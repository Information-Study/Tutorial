---
title: "PHP OPcache 與效能"
desc: "OPcache 設定與監控、JIT、realpath 快取，以及部署時的快取失效處理"
aliases: [opcache, JIT, realpath_cache, preload, opcache_reset]
tags: [群組/軟體與開發工具, 服務/php, 主題/效能]
category: PHP
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[060-03-01-03-guide-PHP-ini重要參數]]"]
updated: 2026-08-28
---

# PHP OPcache 與效能

> [!abstract] 這篇你會學到
> - 理解 **OPcache 的運作原理**與它為什麼是最重要的效能設定
> - 正確設定 **`validate_timestamps`** 並處理**部署時的快取失效**
> - 依實際用量調整 **`memory_consumption` 與 `max_accelerated_files`**
> - 用 **`opcache_get_status()`** 監控命中率與記憶體
> - 設定 **`realpath_cache`**（符號連結部署時特別重要）
> - 評估 **JIT** 與 **preload** 是否值得啟用

## 前置知識

- [[060-03-01-03-guide-PHP-ini重要參數]] — php.ini 設定與生效方式
- [[060-03-01-02-guide-PHP-FPM設定與Pool調校]] — FPM reload

---

## OPcache 的運作原理

```mermaid
graph LR
    A["PHP 原始碼<br/>index.php"] --> B["詞法分析<br/>語法分析"]
    B --> C["編譯成 opcode"]
    C --> D["Zend VM 執行"]

    C -.->|"★ 存入共享記憶體"| E[("OPcache<br/>shared memory")]
    E -.->|"★ 下次直接取用<br/>跳過 ①②③"| D

    style E fill:#d4f4d4
```

```
沒有 OPcache：
  每個請求 → 讀檔 → 詞法分析 → 語法分析 → 編譯 → 執行
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ ★ 每次都重做

有 OPcache：
  第一個請求 → 編譯 → 【存進共享記憶體】 → 執行
  後續請求   → 【直接從共享記憶體取 opcode】 → 執行
```

> [!danger] 沒開 OPcache 的效能差距
> ```
> 實測：Laravel 應用的首頁（載入約 400 個 PHP 檔案）
>
>   OPcache 關閉：  85 req/s   平均 235ms
>   OPcache 開啟： 620 req/s   平均  32ms      ★ 提升 7 倍
> ```
>
> ```bash
> # ★ 檢查是否已啟用
> $ php -i | grep -E 'opcache.enable|Opcode Caching'
> $ echo '<?php var_dump(opcache_get_status() !== false);' > public/_o.php
> $ curl -s https://網站/_o.php
> bool(true)
> ```
>
> **這是 PHP 最重要的一個設定。**

---

## 完整設定

```ini
; ═══════════ /etc/php/8.3/fpm/conf.d/10-opcache.ini ═══════════

; ══ 基本 ══
opcache.enable = 1
opcache.enable_cli = 0                    ; ★ CLI 通常不需要（每次都是新程序）

; ══ ★★ 記憶體 ══
opcache.memory_consumption = 256          ; MB —— 存 opcode 的共享記憶體
opcache.interned_strings_buffer = 32      ; MB —— ★ 字串去重（框架很吃這個）
opcache.max_accelerated_files = 20000     ; ★ 最多快取幾個檔案

; ══ ★★ 時間戳檢查 ══
opcache.validate_timestamps = 0           ; ★★ 正式環境設 0（不檢查檔案是否變更）
opcache.revalidate_freq = 0               ; validate_timestamps=1 時才有意義
; 開發環境：validate_timestamps = 1, revalidate_freq = 0

; ══ 註解 ══
opcache.save_comments = 1                 ; ★ 保留 docblock（annotation 需要）
; opcache.load_comments 已在 PHP 8 移除

; ══ 最佳化 ══
opcache.optimization_level = 0x7FFEBFFF   ; 預設，全部最佳化
opcache.opt_debug_level = 0

; ══ 檔案快取（★ 重啟後不用重新編譯）══
opcache.file_cache = /var/cache/php/opcache
opcache.file_cache_only = 0
opcache.file_cache_consistency_checks = 1

; ══ 錯誤處理 ══
opcache.log_verbosity_level = 1           ; 0=只有致命 1=錯誤 2=警告 3=資訊 4=除錯
opcache.error_log = /var/log/php/opcache-error.log

; ══ 其他 ══
opcache.max_wasted_percentage = 5         ; 浪費超過 5% 就重啟
opcache.consistency_checks = 0            ; ★ 正式環境設 0（檢查有成本）
opcache.huge_code_pages = 1               ; ★ 使用 huge pages（需核心支援）
opcache.validate_permission = 0
opcache.validate_root = 0

; ══ JIT（見下方）══
opcache.jit = tracing
opcache.jit_buffer_size = 128M

; ══ Preload（見下方，★ 要小心）══
; opcache.preload = /var/www/app/current/preload.php
; opcache.preload_user = app-user
```

```bash
$ sudo mkdir -p /var/cache/php/opcache /var/log/php
$ sudo chown www-data:www-data /var/cache/php/opcache /var/log/php
$ sudo systemctl restart php8.3-fpm
```

---

## `validate_timestamps`：最關鍵的取捨 ★★★

```ini
; ═══ 開發環境 ═══
opcache.validate_timestamps = 1
opcache.revalidate_freq = 0         ; ★ 每次請求都檢查（改了立刻生效）

; ═══ 正式環境 ═══
opcache.validate_timestamps = 0     ; ★★ 完全不檢查（最快）
```

```
validate_timestamps = 1：
  每個請求（或每 revalidate_freq 秒）
    → 對【每一個】已快取的檔案做 stat() 檢查 mtime
      → 檔案變了就重新編譯
        → ★ 一個請求載入 400 個檔案 = 400 次 stat()

validate_timestamps = 0：
  ★ 完全不檢查 → 最快
  ★★ 但【改了程式碼也不會生效】，直到 OPcache 被重置
```

> [!danger] `validate_timestamps = 0` 的部署陷阱 ★★★
> ```
> 部署了新版程式碼
>   → OPcache 還記著【舊的 opcode】
>     → 【網站還是跑舊版】
>       → 而且你 git log 看到新的 commit，檔案內容也是新的
>         → 【極度困惑】
> ```
>
> **必須在部署後重置 OPcache**：
> ```bash
> # ★ 方法一：reload FPM（最簡單可靠）
> $ sudo systemctl reload php8.3-fpm
>
> # ★ 方法二：opcache_reset()（需要一個端點）
> $ curl -X POST -H "X-Deploy-Token: $TOKEN" https://網站/opcache-reset
>
> # 方法三：cachetool（CLI 直接操作 FPM）
> $ cachetool opcache:reset --fcgi=/run/php/php8.3-fpm.sock
> ```

> [!warning] `opcache_reset()` 在 CLI 中無效
> ```bash
> # ❌ 這【不會】重置 FPM 的 OPcache
> $ php -r 'opcache_reset();'
>
> # ★ 原因：CLI 與 FPM 是【不同的程序，不同的共享記憶體】
> ```
>
> **正確的三種方式**：
> ```bash
> # ① reload FPM（★ 推薦：簡單、可靠、不中斷服務）
> $ sudo systemctl reload php8.3-fpm
>
> # ② 透過 HTTP 端點（需要 Web 伺服器已在跑）
> # ③ cachetool（透過 FastCGI 協定直接呼叫）
> $ sudo apt install -y php-cli
> $ curl -sLO https://github.com/gordalina/cachetool/releases/latest/download/cachetool.phar
> $ chmod +x cachetool.phar && sudo mv cachetool.phar /usr/local/bin/cachetool
> $ cachetool opcache:reset --fcgi=/run/php/php8.3-fpm.sock
> $ cachetool opcache:status --fcgi=/run/php/php8.3-fpm.sock
> ```

```php
<?php
// ═══ public/opcache-reset.php ═══
// ★ 安全的 OPcache 重置端點
declare(strict_types=1);

// ① 只允許本機
$allowed = ['127.0.0.1', '::1'];
if (!in_array($_SERVER['REMOTE_ADDR'] ?? '', $allowed, true)) {
    http_response_code(404);
    exit;
}

// ② 需要 token（★ 從 web root 之外的檔案讀取）
$expected = trim(@file_get_contents('/var/www/app/shared/deploy.token') ?: '');
$given = $_SERVER['HTTP_X_DEPLOY_TOKEN'] ?? '';
if ($expected === '' || !hash_equals($expected, $given)) {
    http_response_code(404);
    exit;
}

// ③ 只接受 POST
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    http_response_code(405);
    exit;
}

$before = opcache_get_status(false);
$ok = opcache_reset();
$after = opcache_get_status(false);

header('Content-Type: application/json');
echo json_encode([
    'reset'         => $ok,
    'before_files'  => $before['opcache_statistics']['num_cached_scripts'] ?? null,
    'after_files'   => $after['opcache_statistics']['num_cached_scripts'] ?? null,
    'memory_free'   => round(($after['memory_usage']['free_memory'] ?? 0) / 1048576, 1) . ' MB',
], JSON_PRETTY_PRINT);
```

```bash
# ★ 產生 token
$ openssl rand -hex 32 | sudo tee /var/www/app/shared/deploy.token
$ sudo chmod 600 /var/www/app/shared/deploy.token
$ sudo chown app-user:app-user /var/www/app/shared/deploy.token

# 部署腳本中使用
$ TOKEN=$(sudo cat /var/www/app/shared/deploy.token)
$ curl -sX POST -H "X-Deploy-Token: $TOKEN" http://127.0.0.1/opcache-reset.php
```

> [!tip] 為什麼 `reload` 比 `restart` 好
> ```
> systemctl restart php8.3-fpm
>   → 【殺掉所有 worker】→ 正在處理的請求【全部中斷】→ 使用者看到 502
>
> systemctl reload php8.3-fpm
>   → 送出 SIGUSR2 → master 啟動【新的 worker】
>     → 舊 worker【處理完當前請求後才結束】
>       → ★ 零中斷
> ```
> **部署時一律用 `reload`。**

---

## `realpath_cache`：符號連結部署的關鍵 ★

```ini
realpath_cache_size = 4096K       ; ★ 預設只有 256K，太小
realpath_cache_ttl = 600          ; 秒
```

```
PHP 每次 include/require 都要把路徑解析成實體路徑（realpath）
  → 涉及多次 stat() 系統呼叫
    → realpath_cache 把結果快取起來

★ 符號連結部署（current -> releases/xxx）時特別重要
  → 每一層符號連結都要解析
```

```php
<?php
// ★ 檢查 realpath cache 用量
$size = realpath_cache_size();
$limit = ini_get('realpath_cache_size');
printf("realpath_cache: %.1f KB / %s (%.0f%%)\n",
    $size / 1024, $limit,
    $size / (int)$limit * 100 * ((substr($limit, -1) === 'K') ? 1024 : 1) / 1024);
print_r(array_slice(realpath_cache_get(), 0, 5));
```

> [!danger] `realpath_cache` 與部署的衝突
> ```
> 部署時切換符號連結：current -> releases/20260828-100000
>   → realpath_cache 還記著【舊的實體路徑】
>     → 在 realpath_cache_ttl（預設 120 秒）內
>       → 【PHP 還是讀舊版的檔案】
> ```
>
> **這與 OPcache 是兩個獨立的快取，都要處理！**
>
> **解法**：
> ```bash
> # ★ reload FPM 會同時清掉 OPcache 與 realpath_cache
> $ sudo systemctl reload php8.3-fpm
> ```
>
> **Web 伺服器端也要處理**：
> ```nginx
> # ★ 讓 PHP 拿到解析後的實體路徑
> fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
> fastcgi_param DOCUMENT_ROOT   $realpath_root;
> ```
> 見 [[060-02-02-03-guide-Nginx-location與rewrite]]。

---

## 監控 OPcache

```php
<?php
// ═══ public/opcache-status.php ═══
// ★ 只允許內網存取
$allowed = ['127.0.0.1', '::1'];
$ip = $_SERVER['REMOTE_ADDR'] ?? '';
if (!in_array($ip, $allowed, true) && !str_starts_with($ip, '10.0.9.')) {
    http_response_code(404); exit;
}

$s = opcache_get_status(false);
$c = opcache_get_configuration();
if ($s === false) { die("OPcache 未啟用\n"); }

$m = $s['memory_usage'];
$i = $s['interned_strings_usage'];
$st = $s['opcache_statistics'];

header('Content-Type: text/plain; charset=utf-8');
printf("═══ OPcache 狀態 ═══\n\n");
printf("啟用          : %s\n", $s['opcache_enabled'] ? '是' : '否');
printf("完全載入      : %s\n", $s['cache_full'] ? '★ 是（記憶體滿了！）' : '否');
printf("重啟中        : %s\n", $s['restart_pending'] ? '是' : '否');
printf("\n【記憶體】\n");
printf("  已用        : %7.1f MB\n", $m['used_memory'] / 1048576);
printf("  可用        : %7.1f MB\n", $m['free_memory'] / 1048576);
printf("  浪費        : %7.1f MB (%.1f%%) %s\n",
    $m['wasted_memory'] / 1048576, $m['current_wasted_percentage'],
    $m['current_wasted_percentage'] > 10 ? '★ 偏高' : '');
printf("  總計        : %7.1f MB\n",
    ($m['used_memory'] + $m['free_memory'] + $m['wasted_memory']) / 1048576);
printf("  使用率      : %7.1f%%\n",
    $m['used_memory'] / ($m['used_memory'] + $m['free_memory'] + $m['wasted_memory']) * 100);

printf("\n【Interned Strings】\n");
printf("  已用        : %7.1f MB / %.1f MB (%.0f%%) %s\n",
    $i['used_memory'] / 1048576, ($i['used_memory'] + $i['free_memory']) / 1048576,
    $i['used_memory'] / ($i['used_memory'] + $i['free_memory']) * 100,
    $i['free_memory'] < 1048576 ? '★ 快滿了' : '');
printf("  字串數      : %d\n", $i['number_of_strings']);

printf("\n【快取的檔案】\n");
printf("  已快取      : %d / %d (%.0f%%) %s\n",
    $st['num_cached_scripts'], $c['directives']['opcache.max_accelerated_files'],
    $st['num_cached_scripts'] / $c['directives']['opcache.max_accelerated_files'] * 100,
    $st['num_cached_scripts'] >= $c['directives']['opcache.max_accelerated_files'] * 0.9
        ? '★ 接近上限' : '');
printf("  快取的 key  : %d / %d\n", $st['num_cached_keys'], $st['max_cached_keys']);

printf("\n【命中率】★★\n");
$total = $st['hits'] + $st['misses'];
printf("  命中        : %d\n", $st['hits']);
printf("  未命中      : %d\n", $st['misses']);
printf("  命中率      : %7.2f%% %s\n", $st['opcache_hit_rate'],
    $st['opcache_hit_rate'] < 95 ? '★★ 偏低！' : ($st['opcache_hit_rate'] < 99 ? '★ 可再優化' : '✓'));
printf("  快取滿重啟  : %d %s\n", $st['oom_restarts'],
    $st['oom_restarts'] > 0 ? '★★ 記憶體不足，調大 memory_consumption' : '');
printf("  雜湊滿重啟  : %d %s\n", $st['hash_restarts'],
    $st['hash_restarts'] > 0 ? '★★ 調大 max_accelerated_files' : '');
printf("  手動重啟    : %d\n", $st['manual_restarts']);
printf("  最後重啟    : %s\n",
    $st['last_restart_time'] ? date('Y-m-d H:i:s', $st['last_restart_time']) : '從未');
printf("  啟動時間    : %s\n", date('Y-m-d H:i:s', $st['start_time']));

printf("\n【JIT】\n");
if (isset($s['jit'])) {
    $j = $s['jit'];
    printf("  啟用        : %s\n", $j['enabled'] ? '是' : '否');
    printf("  緩衝已用    : %7.1f MB / %.1f MB\n",
        ($j['buffer_size'] - $j['buffer_free']) / 1048576, $j['buffer_size'] / 1048576);
} else { printf("  未啟用\n"); }

printf("\n【關鍵設定】\n");
foreach (['opcache.memory_consumption','opcache.interned_strings_buffer',
          'opcache.max_accelerated_files','opcache.validate_timestamps',
          'opcache.revalidate_freq','opcache.save_comments','opcache.jit',
          'opcache.jit_buffer_size','opcache.file_cache','opcache.preload'] as $k) {
    $v = $c['directives'][$k] ?? '(未設定)';
    printf("  %-34s %s\n", $k, var_export($v, true));
}

printf("\n【realpath cache】\n");
printf("  已用        : %7.1f KB / %s\n",
    realpath_cache_size() / 1024, ini_get('realpath_cache_size'));
printf("  TTL         : %s 秒\n", ini_get('realpath_cache_ttl'));

printf("\n【建議】\n");
if ($s['cache_full']) echo "  ★★ 記憶體已滿 → 調大 opcache.memory_consumption\n";
if ($st['oom_restarts'] > 0) echo "  ★★ 曾因記憶體不足重啟 → 調大 memory_consumption\n";
if ($st['hash_restarts'] > 0) echo "  ★★ 曾因雜湊表滿重啟 → 調大 max_accelerated_files\n";
if ($m['current_wasted_percentage'] > 10) echo "  ★ 浪費比例偏高 → 考慮定期 reload\n";
if ($st['opcache_hit_rate'] < 95) echo "  ★★ 命中率偏低 → 檢查 validate_timestamps 與記憶體\n";
if ($i['free_memory'] < 1048576) echo "  ★ interned_strings 快滿 → 調大 interned_strings_buffer\n";
if ($st['num_cached_scripts'] >= $c['directives']['opcache.max_accelerated_files'] * 0.9)
    echo "  ★ 檔案數接近上限 → 調大 max_accelerated_files\n";
if ($c['directives']['opcache.validate_timestamps'] && getenv('APP_ENV') === 'production')
    echo "  ★ 正式環境建議 validate_timestamps = 0（部署後 reload FPM）\n";
```

```bash
$ curl -s http://127.0.0.1/opcache-status.php
```

### 用 cachetool 從 CLI 監控

```bash
$ cachetool opcache:status --fcgi=/run/php/php8.3-fpm.sock
+----------------------+---------------------------+
| Name                 | Value                     |
+----------------------+---------------------------+
| Enabled              | Yes                       |
| Cache full           | No                        |
| Memory used          | 148.32 MB                 |
| Memory free          | 103.21 MB                 |
| Memory wasted        | 4.47 MB (1.75%)           |
| Cached scripts       | 3842                      |
| Hits                 | 18420331                  |
| Misses               | 3847                      |
| Hit rate             | 99.98%                    |
+----------------------+---------------------------+

$ cachetool opcache:status:scripts --fcgi=/run/php/php8.3-fpm.sock | head -20
$ cachetool opcache:reset --fcgi=/run/php/php8.3-fpm.sock
$ cachetool opcache:invalidate:scripts /var/www/app/current/app/Models/User.php \
    --fcgi=/run/php/php8.3-fpm.sock
```

### 調整依據

| 症狀 | 調整 |
| --- | --- |
| **`cache_full` = true** | **調大 `memory_consumption`** |
| **`oom_restarts` > 0** | **調大 `memory_consumption`** |
| **`hash_restarts` > 0** | **調大 `max_accelerated_files`** |
| **命中率 < 95%** | 檢查 `validate_timestamps` 與記憶體 |
| `num_cached_scripts` 接近上限 | 調大 `max_accelerated_files` |
| interned strings 快滿 | 調大 `interned_strings_buffer` |
| **浪費比例 > 10%** | 定期 `reload`；或檢查是否頻繁部署 |

```bash
# ★ max_accelerated_files 的估算
$ find /var/www/app/current -name '*.php' -not -path '*/tests/*' | wc -l
14832
# → 設成 20000（要留餘裕，且 OPcache 會取「大於等於它的質數」）

# ★ memory_consumption 的估算
# 觀察實際用量後再調
$ curl -s http://127.0.0.1/opcache-status.php | grep -A3 '【記憶體】'
```

---

## JIT（Just-In-Time 編譯）

```ini
opcache.jit = tracing              ; 或 function / disable
opcache.jit_buffer_size = 128M     ; ★ 0 = 停用 JIT
```

| 模式 | 說明 |
| --- | --- |
| **`tracing`（1254）** | **追蹤熱路徑後編譯**（★ 建議） |
| `function`（1205） | 以函式為單位編譯 |
| `disable` / `off` | 停用 |
| `0` | 停用 |

> [!warning] JIT 對「典型的 Web 應用」幫助有限
> ```
> JIT 大幅加速的是：
>   ✓ 【CPU 密集的純運算】（數學、影像處理、加密、壓縮）
>   ✓ 長時間執行的迴圈
>
> JIT 對這些幫助很小（甚至可能變慢）：
>   ✗ 【典型的 Web 請求】（大部分時間在等 I/O：資料庫、檔案、網路）
>   ✗ 短生命週期的請求
>
> 實測（Laravel 應用）：
>   JIT off ：620 req/s
>   JIT on  ：635 req/s      ★ 只有 2%，還多用 128MB 記憶體
> ```
>
> **建議**：
> ```
> ① 一般的 CRUD 網站 → 【不需要】JIT，把記憶體留給 OPcache
> ② 有大量運算的功能（報表、影像處理）→ 值得測試
> ③ 【一定要實測】，不要因為「聽說很快」就開
> ```
>
> **JIT 的已知問題**：某些 PHP 版本的 JIT 有 bug 導致段錯誤（segfault），
> 若看到 `php-fpm[xxx]: segfault` 先試著關掉 JIT。

```bash
# ★ 實測 JIT 的效果
$ cat > /tmp/bench.php <<'EOF'
<?php
$start = microtime(true);
// CPU 密集：計算費氏數列
function fib(int $n): int { return $n < 2 ? $n : fib($n-1) + fib($n-2); }
fib(30);
printf("CPU 密集：%.3f 秒\n", microtime(true) - $start);
EOF

$ php -d opcache.enable_cli=1 -d opcache.jit_buffer_size=0   /tmp/bench.php
CPU 密集：1.842 秒
$ php -d opcache.enable_cli=1 -d opcache.jit_buffer_size=64M -d opcache.jit=tracing /tmp/bench.php
CPU 密集：0.213 秒          # ★ 快 8 倍（但這是純運算）

# ★ 對真實的 Web 應用測試
$ ab -n 3000 -c 20 https://網站/    # JIT 開與關各測一次
```

---

## Preload（謹慎使用）

```php
<?php
// ═══ /var/www/app/current/preload.php ═══
// ★ 在 FPM 啟動時把常用的類別載入記憶體，永久常駐
$dirs = [
    __DIR__ . '/vendor/laravel/framework/src/Illuminate',
    __DIR__ . '/app',
];
foreach ($dirs as $dir) {
    $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dir));
    foreach ($it as $file) {
        if ($file->getExtension() !== 'php') continue;
        // ★ 跳過會產生副作用的檔案
        if (str_contains($file->getPathname(), '/tests/')) continue;
        if (str_contains($file->getPathname(), '/Illuminate/Foundation/helpers.php')) continue;
        try { opcache_compile_file($file->getPathname()); } catch (Throwable $e) { /* 忽略 */ }
    }
}
```

```ini
opcache.preload = /var/www/app/current/preload.php
opcache.preload_user = app-user           ; ★ 不能是 root
```

> [!danger] Preload 的三個嚴重問題
> **① 改了程式碼必須 `restart`（不是 `reload`）**
> ```
> preload 的類別是【永久常駐】的
>   → reload 【不會】重新載入
>     → 必須 systemctl restart php8.3-fpm
>       → ★ 會中斷正在處理的請求
> ```
>
> **② 與符號連結部署衝突**
> ```
> opcache.preload = /var/www/app/current/preload.php
>   → 啟動時解析成 releases/20260828-100000/preload.php
>     → 部署後 current 指向新版，但 preload 還是舊版的類別
>       → ★★ 【新舊程式碼混用，行為極難預測】
> ```
>
> **③ 效益不如預期**
> ```
> 實測（Laravel）：
>   OPcache only        ：620 req/s
>   OPcache + preload   ：665 req/s      ★ 只有 7%
>
> 而且多用了約 100 MB 記憶體，還帶來上述兩個維運問題。
> ```
>
> **結論**：**除非你有實測證明的明確效益，否則不要用 preload。**
> 對機關的一般應用，**OPcache 就夠了**。

---

## 完整實戰範例

### 部署腳本中的快取處理

```bash
#!/usr/bin/env bash
# 部署後的快取處理（★ 三種快取都要清）
set -euo pipefail
APP=/var/www/app
PHPV=8.3

echo "═══ 部署後的快取處理 ═══"

echo -e "\n【1】切換符號連結"
NEW="$1"
ln -sfn "$NEW" "$APP/current.tmp"
mv -Tf "$APP/current.tmp" "$APP/current"
echo "  current -> $(readlink -f "$APP/current")"

echo -e "\n【2】★ Laravel 的應用層快取"
cd "$APP/current"
php artisan config:cache
php artisan route:cache
php artisan view:cache
php artisan event:cache

echo -e "\n【3】★★ reload FPM（同時清 OPcache 與 realpath_cache）"
sudo systemctl reload "php${PHPV}-fpm"

echo -e "\n【4】★ Nginx reload（清 open_file_cache）"
sudo nginx -t && sudo systemctl reload nginx

echo -e "\n【5】★ 驗證新版本真的生效了"
sleep 2
# ★ 用一個回傳 commit hash 的端點驗證
EXPECTED=$(git -C "$NEW" rev-parse --short HEAD)
ACTUAL=$(curl -s http://127.0.0.1/version 2>/dev/null | grep -oP '"commit"\s*:\s*"\K[^"]+' || echo "?")
if [ "$EXPECTED" = "$ACTUAL" ]; then
    echo "  ✓ 版本一致：$ACTUAL"
else
    echo "  ✗✗ 版本不符！預期 $EXPECTED，實際 $ACTUAL"
    echo "     → OPcache 可能沒清乾淨，嘗試 restart"
    sudo systemctl restart "php${PHPV}-fpm"
    sleep 3
    ACTUAL=$(curl -s http://127.0.0.1/version | grep -oP '"commit"\s*:\s*"\K[^"]+' || echo "?")
    [ "$EXPECTED" = "$ACTUAL" ] && echo "  ✓ restart 後正常" || \
      { echo "  ✗✗ 仍然不符，請人工檢查"; exit 1; }
fi

echo -e "\n【6】OPcache 狀態"
curl -s http://127.0.0.1/opcache-status.php 2>/dev/null | \
  grep -E '命中率|已快取|已用' | sed 's/^/  /'

echo -e "\n✓ 完成"
```

```php
<?php
// ═══ public/version.php ═══ 或 Laravel 的路由
// ★ 讓部署腳本能驗證新版本真的生效了
header('Content-Type: application/json');
echo json_encode([
    'commit'  => trim(@file_get_contents(__DIR__ . '/../VERSION') ?: 'unknown'),
    'time'    => date('c'),
    'php'     => PHP_VERSION,
    'opcache' => opcache_get_status(false)['opcache_statistics']['num_cached_scripts'] ?? null,
]);
```

```bash
# 部署時產生 VERSION 檔
$ git rev-parse --short HEAD > "$REL/VERSION"
```

### OPcache 健康檢查（可排程）

```bash
#!/usr/bin/env bash
# /usr/local/bin/opcache-health —— OPcache 健康檢查
SOCK="${1:-/run/php/php8.3-fpm.sock}"
FAIL=0

echo "═══ OPcache 健康檢查 $(date '+%F %T') ═══"

if ! command -v cachetool >/dev/null; then
    echo "  ⚠ 未安裝 cachetool，改用 HTTP 端點"
    OUT=$(curl -s http://127.0.0.1/opcache-status.php 2>/dev/null)
    [ -z "$OUT" ] && { echo "  ✗ 無法取得狀態"; exit 1; }
    echo "$OUT" | sed 's/^/  /'
    exit 0
fi

STATUS=$(cachetool opcache:status --fcgi="$SOCK" 2>/dev/null)
[ -z "$STATUS" ] && { echo "  ✗✗ 無法連接 FPM socket"; exit 1; }

echo "$STATUS" | sed 's/^/  /'

get() { echo "$STATUS" | grep -oP "\| $1\s*\| \K[^|]+" | tr -d ' '; }

echo -e "\n【判讀】"
FULL=$(get "Cache full")
[ "$FULL" = "Yes" ] && { echo "  ✗✗ 記憶體已滿 → 調大 opcache.memory_consumption"; FAIL=1; } \
                    || echo "  ✓ 記憶體未滿"

RATE=$(get "Hit rate" | tr -d '%')
awk -v r="${RATE:-0}" 'BEGIN {
  if (r < 95)      { printf "  ✗✗ 命中率 %.2f%% 偏低\n", r; exit 1 }
  else if (r < 99) { printf "  ⚠ 命中率 %.2f%% 可再優化\n", r }
  else             { printf "  ✓ 命中率 %.2f%%\n", r }
}' || FAIL=1

WASTED=$(get "Memory wasted" | grep -oP '\(\K[0-9.]+')
awk -v w="${WASTED:-0}" 'BEGIN {
  if (w > 10) printf "  ⚠ 浪費 %.1f%% 偏高（頻繁部署？考慮定期 reload）\n", w
  else        printf "  ✓ 浪費 %.1f%%\n", w
}'

echo -e "\n【設定檢查】"
for k in opcache.enable opcache.validate_timestamps opcache.memory_consumption \
         opcache.max_accelerated_files opcache.interned_strings_buffer \
         opcache.save_comments opcache.jit opcache.preload; do
    v=$(cachetool opcache:configuration --fcgi="$SOCK" 2>/dev/null | \
        grep -oP "\| $k\s*\| \K[^|]+" | tr -d ' ')
    printf '  %-38s %s\n' "$k" "${v:-（未設定）}"
done

echo -e "\n【重要檢查】"
VT=$(cachetool opcache:configuration --fcgi="$SOCK" 2>/dev/null | \
     grep -oP '\| opcache.validate_timestamps\s*\| \K[^|]+' | tr -d ' ')
[ "$VT" = "0" ] || [ "$VT" = "" ] \
  && echo "  ✓ validate_timestamps = 0（正式環境，★ 部署後要 reload FPM）" \
  || echo "  ⚠ validate_timestamps 已開啟（開發環境設定，正式環境會較慢）"

PL=$(cachetool opcache:configuration --fcgi="$SOCK" 2>/dev/null | \
     grep -oP '\| opcache.preload\s*\| \K[^|]+' | tr -d ' ')
[ -n "$PL" ] && [ "$PL" != "" ] && \
  echo "  ⚠ 有啟用 preload【改程式碼要 restart 而非 reload；與符號連結部署衝突】"

exit $FAIL
```

---

## 常見錯誤與排錯

| 現象／錯誤 | 原因 | 解法 |
| --- | --- | --- |
| **部署後還是跑舊版** ★★★ | **`validate_timestamps = 0` + 沒清 OPcache** | **部署後 `systemctl reload php8.3-fpm`** |
| **改了程式碼沒生效（開發環境）** | `validate_timestamps = 0` | 開發環境設 1 + `revalidate_freq = 0` |
| **`php -r 'opcache_reset();'` 沒作用** ★ | **CLI 與 FPM 是不同程序** | reload FPM 或用 cachetool |
| **符號連結切版後讀到舊檔** ★ | **`realpath_cache` 沒清** | reload FPM；`$realpath_root` |
| **命中率偏低（< 95%）** | 記憶體不足 / 頻繁重啟 | 看 `oom_restarts`、`hash_restarts` |
| `cache_full = true` | `memory_consumption` 不夠 | 調大到 256M+ |
| `oom_restarts > 0` | 同上 | 調大 `memory_consumption` |
| **`hash_restarts > 0`** | `max_accelerated_files` 太小 | 調大（用 `find -name '*.php' \| wc -l` 估算） |
| **annotation 失效** | `save_comments = 0` | **設成 1**（Doctrine、某些框架需要） |
| interned strings 快滿 | buffer 太小 | 調大 `interned_strings_buffer` 到 32M+ |
| **`php-fpm segfault`** | JIT 的 bug | **先試著關掉 JIT**（`jit_buffer_size = 0`） |
| **preload 後改程式碼沒生效** ★ | preload 是永久常駐 | **必須 `restart`**（不是 reload） |
| **preload 與符號連結衝突** ★★ | 路徑在啟動時就解析了 | **不要對符號連結部署用 preload** |
| 浪費比例持續增高 | 頻繁部署累積 | 定期 `reload`；或檢查是否有動態產生的檔案 |
| CLI 很慢 | `enable_cli = 0` | CLI 通常不需要（每次都是新程序） |

### 排查「部署後還是舊版」

```bash
# 【1】確認檔案真的是新的
$ ls -l /var/www/app/current
lrwxrwxrwx 1 ... current -> /var/www/app/releases/20260828-100000
$ git -C /var/www/app/current rev-parse --short HEAD
a1b2c3d

# 【2】★ 確認網站回報的版本
$ curl -s http://127.0.0.1/version
{"commit":"9f8e7d6", ...}          # ★ 不一致！

# 【3】看 OPcache 快取的是哪個路徑
$ cachetool opcache:status:scripts --fcgi=/run/php/php8.3-fpm.sock | grep -m5 releases
/var/www/app/releases/20260827-090000/public/index.php     # ★ 舊路徑

# 【4】處理
$ sudo systemctl reload php8.3-fpm
$ sleep 2 && curl -s http://127.0.0.1/version

# 【5】還是不行 → restart
$ sudo systemctl restart php8.3-fpm

# 【6】還是不行 → 檢查其他快取
$ php artisan optimize:clear         # Laravel 的 config/route/view 快取
$ sudo systemctl reload nginx        # Nginx 的 open_file_cache
$ redis-cli FLUSHDB                  # 應用層快取（★ 小心）

# 【7】確認 fastcgi_param 用的是 $realpath_root
$ sudo nginx -T | grep -A3 'location ~ \\.php'
fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;   # ★ 必須
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> # 設定檔位置
> /etc/php.d/10-opcache.ini
>
> # 檢視
> $ php --ini | grep opcache
> $ php -i | grep opcache.memory
>
> # ★ SELinux：file_cache 目錄需要正確的 context
> $ sudo mkdir -p /var/cache/php/opcache
> $ sudo chown apache:apache /var/cache/php/opcache
> $ sudo semanage fcontext -a -t httpd_cache_t "/var/cache/php(/.*)?"
> $ sudo restorecon -Rv /var/cache/php
>
> # ★ huge_code_pages 需要核心支援
> $ cat /sys/kernel/mm/transparent_hugepage/enabled
> [always] madvise never
>
> # reload
> $ sudo systemctl reload php-fpm
> ```

---

## 安全性注意事項

> [!danger] `opcache-status.php` 與 `opcache-reset.php` 必須限制存取
> ```
> opcache_get_status() 洩漏：
>   · 【所有已快取的 PHP 檔案完整路徑】（★ 暴露目錄結構與部署方式）
>   · 記憶體用量與統計
>   · PHP 的設定值
>
> opcache_reset() 若對外開放：
>   → 【任何人都可以重置 OPcache】
>     → 每次重置後所有檔案要重新編譯
>       → 【簡單有效的 DoS】
> ```
>
> **兩道防線**：
> ```php
> // ① 只允許本機或內網
> $ip = $_SERVER['REMOTE_ADDR'] ?? '';
> if (!in_array($ip, ['127.0.0.1','::1'], true) && !str_starts_with($ip, '10.0.9.')) {
>     http_response_code(404); exit;
> }
> // ② token（★ 從 web root 之外讀取）
> if (!hash_equals(trim(file_get_contents('/var/www/app/shared/deploy.token')),
>                  $_SERVER['HTTP_X_DEPLOY_TOKEN'] ?? '')) {
>     http_response_code(404); exit;
> }
> ```
> ```nginx
> # ③ Web 伺服器層也擋一次
> location ~ ^/opcache-(status|reset)\.php$ {
>     allow 127.0.0.1;
>     allow 10.0.9.0/24;
>     deny all;
>     try_files $uri =404;
>     include snippets/php-fpm.conf;
> }
> ```
> ```bash
> # ★ 從外部驗證
> $ curl -sk -o /dev/null -w '%{http_code}\n' https://網站/opcache-status.php
> 404      # 必須
> ```

> [!warning] `file_cache` 目錄的權限
> ```ini
> opcache.file_cache = /var/cache/php/opcache
> ```
> ```bash
> $ sudo chmod 700 /var/cache/php/opcache
> $ sudo chown www-data:www-data /var/cache/php/opcache
> ```
> **`file_cache` 中存的是「編譯後的 opcode」** ——
> 雖然不是原始碼，但**足以還原出程式的結構與字串常數**
> （包含可能寫死在程式中的金鑰）。
>
> **絕對不要放在 web root 內。**

> [!tip] `opcache.validate_permission` 與 `validate_root`
> ```ini
> opcache.validate_permission = 0    ; 預設 0
> opcache.validate_root = 0          ; 預設 0
> ```
> **多使用者共用同一個 FPM 的環境**（共享主機）才需要設成 1：
> - `validate_permission = 1`：檢查目前的使用者是否有權讀取該檔案
> - `validate_root = 1`：在 chroot 環境中防止不同 root 的快取混用
>
> **每個站台獨立 pool 的架構下不需要**（本來就是不同的共享記憶體）。

---

## 速查表

### 完整設定

```ini
opcache.enable = 1
opcache.enable_cli = 0
opcache.memory_consumption = 256          ; ★ MB
opcache.interned_strings_buffer = 32      ; ★ MB
opcache.max_accelerated_files = 20000     ; ★ find -name '*.php' | wc -l 估算
opcache.validate_timestamps = 0           ; ★★ 正式環境（部署後 reload FPM）
opcache.save_comments = 1                 ; ★ annotation 需要
opcache.file_cache = /var/cache/php/opcache
opcache.max_wasted_percentage = 5
opcache.huge_code_pages = 1
opcache.jit = tracing                     ; ★ 一般 Web 應用效益有限
opcache.jit_buffer_size = 128M
realpath_cache_size = 4096K               ; ★ 預設 256K 太小
realpath_cache_ttl = 600
```

```
開發環境：validate_timestamps = 1, revalidate_freq = 0
```

### 部署後必做 ★★★

```bash
sudo systemctl reload php8.3-fpm     # ★★ 同時清 OPcache 與 realpath_cache
sudo systemctl reload nginx          # ★ 清 open_file_cache
php artisan optimize:clear           # Laravel 的 config/route/view

# ★ 驗證新版真的生效
curl -s http://127.0.0.1/version     # 比對 commit hash
```

```
★ reload 而非 restart（零中斷）
★ php -r 'opcache_reset();' 【無效】（CLI 與 FPM 是不同程序）
```

### 三種快取都要處理

```
① OPcache          → reload FPM
② realpath_cache   → reload FPM（★ 符號連結部署時特別重要）
③ Nginx open_file_cache → reload nginx
＋ Laravel config/route/view cache → artisan optimize:clear
```

### 監控

```bash
cachetool opcache:status --fcgi=/run/php/php8.3-fpm.sock
cachetool opcache:reset  --fcgi=/run/php/php8.3-fpm.sock
cachetool opcache:status:scripts --fcgi=/run/php/php8.3-fpm.sock
curl -s http://127.0.0.1/opcache-status.php      # ★ 限本機存取
```

| 指標 | 警訊 | 調整 |
| --- | --- | --- |
| **`cache_full`** | true | 調大 `memory_consumption` |
| **`oom_restarts`** | > 0 | 調大 `memory_consumption` |
| **`hash_restarts`** | > 0 | 調大 `max_accelerated_files` |
| **命中率** | < 95% | 檢查記憶體與 `validate_timestamps` |
| 浪費比例 | > 10% | 定期 reload |
| interned strings | 快滿 | 調大 `interned_strings_buffer` |

### JIT

```
tracing   追蹤熱路徑（建議）
function  以函式為單位
0/disable 停用

★ 對典型 Web 應用只有 2-5% 提升（大部分時間在等 I/O）
★ 對 CPU 密集運算可快 5-10 倍
★ 一定要實測；segfault 時先關掉 JIT
```

### Preload（★ 謹慎）

```ini
opcache.preload = /var/www/app/current/preload.php
opcache.preload_user = app-user
```

```
★★ 三個問題：
① 改程式碼要 restart（不是 reload）→ 會中斷請求
② 與符號連結部署衝突（路徑在啟動時就解析了）→ 新舊混用
③ 效益只有約 7%，卻多用 100MB

→ 除非有實測證明的效益，否則【不要用】
```

### 安全

```
① opcache-status.php / opcache-reset.php 只允許本機或內網 + token
   （★ 洩漏所有檔案路徑；reset 可被用來 DoS）
② file_cache 目錄 chmod 700，絕不在 web root 內
③ 從外部驗證：curl https://網站/opcache-status.php 必須 404
```

### 排查「部署後還是舊版」

```bash
ls -l /var/www/app/current                                    # 符號連結指向哪
git -C /var/www/app/current rev-parse --short HEAD            # 檔案的版本
curl -s http://127.0.0.1/version                              # ★ 網站回報的版本
cachetool opcache:status:scripts --fcgi=... | grep releases   # ★ 快取的是哪個路徑
sudo systemctl reload php8.3-fpm                              # ★ 處理
nginx -T | grep 'fastcgi_param SCRIPT_FILENAME'               # ★ 要用 $realpath_root
```

---

## 練習題

> [!question]- 練習 1：測量 OPcache 的效果
> 1. 取一個真實的 Laravel 應用
> 2. `opcache.enable = 0`，`ab -n 2000 -c 20` 測 QPS
> 3. `opcache.enable = 1`，重測
> 4. **提升了幾倍？**
> 5. 再測 `validate_timestamps = 1` vs `0` 的差異
> 6. 用 `strace -c -p <fpm-pid>` 觀察 `stat()` 的呼叫次數

> [!question]- 練習 2：重現「部署後還是舊版」
> 1. 設定 `validate_timestamps = 0`
> 2. 建立 `/version` 端點回傳一個版本字串
> 3. 修改該字串
> 4. **不做任何 reload，`curl /version`** → 舊的還是新的？
> 5. `sudo systemctl reload php8.3-fpm` → 再測
> 6. **用符號連結切版重做一次**（觀察 realpath_cache 的影響）
> 7. 把「版本驗證」加進你的部署腳本

> [!question]- 練習 3：找出合適的 OPcache 參數
> 1. 部署 `opcache-status.php`
> 2. 讓網站跑一天（或用 `ab` 模擬）
> 3. 記錄：命中率、已快取檔案數、記憶體用量、浪費比例
> 4. **故意把 `max_accelerated_files` 設成 1000** → 觀察 `hash_restarts`
> 5. **故意把 `memory_consumption` 設成 32** → 觀察 `oom_restarts` 與 `cache_full`
> 6. 依實際用量調到合適值
> 7. `find /var/www/app -name '*.php' | wc -l` 驗算

> [!question]- 練習 4：JIT 實測
> 1. 用本篇的 `bench.php` 測 CPU 密集運算（JIT 開/關）
> 2. **快了幾倍？**
> 3. 用 `ab -n 3000 -c 20` 測真實的 Web 應用（JIT 開/關）
> 4. **提升了多少？記憶體多用了多少？**
> 5. **結論：你的應用該開 JIT 嗎？**
> 6. 查看 `opcache_get_status()['jit']` 的 buffer 使用量

> [!question]- 練習 5：完整的部署快取處理
> 1. 建立一個符號連結部署結構
> 2. 部署 v1，記錄 `/version` 的回傳
> 3. 部署 v2 但**故意不清任何快取**
> 4. **`/version` 回傳什麼？** 逐一嘗試：
>    - `artisan optimize:clear` → 變了嗎？
>    - `reload nginx` → 變了嗎？
>    - `reload php8.3-fpm` → 變了嗎？
> 5. **記錄「哪一個快取造成的」**
> 6. 寫一個會自動驗證版本的部署腳本

---

## 小測驗

Q1. **OPcache 的運作原理是什麼？沒開的效能差距大約多少**？

Q2. **`validate_timestamps = 0` 的好處與代價是什麼**？

Q3. **為什麼 `php -r 'opcache_reset();'` 不能清除 FPM 的 OPcache？正確的三種方式**？

Q4. **部署後為什麼要用 `reload` 而不是 `restart`**？

Q5. **`realpath_cache` 是什麼？為什麼符號連結部署時特別重要**？

Q6. **`oom_restarts` 與 `hash_restarts` 分別該調整什麼參數**？

Q7. **`opcache.save_comments = 0` 會造成什麼問題**？

Q8. **JIT 對典型的 Web 應用效益如何？什麼情況才值得開**？

Q9. **Preload 有哪三個嚴重問題**？

Q10. **`opcache-status.php` 為什麼必須限制存取**？

> [!question]- 測驗答案
> **Q1.** **運作原理**：PHP 執行前要經過「讀檔 → 詞法分析 → 語法分析 → 編譯成 opcode → 執行」，
> **OPcache 把編譯後的 opcode 存進共享記憶體**，
> **後續請求直接取用 opcode，跳過前四個步驟**。
> **效能差距**：實測一個 Laravel 應用（載入約 400 個 PHP 檔案）：
> ```
> OPcache 關閉： 85 req/s，平均 235ms
> OPcache 開啟：620 req/s，平均  32ms      ★ 約 7 倍
> ```
> **這是 PHP 最重要的一個設定。**
>
> **Q2.** **好處**：**完全不做時間戳檢查，速度最快** ——
> `validate_timestamps = 1` 時，每個請求（或每 `revalidate_freq` 秒）
> 都要對**每一個已快取的檔案做 `stat()`**，
> 一個載入 400 個檔案的請求就是 400 次系統呼叫。
> **代價**：**改了程式碼也不會生效，直到 OPcache 被重置** ——
> 部署新版後 OPcache 還記著舊的 opcode，**網站會繼續跑舊版**，
> 而 `git log` 與檔案內容都是新的，造成極度困惑。
> **必須在部署後 `systemctl reload php8.3-fpm`。**
>
> **Q3.** 因為 **CLI 與 FPM 是「不同的程序」，使用「不同的共享記憶體區」** ——
> `php -r 'opcache_reset();'` 只會（嘗試）清除 CLI 自己的 OPcache，
> 對 FPM 的完全沒有影響。
> **正確的三種方式**：
> ①**`sudo systemctl reload php8.3-fpm`**（★ 推薦：簡單、可靠、零中斷）；
> ②**透過 HTTP 端點呼叫 `opcache_reset()`**
> （需要限制存取 + token，見本篇的 `opcache-reset.php`）；
> ③**`cachetool opcache:reset --fcgi=/run/php/php8.3-fpm.sock`**
> （透過 FastCGI 協定直接與 FPM 溝通）。
>
> **Q4.** **`restart` 會殺掉所有 worker，正在處理的請求全部中斷，使用者看到 502**。
> **`reload`（送出 SIGUSR2）則是**：
> master 程序**啟動新的 worker（使用新的設定與空的 OPcache）**，
> **舊的 worker 處理完當前請求後才優雅結束** ——
> **零中斷**。
> **例外**：修改了 `ServerLimit` 這類需要重新配置共享記憶體的設定，
> 或使用了 **preload**（preload 的類別是永久常駐，reload 不會重新載入），
> 這時才需要 `restart`。
>
> **Q5.** **`realpath_cache` 快取「路徑字串 → 實體路徑」的解析結果** ——
> PHP 每次 `include`/`require` 都要解析路徑（涉及多次 `stat()`），
> 快取後可以省下大量系統呼叫。
> **符號連結部署時特別重要的原因有兩個**：
> ①**每一層符號連結都要解析**，路徑解析成本更高，快取效益更大；
> ②**★ 但快取也會造成問題** ——
> 部署時切換 `current -> releases/新版`，
> **`realpath_cache` 還記著舊的實體路徑**，
> 在 `realpath_cache_ttl`（預設 120 秒）內 **PHP 還是會讀到舊版的檔案**。
> 這與 OPcache 是**兩個獨立的快取**，
> 但 **`reload` FPM 會同時清掉兩者**。
>
> **Q6.** **`oom_restarts > 0`（因記憶體不足而重啟）** →
> **調大 `opcache.memory_consumption`**（例如 128M → 256M）。
> **`hash_restarts > 0`（因雜湊表滿而重啟）** →
> **調大 `opcache.max_accelerated_files`**。
> 後者的估算方式：
> ```bash
> find /var/www/app/current -name '*.php' -not -path '*/tests/*' | wc -l
> ```
> 設成比這個數字大（要留餘裕；OPcache 會自動取「大於等於它的質數」）。
> 兩者都會導致 **OPcache 被清空重來，命中率暴跌**。
>
> **Q7.** **`save_comments = 0` 會在編譯時丟棄 docblock（`/** ... */` 註解）** ——
> 這會讓**依賴 annotation 的功能全部失效**：
> Doctrine ORM 的 `@Entity`、`@Column`、
> Symfony 的 `@Route`、
> 某些 DI 容器的 `@Inject`、
> PHPUnit 的 `@dataProvider`、
> 以及任何用 Reflection 讀取 docblock 的套件。
> 症狀通常是**「本機正常，正式環境找不到路由／實體對應」**，且錯誤訊息很不直觀。
> **一律設成 `opcache.save_comments = 1`**（這是預設值，但有些「效能調校懶人包」會叫你關掉）。
>
> **Q8.** **對典型的 Web 應用效益很有限（約 2-5%）** ——
> 因為**Web 請求大部分時間在等 I/O**（資料庫查詢、檔案讀寫、外部 API），
> 而不是 CPU 運算；而且請求生命週期短，JIT 來不及發揮追蹤最佳化的優勢。
> 實測 Laravel：JIT off 620 req/s，JIT on 635 req/s（**還多用 128MB**）。
> **值得開的情況**：**CPU 密集的純運算** ——
> 數學計算、影像處理、加密、壓縮、長迴圈。
> 本篇的費氏數列測試中 JIT 快了 **8 倍**。
> **結論**：一般 CRUD 網站**不需要 JIT，把記憶體留給 OPcache**；
> 有大量運算的功能才值得測試。**一定要實測，不要因為「聽說很快」就開。**
> 另外某些 PHP 版本的 JIT 有 segfault 的 bug，遇到時先關掉它。
>
> **Q9.** ①**改了程式碼必須 `restart` 而非 `reload`** ——
> preload 的類別是**永久常駐在共享記憶體**，reload 不會重新載入，
> 而 restart **會中斷正在處理的請求**；
> ②**★★ 與符號連結部署衝突** ——
> `opcache.preload = /var/www/app/current/preload.php` 在 **FPM 啟動時**
> 就解析成 `releases/舊版/preload.php`，
> 部署後 `current` 指向新版，但 preload 的類別還是舊版的，
> **新舊程式碼混用，行為極難預測**；
> ③**效益不如預期** —— 實測 Laravel 只有約 7% 的提升，
> 卻多用了約 100MB 記憶體，還帶來上述兩個維運問題。
> **結論：除非有實測證明的明確效益，否則不要用 preload。**
>
> **Q10.** 因為 **`opcache_get_status()` 會洩漏**：
> **所有已快取的 PHP 檔案「完整路徑」** ——
> 這暴露了**目錄結構、部署方式（是否用符號連結、release 目錄的命名）、
> 使用了哪些框架與套件**，是攻擊者踩點的絕佳資訊；
> 以及記憶體用量、統計數據、PHP 的設定值。
> **而 `opcache_reset()` 若對外開放更嚴重** ——
> **任何人都可以重置 OPcache，每次重置後所有檔案都要重新編譯，
> 這是一個極簡單有效的 DoS**。
> **三道防線**：①程式中檢查來源 IP；②檢查 token（`hash_equals`）；
> ③Web 伺服器層 `allow`/`deny`。
> 從外部驗證 `curl https://網站/opcache-status.php` **必須是 404**。

---

## 延伸閱讀

- [[060-03-01-06-guide-PHP-安全設定]] — PHP 層的安全加固
- [[060-03-01-03-guide-PHP-ini重要參數]] — 其他效能相關參數
- [[060-03-01-02-guide-PHP-FPM設定與Pool調校]] — worker 調校與 reload
- [[060-03-01-04-guide-Composer-套件管理]] — autoload 最佳化
- [[060-02-02-05-guide-Nginx-靜態資源與快取]] — Nginx 端的快取
- [[060-01-01-08-guide-Git-伺服器端與自動部署]] — 零停機部署
