---
title: "Laravel 快取最佳化與部署流程"
desc: "config/route/view 快取、OPcache、Octane 與零停機部署腳本"
aliases: [config:cache, optimize, OPcache, Octane, 零停機部署, deploy]
tags: [群組/實務案例, 主題/部署, 主題/Laravel, 主題/LXMP]
category: 專案部署實戰
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[130-01-04-03-guide-Laravel-佇列排程與Supervisor]]"]
updated: 2026-08-28
---

# Laravel 快取最佳化與部署流程

> [!abstract] 這篇你會學到
> - **★★★ `config:cache` 與 `env()` 的致命陷阱**
> - `route:cache` / `view:cache` / `event:cache` 的效益與限制
> - **OPcache** 與部署時的失效處理
> - **應用層快取**（`Cache::remember`、標籤、失效策略）
> - **Laravel Octane**（進階，注意事項很多）
> - **★★★ 完整的零停機部署腳本**（可直接使用）
> - **資料庫遷移**的安全做法

## 前置知識

- [[130-01-04-03-guide-Laravel-佇列排程與Supervisor]] — 佇列與排程
- [[130-01-04-02-guide-Laravel-Nginx與PHP-FPM設定]] — FPM 與 OPcache

---

## ★★★ `config:cache` 與 `env()`

```bash
$ php artisan config:cache
   INFO  Configuration cached successfully.

# ★ 產生 bootstrap/cache/config.php（★ 把所有 config/*.php 合併成一個陣列）
$ ls -la bootstrap/cache/
-rw-rw---- 1 deploy www-data  42183 Aug 28 15:30 config.php
-rw-rw---- 1 deploy www-data 218442 Aug 28 15:30 routes-v7.php
-rw-rw---- 1 deploy www-data   1204 Aug 28 15:30 packages.php
-rw-rw---- 1 deploy www-data    892 Aug 28 15:30 services.php
```

> [!danger] `config:cache` 之後 `env()` 一律回傳 `null` ★★★
> ```
> ★★★ 這是 Laravel 最常見、也最難 debug 的部署陷阱
>
> 執行 config:cache 後：
>   · Laravel 【完全不再讀取 .env 檔案】
>   · ★★★ 所有 env() 呼叫都回傳【null】（除非有第二個參數的預設值）
>
> ❌ 錯誤（在 config/ 以外的地方用 env）：
>   // app/Services/PaymentService.php
>   $key = env('PAYMENT_API_KEY');        // ★★★ config:cache 後是 null
>
>   // routes/web.php
>   if (env('APP_DEBUG')) { ... }         // ★★★ 永遠 false
>
>   // 任何 Controller / Model / Middleware
>   $url = env('EXTERNAL_API_URL');       // ★★★ null
>
> ✅ ★★★ 正確：只在 config/*.php 裡用 env()，其他地方用 config()
>   // config/services.php
>   'payment' => ['key' => env('PAYMENT_API_KEY')],
>
>   // 程式碼中
>   $key = config('services.payment.key');    // ✓
>
> ★★ 症狀：
>   · 本機開發完全正常（★ 本機通常沒跑 config:cache）
>   · 部署到正式環境後功能壞掉
>   · 錯誤是「null given」「Undefined」之類的
>   · ★ 最詭異的是：php artisan config:clear 之後又好了
> ```

```bash
# ★★★ 掃描專案中不當使用 env() 的地方
$ grep -rn "env(" app/ routes/ database/ resources/ \
    --include='*.php' | grep -v '^config/' | grep -v 'vendor/'
app/Services/PaymentService.php:23:        $key = env('PAYMENT_API_KEY');    # ★★★ 有問題
routes/web.php:15:if (env('APP_DEBUG')) {                                     # ★★★ 有問題

# ★★ 加進 CI 檢查
$ ! grep -rn "env(" app/ routes/ database/ --include='*.php' | grep -qv 'config/' || \
    { echo "✗✗ 發現 config/ 以外的 env() 呼叫"; exit 1; }
```

```php
<?php
// ★★ 正確的做法：所有設定都經過 config/
// config/services.php
return [
    'payment' => [
        'key'    => env('PAYMENT_API_KEY'),
        'secret' => env('PAYMENT_API_SECRET'),
        'url'    => env('PAYMENT_API_URL', 'https://api.payment.example'),
        'timeout'=> (int) env('PAYMENT_TIMEOUT', 30),
    ],
    'internal' => [
        'base_url' => env('INTERNAL_API_BASE', 'http://127.0.0.1:9000'),
        'ca_bundle'=> env('INTERNAL_CA_BUNDLE', '/etc/ssl/certs/ca-chain.crt'),
    ],
];
```

```php
<?php
// ★ 程式碼中一律用 config()
class PaymentService
{
    public function __construct(
        private readonly string $key = '',
    ) {
        $this->key = config('services.payment.key');    // ✓
    }
}
```

---

## 四種快取指令 ★★

| 指令 | 產物 | 效益 | ★★ 限制 |
| --- | --- | --- | --- |
| **`config:cache`** ★★★ | `bootstrap/cache/config.php` | 省下解析所有 config 檔 | **`env()` 失效** |
| **`route:cache`** ★★ | `bootstrap/cache/routes-v7.php` | 大專案省 50~100ms | **路由中不能有 Closure** |
| `view:cache` | `storage/framework/views/*.php` | 首次請求不用編譯 Blade | 無 |
| `event:cache` | `bootstrap/cache/events.php` | 省下掃描 Listener | 無 |

```bash
# ═══ ★★ 一次全做（Laravel 的包裝指令）═══
$ php artisan optimize
   INFO  Caching the framework bootstrap files.
  config ......................................... 12ms DONE
  events ......................................... 8ms DONE
  routes ......................................... 42ms DONE
  views .......................................... 318ms DONE

# ★ 等同於
$ php artisan config:cache
$ php artisan event:cache
$ php artisan route:cache
$ php artisan view:cache

# ═══ 清除 ═══
$ php artisan optimize:clear
# 等同於 config:clear + route:clear + view:clear + event:clear + cache:clear + compiled
```

> [!danger] `route:cache` 遇到 Closure 會失敗 ★★
> ```php
> // ❌ routes/web.php
> Route::get('/hello', function () {          // ★★ Closure
>     return 'Hello';
> });
>
> // ★ php artisan route:cache 會報：
> //   Your route files contain closures, which cannot be serialized.
>
> // ✅ 改成 Controller
> Route::get('/hello', [HelloController::class, 'index']);
>
> // ✅ 或用 invokable controller
> Route::get('/hello', HelloController::class);
> ```
>
> ```
> ★★ 同樣的限制也適用於：
>   · Route::middleware(function () { ... })   ← Closure middleware
>   · Route 的參數綁定用 Closure
>
> ★ 但這些是可以的：
>   · Schedule::call(fn() => ...)              ← ★ 排程不受影響
>   · dispatch(function () { ... })            ← ★ 佇列的 Closure job 可以
> ```

```bash
# ★★ 找出所有 Closure 路由
$ php artisan route:list --json 2>/dev/null | \
    jq -r '.[] | select(.action == "Closure") | "\(.method)\t\(.uri)"'
GET|HEAD	hello
GET|HEAD	debug/test

# ★ 或直接嘗試
$ php artisan route:cache
```

---

## OPcache ★★★

```ini
; ★★ 正式環境的 OPcache 設定（php-fpm pool 或 php.ini）
opcache.enable = 1
opcache.enable_cli = 0                    ; ★ CLI 不需要（除非用 Octane）
opcache.memory_consumption = 256          ; ★★ MB，大專案要更多
opcache.interned_strings_buffer = 32      ; ★ MB
opcache.max_accelerated_files = 20000     ; ★★ 要大於專案的檔案數
opcache.validate_timestamps = 0           ; ★★★ 正式環境設 0
opcache.revalidate_freq = 0
opcache.save_comments = 1                 ; ★★★ Laravel 必須（Attributes/DocBlock）
opcache.enable_file_override = 0
opcache.max_wasted_percentage = 10
opcache.jit = tracing                     ; ★ PHP 8 的 JIT
opcache.jit_buffer_size = 64M
opcache.preload = /var/www/api/current/preload.php    ; ★ 可選（見下方）
opcache.preload_user = www-data
```

> [!danger] `validate_timestamps=0` 的代價 ★★★
> ```
> validate_timestamps = 1（★ 預設）
>   → 每次請求檢查檔案的 mtime
>     → ★ 檔案變了自動重新編譯
>     → ★★ 但每個檔案每次請求都要 stat() → 有效能成本
>
> ★★ validate_timestamps = 0（正式環境）
>   → 【完全不檢查】→ 效能最好
>   → ★★★ 但部署新版後【必須手動讓 OPcache 失效】
>     → 否則【一直執行舊程式碼】
>
> ★★★ 三種讓 OPcache 失效的方式：
>   ① systemctl reload php8.3-fpm      ← ★★ 最簡單可靠（★ graceful，不斷線）
>   ② opcache_reset()                  ← ★ 需要一個端點，且【只影響呼叫它的那個 worker】
>   ③ ★★ 用 $realpath_root + releases 佈局
>      → 新版的檔案路徑不同 → OPcache 的 key 不同 → 自動生效
>      → ★ 但舊的快取還佔著記憶體（會被 LRU 淘汰）
>
> ★★ 建議 ③ + ① 一起做
> ```

```bash
# ★★ 檢查 OPcache 狀態（★ 注意 CLI 與 FPM 是分開的）
$ cat > /var/www/api/current/public/_opcache.php <<'PHP'
<?php
// ★★ 一定要限制存取
if (!in_array($_SERVER['REMOTE_ADDR'] ?? '', ['127.0.0.1', '::1'])) {
    http_response_code(403); exit('Forbidden');
}
$s = opcache_get_status(false);
$c = opcache_get_configuration();
header('Content-Type: application/json');
echo json_encode([
    'enabled'      => $s['opcache_enabled'],
    'hit_rate'     => round($s['opcache_statistics']['opcache_hit_rate'], 2),
    'memory_used'  => round($s['memory_usage']['used_memory'] / 1048576, 1) . ' MB',
    'memory_free'  => round($s['memory_usage']['free_memory'] / 1048576, 1) . ' MB',
    'wasted'       => round($s['memory_usage']['current_wasted_percentage'], 2) . '%',
    'cached_files' => $s['opcache_statistics']['num_cached_scripts'],
    'max_files'    => $c['directives']['opcache.max_accelerated_files'],
    'restarts'     => $s['opcache_statistics']['oom_restarts']
                    + $s['opcache_statistics']['hash_restarts']
                    + $s['opcache_statistics']['manual_restarts'],
    'validate_ts'  => $c['directives']['opcache.validate_timestamps'],
], JSON_PRETTY_PRINT);
PHP

$ curl -s http://127.0.0.1/_opcache.php | jq
{
  "enabled": true,
  "hit_rate": 99.87,                # ★★ 應該 >99%
  "memory_used": "142.3 MB",
  "memory_free": "113.7 MB",
  "wasted": "2.14%",                # ★ >10% 表示需要 reset
  "cached_files": 4823,
  "max_files": 20000,               # ★★ cached_files 接近 max 就要調高
  "restarts": 0,                    # ★★ >0 表示記憶體不夠
  "validate_ts": false
}

$ sudo rm /var/www/api/current/public/_opcache.php     # ★★★ 用完刪掉
```

> [!warning] OPcache 記憶體不足的徵兆 ★★
> ```
> ★ 三個要看的指標：
>   ① hit_rate < 95%        → 快取一直被淘汰
>   ② restarts > 0          → ★★ OOM restart（記憶體滿了被迫重置）
>   ③ cached_files 接近 max_accelerated_files
>
> ★★ 解法：
>   opcache.memory_consumption 調大（256 → 512）
>   opcache.max_accelerated_files 調大（★ 要大於實際檔案數）
>
> ★ 算出實際檔案數：
>   find /var/www/api/current -name '*.php' | wc -l
>   → ★ 設成這個數字的 1.5 倍以上（要用質數更好）
> ```

```bash
$ find /var/www/api/current -name '*.php' ! -path '*/node_modules/*' | wc -l
8432
# ★ max_accelerated_files 設 16229（★ 大於 8432*1.5 的質數）
```

---

## 應用層快取 ★★

```php
<?php
use Illuminate\Support\Facades\Cache;

// ═══ ★★ 基本 ═══
$users = Cache::remember('users:active', 300, function () {
    return User::where('active', true)->get();
});

// ★ 永久快取（★ 直到手動清除）
$settings = Cache::rememberForever('settings', fn () => Setting::pluck('value', 'key'));

// ═══ ★★ 標籤（★ 只有 redis / memcached 支援）═══
Cache::tags(['users', 'reports'])->remember('report:monthly', 3600, fn () => ...);
Cache::tags(['users'])->flush();      // ★★ 只清掉有 users 標籤的

// ═══ ★★★ 防雷霆群集（cache stampede）═══
// ★ 快取過期的瞬間，大量請求同時打資料庫
$value = Cache::flexible('expensive-data', [300, 600], function () {
    return expensiveQuery();
});
// ★★ Laravel 11.23+：300 秒內直接用快取，
//    300~600 秒之間【先回傳舊的，同時在背景更新】（stale-while-revalidate）

// ★ 或用 lock 手動實作
$value = Cache::get('key');
if ($value === null) {
    $lock = Cache::lock('key:lock', 10);
    if ($lock->get()) {
        try {
            $value = expensiveQuery();
            Cache::put('key', $value, 300);
        } finally { $lock->release(); }
    } else {
        // ★ 別人正在算，等一下再讀
        $lock->block(5);
        $value = Cache::get('key');
    }
}
```

> [!danger] 快取失效的策略 ★★
> ```
> ★★ 三種常見的失效方式：
>
> ① ★ 時間過期（TTL）—— 最簡單
>    Cache::remember('key', 300, ...)
>    → ★ 資料最多舊 300 秒
>    → 適合：可以容忍短暫不一致的資料
>
> ② ★★ 事件驅動失效 —— 最即時
>    // Model 的 observer
>    static::saved(fn ($m) => Cache::forget("user:{$m->id}"));
>    static::deleted(fn ($m) => Cache::forget("user:{$m->id}"));
>    → ★★ 但要記得【每一個】會影響快取的地方都要清
>    → ★ 漏掉一個就會有髒資料
>
> ③ ★★★ Cache key 含版本 —— 最可靠
>    $version = Cache::get('users:version', 1);
>    Cache::remember("users:list:v{$version}", 3600, ...);
>    // 資料變更時：Cache::increment('users:version');
>    → ★★ 舊的 key 自然過期，不用一個一個清
>    → ★ 適合關聯複雜、難以精確失效的情況
> ```

```php
<?php
// ★★ Model observer 做快取失效
namespace App\Observers;

class UserObserver
{
    public function saved(User $user): void
    {
        Cache::forget("user:{$user->id}");
        Cache::tags(['users'])->flush();          // ★ 需要 redis
        Cache::increment('users:version');        // ★★ 版本化
    }

    public function deleted(User $user): void
    {
        $this->saved($user);
    }
}
```

> [!warning] `Cache::tags()` 的限制 ★★
> ```
> ★ 只有 redis、memcached、dynamodb、array 支援
>   → file、database driver 【不支援】→ ★★ 拋出 BadMethodCallException
>
> ★★ Redis 的 tags 實作有成本：
>   · 每個 tag 維護一個 set
>   · flush 時要遍歷該 set
>   · ★ tag 太多或成員太多時效能會下降
>
> ★★ 大量資料的情況，用【版本化的 key】比 tags 更有效率
> ```

---

## Laravel Octane（進階）★★

```bash
$ composer require laravel/octane
$ php artisan octane:install --server=frankenphp     # ★ 或 swoole / roadrunner
```

```
★★ Octane 讓 Laravel 【常駐記憶體】，不用每次請求都啟動框架
   → ★ 效能可以提升 2~10 倍

★★★ 但代價很大 —— 程式碼必須是「無狀態」的
```

> [!danger] Octane 的五個致命陷阱 ★★★
> ```
> ★★ Octane 下，Laravel 的 Application 實例【跨請求共用】
>
> ① ★★★ 【靜態屬性會殘留】
>      class Foo { public static array $cache = []; }
>      → ★ 第一個請求塞的資料，第二個請求還在
>        → ★★★ 【使用者 A 的資料被使用者 B 看到】
>
> ② ★★★ 【Singleton 綁定的物件會殘留狀態】
>      $this->app->singleton(Service::class, ...);
>      → 若 Service 內部有 $this->currentUser
>        → ★★★ 跨請求洩漏
>      → ★ 用 $this->app->bind()（每次新建）
>      → ★ 或在 Octane 的 flush 事件中重置
>
> ③ ★★ 【全域變數與 static 變數】
>      function foo() { static $x = null; ... }
>
> ④ ★★ 【記憶體洩漏會累積】
>      → 傳統 FPM 每個請求結束就釋放
>      → Octane 是長駐 → ★ 洩漏會一直累積
>      → 必須設 --max-requests
>
> ⑤ ★ 【某些套件不相容】
>      → 依賴請求生命週期的套件可能出問題
>      → ★★ 上線前要完整測試
>
> ★★★ 建議：
>   · 內部管理系統：★ 不需要 Octane（流量不大）
>   · ★★ 若要用：先在 staging 跑一個月，仔細測試
>   · ★ 一定要設 --max-requests=500
> ```

```php
<?php
// ★★ Octane 的 flush 設定（config/octane.php）
'flush' => [
    // ★ 每個請求後重置這些 singleton
    \App\Services\CurrentUserService::class,
    \App\Services\TenantService::class,
],

'warm' => [
    // ★ 這些保持 warm（不重置）
    ...Octane::defaultServicesToWarm(),
],

'listeners' => [
    RequestReceived::class => [
        ...Octane::prepareApplicationForNextOperation(),
        ...Octane::prepareApplicationForNextRequest(),
    ],
    RequestTerminated::class => [
        // ★★ 自訂的清理
        \App\Listeners\FlushStaticState::class,
    ],
],
```

```ini
# ★ Supervisor 管理 Octane
[program:octane]
command=php /var/www/api/current/artisan octane:start
    --server=frankenphp --host=127.0.0.1 --port=8000
    --workers=4 --max-requests=500
directory=/var/www/api/current
autostart=true
autorestart=true
user=www-data
stopwaitsecs=60
stopsignal=TERM
```

```bash
# ★★★ 部署後必須重載
$ php artisan octane:reload         # ★ 優雅重載 worker
# ★ 或 sudo supervisorctl restart octane
```

---

## ★★★ 完整的零停機部署腳本

```bash
#!/usr/bin/env bash
# /usr/local/bin/deploy-laravel —— Laravel 零停機部署
# 用法：deploy-laravel [branch]
#      SKIP_MIGRATE=1 deploy-laravel
set -euo pipefail

# ═══════ 設定 ═══════
APP="${APP:-/var/www/api}"
REPO="${REPO:-git@github.com:Information-Study/laravel-api.git}"
BRANCH="${1:-${BRANCH:-main}}"
SITE="${SITE:-https://api.example.gov.tw}"
PHP_V="${PHP_V:-8.3}"
KEEP="${KEEP:-5}"
BACKUP_DIR="${BACKUP_DIR:-/backup/db}"
SKIP_MIGRATE="${SKIP_MIGRATE:-0}"
REL="$APP/releases/$(date +%Y%m%d-%H%M%S)"

c(){ echo -e "\033[36m[$(date +%T)]\033[0m $*"; }
ok(){ echo -e "\033[32m    ✓ $*\033[0m"; }
err(){ echo -e "\033[31m    ✗ $*\033[0m"; }
die(){ echo -e "\033[31m✗✗ $*\033[0m" >&2; exit 1; }

# ★ 避免同時部署
exec 200>/var/lock/deploy-laravel.lock
flock -n 200 || die "已有部署在進行中"

START=$(date +%s)
c "═══════ Laravel 部署（$BRANCH）═══════"

# ══════ 【0】前置檢查 ══════
c "【0】前置檢查"
[ "$(whoami)" = deploy ] || die "必須用 deploy 使用者執行"
[ -f "$APP/shared/.env" ] || die "找不到 $APP/shared/.env"
grep -q '^APP_ENV=production'  "$APP/shared/.env" || die "★★ APP_ENV 不是 production"
grep -q '^APP_DEBUG=false'     "$APP/shared/.env" || die "★★★ APP_DEBUG 不是 false"
grep -q '^APP_KEY=base64:'     "$APP/shared/.env" || die "★★ APP_KEY 未設定"
df -h "$APP" | tail -1 | awk '{gsub("%","",$5); if ($5 > 90) exit 1}' || \
  die "磁碟使用率超過 90%"
ok "通過"

# ══════ 【1】★★ 資料庫備份 ══════
if [ "$SKIP_MIGRATE" != 1 ]; then
    c "【1】★★ 資料庫備份"
    mkdir -p "$BACKUP_DIR"
    DB_NAME=$(grep '^DB_DATABASE=' "$APP/shared/.env" | cut -d= -f2-)
    DB_USER=$(grep '^DB_USERNAME=' "$APP/shared/.env" | cut -d= -f2-)
    DB_PASS=$(grep '^DB_PASSWORD=' "$APP/shared/.env" | cut -d= -f2-)
    BAK="$BACKUP_DIR/${DB_NAME}-$(date +%Y%m%d%H%M%S).sql.gz"

    MYSQL_PWD="$DB_PASS" mysqldump -u "$DB_USER" \
        --single-transaction --routines --triggers --events \
        --no-tablespaces "$DB_NAME" | gzip > "$BAK"
    ok "$BAK（$(du -h "$BAK" | cut -f1)）"

    # ★ 清理舊備份（保留 14 天）
    find "$BACKUP_DIR" -name '*.sql.gz' -mtime +14 -delete
else
    c "【1】跳過資料庫備份（SKIP_MIGRATE=1）"
fi

# ══════ 【2】clone ══════
c "【2】clone"
mkdir -p "$REL"
git clone --depth 1 --branch "$BRANCH" --single-branch "$REPO" "$REL" 2>&1 | sed 's/^/    /'
COMMIT=$(cd "$REL" && git rev-parse --short HEAD)
MSG=$(cd "$REL" && git log -1 --pretty=%s)
AUTHOR=$(cd "$REL" && git log -1 --pretty=%an)
ok "$COMMIT — $MSG（$AUTHOR）"
rm -rf "$REL/.git"

cd "$REL"

# ══════ 【3】連結 shared ══════
c "【3】連結 shared"
ln -sfn "$APP/shared/.env" "$REL/.env"
rm -rf "$REL/storage"
ln -sfn "$APP/shared/storage" "$REL/storage"
[ -d "$APP/shared/public/uploads" ] && ln -sfn "$APP/shared/public/uploads" "$REL/public/uploads"
ok "完成"

# ══════ 【4】composer ══════
c "【4】composer install"
COMPOSER_MEMORY_LIMIT=-1 composer install \
    --no-dev --optimize-autoloader --no-interaction --prefer-dist --no-progress \
    2>&1 | tail -5 | sed 's/^/    /'

# ★★ 弱點檢查（★ 不中斷部署，只警告）
if ! composer audit --no-interaction >/dev/null 2>&1; then
    err "⚠ composer audit 發現已知弱點（部署繼續，但請盡快處理）"
    composer audit --format=plain 2>/dev/null | head -10 | sed 's/^/      /'
fi

# ══════ 【5】前端建置 ══════
if [ -f "$REL/package.json" ]; then
    c "【5】前端建置"
    npm ci --no-audit --no-fund 2>&1 | tail -3 | sed 's/^/    /'
    NODE_OPTIONS="--max-old-space-size=4096" npm run build 2>&1 | tail -8 | sed 's/^/    /'

    # ★★ 秘密掃描
    if grep -rlE 'sk_live|-----BEGIN|AKIA[0-9A-Z]{16}' "$REL/public/build/" 2>/dev/null; then
        die "★★★ 前端建置產物中發現秘密"
    fi
    find "$REL/public/build" -name '*.map' -delete 2>/dev/null || true
    rm -rf "$REL/node_modules"
    ok "完成"
fi

# ══════ 【6】★★ 資料庫遷移 ══════
if [ "$SKIP_MIGRATE" != 1 ]; then
    c "【6】★★ 資料庫遷移"
    PENDING=$(php artisan migrate:status --pending 2>/dev/null | grep -c 'Pending' || echo 0)
    if [ "$PENDING" -gt 0 ]; then
        c "    有 $PENDING 個待執行的遷移："
        php artisan migrate:status 2>/dev/null | grep 'Pending' | sed 's/^/      /'
        php artisan migrate --force --no-interaction 2>&1 | sed 's/^/    /'
        ok "完成"
    else
        ok "沒有待執行的遷移"
    fi
fi

# ══════ 【7】★★★ 快取最佳化 ══════
c "【7】★★★ 快取最佳化"
php artisan config:cache  2>&1 | sed 's/^/    /'
php artisan event:cache   2>&1 | sed 's/^/    /'
php artisan route:cache   2>&1 | sed 's/^/    /' || \
  err "⚠ route:cache 失敗（★ 檢查路由中有沒有 Closure）"
php artisan view:cache    2>&1 | sed 's/^/    /'
php artisan storage:link  2>&1 | sed 's/^/    /' || true
ok "完成"

# ══════ 【8】★★ 權限 ══════
c "【8】★★ 權限"
find "$REL" -type d -exec chmod 750 {} \;
find "$REL" -type f -exec chmod 640 {} \;
chmod 755 "$REL/artisan"
chmod -R 770 "$REL/bootstrap/cache"
chmod -R 770 "$APP/shared/storage"
chown -R deploy:www-data "$REL"
ok "完成"

# ══════ 【9】★★★ 切換前的煙霧測試 ══════
c "【9】★★★ 煙霧測試"
FAIL=0
s(){ printf '    %-40s ' "$1"; if eval "$2" >/dev/null 2>&1; then echo "✓"; else echo "✗"; FAIL=1; fi; }

s "artisan 可執行"        "php '$REL/artisan' --version"
s "★ 設定快取存在"         "[ -f '$REL/bootstrap/cache/config.php' ]"
s "★ 路由快取存在"         "[ -f '$REL/bootstrap/cache/routes-v7.php' ]"
s "vendor/autoload 存在"  "[ -f '$REL/vendor/autoload.php' ]"
s "public/index.php 存在" "[ -f '$REL/public/index.php' ]"
s "index.php 語法正確"    "php -l '$REL/public/index.php'"
s "★★ 資料庫可連線"        "php '$REL/artisan' db:show"
s "★ 快取可用"            "php '$REL/artisan' tinker --execute='Cache::put(\"__d\",1,5); exit(Cache::get(\"__d\")===1?0:1);'"
s "★★ 沒有開發相依"        "! grep -q 'phpunit' '$REL/vendor/composer/installed.json' 2>/dev/null"

[ "$FAIL" -eq 0 ] || die "★★ 煙霧測試失敗，不切換（舊版本仍在服務）"
ok "全部通過"

# ══════ 【10】★★★ 原子切換 ══════
PREV=$(readlink "$APP/current" 2>/dev/null || echo "")
c "【10】★★★ 原子切換"
ln -sfn "$REL" "$APP/current.tmp"
mv -Tf "$APP/current.tmp" "$APP/current"
ok "$(basename "${PREV:-無}") → $(basename "$REL")"

# ══════ 【11】★★★ 重載服務 ══════
c "【11】★★★ 重載服務"

# ★★ ① PHP-FPM（讓 OPcache 失效）
sudo systemctl reload "php$PHP_V-fpm"
ok "php$PHP_V-fpm reloaded（★ OPcache 已失效）"

# ★★ ② Nginx
sudo nginx -t 2>&1 | sed 's/^/    /' && sudo systemctl reload nginx
ok "nginx reloaded"

# ★★★ ③ Queue worker（最常被忘記）
php artisan queue:restart 2>/dev/null || true
sleep 3
if sudo supervisorctl status laravel-workers: >/dev/null 2>&1; then
    sudo supervisorctl restart laravel-workers: 2>&1 | sed 's/^/    /'
    ok "queue workers restarted"
elif php artisan horizon:status >/dev/null 2>&1; then
    php artisan horizon:terminate
    ok "horizon terminated（★ Supervisor 會重啟）"
fi

# ★ ④ Octane（若有用）
php artisan octane:reload 2>/dev/null && ok "octane reloaded" || true

# ══════ 【12】★★★ 部署後驗證 ══════
c "【12】★★★ 驗證"
sleep 3
FAIL=0
v(){ printf '    %-42s ' "$1"; if eval "$2" >/dev/null 2>&1; then echo "✓"; else echo "✗"; FAIL=1; fi; }

v "首頁 / 健康檢查 200" \
  "[ \"\$(curl -so /dev/null -w '%{http_code}' --max-time 20 $SITE/up)\" = 200 ] || \
   [ \"\$(curl -so /dev/null -w '%{http_code}' --max-time 20 $SITE/)\" = 200 ]"
v "★★ .env 無法存取" \
  "[ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/.env)\" != 200 ]"
v "★★ PathInfo 防護" \
  "[ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/storage/x.jpg/y.php)\" != 200 ]"
v "★ HSTS 標頭" \
  "curl -sI $SITE/ | grep -qi strict-transport-security"
v "★ 不洩漏 PHP 版本" \
  "! curl -sI $SITE/ | grep -qi x-powered-by"

# ★★ 佇列驗證
php artisan tinker --execute='dispatch(function () {
  \Illuminate\Support\Facades\Log::info("__deploy_ok__"); })->onQueue("default");' >/dev/null 2>&1
QOK=0
for i in $(seq 1 20); do
    grep -q '__deploy_ok__' "$APP/shared/storage/logs/laravel-$(date +%Y-%m-%d).log" 2>/dev/null && { QOK=1; break; }
    sleep 1
done
printf '    %-42s ' "★★★ 佇列 worker 運作中"
[ "$QOK" = 1 ] && echo "✓" || { echo "✗"; FAIL=1; }

# ★ 錯誤日誌檢查
NEWERR=$(find "$APP/shared/storage/logs" -name '*.log' -newermt '-2 minutes' \
         -exec grep -c 'production.ERROR' {} + 2>/dev/null | awk -F: '{s+=$NF} END{print s+0}')
printf '    %-42s %s\n' "最近 2 分鐘的 ERROR 數" "$NEWERR"
[ "${NEWERR:-0}" -gt 5 ] && err "⚠ 錯誤偏多，請檢查"

# ══════ 【13】失敗回退 ══════
if [ "$FAIL" != 0 ]; then
    err "✗✗ 驗證失敗 —— 自動回退"
    tail -30 "$APP/shared/storage/logs/laravel-$(date +%Y-%m-%d).log" 2>/dev/null | sed 's/^/      /'
    if [ -n "$PREV" ]; then
        ln -sfn "$PREV" "$APP/current.tmp"
        mv -Tf "$APP/current.tmp" "$APP/current"
        sudo systemctl reload "php$PHP_V-fpm"
        php artisan queue:restart 2>/dev/null || true
        sudo supervisorctl restart laravel-workers: 2>/dev/null || true
        ok "已回退到 $(basename "$PREV")"
        cat <<EOF

  ★★ 注意：程式碼已回退，但【資料庫遷移沒有回退】
     若這次有 migration 且是破壞性的（DROP COLUMN 等）：
       cd $PREV && php artisan migrate:rollback --step=1
     ★ 或從備份還原：
       zcat $BAK | mysql -u <user> -p <db>
EOF
    fi
    exit 1
fi

# ══════ 【14】清理 ══════
c "【14】清理（保留 $KEEP 個）"
cd "$APP/releases"
ls -1dt */ 2>/dev/null | tail -n +$((KEEP+1)) | while read -r d; do
    echo "    刪除 $d"; rm -rf "$d"
done

# ══════ 完成 ══════
ELAPSED=$(( $(date +%s) - START ))
c "═══════ ✓ 部署完成 ═══════"
cat <<EOF
  版本    ：$COMMIT
  訊息    ：$MSG
  耗時    ：${ELAPSED} 秒
  目錄    ：$REL
  網址    ：$SITE

  ★ 回退指令：
    sudo -u deploy rollback-laravel
EOF

# ★ 記錄部署歷史
echo "$(date -Is)|$COMMIT|$BRANCH|$MSG|${ELAPSED}s|${SUDO_USER:-$USER}" >> "$APP/shared/deploy.log"
```

```bash
$ sudo chmod +x /usr/local/bin/deploy-laravel
$ sudo -u deploy deploy-laravel main
$ sudo -u deploy SKIP_MIGRATE=1 deploy-laravel hotfix/urgent
```

### 回退腳本

```bash
#!/usr/bin/env bash
# /usr/local/bin/rollback-laravel
set -euo pipefail
APP="${APP:-/var/www/api}"
PHP_V="${PHP_V:-8.3}"
SITE="${SITE:-https://api.example.gov.tw}"

CUR=$(readlink "$APP/current")
echo "═══ 回退 ═══"
echo "  目前：$(basename "$CUR")"
echo
echo "  可用版本："
cd "$APP/releases"
ls -1dt */ | head -8 | sed 's|/$||' | nl -w4 -s'. ' | sed 's/^/  /'
echo
echo "  ── 部署歷史 ──"
tail -8 "$APP/shared/deploy.log" 2>/dev/null | \
  awk -F'|' '{printf "  %s  %s  %s\n", $1, $2, substr($4,1,50)}'
echo

TARGET="${1:-$(ls -1dt */ | sed 's|/$||' | sed -n '2p')}"
TARGET="$APP/releases/$TARGET"
[ -d "$TARGET" ] || { echo "✗ 找不到 $TARGET"; exit 1; }
[ "$TARGET" = "$CUR" ] && { echo "✗ 與目前相同"; exit 1; }

echo "  回退到：$(basename "$TARGET")"
read -rp "  確認？(yes/no) " a; [ "$a" = yes ] || exit 0

ln -sfn "$TARGET" "$APP/current.tmp"
mv -Tf "$APP/current.tmp" "$APP/current"

sudo systemctl reload "php$PHP_V-fpm"
sudo nginx -t && sudo systemctl reload nginx
php "$APP/current/artisan" queue:restart 2>/dev/null || true
sudo supervisorctl restart laravel-workers: 2>/dev/null || true

sleep 3
C=$(curl -so /dev/null -w '%{http_code}' --max-time 15 "$SITE/" || echo 000)
echo "  HTTP $C"
[ "$C" = 200 ] && echo "  ✓ 回退成功" || echo "  ✗ 仍有問題"

cat <<'EOF'

  ★★★ 注意：資料庫遷移【沒有】回退
     加欄位／加表 → 安全（舊版忽略）
     ★★ 刪欄位／改型別 → 危險，需要：
       php artisan migrate:rollback --step=1
       或從備份還原
EOF
```

---

## 資料庫遷移的安全做法 ★★

> [!danger] 向後相容的遷移（expand-contract）★★★
> ```
> ★★ 原則：新版程式碼與舊版程式碼【都要能跑】
>    → 這樣才能安全地回退
>
> ═══ 安全的遷移（可以直接做）═══
>   · 新增資料表
>   · 新增欄位（★ 有預設值或允許 NULL）
>   · 新增索引（★ 大表要注意鎖定時間）
>
> ═══ ★★★ 危險的遷移（必須分兩次部署）═══
>   · DROP COLUMN / DROP TABLE
>   · 改變欄位型別
>   · 重新命名欄位
>   · 加 NOT NULL 且沒有預設值的欄位
>
> ★★ 分兩次部署的做法（以「刪除欄位」為例）：
>   【第一次部署】
>     · 程式碼改成【不再使用】該欄位
>     · ★ 欄位還留在資料庫裡
>     · 上線後觀察 1~2 週（★ 這期間隨時可以安全回退）
>
>   【第二次部署】
>     · 確認穩定後才 DROP COLUMN
>     · ★ 此時舊版程式碼已經不會被回退到了
> ```

```php
<?php
// ★★ 重新命名欄位的安全做法（三次部署）
// ── 第一次：新增新欄位並雙寫 ──
Schema::table('users', function (Blueprint $t) {
    $t->string('full_name')->nullable()->after('name');
});
// 程式碼：寫入時兩個欄位都寫，讀取時優先讀 full_name，退回 name

// ── 第二次：資料遷移 + 只讀新欄位 ──
// migration: User::whereNull('full_name')->update(['full_name' => DB::raw('name')]);
// 程式碼：只讀寫 full_name

// ── 第三次：刪除舊欄位 ──
Schema::table('users', function (Blueprint $t) {
    $t->dropColumn('name');
});
```

```php
<?php
// ★★ 大表加索引：避免長時間鎖表
// MySQL 8 的 ALGORITHM=INPLACE 大多不鎖表，但要明確指定
DB::statement('ALTER TABLE orders ADD INDEX idx_created_at (created_at), ALGORITHM=INPLACE, LOCK=NONE');

// ★ 或用 pt-online-schema-change（Percona Toolkit）處理超大表
```

```bash
# ★★ 遷移前務必檢查
$ php artisan migrate:status --pending
$ php artisan migrate --pretend         # ★★ 只印出 SQL 不執行
  Ran 1 migration:
    ALTER TABLE `users` ADD `full_name` varchar(255) NULL

# ★ 評估影響（大表）
$ mysql -e "SELECT TABLE_NAME, TABLE_ROWS,
    ROUND(DATA_LENGTH/1048576) AS data_mb
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA='appdb' ORDER BY DATA_LENGTH DESC LIMIT 5;"
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **正式環境功能壞掉但本機正常** ★★★ | `config/` 外用了 `env()` | 改用 `config()`；掃描專案 |
| **改 `.env` 沒生效** ★★★ | `config:cache` | `config:clear && config:cache` |
| **`route:cache` 失敗** ★★ | 路由中有 Closure | 改成 Controller |
| **部署後執行舊程式碼** ★★★ | OPcache | `systemctl reload php-fpm` |
| **worker 執行舊程式碼** ★★★ | 沒重啟 | `queue:restart` + supervisorctl |
| **OPcache hit_rate 低** ★★ | 記憶體不足 | 調高 `memory_consumption` |
| `Class not found`（部署後）★ | autoload 沒更新 | `composer dump-autoload -o` |
| **回退後仍然壞掉** ★★★ | migration 不可逆 | 向後相容的遷移；從備份還原 |
| **Octane 下使用者看到別人的資料** ★★★ | 靜態屬性殘留 | 檢查 static；設 `flush` |
| `Cache::tags()` 拋錯 ★ | driver 不支援 | 用 redis/memcached |
| **快取雷霆群集** ★★ | 大量請求同時算 | `Cache::flexible()` 或 lock |
| 部署很慢 | composer/npm 沒快取 | 設 `cache-dir`；CI 快取 |
| **磁碟滿** | releases 累積 | 只保留 5 個；清理備份 |

### 排查

```bash
APP=/var/www/api

# 【1】★★★ 最重要：檢查不當的 env() 使用
$ grep -rn "env(" "$APP/current/app" "$APP/current/routes" \
    "$APP/current/database" --include='*.php' | grep -v vendor

# 【2】★★ 快取狀態
$ ls -la "$APP/current/bootstrap/cache/"
$ php "$APP/current/artisan" config:show app.env
$ php "$APP/current/artisan" about | head -25

# 【3】★★ OPcache
$ curl -s http://127.0.0.1/_opcache.php | jq   # ★ 需先放檔案
# ★ 或看 FPM 的設定
$ php-fpm8.3 -i 2>/dev/null | grep -E 'opcache\.(enable|validate|memory|max_acc)'

# 【4】★★★ 確認 worker 用新程式碼
$ ps -o pid,lstart,cmd -C php | grep queue:work
$ readlink "$APP/current"

# 【5】部署歷史
$ tail -20 "$APP/shared/deploy.log"
$ ls -lt "$APP/releases/" | head

# 【6】★★ 錯誤日誌
$ tail -100 "$APP/shared/storage/logs/laravel-$(date +%Y-%m-%d).log"
$ grep -c 'production.ERROR' "$APP/shared/storage/logs/laravel-$(date +%Y-%m-%d).log"

# 【7】遷移狀態
$ php "$APP/current/artisan" migrate:status | tail -20

# 【8】效能
$ ab -n 200 -c 10 https://api.example.gov.tw/api/health
$ curl -so /dev/null -w 'TTFB %{time_starttransfer}s  總計 %{time_total}s\n' \
    https://api.example.gov.tw/
```

---

## 安全性注意事項

> [!danger] 部署流程的三個安全要點 ★★★
> ```
> ① ★★★ 部署前檢查 APP_DEBUG 與 APP_ENV
>      → 腳本開頭就 die 掉，不要等到上線才發現
>
> ② ★★★ 前端建置產物的秘密掃描
>      → grep -rE 'sk_live|-----BEGIN|AKIA' public/build/
>      → 發現就中止部署
>
> ③ ★★ 遷移前的資料庫備份
>      → migration 是不可逆的
>      → ★ 備份要驗證能還原（★ 定期演練）
> ```

```bash
# ★★ 驗證備份能還原（★ 每季演練一次）
$ BAK=/backup/db/appdb-20260828153045.sql.gz
$ mysql -u root -p -e "CREATE DATABASE appdb_restore_test;"
$ zcat "$BAK" | mysql -u root -p appdb_restore_test
$ mysql -u root -p -e "
  SELECT COUNT(*) AS tables FROM information_schema.TABLES
    WHERE TABLE_SCHEMA='appdb_restore_test';
  SELECT COUNT(*) AS users FROM appdb_restore_test.users;"
$ mysql -u root -p -e "DROP DATABASE appdb_restore_test;"
```

> [!warning] `bootstrap/cache/` 的權限 ★★
> ```
> ★★ 這個目錄需要 www-data 可寫（Laravel 執行時可能寫入 packages.php）
>   chmod -R 770 bootstrap/cache
>
> ★★★ 但這也是風險：
>   → www-data 可以在裡面【寫入 PHP 檔案】
>   → ★ 若有任意檔案寫入的漏洞 → 可以寫 webshell 到這裡
>
> ★★ 緩解：
>   · Nginx 已經擋掉 /bootstrap/ 路徑（★ 無法直接存取）
>   · ★ open_basedir 限制範圍
>   · ★★ 更好：部署時就產好所有快取，把目錄改成唯讀
>       chmod -R 750 bootstrap/cache
>     → ★ 但某些套件會在執行時寫入 → 要測試
> ```

---

## 速查表

### ★★★ `env()` 的鐵則

```php
// ✅ 只在 config/*.php 裡用 env()
// config/services.php
'payment' => ['key' => env('PAYMENT_API_KEY')],

// ✅ 其他地方一律用 config()
$key = config('services.payment.key');

// ❌❌❌ config:cache 後 env() 回傳 null
$key = env('PAYMENT_API_KEY');    // 在 Controller/Service/routes 裡
```

```bash
# ★★ 掃描
grep -rn "env(" app/ routes/ database/ --include='*.php' | grep -v config/
```

### 四種快取

```bash
php artisan optimize          # ★ config + event + route + view
php artisan optimize:clear    # ★ 全部清除

config:cache   → ★★★ env() 失效
route:cache    → ★★ 路由不能有 Closure
view:cache     → 無限制
event:cache    → 無限制
```

### ★★★ OPcache

```ini
opcache.validate_timestamps = 0    ; ★★★ 正式環境
opcache.save_comments = 1          ; ★★★ Laravel 必須
opcache.memory_consumption = 256
opcache.max_accelerated_files = 20000
```

```
★★★ validate_timestamps=0 → 部署後必須：
   systemctl reload php8.3-fpm
★★ 搭配 $realpath_root + releases 佈局效果最好
```

```bash
# 健康指標
hit_rate > 99%        restarts = 0        wasted < 10%
cached_files < max_accelerated_files
```

### ★★★ 部署流程

```
0  前置檢查（APP_ENV / APP_DEBUG / 磁碟）
1  ★★ 資料庫備份
2  git clone --depth 1
3  連結 shared（.env / storage）
4  composer install --no-dev --optimize-autoloader
5  npm ci && npm run build + ★★ 秘密掃描
6  ★★ php artisan migrate --force
7  ★★★ optimize（config/event/route/view cache）
8  權限 750/640，bootstrap/cache 與 storage 770
9  ★★★ 煙霧測試（★ 失敗就不切換）
10 ★★★ 原子切換 ln -sfn + mv -Tf
11 ★★★ reload php-fpm + nginx + ★★★ queue:restart
12 ★★★ 部署後驗證（含佇列）→ 失敗自動回退
13 清理舊 releases
```

### ★★★ 部署後三個必做的重載

```bash
sudo systemctl reload php8.3-fpm            # ★★ OPcache
sudo systemctl reload nginx
php artisan queue:restart && \
  sudo supervisorctl restart laravel-workers:   # ★★★ 最常被忘記
```

### ★★★ 向後相容的遷移

```
安全：新增表、新增欄位（有預設值/允許NULL）、新增索引
★★ 危險：DROP COLUMN、改型別、重新命名、加 NOT NULL 無預設值

★★★ 危險的要分兩次部署：
  第一次：程式碼不再用該欄位（欄位還在）→ 觀察 1~2 週
  第二次：確認穩定後才 DROP
```

```bash
php artisan migrate:status --pending
php artisan migrate --pretend        # ★★ 只印 SQL 不執行
```

### Octane 五個陷阱 ★★★

```
① 靜態屬性殘留 → ★★★ 跨使用者資料洩漏
② Singleton 狀態殘留
③ 全域/static 變數
④ 記憶體洩漏累積 → --max-requests=500
⑤ 套件不相容

★★ 內部管理系統通常不需要 Octane
```

### 應用層快取

```php
Cache::remember('key', 300, fn () => ...);
Cache::flexible('key', [300, 600], fn () => ...);   // ★★ stale-while-revalidate
Cache::tags(['users'])->flush();                    // ★ 只有 redis/memcached

// ★★ 版本化 key（最可靠的失效策略）
$v = Cache::get('users:version', 1);
Cache::remember("users:list:v{$v}", 3600, ...);
Cache::increment('users:version');    // 資料變更時
```

---

## 練習題

> [!question]- 練習 1：`env()` 的陷阱 ★★★
> 1. 在 Controller 裡寫 `$x = env('APP_NAME');` 並 `dd($x)`
> 2. **不執行 `config:cache`** → 有值嗎？
> 3. **執行 `php artisan config:cache`** → 再看 → **是什麼？**
> 4. 改成 `config('app.name')` → 再測
> 5. **掃描你的專案**，找出所有不當的 `env()` 使用
> 6. **把這個檢查加進 CI**

> [!question]- 練習 2：OPcache 與部署 ★★★
> 1. 設 `opcache.validate_timestamps=0`
> 2. 修改一個 Controller 的回傳值
> 3. **不 reload FPM** → 重新整理 → **看到新的嗎？**
> 4. `systemctl reload php8.3-fpm` → 再看
> 5. **改用 `$realpath_root` + releases 切換** → 不 reload 也會生效嗎？
> 6. 用 `_opcache.php` 觀察 `cached_files` 的變化

> [!question]- 練習 3：`route:cache` 與 Closure
> 1. 在 `routes/web.php` 加一個 Closure 路由
> 2. `php artisan route:cache` → **錯誤訊息是什麼？**
> 3. 找出所有 Closure 路由（用 `route:list --json`）
> 4. 全部改成 Controller
> 5. 再 `route:cache` → 成功
> 6. **比較有無 route cache 的回應時間**（`ab -n 200`）

> [!question]- 練習 4：完整的部署與回退 ★★★
> 1. 部署 `deploy-laravel` 腳本
> 2. 執行一次完整部署，**每一步的輸出都看懂**
> 3. **故意讓煙霧測試失敗**（改壞 `public/index.php`）→ **有切換嗎？**
> 4. 故意讓部署後驗證失敗 → **自動回退了嗎？**
> 5. 開持續請求的迴圈，測量**切換瞬間的中斷**
> 6. 執行 `rollback-laravel`

> [!question]- 練習 5：不可逆的遷移 ★★★
> **★ 在測試環境**
> 1. 建一個 migration `DROP COLUMN old_field`
> 2. 部署（含 migration）
> 3. **回退程式碼** → **應用還能跑嗎？錯誤是什麼？**
> 4. `php artisan migrate:rollback --step=1` → 恢復了嗎？
> 5. 改用**分兩次部署**的做法重做
> 6. **寫出你們的遷移審查清單**

---

## 小測驗

Q1. **`config:cache` 之後 `env()` 會怎樣？正確的做法是什麼**？

Q2. **`route:cache` 有什麼限制**？

Q3. **`opcache.validate_timestamps=0` 的好處與代價**？

Q4. **為什麼 `opcache.save_comments` 對 Laravel 必須是 1**？

Q5. **部署後必須重載哪三個東西**？

Q6. **煙霧測試該放在部署流程的哪一步？為什麼**？

Q7. **什麼是「向後相容的遷移」？刪除欄位該怎麼做**？

Q8. **Laravel Octane 的最大風險是什麼**？

Q9. **`Cache::flexible()` 解決什麼問題**？

Q10. **回退符號連結為什麼不能解決所有問題**？

> [!question]- 測驗答案
> **Q1.** **`config:cache` 之後，Laravel 完全不再讀取 `.env` 檔案**，
> **所有 `env()` 呼叫都回傳 `null`**（除非給了第二個參數的預設值）。
> **正確做法**：
> **只在 `config/*.php` 裡使用 `env()`**，
> **其他所有地方（Controller、Service、Model、Middleware、routes）一律用 `config()`**：
> ```php
> // config/services.php
> 'payment' => ['key' => env('PAYMENT_API_KEY')],
> // 程式碼中
> $key = config('services.payment.key');
> ```
> **這個陷阱特別難 debug 的原因**：
> **本機開發完全正常**（本機通常沒跑 `config:cache`），
> 部署到正式環境才壞掉，而且 `config:clear` 之後又好了。
> **掃描方式**：`grep -rn "env(" app/ routes/ database/ --include='*.php' | grep -v config/`
>
> **Q2.** **路由檔案中不能有 Closure** ——
> `route:cache` 需要把路由序列化成 PHP 陣列，
> **Closure 無法序列化**，會報
> `Your route files contain closures, which cannot be serialized.`
> ```php
> Route::get('/hello', function () { return 'Hello'; });   // ✗
> Route::get('/hello', [HelloController::class, 'index']); // ✓
> Route::get('/hello', HelloController::class);            // ✓ invokable
> ```
> 同樣的限制適用於 **Closure middleware**。
> **不受影響的**：`Schedule::call(fn() => ...)`（排程）、
> `dispatch(function () {...})`（佇列的 Closure job）。
> **找出方式**：`php artisan route:list --json | jq -r '.[] | select(.action=="Closure")'`
>
> **Q3.** **好處**：OPcache **完全不檢查檔案的 mtime** ——
> 省下每個 PHP 檔案在每次請求時的 `stat()` 系統呼叫，
> **在大專案（數千個檔案）上是明顯的效能提升**。
> **代價**：**部署新版後必須手動讓 OPcache 失效**，
> **否則會一直執行舊的程式碼**。
> **三種失效方式**：
> ①**`systemctl reload php8.3-fpm`**（最簡單可靠，是 graceful 的不會斷線）；
> ②`opcache_reset()`（需要端點，**且只影響呼叫它的那個 worker**，不可靠）；
> ③**用 `$realpath_root` + releases 佈局** ——
> 新版的檔案路徑不同，OPcache 的 key 就不同，**自動生效**。
> **建議 ③ + ① 一起做**。
>
> **Q4.** 因為 **Laravel 與許多套件大量使用 PHP 8 Attributes 與 DocBlock 註解**
> 來定義路由、驗證規則、關聯、佇列設定。
> **`save_comments=0` 會在編譯時丟棄所有註解** →
> **Reflection 讀不到 DocBlock 與 Attributes** →
> 路由註冊失敗、關聯定義遺失、
> **某些套件（Laravel Nova、Doctrine Annotations）直接無法運作**，
> 而錯誤訊息通常完全聯想不到 OPcache。
> **這是預設值（1），但有些「PHP 效能調校教學」會建議關掉它** ——
> 對 Laravel **千萬不要**。
>
> **Q5.** ①**`sudo systemctl reload php8.3-fpm`** ——
> 讓 **OPcache 失效**（`validate_timestamps=0` 時必須）；
> ②**`sudo systemctl reload nginx`** —— 若設定或憑證有變更；
> ③**★★★ `php artisan queue:restart` + `sudo supervisorctl restart laravel-workers:`** ——
> **queue worker 是長駐程序，不重啟會永遠執行舊的 Job 類別**。
> **第三項是最常被忘記的** ——
> 症狀是「網頁已經是新版，但背景處理的邏輯還是舊的」，
> 表現為「有些功能好了、有些沒好」，而且**沒有任何錯誤訊息**。
> 若有用 Horizon 則是 `php artisan horizon:terminate`；
> 若有用 Octane 則是 `php artisan octane:reload`。
>
> **Q6.** **放在「原子切換之前」**（步驟 9，切換是步驟 10）。
> **原因**：煙霧測試是在**新的 release 目錄**上執行的，
> 此時**符號連結還指著舊版本，網站仍然由舊版服務** ——
> **如果新版本有問題（vendor 沒裝好、語法錯誤、資料庫連不上、
> 快取產生失敗），就直接中止部署，使用者完全不受影響**。
> **如果放在切換之後才測**，就已經有一段時間是壞的版本在服務了，
> 即使自動回退也會有幾秒到幾十秒的錯誤。
> **煙霧測試該檢查**：artisan 可執行、快取檔案存在、
> `vendor/autoload.php` 存在、`index.php` 語法正確、
> 資料庫可連線、快取可用、沒有開發相依。
> **切換之後再做一次「部署後驗證」**（實際的 HTTP 請求 + 佇列驗證），失敗則自動回退。
>
> **Q7.** **「向後相容的遷移」= 新版程式碼與舊版程式碼都能在遷移後的 schema 上執行** ——
> 這樣才能**安全地回退**。
> **安全的**：新增資料表、新增欄位（有預設值或允許 NULL）、新增索引。
> **危險的**：`DROP COLUMN`、`DROP TABLE`、改變欄位型別、重新命名欄位、
> 加 `NOT NULL` 且無預設值的欄位。
> **刪除欄位的正確做法是「分兩次部署」（expand-contract）**：
> **第一次部署** —— 程式碼改成**不再使用該欄位**，
> 但**欄位還留在資料庫裡**，上線後**觀察 1～2 週**
> （這期間隨時可以安全回退）；
> **第二次部署** —— 確認穩定後才真正執行 `DROP COLUMN`。
> 重新命名欄位則需要**三次部署**（加新欄位並雙寫 → 遷移資料並只讀新欄位 → 刪舊欄位）。
>
> **Q8.** **跨請求的狀態殘留導致「使用者 A 的資料被使用者 B 看到」**。
> Octane 讓 Laravel 常駐記憶體，**Application 實例跨請求共用**，
> 所以：
> ①**靜態屬性會殘留** —— `class Foo { public static array $cache = []; }`
> 第一個請求塞的資料，第二個請求還在；
> ②**Singleton 綁定的物件會保留狀態** ——
> 若 Service 內部有 `$this->currentUser`，就會跨請求洩漏；
> ③全域變數與函式內的 `static` 變數同理。
> **這是資安等級的問題，不只是 bug**。
> 其他風險：**記憶體洩漏會累積**（必須設 `--max-requests=500`）、
> **某些套件不相容**。
> **建議**：內部管理系統流量不大，**通常不需要 Octane**；
> 真要用就先在 staging 跑一個月並仔細測試。
>
> **Q9.** **解決「快取雷霆群集」（cache stampede）** ——
> 一個熱門的快取項目過期的瞬間，
> **所有同時到達的請求都發現快取沒了，於是全部一起去執行昂貴的查詢**，
> 瞬間把資料庫打爆。
> ```php
> Cache::flexible('key', [300, 600], fn () => expensiveQuery());
> ```
> **行為**：**300 秒內**直接回傳快取；
> **300～600 秒之間**「**先回傳舊的（stale），同時在背景更新**」
> —— 使用者不用等，資料庫也只被打一次；
> 超過 600 秒才真的重新計算並等待。
> 這就是 HTTP 的 **stale-while-revalidate** 概念（Laravel 11.23+）。
> **替代做法**是用 `Cache::lock()` 手動實作（只讓一個請求去算，其他等待）。
>
> **Q10.** 因為**符號連結只回退了「程式碼」，資料庫已經被遷移了**。
> **安全的情況**：新版**加了**欄位 → 回退後舊版忽略它 → 沒事。
> **災難的情況**：新版**刪除了**欄位或改了型別 →
> 回退後**舊版程式碼要用那個欄位** → **整個應用壞掉**，
> 而且此時回退也救不了。
> **其他回退救不了的**：
> **已經寄出的通知信**、**已經呼叫的外部 API**（付款、第三方系統）、
> **已經寫入的新格式檔案**、**已經發布給客戶端的新版前端資源**。
> **所以回退是「降低風險的手段，不是萬靈丹」** ——
> 真正的防線是 **staging 驗證** 與 **向後相容的遷移**，
> 以及**遷移前的資料庫備份**（並且定期演練還原）。

---

## 延伸閱讀

- [[130-01-04-05-guide-Laravel-Filament部署]] — Filament 後台的部署
- [[130-01-04-06-guide-Laravel-Nova部署]] — Nova 的授權與部署
- [[130-01-04-07-guide-Laravel-正式環境安全檢查表]] — 上線前的完整檢查
- [[130-01-06-guide-部署-部署自動化]] — CI/CD 與自動化
- [[060-03-01-05-guide-PHP-OPcache與效能]] — OPcache 的深入設定
- [[130-01-04-03-guide-Laravel-佇列排程與Supervisor]] — 佇列的重啟
