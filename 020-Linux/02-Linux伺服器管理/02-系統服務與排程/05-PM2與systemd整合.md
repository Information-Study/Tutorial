---
title: "PM2 與 systemd 整合"
desc: "從 systemd 這一側看 PM2：解剖 pm2-<user>.service、四種雙重管理衝突、三種架構選型與完整遷移"
aliases: [pm2 systemd, pm2-runtime, PM2_HOME, pm2 resurrect, pm2 unstartup, 雙重程序管理]
tags: [群組/Linux, linux/伺服器, 主題/systemd, 主題/程序管理]
category: 系統服務與排程
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[03-PM2-程序管理入門]]", "[[01-systemd-unit撰寫實戰]]"]
updated: 2026-08-28
---

# PM2 與 systemd 整合

> [!abstract] 這篇你會學到
> - **逐行讀懂** `pm2 startup` 產生的那份 `pm2-<user>.service`，說得出它的**四個弱點**
> - ★★★★★ 認出 **`PM2_HOME` 不一致**這個殺手：`systemctl status` 是綠燈、整個前台卻不見了
> - 分辨兩個程序管理器打架的**四種形態**，並知道每一種該往哪一層修
> - 在**架構 A / B / C** 之間依「稽核可見性、日誌集中、多核心、零停機、維運熟悉度」選型
> - 把 systemd 的 `TimeoutStopSec`、PM2 的 `kill_timeout`、應用自己的 SIGTERM 處理**三個逾時對齊**
> - 照一支**可回滾的腳本**，把三年前用 `pm2 startup` 設起來的機關前台遷到 systemd 託管

## 前置知識

- [[03-PM2-程序管理入門]] — PM2 的安裝、基本指令、`pm2 startup` / `pm2 save`、日誌位置、五個坑。
  **本篇不重講這些**，只引用它的結論。
- [[04-PM2-進階設定與部署]] — `ecosystem.config.cjs` 完整寫法、cluster 原理、零停機 reload 的
  graceful shutdown 程式碼。本篇不重貼設定檔全文。
- [[01-systemd-unit撰寫實戰]] — unit 的相依、`Exec*`、沙箱指令、template unit。
- [[04-服務自動復原與看門狗]] — `Restart=` 策略、健康檢查 timer、`OnFailure=` 告警單元的完整實作。
  本篇只談「PM2 情境下這些機制該掛在哪一層」。
- [[17-systemd服務管理]] — `systemctl` 基本操作、`start` 與 `enable` 的差別。
- [[01-Node-安裝與版本管理]] — 為什麼正式機**不要用 nvm**（本篇的 PATH 問題直接源自這個結論）。

---

## 觀念說明

### 一句話定位

[[03-PM2-程序管理入門]] 是從 **PM2 這一側**寫的：怎麼裝、怎麼用、怎麼設開機自啟。
這一篇是從 **systemd 這一側**寫的，回答的是完全不同的問題：

> **當機器上同時存在兩個程序管理器，而它們都認為自己是那個應用的爸爸，會發生什麼事？**

機關情境讓這個問題變得非做不可。稽核的兩條要求幾乎是標配：

```
① 所有對外服務都要能用 `systemctl status <服務>` 看到即時狀態
② 所有服務日誌都要進集中蒐集平台（syslog / Wazuh / SIEM）
```

而 `pm2 startup` 的預設做法**同時違反這兩條**——狀態反映的是 PM2 daemon 不是你的應用，
日誌落在某個使用者家目錄下的 `.pm2/logs/`，集中蒐集根本收不到。
PM2 的「自成一格」在開發機是優點，在機關正式機是**兩個盲區**。

### 兩層托管的疊層圖

```
【架構 A】pm2 startup 的預設產物（最常見、也最多盲區）

  systemd (PID 1)
    └─ pm2-ops.service          Type=forking，PIDFile=~/.pm2/pm2.pid
         └─ PM2 God Daemon      ← ★★★★ systemd 只看得到「它」
              ├─ node .output/server/index.mjs  (worker 0)   ← systemd 看不見
              └─ node .output/server/index.mjs  (worker 1)   ← systemd 看不見
                   stdout ──▶ ~/.pm2/logs/nuxt-out.log       ← 集中蒐集收不到

  → 兩個 worker 全部 errored，God Daemon 還活著
    → `systemctl status pm2-ops` 依然是 active (running)  ★★★★


【架構 B】自寫 unit 跑 pm2-runtime（前景模式）

  systemd (PID 1)
    └─ nuxt-app.service         Type=simple
         └─ pm2-runtime         ← 前景執行，不 fork，systemd 直接監看它
              ├─ node ... (worker 0)
              └─ node ... (worker 1)
                   stdout ──▶ pm2-runtime ──▶ journald  ★★ 集中蒐集收得到

  → 應用全掛 → pm2-runtime 退出 → systemd 判定 failed → OnFailure 觸發告警


【架構 C】完全不用 PM2

  systemd (PID 1)
    ├─ nuxt-app@1.service ─ node .output/server/index.mjs  PORT=3001
    └─ nuxt-app@2.service ─ node .output/server/index.mjs  PORT=3002
         stdout ──▶ journald
  → 多核心靠 Nginx upstream 分流（見 [[03-Nuxt-Nginx反向代理與快取]]）
```

> [!note] 為什麼「systemd 看不見 worker」不等於「systemd 管不到 worker」
> 這兩件事要分清楚，否則排錯會抓錯方向：
>
> | | 監看（狀態判定） | 涵蓋（cgroup 歸屬） |
> | --- | --- | --- |
> | 架構 A 的 worker | ❌ **不在判定範圍**，掛了 systemd 不知道 | ✅ 在 `pm2-ops.service` 的 cgroup 內，`systemctl stop` **殺得到** |
> | 手動在 SSH session 起的 PM2 | ❌ 不知道 | ❌ **在 `user@1000.service` 的 cgroup**，`systemctl stop` **殺不到** ★★★★ |
>
> 所以「狀態不準」與「停不乾淨」是兩個獨立的坑，成因不同，第 ② ④ 種衝突形態各對應一個。

### 責任重疊表：兩邊到底誰在做同一件事

| 職責 | systemd 的做法 | PM2 的做法 | ★ 重疊時的風險 |
| --- | --- | --- | --- |
| 開機自啟 | `systemctl enable` | `pm2 startup` + `pm2 save` | ★★★★★ dump 快照與 unit 的 `PM2_HOME` 不同步 |
| 異常重啟 | `Restart=on-failure` + `RestartSec=` | `autorestart` + `restart_delay` | ★★★★ 兩層退避互踩，服務反覆抖動 |
| 停機語意 | `ExecStop=` → `TimeoutStopSec` → SIGKILL | `kill_timeout`（**預設只有 1600 ms**） | ★★★★ 逾時對不齊 → 連線被 SIGKILL 砍斷 |
| 資源限制 | `MemoryMax=` / `CPUQuota=`（cgroup，硬限制） | `max_memory_restart`（PM2 自己量、自己重啟） | ★★ 兩邊都設會互相搶著動手 |
| 日誌 | `StandardOutput=journal` → journald | `out_file` / `error_file` → 檔案 | ★★★ 雙軌，事故時查錯地方 |
| 環境變數 | `Environment=` / `EnvironmentFile=` | `ecosystem` 的 `env` / `env_production` | ★★★ 兩邊都有值時**以 PM2 的為準**，unit 改了沒效果 |
| 使用者身分 | `User=` / `Group=` | 靠 `pm2 startup -u <user>` 寫進 unit | ★★★ `sudo pm2` 與 `pm2` 是兩套完全獨立的清單 |
| 多實例 | template unit / socket activation | `exec_mode: cluster` + `instances` | ★ 這一項通常只選一邊，衝突少 |

> [!danger] 本篇的核心命題 ★★★★
> **不要讓兩層同時對同一個決策負責。**
> 每一個職責只准有一個「權威層」，另一層退化成純粹的傳遞或第二道安全網。
> 下面的架構 B 就是這個原則的具體化：
> 開機自啟、狀態判定、日誌、停機逾時 → **systemd 說了算**；
> cluster 與零停機 reload → **PM2 說了算**。

---

## 環境準備與現況蒐證

任何遷移動作之前，先把「現在到底是什麼狀態」蒐證下來。
機關環境常見的是「三年前某位離職同仁設定的」，沒有人說得清楚。

### 【第一步】unit 到底長什麼樣：`systemctl cat`

```bash
systemctl cat pm2-ops
```

預期輸出（Ubuntu 22.04 / 24.04，PM2 5.x，使用者為 `ops`）：

```ini
# /etc/systemd/system/pm2-ops.service
[Unit]
Description=PM2 process manager
Documentation=https://pm2.keymetrics.io/
After=network.target

[Service]
Type=forking
User=ops
LimitNOFILE=infinity
LimitNPROC=infinity
LimitCORE=infinity
Environment=PATH=/usr/bin:/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin
Environment=PM2_HOME=/home/ops/.pm2
PIDFile=/home/ops/.pm2/pm2.pid
Restart=on-failure

ExecStart=/usr/lib/node_modules/pm2/bin/pm2 resurrect
ExecReload=/usr/lib/node_modules/pm2/bin/pm2 reload all
ExecStop=/usr/lib/node_modules/pm2/bin/pm2 kill

[Install]
WantedBy=multi-user.target
```

> [!tip] 如果不確定 unit 叫什麼名字
> ```bash
> systemctl list-unit-files 'pm2-*'
> ```
> ```text
> UNIT FILE          STATE   PRESET
> pm2-ops.service    enabled enabled
>
> 1 unit files listed.
> ```
> ★ 名字固定是 `pm2-<執行 pm2 startup 時指定的使用者>`。看到 `pm2-root.service`
> 就代表當初是直接 `sudo pm2 startup` 跑的，全部東西都在 `/root/.pm2`。

### 【第二步】逐行解剖這份 unit

| 行 | 意義 | ★ 這裡藏了什麼 |
| --- | --- | --- |
| `After=network.target` | 網路堆疊初始化後啟動 | ★★ **不等於網路可用**。要 IP 真的綁好用 `After=network-online.target` + `Wants=network-online.target`；掛 NFS 的還要加 `RequiresMountsFor=` |
| `Type=forking` | PM2 會 fork 成 daemon，父程序退出 | ★★★★ systemd 靠「父程序退出 + PIDFile 出現」判定啟動成功，**判定的是 daemon，不是你的應用** |
| `User=ops` | 以 `ops` 身分執行 | ★★★ 模板**沒有 `Group=`**，群組取自該使用者的主要群組；也**沒有 `WorkingDirectory=`**，cwd 是 `/` |
| `LimitNOFILE=infinity` | 檔案描述子不設限 | ★★ 對高併發 Node 是好事，但等於放棄了這道保險 |
| `LimitCORE=infinity` | core dump 不設限 | ★★★★ 應用崩潰時可能在磁碟落下**含記憶體內容**的 core 檔——裡面有 DB 密碼、session token、個資。見〈安全性注意事項〉 |
| `Environment=PATH=...` | **寫死**的 PATH | ★★★★ 第一段 `/usr/bin` 是 **執行 `pm2 startup` 當下 node 所在的目錄**。當初若用 nvm，這裡會是 `/home/ops/.nvm/versions/node/v18.19.0/bin` |
| `Environment=PM2_HOME=...` | daemon 的資料目錄 | ★★★★★ **整篇最重要的一行**。`dump.pm2`、`pm2.pid`、`logs/`、`rpc.sock` 全部在這底下 |
| `PIDFile=.../pm2.pid` | 給 `Type=forking` 用的 pid 來源 | ★★★ 只要這個檔存在且 pid 活著，systemd 就報 active |
| `Restart=on-failure` | daemon 非 0 退出才重啟 | ★★★ 重啟的是 **daemon**；daemon 起來後跑的是 `resurrect`，讀的還是那份 dump |
| `ExecStart=... pm2 resurrect` | 從 `dump.pm2` 還原程序清單 | ★★★★★ **不是**「啟動你的 ecosystem」，是「把上次 `pm2 save` 的快照還原回來」 |
| `ExecReload=... pm2 reload all` | `systemctl reload` 會做零停機重載 | ★★ 這行其實很有用，但幾乎沒人知道可以 `systemctl reload pm2-ops` |
| `ExecStop=... pm2 kill` | 停掉整個 God Daemon | ★★★★ **沒有 `TimeoutStopSec=`**，吃 systemd 預設 90 秒；也與 PM2 的 `kill_timeout` 完全不同步 |

> [!danger] 這份 unit 的四個弱點（記起來，排錯時會一直用到）★★★★
> ```
> ① PATH 寫死
>    → 換 node 版本、移除 nvm、改 npm prefix，開機就找不到 node
>      → 手動在 shell 裡跑一切正常，只有開機失敗（最難查的一類）
>
> ② Type=forking 的啟動判定不精準
>    → 只驗「pm2.pid 出現且 pid 活著」
>      → resurrect 出 0 個應用也算「啟動成功」
>
> ③ 狀態只反映 daemon，不反映應用
>    → 所有 worker 都 errored，systemctl status 照樣綠燈
>      → 【不能拿 systemctl status 當監控依據】
>
> ④ 停機語意與 PM2 的 kill_timeout 不同步
>    → ExecStop 的 pm2 kill 依 kill_timeout（預設 1600ms）砍 worker
>      → 應用還在收尾就被 SIGKILL，而 systemd 那邊還悠哉地等 90 秒
> ```
> 另外模板**完全沒有任何安全加固指令**：沒有 `NoNewPrivileges=`、沒有 `ProtectSystem=`、
> 沒有 `PrivateTmp=`。以 `systemd-analyze security pm2-ops` 打分通常落在 9.x（UNSAFE）。

### 【第三步】★★★★★ PM2_HOME 一致性檢查

這是整篇最大的殺手，值得一個獨立的檢查流程。

**核心事實**：`pm2` 與 `sudo pm2` 是**兩套完全獨立的程序清單**。

```
你打的指令                 PM2_HOME 解析結果        操作的是哪個 daemon
─────────────────────────────────────────────────────────────────────
pm2 list        (ops)      $HOME/.pm2 = /home/ops/.pm2    ops 的 daemon
sudo pm2 list              $HOME/.pm2 = /root/.pm2        root 的 daemon ★★★★★
sudo -u ops pm2 list       /root/.pm2（HOME 沒換！）      ★★★ 常見陷阱
sudo -iu ops pm2 list      /home/ops/.pm2                 ✓ 正確
PM2_HOME=/home/ops/.pm2 pm2 list                          ✓ 最明確
```

`sudo -u ops` **不會**重設 `$HOME`（除非 sudoers 有 `always_set_home`），
所以它會去讀 `/root/.pm2`，然後回報「空的」。★★★ 這一條害過非常多人。

**四道診斷指令**（依序跑完，答案就出來了）：

```bash
# 【1】unit 認定的 PM2_HOME 是哪一個
systemctl show pm2-ops -p Environment
```

```text
Environment=PATH=/usr/bin:/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin PM2_HOME=/home/ops/.pm2
```

```bash
# 【2】各個候選 PM2_HOME 的 dump 檔存在嗎？時間戳是什麼時候？
for h in /home/ops/.pm2 /root/.pm2 /var/lib/nodeapp/.pm2; do
  printf '%-28s ' "$h"
  sudo stat -c '%y  (%s bytes)' "$h/dump.pm2" 2>/dev/null || echo '(無 dump.pm2)'
done
```

```text
/home/ops/.pm2               2023-06-14 10:22:41.000000000 +0800  (2 bytes)   # ★★★★★ 2 bytes = "[]" 空陣列！
/root/.pm2                   2026-08-20 15:03:12.000000000 +0800  (4128 bytes)
/var/lib/nodeapp/.pm2        (無 dump.pm2)
```

```bash
# 【3】用 unit 指定的那個 PM2_HOME 去看清單（★ 這才是開機時會還原的內容）
sudo -u ops PM2_HOME=/home/ops/.pm2 pm2 list
```

```text
┌────┬──────────┬─────────┬─────────┬──────┬────────┬──────┬──────────┐
│ id │ name     │ mode    │ pid     │ ↺    │ status │ cpu  │ mem      │
└────┴──────────┴─────────┴─────────┴──────┴────────┴──────┴──────────┘
                                            # ★★★★★ 空的 → 重開機後前台不會起來
```

```bash
# 【4】現在活著的 God Daemon 各自用哪個 PM2_HOME（★ PM2 把它寫在程序標題裡）
ps -eo user,pid,ppid,args | grep -F 'God Daemon' | grep -v grep
```

```text
root      1842     1 PM2 v5.4.3: God Daemon (/root/.pm2)     # ★★★★ 真正在服務的是這一個
ops       2210     1 PM2 v5.4.3: God Daemon (/home/ops/.pm2) # 由 unit 起的，裡面 0 個應用
```

看到上面這組輸出，事故劇本就完整了：
**unit 指向 `/home/ops/.pm2`，但實際在服務的應用是某次用 `sudo pm2 start` 起的、存在 `/root/.pm2`。
機器一重開，systemd 把 `ops` 的 daemon 拉起來（`systemctl status` 綠燈），
resurrect 出 0 個應用，前台整個不見。**

> [!danger] ★★★★★ 統一規則：全機器只准有一個 PM2_HOME
> 1. **選定一個系統帳號**（例如 `nodeapp`），家目錄在 `/var/lib/nodeapp`，shell 給 `/usr/sbin/nologin`。
> 2. `PM2_HOME` 固定寫成**絕對路徑**放進 unit，**不要**靠 `$HOME` 推導。
> 3. 在 `/etc/profile.d/pm2-home.sh` 放一行提醒，避免有人隨手 `sudo pm2`：
>    ```bash
>    # /etc/profile.d/pm2-home.sh
>    export PM2_HOME=/var/lib/nodeapp/.pm2   # ★★★★ 全機器唯一的 PM2_HOME
>    ```
> 4. **禁止 `sudo pm2`**。要以該帳號操作一律 `sudo -iu nodeapp pm2 ...`，或包成 wrapper：
>    ```bash
>    # /usr/local/bin/npm2  —— 唯一許可的 PM2 進入點
>    #!/usr/bin/env bash
>    set -euo pipefail
>    exec sudo -u nodeapp env PM2_HOME=/var/lib/nodeapp/.pm2 /usr/bin/pm2 "$@"
>    ```
> 5. 巡檢時跑一次 `ps -eo user,args | grep -c 'God Daemon'`，**結果必須是 1**。

### 【第四步】Node 與 PM2 的絕對路徑

systemd 的執行環境**沒有登入 shell**：沒有 `~/.bashrc`、沒有 `~/.profile`、
沒有 nvm 注入的那一段 shell function。`nvm` 的 `node` 根本不是一個檔案，是 shell 裡的一個函式。

```bash
# ★★★ 互動 shell 裡的結果不能直接拿來寫進 unit，要先 readlink -f
command -v node
readlink -f "$(command -v node)"
readlink -f "$(command -v pm2)"
readlink -f "$(command -v pm2-runtime)"
```

正常（NodeSource / 發行版套件）應該長這樣：

```text
/usr/bin/node
/usr/bin/node
/usr/lib/node_modules/pm2/bin/pm2
/usr/lib/node_modules/pm2/bin/pm2-runtime
```

★★★★ 如果看到下面這種，unit 一定會在開機時炸掉：

```text
/home/ops/.nvm/versions/node/v18.19.0/bin/node    # ★★★★ nvm，開機時 /home 可能還沒掛、版本也會被換掉
```

> [!warning] 為什麼「手動跑正常、開機失敗」★★★★
> 你在 SSH session 裡 `sudo systemctl start pm2-ops`——這時 `/home` 早就掛好了、
> nvm 的目錄存在、shim 也在。開機時序完全不同：
> `pm2-ops.service` 只宣告 `After=network.target`，**沒有宣告要等 `/home` 掛載**，
> 若 `/home` 是獨立分割或 NFS，unit 可能比掛載更早跑。
> 修法有兩層：**根治**是把 node 換成 `/usr/bin/node`（見 [[01-Node-安裝與版本管理]] 的「不要用 nvm」結論）；
> **止血**是補 `RequiresMountsFor=/var/lib/nodeapp`。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> unit 模板本身完全相同（PM2 不分發行版），差別在路徑與 SELinux：
>
> ```bash
> # ★ RHEL 系用 dnf module 或 NodeSource，全域套件多半落在 /usr/lib/node_modules
> sudo dnf module install nodejs:20/common
> readlink -f "$(command -v pm2)"
> ```
> ```text
> /usr/lib/node_modules/pm2/bin/pm2
> ```
>
> ★★★ **SELinux 是 RHEL 特有的第三個坑**：自寫的 unit 若把程式碼放在 `/var/www` 以外的地方，
> 或要監聽非標準埠，`systemctl start` 會失敗而 journal 只給一個含糊的 `Permission denied`。
> 先確認是不是 SELinux：
> ```bash
> sudo ausearch -m AVC -ts recent | tail -20
> sudo semanage port -a -t http_port_t -p tcp 3000     # 允許監聽 3000
> sudo restorecon -Rv /var/lib/nodeapp
> ```
> 詳見 [[07-SELinux與AppArmor]]。Ubuntu 的 AppArmor 預設不管自訂 unit，通常不會擋。
>
> ★★ 另外 RHEL 系預設 `/home` 常是獨立 LV，`RequiresMountsFor=` 更值得補上。

---

## 進階設定與調校

### 雙重管理的四種衝突形態

#### ① 兩層重啟互踩，服務反覆抖動 ★★★★

```
       systemd 層                          PM2 層
  Restart=on-failure                  autorestart: true
  RestartSec=1                        min_uptime: '10s'
  StartLimitBurst=5 / 10s             max_restarts: 10
                                      restart_delay: 3000
                                      exp_backoff_restart_delay: 100
```

兩層各自有退避演算法，而且**彼此不知道對方存在**。典型災難：

```text
10:00:01 nuxt-app.service: Main process exited, code=exited, status=1
10:00:02 nuxt-app.service: Scheduled restart job, restart counter is at 1.
10:00:03 PM2 log: App [nuxt:0] exited with code [1] via signal [SIGINT]
10:00:03 PM2 log: App [nuxt:0] starting in -cluster mode-
10:00:04 nuxt-app.service: Main process exited, code=exited, status=1
10:00:05 nuxt-app.service: Scheduled restart job, restart counter is at 2.
...                                     # ★★★★ 兩層日誌交錯，看不出誰在重啟誰
10:00:09 nuxt-app.service: Start request repeated too quickly.
10:00:09 nuxt-app.service: Failed with result 'exit-code'.
```

**修法（架構 B 的建議配置）**：

```ini
[Unit]
# ★★★ StartLimit* 在 [Unit] 區段，不是 [Service]（systemd 230 之後）
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Restart=on-failure
RestartSec=10          # ★★★★ 必須 ≥ PM2 的 min_uptime，否則兩層搶著重啟
```

```javascript
// ecosystem.config.cjs（節錄，完整寫法見 [[04-PM2-進階設定與部署]]）
autorestart: true,
min_uptime: '10s',
max_restarts: 5,        // ★★★ 用完就讓 pm2-runtime 整個退出，交給 systemd 判 failed
restart_delay: 3000,
```

> [!tip] 分工原則 ★★★
> **PM2 負責「快速的、單一 worker 的」重啟**（一個 worker 崩了，秒級補上，使用者無感）。
> **systemd 負責「慢速的、整體的」重啟**（PM2 自己都撐不住了，退避後重來，並觸發 `OnFailure`）。
> 讓 `RestartSec` 明顯大於 `restart_delay`，兩層的時間尺度就不會打架。

#### ② `systemctl stop` 之後子程序殘留 ★★★★

```bash
sudo systemctl stop pm2-ops
systemctl is-active pm2-ops
```

```text
inactive
```

```bash
# ★★★ 但埠還被佔著
sudo ss -lptn 'sport = :3000'
```

```text
State  Recv-Q Send-Q Local Address:Port  Process
LISTEN 0      511        127.0.0.1:3000  users:(("node",pid=1899,fd=22))   # ★★★★ 還活著
```

成因有兩種，**修法完全不同**：

| 成因 | 判斷方式 | 修法 |
| --- | --- | --- |
| ★★★★ 殘留程序**不在** unit 的 cgroup 內（有人在 SSH session 手動 `pm2 start`） | `systemd-cgls -u pm2-ops.service` 看不到那個 pid；`cat /proc/1899/cgroup` 顯示 `user@1000.service` | 只能手動清；根治是禁止互動式 `pm2 start`（見上面的 wrapper） |
| ★★★ 在 cgroup 內但 `ExecStop` 沒殺乾淨，systemd 又等滿 `TimeoutStopSec` | `systemd-cgls -u pm2-ops.service` 看得到；journal 有 `State 'stop-sigterm' timed out` | 補 `TimeoutStopSec=45` + `KillMode=control-group`（預設值，明寫比較安心）+ 修 `kill_timeout` |

```bash
# ★★ 看 unit 的 cgroup 到底涵蓋哪些程序
systemd-cgls -u pm2-ops.service
```

```text
Unit pm2-ops.service (/system.slice/pm2-ops.service):
├─2210 PM2 v5.4.3: God Daemon (/home/ops/.pm2)
├─2231 node /var/www/app/current/.output/server/index.mjs
└─2238 node /var/www/app/current/.output/server/index.mjs
```

```bash
# ★★★ 反向查：某個 pid 屬於哪個 unit
cat /proc/1899/cgroup
```

```text
0::/user.slice/user-1000.slice/user@1000.service/app.slice/session-3.scope
       # ★★★★ 不在 system.slice → systemctl stop 永遠殺不到它
```

> [!tip] 一勞永逸的做法 ★★★
> 給該帳號關掉 lingering，登出就清掉殘留的 user session 程序：
> ```bash
> loginctl disable-linger ops
> loginctl show-user ops -p Linger
> ```
> ```text
> Linger=no
> ```
> ★★ 但這是止血不是根治——正式機的應用本來就不該由互動 session 起。

#### ③ 部署腳本繞過 systemd ★★★★

部署腳本裡寫 `pm2 restart nuxt-app`，systemd **完全不知情**：

```bash
systemctl show pm2-ops -p ActiveEnterTimestamp
sudo -u ops PM2_HOME=/home/ops/.pm2 pm2 jlist \
  | jq -r '.[] | "\(.name)  uptime_since=\(.pm2_env.pm_uptime | ./1000 | todate)  restarts=\(.pm2_env.restart_time)  version=\(.pm2_env.version // "n/a")"'
```

```text
ActiveEnterTimestamp=Mon 2026-05-11 03:14:02 CST      # ★ systemd 以為服務三個月沒動過
nuxt-app  uptime_since=2026-08-28T01:20:11Z  restarts=47  version=2.8.1   # ★★★★ 應用今天早上才換版
```

**後果**：
- `systemctl status` 的 `Active: active (running) since ...` 對版本追蹤**毫無參考價值**
- 稽核問「這台前台最後一次變更是什麼時候」，systemd 給的答案是錯的
- 更嚴重：`pm2 restart` 之後如果沒 `pm2 save`，dump 還是舊的 → 見下面的「快照語意」

**修法**：部署腳本一律走 systemd 的介面，讓變更軌跡集中在一個地方。

```bash
# ✗ 不要
pm2 restart nuxt-app

# ✓ 架構 A：借用 unit 自帶的 ExecReload
sudo systemctl reload pm2-ops        # → 內部執行 pm2 reload all

# ✓ 架構 B：直接對自己的 unit 動作
sudo systemctl reload nuxt-app       # ExecReload=/usr/bin/pm2 reload <name>
sudo systemctl restart nuxt-app
```

#### ④ 兩個 PM2 daemon 同時存在 ★★★

有人在 unit 之外手動 `pm2 resurrect`（或就只是打了一次 `sudo pm2 list`——
**PM2 找不到 daemon 時會靜靜地自己啟一個**），機器上就有了兩個 God Daemon。

```bash
ps -eo user,pid,args | grep -F 'God Daemon' | grep -v grep
```

```text
ops    2210 PM2 v5.4.3: God Daemon (/home/ops/.pm2)
root   9931 PM2 v5.4.3: God Daemon (/root/.pm2)      # ★★★ 誰生的？多半是某次 sudo pm2 list
```

**兩種結局都很難查**：

```
結局一：第二份應用搶不到埠
  → pm2 list 顯示 errored、日誌是 EADDRINUSE
    → 但服務其實是好的（第一份在服務），沒有人發現異常

結局二：第二份搶到了埠（第一份剛好在重啟）
  → 對外服務的變成【舊版本的程式碼】
    → 部署明明成功、頁面卻沒更新 ★★★★
```

```bash
# ★★ 確認到底是誰在服務 3000 埠
sudo ss -lptnH 'sport = :3000' | awk '{print $6}'
sudo tr '\0' ' ' < /proc/1899/environ | tr ' ' '\n' | grep -E '^(PM2_HOME|NODE_ENV|PORT)='
```

```text
users:(("node",pid=1899,fd=22))
PM2_HOME=/root/.pm2         # ★★★★ 抓到了：對外服務的是 root 那一份
NODE_ENV=production
PORT=3000
```

### 日誌雙軌：事故當下最傷的一個盲區 ★★★

```
架構 A 的日誌流向

  PM2 God Daemon ──stdout──▶ systemd ──▶ journald
      「PM2 log: App [nuxt:0] online」              ← journalctl -u pm2-ops 只看得到這些

  node worker ──stdout──▶ PM2 攔截 ──▶ ~/.pm2/logs/nuxt-out.log
      「[nitro] Listening on http://127.0.0.1:3000」
      「Error: connect ECONNREFUSED 127.0.0.1:3306」  ← ★★★ 這些【不會】進 journal
                                                        → 集中蒐集只收 journal → 形同不存在
```

```bash
journalctl -u pm2-ops --since '1 hour ago' | tail -5
```

```text
Aug 28 01:20:11 web01 pm2[2210]: PM2 log: App [nuxt-app:0] online
Aug 28 01:20:11 web01 pm2[2210]: PM2 log: App [nuxt-app:1] online
                                    # ★★★ 應用自己的錯誤一行都沒有
```

```bash
# ★ 應用的實際日誌在這裡（機關的集中蒐集通常收不到）
sudo -u ops PM2_HOME=/home/ops/.pm2 pm2 describe nuxt-app | grep -E 'out log|error log'
```

```text
   out log path       │ /home/ops/.pm2/logs/nuxt-app-out.log
   error log path     │ /home/ops/.pm2/logs/nuxt-app-error.log
```

**三種對策比較**：

| 對策 | 做法 | 優點 | ★ 缺點 |
| --- | --- | --- | --- |
| **甲** `pm2-logrotate` | `pm2 install pm2-logrotate` | 一行搞定、PM2 原生 | ★★★ 日誌仍在檔案裡，**集中蒐集還是收不到**；只解決「磁碟被撐爆」 |
| **乙** 系統 logrotate + rsyslog 讀檔 | `/etc/logrotate.d/pm2` + `imfile` 模組 | 沿用機關既有的日誌管線 | ★★★ 多一層檔案輪替競態；輪替瞬間可能漏行；設定分散在兩處 |
| **丙** ★★★★ 讓應用日誌走 stdout 由 journald 收 | 架構 B（`pm2-runtime`）或架構 C | **單一來源**、稽核可見、`journalctl -u` 一次查完、集中蒐集直接收 | 需要改架構；`pm2 logs` 這個習慣要換成 `journalctl -u` |

> [!warning] 甲的「假解法」陷阱 ★★★
> 很多人裝了 `pm2-logrotate` 就以為日誌問題解決了。
> **它解決的是磁碟，不是可見性。** 稽核問「上週三 14:20 那次 5xx 的應用日誌在哪」，
> 答案還是「在某台機器某個使用者家目錄的一個檔案裡，而且可能已經被輪替壓縮掉了」。
> 日誌輪替的細節屬於 [[03-PM2-程序管理入門]] 與 [[02-日誌集中與輪替]]，本篇只講架構決策。

架構 B 下 journal 看到的是完整的應用輸出：

```bash
sudo journalctl -u nuxt-app -n 5 --no-pager
```

```text
Aug 28 09:31:02 web01 nuxt-app[4412]: [PM2] Starting /var/www/app/current/.output/server/index.mjs in cluster_mode (2 instances)
Aug 28 09:31:03 web01 nuxt-app[4412]: [nitro] Listening on http://127.0.0.1:3000
Aug 28 09:31:03 web01 nuxt-app[4412]: [nitro] Listening on http://127.0.0.1:3000
Aug 28 09:34:18 web01 nuxt-app[4412]: ERROR [db] connect ECONNREFUSED 127.0.0.1:3306   # ★★ 這行進得了集中蒐集
```

### `pm2 save` 的快照語意 ★★★★

**`dump.pm2` 是「當下狀態的快照」，不是「設定檔」。** 這個誤解造成的事故非常多。

```
ecosystem.config.cjs   ← 你在 git 裡維護的【意圖】
        │
        │  pm2 start ecosystem.config.cjs    ← 讀取一次，展開成執行中的程序
        ▼
   執行中的程序清單
        │
        │  pm2 save                          ← ★★★★ 把【當下】序列化成快照
        ▼
   $PM2_HOME/dump.pm2   ← 開機時 pm2 resurrect 讀的是【這個】，不是 ecosystem
```

所以：

```bash
# 改了 ecosystem（例如 instances 2 → 4、PORT 3000 → 3100）
vim /var/www/app/ecosystem.config.cjs
sudo -iu nodeapp pm2 reload /var/www/app/ecosystem.config.cjs --update-env
sudo -iu nodeapp pm2 list          # ★ 現在跑的是新設定，看起來一切正常

# ★★★★ 但是忘了這一行
sudo -iu nodeapp pm2 save

sudo reboot
# → 開機後 resurrect 讀的是【舊快照】：舊的埠、舊的 instances、舊的環境變數
```

**驗證 dump 與現況是否一致**（放進部署腳本的驗收段）：

```bash
sudo -iu nodeapp bash -c '
  diff <(pm2 jlist | jq -S "[.[] | {name, script: .pm2_env.pm_exec_path, instances: .pm2_env.instances, port: .pm2_env.env.PORT}]") \
       <(jq -S "[.[] | {name, script: .script, instances: .instances, port: .env.PORT}]" "$PM2_HOME/dump.pm2")
' && echo "★ dump 與現況一致" || echo "★★★★ 不一致：請執行 pm2 save"
```

```text
★ dump 與現況一致
```

> [!tip] 更徹底的解法：放棄 resurrect ★★★★
> 快照語意的所有麻煩，根源都是「開機時跑的東西不是版控裡的那份設定」。
> 架構 B 直接繞過它——unit 明確寫死要跑哪一份 ecosystem：
> ```ini
> ExecStart=/usr/bin/pm2-runtime start /var/www/app/current/ecosystem.config.cjs --env production
> ```
> 這樣**開機跑的就是 git 裡的那份**，`pm2 save` 這個步驟從流程裡整個消失。
> ★★★ 少一個要記得做的步驟，就少一個會忘記的事故。

### 三種架構對照與選型

| 面向 | **A** `pm2 startup` 產物 | **B** unit 跑 `pm2-runtime` | **C** 純 systemd（template unit） |
| --- | --- | --- | --- |
| 多核心利用 | ★★★★ cluster，一行搞定 | ★★★★ cluster，同 A | ★★★ 多實例 + Nginx upstream，要自己配 |
| 零停機 reload | ★★★★ `pm2 reload` | ★★★★ `systemctl reload` → `pm2 reload` | ★★ 要靠 socket activation 或滾動重啟兩個實例 |
| 日誌集中 | ★ **盲區**：只在 `~/.pm2/logs` | ★★★★ 走 journal，集中蒐集直收 | ★★★★★ 走 journal，最乾淨 |
| 稽核可見性 | ★ **盲區**：狀態反映 daemon | ★★★★ 反映 `pm2-runtime`，接近真實 | ★★★★★ 一個 unit 就是一個應用實例 |
| 維運熟悉度 | ★★ 要同時懂兩套工具 | ★★★ 主要用 systemctl，PM2 退居設定檔 | ★★★★★ 只有 systemd |
| 安全加固 | ★ 模板毫無加固 | ★★★★ 沙箱指令可完整套用 | ★★★★★ 最完整 |
| 設定即程式碼 | ★ dump.pm2 是二進位邏輯上的快照 | ★★★★ ecosystem 進 git | ★★★★ unit + EnvironmentFile 進 git |
| 導入成本 | ★★★★★ 零（已經是現況） | ★★★ 一次遷移，半天 | ★★ 要重寫部署與反向代理設定 |
| 相依層數 | node + pm2 | node + pm2 | **只有 node** |

> [!tip] 選型準則（機關環境）★★★
> ```
> 選 A：
>   · 開發／測試機、內部工具、沒有稽核要求
>   · 或【尚未遷移的既有系統】—— 至少要照本篇補上 PM2_HOME 檢查與監控
>
> 選 B：★★★★ 機關正式機的預設答案
>   · 已經在用 cluster、部署流程綁在 ecosystem 上
>   · 需要稽核可見性與日誌集中，但不想重寫部署
>   · 遷移成本最低、收益最大
>
> 選 C：
>   · 單一實例就夠（大部分機關前台的流量其實是這一類）
>   · 團隊裡沒有 Node 開發者長期維護
>   · 安全要求高（要套 ProtectSystem=strict、SystemCallFilter=）
>   · ★ 少一層相依 = 少一個會壞的東西、少一個要跟著 Node 升級的套件
> ```

> [!note] 架構 C 的多實例長什麼樣
> 用 template unit（完整寫法見 [[01-systemd-unit撰寫實戰]]）：
> ```bash
> sudo systemctl enable --now 'nuxt-app@3001.service' 'nuxt-app@3002.service'
> systemctl status 'nuxt-app@*'
> ```
> ```text
> ● nuxt-app@3001.service - Nuxt SSR (port 3001)
>      Active: active (running) since Fri 2026-08-28 09:31:02 CST; 5min ago
> ● nuxt-app@3002.service - Nuxt SSR (port 3002)
>      Active: active (running) since Fri 2026-08-28 09:31:02 CST; 5min ago
> ```
> Nginx 那一側用 `upstream` 分流，設定見 [[04-Nginx-反向代理與負載平衡]]。
> ★★ 這樣「掛掉一個實例」在 `systemctl status` 上是**看得見的**，架構 A 完全看不見。

### 三個逾時要對齊 ★★★★

```
使用者送出請求
     │
     ├─ 部署觸發 systemctl stop / restart
     │
     ▼
  systemd 送 SIGTERM 給 ExecStart 的主程序
     │      ├──────────────── TimeoutStopSec（預設 90s）────────────────┐
     ▼                                                                  │
  pm2-runtime 轉送 SIGTERM 給每個 worker                                 │
     │      ├──── kill_timeout（★★★★ PM2 預設只有 1600 ms）────┐        │
     ▼                                                          │        │
  應用的 SIGTERM handler：停止收新連線 → 等待 in-flight → 關 DB pool     │
     │      ├──── T_app（實測值，通常 3~15s）────┐              │        │
     ▼                                          ▼              ▼        ▼
  process.exit(0)                        PM2 送 SIGKILL   systemd 送 SIGKILL

★★★★ 必須成立：T_app  ≤  kill_timeout  ≤  TimeoutStopSec
     對不齊的後果：進行中的請求被硬砍（使用者看到 502）、寫入寫到一半（資料不一致）
```

**建議數值**（一般 Nuxt SSR / Laravel API 後端）：

| 層 | 參數 | 建議值 | ★ 理由 |
| --- | --- | --- | --- |
| 應用 | SIGTERM handler 實際耗時 | 實測，目標 ≤ 15s | ★★★ 沒實測過就不知道，見下面的量測方法 |
| PM2 | `kill_timeout` | `30000`（30s） | ★★★★ 預設 1600ms **遠遠不夠**，是最常見的漏設 |
| systemd | `TimeoutStopSec` | `45`（45s） | ★★★★ 要 > kill_timeout，留 15s 給 PM2 自己收尾 |
| systemd | `TimeoutStartSec` | `60` | ★★ cluster 多實例啟動慢，預設 90s 通常夠但明寫較好 |
| PM2 | `listen_timeout` | `10000` | ★★ 等應用開始 listen 的上限 |

**量測 T_app 的方法**：

```bash
# ★★★ 直接量：送 SIGTERM，看程序活到什麼時候
PID=$(pgrep -f 'index.mjs' | head -1)
date +%T.%3N; sudo kill -TERM "$PID"; while kill -0 "$PID" 2>/dev/null; do sleep 0.05; done; date +%T.%3N
```

```text
09:42:11.104
09:42:14.377        # ★ T_app ≈ 3.3 秒 → kill_timeout 給 30000 綽綽有餘
```

```bash
# ★★★★ 驗證整條停機路徑不會斷線：一邊打流量一邊 stop
# （在另一個終端）
while :; do curl -s -o /dev/null -w '%{http_code} ' http://127.0.0.1:3000/healthz; sleep 0.2; done
# （本終端）
time sudo systemctl stop nuxt-app
```

```text
200 200 200 200 200 200 000 000 ...        # ★ 只有連線被拒（000），沒有 502/504 → 停機是乾淨的
real    0m3.612s                            # ★★ 遠小於 TimeoutStopSec=45 → 沒有走到逾時
```

```bash
# ★★★ 如果 stop 剛好花滿 TimeoutStopSec，看 journal 確認是逾時而不是別的
sudo journalctl -u nuxt-app -n 20 --no-pager | grep -iE 'timed out|SIGKILL|Killing'
```

```text
Aug 28 09:44:02 web01 systemd[1]: nuxt-app.service: State 'stop-sigterm' timed out. Killing.
Aug 28 09:44:02 web01 systemd[1]: nuxt-app.service: Killing process 4412 (pm2-runtime) with signal SIGKILL.
   # ★★★★ 看到這兩行 = 每次部署都在硬砍連線，必須調整逾時
```

### PM2 應用怎麼接上前面幾篇的機制

[[04-服務自動復原與看門狗]] 教的健康檢查 timer 與 `OnFailure=` 告警，
在 PM2 情境下**掛錯層就完全沒效果**：

| 機制 | 架構 A 掛在 `pm2-ops.service` | 架構 B/C 掛在應用 unit |
| --- | --- | --- |
| `Restart=on-failure` | ★ 只重啟 daemon，應用死了不觸發 | ★★★★ 有效 |
| `OnFailure=alert@%n.service` | ★ 幾乎不會觸發（daemon 很少死） | ★★★★ 應用真的掛了就發告警 |
| `WatchdogSec=` + `sd_notify` | ✗ 不可用（PM2 不支援 notify 協定） | ★★ 架構 C 可用（應用自己送 watchdog） |
| 健康檢查 timer | ★★★★ **唯一可靠的一層**，必須做 | ★★★ 仍建議做（第二道網） |

> [!danger] ★★★★ 健康檢查要打應用的端點，不要看 PM2 狀態
> ```bash
> # ✗ 錯：pm2 list 顯示 online 不代表應用能服務
> #     （Node 程序活著但 event loop 卡死、DB pool 耗盡都會是 online）
> pm2 list | grep -q online && echo OK
>
> # ✓ 對：打真正的健康端點
> curl -fsS --max-time 5 http://127.0.0.1:3000/healthz
> ```
> ```text
> {"status":"ok","db":"up","uptime":3821}
> ```
> 健康端點要**真的檢查下游**（DB 連得上、快取通得了），不能只回 `200 OK`。
> timer 的完整寫法見 [[04-服務自動復原與看門狗]]，本篇只點名「打哪裡」。

架構 A 下唯一能發現「應用死了」的方式，就是外部健康檢查：

```ini
# /etc/systemd/system/nuxt-health.service（節錄）
[Service]
Type=oneshot
ExecStart=/usr/local/bin/nuxt-healthcheck.sh
# ★★★★ OnFailure 掛在【健康檢查】上才有意義，掛在 pm2-ops 上等於沒掛
OnFailure=alert@%n.service
```

### ★★★★ 重開機是唯一可信的驗收

`systemctl restart` 通過**不代表**開機會成功。兩者的差異剛好涵蓋四類最難查的問題：

| 問題類別 | `systemctl restart` 會發現嗎 | `reboot` 會發現嗎 |
| --- | --- | --- |
| ★★★★★ `PM2_HOME` / dump 不一致 | ❌（daemon 還在，狀態沿用記憶體中的清單） | ✅ |
| ★★★★ PATH / node 路徑錯誤 | ⚠️ 有時會（若 PATH 本來就錯則會） | ✅ |
| ★★★★ 掛載相依（`/home`、NFS、LVM 尚未就緒） | ❌（早就掛好了） | ✅ |
| ★★★★ 啟動順序（DB 還沒起來、網路還沒綁 IP） | ❌ | ✅ |
| ★★★ `systemctl enable` 漏做 | ❌ | ✅ |

**reboot 驗收清單**（每一項都要有輸出佐證，存檔備查）：

| # | 檢查項 | 指令 | 預期結果 |
| --- | --- | --- | --- |
| 1 | unit 已 enable | `systemctl is-enabled nuxt-app` | `enabled` |
| 2 | 開機後自動 active | `systemctl is-active nuxt-app` | `active` |
| 3 | ★★★★ 應用真的在服務 | `curl -fsS http://127.0.0.1:3000/healthz` | `{"status":"ok",...}` |
| 4 | ★★★★ 只有一個 PM2 daemon | `ps -eo args \| grep -c 'God Daemon'` | `1` |
| 5 | ★★★ instances 數量正確 | `sudo -iu nodeapp pm2 jlist \| jq 'length'` | 與 ecosystem 一致 |
| 6 | ★★★ 日誌進得了 journal | `journalctl -u nuxt-app -b \| grep -c nitro` | `> 0` |
| 7 | ★★ 啟動耗時合理 | `systemd-analyze blame \| grep nuxt-app` | `< 30s` |
| 8 | ★★★ 沒有失敗的 unit | `systemctl --failed` | `0 loaded units listed.` |
| 9 | ★★★ 對外真的通 | `curl -fsS -o /dev/null -w '%{http_code}\n' https://前台網址/` | `200` |
| 10 | ★★★ 舊 unit 已消失 | `systemctl list-unit-files 'pm2-*'` | `0 unit files listed.` |

> [!warning] 機關環境怎麼安排這次重開機 ★★★
> 「不敢重開機」的機器就是「不知道能不能開起來」的機器，風險只會隨時間累積。
> 依 [[08-變更管理流程]] 的節奏辦：
> ```
> 【事前】
>   · 申請維護窗（機關通常是週三或週六凌晨），公告停機時間
>   · 建立回滾點：VM 快照 / LVM snapshot；備份 unit、ecosystem、dump.pm2
>   · 準備好【帶外管理通道】（iDRAC / iLO / PVE console）★★★★
>     —— 服務起不來還能 SSH，網路起不來就只剩帶外
>   · 事先在測試機做過一次完整 reboot 驗收
> 【當下】
>   · 一人操作、一人看螢幕對照驗收清單
>   · reboot 後 15 分鐘內跑完上表 10 項
> 【事後】
>   · 驗收輸出存檔（機關稽核要看得到證據）
>   · 快照保留至少 7 天再刪
> ```

---

## 完整實戰範例

### 情境

一台機關前台主機 `web01`（Ubuntu 22.04），跑 Nuxt SSR：

```
現況（三年前設定，設定者已離職）
  · pm2 startup 產生的 pm2-ops.service，跑在【個人帳號 ops】下
  · 應用日誌只在 /home/ops/.pm2/logs/
  · 部署腳本直接 pm2 restart，systemd 完全不知情
  · 沒有人敢重開機

稽核新要求
  ① 所有服務要能用 systemctl 看狀態
  ② 日誌要進集中蒐集平台
  ③ 服務不得跑在個人帳號下（人員異動就是資安風險）

目標：遷移到【架構 B】—— 自寫 unit 跑 pm2-runtime，專屬系統帳號 nodeapp
```

### 步驟總覽

```
① 現況蒐證並存檔      ── 不可跳過，這是回滾的依據
② 建立專屬系統帳號與目錄
③ 撰寫 nuxt-app.service
④ 切換（停舊 → 起新）  ── ★★★★ 中間有短暫停機，要在維護窗做
⑤ 驗收（含真的 reboot）
⑥ 回滾腳本（先寫好、先測過，才敢執行 ④）
```

### 主腳本

```bash
#!/usr/bin/env bash
# /usr/local/bin/pm2-to-systemd-migrate.sh
# 把 pm2 startup（架構 A）遷移到 systemd + pm2-runtime（架構 B）
# 用法：
#   sudo pm2-to-systemd-migrate.sh snapshot     # ① 只蒐證，不改任何東西
#   sudo pm2-to-systemd-migrate.sh prepare      # ② ③ 建帳號、建目錄、寫 unit（仍不切換）
#   sudo pm2-to-systemd-migrate.sh cutover      # ④ 切換（會短暫停機）
#   sudo pm2-to-systemd-migrate.sh verify       # ⑤ 驗收
set -euo pipefail

OLD_USER="ops"
OLD_UNIT="pm2-${OLD_USER}.service"
NEW_USER="nodeapp"
NEW_UNIT="nuxt-app.service"
NEW_HOME="/var/lib/${NEW_USER}"
APP_DIR="/var/www/app/current"
ECOSYSTEM="${APP_DIR}/ecosystem.config.cjs"
PORT=3000
HEALTH="http://127.0.0.1:${PORT}/healthz"
TS="$(date +%Y%m%d-%H%M%S)"
SNAP="/var/backups/pm2-migration-${TS}"

log()  { printf '\033[1;32m[%s]\033[0m %s\n' "$(date +%T)" "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[FATAL]\033[0m %s\n' "$*" >&2; exit 1; }

require_root() { [[ $EUID -eq 0 ]] || die "請用 sudo 執行"; }

# ═══════════════════════════════════════════════════════════
# ① 現況蒐證 —— ★★★★ 回滾全靠這一份，絕對不能跳過
# ═══════════════════════════════════════════════════════════
do_snapshot() {
  require_root
  log "建立蒐證目錄 ${SNAP}"
  install -d -m 0700 "$SNAP"

  log "[1/8] 舊 unit 全文"
  systemctl cat "$OLD_UNIT" > "${SNAP}/old-unit.txt" 2>&1 \
    || warn "找不到 ${OLD_UNIT}（可能是別的使用者名稱，請確認）"

  log "[2/8] 舊 unit 的環境變數與關鍵屬性"
  systemctl show "$OLD_UNIT" \
    -p Environment -p User -p Group -p Type -p PIDFile \
    -p ExecStart -p ExecStop -p Restart -p TimeoutStopUSec \
    -p ActiveState -p ActiveEnterTimestamp \
    > "${SNAP}/old-unit-props.txt"

  # ★★★★★ 這一段是本腳本的核心：找出【真正】在服務的 PM2_HOME
  log "[3/8] 掃描所有 PM2 God Daemon 與其 PM2_HOME"
  ps -eo user,pid,args | grep -F 'God Daemon' | grep -v grep \
    > "${SNAP}/god-daemons.txt" || true
  local n
  n=$(wc -l < "${SNAP}/god-daemons.txt")
  cat "${SNAP}/god-daemons.txt"
  if [[ "$n" -gt 1 ]]; then
    warn "★★★★ 偵測到 ${n} 個 PM2 daemon —— 先釐清哪一個在服務再繼續！"
  elif [[ "$n" -eq 0 ]]; then
    die "★★★★ 找不到任何 PM2 daemon，現況與預期不符，請人工確認"
  fi

  log "[4/8] 各候選 PM2_HOME 的 dump.pm2 時間戳"
  : > "${SNAP}/dump-inventory.txt"
  for h in "/home/${OLD_USER}/.pm2" /root/.pm2 "${NEW_HOME}/.pm2"; do
    if [[ -f "${h}/dump.pm2" ]]; then
      printf '%-30s %s  %s bytes\n' "$h" \
        "$(stat -c '%y' "${h}/dump.pm2")" "$(stat -c '%s' "${h}/dump.pm2")"
      cp -a "${h}/dump.pm2" "${SNAP}/dump.pm2.$(basename "$(dirname "$h")")" 2>/dev/null || true
    else
      printf '%-30s (無)\n' "$h"
    fi
  done | tee -a "${SNAP}/dump-inventory.txt"

  log "[5/8] 誰在監聽 ${PORT}，它的 PM2_HOME 是什麼"
  ss -lptnH "sport = :${PORT}" > "${SNAP}/listener.txt" || true
  local lpid
  lpid=$(ss -lptnH "sport = :${PORT}" 2>/dev/null \
         | grep -oP 'pid=\K[0-9]+' | head -1 || true)
  if [[ -n "$lpid" ]]; then
    tr '\0' '\n' < "/proc/${lpid}/environ" \
      | grep -E '^(PM2_HOME|NODE_ENV|PORT|HOST)=' \
      | tee -a "${SNAP}/listener.txt"
    readlink -f "/proc/${lpid}/exe" | tee -a "${SNAP}/listener.txt"
  else
    warn "★★★ 沒有程序在監聽 ${PORT}，服務可能已經是掛的"
  fi

  log "[6/8] PM2 程序清單（用舊 unit 宣告的 PM2_HOME）"
  local unit_pm2_home
  unit_pm2_home=$(systemctl show "$OLD_UNIT" -p Environment --value \
                  | tr ' ' '\n' | grep -oP '^PM2_HOME=\K.*' || echo "/home/${OLD_USER}/.pm2")
  echo "unit 宣告的 PM2_HOME = ${unit_pm2_home}" | tee "${SNAP}/pm2-list.txt"
  sudo -u "$OLD_USER" env "PM2_HOME=${unit_pm2_home}" pm2 jlist 2>/dev/null \
    | jq '.' >> "${SNAP}/pm2-list.txt" || warn "pm2 jlist 失敗（daemon 可能沒起來）"

  log "[7/8] node / pm2 / pm2-runtime 的絕對路徑"
  { readlink -f "$(command -v node)"        || echo 'node: NOT FOUND';
    readlink -f "$(command -v pm2)"         || echo 'pm2: NOT FOUND';
    readlink -f "$(command -v pm2-runtime)" || echo 'pm2-runtime: NOT FOUND';
    node --version; pm2 --version;
  } | tee "${SNAP}/binaries.txt"

  log "[8/8] 應用設定與 Nginx 上游"
  cp -a "$ECOSYSTEM" "${SNAP}/" 2>/dev/null || warn "找不到 ${ECOSYSTEM}"
  grep -rn "127.0.0.1:${PORT}" /etc/nginx/ > "${SNAP}/nginx-upstream.txt" 2>/dev/null || true
  curl -fsS --max-time 5 "$HEALTH" > "${SNAP}/health-before.json" 2>&1 \
    || warn "★★★ 遷移【前】健康檢查就失敗了，先修好再遷移"

  chmod -R go-rwx "$SNAP"
  log "蒐證完成 → ${SNAP}"
  log "★★★★ 請人工檢視 ${SNAP}/dump-inventory.txt 與 god-daemons.txt 再進行 prepare"
}

# ═══════════════════════════════════════════════════════════
# ② ③ 建帳號、目錄、unit（不切換，可安全重跑）
# ═══════════════════════════════════════════════════════════
do_prepare() {
  require_root
  local node_bin pm2_runtime_bin
  node_bin=$(readlink -f "$(command -v node)")       || die "找不到 node"
  pm2_runtime_bin=$(readlink -f "$(command -v pm2-runtime)") \
    || die "找不到 pm2-runtime，請先 npm i -g pm2"
  # ★★★★ 絕不接受 nvm 路徑
  case "$node_bin" in
    *"/.nvm/"*) die "node 走的是 nvm（${node_bin}）。請先改用系統套件安裝，見「Node 安裝與版本管理」" ;;
  esac
  log "node        = ${node_bin}"
  log "pm2-runtime = ${pm2_runtime_bin}"

  log "建立系統帳號 ${NEW_USER}"
  if ! id -u "$NEW_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "$NEW_HOME" \
            --shell /usr/sbin/nologin --comment 'Nuxt app service account' "$NEW_USER"
  else
    log "帳號已存在，略過"
  fi
  install -d -o "$NEW_USER" -g "$NEW_USER" -m 0750 "${NEW_HOME}/.pm2"

  log "移轉程式碼擁有者到 ${NEW_USER}"
  [[ -d "$APP_DIR" ]] || die "找不到 ${APP_DIR}"
  chown -R "${NEW_USER}:${NEW_USER}" /var/www/app
  find /var/www/app -type d -exec chmod 0755 {} +
  find /var/www/app -type f -exec chmod 0644 {} +
  # ★★★ .env 含 DB 密碼，只給服務帳號讀
  if [[ -f /var/www/app/shared/.env ]]; then
    chmod 0640 /var/www/app/shared/.env
    chown "${NEW_USER}:${NEW_USER}" /var/www/app/shared/.env
  fi

  log "寫入 /etc/systemd/system/${NEW_UNIT}"
  cat > "/etc/systemd/system/${NEW_UNIT}" <<UNIT
[Unit]
Description=Nuxt SSR front-end (PM2 runtime, cluster mode)
Documentation=https://pm2.keymetrics.io/docs/usage/docker-pm2-nodejs/
# ★★★ network.target 不保證 IP 綁好，要用 network-online
Wants=network-online.target
After=network-online.target mysql.service
# ★★★★ 開機時 /var/lib 尚未就緒會直接失敗，明寫掛載相依
RequiresMountsFor=${NEW_HOME} ${APP_DIR}
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
# ★★★★ pm2-runtime 在前景執行 → Type=simple，systemd 監看的就是真實的應用進程樹
Type=simple
User=${NEW_USER}
Group=${NEW_USER}
WorkingDirectory=${APP_DIR}

# ★★★★★ PM2_HOME 寫絕對路徑，不靠 \$HOME 推導
Environment=PM2_HOME=${NEW_HOME}/.pm2
Environment=NODE_ENV=production
Environment=HOST=127.0.0.1
Environment=PORT=${PORT}
EnvironmentFile=-/var/www/app/shared/.env

# ★★★★ 絕對路徑，不依賴 PATH
ExecStartPre=/usr/bin/test -x ${node_bin}
ExecStart=${pm2_runtime_bin} start ${ECOSYSTEM} --env production
ExecReload=/usr/bin/pm2 reload ${ECOSYSTEM} --env production --update-env

# ★★★★ 三個逾時對齊：T_app(≈3s) ≤ kill_timeout(30s) ≤ TimeoutStopSec(45s)
TimeoutStartSec=60
TimeoutStopSec=45
KillMode=control-group
KillSignal=SIGTERM

# ★★★ 第二層安全網：PM2 自己救不回來才輪到 systemd
Restart=on-failure
RestartSec=10
# ★★★★ 應用真的失敗才告警，掛在這一層才有意義（見「服務自動復原與看門狗」）
OnFailure=alert@%n.service

# ★★★★ 日誌走 journal → 集中蒐集直接收得到
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nuxt-app

# ★★★ 安全加固（pm2 startup 的模板一項都沒有）
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${NEW_HOME}/.pm2 /var/www/app/shared/storage
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
RestrictSUIDSGID=true
LockPersonality=true
# ★★★★ Node 的 JIT 需要可寫可執行記憶體，這一項【必須】false
MemoryDenyWriteExecute=false
# ★★★ core dump 關掉：崩潰時的記憶體含 DB 密碼與個資
LimitCORE=0

LimitNOFILE=65535
MemoryMax=1500M
CPUQuota=200%

[Install]
WantedBy=multi-user.target
UNIT

  chmod 0644 "/etc/systemd/system/${NEW_UNIT}"
  systemd-analyze verify "/etc/systemd/system/${NEW_UNIT}" \
    || die "unit 語法檢查未過"
  systemctl daemon-reload
  log "★ unit 已就緒但【尚未啟用】。請人工檢視後再執行 cutover"
  systemctl cat "$NEW_UNIT"
}

# ═══════════════════════════════════════════════════════════
# ④ 切換 —— ★★★★ 有短暫停機，務必在維護窗執行
# ═══════════════════════════════════════════════════════════
do_cutover() {
  require_root
  [[ -f "/etc/systemd/system/${NEW_UNIT}" ]] || die "請先執行 prepare"

  log "[1/6] 停掉舊架構的應用（避免兩份搶 ${PORT}）"
  sudo -u "$OLD_USER" env "PM2_HOME=/home/${OLD_USER}/.pm2" pm2 delete all || true
  sudo -u "$OLD_USER" env "PM2_HOME=/home/${OLD_USER}/.pm2" pm2 save --force || true

  log "[2/6] 移除舊 unit（pm2 unstartup 會 disable + 刪檔 + daemon-reload）"
  sudo -u "$OLD_USER" env "PM2_HOME=/home/${OLD_USER}/.pm2" \
       PATH=/usr/bin:/bin pm2 unstartup systemd || true
  systemctl disable --now "$OLD_UNIT" 2>/dev/null || true
  rm -f "/etc/systemd/system/${OLD_UNIT}"
  systemctl daemon-reload

  log "[3/6] 殺掉所有殘留的 PM2 daemon"
  sudo -u "$OLD_USER" env "PM2_HOME=/home/${OLD_USER}/.pm2" pm2 kill || true
  # ★★★ 手動起的 daemon 不在任何 unit 的 cgroup 內，只能直接砍
  pkill -f 'God Daemon' || true
  sleep 2
  if pgrep -f 'God Daemon' >/dev/null; then
    warn "★★★ 仍有 PM2 daemon 存活："
    ps -eo user,pid,args | grep -F 'God Daemon' | grep -v grep
    die "請人工釐清後重跑"
  fi

  log "[4/6] 確認 ${PORT} 已釋放"
  local waited=0
  while ss -lntH "sport = :${PORT}" | grep -q .; do
    ((waited++)); [[ $waited -gt 20 ]] && die "★★★★ ${PORT} 仍被佔用，中止切換"
    sleep 1
  done
  log "${PORT} 已釋放（等待 ${waited}s）"

  log "[5/6] 清理舊的 dump.pm2（已備份在 ${SNAP} 或先前的蒐證目錄）"
  for h in "/home/${OLD_USER}/.pm2" /root/.pm2; do
    [[ -f "${h}/dump.pm2" ]] && mv -v "${h}/dump.pm2" "${h}/dump.pm2.migrated-${TS}"
  done

  log "[6/6] 啟用新 unit"
  systemctl enable --now "$NEW_UNIT"
  sleep 8
  systemctl is-active --quiet "$NEW_UNIT" || {
    journalctl -u "$NEW_UNIT" -n 40 --no-pager
    die "★★★★ 新 unit 沒起來，請執行 pm2-to-systemd-rollback.sh"
  }
  log "切換完成，請立即執行 verify"
}

# ═══════════════════════════════════════════════════════════
# ⑤ 驗收
# ═══════════════════════════════════════════════════════════
do_verify() {
  local fail=0
  chk() { # chk <說明> <期望> <實際>
    if [[ "$2" == "$3" ]]; then printf '  ✓ %-40s %s\n' "$1" "$3"
    else printf '  ✗ %-40s 期望=%s 實際=%s\n' "$1" "$2" "$3"; fail=1; fi
  }
  log "驗收 ${NEW_UNIT}"
  chk "unit 已 enable"      "enabled" "$(systemctl is-enabled "$NEW_UNIT" 2>&1)"
  chk "unit active"         "active"  "$(systemctl is-active  "$NEW_UNIT" 2>&1)"
  chk "只有一個 PM2 daemon"  "1"       "$(ps -eo args | grep -cF 'God Daemon' || true)"
  chk "舊 unit 已消失"       "0"       "$(systemctl list-unit-files 'pm2-*' --no-legend | wc -l)"
  chk "沒有 failed unit"     "0"       "$(systemctl --failed --no-legend | wc -l)"

  printf '  ─ 健康端點：'
  if curl -fsS --max-time 5 "$HEALTH"; then echo; else echo " ✗ 失敗"; fail=1; fi

  printf '  ─ 應用日誌進 journal：'
  local n; n=$(journalctl -u "$NEW_UNIT" -b --no-pager | grep -ci 'nitro\|Listening' || true)
  if [[ "$n" -gt 0 ]]; then echo "✓ ${n} 行"; else echo "✗ 0 行（日誌沒走 stdout）"; fail=1; fi

  printf '  ─ instances 數：'
  sudo -u "$NEW_USER" env "PM2_HOME=${NEW_HOME}/.pm2" pm2 jlist 2>/dev/null \
    | jq -r 'length' || { echo "✗"; fail=1; }

  echo
  if [[ $fail -eq 0 ]]; then
    log "★★★★ 全數通過。但這還不算完成 —— 請安排維護窗真的 reboot 一次再跑一輪。"
  else
    die "★★★★ 有項目未通過，考慮回滾"
  fi
}

case "${1:-}" in
  snapshot) do_snapshot ;;
  prepare)  do_prepare  ;;
  cutover)  do_cutover  ;;
  verify)   do_verify   ;;
  *) die "用法：$0 {snapshot|prepare|cutover|verify}" ;;
esac
```

### 回滾腳本

★★★★ **先寫好、先在測試機跑過一遍，才有資格執行 `cutover`。**

```bash
#!/usr/bin/env bash
# /usr/local/bin/pm2-to-systemd-rollback.sh
# 用法：sudo pm2-to-systemd-rollback.sh /var/backups/pm2-migration-20260828-091500
set -euo pipefail

SNAP="${1:?請指定蒐證目錄，例如 /var/backups/pm2-migration-YYYYmmdd-HHMMSS}"
OLD_USER="ops"
OLD_HOME="/home/${OLD_USER}/.pm2"
NEW_UNIT="nuxt-app.service"
PORT=3000
HEALTH="http://127.0.0.1:${PORT}/healthz"

log() { printf '\033[1;36m[rollback %s]\033[0m %s\n' "$(date +%T)" "$*"; }
die() { printf '\033[1;31m[FATAL]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "請用 sudo 執行"
[[ -d "$SNAP" ]]  || die "找不到蒐證目錄 ${SNAP}"

log "[1/6] 停用新 unit"
systemctl disable --now "$NEW_UNIT" 2>/dev/null || true
sleep 3

log "[2/6] 確認 ${PORT} 釋放"
for i in $(seq 1 20); do
  ss -lntH "sport = :${PORT}" | grep -q . || break
  [[ "$i" -eq 20 ]] && die "★★★★ ${PORT} 未釋放，人工介入"
  sleep 1
done

log "[3/6] 還原舊帳號的 dump.pm2"
DUMP=$(ls -1 "${SNAP}"/dump.pm2.* 2>/dev/null | head -1) \
  || die "蒐證目錄裡沒有 dump.pm2 備份"
install -o "$OLD_USER" -g "$OLD_USER" -m 0600 "$DUMP" "${OLD_HOME}/dump.pm2"
log "已還原 $(basename "$DUMP") → ${OLD_HOME}/dump.pm2"

log "[4/6] 重建 pm2 startup"
PM2_BIN=$(readlink -f "$(command -v pm2)")
sudo -u "$OLD_USER" env "PM2_HOME=${OLD_HOME}" PATH=/usr/bin:/bin "$PM2_BIN" kill || true
env PATH="$PATH:/usr/bin" "$PM2_BIN" startup systemd \
    -u "$OLD_USER" --hp "/home/${OLD_USER}"
systemctl daemon-reload
systemctl enable --now "pm2-${OLD_USER}.service"

log "[5/6] resurrect 並確認清單非空"
sudo -u "$OLD_USER" env "PM2_HOME=${OLD_HOME}" "$PM2_BIN" resurrect
N=$(sudo -u "$OLD_USER" env "PM2_HOME=${OLD_HOME}" "$PM2_BIN" jlist | jq 'length')
[[ "$N" -gt 0 ]] || die "★★★★★ resurrect 出 0 個應用，回滾失敗，改用 VM 快照還原"
log "已還原 ${N} 個應用"

log "[6/6] 驗證服務"
for i in $(seq 1 15); do
  curl -fsS --max-time 5 "$HEALTH" && { echo; log "★ 回滾成功"; exit 0; }
  sleep 2
done
die "★★★★★ 健康檢查未通過，請改用 VM 快照還原並通報"
```

### 執行順序與驗收檢查表

```bash
sudo /usr/local/bin/pm2-to-systemd-migrate.sh snapshot   # 平日就可以跑，不影響服務
sudo /usr/local/bin/pm2-to-systemd-migrate.sh prepare    # 平日就可以跑，不影響服務
# ↓ 以下在維護窗執行
sudo /usr/local/bin/pm2-to-systemd-migrate.sh cutover
sudo /usr/local/bin/pm2-to-systemd-migrate.sh verify
```

| # | 檢查項 | 指令 | 預期結果 |
| --- | --- | --- | --- |
| 1 | ★★★ 蒐證完整 | `ls /var/backups/pm2-migration-*/` | 含 `old-unit.txt`、`dump.pm2.*`、`binaries.txt` |
| 2 | ★★★ unit 語法正確 | `systemd-analyze verify /etc/systemd/system/nuxt-app.service` | 無輸出 |
| 3 | ★★★★ 狀態反映真實應用 | `systemctl status nuxt-app` | `Active: active (running)`，`Main PID` 是 `pm2-runtime` |
| 4 | ★★★★ 應用 stdout 進 journal | `journalctl -u nuxt-app -b \| grep -i nitro` | 看得到 `Listening on http://127.0.0.1:3000` |
| 5 | ★★★★ 健康端點通 | `curl -fsS http://127.0.0.1:3000/healthz` | `{"status":"ok",...}` |
| 6 | ★★★ 殺掉 worker 會自動補 | `sudo pkill -f 'index.mjs' -n; sleep 5; curl -fsS $HEALTH` | 5 秒內恢復 200 |
| 7 | ★★★★ reload 不斷線 | 一邊 `while :; do curl -s -o /dev/null -w '%{http_code} ' $HEALTH; done`，一邊 `sudo systemctl reload nuxt-app` | 全程 `200`，沒有 `000` / `502` |
| 8 | ★★★★ stop 不硬砍 | `time sudo systemctl stop nuxt-app` | 秒數 << 45s，journal 無 `timed out. Killing` |
| 9 | ★★★★ 只有一個 daemon | `ps -eo args \| grep -c 'God Daemon'` | `1` |
| 10 | ★★★★ 舊 unit 已清除 | `systemctl list-unit-files 'pm2-*'` | `0 unit files listed.` |
| 11 | ★★★ 安全評分改善 | `systemd-analyze security nuxt-app` | `< 6.0`（舊的 pm2-ops 通常 9.x） |
| 12 | ★★★★★ **真的 reboot 一次** | `sudo reboot`，開機後重跑第 3~10 項 | 全數通過 |
| 13 | ★★★ 對外前台正常 | `curl -fsS -o /dev/null -w '%{http_code}\n' https://前台網址/` | `200` |
| 14 | ★★★ 集中蒐集收得到 | 在 SIEM 查 `web01` + `nuxt-app` 最近 10 分鐘 | 有應用層日誌 |

> [!warning] 遷移期間避免兩份應用搶同一個埠 ★★★★
> `cutover` 第 [4] 步的等待迴圈就是為了這件事。若跳過，最糟的情況是：
> 新 unit 起來時舊 worker 還握著 3000，cluster 的其中一個 instance 拿到 `EADDRINUSE` 而 errored，
> **另一個 instance 卻正常**——`systemctl status` 綠燈、健康檢查也通過（有一半機率打到好的那個），
> 但實際上只有一半的處理能力，而且沒有人會發現。
>
> 若不能接受任何停機，改用**換埠切換**：新 unit 先跑在 3100 → 驗收 → 改 Nginx upstream →
> `systemctl reload nginx` → 停舊的 3000。詳見 [[06-部署自動化]]。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 重開機後前台整個不見，但 `systemctl status pm2-ops` 是 `active (running)` | unit 的 `PM2_HOME` 與當初 `pm2 save` 的 `PM2_HOME` 不同（多半是有人用 `sudo pm2 save` 存到 `/root/.pm2`），`resurrect` 讀到空的或極舊的 dump | 跑「PM2_HOME 一致性檢查」四道指令；以 unit 宣告的 `PM2_HOME` 重新 `pm2 start` + `pm2 save`；長期改成架構 B |
| ★★★★ `systemctl status` 綠燈，網站卻 502 | 架構 A 的 `Type=forking` + `PIDFile` 監看的是 PM2 God Daemon，worker 全 `errored` 也不影響判定 | 短期：加健康檢查 timer 打 `/healthz`；長期：遷到架構 B/C |
| ★★★★ 開機起不來，手動 `systemctl start` 卻完全正常 | `Environment=PATH=` 裡的 node 目錄在 `/home/*/.nvm/...`，開機時 `/home` 未掛載或版本已換 | 改用系統套件的 `/usr/bin/node`；`ExecStart` 寫絕對路徑；補 `RequiresMountsFor=` |
| ★★★★ 服務每幾秒重啟一次，journal 裡兩層日誌交錯 | systemd 的 `Restart=` 與 PM2 的 `autorestart` 疊加，且 `RestartSec` < PM2 的 `min_uptime` | `RestartSec=10` ≥ `min_uptime`；設 `StartLimitIntervalSec`/`StartLimitBurst`；PM2 側設 `max_restarts` |
| ★★★★ 每次部署都有零星 502、資料庫寫入不完整 | `kill_timeout` 用預設 1600 ms，小於應用 SIGTERM 處理耗時；或 `TimeoutStopSec` < `kill_timeout` | 實測 T_app；設 `kill_timeout: 30000`、`TimeoutStopSec=45` |
| ★★★★ 重開機後跑回舊設定（舊埠、舊 instances、舊環境變數） | 改了 `ecosystem.config.cjs` 卻沒 `pm2 save`，`dump.pm2` 仍是舊快照 | 部署流程最後加 `pm2 save` 與 dump/現況 diff 驗證；或改架構 B 讓 unit 直接指定 ecosystem |
| ★★★★ `systemctl stop` 顯示 inactive，但埠仍被佔用 | 殘留程序在 `user@1000.service` 的 cgroup，不屬於該 unit，`systemctl stop` 殺不到 | `cat /proc/<pid>/cgroup` 確認歸屬；手動清；`loginctl disable-linger`；禁止互動式 `pm2 start` |
| ★★★★ 部署成功但頁面沒更新 | 兩個 PM2 daemon（不同 `PM2_HOME`）並存，對外服務的是舊那份 | `ps -eo user,args \| grep 'God Daemon'` 必須只有 1 行；查 `/proc/<listener_pid>/environ` 的 `PM2_HOME` |
| ★★★ `systemctl stop` 卡滿 90 秒才結束 | `ExecStop=pm2 kill` 連到別的 `PM2_HOME` 或 `rpc.sock` 已損壞，殺不到東西，systemd 只好等逾時 | 明寫 `TimeoutStopSec=45`；修正 `PM2_HOME`；`rm -f $PM2_HOME/rpc.sock $PM2_HOME/pub.sock` 後重啟 |
| ★★★ 事故當下集中蒐集平台完全查不到應用日誌 | 應用 stdout 被 PM2 攔到 `$PM2_HOME/logs/*.log`，只有 daemon 訊息進 journal | 改架構 B（`pm2-runtime` → journal）；過渡期用 rsyslog `imfile` 收檔案 |
| ★★★ `pm2 list` 是空的，但網站活得好好的 | 你的 shell 的 `PM2_HOME` 與服務用的不同（`sudo pm2` vs `pm2`，或 `sudo -u` 沒換 `$HOME`） | 一律 `sudo -iu <user> pm2 ...` 或明寫 `PM2_HOME=... pm2 ...` |
| ★★★ 加了 `ProtectHome=true` 後 unit 起不來，journal 顯示權限錯誤 | `PM2_HOME` 在 `/home/...` 底下，被沙箱擋住 | 把 `PM2_HOME` 移到 `/var/lib/<user>/.pm2`，並加 `ReadWritePaths=` |
| ★★★ 架構 B 下 unit 起來就馬上 `failed`，journal 顯示 `Cannot find module` | `WorkingDirectory` 沒設或設錯，ecosystem 裡的相對路徑（`script: '.output/server/index.mjs'`）解析不到 | 設 `WorkingDirectory=`，或 ecosystem 裡的 `cwd` 與 `script` 都寫絕對路徑 |
| ★★★ 加了 `MemoryDenyWriteExecute=true` 後 Node 直接 crash | Node 的 V8 JIT 需要同時可寫可執行的記憶體頁 | ★★★★ 這一項對 Node **必須** `false`（或整行不寫） |
| ★★ `systemctl reload` 沒有任何效果 | 架構 A 的 `ExecReload=pm2 reload all` 對 `fork` 模式無效（只有 `cluster` 模式才是零停機重載） | 確認 `exec_mode: 'cluster'`；fork 模式只能 `restart` |
| ★★ `systemd-analyze security` 給 9.x UNSAFE | `pm2 startup` 模板完全沒有加固指令 | 遷到架構 B/C 並套用本篇 unit 的沙箱段落 |

### 排查步驟

當有人回報「Node 服務怪怪的」，依序跑完這八步，問題一定會落在某一格。

**【1】現在對外服務的到底是哪個程序？**

```bash
sudo ss -lptnH 'sport = :3000'
```

```text
LISTEN 0 511 127.0.0.1:3000 users:(("node",pid=1899,fd=22))
```

- 有輸出 → 進【2】
- **沒有輸出** → 應用根本沒起來，跳到【4】
- ★★★ 監聽在 `0.0.0.0:3000` 而不是 `127.0.0.1` → 應用繞過 Nginx 直接曝露，見〈安全性注意事項〉

**【2】這個程序歸誰管？（cgroup 決定 `systemctl stop` 殺不殺得到）**

```bash
cat /proc/1899/cgroup
```

```text
0::/system.slice/nuxt-app.service          # ★ 正常：由 unit 管理
0::/system.slice/pm2-ops.service           # ★ 架構 A，正常
0::/user.slice/.../session-3.scope         # ★★★★ 有人手動起的，systemctl 管不到 → 進【7】
```

**【3】它用的是哪個 `PM2_HOME`？**

```bash
sudo tr '\0' '\n' < /proc/1899/environ | grep -E '^(PM2_HOME|NODE_ENV|PORT)='
systemctl show pm2-ops -p Environment
```

```text
PM2_HOME=/root/.pm2                        # 實際在跑的
Environment=PATH=... PM2_HOME=/home/ops/.pm2   # ★★★★★ unit 說的
```

- **兩者不同** → 就是這個問題，重開機必炸。回到〈PM2_HOME 一致性檢查〉。
- 兩者相同 → 進【4】

**【4】unit 到底做了什麼、失敗在哪一步？**

```bash
systemctl status nuxt-app --no-pager -l
sudo journalctl -u nuxt-app -b --no-pager | tail -40
```

```text
● nuxt-app.service - Nuxt SSR front-end
     Active: activating (start) since ...; 1min ago       # ★★★ 卡在 activating → 進【5】
     Active: failed (Result: exit-code) ... status=127     # ★★★★ 127 = command not found → 進【6】
     Active: failed (Result: start-limit-hit)              # ★★★★ 重啟太頻繁 → 進【8】
     Active: active (running) ...                          # daemon 活著 → 但應用未必，進【7】
```

**【5】卡在 activating：`Type=` 與實際行為不符**

```bash
systemctl show nuxt-app -p Type -p PIDFile -p MainPID
```

```text
Type=forking
PIDFile=/var/lib/nodeapp/.pm2/pm2.pid
MainPID=0                     # ★★★★ pid 檔沒出現 → forking 判定失敗
```

- ★★★★ `ExecStart` 跑的是 `pm2-runtime`（前景）卻寫了 `Type=forking` → 改 `Type=simple`
- ★★★ `ExecStart` 跑的是 `pm2 start`（會 fork）卻寫了 `Type=simple` → systemd 會誤判服務已結束

**【6】exit 127 / 203：找不到執行檔**

```bash
systemctl show nuxt-app -p ExecStart --value
ls -l /usr/bin/pm2-runtime /usr/bin/node
sudo -u nodeapp env -i PATH=/usr/bin:/bin /usr/bin/pm2-runtime --version
```

```text
{ path=/home/ops/.nvm/versions/node/v18.19.0/bin/pm2-runtime ; ... }
ls: cannot access '/usr/bin/pm2-runtime': No such file or directory   # ★★★★ 就是它
```

★★★★ `env -i` 那一行很關鍵：它模擬 systemd 的乾淨環境。
**在互動 shell 跑得動、在 `env -i` 底下跑不動，就是 PATH 問題。**

**【7】unit 是 active，但應用其實已死**

```bash
curl -fsS --max-time 5 http://127.0.0.1:3000/healthz || echo "★★★★ 應用沒回應"
sudo -iu nodeapp pm2 jlist | jq -r '.[] | "\(.name) \(.pm2_env.status) restarts=\(.pm2_env.restart_time)"'
```

```text
★★★★ 應用沒回應
nuxt-app errored restarts=142               # ★★★★ 架構 A 的典型：systemd 綠燈、應用全掛
nuxt-app errored restarts=142
```

- 看到這個 → 應用層的錯誤在 `$PM2_HOME/logs/nuxt-app-error.log`（架構 A）
  或 `journalctl -u nuxt-app`（架構 B）
- ★★★★ 順便確認一件事：**你的監控是不是只在看 `systemctl is-active`？** 如果是，換掉。

**【8】start-limit-hit：兩層重啟互踩**

```bash
systemctl show nuxt-app -p RestartSec -p StartLimitIntervalUSec -p StartLimitBurst
grep -E 'min_uptime|restart_delay|max_restarts' /var/www/app/current/ecosystem.config.cjs
```

```text
RestartSec=1s                    # ★★★★ 太短
StartLimitIntervalUSec=10s
StartLimitBurst=5
    min_uptime: '10s',           # ★★★★ RestartSec(1s) < min_uptime(10s) → 兩層搶著重啟
    restart_delay: 3000,
```

修法：`RestartSec=10`、`StartLimitIntervalSec=300`、`StartLimitBurst=5`。
清掉計數器再試：

```bash
sudo systemctl reset-failed nuxt-app
sudo systemctl start nuxt-app
```

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對禁止：正式機服務跑在個人帳號下
> ```
> pm2 startup -u 王小明 --hp /home/王小明
> ```
> **後果**：
> - 人員異動、帳號停用或家目錄被清 → **整個前台服務消失**，而且沒有任何告警
> - 該員的 SSH 金鑰、`~/.bash_history`、個人檔案與生產服務混在同一個家目錄
> - 稽核上無法區分「個人行為」與「服務行為」，責任歸屬說不清
> - ★★★ 該員若有 sudo，等於服務帳號有 sudo
>
> **正確做法**：`useradd --system --shell /usr/sbin/nologin --home-dir /var/lib/nodeapp nodeapp`。
> 見 [[09-使用者與群組管理]]。

> [!danger] ★★★★★ 絕對禁止：`sudo pm2 start` 讓應用以 root 執行
> ```bash
> sudo pm2 start app.js        # ✗ Node 應用取得 root
> ```
> **後果**：任何一個 RCE 漏洞（相依套件的、Nuxt 的、你自己寫的模板注入）
> 直接就是**整台機器淪陷**，不是只有應用被打下來。
> 而且它同時把程序清單寫進 `/root/.pm2`，觸發本篇的 `PM2_HOME` 殺手。
>
> 若真的需要綁 80/443（其實不該，前面應該有 Nginx），用 systemd 的能力機制而不是 root：
> ```ini
> AmbientCapabilities=CAP_NET_BIND_SERVICE
> CapabilityBoundingSet=CAP_NET_BIND_SERVICE
> ```

> [!danger] ★★★★ `LimitCORE=infinity` 會把記憶體內容寫到磁碟
> `pm2 startup` 模板預設就有這一行。應用崩潰時產生的 core 檔**包含當下整個記憶體**：
> DB 連線字串與密碼、JWT 簽章金鑰、session token、剛處理到一半的**民眾個資**。
> 這些檔案的權限與保存期限通常沒有人管，備份還會把它一起帶走。
>
> ```ini
> LimitCORE=0                  # ★★★★ 正式機明確關掉
> ```
> ```bash
> # 確認目前設定與是否已經有 core 檔落地
> systemctl show nuxt-app -p LimitCORE
> coredumpctl list --since '30 days ago' 2>/dev/null | head
> ```
> ```text
> LimitCORE=0
> No coredumps found.
> ```

> [!danger] ★★★★ `EnvironmentFile` 裡的 DB 密碼會被整台機器看光
> ```bash
> # ★★★★ 任何使用者都能讀到別人程序的 cmdline；環境變數雖然只有同 uid 與 root 能讀，
> #       但 EnvironmentFile 若權限沒收好，就是人人可讀的明文密碼
> ls -l /var/www/app/shared/.env
> ```
> ```text
> -rw-r--r-- 1 root root 412 Aug 20 15:03 /var/www/app/shared/.env   # ★★★★ 644 = 全機器可讀
> ```
> 修正：
> ```bash
> sudo chown nodeapp:nodeapp /var/www/app/shared/.env
> sudo chmod 0640 /var/www/app/shared/.env
> ```
> ★★★ 更嚴謹的做法是用 systemd 的 `LoadCredential=` / `SetCredential=`，
> 讓密文只在該 unit 的私有 tmpfs 出現。

> [!warning] ★★★ 稽核軌跡：不要讓部署繞過 systemd
> 機關稽核會問「這台前台最後一次變更是什麼時候、誰做的」。
> 若部署腳本直接 `pm2 restart`，systemd 的 `ActiveEnterTimestamp` 就是錯的，
> 而 `pm2` 的操作也不會進 journal——**等於這次變更沒有軌跡**。
>
> 一律走 `systemctl restart/reload`，systemd 會自動留下：
> ```bash
> sudo journalctl -u nuxt-app --since today | grep -E 'Starting|Started|Stopping|Reloading'
> ```
> ```text
> Aug 28 09:31:02 web01 systemd[1]: Starting Nuxt SSR front-end...
> Aug 28 09:31:04 web01 systemd[1]: Started Nuxt SSR front-end.
> Aug 28 14:02:11 web01 systemd[1]: Reloading Nuxt SSR front-end...
> ```
> 再配合 `sudo` 的日誌（`/var/log/auth.log`），誰在什麼時候做了什麼就完整了。

> [!warning] ★★★ 最小權限：`ReadWritePaths` 要列到最小
> `ProtectSystem=strict` 把整個檔案系統設為唯讀，只有 `ReadWritePaths=` 列出的才可寫。
> **不要偷懶寫 `ReadWritePaths=/var/www`**——那等於應用可以改自己的程式碼，
> 一個檔案上傳漏洞就變成 webshell。只列真正需要寫入的：
> ```ini
> ReadWritePaths=/var/lib/nodeapp/.pm2 /var/www/app/shared/storage
> ```
> ```bash
> systemd-analyze security nuxt-app | head -20
> ```
> ```text
> → Overall exposure level for nuxt-app.service: 4.6 OK    # ★★ 舊的 pm2-ops 通常是 9.x UNSAFE
> ```

> [!warning] ★★★ 日誌裡不要有個資
> 應用日誌一旦走 journal 進了集中蒐集，就會被**長期保存並跨系統複製**。
> 原本只在 `~/.pm2/logs` 的「印出整個 request body 方便除錯」，
> 遷移後會變成散布到 SIEM 的個資外洩。遷移前先檢查：
> ```bash
> sudo grep -ciE '身分證|統一編號|[A-Z][12][0-9]{8}' /home/ops/.pm2/logs/*.log
> ```
> ```text
> /home/ops/.pm2/logs/nuxt-app-out.log:1284      # ★★★★ 先修應用的日誌輸出再遷移
> ```

---

## 速查表

### 診斷指令（★ 依使用頻率排序）

| ★ | 指令 | 用途 |
| --- | --- | --- |
| ★★★★★ | `ps -eo user,pid,args \| grep 'God Daemon'` | 有幾個 PM2 daemon、各自的 `PM2_HOME`（**結果必須是 1 行**） |
| ★★★★★ | `systemctl show <unit> -p Environment` | unit 宣告的 `PM2_HOME` 與 `PATH` |
| ★★★★ | `systemctl cat <unit>` | unit 全文（含 drop-in） |
| ★★★★ | `sudo tr '\0' '\n' < /proc/<pid>/environ \| grep PM2_HOME` | 某個程序**實際**用的 `PM2_HOME` |
| ★★★★ | `sudo ss -lptn 'sport = :3000'` | 誰在監聽這個埠 |
| ★★★★ | `cat /proc/<pid>/cgroup` | 這個程序屬於哪個 unit（決定 `stop` 殺不殺得到） |
| ★★★ | `systemd-cgls -u <unit>` | unit 的 cgroup 涵蓋哪些程序 |
| ★★★ | `stat -c '%y %s' $PM2_HOME/dump.pm2` | 快照什麼時候存的、是不是 2 bytes 的空陣列 |
| ★★★ | `sudo -iu <user> pm2 jlist \| jq -r '.[].pm2_env.status'` | 每個 instance 的真實狀態 |
| ★★★ | `journalctl -u <unit> -b` | 本次開機以來的日誌 |
| ★★★ | `systemd-analyze security <unit>` | 加固程度評分 |
| ★★ | `systemd-analyze blame \| grep <unit>` | 開機時這個 unit 花了多久 |
| ★★ | `systemctl list-unit-files 'pm2-*'` | 還有沒有殘留的舊 unit |

### `pm2 startup` 模板的四個弱點

| ★ | 弱點 | 徵狀 | 修法 |
| --- | --- | --- | --- |
| ★★★★ | PATH 寫死 | 開機失敗、手動正常 | 絕對路徑 + 不用 nvm |
| ★★★★ | `Type=forking` 判定不精準 | resurrect 出 0 個也算成功 | 改 `Type=simple` + `pm2-runtime` |
| ★★★★ | 狀態只反映 daemon | 綠燈但 502 | 健康檢查 timer 或改架構 B/C |
| ★★★★ | 停機語意不同步 | 部署時 5xx、`stop` 卡 90s | `TimeoutStopSec` ≥ `kill_timeout` ≥ T_app |

### 逾時對齊建議值

| ★ | 層 | 參數 | 值 |
| --- | --- | --- | --- |
| ★★★ | 應用 | SIGTERM handler 耗時 | 實測 ≤ 15s |
| ★★★★ | PM2 | `kill_timeout` | `30000`（預設 1600 遠遠不夠） |
| ★★★★ | systemd | `TimeoutStopSec` | `45` |
| ★★ | systemd | `TimeoutStartSec` | `60` |
| ★★★★ | systemd | `RestartSec` | `10`（必須 ≥ PM2 `min_uptime`） |
| ★★★ | systemd | `StartLimitIntervalSec` / `StartLimitBurst` | `300` / `5` |

### 檔案與路徑

| ★ | 路徑 | 內容 |
| --- | --- | --- |
| ★★★★★ | `$PM2_HOME/dump.pm2` | `pm2 save` 的快照，`resurrect` 讀它 |
| ★★★★ | `$PM2_HOME/pm2.pid` | God Daemon 的 pid，`Type=forking` 的 `PIDFile` |
| ★★★ | `$PM2_HOME/rpc.sock` / `pub.sock` | CLI 與 daemon 的通訊；損壞會導致 `pm2` 指令卡住 |
| ★★★ | `$PM2_HOME/logs/<name>-out.log` | 應用 stdout（**journal 收不到**） |
| ★★★ | `$PM2_HOME/logs/<name>-error.log` | 應用 stderr |
| ★★★ | `$PM2_HOME/pm2.log` | PM2 daemon 自己的日誌 |
| ★★★★ | `/etc/systemd/system/pm2-<user>.service` | `pm2 startup` 產生的 unit |
| ★★★ | `/usr/lib/node_modules/pm2/bin/pm2` | NodeSource / RHEL 的 pm2 本體 |
| ★★★ | `/usr/local/lib/node_modules/pm2/bin/pm2` | Ubuntu 內建 npm（prefix `/usr/local`）的位置 |

### 三種架構一句話

| ★ | 架構 | 一句話 | 適用 |
| --- | --- | --- | --- |
| ★★ | **A** `pm2 startup` | 最省事，狀態與日誌都是盲區 | 開發／測試機、尚未遷移的既有系統 |
| ★★★★ | **B** unit 跑 `pm2-runtime` | 保留 cluster，狀態與日誌交還 systemd | ★ 機關正式機的預設答案 |
| ★★★ | **C** 純 systemd | 少一層相依，最乾淨也最好加固 | 單實例、無 Node 專職維運、高安全要求 |

### 判斷準則

| ★ | 看到這個 | 就代表 |
| --- | --- | --- |
| ★★★★★ | `dump.pm2` 只有 2 bytes | 內容是 `[]`，重開機會起 0 個應用 |
| ★★★★★ | `God Daemon` 出現 2 行以上 | 兩套獨立清單並存，部署結果不可預測 |
| ★★★★ | `systemctl status` 綠燈 + `curl /healthz` 失敗 | 架構 A 的典型盲區 |
| ★★★★ | `status=127` | 找不到執行檔，八成是 PATH / nvm |
| ★★★★ | `State 'stop-sigterm' timed out. Killing.` | 每次部署都在硬砍連線 |
| ★★★★ | `start-limit-hit` | 兩層重啟互踩，先看 `RestartSec` vs `min_uptime` |
| ★★★ | `/proc/<pid>/cgroup` 出現 `user@1000.service` | 手動起的，`systemctl stop` 殺不到 |
| ★★★ | `journalctl -u pm2-*` 只有 `PM2 log:` 開頭的行 | 應用日誌沒進 journal，集中蒐集是空的 |

---

## 練習題

> [!question]- 練習 1：三分鐘內判斷這台機器重開機會不會活
> **題目**：你接手一台陌生的前台主機，只知道上面跑著 Node 應用。
> 在**不重開機**的前提下，寫出一組指令判斷「重開機後服務會不會自己起來」，
> 並說明每個輸出各代表什麼。
>
> **參考解答**：
> ```bash
> # 【1】有沒有設開機自啟
> systemctl list-unit-files 'pm2-*' 'nuxt*' 'node*' --no-legend
> ```
> ```text
> pm2-ops.service    enabled enabled       # ★ 有，繼續往下
> ```
> ```bash
> # 【2】unit 宣告的 PM2_HOME
> systemctl show pm2-ops -p Environment --value | tr ' ' '\n' | grep PM2_HOME
> ```
> ```text
> PM2_HOME=/home/ops/.pm2
> ```
> ```bash
> # 【3】★★★★★ 那個 PM2_HOME 的 dump 有幾個應用
> sudo -u ops env PM2_HOME=/home/ops/.pm2 pm2 jlist | jq 'length'
> sudo stat -c '%y %s bytes' /home/ops/.pm2/dump.pm2
> ```
> ```text
> 0
> 2023-06-14 10:22:41 2 bytes          # ★★★★★ 2 bytes = "[]" → 重開機會起 0 個應用
> ```
> ```bash
> # 【4】那現在是誰在服務？
> ps -eo user,pid,args | grep -F 'God Daemon' | grep -v grep
> ```
> ```text
> root 1842 PM2 v5.4.3: God Daemon (/root/.pm2)   # ★★★★★ 對上了：實際服務的在 /root
> ```
>
> **結論**：重開機後 `systemctl status pm2-ops` 會是綠燈，但**應用一個都不會起來**。
> 這台機器現在是「靠著三年沒重開機」在活。
> ★★★★ 立即動作：先讓現況可存活（以 unit 的 `PM2_HOME` 重新 start + save），
> 再排維護窗遷移到架構 B。

> [!question]- 練習 2：把逾時對齊，並證明部署不會斷線
> **題目**：一台架構 B 的機器，`ecosystem.config.cjs` 沒有設 `kill_timeout`，
> unit 也沒有設 `TimeoutStopSec`。請量測、設定，並用實驗證明改善。
>
> **參考解答**：
> ```bash
> # 【1】量 T_app：直接對一個 worker 送 SIGTERM
> PID=$(pgrep -f 'index.mjs' | head -1)
> date +%T.%3N; sudo kill -TERM "$PID"
> while kill -0 "$PID" 2>/dev/null; do sleep 0.05; done; date +%T.%3N
> ```
> ```text
> 09:42:11.104
> 09:42:18.660        # ★ T_app ≈ 7.6 秒
> ```
> ```bash
> # 【2】改前基準：一邊打流量一邊 restart
> ( while :; do curl -s -o /dev/null -w '%{http_code} ' http://127.0.0.1:3000/healthz; sleep 0.1; done ) &
> sudo systemctl restart nuxt-app; sleep 15; kill %1
> ```
> ```text
> 200 200 200 502 502 000 000 200 200      # ★★★★ 有 502 = 連線被硬砍
> ```
> 因為 PM2 預設 `kill_timeout: 1600`（1.6s）< T_app（7.6s），worker 在收尾途中就被 SIGKILL。
>
> ```javascript
> // 【3】ecosystem.config.cjs
> kill_timeout: 30000,     // ★★★★ 30s > T_app 7.6s，留足裕度
> ```
> ```ini
> # 【4】/etc/systemd/system/nuxt-app.service
> TimeoutStopSec=45        # ★★★★ 45s > kill_timeout 30s
> ```
> ```bash
> sudo systemctl daemon-reload && sudo systemctl restart nuxt-app
> # 【5】重跑第 2 步的實驗
> ```
> ```text
> 200 200 200 000 000 200 200               # ★ 只剩連線被拒，沒有 502 → 通過
> ```
> ★★★ `000` 是 curl 連不上（服務真的停了那幾秒），這在 `restart` 時無法避免；
> 要完全不中斷得用 `systemctl reload`（cluster 模式的零停機重載）。

> [!question]- 練習 3：設計一個「兩份應用搶同一個埠」的偵測腳本
> **題目**：寫一支可以放進 cron / systemd timer 的巡檢腳本，
> 偵測本篇提到的三種危險狀態並回報。
>
> **參考解答**：
> ```bash
> #!/usr/bin/env bash
> # /usr/local/bin/pm2-sanity-check.sh
> set -uo pipefail            # ★ 巡檢腳本不要 -e，要跑完所有項目再彙總
> UNIT="nuxt-app.service"
> PM2_HOME_EXPECT="/var/lib/nodeapp/.pm2"
> PORT=3000
> issues=()
>
> # ★★★★★ ① 只能有一個 God Daemon
> n=$(ps -eo args | grep -cF 'God Daemon' || true)
> [[ "$n" -eq 1 ]] || issues+=("★★★★★ PM2 daemon 數量=${n}（應為 1）")
>
> # ★★★★★ ② unit 宣告的 PM2_HOME 與實際監聽程序的必須一致
> unit_home=$(systemctl show "$UNIT" -p Environment --value \
>             | tr ' ' '\n' | grep -oP '^PM2_HOME=\K.*' || echo '')
> [[ "$unit_home" == "$PM2_HOME_EXPECT" ]] \
>   || issues+=("★★★★ unit PM2_HOME=${unit_home:-未設定}，預期 ${PM2_HOME_EXPECT}")
>
> lpid=$(ss -lptnH "sport = :${PORT}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1 || true)
> if [[ -n "$lpid" ]]; then
>   real_home=$(tr '\0' '\n' < "/proc/${lpid}/environ" | grep -oP '^PM2_HOME=\K.*' || echo '')
>   [[ "$real_home" == "$unit_home" ]] \
>     || issues+=("★★★★★ 監聽程序 PM2_HOME=${real_home} ≠ unit 的 ${unit_home}")
> else
>   issues+=("★★★★ 沒有程序監聽 ${PORT}")
> fi
>
> # ★★★★ ③ systemctl 綠燈但健康端點不通（架構 A 的盲區也用這招偵測）
> if systemctl is-active --quiet "$UNIT"; then
>   curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/healthz" >/dev/null \
>     || issues+=("★★★★ unit active 但 /healthz 失敗（狀態綠燈是假的）")
> else
>   issues+=("★★★★ ${UNIT} 非 active")
> fi
>
> # ★★★ ④ dump 是不是空的（架構 A 才需要）
> if [[ -f "${PM2_HOME_EXPECT}/dump.pm2" ]]; then
>   sz=$(stat -c '%s' "${PM2_HOME_EXPECT}/dump.pm2")
>   [[ "$sz" -gt 10 ]] || issues+=("★★★★★ dump.pm2 只有 ${sz} bytes（空陣列）")
> fi
>
> if [[ ${#issues[@]} -eq 0 ]]; then
>   echo "OK"; exit 0
> fi
> printf '%s\n' "${issues[@]}" >&2
> exit 1
> ```
> ```bash
> sudo /usr/local/bin/pm2-sanity-check.sh
> ```
> ```text
> ★★★★★ PM2 daemon 數量=2（應為 1）
> ★★★★★ 監聽程序 PM2_HOME=/root/.pm2 ≠ unit 的 /var/lib/nodeapp/.pm2
> ```
> ★★★ 用 `Type=oneshot` 的 service + timer 每 15 分鐘跑一次，
> 並在 service 上掛 `OnFailure=alert@%n.service`，寫法見 [[04-服務自動復原與看門狗]]。

---

## 小測驗

Q1. `pm2 startup systemd` 產生的 unit 為什麼用 `Type=forking` 而不是 `Type=simple`？這個選擇帶來什麼副作用？

Q2. 下面兩個指令的結果為什麼可能完全不同？

```bash
sudo -u ops pm2 list
sudo -iu ops pm2 list
```

Q3. 是非題：`systemctl status pm2-ops` 顯示 `active (running)`，就可以確定 Node 應用正在正常服務。

Q4. 一台機器 `systemctl restart pm2-ops` 每次都成功，但某次計畫外斷電重開後前台就不見了。列出**三個**最可能的原因，並各給一道驗證指令。

Q5. `ExecStart` 寫成 `/home/ops/.nvm/versions/node/v18.19.0/bin/pm2-runtime start ...` 會在什麼時候壞掉？為什麼手動 `systemctl start` 測試時不會發現？

Q6. 這行指令會發生什麼事，輸出怎麼解讀？

```bash
sudo tr '\0' '\n' < /proc/1899/environ | grep -E '^PM2_HOME='
```

Q7. 應用的 SIGTERM handler 要跑 8 秒才收工完畢。若 `kill_timeout` 是預設值、`TimeoutStopSec=45`，部署時會發生什麼？

Q8. 架構 B 下，你在 unit 加了 `Restart=on-failure` + `RestartSec=1`，ecosystem 裡 `min_uptime: '10s'`。journal 出現 `start-limit-hit`。問題出在哪一層？

Q9. 選擇題：機關稽核要求「所有服務日誌進集中蒐集平台」，現況是架構 A。下列哪個做法**真正**解決問題？
(a) `pm2 install pm2-logrotate`
(b) 寫 `/etc/logrotate.d/pm2` 輪替 `~/.pm2/logs/*.log`
(c) 改成架構 B，讓應用 stdout 經 `pm2-runtime` 進 journald
(d) 把 `~/.pm2/logs` 做成 NFS 掛載到日誌伺服器

Q10. `pm2 unstartup systemd` 做了哪些事、**沒有**做哪些事？遷移時漏掉哪一步會造成兩份應用搶同一個埠？

> [!question]- 測驗答案
> **Q1.** `pm2 startup` 產生的 unit 執行的是 `pm2 resurrect`，而 `pm2` CLI 的行為是：
> 確認 God Daemon 存在（不存在就 fork 一個出來成為背景 daemon），送出 RPC，然後 **CLI 自己退出**。
> 對 systemd 而言就是「主程序 fork 後父程序結束」，這正是 `Type=forking` 的定義，
> 所以模板還配了 `PIDFile=$PM2_HOME/pm2.pid` 讓 systemd 找得到真正的 daemon pid。
> ★★★★ 副作用是**啟動判定變得不精準**：systemd 只驗「pid 檔出現且該 pid 活著」，
> 至於 `resurrect` 還原出 0 個應用、或全部 `errored`，它一概不知道，照樣報 `active (running)`。
> 加上 `Restart=on-failure` 監看的也是 daemon，應用死光了不會觸發重啟。
> 這就是為什麼架構 A 的 `systemctl status` **不能當監控依據**。
> 修法見〈三種架構對照〉的架構 B：`pm2-runtime` 在前景跑，改用 `Type=simple`，
> systemd 監看的就是真實的應用進程樹。
> （對應段落：〈逐行解剖這份 unit〉、〈三種架構對照與選型〉）
>
> **Q2.** ★★★★ 因為 `sudo -u` **不會重設 `$HOME`**（除非 sudoers 設了 `always_set_home`），
> 而 PM2 的 `PM2_HOME` 預設值就是 `$HOME/.pm2`。
> - `sudo -u ops pm2 list`：以 `ops` 的 uid 執行，但 `$HOME` 仍是 `/root`（你原本 sudo 的環境），
>   於是它去讀 `/root/.pm2`——那裡可能沒有 daemon，PM2 會**靜靜地新開一個**，回報空清單。
> - `sudo -iu ops pm2 list`：`-i` 模擬登入，`$HOME` 正確變成 `/home/ops`，讀 `/home/ops/.pm2`，
>   看到的才是那個帳號真正的程序清單。
>
> 實務上最保險的是完全不靠 `$HOME` 推導：
> ```bash
> sudo -u ops env PM2_HOME=/home/ops/.pm2 pm2 list
> ```
> ★★★ 這個差異害過非常多人——「明明服務在跑，`pm2 list` 卻是空的」十次有八次是這個。
> （對應段落：〈PM2_HOME 一致性檢查〉）
>
> **Q3.** ★★★★ **否**（架構 A 下）。`pm2-ops.service` 的 `Type=forking` + `PIDFile` 監看的是
> **PM2 God Daemon**，不是你的 Node 應用。所有 worker 都 `errored`、埠沒人監聽、
> 網站回 502，只要 God Daemon 這個程序還活著，`systemctl status` 就是綠燈。
> 驗證方式是同時看兩個地方：
> ```bash
> systemctl is-active pm2-ops
> curl -fsS --max-time 5 http://127.0.0.1:3000/healthz || echo '★★★★ 應用其實沒回應'
> ```
> ★★★ 所以架構 A 下的監控**必須**是外部健康檢查（打 `/healthz`），不能是 `systemctl is-active`。
> 架構 B/C 下這題的答案才會變成「是」，因為 systemd 監看的就是應用本身。
> （對應段落：〈兩層托管的疊層圖〉、〈PM2 應用怎麼接上前面幾篇的機制〉）
>
> **Q4.** `restart` 與 `reboot` 的差異剛好涵蓋四類問題，三個最可能的是：
> ① ★★★★★ **`PM2_HOME` / dump 不一致**——`restart` 時 daemon 可能還在、或 resurrect 讀到的是
>    你手動 start 過的狀態；真的重開機才會暴露 dump 是空的。
> ```bash
> sudo -u ops env PM2_HOME="$(systemctl show pm2-ops -p Environment --value | tr ' ' '\n' | grep -oP '^PM2_HOME=\K.*')" pm2 jlist | jq 'length'
> ```
> 期望 > 0，得到 `0` 就是它。
> ② ★★★★ **掛載相依**——`/home` 或 `/var/www` 是獨立分割 / NFS，開機時 unit 比掛載早跑。
> ```bash
> systemctl show pm2-ops -p RequiresMountsFor -p After
> ```
> 沒有列到程式碼與 `PM2_HOME` 所在的掛載點就是它。
> ③ ★★★★ **PATH / node 路徑**——`Environment=PATH=` 指向 nvm 目錄。
> ```bash
> sudo -u ops env -i PATH=/usr/bin:/bin /usr/lib/node_modules/pm2/bin/pm2 --version
> ```
> 報 `command not found` 或 `status=127` 就是它。
> ★★★★ 結論：**只用 `systemctl restart` 驗收就宣告完成是不合格的**，必須真的 reboot 一次。
> （對應段落：〈重開機是唯一可信的驗收〉）
>
> **Q5.** 它會在**開機時**壞掉，而且是最難查的一類。三個原因疊在一起：
> ① nvm 的目錄在 `/home/ops` 底下，若 `/home` 是獨立分割或 NFS，unit 只宣告了
>    `After=network.target`，**沒有宣告要等掛載**，可能比 `/home` 掛好還早跑 → `status=203/EXEC`。
> ② nvm 換版本（`nvm install 20` 後 `nvm alias default 20`）→ 舊路徑消失 → `status=127`。
> ③ 若 unit 有 `ProtectHome=true`，`/home` 直接被沙箱擋掉。
>
> ★★★★ 手動測試不會發現，是因為你 `systemctl start` 的時候 `/home` 早就掛好了、
> 版本也還沒換——**測試環境與開機環境根本不同**。
> 用這行模擬 systemd 的乾淨環境就能提前抓到：
> ```bash
> sudo -u nodeapp env -i PATH=/usr/bin:/bin /usr/bin/pm2-runtime --version
> ```
> 根治方式是照 [[01-Node-安裝與版本管理]] 的結論，正式機用系統套件的 `/usr/bin/node`。
> （對應段落：〈Node 與 PM2 的絕對路徑〉、排查步驟【6】）
>
> **Q6.** 它讀出 pid 1899 這個程序**啟動當下**的環境變數（`/proc/<pid>/environ` 是
> NUL 分隔的，所以先用 `tr '\0' '\n'` 轉成一行一個），再濾出 `PM2_HOME`。
> ```text
> PM2_HOME=/root/.pm2
> ```
> ★★★★★ 這是本篇最有用的一行診斷。把它跟 `systemctl show <unit> -p Environment` 對照：
> - **兩者相同** → 服務確實是由那個 unit 起的，`PM2_HOME` 沒問題。
> - **兩者不同** → 抓到殺手了：現在在服務的那份應用**不是** unit 起的，
>   重開機後 systemd 會用 unit 裡的 `PM2_HOME` 去 resurrect，很可能是空的。
>
> ★★★ 注意兩件事：需要 root 才讀得到別人的 `environ`；讀到的是**啟動當下**的值，
> 程序執行中用 `process.env.X = ...` 改的不會反映在這裡。
> （對應段落：〈PM2_HOME 一致性檢查〉、排查步驟【3】）
>
> **Q7.** ★★★★ 會**每次部署都硬砍進行中的請求**。時序是這樣：
> ```
> t=0.0s  systemd 送 SIGTERM 給 pm2-runtime
> t=0.0s  pm2-runtime 轉送 SIGTERM 給每個 worker，開始倒數 kill_timeout
> t=1.6s  ★★★★ kill_timeout（預設 1600ms）到期 → PM2 送 SIGKILL
>         → 應用的收尾才做到第 1.6 秒（總共要 8 秒）
>         → in-flight 請求直接斷（使用者看到 502）、DB 交易可能寫一半
> t=1.7s  pm2-runtime 退出，systemd 判定停止完成
>         → TimeoutStopSec=45 【根本沒有用到】
> ```
> 關鍵在於 `TimeoutStopSec` 只是**最外層**的上限，內層的 `kill_timeout` 先到期就先動手。
> 三個逾時必須滿足 `T_app ≤ kill_timeout ≤ TimeoutStopSec`，這裡是 `8 > 1.6`，第一個不等式就破了。
> 修法：`kill_timeout: 30000`。驗證：一邊打流量一邊 `systemctl restart`，觀察有沒有 502；
> 並查 journal 有沒有 `State 'stop-sigterm' timed out. Killing.`。
> （對應段落：〈三個逾時要對齊〉、練習 2）
>
> **Q8.** ★★★★ 問題出在 **systemd 這一層的 `RestartSec=1` 太短**，與 PM2 的 `min_uptime: '10s'` 打架。
> 機制是這樣：PM2 認為「活不滿 10 秒就算啟動失敗」，所以應用起來後前 10 秒它一直在觀察；
> 而 systemd 只要 `pm2-runtime` 一退出，**1 秒**後就重來。
> 於是每 1 秒觸發一次啟動，`StartLimitBurst` 的計數迅速用完 → `start-limit-hit` → 服務直接躺平。
> 兩層日誌交錯，看起來像是「應用瘋狂重啟」，實際上是排程打架。
> 修法：
> ```ini
> [Unit]
> StartLimitIntervalSec=300
> StartLimitBurst=5
> [Service]
> RestartSec=10          # ★★★★ 必須 ≥ ecosystem 的 min_uptime
> ```
> ```bash
> sudo systemctl daemon-reload && sudo systemctl reset-failed nuxt-app && sudo systemctl start nuxt-app
> ```
> 分工原則：PM2 管快速的單 worker 重啟，systemd 管慢速的整體重啟。
> （對應段落：〈衝突形態 ①〉、排查步驟【8】）
>
> **Q9.** ★★★★ 答案是 **(c)**。
> - (a) `pm2-logrotate` 解決的是「磁碟被日誌撐爆」，日誌**仍然是檔案**，
>   集中蒐集平台若只收 journal / syslog 就還是收不到。★★★ 這是最常見的「假解法」。
> - (b) 同理，只是換一套輪替工具，可見性一點都沒改善（除非再搭 rsyslog 的 `imfile` 去讀檔，
>   但那會多一層輪替競態，輪替瞬間可能漏行）。
> - (c) ✓ `pm2-runtime` 在前景執行，worker 的 stdout/stderr 直接串到 systemd，
>   由 `StandardOutput=journal` 收進 journald，`journalctl -u nuxt-app` 一次查完，
>   集中蒐集直接就收得到，稽核的兩條要求同時滿足。
> - (d) NFS 掛家目錄是**更糟的做法**：多一個開機時的掛載相依（本篇 Q4 的第 ② 類問題），
>   NFS 斷線時應用會整個卡住，而且日誌格式仍未進蒐集管線。
> （對應段落：〈日誌雙軌〉的三種對策比較表）
>
> **Q10.** `pm2 unstartup systemd` 做的是：
> ① `systemctl disable pm2-<user>`；② 刪除 `/etc/systemd/system/pm2-<user>.service`；
> ③ `systemctl daemon-reload`。
>
> ★★★★ 它**沒有**做的是：
> - **沒有**停掉正在跑的 PM2 daemon 與 worker（`pm2 kill` 要另外下）
> - **沒有**刪除 `$PM2_HOME/dump.pm2`（快照原封不動留著）
> - **沒有**碰其他 `PM2_HOME` 的 daemon（例如 `/root/.pm2` 那一份）
>
> 遷移時漏掉的關鍵步驟就是**沒有真的停掉舊 worker、也沒有等埠釋放**。
> 結果是新 unit 起來時舊 worker 還握著 3000，cluster 的一個 instance 拿到 `EADDRINUSE` 而 errored，
> 另一個卻正常——★★★★ `systemctl status` 綠燈、健康檢查也可能剛好通過，
> 但實際處理能力少一半，而且沒有人會發現。
> 正確順序：`pm2 delete all` → `pm2 unstartup systemd` → `pm2 kill` → `pkill -f 'God Daemon'`
> → **輪詢等待埠釋放** → 才 `systemctl enable --now` 新 unit。
> （對應段落：〈完整實戰範例〉的 `do_cutover`、遷移期間避免搶埠的 warning）

---

## 延伸閱讀

- [[03-PM2-程序管理入門]] — PM2 那一側的完整說明：安裝、`pm2 monit`／`pm2 describe` 診斷、
  日誌輪替、五個坑。本篇的所有 PM2 指令細節都以那篇為準。
- [[04-PM2-進階設定與部署]] — `ecosystem.config.cjs` 全文、cluster 原理與限制、
  零停機 reload 的 graceful shutdown 程式碼。本篇「三個逾時對齊」裡的 `T_app` 就是那篇的 handler。
- [[01-systemd-unit撰寫實戰]] — unit 的相依宣告、`Exec*` 家族、沙箱指令、template unit。
  本篇實戰範例的 unit 用到的每一個指令，那篇都有完整說明。
- [[04-服務自動復原與看門狗]] — `Restart=` 策略、健康檢查 timer、`OnFailure=` 告警單元的實作。
  搭配本篇的「這些機制該掛在哪一層」一起看。
- [[01-Node-安裝與版本管理]] — 「正式機不要用 nvm」的完整論證。本篇一半的 PATH 問題源自違反這條。
- [[02-Nuxt-SSR與PM2部署]] — Nuxt 的建置產物、`.output/server/index.mjs` 與 Nginx 反向代理設定。
- [[06-部署自動化]] — 換埠切換、符號連結切版、部署腳本要把 `systemctl reload` 放在哪。
- [[02-日誌集中與輪替]] — journald 的保留策略、轉送到集中蒐集平台的做法。
- PM2 官方 startup script 文件：<https://pm2.keymetrics.io/docs/usage/startup/>
- PM2 `pm2-runtime`（容器與前景模式）文件：<https://pm2.keymetrics.io/docs/usage/docker-pm2-nodejs/>
- systemd `systemd.service(5)`（`Type=`、`Restart=`、`TimeoutStopSec=`）：<https://www.freedesktop.org/software/systemd/man/systemd.service.html>
- systemd `systemd.exec(5)`（`Environment=`、沙箱指令）：<https://www.freedesktop.org/software/systemd/man/systemd.exec.html>
