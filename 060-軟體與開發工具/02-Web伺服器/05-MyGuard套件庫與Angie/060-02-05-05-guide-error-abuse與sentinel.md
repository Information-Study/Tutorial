---
title: "error-abuse 與 sentinel"
desc: "錯誤率限流與信譽評分：擋掉掃描器、爬蟲與 AI 抓取"
aliases: [error-abuse, sentinel, 限流, 信譽評分, tarpit, JA4, AI 爬蟲, PoW]
tags: [群組/軟體與開發工具, 服務/nginx, 服務/myguard, 主題/資安]
category: MyGuard與Angie
difficulty: 專家
status: 完成
distro: [ubuntu]
prerequisites: ["[[060-02-05-04-guide-http-shield攻擊攔截]]"]
updated: 2026-08-28
---

# error-abuse 與 sentinel

> [!abstract] 這篇你會學到
> - **★★★ `error-abuse`**：依錯誤率自動封鎖（★ 擋掃描器最有效）
> - 完整的參數、Redis 共享狀態、白名單技巧
> - **★★★★ `sentinel`**：加權信譽評分（★ 實驗性）
> - JA3/JA4/JA4T 指紋、FCrDNS、AI 爬蟲偵測
> - **★★★ tarpit 與 PoW 挑戰**
> - **★★★★ shadow 模式先行的上線流程**
> - 和 fail2ban / CrowdSec 的關係

> [!danger] sentinel 是實驗性模組 ★★★★
> ```
> ★★★★ 官方明確標示 nginx-http-sentinel-module 為
>       【EXPERIMENTAL，仍在 planning stage】
>       → API 與行為可能有重大變更
>
> ★★★★ 本手冊的立場：
>   · error-abuse  → ★★★ 成熟，正式環境可用
>   · sentinel     → ★★★★ 【只在測試環境或 shadow 模式使用】
>                     ★★★ 正式環境要用的話，務必先長期 shadow 觀察
> ```

> [!warning] 未實機驗證 ★★★
> ```
> ★★★ 本章依據 myguard-labs 的 GitHub 文件（2026 年 8 月）撰寫。
> ★★★★ 實作前請對照官方 README，指令可能已變更。
> ```

## 前置知識

- [[060-02-05-04-guide-http-shield攻擊攔截]] — shield 的攔截機制
- [[090-02-05-guide-防護-Fail2ban入侵防護]] — fail2ban 的做法（★ 用來對照）

---

## ★★★ error-abuse：依錯誤率封鎖

```
★★★★ 核心概念一句話：
  「一個 IP 在 5 分鐘內造成 100 個錯誤回應 → 封鎖 60 分鐘」

★★★ 為什麼有效：
  自動化掃描器的行為特徵是【大量的 404】
    /wp-admin/  /.env  /phpmyadmin/  /.git/config  /admin.php ...
  → ★★★★ 正常使用者不會在 5 分鐘內產生 100 個 404

★★★ 和 fail2ban 的差異：
  ┌──────────────┬────────────────────────┬─────────────────────────┐
  │              │ fail2ban               │ ★★★ error-abuse         │
  ├──────────────┼────────────────────────┼─────────────────────────┤
  │ 運作位置     │ ★★ 讀日誌（外部程序）  │ ★★★★ nginx 內部          │
  │ 反應速度     │ ★★ 秒級（要等寫日誌+輪詢）│ ★★★★ 立即             │
  │ 封鎖方式     │ ★★★ 防火牆規則         │ ★★ 應用層回 429         │
  │ 資源開銷     │ ★★ 多一個 Python 程序  │ ★★★ 共享記憶體，極小    │
  │ ★★★ 持久化   │ ✓ 防火牆規則           │ ✓ persist= 或 Redis     │
  │ ★★★ 多台共享 │ ✗（各自為政）          │ ★★★★ ✓ Redis           │
  │ 跨服務       │ ★★★ ✓（SSH/郵件等）    │ ✗ 只有 HTTP             │
  └──────────────┴────────────────────────┴─────────────────────────┘

★★★★ 兩者互補：
  error-abuse → HTTP 層的快速反應
  fail2ban    → SSH 等其他服務 + 防火牆層的持久封鎖
```

### 安裝與指令

```bash
$ sudo apt install -y libnginx-mod-http-error-abuse
$ apt-cache search error-abuse
$ ls -l /usr/lib/nginx/modules/ | grep -i error
$ sudo nginx -t
```

| 指令 | 語境 | 說明 |
| --- | --- | --- |
| **`error_abuse_zone`** | http | **★★★★ 定義計數與封鎖的共享記憶體區** |
| **`error_abuse`** | http, server, location | **★★★★ 啟用某個 zone** |
| **`error_abuse_redis`** | http | **★★★ 多台共享封鎖狀態** |

```nginx
# ★★★★ error_abuse_zone 的完整參數
error_abuse_zone zone=name:size
                 [key=$variable]          # 預設 $binary_remote_addr
                 [statuses=codes]         # 預設 403,404,500-599
                 [interval=time]          # 預設 300s（滑動視窗）
                 [threshold=number]       # 預設 100
                 [block=time]             # 預設 60m
                 [inactive=time]          # 預設 max(1h, interval, block)
                 [redis=on|off]
                 [persist=path]           # ★★★ 磁碟快照（重啟後保留）
                 [persist_interval=time]
                 [persist_secret=hex]
                 [on_full=allow|reject];

# ★★★★ error_abuse 的參數
error_abuse zone=name
            [status=code]                 # 預設 429
            [dry_run=on|off]              # ★★★★ 只記錄不封鎖
            [log_level=level];
```

### ★★★★ 最小可用設定

```nginx
load_module modules/ngx_http_error_abuse_module.so;

http {
    error_abuse_zone zone=client_errors:10m;

    server {
        listen 443 ssl;
        server_name app.example.gov.tw;

        location / {
            error_abuse zone=client_errors;
            root /var/www/app/current/public;
            try_files $uri $uri/ /index.php?$query_string;
        }
    }
}
```

### ★★★★ 上線流程（dry_run 先行）

```nginx
# ═══ ★★★★ 第一階段：dry_run（只記錄不封鎖）═══
http {
    # ★★★ 變數可以記進日誌
    log_format abuse '$remote_addr - [$time_local] "$request" $status '
                     'ea=$error_abuse_status count=$error_abuse_count '
                     'until=$error_abuse_blocked_until';

    error_abuse_zone zone=client_errors:10m
                     statuses=403,404,500-599
                     interval=300s
                     threshold=100
                     block=60m;

    server {
        listen 443 ssl;
        server_name app.example.gov.tw;
        access_log /var/log/nginx/abuse.log abuse;

        location / {
            error_abuse zone=client_errors dry_run=on log_level=notice;
            #                              ↑ ★★★★ 只記錄
            root /var/www/app/current/public;
            try_files $uri $uri/ /index.php?$query_string;
        }
    }
}
```

```bash
$ sudo nginx -t && sudo systemctl reload nginx

# ★★★★ 觀察哪些 IP 會被封鎖（★ 但實際沒有封）
$ sudo grep 'ea=DRY_RUN' /var/log/nginx/abuse.log | \
    awk '{print $1}' | sort | uniq -c | sort -rn | head -10
    284 203.0.113.45
     12 198.51.100.22

# ★★★ 看它們在做什麼
$ sudo grep '203.0.113.45' /var/log/nginx/abuse.log | \
    awk '{print $7}' | sort | uniq -c | sort -rn | head -10
     92 /.env
     84 /wp-admin/
     48 /.git/config
     32 /phpmyadmin/
#   ★★★★ 明顯是掃描器 → 可以放心開啟封鎖

# ★★★★ 檢查有沒有正常使用者被誤判
$ sudo grep 'ea=DRY_RUN' /var/log/nginx/abuse.log | \
    awk '{print $1}' | sort | uniq -c | awk '$1 < 150' | head
#   ★★★ 剛好超過門檻的要仔細看
```

```nginx
# ═══ ★★★ 第二階段：正式啟用 ═══
location / {
    error_abuse zone=client_errors log_level=notice;   # ★★★ 拿掉 dry_run
    ...
}
```

```bash
# ★★★ 驗證封鎖生效
$ for i in $(seq 1 120); do
    curl -sko /dev/null "https://app.example.gov.tw/nonexistent-$i"
  done
$ curl -sI https://app.example.gov.tw/
HTTP/2 429                                 # ★★★★ 被封鎖了
retry-after: 3600
cache-control: private, no-store
```

### ★★★★ 白名單的技巧

```nginx
# ★★★★ 模組會【忽略空的 key】→ 用 map 把信任的來源對應成空字串
http {
    map $remote_addr $error_abuse_key {
        127.0.0.1        "";               # ★★★ 本機
        default          $binary_remote_addr;
    }

    # ★★★ 用 geo 處理網段（map 不支援 CIDR）
    geo $abuse_exempt {
        default          0;
        127.0.0.0/8      1;
        10.10.20.0/24    1;                # ★★★ 內網
        203.0.113.0/28   1;                # ★★ 重要的合作機關
    }
    map $abuse_exempt $error_abuse_key2 {
        1                "";               # ★★★★ 空字串 = 不計數
        default          $binary_remote_addr;
    }

    error_abuse_zone zone=client_errors:10m key=$error_abuse_key2;
}
```

> [!danger] key 的選擇 ★★★★
> ```
> ★★★ 預設 key=$binary_remote_addr（依 IP）
>
> ★★★★ 在 CDN / 負載平衡器後面要先設 real_ip：
>   set_real_ip_from 10.10.20.0/24;
>   real_ip_header X-Forwarded-For;
>   real_ip_recursive on;
>   → ★★★★ 否則會封鎖 CDN 的 IP = 封鎖所有使用者！
>
> ★★★ 其他可用的 key：
>   key=$http_x_forwarded_for       ★★ 不建議（可偽造）
>   key=$http_authorization         ★★ 依 API token（★ 適合 API）
>   key=$cookie_session             ★ 依 session
>   key=$binary_remote_addr$http_user_agent   ★★ IP + UA（★ 較精準但更吃記憶體）
>
> ★★★★ NAT 環境的考量：
>   一整個機關共用一個對外 IP
>   → ★★★ threshold 要設高（★ 500~1000）
>   → 或用 IP + UA 或 IP + session 當 key
> ```

### ★★★ 持久化與多台共享

```nginx
http {
    # ═══ ★★★ 方式一：磁碟快照（單機重啟後保留）═══
    error_abuse_zone zone=client_errors:10m
                     threshold=100
                     block=60m
                     persist=/var/lib/nginx/error-abuse.state
                     persist_interval=5s;

    # ═══ ★★★★ 方式二：Redis（多台共享）═══
    error_abuse_redis host=10.10.20.60 port=6379
                      password=很長的密碼
                      db=2
                      prefix=ea_
                      timeout=100ms;

    error_abuse_zone zone=client_errors:10m
                     threshold=100
                     block=60m
                     redis=on;
    #   ★★★★ 一台封鎖 → 所有台都封鎖
}
```

```bash
# ★★★ 建立持久化目錄
$ sudo install -d -m 750 -o www-data -g www-data /var/lib/nginx
$ sudo systemctl reload nginx
$ sudo ls -l /var/lib/nginx/error-abuse.state

# ★★★ Redis 的驗證
$ redis-cli -h 10.10.20.60 -a '很長的密碼' -n 2 --scan --pattern 'ea_*' | head
ea_a1b2c3d4e5f6...
$ redis-cli -h 10.10.20.60 -a '很長的密碼' -n 2 TTL 'ea_a1b2c3...'
(integer) 3421

# ★★★★ Redis 的安全（★ 一定要有密碼且不對外）
$ sudo ss -tlnp | grep :6379
LISTEN 0 511 10.10.20.60:6379    # ★★★ 綁內網，不是 0.0.0.0
```

### ★★★ 變數與監控

```
★★★ 模組提供的變數：

  $error_abuse_status         BYPASSED / PASSED / COUNTED / BLOCKED / DRY_RUN
  $error_abuse_count          ★★★ 目前視窗內的命中數
  $error_abuse_blocked_until  ★★ 封鎖到期的 Unix 時間戳（未封鎖是 0）
```

```bash
#!/usr/bin/env bash
# ★★★ /usr/local/bin/abuse-monitor
LOG=/var/log/nginx/abuse.log
TODAY=$(date '+%d/%b/%Y')

echo "═══ error-abuse 監控 $(date '+%F %T') ═══"

echo -e "\n【狀態分布（今日）】"
grep "$TODAY" "$LOG" 2>/dev/null | grep -oP 'ea=\K\w+' | \
  sort | uniq -c | sort -rn | awk '{printf "  %-10s %8d\n", $2, $1}'

echo -e "\n【★★★ 目前被封鎖的 IP】"
grep "$TODAY" "$LOG" 2>/dev/null | grep 'ea=BLOCKED' | \
  awk '{print $1}' | sort | uniq -c | sort -rn | head -10 | \
  awk '{printf "  %-18s %6d 次\n", $2, $1}'

echo -e "\n【★★★★ 被封鎖的 IP 在存取什麼】"
TOP=$(grep "$TODAY" "$LOG" 2>/dev/null | grep 'ea=BLOCKED' | \
      awk '{print $1}' | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')
[ -n "$TOP" ] && grep "^$TOP " "$LOG" | awk '{print $7}' | \
  sort | uniq -c | sort -rn | head -8 | awk '{printf "  %6d  %s\n", $1, $2}'

echo -e "\n【★★★ 接近門檻但沒被封鎖的（可能是誤判）】"
grep "$TODAY" "$LOG" 2>/dev/null | grep -oP '^(\S+).*count=\K[0-9]+' | \
  sort -rn | head -5 | sed 's/^/  count=/'
grep "$TODAY" "$LOG" 2>/dev/null | \
  awk '{for(i=1;i<=NF;i++) if($i ~ /^count=/) {split($i,a,"="); if(a[2]>50 && a[2]<100) print $1, a[2]}}' | \
  sort -u | head -5 | sed 's/^/  ★★★ /'
```

---

## ★★★★ sentinel：加權信譽評分

> [!danger] 實驗性模組 ★★★★
> ```
> ★★★★ 官方標示：EXPERIMENTAL，planning stage
>       API 與行為可能有重大變更
>
> ★★★★ 本手冊建議：
>   · ★★★ 只在測試環境使用
>   · 正式環境要用的話：sentinel_mode shadow 長期觀察（★ 至少一個月）
>   · ★★★★ 不要在關鍵服務上直接 enforce
> ```

```
★★★★ sentinel 的核心：【加權評分 + 四級處置】

  對每一個請求計算一個分數，依分數決定：

  ┌─────────────────────────────────────────────────────┐
  │ 分數 < 30    →  ★★ allow      正常放行                │
  │ 30 ~ 59      →  ★★★ challenge PoW 工作量證明頁面      │
  │ 60 ~ 79      →  ★★★★ tarpit   慢速滴水 / 限速 / 只給快取│
  │ ≥ 80         →  ★★★ block     403 / 444 / 斷線        │
  └─────────────────────────────────────────────────────┘

★★★ 預設門檻：challenge=30 tarpit=60 block=80
```

### ★★★ 評分的訊號來源

| 訊號 | 預設權重 | 說明 |
| --- | --- | --- |
| `errrate` | **1**（每次錯誤） | 錯誤率（滑動視窗） |
| **`scanner`** | **50** | **★★★ 內建的掃描路徑**（`.env` `.git` `wp-login` `wp-admin` `.aws` `phpinfo`） |
| **`bot`** | **30** | **★★★ 啟發式的 bot User-Agent** |
| **`honeypot`** | **90** | **★★★★ 你自己設的誘餌路徑** |
| **`velocity`** | **30** | **★★★ 請求速率超標** |
| `asn` | 35 | **★★ 標記的資料中心 ASN** |
| **`c2ip`** | **80** | **★★★ abuse.ch Feodo 的 C2 IP 清單** |
| **`ja3`** | **80** | **★★★ abuse.ch SSLBL 的惡意 TLS 指紋** |
| **`ja4`** | **50** | **★★★ JA4 TLS 指紋黑名單** |
| `ja4t` | 45 | JA4T TCP 指紋黑名單 |
| **`crowdsec`** | **100** | **★★★★ CrowdSec 封鎖清單** |
| `header` / `blocked` / `coherence` | — | 標頭異常 / 已軟封鎖 / UA 不一致 |

```
★★★★ 兩個短路規則：

  ① ★★★ 已知的正常爬蟲（Googlebot、Bingbot…）→ 分數強制歸零
     ★★★★ 除非 CrowdSec 有命中
     ★★★ 而且 FCrDNS 判定為 spoofed 時這個短路會失效

  ② ★★★ sentinel_allowlist 中的 IP → 分數強制歸零
     ★★ 同樣除非 CrowdSec 有命中

★★★ 分數上限 100,000（防止溢位）
```

### ★★★★ shadow 模式先行

```nginx
load_module modules/ngx_http_sentinel_module.so;

http {
    resolver 1.1.1.1 8.8.8.8 valid=300s ipv6=off;    # ★★★ FCrDNS 需要

    # ═══ ★★★ 共享記憶體區 ═══
    sentinel_zone main:20m;
    sentinel_velocity_zone vzone:5m rate=100 window=10 block=3600;
    sentinel_fcrdns_zone fcdns:1m;

    # ★★★ 記錄評分結果（★ shadow 階段的關鍵）
    log_format sentinel '$remote_addr - [$time_local] "$request" $status '
                        'score=$sentinel_score verdict=$sentinel_verdict '
                        'ja4h=$sentinel_ja4h fcrdns=$sentinel_fcrdns '
                        'sig=[scanner=$sentinel_scanner,bot=$sentinel_bot,'
                        'hp=$sentinel_honeypot,vel=$sentinel_velocity,'
                        'err=$sentinel_errrate,coh=$sentinel_coherence] '
                        'ua="$http_user_agent"';

    server {
        listen 443 ssl;
        server_name app.example.gov.tw;
        access_log /var/log/nginx/sentinel.log sentinel;

        # ═══ ★★★★ shadow 模式：只記錄不處置 ═══
        sentinel on;
        sentinel_mode shadow;                # ★★★★ 關鍵！
        sentinel_zone main:20m;
        sentinel_threshold challenge=30 tarpit=60 block=80;

        sentinel_velocity vzone;
        sentinel_honeypot /wp-login.php /xmlrpc.php /.env /.git /admin.php;
        sentinel_fcrdns fcdns;
        sentinel_fcrdns_verify_suffix .googlebot.com .google.com
                                      .search.msn.com .crawl.yahoo.net;
        sentinel_allowlist 10.10.20.0/24 203.0.113.0/28;

        location / {
            root /var/www/app/current/public;
            try_files $uri $uri/ /index.php?$query_string;
        }

        # ★★ Prometheus 狀態
        location = /sentinel-status {
            sentinel_status;
            allow 127.0.0.1;
            allow 10.10.20.50;
            deny all;
            access_log off;
        }
    }
}
```

```bash
#!/usr/bin/env bash
# ★★★★ /usr/local/bin/sentinel-shadow-analyze —— shadow 階段的分析
set -uo pipefail
LOG="${1:-/var/log/nginx/sentinel.log}"
DAYS="${2:-7}"

echo "═══ sentinel shadow 分析（近 $DAYS 天）═══"
TOTAL=$(wc -l < "$LOG")
echo "  總請求數: $TOTAL"

# ═══ ★★★★【1】判決分布（★ 最重要）═══
echo -e "\n【1】★★★★ 判決分布"
grep -oP 'verdict=\K\w+' "$LOG" | sort | uniq -c | sort -rn | \
  awk -v t="$TOTAL" '{printf "  %-12s %8d  (%.2f%%)", $2, $1, $1/t*100
    if ($2 != "allow" && $1/t > 0.05) printf "  ★★★★ 比例偏高！"
    print ""}'
#   ★★★★ 如果 block + tarpit 超過 5%，enforce 之後會有大量使用者受影響

# ═══ ★★★【2】分數分布 ═══
echo -e "\n【2】分數分布"
grep -oP 'score=\K[0-9]+' "$LOG" | sort -n | awk '
  {a[NR]=$1}
  END{printf "  P50=%d  P90=%d  P95=%d  P99=%d  max=%d\n",
      a[int(NR*0.5)], a[int(NR*0.9)], a[int(NR*0.95)], a[int(NR*0.99)], a[NR]}'

# ═══ ★★★★【3】哪些訊號觸發最多 ═══
echo -e "\n【3】★★★ 訊號觸發次數"
for s in scanner bot hp vel err coh; do
    n=$(grep -oP "$s=\K[0-9]+" "$LOG" | awk '$1>0' | wc -l)
    printf "  %-10s %8d\n" "$s" "$n"
done

# ═══ ★★★★【4】被判 block/tarpit 的請求（★ 檢查誤判）═══
echo -e "\n【4】★★★★ 會被處置的請求（前 15 筆）"
grep -E 'verdict=(block|tarpit|challenge)' "$LOG" | tail -15 | \
  cut -c1-160 | sed 's/^/  /'

# ═══ ★★★★【5】被判 block 的 UA（★ 誤判的關鍵指標）═══
echo -e "\n【5】★★★★ 被判 block/tarpit 的 User-Agent"
grep -E 'verdict=(block|tarpit)' "$LOG" | \
  grep -oP 'ua="\K[^"]*' | sort | uniq -c | sort -rn | head -10 | \
  cut -c1-120 | sed 's/^/  /'
echo "  ★★★★ 出現真實瀏覽器的 UA（Chrome/Firefox/Safari）= 誤判！"

# ═══ ★★★【6】FCrDNS ═══
echo -e "\n【6】FCrDNS 驗證結果"
grep -oP 'fcrdns=\K\w+' "$LOG" | sort | uniq -c | sort -rn | \
  awk '{printf "  %-10s %8d", $2, $1
        if ($2 == "spoofed") printf "  ★★★★ 偽裝成爬蟲的請求"
        print ""}'

# ═══ ★★★★【7】結論 ═══
echo -e "\n【7】★★★★ 上線建議"
BLOCK_PCT=$(grep -c 'verdict=block' "$LOG" | awk -v t="$TOTAL" '{printf "%.2f", $1/t*100}')
REAL_UA=$(grep -E 'verdict=(block|tarpit)' "$LOG" | \
          grep -cE 'ua="Mozilla/5\.0 \((Windows|Macintosh|X11|iPhone|iPad)' || echo 0)
echo "  block 比率: ${BLOCK_PCT}%"
echo "  被處置的請求中，真實瀏覽器 UA: $REAL_UA 筆"
if [ "$REAL_UA" -gt 0 ]; then
    echo "  ★★★★ 有真實瀏覽器被誤判 → 【不要】切換到 enforce"
    echo "     · 調高 sentinel_threshold"
    echo "     · 檢查 sentinel_weight_bot / sentinel_weight_asn"
    echo "     · 把來源加進 sentinel_allowlist"
else
    echo "  ★ 沒有明顯的誤判，可以考慮小範圍 enforce"
fi
```

```bash
$ sudo install -m755 sentinel-shadow-analyze.sh /usr/local/bin/sentinel-shadow-analyze
$ sudo sentinel-shadow-analyze /var/log/nginx/sentinel.log 7

═══ sentinel shadow 分析（近 7 天）═══
  總請求數: 482104

【1】★★★★ 判決分布
  allow          478210  (99.19%)
  block            2840  (0.59%)
  tarpit            892  (0.19%)
  challenge         162  (0.03%)

【5】★★★★ 被判 block/tarpit 的 User-Agent
    1840 python-requests/2.31.0
     620 Mozilla/5.0 (compatible; SemrushBot/7~bl; ...)
     284 curl/8.5.0
      88 Go-http-client/2.0
  ★★★★ 出現真實瀏覽器的 UA（Chrome/Firefox/Safari）= 誤判！

【7】★★★★ 上線建議
  block 比率: 0.59%
  被處置的請求中，真實瀏覽器 UA: 0 筆
  ★ 沒有明顯的誤判，可以考慮小範圍 enforce
```

### ★★★ tarpit 與 PoW

```nginx
server {
    sentinel on;
    sentinel_mode enforce;                  # ★★★★ 確認 shadow 沒問題才切
    sentinel_threshold challenge=30 tarpit=60 block=80;

    # ═══ ★★★ block 的處置 ═══
    sentinel_block_status 403;              # ★ 400-599，或 444 直接斷線
    sentinel_block_ttl 3600;                # ★★ 軟封鎖時長（0 = 關閉）

    # ═══ ★★★★ tarpit（★ 慢速滴水拖住對方）═══
    sentinel_tarpit_max_conns 256;          # ★★★★ 全域並行上限（★ 防自我 DoS）
    sentinel_tarpit_delay 5000;             # ★★ 每次滴水的間隔（ms，100-60000）
    sentinel_tarpit_bytes 1024;             # ★★ 總共滴多少 bytes（1-65536）
    sentinel_tarpit_max_lifetime 30000;     # ★★★ 硬上限（ms，1000-600000）
    sentinel_tarpit_maze on;                # ★★★ 滴出誘餌連結而不是空白

    # ═══ ★★ 或用限速（★ 與 tarpit 互斥）═══
    # sentinel_throttle_rate 32k;

    # ═══ ★★★ PoW 工作量證明挑戰 ═══
    sentinel_pow on;
    sentinel_pow_secret "用 openssl rand -hex 32 產生的值";
    sentinel_pow_difficulty 16;             # ★★★ 前導零位元數（1-32）
    sentinel_pow_ttl 3600;                  # ★★ 挑戰與 cookie 的存活時間
}
```

```
★★★★ tarpit 的設計哲學：

  一般的封鎖（403）：
    → 攻擊者立刻收到回應 → ★★ 馬上換下一個目標或換 IP
    → 你省了資源，但對方也省了

  ★★★★ tarpit（慢速滴水）：
    → 連線【保持開啟但極慢地滴資料】
    → ★★★ 攻擊者的連線被佔住（★ 消耗對方的資源）
    → maze 模式還會滴出【誘餌連結】讓爬蟲繼續往下爬
    → ★★★ 對 AI 爬蟲特別有效（★ 它們會傻傻地跟著爬）

  ★★★★ 但要小心【自我 DoS】：
    → 每個 tarpit 連線都佔用你的 worker 連線
    → ★★★★ sentinel_tarpit_max_conns 是必要的保護
    → ★★★ max_lifetime 確保連線不會無限期掛著
```

> [!danger] PoW 挑戰的三個注意事項 ★★★
> ```
> ① ★★★★ 難度的選擇
>      sentinel_pow_difficulty 16    → ★★ 一般裝置約 0.1~1 秒
>      sentinel_pow_difficulty 20    → ★★★ 約 2~10 秒
>      sentinel_pow_difficulty 24    → ★★★★ 太久，正常使用者會走掉
>      → ★★★ 建議 16~18
>
> ② ★★★★ 需要 JavaScript
>      → ★★★ 沒有 JS 的客戶端【完全無法通過】
>      → API 客戶端、行動 App、無障礙工具會被擋死
>      → ★★★★ API 的 location 不要開 PoW
>
> ③ ★★★ secret 一定要是隨機的
>      $ openssl rand -hex 32
>      → ★★★★ 用固定值 = 攻擊者可以預先算好答案
>      → ★★ 而且要定期輪替
> ```

```nginx
# ★★★★ 分區設定：API 不用 PoW
server {
    sentinel on;
    sentinel_mode enforce;

    # ★★ 網頁：可以用 PoW
    location / {
        sentinel_pow on;
        sentinel_pow_secret "...";
        sentinel_pow_difficulty 16;
        root /var/www/app/current/public;
    }

    # ★★★★ API：不能用 PoW（★ 客戶端沒有 JS）
    location /api/ {
        sentinel_pow off;
        sentinel_threshold challenge=100 tarpit=80 block=90;   # ★★★ 門檻調高
        try_files $uri /index.php?$query_string;
    }

    # ★★★ 管理後台：更嚴格
    location /admin/ {
        sentinel_threshold challenge=10 tarpit=40 block=60;
        sentinel_weight_bot 100;             # ★★★ 後台不該有 bot
        allow 10.10.20.0/24;
        deny all;
    }
}
```

### ★★★ 指紋與爬蟲偵測

```nginx
http {
    # ═══ ★★★ JA3 / JA4 TLS 指紋（★ 需要 ssl-fingerprint 模組）═══
    server {
        listen 443 ssl;
        ssl_fingerprint on;

        sentinel_ja3 $ssl_fingerprint_ja3_hash;
        sentinel_ja3_deny <abuse.ch SSLBL 的雜湊值> ...;

        sentinel_ja4 $ssl_fingerprint_ja4;
        sentinel_ja4_deny <JA4 指紋> ...;

        # ★★ JA4T TCP 指紋（★ 需要 PROXY protocol）
        sentinel_ja4t $proxy_protocol_tlv_0xe0;
    }

    # ═══ ★★★ ASN（★ 需要 geoip2 模組）═══
    geoip2 /usr/share/GeoIP/GeoLite2-ASN.mmdb {
        $geoip2_asn autonomous_system_number;
    }
    server {
        sentinel_asn $geoip2_asn;
        sentinel_datacenter_asn 16509 14618 15169 13335 16276;
        #   ★★ AWS / Amazon / Google / Cloudflare / OVH
        #   ★★★ 資料中心來的流量通常不是真人
    }

    # ═══ ★★★★ FCrDNS（正反解驗證）═══
    sentinel_fcrdns_zone fcdns:1m;
    server {
        sentinel_fcrdns fcdns;
        sentinel_fcrdns_verify_suffix .googlebot.com .google.com
                                      .search.msn.com .crawl.yahoo.net
                                      .applebot.apple.com;
    }
}
```

```
★★★★ FCrDNS（Forward-Confirmed reverse DNS）是什麼：

  ★★★ 驗證「自稱是 Googlebot 的請求，真的是 Googlebot 嗎」

  流程：
    ① 客戶端 UA 自稱 Googlebot
    ② ★★★ 對它的 IP 做反解 → 例如 crawl-66-249-66-1.googlebot.com
    ③ ★★★ 再對那個網域做正解 → 66.249.66.1
    ④ ★★★★ 兩個 IP 一致 → verified；不一致或反解失敗 → spoofed

  ★★★★ 為什麼重要：
    · 攻擊者常常偽裝成 Googlebot 來繞過防護
    · ★★★ sentinel 對已知的正常爬蟲會【分數歸零】
    · ★★★★ 沒有 FCrDNS 的話，只要把 UA 改成 Googlebot 就能繞過所有防護！
    · ★★★ FCrDNS 判定 spoofed 時，這個短路會失效

  ★★ 狀態：verified / spoofed / pending（非同步查詢中）
```

```bash
# ★★★★ 驗證 FCrDNS 有在運作
$ sudo grep -oP 'fcrdns=\K\w+' /var/log/nginx/sentinel.log | sort | uniq -c
   4820 verified
    284 spoofed                            # ★★★★ 偽裝成爬蟲的
   1240 pending

# ★★★ 看偽裝的請求
$ sudo grep 'fcrdns=spoofed' /var/log/nginx/sentinel.log | \
    grep -oP 'ua="\K[^"]*' | sort | uniq -c | sort -rn | head
    182 Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)
     62 Mozilla/5.0 (compatible; bingbot/2.0; ...)
#   ★★★★ 這些都是【假的】Googlebot

# ★★ 手動驗證一個 IP
$ IP=66.249.66.1
$ HOST=$(dig +short -x "$IP" | head -1)
$ echo "$HOST"
crawl-66-249-66-1.googlebot.com.
$ dig +short "$HOST"
66.249.66.1                                # ★★★ 一致 = verified
```

### ★★ CrowdSec 整合

```nginx
http {
    sentinel_crowdsec_zone cs:4m;

    server {
        sentinel_crowdsec_feed /var/lib/crowdsec/sentinel-feed.txt;
        sentinel_crowdsec_interval 10;              # ★★ 重新載入的間隔（秒）
        sentinel_crowdsec_default_ttl 3600;
        sentinel_crowdsec_stale_after 600;          # ★★ 超過就警告 feed 太舊
        sentinel_crowdsec_max_bytes 16m;
        sentinel_weight_crowdsec 100;

        # ★★★ 把 sentinel 的判決回饋給 CrowdSec
        sentinel_cs_sink_path /var/lib/crowdsec/sentinel-decisions.json;
        sentinel_cs_sink_interval 10;
        sentinel_cs_sink_scenario sentinel/http-abuse;
    }

    # ★★★ 多台共享封鎖狀態
    sentinel_redis 10.10.20.60:6379;
    sentinel_redis_password "很長的密碼";
    sentinel_redis_prefix sentinel;
    sentinel_redis_interval 10;
    sentinel_redis_ttl 3600;
}
```

```
★★★ CrowdSec 的動作分級：
  ban       → ★★★ 完整權重（100）→ 直接 block
  captcha   → ★★ 進入 challenge 區間
  throttle  → ★★ 進入 tarpit 區間
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **正常使用者被 429** ★★★★ | error-abuse 誤判 | **回 `dry_run=on`**；調高 `threshold` |
| **封鎖了整個機關** ★★★★ | **NAT 共用 IP** | `threshold` 設 500+；白名單；換 key |
| **封鎖了 CDN 的 IP** ★★★★ | `real_ip_header` 沒設 | **`set_real_ip_from` + `real_ip_header`** |
| **重啟後封鎖消失** ★★ | 沒有持久化 | `persist=`；或 `redis=on` |
| **多台各自為政** ★★★ | 沒有共享狀態 | **`error_abuse_redis`** |
| **白名單沒作用** ★★★ | **key 不是空字串** | **`map` 對應成 `""`**（模組忽略空 key） |
| **sentinel 誤判瀏覽器** ★★★★ | 權重/門檻不當 | **回 `shadow`**；調 `threshold`；查 `sig=` |
| **假 Googlebot 繞過防護** ★★★★ | **沒開 FCrDNS** | `sentinel_fcrdns` + `verify_suffix` |
| **FCrDNS 一直 pending** ★★★ | **沒設 `resolver`** | `resolver 1.1.1.1 ipv6=off;` |
| **PoW 擋掉 API 客戶端** ★★★★ | **API 沒有 JS** | **API 的 location `sentinel_pow off`** |
| **tarpit 把自己拖垮** ★★★★ | 並行數沒限制 | **`sentinel_tarpit_max_conns 256`** |
| **JA3/JA4 變數是空的** ★★★ | 缺 ssl-fingerprint 模組 | 安裝並 `ssl_fingerprint on;` |
| **ASN 是空的** ★★ | 缺 geoip2 或資料庫 | 安裝 geoip2；下載 GeoLite2-ASN |

### 排查

```bash
# 【1】★★★ 模組與設定
$ sudo nginx -T 2>/dev/null | grep -E 'load_module.*(error_abuse|sentinel)'
$ sudo nginx -T 2>/dev/null | grep -E '^\s*(error_abuse|sentinel)'

# 【2】★★★★ error-abuse 的狀態
$ sudo grep -oP 'ea=\K\w+' /var/log/nginx/abuse.log | sort | uniq -c
$ sudo grep 'ea=BLOCKED' /var/log/nginx/abuse.log | awk '{print $1}' | sort -u
$ sudo ls -l /var/lib/nginx/error-abuse.state

# 【3】★★★ 特定 IP 為什麼被封鎖
$ IP=203.0.113.45
$ sudo grep "^$IP " /var/log/nginx/abuse.log | tail -20
$ sudo grep "^$IP " /var/log/nginx/abuse.log | awk '{print $9, $7}' | \
    sort | uniq -c | sort -rn | head

# 【4】★★★★ sentinel 的評分
$ sudo grep -oP 'score=\K[0-9]+' /var/log/nginx/sentinel.log | \
    sort -n | uniq -c | tail -20
$ sudo grep 'verdict=block' /var/log/nginx/sentinel.log | tail -5 | cut -c1-200

# 【5】★★★★ 哪個訊號讓分數變高
$ sudo grep 'verdict=block' /var/log/nginx/sentinel.log | \
    grep -oP 'sig=\[\K[^]]*' | tr ',' '\n' | grep -v '=0' | \
    sort | uniq -c | sort -rn | head

# 【6】★★★ Prometheus 狀態
$ curl -s http://127.0.0.1/sentinel-status
sentinel_requests_total 482104
sentinel_verdict_total{v="allow"} 478210
sentinel_verdict_total{v="block"} 2840
sentinel_tarpit_active 12

# 【7】★★★ Redis 共享狀態
$ redis-cli -h 10.10.20.60 -a '密碼' --scan --pattern 'ea_*' | wc -l
$ redis-cli -h 10.10.20.60 -a '密碼' --scan --pattern 'sentinel*' | head

# 【8】★★★★ 真實 IP 是否正確
$ sudo awk '{print $1}' /var/log/nginx/abuse.log | sort -u | head
#   ★★★★ 都是同一個內部 IP = real_ip 沒設對
$ sudo nginx -T | grep -E 'set_real_ip_from|real_ip_header'
```

---

## 安全性注意事項

> [!danger] 六個要點 ★★★★
> ```
> ① ★★★★ sentinel 是實驗性的
>      → ★★★ 正式環境只用 shadow 模式
>      → 要 enforce 的話先小範圍（★ 單一 location）
>
> ② ★★★★ CDN/LB 後面一定要設 real_ip
>      → 兩個模組都依 IP 判斷
>      → ★★★ 沒設會封鎖所有使用者
>
> ③ ★★★★ PoW 會擋掉沒有 JS 的客戶端
>      → API、行動 App、無障礙工具、爬蟲（★ 包括你要的那些）
>      → ★★★ API 的 location 一定要 sentinel_pow off
>
> ④ ★★★★ tarpit 要限制並行數
>      → ★★★ 沒限制的話攻擊者可以用 tarpit 把你的連線佔滿
>      → sentinel_tarpit_max_conns + max_lifetime
>
> ⑤ ★★★ Redis 的安全
>      → ★★★★ 一定要設密碼且綁內網
>      → 封鎖狀態外洩 = 攻擊者知道自己被封了
>
> ⑥ ★★★ 日誌含完整的請求與 UA
>      → chmod 640；不在 web root；有保留期限
> ```

```bash
# ★★★★ CDN 後面的必要設定
$ sudo tee /etc/nginx/conf.d/00-realip.conf >/dev/null <<'EOF'
# ★★★★ 一定要在其他設定之前載入
set_real_ip_from 10.10.20.0/24;          # 內部 LB
set_real_ip_from 173.245.48.0/20;        # Cloudflare
set_real_ip_from 103.21.244.0/22;
# ... 完整清單見 https://www.cloudflare.com/ips/
real_ip_header CF-Connecting-IP;
real_ip_recursive on;
EOF

# ★★★★ 驗證看到的是真實 IP
$ sudo nginx -t && sudo systemctl reload nginx
$ sudo tail -20 /var/log/nginx/abuse.log | awk '{print $1}' | sort -u
203.0.113.45                              # ★★★ 真實客戶端
198.51.100.22
#   ★★★★ 只有一個內部 IP = 設定錯誤

# ★★★ Redis 的安全
$ sudo grep -E '^(bind|requirepass|protected-mode)' /etc/redis/redis.conf
bind 10.10.20.60 127.0.0.1                # ★★★ 不是 0.0.0.0
requirepass 很長的隨機密碼                  # ★★★★ 一定要有
protected-mode yes

$ sudo ss -tlnp | grep :6379
LISTEN 0 511 10.10.20.60:6379             # ★★★ 綁內網

# ★★★ PoW secret 的產生與輪替
$ openssl rand -hex 32
a1b2c3d4...
$ sudo tee /etc/nginx/pow-secret >/dev/null <<< "$(openssl rand -hex 32)"
$ sudo chmod 600 /etc/nginx/pow-secret
$ sudo chown root:root /etc/nginx/pow-secret

# ★★ 每季輪替
$ sudo tee /etc/cron.d/pow-secret-rotate >/dev/null <<'EOF'
0 3 1 1,4,7,10 * root openssl rand -hex 32 > /etc/nginx/pow-secret && \
  chmod 600 /etc/nginx/pow-secret && systemctl reload nginx
EOF

# ★★★★ 日誌的保護
$ sudo chmod 640 /var/log/nginx/{abuse,sentinel}.log
$ sudo chown www-data:adm /var/log/nginx/{abuse,sentinel}.log
$ sudo tee /etc/logrotate.d/nginx-abuse >/dev/null <<'EOF'
/var/log/nginx/abuse.log /var/log/nginx/sentinel.log {
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

# ★★★ 確認日誌不在 web root
$ curl -sko /dev/null -w '%{http_code}\n' https://app.example.gov.tw/abuse.log
404

# ★★★★ 誤判的緊急處理
$ sudo tee /usr/local/bin/abuse-unblock >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★★ 緊急解除封鎖（★ 最快的方式是 reload）
echo "★★★ 方式一：reload nginx（清空共享記憶體的封鎖狀態）"
echo "  sudo systemctl reload nginx"
echo ""
echo "★★★ 方式二：清除 Redis 中的封鎖"
echo "  redis-cli -h 10.10.20.60 -a PASS --scan --pattern 'ea_*' | \\"
echo "    xargs -r redis-cli -h 10.10.20.60 -a PASS DEL"
echo ""
echo "★★★ 方式三：刪除持久化檔案後 reload"
echo "  sudo rm -f /var/lib/nginx/error-abuse.state"
echo "  sudo systemctl reload nginx"
echo ""
echo "★★★★ 長期解法：把該來源加進白名單（map → \"\"）"
EOF
$ sudo chmod +x /usr/local/bin/abuse-unblock
```

---

## 速查表

### ★★★ error-abuse

```nginx
error_abuse_zone zone=ce:10m
    key=$binary_remote_addr        # ★★★ CDN 後面要先設 real_ip
    statuses=403,404,500-599
    interval=300s threshold=100 block=60m
    persist=/var/lib/nginx/error-abuse.state
    redis=on;

error_abuse zone=ce dry_run=on log_level=notice;   # ★★★★ 先 dry_run！

# ★★★★ 白名單：模組忽略【空的 key】
geo $exempt { default 0; 10.10.20.0/24 1; }
map $exempt $ea_key { 1 ""; default $binary_remote_addr; }
```

```
變數：$error_abuse_status（BYPASSED/PASSED/COUNTED/BLOCKED/DRY_RUN）
      $error_abuse_count / $error_abuse_blocked_until
```

### ★★★★ sentinel（實驗性）

```nginx
sentinel on;
sentinel_mode shadow;              # ★★★★ 正式環境只用 shadow
sentinel_threshold challenge=30 tarpit=60 block=80;
sentinel_zone main:20m;
sentinel_velocity_zone vz:5m rate=100 window=10 block=3600;
sentinel_honeypot /wp-login.php /.env /.git;
sentinel_allowlist 10.10.20.0/24;
sentinel_fcrdns fcdns;             # ★★★★ 防假 Googlebot（要 resolver）
sentinel_fcrdns_verify_suffix .googlebot.com .search.msn.com;
```

```
權重：scanner=50 bot=30 honeypot=90 velocity=30 asn=35
      c2ip=80 ja3=80 ja4=50 crowdsec=100
短路：★★★ 已知爬蟲 / allowlist → 分數歸零（CrowdSec 命中除外）
變數：$sentinel_score / $sentinel_verdict / $sentinel_fcrdns / $sentinel_ja4h
```

### ★★★ tarpit / PoW

```nginx
sentinel_tarpit_max_conns 256;     # ★★★★ 必要！防自我 DoS
sentinel_tarpit_delay 5000;
sentinel_tarpit_bytes 1024;
sentinel_tarpit_max_lifetime 30000;
sentinel_tarpit_maze on;           # ★★★ 滴誘餌連結（對 AI 爬蟲有效）

sentinel_pow on;
sentinel_pow_secret "$(openssl rand -hex 32)";   # ★★★★ 一定要隨機
sentinel_pow_difficulty 16;        # ★★★ 16~18（24 太久）
★★★★ API 的 location 一定要 sentinel_pow off（沒有 JS）
```

### ★★★★ 上線流程

```
error-abuse：dry_run=on → 分析 → 拿掉 dry_run
sentinel：   ★★★★ shadow（至少一個月）→ 分析判決分布與 UA →
             ★★★ 單一 location enforce → 逐步擴大

★★★★ 判斷可否 enforce：
  · block+tarpit 比率 < 5%
  · ★★★★ 被處置的請求中【沒有真實瀏覽器的 UA】
```

### ★★★★ 三個必做

```
① real_ip：CDN/LB 後面沒設 = 封鎖所有使用者
② dry_run / shadow 先行
③ tarpit_max_conns：不設會被拿來 DoS 自己
```

### 排錯

```bash
sudo grep -oP 'ea=\K\w+' /var/log/nginx/abuse.log | sort | uniq -c
sudo grep 'verdict=block' sentinel.log | grep -oP 'sig=\[\K[^]]*' | tr ',' '\n' | grep -v '=0'
sudo grep -oP 'fcrdns=\K\w+' sentinel.log | sort | uniq -c    # ★★★ spoofed = 假爬蟲
curl -s http://127.0.0.1/sentinel-status
sudo systemctl reload nginx        # ★★★ 緊急解除封鎖
```

---

## 練習題

> [!question]- 練習 1：error-abuse dry_run ★★★★
> 1. **設定 `error_abuse_zone` 與 `dry_run=on`**
> 2. **在 log_format 加上 `$error_abuse_status` 與 `$error_abuse_count`**
> 3. **連送 120 個 404** → 日誌中的 `ea=` 變化如何？
> 4. **請求有被擋嗎？**
> 5. **拿掉 `dry_run` 再測** → 第幾次開始回 429？
> 6. **`systemctl reload nginx` 後** → 還被封鎖嗎？為什麼？

> [!question]- 練習 2：白名單與 key ★★★★
> 1. **用 `geo` + `map` 把內網對應成空字串**
> 2. **從內網送 200 個 404** → 被封鎖嗎？
> 3. **`$error_abuse_status` 是什麼？**
> 4. **把 key 改成 `$binary_remote_addr$http_user_agent`**
> 5. **用兩個不同的 UA 各送 80 個 404** → 被封鎖嗎？
> 6. **這在 NAT 環境有什麼意義？**

> [!question]- 練習 3：持久化與 Redis ★★★
> 1. **設定 `persist=` 並 reload** → 檔案產生了嗎？
> 2. **封鎖一個 IP 後 restart nginx** → 還被封嗎？
> 3. **設定 Redis 共享**
> 4. **`redis-cli --scan --pattern 'ea_*'`** → 看得到嗎？
> 5. **在 A 機封鎖，從 B 機測試** → 也被封嗎？
> 6. **Redis 沒設密碼有什麼風險？**

> [!question]- 練習 4：sentinel shadow ★★★★
> 1. **設定 `sentinel_mode shadow` 與完整的 log_format**
> 2. **跑一段時間後執行 `sentinel-shadow-analyze`**
> 3. **判決分布如何？block 比率多少？**
> 4. **被判 block 的 UA 有真實瀏覽器嗎？**
> 5. **`sig=` 中哪個訊號觸發最多？**
> 6. **依分析結果決定：可以 enforce 嗎？要調什麼？**

> [!question]- 練習 5：FCrDNS 與假爬蟲 ★★★★
> 1. **用 `curl -H 'User-Agent: Mozilla/5.0 (compatible; Googlebot/2.1)'` 送掃描請求**
> 2. **沒開 FCrDNS 時，`$sentinel_score` 是多少？**
> 3. **為什麼？**（提示：短路規則）
> 4. **開啟 `sentinel_fcrdns` 與 `verify_suffix` 後再測**
> 5. **`fcrdns=` 是什麼？分數變了嗎？**
> 6. **手動用 `dig -x` 驗證一個真的 Googlebot IP**

---

## 小測驗

Q1. **error-abuse 和 fail2ban 的六個差異**？兩者該怎麼搭配？

Q2. **error-abuse 的白名單怎麼設**？為什麼是這個做法？

Q3. **`dry_run=on` 的用途**？上線流程該怎麼走？

Q4. **NAT 環境使用 error-abuse 要注意什麼**？三個對策？

Q5. **sentinel 的四級判決與預設門檻**？

Q6. **sentinel 的兩個「短路規則」是什麼**？為什麼危險？

Q7. **FCrDNS 是什麼**？沒開的話有什麼漏洞？

Q8. **tarpit 相對於直接 403 的優勢**？為什麼一定要限制並行數？

Q9. **PoW 挑戰不能用在哪些 location**？為什麼？

Q10. **為什麼 sentinel 在正式環境只建議用 shadow 模式**？

> [!question]- 測驗答案
> **Q1.** **六個差異**：
> ①**運作位置** —— fail2ban 是**外部程序讀日誌**，error-abuse **在 nginx 內部**；
> ②**★★★★ 反應速度** —— fail2ban 要等日誌寫入 + 輪詢（秒級），
> error-abuse **立即**（同一個請求就計數）；
> ③**封鎖方式** —— fail2ban 寫**防火牆規則**（連線層），
> error-abuse 回 **429**（應用層）；
> ④**資源開銷** —— fail2ban 多一個 Python 程序，error-abuse 是**共享記憶體，極小**；
> ⑤**★★★★ 多台共享** —— fail2ban 各自為政，error-abuse **可用 Redis 共享**；
> ⑥**跨服務** —— fail2ban **可以擋 SSH、郵件等**，error-abuse **只有 HTTP**。
> **★★★ 搭配方式**：error-abuse 做 HTTP 層的即時反應，
> fail2ban 讀 nginx 的日誌做**防火牆層的持久封鎖**（累犯遞增），
> 同時負責 SSH 等其他服務。
>
> **Q2.** **★★★★ 用 `map` 把信任的來源對應成空字串** ——
> 因為**模組會忽略空的 key**（不計數也不封鎖）。
> ```nginx
> geo $abuse_exempt {                    # ★★★ geo 支援 CIDR
>     default        0;
>     127.0.0.0/8    1;
>     10.10.20.0/24  1;
>     203.0.113.0/28 1;
> }
> map $abuse_exempt $ea_key {
>     1        "";                       # ★★★★ 空字串 = 不計數
>     default  $binary_remote_addr;
> }
> error_abuse_zone zone=ce:10m key=$ea_key;
> ```
> **為什麼用 `geo` 而不是直接 `map`** ——
> `map` 不支援 CIDR 網段比對，`geo` 才支援。
> 這個設計很優雅：**不需要額外的白名單指令**，
> 用 nginx 既有的變數機制就能表達任意複雜的豁免邏輯
> （例如「內網 + 特定 UA + 特定路徑」的組合）。
>
> **Q3.** **`dry_run=on` 讓模組正常計數與判斷，但「不實際封鎖」，只記錄** ——
> `$error_abuse_status` 會是 `DRY_RUN`，請求照常放行。
> **★★★★ 上線流程**：
> **①第一階段 `dry_run=on`** —— 在 log_format 加上
> `$error_abuse_status` 和 `$error_abuse_count`，跑一到兩週；
> **②分析** —— 哪些 IP 會被封鎖？它們在存取什麼？
> ```bash
> grep 'ea=DRY_RUN' abuse.log | awk '{print $1}' | sort | uniq -c | sort -rn
> ```
> 明顯是掃描器（大量 `.env`、`wp-admin`）就安全；
> **★★★ 特別注意「剛好超過門檻」的 IP**（可能是正常的重度使用者）；
> **③調整 `threshold`** 或加白名單；
> **④拿掉 `dry_run` 正式啟用**，密切監控 429 的比率。
>
> **Q4.** **★★★★ 一整個機關/學校/大樓可能共用一個對外 IP** ——
> 依 IP 計數的話，**一個人的異常行為會讓整個組織被封鎖**。
> **三個對策**：
> ①**★★★ 把 `threshold` 設高** —— 預設 100 對 NAT 環境太低，
> 依組織規模設 500~2000（先用 `dry_run` 觀察正常的錯誤量）；
> ②**★★★ 換一個 key** ——
> `key=$binary_remote_addr$http_user_agent`（IP + UA）
> 或 `key=$cookie_session`（依 session），
> 讓同一個 IP 的不同使用者分開計數（代價是更吃記憶體）；
> ③**★★★ 白名單** —— 已知的合作機關、分公司的固定 IP 加進豁免清單。
> **另外要注意 `block` 時長不要太久**（1h 就好），
> 誤判的影響才有上限。
>
> **Q5.** **四級判決與預設門檻**：
> ```
> 分數 < 30    →  allow      正常放行
> 30 ~ 59      →  challenge  ★★★ PoW 工作量證明頁面
> 60 ~ 79      →  ★★★★ tarpit  慢速滴水 / 限速 / 只給快取
> ≥ 80         →  block      403 / 444 / 斷線
> ```
> 設定方式：`sentinel_threshold challenge=30 tarpit=60 block=80;`
> **分數由加權訊號累加**：
> `honeypot=90`（誘餌路徑，最重）、
> `crowdsec=100`、`c2ip=80`、`ja3=80`、
> `scanner=50`（內建掃描路徑）、`ja4=50`、
> `asn=35`（資料中心）、`bot=30`、`velocity=30`、
> `errrate=1`（每次錯誤）。
> 權重設為 0 可以停用該訊號。**分數上限 100,000**（防溢位）。
>
> **Q6.** **兩個短路規則**（都會讓分數**強制歸零**）：
> ①**★★★ 已知的正常爬蟲 UA**（Googlebot、Bingbot 等）；
> ②**★★★ `sentinel_allowlist` 中的 IP**。
> **兩者都有例外：CrowdSec 命中時不短路**。
> **★★★★ 為什麼危險** —— 規則①：
> **User-Agent 是客戶端可以任意偽造的字串** ——
> 攻擊者只要把 UA 改成
> `Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)`，
> **分數就強制歸零，繞過所有防護**。
> **★★★★ 解方是 FCrDNS**：
> ```nginx
> sentinel_fcrdns fcdns;
> sentinel_fcrdns_verify_suffix .googlebot.com .search.msn.com;
> ```
> **FCrDNS 判定為 `spoofed` 時，這個短路會失效**。
> 所以**只要啟用了「已知爬蟲短路」，就必須同時啟用 FCrDNS**。
>
> **Q7.** **FCrDNS（Forward-Confirmed reverse DNS，正反解確認）** ——
> 驗證「自稱是 Googlebot 的請求，真的來自 Google 嗎」。
> **流程**：
> ①客戶端 UA 自稱 Googlebot →
> ②**對它的 IP 做反解**（`dig -x 66.249.66.1` → `crawl-66-249-66-1.googlebot.com`）→
> ③**再對那個網域做正解**（`dig crawl-66-249-66-1.googlebot.com` → `66.249.66.1`）→
> ④**兩個 IP 一致 = `verified`；不一致或反解失敗 = `spoofed`**。
> **★★★★ 沒開的漏洞**：
> sentinel 對已知爬蟲的 UA 會**分數強制歸零**，
> **攻擊者只要偽造 UA 就能完全繞過所有防護** ——
> 掃描、爆破、抓取都不會被計分。
> **需要 `resolver` 指令**（非同步查詢，狀態有 `pending`）。
> 驗證：`grep -oP 'fcrdns=\K\w+' sentinel.log | sort | uniq -c`，
> `spoofed` 的就是假爬蟲。
>
> **Q8.** **直接 403 的問題**：攻擊者**立刻收到回應，馬上換下一個目標或換 IP** ——
> 你省了資源，但**對方也省了**，掃描效率沒有降低。
> **★★★★ tarpit 的優勢**：**連線保持開啟但極慢地滴資料** ——
> 攻擊者的連線被佔住，**消耗的是對方的資源**（連線數、執行緒、時間）。
> `sentinel_tarpit_maze on` 還會**滴出誘餌連結**，
> 讓爬蟲繼續往下爬進迷宮 —— **對 AI 抓取特別有效**。
> **★★★★ 為什麼一定要限制並行數**：
> **每一個 tarpit 連線都佔用你自己的 worker 連線** ——
> 攻擊者可以**故意觸發大量 tarpit 把你的連線池佔滿**，
> 讓正常使用者連不進來（**用你的防護機制對你自己 DoS**）。
> ```nginx
> sentinel_tarpit_max_conns 256;        # ★★★★ 全域並行上限
> sentinel_tarpit_max_lifetime 30000;   # ★★★ 硬上限，不會無限期掛著
> ```
>
> **Q9.** **★★★★ 不能用在 API 的 location**，以及任何**沒有 JavaScript 執行環境**的客戶端會存取的路徑。
> **PoW 挑戰的原理是回一個 HTML 頁面，讓瀏覽器用 JS 計算雜湊** ——
> 找到前導零位元數符合 `sentinel_pow_difficulty` 的 nonce，
> 通過後設 cookie 放行。
> **完全無法通過的客戶端**：
> **REST API 的呼叫方**（curl、後端服務、其他系統的整合）、
> **行動 App**（原生的 HTTP client）、
> **無障礙輔助工具**、
> **你希望通過的正常爬蟲**（Googlebot 不會執行 PoW）。
> ```nginx
> location /api/ {
>     sentinel_pow off;                                    # ★★★★ 必須
>     sentinel_threshold challenge=100 tarpit=80 block=90; # ★★★ 門檻調高
> }
> ```
> **難度也要注意**：16 約 0.1~1 秒（建議），
> 20 約 2~10 秒，**24 太久，正常使用者會直接離開**。
> secret 必須是 `openssl rand -hex 32` 的隨機值（固定值可被預先計算）。
>
> **Q10.** **★★★★ 官方明確標示它是 EXPERIMENTAL，而且仍在 planning stage** ——
> **API 與行為可能有重大變更**，升級模組可能讓你的設定失效或行為改變。
> **更實際的風險**：
> ①**★★★★ 誤判會直接影響真實使用者** ——
> sentinel 的評分綜合了十幾個訊號，
> 任何一個權重不當就可能讓正常瀏覽器被判 `tarpit` 或 `block`，
> 而**使用者不會告訴你「我被擋了」，他們只會離開**；
> ②**★★★ 訊號來源依賴外部資料**（GeoIP ASN 資料庫、abuse.ch 清單、CrowdSec feed），
> 資料過期或錯誤會造成誤判；
> ③**★★★ tarpit 和 PoW 有自我 DoS 與擋掉 API 客戶端的風險**。
> **★★★★ 正確做法**：
> `sentinel_mode shadow` **至少觀察一個月**，
> 用 `sentinel-shadow-analyze` 確認
> **「block+tarpit 比率 < 5%」且「被處置的請求中沒有真實瀏覽器的 UA」**，
> 然後**先在單一 location（例如 `/admin/`）enforce**，逐步擴大。

---

## 延伸閱讀

- [[060-02-05-04-guide-http-shield攻擊攔截]] — 已知漏洞利用的攔截
- [[090-02-05-guide-防護-Fail2ban入侵防護]] — **★★★ 防火牆層的封鎖（互補）**
- [[060-02-02-08-guide-Nginx-效能調校]] — `limit_req` / `limit_conn` 的基礎限流
- [[060-02-02-09-guide-Nginx-安全設定]] — NGINX 的安全基礎
- [[060-02-05-08-guide-MyGuard-MyGuard實戰組合]] — 完整的實戰配置
- [[090-08-04-guide-Wazuh-FIM檔案完整性監控]] — 集中式的資安監控
