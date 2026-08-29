---
title: "MyGuard 實戰組合"
desc: "從零建置一台整合 autocert、shield、cache-turbo 的 LXMP 伺服器"
aliases: [MyGuard 實戰, 完整組合, LXMP, Docker 映像]
tags: [群組/軟體與開發工具, 服務/nginx, 服務/myguard, 主題/LXMP, 主題/實戰]
category: MyGuard與Angie
difficulty: 專家
status: 完成
distro: [ubuntu]
prerequisites: ["[[060-02-05-07-guide-MyGuard-動態模組管理]]", "[[130-01-05-06-guide-Vue-Laravel完整部署實戰]]"]
updated: 2026-08-28
---

# MyGuard 實戰組合

> [!abstract] 這篇你會學到
> - **★★★★ 從裸機到上線**的完整流程（★ 整合前七篇）
> - 三種情境的完整設定：**傳統網站 / API / SPA + Laravel**
> - **★★★★ 分階段上線的節奏**（★ detect → block）
> - Docker 映像的用法
> - **★★★★ 上線前的完整驗收清單**
> - 日常維運與監控
> - **★★★ 退場方案**

> [!warning] 未實機驗證 ★★★
> ```
> ★★★ 本章整合前七篇的內容，指令參數依 2026 年 8 月的官方文件。
> ★★★★ 實作前請對照各模組的官方 README。
> ★★ 建議先在測試環境完整跑過一次。
> ```

## 前置知識

- [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]] ~ [[060-02-05-07-guide-MyGuard-動態模組管理]] — **★★★ 前七篇**
- [[130-01-05-06-guide-Vue-Laravel完整部署實戰]] — LXMP 的部署流程

---

## ★★★★ 整體架構

```
★★★★ 一台整合了 MyGuard 模組的 LXMP 伺服器：

  網際網路
     │
     ▼
  ┌─────────────────────────────────────────────────────────┐
  │ ★★★ 防火牆（nftables）                                   │
  │   只開 22（限來源）/ 80 / 443                            │
  └──────────────────────┬──────────────────────────────────┘
                         ▼
  ┌─────────────────────────────────────────────────────────┐
  │ ★★★★ NGINX（MyGuard 強化版）                             │
  │                                                          │
  │  ① ★★★★ autocert    → 自動申請與續期憑證（免 certbot）   │
  │  ② ★★★★ shield      → 攔截已知漏洞利用（★ 第一道）       │
  │  ③ ★★★ error-abuse  → 錯誤率限流（★ 擋掃描器）           │
  │  ④ ★★★ cache-turbo  → 邊緣快取（SWR + single-flight）    │
  │  ⑤ ★★ strip-filter  → 回應精簡                           │
  │  ⑥ ★★★ brotli/zstd  → 壓縮                               │
  │  ⑦ ★★ ModSecurity   → 深度 WAF（★ 選用，第二道）         │
  └──────────────────────┬──────────────────────────────────┘
                         ▼
  ┌─────────────────────────────────────────────────────────┐
  │ ★★★ PHP-FPM（Laravel）                                   │
  └──────────────────────┬──────────────────────────────────┘
                         ▼
  ┌─────────────────────────────────────────────────────────┐
  │ MySQL + Redis                                            │
  └─────────────────────────────────────────────────────────┘

★★★★ 每一層的職責：
  shield       擋【已知的漏洞利用】（誤判極低，可以直接 block）
  error-abuse  擋【行為異常的來源】（大量 404 = 掃描器）
  ModSecurity  擋【未知的攻擊模式】（★ 需要長期調校）
  cache-turbo  ★★★ 擋掉大部分打向 PHP 的請求
  autocert     ★★★★ 讓 HTTPS 完全自動化
```

---

## ★★★★ 完整安裝腳本

```bash
#!/usr/bin/env bash
# ★★★★ /usr/local/bin/setup-myguard-lxmp
# 從裸機 Ubuntu 24.04 建置整合 MyGuard 的 LXMP 伺服器
set -euo pipefail

DOMAIN="${1:?用法: setup-myguard-lxmp <網域> <管理員信箱>}"
EMAIL="${2:?}"
APP_DIR=/var/www/app
PHP_V=8.3

echo "═══ MyGuard LXMP 建置：$DOMAIN ═══"

# ═══ ★★★【1】系統基礎 ═══
echo -e "\n【1】系統基礎"
sudo apt update
sudo apt install -y curl gnupg ca-certificates lsb-release \
                    ufw fail2ban jq git unzip

sudo timedatectl set-timezone Asia/Taipei
sudo timedatectl set-ntp true

# ★★★ 提高 fd 上限
sudo tee /etc/sysctl.d/60-nginx.conf >/dev/null <<'EOF'
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.core.netdev_max_backlog = 16384
net.ipv4.tcp_syncookies = 1
net.ipv4.ip_local_port_range = 10240 65535
net.ipv4.tcp_tw_reuse = 1
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
EOF
sudo sysctl --system >/dev/null

# ═══ ★★★★【2】MyGuard 套件庫 ═══
echo -e "\n【2】★★★★ MyGuard 套件庫"
CODENAME=$(lsb_release -cs)
KEYRING=/etc/apt/keyrings/deb.myguard.nl.gpg

sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://deb.myguard.nl/deb.myguard.nl.gpg | sudo tee "$KEYRING" >/dev/null
sudo chmod 644 "$KEYRING"

echo "  ★★★★ 金鑰指紋（請與 https://deb.myguard.nl/how-to-use/ 比對）："
gpg --show-keys --with-fingerprint "$KEYRING" 2>/dev/null | sed 's/^/    /'
read -rp "  指紋正確嗎？[y/N] " a
[ "$a" = y ] || { sudo rm -f "$KEYRING"; echo "  ★★ 已中止"; exit 1; }

echo "deb [arch=amd64 signed-by=$KEYRING] \
https://deb.myguard.nl/apt/nginx/$CODENAME $CODENAME main" \
  | sudo tee /etc/apt/sources.list.d/myguard-nginx.list >/dev/null

# ★★★★ pinning：不讓第三方套件庫取代系統套件
sudo tee /etc/apt/preferences.d/myguard >/dev/null <<'EOF'
Package: nginx nginx-* libnginx-mod-*
Pin: origin deb.myguard.nl
Pin-Priority: 700

Package: *
Pin: origin deb.myguard.nl
Pin-Priority: 100
EOF

sudo apt update

# ═══ ★★★【3】NGINX 與模組 ═══
echo -e "\n【3】NGINX 與模組"
sudo apt install -y nginx \
    libnginx-mod-http-autocert \
    libnginx-mod-http-shield \
    libnginx-mod-http-error-abuse \
    libnginx-mod-http-cache-turbo \
    libnginx-mod-http-strip-filter \
    libnginx-mod-http-brotli-filter \
    libnginx-mod-http-brotli-static \
    libnginx-mod-http-zstd-filter \
    libnginx-mod-http-zstd-static \
  || echo "  ★★★ 部分模組安裝失敗，用 apt-cache search 確認名稱"

nginx -v
echo "  ── 載入的模組 ──"
ls -1 /etc/nginx/modules-enabled/ | sed 's/^/    /'

# ═══ ★★★【4】PHP-FPM ═══
echo -e "\n【4】PHP-FPM $PHP_V"
sudo apt install -y "php$PHP_V-fpm" "php$PHP_V-cli" \
    "php$PHP_V-mysql" "php$PHP_V-redis" "php$PHP_V-mbstring" \
    "php$PHP_V-xml" "php$PHP_V-curl" "php$PHP_V-zip" \
    "php$PHP_V-bcmath" "php$PHP_V-gd" "php$PHP_V-intl" "php$PHP_V-opcache"

sudo tee "/etc/php/$PHP_V/fpm/conf.d/99-app.ini" >/dev/null <<'EOF'
; ★★★ 安全
expose_php = Off
display_errors = Off
display_startup_errors = Off
log_errors = On
error_log = /var/log/php-fpm-error.log
cgi.fix_pathinfo = 0
allow_url_include = Off
disable_functions = exec,passthru,shell_exec,system,proc_open,popen

; ★★★ 效能
memory_limit = 256M
max_execution_time = 60
upload_max_filesize = 20M
post_max_size = 24M
realpath_cache_size = 4096K
realpath_cache_ttl = 600

; ★★★★ OPcache
opcache.enable = 1
opcache.memory_consumption = 256
opcache.interned_strings_buffer = 16
opcache.max_accelerated_files = 20000
opcache.validate_timestamps = 0
opcache.save_comments = 1
EOF

# ═══ ★★★【5】MySQL 與 Redis ═══
echo -e "\n【5】MySQL 與 Redis"
sudo apt install -y mysql-server redis-server

sudo tee /etc/redis/redis.conf.d/99-security.conf >/dev/null 2>&1 || true
sudo sed -i 's/^bind .*/bind 127.0.0.1 ::1/' /etc/redis/redis.conf
sudo sed -i 's/^# *requirepass .*/requirepass '"$(openssl rand -base64 32)"'/' /etc/redis/redis.conf
sudo systemctl restart redis-server

# ═══ ★★★★【6】NGINX 主設定 ═══
echo -e "\n【6】★★★★ NGINX 主設定"
sudo cp /etc/nginx/nginx.conf "/etc/nginx/nginx.conf.orig-$(date +%F)"
sudo tee /etc/nginx/nginx.conf >/dev/null <<'NGINXEOF'
user www-data;
worker_processes auto;
worker_rlimit_nofile 65536;
pid /run/nginx.pid;

# ★★★★ 模組載入（main context，http 之前）
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 8192;
    multi_accept on;
    use epoll;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # ═══ ★★★ 基本 ═══
    server_tokens off;
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    keepalive_requests 1000;
    client_max_body_size 20m;
    client_body_timeout 30s;
    client_header_timeout 30s;
    send_timeout 30s;
    types_hash_max_size 4096;
    server_names_hash_bucket_size 128;

    # ═══ ★★★★ 真實 IP（★ 在 CDN/LB 後面時必要）═══
    # set_real_ip_from 10.10.20.0/24;
    # real_ip_header X-Forwarded-For;
    # real_ip_recursive on;

    # ═══ ★★★★ DNS（autocert 必要）═══
    resolver 1.1.1.1 8.8.8.8 valid=300s ipv6=off;
    resolver_timeout 5s;

    # ═══ ★★★★ autocert ═══
    autocert_contact ADMIN_EMAIL;
    autocert_key_type p384 rsa2048;
    autocert_challenge http-01;
    autocert_renew_before 21d;
    # ★★★★ 第一次上線先開 staging！
    autocert_staging on;

    # ═══ ★★★★ shield（★ 先 detect）═══
    shield detect;
    shield_body on;
    shield_max_body 8k;
    shield_status 403;
    shield_log /var/log/nginx/shield.json;
    shield_ban_zone shield:10m;

    # ═══ ★★★ error-abuse（★ 先 dry_run）═══
    error_abuse_zone zone=ea:10m
                     statuses=403,404,500-599
                     interval=300s
                     threshold=100
                     block=60m
                     persist=/var/lib/nginx/error-abuse.state
                     persist_interval=5s;

    # ═══ ★★★ cache-turbo ═══
    cache_turbo_zone name=ct 256m;

    map $http_cookie $is_logged_in {
        default              0;
        "~*laravel_session"  1;
        "~*remember_web_"    1;
    }
    map $request_method $not_cacheable {
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

    # ═══ ★★ 精簡 ═══
    strip on;
    strip_css on;
    strip_json on;
    strip_js on;
    strip_min_size 1k;
    strip_max_size 1m;

    # ═══ ★★★ 日誌 ═══
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" "$http_user_agent" '
                    'rt=$request_time urt=$upstream_response_time '
                    'cache=$cache_turbo_status ea=$error_abuse_status '
                    'enc=$http_content_encoding';
    access_log /var/log/nginx/access.log main;
    error_log  /var/log/nginx/error.log warn;

    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
NGINXEOF
sudo sed -i "s/ADMIN_EMAIL/$EMAIL/" /etc/nginx/nginx.conf

# ═══ ★★★ 安全標頭 snippet ═══
sudo install -d /etc/nginx/snippets
sudo tee /etc/nginx/snippets/security-headers.conf >/dev/null <<'EOF'
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
EOF

sudo install -d -m 750 -o www-data -g www-data /var/lib/nginx

# ═══ ★★★★【7】防火牆 ═══
echo -e "\n【7】防火牆"
sudo ufw --force reset >/dev/null
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp comment 'SSH'
sudo ufw allow 80/tcp comment 'HTTP (autocert)'
sudo ufw allow 443/tcp comment 'HTTPS'
sudo ufw --force enable
sudo ufw status numbered

echo -e "\n★ 基礎建置完成"
echo "★★★ 下一步："
echo "  ① 建立站台設定（見下方範本）"
echo "  ② sudo nginx -t && sudo systemctl reload nginx"
echo "  ③ ★★★★ 確認 staging 憑證申請成功後，關掉 autocert_staging"
echo "  ④ ★★★★ shield 與 error-abuse 觀察一週後才切成 block"
```

---

## ★★★★ 情境一：傳統 PHP 網站

```nginx
# /etc/nginx/sites-available/app.conf
server {
    listen 80;
    listen [::]:80;
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name app.example.gov.tw www.app.example.gov.tw;

    # ═══ ★★★★ 自動憑證（★ 取代 certbot）═══
    autocert on;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:20m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;
    ssl_stapling on;
    ssl_stapling_verify on;

    include snippets/security-headers.conf;

    root /var/www/app/current/public;
    index index.php index.html;

    charset utf-8;
    access_log /var/log/nginx/app-access.log main;
    error_log  /var/log/nginx/app-error.log warn;

    # ═══ ★★★★ 一般流量 ═══
    location / {
        shield detect;                                # ★★★★ 上線初期用 detect
        shield_ban zone=shield count=10 window=1m bantime=1h;
        error_abuse zone=ea dry_run=on;               # ★★★★ 上線初期用 dry_run

        cache_turbo ct;
        cache_turbo_valid 60s;
        cache_turbo_valid 404 1m;
        cache_turbo_key $host$uri$cache_turbo_normalized_args;
        cache_turbo_normalize_strip utm_source utm_medium utm_campaign
                                    fbclid gclid "tmp_*";
        cache_turbo_stale_while_revalidate 4m;
        cache_turbo_stale_if_error 24h;
        cache_turbo_lock_ttl 5s;
        # ★★★★★ 個資外洩防護（三層）
        cache_turbo_bypass   $is_logged_in $not_cacheable $http_authorization;
        cache_turbo_no_store $is_logged_in $not_cacheable $http_authorization;
        cache_turbo_cache_control honor;
        add_header X-Cache $cache_turbo_status always;

        try_files $uri $uri/ /index.php?$query_string;
    }

    # ═══ ★★★ 靜態資源（★ 不需要 shield / cache-turbo）═══
    location ~* \.(?:css|js|svg|woff2?|ttf|eot)$ {
        shield off;
        strip off;
        gzip_static on;
        brotli_static on;
        zstd_static on;
        expires 1y;
        add_header Cache-Control "public, immutable" always;
        add_header Vary "Accept-Encoding" always;
        access_log off;
    }

    location ~* \.(?:jpg|jpeg|png|gif|webp|avif|ico|mp4|webm)$ {
        shield off;
        strip off;
        gzip off; brotli off; zstd off;
        expires 30d;
        add_header Cache-Control "public" always;
        access_log off;
    }

    # ═══ ★★★★ PHP ═══
    location ~ \.php$ {
        shield detect;
        shield_ban zone=shield count=5 window=1m bantime=2h;
        error_abuse zone=ea dry_run=on;

        try_files $uri =404;                          # ★★★★ 防 PathInfo RCE
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
        fastcgi_param DOCUMENT_ROOT   $realpath_root;
        fastcgi_param HTTPS on;                       # ★★★★ Laravel 需要
        fastcgi_read_timeout 60s;
        fastcgi_buffers 16 16k;
        fastcgi_buffer_size 32k;
        include fastcgi_params;
        include snippets/security-headers.conf;       # ★★★★ add_header 陣列繼承
    }

    # ═══ ★★★ 隱藏檔與敏感路徑 ═══
    location ~ /\. {
        deny all;
        return 404;
    }
    location ~* \.(?:env|log|sql|bak|orig|swp|save)$ {
        deny all;
        return 404;
    }

    # ═══ ★★ 狀態端點（★ 只給本機與監控）═══
    location = /shield-status {
        shield_ban_status shield;
        allow 127.0.0.1; allow 10.10.20.50; deny all;
        access_log off;
    }
    location = /_cache-admin {
        cache_turbo_admin_path /_cache-admin;
        allow 127.0.0.1; allow 10.10.20.0/24; deny all;
        access_log off;
    }
    location = /fpm-status {
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $fastcgi_script_name;
        include fastcgi_params;
        allow 127.0.0.1; deny all;
        access_log off;
    }
}
```

---

## ★★★★ 情境二：純 API

```nginx
# /etc/nginx/sites-available/api.conf
server {
    listen 80;
    listen 443 ssl;
    http2 on;
    server_name api.example.gov.tw;

    autocert on;

    ssl_protocols TLSv1.2 TLSv1.3;
    include snippets/security-headers.conf;
    add_header X-Frame-Options "DENY" always;         # ★★★ API 不該被嵌入

    root /var/www/api/current/public;

    access_log /var/log/nginx/api-access.log main;

    # ═══ ★★★★ API 主要路徑 ═══
    location / {
        shield block;                                  # ★★★ API 可以較早 block
        shield_max_body 32k;                           # ★★ API 的 body 較大
        shield_ban zone=shield count=5 window=1m bantime=2h;

        error_abuse zone=ea status=429;                # ★★★ API 用 429 較合適

        # ★★★★ API 通常【不做 HTML 快取】
        # 但可以精簡與壓縮 JSON
        strip_json on;

        try_files $uri /index.php?$query_string;
    }

    # ═══ ★★★ 上傳：不掃 body ═══
    location = /api/upload {
        shield block;
        shield_body off;                               # ★★★★ 二進位不用掃
        error_abuse zone=ea;
        client_max_body_size 50m;
        client_body_timeout 300s;
        try_files $uri /index.php?$query_string;
    }

    # ═══ ★★★ 健康檢查：完全不擋 ═══
    location = /api/health/live {
        shield off;
        error_abuse off;
        access_log off;
        try_files $uri /index.php?$query_string;
    }

    # ═══ ★★★★ PHP ═══
    location ~ \.php$ {
        try_files $uri =404;
        fastcgi_pass unix:/run/php/php8.3-fpm-api.sock;
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
        fastcgi_param HTTPS on;
        fastcgi_read_timeout 60s;
        include fastcgi_params;
        include snippets/security-headers.conf;
    }

    location ~ /\. { deny all; return 404; }
}
```

```
★★★★ API 與網站的三個設定差異：

  ① ★★★ shield 可以較早進入 block
     → API 的請求格式固定，誤判機率低
     → ★★ 但 shield_max_body 要調大（JSON 可能較長）

  ② ★★★★ 不做 HTML 快取
     → API 的回應通常是個人化的
     → ★★★ 快取要做在應用層（Redis）

  ③ ★★★★ 不能用 PoW / JS 挑戰
     → API 客戶端沒有 JavaScript
     → ★★★ sentinel 的 challenge 一定要關
```

---

## ★★★★ 情境三：SPA + Laravel API

```nginx
# /etc/nginx/sites-available/spa.conf
upstream php_backend {
    server unix:/run/php/php8.3-fpm.sock;
}

server {
    listen 80;
    listen 443 ssl;
    http2 on;
    server_name crm.example.gov.tw;

    autocert on;
    ssl_protocols TLSv1.2 TLSv1.3;
    include snippets/security-headers.conf;

    root /var/www/crm/frontend/dist;
    index index.html;

    access_log /var/log/nginx/crm-access.log main;

    # ═══ ★★★★ API：優先比對（^~ 停止 regex 檢查）═══
    location ^~ /api/ {
        root /var/www/crm/api/current/public;

        shield block;
        shield_max_body 32k;
        shield_ban zone=shield count=5 window=1m bantime=2h;
        error_abuse zone=ea status=429;

        try_files $uri /index.php?$query_string;

        # ★★★★ 巢狀 location 要重複 root
        location ~ \.php$ {
            root /var/www/crm/api/current/public;
            try_files $uri =404;                       # ★★★★ 必要
            fastcgi_pass php_backend;
            fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
            fastcgi_param HTTPS on;                    # ★★★★
            include fastcgi_params;
            include snippets/security-headers.conf;
        }
    }

    # ═══ ★★★ Sanctum 的 CSRF 端點 ═══
    location = /sanctum/csrf-cookie {
        root /var/www/crm/api/current/public;
        shield off;                                    # ★★ 不需要
        try_files $uri /index.php?$query_string;
        location ~ \.php$ {
            root /var/www/crm/api/current/public;
            try_files $uri =404;
            fastcgi_pass php_backend;
            fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
            fastcgi_param HTTPS on;
            include fastcgi_params;
        }
    }

    # ═══ ★★★ 前端的建置產物：長期快取 ═══
    location /assets/ {
        shield off;
        strip off;
        gzip_static on;
        brotli_static on;
        zstd_static on;
        expires 1y;
        add_header Cache-Control "public, immutable" always;
        add_header Vary "Accept-Encoding" always;
        access_log off;
        try_files $uri =404;
    }

    # ═══ ★★★★ SPA 的 fallback ═══
    location / {
        shield detect;
        error_abuse zone=ea dry_run=on;

        # ★★★★ index.html 絕對不能長期快取
        location = /index.html {
            add_header Cache-Control "no-cache, must-revalidate" always;
            expires -1;
        }

        # ★★★ 快取 SPA 的殼（★ 但 TTL 短）
        cache_turbo ct;
        cache_turbo_valid 30s;
        cache_turbo_bypass   $is_logged_in $not_cacheable;
        cache_turbo_no_store $is_logged_in $not_cacheable;

        try_files $uri $uri/ /index.html;
    }

    location ~ /\. { deny all; return 404; }
}
```

---

## ★★★★ 分階段上線

```
★★★★ 絕對不要一次全開！四週的節奏：

┌────────────────────────────────────────────────────────────┐
│ ★★★★ 第 1 週：全部觀察模式                                  │
│   autocert_staging on;         ← 憑證用 staging             │
│   shield detect;               ← 只記錄                     │
│   error_abuse dry_run=on;      ← 只記錄                     │
│   cache_turbo（可以直接開，但要驗證個資外洩）                 │
│   → ★★★ 每天看 shield-analyze 與 abuse-monitor              │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│ ★★★ 第 2 週：憑證正式化 + 處理誤判                           │
│   autocert_staging off;        ← ★★★★ 換正式憑證            │
│   依分析結果加 shield_skip                                   │
│   調整 error_abuse 的 threshold                             │
│   → ★★★★ cache-privacy-test 驗證沒有個資外洩                │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│ ★★★ 第 3 週：shield 進入 block                              │
│   shield block;                ← 低流量時段先切              │
│   → ★★★★ 密切監控 403 的比率                                │
│   → 有異常就立刻切回 detect                                  │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│ ★★★ 第 4 週：error-abuse 正式啟用                           │
│   拿掉 dry_run                                              │
│   → ★★★★ 監控 429 的比率                                    │
│   → 觀察一週無誤後，考慮加 ModSecurity（第二道）              │
└────────────────────────────────────────────────────────────┘
```

```bash
#!/usr/bin/env bash
# ★★★★ /usr/local/bin/myguard-stage —— 切換上線階段
set -euo pipefail
STAGE="${1:?用法: myguard-stage <1|2|3|4|rollback>}"
CONF=/etc/nginx/nginx.conf
SITE=/etc/nginx/sites-available/app.conf

backup() {
    sudo cp -a "$CONF" "$CONF.bak-$(date +%Y%m%d-%H%M%S)"
    sudo cp -a "$SITE" "$SITE.bak-$(date +%Y%m%d-%H%M%S)"
}

apply() {
    if sudo nginx -t; then
        sudo systemctl reload nginx
        echo "  ★ 已套用"
    else
        echo "  ★★★★ 語法錯誤，未套用"
        exit 1
    fi
}

case "$STAGE" in
  1)
    echo "═══ 階段 1：全部觀察模式 ═══"
    backup
    sudo sed -i 's/^\(\s*autocert_staging\s*\).*/\1on;/' "$CONF"
    sudo sed -i 's/^\(\s*shield\s\+\)block;/\1detect;/' "$CONF" "$SITE"
    sudo sed -i 's/\(error_abuse zone=ea\)\([^;]*\);/\1 dry_run=on;/' "$SITE"
    apply
    echo "  ★★★ 觀察一週，每天執行："
    echo "     sudo shield-analyze /var/log/nginx/shield.json 7"
    echo "     sudo abuse-monitor"
    ;;
  2)
    echo "═══ 階段 2：憑證正式化 ═══"
    backup
    sudo sed -i 's/^\(\s*autocert_staging\s*\).*/\1off;/' "$CONF"
    apply
    sleep 30
    echo "  ── 驗證憑證 ──"
    D=$(grep -oP 'server_name\s+\K\S+' "$SITE" | head -1 | tr -d ';')
    echo | openssl s_client -connect "$D:443" -servername "$D" 2>/dev/null | \
      openssl x509 -noout -issuer -dates | sed 's/^/    /'
    echo "  ★★★★ issuer 不能含 STAGING！"
    echo "  ★★★★ 接著執行：sudo cache-privacy-test https://$D"
    ;;
  3)
    echo "═══ 階段 3：shield 進入 block ═══"
    backup
    sudo sed -i 's/^\(\s*shield\s\+\)detect;/\1block;/' "$CONF" "$SITE"
    apply
    echo "  ★★★★ 密切監控 403 的比率："
    echo "     watch -n 60 'sudo shield-monitor'"
    echo "  ★★★ 異常時立刻回退：sudo myguard-stage rollback"
    ;;
  4)
    echo "═══ 階段 4：error-abuse 正式啟用 ═══"
    backup
    sudo sed -i 's/\(error_abuse zone=ea\)\s*dry_run=on;/\1;/' "$SITE"
    apply
    echo "  ★★★★ 監控 429 的比率"
    ;;
  rollback)
    echo "═══ ★★★★ 緊急回退：全部改回觀察模式 ═══"
    backup
    sudo sed -i 's/^\(\s*shield\s\+\)block;/\1detect;/' "$CONF" "$SITE"
    sudo sed -i 's/\(error_abuse zone=ea\)\([^;]*\);/\1 dry_run=on;/' "$SITE"
    apply
    echo "  ★ 已回到觀察模式，服務不再被阻擋"
    echo "  ★★★ 分析原因：sudo shield-analyze; sudo abuse-monitor"
    ;;
  *)
    echo "★★ 用法: myguard-stage <1|2|3|4|rollback>"; exit 1 ;;
esac
```

---

## ★★★★ 上線前的完整驗收

```bash
#!/usr/bin/env bash
# ★★★★ /usr/local/bin/myguard-golive-check
set -uo pipefail
DOMAIN="${1:?用法: myguard-golive-check <網域>}"
URL="https://$DOMAIN"
FAIL=0
WARN=0

if [ -t 1 ]; then G='\033[32m'; R='\033[31m'; Y='\033[33m'; N='\033[0m'
else G=''; R=''; Y=''; N=''; fi

ok(){ printf "  ${G}✓${N} %s\n" "$1"; }
bad(){ printf "  ${R}★★★★ %s${N}\n" "$1"; FAIL=$((FAIL+1)); }
warn(){ printf "  ${Y}★★★ %s${N}\n" "$1"; WARN=$((WARN+1)); }

echo "═══ MyGuard 上線驗收：$DOMAIN ═══"
CONF=$(sudo nginx -T 2>/dev/null)

# ═══【1】基礎 ═══
echo -e "\n【1】基礎"
sudo nginx -t >/dev/null 2>&1 && ok "nginx 設定語法正確" || bad "nginx 設定語法錯誤"
systemctl is-active --quiet nginx && ok "nginx 執行中" || bad "nginx 未執行"
systemctl is-active --quiet php8.3-fpm && ok "php-fpm 執行中" || bad "php-fpm 未執行"
echo "$CONF" | grep -q 'server_tokens\s*off' && ok "server_tokens off" || bad "server_tokens 未關閉"

# ═══【2】★★★★ 模組 ═══
echo -e "\n【2】★★★★ 模組"
NV=$(dpkg-query -W -f='${Version}' nginx 2>/dev/null)
BAD=$(dpkg-query -W -f='${Package} ${Version}\n' 'libnginx-mod-*' 2>/dev/null | \
      awk -v v="$NV" '$2 != v' | wc -l)
[ "$BAD" -eq 0 ] && ok "模組版本一致（$NV）" || bad "$BAD 個模組版本不符"

for m in autocert shield cache_turbo; do
    echo "$CONF" | grep -q "load_module.*$m" && ok "$m 已載入" || warn "$m 未載入"
done

# ═══【3】★★★★ 憑證 ═══
echo -e "\n【3】★★★★ 憑證"
CERT=$(echo | timeout 10 openssl s_client -connect "$DOMAIN:443" \
       -servername "$DOMAIN" 2>/dev/null)
if [ -n "$CERT" ]; then
    INFO=$(echo "$CERT" | openssl x509 -noout -subject -issuer -dates 2>/dev/null)
    echo "$INFO" | sed 's/^/    /'
    echo "$INFO" | grep -qi 'STAGING' && \
      bad "★★★★ 這是 STAGING 憑證！autocert_staging 沒關" || ok "正式憑證"

    EXP=$(echo "$INFO" | grep -oP 'notAfter=\K.*')
    DAYS=$(( ($(date -d "$EXP" +%s) - $(date +%s)) / 86400 ))
    [ "$DAYS" -gt 20 ] && ok "憑證剩餘 $DAYS 天" || bad "憑證只剩 $DAYS 天"

    N=$(echo | timeout 10 openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" \
        -showcerts 2>/dev/null | grep -c 'BEGIN CERTIFICATE')
    [ "$N" -ge 2 ] && ok "憑證鏈完整（$N 張）" || bad "缺中繼憑證（只有 $N 張）"

    echo "$CERT" | grep -q 'Verify return code: 0 (ok)' && \
      ok "憑證驗證通過" || bad "憑證驗證失敗"
else
    bad "無法取得憑證"
fi

# ★★★ 舊協定
for v in tls1 tls1_1; do
    if timeout 5 openssl s_client -connect "$DOMAIN:443" -"$v" </dev/null >/dev/null 2>&1; then
        bad "★★★★ TLSv${v#tls} 還開著"
    fi
done
ok "舊 TLS 協定已停用"

# ═══【4】★★★★ 端點 ═══
echo -e "\n【4】★★★★ 端點"
t(){ local n="$1" p="$2" w="$3"
     local c; c=$(curl -sko /dev/null -w '%{http_code}' --max-time 15 "$URL$p")
     [ "$c" = "$w" ] && ok "$n ($c)" || bad "$n: $c ≠ $w"; }
t "首頁"                    "/"                        200
t "★★★★ .env 擋住"          "/.env"                    404
t "★★★★ .git/config 擋住"   "/.git/config"             404
t "★★★★ PathInfo RCE 防護"  "/storage/x.jpg/y.php"     404
t "★★★ shield-status 擋住"  "/shield-status"           403
t "★★★ 快取管理端擋住"       "/_cache-admin"            403
t "不存在的頁面"             "/__nope__"                404

# ═══【5】★★★★ shield ═══
echo -e "\n【5】★★★★ shield"
MODE=$(echo "$CONF" | grep -oP '^\s*shield\s+\K(off|detect|block)' | head -1)
echo "    目前模式: ${MODE:-未設定}"
if [ "$MODE" = "block" ]; then
    C=$(curl -sko /dev/null -w '%{http_code}' --max-time 10 \
        "$URL/?id=1%27+union+select+password+from+users--")
    [ "$C" != "200" ] && ok "SQLi 被擋 ($C)" || bad "★★★★ SQLi 沒有被擋"
    C=$(curl -sko /dev/null -w '%{http_code}' --max-time 10 "$URL/")
    [ "$C" = "200" ] && ok "正常請求放行" || bad "★★★★ 正常請求被擋 ($C)"
elif [ "$MODE" = "detect" ]; then
    warn "shield 仍在 detect 模式（★ 上線前應該切成 block）"
else
    bad "shield 未啟用"
fi
[ -f /var/log/nginx/shield.json ] && ok "shield 日誌存在" || warn "shield 日誌不存在"

# ═══【6】★★★★★ 快取的個資外洩 ═══
echo -e "\n【6】★★★★★ 快取隱私"
if echo "$CONF" | grep -q 'cache_turbo\s\+ct'; then
    echo "$CONF" | grep -q 'cache_turbo_no_store' && \
      ok "有設 cache_turbo_no_store" || bad "★★★★★ 缺 cache_turbo_no_store"
    echo "$CONF" | grep -q 'cache_turbo_bypass' && \
      ok "有設 cache_turbo_bypass" || bad "★★★★★ 缺 cache_turbo_bypass"

    XC=$(curl -skI "$URL/" -H 'Cookie: laravel_session=probe' | \
         grep -i '^x-cache' | awk '{print $2}' | tr -d '\r')
    case "$XC" in
        BYPASS|MISS|"") ok "帶 session 的請求不命中快取 (${XC:-none})" ;;
        *) bad "★★★★★ 帶 session 的請求命中快取 ($XC)！可能洩漏個資" ;;
    esac
    echo "    ★★★★★ 請另外執行完整測試：sudo cache-privacy-test $URL"
else
    warn "cache-turbo 未啟用"
fi

# ═══【7】★★★ 壓縮 ═══
echo -e "\n【7】壓縮"
V=$(curl -skI "$URL/" | grep -i '^vary' | tr -d '\r')
echo "$V" | grep -qi 'accept-encoding' && ok "$V" || bad "★★★★ 缺 Vary: Accept-Encoding"
for e in gzip br; do
    ce=$(curl -skI -H "Accept-Encoding: $e" "$URL/" | \
         grep -i '^content-encoding' | awk '{print $2}' | tr -d '\r')
    [ "$ce" = "$e" ] && ok "$e 壓縮生效" || warn "$e 未生效（${ce:-none}）"
done

# ═══【8】★★★ 安全標頭 ═══
echo -e "\n【8】安全標頭"
H=$(curl -skI "$URL/")
for h in strict-transport-security x-frame-options x-content-type-options referrer-policy; do
    echo "$H" | grep -qi "^$h:" && ok "$h" || warn "缺 $h"
done
echo "$H" | grep -qiE '^(x-powered-by|server: .*/[0-9])' && \
  bad "★★★★ 洩漏版本資訊" || ok "沒有洩漏版本"

# ═══【9】★★★ HTTP → HTTPS ═══
echo -e "\n【9】HTTP 重導向"
R=$(curl -sI --max-time 10 "http://$DOMAIN/" | tr -d '\r')
C=$(echo "$R" | head -1 | awk '{print $2}')
L=$(echo "$R" | grep -i '^location:' | cut -d' ' -f2-)
if [ "$C" = "301" ] && [[ "$L" == https://* ]]; then ok "301 → $L"
elif [ "$C" = "302" ]; then warn "用 302（建議 301）"
else bad "★★★★ HTTP 沒有重導向到 HTTPS ($C)"; fi

# ═══【10】★★★ 效能 ═══
echo -e "\n【10】效能"
curl -sko /dev/null --max-time 15 \
  -w "    DNS=%{time_namelookup}s TLS=%{time_appconnect}s ★★★ TTFB=%{time_starttransfer}s total=%{time_total}s\n" \
  "$URL/"
TTFB=$(curl -sko /dev/null -w '%{time_starttransfer}' --max-time 15 "$URL/")
awk -v t="$TTFB" 'BEGIN{ if (t > 1) exit 1 }' && ok "TTFB < 1s" || warn "TTFB 偏高（${TTFB}s）"

# ★★★ 快取命中
echo "    ── 快取命中測試 ──"
for i in 1 2 3; do
    printf "      第 %d 次: " "$i"
    curl -skI "$URL/" | grep -i '^x-cache' | tr -d '\r' | awk '{print $2}'
done

# ═══【11】★★★ 日誌與監控 ═══
echo -e "\n【11】日誌與監控"
for f in /var/log/nginx/access.log /var/log/nginx/error.log; do
    [ -f "$f" ] && ok "$(basename "$f") 存在" || warn "$(basename "$f") 不存在"
done
[ -f /etc/logrotate.d/nginx ] && ok "logrotate 已設定" || bad "★★★ 缺 logrotate"
sudo tail -50 /var/log/nginx/error.log 2>/dev/null | grep -q '\[emerg\]' && \
  bad "★★★★ error.log 有 emerg" || ok "error.log 沒有嚴重錯誤"

# ═══【12】★★★ 防火牆 ═══
echo -e "\n【12】防火牆"
sudo ufw status 2>/dev/null | grep -q 'Status: active' && ok "ufw 啟用中" || warn "ufw 未啟用"
sudo ss -tlnp 2>/dev/null | awk 'NR>1 && $4 !~ /^127\.|^\[::1\]/ {split($4,a,":"); print a[length(a)]}' | \
  sort -u | while read -r p; do
    case "$p" in
      80|443|22) ;;
      *) printf "  ${R}★★★★ 對外開放的埠: %s${N}\n" "$p" ;;
    esac
  done
ok "對外埠檢查完成"

# ═══ 總結 ═══
echo ""
echo "═══════════════════════════════════════"
if [ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]; then
    printf "${G}★ 全部通過，可以上線${N}\n"
elif [ "$FAIL" -eq 0 ]; then
    printf "${Y}★★★ %d 項警告（可上線但建議處理）${N}\n" "$WARN"
else
    printf "${R}★★★★ %d 項失敗、%d 項警告 —— 【不可上線】${N}\n" "$FAIL" "$WARN"
fi
echo "═══════════════════════════════════════"
echo ""
echo "★★★★★ 另外一定要手動執行："
echo "  sudo cache-privacy-test $URL      # 快取個資外洩的完整測試"
echo "  sudo nginx-module-verify $URL     # 各模組的功能驗證"
exit "$FAIL"
```

```bash
$ sudo install -m755 myguard-golive-check.sh /usr/local/bin/myguard-golive-check
$ sudo myguard-golive-check app.example.gov.tw
```

---

## ★★ Docker 映像

```bash
# ★★ MyGuard 提供每日重建的 Docker 映像
$ docker pull eilandert/nginx:latest
$ docker run --rm eilandert/nginx nginx -V 2>&1 | tr ' ' '\n' | grep -c '^--add-dynamic-module'

# ★★★ 適用情境：
#   · 主機不是 Debian/Ubuntu（★ RHEL 系沒有 RPM）
#   · ★★ 想快速試用不污染主機
#   · ★★ 需要多版本並存
```

```yaml
# ★★★ docker-compose.yml
services:
  nginx:
    image: eilandert/nginx:latest
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/sites:/etc/nginx/sites-enabled:ro
      - ./nginx/snippets:/etc/nginx/snippets:ro
      # ★★★★ autocert 的憑證儲存要持久化！
      - autocert-data:/var/lib/nginx/autocert
      - ./app:/var/www/app:ro
      - nginx-logs:/var/log/nginx
    environment:
      - TZ=Asia/Taipei
    depends_on:
      - php
    # ★★★ 安全加固
    cap_drop: [ALL]
    cap_add: [CHOWN, SETUID, SETGID, NET_BIND_SERVICE]
    security_opt: [no-new-privileges:true]
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://127.0.0.1/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  php:
    image: eilandert/php:8.3-fpm
    restart: unless-stopped
    volumes:
      - ./app:/var/www/app
    environment:
      - TZ=Asia/Taipei
    # ★★★★ 不要 expose port（★ 只給 nginx 內部連）

volumes:
  autocert-data:
  nginx-logs:
```

> [!danger] 容器中的 autocert ★★★★
> ```
> ★★★★ 憑證儲存目錄【一定要持久化】
>   → 沒有 volume 的話，容器重建時憑證全部消失
>   → ★★★★ 重新申請會撞到 Let's Encrypt 的速率限制
>
> ★★★ 三個要點：
>   ① volume 掛 /var/lib/nginx/autocert（★ 或你設定的 store_path）
>   ② ★★★ 80 埠一定要對外（http-01 challenge）
>   ③ ★★ 容器內也要設 resolver
> ```

---

## ★★★ 日常維運

```bash
#!/usr/bin/env bash
# ★★★ /usr/local/bin/myguard-daily —— 每日檢查
set -uo pipefail
DOMAIN="${1:?}"
TODAY=$(date '+%d/%b/%Y')
LOG=/var/log/nginx/access.log

echo "═══ MyGuard 每日檢查 $(date '+%F') ═══"

# ═══ ★★★ 憑證 ═══
echo -e "\n【憑證】"
EXP=$(echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null | \
      openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -n "$EXP" ]; then
    D=$(( ($(date -d "$EXP" +%s) - $(date +%s)) / 86400 ))
    printf "  剩餘 %s 天  " "$D"
    [ "$D" -lt 14 ] && echo "★★★★ 緊急！檢查 autocert" || echo "✓"
else
    echo "  ★★★★ 無法取得憑證"
fi

# ═══ ★★★ 流量與錯誤率 ═══
echo -e "\n【流量】"
T=$(grep -c "$TODAY" "$LOG" 2>/dev/null || echo 0)
echo "  今日請求: $T"
for c in 200 403 404 429 500 502; do
    n=$(grep "$TODAY" "$LOG" 2>/dev/null | grep -c " $c " || echo 0)
    awk -v c="$c" -v n="$n" -v t="$T" 'BEGIN{
      printf "  %-5s %8d  (%.2f%%)", c, n, (t>0? n/t*100 : 0)
      if ((c==403||c==429) && t>0 && n/t>0.05) printf "  ★★★★ 比率偏高，檢查誤判"
      if (c ~ /^5/ && t>0 && n/t>0.01) printf "  ★★★★ 伺服器錯誤偏高"
      print ""}'
done

# ═══ ★★★ 快取 ═══
echo -e "\n【快取】"
grep "$TODAY" "$LOG" 2>/dev/null | grep -oP 'cache=\K\S+' | sort | uniq -c | sort -rn | \
  awk '{a[$2]=$1; t+=$1} END {
    for (k in a) printf "  %-16s %8d (%.1f%%)\n", k, a[k], a[k]/t*100
    hit=a["HIT"]+a["STALE"]+a["STALE-IF-ERROR"]
    printf "  ★★★ 有效命中率: %.1f%%\n", (t>0? hit/t*100 : 0)}'

# ═══ ★★★ shield ═══
echo -e "\n【shield】"
if [ -f /var/log/nginx/shield.json ]; then
    D=$(date +%Y-%m-%d)
    N=$(jq -c "select(.ts >= \"$D\")" /var/log/nginx/shield.json 2>/dev/null | wc -l)
    B=$(jq -c "select(.ts >= \"$D\" and .mode==\"block\")" /var/log/nginx/shield.json 2>/dev/null | wc -l)
    echo "  今日命中: $N（阻擋 $B）"
    jq -r "select(.ts >= \"$D\") | .cat" /var/log/nginx/shield.json 2>/dev/null | \
      sort | uniq -c | sort -rn | head -5 | awk '{printf "    %-18s %6d\n", $2, $1}'
fi

# ═══ ★★★ error-abuse ═══
echo -e "\n【error-abuse】"
grep "$TODAY" "$LOG" 2>/dev/null | grep -oP 'ea=\K\w+' | sort | uniq -c | \
  awk '{printf "  %-10s %8d\n", $2, $1}'

# ═══ ★★★ 系統 ═══
echo -e "\n【系統】"
uptime | sed 's/^/  /'
free -h | awk '/^Mem:/{printf "  記憶體: available %s / %s\n", $7, $2}'
df -h / /var 2>/dev/null | awk 'NR>1{printf "  %-12s %s used\n", $6, $5}'
ps -o rss= -C nginx | awk '{s+=$1} END {printf "  nginx: %.1f MB\n", s/1024}'
ps -o rss= -C php-fpm 2>/dev/null | awk '{s+=$1} END {printf "  php-fpm: %.1f MB\n", s/1024}'

# ═══ ★★★★ 錯誤日誌 ═══
echo -e "\n【★★★ error.log 異常】"
sudo grep -c "$(date '+%Y/%m/%d')" /var/log/nginx/error.log 2>/dev/null | \
  awk '{print "  今日錯誤數: " $1}'
sudo grep "$(date '+%Y/%m/%d')" /var/log/nginx/error.log 2>/dev/null | \
  grep -oP '\[\K(emerg|alert|crit|error)' | sort | uniq -c | sed 's/^/  /'
sudo grep "$(date '+%Y/%m/%d')" /var/log/nginx/error.log 2>/dev/null | \
  tail -5 | cut -c1-140 | sed 's/^/    /'

# ═══ ★★★ 套件更新 ═══
echo -e "\n【更新】"
apt list --upgradable 2>/dev/null | grep -E '^(nginx|libnginx-mod-|php)' | \
  sed 's/^/  ★★ /' || echo "  ★ 沒有可用的更新"
```

```bash
$ sudo install -m755 myguard-daily.sh /usr/local/bin/myguard-daily
$ sudo tee /etc/cron.d/myguard >/dev/null <<'EOF'
0 8 * * * root /usr/local/bin/myguard-daily app.example.gov.tw 2>&1 | logger -t myguard
0 9 * * 1 root /usr/local/bin/nginx-security-check 2>&1 | logger -t myguard
0 3 * * 0 root /usr/local/bin/nginx-module-audit 2>&1 | logger -t myguard
EOF
```

---

## ★★★ 退場方案

```bash
#!/usr/bin/env bash
# ★★★★ /usr/local/bin/myguard-exit —— 退回官方 nginx
set -euo pipefail

echo "═══ ★★★★ MyGuard 退場 ═══"
echo "★★★ 這會把系統換回官方的 nginx，MyGuard 的所有模組功能都會失效。"
read -rp "確定嗎？[yes/N] " a
[ "$a" = yes ] || exit 1

TS=$(date +%Y%m%d-%H%M%S)

# ═══ ★★★【1】備份 ═══
echo -e "\n【1】備份"
sudo tar -czf "/root/nginx-myguard-$TS.tar.gz" /etc/nginx/
sudo nginx -T > "/root/nginx-full-$TS.conf" 2>/dev/null
#   ★★★★ 憑證也要備份（★ autocert 的儲存目錄）
sudo tar -czf "/root/autocert-$TS.tar.gz" /var/lib/nginx/ 2>/dev/null || true
echo "  ★ /root/nginx-myguard-$TS.tar.gz"

# ═══ ★★★★【2】移除設定中的 MyGuard 專屬指令 ═══
echo -e "\n【2】★★★★ 移除 MyGuard 專屬指令"
DIRECTIVES='autocert|shield|error_abuse|cache_turbo|strip|sentinel|brotli|zstd'
FILES=$(sudo grep -rlE "^\s*($DIRECTIVES)" /etc/nginx/ 2>/dev/null || true)
echo "  ── 需要處理的檔案 ──"
echo "$FILES" | sed 's/^/    /'

for f in $FILES; do
    sudo cp -a "$f" "$f.pre-exit-$TS"
    #   ★★★ 註解掉而不是刪除（★ 方便回頭看）
    sudo sed -i -E "s/^(\s*)($DIRECTIVES)/\1# [myguard-exit] \2/" "$f"
done
echo "  ★ 已註解（原檔備份為 *.pre-exit-$TS）"

# ═══ ★★★★【3】憑證：改回 certbot ═══
echo -e "\n【3】★★★★ 憑證"
echo "  ★★★★ autocert 移除後【沒有憑證了】，必須改用 certbot："
echo "     sudo apt install -y certbot python3-certbot-nginx"
echo "     sudo certbot --nginx -d app.example.gov.tw"
echo "  ★★★ 或先手動把備份的憑證放回去並設定 ssl_certificate"
read -rp "  已經準備好憑證方案了嗎？[y/N] " a
[ "$a" = y ] || { echo "  ★★ 已中止（設定已註解，但套件未移除）"; exit 1; }

# ═══ ★★★【4】移除套件與套件庫 ═══
echo -e "\n【4】移除套件"
sudo apt remove --purge -y nginx 'libnginx-mod-*' 2>/dev/null || true
sudo rm -f /etc/apt/sources.list.d/myguard*.list \
           /etc/apt/sources.list.d/myguard*.sources \
           /etc/apt/preferences.d/myguard \
           /etc/apt/keyrings/deb.myguard.nl.gpg
sudo apt update

# ═══ ★★★【5】安裝官方 nginx ═══
echo -e "\n【5】安裝官方 nginx"
sudo apt install -y nginx

# ═══ ★★★★【6】驗證 ═══
echo -e "\n【6】★★★★ 驗證"
if sudo nginx -t; then
    echo "  ★ 語法正確"
    sudo systemctl restart nginx
    systemctl is-active --quiet nginx && echo "  ★ 服務正常" || echo "  ★★★★ 服務異常"
else
    echo "  ★★★★ 語法錯誤 —— 還有 MyGuard 的指令沒處理乾淨"
    sudo nginx -t 2>&1 | sed 's/^/    /'
    echo "  ★★★ 檢查上面列出的檔案"
fi

echo -e "\n★ 退場完成"
echo "★★★ 備份位置："
echo "  設定: /root/nginx-myguard-$TS.tar.gz"
echo "  憑證: /root/autocert-$TS.tar.gz"
echo "★★★★ 別忘了設定 certbot 的自動續期並驗證"
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **憑證是 STAGING** ★★★★ | 忘記關 `autocert_staging` | `autocert_staging off;` + reload |
| **憑證申請失敗** ★★★★ | resolver / 80 埠 / 速率限制 | 見 [[060-02-05-03-guide-MyGuard-autocert自動憑證模組]] |
| **★★★★★ 未登入看到別人的內容** | 快取設定錯 | **立刻 `cache_turbo off`**；查 bypass/no_store |
| **403 比率突然升高** ★★★★ | shield 誤判 | **`myguard-stage rollback`** |
| **429 比率升高** ★★★★ | error-abuse 誤判 | 回 `dry_run`；調 threshold |
| **升級後 nginx 起不來** ★★★★ | 模組版本不符 | 一起升級；見 [[060-02-05-07-guide-MyGuard-動態模組管理]] |
| **頁面亂碼** ★★★★ | 缺 `Vary: Accept-Encoding` | `gzip_vary on`；`cache_turbo_auto_vary on` |
| **記憶體用量高** ★★★ | 模組太多／zone 太大 | `nginx-module-audit`；縮小 zone |
| **容器重建後憑證消失** ★★★★ | 沒持久化 | volume 掛 autocert 儲存目錄 |
| **CDN 後面封鎖所有人** ★★★★ | 沒設 `real_ip_header` | `set_real_ip_from` + `real_ip_header` |

### 排查

```bash
# ★★★★ 一鍵完整檢查
$ sudo myguard-golive-check app.example.gov.tw
$ sudo nginx-module-verify https://app.example.gov.tw
$ sudo cache-privacy-test https://app.example.gov.tw

# ★★★ 分項
$ sudo nginx -T 2>/dev/null | grep -E '^\s*(autocert|shield|error_abuse|cache_turbo|strip)'
$ sudo shield-analyze /var/log/nginx/shield.json 7
$ sudo abuse-monitor
$ sudo cache-monitor
$ sudo myguard-daily app.example.gov.tw

# ★★★★ 緊急回退
$ sudo myguard-stage rollback         # ★★★ 全部改回觀察模式
$ sudo systemctl reload nginx         # ★★ 清空 shield/error-abuse 的封鎖
```

---

## 安全性注意事項

> [!danger] 上線前的七個必檢項目 ★★★★
> ```
> ① ★★★★★ 快取沒有洩漏個資
>      → cache-privacy-test 必須通過
>      → cache_turbo_bypass + no_store 都要設
>
> ② ★★★★ 憑證是正式的（不是 STAGING）
>      → openssl s_client 看 issuer
>
> ③ ★★★★ .env / .git / PathInfo 都擋住
>      → curl 測試回 404
>
> ④ ★★★★ 狀態端點限制存取
>      → shield-status / _cache-admin / fpm-status
>
> ⑤ ★★★ Vary: Accept-Encoding 存在
>      → 否則壓縮內容會錯給
>
> ⑥ ★★★ shield 與 error-abuse 經過觀察期
>      → 直接 block 會擋掉正常使用者
>
> ⑦ ★★★ CDN/LB 後面設了 real_ip
>      → 否則封鎖的是 CDN 的 IP
> ```

```bash
# ★★★★ 上線前的最終確認（★ 全部要通過才能上線）
$ sudo myguard-golive-check app.example.gov.tw && \
  sudo cache-privacy-test https://app.example.gov.tw && \
  sudo nginx-module-verify https://app.example.gov.tw && \
  echo "★★★★ 可以上線" || echo "★★★★ 有問題，不可上線"

# ★★★ 記錄上線的狀態（★ 之後比對用）
$ sudo tee "/root/golive-$(date +%F).txt" >/dev/null <<EOF
上線日期: $(date -Is)
nginx: $(nginx -v 2>&1)
模組: $(dpkg-query -W -f='${Package}=${Version}\n' 'libnginx-mod-*' | tr '\n' ' ')
shield 模式: $(sudo nginx -T 2>/dev/null | grep -oP '^\s*shield\s+\K\w+' | head -1)
error-abuse: $(sudo nginx -T 2>/dev/null | grep -oP 'error_abuse zone=\K\S+' | head -1)
憑證: $(echo | openssl s_client -connect app.example.gov.tw:443 -servername app.example.gov.tw 2>/dev/null | openssl x509 -noout -issuer -enddate | tr '\n' ' ')
EOF
```

---

## 速查表

### ★★★★ 完整堆疊

```
autocert     ★★★★ 自動憑證（免 certbot）
shield       ★★★★ 已知漏洞利用（誤判低，可 block）
error-abuse  ★★★ 錯誤率限流（擋掃描器）
cache-turbo  ★★★★ 邊緣快取（SWR + single-flight）
strip-filter ★★ 回應精簡
brotli/zstd  ★★★ 壓縮
ModSecurity  ★★ 深度 WAF（選用，第二道）
```

### ★★★★ 分階段上線

```
第1週  autocert_staging on / shield detect / error_abuse dry_run=on
第2週  ★★★★ autocert_staging off + cache-privacy-test
第3週  ★★★ shield block（低流量時段，監控 403）
第4週  ★★★ error_abuse 拿掉 dry_run（監控 429）

sudo myguard-stage <1|2|3|4|rollback>
```

### ★★★★★ 三個絕對不能漏的

```
① cache_turbo_bypass + no_store（★★★★★ 個資外洩）
② autocert_staging off（★★★★ 否則憑證不被信任）
③ try_files $uri =404 在 php location（★★★★ PathInfo RCE）
```

### ★★★★ 驗收

```bash
sudo myguard-golive-check app.example.gov.tw    # ★★★★ 12 項檢查
sudo cache-privacy-test https://app.example.gov.tw   # ★★★★★ 個資外洩
sudo nginx-module-verify https://app.example.gov.tw  # ★★★ 各模組功能
```

### 日常維運

```bash
sudo myguard-daily app.example.gov.tw     # ★★★ 每日
sudo nginx-security-check                 # ★★★ 每週
sudo nginx-module-audit                   # ★★★ 每月清理
sudo shield-analyze; sudo abuse-monitor; sudo cache-monitor
```

### ★★★ 緊急處置

```bash
sudo myguard-stage rollback        # ★★★★ 全部回到觀察模式
sudo systemctl reload nginx        # ★★★ 清空封鎖狀態
# 快取洩漏個資 → location / { cache_turbo off; } 立刻 reload
```

### 退場

```bash
sudo myguard-exit                  # ★★★★ 退回官方 nginx
★★★★ 順序：註解 MyGuard 指令 → 準備 certbot → 移除套件 → 裝官方版
```

---

## 練習題

> [!question]- 練習 1：完整建置 ★★★★
> 1. **在一台乾淨的 Ubuntu 24.04 執行 `setup-myguard-lxmp`**
> 2. **建立站台設定並 `nginx -t`**
> 3. **確認 staging 憑證申請成功**（看 error.log）
> 4. **`myguard-golive-check`** → 有幾項失敗？
> 5. **逐一修正**
> 6. **關掉 staging 換正式憑證並再次驗收**

> [!question]- 練習 2：★★★★★ 個資外洩測試
> 1. **不設 `cache_turbo_bypass` / `no_store`，直接快取整站**
> 2. **登入後訪問 `/dashboard`**
> 3. **★★★★ 用另一個瀏覽器（未登入）訪問同一個 URL** → 看到什麼？
> 4. **這是什麼等級的資安事件？該怎麼緊急處置？**
> 5. **加上三層防護再測**
> 6. **執行 `cache-privacy-test`** → 通過了嗎？

> [!question]- 練習 3：分階段上線 ★★★★
> 1. **執行 `myguard-stage 1`** → 設定變成什麼？
> 2. **產生一些攻擊流量與正常流量**
> 3. **`shield-analyze`** → 有誤判嗎？
> 4. **執行 `myguard-stage 3`（block）**
> 5. **用正常瀏覽器訪問** → 被擋嗎？403 比率多少？
> 6. **`myguard-stage rollback`** → 恢復了嗎？

> [!question]- 練習 4：三種情境 ★★★
> 1. **分別建立傳統網站 / API / SPA 三個站台**
> 2. **三者的 shield 設定差在哪？為什麼？**
> 3. **三者的 cache-turbo 設定差在哪？**
> 4. **API 為什麼不能用 PoW 挑戰？**
> 5. **SPA 的 `index.html` 為什麼不能長期快取？**
> 6. **各自跑一次 `myguard-golive-check`**

> [!question]- 練習 5：退場演練 ★★★★
> 1. **完整建置好一台 MyGuard 伺服器**
> 2. **直接 `apt remove nginx` 換官方版** → `nginx -t` 說什麼？
> 3. **錯誤訊息列出哪些指令？**
> 4. **正確的順序應該是什麼？**
> 5. **執行 `myguard-exit` 完整走一次**
> 6. **憑證的問題怎麼處理？**

---

## 小測驗

Q1. **MyGuard 堆疊中，每一層的職責是什麼**？

Q2. **★★★★ 分階段上線的四個階段**？為什麼不能一次全開？

Q3. **★★★★★ 上線前三個絕對不能漏的檢查**？

Q4. **API 站台的設定和一般網站差在哪三點**？

Q5. **SPA 的 `index.html` 為什麼不能長期快取**？

Q6. **容器中使用 autocert 要注意什麼**？

Q7. **shield 誤判導致大量 403，緊急處置的順序**？

Q8. **快取洩漏個資時，第一件事該做什麼**？

Q9. **退場（換回官方 nginx）的正確順序**？順序錯了會怎樣？

Q10. **每日、每週、每月各該做哪些維運檢查**？

> [!question]- 測驗答案
> **Q1.** **每一層擋不同性質的東西**：
> **`autocert`** —— **讓 HTTPS 完全自動化**（申請、續期、熱載入），
> 消除 certbot 的「續期成功但 reload 失敗」風險；
> **`shield`** —— **★★★★ 擋已知的漏洞利用**
> （SQLi payload、Log4Shell 的 JNDI、`.env` 探測），
> 誤判極低所以可以直接 block，成本約 1µs/請求；
> **`error-abuse`** —— **★★★ 擋行為異常的來源**（5 分鐘內 100 個 404 = 掃描器），
> 這是**行為判斷**而不是內容判斷；
> **`cache-turbo`** —— **★★★ 擋掉大部分打向 PHP 的請求**
> （SWR + single-flight 讓上游壓力降到 1/1000）；
> **`ModSecurity`（選用）** —— 擋**未知的攻擊模式**，涵蓋廣但要長期調校；
> **壓縮與精簡** —— 減少傳輸量。
> **關鍵是「shield 在前、ModSecurity 在後」** ——
> shield 先擋掉大量自動化掃描，大幅減輕 ModSecurity 的 CPU 負擔。
>
> **Q2.** **四個階段**：
> **第 1 週全部觀察** —— `autocert_staging on`、`shield detect`、
> `error_abuse dry_run=on`；
> **第 2 週憑證正式化 + 處理誤判** —— `autocert_staging off`，
> 依 `shield-analyze` 的結果加 `shield_skip`，**執行 `cache-privacy-test`**；
> **第 3 週 shield 進入 block** —— 低流量時段先切，密切監控 403 比率；
> **第 4 週 error-abuse 正式啟用** —— 拿掉 `dry_run`，監控 429。
> **★★★★ 為什麼不能一次全開**：
> ①**你不知道自己的應用程式會不會誤判** ——
> 富文本編輯器的內容像 XSS、舊系統的參數像 SQLi；
> ②**誤判會直接擋掉正常使用者，而他們不會告訴你，只會離開**；
> ③**一次開多個功能，出問題時無法判斷是哪一個造成的**；
> ④**Let's Encrypt 有速率限制**，設定錯誤反覆重試會被鎖一週。
>
> **Q3.** ①**★★★★★ 快取沒有洩漏個資** ——
> `cache_turbo_bypass` + `cache_turbo_no_store` 都要設，
> 而且**必須實測**：登入後訪問 `/dashboard`，
> 再用未登入的 client 訪問同一個 URL，**看得到就是確定的資安事件**；
> ②**★★★★ 憑證是正式的不是 STAGING** ——
> 忘記 `autocert_staging off` 的話，
> **所有瀏覽器都會顯示憑證錯誤**，等於網站完全不能用：
> ```bash
> echo | openssl s_client -connect d:443 -servername d 2>/dev/null | \
>   openssl x509 -noout -issuer     # ★★★★ 不能含 STAGING
> ```
> ③**★★★★ `try_files $uri =404` 在 php location** ——
> 缺了會有 **PathInfo RCE**（上傳偽裝成圖片的 PHP，
> 用 `/uploads/x.jpg/y.php` 執行）。
> **驗證**：`curl -I https://d/storage/x.jpg/y.php` 必須回 404。
>
> **Q4.** ①**★★★ shield 可以較早進入 block** ——
> API 的請求格式固定（JSON），誤判機率遠低於網頁，
> 但 **`shield_max_body` 要調大**（32k），因為 JSON body 可能較長；
> ②**★★★★ 不做 HTML 快取** ——
> API 的回應通常是個人化的，**快取要做在應用層（Redis）**，
> 但可以開 `strip_json` 和壓縮；
> ③**★★★★ 不能用 PoW / JS 挑戰** ——
> **API 客戶端沒有 JavaScript 執行環境**
> （curl、後端服務、行動 App 的原生 HTTP client），
> 開了會把所有正常的 API 呼叫全部擋死。
> 另外 API 適合用 **`error_abuse status=429`**（語意正確）而不是 403，
> 而且健康檢查端點要 `shield off; error_abuse off;`。
>
> **Q5.** 因為 **`index.html` 是 SPA 的「殼」，裡面寫著要載入哪些 JS/CSS 檔案**。
> ```html
> <script src="/assets/app-a1b2c3.js"></script>
> ```
> **部署新版本後，檔名的 hash 會改變**（`app-d4e5f6.js`），
> 但如果瀏覽器**快取了舊的 `index.html`**，
> 它會繼續去載入 `app-a1b2c3.js` ——
> 而那個檔案在新版部署後**可能已經被刪除**，
> 使用者就會看到 **`ChunkLoadError` 或整個頁面白畫面**，
> 而且**清瀏覽器快取之前一直是壞的**。
> **正確設定**：
> ```nginx
> location = /index.html {
>     add_header Cache-Control "no-cache, must-revalidate" always;
>     expires -1;
> }
> location /assets/ {
>     expires 1y;
>     add_header Cache-Control "public, immutable" always;   # ★★★ 檔名有 hash
> }
> ```
> **「殼短快取、資源長快取」是 SPA 部署的基本原則**。
>
> **Q6.** **★★★★ 憑證儲存目錄一定要持久化**：
> ```yaml
> volumes:
>   - autocert-data:/var/lib/nginx/autocert
> ```
> **沒有 volume 的話，容器重建時憑證全部消失** ——
> 重新申請會**撞到 Let's Encrypt 的速率限制**
> （同一網域每週 50 張），
> 而在 CI/CD 環境中容器可能每天重建好幾次，**很快就被鎖住**。
> **另外兩個要點**：
> ②**★★★ 80 埠一定要對外映射**（`"80:80"`）——
> http-01 challenge 需要 CA 從外部連進來；
> ③**★★ 容器內也要設 `resolver`** ——
> 容器的 `/etc/resolv.conf` 指向 Docker 的內建 DNS，
> 但 nginx 不讀它，仍然要在設定中明確指定。
> 也要注意容器的時區（`TZ=Asia/Taipei`）會影響憑證的有效期判斷。
>
> **Q7.** **★★★★ 立刻回到觀察模式，而不是先分析原因**：
> ```bash
> sudo myguard-stage rollback        # ★★★★ shield 改回 detect
> # 或手動：
> sudo sed -i 's/^\(\s*shield\s\+\)block;/\1detect;/' /etc/nginx/nginx.conf
> sudo nginx -t && sudo systemctl reload nginx
> ```
> **`reload` 同時會清空 shield 的封鎖狀態**（共享記憶體重置），
> 被誤封的使用者立刻恢復。
> **順序的理由：先止血，再診斷** ——
> 每多一分鐘就有更多正常使用者被擋掉並離開。
> **恢復服務後才分析**：
> ```bash
> sudo shield-analyze /var/log/nginx/shield.json 1
> # ★★★★ 看「平均次數/IP」低的分類（分散在很多使用者身上 = 誤判）
> # ★★★★ 看被擋的 UA 有沒有真實瀏覽器
> ```
> 找出誤判的分類後用 **`shield_skip`**（優先在特定 location），
> 修正後**重新走一次觀察期**再切回 block。
>
> **Q8.** **★★★★★ 立刻停用快取，不要先研究原因**：
> ```nginx
> location / {
>     cache_turbo off;        # ★★★★★ 第一件事
> }
> ```
> ```bash
> sudo nginx -t && sudo systemctl reload nginx
> ```
> **reload 也會清空共享記憶體中已經快取的個資**。
> **這是資安事件等級的問題** —— 個資已經外洩了，
> 每多一秒就可能有更多人看到別人的資料。
> **停用後才處理**：
> ①**評估影響範圍** —— 從 access log 找出哪些 URL 被快取、
> `X-Cache: HIT` 的請求有多少、時間範圍多長；
> ②**依機關的資安事件通報程序回報**（個資法可能有通報義務）；
> ③修正設定（`cache_turbo_bypass` + `no_store` + `map`）；
> ④**用 `cache-privacy-test` 完整驗證**後才重新啟用。
> **絕對不要「先改設定看看有沒有好」** —— 那期間洩漏還在繼續。
>
> **Q9.** **★★★★ 正確順序**：
> ①**備份**（設定 + **autocert 的憑證儲存目錄**）；
> ②**★★★★ 先註解掉設定檔中所有 MyGuard 專屬的指令**
> （`autocert`、`shield`、`error_abuse`、`cache_turbo`、`strip`、`brotli`、`zstd`）；
> ③**★★★★ 準備好憑證的替代方案** ——
> autocert 移除後**就沒有憑證了**，必須先裝好 certbot 或把備份的憑證放回去；
> ④移除套件、套件庫、GPG 金鑰、pinning；
> ⑤安裝官方 nginx；
> ⑥`nginx -t` → restart → 驗證。
> **★★★★ 順序錯了會怎樣**：
> 如果**先移除套件再處理設定**，官方 nginx 啟動時會遇到
> `unknown directive "autocert"` —— **nginx 完全起不來，服務中斷**；
> 而且**憑證也一併消失**，就算 nginx 起來了也是 HTTPS 全掛。
> **這個流程應該事先演練並寫進文件** —— 真正需要退場時通常是緊急狀況。
>
> **Q10.** **每日**（`myguard-daily`）：
> 憑證剩餘天數（< 14 天要查 autocert）、
> 各狀態碼的比率（**403/429 > 5% 表示誤判**、5xx > 1% 表示應用有問題）、
> **快取命中率**、shield 今日命中與分類分布、
> error-abuse 的狀態分布、系統資源、error.log 的 emerg/crit。
> **每週**（`nginx-security-check`）：
> **模組版本一致性**、可用的安全更新、
> 模組檔案的權限與來源（是否來自套件管理）、
> 深入的 `shield-analyze`（七天的誤判趨勢）。
> **每月**（`nginx-module-audit`）：
> **找出載入但設定中沒使用的模組**並清理（減少攻擊面與記憶體）、
> 檢視 `cache-privacy-test` 是否仍通過（設定可能被改動）、
> 檢視封鎖清單有沒有誤封重要來源。
> **每季**：完整的 `myguard-golive-check`、
> 憑證的 CAA 記錄確認、退場方案的演練。

---

## 延伸閱讀

- [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]] — 套件庫與風險評估
- [[060-02-05-02-guide-MyGuard-Angie伺服器入門]] — Angie 的替代方案
- [[060-02-05-03-guide-MyGuard-autocert自動憑證模組]] — 自動憑證的細節
- [[060-02-05-04-guide-http-shield攻擊攔截]] — 攻擊攔截的調校
- [[060-02-05-05-guide-error-abuse與sentinel]] — 限流與信譽評分
- [[060-02-05-06-guide-cache-turbo與壓縮模組]] — 快取與壓縮
- [[060-02-05-07-guide-MyGuard-動態模組管理]] — 模組的升級與管理
- [[130-01-05-06-guide-Vue-Laravel完整部署實戰]] — **★★★ LXMP 的部署流程**
- [[130-01-04-07-guide-Laravel-正式環境安全檢查表]] — 應用層的安全
