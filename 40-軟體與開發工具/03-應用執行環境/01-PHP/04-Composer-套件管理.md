---
title: "Composer 套件管理"
desc: "安裝、autoload、版本約束、正式環境部署最佳化與安全稽核"
aliases: [composer, composer.lock, autoload, packagist, composer audit]
tags: [群組/軟體與開發工具, 服務/php, 主題/套件管理]
category: PHP
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[01-PHP-安裝與多版本管理]]"]
updated: 2026-08-28
---

# Composer 套件管理

> [!abstract] 這篇你會學到
> - 安全地安裝 Composer（**驗證安裝程式的雜湊**）
> - 分清 **`composer.json` 與 `composer.lock`** 的角色與 git 政策
> - 讀懂**版本約束語法**（`^` / `~` / `>=`）
> - **正式環境部署的正確指令**（含 autoload 最佳化）
> - 用 **`composer audit`** 檢查已知漏洞
> - 處理**私有套件庫、Nova 授權金鑰、離線部署**

## 前置知識

- [[01-PHP-安裝與多版本管理]] — PHP CLI 版本與擴充
- [[01-Git-觀念與初次設定]] — 版本控制基礎

---

## 安裝

```bash
# ═══ ★ 安全的安裝方式（驗證雜湊）═══
$ EXPECTED=$(curl -sS https://composer.github.io/installer.sig)
$ curl -sS https://getcomposer.org/installer -o /tmp/composer-setup.php
$ ACTUAL=$(php -r "echo hash_file('sha384', '/tmp/composer-setup.php');")

$ if [ "$EXPECTED" = "$ACTUAL" ]; then
      sudo php /tmp/composer-setup.php --install-dir=/usr/local/bin --filename=composer
  else
      echo "✗✗ 雜湊不符，可能被竄改！"
  fi
$ rm -f /tmp/composer-setup.php

$ composer --version
Composer version 2.8.4 2026-08-01 10:00:00
```

> [!danger] 不要用 `curl ... | php` 直接執行
> ```bash
> # ❌ 極度危險
> $ curl -sS https://getcomposer.org/installer | php
> ```
> **這是供應鏈攻擊的標準入口** ——
> 若下載過程被中間人竄改（或該網站被入侵），
> **你會在自己的伺服器上以 root 執行任意程式碼**。
>
> **一律驗證雜湊。** 這個原則適用於所有的 `curl | bash` 安裝方式。

```bash
# ═══ 用套件庫安裝（版本較舊但有自動更新）═══
$ sudo apt install -y composer
$ composer --version

# ═══ 更新 Composer 自己 ═══
$ sudo composer self-update
$ sudo composer self-update --2                 # 停在 2.x
$ sudo composer self-update --rollback           # 回退

# ═══ 多版本 PHP 時明確指定 ═══
$ /usr/bin/php8.3 /usr/local/bin/composer install
```

---

## `composer.json` 與 `composer.lock`

```json
{
    "name": "gov/myapp",
    "type": "project",
    "require": {
        "php": "^8.3",
        "laravel/framework": "^11.0",
        "guzzlehttp/guzzle": "^7.8",
        "ext-redis": "*",
        "ext-intl": "*"
    },
    "require-dev": {
        "phpunit/phpunit": "^11.0",
        "laravel/pint": "^1.13",
        "nunomaduro/collision": "^8.0"
    },
    "autoload": {
        "psr-4": { "App\\": "app/" },
        "files": [ "app/helpers.php" ]
    },
    "autoload-dev": {
        "psr-4": { "Tests\\": "tests/" }
    },
    "scripts": {
        "post-autoload-dump": [
            "@php artisan package:discover --ansi"
        ]
    },
    "config": {
        "optimize-autoloader": true,
        "preferred-install": "dist",
        "sort-packages": true,
        "allow-plugins": {
            "pestphp/pest-plugin": true,
            "php-http/discovery": true
        }
    },
    "minimum-stability": "stable",
    "prefer-stable": true
}
```

| 檔案 | 內容 | git |
| --- | --- | --- |
| **`composer.json`** | **你宣告的需求**（版本範圍） | **✅ 一定要進 git** |
| **`composer.lock`** | **實際安裝的精確版本 + 雜湊** | **✅ 一定要進 git**（應用程式） |
| `vendor/` | 實際的套件程式碼 | **❌ 不要進 git** |

> [!danger] `composer.lock` 一定要進 git ★★
> ```
> 沒有 lock 檔：
>   開發機執行 composer install → 裝到 guzzle 7.8.1
>   兩週後正式機執行           → 裝到 guzzle 7.9.0（有 breaking change）
>     → 【開發機正常，正式機炸掉】
>       → 而且【無法重現】開發機的環境
>
> 有 lock 檔：
>   composer install 【永遠】裝出完全相同的版本組合
>     → 開發、測試、正式環境【完全一致】
> ```
>
> **唯一的例外**：你在開發一個**函式庫（library）**而非應用程式時，
> 不要提交 `composer.lock`（讓使用者自己解析版本）。
>
> ```bash
> # .gitignore
> /vendor/
> # ★ composer.lock 【不要】加進 .gitignore
> ```

### `install` vs `update` ★★★

```bash
# ═══ composer install ═══
# ★ 依【composer.lock】安裝精確的版本
# ★ 不會改變任何版本
# ★ 正式環境【只能用這個】
$ composer install

# ═══ composer update ═══
# ★ 依【composer.json】重新解析，找出符合約束的【最新】版本
# ★ 會【改寫 composer.lock】
# ★★ 絕對【不要】在正式環境執行
$ composer update

# ═══ 只更新特定套件 ═══
$ composer update guzzlehttp/guzzle
$ composer update guzzlehttp/guzzle --with-dependencies

# ═══ 只更新 lock 檔的雜湊（改了 composer.json 的非相依欄位後）═══
$ composer update --lock
```

> [!danger] 正式環境執行 `composer update` 的後果
> ```
> composer update
>   → 把所有套件更新到符合約束的最新版
>     → 可能引入 breaking change
>       → 【網站當場掛掉】
>         → 而且 composer.lock 被改了，git 有未提交的變更
>           → 下次部署時衝突
> ```
>
> **正確流程**：
> ```
> ① 開發機：composer update（或 composer update 某套件）
> ② 開發機：跑完整測試
> ③ 提交【composer.json + composer.lock】
> ④ 正式機：git pull && composer install --no-dev
> ```
>
> **防護**：
> ```bash
> # ★ 部署腳本中明確禁止
> if [ "$APP_ENV" = "production" ]; then
>     alias composer-update='echo "★ 正式環境禁止 composer update"; false'
> fi
> ```

---

## 版本約束

```json
{
    "require": {
        "vendor/pkg": "1.2.3",        // 精確版本（★ 太死板，不建議）
        "vendor/pkg": "^1.2.3",       // ★ >=1.2.3 <2.0.0（允許次版本與修補）
        "vendor/pkg": "~1.2.3",       // >=1.2.3 <1.3.0（只允許修補）
        "vendor/pkg": "~1.2",         // >=1.2.0 <2.0.0（等同 ^1.2）
        "vendor/pkg": ">=1.2 <2.0",   // 明確範圍
        "vendor/pkg": "1.2.*",        // >=1.2.0 <1.3.0
        "vendor/pkg": "*",            // ★★ 任何版本（極危險）
        "vendor/pkg": "dev-main",     // ★ 直接用分支（不穩定）
        "vendor/pkg": "^1.0 || ^2.0"  // 多個範圍
    }
}
```

```
語意化版本（SemVer）：主版本.次版本.修補
                      MAJOR.MINOR.PATCH

MAJOR 變更 → 【有 breaking change】
MINOR 變更 → 新增功能，向下相容
PATCH 變更 → 修 bug，向下相容

^1.2.3  = >=1.2.3 <2.0.0   ★ 最常用（允許新功能與修補，擋掉 breaking）
~1.2.3  = >=1.2.3 <1.3.0     保守（只允許修 bug）
```

> [!warning] `^0.x` 的特殊規則
> ```
> ^0.3.0 = >=0.3.0 <0.4.0     ★ 【不是】 <1.0.0
> ```
> **因為 SemVer 規定 0.x 版本是「開發中」，
> 任何 MINOR 變更都可能有 breaking change。**
>
> 這是很多人踩過的坑 —— 以為 `^0.3` 會涵蓋 `0.9`，其實不會。

```bash
# ★ 檢查目前實際安裝的版本
$ composer show
guzzlehttp/guzzle    7.8.1   Guzzle is a PHP HTTP client library
laravel/framework    v11.9.2 The Laravel Framework.

$ composer show guzzlehttp/guzzle
name     : guzzlehttp/guzzle
versions : * 7.8.1
requires : php ^7.2.5 || ^8.0
           guzzlehttp/promises ^1.5.3 || ^2.0.3

# ★ 為什麼某個套件被鎖在舊版
$ composer why-not guzzlehttp/guzzle 7.9
laravel/framework v11.9.2 requires guzzlehttp/guzzle (^7.8)

# ★ 誰依賴這個套件
$ composer why guzzlehttp/guzzle
laravel/framework  v11.9.2  requires  guzzlehttp/guzzle (^7.8)
aws/aws-sdk-php    3.300.0  requires  guzzlehttp/guzzle (^7.4)

# ★ 相依樹
$ composer depends laravel/framework --tree
```

---

## 正式環境部署

```bash
# ═══════════ ★★ 正式環境的標準指令 ═══════════
$ composer install \
    --no-dev \                    # ★ 不裝 require-dev（減少攻擊面與體積）
    --optimize-autoloader \       # ★ 產生 classmap（大幅加快載入）
    --classmap-authoritative \    # ★ 只用 classmap，不做檔案系統查找
    --no-interaction \            # 非互動（CI/CD 必要）
    --prefer-dist \               # 用壓縮包而非 git clone
    --no-progress \               # 不輸出進度條（日誌乾淨）
    --no-scripts                  # ★ 視情況（見下方警告）
```

| 參數 | 作用 | 效益 |
| --- | --- | --- |
| **`--no-dev`** | 不安裝 `require-dev` | **減少 100+ MB 與攻擊面** |
| **`--optimize-autoloader`（`-o`）** | 掃描所有 PSR-4 目錄產生 classmap | **載入速度提升明顯** |
| **`--classmap-authoritative`（`-a`）** | **只用 classmap，找不到就直接失敗** | **再快一些**（不做 file_exists） |
| `--apcu-autoloader` | 把 classmap 存進 APCu | 多程序共享 |
| `--prefer-dist` | 下載壓縮包 | 比 git clone 快很多 |
| `--no-interaction` | 不詢問 | CI/CD 必要 |

> [!danger] `--classmap-authoritative` 的前提
> ```
> 它讓 Composer 【完全信任 classmap】
>   → 不在 classmap 中的類別【直接判定不存在】
>     → 不會再去檔案系統找
>
> ★ 前提：所有類別都必須在 classmap 中
>   → 動態產生的類別（某些套件會在執行時產生）會【找不到】
> ```
>
> **症狀**：`Class "App\Generated\Xxx" not found`（但檔案明明存在）。
>
> **保守做法**：只用 `--optimize-autoloader`，不加 `--classmap-authoritative`。
> **測試方式**：加上後跑完整的測試套件，確認沒有類別找不到。

> [!warning] `--no-scripts` 的取捨
> ```
> composer.json 的 scripts 會在 install 時執行：
>   "post-autoload-dump": ["@php artisan package:discover"]
>
> --no-scripts 會跳過它們
>   → 好處：避免執行未預期的程式碼（★ 供應鏈安全）
>   → 壞處：Laravel 的 package discovery 不會執行
>            → 【套件的 ServiceProvider 沒被註冊】
> ```
>
> **建議做法**：**不用 `--no-scripts`，但明確檢視 `composer.json` 的 scripts**：
> ```bash
> $ composer show --self | grep -A20 scripts
> # 或直接看 composer.json
> ```
> 若真的用了 `--no-scripts`，記得手動執行：
> ```bash
> $ php artisan package:discover
> ```

```bash
# ═══ 部署後的 Laravel 最佳化 ═══
$ php artisan config:cache        # ★ 合併所有 config 成一個檔案
$ php artisan route:cache         # ★ 快取路由
$ php artisan view:cache          # 預編譯 Blade
$ php artisan event:cache         # 快取事件監聽器

# ★ 清除（改了 .env 或 config 後必須）
$ php artisan config:clear
$ php artisan optimize:clear      # 一次清全部
```

> [!danger] `config:cache` 之後 `env()` 只在 config 檔中有效
> ```php
> // ❌ 執行 config:cache 後，這裡的 env() 【永遠回傳 null】
> class SomeService {
>     public function __construct() {
>         $this->key = env('API_KEY');        // ★★ null！
>     }
> }
>
> // ✅ 正確做法
> // config/services.php
> return ['api' => ['key' => env('API_KEY')]];
> // 程式中
> $this->key = config('services.api.key');
> ```
>
> **原因**：`config:cache` 把所有 config 檔的**執行結果**寫成一個 PHP 陣列檔，
> 之後 Laravel **不再載入 `.env`**，所以 `env()` 找不到值。
>
> **檢查方式**：
> ```bash
> $ grep -rn "env(" app/ --include='*.php' | grep -v 'config/'
> # ★ app/ 中不應該有 env() 呼叫
> ```

---

## `composer audit`：檢查已知漏洞 ★

```bash
$ composer audit
Found 3 security vulnerability advisories affecting 2 packages:
+-------------------+----------------------------------------------------------+
| Package           | guzzlehttp/guzzle                                        |
| CVE              | CVE-2022-31090                                            |
| Title            | Cookie headers on redirect                                |
| URL              | https://github.com/guzzle/guzzle/security/advisories/...  |
| Affected versions| >=7.0.0,<7.4.5                                            |
| Reported at      | 2022-06-27                                                |
+-------------------+----------------------------------------------------------+

# 只看摘要
$ composer audit --format=summary
Found 3 security vulnerability advisories affecting 2 packages.

# JSON（給 CI/CD 用）
$ composer audit --format=json | jq '.advisories | keys'

# ★ 有漏洞時回傳非 0（可以讓 CI 失敗）
$ composer audit --no-dev; echo "exit=$?"

# 忽略特定的 advisory（★ 要有正當理由並記錄）
$ composer audit --ignore-severity=low
```

```bash
#!/usr/bin/env bash
# /usr/local/bin/composer-security-check —— 相依套件安全稽核
set -uo pipefail
DIR="${1:-.}"
cd "$DIR" || exit 1
FAIL=0

echo "═══ Composer 安全稽核：$(pwd) ═══"

echo -e "\n【1】★ 已知漏洞"
if composer audit --no-dev --format=summary 2>&1 | grep -q 'No security'; then
    echo "  ✓ 沒有已知漏洞"
else
    composer audit --no-dev 2>&1 | sed 's/^/  /'
    FAIL=1
fi

echo -e "\n【2】★ composer.lock 是否與 composer.json 同步"
if composer validate --no-check-publish --no-check-all 2>&1 | grep -qi 'lock file is not up to date'; then
    echo "  ⚠⚠ composer.lock 過期【執行 composer update --lock】"
    FAIL=1
else
    echo "  ✓ 同步"
fi

echo -e "\n【3】composer.json 驗證"
composer validate --no-check-publish 2>&1 | sed 's/^/  /'

echo -e "\n【4】★ 平台需求"
composer check-platform-reqs --no-dev 2>&1 | grep -v success | sed 's/^/  /' || echo "  ✓ 全部滿足"

echo -e "\n【5】★ 過期的套件"
composer outdated --direct --no-dev 2>&1 | tail -n +2 | head -20 | sed 's/^/  /' || echo "  ✓ 都是最新"

echo -e "\n【6】★ 危險的版本約束"
grep -nE '"\*"|"dev-|">=\s*[0-9.]+"\s*$' composer.json 2>/dev/null | sed 's/^/  ⚠ /' \
  || echo "  ✓ 沒有過寬的約束"

echo -e "\n【7】★ 被放棄維護的套件"
composer show --direct 2>/dev/null | awk '{print $1}' | while read -r p; do
    [ -z "$p" ] && continue
    composer show "$p" 2>/dev/null | grep -qi 'abandoned' && echo "  ⚠ $p 已被放棄維護"
done

echo -e "\n【8】★ vendor 目錄是否在 web root 內"
DOCROOT=$(sudo nginx -T 2>/dev/null | grep -oP '^\s*root\s+\K\S+' | tr -d ';' | head -1)
if [ -n "$DOCROOT" ] && [ -d "$DOCROOT/../vendor" ]; then
    echo "  ✓ vendor 在 web root 之外"
elif [ -n "$DOCROOT" ] && [ -d "$DOCROOT/vendor" ]; then
    echo "  ✗✗ vendor 在 web root 【內】—— 原始碼可能被下載"
    FAIL=1
fi

echo -e "\n【9】★ 從外部驗證"
for p in /vendor/autoload.php /composer.json /composer.lock; do
    code=$(curl -sk -o /dev/null -w '%{http_code}' -m 5 "https://${2:-localhost}$p" 2>/dev/null)
    [ "$code" = "200" ] && { echo "  ✗✗ $p 可以下載"; FAIL=1; }
done
[ "$FAIL" -eq 0 ] && echo "  ✓ 敏感檔案無法存取"

echo -e "\n【10】require-dev 是否安裝在正式環境"
if [ -d vendor/phpunit ] || [ -d vendor/nunomaduro ]; then
    echo "  ⚠⚠ 發現開發套件【正式環境應該用 --no-dev】"
    FAIL=1
else
    echo "  ✓ 沒有開發套件"
fi

exit $FAIL
```

```bash
# ★ 排程化（每週稽核）
$ sudo tee /etc/cron.d/composer-audit >/dev/null <<'EOF'
0 6 * * 1 www-data cd /var/www/app/current && \
  /usr/local/bin/composer-security-check . app.example.gov.tw > /var/log/composer-audit.log 2>&1 || \
  mail -s "【警告】Composer 安全稽核發現問題" admin@example.gov.tw < /var/log/composer-audit.log
EOF
```

---

## 私有套件庫與授權

### Laravel Nova（需要授權金鑰）

```json
{
    "repositories": [
        {
            "type": "composer",
            "url": "https://nova.laravel.com"
        }
    ],
    "require": {
        "laravel/nova": "^4.0"
    }
}
```

```bash
# ═══ ★ 設定授權（★ auth.json 不要進 git）═══
$ composer config --global --auth http-basic.nova.laravel.com \
    "你的Nova帳號email" "你的授權金鑰"

# 或專案層級（★ 產生 auth.json）
$ composer config --auth http-basic.nova.laravel.com "email" "key"

$ cat ~/.composer/auth.json
{
    "http-basic": {
        "nova.laravel.com": {
            "username": "admin@example.gov.tw",
            "password": "abcd1234-..."
        }
    }
}
$ chmod 600 ~/.composer/auth.json
```

> [!danger] `auth.json` 絕對不能進 git
> ```bash
> # .gitignore
> /auth.json
> /vendor/
> ```
> ```bash
> # ★ 檢查是否曾經被提交
> $ git log --all --diff-filter=A --name-only | grep -i 'auth.json'
> # ★ 若有，金鑰已經外洩，必須【立刻撤銷並重新產生】
> ```
>
> **CI/CD 中的正確做法**：用環境變數
> ```bash
> $ export COMPOSER_AUTH='{"http-basic":{"nova.laravel.com":{"username":"'"$NOVA_USER"'","password":"'"$NOVA_KEY"'"}}}'
> $ composer install --no-dev
> ```
> 或在 CI 中動態產生：
> ```bash
> $ composer config --auth http-basic.nova.laravel.com "$NOVA_USER" "$NOVA_KEY"
> $ composer install --no-dev
> $ rm -f auth.json                    # ★ 用完刪除
> ```

### 私有 Git 套件庫

```json
{
    "repositories": [
        {
            "type": "vcs",
            "url": "https://github.com/gov-org/internal-lib.git"
        },
        {
            "type": "path",
            "url": "../shared-lib",
            "options": { "symlink": true }
        }
    ],
    "require": {
        "gov-org/internal-lib": "^2.0"
    }
}
```

```bash
# ★ GitHub Token（唯讀的 deploy key 或 PAT）
$ composer config --global --auth github-oauth.github.com "ghp_xxxxxxxxxxxx"

# GitLab
$ composer config --global --auth gitlab-token.gitlab.example.gov.tw "glpat-xxx"

# ★ 或用 SSH（更好，不需要 token）
{
    "repositories": [
        { "type": "vcs", "url": "git@github.com:gov-org/internal-lib.git" }
    ]
}
```

### 私有 Packagist（Satis / Private Packagist）

```bash
# ★ 用 Satis 建立內部套件庫（離線環境常用）
$ composer create-project composer/satis:dev-main /var/www/satis
$ cd /var/www/satis
$ cat > satis.json <<'EOF'
{
    "name": "gov/internal-packages",
    "homepage": "https://packages.example.gov.tw",
    "repositories": [
        { "type": "vcs", "url": "https://git.example.gov.tw/lib/common.git" },
        { "type": "vcs", "url": "https://git.example.gov.tw/lib/auth.git" }
    ],
    "require-all": true,
    "archive": { "directory": "dist", "format": "tar", "skip-dev": true }
}
EOF
$ php bin/satis build satis.json public/
```

```json
// 專案的 composer.json
{
    "repositories": [
        { "type": "composer", "url": "https://packages.example.gov.tw" }
    ]
}
```

---

## 離線／內網部署

```bash
# ═══ 方式一：把 vendor 打包帶進內網 ═══
# 【有網路的機器】
$ composer install --no-dev --optimize-autoloader
$ tar czf vendor.tar.gz vendor/ composer.json composer.lock

# 【內網機器】
$ tar xzf vendor.tar.gz
$ composer dump-autoload --optimize --classmap-authoritative --no-dev

# ═══ 方式二：Composer 的離線快取 ═══
# 【有網路的機器】
$ composer install --no-dev
$ tar czf composer-cache.tar.gz -C ~/.cache composer

# 【內網機器】
$ tar xzf composer-cache.tar.gz -C ~/.cache
$ composer install --no-dev --prefer-dist

# ═══ 方式三：★ 內部 Satis 鏡像（最完整）═══
# 見上方
```

```bash
# ★ 完全離線的驗證
$ composer install --no-dev --offline
# 若有任何套件不在快取中會失敗
```

---

## 完整實戰範例

### 部署腳本中的 Composer 步驟

```bash
#!/usr/bin/env bash
# 部署腳本的 Composer 部分
set -euo pipefail
APP=/var/www/app
REL="$APP/releases/$(date +%Y%m%d-%H%M%S)"
PHP=/usr/bin/php8.3
COMPOSER=/usr/local/bin/composer

echo "═══ 【1】取得程式碼 ═══"
git clone --depth 1 --branch "${1:-main}" \
    https://github.com/gov-org/myapp.git "$REL"
cd "$REL"
echo "  commit: $(git rev-parse --short HEAD)"

echo -e "\n═══ 【2】★ 驗證 lock 檔 ═══"
"$PHP" "$COMPOSER" validate --no-check-publish --no-check-all
# ★ lock 檔與 json 不同步就中止
if "$PHP" "$COMPOSER" validate 2>&1 | grep -qi 'lock file is not up to date'; then
    echo "  ✗✗ composer.lock 過期，中止部署"
    exit 1
fi

echo -e "\n═══ 【3】★ 平台需求檢查 ═══"
"$PHP" "$COMPOSER" check-platform-reqs --no-dev || {
    echo "  ✗✗ 缺少必要的 PHP 擴充，中止"
    exit 1
}

echo -e "\n═══ 【4】★ 安全稽核（★ 有高風險漏洞就中止）═══"
if ! "$PHP" "$COMPOSER" audit --no-dev --format=summary 2>&1 | grep -q 'No security'; then
    echo "  ⚠ 發現安全性建議："
    "$PHP" "$COMPOSER" audit --no-dev 2>&1 | sed 's/^/    /'
    # 依政策決定要不要中止
    # exit 1
fi

echo -e "\n═══ 【5】安裝相依套件 ═══"
COMPOSER_ALLOW_SUPERUSER=0 \
"$PHP" "$COMPOSER" install \
    --no-dev \
    --optimize-autoloader \
    --classmap-authoritative \
    --no-interaction \
    --prefer-dist \
    --no-progress

echo -e "\n═══ 【6】連結共享資源 ═══"
ln -sfn "$APP/shared/.env"    "$REL/.env"
rm -rf "$REL/storage"
ln -sfn "$APP/shared/storage" "$REL/storage"

echo -e "\n═══ 【7】Laravel 最佳化 ═══"
"$PHP" artisan config:cache
"$PHP" artisan route:cache
"$PHP" artisan view:cache
"$PHP" artisan event:cache

echo -e "\n═══ 【8】資料庫遷移 ═══"
"$PHP" artisan migrate --force

echo -e "\n═══ 【9】★ 部署後檢查 ═══"
echo "  vendor 大小：$(du -sh vendor | cut -f1)"
echo "  套件數量：$("$PHP" "$COMPOSER" show --no-dev 2>/dev/null | wc -l)"
[ -d vendor/phpunit ] && echo "  ⚠⚠ 有開發套件（--no-dev 沒生效？）" \
                      || echo "  ✓ 沒有開發套件"

echo -e "\n═══ 【10】切換符號連結 ═══"
ln -sfn "$REL" "$APP/current.tmp"
mv -Tf "$APP/current.tmp" "$APP/current"

echo -e "\n═══ 【11】★ reload FPM（清 OPcache）═══"
sudo systemctl reload php8.3-fpm

echo -e "\n═══ 【12】清理舊版本 ═══"
ls -1dt "$APP"/releases/*/ | tail -n +6 | xargs -r rm -rf

echo -e "\n✓ 部署完成"
```

### 相依套件盤點報告

```bash
#!/usr/bin/env bash
# 產生相依套件盤點報告（★ 資安稽核用）
cd "${1:-.}" || exit 1
OUT="${2:-/tmp/composer-inventory-$(date +%Y%m%d).md}"

{
echo "# 相依套件盤點報告"
echo
echo "- 專案：$(grep -oP '"name"\s*:\s*"\K[^"]+' composer.json | head -1)"
echo "- 產生時間：$(date '+%F %T')"
echo "- 主機：$(hostname)"
echo "- PHP：$(php -v | head -1)"
echo "- Composer：$(composer --version)"
echo

echo "## 直接相依（production）"
echo
echo "| 套件 | 版本 | 授權 | 說明 |"
echo "| --- | --- | --- | --- |"
composer show --direct --no-dev --format=json 2>/dev/null | \
  jq -r '.installed[] | "| \(.name) | \(.version) | \(.licenses[0] // "?") | \(.description // "" | .[0:60]) |"' \
  2>/dev/null || composer show --direct --no-dev | awk '{printf "| %s | %s | | |\n", $1, $2}'
echo

echo "## 全部相依（含間接）"
echo
TOTAL=$(composer show --no-dev 2>/dev/null | wc -l)
echo "- 總數：**$TOTAL** 個套件"
echo "- vendor 大小：$(du -sh vendor 2>/dev/null | cut -f1)"
echo

echo "## 授權分布"
echo
composer licenses --no-dev --format=json 2>/dev/null | \
  jq -r '.dependencies | to_entries[] | .value.license[0] // "unknown"' 2>/dev/null | \
  sort | uniq -c | sort -rn | awk '{printf "- %s：%d 個\n", $2, $1}'
echo

echo "## ★ 已知漏洞"
echo
echo '```'
composer audit --no-dev 2>&1 | head -60
echo '```'
echo

echo "## ★ 過期的套件"
echo
echo '```'
composer outdated --direct --no-dev 2>&1 | head -30
echo '```'
echo

echo "## ★ 被放棄維護的套件"
echo
composer show --no-dev 2>/dev/null | awk '{print $1}' | while read -r p; do
    [ -z "$p" ] && continue
    composer show "$p" 2>/dev/null | grep -qi 'abandoned' && echo "- ⚠ **$p**"
done
echo

echo "## 檢查清單"
echo
cat <<'EOF'
- [ ] `composer audit` 沒有高風險漏洞
- [ ] 沒有被放棄維護的套件
- [ ] 沒有 `"*"` 或 `dev-` 的版本約束
- [ ] `composer.lock` 已提交到 git
- [ ] 正式環境用 `--no-dev`
- [ ] `vendor/` 在 web root 之外
- [ ] `auth.json` 不在 git 中
- [ ] 授權條款符合機關規定（注意 GPL/AGPL）
EOF
} | tee "$OUT"

echo
echo "報告已存到：$OUT"
```

---

## 常見錯誤與排錯

| 現象／錯誤 | 原因 | 解法 |
| --- | --- | --- |
| **正式環境跑 `composer update` 炸掉** ★★ | 引入了 breaking change | **正式環境只能 `composer install`** |
| **開發機正常、正式機炸掉** ★ | **`composer.lock` 沒進 git** | **一定要提交 lock 檔** |
| `Your requirements could not be resolved` | 版本約束衝突 | `composer why-not 套件 版本` |
| **`Class "X" not found`（檔案存在）** | `--classmap-authoritative` + 動態類別 | 移除該參數；或 `composer dump-autoload` |
| **`env()` 回傳 null** ★★ | **執行了 `config:cache`** | **改用 `config()`**；`app/` 中不要用 `env()` |
| 改了 `.env` 沒生效 | config 被快取 | `php artisan config:clear` |
| **`allow_plugins` 錯誤** | Composer 2.2+ 的安全機制 | 在 `config.allow-plugins` 明確允許 |
| `Composer detected issues in your platform` | PHP 版本或擴充不符 | `composer check-platform-reqs` |
| **多版本 PHP 時裝錯版本** | 用了預設的 `php` | `/usr/bin/php8.3 /usr/local/bin/composer install` |
| **`auth.json` 進了 git** ★★ | 忘了加 `.gitignore` | **立刻撤銷金鑰並重新產生** |
| `composer install` 極慢 | 用了 `--prefer-source`（git clone） | `--prefer-dist` |
| 記憶體不足 | Composer 需要大量記憶體 | `COMPOSER_MEMORY_LIMIT=-1 composer install` |
| **`vendor/` 在 web root 內** ★ | DocumentRoot 設錯 | `root .../public` |
| 離線環境裝不起來 | 需要網路 | 打包 vendor 或用 Satis |
| **`^0.3` 沒涵蓋 `0.9`** | `^0.x` 的特殊規則 | `^0.3` = `>=0.3.0 <0.4.0` |
| `composer.lock` 一直有變更 | 不同機器的 Composer 版本不同 | 統一 Composer 版本；`composer self-update --2` |

### 排查

```bash
# 【1】為什麼裝不了某個版本
$ composer why-not laravel/framework 12.0
$ composer prohibits laravel/framework 12.0     # 同義

# 【2】誰依賴這個套件
$ composer why guzzlehttp/guzzle
$ composer depends guzzlehttp/guzzle --tree

# 【3】平台需求
$ composer check-platform-reqs
$ composer check-platform-reqs --no-dev

# 【4】驗證 json 與 lock
$ composer validate --no-check-publish

# 【5】診斷（網路、權限、設定）
$ composer diagnose

# 【6】看實際的解析過程
$ composer install -vvv 2>&1 | head -50

# 【7】清快取
$ composer clear-cache
$ rm -rf vendor composer.lock && composer install     # ★ 最後手段

# 【8】autoload 問題
$ composer dump-autoload --optimize
$ grep -c '' vendor/composer/autoload_classmap.php    # classmap 的類別數
```

---

## 安全性注意事項

> [!danger] 供應鏈攻擊的四道防線
> ```
> ① ★ 安裝 Composer 時驗證雜湊（不要 curl | php）
> ② ★ composer.lock 進 git（確保版本不會意外變動）
> ③ ★ composer audit 檢查已知漏洞（排程化）
> ④ ★ 檢視 composer.json 的 scripts（install 時會執行）
> ```
>
> **真實案例的攻擊模式**：
> ```
> 攻擊者取得某個熱門套件的維護權限（或社交工程）
>   → 發布一個看似正常的新版本
>     → 其中的 post-install-cmd 執行惡意程式碼
>       → 【所有執行 composer update 的伺服器都被植入後門】
>
> ★ composer.lock 讓你【不會意外裝到新版本】
> ★ 但 composer update 時仍要檢視變更
> ```
>
> ```bash
> # ★ update 後檢視 lock 檔的變更
> $ composer update
> $ git diff composer.lock | grep -E '^\+.*"(name|version|source|dist)"'
> ```

> [!warning] `vendor/` 必須在 web root 之外
> ```
> ❌ DocumentRoot = /var/www/app
>    → https://網站/vendor/autoload.php          可以下載
>    → https://網站/vendor/某套件/tests/...       可能有測試用的後門檔案
>    → 【某些套件的 examples/ 中有可執行的 PHP】
>
> ✅ DocumentRoot = /var/www/app/public
>    → vendor/ 在 web root 之外，碰不到
> ```
> ```bash
> # ★ 驗證
> $ curl -sk -o /dev/null -w '%{http_code}\n' https://網站/vendor/autoload.php
> 404      # 必須
> $ curl -sk -o /dev/null -w '%{http_code}\n' https://網站/composer.json
> 404      # 必須
> ```

> [!danger] `--no-dev` 不只是省空間
> ```
> require-dev 中常見的東西：
>   · phpunit             （測試框架）
>   · symfony/var-dumper  （★ dump() 函式，可能洩漏變數）
>   · filp/whoops         （★★ 錯誤頁面，會顯示完整的原始碼與環境變數）
>   · barryvdh/laravel-debugbar  （★★ 顯示所有 SQL、session、config）
>   · fakerphp/faker      （測試資料產生器）
>
> ★ 若正式環境裝了這些，加上某個設定失誤
>   → 【完整的資料庫連線資訊、session 內容、原始碼全部顯示在錯誤頁】
> ```
> ```bash
> # ★ 檢查正式環境
> $ ls vendor/ | grep -E 'phpunit|whoops|debugbar|faker'
> # 應該沒有輸出
> ```

> [!tip] 授權條款也要盤點
> ```bash
> $ composer licenses --no-dev
> ```
> **機關專案要注意**：
> ```
> MIT / BSD / Apache-2.0  → 通常沒問題
> GPL-2.0 / GPL-3.0       → ★ 有傳染性，可能要求你的程式碼也開源
> AGPL-3.0                → ★★ 連「透過網路提供服務」也算散布
> 商業授權（Nova 等）      → ★ 確認授權數量與使用範圍
> ```
> **納入資產盤點與採購文件。**

---

## 速查表

### 安裝（★ 驗證雜湊）

```bash
EXPECTED=$(curl -sS https://composer.github.io/installer.sig)
curl -sS https://getcomposer.org/installer -o /tmp/composer-setup.php
ACTUAL=$(php -r "echo hash_file('sha384','/tmp/composer-setup.php');")
[ "$EXPECTED" = "$ACTUAL" ] && sudo php /tmp/composer-setup.php \
  --install-dir=/usr/local/bin --filename=composer
rm -f /tmp/composer-setup.php

❌ curl -sS https://getcomposer.org/installer | php     ← 供應鏈攻擊入口
```

### install vs update ★★

```bash
composer install    # ★ 依 lock 檔裝精確版本（★ 正式環境只能用這個）
composer update     # ★★ 重新解析 + 改寫 lock（★ 絕不在正式環境執行）
composer update 套件 --with-dependencies
composer update --lock                      # 只更新 lock 的雜湊
```

```
流程：開發機 update → 測試 → 提交 json+lock → 正式機 install --no-dev
```

### git 政策

```
composer.json  ✅ 進 git
composer.lock  ✅ 進 git（★ 應用程式；函式庫則不要）
vendor/        ❌ 不進 git
auth.json      ❌❌ 絕不進 git（含授權金鑰）
```

### 版本約束

```
^1.2.3   >=1.2.3 <2.0.0    ★ 最常用
~1.2.3   >=1.2.3 <1.3.0      保守（只修補）
~1.2     >=1.2.0 <2.0.0
1.2.*    >=1.2.0 <1.3.0
^0.3.0   >=0.3.0 <0.4.0    ★ 【不是】 <1.0.0
*        任何版本            ★★ 極危險
dev-main 直接用分支          ★ 不穩定
```

### 正式環境部署 ★

```bash
composer install \
  --no-dev \                     # ★ 減少 100MB 與攻擊面
  --optimize-autoloader \        # ★ 產生 classmap
  --classmap-authoritative \     # ★ 更快（但動態類別會找不到）
  --no-interaction --prefer-dist --no-progress

php artisan config:cache route:cache view:cache event:cache
```

```
★ config:cache 之後 env() 只在 config/ 中有效 → 程式中改用 config()
★ --classmap-authoritative 要跑完整測試確認沒有類別找不到
```

### 安全稽核

```bash
composer audit --no-dev                  # ★ 已知漏洞
composer audit --format=json | jq        # CI/CD
composer validate --no-check-publish     # json 與 lock 同步
composer check-platform-reqs --no-dev    # PHP 版本與擴充
composer outdated --direct --no-dev      # 過期的套件
composer licenses --no-dev               # ★ 授權盤點
composer show --direct --no-dev          # 直接相依清單
```

### 排查

```bash
composer why-not laravel/framework 12.0   # ★ 為什麼裝不了
composer why guzzlehttp/guzzle            # 誰依賴它
composer depends 套件 --tree
composer diagnose
composer install -vvv | head -50
composer clear-cache
COMPOSER_MEMORY_LIMIT=-1 composer install # 記憶體不足時
/usr/bin/php8.3 /usr/local/bin/composer install   # ★ 多版本時
```

### 私有套件庫

```bash
composer config --global --auth http-basic.nova.laravel.com "email" "key"
composer config --global --auth github-oauth.github.com "ghp_xxx"

# ★ CI/CD 用環境變數（不留 auth.json）
export COMPOSER_AUTH='{"http-basic":{"nova.laravel.com":{"username":"'"$U"'","password":"'"$K"'"}}}'
```

### 安全五條

```
① 安裝時驗證雜湊（不要 curl | php）
② composer.lock 進 git
③ composer audit 排程化
④ 正式環境 --no-dev（whoops/debugbar 會洩漏一切）
⑤ vendor/ 在 web root 之外（curl 網站/vendor/autoload.php 必須 404）
```

---

## 練習題

> [!question]- 練習 1：lock 檔的重要性
> 1. 建立一個小專案，`require` 一個常更新的套件（例如 `guzzlehttp/guzzle: ^7.0`）
> 2. `composer install`，記下版本
> 3. **刪除 `composer.lock`**，再 `composer install`
> 4. **版本一樣嗎？**（若該套件近期有更新就會不同）
> 5. 保留 lock 檔，在另一台機器 `composer install`
> 6. **版本完全一致嗎？**
> 7. **寫下這對「開發機正常、正式機炸掉」的意義**

> [!question]- 練習 2：autoload 最佳化的效果
> 1. 取一個真實的 Laravel 專案
> 2. `composer dump-autoload`（不最佳化），`ab -n 2000 -c 20` 測 QPS
> 3. `composer dump-autoload --optimize`，重測
> 4. 加上 `--classmap-authoritative`，重測
> 5. **記錄三者的 QPS 與 `vendor/composer/autoload_classmap.php` 的類別數**
> 6. **跑完整測試套件** —— `--classmap-authoritative` 有造成類別找不到嗎？

> [!question]- 練習 3：`config:cache` 的陷阱
> 1. 在一個 Service 類別中使用 `env('SOME_KEY')`
> 2. 不執行 `config:cache`，確認能取到值
> 3. **執行 `php artisan config:cache`**
> 4. **再測一次** → 值變成什麼？
> 5. 改成 `config('services.some.key')` + 在 `config/services.php` 用 `env()`
> 6. 重新 `config:cache`，再測
> 7. 用 `grep -rn "env(" app/` 檢查專案中還有沒有這個問題

> [!question]- 練習 4：安全稽核
> 1. 對一個真實專案執行 `composer audit`
> 2. **有漏洞嗎？各是什麼？**
> 3. `composer outdated --direct` —— 哪些套件過期了？
> 4. `composer licenses --no-dev` —— **有 GPL / AGPL 的套件嗎？**
> 5. 執行本篇的盤點報告腳本
> 6. **從外部驗證**：`curl https://網站/vendor/autoload.php` 與 `/composer.json`
> 7. 檢查正式環境有沒有 `whoops`、`debugbar`

> [!question]- 練習 5：離線部署
> 1. 在有網路的機器 `composer install --no-dev --optimize-autoloader`
> 2. 打包 `vendor/` 與 `~/.cache/composer`
> 3. **模擬內網**（`sudo ufw deny out 443` 或用沒有網路的容器）
> 4. 嘗試 `composer install` → **失敗了嗎？**
> 5. 解壓縮快取後 `composer install --prefer-dist --offline`
> 6. **成功了嗎？**
> 7. 記錄一份「內網部署 SOP」

---

## 小測驗

Q1. **為什麼不能用 `curl ... | php` 安裝 Composer？正確做法是什麼**？

Q2. **`composer.json` 與 `composer.lock` 各記錄什麼？git 政策為何？有什麼例外**？

Q3. **`composer install` 與 `composer update` 的差別是什麼？正式環境該用哪個**？

Q4. **`^1.2.3`、`~1.2.3`、`^0.3.0` 分別涵蓋什麼版本範圍**？

Q5. **正式環境部署的四個關鍵參數是什麼？各自的作用**？

Q6. **`--classmap-authoritative` 的前提與風險是什麼**？

Q7. **`--no-dev` 除了省空間，還有什麼安全意義**？

Q8. **執行 `config:cache` 之後 `env()` 為什麼失效？正確的寫法是什麼**？

Q9. **`auth.json` 不小心進了 git 該怎麼處理？CI/CD 中的正確做法是什麼**？

Q10. **供應鏈攻擊的四道防線是什麼**？

> [!question]- 測驗答案
> **Q1.** 因為 **`curl ... | php` 會直接執行從網路下載的內容，
> 完全沒有驗證** —— 若下載過程被中間人竄改，或該網站被入侵，
> **你會在自己的伺服器上（通常以 root）執行任意程式碼**，
> 這是供應鏈攻擊的標準入口。
> **正確做法是驗證安裝程式的 SHA-384 雜湊**：
> ```bash
> EXPECTED=$(curl -sS https://composer.github.io/installer.sig)
> curl -sS https://getcomposer.org/installer -o /tmp/composer-setup.php
> ACTUAL=$(php -r "echo hash_file('sha384','/tmp/composer-setup.php');")
> [ "$EXPECTED" = "$ACTUAL" ] && sudo php /tmp/composer-setup.php ...
> ```
> **這個原則適用於所有的 `curl | bash` 安裝方式。**
>
> **Q2.** **`composer.json` 記錄「你宣告的需求」**（版本範圍，例如 `^11.0`）；
> **`composer.lock` 記錄「實際安裝的精確版本與內容雜湊」**（例如 `v11.9.2`）。
> **git 政策**：**兩者都要進 git**，`vendor/` 不進 git。
> **例外**：**開發「函式庫（library）」而非應用程式時，不要提交 `composer.lock`** ——
> 因為函式庫的使用者應該自己解析版本，
> 提交 lock 檔會誤導（而且對使用者完全無效）。
>
> **Q3.** **`composer install`**：**依 `composer.lock` 安裝精確的版本組合**，
> **不會改變任何版本**。
> **`composer update`**：**依 `composer.json` 重新解析，找出符合約束的最新版本**，
> 並**改寫 `composer.lock`**。
> **正式環境只能用 `composer install`** ——
> 在正式環境執行 `update` 可能引入 breaking change 讓網站當場掛掉，
> 而且會改動 `composer.lock` 造成 git 有未提交的變更、下次部署衝突。
> 正確流程：開發機 `update` → 跑測試 → 提交 json+lock → 正式機 `install --no-dev`。
>
> **Q4.**
> **`^1.2.3` = `>=1.2.3 <2.0.0`** —— 允許次版本與修補更新，
> 擋掉有 breaking change 的主版本（**最常用**）。
> **`~1.2.3` = `>=1.2.3 <1.3.0`** —— 只允許修補更新（保守）。
> **`^0.3.0` = `>=0.3.0 <0.4.0`** —— **不是 `<1.0.0`**！
> 因為 SemVer 規定 0.x 是「開發中版本」，任何 MINOR 變更都可能有 breaking change，
> 所以 Composer 對 `^0.x` 採用特殊規則。**這是很多人踩過的坑。**
> （另外 `~1.2` = `>=1.2.0 <2.0.0`，與 `~1.2.3` 的行為不同，也常搞混。）
>
> **Q5.** ①**`--no-dev`** —— 不安裝 `require-dev`，
> 減少 100+ MB 與攻擊面（見 Q7）；
> ②**`--optimize-autoloader`（`-o`）** —— 掃描所有 PSR-4 目錄
> 產生完整的 classmap，**大幅加快類別載入**（不必每次都做檔案系統查找）；
> ③**`--no-interaction`** —— 非互動模式，CI/CD 必要；
> ④**`--prefer-dist`** —— 下載壓縮包而非 git clone，快很多。
> 可選的第五個是 **`--classmap-authoritative`（`-a`）**，再快一些但有風險（見 Q6）。
>
> **Q6.** **前提**：**所有類別都必須存在於 classmap 中**。
> 它讓 Composer **完全信任 classmap** ——
> **不在 classmap 中的類別直接判定為不存在，不會再去檔案系統尋找**。
> **風險**：**動態產生的類別會找不到** ——
> 某些套件會在執行時產生類別檔案（proxy、cache、編譯後的模板），
> 這些不在建置時的 classmap 中，
> 症狀是 `Class "App\Generated\Xxx" not found`（但檔案明明存在）。
> **保守做法**：只用 `--optimize-autoloader`。
> **要用的話**：加上後**跑完整的測試套件**確認沒有類別找不到。
>
> **Q7.** **`require-dev` 中常見的套件在正式環境是嚴重的安全風險**：
> **`filp/whoops`**（錯誤頁面，**會顯示完整的原始碼、環境變數、堆疊**）、
> **`barryvdh/laravel-debugbar`**（**顯示所有 SQL、session 內容、config**）、
> `symfony/var-dumper`（`dump()` 可能洩漏變數）、
> `phpunit`、`fakerphp/faker`。
> **只要有一個設定失誤**（例如 `APP_DEBUG=true` 沒關），
> **完整的資料庫連線資訊、session 內容、原始碼就會顯示在錯誤頁上**。
> ```bash
> ls vendor/ | grep -E 'phpunit|whoops|debugbar|faker'    # ★ 應無輸出
> ```
>
> **Q8.** 因為 **`config:cache` 把所有 `config/*.php` 的「執行結果」
> 寫成一個 PHP 陣列快取檔，之後 Laravel 就不再載入 `.env` 了** ——
> 所以程式中任何位置的 `env()` 呼叫都會**回傳 `null`**。
> **正確寫法**：
> ```php
> // config/services.php
> return ['api' => ['key' => env('API_KEY')]];    // ★ 只在 config/ 中用 env()
>
> // 程式中
> $this->key = config('services.api.key');        // ★ 用 config()
> ```
> **檢查方式**：`grep -rn "env(" app/ --include='*.php'` ——
> `app/` 中不應該有 `env()` 呼叫。
>
> **Q9.** **`auth.json` 含有授權金鑰（例如 Nova 的授權碼、GitHub token）**，
> 一旦進了 git（**即使是私有 repo**）就必須視為已外洩：
> ①**立刻到對應的服務撤銷／重新產生金鑰**；
> ②從 git 歷史中移除（`git filter-repo` 或 BFG）——
> 但**這不能取代撤銷金鑰**，因為可能已經被 clone。
> ```bash
> git log --all --diff-filter=A --name-only | grep -i 'auth.json'
> ```
> **CI/CD 的正確做法**：**用環境變數，不留下檔案**：
> ```bash
> export COMPOSER_AUTH='{"http-basic":{"nova.laravel.com":{"username":"'"$U"'","password":"'"$K"'"}}}'
> composer install --no-dev
> ```
> 或動態產生後用完刪除：`composer config --auth ... && composer install && rm -f auth.json`。
>
> **Q10.** ①**安裝 Composer 時驗證雜湊**（不要 `curl | php`）；
> ②**`composer.lock` 進 git** ——
> 確保版本不會意外變動，**你不會「自動」裝到被植入後門的新版本**；
> ③**`composer audit` 排程化** —— 定期檢查已知漏洞；
> ④**檢視 `composer.json` 的 `scripts`** ——
> `install`/`update` 時會執行其中的指令，
> 惡意套件可以透過 `post-install-cmd` 執行任意程式碼。
> **另外**：`composer update` 後應該檢視 lock 檔的變更：
> ```bash
> git diff composer.lock | grep -E '^\+.*"(name|version|source|dist)"'
> ```
> **典型的攻擊模式**是攻擊者取得熱門套件的維護權限，
> 發布看似正常的新版本，其中的 install script 植入後門 ——
> lock 檔讓你不會被動中招，但主動 update 時仍要警覺。

---

## 延伸閱讀

- [[05-PHP-OPcache與效能]] — autoload 最佳化與 OPcache 的關係
- [[06-PHP-安全設定]] — 應用層安全
- [[01-PHP-安裝與多版本管理]] — 多版本時的 Composer 使用
- [[06-Laravel-Nova部署]] — Nova 授權金鑰的完整處理
- [[08-Git-伺服器端與自動部署]] — 部署流程整合
- [[00-部署實戰-索引]] — 完整的部署實戰
