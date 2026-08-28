---
title: "Nginx 安全設定"
desc: "安全標頭、隱藏版本、路徑與方法限制、防盜連、IP 封鎖與上線前檢查清單"
aliases: [安全標頭, CSP, HSTS, 防盜連, server_tokens, 加固, hardening]
tags: [群組/軟體與開發工具, 服務/nginx, 主題/安全]
category: Nginx
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[03-Nginx-location與rewrite]]"]
updated: 2026-08-28
---

# Nginx 安全設定

> [!abstract] 這篇你會學到
> - 設定**完整的安全標頭**（並避開 `add_header` 的繼承陷阱）
> - 從零建立 **CSP（內容安全政策）**而不弄壞網站
> - **隱藏版本與指紋**、限制 HTTP 方法與路徑
> - 防止 **`.env` / `.git` 外洩**與**上傳目錄執行 PHP**
> - 設定**防盜連、IP 封鎖、地理封鎖**
> - 一份可直接使用的**上線前安全檢查清單與驗證腳本**

## 前置知識

- [[03-Nginx-location與rewrite]] — location 比對與 try_files
- [[06-Nginx-HTTPS與Certbot]] — TLS 設定與 HSTS

---

## 第一原則：檔案不在 web root 內

> [!danger] 最嚴重也最常見的三個 Nginx 安全問題
> ```
> ①  root 指向專案根目錄而非 public/
>     → .env（★ 資料庫密碼、API 金鑰）、composer.json、vendor/、
>       storage/logs/laravel.log 全部可以被下載
>
> ②  上傳目錄可以執行 PHP
>     → 上傳 shell.php → 取得 web shell → 【整台機器淪陷】
>
> ③  .git 目錄可以存取
>     → 攻擊者用 git-dumper 把【整份原始碼與提交歷史】下載下來
>       → 歷史中的舊 .env、金鑰、內部 IP 全部外洩
> ```

```bash
# ★ 三十秒自我檢查
$ for p in /.env /.git/config /.git/HEAD /composer.json /package.json \
           /storage/logs/laravel.log /vendor/autoload.php /.htaccess \
           /docker-compose.yml /Dockerfile /artisan /phpinfo.php; do
    code=$(curl -sk -o /dev/null -w '%{http_code}' -m 5 "https://你的網站$p")
    [ "$code" = "200" ] && echo "⚠⚠⚠ $p 【可以下載】" || echo "  ✓ $p → $code"
  done
```

### 正確的目錄結構

```
/var/www/myproject/
├── releases/
│   └── 20260828-100000/
│       ├── app/              ← 程式碼（★ web root 之外）
│       ├── vendor/           ← 套件（★ web root 之外）
│       ├── storage/          ← 日誌、快取（★ web root 之外）
│       ├── .env              ← ★★ 絕對在 web root 之外
│       └── public/           ← ★★★ 【只有這裡】對外開放
│           ├── index.php
│           ├── assets/
│           └── uploads/      ← 上傳（★ 必須禁止執行）
├── shared/
│   ├── .env                  ← 實際的設定檔
│   └── storage/
└── current -> releases/20260828-100000
```

```nginx
root /var/www/myproject/current/public;      # ★★ 一定要指到 public
```

---

## 完整的安全標頭

```nginx
# ═══════════ /etc/nginx/snippets/security-headers.conf ═══════════

# ── 防點擊劫持 ──
add_header X-Frame-Options "SAMEORIGIN" always;

# ── 防 MIME 類型嗅探 ──
add_header X-Content-Type-Options "nosniff" always;

# ── 控制 Referer 洩漏 ──
add_header Referrer-Policy "strict-origin-when-cross-origin" always;

# ── 限制瀏覽器 API ──
add_header Permissions-Policy "geolocation=(), microphone=(), camera=(), payment=(), usb=(), magnetometer=(), gyroscope=()" always;

# ── 跨來源隔離 ──
add_header Cross-Origin-Opener-Policy   "same-origin" always;
add_header Cross-Origin-Resource-Policy "same-origin" always;

# ── HSTS（★ 見 06 篇的漸進導入）──
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

# ── ★ 移除會洩漏技術棧的標頭 ──
proxy_hide_header X-Powered-By;
proxy_hide_header Server;
proxy_hide_header X-AspNet-Version;
proxy_hide_header X-AspNetMvc-Version;
proxy_hide_header X-Generator;
proxy_hide_header X-Drupal-Cache;
fastcgi_hide_header X-Powered-By;

# ── CSP（★ 見下方，必須依網站客製）──
# add_header Content-Security-Policy "..." always;
```

| 標頭 | 防護 | 建議值 |
| --- | --- | --- |
| **`X-Frame-Options`** | 點擊劫持 | `SAMEORIGIN`（或用 CSP 的 `frame-ancestors`） |
| **`X-Content-Type-Options`** | MIME 嗅探 | `nosniff` |
| **`Referrer-Policy`** | Referer 洩漏內部路徑 | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | 限制瀏覽器 API | 明確關閉不需要的 |
| **`Strict-Transport-Security`** | SSL Stripping | `max-age=31536000`（**漸進導入**） |
| **`Content-Security-Policy`** | **XSS（最強的防護）** | **必須客製** |
| `Cross-Origin-Opener-Policy` | 跨視窗攻擊 | `same-origin` |

> [!danger] `always` 與 `add_header` 繼承陷阱（★ 再強調一次）
> ```nginx
> # ① 一定要加 always，否則 4xx/5xx 沒有防護
> add_header X-Frame-Options "SAMEORIGIN" always;
>
> # ② ★★ add_header 是「陣列型指令」：內層【完全覆蓋】外層
> #    → 每個有 add_header 的 location 都要 include 一次
> server {
>     include snippets/security-headers.conf;
>
>     location /api/ {
>         include snippets/security-headers.conf;      # ★ 【必須】再 include
>         add_header Access-Control-Allow-Origin "https://app.example.gov.tw" always;
>     }
> }
> ```
>
> **驗證每一個 location**：
> ```bash
> $ for p in / /api/health /assets/app.css /admin /nonexistent; do
>     n=$(curl -skI "https://網站$p" | grep -icE 'x-frame|x-content-type|referrer-policy')
>     printf '  %-25s %d 個安全標頭 %s\n' "$p" "$n" \
>       "$([ "$n" -ge 3 ] && echo ✓ || echo '⚠ 被覆蓋了')"
>   done
> ```
> **注意最後一個 `/nonexistent`（404 頁面）** —— 沒加 `always` 就會是 0。

### CSP：最強但最難的一個

> [!warning] CSP 設錯會讓網站完全壞掉
> **絕對不要直接複製別人的 CSP。** 正確流程是：
> **①先用 Report-Only 觀察 → ②依報告調整 → ③才啟用強制模式**

```nginx
# ═══ 【階段一】只觀察，不阻擋（★ 至少跑一週）═══
add_header Content-Security-Policy-Report-Only
    "default-src 'self'; report-uri /csp-report" always;

location = /csp-report {
    access_log /var/log/nginx/csp-report.log json;
    return 204;
}
```

```bash
# 收集一週後，看看違規了哪些來源
$ sudo jq -r '.["csp-report"]["blocked-uri"]' /var/log/nginx/csp-report.log 2>/dev/null | \
    sort | uniq -c | sort -rn | head -30
```

```nginx
# ═══ 【階段二】依報告放行必要的來源 ═══
add_header Content-Security-Policy-Report-Only
    "default-src 'self';
     script-src  'self' https://cdn.jsdelivr.net;
     style-src   'self' 'unsafe-inline' https://fonts.googleapis.com;
     font-src    'self' https://fonts.gstatic.com data:;
     img-src     'self' data: https:;
     connect-src 'self' https://api.example.gov.tw;
     frame-ancestors 'self';
     base-uri 'self';
     form-action 'self';
     report-uri /csp-report" always;
```

```nginx
# ═══ 【階段三】確認沒有違規後，改成強制 ═══
add_header Content-Security-Policy
    "default-src 'self';
     script-src  'self' https://cdn.jsdelivr.net;
     style-src   'self' 'unsafe-inline' https://fonts.googleapis.com;
     font-src    'self' https://fonts.gstatic.com data:;
     img-src     'self' data: https:;
     connect-src 'self' https://api.example.gov.tw;
     object-src  'none';
     frame-ancestors 'self';
     base-uri 'self';
     form-action 'self';
     upgrade-insecure-requests" always;
```

| CSP 指令 | 控制 |
| --- | --- |
| `default-src` | 所有資源的預設來源 |
| **`script-src`** | **JS 來源（★ 防 XSS 的核心）** |
| `style-src` | CSS 來源 |
| `img-src` / `font-src` | 圖片 / 字型 |
| `connect-src` | fetch / XHR / WebSocket 的目標 |
| **`object-src 'none'`** | **禁止 Flash / 外掛（★ 一定要設）** |
| **`frame-ancestors`** | **誰可以嵌入本站**（取代 X-Frame-Options） |
| `base-uri 'self'` | 防止 `<base>` 標籤劫持 |
| `form-action 'self'` | 表單只能提交到本站 |
| `upgrade-insecure-requests` | 自動把 http 資源升級成 https |

> [!danger] `'unsafe-inline'` 與 `'unsafe-eval'` 會讓 CSP 幾乎失效
> ```nginx
> # ❌ 這樣寫 CSP 對 XSS 幾乎沒有防護力
> script-src 'self' 'unsafe-inline' 'unsafe-eval';
> ```
> **`'unsafe-inline'` 允許 `<script>alert(1)</script>` 這種內聯腳本
> —— 而這正是 XSS 攻擊的主要形式。**
>
> **正確做法是用 nonce**：
> ```nginx
> # Nginx 產生隨機 nonce（需要 ngx_http_sub_module 或在應用層產生）
> set $csp_nonce $request_id;         # ★ $request_id 是每個請求唯一的
> add_header Content-Security-Policy
>     "script-src 'self' 'nonce-$csp_nonce'; object-src 'none'" always;
> ```
> ```php
> // 應用層在每個 <script> 加上 nonce（Laravel 用中介層產生）
> <script nonce="<?= $nonce ?>">...</script>
> ```
> **`style-src` 的 `'unsafe-inline'` 風險較低**（多數框架難以避免），
> 但 **`script-src` 絕對要避免**。

---

## 隱藏指紋

```nginx
http {
    server_tokens off;                  # ★ 隱藏版本號
}
```

```bash
# 前後對照
$ curl -sI https://網站/ | grep -i '^server'
server: nginx/1.27.3          # ❌ 版本號 → 攻擊者可以查對應的 CVE
server: nginx                 # ✓ server_tokens off
```

> [!tip] 完全隱藏 `Server` 標頭需要模組
> `server_tokens off` 只移除版本號，仍會顯示 `nginx`。
> **完全移除需要 `headers-more` 模組**：
> ```nginx
> load_module modules/ngx_http_headers_more_filter_module.so;
> more_clear_headers 'Server';
> # 或偽裝
> more_set_headers 'Server: WebServer';
> ```
> ```bash
> $ sudo apt install -y libnginx-mod-http-headers-more-filter
> ```
> **不過這只是「安全模糊化」**，
> 有經驗的攻擊者仍可從**錯誤頁格式、標頭順序、TLS 指紋**判斷出是 Nginx。
> **不要因為隱藏了指紋就以為安全** —— 該打的補丁還是要打。

```nginx
# ★ 自訂錯誤頁（預設錯誤頁也會洩漏是 Nginx）
error_page 400 401 402 403 404 405 /errors/4xx.html;
error_page 500 501 502 503 504     /errors/5xx.html;

location ^~ /errors/ {
    internal;
    root /var/www/error-pages;
}
```

---

## 拒絕敏感路徑

```nginx
# ═══════════ /etc/nginx/snippets/deny-hidden.conf ═══════════

# ── ★ 隱藏檔（.env、.git、.htaccess…）但放行 .well-known ──
location ~ /\.(?!well-known) {
    deny all;
    access_log off;
    log_not_found off;
    return 404;
}

# ── ★ 敏感副檔名 ──
location ~* \.(?:env|log|sql|sqlite|sqlite3|db|bak|backup|old|orig|save|swp|swo|tmp|dist|inc|conf|ini|yml|yaml|toml|lock|sh|bash|pem|key|crt|p12|pfx)$ {
    deny all;
    access_log off;
    return 404;
}

# ── ★ 專案設定與腳本檔 ──
location ~* /(?:composer\.(?:json|lock)|package(?:-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|artisan|Makefile|Dockerfile|docker-compose\.ya?ml|webpack\.config\.js|vite\.config\.js|\.editorconfig|\.eslintrc.*|phpunit\.xml|README\.md|CHANGELOG\.md|LICENSE)$ {
    deny all;
    access_log off;
    return 404;
}

# ── ★ 常見的敏感目錄 ──
location ~* ^/(?:vendor|node_modules|storage|bootstrap/cache|tests|\.github|\.vscode|\.idea)/ {
    deny all;
    access_log off;
    return 404;
}

# ── ★ 常見的攻擊路徑（減少日誌雜訊）──
location ~* ^/(?:wp-admin|wp-login|wp-content|wp-includes|xmlrpc\.php|phpmyadmin|pma|adminer|\.env\.|config\.php\.|shell|c99|r57)/ {
    deny all;
    access_log off;
    return 444;                # ★ 直接關閉連線
}

# ── 備份檔命名慣例 ──
location ~* \.(?:php|inc|js|css|html)~$   { deny all; return 404; }
location ~* \.(?:php|inc)\.(?:txt|bak|old)$ { deny all; return 404; }
```

### 上傳目錄禁止執行 ★★★

```nginx
# ★ 用 ^~ 確保優先於全域的 location ~ \.php$
location ^~ /uploads/ {
    location ~* \.(?:php|phtml|phar|php\d?|pl|py|cgi|asp|aspx|jsp|sh)$ {
        deny all;
        access_log /var/log/nginx/upload-exec-attempt.log;   # ★ 記錄攻擊嘗試
        return 404;
    }
}

location ^~ /storage/ {
    location ~* \.(?:php|phtml|phar|php\d?)$ { deny all; return 404; }
}

location ^~ /media/ {
    location ~* \.(?:php|phtml|phar|php\d?)$ { deny all; return 404; }
}
```

> [!danger] 三道防線缺一不可
> ```nginx
> # 【防線 1】PHP 處理器要求檔案真的存在（防 PathInfo 攻擊）
> location ~ \.php$ {
>     try_files $uri =404;               # ★★
>     fastcgi_pass ...;
> }
> ```
> ```ini
> ; 【防線 2】php.ini
> cgi.fix_pathinfo = 0
> ; 順便：限制 PHP 只能讀取這些目錄
> open_basedir = /var/www/myproject/current:/tmp
> ; 停用危險函式
> disable_functions = exec,passthru,shell_exec,system,proc_open,popen,pcntl_exec
> ```
> ```nginx
> # 【防線 3】上傳目錄明確禁止（如上）
> ```
>
> **更根本的做法**：
> ①**上傳的檔案不要放在 web root 內**，用 `internal` + `X-Accel-Redirect` 提供下載
> （見 [[03-Nginx-location與rewrite]]）；
> ②**放在獨立的網域**（該網域完全沒有 PHP 處理器）；
> ③**上傳時重新命名並驗證真實的檔案類型**（用 magic bytes，不信任副檔名與 MIME）。

---

## 限制方法與請求

```nginx
# ═══ 只允許需要的 HTTP 方法 ═══
if ($request_method !~ ^(GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)$) {
    return 405;
}
# ★ if + return 是安全的用法

# ═══ 純靜態站台可以更嚴格 ═══
location ~* \.(?:js|css|png|jpg|woff2)$ {
    limit_except GET HEAD { deny all; }
}

# ═══ 阻擋惡意 User-Agent ═══
map $http_user_agent $bad_ua {
    default 0;
    ""                                          1;    # 空的 UA
    ~*(nikto|sqlmap|nmap|masscan|zgrab|nessus|acunetix|w3af|havij)  1;
    ~*(libwww-perl|python-requests/0|curl/7\.(1|2)[0-9]\.)          1;
    ~*(semrush|ahrefs|mj12bot|dotbot|petalbot)  1;    # 吃頻寬的 SEO 爬蟲
}

# ═══ 阻擋沒有 Host 標頭的請求 ═══
map $http_host $bad_host {
    default 0;
    ""      1;
}

server {
    if ($bad_ua)   { return 444; }
    if ($bad_host) { return 444; }

    # ═══ 阻擋 Referer 中的垃圾（referer spam）═══
    valid_referers none blocked server_names
                   *.example.gov.tw
                   ~\.google\. ~\.bing\. ~\.yahoo\.;
    # ...
}
```

> [!warning] 阻擋 User-Agent 的效果有限
> **攻擊者只要改一個字串就繞過了。**
> 這只能過濾掉「懶得改 UA 的自動化掃描」與**減少日誌雜訊**，
> **不能當成主要的防護手段**。
>
> **真正有效的是**：
> ```
> ① 應用層的輸入驗證與參數化查詢     ← 最重要
> ② WAF（ModSecurity + OWASP CRS）
> ③ 限流（limit_req）
> ④ fail2ban 依日誌自動封鎖
> ```

---

## 防盜連

```nginx
location ~* \.(?:jpg|jpeg|png|gif|webp|avif|svg|mp4|webm|pdf|zip)$ {
    valid_referers none blocked server_names
                   *.example.gov.tw
                   ~\.google\. ~\.bing\.;

    if ($invalid_referer) {
        return 403;
        # 或回傳一張「請勿盜連」的圖片
        # rewrite ^ /images/no-hotlink.png break;
    }

    expires 30d;
    add_header Cache-Control "public";
}
```

| `valid_referers` 參數 | 意思 |
| --- | --- |
| `none` | **沒有 Referer 標頭**（直接輸入網址、書籤） |
| `blocked` | Referer 被防火牆或代理移除了 |
| `server_names` | **本站的 server_name** |
| `*.example.gov.tw` | 指定網域 |
| `~\.google\.` | 正規表示式 |

> [!warning] 防盜連可能擋掉正常使用者
> ```
> · 使用者的隱私設定會移除 Referer
> · 從 https 連到 http 時瀏覽器不送 Referer
> · Referrer-Policy: no-referrer 的網站連過來
> · 某些 App 的 WebView 不送 Referer
> ```
> **所以 `none` 與 `blocked` 通常要放行**，
> 否則會擋掉相當比例的正常流量。
>
> **對重要資源，正確的做法是「簽名網址」**：
> ```nginx
> # 用 secure_link 模組
> location ^~ /protected-media/ {
>     secure_link $arg_md5,$arg_expires;
>     secure_link_md5 "$secure_link_expires$uri$remote_addr 你的密鑰";
>
>     if ($secure_link = "")  { return 403; }    # 簽名錯誤
>     if ($secure_link = "0") { return 410; }    # 已過期
>
>     alias /var/data/media/;
> }
> ```
> ```php
> // 應用層產生簽名網址
> $expires = time() + 3600;
> $md5 = base64_encode(md5($expires . $uri . $ip . '你的密鑰', true));
> $md5 = strtr($md5, '+/', '-_'); $md5 = str_replace('=', '', $md5);
> $url = "https://網站{$uri}?md5={$md5}&expires={$expires}";
> ```

---

## IP 封鎖與地理封鎖

```nginx
# ═══ 靜態封鎖清單 ═══
# /etc/nginx/conf.d/05-blocklist.conf
geo $blocked_ip {
    default 0;
    include /etc/nginx/blocklist.conf;      # ★ 由 fail2ban 或腳本產生
}

# /etc/nginx/blocklist.conf
# 203.0.113.5  1;
# 198.51.100.0/24  1;

server {
    if ($blocked_ip) { return 444; }
}

# ═══ 管理介面只允許內網 ═══
geo $is_internal {
    default 0;
    10.0.9.0/24    1;         # 管理網段
    127.0.0.0/8    1;
}

location ^~ /admin/ {
    if ($is_internal = 0) { return 404; }    # ★ 回 404 而非 403
    proxy_pass http://backend;
}

# 或用 allow/deny（更直接）
location ^~ /nginx-status {
    allow 127.0.0.1;
    allow 10.0.9.0/24;
    deny  all;
    stub_status on;
    access_log off;
}
```

> [!tip] 回 404 而非 403
> ```
> 403 Forbidden → 「這裡有東西，只是你沒權限」→ 攻擊者知道要繼續嘗試
> 404 Not Found → 「根本沒這個東西」        → ★ 攻擊者放棄
> ```

### 地理封鎖（GeoIP2）

```bash
$ sudo apt install -y libnginx-mod-http-geoip2
$ sudo mkdir -p /usr/share/GeoIP
# 從 MaxMind 下載 GeoLite2-Country.mmdb（需免費註冊）
```

```nginx
load_module modules/ngx_http_geoip2_module.so;

http {
    geoip2 /usr/share/GeoIP/GeoLite2-Country.mmdb {
        auto_reload 24h;
        $geoip2_country_code source=$remote_addr country iso_code;
    }

    map $geoip2_country_code $allowed_country {
        default 0;
        TW 1;      # 台灣
        JP 1;
        US 1;
        ""  1;     # ★ 查不到的也放行（避免誤擋）
    }

    server {
        if ($allowed_country = 0) { return 444; }
    }
}
```

> [!warning] 地理封鎖不可靠
> ```
> · VPN / Tor / 代理輕易繞過
> · IP 地理資料庫【本來就不準】（雲端主機、行動網路尤其）
> · 【會擋掉在國外出差的自己人】
> · 資料庫需要定期更新
> ```
> **只適合當作「減少雜訊」的輔助手段**，
> 不能當成存取控制。真正的存取控制要用**身分驗證**。

---

## 完整實戰範例

### 完整加固的站台設定

```nginx
# ═══════════ /etc/nginx/sites-available/app.example.gov.tw ═══════════

# ── HTTP：只做 ACME 與轉址 ──
server {
    listen 80;
    listen [::]:80;
    server_name app.example.gov.tw;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/acme;
        default_type "text/plain";
    }
    location / { return 301 https://$host$request_uri; }
}

# ── HTTPS 主站 ──
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name app.example.gov.tw;

    # ═══ TLS ═══
    ssl_certificate         /etc/letsencrypt/live/app.example.gov.tw/fullchain.pem;
    ssl_certificate_key     /etc/letsencrypt/live/app.example.gov.tw/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/app.example.gov.tw/chain.pem;
    include snippets/ssl-params.conf;

    # ═══ 安全標頭 ═══
    include snippets/security-headers.conf;

    # ═══ web root（★ public 子目錄）═══
    root  /var/www/app/current/public;
    index index.php;

    # ═══ 限制 ═══
    client_max_body_size 20m;
    limit_req  zone=general burst=40 nodelay;
    limit_conn perip 20;

    access_log /var/log/nginx/app.access.log main;
    error_log  /var/log/nginx/app.error.log  warn;

    # ═══ ① 阻擋惡意請求（最先）═══
    if ($blocked_ip) { return 444; }
    if ($bad_ua)     { return 444; }
    if ($bad_host)   { return 444; }
    if ($request_method !~ ^(GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)$) { return 405; }

    # ═══ ② 拒絕敏感路徑 ═══
    include snippets/deny-hidden.conf;

    # ═══ ③ 健康檢查 ═══
    location = /health {
        access_log off;
        limit_req off;
        default_type application/json;
        return 200 '{"status":"ok"}';
    }

    # ═══ ④ 監控端點（只允許內網）═══
    location = /nginx-status {
        allow 127.0.0.1;
        allow 10.0.9.0/24;
        deny  all;
        stub_status on;
        access_log off;
    }

    # ═══ ⑤ 登入端點：嚴格限流 ═══
    location = /login {
        limit_req zone=login burst=3 nodelay;
        try_files $uri /index.php?$query_string;
    }

    location ^~ /api/auth/ {
        limit_req zone=login burst=3 nodelay;
        try_files $uri /index.php?$query_string;
    }

    # ═══ ⑥ 管理後台：只允許內網 ═══
    location ^~ /admin/ {
        if ($is_internal = 0) { return 404; }
        try_files $uri /index.php?$query_string;
    }

    # ═══ ⑦ ★★ 上傳目錄：禁止執行 ═══
    location ^~ /uploads/ {
        location ~* \.(?:php|phtml|phar|php\d?|pl|py|cgi|sh)$ {
            deny all;
            access_log /var/log/nginx/upload-exec-attempt.log;
            return 404;
        }
        expires 7d;
        add_header Cache-Control "public" always;
        add_header X-Content-Type-Options "nosniff" always;
        # ★ 強制下載而非在瀏覽器中執行
        add_header Content-Disposition "attachment" always;
    }

    location ^~ /storage/ {
        location ~* \.(?:php|phtml|phar|php\d?)$ { deny all; return 404; }
        expires 7d;
    }

    # ═══ ⑧ 受保護的下載 ═══
    location ^~ /protected-files/ {
        internal;                                  # ★ 只能內部跳轉
        alias /var/data/app-uploads/;
    }

    # ═══ ⑨ 靜態資源（★ try_files 防 Cache Deception）═══
    location ~* \.(?:js|mjs|css|woff2?|ttf|jpg|jpeg|png|gif|webp|avif|svg|ico)$ {
        try_files $uri =404;                       # ★★ 必須
        expires 30d;
        add_header Cache-Control "public" always;
        access_log off;
        limit_req off;
        limit_conn off;
        include snippets/security-headers.conf;

        # 防盜連
        valid_referers none blocked server_names *.example.gov.tw;
        if ($invalid_referer) { return 403; }
    }

    # ═══ ⑩ 前端路由 ═══
    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }

    # ═══ ⑪ ★★ PHP 處理器 ═══
    location ~ \.php$ {
        try_files $uri =404;                       # ★★ 防 PathInfo 攻擊

        fastcgi_pass unix:/run/php/php8.3-fpm-app.sock;
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
        fastcgi_param DOCUMENT_ROOT   $realpath_root;
        fastcgi_param HTTPS           on;
        include fastcgi_params;

        fastcgi_hide_header X-Powered-By;
        fastcgi_read_timeout 60s;
        include snippets/security-headers.conf;    # ★ 補回來
    }

    # ═══ ⑫ 自訂錯誤頁 ═══
    error_page 400 401 403 404 405 /errors/4xx.html;
    error_page 500 501 502 503 504 /errors/5xx.html;
    location ^~ /errors/ {
        internal;
        root /var/www/error-pages;
    }
}

# ═══ 預設拒絕 ═══
server {
    listen 80  default_server;
    listen [::]:80 default_server;
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;
    ssl_reject_handshake on;
    return 444;
}
```

### 上線前安全驗證腳本

```bash
#!/usr/bin/env bash
# /usr/local/bin/nginx-security-audit —— Nginx 安全稽核
D="${1:?用法: $0 <domain>}"
B="https://$D"
FAIL=0; WARN=0

pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m⚠\033[0m %s\n' "$1"; WARN=$((WARN+1)); }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }

echo "═══════ Nginx 安全稽核 $D ═══════"

echo -e "\n【1】★★ 敏感檔案是否可下載"
for p in /.env /.env.example /.env.backup /.git/config /.git/HEAD /.gitignore \
         /composer.json /composer.lock /package.json /package-lock.json \
         /artisan /Dockerfile /docker-compose.yml /Makefile \
         /storage/logs/laravel.log /vendor/autoload.php \
         /phpinfo.php /info.php /test.php /adminer.php \
         /config.php.bak /index.php~ /.htaccess /web.config /README.md; do
    code=$(curl -sk -o /dev/null -w '%{http_code}' -m 5 "$B$p" 2>/dev/null)
    case "$code" in
        200) fail "$p 【可以下載！】" ;;
        403) warn "$p → 403（建議改成 404）" ;;
        *)   : ;;
    esac
done
[ "$FAIL" -eq 0 ] && pass "沒有發現可下載的敏感檔案"

echo -e "\n【2】★★ 上傳目錄能否執行程式"
for p in /uploads/test.php /uploads/x.php /storage/test.php /media/x.php \
         /uploads/image.jpg/x.php /index.php/x.php /uploads/shell.phar; do
    code=$(curl -sk -o /dev/null -w '%{http_code}' -m 5 "$B$p" 2>/dev/null)
    [ "$code" = "200" ] && fail "$p 【回 200 —— 可能可以執行】"
done
pass "上傳目錄檢查完成"

echo -e "\n【3】路徑穿越"
for p in "/files../etc/passwd" "/static/../../../etc/passwd" \
         "/..%2f..%2f..%2fetc%2fpasswd" "/%2e%2e/%2e%2e/etc/passwd"; do
    body=$(curl -sk -m 5 "$B$p" 2>/dev/null | head -c 200)
    echo "$body" | grep -q 'root:.*:0:0:' && fail "$p 【路徑穿越成功！】"
done
pass "沒有發現路徑穿越"

echo -e "\n【4】安全標頭（★ 檢查多個路徑，驗證 add_header 繼承）"
for p in / /api/health /assets/app.css /nonexistent-page-404; do
    hdr=$(curl -skI -m 5 "$B$p" 2>/dev/null)
    n=0
    for h in x-frame-options x-content-type-options referrer-policy strict-transport-security; do
        echo "$hdr" | grep -qi "^$h:" && n=$((n+1))
    done
    if [ "$n" -ge 4 ]; then pass "$p → $n/4 個安全標頭"
    elif [ "$n" -ge 2 ]; then warn "$p → 只有 $n/4（★ add_header 可能被覆蓋）"
    else fail "$p → 只有 $n/4"; fi
done

echo -e "\n【5】CSP"
csp=$(curl -skI -m 5 "$B/" 2>/dev/null | grep -i 'content-security-policy' | tr -d '\r')
if [ -z "$csp" ]; then
    warn "沒有 CSP（★ 建議先用 Report-Only 導入）"
else
    echo "$csp" | grep -qi 'report-only' && warn "CSP 是 Report-Only 模式（觀察中）" \
                                         || pass "CSP 已啟用強制模式"
    echo "$csp" | grep -q "unsafe-inline" && \
        echo "$csp" | grep -q "script-src[^;]*unsafe-inline" && \
        warn "★ script-src 含 'unsafe-inline' —— CSP 對 XSS 幾乎無效"
    echo "$csp" | grep -q "unsafe-eval" && warn "★ 含 'unsafe-eval'"
    echo "$csp" | grep -q "object-src 'none'" && pass "object-src 'none'" \
                                              || warn "建議加 object-src 'none'"
fi

echo -e "\n【6】版本與指紋"
srv=$(curl -skI -m 5 "$B/" 2>/dev/null | grep -i '^server:' | tr -d '\r')
echo "$srv" | grep -qE 'nginx/[0-9]' && fail "$srv 【洩漏版本號 —— server_tokens off】" \
                                     || pass "${srv:-（無 Server 標頭）}"
for h in x-powered-by x-aspnet-version x-generator x-drupal-cache; do
    v=$(curl -skI -m 5 "$B/" 2>/dev/null | grep -i "^$h:" | tr -d '\r')
    [ -n "$v" ] && fail "$v 【洩漏技術棧】"
done

echo -e "\n【7】TLS"
for p in tls1 tls1_1; do
    echo | timeout 5 openssl s_client -"$p" -connect "$D:443" -servername "$D" >/dev/null 2>&1 \
        && fail "${p^^} 仍然啟用【應關閉】" || pass "${p^^} 已關閉"
done
echo | timeout 5 openssl s_client -tls1_3 -connect "$D:443" -servername "$D" >/dev/null 2>&1 \
    && pass "TLS 1.3 已啟用" || warn "TLS 1.3 未啟用"
CH=$(echo | timeout 10 openssl s_client -connect "$D:443" -servername "$D" -showcerts 2>/dev/null | \
     grep -c 'BEGIN CERTIFICATE')
[ "$CH" -ge 2 ] && pass "憑證鏈完整（$CH 張）" || fail "憑證鏈不完整【應用 fullchain.pem】"

echo -e "\n【8】HTTP 轉址"
loc=$(curl -sI -m 5 "http://$D/" 2>/dev/null | grep -i '^location:' | tr -d '\r')
echo "$loc" | grep -qi 'https://' && pass "HTTP → HTTPS" || fail "HTTP 沒有轉到 HTTPS"

echo -e "\n【9】目錄列表"
for p in /assets/ /uploads/ /images/ /js/ /css/ /storage/; do
    body=$(curl -sk -m 5 "$B$p" 2>/dev/null | head -c 300)
    echo "$body" | grep -qi 'Index of\|<title>Index' && fail "$p 【目錄列表開啟！】"
done
pass "沒有發現目錄列表"

echo -e "\n【10】HTTP 方法"
for m in TRACE TRACK DEBUG PROPFIND; do
    code=$(curl -sk -o /dev/null -w '%{http_code}' -m 5 -X "$m" "$B/" 2>/dev/null)
    [ "$code" = "200" ] && fail "$m 方法可用【應阻擋】"
done
pass "危險的 HTTP 方法已阻擋"

echo -e "\n【11】限流"
codes=$(for i in $(seq 1 80); do
    curl -sk -o /dev/null -w '%{http_code} ' -m 3 "$B/" 2>/dev/null
done)
echo "$codes" | grep -q 429 && pass "限流生效（出現 429）" \
                            || warn "80 次連續請求沒有被限流（確認 limit_req 設定）"

echo -e "\n【12】設定檔檢查"
sudo nginx -T 2>/dev/null > /tmp/nginx-full.conf
chk() { grep -q "$1" /tmp/nginx-full.conf && pass "$2" || fail "$2"; }
chk 'server_tokens off'          "server_tokens off"
chk 'try_files \$uri =404'       "PHP location 有 try_files \$uri =404"
chk 'location ~ /\\\\.'          "有拒絕隱藏檔的規則"
chk 'ssl_protocols TLSv1.2 TLSv1.3' "ssl_protocols 只有 1.2/1.3"
chk 'limit_req_zone'             "有設定限流"
chk 'ssl_session_tickets off'    "ssl_session_tickets off"
grep -q 'autoindex on' /tmp/nginx-full.conf && fail "有 autoindex on【應關閉】" \
                                            || pass "autoindex 已關閉"
grep -q 'proxy_ignore_headers.*Set-Cookie' /tmp/nginx-full.conf && \
    fail "★★ proxy_ignore_headers Set-Cookie【快取洩漏風險】"
grep -qE 'location\s+/[a-z-]+\s*\{[^}]*alias' /tmp/nginx-full.conf && \
    warn "有 location 沒有結尾斜線卻用了 alias【路徑穿越風險】"
rm -f /tmp/nginx-full.conf

echo -e "\n【13】檔案權限"
[ -d /etc/letsencrypt/live ] && {
    perm=$(sudo stat -c '%a' /etc/letsencrypt/live 2>/dev/null)
    [ "$perm" = "700" ] && pass "憑證目錄權限 700" || warn "憑證目錄權限 $perm（建議 700）"
}
sudo find /var/www -name '.env' -perm /o+r 2>/dev/null | head -3 | \
    while read -r f; do fail ".env 權限太鬆：$f"; done
sudo find /var/www -name '*.log' 2>/dev/null | head -3 | \
    while read -r f; do warn "web root 內有日誌檔：$f"; done

echo -e "\n═══════ 結果 ═══════"
printf '  失敗 \033[31m%d\033[0m 項，警告 \033[33m%d\033[0m 項\n' "$FAIL" "$WARN"
[ "$FAIL" -eq 0 ] && echo "  ✓ 沒有嚴重問題" || echo "  ★ 請先修正所有失敗項目再上線"
echo
echo "  補充檢測："
echo "    · SSL Labs      https://www.ssllabs.com/ssltest/analyze.html?d=$D"
echo "    · Security Headers  https://securityheaders.com/?q=$D"
echo "    · Mozilla Observatory  https://observatory.mozilla.org/analyze/$D"
exit $FAIL
```

---

## 常見錯誤與排錯

| 現象／問題 | 原因 | 解法 |
| --- | --- | --- |
| **`.env` 可以下載** ★★★ | `root` 指向專案根目錄 | **`root` 改成 `.../public`** + `deny-hidden.conf` |
| **`.git` 可以存取** ★★★ | 同上；或部署時把 `.git` 一起放上去 | 同上；**部署時排除 `.git`** |
| **上傳的 jpg 被當 PHP 執行** ★★★ | 缺 `try_files $uri =404` / `cgi.fix_pathinfo=1` | **三道防線全部套用** |
| **安全標頭在某些路徑消失** ★ | **`add_header` 內層覆蓋外層** | 每個有 `add_header` 的 location 都 `include` |
| 404/500 頁面沒有安全標頭 | 缺 `always` | **所有安全標頭加 `always`** |
| **CSP 設完網站壞掉** | 直接抄別人的 CSP | **先用 `Report-Only` 跑一週再啟用** |
| CSP 對 XSS 沒防護力 | `script-src` 含 `'unsafe-inline'` | 改用 **nonce** |
| **`/files../etc/passwd` 拿到系統檔** | **alias 的 location 沒有結尾斜線** | **加結尾斜線** |
| 目錄被列出來 | `autoindex on` | `autoindex off;`（預設） |
| **HSTS 導致子網域全掛** | `includeSubDomains` | **導入前檢查所有子網域**；只能等過期 |
| 防盜連擋掉正常使用者 | 沒放行 `none` / `blocked` | `valid_referers none blocked server_names ...` |
| 地理封鎖擋掉出差的同事 | GeoIP 不可靠 | 只當輔助；**存取控制要用身分驗證** |
| **`Server: nginx/1.27.3`** | 沒關 `server_tokens` | `server_tokens off;`（完全移除需 headers-more） |
| 掃描器塞爆日誌 | 沒有阻擋規則 | 常見攻擊路徑 `return 444;` + `access_log off` |
| 403 洩漏路徑存在 | 直接回 403 | `return 404;` 或 `error_page 403 =404` |
| **正常使用者被限流** | 靜態資源沒排除 / NAT | 靜態 `limit_req off`；`geo` 排除內網 |
| **快取洩漏（A 看到 B 的頁面）** ★★ | `proxy_cache` 快取了個人化內容 | 登入路徑 `proxy_cache off`（見 05 篇） |

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> # ★ SELinux 是額外的一道防線（不要關掉）
> $ getenforce
> Enforcing
>
> # 正確的 context
> $ sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/app/current/public(/.*)?"
> $ sudo restorecon -Rv /var/www/app
>
> # ★ 上傳目錄設成「唯讀」的 context，PHP 也無法寫入可執行檔
> $ sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/app/current/public/uploads(/.*)?"
>
> # 需要 PHP 寫入的目錄
> $ sudo semanage fcontext -a -t httpd_sys_rw_content_t "/var/www/app/shared/storage(/.*)?"
> $ sudo restorecon -Rv /var/www/app/shared/storage
>
> # 布林值（★ 最小權限原則，不需要的就關著）
> $ getsebool -a | grep httpd | grep ' on$'
> $ sudo setsebool -P httpd_can_network_connect 1        # 只在需要連 TCP 後端時
> # httpd_can_sendmail、httpd_enable_cgi 等不需要就【不要開】
>
> # firewalld
> $ sudo firewall-cmd --permanent --add-service=https
> $ sudo firewall-cmd --permanent --remove-service=http   # 若已全 HTTPS
> $ sudo firewall-cmd --reload
> ```
>
> **SELinux 是 Nginx 安全的重要一環** ——
> 即使攻擊者拿到了 web shell，
> SELinux 也能阻止它寫入不該寫的目錄或執行不該執行的程式。
> **不要用 `setenforce 0` 當作排錯的解法。**

---

## 安全性注意事項

> [!danger] Nginx 設定不能取代應用層安全
> ```
> Nginx 能防的：
>   ✓ 檔案外洩、目錄列表、路徑穿越
>   ✓ 已知攻擊路徑的掃描
>   ✓ 部分的 DoS 與暴力破解
>   ✓ 傳輸加密
>   ✓ 上傳目錄執行
>
> Nginx 【不能】防的：
>   ✗ SQL Injection          → 應用層要用參數化查詢
>   ✗ XSS                    → 應用層要跳脫輸出（CSP 是第二道防線）
>   ✗ CSRF                   → 應用層要用 token
>   ✗ 業務邏輯漏洞（越權）    → 應用層要做授權檢查
>   ✗ 不安全的反序列化
>   ✗ 相依套件的已知漏洞      → 定期 composer audit / npm audit
> ```
> **Nginx 是縱深防禦的一層，不是全部。**

> [!warning] 定期更新才是最有效的安全措施
> ```bash
> # ★ 檢查 Nginx 版本與已知漏洞
> $ nginx -v
> $ apt list --upgradable 2>/dev/null | grep nginx
>
> # 自動安全更新
> $ sudo apt install -y unattended-upgrades
> $ sudo dpkg-reconfigure -plow unattended-upgrades
>
> # ★ 訂閱安全公告
> #   https://nginx.org/en/security_advisories.html
> #   https://ubuntu.com/security/notices
> ```
> **絕大多數的入侵事件不是因為設定不夠精巧，
> 而是因為跑著三年沒更新的軟體。**

> [!tip] 縱深防禦的七層
> ```
> ① 網路層     防火牆只開 80/443，後端只綁 127.0.0.1
> ② 傳輸層     TLS 1.2+、HSTS、正確的憑證鏈
> ③ ★ Nginx    本篇的所有設定
> ④ WAF        ModSecurity + OWASP CRS（見 ModSecurity 章節）
> ⑤ 應用層     輸入驗證、參數化查詢、授權檢查、CSRF token
> ⑥ 系統層     SELinux/AppArmor、最小權限、定期更新
> ⑦ 監控層     日誌集中、fail2ban、Wazuh、異常告警
> ```
> **每一層都會有漏洞，但攻擊者要同時突破七層才會成功。**

> [!warning] 上線後也要持續驗證
> ```bash
> # ★ 把安全稽核腳本排程化
> $ sudo tee /etc/cron.d/nginx-security-audit >/dev/null <<'EOF'
> 0 3 * * 1 root /usr/local/bin/nginx-security-audit app.example.gov.tw > /var/log/security-audit.log 2>&1 || \
>   mail -s "【警告】Nginx 安全稽核發現問題" admin@example.gov.tw < /var/log/security-audit.log
> EOF
> ```
> **每次部署後也要跑一次** ——
> 部署腳本的一個小錯誤（例如把 `.env` 複製到 `public/`）
> 就可能造成嚴重外洩。

---

## 速查表

### 三個最嚴重的問題 ★★★

```nginx
① root /var/www/app/current/public;      # 不是專案根目錄
② location ~ \.php$ { try_files $uri =404; }   # + php.ini cgi.fix_pathinfo=0
③ location ^~ /uploads/ {
      location ~* \.(php|phtml|phar|php\d?)$ { deny all; return 404; }
  }
```

```bash
# 三十秒自我檢查
for p in /.env /.git/config /composer.json /storage/logs/laravel.log; do
  curl -sk -o /dev/null -w "$p %{http_code}\n" https://網站$p
done   # ★ 全部必須是 404
```

### 安全標頭

```nginx
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header Cross-Origin-Opener-Policy "same-origin" always;
proxy_hide_header X-Powered-By;
fastcgi_hide_header X-Powered-By;

★ 每個有 add_header 的 location 都要 include 一次（陣列型指令會覆蓋）
★ 一律加 always（否則 4xx/5xx 沒防護）
```

### CSP 導入三階段

```nginx
# ① Report-Only 觀察一週
add_header Content-Security-Policy-Report-Only "default-src 'self'; report-uri /csp-report" always;
# ② 依報告放行必要來源（仍是 Report-Only）
# ③ 改成 Content-Security-Policy 強制

★ script-src 絕不要 'unsafe-inline' / 'unsafe-eval' → 用 nonce
★ 一定要有 object-src 'none'; base-uri 'self'; form-action 'self';
```

### 拒絕敏感路徑

```nginx
location ~ /\.(?!well-known) { deny all; return 404; }
location ~* \.(env|log|sql|bak|old|swp|pem|key|ini|yml)$ { deny all; return 404; }
location ~* /(composer\.(json|lock)|package.*\.json|artisan|Dockerfile)$ { deny all; return 404; }
location ~* ^/(vendor|node_modules|storage|tests)/ { deny all; return 404; }
location ~* ^/(wp-admin|phpmyadmin|adminer)/ { deny all; return 444; }

★ 回 404 而非 403（403 等於告訴攻擊者「這裡有東西」）
```

### 阻擋與限制

```nginx
if ($request_method !~ ^(GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)$) { return 405; }

map $http_user_agent $bad_ua {
    default 0;  "" 1;
    ~*(nikto|sqlmap|nmap|masscan|acunetix) 1;
}
if ($bad_ua) { return 444; }

geo $is_internal { default 0; 10.0.9.0/24 1; }
location ^~ /admin/ { if ($is_internal = 0) { return 404; } }

location = /nginx-status { allow 127.0.0.1; deny all; stub_status on; }
```

### 防盜連與簽名網址

```nginx
valid_referers none blocked server_names *.example.gov.tw;
if ($invalid_referer) { return 403; }
★ none 與 blocked 要放行，否則擋掉正常使用者

# 重要資源用簽名網址
location ^~ /protected-media/ {
    secure_link $arg_md5,$arg_expires;
    secure_link_md5 "$secure_link_expires$uri$remote_addr 密鑰";
    if ($secure_link = "")  { return 403; }
    if ($secure_link = "0") { return 410; }
    alias /var/data/media/;
}
```

### 上線前檢查清單

```
□ root 指向 public/（不是專案根目錄）★★★
□ .env / .git / composer.json 全部 404 ★★★
□ 上傳目錄禁止執行 php/phtml/phar ★★★
□ location ~ \.php$ 有 try_files $uri =404 ★★★
□ php.ini: cgi.fix_pathinfo=0、open_basedir、disable_functions
□ alias 的 location 都有結尾斜線
□ 靜態資源 location 有 try_files $uri =404（防 Cache Deception）
□ 每個 location 都有完整安全標頭（含 404 頁面）
□ server_tokens off
□ autoindex off
□ ssl_protocols 只有 TLSv1.2 TLSv1.3
□ 憑證鏈完整（fullchain.pem）+ deploy hook
□ HSTS 漸進導入
□ CSP 至少 Report-Only
□ default_server + ssl_reject_handshake on + return 444
□ 限流（登入端點嚴格、靜態資源排除）
□ 管理介面限制來源
□ 錯誤頁自訂（internal）
□ 日誌不在 web root、權限 640
□ proxy_cache 對登入路徑關閉
□ 定期更新 + unattended-upgrades
□ 安全稽核腳本排程化
```

### 外部檢測

```
SSL Labs           https://www.ssllabs.com/ssltest/
Security Headers   https://securityheaders.com/
Mozilla Observatory https://observatory.mozilla.org/
```

---

## 練習題

> [!question]- 練習 1：重現三個最嚴重的問題
> **★ 在測試環境做**
> 1. 建立一個 Laravel 專案，**故意把 `root` 指向專案根目錄**
> 2. `curl https://測試站台/.env` → **拿到資料庫密碼了嗎？**
> 3. 用 `git-dumper` 或 `curl /.git/HEAD` 測試 `.git` 是否可存取
> 4. 上傳一個內容是 `<?php echo "PWNED";` 的 `test.jpg`
> 5. 存取 `/uploads/test.jpg/x.php` → **看到 PWNED 了嗎？**
> 6. **逐項修正，每修一項就重測一次**
> 7. 最後跑完整的安全稽核腳本

> [!question]- 練習 2：安全標頭的繼承陷阱
> 1. 在 `http` 層設定四個安全標頭
> 2. 在某個 `location` 加一個 `add_header Access-Control-Allow-Origin`
> 3. **對那個路徑 `curl -I`，還剩幾個安全標頭？**
> 4. 加上 `include snippets/security-headers.conf` 後重測
> 5. **檢查 404 頁面**：`curl -I https://網站/不存在的路徑`
> 6. 移除 `always` 再測一次 404 → **標頭還在嗎？**
> 7. 對你的**正式站台**跑一次多路徑檢查

> [!question]- 練習 3：CSP 從零導入
> 1. 對一個真實的網站設定 `Content-Security-Policy-Report-Only: default-src 'self'`
> 2. 建立 `/csp-report` 端點收集報告
> 3. **正常使用網站一天**，收集違規紀錄
> 4. 統計 `blocked-uri`，列出需要放行的來源
> 5. 逐步放寬 policy，直到沒有違規
> 6. 改成強制模式
> 7. **試著移除 `script-src` 的 `'unsafe-inline'`** —— 網站還能用嗎？需要改哪些程式碼？

> [!question]- 練習 4：完整安全稽核
> 1. 部署本篇的 `nginx-security-audit` 腳本
> 2. 對你的**測試環境**執行
> 3. **逐項修正所有失敗與警告**
> 4. 到 SSL Labs、Security Headers、Mozilla Observatory 檢測
> 5. **目標：SSL Labs A+、Security Headers A**
> 6. 把腳本排程化（每週一次 + 每次部署後）
> 7. 接到告警通知

> [!question]- 練習 5：縱深防禦驗證
> 假設攻擊者已經取得了 web shell（模擬：在 `public/` 放一個測試用的 shell）：
> 1. **他能讀到 `.env` 嗎？**（`open_basedir` 有擋住嗎？）
> 2. **他能執行 `id`、`ls /` 嗎？**（`disable_functions` 有擋住嗎？）
> 3. **他能寫入 `public/` 嗎？**（檔案權限 / SELinux）
> 4. **他能連到資料庫嗎？**（網路隔離）
> 5. **他能連到外部嗎？**（出向防火牆）
> 6. **這個行為會被記錄與告警嗎？**（Wazuh / fail2ban）
> 7. **每一個「能」都是一個要補的洞**

---

## 小測驗

Q1. **Nginx 最嚴重也最常見的三個安全問題是什麼**？

Q2. **`root` 指向專案根目錄與指向 `public/` 有什麼差別？會洩漏哪些檔案**？

Q3. **上傳目錄執行 PHP 的三道防線分別是什麼？更根本的做法有哪三種**？

Q4. **安全標頭為什麼要加 `always`？為什麼每個 location 都要重複 include**？

Q5. **CSP 的正確導入流程是什麼？為什麼不能直接抄別人的**？

Q6. **`script-src 'unsafe-inline'` 為什麼讓 CSP 幾乎失效？正確做法是什麼**？

Q7. **為什麼建議回 404 而非 403**？

Q8. **`valid_referers` 中的 `none` 與 `blocked` 為什麼通常要放行？重要資源該用什麼取代防盜連**？

Q9. **Nginx 設定「能防」與「不能防」哪些攻擊**？

Q10. **縱深防禦的七層是什麼？為什麼「定期更新」比精巧的設定更重要**？

> [!question]- 測驗答案
> **Q1.** ①**`root` 指向專案根目錄而非 `public/`** ——
> `.env`（資料庫密碼、API 金鑰）、`composer.json`、`vendor/`、
> `storage/logs/laravel.log` 全部可以被下載；
> ②**上傳目錄可以執行 PHP** ——
> 攻擊者上傳 `shell.php` 就取得 web shell，整台機器淪陷；
> ③**`.git` 目錄可以存取** ——
> 攻擊者用 `git-dumper` 把整份原始碼與提交歷史下載下來，
> **歷史中的舊 `.env`、金鑰、內部 IP 全部外洩**。
>
> **Q2.** **`root /var/www/myproject;`（專案根目錄）**：
> `.env`、`composer.json`、`composer.lock`、`vendor/`（含所有套件原始碼）、
> `storage/logs/laravel.log`、`artisan`、`.git/`、`Dockerfile`、`docker-compose.yml`
> **全部在 web root 內，全部可以被直接下載**。
> **`root /var/www/myproject/current/public;`**：
> 那些檔案**在 web root 之外，Nginx 根本碰不到**。
> Laravel、Symfony、Nuxt 都是這個結構。
> 即使有 `deny` 規則，也應該**從根本上讓檔案不在 web root 內**
> —— 深度防禦：規則可能寫錯或被繞過，但目錄結構不會。
>
> **Q3.** **三道防線**：
> ①**Nginx 的 PHP location 加 `try_files $uri =404;`**（防 PathInfo 攻擊）；
> ②**`php.ini` 設 `cgi.fix_pathinfo = 0`**；
> ③**上傳目錄用 `^~` 明確禁止**：
> ```nginx
> location ^~ /uploads/ {
>     location ~* \.(php|phtml|phar|php\d?)$ { deny all; return 404; }
> }
> ```
> **三種更根本的做法**：
> ①**上傳的檔案不要放在 web root 內**，用 `internal` + `X-Accel-Redirect` 提供下載
> （順便還能做權限檢查）；
> ②**放在獨立的網域**（該網域完全沒有 PHP 處理器）；
> ③**上傳時重新命名並驗證真實的檔案類型**（用 magic bytes，不信任副檔名與 MIME）。
>
> **Q4.** **`always`**：不加的話，`add_header` **只會在 2xx 與 3xx 的回應中生效**，
> **404 與 500 頁面就沒有任何防護標頭** ——
> 而攻擊者往往就是刻意去觸發錯誤頁面。
> **每個 location 都要重複 include**：因為 **`add_header` 是「陣列型指令」，
> 內層的設定會「完全覆蓋」外層，而不是累加** ——
> `http` 層設了四個安全標頭，某個 `location` 只加了一個 `add_header`（例如 CORS），
> **那個 location 就「只有」那一個標頭，上面四個全部消失**，
> 而且你不會發現，因為主頁面看起來正常。
>
> **Q5.** **正確流程是三階段**：
> ①**先用 `Content-Security-Policy-Report-Only` 觀察至少一週**，
> 搭配 `report-uri` 收集違規紀錄；
> ②**統計 `blocked-uri`，逐步放行真正需要的來源**（仍是 Report-Only）；
> ③**確認沒有違規後，才改成 `Content-Security-Policy` 強制模式**。
> **不能直接抄別人的**，因為 CSP 必須完全符合**你的網站實際載入的資源**
> （CDN、字型、分析工具、內嵌腳本…）——
> **抄來的 CSP 幾乎一定會擋掉你網站的某些資源，導致網站部分或完全壞掉**，
> 而且症狀往往只在某些頁面出現，很難發現。
>
> **Q6.** 因為 **`'unsafe-inline'` 允許所有內聯腳本**
> （`<script>alert(1)</script>`、`onclick="..."`）——
> **而這正是 XSS 攻擊最主要的形式**。
> 有了它，攻擊者注入的腳本一樣會執行，CSP 等於形同虛設。
> **正確做法是用 nonce**：
> ```nginx
> set $csp_nonce $request_id;         # 每個請求唯一
> add_header Content-Security-Policy "script-src 'self' 'nonce-$csp_nonce'; object-src 'none'" always;
> ```
> 應用層在每個合法的 `<script>` 加上對應的 `nonce` 屬性 ——
> 攻擊者注入的腳本因為沒有正確的 nonce 就不會執行。
> （`style-src` 的 `'unsafe-inline'` 風險較低，多數框架難以避免，
> 但 **`script-src` 絕對要避免**。）
>
> **Q7.** 因為狀態碼會洩漏資訊：
> **`403 Forbidden` 等於告訴攻擊者「這裡確實有東西，只是你沒有權限」** ——
> 攻擊者知道路徑正確，會繼續嘗試其他繞過方式（換 IP、找認證繞過、猜其他相似路徑）；
> **`404 Not Found` 讓他以為根本不存在**，通常就放棄了。
> 這對**管理後台、內部 API、敏感檔案**特別重要：
> ```nginx
> location ^~ /admin/ { if ($is_internal = 0) { return 404; } }
> error_page 403 =404 /errors/404.html;
> ```
> 對明顯的掃描行為甚至可以用 `return 444`（直接關閉連線，完全沉默）。
>
> **Q8.** 因為**相當比例的正常請求根本沒有 Referer 標頭**：
> 使用者的隱私設定移除了它、從 https 連到 http 時瀏覽器不送、
> 對方網站設了 `Referrer-Policy: no-referrer`、
> 某些 App 的 WebView 不送、使用者直接輸入網址或用書籤。
> **不放行 `none` 與 `blocked` 會擋掉這些正常使用者**（圖片破圖）。
> **重要資源該用「簽名網址」（`secure_link` 模組）取代**：
> ```nginx
> location ^~ /protected-media/ {
>     secure_link $arg_md5,$arg_expires;
>     secure_link_md5 "$secure_link_expires$uri$remote_addr 密鑰";
>     if ($secure_link = "")  { return 403; }     # 簽名錯誤
>     if ($secure_link = "0") { return 410; }     # 已過期
>     alias /var/data/media/;
> }
> ```
> 應用層產生帶簽名與到期時間的網址 —— 這是真正可靠的存取控制。
>
> **Q9.** **Nginx 能防**：檔案外洩、目錄列表、路徑穿越、
> 已知攻擊路徑的掃描、部分的 DoS 與暴力破解（限流）、
> 傳輸加密（TLS）、上傳目錄執行。
> **Nginx 不能防**：
> **SQL Injection**（要靠應用層的參數化查詢）、
> **XSS**（要靠應用層跳脫輸出，CSP 只是第二道防線）、
> **CSRF**（要靠應用層的 token）、
> **業務邏輯漏洞與越權存取**（要靠應用層的授權檢查）、
> **不安全的反序列化**、
> **相依套件的已知漏洞**（要靠 `composer audit` / `npm audit`）。
> **Nginx 是縱深防禦的一層，不是全部。**
>
> **Q10.** **七層**：
> ①**網路層**（防火牆只開 80/443、後端只綁 127.0.0.1）；
> ②**傳輸層**（TLS 1.2+、HSTS、正確的憑證鏈）；
> ③**Nginx**（本篇的所有設定）；
> ④**WAF**（ModSecurity + OWASP CRS）；
> ⑤**應用層**（輸入驗證、參數化查詢、授權檢查、CSRF token）；
> ⑥**系統層**（SELinux/AppArmor、最小權限、定期更新）；
> ⑦**監控層**（日誌集中、fail2ban、Wazuh、異常告警）。
> **「定期更新」更重要的原因**：
> **絕大多數的入侵事件不是因為設定不夠精巧，
> 而是因為跑著三年沒更新的軟體，被已知且有公開 exploit 的漏洞打進來。**
> 再精巧的設定也擋不住 Nginx、PHP、或某個 Composer 套件的遠端執行漏洞。
> 所以 `unattended-upgrades` + 訂閱安全公告，
> 比花三天調 CSP 的效益高得多。

---

## 延伸閱讀

- [[00-ModSecurity-索引]] — WAF 是 Nginx 之上的第四層防護
- [[06-Nginx-HTTPS與Certbot]] — TLS 與 HSTS
- [[05-Nginx-靜態資源與快取]] — 快取洩漏與 Web Cache Deception
- [[03-Nginx-location與rewrite]] — location 安全規則
- [[02-應用層安全]] — OWASP Top 10 與應用層防護
- [[06-PHP-安全設定]] — open_basedir、disable_functions
- [[05-Fail2ban入侵防護]] — 依日誌自動封鎖
- [[07-Apache-安全與效能]] — Apache 的對應設定
