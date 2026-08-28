---
title: "Apache 安全與效能"
desc: "安全加固清單、壓縮與快取、逾時與限流，以及上線前的完整驗證"
aliases: [Apache 加固, hardening, mod_deflate, mod_expires, mod_evasive, ServerTokens]
tags: [群組/軟體與開發工具, 服務/apache, 主題/安全]
category: Apache
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[06-Apache-與PHP整合]]"]
updated: 2026-08-28
---

# Apache 安全與效能

> [!abstract] 這篇你會學到
> - 一份可直接套用的 **Apache 安全加固設定**
> - 設定 **`mod_deflate` / `mod_brotli` 壓縮**與 **`mod_expires` 快取**
> - 用 **`mod_reqtimeout` / `mod_evasive` / `mod_ratelimit`** 抵抗慢速攻擊與 DoS
> - 設定 **`mod_cache` 反向代理快取**
> - 完成**上線前的安全與效能驗證**
> - 建立可排程的**稽核腳本**

## 前置知識

- [[06-Apache-與PHP整合]] — PHP-FPM 與權限隔離
- [[03-Apache-模組與MPM]] — MPM 調校
- [[09-Nginx-安全設定]] — 通用的 Web 安全觀念（本篇不重複）

---

## 安全加固基準

```apache
# ═══════════ /etc/apache2/conf-available/hardening.conf ═══════════

# ── ① 隱藏版本與簽章 ──
ServerTokens Prod                    # 只顯示 "Apache"
ServerSignature Off                  # 錯誤頁不顯示版本與主機名

# ── ② 全域預設拒絕 ──
<Directory />
    Options None
    AllowOverride None
    Require all denied
</Directory>

# ── ③ 關閉危險的 HTTP 方法 ──
TraceEnable Off                      # ★ 防 Cross-Site Tracing

# ── ④ 逾時（★ 防 Slowloris / Slow POST）──
Timeout 30
KeepAlive On
KeepAliveTimeout 5
MaxKeepAliveRequests 500

<IfModule mod_reqtimeout.c>
    # header：20 秒內收完，或至少每秒 500 bytes，最多 40 秒
    # body  ：20 秒內收完，或至少每秒 500 bytes
    RequestReadTimeout header=20-40,MinRate=500 body=20,MinRate=500
</IfModule>

# ── ⑤ 限制請求大小 ──
LimitRequestBody      20971520       # 20 MB
LimitRequestFields    100
LimitRequestFieldSize 8190
LimitRequestLine      8190
LimitXMLRequestBody   1048576

# ── ⑥ 移除 ETag（避免洩漏 inode）──
FileETag None

# ── ⑦ 安全標頭 ──
<IfModule mod_headers.c>
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-Content-Type-Options "nosniff"
    Header always set Referrer-Policy "strict-origin-when-cross-origin"
    Header always set Permissions-Policy "geolocation=(), microphone=(), camera=(), payment=()"
    Header always set Cross-Origin-Opener-Policy "same-origin"

    # ★ 移除洩漏技術棧的標頭
    Header always unset X-Powered-By
    Header always unset X-AspNet-Version
    Header always unset X-Generator
    Header unset Server

    # ★ 強制 Cookie 加上安全屬性（補救措施）
    Header always edit Set-Cookie ^(.*)$ "$1; HttpOnly; Secure; SameSite=Lax"
</IfModule>

# ── ⑧ 拒絕敏感檔案（★ 全域生效）──
<FilesMatch "^\.">
    Require all denied
</FilesMatch>

<FilesMatch "\.(env|log|sql|sqlite3?|db|bak|backup|old|orig|save|swp|swo|tmp|dist|inc|conf|ini|ya?ml|toml|lock|sh|bash|pem|key|crt|p12|pfx)$">
    Require all denied
</FilesMatch>

<FilesMatch "^(composer\.(json|lock)|package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|artisan|Makefile|Dockerfile|docker-compose\.ya?ml|webpack\.config\.js|vite\.config\.js|phpunit\.xml|README\.md|CHANGELOG\.md|LICENSE)$">
    Require all denied
</FilesMatch>

<DirectoryMatch "/(\.git|\.svn|\.hg|vendor|node_modules|tests|\.github|\.vscode|\.idea)/">
    Require all denied
</DirectoryMatch>

# ── ⑨ 常見攻擊路徑（減少日誌雜訊）──
<LocationMatch "^/(wp-admin|wp-login|wp-content|xmlrpc\.php|phpmyadmin|pma|adminer)">
    Require all denied
</LocationMatch>
```

```bash
$ sudo a2enmod headers reqtimeout
$ sudo a2enconf hardening
$ sudo apache2ctl configtest && sudo systemctl restart apache2
```

### 停用不需要的模組

```bash
$ sudo a2dismod \
    info \              # ★★ /server-info 洩漏完整設定
    status \            # ★ /server-status 洩漏執行中的 URL
    autoindex \         # ★ 目錄列表
    userdir \           # /~user/
    cgi cgid \          # CGI
    include \           # SSI
    dav dav_fs \        # WebDAV
    negotiation \       # MultiViews
    imagemap actions speling
$ sudo systemctl restart apache2

# 移除預設的別名設定
$ sudo a2disconf serve-cgi-bin
$ sudo a2dissite 000-default
```

```bash
# ★ 驗證
$ for p in /server-info /server-status /icons/ /manual/ /cgi-bin/ /~root/; do
    printf '%-20s %s\n' "$p" "$(curl -sk -o /dev/null -w '%{http_code}' https://網站$p)"
  done
# ★ 全部必須是 403 或 404
```

---

## 壓縮

```apache
# ═══════════ /etc/apache2/conf-available/compression.conf ═══════════
<IfModule mod_deflate.c>
    <IfModule mod_filter.c>
        AddOutputFilterByType DEFLATE \
            text/plain text/html text/xml text/css text/javascript \
            application/javascript application/x-javascript \
            application/json application/xml application/rss+xml \
            application/ld+json application/manifest+json \
            application/vnd.api+json \
            image/svg+xml image/x-icon \
            font/ttf font/otf application/x-font-ttf
    </IfModule>

    DeflateCompressionLevel 5          # ★ 1-9，5 是甜蜜點

    # ★ 舊瀏覽器排除
    BrowserMatch ^Mozilla/4         gzip-only-text/html
    BrowserMatch ^Mozilla/4\.0[678] no-gzip
    BrowserMatch \bMSIE\ [456]      no-gzip

    # ★ 已經壓縮過的格式不要再壓
    SetEnvIfNoCase Request_URI \.(?:gif|jpe?g|png|webp|avif|ico)$   no-gzip dont-vary
    SetEnvIfNoCase Request_URI \.(?:zip|gz|bz2|rar|7z|tgz)$         no-gzip dont-vary
    SetEnvIfNoCase Request_URI \.(?:mp3|mp4|webm|avi|mkv|flv)$      no-gzip dont-vary
    SetEnvIfNoCase Request_URI \.(?:pdf|woff2?)$                    no-gzip dont-vary

    # ★ Vary 標頭（CDN 必要）
    Header append Vary Accept-Encoding env=!dont-vary
</IfModule>

# ═══ brotli（Apache 2.4.26+）═══
<IfModule mod_brotli.c>
    AddOutputFilterByType BROTLI_COMPRESS \
        text/html text/plain text/css text/javascript \
        application/javascript application/json application/xml \
        image/svg+xml
    BrotliCompressionQuality 5         # ★ 0-11
    BrotliWindowSize 18
</IfModule>
```

```bash
$ sudo a2enmod deflate brotli filter
$ sudo a2enconf compression
$ sudo systemctl restart apache2

# 驗證
$ curl -sI -H 'Accept-Encoding: gzip' https://網站/assets/app.js | grep -i content-encoding
content-encoding: gzip
$ curl -sI -H 'Accept-Encoding: br' https://網站/assets/app.js | grep -i content-encoding
content-encoding: br

# 比較大小
$ for e in identity gzip br; do
    printf '%-10s %s bytes\n' "$e" \
      "$(curl -s -H "Accept-Encoding: $e" -o /dev/null -w '%{size_download}' https://網站/assets/app.js)"
  done
```

> [!danger] 不要壓縮含機密的動態回應（BREACH）
> ```apache
> # ★ 敏感 API 關閉壓縮
> <LocationMatch "^/api/(auth|payment|user)">
>     SetEnv no-gzip 1
>     SetEnv no-brotli 1
> </LocationMatch>
> ```
> **BREACH 攻擊**：攻擊者透過觀察壓縮後的回應大小，
> 可以逐字元推測出回應中的 CSRF token 或 session。
> 詳見 [[05-Nginx-靜態資源與快取]]。

> [!tip] 預壓縮（★ 最好的壓縮是不在請求時壓縮）
> ```apache
> # 提供預先產生的 .gz / .br 檔案
> <IfModule mod_rewrite.c>
>     RewriteEngine On
>
>     # brotli
>     RewriteCond %{HTTP:Accept-Encoding} br
>     RewriteCond %{REQUEST_FILENAME}\.br -f
>     RewriteRule ^(.*)$ $1.br [QSA,L]
>
>     # gzip
>     RewriteCond %{HTTP:Accept-Encoding} gzip
>     RewriteCond %{REQUEST_FILENAME}\.gz -f
>     RewriteRule ^(.*)$ $1.gz [QSA,L]
> </IfModule>
>
> # ★ 設定正確的 Content-Type 與 Content-Encoding
> <FilesMatch "\.js\.br$">
>     AddType application/javascript .br
>     Header set Content-Encoding br
>     Header append Vary Accept-Encoding
> </FilesMatch>
> <FilesMatch "\.css\.br$">
>     AddType text/css .br
>     Header set Content-Encoding br
>     Header append Vary Accept-Encoding
> </FilesMatch>
> <FilesMatch "\.js\.gz$">
>     AddType application/javascript .gz
>     Header set Content-Encoding gzip
>     Header append Vary Accept-Encoding
> </FilesMatch>
> <FilesMatch "\.css\.gz$">
>     AddType text/css .gz
>     Header set Content-Encoding gzip
>     Header append Vary Accept-Encoding
> </FilesMatch>
> ```
> ```bash
> # 建置後產生壓縮檔
> $ find dist -type f \( -name '*.js' -o -name '*.css' -o -name '*.svg' \) -size +1k \
>     -print0 | xargs -0 -P4 -I{} sh -c 'gzip -9 -k -f "{}"; brotli -9 -k -f "{}"'
> ```

---

## 快取標頭

```apache
# ═══════════ /etc/apache2/conf-available/caching.conf ═══════════
<IfModule mod_expires.c>
    ExpiresActive On
    ExpiresDefault "access plus 0 seconds"

    # 圖片
    ExpiresByType image/jpeg "access plus 1 month"
    ExpiresByType image/png  "access plus 1 month"
    ExpiresByType image/webp "access plus 1 month"
    ExpiresByType image/avif "access plus 1 month"
    ExpiresByType image/svg+xml "access plus 1 month"
    ExpiresByType image/x-icon  "access plus 1 year"

    # 字型
    ExpiresByType font/woff2 "access plus 1 year"
    ExpiresByType font/woff  "access plus 1 year"

    # CSS / JS
    ExpiresByType text/css "access plus 1 week"
    ExpiresByType application/javascript "access plus 1 week"

    # ★ HTML 不快取
    ExpiresByType text/html "access plus 0 seconds"
    ExpiresByType application/json "access plus 0 seconds"
</IfModule>

<IfModule mod_headers.c>
    # ★ 帶 hash 的資源：永久快取
    <FilesMatch "\.[0-9a-f]{8,}\.(js|mjs|css|woff2?)$">
        Header always set Cache-Control "public, max-age=31536000, immutable"
        Header unset ETag
        FileETag None
    </FilesMatch>

    # 字型：長快取 + CORS
    <FilesMatch "\.(woff2?|ttf|otf)$">
        Header always set Cache-Control "public, max-age=31536000, immutable"
        Header always set Access-Control-Allow-Origin "*"
    </FilesMatch>

    # ★★ 入口檔：絕不快取
    <FilesMatch "^(index\.html|sw\.js|manifest\.json)$">
        Header always set Cache-Control "no-store, no-cache, must-revalidate, max-age=0"
        Header always set Pragma "no-cache"
    </FilesMatch>

    # ★ API：不快取
    <LocationMatch "^/api/">
        Header always set Cache-Control "no-store, private"
    </LocationMatch>
</IfModule>
```

```bash
$ sudo a2enmod expires headers
$ sudo a2enconf caching
$ sudo systemctl restart apache2

# ★ 驗證
$ for p in /index.html /assets/app.a1b2c3d4.js /favicon.ico /api/health; do
    cc=$(curl -skI "https://網站$p" | grep -i '^cache-control' | tr -d '\r')
    printf '  %-35s %s\n' "$p" "${cc:-（無）}"
  done
```

> [!danger] `index.html` 長期快取 = 部署後白畫面
> **這與 Nginx 的問題完全相同**，見 [[05-Nginx-靜態資源與快取]]。
> ```
> index.html 被快取一年 → 部署新版 → 舊 index.html 引用已刪除的 JS
>   → 【網站完全白畫面，而且無法補救】
> ```

---

## `mod_cache`：反向代理快取

```apache
<IfModule mod_cache.c>
    <IfModule mod_cache_disk.c>
        CacheRoot /var/cache/apache2/mod_cache_disk
        CacheDirLevels 2
        CacheDirLength 1
        CacheMaxFileSize 10000000
        CacheMinFileSize 1
        CacheDefaultExpire 3600
        CacheMaxExpire 86400

        # ★ 只快取明確允許的路徑
        <LocationMatch "^/(news|public-api)/">
            CacheEnable disk
            CacheHeader on                   # ★ 加上 X-Cache 標頭
            CacheDetailHeader on
            CacheLock on                     # ★ 防快取雪崩
            CacheLockMaxAge 5
            CacheStaleOnError on             # ★ 後端掛了用舊快取
            CacheIgnoreQueryString off
        </LocationMatch>

        # ★★ 登入相關路徑絕對不快取
        <LocationMatch "^/(admin|api/user|dashboard|profile)">
            CacheDisable on
        </LocationMatch>

        # ★ 不要忽略這些標頭（保護機制）
        # CacheIgnoreCacheControl Off        （預設）
        # CacheIgnoreHeaders Set-Cookie      ← ❌❌ 絕對不要設
    </IfModule>
</IfModule>
```

```bash
$ sudo a2enmod cache cache_disk
$ sudo mkdir -p /var/cache/apache2/mod_cache_disk
$ sudo chown -R www-data:www-data /var/cache/apache2
$ sudo chmod 700 /var/cache/apache2/mod_cache_disk
$ sudo systemctl restart apache2

# ★ 快取清理（htcacheclean）
$ sudo systemctl enable --now apache-htcacheclean
$ sudo systemctl status apache-htcacheclean

# 手動清理
$ sudo htcacheclean -v -t -p /var/cache/apache2/mod_cache_disk -l 1G
```

```bash
# 驗證快取
$ curl -sI https://網站/news/123 | grep -i x-cache
X-Cache: MISS from app.example.gov.tw
$ curl -sI https://網站/news/123 | grep -i x-cache
X-Cache: HIT from app.example.gov.tw      # ★ 命中
```

> [!danger] 快取洩漏：`CacheIgnoreHeaders Set-Cookie` 絕對不能設
> ```
> 設了之後，帶有個人 session 的頁面會被快取
>   → 使用者 A 的個人資料頁被存進快取
>     → 使用者 B 存取同一個 URL → 【拿到 A 的個資】
> ```
> **驗證**：
> ```bash
> $ curl -s -b "session=AAA" https://網站/dashboard | md5sum
> $ curl -s https://網站/dashboard | md5sum
> # ★ 兩者相同 = 可能有快取洩漏
> ```

---

## DoS 防護

### `mod_evasive`

```bash
$ sudo apt install -y libapache2-mod-evasive
$ sudo mkdir -p /var/log/mod_evasive
$ sudo chown www-data:www-data /var/log/mod_evasive
```

```apache
# /etc/apache2/mods-available/evasive.conf
<IfModule mod_evasive20.c>
    DOSHashTableSize    3097
    DOSPageCount        20          # ★ 同一頁面在 DOSPageInterval 內的次數上限
    DOSPageInterval     1           # 秒
    DOSSiteCount        100         # ★ 同一站台在 DOSSiteInterval 內的次數上限
    DOSSiteInterval     1           # 秒
    DOSBlockingPeriod   60          # ★ 封鎖幾秒

    DOSLogDir           "/var/log/mod_evasive"
    DOSEmailNotify      admin@example.gov.tw
    # DOSSystemCommand  "sudo /usr/local/bin/block-ip %s"

    # ★ 白名單（監控主機、內部網段）
    DOSWhitelist        127.0.0.1
    DOSWhitelist        10.0.9.*
    DOSWhitelist        192.168.1.*
</IfModule>
```

```bash
$ sudo a2enmod evasive
$ sudo systemctl restart apache2

# 測試
$ for i in $(seq 1 60); do curl -s -o /dev/null -w '%{http_code} ' https://網站/; done
200 200 ... 403 403 403      # ★ 觸發後回 403

$ ls -l /var/log/mod_evasive/
dos-203.0.113.5
```

> [!warning] `mod_evasive` 的三個限制
> ```
> ① ★ 資料存在【單一程序】的記憶體中
>    → 多程序（prefork/event）時，每個程序各自計數
>      → 實際的閾值是【設定值 × 程序數】
>
> ② 重啟後計數歸零
>
> ③ 只能擋簡單的 flood，擋不住分散式攻擊
> ```
>
> **更可靠的做法**：
> ```
> ① fail2ban（依日誌封鎖，跨程序、可持久化）
> ② 前面加 Nginx 做 limit_req（★ 共享記憶體，計數準確）
> ③ CDN / 雲端 WAF
> ```

### `mod_ratelimit`：限制頻寬

```apache
# 限制下載速度
<Location /downloads/>
    SetOutputFilter RATE_LIMIT
    SetEnv rate-limit 512            # ★ 512 KB/s
    SetEnv rate-initial-burst 2048   # 前 2MB 全速
</Location>
```

```bash
$ sudo a2enmod ratelimit
```

### `mod_qos`（更完整的流量控制）

```bash
$ sudo apt install -y libapache2-mod-qos
```

```apache
<IfModule mod_qos.c>
    # ★ 每個 IP 最多 50 條連線
    QS_SrvMaxConnPerIP 50

    # ★ 保留 100 個連線給「行為正常」的客戶端
    QS_SrvMaxConnClose 80%

    # ★ 慢速客戶端偵測（防 Slowloris）
    QS_SrvMinDataRate 120 1500

    # 特定路徑的並發限制
    QS_LocRequestLimit /admin 10
    QS_LocRequestLimit /api 100
</IfModule>
```

---

## 效能設定

```apache
# ═══════════ /etc/apache2/conf-available/performance.conf ═══════════

# ── 檔案傳輸 ──
EnableSendfile On                    # ★ 零複製（網路檔案系統要設 Off）
EnableMMAP On                        # 記憶體映射（NFS 要設 Off）

# ── keepalive ──
KeepAlive On
KeepAliveTimeout 5                   # ★ event MPM 下可以短一點
MaxKeepAliveRequests 500

# ── DNS ──
HostnameLookups Off                  # ★ 一定要 Off（否則每個請求都做反向 DNS）

# ── 符號連結 ──
# ★ FollowSymLinks 比 SymLinksIfOwnerMatch 快（後者要額外 stat）
<Directory /var/www>
    Options +FollowSymLinks -SymLinksIfOwnerMatch
</Directory>

# ── AllowOverride ──
# ★ None 可以省下每個請求對每層目錄的 stat()
<Directory /var/www>
    AllowOverride None
</Directory>

# ── 日誌 ──
# ★ 靜態資源不記錄（可減少 80% 日誌量）
SetEnvIf Request_URI "\.(?:js|css|png|jpe?g|gif|webp|svg|ico|woff2?)$" dontlog
SetEnvIf Request_URI "^/(health|ping|metrics)$" dontlog
CustomLog ${APACHE_LOG_DIR}/access.log combined env=!dontlog

# ★ 帶效能欄位的日誌格式
LogFormat "%h %l %u %t \"%r\" %>s %O \"%{Referer}i\" \"%{User-Agent}i\" \
rt=%D us=%{ms}T host=%v proto=%H ssl=%{SSL_PROTOCOL}x" perf
# %D = 微秒；%{ms}T = 毫秒
```

> [!tip] Apache 日誌的時間欄位
> ```
> %D            處理時間（微秒）
> %T            處理時間（秒，整數）
> %{ms}T        處理時間（毫秒）★ 推薦
> %{us}T        處理時間（微秒）
> %O            送出的位元組數（含標頭）
> %B            回應體的位元組數
> %{SSL_PROTOCOL}x   TLS 版本
> %{SSL_CIPHER}x     加密套件
> %v            ServerName（★ 多站台必要）
> %p            埠
> ```
>
> ```bash
> # 分析最慢的請求
> $ awk '{for(i=1;i<=NF;i++) if($i ~ /^rt=/) print substr($i,4)/1000, $7}' \
>     /var/log/apache2/access.log | sort -rn | head -20
> ```

---

## 完整實戰範例

### 安全與效能稽核腳本

```bash
#!/usr/bin/env bash
# /usr/local/bin/apache-audit —— Apache 安全與效能稽核
D="${1:?用法: $0 <domain>}"
B="https://$D"
CTL=$(command -v apache2ctl || command -v apachectl)
FAIL=0; WARN=0
pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m⚠\033[0m %s\n' "$1"; WARN=$((WARN+1)); }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }

echo "═══════ Apache 稽核 $D ═══════"
sudo $CTL -t -D DUMP_CONFIG 2>/dev/null > /tmp/httpd-full.conf
chk() { grep -qiE "$1" /tmp/httpd-full.conf && pass "$2" || fail "$2"; }
neg() { grep -qiE "$1" /tmp/httpd-full.conf && fail "$2" || pass "$3"; }

echo -e "\n【1】★★ 敏感檔案"
for p in /.env /.git/config /.git/HEAD /composer.json /composer.lock \
         /package.json /artisan /Dockerfile /docker-compose.yml \
         /storage/logs/laravel.log /vendor/autoload.php /.htaccess \
         /phpinfo.php /info.php /README.md /web.config; do
    code=$(curl -sk -o /dev/null -w '%{http_code}' -m 5 "$B$p" 2>/dev/null)
    [ "$code" = "200" ] && fail "$p 【可以下載】"
done
[ "$FAIL" -eq 0 ] && pass "沒有可下載的敏感檔案"

echo -e "\n【2】★★ 上傳目錄執行"
for p in /uploads/test.php /uploads/x.php /storage/test.php \
         /uploads/image.jpg/x.php /index.php/x.php; do
    code=$(curl -sk -o /dev/null -w '%{http_code}' -m 5 "$B$p" 2>/dev/null)
    [ "$code" = "200" ] && fail "$p 【回 200】"
done
pass "上傳目錄檢查完成"

echo -e "\n【3】★ 預設頁面與資訊洩漏"
for p in /server-info /server-status /icons/ /manual/ /cgi-bin/ /~root/ \
         /icons/README /apache2-default/; do
    code=$(curl -sk -o /dev/null -w '%{http_code}' -m 5 "$B$p" 2>/dev/null)
    [ "$code" = "200" ] && fail "$p 【可存取】"
done
pass "預設路徑已封鎖"

echo -e "\n【4】版本與指紋"
srv=$(curl -skI -m 5 "$B/" | grep -i '^server:' | tr -d '\r')
echo "$srv" | grep -qiE 'apache/[0-9]' && fail "$srv 【洩漏版本 → ServerTokens Prod】" \
                                       || pass "${srv:-（無 Server 標頭）}"
for h in x-powered-by x-aspnet-version x-generator; do
    v=$(curl -skI -m 5 "$B/" | grep -i "^$h:" | tr -d '\r')
    [ -n "$v" ] && fail "$v"
done

echo -e "\n【5】安全標頭（多路徑驗證）"
for p in / /api/health /assets/app.css /nonexistent-404; do
    n=0
    hdr=$(curl -skI -m 5 "$B$p" 2>/dev/null)
    for h in x-frame-options x-content-type-options referrer-policy strict-transport-security; do
        echo "$hdr" | grep -qi "^$h:" && n=$((n+1))
    done
    [ "$n" -ge 4 ] && pass "$p → $n/4" || \
    { [ "$n" -ge 2 ] && warn "$p → $n/4（★ 檢查 always）" || fail "$p → $n/4"; }
done

echo -e "\n【6】HTTP 方法"
for m in TRACE TRACK DEBUG PROPFIND PUT DELETE; do
    code=$(curl -sk -o /dev/null -w '%{http_code}' -m 5 -X "$m" "$B/" 2>/dev/null)
    [ "$code" = "200" ] && fail "$m 可用"
done
pass "危險方法已封鎖"

echo -e "\n【7】目錄列表"
for p in /assets/ /uploads/ /images/ /js/ /css/; do
    curl -sk -m 5 "$B$p" 2>/dev/null | head -c 300 | grep -qi 'Index of' && fail "$p 【目錄列表】"
done
pass "沒有目錄列表"

echo -e "\n【8】設定檔"
chk '^\s*ServerTokens\s+Prod'      "ServerTokens Prod"
chk '^\s*ServerSignature\s+Off'    "ServerSignature Off"
chk '^\s*TraceEnable\s+Off'        "TraceEnable Off"
chk '^\s*HostnameLookups\s+Off'    "HostnameLookups Off"
chk 'RequestReadTimeout'           "RequestReadTimeout（防 Slowloris）"
chk 'LimitRequestBody'             "LimitRequestBody"
neg '^\s*Options[^-\n]*\bIndexes\b' "有 Options Indexes" "沒有 Options Indexes"
neg '^\s*Order\s+' "使用 2.2 舊語法 Order/Allow/Deny" "使用 2.4 Require 語法"
neg 'CacheIgnoreHeaders.*Set-Cookie' "★★ CacheIgnoreHeaders Set-Cookie【快取洩漏】" "快取設定安全"
neg 'ProxyPassMatch.*\\\.php' "使用 ProxyPassMatch【PathInfo 風險】" "使用 SetHandler"

echo -e "\n【9】模組"
for m in info status autoindex userdir cgi cgid include dav negotiation; do
    sudo $CTL -M 2>/dev/null | grep -q "${m}_module" && warn "$m 仍載入【建議停用】"
done
for m in headers rewrite ssl deflate expires reqtimeout proxy_fcgi; do
    sudo $CTL -M 2>/dev/null | grep -q "${m}_module" && pass "$m ✓" || warn "$m 未啟用"
done

echo -e "\n【10】MPM 與 PHP"
MPM=$(sudo $CTL -M 2>/dev/null | grep -oP 'mpm_\K\w+(?=_module)')
[ "$MPM" = "event" ] && pass "MPM: event" || warn "MPM: $MPM（建議 event）"
sudo $CTL -M 2>/dev/null | grep -q php_module && warn "mod_php 仍載入【建議 PHP-FPM】" \
                                              || pass "使用 PHP-FPM"
grep -qh '^\s*cgi.fix_pathinfo\s*=\s*0' /etc/php/*/fpm/php.ini /etc/php.ini 2>/dev/null \
  && pass "cgi.fix_pathinfo = 0" || fail "cgi.fix_pathinfo 不是 0"

echo -e "\n【11】壓縮"
for e in gzip br; do
    enc=$(curl -skI -m 5 -H "Accept-Encoding: $e" "$B/" | grep -i content-encoding | tr -d '\r')
    [ -n "$enc" ] && pass "$e: $enc" || warn "$e 未啟用"
done
curl -skI -m 5 "$B/" | grep -qi '^vary:.*accept-encoding' && pass "Vary: Accept-Encoding" \
                                                          || warn "缺 Vary: Accept-Encoding"

echo -e "\n【12】快取標頭"
for p in /index.html /favicon.ico; do
    cc=$(curl -skI -m 5 "$B$p" | grep -i '^cache-control' | tr -d '\r')
    printf '     %-20s %s\n' "$p" "${cc:-（無）}"
done
cc=$(curl -skI -m 5 "$B/index.html" | grep -i '^cache-control')
echo "$cc" | grep -qi 'no-store\|no-cache' && pass "index.html 不快取" \
                                           || fail "★ index.html 應設 no-store"

echo -e "\n【13】TLS"
for p in tls1 tls1_1; do
    echo | timeout 5 openssl s_client -"$p" -connect "$D:443" -servername "$D" >/dev/null 2>&1 \
      && fail "${p^^} 仍啟用" || pass "${p^^} 已關閉"
done
CH=$(echo | timeout 10 openssl s_client -connect "$D:443" -servername "$D" -showcerts 2>/dev/null | \
     grep -c 'BEGIN CERTIFICATE')
[ "$CH" -ge 2 ] && pass "憑證鏈完整（$CH）" || fail "憑證鏈不完整【用 fullchain.pem】"

echo -e "\n【14】效能"
sudo $CTL -M 2>/dev/null | grep -q http2_module && \
  { curl -sI --http2 -m 5 "$B/" | head -1 | grep -q 'HTTP/2' && pass "HTTP/2 ✓" || warn "HTTP/2 未生效"; }
for i in 1 2 3; do
    curl -sk -o /dev/null -w "     第 $i 次: connect=%{time_connect}s ttfb=%{time_starttransfer}s total=%{time_total}s\n" \
        -m 10 "$B/"
done

echo -e "\n【15】權限隔離"
U=$(grep -h '^\s*user\s*=' /etc/php/*/fpm/pool.d/*.conf /etc/php-fpm.d/*.conf 2>/dev/null | \
    grep -oP '=\s*\K\S+' | sort -u | wc -l)
S=$(sudo $CTL -S 2>&1 | grep -c namevhost)
[ "$U" -gt 1 ] || [ "$S" -le 1 ] && pass "PHP 使用者 $U 個 / 站台 $S 個" \
                                 || warn "★ $S 個站台共用 1 個 PHP 使用者"
grep -qh 'open_basedir' /etc/php/*/fpm/pool.d/*.conf /etc/php-fpm.d/*.conf 2>/dev/null \
  && pass "有設定 open_basedir" || warn "沒有 open_basedir"

rm -f /tmp/httpd-full.conf
echo -e "\n═══════ 結果 ═══════"
printf '  失敗 \033[31m%d\033[0m 項，警告 \033[33m%d\033[0m 項\n' "$FAIL" "$WARN"
echo
echo "  外部檢測："
echo "    SSL Labs         https://www.ssllabs.com/ssltest/analyze.html?d=$D"
echo "    Security Headers https://securityheaders.com/?q=$D"
exit $FAIL
```

```bash
# 排程化
$ sudo tee /etc/cron.d/apache-audit >/dev/null <<'EOF'
0 3 * * 1 root /usr/local/bin/apache-audit app.example.gov.tw > /var/log/apache-audit.log 2>&1 || \
  mail -s "【警告】Apache 稽核發現問題" admin@example.gov.tw < /var/log/apache-audit.log
EOF
```

---

## 常見錯誤與排錯

| 現象／問題 | 原因 | 解法 |
| --- | --- | --- |
| **`.env` / `.git` 可下載** ★★★ | DocumentRoot 錯 / 沒有 FilesMatch | `DocumentRoot .../public` + 全域 `<FilesMatch>` |
| **`/server-info` 洩漏完整設定** ★★ | `mod_info` 啟用 | `a2dismod info` |
| **上傳的 jpg 被執行** ★★★ | ProxyPassMatch / 沒禁止 | `SetHandler` + `cgi.fix_pathinfo=0` + 目錄禁止 |
| **安全標頭在 404 頁面消失** | 缺 `always` | `Header always set ...` |
| **壓縮沒生效** | 未載入 mod_deflate / MIME 不在清單 | `a2enmod deflate filter` |
| CDN 給錯壓縮版本 | 缺 `Vary: Accept-Encoding` | `Header append Vary Accept-Encoding` |
| **敏感 API 有 BREACH 風險** | 對含 token 的回應壓縮 | `SetEnv no-gzip 1` |
| **部署後白畫面** ★ | index.html 長期快取 | `Cache-Control: no-store` |
| **快取洩漏（A 看到 B 的頁面）** ★★ | `CacheIgnoreHeaders Set-Cookie` | **移除它**；登入路徑 `CacheDisable on` |
| **`mod_evasive` 閾值不準** | **資料在單一程序記憶體** | 實際閾值 = 設定值 × 程序數；改用 fail2ban |
| Slowloris 打垮服務 | 沒有 `RequestReadTimeout` | `a2enmod reqtimeout` + 設定 |
| **每個請求都很慢（+100ms）** | `HostnameLookups On` | **設成 `Off`** |
| 深層路徑特別慢 | `AllowOverride All` | 改成 `None` |
| **`Order`/`Allow` 與 `Require` 混用行為詭異** | `mod_access_compat` | 統一用 2.4 語法 |
| htcacheclean 沒跑，快取塞滿磁碟 | 服務沒啟用 | `systemctl enable --now apache-htcacheclean` |
| RHEL 上設定沒生效 | **SELinux / 加密政策** | `ausearch -m avc`；`update-crypto-policies --show` |

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> # ★ SELinux 是重要的一道防線，不要關掉
> $ getenforce
> Enforcing
>
> # 正確的 context
> $ sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/app/current/public(/.*)?"
> $ sudo semanage fcontext -a -t httpd_sys_rw_content_t "/var/www/app/shared/storage(/.*)?"
> $ sudo restorecon -Rv /var/www/app
>
> # ★ 上傳目錄設成唯讀 context —— 即使有 web shell 也寫不進去
> $ sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/app/current/public/uploads(/.*)?"
>
> # ★ 最小權限：不需要的布林值不要開
> $ getsebool -a | grep httpd | grep ' on$'
> $ sudo setsebool -P httpd_can_network_connect 1      # 只在需要時
> # httpd_can_sendmail、httpd_enable_cgi、httpd_unified 等不需要就【不要開】
>
> # 加密政策
> $ update-crypto-policies --show          # ★ 不要是 LEGACY
> $ sudo update-crypto-policies --set DEFAULT
>
> # firewalld
> $ sudo firewall-cmd --permanent --add-service=https
> $ sudo firewall-cmd --permanent --remove-service=http    # 若已全 HTTPS
> $ sudo firewall-cmd --reload
>
> # 快取目錄
> $ sudo mkdir -p /var/cache/httpd/proxy
> $ sudo chown -R apache:apache /var/cache/httpd
> $ sudo semanage fcontext -a -t httpd_cache_t "/var/cache/httpd(/.*)?"
> $ sudo restorecon -Rv /var/cache/httpd
> ```

---

## 安全性注意事項

> [!danger] 上線前必須全部通過的十項
> ```
> ① DocumentRoot 指向 public/（不是專案根目錄）
> ② .env / .git / composer.json 全部 403 或 404
> ③ 上傳目錄禁止執行 PHP（SetHandler none + Require all denied + AllowOverride None）
> ④ cgi.fix_pathinfo = 0
> ⑤ ServerTokens Prod / ServerSignature Off / TraceEnable Off
> ⑥ mod_info、mod_status、mod_autoindex 停用
> ⑦ 全域 <Directory /> 是 Require all denied
> ⑧ RequestReadTimeout（防 Slowloris）
> ⑨ 每個 location 都有完整的安全標頭（含 404 頁面）
> ⑩ SSL Labs A 以上、憑證鏈完整、deploy hook 存在
> ```

> [!warning] Apache 特有的安全考量
> **① `.htaccess` 是攻擊面**
> ```apache
> # 上傳目錄絕對要 AllowOverride None
> # 否則攻擊者寫入 .htaccess 就能讓 .jpg 被當成 PHP 執行
> ```
>
> **② `mod_info` 比任何東西都危險**
> ```
> /server-info 顯示【完整的設定檔內容】
>   → 所有路徑、所有模組、甚至設定檔中的密碼
> ```
>
> **③ 容器合併順序（`<Location>` 覆蓋 `<Directory>`）**
> ```apache
> # 存取控制不要分散在不同種容器
> # 設定完一定要【實際測試】而非看設定檔推論
> ```
>
> **④ 2.2 舊語法與 2.4 新語法混用**
> ```bash
> $ sudo apache2ctl -M | grep access_compat     # 載入了就有風險
> $ sudo apache2ctl -t -D DUMP_CONFIG | grep -cE '^\s*(Order|Allow from|Deny from)'
> ```

> [!tip] 縱深防禦：Apache 只是一層
> ```
> ① 網路層     防火牆、後端只綁 127.0.0.1
> ② 傳輸層     TLS 1.2+、HSTS、憑證鏈完整
> ③ ★ Apache   本篇的所有設定
> ④ PHP 層     open_basedir、disable_functions、獨立 pool 與使用者
> ⑤ WAF        ModSecurity + OWASP CRS
> ⑥ 應用層     輸入驗證、參數化查詢、授權檢查、CSRF token
> ⑦ 系統層     SELinux/AppArmor、最小權限、【定期更新】
> ⑧ 監控層     日誌集中、fail2ban、Wazuh
> ```
>
> **絕大多數的入侵不是因為設定不夠精巧，
> 而是因為跑著三年沒更新的軟體。**
> ```bash
> $ sudo apt install -y unattended-upgrades
> $ sudo dpkg-reconfigure -plow unattended-upgrades
> ```

---

## 速查表

### 安全加固基準

```apache
ServerTokens Prod
ServerSignature Off
TraceEnable Off
HostnameLookups Off
FileETag None
Timeout 30
KeepAliveTimeout 5
RequestReadTimeout header=20-40,MinRate=500 body=20,MinRate=500
LimitRequestBody 20971520
LimitRequestFields 100

<Directory />
    Options None
    AllowOverride None
    Require all denied
</Directory>

<FilesMatch "^\."> Require all denied </FilesMatch>
<FilesMatch "\.(env|log|sql|bak|ini|ya?ml|key|pem)$"> Require all denied </FilesMatch>
<DirectoryMatch "/(\.git|vendor|node_modules)/"> Require all denied </DirectoryMatch>

Header always set X-Frame-Options "SAMEORIGIN"
Header always set X-Content-Type-Options "nosniff"
Header always set Referrer-Policy "strict-origin-when-cross-origin"
Header always unset X-Powered-By
```

### 停用模組

```bash
sudo a2dismod info status autoindex userdir cgi cgid include dav dav_fs negotiation
sudo a2disconf serve-cgi-bin
sudo a2dissite 000-default
```

### 壓縮

```apache
AddOutputFilterByType DEFLATE text/html text/css application/javascript application/json image/svg+xml
DeflateCompressionLevel 5
SetEnvIfNoCase Request_URI \.(?:gif|jpe?g|png|zip|mp4|pdf|woff2)$ no-gzip dont-vary
Header append Vary Accept-Encoding env=!dont-vary

# brotli（2.4.26+）
AddOutputFilterByType BROTLI_COMPRESS text/html text/css application/javascript
BrotliCompressionQuality 5

# ★ 敏感 API 關閉（BREACH）
<LocationMatch "^/api/(auth|payment)"> SetEnv no-gzip 1 </LocationMatch>
```

### 快取

```apache
ExpiresActive On
ExpiresByType image/png "access plus 1 month"
ExpiresByType text/html "access plus 0 seconds"

<FilesMatch "\.[0-9a-f]{8,}\.(js|css|woff2)$">
    Header always set Cache-Control "public, max-age=31536000, immutable"
    FileETag None
</FilesMatch>
<FilesMatch "^(index\.html|sw\.js)$">
    Header always set Cache-Control "no-store, no-cache, must-revalidate"    # ★★
</FilesMatch>
<LocationMatch "^/api/"> Header always set Cache-Control "no-store, private" </LocationMatch>
```

### mod_cache

```apache
CacheRoot /var/cache/apache2/mod_cache_disk
<LocationMatch "^/(news|public-api)/">
    CacheEnable disk
    CacheHeader on
    CacheLock on                      # 防雪崩
    CacheStaleOnError on              # 後端掛了用舊快取
</LocationMatch>
<LocationMatch "^/(admin|api/user|dashboard)"> CacheDisable on </LocationMatch>

❌❌ CacheIgnoreHeaders Set-Cookie    ← 快取洩漏
```

```bash
sudo systemctl enable --now apache-htcacheclean
curl -sI https://D/news/1 | grep -i x-cache      # HIT / MISS
```

### DoS 防護

```apache
# mod_evasive（★ 計數在單一程序，實際閾值 = 設定 × 程序數）
DOSPageCount 20 ; DOSPageInterval 1
DOSSiteCount 100 ; DOSSiteInterval 1
DOSBlockingPeriod 60
DOSWhitelist 10.0.9.*

# mod_reqtimeout（★ 防 Slowloris）
RequestReadTimeout header=20-40,MinRate=500 body=20,MinRate=500

# mod_ratelimit
<Location /downloads/>
    SetOutputFilter RATE_LIMIT
    SetEnv rate-limit 512
</Location>
```

```
★ 更可靠：fail2ban（跨程序、持久化）／前面加 Nginx limit_req／CDN WAF
```

### 效能

```apache
EnableSendfile On
EnableMMAP On
HostnameLookups Off             # ★ 一定要 Off
AllowOverride None              # ★ 省下每請求對每層目錄的 stat()
Options +FollowSymLinks -SymLinksIfOwnerMatch

SetEnvIf Request_URI "\.(js|css|png|jpe?g|woff2)$" dontlog
CustomLog ${APACHE_LOG_DIR}/access.log combined env=!dontlog

LogFormat "%h %l %u %t \"%r\" %>s %O rt=%D host=%v ssl=%{SSL_PROTOCOL}x" perf
# %D 微秒 · %{ms}T 毫秒 · %v ServerName
```

### 上線前十項 ★

```
□ DocumentRoot 指向 public/
□ .env / .git / composer.json → 403/404
□ 上傳目錄禁止執行 PHP
□ cgi.fix_pathinfo = 0
□ ServerTokens Prod / ServerSignature Off / TraceEnable Off
□ mod_info / mod_status / mod_autoindex 停用
□ <Directory /> 是 Require all denied
□ RequestReadTimeout（防 Slowloris）
□ 每個路徑（含 404）都有完整安全標頭
□ SSL Labs A 以上 + 憑證鏈完整 + deploy hook
```

### 驗證

```bash
for p in /.env /.git/config /server-info /server-status /uploads/x.php; do
  curl -sk -o /dev/null -w "$p %{http_code}\n" https://D$p
done                                              # ★ 全部 403/404

curl -skI https://D/nonexistent | grep -icE 'x-frame|x-content|referrer'   # ★ 應為 3
curl -sI -H 'Accept-Encoding: br' https://D/ | grep -i content-encoding
sudo apache2ctl -t -D DUMP_CONFIG | grep -cE '^\s*(Order|Allow from)'      # 應為 0
```

---

## 練習題

> [!question]- 練習 1：完整稽核與修正
> 1. 對測試環境執行 `apache-audit` 腳本
> 2. **逐項修正所有失敗與警告**
> 3. 重跑，直到 0 失敗
> 4. 到 SSL Labs、Security Headers、Mozilla Observatory 檢測
> 5. **目標：SSL Labs A+、Security Headers A**
> 6. 把腳本排程化

> [!question]- 練習 2：Slowloris 防護驗證
> **★ 只在測試環境**
> 1. **先移除** `RequestReadTimeout`
> 2. `sudo apt install -y slowhttptest`
> 3. `slowhttptest -c 1000 -H -i 10 -r 200 -u https://測試站台/ -x 24 -p 3`
> 4. **觀察 "service available" 是否變成 NO**
> 5. 同時看 `server-status` 的 Scoreboard（**大量 `R` 嗎？**）
> 6. 加上 `RequestReadTimeout` + `mod_qos` 的 `QS_SrvMinDataRate`
> 7. **重測，確認一直是 YES**

> [!question]- 練習 3：壓縮效果測量
> 1. 對一個真實的 JS bundle 測三種大小（identity / gzip / br）
> 2. 測不同 `DeflateCompressionLevel`（1、5、9）的**大小與 CPU 時間**
> 3. 設定預壓縮（`.gz` / `.br` 檔 + RewriteRule）
> 4. **比較「即時壓縮」與「預壓縮」的回應時間**
> 5. **結論：哪個等級最划算？預壓縮省了多少？**

> [!question]- 練習 4：快取洩漏測試
> 1. 設定 `mod_cache` 快取 `/dashboard`
> 2. **故意加上** `CacheIgnoreHeaders Set-Cookie`
> 3. 用使用者 A 的 session 存取 → 記下內容
> 4. **用無痕視窗存取同一個 URL** → 看到 A 的資料了嗎？
> 5. 移除該設定，加上 `CacheDisable on`
> 6. **重測**
> 7. 寫一個自動化檢查加進部署流程

> [!question]- 練習 5：效能設定的實際影響
> 逐項測量（每項都用 `ab -n 5000 -c 50`）：
> 1. `HostnameLookups On` vs `Off` → **差多少？**
> 2. `AllowOverride All` vs `None`（用 5 層深的路徑）
> 3. 壓縮開 vs 關（比較傳輸量與 CPU）
> 4. `KeepAlive On` vs `Off`
> 5. **哪一項的影響最大？**

---

## 小測驗

Q1. **Apache 安全加固的前六項設定是什麼**？

Q2. **哪三個模組一定要停用？各自洩漏什麼**？

Q3. **`RequestReadTimeout` 防的是什麼攻擊？參數的意義是什麼**？

Q4. **`Header append Vary Accept-Encoding` 為什麼重要？哪些檔案不該壓縮**？

Q5. **`index.html` 設成長期快取會造成什麼災難**？

Q6. **`CacheIgnoreHeaders Set-Cookie` 為什麼絕對不能設**？

Q7. **`mod_evasive` 有哪三個限制？更可靠的替代方案是什麼**？

Q8. **`HostnameLookups On` 為什麼會嚴重影響效能**？

Q9. **`AllowOverride None` 的效能好處來自哪裡**？

Q10. **上線前必須通過的十項檢查是什麼**？

> [!question]- 測驗答案
> **Q1.** ①**`ServerTokens Prod` + `ServerSignature Off`**（隱藏版本與簽章）；
> ②**全域 `<Directory /> Options None / AllowOverride None / Require all denied </Directory>`**
> （預設拒絕，再逐一開放）；
> ③**`TraceEnable Off`**（防 Cross-Site Tracing）；
> ④**逾時設定**（`Timeout 30`、`KeepAliveTimeout 5`、
> **`RequestReadTimeout header=20-40,MinRate=500 body=20,MinRate=500`** 防 Slowloris）；
> ⑤**限制請求大小**（`LimitRequestBody`、`LimitRequestFields`、`LimitRequestLine`）；
> ⑥**`FileETag None`**（避免洩漏 inode）。
> 另外加上安全標頭（`Header always set ...`）與
> 拒絕敏感檔案的 `<FilesMatch>` / `<DirectoryMatch>`。
>
> **Q2.** ①**`mod_info`（`/server-info`）** —— **最危險**，
> 顯示 **Apache 的完整設定檔內容**：所有 VirtualHost、DocumentRoot 路徑、
> 已載入模組，**甚至設定檔中的密碼**；
> ②**`mod_status`（`/server-status`）** ——
> 洩漏**所有正在處理的 URL（含查詢字串中的 token）**、
> 客戶端 IP、虛擬主機清單、伺服器狀態與版本；
> ③**`mod_autoindex`** —— **開啟目錄列表**。
> 另建議停用 `userdir`、`cgi`/`cgid`、`include`（SSI）、
> `dav`/`dav_fs`（WebDAV）、`negotiation`（MultiViews）。
>
> **Q3.** 防的是 **Slowloris 與 Slow POST 慢速攻擊** ——
> 攻擊者開很多連線，每個都只送半個標頭（或宣告很大的 Content-Length
> 然後每秒只送 1 byte），**每條連線佔用一個 worker slot 數小時**，
> 直到 worker 用完，**正常使用者連不進來**。
> **參數意義**：
> ```apache
> RequestReadTimeout header=20-40,MinRate=500 body=20,MinRate=500
> ```
> `header=20-40` 表示**標頭必須在 20 秒內收完，
> 但只要維持 `MinRate=500`（每秒至少 500 bytes）就可以延長，最多到 40 秒**；
> `body=20,MinRate=500` 對 request body 同理。
> 需要 `a2enmod reqtimeout`。
>
> **Q4.** `Vary: Accept-Encoding` 告訴 **CDN 與中間代理
> 「這個回應會依 Accept-Encoding 而不同，要分開快取」**。
> **沒有它**，CDN 可能把「未壓縮的版本」快取起來給支援壓縮的使用者（浪費頻寬），
> 或反過來**把 gzip 版本給不支援壓縮的客戶端（畫面全亂碼）**。
> **不該壓縮的**：①**已經壓縮過的格式**
> （jpg、png、webp、gif、mp4、zip、gz、pdf、**woff2**）——
> 壓不動只浪費 CPU；
> ②**含有機密（CSRF token / session）的動態回應** —— **BREACH 攻擊**風險，
> 敏感 API 要 `SetEnv no-gzip 1`。
>
> **Q5.** 部署新版後，**使用者的瀏覽器在快取有效期內都拿不到新的 `index.html`**，
> 而**舊的 `index.html` 引用的是已經被刪除的舊 hash JS 檔案** →
> **網站完全白畫面**。
> 更糟的是**叫使用者「清快取」也未必有用**（CDN 也快取了），
> 而且你無法主動讓已發出去的快取失效，只能等它自然過期。
> ```apache
> <FilesMatch "^(index\.html|sw\.js|manifest\.json)$">
>     Header always set Cache-Control "no-store, no-cache, must-revalidate, max-age=0"
> </FilesMatch>
> ```
>
> **Q6.** 因為 **`Set-Cookie` 標頭是 Apache 判斷「這個回應是個人化的、不該快取」
> 的重要依據** ——
> 忽略它之後，**帶有個人 session 的頁面會被存進共用快取**：
> ```
> 使用者 A 登入後存取 /dashboard → 被快取
>   → 使用者 B 存取同一個 URL → 【拿到 A 的姓名、身分證字號等個資】
> ```
> **正確做法**：尊重後端的 `Set-Cookie` 與 `Cache-Control`，
> 並對登入相關路徑明確 `CacheDisable on`。
> **驗證**：用 A 的 session 與無 session 分別存取同一 URL，比對內容是否相同。
>
> **Q7.** ①**★ 計數資料存在「單一程序」的記憶體中** ——
> 多程序（prefork / event）時每個程序各自計數，
> **實際的觸發閾值變成「設定值 × 程序數」**，遠比你設定的寬鬆；
> ②**Apache 重啟後計數歸零**；
> ③**只能擋簡單的單源 flood，擋不住分散式攻擊**。
> **更可靠的替代方案**：
> ①**fail2ban**（依日誌封鎖，跨程序、可持久化、能寫進防火牆）；
> ②**前面加一層 Nginx 做 `limit_req`**（★ 用共享記憶體，計數準確）；
> ③**CDN / 雲端 WAF**。
>
> **Q8.** 因為 `HostnameLookups On` 會讓 Apache **對每一個請求的客戶端 IP
> 做一次反向 DNS 查詢（PTR）**，才能在日誌中寫入主機名。
> **反向 DNS 查詢是網路操作，可能耗時數十到數百毫秒，
> 而且很多 IP 根本沒有 PTR 記錄（要等到逾時）** ——
> 這會直接加在每個請求的處理時間上。
> **一定要設成 `Off`**（這也是預設值）。
> 若真的需要主機名，**在離線分析日誌時再解析**
> （Apache 有提供 `logresolve` 工具）。
>
> **Q9.** 因為 `AllowOverride` 不是 `None` 時，
> **Apache 在「每一個請求」都要對「路徑上的每一層目錄」執行 `stat()`
> 去尋找 `.htaccess`**，
> 而且**這個結果無法快取**（因為 `.htaccess` 可能隨時被修改）。
> 一個 5 層深的路徑就是 5-6 次額外的系統呼叫，
> 高流量下累積起來相當可觀（實測可差 20-25% 的 QPS）。
> `AllowOverride None` 讓 Apache **完全跳過這個搜尋**。
> 附帶的安全好處是**開發者無法用 `.htaccess` 覆蓋你的安全設定**。
>
> **Q10.** ①**DocumentRoot 指向 `public/`**（不是專案根目錄）；
> ②**`.env` / `.git` / `composer.json` 全部 403 或 404**；
> ③**上傳目錄禁止執行 PHP**（`SetHandler none` + `Require all denied`
> + **`AllowOverride None`**）；
> ④**`cgi.fix_pathinfo = 0`**；
> ⑤**`ServerTokens Prod` / `ServerSignature Off` / `TraceEnable Off`**；
> ⑥**`mod_info`、`mod_status`、`mod_autoindex` 停用**；
> ⑦**全域 `<Directory />` 是 `Require all denied`**；
> ⑧**`RequestReadTimeout`**（防 Slowloris）；
> ⑨**每個路徑（含 404 頁面）都有完整的安全標頭**（`always`）；
> ⑩**SSL Labs A 以上、憑證鏈完整（`fullchain.pem`）、deploy hook 存在**。
> 建議把這十項寫成自動化腳本，**每次部署後都跑一次**。

---

## 延伸閱讀

- [[06-Apache-與PHP整合]] — PHP 層的加固與權限隔離
- [[03-Apache-模組與MPM]] — MPM 調校與 MaxRequestWorkers
- [[05-Apache-HTTPS設定]] — TLS 與憑證
- [[09-Nginx-安全設定]] — 通用的 Web 安全觀念
- [[00-ModSecurity-索引]] — WAF（Apache 之上的一層）
- [[05-Fail2ban入侵防護]] — 依日誌自動封鎖
- [[04-Nginx與Apache選型與共存]] — 兩者並用的架構
