---
title: "php.ini 重要參數"
desc: "資源限制、錯誤處理、上傳、session 與安全參數的完整說明"
aliases: [php.ini, memory_limit, upload_max_filesize, error_reporting, session]
tags: [群組/軟體與開發工具, 服務/php, 主題/設定]
category: PHP
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[060-03-01-02-guide-PHP-FPM設定與Pool調校]]"]
updated: 2026-08-28
---

# php.ini 重要參數

> [!abstract] 這篇你會學到
> - 分清 **`PHP_INI_ALL` / `PHP_INI_PERDIR` / `PHP_INI_SYSTEM`** 三種可修改層級
> - 正確設定**資源限制**（記憶體、執行時間、輸入變數）
> - 設定**正式環境的錯誤處理**（不洩漏資訊但保留完整日誌）
> - 讓**檔案上傳**在三層設定下正常運作
> - 設定**安全的 session**（Cookie 屬性、Redis、鎖定問題）
> - 一份可直接使用的**正式環境 `php.ini` 範本**

## 前置知識

- [[060-03-01-01-guide-PHP-安裝與多版本管理]] — 設定檔位置（CLI 與 FPM 分開）
- [[060-03-01-02-guide-PHP-FPM設定與Pool調校]] — pool 的 `php_admin_value[]`

---

## 設定的可修改層級

| 層級 | 意思 | 可在哪裡設定 |
| --- | --- | --- |
| **`PHP_INI_ALL`** | 任何地方 | `php.ini`、pool、`.htaccess`、**`ini_set()`** |
| **`PHP_INI_PERDIR`** | 目錄層級 | `php.ini`、pool、`.htaccess`（**不能 `ini_set()`**） |
| **`PHP_INI_SYSTEM`** | 系統層級 | **只有 `php.ini` 與 pool**（`php_admin_value`） |
| `PHP_INI_USER` | 使用者層級 | 已與 ALL 合併 |

```php
// ★ 查詢某個設定的層級
<?php
$all = ini_get_all();
echo $all['memory_limit']['access'];         // 7 = PHP_INI_ALL
echo $all['upload_max_filesize']['access'];  // 6 = PHP_INI_PERDIR
echo $all['disable_functions']['access'];    // 4 = PHP_INI_SYSTEM
```

> [!danger] 這解釋了很多「為什麼改不了」
> ```
> ini_set('memory_limit', '1G');           ✓ 可以（PHP_INI_ALL）
> ini_set('upload_max_filesize', '100M');  ✗ 無效（PHP_INI_PERDIR）
> ini_set('disable_functions', '');        ✗ 無效（PHP_INI_SYSTEM）★ 這是安全設計
> ```
>
> **也解釋了為什麼安全設定要用 `php_admin_value`**：
> ```ini
> php_value[open_basedir]       = /var/www/app    ; ✗ 可能被繞過
> php_admin_value[open_basedir] = /var/www/app    ; ★ 不能被 ini_set 覆蓋
> ```

---

## 資源限制

```ini
; ═══ 記憶體 ═══
memory_limit = 512M           ; ★ 單一請求的上限（-1 = 無限，★ 不要用）

; ═══ 時間 ═══
max_execution_time = 60       ; ★ 腳本執行秒數（★ CLI 下預設 0 = 無限）
max_input_time = 60           ; 解析輸入資料的時間

; ═══ 輸入 ═══
max_input_vars = 3000         ; ★ GET/POST/COOKIE 的變數總數上限
max_input_nesting_level = 64  ; 陣列巢狀深度
```

> [!warning] `memory_limit` 的三個陷阱
> **陷阱一：設 `-1`（無限）**
> ```
> 一個有 bug 的迴圈 → 吃光整台機器的記憶體 → OOM → 【全部服務掛掉】
> ★ 一定要設一個上限
> ```
>
> **陷阱二：與 `pm.max_children` 的關係被誤解**
> ```
> memory_limit 是【單一請求的上限】，不是 worker 的常駐用量
> → 最壞情況才是 max_children × memory_limit
> → 實務上遠低於此（見 02 篇）
> ```
>
> **陷阱三：CLI 與 FPM 不同**
> ```bash
> $ php -r 'echo ini_get("memory_limit");'      # CLI
> -1                                             # ★ Debian 的 CLI 預設是無限
> $ curl -s 網站/_m.php
> 512M                                           # FPM
> ```
> **`php artisan` 這類長時間執行的指令通常需要更大的 `memory_limit`**：
> ```bash
> $ php -d memory_limit=2G artisan import:large-file
> ```

> [!danger] `max_input_vars` 是「大表單送不出去」的元凶
> ```
> 預設值 1000
>   → 一個有 500 筆資料、每筆 3 個欄位的批次編輯表單 = 1500 個變數
>     → 【超過 1000 的部分【靜默丟失】】
>       → 資料只存了一部分，而且【沒有任何錯誤訊息】
> ```
>
> **症狀**：使用者說「我明明有填，存檔後只剩前面幾筆」。
>
> ```ini
> max_input_vars = 3000        ; ★ 依實際需求調整
> ```
> ```php
> // ★ 應用層偵測
> if (count($_POST, COUNT_RECURSIVE) >= ini_get('max_input_vars')) {
>     abort(400, '表單欄位過多，請分批送出');
> }
> ```

```ini
; ═══ FPM 相關的時間設定關係 ★ ═══
; php.ini
max_execution_time = 60

; pool.conf
request_terminate_timeout = 120s     ; ★ 要比 max_execution_time 大

; Nginx
fastcgi_read_timeout 90s;            ; ★ 介於兩者之間

; 順序：max_execution_time < fastcgi_read_timeout < request_terminate_timeout
;   → 讓 PHP 有機會自己先逾時（可以記錄較好的錯誤訊息）
```

---

## 錯誤處理

```ini
; ═══════════ 正式環境 ═══════════
display_errors = Off              ; ★★ 絕不能開
display_startup_errors = Off      ; ★★
log_errors = On                   ; ★ 一定要開
error_log = /var/log/php/fpm-error.log
error_reporting = E_ALL & ~E_DEPRECATED & ~E_STRICT
log_errors_max_len = 4096
ignore_repeated_errors = On       ; 相同錯誤不重複記錄
ignore_repeated_source = Off
html_errors = Off                 ; ★ 日誌中不要 HTML 標籤

; ═══════════ 開發環境 ═══════════
; display_errors = On
; display_startup_errors = On
; error_reporting = E_ALL
; html_errors = On
```

> [!danger] `display_errors = On` 在正式環境是嚴重的資訊洩漏
> ```
> 一個 SQL 錯誤會顯示：
>   SQLSTATE[42S02]: Base table or view not found:
>   1146 Table 'myapp_prod.users_old' doesn't exist
>   (SQL: select * from `users_old` where `email` = 'test@x.com')
>   in /var/www/app/releases/20260828-100000/app/Http/Controllers/UserController.php:45
>
> → 洩漏了：
>   · 【資料庫名稱與資料表結構】
>   · 【完整的檔案系統路徑與部署方式】
>   · 【框架版本】（從堆疊追蹤）
>   · 【SQL 語句】（可據此構造注入）
> ```
>
> ```bash
> # ★ 從外部驗證
> $ curl -s 'https://網站/api/x?id=%27' | head -20
> # ★ 不應該看到任何路徑、SQL 或堆疊追蹤
>
> # 檢查設定
> $ echo '<?php echo ini_get("display_errors") ?: "Off";' > public/_e.php
> $ curl -s https://網站/_e.php
> ```
>
> **同時要確認應用框架也關閉了 debug**：
> ```ini
> # Laravel .env
> APP_DEBUG=false
> APP_ENV=production
> ```

```bash
# ★ 建立日誌目錄與輪替
$ sudo mkdir -p /var/log/php
$ sudo chown www-data:www-data /var/log/php
$ sudo chmod 750 /var/log/php

$ sudo tee /etc/logrotate.d/php >/dev/null <<'EOF'
/var/log/php/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        systemctl reload php8.3-fpm > /dev/null 2>&1 || true
    endscript
}
EOF
```

### 錯誤等級對照

| 常數 | 意義 |
| --- | --- |
| `E_ERROR` | 致命錯誤（腳本中止） |
| `E_WARNING` | 警告（繼續執行） |
| `E_NOTICE` | 通知（例如用了未定義的變數） |
| **`E_DEPRECATED`** | **已棄用的功能**（升級 PHP 版本時會爆量） |
| `E_STRICT` | 建議的寫法 |
| `E_ALL` | **全部** |

```ini
; 正式環境（★ 排除升級時的雜訊，但保留真正的錯誤）
error_reporting = E_ALL & ~E_DEPRECATED & ~E_STRICT

; ★ 升級 PHP 版本時暫時打開，找出需要修的地方
; error_reporting = E_ALL
```

```bash
# ★ 升級 PHP 前先看有多少 Deprecated
$ sudo grep -c 'Deprecated' /var/log/php/fpm-error.log
$ sudo grep 'Deprecated' /var/log/php/fpm-error.log | \
    sed 's/.*Deprecated: //; s/ in \/.*//' | sort | uniq -c | sort -rn | head -20
```

---

## 檔案上傳

```ini
file_uploads = On
upload_max_filesize = 50M     ; ★ 單一檔案的上限
post_max_size = 64M           ; ★★ 要比 upload_max_filesize 大
max_file_uploads = 20         ; 一次最多幾個檔案
upload_tmp_dir = /var/www/app/shared/tmp    ; ★ 每個站台獨立
```

> [!danger] 三層設定必須一致 ★★
> ```
> ① Web 伺服器
>    Nginx ：client_max_body_size 50m;
>    Apache：LimitRequestBody 52428800
>
> ② PHP
>    upload_max_filesize = 50M
>    post_max_size = 64M          ★ 要比 upload 大（因為還有其他表單欄位）
>    max_execution_time = 300     （大檔案需要更久）
>
> ③ 應用程式
>    Laravel：'max:51200'（KB）
> ```
>
> **各層不足的症狀完全不同**：
> | 哪一層不足 | 症狀 |
> | --- | --- |
> | **Web 伺服器** | **413 Request Entity Too Large** |
> | **PHP `upload_max_filesize`** | **上傳「成功」但 `$_FILES['x']['error']` = 1**（★ 最難察覺） |
> | **PHP `post_max_size`** | **`$_POST` 與 `$_FILES` 都是空的**（★★ 最詭異） |
> | 應用程式 | 422 驗證失敗 |

```php
// ★ 應用層的完整檢查
<?php
if ($_SERVER['REQUEST_METHOD'] === 'POST' && empty($_POST) && empty($_FILES)
    && (int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 0) {
    // ★ post_max_size 被超過的典型症狀
    $max = ini_get('post_max_size');
    abort(413, "上傳資料超過伺服器限制（{$max}）");
}

// 檢查每個上傳的錯誤碼
foreach ($_FILES as $name => $f) {
    switch ($f['error']) {
        case UPLOAD_ERR_OK:        break;
        case UPLOAD_ERR_INI_SIZE:  abort(413, '超過 upload_max_filesize');
        case UPLOAD_ERR_FORM_SIZE: abort(413, '超過表單的 MAX_FILE_SIZE');
        case UPLOAD_ERR_PARTIAL:   abort(400, '檔案只上傳了一部分');
        case UPLOAD_ERR_NO_TMP_DIR: abort(500, '暫存目錄不存在');   // ★ upload_tmp_dir
        case UPLOAD_ERR_CANT_WRITE: abort(500, '無法寫入暫存目錄'); // ★ 權限
        case UPLOAD_ERR_EXTENSION: abort(500, '某個 PHP 擴充阻止了上傳');
    }
}
```

```bash
#!/usr/bin/env bash
# 檢查上傳設定的三層一致性
echo "═══ 上傳限制檢查 ═══"

to_bytes() {
    local v="${1//[[:space:]]/}"
    local n="${v%[KMGkmg]}" u="${v: -1}"
    case "${u,,}" in
        k) echo $(( n * 1024 )) ;;
        m) echo $(( n * 1024 * 1024 )) ;;
        g) echo $(( n * 1024 * 1024 * 1024 )) ;;
        *) echo "${v}" ;;
    esac
}

# Web 伺服器
if command -v nginx >/dev/null; then
    NGINX=$(sudo nginx -T 2>/dev/null | grep -oP 'client_max_body_size\s+\K\S+' | tr -d ';' | head -1)
    echo "  Nginx client_max_body_size : ${NGINX:-1m（預設）}"
    NB=$(to_bytes "${NGINX:-1m}")
fi
if command -v apache2ctl >/dev/null; then
    APACHE=$(sudo apache2ctl -t -D DUMP_CONFIG 2>/dev/null | grep -oP 'LimitRequestBody\s+\K\d+' | head -1)
    echo "  Apache LimitRequestBody    : ${APACHE:-0（無限）}"
fi

# PHP（★ 從網頁看，不是 CLI）
echo '<?php
echo "upload_max_filesize=", ini_get("upload_max_filesize"), "\n";
echo "post_max_size=", ini_get("post_max_size"), "\n";
echo "max_file_uploads=", ini_get("max_file_uploads"), "\n";
echo "max_execution_time=", ini_get("max_execution_time"), "\n";
echo "upload_tmp_dir=", ini_get("upload_tmp_dir") ?: sys_get_temp_dir(), "\n";
echo "memory_limit=", ini_get("memory_limit"), "\n";
' | sudo tee /var/www/html/_up.php >/dev/null 2>&1

if OUT=$(curl -s -m 5 http://127.0.0.1/_up.php 2>/dev/null) && [ -n "$OUT" ]; then
    echo "$OUT" | sed 's/^/  PHP(FPM) /'
    UMF=$(echo "$OUT" | grep -oP 'upload_max_filesize=\K\S+')
    PMS=$(echo "$OUT" | grep -oP 'post_max_size=\K\S+')
    UB=$(to_bytes "$UMF"); PB=$(to_bytes "$PMS")
    echo
    [ "$PB" -gt "$UB" ] && echo "  ✓ post_max_size > upload_max_filesize" \
                        || echo "  ⚠⚠ post_max_size 應該【大於】 upload_max_filesize"
    [ -n "${NB:-}" ] && {
        [ "$NB" -ge "$UB" ] && echo "  ✓ Nginx 限制 ≥ PHP 限制" \
                            || echo "  ⚠⚠ Nginx 的 client_max_body_size 太小（會先 413）"
    }
    TMP=$(echo "$OUT" | grep -oP 'upload_tmp_dir=\K\S+')
    [ -d "$TMP" ] && echo "  ✓ upload_tmp_dir 存在：$TMP" \
                  || echo "  ⚠⚠ upload_tmp_dir 不存在：$TMP"
else
    echo "  ⚠ 無法從網頁取得 PHP 設定"
fi
sudo rm -f /var/www/html/_up.php

echo
echo "  ★ 建議：Nginx ≥ post_max_size > upload_max_filesize"
```

---

## Session

```ini
; ═══ 儲存 ═══
session.save_handler = files
session.save_path = /var/lib/php/sessions/app     ; ★ 每個站台獨立
session.gc_maxlifetime = 7200                      ; ★ session 存活秒數
session.gc_probability = 1
session.gc_divisor = 100                           ; 1% 的機率執行垃圾回收

; ═══ ★★ Cookie 安全 ═══
session.cookie_httponly = 1        ; ★ JS 讀不到（防 XSS 竊取）
session.cookie_secure = 1          ; ★ 只在 HTTPS 送出
session.cookie_samesite = Lax      ; ★ 防 CSRF（Strict 更嚴但可能影響使用性）
session.cookie_lifetime = 0        ; 0 = 關閉瀏覽器就失效
session.use_strict_mode = 1        ; ★★ 防 session fixation
session.use_only_cookies = 1       ; ★ 不接受 URL 中的 session id
session.use_trans_sid = 0          ; ★ 不在 URL 中傳遞

; ═══ ID 安全性 ═══
session.sid_length = 48            ; ★ 更長的 session ID
session.sid_bits_per_character = 6
session.name = APPSESSID           ; ★ 改掉預設的 PHPSESSID（減少指紋）
```

> [!danger] `session.use_strict_mode = 1` 防的是 Session Fixation
> ```
> 攻擊流程（沒有 strict_mode 時）：
>   ① 攻擊者訪問網站，取得（或自己編一個）session ID：ABC123
>   ② 誘騙受害者點擊 https://網站/?PHPSESSID=ABC123
>      （或用 XSS 設定 Cookie）
>   ③ 受害者【用這個 ID】登入
>   ④ 攻擊者用同一個 ID → 【直接取得已登入的 session】
>
> use_strict_mode = 1：
>   → PHP 【拒絕使用未經伺服器產生的 session ID】
>     → 會產生一個新的
> ```
>
> **應用層也要在登入後重新產生 ID**：
> ```php
> // 登入成功後
> session_regenerate_id(true);      // ★ true = 刪除舊的 session 檔
> ```
> Laravel 的 `Auth::login()` 已內建這個行為。

### 改用 Redis（★ 強烈建議）

```ini
session.save_handler = redis
session.save_path = "tcp://127.0.0.1:6379?database=1&auth=你的密碼&timeout=2.5"
```

```bash
$ sudo apt install -y php8.3-redis redis-server
$ sudo systemctl enable --now redis-server
$ sudo systemctl restart php8.3-fpm

# 驗證
$ redis-cli -n 1 KEYS 'PHPREDIS_SESSION*' | head
```

> [!tip] Redis session 解決三個問題
> ```
> ① ★ 【不會鎖定】 —— 檔案型 session 會鎖，導致並行的 AJAX 串列執行
> ② ★ 【多台伺服器共享】 —— 負載平衡時不需要 session 黏著（ip_hash）
> ③ 自動過期 —— 不需要 PHP 的垃圾回收機制
> ```
>
> **檔案型 session 的鎖定問題**：
> ```
> 前端同時發 5 個 AJAX
>   → 每個都 session_start()
>     → 第一個鎖住 session 檔案
>       → 其他 4 個【等待】
>         → 原本 5×100ms 並行 = 100ms
>           變成 5×100ms 串列 = 500ms
> ```
> **在 slowlog 中會看到大量卡在 `session_start()`。**

```bash
# ★ 檔案型 session 的權限與清理
$ sudo mkdir -p /var/lib/php/sessions/app
$ sudo chown app-user:app-user /var/lib/php/sessions/app
$ sudo chmod 700 /var/lib/php/sessions/app       # ★ 只有該站台讀得到

# ★ Debian 系用 cron 清理，不是 PHP 的 gc
$ cat /etc/cron.d/php
09,39 * * * * root [ -x /usr/lib/php/sessionclean ] && \
  ( /usr/lib/php/sessionclean; sleep $(( RANDOM \% 60 )); )

# ★ 若用自訂的 save_path，這個 cron 不會清 → 要自己處理
$ sudo tee /etc/cron.d/php-session-clean >/dev/null <<'EOF'
15,45 * * * * root find /var/lib/php/sessions/app -type f -name 'sess_*' -mmin +120 -delete
EOF
```

---

## 安全參數

```ini
; ═══ ★★ 最重要的四個 ═══
cgi.fix_pathinfo = 0          ; ★★ 防 PathInfo 攻擊（上傳的 jpg 被當 PHP 執行）
allow_url_include = Off       ; ★★ 防遠端檔案包含（RFI）
expose_php = Off              ; ★ 不在標頭洩漏 PHP 版本
display_errors = Off          ; ★ 不顯示錯誤給使用者

; ═══ 檔案存取 ═══
allow_url_fopen = On          ; ★ 多數框架需要（Composer、HTTP client）
open_basedir = /var/www/app/current:/var/www/app/shared:/tmp:/usr/share/php
                              ; ★ 建議在 pool 用 php_admin_value 設定

; ═══ 停用危險函式 ═══
disable_functions = exec,passthru,shell_exec,system,proc_open,popen,pcntl_exec,pcntl_fork,dl,putenv,proc_nice,proc_terminate,proc_get_status,pcntl_signal,pcntl_alarm

; ═══ 其他 ═══
enable_dl = Off               ; 不允許執行時載入擴充
max_input_nesting_level = 64
zend.exception_ignore_args = On   ; ★ 例外的堆疊追蹤不含參數值（防洩漏密碼）
zend.exception_string_param_max_len = 0

; ═══ 時區與編碼 ═══
date.timezone = Asia/Taipei   ; ★ 一定要設（否則有警告且時間可能錯）
default_charset = UTF-8
mbstring.internal_encoding = UTF-8
```

> [!danger] `disable_functions` 的取捨
> ```
> 停用太多 → 應用程式壞掉
> 停用太少 → web shell 能為所欲為
>
> ★ 一定要停用（正常應用不會用到）：
>   exec, passthru, shell_exec, system, proc_open, popen,
>   pcntl_exec, pcntl_fork, dl, putenv
>
> ★ 視情況（某些工具會用）：
>   symlink, link, chgrp, chown          （某些部署工具）
>   escapeshellarg, escapeshellcmd        （通常保留）
>
> ✗ 【不要】停用（會壞掉）：
>   file_get_contents, fopen, fwrite       （框架大量使用）
>   base64_decode, eval                    （eval 是語言結構，停不掉）
>   phpinfo                                （停了也不能用，但沒必要）
> ```
>
> **測試方式**：
> ```bash
> # 停用後跑完整的測試套件
> $ php artisan test
> $ composer install --dry-run
> ```
> **常見會壞掉的**：Laravel 的 `Process` facade（需要 `proc_open`）、
> 某些備份套件（需要 `exec` 呼叫 `mysqldump`）。
> **這種情況應該給那個 pool 單獨放寬，而不是全域放寬。**

> [!warning] `zend.exception_ignore_args = On` 很重要
> ```php
> // 沒有這個設定時，例外的堆疊追蹤會包含【參數的實際值】
> #0 /app/Auth.php(45): login('admin', 'P@ssw0rd123')
> //                                    ^^^^^^^^^^^^ ★ 密碼被寫進日誌！
> ```
> ```ini
> zend.exception_ignore_args = On
> ```
> ```
> #0 /app/Auth.php(45): login()
> ```

---

## 完整實戰範例

### 正式環境的 php.ini 範本

```ini
; ═══════════════════════════════════════════════════════════
; /etc/php/8.3/fpm/conf.d/99-production.ini
; 正式環境設定（★ 這個檔案會覆蓋 php.ini 的同名設定）
; ═══════════════════════════════════════════════════════════

; ══════════ 資源限制 ══════════
memory_limit = 512M
max_execution_time = 60
max_input_time = 60
max_input_vars = 3000
max_input_nesting_level = 64

; ══════════ 錯誤處理 ══════════
display_errors = Off
display_startup_errors = Off
log_errors = On
error_log = /var/log/php/fpm-error.log
error_reporting = E_ALL & ~E_DEPRECATED & ~E_STRICT
log_errors_max_len = 4096
ignore_repeated_errors = On
html_errors = Off
zend.exception_ignore_args = On
zend.exception_string_param_max_len = 0

; ══════════ 上傳 ══════════
file_uploads = On
upload_max_filesize = 50M
post_max_size = 64M
max_file_uploads = 20

; ══════════ Session ══════════
session.save_handler = redis
session.save_path = "tcp://127.0.0.1:6379?database=1"
session.gc_maxlifetime = 7200
session.cookie_httponly = 1
session.cookie_secure = 1
session.cookie_samesite = Lax
session.cookie_lifetime = 0
session.use_strict_mode = 1
session.use_only_cookies = 1
session.use_trans_sid = 0
session.sid_length = 48
session.sid_bits_per_character = 6
session.name = APPSESSID

; ══════════ 安全 ══════════
cgi.fix_pathinfo = 0
allow_url_fopen = On
allow_url_include = Off
expose_php = Off
enable_dl = Off
disable_functions = exec,passthru,shell_exec,system,proc_open,popen,pcntl_exec,pcntl_fork,dl,putenv,proc_nice,proc_terminate

; ══════════ 時區與編碼 ══════════
date.timezone = Asia/Taipei
default_charset = UTF-8
mbstring.internal_encoding = UTF-8
mbstring.http_output = UTF-8

; ══════════ OPcache（見 05 篇）══════════
opcache.enable = 1
opcache.enable_cli = 0
opcache.memory_consumption = 256
opcache.interned_strings_buffer = 32
opcache.max_accelerated_files = 20000
opcache.validate_timestamps = 0        ; ★ 正式環境；部署後要 reload FPM
opcache.save_comments = 1              ; ★ 某些框架需要（annotation）
opcache.jit = tracing
opcache.jit_buffer_size = 128M

; ══════════ Realpath 快取 ══════════
realpath_cache_size = 4096K
realpath_cache_ttl = 600

; ══════════ 其他 ══════════
serialize_precision = -1
precision = 14
output_buffering = 4096
implicit_flush = Off
```

```bash
$ sudo systemctl restart php8.3-fpm
$ sudo php-fpm8.3 -t
```

### 設定驗證腳本

```bash
#!/usr/bin/env bash
# /usr/local/bin/php-ini-audit —— php.ini 稽核（★ 從網頁檢查，不是 CLI）
D="${1:-127.0.0.1}"
SCHEME="${2:-http}"
FAIL=0; WARN=0
pass() { printf '  \033[32m✓\033[0m %-30s %s\n' "$1" "$2"; }
warn() { printf '  \033[33m⚠\033[0m %-30s %s\n' "$1" "$2"; WARN=$((WARN+1)); }
fail() { printf '  \033[31m✗\033[0m %-30s %s\n' "$1" "$2"; FAIL=$((FAIL+1)); }

# ★ 建立檢查腳本
DOC=$(sudo nginx -T 2>/dev/null | grep -oP '^\s*root\s+\K\S+' | tr -d ';' | head -1)
DOC="${DOC:-/var/www/html}"
cat > /tmp/_audit.php <<'EOF'
<?php
$keys = [
  'memory_limit','max_execution_time','max_input_vars','max_input_time',
  'display_errors','display_startup_errors','log_errors','error_log','error_reporting',
  'upload_max_filesize','post_max_size','max_file_uploads','upload_tmp_dir','file_uploads',
  'session.save_handler','session.save_path','session.cookie_httponly','session.cookie_secure',
  'session.cookie_samesite','session.use_strict_mode','session.use_only_cookies','session.name',
  'session.gc_maxlifetime',
  'cgi.fix_pathinfo','allow_url_fopen','allow_url_include','expose_php','enable_dl',
  'open_basedir','disable_functions','zend.exception_ignore_args',
  'date.timezone','default_charset',
  'opcache.enable','opcache.validate_timestamps','opcache.memory_consumption',
  'opcache.max_accelerated_files','opcache.enable_cli',
  'realpath_cache_size',
];
foreach ($keys as $k) echo "$k=", var_export(ini_get($k), true), "\n";
echo "PHP_VERSION=", PHP_VERSION, "\n";
echo "SAPI=", php_sapi_name(), "\n";
echo "EXT=", implode(',', get_loaded_extensions()), "\n";
EOF
sudo cp /tmp/_audit.php "$DOC/_audit.php" 2>/dev/null

OUT=$(curl -sk -m 10 "$SCHEME://$D/_audit.php" 2>/dev/null)
sudo rm -f "$DOC/_audit.php" /tmp/_audit.php
[ -z "$OUT" ] && { echo "✗ 無法取得設定，請確認 $DOC 可寫且網站可存取"; exit 1; }

g() { echo "$OUT" | grep -oP "^$1=\K.*" | tr -d "'" ; }

echo "═══════ php.ini 稽核 ═══════"
echo "  PHP $(g PHP_VERSION)  SAPI=$(g SAPI)"

echo -e "\n【★★ 安全（最重要）】"
[ "$(g cgi.fix_pathinfo)" = "0" ] || [ -z "$(g cgi.fix_pathinfo)" ] \
  && pass "cgi.fix_pathinfo" "0" || fail "cgi.fix_pathinfo" "$(g cgi.fix_pathinfo)【必須是 0】"
[ "$(g allow_url_include)" = "" ] || [ "$(g allow_url_include)" = "0" ] \
  && pass "allow_url_include" "Off" || fail "allow_url_include" "【必須 Off】"
[ "$(g display_errors)" = "" ] || [ "$(g display_errors)" = "0" ] \
  && pass "display_errors" "Off" || fail "display_errors" "$(g display_errors)【必須 Off】"
[ "$(g expose_php)" = "" ] || [ "$(g expose_php)" = "0" ] \
  && pass "expose_php" "Off" || warn "expose_php" "建議 Off"
[ -n "$(g open_basedir)" ] && pass "open_basedir" "$(g open_basedir | cut -c1-50)..." \
  || warn "open_basedir" "未設定（建議在 pool 設定）"
[ -n "$(g disable_functions)" ] && pass "disable_functions" "$(g disable_functions | cut -c1-50)..." \
  || fail "disable_functions" "未設定"
echo "$(g disable_functions)" | grep -q 'shell_exec' && pass "  └ shell_exec" "已停用" \
  || fail "  └ shell_exec" "★ 未停用"
[ "$(g zend.exception_ignore_args)" = "1" ] && pass "exception_ignore_args" "On" \
  || warn "exception_ignore_args" "建議 On（防止密碼寫進日誌）"

echo -e "\n【錯誤處理】"
[ "$(g log_errors)" = "1" ] && pass "log_errors" "On" || fail "log_errors" "應為 On"
EL=$(g error_log); [ -n "$EL" ] && pass "error_log" "$EL" || warn "error_log" "未設定"
echo "  ○ error_reporting                $(g error_reporting)"

echo -e "\n【資源限制】"
for k in memory_limit max_execution_time max_input_vars; do
    echo "  ○ $(printf '%-30s' "$k") $(g "$k")"
done
[ "$(g memory_limit)" = "-1" ] && fail "memory_limit" "-1【無限，危險】"
[ "$(g max_input_vars)" -lt 1000 ] 2>/dev/null && warn "max_input_vars" "偏小，大表單可能靜默丟失欄位"

echo -e "\n【上傳】"
UMF=$(g upload_max_filesize); PMS=$(g post_max_size)
echo "  ○ upload_max_filesize            $UMF"
echo "  ○ post_max_size                  $PMS"
python3 -c "
import sys,re
def b(v):
    m=re.match(r'(\d+)([KMGkmg]?)',v or '0')
    n=int(m.group(1)); u=m.group(2).upper()
    return n*{'':1,'K':1024,'M':1048576,'G':1073741824}[u]
sys.exit(0 if b('$PMS')>b('$UMF') else 1)
" 2>/dev/null && pass "post > upload" "✓" || warn "post_max_size" "應該大於 upload_max_filesize"
TMP=$(g upload_tmp_dir)
[ -n "$TMP" ] && { [ -d "$TMP" ] && pass "upload_tmp_dir" "$TMP" || fail "upload_tmp_dir" "$TMP 不存在"; }

echo -e "\n【Session】"
for k in session.save_handler session.save_path session.name session.gc_maxlifetime; do
    echo "  ○ $(printf '%-30s' "$k") $(g "$k" | cut -c1-45)"
done
[ "$(g session.cookie_httponly)" = "1" ] && pass "cookie_httponly" "On" || fail "cookie_httponly" "★ 必須 On"
[ "$(g session.cookie_secure)" = "1" ]   && pass "cookie_secure" "On"   || warn "cookie_secure" "HTTPS 站台應設 On"
[ -n "$(g session.cookie_samesite)" ]    && pass "cookie_samesite" "$(g session.cookie_samesite)" \
                                         || warn "cookie_samesite" "建議 Lax"
[ "$(g session.use_strict_mode)" = "1" ] && pass "use_strict_mode" "On（防 session fixation）" \
                                         || fail "use_strict_mode" "★ 必須 On"
[ "$(g session.save_handler)" = "redis" ] && pass "save_handler" "redis（★ 不會鎖定）" \
                                          || warn "save_handler" "files（★ 會鎖定，建議改 Redis）"

echo -e "\n【OPcache】"
[ "$(g opcache.enable)" = "1" ] && pass "opcache.enable" "On" || fail "opcache.enable" "★ 應該啟用"
[ "$(g opcache.validate_timestamps)" = "" ] || [ "$(g opcache.validate_timestamps)" = "0" ] \
  && pass "validate_timestamps" "Off（正式環境，★ 部署後要 reload）" \
  || warn "validate_timestamps" "On（開發環境設定）"
echo "  ○ memory_consumption             $(g opcache.memory_consumption) MB"
echo "  ○ max_accelerated_files          $(g opcache.max_accelerated_files)"

echo -e "\n【其他】"
[ -n "$(g date.timezone)" ] && pass "date.timezone" "$(g date.timezone)" || fail "date.timezone" "未設定"
echo "$(g EXT)" | grep -qi xdebug && fail "Xdebug" "★★ 正式環境不應安裝（慢 2-5 倍）" \
                                 || pass "Xdebug" "未安裝"

echo -e "\n【從外部驗證】"
curl -skI -m 5 "$SCHEME://$D/" | grep -qi 'x-powered-by' \
  && fail "X-Powered-By" "★ 有洩漏（expose_php）" || pass "X-Powered-By" "無"

echo -e "\n═══════ 結果 ═══════"
printf '  失敗 \033[31m%d\033[0m 項，警告 \033[33m%d\033[0m 項\n' "$FAIL" "$WARN"
exit $FAIL
```

---

## 常見錯誤與排錯

| 現象／錯誤 | 原因 | 解法 |
| --- | --- | --- |
| **`ini_set()` 沒作用** | 該設定是 `PHP_INI_PERDIR` 或 `PHP_INI_SYSTEM` | 改 `php.ini` 或 pool 設定 |
| **改了 `php.ini` 沒生效** ★ | 改到 CLI 的 / 沒重啟 FPM / 被 pool 覆蓋 | 見 [[060-03-01-01-guide-PHP-安裝與多版本管理]] |
| **大表單只存了一部分** ★★ | **`max_input_vars` 太小（靜默丟失）** | 調大到 3000+；應用層偵測 |
| **`$_POST` 與 `$_FILES` 都是空的** ★★ | **`post_max_size` 被超過** | 調大；應用層用 `CONTENT_LENGTH` 偵測 |
| 上傳「成功」但檔案不見 | `upload_max_filesize` 太小 | 檢查 `$_FILES['x']['error']` |
| **413 Request Entity Too Large** | Web 伺服器的限制 | Nginx `client_max_body_size` |
| `UPLOAD_ERR_CANT_WRITE` | `upload_tmp_dir` 權限 | `chown` 給 pool 的 user |
| **正式環境洩漏 SQL 與路徑** ★★ | `display_errors = On` | **設成 Off**；`APP_DEBUG=false` |
| **例外日誌含明文密碼** ★ | 沒設 `zend.exception_ignore_args` | 設成 `On` |
| **AJAX 請求變成串列** ★ | **檔案型 session 鎖定** | 改 Redis；或 `session_write_close()` |
| session 隨機遺失 | 多站台共用 save_path 但權限不同 | 每個 pool 獨立 `session.save_path` |
| session 過早失效 | `gc_maxlifetime` 太小；或被其他站台的 gc 清掉 | 調大；獨立 save_path |
| **Session Fixation 漏洞** | 沒設 `use_strict_mode` | 設成 1；登入後 `session_regenerate_id(true)` |
| `Deprecated` 訊息爆量 | 升級 PHP 後 | `error_reporting = E_ALL & ~E_DEPRECATED`；逐步修正程式碼 |
| **時間錯誤／時區警告** | 沒設 `date.timezone` | `date.timezone = Asia/Taipei` |
| 停用函式後應用壞掉 | `disable_functions` 太嚴 | 找出哪個函式；**只對該 pool 放寬** |

### 排查流程

```bash
# 【1】★ 從網頁確認實際生效的值（不是 CLI）
$ echo '<?php echo ini_get("要查的設定");' > /var/www/html/_v.php
$ curl -s http://127.0.0.1/_v.php
$ rm /var/www/html/_v.php

# 【2】★ 這個設定是在哪裡被設的
$ grep -rn 'max_input_vars' /etc/php/8.3/fpm/
/etc/php/8.3/fpm/php.ini:max_input_vars = 1000
/etc/php/8.3/fpm/conf.d/99-production.ini:max_input_vars = 3000
/etc/php/8.3/fpm/pool.d/app.conf:php_admin_value[max_input_vars] = 5000   ★ 最優先

# 【3】設定的可修改層級
$ php -r '$a = ini_get_all(); print_r($a["upload_max_filesize"]);'
Array ( [global_value] => 2M [local_value] => 50M [access] => 6 )
#                                                  ^^^^^^^^^^ 6 = PHP_INI_PERDIR

# 【4】錯誤日誌
$ sudo tail -50 /var/log/php/fpm-error.log
$ sudo tail -50 /var/log/php8.3-fpm.log

# 【5】上傳問題的完整診斷
$ echo '<?php
if ($_SERVER["REQUEST_METHOD"] === "POST") {
    echo "CONTENT_LENGTH: ", $_SERVER["CONTENT_LENGTH"] ?? "-", "\n";
    echo "post_max_size: ", ini_get("post_max_size"), "\n";
    echo "upload_max_filesize: ", ini_get("upload_max_filesize"), "\n";
    echo "\$_POST 數量: ", count($_POST), "\n";
    echo "\$_FILES: "; print_r($_FILES);
}' > /var/www/html/_upt.php
$ curl -F 'f=@bigfile.zip' http://127.0.0.1/_upt.php
```

---

## 安全性注意事項

> [!danger] 正式環境必須設定的八項
> ```ini
> ① cgi.fix_pathinfo = 0                    ★★ 防 PathInfo 攻擊
> ② allow_url_include = Off                 ★★ 防 RFI
> ③ display_errors = Off                    ★★ 防資訊洩漏
> ④ expose_php = Off                        ★ 防指紋
> ⑤ disable_functions = exec,shell_exec,... ★ 限制 web shell 能力
> ⑥ open_basedir = ...                      ★ 限制檔案存取（在 pool 設）
> ⑦ session.use_strict_mode = 1             ★ 防 session fixation
> ⑧ zend.exception_ignore_args = On         ★ 防密碼寫進日誌
> ```
>
> 加上 session cookie 三件套：
> ```ini
> session.cookie_httponly = 1
> session.cookie_secure = 1
> session.cookie_samesite = Lax
> ```

> [!warning] `session.save_path` 的權限問題
> ```bash
> # ❌ 預設：所有站台共用 /var/lib/php/sessions，權限 1733（sticky）
> $ ls -ld /var/lib/php/sessions
> drwx-wx-wt 2 root root 4096 /var/lib/php/sessions
> #      ^^^ 其他人可寫但不可讀（sticky bit）
>
> # ★ 問題：某些設定下，站台 A 的 PHP 可以列出並讀取站台 B 的 session 檔
> #   → 取得別的站台的登入 session
> ```
>
> ```bash
> # ✅ 每個 pool 獨立且權限 700
> $ sudo mkdir -p /var/lib/php/sessions/{app,shop}
> $ sudo chown app-user:app-user   /var/lib/php/sessions/app
> $ sudo chown shop-user:shop-user /var/lib/php/sessions/shop
> $ sudo chmod 700 /var/lib/php/sessions/{app,shop}
> ```
> ```ini
> ; pool.d/app.conf
> php_admin_value[session.save_path] = /var/lib/php/sessions/app
> ```
> **或直接改用 Redis（不同 database 或不同 prefix）。**

> [!tip] `open_basedir` 要包含的路徑
> ```ini
> php_admin_value[open_basedir] = \
>     /var/www/app/current:\            ; 程式碼
>     /var/www/app/shared:\             ; .env、storage
>     /tmp:\                            ; ★ 暫存
>     /usr/share/php:\                  ; ★ PEAR / 共用函式庫
>     /var/lib/php/sessions/app:\       ; ★ session
>     /usr/share/zoneinfo               ; 時區資料
> ```
> **漏掉任何一個都會造成「應用程式莫名其妙出錯」**，
> 而且錯誤訊息通常是
> `open_basedir restriction in effect. File(/tmp/xxx) is not within the allowed path(s)`。
>
> **注意**：`open_basedir` **不能防止 `exec()` 執行外部指令** ——
> 那要靠 `disable_functions`。兩者要一起用。

---

## 速查表

### 可修改層級

```
PHP_INI_ALL      任何地方（含 ini_set）      memory_limit
PHP_INI_PERDIR   php.ini/pool/.htaccess     upload_max_filesize
PHP_INI_SYSTEM   只有 php.ini/pool          disable_functions ★ 安全設計

★ 安全設定用 php_admin_value[]（不能被 ini_set 覆蓋）
```

### 正式環境必設八項 ★

```ini
cgi.fix_pathinfo = 0                    ; ★★ 防 PathInfo 攻擊
allow_url_include = Off                 ; ★★ 防 RFI
display_errors = Off                    ; ★★ 防資訊洩漏
expose_php = Off
disable_functions = exec,passthru,shell_exec,system,proc_open,popen,pcntl_exec,dl,putenv
open_basedir = /var/www/app/current:/var/www/app/shared:/tmp:/usr/share/php
session.use_strict_mode = 1             ; ★ 防 session fixation
zend.exception_ignore_args = On         ; ★ 防密碼寫進日誌
```

### 資源限制

```ini
memory_limit = 512M          ; ★ 不要設 -1
max_execution_time = 60
max_input_vars = 3000        ; ★ 預設 1000，大表單會【靜默丟失欄位】
```

```
時間設定的順序：
max_execution_time(60) < fastcgi_read_timeout(90) < request_terminate_timeout(120)
```

### 上傳三層一致 ★

```
Nginx  client_max_body_size 50m;
PHP    upload_max_filesize = 50M
       post_max_size = 64M          ★ 要比 upload 大
應用    Laravel 'max:51200'

★ 建議：Nginx ≥ post_max_size > upload_max_filesize
```

| 哪層不足 | 症狀 |
| --- | --- |
| Web 伺服器 | **413** |
| `upload_max_filesize` | `$_FILES['x']['error']` = 1 |
| **`post_max_size`** | **`$_POST` 與 `$_FILES` 都是空的** |

### Session 安全

```ini
session.cookie_httponly = 1      ; ★ JS 讀不到
session.cookie_secure = 1        ; ★ 只在 HTTPS
session.cookie_samesite = Lax    ; ★ 防 CSRF
session.use_strict_mode = 1      ; ★★ 防 session fixation
session.use_only_cookies = 1
session.sid_length = 48
session.name = APPSESSID         ; 改掉預設值

; ★ 強烈建議改 Redis
session.save_handler = redis
session.save_path = "tcp://127.0.0.1:6379?database=1"
```

```
Redis session 解決三件事：
① 不會鎖定（檔案型會讓並行 AJAX 串列化）
② 多台伺服器共享（不需要 ip_hash）
③ 自動過期

★ 登入後要 session_regenerate_id(true)
```

### 錯誤處理

```ini
display_errors = Off             ; ★★ 正式環境
log_errors = On
error_log = /var/log/php/fpm-error.log
error_reporting = E_ALL & ~E_DEPRECATED & ~E_STRICT
html_errors = Off
zend.exception_ignore_args = On  ; ★ 堆疊追蹤不含參數值
```

### 排查

```bash
# ★ 從【網頁】確認實際值（不是 CLI）
echo '<?php echo ini_get("X");' > /var/www/html/_v.php && curl -s http://127.0.0.1/_v.php

# ★ 設定在哪被設的
grep -rn 'max_input_vars' /etc/php/8.3/fpm/

# 可修改層級
php -r '$a=ini_get_all(); print_r($a["upload_max_filesize"]);'
# access: 1=USER 2=PERDIR 4=SYSTEM 7=ALL

sudo tail -50 /var/log/php/fpm-error.log
```

---

## 練習題

> [!question]- 練習 1：可修改層級實驗
> 1. 寫一個腳本嘗試 `ini_set()` 三種層級的設定：
>    ```php
>    var_dump(ini_set('memory_limit', '1G'));           // ALL
>    var_dump(ini_set('upload_max_filesize', '100M'));  // PERDIR
>    var_dump(ini_set('disable_functions', ''));        // SYSTEM
>    ```
> 2. **哪些回傳 `false`？為什麼？**
> 3. 用 `ini_get_all()` 查詢每個設定的 `access` 值
> 4. **這對安全設定的意義是什麼？**

> [!question]- 練習 2：`max_input_vars` 的靜默丟失
> 1. 把 `max_input_vars` 設成 `100`
> 2. 建立一個有 200 個欄位的表單
> 3. 送出後 `count($_POST)` 是多少？
> 4. **有任何錯誤訊息嗎？**（看 error log）
> 5. 調大到 3000，重測
> 6. 寫一個應用層的偵測機制

> [!question]- 練習 3：上傳的四種失敗
> 逐一重現並記錄症狀：
> 1. Nginx 的 `client_max_body_size` 太小
> 2. `upload_max_filesize` 太小
> 3. **`post_max_size` 太小**（★ 觀察 `$_POST` 與 `$_FILES`）
> 4. `upload_tmp_dir` 不存在或無寫入權限
>
> **每一種的錯誤訊息、`$_FILES['x']['error']` 值各是什麼？**
> 寫一個能正確區分四種情況的錯誤處理。

> [!question]- 練習 4：Session 鎖定實測
> 1. 用檔案型 session，建立一個 `session_start(); sleep(2);` 的端點
> 2. 用同一個瀏覽器**同時發 5 個 AJAX 到這個端點**
> 3. **總共花了多久？**（應該是 10 秒而非 2 秒）
> 4. 加上 `session_write_close()` 在 sleep 之前 → 重測
> 5. 改用 Redis session → 重測
> 6. **記錄三種情況的時間差異**

> [!question]- 練習 5：完整稽核
> 1. 執行 `php-ini-audit` 腳本
> 2. **逐項修正所有失敗與警告**
> 3. 重跑直到 0 失敗
> 4. 特別驗證：
>    - `curl -sI https://網站/ | grep -i x-powered-by` → 沒有
>    - 觸發一個錯誤 → 頁面上看不到任何路徑或 SQL
>    - `curl https://網站/uploads/x.jpg/y.php` → 404
> 5. 把腳本排程化

---

## 小測驗

Q1. **`PHP_INI_ALL` / `PHP_INI_PERDIR` / `PHP_INI_SYSTEM` 的差別是什麼？對安全設定的意義**？

Q2. **`memory_limit` 設 `-1` 有什麼風險？它與 `pm.max_children` 的關係常被怎麼誤解**？

Q3. **`max_input_vars` 太小會造成什麼？為什麼特別難察覺**？

Q4. **`max_execution_time`、`fastcgi_read_timeout`、`request_terminate_timeout` 該怎麼排序？為什麼**？

Q5. **`display_errors = On` 在正式環境會洩漏哪四類資訊**？

Q6. **上傳失敗時，Web 伺服器 / `upload_max_filesize` / `post_max_size` 三者不足的症狀各是什麼**？

Q7. **`session.use_strict_mode = 1` 防的是什麼攻擊？攻擊流程是什麼**？

Q8. **Redis session 相對檔案型 session 解決了哪三個問題**？

Q9. **`zend.exception_ignore_args = On` 為什麼重要**？

Q10. **`open_basedir` 需要包含哪些常被遺漏的路徑？它能防止 `exec()` 嗎**？

> [!question]- 測驗答案
> **Q1.** **`PHP_INI_ALL`**：可以在任何地方修改，**包含程式中的 `ini_set()`**
> （例如 `memory_limit`）。
> **`PHP_INI_PERDIR`**：只能在 `php.ini`、FPM pool、`.htaccess` 中設定，
> **不能用 `ini_set()`**（例如 `upload_max_filesize`）。
> **`PHP_INI_SYSTEM`**：**只能在 `php.ini` 與 FPM pool 中設定**
> （例如 `disable_functions`、`open_basedir`）。
> **對安全設定的意義**：把安全相關的設定設計成 `PHP_INI_SYSTEM`，
> **就是為了讓應用程式（或被注入的惡意程式碼）無法用 `ini_set()` 解除限制**。
> 同理，在 pool 中要用 **`php_admin_value[]`** 而非 `php_value[]`，
> 因為前者不能被覆蓋。
>
> **Q2.** **設 `-1`（無限）的風險**：一個有 bug 的迴圈或載入超大檔案，
> **會吃光整台機器的記憶體 → OOM killer → 所有服務掛掉**。
> 一定要設一個上限。
> **常被誤解的關係**：以為
> 「`pm.max_children` × `memory_limit` = 需要的記憶體」
> 所以把 `max_children` 設得極保守。
> 實際上 **`memory_limit` 是「單一請求可用的上限」，不是 worker 的常駐用量** ——
> 只有極少數請求會接近它，典型的 worker RSS 只有 40-80MB。
> 應該用**實際的 RSS** 來算 `max_children`（見 [[060-03-01-02-guide-PHP-FPM設定與Pool調校]]）。
>
> **Q3.** `max_input_vars`（預設 **1000**）限制 GET/POST/COOKIE 的變數總數。
> 超過的部分**會被靜默丟棄** ——
> 例如一個有 500 筆資料、每筆 3 個欄位的批次編輯表單 = 1500 個變數，
> **只有前 1000 個會進到 `$_POST`**。
> **特別難察覺的原因**：
> **沒有任何錯誤訊息、沒有例外、HTTP 狀態碼是 200**，
> 使用者只會說「我明明有填，存檔後只剩前面幾筆」，
> 而開發者在小資料量下永遠重現不了。
> 解法：調大到 3000+，並在應用層偵測：
> ```php
> if (count($_POST, COUNT_RECURSIVE) >= ini_get('max_input_vars')) { ... }
> ```
>
> **Q4.** 順序應該是：
> **`max_execution_time`(60) < `fastcgi_read_timeout`(90) < `request_terminate_timeout`(120)**。
> **原因**：**讓 PHP 有機會自己先觸發逾時** ——
> PHP 自己逾時會拋出可捕捉的錯誤，**可以記錄完整的堆疊追蹤與較好的錯誤訊息**；
> 而 `request_terminate_timeout` 是 FPM 直接 kill 掉 worker，
> 什麼都留不下（只有 FPM 日誌的一行 `execution timed out`）。
> Nginx 的 `fastcgi_read_timeout` 介於中間，
> 確保 Nginx 不會比 PHP 更早放棄（否則使用者看到 504 但 PHP 還在跑）。
>
> **Q5.** ①**資料庫名稱與資料表結構**（`myapp_prod.users_old`）；
> ②**完整的檔案系統路徑與部署方式**
> （`/var/www/app/releases/20260828-100000/...` 洩漏了用符號連結部署）；
> ③**框架與套件版本**（從堆疊追蹤中的 vendor 路徑）；
> ④**SQL 語句**（攻擊者可據此構造更精準的注入）。
> 驗證：`curl -s "https://網站/api/x?id=%27"` 不應看到任何路徑、SQL 或堆疊。
> 同時要確認 `APP_DEBUG=false`。
>
> **Q6.** **Web 伺服器不足**（Nginx `client_max_body_size`）：
> **413 Request Entity Too Large**，請求根本沒到 PHP。
> **`upload_max_filesize` 不足**：
> **上傳「成功」（HTTP 200），但 `$_FILES['x']['error']` = `UPLOAD_ERR_INI_SIZE`(1)**，
> 檔案不存在 —— **最難察覺，因為程式若沒檢查 error 就會以為成功**。
> **`post_max_size` 不足**：
> **`$_POST` 與 `$_FILES` 「都是空的」** —— 最詭異，
> 因為連表單的其他欄位也不見了。
> 偵測方式：`REQUEST_METHOD` 是 POST、`$_POST` 空、
> 但 `$_SERVER['CONTENT_LENGTH']` > 0。
>
> **Q7.** 防的是 **Session Fixation（會話固定）攻擊**。
> **流程**：
> ①攻擊者訪問網站取得（或自己編一個）session ID：`ABC123`；
> ②**誘騙受害者使用這個 ID**（`https://網站/?PHPSESSID=ABC123`，或用 XSS 設 Cookie）；
> ③**受害者用這個 ID 登入**，伺服器把登入狀態綁到 `ABC123`；
> ④**攻擊者用同一個 ID 存取 → 直接取得已登入的 session**。
> **`use_strict_mode = 1` 讓 PHP 拒絕使用「未經伺服器產生」的 session ID**，
> 會改產生一個新的。
> 應用層也要在**登入成功後呼叫 `session_regenerate_id(true)`**
> （Laravel 的 `Auth::login()` 已內建）。
>
> **Q8.** ①**★ 不會鎖定** —— 檔案型 session 在 `session_start()` 時會鎖定檔案，
> 直到腳本結束才釋放，**導致同一使用者的並行 AJAX 串列執行**
> （5 個各 100ms 的請求變成 500ms）；
> ②**★ 多台伺服器共享** —— 負載平衡時不需要 session 黏著（`ip_hash`），
> 可以自由用 `least_conn`，節點增減也不影響使用者；
> ③**自動過期** —— Redis 的 TTL 機制取代 PHP 的垃圾回收，
> 不需要 cron 清理，也不會有「被其他站台的 gc 清掉」的問題。
> 另外還順帶解決了 session 檔案的權限隔離問題。
>
> **Q9.** 因為**沒有這個設定時，PHP 例外的堆疊追蹤會包含函式呼叫的「參數實際值」**：
> ```
> #0 /app/Auth.php(45): login('admin', 'P@ssw0rd123')
> #1 /app/Db.php(88): connect('localhost', 'root', 'db_secret_pw')
> ```
> **明文密碼、API 金鑰、個資都會被寫進錯誤日誌**，
> 而錯誤日誌的權限通常沒有像 `.env` 那樣嚴格保護，
> 也常常會被送到中央日誌系統、監控平台（Sentry）。
> ```ini
> zend.exception_ignore_args = On
> zend.exception_string_param_max_len = 0
> ```
> 設定後堆疊追蹤只顯示 `login()`，不含參數。
>
> **Q10.** **常被遺漏的路徑**：
> **`/tmp`**（暫存檔、上傳暫存）、
> **`/usr/share/php`**（PEAR 與共用函式庫）、
> **session 的 `save_path`**、
> **`upload_tmp_dir`**、
> `/usr/share/zoneinfo`（時區資料）。
> 漏掉會出現 `open_basedir restriction in effect. File(...) is not within the allowed path(s)`。
> **`open_basedir` 不能防止 `exec()`** ——
> 它只限制 **PHP 的檔案系統函式**（`fopen`、`include`、`file_get_contents` 等），
> **攻擊者仍可以用 `exec('cat /etc/passwd')` 繞過**。
> 所以 **`open_basedir` 必須與 `disable_functions` 一起用**：
> ```ini
> php_admin_value[open_basedir] = /var/www/app:/tmp:/usr/share/php
> php_admin_value[disable_functions] = exec,passthru,shell_exec,system,proc_open,popen
> ```

---

## 延伸閱讀

- [[060-03-01-05-guide-PHP-OPcache與效能]] — OPcache 的完整設定
- [[060-03-01-06-guide-PHP-安全設定]] — open_basedir 與 disable_functions 的深入說明
- [[060-03-01-02-guide-PHP-FPM設定與Pool調校]] — pool 的 php_admin_value
- [[060-03-01-01-guide-PHP-安裝與多版本管理]] — 設定檔位置
- [[060-03-01-04-guide-Composer-套件管理]] — 相依套件
