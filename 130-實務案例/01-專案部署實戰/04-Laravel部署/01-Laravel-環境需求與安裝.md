---
title: "Laravel 環境需求與安裝"
desc: "PHP 擴充、Composer、MySQL 與 Redis 的準備，以及從 GitHub 專案首次部署"
aliases: [Laravel環境, PHP擴充, composer install, .env, APP_KEY]
tags: [群組/實務案例, 主題/部署, 主題/Laravel, 主題/LXMP]
category: 專案部署實戰
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[01-部署共通觀念]]", "[[01-PHP-安裝與多版本管理]]"]
updated: 2026-08-28
---

# Laravel 環境需求與安裝

> [!abstract] 這篇你會學到
> - Laravel 11/12 的**完整環境需求**
> - **PHP 擴充**的安裝與驗證
> - **Composer** 的正式環境用法
> - **MySQL / Redis** 的準備
> - **★★ 從 GitHub 專案首次部署**的完整流程
> - **`.env` 的產生**與 `APP_KEY`
> - **環境檢查腳本**

## 前置知識

- [[01-部署共通觀念]] — releases/current 佈局
- [[01-PHP-安裝與多版本管理]] — PHP 的安裝
- [[01-MySQL-安裝與初始化]] — MySQL 的準備

---

## 環境需求 ★★

| 元件 | 版本 | 說明 |
| --- | --- | --- |
| **PHP** | **8.2+**（Laravel 11）／**8.2+**（Laravel 12） | ★★ 建議 8.3 |
| Composer | 2.x | ★ 不要用 1.x |
| **MySQL** | **8.0+** | 或 MariaDB 10.11+ / PostgreSQL 13+ |
| Redis | 6+ | ★ 快取、佇列、session |
| Node.js | 20+ | ★ 只在**建置**時需要（Vite） |
| Nginx | 1.24+ | 或 Apache 2.4 |

```bash
# ═══ ★★ 一次檢查所有版本 ═══
$ php -v && composer -V && mysql --version && redis-server -v && node -v && nginx -v
PHP 8.3.14 (cli) (built: ...)
Composer version 2.8.3
mysql  Ver 8.4.3 for Linux
Redis server v=7.4.1
v22.12.0
nginx version: nginx/1.27.3
```

### ★★★ PHP 擴充

```bash
# ═══ Laravel 必要的擴充 ═══
$ sudo apt update
$ sudo apt install -y \
    php8.3-fpm php8.3-cli \
    php8.3-mysql \
    php8.3-mbstring \
    php8.3-xml \
    php8.3-curl \
    php8.3-zip \
    php8.3-bcmath \
    php8.3-gd \
    php8.3-intl \
    php8.3-redis \
    php8.3-opcache \
    php8.3-soap        # ★ 若要串接 SOAP 服務

# ★★ 驗證
$ php -m | sort | tr '\n' ' '
bcmath calendar Core ctype curl date dom exif FFI fileinfo filter ftp gd
hash iconv intl json libxml mbstring mysqli mysqlnd openssl pcntl pcre PDO
pdo_mysql Phar posix readline redis Reflection session SimpleXML sodium SPL
sqlite3 standard tokenizer xml xmlreader xmlwriter Zend OPcache zip zlib
```

```bash
#!/usr/bin/env bash
# /usr/local/bin/check-laravel-ext —— ★★ 檢查 Laravel 需要的擴充
REQUIRED=(
  bcmath ctype curl dom fileinfo filter hash mbstring openssl pcre
  pdo pdo_mysql session tokenizer xml json
)
RECOMMENDED=( redis opcache gd intl zip exif sodium )

echo "═══ Laravel PHP 擴充檢查 ═══"
echo "  PHP $(php -r 'echo PHP_VERSION;')"

MISSING=0
echo -e "\n【必要】"
for e in "${REQUIRED[@]}"; do
    printf '  %-14s ' "$e"
    php -m | grep -qix "$e" && echo "✓" || { echo "✗✗ 缺少"; MISSING=$((MISSING+1)); }
done

echo -e "\n【建議】"
for e in "${RECOMMENDED[@]}"; do
    printf '  %-14s ' "$e"
    php -m | grep -qix "$e" && echo "✓" || echo "⚠ 建議安裝"
done

echo -e "\n【重要設定】"
for k in memory_limit max_execution_time upload_max_filesize post_max_size \
         opcache.enable opcache.validate_timestamps date.timezone; do
    printf '  %-30s %s\n' "$k" "$(php -r "echo ini_get('$k') ?: '(未設定)';")"
done

echo -e "\n【★★ FPM 與 CLI 的差異】"
echo "  ★ php.ini 是分開的："
printf '    CLI : %s\n' "$(php -r 'echo php_ini_loaded_file();')"
printf '    FPM : %s\n' "/etc/php/$(php -r 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION;')/fpm/php.ini"

[ "$MISSING" -eq 0 ] && echo -e "\n  ✓ 必要擴充齊全" || \
  { echo -e "\n  ✗✗ 缺少 $MISSING 個必要擴充"; exit 1; }
```

> [!danger] CLI 與 FPM 的 `php.ini` 是分開的 ★★★
> ```
> /etc/php/8.3/cli/php.ini      ← ★ php artisan、composer 用這個
> /etc/php/8.3/fpm/php.ini      ← ★★ 網頁請求用這個
>
> ★★★ 常見的困惑：
>   · php -m 看得到某個擴充，但網頁報「Class not found」
>     → ★ 那個擴充只在 CLI 啟用了
>   · CLI 的 memory_limit 是 -1，網頁卻 OOM
>     → ★ FPM 的設定不同
>
> ★★ 驗證 FPM 實際載入的設定：
>   建一個 phpinfo.php（★ 看完立刻刪除）
>   或用：sudo -u www-data php-fpm8.3 -tt
>   或：php-fpm8.3 -i | grep memory_limit
> ```

```bash
# ★★ 比較 CLI 與 FPM 的設定
$ diff <(php -i | grep -E '^(memory_limit|max_execution_time|opcache)' | sort) \
       <(php-fpm8.3 -i 2>/dev/null | grep -E '^(memory_limit|max_execution_time|opcache)' | sort)

# ★ 或用一個臨時的端點
$ echo '<?php phpinfo();' | sudo tee /var/www/app/current/public/_info.php
$ curl -s https://app.example.gov.tw/_info.php | grep -oE 'memory_limit</td><td[^>]*>[^<]*'
$ sudo rm /var/www/app/current/public/_info.php     # ★★★ 立刻刪除
```

### Composer

```bash
# ═══ ★★ 安裝（驗證雜湊）═══
$ EXPECTED=$(curl -sS https://composer.github.io/installer.sig)
$ php -r "copy('https://getcomposer.org/installer', '/tmp/composer-setup.php');"
$ ACTUAL=$(php -r "echo hash_file('sha384', '/tmp/composer-setup.php');")
$ [ "$EXPECTED" = "$ACTUAL" ] && echo "✓ 雜湊相符" || { echo "✗✗ 雜湊不符，中止"; exit 1; }
$ sudo php /tmp/composer-setup.php --install-dir=/usr/local/bin --filename=composer
$ rm /tmp/composer-setup.php
$ composer -V

# ═══ ★ 正式環境的設定 ═══
$ composer config -g process-timeout 600      # ★ 大專案可能要久一點
$ composer config -g cache-dir /var/cache/composer
$ sudo mkdir -p /var/cache/composer && sudo chown deploy /var/cache/composer
```

> [!danger] 正式環境的 `composer install` 參數 ★★★
> ```bash
> composer install \
>   --no-dev \                    # ★★★ 不安裝開發相依（PHPUnit、Faker…）
>   --optimize-autoloader \       # ★★ 產生 classmap（★ 大幅加速）
>   --no-interaction \            # ★ 不互動（自動化必須）
>   --prefer-dist \               # ★ 用壓縮檔而非 git clone（快很多）
>   --no-progress                 # ★ 日誌乾淨
>
> ★★★ --no-dev 的重要性：
>   開發相依裡有 Faker、PHPUnit、Ignition（★ 除錯頁面）
>   → 裝在正式環境 = ★★ 多餘的攻擊面
>   → ★ Ignition 曾有 RCE 漏洞（CVE-2021-3129）
>
> ★★ --optimize-autoloader：
>   把 PSR-4 的動態查找改成 classmap
>   → ★ 每次 autoload 少一次檔案系統查找
>   → 大專案可以快 20~30%
>
> ★ 更激進：--classmap-authoritative
>   → 完全不做檔案系統查找（★ 但動態產生的類別會失敗）
> ```

```bash
# ★ 用 composer.lock 確保版本一致
$ composer install --no-dev --optimize-autoloader   # ★★ 依 lock 檔
$ composer update                                   # ★★★ 【不要】在正式環境跑！

# ★ 檢查有沒有已知的弱點
$ composer audit
$ composer audit --format=json | jq '.advisories | length'
```

---

## 資料庫準備

```sql
-- ═══ ★★ MySQL ═══
CREATE DATABASE appdb
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;        -- ★★ 一定要 utf8mb4（支援 emoji 與完整中文）

-- ★★ 建立專用使用者（★ 不要用 root）
CREATE USER 'appuser'@'localhost' IDENTIFIED BY '強密碼';

-- ★★ 最小權限（★ 不要 GRANT ALL）
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON appdb.* TO 'appuser'@'localhost';
-- ★ CREATE/ALTER/DROP/INDEX 是 migration 需要的
-- ★★ 若不想給，可以用另一個「migration 專用」的帳號

FLUSH PRIVILEGES;

-- ★ 驗證
SHOW GRANTS FOR 'appuser'@'localhost';
```

> [!danger] `utf8` 不是真正的 UTF-8 ★★★
> ```
> MySQL 的 utf8 = utf8mb3（★ 每個字元最多 3 bytes）
>   → ★★ 存不下 emoji 與部分罕用字
>     → 「Incorrect string value: '\xF0\x9F\x98\x80'」
>       → ★ 資料被截斷或整筆寫入失敗
>
> ★★★ 一定要用 utf8mb4：
>   CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
>
> ★ Laravel 的 config/database.php 預設就是 utf8mb4，
>   但【資料庫本身】也要是 utf8mb4
>
> ★ 檢查既有的資料庫：
>   SELECT SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME
>     FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='appdb';
>   SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES
>     WHERE TABLE_SCHEMA='appdb';
> ```

```bash
# ★★ 修正既有的資料庫
$ mysql -u root -p <<'SQL'
ALTER DATABASE appdb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
SQL

# ★ 逐表轉換（★ 大表會鎖很久，先評估）
$ mysql -u root -pN -e "SELECT CONCAT('ALTER TABLE \`', TABLE_NAME,
    '\` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;')
    FROM information_schema.TABLES WHERE TABLE_SCHEMA='appdb';" | \
  mysql -u root -p appdb
```

```bash
# ═══ Redis ═══
$ sudo apt install -y redis-server
$ sudo sed -i 's/^# requirepass .*/requirepass 強密碼/' /etc/redis/redis.conf
$ sudo sed -i 's/^bind .*/bind 127.0.0.1 ::1/' /etc/redis/redis.conf      # ★★ 只聽本機
$ sudo sed -i 's/^# maxmemory .*/maxmemory 512mb/' /etc/redis/redis.conf
$ sudo sed -i 's/^# maxmemory-policy .*/maxmemory-policy allkeys-lru/' /etc/redis/redis.conf
$ sudo systemctl restart redis-server
$ redis-cli -a '強密碼' ping
PONG
```

> [!danger] Redis 一定要設密碼與綁定本機 ★★★
> ```
> ★★★ Redis 預設【沒有密碼】且【可能綁在 0.0.0.0】
>   → 網路上有大量被入侵的 Redis
>     → 攻擊者可以：
>       · 讀取所有 session（★ 直接偽造登入）
>       · CONFIG SET dir / dbfilename → ★★ 【寫檔案到任意位置】
>         → 寫 SSH 授權金鑰、寫 webshell、寫 cron
>
> ★★ 必要設定：
>   bind 127.0.0.1 ::1
>   requirepass 強密碼
>   ★ rename-command CONFIG ""        （★ 停用危險指令）
>   ★ rename-command FLUSHALL ""
>
> ★ 驗證：
>   ss -tlnp | grep 6379    → 必須是 127.0.0.1
>   從外部：nc -zv 伺服器IP 6379 → 應該 refused
> ```

---

## ★★ 從 GitHub 首次部署

```bash
#!/usr/bin/env bash
# /usr/local/bin/laravel-first-deploy —— Laravel 專案首次部署
set -euo pipefail

APP="${APP:-/var/www/api}"
REPO="${REPO:-git@github.com:Information-Study/laravel-api.git}"
BRANCH="${BRANCH:-main}"
DOMAIN="${DOMAIN:-api.example.gov.tw}"
DB_NAME="${DB_NAME:-appdb}"
DB_USER="${DB_USER:-appuser}"
PHP_V="${PHP_V:-8.3}"

c(){ echo -e "\033[36m[$(date +%T)]\033[0m $*"; }
die(){ echo -e "\033[31m✗ $*\033[0m" >&2; exit 1; }

c "═══════ Laravel 首次部署 ═══════"
c "  專案根目錄：$APP"
c "  Repo      ：$REPO"
c "  網域      ：$DOMAIN"

# ══ 【1】環境檢查 ══
c "\n【1】環境檢查"
/usr/local/bin/check-laravel-ext || die "PHP 擴充不齊全"
command -v composer >/dev/null || die "找不到 composer"

# ══ 【2】建立目錄結構 ══
c "\n【2】建立目錄結構"
sudo mkdir -p "$APP"/{releases,shared/storage/{app/public,framework/{cache/data,sessions,views},logs}}
sudo chown -R deploy:www-data "$APP"
sudo chmod -R 770 "$APP/shared/storage"
sudo find "$APP/shared/storage" -type d -exec chmod g+s {} \;
tree -L 3 "$APP" 2>/dev/null | sed 's/^/    /' || ls -R "$APP" | head -20

# ══ 【3】clone ══
c "\n【3】clone"
REL="$APP/releases/$(date +%Y%m%d-%H%M%S)"
sudo -u deploy git clone --depth 1 --branch "$BRANCH" --single-branch "$REPO" "$REL" 2>&1 | sed 's/^/    /'
COMMIT=$(cd "$REL" && git rev-parse --short HEAD)
c "    $COMMIT"
sudo rm -rf "$REL/.git"

# ══ 【4】★★ 產生 .env ══
c "\n【4】★★ 產生 .env"
if [ ! -f "$APP/shared/.env" ]; then
    sudo -u deploy cp "$REL/.env.example" "$APP/shared/.env"

    read -rsp "  資料庫密碼：" DB_PASS; echo
    read -rsp "  Redis 密碼：" REDIS_PASS; echo

    sudo -u deploy tee "$APP/shared/.env" >/dev/null <<EOF
APP_NAME="機關管理系統"
APP_ENV=production
APP_KEY=
APP_DEBUG=false
APP_URL=https://$DOMAIN
APP_TIMEZONE=Asia/Taipei
APP_LOCALE=zh_TW
APP_FALLBACK_LOCALE=en
APP_FAKER_LOCALE=zh_TW

# ★★ 日誌
LOG_CHANNEL=daily
LOG_STACK=daily
LOG_LEVEL=warning
LOG_DAILY_DAYS=14

# ★★ 資料庫
DB_CONNECTION=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE=$DB_NAME
DB_USERNAME=$DB_USER
DB_PASSWORD=$DB_PASS

# ★★ session / 快取 / 佇列（★ 用 Redis）
SESSION_DRIVER=redis
SESSION_LIFETIME=120
SESSION_ENCRYPT=false
SESSION_SECURE_COOKIE=true
SESSION_SAME_SITE=lax
SESSION_DOMAIN=.example.gov.tw

CACHE_STORE=redis
CACHE_PREFIX=app_cache

QUEUE_CONNECTION=redis

REDIS_CLIENT=phpredis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=$REDIS_PASS
REDIS_DB=0
REDIS_CACHE_DB=1

# ★ 檔案系統
FILESYSTEM_DISK=local

# ★ Sanctum（★ 前後端分離時）
SANCTUM_STATEFUL_DOMAINS=$DOMAIN,app.example.gov.tw

# ★★ 廣播與郵件（★ 本手冊不含郵件伺服器，用外部 SMTP 或 log）
BROADCAST_CONNECTION=log
MAIL_MAILER=log

# ★ Vite
VITE_APP_NAME="\${APP_NAME}"
EOF
    sudo chmod 640 "$APP/shared/.env"
    sudo chown deploy:www-data "$APP/shared/.env"
    c "    ✓ 已產生"
else
    c "    ✓ 已存在，跳過"
fi

# ══ 【5】連結 shared ══
c "\n【5】連結 shared"
sudo -u deploy ln -sfn "$APP/shared/.env" "$REL/.env"
sudo rm -rf "$REL/storage"
sudo -u deploy ln -sfn "$APP/shared/storage" "$REL/storage"

# ══ 【6】composer ══
c "\n【6】composer install"
cd "$REL"
sudo -u deploy COMPOSER_MEMORY_LIMIT=-1 composer install \
    --no-dev --optimize-autoloader --no-interaction --prefer-dist --no-progress \
    2>&1 | tail -6 | sed 's/^/    /'

# ══ 【7】★★★ APP_KEY ══
c "\n【7】★★★ APP_KEY"
if ! grep -q '^APP_KEY=base64:' "$APP/shared/.env"; then
    sudo -u deploy php artisan key:generate --force
    c "    ✓ 已產生"
    c "    ★★★ 請【立刻備份】這把金鑰："
    grep '^APP_KEY=' "$APP/shared/.env" | sed 's/^/      /'
else
    c "    ✓ 已存在"
fi

# ══ 【8】前端建置 ══
if [ -f "$REL/package.json" ]; then
    c "\n【8】前端建置"
    sudo -u deploy npm ci --no-audit --no-fund 2>&1 | tail -3 | sed 's/^/    /'
    sudo -u deploy npm run build 2>&1 | tail -6 | sed 's/^/    /'
    sudo rm -rf "$REL/node_modules"
fi

# ══ 【9】★★ 資料庫遷移 ══
c "\n【9】★★ 資料庫遷移"
sudo -u deploy php artisan migrate:status 2>&1 | tail -10 | sed 's/^/    /' || true
read -rp "  執行 migrate？(yes/no) " a
if [ "$a" = yes ]; then
    sudo -u deploy php artisan migrate --force 2>&1 | sed 's/^/    /'
fi

# ══ 【10】Laravel 最佳化 ══
c "\n【10】最佳化"
sudo -u deploy php artisan config:cache
sudo -u deploy php artisan route:cache
sudo -u deploy php artisan view:cache
sudo -u deploy php artisan event:cache 2>/dev/null || true
sudo -u deploy php artisan storage:link 2>/dev/null || true
c "    ✓ 完成"

# ══ 【11】★★ 權限 ══
c "\n【11】★★ 權限"
sudo find "$REL" -type d -exec chmod 750 {} \;
sudo find "$REL" -type f -exec chmod 640 {} \;
sudo chmod 755 "$REL/artisan"
sudo chmod -R 770 "$APP/shared/storage" "$REL/bootstrap/cache"
sudo chown -R deploy:www-data "$REL"
c "    ✓ 完成"

# ══ 【12】★★★ 切換 ══
c "\n【12】★★★ 原子切換"
sudo -u deploy ln -sfn "$REL" "$APP/current.tmp"
sudo -u deploy mv -Tf "$APP/current.tmp" "$APP/current"
c "    → $REL"

# ══ 【13】★★ 驗證 ══
c "\n【13】★★ 驗證"
FAIL=0
v(){ printf '    %-42s ' "$1"; if eval "$2" >/dev/null 2>&1; then echo "✓"; else echo "✗"; FAIL=1; fi; }

v "artisan 可執行"      "sudo -u deploy php '$APP/current/artisan' --version"
v "★★ APP_KEY 已設定"    "grep -q '^APP_KEY=base64:' '$APP/shared/.env'"
v "★★★ APP_DEBUG=false"  "grep -q '^APP_DEBUG=false' '$APP/shared/.env'"
v "★★ APP_ENV=production" "grep -q '^APP_ENV=production' '$APP/shared/.env'"
v "資料庫可連線"        "sudo -u deploy php '$APP/current/artisan' db:show"
v "Redis 可連線"        "sudo -u deploy php '$APP/current/artisan' tinker --execute='Cache::put(\"t\",1,10);'"
v "storage 可寫"        "sudo -u www-data test -w '$APP/shared/storage'"
v "★★ 程式碼不可寫"      "! sudo -u www-data test -w '$APP/current/public/index.php'"
v "設定已快取"          "[ -f '$APP/current/bootstrap/cache/config.php' ]"

sudo -u deploy php "$APP/current/artisan" about 2>/dev/null | head -25 | sed 's/^/    /'

echo
[ "$FAIL" -eq 0 ] && c "═══ ✓ 首次部署完成 ═══" || die "有檢查未通過"

cat <<EOF

★★ 接下來：
  ① 設定 PHP-FPM pool  → [[02-Laravel-Nginx與PHP-FPM設定]]
  ② 設定 Nginx         → 同上
  ③ 簽發並部署憑證     → [[08-用自建CA簽發伺服器憑證]]
  ④ 設定佇列與排程     → [[03-Laravel-佇列排程與Supervisor]]
  ⑤ 執行安全檢查表     → [[07-Laravel-正式環境安全檢查表]]

★★★ 【立刻備份 APP_KEY】：
    $(grep '^APP_KEY=' "$APP/shared/.env")
  → 遺失的話，所有加密欄位與已發出的 session 全部失效
EOF
```

> [!danger] `APP_KEY` 遺失的後果 ★★★
> ```
> APP_KEY 用於：
>   · ★★ 加密 session cookie
>   · ★★★ 加密資料庫中用 encrypted cast 的欄位
>   · 簽署已簽名的 URL（signed routes）
>   · 加密的佇列 payload
>
> ★★★ 遺失或更換的後果：
>   · 所有使用者【立刻被登出】
>   · ★★★ 資料庫中的加密欄位【永久無法解密】（★ 資料等於遺失）
>   · 所有已發出的 signed URL 失效
>   · 佇列中未處理的加密 job 無法解開
>
> ★★ 必須：
>   · 產生後【立刻備份到密碼管理系統】
>   · ★ 與資料庫備份【分開保管】
>     （備份檔外洩時，沒有 key 就解不開加密欄位）
>   · 部署流程中【絕不重新產生】
>     → php artisan key:generate 只在【第一次】執行
> ```

```bash
# ★★ 檢查有沒有用到加密欄位
$ grep -rn "encrypted" app/Models/ | head
protected $casts = ['id_number' => 'encrypted'];
protected $casts = ['bank_account' => 'encrypted:array'];
# ★ 有的話，APP_KEY 的重要性等同於資料庫本身
```

---

## ★★ 環境驗證腳本

```bash
#!/usr/bin/env bash
# /usr/local/bin/laravel-env-check —— Laravel 環境完整檢查
set -uo pipefail
APP="${1:-/var/www/api}"
cd "$APP/current" 2>/dev/null || { echo "找不到 $APP/current"; exit 1; }

PASS=0; FAIL=0
chk(){ printf '  %-46s ' "$1"; if eval "$2" >/dev/null 2>&1; then echo "✓"; PASS=$((PASS+1))
       else echo "✗"; FAIL=$((FAIL+1)); fi; }

echo "═══ Laravel 環境檢查：$APP ═══"

echo -e "\n【1】版本"
php -r 'printf("  PHP        %s\n", PHP_VERSION);'
php artisan --version 2>/dev/null | sed 's/^/  /'
composer -V 2>/dev/null | sed 's/^/  /'

echo -e "\n【2】★★★ 環境設定"
chk "APP_ENV=production"      "php artisan tinker --execute='exit(config(\"app.env\")===\"production\"?0:1);'"
chk "★★★ APP_DEBUG=false"      "php artisan tinker --execute='exit(config(\"app.debug\")?1:0);'"
chk "APP_KEY 已設定"          "php artisan tinker --execute='exit(config(\"app.key\")?0:1);'"
chk "APP_URL 是 https"        "php artisan tinker --execute='exit(str_starts_with(config(\"app.url\"),\"https\")?0:1);'"
chk "時區 Asia/Taipei"        "php artisan tinker --execute='exit(config(\"app.timezone\")===\"Asia/Taipei\"?0:1);'"

echo -e "\n【3】連線"
chk "資料庫"                  "php artisan db:show"
chk "★ 資料庫是 utf8mb4"       "php artisan tinker --execute='exit(str_contains(DB::selectOne(\"SELECT @@character_set_database as c\")->c,\"utf8mb4\")?0:1);'"
chk "Redis 快取"              "php artisan tinker --execute='Cache::put(\"__t\",1,5); exit(Cache::get(\"__t\")===1?0:1);'"
chk "Redis session"           "php artisan tinker --execute='exit(config(\"session.driver\")===\"redis\"?0:1);'"

echo -e "\n【4】★★ 快取狀態"
for f in config routes services packages; do
    printf '  %-46s ' "bootstrap/cache/$f.php"
    [ -f "bootstrap/cache/$f.php" ] && { echo "✓"; PASS=$((PASS+1)); } || \
      { echo "－（★ 正式環境建議快取）"; }
done

echo -e "\n【5】★★ 權限"
chk "storage 可被 www-data 寫" "sudo -u www-data test -w storage"
chk "bootstrap/cache 可寫"     "sudo -u www-data test -w bootstrap/cache"
chk "★★ public/index.php 唯讀"  "! sudo -u www-data test -w public/index.php"
chk "★★ .env 權限 ≤640"        "[ \$(stat -Lc %a .env) -le 640 ]"

echo -e "\n【6】★★ 安全"
chk "★★★ .env 不在 public/"     "[ ! -f public/.env ]"
chk "★ 沒有 .git"              "[ ! -d .git ]"
chk "★ 沒有 node_modules"      "[ ! -d node_modules ]"
chk "★★ 沒有開發相依"          "! composer show --installed 2>/dev/null | grep -qiE '^(phpunit|fakerphp|spatie/laravel-ignition)'"
chk "★ 沒有 .env.example 在 public" "[ ! -f public/.env.example ]"

echo -e "\n【7】★ 弱點"
if composer audit --no-interaction >/dev/null 2>&1; then
    echo "  ✓ composer audit 通過"; PASS=$((PASS+1))
else
    N=$(composer audit --format=json 2>/dev/null | jq '[.advisories[]] | length' 2>/dev/null || echo "?")
    echo "  ⚠ 有 $N 個已知弱點（composer audit）"
fi

echo -e "\n【8】PHP 設定"
for k in memory_limit max_execution_time upload_max_filesize post_max_size \
         opcache.enable opcache.validate_timestamps opcache.memory_consumption; do
    printf '  %-40s %s\n' "$k" "$(php -r "echo ini_get('$k') ?: '-';")"
done

echo -e "\n═══ ✓ $PASS  ✗ $FAIL ═══"
[ "$FAIL" -eq 0 ] || exit 1
```

```bash
$ laravel-env-check /var/www/api
═══ Laravel 環境檢查：/var/www/api ═══

【1】版本
  PHP        8.3.14
  Laravel Framework 11.36.1
  Composer version 2.8.3

【2】★★★ 環境設定
  APP_ENV=production                             ✓
  ★★★ APP_DEBUG=false                            ✓
  APP_KEY 已設定                                 ✓
  APP_URL 是 https                               ✓
  時區 Asia/Taipei                               ✓
...
═══ ✓ 24  ✗ 0 ═══
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`No application encryption key`** ★★ | 沒 `APP_KEY` | `php artisan key:generate --force` |
| **`Class not found`（網頁）但 CLI 可以** ★★★ | 擴充只在 CLI 啟用 | 檢查 **FPM 的 php.ini** |
| **`Incorrect string value: '\xF0\x9F...'`** ★★★ | 資料庫不是 utf8mb4 | `ALTER DATABASE ... utf8mb4` |
| **`SQLSTATE[HY000] [2002] Connection refused`** | DB 沒啟動或 host 錯 | `DB_HOST=127.0.0.1`（不是 `localhost`） |
| **`could not find driver`** ★★ | 缺 `php-mysql` | `apt install php8.3-mysql` |
| `Permission denied` on storage ★★ | 權限 | `chmod -R 770 storage` + `chown :www-data` |
| **`composer install` OOM** ★ | CLI memory_limit | `COMPOSER_MEMORY_LIMIT=-1` |
| **改了 `.env` 沒生效** ★★★ | `config:cache` 快取住了 | `config:clear && config:cache` |
| `The stream or file could not be opened` | log 目錄不可寫 | `chmod 770 storage/logs` |
| **Redis 連不上** | 密碼或 bind | 檢查 `requirepass` 與 `bind` |
| **`Specified key was too long`** ★ | MySQL <5.7 的索引長度 | `Schema::defaultStringLength(191)` |
| 部署後 500 但看不到錯誤 ★★ | `APP_DEBUG=false`（正確） | 看 `storage/logs/laravel.log` |
| **`.env` 可被下載** ★★★ | Nginx 沒擋 | `location ~ /\. { deny all; }` |

### 排查

```bash
APP=/var/www/api

# 【1】★★★ 最先看的：Laravel 的日誌
$ sudo tail -100 "$APP/shared/storage/logs/laravel.log"
$ sudo tail -f "$APP/shared/storage/logs/laravel-$(date +%Y-%m-%d).log"

# 【2】PHP-FPM 的錯誤
$ sudo tail -50 /var/log/php8.3-fpm.log
$ sudo journalctl -u php8.3-fpm -n 50 --no-pager

# 【3】Nginx
$ sudo tail -50 /var/log/nginx/api.error.log

# 【4】★★ 環境資訊
$ cd "$APP/current" && php artisan about
$ php artisan config:show database
$ php artisan config:show app

# 【5】★★ 連線測試
$ php artisan db:show
$ php artisan db:table users
$ php artisan tinker --execute='dd(DB::connection()->getPdo());'
$ redis-cli -a "$REDIS_PASSWORD" ping

# 【6】★★★ CLI vs FPM 的擴充差異
$ php -m > /tmp/cli.txt
$ php-fpm8.3 -m 2>/dev/null > /tmp/fpm.txt
$ diff /tmp/cli.txt /tmp/fpm.txt

# 【7】★★ 快取狀態
$ ls -la bootstrap/cache/
$ php artisan config:clear && php artisan config:cache

# 【8】權限
$ sudo -u www-data test -w storage && echo "可寫" || echo "✗ 不可寫"
$ namei -l "$APP/shared/storage"
```

---

## 安全性注意事項

> [!danger] 首次部署的五個安全要點 ★★★
> ```
> ① ★★★ APP_DEBUG=false
>      → true 時錯誤頁會顯示【完整的 .env】
>
> ② ★★★ .env 權限 640 且不在 public/
>      → curl https://api/.env 必須是 404
>
> ③ ★★★ --no-dev（不安裝開發相依）
>      → Ignition 曾有 RCE 漏洞（CVE-2021-3129）
>      → PHPUnit 的 eval-stdin.php 也曾被利用
>
> ④ ★★ 資料庫使用最小權限的專用帳號
>      → 不要用 root
>      → 只給 SELECT/INSERT/UPDATE/DELETE + migration 需要的
>
> ⑤ ★★★ Redis 設密碼 + 綁 127.0.0.1
>      → 無密碼的 Redis 可以被用來寫檔案（webshell / SSH key）
> ```

```bash
# ★★★ 上線前的快速安全檢查
$ S=https://api.example.gov.tw
$ for p in /.env /.env.example /composer.json /composer.lock \
           /storage/logs/laravel.log /.git/config \
           /vendor/phpunit/phpunit/src/Util/PHP/eval-stdin.php; do
    printf '%-58s ' "$p"
    C=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "$S$p")
    [ "$C" = 404 ] || [ "$C" = 403 ] && echo "✓ ($C)" || echo "✗✗ ($C)"
  done
```

> [!warning] `DB_HOST` 用 `127.0.0.1` 而不是 `localhost` ★
> ```
> ★ PHP 的 MySQL 驅動對 localhost 有特殊處理：
>   DB_HOST=localhost  → ★ 用 【Unix socket】連線
>   DB_HOST=127.0.0.1  → ★ 用 TCP 連線
>
> ★★ 用 localhost 的問題：
>   · socket 路徑可能不對（不同的 MySQL 安裝方式路徑不同）
>   · 容器化時 socket 不存在
>   · ★ 錯誤訊息很難懂：「No such file or directory」
>
> ★ 建議一律用 127.0.0.1（明確且可攜）
>   ★★ 若真的要用 socket（效能略好）：
>     DB_SOCKET=/var/run/mysqld/mysqld.sock
> ```

---

## 速查表

### 環境需求

```
PHP 8.2+（★ 建議 8.3）  Composer 2.x  MySQL 8.0+  Redis 6+  Node 20+（★ 只建置時）
```

### ★★★ 必要的 PHP 擴充

```bash
sudo apt install -y php8.3-{fpm,cli,mysql,mbstring,xml,curl,zip,bcmath,gd,intl,redis,opcache}

# 驗證
check-laravel-ext
```

```
★★★ CLI 與 FPM 的 php.ini 是【分開的】
   /etc/php/8.3/cli/php.ini   ← artisan、composer
   /etc/php/8.3/fpm/php.ini   ← 網頁請求
```

### ★★★ 正式環境的 composer

```bash
composer install --no-dev --optimize-autoloader --no-interaction --prefer-dist

# ★★★ 絕不在正式環境跑
composer update
```

```
--no-dev              ★★★ 不裝 PHPUnit/Faker/Ignition（★ 減少攻擊面）
--optimize-autoloader ★★ classmap，快 20~30%
```

### 資料庫

```sql
CREATE DATABASE appdb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;   -- ★★★
CREATE USER 'appuser'@'localhost' IDENTIFIED BY '強密碼';
GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,INDEX,DROP,REFERENCES ON appdb.* TO 'appuser'@'localhost';
```

```
★★★ utf8 = utf8mb3（存不下 emoji）→ 一定要 utf8mb4
★  DB_HOST 用 127.0.0.1 不要用 localhost
```

### Redis ★★★

```conf
bind 127.0.0.1 ::1          # ★★★ 只聽本機
requirepass 強密碼           # ★★★
maxmemory 512mb
maxmemory-policy allkeys-lru
rename-command CONFIG ""    # ★ 停用危險指令
```

### ★★★ `.env` 關鍵設定

```dotenv
APP_ENV=production
APP_DEBUG=false                  # ★★★
APP_KEY=base64:...               # ★★★ 產生後立刻備份
APP_URL=https://api.example.gov.tw
APP_TIMEZONE=Asia/Taipei

SESSION_DRIVER=redis
SESSION_SECURE_COOKIE=true       # ★★
CACHE_STORE=redis
QUEUE_CONNECTION=redis
DB_HOST=127.0.0.1                # ★ 不用 localhost
LOG_LEVEL=warning
```

### ★★★ `APP_KEY` 的重要性

```
用於：session cookie 加密、encrypted cast 欄位、signed URL、佇列 payload

遺失／更換 →
  · 所有使用者立刻被登出
  · ★★★ 加密欄位【永久無法解密】（資料等於遺失）

★★ 產生後立刻備份，與資料庫備份【分開保管】
★★ 部署流程中【絕不重新產生】
```

### 部署流程

```
① mkdir releases / shared/storage
② git clone --depth 1
③ ln -sfn shared/.env & shared/storage
④ composer install --no-dev --optimize-autoloader
⑤ ★★★ php artisan key:generate（★ 只有第一次）
⑥ npm ci && npm run build
⑦ ★★ php artisan migrate --force（★ 先備份資料庫）
⑧ config:cache route:cache view:cache
⑨ 權限 750/640，storage 與 bootstrap/cache 770
⑩ ★★★ 原子切換
```

### 排查

```bash
tail -f storage/logs/laravel.log          # ★★★ 最先看這個
php artisan about
php artisan db:show
php artisan config:show app
diff <(php -m) <(php-fpm8.3 -m)           # ★★ CLI vs FPM
laravel-env-check /var/www/api
```

---

## 練習題

> [!question]- 練習 1：CLI 與 FPM 的差異 ★★★
> 1. `php -m | grep redis` → 有嗎？
> 2. 用一個 `phpinfo()` 頁面看**網頁端**有沒有 redis
> 3. **故意在 FPM 的 php.ini 停用一個擴充**（`;extension=...`）
> 4. `php artisan tinker` 用得到嗎？網頁呢？
> 5. 比較兩者的 `memory_limit`
> 6. **記下你的排查流程**

> [!question]- 練習 2：`utf8` vs `utf8mb4` ★★★
> 1. 建一個 `CHARACTER SET utf8` 的資料庫
> 2. 建一個表，插入含 emoji 的資料 → **成功嗎？錯誤是什麼？**
> 3. 插入罕用中文字（如 𠀀）→ 結果？
> 4. `ALTER DATABASE ... utf8mb4` 後再試
> 5. **檢查你現有資料庫的每一張表的 collation**

> [!question]- 練習 3：`APP_KEY` 的影響 ★★★
> **★ 在測試環境**
> 1. 建一個有 `encrypted` cast 的欄位，寫入一筆資料
> 2. 登入一個帳號
> 3. **執行 `php artisan key:generate --force`**
> 4. 重新整理頁面 → **還是登入狀態嗎？**
> 5. 讀取那個加密欄位 → **錯誤是什麼？**
> 6. 把舊的 `APP_KEY` 換回去 → 資料回來了嗎？
> 7. **設計你的 APP_KEY 備份策略**

> [!question]- 練習 4：`--no-dev` 的重要性
> 1. `composer install`（**不加 `--no-dev`**）
> 2. `ls vendor/` → **有哪些開發套件？**
> 3. `curl https://api/vendor/phpunit/phpunit/src/Util/PHP/eval-stdin.php` → 存取得到嗎？
> 4. 用 `--no-dev` 重裝
> 5. **比較 `vendor/` 的大小與套件數量**
> 6. Nginx 加上擋 `/vendor/` 的規則

> [!question]- 練習 5：完整的首次部署
> 1. 準備一台乾淨的 VM
> 2. 執行 `laravel-first-deploy`
> 3. **每一步的輸出都看懂**
> 4. 執行 `laravel-env-check` → 有幾項沒過？
> 5. **故意設 `APP_DEBUG=true`** → 觸發一個錯誤 → **看到什麼？**
> 6. 執行上線前的安全檢查 curl 迴圈
> 7. **寫出你們機關的 Laravel 部署 SOP**

---

## 小測驗

Q1. **CLI 與 FPM 的 `php.ini` 是同一個嗎？造成什麼常見困惑**？

Q2. **正式環境的 `composer install` 應該加哪些參數？`--no-dev` 為什麼重要**？

Q3. **MySQL 的 `utf8` 與 `utf8mb4` 差在哪**？

Q4. **`APP_KEY` 用在哪些地方？遺失的後果是什麼**？

Q5. **`DB_HOST` 用 `localhost` 與 `127.0.0.1` 有什麼差別**？

Q6. **Redis 沒設密碼會有什麼風險**？

Q7. **為什麼 `storage` 要放在 `shared` 並用符號連結**？

Q8. **改了 `.env` 但沒生效，最可能的原因是什麼**？

Q9. **正式環境的 `LOG_LEVEL` 該設什麼？為什麼不用 `debug`**？

Q10. **`composer update` 為什麼絕對不能在正式環境執行**？

> [!question]- 測驗答案
> **Q1.** **不是同一個**：
> `/etc/php/8.3/cli/php.ini`（`php artisan`、`composer` 用）與
> `/etc/php/8.3/fpm/php.ini`（**網頁請求用**）是**兩個獨立的檔案**。
> **常見困惑**：
> ①**`php -m` 看得到某個擴充，但網頁報 `Class not found`** ——
> 那個擴充只在 CLI 啟用了；
> ②**CLI 的 `memory_limit` 是 -1（無限），網頁卻 OOM** ——
> FPM 的設定不同；
> ③改了 `php.ini` 重啟 FPM 但 `php artisan` 的行為沒變（或相反）。
> **驗證方法**：`diff <(php -m) <(php-fpm8.3 -m)`，
> 或建一個臨時的 `phpinfo()` 頁面（**看完立刻刪除**）。
>
> **Q2.** ```bash
> composer install --no-dev --optimize-autoloader --no-interaction --prefer-dist
> ```
> **`--no-dev`（最重要）**：不安裝開發相依（PHPUnit、Faker、Ignition、Debugbar）。
> **為什麼重要**：這些套件**在正式環境是多餘的攻擊面** ——
> **Ignition 曾有 RCE 漏洞（CVE-2021-3129，可直接遠端執行程式碼）**，
> PHPUnit 的 `eval-stdin.php` 也長期是掃描器的目標（CVE-2017-9841）。
> **`--optimize-autoloader`**：把 PSR-4 的動態檔案查找改成 **classmap**，
> 每次 autoload 少一次檔案系統操作，**大專案可以快 20～30%**。
> **`--no-interaction`** 自動化必須；**`--prefer-dist`** 用壓縮檔而非 git clone（快很多）。
>
> **Q3.** **MySQL 的 `utf8` 其實是 `utf8mb3` —— 每個字元最多 3 bytes**，
> **存不下需要 4 bytes 的字元**：
> **emoji**（😀）、**部分罕用漢字**（𠀀、𡈽 等擴充區的字）、
> 某些數學符號與古文字。
> **後果**：`Incorrect string value: '\xF0\x9F\x98\x80'` ——
> 依 SQL mode 不同，資料會被**截斷**或**整筆寫入失敗**。
> **`utf8mb4` 才是真正完整的 UTF-8**（每字元最多 4 bytes）。
> **建立資料庫時一定要指定**：
> ```sql
> CREATE DATABASE appdb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
> ```
> Laravel 的 `config/database.php` 預設就是 `utf8mb4`，
> **但資料庫本身也必須是** —— 兩邊都要對。
>
> **Q4.** **`APP_KEY` 用於**：
> ①**加密 session cookie**；
> ②**★★★ 加密資料庫中用 `encrypted` cast 的欄位**（身分證號、銀行帳號等）；
> ③**簽署 signed URL**（密碼重設連結、檔案下載連結）；
> ④**加密的佇列 payload**。
> **遺失或更換的後果**：
> ①**所有使用者立刻被登出**（session cookie 解不開）；
> ②**★★★ 資料庫中的加密欄位永久無法解密** —— **那些資料等於遺失了**；
> ③所有已發出的 signed URL 失效；
> ④佇列中未處理的加密 job 無法解開。
> **所以必須**：產生後**立刻備份到密碼管理系統**，
> **與資料庫備份分開保管**（備份檔外洩時沒有 key 就解不開加密欄位），
> **部署流程中絕不重新產生**（`key:generate` 只在第一次執行）。
>
> **Q5.** **PHP 的 MySQL 驅動對 `localhost` 有特殊處理** ——
> **`localhost` 會走 Unix socket 連線**，
> **`127.0.0.1` 會走 TCP 連線**。
> **用 `localhost` 的問題**：
> ①**socket 路徑可能不對**（不同的 MySQL 安裝方式路徑不同：
> `/var/run/mysqld/mysqld.sock`、`/tmp/mysql.sock`…）；
> ②**容器化時 socket 根本不存在**（資料庫在另一個容器）；
> ③錯誤訊息很難懂：`No such file or directory`（看起來像檔案問題，其實是連線問題）。
> **建議一律用 `127.0.0.1`**（明確且可攜）。
> 真的要用 socket（本機連線效能略好）就明確設 `DB_SOCKET=/var/run/mysqld/mysqld.sock`。
>
> **Q6.** **Redis 預設沒有密碼，如果又綁在 `0.0.0.0`，就是完全開放的**。
> **攻擊者可以**：
> ①**讀取所有 session** —— 拿到 session ID 後**直接偽造任何使用者的登入**；
> ②讀取所有快取（可能含個資與 API 回應）；
> ③**★★★ 用 `CONFIG SET dir` 與 `CONFIG SET dbfilename` 把資料寫到任意檔案路徑** ——
> 寫 SSH 的 `authorized_keys`（取得 shell）、
> 寫 webshell 到 web root、寫 cron 檔案（排程執行任意指令）。
> **必要設定**：
> ```conf
> bind 127.0.0.1 ::1
> requirepass 強密碼
> rename-command CONFIG ""      # ★ 停用危險指令
> rename-command FLUSHALL ""
> ```
> **驗證**：`ss -tlnp | grep 6379` 必須是 `127.0.0.1`。
>
> **Q7.** 因為 **`storage` 存放的是「跨版本必須保留的資料」**：
> `app/public/`（**使用者上傳的檔案**）、
> `framework/sessions/`（**登入狀態**，若用檔案式 session）、
> `framework/cache/`、`logs/`（**日誌**）。
> **如果每個 release 各有自己的 `storage`**：
> **每次部署，所有上傳的檔案會消失**（新目錄是空的），
> **所有使用者被登出**，日誌斷成好幾段。
> **做法**：`storage` 實體放在 `shared/`，
> 每次部署後 `rm -rf $REL/storage && ln -sfn $APP/shared/storage $REL/storage`。
> 同理 `.env` 也要放 `shared`（每個環境的設定不同，且不進 git）。
>
> **Q8.** **`php artisan config:cache` 把設定快取到 `bootstrap/cache/config.php` 了**。
> **快取存在時，Laravel 完全不讀 `.env`** ——
> 改了 `.env` 也不會有任何效果。
> **解法**：
> ```bash
> php artisan config:clear && php artisan config:cache
> ```
> **這也是為什麼**：
> ①正式環境**必須**用 `config:cache`（省下每次請求解析 `.env` 的成本）；
> ②但**程式碼中絕對不能用 `env()`**，只能用 `config()` ——
> 因為 `config:cache` 之後 `env()` 會回傳 `null`
> （這是 Laravel 最常見的部署陷阱之一）。
> 相關的還有 `route:cache`、`view:cache`、`event:cache`。
>
> **Q9.** **正式環境建議 `LOG_LEVEL=warning`**（或 `error`）。
> **不用 `debug` 的原因**：
> ①**磁碟消耗** —— `debug` 等級會記錄每一次的 SQL 查詢、每一個請求細節，
> 高流量下**一天可能產生數 GB 的日誌**，可能塞爆磁碟導致服務中斷；
> ②**★★ 資訊洩漏** —— debug 日誌常含**完整的請求內容**
> （可能有密碼、token、個資），日誌檔一旦外洩就是資料外洩；
> ③**效能** —— 大量的 I/O 寫入；
> ④**訊號被雜訊淹沒** —— 真正的錯誤混在幾百萬行 debug 訊息裡找不到。
> 搭配 `LOG_CHANNEL=daily` 與 `LOG_DAILY_DAYS=14` 做輪替。
>
> **Q10.** 因為 **`composer update` 會依 `composer.json` 的版本範圍重新解析並安裝「最新符合的版本」，
> 並改寫 `composer.lock`** ——
> 這表示**正式環境安裝的套件版本，可能與開發與測試環境完全不同**。
> **風險**：
> ①**未經測試的版本直接上正式環境** —— 可能有 breaking change；
> ②**建置結果不可重現** —— 同一份程式碼在不同時間部署會得到不同的相依；
> ③**★ 供應鏈風險** —— 自動拉到被入侵的新版本；
> ④更新 `composer.lock` 後與 git 中的版本不一致，下次部署又被覆蓋。
> **正確流程**：在**開發機**上執行 `composer update`，
> **測試通過後把 `composer.lock` commit 進 git**，
> 正式環境**只執行 `composer install`**（嚴格依照 lock 檔）。

---

## 延伸閱讀

- [[02-Laravel-Nginx與PHP-FPM設定]] — 下一步：Web 伺服器設定
- [[03-Laravel-佇列排程與Supervisor]] — 佇列與排程
- [[04-Laravel-快取最佳化與部署流程]] — 部署流程與快取
- [[07-Laravel-正式環境安全檢查表]] — 上線前的完整檢查
- [[01-PHP-安裝與多版本管理]] — PHP 的安裝
- [[01-MySQL-安裝與初始化]] — MySQL 的準備
