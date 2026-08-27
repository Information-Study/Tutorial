---
title: "Apache 安裝與目錄結構"
desc: "Debian 系與 RHEL 系截然不同的目錄配置，以及 a2en* 系列工具"
aliases: [httpd, apache2, a2ensite, a2enmod, apachectl]
tags: [群組/軟體與開發工具, 服務/apache, 主題/安裝]
category: Apache
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[01-Web伺服器概論]]"]
updated: 2026-08-28
---

# Apache 安裝與目錄結構

> [!abstract] 這篇你會學到
> - 安裝 Apache 並理解 **Debian 系與 RHEL 系差異極大**的目錄結構
> - 熟練使用 **`a2enmod` / `a2ensite` / `a2enconf`** 系列工具
> - 讀懂 **`apachectl -S`** 與 **`apachectl -M`** 的輸出
> - 完成**第一次啟動就該做對的六件事**
> - 知道 **Apache 與 Nginx 在設計哲學上的根本差異**

## 前置知識

- [[01-Web伺服器概論]] — 請求流程與 LXMP 架構

---

## Apache 與 Nginx 的根本差異

| | **Apache** | **Nginx** |
| --- | --- | --- |
| **架構** | **程序／執行緒**（每個連線一個 worker） | **事件驅動**（單一 worker 處理數千連線） |
| **設定風格** | **可以分散在各目錄**（`.htaccess`） | **只能集中**在設定檔 |
| **模組** | **可動態載入／卸載**（`a2enmod`） | 編譯時決定（新版支援動態模組） |
| **PHP 整合** | **可以內嵌**（`mod_php`）或 FPM | **只能** FPM |
| **高並發** | 記憶體用量隨連線數線性成長 | **記憶體用量幾乎不變** |
| **靜態檔** | 較慢 | **快很多** |
| **設定彈性** | **極高**（`.htaccess` 讓開發者能自己改） | 集中管理、較嚴謹 |

> [!tip] 什麼時候該選 Apache
> ```
> ✓ 應用程式【依賴 .htaccess】（WordPress 外掛、共享主機、舊系統）
> ✓ 需要 mod_php 的內嵌執行模式
> ✓ 團隊熟悉 Apache，且流量不大
> ✓ 需要某個只有 Apache 有的模組
>
> ✗ 高並發、大量靜態檔 → Nginx
> ✗ 純反向代理 → Nginx
> ```
>
> **實務上最常見的組合**：
> **Nginx 在前（處理靜態檔、TLS、反向代理），Apache 在後（跑 PHP）**
> —— 見 [[04-Nginx與Apache選型與共存]]。

---

## 安裝

```bash
# ═══ Ubuntu / Debian ═══
$ sudo apt update
$ sudo apt install -y apache2

$ apache2 -v
Server version: Apache/2.4.62 (Ubuntu)

$ sudo systemctl status apache2
$ sudo systemctl enable --now apache2
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> $ sudo dnf install -y httpd
> $ httpd -v
> Server version: Apache/2.4.62 (Rocky Linux)
>
> $ sudo systemctl enable --now httpd
>
> # ★ 防火牆
> $ sudo firewall-cmd --permanent --add-service=http --add-service=https
> $ sudo firewall-cmd --reload
> ```
>
> **★ 名稱差異貫穿整個系統**：
> | | Debian 系 | RHEL 系 |
> | --- | --- | --- |
> | 套件名 | `apache2` | **`httpd`** |
> | 服務名 | `apache2` | **`httpd`** |
> | 指令 | `apache2ctl` / `apachectl` | **`apachectl`** / `httpd` |
> | 執行身分 | **`www-data`** | **`apache`** |
> | 設定目錄 | `/etc/apache2/` | **`/etc/httpd/`** |
> | 主設定檔 | `apache2.conf` | **`conf/httpd.conf`** |
> | 網站根目錄 | `/var/www/html` | **`/var/www/html`**（相同） |
> | 日誌 | `/var/log/apache2/` | **`/var/log/httpd/`** |

---

## 目錄結構（★ 兩系差異極大）

### Debian / Ubuntu

```
/etc/apache2/
├── apache2.conf              ★ 主設定檔（相當於 nginx.conf）
├── ports.conf                ★ Listen 指令集中在這裡
├── envvars                   ★ 環境變數（APACHE_RUN_USER 等）
├── magic
│
├── mods-available/           ★ 所有可用模組的 .load 與 .conf
│   ├── rewrite.load
│   ├── ssl.load
│   ├── ssl.conf
│   └── ...
├── mods-enabled/             ★ 已啟用的模組（符號連結）
│   └── rewrite.load -> ../mods-available/rewrite.load
│
├── sites-available/          ★ 所有站台設定
│   ├── 000-default.conf
│   └── default-ssl.conf
├── sites-enabled/            ★ 已啟用的站台（符號連結）
│   └── 000-default.conf -> ../sites-available/000-default.conf
│
├── conf-available/           ★ 其他設定片段
│   ├── charset.conf
│   ├── security.conf         ★ 安全相關設定在這裡
│   └── ...
└── conf-enabled/             ★ 已啟用的設定片段（符號連結）
```

```
/var/www/html/                預設網站根目錄
/var/log/apache2/             access.log、error.log、other_vhosts_access.log
/usr/lib/apache2/modules/     模組的 .so 檔
/usr/sbin/apache2ctl          控制指令
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```
> /etc/httpd/
> ├── conf/
> │   ├── httpd.conf            ★ 主設定檔（【所有東西都在這裡面】）
> │   └── magic
> ├── conf.d/                   ★ 額外設定（★ 站台設定放這裡，沒有 sites-*）
> │   ├── ssl.conf
> │   ├── welcome.conf
> │   └── userdir.conf
> ├── conf.modules.d/           ★ 模組載入設定
> │   ├── 00-base.conf
> │   ├── 00-mpm.conf           ★ MPM 選擇在這裡
> │   ├── 00-ssl.conf
> │   └── 10-php.conf
> ├── modules -> /usr/lib64/httpd/modules
> └── logs -> /var/log/httpd
> ```
>
> **★ RHEL 系【沒有】 `sites-available` / `sites-enabled` 機制**，
> 也**沒有 `a2ensite` / `a2enmod` 指令**。
> 所有站台設定放在 `/etc/httpd/conf.d/*.conf`，
> 模組載入寫在 `/etc/httpd/conf.modules.d/*.conf`。
>
> **想要類似的機制可以自己建**：
> ```bash
> $ sudo mkdir -p /etc/httpd/sites-{available,enabled}
> $ echo 'IncludeOptional sites-enabled/*.conf' | \
>     sudo tee -a /etc/httpd/conf/httpd.conf
> $ sudo ln -s /etc/httpd/sites-available/mysite.conf /etc/httpd/sites-enabled/
> ```

### 為什麼 Debian 要搞這套符號連結

```
好處：
  ✓ 「安裝了但沒啟用」與「已啟用」分開
  ✓ 停用一個站台只要 a2dissite，設定檔還在
  ✓ 套件升級時 available 的檔案會更新，enabled 的連結不受影響
  ✓ 一眼看出目前啟用了什麼：ls sites-enabled/

代價：
  ✗ 與上游文件、RHEL 系的做法不一致
  ✗ 直接編輯 sites-enabled/ 裡的檔案會改到 available（因為是連結）
```

---

## `a2*` 系列工具（Debian 系）

```bash
# ═══ 模組 ═══
$ sudo a2enmod rewrite                    # 啟用
$ sudo a2enmod ssl headers proxy proxy_fcgi     # 一次多個
$ sudo a2dismod status                    # 停用
$ apache2ctl -M                           # 列出【已載入】的模組

# ═══ 站台 ═══
$ sudo a2ensite mysite                    # 啟用（副檔名 .conf 可省略）
$ sudo a2dissite 000-default              # ★ 停用預設站台
$ apache2ctl -S                           # ★ 列出所有 VirtualHost

# ═══ 設定片段 ═══
$ sudo a2enconf security
$ sudo a2disconf serve-cgi-bin

# ═══ 套用 ═══
$ sudo apache2ctl configtest              # ★ 檢查語法（= apache2ctl -t）
$ sudo systemctl reload apache2           # 平滑重新載入
$ sudo systemctl restart apache2          # 完整重啟
```

> [!warning] `a2enmod` 之後幾乎都要 `restart` 而不是 `reload`
> **載入新模組需要重啟 Apache**。
> ```bash
> $ sudo a2enmod rewrite
> Enabling module rewrite.
> To activate the new configuration, you need to run:
>   systemctl restart apache2          # ★ 它自己會告訴你
> ```
> 站台設定（`a2ensite`）則 `reload` 就夠了。

### 三個必看的檢查指令

```bash
# ═══ ① 語法檢查（改設定後【一定要跑】）═══
$ sudo apache2ctl configtest
Syntax OK

# 有錯時
$ sudo apache2ctl configtest
AH00526: Syntax error on line 12 of /etc/apache2/sites-enabled/mysite.conf:
Invalid command 'ProxyPass', perhaps misspelled or defined by a module not included
#                                                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#                                                    ★ 忘了 a2enmod proxy

# ═══ ② ★ 列出所有 VirtualHost 與比對順序 ═══
$ sudo apache2ctl -S
VirtualHost configuration:
*:80    is a NameVirtualHost
        default server app.example.gov.tw (/etc/apache2/sites-enabled/app.conf:1)
        port 80 namevhost app.example.gov.tw (/etc/apache2/sites-enabled/app.conf:1)
        port 80 namevhost api.example.gov.tw (/etc/apache2/sites-enabled/api.conf:1)
*:443   is a NameVirtualHost
        default server app.example.gov.tw (/etc/apache2/sites-enabled/app-ssl.conf:1)
        port 443 namevhost app.example.gov.tw (/etc/apache2/sites-enabled/app-ssl.conf:1)

ServerRoot: "/etc/apache2"
Main DocumentRoot: "/var/www/html"
Main ErrorLog: "/var/log/apache2/error.log"
Mutex default: dir="/var/run/apache2/" mechanism=default
PidFile: "/var/run/apache2/apache2.pid"
User: name="www-data" id=33
Group: name="www-data" id=33
```

> [!danger] `apachectl -S` 中的 `default server` 是關鍵
> **沒有比對到任何 `ServerName` 的請求，都會落到 `default server`。**
>
> ```
> Apache 的 default server = 【第一個載入的】 VirtualHost
>   → 而載入順序是【檔名的字母順序】
>     → 所以 000-default.conf 才會叫這個名字
> ```
>
> **常見問題**：新增了一個站台，結果它變成了 default server，
> **所有找不到對應網域的請求（包含掃描器）都連到它**。
>
> **解法**：建立一個 `000-catch-all.conf`：
> ```apache
> # /etc/apache2/sites-available/000-catch-all.conf
> <VirtualHost *:80>
>     ServerName catch-all.invalid
>     RedirectMatch 404 ^/.*$
>     # 或直接關閉連線（需要 mod_rewrite）
>     # RewriteEngine On
>     # RewriteRule ^ - [F]
> </VirtualHost>
> ```

```bash
# ═══ ③ 列出已載入的模組 ═══
$ apache2ctl -M
Loaded Modules:
 core_module (static)
 so_module (static)
 mpm_event_module (shared)          ★ 目前的 MPM
 authz_core_module (shared)
 rewrite_module (shared)
 ssl_module (shared)
 proxy_module (shared)
 proxy_fcgi_module (shared)
 headers_module (shared)
 ...

# 檢查特定模組
$ apache2ctl -M | grep -E 'rewrite|ssl|proxy_fcgi|headers'
```

---

## 第一次啟動就該做對的六件事

```bash
# ═══ ① 停用預設站台 ═══
$ sudo a2dissite 000-default
$ sudo systemctl reload apache2
# ★ 預設站台會顯示「Apache2 Default Page」，洩漏版本與系統資訊

# ═══ ② 隱藏版本資訊 ═══
$ sudo tee /etc/apache2/conf-available/hardening.conf >/dev/null <<'EOF'
# ★ 隱藏版本號（Prod = 只顯示 "Apache"）
ServerTokens Prod
ServerSignature Off

# ★ 關閉目錄列表與危險選項
<Directory />
    Options None
    AllowOverride None
    Require all denied
</Directory>

# ★ 關閉 TRACE 方法（防 Cross-Site Tracing）
TraceEnable Off

# ★ 逾時設定（防 Slowloris）
Timeout 30
KeepAliveTimeout 5
RequestReadTimeout header=20-40,MinRate=500 body=20,MinRate=500

# ★ 限制請求大小
LimitRequestBody 20971520
LimitRequestFields 100
LimitRequestFieldSize 8190
LimitRequestLine 8190

# ★ 移除 ETag（避免洩漏 inode）
FileETag None
EOF

$ sudo a2enconf hardening
$ sudo a2enmod headers
$ sudo systemctl restart apache2

# 驗證
$ curl -sI http://localhost/ | grep -i '^server'
Server: Apache                      # ★ 沒有版本號
```

```bash
# ═══ ③ 啟用必要模組 ═══
$ sudo a2enmod rewrite headers ssl http2 proxy proxy_fcgi setenvif deflate expires
$ sudo systemctl restart apache2

# ═══ ④ 停用不需要的模組（★ 減少攻擊面）═══
$ sudo a2dismod status autoindex userdir cgi
$ sudo systemctl restart apache2

# ═══ ⑤ 建立自己的第一個站台 ═══
$ sudo mkdir -p /var/www/mysite/public
$ echo '<h1>OK</h1>' | sudo tee /var/www/mysite/public/index.html
$ sudo chown -R www-data:www-data /var/www/mysite

$ sudo tee /etc/apache2/sites-available/mysite.conf >/dev/null <<'EOF'
<VirtualHost *:80>
    ServerName mysite.example.gov.tw
    DocumentRoot /var/www/mysite/public       # ★ public 子目錄

    <Directory /var/www/mysite/public>
        Options -Indexes +FollowSymLinks
        AllowOverride None                     # ★ 不用 .htaccess（效能較好）
        Require all granted
    </Directory>

    ErrorLog  ${APACHE_LOG_DIR}/mysite-error.log
    CustomLog ${APACHE_LOG_DIR}/mysite-access.log combined
</VirtualHost>
EOF

$ sudo a2ensite mysite
$ sudo apache2ctl configtest && sudo systemctl reload apache2

# ═══ ⑥ 把 /etc/apache2 納入版本控制 ═══
$ cd /etc/apache2
$ sudo git init -b main
$ sudo git add -A
$ sudo git commit -q -m "初始設定"
```

> [!tip] 改設定前先設一個「自動回退」的保險
> ```bash
> # ★ 15 分鐘後自動還原（改遠端主機的設定時保命用）
> $ sudo cp -a /etc/apache2 /etc/apache2.bak
> $ echo 'rm -rf /etc/apache2 && mv /etc/apache2.bak /etc/apache2 && systemctl reload apache2' | \
>     sudo at now + 15 minutes
>
> # 改完設定、確認正常後，取消它
> $ sudo atq
> $ sudo atrm <job號>
> $ sudo rm -rf /etc/apache2.bak
> ```

---

## 完整實戰範例

### 安裝檢查腳本

```bash
#!/usr/bin/env bash
# Apache 安裝後檢查
if command -v apache2ctl >/dev/null; then
    CTL=apache2ctl; SVC=apache2; CONF=/etc/apache2; LOG=/var/log/apache2; USR=www-data
else
    CTL=apachectl;  SVC=httpd;   CONF=/etc/httpd;  LOG=/var/log/httpd;  USR=apache
fi

echo "═══ Apache 檢查（$SVC）═══"

echo -e "\n【1】版本與服務"
$CTL -v 2>/dev/null | sed 's/^/  /'
systemctl is-active $SVC >/dev/null && echo "  ✓ 執行中" || echo "  ✗ 未執行"
systemctl is-enabled $SVC >/dev/null 2>&1 && echo "  ✓ 開機自啟" || echo "  ⚠ 未設定開機自啟"

echo -e "\n【2】設定語法"
sudo $CTL configtest 2>&1 | sed 's/^/  /'

echo -e "\n【3】MPM"
sudo $CTL -M 2>/dev/null | grep -oP 'mpm_\K\w+(?=_module)' | sed 's/^/  目前 MPM：/'

echo -e "\n【4】★ 關鍵模組"
for m in rewrite ssl headers http2 proxy proxy_fcgi deflate expires setenvif; do
    sudo $CTL -M 2>/dev/null | grep -q "${m}_module" \
        && echo "  ✓ $m" || echo "  ✗ $m（未啟用）"
done

echo -e "\n【5】應該停用的模組（減少攻擊面）"
for m in status autoindex userdir cgi info; do
    sudo $CTL -M 2>/dev/null | grep -q "${m}_module" \
        && echo "  ⚠ $m 【建議停用】" || echo "  ✓ $m 已停用"
done

echo -e "\n【6】★ VirtualHost 與 default server"
sudo $CTL -S 2>&1 | grep -E 'namevhost|default server|VirtualHost config' | sed 's/^/  /'

echo -e "\n【7】監聽的埠"
sudo ss -tlnp | grep -E 'apache|httpd' | sed 's/^/  /'

echo -e "\n【8】執行身分"
ps -o user=,comm= -C "$SVC" 2>/dev/null | sort -u | sed 's/^/  /'
echo "  ★ 應該是 root（master）+ $USR（worker）"

echo -e "\n【9】安全設定"
FULL=$(sudo $CTL -t -D DUMP_CONFIG 2>/dev/null || sudo grep -rh '' $CONF --include='*.conf' 2>/dev/null)
for item in "ServerTokens Prod:隱藏版本" "ServerSignature Off:關閉簽章" "TraceEnable Off:關閉 TRACE"; do
    k="${item%%:*}"; d="${item##*:}"
    echo "$FULL" | grep -qi "^\s*$k" && echo "  ✓ $d" || echo "  ✗ $d"
done
echo "$FULL" | grep -qiE '^\s*Options.*[^-]Indexes' && echo "  ⚠ 有 Options Indexes【目錄列表會開啟】" \
                                                    || echo "  ✓ 沒有目錄列表"

echo -e "\n【10】從外部驗證"
SRV=$(curl -sI -m 5 http://localhost/ 2>/dev/null | grep -i '^server:' | tr -d '\r')
echo "  ${SRV:-（連不上）}"
echo "$SRV" | grep -qE 'Apache/[0-9]' && echo "  ⚠ 洩漏版本號 → ServerTokens Prod"

echo -e "\n【11】DocumentRoot 檢查"
echo "$FULL" | grep -oP '^\s*DocumentRoot\s+"?\K[^"\s]+' | sort -u | while read -r d; do
    if [[ "$d" == */public ]] || [[ "$d" == */html ]] || [[ "$d" == */dist ]]; then
        echo "  ✓ $d"
    else
        echo "  ⚠ $d 【確認是否應指向 public/ 子目錄】"
    fi
done

echo -e "\n【12】日誌"
ls -lh $LOG/*.log 2>/dev/null | awk '{printf "  %-45s %s\n", $NF, $5}'
echo "  近期錯誤："
sudo tail -5 $LOG/error*.log 2>/dev/null | sed 's/^/    /'
```

---

## 常見錯誤與排錯

| 現象／錯誤 | 原因 | 解法 |
| --- | --- | --- |
| **`Invalid command 'RewriteEngine'`** | **模組沒啟用** | `sudo a2enmod rewrite && sudo systemctl restart apache2` |
| `Invalid command 'ProxyPass'` | 同上 | `sudo a2enmod proxy proxy_http proxy_fcgi` |
| `Invalid command 'Header'` | 同上 | `sudo a2enmod headers` |
| **`a2enmod` 後沒生效** | **只做了 reload** | **載入模組要 `restart`** |
| `AH00558: Could not reliably determine the server's fully qualified domain name` | 沒有全域 `ServerName` | 在 `apache2.conf` 加 `ServerName localhost` |
| **新站台變成了 default server** | Apache 用**第一個載入的** VirtualHost | 建立 `000-catch-all.conf` |
| **改了 `sites-enabled/` 裡的檔案，`sites-available/` 也變了** | **它們是符號連結** | 這是預期行為；編輯 `sites-available/` 就好 |
| `Address already in use` | 埠被佔用（常是 Nginx） | `sudo ss -tlnp \| grep :80` |
| **RHEL 上找不到 `a2enmod`** | **RHEL 系沒有這套工具** | 直接編輯 `/etc/httpd/conf.modules.d/` |
| RHEL 上找不到 `sites-available` | RHEL 系沒有這個機制 | 用 `/etc/httpd/conf.d/*.conf` |
| **權限錯誤（403）** | DocumentRoot 的父目錄缺 `x` 權限 | `chmod o+x` 沿路徑每一層 |
| RHEL 上一直 403 但權限正常 | **SELinux** | `sudo restorecon -Rv /var/www`；`ausearch -m avc` |
| 預設頁面還在 | 沒停用 `000-default` | `sudo a2dissite 000-default` |
| `Permission denied` 寫不了日誌 | 日誌目錄權限 | `chown root:adm /var/log/apache2` |

### 排查流程

```bash
# 【1】語法
$ sudo apache2ctl configtest

# 【2】服務狀態與啟動失敗原因
$ sudo systemctl status apache2 -l --no-pager
$ sudo journalctl -u apache2 -n 50 --no-pager

# 【3】★ 完整的生效設定（相當於 nginx -T）
$ sudo apache2ctl -t -D DUMP_CONFIG 2>/dev/null | head -50
$ sudo apache2ctl -t -D DUMP_VHOSTS
$ sudo apache2ctl -t -D DUMP_MODULES
$ sudo apache2ctl -t -D DUMP_RUN_CFG

# 【4】錯誤日誌
$ sudo tail -50 /var/log/apache2/error.log

# 【5】埠佔用
$ sudo ss -tlnp | grep -E ':(80|443)'
```

> [!tip] Apache 的「`nginx -T`」等效指令
> ```bash
> $ sudo apache2ctl -t -D DUMP_CONFIG      # ★ 完整的展開設定（2.4.34+）
> $ sudo apache2ctl -t -D DUMP_VHOSTS      # = apache2ctl -S
> $ sudo apache2ctl -t -D DUMP_MODULES     # = apache2ctl -M
> $ sudo apache2ctl -t -D DUMP_INCLUDES    # 所有 Include 的檔案
> ```

---

## 安全性注意事項

> [!danger] 預設安裝的四個問題
> ```
> ① 「Apache2 Default Page」洩漏 OS 版本與目錄結構
>    → sudo a2dissite 000-default
>
> ② Server: Apache/2.4.62 (Ubuntu) 洩漏版本
>    → ServerTokens Prod
>       ServerSignature Off
>
> ③ /icons/、/manual/ 等預設別名可存取
>    → sudo a2disconf serve-cgi-bin
>       檢查 /etc/apache2/mods-enabled/alias.conf
>
> ④ ★ 全域 <Directory /> 若設成 Require all granted
>    → 【整個檔案系統都可能被存取】
> ```
>
> ```apache
> # ★ 正確的全域預設：全部拒絕，再逐一開放
> <Directory />
>     Options None
>     AllowOverride None
>     Require all denied
> </Directory>
>
> <Directory /var/www/mysite/public>
>     Options -Indexes +FollowSymLinks
>     AllowOverride None
>     Require all granted
> </Directory>
> ```

> [!warning] `Options` 的危險選項
> | 選項 | 風險 |
> | --- | --- |
> | **`Indexes`** | **開啟目錄列表** —— 一定要用 `-Indexes` 關掉 |
> | `Includes` | 啟用 SSI，**可能執行指令**（用 `IncludesNOEXEC` 較安全） |
> | **`ExecCGI`** | **允許執行 CGI 腳本** —— 非必要不開 |
> | `FollowSymLinks` | 跟隨符號連結（**可能跳出 DocumentRoot**） |
> | `SymLinksIfOwnerMatch` | 較安全的替代（但有效能代價） |
> | `MultiViews` | **內容協商** —— 可能繞過副檔名限制 |
>
> ```apache
> # ★ 建議
> Options -Indexes -Includes -ExecCGI -MultiViews +FollowSymLinks
> ```

> [!tip] `AllowOverride None` 的兩個好處
> ```
> ① 效能：Apache 不需要在【每個請求】對【路徑上的每一層目錄】
>          去 stat() 找 .htaccess
>
> ② 安全：開發者無法用 .htaccess 覆蓋你的安全設定
> ```
> **除非應用程式真的依賴 `.htaccess`（例如 WordPress），
> 否則一律 `AllowOverride None`，把規則寫進 VirtualHost。**
>
> 見 [[04-Apache-htaccess與Rewrite]]。

---

## 速查表

### 兩系差異 ★

| | Debian / Ubuntu | RHEL / Rocky |
| --- | --- | --- |
| 套件／服務 | `apache2` | **`httpd`** |
| 設定目錄 | `/etc/apache2/` | **`/etc/httpd/`** |
| 主設定檔 | `apache2.conf` | **`conf/httpd.conf`** |
| 站台設定 | `sites-available/` + `a2ensite` | **`conf.d/*.conf`（沒有 a2ensite）** |
| 模組 | `mods-available/` + `a2enmod` | **`conf.modules.d/*.conf`** |
| 執行身分 | `www-data` | **`apache`** |
| 日誌 | `/var/log/apache2/` | **`/var/log/httpd/`** |
| 額外 | — | **SELinux** |

### 常用指令

```bash
sudo a2enmod rewrite ssl headers proxy proxy_fcgi http2 deflate expires
sudo a2dismod status autoindex userdir cgi
sudo a2ensite mysite            # 啟用站台
sudo a2dissite 000-default      # ★ 停用預設站台
sudo a2enconf hardening

sudo apache2ctl configtest      # ★ 語法檢查
sudo apache2ctl -S              # ★ 列出 VirtualHost 與 default server
sudo apache2ctl -M              # 已載入模組
sudo apache2ctl -t -D DUMP_CONFIG   # ★ 完整展開設定（≈ nginx -T）

sudo systemctl reload apache2   # 改站台設定
sudo systemctl restart apache2  # ★ 改模組後必須
```

### 首次設定六件事

```
① sudo a2dissite 000-default
② ServerTokens Prod / ServerSignature Off / TraceEnable Off
③ a2enmod rewrite headers ssl http2 proxy proxy_fcgi deflate expires
④ a2dismod status autoindex userdir cgi
⑤ DocumentRoot 指向 public/；<Directory /> 預設 Require all denied
⑥ /etc/apache2 納入 git
```

### 安全基準設定

```apache
ServerTokens Prod
ServerSignature Off
TraceEnable Off
FileETag None
Timeout 30
KeepAliveTimeout 5
RequestReadTimeout header=20-40,MinRate=500 body=20,MinRate=500
LimitRequestBody 20971520

<Directory />
    Options None
    AllowOverride None
    Require all denied
</Directory>

<Directory /var/www/app/public>
    Options -Indexes -Includes -ExecCGI -MultiViews +FollowSymLinks
    AllowOverride None
    Require all granted
</Directory>
```

### 排查

```bash
sudo apache2ctl configtest
sudo systemctl status apache2 -l
sudo journalctl -u apache2 -n 50
sudo tail -50 /var/log/apache2/error.log
sudo apache2ctl -S               # ★ default server 是誰
sudo ss -tlnp | grep -E ':(80|443)'
sudo ausearch -m avc -ts recent  # RHEL: SELinux
```

| error.log 訊息 | 原因 |
| --- | --- |
| `Invalid command 'XXX'` | **模組沒啟用** → `a2enmod` + **restart** |
| `Could not reliably determine FQDN` | 缺全域 `ServerName` |
| `Address already in use` | 埠被佔用（常是 Nginx） |
| `Permission denied` | 目錄權限 / **SELinux** |

---

## 練習題

> [!question]- 練習 1：熟悉目錄結構
> 1. 安裝 Apache
> 2. `tree -L 2 /etc/apache2`（或 `/etc/httpd`）
> 3. **找出**：主設定檔、埠設定、已啟用的模組、已啟用的站台
> 4. `ls -la /etc/apache2/mods-enabled/ | head -20` —— **它們都是什麼？**
> 5. 執行 `sudo apache2ctl -S`，**說出 default server 是哪一個、為什麼**
> 6. 若你有 RHEL 系的環境，**對照兩者的差異**

> [!question]- 練習 2：模組管理
> 1. `apache2ctl -M | wc -l` —— 預設載入了幾個模組？
> 2. 寫一個含 `RewriteEngine On` 的站台設定
> 3. `apache2ctl configtest` → **看到什麼錯誤？**
> 4. `a2enmod rewrite` 後只做 `reload` → **生效了嗎？**
> 5. 改成 `restart` → 再測
> 6. **停用五個不需要的模組**，確認網站仍正常

> [!question]- 練習 3：default server 陷阱
> 1. 建立兩個站台：`aaa.test.local` 與 `zzz.test.local`
> 2. `apache2ctl -S` —— **哪一個是 default server？**
> 3. `curl -H 'Host: 不存在的網域' http://localhost/` → **連到哪一個？**
> 4. 建立 `000-catch-all.conf` 回傳 404
> 5. **重測，確認未知網域連到 catch-all**
> 6. 對照 Nginx 的 `default_server` 機制，**兩者有什麼不同？**

> [!question]- 練習 4：安全基準
> 1. 執行本篇的檢查腳本，記錄結果
> 2. 套用「首次設定六件事」
> 3. **重跑腳本，比對差異**
> 4. `curl -I http://localhost/` —— **Server 標頭變了嗎？**
> 5. 存取 `/icons/`、`/manual/`、`/server-status` → **都是 404 嗎？**
> 6. 建立一個沒有 index 的目錄，存取它 → **會列出檔案嗎？**

---

## 小測驗

Q1. **Apache 與 Nginx 在架構上的根本差異是什麼？各自的優勢在哪**？

Q2. **Debian 系與 RHEL 系的 Apache 有哪六個主要差異**？

Q3. **`sites-available` / `sites-enabled` 的設計有什麼好處與代價**？

Q4. **`a2enmod` 之後為什麼通常要 `restart` 而不是 `reload`**？

Q5. **`apachectl -S` 中的 `default server` 是怎麼決定的？會造成什麼問題**？

Q6. **Apache 的哪個指令相當於 `nginx -T`**？

Q7. **預設安裝有哪四個安全問題？各自怎麼修**？

Q8. **`Options` 中哪四個選項有安全風險**？

Q9. **`AllowOverride None` 有哪兩個好處**？

Q10. **看到 `Invalid command 'RewriteEngine'` 該怎麼處理**？

> [!question]- 測驗答案
> **Q1.** **Apache 是「程序／執行緒」架構** ——
> 每個連線分配一個 worker（程序或執行緒），
> **記憶體用量隨連線數線性成長**，高並發時吃記憶體。
> **Nginx 是「事件驅動」架構** ——
> 單一 worker 用 epoll 處理數千條連線，**記憶體用量幾乎不隨連線數變化**。
> **Apache 的優勢**：設定彈性極高（**`.htaccess` 讓開發者能自己改設定**）、
> **模組可動態載入／卸載**、**可以用 `mod_php` 內嵌執行 PHP**。
> **Nginx 的優勢**：**高並發、靜態檔快很多、記憶體效率高**，
> 適合當反向代理與前端。
>
> **Q2.** ①**套件與服務名**：`apache2` vs **`httpd`**；
> ②**設定目錄**：`/etc/apache2/` vs **`/etc/httpd/`**；
> ③**主設定檔**：`apache2.conf` vs **`conf/httpd.conf`**；
> ④**站台設定機制**：`sites-available/` + `a2ensite`
> vs **`conf.d/*.conf`（RHEL 系完全沒有 `a2ensite`）**；
> ⑤**模組管理**：`mods-available/` + `a2enmod`
> vs **`conf.modules.d/*.conf`（手動編輯）**；
> ⑥**執行身分**：`www-data` vs **`apache`**。
> 另外日誌在 `/var/log/apache2/` vs `/var/log/httpd/`，
> 且 RHEL 系有 **SELinux** 這個額外的變因。
>
> **Q3.** **好處**：①「安裝了但沒啟用」與「已啟用」清楚分開；
> ②停用一個站台只要 `a2dissite`，**設定檔還在**，隨時能啟用回來；
> ③**套件升級時 `available` 的檔案會更新，`enabled` 的符號連結不受影響**；
> ④`ls sites-enabled/` 一眼看出目前啟用了什麼。
> **代價**：①**與上游文件、RHEL 系的做法不一致**，換系統時要重新適應；
> ②直接編輯 `sites-enabled/` 裡的檔案**其實是在改 `sites-available/`**
> （因為是符號連結），容易搞混。
>
> **Q4.** 因為 **載入新的動態模組（`.so`）需要 Apache 重新啟動才會生效** ——
> `reload` 只是重新讀取設定檔，不會重新載入共享函式庫。
> `a2enmod` 執行後自己就會提示：
> ```
> To activate the new configuration, you need to run:
>   systemctl restart apache2
> ```
> 而 **`a2ensite`（站台設定）用 `reload` 就夠了**，
> 因為那只是設定檔的變更。
>
> **Q5.** **Apache 的 default server 是「第一個載入的 VirtualHost」，
> 而載入順序是檔名的字母順序** ——
> 這就是為什麼預設站台叫 `000-default.conf`（`000-` 確保排在最前）。
> **會造成的問題**：新增一個站台後（例如 `api.conf`），
> 如果它的檔名排序在最前面，**它就變成了 default server** ——
> **所有找不到對應 `ServerName` 的請求（包含掃描器與直接用 IP 存取）
> 全部連到它**，可能洩漏本不該對外的內容。
> **解法**：建立一個 `000-catch-all.conf`，回傳 404 或直接拒絕。
>
> **Q6.** **`sudo apache2ctl -t -D DUMP_CONFIG`**（Apache 2.4.34+）——
> 輸出所有 `Include` 展開後的完整生效設定。
> 相關的還有：
> ```bash
> sudo apache2ctl -t -D DUMP_VHOSTS     # = apachectl -S
> sudo apache2ctl -t -D DUMP_MODULES    # = apachectl -M
> sudo apache2ctl -t -D DUMP_INCLUDES   # 列出所有被 Include 的檔案
> sudo apache2ctl -t -D DUMP_RUN_CFG    # 執行時的設定（User/Group/PidFile…）
> ```
>
> **Q7.** ①**「Apache2 Default Page」洩漏 OS 版本與目錄結構** →
> `sudo a2dissite 000-default`；
> ②**`Server: Apache/2.4.62 (Ubuntu)` 洩漏版本與發行版** →
> `ServerTokens Prod` + `ServerSignature Off`；
> ③**`/icons/`、`/manual/`、`/server-status` 等預設別名可存取** →
> `a2disconf serve-cgi-bin`、`a2dismod status info`、檢查 `alias.conf`；
> ④**全域 `<Directory />` 若設成 `Require all granted`，
> 整個檔案系統都可能被存取** →
> 全域預設改成 `Require all denied` + `Options None`，再逐一開放需要的目錄。
>
> **Q8.** ①**`Indexes`** —— **開啟目錄列表**，會把目錄下所有檔案列給訪客看，
> **一定要用 `-Indexes` 關掉**；
> ②**`ExecCGI`** —— **允許執行 CGI 腳本**，非必要不要開（等於開了執行入口）；
> ③**`Includes`** —— 啟用 SSI，**可能執行系統指令**
> （若必須用，改成較安全的 `IncludesNOEXEC`）；
> ④**`MultiViews`** —— 內容協商，**可能繞過副檔名的限制**
> （例如請求 `/shell` 可能匹配到 `/shell.php`）。
> 另外 `FollowSymLinks` 可能跟隨符號連結跳出 DocumentRoot，
> 較安全的替代是 `SymLinksIfOwnerMatch`（但有效能代價）。
> **建議**：`Options -Indexes -Includes -ExecCGI -MultiViews +FollowSymLinks`。
>
> **Q9.** ①**效能** —— `AllowOverride` 不是 `None` 時，
> **Apache 在「每一個請求」都要對「路徑上的每一層目錄」執行 `stat()`
> 去尋找 `.htaccess`**，這在深層路徑與高流量下是可觀的開銷；
> ②**安全** —— **開發者無法用 `.htaccess` 覆蓋你在 VirtualHost 中設定的安全規則**
> （例如把 `Options -Indexes` 改回去、放寬 `Require`）。
> **除非應用程式真的依賴 `.htaccess`（WordPress、共享主機環境），
> 否則一律 `AllowOverride None`，把規則直接寫進 VirtualHost。**
>
> **Q10.** 這表示 **提供該指令的模組沒有被載入**。
> 處理步驟：
> ```bash
> # ① 確認模組是否已載入
> apache2ctl -M | grep rewrite
> # ② 啟用模組
> sudo a2enmod rewrite
> # ③ ★ 必須 restart（reload 不夠）
> sudo systemctl restart apache2
> # ④ 重新驗證語法
> sudo apache2ctl configtest
> ```
> 同類的常見錯誤與對應模組：
> `ProxyPass` → `proxy proxy_http proxy_fcgi`；
> `Header` → `headers`；
> `SSLEngine` → `ssl`；
> `ExpiresActive` → `expires`；
> `AddOutputFilterByType DEFLATE` → `deflate`。
> **RHEL 系沒有 `a2enmod`**，要編輯 `/etc/httpd/conf.modules.d/` 中的 `LoadModule`。

---

## 延伸閱讀

- [[02-Apache-VirtualHost設定]] — 下一步：虛擬主機設定
- [[03-Apache-模組與MPM]] — prefork / worker / event 的選擇
- [[04-Apache-htaccess與Rewrite]] — .htaccess 與 mod_rewrite
- [[04-Nginx與Apache選型與共存]] — 兩者並用的架構
- [[01-Nginx-安裝與目錄結構]] — 對照 Nginx 的做法
