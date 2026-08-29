---
title: "Nuxt Docker 部署"
desc: "SSR 容器化、執行時環境變數、健康檢查、優雅關閉與 Compose 全套"
aliases: [Nuxt Docker, SSR容器, node-server preset, dumb-init, tini]
tags: [群組/實務案例, 主題/部署, 主題/Nuxt, 主題/容器]
category: 專案部署實戰
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[130-01-03-02-guide-Nuxt-SSR與PM2部署]]", "[[130-01-02-03-guide-Vue-Docker部署]]"]
updated: 2026-08-28
---

# Nuxt Docker 部署

> [!abstract] 這篇你會學到
> - **SSR 容器與 SPA 容器的根本差異**
> - **多階段建置**（★ 只複製 `.output`）
> - **★★★ PID 1 問題**與 `dumb-init` / `tini`
> - **執行時環境變數**（`runtimeConfig` 天然支援）
> - **健康檢查**與**優雅關閉**
> - **非 root 容器**與加固
> - Compose 全套與**多副本零停機**

## 前置知識

- [[130-01-03-02-guide-Nuxt-SSR與PM2部署]] — SSR 的程序管理概念
- [[130-01-02-03-guide-Vue-Docker部署]] — 靜態 SPA 的容器化
- [[050-02-01-03-guide-Docker-Dockerfile撰寫]] — Dockerfile 語法

---

## SSR 容器 vs SPA 容器 ★★

| | **SPA 容器** | **★★ SSR 容器** |
| --- | --- | --- |
| 基底映像 | `nginx:alpine` | **`node:22-alpine`** |
| 執行的東西 | Nginx 送靜態檔 | **Node 程序（長駐）** |
| 映像大小 | ~50MB | **~150MB** |
| 記憶體 | ~10MB | **★ 80～300MB** |
| **環境變數** | 需要 `env.js` 技巧 | **★★ `runtimeConfig` 天然支援** |
| **優雅關閉** | 不需要 | **★★★ 必須** |
| **PID 1 問題** | Nginx 有處理 | **★★★ 必須處理** |
| 健康檢查 | 靜態端點 | **★ 應用層端點** |
| 擴充 | 隨便加 | ★ 要注意狀態共享 |

> [!tip] Nuxt SSR 容器化的優勢 ★★
> ```
> ★★ runtimeConfig 天然支援執行時環境變數
>   → 不需要 Vue SPA 的 env.js 技巧
>   → docker run -e NUXT_PUBLIC_API_BASE=... 直接生效
>     → ★★★ 真正的「build once, deploy anywhere」
>
> ★ .output/server/node_modules 已經打包好
>   → 最終映像不需要跑 npm install
>   → 也不需要保留專案的 node_modules
> ```

---

## Dockerfile ★★★

```dockerfile
# ═══════════════════════════════════════════════════════
# Dockerfile —— Nuxt 3 SSR
# ═══════════════════════════════════════════════════════

# ─────────── ★ 階段 1：相依 ───────────
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ─────────── ★ 階段 2：建置 ───────────
FROM node:22-alpine AS build
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG APP_VERSION=dev
ENV NUXT_TELEMETRY_DISABLED=1 \
    NODE_OPTIONS=--max-old-space-size=4096 \
    NUXT_PUBLIC_APP_VERSION=$APP_VERSION

RUN npm run build && \
    # ★★ 移除 sourcemap
    find .output/public -name '*.map' -delete 2>/dev/null || true && \
    # ★ 預壓縮靜態資源
    find .output/public -type f \( -name '*.js' -o -name '*.css' \
      -o -name '*.svg' -o -name '*.json' \) -size +1k \
      -exec gzip -9 -k {} \; 2>/dev/null || true

# ★★ 建置後驗證秘密沒有洩漏
RUN if grep -rlE 'apiSecret|dbPassword|NUXT_API_SECRET|sk_live|-----BEGIN' \
      .output/public/ 2>/dev/null; then \
      echo "✗✗✗ 秘密洩漏到客戶端產物"; exit 1; \
    fi

# ─────────── ★★ 階段 3：執行 ───────────
FROM node:22-alpine

# ★★★ 處理 PID 1 問題（訊號轉發與殭屍程序回收）
RUN apk add --no-cache dumb-init curl ca-certificates && \
    rm -rf /var/cache/apk/*

# ★★ 內部 CA（SSR 呼叫內部 HTTPS API 時需要）
# COPY pki/root-ca.crt /usr/local/share/ca-certificates/internal-ca.crt
# RUN update-ca-certificates
# ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/internal-ca.crt

WORKDIR /app

# ★★★ 只複製 .output（自給自足，不需要 node_modules）
COPY --from=build --chown=node:node /app/.output ./.output

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000 \
    TZ=Asia/Taipei \
    NUXT_TELEMETRY_DISABLED=1 \
    NODE_OPTIONS=--max-old-space-size=512

# ★★ 非 root
USER node

EXPOSE 3000

# ★ 健康檢查
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:3000/healthz || exit 1

# ★★★ dumb-init 當 PID 1，正確轉發訊號
ENTRYPOINT ["dumb-init", "--"]
CMD ["node", ".output/server/index.mjs"]

ARG APP_VERSION=dev
LABEL org.opencontainers.image.version="$APP_VERSION" \
      org.opencontainers.image.source="https://github.com/Information-Study/nuxt-frontend"
```

> [!danger] 容器裡的 `HOST=0.0.0.0` 是正確的 ★★
> ```
> ★★ 這與「裸機部署要用 127.0.0.1」的建議【不衝突】
>
> 裸機：HOST=127.0.0.1
>   → 因為 Node 與 Nginx 在【同一台機器】上
>     → 綁 0.0.0.0 會讓外部可以直接連 3000 埠繞過 Nginx
>
> 容器：HOST=0.0.0.0
>   → ★ 容器有自己的網路命名空間
>     → 綁 127.0.0.1 的話【連容器外都連不進來】（連 Nginx 容器也連不到）
>   → ★★ 隔離靠的是【不要 publish 埠】：
>     ❌ ports: - "3000:3000"      ← 暴露到宿主機
>     ✅ expose: - "3000"          ← 只有同一個 Docker 網路內看得到
>       （或什麼都不寫，Compose 內部網路本來就通）
>
> ★★★ 檢查：docker compose ps 看 PORTS 欄位
>    → SSR 容器【不應該】有 0.0.0.0:3000->3000/tcp
> ```

### ★★★ PID 1 問題

> [!danger] 沒有 init 程序，優雅關閉會失效 ★★★
> ```
> ★★ 在容器中，CMD 指定的程序會成為【PID 1】
>
> PID 1 在 Linux 有兩個特殊責任：
>   ① ★★ 回收【孤兒殭屍程序】
>   ② ★★★ 【預設忽略】所有沒有明確註冊 handler 的訊號
>
> 問題：
>   · Node 若沒註冊 SIGTERM handler → ★★★ docker stop 【完全無效】
>     → 等 10 秒後 Docker 送 SIGKILL 強制殺掉
>       → ★★ 正在處理的請求全部被砍
>   · 子程序（若有 spawn）變成殭屍不會被回收
>
> ★★★ 解法：用 dumb-init 或 tini 當 PID 1
>   ENTRYPOINT ["dumb-init", "--"]
>   CMD ["node", ".output/server/index.mjs"]
>   → dumb-init 是 PID 1，正確地把訊號【轉發】給 Node
>
> ★ 或用 docker run --init（★ 用 Docker 內建的 tini）
>   compose: init: true
> ```

```bash
# ★★ 驗證訊號有被正確處理
$ docker run -d --name t nuxt-app:latest
$ time docker stop t
real  0m1.234s              # ★ 快速停止 = 訊號有效

# ★ 若花了 10 秒 → 訊號沒被處理（等到 SIGKILL）
real  0m10.412s             # ✗✗

# ★ 看容器內的程序樹
$ docker exec t ps -ef
PID   USER     COMMAND
    1 node     dumb-init -- node .output/server/index.mjs    # ★★ PID 1 是 dumb-init
    7 node     node .output/server/index.mjs
```

```yaml
# ★ Compose 用內建的 init（不用改 Dockerfile）
services:
  nuxt:
    image: nuxt-app:latest
    init: true                 # ★★ Docker 會注入 tini 當 PID 1
```

### 優雅關閉（容器版）

```typescript
// server/plugins/graceful.ts
export default defineNitroPlugin((nitroApp) => {
  let shuttingDown = false;
  let active = 0;

  nitroApp.hooks.hook('request',       () => { active++; });
  nitroApp.hooks.hook('afterResponse', () => { active--; });

  nitroApp.hooks.hook('listen', () => {
    console.log('[graceful] 服務已就緒');
    if (process.send) process.send('ready');    // ★ PM2 用（容器裡沒作用但無害）
  });

  async function shutdown(sig: string) {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(`[graceful] ${sig} → 開始關閉（進行中 ${active} 個請求）`);

    const deadline = Date.now() + 8000;
    while (active > 0 && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 200));
    }
    if (active > 0) console.warn(`[graceful] 逾時，仍有 ${active} 個請求`);

    try { await nitroApp.hooks.callHook('close'); } catch {}
    console.log('[graceful] 完成');
    process.exit(0);
  }

  // ★★★ 容器主要送 SIGTERM
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT',  () => shutdown('SIGINT'));
});
```

```typescript
// server/routes/healthz.get.ts —— ★ 健康檢查端點
export default defineEventHandler(() => {
  return {
    status: 'ok',
    version: useRuntimeConfig().public.appVersion,
    uptime: Math.floor(process.uptime()),
    memory: Math.round(process.memoryUsage().rss / 1048576),
  };
});
```

```
# .dockerignore
node_modules
.output
.nuxt
.git
.github
.env
.env.*
!.env.example
tests
*.md
Dockerfile*
docker-compose*.yml
.vscode
coverage
```

---

## 執行時環境變數 ★★

```bash
# ═══════ ★★★ Nuxt 的優勢：直接用環境變數，不需要任何技巧 ═══════

$ docker run -d -p 3000:3000 \
    -e NUXT_PUBLIC_API_BASE=https://api-dev.example.gov.tw \
    -e NUXT_PUBLIC_APP_ENV=development \
    -e NUXT_API_SECRET=dev-secret \
    nuxt-app:v1.2.3

$ docker run -d -p 3001:3000 \
    -e NUXT_PUBLIC_API_BASE=https://api.example.gov.tw \
    -e NUXT_PUBLIC_APP_ENV=production \
    -e NUXT_API_SECRET=prod-secret \
    nuxt-app:v1.2.3           # ★★★ 同一個 tag！

# ★ 驗證
$ curl -s http://localhost:3000/ | grep -oE '"apiBase":"[^"]*"'
"apiBase":"https://api-dev.example.gov.tw"
```

> [!danger] 秘密不要用 `-e` 傳 ★★
> ```
> ❌ docker run -e NUXT_API_SECRET=super-secret ...
>   → ★★ docker inspect 看得到
>   → ps aux 也看得到（★ 執行的當下）
>   → ★ shell history 裡也有
>
> ✅ 三種較好的做法：
>   ① env_file（★ 檔案權限 600）
>        docker run --env-file ./secrets/nuxt.env ...
>   ② ★★ Docker secrets（Swarm / Compose）
>        secrets: [api_secret]
>        → 掛載到 /run/secrets/api_secret
>   ③ ★ 從外部的秘密管理系統注入（Vault、AWS Secrets Manager）
>
> ★★ 驗證：
>   docker inspect nuxt | jq '.[0].Config.Env'
>   → 不應該看到明文的秘密
> ```

```yaml
# ★★ Compose 的 secrets
services:
  nuxt:
    image: nuxt-app:v1.2.3
    environment:
      # ★ 公開設定用 environment
      NUXT_PUBLIC_API_BASE: /api
      NUXT_PUBLIC_APP_ENV: production
    secrets:
      - api_secret
    # ★★ Nuxt 讀檔案版的環境變數（需要 entrypoint 處理，或應用自己讀）
    entrypoint: >
      sh -c 'export NUXT_API_SECRET=$$(cat /run/secrets/api_secret);
             exec dumb-init -- node .output/server/index.mjs'

secrets:
  api_secret:
    file: ./secrets/api_secret.txt
```

```typescript
// ★ 或讓應用直接讀檔案（更乾淨）
// server/plugins/secrets.ts
import { readFileSync, existsSync } from 'node:fs';

export default defineNitroPlugin(() => {
  // ★★ 支援 _FILE 後綴的慣例（Docker 生態的標準做法）
  for (const [key, val] of Object.entries(process.env)) {
    if (key.endsWith('_FILE') && val && existsSync(val)) {
      const target = key.slice(0, -5);
      process.env[target] = readFileSync(val, 'utf8').trim();
      delete process.env[key];
    }
  }
});
```

```yaml
# ★★ 搭配 _FILE 慣例
services:
  nuxt:
    environment:
      NUXT_API_SECRET_FILE: /run/secrets/api_secret     # ★ 應用自己讀
    secrets: [api_secret]
```

---

## 完整實戰範例：Compose 全套

```yaml
# docker-compose.yml —— Nuxt SSR + Laravel API + MySQL + Redis
name: nuxt-lxmp

services:
  # ═══════ ★ 反向代理（TLS + 快取）═══════
  proxy:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./docker/proxy.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/ssl/certs/app-fullchain.crt:/etc/nginx/ssl/fullchain.crt:ro
      - /etc/ssl/private/app.key:/etc/nginx/ssl/app.key:ro
      # ★★ 靜態資源直送：把 Nuxt 的 public 掛給 Nginx
      - nuxt-public:/usr/share/nginx/nuxt-public:ro
      - nginx-cache:/var/cache/nginx
    depends_on:
      nuxt: { condition: service_healthy }
      api:  { condition: service_healthy }
    restart: unless-stopped
    networks: [web]

  # ═══════ ★★ Nuxt SSR ═══════
  nuxt:
    image: ghcr.io/information-study/nuxt-frontend:${TAG:-latest}
    build:
      context: .
      args: { APP_VERSION: "${TAG:-dev}" }
    # ★★★ 不要 publish 埠（只在內部網路可見）
    expose: ["3000"]
    environment:
      NODE_ENV: production
      HOST: 0.0.0.0                    # ★ 容器內正確
      PORT: 3000
      TZ: Asia/Taipei
      # ★ 執行時設定
      NUXT_PUBLIC_API_BASE: /api
      NUXT_PUBLIC_APP_ENV: production
      NUXT_PUBLIC_APP_VERSION: ${TAG:-dev}
      NUXT_INTERNAL_API_BASE: http://api:9000
      # ★★ 秘密用 _FILE 慣例
      NUXT_API_SECRET_FILE: /run/secrets/nuxt_api_secret
      NODE_OPTIONS: --max-old-space-size=512
    secrets: [nuxt_api_secret]
    volumes:
      # ★★ 把 public 產物分享給 proxy（靜態直送）
      - nuxt-public:/app/.output/public:ro
    init: true                          # ★★★ PID 1（★ 也可以靠 dumb-init）
    stop_grace_period: 20s              # ★★ 給優雅關閉足夠的時間
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:3000/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
    deploy:
      resources:
        limits:   { memory: 800M, cpus: '1.5' }
        reservations: { memory: 256M }
    # ★★ 加固
    user: "1000:1000"                   # node 使用者
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    read_only: true
    tmpfs:
      - /tmp:size=64M
    restart: unless-stopped
    networks: [web, data]
    logging:
      driver: json-file
      options: { max-size: "20m", max-file: "5" }

  # ═══════ Laravel API ═══════
  api:
    image: ghcr.io/information-study/laravel-api:${TAG:-latest}
    expose: ["9000"]
    env_file: [./secrets/api.env]
    environment:
      APP_ENV: production
      APP_DEBUG: "false"                # ★★★
      DB_HOST: mysql
      REDIS_HOST: redis
    volumes:
      - api-storage:/var/www/html/storage
    depends_on:
      mysql: { condition: service_healthy }
      redis: { condition: service_started }
    healthcheck:
      test: ["CMD-SHELL", "php -r \"exit(@file_get_contents('http://127.0.0.1:9000/health')?0:1);\""]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 40s
    restart: unless-stopped
    networks: [web, data]

  # ═══════ MySQL ═══════
  mysql:
    image: mysql:8.4
    env_file: [./secrets/mysql.env]
    command: >
      --character-set-server=utf8mb4
      --collation-server=utf8mb4_unicode_ci
      --innodb-buffer-pool-size=1G
    volumes: [mysql-data:/var/lib/mysql]
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 40s
    restart: unless-stopped
    networks: [data]                    # ★★ 只在 internal 網路

  # ═══════ Redis ═══════
  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes",
              "--maxmemory", "512mb", "--maxmemory-policy", "allkeys-lru"]
    volumes: [redis-data:/data]
    restart: unless-stopped
    networks: [data]

networks:
  web:  {}
  data: { internal: true }              # ★★★ 無法連外網

volumes:
  mysql-data:
  redis-data:
  api-storage:
  nginx-cache:
  nuxt-public:                          # ★ 分享 Nuxt 的靜態產物

secrets:
  nuxt_api_secret:
    file: ./secrets/nuxt_api_secret.txt
```

```nginx
# docker/proxy.conf
proxy_cache_path /var/cache/nginx/nuxt levels=1:2
    keys_zone=nuxt_cache:50m max_size=1g inactive=10m use_temp_path=off;

upstream nuxt_up { server nuxt:3000; keepalive 32; }
upstream api_up  { server api:9000;  keepalive 16; }

map $http_cookie $skip_cookie { default 0; "~*(nuxt-session|laravel_session)=" 1; }
map $request_method $skip_method { default 1; GET 0; HEAD 0; }
map $request_uri $skip_uri { default 0; "~^/(api|admin|account|auth)" 1; }
map "$skip_cookie$skip_method$skip_uri" $skip_cache { default 1; "000" 0; }

server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name app.example.gov.tw;

    ssl_certificate     /etc/nginx/ssl/fullchain.crt;
    ssl_certificate_key /etc/nginx/ssl/app.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_tickets off;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;

    client_max_body_size 20m;
    gzip on; gzip_static on; gzip_vary on;
    gzip_types text/css application/json application/javascript image/svg+xml;

    # ═══ ★★ 靜態資源直送（從共享 volume 讀）═══
    location ^~ /_nuxt/ {
        alias /usr/share/nginx/nuxt-public/_nuxt/;
        try_files $uri =404;
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
        add_header X-Content-Type-Options "nosniff" always;
        access_log off;
        gzip_static on;
    }

    # ═══ API ═══
    location ^~ /api/ {
        proxy_pass http://api_up;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache off;
    }

    # ═══ ★★ Nuxt SSR（微快取）═══
    location / {
        proxy_pass http://nuxt_up;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_cache nuxt_cache;
        proxy_cache_key "$scheme$request_method$host$request_uri";
        proxy_cache_valid 200 301 302 5s;
        proxy_cache_bypass $skip_cache;
        proxy_no_cache     $skip_cache;
        proxy_cache_lock on;
        proxy_cache_use_stale error timeout updating http_502 http_503 http_504;
        proxy_cache_background_update on;

        add_header X-Cache-Status $upstream_cache_status always;
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
        add_header X-Content-Type-Options "nosniff" always;
    }
}
```

```bash
# ═══ 秘密 ═══
$ mkdir -p secrets && chmod 700 secrets
$ openssl rand -base64 32 > secrets/nuxt_api_secret.txt
$ chmod 600 secrets/*
$ echo "secrets/" >> .gitignore

# ═══ 啟動 ═══
$ TAG=v1.2.3 docker compose up -d

# ═══ ★★ 驗證 ═══
$ docker compose ps
NAME              STATUS                    PORTS
nuxt-lxmp-nuxt-1  Up 2 minutes (healthy)                        # ★★ 沒有對外埠
nuxt-lxmp-proxy-1 Up 2 minutes    0.0.0.0:80->80, 0.0.0.0:443->443
nuxt-lxmp-mysql-1 Up 2 minutes (healthy)                        # ★★ 沒有對外埠

$ curl -sI https://app.example.gov.tw/ | grep -iE 'HTTP|x-cache'
$ curl -s  https://app.example.gov.tw/healthz | jq
{
  "status": "ok",
  "version": "v1.2.3",
  "uptime": 142,
  "memory": 96
}
```

### ★★ 多副本零停機更新

```yaml
# ★ Compose 的 rolling update（★ 需要多副本）
services:
  nuxt:
    deploy:
      replicas: 2
      update_config:
        parallelism: 1              # ★★ 一次只更新一個
        order: start-first          # ★★★ 先啟動新的再停舊的
        delay: 10s
        failure_action: rollback
      rollback_config:
        parallelism: 1
        order: stop-first
```

```bash
# ★★ Compose（非 Swarm）的零停機更新
$ TAG=v1.2.4 docker compose up -d --no-deps nuxt
# ★ Compose v2 會：
#   ① 啟動新容器
#   ② 等 healthcheck 通過
#   ③ 才停掉舊的
# ★★ 但預設是 stop-first —— 用 --wait 確保新的先健康

# ★★★ 更可靠的做法：明確的藍綠切換
$ sudo tee /usr/local/bin/deploy-nuxt-docker >/dev/null <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
TAG="${1:?用法: deploy-nuxt-docker <tag>}"
COMPOSE="docker compose -f /opt/app/docker-compose.yml"
SITE=https://app.example.gov.tw

c(){ echo -e "\033[36m[$(date +%T)]\033[0m $*"; }

c "═══ 部署 $TAG ═══"

# ══ 【1】拉取映像 ══
c "【1】拉取映像"
TAG="$TAG" $COMPOSE pull nuxt 2>&1 | tail -3 | sed 's/^/    /'

# ══ 【2】★★ 先在暫時的容器上煙霧測試 ══
c "【2】★★ 煙霧測試"
docker run --rm -d --name nuxt-smoke \
  --network "$($COMPOSE ps --format json nuxt | jq -r '.[0].Networks' | cut -d, -f1)" \
  -e NODE_ENV=production -e HOST=0.0.0.0 -e PORT=3000 \
  "ghcr.io/information-study/nuxt-frontend:$TAG" >/dev/null
trap 'docker rm -f nuxt-smoke 2>/dev/null || true' EXIT

OK=0
for i in $(seq 1 30); do
    docker exec nuxt-smoke curl -fsS http://127.0.0.1:3000/healthz >/dev/null 2>&1 && { OK=1; break; }
    sleep 1
done
[ "$OK" = 1 ] || { docker logs nuxt-smoke | tail -30; echo "✗✗ 新映像起不來"; exit 1; }
c "    ✓ 通過"
docker rm -f nuxt-smoke >/dev/null
trap - EXIT

# ══ 【3】★★★ 更新（start-first）══
c "【3】更新"
PREV_TAG=$($COMPOSE ps --format json nuxt | jq -r '.[0].Image' | sed 's/.*://')
TAG="$TAG" $COMPOSE up -d --no-deps --wait --wait-timeout 60 nuxt 2>&1 | tail -5 | sed 's/^/    /'

# ══ 【4】★★ 清 proxy 快取 ══
c "【4】清快取"
$COMPOSE exec -T proxy sh -c 'find /var/cache/nginx -mindepth 1 -type f -delete' || true
$COMPOSE exec -T proxy nginx -s reload

# ══ 【5】★★★ 驗證 ══
c "【5】驗證"
sleep 3
FAIL=0
v(){ printf '    %-38s ' "$1"; if eval "$2" >/dev/null 2>&1; then echo "✓"; else echo "✗"; FAIL=1; fi; }
v "首頁 200"        "[ \"\$(curl -so /dev/null -w '%{http_code}' --max-time 15 $SITE/)\" = 200 ]"
v "★ SSR 有內容"     "curl -s $SITE/ | grep -q '<div id=\"__nuxt\"><'"
v "版本正確"        "curl -s $SITE/healthz | grep -q '$TAG'"
v "★★ 未暴露 3000"   "! docker compose ps --format json nuxt | grep -q '0.0.0.0:3000'"
v "健康"            "[ \"\$($COMPOSE ps --format json nuxt | jq -r '.[0].Health')\" = healthy ]"

if [ "$FAIL" != 0 ]; then
    echo -e "\033[31m    ✗✗ 驗證失敗 —— 回退到 $PREV_TAG\033[0m"
    $COMPOSE logs --tail=40 nuxt | sed 's/^/    /'
    TAG="$PREV_TAG" $COMPOSE up -d --no-deps --wait nuxt
    exit 1
fi

c "═══ ✓ 完成：$TAG ═══"
SCRIPT
$ sudo chmod +x /usr/local/bin/deploy-nuxt-docker
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`docker stop` 要等 10 秒** ★★★ | PID 1 沒轉發訊號 | `dumb-init` / `tini` / `init: true` |
| **停止時請求被砍** ★★ | 沒實作優雅關閉 | Nitro plugin 處理 SIGTERM + `stop_grace_period` |
| **容器內連不到自己** ★★ | `HOST=127.0.0.1` | 容器內要 **`0.0.0.0`** |
| **3000 埠暴露到宿主機** ★★★ | 用了 `ports:` | 改用 `expose:` 或不寫 |
| **秘密在 `docker inspect` 看得到** ★★ | 用 `-e` 傳 | `env_file` / secrets / `_FILE` 慣例 |
| **映像很大（>500MB）** ★★ | 複製了 `node_modules` | **只複製 `.output`** |
| `Cannot find module` | 只複製了 `.output/server` | 複製整個 `.output` |
| **靜態資源走 Node** ★★ | proxy 沒設直送 | 共享 volume + `alias` |
| **健康檢查一直失敗** ★ | 沒有 `/healthz` 端點 | 加 `server/routes/healthz.get.ts` |
| `curl: not found`（healthcheck） | alpine 沒裝 curl | `apk add --no-cache curl` 或用 `wget` |
| **記憶體被 OOM kill** ★★ | 沒設 `NODE_OPTIONS` | `--max-old-space-size` < 容器記憶體上限 |
| `read_only` 後起不來 | Node 要寫暫存 | `tmpfs: [/tmp]` |
| **更新時有停機** ★★ | `stop-first` | `--wait` 或 `order: start-first` |

### 排查

```bash
# 【1】★★★ PID 1 與訊號
$ docker exec nuxt-lxmp-nuxt-1 ps -ef
PID  USER  COMMAND
  1  node  /usr/bin/dumb-init -- node .output/server/index.mjs    # ★★ 正確
  7  node  node .output/server/index.mjs

$ time docker stop nuxt-lxmp-nuxt-1
real 0m1.2s                          # ★ 快 = 訊號有效

# 【2】★★ 埠有沒有誤暴露
$ docker compose ps --format 'table {{.Name}}\t{{.Ports}}'
$ sudo ss -tlnp | grep 3000          # ★★ 宿主機上不應該有

# 【3】★★ 秘密
$ docker inspect nuxt-lxmp-nuxt-1 | jq '.[0].Config.Env'
# ★ 不應該有明文秘密
$ docker exec nuxt-lxmp-nuxt-1 ls -la /run/secrets/

# 【4】健康檢查
$ docker inspect nuxt-lxmp-nuxt-1 | jq '.[0].State.Health'
$ docker exec nuxt-lxmp-nuxt-1 curl -sS http://127.0.0.1:3000/healthz

# 【5】記憶體
$ docker stats --no-stream
$ docker exec nuxt-lxmp-nuxt-1 sh -c 'cat /sys/fs/cgroup/memory.max 2>/dev/null || \
    cat /sys/fs/cgroup/memory/memory.limit_in_bytes'

# 【6】日誌
$ docker compose logs --tail=100 -f nuxt
$ docker compose logs nuxt | grep -i graceful

# 【7】網路
$ docker compose exec proxy wget -qO- http://nuxt:3000/healthz
$ docker network inspect nuxt-lxmp_data | jq '.[0].Internal'
true                                 # ★★ internal 生效

# 【8】映像分析
$ docker images | grep nuxt
$ dive ghcr.io/information-study/nuxt-frontend:v1.2.3
$ trivy image --severity HIGH,CRITICAL ghcr.io/information-study/nuxt-frontend:v1.2.3
```

---

## 安全性注意事項

> [!danger] SSR 容器的五條紅線 ★★★
> ```
> ① ★★★ 不要 publish SSR 的埠
>      ❌ ports: - "3000:3000"
>      ✅ expose: - "3000"（或什麼都不寫）
>      → 否則可繞過 proxy 的 TLS / WAF / 快取 / 限流
>
> ② ★★★ 必須有 init 程序（dumb-init / tini / init: true）
>      → 否則 docker stop 無效，請求被強制中斷
>
> ③ ★★ 秘密不要用 -e 或寫在 Compose 的 environment
>      → docker inspect 看得到
>      → 用 secrets 或 env_file（600 權限）
>
> ④ ★★ 非 root 執行
>      → USER node（node:alpine 內建 node 使用者，UID 1000）
>
> ⑤ ★★ 不要 COPY .env 或私鑰進映像
>      → .dockerignore 要排除
>      → 憑證用 volume 掛載
> ```

```bash
# ★★★ 上線前的容器安全檢查
$ sudo tee /usr/local/bin/check-container-security >/dev/null <<'EOF'
#!/usr/bin/env bash
SVC="${1:-nuxt}"
COMPOSE="docker compose"
FAIL=0
echo "═══ 容器安全檢查：$SVC ═══"

chk(){ printf '  %-42s ' "$1"; if eval "$2" >/dev/null 2>&1; then echo "✓"; else echo "✗"; FAIL=$((FAIL+1)); fi; }

C=$($COMPOSE ps -q "$SVC" | head -1)
[ -n "$C" ] || { echo "找不到容器"; exit 1; }

chk "★★★ 未 publish 埠" \
    "! docker inspect $C | jq -e '.[0].NetworkSettings.Ports | to_entries[] | select(.value != null)' >/dev/null"
chk "★★ 非 root 執行" \
    "[ \"\$(docker exec $C id -u)\" != 0 ]"
chk "★★★ PID 1 是 init" \
    "docker exec $C sh -c 'head -c 200 /proc/1/cmdline | tr \"\\0\" \" \"' | grep -qE 'dumb-init|tini'"
chk "★ 有健康檢查" \
    "docker inspect $C | jq -e '.[0].State.Health' >/dev/null"
chk "★ 健康狀態正常" \
    "[ \"\$(docker inspect $C | jq -r '.[0].State.Health.Status')\" = healthy ]"
chk "★★ 環境變數無明文秘密" \
    "! docker inspect $C | jq -r '.[0].Config.Env[]' | grep -qiE 'SECRET=[^F]|PASSWORD=|_KEY=[A-Za-z0-9]{20}'"
chk "★★ 映像內無 .env" \
    "! docker exec $C sh -c 'ls /app/.env 2>/dev/null' | grep -q ."
chk "★ 有記憶體限制" \
    "[ \"\$(docker inspect $C | jq -r '.[0].HostConfig.Memory')\" != 0 ]"
chk "★ no-new-privileges" \
    "docker inspect $C | jq -r '.[0].HostConfig.SecurityOpt[]?' | grep -q no-new-privileges"
chk "★ 日誌有輪替上限" \
    "docker inspect $C | jq -e '.[0].HostConfig.LogConfig.Config[\"max-size\"]' >/dev/null"

echo
[ "$FAIL" -eq 0 ] && echo "  ✓✓ 全部通過" || echo "  ✗ $FAIL 項未通過"
exit "$FAIL"
EOF
$ sudo chmod +x /usr/local/bin/check-container-security
$ check-container-security nuxt
```

> [!warning] `NODE_OPTIONS` 與容器記憶體上限 ★★
> ```
> ★★ Node 的 V8 堆上限【預設不會讀取 cgroup 的限制】
>   → 容器設 512MB，但 V8 以為自己有整台機器的記憶體
>     → ★ 一直不做 GC → 超過 cgroup 上限 → 【OOM Kill】
>       → 容器直接被殺，沒有任何錯誤訊息（exit code 137）
>
> ★★ 解法：明確設定
>   deploy.resources.limits.memory: 800M
>   NODE_OPTIONS: --max-old-space-size=512     ← ★ 約為容器上限的 60~70%
>
> ★ 留出空間給：非堆的記憶體（buffer、原生模組、程式碼本身）
>
> ★ Node 18+ 對 cgroup v2 有部分支援，但明確設定仍然最可靠
> ```

```bash
# ★ 檢查是否被 OOM kill
$ docker inspect nuxt-lxmp-nuxt-1 | jq '.[0].State | {OOMKilled, ExitCode, Error}'
{
  "OOMKilled": true,          # ★★ 被 OOM 殺掉
  "ExitCode": 137,
  "Error": ""
}
$ dmesg | grep -i 'killed process'
```

---

## 速查表

### ★★★ 三個 SSR 容器必做的事

```dockerfile
# ① PID 1
RUN apk add --no-cache dumb-init
ENTRYPOINT ["dumb-init", "--"]
CMD ["node", ".output/server/index.mjs"]

# ② 非 root
USER node

# ③ 只複製 .output（自給自足）
COPY --from=build --chown=node:node /app/.output ./.output
```

### ★★ HOST 的差異

```
裸機部署：HOST=127.0.0.1     ★ 防止繞過 Nginx
容器部署：HOST=0.0.0.0       ★ 容器有自己的網路命名空間
          ★★★ 隔離靠「不 publish 埠」：
             ❌ ports: - "3000:3000"
             ✅ expose: - "3000"
```

### 優雅關閉

```typescript
process.on('SIGTERM', () => shutdown());   // ★★★ 容器主要送這個
process.on('SIGINT',  () => shutdown());
```
```yaml
init: true                # ★★★ 或用 dumb-init
stop_grace_period: 20s    # ★★ 給足夠的時間
```

### 執行時環境變數

```bash
# ★★ Nuxt 天然支援（不需要 env.js 技巧）
docker run -e NUXT_PUBLIC_API_BASE=https://api.gov.tw nuxt-app:v1.2.3
```

```
★★ 秘密不要用 -e（docker inspect 看得到）
   → env_file（600）/ Docker secrets / _FILE 慣例
```

### 記憶體 ★★

```yaml
deploy.resources.limits.memory: 800M
environment:
  NODE_OPTIONS: --max-old-space-size=512    # ★ 容器上限的 60~70%
```

```
★★ 不設 → V8 不知道 cgroup 限制 → OOM Kill（exit 137，無錯誤訊息）
```

### Compose 網路

```yaml
networks:
  web:  {}
  data: { internal: true }      # ★★ 無法連外

proxy: { networks: [web] }              # ★ 唯一有 ports 的
nuxt:  { networks: [web, data], expose: ["3000"] }   # ★★ 沒有 ports
mysql: { networks: [data] }             # ★★ 完全隔離
```

### ★★★ 五條紅線

```
① 不 publish SSR 的埠
② 必須有 init 程序（dumb-init / tini / init: true）
③ 秘密不用 -e
④ 非 root（USER node）
⑤ 不 COPY .env / 私鑰進映像
```

### 排查

```bash
docker exec C ps -ef                             # ★★★ PID 1 是 dumb-init？
time docker stop C                               # ★ 應該 <3 秒
docker compose ps --format 'table {{.Name}}\t{{.Ports}}'   # ★★ SSR 不應有 ports
docker inspect C | jq '.[0].Config.Env'          # ★★ 無明文秘密
docker inspect C | jq '.[0].State.Health'
docker inspect C | jq '.[0].State | {OOMKilled, ExitCode}'
check-container-security nuxt
```

---

## 練習題

> [!question]- 練習 1：PID 1 問題 ★★★
> 1. **不用 `dumb-init`**，直接 `CMD ["node", ".output/server/index.mjs"]`
> 2. **不註冊 SIGTERM handler**
> 3. `time docker stop` → **花了多久？**
> 4. 加上 SIGTERM handler（不加 dumb-init）→ 再測
> 5. 加上 `dumb-init` → 再測
> 6. `docker exec C ps -ef` 看 PID 1 是誰
> 7. **記錄四種組合的停止時間**

> [!question]- 練習 2：埠暴露的風險 ★★★
> 1. 用 `ports: - "3000:3000"` 啟動
> 2. **從另一台機器** `curl http://伺服器IP:3000/` → **連得到嗎？**
> 3. 比較「經過 proxy」與「直連 3000」的回應標頭
> 4. **列出繞過 proxy 會失去哪些防護**
> 5. 改成 `expose: - "3000"` → 再測
> 6. `docker compose ps` 看 PORTS 欄位的差別

> [!question]- 練習 3：OOM Kill ★★
> 1. 設 `deploy.resources.limits.memory: 256M`，**不設 `NODE_OPTIONS`**
> 2. 用 `wrk` 壓測直到容器掛掉
> 3. `docker inspect C | jq '.[0].State'` → **`OOMKilled` 是 true 嗎？ExitCode？**
> 4. 加上 `NODE_OPTIONS: --max-old-space-size=160`
> 5. 再壓測 → **這次是 OOM 還是 V8 自己的 heap out of memory？**
> 6. **哪一種比較好？為什麼？**

> [!question]- 練習 4：執行時環境變數
> 1. 建置一個映像
> 2. **同一個 tag** 用三組不同的 `NUXT_PUBLIC_API_BASE` 啟動
> 3. `curl http://localhost:PORT/ | grep apiBase` → **各自不同嗎？**
> 4. 用 `-e NUXT_API_SECRET=xxx` 傳秘密
> 5. `docker inspect C | jq '.[0].Config.Env'` → **看得到嗎？**
> 6. 改用 `secrets` + `_FILE` 慣例 → 再檢查一次

> [!question]- 練習 5：零停機更新
> 1. 部署完整的 Compose 全套
> 2. 開持續請求的迴圈
> 3. `docker compose up -d --no-deps nuxt`（**不加 `--wait`**）→ **有幾次失敗？**
> 4. 加上 `--wait --wait-timeout 60` → 再測
> 5. 加上 `stop_grace_period: 20s` 與優雅關閉 → 再測
> 6. 執行 `deploy-nuxt-docker` 腳本，**故意讓煙霧測試失敗** → 有中止嗎？

---

## 小測驗

Q1. **SSR 容器與 SPA 容器最大的三個差異**？

Q2. **為什麼容器內要用 `HOST=0.0.0.0`，而裸機部署要用 `127.0.0.1`**？

Q3. **什麼是 PID 1 問題？不處理會怎樣**？

Q4. **`dumb-init` / `tini` / `init: true` 三者的關係**？

Q5. **為什麼最終映像只要複製 `.output` 就好**？

Q6. **秘密為什麼不要用 `-e` 傳**？三種較好的做法？

Q7. **`NODE_OPTIONS: --max-old-space-size` 為什麼一定要設**？

Q8. **`stop_grace_period` 的作用**？

Q9. **SSR 容器要怎麼做到「靜態資源由 Nginx 直送」**？

Q10. **Compose 中 SSR 容器為什麼不能用 `ports:`**？

> [!question]- 測驗答案
> **Q1.** ①**執行的東西不同** ——
> SPA 容器跑 **Nginx 送靜態檔**（基底 `nginx:alpine`，~50MB，記憶體 ~10MB）；
> SSR 容器跑 **長駐的 Node 程序**（基底 `node:22-alpine`，~150MB，記憶體 80～300MB）。
> ②**★★★ SSR 容器必須處理優雅關閉與 PID 1 問題** ——
> Nginx 官方映像已經處理好訊號，
> 但 Node 若沒註冊 `SIGTERM` handler 且沒有 init 程序，`docker stop` 會**完全無效**。
> ③**環境變數的處理** ——
> SPA 需要 `env.js` + entrypoint 的技巧才能執行時注入；
> **Nuxt 的 `runtimeConfig` 天然支援**（`docker run -e NUXT_PUBLIC_API_BASE=...` 直接生效）。
>
> **Q2.** **兩者的隔離機制不同**。
> **裸機**：Node 與 Nginx 在**同一個網路命名空間**，
> 綁 `0.0.0.0` 就等於**暴露在所有網路介面上**，
> 外部可以直接連 3000 埠**繞過 Nginx**（繞過 TLS/WAF/限流/安全標頭）。
> **容器**：**每個容器有自己的網路命名空間**，
> 綁 `127.0.0.1` 的話**連同一個 Docker 網路裡的 proxy 容器都連不到**。
> **容器的隔離靠的是「不要 publish 埠」**：
> ```yaml
> ❌ ports:  - "3000:3000"     # 暴露到宿主機
> ✅ expose: - "3000"          # 只有同網路的容器看得到
> ```
> **驗證**：`docker compose ps` 的 PORTS 欄位，SSR 容器不該有 `0.0.0.0:3000->3000/tcp`。
>
> **Q3.** **在容器中，`CMD` 指定的程序會成為 PID 1**，
> 而 **PID 1 在 Linux 有特殊行為：預設「忽略」所有沒有明確註冊 handler 的訊號**
> （這是核心的保護機制，避免意外殺掉 init 程序）。
> **後果**：
> ①**`docker stop` 送的 `SIGTERM` 被完全忽略** →
> Docker 等 10 秒後送 `SIGKILL` **強制殺掉** →
> **正在處理的請求全部被中斷**，資料庫連線沒有正常關閉；
> ②**孤兒殭屍程序不會被回收**（如果應用有 spawn 子程序）。
> **症狀很好辨認**：`time docker stop` 每次都剛好花 **10 秒**。
>
> **Q4.** **三者都是解決同一個問題：讓一個「正確處理訊號與殭屍程序」的 init 程式當 PID 1**。
> **`dumb-init`** —— Yelp 開發的極簡 init，要自己 `apk add` 並設
> `ENTRYPOINT ["dumb-init", "--"]`。
> **`tini`** —— 功能類似，**Docker 內建**了一份。
> **`init: true`（Compose）/ `docker run --init`** ——
> **讓 Docker 自動注入它內建的 tini 當 PID 1**，
> **不需要修改 Dockerfile**。
> **實務選擇**：
> 映像要能獨立運作（可能被 k8s 或其他方式執行）→ 在 Dockerfile 裡用 `dumb-init`；
> 只在 Compose 環境用 → `init: true` 最簡單。
> **兩者同時用也沒問題**（tini 執行 dumb-init 執行 node）。
>
> **Q5.** 因為 **Nitro 的 `node-server` preset 會把所有需要的相依「打包」進 `.output/server/node_modules`**。
> 它做的是 bundle 而不是單純編譯 ——
> 分析 `node_modules` 裡實際用到的程式碼、tree-shake、輸出到產物目錄。
> **所以 `.output/` 是完全自給自足的**：
> ```dockerfile
> COPY --from=build /app/.output ./.output
> CMD ["node", ".output/server/index.mjs"]
> ```
> **不需要**複製專案的 `node_modules`（通常幾百 MB），
> **也不需要**在最終映像裡跑 `npm install`。
> 這讓最終映像從 500MB+ 降到約 150MB，
> 而且**最終映像裡沒有 npm、沒有原始碼、沒有建置工具** —— 攻擊面小很多。
>
> **Q6.** 因為 **`-e` 傳入的環境變數會被記錄在容器的 metadata 裡**：
> `docker inspect C | jq '.[0].Config.Env'` **直接看得到明文**，
> 執行的當下 `ps aux` 也看得到，
> 而且會留在 **shell history** 與 CI 的日誌裡。
> **三種較好的做法**：
> ①**`env_file`**（檔案權限設 600，且 `.gitignore` 排除）；
> ②**★★ Docker secrets** —— 掛載到 `/run/secrets/xxx`，
> 只存在於容器的 tmpfs，`docker inspect` 看不到內容；
> ③**`_FILE` 慣例**（Docker 生態的標準做法）——
> 環境變數傳的是**檔案路徑**（`NUXT_API_SECRET_FILE=/run/secrets/x`），
> 應用啟動時自己讀檔案。
>
> **Q7.** 因為 **Node 的 V8 堆上限預設不會讀取 cgroup 的記憶體限制** ——
> 容器設了 512MB，但 **V8 以為自己有整台機器的記憶體**，
> 於是**一直不積極做 GC**，直到超過 cgroup 上限 →
> **容器被核心 OOM Kill（exit code 137），而且沒有任何應用層的錯誤訊息**。
> **正確設定**：
> ```yaml
> deploy.resources.limits.memory: 800M
> environment:
>   NODE_OPTIONS: --max-old-space-size=512     # ★ 約容器上限的 60~70%
> ```
> 要留空間給**非堆的記憶體**（Buffer、原生模組、程式碼本身、堆疊）。
> **驗證是否被 OOM**：`docker inspect C | jq '.[0].State | {OOMKilled, ExitCode}'`。
>
> **Q8.** **`stop_grace_period` 是 Docker 在送出 `SIGTERM` 之後、
> 送 `SIGKILL` 之前的等待時間**（預設 **10 秒**）。
> **它決定了「優雅關閉有多少時間可以用」** ——
> 如果應用需要等待進行中的請求完成（例如一個跑 15 秒的報表產生），
> 預設的 10 秒不夠，請求還是會被強制中斷。
> **設定原則**：
> `stop_grace_period` 要**大於**應用內部的優雅關閉逾時
> （例如應用等 8 秒 → `stop_grace_period: 20s`），
> 留一點餘裕給關閉資料庫連線池等後續動作。
> 這與 PM2 的 `kill_timeout`、systemd 的 `TimeoutStopSec` 是同一個概念。
>
> **Q9.** **透過「共享 volume」把 Nuxt 的 `.output/public` 分享給 Nginx 容器**：
> ```yaml
> volumes:
>   nuxt-public:
> services:
>   nuxt:  { volumes: [nuxt-public:/app/.output/public:ro] }
>   proxy: { volumes: [nuxt-public:/usr/share/nginx/nuxt-public:ro] }
> ```
> ```nginx
> location ^~ /_nuxt/ {
>     alias /usr/share/nginx/nuxt-public/_nuxt/;
>     try_files $uri =404;
>     expires 1y;
>     add_header Cache-Control "public, max-age=31536000, immutable";
> }
> ```
> **這樣靜態資源完全不經過 Node**，
> 讓 Node 專心做 SSR 渲染（可以提升數倍的吞吐量）。
> **注意**：更新映像後 volume 裡的內容要跟著更新
> （volume 是在容器啟動時從映像複製的，新容器會帶新內容）。
>
> **Q10.** 因為 **`ports:` 會把容器的埠「publish 到宿主機的所有網路介面」**（`0.0.0.0`），
> 等於**把 SSR 服務直接暴露出去**，
> 任何能連到這台機器的人都可以 `http://伺服器IP:3000/` **繞過 proxy 容器**，
> 因而繞過：**TLS 加密、ModSecurity WAF、proxy_cache、限流、
> 所有安全標頭、存取日誌**。
> **正確做法是 `expose: ["3000"]`**（或什麼都不寫）——
> 同一個 Docker 網路內的 proxy 容器仍然連得到（`http://nuxt:3000`），
> 但**宿主機與外部完全連不到**。
> **同樣的原則適用於資料庫容器** —— 更不能 publish 3306。
> **驗證**：`docker compose ps --format 'table {{.Name}}\t{{.Ports}}'`，
> 只有 proxy 應該有 `0.0.0.0:443->443/tcp`。

---

## 延伸閱讀

- [[130-01-05-07-guide-Nuxt-Laravel-SSR完整部署實戰]] — 完整的整合實戰
- [[130-01-02-03-guide-Vue-Docker部署]] — SPA 容器化（對照）
- [[130-01-03-03-guide-Nuxt-Nginx反向代理與快取]] — proxy 層的完整設定
- [[050-02-01-06-svc-Docker-多階段建置與映像優化]] — 映像優化
- [[050-02-01-08-guide-Docker-安全實務]] — 容器安全加固
- [[050-02-02-02-guide-Compose-多服務編排實戰]] — Compose 的進階用法
