---
title: "Nuxt SSR 與 PM2 部署"
desc: "用 PM2 或 systemd 管理 Nuxt SSR 程序、cluster、零停機重載與記憶體監控"
aliases: [Nuxt SSR部署, PM2, ecosystem, reload, systemd Node]
tags: [群組/實務案例, 主題/部署, 主題/Nuxt, 主題/PM2]
category: 專案部署實戰
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[01-Nuxt-渲染模式與部署選型]]", "[[03-PM2-程序管理入門]]"]
updated: 2026-08-28
---

# Nuxt SSR 與 PM2 部署

> [!abstract] 這篇你會學到
> - **PM2 vs systemd** 的選擇
> - `ecosystem.config.cjs` 的**完整設定**
> - **★★ cluster 模式**與它的禁忌
> - **★★★ 零停機重載**（`pm2 reload` 的真相）
> - **優雅關閉**（SIGINT / SIGTERM）
> - **記憶體監控**與自動重啟
> - **systemd 的完整替代方案**
> - 完整的部署腳本

## 前置知識

- [[01-Nuxt-渲染模式與部署選型]] — 確定要用 SSR
- [[03-PM2-程序管理入門]] — PM2 基本操作
- [[01-部署共通觀念]] — releases/current 佈局

---

## PM2 vs systemd ★★

| | **PM2** | **systemd** |
| --- | --- | --- |
| 安裝 | `npm i -g pm2` | ✓ 系統內建 |
| **零停機重載** | **✓ `pm2 reload`** | ✗ 需要自己實作 |
| cluster | ✓ 內建 | ✗ 用 `Node cluster` 或多個 unit |
| 日誌 | 自己的檔案 + `pm2-logrotate` | **✓ journald（統一）** |
| 監控 | `pm2 monit` | `systemctl status` |
| **開機自啟** | `pm2 startup`（★ 有坑） | **✓ `systemctl enable`** |
| 記憶體上限重啟 | ✓ `max_memory_restart` | ✓ `MemoryMax` + `Restart` |
| **安全加固** | ✗ 有限 | **✓✓ 完整**（`ProtectSystem` 等） |
| 額外的常駐程序 | ★ PM2 daemon 本身 | ✗ 不需要 |
| 適用 | 需要 **cluster + 零停機** | **★★ 加固要求高、單一實例** |

> [!tip] 怎麼選 ★★
> ```
> ★★ 用 PM2：
>   · 需要【cluster 多程序】提升吞吐
>   · 需要【零停機重載】（reload）
>   · 團隊熟悉 PM2 的操作
>
> ★★ 用 systemd：
>   · 只需要單一實例
>   · ★ 要用 systemd 的安全加固（ProtectSystem / LoadCredential）
>   · 希望日誌統一到 journald
>   · ★ 不想多一個 PM2 daemon
>
> ★★★ 混合方案（本手冊推薦）：
>   用 systemd 管理 PM2 → 兼得兩者的好處
>   → systemd 保證開機自啟與程序監管
>   → PM2 提供 cluster 與零停機重載
> ```

---

## PM2 部署 ★★

### `ecosystem.config.cjs`

```javascript
// /var/www/nuxt-app/shared/ecosystem.config.cjs
// ★★ 副檔名用 .cjs（★ 專案的 package.json 有 "type": "module" 時 .js 會失敗）
module.exports = {
  apps: [
    {
      name: 'nuxt-app',
      script: '/var/www/nuxt-app/current/.output/server/index.mjs',
      cwd: '/var/www/nuxt-app/current',

      // ═══ ★★ 執行模式 ═══
      exec_mode: 'cluster',            // ★ cluster | fork
      instances: 2,                    // ★★ 數字 或 'max'（= CPU 核心數）
      // ★ 建議：CPU 核心數 - 1，留一顆給 Nginx 與系統

      // ═══ ★★★ 零停機重載 ═══
      wait_ready: true,                // ★★★ 等程式送出 'ready' 訊號
      listen_timeout: 10000,           // ★ 等待 ready 的逾時（10 秒）
      kill_timeout: 8000,              // ★★ 送 SIGINT 後等 8 秒才強制 kill

      // ═══ 環境變數（★★ 用 NUXT_ 前綴，執行時讀取）═══
      env: {
        NODE_ENV: 'production',
        HOST: '127.0.0.1',             // ★★★ 只聽本機！由 Nginx 反代
        PORT: 3000,
        NUXT_PUBLIC_API_BASE: '/api',
        NUXT_PUBLIC_APP_ENV: 'production',
        // ★★ 內部 CA（SSR 呼叫內部 HTTPS API 時必須）
        NODE_EXTRA_CA_CERTS: '/usr/local/share/ca-certificates/internal-ca.crt',
        // ★ 時區
        TZ: 'Asia/Taipei',
      },

      // ═══ ★★ 記憶體與重啟 ═══
      max_memory_restart: '600M',      // ★★ 超過就重啟（防記憶體洩漏）
      min_uptime: 10000,               // ★ 啟動後活超過 10 秒才算成功
      max_restarts: 10,                // ★ 連續失敗 10 次就放棄
      restart_delay: 3000,             // ★ 重啟間隔
      exp_backoff_restart_delay: 200,  // ★ 指數退避（避免瘋狂重啟）
      autorestart: true,

      // ═══ 日誌 ═══
      out_file: '/var/log/nuxt-app/out.log',
      error_file: '/var/log/nuxt-app/error.log',
      merge_logs: true,                // ★ cluster 的多個實例合併到同一個檔
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      time: true,

      // ═══ ★ 不要用 watch（正式環境）═══
      watch: false,

      // ═══ 其他 ═══
      node_args: [
        '--max-old-space-size=512',    // ★ 每個實例的堆上限
      ],
      source_map_support: false,       // ★ 正式環境不需要
    },
  ],
};
```

> [!danger] `HOST: '127.0.0.1'` 是必要的 ★★★
> ```
> ❌ HOST: '0.0.0.0'（Nuxt 的預設值）
>   → ★★★ Node 服務【直接暴露在所有網路介面】
>     → 任何人可以 http://伺服器IP:3000/ 【繞過 Nginx】
>       → 繞過 TLS、繞過 WAF、繞過限流、繞過 IP 限制
>       → ★★ 也繞過所有的安全標頭
>
> ✅ ★★★ HOST: '127.0.0.1'
>   → 只有本機能連 → 必須經過 Nginx
>
> ★ 驗證（從另一台機器）：
>   nc -zv 伺服器IP 3000
>   → 應該 connection refused
> ```

```bash
# ★★ 檢查有沒有誤開
$ sudo ss -tlnp | grep 3000
LISTEN 0 511 127.0.0.1:3000 0.0.0.0:* users:(("node",pid=1234,fd=20))
#              ^^^^^^^^^ ★ 必須是 127.0.0.1，不是 0.0.0.0 或 *
```

### ★★★ 優雅關閉與 `wait_ready`

> [!danger] 沒有正確實作優雅關閉，`pm2 reload` 就不是零停機 ★★★
> ```
> ★★ pm2 reload 的實際流程（cluster 模式）：
>   ① 啟動一個新的實例
>   ② ★★★ 【等它送出 'ready' 訊號】（wait_ready: true 時）
>   ③ 把舊實例移出負載平衡
>   ④ 對舊實例送 SIGINT
>   ⑤ ★★ 等 kill_timeout（預設 1600ms）
>   ⑥ 還沒退出就 SIGKILL 強制殺掉
>
> ★★★ 兩個必要條件：
>   ① 程式要在【真的能接受請求後】送出 process.send('ready')
>      → 否則 PM2 太早切換 → ★ 請求打到還沒 ready 的實例 → 502
>   ② 程式要處理 SIGINT【優雅關閉】
>      → 否則正在處理的請求會被【中途砍掉】→ 使用者看到錯誤
>      → kill_timeout 也要調大（預設 1600ms 太短）
> ```

```typescript
// server/plugins/graceful.ts —— ★★ Nuxt 的 Nitro plugin
export default defineNitroPlugin((nitroApp) => {
  let shuttingDown = false;
  let activeRequests = 0;

  // ★ 計數進行中的請求
  nitroApp.hooks.hook('request', () => { activeRequests++; });
  nitroApp.hooks.hook('afterResponse', () => { activeRequests--; });

  // ★★★ 告訴 PM2 已經準備好接受請求
  nitroApp.hooks.hook('listen', () => {
    if (process.send) {
      process.send('ready');
      console.log('[graceful] 已送出 ready 訊號');
    }
  });

  async function shutdown(signal: string) {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(`[graceful] 收到 ${signal}，開始優雅關閉…`);

    // ★★ 等待進行中的請求完成（最多 6 秒）
    const deadline = Date.now() + 6000;
    while (activeRequests > 0 && Date.now() < deadline) {
      console.log(`[graceful] 等待 ${activeRequests} 個請求完成…`);
      await new Promise((r) => setTimeout(r, 200));
    }

    if (activeRequests > 0) {
      console.warn(`[graceful] 逾時，仍有 ${activeRequests} 個請求未完成`);
    }

    // ★ 關閉資源（資料庫連線池、Redis…）
    try { await nitroApp.hooks.callHook('close'); } catch {}

    console.log('[graceful] 關閉完成');
    process.exit(0);
  }

  process.on('SIGINT',  () => shutdown('SIGINT'));   // ★★★ PM2 送這個
  process.on('SIGTERM', () => shutdown('SIGTERM'));  // ★ systemd / Docker 送這個

  // ★ 未捕捉的錯誤也要記錄（★ 不要靜默死掉）
  process.on('uncaughtException', (err) => {
    console.error('[fatal] uncaughtException:', err);
    shutdown('uncaughtException');
  });
  process.on('unhandledRejection', (reason) => {
    console.error('[fatal] unhandledRejection:', reason);
  });
});
```

> [!warning] PM2 送 SIGINT，systemd 與 Docker 送 SIGTERM ★★
> ```
> ★★ 兩個都要處理：
>   process.on('SIGINT',  handler);    ← PM2
>   process.on('SIGTERM', handler);    ← systemd / Docker / k8s
>
> ★ 只處理一個 → 換管理方式時就壞掉
>
> ★ PM2 也可以改成送 SIGTERM：
>   ecosystem: { kill_signal: 'SIGTERM' }
>   → 但仍建議兩個都處理
> ```

### ★★ cluster 模式的禁忌

```javascript
exec_mode: 'cluster',
instances: 2,
```

> [!danger] cluster 模式的四個禁忌 ★★★
> ```
> ★★ cluster = 【多個獨立的 Node 程序】，它們【不共享記憶體】
>
> ① ★★★ 【記憶體中的狀態】不能用
>      const cache = new Map();          ← ✗ 每個程序有自己的一份
>      let counter = 0;                  ← ✗ 各數各的
>      → ★ 改用 Redis
>
> ② ★★★ 【檔案式 session】不能用
>      → 使用者的請求可能打到不同的程序
>        → ★ 一下登入一下登出
>      → 改用 Redis / 資料庫 / JWT
>
> ③ ★★★ 【排程】會執行 N 次
>      setInterval(() => sendDailyReport(), ...)  ← ✗ 2 個實例 = 寄 2 封信
>      → ★ 用 process.env.NODE_APP_INSTANCE === '0' 判斷
>      → ★★ 更好：排程用【獨立的 cron 或 worker】，不要放在 web 程序裡
>
> ④ ★★ 【檔案鎖 / 本機暫存】不可靠
>      → 用共享儲存或 Redis 的分散式鎖
> ```

```javascript
// ★ 只在第一個實例執行排程（★ 但仍建議用獨立的 worker）
if (process.env.NODE_APP_INSTANCE === '0' || !process.env.NODE_APP_INSTANCE) {
  setInterval(async () => {
    await runDailyReport();
  }, 24 * 60 * 60 * 1000);
}
```

```bash
# ★★ 驗證 cluster 沒有狀態問題
$ for i in $(seq 1 10); do
    curl -s https://app.example.gov.tw/api/whoami -b cookies.txt -c cookies.txt | \
      jq -r '.user // "未登入"'
  done
# ★ 若出現時而登入時而未登入 → session 沒有共享
```

```typescript
// ★★ Nuxt 用 Redis 存 session
// server/plugins/session.ts 或用 nuxt-auth-utils + Redis
// nuxt.config.ts
export default defineNuxtConfig({
  nitro: {
    storage: {
      // ★★ session 用 Redis（cluster 安全）
      sessions: {
        driver: 'redis',
        host: '127.0.0.1',
        port: 6379,
        db: 1,
      },
    },
  },
});
```

### PM2 操作

```bash
# ═══ 啟動 ═══
$ pm2 start /var/www/nuxt-app/shared/ecosystem.config.cjs --env production

# ═══ ★★★ 零停機重載（部署後用這個）═══
$ pm2 reload nuxt-app
# ★ 或 pm2 reload ecosystem.config.cjs --update-env

# ═══ ★ restart 會有中斷（不要用於正式環境的更新）═══
$ pm2 restart nuxt-app        # ★★ 直接殺掉再啟動 → 有停機

# ═══ 狀態 ═══
$ pm2 list
$ pm2 describe nuxt-app
$ pm2 monit                   # ★ 即時監控

# ═══ 日誌 ═══
$ pm2 logs nuxt-app --lines 50
$ pm2 logs nuxt-app --err     # 只看錯誤
$ pm2 flush                   # 清空日誌

# ═══ ★★ 日誌輪替（必裝）═══
$ pm2 install pm2-logrotate
$ pm2 set pm2-logrotate:max_size 50M
$ pm2 set pm2-logrotate:retain 14
$ pm2 set pm2-logrotate:compress true
$ pm2 set pm2-logrotate:rotateInterval '0 0 * * *'
```

> [!danger] `pm2 startup` + `pm2 save` 的陷阱 ★★★
> ```
> $ pm2 startup systemd -u deploy --hp /home/deploy
> # → 產生一個 systemd unit
>
> $ pm2 save
> # ★★ 把【目前正在跑的】程序清單存到 ~/.pm2/dump.pm2
>
> ★★★ 陷阱：
>   pm2 save 存的是【當下的狀態】
>     → 若當下有一個測試用的程序在跑 → 也會被存進去
>     → 若當下 app 是【停止的】→ 開機後也不會啟動
>     → ★★ 改了 ecosystem.config.cjs 但【沒有再 save】
>       → 開機後跑的是【舊設定】
>
> ★★ 正確流程（每次改設定後）：
>   pm2 reload ecosystem.config.cjs --update-env
>   pm2 save                        ← ★★★ 不要忘記
>
> ★ 驗證：
>   cat ~/.pm2/dump.pm2 | jq '.[].name, .[].env.PORT'
> ```

```bash
# ★★ 設定開機自啟
$ pm2 startup systemd -u deploy --hp /home/deploy
[PM2] To setup the Startup Script, copy/paste the following command:
sudo env PATH=$PATH:/usr/bin pm2 startup systemd -u deploy --hp /home/deploy

$ sudo env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 \
    startup systemd -u deploy --hp /home/deploy

$ pm2 save

# ★ 測試（★ 真的重開機驗證）
$ sudo systemctl status pm2-deploy
$ sudo reboot
# 開機後
$ pm2 list
```

---

## systemd 部署（替代方案）★★

```ini
# /etc/systemd/system/nuxt-app.service
[Unit]
Description=Nuxt SSR Application
Documentation=https://github.com/Information-Study/nuxt-frontend
After=network-online.target
Wants=network-online.target

[Service]
Type=notify-reload
# ★ 或 Type=simple（★ notify 需要程式支援 sd_notify）
NotifyAccess=all

User=deploy
Group=www-data
WorkingDirectory=/var/www/nuxt-app/current

# ═══ 環境變數 ═══
Environment=NODE_ENV=production
Environment=HOST=127.0.0.1
Environment=PORT=3000
Environment=TZ=Asia/Taipei
Environment=NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/internal-ca.crt
Environment=NODE_OPTIONS=--max-old-space-size=512
# ★★ 秘密從檔案讀（★ 不寫在 unit 裡）
EnvironmentFile=-/var/www/nuxt-app/shared/.env

ExecStart=/usr/bin/node /var/www/nuxt-app/current/.output/server/index.mjs

# ═══ ★★ 重啟策略 ═══
Restart=always
RestartSec=3
StartLimitBurst=5
StartLimitIntervalSec=60

# ═══ ★★ 優雅關閉 ═══
KillSignal=SIGTERM
TimeoutStopSec=15                    # ★ 給程式 15 秒優雅關閉
KillMode=mixed

# ═══ ★★ 記憶體限制 ═══
MemoryMax=800M
MemoryHigh=600M                      # ★ 到這個值開始積極回收

# ═══ ★★★ 安全加固 ═══
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict                 # ★ 整個檔案系統唯讀
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
LockPersonality=true
RestrictSUIDSGID=true
RemoveIPC=true

# ★★★ V8 的 JIT 需要可寫可執行的記憶體
MemoryDenyWriteExecute=false

# ★ 只允許寫這些目錄
ReadWritePaths=/var/log/nuxt-app /var/www/nuxt-app/shared

# ═══ 日誌 ═══
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nuxt-app

[Install]
WantedBy=multi-user.target
```

> [!danger] `MemoryDenyWriteExecute=true` 會讓 Node 直接掛掉 ★★★
> ```
> ★★ V8 引擎的 JIT 編譯需要「可寫且可執行」的記憶體頁
>   → MemoryDenyWriteExecute=true 會禁止這個
>     → ★★★ Node 啟動就 SIGSEGV 或 "Cannot allocate memory"
>
> ★ 必須明確設 false（★ 即使其他加固都開）：
>   MemoryDenyWriteExecute=false
>
> ★ 這是 Node.js 服務的 systemd 加固最常見的坑
> ```

```bash
$ sudo mkdir -p /var/log/nuxt-app && sudo chown deploy:www-data /var/log/nuxt-app
$ sudo systemctl daemon-reload
$ sudo systemctl enable --now nuxt-app
$ sudo systemctl status nuxt-app
$ sudo journalctl -u nuxt-app -f

# ★★ systemd 的「零停機」需要額外處理
#   → 單一實例的 restart 一定有中斷（1～3 秒）
#   → ★ 解法：跑兩個 unit + Nginx upstream 輪流重啟（見下方）
```

### ★★ systemd 的零停機方案

```ini
# ★ 用 template unit 跑多個實例
# /etc/systemd/system/nuxt-app@.service
[Unit]
Description=Nuxt SSR Application (instance %i)
After=network-online.target

[Service]
User=deploy
WorkingDirectory=/var/www/nuxt-app/current
Environment=NODE_ENV=production
Environment=HOST=127.0.0.1
Environment=PORT=300%i                 # ★ 3001, 3002...
ExecStart=/usr/bin/node /var/www/nuxt-app/current/.output/server/index.mjs
Restart=always
RestartSec=3
KillSignal=SIGTERM
TimeoutStopSec=15
MemoryDenyWriteExecute=false
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/log/nuxt-app

[Install]
WantedBy=multi-user.target
```

```bash
$ sudo systemctl enable --now nuxt-app@1 nuxt-app@2
```

```nginx
# ★★ Nginx upstream
upstream nuxt_backend {
    server 127.0.0.1:3001 max_fails=2 fail_timeout=10s;
    server 127.0.0.1:3002 max_fails=2 fail_timeout=10s;
    keepalive 32;
}
```

```bash
#!/usr/bin/env bash
# ★★ 輪流重啟（零停機）
for i in 1 2; do
    echo "重啟實例 $i…"
    sudo systemctl restart "nuxt-app@$i"
    # ★★ 等它真的能服務了才動下一個
    for n in $(seq 1 30); do
        curl -sf -o /dev/null "http://127.0.0.1:300$i/" && break
        sleep 1
    done
    curl -sf -o /dev/null "http://127.0.0.1:300$i/" || {
        echo "✗✗ 實例 $i 起不來，中止"; exit 1; }
    echo "  ✓ 實例 $i 已就緒"
    sleep 2
done
```

---

## 完整實戰範例：部署腳本

```bash
#!/usr/bin/env bash
# /usr/local/bin/deploy-nuxt —— 從 GitHub 部署 Nuxt SSR
set -euo pipefail

APP=/var/www/nuxt-app
REPO="git@github.com:Information-Study/nuxt-frontend.git"
BRANCH="${1:-main}"
KEEP=5
SITE="https://app.example.gov.tw"
PM2_APP=nuxt-app
REL="$APP/releases/$(date +%Y%m%d-%H%M%S)"

c(){ echo -e "\033[36m[$(date +%T)]\033[0m $*"; }
die(){ echo -e "\033[31m✗ $*\033[0m" >&2; exit 1; }

exec 200>/var/lock/deploy-nuxt.lock
flock -n 200 || die "已有部署在進行中"

c "═══ 部署 Nuxt SSR（$BRANCH）═══"
[ "$(whoami)" = deploy ] || die "必須用 deploy 使用者"

# ══ 【1】clone ══
c "【1】clone"
mkdir -p "$REL"
git clone --depth 1 --branch "$BRANCH" --single-branch "$REPO" "$REL" 2>&1 | sed 's/^/    /'
COMMIT=$(cd "$REL" && git rev-parse --short HEAD)
c "    $COMMIT — $(cd "$REL" && git log -1 --pretty=%s)"
rm -rf "$REL/.git"
cd "$REL"

# ══ 【2】建置 ══
c "【2】npm ci && build"
npm ci --no-audit --no-fund 2>&1 | tail -3 | sed 's/^/    /'
export NUXT_PUBLIC_APP_VERSION="$COMMIT"
export NODE_OPTIONS="--max-old-space-size=4096"
npm run build 2>&1 | tail -12 | sed 's/^/    /'

[ -f "$REL/.output/server/index.mjs" ] || die "找不到 .output/server/index.mjs（★ preset 是 node-server 嗎？）"

# ══ 【3】★★ 秘密掃描 ══
c "【3】★★ 秘密掃描"
if grep -rlE 'apiSecret|dbPassword|NUXT_API_SECRET|sk_live|-----BEGIN' \
     "$REL/.output/public/" 2>/dev/null; then
    die "★★★ 秘密洩漏到客戶端產物"
fi
find "$REL/.output/public" -name '*.map' -delete 2>/dev/null || true
c "    ✓ 通過"

# ══ 【4】清理與連結 ══
c "【4】清理"
rm -rf "$REL/node_modules" "$REL/.nuxt" "$REL/app" "$REL/components" \
       "$REL/pages" "$REL/tests" 2>/dev/null || true
# ★★ .output/server/node_modules 已打包好，不需要專案的 node_modules
[ -f "$APP/shared/.env" ] && ln -sfn "$APP/shared/.env" "$REL/.env"
du -sh "$REL/.output" | sed 's/^/    /'

# ══ 【5】★★ 切換前的煙霧測試（★ 在暫時的埠上）══
c "【5】★★ 煙霧測試（127.0.0.1:3999）"
set -a; [ -f "$APP/shared/.env" ] && . "$APP/shared/.env"; set +a
HOST=127.0.0.1 PORT=3999 NODE_ENV=production \
  NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/internal-ca.crt \
  node "$REL/.output/server/index.mjs" > /tmp/nuxt-smoke.log 2>&1 &
SMOKE=$!
trap "kill $SMOKE 2>/dev/null || true" EXIT

OK=0
for i in $(seq 1 30); do
    curl -sf -o /dev/null --max-time 3 http://127.0.0.1:3999/ && { OK=1; break; }
    kill -0 $SMOKE 2>/dev/null || { c "    ✗ 程序已退出"; break; }
    sleep 1
done
if [ "$OK" != 1 ]; then
    echo "── 煙霧測試日誌 ──"; tail -30 /tmp/nuxt-smoke.log | sed 's/^/    /'
    die "★★ 新版本無法啟動，不切換"
fi

# ★ 額外檢查
curl -s http://127.0.0.1:3999/ | grep -q '<div id="__nuxt">' || c "    ⚠ HTML 結構異常"
RSS=$(ps -o rss= -p $SMOKE | tr -d ' ')
c "    ✓ 啟動成功（RSS $((RSS/1024)) MB）"
kill $SMOKE 2>/dev/null || true
trap - EXIT
sleep 1

# ══ 【6】權限 ══
c "【6】權限"
find "$REL" -type d -exec chmod 750 {} \;
find "$REL" -type f -exec chmod 640 {} \;
chmod 755 "$REL/.output/server/index.mjs"
# ★ Nginx 要能讀 .output/public（直接送靜態資源）
chmod -R o+rX "$REL/.output/public" 2>/dev/null || true

# ══ 【7】★★★ 原子切換 ══
PREV=$(readlink "$APP/current" 2>/dev/null || echo "")
c "【7】★★★ 原子切換"
ln -sfn "$REL" "$APP/current.tmp"
mv -Tf "$APP/current.tmp" "$APP/current"

# ══ 【8】★★★ 零停機重載 ══
c "【8】★★★ pm2 reload"
if pm2 describe "$PM2_APP" >/dev/null 2>&1; then
    pm2 reload "$APP/shared/ecosystem.config.cjs" --update-env 2>&1 | tail -5 | sed 's/^/    /'
else
    pm2 start "$APP/shared/ecosystem.config.cjs" --env production 2>&1 | tail -5 | sed 's/^/    /'
fi
pm2 save >/dev/null 2>&1          # ★★★ 不要忘記
sudo nginx -t && sudo systemctl reload nginx

# ══ 【9】★★★ 驗證 ══
c "【9】★★★ 驗證"
sleep 3
FAIL=0
v(){ printf '    %-40s ' "$1"; if eval "$2" >/dev/null 2>&1; then echo "✓"; else echo "✗"; FAIL=1; fi; }

v "首頁 200"           "[ \"\$(curl -so /dev/null -w '%{http_code}' --max-time 15 $SITE/)\" = 200 ]"
v "★ SSR 有渲染內容"    "curl -s --max-time 15 $SITE/ | grep -q '<div id=\"__nuxt\"><'"
v "版本正確"           "curl -s $SITE/ | grep -q '$COMMIT'"
v "★ 靜態資源"         "[ \"\$(curl -so /dev/null -w '%{http_code}' $SITE/_nuxt/)\" != 502 ]"
v "★★ 只聽 127.0.0.1"  "! ss -tln | grep -qE '0\.0\.0\.0:3000|\*:3000'"

# ★ PM2 狀態
STATUS=$(pm2 jlist | jq -r ".[] | select(.name==\"$PM2_APP\") | .pm2_env.status" | head -1)
printf '    %-40s %s\n' "PM2 狀態" "$STATUS"
[ "$STATUS" = online ] || FAIL=1

RESTARTS=$(pm2 jlist | jq -r ".[] | select(.name==\"$PM2_APP\") | .pm2_env.restart_time" | head -1)
printf '    %-40s %s\n' "重啟次數" "$RESTARTS"

if [ "$FAIL" != 0 ]; then
    echo -e "\033[31m    ✗✗ 驗證失敗 —— 回退\033[0m"
    pm2 logs "$PM2_APP" --lines 30 --nostream 2>/dev/null | tail -30 | sed 's/^/    /'
    [ -n "$PREV" ] && {
        ln -sfn "$PREV" "$APP/current.tmp"
        mv -Tf "$APP/current.tmp" "$APP/current"
        pm2 reload "$APP/shared/ecosystem.config.cjs" --update-env
        pm2 save >/dev/null
        echo "    ✓ 已回退到 $PREV"
    }
    exit 1
fi

# ══ 【10】清理 ══
c "【10】清理（保留 $KEEP 個）"
cd "$APP/releases"
ls -1dt */ 2>/dev/null | tail -n +$((KEEP+1)) | while read -r d; do
    echo "    刪除 $d"; rm -rf "$d"
done

c "═══ ✓ 部署完成：$COMMIT ═══"
pm2 list | sed 's/^/  /'
```

---

## 記憶體監控 ★★

```bash
#!/usr/bin/env bash
# /usr/local/bin/nuxt-health —— Nuxt SSR 健康檢查
set -uo pipefail
APP="${1:-nuxt-app}"
SITE="${2:-https://app.example.gov.tw}"

echo "═══ Nuxt SSR 健康檢查 ═══"

echo -e "\n【1】PM2 狀態"
pm2 jlist 2>/dev/null | jq -r --arg a "$APP" '
  .[] | select(.name==$a) |
  "  實例 \(.pm_id)  \(.pm2_env.status)  " +
  "RSS \((.monit.memory/1048576)|floor)MB  " +
  "CPU \(.monit.cpu)%  " +
  "重啟 \(.pm2_env.restart_time)  " +
  "運行 \(((now*1000 - .pm2_env.pm_uptime)/3600000)|floor)h"'

echo -e "\n【2】★★ 記憶體趨勢"
MEM=$(pm2 jlist | jq -r --arg a "$APP" '[.[] | select(.name==$a) | .monit.memory] | add // 0')
MEMB=$((MEM/1048576))
LIMIT=600
printf '  總計 %d MB / 上限 %d MB per instance  ' "$MEMB" "$LIMIT"
[ "$MEMB" -gt $((LIMIT * 2)) ] && echo "⚠ 偏高" || echo "✓"

echo -e "\n【3】★ 重啟次數（★ 頻繁重啟 = 有問題）"
R=$(pm2 jlist | jq -r --arg a "$APP" '[.[] | select(.name==$a) | .pm2_env.restart_time] | add // 0')
printf '  %d 次  ' "$R"
[ "$R" -gt 20 ] && echo "⚠ 檢查 pm2 logs $APP --err" || echo "✓"

echo -e "\n【4】★★ 網路綁定"
printf '  '
if ss -tln | grep -qE '0\.0\.0\.0:3000|\*:3000'; then
    echo "✗✗✗ 綁在 0.0.0.0 —— 可繞過 Nginx！"
else
    ss -tlnp 2>/dev/null | grep ':300[0-9]' | awk '{print "  " $4}' || echo "  無 3000 系列的監聽"
fi

echo -e "\n【5】回應時間"
for i in 1 2 3; do
    printf '  第 %d 次  ' "$i"
    curl -so /dev/null -w 'HTTP %{http_code}  總計 %{time_total}s  TTFB %{time_starttransfer}s\n' \
      --max-time 20 "$SITE/"
done

echo -e "\n【6】★ 最近的錯誤"
pm2 logs "$APP" --err --lines 10 --nostream 2>/dev/null | \
  grep -vE '^$|^\s*$' | tail -10 | sed 's/^/  /' || echo "  （無）"

echo -e "\n【7】★★ 記憶體洩漏偵測"
echo "  連續取樣 5 次（每次間隔 10 秒）："
for i in $(seq 1 5); do
    M=$(pm2 jlist | jq -r --arg a "$APP" '[.[] | select(.name==$a) | .monit.memory] | add // 0')
    printf '    #%d  %d MB\n' "$i" "$((M/1048576))"
    [ "$i" -lt 5 ] && sleep 10
done
echo "  ★ 若持續上升且不回落 → 可能有記憶體洩漏"
```

```bash
# ★ 排程監控
$ sudo tee /etc/cron.d/nuxt-health >/dev/null <<'EOF'
*/10 * * * * deploy /usr/local/bin/nuxt-health nuxt-app > /tmp/nuxt-health.txt 2>&1; \
  grep -q '✗✗' /tmp/nuxt-health.txt && \
  mail -s "【警告】Nuxt SSR 異常" ops@example.gov.tw < /tmp/nuxt-health.txt
EOF
```

> [!warning] SSR 的記憶體洩漏 ★★
> ```
> ★★ SSR 特別容易洩漏，因為每個請求都在同一個程序裡建立元件樹
>
> 常見來源：
>   · ★★ 模組層級的 Map / 陣列不斷累積
>       const cache = new Map();  // ★ 沒有上限 → 一直長
>   · ★ 全域事件監聽器沒移除
>   · ★★ 在 setup 裡註冊 setInterval 但沒 clear
>   · 第三方套件的已知洩漏
>
> ★★ 防護：
>   ① max_memory_restart: '600M'（PM2）或 MemoryMax（systemd）
>   ② ★ 定期監控趨勢（不只看當下的值）
>   ③ 用 node --inspect + Chrome DevTools 的 Heap Snapshot 定位
>   ④ ★ cluster 多實例 → 單一實例洩漏不會拖垮整個服務
> ```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`pm2 reload` 仍有 502** ★★★ | 沒送 `ready` 訊號 | Nitro plugin 加 `process.send('ready')` + `wait_ready: true` |
| **請求被中途砍掉** ★★ | 沒處理 SIGINT | 實作優雅關閉 + 調大 `kill_timeout` |
| **服務可繞過 Nginx** ★★★ | `HOST=0.0.0.0` | 改 `HOST=127.0.0.1` |
| **cluster 下 session 亂掉** ★★★ | 檔案式 session | 改用 Redis |
| **排程執行 N 次** ★★★ | cluster 每個實例都跑 | `NODE_APP_INSTANCE === '0'` 或獨立 worker |
| **開機後跑舊設定** ★★ | 改了 ecosystem 沒 `pm2 save` | 每次 reload 後 `pm2 save` |
| **systemd 下 Node 直接掛** ★★★ | `MemoryDenyWriteExecute=true` | 設 **`false`** |
| `ecosystem.config.js` 載入失敗 | 專案 `"type": "module"` | 副檔名改 **`.cjs`** |
| **記憶體持續增長** ★★ | SSR 記憶體洩漏 | `max_memory_restart` + Heap Snapshot |
| **SSR 呼叫內部 HTTPS 失敗** ★★ | 沒信任內部 CA | `NODE_EXTRA_CA_CERTS` |
| PM2 日誌塞滿磁碟 ★ | 沒裝 logrotate | `pm2 install pm2-logrotate` |
| 頻繁重啟 | 啟動就 crash | `pm2 logs --err`；`min_uptime` |
| 502 但 PM2 顯示 online | 埠不對或還沒 listen | `ss -tlnp \| grep 3000` |

### 排查

```bash
# 【1】★★ PM2 狀態與重啟次數
$ pm2 list
$ pm2 describe nuxt-app | grep -E 'status|restarts|uptime|memory|script'

# 【2】★★★ 網路綁定（最重要的安全檢查）
$ sudo ss -tlnp | grep node
LISTEN 0 511 127.0.0.1:3000 ...      # ★ 必須是 127.0.0.1

# 【3】直接測試 Node（繞過 Nginx）
$ curl -sI http://127.0.0.1:3000/
$ curl -s http://127.0.0.1:3000/ | head -20

# 【4】★★ ready 訊號有沒有送
$ pm2 logs nuxt-app --lines 30 | grep -i ready
$ pm2 describe nuxt-app | grep -i 'wait ready'

# 【5】★★ reload 時真的零停機嗎
$ while true; do
    curl -so /dev/null -w '%{http_code} ' --max-time 5 https://app.example.gov.tw/
    sleep 0.2
  done &
$ pm2 reload nuxt-app
# ★ 觀察有沒有出現 502 / 000

# 【6】記憶體
$ pm2 monit
$ ps -o pid,rss,vsz,cmd -C node

# 【7】★ 產生 Heap Snapshot（定位洩漏）
$ pm2 sendSignal SIGUSR2 nuxt-app     # ★ 若程式有實作
# ★ 或用 --inspect
$ node --inspect=127.0.0.1:9229 .output/server/index.mjs
# → Chrome 開 chrome://inspect → Memory → Take heap snapshot

# 【8】systemd
$ sudo systemctl status nuxt-app
$ sudo journalctl -u nuxt-app -n 50 --no-pager
$ sudo systemd-analyze security nuxt-app     # ★ 加固評分
```

---

## 安全性注意事項

> [!danger] 三個必須做的安全設定 ★★★
> ```
> ① ★★★ HOST=127.0.0.1
>      → 否則 Node 服務可以被【直接存取】，繞過：
>        TLS、WAF（ModSecurity）、限流、IP 限制、安全標頭
>      → 驗證：ss -tlnp | grep 3000
>
> ② ★★ 不要用 root 執行
>      PM2:     pm2 startup systemd -u deploy
>      systemd: User=deploy
>      → SSR 程序有 RCE 漏洞時，影響範圍受限
>
> ③ ★★ 秘密只放在 runtimeConfig（非 public）
>      → public 的東西會出現在 HTML 的 window.__NUXT__ 裡
>      → 驗證：curl -s https://app/ | grep -oE 'window.__NUXT__.{0,500}'
> ```

```bash
# ★★★ 從另一台機器驗證無法繞過
$ nc -zv 10.0.20.15 3000
nc: connect to 10.0.20.15 port 3000 (tcp) failed: Connection refused   # ★ 正確

# ★ 若能連上 → 立刻修正
$ curl http://10.0.20.15:3000/        # ★★ 若有回應就是設定錯了
```

> [!warning] SSR 的伺服器端請求偽造（SSRF）風險 ★★
> ```
> ★★ SSR 時，Node 會【代替使用者】發出請求
>   → 若讓使用者控制請求的目標 → SSRF
>
> ❌ 危險：
>   const { data } = await useFetch(route.query.url);   // ✗✗✗
>   const img = await $fetch(`/proxy?url=${userInput}`); // ✗✗
>
> ★ 攻擊者可以：
>   · 存取【內網服務】（http://10.0.0.5:8080/admin）
>   · 讀取雲端的 metadata（http://169.254.169.254/）
>   · 掃描內網
>
> ✅ 防護：
>   · ★★ 只允許白名單的網域
>   · 禁止私有 IP 範圍（10./172.16./192.168./127./169.254.）
>   · ★ 不要讓使用者輸入直接進入伺服器端的請求 URL
> ```

```typescript
// server/utils/safeFetch.ts —— ★★ SSRF 防護
const ALLOWED_HOSTS = ['api.example.gov.tw', 'cdn.example.gov.tw'];
const PRIVATE = /^(10\.|127\.|169\.254\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1|fc00:|fe80:)/;

export async function safeFetch(url: string) {
  const u = new URL(url);
  if (!['http:', 'https:'].includes(u.protocol)) throw new Error('協定不允許');
  if (!ALLOWED_HOSTS.includes(u.hostname)) throw new Error('網域不在白名單');
  // ★ 也要檢查解析後的 IP（防 DNS rebinding）
  const { lookup } = await import('node:dns/promises');
  const { address } = await lookup(u.hostname);
  if (PRIVATE.test(address)) throw new Error('目標為私有位址');
  return $fetch(url, { timeout: 5000 });
}
```

---

## 速查表

### ★★★ 必要設定

```javascript
// ecosystem.config.cjs（★ 副檔名是 .cjs）
{
  name: 'nuxt-app',
  script: '/var/www/nuxt-app/current/.output/server/index.mjs',
  exec_mode: 'cluster', instances: 2,
  wait_ready: true,              // ★★★ 零停機必須
  listen_timeout: 10000,
  kill_timeout: 8000,            // ★★ 預設 1600ms 太短
  max_memory_restart: '600M',    // ★★ 防洩漏
  env: {
    NODE_ENV: 'production',
    HOST: '127.0.0.1',           // ★★★ 絕不用 0.0.0.0
    PORT: 3000,
    NODE_EXTRA_CA_CERTS: '/usr/local/share/ca-certificates/internal-ca.crt',
  },
}
```

### ★★★ 優雅關閉（Nitro plugin）

```typescript
nitroApp.hooks.hook('listen', () => {
  if (process.send) process.send('ready');    // ★★★ wait_ready 必須
});
process.on('SIGINT',  () => shutdown());      // ★★ PM2
process.on('SIGTERM', () => shutdown());      // ★ systemd / Docker
```

### ★★★ cluster 四個禁忌

```
① 記憶體中的狀態（Map / 計數器）→ 改用 Redis
② 檔案式 session               → 改用 Redis / JWT
③ 排程會執行 N 次              → NODE_APP_INSTANCE==='0' 或獨立 worker
④ 檔案鎖 / 本機暫存            → 分散式鎖
```

### PM2 操作

```bash
pm2 start ecosystem.config.cjs --env production
pm2 reload nuxt-app                    # ★★★ 零停機
pm2 restart nuxt-app                   # ★ 有中斷，不要用於更新
pm2 save                               # ★★★ 改設定後【一定要】
pm2 startup systemd -u deploy --hp /home/deploy
pm2 install pm2-logrotate              # ★★ 必裝
pm2 logs nuxt-app --err --lines 50
pm2 monit
```

### systemd 關鍵設定

```ini
User=deploy
Environment=HOST=127.0.0.1
KillSignal=SIGTERM
TimeoutStopSec=15
MemoryMax=800M
MemoryDenyWriteExecute=false     # ★★★ V8 JIT 需要（true 會直接掛）
ProtectSystem=strict
ReadWritePaths=/var/log/nuxt-app
```

### ★★★ 三個安全設定

```
① HOST=127.0.0.1    → 否則可繞過 Nginx/TLS/WAF/限流
② User=deploy       → 不用 root
③ 秘密不放 public   → 會出現在 window.__NUXT__
```

### 驗證

```bash
sudo ss -tlnp | grep 3000                    # ★★★ 必須是 127.0.0.1
pm2 describe nuxt-app | grep -E 'status|restarts|memory'
curl -s https://app/ | grep -q '<div id="__nuxt"><'   # ★ SSR 有內容

# ★★ 驗證 reload 真的零停機
while true; do curl -so /dev/null -w '%{http_code} ' https://app/; sleep 0.2; done &
pm2 reload nuxt-app        # ★ 觀察有沒有 502/000
```

### 部署流程

```
① clone + npm ci + npm run build
② ★★ 秘密掃描 + 移除 sourcemap
③ ★★ 煙霧測試（在暫時的埠 3999 上啟動並 curl）
④ ★★★ 原子切換符號連結
⑤ ★★★ pm2 reload + pm2 save
⑥ ★★★ 驗證（HTTP / SSR 內容 / 版本 / 綁定位址）→ 失敗回退
```

---

## 練習題

> [!question]- 練習 1：`pm2 reload` 真的零停機嗎 ★★★
> 1. **不實作 `process.send('ready')`**，設 `wait_ready: true`
> 2. 開持續請求的迴圈，執行 `pm2 reload` → **有 502 嗎？**
> 3. 拿掉 `wait_ready` → 再測
> 4. **實作 ready 訊號 + 優雅關閉**，再測
> 5. 把 `kill_timeout` 設成 100ms，在一個很慢的 API 上測 → **請求被砍了嗎？**
> 6. **記錄每一種組合的中斷次數**

> [!question]- 練習 2：cluster 的狀態陷阱 ★★★
> 1. 寫一個 API：`let count = 0; count++; return count;`
> 2. `instances: 1` → 連續呼叫 10 次 → **數字是什麼？**
> 3. 改 `instances: 4` → 再呼叫 10 次 → **數字呢？**
> 4. 用檔案式 session 做登入，`instances: 4` → **會被登出嗎？**
> 5. 改用 Redis session → 再測
> 6. 加一個 `setInterval` 寫 log，`instances: 4` → **一分鐘寫幾行？**

> [!question]- 練習 3：`HOST` 的安全性 ★★★
> 1. 設 `HOST: '0.0.0.0'` 啟動
> 2. `ss -tlnp | grep 3000` → 看綁定位址
> 3. **從另一台機器** `curl http://伺服器IP:3000/` → **連得到嗎？**
> 4. 比較「經過 Nginx」與「直連 3000」的回應標頭 → **少了哪些？**
> 5. 改成 `127.0.0.1` → 再測
> 6. **列出繞過 Nginx 會失去哪些防護**

> [!question]- 練習 4：systemd 的 `MemoryDenyWriteExecute`
> 1. 寫一個 systemd unit，設 **`MemoryDenyWriteExecute=true`**
> 2. `systemctl start` → **錯誤訊息是什麼？**
> 3. `journalctl -u` 看詳細
> 4. 改成 `false` → 正常了嗎？
> 5. `systemd-analyze security nuxt-app` → **加固評分是多少？**
> 6. 逐一加上其他加固選項，看評分變化

> [!question]- 練習 5：記憶體洩漏
> 1. 故意寫一個洩漏：模組層級 `const leak = []`，每個請求 `leak.push(new Array(10000))`
> 2. 用 `ab` 或 `wrk` 打 10000 個請求
> 3. `pm2 monit` 觀察記憶體 → **上升多快？**
> 4. 設 `max_memory_restart: '300M'` → **會自動重啟嗎？**
> 5. 用 `node --inspect` + Chrome DevTools 取 Heap Snapshot
> 6. **找出洩漏的物件**

---

## 小測驗

Q1. **PM2 與 systemd 各適合什麼情境**？

Q2. **`pm2 reload` 要真的零停機，程式必須做哪兩件事**？

Q3. **`HOST` 為什麼一定要設 `127.0.0.1`**？

Q4. **cluster 模式的四個禁忌是什麼**？

Q5. **PM2 送什麼訊號？systemd 送什麼**？

Q6. **`pm2 save` 的作用與陷阱**？

Q7. **`MemoryDenyWriteExecute=true` 會造成什麼問題**？

Q8. **為什麼 `ecosystem.config` 要用 `.cjs` 副檔名**？

Q9. **SSR 為什麼特別容易記憶體洩漏？怎麼防護**？

Q10. **什麼是 SSR 的 SSRF 風險？怎麼防**？

> [!question]- 測驗答案
> **Q1.** **PM2 適合**：需要 **cluster 多程序**提升吞吐、
> 需要**零停機重載**（`pm2 reload`）、團隊熟悉 PM2 操作。
> **systemd 適合**：只需要**單一實例**、
> 要用 **systemd 的安全加固**（`ProtectSystem=strict`、`LoadCredential`、
> `RestrictAddressFamilies` 等，`systemd-analyze security` 可評分）、
> 希望**日誌統一到 journald**、不想多一個 PM2 daemon。
> **推薦的混合方案**：**用 systemd 管理 PM2**
> （`pm2 startup systemd` 產生的 unit）——
> systemd 保證開機自啟與程序監管，PM2 提供 cluster 與零停機重載。
>
> **Q2.** ①**在「真的能接受請求後」送出 `process.send('ready')`**
> （並在 ecosystem 設 `wait_ready: true`）——
> 否則 PM2 會**太早**把流量切到新實例，
> 請求打到還沒 listen 完成的程序 → **502**；
> ②**處理 `SIGINT` 做優雅關閉** ——
> 停止接受新連線、**等待進行中的請求完成**、關閉資料庫連線池、才 `process.exit(0)`；
> 同時要把 **`kill_timeout` 調大**（預設 **1600ms** 太短，建議 8000）。
> 沒有第二點的話，`reload` 時**正在處理的請求會被中途砍掉**，
> 使用者看到連線重設。
>
> **Q3.** 因為 **`HOST=0.0.0.0`（Nuxt 的預設值）會讓 Node 服務綁定在所有網路介面上** ——
> 任何人可以直接 `http://伺服器IP:3000/` **繞過 Nginx**，
> 因而繞過：
> **TLS 加密**、**ModSecurity WAF**、**限流（`limit_req`）**、
> **IP 白名單**、**所有安全標頭**（HSTS、CSP、X-Frame-Options）、
> **存取日誌**。
> **設 `HOST=127.0.0.1` 後只有本機能連**，
> 流量必須經過 Nginx 才進得來。
> **驗證**：`ss -tlnp | grep 3000` 應該顯示 `127.0.0.1:3000`；
> 從另一台機器 `nc -zv 伺服器IP 3000` 應該 `Connection refused`。
>
> **Q4.** cluster 是**多個獨立的 Node 程序，彼此不共享記憶體**，所以：
> ①**記憶體中的狀態不能用** —— `const cache = new Map()`、
> 計數器等，每個程序有自己的一份 → **改用 Redis**；
> ②**檔案式 session 不能用** —— 同一個使用者的請求可能打到不同程序，
> **一下登入一下登出** → 改用 Redis / 資料庫 / JWT；
> ③**排程會執行 N 次** —— `setInterval` 在每個實例都會跑，
> 2 個實例就寄 2 封信 → 用 `process.env.NODE_APP_INSTANCE === '0'` 判斷，
> **更好的做法是把排程搬到獨立的 worker 程序**；
> ④**檔案鎖／本機暫存不可靠** → 用分散式鎖。
>
> **Q5.** **PM2 送 `SIGINT`**（可用 `kill_signal: 'SIGTERM'` 改變）；
> **systemd、Docker、Kubernetes 都送 `SIGTERM`**。
> **所以兩個都要處理**：
> ```javascript
> process.on('SIGINT',  () => shutdown('SIGINT'));
> process.on('SIGTERM', () => shutdown('SIGTERM'));
> ```
> 只處理其中一個的話，換管理方式（PM2 → systemd，或搬進容器）時，
> 優雅關閉就失效了，**而且不會有任何錯誤訊息** ——
> 只會看到「部署時偶爾有請求失敗」這種難以追查的症狀。
> 建議同時處理 `uncaughtException` 與 `unhandledRejection` 並記錄。
>
> **Q6.** **作用**：`pm2 save` 把**目前正在跑的程序清單**存到 `~/.pm2/dump.pm2`，
> 開機時 `pm2 resurrect`（由 `pm2 startup` 產生的 systemd unit 呼叫）會依此還原。
> **三個陷阱**：
> ①**存的是「當下的狀態」** —— 如果當下有測試用的程序在跑，也會被存進去；
> ②**如果當下 app 是停止的，開機後也不會啟動**；
> ③**★★ 改了 `ecosystem.config.cjs` 但沒有再 `pm2 save`** →
> **開機後跑的是舊設定**（這個最難察覺，因為平常 reload 是對的，
> 只有重開機後才會出問題）。
> **正確流程**：每次 `pm2 reload ecosystem.config.cjs --update-env` 之後
> **一定要 `pm2 save`**。
> **驗證**：`cat ~/.pm2/dump.pm2 | jq '.[].name, .[].env.PORT'`
>
> **Q7.** **Node.js 會直接無法啟動**（SIGSEGV 或 `Cannot allocate memory`）。
> 原因是 **V8 引擎的 JIT 編譯器需要「可寫且可執行」的記憶體頁** ——
> 它在執行期間動態產生機器碼並執行。
> `MemoryDenyWriteExecute=true` 這個加固選項會禁止建立 W+X 的記憶體對映，
> 直接讓 V8 無法運作。
> **必須明確設 `MemoryDenyWriteExecute=false`**，
> 即使其他加固選項都開著。
> **這是 Node.js 服務做 systemd 加固時最常見的坑** ——
> 因為 `systemd-analyze security` 會建議開啟這個選項來提高評分。
> 同類的還有 `RestrictAddressFamilies` 要記得包含 `AF_UNIX`。
>
> **Q8.** 因為 **PM2 是用 CommonJS 的 `require()` 載入 ecosystem 設定檔的**，
> 而如果專案的 `package.json` 有 **`"type": "module"`**（Nuxt 3 專案通常有），
> Node 會把 `.js` 檔案**當成 ES module** 解析 →
> `module.exports = {...}` 這種 CommonJS 語法就會失敗
> （`ReferenceError: module is not defined in ES module scope`）。
> **改用 `.cjs` 副檔名**可以**明確告訴 Node 這是 CommonJS**，
> 不受 `"type": "module"` 影響。
> 同樣的道理適用於其他工具的設定檔
> （`tailwind.config.cjs`、`postcss.config.cjs`）。
>
> **Q9.** 因為 **SSR 的每個請求都在同一個長駐程序裡建立完整的元件樹**，
> 任何沒有正確釋放的參照都會累積。
> **常見來源**：
> ①**模組層級的 `Map` / 陣列不斷累積**（沒有上限的快取）；
> ②**全域事件監聽器沒有移除**；
> ③**在 `setup` 裡註冊 `setInterval` 但沒有在 `onScopeDispose` 清除**；
> ④第三方套件的已知洩漏；
> ⑤**閉包意外持有大物件的參照**。
> **四層防護**：
> ①**`max_memory_restart: '600M'`**（PM2）或 `MemoryMax`（systemd）——
> 超過就自動重啟，避免 OOM 拖垮整台機器；
> ②**定期監控趨勢**（不只看當下的值，要看是否持續上升且不回落）；
> ③用 **`node --inspect` + Chrome DevTools 的 Heap Snapshot** 定位；
> ④**cluster 多實例** —— 單一實例洩漏重啟時，其他實例還在服務。
>
> **Q10.** **SSRF（Server-Side Request Forgery）** ——
> SSR 時 **Node 會「代替使用者」發出 HTTP 請求**，
> 如果**讓使用者控制請求的目標網址**，攻擊者就能利用你的伺服器去存取：
> **內網服務**（`http://10.0.0.5:8080/admin`，這些通常沒有對外的認證）、
> **雲端 metadata 端點**（`http://169.254.169.254/` —— 可以拿到 IAM 憑證）、
> **掃描內網拓撲**。
> **危險寫法**：`await useFetch(route.query.url)`、
> `$fetch(`/proxy?url=${userInput}`)`。
> **防護**：
> ①**網域白名單**（只允許明確列出的 host）；
> ②**禁止私有 IP 範圍**（`10.`、`127.`、`169.254.`、`192.168.`、`172.16-31.`、`::1`、`fc00:`）；
> ③**★ 檢查「DNS 解析後的 IP」而不只是網域字串**（防 DNS rebinding）；
> ④設定 timeout 與不跟隨轉址（避免用 302 繞過白名單）。

---

## 延伸閱讀

- [[03-Nuxt-Nginx反向代理與快取]] — Nginx 層的設定
- [[04-Nuxt-Docker部署]] — 容器化部署
- [[07-Nuxt-Laravel-SSR完整部署實戰]] — 與 Laravel 整合
- [[04-PM2-進階設定與部署]] — PM2 的進階功能
- [[05-PM2與systemd整合]] — 兩者的整合方式
- [[01-Nuxt-渲染模式與部署選型]] — 確認是否真的需要 SSR
