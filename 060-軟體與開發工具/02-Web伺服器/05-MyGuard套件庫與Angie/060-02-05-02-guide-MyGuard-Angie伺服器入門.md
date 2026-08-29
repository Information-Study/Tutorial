---
title: "Angie 伺服器入門"
desc: "NGINX 的 fork：內建 ACME、RESTful API、動態 upstream 與監控主控台"
aliases: [Angie, angie, nginx fork, Console Light, acme_client]
tags: [群組/軟體與開發工具, 服務/nginx, 服務/angie, 服務/myguard]
category: MyGuard與Angie
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]]", "[[060-02-02-02-guide-Nginx-設定語法與虛擬主機]]"]
updated: 2026-08-28
---

# Angie 伺服器入門

> [!abstract] 這篇你會學到
> - **★★★ Angie 是什麼**、和 NGINX 的關係
> - **★★★★ 四個關鍵差異**：內建 ACME、RESTful API、動態 upstream、監控主控台
> - 安裝與目錄結構
> - **★★★★ 從 NGINX 遷移**（★ 設定檔幾乎不用改）
> - `acme_client` 的設定
> - API 與 Prometheus 監控
> - **★★★ 該不該換？** 決策指引

> [!warning] 未實機驗證 ★★★
> ```
> ★★★ 本章依據 2026 年 8 月的官方文件與套件庫資訊撰寫，
>      作者【未在實機上完整驗證所有指令參數】。
>
> ★★★★ 實作前請對照官方文件：
>   · Angie 官方：https://en.angie.software/angie/docs/
>   · ACME 模組：https://en.angie.software/angie/docs/configuration/acme/
>   · MyGuard：  https://deb.myguard.nl/
>
> ★★ 指令的完整參數清單以官方文件為準。
> ```

## 前置知識

- [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]] — 套件庫的加入
- [[060-02-02-02-guide-Nginx-設定語法與虛擬主機]] — **★★★ NGINX 的設定語法完全通用**

---

## ★★★ Angie 是什麼

```
★★★★ Angie = NGINX 的 fork（分支）

  ★★★ 背景：
    · 由【原本的 NGINX 開發者】建立
    · NGINX 被 F5 收購後，部分核心開發者離開
    · 2022 年起獨立開發
    · ★★ 開源（BSD 授權），也有商業版 Angie PRO

  ★★★★ 最重要的一句話：
    「drop-in replacement for nginx」
    → ★★★★ 【設定檔完全相容】
    → 每一個指令、每一個模組都能直接用
    → ★★★ 遷移幾乎不用改設定

  ★★★ 官方：https://angie.software（★ en.angie.software 是英文版）
  ★★ 原始碼：https://git.angie.software/web-server/angie
```

### ★★★★ 四個關鍵差異

| | **NGINX（開源版）** | **★★★ Angie** |
| --- | --- | --- |
| **★★★★ 自動憑證（ACME）** | ✗（要 certbot） | **✓ 內建 `acme_client`**（HTTP/DNS/TLS-ALPN） |
| **★★★★ 狀態 API** | ✗（只有 stub_status） | **✓ RESTful JSON API** |
| **★★★ Prometheus 指標** | ✗（要 exporter） | **✓ 內建匯出** |
| **★★★ 監控主控台** | ✗ | **✓ Console Light**（瀏覽器） |
| **★★★ upstream 健康檢查** | ✗（商業版才有） | **✓ 內建** |
| **★★ 動態 upstream** | ✗ | **✓**（★ 依 Docker 標籤自動更新，不用 reload） |
| **★★ session sticky** | ✗（商業版才有） | ✓ |
| 設定檔相容性 | — | **★★★★ 100% 相容** |
| 授權 | BSD | BSD |

```
★★★★ 用一句話總結：
  「Angie ≈ NGINX + 幾個原本要付費（NGINX Plus）或要外掛才有的功能」

★★★ 對本手冊的讀者，最有價值的是：
  ① ★★★★ 內建 ACME → 不用 certbot、不用 cron、不用 reload hook
  ② ★★★ RESTful API + Prometheus → 監控好做太多
  ③ ★★★ upstream 健康檢查 → 上游掛掉自動移除
```

---

## 安裝

### 方法一：MyGuard 套件庫

```bash
# ★★★ 見 [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]] 設定套件庫後
$ sudo apt install -y angie
$ angie -v
Angie/1.10.0

$ sudo systemctl enable --now angie
$ sudo systemctl status angie --no-pager | head -5
```

### 方法二：Angie 官方套件庫

```bash
# ★★ Ubuntu / Debian
$ curl -fsSL https://angie.software/keys/angie-signing.gpg \
    | sudo tee /etc/apt/keyrings/angie-signing.gpg >/dev/null
$ echo "deb [signed-by=/etc/apt/keyrings/angie-signing.gpg] \
https://download.angie.software/angie/$(. /etc/os-release && echo "$ID/$VERSION_ID") \
$(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/angie.list
$ sudo apt update && sudo apt install -y angie
#   ★★★ 實際的路徑請對照 https://en.angie.software/angie/docs/installation/
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> # ★★★ Angie 官方有提供 RPM 套件庫（★ MyGuard 沒有 RPM）
> $ sudo curl -o /etc/yum.repos.d/angie.repo \
>     https://download.angie.software/angie/rhel/$(rpm -E %rhel)/angie.repo
> $ sudo dnf install -y angie
> $ sudo systemctl enable --now angie
>
> # ★★ 或用 getpagespeed 的套件庫
> #   https://nginx-extras.getpagespeed.com/angie/
> ```

```bash
# ═══ ★★★ 目錄結構（★ 和 NGINX 幾乎一樣）═══
$ dpkg -L angie | grep -E '^/etc|^/usr/sbin|^/var' | sort | head -20
/etc/angie
/etc/angie/angie.conf
/etc/angie/conf.d
/etc/angie/http.d
/etc/angie/mime.types
/etc/angie/modules
/usr/sbin/angie
/var/log/angie

$ ls /etc/angie/
angie.conf  conf.d/  http.d/  mime.types  modules/  stream.d/

# ★★★ 對照 NGINX：
#   /etc/nginx/nginx.conf          → /etc/angie/angie.conf
#   /etc/nginx/conf.d/             → /etc/angie/http.d/（★ 名稱不同）
#   /etc/nginx/sites-available/    → ★★ Angie 沒有這個慣例（Debian 特有）
#   /var/log/nginx/                → /var/log/angie/
#   nginx -t                       → angie -t
```

---

## ★★★★ 從 NGINX 遷移

```
★★★★ 官方說法：「設定檔、指令、模組全部不用改」

★★★ 但實務上要注意五件事：
  ① 路徑不同（/etc/nginx → /etc/angie）
  ② ★★★ 兩者【不能同時監聽同一個 port】
  ③ ★★ 第三方動態模組要換成 Angie 版本
  ④ ★★★ 服務名稱不同（nginx → angie）
  ⑤ ★★★★ 監控、日誌輪替、部署腳本中的路徑要一起改
```

```bash
#!/usr/bin/env bash
# ★★★★ /usr/local/bin/migrate-to-angie —— NGINX → Angie 遷移
set -euo pipefail

echo "═══ NGINX → Angie 遷移 ═══"

# ═══ ★★★★【1】前置檢查 ═══
echo -e "\n【1】前置檢查"
command -v nginx >/dev/null || { echo "  ★★ 沒有安裝 nginx"; exit 1; }
nginx -v 2>&1 | sed 's/^/  現有: /'

#   ★★★ 檢查有沒有用到第三方動態模組
echo "  ── 目前載入的動態模組 ──"
nginx -T 2>/dev/null | grep -oP '^\s*load_module\s+\K\S+' | sed 's/^/    /' || echo "    （無）"
echo "  ★★★ 這些模組在 Angie 上要換成對應的版本"

# ═══ ★★★【2】備份 ═══
echo -e "\n【2】備份"
TS=$(date +%Y%m%d-%H%M%S)
sudo tar -czf "/root/nginx-config-$TS.tar.gz" /etc/nginx/
echo "  ★ /root/nginx-config-$TS.tar.gz"

#   ★★★★ 匯出【合併後】的完整設定（★ 這份是遷移的依據）
sudo nginx -T > "/root/nginx-full-config-$TS.conf" 2>/dev/null
echo "  ★★★ /root/nginx-full-config-$TS.conf（合併後的完整設定）"

# ═══ ★★★【3】安裝 Angie（★ 先不啟動）═══
echo -e "\n【3】安裝 Angie"
sudo apt install -y angie
sudo systemctl stop angie 2>/dev/null || true
sudo systemctl disable angie 2>/dev/null || true
angie -v 2>&1 | sed 's/^/  /'

# ═══ ★★★★【4】複製設定 ═══
echo -e "\n【4】★★★ 複製設定"
sudo cp -a /etc/angie/angie.conf "/etc/angie/angie.conf.orig-$TS"

#   ★★★ 複製站台設定
sudo mkdir -p /etc/angie/http.d
for f in /etc/nginx/sites-enabled/*; do
    [ -e "$f" ] || continue
    name=$(basename "$(readlink -f "$f")")
    sudo cp -L "$f" "/etc/angie/http.d/$name.conf"
    echo "  ★ $name.conf"
done

#   ★★ conf.d 也複製
for f in /etc/nginx/conf.d/*.conf; do
    [ -e "$f" ] || continue
    sudo cp "$f" "/etc/angie/http.d/$(basename "$f")"
done

#   ★★★ snippets
[ -d /etc/nginx/snippets ] && sudo cp -a /etc/nginx/snippets /etc/angie/

# ═══ ★★★★【5】調整路徑 ═══
echo -e "\n【5】★★★★ 調整設定中的路徑"
sudo find /etc/angie/http.d /etc/angie/snippets -type f 2>/dev/null -exec sed -i \
    -e 's#/etc/nginx/#/etc/angie/#g' \
    -e 's#/var/log/nginx/#/var/log/angie/#g' \
    -e 's#/var/run/nginx#/var/run/angie#g' \
    -e 's#/run/nginx#/run/angie#g' \
    {} +
echo "  ★ 已替換 /etc/nginx → /etc/angie 等路徑"

#   ★★★ 讓 angie.conf 載入 http.d
sudo grep -q 'http.d' /etc/angie/angie.conf || \
  sudo sed -i '/^http {/a\    include /etc/angie/http.d/*.conf;' /etc/angie/angie.conf

# ═══ ★★★★【6】語法檢查 ═══
echo -e "\n【6】★★★★ 語法檢查"
if sudo angie -t; then
    echo "  ★ 語法正確"
else
    echo "  ★★★★ 語法錯誤！常見原因："
    echo "    · 用到 Angie 沒有的第三方模組 → 安裝對應的 Angie 模組"
    echo "    · load_module 的路徑不對 → /usr/lib/angie/modules/"
    echo "    · 路徑替換不完整 → 手動檢查"
    exit 1
fi

# ═══ ★★★★【7】切換（★ 兩者不能同時佔用 80/443）═══
echo -e "\n【7】★★★★ 切換服務"
echo "  ★★★ 停止 nginx..."
sudo systemctl stop nginx
sudo systemctl disable nginx

echo "  ★ 啟動 angie..."
sudo systemctl enable --now angie
sleep 2

# ═══ ★★★【8】驗證 ═══
echo -e "\n【8】★★★ 驗證"
sudo systemctl status angie --no-pager | head -5 | sed 's/^/  /'
sudo ss -tlnp | grep -E ':80|:443' | sed 's/^/  /'

for u in / /api/health; do
    printf '  %-20s ' "$u"
    curl -sko /dev/null -w '%{http_code}\n' --max-time 10 "https://localhost$u" || echo "失敗"
done

echo -e "\n★ 遷移完成"
echo "★★★ 還要處理："
echo "  · logrotate 設定（/etc/logrotate.d/nginx → angie）"
echo "  · 監控腳本中的服務名稱與路徑"
echo "  · 部署腳本中的 'systemctl reload nginx' → 'reload angie'"
echo "  · fail2ban 的 logpath"
echo ""
echo "★★★★ 回退：sudo systemctl stop angie && sudo systemctl start nginx"
```

> [!danger] 遷移的四個容易漏掉的地方 ★★★★
> ```
> ① ★★★★ 【部署腳本】
>    sudo systemctl reload nginx     ← ★★★ 遷移後不會有作用
>    sudo nginx -t                    ← ★★★ 指令不存在了
>    → ★★ 全部改成 angie
>    $ grep -rn 'nginx' /usr/local/bin/ /etc/cron.d/ .github/workflows/
>
> ② ★★★ 【logrotate】
>    /etc/logrotate.d/nginx 仍指向 /var/log/nginx
>    → ★★★ Angie 的日誌在 /var/log/angie/，不會被輪替 → 磁碟塞爆
>
> ③ ★★★ 【fail2ban】
>    logpath = /var/log/nginx/error.log
>    → ★★ 改成 /var/log/angie/error.log
>
> ④ ★★★★ 【監控與告警】
>    · systemd 的服務名稱
>    · GoAccess / 日誌分析的路徑
>    · Prometheus 的 nginx-exporter → ★★★ Angie 內建，可以拿掉
> ```

```bash
# ★★★ 找出所有需要修改的地方
$ sudo grep -rln 'nginx' \
    /etc/logrotate.d/ /etc/fail2ban/ /etc/cron.d/ \
    /usr/local/bin/ /etc/systemd/system/ 2>/dev/null

# ★★★★ 遷移後的完整檢查
$ sudo tee /usr/local/bin/angie-migration-check >/dev/null <<'EOF'
#!/usr/bin/env bash
echo "═══ Angie 遷移後檢查 ═══"
FAIL=0
chk(){ printf '  %-46s ' "$1"; shift; eval "$@" >/dev/null 2>&1 && echo "✓" || { echo "★★★★ 失敗"; FAIL=$((FAIL+1)); }; }

chk "angie 服務執行中"        'systemctl is-active --quiet angie'
chk "★★★ nginx 已停用"         '! systemctl is-active --quiet nginx'
chk "★★★ nginx 已 disable"     '! systemctl is-enabled --quiet nginx'
chk "監聽 80"                  'ss -tlnp | grep -q ":80 "'
chk "監聽 443"                 'ss -tlnp | grep -q ":443 "'
chk "設定語法正確"             'angie -t'
chk "★★★ logrotate 指向 angie" 'grep -rq "/var/log/angie" /etc/logrotate.d/'
chk "★★★ 日誌有在寫入"          '[ -s /var/log/angie/access.log ]'

echo -e "\n【★★★ 仍指向 nginx 的設定】"
grep -rln '/var/log/nginx\|/etc/nginx\|systemctl.*nginx' \
    /etc/logrotate.d/ /etc/fail2ban/ /etc/cron.d/ /usr/local/bin/ 2>/dev/null | \
    sed 's/^/  ★★★ /' || echo "  ★ 無"

echo ""
[ "$FAIL" -eq 0 ] && echo "★ 全部通過" || echo "★★★★ $FAIL 項需要處理"
exit "$FAIL"
EOF
$ sudo chmod +x /usr/local/bin/angie-migration-check
$ sudo angie-migration-check
```

---

## ★★★★ 內建 ACME

```
★★★★ 這是 Angie 最實用的功能：【不需要 certbot】

★★★ 和 certbot 的差異：
  ┌────────────────┬─────────────────────┬──────────────────────┐
  │                │ certbot             │ ★★★ Angie 內建 ACME   │
  ├────────────────┼─────────────────────┼──────────────────────┤
  │ 額外的程式      │ ✓ 要裝              │ ✗ 內建               │
  │ ★★★ cron       │ ✓ 要設              │ ✗ 自動               │
  │ ★★★ reload     │ ✓ 續期後要 reload   │ ✗ ★★★★ 熱載入        │
  │ challenge 路徑  │ ★★ 要設 location    │ ✗ 自動處理           │
  │ ★★★ 失敗時     │ ★★★★ 常常沒人發現   │ ★★ 在 API/日誌看得到 │
  │ DNS-01         │ 要外掛              │ ✓ 內建               │
  └────────────────┴─────────────────────┴──────────────────────┘

★★★★ certbot 最大的問題：
  續期成功但 reload 失敗 → ★★★ 憑證更新了但 nginx 還在用舊的
  → 過期當天才發現
```

```nginx
# ★★★ /etc/angie/angie.conf 的 http 區塊
# ★★★ 注意：以下語法依官方文件，實作前請對照
#     https://en.angie.software/angie/docs/configuration/acme/

http {
    # ═══ ★★★★ 定義 ACME 客戶端 ═══
    resolver 1.1.1.1 8.8.8.8 valid=300s ipv6=off;

    # ★★★ acme_client <名稱> <ACME 目錄 URL> [參數...]
    acme_client letsencrypt https://acme-v02.api.letsencrypt.org/directory;

    # ★★ 測試用（★ 開發時一定要先用 staging）
    acme_client le_staging https://acme-staging-v02.api.letsencrypt.org/directory;

    # ★★★ DNS-01 challenge（★ 萬用憑證需要）
    acme_client le_dns https://acme-v02.api.letsencrypt.org/directory
                challenge=dns;

    server {
        listen 80;
        listen 443 ssl;
        http2 on;
        server_name app.example.gov.tw www.app.example.gov.tw;

        # ═══ ★★★★ 啟用 ACME ═══
        acme letsencrypt;

        # ★★★★ 用變數引用自動取得的憑證
        ssl_certificate     $acme_cert_letsencrypt;
        ssl_certificate_key $acme_cert_key_letsencrypt;

        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_prefer_server_ciphers off;

        location / {
            root /var/www/app/current/public;
            try_files $uri $uri/ /index.php?$query_string;
        }
    }
}
```

```bash
# ═══ ★★★ 驗證 ═══
$ sudo angie -t && sudo systemctl reload angie

# ★★★ 看 ACME 的過程
$ sudo journalctl -u angie -f | grep -i acme
$ sudo tail -f /var/log/angie/error.log | grep -i acme

# ★★★★ 憑證存放位置（★ 依編譯時的 --http-acme-client-path）
$ sudo ls -la /var/lib/angie/acme/letsencrypt/
$ sudo find /var/lib/angie -name '*.pem' 2>/dev/null

# ★★★ 驗證憑證
$ echo | openssl s_client -connect app.example.gov.tw:443 \
    -servername app.example.gov.tw 2>/dev/null | \
    openssl x509 -noout -subject -issuer -dates
subject=CN = app.example.gov.tw
issuer=C = US, O = Let's Encrypt, CN = R11
notBefore=Aug 28 00:00:00 2026 GMT
notAfter=Nov 26 23:59:59 2026 GMT
```

> [!danger] ACME 的三個必做 ★★★★
> ```
> ① ★★★★ 【先用 staging 測試】
>      acme_client le_staging https://acme-staging-v02.api.letsencrypt.org/directory;
>      → ★★★ Let's Encrypt 正式環境有【嚴格的速率限制】
>        （同一個網域每週 50 張、失敗驗證每小時 5 次）
>      → ★★★★ 設定錯誤反覆重試會被鎖住一週！
>
> ② ★★★★ 【設定 resolver】
>      → ACME 客戶端要解析 CA 的網域
>      → ★★★ 沒設 resolver 會失敗且訊息不明顯
>      → resolver 1.1.1.1 valid=300s ipv6=off;
>
> ③ ★★★ 【HTTP-01 需要 80 埠可達】
>      → 防火牆要放行 80
>      → ★★★ 不要把 80 全部 301 到 443（★ 或至少要讓 ACME 的路徑通過）
>      → ★★ 內網服務用 DNS-01 challenge
> ```

```
★★★ 三種 challenge 的選擇：

  http-01     ★★★ 預設。需要【80 埠從外網可達】
              → 適合：一般的對外網站

  tls-alpn-01 ★★ 需要 443 可達，不需要 80
              → 適合：只開 443 的環境

  dns-01      ★★★★ 需要能改 DNS 的 TXT 記錄
              → ★★★★ 唯一能簽【萬用憑證】的方式
              → ★★★ 適合：內網服務（★ 不需要對外可達）
              → 需要 DNS provider 的 API 或 hook 腳本
```

---

## ★★★★ API 與監控

```
★★★★ Angie 內建 RESTful JSON API —— NGINX 開源版只有 stub_status

  NGINX stub_status 給你：
    Active connections: 291
    server accepts handled requests
     16630948 16630948 31070465
    Reading: 6 Writing: 179 Waiting: 106
    → ★★★ 就這樣，沒有 per-server / per-upstream 的資訊

  ★★★★ Angie API 給你：
    · 每個 server zone 的請求數、狀態碼分布、流量
    · ★★★ 每個 upstream 的健康狀態、回應時間、失敗次數
    · 每個 location 的統計
    · 共享記憶體區的使用狀況
    · SSL 交握的成功/失敗數
    · ★★★ Prometheus 格式匯出
```

```nginx
# ★★★ 設定 API（★ 一定要限制存取！）
http {
    server {
        listen 127.0.0.1:8080;          # ★★★★ 只綁本機
        server_name _;

        # ═══ ★★★ RESTful API ═══
        location /status/ {
            api /status/;

            # ★★★★ 存取控制（★ 一定要有）
            allow 127.0.0.1;
            allow 10.10.20.0/24;
            deny all;
        }

        # ═══ ★★★ Prometheus 指標 ═══
        location /metrics {
            # ★★ Angie 內建 Prometheus 模板
            prometheus_template main;
            allow 127.0.0.1;
            allow 10.10.20.50;          # ★ Prometheus 伺服器
            deny all;
        }

        # ═══ ★★ Console Light（瀏覽器監控介面）═══
        location /console/ {
            alias /usr/share/angie-console-light/html/;
            index index.html;
            allow 10.10.20.0/24;
            deny all;
        }
    }

    # ★★★ 要有統計就要定義 zone
    upstream backend {
        zone backend 1m;                # ★★★★ 沒有 zone 就沒有統計
        server 10.10.20.31:8080;
        server 10.10.20.32:8080;
    }

    server {
        listen 443 ssl;
        server_name app.example.gov.tw;
        status_zone app;                # ★★★ 這個 server 的統計

        location / {
            proxy_pass http://backend;
            status_zone app_root;       # ★★ 這個 location 的統計
        }
    }
}
```

```bash
# ═══ ★★★ 查詢 API ═══
$ curl -s http://127.0.0.1:8080/status/ | jq 'keys'
["angie","connections","http","resolvers","slabs","stream"]

$ curl -s http://127.0.0.1:8080/status/angie | jq .
{
  "version": "1.10.0",
  "build": "Angie",
  "address": "10.10.20.31",
  "generation": 3,
  "load_time": "2026-08-28T18:30:11Z"
}

$ curl -s http://127.0.0.1:8080/status/connections | jq .
{
  "accepted": 16630948,
  "dropped": 0,
  "active": 291,
  "idle": 106
}

# ★★★★ 每個 server zone 的統計
$ curl -s http://127.0.0.1:8080/status/http/server_zones | jq .
{
  "app": {
    "ssl": { "handshaked": 48210, "reuses": 12840, "timedout": 2, "failed": 8 },
    "requests": { "total": 84210, "processing": 12, "discarded": 0 },
    "responses": {
      "200": 78420, "301": 1240, "304": 2810,
      "404": 892, "500": 124, "502": 8
    },
    "data": { "received": 48210240, "sent": 892104820 }
  }
}

# ★★★★ upstream 的健康狀態（★ 這是 NGINX 開源版沒有的）
$ curl -s http://127.0.0.1:8080/status/http/upstreams/backend | jq .
{
  "peers": {
    "10.10.20.31:8080": {
      "server": "10.10.20.31:8080",
      "state": "up",                          # ★★★ 健康狀態
      "selected": { "current": 8, "total": 42104 },
      "responses": { "200": 41892, "5xx": 12 },
      "data": { "sent": 12840240, "received": 482104820 },
      "health": { "fails": 0, "unavailable": 0, "downtime": 0 }
    },
    "10.10.20.32:8080": {
      "state": "unhealthy",                   # ★★★★ 這台有問題！
      "health": { "fails": 28, "unavailable": 3, "downtime": 142000 }
    }
  }
}

# ═══ ★★★ Prometheus ═══
$ curl -s http://127.0.0.1:8080/metrics | head -20
# HELP angie_http_server_zones_requests_total ...
angie_http_server_zones_requests_total{zone="app"} 84210
angie_http_server_zones_responses_total{zone="app",code="200"} 78420
angie_http_upstreams_peers_state{upstream="backend",peer="10.10.20.31:8080"} 1
```

```bash
# ★★★★ 用 API 做健康檢查腳本
$ sudo tee /usr/local/bin/angie-health >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★★ 用 Angie API 檢查服務健康
API="${1:-http://127.0.0.1:8080/status}"
FAIL=0

echo "═══ Angie 健康檢查 ═══"

# ★★★ 基本
V=$(curl -sf "$API/angie" | jq -r '.version // "?"')
echo "  版本: $V"

# ★★★ 連線
curl -sf "$API/connections" | jq -r \
  '"  連線: active=\(.active) idle=\(.idle) dropped=\(.dropped)"'
D=$(curl -sf "$API/connections" | jq -r '.dropped')
[ "$D" -eq 0 ] || { echo "  ★★★★ 有 $D 個連線被丟棄"; FAIL=$((FAIL+1)); }

# ★★★★ upstream 健康
echo "  ── upstream ──"
curl -sf "$API/http/upstreams" | jq -r '
  to_entries[] | .key as $u | .value.peers | to_entries[] |
  "  \($u)/\(.key): \(.value.state) fails=\(.value.health.fails // 0)"'

UNHEALTHY=$(curl -sf "$API/http/upstreams" | \
  jq '[.[] | .peers | .[] | select(.state != "up")] | length')
[ "$UNHEALTHY" -eq 0 ] || { echo "  ★★★★ $UNHEALTHY 個 upstream 不健康"; FAIL=$((FAIL+1)); }

# ★★★ 5xx 比率
echo "  ── 錯誤率 ──"
curl -sf "$API/http/server_zones" | jq -r '
  to_entries[] | .key as $z | .value.responses |
  ([.["500"],.["502"],.["503"],.["504"]] | map(. // 0) | add) as $e5 |
  (.total // ([.[]] | add)) as $t |
  "  \($z): 5xx=\($e5) / \($t) = \((($e5 / ($t|if .==0 then 1 else . end)) * 100 * 100 | floor) / 100)%"'

# ★★★ SSL
curl -sf "$API/http/server_zones" | jq -r '
  to_entries[] | select(.value.ssl.failed > 0) |
  "  ★★★ \(.key): SSL 失敗 \(.value.ssl.failed) 次"'

echo ""
[ "$FAIL" -eq 0 ] && echo "★ 健康" || echo "★★★★ $FAIL 項異常"
exit "$FAIL"
EOF
$ sudo chmod +x /usr/local/bin/angie-health
$ angie-health
```

> [!danger] API 一定要限制存取 ★★★★
> ```
> ★★★★ Angie 的 API 會暴露：
>   · 完整的 upstream 位址與健康狀態（★★★ 內部拓撲）
>   · 各 server 的流量與錯誤統計
>   · 版本號、載入時間、worker 數
>   → ★★★★ 對攻擊者是完整的偵察資訊
>
> ★★★ 三層防護：
>   ① ★★★★ listen 127.0.0.1:8080（★ 只綁本機）
>   ② allow / deny 存取控制
>   ③ ★★ 要遠端存取的話用 SSH 埠轉發，不要對外開放
>      $ ssh -L 8080:127.0.0.1:8080 app-server
>
> ★★★★ 絕對不要：
>   location /status/ { api /status/; }     ← ★★★★ 沒有 allow/deny！
>   listen 0.0.0.0:8080;                     ← ★★★★ 對外開放
> ```

---

## ★★★ upstream 健康檢查

```nginx
# ★★★★ 這是 NGINX Plus（商業版）才有的功能，Angie 免費提供
http {
    upstream backend {
        zone backend 1m;                    # ★★★★ 必要

        server 10.10.20.31:8080;
        server 10.10.20.32:8080;
        server 10.10.20.33:8080 backup;
    }

    server {
        listen 443 ssl;
        server_name app.example.gov.tw;

        location / {
            proxy_pass http://backend;

            # ═══ ★★★ 主動健康檢查 ═══
            # ★★★ 語法依官方文件，實作前請對照
            #     https://en.angie.software/angie/docs/
        }
    }
}
```

```
★★★★ 主動 vs 被動健康檢查：

  【被動】（NGINX 開源版也有）
    max_fails=3 fail_timeout=30s
    → ★★★ 要等【真實的使用者請求失敗】才知道
    → ★★★★ 前 3 個使用者是「白老鼠」

  【★★★★ 主動】（Angie 內建）
    → 定期主動送探測請求
    → ★★★ 上游還沒有影響到使用者就先被移除
    → 恢復時也會自動加回來
    → ★★ 可以檢查回應內容而不只是狀態碼
```

---

## ★★★ 該不該換

```
★★★★ 決策指引：

  ┌──────────────────────────────────┬────────────────────────┐
  │ 情境                              │ ★ 建議                 │
  ├──────────────────────────────────┼────────────────────────┤
  │ ★★★ 現有 NGINX 運作良好、          │ ★★★ 不用換             │
  │    沒有特殊需求                    │ （★ 沒有壞就不要修）   │
  ├──────────────────────────────────┼────────────────────────┤
  │ ★★★★ 想擺脫 certbot 的維護負擔     │ ★★★ 值得考慮           │
  ├──────────────────────────────────┼────────────────────────┤
  │ ★★★ 需要 upstream 健康檢查         │ ★★★★ 很值得            │
  │    但不想買 NGINX Plus             │ （★ 省一大筆錢）       │
  ├──────────────────────────────────┼────────────────────────┤
  │ ★★★ 需要好用的監控 API             │ ★★★ 值得              │
  ├──────────────────────────────────┼────────────────────────┤
  │ ★★★★ 機關的關鍵基礎設施            │ ★★★ 謹慎              │
  │                                   │ （★ 生態系較小）       │
  ├──────────────────────────────────┼────────────────────────┤
  │ ★★ 團隊只熟 NGINX                 │ ★★★ 可以換             │
  │                                   │ （★ 設定完全相容）     │
  ├──────────────────────────────────┼────────────────────────┤
  │ ★★★ 用了大量第三方模組             │ ★★ 先確認有 Angie 版   │
  └──────────────────────────────────┴────────────────────────┘

★★★ Angie 的風險：
  · ★★★ 生態系比 NGINX 小很多（★ 文件、教學、Stack Overflow 答案少）
  · ★★ 商業支援要另外付費（Angie PRO）
  · ★★★ 第三方模組不一定有對應版本
  · ★ 不在 Ubuntu/Debian 的官方支援範圍

★★★★ 折衷做法：
  【新專案】用 Angie（★ 享受內建的功能）
  【既有系統】維持 NGINX（★ 除非有明確的痛點）
  → ★★★ 兩者設定完全相容，隨時可以切回去
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`angie -t` unknown directive** ★★★★ | 用到第三方模組 | 裝 Angie 版的模組；`load_module` 路徑 |
| **80/443 被佔用** ★★★★ | **nginx 還在跑** | **`systemctl stop nginx && disable nginx`** |
| **ACME 一直失敗** ★★★★ | **沒設 resolver** | **`resolver 1.1.1.1 ipv6=off;`** |
| **ACME 被鎖住** ★★★★ | **速率限制** | **先用 staging**；等一週 |
| **HTTP-01 失敗** ★★★ | 80 不可達／被 301 | 防火牆放行 80；或用 dns-01 |
| **API 回 404** ★★★ | 沒設 `api` 指令 | `location /status/ { api /status/; }` |
| **upstream 沒有統計** ★★★★ | **沒有 `zone`** | **`upstream x { zone x 1m; ... }`** |
| **server 沒有統計** ★★★ | 沒有 `status_zone` | 在 server 加 `status_zone name;` |
| **日誌沒有輪替** ★★★ | logrotate 還指向 nginx | 改 `/etc/logrotate.d/` |
| **部署腳本失效** ★★★★ | `systemctl reload nginx` | **grep 出所有 nginx 改成 angie** |
| **fail2ban 沒作用** ★★★ | logpath 錯 | 改成 `/var/log/angie/` |

### 排查

```bash
# 【1】★★★ 基本
$ angie -v
$ angie -V 2>&1 | tr ' ' '\n' | grep -E '^--'     # ★★★ 編譯參數
$ sudo angie -t
$ sudo angie -T | head -50                         # ★★★ 合併後的完整設定

# 【2】★★★★ 兩者衝突
$ sudo ss -tlnp | grep -E ':80 |:443 '
$ systemctl is-active nginx angie
$ systemctl is-enabled nginx angie

# 【3】★★★ 模組
$ ls /usr/lib/angie/modules/
$ sudo angie -T | grep load_module
$ dpkg -l | grep -E 'angie|libangie'

# 【4】★★★★ ACME
$ sudo journalctl -u angie --since '10 min ago' | grep -i acme
$ sudo grep -i acme /var/log/angie/error.log | tail -20
$ sudo ls -la /var/lib/angie/acme/*/
$ dig +short app.example.gov.tw               # ★★ DNS 指對了嗎
$ curl -sI http://app.example.gov.tw/.well-known/acme-challenge/test

# 【5】★★★ API
$ curl -s http://127.0.0.1:8080/status/ | jq 'keys'
$ curl -sv http://127.0.0.1:8080/status/ 2>&1 | grep -E '^[<>]'
$ sudo angie -T | grep -A5 'api '

# 【6】★★★ 統計為什麼是空的
$ sudo angie -T | grep -E 'zone |status_zone'
#   ★★★★ upstream 要有 zone、server 要有 status_zone

# 【7】★★★ 遷移遺漏
$ sudo angie-migration-check
$ grep -rln 'nginx' /etc/logrotate.d/ /etc/fail2ban/ /usr/local/bin/ 2>/dev/null
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★★
> ```
> ① ★★★★ API 一定要限制存取
>      → listen 127.0.0.1 + allow/deny
>      → ★★★ 暴露內部拓撲與流量統計
>
> ② ★★★★ Console Light 也要限制
>      → 它讀 API，同樣暴露敏感資訊
>
> ③ ★★★ ACME 先用 staging 測試
>      → 正式環境有速率限制，設錯會被鎖一週
>
> ④ ★★★ 遷移後檢查安全設定有沒有跟著過來
>      → server_tokens off、security headers、ModSecurity
>      → ★★★★ 路徑替換可能漏掉 include 的檔案
>
> ⑤ ★★ Angie 的安全更新要自己追
>      → 不在發行版的支援範圍
>      → ★★★ 訂閱官方的公告
> ```

```bash
# ★★★★ 遷移後的安全設定檢查
$ sudo tee /usr/local/bin/angie-security-check >/dev/null <<'EOF'
#!/usr/bin/env bash
echo "═══ Angie 安全檢查 ═══"
CONF=$(sudo angie -T 2>/dev/null)
FAIL=0

chk(){ printf '  %-44s ' "$1"; shift
       eval "$@" >/dev/null 2>&1 && echo "✓" || { echo "★★★★ 失敗"; FAIL=$((FAIL+1)); }; }

echo -e "\n【資訊洩漏】"
chk "server_tokens off"        'echo "$CONF" | grep -q "server_tokens\s*off"'
chk "★★★ API 沒有對外監聽"       '! sudo ss -tlnp | grep -q "0.0.0.0:8080"'
chk "★★★★ API 有 allow/deny"    'echo "$CONF" | grep -A5 "api " | grep -q "deny all"'

echo -e "\n【TLS】"
chk "沒有 TLSv1.0/1.1"          '! echo "$CONF" | grep -qE "ssl_protocols.*TLSv1(\.[01])?[^.]"'
chk "有 HSTS"                   'echo "$CONF" | grep -qi "Strict-Transport-Security"'

echo -e "\n【安全標頭】"
for h in X-Frame-Options X-Content-Type-Options Referrer-Policy; do
    chk "$h" "echo \"\$CONF\" | grep -qi '$h'"
done

echo -e "\n【檔案存取】"
chk "★★★ 擋隱藏檔"              'echo "$CONF" | grep -q "location ~ /\\\\."'
chk "★★★★ PHP 有 try_files =404" 'echo "$CONF" | grep -A3 "location ~ .*\\\\.php" | grep -q "try_files.*=404"'

echo -e "\n【★★★ ACME】"
chk "有設定 resolver"            'echo "$CONF" | grep -q "^\s*resolver "'
echo "  ── ACME 客戶端 ──"
echo "$CONF" | grep -oP 'acme_client\s+\K\S+\s+\S+' | sed 's/^/    /' || echo "    （無）"

echo ""
[ "$FAIL" -eq 0 ] && echo "★ 全部通過" || echo "★★★★ $FAIL 項需要處理"
exit "$FAIL"
EOF
$ sudo chmod +x /usr/local/bin/angie-security-check
$ sudo angie-security-check

# ★★★ API 只讓 SSH 埠轉發存取
$ ssh -L 8080:127.0.0.1:8080 app-server
#   → 本機瀏覽器開 http://localhost:8080/console/

# ★★ 追蹤安全更新
$ apt list --upgradable 2>/dev/null | grep angie
$ curl -s https://en.angie.software/news/ | grep -i security | head
```

---

## 速查表

### ★★★ Angie 是什麼

```
NGINX 的 fork，由原 NGINX 開發者建立，BSD 授權
★★★★ 「drop-in replacement」—— 設定檔 100% 相容
★★★★ 內建：ACME / RESTful API / Prometheus / upstream 健康檢查 / Console Light
```

### 安裝與路徑

```bash
sudo apt install -y angie          # ★ MyGuard 或 Angie 官方套件庫
angie -v / angie -t / angie -T     # ★★★ 對應 nginx -v/-t/-T

/etc/angie/angie.conf              # ← /etc/nginx/nginx.conf
/etc/angie/http.d/                 # ← /etc/nginx/conf.d/
/var/log/angie/                    # ← /var/log/nginx/
/usr/lib/angie/modules/            # ← /usr/lib/nginx/modules/
```

### ★★★★ 遷移

```bash
sudo nginx -T > /root/full-config.conf     # ★★★ 先匯出完整設定
cp 設定到 /etc/angie/http.d/
sed -i 's#/etc/nginx/#/etc/angie/#g; s#/var/log/nginx/#/var/log/angie/#g' ...
sudo angie -t
sudo systemctl stop nginx && sudo systemctl disable nginx   # ★★★★ 必須
sudo systemctl enable --now angie

★★★★ 別忘了：logrotate / fail2ban / 部署腳本 / 監控
grep -rln 'nginx' /etc/logrotate.d/ /etc/fail2ban/ /usr/local/bin/
```

### ★★★★ 內建 ACME

```nginx
http {
    resolver 1.1.1.1 valid=300s ipv6=off;        # ★★★★ 必要！
    acme_client letsencrypt https://acme-v02.api.letsencrypt.org/directory;
    server {
        listen 443 ssl;
        server_name app.example.gov.tw;
        acme letsencrypt;                         # ★★★★ 一行搞定
        ssl_certificate     $acme_cert_letsencrypt;
        ssl_certificate_key $acme_cert_key_letsencrypt;
    }
}
★★★★ 先用 staging：acme-staging-v02.api.letsencrypt.org
★★★ challenge：http-01（預設）/ tls-alpn-01 / dns-01（萬用憑證）
```

### ★★★ API

```nginx
upstream backend { zone backend 1m; ... }   # ★★★★ 沒 zone 就沒統計
server { status_zone app; ... }

server {
    listen 127.0.0.1:8080;                  # ★★★★ 只綁本機
    location /status/  { api /status/; allow 127.0.0.1; deny all; }
    location /metrics  { prometheus_template main; allow 10.10.20.50; deny all; }
    location /console/ { alias /usr/share/angie-console-light/html/; }
}
```

```bash
curl -s :8080/status/connections | jq .
curl -s :8080/status/http/upstreams | jq '.[] | .peers | .[] | .state'
curl -s :8080/status/http/server_zones | jq '.[].responses'
```

### ★★★ 該不該換

```
換：★★★★ 想擺脫 certbot / 需要 upstream 健康檢查 / 需要監控 API
不換：★★★ 現有 NGINX 沒問題 / 用了大量第三方模組 / 關鍵基礎設施
★★★ 設定完全相容 → 隨時可以切回去
```

---

## 練習題

> [!question]- 練習 1：安裝與比較 ★★★
> 1. **在測試機安裝 Angie（★ 用不同的 port 避免衝突）**
> 2. **`angie -V`** → 編譯了哪些模組？
> 3. **和 `nginx -V` 比較** → 差在哪？
> 4. **把一個現有的 NGINX 設定直接複製過去** → `angie -t` 通過嗎？
> 5. **有哪些指令不認得？**
> 6. **`ls /usr/lib/angie/modules/`** → 有幾個模組？

> [!question]- 練習 2：遷移 ★★★★
> 1. **`nginx -T > full.conf` 匯出完整設定**
> 2. **執行遷移腳本**
> 3. **`angie -t`** → 通過嗎？錯在哪？
> 4. **切換服務並驗證網站正常**
> 5. **`grep -rln 'nginx' /etc/logrotate.d/ /etc/fail2ban/`** → 漏了什麼？
> 6. **執行 `angie-migration-check`** → 有幾項失敗？

> [!question]- 練習 3：ACME ★★★★
> 1. **★★★★ 先用 staging 設定 `acme_client`**
> 2. **看 `journalctl -u angie | grep -i acme`** → 過程是什麼？
> 3. **故意不設 `resolver`** → 錯誤訊息是什麼？
> 4. **憑證存在哪裡？**
> 5. **`openssl s_client` 驗證** → issuer 是 staging 嗎？
> 6. **改成正式環境並確認憑證**

> [!question]- 練習 4：API 與監控 ★★★
> 1. **設定 API 並用 `curl` 查詢**
> 2. **`upstream` 不加 `zone`** → 統計出得來嗎？
> 3. **加上 `zone` 和 `status_zone` 再試**
> 4. **故意關掉一台 upstream** → API 的 `state` 變成什麼？
> 5. **設定 Prometheus 端點並抓取**
> 6. **把 `angie-health` 腳本裝起來並加進 cron**

> [!question]- 練習 5：安全 ★★★★
> 1. **把 API 設成 `listen 0.0.0.0:8080` 且沒有 allow/deny**
> 2. **從另一台機器 `curl`** → 拿得到什麼資訊？
> 3. **這些資訊對攻擊者有什麼價值？**
> 4. **改成只綁本機 + allow/deny**
> 5. **用 SSH 埠轉發存取 Console Light**
> 6. **執行 `angie-security-check`** → 有幾項失敗？

---

## 小測驗

Q1. **Angie 和 NGINX 的關係是什麼**？設定檔相容嗎？

Q2. **Angie 相對於 NGINX 開源版最有價值的四個功能**？

Q3. **從 NGINX 遷移到 Angie，最容易漏掉的四個地方**？

Q4. **內建 ACME 相對於 certbot 解決了什麼問題**？

Q5. **設定 `acme_client` 時，為什麼一定要有 `resolver`**？

Q6. **為什麼一定要先用 Let's Encrypt 的 staging 環境**？

Q7. **三種 ACME challenge 的差別**？內網服務該用哪個？

Q8. **`upstream` 的統計出不來，最可能的原因**？

Q9. **Angie 的 API 為什麼一定要限制存取**？三層防護？

Q10. **什麼情況下不建議從 NGINX 換成 Angie**？

> [!question]- 測驗答案
> **Q1.** **Angie 是 NGINX 的 fork（分支）**，
> 由**原本的 NGINX 開發者**在 F5 收購 NGINX 後離開所建立，2022 年起獨立開發，
> **BSD 授權開源**（也有商業版 Angie PRO）。
> **★★★★ 設定檔 100% 相容** —— 官方定位是
> **「drop-in replacement for nginx」**：
> **每一個指令、每一個模組都能不改就用**。
> 這是它最大的優勢 —— 遷移的成本極低，
> 而且**隨時可以切回 NGINX**（設定檔通用）。
> 差別主要在**路徑**（`/etc/nginx` → `/etc/angie`）、
> **服務名稱**（`nginx` → `angie`），
> 以及 Angie **多出來的功能**（內建 ACME、API、健康檢查）。
> 官方：`angie.software`（英文版是 `en.angie.software`）。
>
> **Q2.** ①**★★★★ 內建 ACME（`acme_client`）** ——
> 不需要 certbot、不需要 cron、續期後**不需要 reload**（熱載入），
> 支援 HTTP-01 / DNS-01 / TLS-ALPN-01；
> ②**★★★★ RESTful JSON API** ——
> NGINX 開源版只有 `stub_status`（幾個總計數字），
> Angie 提供**每個 server zone、每個 upstream、每個 location 的完整統計**；
> ③**★★★ upstream 主動健康檢查** ——
> **這是 NGINX Plus（商業版）才有的功能**，Angie 免費提供，
> 上游還沒影響到使用者就先被移除；
> ④**★★★ Prometheus 內建匯出 + Console Light 監控介面** ——
> 不用另外裝 nginx-exporter。
> 另外還有依 Docker 標籤的**動態 upstream 更新**（不用 reload）和 session sticky。
>
> **Q3.** ①**★★★★ 部署腳本** ——
> `systemctl reload nginx`、`nginx -t` 在遷移後**完全不會有作用**，
> 而且 `nginx -t` 會因為指令不存在而讓部署腳本失敗；
> ②**★★★ logrotate** —— `/etc/logrotate.d/nginx` 仍指向 `/var/log/nginx`，
> **Angie 的日誌在 `/var/log/angie/` 不會被輪替 → 磁碟塞爆**；
> ③**★★★ fail2ban** —— `logpath = /var/log/nginx/error.log` 要改；
> ④**★★★★ 監控與告警** —— systemd 服務名稱、
> GoAccess 的日誌路徑、Prometheus 的 nginx-exporter（可以拿掉，Angie 內建）。
> **找出所有需要改的地方**：
> ```bash
> grep -rln 'nginx' /etc/logrotate.d/ /etc/fail2ban/ /etc/cron.d/ /usr/local/bin/
> ```
> 還有一個必做的：**`systemctl stop nginx && systemctl disable nginx`**
> —— 否則 80/443 被佔用，Angie 起不來。
>
> **Q4.** **★★★★ certbot 最大的問題是「續期成功但 reload 失敗」** ——
> 憑證檔案更新了，但 nginx 還在用記憶體中的舊憑證，
> **通常到過期當天才有人發現**。
> 其他問題：
> ①**要另外安裝並維護一個程式**；
> ②**要設 cron**（cron 停掉就沒人知道）；
> ③**要為 `.well-known/acme-challenge` 設定 location**
> （而且不能被 HTTPS 重導向攔截）；
> ④**DNS-01 要另外裝外掛**；
> ⑤**失敗時沒有明顯的告警**。
> **Angie 內建 ACME 全部解決**：
> `acme letsencrypt;` 一行，**憑證熱載入不用 reload**，
> 狀態在 API 和日誌中看得到，DNS-01 內建。
>
> **Q5.** 因為 **ACME 客戶端需要解析 CA 的網域名稱**
> （`acme-v02.api.letsencrypt.org`）才能連上去申請憑證。
> **NGINX/Angie 的內部 DNS 解析不使用系統的 `/etc/resolv.conf`** ——
> 它有自己的 resolver 機制，**沒有明確設定 `resolver` 指令就無法解析任何網域**。
> **★★★ 而且失敗的訊息通常不明顯**，只會看到 ACME 一直失敗但不知道為什麼。
> **正確設定**：
> ```nginx
> http {
>     resolver 1.1.1.1 8.8.8.8 valid=300s ipv6=off;
>     acme_client letsencrypt https://acme-v02.api.letsencrypt.org/directory;
> }
> ```
> **`ipv6=off` 也很重要** —— 沒有 IPv6 連線能力的環境下，
> 解析到 AAAA 記錄會導致連線逾時。
> 同樣的問題也發生在 `proxy_pass` 用網域名稱時。
>
> **Q6.** 因為 **Let's Encrypt 的正式環境有嚴格的速率限制**：
> **同一個註冊網域每週最多 50 張憑證**、
> **失敗的驗證每小時最多 5 次**、
> 重複的憑證每週 5 張。
> **★★★★ 設定錯誤時 ACME 客戶端會反覆重試 → 很快就撞到上限 → 被鎖住一整週**，
> 這期間**你完全無法申請憑證**，正式上線就開天窗了。
> **staging 環境的限制寬鬆很多**，適合反覆測試設定：
> ```nginx
> acme_client le_staging https://acme-staging-v02.api.letsencrypt.org/directory;
> ```
> **staging 簽發的憑證不被瀏覽器信任**（issuer 是 `(STAGING) Let's Encrypt`），
> 但這正好可以驗證「整個流程有沒有跑通」。
> 確認無誤後才換成正式的 directory URL。
>
> **Q7.** **`http-01`（預設）** —— CA 連到你的 **80 埠**取一個檔案驗證。
> **需要 80 埠從外網可達**，而且不能被全部 301 到 443。
> 適合一般的對外網站。
> **`tls-alpn-01`** —— 透過 **443 埠的 TLS 交握**驗證（用特殊的 ALPN 協定）。
> **不需要 80 埠**，適合只開 443 的環境。
> **`dns-01`** —— 在 DNS 加一筆 **TXT 記錄**驗證。
> **★★★★ 這是唯一能簽發萬用憑證（`*.example.com`）的方式**，
> 而且**完全不需要伺服器從外網可達**。
> **★★★ 內網服務應該用 dns-01** ——
> 內網的機器外面連不到，http-01 和 tls-alpn-01 都不可能成功。
> 代價是需要 DNS provider 的 API 或 hook 腳本來自動新增/刪除 TXT 記錄。
>
> **Q8.** **★★★★ `upstream` 區塊裡沒有定義 `zone`**。
> Angie 的統計資料存放在**共享記憶體區**中，讓所有 worker 程序都能更新，
> **沒有 `zone` 就沒有地方存統計資料**，API 自然查不到。
> ```nginx
> upstream backend {
>     zone backend 1m;          # ★★★★ 這一行是必要的
>     server 10.10.20.31:8080;
> }
> ```
> **同樣的道理**：`server` 區塊要有 **`status_zone name;`** 才會有該站台的統計；
> `location` 也可以加 `status_zone` 取得更細的統計。
> **順帶一提**，`zone` 也是 upstream **主動健康檢查**和
> **動態 upstream 更新**的前提 —— 沒有共享記憶體就無法在 worker 間同步狀態。
> **檢查**：`sudo angie -T | grep -E 'zone |status_zone'`。
>
> **Q9.** 因為 **API 會暴露完整的內部資訊**：
> **所有 upstream 的位址與健康狀態（★ 內部網路拓撲）**、
> 各站台的流量與錯誤統計、
> **版本號與載入時間**（可以查有沒有已知漏洞）、
> worker 數與共享記憶體使用狀況、SSL 交握的成功/失敗數。
> **對攻擊者這是一份完整的偵察報告** ——
> 知道有幾台後端、位址是什麼、哪一台不健康（可以集中攻擊）。
> **三層防護**：
> ①**★★★★ `listen 127.0.0.1:8080;`** —— 只綁本機，外部根本連不到；
> ②**`allow` / `deny` 存取控制** —— 即使綁了內網介面也要限制來源；
> ③**★★ 要遠端存取時用 SSH 埠轉發**：
> ```bash
> ssh -L 8080:127.0.0.1:8080 app-server
> ```
> **絕對不要**：`listen 0.0.0.0:8080;` 或沒有 `deny all;` 的 API location。
>
> **Q10.** ①**★★★ 現有的 NGINX 運作良好、沒有特殊需求** ——
> 「沒有壞就不要修」，遷移本身就有風險；
> ②**★★★ 用了大量第三方動態模組** ——
> 要先確認每一個都有對應的 Angie 版本，
> 否則 `angie -t` 會因為 `unknown directive` 而失敗；
> ③**★★★ 機關的關鍵基礎設施** ——
> Angie 的**生態系比 NGINX 小很多**：
> 文件、教學、Stack Overflow 的答案都少，
> 遇到問題時可參考的資源有限；
> 商業支援要另外付費（Angie PRO），
> 而且**不在 Ubuntu/Debian 的官方支援範圍**（安全更新要自己追）。
> **★★★★ 折衷做法**：
> **新專案用 Angie**（享受內建功能），
> **既有系統維持 NGINX**（除非有明確的痛點，例如受夠了 certbot、
> 或需要 upstream 健康檢查但不想買 NGINX Plus）。
> 因為設定完全相容，**隨時可以切回去**，風險其實可控。

---

## 延伸閱讀

- [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]] — 套件庫的加入與風險評估
- [[060-02-05-03-guide-MyGuard-autocert自動憑證模組]] — **★★★ NGINX 版的自動憑證（MyGuard 自製）**
- [[060-02-05-07-guide-MyGuard-動態模組管理]] — 模組的安裝與載入
- [[060-02-05-08-guide-MyGuard-MyGuard實戰組合]] — 完整的實戰配置
- [[060-02-02-02-guide-Nginx-設定語法與虛擬主機]] — **★★★ 設定語法完全通用**
- [[060-02-02-06-guide-Nginx-HTTPS與Certbot]] — certbot 的傳統做法
