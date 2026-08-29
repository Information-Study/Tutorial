---
title: "Laravel Nova 部署"
desc: "Nova 授權金鑰、auth.json 管理、CI/CD 整合與資產發布"
aliases: [Nova, auth.json, nova:publish, 授權金鑰, COMPOSER_AUTH]
tags: [群組/實務案例, 主題/部署, 主題/Laravel, 主題/LXMP]
category: 專案部署實戰
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[130-01-04-04-guide-Laravel-快取最佳化與部署流程]]"]
updated: 2026-08-28
---

# Laravel Nova 部署

> [!abstract] 這篇你會學到
> - Nova 的**授權模式**與購買前該知道的事
> - **★★★ `auth.json`** 的三種管理方式（含 CI/CD）
> - **`NOVA_LICENSE_KEY`** 與授權驗證
> - **資產發布**（`nova:publish`）與升級流程
> - **★★★ 存取控管**（`NovaServiceProvider` 的 Gate）
> - **Inertia** 的部署特性（與 Filament/Livewire 的差別）
> - 常見的授權錯誤排查

## 前置知識

- [[130-01-04-04-guide-Laravel-快取最佳化與部署流程]] — 部署流程
- [[130-01-04-05-guide-Laravel-Filament部署]] — 對照參考

---

## Nova 的授權模式 ★★

```
Laravel Nova 是【商業軟體】

  Solo    $99/年    ★ 1 個專案（★ 個人開發者）
  Pro     $199/年   ★ 無限專案

★★ 授權綁定的是【帳號】，不是伺服器
   → 同一個授權可以部署到多台伺服器（同一個專案）

★★★ 部署時需要兩樣東西：
  ① auth.json          → composer 下載 Nova 套件時用
  ② NOVA_LICENSE_KEY   → 應用執行時驗證授權（★ Nova 4+）
```

> [!danger] 機關採購前的注意事項 ★★
> ```
> ★★ Nova 是【年費訂閱】
>   · 到期後【已安裝的版本仍可運作】
>   · ★ 但無法下載更新與新版本
>   · ★★ 無法用 composer install 重新安裝
>     → 部署到新伺服器時會失敗
>
> ★★★ 機關採購的實務問題：
>   ① 年度預算編列（★ 訂閱制的續約）
>   ② ★★ 授權帳號的保管（★ 承辦人離職怎麼辦）
>   ③ 國外刷卡與發票（★ 有些機關的會計流程不接受）
>   ④ ★ 廠商代購時，授權登記在誰名下
>
> ★★ 替代方案：Filament（MIT 授權，免費）
>   → 見 [[130-01-04-05-guide-Laravel-Filament部署]]
>   → ★ 功能上大致相當，社群更活躍
> ```

---

## ★★★ `auth.json`

```json
// ★★ composer 的私有套件庫認證
// ~/.composer/auth.json  或  <專案>/auth.json
{
    "http-basic": {
        "nova.laravel.com": {
            "username": "你的 Nova 帳號 email",
            "password": "★★★ 授權金鑰（不是登入密碼）"
        }
    }
}
```

```bash
# ★ 取得授權金鑰：
#   https://nova.laravel.com/settings#licenses
#   → 複製 License Key

# ★★ 設定（★ 專案層級）
$ composer config http-basic.nova.laravel.com \
    "your-email@example.gov.tw" \
    "your-license-key"
# → 產生 <專案>/auth.json

$ chmod 600 auth.json
$ echo "auth.json" >> .gitignore        # ★★★ 絕對不要 commit
```

> [!danger] `auth.json` 絕對不能進 git ★★★
> ```
> ★★★ auth.json 裡是【你的 Nova 授權金鑰】
>   → 外洩後任何人都能用你的授權下載 Nova
>     → ★ 違反授權條款，可能被 Laravel 撤銷授權
>     → ★★ 公開的 GitHub repo 會被自動掃描
>
> ★★ 必須：
>   echo "auth.json" >> .gitignore
>
> ★★★ 若已經 commit 過：
>   ① 【立刻】到 https://nova.laravel.com/settings#licenses 重新產生金鑰
>   ② git filter-repo 或 BFG 清除歷史（★ 但假設已外洩）
>   ③ 更新所有部署環境的 auth.json
> ```

```bash
# ★★ 檢查有沒有誤 commit
$ git log --all --full-history -- auth.json
$ git log --all -p -S 'nova.laravel.com' | head -30

# ★ 掃描整個歷史
$ git rev-list --all | while read -r c; do
    git grep -l 'nova.laravel.com' "$c" 2>/dev/null
  done | head
```

### 三種管理方式 ★★

```bash
# ═══════ ★ 方式 ①：全域 auth.json（★ 單一伺服器）═══════
$ sudo -u deploy mkdir -p /home/deploy/.composer
$ sudo -u deploy tee /home/deploy/.composer/auth.json >/dev/null <<'EOF'
{
    "http-basic": {
        "nova.laravel.com": {
            "username": "admin@example.gov.tw",
            "password": "★ 授權金鑰"
        }
    }
}
EOF
$ sudo chmod 600 /home/deploy/.composer/auth.json
$ sudo chown deploy:deploy /home/deploy/.composer/auth.json

# ★ 驗證
$ sudo -u deploy composer config --global --list | grep nova
```

```bash
# ═══════ ★★ 方式 ②：專案的 shared/auth.json（★ 推薦）═══════
$ sudo -u deploy tee /var/www/api/shared/auth.json >/dev/null <<'EOF'
{
    "http-basic": {
        "nova.laravel.com": {
            "username": "admin@example.gov.tw",
            "password": "★ 授權金鑰"
        }
    }
}
EOF
$ sudo chmod 600 /var/www/api/shared/auth.json

# ★★ 部署時連結進 release
$ ln -sfn /var/www/api/shared/auth.json "$REL/auth.json"
# ★ 然後才跑 composer install
```

```bash
# ═══════ ★★★ 方式 ③：COMPOSER_AUTH 環境變數（★ CI/CD 用）═══════
$ export COMPOSER_AUTH='{"http-basic":{"nova.laravel.com":{"username":"admin@example.gov.tw","password":"授權金鑰"}}}'
$ composer install --no-dev --optimize-autoloader

# ★★ 好處：不用在磁碟上留檔案
```

```yaml
# ★★★ GitHub Actions
name: 部署

on:
  push:
    tags: ['v*']

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: shivammathur/setup-php@v2
        with:
          php-version: '8.3'
          extensions: mbstring, xml, curl, zip, bcmath, intl, pdo_mysql, redis

      # ═══ ★★★ Nova 授權 ═══
      - name: 設定 composer 認證
        env:
          # ★★ 存在 GitHub Secrets
          NOVA_USERNAME: ${{ secrets.NOVA_USERNAME }}
          NOVA_LICENSE_KEY: ${{ secrets.NOVA_LICENSE_KEY }}
        run: |
          composer config --global --auth \
            http-basic.nova.laravel.com "$NOVA_USERNAME" "$NOVA_LICENSE_KEY"

      # ★ 或用環境變數（更乾淨，不留檔案）
      # env:
      #   COMPOSER_AUTH: ${{ secrets.COMPOSER_AUTH_JSON }}

      - run: composer install --no-dev --optimize-autoloader --no-interaction

      - uses: actions/setup-node@v4
        with: { node-version: '22', cache: npm }
      - run: npm ci && npm run build

      # ★★ 打包（★ 排除 auth.json）
      - name: 打包
        run: |
          tar czf release.tar.gz \
            --exclude='.git' --exclude='node_modules' \
            --exclude='auth.json' \
            --exclude='tests' --exclude='.env' \
            .

      - uses: actions/upload-artifact@v4
        with: { name: release, path: release.tar.gz }
```

> [!warning] CI 建置的好處 ★★
> ```
> ★★ 用 CI 建置 + 傳產物的模式（模式②）
>   → ★★★ 【正式環境完全不需要 auth.json】
>     → vendor/ 已經在 CI 上裝好了
>       → ★ 伺服器上連 composer 都不用裝
>         → 大幅降低授權金鑰外洩的風險
>
> ★★ 這是處理 Nova 授權最乾淨的方式
> ```

---

## 安裝與部署

```bash
# ═══ 安裝（★ 在開發機做）═══
$ composer require laravel/nova
$ php artisan nova:install
$ php artisan migrate
$ php artisan nova:user
```

```dotenv
# ★★★ .env（Nova 4+ 需要）
NOVA_LICENSE_KEY=你的授權金鑰
```

```bash
# ═══════ ★★ 正式環境的部署步驟 ═══════
$ cd "$REL"

# ① ★★★ 連結 auth.json（★ composer install 之前）
$ ln -sfn /var/www/api/shared/auth.json "$REL/auth.json"

# ② composer
$ composer install --no-dev --optimize-autoloader --no-interaction

# ③ ★★ 發布 Nova 的資產
$ php artisan nova:publish

# ④ Laravel 最佳化
$ php artisan optimize

# ⑤ ★ 移除 auth.json 的連結（★ 部署後不需要）
$ rm -f "$REL/auth.json"
```

> [!danger] `nova:publish` 每次升級都要跑 ★★
> ```
> $ php artisan nova:publish
> → 把 Nova 的 CSS/JS 複製到 public/vendor/nova/
>
> ★★ 什麼時候要跑：
>   · ★★★ 每次部署（★ releases 佈局下 public/ 是新的）
>   · 每次 composer update 升級 Nova 後
>
> ★★ 不跑的後果：
>   · public/vendor/nova/ 不存在 → ★ 後台的 CSS/JS 全部 404
>   · 或者是【舊版本的資產配新版本的 HTML】→ 版面錯亂
>
> ★ 檢查：
>   ls -la public/vendor/nova/
>   curl -sI https://api/vendor/nova/app.js
> ```

```bash
# ★★ 驗證資產
$ ls -la "$REL/public/vendor/nova/" | head
-rw-r--r-- 1 deploy www-data  842183 app.js
-rw-r--r-- 1 deploy www-data  218442 app.css
-rw-r--r-- 1 deploy www-data    4821 manifest.js

$ curl -sI https://api.example.gov.tw/vendor/nova/app.js | head -1
HTTP/2 200
```

```
# ★★ .gitignore
/public/vendor/nova/
/auth.json
```

---

## ★★★ 存取控管

```php
<?php
// ★★★ app/Providers/NovaServiceProvider.php
namespace App\Providers;

use Illuminate\Support\Facades\Gate;
use Laravel\Nova\Nova;
use Laravel\Nova\NovaApplicationServiceProvider;
use Laravel\Nova\Menu\MenuSection;
use Laravel\Nova\Menu\MenuItem;

class NovaServiceProvider extends NovaApplicationServiceProvider
{
    public function boot(): void
    {
        parent::boot();

        Nova::withBreadcrumbs();
        Nova::footer(fn () => '機關管理系統 © ' . date('Y'));
    }

    // ═══════ ★★★ 誰能存取 Nova ═══════
    protected function gate(): void
    {
        Gate::define('viewNova', function ($user) {
            // ── ★ 方式 ①：角色 ──
            return $user->hasRole(['admin', 'editor']) && $user->is_active;

            // ── ★ 方式 ②：email 白名單（★ 小團隊）──
            // return in_array($user->email, [
            //     'admin@example.gov.tw',
            //     'manager@example.gov.tw',
            // ], true);

            // ── ★★ 方式 ③：email 網域 + 額外條件 ──
            // return str_ends_with($user->email, '@example.gov.tw')
            //     && $user->hasVerifiedEmail()
            //     && $user->is_active
            //     && $user->department_id === 1;   // ★ 只有資訊室
        });
    }

    // ═══ 路由 ═══
    protected function routes(): void
    {
        Nova::routes()
            ->withAuthenticationRoutes()
            // ->withPasswordResetRoutes()      // ★ 內部系統通常不需要
            ->register();
    }

    // ═══ 儀表板 ═══
    protected function dashboards(): array
    {
        return [new \App\Nova\Dashboards\Main];
    }

    // ═══ 工具 ═══
    public function tools(): array
    {
        return [];
    }
}
```

> [!danger] Nova 的預設 Gate 比 Filament 安全，但仍要檢查 ★★
> ```
> ★★ Nova 的預設 gate（nova:install 產生的）：
>   Gate::define('viewNova', function ($user) {
>       return in_array($user->email, [
>           //
>       ]);
>   });
>
> ★ 這是【空陣列】→ 預設【拒絕所有人】（★ 安全的預設）
>
> ★★★ 但很多人為了「先能用」會改成：
>   return true;          ← ★★★ 千萬不要留在正式環境
>
> ★★ 檢查：
>   grep -A10 "define('viewNova'" app/Providers/NovaServiceProvider.php
> ```

```bash
# ★★★ 上線前必測
$ grep -A12 "viewNova" /var/www/api/current/app/Providers/NovaServiceProvider.php
# ★ 確認不是 return true;

$ grep -q 'return true;' <(grep -A12 "viewNova" \
    /var/www/api/current/app/Providers/NovaServiceProvider.php) && \
  echo "✗✗✗ viewNova 回傳 true —— 任何登入者都能進 Nova"
```

### Nginx 層的保護

```nginx
# ★★ Nova 的路徑（預設 /nova）
location ^~ /nova {
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    deny all;

    limit_req zone=api_general burst=30 nodelay;
    try_files $uri $uri/ /index.php?$query_string;
}

# ★★ Nova 的 API 端點（★ 前端會呼叫）
location ^~ /nova-api {
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    deny all;
    try_files $uri $uri/ /index.php?$query_string;
}

# ★ 資產（★ 可以公開，因為只是 JS/CSS）
location ^~ /vendor/nova/ {
    try_files $uri =404;
    expires 30d;
    add_header Cache-Control "public, max-age=2592000";
    add_header X-Content-Type-Options "nosniff" always;
    access_log off;
}

# ★★ 登入端點嚴格限流
location = /nova/login {
    limit_req zone=api_login burst=3 nodelay;
    limit_req_status 429;
    allow 10.0.0.0/8;
    deny all;
    try_files $uri $uri/ /index.php?$query_string;
}
```

```php
<?php
// ★ 或改變 Nova 的路徑（★ 增加掃描難度，但不是主要防護）
// config/nova.php
'path' => env('NOVA_PATH', '/nova'),
```

```dotenv
NOVA_PATH=/internal-admin-7x9k
```

---

## Inertia 的部署特性 ★★

```
★★ Nova 用的是 Vue 3 + Inertia（不是 Livewire）

★ 與 Filament/Livewire 的差別：
  · ★★ 請求數量少很多（★ 前端渲染，只有資料來回）
  · ★★ WAF 誤判的機率低（★ 請求是標準的 JSON API）
  · ★ 首次載入較大（★ 要下載整個 Vue app）
  · ★★ 對 PHP-FPM 的負載較低
```

```nginx
# ★★ Nova 的 API 請求是標準 JSON → WAF 誤判較少
# ★ 但仍建議排除幾條規則
```

```apache
# /etc/nginx/modsec/nova-exclusions.conf
# ★ Nova 的 API 端點
SecRule REQUEST_URI "@beginsWith /nova-api/" \
  "id:30001,phase:2,pass,nolog,\
   ctl:ruleRemoveTargetByTag=attack-xss;ARGS,\
   ctl:ruleRemoveById=942440"

# ★ Nova 的檔案上傳
SecRule REQUEST_URI "@rx ^/nova-api/.*/(field|attach)" \
  "id:30002,phase:2,pass,nolog,ctl:ruleEngine=DetectionOnly"

SecRequestBodyNoFilesLimit 1048576
```

```php
<?php
// ★★ Nova Resource 的效能優化
namespace App\Nova;

use Laravel\Nova\Fields\ID;
use Laravel\Nova\Fields\Text;
use Laravel\Nova\Fields\BelongsTo;
use Laravel\Nova\Http\Requests\NovaRequest;
use Illuminate\Database\Eloquent\Builder;

class Order extends Resource
{
    public static $model = \App\Models\Order::class;
    public static $title = 'id';
    public static $search = ['id', 'reference'];

    // ★★ 每頁筆數
    public static $perPageOptions = [25, 50, 100];

    // ★★★ 避免 N+1
    public static function indexQuery(NovaRequest $request, $query): Builder
    {
        return $query->with(['customer'])->withCount('items');
    }

    public static function detailQuery(NovaRequest $request, $query): Builder
    {
        return $query->with(['customer', 'items.product']);
    }

    // ★★ 關聯的查詢也要優化
    public static function relatableQuery(NovaRequest $request, $query): Builder
    {
        return $query->select(['id', 'name']);      // ★ 只選需要的欄位
    }

    public function fields(NovaRequest $request): array
    {
        return [
            ID::make()->sortable(),
            BelongsTo::make('客戶', 'customer', Customer::class)
                ->searchable()
                ->withSubtitles(),
            Text::make('編號', 'reference')->sortable(),
            // ...
        ];
    }

    // ★★ 授權（★ 每個 Resource 都要）
    public static function authorizedToViewAny(Request $request): bool
    {
        return $request->user()->can('viewAny', \App\Models\Order::class);
    }
}
```

---

## 完整實戰範例：Nova 的部署腳本片段

```bash
#!/usr/bin/env bash
# ★★ 部署腳本中與 Nova 相關的完整片段
set -euo pipefail
APP="${APP:-/var/www/api}"
REL="$1"
SITE="${SITE:-https://api.example.gov.tw}"

c(){ echo -e "\033[36m  $*\033[0m"; }
die(){ echo -e "\033[31m  ✗✗ $*\033[0m" >&2; exit 1; }

# ══ 【1】★★★ auth.json ══
c "★★★ Nova 授權"
if [ -f "$APP/shared/auth.json" ]; then
    ln -sfn "$APP/shared/auth.json" "$REL/auth.json"
    c "    ✓ 已連結 shared/auth.json"

    # ★★ 驗證格式
    if ! jq -e '.["http-basic"]["nova.laravel.com"].password' \
         "$APP/shared/auth.json" >/dev/null 2>&1; then
        die "auth.json 格式不正確或缺少 nova.laravel.com"
    fi
    # ★ 權限
    P=$(stat -Lc %a "$APP/shared/auth.json")
    [ "$P" -le 600 ] || die "auth.json 權限是 $P（應該 ≤600）"

elif [ -n "${COMPOSER_AUTH:-}" ]; then
    c "    ✓ 使用 COMPOSER_AUTH 環境變數"
elif [ -f /home/deploy/.composer/auth.json ]; then
    c "    ✓ 使用全域 auth.json"
else
    c "    ⚠ 找不到 Nova 授權設定"
    c "      → 若 vendor/ 已由 CI 建置好則可忽略"
    [ -d "$REL/vendor/laravel/nova" ] || die "vendor/laravel/nova 不存在且無授權"
fi

# ══ 【2】composer ══
c "composer install"
cd "$REL"
COMPOSER_MEMORY_LIMIT=-1 composer install \
    --no-dev --optimize-autoloader --no-interaction --prefer-dist --no-progress \
    2>&1 | tail -6 | sed 's/^/    /'

[ -d "$REL/vendor/laravel/nova" ] || die "Nova 套件沒有安裝成功"

# ══ 【3】★★ 移除 auth.json（★ 安全）══
rm -f "$REL/auth.json"
c "    ✓ 已移除 release 中的 auth.json 連結"

# ══ 【4】★★★ 發布資產 ══
c "★★★ nova:publish"
php artisan nova:publish 2>&1 | sed 's/^/    /'

for f in public/vendor/nova/app.js public/vendor/nova/app.css; do
    [ -f "$REL/$f" ] && echo "    ✓ $f ($(du -h "$REL/$f" | cut -f1))" || \
      die "找不到 $f —— nova:publish 失敗"
done

# ══ 【5】★★★ 安全檢查 ══
c "★★★ 安全檢查"
FAIL=0

# ★★★ viewNova gate
NSP="$REL/app/Providers/NovaServiceProvider.php"
if [ -f "$NSP" ]; then
    GATE=$(sed -n "/define('viewNova'/,/});/p" "$NSP")
    if echo "$GATE" | grep -qE '^\s*return true;'; then
        echo "    ✗✗✗ viewNova 回傳 true —— 任何登入者都能進 Nova"
        FAIL=1
    elif echo "$GATE" | grep -qE 'in_array\(\s*\$user->email,\s*\[\s*(//)?\s*\]'; then
        echo "    ⚠ viewNova 的 email 陣列是空的 —— 沒有人能進（★ 可能是忘了設定）"
    else
        echo "    ✓ viewNova 有實作條件"
        echo "$GATE" | grep -E 'return|hasRole|in_array' | head -3 | sed 's/^/      /'
    fi
else
    echo "    ⚠ 找不到 NovaServiceProvider.php"
fi

# ★★ NOVA_LICENSE_KEY
if grep -q '^NOVA_LICENSE_KEY=.\+' "$APP/shared/.env"; then
    echo "    ✓ NOVA_LICENSE_KEY 已設定"
else
    echo "    ⚠ NOVA_LICENSE_KEY 未設定（★ Nova 4+ 需要）"
fi

# ★★★ auth.json 不在 release 裡
if [ -e "$REL/auth.json" ]; then
    echo "    ✗✗ release 中仍有 auth.json"
    FAIL=1
else
    echo "    ✓ release 中沒有 auth.json"
fi

# ★ .gitignore
if grep -q '^auth.json' "$REL/.gitignore" 2>/dev/null || \
   grep -q '^/auth.json' "$REL/.gitignore" 2>/dev/null; then
    echo "    ✓ .gitignore 有排除 auth.json"
else
    echo "    ⚠ .gitignore 沒有排除 auth.json"
fi

[ "$FAIL" -eq 0 ] || die "安全檢查未通過"

# ══ 【6】★★ 部署後驗證（★ 切換之後執行）══
verify_nova() {
    c "★★ Nova 驗證"
    local F=0
    v(){ printf '    %-44s ' "$1"; if eval "$2" >/dev/null 2>&1; then echo "✓"; else echo "✗"; F=1; fi; }

    v "★ 登入頁可存取"  "[ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/nova/login)\" = 200 ]"
    v "★★ app.js 200"    "[ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/vendor/nova/app.js)\" = 200 ]"
    v "★★ app.css 200"   "[ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/vendor/nova/app.css)\" = 200 ]"
    v "★★★ auth.json 無法存取" \
      "[ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/auth.json)\" != 200 ]"
    v "★ 未登入被導向"   "[ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/nova)\" = 302 ]"

    # ★ 檢查授權錯誤
    if curl -s "$SITE/nova/login" | grep -qi 'license\|unauthorized\|invalid'; then
        echo "    ✗✗ 頁面出現授權相關的錯誤訊息"
        F=1
    fi

    return $F
}
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`Could not authenticate against nova.laravel.com`** ★★★ | `auth.json` 缺失或錯誤 | 設定 `auth.json` 或 `COMPOSER_AUTH` |
| **`The requested package laravel/nova could not be found`** ★★ | repositories 沒設或授權過期 | 檢查 `composer.json` 的 repositories |
| **後台版面全爛** ★★★ | 沒跑 `nova:publish` | 部署時執行 |
| **`Invalid Nova license`** ★★ | `NOVA_LICENSE_KEY` 錯或過期 | 檢查 `.env`；到官網確認授權狀態 |
| **任何登入者都能進 Nova** ★★★ | `viewNova` 回傳 `true` | 實作正確的條件 |
| **沒有人能進 Nova** ★ | email 陣列是空的 | 填入或改用角色判斷 |
| `auth.json` 被 commit ★★★ | 沒加 `.gitignore` | **重新產生金鑰**；清歷史 |
| **升級後版面錯亂** ★★ | 資產是舊版的 | 重跑 `nova:publish` |
| **表格載入很慢** ★★ | N+1 查詢 | `indexQuery()` 加 `with()` |
| `403 This action is unauthorized` | Policy 沒定義 | 建立對應的 Policy |
| **CI 建置失敗（授權）** ★★ | Secrets 沒設 | 設定 `NOVA_USERNAME` / `NOVA_LICENSE_KEY` |
| 授權到期後無法部署 ★★ | 訂閱過期 | 續約；或用 CI 建好的 vendor/ |

### 排查

```bash
SITE=https://api.example.gov.tw
APP=/var/www/api

# 【1】★★★ 授權設定
$ cat /var/www/api/shared/auth.json | jq '.["http-basic"] | keys'
[
  "nova.laravel.com"
]
$ stat -c '%a %U:%G' /var/www/api/shared/auth.json
600 deploy:deploy

# 【2】★★ 測試能不能下載
$ cd /tmp && composer create-project --dry-run laravel/nova 2>&1 | head -5
# ★ 或直接測 HTTP
$ USER=$(jq -r '.["http-basic"]["nova.laravel.com"].username' /var/www/api/shared/auth.json)
$ PASS=$(jq -r '.["http-basic"]["nova.laravel.com"].password' /var/www/api/shared/auth.json)
$ curl -su "$USER:$PASS" -o /dev/null -w '%{http_code}\n' \
    https://nova.laravel.com/api/packages.json
200                                    # ★★ 200 = 授權有效

# 【3】★★ Nova 套件與版本
$ composer show laravel/nova
$ ls -la "$APP/current/vendor/laravel/nova/" | head -3

# 【4】★★★ 資產
$ ls -la "$APP/current/public/vendor/nova/"
$ curl -sI "$SITE/vendor/nova/app.js" | head -1
$ curl -s "$SITE/nova/login" | grep -oE '/vendor/nova/[^"]*' | sort -u

# 【5】★★★ Gate
$ sed -n "/define('viewNova'/,/});/p" \
    "$APP/current/app/Providers/NovaServiceProvider.php"

# 【6】授權金鑰
$ grep '^NOVA_LICENSE_KEY=' "$APP/shared/.env" | sed 's/=.*/=***/'
$ php "$APP/current/artisan" nova:check-license 2>/dev/null || true

# 【7】★ Nova 的日誌
$ tail -50 "$APP/shared/storage/logs/laravel-$(date +%Y-%m-%d).log" | grep -i nova

# 【8】效能
$ sudo tail -30 /var/log/php-fpm/api-slow.log | grep -i nova
```

---

## 安全性注意事項

> [!danger] Nova 的四條紅線 ★★★
> ```
> ① ★★★★ auth.json 絕對不能進 git
>      → 外洩 = 授權金鑰外洩 → 可能被撤銷授權
>      → ★ 公開 repo 會被自動掃描
>      → 已經 commit 過 → 【立刻重新產生金鑰】
>
> ② ★★★ viewNova 不能 return true
>      → 任何登入者都能進管理後台
>      → ★ Nova 的預設是空陣列（安全），但很多人為了測試改成 true
>
> ③ ★★ auth.json 不能留在 web 可存取的位置
>      → 放 shared/ 並在部署後移除 release 中的連結
>      → ★ Nginx 也要擋：location ~ /auth\.json { deny all; }
>
> ④ ★★ Nova 的路徑要限制來源
>      → /nova 與 /nova-api 都要
>      → ★ /vendor/nova/（資產）可以公開
> ```

```nginx
# ★★★ 額外的保護
location ~ ^/(auth\.json|composer\.(json|lock)|package\.json)$ {
    deny all;
    access_log off;
}
```

```bash
# ★★★ 上線前必測
$ for p in /auth.json /composer.json /nova /nova-api/scripts; do
    printf '%-30s %s\n' "$p" "$(curl -sko /dev/null -w '%{http_code}' "$SITE$p")"
  done
/auth.json                     404          # ★★★ 必須
/composer.json                 404          # ★★
/nova                          302          # ★ 導向登入（或 403 若有 IP 限制）
/nova-api/scripts              403          # ★ 或 302
```

> [!warning] 授權的長期維運 ★★
> ```
> ★★ 機關要注意的：
>   ① 【授權帳號的保管】
>      → 用機關的共用信箱（★ 不要用個人 email）
>      → ★ 密碼與授權金鑰存在密碼管理系統
>      → 承辦人離職時要交接
>
>   ② 【到期提醒】
>      → 到期後無法 composer install
>      → ★★ 到期前 60 天就要開始編列預算
>      → 設定行事曆提醒
>
>   ③ ★★ 【備份 vendor/laravel/nova】
>      → 若授權到期又需要緊急部署
>      → ★ 有 vendor/ 的備份就能撐過去
>      → tar czf nova-vendor-backup.tar.gz vendor/laravel/nova
>
>   ④ ★ 【評估替代方案】
>      → Filament 是 MIT 授權（免費）
>      → 遷移成本 vs 每年的授權費
> ```

```bash
# ★★ 授權到期監控
$ sudo tee /usr/local/bin/check-nova-license >/dev/null <<'EOF'
#!/usr/bin/env bash
AUTH=/var/www/api/shared/auth.json
[ -f "$AUTH" ] || { echo "找不到 auth.json"; exit 1; }

USER=$(jq -r '.["http-basic"]["nova.laravel.com"].username' "$AUTH")
PASS=$(jq -r '.["http-basic"]["nova.laravel.com"].password' "$AUTH")

CODE=$(curl -su "$USER:$PASS" -o /dev/null -w '%{http_code}' \
       --max-time 15 https://nova.laravel.com/api/packages.json)

if [ "$CODE" = 200 ]; then
    echo "✓ Nova 授權有效"
    exit 0
else
    echo "✗✗ Nova 授權驗證失敗（HTTP $CODE）"
    echo "   → 可能已到期，請至 https://nova.laravel.com/settings 確認"
    exit 1
fi
EOF
$ sudo chmod +x /usr/local/bin/check-nova-license

$ sudo tee /etc/cron.d/check-nova-license >/dev/null <<'EOF'
0 9 * * 1 root /usr/local/bin/check-nova-license || \
  mail -s "【警告】Nova 授權可能已到期" it@example.gov.tw
EOF
```

---

## 速查表

### ★★★ auth.json

```json
{
    "http-basic": {
        "nova.laravel.com": {
            "username": "email",
            "password": "★ 授權金鑰（不是登入密碼）"
        }
    }
}
```

```bash
composer config http-basic.nova.laravel.com "email" "key"
chmod 600 auth.json
echo "auth.json" >> .gitignore        # ★★★ 絕對不要 commit
```

### 三種管理方式

```
① 全域 ~/.composer/auth.json          單一伺服器
★★ ② 專案 shared/auth.json + 符號連結   ← 推薦
★★★ ③ COMPOSER_AUTH 環境變數           ← CI/CD

★★ 最好的做法：CI 建置 + 傳產物
   → 正式環境完全不需要 auth.json
```

### ★★★ 部署必做

```bash
ln -sfn shared/auth.json $REL/auth.json      # ★ composer 之前
composer install --no-dev --optimize-autoloader
rm -f $REL/auth.json                          # ★★ 之後移除
php artisan nova:publish                      # ★★★ 沒做 → 版面全爛
php artisan optimize
```

### ★★★ 存取控管

```php
// ★★★ NovaServiceProvider::gate()
Gate::define('viewNova', function ($user) {
    return $user->hasRole('admin') && $user->is_active;
    // ★★★ 絕對不要 return true;
});
```

```nginx
location ^~ /nova     { allow 10.0.0.0/8; deny all; }
location ^~ /nova-api { allow 10.0.0.0/8; deny all; }
location ~ ^/auth\.json$ { deny all; }        # ★★★
```

### 效能

```php
public static function indexQuery(NovaRequest $r, $q): Builder {
    return $q->with(['customer'])->withCount('items');    // ★★ 避免 N+1
}
public static function relatableQuery(NovaRequest $r, $q): Builder {
    return $q->select(['id', 'name']);                    // ★ 只選需要的
}
public static $perPageOptions = [25, 50, 100];
```

### Nova vs Filament

```
              Nova                    Filament
授權          ✗ $99~199/年            ★ MIT 免費
底層          Vue 3 + Inertia         Livewire
請求量        ★ 少                    ★★ 多
WAF 誤判      ★ 少                    ★★ 多
部署複雜度    ★★ 高（auth.json）       ★ 中
```

### ★★★ 四條紅線

```
① auth.json 不進 git（外洩 → 立刻重新產生金鑰）
② viewNova 不能 return true
③ auth.json 不留在 web 可存取的位置
④ /nova 與 /nova-api 限制來源 IP
```

### 驗證

```bash
curl -su "$USER:$KEY" -o /dev/null -w '%{http_code}\n' \
  https://nova.laravel.com/api/packages.json     # ★★ 200 = 授權有效

curl -so /dev/null -w '%{http_code}\n' https://api/vendor/nova/app.js   # ★ 200
curl -so /dev/null -w '%{http_code}\n' https://api/auth.json            # ★★★ 404
sed -n "/define('viewNova'/,/});/p" app/Providers/NovaServiceProvider.php
```

---

## 練習題

> [!question]- 練習 1：`auth.json` 的三種方式
> 1. 用全域 `~/.composer/auth.json` 執行 `composer install`
> 2. **移除它**，改用專案的 `auth.json` → 成功嗎？
> 3. 移除檔案，改用 `COMPOSER_AUTH` 環境變數
> 4. **三種都移除** → `composer install` → **錯誤訊息是什麼？**
> 5. **哪一種最適合 CI/CD？為什麼？**

> [!question]- 練習 2：`nova:publish` ★★★
> 1. 部署時**故意不跑 `nova:publish`**
> 2. 開 `/nova/login` → **看起來怎樣？**
> 3. F12 → Network → **哪些 404？**
> 4. 執行 `php artisan nova:publish` → 重新整理
> 5. **升級 Nova 版本後不重跑** → 會怎樣？
> 6. 把這一步加進部署腳本

> [!question]- 練習 3：`viewNova` Gate ★★★
> 1. **把 `viewNova` 改成 `return true;`**
> 2. 用一個「一般使用者」登入後存取 `/nova` → **進得去嗎？**
> 3. 改成 `return $user->hasRole('admin');` → 再測
> 4. 改成空的 `in_array($user->email, [])` → **誰進得去？**
> 5. **寫一個部署前的自動檢查**（grep 出 `return true`）

> [!question]- 練習 4：授權驗證
> 1. 用正確的授權金鑰執行 `check-nova-license` → 通過
> 2. **故意改錯金鑰** → 執行 → **HTTP code 是什麼？**
> 3. `composer install` 會發生什麼？
> 4. **備份 `vendor/laravel/nova`**
> 5. 移除授權後，用備份的 vendor 部署 → **能跑嗎？**
> 6. **設計你們機關的授權維運流程**

> [!question]- 練習 5：Nova vs Filament 的負載
> 1. 用相同的資料建立 Nova 與 Filament 的列表頁
> 2. `wrk -t2 -c10 -d20s` 分別壓測
> 3. **比較 Requests/sec 與 PHP-FPM 的 CPU**
> 4. 在列表上做 10 次篩選操作，看 `access.log` 的請求數
> 5. **哪一個對伺服器的負載較高？為什麼？**

---

## 小測驗

Q1. **Nova 的授權模式是什麼？到期後會怎樣**？

Q2. **`auth.json` 裡放的密碼是什麼**？

Q3. **`auth.json` 有哪三種管理方式？CI/CD 該用哪一種**？

Q4. **為什麼「CI 建置 + 傳產物」是處理 Nova 授權最乾淨的方式**？

Q5. **`nova:publish` 什麼時候要跑？不跑會怎樣**？

Q6. **Nova 的 `viewNova` 預設是什麼？為什麼比 Filament 安全**？

Q7. **Nova 與 Filament 在底層技術上的差別？對部署有什麼影響**？

Q8. **`auth.json` 誤 commit 到 git 該怎麼處理**？

Q9. **Nova Resource 的 N+1 查詢該怎麼避免**？

Q10. **機關使用 Nova 在長期維運上要注意什麼**？

> [!question]- 測驗答案
> **Q1.** Nova 是**商業軟體，年費訂閱制**：
> **Solo $99/年**（1 個專案）、**Pro $199/年**（無限專案）。
> **授權綁定的是「帳號」不是伺服器**，同一個授權可以部署到多台伺服器。
> **到期後**：
> **已安裝的版本仍然可以正常運作**（不會突然停止），
> **但無法下載更新與新版本**，
> **★★ 也無法用 `composer install` 重新安裝** ——
> 這表示**部署到新伺服器或重建 `vendor/` 時會失敗**。
> 所以到期是「無法部署」而不是「服務中斷」，但仍然是嚴重的維運風險。
>
> **Q2.** **是「授權金鑰（License Key）」，不是 Nova 帳號的登入密碼**。
> 到 `https://nova.laravel.com/settings#licenses` 取得。
> ```json
> {
>     "http-basic": {
>         "nova.laravel.com": {
>             "username": "你的 Nova 帳號 email",
>             "password": "★ 授權金鑰"
>         }
>     }
> }
> ```
> **這是很多人第一次設定時的困惑點** —— 填了登入密碼會一直認證失敗。
> 另外 Nova 4+ 還需要在 `.env` 設 **`NOVA_LICENSE_KEY`**（應用執行時驗證）。
>
> **Q3.** ①**全域 `~/.composer/auth.json`** —— 適合單一伺服器；
> ②**★★ 專案的 `shared/auth.json` + 部署時符號連結** —— 推薦（與 releases 佈局一致）；
> ③**★★★ `COMPOSER_AUTH` 環境變數** —— **CI/CD 該用這一種**。
> ```bash
> export COMPOSER_AUTH='{"http-basic":{"nova.laravel.com":{"username":"...","password":"..."}}}'
> ```
> **CI/CD 用環境變數的好處**：
> **不需要在磁碟上留下檔案**，
> 金鑰存在 CI 平台的 Secrets 中（GitHub Secrets），
> 建置結束後隨著容器銷毀，**不會殘留**。
> GitHub Actions 也可以用 `composer config --global --auth`。
>
> **Q4.** 因為 **`vendor/` 已經在 CI 上安裝好了，
> 部署時只是把打包好的產物傳到伺服器解開** ——
> **正式環境完全不需要 `auth.json`，甚至不需要安裝 composer**。
> **好處**：
> ①**大幅降低授權金鑰外洩的風險**（金鑰只存在於 CI 的 Secrets 中，
> 不會出現在任何一台正式伺服器上）；
> ②**縮小正式環境的攻擊面**（少了 composer 與相關的工具鏈）；
> ③**部署更快**（不用在伺服器上跑 `composer install`）；
> ④**建置可重現**（同一份產物部署到多台，保證完全一致）；
> ⑤**授權到期時仍然可以部署已建置好的產物**。
>
> **Q5.** **兩個時機都要跑**：
> ①**★★★ 每次部署** —— releases 佈局下 `public/` 是全新的目錄，
> 沒有 `vendor/nova/` 這個資產目錄；
> ②**每次 `composer update` 升級 Nova 之後** —— 資產內容變了。
> **不跑的後果**：
> `public/vendor/nova/` 不存在 → **後台的 CSS/JS 全部 404 → 版面完全爛掉**；
> 或者是**舊版本的資產配新版本的 HTML** → 版面錯亂、功能異常。
> **驗證**：
> ```bash
> ls -la public/vendor/nova/
> curl -sI https://api/vendor/nova/app.js
> ```
>
> **Q6.** **Nova 的預設 gate（`nova:install` 產生的）是一個「空的 email 陣列」**：
> ```php
> Gate::define('viewNova', function ($user) {
>     return in_array($user->email, [
>         //
>     ]);
> });
> ```
> **空陣列表示「拒絕所有人」—— 這是安全的預設**。
> **對照 Filament**：不實作 `canAccessPanel` 時，
> **任何已登入的使用者都能進後台**（不安全的預設）。
> **但 Nova 仍要檢查** —— 很多人為了「先能用」會把它改成 **`return true;`**，
> 然後忘了改回來 →
> **任何登入者都能進管理後台**。
> **部署前應該自動檢查**：
> ```bash
> sed -n "/define('viewNova'/,/});/p" NovaServiceProvider.php | grep -q 'return true;'
> ```
>
> **Q7.** **Nova 用 Vue 3 + Inertia（前端渲染）**；
> **Filament 用 Livewire（伺服器端渲染）**。
> **對部署的影響**：
> ①**請求數量** —— Livewire **每次互動都送 POST 回伺服器**，
> Nova 只在需要資料時呼叫 API → **Nova 對 PHP-FPM 的負載明顯較低**；
> ②**★★ WAF 誤判** —— Livewire 的 payload 是序列化的元件狀態
> （含 HTML、SQL 片段），**極容易被 CRS 誤判為 SQLi/XSS**；
> Nova 的請求是**標準的 JSON API**，誤判機率低很多；
> ③**首次載入** —— Nova 要下載整個 Vue app（較大），
> Filament 的首次載入較輕但後續互動較重；
> ④**部署複雜度** —— Nova 需要 `auth.json`（商業授權），Filament 不用。
>
> **Q8.** **三個步驟，第一個最緊急**：
> ①**★★★ 立刻到 `https://nova.laravel.com/settings#licenses` 重新產生授權金鑰** ——
> **假設舊金鑰已經外洩**（特別是公開的 GitHub repo 會被機器人自動掃描），
> 舊金鑰立即作廢；
> ②**用 `git filter-repo` 或 BFG Repo-Cleaner 清除 git 歷史中的 `auth.json`**
> （`git rm` 是不夠的，歷史裡還在），然後 force push；
> ③**更新所有部署環境的 `auth.json`** 與 CI 的 Secrets，
> 並**加上 `.gitignore`**（`echo "auth.json" >> .gitignore`）。
> **檢查是否曾經 commit**：
> ```bash
> git log --all --full-history -- auth.json
> git log --all -p -S 'nova.laravel.com' | head
> ```
>
> **Q9.** **覆寫 `indexQuery()` 與 `detailQuery()` 加上 eager loading**：
> ```php
> public static function indexQuery(NovaRequest $request, $query): Builder
> {
>     return $query->with(['customer'])->withCount('items');
> }
> public static function detailQuery(NovaRequest $request, $query): Builder
> {
>     return $query->with(['customer', 'items.product']);
> }
> ```
> **還有一個常被忽略的**：**`relatableQuery()`** ——
> 當 `BelongsTo` 欄位需要列出可選項目時，
> 預設會**查詢整張表的所有欄位**，大表上非常慢：
> ```php
> public static function relatableQuery(NovaRequest $request, $query): Builder
> {
>     return $query->select(['id', 'name']);      // ★ 只選需要的欄位
> }
> ```
> 加上 `public static $perPageOptions = [25, 50, 100];`（不要讓使用者選太大）。
>
> **Q10.** ①**★★ 授權帳號的保管** ——
> 用**機關的共用信箱**註冊（不要用承辦人的個人 email），
> 密碼與授權金鑰存在**密碼管理系統**，**承辦人離職時要交接**；
> ②**★★ 到期提醒** —— 到期後**無法 `composer install`**，
> 到期前 **60 天就要開始編列預算**，設定行事曆提醒，
> 並用腳本定期驗證授權有效性；
> ③**★★ 備份 `vendor/laravel/nova`** ——
> 萬一授權到期又需要緊急部署，有 vendor 的備份就能撐過去：
> ```bash
> tar czf nova-vendor-backup.tar.gz vendor/laravel/nova
> ```
> ④**★ 評估替代方案** —— **Filament 是 MIT 授權（免費）**，
> 功能上大致相當且社群更活躍，可以評估「遷移成本 vs 每年的授權費」。
> 另外要注意國外刷卡與發票的會計流程（有些機關不接受）。

---

## 延伸閱讀

- [[130-01-04-05-guide-Laravel-Filament部署]] — 免費的替代方案
- [[130-01-04-07-guide-Laravel-正式環境安全檢查表]] — 上線前的完整檢查
- [[130-01-04-04-guide-Laravel-快取最佳化與部署流程]] — 部署流程整合
- [[130-01-06-guide-部署-部署自動化]] — CI/CD 的完整設定
- [[060-03-01-04-guide-Composer-套件管理]] — composer 的私有套件庫
- [[090-03-02-guide-應用安全-應用層安全]] — 後台安全的通用原則
