---
title: "Laravel API 後端部署"
desc: "API 專屬的路由、JSON 錯誤處理、版本控制、限流、健康檢查與文件"
aliases: [Laravel API, API Resource, 限流, throttle, 健康檢查, API版本]
tags: [群組/實務案例, 主題/部署, 主題/Laravel, 主題/LXMP]
category: 專案部署實戰
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[01-前後端分離架構選型]]", "[[02-Laravel-Nginx與PHP-FPM設定]]"]
updated: 2026-08-28
---

# Laravel API 後端部署

> [!abstract] 這篇你會學到
> - **API 專用的 Laravel 設定**（無 session、無 CSRF 的例外情況）
> - **★★★ 統一的 JSON 錯誤處理**（不要回傳 HTML）
> - **API 版本控制**的三種做法
> - **★★ 限流策略**（依端點、依使用者、依 IP）
> - **健康檢查端點**與監控整合
> - **API Resource** 與資料洩漏防護
> - **API 文件**（Scramble / OpenAPI）

## 前置知識

- [[01-前後端分離架構選型]] — 拓撲與認證的選擇
- [[02-Laravel-Nginx與PHP-FPM設定]] — Nginx 與 FPM

---

## API 專用的 Laravel 設定 ★★

```php
<?php
// ★★ bootstrap/app.php（Laravel 11+）
use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\Exceptions;
use Illuminate\Foundation\Configuration\Middleware;
use Illuminate\Http\Request;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        web:      __DIR__.'/../routes/web.php',
        api:      __DIR__.'/../routes/api.php',
        commands: __DIR__.'/../routes/console.php',
        health:   '/up',                          // ★★ 內建的健康檢查端點
    )
    ->withMiddleware(function (Middleware $middleware) {
        // ═══ ★★★ 信任反向代理（HTTPS 三件套之二）═══
        $middleware->trustProxies(
            at: ['127.0.0.1', '::1'],
            headers: Request::HEADER_X_FORWARDED_FOR
                   | Request::HEADER_X_FORWARDED_HOST
                   | Request::HEADER_X_FORWARDED_PORT
                   | Request::HEADER_X_FORWARDED_PROTO,
        );

        // ═══ ★★ Sanctum SPA 認證（★ cookie 模式必須）═══
        $middleware->statefulApi();

        // ═══ ★★ API 的全域 middleware ═══
        $middleware->api(prepend: [
            \Laravel\Sanctum\Http\Middleware\EnsureFrontendRequestsAreStateful::class,
        ]);

        $middleware->api(append: [
            \App\Http\Middleware\ForceJsonResponse::class,   // ★★★ 見下方
            \App\Http\Middleware\SecurityHeaders::class,
        ]);

        // ═══ ★ 別名 ═══
        $middleware->alias([
            'ability'    => \Laravel\Sanctum\Http\Middleware\CheckAbilities::class,
            'abilities'  => \Laravel\Sanctum\Http\Middleware\CheckForAnyAbility::class,
            'admin.ip'   => \App\Http\Middleware\RestrictAdminIp::class,
        ]);

        // ═══ ★★ 節流的自訂回應 ═══
        $middleware->throttleWithRedis();          // ★ 用 Redis（★ 多台伺服器時必須）
    })
    ->withExceptions(function (Exceptions $exceptions) {
        // ★★★ 見下方「統一的 JSON 錯誤處理」
    })
    ->create();
```

```php
<?php
// ★★★ app/Http/Middleware/ForceJsonResponse.php
namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class ForceJsonResponse
{
    public function handle(Request $request, Closure $next): Response
    {
        // ★★★ 強制 API 請求都當成 JSON 處理
        // → 讓 Laravel 的例外處理回傳 JSON 而不是 HTML
        $request->headers->set('Accept', 'application/json');
        return $next($request);
    }
}
```

> [!danger] 沒有這個 middleware，API 會回傳 HTML 錯誤頁 ★★★
> ```
> ★★ Laravel 依 Accept 標頭決定回應格式
>   → 客戶端沒送 Accept: application/json
>     → ★★ 例外處理回傳【HTML 錯誤頁】
>       → 前端 JSON.parse 失敗
>         → 「Unexpected token '<'」
>
> ★★ 症狀：
>   · 正常的請求都好好的
>   · ★ 一旦發生錯誤（驗證失敗、404、500）就爆炸
>   · 前端看到的是 HTML 而不是錯誤訊息
>
> ★★★ 兩種解法：
>   ① 前端一律送 Accept: application/json（★ 最正確）
>   ② ★★ 後端用 middleware 強制（★ 保險）
>   → 建議兩個都做
> ```

```php
<?php
// ★★ app/Http/Middleware/SecurityHeaders.php
namespace App\Http\Middleware;

class SecurityHeaders
{
    public function handle(Request $request, Closure $next): Response
    {
        $response = $next($request);

        $response->headers->set('X-Content-Type-Options', 'nosniff');
        $response->headers->set('X-Frame-Options', 'DENY');
        $response->headers->set('Referrer-Policy', 'no-referrer');
        $response->headers->set('X-Robots-Tag', 'noindex, nofollow');
        // ★★ API 的回應絕不快取
        $response->headers->set('Cache-Control', 'no-store, no-cache, must-revalidate, private');
        $response->headers->remove('X-Powered-By');

        return $response;
    }
}
```

---

## ★★★ 統一的 JSON 錯誤處理

```php
<?php
// ★★★ bootstrap/app.php 的 withExceptions
use Illuminate\Auth\AuthenticationException;
use Illuminate\Auth\Access\AuthorizationException;
use Illuminate\Database\Eloquent\ModelNotFoundException;
use Illuminate\Http\Request;
use Illuminate\Validation\ValidationException;
use Symfony\Component\HttpKernel\Exception\HttpExceptionInterface;
use Symfony\Component\HttpKernel\Exception\NotFoundHttpException;
use Symfony\Component\HttpKernel\Exception\MethodNotAllowedHttpException;
use Symfony\Component\HttpKernel\Exception\TooManyRequestsHttpException;
use Illuminate\Support\Str;

->withExceptions(function (Exceptions $exceptions) {

    // ═══ ★★ 不要回報這些例外（減少噪音）═══
    $exceptions->dontReport([
        ValidationException::class,
        AuthenticationException::class,
        AuthorizationException::class,
        ModelNotFoundException::class,
        NotFoundHttpException::class,
    ]);

    // ═══ ★★★ 不要記錄敏感欄位 ═══
    $exceptions->dontFlash([
        'current_password', 'password', 'password_confirmation',
        'token', 'api_key', 'secret', 'credit_card',
    ]);

    // ═══ ★★★ 統一的 JSON 回應格式 ═══
    $exceptions->render(function (Throwable $e, Request $request) {
        if (!$request->expectsJson() && !$request->is('api/*')) {
            return null;                       // ★ 讓 web 路由用預設處理
        }

        // ★★ 產生 trace ID（★ 方便對應日誌）
        $traceId = Str::uuid()->toString();

        [$status, $code, $message, $extra] = match (true) {
            $e instanceof ValidationException => [
                422, 'VALIDATION_ERROR', '輸入資料有誤',
                ['errors' => $e->errors()],
            ],
            $e instanceof AuthenticationException => [
                401, 'UNAUTHENTICATED', '請先登入', [],
            ],
            $e instanceof AuthorizationException => [
                403, 'FORBIDDEN', '沒有權限執行這個操作', [],
            ],
            $e instanceof ModelNotFoundException => [
                404, 'NOT_FOUND', '找不到指定的資料', [],
            ],
            $e instanceof NotFoundHttpException => [
                404, 'NOT_FOUND', '找不到該端點', [],
            ],
            $e instanceof MethodNotAllowedHttpException => [
                405, 'METHOD_NOT_ALLOWED', '不支援的 HTTP 方法', [],
            ],
            $e instanceof TooManyRequestsHttpException => [
                429, 'TOO_MANY_REQUESTS', '請求過於頻繁，請稍後再試',
                ['retry_after' => $e->getHeaders()['Retry-After'] ?? 60],
            ],
            $e instanceof HttpExceptionInterface => [
                $e->getStatusCode(), 'HTTP_ERROR',
                $e->getMessage() ?: '請求發生錯誤', [],
            ],
            default => [
                500, 'SERVER_ERROR', '系統發生錯誤，請聯絡管理員', [],
            ],
        };

        // ★★★ 500 錯誤一定要記錄（含 trace ID）
        if ($status >= 500) {
            Log::error('API 例外', [
                'trace_id' => $traceId,
                'message'  => $e->getMessage(),
                'file'     => $e->getFile() . ':' . $e->getLine(),
                'url'      => $request->fullUrl(),
                'method'   => $request->method(),
                'user_id'  => $request->user()?->id,
                'ip'       => $request->ip(),
                'trace'    => collect($e->getTrace())->take(10)->toArray(),
            ]);
        }

        $payload = array_merge([
            'message'  => $message,
            'code'     => $code,
            'trace_id' => $traceId,           // ★★ 給使用者回報時用
        ], $extra);

        // ★★★ 只有非正式環境才顯示技術細節
        if (config('app.debug') && $status >= 500) {
            $payload['debug'] = [
                'exception' => get_class($e),
                'message'   => $e->getMessage(),
                'file'      => $e->getFile(),
                'line'      => $e->getLine(),
            ];
        }

        return response()->json($payload, $status);
    });
});
```

```json
// ★★ 統一的錯誤格式範例
// 422
{
  "message": "輸入資料有誤",
  "code": "VALIDATION_ERROR",
  "trace_id": "018f2c1a-...",
  "errors": {
    "email": ["email 必須是有效的電子郵件地址"],
    "password": ["password 至少需要 12 個字元"]
  }
}

// 500（★ 正式環境不含技術細節）
{
  "message": "系統發生錯誤，請聯絡管理員",
  "code": "SERVER_ERROR",
  "trace_id": "018f2c1b-..."
}
```

> [!tip] `trace_id` 的價值 ★★
> ```
> ★★ 使用者回報「系統壞了」時：
>   ❌ 沒有 trace_id → 要從幾千行日誌裡找
>   ✅ 有 trace_id → grep 一次就找到
>
> $ grep '018f2c1b-' /var/www/api/shared/storage/logs/*.log
>
> ★ 前端也要顯示：
>   「系統發生錯誤（代碼：018f2c1b），請聯絡管理員」
> ```

---

## API 版本控制 ★★

| 方式 | 範例 | 優點 | 缺點 |
| --- | --- | --- | --- |
| **① URL 路徑** ★★ | `/api/v1/users` | **✓ 最直覺、易快取、易除錯** | 網址會變 |
| ② 標頭 | `Accept: application/vnd.api.v1+json` | 網址不變 | 除錯麻煩、不易快取 |
| ③ 查詢參數 | `/api/users?version=1` | 簡單 | 易被忽略、快取問題 |

```php
<?php
// ★★ ① URL 路徑（推薦）
// routes/api.php
use Illuminate\Support\Facades\Route;

Route::prefix('v1')->name('v1.')->group(function () {
    Route::middleware('auth:sanctum')->group(function () {
        Route::apiResource('orders', V1\OrderController::class);
        Route::apiResource('users',  V1\UserController::class);
    });

    Route::post('/login',  [V1\AuthController::class, 'login'])->middleware('throttle:login');
    Route::post('/logout', [V1\AuthController::class, 'logout'])->middleware('auth:sanctum');
});

Route::prefix('v2')->name('v2.')->group(function () {
    // ★★ v2 只覆寫有變動的端點，其他沿用 v1
    Route::middleware('auth:sanctum')->group(function () {
        Route::apiResource('orders', V2\OrderController::class);   // ★ 只有這個變了
        Route::apiResource('users',  V1\UserController::class);    // ★ 沿用 v1
    });
});
```

```php
<?php
// ★★ 舊版的淘汰通知
// app/Http/Middleware/DeprecationWarning.php
class DeprecationWarning
{
    public function handle(Request $request, Closure $next, string $sunset = ''): Response
    {
        $response = $next($request);

        // ★★ RFC 8594 的標準標頭
        $response->headers->set('Deprecation', 'true');
        if ($sunset) {
            $response->headers->set('Sunset', $sunset);   // ★ HTTP date 格式
        }
        $response->headers->set('Link', '</api/v2/docs>; rel="successor-version"');

        return $response;
    }
}
```

```php
<?php
// ★ 套用到舊版
Route::prefix('v1')->middleware('deprecated:Sun, 31 Dec 2026 23:59:59 GMT')->group(function () {
    // ...
});
```

```bash
# ★★ 監控舊版的使用量（決定何時能下線）
$ awk '$7 ~ /^\/api\/v1\//' /var/log/nginx/api.access.log | wc -l
$ awk '$7 ~ /^\/api\/v1\//{print $1}' /var/log/nginx/api.access.log | sort -u | wc -l
# ★ 使用者數降到 0 才能下線
```

---

## ★★ 限流策略

```php
<?php
// ★★★ app/Providers/AppServiceProvider.php 或 bootstrap/app.php
use Illuminate\Cache\RateLimiting\Limit;
use Illuminate\Support\Facades\RateLimiter;

public function boot(): void
{
    // ═══ ★★ 一般 API：依使用者，未登入依 IP ═══
    RateLimiter::for('api', function (Request $request) {
        return $request->user()
            ? Limit::perMinute(300)->by('user:' . $request->user()->id)
            : Limit::perMinute(60)->by('ip:' . $request->ip());
    });

    // ═══ ★★★ 登入：極嚴格（防暴力破解）═══
    RateLimiter::for('login', function (Request $request) {
        return [
            Limit::perMinute(5)->by('ip:' . $request->ip()),
            // ★★ 同一個 email 更嚴格（★ 防針對特定帳號的攻擊）
            Limit::perMinute(3)->by('email:' . Str::lower($request->input('email', ''))),
            Limit::perHour(20)->by('ip:' . $request->ip()),
        ];
    });

    // ═══ ★ 昂貴的操作（報表、匯出）═══
    RateLimiter::for('expensive', function (Request $request) {
        return Limit::perMinute(3)->by('user:' . $request->user()?->id ?: $request->ip())
            ->response(function () {
                return response()->json([
                    'message' => '此操作較耗資源，請稍後再試',
                    'code'    => 'RATE_LIMITED',
                ], 429);
            });
    });

    // ═══ ★★ 上傳 ═══
    RateLimiter::for('upload', function (Request $request) {
        return Limit::perMinute(10)->by('user:' . $request->user()?->id ?: $request->ip());
    });

    // ═══ ★ 依角色差異化 ═══
    RateLimiter::for('tiered', function (Request $request) {
        $user = $request->user();
        return match (true) {
            !$user                  => Limit::perMinute(30)->by('ip:' . $request->ip()),
            $user->hasRole('admin') => Limit::none(),                    // ★ 管理員不限
            $user->is_premium       => Limit::perMinute(1000)->by('user:' . $user->id),
            default                 => Limit::perMinute(200)->by('user:' . $user->id),
        };
    });
}
```

```php
<?php
// ★ 套用
Route::middleware(['auth:sanctum', 'throttle:api'])->group(function () {
    Route::apiResource('orders', OrderController::class);

    Route::post('/reports/generate', ReportController::class)
        ->middleware('throttle:expensive');

    Route::post('/files', [FileController::class, 'store'])
        ->middleware('throttle:upload');
});

Route::post('/login', [AuthController::class, 'login'])->middleware('throttle:login');
```

> [!danger] 限流的三個陷阱 ★★★
> ```
> ① ★★★ 多台伺服器時必須用 Redis
>      預設用 cache driver
>      → ★ 若是 file/array → 每台各算各的
>        → 3 台伺服器 = 實際的限制是 3 倍
>      → ★★ CACHE_STORE=redis + $middleware->throttleWithRedis()
>
> ② ★★★ 反向代理後面的 IP
>      $request->ip() 若沒設 TrustProxies
>      → ★ 永遠是 127.0.0.1
>        → 【所有使用者共用同一個限流配額】
>          → 一個人打太多，全部人被鎖
>      → ★★ 必須設好 TrustProxies
>
> ③ ★★ 限流的 key 要夠精確
>      by($request->ip())
>      → ★ 同一個機關的所有人共用一個對外 IP
>        → 一個人觸發限流，全機關被鎖
>      → ★★ 登入後改用 by('user:' . $user->id)
> ```

```bash
# ★★ 驗證限流是否生效
$ for i in $(seq 1 10); do
    curl -so /dev/null -w '%{http_code} ' https://api.example.gov.tw/api/v1/orders \
      -H 'Accept: application/json'
  done; echo
200 200 200 200 200 429 429 429 429 429     # ★ 第 6 次開始被限流

# ★★ 檢查限流的標頭
$ curl -sI https://api.example.gov.tw/api/v1/orders -H 'Accept: application/json' | \
    grep -i 'x-ratelimit\|retry-after'
x-ratelimit-limit: 60
x-ratelimit-remaining: 55
retry-after: 42                        # ★ 被限流時才有

# ★★★ 驗證 IP 是真實的（不是 127.0.0.1）
$ curl -s https://api.example.gov.tw/api/v1/whoami -H 'Accept: application/json' | jq .ip
"203.0.113.5"                          # ★★ 不能是 127.0.0.1
```

---

## 健康檢查端點 ★★

```php
<?php
// ★★ routes/api.php —— 三層健康檢查
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Redis;
use Illuminate\Support\Facades\Cache;

// ═══ ① ★ 存活檢查（liveness）—— 極輕量 ═══
Route::get('/health/live', fn () => response()->json(['status' => 'ok']));

// ═══ ② ★★ 就緒檢查（readiness）—— 檢查相依服務 ═══
Route::get('/health/ready', function () {
    $checks = [];
    $healthy = true;

    // ★ 資料庫
    try {
        $t = microtime(true);
        DB::select('SELECT 1');
        $checks['database'] = ['ok' => true, 'ms' => round((microtime(true) - $t) * 1000, 1)];
    } catch (Throwable $e) {
        $checks['database'] = ['ok' => false, 'error' => 'connection failed'];
        $healthy = false;
    }

    // ★ Redis / 快取
    try {
        $t = microtime(true);
        Cache::put('__health', 1, 10);
        $ok = Cache::get('__health') === 1;
        $checks['cache'] = ['ok' => $ok, 'ms' => round((microtime(true) - $t) * 1000, 1)];
        $healthy = $healthy && $ok;
    } catch (Throwable $e) {
        $checks['cache'] = ['ok' => false, 'error' => 'connection failed'];
        $healthy = false;
    }

    // ★ 儲存空間可寫
    try {
        $checks['storage'] = ['ok' => is_writable(storage_path('app'))];
        $healthy = $healthy && $checks['storage']['ok'];
    } catch (Throwable $e) {
        $checks['storage'] = ['ok' => false];
        $healthy = false;
    }

    // ★★ 磁碟空間
    $free = disk_free_space(base_path());
    $total = disk_total_space(base_path());
    $pct = round(($total - $free) / $total * 100, 1);
    $checks['disk'] = ['ok' => $pct < 90, 'used_percent' => $pct];
    $healthy = $healthy && $checks['disk']['ok'];

    return response()->json([
        'status' => $healthy ? 'ok' : 'degraded',
        'checks' => $checks,
    ], $healthy ? 200 : 503);
});

// ═══ ③ ★ 版本資訊（★ 部署驗證用）═══
Route::get('/health/version', fn () => response()->json([
    'version'     => config('app.version', 'unknown'),
    'commit'      => trim(@file_get_contents(base_path('VERSION')) ?: 'unknown'),
    'laravel'     => app()->version(),
    'php'         => PHP_VERSION,
    'environment' => config('app.env'),
    'deployed_at' => @filemtime(base_path('composer.lock'))
        ? date('c', filemtime(base_path('composer.lock')))
        : null,
]));
```

> [!warning] 健康檢查端點的安全考量 ★★
> ```
> ★★ /health/ready 會洩漏內部資訊：
>   · 哪些相依服務存在
>   · 服務是否正常（★ 攻擊者知道什麼時候該攻擊）
>   · 版本資訊（★ 對應到已知的漏洞）
>
> ★★ 建議：
>   · /health/live   → 公開（★ 只回 {"status":"ok"}）
>   · ★★ /health/ready 與 /health/version → 限制來源 IP
> ```

```nginx
# ★★ Nginx 的保護
location = /api/health/live {
    access_log off;
    try_files $uri /index.php?$query_string;
}

location ~ ^/api/health/(ready|version)$ {
    allow 127.0.0.1;
    allow 10.0.0.0/8;              # ★ 監控主機
    deny all;
    access_log off;
    try_files $uri /index.php?$query_string;
}
```

```bash
# ★ 部署腳本中的驗證
$ curl -s https://api.example.gov.tw/api/health/ready | jq
{
  "status": "ok",
  "checks": {
    "database": { "ok": true, "ms": 1.2 },
    "cache":    { "ok": true, "ms": 0.4 },
    "storage":  { "ok": true },
    "disk":     { "ok": true, "used_percent": 42.3 }
  }
}

# ★★ Uptime Kuma / Prometheus 監控這個端點
```

---

## API Resource 與資料洩漏防護 ★★★

```php
<?php
// ❌❌ 危險：直接回傳 Model
Route::get('/users/{user}', fn (User $user) => $user);
// → ★★★ 回傳【所有欄位】，包含：
//     password（雜湊）、remember_token、api_token
//     internal_notes、is_admin、salary…
```

```php
<?php
// ✅ ★★★ 用 API Resource 明確控制輸出
namespace App\Http\Resources;

use Illuminate\Http\Resources\Json\JsonResource;

class UserResource extends JsonResource
{
    public function toArray(Request $request): array
    {
        return [
            'id'         => $this->id,
            'name'       => $this->name,
            'email'      => $this->email,
            'avatar_url' => $this->avatar_url,
            'created_at' => $this->created_at?->toIso8601String(),

            // ★★ 依權限決定要不要顯示
            'phone' => $this->when(
                $request->user()?->can('view-contact', $this->resource),
                $this->phone,
            ),

            // ★★★ 只有管理員看得到
            $this->mergeWhen($request->user()?->hasRole('admin'), [
                'is_active'      => $this->is_active,
                'last_login_at'  => $this->last_login_at?->toIso8601String(),
                'internal_notes' => $this->internal_notes,
            ]),

            // ★★ 關聯（★ 只在有載入時才輸出，避免 N+1）
            'roles' => RoleResource::collection($this->whenLoaded('roles')),

            'orders_count' => $this->whenCounted('orders'),
        ];
    }
}
```

```php
<?php
// ★★ Controller
class UserController extends Controller
{
    public function index(Request $request)
    {
        $this->authorize('viewAny', User::class);

        $users = User::query()
            ->with(['roles'])                   // ★★ 避免 N+1
            ->withCount('orders')
            ->when($request->search, fn ($q, $s) =>
                $q->where('name', 'like', "%{$s}%"))
            ->latest()
            ->paginate($request->integer('per_page', 25));

        return UserResource::collection($users);
    }

    public function show(User $user)
    {
        $this->authorize('view', $user);        // ★★★ 防 IDOR
        return new UserResource($user->load('roles'));
    }
}
```

> [!danger] Model 的 `$hidden` 不夠可靠 ★★
> ```php
> class User extends Model {
>     protected $hidden = ['password', 'remember_token'];
> }
> ```
>
> ```
> ★★ $hidden 是【黑名單】：
>   → 新增了一個敏感欄位但忘了加進 $hidden
>     → ★★★ 直接洩漏
>   → ->makeVisible() 可以繞過
>   → toArray() 之外的路徑可能不生效
>
> ★★★ API Resource 是【白名單】：
>   → 明確列出要輸出的欄位
>   → 新增欄位【預設不會輸出】（★ 安全的預設）
>
> ★★ 兩個都做：$hidden 當第二道防線，Resource 是主要控制
> ```

```bash
# ★★★ 檢查 API 回應有沒有洩漏
$ curl -s https://api.example.gov.tw/api/v1/users/1 \
    -H 'Accept: application/json' -b cookies.txt | jq 'keys'
[
  "id", "name", "email", "avatar_url", "created_at"
]
# ★ 不應該有 password、remember_token、internal_notes 等

# ★★ 掃描所有端點
$ for e in users orders products; do
    echo "── /api/v1/$e ──"
    curl -s "https://api.example.gov.tw/api/v1/$e" \
      -H 'Accept: application/json' -b cookies.txt | \
      jq -r '.data[0] // .[0] // {} | keys[]' 2>/dev/null | \
      grep -iE 'password|token|secret|salary|internal|_key' && echo "  ✗✗ 可能洩漏"
  done
```

---

## API 文件 ★

```bash
# ★★ Scramble：從程式碼自動產生 OpenAPI（★ 不用寫註解）
$ composer require dedoc/scramble

$ php artisan vendor:publish --provider="Dedoc\Scramble\ScrambleServiceProvider"
```

```php
<?php
// ★★ config/scramble.php
return [
    'api_path' => 'api',
    'info' => [
        'version' => '1.0.0',
        'description' => '機關管理系統 API',
    ],
    // ★★★ 正式環境的存取控制
    'middleware' => [
        'web',
        \Dedoc\Scramble\Http\Middleware\RestrictedDocsAccess::class,
    ],
];
```

```php
<?php
// ★★★ AppServiceProvider::boot()
use Dedoc\Scramble\Scramble;
use Illuminate\Support\Facades\Gate;

Gate::define('viewApiDocs', function ($user = null) {
    // ★★ 正式環境只給管理員
    if (app()->environment('production')) {
        return $user?->hasRole('admin') ?? false;
    }
    return true;
});
```

```nginx
# ★★ 或直接在 Nginx 限制
location ^~ /docs/api {
    allow 10.0.0.0/8;
    deny all;
    try_files $uri /index.php?$query_string;
}
```

```bash
# ★ 產生靜態的 OpenAPI 檔（★ 給前端或第三方）
$ php artisan scramble:export --path=storage/app/openapi.json
$ jq '.paths | keys | length' storage/app/openapi.json
42                                     # ★ 42 個端點
```

---

## 完整實戰範例：API 部署驗證

```bash
#!/usr/bin/env bash
# /usr/local/bin/verify-api —— API 部署後驗證
set -uo pipefail
API="${1:-https://api.example.gov.tw}"
COOKIE=/tmp/api-verify-cookies.txt
PASS=0; FAIL=0

p(){ printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
f(){ printf '  \033[31m✗✗\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
code(){ curl -sko /dev/null -w '%{http_code}' --max-time 15 "$@"; }

echo "═══ API 部署驗證：$API ═══"

# ═══ 【1】健康檢查 ═══
echo -e "\n【1】健康檢查"
[ "$(code "$API/api/health/live")" = 200 ] && p "liveness 200" || f "liveness 失敗"

READY=$(curl -s --max-time 15 "$API/api/health/ready" 2>/dev/null)
if echo "$READY" | jq -e '.status == "ok"' >/dev/null 2>&1; then
    p "readiness ok"
    echo "$READY" | jq -r '.checks | to_entries[] | "      \(.key): \(.value.ok)"'
else
    f "readiness 失敗"
    echo "$READY" | jq . 2>/dev/null | sed 's/^/      /' | head -10
fi

VER=$(curl -s "$API/api/health/version" 2>/dev/null)
echo "$VER" | jq -e '.commit' >/dev/null 2>&1 && \
  p "版本：$(echo "$VER" | jq -r '.commit') / Laravel $(echo "$VER" | jq -r '.laravel')"

# ═══ 【2】★★★ JSON 錯誤格式 ═══
echo -e "\n【2】★★★ JSON 錯誤格式"

# ★ 404
R=$(curl -s "$API/api/v1/nonexistent-endpoint" -H 'Accept: application/json' --max-time 10)
if echo "$R" | jq -e '.message and .code' >/dev/null 2>&1; then
    p "404 回傳 JSON：$(echo "$R" | jq -r '.code')"
else
    f "404 沒有回傳正確的 JSON 格式"
    echo "$R" | head -c 200 | sed 's/^/      /'
fi

# ★★ 不帶 Accept 標頭也要回 JSON
R=$(curl -s "$API/api/v1/nonexistent-endpoint" --max-time 10)
echo "$R" | grep -q '<!DOCTYPE\|<html' && \
  f "★★★ 沒有 Accept 標頭時回傳 HTML（★ 缺 ForceJsonResponse middleware）" || \
  p "★★ 沒有 Accept 標頭也回傳 JSON"

# ★ 401
R=$(curl -s "$API/api/v1/orders" -H 'Accept: application/json' --max-time 10)
echo "$R" | jq -e '.code == "UNAUTHENTICATED"' >/dev/null 2>&1 && \
  p "401 格式正確" || f "401 格式不正確"

# ★★ trace_id
echo "$R" | jq -e '.trace_id' >/dev/null 2>&1 && p "★★ 有 trace_id" || \
  printf '  \033[33m⚠\033[0m 沒有 trace_id\n'

# ═══ 【3】★★ 限流 ═══
echo -e "\n【3】★★ 限流"
CODES=""
for i in $(seq 1 12); do
    CODES="$CODES$(code "$API/api/v1/login" -X POST -H 'Accept: application/json' \
      -H 'Content-Type: application/json' -d '{"email":"x@x.tw","password":"x"}') "
done
echo "      $CODES"
echo "$CODES" | grep -q 429 && p "★★★ 登入端點有限流（出現 429）" || \
  f "★★★ 登入端點沒有限流 —— 可被暴力破解"

H=$(curl -sI "$API/api/v1/orders" -H 'Accept: application/json' --max-time 10)
echo "$H" | grep -qi 'x-ratelimit-limit' && \
  p "有 X-RateLimit 標頭：$(echo "$H"|grep -i x-ratelimit-limit|tr -d '\r')" || \
  printf '  \033[33m⚠\033[0m 沒有 X-RateLimit 標頭\n'

# ═══ 【4】★★★ 安全標頭 ═══
echo -e "\n【4】★★★ 安全標頭"
H=$(curl -skI "$API/api/health/live" --max-time 10)
for hdr in 'strict-transport-security' 'x-content-type-options'; do
    echo "$H" | grep -qi "$hdr" && p "$hdr" || f "缺少 $hdr"
done
echo "$H" | grep -qi 'cache-control:.*no-store' && p "★★ API 回應不快取" || \
  printf '  \033[33m⚠\033[0m API 回應沒有 no-store\n'
echo "$H" | grep -qi 'x-powered-by' && f "★ 洩漏 X-Powered-By" || p "★ 不洩漏 X-Powered-By"

# ═══ 【5】★★★ 敏感檔案 ═══
echo -e "\n【5】★★★ 敏感檔案"
for pth in /.env /.git/config /composer.json /storage/logs/laravel.log \
           /storage/x.jpg/y.php /artisan; do
    C=$(code "$API$pth")
    { [ "$C" = 404 ] || [ "$C" = 403 ]; } && p "$pth ($C)" || f "$pth 可存取 ($C)"
done

# ═══ 【6】★★ 真實 IP ═══
echo -e "\n【6】★★ 真實 IP 與 HTTPS"
W=$(curl -s "$API/api/health/version" -H 'Accept: application/json' --max-time 10)
# ★ 若有 whoami 端點
IP=$(curl -s "$API/api/v1/whoami" -H 'Accept: application/json' 2>/dev/null | jq -r '.ip // empty')
if [ -n "$IP" ]; then
    [ "$IP" != "127.0.0.1" ] && p "★★ 真實 IP：$IP" || \
      f "★★★ IP 是 127.0.0.1 —— TrustProxies 沒設好（★ 限流會失效）"
fi

# ═══ 【7】★★ 資料洩漏 ═══
echo -e "\n【7】★★ 回應欄位檢查（★ 需要登入的 cookie）"
if [ -f "$COOKIE" ]; then
    LEAK=$(curl -s "$API/api/v1/users" -H 'Accept: application/json' -b "$COOKIE" 2>/dev/null | \
           jq -r '(.data[0] // .[0] // {}) | keys[]' 2>/dev/null | \
           grep -iE 'password|remember_token|api_token|secret|salary|internal' || true)
    [ -z "$LEAK" ] && p "★★ 沒有洩漏敏感欄位" || \
      { f "★★★ 回應中有敏感欄位"; echo "$LEAK" | sed 's/^/      /'; }
else
    printf '  \033[33m⚠\033[0m 沒有登入 cookie，跳過（★ 建議手動檢查）\n'
fi

echo -e "\n═══ ✓ $PASS  ✗ $FAIL ═══"
[ "$FAIL" -eq 0 ] || exit 1
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **錯誤時回傳 HTML** ★★★ | 沒有 `Accept: application/json` | `ForceJsonResponse` middleware |
| **500 錯誤看不到原因** ★★ | `APP_DEBUG=false`（正確） | 用 `trace_id` 查日誌 |
| **限流沒生效** ★★★ | cache driver 是 file | `CACHE_STORE=redis` |
| **所有人共用限流配額** ★★★ | `$request->ip()` 是 127.0.0.1 | 設好 `TrustProxies` |
| **一個人被限流全機關被鎖** ★★ | 限流 key 用 IP | 登入後改用 `user:id` |
| **回應洩漏敏感欄位** ★★★ | 直接回傳 Model | 用 API Resource |
| **N+1 查詢** ★★ | 沒有 eager load | `->with([...])` + `whenLoaded()` |
| `/up` 端點 404 | 沒設 `health:` | `withRouting(health: '/up')` |
| **健康檢查洩漏資訊** ★★ | `/health/ready` 公開 | 限制來源 IP |
| API 文件公開 ★★ | 沒設 Gate | `viewApiDocs` Gate + IP 限制 |
| 版本無法共存 | 路由結構混亂 | 用 `Route::prefix('v1')` |
| **CORS preflight 每次都發** ★ | `max_age` 太小 | 設 86400 |

### 排查

```bash
API=https://api.example.gov.tw

# 【1】★★★ 錯誤格式
$ curl -s "$API/api/v1/nope" | head -c 200
$ curl -s "$API/api/v1/nope" -H 'Accept: application/json' | jq

# 【2】★★ 用 trace_id 查日誌
$ TID=$(curl -s "$API/api/v1/broken" -H 'Accept: application/json' | jq -r .trace_id)
$ sudo grep "$TID" /var/www/api/shared/storage/logs/laravel-*.log | jq -r '.message, .file'

# 【3】★★★ 限流
$ for i in $(seq 1 10); do
    curl -so /dev/null -w '%{http_code} ' "$API/api/v1/login" -X POST \
      -H 'Accept: application/json' -d '{}'
  done; echo

# ★ 檢查用哪個 store
$ php artisan config:show cache.default
$ redis-cli -a "$REDIS_PASSWORD" keys 'laravel_database_*throttle*' | head

# 【4】★★★ 真實 IP
$ curl -s "$API/api/v1/whoami" -H 'Accept: application/json' | jq
# ★ 或看 Laravel 日誌中記錄的 IP

# 【5】★★ 路由清單
$ php artisan route:list --path=api --json | \
    jq -r '.[] | "\(.method)\t\(.uri)\t\(.middleware|join(","))"' | head -30

# ★★ 找出沒有 auth 的端點
$ php artisan route:list --path=api --json | \
    jq -r '.[] | select((.middleware|join(","))|contains("auth")|not) | "\(.method) \(.uri)"'

# ★★ 找出沒有 throttle 的端點
$ php artisan route:list --path=api --json | \
    jq -r '.[] | select((.middleware|join(","))|contains("throttle")|not) | "\(.method) \(.uri)"'

# 【6】健康檢查
$ curl -s "$API/api/health/ready" | jq
$ curl -s "$API/api/health/version" | jq

# 【7】★ 慢端點
$ awk '{for(i=1;i<=NF;i++) if($i ~ /^rt=/) {gsub("rt=","",$i); if($i+0 > 1) print $i, $7}}' \
    /var/log/nginx/api.access.log | sort -rn | head -10
```

---

## 安全性注意事項

> [!danger] API 的四條紅線 ★★★
> ```
> ① ★★★★ 不要直接回傳 Model
>      → 洩漏 password（雜湊）、token、內部欄位
>      → ★ 用 API Resource（白名單）
>
> ② ★★★★ 每個端點都要有授權檢查
>      → $this->authorize() 或查詢範圍限制
>      → ★★ 用 route:list 掃描沒有 auth middleware 的端點
>
> ③ ★★★ 登入端點必須限流
>      → 5 次/分鐘（依 IP）+ 3 次/分鐘（依 email）
>      → ★ 沒有限流 = 可暴力破解
>
> ④ ★★ 錯誤訊息不要洩漏資訊
>      → 「帳號或密碼錯誤」（★ 不要說「這個帳號不存在」）
>      → 500 錯誤不要顯示 stack trace
>      → ★ 用 trace_id 讓使用者回報，細節只在日誌裡
> ```

```bash
# ★★★ 掃描沒有保護的端點
$ php artisan route:list --path=api --json | jq -r '
  .[] |
  select((.middleware | join(",")) | (contains("auth") | not)) |
  "\(.method)\t\(.uri)"' | grep -vE 'health|login|register|csrf'
# ★ 有輸出的都要確認是否真的可以公開
```

```php
<?php
// ★★ 統一的錯誤訊息（★ 不洩漏帳號是否存在）
public function login(LoginRequest $request)
{
    $user = User::where('email', $request->email)->first();

    // ❌ 洩漏帳號存在與否
    // if (!$user) return response()->json(['message' => '此帳號不存在'], 404);
    // if (!Hash::check(...)) return response()->json(['message' => '密碼錯誤'], 401);

    // ✅ ★★ 統一的訊息
    if (!$user || !Hash::check($request->password, $user->password)) {
        // ★ 記錄（給稽核用）
        Log::channel('security')->warning('登入失敗', [
            'email' => $request->email,
            'ip'    => $request->ip(),
            'exists'=> (bool) $user,        // ★ 只記在日誌，不回傳給客戶端
        ]);
        throw ValidationException::withMessages([
            'email' => ['帳號或密碼錯誤'],
        ]);
    }

    // ★★ 檢查帳號狀態（★ 也用統一的訊息或明確但不洩漏的訊息）
    if (!$user->is_active) {
        throw ValidationException::withMessages([
            'email' => ['此帳號已停用，請聯絡管理員'],
        ]);
    }

    // ★★ 時序攻擊防護：即使帳號不存在也要花一樣的時間
    // → Hash::check 已經有 constant-time 比較
    // → ★ 但「查不到使用者就直接返回」會比較快
    // → 可以在查不到時也執行一次假的 Hash::check
}
```

```php
<?php
// ★★ 防時序攻擊的完整寫法
$user = User::where('email', $request->email)->first();
$hash = $user?->password ?? '$2y$12$'.str_repeat('x', 53);   // ★ 假的雜湊
$valid = Hash::check($request->password, $hash) && $user !== null;
if (!$valid) { /* 統一的錯誤 */ }
```

---

## 速查表

### ★★★ API 專用設定

```php
// bootstrap/app.php
->withRouting(api: __DIR__.'/../routes/api.php', health: '/up')
->withMiddleware(function (Middleware $m) {
    $m->trustProxies(at: ['127.0.0.1'], headers: ...HEADER_X_FORWARDED_PROTO);  // ★★★
    $m->statefulApi();                                    // ★★ Sanctum SPA
    $m->api(append: [ForceJsonResponse::class]);          // ★★★ 強制 JSON
    $m->throttleWithRedis();                              // ★★ 多台必須
})
```

### ★★★ 統一的錯誤格式

```json
{
  "message": "輸入資料有誤",
  "code": "VALIDATION_ERROR",
  "trace_id": "018f2c1a-...",
  "errors": { "email": ["..."] }
}
```

```
★★★ 沒有 ForceJsonResponse → 錯誤時回傳 HTML → 前端 Unexpected token '<'
★★ trace_id 讓使用者回報時能快速定位日誌
```

### ★★ 限流

```php
RateLimiter::for('api', fn ($r) => $r->user()
    ? Limit::perMinute(300)->by('user:'.$r->user()->id)
    : Limit::perMinute(60)->by('ip:'.$r->ip()));

RateLimiter::for('login', fn ($r) => [
    Limit::perMinute(5)->by('ip:'.$r->ip()),
    Limit::perMinute(3)->by('email:'.$r->input('email')),   // ★★
]);
```

```
★★★ 三個陷阱：
  ① 多台伺服器 → CACHE_STORE=redis
  ② IP 是 127.0.0.1 → TrustProxies 沒設 → 全部人共用配額
  ③ key 用 IP → 同機關共用對外 IP → 一人被鎖全部被鎖
```

### 健康檢查

```
/api/health/live     ★ 極輕量，公開
/api/health/ready    ★★ 檢查 DB/Redis/磁碟，限制 IP
/api/health/version  ★ 部署驗證用，限制 IP
```

### ★★★ 資料洩漏防護

```php
// ❌ 直接回 Model → 洩漏 password/token/內部欄位
Route::get('/users/{user}', fn (User $u) => $u);

// ✅ API Resource（白名單）
return new UserResource($user);

// ★★ 依權限顯示
$this->when($request->user()?->can('...'), $this->phone)
$this->mergeWhen($request->user()?->hasRole('admin'), [...])
$this->whenLoaded('roles')       // ★ 避免 N+1
```

### API 版本

```php
Route::prefix('v1')->group(...);      // ★★ URL 路徑（推薦）
Route::prefix('v2')->group(...);      // ★ 只覆寫變動的端點
```

```php
// ★ 淘汰通知（RFC 8594）
$response->headers->set('Deprecation', 'true');
$response->headers->set('Sunset', 'Sun, 31 Dec 2026 23:59:59 GMT');
```

### ★★★ 掃描

```bash
# 沒有 auth 的端點
php artisan route:list --path=api --json | \
  jq -r '.[] | select((.middleware|join(","))|contains("auth")|not) | .uri'

# 沒有 throttle 的端點
php artisan route:list --path=api --json | \
  jq -r '.[] | select((.middleware|join(","))|contains("throttle")|not) | .uri'

# 回應欄位
curl -s https://api/api/v1/users -b c.txt | jq '.data[0] | keys'

verify-api https://api.example.gov.tw
```

---

## 練習題

> [!question]- 練習 1：JSON 錯誤處理 ★★★
> 1. **不加 `ForceJsonResponse`**
> 2. `curl https://api/api/v1/nope`（**不帶 Accept**）→ **回傳什麼？**
> 3. 加上 `-H 'Accept: application/json'` → 呢？
> 4. 加上 middleware 再測
> 5. **故意觸發一個 500** → 正式環境看得到 stack trace 嗎？
> 6. 用 `trace_id` 在日誌裡找到那個錯誤

> [!question]- 練習 2：限流的三個陷阱 ★★★
> 1. `CACHE_STORE=file`，開兩個 PHP-FPM pool 模擬多台
> 2. 打 API 直到被限流 → **實際擋在第幾次？**
> 3. 改成 `redis` → 再測
> 4. **拿掉 TrustProxies** → `whoami` 的 IP 是什麼？
> 5. 用兩台不同的機器打 API → **會互相影響嗎？**
> 6. 加回 TrustProxies → 再測

> [!question]- 練習 3：資料洩漏 ★★★
> 1. 寫一個直接回傳 Model 的端點
> 2. `curl | jq 'keys'` → **有哪些欄位？**
> 3. 在 Model 加一個 `internal_note` 欄位 → 再測 → **洩漏了嗎？**
> 4. 改用 API Resource
> 5. **再加一個新欄位** → 這次會洩漏嗎？
> 6. **寫下白名單 vs 黑名單的差別**

> [!question]- 練習 4：端點掃描
> 1. `php artisan route:list --path=api --json | jq` 看完整結構
> 2. 用 jq 找出**沒有 auth middleware** 的端點
> 3. 用 jq 找出**沒有 throttle** 的端點
> 4. **逐一檢查每一個是否真的可以公開**
> 5. 補上缺少的 middleware
> 6. **把掃描加進 CI**

> [!question]- 練習 5：完整的 API 驗證
> 1. 部署 `verify-api` 腳本
> 2. 執行 → **有幾項 ✗？**
> 3. 逐一修復
> 4. **故意製造每一種問題**看腳本能不能抓到：
>    - 移除 `ForceJsonResponse`
>    - 移除登入的 throttle
>    - 直接回傳 Model
> 5. 加進部署流程

---

## 小測驗

Q1. **為什麼 API 需要 `ForceJsonResponse` middleware**？

Q2. **`trace_id` 的作用是什麼**？

Q3. **限流的三個陷阱是什麼**？

Q4. **為什麼限流的 key 登入後應該改用 `user:id`**？

Q5. **API 版本控制的三種做法？哪一種最推薦**？

Q6. **健康檢查該分成哪幾層？為什麼要限制存取**？

Q7. **為什麼不能直接回傳 Eloquent Model**？

Q8. **Model 的 `$hidden` 與 API Resource 有什麼根本差別**？

Q9. **登入失敗的錯誤訊息該怎麼寫**？

Q10. **怎麼掃描出沒有授權保護的 API 端點**？

> [!question]- 測驗答案
> **Q1.** 因為 **Laravel 依 `Accept` 標頭決定回應格式** ——
> 如果客戶端沒有送 `Accept: application/json`，
> **例外處理會回傳 HTML 錯誤頁**（Laravel 的預設錯誤頁面）。
> **症狀**：正常的請求都好好的，
> **但一旦發生錯誤（驗證失敗、404、500），前端收到的是 HTML**，
> `JSON.parse` 失敗 → `Unexpected token '<'`，
> 前端完全拿不到錯誤訊息。
> `ForceJsonResponse` 在 middleware 中強制設定
> `$request->headers->set('Accept', 'application/json')`，
> 讓所有 API 路徑的錯誤都回傳 JSON。
> **最好前後端都做**：前端一律送 `Accept` 標頭（最正確），
> 後端用 middleware 保險。
>
> **Q2.** **`trace_id` 是每個錯誤回應中的唯一識別碼**，
> 同時**寫進伺服器日誌**與**回傳給客戶端**。
> **價值**：使用者回報「系統壞了」時，
> **不用從幾千行日誌裡找**，直接 grep 那個 ID 就能定位：
> ```bash
> grep '018f2c1b-' /var/www/api/shared/storage/logs/*.log
> ```
> **前端也要顯示**：「系統發生錯誤（代碼：018f2c1b），請聯絡管理員」。
> **這也解決了「正式環境不能顯示 stack trace」與
> 「需要足夠資訊來除錯」的矛盾** ——
> 給使用者的是無害的 ID，技術細節只留在日誌裡。
>
> **Q3.** ①**★★★ 多台伺服器時必須用 Redis** ——
> 預設用 cache driver，若是 `file`/`array` 則**每台各算各的**，
> 3 台伺服器等於實際限制是 3 倍
> （解法：`CACHE_STORE=redis` + `$middleware->throttleWithRedis()`）；
> ②**★★★ 反向代理後面的 IP** ——
> 沒設 `TrustProxies` 時 `$request->ip()` **永遠是 `127.0.0.1`**，
> **所有使用者共用同一個限流配額**，一個人打太多全部人被鎖；
> ③**★★ 限流的 key 不夠精確** ——
> 用 IP 的話，**同一個機關的所有人共用一個對外 IP**，
> 一個人觸發限流，整個機關被鎖。
>
> **Q4.** 因為 **同一個機關（或同一棟大樓、同一個 NAT 後面）的所有使用者
> 共用同一個對外 IP** ——
> 如果限流的 key 是 IP，**一個人的異常行為會鎖住整個機關的人**。
> **登入後改用 `user:id` 就精確到個人**：
> ```php
> RateLimiter::for('api', fn ($r) => $r->user()
>     ? Limit::perMinute(300)->by('user:'.$r->user()->id)     // ★ 已登入
>     : Limit::perMinute(60)->by('ip:'.$r->ip()));            // ★ 未登入只能用 IP
> ```
> **登入端點本身仍要用 IP**（因為還沒有使用者身分），
> 但**同時加上依 email 的限制**（防止針對特定帳號的暴力破解）。
>
> **Q5.** ①**URL 路徑**（`/api/v1/users`）—— **最推薦**：
> 最直覺、易於快取、易於除錯（從網址就看得出版本）、
> 反向代理可以依路徑分流。缺點是網址會變。
> ②**標頭**（`Accept: application/vnd.api.v1+json`）——
> 網址不變，但**除錯麻煩**（curl 要多帶標頭）、**快取困難**（要設 `Vary`）。
> ③**查詢參數**（`?version=1`）—— 簡單但**容易被忽略**，也有快取問題。
> **實務建議**：用 URL 路徑，
> 新版**只覆寫有變動的端點**（其他沿用舊版的 Controller），
> 舊版加上 `Deprecation` 與 `Sunset` 標頭（RFC 8594），
> **監控舊版的使用量降到 0 才下線**。
>
> **Q6.** **三層**：
> ①**`/health/live`（liveness）** —— **極輕量**，只回 `{"status":"ok"}`，
> 用來判斷「程序還活著嗎」（給 k8s 的 liveness probe 或負載平衡器）；
> ②**`/health/ready`（readiness）** ——
> 檢查**相依服務**（資料庫、Redis、儲存空間、磁碟），
> 用來判斷「可以接受流量嗎」；
> ③**`/health/version`** —— 版本資訊，**部署後驗證用**。
> **為什麼要限制存取**：
> `/health/ready` 會**洩漏內部架構**（哪些相依服務存在）、
> **服務的健康狀態**（攻擊者知道什麼時候該攻擊）、
> **版本資訊**（可對應到已知漏洞）。
> 建議 `live` 公開，`ready` 與 `version` 限制來源 IP。
>
> **Q7.** 因為 **Eloquent Model 的 `toJson()` 會輸出「所有欄位」**，
> 包含：**`password`（雜湊值）**、**`remember_token`**、**`api_token`**、
> 以及各種內部欄位（`internal_notes`、`is_admin`、`salary`、
> `deleted_at`、外鍵 ID）。
> ```php
> Route::get('/users/{user}', fn (User $user) => $user);   // ❌
> ```
> 密碼雜湊外洩後可以離線暴力破解；
> 內部欄位洩漏商業邏輯與個資。
> **正確做法是用 API Resource 明確列出要輸出的欄位**，
> 並用 `when()` / `mergeWhen()` 依權限決定顯示範圍。
>
> **Q8.** **`$hidden` 是「黑名單」，API Resource 是「白名單」**。
> **`$hidden` 的問題**：
> **新增了一個敏感欄位但忘了加進 `$hidden` → 直接洩漏**；
> 而且 `->makeVisible()` 可以繞過它，
> 某些序列化路徑也可能不生效。
> **API Resource 的優勢**：
> **明確列出要輸出的欄位，新增的欄位「預設不會輸出」** ——
> 這是**安全的預設**（fail-safe）。
> 而且 Resource 可以**依權限動態決定**輸出內容
> （`when()` / `mergeWhen()`），
> 也能用 `whenLoaded()` 避免 N+1。
> **兩個都做**：`$hidden` 當第二道防線，Resource 是主要控制。
>
> **Q9.** **必須用「統一的訊息」，不能洩漏帳號是否存在**：
> ```php
> // ❌ 洩漏
> if (!$user) return ['message' => '此帳號不存在'];
> if (!Hash::check(...)) return ['message' => '密碼錯誤'];
>
> // ✅ 統一
> if (!$user || !Hash::check($request->password, $user->password)) {
>     throw ValidationException::withMessages(['email' => ['帳號或密碼錯誤']]);
> }
> ```
> **原因**：能分辨「帳號不存在」與「密碼錯誤」的話，
> 攻擊者可以**列舉出系統中有哪些帳號**（帳號列舉攻擊），
> 再針對那些帳號做暴力破解或社交工程。
> **進階**：還要防**時序攻擊** ——
> 「查不到使用者就直接返回」比「執行 `Hash::check`」快很多，
> 攻擊者可以從回應時間推測帳號是否存在。
> 解法是查不到時也執行一次假的 `Hash::check`。
> **真實原因記在日誌裡**（給稽核用），不回傳給客戶端。
>
> **Q10.** **用 `route:list --json` 配合 jq 過濾**：
> ```bash
> # ★ 沒有 auth middleware 的端點
> php artisan route:list --path=api --json | jq -r '
>   .[] | select((.middleware | join(",")) | (contains("auth") | not)) |
>   "\(.method)\t\(.uri)"' | grep -vE 'health|login|register|csrf'
>
> # ★ 沒有 throttle 的端點
> php artisan route:list --path=api --json | jq -r '
>   .[] | select((.middleware | join(",")) | (contains("throttle") | not)) | .uri'
> ```
> **有輸出的都要逐一確認是否真的可以公開**
> （健康檢查、登入、註冊是合理的例外）。
> **但要注意**：有 `auth` middleware 只代表「需要登入」，
> **不代表有「授權」檢查** ——
> IDOR 漏洞（登入者能存取別人的資料）需要另外用
> `$this->authorize()` 或查詢範圍限制來防護，
> 這部分要靠**人工檢視 Controller** 或**兩帳號的實際測試**。
> **把這兩個掃描加進 CI**，新增端點時就會被檢查到。

---

## 延伸閱讀

- [[03-跨網域與CORS設定]] — CORS 的完整設定
- [[04-認證串接-Sanctum與JWT]] — 認證的實作細節
- [[09-前後端分離常見問題排查]] — 問題排查
- [[07-Laravel-正式環境安全檢查表]] — 完整的安全檢查
- [[02-Laravel-Nginx與PHP-FPM設定]] — Nginx 與 FPM
- [[01-前後端分離架構選型]] — 拓撲的選擇
