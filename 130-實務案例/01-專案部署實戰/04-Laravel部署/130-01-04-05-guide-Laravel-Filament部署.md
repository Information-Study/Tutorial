---
title: "Laravel Filament 部署"
desc: "Filament v3/v4 的正式環境部署、資產發布、權限控管與效能調校"
aliases: [Filament, filament:optimize, Panel, 後台部署, Livewire]
tags: [群組/實務案例, 主題/部署, 主題/Laravel, 主題/LXMP]
category: 專案部署實戰
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[130-01-04-04-guide-Laravel-快取最佳化與部署流程]]"]
updated: 2026-08-28
---

# Laravel Filament 部署

> [!abstract] 這篇你會學到
> - **Filament 是什麼**（與 Nova 的差別）
> - **正式環境的安裝與資產發布**
> - **★★★ `filament:optimize`** 與部署流程整合
> - **★★★ 存取控管**（`canAccessPanel` 是必須的）
> - **Livewire** 的部署注意事項（★ 與 Nginx / WAF 的互動）
> - **檔案上傳**與 storage 設定
> - **效能調校**與常見問題

## 前置知識

- [[130-01-04-04-guide-Laravel-快取最佳化與部署流程]] — 部署流程
- [[130-01-04-02-guide-Laravel-Nginx與PHP-FPM設定]] — Nginx 與 FPM

---

## Filament 是什麼 ★★

```
Filament = 基於 TALL stack 的 Laravel 後台框架
  T = Tailwind CSS
  A = Alpine.js
  L = Livewire        ★★ 關鍵：伺服器端渲染的互動元件
  L = Laravel
```

| | **Filament** | **Nova** |
| --- | --- | --- |
| 授權 | **✓ MIT（免費）** | ✗ 商業授權（$99/專案起） |
| 底層 | **Livewire**（TALL） | Vue 3 + Inertia |
| 客製化 | ★★ 非常彈性 | 中等 |
| **部署複雜度** | ★ 中（需要 `filament:optimize`） | ★★ 高（需要 `auth.json`） |
| 前端建置 | ★ 通常不需要（★ 除非自訂主題） | 需要 |
| 學習曲線 | 中 | 低 |
| 社群 | ★★ 非常活躍 | 官方支援 |

> [!tip] Livewire 的部署意義 ★★
> ```
> ★★ Livewire = 每次互動都發一個 POST 請求回伺服器
>   → 伺服器重新渲染元件並回傳 HTML diff
>
> ★★ 部署上的影響：
>   ① ★★ 請求數量遠多於傳統的 SPA
>      → PHP-FPM 的 pm.max_children 要夠
>   ② ★★★ WAF（ModSecurity）容易誤判
>      → Livewire 的 payload 是 JSON，含序列化的元件狀態
>   ③ ★ 需要 session（★ cluster 環境要用 Redis）
>   ④ ★ 上傳檔案走 Livewire 的臨時上傳機制
> ```

---

## 安裝與部署 ★★

```bash
# ═══ 安裝（★ 在開發機做，commit 進 git）═══
$ composer require filament/filament:"^3.3"
$ php artisan filament:install --panels
$ php artisan make:filament-user
```

```bash
# ═══════ ★★★ 正式環境的部署步驟 ═══════
$ cd /var/www/api/current

# ① composer（★ --no-dev）
$ composer install --no-dev --optimize-autoloader --no-interaction

# ② ★★★ Filament 的最佳化（★ 這是關鍵）
$ php artisan filament:optimize
   INFO  Caching Filament components.
   INFO  Caching Blade icons.

# ★ 等同於：
#   php artisan filament:cache-components
#   php artisan icons:cache

# ③ Laravel 的一般最佳化
$ php artisan optimize

# ④ ★★ 發布資產（★ 見下方說明）
$ php artisan filament:assets
```

> [!danger] `filament:optimize` 是必要的 ★★★
> ```
> ★★ 不執行的後果：
>   ① Filament 每次請求都要【掃描整個專案】找 Resource、Page、Widget
>      → ★★ 大專案可能多花 200~500ms
>   ② Blade icon 每次都要從檔案系統讀取 SVG
>      → ★ 一個頁面可能有幾十個圖示
>
> ★★★ 但要注意：
>   filament:cache-components 產生的快取【綁定檔案路徑】
>   → ★★ 與 config:cache 一樣，部署後必須重新產生
>   → releases 佈局下路徑會變，所以【每次部署都要跑】
>
> ★ 清除：php artisan filament:optimize-clear
> ```

### ★★ 資產（assets）

```bash
# ★★ Filament 的 CSS/JS 需要發布到 public/
$ php artisan filament:assets

$ ls -la public/
drwxr-xr-x  css/
drwxr-xr-x  js/
drwxr-xr-x  ★ vendor/            # ★★ Filament 的資產在這裡
    ├── filament/
    │   ├── filament/app.css
    │   ├── filament/app.js
    │   └── forms/forms.js
    ├── livewire/livewire.js      # ★★ Livewire 的核心
    └── ...
```

> [!warning] `public/vendor/` 不要進 git ★★
> ```
> ★ Filament 的資產是【由 composer 套件產生的】
>   → 每次 composer update 後可能變更
>   → ★★ 應該在【部署時產生】而不是 commit 進 git
>
> .gitignore：
>   /public/vendor/
>   /public/css/filament/
>   /public/js/filament/
>
> ★★★ 但要記得部署腳本一定要跑 php artisan filament:assets
>    → 否則後台的 CSS/JS 全部 404 → 版面完全爛掉
> ```

```bash
# ★★ 驗證資產有發布
$ ls -la public/vendor/filament/ 2>/dev/null | head
$ curl -sI https://api.example.gov.tw/vendor/filament/filament/app.css | head -1
HTTP/2 200

$ curl -sI https://api.example.gov.tw/vendor/livewire/livewire.js | head -1
HTTP/2 200
```

```nginx
# ★★ Nginx：Filament 資產的快取設定
location ^~ /vendor/ {
    try_files $uri =404;
    expires 30d;                    # ★ 不是 1y（★ 檔名沒有 hash）
    add_header Cache-Control "public, max-age=2592000";
    add_header X-Content-Type-Options "nosniff" always;
    access_log off;
}

# ★★ Livewire 的資產有版本查詢字串，可以長快取
location = /vendor/livewire/livewire.js {
    try_files $uri =404;
    expires 1y;
    add_header Cache-Control "public, max-age=31536000";
    add_header X-Content-Type-Options "nosniff" always;
}
```

> [!danger] Filament 資產沒有內容 hash ★★
> ```
> ★★ /vendor/filament/filament/app.css 這個檔名【永遠一樣】
>   → 內容更新後檔名不變
>     → ★★ 瀏覽器會用舊的快取 → 版面錯亂
>
> ★★ 三種解法：
>   ① expires 30d（★ 不要用 1y）
>   ② ★★ Filament 會自動加版本查詢字串：
>        app.css?v=3.3.14
>      → 升級版本後 URL 就變了 → 自動失效
>   ③ ★ 部署後清 CDN 快取
>
> ★ 檢查實際輸出的 URL：
>   curl -s https://api/admin/login | grep -oE '/vendor/filament[^"]*'
> ```

---

## ★★★ 存取控管

> [!danger] 沒有實作 `canAccessPanel` = 任何登入者都能進後台 ★★★
> ```
> ★★★ Filament 的預設行為：
>   · 開發環境（APP_ENV=local）：任何已登入的使用者都能存取
>   · ★★ 正式環境：也是【任何已登入的使用者】
>     （★ 不像 Horizon 那樣預設拒絕）
>
> → ★★★ 若你的網站有一般使用者註冊功能
>   → 【任何人註冊後都能進管理後台】
>     → 看到所有資料、可以新增修改刪除
>
> ★★★ 必須實作 FilamentUser 介面
> ```

```php
<?php
// ★★★ app/Models/User.php
namespace App\Models;

use Filament\Models\Contracts\FilamentUser;
use Filament\Panel;
use Illuminate\Foundation\Auth\User as Authenticatable;

class User extends Authenticatable implements FilamentUser
{
    // ★★★ 這個方法決定誰能進後台
    public function canAccessPanel(Panel $panel): bool
    {
        // ── 方式 ①：用角色 ──
        return $this->hasRole(['admin', 'editor']);

        // ── 方式 ②：用欄位 ──
        // return $this->is_admin === true && $this->is_active;

        // ── 方式 ③：★ 依 panel 分權 ──
        // return match ($panel->getId()) {
        //     'admin'  => $this->hasRole('admin'),
        //     'staff'  => $this->hasRole(['admin', 'staff']),
        //     default  => false,
        // };

        // ── ★ 方式 ④：email 網域白名單（★ 內部系統常用）──
        // return str_ends_with($this->email, '@example.gov.tw')
        //     && $this->hasVerifiedEmail()
        //     && $this->is_active;
    }
}
```

```php
<?php
// ★★ Panel 的完整設定
// app/Providers/Filament/AdminPanelProvider.php
namespace App\Providers\Filament;

use Filament\Http\Middleware\Authenticate;
use Filament\Http\Middleware\DisableBladeIconComponents;
use Filament\Http\Middleware\DispatchServingFilamentEvent;
use Filament\Panel;
use Filament\PanelProvider;
use Filament\Support\Colors\Color;
use Illuminate\Cookie\Middleware\AddQueuedCookiesToResponse;
use Illuminate\Cookie\Middleware\EncryptCookies;
use Illuminate\Foundation\Http\Middleware\ValidatePostSize;
use Illuminate\Routing\Middleware\SubstituteBindings;
use Illuminate\Session\Middleware\AuthenticateSession;
use Illuminate\Session\Middleware\StartSession;
use Illuminate\View\Middleware\ShareErrorsFromSession;
use Illuminate\Cookie\Middleware\EncryptCookies as Encrypt;

class AdminPanelProvider extends PanelProvider
{
    public function panel(Panel $panel): Panel
    {
        return $panel
            ->default()
            ->id('admin')
            ->path('admin')                       // ★★ https://api/admin
            ->login()
            // ->registration()                   // ★★★ 正式環境【絕對不要】開放註冊
            // ->passwordReset()                  // ★ 內部系統通常不需要
            ->colors(['primary' => Color::Blue])
            ->brandName('機關管理系統')
            ->favicon(asset('favicon.ico'))
            ->discoverResources(in: app_path('Filament/Resources'), for: 'App\\Filament\\Resources')
            ->discoverPages(in: app_path('Filament/Pages'), for: 'App\\Filament\\Pages')
            ->discoverWidgets(in: app_path('Filament/Widgets'), for: 'App\\Filament\\Widgets')
            ->middleware([
                EncryptCookies::class,
                AddQueuedCookiesToResponse::class,
                StartSession::class,
                AuthenticateSession::class,        // ★★ 密碼變更時使其他 session 失效
                ShareErrorsFromSession::class,
                \Illuminate\Foundation\Http\Middleware\VerifyCsrfToken::class,
                SubstituteBindings::class,
                DisableBladeIconComponents::class,
                DispatchServingFilamentEvent::class,
            ])
            ->authMiddleware([
                Authenticate::class,
            ])
            // ★★ 閒置自動登出
            ->sidebarCollapsibleOnDesktop()
            ->maxContentWidth('full')
            ->spa();                              // ★ SPA 模式（★ 導覽更快）
    }
}
```

> [!danger] 三個必須關掉的功能 ★★★
> ```php
> ->registration()          // ★★★ 開放註冊 = 任何人都能建立帳號
> ->passwordReset()         // ★ 內部系統通常不需要（★ 可能被用來探測帳號是否存在）
> ->emailVerification()     // ★ 若沒有郵件伺服器，開了會卡住登入流程
> ```
>
> ```
> ★★★ 特別是 registration()：
>   若同時沒有實作 canAccessPanel
>   → ★★★ 【任何人都能註冊並進入管理後台】
>     → 這是最嚴重的設定錯誤
> ```

```bash
# ★★★ 上線前必測
$ curl -so /dev/null -w '%{http_code}\n' https://api.example.gov.tw/admin/register
404                                    # ★★ 必須是 404

# ★ 用一個「非管理員」的帳號登入後存取 /admin
# → ★★★ 必須被拒絕（403 或導回首頁）
```

### Nginx 層的額外保護

```nginx
# ★★ 管理後台限制來源（★ 第二道防線）
location ^~ /admin {
    allow 10.0.0.0/8;                # ★ 內部網段
    allow 172.16.0.0/12;
    allow 203.0.113.0/24;            # ★ 特定的外部辦公室
    deny all;

    limit_req zone=api_general burst=30 nodelay;
    try_files $uri $uri/ /index.php?$query_string;
}

# ★★ 登入端點的嚴格限流
location = /admin/login {
    limit_req zone=api_login burst=3 nodelay;
    limit_req_status 429;
    allow 10.0.0.0/8;
    deny all;
    try_files $uri $uri/ /index.php?$query_string;
}
```

```php
<?php
// ★★ 或用 Laravel 的 middleware（更彈性）
// app/Http/Middleware/RestrictAdminIp.php
public function handle(Request $request, Closure $next): Response
{
    $allowed = config('security.admin_ips', []);
    if (!empty($allowed) && !IpUtils::checkIp($request->ip(), $allowed)) {
        Log::warning('管理後台的未授權存取', [
            'ip' => $request->ip(),
            'ua' => $request->userAgent(),
            'path' => $request->path(),
        ]);
        abort(403);
    }
    return $next($request);
}
```

```php
<?php
// config/security.php
return [
    'admin_ips' => array_filter(explode(',', env('ADMIN_ALLOWED_IPS', ''))),
];
```

```dotenv
ADMIN_ALLOWED_IPS=10.0.0.0/8,172.16.0.0/12,203.0.113.5
```

---

## Livewire 的部署注意事項 ★★

### ★★★ ModSecurity 誤判

> [!danger] Livewire 的 payload 極容易被 WAF 誤判 ★★★
> ```
> ★★ Livewire 每次互動都送一個 POST 到 /livewire/update
>   payload 是 JSON，包含：
>     · 序列化的元件狀態（★ 可能含 HTML、SQL 片段、base64）
>     · checksum
>     · 呼叫的方法與參數
>
> ★★★ OWASP CRS 很容易把它判定為：
>   · SQL injection（942xxx）—— 元件狀態裡有查詢條件
>   · XSS（941xxx）—— 富文字欄位的 HTML
>   · PHP injection（933xxx）—— 序列化的類別名稱
>
> ★★ 症狀：
>   · 後台的按鈕點了沒反應
>   · Console 顯示 403
>   · ★ 而且【只有某些操作】會發生（★ 極難重現）
> ```

```apache
# /etc/nginx/modsec/filament-exclusions.conf
# ★★ 放在 CRS 之後載入

# ═══ ★★★ Livewire 的端點整體放寬 ═══
SecRule REQUEST_URI "@beginsWith /livewire/" \
  "id:20001,phase:1,pass,nolog,\
   ctl:ruleRemoveByTag=attack-sqli,\
   ctl:ruleRemoveByTag=attack-xss,\
   ctl:ruleRemoveByTag=attack-injection-php,\
   ctl:ruleRemoveByTag=attack-rce,\
   ctl:ruleRemoveById=200002,\
   ctl:ruleRemoveById=200003"

# ═══ ★★ Filament 的檔案上傳 ═══
SecRule REQUEST_URI "@rx ^/livewire/upload-file" \
  "id:20002,phase:1,pass,nolog,\
   ctl:ruleEngine=DetectionOnly"

# ═══ ★ Filament 後台的表單提交 ═══
SecRule REQUEST_URI "@beginsWith /admin" \
  "id:20003,phase:2,pass,nolog,\
   ctl:ruleRemoveTargetById=942440;ARGS:_token,\
   ctl:ruleRemoveTargetByTag=attack-xss;ARGS:components"

# ═══ ★★ 請求大小（★ Livewire 的 payload 可能很大）═══
SecRequestBodyLimit 22020096
SecRequestBodyNoFilesLimit 2097152     # ★ 預設 128KB 太小
SecRequestBodyLimitAction ProcessPartial
```

```bash
# ★★ 找出誤判
$ sudo grep -oP 'id "\K\d+' /var/log/modsec_audit.log | sort | uniq -c | sort -rn | head
$ sudo grep 'livewire' /var/log/modsec_audit.log | grep -oP 'id "\K\d+' | sort -u

# ★ 看某條規則觸發的完整內容
$ sudo awk '/---.*-A--/{p=0} /942100/{p=1} p' /var/log/modsec_audit.log | head -50
```

> [!warning] 更務實的做法：後台不套 WAF ★★
> ```nginx
> # ★★ 管理後台已經有 IP 限制 + 登入驗證
> #    → WAF 的邊際效益低，誤判成本高
> location ^~ /admin {
>     modsecurity off;                  # ★★ 關掉 WAF
>     allow 10.0.0.0/8;                 # ★ 靠網路層與應用層保護
>     deny all;
>     try_files $uri $uri/ /index.php?$query_string;
> }
>
> location ^~ /livewire/ {
>     modsecurity off;                  # ★★
>     try_files $uri $uri/ /index.php?$query_string;
> }
> ```
>
> ```
> ★★ 這是安全與可用性的權衡：
>   · ★ 前台（公開端點）→ 開 WAF
>   · ★★ 後台（已有 IP 限制 + 認證）→ 可以關 WAF
>
> ★★★ 前提是後台【確實有】IP 限制與嚴格的認證
> ```

### 檔案上傳

```php
<?php
// ★★ Filament 的檔案上傳
use Filament\Forms\Components\FileUpload;

FileUpload::make('attachment')
    ->disk('public')                       // ★ storage/app/public
    ->directory('attachments/' . date('Y/m'))
    ->visibility('public')
    ->maxSize(20480)                       // ★★ KB（★ 要與 PHP/Nginx 一致）
    ->acceptedFileTypes(['application/pdf', 'image/jpeg', 'image/png'])
    ->preserveFilenames(false)             // ★★★ 不保留原始檔名（防路徑遍歷與覆蓋）
    ->imageEditor()
    ->downloadable()
    ->openable()
    // ★★ 自訂檔名（更安全）
    ->getUploadedFileNameForStorageUsing(
        fn ($file) => (string) str()->uuid() . '.' . $file->getClientOriginalExtension()
    );
```

> [!danger] `preserveFilenames(true)` 的風險 ★★★
> ```
> ★★★ 保留使用者上傳的原始檔名：
>   · 路徑遍歷：../../etc/passwd
>     （★ Laravel 有處理，但仍不建議冒險）
>   · 覆蓋既有檔案
>   · ★★ 檔名中的特殊字元造成問題
>   · ★★★ 雙副檔名：evil.php.jpg
>     → 若 Nginx 設定不當可能被當成 PHP 執行
>
> ★★ 正確做法：
>   ->preserveFilenames(false)              // ★ 預設值
>   → Filament 會產生隨機檔名
>
>   或自訂：
>   ->getUploadedFileNameForStorageUsing(fn ($f) => str()->uuid().'.'.$f->extension())
>
> ★★★ 再加上 Nginx 的防護：
>   location ^~ /storage/ {
>       location ~ \.(php|phtml|phar)$ { deny all; }
>   }
> ```

```bash
# ═══ ★★ storage 設定 ═══
$ php artisan storage:link
   INFO  The [public/storage] link has been connected to [storage/app/public].

# ★★★ 在 releases 佈局下要注意
$ ls -la /var/www/api/current/public/storage
lrwxrwxrwx 1 deploy www-data 32 Aug 28 15:30 storage -> /var/www/api/shared/storage/app/public
# ★★ 指向 shared 才對（★ 因為 current/storage 本身也是符號連結到 shared）

# ★ 驗證
$ readlink -f /var/www/api/current/public/storage
/var/www/api/shared/storage/app/public          # ★★ 正確

# ★ 上傳測試
$ curl -sI https://api.example.gov.tw/storage/attachments/2026/08/test.pdf
```

```ini
; ★★ Livewire 的上傳需要較大的暫存空間
; php-fpm pool
php_admin_value[upload_max_filesize] = 20M
php_admin_value[post_max_size] = 22M
php_admin_value[max_file_uploads] = 20
php_admin_value[upload_tmp_dir] = /var/tmp/php-uploads
```

```bash
$ sudo mkdir -p /var/tmp/php-uploads
$ sudo chown www-data:www-data /var/tmp/php-uploads
$ sudo chmod 700 /var/tmp/php-uploads

# ★★ 清理 Livewire 的暫存上傳檔（★ 排程）
# routes/console.php
# Schedule::command('livewire:configure-s3-upload-cleanup')->daily();  // S3
# ★ 本機儲存的話 Livewire 會自動清理，但可以額外保險：
$ sudo tee /etc/cron.d/livewire-tmp-cleanup >/dev/null <<'EOF'
0 4 * * * www-data find /var/www/api/shared/storage/app/livewire-tmp -type f -mmin +1440 -delete 2>/dev/null
EOF
```

---

## 效能調校 ★★

```php
<?php
// ★★ Resource 的查詢最佳化
namespace App\Filament\Resources;

class OrderResource extends Resource
{
    // ★★★ 避免 N+1 查詢
    public static function getEloquentQuery(): Builder
    {
        return parent::getEloquentQuery()
            ->with(['customer', 'items.product'])       // ★★ eager load
            ->withCount('items');                        // ★ 避免逐筆 count
    }

    public static function table(Table $table): Table
    {
        return $table
            ->columns([
                TextColumn::make('id')->sortable(),
                TextColumn::make('customer.name')
                    ->searchable()
                    ->sortable(),
                TextColumn::make('total')
                    ->money('TWD')
                    ->sortable()
                    ->summarize(Sum::make()),
                TextColumn::make('created_at')
                    ->dateTime('Y-m-d H:i')
                    ->sortable(),
            ])
            // ★★ 分頁大小（★ 不要讓使用者選 "all"）
            ->paginated([10, 25, 50])
            ->defaultPaginationPageOption(25)
            // ★★★ 大表關掉總筆數計算（★ COUNT(*) 在大表上很慢）
            ->paginationMode(PaginationMode::Simple)
            // ★ 或用 deferLoading
            ->deferLoading()                     // ★★ 先渲染框架，資料非同步載入
            ->poll(null)                         // ★★★ 關掉自動輪詢（★ 預設可能有）
            ->striped();
    }
}
```

> [!danger] `->poll()` 會造成大量請求 ★★
> ```php
> ->poll('10s')      // ★★ 每 10 秒重新載入整個表格
>
> ★★ 影響：
>   · 每個開著這頁的使用者，每 10 秒一個完整的 Livewire 請求
>   · ★ 10 個使用者 = 每秒 1 個請求（★ 而且是完整的表格查詢）
>   · ★★ 50 個使用者開著儀表板 = 明顯的伺服器負載
>
> ★★ 建議：
>   · 一般列表：★★★ 不要 poll
>   · 真的需要即時：用較長的間隔（'60s'）或改用 WebSocket
>   · ★ 儀表板的 Widget 可以個別設定
> ```

```php
<?php
// ★★ Widget 的快取
namespace App\Filament\Widgets;

use Filament\Widgets\StatsOverviewWidget as BaseWidget;
use Filament\Widgets\StatsOverviewWidget\Stat;
use Illuminate\Support\Facades\Cache;

class StatsOverview extends BaseWidget
{
    protected static ?string $pollingInterval = null;      // ★★★ 關掉輪詢
    protected static bool $isLazy = true;                  // ★★ 延遲載入（頁面先顯示）

    protected function getStats(): array
    {
        // ★★ 快取昂貴的統計查詢
        return Cache::remember('filament:stats:overview', 300, function () {
            return [
                Stat::make('總訂單', Order::count())
                    ->description('全部')
                    ->color('success'),
                Stat::make('本月營收', 'NT$' . number_format(
                    Order::whereMonth('created_at', now()->month)->sum('total')
                )),
                Stat::make('待處理', Order::where('status', 'pending')->count())
                    ->color('warning'),
            ];
        });
    }
}
```

```bash
# ★★ 找出慢的 Livewire 請求
$ sudo tail -f /var/log/php-fpm/api-slow.log

# ★ 用 Laravel Debugbar（★ 只在開發環境）
$ composer require barryvdh/laravel-debugbar --dev

# ★★ 正式環境用 slowlog + 查詢日誌
$ php artisan tinker --execute='
  DB::listen(fn ($q) => $q->time > 100 && \Log::warning("慢查詢", [
      "sql" => $q->sql, "time" => $q->time
  ]));'
```

```php
<?php
// ★★ 在 AppServiceProvider 記錄慢查詢（正式環境）
public function boot(): void
{
    if ($this->app->environment('production')) {
        DB::listen(function ($query) {
            if ($query->time > 500) {              // ★ 超過 500ms
                Log::channel('slow')->warning('慢查詢', [
                    'sql'      => $query->sql,
                    'bindings' => $query->bindings,
                    'time_ms'  => $query->time,
                    'url'      => request()->fullUrl(),
                ]);
            }
        });
    }
}
```

---

## 完整實戰範例：部署腳本的 Filament 部分

```bash
#!/usr/bin/env bash
# ★★ 部署腳本中與 Filament 相關的片段
set -euo pipefail
REL="$1"        # 新的 release 目錄
SITE="${SITE:-https://api.example.gov.tw}"

c(){ echo -e "\033[36m  $*\033[0m"; }

# ══ 【1】★★ 發布資產 ══
c "★★ 發布 Filament 資產"
cd "$REL"
php artisan filament:assets 2>&1 | sed 's/^/    /'

# ★★ 驗證資產存在
for f in public/vendor/filament public/vendor/livewire/livewire.js; do
    if [ -e "$REL/$f" ]; then
        echo "    ✓ $f"
    else
        echo "    ✗✗ 找不到 $f"
        exit 1
    fi
done

# ══ 【2】★★★ Filament 最佳化 ══
c "★★★ filament:optimize"
php artisan filament:optimize 2>&1 | sed 's/^/    /'

# ★ 驗證快取產生
if [ -f "$REL/bootstrap/cache/filament/panels/admin.php" ] || \
   ls "$REL/bootstrap/cache/filament/" >/dev/null 2>&1; then
    echo "    ✓ 元件快取已產生"
else
    echo "    ⚠ 找不到 Filament 的元件快取"
fi

# ══ 【3】★★★ 安全檢查 ══
c "★★★ 安全檢查"
FAIL=0

# ★★★ canAccessPanel 必須實作
if grep -rq 'implements FilamentUser' "$REL/app/Models/User.php" && \
   grep -rq 'function canAccessPanel' "$REL/app/Models/User.php"; then
    echo "    ✓ User 有實作 canAccessPanel"
else
    echo "    ✗✗✗ User 沒有實作 FilamentUser::canAccessPanel"
    echo "        → 【任何登入的使用者都能進管理後台】"
    FAIL=1
fi

# ★★★ 不能開放註冊
if grep -rqE '^\s*->registration\(\)' "$REL/app/Providers/Filament/"*.php 2>/dev/null; then
    echo "    ✗✗✗ Panel 開放了 registration()"
    FAIL=1
else
    echo "    ✓ 沒有開放註冊"
fi

# ★ 檢查 poll
POLLS=$(grep -rn "->poll(" "$REL/app/Filament/" 2>/dev/null | grep -v 'poll(null)' | wc -l)
[ "$POLLS" -gt 0 ] && {
    echo "    ⚠ 有 $POLLS 處使用 ->poll()（★ 會增加伺服器負載）"
    grep -rn "->poll(" "$REL/app/Filament/" 2>/dev/null | grep -v 'poll(null)' | head -3 | sed 's/^/      /'
}

[ "$FAIL" -eq 0 ] || exit 1

# ══ 【4】★★ storage 連結 ══
c "★★ storage 連結"
php artisan storage:link 2>&1 | sed 's/^/    /' || true
TARGET=$(readlink -f "$REL/public/storage" 2>/dev/null || echo "")
if [[ "$TARGET" == */shared/storage/app/public ]]; then
    echo "    ✓ 指向 shared：$TARGET"
else
    echo "    ⚠ storage 連結可能不正確：$TARGET"
fi

# ══ 【5】★★★ 部署後驗證（★ 切換之後執行）══
verify_filament() {
    c "★★★ Filament 驗證"
    local F=0
    v(){ printf '    %-42s ' "$1"; if eval "$2" >/dev/null 2>&1; then echo "✓"; else echo "✗"; F=1; fi; }

    v "登入頁 200"          "[ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/admin/login)\" = 200 ]"
    v "★★ 資產 CSS 200"      "[ \"\$(curl -so /dev/null -w '%{http_code}' \$(curl -s $SITE/admin/login | grep -oE '/vendor/filament[^\"]*\.css' | head -1))\" = 200 ]"
    v "★★ livewire.js 200"   "[ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/vendor/livewire/livewire.js)\" = 200 ]"
    v "★★★ 註冊頁 404"       "[ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/admin/register)\" != 200 ]"
    v "★ 未登入被導向登入頁" \
      "[ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/admin)\" = 302 ] || \
       [ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/admin)\" = 200 ]"

    return $F
}

echo "$SITE" > /dev/null   # 供切換後呼叫
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **後台版面全爛（沒有 CSS）** ★★★ | 沒跑 `filament:assets` | 部署腳本加上 |
| **任何登入者都能進後台** ★★★ | 沒實作 `canAccessPanel` | 實作 `FilamentUser` |
| **任何人都能註冊進後台** ★★★ | 開了 `->registration()` | 移除 |
| **按鈕點了沒反應（403）** ★★★ | ModSecurity 誤判 Livewire | 寫排除規則或後台關 WAF |
| **後台很慢（>2 秒）** ★★ | 沒跑 `filament:optimize` | 部署時執行 |
| **表格載入很慢** ★★ | N+1 查詢 | `getEloquentQuery()` 加 `with()` |
| **伺服器負載很高** ★★ | `->poll()` | 改成 `poll(null)` 或延長間隔 |
| **上傳的圖片顯示 404** ★★ | `storage:link` 沒建或指錯 | `readlink -f public/storage` |
| **上傳失敗（無錯誤訊息）** ★★ | `post_max_size` 太小 | 四層都要調 |
| **升級後版面錯亂** ★★ | 資產被瀏覽器快取 | `expires 30d`；確認有版本查詢字串 |
| CSRF token mismatch（419）★ | session 過期或多台不共享 | `SESSION_DRIVER=redis` |
| **Livewire 元件狀態遺失** ★ | session 或 cluster | 用 Redis session |
| 圖示不顯示 | 沒跑 `icons:cache` | `filament:optimize` 包含它 |

### 排查

```bash
SITE=https://api.example.gov.tw
APP=/var/www/api

# 【1】★★ 資產
$ ls -la "$APP/current/public/vendor/filament/" | head
$ curl -s "$SITE/admin/login" | grep -oE '/vendor/[^"]*\.(css|js)' | sort -u
$ for a in $(curl -s "$SITE/admin/login" | grep -oE '/vendor/[^"]*\.(css|js)' | sort -u); do
    printf '%-60s %s\n' "$a" "$(curl -so /dev/null -w '%{http_code}' "$SITE$a")"
  done

# 【2】★★★ 存取控管
$ grep -A20 'canAccessPanel' "$APP/current/app/Models/User.php"
$ grep -rn 'registration()' "$APP/current/app/Providers/Filament/"

# 【3】★★ Livewire 的請求
$ sudo tail -f /var/log/nginx/api.access.log | grep livewire
$ sudo tail -f /var/log/nginx/api.error.log

# 【4】★★★ ModSecurity 誤判
$ sudo grep livewire /var/log/modsec_audit.log | grep -oP 'id "\K\d+' | sort | uniq -c

# 【5】★★ 慢請求
$ sudo tail -50 /var/log/php-fpm/api-slow.log
$ sudo grep -c 'livewire' /var/log/php-fpm/api-slow.log

# 【6】storage
$ readlink -f "$APP/current/public/storage"
$ ls -la "$APP/shared/storage/app/public/" | head
$ curl -sI "$SITE/storage/$(ls "$APP/shared/storage/app/public" | head -1)"

# 【7】快取狀態
$ ls -la "$APP/current/bootstrap/cache/filament/" 2>/dev/null
$ php "$APP/current/artisan" about | grep -i filament

# 【8】★ 資料庫查詢
$ php "$APP/current/artisan" tinker --execute='
  DB::enableQueryLog();
  // ★ 模擬一次 Resource 查詢
  echo count(DB::getQueryLog()) . " 個查詢\n";'
```

---

## 安全性注意事項

> [!danger] Filament 的四條紅線 ★★★
> ```
> ① ★★★★ 必須實作 canAccessPanel
>      → 不實作 = 【任何登入的使用者都能進管理後台】
>      → 這是 Filament 最嚴重的預設行為
>
> ② ★★★ 絕對不要開 ->registration()
>      → 配合 ① 沒實作 = 【任何人註冊後直接進後台】
>
> ③ ★★ 檔案上傳用隨機檔名
>      → preserveFilenames(false)（★ 預設值，不要改）
>      → ★ Nginx 也要擋上傳目錄的 .php
>
> ④ ★★ 後台限制來源 IP
>      → Nginx 的 allow/deny 或應用層 middleware
>      → ★ 這是第二道防線（★ 不能取代 ①）
> ```

```bash
# ★★★ 上線前必測（★ 用一個非管理員的帳號）
$ curl -c /tmp/c.txt -s "$SITE/admin/login" > /dev/null
$ TOKEN=$(grep XSRF /tmp/c.txt | awk '{print $7}' | sed 's/%3D/=/g')
$ curl -b /tmp/c.txt -c /tmp/c.txt -s -X POST "$SITE/admin/login" \
    -H "X-XSRF-TOKEN: $TOKEN" \
    -d "email=normaluser@example.gov.tw&password=xxx" -o /dev/null -w '%{http_code}\n'
# ★ 登入後
$ curl -b /tmp/c.txt -so /dev/null -w '%{http_code}\n' "$SITE/admin"
403                                    # ★★★ 必須是 403（不是 200）
```

> [!warning] 稽核記錄 ★★
> ```php
> // ★★ 記錄後台的所有異動
> composer require spatie/laravel-activitylog
> ```
>
> ```php
> <?php
> // app/Models/Order.php
> use Spatie\Activitylog\Traits\LogsActivity;
> use Spatie\Activitylog\LogOptions;
>
> class Order extends Model
> {
>     use LogsActivity;
>
>     public function getActivitylogOptions(): LogOptions
>     {
>         return LogOptions::defaults()
>             ->logOnly(['status', 'total', 'customer_id'])
>             ->logOnlyDirty()
>             ->dontSubmitEmptyLogs()
>             ->setDescriptionForEvent(fn (string $e) => "訂單被{$e}");
>     }
> }
> ```
>
> ```
> ★★ 機關的資訊系統通常有稽核要求：
>   · 誰在什麼時候改了什麼
>   · ★ 保存期限（通常 1~3 年）
>   · ★★ 稽核記錄本身不可被後台使用者刪除
>     → 用單獨的資料庫使用者，只給 INSERT 權限
> ```

---

## 速查表

### ★★★ 部署必做的三件事

```bash
php artisan filament:assets       # ★★★ 沒做 → 後台版面全爛
php artisan filament:optimize     # ★★★ 沒做 → 每次請求慢 200~500ms
php artisan storage:link          # ★★ 上傳的檔案才看得到
```

```
★★ 加上 Laravel 的：
   composer install --no-dev --optimize-autoloader
   php artisan optimize
```

### ★★★★ 存取控管

```php
// ★★★★ app/Models/User.php —— 沒有這個 = 任何登入者都能進後台
class User extends Authenticatable implements FilamentUser
{
    public function canAccessPanel(Panel $panel): bool
    {
        return $this->hasRole('admin') && $this->is_active;
    }
}
```

```php
// ★★★ Panel 絕對不要開
->registration()          // ★★★ 任何人都能建立帳號
```

```nginx
# ★★ 第二道防線
location ^~ /admin {
    allow 10.0.0.0/8;
    deny all;
}
```

### ★★★ Livewire 與 WAF

```
★★ Livewire 的 payload 極容易被 CRS 誤判為 SQLi/XSS/PHP injection
   症狀：★ 按鈕點了沒反應（403），而且只有某些操作會發生

★★ 兩種解法：
  ① 寫排除規則（ctl:ruleRemoveByTag=attack-sqli 等）
  ② ★★ 後台與 /livewire/ 直接關掉 WAF（★ 前提是有 IP 限制 + 認證）
```

```apache
SecRule REQUEST_URI "@beginsWith /livewire/" \
  "id:20001,phase:1,pass,nolog,\
   ctl:ruleRemoveByTag=attack-sqli,\
   ctl:ruleRemoveByTag=attack-xss,\
   ctl:ruleRemoveByTag=attack-injection-php"

SecRequestBodyNoFilesLimit 2097152    # ★ 預設 128KB 太小
```

### 效能

```php
// ★★★ 避免 N+1
public static function getEloquentQuery(): Builder {
    return parent::getEloquentQuery()->with(['customer', 'items'])->withCount('items');
}

// ★★★ 關掉輪詢
->poll(null)
protected static ?string $pollingInterval = null;

// ★★ 延遲載入
->deferLoading()
protected static bool $isLazy = true;

// ★★ 大表用簡單分頁（避免 COUNT(*)）
->paginationMode(PaginationMode::Simple)

// ★★ Widget 快取
Cache::remember('filament:stats', 300, fn () => ...);
```

### 檔案上傳

```php
FileUpload::make('file')
    ->disk('public')
    ->maxSize(20480)                    // ★ KB
    ->acceptedFileTypes(['application/pdf', 'image/jpeg'])
    ->preserveFilenames(false)          // ★★★ 不要改成 true
```

```nginx
location ^~ /storage/ {
    location ~ \.(php|phtml|phar)$ { deny all; }   # ★★★
}
```

### 驗證

```bash
curl -so /dev/null -w '%{http_code}\n' https://api/admin/login       # ★ 200
curl -so /dev/null -w '%{http_code}\n' https://api/admin/register    # ★★★ 必須 404
curl -so /dev/null -w '%{http_code}\n' https://api/vendor/livewire/livewire.js  # ★ 200
readlink -f /var/www/api/current/public/storage    # ★ 應指向 shared
grep -A10 canAccessPanel app/Models/User.php       # ★★★ 必須有
```

---

## 練習題

> [!question]- 練習 1：`canAccessPanel` ★★★★
> **★ 在測試環境**
> 1. **不實作 `FilamentUser`**
> 2. 建一個「一般使用者」帳號（沒有任何角色）
> 3. 用它登入後存取 `/admin` → **進得去嗎？**
> 4. **實作 `canAccessPanel` 回傳 `$this->hasRole('admin')`**
> 5. 再測一次 → 現在呢？
> 6. **這是 Filament 最嚴重的預設行為**

> [!question]- 練習 2：資產發布 ★★★
> 1. **部署時故意不跑 `filament:assets`**
> 2. 開啟 `/admin/login` → **看起來怎樣？**
> 3. F12 看 Console 與 Network → **哪些 404？**
> 4. 執行 `php artisan filament:assets`
> 5. 重新整理 → 正常了嗎？
> 6. **把這一步加進部署腳本並驗證**

> [!question]- 練習 3：`filament:optimize` 的效益
> 1. **不執行 `filament:optimize`**
> 2. `curl -w '%{time_total}' https://api/admin` 測 10 次取平均
> 3. 執行 `php artisan filament:optimize`
> 4. 再測 10 次 → **快了多少？**
> 5. 在有 30+ 個 Resource 的專案上差異更明顯
> 6. **執行 `filament:optimize-clear` 再測一次**

> [!question]- 練習 4：Livewire 與 ModSecurity ★★★
> 1. 開啟 ModSecurity + OWASP CRS（`SecRuleEngine On`）
> 2. 在後台的富文字欄位輸入含 HTML 的內容並儲存
> 3. **成功嗎？Console 顯示什麼？**
> 4. `grep livewire /var/log/modsec_audit.log` → **哪些規則被觸發？**
> 5. 寫排除規則 → 再測
> 6. 改成後台整個關掉 WAF → 比較兩種做法

> [!question]- 練習 5：`->poll()` 的負載
> 1. 在一個表格上設 `->poll('5s')`
> 2. 開 5 個瀏覽器分頁停在那個頁面
> 3. `tail -f /var/log/nginx/api.access.log | grep livewire` → **每秒幾個請求？**
> 4. `htop` 觀察 PHP-FPM 的 CPU
> 5. 改成 `->poll(null)` → 再看
> 6. **計算 50 個使用者時的請求量**

---

## 小測驗

Q1. **Filament 與 Nova 的三個主要差別**？

Q2. **部署 Filament 必須執行哪三個 artisan 指令**？

Q3. **`canAccessPanel` 不實作會怎樣？為什麼特別危險**？

Q4. **為什麼 `public/vendor/` 不該進 git**？

Q5. **Filament 的資產為什麼不能設 `expires 1y`**？

Q6. **Livewire 為什麼容易被 ModSecurity 誤判？症狀是什麼**？

Q7. **`preserveFilenames(true)` 有什麼風險**？

Q8. **`->poll()` 對伺服器負載的影響**？

Q9. **`storage:link` 在 releases 佈局下要注意什麼**？

Q10. **Filament Resource 的 N+1 查詢該怎麼避免**？

> [!question]- 測驗答案
> **Q1.** ①**授權**：Filament 是 **MIT 免費**，Nova 是**商業授權**（$99/專案起）；
> ②**底層技術**：Filament 用 **Livewire（TALL stack）**——
> 伺服器端渲染，每次互動都送 POST 回伺服器；
> Nova 用 **Vue 3 + Inertia** —— 前端渲染。
> ③**部署複雜度**：Filament 需要 `filament:optimize` 與 `filament:assets`；
> Nova **需要 `auth.json` 的授權金鑰**才能 `composer install`
> （這是 Nova 部署最大的坑，見下一篇）。
> 附帶差別：Filament 通常**不需要前端建置**（除非自訂主題），
> 而 Livewire 的請求數量遠多於 Inertia，**對 PHP-FPM 的負載較高**。
>
> **Q2.** ①**`php artisan filament:assets`** ——
> 把 Filament 與 Livewire 的 CSS/JS 發布到 `public/vendor/`，
> **不做的話後台版面完全爛掉**（所有資產 404）；
> ②**`php artisan filament:optimize`** ——
> 快取元件（Resource/Page/Widget）與 Blade 圖示，
> **不做的話每次請求都要掃描整個專案，可能多花 200～500ms**；
> ③**`php artisan storage:link`** —— 建立 `public/storage` 符號連結，
> **上傳的檔案才看得到**。
> 加上 Laravel 的一般步驟：`composer install --no-dev --optimize-autoloader`
> 與 `php artisan optimize`。
>
> **Q3.** **不實作的話，「任何已登入的使用者」都能進入管理後台** ——
> 看到所有資料、可以新增修改刪除。
> **特別危險的原因**：
> ①**這是 Filament 的預設行為**（不像 Horizon 預設拒絕所有人）；
> ②**如果網站有一般使用者註冊功能**（前台會員），
> **那些會員登入後直接就能進後台**；
> ③**如果又開了 Filament 的 `->registration()`**，
> **任何人都能自己註冊帳號並進入管理後台** —— 這是災難級的設定錯誤。
> **正確做法**：`User` 實作 `FilamentUser` 介面並在 `canAccessPanel()`
> 中檢查角色／權限／狀態。
>
> **Q4.** 因為 **`public/vendor/` 的內容是「由 composer 套件產生的」**，
> 不是專案自己的原始碼 ——
> 每次 `composer update` 升級 Filament 或 Livewire 後，那些資產的內容就會變。
> **進 git 的問題**：
> ①**每次升級都產生大量的二進位/壓縮檔 diff**，讓 git 歷史變得臃腫；
> ②**容易產生衝突**；
> ③**版本可能與 `composer.lock` 中的套件版本不一致**
> （有人升級了套件但忘了重新發布資產）。
> **正確做法**：`.gitignore` 排除 `/public/vendor/`，
> **在部署時執行 `php artisan filament:assets` 產生**。
> **但一定要記得部署腳本要有這一步**，否則後台版面全爛。
>
> **Q5.** 因為 **Filament 的資產檔名沒有內容 hash** ——
> `/vendor/filament/filament/app.css` 這個路徑**永遠一樣**，
> 內容更新後檔名不變。
> 如果設 `expires 1y`，**瀏覽器會用舊的快取一整年** →
> 升級 Filament 後**版面錯亂**（新的 HTML 結構配舊的 CSS）。
> **三種處理**：
> ①**`expires 30d`**（不要用 1y）；
> ②**Filament 會自動加版本查詢字串**（`app.css?v=3.3.14`）——
> 升級後 URL 就變了，快取自動失效
> （所以實務上風險比想像中小，但仍不建議 1y）；
> ③部署後清 CDN 快取。
> **對照**：Vite 建置的產物**檔名帶 hash**（`index-D4f8a2b1.js`），
> 可以放心設 `immutable` 一年。
>
> **Q6.** 因為 **Livewire 每次互動都送一個 POST 到 `/livewire/update`，
> payload 是 JSON，裡面包含「序列化的元件狀態」** ——
> 可能含 HTML 片段（富文字欄位）、SQL 查詢條件、base64 資料、類別名稱。
> **OWASP CRS 會把這些判定為**：
> **SQL injection（942xxx）**、**XSS（941xxx）**、**PHP injection（933xxx）**。
> **症狀**：
> **後台的按鈕點了沒反應**，Console 顯示 **403**，
> **而且只有某些操作會發生**（取決於 payload 的內容）——
> **極難重現與追查**。
> **解法**：寫排除規則（`ctl:ruleRemoveByTag=attack-sqli` 等），
> 或**後台與 `/livewire/` 直接關掉 WAF**
> （前提是後台確實有 IP 限制 + 嚴格認證）。
> 另外 `SecRequestBodyNoFilesLimit` 的預設 128KB 對 Livewire 太小。
>
> **Q7.** **保留使用者上傳的原始檔名**會帶來：
> ①**路徑遍歷**（`../../etc/passwd`）—— Laravel 有處理，但不值得冒險；
> ②**覆蓋既有檔案**（兩個使用者上傳同名檔案）；
> ③**檔名中的特殊字元**造成 URL 編碼、檔案系統、下載時的問題；
> ④**★★★ 雙副檔名**（`evil.php.jpg`）——
> **若 Nginx 設定不當（缺 `try_files $uri =404`）可能被當成 PHP 執行**。
> **正確做法**：`->preserveFilenames(false)`（**這是預設值，不要改**），
> 或自訂 `->getUploadedFileNameForStorageUsing(fn ($f) => str()->uuid().'.'.$f->extension())`。
> **再加上 Nginx 的防護**：上傳目錄的 `.php` 一律 `deny all`。
>
> **Q8.** **`->poll('10s')` 表示「每 10 秒重新載入整個表格」** ——
> 對每個開著那個頁面的使用者都會發生。
> **負載計算**：
> 10 個使用者 × 每 10 秒 1 次 = **每秒 1 個完整的 Livewire 請求**
> （而且每個請求都包含完整的資料庫查詢與 HTML 渲染）；
> **50 個使用者開著儀表板 = 每秒 5 個請求**，
> 這對 PHP-FPM 是明顯的負載，而且**在沒有人操作的時候也持續發生**。
> **建議**：
> **一般列表不要 poll**（`->poll(null)`）；
> 真的需要即時更新就用**較長的間隔**（`'60s'`）或改用 WebSocket（Laravel Reverb）；
> Widget 用 `protected static ?string $pollingInterval = null;` 關掉。
>
> **Q9.** **要確認符號連結最終指向 `shared/storage/app/public`**。
> 在 releases 佈局下：
> `current/storage` 本身已經是符號連結指向 `shared/storage`，
> 所以 `php artisan storage:link` 建立的 `current/public/storage`
> 應該解析為 `shared/storage/app/public`。
> **驗證**：
> ```bash
> readlink -f /var/www/api/current/public/storage
> # ★ 應該輸出 /var/www/api/shared/storage/app/public
> ```
> **如果指向 release 目錄內的路徑**，
> **部署後上傳的檔案就會消失**（舊的 release 被清掉）。
> 另外每次部署都要重新執行 `storage:link`（新的 release 目錄裡沒有那個連結）。
>
> **Q10.** **覆寫 `getEloquentQuery()` 加上 eager loading**：
> ```php
> public static function getEloquentQuery(): Builder
> {
>     return parent::getEloquentQuery()
>         ->with(['customer', 'items.product'])   // ★★ eager load
>         ->withCount('items');                    // ★ 避免逐筆 count
> }
> ```
> **為什麼會有 N+1**：
> 表格顯示 25 筆訂單，每一筆都有 `TextColumn::make('customer.name')` →
> **每一筆都會單獨查一次 customers 表** → 1 + 25 = 26 個查詢。
> **其他優化**：
> `->paginated([10, 25, 50])`（**不要讓使用者選 "all"**）、
> **大表用 `->paginationMode(PaginationMode::Simple)`**（避免 `COUNT(*)`）、
> `->deferLoading()`（先渲染框架，資料非同步載入）、
> Widget 用 `Cache::remember()` 快取統計查詢。
> **偵測方式**：在 `AppServiceProvider` 用 `DB::listen()` 記錄慢查詢，
> 或開發時用 Laravel Debugbar。

---

## 延伸閱讀

- [[130-01-04-06-guide-Laravel-Nova部署]] — Nova 的授權與部署（差異很大）
- [[130-01-04-07-guide-Laravel-正式環境安全檢查表]] — 上線前的完整檢查
- [[130-01-04-04-guide-Laravel-快取最佳化與部署流程]] — 部署流程整合
- [[130-01-04-02-guide-Laravel-Nginx與PHP-FPM設定]] — Nginx 與 WAF
- [[090-04-03-svc-ModSecurity-規則調校與誤判處理]] — WAF 誤判的處理
- [[090-03-02-guide-應用安全-應用層安全]] — 後台安全的通用原則
