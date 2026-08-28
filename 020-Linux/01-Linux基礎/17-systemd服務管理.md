---
title: "systemd 服務管理"
desc: "systemctl 操作、unit 檔結構與自訂服務的寫法"
aliases: [systemctl, systemd, unit, service, daemon]
tags: [群組/Linux, linux/基礎, 主題/systemd]
category: Linux基礎
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[10-程序管理與訊號]]"]
updated: 2026-08-27
---

# systemd 服務管理

> [!abstract] 這篇你會學到
> - 分清楚 **`start` 與 `enable`**、**`restart` 與 `reload`**——這兩組差別每天都會用到
> - 從零寫出一個穩定的自訂服務 unit，含自動重啟、資源限制與安全強化
> - 用 **`systemctl edit`** 修改套件提供的服務，而不會在升級時被覆蓋
> - 用 **`MemoryMax=`** 讓失控的服務只殺死自己，不拖垮整台機器
> - 用 `systemd-analyze security` 量化並改善服務的安全評分
> - 排查「服務起不來」的固定流程

## 前置知識

- [[10-程序管理與訊號]]

---

## 觀念說明

### systemd 是什麼

systemd 是現代 Linux 的 **PID 1**——開機後第一個啟動的程序，
負責啟動與監督所有其他服務。

```bash
ps -p 1 -o pid,comm,args
```

```
    PID COMMAND         COMMAND
      1 systemd         /sbin/init
```

它接管了過去分散在多個工具的職責：

| 職責 | 舊做法 | systemd |
| --- | --- | --- |
| 服務啟動 | SysV init script | **unit 檔** |
| 排程 | `cron` | **timer unit**（見 [[18-排程工作]]） |
| 日誌 | `syslog` | **journald**（見 [[19-日誌系統]]） |
| 掛載 | `fstab` | mount unit（仍讀 fstab） |
| 網路 | `ifupdown` | `systemd-networkd` |
| DNS | `resolv.conf` | `systemd-resolved` |
| 資源限制 | `ulimit` | **cgroup 屬性** |

### Unit 的類型

| 副檔名 | 用途 | 例子 |
| --- | --- | --- |
| **`.service`** | **服務** | `nginx.service` |
| `.timer` | 排程 | `logrotate.timer` |
| `.socket` | 通訊端啟動 | `docker.socket` |
| `.mount` | 掛載點 | `var-lib-mysql.mount` |
| `.target` | 一組 unit 的集合 | `multi-user.target` |
| `.path` | 監看檔案變化 | `cups.path` |

```bash
systemctl list-units --type=service --state=running
systemctl list-unit-files --type=service --state=enabled
systemctl list-units --type=timer
```

### Unit 檔的三個位置（優先度由高到低）

```
/etc/systemd/system/          ← 你自己寫的、優先度最高
/run/systemd/system/          ← 執行期產生的
/usr/lib/systemd/system/      ← 套件安裝的（不要手動改！）
```

> [!danger] 不要直接編輯 `/usr/lib/systemd/system/` 底下的檔案
> 那是套件管理的地盤，**下次套件升級時你的修改會被覆蓋**，
> 而且是無聲無息地覆蓋。
>
> 正確做法有兩種：
> ```bash
> sudo systemctl edit nginx           # ✓ 建立 drop-in 覆寫（推薦）
> sudo systemctl edit --full nginx    # ✓ 完整複製到 /etc/ 後編輯
> ```

---

## 基礎操作

### 最常用的指令

```bash
sudo systemctl start nginx            # 啟動（立即，但重開機不會自動起）
sudo systemctl stop nginx             # 停止
sudo systemctl restart nginx          # 重啟（會中斷連線）
sudo systemctl reload nginx           # 重載設定（不中斷連線）
sudo systemctl reload-or-restart nginx # 支援 reload 就 reload，否則 restart
sudo systemctl enable nginx           # 設定開機自動啟動（但現在不會啟動）
sudo systemctl disable nginx          # 取消開機自動啟動
sudo systemctl enable --now nginx     # ✓ 同時 enable + start
sudo systemctl disable --now nginx    # 同時 disable + stop
systemctl status nginx                # 狀態與最近日誌
systemctl is-active nginx             # 只回傳 active/inactive（腳本用）
systemctl is-enabled nginx            # 只回傳 enabled/disabled
sudo systemctl mask nginx             # 徹底禁用（連手動 start 都不行）
sudo systemctl unmask nginx           # 解除
```

> [!danger] `start` 和 `enable` 是兩件完全不同的事
> | 指令 | 現在啟動？ | 重開機後啟動？ |
> | --- | --- | --- |
> | `start` | ✅ | ❌ |
> | `enable` | ❌ | ✅ |
> | **`enable --now`** | ✅ | ✅ |
>
> **「裝好服務、`start` 了、測試都正常，結果重開機後服務沒起來」**
> 是最常見的疏漏之一。永遠用 `enable --now`。
>
> 檢查有沒有漏掉：
> ```bash
> # 目前在跑但沒設定開機啟動的服務
> comm -23 \
>   <(systemctl list-units --type=service --state=running --no-legend | awk '{print $1}' | sort) \
>   <(systemctl list-unit-files --type=service --state=enabled --no-legend | awk '{print $1}' | sort)
> ```

> [!danger] `restart` 會中斷連線，`reload` 不會
> | | `restart` | `reload` |
> | --- | --- | --- |
> | 做什麼 | **殺掉再重開** | 送 `SIGHUP`，程序自己重讀設定 |
> | 現有連線 | **全部中斷** | 保留 |
> | 適用 | 換了執行檔、改了啟動參數 | **只改了設定檔** |
>
> 改 Nginx 設定用 `reload`，正在下載大檔的使用者不會被踢掉。
> 用 `restart` 他們就得重來。
>
> **但不是每個服務都支援 `reload`**——unit 檔要有 `ExecReload=`：
> ```bash
> systemctl cat nginx | grep ExecReload
> ```
> ```
> ExecReload=/usr/sbin/nginx -g 'daemon on; master_process on;' -s reload
> ```
> 沒有的話 `reload` 會報錯，用 `reload-or-restart` 較安全。

> [!tip] `mask` 是比 `disable` 更強的禁用
> ```bash
> sudo systemctl disable apache2      # 不開機啟動，但別的服務或你仍可 start
> sudo systemctl mask apache2         # 建立 → /dev/null 的連結，完全無法啟動
> ```
> ```bash
> sudo systemctl start apache2
> ```
> ```
> Failed to start apache2.service: Unit apache2.service is masked.
> ```
> 用在「這個服務絕對不能跑」的情況，例如裝了 Nginx 之後要確保
> Apache 不會因為相依關係被拉起來搶 80 埠。

### 讀懂 `systemctl status`

```bash
systemctl status nginx
```

```
● nginx.service - A high performance web server and a reverse proxy server
     Loaded: loaded (/usr/lib/systemd/system/nginx.service; enabled; preset: enabled)
     Active: active (running) since Wed 2026-08-27 09:12:03 CST; 8h ago
       Docs: man:nginx(8)
    Process: 880 ExecStartPre=/usr/sbin/nginx -t -q -g daemon on; (code=exited, status=0/SUCCESS)
   Main PID: 891 (nginx)
      Tasks: 3 (limit: 2273)
     Memory: 12.4M (peak: 18.2M)
        CPU: 2.104s
     CGroup: /system.slice/nginx.service
             ├─891 "nginx: master process /usr/sbin/nginx"
             ├─892 "nginx: worker process"
             └─893 "nginx: worker process"

8月 27 09:12:03 lab01 systemd[1]: Starting nginx.service...
8月 27 09:12:03 lab01 systemd[1]: Started nginx.service.
```

| 欄位 | 判讀 |
| --- | --- |
| `Loaded: ... enabled` | **有沒有設定開機啟動** |
| `Active: active (running)` | 目前狀態 |
| `Active: failed` | **失敗了，往下看日誌** |
| `Main PID` | 主程序 |
| `Tasks: 3 (limit: 2273)` | 執行緒數與上限 |
| `Memory: 12.4M (peak: 18.2M)` | **記憶體用量與峰值** |
| `CGroup` | **這個服務底下所有程序** |
| 最後幾行 | 最近的日誌 |

常見的 `Active` 狀態：

| 狀態 | 意義 |
| --- | --- |
| `active (running)` | 正常執行中 |
| `active (exited)` | 執行完就結束了（`Type=oneshot` 的正常狀態） |
| `active (waiting)` | 等待事件（socket/timer） |
| `inactive (dead)` | 沒在跑 |
| **`failed`** | **啟動或執行失敗** |
| `activating` / `deactivating` | 過渡中 |

### 查看與追蹤

```bash
systemctl cat nginx                        # ✓ 看完整 unit 檔（含 drop-in）
systemctl show nginx                       # 所有生效中的屬性
systemctl show nginx -p MemoryMax,Restart  # 只看特定屬性
systemctl list-dependencies nginx          # 相依關係樹
systemctl list-dependencies --reverse nginx # 誰相依於它
systemctl --failed                         # ✓ 所有失敗的服務
sudo systemctl daemon-reload               # 改過 unit 檔後必須執行
```

> [!warning] 改完 unit 檔一定要 `daemon-reload`
> systemd 把 unit 檔載入記憶體，你改了檔案它不會自動知道。
> ```
> Warning: The unit file, source configuration file or drop-ins of
> nginx.service changed on disk. Run 'systemctl daemon-reload' to reload units.
> ```
> **順序是：改檔案 → `daemon-reload` → `restart`。**

```bash
sudo journalctl -u nginx -f                # 即時追蹤該服務日誌
sudo journalctl -u nginx --since "10 min ago"
sudo journalctl -u nginx -p err            # 只看錯誤等級以上
sudo journalctl -u nginx -b                # 只看本次開機
sudo journalctl -xeu nginx                 # ✓ 排查失敗最常用
```

`-xeu` 拆解：`-x` 加上說明文字、`-e` 跳到最後、`-u` 指定服務。

---

## 進階用法：寫一個自訂服務

### Unit 檔的基本結構

```ini
[Unit]
Description=My Application API Server
Documentation=https://example.com/docs
After=network-online.target postgresql.service
Wants=network-online.target
Requires=postgresql.service

[Service]
Type=simple
User=myapp
Group=myapp
WorkingDirectory=/opt/myapp
EnvironmentFile=/etc/myapp/env
ExecStartPre=/opt/myapp/bin/preflight-check
ExecStart=/opt/myapp/bin/server --config /etc/myapp/config.yaml
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

### `[Unit]` 區塊：相依關係

| 指令 | 意義 |
| --- | --- |
| `Description=` | 一行說明（`systemctl status` 會顯示） |
| **`After=`** | **在這些 unit 之後啟動**（只管順序） |
| `Before=` | 在這些之前啟動 |
| **`Requires=`** | **強相依**：對方失敗，我也停止 |
| **`Wants=`** | **弱相依**：對方失敗，我照樣跑（**建議預設用這個**） |
| `BindsTo=` | 比 Requires 更強：對方停止我立刻停止 |
| `PartOf=` | 對方 restart/stop 時我跟著 |
| `Conflicts=` | 互斥，不能同時跑 |

> [!warning] `After=` 和 `Requires=` 是兩個獨立的概念
> - `After=` 只管**啟動順序**，不管對方有沒有成功
> - `Requires=` 只管**相依關係**，不管順序
>
> 想要「資料庫起來之後再啟動我，而且資料庫掛了我也停」：
> ```ini
> Requires=postgresql.service
> After=postgresql.service
> ```
> **兩個都要寫。** 只寫 `Requires=` 的話兩者可能同時啟動，
> 你的服務會因為連不上資料庫而失敗。

> [!tip] `network-online.target` vs `network.target`
> ```ini
> After=network.target           # ✗ 只代表「網路子系統已啟動」，可能還沒拿到 IP
> After=network-online.target    # ✓ 代表「網路真的可用了」
> Wants=network-online.target    # ← 必須同時寫，否則該 target 不會被啟動
> ```
> 需要綁定特定 IP 或連外的服務，一定要用 `network-online.target`
> **並且加上 `Wants=`**，否則那個 target 根本不會被拉起來。

### `[Service]` 區塊：Type 的選擇

| Type | 意義 | 適用 |
| --- | --- | --- |
| **`simple`** | ExecStart 啟動的程序就是主程序（**預設**） | 大部分現代程式 |
| `exec` | 同 simple，但等 exec 成功才算啟動完成 | 比 simple 更精確 |
| **`forking`** | 程式會 fork 到背景，父程序退出 | 傳統 daemon（需搭配 `PIDFile=`） |
| **`oneshot`** | 執行完就結束 | 一次性任務、搭配 timer |
| `notify` | 程式會主動通知 systemd 已就緒 | 支援 sd_notify 的程式 |
| `idle` | 等其他工作都完成才執行 | 避免干擾開機訊息 |

> [!danger] Type 選錯是「服務啟動失敗」的頭號原因
> 症狀：
> - 程式明明在跑，`systemctl status` 卻顯示 `failed`
> - 或者 systemd 一直重複啟動同一個服務
>
> **關鍵判斷**：你的程式會不會自己 fork 到背景？
> ```ini
> # 程式在前景執行（現代做法，大多數如此）
> Type=simple
> ExecStart=/opt/myapp/server
>
> # 程式會 fork 到背景（傳統 daemon）
> Type=forking
> PIDFile=/run/myapp/myapp.pid
> ExecStart=/opt/myapp/server --daemonize
> ```
>
> **最好的做法是讓程式不要 fork**——大多數程式都有
> `--foreground`、`-D`、`--no-daemon` 之類的選項。
> 交給 systemd 管理背景化就好。

### 執行身分與環境

```ini
[Service]
User=myapp
Group=myapp
WorkingDirectory=/opt/myapp
UMask=0027

# 單一環境變數
Environment="NODE_ENV=production"
Environment="PORT=3000"

# 從檔案讀取（推薦，機密放這裡）
EnvironmentFile=/etc/myapp/env
EnvironmentFile=-/etc/myapp/env.local     # 前面加 - 代表檔案不存在也沒關係
```

`/etc/myapp/env`：

```
NODE_ENV=production
PORT=3000
DATABASE_URL=postgres://myapp:secret@localhost/myapp
```

```bash
sudo chmod 600 /etc/myapp/env
sudo chown root:myapp /etc/myapp/env
sudo chmod 640 /etc/myapp/env      # 讓服務帳號讀得到
```

> [!warning] `EnvironmentFile` 的格式不是 shell 腳本
> ```
> PORT=3000                  # ✓
> export PORT=3000           # ✗ export 會變成變數名稱的一部分
> PATH=$PATH:/opt/bin        # ✗ 不會展開變數
> MSG="hello world"          # ✓ 引號會被移除
> ```
> 它只是簡單的 `KEY=VALUE`，不執行 shell。

> [!tip] `Environment=` vs `EnvironmentFile=`
> **機密一律用 `EnvironmentFile=`**，因為：
> ```bash
> systemctl show myapp -p Environment
> ```
> 會把 `Environment=` 的內容印出來，**任何使用者都看得到**。
> `EnvironmentFile=` 只會顯示檔案路徑。
>
> 更安全的做法是用 systemd 的 credentials 機制或外部秘密管理，
> 見 [[03-機密管理與金鑰保護]]。

### 自動重啟

```ini
[Service]
Restart=on-failure          # ✓ 建議：只在異常退出時重啟
RestartSec=5s               # 重啟前等 5 秒
StartLimitIntervalSec=300   # 5 分鐘內
StartLimitBurst=5           # 最多重啟 5 次，超過就放棄
```

| `Restart=` | 何時重啟 |
| --- | --- |
| `no` | 從不（預設） |
| **`on-failure`** | **非 0 退出碼、被訊號殺掉、逾時**（建議） |
| `always` | 一律重啟（連正常結束也重啟） |
| `on-abnormal` | 被訊號殺掉或逾時 |
| `unless-stopped` | 除非你手動 stop |

> [!warning] 沒有 `StartLimitBurst` 會造成無限重啟迴圈
> 程式因設定錯誤而每次啟動就馬上死掉時，
> `Restart=always` 會讓它每秒重啟一次，把日誌塞爆、CPU 吃滿。
>
> 加上限制之後，systemd 會在達到上限時停止嘗試並標記為 `failed`，
> 你才看得到問題：
> ```
> myapp.service: Start request repeated too quickly.
> myapp.service: Failed with result 'exit-code'.
> ```
> 修好之後要手動重設計數器：
> ```bash
> sudo systemctl reset-failed myapp
> sudo systemctl start myapp
> ```

### 資源限制（cgroup）

```ini
[Service]
MemoryMax=1G                # 硬上限，超過就被 OOM 殺掉（只殺這個服務）
MemoryHigh=800M             # 軟上限，超過會被限速
CPUQuota=50%                # 最多用 0.5 顆核心
CPUWeight=100               # 相對權重（預設 100）
TasksMax=512                # 最多幾個執行緒/程序
IOWeight=50                 # I/O 權重
LimitNOFILE=65535           # 檔案描述符上限（Nginx/資料庫常需要調高）
OOMScoreAdjust=-500         # 降低被 OOM Killer 選中的機率
```

> [!tip] `MemoryMax=` 是防止單一服務拖垮整台機器的關鍵
> 沒有限制時，一個記憶體洩漏的服務會吃光全機記憶體，
> 然後 OOM Killer 會挑「最大的」殺——**通常是你的資料庫**
> （見 [[10-程序管理與訊號]]）。
>
> 設了 `MemoryMax=1G` 之後，超過的是這個服務自己被殺，
> 其他服務完全不受影響，而且會留下明確的日誌：
> ```
> myapp.service: A process of this unit has been killed by the OOM killer.
> ```
>
> **每個自訂服務都該設一個合理的 `MemoryMax=`。**

檢查實際用量以決定上限：

```bash
systemctl status myapp | grep Memory
systemd-cgtop                      # 即時看各服務的資源用量
```

### 安全強化

systemd 提供大量沙箱選項，**成本極低但效果顯著**：

```ini
[Service]
# ── 檔案系統保護 ─────────────────────────────
ProtectSystem=strict           # /usr /boot /etc 全部唯讀
ProtectHome=true               # /home /root /run/user 不可存取
ReadWritePaths=/var/lib/myapp /var/log/myapp    # 例外：這些可寫
PrivateTmp=true                # 獨立的 /tmp（防符號連結攻擊）
ProtectKernelTunables=true     # /proc/sys /sys 唯讀
ProtectKernelModules=true      # 禁止載入核心模組
ProtectControlGroups=true      # cgroup 唯讀
ProtectProc=invisible          # 看不到其他使用者的程序

# ── 權限限制 ─────────────────────────────────
NoNewPrivileges=true           # ✓ 禁止提權（setuid 失效）
CapabilityBoundingSet=          # 移除所有 capabilities
AmbientCapabilities=CAP_NET_BIND_SERVICE   # 只留「綁定 <1024 埠」
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true    # 禁止可寫又可執行的記憶體頁

# ── 網路限制 ─────────────────────────────────
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
IPAddressDeny=any
IPAddressAllow=localhost 10.0.0.0/8

# ── 系統呼叫過濾 ─────────────────────────────
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
SystemCallArchitectures=native

# ── 裝置 ─────────────────────────────────────
PrivateDevices=true
DeviceAllow=
```

> [!tip] `systemd-analyze security` 量化你的服務有多安全
> ```bash
> systemd-analyze security myapp.service
> ```
> ```
> NAME                     DESCRIPTION                          EXPOSURE
> ✗ PrivateNetwork=        Service has access to the host's...      0.5
> ✗ User=/DynamicUser=     Service runs as root, option...          0.4
> ✓ ProtectSystem=         Service has strict read-only acc...
> ✗ RestrictAddressFamilies=Service may allocate exotic soc...      0.3
> ...
> → Overall exposure level for myapp.service: 6.8 EXPOSED 🙁
> ```
>
> ```bash
> systemd-analyze security          # 列出所有服務的評分
> ```
> 分數越低越安全（0 = 最安全，10 = 完全沒保護）。
> **這是很好的改善清單**——逐項加上建議的選項，看分數往下掉。
>
> 目標參考：一般服務做到 `< 5.0` 就相當不錯。

> [!warning] 加了沙箱選項要實測
> `ProtectSystem=strict` 之後服務可能寫不進它需要的目錄。
> 逐項加、逐項測：
> ```bash
> sudo systemctl restart myapp
> sudo journalctl -xeu myapp | grep -i 'permission denied\|read-only'
> ```
> 找出它需要寫的路徑，加進 `ReadWritePaths=`。

### `[Install]` 區塊

```ini
[Install]
WantedBy=multi-user.target      # 一般伺服器服務用這個
# WantedBy=graphical.target     # 需要圖形介面才啟動
# RequiredBy=other.service      # 更強的關係
# Alias=myapp2.service          # 別名
```

`enable` 時 systemd 會依照 `WantedBy=` 建立符號連結：

```bash
sudo systemctl enable myapp
```

```
Created symlink /etc/systemd/system/multi-user.target.wants/myapp.service
              → /etc/systemd/system/myapp.service
```

> [!warning] 沒有 `[Install]` 區塊就無法 `enable`
> ```
> The unit files have no installation config (WantedBy=, RequiredBy=, ...).
> This means they are not meant to be enabled using systemctl.
> ```
> 寫自訂服務時很容易漏掉這一段。

### 用 drop-in 覆寫套件提供的服務

```bash
sudo systemctl edit nginx
```

會開啟編輯器，你只需要寫**要覆蓋的部分**：

```ini
[Service]
LimitNOFILE=65535
MemoryMax=2G
Restart=always
RestartSec=3s
```

存檔後產生 `/etc/systemd/system/nginx.service.d/override.conf`。

```bash
sudo systemctl daemon-reload
sudo systemctl restart nginx
systemctl cat nginx                       # 看合併後的完整設定
systemctl show nginx -p LimitNOFILE
```

> [!tip] drop-in 的優點
> - 套件升級時**不會被覆蓋**
> - 只寫差異，一眼看出你改了什麼
> - 可以有多個 drop-in 檔案分別管理不同面向
>
> 移除覆寫：
> ```bash
> sudo systemctl revert nginx
> ```

> [!warning] 覆寫「列表型」的指令要先清空
> `ExecStart=` 是列表型指令，drop-in 裡直接寫會**變成兩個 ExecStart**：
> ```ini
> [Service]
> ExecStart=                        # ← 先用空值清空
> ExecStart=/usr/local/bin/mynginx  # 再設定新的
> ```
> 同樣的規則適用於 `ExecStartPre=`、`Environment=`、`ReadWritePaths=` 等。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> systemd 是跨發行版統一的，`systemctl` 指令與 unit 語法**完全相同**。差異：
>
> | 項目 | Debian / Ubuntu | RHEL 系 |
> | --- | --- | --- |
> | 套件 unit 位置 | `/lib/systemd/system/`（連結到 `/usr/lib/`） | `/usr/lib/systemd/system/` |
> | Apache 服務名 | `apache2` | **`httpd`** |
> | SSH 服務名 | `ssh`（`sshd` 是別名） | **`sshd`** |
> | 防火牆服務 | `ufw` | `firewalld` |
> | 安裝後預設狀態 | **自動 enable 並 start** | **不會自動啟動** |
>
> **最後一項差異很重要**：Debian 系裝完套件會自動啟動服務，
> RHEL 系不會。在 RHEL 上裝完 nginx 要記得：
> ```bash
> sudo systemctl enable --now nginx
> ```
>
> 另外 RHEL 系啟用 SELinux 時，服務若要監聽非標準埠會被擋：
> ```bash
> sudo semanage port -a -t http_port_t -p tcp 8080
> ```
> 見 [[07-SELinux與AppArmor]]。

---

## 完整實戰範例：部署一個 Node.js 應用

### 1. 建立專屬使用者與目錄

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin myapp
sudo mkdir -p /opt/myapp /var/lib/myapp /var/log/myapp /etc/myapp
sudo chown -R myapp:myapp /opt/myapp /var/lib/myapp /var/log/myapp
sudo chmod 750 /opt/myapp /var/lib/myapp
```

### 2. 環境變數檔

```bash
sudo tee /etc/myapp/env > /dev/null <<'ENVFILE'
NODE_ENV=production
PORT=3000
DATABASE_URL=postgres://myapp:changeme@127.0.0.1:5432/myapp
LOG_LEVEL=info
ENVFILE
sudo chown root:myapp /etc/myapp/env
sudo chmod 640 /etc/myapp/env
```

### 3. Unit 檔

```bash
sudo tee /etc/systemd/system/myapp.service > /dev/null <<'UNITFILE'
[Unit]
Description=MyApp API Server
Documentation=https://example.com/docs
After=network-online.target postgresql.service
Wants=network-online.target
Requires=postgresql.service

[Service]
Type=simple
User=myapp
Group=myapp
WorkingDirectory=/opt/myapp
EnvironmentFile=/etc/myapp/env

ExecStartPre=/usr/bin/node /opt/myapp/scripts/preflight.js
ExecStart=/usr/bin/node /opt/myapp/dist/server.js
ExecReload=/bin/kill -HUP $MAINPID

Restart=on-failure
RestartSec=5s
StartLimitIntervalSec=300
StartLimitBurst=5
TimeoutStopSec=30

# ── 資源限制 ──────────────────────────────
MemoryMax=1G
MemoryHigh=800M
CPUQuota=200%
TasksMax=256
LimitNOFILE=65535
OOMScoreAdjust=-200

# ── 安全強化 ──────────────────────────────
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/myapp /var/log/myapp
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ProtectProc=invisible
RestrictSUIDSGID=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
SystemCallArchitectures=native
CapabilityBoundingSet=
AmbientCapabilities=

# ── 日誌 ──────────────────────────────────
StandardOutput=journal
StandardError=journal
SyslogIdentifier=myapp

[Install]
WantedBy=multi-user.target
UNITFILE
```

### 4. 啟用與驗證

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now myapp

# 驗證
systemctl status myapp
sudo journalctl -u myapp -n 30 --no-pager
systemctl show myapp -p MemoryMax,Restart,User,NoNewPrivileges
systemd-analyze security myapp.service
curl -sS http://127.0.0.1:3000/health
```

### 5. 常見的調整

```bash
# 測試自動重啟是否運作
sudo systemctl show myapp -p MainPID
sudo kill -9 $(systemctl show myapp -p MainPID --value)
sleep 8
systemctl status myapp        # 應該已經自己起來了

# 測試資源限制是否生效
systemctl show myapp -p MemoryMax,MemoryHigh,TasksMax

# 看它實際用多少
systemd-cgtop -1 --order=memory | head
```

> [!tip] 這個 unit 檔可以當範本
> 把 `myapp` 換成你的服務名稱、調整 `ExecStart` 與 `ReadWritePaths` 就能用。
> 完整檔案建議另存到 `_設定檔範例/systemd/`。
>
> **對照 PM2 的做法**：Node 應用也可以用 PM2 管理
> （見 [[03-PM2-程序管理入門]]），兩者的取捨在
> [[04-PM2-進階設定與部署]] 有完整比較。簡單說：
> 單一應用用 systemd 更乾淨，多應用且需要零停機重載用 PM2。

---

## 常見錯誤與排錯

### 服務起不來的固定流程

```bash
# 1. 狀態與最近日誌（八成問題這裡就看到了）
systemctl status myapp

# 2. 完整日誌（-x 有解釋、-e 跳到最後）
sudo journalctl -xeu myapp

# 3. 只看本次開機的錯誤
sudo journalctl -u myapp -b -p err

# 4. 檢查 unit 檔語法
systemd-analyze verify /etc/systemd/system/myapp.service

# 5. 看合併後的實際設定
systemctl cat myapp
systemctl show myapp -p ExecStart,User,WorkingDirectory,Environment

# 6. 用服務的身分手動執行看看
sudo -u myapp env $(cat /etc/myapp/env | xargs) /usr/bin/node /opt/myapp/dist/server.js

# 7. 檢查路徑與權限
sudo -u myapp test -x /usr/bin/node && echo "執行檔 OK"
sudo -u myapp test -r /opt/myapp/dist/server.js && echo "程式檔可讀"
sudo -u myapp test -w /var/lib/myapp && echo "資料目錄可寫"
namei -l /opt/myapp/dist/server.js
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| `Unit not found` | unit 檔位置錯或沒 `daemon-reload` | 確認在 `/etc/systemd/system/`；`daemon-reload` |
| 改了 unit 檔沒生效 | 沒 `daemon-reload` | `sudo systemctl daemon-reload` |
| `status=203/EXEC` | **執行檔不存在或沒有執行權限** | `ls -l` 確認；`ExecStart` 要用**絕對路徑** |
| `status=200/CHDIR` | `WorkingDirectory` 不存在 | 建立目錄並設好權限 |
| `status=209/STDOUT` | 日誌輸出路徑有問題 | 用 `StandardOutput=journal` |
| `status=1/FAILURE` | 程式自己退出 | 看 `journalctl -xeu` 的程式輸出 |
| `Start request repeated too quickly` | 反覆失敗達到 `StartLimitBurst` | 修好問題後 `systemctl reset-failed` |
| 程式在跑但 systemd 說 failed | **`Type=` 選錯**（程式 fork 了但寫 simple） | 改 `Type=forking` + `PIDFile=`，或讓程式不要 fork |
| 重開機後服務沒起來 | 只 `start` 沒 `enable` | `sudo systemctl enable --now myapp` |
| `Permission denied` 寫不進檔案 | 沙箱選項擋住了 | 加進 `ReadWritePaths=` |
| 服務連不到網路 | `After=network.target` 不夠 | 改 `network-online.target` **並加 `Wants=`** |
| 環境變數沒生效 | `EnvironmentFile` 格式錯或權限不足 | 不要寫 `export`；確認服務帳號讀得到 |
| `reload` 說不支援 | unit 沒有 `ExecReload=` | 用 `reload-or-restart` |
| 服務被 OOM 殺掉 | 沒設 `MemoryMax=` 或設太低 | `journalctl -k \| grep -i oom`；調整上限 |
| RHEL 上裝完服務沒跑 | RHEL 不會自動啟動 | `sudo systemctl enable --now` |

---

## 安全性注意事項

> [!danger] 不要用 root 執行自訂服務
> ```ini
> # ✗ 沒有 User=，預設就是 root
> [Service]
> ExecStart=/opt/myapp/server
> ```
> 服務被入侵 = 整台機器被拿下。
>
> ```ini
> # ✓ 專屬帳號 + 移除所有 capabilities
> [Service]
> User=myapp
> Group=myapp
> NoNewPrivileges=true
> CapabilityBoundingSet=
> ```
>
> **需要綁 <1024 的埠**時不需要 root，用 ambient capability：
> ```ini
> AmbientCapabilities=CAP_NET_BIND_SERVICE
> CapabilityBoundingSet=CAP_NET_BIND_SERVICE
> ```

> [!warning] 稽核用 root 執行的服務
> ```bash
> systemctl show '*.service' -p Id,User --value 2>/dev/null \
>   | paste - - | awk -F'\t' '$2 == "" || $2 == "root" {print $1}'
> ```
> 或直接看評分：
> ```bash
> systemd-analyze security --no-pager | sort -k2 -rn | head -20
> ```
> 把分數最高（最不安全）的幾個列為改善目標。

> [!tip] 系統加固：關掉不需要的服務
> ```bash
> # 列出所有 enabled 的服務
> systemctl list-unit-files --type=service --state=enabled --no-pager
>
> # 逐一評估，不需要的關掉
> sudo systemctl disable --now bluetooth cups avahi-daemon ModemManager
> ```
> 每個不必要的服務都是一個攻擊面。
> 這是 TWGCB 與 CIS 的必檢項，見 [[03-TWGCB-Linux項目分類詳解]]。

---

## 速查表

### 日常操作

| 指令 | 說明 |
| --- | --- |
| **`systemctl enable --now X`** | **啟動 + 設定開機自啟** |
| `systemctl disable --now X` | 停止 + 取消開機自啟 |
| `systemctl start/stop/restart X` | 啟動/停止/重啟 |
| **`systemctl reload X`** | **重載設定（不中斷連線）** |
| `systemctl reload-or-restart X` | 支援就 reload，否則 restart |
| `systemctl mask/unmask X` | 徹底禁用/解除 |
| `systemctl status X` | 狀態與最近日誌 |
| `systemctl is-active/is-enabled X` | 腳本用的狀態查詢 |
| **`systemctl --failed`** | **所有失敗的服務** |
| **`sudo systemctl daemon-reload`** | **改過 unit 檔後必做** |
| `systemctl reset-failed X` | 重設失敗計數 |

### 查看

| 指令 | 說明 |
| --- | --- |
| **`systemctl cat X`** | **完整 unit 檔（含 drop-in）** |
| `systemctl show X -p 屬性` | 查特定屬性的生效值 |
| `systemctl list-units --type=service --state=running` | 執行中的服務 |
| `systemctl list-unit-files --state=enabled` | 開機啟動的服務 |
| `systemctl list-dependencies X` | 相依關係樹 |
| **`sudo journalctl -xeu X`** | **排查失敗最常用** |
| `sudo journalctl -u X -f` | 即時追蹤 |
| `systemd-cgtop` | 各服務資源用量 |
| **`systemd-analyze security X`** | **安全評分** |
| `systemd-analyze verify <檔案>` | 驗證 unit 語法 |
| `systemd-analyze blame` | 開機各服務耗時 |

### Unit 檔關鍵指令

| 指令 | 說明 |
| --- | --- |
| `After=` / `Wants=` / `Requires=` | 順序 / 弱相依 / 強相依 |
| `After=network-online.target` + `Wants=` | **等網路真的可用** |
| `Type=simple` / `forking` / `oneshot` | 程序模型 |
| `User=` / `Group=` | **執行身分（不要用 root）** |
| `EnvironmentFile=` | 環境變數（**機密放這裡**） |
| `Restart=on-failure` + `RestartSec=` | 自動重啟 |
| `StartLimitBurst=` | **避免無限重啟迴圈** |
| **`MemoryMax=`** | **防止拖垮整機** |
| `LimitNOFILE=` | 檔案描述符上限 |
| `NoNewPrivileges=true` | 禁止提權 |
| `ProtectSystem=strict` + `ReadWritePaths=` | 檔案系統唯讀 + 例外 |
| `PrivateTmp=true` | 獨立 /tmp |
| `WantedBy=multi-user.target` | **沒有 `[Install]` 就無法 enable** |

### 修改套件服務

| 指令 | 說明 |
| --- | --- |
| **`sudo systemctl edit X`** | **建立 drop-in 覆寫（推薦）** |
| `sudo systemctl edit --full X` | 完整複製到 `/etc/` 後編輯 |
| `sudo systemctl revert X` | 移除所有覆寫 |
| `ExecStart=` （空值） | **列表型指令要先清空再設定** |

---

## 練習題

> [!question]- 練習 1：`start` 與 `enable` 的差別
> 建立一個最簡單的服務，只 `start` 不 `enable`，重開機驗證結果。
>
> **解答**
>
> ```bash
> sudo tee /etc/systemd/system/hello.service > /dev/null <<'UNIT'
> [Unit]
> Description=Hello Test Service
>
> [Service]
> Type=simple
> ExecStart=/bin/bash -c 'while true; do echo "hello $(date)"; sleep 60; done'
>
> [Install]
> WantedBy=multi-user.target
> UNIT
>
> sudo systemctl daemon-reload
> sudo systemctl start hello
> systemctl is-active hello      # active
> systemctl is-enabled hello     # disabled  ← 注意！
> ```
>
> ```bash
> sudo reboot
> # 重開機後
> systemctl is-active hello      # inactive  ← 沒有自動啟動
> ```
>
> ```bash
> sudo systemctl enable --now hello
> systemctl is-enabled hello     # enabled
> ```
>
> **這就是「測試都正常，上線後某次重開機服務就沒了」的原因。**
>
> 快速檢查全機有沒有這種漏網之魚：
> ```bash
> comm -23 \
>   <(systemctl list-units --type=service --state=running --no-legend | awk '{print $1}' | sort) \
>   <(systemctl list-unit-files --type=service --state=enabled --no-legend | awk '{print $1}' | sort)
> ```
>
> 清理：
> ```bash
> sudo systemctl disable --now hello
> sudo rm /etc/systemd/system/hello.service
> sudo systemctl daemon-reload
> ```

> [!question]- 練習 2：用 `MemoryMax` 保護整台機器
> 建立一個會不斷吃記憶體的服務，比較有無 `MemoryMax=` 的差別。
>
> **解答**
>
> ```bash
> # ⚠ 在有快照的練習機上做
> sudo tee /etc/systemd/system/memhog.service > /dev/null <<'UNIT'
> [Unit]
> Description=Memory Hog Test
>
> [Service]
> Type=simple
> MemoryMax=100M
> ExecStart=/bin/bash -c 'a=""; while true; do a="$a$(head -c 1048576 /dev/zero | tr "\0" "x")"; sleep 0.1; done'
> Restart=no
>
> [Install]
> WantedBy=multi-user.target
> UNIT
>
> sudo systemctl daemon-reload
> sudo systemctl start memhog
> watch -n 1 'systemctl status memhog | grep -E "Active|Memory"'
> ```
>
> 幾秒後：
> ```
> Active: failed (Result: oom-kill) since ...
> ```
>
> ```bash
> sudo journalctl -u memhog | grep -i oom
> ```
> ```
> memhog.service: A process of this unit has been killed by the OOM killer.
> ```
>
> **關鍵觀察**：`free -h` 顯示整機記憶體幾乎沒有波動——
> cgroup 限制讓它「只殺自己」。
>
> 拿掉 `MemoryMax=` 重試（**只在可拋棄的練習機上**），
> 你會看到整機記憶體被吃光、系統變得極慢，
> 最後 OOM Killer 可能砍掉別的重要服務。
>
> 清理：
> ```bash
> sudo systemctl stop memhog; sudo rm /etc/systemd/system/memhog.service
> sudo systemctl daemon-reload; sudo systemctl reset-failed
> ```

> [!question]- 練習 3：用 drop-in 安全地調整 Nginx
> 把 Nginx 的檔案描述符上限調到 65535、記憶體上限 2G，
> 且**不能**動到套件提供的 unit 檔。改完驗證，再完整還原。
>
> **解答**
>
> ```bash
> # 1. 先看原始設定
> systemctl show nginx -p LimitNOFILE,MemoryMax
> ```
> ```
> LimitNOFILE=1024
> MemoryMax=infinity
> ```
>
> ```bash
> # 2. 建立 drop-in（不用手動建目錄）
> sudo systemctl edit nginx
> ```
> 在編輯器中輸入：
> ```ini
> [Service]
> LimitNOFILE=65535
> MemoryMax=2G
> ```
>
> ```bash
> # 3. 確認產生的檔案
> ls -l /etc/systemd/system/nginx.service.d/
> cat /etc/systemd/system/nginx.service.d/override.conf
>
> # 4. 套用並驗證
> sudo systemctl daemon-reload
> sudo systemctl restart nginx
> systemctl show nginx -p LimitNOFILE,MemoryMax
> ```
> ```
> LimitNOFILE=65535
> MemoryMax=2147483648
> ```
>
> ```bash
> # 5. 確認原始檔案沒被動過
> sudo git -C /etc status --short 2>/dev/null    # 有 etckeeper 的話
> md5sum /usr/lib/systemd/system/nginx.service   # 與套件原始版本比對
> dpkg -V nginx-core | grep systemd              # 應該沒有輸出
>
> # 6. 看合併後的完整設定
> systemctl cat nginx
> ```
> 輸出會先顯示原始 unit，再顯示 drop-in：
> ```
> # /usr/lib/systemd/system/nginx.service
> ...
> # /etc/systemd/system/nginx.service.d/override.conf
> [Service]
> LimitNOFILE=65535
> MemoryMax=2G
> ```
>
> ```bash
> # 7. 完整還原
> sudo systemctl revert nginx
> sudo systemctl daemon-reload && sudo systemctl restart nginx
> systemctl show nginx -p LimitNOFILE,MemoryMax
> ```
>
> **為什麼不直接改 `/usr/lib/systemd/system/nginx.service`**：
> 下次 `apt upgrade nginx` 時那個檔案會被套件的新版覆蓋，
> 你的修改**無聲無息地消失**，而且很難察覺。

---

## 小測驗

Q1. `systemctl start` 與 `enable` 各做什麼？「測試正常、重開機後服務沒起來」是漏了哪個？
Q2. `restart` 與 `reload` 的差別？改了 Nginx 設定該用哪個？`reload` 失敗說不支援代表什麼？
Q3. 為什麼不能直接編輯 `/usr/lib/systemd/system/nginx.service`？正確做法？
Q4. 改完 unit 檔卻沒生效，最常漏的一步？
Q5. `After=` 與 `Requires=` 各管什麼？只寫 `Requires=postgresql` 會有什麼問題？
Q6. `After=network.target` 對需要連外的服務為什麼不夠？正確寫法要兩行是哪兩行？
Q7. 程式明明在跑但 `status` 顯示 `failed`，最可能是哪個設定選錯？
Q8. `Restart=always` 沒有 `StartLimitBurst` 會發生什麼？修好後要跑什麼指令？
Q9. `MemoryMax=1G` 的價值是什麼？被 OOM 殺掉時日誌會怎麼寫？
Q10. drop-in 中要覆寫 `ExecStart=` 為什麼要先寫一行空的？

> [!question]- 測驗答案
> **Q1.** `start` 立即啟動但不設開機自啟，`enable` 相反；漏了 `enable`。一律 `enable --now`（見「最常用的指令」）。
> **Q2.** `restart` 殺掉重開會中斷連線，`reload` 送訊號重讀設定不中斷；改設定用 `reload`；unit 沒有 `ExecReload=`，用 `reload-or-restart`。
> **Q3.** 套件升級會無聲覆蓋；`systemctl edit nginx` 建 drop-in（或 `--full`）。
> **Q4.** `sudo systemctl daemon-reload`。
> **Q5.** `After=` 只管順序，`Requires=` 只管相依；只寫 `Requires` 兩者可能同時啟動，服務因連不到資料庫而失敗。兩個都要寫。
> **Q6.** `network.target` 只代表網路子系統啟動，可能還沒拿到 IP；`After=network-online.target` 加 `Wants=network-online.target`。
> **Q7.** `Type=`——程式會 fork 到背景卻寫 `simple`（或反之）。
> **Q8.** 每秒無限重啟塞爆日誌吃滿 CPU；`systemctl reset-failed` 再 `start`。
> **Q9.** 失控的服務只殺死自己，不拖垮整機讓 OOM Killer 去殺資料庫；`A process of this unit has been killed by the OOM killer`。
> **Q10.** `ExecStart=` 是列表型指令，直接寫會變成兩個 ExecStart；空值先清空再設定。

---

## 延伸閱讀

- [[18-排程工作]] — systemd timer 與 cron 的選型
- [[19-日誌系統]] — `journalctl` 的完整用法
- [[10-程序管理與訊號]] — 訊號、cgroup 與 OOM Killer
- [[09-使用者與群組管理]] — 服務專屬帳號的建立
- [[03-PM2-程序管理入門]] — Node 應用的另一種管理方式
- [[03-TWGCB-Linux項目分類詳解]] — 停用非必要服務的合規要求
- `man 5 systemd.unit` / `man 5 systemd.service` / `man 5 systemd.exec` / `man 5 systemd.resource-control`
