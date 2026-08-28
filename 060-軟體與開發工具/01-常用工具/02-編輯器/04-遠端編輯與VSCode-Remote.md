---
title: "遠端編輯與 VSCode Remote"
desc: "Remote-SSH、WSL、Dev Containers 與伺服器端的資源與安全考量"
aliases: [VSCode Remote, Remote-SSH, vscode-server, sshfs, WSL 開發]
tags: [群組/軟體與開發工具, 主題/編輯器, 主題/vscode, 主題/遠端]
category: 常用工具
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[02-SSH-金鑰認證與ssh-agent]]", "[[03-SSH-客戶端設定檔]]"]
updated: 2026-08-28
---

# 遠端編輯與 VSCode Remote

> [!abstract] 這篇你會學到
> - **遠端編輯的四種做法**與各自的適用場景
> - **★★★ VSCode Remote-SSH** 的完整設定（含跳板機）
> - **★★★ 它在伺服器上實際做了什麼**（很多人不知道）
> - **★★ 資源占用與正式環境的風險**
> - Remote-WSL 與 Dev Containers
> - `sshfs` / `rsync` 的替代方案
> - **★★★ 機關環境的安全考量與替代方案**

## 前置知識

- [[02-SSH-金鑰認證與ssh-agent]] — 金鑰認證
- [[03-SSH-客戶端設定檔]] — `~/.ssh/config` 與 ProxyJump
- [[02-Vim-基礎操作]] — 沒有 GUI 時的後備方案

---

## 觀念說明：四種遠端編輯方式 ★★★

| | **① 終端機編輯器** | **② VSCode Remote-SSH** | **③ sshfs 掛載** | **④ 本機編輯 + 同步** |
| --- | --- | --- | --- | --- |
| 怎麼做 | SSH 進去用 vim/nano | 在伺服器跑一個 server | 把遠端目錄掛成本機目錄 | 本機改，`rsync`/`scp` 推上去 |
| **伺服器要裝東西** | ✗ | **★★★ 要**（~200MB） | ✗ | ✗ |
| **伺服器資源占用** | ★ 極小 | **★★★ 高**（Node 程序、記憶體 300MB+） | 小 | ✗ 無 |
| 使用體驗 | ★ 純文字 | **★★★ 最好**（完整 IDE） | 中（★ 延遲高） | 中 |
| 大型專案 | ✗ | **★★ 好** | ✗ 很慢 | ★ 好 |
| **適合正式環境** | **★★★ 是** | **★★ 要評估** | ✗ | **★★★ 是** |
| **適合開發機** | ★ | **★★★ 是** | ★ | ★★ |
| 網路中斷 | ★★ 用 tmux 保住 | ★ 自動重連 | ✗✗ 卡死 | ✓ 不影響 |

```
★★★ 選擇原則：

  正式環境的伺服器      → ① 終端機編輯器（★★★ vim/nano）
                          → ★★ 或 ④ 本機改好 + 部署流程推上去

  開發／測試機          → ② VSCode Remote-SSH（★★★ 體驗最好）

  只是要看看檔案        → ① 或 ③

  ★★★★ 正式環境不建議直接編輯任何檔案
    → 應該走【版本控制 + 部署流程】
    → 見 [[01-部署共通觀念]]
```

---

## ★★★ VSCode Remote-SSH

### 它實際做了什麼

```
★★★ 很多人以為 Remote-SSH 是「像 sshfs 一樣把檔案抓回來編輯」
    → ★★★★ 不是。它在【伺服器上安裝並執行一個 Node.js server】

  ┌─────────────────┐          ┌──────────────────────────────┐
  │  你的電腦        │          │  伺服器                       │
  │                 │          │                              │
  │  VSCode UI      │◄──SSH───►│  ~/.vscode-server/           │
  │  （只負責畫面）  │  隧道     │    ├─ bin/<commit>/          │
  │                 │          │    │    └─ ★ node（~100MB）  │
  │  ★ 擴充功能分兩種│          │    ├─ extensions/            │
  │   · UI 端       │          │    │    └─ ★★ 遠端擴充在這   │
  │   · ★★ Workspace│──安裝──► │    └─ data/                  │
  │      端（跑在遠端）│         │                              │
  └─────────────────┘          │  ★★ 執行中的程序：            │
                               │    node（server 主程序）      │
                               │    node（extension host）    │
                               │    node（每個語言伺服器）      │
                               │    ★★★ 記憶體 300MB ~ 2GB    │
                               └──────────────────────────────┘

★★★ 三個關鍵事實：
  ① 檔案【留在伺服器】，不會下載到本機
  ② ★★★ 終端機、除錯、擴充功能全部【在伺服器上執行】
  ③ ★★★★ 這代表它會【消耗伺服器的 CPU 與記憶體】
```

```bash
# ★★ 在伺服器上看實際占用
$ ls -d ~/.vscode-server/bin/*/
/home/admin/.vscode-server/bin/a1b2c3d4e5f6.../

$ du -sh ~/.vscode-server/
287M    /home/admin/.vscode-server/          # ★★ 每個版本一份

$ ps -o pid,rss,etime,cmd -u "$USER" | grep -E 'vscode|[n]ode' | head
  PID   RSS     ELAPSED CMD
12345 158234    02:14:33 .../node .../server-main.js
12389 245891    02:14:30 .../node .../extensionHostProcess.js
12456  89234    02:10:12 .../node .../intelephense/...   # ★★ PHP 語言伺服器

$ ps -u "$USER" -o rss= | awk '{s+=$1} END {print s/1024 " MB"}'
487 MB                                       # ★★★ 一個使用者就快 500MB
```

> [!danger] 正式環境的三個風險 ★★★
> ```
> ① ★★★ 記憶體與 CPU
>    · 一個使用者 300MB~2GB（★ 看裝了什麼擴充）
>    · ★★ 三個人同時連 = 可能吃掉 3~6GB
>    · ★★★ 語言伺服器（intelephense / pylsp / gopls）會【掃描整個專案】
>      → 大型 repo 上 CPU 100% 好幾分鐘
>    · ★★★★ 正式的 web 伺服器記憶體吃緊時 → OOM killer 可能砍掉 php-fpm
>
> ② ★★★ 檔案 watcher
>    · ★★★★ VSCode 會遞迴 watch 整個開啟的資料夾
>    · 開了 /var/www 或 / → inotify watch 數量爆掉
>      ENOSPC: System limit for number of file watchers reached
>    · ★★ 會影響其他用 inotify 的服務（如 systemd、supervisord）
>
> ③ ★★★★ 直接編輯正式環境的檔案
>    · 改了沒經過版控 → ★ 下次部署被蓋掉
>    · ★★★ 沒有稽核記錄
>    · ★★ 存到一半服務就讀到不完整的檔案
>
> ★★★ 結論：Remote-SSH 用在【開發/測試機】，正式環境走部署流程
> ```

### 安裝與基本連線

```
★★ 前提：
  · 本機：VSCode + 「Remote - SSH」擴充（★ 或 Remote Development 套裝）
  · 伺服器：SSH 可連、glibc ≥ 2.28（★★ CentOS 7 已不支援）
           有 ~200MB 磁碟空間、不是唯讀家目錄
```

```bash
# ═══ ★★ 伺服器端的需求檢查 ═══
$ ldd --version | head -1
ldd (Ubuntu GLIBC 2.39-0ubuntu8.2) 2.39      # ★ 需要 >= 2.28

$ df -h ~ | tail -1
/dev/sda2  50G  12G  36G  25% /home          # ★ 要有 200MB+

$ uname -m
x86_64                                        # ★ 或 aarch64

$ command -v tar gzip                         # ★★ 安裝過程需要
/usr/bin/tar
/usr/bin/gzip

# ★★ 檢查家目錄可寫
$ touch ~/.write-test && rm ~/.write-test && echo OK
OK
```

> [!warning] 伺服器不支援時的訊息 ★★
> ```
> ★★ 常見錯誤：
>
>   "The remote host may not meet VS Code Server's prerequisites"
>     → ★★ glibc 太舊（CentOS 7 = glibc 2.17）
>     → ★ 解法：升級系統，或改用 vim / 本機編輯 + rsync
>
>   "Could not establish connection ... spawn ... ENOENT"
>     → ★ 伺服器沒有 tar 或 wget/curl
>
>   "Failed to install VS Code Server: no space left"
>     → ★ 家目錄滿了；或 /tmp 滿了
> ```

### `~/.ssh/config` 設定 ★★★

```
# ~/.ssh/config —— ★★ Remote-SSH 直接讀這個檔

# ═══ 基本 ═══
Host dev
    HostName dev.internal.example.gov.tw
    User admin
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes

# ═══ ★★★ 透過跳板機 ═══
Host bastion
    HostName bastion.example.gov.tw
    User jumpuser
    Port 2222
    IdentityFile ~/.ssh/id_ed25519_bastion

Host app-internal
    HostName 10.10.20.31
    User deploy
    IdentityFile ~/.ssh/id_ed25519
    ProxyJump bastion                  # ★★★ Remote-SSH 支援 ProxyJump

# ═══ ★★ 連線穩定性（★ Remote-SSH 很需要）═══
Host *
    ServerAliveInterval 30             # ★★ 每 30 秒送一次 keepalive
    ServerAliveCountMax 6              # ★ 連續 6 次沒回應才斷（3 分鐘）
    TCPKeepAlive yes
    ControlMaster auto                 # ★★★ 連線重用（★ 大幅加快）
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 10m                 # ★ 閒置 10 分鐘後才關
    Compression yes                    # ★ 慢速網路有幫助
```

```bash
# ★★★ 先在終端機測試（★ VSCode 之前一定要先測）
$ ssh app-internal 'hostname; whoami'
app01
deploy

# ★★ 看詳細的連線過程
$ ssh -vv app-internal exit 2>&1 | grep -E 'Authenticat|ProxyJump|debug1: Connect'

# ★★ ControlMaster 生效的話第二次會很快
$ time ssh app-internal true
real    0m0.089s                       # ★ 重用連線
```

> [!tip] VSCode 使用 `~/.ssh/config` 的注意事項 ★★
> ```
> ★★ ① VSCode 有自己的設定可以指定 config 檔位置：
>      settings.json → "remote.SSH.configFile": "/path/to/config"
>
> ★★★ ② Windows 上的 VSCode 用【Windows 的 OpenSSH】
>      → C:\Users\<你>\.ssh\config
>      → ★★ 不是 WSL 裡的那個！（★ 很多人卡在這）
>      → ★ 或設定用 WSL 的 ssh：
>        "remote.SSH.remotePlatform": {...}
>
> ★★ ③ ProxyJump 需要 OpenSSH 7.3+
>      → Windows 10 1809+ 內建的夠新
>      → ★ 舊版用 ProxyCommand 代替：
>        ProxyCommand ssh -W %h:%p bastion
>
> ★★ ④ 金鑰有密碼的話要用 ssh-agent
>      → ★ Windows: Start-Service ssh-agent; ssh-add
>      → ★ 否則每次連線都會跳密碼視窗
> ```

### ★★ 重要的 VSCode 設定

```jsonc
// settings.json —— ★★★ 遠端開發的關鍵設定
{
  // ═══ ★★★ 檔案 watcher（★ 最重要）═══
  "files.watcherExclude": {
    "**/.git/objects/**": true,
    "**/.git/subtree-cache/**": true,
    "**/node_modules/**": true,          // ★★★ 一定要排除
    "**/vendor/**": true,                // ★★★ PHP 專案
    "**/storage/logs/**": true,          // ★★ Laravel
    "**/storage/framework/**": true,
    "**/public/build/**": true,
    "**/dist/**": true,
    "**/.venv/**": true,
    "**/__pycache__/**": true,
    "**/target/**": true
  },

  // ═══ ★★ 搜尋排除（★ 加快搜尋、減少 CPU）═══
  "search.exclude": {
    "**/node_modules": true,
    "**/vendor": true,
    "**/dist": true,
    "**/.git": true,
    "**/storage/logs": true,
    "**/*.min.js": true
  },
  "search.followSymlinks": false,        // ★★ 避免 releases/ 符號連結重複掃描

  // ═══ ★★ 減少伺服器負擔 ═══
  "files.autoSave": "off",               // ★★★ 正式環境一定要 off！
  "git.autofetch": false,                // ★ 減少背景 SSH 活動
  "telemetry.telemetryLevel": "off",
  "extensions.autoUpdate": false,        // ★★ 避免自動更新遠端擴充
  "remote.SSH.useLocalServer": true,
  "remote.SSH.connectTimeout": 60,
  "remote.SSH.showLoginTerminal": true,  // ★★ 看得到連線過程（排錯用）

  // ═══ ★ 遠端伺服器的清理 ═══
  "remote.SSH.lockfilesInTmp": true,
  "remote.autoForwardPorts": false,      // ★★★ 見下方安全說明
  "remote.SSH.defaultExtensions": [
    "editorconfig.editorconfig"
  ]
}
```

> [!danger] `files.autoSave` 在正式環境的風險 ★★★★
> ```
> ★★★★ autoSave 預設是 "off"，但很多人開了 "afterDelay"
>
> 風險情境：
>   你在遠端編輯 /etc/nginx/nginx.conf
>   打到一半 → ★★ autoSave 存檔（語法不完整）
>   → 剛好有人跑了 systemctl reload nginx
>   → ★★★★ nginx 讀到壞掉的設定 → 服務中斷
>
> ★★★ 同樣的風險：
>   · PHP 檔案存到一半 → OPcache 讀到不完整的檔案 → 500
>   · .env 存到一半 → 應用程式讀不到變數
>
> ★★★ 正式環境：
>   ① "files.autoSave": "off"
>   ② ★★★★ 更好的做法：不要直接編輯正式環境
> ```

### ★★★ 埠轉發

```
★★ Remote-SSH 內建埠轉發（PORTS 分頁）
  → 把遠端的 port 映射到本機

  情境：伺服器上的服務只綁 127.0.0.1（★ 正確的安全設定）
    · Laravel dev server → 127.0.0.1:8000
    · Nuxt SSR         → 127.0.0.1:3000
    · Adminer          → 127.0.0.1:8080

  → ★★ 用埠轉發從本機瀏覽器連
  → ★★★ 不需要對外開放這些 port
```

```bash
# ★★ 不用 VSCode 也可以（純 SSH）
$ ssh -L 8000:127.0.0.1:8000 app-internal
#   → 本機 http://localhost:8000 = 遠端的 127.0.0.1:8000

# ★★ 多個埠
$ ssh -L 8000:127.0.0.1:8000 -L 3306:127.0.0.1:3306 app-internal

# ★★★ 只在本機監聽（★ 預設就是，不要改成 0.0.0.0）
$ ssh -L 127.0.0.1:8000:127.0.0.1:8000 app-internal
```

> [!danger] `autoForwardPorts` 的風險 ★★★
> ```
> ★★★ VSCode 預設會【自動偵測遠端開啟的 port 並轉發】
>   → 看起來很方便
>   → ★★★ 但它會把【資料庫、Redis、內部 API】都轉到你本機
>
> ★★ 兩個問題：
>   ① ★★ 你可能不小心用生產資料庫做測試
>   ② ★★★ 轉發的 port 若設成 0.0.0.0，同網段的人連得到
>
> ★★★ 建議：
>   "remote.autoForwardPorts": false      ← ★ 手動轉發需要的就好
>   "remote.portsAttributes": {
>     "3306": { "onAutoForward": "ignore" },
>     "6379": { "onAutoForward": "ignore" }
>   }
> ```

---

## Remote-WSL ★★

```
★★ WSL 是 Remote 系列中【最沒有負擔】的
  → 因為本來就在同一台機器，沒有網路延遲
  → ★★ vscode-server 裝在 WSL 的家目錄

★★★ 三個必知的重點：
```

```bash
# ═══ ★★★【1】檔案放在 Linux 檔案系統，不要放在 /mnt/c ═══
$ cd ~/projects/myapp          # ★★★ 正確（ext4，快）
$ cd /mnt/c/Users/me/myapp     # ★★★★ 錯誤（9p 協定，慢 10~20 倍）

# ★★ 實測差異
$ time (cd ~/proj && git status)
real    0m0.089s
$ time (cd /mnt/c/proj && git status)
real    0m2.341s               # ★★★ 26 倍慢

# ★★ npm install 的差異更誇張（★ 幾萬個小檔案）
#   ~/  → 30 秒     /mnt/c/ → 8 分鐘

# ═══ ★★【2】從 WSL 開啟 VSCode ═══
$ cd ~/projects/myapp
$ code .                       # ★★ 自動用 WSL 模式開啟

# ★ 從 Windows 開啟 WSL 的資料夾
#   VSCode → Ctrl+Shift+P → "WSL: Open Folder in WSL"

# ═══ ★★【3】WSL 的檔案 watcher 限制 ═══
$ cat /proc/sys/fs/inotify/max_user_watches
8192                           # ★★ 太少

$ sudo tee /etc/sysctl.d/60-inotify.conf >/dev/null <<'EOF'
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 512
EOF
$ sudo sysctl --system
$ cat /proc/sys/fs/inotify/max_user_watches
524288
```

```ini
# ★★ /etc/wsl.conf —— WSL 的設定（★ 改完要 wsl --shutdown）
[boot]
systemd=true                   # ★★★ 啟用 systemd（WSL2 0.67.6+）

[automount]
enabled = true
options = "metadata,umask=22,fmask=11"   # ★★ metadata 讓 chmod 生效

[interop]
appendWindowsPath = true       # ★ Windows 的 PATH（★ 讓 code.exe 可用）

[network]
generateResolvConf = true
```

> [!warning] WSL 的 `chmod` 問題 ★★
> ```
> ★★ 沒有 metadata 選項時：
> $ chmod 600 ~/.ssh/id_ed25519      # 在 /mnt/c 下
> $ ls -l
> -rwxrwxrwx 1 me me 411 ...          # ★★★ 沒生效！
> $ ssh server
> Permissions 0777 for 'id_ed25519' are too open.   # ★★ SSH 拒絕
>
> ★★★ 解法：
>   ① ★★★ 金鑰放在 Linux 檔案系統（~/.ssh/）
>   ② /etc/wsl.conf 加 options = "metadata"
>   ③ wsl --shutdown 重啟
> ```

---

## Dev Containers ★

```
★★ 在容器裡開發 —— 環境完全一致、不污染主機

★ 適合：
  · 團隊環境統一（★ 每個人的 PHP/Node 版本一樣）
  · 專案需要特殊的相依（★ 不想裝在主機上）
  · ★ 學習環境（用完就丟）

★★ 不適合：
  · 正式伺服器上（★ 沒必要）
  · 資源很緊的機器
```

```jsonc
// .devcontainer/devcontainer.json —— ★ LXMP 開發環境
{
  "name": "LXMP Dev",
  "dockerComposeFile": "../docker-compose.dev.yml",
  "service": "app",
  "workspaceFolder": "/var/www/html",

  "customizations": {
    "vscode": {
      "extensions": [
        "bmewburn.vscode-intelephense-client",
        "onecentlin.laravel-blade",
        "Vue.volar",
        "editorconfig.editorconfig"
      ],
      "settings": {
        "php.validate.executablePath": "/usr/local/bin/php",
        "files.autoSave": "off"
      }
    }
  },

  "forwardPorts": [8000, 3306, 5173],
  "postCreateCommand": "composer install && npm ci",
  "remoteUser": "www-data"          // ★★ 不要用 root
}
```

---

## 替代方案：sshfs 與 rsync

### sshfs ★

```bash
# ★ 安裝
$ sudo apt install -y sshfs                    # Ubuntu
$ sudo dnf install -y fuse-sshfs               # RHEL

# ★★ 掛載
$ mkdir -p ~/mnt/app
$ sshfs app-internal:/var/www/app ~/mnt/app \
    -o reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,\
follow_symlinks,idmap=user,cache_timeout=60

$ ls ~/mnt/app
current  releases  shared

# ★ 卸載
$ fusermount -u ~/mnt/app

# ★★ 寫進 /etc/fstab（★ 需要 allow_other 與 _netdev）
app-internal:/var/www/app  /home/me/mnt/app  fuse.sshfs \
  noauto,x-systemd.automount,_netdev,user,idmap=user,\
IdentityFile=/home/me/.ssh/id_ed25519,reconnect  0 0
```

> [!warning] sshfs 的三個問題 ★★
> ```
> ① ★★★ 慢 —— 每個檔案操作都是一次網路往返
>    → ls 一個有 5000 個檔案的目錄要好幾秒
>    → ★★★ git status / npm install 幾乎不能用
>
> ② ★★ 網路斷線會【卡死】
>    → 存取掛載點的程序變成 D state（不可中斷）
>    → ★ 連 ls 都會卡住，Ctrl+C 沒用
>    → ★★ 解法：fusermount -uz ~/mnt/app（延遲卸載）
>
> ③ ★★ 權限與 uid 對應
>    → 遠端的 uid 1000 ≠ 本機的 uid 1000
>    → ★ 用 idmap=user 或 -o uid=$(id -u),gid=$(id -g)
>
> ★★ 適合：偶爾看看檔案、拖拉幾個檔案
> ★★★ 不適合：實際開發
> ```

### ★★★ 本機編輯 + rsync（正式環境的正解）

```bash
#!/usr/bin/env bash
# ★★ 本機開發 → 推到測試機（★ 不是正式環境！）
set -euo pipefail

SRC="$HOME/projects/myapp/"
DST="dev:/var/www/myapp/"

rsync -avz --delete \
  --exclude='.git/' \
  --exclude='node_modules/' \
  --exclude='vendor/' \
  --exclude='.env' \
  --exclude='storage/logs/' \
  --exclude='storage/framework/' \
  --exclude='public/build/' \
  --chmod=D750,F640 \
  -e 'ssh -o ControlMaster=auto -o ControlPath=~/.ssh/cm-%r@%h:%p' \
  "$SRC" "$DST"

ssh dev 'cd /var/www/myapp && php artisan optimize:clear'
```

```bash
# ★★ 自動監看並同步（用 inotifywait）
$ sudo apt install -y inotify-tools

$ while inotifywait -r -e modify,create,delete,move \
      --exclude '(\.git|node_modules|vendor|\.swp)' "$SRC"; do
      ./sync-to-dev.sh
  done

# ★★ 或用 watchexec（更好）
$ watchexec -w "$SRC" -i 'node_modules/**' -i '.git/**' -- ./sync-to-dev.sh
```

> [!tip] 正式環境的正確做法 ★★★★
> ```
> ★★★★ 正式環境【不應該有人直接編輯檔案】
>
>   ✗ VSCode Remote-SSH 連正式機改檔案
>   ✗ vim 改正式機的程式碼
>   ✗ rsync 把本機的東西推上正式機
>
>   ✓ ★★★ git push → CI 檢查 → 建置 → 部署腳本 → 原子切換
>      → 見 [[06-部署自動化]]
>
> ★★ 唯一的例外：
>   · 緊急處理（★ 但事後要補回版控）
>   · 改設定檔（★ 但也應該進版控 + Ansible）
>
> ★★★ 判斷方式：
>   「這台機器上的檔案，能不能用一個指令從 git 重建？」
>   → 不能 = 你的部署流程有問題
> ```

---

## 完整實戰範例：透過跳板機開發

```bash
# ═══ 架構 ═══
#   你的筆電 ──► bastion.example.gov.tw:2222 ──► 10.10.20.31（dev01）
#                    （唯一對外的入口）              （內網開發機）

# ═══【1】產生並部署金鑰 ═══
$ ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_gov -C "me@laptop"
$ ssh-copy-id -i ~/.ssh/id_ed25519_gov.pub -p 2222 jumpuser@bastion.example.gov.tw

# ★★ 部署到內網機（透過跳板）
$ ssh -J jumpuser@bastion.example.gov.tw:2222 dev@10.10.20.31 \
    'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys' \
    < ~/.ssh/id_ed25519_gov.pub

# ═══ ★★★【2】~/.ssh/config ═══
$ cat >> ~/.ssh/config <<'EOF'

Host gov-bastion
    HostName bastion.example.gov.tw
    Port 2222
    User jumpuser
    IdentityFile ~/.ssh/id_ed25519_gov
    IdentitiesOnly yes

Host gov-dev
    HostName 10.10.20.31
    User dev
    IdentityFile ~/.ssh/id_ed25519_gov
    IdentitiesOnly yes
    ProxyJump gov-bastion
    ServerAliveInterval 30
    ServerAliveCountMax 6
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 10m
EOF
$ chmod 600 ~/.ssh/config

# ═══ ★★★【3】先在終端機驗證 ═══
$ ssh gov-dev 'hostname; ldd --version | head -1; df -h ~ | tail -1'
dev01
ldd (Ubuntu GLIBC 2.39-0ubuntu8.2) 2.39
/dev/sda2  50G  12G  36G  25% /home
#   ★★ glibc 夠新、磁碟夠 → 可以用 Remote-SSH

# ═══ ★★【4】提高 inotify 上限（伺服器上）═══
$ ssh gov-dev 'cat /proc/sys/fs/inotify/max_user_watches'
8192

$ ssh gov-dev 'sudo tee /etc/sysctl.d/60-inotify.conf' <<'EOF'
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 512
EOF
$ ssh gov-dev 'sudo sysctl --system | grep inotify'
fs.inotify.max_user_watches = 524288

# ═══【5】VSCode 連線 ═══
#   Ctrl+Shift+P → "Remote-SSH: Connect to Host" → gov-dev
#   → ★★ 第一次會安裝 vscode-server（約 1~2 分鐘）
#   → ★ 看得到進度：Output → Remote-SSH

# ═══ ★★【6】驗證資源占用 ═══
$ ssh gov-dev 'ps -o pid,rss,cmd -u dev | grep [n]ode'
$ ssh gov-dev "ps -u dev -o rss= | awk '{s+=\$1} END {print s/1024\" MB\"}'"
412 MB

$ ssh gov-dev 'free -h'
               total   used   free  shared  buff/cache  available
Mem:            7.8Gi  2.1Gi  3.2Gi   210Mi       2.5Gi       5.4Gi
#   ★ 還有 5.4G 可用 → OK

# ═══ ★★【7】定期清理 ═══
$ ssh gov-dev 'du -sh ~/.vscode-server; ls ~/.vscode-server/bin/'
1.2G    /home/dev/.vscode-server
a1b2c3d4  e5f6g7h8  i9j0k1l2               # ★★ 三個舊版本

$ ssh gov-dev 'ls -1dt ~/.vscode-server/bin/*/ | tail -n +2 | xargs -r rm -rf'
$ ssh gov-dev 'du -sh ~/.vscode-server'
298M    /home/dev/.vscode-server
```

```bash
# ★★ 加進 cron 自動清理（伺服器上）
$ ssh gov-dev 'crontab -l 2>/dev/null; echo "0 3 * * 0 ls -1dt ~/.vscode-server/bin/*/ | tail -n +2 | xargs -r rm -rf"' | ssh gov-dev 'crontab -'
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`prerequisites not met`** ★★★ | glibc < 2.28 | 升級系統；改用 vim / rsync |
| **`ENOSPC: file watchers`** ★★★★ | inotify 上限太低 | `fs.inotify.max_user_watches=524288`；`files.watcherExclude` |
| **連線後一直轉圈** ★★★ | 安裝 server 中／網路慢 | Output → Remote-SSH 看進度；`connectTimeout: 60` |
| **每次都要輸入密碼** ★★ | 沒用 ssh-agent | `ssh-add`；Windows 啟用 `ssh-agent` 服務 |
| **`ProxyJump` 不動** ★★ | Windows OpenSSH 太舊 | 升級；或用 `ProxyCommand ssh -W %h:%p bastion` |
| **伺服器記憶體暴增** ★★★ | 語言伺服器掃描大目錄 | 排除 `vendor`/`node_modules`；不要開 `/` |
| **本機 config 沒被讀到** ★★★ | Windows 用的是 `C:\Users\..\.ssh\config` | 改那一份；或設 `remote.SSH.configFile` |
| **磁碟被 `.vscode-server` 吃滿** ★★ | 多個版本累積 | 清舊版本；設 cron |
| **WSL 專案超慢** ★★★ | 檔案放在 `/mnt/c` | **移到 `~/`（ext4）** |
| **WSL 的 `chmod` 沒效** ★★ | 沒有 `metadata` | `/etc/wsl.conf` 加；金鑰放 Linux 檔案系統 |
| **斷線後改的東西不見** ★★ | 沒存檔 | VSCode 有 hot exit，但**不要依賴**；重要修改立刻存 |
| **改了正式環境被部署蓋掉** ★★★★ | 直接編輯正式機 | **走版控 + 部署流程** |

### 排查

```bash
# 【1】★★★ 先確認純 SSH 能連
$ ssh -vv gov-dev exit 2>&1 | tail -20

# 【2】★★ 伺服器端的需求
$ ssh gov-dev 'ldd --version|head -1; uname -m; df -h ~|tail -1; command -v tar gzip'

# 【3】★★★ inotify 用量
$ ssh gov-dev 'cat /proc/sys/fs/inotify/max_user_watches'
$ ssh gov-dev "find /proc/*/fd -lname anon_inode:inotify 2>/dev/null | wc -l"
#   ★★ 用量接近上限就要調高或排除目錄

# 【4】★★★ 資源占用
$ ssh gov-dev 'ps -o pid,rss,pcpu,etime,cmd -u $USER --sort=-rss | head -10'
$ ssh gov-dev 'free -h; uptime'

# 【5】★★ VSCode server 的日誌
$ ssh gov-dev 'ls -lt ~/.vscode-server/data/logs/ | head'
$ ssh gov-dev 'tail -50 ~/.vscode-server/data/logs/*/remoteagent.log'

# 【6】★★★ 完全重置（★ server 壞掉時）
#   VSCode: Ctrl+Shift+P → "Remote-SSH: Kill VS Code Server on Host"
#   或手動：
$ ssh gov-dev 'pkill -u $USER -f vscode-server; rm -rf ~/.vscode-server'

# 【7】★ 本機的 Remote-SSH 日誌
#   VSCode → Output 面板 → 下拉選 "Remote - SSH"

# 【8】★★ 磁碟占用
$ ssh gov-dev 'du -sh ~/.vscode-server ~/.vscode-server/*'
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★
> ```
> ① ★★★★ 正式環境不要用 Remote-SSH 直接改檔案
>      → 沒有版控、沒有稽核、下次部署被蓋掉
>      → ★ 走 git + CI + 部署腳本
>
> ② ★★★ vscode-server 是一個【長時間執行的 Node 程序】
>      → 有自己的 CVE 歷史
>      → ★★ 定期更新；不用的時候 Kill Server
>      → ★★★ 正式環境不要留著它跑
>
> ③ ★★★ 遠端擴充功能在伺服器上執行任意程式碼
>      → ★★ 只裝必要的；審查來源
>      → "extensions.autoUpdate": false（★ 避免自動拉新版）
>
> ④ ★★★ autoForwardPorts 會把資料庫轉到你本機
>      → ★★ 關掉，需要什麼手動轉發
>      → ★ 轉發只綁 127.0.0.1，不要 0.0.0.0
>
> ⑤ ★★ 跳板機不要放私鑰
>      → ★★★ 用 ProxyJump（金鑰只在你本機）
>      → ★★★★ 不要用 ssh -A（agent forwarding）
>        → 跳板機被入侵 = 攻擊者可以用你的 agent 連任何機器
> ```

```bash
# ★★★ 限制 Remote-SSH 只能連特定機器（sshd 端）
$ sudo tee -a /etc/ssh/sshd_config.d/10-vscode.conf >/dev/null <<'EOF'
# ★★ 只允許開發群組使用（正式機不加這段 = 不允許）
Match Group developers
    PermitTTY yes
    AllowTcpForwarding local           # ★★ 只允許本機端轉發
    X11Forwarding no
    PermitTunnel no

# ★★★ 部署帳號不允許互動與轉發
Match User deploy
    AllowTcpForwarding no
    PermitTTY no
    ForceCommand /usr/local/bin/deploy-shell
EOF
$ sudo sshd -t && sudo systemctl reload ssh

# ★★ 稽核誰在跑 vscode-server
$ sudo ps -eo user,pid,rss,etime,cmd | grep [v]scode-server
$ sudo ls -ld /home/*/.vscode-server 2>/dev/null

# ★★★ 正式機上偵測並告警
$ sudo tee /usr/local/bin/check-remote-editors >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★ 正式環境不該有人用 Remote-SSH
FOUND=$(ps -eo user,pid,cmd | grep -E '[v]scode-server|[s]shfs' || true)
if [ -n "$FOUND" ]; then
    echo "⚠ 偵測到遠端編輯工具："
    echo "$FOUND"
    logger -t security -p auth.warning "remote editor detected: $FOUND"
    exit 1
fi
echo "✓ 沒有遠端編輯工具"
EOF
$ sudo chmod +x /usr/local/bin/check-remote-editors
$ sudo /usr/local/bin/check-remote-editors
```

```bash
# ★★★ 不要用 agent forwarding
$ ssh -A bastion            # ★★★★ 危險！
#   → 跳板機的 root 可以用你的 agent 連任何機器
#   → 攻擊者只要找到 $SSH_AUTH_SOCK 就能冒用你

$ ssh -J bastion target     # ★★★ 正確：ProxyJump
#   → 認證在【你本機】完成，跳板機只是轉發加密流量
#   → ★ 跳板機看不到你的金鑰、也用不了

# ★★ 全域停用 agent forwarding
$ cat >> ~/.ssh/config <<'EOF'
Host *
    ForwardAgent no
EOF
```

---

## 速查表

### ★★★ 選哪一個

```
正式環境伺服器   → ★★★ vim/nano，或本機改 + 部署流程
開發／測試機     → ★★★ VSCode Remote-SSH
WSL             → ★★★ Remote-WSL（★ 檔案放 ~/ 不要放 /mnt/c）
偶爾看檔案       → sshfs
團隊環境統一     → Dev Containers
```

### `~/.ssh/config` 關鍵

```
Host dev
    HostName 10.10.20.31
    User dev
    ProxyJump bastion          # ★★★ 跳板機（★ 不要用 ssh -A）
Host *
    ServerAliveInterval 30     # ★★ 保持連線
    ControlMaster auto         # ★★★ 連線重用
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 10m
    ForwardAgent no            # ★★★ 安全
```

### ★★★ 伺服器端必調

```bash
# inotify 上限
sudo tee /etc/sysctl.d/60-inotify.conf <<'EOF'
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 512
EOF
sudo sysctl --system

# 清理舊版 server
ls -1dt ~/.vscode-server/bin/*/ | tail -n +2 | xargs -r rm -rf
```

### ★★★ VSCode 必設

```jsonc
"files.watcherExclude": { "**/node_modules/**": true, "**/vendor/**": true },
"search.exclude":       { "**/node_modules": true, "**/vendor": true },
"files.autoSave": "off",              // ★★★★ 正式環境必須
"remote.autoForwardPorts": false,     // ★★★ 安全
"extensions.autoUpdate": false,
"search.followSymlinks": false
```

### 排查

```bash
ssh -vv host exit                          # ★★ 先確認 SSH 通
ssh host 'ldd --version|head -1'           # ★★ glibc >= 2.28
ssh host 'ps -o rss,cmd -u $USER|grep [n]ode'   # ★★ 資源
ssh host 'cat /proc/sys/fs/inotify/max_user_watches'
ssh host 'pkill -f vscode-server; rm -rf ~/.vscode-server'   # ★★ 重置
# VSCode: Ctrl+Shift+P → "Kill VS Code Server on Host"
```

### 埠轉發

```bash
ssh -L 8000:127.0.0.1:8000 dev        # ★★ 手動轉發
# ★★★ 不要轉發資料庫到 0.0.0.0
```

### WSL

```
★★★ 檔案放 ~/（ext4），不要放 /mnt/c（★ 慢 10~20 倍）
/etc/wsl.conf: [boot] systemd=true
               [automount] options="metadata"   ★★ 讓 chmod 生效
wsl --shutdown 後生效
```

---

## 練習題

> [!question]- 練習 1：Remote-SSH 基本 ★★
> 1. 設定 `~/.ssh/config`，**先用終端機確認能連**
> 2. VSCode 連上去，**觀察 Output → Remote-SSH 的安裝過程**
> 3. **`ssh host 'du -sh ~/.vscode-server'`** → 多大？
> 4. **`ps -o rss,cmd -u $USER | grep node`** → 用了多少記憶體？
> 5. 開一個大專案（含 `node_modules`）→ 記憶體變多少？
> 6. **加上 `files.watcherExclude` 再測一次**

> [!question]- 練習 2：跳板機 ★★★
> 1. 設定 `ProxyJump` 連內網機
> 2. **`ssh -vv` 觀察連線過程**，確認是兩段
> 3. VSCode 用同一個 Host 連
> 4. **改用 `ssh -A`（agent forwarding）** → 在跳板機上 `echo $SSH_AUTH_SOCK`
> 5. **從跳板機用你的 agent 連目標機** → 成功了嗎？
> 6. **這代表什麼安全風險？為什麼 ProxyJump 比較安全？**

> [!question]- 練習 3：inotify ★★★
> 1. `cat /proc/sys/fs/inotify/max_user_watches` → 目前值？
> 2. **在 VSCode 開一個含 `node_modules` 的大專案**
> 3. **`find /proc/*/fd -lname anon_inode:inotify | wc -l`** → 用了多少？
> 4. 故意把上限調到 1024 → 開專案會怎樣？
> 5. **調回 524288 並加上 `watcherExclude`**
> 6. 比較兩者的記憶體與 CPU

> [!question]- 練習 4：WSL 效能 ★★★
> 1. 在 `/mnt/c/` 和 `~/` 各 clone 同一個 repo
> 2. **`time git status`** 兩邊各測 → 差幾倍？
> 3. **`time npm ci`** → 差幾倍？
> 4. 在 `/mnt/c/` 下 `chmod 600` 一個檔案 → `ls -l` 生效嗎？
> 5. **改 `/etc/wsl.conf` 加 `metadata`，`wsl --shutdown` 後再試**
> 6. **結論：SSH 金鑰該放哪裡？**

> [!question]- 練習 5：正式環境的判斷 ★★★
> 1. 列出你環境中所有「有人會直接編輯」的伺服器
> 2. **對每一台問：「檔案能不能用一個指令從 git 重建？」**
> 3. 不能的話，缺什麼？
> 4. **寫一個 `check-remote-editors` 腳本並在正式機跑**
> 5. 用 sshd 的 `Match Group` 限制誰能用埠轉發
> 6. **`sudo sshd -T | grep -i forward` 驗證**

---

## 小測驗

Q1. **VSCode Remote-SSH 在伺服器上實際做了什麼**？跟 sshfs 差在哪？

Q2. **為什麼正式環境不建議用 Remote-SSH**？（至少三個理由）

Q3. **`ENOSPC: System limit for number of file watchers reached` 是什麼**？兩個層面的解法？

Q4. **`files.autoSave` 在遠端編輯設定檔時為什麼危險**？

Q5. **`ssh -A` 和 `ssh -J` 的差別**？為什麼後者安全？

Q6. **WSL 的專案為什麼不能放在 `/mnt/c`**？大概差幾倍？

Q7. **WSL 裡 `chmod 600` 沒生效，原因與兩個解法**？

Q8. **`remote.autoForwardPorts` 為什麼建議關掉**？

Q9. **`~/.vscode-server` 越來越大怎麼辦**？

Q10. **判斷一台伺服器「該不該讓人直接編輯」的標準是什麼**？

> [!question]- 測驗答案
> **Q1.** **★★★ Remote-SSH 在伺服器上安裝並執行一個 Node.js server**
> （`~/.vscode-server/`，約 200MB），
> **檔案完全留在伺服器上不會下載到本機**，
> 你本機的 VSCode **只負責畫面**，
> 而**終端機、除錯器、語言伺服器、擴充功能全部在伺服器上執行**。
> **和 sshfs 的差別**：
> sshfs 是把遠端目錄**掛載成本機檔案系統**，
> 所有操作（開檔、`ls`、搜尋）都是**逐個檔案的網路往返** ——
> 所以 `git status` 或 `npm install` 慢到不能用，而且斷線會讓程序卡在 D state。
> Remote-SSH 因為運算在伺服器端，**大型專案的體驗好很多**，
> 但代價是**吃伺服器的 CPU 與記憶體**（一個使用者 300MB~2GB）。
>
> **Q2.** **至少四個理由**：
> ①**★★★ 資源占用** —— 一個使用者 300MB~2GB，
> 語言伺服器（intelephense/pylsp）**會掃描整個專案**，CPU 可能滿載好幾分鐘；
> 正式的 web 伺服器記憶體吃緊時，**OOM killer 可能砍掉 php-fpm**；
> ②**★★★★ 檔案 watcher** —— VSCode 遞迴 watch 整個開啟的資料夾，
> inotify 數量爆掉會影響**其他用 inotify 的服務**（systemd、supervisord）；
> ③**★★★★ 直接編輯正式環境的檔案本身就是問題** ——
> 沒有版控、沒有稽核記錄、**下次部署會被蓋掉**、
> 存到一半服務可能讀到不完整的檔案；
> ④**★★ vscode-server 是長時間執行的 Node 程序**，有自己的 CVE 歷史，
> 正式機上多一個對外服務就是多一個攻擊面。
> **正確做法**：正式環境走 git + CI + 部署腳本。
>
> **Q3.** **inotify 的 watch 數量超過核心上限**。
> Linux 的 `fs.inotify.max_user_watches` 預設常常只有 **8192**，
> 而 VSCode 開一個含 `node_modules` 的專案就可能需要**幾十萬個 watch**。
> **兩個層面的解法**：
> ①**★★★ 系統層：調高上限**
> ```bash
> sudo tee /etc/sysctl.d/60-inotify.conf <<'EOF'
> fs.inotify.max_user_watches = 524288
> fs.inotify.max_user_instances = 512
> EOF
> sudo sysctl --system
> ```
> ②**★★★ 應用層：減少需要 watch 的目錄**（更治本）
> ```jsonc
> "files.watcherExclude": {
>   "**/node_modules/**": true, "**/vendor/**": true,
>   "**/storage/logs/**": true, "**/dist/**": true
> },
> "search.followSymlinks": false
> ```
> **兩個都要做** —— 只調上限的話，記憶體還是被吃掉了。
>
> **Q4.** 因為 **autoSave 會在你「打到一半」時就把檔案寫入磁碟**，
> 而設定檔在那個瞬間是**語法不完整的**。
> **風險情境**：
> 你在編輯 `/etc/nginx/nginx.conf`，autoSave 存了一個少了 `}` 的版本，
> 這時剛好有人（或 cron、或 certbot 的 renew hook）跑了
> `systemctl reload nginx` → **nginx 讀到壞掉的設定 → 服務中斷**。
> 同類風險：PHP 檔案存到一半 → **OPcache 快取了不完整的檔案 → 500**；
> `.env` 存到一半 → 應用程式讀不到變數。
> **解法**：`"files.autoSave": "off"`（這其實是預設值，但很多人開了）。
> **更好的解法**：**不要直接編輯正式環境**。
>
> **Q5.** **`ssh -A`（agent forwarding）** 把你本機的 **SSH agent socket 轉發到跳板機**，
> 讓跳板機上的程序可以**使用你的私鑰進行認證**。
> **`ssh -J`（ProxyJump）** 則是**認證完全在你本機完成** ——
> 跳板機只是**轉發加密的 TCP 流量**，它看不到也用不了你的金鑰。
> **`-A` 的風險**：
> 跳板機上的 root（或任何能讀你的 `$SSH_AUTH_SOCK` 的程序）
> **可以冒用你的身分連到任何信任你金鑰的機器** ——
> 而且你不會知道。跳板機通常是多人共用、對外暴露的機器，
> **正是最不該信任的地方**。
> **建議**：`~/.ssh/config` 全域設 `ForwardAgent no`，一律用 `ProxyJump`。
>
> **Q6.** 因為 **`/mnt/c` 走的是 9p 協定**（WSL 跨檔案系統的橋接層），
> **每個檔案操作都要經過一層轉譯**，
> 而 `~/`（WSL 的家目錄）是**原生的 ext4**。
> **實測差距約 10~26 倍**：
> ```
> git status:   ~/ 0.09 秒   vs   /mnt/c 2.34 秒     ★ 26 倍
> npm install:  ~/ 30 秒     vs   /mnt/c 8 分鐘      ★ 16 倍
> ```
> 差距在**大量小檔案**的操作上最明顯（`node_modules` 動輒幾萬個檔案）。
> **建議**：專案一律放在 `~/projects/`，
> 需要從 Windows 存取時用 `\\wsl$\Ubuntu\home\me\projects`（反向存取比較快）。
> **從 WSL 開啟**：`cd ~/projects/app && code .`。
>
> **Q7.** **原因：`/mnt/c` 預設沒有掛載 `metadata` 選項** ——
> Windows 的 NTFS 沒有 Unix 權限位元，
> WSL 只好把所有檔案都顯示成 `0777`，`chmod` 等於沒作用。
> **後果**：SSH 會拒絕使用權限太開放的金鑰：
> ```
> Permissions 0777 for 'id_ed25519' are too open.
> ```
> **兩個解法**：
> ①**★★★ 最好的做法：金鑰（和專案）放在 Linux 檔案系統** `~/.ssh/`；
> ②**掛載時加 `metadata`**：
> ```ini
> # /etc/wsl.conf
> [automount]
> options = "metadata,umask=22,fmask=11"
> ```
> 然後在 PowerShell 執行 **`wsl --shutdown`** 讓它重新掛載。
> 加了 metadata 之後 `chmod` 才會真的存進 NTFS 的擴充屬性。
>
> **Q8.** 因為它會**自動偵測遠端開啟的 port 並轉發到你本機** ——
> 包括**你沒打算轉發的**：MySQL 3306、Redis 6379、內部 API。
> **兩個問題**：
> ①**★★ 你可能不小心用生產資料庫做測試** ——
> 本機的工具連 `localhost:3306` 連到的其實是遠端的正式資料庫；
> ②**★★★ 如果轉發綁定在 `0.0.0.0`，同網段的人也連得到** ——
> 等於把內網服務暴露到你所在的網段。
> **建議**：
> ```jsonc
> "remote.autoForwardPorts": false,
> "remote.portsAttributes": {
>   "3306": { "onAutoForward": "ignore" },
>   "6379": { "onAutoForward": "ignore" }
> }
> ```
> 需要什麼**手動轉發**，而且確保只綁 `127.0.0.1`。
>
> **Q9.** **`~/.vscode-server/bin/` 下每個 VSCode 版本都留一份**（各約 200-300MB），
> 用久了會累積好幾 GB。
> **清理**：
> ```bash
> # ★ 保留最新的，刪掉其他
> ls -1dt ~/.vscode-server/bin/*/ | tail -n +2 | xargs -r rm -rf
> ```
> **自動化**（cron，每週日凌晨三點）：
> ```
> 0 3 * * 0 ls -1dt ~/.vscode-server/bin/*/ | tail -n +2 | xargs -r rm -rf
> ```
> **完全重置**（server 壞掉時）：
> VSCode 的 `Ctrl+Shift+P` → **「Remote-SSH: Kill VS Code Server on Host」**，
> 或手動 `pkill -f vscode-server && rm -rf ~/.vscode-server`
> （下次連線會重新安裝）。
> `~/.vscode-server/data/logs/` 也會累積，一併清掉。
>
> **Q10.** **★★★★ 判斷標準：「這台機器上的檔案，能不能用一個指令從 git 完整重建？」**
> **能** → 這是一台可拋棄的機器，直接編輯的損害有限
> （但改動仍然會在下次部署時被蓋掉，所以還是不該改）。
> **不能** → **你的部署流程有問題** ——
> 代表機器上有「只存在於這台機器」的狀態，
> 這台機器變成了不可替代的**寵物**而不是可替換的**牲口**。
> **正式環境的三條原則**：
> ①程式碼一律走 **git → CI 檢查 → 建置 → 部署腳本 → 原子切換**；
> ②設定檔也要進版控（或用 Ansible 管理），
> 不是手改 `/etc/nginx/`；
> ③**唯一的例外是緊急處理**，但事後必須把改動補回版控，
> 否則下一次部署就會回退你的緊急修復。
> 可以在正式機上跑一個 `check-remote-editors` 腳本偵測
> `vscode-server` / `sshfs` 並告警。

---

## 延伸閱讀

- [[02-SSH-金鑰認證與ssh-agent]] — 金鑰與 agent
- [[03-SSH-客戶端設定檔]] — `ProxyJump` 完整說明
- [[02-Vim-基礎操作]] — 沒有 GUI 時的方案
- [[02-rsync-同步與備份]] — 本機編輯 + 同步
- [[01-部署共通觀念]] — 為什麼正式環境不該直接編輯
- [[06-部署自動化]] — 正確的做法
- [[01-tmux-工作階段管理]] — 保住斷線的工作階段
