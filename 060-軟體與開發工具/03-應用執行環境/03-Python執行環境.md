---
title: "Python 執行環境"
desc: "venv / uv 虛擬環境、gunicorn / uvicorn 與 systemd 整合"
aliases: [python, venv, uv, gunicorn, uvicorn, pip, requirements.txt]
tags: [群組/軟體與開發工具, 服務/python, 主題/執行環境]
category: 應用執行環境
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[14-套件管理]]"]
updated: 2026-08-28
---

# Python 執行環境

> [!abstract] 這篇你會學到
> - 為什麼**絕對不要動系統的 Python**，以及 PEP 668 的意義
> - 用 **venv** 與 **uv** 建立隔離的執行環境
> - 用 **`requirements.txt` + `pip-compile`** 或 **`uv.lock`** 鎖定版本
> - 用 **gunicorn / uvicorn** 部署 WSGI / ASGI 應用
> - 寫出正確的 **systemd service**（含 socket 與加固）
> - 這是 **OpenWebUI / ComfyUI / n8n 附屬服務**的前置知識

## 前置知識

- [[14-套件管理]] — apt / dnf
- [[17-systemd服務管理]] — systemd 基礎

---

## 絕對不要動系統的 Python ★★★

```bash
$ which python3
/usr/bin/python3
$ python3 --version
Python 3.12.3
```

> [!danger] `sudo pip install` 是最危險的 Python 指令
> ```
> 系統的 Python 被【大量系統工具】依賴：
>   · apt / dnf 的部分元件
>   · ufw、firewalld
>   · cloud-init、netplan
>   · fail2ban
>   · 各種發行版的管理腳本
>
> sudo pip install 升級了某個套件
>   → 與系統套件的版本衝突
>     → 【apt 壞掉、防火牆壞掉、開機失敗】
>       → ★★ 而且極難修復（要手動還原每個套件的版本）
> ```
>
> **這是「機器變磚」的常見原因之一。**

```bash
# ★ 現代的 Python（PEP 668）會直接擋下來
$ sudo pip install requests
error: externally-managed-environment

× This environment is externally managed
╰─> To install Python packages system-wide, try apt install
    python3-xyz, where xyz is the package you are trying to
    install.

    If you wish to install a non-Debian-packaged Python package,
    create a virtual environment using python3 -m venv path/to/venv.
```

> [!danger] 不要用 `--break-system-packages` 繞過
> ```bash
> # ❌❌ 這個參數的名字已經告訴你會發生什麼事
> $ sudo pip install --break-system-packages requests
> ```
> **PEP 668 的這個保護機制是為了防止上述的災難。**
> 正確做法是**用虛擬環境**。

```
三個選項（依偏好排序）：

① ★★ 虛擬環境（venv / uv）      —— 應用程式一律用這個
② ★ 系統套件（apt install python3-xxx）—— 系統工具需要時
③ pipx                          —— 安裝 CLI 工具（每個工具一個獨立環境）
```

---

## venv：內建的虛擬環境

```bash
# ═══ 安裝 ═══
$ sudo apt install -y python3-venv python3-pip python3-dev build-essential

# ═══ 建立 ═══
$ cd /var/www/myapp
$ python3 -m venv .venv

$ ls .venv/
bin/  include/  lib/  lib64  pyvenv.cfg

# ═══ 啟用 ═══
$ source .venv/bin/activate
(.venv) $ which python
/var/www/myapp/.venv/bin/python
(.venv) $ python --version
Python 3.12.3

# ═══ 安裝套件 ═══
(.venv) $ pip install --upgrade pip setuptools wheel
(.venv) $ pip install fastapi uvicorn[standard] sqlalchemy psycopg2-binary

# ═══ 離開 ═══
(.venv) $ deactivate
```

> [!tip] 在腳本與 systemd 中不需要 `activate`
> ```bash
> # ★ 直接用虛擬環境中的執行檔（等效於 activate）
> $ /var/www/myapp/.venv/bin/python app.py
> $ /var/www/myapp/.venv/bin/pip install requests
> $ /var/www/myapp/.venv/bin/uvicorn main:app
> ```
> **`activate` 只是修改 `PATH` 與提示字元的便利工具** ——
> **systemd service 中一律用絕對路徑**（與 nvm 的道理相同）。

```bash
# ═══ 其他選項 ═══
$ python3 -m venv --system-site-packages .venv   # ★ 可以看到系統套件（少用）
$ python3 -m venv --upgrade-deps .venv           # 建立時就升級 pip
$ python3 -m venv --prompt myapp .venv           # 自訂提示字元

# ★ 重建虛擬環境（升級 Python 版本後必須）
$ rm -rf .venv && python3 -m venv .venv
$ .venv/bin/pip install -r requirements.txt
```

---

## uv：極快的替代方案 ★

```bash
# ═══ 安裝 ═══
$ curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv.sh
$ less /tmp/uv.sh                        # ★ 先看過
$ sh /tmp/uv.sh
$ source ~/.bashrc

# 或用 pipx / apt
$ pipx install uv

$ uv --version
uv 0.5.11
```

```bash
# ═══ 基本使用 ═══
$ cd /var/www/myapp
$ uv venv                                # ★ 建立 .venv（比 python -m venv 快很多）
$ uv pip install fastapi uvicorn         # ★ 比 pip 快 10-100 倍

# ═══ ★ 專案模式（推薦）═══
$ uv init myapp && cd myapp
$ uv add fastapi 'uvicorn[standard]'     # ★ 自動更新 pyproject.toml 與 uv.lock
$ uv add --dev pytest ruff mypy
$ uv sync                                # ★ 依 uv.lock 安裝（等同 npm ci）
$ uv sync --frozen                       # ★★ 嚴格：lock 不同步就失敗
$ uv run uvicorn main:app                # ★ 自動使用虛擬環境
$ uv lock --upgrade-package fastapi      # 只升級某個套件

# ═══ Python 版本管理 ═══
$ uv python list
$ uv python install 3.12
$ uv venv --python 3.12
```

```toml
# pyproject.toml
[project]
name = "myapp"
version = "1.0.0"
requires-python = ">=3.11,<3.14"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy>=2.0.36",
    "psycopg[binary]>=3.2.3",
    "pydantic-settings>=2.6.0",
]

[dependency-groups]
dev = ["pytest>=8.3.0", "ruff>=0.8.0", "mypy>=1.13.0"]

[tool.uv]
package = false
```

| | **pip + venv** | **uv** |
| --- | --- | --- |
| 內建 | ✅ | ❌ |
| 速度 | 基準 | **★ 10-100 倍** |
| lock 檔 | 需要 pip-tools | **★ 內建 `uv.lock`** |
| Python 版本管理 | ❌ | **★ 內建** |
| 相依解析 | 較弱 | **★ 完整的 resolver** |
| 成熟度 | 極成熟 | 較新（但已廣泛採用） |

> [!tip] 選擇建議
> ```
> ① 求穩、環境單純           → venv + pip + pip-tools
> ② 大量相依、CI 時間敏感    → ★ uv
> ③ 已有 poetry/pdm 且運作良好 → 不用換
>
> ★ 無論選哪個，重點是【要有 lock 檔】
> ```

---

## 鎖定版本

### pip + pip-tools

```bash
$ pip install pip-tools

# ═══ 只寫「直接相依」到 requirements.in ═══
$ cat requirements.in
fastapi>=0.115
uvicorn[standard]>=0.32
sqlalchemy>=2.0
psycopg[binary]>=3.2

# ═══ ★ 產生完整的 lock 檔 ═══
$ pip-compile --generate-hashes --output-file=requirements.txt requirements.in

$ head -20 requirements.txt
# This file is autogenerated by pip-compile with Python 3.12
# by the following command:
#    pip-compile --generate-hashes --output-file=requirements.txt requirements.in
#
annotated-types==0.7.0 \
    --hash=sha256:1f02e8b43a8fbbc3f3e0d4f0f4bfc8131bcb4eebe8849b8e5c773f3a1c582a53 \
    --hash=sha256:aff07c09a53a08bc8cfccb9c85b05f1aa9a2a6f23728d790723543408344ce89
    # via pydantic
anyio==4.7.0 \
    --hash=sha256:... \
    # via httpx, starlette
```

```bash
# ═══ ★★ 正式環境安裝（驗證雜湊）═══
$ pip install --require-hashes -r requirements.txt

# ═══ 開發相依分開 ═══
$ pip-compile --generate-hashes -o requirements-dev.txt requirements-dev.in

# ═══ 升級 ═══
$ pip-compile --upgrade requirements.in                        # 全部
$ pip-compile --upgrade-package fastapi requirements.in        # 只升級一個

# ═══ 同步（★ 移除不在 lock 中的套件）═══
$ pip-sync requirements.txt
```

> [!danger] `--generate-hashes` 是供應鏈安全的關鍵
> ```
> 沒有雜湊：
>   pip 從 PyPI 下載 → 【直接安裝】
>     → 若 PyPI 被入侵、或有中間人 → 【裝到被竄改的套件】
>
> 有 --require-hashes：
>   下載後【驗證 SHA-256】
>     → 不符就【直接失敗】
> ```
>
> **這等同於 npm 的 `integrity` 與 Composer 的 lock 檔雜湊。**

```bash
# ★ 沒有 lock 檔時的最低要求：凍結版本
$ pip freeze > requirements.txt
# ⚠ 但這會包含所有間接相依，且沒有雜湊，也分不出直接／間接相依
```

### uv

```bash
$ uv lock                                # 產生 uv.lock
$ uv sync --frozen --no-dev              # ★★ 正式環境（嚴格 + 不裝開發相依）
$ uv export --format requirements-txt --no-dev > requirements.txt   # 匯出相容格式
```

| 檔案 | git |
| --- | --- |
| `requirements.in` / `pyproject.toml` | **✅ 進 git** |
| **`requirements.txt`（compile 後）/ `uv.lock`** | **✅ 進 git** |
| `.venv/` | **❌ 不要進 git** |

```gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.egg-info/
.env
```

---

## WSGI vs ASGI

```
WSGI（同步）：Django（傳統）、Flask
  → 用 gunicorn

ASGI（非同步）：FastAPI、Starlette、Django (async)、Channels
  → 用 uvicorn（或 gunicorn + uvicorn worker）
```

### gunicorn（WSGI）

```bash
$ pip install gunicorn

# 基本
$ gunicorn myapp.wsgi:application --bind 127.0.0.1:8000

# ★ 正式環境
$ gunicorn myapp.wsgi:application \
    --bind unix:/run/myapp/gunicorn.sock \
    --workers 4 \
    --worker-class sync \
    --threads 2 \
    --timeout 60 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
```

```python
# ═══ gunicorn.conf.py（★ 設定即程式碼）═══
import multiprocessing
import os

# ── 綁定 ──
bind = os.getenv('GUNICORN_BIND', 'unix:/run/myapp/gunicorn.sock')
umask = 0o007                      # ★ socket 權限 660

# ── Worker ──
workers = int(os.getenv('WEB_CONCURRENCY', multiprocessing.cpu_count() * 2 + 1))
worker_class = 'sync'              # sync / gthread / uvicorn.workers.UvicornWorker
threads = 2                        # 只對 gthread 有意義
worker_connections = 1000

# ── ★ 逾時 ──
timeout = 60                       # ★ worker 無回應多久後被殺掉
graceful_timeout = 30              # ★ 優雅關閉的等待時間
keepalive = 5

# ── ★ 防記憶體洩漏 ──
max_requests = 1000                # 處理 N 個請求後重生 worker
max_requests_jitter = 100          # ★ 加隨機值，避免所有 worker 同時重生

# ── 日誌（★ 交給 journald）──
accesslog = '-'
errorlog = '-'
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sus'
#                                                                                  ^^^^ 微秒

# ── 其他 ──
preload_app = True                 # ★ 先載入應用再 fork（省記憶體，但 reload 需 restart）
forwarded_allow_ips = '127.0.0.1'  # ★ 只信任本機代理
proxy_allow_ips = '127.0.0.1'
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

# ── Hooks ──
def when_ready(server):
    server.log.info("Gunicorn 已就緒，監聽 %s", bind)

def worker_int(worker):
    worker.log.info("Worker %s 收到 SIGINT", worker.pid)

def child_exit(server, worker):
    # ★ Prometheus multiprocess 模式需要清理
    pass
```

```bash
$ gunicorn -c gunicorn.conf.py myapp.wsgi:application
```

| worker_class | 適用 | 說明 |
| --- | --- | --- |
| **`sync`** | **一般的同步應用** | 一個 worker 一次一個請求（★ 最穩定） |
| `gthread` | I/O 較多的同步應用 | 每個 worker 開多個執行緒 |
| **`uvicorn.workers.UvicornWorker`** | **ASGI 應用** | ★ 讓 gunicorn 管理 uvicorn |
| `gevent` / `eventlet` | 大量 I/O 等待 | 需要 monkey patching（★ 容易出問題） |

> [!warning] `workers` 該設多少
> ```
> 官方建議：(2 × CPU 核心數) + 1
>
> ★ 但要考慮記憶體：
>   workers × 單一 worker 的 RSS ≤ 可用記憶體
>
> 例：4 核心，每 worker 200MB，可用 4GB
>   CPU 角度：2×4+1 = 9
>   記憶體角度：4096/200 ≈ 20
>   → 取 9
>
> 但若每 worker 是 800MB（載入了 ML 模型）：
>   記憶體角度：4096/800 ≈ 5
>   → ★ 取 5（記憶體是限制）
> ```
> ```bash
> # ★ 觀察實際的 RSS
> $ ps -o rss=,args= -C gunicorn | awk '{printf "%.0f MB  %s\n", $1/1024, $2}'
> ```

### uvicorn（ASGI）

```bash
$ pip install 'uvicorn[standard]'      # ★ standard 包含 uvloop 與 httptools（更快）

# 開發
$ uvicorn main:app --reload --host 127.0.0.1 --port 8000

# ★ 正式環境（單程序）
$ uvicorn main:app \
    --host 127.0.0.1 --port 8000 \
    --workers 4 \
    --loop uvloop \
    --http httptools \
    --proxy-headers \
    --forwarded-allow-ips='127.0.0.1' \
    --timeout-keep-alive 5 \
    --log-level info

# ★★ 正式環境（gunicorn 管理 uvicorn —— 更好的程序管理）
$ gunicorn main:app \
    -k uvicorn.workers.UvicornWorker \
    -c gunicorn.conf.py
```

> [!tip] `gunicorn + UvicornWorker` 比純 uvicorn 好的三個理由
> ```
> ① ★ 更成熟的 worker 管理（自動重生、優雅關閉、max_requests）
> ② ★ 支援 unix socket（uvicorn 的 --uds 較少人用）
> ③ ★ 統一的設定檔與 hooks
>
> 但純 uvicorn --workers N 也是可行的（較新的版本已改善）
> ```

> [!danger] `--proxy-headers` 與 `--forwarded-allow-ips` 缺一不可
> ```
> 沒有 --proxy-headers：
>   → 應用讀到的 client IP 是 127.0.0.1（Nginx 的）
>   → request.url.scheme 是 http（★ 導致重導向迴圈）
>
> 有 --proxy-headers 但 --forwarded-allow-ips='*'：
>   → ★★ 任何人都能偽造 X-Forwarded-For / X-Forwarded-Proto
>     → 繞過 IP 限制與限流
>
> ✅ --proxy-headers --forwarded-allow-ips='127.0.0.1'
> ```

---

## systemd 整合

```ini
# ═══════════ /etc/systemd/system/myapp.service ═══════════
[Unit]
Description=MyApp FastAPI (gunicorn + uvicorn worker)
After=network.target postgresql.service redis.service
Requires=myapp.socket

[Service]
Type=notify                        # ★ gunicorn 支援 sd_notify
User=myapp
Group=myapp
WorkingDirectory=/var/www/myapp/current

# ★ 環境變數
Environment="PATH=/var/www/myapp/current/.venv/bin"
Environment="PYTHONUNBUFFERED=1"           # ★ 日誌即時輸出（不緩衝）
Environment="PYTHONDONTWRITEBYTECODE=1"    # 不產生 .pyc
Environment="WEB_CONCURRENCY=4"
EnvironmentFile=-/var/www/myapp/shared/.env

# ★ 絕對路徑（不需要 activate）
ExecStart=/var/www/myapp/current/.venv/bin/gunicorn \
    --config /var/www/myapp/current/gunicorn.conf.py \
    main:app

ExecReload=/bin/kill -s HUP $MAINPID        # ★ 優雅重載
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30

Restart=always
RestartSec=5

StandardOutput=journal
StandardError=journal
SyslogIdentifier=myapp

# ★ 安全加固
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/www/myapp/shared/storage /run/myapp
RuntimeDirectory=myapp                      # ★ 自動建立 /run/myapp
RuntimeDirectoryMode=0750
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
LockPersonality=true
RestrictSUIDSGID=true
RemoveIPC=true
MemoryDenyWriteExecute=false                # ★ 某些 C 擴充需要

# 資源限制
LimitNOFILE=65535
MemoryMax=2G
CPUQuota=200%

[Install]
WantedBy=multi-user.target
```

```ini
# ═══════════ /etc/systemd/system/myapp.socket ═══════════
# ★ socket activation：systemd 建立 socket，權限交給 systemd 管理
[Unit]
Description=MyApp gunicorn socket

[Socket]
ListenStream=/run/myapp/gunicorn.sock
SocketUser=myapp
SocketGroup=www-data                # ★ Nginx 的身分
SocketMode=0660

[Install]
WantedBy=sockets.target
```

```bash
$ sudo useradd -r -M -d /var/www/myapp -s /usr/sbin/nologin myapp
$ sudo systemctl daemon-reload
$ sudo systemctl enable --now myapp.socket myapp.service
$ sudo systemctl status myapp
$ sudo journalctl -u myapp -f

$ ls -l /run/myapp/gunicorn.sock
srw-rw---- 1 myapp www-data 0 ... /run/myapp/gunicorn.sock
```

```nginx
# ═══ Nginx 反向代理 ═══
upstream myapp {
    server unix:/run/myapp/gunicorn.sock;
    keepalive 16;
}

server {
    listen 443 ssl;
    http2 on;
    server_name api.example.gov.tw;
    include snippets/ssl-params.conf;
    ssl_certificate     /etc/letsencrypt/live/api.example.gov.tw/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.gov.tw/privkey.pem;
    include snippets/security-headers.conf;

    client_max_body_size 20m;

    # ★ 靜態檔由 Nginx 直接處理
    location /static/ {
        alias /var/www/myapp/current/static/;
        expires 30d;
        add_header Cache-Control "public" always;
        access_log off;
    }
    location /media/ {
        alias /var/www/myapp/shared/media/;
        expires 7d;
        location ~* \.(php|py|sh)$ { deny all; return 404; }
    }

    location / {
        proxy_pass http://myapp;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;      # ★★
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        $connection_upgrade;
        proxy_read_timeout 60s;
    }

    # ★ SSE / WebSocket（AI 串流常用）
    location /api/stream {
        proxy_pass http://myapp;
        include snippets/proxy-common.conf;
        proxy_buffering off;                   # ★★ 串流必須
        proxy_read_timeout 3600s;
        add_header X-Accel-Buffering no;
        gzip off;
    }
}
```

> [!warning] `PYTHONUNBUFFERED=1` 不能少
> ```
> Python 預設會【緩衝 stdout】
>   → 日誌不會即時出現在 journalctl
>     → ★ 崩潰時可能【完全看不到最後的錯誤訊息】
>
> PYTHONUNBUFFERED=1 → 立刻輸出
> ```
> **這在容器中也是必要的設定。**

---

## 完整實戰範例

### 部署腳本

```bash
#!/usr/bin/env bash
# Python 應用的零停機部署
set -euo pipefail
APP=/var/www/myapp
REPO=https://github.com/gov-org/myapp.git
BRANCH="${1:-main}"
TS=$(date +%Y%m%d-%H%M%S)
REL="$APP/releases/$TS"
SVC=myapp

log() { printf '\033[36m[%s]\033[0m %s\n' "$(date +%T)" "$*"; }
fail() { printf '\033[31m[錯誤]\033[0m %s\n' "$*"; exit 1; }

log "═══ 【1】取得程式碼 ═══"
git clone --depth 1 --branch "$BRANCH" "$REPO" "$REL" || fail "clone 失敗"
cd "$REL"
COMMIT=$(git rev-parse --short HEAD)
echo "$COMMIT" > VERSION
log "  commit: $COMMIT"

log "═══ 【2】連結共享資源 ═══"
ln -sfn "$APP/shared/.env" "$REL/.env"
ln -sfn "$APP/shared/media" "$REL/media"

log "═══ 【3】★ 建立虛擬環境 ═══"
if command -v uv >/dev/null; then
    uv venv "$REL/.venv"
    log "  使用 uv"
else
    python3 -m venv "$REL/.venv"
    "$REL/.venv/bin/pip" install --upgrade pip setuptools wheel --quiet
fi

log "═══ 【4】★★ 安裝相依（驗證雜湊）═══"
if [ -f uv.lock ]; then
    uv sync --frozen --no-dev || fail "uv sync 失敗"
elif [ -f requirements.txt ]; then
    if grep -q -- '--hash=' requirements.txt; then
        "$REL/.venv/bin/pip" install --require-hashes -r requirements.txt || fail "pip install 失敗"
        log "  ✓ 已驗證雜湊"
    else
        log "  ⚠ requirements.txt 沒有雜湊【建議用 pip-compile --generate-hashes】"
        "$REL/.venv/bin/pip" install -r requirements.txt || fail "pip install 失敗"
    fi
else
    fail "找不到 uv.lock 或 requirements.txt"
fi

log "═══ 【5】★ 安全稽核 ═══"
"$REL/.venv/bin/pip" install pip-audit --quiet 2>/dev/null || true
if "$REL/.venv/bin/pip-audit" --version >/dev/null 2>&1; then
    "$REL/.venv/bin/pip-audit" 2>&1 | tail -20 | sed 's/^/  /' || {
        log "  ⚠⚠ 發現已知漏洞"
        # 依政策決定是否中止
    }
fi

log "═══ 【6】收集靜態檔與遷移（Django）═══"
if [ -f manage.py ]; then
    "$REL/.venv/bin/python" manage.py collectstatic --noinput --clear
    "$REL/.venv/bin/python" manage.py migrate --noinput || fail "遷移失敗"
    "$REL/.venv/bin/python" manage.py check --deploy 2>&1 | sed 's/^/  /'
fi

log "═══ 【7】★ 煙霧測試（臨時 port）═══"
TEST_PORT=$((8000 + RANDOM % 1000))
("$REL/.venv/bin/gunicorn" main:app -k uvicorn.workers.UvicornWorker \
    --bind "127.0.0.1:$TEST_PORT" --workers 1 --timeout 30 \
    > /tmp/smoke-$TS.log 2>&1 & echo $! > /tmp/smoke-$TS.pid)
OK=0
for i in $(seq 1 30); do
    curl -sf -m 2 "http://127.0.0.1:$TEST_PORT/health" >/dev/null 2>&1 && { OK=1; break; }
    sleep 1
done
kill "$(cat /tmp/smoke-$TS.pid)" 2>/dev/null || true
rm -f /tmp/smoke-$TS.pid
[ "$OK" -eq 1 ] || {
    tail -30 /tmp/smoke-$TS.log | sed 's/^/    /'
    rm -rf "$REL"
    fail "煙霧測試失敗，已中止（現有服務不受影響）"
}
log "  ✓ 通過"
rm -f /tmp/smoke-$TS.log

log "═══ 【8】★★ 原子切換 ═══"
PREV=$(readlink -f "$APP/current" 2>/dev/null || echo "")
ln -sfn "$REL" "$APP/current.tmp"
mv -Tf "$APP/current.tmp" "$APP/current"

log "═══ 【9】★ 優雅重載 ═══"
# gunicorn 的 SIGHUP 會逐一替換 worker（★ 但 preload_app=True 時無效）
sudo systemctl reload "$SVC" || sudo systemctl restart "$SVC"

log "═══ 【10】驗證 ═══"
sleep 5
ACTUAL=$(curl -s -m 5 --unix-socket /run/myapp/gunicorn.sock \
         http://localhost/version 2>/dev/null | grep -oP '"commit"\s*:\s*"\K[^"]+' || echo "?")
if [ "$ACTUAL" = "$COMMIT" ]; then
    log "  ✓ 版本一致：$ACTUAL"
else
    log "  ✗ 版本不符（預期 $COMMIT，實際 $ACTUAL）"
    [ -n "$PREV" ] && {
        log "  ★ 自動回退"
        ln -sfn "$PREV" "$APP/current.tmp"; mv -Tf "$APP/current.tmp" "$APP/current"
        sudo systemctl restart "$SVC"
    }
    fail "部署驗證失敗"
fi

log "═══ 【11】清理 ═══"
ls -1dt "$APP"/releases/*/ | tail -n +6 | xargs -r rm -rf

log "═══ 完成（$COMMIT）═══"
log "回退：ln -sfn $PREV $APP/current && sudo systemctl restart $SVC"
```

> [!warning] `preload_app = True` 時 SIGHUP 無法零停機
> ```
> preload_app = True：
>   ✓ 先載入應用再 fork → 省記憶體（copy-on-write）
>   ✗ ★ SIGHUP 【不會重新載入程式碼】
>     → 必須 systemctl restart（會中斷）
>
> preload_app = False：
>   ✓ SIGHUP 可以逐一替換 worker（零停機）
>   ✗ 每個 worker 各自載入 → 記憶體用量較高、啟動較慢
> ```
> **要零停機就設 `preload_app = False`**；
> 或用**兩個 systemd unit 做藍綠切換**（更複雜但更可靠）。

### 環境檢查腳本

```bash
#!/usr/bin/env bash
# /usr/local/bin/python-env-check
echo "═══ Python 環境檢查 ═══"

echo -e "\n【1】系統 Python"
python3 --version
echo "  路徑：$(which python3)"
python3 -c "import sys; print('  PEP 668 保護:', 'EXTERNALLY-MANAGED' if __import__('os').path.exists(f'{sys.prefix}/lib/python{sys.version_info.major}.{sys.version_info.minor}/EXTERNALLY-MANAGED') else '無')"

echo -e "\n【2】★★ 系統 Python 是否被污染"
SYS_PKGS=$(python3 -m pip list --user 2>/dev/null | tail -n +3 | wc -l)
[ "$SYS_PKGS" -gt 0 ] && {
    echo "  ⚠⚠ 系統 Python 有 $SYS_PKGS 個使用者層級的套件"
    python3 -m pip list --user 2>/dev/null | tail -n +3 | head -10 | sed 's/^/    /'
} || echo "  ✓ 乾淨"

echo -e "\n【3】虛擬環境"
for v in /var/www/*/current/.venv /opt/*/.venv /srv/*/.venv; do
    [ -d "$v" ] || continue
    PY=$("$v/bin/python" --version 2>&1)
    N=$("$v/bin/pip" list --format=freeze 2>/dev/null | wc -l)
    SZ=$(du -sh "$v" 2>/dev/null | cut -f1)
    printf '  %-45s %s  %s 個套件  %s\n' "$v" "$PY" "$N" "$SZ"
done

echo -e "\n【4】★ lock 檔"
for d in /var/www/*/current /opt/*; do
    [ -d "$d" ] || continue
    if [ -f "$d/uv.lock" ]; then
        echo "  ✓ $d：uv.lock"
    elif [ -f "$d/requirements.txt" ]; then
        grep -q -- '--hash=' "$d/requirements.txt" \
          && echo "  ✓ $d：requirements.txt（★ 含雜湊）" \
          || echo "  ⚠ $d：requirements.txt（★ 沒有雜湊，建議 pip-compile --generate-hashes）"
    else
        [ -f "$d/pyproject.toml" ] && echo "  ⚠⚠ $d：只有 pyproject.toml，沒有 lock 檔"
    fi
done

echo -e "\n【5】★ 已知漏洞"
for v in /var/www/*/current/.venv; do
    [ -d "$v" ] || continue
    if "$v/bin/pip-audit" --version >/dev/null 2>&1; then
        echo "  ── $v ──"
        "$v/bin/pip-audit" 2>&1 | tail -15 | sed 's/^/    /'
    fi
done
command -v pip-audit >/dev/null || echo "  ○ 未安裝 pip-audit（pip install pip-audit）"

echo -e "\n【6】systemd 服務"
systemctl list-units --type=service --all 2>/dev/null | \
  grep -iE 'gunicorn|uvicorn|python|django|fastapi' | sed 's/^/  /' || echo "  （無）"

echo -e "\n【7】★ 監聽的位址"
sudo ss -tlnp 2>/dev/null | grep -iE 'python|gunicorn|uvicorn' | \
while read -r _ _ _ _ addr _; do
    [[ "$addr" == 127.0.0.1:* ]] || [[ "$addr" == "[::1]":* ]] \
      && echo "  ✓ $addr" || echo "  ⚠⚠ $addr【應只監聽 127.0.0.1 或用 unix socket】"
done
ls -l /run/*/gunicorn.sock /run/*/uvicorn.sock 2>/dev/null | sed 's/^/  /'

echo -e "\n【8】記憶體"
ps -eo rss,args --sort=-rss 2>/dev/null | grep -iE '[g]unicorn|[u]vicorn' | head -10 | \
  awk '{printf "  %7.1f MB  %s\n", $1/1024, substr($0, index($0,$2), 70)}'
ps -eo rss,args 2>/dev/null | grep -icE '[g]unicorn|[u]vicorn' | \
  awk '{print "  worker 數量: "$1}'

echo -e "\n【9】★ PYTHONUNBUFFERED"
for s in $(systemctl list-units --type=service 2>/dev/null | \
           grep -oiE '\b\w*(gunicorn|uvicorn|myapp)\w*\.service' | sort -u); do
    systemctl show "$s" -p Environment 2>/dev/null | grep -q PYTHONUNBUFFERED \
      && echo "  ✓ $s" || echo "  ⚠ $s 缺 PYTHONUNBUFFERED=1【日誌不會即時輸出】"
done
```

---

## 常見錯誤與排錯

| 現象／錯誤 | 原因 | 解法 |
| --- | --- | --- |
| **`externally-managed-environment`** | **PEP 668 保護** | **用虛擬環境**（★ 不要 `--break-system-packages`） |
| **`sudo pip install` 後 apt 壞掉** ★★★ | 污染了系統 Python | 極難修復；**永遠不要這樣做** |
| **systemd 中找不到模組** ★ | 沒用虛擬環境的絕對路徑 | `ExecStart=/path/.venv/bin/gunicorn ...` |
| `ModuleNotFoundError` | 沒 activate / 裝到別的環境 | 用 `.venv/bin/python`；檢查 `sys.path` |
| **升級 Python 後虛擬環境壞掉** | venv 記錄了舊的 Python 路徑 | **重建 `.venv`** |
| **日誌看不到最後的錯誤** ★ | Python 緩衝 stdout | **`PYTHONUNBUFFERED=1`** |
| **應用讀到的 IP 都是 127.0.0.1** | 缺 `--proxy-headers` | 加上並限制 `--forwarded-allow-ips` |
| **重導向迴圈** | 應用以為是 http | `--proxy-headers` + Nginx 傳 `X-Forwarded-Proto` |
| socket 權限錯誤 | `SocketGroup` 不是 Nginx 的身分 | `SocketGroup=www-data`、`SocketMode=0660` |
| **worker timeout** | 請求太慢 | 調 `timeout`；**根本解法是改非同步** |
| **記憶體持續成長** | 記憶體洩漏 | `max_requests` + `max_requests_jitter` |
| **`SIGHUP` 沒有重載程式碼** ★ | `preload_app = True` | 設成 `False`；或 restart |
| 所有 worker 同時重生 | 沒設 jitter | `max_requests_jitter = 100` |
| **裝到有漏洞的套件** | 沒有雜湊驗證 | `pip-compile --generate-hashes` + `--require-hashes` |
| C 擴充編譯失敗 | 缺編譯工具 | `apt install python3-dev build-essential` |
| RHEL 上找不到 venv | 套件未安裝 | `dnf install python3-devel` |

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> $ sudo dnf install -y python3 python3-pip python3-devel gcc gcc-c++ make
>
> # ★ RHEL 8/9 也有 PEP 668 保護（較新版本）
> $ python3 -m venv .venv
>
> # ★ 多版本（AppStream 模組）
> $ sudo dnf module list python39 python311 python312
> $ sudo dnf install -y python3.12 python3.12-devel
> $ python3.12 -m venv .venv
>
> # ★★ SELinux：Nginx 要能連 unix socket
> $ sudo semanage fcontext -a -t httpd_var_run_t "/run/myapp(/.*)?"
> $ sudo restorecon -Rv /run/myapp
> $ sudo setsebool -P httpd_can_network_connect 1     # 若用 TCP
>
> # 若應用需要寫入某個目錄
> $ sudo semanage fcontext -a -t httpd_sys_rw_content_t "/var/www/myapp/shared/media(/.*)?"
> $ sudo restorecon -Rv /var/www/myapp/shared/media
> ```

### 排查

```bash
# 【1】確認用的是哪個 Python
$ /var/www/myapp/current/.venv/bin/python -c "import sys; print(sys.executable); print(sys.prefix)"
$ /var/www/myapp/current/.venv/bin/pip list

# 【2】模組找不到
$ .venv/bin/python -c "import sys; print('\n'.join(sys.path))"
$ .venv/bin/python -c "import fastapi; print(fastapi.__file__)"

# 【3】systemd 環境
$ sudo systemctl show myapp -p Environment
$ sudo systemd-run --uid=myapp --pty /var/www/myapp/current/.venv/bin/python -V

# 【4】gunicorn 狀態
$ sudo systemctl status myapp
$ sudo journalctl -u myapp -n 100 --no-pager
$ ps -ef | grep gunicorn

# 【5】直接測 socket
$ curl --unix-socket /run/myapp/gunicorn.sock http://localhost/health
$ ls -l /run/myapp/gunicorn.sock

# 【6】記憶體與 worker
$ ps -o pid,rss,etime,args -C gunicorn
$ sudo systemctl show myapp -p MemoryCurrent

# 【7】相依衝突
$ .venv/bin/pip check
$ .venv/bin/pip-audit

# 【8】重建虛擬環境（最後手段）
$ rm -rf .venv && python3 -m venv .venv
$ .venv/bin/pip install --require-hashes -r requirements.txt
```

---

## 安全性注意事項

> [!danger] 三個最重要的原則
> ```
> ① ★★★ 絕對不要 sudo pip install（會弄壞系統工具）
> ② ★★ 一定要有 lock 檔且含雜湊（pip-compile --generate-hashes / uv.lock）
> ③ ★★ 應用只監聽 127.0.0.1 或 unix socket
> ```

> [!warning] `pickle` 反序列化 = 任意程式碼執行
> ```python
> # ❌❌ 極度危險
> import pickle
> data = pickle.loads(request.data)         # ★★ 直接 RCE
> data = pickle.load(open(user_file, 'rb'))
>
> # ★ pickle 的設計就是「可以還原任意 Python 物件」
> #   包括呼叫任意函式
>
> # ✅ 用 JSON
> import json
> data = json.loads(request.data)
>
> # ✅ 需要複雜結構時用 pydantic
> from pydantic import BaseModel
> class Payload(BaseModel):
>     name: str
>     count: int
> data = Payload.model_validate_json(request.data)
> ```
> **同樣危險的還有**：`yaml.load()`（要用 `yaml.safe_load()`）、
> `eval()`、`exec()`、`os.system()`、`subprocess` 的 `shell=True`。

```python
# ❌ 命令注入
import os, subprocess
os.system(f"convert {user_input} out.png")
subprocess.run(f"convert {user_input} out.png", shell=True)

# ✅ 用列表參數（不經過 shell）
subprocess.run(['convert', user_input, 'out.png'], check=True, timeout=30)

# ✅✅ 更好：用函式庫
from PIL import Image
Image.open(user_input).save('out.png')
```

> [!warning] Django 的部署檢查
> ```bash
> $ .venv/bin/python manage.py check --deploy
> System check identified some issues:
>
> WARNINGS:
> ?: (security.W004) You have not set a value for the SECURE_HSTS_SECONDS setting.
> ?: (security.W008) Your SECURE_SSL_REDIRECT setting is not set to True.
> ?: (security.W012) SESSION_COOKIE_SECURE is not set to True.
> ?: (security.W016) You have 'django.middleware.csrf.CsrfViewMiddleware' in your
>    MIDDLEWARE, but you have not set CSRF_COOKIE_SECURE to True.
> ```
> ```python
> # settings.py（正式環境）
> DEBUG = False                            # ★★★ 絕對不能是 True
> ALLOWED_HOSTS = ['api.example.gov.tw']   # ★ 不要用 ['*']
> SECRET_KEY = os.environ['SECRET_KEY']    # ★ 從環境變數讀
>
> SECURE_SSL_REDIRECT = True
> SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')   # ★ 反向代理後面
> SESSION_COOKIE_SECURE = True
> CSRF_COOKIE_SECURE = True
> SESSION_COOKIE_HTTPONLY = True
> SESSION_COOKIE_SAMESITE = 'Lax'
> SECURE_HSTS_SECONDS = 31536000
> SECURE_CONTENT_TYPE_NOSNIFF = True
> X_FRAME_OPTIONS = 'SAMEORIGIN'
> ```
>
> **`DEBUG = True` 在正式環境的後果**：
> **任何錯誤頁都會顯示完整的 settings（含資料庫密碼與 SECRET_KEY）、
> 所有環境變數、完整的堆疊追蹤與原始碼**。

> [!tip] `pip-audit` 排程化
> ```bash
> $ .venv/bin/pip install pip-audit
> $ .venv/bin/pip-audit
> Found 2 known vulnerabilities in 2 packages
> Name       Version ID                  Fix Versions
> ---------- ------- ------------------- ------------
> jinja2     3.1.2   GHSA-h5c8-rqwp-cp95 3.1.3
> requests   2.31.0  GHSA-9wx4-h78v-vm56 2.32.0
> ```
> ```bash
> $ sudo tee /etc/cron.d/pip-audit >/dev/null <<'EOF'
> 0 7 * * 1 myapp cd /var/www/myapp/current && \
>   .venv/bin/pip-audit > /tmp/pip-audit.log 2>&1 || \
>   mail -s "【警告】Python 相依套件有已知漏洞" admin@example.gov.tw < /tmp/pip-audit.log
> EOF
> ```

---

## 速查表

### ★★★ 絕對不要

```bash
❌ sudo pip install xxx                        # 會弄壞 apt、防火牆、開機
❌ sudo pip install --break-system-packages    # 名字已經警告你了
❌ DEBUG = True（Django 正式環境）
❌ pickle.loads(使用者輸入)                     # = RCE
❌ yaml.load()（要用 safe_load）
❌ subprocess(..., shell=True) 帶使用者輸入
```

### 虛擬環境

```bash
# venv（內建）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt      # ★ 不需要 activate
.venv/bin/python app.py

# ★ uv（快 10-100 倍）
uv venv && uv pip install fastapi
uv add fastapi 'uvicorn[standard]'             # 專案模式
uv sync --frozen --no-dev                      # ★★ 正式環境
```

### 鎖定版本 ★

```bash
# pip-tools
pip-compile --generate-hashes -o requirements.txt requirements.in
pip install --require-hashes -r requirements.txt      # ★★ 驗證雜湊
pip-sync requirements.txt                              # 移除多餘的套件

# uv
uv lock
uv sync --frozen --no-dev
```

```
git：requirements.in / pyproject.toml ✅
     requirements.txt（compile 後）/ uv.lock ✅
     .venv/ ❌
```

### gunicorn / uvicorn

```python
# gunicorn.conf.py
bind = 'unix:/run/myapp/gunicorn.sock'
umask = 0o007
workers = cpu_count() * 2 + 1        # ★ 但要看記憶體
worker_class = 'uvicorn.workers.UvicornWorker'   # ASGI
timeout = 60
graceful_timeout = 30
max_requests = 1000                  # ★ 防記憶體洩漏
max_requests_jitter = 100            # ★ 避免同時重生
accesslog = '-'; errorlog = '-'      # ★ 交給 journald
preload_app = False                  # ★ True 時 SIGHUP 無法重載程式碼
forwarded_allow_ips = '127.0.0.1'    # ★ 只信任本機
```

```bash
gunicorn main:app -k uvicorn.workers.UvicornWorker -c gunicorn.conf.py
uvicorn main:app --host 127.0.0.1 --workers 4 --proxy-headers \
  --forwarded-allow-ips='127.0.0.1'
```

### systemd

```ini
[Service]
Type=notify
User=myapp
WorkingDirectory=/var/www/myapp/current
Environment="PATH=/var/www/myapp/current/.venv/bin"
Environment="PYTHONUNBUFFERED=1"          # ★★ 日誌即時輸出
ExecStart=/var/www/myapp/current/.venv/bin/gunicorn -c gunicorn.conf.py main:app
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RuntimeDirectory=myapp                    # ★ 自動建 /run/myapp

NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/www/myapp/shared/storage /run/myapp
MemoryDenyWriteExecute=false
MemoryMax=2G
```

```ini
# myapp.socket
[Socket]
ListenStream=/run/myapp/gunicorn.sock
SocketUser=myapp
SocketGroup=www-data                      # ★ Nginx 的身分
SocketMode=0660
```

### Django 正式環境檢查

```bash
.venv/bin/python manage.py check --deploy
```
```python
DEBUG = False                                                    # ★★★
ALLOWED_HOSTS = ['api.example.gov.tw']                           # ★ 不用 ['*']
SECRET_KEY = os.environ['SECRET_KEY']
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')    # ★ 代理後面
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = 31536000
```

### 排查

```bash
.venv/bin/python -c "import sys; print(sys.executable, sys.prefix)"
.venv/bin/pip check                                # 相依衝突
.venv/bin/pip-audit                                # ★ 已知漏洞
sudo journalctl -u myapp -n 100
curl --unix-socket /run/myapp/gunicorn.sock http://localhost/health
ls -l /run/myapp/gunicorn.sock                     # ★ 權限
ps -o pid,rss,args -C gunicorn
rm -rf .venv && python3 -m venv .venv              # 最後手段
```

---

## 練習題

> [!question]- 練習 1：PEP 668 與虛擬環境
> 1. `sudo pip install requests` → **看到什麼訊息？**
> 2. 讀懂它的建議
> 3. 建立虛擬環境並安裝
> 4. `.venv/bin/python -c "import sys; print(sys.prefix)"` → 與系統的差異？
> 5. **不 activate**，直接用 `.venv/bin/python` 執行 → 可以嗎？
> 6. **這對 systemd service 的寫法有什麼意義？**

> [!question]- 練習 2：雜湊驗證
> 1. 用 `pip freeze > requirements.txt` 產生檔案
> 2. 改用 `pip-compile --generate-hashes` → **檔案差在哪？**
> 3. `pip install --require-hashes -r requirements.txt`
> 4. **手動改掉其中一個雜湊值**，重新安裝 → 發生什麼事？
> 5. **這對供應鏈安全的意義是什麼？**
> 6. 若用 uv，`uv.lock` 中有對應的機制嗎？

> [!question]- 練習 3：`PYTHONUNBUFFERED`
> 1. 寫一個「印出 10 行後就崩潰」的應用
> 2. 用 systemd 啟動，**不設 `PYTHONUNBUFFERED`**
> 3. `journalctl -u xxx` → **看得到那 10 行嗎？**
> 4. 加上 `PYTHONUNBUFFERED=1`，重測
> 5. **差異是什麼？這在排查崩潰時多重要？**

> [!question]- 練習 4：workers 與記憶體
> 1. 建立一個 FastAPI 應用
> 2. `ps -o rss= -C gunicorn` 記錄單一 worker 的記憶體
> 3. 依 `(2 × 核心數) + 1` 設定 workers，觀察總記憶體
> 4. **故意載入一個大模型**（或用 `numpy` 配置大陣列）
> 5. **重測** → workers 該怎麼調？
> 6. 設定 systemd 的 `MemoryMax` 並觀察 OOM 時的行為

> [!question]- 練習 5：零停機重載
> 1. 設定 `preload_app = True`
> 2. 持續請求 + 修改程式碼 + `systemctl reload`
>    → **程式碼更新了嗎？有請求失敗嗎？**
> 3. 改成 `preload_app = False`，重測
> 4. **比較兩者的記憶體用量與重載行為**
> 5. 測試 `systemctl restart` 的中斷時間
> 6. **設計一個「零停機」的方案**

---

## 小測驗

Q1. **為什麼絕對不能 `sudo pip install`？PEP 668 做了什麼**？

Q2. **在 systemd service 中為什麼不需要（也不該用）`activate`**？

Q3. **`pip freeze` 與 `pip-compile --generate-hashes` 產生的檔案差在哪**？

Q4. **`--require-hashes` 的安全意義是什麼**？

Q5. **WSGI 與 ASGI 的差別？各該用什麼伺服器**？

Q6. **`workers` 該怎麼算？什麼情況下記憶體才是限制**？

Q7. **`preload_app = True` 的好處與代價是什麼**？

Q8. **`PYTHONUNBUFFERED=1` 為什麼重要**？

Q9. **`--proxy-headers` 與 `--forwarded-allow-ips` 為什麼要一起用**？

Q10. **Python 中哪四個函式接受使用者輸入時等同 RCE**？

> [!question]- 測驗答案
> **Q1.** 因為**系統的 Python 被大量系統工具依賴** ——
> apt/dnf 的部分元件、ufw、firewalld、cloud-init、netplan、fail2ban、
> 各種發行版的管理腳本。
> `sudo pip install` 升級了某個套件後與系統套件版本衝突，
> **可能導致 apt 壞掉、防火牆壞掉、甚至開機失敗**，而且**極難修復**
> （要手動還原每個套件到發行版的版本）。
> **PEP 668** 在系統 Python 的目錄中放一個 `EXTERNALLY-MANAGED` 標記檔，
> 讓 `pip` **直接拒絕安裝到系統環境**並提示使用虛擬環境
> （`error: externally-managed-environment`）。
> **不要用 `--break-system-packages` 繞過** —— 這個參數的名字已經說明了後果。
>
> **Q2.** 因為 **`activate` 只是一個修改 `PATH` 與提示字元的 shell 腳本** ——
> 它的效果只存在於當前的 shell session 中。
> **systemd 執行 `ExecStart` 時不會經過 shell，也不會載入任何 profile**，
> 所以 `activate` 根本不會生效。
> **正確做法是直接用虛擬環境中的絕對路徑**：
> ```ini
> ExecStart=/var/www/myapp/current/.venv/bin/gunicorn -c gunicorn.conf.py main:app
> ```
> 這與「systemd 中不能用 nvm 的 node」是完全相同的道理。
>
> **Q3.** **`pip freeze`**：輸出**當前環境中所有已安裝的套件與版本**，
> 但**分不出「直接相依」與「間接相依」，也沒有雜湊**。
> **`pip-compile --generate-hashes`**：
> 從 `requirements.in`（**只寫直接相依**）解析出完整的相依樹，
> 輸出**每個套件的精確版本 + SHA-256 雜湊 + `# via` 註解說明是誰引入的**：
> ```
> anyio==4.7.0 \
>     --hash=sha256:... \
>     # via httpx, starlette
> ```
> 這樣既能追蹤「為什麼裝了這個套件」，又能驗證內容完整性。
>
> **Q4.** **`pip install --require-hashes` 會在下載後驗證每個套件的 SHA-256**，
> 不符就**直接失敗**。
> **安全意義**：即使 **PyPI 被入侵、CDN 被竄改、或有中間人攻擊**，
> **你也不會裝到被修改過的套件** ——
> 這等同於 npm 的 `integrity` 欄位與 Composer lock 檔的雜湊。
> 這是**供應鏈安全的基本要求**，
> 對機關系統（無法快速應變供應鏈事件）尤其重要。
>
> **Q5.** **WSGI（同步）** —— 傳統的 Python Web 介面，
> 一個 worker 一次處理一個請求；用於 **Django（傳統）、Flask**；
> **用 `gunicorn`**。
> **ASGI（非同步）** —— 支援 async/await、WebSocket、長連線；
> 用於 **FastAPI、Starlette、Django (async)、Channels**；
> **用 `uvicorn`**（或 **`gunicorn -k uvicorn.workers.UvicornWorker`**，
> 取得 gunicorn 成熟的 worker 管理 + uvicorn 的 ASGI 支援 —— ★ 推薦）。
>
> **Q6.** **官方建議 `(2 × CPU 核心數) + 1`**，
> 但**必須同時檢查記憶體**：
> ```
> workers × 單一 worker 的 RSS ≤ 可用記憶體
> ```
> **記憶體成為限制的情況**：
> **當單一 worker 的 RSS 很大時** ——
> 例如載入了機器學習模型、大型的資料集、或大量的快取。
> ```
> 例：4 核心、4GB 可用
>   每 worker 200MB → CPU 限制 9 個（記憶體可容納 20 個）→ 取 9
>   每 worker 800MB → 記憶體限制 5 個（CPU 建議 9 個）→ ★ 取 5
> ```
> ```bash
> ps -o rss=,args= -C gunicorn | awk '{printf "%.0f MB\n", $1/1024}'
> ```
>
> **Q7.** **`preload_app = True`**：
> **好處** —— **先載入應用再 fork worker**，
> 利用 copy-on-write **大幅節省記憶體**（尤其是載入大模型或大量套件時），
> 而且啟動較快（只載入一次）。
> **代價** —— **`SIGHUP`（`systemctl reload`）不會重新載入程式碼**，
> 因為 master 程序中的應用已經載入了，
> **必須 `systemctl restart`（會中斷服務）**。
> **要零停機重載就設 `preload_app = False`**
> （代價是每個 worker 各自載入，記憶體較高、啟動較慢），
> 或用兩個 systemd unit 做藍綠切換。
>
> **Q8.** 因為 **Python 預設會緩衝 stdout**（當輸出不是 tty 時是全緩衝）——
> 日誌不會即時出現在 `journalctl`，
> **而且應用崩潰時，緩衝區中尚未輸出的內容會直接遺失**，
> 導致**完全看不到崩潰前的最後幾行錯誤訊息**，排查極為困難。
> ```ini
> Environment="PYTHONUNBUFFERED=1"
> ```
> **這在 Docker 容器中也是必要的設定**（同樣的原因）。
>
> **Q9.** **`--proxy-headers`** 讓 uvicorn **讀取 `X-Forwarded-For` /
> `X-Forwarded-Proto`** 來還原真實的客戶端 IP 與協定 ——
> **沒有它，應用讀到的 IP 都是 127.0.0.1（Nginx 的），
> 而且以為請求是 http（導致重導向迴圈與 Cookie 的 Secure 失效）**。
> **`--forwarded-allow-ips='127.0.0.1'`** 限制**只信任本機代理送來的這些標頭** ——
> 若設成 `'*'`（或不設），**任何人都能偽造 `X-Forwarded-For`**，
> **繞過所有依 IP 的限制與限流**。
> **兩者缺一不可**：只有前者會有安全漏洞，只有後者則標頭根本不會被讀取。
>
> **Q10.** ①**`pickle.loads()` / `pickle.load()`** ——
> pickle 的設計就是「還原任意 Python 物件」，**包括呼叫任意函式，直接 RCE**；
> 改用 `json` 或 `pydantic`。
> ②**`yaml.load()`** —— 預設的 loader 可以實例化任意物件；
> **必須用 `yaml.safe_load()`**。
> ③**`eval()` / `exec()`** —— 直接執行任意程式碼。
> ④**`os.system()` 與 `subprocess(..., shell=True)`** ——
> 命令注入；**改用 `subprocess.run(['cmd','arg'], shell=False)` 的列表參數形式**
> （不經過 shell），或直接用函式庫（例如用 `PIL` 取代呼叫 `convert`）。

---

## 延伸閱讀

- [[01-Ollama-安裝與GPU設定]] — AI 服務的 Python 環境
- [[00-OpenWebUI-索引]] — OpenWebUI 的部署
- [[17-systemd服務管理]] — systemd 加固
- [[04-Nginx-反向代理與負載平衡]] — 反向代理與 SSE 串流
- [[04-Composer-套件管理]] — PHP 端的對應概念
- [[02-npm-pnpm-yarn套件管理]] — Node 端的對應概念
