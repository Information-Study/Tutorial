---
title: "autocert 自動憑證模組"
desc: "NGINX 內建的 ACME 客戶端，一行設定取代 certbot 與 cron"
aliases: [autocert, nginx-autocert-module, ACME, 自動憑證, 免 certbot]
tags: [群組/軟體與開發工具, 服務/nginx, 服務/myguard, 主題/憑證]
category: MyGuard與Angie
difficulty: 進階
status: 完成
distro: [ubuntu]
prerequisites: ["[[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]]", "[[060-02-02-06-guide-Nginx-HTTPS與Certbot]]"]
updated: 2026-08-28
---

# autocert 自動憑證模組

> [!abstract] 這篇你會學到
> - **★★★★ 一行 `autocert on;` 取代整套 certbot 流程**
> - 完整的指令清單與參數
> - **★★★ 三種 challenge**（http-01 / tls-alpn-01 / dns-01）
> - **★★★★ 雙憑證（EC + RSA）**與金鑰類型
> - 私有 CA、EAB、憑證儲存佈局
> - **★★★★ 從 certbot 遷移**
> - 排錯與速率限制的處理

> [!warning] 未實機驗證 ★★★
> ```
> ★★★ 本章依據 https://github.com/myguard-labs/nginx-autocert-module
>      2026 年 8 月的文件撰寫。
>
> ★★★★ 實作前請對照官方 README 確認指令的完整參數。
> ★★ 模組仍在演進，指令可能新增或調整。
> ```

## 前置知識

- [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]] — 套件庫的加入
- [[060-02-02-06-guide-Nginx-HTTPS與Certbot]] — **★★★ certbot 的傳統做法**（★ 用來對照）
- [[090-01-12-guide-PKI-憑證生命週期管理]] — 憑證的生命週期

---

## ★★★★ 它解決了什麼

```
★★★★ certbot 流程的五個痛點：

  ① ★★★★ 【續期成功但 reload 失敗】← 最嚴重
     certbot renew 成功 → deploy-hook 的 reload 失敗（設定有錯、權限問題）
     → ★★★ 憑證檔案更新了，但 nginx 記憶體中還是舊的
     → ★★★★ 【過期當天才發現】

  ② ★★★ 【cron 停了沒人知道】
     → cron 服務沒啟動、腳本被改壞、systemd timer 被 disable
     → ★★ 沒有告警的話，兩個月後憑證過期

  ③ ★★ 【challenge 路徑的設定容易出錯】
     → .well-known/acme-challenge 被 HTTPS 重導向攔截
     → 被 try_files 吃掉
     → ★★★ location 的優先順序搞錯

  ④ ★★ 【多一個程式要維護】
     → certbot 本身的更新、Python 相依、snap 版本的問題

  ⑤ ★★ 【新增網域要重跑一次流程】

★★★★ autocert 的做法：
  ┌────────────────────────────────────────────────┐
  │  server {                                       │
  │      listen 443 ssl;                            │
  │      server_name app.example.gov.tw;            │
  │      autocert on;          ← ★★★★ 就這一行      │
  │  }                                              │
  └────────────────────────────────────────────────┘

  → NGINX 自己：申請 → 提供 → 續期
  → ★★★★ 憑證【熱載入】，不需要 reload
  → ★★★ challenge 由模組自己處理，不用設 location
  → ★★ 沒有 cron、沒有 certbot、沒有 deploy hook
```

---

## 安裝

```bash
# ★★★ 見 [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]] 設定套件庫後
$ sudo apt install -y nginx libnginx-mod-http-autocert
#   ★★★ 套件名稱可能不同，先搜尋
$ apt-cache search autocert
$ apt-cache search '^libnginx-mod-.*acme|^libnginx-mod-.*autocert'

# ★★★ 確認模組檔案
$ ls -l /usr/lib/nginx/modules/ | grep -i autocert
-rw-r--r-- 1 root root 148K ... ngx_http_autocert_module.so

# ★★★ 確認載入設定（★ MyGuard 的套件通常會自動建立）
$ ls /etc/nginx/modules-enabled/
50-mod-http-autocert.conf
$ cat /etc/nginx/modules-enabled/50-mod-http-autocert.conf
load_module modules/ngx_http_autocert_module.so;

# ★★ 手動載入（★ 一定要在 nginx.conf 的最上層，http 區塊之前）
$ sudo sed -i '1i load_module modules/ngx_http_autocert_module.so;' /etc/nginx/nginx.conf

$ sudo nginx -t
$ sudo nginx -V 2>&1 | tr ' ' '\n' | grep -i autocert
```

---

## ★★★★ 最小可用設定

```nginx
# /etc/nginx/nginx.conf
load_module modules/ngx_http_autocert_module.so;    # ★★★ 最上層

http {
    # ★★★★ 一定要有 resolver（★ ACME 客戶端要解析 CA 的網域）
    resolver 1.1.1.1 8.8.8.8 valid=300s ipv6=off;

    # ★★★ ACME 帳號的聯絡信箱（★ 憑證快過期時 CA 會通知）
    autocert_contact admin@example.gov.tw;

    server {
        listen 80;
        listen 443 ssl;
        http2 on;
        server_name app.example.gov.tw www.app.example.gov.tw;

        autocert on;                    # ★★★★ 就這一行

        ssl_protocols TLSv1.2 TLSv1.3;

        location / {
            root /var/www/app/current/public;
            try_files $uri $uri/ /index.php?$query_string;
        }
    }
}
```

```bash
$ sudo nginx -t && sudo systemctl reload nginx

# ★★★ 觀察申請過程
$ sudo tail -f /var/log/nginx/error.log | grep -i autocert
2026/08/28 18:45:11 [notice] 1234#1234: autocert: requesting certificate for app.example.gov.tw
2026/08/28 18:45:14 [notice] 1234#1234: autocert: http-01 challenge ready
2026/08/28 18:45:18 [notice] 1234#1234: autocert: certificate issued, valid until 2026-11-26

# ★★★ 驗證
$ echo | openssl s_client -connect app.example.gov.tw:443 \
    -servername app.example.gov.tw 2>/dev/null | \
    openssl x509 -noout -subject -issuer -dates
subject=CN = app.example.gov.tw
issuer=C = US, O = Let's Encrypt, CN = R11
notAfter=Nov 26 23:59:59 2026 GMT
```

> [!danger] 三件必做的事 ★★★★
> ```
> ① ★★★★ 【先用 staging 測試】
>      autocert_staging on;
>      → ★★★ Let's Encrypt 正式環境的速率限制：
>        · 同一註冊網域每週 50 張
>        · ★★★★ 失敗的驗證每小時 5 次
>      → 設定錯誤反覆重試會被鎖住！
>
> ② ★★★★ 【一定要設 resolver】
>      → ACME 客戶端要解析 CA 的網域
>      → ★★★ 沒設會失敗且訊息不明顯
>      → ipv6=off 避免沒有 IPv6 時的逾時
>
> ③ ★★★ 【http-01 需要 80 埠可達】
>      → 防火牆放行 80
>      → ★★★★ 不要把 80 【全部】301 到 443
>      → 內網服務用 dns-01
> ```

```nginx
# ★★★★ 開發階段的正確設定
http {
    resolver 1.1.1.1 valid=300s ipv6=off;
    autocert_contact admin@example.gov.tw;
    autocert_staging on;                # ★★★★ 測試時開，上線前關

    server {
        listen 443 ssl;
        server_name app.example.gov.tw;
        autocert on;
    }
}
```

---

## ★★★ 完整指令清單

### 基本

| 指令 | 語境 | 預設 | 說明 |
| --- | --- | --- | --- |
| **`autocert on\|off`** | http, server | `off` | **★★★★ 主開關** |
| **`autocert_contact <email>`** | http, server | 無 | **★★★ ACME 帳號的聯絡信箱**（★ 純位址，不加 `mailto:`） |
| **`autocert_ca <url>`** | http, server | LE 正式 | ACME directory URL |
| **`autocert_staging on\|off`** | http, server | `off` | **★★★★ LE staging 的簡寫**（★ 與 `autocert_ca` 互斥） |
| `autocert_wildcard *.rest` | http, server | 無 | **★★ 宣告萬用 SAN**（★ 僅 dns-01） |

### 憑證與金鑰

| 指令 | 語境 | 預設 | 說明 |
| --- | --- | --- | --- |
| **`autocert_key_type <type>`** | http | `p384` | **★★★ 葉憑證的金鑰類型**（見下） |
| **`autocert_challenge <type>`** | http | `http-01` | **★★★ `http-01` / `tls-alpn-01` / `dns-01`** |
| **`autocert_renew_before <time>`** | http | `7d` | **★★★ 到期前多久續期**（`>0`，`≤89d`） |
| `autocert_runtime_ttl <time>` | http | `7d` | 執行期請求的名稱的閒置 TTL |
| `autocert_profile <name>` | http | 無 | ACME 簽發設定檔（★ 例如 IP 憑證用 `shortlived`） |

### 儲存

| 指令 | 語境 | 預設 | 說明 |
| --- | --- | --- | --- |
| **`autocert_store_path <path>`** | http | `autocert` | **★★★ 憑證與帳號金鑰的儲存根目錄** |
| **`autocert_store_layout default\|certbot`** | http | `default` | **★★ 磁碟佈局**（★ `certbot` 相容既有工具） |

### DNS 解析

| 指令 | 語境 | 預設 | 說明 |
| --- | --- | --- | --- |
| `autocert_resolver <addr>` | http | 回退到核心 resolver | 解析 CA 用的 DNS |
| `autocert_resolver_timeout <time>` | http | `30s` | 解析逾時 |

### DNS-01 challenge

| 指令 | 語境 | 預設 | 說明 |
| --- | --- | --- | --- |
| **`autocert_dns_hook_add <path>`** | http | 無 | **★★★ 新增 TXT 記錄的 hook**（絕對路徑） |
| **`autocert_dns_hook_remove <path>`** | http | 無 | **★★★ 移除 TXT 記錄的 hook** |
| `autocert_dns_propagation_delay <time>` | http | `10s` | **★★ add hook 之後等待 CA 驗證的時間** |
| `autocert_dns_hook_timeout <time>` | http | `30s` | 每次 hook 執行的逾時（`>0`） |

### 私有 CA / EAB

| 指令 | 語境 | 說明 |
| --- | --- | --- |
| `autocert_ca_trusted_certificate <file>` | http, server | **★★ 私有 CA 的 TLS 端點的信任 bundle** |
| `autocert_ca_issuance_certificate <file>` | http, server | 驗證簽發鏈的錨點 |
| `autocert_eab_kid <key-id>` | http, server | **★★ External Account Binding 的 key ID** |
| `autocert_eab_hmac_key <b64url>` | http, server | EAB 的 HMAC 金鑰（base64url） |

---

## ★★★ 金鑰類型與雙憑證

```nginx
# ★★★ 支援的類型
autocert_key_type p384;         # ★★★ 預設（★ EC，最好的效能與安全平衡）
autocert_key_type p256;         # ★★ EC，相容性最好
autocert_key_type rsa2048;      # ★★ RSA，最舊的相容性
autocert_key_type rsa3072;
autocert_key_type rsa4096;      # ★ 最慢

# ★★★★ 雙憑證：同時簽 EC 與 RSA（★ 最多一個 EC + 一個 RSA）
autocert_key_type p384 rsa2048;
```

```
★★★★ 為什麼要雙憑證：

  ★★★ EC（橢圓曲線）憑證：
    ✓ 交握快（★ 比 RSA 快 2~3 倍）
    ✓ 金鑰小、CPU 負擔低
    ✗ ★★ 非常舊的客戶端不支援
      （Windows XP、Android 4.3 以前、Java 7 以前）

  ★★★ RSA 憑證：
    ✓ 相容性最好
    ✗ 交握慢、CPU 負擔高

  ★★★★ 雙憑證的做法：
    → 伺服器同時持有兩張憑證
    → ★★★ TLS 交握時依客戶端支援的演算法【自動選擇】
    → 現代瀏覽器用 EC（快），舊客戶端用 RSA（能連）

★★★ 什麼時候需要：
  · 機關的對外服務（★★ 可能有很舊的客戶端）
  · ★★ 要相容舊的 IE / 舊的 Android App
  · ★★★ 純內部或現代化的服務 → p384 就好
```

```bash
# ★★★ 驗證雙憑證生效
$ echo | openssl s_client -connect app.example.gov.tw:443 \
    -servername app.example.gov.tw -sigalgs 'ecdsa_secp384r1_sha384' 2>/dev/null | \
    openssl x509 -noout -text | grep -A2 'Public Key Algorithm'
        Public Key Algorithm: id-ecPublicKey
            Public-Key: (384 bit)

$ echo | openssl s_client -connect app.example.gov.tw:443 \
    -servername app.example.gov.tw -sigalgs 'rsa_pkcs1_sha256' 2>/dev/null | \
    openssl x509 -noout -text | grep -A2 'Public Key Algorithm'
        Public Key Algorithm: rsaEncryption
            RSA Public-Key: (2048 bit)
#   ★★★★ 兩個都拿得到 = 雙憑證正常

# ★★ 用 nmap 看密碼套件
$ nmap --script ssl-enum-ciphers -p 443 app.example.gov.tw | grep -E 'ecdsa|rsa'
```

---

## ★★★ 三種 challenge

### http-01（預設）

```nginx
http {
    autocert_challenge http-01;         # ★ 預設，可省略

    server {
        listen 80;                      # ★★★★ 一定要有
        listen 443 ssl;
        server_name app.example.gov.tw;
        autocert on;
    }
}
```

```
★★★ 需求：
  · ★★★★ 80 埠從【外網】可達
  · 網域的 A/AAAA 記錄指向這台伺服器

★★★★ 最常見的問題：把 80 全部重導向到 443
```

```nginx
# ★★★★ 錯誤的做法（★ 會讓 http-01 失敗）
server {
    listen 80;
    server_name app.example.gov.tw;
    return 301 https://$host$request_uri;      # ★★★★ 全部重導向
}

# ★★★ 正確：autocert 模組會自己處理 challenge 路徑
#   → ★★★ 模組在 PREACCESS 階段攔截，優先於 return
#   → ★★ 但保險起見，可以明確排除：
server {
    listen 80;
    server_name app.example.gov.tw;
    autocert on;                        # ★★★ 讓模組處理 challenge

    location / {
        return 301 https://$host$request_uri;
    }
}
```

### tls-alpn-01

```nginx
http {
    autocert_challenge tls-alpn-01;

    server {
        listen 443 ssl;                 # ★★★ 只要 443
        server_name app.example.gov.tw;
        autocert on;
    }
}
```

```
★★★ 特點：
  ✓ ★★ 不需要 80 埠
  ✓ 完全在 TLS 層完成（用特殊的 ALPN 協定）
  ✗ ★★★ 有些 CDN / 負載平衡器會擋掉（★ 它們自己終止 TLS）

★★ 適合：只開 443 的環境
```

### ★★★★ dns-01（內網服務與萬用憑證）

```nginx
http {
    autocert_challenge dns-01;
    autocert_dns_hook_add    /usr/local/bin/acme-dns-add;
    autocert_dns_hook_remove /usr/local/bin/acme-dns-remove;
    autocert_dns_propagation_delay 30s;      # ★★★ 依 DNS provider 調整
    autocert_dns_hook_timeout 60s;

    server {
        listen 443 ssl;
        server_name internal.example.gov.tw;
        autocert on;
        autocert_wildcard *.internal.example.gov.tw;    # ★★★★ 萬用憑證
    }
}
```

```bash
#!/usr/bin/env bash
# ★★★★ /usr/local/bin/acme-dns-add —— 新增 TXT 記錄
# ★★★ 模組會傳入：$1=網域  $2=TXT 值
#     （★ 實際的參數傳遞方式請對照官方文件）
set -euo pipefail

DOMAIN="$1"
TXT_VALUE="$2"
RECORD="_acme-challenge.${DOMAIN#\*.}"

# ═══ ★★ 以 Cloudflare 為例 ═══
CF_TOKEN=$(cat /etc/acme/cloudflare.token)     # ★★★ chmod 600
ZONE_NAME=$(echo "$DOMAIN" | rev | cut -d. -f1,2 | rev)

ZONE_ID=$(curl -sf -H "Authorization: Bearer $CF_TOKEN" \
    "https://api.cloudflare.com/client/v4/zones?name=$ZONE_NAME" | \
    jq -r '.result[0].id')

curl -sf -X POST \
    -H "Authorization: Bearer $CF_TOKEN" \
    -H 'Content-Type: application/json' \
    "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records" \
    -d "$(jq -n --arg n "$RECORD" --arg c "$TXT_VALUE" \
          '{type:"TXT", name:$n, content:$c, ttl:60}')" | \
    jq -e '.success' >/dev/null

logger -t acme-dns "已新增 TXT $RECORD"

# ★★★ 等待傳播（★ 主動確認比固定 sleep 好）
for i in $(seq 1 30); do
    if dig +short "@1.1.1.1" TXT "$RECORD" | grep -qF "$TXT_VALUE"; then
        logger -t acme-dns "TXT 已傳播（第 $i 次檢查）"
        exit 0
    fi
    sleep 2
done
logger -t acme-dns "★★★ TXT 傳播逾時"
exit 1
```

```bash
#!/usr/bin/env bash
# ★★★ /usr/local/bin/acme-dns-remove —— 移除 TXT 記錄
set -euo pipefail
DOMAIN="$1"
RECORD="_acme-challenge.${DOMAIN#\*.}"

CF_TOKEN=$(cat /etc/acme/cloudflare.token)
ZONE_NAME=$(echo "$DOMAIN" | rev | cut -d. -f1,2 | rev)
ZONE_ID=$(curl -sf -H "Authorization: Bearer $CF_TOKEN" \
    "https://api.cloudflare.com/client/v4/zones?name=$ZONE_NAME" | jq -r '.result[0].id')

curl -sf -H "Authorization: Bearer $CF_TOKEN" \
    "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records?type=TXT&name=$RECORD" | \
  jq -r '.result[].id' | while read -r id; do
    curl -sf -X DELETE -H "Authorization: Bearer $CF_TOKEN" \
        "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records/$id" >/dev/null
  done

logger -t acme-dns "已移除 TXT $RECORD"
```

```bash
$ sudo install -m750 -o root -g root acme-dns-add.sh /usr/local/bin/acme-dns-add
$ sudo install -m750 -o root -g root acme-dns-remove.sh /usr/local/bin/acme-dns-remove
$ sudo install -d -m 700 /etc/acme
$ echo 'CF_API_TOKEN' | sudo tee /etc/acme/cloudflare.token
$ sudo chmod 600 /etc/acme/cloudflare.token
#   ★★★★ Cloudflare token 只給【該 zone 的 DNS 編輯】權限，不要用 Global API Key
```

> [!danger] DNS hook 的安全 ★★★★
> ```
> ★★★★ hook 腳本以【nginx 的 worker 使用者】執行，而且持有 DNS API token
>
>   → ★★★ token 洩漏 = 攻擊者可以【改你的 DNS】
>     · 把網域指到他的伺服器
>     · ★★★★ 為你的網域簽發憑證（中間人攻擊）
>
> ★★★ 四個防護：
>   ① ★★★★ token 用【最小權限】
>      → Cloudflare：只給該 zone 的 Zone:DNS:Edit
>      → ★★★★ 絕對不要用 Global API Key
>   ② ★★★ token 檔案 chmod 600，目錄 700
>   ③ ★★ hook 腳本 750，不可被 worker 使用者寫入
>   ④ ★★★ 用 CAA 記錄限制只有你用的 CA 能簽發
>      example.gov.tw. CAA 0 issue "letsencrypt.org"
> ```

---

## ★★★★ 從 certbot 遷移

```bash
#!/usr/bin/env bash
# ★★★★ /usr/local/bin/migrate-certbot-to-autocert
set -euo pipefail

echo "═══ certbot → autocert 遷移 ═══"

# ═══ ★★★【1】盤點現有憑證 ═══
echo -e "\n【1】現有的 certbot 憑證"
sudo certbot certificates 2>/dev/null | grep -E 'Certificate Name|Domains|Expiry' | sed 's/^/  /'

DOMAINS=$(sudo certbot certificates 2>/dev/null | \
    grep -oP 'Domains: \K.*' | tr ' ' '\n' | sort -u)
echo "  ★ 共 $(echo "$DOMAINS" | wc -l) 個網域"

# ═══ ★★★【2】備份 ═══
echo -e "\n【2】備份"
TS=$(date +%Y%m%d-%H%M%S)
sudo tar -czf "/root/letsencrypt-$TS.tar.gz" /etc/letsencrypt/
sudo tar -czf "/root/nginx-conf-$TS.tar.gz" /etc/nginx/
echo "  ★ /root/letsencrypt-$TS.tar.gz"
echo "  ★ /root/nginx-conf-$TS.tar.gz"

# ═══ ★★★【3】安裝模組 ═══
echo -e "\n【3】安裝 autocert 模組"
sudo apt install -y libnginx-mod-http-autocert 2>/dev/null || \
  echo "  ★★ 套件名稱可能不同，用 apt-cache search autocert 找"
ls -l /usr/lib/nginx/modules/ | grep -i autocert | sed 's/^/  /'

# ═══ ★★★★【4】改設定（★ 先在測試環境）═══
echo -e "\n【4】★★★★ 修改設定"
cat <<'GUIDE'
  ★★★ 在 http 區塊加入：
      resolver 1.1.1.1 8.8.8.8 valid=300s ipv6=off;
      autocert_contact admin@example.gov.tw;
      autocert_staging on;              # ★★★★ 先用 staging！
      autocert_key_type p384 rsa2048;   # ★★ 雙憑證

  ★★★ 在每個 server 區塊：
      - ssl_certificate     /etc/letsencrypt/live/xxx/fullchain.pem;   ← 移除
      - ssl_certificate_key /etc/letsencrypt/live/xxx/privkey.pem;     ← 移除
      + autocert on;                                                   ← 加入

  ★★★★ 移除 .well-known 的 location（模組自己處理）
GUIDE

# ═══ ★★★【5】停用 certbot 的自動續期 ═══
echo -e "\n【5】★★★ 停用 certbot 的續期"
sudo systemctl list-timers 'certbot*' --no-pager | sed 's/^/  /'
echo "  ★★ 確認遷移成功後才執行："
echo "     sudo systemctl disable --now certbot.timer"
echo "     sudo rm -f /etc/cron.d/certbot"

echo -e "\n★★★ 遷移步驟："
echo "  ① 改設定（staging）→ nginx -t → reload"
echo "  ② 看日誌確認申請成功"
echo "  ③ 改成正式（autocert_staging off）→ reload"
echo "  ④ ★★★★ 驗證憑證的 issuer 是正式的 Let's Encrypt"
echo "  ⑤ 停用 certbot.timer"
echo "  ⑥ ★★ 觀察一週確認自動續期正常後，才刪除 /etc/letsencrypt"
```

```nginx
# ═══ ★★★ 遷移前 ═══
server {
    listen 80;
    server_name app.example.gov.tw;

    # ★★★ certbot 的 challenge location
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
        try_files $uri =404;
    }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    http2 on;
    server_name app.example.gov.tw;

    # ★★★ certbot 的憑證
    ssl_certificate     /etc/letsencrypt/live/app.example.gov.tw/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.example.gov.tw/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    location / { root /var/www/app/current/public; }
}

# ═══ ★★★★ 遷移後 ═══
server {
    listen 80;
    listen 443 ssl;
    http2 on;
    server_name app.example.gov.tw;

    autocert on;                        # ★★★★ 取代上面全部的憑證設定

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_stapling on;
    ssl_stapling_verify on;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        root /var/www/app/current/public;
        try_files $uri $uri/ /index.php?$query_string;
    }
}
#   ★★★ .well-known 的 location 不用了，模組自己處理
```

```bash
# ═══ ★★★★ 遷移的驗證檢查表 ═══
$ sudo tee /usr/local/bin/autocert-verify >/dev/null <<'EOF'
#!/usr/bin/env bash
DOMAIN="${1:?用法: autocert-verify <網域>}"
FAIL=0
echo "═══ autocert 驗證: $DOMAIN ═══"

# ★★★ 憑證資訊
INFO=$(echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null | \
       openssl x509 -noout -subject -issuer -dates -ext subjectAltName 2>/dev/null)
echo "$INFO" | sed 's/^/  /'

# ★★★★ 不能是 staging
if echo "$INFO" | grep -qi 'STAGING'; then
    echo "  ★★★★ 這是 STAGING 憑證！瀏覽器不會信任"
    FAIL=$((FAIL+1))
else
    echo "  ✓ 正式憑證"
fi

# ★★★ 剩餘天數
EXP=$(echo "$INFO" | grep -oP 'notAfter=\K.*')
DAYS=$(( ($(date -d "$EXP" +%s) - $(date +%s)) / 86400 ))
printf '  剩餘 %s 天  ' "$DAYS"
[ "$DAYS" -gt 20 ] && echo "✓" || { echo "★★★★ 該續期了"; FAIL=$((FAIL+1)); }

# ★★★★ 憑證鏈完整
N=$(echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" \
      -showcerts 2>/dev/null | grep -c 'BEGIN CERTIFICATE')
printf '  憑證鏈 %s 張  ' "$N"
[ "$N" -ge 2 ] && echo "✓" || { echo "★★★★ 缺中繼憑證"; FAIL=$((FAIL+1)); }

# ★★★ 驗證通過
if echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>&1 | \
     grep -q 'Verify return code: 0 (ok)'; then
    echo "  ✓ 憑證驗證通過"
else
    echo "  ★★★★ 憑證驗證失敗"
    FAIL=$((FAIL+1))
fi

# ★★ 雙憑證
echo "  ── 金鑰類型 ──"
for sa in 'ecdsa_secp384r1_sha384' 'rsa_pkcs1_sha256'; do
    alg=$(echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" \
          -sigalgs "$sa" 2>/dev/null | openssl x509 -noout -text 2>/dev/null | \
          grep -oP 'Public Key Algorithm: \K.*' | head -1)
    printf '    %-28s %s\n' "$sa" "${alg:-（不支援）}"
done

# ★★★ 儲存目錄
echo "  ── 儲存 ──"
sudo find /var/lib/nginx /var/cache/nginx -name '*.pem' -path '*autocert*' 2>/dev/null | \
    head -5 | sed 's/^/    /' || echo "    （用 nginx -T 查 autocert_store_path）"

echo ""
[ "$FAIL" -eq 0 ] && echo "★ 全部通過" || echo "★★★★ $FAIL 項有問題"
exit "$FAIL"
EOF
$ sudo chmod +x /usr/local/bin/autocert-verify
$ autocert-verify app.example.gov.tw
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`unknown directive "autocert"`** ★★★★ | **模組沒載入** | `load_module` 放在 nginx.conf 最上層 |
| **一直申請失敗** ★★★★ | **沒設 `resolver`** | **`resolver 1.1.1.1 ipv6=off;`** |
| **被 CA 鎖住** ★★★★ | **速率限制** | **先用 `autocert_staging on`**；等一小時/一週 |
| **http-01 失敗** ★★★ | 80 不可達／被防火牆擋 | 放行 80；`curl -I http://domain/` 測試 |
| **DNS-01 hook 失敗** ★★★ | 權限／token／路徑 | hook 用絕對路徑；`chmod 750`；看 `logger` |
| **DNS-01 傳播逾時** ★★★ | `propagation_delay` 太短 | 調大；hook 內主動 `dig` 確認 |
| **拿到 STAGING 憑證** ★★★★ | 忘記關 staging | **`autocert_staging off;`** + reload |
| **憑證沒有自動續期** ★★★ | `renew_before` 設定 | 預設 `7d`；看 error.log |
| **雙憑證只有一種生效** ★★ | 客戶端不支援 | 用 `-sigalgs` 分別測試 |
| **儲存目錄權限錯誤** ★★★ | worker 使用者不能寫 | 確認 `autocert_store_path` 的擁有者 |
| **通配憑證失敗** ★★★★ | **只有 dns-01 支援** | `autocert_challenge dns-01` + `autocert_wildcard` |

### 排查

```bash
# 【1】★★★★ 模組是否載入
$ sudo nginx -T 2>/dev/null | grep -i 'load_module.*autocert'
$ ls -l /usr/lib/nginx/modules/ | grep -i autocert
$ sudo nginx -t

# 【2】★★★★ 日誌（★ 最重要）
$ sudo tail -100 /var/log/nginx/error.log | grep -i autocert
$ sudo journalctl -u nginx --since '10 min ago' | grep -i -E 'autocert|acme'

# ★★★ 提高日誌等級（★ 排查時）
#   error_log /var/log/nginx/error.log info;
$ sudo sed -i 's#^\(\s*error_log.*error.log\)\s*;#\1 info;#' /etc/nginx/nginx.conf
$ sudo nginx -t && sudo systemctl reload nginx

# 【3】★★★ 目前的設定
$ sudo nginx -T 2>/dev/null | grep -E 'autocert|resolver'

# 【4】★★★★ http-01 的可達性
$ curl -sI "http://app.example.gov.tw/.well-known/acme-challenge/test"
#   ★★★ 應該回 404（不是 301！）
$ dig +short app.example.gov.tw
$ sudo ss -tlnp | grep ':80 '
$ sudo nft list ruleset | grep -A3 'dport 80'

# 【5】★★★ DNS-01
$ dig +short TXT "_acme-challenge.app.example.gov.tw"
$ sudo -u www-data /usr/local/bin/acme-dns-add app.example.gov.tw testvalue
$ journalctl -t acme-dns -n 20 --no-pager
$ ls -l /usr/local/bin/acme-dns-* /etc/acme/

# 【6】★★★ 憑證儲存
$ sudo nginx -T | grep autocert_store_path
$ sudo find / -path '*autocert*' -name '*.pem' 2>/dev/null | head
$ sudo ls -la /var/lib/nginx/autocert/ 2>/dev/null

# 【7】★★★ 速率限制的狀態
$ curl -s 'https://acme-v02.api.letsencrypt.org/directory' | jq .
#   ★★ 查詢自己網域的簽發記錄
$ curl -s "https://crt.sh/?q=app.example.gov.tw&output=json" | \
    jq -r '.[:10] | .[] | "\(.not_before) \(.issuer_name)"'
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★★
> ```
> ① ★★★★ DNS API token 用最小權限
>      → Cloudflare：只給該 zone 的 Zone:DNS:Edit
>      → ★★★★ 絕不用 Global API Key
>      → token 檔案 chmod 600，目錄 700
>
> ② ★★★★ 設定 CAA 記錄
>      → 限制只有指定的 CA 能為你的網域簽發憑證
>      → ★★★ 沒設 CAA = 任何 CA 都能簽（★ 包括被騙的 CA）
>
> ③ ★★★ 憑證儲存目錄的權限
>      → 私鑰只能由 nginx 的使用者讀取
>      → ★★★★ 絕對不能放在 web root 底下
>
> ④ ★★★ hook 腳本不可被 worker 使用者寫入
>      → ★★★★ 可寫 = worker 被入侵時可以改 hook 執行任意指令
>      → root:root 750
>
> ⑤ ★★★ 監控憑證的到期日
>      → ★★★★ 自動化不代表不會失敗
>      → 外部監控（★ 不要只靠伺服器自己）
> ```

```bash
# ★★★★ 設定 CAA
$ dig +short example.gov.tw CAA
#   ★★★★ 空的 = 任何 CA 都能簽

#   ★★★ 在 DNS 管理介面加入：
#     example.gov.tw. CAA 0 issue "letsencrypt.org"
#     example.gov.tw. CAA 0 issuewild ";"                # ★★ 禁止萬用（★ 用 dns-01 的話要允許）
#     example.gov.tw. CAA 0 iodef "mailto:security@example.gov.tw"

$ dig +short example.gov.tw CAA
0 issue "letsencrypt.org"
0 iodef "mailto:security@example.gov.tw"

# ★★★ 憑證儲存的權限
$ sudo nginx -T | grep autocert_store_path
$ STORE=$(sudo nginx -T 2>/dev/null | grep -oP 'autocert_store_path\s+\K\S+' | tr -d ';')
$ sudo ls -ld "${STORE:-/var/lib/nginx/autocert}"
drwx------ 4 www-data www-data 4096 ... /var/lib/nginx/autocert
#   ★★★★ 700 且由 nginx 的使用者擁有

$ sudo find "${STORE:-/var/lib/nginx/autocert}" -name '*.pem' -exec ls -l {} \;
-rw------- 1 www-data www-data 241 ... privkey.pem       # ★★★ 600

# ★★★★ 確認私鑰不在 web root
$ sudo nginx -T | grep -oP '^\s*root\s+\K\S+' | tr -d ';' | sort -u | while read -r r; do
    sudo find "$r" -name '*.pem' -o -name '*.key' 2>/dev/null | head
  done
#   ★★★★ 有輸出 = 私鑰暴露在 web root！立刻處理

$ curl -sko /dev/null -w '%{http_code}\n' \
    https://app.example.gov.tw/.well-known/acme-challenge/../../privkey.pem
404                                        # ★★★ 正確

# ★★★ hook 腳本的權限
$ ls -l /usr/local/bin/acme-dns-*
-rwxr-x--- 1 root root 1842 ... /usr/local/bin/acme-dns-add
#   ★★★★ root:root 750（★ worker 可執行但不可寫）

$ sudo -u www-data test -w /usr/local/bin/acme-dns-add && \
    echo "★★★★ 危險：worker 可以修改 hook！" || echo "★ 正確"

# ★★★★ 外部監控憑證到期日（★ 不要只靠伺服器自己）
$ sudo tee /usr/local/bin/cert-expiry-monitor >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★★ 從【外部】檢查憑證到期日
WARN=21
FAIL=0
for d in "$@"; do
    exp=$(echo | openssl s_client -connect "$d:443" -servername "$d" 2>/dev/null | \
          openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    [ -n "$exp" ] || { echo "★★★★ $d: 無法取得憑證"; FAIL=$((FAIL+1)); continue; }
    days=$(( ($(date -d "$exp" +%s) - $(date +%s)) / 86400 ))
    printf '%-40s %3s 天  ' "$d" "$days"
    if [ "$days" -lt 7 ];  then echo "★★★★ 緊急"; FAIL=$((FAIL+1))
    elif [ "$days" -lt "$WARN" ]; then echo "★★★ 注意"; FAIL=$((FAIL+1))
    else echo "✓"; fi
done
exit "$FAIL"
EOF
$ sudo chmod +x /usr/local/bin/cert-expiry-monitor

#   ★★★★ 從【另一台機器】執行（★ 這樣伺服器整個掛掉也會被發現）
$ sudo tee /etc/cron.d/cert-monitor >/dev/null <<'EOF'
0 8 * * * root /usr/local/bin/cert-expiry-monitor app.example.gov.tw api.example.gov.tw || \
  logger -t cert-monitor -p daemon.err "憑證即將到期"
EOF
```

---

## 速查表

### ★★★★ 最小設定

```nginx
load_module modules/ngx_http_autocert_module.so;   # ★★★ 最上層

http {
    resolver 1.1.1.1 valid=300s ipv6=off;          # ★★★★ 必要！
    autocert_contact admin@example.gov.tw;
    autocert_staging on;                            # ★★★★ 測試時開

    server {
        listen 80;
        listen 443 ssl;
        server_name app.example.gov.tw;
        autocert on;                                # ★★★★ 就這一行
    }
}
```

### 常用指令

```nginx
autocert on|off                     ★★★★ 主開關（http, server）
autocert_contact <email>            ★★★ ACME 帳號信箱
autocert_staging on|off             ★★★★ LE staging（測試必用）
autocert_ca <url>                   自訂 ACME directory
autocert_key_type p384 rsa2048      ★★★ 雙憑證（最多 1 EC + 1 RSA）
autocert_challenge http-01|tls-alpn-01|dns-01
autocert_renew_before 7d            ★★★ 到期前多久續期（≤89d）
autocert_store_path <path>          憑證儲存根目錄
autocert_store_layout default|certbot
autocert_wildcard *.rest            ★★★ 萬用 SAN（僅 dns-01）
```

### ★★★ 金鑰類型

```
p384（預設）★★★ EC，效能與安全的平衡
p256        ★★ EC，相容性較好
rsa2048/3072/4096   ★★ 相容性最好但慢
★★★★ 雙憑證：autocert_key_type p384 rsa2048;
      → 現代客戶端用 EC，舊客戶端用 RSA
```

### ★★★ 三種 challenge

```
http-01      ★★★ 預設。需要 80 埠【外網可達】
tls-alpn-01  ★★ 只需要 443（★ CDN 後面可能不行）
dns-01       ★★★★ 內網服務 + 萬用憑證的唯一選擇
             → autocert_dns_hook_add / _remove（絕對路徑）
             → autocert_dns_propagation_delay 30s
```

### ★★★★ 三件必做

```
① autocert_staging on;             先用 staging（★ 速率限制！）
② resolver 1.1.1.1 ipv6=off;       必要，否則失敗
③ http-01 需要 80 可達             或用 dns-01
```

### 從 certbot 遷移

```nginx
- ssl_certificate     /etc/letsencrypt/live/x/fullchain.pem;
- ssl_certificate_key /etc/letsencrypt/live/x/privkey.pem;
- location ^~ /.well-known/acme-challenge/ { ... }    # ★★★ 不需要了
+ autocert on;

★★★ 之後：sudo systemctl disable --now certbot.timer
★★★ 觀察一週確認自動續期正常，才刪 /etc/letsencrypt
```

### ★★★ 排錯

```bash
sudo nginx -T | grep -E 'autocert|resolver|load_module'
sudo tail -f /var/log/nginx/error.log | grep -i autocert
curl -sI http://domain/.well-known/acme-challenge/test    # ★★★ 應該 404 不是 301
dig +short TXT _acme-challenge.domain                      # ★★ dns-01
autocert-verify domain                                     # ★★★ 完整驗證
```

### ★★★★ 安全

```bash
★★★★ DNS token 最小權限（Zone:DNS:Edit，不用 Global API Key）
★★★★ CAA：example.gov.tw. CAA 0 issue "letsencrypt.org"
★★★ 儲存目錄 700、私鑰 600、不在 web root
★★★ hook 腳本 root:root 750（worker 不可寫）
★★★★ 從【外部】監控憑證到期日
```

---

## 練習題

> [!question]- 練習 1：最小設定 ★★★
> 1. **安裝模組並確認 `load_module` 生效**
> 2. **用 `autocert_staging on` 設定一個測試網域**
> 3. **看 error.log 的申請過程** → 有幾個階段？
> 4. **`openssl s_client` 看 issuer** → 是 STAGING 嗎？
> 5. **故意不設 `resolver`** → 錯誤訊息是什麼？
> 6. **改成正式環境並驗證**

> [!question]- 練習 2：challenge ★★★★
> 1. **用 http-01，把 80 全部 `return 301`** → 申請成功嗎？
> 2. **`curl -sI http://domain/.well-known/acme-challenge/test`** → 回什麼？
> 3. **改成 tls-alpn-01（關掉 80）** → 呢？
> 4. **設定 dns-01 的 hook 腳本**
> 5. **手動執行 hook 並用 `dig` 確認 TXT**
> 6. **用 dns-01 申請一張萬用憑證**

> [!question]- 練習 3：雙憑證 ★★★
> 1. **設 `autocert_key_type p384`** → 憑證的金鑰類型？
> 2. **改成 `p384 rsa2048`**
> 3. **用 `-sigalgs ecdsa_secp384r1_sha384` 測試** → 拿到哪張？
> 4. **用 `-sigalgs rsa_pkcs1_sha256` 測試** → 呢？
> 5. **用 `nmap --script ssl-enum-ciphers`** → 看得到兩種嗎？
> 6. **什麼情況下需要雙憑證？**

> [!question]- 練習 4：從 certbot 遷移 ★★★★
> 1. **在測試機建立一個 certbot 管理的站台**
> 2. **備份 `/etc/letsencrypt` 與 nginx 設定**
> 3. **改成 autocert（先用 staging）**
> 4. **移除 `.well-known` 的 location** → 還能申請嗎？
> 5. **停用 `certbot.timer`**
> 6. **執行 `autocert-verify`** → 全部通過嗎？

> [!question]- 練習 5：安全 ★★★★
> 1. **`dig +short 你的網域 CAA`** → 有設嗎？
> 2. **設定 CAA 只允許 Let's Encrypt**
> 3. **檢查憑證儲存目錄的權限**
> 4. **`sudo -u www-data test -w /usr/local/bin/acme-dns-add`** → 可寫嗎？
> 5. **建立一個最小權限的 Cloudflare token**
> 6. **從另一台機器設定憑證到期監控**

---

## 小測驗

Q1. **`autocert` 解決了 certbot 的哪五個痛點**？

Q2. **設定 autocert 時，哪三件事是必做的**？

Q3. **為什麼一定要先用 `autocert_staging on`**？

Q4. **為什麼一定要設 `resolver`**？`ipv6=off` 的用意？

Q5. **三種 challenge 的差別**？內網服務與萬用憑證該用哪個？

Q6. **`autocert_key_type p384 rsa2048` 的用意**？怎麼驗證兩張都生效？

Q7. **從 certbot 遷移後，`.well-known` 的 location 還需要嗎**？

Q8. **DNS-01 的 hook 腳本有什麼安全風險**？四個防護？

Q9. **CAA 記錄的作用是什麼**？沒設會怎樣？

Q10. **既然 autocert 會自動續期，為什麼還要監控憑證到期日**？

> [!question]- 測驗答案
> **Q1.** ①**★★★★ 續期成功但 reload 失敗** ——
> certbot 更新了憑證檔案，但 deploy-hook 的 reload 失敗
> （設定有語法錯誤、權限問題），**nginx 記憶體中還是舊憑證，
> 通常到過期當天才發現**；
> ②**★★★ cron / timer 停了沒人知道** ——
> 服務沒啟動、腳本被改壞、timer 被 disable，兩個月後憑證就過期了；
> ③**★★ challenge 路徑的設定容易出錯** ——
> `.well-known/acme-challenge` 被 HTTPS 重導向攔截、被 `try_files` 吃掉、
> location 優先順序搞錯；
> ④**★★ 多一個程式要維護**（certbot 本身的更新、Python 相依、snap 版本問題）；
> ⑤**★★ 新增網域要重跑一次流程**。
> **autocert 的做法**：`autocert on;` 一行，
> NGINX 自己申請、提供、續期，**憑證熱載入不需要 reload**，
> challenge 由模組在 PREACCESS 階段處理。
>
> **Q2.** ①**★★★★ 先用 `autocert_staging on;` 測試** ——
> Let's Encrypt 正式環境有**嚴格的速率限制**
> （同一註冊網域每週 50 張、**失敗驗證每小時 5 次**），
> 設定錯誤反覆重試會**被鎖住**；
> ②**★★★★ 一定要設 `resolver`** ——
> ACME 客戶端要解析 CA 的網域，
> NGINX 的內部解析不使用 `/etc/resolv.conf`，
> 沒設會失敗而且**訊息不明顯**；
> ③**★★★ http-01 需要 80 埠從外網可達** ——
> 防火牆要放行 80，網域的 A 記錄要指對，
> **不要把 80 全部 301 到 443**（內網服務改用 dns-01）。
> 另外建議設 `autocert_contact`（CA 會在憑證快過期時通知）。
>
> **Q3.** 因為 **Let's Encrypt 正式環境的速率限制很嚴格**：
> **同一個註冊網域每週最多 50 張憑證**、
> **★★★★ 失敗的驗證每小時最多 5 次**、
> 重複的憑證每週 5 張。
> **設定錯誤時，autocert 會自動重試** ——
> DNS 沒指對、80 埠不通、resolver 沒設，
> 每次重試都算一次失敗驗證，**很快就撞到每小時 5 次的上限**，
> 然後**你完全無法申請憑證**，正式上線就開天窗。
> **staging 環境的限制寬鬆很多**，可以反覆測試。
> ```nginx
> autocert_staging on;      # ★★★★ 測試時
> autocert_staging off;     # ★★★ 確認流程通了才關掉
> ```
> **staging 簽的憑證瀏覽器不信任**（issuer 含 `(STAGING)`），
> 但正好驗證「整個流程有沒有跑通」。上線前記得關掉並確認 issuer。
>
> **Q4.** 因為 **ACME 客戶端需要解析 CA 的網域名稱**
> （`acme-v02.api.letsencrypt.org`）才能連上去申請憑證，
> 而 **NGINX 的內部 DNS 解析器不使用系統的 `/etc/resolv.conf`** ——
> 它有獨立的 resolver 機制，**沒有明確設定 `resolver` 指令就無法解析任何網域**。
> 失敗訊息通常不明顯，只看到 ACME 一直失敗。
> **`ipv6=off` 的用意**：
> 預設 resolver 會同時查 A 和 AAAA 記錄，
> **在沒有 IPv6 連線能力的環境下，解析到 AAAA 會導致連線逾時**
> （每次都要等 timeout 才 fallback 到 IPv4），
> 讓 ACME 流程變得極慢甚至失敗。
> ```nginx
> resolver 1.1.1.1 8.8.8.8 valid=300s ipv6=off;
> ```
> 同樣的問題也發生在 `proxy_pass` 使用網域名稱時。
>
> **Q5.** **`http-01`（預設）** —— CA 連到你的 **80 埠**取檔案驗證。
> 需要**80 埠從外網可達**、網域 A 記錄指對。適合一般對外網站。
> **`tls-alpn-01`** —— 在 **443 埠的 TLS 交握**中用特殊 ALPN 協定驗證。
> **不需要 80 埠**，適合只開 443 的環境；
> 但**CDN / 負載平衡器自己終止 TLS 時會失敗**。
> **`dns-01`** —— 在 DNS 加 **TXT 記錄**驗證。
> **★★★★ 這是內網服務與萬用憑證的唯一選擇**：
> 內網機器外面連不到，http-01 和 tls-alpn-01 都不可能成功；
> 而**萬用憑證（`*.example.com`）只能用 dns-01 簽發**。
> 代價是需要 hook 腳本呼叫 DNS provider 的 API：
> ```nginx
> autocert_challenge dns-01;
> autocert_dns_hook_add    /usr/local/bin/acme-dns-add;
> autocert_dns_hook_remove /usr/local/bin/acme-dns-remove;
> autocert_wildcard *.internal.example.gov.tw;
> ```
>
> **Q6.** **★★★★ 同時簽發一張 EC 憑證和一張 RSA 憑證**，
> TLS 交握時**依客戶端支援的簽章演算法自動選擇**。
> **為什麼**：
> **EC（p384）憑證交握快 2~3 倍、金鑰小、CPU 負擔低**，
> 但**非常舊的客戶端不支援**（Windows XP、Android 4.3 以前、Java 7 以前）；
> **RSA 相容性最好但慢**。
> 雙憑證讓**現代瀏覽器用 EC（快），舊客戶端用 RSA（能連）**。
> **驗證**：
> ```bash
> echo | openssl s_client -connect d:443 -servername d \
>   -sigalgs 'ecdsa_secp384r1_sha384' 2>/dev/null | \
>   openssl x509 -noout -text | grep -A2 'Public Key Algorithm'
> # → id-ecPublicKey (384 bit)
> echo | openssl s_client -connect d:443 -servername d \
>   -sigalgs 'rsa_pkcs1_sha256' 2>/dev/null | ...
> # → rsaEncryption (2048 bit)
> ```
> **限制：最多一個 EC + 一個 RSA**。純內部或現代化的服務用 `p384` 就好。
>
> **Q7.** **★★★ 不需要了，而且應該移除**。
> autocert 模組**在 PREACCESS 階段自己攔截 challenge 請求並回應**，
> 不需要你設定任何 location，也不需要 `/var/www/certbot` 這種目錄。
> **留著舊的 location 反而可能有害**：
> ```nginx
> location ^~ /.well-known/acme-challenge/ {
>     root /var/www/certbot;
>     try_files $uri =404;                 # ★★★ 可能攔截模組的處理
> }
> ```
> `^~` 是**高優先的前綴比對**，可能在模組之前就把請求處理掉並回 404，
> 導致 ACME 驗證失敗。
> **遷移時要一併移除的還有**：
> `ssl_certificate` / `ssl_certificate_key` 指向 `/etc/letsencrypt/` 的設定、
> `include /etc/letsencrypt/options-ssl-nginx.conf`、
> 以及**停用 `certbot.timer`**（否則兩套續期機制並存會很混亂）。
>
> **Q8.** **hook 腳本以 nginx worker 的使用者執行，而且持有 DNS API token** ——
> **token 洩漏 = 攻擊者可以修改你的 DNS**：
> 把網域指到他的伺服器、**為你的網域簽發憑證（完美的中間人攻擊）**、
> 攔截你的郵件（改 MX）。
> **四個防護**：
> ①**★★★★ token 用最小權限** ——
> Cloudflare 只給該 zone 的 `Zone:DNS:Edit`，
> **絕對不要用 Global API Key**（那把鑰匙能改你所有的網域和帳號設定）；
> ②**★★★ token 檔案 `chmod 600`、目錄 `chmod 700`**；
> ③**★★★★ hook 腳本 `root:root 750`** ——
> **worker 使用者可執行但不可寫入**；
> 可寫的話，worker 被入侵時攻擊者可以改 hook 執行任意指令；
> ④**★★★ 設定 CAA 記錄**限制只有你用的 CA 能簽發。
> 驗證：`sudo -u www-data test -w /usr/local/bin/acme-dns-add` 應該失敗。
>
> **Q9.** **CAA（Certification Authority Authorization）記錄限制「哪些 CA 可以為你的網域簽發憑證」**。
> ```
> example.gov.tw. CAA 0 issue "letsencrypt.org"
> example.gov.tw. CAA 0 issuewild ";"          # 禁止萬用憑證
> example.gov.tw. CAA 0 iodef "mailto:security@example.gov.tw"
> ```
> **CA 在簽發前必須檢查 CAA 記錄**，不符合就必須拒絕。
> **沒設 CAA 的話，任何一家 CA 都能為你的網域簽發憑證** ——
> 全世界有上百家受信任的 CA，只要**其中任何一家被入侵、被騙、或有內鬼**，
> 攻擊者就能拿到你網域的合法憑證做中間人攻擊，
> 而**瀏覽器完全不會有警告**（憑證是「合法」的）。
> 這種事真的發生過（DigiNotar、Symantec 的事件）。
> **`iodef` 讓 CA 在有人嘗試違規簽發時通知你** —— 這是很有價值的入侵早期警訊。
> 用 dns-01 簽萬用憑證的話，`issuewild` 要允許而不是 `";"`。
>
> **Q10.** 因為 **★★★★ 自動化不代表不會失敗**，
> 而且**失敗時往往沒有人會發現**：
> DNS 記錄被改動（換了 IP 忘記更新）、
> 防火牆規則變更擋掉了 80 埠、
> DNS API token 過期或被撤銷、
> CA 端的政策變更、
> **撞到速率限制被鎖住**、
> nginx 因為別的原因掛掉導致續期沒執行。
> **★★★★ 關鍵是要從「外部」監控** ——
> 如果監控腳本跑在同一台伺服器上，**伺服器整個掛掉時監控也一起掛了**，
> 沒有人會收到告警。
> ```bash
> # ★★★ 在另一台機器上執行
> 0 8 * * * root /usr/local/bin/cert-expiry-monitor app.example.gov.tw || \
>   logger -t cert-monitor -p daemon.err "憑證即將到期"
> ```
> 建議在**剩餘 21 天**時就開始告警（autocert 預設 7 天前續期，
> 留 14 天的緩衝讓你有時間處理問題）。

---

## 延伸閱讀

- [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]] — 套件庫與模組安裝
- [[060-02-05-02-guide-MyGuard-Angie伺服器入門]] — **★★★ Angie 的內建 ACME（另一種做法）**
- [[060-02-02-06-guide-Nginx-HTTPS與Certbot]] — **★★★ certbot 的傳統做法**
- [[090-01-12-guide-PKI-憑證生命週期管理]] — 憑證的監控與輪替
- [[090-01-13-guide-PKI-憑證常見問題排查]] — TLS 錯誤的完整對照
- [[060-02-05-07-guide-MyGuard-動態模組管理]] — 模組的載入與管理
