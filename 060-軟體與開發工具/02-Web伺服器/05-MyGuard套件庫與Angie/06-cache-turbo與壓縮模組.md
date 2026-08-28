---
title: "cache-turbo 與壓縮模組"
desc: "內建邊緣快取、回應精簡與 Brotli/Zstd 壓縮"
aliases: [cache-turbo, strip-filter, zstd, brotli, 邊緣快取, SWR, 壓縮]
tags: [群組/軟體與開發工具, 服務/nginx, 服務/myguard, 主題/效能]
category: MyGuard與Angie
difficulty: 進階
status: 完成
distro: [ubuntu]
prerequisites: ["[[05-Nginx-靜態資源與快取]]", "[[08-Nginx-效能調校]]"]
updated: 2026-08-28
---

# cache-turbo 與壓縮模組

> [!abstract] 這篇你會學到
> - **★★★★ `cache-turbo`**：NGINX 內建的邊緣快取（★ 像是內建的 Varnish）
> - **★★★★ stale-while-revalidate 與 single-flight**（★ 防 dogpile）
> - 三層架構：L1 共享記憶體 → L2 Redis → 上游
> - CMS 預設分類、auto-vary、清除機制
> - **★★★ `strip-filter`**：HTML/CSS/JS/JSON 精簡
> - **★★★ Brotli 與 Zstandard** 壓縮的取捨
> - **★★★★ 快取三層的關係**（cache-turbo / proxy_cache / CDN）

> [!warning] 未實機驗證 ★★★
> ```
> ★★★ 本章依據 myguard-labs 的 GitHub 文件（2026 年 8 月）撰寫。
> ★★★★ 實作前請對照官方 README 確認指令與預設值。
> ```

## 前置知識

- [[05-Nginx-靜態資源與快取]] — **★★★ `proxy_cache` 的基礎**
- [[08-Nginx-效能調校]] — gzip 與效能設定
- [[01-MyGuard套件庫介紹]] — 套件庫與模組安裝

---

## ★★★★ cache-turbo 是什麼

```
★★★★ 官方的一句話：
  「Think of it as a tiny Varnish that lives inside nginx
    — no extra daemon, no second port, no Lua.」
  → ★★★ 一個住在 nginx 裡面的迷你 Varnish

★★★★ 和 nginx 內建 proxy_cache 的差異：

  ┌────────────────────┬──────────────────────┬──────────────────────────┐
  │                    │ ★★★ proxy_cache      │ ★★★★ cache-turbo         │
  ├────────────────────┼──────────────────────┼──────────────────────────┤
  │ 儲存位置           │ ★★ 磁碟（+ page cache）│ ★★★★ 共享記憶體（L1）    │
  │ 讀取延遲           │ ★★ 毫秒級（有磁碟 I/O）│ ★★★★ 次毫秒級           │
  │ ★★★★ stale-while-  │ ★★ 有（proxy_cache_   │ ★★★★ 有，且更完整        │
  │    revalidate      │    background_update）│                          │
  │ ★★★★ single-flight │ ★★ proxy_cache_lock  │ ★★★★ 內建，更細緻        │
  │ ★★★ 多台共享       │ ✗                    │ ★★★★ ✓（L2 Redis）       │
  │ ★★★ CMS 感知       │ ✗（要自己寫規則）    │ ★★★★ ✓（30+ 預設）       │
  │ auto-vary          │ ✗（要自己處理）      │ ★★★ ✓（讀 Vary 標頭）    │
  │ 清除               │ ★★ 商業版才有 purge  │ ★★★ 內建 admin 端點      │
  │ 記憶體用量         │ ★★★ 小（只有 key）   │ ★★ 大（★ 內容在記憶體）  │
  │ 快取容量           │ ★★★ 大（磁碟）       │ ★★ 受記憶體限制          │
  └────────────────────┴──────────────────────┴──────────────────────────┘

★★★★ 選擇原則：
  · ★★★ 熱門內容少、要求極低延遲   → cache-turbo
  · ★★★ 內容量大（大量圖片/影片） → proxy_cache（磁碟）
  · ★★★★ 兩者可以【並用】：cache-turbo 當 L1，proxy_cache 當 L2
```

### ★★★ 三層架構

```
★★★★ cache-turbo 的請求流程：

  請求進來
     │
     ▼
  ┌──────────────────────────────────────┐
  │ ★★★★ L1：共享記憶體（每台機器各自）   │
  │   · 次毫秒級                          │
  │   · ★★★ 容量受記憶體限制              │
  └──────────┬───────────────────────────┘
             │ MISS
             ▼
  ┌──────────────────────────────────────┐
  │ ★★★ L2：Redis / memcached（選用）     │
  │   · ★★★★ 整個叢集共享                │
  │   · ★★★ 重啟後可以暖啟動              │
  │   · ★★ 只在 L1 MISS 時才碰            │
  └──────────┬───────────────────────────┘
             │ MISS
             ▼
  ┌──────────────────────────────────────┐
  │ 上游（你的應用程式）                   │
  └──────────────────────────────────────┘

★★★ L2 的價值：
  · 一台機器熱身好的內容，其他台直接用
  · ★★★★ nginx 重啟後不會「冷啟動」把上游打爆
```

---

## 安裝

```bash
$ sudo apt install -y libnginx-mod-http-cache-turbo \
                      libnginx-mod-http-strip-filter \
                      libnginx-mod-http-zstd \
                      libnginx-mod-http-brotli
#   ★★★ 套件名稱可能不同
$ apt-cache search 'cache-turbo|strip|zstd|brotli'

$ ls -l /usr/lib/nginx/modules/ | grep -E 'cache_turbo|strip|zstd|brotli'
$ sudo nginx -t
```

---

## ★★★★ cache-turbo 設定

### 最小可用

```nginx
load_module modules/ngx_http_cache_turbo_module.so;

http {
    # ★★★★ 定義共享記憶體區（★ 必須先定義）
    cache_turbo_zone name=ct 256m;

    server {
        listen 443 ssl;
        server_name app.example.gov.tw;

        location / {
            cache_turbo ct;                 # ★★★★ 啟用
            cache_turbo_valid 60s;          # ★★★ 新鮮期（預設 60s）
            proxy_pass http://backend;
        }
    }
}
```

### ★★★ 完整指令

| 指令 | 語境 | 預設 | 說明 |
| --- | --- | --- | --- |
| **`cache_turbo_zone name=X SIZE`** | http | — | **★★★★ 共享記憶體區** |
| **`cache_turbo <zone>`** | location | — | **★★★★ 啟用** |
| **`cache_turbo_valid <time>`** | | `60s` | **★★★ 新鮮期 TTL** |
| **`cache_turbo_valid <codes> <time>`** | | `200` | **★★ 依狀態碼設 TTL** |
| **`cache_turbo_key <string>`** | | `Host + unparsed_uri` | **★★★ 快取鍵** |
| **`cache_turbo_normalize_strip <args>`** | | — | **★★★ 移除追蹤參數** |
| **`cache_turbo_stale_while_revalidate <t>`** | | 依預設集 | **★★★★ 過期後仍供應多久** |
| **`cache_turbo_stale_if_error <t>`** | | — | **★★★★ 上游掛掉時的寬限** |
| **`cache_turbo_lock_ttl <t>`** | | `5s` | **★★★★ single-flight 鎖** |
| **`cache_turbo_bypass <var>`** | | — | **★★★ 跳過查詢** |
| **`cache_turbo_no_store <var>`** | | — | **★★★ 不儲存回應** |
| **`cache_turbo_backend <cms>`** | | — | **★★★★ CMS 自動分類** |
| `cache_turbo_cache_control honor` | | — | ★★ 尊重 Cache-Control |
| **`cache_turbo_auto_vary on\|off`** | | `on` | **★★★ 依 Vary 標頭分割** |
| **`cache_turbo_redis "host:port"`** | http | — | **★★★ L2 共享** |
| **`cache_turbo_admin_path <path>`** | | — | **★★ 清除端點** |

### ★★★★ stale-while-revalidate 與 single-flight

```
★★★★ 這是 cache-turbo 最有價值的兩個機制：

【★★★★ stale-while-revalidate（SWR）】
  沒有 SWR 時：
    快取過期 → ★★★ 使用者【等】上游回應 → 才拿到內容
    → ★★★★ 每次過期都有一個使用者要承受完整的延遲

  ★★★★ 有 SWR：
    快取過期 → ★★★ 【立刻給過期的內容】（使用者不用等）
             → ★★ 同時在【背景】向上游取新的
    → ★★★★ 使用者永遠不會等上游

  cache_turbo_stale_while_revalidate 4m;

【★★★★ single-flight（防 dogpile / cache stampede）】
  沒有鎖時：
    熱門頁面快取過期的那一瞬間
    → ★★★★ 【1000 個並行請求同時打向上游】
    → ★★★ 上游瞬間被打爆（★ 這叫 cache stampede / dogpile）

  ★★★★ 有鎖：
    第一個 MISS 拿到鎖 → 去問上游
    → ★★★ 其他 999 個【等鎖】或【拿過期的內容】
    → ★★★★ 上游只收到【1 個】請求

  cache_turbo_lock_ttl 5s;

★★★★ 兩者合起來：
  熱門頁面過期 → 999 個使用者拿到過期內容（0ms）
               → 1 個背景請求去更新
               → ★★★★ 上游壓力 = 1/1000，使用者延遲 = 0
```

```nginx
# ★★★★ 完整的 SWR + single-flight 設定
location / {
    cache_turbo ct;
    cache_turbo_valid 60s;                      # ★★★ 60 秒內是「新鮮的」

    cache_turbo_stale_while_revalidate 4m;      # ★★★★ 過期後 4 分鐘仍可供應
    cache_turbo_stale_if_error 24h;             # ★★★★ 上游掛掉時供應 24 小時

    cache_turbo_lock_ttl 5s;                    # ★★★★ 併發鎖

    proxy_pass http://backend;
}
```

```
★★★★ cache_turbo_stale_if_error 的價值（★ 最被低估的功能）：

  上游整個掛掉時：
    沒有 stale_if_error → ★★★★ 使用者看到 502
    ★★★★ 有 stale_if_error → 使用者看到【24 小時前的內容】

  → ★★★ 對「內容不常變」的網站（★ 機關的公告網站）
    這等於【上游掛了使用者也感覺不到】
  → ★★ 回應標頭會是 X-Cache: STALE-IF-ERROR
```

### ★★★ 快取鍵與參數正規化

```nginx
# ★★★ 預設的 key：Host + 未解析的 URI（★ 完全不正規化）
#   → /page?a=1&b=2 和 /page?b=2&a=1 是【不同】的快取項目
#   → ★★★★ 追蹤參數（utm_source 等）會讓快取命中率暴跌

# ★★★★ 正規化：移除追蹤參數
location / {
    cache_turbo ct;
    cache_turbo_key $host$uri$cache_turbo_normalized_args;
    cache_turbo_normalize_strip utm_source utm_medium utm_campaign utm_term
                                utm_content fbclid gclid msclkid
                                sid sessionid "tmp_*";
    #   ★★★ 支援萬用字元
    proxy_pass http://backend;
}
```

```bash
# ★★★★ 驗證正規化生效
$ curl -sI "https://app.example.gov.tw/news?utm_source=facebook" | grep -i x-cache
x-cache: MISS
$ curl -sI "https://app.example.gov.tw/news?utm_source=twitter" | grep -i x-cache
x-cache: HIT                              # ★★★★ 不同的 utm 也命中了

# ★★★ 沒有正規化的話
x-cache: MISS                             # ★★★★ 每個 utm 都是新的快取項目
```

### ★★★★ CMS 自動分類

```nginx
# ★★★★ 一行搞定 WordPress 的所有動態頁面
location / {
    cache_turbo ct;
    cache_turbo_valid 60s;
    cache_turbo_backend wordpress woocommerce;
    #   ★★★★ 自動跳過：
    #     · 登入/session 流量（wordpress_logged_in_* cookie）
    #     · /wp-admin/ /wp-login.php
    #     · 搜尋、預覽、購物車、結帳
    #   ★★★ 而且【完全不儲存】這些回應
    proxy_pass http://backend;
}
```

```
★★★ 支援 30+ 種 CMS 預設，常見的有：
  wordpress / woocommerce / drupal / magento / ghost
  joomla / prestashop / opencart / typo3 / laravel ...

★★★★ 每個預設定義了三類跳過條件：
  · URI 前綴（/wp-admin/、/administrator/）
  · 查詢參數（?preview=、?s=）
  · ★★★ Cookie 子字串（wordpress_logged_in_、woocommerce_cart_hash）
```

> [!danger] 快取動態內容的災難 ★★★★
> ```
> ★★★★ 最嚴重的快取錯誤：把【登入使用者的頁面】快取起來
>
>   使用者 A 登入 → 看到「歡迎，張三」的頁面
>   → ★★★★ 這個頁面被快取
>   → 使用者 B（未登入）訪問同一個 URL
>   → ★★★★ 看到「歡迎，張三」！
>   → ★★★★ 【個資外洩】+ 可能連 session 都被共用
>
> ★★★ 三層防護：
>   ① ★★★★ cache_turbo_backend <cms>（自動處理已知的 CMS）
>   ② ★★★★ cache_turbo_no_store $cookie_session;
>      → 有 session cookie 的回應【絕對不儲存】
>   ③ ★★★ cache_turbo_bypass $cookie_session;
>      → 有 session cookie 的請求【不查快取】
>
> ★★★★ 自己寫的應用程式一定要手動設定這三個！
> ```

```nginx
# ★★★★ Laravel / 自訂應用程式的安全設定
http {
    # ★★★ 判斷是否為已登入的請求
    map $http_cookie $skip_cache {
        default                     0;
        "~*laravel_session"         1;      # ★★★★ Laravel 的 session
        "~*XSRF-TOKEN"              1;
        "~*remember_web_"           1;      # ★★ remember me
    }

    map $request_method $skip_cache_method {
        default   1;                        # ★★★★ 非 GET/HEAD 一律不快取
        GET       0;
        HEAD      0;
    }

    server {
        location / {
            cache_turbo ct;
            cache_turbo_valid 60s;

            # ★★★★ 三層防護
            cache_turbo_bypass   $skip_cache $skip_cache_method $http_authorization;
            cache_turbo_no_store $skip_cache $skip_cache_method $http_authorization;
            cache_turbo_cache_control honor;    # ★★★ 尊重應用程式的 Cache-Control

            proxy_pass http://backend;
        }

        # ★★★★ API 與後台完全不快取
        location /api/ {
            proxy_pass http://backend;
        }
        location /admin/ {
            proxy_pass http://backend;
        }
    }
}
```

```bash
# ★★★★ 驗證登入頁面沒有被快取
$ curl -sI https://app.example.gov.tw/dashboard \
    -H 'Cookie: laravel_session=abc123' | grep -iE 'x-cache|set-cookie'
x-cache: BYPASS                           # ★★★ 正確

# ★★★★ 最重要的測試：登入後的內容會不會被別人拿到
$ curl -s -c /tmp/ck https://app.example.gov.tw/login >/dev/null
$ curl -s -b /tmp/ck https://app.example.gov.tw/dashboard | grep -o '歡迎[^<]*'
歡迎，張三
$ curl -s https://app.example.gov.tw/dashboard | grep -o '歡迎[^<]*'
#   ★★★★ 沒有輸出 = 正確（未登入者拿不到）
#   ★★★★ 有「歡迎，張三」= 【嚴重的個資外洩】，立刻停用快取！
```

### ★★★ 預設集與 L2

```nginx
# ★★ 四種內建的調校預設集
#   micro         新鮮 1s   stale ×2  refresh 1000
#   conservative  新鮮 30s  stale ×2  refresh 500
#   balanced      新鮮 60s  stale ×4  refresh 1000
#   aggressive    新鮮 300s stale ×8  refresh 3000

location / {
    cache_turbo ct;
    # ★★ 用預設集快速起步，再依需要覆寫個別參數
    cache_turbo_valid 60s;
    cache_turbo_stale_while_revalidate 4m;
}

# ═══ ★★★ L2 Redis（多台共享）═══
http {
    cache_turbo_zone name=ct 256m;
    cache_turbo_redis "10.10.20.60:6379" keepalive=10;
    #   ★★★★ Redis 要設密碼且綁內網！
}
```

### ★★★ auto-vary

```nginx
# ★★★ 預設開啟：讀回應的 Vary 標頭，依對應的請求標頭分割快取
cache_turbo_auto_vary on;

# ★★★ 安全的 vary 軸：
#   Accept-Encoding   ★★★★ 壓縮格式（gzip/br/zstd 要分開存）
#   Accept-Language   ★★ 多語系
#   User-Agent        ★★ 行動版/桌面版
#   Origin            ★★ CORS

# ★★★★ 不可快取的 Vary：
#   Vary: Cookie          → ★★★★ 每個使用者一份，等於沒快取
#   Vary: Authorization   → ★★★★ 同上
#   Vary: *               → ★★★★ 完全不能快取
#   → ★★★ 模組會自動【不儲存】這些回應
```

### ★★ 監控與清除

```nginx
server {
    # ★★★ 記錄快取狀態
    log_format cache '$remote_addr - [$time_local] "$request" $status '
                     'cache=$cache_turbo_status rt=$request_time '
                     'urt=$upstream_response_time';
    access_log /var/log/nginx/cache.log cache;

    location / {
        cache_turbo ct;
        cache_turbo_valid 60s;
        add_header X-Cache $cache_turbo_status always;   # ★★★ 方便除錯
        proxy_pass http://backend;
    }

    # ★★ 清除端點（★ 一定要限制存取）
    location /admin/cache {
        cache_turbo_admin_path /admin/cache;
        allow 127.0.0.1;
        allow 10.10.20.0/24;
        deny all;
    }
}
```

```
★★★ 回應標頭與變數：
  X-Cache: HIT              ★★★ L1 命中
  X-Cache: STALE            ★★★ 供應過期內容，背景更新中
  X-Cache: STALE-IF-ERROR   ★★★★ 上游掛了，供應舊內容
  X-Cache: MISS             未命中
  X-Cache: BYPASS           ★★★ 被 bypass 跳過

  $cache_turbo_status       ★★★ 同上
  $cache_turbo_hits / $cache_turbo_misses
  $cache_turbo_lock_waits   ★★★ 等鎖的次數（★ dogpile 的指標）
```

```bash
#!/usr/bin/env bash
# ★★★ /usr/local/bin/cache-monitor
LOG=/var/log/nginx/cache.log
TODAY=$(date '+%d/%b/%Y')

echo "═══ cache-turbo 監控 $(date '+%F %T') ═══"

echo -e "\n【★★★★ 命中率】"
grep "$TODAY" "$LOG" 2>/dev/null | grep -oP 'cache=\K\S+' | \
  sort | uniq -c | sort -rn | \
  awk '{a[$2]=$1; t+=$1} END {
    for (k in a) printf "  %-18s %8d  (%.2f%%)\n", k, a[k], a[k]/t*100
    printf "  ─────────────────────────────\n"
    hit = a["HIT"] + a["STALE"] + a["STALE-IF-ERROR"]
    printf "  ★★★★ 有效命中率: %.2f%%", hit/t*100
    if (hit/t < 0.5) printf "  ★★★ 偏低，檢查 key 與 bypass 條件"
    print ""
  }'

echo -e "\n【★★★ 回應時間（依快取狀態）】"
for s in HIT STALE MISS BYPASS; do
    grep "$TODAY" "$LOG" 2>/dev/null | grep "cache=$s" | \
      grep -oP 'rt=\K[0-9.]+' | sort -n | \
      awk -v s="$s" '{a[NR]=$1} END {
        if (NR>0) printf "  %-10s P50=%.3fs P95=%.3fs (n=%d)\n",
                  s, a[int(NR*0.5)], a[int(NR*0.95)], NR}'
done

echo -e "\n【★★★ 最常 MISS 的 URL】"
grep "$TODAY" "$LOG" 2>/dev/null | grep 'cache=MISS' | \
  awk '{print $7}' | sed 's/?.*//' | sort | uniq -c | sort -rn | head -10 | \
  awk '{printf "  %6d  %s\n", $1, $2}'

echo -e "\n【★★★★ BYPASS 的比例（★ 太高表示快取沒發揮作用）】"
B=$(grep "$TODAY" "$LOG" 2>/dev/null | grep -c 'cache=BYPASS' || echo 0)
T=$(grep -c "$TODAY" "$LOG" 2>/dev/null || echo 1)
awk -v b="$B" -v t="$T" 'BEGIN{printf "  BYPASS: %d/%d (%.2f%%)  ", b, t, b/t*100
  if (b/t > 0.5) print "★★★★ 過半被跳過，檢查 bypass 條件"; else print "✓"}'
```

---

## ★★★ strip-filter：回應精簡

```bash
$ sudo apt install -y libnginx-mod-http-strip-filter
```

| 指令 | 語境 | 預設 | 說明 |
| --- | --- | --- | --- |
| **`strip on\|off`** | http/server/location | `off` | **★★★ HTML 精簡** |
| **`strip_css`** | | `off` | CSS |
| **`strip_js`** | | `off` | **★★ JavaScript** |
| **`strip_json`** | | `off` | **★★★ JSON**（★ API 有效） |
| `strip_svg` | | `off` | SVG |
| `strip_xml` | | `off` | XML（RSS/sitemap） |
| **`strip_aggressive`** | | `off` | **★★★★ JS 的註解與空白**（見下） |
| `strip_min_size` | | `0` | 小於此值不處理 |
| **`strip_max_size`** | | `1m` | **★★★ 大於此值跳過** |
| `strip_types` | | `text/html` | 額外視為 HTML 的 MIME |

```nginx
# ★★★ 基本設定
http {
    strip      on;
    strip_css  on;
    strip_js   on;
    strip_json on;
    strip_min_size 1k;              # ★★ 太小的不值得處理
    strip_max_size 1m;              # ★★★ 太大的跳過（★ 避免吃記憶體）
}
```

```
★★★★ 絕對不會被動到的區域（★ 這是安全保證）：

  HTML：<pre> <textarea> <script> <style> <title>
        <iframe> <xmp> <noembed> <noframes>
  CSS/JSON：字串字面值
  ★★★ SVG/XML：註解保留、CDATA 永遠保護
  ★★★★ aggressive JS 模式：字串/模板/regex 字面值、ASI 關鍵的換行

★★★ 預設的處理：
  HTML  註解、布林屬性、安全的屬性值去引號
  CSS   註解、多餘空白、結尾分號
  ★★★★ JS  【預設 byte-identical】（★ 完全不動）
  JSON  移除所有結構性空白
```

> [!danger] `strip_aggressive` 的風險 ★★★★
> ```
> ★★★★ 預設 JavaScript 是【完全不動的】（byte-identical）
>       → 開了 strip_aggressive 才會移除註解與空白
>
> ★★★ 為什麼預設不動：
>   JavaScript 的 ASI（自動分號插入）讓【換行有語意】
>     return
>     { a: 1 }
>   → ★★★★ 移除換行會變成完全不同的程式碼
>   → 模組宣稱會保護 ASI 關鍵的換行，但仍有風險
>
> ★★★★ 建議：
>   · ★★★ 前端資源應該在【建置階段】就 minify（Vite/webpack）
>   · ★★ strip_js 用預設（不 aggressive）就好
>   · ★★★★ 要開 aggressive 的話【一定要在測試環境完整驗證】
>     → 所有頁面的 JS 功能都要測過
>
> ★★★ 最實用的其實是 strip_json：
>   → API 回應移除空白，★★ 對大量小 JSON 的 API 有感
> ```

```bash
# ★★★ 驗證精簡效果
$ curl -s https://app.example.gov.tw/ | wc -c
48210
$ curl -s https://app.example.gov.tw/ | grep -c '<!--'
0                                          # ★★★ 註解被移除

# ★★★ 對照未精簡的（暫時關掉）
$ sudo sed -i 's/^\(\s*strip\s*\)on;/\1off;/' /etc/nginx/conf.d/strip.conf
$ sudo systemctl reload nginx
$ curl -s https://app.example.gov.tw/ | wc -c
52840
#   ★★ 省了約 9%

# ★★★★ 但要注意：搭配壓縮之後的效果
$ curl -s --compressed https://app.example.gov.tw/ | wc -c
#   ★★★ gzip/br 本來就會把空白壓得很好
#   → ★★★★ strip 的邊際效益在【壓縮之後】其實不大
#   → ★★ 真正有價值的是【減少解壓後的解析時間】
```

---

## ★★★ 壓縮：gzip / Brotli / Zstandard

```
★★★★ 三種壓縮的比較：

  ┌──────────┬──────────┬──────────┬──────────┬────────────────────┐
  │          │ 壓縮率   │ 壓縮速度 │ 解壓速度 │ ★ 瀏覽器支援       │
  ├──────────┼──────────┼──────────┼──────────┼────────────────────┤
  │ gzip     │ ★★ 基準  │ ★★★ 快   │ ★★★ 快   │ ★★★★ 100%          │
  │ ★★★ br   │ ★★★★ 最好│ ★★ 慢    │ ★★★ 快   │ ★★★ 96%+（HTTPS）  │
  │          │ (~20% 更小)│         │          │                    │
  │ ★★ zstd  │ ★★★ 好   │ ★★★★ 最快│ ★★★★ 最快│ ★★ 有限（Chrome）  │
  └──────────┴──────────┴──────────┴──────────┴────────────────────┘

★★★★ 實務建議：
  ① ★★★ 靜態資源【預先壓縮】（build 時產生 .gz 和 .br）
     → ★★★★ 最好的做法：壓縮成本是零，用最高等級
  ② ★★★ 動態內容用 br 等級 4~5（★ 平衡壓縮率與 CPU）
  ③ ★★ zstd 目前支援度還不夠廣，可以開但不能只靠它
  ④ ★★★★ 已經壓縮的檔案不要再壓（jpg/png/mp4/zip/woff2）
```

```nginx
http {
    # ═══ ★★★ gzip（★ 保底，一定要開）═══
    gzip on;
    gzip_vary on;                          # ★★★★ 一定要開（★ 快取正確性）
    gzip_comp_level 5;                     # ★★★ 5 是平衡點（9 的 CPU 不划算）
    gzip_min_length 1024;                  # ★★ 太小的不值得壓
    gzip_proxied any;
    gzip_types
        text/plain text/css text/xml text/javascript
        application/javascript application/json application/xml
        application/rss+xml application/atom+xml
        image/svg+xml font/ttf font/otf;
    #   ★★★★ 不要加：image/jpeg image/png video/* application/zip font/woff2

    # ═══ ★★★ Brotli ═══
    brotli on;
    brotli_comp_level 5;                   # ★★★ 動態內容用 4~5
    brotli_min_length 1024;
    brotli_types
        text/plain text/css text/xml text/javascript
        application/javascript application/json application/xml
        image/svg+xml;

    # ★★★★ 預先壓縮的靜態檔案（★ 最有價值）
    brotli_static on;                      # ★★★★ 找 .br 檔案直接送

    # ═══ ★★ Zstandard ═══
    zstd on;
    zstd_comp_level 6;
    zstd_min_length 1024;
    zstd_types text/plain text/css application/javascript application/json;
    zstd_static on;

    # ═══ ★★★★ gzip 的預先壓縮 ═══
    gzip_static on;                        # ★★★★ 找 .gz 檔案直接送
}
```

```bash
# ═══ ★★★★ 建置時預先壓縮（★ 最佳做法）═══
$ cd /var/www/app/current/public/build
$ find . -type f \( -name '*.js' -o -name '*.css' -o -name '*.svg' \
                 -o -name '*.json' -o -name '*.html' \) | while read -r f; do
    # ★★★★ 用最高等級（★ 反正只壓一次）
    gzip -9 -k -f "$f"
    brotli -q 11 -f "$f"
    zstd -19 -q -f "$f" -o "$f.zst" 2>/dev/null
  done

$ ls -lh app-a1b2c3.js*
-rw-r--r-- 1 deploy www-data 482K app-a1b2c3.js
-rw-r--r-- 1 deploy www-data 124K app-a1b2c3.js.br      # ★★★ 74% 減少
-rw-r--r-- 1 deploy www-data 142K app-a1b2c3.js.gz      # ★★ 71%
-rw-r--r-- 1 deploy www-data 131K app-a1b2c3.js.zst

# ★★★ 加進部署腳本
$ cat >> /usr/local/bin/deploy-app <<'EOF'
# ★★★★ 預先壓縮靜態資源
find "$REL/public/build" -type f \( -name '*.js' -o -name '*.css' -o -name '*.svg' \) \
  -exec sh -c 'gzip -9 -k -f "$1"; brotli -q 11 -f "$1"' _ {} \;
EOF
```

```bash
# ═══ ★★★ 驗證壓縮 ═══
$ curl -sI -H 'Accept-Encoding: br' https://app.example.gov.tw/build/app.js | \
    grep -iE 'content-encoding|content-length|vary'
content-encoding: br
content-length: 126976
vary: Accept-Encoding                     # ★★★★ 一定要有

$ curl -sI -H 'Accept-Encoding: gzip' https://app.example.gov.tw/build/app.js | \
    grep -i content-encoding
content-encoding: gzip

$ curl -sI -H 'Accept-Encoding: zstd' https://app.example.gov.tw/build/app.js | \
    grep -i content-encoding
content-encoding: zstd

# ★★★★ 比較各種壓縮的大小
$ for enc in identity gzip br zstd; do
    printf "%-10s " "$enc"
    curl -sI -H "Accept-Encoding: $enc" https://app.example.gov.tw/build/app.js | \
      grep -i '^content-length' | awk '{print $2}' | tr -d '\r' | numfmt --to=iec
  done
identity   482K
gzip       142K
br         124K
zstd       131K
```

> [!danger] `Vary: Accept-Encoding` 是必要的 ★★★★
> ```
> ★★★★ 沒有 Vary: Accept-Encoding 時：
>
>   使用者 A（支援 br）→ 快取存了 br 壓縮的版本
>   使用者 B（只支援 gzip）→ ★★★★ 拿到 br 的內容但不會解壓
>   → ★★★★ 【頁面顯示成亂碼或完全打不開】
>
> ★★★ 三個地方要確認：
>   ① gzip_vary on;    ★★★★（brotli/zstd 模組通常自動加）
>   ② ★★★ cache_turbo_auto_vary on;（預設就是 on）
>   ③ ★★ CDN 也要正確處理 Vary
>
> ★★★ 驗證：
>   curl -sI https://app.example.gov.tw/ | grep -i vary
>   → 一定要看到 vary: Accept-Encoding
> ```

---

## 完整實戰範例

```nginx
# /etc/nginx/nginx.conf
load_module modules/ngx_http_cache_turbo_module.so;
load_module modules/ngx_http_strip_filter_module.so;
load_module modules/ngx_http_brotli_filter_module.so;
load_module modules/ngx_http_brotli_static_module.so;
load_module modules/ngx_http_zstd_filter_module.so;
load_module modules/ngx_http_zstd_static_module.so;

http {
    # ═══ ★★★ 真實 IP ═══
    set_real_ip_from 10.10.20.0/24;
    real_ip_header X-Forwarded-For;

    # ═══ ★★★★ 快取 ═══
    cache_turbo_zone name=ct 512m;
    cache_turbo_redis "10.10.20.60:6379" keepalive=10;

    # ★★★★ 判斷是否為登入使用者
    map $http_cookie $is_logged_in {
        default              0;
        "~*laravel_session"  1;
        "~*remember_web_"    1;
    }
    map $request_method $not_cacheable_method {
        default  1;
        GET      0;
        HEAD     0;
    }

    # ═══ ★★★ 壓縮 ═══
    gzip on;
    gzip_vary on;
    gzip_static on;
    gzip_comp_level 5;
    gzip_min_length 1024;
    gzip_proxied any;
    gzip_types text/plain text/css text/xml text/javascript
               application/javascript application/json application/xml
               image/svg+xml;

    brotli on;
    brotli_static on;
    brotli_comp_level 5;
    brotli_min_length 1024;
    brotli_types text/plain text/css text/xml text/javascript
                 application/javascript application/json image/svg+xml;

    zstd on;
    zstd_static on;
    zstd_comp_level 6;
    zstd_min_length 1024;
    zstd_types text/plain text/css application/javascript application/json;

    # ═══ ★★★ 精簡 ═══
    strip on;
    strip_css on;
    strip_json on;
    strip_js on;                       # ★★★ 不開 aggressive
    strip_min_size 1k;
    strip_max_size 1m;

    # ═══ 日誌 ═══
    log_format perf '$remote_addr - [$time_local] "$request" $status $body_bytes_sent '
                    'cache=$cache_turbo_status enc=$http_accept_encoding '
                    'rt=$request_time urt=$upstream_response_time';

    upstream backend {
        server 127.0.0.1:8080;
        keepalive 64;
    }

    server {
        listen 443 ssl;
        http2 on;
        server_name app.example.gov.tw;
        access_log /var/log/nginx/perf.log perf;

        root /var/www/app/current/public;

        # ═══ ★★★★ 靜態資源：預先壓縮 + 長期快取 ═══
        location ~* \.(?:js|css|svg|woff2?|ttf|eot)$ {
            # ★★★★ 不需要 cache-turbo（★ 檔案本來就在磁碟）
            gzip_static on;
            brotli_static on;
            zstd_static on;
            expires 1y;
            add_header Cache-Control "public, immutable" always;
            add_header Vary "Accept-Encoding" always;
            access_log off;
        }

        # ═══ ★★ 圖片影片：不壓縮 ═══
        location ~* \.(?:jpg|jpeg|png|gif|webp|avif|mp4|webm|ico)$ {
            gzip off;
            brotli off;
            zstd off;
            strip off;
            expires 30d;
            add_header Cache-Control "public" always;
            access_log off;
        }

        # ═══ ★★★★ 動態頁面：cache-turbo ═══
        location / {
            cache_turbo ct;
            cache_turbo_valid 60s;
            cache_turbo_valid 301 302 308 1h;
            cache_turbo_valid 404 1m;                  # ★★ 負向快取

            cache_turbo_key $host$uri$cache_turbo_normalized_args;
            cache_turbo_normalize_strip utm_source utm_medium utm_campaign
                                        fbclid gclid "tmp_*";

            cache_turbo_stale_while_revalidate 4m;     # ★★★★ 使用者不用等
            cache_turbo_stale_if_error 24h;            # ★★★★ 上游掛了也能撐
            cache_turbo_lock_ttl 5s;                   # ★★★★ 防 dogpile

            # ★★★★ 登入使用者完全不碰快取
            cache_turbo_bypass   $is_logged_in $not_cacheable_method $http_authorization;
            cache_turbo_no_store $is_logged_in $not_cacheable_method $http_authorization;
            cache_turbo_cache_control honor;
            cache_turbo_auto_vary on;

            add_header X-Cache $cache_turbo_status always;

            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # ═══ ★★★★ API：不快取 HTML 快取，但壓縮 JSON ═══
        location /api/ {
            strip_json on;
            zstd on;
            brotli on;
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
        }

        # ═══ ★★★★ 後台：完全不快取不精簡 ═══
        location /admin/ {
            strip off;
            proxy_pass http://backend;
        }

        # ═══ ★★ 清除端點 ═══
        location /_cache-admin {
            cache_turbo_admin_path /_cache-admin;
            allow 127.0.0.1;
            allow 10.10.20.0/24;
            deny all;
            access_log off;
        }
    }
}
```

```bash
# ═══ ★★★★ 上線後的驗證 ═══
$ sudo tee /usr/local/bin/cache-verify >/dev/null <<'EOF'
#!/usr/bin/env bash
URL="${1:?用法: cache-verify <URL>}"
FAIL=0
echo "═══ 快取與壓縮驗證: $URL ═══"

# ★★★ 快取狀態
echo -e "\n【快取】"
for i in 1 2 3; do
    printf "  第 %d 次: " "$i"
    curl -sI "$URL" | grep -i '^x-cache' | tr -d '\r' | sed 's/^/  /'
done
#   ★★★★ 第 2、3 次應該是 HIT

# ★★★★ 壓縮
echo -e "\n【壓縮】"
for enc in identity gzip br zstd; do
    r=$(curl -sI -H "Accept-Encoding: $enc" "$URL")
    ce=$(echo "$r" | grep -i '^content-encoding' | awk '{print $2}' | tr -d '\r')
    cl=$(echo "$r" | grep -i '^content-length' | awk '{print $2}' | tr -d '\r')
    printf "  %-10s encoding=%-8s size=%s\n" "$enc" "${ce:-none}" "${cl:-?}"
done

# ★★★★ Vary
echo -e "\n【★★★★ Vary】"
V=$(curl -sI "$URL" | grep -i '^vary' | tr -d '\r')
if echo "$V" | grep -qi 'accept-encoding'; then
    echo "  ✓ $V"
else
    echo "  ★★★★ 缺少 Vary: Accept-Encoding！壓縮內容可能被錯誤快取"
    FAIL=$((FAIL+1))
fi

# ★★★★ 登入頁面不該被快取
echo -e "\n【★★★★ 個資外洩檢查】"
LOGGED=$(curl -sI "$URL" -H 'Cookie: laravel_session=test' | \
         grep -i '^x-cache' | awk '{print $2}' | tr -d '\r')
printf "  帶 session cookie: x-cache=%s  " "${LOGGED:-?}"
if [ "$LOGGED" = "BYPASS" ] || [ "$LOGGED" = "MISS" ]; then
    echo "✓"
else
    echo "★★★★ 登入請求命中快取！立刻檢查 bypass 設定"
    FAIL=$((FAIL+1))
fi

# ★★★ 回應時間
echo -e "\n【回應時間】"
for i in 1 2 3; do
    curl -sko /dev/null -w "  第 $i 次: ttfb=%{time_starttransfer}s total=%{time_total}s\n" "$URL"
done

echo ""
[ "$FAIL" -eq 0 ] && echo "★ 全部通過" || echo "★★★★ $FAIL 項有問題"
exit "$FAIL"
EOF
$ sudo chmod +x /usr/local/bin/cache-verify
$ cache-verify https://app.example.gov.tw/news
```

---

## ★★★★ 快取的三層關係

```
★★★★ 一個完整的架構中有三層快取，要搞清楚各自的角色：

  ┌────────────────────────────────────────────────────────┐
  │ ★★★ 瀏覽器快取（Cache-Control / expires）               │
  │   · 靜態資源：1 年 + immutable（★ 檔名有 hash）          │
  │   · HTML：no-cache 或很短的 TTL                         │
  └──────────────────────┬─────────────────────────────────┘
                         ▼
  ┌────────────────────────────────────────────────────────┐
  │ ★★★ CDN（如果有）                                       │
  │   · 邊緣節點，離使用者最近                               │
  │   · ★★★★ 要正確處理 Vary 與 Cookie                      │
  └──────────────────────┬─────────────────────────────────┘
                         ▼
  ┌────────────────────────────────────────────────────────┐
  │ ★★★★ cache-turbo（L1 記憶體）+ Redis（L2）              │
  │   · 次毫秒級，擋掉大部分的上游請求                        │
  │   · ★★★★ SWR + single-flight 是關鍵                     │
  └──────────────────────┬─────────────────────────────────┘
                         ▼
  ┌────────────────────────────────────────────────────────┐
  │ ★★ 應用程式快取（Redis / Memcached）                     │
  │   · 查詢結果、計算結果、session                          │
  └──────────────────────┬─────────────────────────────────┘
                         ▼
  ┌────────────────────────────────────────────────────────┐
  │ 資料庫                                                  │
  └────────────────────────────────────────────────────────┘

★★★★ 常見的錯誤：
  ① ★★★★ 每一層都設不同的 TTL → 清除時要清好幾個地方，容易漏
     → ★★★ 用檔名 hash（immutable）+ 短 TTL 的 HTML
  ② ★★★★ 上層快取了不該快取的內容 → 個資外洩
     → ★★★ 每一層都要有 bypass 條件
  ③ ★★★ Vary 處理不一致 → 壓縮內容錯給
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **★★★★ 未登入者看到別人的內容** | **快取了登入頁面** | **`cache_turbo_no_store $cookie_session`**；立刻停用快取 |
| **命中率很低** ★★★ | key 沒正規化／bypass 太寬 | `cache_turbo_normalize_strip`；檢查 bypass 條件 |
| **內容更新後還是舊的** ★★★ | TTL 太長／SWR 期間 | 縮短 `valid`；用清除端點 |
| **上游被打爆** ★★★★ | **沒有 single-flight** | **`cache_turbo_lock_ttl 5s`** |
| **記憶體用量暴增** ★★★ | zone 太大／內容太大 | 縮小 zone；用 proxy_cache 存大檔 |
| **★★★★ 頁面顯示亂碼** | **缺 `Vary: Accept-Encoding`** | `gzip_vary on`；`cache_turbo_auto_vary on` |
| **JS 壞掉** ★★★★ | **`strip_aggressive`** | **關掉**；在建置階段 minify |
| **壓縮沒生效** ★★★ | MIME type 不在清單／檔案太小 | 檢查 `*_types`；`*_min_length` |
| **CPU 飆高** ★★★ | 壓縮等級太高 | `comp_level 5`；用預先壓縮 |
| **圖片變大** ★★ | 對已壓縮的檔案再壓 | `location` 中 `gzip off; brotli off;` |
| **L2 Redis 連不上** ★★ | 密碼/網路 | `redis-cli ping`；檢查防火牆 |
| **清除端點 404** ★★ | 路徑設定 | `cache_turbo_admin_path` 與 location 要一致 |

### 排查

```bash
# 【1】★★★ 模組與設定
$ sudo nginx -T 2>/dev/null | grep -E 'load_module.*(cache_turbo|strip|brotli|zstd)'
$ sudo nginx -T 2>/dev/null | grep -E '^\s*(cache_turbo|strip|gzip|brotli|zstd)'

# 【2】★★★★ 快取狀態
$ curl -sI https://app.example.gov.tw/ | grep -i x-cache
$ for i in 1 2 3; do curl -sI URL | grep -i x-cache; done
#   ★★★ 第一次 MISS，之後應該是 HIT

# 【3】★★★★ 命中率
$ sudo grep -oP 'cache=\K\S+' /var/log/nginx/perf.log | sort | uniq -c | sort -rn

# 【4】★★★★ 個資外洩檢查（★ 最重要）
$ curl -s -c /tmp/ck https://app.example.gov.tw/login >/dev/null
$ curl -s -b /tmp/ck https://app.example.gov.tw/dashboard > /tmp/logged.html
$ curl -s https://app.example.gov.tw/dashboard > /tmp/anon.html
$ diff /tmp/logged.html /tmp/anon.html | head
#   ★★★★ 沒有差異 = 登入內容被快取了！立刻處理

# 【5】★★★ 壓縮
$ for e in gzip br zstd; do
    printf "%-6s " "$e"
    curl -sI -H "Accept-Encoding: $e" URL | grep -i content-encoding
  done
$ curl -sI URL | grep -i vary

# 【6】★★★ 記憶體用量
$ sudo nginx -T | grep cache_turbo_zone
$ ps -o pid,rss,cmd -C nginx | head
$ cat /proc/meminfo | grep -E 'Shmem|MemAvailable'

# 【7】★★ L2 Redis
$ redis-cli -h 10.10.20.60 -a '密碼' ping
$ redis-cli -h 10.10.20.60 -a '密碼' --scan --pattern 'ct*' | head
$ redis-cli -h 10.10.20.60 -a '密碼' INFO memory | grep used_memory_human

# 【8】★★★ strip 是否破壞內容
$ curl -s URL > /tmp/stripped.html
$ sudo sed -i 's/^\(\s*strip\s*\)on;/\1off;/' /etc/nginx/conf.d/strip.conf
$ sudo systemctl reload nginx
$ curl -s URL > /tmp/original.html
$ diff <(sed 's/[[:space:]]\+/ /g' /tmp/stripped.html) \
       <(sed 's/[[:space:]]\+/ /g' /tmp/original.html) | head
#   ★★★★ 除了空白之外有其他差異 = strip 改壞了內容
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★★
> ```
> ① ★★★★★ 快取個人化內容 = 個資外洩
>      → ★★★★ 這是最嚴重的快取風險
>      → cache_turbo_no_store + bypass 三層防護
>      → ★★★ 上線前一定要做「未登入者拿不拿得到登入內容」的測試
>
> ② ★★★★ Vary 處理不當 = 內容錯給
>      → 壓縮格式、語系、行動版/桌面版
>      → ★★★ gzip_vary on + cache_turbo_auto_vary on
>
> ③ ★★★ 清除端點要限制存取
>      → ★★★★ 開放的話攻擊者可以反覆清空快取 → 打爆上游
>
> ④ ★★★ L2 Redis 的安全
>      → ★★★★ 快取內容存在 Redis 裡 → 沒密碼 = 內容外洩
>      → 綁內網 + requirepass
>
> ⑤ ★★★ strip_aggressive 可能破壞功能
>      → ★★★★ JS 壞掉可能造成 XSS 防護失效或表單無法提交
>      → ★★★ 建置階段 minify 才是正解
> ```

```bash
# ★★★★★ 個資外洩的完整測試（★ 上線前必做）
$ sudo tee /usr/local/bin/cache-privacy-test >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★★★★ 測試快取有沒有洩漏個人化內容
BASE="${1:?用法: cache-privacy-test <base-url>}"
CK=$(mktemp); trap 'rm -f "$CK" /tmp/cpt-*' EXIT
FAIL=0

echo "═══ ★★★★★ 快取隱私測試 ═══"

# ★★★ 需要一組測試帳號
read -rp "  測試帳號: " USER
read -rsp "  密碼: " PASS; echo

# ★★★ 登入
curl -s -c "$CK" "$BASE/login" >/dev/null
TOKEN=$(awk '/XSRF-TOKEN/{print $7}' "$CK" | python3 -c \
        'import sys,urllib.parse;print(urllib.parse.unquote(sys.stdin.read().strip()))' 2>/dev/null)
curl -s -b "$CK" -c "$CK" -X POST "$BASE/login" \
    -H "X-XSRF-TOKEN: $TOKEN" -H 'Accept: application/json' \
    -d "email=$USER&password=$PASS" >/dev/null

# ★★★★ 測試每一個受保護的路徑
for path in / /dashboard /profile /orders /admin; do
    printf '  %-20s ' "$path"

    #   ① 登入狀態存取（★ 可能觸發快取儲存）
    curl -s -b "$CK" "$BASE$path" -o "/tmp/cpt-logged$$" 2>/dev/null
    LOGGED_SIZE=$(stat -c%s "/tmp/cpt-logged$$" 2>/dev/null || echo 0)

    #   ② ★★★★ 未登入存取同一個路徑
    sleep 1
    curl -s "$BASE$path" -o "/tmp/cpt-anon$$" 2>/dev/null
    ANON_SIZE=$(stat -c%s "/tmp/cpt-anon$$" 2>/dev/null || echo 0)

    #   ★★★★ 判斷
    if [ "$LOGGED_SIZE" -gt 0 ] && [ "$LOGGED_SIZE" -eq "$ANON_SIZE" ] && \
       cmp -s "/tmp/cpt-logged$$" "/tmp/cpt-anon$$"; then
        echo "★★★★★ 內容完全相同 → 可能洩漏！"
        FAIL=$((FAIL+1))
    elif grep -qiE "$USER|登出|logout|我的帳戶" "/tmp/cpt-anon$$" 2>/dev/null; then
        echo "★★★★★ 未登入頁面含登入資訊 → 【確定洩漏】"
        FAIL=$((FAIL+1))
    else
        XC=$(curl -sI "$BASE$path" | grep -i '^x-cache' | awk '{print $2}' | tr -d '\r')
        echo "✓ (x-cache=${XC:-none})"
    fi
    rm -f "/tmp/cpt-logged$$" "/tmp/cpt-anon$$"
done

echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "★ 沒有發現洩漏"
else
    echo "★★★★★ $FAIL 個路徑可能洩漏個資 —— 【立刻停用快取並檢查設定】"
    echo "  location / { cache_turbo off; }"
fi
exit "$FAIL"
EOF
$ sudo chmod +x /usr/local/bin/cache-privacy-test
$ cache-privacy-test https://app.example.gov.tw

# ★★★ 清除端點的保護
$ sudo nginx -T | grep -A5 cache_turbo_admin_path
#   ★★★★ 一定要有 deny all
$ curl -sI https://app.example.gov.tw/_cache-admin
HTTP/2 403                                # ★★★ 從外部應該被擋

# ★★★ Redis 的安全
$ sudo grep -E '^(bind|requirepass|protected-mode)' /etc/redis/redis.conf
bind 10.10.20.60 127.0.0.1
requirepass 很長的隨機密碼
protected-mode yes
$ sudo ss -tlnp | grep :6379
LISTEN 0 511 10.10.20.60:6379             # ★★★ 不是 0.0.0.0

# ★★★★ 快取中有沒有敏感內容
$ redis-cli -h 10.10.20.60 -a '密碼' --scan --pattern 'ct*' | head -20 | \
  while read -r k; do
    redis-cli -h 10.10.20.60 -a '密碼' GET "$k" 2>/dev/null | \
      grep -qiE 'password|session|token|身分證|信用卡' && echo "★★★★ $k 含敏感內容"
  done
```

---

## 速查表

### ★★★★ cache-turbo

```nginx
cache_turbo_zone name=ct 256m;                    # http
location / {
    cache_turbo ct;
    cache_turbo_valid 60s;
    cache_turbo_valid 404 1m;                     # ★★ 負向快取
    cache_turbo_key $host$uri$cache_turbo_normalized_args;
    cache_turbo_normalize_strip utm_source fbclid gclid "tmp_*";
    cache_turbo_stale_while_revalidate 4m;        # ★★★★ 使用者不用等
    cache_turbo_stale_if_error 24h;               # ★★★★ 上游掛了也能撐
    cache_turbo_lock_ttl 5s;                      # ★★★★ 防 dogpile
    cache_turbo_bypass   $is_logged_in;           # ★★★★ 三層防護
    cache_turbo_no_store $is_logged_in;
    cache_turbo_backend wordpress;                # ★★★ CMS 自動分類
}
```

```
狀態：HIT / STALE / STALE-IF-ERROR / MISS / BYPASS
變數：$cache_turbo_status / $cache_turbo_hits / $cache_turbo_lock_waits
```

### ★★★★ SWR + single-flight

```
SWR：快取過期 → ★★★ 立刻給舊的 + 背景更新 → 使用者不用等
single-flight：1000 個並行 MISS → ★★★★ 上游只收到 1 個
兩者合起來：上游壓力 1/1000，使用者延遲 0
```

### ★★★★★ 個資外洩防護

```nginx
map $http_cookie $is_logged_in {
    default              0;
    "~*laravel_session"  1;
}
map $request_method $not_cacheable { default 1; GET 0; HEAD 0; }

cache_turbo_bypass   $is_logged_in $not_cacheable $http_authorization;
cache_turbo_no_store $is_logged_in $not_cacheable $http_authorization;

★★★★★ 上線前必測：未登入者拿不拿得到登入後的內容？
  cache-privacy-test https://app.example.gov.tw
```

### ★★★ strip-filter

```nginx
strip on; strip_css on; strip_json on; strip_js on;
strip_min_size 1k; strip_max_size 1m;
★★★★ strip_aggressive off（★ JS 預設 byte-identical，開了有風險）
★★★ 保護區：<pre> <textarea> <script> <style> <title> CDATA 字串字面值
★★★ 真正有價值的是 strip_json（API）
```

### ★★★ 壓縮

```nginx
gzip on; gzip_vary on; gzip_static on; gzip_comp_level 5;
brotli on; brotli_static on; brotli_comp_level 5;
zstd on; zstd_static on; zstd_comp_level 6;

★★★★ 靜態資源【建置時預先壓縮】（gzip -9 / brotli -q 11）
★★★★ 已壓縮的檔案關掉：jpg png mp4 zip woff2
★★★★ Vary: Accept-Encoding 一定要有（★ 否則內容錯給 → 亂碼）
```

### 排錯

```bash
curl -sI URL | grep -iE 'x-cache|vary|content-encoding'
sudo grep -oP 'cache=\K\S+' perf.log | sort | uniq -c    # ★★★ 命中率
diff <(curl -s -b ck URL) <(curl -s URL)                 # ★★★★★ 個資外洩
for e in gzip br zstd; do curl -sI -H "Accept-Encoding: $e" URL | grep -i content-encoding; done
cache-verify URL
```

---

## 練習題

> [!question]- 練習 1：基本快取 ★★★
> 1. **設定 `cache_turbo_zone` 與最小的 `cache_turbo`**
> 2. **連續 `curl -sI` 三次** → `x-cache` 分別是什麼？
> 3. **等 TTL 過期再測** → 呢？
> 4. **加上 `cache_turbo_stale_while_revalidate`** → 過期後第一次的回應時間？
> 5. **停掉上游，測 `stale_if_error`** → 拿到什麼？
> 6. **比較有無 SWR 的 P95 回應時間**

> [!question]- 練習 2：★★★★★ 個資外洩測試
> 1. **不設任何 bypass，直接快取整個站台**
> 2. **登入後訪問 `/dashboard`**
> 3. **★★★★ 未登入用另一個瀏覽器訪問同一個 URL** → 看到什麼？
> 4. **這是什麼等級的資安事件？**
> 5. **加上三層防護（bypass / no_store / map）再測**
> 6. **執行 `cache-privacy-test`**

> [!question]- 練習 3：single-flight ★★★★
> 1. **不設 `cache_turbo_lock_ttl`**
> 2. **用 `ab -n 1000 -c 200` 在快取剛過期時壓測**
> 3. **看上游的 access log** → 收到幾個請求？
> 4. **設定 `cache_turbo_lock_ttl 5s` 再測** → 呢？
> 5. **`$cache_turbo_lock_waits` 是多少？**
> 6. **這在真實流量下代表什麼？**

> [!question]- 練習 4：壓縮 ★★★
> 1. **對同一個 JS 檔案測 identity/gzip/br/zstd 的大小**
> 2. **`curl -sI | grep -i vary`** → 有 `Accept-Encoding` 嗎？
> 3. **拿掉 `gzip_vary on` 再測** → 危險在哪？
> 4. **建置時預先壓縮並開 `*_static on`**
> 5. **比較「即時壓縮」和「預先壓縮」的 CPU**（`perf stat`）
> 6. **對 jpg 開啟壓縮** → 檔案變大還是變小？

> [!question]- 練習 5：strip ★★★
> 1. **開啟 `strip on`，比較 HTML 大小**
> 2. **加上 `--compressed` 再比較** → 差異還明顯嗎？
> 3. **檢查 `<pre>` 和 `<textarea>` 的內容有沒有被動到**
> 4. **開啟 `strip_aggressive`，測試所有 JS 功能**
> 5. **有壞掉的嗎？**
> 6. **結論：strip 最有價值的用途是什麼？**

---

## 小測驗

Q1. **cache-turbo 和 nginx 內建 `proxy_cache` 的五個差異**？各適合什麼場景？

Q2. **stale-while-revalidate 解決了什麼問題**？

Q3. **single-flight（`cache_turbo_lock_ttl`）防的是什麼**？沒有它會怎樣？

Q4. **`cache_turbo_stale_if_error` 的價值**？

Q5. **★★★★★ 快取最嚴重的風險是什麼**？三層防護？

Q6. **`cache_turbo_normalize_strip` 解決什麼問題**？

Q7. **為什麼 `Vary: Accept-Encoding` 是必要的**？沒有會怎樣？

Q8. **`strip_aggressive` 為什麼預設是關的**？

Q9. **gzip / Brotli / Zstandard 該怎麼選**？靜態資源的最佳做法？

Q10. **一個完整架構有哪幾層快取**？兩個常見的錯誤？

> [!question]- 測驗答案
> **Q1.** ①**儲存位置** —— `proxy_cache` 存**磁碟**（靠 page cache 加速），
> cache-turbo 存**共享記憶體**；
> ②**★★★★ 讀取延遲** —— proxy_cache 毫秒級（有磁碟 I/O），
> cache-turbo **次毫秒級**；
> ③**★★★★ 多台共享** —— proxy_cache 各台獨立，
> cache-turbo **可用 L2 Redis 讓整個叢集共享**（重啟後還能暖啟動）；
> ④**★★★★ CMS 感知** —— proxy_cache 要自己寫 bypass 規則，
> cache-turbo 有 **30+ 種 CMS 預設**（`cache_turbo_backend wordpress`）；
> ⑤**容量** —— proxy_cache 受磁碟限制（可以很大），
> cache-turbo **受記憶體限制**。
> **適合場景**：
> **熱門內容少、要求極低延遲 → cache-turbo**；
> **內容量大（大量圖片影片）→ proxy_cache**；
> **★★★ 兩者可以並用**：cache-turbo 當 L1，proxy_cache 當 L2。
>
> **Q2.** **★★★★ 解決「快取過期時，有一個使用者必須等上游回應」的問題**。
> **沒有 SWR**：快取一過期，下一個請求就是 MISS，
> 那個使用者要**完整承受上游的延遲**（可能是幾百毫秒到幾秒）。
> **★★★★ 有 SWR**：快取過期後，
> **立刻把過期的內容給使用者（0ms）**，
> **同時在背景**向上游取新的內容更新快取。
> ```nginx
> cache_turbo_stale_while_revalidate 4m;    # ★★★ 過期後 4 分鐘仍可供應舊的
> ```
> **效果：使用者永遠不會等上游**。
> 代價是可能拿到最多 4 分鐘前的內容 ——
> 對公告、新聞、商品列表這類內容完全可以接受。
> 回應標頭會是 `X-Cache: STALE`。
>
> **Q3.** **★★★★ 防的是 cache stampede（dogpile / 快取雪崩）**。
> **沒有 single-flight 時**：
> 一個熱門頁面的快取過期的**那一瞬間**，
> 所有正在進行的並行請求（可能是 1000 個）**全部變成 MISS**，
> **同時打向上游** —— 上游瞬間收到 1000 個相同的請求，
> **資料庫被打爆、應用程式的 worker 全滿、回應時間暴增**，
> 更糟的是這會**引發連鎖反應**（其他頁面也開始逾時）。
> **★★★★ 有鎖時**：
> 第一個 MISS 拿到鎖去問上游，**其他 999 個等鎖或直接拿過期的內容**，
> **上游只收到 1 個請求**。
> ```nginx
> cache_turbo_lock_ttl 5s;
> ```
> **配合 SWR 效果最好**：999 個使用者拿到過期內容（0ms 延遲），
> 1 個背景請求去更新 —— **上游壓力降到 1/1000，使用者延遲為 0**。
> 監控指標：`$cache_turbo_lock_waits`。
>
> **Q4.** **★★★★ 上游整個掛掉時，使用者仍然看得到內容**。
> ```nginx
> cache_turbo_stale_if_error 24h;
> ```
> **沒有它**：上游掛掉 → 使用者看到 **502 Bad Gateway**。
> **有它**：上游掛掉 → 使用者看到**最多 24 小時前的快取內容**，
> 回應標頭是 `X-Cache: STALE-IF-ERROR`。
> **★★★ 對「內容不常變」的網站價值極高** ——
> 機關的公告網站、產品型錄、文件站，
> 資料庫維護或應用程式部署失敗時，**使用者完全感覺不到**。
> **這是最被低估的功能之一** ——
> 它把「上游可用性」和「網站可用性」解耦了。
> 注意要搭配監控：使用者看不到問題不代表沒問題，
> 你還是要知道上游掛了（監控 `X-Cache: STALE-IF-ERROR` 的比率）。
>
> **Q5.** **★★★★★ 把「個人化的內容」快取起來給別人看 = 個資外洩**。
> ```
> 使用者 A 登入 → 看到「歡迎，張三」的頁面 → ★★★★ 被快取
> 使用者 B（未登入）訪問同一個 URL → ★★★★★ 看到「歡迎，張三」！
> ```
> 洩漏的可能包括姓名、身分證號、訂單、病歷、甚至 CSRF token 或 session。
> **★★★ 三層防護**：
> ①**`cache_turbo_backend <cms>`** —— 已知 CMS 自動跳過動態頁面；
> ②**★★★★ `cache_turbo_no_store $is_logged_in`** ——
> 有 session cookie 的**回應絕對不儲存**；
> ③**★★★ `cache_turbo_bypass $is_logged_in`** ——
> 有 session cookie 的**請求不查快取**。
> **★★★★★ 上線前一定要實測**：
> 登入後訪問 `/dashboard`，然後**用未登入的 client 訪問同一個 URL**，
> 看得到登入內容就是**確定的資安事件，立刻停用快取**。
>
> **Q6.** **★★★ 解決「追蹤參數讓快取命中率暴跌」的問題**。
> cache-turbo 預設的 key 是 **Host + 未解析的 URI（完全不正規化）** ——
> `/news?utm_source=facebook` 和 `/news?utm_source=twitter`
> 是**兩個完全不同的快取項目**，
> 而社群分享、廣告、電子報產生的 `utm_*`、`fbclid`、`gclid`
> 會讓**同一個頁面產生無數個快取副本**：
> 命中率趨近於零，記憶體被無用的副本佔滿。
> ```nginx
> cache_turbo_key $host$uri$cache_turbo_normalized_args;
> cache_turbo_normalize_strip utm_source utm_medium utm_campaign
>                             fbclid gclid msclkid "tmp_*";
> ```
> **支援萬用字元**（`"tmp_*"`）。
> 正規化後，所有帶不同 utm 的請求**共用同一份快取**。
> 驗證：用不同的 utm 參數請求，第二次應該就 `x-cache: HIT`。
>
> **Q7.** 因為 **同一個 URL 會依客戶端支援的壓縮格式回傳不同的位元組**。
> **沒有 `Vary: Accept-Encoding` 時**：
> ```
> 使用者 A（支援 br）→ 快取儲存了 Brotli 壓縮的版本
> 使用者 B（只支援 gzip）→ ★★★★ 拿到 br 的內容但不會解壓
> → ★★★★ 頁面顯示成亂碼或完全打不開
> ```
> 這個問題會**在 CDN 或反向代理層放大** —— 一個節點快取錯了，
> 影響所有經過該節點的使用者，而且很難重現（要剛好用對的 client 才看得到）。
> **三個地方要確認**：
> ①`gzip_vary on;`（brotli/zstd 模組通常自動加）；
> ②`cache_turbo_auto_vary on;`（預設就是 on）；
> ③**CDN 也要正確處理 Vary**。
> **驗證**：`curl -sI URL | grep -i vary` 一定要看到 `vary: Accept-Encoding`。
>
> **Q8.** 因為 **JavaScript 的 ASI（Automatic Semicolon Insertion）讓換行有語意**。
> ```javascript
> return
> { a: 1 }
> ```
> 這段程式碼因為 ASI，**實際上等於 `return undefined;`** ——
> 移除換行會變成 `return { a: 1 }`，**完全不同的行為**。
> 類似的陷阱還有 `++`/`--`、`break`/`continue`、模板字串、正規表示式字面值。
> **所以 strip-filter 預設對 JS 是 byte-identical（完全不動）**，
> 只有 `strip_aggressive on` 才會移除註解與空白。
> 模組宣稱會保護 ASI 關鍵的換行和字串/模板/regex 字面值，
> **但仍有風險** —— JS 壞掉可能造成表單無法提交、
> 甚至讓前端的 XSS 防護失效。
> **★★★ 正解是在建置階段用 Vite/webpack/esbuild minify** ——
> 那些工具有完整的 AST 解析，安全得多。
> **strip-filter 最有價值的其實是 `strip_json`**（API 回應）。
>
> **Q9.** **gzip** —— **一定要開，當保底**（100% 瀏覽器支援）。
> **Brotli** —— **壓縮率最好（比 gzip 小約 20%）**，
> 瀏覽器支援 96%+（HTTPS 下），**動態內容用等級 4~5**（平衡 CPU）。
> **Zstandard** —— **壓縮和解壓速度最快**，
> 但**瀏覽器支援還有限**（主要是 Chrome 系），可以開但不能只靠它。
> **★★★★ 靜態資源的最佳做法：建置時預先壓縮**：
> ```bash
> gzip -9 -k -f "$f"        # ★ 最高等級，反正只壓一次
> brotli -q 11 -f "$f"
> zstd -19 -q -f "$f"
> ```
> 搭配 `gzip_static on; brotli_static on; zstd_static on;` ——
> **nginx 直接送預壓縮的檔案，執行期的 CPU 成本是零**，
> 而且可以用最高的壓縮等級（即時壓縮用等級 11 會拖垮 CPU）。
> **★★★★ 已壓縮的檔案要關掉壓縮**：jpg、png、webp、mp4、zip、woff2 ——
> 再壓一次只會**變大**還浪費 CPU。
>
> **Q10.** **四層**：
> ①**瀏覽器快取**（`Cache-Control`/`expires`）——
> 靜態資源 1 年 + `immutable`（檔名有 hash），HTML 用 `no-cache` 或短 TTL；
> ②**CDN**（如果有）—— 邊緣節點，離使用者最近；
> ③**★★★★ cache-turbo（L1 記憶體）+ Redis（L2）** ——
> 擋掉大部分的上游請求；
> ④**應用程式快取**（Redis/Memcached）—— 查詢結果、計算結果。
> **兩個常見的錯誤**：
> ①**★★★★ 每一層設不同的 TTL** ——
> 內容更新時要清好幾個地方，很容易漏掉一層，
> 使用者看到不一致的內容。**解法**：靜態資源用**檔名 hash + immutable**
> （永遠不用清），HTML 用**短 TTL**；
> ②**★★★★★ 上層快取了不該快取的內容** —— 個資外洩。
> **每一層都要有 bypass 條件**，而且**每一層都要單獨測試**
> （CDN 的 bypass 規則和 nginx 的是分開設定的）。

---

## 延伸閱讀

- [[05-Nginx-靜態資源與快取]] — **★★★ `proxy_cache` 的基礎**
- [[08-Nginx-效能調校]] — gzip、HTTP/2、連線調校
- [[07-Nuxt-Laravel-SSR完整部署實戰]] — **★★★★ SSR 的快取污染防護**
- [[03-Nuxt-Nginx反向代理與快取]] — 微快取的做法
- [[04-Redis快取入門]] — 應用層快取
- [[08-MyGuard實戰組合]] — 完整的實戰配置
