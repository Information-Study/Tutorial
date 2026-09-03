---
title: "WAF 概念與 ModSecurity 安裝"
desc: "WAF 在縱深防禦中的位置與限制，以及 ModSecurity v3 + Nginx 的三條安裝路線與 DetectionOnly 上線流程"
aliases: [waf, modsecurity]
tags: [群組/資訊安全, 安全/waf, 主題/安裝]
category: WAF與ModSecurity
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[060-02-02-09-guide-Nginx-安全設定]]"]
updated: 2026-09-03
---

# WAF 概念與 ModSecurity 安裝

> [!abstract] 這篇你會學到
> - 說清楚 WAF **擋得住什麼、擋不住什麼**，以及為什麼它永遠只是「外加的一層」
> - 三種部署位置（反向代理前、與應用同機、雲端 WAF）的取捨
> - ★★★★ ModSecurity **v3 與 v2 的架構差異**：libmodsecurity + connector
> - 三條安裝路線：發行版套件、MyGuard 強化版 NGINX、自行編譯
> - `modsecurity.conf` 的關鍵指令，以及在 Nginx 裡怎麼掛上去
> - ★★★★★ 第一次上線**一定用 `DetectionOnly`**，並確認日誌真的有記到攻擊

---

## 這篇你會學到

本篇是 `090-04` 這一章的第一篇，負責把 **WAF 的定位** 與 **ModSecurity 的安裝** 一次講完。
讀完之後你應該能：

| # | 能力 | 重要度 |
| --- | --- | --- |
| 1 | 對主管解釋「為什麼裝了防火牆還要裝 WAF」 | ★★ |
| 2 | 對開發說明「WAF 不能取代你把 SQL 參數化」 | ★★★★ |
| 3 | 判斷這台機器該用哪一條安裝路線 | ★★★ |
| 4 | 在 Nginx 上完成 ModSecurity v3 安裝並確認模組真的載入 | ★★★★ |
| 5 | 看懂 `modsecurity.conf` 前 20 行每一個指令在做什麼 | ★★★★ |
| 6 | 用 `DetectionOnly` 安全上線，發測試攻擊並在日誌中找到它 | ★★★★★ |
| 7 | 遇到「裝完網站就 500」時知道從哪查起 | ★★★★ |

規則集（OWASP CRS）本身放在 [[090-04-02-guide-OWASP-CRS規則集]]，
誤判調校放在 [[090-04-03-svc-ModSecurity-規則調校與誤判處理]]，
本篇只把引擎裝好、跑起來、能記日誌。

---

## 前置知識

動筆前建議先具備：

- **HTTP 請求的結構**：request line、header、body、query string、multipart。
  沒有這個概念，看稽核日誌會完全看不懂 —— 見 [[010-02-13-guide-網概-HTTP與HTTPS]]。
- **Nginx 基本操作**：`nginx -t`、`nginx -V`、`systemctl reload nginx`、
  設定檔目錄結構 —— 見 [[060-02-02-01-guide-Nginx-安裝與目錄結構]]。
- **反向代理概念**：WAF 幾乎都掛在反向代理上 —— 見 [[060-02-02-04-guide-Nginx-反向代理與負載平衡]]。
- **應用層攻擊的基本樣貌**：SQL Injection、XSS、路徑穿越 ——
  見 [[090-03-02-guide-應用安全-應用層安全]]。
- **WAF 的市場全景與選型**（商用設備 vs 開源 vs 雲端）——
  見 [[090-05-04-guide-資安設備-Web應用防火牆WAF]]。那篇談「買哪一種」，本章談「開源這一種怎麼做」。

> [!tip] 建議的實驗環境 ★★
> 一台 Ubuntu 24.04 LTS 或 Debian 12 的測試 VM，裝好 Nginx，
> 後面接一個隨便什麼 PHP 或靜態站台。**不要拿正式機做第一次安裝**。
> 虛擬機建置見 `050-01` 群組。

---

## 觀念說明

### WAF 是什麼：一台看得懂 HTTP 的過濾器 ★★★

一般防火牆（含次世代防火牆）判斷的是 **IP、port、協定、應用識別**。
它看得到「這是一個往 443 port 的 HTTPS 連線」，但看不到裡面那個
`POST /login.php` 的 `username` 參數塞了 `' OR '1'='1' --`。

WAF 的位置就在這裡：**它把 HTTP 請求解開，逐欄位比對規則**。

```text
使用者 ──HTTP──▶ ┌──────────┐ ──▶ ┌──────────┐ ──▶ ┌──────────┐
                 │ 防火牆    │     │   WAF    │     │  Web App │
                 │ IP/port  │     │ 解析 HTTP │     │  商業邏輯 │
                 └──────────┘     └──────────┘     └──────────┘
                  第 3/4 層         第 7 層          真正的資料
```

WAF 檢查的欄位至少包含：

| 欄位群 | ModSecurity 變數名 | 常見攻擊 |
| --- | --- | --- |
| 請求行與方法 | `REQUEST_METHOD`、`REQUEST_URI` | 非法方法、路徑穿越 |
| 查詢字串參數 | `ARGS_GET` | SQLi、XSS |
| 表單／JSON 本體 | `ARGS_POST`、`REQUEST_BODY` | SQLi、RCE |
| 標頭 | `REQUEST_HEADERS` | Log4Shell、Shellshock、掃描器指紋 |
| Cookie | `REQUEST_COOKIES` | Session Fixation |
| 上傳檔名與內容 | `FILES`、`FILES_NAMES` | Web shell 上傳 |
| 回應本體 | `RESPONSE_BODY` | 資料庫錯誤訊息外洩、目錄列表外洩 |

### ★★★★ WAF 擋什麼、不擋什麼

這張表是全篇最需要背下來的東西。**寫進導入報告，避免主管誤以為裝了 WAF 就安全了。**

| 情境 | WAF 擋得住嗎 | 說明 |
| --- | --- | --- |
| 典型 SQL Injection（`' OR 1=1 --`） | ✅ 大多擋得住 | 有明顯特徵字串 ★★★ |
| 反射型 XSS（URL 帶 `<script>`） | ✅ 大多擋得住 | ★★★ |
| 路徑穿越（`../../etc/passwd`） | ✅ 擋得住 | ★★★ |
| 遠端指令執行（`;cat /etc/passwd`） | ✅ 大多擋得住 | ★★★ |
| 已知 CVE 的固定 payload | ✅ **虛擬修補** | ★★★★ 這是 WAF 最有價值的用途 |
| 自動化掃描器（sqlmap、nikto） | ✅ 靠 User-Agent 與行為 | ★★ |
| **邏輯漏洞**：把訂單金額改成 `-1` | ❌ 完全擋不住 | ★★★★★ 那是合法的數字 |
| **越權存取**：改 URL 的 `user_id=123` 看別人資料 | ❌ 擋不住 | ★★★★★ IDOR 是應用層責任 |
| **弱密碼被猜中** | ❌ 擋不住 | 只能靠速率限制減緩 |
| **合法帳號的內部濫用** | ❌ 擋不住 | 那是稽核與權限的事 |
| **加密流量中的攻擊（WAF 在 TLS 後面沒解密）** | ❌ 擋不住 | ★★★★ 部署位置決定 |
| 高度客製化、無特徵的注入 | ⚠️ 不一定 | 取決於 Paranoia Level |
| 業務層 DDoS（大量合法請求） | ⚠️ 部分 | 需要專門的速率限制 |

> [!danger] ★★★★★ WAF 不能取代應用本身的安全
> WAF 是**外加的一層**（bolt-on），不是修補程式。它做的是
> 「在請求進到應用之前，把長得像攻擊的東西攔下來」。
>
> - 它**不知道**你的 SQL 有沒有參數化
> - 它**不知道**你的權限檢查寫在哪一行
> - 它只認得 payload 的**外觀**，攻擊者改寫 payload 就可能繞過
>
> 正確的說法是：**「應用層防護是主體，WAF 是保險」**。
> 應用層該做的事（參數化查詢、輸出編碼、權限檢查、CSRF token）
> 一項都不能因為裝了 WAF 而省略 —— 見 [[090-03-02-guide-應用安全-應用層安全]]。
>
> 現場最常見的災難句型是：「反正有 WAF，這個漏洞先不修。」
> 半年後那個漏洞被用一個 WAF 沒見過的變形 payload 打穿，
> 而且因為長期沒人看 WAF 日誌，沒有人發現。

### WAF 唯一無可取代的用途：虛擬修補 ★★★★

當出現這種狀況：

- 廠商開發的系統爆出 CVE，但**廠商合約到期／原開發者離職／改版要三個月**
- 系統跑在無法升級的舊 PHP 上
- 修補需要停機，但這是不能停的服務

WAF 可以在**不動應用程式碼**的情況下，寫一條規則把該 CVE 的 payload 特徵擋掉，
爭取到修補的時間窗。這叫 **virtual patching（虛擬修補）**。
機關環境有大量委外系統，這是 WAF 最實際的價值 ——
搭配 [[090-03-06-guide-應用安全-委外系統上線前資安檢測]] 一起看。

### 三種部署位置 ★★★★

#### A. 反向代理前（獨立 WAF 節點）

```text
Internet ──▶ [Nginx + ModSecurity]  ──▶ [App Server 1]
              反向代理 + WAF          ──▶ [App Server 2]
```

| 面向 | 評價 |
| --- | --- |
| 對後端應用侵入性 | ✅ 零，應用完全不用改 |
| 集中管理多站台 | ✅ 一台管全部 |
| 可否看到明文 | ✅ TLS 在此終止，看得到明文 ★★★★ |
| 真實來源 IP | ⚠️ 後端要靠 `X-Forwarded-For` |
| 單點故障 | ❌ 這台掛了全部掛，要做 HA |
| 效能瓶頸 | ⚠️ 全站流量都經過它 |

**機關環境最推薦這一種。** 一台反向代理保護後面十幾個委外系統，
而且那些系統你根本不能動。

#### B. 與應用同機（模組式）

```text
Internet ──▶ [Nginx + ModSecurity + PHP-FPM]  同一台
```

| 面向 | 評價 |
| --- | --- |
| 部署簡單 | ✅ 一台就好 |
| 每站台可獨立調規則 | ✅ ★★★ |
| 資源競爭 | ❌ WAF 吃掉應用的 CPU |
| 站台多時管理成本 | ❌ 每台都要調一次 |

適合單一站台、或是想針對這個站台做非常細緻調校的情境。

#### C. 雲端 WAF（DNS 導流）

```text
使用者 ──▶ [雲端 WAF/CDN] ──▶ 你的機房
```

| 面向 | 評價 |
| --- | --- |
| 免自建、自動更新規則 | ✅ |
| 附帶 DDoS 清洗與 CDN | ✅ ★★★ |
| 流量與明文交給第三方 | ❌ ★★★★★ 機關資料落地與個資議題 |
| 來源 IP 白名單繞過 | ❌ 有人直接連你的 origin IP 就繞過了 |
| 費用 | 依流量計價 |

> [!warning] ★★★★ 用雲端 WAF 一定要鎖 origin
> 若不在源站防火牆上**只允許雲端 WAF 的 IP 段**，攻擊者只要查到你的真實 IP
> 就完全繞過 WAF。這是雲端 WAF 導入最常被忽略的一步。
> 機關環境還要先確認資料是否允許經過境外節點。

### ★★★★ ModSecurity v2 與 v3 的差別

這一段是安裝踩雷的根源。**網路上大量教學是 v2 的，語法與檔名都不一樣。**

```text
【 ModSecurity v2 】
  ┌─────────────────────────────┐
  │  Apache httpd               │
  │   └── mod_security2.so      │  ← 直接是一個 Apache 模組
  │        （引擎與規則都在裡面） │     只能給 Apache 用
  └─────────────────────────────┘

【 ModSecurity v3 】
  ┌───────────────────┐        ┌──────────────────────────┐
  │  libmodsecurity   │◀───────│ ModSecurity-nginx        │ ← Nginx connector
  │  （獨立 C++ 函式庫）│◀───────│ ModSecurity-apache       │ ← Apache connector
  │  規則解析與比對      │◀───────│ 其他 connector           │
  └───────────────────┘        └──────────────────────────┘
```

| 項目 | v2 | v3 |
| --- | --- | --- |
| 架構 | Apache 模組 | ★★★★ 獨立函式庫 `libmodsecurity` + 各伺服器 connector |
| 支援 Nginx | ❌ 只有非官方移植 | ✅ 官方 `ModSecurity-nginx` |
| 模組檔名 | `mod_security2.so` | `ngx_http_modsecurity_module.so`（Nginx） |
| Nginx 掛載指令 | 不適用 | `modsecurity on;` + `modsecurity_rules_file` |
| 效能 | 較慢 | ★★★ 一般較快，多執行緒友善 |
| 指令相容性 | — | ★★★★ **大部分相容，但少數 v2 指令 v3 未實作**，照抄 v2 設定檔會啟動失敗 |
| 專案位置 | 已維護模式 | 現由 OWASP 接手維護（`owasp-modsecurity/ModSecurity`） |

> [!warning] ★★★★ 找教學時先確認版本
> 判斷方式：
> - 文章裡出現 `LoadModule security2_module` → **v2、Apache**
> - 文章裡出現 `modsecurity_rules_file` → **v3、Nginx**
> - 文章裡出現 `SecRuleEngine` → 兩者都有，這個指令不能拿來判斷
>
> 少數 v2 指令（例如某些與回應內容注入、guardian log 相關的指令）在 v3 沒有實作。
> 好消息是：**啟動時會直接報出是哪一行不認得**，照著刪掉即可。

> [!info]- Apache 對照：該用 v2 還是 v3
> Apache 的官方 v3 connector（`ModSecurity-apache`）成熟度不如 Nginx 版，
> 而且多數發行版套件庫提供的仍然是 **v2 的 `libapache2-mod-security2`**。
>
> ```bash
> # Ubuntu / Debian：安裝 Apache 的 ModSecurity v2
> sudo apt update
> sudo apt install -y libapache2-mod-security2
> sudo a2enmod security2
> sudo cp /etc/modsecurity/modsecurity.conf-recommended \
>         /etc/modsecurity/modsecurity.conf
> sudo systemctl restart apache2
> ```
>
> 確認模組載入：
>
> ```bash
> apachectl -M | grep -i security
> # 預期輸出：
> #  security2_module (shared)
> ```
>
> v2 的規則語法與 CRS 用法與 v3 幾乎一致，本章後續談的
> `SecRuleEngine`、`SecRuleRemoveById`、CRS 設定，**Apache 這邊都通用**。
> 差別只在「怎麼掛上去」。Apache 模組管理見 [[060-02-03-03-guide-Apache-模組與MPM]]。

---

## 安裝或基礎操作

### 安裝前的決策：三條路線怎麼選 ★★★★

| 路線 | 難度 | 版本新舊 | 升級維護 | 適用 |
| --- | --- | --- | --- | --- |
| A. 發行版套件 | ★ 最簡單 | ⚠️ 可能落後一兩個版本 | ✅ `apt upgrade` 就好 | 內網、非關鍵站台、快速驗證 |
| B. ★★★★ MyGuard 套件庫強化版 NGINX | ★★ 加個套件庫 | ✅ 每日重建、mainline | ✅ 走 apt | **本手冊推薦**：對外網站 |
| C. 自行編譯 | ★★★★ 最麻煩 | ✅ 完全自主 | ❌ Nginx 升級要重編 | 有特殊模組需求、需通過特定稽核 |

> [!tip] ★★★ 決策一句話
> **能用 B 就用 B**；不能加第三方套件庫（機關內網封鎖外部 repo）就用 A；
> A 的版本被稽核判定過舊、或你需要同時掛一堆自訂模組，才用 C。

---

### 路線 A：發行版套件（最省事）

先確認你的發行版有沒有 Nginx 的 ModSecurity 動態模組。

```bash
sudo apt update
apt-cache search modsecurity
```

可能會看到類似輸出：

```text
libmodsecurity3 - ModSecurity v3 library component
libmodsecurity-dev - ModSecurity v3 library component (development files)
libapache2-mod-security2 - Tighten web applications security for Apache
libnginx-mod-http-modsecurity - ModSecurity v3 dynamic module for Nginx
modsecurity-crs - OWASP ModSecurity Core Rule Set
```

> [!warning] ★★★ 不是每個發行版都有 `libnginx-mod-http-modsecurity`
> 這個套件在部分 Debian／Ubuntu 版本才有。**搜尋不到就走路線 B 或 C**，
> 不要自己去找來路不明的 `.deb` 安裝。

安裝：

```bash
sudo apt install -y nginx libnginx-mod-http-modsecurity modsecurity-crs
```

安裝完成後確認：

```bash
# 1. 模組檔案在不在
ls -l /usr/lib/nginx/modules/ | grep -i modsec
# 預期輸出（路徑與檔名依發行版可能略有不同）：
# -rw-r--r-- 1 root root 254680 Jan  1 00:00 ngx_http_modsecurity_module.so

# 2. 動態模組載入設定
ls /etc/nginx/modules-enabled/
# 預期會看到類似：
# 50-mod-http-modsecurity.conf

# 3. 設定檔範本
ls /etc/modsecurity/
# 預期輸出：
# modsecurity.conf-recommended  unicode.mapping
```

> [!note] ★★★ 為什麼是 `modsecurity.conf-recommended`
> 套件**故意不直接給你 `modsecurity.conf`**，因為那份範本裡
> `SecRuleEngine` 預設是 `DetectionOnly`，而且套件維護者不想幫你決定要不要開。
> 你必須自己複製一份、自己決定模式 —— 這個設計是刻意的。

---

### 路線 B：MyGuard 套件庫的強化版 NGINX ★★★★（推薦）

`deb.myguard.nl` 是 myguard-labs 維護的第三方 Debian／Ubuntu APT 套件庫，
提供**強化版 NGINX 與 Angie**：mainline 版本、HTTP/3 (QUIC)、kTLS、Brotli、Zstandard，
以及**已經內建編譯好的 ModSecurity v3 動態模組**與 100 多個其他模組，每日重建。

用這一條路的好處：

| 好處 | 說明 |
| --- | --- |
| 免編譯 | ★★★★ ModSecurity 模組已經跟 Nginx 版本對齊編好 |
| 版本新 | ★★★ mainline，跟得上 CVE 修補 |
| 走 apt 升級 | ★★★★ Nginx 升級時模組會一起升，不會 ABI 不合 |
| 附加防護模組 | `http-shield`（已知攻擊鏈攔截）、`error-abuse`（404 濫用限流）可與 CRS 互補 |

完整介紹見 [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]]，
整章導覽見 [[060-02-05-00-idx-MyGuard與Angie]]。

> [!warning] ★★★★ 動筆前先去官網確認當前套件庫路徑與金鑰
> 第三方套件庫的 URL、GPG 金鑰指紋、支援的 codename **會變**。
> 加入之前務必到 <https://deb.myguard.nl/how-to-use/> 對照官方當前寫法，
> 不要照抄任何一篇（包含這篇）寫死的路徑。
>
> 加入第三方 APT 套件庫的通用安全做法（金鑰放 `/etc/apt/keyrings/`、
> 用 `signed-by=` 綁定、必要時用 apt pinning 限制只取特定套件）
> 見 `020-02` 群組的第三方套件庫實務篇。

> [!warning] 未實機驗證
> 以下流程為依官方文件整理的**示意**，實際指令以 MyGuard 官網當前說明為準。

```bash
# 1) 準備 keyring 目錄
sudo install -d -m 0755 /etc/apt/keyrings

# 2) 依官網說明匯入 GPG 金鑰（實際 URL 以官網為準）
#    務必核對金鑰指紋

# 3) 依官網說明寫入 sources 檔，並帶上 signed-by=
#    /etc/apt/sources.list.d/myguard.sources

# 4) 更新並安裝
sudo apt update
sudo apt install -y nginx

# 5) 安裝 ModSecurity 動態模組（套件名以官網為準）
apt-cache search nginx-module | grep -i modsec
```

安裝後的驗證方式與路線 A 相同：確認 `.so` 檔存在、確認 `load_module` 生效。

> [!tip] ★★★ MyGuard 的 http-shield 與 CRS 的關係
> `http-shield` 攔的是**已知攻擊鏈的固定特徵**（Log4Shell、Shellshock、常見 RCE 鏈），
> 反應快、誤判低；CRS 攔的是**通用的注入模式**，覆蓋廣但誤判高。
> 兩者是互補而非取代，可以同時開。細節見 [[060-02-05-04-guide-http-shield攻擊攔截]]
> 與 [[060-02-05-08-guide-MyGuard-MyGuard實戰組合]]。

---

### 路線 C：自行編譯 ★★★★

只有在前兩條路都不可行時才走。整個流程分三大步：
**編 libmodsecurity → 編 connector → 掛進 Nginx**。

> [!danger] ★★★★★ 不要在正式機上編譯
> 編譯會裝進一大堆 `-dev` 套件與編譯工具鏈，正式機上多裝這些會擴大攻擊面，
> 也可能違反機關的系統強化基準（見 [[090-02-08-guide-防護-系統強化與稽核]]）。
> **在同版本的建置機上編好，產出 `.so` 再複製過去。**

#### C-1 安裝建置相依套件

```bash
sudo apt update
sudo apt install -y \
  git build-essential automake autoconf libtool pkg-config \
  libcurl4-openssl-dev libxml2-dev libyajl-dev \
  liblmdb-dev libgeoip-dev libpcre2-dev zlib1g-dev libssl-dev \
  wget
```

> [!warning] 未實機驗證
> 相依套件清單會隨 ModSecurity 版本變動（例如 PCRE 從 pcre 換到 pcre2 的過渡）。
> **以你要編的那個版本的 `README.md` 與 `configure` 輸出為準**；
> `./configure` 跑完會列出每個可選功能是 enabled 還是 disabled，照著補套件。

#### C-2 編譯 libmodsecurity

```bash
cd /usr/local/src
sudo git clone --depth 1 -b v3/master \
  https://github.com/owasp-modsecurity/ModSecurity
cd ModSecurity
sudo git submodule init
sudo git submodule update
sudo ./build.sh
sudo ./configure
sudo make -j"$(nproc)"
sudo make install
```

`./configure` 結尾會印出功能摘要，**要停下來看**：

```text
   ModSecurity - v3.x.x
     ...
     PCRE2 ....................................enabled
     LibXML2 ..................................enabled
     YAJL .....................................enabled
     LMDB .....................................enabled
     GeoIP ....................................disabled
```

> [!warning] ★★★ `LibXML2` 或 `YAJL` 顯示 disabled 要停下來
> - `LibXML2` disabled → **XML 本體無法解析**，SOAP 類 API 完全不受保護
> - `YAJL` disabled → ★★★★ **JSON 本體無法解析**，現代 API 的參數 WAF 全看不到，
>   等於裝了個看不到重點的 WAF。補 `libyajl-dev` 後重跑 `./configure`。

安裝結果預設在 `/usr/local/modsecurity/`：

```bash
ls /usr/local/modsecurity/lib/
# 預期輸出：
# libmodsecurity.a  libmodsecurity.la  libmodsecurity.so  libmodsecurity.so.3 ...
```

#### C-3 編譯 Nginx connector

★★★★ **關鍵**：connector 必須用**跟現有 Nginx 完全相同的原始碼版本與 configure 參數**編譯，
否則載入時會因 ABI 不合而失敗。

```bash
# 1) 取得現有 Nginx 的版本與編譯參數
nginx -V
```

輸出長這樣（重點是最後那一長串 `configure arguments`）：

```text
nginx version: nginx/1.26.2
built by gcc 13.2.0
built with OpenSSL 3.0.13
TLS SNI support enabled
configure arguments: --prefix=/usr/share/nginx --conf-path=/etc/nginx/nginx.conf ...
```

```bash
# 2) 下載完全相同版本的 Nginx 原始碼
cd /usr/local/src
sudo wget https://nginx.org/download/nginx-1.26.2.tar.gz
sudo tar zxf nginx-1.26.2.tar.gz

# 3) 取得 connector 原始碼
sudo git clone --depth 1 \
  https://github.com/owasp-modsecurity/ModSecurity-nginx.git

# 4) 用原本的 configure 參數 + --add-dynamic-module 重跑
cd /usr/local/src/nginx-1.26.2
sudo ./configure <把上面 nginx -V 那串參數原封不動貼進來> \
  --add-dynamic-module=/usr/local/src/ModSecurity-nginx

# 5) 只編模組，不要 make install（不要覆蓋現有 Nginx）
sudo make modules
```

產出：

```bash
ls -l objs/*.so
# 預期輸出：
# -rwxr-xr-x 1 root root 1234567 ... objs/ngx_http_modsecurity_module.so
```

複製到模組目錄：

```bash
sudo cp objs/ngx_http_modsecurity_module.so /usr/lib/nginx/modules/
sudo chmod 644 /usr/lib/nginx/modules/ngx_http_modsecurity_module.so
```

> [!danger] ★★★★★ Nginx 每次升級都要重編模組
> 走路線 C 之後，`apt upgrade` 升級 Nginx **會讓舊模組載入失敗，Nginx 直接起不來**。
> 錯誤訊息是：
>
> ```text
> nginx: [emerg] module "ngx_http_modsecurity_module.so" version 1026002
> instead of 1026003 in /etc/nginx/nginx.conf:1
> ```
>
> 因應方式二選一：
> 1. 把 Nginx 套件 hold 住：`sudo apt-mark hold nginx`，升級改為人工排程
> 2. 建立「升 Nginx 必重編模組」的 SOP 並寫進變更管理流程
>
> **這就是為什麼推薦路線 B** —— MyGuard 幫你處理了版本對齊。

---

### 掛進 Nginx：三個層次的設定

#### 第 1 層：載入動態模組

```nginx
# /etc/nginx/nginx.conf 的「最上方」，必須在任何 http {} 之前
load_module modules/ngx_http_modsecurity_module.so;
```

路線 A 的套件通常已經幫你放好在 `/etc/nginx/modules-enabled/`，不用自己寫。

```bash
sudo nginx -t
# 預期輸出：
# nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# nginx: configuration file /etc/nginx/nginx.conf test is successful
```

#### 第 2 層：主設定檔

```bash
sudo mkdir -p /etc/nginx/modsec
sudo cp /etc/modsecurity/modsecurity.conf-recommended \
        /etc/nginx/modsec/modsecurity.conf
sudo cp /etc/modsecurity/unicode.mapping /etc/nginx/modsec/
```

> [!warning] ★★★★ `unicode.mapping` 少了會啟動失敗
> `modsecurity.conf` 裡的 `SecUnicodeMapFile unicode.mapping 20127`
> 是相對路徑，**檔案必須跟設定檔放在同一個目錄**。忘了複製會看到：
>
> ```text
> nginx: [emerg] "modsecurity_rules_file" directive Rules error ...
> File not found: unicode.mapping
> ```

建立總入口 `main.conf`：

```nginx
# /etc/nginx/modsec/main.conf
# 1) 引擎主設定
Include /etc/nginx/modsec/modsecurity.conf

# 2) 規則集（CRS）—— 下一篇才裝，現在先留註解
# Include /etc/nginx/modsec/crs/crs-setup.conf
# Include /etc/nginx/modsec/crs/rules/*.conf
```

> [!tip] ★★★ 為什麼要多一層 `main.conf`
> 讓 Nginx 設定只指向一個檔案，之後不管加 CRS、加自訂規則、加排除規則，
> **都只改 `main.conf` 的 Include 順序**，不用動 Nginx 設定。
> 而且 Include 的**順序就是規則載入順序**，這在誤判排除時是關鍵
> —— 見 [[090-04-03-svc-ModSecurity-規則調校與誤判處理]]。

#### 第 3 層：在 server／location 啟用

```nginx
server {
    listen 443 ssl;
    server_name app.example.gov.tw;

    # 啟用 ModSecurity
    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsec/main.conf;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 靜態資源不需要過 WAF，關掉可省下大量 CPU ★★★
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|woff2?|svg)$ {
        modsecurity off;
        root /var/www/app/public;
        expires 7d;
    }
}
```

ModSecurity-nginx 提供的指令只有這幾個：

| 指令 | 可用位置 | 說明 |
| --- | --- | --- |
| `modsecurity on\|off;` | http、server、location | ★★★★ 總開關 |
| `modsecurity_rules_file <path>;` | http、server、location | 從檔案載入規則 |
| `modsecurity_rules '<內容>';` | http、server、location | ★★ 直接內嵌規則字串 |
| `modsecurity_transaction_id <var>;` | http、server、location | 指定交易 ID 變數，方便與存取日誌對齊 |

> [!tip] ★★★★ 把 transaction id 串進存取日誌
> 這樣一筆 Nginx access log 就能直接對到一筆稽核日誌，除錯效率差非常多。
>
> ```nginx
> http {
>     log_format waf '$remote_addr - $remote_user [$time_local] '
>                    '"$request" $status $body_bytes_sent '
>                    '"$http_referer" "$http_user_agent" '
>                    'txid=$request_id';
>
>     modsecurity_transaction_id "$request_id";
>     access_log /var/log/nginx/access.log waf;
> }
> ```
>
> 日誌關聯的完整做法見 [[090-04-04-guide-ModSecurity-日誌分析與監控]]。

---

### `modsecurity.conf` 關鍵指令逐條解說 ★★★★

打開 `/etc/nginx/modsec/modsecurity.conf`，重點在這幾行。

#### `SecRuleEngine` —— 全篇最重要的一個指令 ★★★★★

```apache
SecRuleEngine DetectionOnly
```

| 值 | 行為 | 何時用 |
| --- | --- | --- |
| `Off` | 完全不執行規則，等於沒裝 | ★★ 緊急時的斷路器 |
| `DetectionOnly` | ★★★★★ 執行規則、**寫日誌、但不阻擋** | **第一次上線一律用這個** |
| `On` | 執行規則並依 `disruptive action` 阻擋 | 調校完成之後 |

> [!danger] ★★★★★ 第一次上線一定要用 `DetectionOnly`
> 剛裝好、還沒經過任何調校就直接寫 `SecRuleEngine On`，結果幾乎必然是：
>
> 1. 後台編輯器儲存文章 → HTML 內容被判成 XSS → **403**
> 2. 使用者密碼含 `<` 或 `'` → 登入被擋 → **打不進系統**
> 3. 上傳 Word 檔 → multipart 內容命中規則 → **403**
> 4. JSON API 的中文欄位編碼被誤判 → **前端整個壞掉**
> 5. 一小時內湧入十幾通客訴電話
> 6. 你在壓力下把 WAF 整個關掉，從此再也沒人敢打開
>
> 這就是機關導入 WAF 最典型的失敗劇本。
> **正確做法：`DetectionOnly` 跑至少兩週 → 統計誤判 → 逐一排除 → 才切 `On`。**
> 完整節奏見 [[090-04-03-svc-ModSecurity-規則調校與誤判處理]]。

#### 請求本體相關

```apache
SecRequestBodyAccess On
SecRequestBodyLimit 13107200
SecRequestBodyNoFilesLimit 131072
SecRequestBodyLimitAction Reject
```

| 指令 | 意義 | 注意 |
| --- | --- | --- |
| `SecRequestBodyAccess On` | ★★★★ **緩衝並檢查請求本體**。關掉的話所有 POST 參數都不檢查 | 幾乎一定要 On |
| `SecRequestBodyLimit` | 本體大小上限（含上傳檔案），預設約 12.5 MB | ★★★★ 有檔案上傳功能一定要調大 |
| `SecRequestBodyNoFilesLimit` | 扣掉上傳檔案後的本體上限，預設 128 KB | ★★★ 大型 JSON API 可能不夠 |
| `SecRequestBodyLimitAction` | 超過上限怎麼辦：`Reject`／`ProcessPartial` | ★★★★ 見下方警告 |

> [!danger] ★★★★ `SecRequestBodyLimitAction ProcessPartial` 是一個安全取捨
> - `Reject`：超過大小直接回 413，**安全但會擋掉合法的大檔上傳**
> - `ProcessPartial`：只檢查前面那一段，**後面的內容完全不檢查** ——
>   攻擊者只要在 payload 前面塞夠多無害填充字元就能繞過 WAF
>
> 正確做法是**調大 `SecRequestBodyLimit` 到符合業務需求的值，並維持 `Reject`**，
> 而不是改成 `ProcessPartial`。

#### 回應本體相關

```apache
SecResponseBodyAccess On
SecResponseBodyMimeType text/plain text/html text/xml
SecResponseBodyLimit 524288
SecResponseBodyLimitAction ProcessPartial
```

檢查**回應**是為了抓資料外洩（資料庫錯誤訊息、堆疊追蹤、信用卡號樣式）。

> [!warning] ★★★ 回應檢查很吃記憶體
> 每個回應都要整份緩衝進記憶體才能比對。高流量站台若只在意「擋攻擊」，
> 可以把 `SecResponseBodyAccess` 設成 `Off` 換取效能。
> 取捨細節見 [[090-04-05-guide-ModSecurity-效能與實戰情境]]。
>
> 若你的 API 回應是 JSON，記得把 `application/json` 加進 `SecResponseBodyMimeType`，
> 否則回應檢查對 API 完全不生效。

#### 稽核日誌相關 ★★★★

```apache
SecAuditEngine RelevantOnly
SecAuditLogRelevantStatus "^(?:5|4(?!04))"
SecAuditLogParts ABIJDEFHZ
SecAuditLogType Serial
SecAuditLog /var/log/modsec_audit.log
```

| 指令 | 值 | 說明 |
| --- | --- | --- |
| `SecAuditEngine` | `On` | 記錄**每一個**請求 → ★★★★★ 硬碟會爆 |
| | `Off` | 完全不記 → 等於白裝 |
| | `RelevantOnly` | ★★★★ 只記命中規則或狀態碼符合的 → **正式環境用這個** |
| `SecAuditLogRelevantStatus` | 正規表示式 | 上面的預設值意思是「5xx 和 4xx 都記，但排除 404」 |
| `SecAuditLogParts` | 字母組合 | 見下表 |
| `SecAuditLogType` | `Serial` | 全部寫同一個檔，簡單但高並發時會鎖爭用 |
| | `Concurrent` | 一個交易一個檔，配合 `SecAuditLogStorageDir` |

`SecAuditLogParts` 各段落：

| 代號 | 內容 | 常用 |
| --- | --- | --- |
| `A` | 稽核日誌標頭（時間、來源 IP、交易 ID） | ★★★★ 必留 |
| `B` | 請求標頭 | ★★★★ 必留 |
| `C` | 請求本體 | ★★★ 含個資風險 |
| `D` | 保留（未實作） | — |
| `E` | 中介回應本體 | ★★ |
| `F` | 最終回應標頭 | ★★ |
| `G` | 保留（未實作） | — |
| `H` | ★★★★★ 稽核日誌結尾：**命中的規則訊息、分數、處理時間** | **調校時最重要的一段** |
| `I` | `C` 的精簡替代（multipart 不含檔案內容） | ★★★ |
| `J` | 上傳檔案資訊 | ★★★ |
| `K` | 所有比對到的規則 | ★★ 很吵 |
| `Z` | 結尾邊界（必須有） | 必留 |

> [!danger] ★★★★ 稽核日誌含個資
> `C` 與 `I` 會把 POST 本體整個寫進日誌 —— **包含使用者輸入的帳號、身分證號、
> 甚至明文密碼欄位**。機關環境務必：
> - 檔案權限設 `0640`、擁有者 `root:adm`
> - 納入個資盤點與保存期限管理
> - 設定 logrotate，見 [[100-01-02-guide-日誌-日誌集中與輪替]]
>
> 敏感欄位的遮蔽做法見 [[090-04-04-guide-ModSecurity-日誌分析與監控]]。

#### 其他常用指令

```apache
SecTmpDir /tmp/modsecurity/tmp
SecDataDir /tmp/modsecurity/data
SecUploadDir /tmp/modsecurity/upload
SecDebugLog /var/log/modsec_debug.log
SecDebugLogLevel 0
SecStatusEngine Off
SecPcreMatchLimit 100000
SecPcreMatchLimitRecursion 100000
```

| 指令 | 說明 |
| --- | --- |
| `SecTmpDir` / `SecDataDir` | ★★★ 目錄不存在或權限不對，Nginx worker 會拒絕啟動 |
| `SecDebugLogLevel` | 0=關、1~3=錯誤、**9=極詳細**。★★★★★ 正式環境必須 0～3，開 9 硬碟會在數小時內滿 |
| `SecStatusEngine` | ★★★ `On` 會回報版本資訊到外部主機，**機關環境一律 `Off`** |
| `SecPcreMatchLimit` | 正規表示式比對上限，太小會出現 `Execution error - PCRE limits exceeded` |

建立所需目錄：

```bash
sudo mkdir -p /tmp/modsecurity/{tmp,data,upload}
sudo chown -R www-data:www-data /tmp/modsecurity
sudo chmod 700 /tmp/modsecurity/{tmp,data,upload}
```

> [!warning] ★★★ 放在 `/tmp` 有兩個坑
> 1. systemd 的 `PrivateTmp=true` 會讓 Nginx 看到的 `/tmp` 跟你 shell 看到的不是同一個
> 2. `/tmp` 可能被開機清空
>
> 正式環境建議改到 `/var/cache/modsecurity/` 底下並建好 tmpfiles 規則。

---

## 進階應用

### 只在特定 location 啟用 WAF ★★★

WAF 是有成本的。把它用在該用的地方：

```nginx
server {
    listen 443 ssl;
    server_name app.example.gov.tw;

    # 預設關閉
    modsecurity off;

    # 只有動態程式路徑開啟
    location /api/ {
        modsecurity on;
        modsecurity_rules_file /etc/nginx/modsec/main.conf;
        proxy_pass http://127.0.0.1:8080;
    }

    location /admin/ {
        modsecurity on;
        modsecurity_rules_file /etc/nginx/modsec/main.conf;
        proxy_pass http://127.0.0.1:8080;
    }

    # 靜態檔案完全不過 WAF
    location / {
        root /var/www/app/public;
        try_files $uri $uri/ /index.php?$query_string;
    }
}
```

> [!warning] ★★★★ 別把 `try_files` 導到的 PHP 入口漏掉
> 上面這種寫法若 `/index.php` 落在沒開 WAF 的 `location /` 裡，
> **整個應用其實都沒被保護**。設定完務必用實際攻擊請求驗證（見實戰範例）。

### 用 `modsecurity_rules` 內嵌少量規則 ★★

臨時針對某個 location 加一條規則，不想動檔案時：

```nginx
location /upload/ {
    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsec/main.conf;

    # 這個路徑允許較大的請求本體
    modsecurity_rules '
        SecRequestBodyLimit 104857600
    ';
    proxy_pass http://127.0.0.1:8080;
}
```

> [!tip] ★★ 內嵌規則只適合一兩行
> 超過三行就該搬到檔案裡，否則 Nginx 設定會變得無法維護，
> 而且錯誤訊息只會指到「第幾行」，很難對。

### 真實來源 IP：WAF 在 CDN 或負載平衡後面 ★★★★

如果 Nginx 前面還有一層（F5、雲端 CDN、另一台 LB），
ModSecurity 看到的 `REMOTE_ADDR` 會是那台前置設備的 IP，
結果就是**所有規則的 IP 相關判斷全部失效、封鎖名單也封不到人**。

```nginx
http {
    # 信任前置設備的網段
    set_real_ip_from 10.20.0.0/24;
    real_ip_header   X-Forwarded-For;
    real_ip_recursive on;
}
```

> [!danger] ★★★★★ `set_real_ip_from` 絕對不能寫 `0.0.0.0/0`
> 那等於「相信任何人送來的 `X-Forwarded-For`」，攻擊者可以隨手偽造來源 IP，
> 讓你的封鎖清單與稽核日誌全部失真，也可能偽裝成內網 IP 繞過 IP 白名單規則。
> **只填你確實控制的前置設備網段。**

### 自訂一條最簡單的規則 ★★★

在還沒裝 CRS 之前，可以先用一條自訂規則驗證引擎會不會動：

```apache
# /etc/nginx/modsec/00-local-test.conf
SecRule ARGS:testparam "@contains modsectest" \
    "id:1000001,\
     phase:2,\
     deny,\
     status:403,\
     log,\
     msg:'Local ModSecurity smoke test rule'"
```

規則語法拆解：

| 部分 | 意義 |
| --- | --- |
| `SecRule` | 規則指令 |
| `ARGS:testparam` | **變數**：要檢查哪裡 —— 名為 `testparam` 的參數 |
| `"@contains modsectest"` | **運算子**：怎麼比對 |
| `id:1000001` | ★★★★ 規則 ID，**必填且全域唯一**。自訂規則建議用 1000000 以上避開 CRS |
| `phase:2` | ★★★ 在哪個階段執行（見下表） |
| `deny,status:403` | **中斷動作**（disruptive action） |
| `log,msg:'...'` | 非中斷動作：寫日誌與訊息 |

處理階段：

| phase | 時機 | 看得到什麼 |
| --- | --- | --- |
| 1 | 請求標頭讀完 | URI、方法、標頭、Cookie ★★★ |
| 2 | 請求本體讀完 | ★★★★ 上面全部 + POST/JSON 參數。**大部分規則在這裡** |
| 3 | 回應標頭產生 | 回應狀態碼與標頭 |
| 4 | 回應本體產生 | ★★★ 回應內容，用於偵測外洩 |
| 5 | 記錄階段 | ★★ 只能寫日誌，不能阻擋 |

> [!warning] ★★★★ `phase` 選錯規則就不會生效
> 想檢查 POST 參數卻寫 `phase:1`，那時候本體根本還沒讀進來，規則永遠不會命中。
> **不確定就寫 `phase:2`。**

---

## 完整實戰範例

**目標**：在一台乾淨的 Ubuntu 24.04 上，用套件路線裝好 Nginx + ModSecurity v3，
以 `DetectionOnly` 啟動，發一個 SQL Injection 測試請求，並在稽核日誌中找到它。

**環境假設**

| 項目 | 值 |
| --- | --- |
| OS | Ubuntu 24.04 LTS |
| 主機 | `waf-lab`，IP `192.168.56.20` |
| 站台 | `http://waf-lab.local/`（實驗用，先不上 TLS） |
| 後端 | 先用靜態頁面代替，重點是驗證 WAF 有沒有攔到 |

### 步驟 1：安裝

```bash
sudo apt update
sudo apt install -y nginx
apt-cache policy libnginx-mod-http-modsecurity
```

```text
libnginx-mod-http-modsecurity:
  Installed: (none)
  Candidate: 1.0.3-1build2
  Version table:
     1.0.3-1build2 500
        500 http://archive.ubuntu.com/ubuntu noble/universe amd64 Packages
```

看到 Candidate 有值就可以裝：

```bash
sudo apt install -y libnginx-mod-http-modsecurity
```

> [!tip] ★★★ 如果 Candidate 是 `(none)`
> 代表這個發行版沒提供，改走路線 B（MyGuard）或路線 C（自行編譯）。
> 不要去下載別人打包的 `.deb`。

### 步驟 2：確認模組載入

```bash
ls /etc/nginx/modules-enabled/
```

```text
50-mod-http-modsecurity.conf
```

```bash
cat /etc/nginx/modules-enabled/50-mod-http-modsecurity.conf
```

```text
load_module modules/ngx_http_modsecurity_module.so;
```

```bash
sudo nginx -t
```

```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

★★★★ 如果這一步就失敗，後面全部不用做。錯誤訊息通常是找不到 `.so` 檔或版本不合。

### 步驟 3：建立 ModSecurity 設定

```bash
sudo mkdir -p /etc/nginx/modsec
sudo cp /etc/modsecurity/modsecurity.conf-recommended \
        /etc/nginx/modsec/modsecurity.conf
sudo cp /etc/modsecurity/unicode.mapping /etc/nginx/modsec/
```

確認並修改關鍵設定：

```bash
grep -nE '^SecRuleEngine|^SecAuditLog |^SecAuditEngine|^SecRequestBodyAccess|^SecDebugLogLevel' \
     /etc/nginx/modsec/modsecurity.conf
```

```text
7:SecRuleEngine DetectionOnly
20:SecRequestBodyAccess On
183:SecAuditEngine RelevantOnly
201:SecAuditLog /var/log/modsec_audit.log
```

★★★★★ 確認 `SecRuleEngine` 就是 `DetectionOnly`，**這一步不要跳過**。

調整稽核日誌路徑與臨時目錄：

```bash
sudo mkdir -p /var/log/nginx /var/cache/modsecurity/{tmp,data,upload}
sudo chown -R www-data:www-data /var/cache/modsecurity
sudo chmod 700 /var/cache/modsecurity/{tmp,data,upload}

sudo sed -i \
  -e 's#^SecAuditLog .*#SecAuditLog /var/log/nginx/modsec_audit.log#' \
  -e 's#^SecTmpDir .*#SecTmpDir /var/cache/modsecurity/tmp#' \
  -e 's#^SecDataDir .*#SecDataDir /var/cache/modsecurity/data#' \
  /etc/nginx/modsec/modsecurity.conf
```

### 步驟 4：建立測試規則與主入口

```bash
sudo tee /etc/nginx/modsec/10-smoke-test.conf > /dev/null <<'EOF'
# 冒煙測試規則：只為了驗證引擎有在跑，正式上線後移除
SecRule ARGS "@rx (?i)(?:'\s*or\s*'?1'?\s*=\s*'?1|union\s+select)" \
    "id:1000010,\
     phase:2,\
     pass,\
     log,\
     msg:'SMOKE TEST: possible SQL injection pattern',\
     severity:'CRITICAL'"
EOF

sudo tee /etc/nginx/modsec/main.conf > /dev/null <<'EOF'
Include /etc/nginx/modsec/modsecurity.conf
Include /etc/nginx/modsec/10-smoke-test.conf
EOF
```

> [!note] ★★★ 為什麼動作寫 `pass` 不寫 `deny`
> 因為 `SecRuleEngine DetectionOnly` 已經會把所有中斷動作降級成「只記錄」。
> 這裡寫 `pass` 是**雙保險**，確保就算有人把引擎切成 `On`，這條測試規則也不會擋人。

### 步驟 5：Nginx 站台設定

```bash
sudo tee /etc/nginx/sites-available/waf-lab > /dev/null <<'EOF'
server {
    listen 80;
    server_name waf-lab.local 192.168.56.20;

    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsec/main.conf;

    root /var/www/html;
    index index.nginx-debian.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/waf-lab /etc/nginx/sites-enabled/waf-lab
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
```

```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

```bash
sudo systemctl reload nginx
```

### 步驟 6：發正常請求，確認網站沒壞 ★★★★

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.56.20/
```

```text
200
```

★★★★ 這一步是**回歸驗證**。裝完 WAF 第一件事永遠是確認正常流量還通。

### 步驟 7：發測試攻擊

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  --get --data-urlencode "id=1' OR '1'='1" \
  http://192.168.56.20/
```

```text
200
```

> [!note] ★★★★ 回 200 是**正確的**
> 因為現在是 `DetectionOnly` —— 規則命中了，但引擎只記錄不阻擋。
> **判斷 WAF 有沒有在運作，要看日誌，不是看狀態碼。**
> 這是新手最常誤判「WAF 沒裝好」的地方。

### 步驟 8：在稽核日誌找到它 ★★★★★

```bash
sudo ls -l /var/log/nginx/modsec_audit.log
```

```text
-rw-r----- 1 www-data www-data 4127 Sep  3 10:22 /var/log/nginx/modsec_audit.log
```

```bash
sudo tail -n 40 /var/log/nginx/modsec_audit.log
```

會看到類似（欄位依 `SecAuditLogParts` 設定而異）：

```text
---abcd1234---A--
[03/Sep/2026:10:22:41 +0800] 175698736138.512345 192.168.56.1 51234 192.168.56.20 80
---abcd1234---B--
GET /?id=1%27%20OR%20%271%27%3D%271 HTTP/1.1
Host: 192.168.56.20
User-Agent: curl/8.5.0
Accept: */*

---abcd1234---F--
HTTP/1.1 200
Server: nginx/1.24.0
Content-Type: text/html

---abcd1234---H--
ModSecurity: Warning. Matched "Operator `Rx' with parameter
`(?i)(?:'\s*or\s*'?1'?\s*=\s*'?1|union\s+select)' against variable `ARGS:id'
(Value: `1' OR '1'='1') [file "/etc/nginx/modsec/10-smoke-test.conf"] [line "3"]
[id "1000010"] [msg "SMOKE TEST: possible SQL injection pattern"]
[severity "CRITICAL"] [hostname "192.168.56.20"] [uri "/"]
[unique_id "175698736138.512345"]

---abcd1234---Z--
```

★★★★★ **看到 `[id "1000010"]` 就代表整條鏈路是通的**：
模組載入 → 設定讀取 → 規則解析 → 請求解析 → 規則命中 → 稽核日誌寫入。

也可以同時看 Nginx 的 error log：

```bash
sudo grep -i modsecurity /var/log/nginx/error.log | tail -n 3
```

```text
2026/09/03 10:22:41 [warn] 1234#1234: *5 [client 192.168.56.1] ModSecurity:
Warning. Matched "Operator `Rx' ... [id "1000010"] [msg "SMOKE TEST: possible
SQL injection pattern"] ... , client: 192.168.56.1, server: waf-lab.local,
request: "GET /?id=1'%20OR%20'1'='1 HTTP/1.1", host: "192.168.56.20"
```

### 步驟 9：驗證「切到 On 真的會擋」（只在實驗機做）

> [!danger] ★★★★★ 這一步只准在實驗機做
> 正式環境**不可以**在還沒完成誤判調校前執行下面這段。

```bash
# 臨時改成 On，並把測試規則的動作改成 deny
sudo sed -i 's/^SecRuleEngine .*/SecRuleEngine On/' \
     /etc/nginx/modsec/modsecurity.conf
sudo sed -i 's/     pass,\\/     deny,status:403,\\/' \
     /etc/nginx/modsec/10-smoke-test.conf
sudo nginx -t && sudo systemctl reload nginx

curl -s -o /dev/null -w '%{http_code}\n' \
  --get --data-urlencode "id=1' OR '1'='1" \
  http://192.168.56.20/
```

```text
403
```

正常請求仍應為 200：

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.56.20/
```

```text
200
```

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

**驗證完就一定要改回去。** 下一篇裝上 CRS 之後，規則數量會從 1 條變成上千條，
在 `On` 的狀態下裝 CRS 幾乎保證會擋到人。

### 步驟 11：交付前的檢查清單

| # | 檢查項 | 指令 | 通過標準 |
| --- | --- | --- | --- |
| 1 | 模組載入 | `nginx -t` | syntax is ok |
| 2 | 引擎模式 | `grep ^SecRuleEngine ...` | `DetectionOnly` ★★★★★ |
| 3 | 正常流量 | `curl -o /dev/null -w '%{http_code}'` 首頁 | 200 |
| 4 | 攻擊被記錄 | tail 稽核日誌 | 有對應 `[id ...]` |
| 5 | 日誌權限 | `ls -l modsec_audit.log` | `0640`，非全域可讀 ★★★★ |
| 6 | logrotate | `ls /etc/logrotate.d/` | 有對應設定 |
| 7 | debug level | `grep ^SecDebugLogLevel ...` | 0～3 ★★★★ |
| 8 | 狀態回報 | `grep ^SecStatusEngine ...` | `Off` ★★★ |
| 9 | 重開機存活 | `sudo reboot` 後再測一次 | 全部通過 |

---

## 常見錯誤與排錯

| # | 現象 | 原因 | 解法 |
| --- | --- | --- | --- |
| 1 | `nginx: [emerg] unknown directive "modsecurity"` | 模組沒載入 | 確認 `load_module` 那行在 `nginx.conf` **最上方**、`http {}` 之前；確認 `.so` 檔存在 ★★★★ |
| 2 | `module "..._modsecurity_module.so" version 1026002 instead of 1026003` | ★★★★★ Nginx 升級後模組版本不合 | 用新版 Nginx 原始碼重編模組，或改走 MyGuard 套件路線 |
| 3 | `nginx: [emerg] "modsecurity_rules_file" directive Rules error ... File not found: unicode.mapping` | `unicode.mapping` 沒放在設定檔同目錄 | `cp /etc/modsecurity/unicode.mapping /etc/nginx/modsec/` ★★★★ |
| 4 | 啟動報 `Unknown directive Sec...` | 照抄了 v2 的設定檔，該指令 v3 未實作 | 把錯誤訊息指的那一行註解掉；改找 v3 的教學 ★★★★ |
| 5 | 裝完之後**所有頁面回 403** | 直接開了 `SecRuleEngine On` 又載入了規則集 | ★★★★★ 立刻改回 `DetectionOnly` 並 reload，再照 03 篇流程調校 |
| 6 | 稽核日誌檔案不存在 | `SecAuditEngine Off`，或路徑不可寫 | 設 `RelevantOnly`；確認目錄擁有者是 Nginx worker 使用者 |
| 7 | 稽核日誌一片空白但 error.log 有 ModSecurity 訊息 | `SecAuditLogParts` 沒含 `H` | 改成 `ABIJDEFHZ` ★★★★ |
| 8 | POST 參數完全不被檢查 | `SecRequestBodyAccess Off` | 改成 `On` ★★★★ |
| 9 | JSON API 的欄位規則都不命中 | libmodsecurity 編譯時 YAJL disabled，或 Content-Type 不在允許清單 | 補 `libyajl-dev` 重編；確認請求的 `Content-Type: application/json` ★★★★ |
| 10 | 上傳大檔回 413 | `SecRequestBodyLimit` 太小 + `LimitAction Reject` | 調大 limit，**不要**改成 `ProcessPartial` ★★★★ |
| 11 | Nginx worker 反覆 crash／重啟 | `SecTmpDir`／`SecDataDir` 不存在或權限不足 | 建目錄並 `chown` 給 worker 使用者；注意 systemd `PrivateTmp` |
| 12 | 磁碟在幾小時內被塞滿 | `SecDebugLogLevel 9` 或 `SecAuditEngine On` | 改 `SecDebugLogLevel 0`、`SecAuditEngine RelevantOnly`；設 logrotate ★★★★★ |
| 13 | 所有規則看到的來源 IP 都是同一個內網位址 | WAF 在 LB／CDN 後面沒設 real_ip | 設 `set_real_ip_from` + `real_ip_header`，**網段要寫實際的** ★★★★ |
| 14 | `Execution error - PCRE limits exceeded` | 請求太大或規則正規表示式太複雜 | 調高 `SecPcreMatchLimit` 與 `SecPcreMatchLimitRecursion` |
| 15 | 攻擊請求回 200，以為 WAF 沒裝好 | ★★★★ 現在是 `DetectionOnly` | 看稽核日誌有沒有記到；有記到就是正常 |
| 16 | 靜態站台開了 WAF 之後回應變慢 | 圖片、CSS、JS 也在過規則 | 在靜態資源的 location 加 `modsecurity off;` ★★★ |
| 17 | HTTPS 網站的攻擊完全沒被記錄 | WAF 掛在 TLS 沒終止的那一層，看到的是密文 | 確認 TLS 在這台終止；見 [[090-03-01-guide-應用安全-TLS憑證與HTTPS實務]] |
| 18 | `reload` 後設定沒生效 | 改的是 `sites-available` 但沒建 symlink，或改到別的 server block | `nginx -T` 印出完整生效設定來比對 ★★★ |

**排錯的固定順序** ★★★★

1. `nginx -t` —— 設定語法過不過
2. `nginx -T | grep -i modsec` —— 我以為的設定真的生效了嗎
3. `grep -i modsecurity /var/log/nginx/error.log | tail` —— 引擎有沒有講話
4. `tail -f /var/log/nginx/modsec_audit.log` —— 稽核日誌有沒有東西
5. 都沒有 → 回到步驟 2，你的 `modsecurity on;` 可能寫在沒被命中的 location

---

## 安全性注意事項

> [!danger] ★★★★★ 五條紅線
> 1. **第一次上線一律 `DetectionOnly`**，不管誰催。
> 2. **不要因為裝了 WAF 就延後修應用層漏洞。** WAF 是保險不是修補。
> 3. **稽核日誌含個資**，權限、保存期限、遮蔽都要納管。
> 4. **`SecDebugLogLevel` 正式環境不可超過 3**。
> 5. **雲端 WAF 一定要鎖 origin IP**，否則等於沒裝。

### 其他要點

| 項目 | 做法 | 重要度 |
| --- | --- | --- |
| WAF 節點本身的強化 | 這台是對外第一線，套用系統強化基準 | ★★★★ |
| 只開必要 port | 80/443 對外，管理介面走內網或跳板 | ★★★★ |
| `SecStatusEngine Off` | 避免版本資訊外洩到第三方 | ★★★ |
| 隱藏 Nginx 版本 | `server_tokens off;` | ★★★ |
| 自訂 403 頁面 | 不要洩漏「你被 WAF 擋了」與規則細節 | ★★★ |
| WAF 規則變更走變更管理 | 每次改規則都要有紀錄與回退方案 | ★★★★ |
| 備份設定檔 | `/etc/nginx/modsec/` 納入版控 | ★★★★ |
| 與 Fail2ban 串接 | 重複觸發規則的 IP 直接在防火牆封 | ★★★ 見 [[090-02-05-guide-防護-Fail2ban入侵防護]] |
| 日誌集中 | 送到 SIEM，別只留在本機 | ★★★★ 見 [[100-01-03-guide-日誌-系統監控與告警]] |
| 定期更新規則集 | CRS 有版本更新，排入維運行事曆 | ★★★ |

> [!warning] ★★★★ 自訂 403 頁面不要暴露規則資訊
> 預設的 403 頁面不會洩漏，但有些人會「好心」把 ModSecurity 的 `msg` 顯示給使用者看。
> 那等於直接告訴攻擊者「你被哪條規則擋了」，方便他調整 payload 繞過。
> 對外只顯示一個通用訊息與一組事件編號（用 transaction id），細節留在日誌。

---

## 速查表

### 三條安裝路線

| 路線 | 指令關鍵字 | 適用 |
| --- | --- | --- |
| A 發行版套件 | `apt install libnginx-mod-http-modsecurity` | 內網、快速驗證 |
| B MyGuard ★★★★ | 加 `deb.myguard.nl` 套件庫後 `apt install` | 對外站台，本手冊推薦 |
| C 自行編譯 | `./configure --add-dynamic-module=...` + `make modules` | 特殊需求 |

### 關鍵檔案路徑

| 路徑 | 用途 |
| --- | --- |
| `/etc/nginx/modules-enabled/*.conf` | `load_module` 設定 |
| `/usr/lib/nginx/modules/ngx_http_modsecurity_module.so` | 模組本體 |
| `/etc/modsecurity/modsecurity.conf-recommended` | 官方範本（不要直接改） |
| `/etc/nginx/modsec/modsecurity.conf` | 你的引擎設定 |
| `/etc/nginx/modsec/unicode.mapping` | ★★★★ 必須與設定檔同目錄 |
| `/etc/nginx/modsec/main.conf` | 總入口，控制 Include 順序 |
| `/var/log/nginx/modsec_audit.log` | 稽核日誌 |
| `/var/log/nginx/error.log` | ModSecurity 警告也會寫這裡 |

### Nginx 指令

| 指令 | 說明 |
| --- | --- |
| `load_module modules/ngx_http_modsecurity_module.so;` | 載入模組（`http {}` 之前） |
| `modsecurity on\|off;` | ★★★★ 總開關（http/server/location） |
| `modsecurity_rules_file <path>;` | 從檔案載入規則 |
| `modsecurity_rules '<內容>';` | 內嵌規則 |
| `modsecurity_transaction_id $request_id;` | ★★★ 交易 ID，方便日誌關聯 |

### `modsecurity.conf` 核心指令

| 指令 | 建議值 | 重要度 |
| --- | --- | --- |
| `SecRuleEngine` | 上線初期 `DetectionOnly` | ★★★★★ |
| `SecRequestBodyAccess` | `On` | ★★★★ |
| `SecRequestBodyLimit` | 依上傳需求調大 | ★★★★ |
| `SecRequestBodyLimitAction` | `Reject` | ★★★★ |
| `SecResponseBodyAccess` | 視效能取捨 | ★★★ |
| `SecResponseBodyMimeType` | 記得加 `application/json` | ★★★ |
| `SecAuditEngine` | `RelevantOnly` | ★★★★ |
| `SecAuditLogParts` | `ABIJDEFHZ`（`H` 必留） | ★★★★★ |
| `SecAuditLogType` | `Serial` 或 `Concurrent` | ★★ |
| `SecDebugLogLevel` | 正式環境 `0`～`3` | ★★★★★ |
| `SecStatusEngine` | `Off` | ★★★ |
| `SecTmpDir` / `SecDataDir` | 指到存在且可寫的目錄 | ★★★ |
| `SecPcreMatchLimit` | 遇到 PCRE 錯誤才調 | ★★ |
| `SecUnicodeMapFile` | 對應檔要在同目錄 | ★★★★ |

### 規則處理階段

| phase | 時機 | 主要用途 |
| --- | --- | --- |
| 1 | 請求標頭 | URI、標頭、Cookie 檢查 |
| 2 | ★★★★ 請求本體 | 參數注入偵測（絕大多數規則） |
| 3 | 回應標頭 | 狀態碼判斷 |
| 4 | 回應本體 | 資料外洩偵測 |
| 5 | 記錄 | 只能記錄，不能阻擋 |

### 常用驗證指令

| 指令 | 用途 |
| --- | --- |
| `nginx -t` | 語法檢查 |
| `nginx -T \| grep -i modsec` | ★★★★ 印出**實際生效**的完整設定 |
| `nginx -V 2>&1 \| tr ' ' '\n' \| grep -- --with` | 取出編譯參數 |
| `apachectl -M \| grep -i security` | Apache 確認模組 |
| `curl -o /dev/null -w '%{http_code}\n' <url>` | 只看狀態碼 |
| `curl --get --data-urlencode "id=1' OR '1'='1" <url>` | ★★★ 發測試攻擊 |
| `tail -f /var/log/nginx/modsec_audit.log` | 即時看稽核日誌 |
| `grep -c 'id "' modsec_audit.log` | 粗估命中次數 |

---

## 練習題

> [!example] 練習 1（★★）
> 在測試機上安裝 ModSecurity v3 + Nginx，用 `nginx -T` 證明
> `modsecurity_rules_file` 確實生效在你預期的那個 server block。

> [!question]- 參考解答
> ```bash
> sudo nginx -T 2>/dev/null | grep -n -A2 -B8 'modsecurity_rules_file'
> ```
> 重點在看它出現在哪一個 `server { ... }` 的範圍內。
> 常見的失敗是設定寫在 `sites-available` 但沒建 symlink，
> 這時 `nginx -T` 就完全找不到那段。

> [!example] 練習 2（★★★）
> 寫一條自訂規則，偵測 `User-Agent` 含有 `sqlmap`，
> 只記錄不阻擋，訊息寫成 `Scanner detected: sqlmap`。
> 然後用 curl 觸發它並在稽核日誌中找到。

> [!question]- 參考解答
> ```apache
> SecRule REQUEST_HEADERS:User-Agent "@contains sqlmap" \
>     "id:1000020,\
>      phase:1,\
>      pass,\
>      log,\
>      msg:'Scanner detected: sqlmap',\
>      severity:'WARNING'"
> ```
> 觸發：
> ```bash
> curl -s -o /dev/null -A "sqlmap/1.8" http://192.168.56.20/
> sudo grep 'id "1000020"' /var/log/nginx/modsec_audit.log
> ```
> ★★★ 這裡用 `phase:1` 是對的，因為 User-Agent 在請求標頭階段就拿得到。

> [!example] 練習 3（★★★★）
> 設定一個 server block：`/api/` 開 WAF、`/static/` 關 WAF、
> 其餘路徑開 WAF。然後用三個 curl 分別驗證三種行為。

> [!question]- 參考解答
> ```nginx
> server {
>     listen 80;
>     server_name waf-lab.local;
>
>     modsecurity on;
>     modsecurity_rules_file /etc/nginx/modsec/main.conf;
>
>     location /static/ {
>         modsecurity off;
>         root /var/www;
>     }
>     location /api/ { proxy_pass http://127.0.0.1:8080; }
>     location /     { root /var/www/html; }
> }
> ```
> 驗證時對三個路徑各發一次含攻擊字串的請求，
> 只有 `/static/` 那次的稽核日誌不該出現命中紀錄。
> ★★★★ 注意 `modsecurity on;` 寫在 server 層，location 層可以覆寫成 `off`。

> [!example] 練習 4（★★★）
> 把 `SecAuditLogParts` 從 `ABIJDEFHZ` 改成 `ABZ`，重新觸發一次攻擊，
> 說明日誌少了什麼、為什麼這樣不能用來調校。

> [!question]- 參考解答
> 少掉的最關鍵是 **`H` 段** —— 命中的規則 ID、訊息、異常分數全部不見了，
> 只剩「有一個請求進來」。這種日誌完全無法拿來做誤判分析。
> ★★★★ 結論：`H` 段是調校的命脈，任何情況下都不要拿掉。

> [!example] 練習 5（★★★★）
> 寫一份「WAF 導入前的環境檢查表」，至少 8 項，
> 涵蓋：TLS 終止在哪、真實 IP 怎麼取得、上傳檔案最大多少、
> 有沒有 JSON API、稽核日誌放哪、保存多久。

> [!question]- 參考解答
> 檢查表至少應包含：
> 1. TLS 在哪一層終止（WAF 看得到明文嗎）★★★★
> 2. 前面是否有 LB／CDN，`X-Forwarded-For` 的信任網段是什麼 ★★★★
> 3. 應用最大上傳檔案大小 → 決定 `SecRequestBodyLimit`
> 4. 是否有 JSON／XML API → 決定 libmodsecurity 要編 YAJL／LibXML2
> 5. 是否有後台富文字編輯器 → 預告會是誤判重災區 ★★★★★
> 6. 稽核日誌磁碟空間與 logrotate 策略
> 7. 個資保存期限與存取權限
> 8. 回退方案：出事時誰有權把 `SecRuleEngine` 改回 `Off`
> 9. 變更視窗與通知對象

---

## 小測驗

**Q1.** WAF 對下列哪一種攻擊**基本上無效**？
（A）反射型 XSS （B）把訂單金額改成 `-1` 的邏輯漏洞
（C）`../../etc/passwd` 路徑穿越 （D）Log4Shell 的固定 payload

**Q2.**（是非）ModSecurity v3 是一個 Nginx 模組，直接編進 Nginx 就能用。

**Q3.** 這段設定會發生什麼事？

```nginx
server {
    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsec/main.conf;
    location ~ \.php$ {
        modsecurity off;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
    }
}
```

**Q4.** `SecRuleEngine` 的三個值分別是什麼？第一次上線該用哪一個，為什麼？

**Q5.**（是非）在 `DetectionOnly` 模式下，攻擊請求回應 200 代表 WAF 沒有裝好。

**Q6.** `SecAuditLogParts` 裡哪一段包含「命中了哪條規則、訊息是什麼」？拿掉它會怎樣？

**Q7.** 為什麼 `SecRequestBodyLimitAction ProcessPartial` 是一個安全風險？
正確的做法應該是什麼？

**Q8.** 這行指令的問題在哪？

```nginx
set_real_ip_from 0.0.0.0/0;
real_ip_header X-Forwarded-For;
```

**Q9.** 走「自行編譯」路線的最大長期維運代價是什麼？有什麼替代方案？

**Q10.** 編譯 libmodsecurity 時 `./configure` 顯示 `YAJL ... disabled`，
對一個 JSON API 為主的系統會造成什麼後果？

> [!question]- 測驗答案
> **A1. (B)**
> 邏輯漏洞（金額為負、越權存取 IDOR）送出的都是**合法格式的資料**，
> 沒有任何攻擊特徵，WAF 無從判斷。這正是「WAF 不能取代應用安全」的核心理由。
> ★★★★★ 參見〈觀念說明〉的「WAF 擋什麼、不擋什麼」表。
>
> **A2. 錯。**
> v3 的架構是 **`libmodsecurity`（獨立函式庫）+ 各 Web Server 的 connector**。
> Nginx 用的是 `ModSecurity-nginx` 這個 connector，編出來的才是 Nginx 動態模組。
> ★★★★ 參見「ModSecurity v2 與 v3 的差別」。
>
> **A3. 所有 PHP 請求都不會經過 WAF。**
> `location ~ \.php$` 覆寫了 server 層的設定成 `modsecurity off;`，
> 而 PHP 正是動態程式的入口 —— 等於 **WAF 完全沒有保護到應用**，只保護了靜態檔。
> ★★★★★ 這是實務上很容易犯的設定錯誤，設定完務必用攻擊請求實測驗證。
>
> **A4.** `Off`（完全不執行）、`DetectionOnly`（執行並記錄但不擋）、`On`（執行並阻擋）。
> 第一次上線用 **`DetectionOnly`**，因為還沒經過誤判調校，直接開 `On`
> 會擋到大量正常使用者（後台編輯器、檔案上傳、含特殊字元的密碼），
> 最後的結局通常是整個 WAF 被關掉。★★★★★
>
> **A5. 錯。**
> `DetectionOnly` 的定義就是「記錄但不阻擋」，回 200 是**預期行為**。
> 判斷 WAF 是否運作要看**稽核日誌有沒有對應的規則命中紀錄**。
> ★★★★ 參見實戰範例步驟 7～8。
>
> **A6. `H` 段（audit log trailer）。**
> 它包含命中的規則 ID、`msg`、severity、以及（裝了 CRS 之後的）異常分數。
> 拿掉它，日誌就只剩「有請求進來」，**完全無法做誤判分析與調校**。
> ★★★★★ 參見 `SecAuditLogParts` 表。
>
> **A7.** `ProcessPartial` 表示「超過大小限制的部分不檢查就放行」，
> 攻擊者只要在 payload 前面填充足夠多的無害資料，就能讓真正的攻擊落在檢查範圍之外，
> 等於繞過 WAF。正確做法是**把 `SecRequestBodyLimit` 調大到符合業務需求，
> 並維持 `SecRequestBodyLimitAction Reject`**。★★★★
>
> **A8.** 它代表「相信任何來源送來的 `X-Forwarded-For` 標頭」。
> 攻擊者可以任意偽造來源 IP，導致封鎖清單失效、稽核日誌來源失真、
> 甚至偽裝成內網位址繞過 IP 白名單。**只能填你實際控制的前置設備網段。**
> ★★★★★ 參見「真實來源 IP」。
>
> **A9.** 最大代價是 **Nginx 每次升級都必須用新版原始碼重新編譯 connector**，
> 否則 Nginx 會因模組版本不合而完全無法啟動（`version 1026002 instead of 1026003`）。
> 替代方案是走 **MyGuard 套件庫的強化版 NGINX**，模組與 Nginx 版本由套件庫對齊，
> 直接走 apt 升級。★★★★ 參見「路線 B」與排錯表第 2 列。
>
> **A10.** YAJL 是 JSON 解析器。disabled 表示 libmodsecurity **無法解析 JSON 請求本體**，
> 所有 JSON 欄位裡的參數 WAF 都看不到 —— 對一個 JSON API 為主的系統，
> 等於這個 WAF 對主要攻擊面完全失效。需補 `libyajl-dev` 後重新 `./configure` 與編譯。
> ★★★★ 參見「C-2 編譯 libmodsecurity」。

---

## 延伸閱讀

### 本章其他篇

- [[090-04-02-guide-OWASP-CRS規則集]] —— 引擎裝好了，接下來裝規則
- [[090-04-03-svc-ModSecurity-規則調校與誤判處理]] —— ★★★★★ 本章最重要，誤判怎麼處理
- [[090-04-04-guide-ModSecurity-日誌分析與監控]] —— 稽核日誌判讀與告警串接
- [[090-04-05-guide-ModSecurity-效能與實戰情境]] —— 效能開銷與真實攻擊處置
- [[090-04-00-idx-ModSecurity]] —— 本章索引

### 相關主題

- [[090-05-04-guide-資安設備-Web應用防火牆WAF]] —— WAF 的**設備選型與市場全景**
- [[090-05-01-guide-資安設備-資安全景圖與縱深防禦]] —— WAF 在整體防禦中的位置
- [[090-03-02-guide-應用安全-應用層安全]] —— ★★★★★ WAF 取代不了的那一半
- [[090-03-01-guide-應用安全-TLS憑證與HTTPS實務]] —— TLS 終止位置決定 WAF 看不看得到明文
- [[090-03-06-guide-應用安全-委外系統上線前資安檢測]] —— 虛擬修補的使用時機
- [[090-02-05-guide-防護-Fail2ban入侵防護]] —— 把重複攻擊的 IP 丟到防火牆

### Web 伺服器

- [[060-02-02-01-guide-Nginx-安裝與目錄結構]]
- [[060-02-02-09-guide-Nginx-安全設定]]
- [[060-02-02-04-guide-Nginx-反向代理與負載平衡]]
- [[060-02-02-07-guide-Nginx-日誌與除錯]]
- [[060-02-03-07-guide-Apache-安全與效能]] —— Apache 對照
- [[060-02-05-00-idx-MyGuard與Angie]] —— ★★★★ 推薦的安裝路線
- [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]]
- [[060-02-05-04-guide-http-shield攻擊攔截]]

### 官方資源

| 資源 | 網址 |
| --- | --- |
| ModSecurity 專案 | <https://github.com/owasp-modsecurity/ModSecurity> |
| ModSecurity-nginx connector | <https://github.com/owasp-modsecurity/ModSecurity-nginx> |
| OWASP CRS | <https://coreruleset.org/> |
| MyGuard 套件庫使用說明 | <https://deb.myguard.nl/how-to-use/> |
