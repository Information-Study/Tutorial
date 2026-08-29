---
title: "Apache HTTPS 設定"
desc: "mod_ssl 設定、Certbot 申請與續期、SNI 與 OCSP Stapling"
aliases: [mod_ssl, SSLEngine, Certbot, HTTPS, SSLCertificateFile]
tags: [群組/軟體與開發工具, 服務/apache, 主題/HTTPS]
category: Apache
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[060-02-03-02-guide-Apache-VirtualHost設定]]"]
updated: 2026-08-28
---

# Apache HTTPS 設定

> [!abstract] 這篇你會學到
> - 用 **Certbot** 為 Apache 申請憑證並設定自動續期
> - 寫出一份 **SSL Labs 拿 A+** 的 `mod_ssl` 設定
> - 分清 **`SSLCertificateFile` / `SSLCertificateChainFile`**（2.4.8 前後不同）
> - 設定 **OCSP Stapling** 與 **HTTP/2**
> - 處理**多網域與萬用憑證**
> - 系統化排查 Apache 的 **TLS 錯誤**

## 前置知識

- [[060-02-03-02-guide-Apache-VirtualHost設定]] — VirtualHost
- [[060-02-02-06-guide-Nginx-HTTPS與Certbot]] — 憑證的通用概念（本篇不重複）

> [!tip] 憑證原理與自簽憑證鏈
> 本篇專注在 **Apache 這邊怎麼設**。
> 憑證原理、CSR、自簽憑證鏈、內部 CA 見 [[090-01-00-idx-PKI-憑證與PKI]]。

---

## 啟用 mod_ssl

```bash
# ═══ Ubuntu / Debian ═══
$ sudo a2enmod ssl socache_shmcb headers http2
$ sudo a2ensite default-ssl            # 或用你自己的
$ sudo systemctl restart apache2

$ sudo ss -tlnp | grep :443
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> $ sudo dnf install -y mod_ssl
> # ★ 安裝後會自動產生 /etc/httpd/conf.d/ssl.conf
>
> $ sudo systemctl restart httpd
> $ sudo firewall-cmd --permanent --add-service=https && sudo firewall-cmd --reload
>
> # ★ RHEL 有系統層級的加密政策（會覆蓋應用層設定）
> $ update-crypto-policies --show
> DEFAULT
> # 政策：LEGACY / DEFAULT / FUTURE / FIPS
> $ sudo update-crypto-policies --set DEFAULT
>
> # ★ 若 Apache 的 SSLProtocol 設定「看起來沒生效」，先檢查這個
> $ cat /etc/crypto-policies/back-ends/opensslcnf.config
> ```

---

## Certbot

```bash
$ sudo snap install --classic certbot
$ sudo ln -sf /snap/bin/certbot /usr/bin/certbot

# ═══ 方式一：--apache（自動改設定）═══
$ sudo certbot --apache -d app.example.gov.tw -d www.app.example.gov.tw

# ═══ 方式二：--webroot（★ 推薦，不動你的設定檔）═══
$ sudo mkdir -p /var/www/acme
$ sudo certbot certonly --webroot -w /var/www/acme \
    -d app.example.gov.tw \
    --email admin@example.gov.tw --agree-tos --no-eff-email

# ═══ 測試續期（★ 一定要做）═══
$ sudo certbot renew --dry-run
$ sudo certbot certificates
```

```apache
# ★ ACME 挑戰的設定（HTTP VirtualHost）
<VirtualHost *:80>
    ServerName app.example.gov.tw

    # ★ Alias 要在轉址規則【之前】
    Alias /.well-known/acme-challenge /var/www/acme/.well-known/acme-challenge
    <Directory /var/www/acme/.well-known/acme-challenge>
        Options None
        AllowOverride None
        Require all granted
        ForceType text/plain
    </Directory>

    # 其餘全部轉到 HTTPS
    RedirectMatch permanent "^/(?!\.well-known/acme-challenge)(.*)$" \
        "https://app.example.gov.tw/$1"

    ErrorLog  ${APACHE_LOG_DIR}/app-http-error.log
    CustomLog ${APACHE_LOG_DIR}/app-http-access.log combined
</VirtualHost>
```

> [!danger] deploy hook：憑證續期後必須 reload ★★
> **與 Nginx 完全相同的問題** ——
> Certbot 續期成功但 Apache 還在用記憶體中的舊憑證。
>
> ```bash
> $ sudo mkdir -p /etc/letsencrypt/renewal-hooks/deploy
> $ sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-apache.sh >/dev/null <<'EOF'
> #!/usr/bin/env bash
> set -euo pipefail
> SVC=$(systemctl list-units --type=service --state=running 2>/dev/null | \
>       grep -oE '\b(apache2|httpd)\.service' | head -1)
> SVC="${SVC:-apache2.service}"
> CTL=$(command -v apache2ctl || command -v apachectl)
>
> if "$CTL" configtest 2>/dev/null; then
>     systemctl reload "$SVC"
>     logger -t certbot-deploy "憑證已續期並重新載入 $SVC：${RENEWED_DOMAINS:-unknown}"
> else
>     logger -t certbot-deploy "★ configtest 失敗，未重新載入"
>     exit 1
> fi
> EOF
> $ sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-apache.sh
>
> # 驗證
> $ sudo certbot renew --dry-run 2>&1 | grep -i hook
> ```
>
> **監控方式**（不要只看檔案）：
> ```bash
> # 比對「磁碟上的憑證」與「Apache 正在服務的憑證」
> $ openssl x509 -in /etc/letsencrypt/live/D/fullchain.pem -noout -fingerprint -sha256
> $ echo | openssl s_client -connect D:443 -servername D 2>/dev/null | \
>     openssl x509 -noout -fingerprint -sha256
> # ★ 不一致 = 沒有 reload
> ```

---

## 完整的 TLS 設定

```apache
# ═══════════ /etc/apache2/conf-available/ssl-params.conf ═══════════

# ── 協定版本 ──
SSLProtocol             -all +TLSv1.2 +TLSv1.3
#                       ^^^^ ★ 先全部關掉，再明確開啟需要的

# ── 加密套件 ──
SSLCipherSuite          ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384
SSLHonorCipherOrder     off          # ★ TLS 1.3 時代讓客戶端決定較好

# ★ TLS 1.3 的套件是獨立設定的
SSLOpenSSLConfCmd Ciphersuites TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256

# ── 橢圓曲線 ──
SSLOpenSSLConfCmd Curves X25519:secp256r1:secp384r1

# ── 壓縮與重新協商 ──
SSLCompression          off          # ★ 防 CRIME 攻擊
SSLInsecureRenegotiation off
SSLStrictSNIVHostCheck  off          # 舊客戶端相容（改 on 更嚴格）

# ── Session ──
SSLSessionTickets       off          # ★ 保護前向保密
SSLSessionCache         "shmcb:/var/run/apache2/ssl_scache(512000)"
SSLSessionCacheTimeout  300

# ── OCSP Stapling ──
SSLUseStapling          on
SSLStaplingCache        "shmcb:/var/run/apache2/ssl_stapling(128000)"
SSLStaplingResponderTimeout 5
SSLStaplingReturnResponderErrors off
SSLStaplingStandardCacheTimeout  3600
```

```bash
$ sudo a2enconf ssl-params
$ sudo apache2ctl configtest && sudo systemctl restart apache2
```

> [!danger] `SSLProtocol` 要用「先關全部再開需要的」寫法
> ```apache
> # ❌ 這種寫法在不同 OpenSSL 版本行為不一致
> SSLProtocol all -SSLv2 -SSLv3 -TLSv1 -TLSv1.1
>
> # ✅ 明確且可預測
> SSLProtocol -all +TLSv1.2 +TLSv1.3
> ```
>
> **`SSLStaplingCache` 必須設在「全域」，不能放在 VirtualHost 內**：
> ```
> AH02172: SSLStaplingCache: unknown or unsupported cache type
> ```

### VirtualHost 中的憑證設定

```apache
<VirtualHost *:443>
    ServerName app.example.gov.tw

    SSLEngine on

    # ── ★ Apache 2.4.8+ 的寫法 ──
    SSLCertificateFile      /etc/letsencrypt/live/app.example.gov.tw/fullchain.pem
    SSLCertificateKeyFile   /etc/letsencrypt/live/app.example.gov.tw/privkey.pem
    # ★ 2.4.8 之後 fullchain.pem 已含中繼憑證，【不需要】 SSLCertificateChainFile

    # ── OCSP Stapling 需要 ──
    SSLUseStapling on

    # ── HTTP/2 ──
    Protocols h2 http/1.1

    # ── HSTS（★ 漸進導入）──
    Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"

    # ── 安全標頭 ──
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-Content-Type-Options "nosniff"
    Header always set Referrer-Policy "strict-origin-when-cross-origin"

    DocumentRoot /var/www/app/current/public
    <Directory /var/www/app/current/public>
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>

    # ── ★ 讓後端知道是 HTTPS ──
    <FilesMatch \.php$>
        SetHandler "proxy:unix:/run/php/php8.3-fpm.sock|fcgi://localhost"
    </FilesMatch>
    SetEnvIf X-Forwarded-Proto https HTTPS=on

    ErrorLog  ${APACHE_LOG_DIR}/app-ssl-error.log
    CustomLog ${APACHE_LOG_DIR}/app-ssl-access.log combined
    LogLevel warn ssl:warn
</VirtualHost>
```

> [!warning] `SSLCertificateChainFile` 在 2.4.8 之後被廢棄
> ```apache
> # ── Apache < 2.4.8（舊）──
> SSLCertificateFile      /path/cert.pem          # 只有自己的憑證
> SSLCertificateChainFile /path/chain.pem         # ★ 中繼憑證分開
>
> # ── Apache ≥ 2.4.8（★ 現在的做法）──
> SSLCertificateFile      /path/fullchain.pem     # ★ 自己的 + 中繼，合在一起
> # SSLCertificateChainFile 不需要（寫了會有 deprecation 警告）
> ```
>
> **用錯的症狀與 Nginx 完全相同**：
> **桌面版 Chrome 正常，手機 App / curl / Java 憑證驗證失敗。**
>
> ```bash
> # ★ 檢查憑證鏈長度
> $ echo | openssl s_client -connect D:443 -servername D -showcerts 2>/dev/null | \
>     grep -c 'BEGIN CERTIFICATE'
> 2      # ★ 至少要 2
> ```

### HTTP/2

```apache
# 全域或 VirtualHost
Protocols h2 http/1.1
# ★ h2 必須在 http/1.1 【前面】

# HTTP/2 調校
H2MaxSessionStreams 128
H2WindowSize        65535
H2MinWorkers        10
H2MaxWorkers        64
```

```bash
$ sudo a2enmod http2
$ sudo systemctl restart apache2
$ curl -sI --http2 https://網站/ | head -1
HTTP/2 200
```

> [!danger] HTTP/2 不能搭配 prefork MPM
> ```
> AH10034: The mpm module (prefork.c) is not supported by mod_http2.
> mod_http2 requires an event or worker MPM.
> ```
> **這又是一個離開 `mod_php` + prefork 的理由。**
> 見 [[060-02-03-03-guide-Apache-模組與MPM]]。

---

## 多網域與萬用憑證

### 多網域（SNI）

```apache
# 每個網域各自的 VirtualHost 與憑證
<VirtualHost *:443>
    ServerName a.example.gov.tw
    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/a.example.gov.tw/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/a.example.gov.tw/privkey.pem
    Protocols h2 http/1.1
    # ...
</VirtualHost>

<VirtualHost *:443>
    ServerName b.example.gov.tw
    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/b.example.gov.tw/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/b.example.gov.tw/privkey.pem
    Protocols h2 http/1.1
    # ...
</VirtualHost>
```

> [!warning] `SSLStrictSNIVHostCheck` 的取捨
> ```apache
> SSLStrictSNIVHostCheck off     # ★ 預設：不支援 SNI 的舊客戶端會拿到【第一個】憑證
> SSLStrictSNIVHostCheck on      # 嚴格：不送 SNI 的客戶端直接拒絕（403）
> ```
> 現代客戶端都支援 SNI，
> **設成 `on` 可以避免「意外洩漏第一個 VirtualHost 的憑證」**，
> 但可能擋掉極舊的裝置（Windows XP 的 IE、Android 2.x）。

### 萬用憑證

```bash
$ sudo snap install certbot-dns-cloudflare
$ sudo snap set certbot trust-plugin-with-root=ok
$ sudo mkdir -p /root/.secrets
$ echo 'dns_cloudflare_api_token = 你的_Token' | sudo tee /root/.secrets/cloudflare.ini
$ sudo chmod 600 /root/.secrets/cloudflare.ini

$ sudo certbot certonly --dns-cloudflare \
    --dns-cloudflare-credentials /root/.secrets/cloudflare.ini \
    -d "example.gov.tw" -d "*.example.gov.tw"
```

```apache
<VirtualHost *:443>
    ServerName  example.gov.tw
    ServerAlias *.example.gov.tw

    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/example.gov.tw/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/example.gov.tw/privkey.pem

    # ★ 依子網域決定 DocumentRoot（需要 mod_vhost_alias 或 rewrite）
    VirtualDocumentRoot /var/www/sites/%1/public
    # %1 = 第一段子網域

    <Directory /var/www/sites>
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>
</VirtualHost>
```

```bash
$ sudo a2enmod vhost_alias
```

### 雙憑證（ECC + RSA）

```apache
<VirtualHost *:443>
    ServerName app.example.gov.tw
    SSLEngine on

    # ★ Apache 2.4.8+ 支援多組憑證，會依客戶端能力自動選擇
    SSLCertificateFile    /etc/letsencrypt/live/app.example.gov.tw-ecc/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/app.example.gov.tw-ecc/privkey.pem

    SSLCertificateFile    /etc/letsencrypt/live/app.example.gov.tw/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/app.example.gov.tw/privkey.pem
</VirtualHost>
```

---

## mTLS（雙向認證）

```apache
<VirtualHost *:443>
    ServerName secure-api.example.gov.tw

    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/secure-api.example.gov.tw/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/secure-api.example.gov.tw/privkey.pem

    # ── ★ 要求客戶端憑證 ──
    SSLCACertificateFile  /etc/ssl/internal-ca/ca.crt        # 內部 CA
    SSLVerifyClient       require
    SSLVerifyDepth        2

    # ── 撤銷檢查 ──
    SSLCARevocationFile   /etc/ssl/internal-ca/crl.pem
    SSLCARevocationCheck  chain

    # ── ★ 把客戶端憑證資訊傳給後端 ──
    RequestHeader set X-Client-DN    "%{SSL_CLIENT_S_DN}s"
    RequestHeader set X-Client-CN    "%{SSL_CLIENT_S_DN_CN}s"
    RequestHeader set X-Client-Serial "%{SSL_CLIENT_M_SERIAL}s"
    RequestHeader set X-Client-Verify "%{SSL_CLIENT_VERIFY}s"

    # ── 只允許特定的客戶端憑證 ──
    <Location />
        Require expr %{SSL_CLIENT_S_DN_O} == "Example Government Agency"
    </Location>

    ErrorLog  ${APACHE_LOG_DIR}/mtls-error.log
    CustomLog ${APACHE_LOG_DIR}/mtls-access.log \
        "%h %l %u %t \"%r\" %>s %O SSL_CLIENT=%{SSL_CLIENT_S_DN_CN}x"
</VirtualHost>
```

```bash
# 測試 mTLS
$ curl --cert client.crt --key client.key \
    https://secure-api.example.gov.tw/

# 不帶憑證應該失敗
$ curl https://secure-api.example.gov.tw/
curl: (56) OpenSSL SSL_read: error:0A00045C:SSL routines::tlsv13 alert certificate required
```

> [!tip] mTLS 適合機關間的系統對接
> 比 API Key 安全得多：
> - 憑證有**有效期**與**撤銷機制（CRL/OCSP）**
> - 私鑰**不會在網路上傳輸**
> - 可以在 TLS 層就擋掉未授權的連線（**不進到應用層**）
>
> 內部 CA 的建立見 [[090-01-00-idx-PKI-憑證與PKI]]。

---

## 完整實戰範例

### 一鍵建立 HTTPS 站台

```bash
#!/usr/bin/env bash
set -euo pipefail
DOMAIN="${1:?用法: $0 <domain> [webroot]}"
WEBROOT="${2:-/var/www/$DOMAIN/current/public}"
EMAIL="admin@example.gov.tw"

echo "═══ 【1】前置檢查 ═══"
apache2ctl -M | grep -q ssl_module || { echo "  啟用 mod_ssl"; sudo a2enmod ssl socache_shmcb headers http2; }
MPM=$(apache2ctl -M | grep -oP 'mpm_\K\w+(?=_module)')
echo "  MPM: $MPM"
[ "$MPM" = "prefork" ] && echo "  ⚠ prefork 不支援 HTTP/2，建議先遷移到 event"

echo -e "\n═══ 【2】ACME 準備 ═══"
sudo mkdir -p /var/www/acme/.well-known/acme-challenge
sudo chown -R www-data:www-data /var/www/acme

sudo tee "/etc/apache2/sites-available/$DOMAIN.conf" >/dev/null <<EOF
<VirtualHost *:80>
    ServerName $DOMAIN

    Alias /.well-known/acme-challenge /var/www/acme/.well-known/acme-challenge
    <Directory /var/www/acme/.well-known/acme-challenge>
        Options None
        AllowOverride None
        Require all granted
        ForceType text/plain
    </Directory>

    RedirectMatch permanent "^/(?!\\.well-known/acme-challenge)(.*)\$" "https://$DOMAIN/\$1"

    ErrorLog  \${APACHE_LOG_DIR}/$DOMAIN-http-error.log
    CustomLog \${APACHE_LOG_DIR}/$DOMAIN-http-access.log combined
</VirtualHost>
EOF
sudo a2ensite "$DOMAIN"
sudo apache2ctl configtest && sudo systemctl reload apache2

echo "  驗證 ACME 路徑"
echo "test" | sudo tee /var/www/acme/.well-known/acme-challenge/test >/dev/null
curl -sf "http://$DOMAIN/.well-known/acme-challenge/test" >/dev/null \
  && echo "  ✓ 可存取" || { echo "  ✗ 不通，中止"; exit 1; }
sudo rm -f /var/www/acme/.well-known/acme-challenge/test

echo -e "\n═══ 【3】申請憑證 ═══"
sudo certbot certonly --webroot -w /var/www/acme -d "$DOMAIN" \
    --email "$EMAIL" --agree-tos --no-eff-email --non-interactive

echo -e "\n═══ 【4】ssl-params ═══"
sudo tee /etc/apache2/conf-available/ssl-params.conf >/dev/null <<'EOF'
SSLProtocol             -all +TLSv1.2 +TLSv1.3
SSLCipherSuite          ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305
SSLHonorCipherOrder     off
SSLCompression          off
SSLInsecureRenegotiation off
SSLSessionTickets       off
SSLSessionCache         "shmcb:/var/run/apache2/ssl_scache(512000)"
SSLSessionCacheTimeout  300
SSLUseStapling          on
SSLStaplingCache        "shmcb:/var/run/apache2/ssl_stapling(128000)"
SSLStaplingResponderTimeout 5
SSLStaplingReturnResponderErrors off
EOF
sudo a2enconf ssl-params

echo -e "\n═══ 【5】HTTPS VirtualHost ═══"
sudo tee -a "/etc/apache2/sites-available/$DOMAIN.conf" >/dev/null <<EOF

<VirtualHost *:443>
    ServerName $DOMAIN

    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/$DOMAIN/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/$DOMAIN/privkey.pem
    SSLUseStapling on

    Protocols h2 http/1.1

    # ★ HSTS 先用短的
    Header always set Strict-Transport-Security "max-age=300"
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-Content-Type-Options "nosniff"
    Header always set Referrer-Policy "strict-origin-when-cross-origin"
    Header always unset X-Powered-By

    DocumentRoot $WEBROOT
    <Directory $WEBROOT>
        Options -Indexes -MultiViews +FollowSymLinks
        AllowOverride None
        Require all granted

        RewriteEngine On
        RewriteCond %{HTTP:Authorization} .
        RewriteRule .* - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]
        RewriteCond %{REQUEST_FILENAME} !-d
        RewriteCond %{REQUEST_FILENAME} !-f
        RewriteRule ^ index.php [L]
    </Directory>

    <FilesMatch \\.php\$>
        SetHandler "proxy:unix:/run/php/php8.3-fpm.sock|fcgi://localhost"
    </FilesMatch>

    <FilesMatch "^\\.|\\.(env|log|sql|bak|ini|ya?ml|key|pem)\$">
        Require all denied
    </FilesMatch>

    ErrorLog  \${APACHE_LOG_DIR}/$DOMAIN-ssl-error.log
    CustomLog \${APACHE_LOG_DIR}/$DOMAIN-ssl-access.log combined
    LogLevel warn ssl:warn
</VirtualHost>
EOF
sudo apache2ctl configtest && sudo systemctl restart apache2

echo -e "\n═══ 【6】deploy hook ═══"
sudo mkdir -p /etc/letsencrypt/renewal-hooks/deploy
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-apache.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
CTL=$(command -v apache2ctl || command -v apachectl)
if "$CTL" configtest 2>/dev/null; then
    systemctl reload apache2 2>/dev/null || systemctl reload httpd
    logger -t certbot-deploy "憑證續期並重新載入：${RENEWED_DOMAINS:-unknown}"
else
    logger -t certbot-deploy "★ configtest 失敗"
    exit 1
fi
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-apache.sh
sudo certbot renew --dry-run

echo -e "\n═══ 【7】驗證 ═══"
sleep 2
echo "  ── 憑證鏈 ──"
echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" -showcerts 2>/dev/null | \
    grep -c 'BEGIN CERTIFICATE' | awk '{print "    憑證數："$1" "($1>=2?"✓":"✗ 應用 fullchain.pem")}'
echo "  ── 協定 ──"
for p in tls1 tls1_1 tls1_2 tls1_3; do
    if echo | timeout 5 openssl s_client -"$p" -connect "$DOMAIN:443" -servername "$DOMAIN" >/dev/null 2>&1; then
        case "$p" in tls1|tls1_1) echo "    ✗ $p 【應關閉】";; *) echo "    ✓ $p";; esac
    else
        case "$p" in tls1|tls1_1) echo "    ✓ $p 已關閉";; *) echo "    ⚠ $p 不支援";; esac
    fi
done
echo "  ── OCSP ──"
echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" -status 2>/dev/null | \
    grep -q 'OCSP Response Status: successful' && echo "    ✓ 已啟用" || echo "    ⚠ 未啟用"
echo "  ── HTTP/2 ──"
curl -sI --http2 "https://$DOMAIN/" 2>/dev/null | head -1 | sed 's/^/    /'
echo "  ── 轉址 ──"
curl -sI "http://$DOMAIN/" 2>/dev/null | grep -iE '^(HTTP|location)' | sed 's/^/    /'

echo -e "\n✓ 完成。檢測：https://www.ssllabs.com/ssltest/analyze.html?d=$DOMAIN"
echo "  ★ 確認全站 HTTPS 正常一個月後，再把 HSTS 的 max-age 拉長"
```

---

## 常見錯誤與排錯

| 現象／錯誤 | 原因 | 解法 |
| --- | --- | --- |
| **手機 App 憑證錯誤，電腦正常** ★ | 用了 `cert.pem` 或缺中繼憑證 | **`SSLCertificateFile` 用 `fullchain.pem`** |
| **續期後還是舊憑證** ★★ | 沒有 deploy hook | 建立 `renewal-hooks/deploy/reload-apache.sh` |
| `AH02172: SSLStaplingCache: unknown` | `SSLStaplingCache` 放在 VirtualHost 內 | **移到全域設定** |
| **`AH10034: mpm module (prefork.c) is not supported by mod_http2`** | prefork 不支援 HTTP/2 | **改用 event MPM** |
| `SSLCertificateChainFile` deprecation 警告 | 2.4.8+ 已廢棄 | 移除它，用 `fullchain.pem` |
| **`SSLProtocol` 設定沒生效（RHEL）** ★ | **系統加密政策覆蓋** | `update-crypto-policies --show` |
| `AH01909: server certificate does NOT include an ID which matches the server name` | 憑證的 SAN 不含此網域 | 重新申請時加 `-d` |
| ACME 驗證失敗（301） | 轉址規則吃掉了挑戰路徑 | `Alias` 放在 `RedirectMatch` 前；用 `(?!\.well-known...)` |
| **`ERR_TOO_MANY_REDIRECTS`** | 後端不知道是 HTTPS | `RequestHeader set X-Forwarded-Proto "https"` |
| PHP 的 `$_SERVER['HTTPS']` 是空的 | FPM 沒收到 | `SetEnvIf X-Forwarded-Proto https HTTPS=on` |
| 不支援 SNI 的客戶端拿到錯的憑證 | SNI 限制 | `SSLStrictSNIVHostCheck on`（會擋掉舊裝置） |
| **SSL Labs 只有 B** | TLS 1.0/1.1 未關 / 弱 cipher | 套用本篇的 `ssl-params.conf` |
| `unable to get local issuer certificate` | 憑證鏈不完整 | `fullchain.pem` |
| 私鑰讀取失敗 | 權限 / SELinux | `chmod 600`；`restorecon -Rv /etc/letsencrypt` |

### 排查指令

```bash
# 【1】從外部看到的憑證
$ echo | openssl s_client -connect D:443 -servername D 2>/dev/null | \
    openssl x509 -noout -subject -issuer -dates -ext subjectAltName

# 【2】★ 磁碟 vs 線上（抓「沒 reload」）
$ openssl x509 -in /etc/letsencrypt/live/D/fullchain.pem -noout -fingerprint -sha256
$ echo | openssl s_client -connect D:443 -servername D 2>/dev/null | \
    openssl x509 -noout -fingerprint -sha256

# 【3】憑證鏈長度（★ 至少 2）
$ echo | openssl s_client -connect D:443 -servername D -showcerts 2>/dev/null | \
    grep -c 'BEGIN CERTIFICATE'

# 【4】憑證與私鑰是否配對
$ sudo openssl x509 -noout -modulus -in fullchain.pem | openssl md5
$ sudo openssl rsa  -noout -modulus -in privkey.pem   | openssl md5

# 【5】Apache 實際載入的憑證
$ sudo apache2ctl -t -D DUMP_CONFIG 2>/dev/null | grep -E 'SSLCertificate|ServerName'

# 【6】SSL 錯誤日誌（★ 提高等級）
$ sudo sed -i 's/^LogLevel warn$/LogLevel warn ssl:info/' /etc/apache2/apache2.conf
$ sudo systemctl reload apache2
$ sudo tail -f /var/log/apache2/error.log | grep -i ssl
# ★ 測完改回 LogLevel warn

# 【7】RHEL 的加密政策
$ update-crypto-policies --show
$ cat /etc/crypto-policies/back-ends/opensslcnf.config
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> # ★★ 系統加密政策會【覆蓋】Apache 的設定
> $ update-crypto-policies --show
> DEFAULT
>
> # 症狀：SSLProtocol 明明設了 +TLSv1.3，但 SSL Labs 顯示不支援
> #       或設了 -TLSv1.1 但還是可以連
>
> # 各政策的意義：
> #   LEGACY  ：相容舊系統（★ 允許 TLS 1.0/1.1，不要用）
> #   DEFAULT ：TLS 1.2+（一般用這個）
> #   FUTURE  ：更嚴格（TLS 1.2+ 且只有強 cipher）
> #   FIPS    ：符合 FIPS 140-2
>
> $ sudo update-crypto-policies --set DEFAULT
> $ sudo systemctl restart httpd
>
> # SELinux 相關
> $ sudo restorecon -Rv /etc/letsencrypt
> $ sudo setsebool -P httpd_can_network_connect 1     # OCSP Stapling 需要外連
>
> # 憑證位置慣例
> /etc/pki/tls/certs/     憑證
> /etc/pki/tls/private/   私鑰
> ```

---

## 安全性注意事項

> [!danger] 私鑰保護
> ```bash
> $ sudo ls -l /etc/letsencrypt/live/D/privkey.pem
> -rw------- 1 root root ...          # ★ 只有 root
> $ sudo ls -ld /etc/letsencrypt/{live,archive}
> drwx------                          # ★ 目錄也要
> ```
> **Apache 的 master process 以 root 啟動並讀取私鑰，
> 之後才降權成 www-data** —— 所以私鑰不需要給 www-data 讀。
>
> **三個絕對不能做的事**：私鑰進 git、私鑰放 web root、用 email 傳私鑰。
> ```bash
> $ curl -sI https://網站/privkey.pem | head -1     # ★ 必須 404
> $ sudo find /var/www -name '*.key' -o -name '*.pem' 2>/dev/null
> ```

> [!warning] HSTS 的不可逆風險（★ 與 Nginx 相同）
> ```apache
> # 第 1 週
> Header always set Strict-Transport-Security "max-age=300"
> # 第 2-4 週
> Header always set Strict-Transport-Security "max-age=86400"
> # 第 2 個月（★ 確認所有子網域都支援 HTTPS）
> Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"
> # preload ★★ 幾乎不可逆
> ```
> **三個風險**：`includeSubDomains` 會影響所有子網域（還在用 HTTP 的舊系統會被擋死）、
> 憑證過期時使用者**完全無法繞過**、`preload` 移除要等好幾個月。
> 詳見 [[060-02-02-06-guide-Nginx-HTTPS與Certbot]]。

> [!tip] `SSLSessionTickets off` 的理由
> Session ticket 的加密金鑰若不定期輪替，
> 攻擊者取得金鑰就能**解密過去錄下的所有流量**（破壞前向保密）。
> **Apache 沒有內建的自動輪替機制**，所以直接關閉。
> `SSLSessionCache` 已提供大部分的握手效能好處。

---

## 速查表

### 啟用

```bash
sudo a2enmod ssl socache_shmcb headers http2
sudo systemctl restart apache2
# RHEL: sudo dnf install -y mod_ssl
```

### 憑證檔案對應

```
fullchain.pem → SSLCertificateFile        ★ 2.4.8+ 用這個
privkey.pem   → SSLCertificateKeyFile
chain.pem     → SSLCertificateChainFile   ★ 2.4.8 起已廢棄，不需要
cert.pem      → ✗ 不要用（缺中繼，手機會失敗）
```

### ssl-params（全域）

```apache
SSLProtocol             -all +TLSv1.2 +TLSv1.3      # ★ 先關全部再開
SSLCipherSuite          ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:...
SSLHonorCipherOrder     off
SSLCompression          off                          # 防 CRIME
SSLInsecureRenegotiation off
SSLSessionTickets       off                          # ★ 保護前向保密
SSLSessionCache         "shmcb:/var/run/apache2/ssl_scache(512000)"
SSLUseStapling          on
SSLStaplingCache        "shmcb:/var/run/apache2/ssl_stapling(128000)"   # ★ 必須全域
```

### VirtualHost

```apache
<VirtualHost *:443>
    ServerName D
    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/D/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/D/privkey.pem
    SSLUseStapling on
    Protocols h2 http/1.1                            # ★ h2 在前
    Header always set Strict-Transport-Security "max-age=31536000"
    SetEnvIf X-Forwarded-Proto https HTTPS=on
</VirtualHost>
```

### ACME 的 HTTP VirtualHost

```apache
<VirtualHost *:80>
    ServerName D
    Alias /.well-known/acme-challenge /var/www/acme/.well-known/acme-challenge
    <Directory /var/www/acme/.well-known/acme-challenge>
        Require all granted
        ForceType text/plain
    </Directory>
    RedirectMatch permanent "^/(?!\.well-known/acme-challenge)(.*)$" "https://D/$1"
</VirtualHost>
```

### deploy hook（★ 最重要）

```bash
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-apache.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
apache2ctl configtest && systemctl reload apache2
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-apache.sh
sudo certbot renew --dry-run
```

### mTLS

```apache
SSLCACertificateFile /etc/ssl/internal-ca/ca.crt
SSLVerifyClient      require
SSLVerifyDepth       2
SSLCARevocationFile  /etc/ssl/internal-ca/crl.pem
SSLCARevocationCheck chain
RequestHeader set X-Client-CN "%{SSL_CLIENT_S_DN_CN}s"
```

### 排查

```bash
echo | openssl s_client -connect D:443 -servername D -showcerts 2>/dev/null | grep -c 'BEGIN CERT'  # ★ ≥2
openssl x509 -in /etc/letsencrypt/live/D/fullchain.pem -noout -fingerprint -sha256   # ★ 比對線上
echo | openssl s_client -connect D:443 -servername D -status 2>/dev/null | grep 'OCSP Response Status'
sudo apache2ctl -t -D DUMP_CONFIG | grep SSLCertificate
LogLevel warn ssl:info        # ★ 測完改回 warn
update-crypto-policies --show # ★ RHEL 專有
```

### 檢查清單

```
□ SSLCertificateFile 用 fullchain.pem
□ SSLProtocol -all +TLSv1.2 +TLSv1.3
□ SSLSessionTickets off / SSLCompression off
□ SSLStaplingCache 在全域（不在 VirtualHost 內）
□ Protocols h2 http/1.1（★ 需要 event MPM）
□ deploy hook 存在且可執行 ★★
□ certbot renew --dry-run 通過
□ 私鑰 chmod 600、不在 web root、不在 git
□ HSTS 漸進導入
□ ACME 的 Alias 在轉址規則之前
□ SetEnvIf X-Forwarded-Proto https HTTPS=on
□ RHEL: update-crypto-policies 不是 LEGACY
□ SSL Labs A 以上
```

---

## 練習題

> [!question]- 練習 1：完整走一次
> 1. 用 `--staging` 走完整個流程
> 2. 套用 `ssl-params.conf`
> 3. 到 **SSL Labs 檢測，目標 A+**
> 4. 若不是 A+，逐項修正
> 5. **對照 [[060-02-02-06-guide-Nginx-HTTPS與Certbot]]，兩者的設定方式有什麼異同？**

> [!question]- 練習 2：驗證 fullchain 的重要性
> 1. 把 `SSLCertificateFile` 改成 `cert.pem`
> 2. 桌面 Chrome 開啟 → 正常嗎？
> 3. `curl -v https://網域/ 2>&1 | grep -i 'local issuer'`
> 4. `openssl s_client ... -showcerts | grep -c 'BEGIN CERT'` → 幾張？
> 5. 改回 `fullchain.pem`，重測

> [!question]- 練習 3：重現「續期沒 reload」
> 1. 移除 deploy hook
> 2. `sudo certbot renew --force-renewal`
> 3. **不要** reload
> 4. **比對磁碟與線上的憑證指紋** → 不同嗎？
> 5. 建立 hook，重做一次
> 6. 把指紋比對寫成監控腳本

> [!question]- 練習 4：HTTP/2 與 MPM
> 1. 在 **prefork** MPM 下設定 `Protocols h2 http/1.1`
> 2. `apache2ctl configtest` 與 `restart` → **error.log 說什麼？**
> 3. `curl -sI --http2 https://網站/` → 是 HTTP/2 嗎？
> 4. 遷移到 event MPM
> 5. **重測，確認 HTTP/2 生效**

> [!question]- 練習 5：mTLS 實作
> 1. 建立一個內部 CA（見憑證與 PKI 章節）
> 2. 簽發一張客戶端憑證
> 3. 設定 `SSLVerifyClient require` 的 VirtualHost
> 4. `curl --cert client.crt --key client.key https://...` → 成功嗎？
> 5. **不帶憑證測試** → 錯誤訊息是什麼？
> 6. 用 CRL 撤銷該憑證，**再測一次**
> 7. 觀察 `%{SSL_CLIENT_S_DN_CN}` 是否有傳到後端

---

## 小測驗

Q1. **`SSLCertificateFile` 在 Apache 2.4.8 前後的用法有什麼不同？用錯的症狀是什麼**？

Q2. **`SSLProtocol` 為什麼要用「先關全部再開需要的」寫法**？

Q3. **`SSLStaplingCache` 放在 VirtualHost 內會怎樣**？

Q4. **為什麼 HTTP/2 不能搭配 prefork MPM**？

Q5. **憑證續期後 Apache 還在用舊憑證，怎麼修？怎麼監控**？

Q6. **ACME 挑戰的 `Alias` 為什麼要放在轉址規則之前？怎麼寫轉址才不會擋到它**？

Q7. **`SSLSessionTickets` 為什麼建議設成 `off`**？

Q8. **RHEL 上 `SSLProtocol` 設定「看起來沒生效」，第一個該檢查什麼**？

Q9. **`SSLStrictSNIVHostCheck` 設成 `on` 與 `off` 有什麼差別與取捨**？

Q10. **mTLS 相對 API Key 有哪三個優勢？Apache 怎麼把客戶端憑證資訊傳給後端**？

> [!question]- 測驗答案
> **Q1.** **Apache < 2.4.8**：`SSLCertificateFile` 放**只有自己的憑證**（`cert.pem`），
> 中繼憑證要用**另一個指令 `SSLCertificateChainFile`** 指定（`chain.pem`）。
> **Apache ≥ 2.4.8**：`SSLCertificateFile` 直接放 **`fullchain.pem`**
> （自己的憑證 + 中繼憑證合在一起），
> **`SSLCertificateChainFile` 已被廢棄**（寫了會有 deprecation 警告）。
> **用錯的症狀**（與 Nginx 相同）：
> **桌面版 Chrome / Firefox 正常**（它們會自己去 AIA 抓中繼憑證），
> 但**手機 App、`curl`、Java、舊版 Android 全部憑證驗證失敗**。
> 驗證：`openssl s_client ... -showcerts | grep -c 'BEGIN CERTIFICATE'` **至少要 2**。
>
> **Q2.** 因為 **`SSLProtocol all -TLSv1 -TLSv1.1` 這種「減法」寫法
> 在不同 OpenSSL 版本與不同發行版上的行為並不一致** ——
> `all` 涵蓋的範圍會隨版本改變，可能意外留下不該啟用的協定。
> **`SSLProtocol -all +TLSv1.2 +TLSv1.3`（先全部關掉，再明確開啟需要的）
> 是明確且可預測的**，不論 OpenSSL 版本如何都只會啟用你列出的那兩個。
>
> **Q3.** 會啟動失敗並報錯：
> ```
> AH02172: SSLStaplingCache: unknown or unsupported cache type
> ```
> 因為 **`SSLStaplingCache` 是「伺服器層級」的指令，必須設定在全域**
> （`httpd.conf` 或 `conf-available/ssl-params.conf`），
> **不能放在 `<VirtualHost>` 區塊內** ——
> 它配置的是所有 VirtualHost 共用的一塊共享記憶體。
> 同理，`SSLSessionCache` 也必須在全域。
> 而 `SSLUseStapling on` 則可以（也應該）寫在各個 VirtualHost 中。
>
> **Q4.** 因為 **`mod_http2` 需要多執行緒的 MPM（event 或 worker）** ——
> HTTP/2 的多工特性要求在單一連線上並行處理多個串流，
> 這需要執行緒模型的支援；prefork 的「一個程序處理一個連線」模型做不到。
> 症狀：
> ```
> AH10034: The mpm module (prefork.c) is not supported by mod_http2.
> mod_http2 requires an event or worker MPM.
> ```
> **這又是一個離開 `mod_php` + prefork 的理由** ——
> 因為 `mod_php` 不是執行緒安全的，強迫你用 prefork，也就用不了 HTTP/2。
> 解法是改用 **event MPM + PHP-FPM**。
>
> **Q5.** 原因是 **Certbot 續期後沒有通知 Apache 重新載入** ——
> Apache 把憑證讀進記憶體，不會自己重新讀檔。
> **修法**：建立 deploy hook：
> ```bash
> sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-apache.sh <<'EOF'
> #!/usr/bin/env bash
> set -euo pipefail
> apache2ctl configtest && systemctl reload apache2
> EOF
> sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-apache.sh
> ```
> **監控方式**：**比對「磁碟上憑證的 SHA-256 指紋」與
> 「從外部連線取得的憑證指紋」** ——
> ```bash
> openssl x509 -in /etc/letsencrypt/live/D/fullchain.pem -noout -fingerprint -sha256
> echo | openssl s_client -connect D:443 -servername D 2>/dev/null | \
>   openssl x509 -noout -fingerprint -sha256
> ```
> 不一致就代表沒有 reload。只檢查檔案到期日抓不到這個問題。
>
> **Q6.** 因為若 HTTP 的 VirtualHost 寫成「把所有請求都轉到 HTTPS」，
> **ACME 的驗證請求（`http://網域/.well-known/acme-challenge/xxx`）
> 也會被 301 轉走，導致 Let's Encrypt 拿不到驗證檔案，申請永遠失敗**
> （錯誤訊息：`Invalid response ... : 301`）。
> **正確寫法是用負向前瞻（negative lookahead）排除挑戰路徑**：
> ```apache
> Alias /.well-known/acme-challenge /var/www/acme/.well-known/acme-challenge
> <Directory /var/www/acme/.well-known/acme-challenge>
>     Require all granted
>     ForceType text/plain
> </Directory>
> RedirectMatch permanent "^/(?!\.well-known/acme-challenge)(.*)$" "https://D/$1"
> ```
>
> **Q7.** 因為 **session ticket 的加密金鑰若不定期輪替，
> 攻擊者只要取得那把金鑰，就能解密過去所有錄下的流量** ——
> 這會**破壞前向保密（Forward Secrecy）**。
> **Apache 沒有內建的自動金鑰輪替機制**，
> 除非你自己實作輪替，否則應該直接 `SSLSessionTickets off`。
> `SSLSessionCache shmcb:...` 已經能提供大部分的握手效能好處
> （它的 session 資料存在伺服器端，不會有這個問題）。
>
> **Q8.** **系統加密政策（`update-crypto-policies`）** ——
> 這是 RHEL 8/9 特有的機制，它**在 OpenSSL 層級統一設定全系統的加密政策，
> 會覆蓋（或限制）應用層的設定**。
> ```bash
> $ update-crypto-policies --show
> DEFAULT
> ```
> 政策選項：**`LEGACY`**（相容舊系統，**允許 TLS 1.0/1.1，不要用**）、
> **`DEFAULT`**（TLS 1.2+，一般用這個）、
> `FUTURE`（更嚴格）、`FIPS`（符合 FIPS 140-2）。
> 典型症狀：`SSLProtocol` 設了 `+TLSv1.3` 但 SSL Labs 顯示不支援，
> 或設了 `-TLSv1.1` 但外部還是連得上。
> ```bash
> $ sudo update-crypto-policies --set DEFAULT
> $ sudo systemctl restart httpd
> ```
>
> **Q9.** **`off`（預設）**：不支援 SNI 的舊客戶端連進來時，
> **會拿到「第一個 VirtualHost 的憑證」** ——
> 這可能導致「意外洩漏另一個網站的憑證資訊」，
> 而且使用者會看到憑證網域不符的警告。
> **`on`（嚴格）**：**不送 SNI 的客戶端直接被拒絕（403）**，
> 不會拿到任何憑證。
> **取捨**：現代客戶端全部支援 SNI，設成 `on` 更安全；
> 但會擋掉極舊的裝置（Windows XP 的 IE、Android 2.x）。
> 對機關內部系統或面向現代瀏覽器的服務，**建議設成 `on`**。
>
> **Q10.** **三個優勢**：
> ①**憑證有有效期與撤銷機制（CRL / OCSP）** ——
> API Key 一旦外流往往無限期有效，且很難全面撤換；
> ②**私鑰不會在網路上傳輸** ——
> API Key 每次請求都要送出，任何一個中間環節（日誌、代理）都可能記錄下來；
> ③**在 TLS 層就能擋掉未授權的連線，根本不進到應用層** ——
> 減少攻擊面，也不消耗應用資源。
> **傳給後端的方式**：
> ```apache
> SSLVerifyClient require
> SSLCACertificateFile /etc/ssl/internal-ca/ca.crt
> RequestHeader set X-Client-DN     "%{SSL_CLIENT_S_DN}s"
> RequestHeader set X-Client-CN     "%{SSL_CLIENT_S_DN_CN}s"
> RequestHeader set X-Client-Serial "%{SSL_CLIENT_M_SERIAL}s"
> RequestHeader set X-Client-Verify "%{SSL_CLIENT_VERIFY}s"
> ```
> 後端讀這些標頭做授權判斷。
> 也可以直接在 Apache 就限制：
> `Require expr %{SSL_CLIENT_S_DN_O} == "Example Government Agency"`。
> **注意**：後端必須確認這些標頭**只可能來自 Apache**
> （後端只綁 127.0.0.1），否則攻擊者可以偽造。

---

## 延伸閱讀

- [[060-02-03-06-guide-Apache-與PHP整合]] — 下一步：PHP 整合
- [[060-02-03-07-guide-Apache-安全與效能]] — 完整加固
- [[060-02-03-03-guide-Apache-模組與MPM]] — event MPM（HTTP/2 的前提）
- [[060-02-02-06-guide-Nginx-HTTPS與Certbot]] — 對照 Nginx；HSTS 的完整說明
- [[090-01-00-idx-PKI-憑證與PKI]] — 憑證原理、自簽憑證鏈、內部 CA
