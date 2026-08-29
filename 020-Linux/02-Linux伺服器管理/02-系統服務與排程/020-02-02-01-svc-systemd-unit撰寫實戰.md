---
title: "systemd unit 撰寫實戰"
desc: "把自寫或委外的服務寫成能撐過重開機、套件升級與交接稽核的 unit：相依、掛載、目錄委派、template、drop-in、停機語意與沙箱"
aliases: [unit檔, systemd-unit, drop-in, template-unit, systemd-analyze, ExecStartPre, RequiresMountsFor]
tags: [群組/Linux, linux/伺服器, 主題/systemd]
category: 系統服務與排程
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-01-17-cmd-Linux-systemd服務管理]]", "[[020-01-10-cmd-Linux-程序管理與訊號]]"]
updated: 2026-08-28
---

# systemd unit 撰寫實戰

> [!abstract] 這篇你會學到
> - 把相依關係的**順序**（`After=`）與**強度**（`Wants=`／`Requires=`）分開設計，
>   不再出現「重開機後掛掉、手動 start 就正常」這種鬼打牆
> - ★★★★ 讓服務在**開機當下**就拿得到 IP、掛得到 NFS、找得到 `/run` 底下的目錄 ——
>   這是正式環境九成「只有開機會失敗一次」事故的來源
> - 用 **template unit** 一份檔案管三條 queue、五個站台，並且不會漏 enable
> - 用 **drop-in** 正確覆寫套件提供的 unit，避開 list 型指令沒清空就變成兩條 `ExecStart=` 的坑
> - 把 `TimeoutStopSec=` 與 `KillMode=` 對齊應用的 graceful shutdown，讓部署 restart 不砍掉進行中的工作
> - 用 `systemd-analyze verify` / `security` / `systemd-run` 在**不落檔、不重啟正式服務**的情況下驗證 unit
> - 產出一份可交接、可稽核的 unit：專屬系統帳號、640 的 `EnvironmentFile=`、納入 git 的檔案

---

## 前置知識

| 篇章 | 你需要從那篇帶過來的東西 |
| --- | --- |
| [[020-01-17-cmd-Linux-systemd服務管理]] | `systemctl` 基本操作、`status` 判讀、unit 三個位置的優先序、`Type=` 對照表、`[Install]` 與 `systemctl edit` 入門、資源限制（`MemoryMax=`）|
| [[020-01-10-cmd-Linux-程序管理與訊號]] | SIGTERM／SIGKILL 的差別、程序群組與 cgroup、殭屍與孤兒程序 |
| [[020-01-08-cmd-Linux-檔案權限與擁有者]] | 640／750 的意義、`chown` 與服務帳號 |
| [[020-01-19-guide-Linux-日誌系統]] | `journalctl -xeu <unit>` 追服務日誌 |

> [!note] 本篇的起點假設
> **你已經會寫最簡單的 unit** —— `[Unit]` / `[Service]` / `[Install]` 三段、`ExecStart=` 一行、
> `systemctl enable --now` 就能跑。本篇不重講那些，直接進到「正式環境才會踩到」的部分。
>
> 本章其他篇的分工，先講清楚免得你找錯地方：
>
> | 主題 | 在哪一篇 |
> | --- | --- |
> | `Restart=` 策略、重啟風暴、`WatchdogSec=`、`OnFailure=` 告警 | [[020-02-02-04-svc-systemd-服務自動復原與看門狗]] |
> | timer unit、`OnCalendar=`、oneshot 服務怎麼被排程觸發 | [[020-02-02-02-cmd-systemd-timer與cron選型]] |
> | PM2 與 systemd 的分工與衝突 | [[020-02-02-05-svc-systemd-PM2與systemd整合]] |
> | Supervisor 本身的設定寫法 | [[130-01-04-03-guide-Laravel-佇列排程與Supervisor]] |

---

## 觀念說明

### 本篇會一路帶著走的三個服務

機關環境裡九成的自訂服務逃不出這三種形狀，本篇所有範例都從它們長出來：

```
┌──────────────────────┬─────────────┬────────────────────────────────────────┐
│ 服務                 │ 形狀        │ 難點                                   │
├──────────────────────┼─────────────┼────────────────────────────────────────┤
│ collector.service    │ 自寫 Python │ 要綁固定 IP、資料寫在 NFS 上           │
│  資產收集器          │ simple      │ → 開機時序（network-online / mount）   │
├──────────────────────┼─────────────┼────────────────────────────────────────┤
│ laravel-worker@      │ 委外 PHP    │ 三條 queue 要各跑一份、部署要重啟      │
│  佇列處理            │ 多實例      │ → template unit + 停機語意             │
├──────────────────────┼─────────────┼────────────────────────────────────────┤
│ nuxt-ssr.service     │ Node SSR    │ 「起來了」不等於「能接請求」           │
│  前端 SSR            │ notify      │ → Type=notify + TimeoutStopSec         │
└──────────────────────┴─────────────┴────────────────────────────────────────┘
```

### 相依關係有兩個維度，它們互不相干

這是本篇最重要的心智模型。**`After=` 和 `Requires=` 是兩件事，不是同一件事的強弱版本。**

```
                       強度（要不要幫我把它拉起來？對方掛了我怎麼辦？）
                       │
          沒有任何強度 │ Wants=      │ Requires=   │ BindsTo=
                       │ 弱          │ 強          │ 最強
  ─────────────────────┼─────────────┼─────────────┼─────────────
  沒寫 After=          │ 可能同時起  │ 可能同時起  │ 可能同時起
  （順序不管）         │ ← 常見錯誤：資料庫還沒好我就連了
  ─────────────────────┼─────────────┼─────────────┼─────────────
  After=X              │ ✓ 標準寫法  │ 連鎖啟動    │ 連鎖啟停
  （X 之後才輪到我）   │             │ + 連鎖失敗  │ + 對方消失我也消失
```

| 指令 | 會不會幫我啟動對方？ | 對方**啟動失敗**時 | 對方**事後停止**時 | 管順序嗎 |
| --- | --- | --- | --- | --- |
| ★★★★ `After=X` | **不會** | 無關 | 無關 | ✔ 我排在 X 之後 |
| `Before=X` | 不會 | 無關 | 無關 | ✔ 我排在 X 之前 |
| ★★★★ `Wants=X` | 會（失敗也沒關係） | 我照樣啟動 | 我照樣跑 | ✘ |
| ★★★ `Requires=X` | 會 | **我也失敗** | 我被一起停掉 | ✘ |
| ★★★ `BindsTo=X` | 會 | 我也失敗 | **我立刻停**（連 X 是被硬體拔掉而消失也算） | ✘ |
| ★★ `Requisite=X` | **不會** | X 當下沒在跑 → **我立刻失敗** | 無關 | ✘ |
| ★★ `PartOf=X` | 不會 | 無關 | X `restart`／`stop` 時我跟著 | ✘ |
| ★ `Upholds=X`（v249+） | 會，而且 X 掛了會**一直被拉回來** | — | 一直重拉 | ✘ |

> [!danger] 兩個方向相反的事故，都來自誤解上表
> **事故 A：只寫 `After=` 沒寫 `Wants=`（★★★★）**
> ```ini
> [Unit]
> After=collector-cache.service      # ← 只有這一行
> ```
> `collector-cache.service` 是你自己寫的、**沒有 `enable`**。開機時沒有任何人要求啟動它，
> `After=` 只是說「如果它也要啟動，那我排在它後面」。結果它根本沒被拉起來，
> `collector` 連不上 cache → `failed`。
> **症狀：重開機後服務掛掉，你上去手動 `systemctl start collector` 就正常** ——
> 因為手動 start 的當下 cache 早就被別的東西帶起來了，或你先手動起了 cache。
> 這個症狀會讓維運誤判成「程式有 bug」，追一整天。
>
> **事故 B：亂寫 `Requires=` 造成連鎖失敗（★★★）**
> ```ini
> Requires=mysql.service
> After=mysql.service
> ```
> 看起來很合理，但代價是：MySQL 做維護 `systemctl restart mysql`，
> **你的 5 個 worker 會被一起停掉，而且不會自己回來**（`Requires=` 的傳播是停止，不是重啟）。
> 資料庫維護窗口結束後，沒人記得要把 worker 拉回來，郵件靜靜堆積三天。
>
> **通則：預設用 `Wants=` + `After=`，把「連不上就重試」的責任交給應用與 `Restart=on-failure`。**
> 只有在「對方不在我就絕對不該存在」（例如綁定某個 VPN 介面、某個 LUKS 裝置）才用 `Requires=`／`BindsTo=`。

### unit 的完整生命週期

寫 unit 之前先把這張圖背起來，排錯時省一半時間：

```
  systemctl start x.service
        │
        ▼
  ┌─────────────────┐  exit 1~254 ──► 靜默跳過，unit 不算 failed（狀態 inactive）
  │ ExecCondition=  │  exit 255 / 被訊號殺 ──► failed
  └────────┬────────┘
           │ exit 0
           ▼
  ┌─────────────────┐  任一行非 0（且沒有 "-" 前綴）
  │ ExecStartPre=   │  ──► 整個啟動失敗，ExecStart 不會跑
  │ （可多行，序列）│      ★★★ 而且 ExecStop= 會被「跳過」，直接跑 ExecStopPost=
  └────────┬────────┘
           ▼
  ┌─────────────────┐  「算啟動完成」的判定點由 Type= 決定：
  │ ExecStart=      │    simple → fork 完就算
  │                 │    exec   → execve() 成功才算
  │                 │    oneshot→ 跑完且 exit 0 才算
  │                 │    notify → 收到 READY=1 才算
  └────────┬────────┘  超過 TimeoutStartSec=（預設 90s）── ► failed
           ▼
  ┌─────────────────┐
  │ ExecStartPost=  │  ★★ 這一段也算進 After= 的排序，後面的 unit 會等它
  └────────┬────────┘
           ▼
       active (running) ◄──── ExecReload=（systemctl reload）
           │
           │ systemctl stop
           ▼
  ┌─────────────────┐
  │ ExecStop=       │  沒設就直接送訊號
  └────────┬────────┘
           ▼
   送 KillSignal=（預設 SIGTERM）+ SIGCONT
           │
           │ 等 TimeoutStopSec=（預設 90s）
           ▼
   還活著 → 送 FinalKillSignal=（預設 SIGKILL）    ★★★★ 這就是「stop 卡 90 秒」的真相
           │
           ▼
  ┌─────────────────┐
  │ ExecStopPost=   │  ★★★ 不管成功失敗都會跑 → 清理邏輯放這裡才保險
  └─────────────────┘
```

### 「能上線」與「能交接」的差距

| 項目 | 只求能跑 | 能交接、能稽核 |
| --- | --- | --- |
| 執行身分 | `User=root` | ★★★★ 專屬系統帳號 `useradd --system` |
| 機密 | `Environment="DB_PASS=..."` | ★★★★ `EnvironmentFile=` + `640 root:svc` |
| 目錄 | 腳本裡 `mkdir -p /run/app` | ★★★★ `RuntimeDirectory=` 交給 systemd |
| 多實例 | 複製 3 份 `.service` | ★★★ template unit `app@.service` |
| 改官方 unit | 直接編 `/usr/lib/systemd/system/` | ★★★★ drop-in `/etc/systemd/system/x.d/` |
| 版本控管 | 沒有 | ★★★ unit 檔納入 git（[[020-02-03-00-idx-標準化-伺服器建置與標準化]]）|
| 驗證 | `restart` 看看會不會炸 | ★★★ `systemd-analyze verify` + `systemd-run` 試跑 |

---

## 基礎設定

### 開機起不來、手動 start 就好：network-online.target

這是頭號嫌疑犯，值得完整重現一次。

`collector` 要綁在管理網段的固定 IP `10.20.30.40` 上：

```ini
# /etc/systemd/system/collector.service —— ★★★★ 這是壞掉的版本
[Unit]
Description=Asset Collector
After=network.target

[Service]
Type=simple
User=collector
ExecStart=/opt/collector/venv/bin/python -m collector --bind 10.20.30.40:9100

[Install]
WantedBy=multi-user.target
```

重開機之後：

```bash
systemctl status collector
```

預期輸出：

```text
● collector.service - Asset Collector
     Loaded: loaded (/etc/systemd/system/collector.service; enabled)
     Active: failed (Result: exit-code) since Fri 2026-08-28 08:31:07 CST; 3min ago
    Process: 921 ExecStart=/opt/collector/venv/bin/python -m collector --bind 10.20.30.40:9100 (code=exited, status=1/FAILURE)

8月 28 08:31:07 srv01 python[921]: OSError: [Errno 99] Cannot assign requested address   # ★★★★ 關鍵字
```

```bash
sudo systemctl start collector      # 手動起就正常，於是你以為是「偶發」
systemctl is-active collector
```

```text
active
```

**成因**：`network.target` 的語意是「網路**子系統**已經啟動」（`systemd-networkd` 這個 daemon 起來了），
**不代表任何一張網卡拿到 IP**。綁定特定位址、需要 DNS、需要連外的服務都必須等 `network-online.target`。

**修法有兩半，缺一不可：**

```ini
[Unit]
Description=Asset Collector
After=network-online.target
Wants=network-online.target      # ★★★★ 這行沒寫，target 根本不會被拉起來，After 等於白寫
```

```bash
# 第二半：確認 wait-online 服務有 enable，否則 network-online.target 會「秒到達」
systemctl is-enabled systemd-networkd-wait-online.service
```

```text
enabled
```

| 你的網路管理者 | 要 enable 的服務 | 常見情境 |
| --- | --- | --- |
| ★★★★ `systemd-networkd`（netplan 預設 renderer） | `systemd-networkd-wait-online.service` | Ubuntu Server、雲端映像 |
| ★★★ `NetworkManager` | `NetworkManager-wait-online.service` | Ubuntu Desktop、RHEL 系 |
| ★★ `ifupdown` | `networking.service` 自帶等待 | 老 Debian |

```bash
# 看 network-online.target 實際被誰滿足
systemctl list-dependencies network-online.target
```

```text
network-online.target
● └─systemd-networkd-wait-online.service
```

> [!warning] 兩個進一步的坑（★★★）
> **坑一：多張網卡時 wait-online 會等到最慢的那張。**
> 有一張沒插線的備援網卡，開機就會卡到 `systemd-networkd-wait-online` 的預設 120 秒逾時。
> 指定只等某張：
> ```bash
> sudo systemctl edit systemd-networkd-wait-online.service
> ```
> ```ini
> [Service]
> ExecStart=
> ExecStart=/usr/lib/systemd/systemd-networkd-wait-online --interface=ens18 --timeout=30
> ```
> 注意這裡也要**先寫空的 `ExecStart=`**，理由見下方 drop-in 一節。
>
> **坑二：`network-online.target` 只保證「有 IP」，不保證「DNS 解得開」或「防火牆規則已載入」。**
> 需要 DNS 的服務再加 `After=nss-lookup.target`；
> 真正穩健的做法是**在應用層做連線重試**，unit 只負責大方向的時序。

### 資料在 NFS／iSCSI／額外磁碟上：RequiresMountsFor=

`collector` 把收集結果寫到 NAS 掛載的 `/srv/share/uploads`。
**如果掛載還沒完成服務就啟動，它會寫進本機那個空目錄** —— 掛載完成後這些檔案被蓋在下面，
從此看不見也刪不掉，而且監控完全不會叫。這是 ★★★★ 級的無聲資料遺失。

`/etc/fstab`：

```text
nas01:/export/uploads  /srv/share/uploads  nfs  _netdev,x-systemd.automount,x-systemd.idle-timeout=600,x-systemd.mount-timeout=30,nofail,noatime  0 0
```

| fstab 選項 | systemd 做了什麼 | 星級 |
| --- | --- | --- |
| `_netdev` | 自動加上 `After=network-online.target`、掛進 `remote-fs.target` | ★★★★ |
| `x-systemd.automount` | 產生 `.automount` unit，**第一次被存取才真的掛**，開機不會卡 | ★★★★ |
| `x-systemd.mount-timeout=30` | 掛載逾時（預設吃 `DefaultTimeoutStartSec`，90 秒） | ★★★ |
| `x-systemd.idle-timeout=600` | 閒置 10 分鐘自動卸載（搭配 automount） | ★★ |
| `nofail` | 掛不上不擋開機（但也代表你的服務要自己防呆） | ★★★ |
| `x-systemd.requires=` | 手動指定它相依的 unit（例如 iSCSI 的 `iscsi.service`） | ★★★ |

unit 這邊：

```ini
[Unit]
Description=Asset Collector
After=network-online.target
Wants=network-online.target
RequiresMountsFor=/srv/share/uploads      # ★★★★ 一行搞定：自動加 Requires= 與 After= 到對應的 .mount
```

`RequiresMountsFor=` 會自己算出路徑對應到哪個 mount unit。想知道是哪一個：

```bash
systemd-escape -p --suffix=mount /srv/share/uploads
```

```text
srv-share-uploads.mount
```

```bash
systemctl list-dependencies --after collector.service | grep -i mount
```

```text
● ├─srv-share-uploads.mount        # ★★★ 出現這行就代表相依正確建立了
```

> [!tip] 改完 `/etc/fstab` 一定要 `daemon-reload`（★★★）
> fstab 是被 `systemd-fstab-generator` 轉成 mount unit 的，**改了檔案 systemd 不會自己知道**：
> ```bash
> sudo systemctl daemon-reload
> sudo systemctl restart remote-fs.target
> ```
> 這一步漏掉的話，你會看到「fstab 明明改好了，`RequiresMountsFor=` 卻說找不到 mount unit」。
> 磁碟與掛載本身見 [[020-01-15-cmd-Linux-磁碟分割與掛載]]、[[020-01-29-guide-Linux-網路儲存與軟體RAID]]。

> [!warning] `WantsMountsFor=` 需要 systemd 256 以上
> v256 才有的弱版（加 `Wants=` 而非 `Requires=`）。
> Ubuntu 24.04 是 systemd 255、22.04 是 249、RHEL 9 是 252，**都沒有**。
> 在這些版本上只能用 `RequiresMountsFor=`，並靠 fstab 的 `nofail` 控制開機不被擋住。

### Exec* 家族：執行順序與失敗語意

```ini
[Service]
Type=simple
ExecCondition=/usr/local/bin/only-on-primary.sh      # 不是主節點就靜默跳過
ExecStartPre=/usr/bin/install -d -o app -g app -m 0750 /var/lib/app/tmp
ExecStartPre=/opt/app/bin/app --config-test          # ★★★★ 設定檔錯就不要啟動
ExecStart=/opt/app/bin/app --serve
ExecStartPost=-/usr/local/bin/notify-deploy.sh       # 前面的 "-" ：失敗也不影響服務
ExecReload=/bin/kill -HUP $MAINPID
ExecStop=/opt/app/bin/app --graceful-stop
ExecStopPost=-/bin/rm -f /run/app/app.lock           # 不管成功失敗都會跑
```

| 規則 | 說明 | 星級 |
| --- | --- | --- |
| 多行 `ExecStartPre=` **依序**執行 | 任一行非 0（且無 `-`）→ 後面全部跳過、整個啟動失敗 | ★★★★ |
| `ExecStart=` 只能有一行 | 例外：`Type=oneshot` 可以多行 | ★★★★ |
| `ExecStartPre=` **不能**啟動長駐程序 | 它 fork 出來的所有程序在下一步之前會被殺掉 | ★★★ |
| 啟動階段失敗 → **跳過 `ExecStop=`** | 只跑 `ExecStopPost=`，清理邏輯要放後者 | ★★★ |
| `ExecStartPost=` 算進 `After=` 排序 | 你在這裡 `sleep 30`，後面的 unit 就等 30 秒 | ★★ |
| `ExecReload=` 沒設 → `systemctl reload` 直接報錯 | 用 `reload-or-restart` 較安全 | ★★ |

**命令前綴**（可疊加，順序不拘）：

| 前綴 | 意義 | 什麼時候該用 |
| --- | --- | --- |
| ★★★ `-` | 非 0 退出視同成功 | 清理、通知這類「失敗也無所謂」的動作 |
| ★★★★★ `+` | 以**完整權限（root）**執行，`User=`／`Group=`／`CapabilityBoundingSet=`／檔案系統沙箱（`PrivateTmp=`、`ProtectSystem=` 等）**對這一行不生效** | 幾乎永遠不該用，理由見下方 danger |
| ★★ `!` | 只跳過 `User=`／`Group=`／`SupplementaryGroups=`，**沙箱仍然生效** | 需要 root 但仍想保留沙箱時 |
| ★ `:` | 不做環境變數展開（`$VAR` 原樣傳入） | 參數本身含 `$` |
| ★ `@` | 第二個 token 當作 `argv[0]` | 少見 |

> [!danger] ★★★★★ `+` 前綴指到一個「別人可寫」的腳本，等同開一個 root 後門
> ```ini
> [Service]
> User=laravel
> ExecStartPre=+/srv/www/app/scripts/pre-start.sh     # ✗ 極度危險
> ```
> `/srv/www/app/` 是**部署流程會覆寫的目錄**，任何能推 code、能寫入該路徑的人
> （委外廠商、CI 的 deploy key、被入侵的 web 帳號）只要改一行這支腳本，
> 下一次 `systemctl restart` 就以 **root** 執行他寫的東西。整台機器沒了。
>
> 判斷準則：**凡是用 `+` 或 `User=root`，那支被執行的檔案必須是
> `root:root` 擁有、`0755`（目錄一路到根也都不可被他人寫入）。**
> ```bash
> sudo install -o root -g root -m 0755 pre-start.sh /usr/local/sbin/app-pre-start.sh
> namei -l /usr/local/sbin/app-pre-start.sh      # ★★★★ 逐層檢查路徑上每個目錄的權限
> ```
> ```text
> f: /usr/local/sbin/app-pre-start.sh
>  drwxr-xr-x root root /
>  drwxr-xr-x root root usr
>  drwxr-xr-x root root local
>  drwxr-xr-x root root sbin
>  -rwxr-xr-x root root app-pre-start.sh
> ```
> 只要中間有任何一層是 `drwxrwxr-x deploy deploy`，這個 `+` 就是後門。

### 目錄與權限交給 systemd，不要自己 mkdir

```ini
[Service]
User=collector
Group=collector

RuntimeDirectory=collector                # → /run/collector          （stop 時自動刪）
RuntimeDirectoryMode=0750
StateDirectory=collector                  # → /var/lib/collector      （保留）
StateDirectoryMode=0750
LogsDirectory=collector                   # → /var/log/collector      （保留）
CacheDirectory=collector                  # → /var/cache/collector    （保留）
ConfigurationDirectory=collector          # → /etc/collector          （保留，維持 root 擁有）
ConfigurationDirectoryMode=0750
```

systemd 會在**每次啟動前**建好目錄、把擁有者設成 `User=`／`Group=`、把權限設成 `*Mode=`，
並把絕對路徑塞進環境變數給程式用：

```bash
sudo systemctl show collector -p Environment
```

```text
Environment=RUNTIME_DIRECTORY=/run/collector STATE_DIRECTORY=/var/lib/collector LOGS_DIRECTORY=/var/log/collector
```

```python
# collector/__main__.py —— ★★★ 直接讀環境變數，路徑就不會寫死在程式裡
import os
state_dir = os.environ.get("STATE_DIRECTORY", "/var/lib/collector")
```

| 指令 | 根路徑（system 模式） | stop 時會刪嗎 | 擁有者 |
| --- | --- | --- | --- |
| ★★★★ `RuntimeDirectory=` | `/run/` | **會**（除非 `RuntimeDirectoryPreserve=yes\|restart`） | `User=`／`Group=` |
| ★★★ `StateDirectory=` | `/var/lib/` | 不會 | `User=`／`Group=` |
| ★★★ `LogsDirectory=` | `/var/log/` | 不會 | `User=`／`Group=` |
| ★★ `CacheDirectory=` | `/var/cache/` | 不會 | `User=`／`Group=` |
| ★★ `ConfigurationDirectory=` | `/etc/` | 不會 | **root**（唯一例外） |

> [!danger] ★★★★ 經典事故：自己在 `/run` 底下 `mkdir`，重開機後服務永久起不來
> ```bash
> # 上線那天有人這樣做，當下完全正常
> sudo mkdir -p /run/collector && sudo chown collector:collector /run/collector
> sudo systemctl start collector          # ✓ active (running)
> ```
> 三個月後機房停電重開機：
> ```text
> collector.service: Failed to open PID file /run/collector/collector.pid: No such file or directory
> collector.service: Failed with result 'protocol'.
> ```
> **`/run` 是 tmpfs，每次開機都是空的。** 手動建的目錄不存在了，
> 服務寫不出 PID 檔／unix socket，`Type=forking` 直接判定啟動失敗。
> 而且因為「上線時明明測過」，沒人會往這裡想。
>
> 正解就一行：
> ```ini
> RuntimeDirectory=collector
> ```
> 舊系統若真的需要更複雜的生命週期（例如多個服務共用的目錄），才用 `tmpfiles.d`：
> ```bash
> echo 'd /run/shared-sock 0770 root svcgrp -' | sudo tee /etc/tmpfiles.d/shared-sock.conf
> sudo systemd-tmpfiles --create /etc/tmpfiles.d/shared-sock.conf
> ```

> [!warning] 沒有 `StateDirectoryOwner=` 這種指令（★★★）
> 常有人照著印象寫 `StateDirectoryOwner=collector`，`systemd-analyze verify` 會報
> `Unknown key 'StateDirectoryOwner' in section [Service]`，然後整份 unit 被拒載。
> **擁有者是自動跟著 `User=`／`Group=` 走的**，只有 `*Mode=` 這一組指令存在。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> unit 語法完全相同，差異在周邊：
>
> | 項目 | Ubuntu / Debian | Rocky / AlmaLinux |
> | --- | --- | --- |
> | 網路管理者 | `systemd-networkd`（netplan） | `NetworkManager` |
> | wait-online 服務 | `systemd-networkd-wait-online.service` | `NetworkManager-wait-online.service` |
> | nologin 路徑 | `/usr/sbin/nologin` | **`/sbin/nologin`** |
> | 系統帳號建立 | `useradd --system` 相同 | 相同 |
> | 強制存取控制 | AppArmor | **SELinux** |
> | 套件 unit 位置 | `/lib/systemd/system/`（連到 `/usr/lib/`） | `/usr/lib/systemd/system/` |
> | systemd 版本 | 24.04 → 255；22.04 → 249 | RHEL 9 → 252；RHEL 8 → 239 |
>
> ★★★★ **SELinux 是 RHEL 系獨有的第二層阻擋。** 你的 unit 沙箱都設對了、權限也對，
> 服務仍然 `Permission denied`，先看：
> ```bash
> sudo ausearch -m avc -ts recent | audit2why
> ```
> 自訂執行檔放在 `/opt` 底下常見的 label 修法：
> ```bash
> sudo semanage fcontext -a -t bin_t "/opt/collector/venv/bin(/.*)?"
> sudo restorecon -Rv /opt/collector
> ```
> 詳見 [[090-02-07-guide-防護-SELinux與AppArmor]]。
>
> ★★★ RHEL 8 的 systemd 239 **沒有 `ExecCondition=`**（v243 才有）、
> 沒有 `Type=notify-reload`（v253）。在 RHEL 8 上寫這些會讓 unit 直接載入失敗。

---

## 進階設定與調校

### Template unit：一份檔案管三條 queue

檔名裡有 `@` 的就是 template：`laravel-worker@.service`。
`@` 後面的字串叫 **instance name**，在 unit 檔裡用 `%i` 取用。

```ini
# /etc/systemd/system/laravel-worker@.service
[Unit]
Description=Laravel queue worker (%i)          # → "Laravel queue worker (mail)"
After=network-online.target mysql.service
Wants=network-online.target mysql.service

[Service]
Type=simple
User=laravel
Group=laravel
WorkingDirectory=/srv/www/app-a
EnvironmentFile=/etc/laravel/app-a.env
StateDirectory=laravel/%p                      # → /var/lib/laravel/laravel-worker
LogsDirectory=laravel/%p                       # → /var/log/laravel/laravel-worker
ExecStart=/usr/bin/php artisan queue:work --queue=%i --sleep=3 --tries=3 --max-time=3600
SyslogIdentifier=lw-%i                         # ★★★ journal 裡好過濾：journalctl -t lw-mail

[Install]
WantedBy=multi-user.target
```

| Specifier | 展開成什麼（以 `laravel-worker@mail.service` 為例） | 常用度 |
| --- | --- | --- |
| ★★★★ `%i` | `mail`（`@` 與副檔名之間的字串，**保留跳脫**） | 最常用 |
| ★★★ `%I` | `mail`（同 `%i`，但**還原跳脫**：`-` 會變回 `/`） | 路徑型實例必用 |
| ★★★ `%p` | `laravel-worker`（prefix，`@` 之前） | 拿來組目錄名 |
| ★★ `%P` | 同 `%p` 但還原跳脫 | |
| ★★ `%n` | `laravel-worker@mail.service`（完整 unit 名） | 寫日誌標籤 |
| ★★ `%N` | `laravel-worker@mail`（去掉 `.service`） | |
| ★★★ `%t` | `/run`（Runtime 根） | 組 socket 路徑 |
| ★★★ `%S` | `/var/lib`（State 根） | |
| ★★ `%L` | `/var/log`（Logs 根） | |
| ★ `%C` / `%E` | `/var/cache` / `/etc` | |
| ★★ `%H` | 主機名稱（unit 載入當下） | 多台共用同一份 unit |
| ★★ `%u` | `User=` 指定的使用者名稱 | |
| ★ `%h` | 執行 service manager 的使用者家目錄（system 模式是 `/root`） | 容易誤用 |
| ★ `%%` | 一個字面上的 `%` | |

啟用三個實例：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now laravel-worker@{default,mail,report}.service
```

預期輸出：

```text
Created symlink '/etc/systemd/system/multi-user.target.wants/laravel-worker@default.service' → '/etc/systemd/system/laravel-worker@.service'.
Created symlink '/etc/systemd/system/multi-user.target.wants/laravel-worker@mail.service' → '/etc/systemd/system/laravel-worker@.service'.
Created symlink '/etc/systemd/system/multi-user.target.wants/laravel-worker@report.service' → '/etc/systemd/system/laravel-worker@.service'.
```

```bash
systemctl list-units 'laravel-worker@*' --no-pager
```

```text
UNIT                             LOAD   ACTIVE SUB     DESCRIPTION
laravel-worker@default.service   loaded active running Laravel queue worker (default)
laravel-worker@mail.service      loaded active running Laravel queue worker (mail)
laravel-worker@report.service    loaded active running Laravel queue worker (report)
```

> [!danger] ★★★★ 只 enable 了一個實例 —— 最安靜的一種故障
> `systemctl start laravel-worker@mail` 可以不 enable 就直接跑，
> 所以上線當天三個都在跑、測試全過。但 `enable` 只做了 `default` 的話，
> **重開機後只有 default 回來**，mail 與 report 兩條 queue 從此沒人處理。
> 沒有錯誤日誌、沒有 alert，只有使用者三天後問「為什麼沒收到通知信」。
>
> 上線前一定要做這個檢查：
> ```bash
> ls -1 /etc/systemd/system/multi-user.target.wants/ | grep '^laravel-worker@'
> ```
> ```text
> laravel-worker@default.service
> laravel-worker@mail.service
> laravel-worker@report.service      # ★★★★ 三個都在，才算 enable 完成
> ```
> 或直接比對「在跑但沒 enable」的：
> ```bash
> for i in default mail report; do
>   printf '%-10s active=%s enabled=%s\n' "$i" \
>     "$(systemctl is-active laravel-worker@$i)" \
>     "$(systemctl is-enabled laravel-worker@$i)"
> done
> ```
> ```text
> default    active=active enabled=enabled
> mail       active=active enabled=disabled     # ← 就是它
> report     active=active enabled=disabled
> ```

**實例名含 `/` 時必須跳脫**（例如以路徑當實例的備份服務）：

```bash
systemd-escape --template=backup@.service /srv/data
```

```text
backup@-srv-data.service
```

```bash
systemd-escape -u -- '-srv-data'
```

```text
/srv/data
```

unit 裡就用 `%I` 拿回原本的路徑：

```ini
ExecStart=/usr/local/bin/backup.sh %I      # → /usr/local/bin/backup.sh /srv/data
```

> [!tip] `DefaultInstance=`（★★）
> 在 template 的 `[Install]` 加：
> ```ini
> [Install]
> WantedBy=multi-user.target
> DefaultInstance=default
> ```
> 讓 `systemctl enable laravel-worker@.service`（沒給實例名）等同 enable `@default`。
> 好處是不容易誤 enable 一個空實例名。

### drop-in override 的正式做法

| 做法 | 產生什麼 | 套件升級會被蓋嗎 | 什麼時候用 |
| --- | --- | --- | --- |
| ★★★★ `systemctl edit <unit>` | `/etc/systemd/system/<unit>.d/override.conf` | 不會 | **預設選這個**，只寫差異 |
| ★★★ `systemctl edit --drop-in=90-hardening.conf <unit>`（v253+） | 同上，但檔名自訂 | 不會 | 多個面向分檔管理 |
| ★★ `systemctl edit --full <unit>` | 整份複製到 `/etc/systemd/system/<unit>` | 不會，但**也吃不到官方的修正** | 要大改結構時 |
| ★ `systemctl edit --runtime <unit>` | `/run/systemd/system/...`，重開機消失 | — | 臨時實驗 |
| ✗ 直接編 `/usr/lib/systemd/system/` | — | **會，而且無聲** | 永遠不要 |

`.d/` 目錄裡的檔案**依檔名字母序合併**，所以慣例加數字前綴：

```text
/etc/systemd/system/nginx.service.d/
├── 10-limits.conf         # 資源上限
├── 50-restart.conf        # 重啟策略
└── 90-hardening.conf      # 沙箱
```

> [!danger] ★★★★ list 型指令沒先清空 → 變成兩條 `ExecStart=`
> ```ini
> # /etc/systemd/system/nginx.service.d/override.conf  ✗ 壞掉的寫法
> [Service]
> ExecStart=/usr/local/nginx/sbin/nginx -g 'daemon off;'
> ```
> 這**不是**取代，是**追加**。實測結果：
> ```bash
> systemd-analyze verify /etc/systemd/system/dup.service
> ```
> ```text
> dup.service: Service has more than one ExecStart= setting, which is only allowed for Type=oneshot services. Refusing.
> Unit dup.service has a bad unit file setting.
> ```
> - `Type=simple` / `exec` / `notify` → **直接被拒載**，`systemctl status` 顯示
>   `Loaded: bad-setting`，而且錯誤訊息只在 `daemon-reload` 當下閃過一次。
> - `Type=oneshot` → **不報錯，兩條依序執行**，於是服務起了兩份或做了兩次遷移。
>
> 正確寫法是先給一行空值把清單歸零：
> ```ini
> [Service]
> ExecStart=
> ExecStart=/usr/local/nginx/sbin/nginx -g 'daemon off;'
> ```
>
> **哪些是 list 型？**（這些都要先清空）
> `ExecStart=` `ExecStartPre=` `ExecStartPost=` `ExecStop=` `ExecStopPost=` `ExecReload=`
> `Environment=` `EnvironmentFile=` `After=` `Before=` `Wants=` `Requires=` `Conflicts=`
> `ReadWritePaths=` `ReadOnlyPaths=` `InaccessiblePaths=` `RestrictAddressFamilies=`
> `SystemCallFilter=` `SupplementaryGroups=` `AmbientCapabilities=` `RuntimeDirectory=`
>
> **哪些是純量型？**（直接寫就是覆蓋，不用清空）
> `Type=` `User=` `Group=` `Restart=` `RestartSec=` `TimeoutStopSec=` `KillMode=`
> `MemoryMax=` `WorkingDirectory=` `ProtectSystem=` `NoNewPrivileges=`

驗證合併結果：

```bash
systemctl cat nginx
```

```text
# /lib/systemd/system/nginx.service
[Unit]
Description=A high performance web server and a reverse proxy server
...
ExecStart=/usr/sbin/nginx -g 'daemon on; master_process on;'

# /etc/systemd/system/nginx.service.d/override.conf     # ★★★★ 分隔線之後是你加的
[Service]
ExecStart=
ExecStart=/usr/local/nginx/sbin/nginx -g 'daemon off;'
```

```bash
systemctl show nginx -p ExecStart
```

```text
ExecStart={ path=/usr/local/nginx/sbin/nginx ; argv[]=/usr/local/nginx/sbin/nginx -g daemon off; ; ... }
```

★★★★ **`systemctl show` 才是最終仲裁**。`systemctl cat` 只是把檔案接起來給你看，
上面若出現**兩個** `ExecStart={...}` 區塊，就是清空那行漏了。

盤點全機哪些 unit 被動過手腳（交接與稽核必跑）：

```bash
systemd-delta --type=extended,overridden
```

```text
[EXTENDED]   /lib/systemd/system/nginx.service → /etc/systemd/system/nginx.service.d/override.conf
[EXTENDED]   /lib/systemd/system/ssh.service → /etc/systemd/system/ssh.service.d/10-limits.conf
[OVERRIDDEN] /etc/systemd/system/rsyslog.service → /lib/systemd/system/rsyslog.service

3 overridden configuration files found.
```

復原：

```bash
sudo systemctl revert nginx        # 刪掉 /etc 底下所有 drop-in 與 --full 複本
sudo systemctl daemon-reload
sudo systemctl restart nginx
```

> [!warning] ★★★ 改完 unit 沒 `daemon-reload`，你測的是舊設定
> ```text
> Warning: The unit file, source configuration file or drop-ins of nginx.service changed
> on disk. Run 'systemctl daemon-reload' to reload units.
> ```
> 這行警告只在你下次操作該 unit 時出現，很容易被忽略。
> **順序永遠是：改檔案 → `daemon-reload` → `restart`。**
> `systemctl edit` 會自動幫你 reload，手動編檔案則不會。

### 停機語意：「stop 卡 90 秒」到底發生什麼事

```text
$ time sudo systemctl stop laravel-worker@report
（等⋯⋯）
real    1m30.412s
```

journal 會留下完整證據：

```bash
sudo journalctl -u laravel-worker@report -n 10 --no-pager
```

```text
8月 28 14:02:11 srv01 systemd[1]: Stopping Laravel queue worker (report)...
8月 28 14:03:41 srv01 systemd[1]: laravel-worker@report.service: State 'stop-sigterm' timed out. Killing.   # ★★★★
8月 28 14:03:41 srv01 systemd[1]: laravel-worker@report.service: Killing process 3312 (php) with signal SIGKILL.
8月 28 14:03:41 srv01 systemd[1]: laravel-worker@report.service: Main process exited, code=killed, status=9/KILL
8月 28 14:03:41 srv01 systemd[1]: Stopped Laravel queue worker (report).
```

| 指令 | 預設值 | 意義 | 星級 |
| --- | --- | --- | --- |
| `TimeoutStartSec=` | 90s（`DefaultTimeoutStartSec`） | 啟動超過就判 failed | ★★★ |
| ★★★★ `TimeoutStopSec=` | 90s | 送 SIGTERM 後等多久才 SIGKILL | ★★★★ |
| `TimeoutSec=` | — | 同時設上面兩個 | ★★ |
| `TimeoutAbortSec=` | 吃 `TimeoutStopSec=` | watchdog 觸發時的逾時 | ★★ |
| `KillSignal=` | `SIGTERM` | 第一步送什麼訊號 | ★★★ |
| `RestartKillSignal=` | 同 `KillSignal=` | 只在 restart 時用 | ★★ |
| `FinalKillSignal=` | `SIGKILL` | 逾時後補刀 | ★★ |
| `SendSIGKILL=` | `yes` | 設 `no` 就永遠不補刀（**服務可能卡在 deactivating**） | ★★★ |
| `SendSIGHUP=` | `no` | SIGTERM 後立刻補一個 SIGHUP | ★ |

`KillMode=` 決定**誰**收到訊號：

| 值 | SIGTERM 送給 | SIGKILL 送給 | 建議 |
| --- | --- | --- | --- |
| ★★★★ `control-group`（預設） | cgroup 內**所有**程序 | cgroup 內所有程序 | **絕大多數情況用這個** |
| ★★★ `mixed` | 只有主程序 | cgroup 內所有程序 | 主程序要負責優雅收掉子程序時（Nginx、PHP-FPM） |
| ★★ `process` | 只有主程序 | 只有主程序 | 不建議：子程序會逃出生命週期 |
| ★ `none` | 沒有 | 沒有 | 強烈不建議，只跑 `ExecStop=` |

**三種讓 stop 卡住的成因，判斷方式不同：**

```bash
# 【成因一】程式根本不理 SIGTERM
sudo systemctl show laravel-worker@report -p MainPID
```

```text
MainPID=3312
```

```bash
grep -E 'SigCgt|SigIgn' /proc/3312/status
```

```text
SigIgn:	0000000000001000
SigCgt:	0000000180004a03      # ★★★ 用 bit 15 (SIGTERM=15) 判斷有沒有註冊 handler
```

PHP 沒編 `pcntl` 擴充時，`queue:work` 收不到 SIGTERM 也不會提早結束：

```bash
php -m | grep -i pcntl || echo "★★★★ 沒有 pcntl → queue:work 無法優雅停止"
```

```text
★★★★ 沒有 pcntl → queue:work 無法優雅停止
```

```bash
# 【成因二】子程序沒被算進 cgroup（KillMode 選錯，或用了 sh -c 沒 exec）
systemctl status laravel-worker@report | sed -n '/CGroup/,$p'
```

```text
     CGroup: /system.slice/system-laravel\x2dworker.slice/laravel-worker@report.service
             ├─3312 /bin/sh -c /usr/bin/php artisan queue:work ...    # ★★★★ shell 收到訊號
             └─3313 php artisan queue:work --queue=report              #      php 沒收到
```

★★★★ **用 `sh -c` 包一層卻沒有 `exec`，訊號只送到 shell，真正的程式毫無所覺。**
修法二選一：

```ini
ExecStart=/usr/bin/php artisan queue:work --queue=%i        # ✓ 最好：根本不要 shell
# 非用 shell 不可時：
ExecStart=/bin/sh -c 'exec /usr/bin/php artisan queue:work --queue=%i'   # ✓ exec 取代 shell 本體
```

```bash
# 【成因三】TimeoutStopSec 比應用最長一筆工作短
systemctl show laravel-worker@report -p TimeoutStopUSec
```

```text
TimeoutStopUSec=1min 30s
```

> [!danger] ★★★★ `TimeoutStopSec=` 沒對齊 graceful shutdown ＝ 部署時砍掉進行中的交易
> Laravel `queue:work` 收到 SIGTERM 後的行為是：**把手上那一筆做完再退出**。
> 如果你的報表 job 要跑 5 分鐘，而 `TimeoutStopSec=90`，
> 每次 `systemctl restart` 都會在第 90 秒 SIGKILL —— job 做到一半、
> 資料庫寫了一半、檔案產出一半，而且因為是被 SIGKILL，
> Laravel 連把它退回 queue 的機會都沒有（除非有設 `--tries` 與 `retry_after`）。
>
> **對齊規則：**
> ```
> TimeoutStopSec  ≥  單筆 job 最長執行時間  +  30 秒緩衝
> ```
> 而且要與 `queue:work --timeout=` 一起看：
> ```ini
> ExecStart=/usr/bin/php artisan queue:work --queue=%i --timeout=300 --max-time=3600
> TimeoutStopSec=360        # ★★★★ = job timeout 300 + 60 秒緩衝
> KillMode=mixed
> ```
> 對 Web 服務同理：Nginx／Nuxt SSR 的 `TimeoutStopSec=` 要大於最長的請求處理時間，
> 否則部署時使用者會看到連線被硬切。

### Type=notify：讓「起來了」真的等於「能接請求」

`Type=simple` 的問題：systemd 在 `fork()` 完成的那一瞬間就宣告啟動成功。
但你的 Nuxt SSR 可能還要 8 秒才 listen。這 8 秒內：

- `After=nuxt-ssr.service` 的 Nginx 已經開始轉發 → **502**
- 部署腳本 `systemctl restart && curl localhost:3000` → **connection refused**，誤判部署失敗
- 應用因為設定檔錯誤而在第 2 秒退出 → `systemctl start` 卻早就回傳成功

| Type | 判定「啟動完成」的時機 | 抓得到什麼失敗 | 星級 |
| --- | --- | --- | --- |
| `simple` | `fork()` 完成 | 幾乎什麼都抓不到 | ★★ |
| ★★★ `exec` | `execve()` 成功回傳 | **執行檔不存在、權限不對、沙箱擋住** | ★★★ |
| ★★★★ `notify` | 應用送出 `READY=1` | **設定檔錯、埠被佔用、資料庫連不上** | ★★★★ |
| `notify-reload`（v253+） | 同上，且 `reload` 也走 sd_notify | reload 失敗 | ★★★ |
| `oneshot` | 命令跑完且 exit 0 | 一切 | ★★★ |

**改應用值不值得？** 判斷標準：這個服務**後面有沒有人在等它**。
Nginx 要反向代理它、部署腳本要立刻打健康檢查、資料庫遷移要在它之前完成 —— 有其一就值得。

Node（Nuxt SSR）端最小改法：

```javascript
// server-entry.mjs —— ★★★ 不需要額外套件，直接寫 unix datagram socket
import { createSocket } from 'node:dgram'

function sdNotify (state) {
  const path = process.env.NOTIFY_SOCKET
  if (!path) return                       // 不是被 systemd 啟動時就安靜跳過
  const sock = createSocket('unix_dgram')
  sock.send(Buffer.from(state), 0, state.length, path.replace(/^@/, '\0'))
  sock.close()
}

server.listen(3000, () => {
  sdNotify('READY=1')                     // ★★★★ listen 成功之後才通知
  sdNotify('STATUS=listening on :3000')
})
process.on('SIGTERM', () => {
  sdNotify('STOPPING=1')
  server.close(() => process.exit(0))
})
```

Python 端（`collector`）：

```python
# ★★ Ubuntu: sudo apt install -y python3-systemd
from systemd.daemon import notify
notify("READY=1")
notify("STATUS=collecting from 42 hosts")
```

unit：

```ini
[Service]
Type=notify
NotifyAccess=main          # ★★★ 預設值：只接受「主程序」送的通知
TimeoutStartSec=60         # 應用要 8 秒起來，這裡給寬鬆一點但別無限
ExecStart=/usr/bin/node /srv/www/nuxt/.output/server/index.mjs
```

| `NotifyAccess=` | 誰可以送通知 | 星級 |
| --- | --- | --- |
| `main`（預設） | 只有主程序 | ★★★ |
| `exec` | 主程序與 `Exec*=` 直接啟動的程序 | ★★ |
| ★★★ `all` | cgroup 內任何程序（**包含 `ExecStartPost=` 裡的 shell**） | ★★★ |
| `none` | 不接受 | ★ |

不想改應用時的折衷（★★★，效果比 `simple` 好但比不上真的 sd_notify）：

```ini
Type=notify
NotifyAccess=all
ExecStart=/usr/bin/node /srv/www/nuxt/.output/server/index.mjs
ExecStartPost=/bin/sh -c 'until curl -sf http://127.0.0.1:3000/healthz >/dev/null; do sleep 1; done; systemd-notify --ready'
```

驗證：

```bash
systemd-analyze critical-chain nuxt-ssr.service
```

```text
nuxt-ssr.service +8.214s
└─network-online.target @3.102s
  └─systemd-networkd-wait-online.service @1.884s +1.216s
```

★★★ `+8.214s` 才是真正的「起來要多久」；`Type=simple` 時這個數字永遠是幾毫秒，毫無參考價值。

### oneshot + RemainAfterExit + SuccessExitStatus

給第 02 篇的 timer 服務用的形狀（timer 寫法見 [[020-02-02-02-cmd-systemd-timer與cron選型]]）：

```ini
# /etc/systemd/system/collector-import.service
[Unit]
Description=Nightly asset import
RequiresMountsFor=/srv/share/uploads

[Service]
Type=oneshot
RemainAfterExit=no                # 排程型任務：跑完就回 inactive
User=collector
StateDirectory=collector
ExecStart=/opt/collector/venv/bin/python -m collector.import
SuccessExitStatus=75              # ★★★ 75 = EX_TEMPFAIL：來源系統維護中，不算失敗
```

```bash
systemd-analyze exit-status 75
```

```text
NAME      CLASS  MAPPING
TEMPFAIL  BSD    75
```

| 情境 | `RemainAfterExit=` | 為什麼 |
| --- | --- | --- |
| ★★★ 排程任務（timer 觸發） | `no` | 跑完就該回 `inactive`，下次 timer 才好觸發 |
| ★★★★ 一次性的環境設定（載入 sysctl、建 bridge、掛 tmpfs） | **`yes`** | 否則跑完變 `inactive`，別人的 `Requires=` 立刻認定它掛了而連鎖失敗 |

```bash
systemctl status collector-setup      # RemainAfterExit=yes 的正常狀態
```

```text
● collector-setup.service - One-time network bridge setup
     Active: active (exited) since Fri 2026-08-28 08:30:55 CST; 6h ago    # ★★★ exited 但仍是 active
```

### 沙箱化的實務踩雷版

先量測現況：

```bash
systemd-analyze security laravel-worker@mail.service
```

```text
✗ PrivateNetwork=          Service has access to the host's network                    0.5
✗ PrivateTmp=              Service has access to other software's temporary files      0.2
✗ SystemCallFilter=~@debug Service does not filter system calls                        0.2
✗ IPAddressDeny=           Service does not define an IP address allow list            0.2
✗ UMask=                   Files created by service are world-readable by default      0.1
...
→ Overall exposure level for laravel-worker@mail.service: 9.2 UNSAFE 😨
```

還沒安裝的 unit 也能掃（部署前用）：

```bash
systemd-analyze security --offline=true --threshold=6 /etc/systemd/system/laravel-worker@.service
```

`--threshold=6` 讓分數高於 6 時回傳非 0 —— 這正好塞進 CI 或 pre-check 腳本。

**四個最常打臉的沙箱選項：**

| 選項 | 加上去之後會壞什麼 | 正確解法 | 星級 |
| --- | --- | --- | --- |
| `ProtectSystem=strict` | `/usr` `/boot` `/etc` **與整個 `/var`** 都變唯讀 → 服務寫不進 `/var/lib/app` | ★★★ **用 `StateDirectory=app`**（它會自動加進可寫清單），而不是把 `ProtectSystem` 降級 | ★★★ |
| `PrivateTmp=yes` | 服務看到的是私有 `/tmp`，**看不到別的程序放在 `/tmp` 的 unix socket** | 把 socket 移到 `/run/<app>/`（用 `RuntimeDirectory=`），這本來就是正確位置 | ★★★★ |
| `ProtectHome=yes` | 程式碼部署在 `/home/deploy/app` 時**整個讀不到**，`No such file or directory` | 把程式碼搬到 `/srv` 或 `/opt`；真的不能搬就用 `ProtectHome=read-only` | ★★★★ |
| `CapabilityBoundingSet=` 清空 | 服務綁不到 1024 以下的埠，`Permission denied` | 加 `AmbientCapabilities=CAP_NET_BIND_SERVICE` | ★★★ |

> [!danger] ★★★ `ProtectSystem=strict` 上線後才發現寫不進去，不要把它關掉
> ```text
> 8月 28 09:14:02 srv01 php[4021]: file_put_contents(/var/lib/app/cache/x): Read-only file system
> ```
> 錯誤的直覺反應：
> ```ini
> ProtectSystem=no        # ✗ 一行退回沒有保護的狀態
> ```
> 正解是把「這個服務該寫哪裡」講清楚：
> ```ini
> ProtectSystem=strict
> StateDirectory=app                    # ✓ /var/lib/app 自動變可寫且由服務帳號擁有
> LogsDirectory=app                     # ✓ /var/log/app
> ReadWritePaths=/srv/www/app-a/storage # ✓ 例外清單（Laravel 的 storage 目錄）
> ```
> 找出它到底想寫哪裡的通用手法：
> ```bash
> sudo journalctl -u laravel-worker@mail --since "5 min ago" \
>   | grep -iE 'read-only|permission denied|no such file'
> ```

**1024 以下的埠有三種解法，優先序如下：**

```ini
# 解法 1（★★★★ 最推薦）：根本不要綁低埠，讓 Nginx 反向代理
ExecStart=/usr/bin/node .output/server/index.mjs      # 聽 3000

# 解法 2（★★★）：只給這一個 capability
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes            # ★★★ ambient capability 不受 NoNewPrivileges 影響，可以並存

# 解法 3（★★）：全機放寬非特權埠下限（影響所有程序，要寫進基準文件）
# sysctl -w net.ipv4.ip_unprivileged_port_start=80
```

一份平衡的沙箱起手式（貼上去、逐項驗證、壞了再放寬）：

```ini
[Service]
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
ProtectProc=invisible
ProcSubset=pid
RestrictSUIDSGID=yes
RestrictRealtime=yes
RestrictNamespaces=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
LockPersonality=yes
MemoryDenyWriteExecute=yes          # ★★ 用 JIT 的程式（PHP JIT、Node 的 V8）可能要關掉
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
SystemCallArchitectures=native
CapabilityBoundingSet=
AmbientCapabilities=
UMask=0027
```

> [!warning] ★★★ `MemoryDenyWriteExecute=yes` 會打死 JIT
> Node.js（V8）與開了 JIT 的 PHP 8 需要可寫又可執行的記憶體頁。加了這行的症狀是
> 服務啟動後立刻 `SIGSEGV` 或 `Failed to allocate executable memory`。
> 對這類服務就把它拿掉，其餘沙箱選項照留 —— **不要因為一項不能用就整組放棄**。

### 驗證工具鏈：不啟動、不落檔就先抓錯

```bash
# 1) 語法、未知指令、執行檔存在性、危險設定 —— 不會啟動服務
systemd-analyze verify /etc/systemd/system/laravel-worker@default.service
```

實測輸出（故意寫錯的版本）：

```text
/etc/systemd/system/w.service:7: Special user nobody configured, this is not safe!
w.service: Command /usr/local/bin/nosuchbinary is not executable: No such file or directory
```

★★★★ **template unit 要帶實例名去 verify**（`@default`），
直接 verify `laravel-worker@.service` 時 `%i` 是空的，很多路徑會驗不出問題。

```bash
# 2) 看合併後的檔案內容
systemctl cat laravel-worker@mail.service

# 3) 看「systemd 實際採用的值」——排錯時的最終依據
systemctl show laravel-worker@mail.service \
  -p ExecStart,User,StateDirectory,TimeoutStopUSec,KillMode,ProtectSystem,ReadWritePaths
```

```text
ExecStart={ path=/usr/bin/php ; argv[]=/usr/bin/php artisan queue:work --queue=mail ... }
User=laravel
StateDirectory=laravel/laravel-worker
TimeoutStopUSec=6min
KillMode=mixed
ProtectSystem=strict
ReadWritePaths=/srv/www/app-a/storage
```

```bash
# 4) 不落檔試跑：所有 unit 屬性都能用 --property 帶進去
sudo systemd-run --unit=trial-worker --collect \
  --property=User=laravel \
  --property=WorkingDirectory=/srv/www/app-a \
  --property=EnvironmentFile=/etc/laravel/app-a.env \
  --property=ProtectSystem=strict \
  --property=StateDirectory=laravel/trial \
  /usr/bin/php artisan queue:work --queue=mail --once
```

```text
Running as unit: trial-worker.service
```

```bash
journalctl -u trial-worker -n 20 --no-pager
```

```text
8月 28 15:02:11 srv01 php[5120]: [2026-08-28 15:02:11] Processing: App\Jobs\SendMail
8月 28 15:02:12 srv01 php[5120]: [2026-08-28 15:02:12] Processed:  App\Jobs\SendMail
```

`--collect` 讓失敗的暫時 unit 自動清掉，不然它會留在 `systemctl --failed` 裡礙眼。

```bash
# 5) 相依關係到底長怎樣
systemctl list-dependencies --after laravel-worker@mail.service    # 我要等誰
systemctl list-dependencies --before laravel-worker@mail.service   # 誰要等我
systemctl list-dependencies --reverse laravel-worker@mail.service  # 誰 Wants/Requires 我
```

```text
laravel-worker@mail.service
● ├─-.mount
● ├─mysql.service
● ├─network-online.target
● ├─system-laravel\x2dworker.slice
● └─sysinit.target
```

```bash
# 6) 開機慢的元凶
systemd-analyze blame | head -10
systemd-analyze critical-chain
```

### 交付與稽核：讓下一個人接得住

```bash
# ★★★★ 每個服務一個專屬系統帳號，不要共用 www-data，更不要 root
sudo useradd --system --no-create-home --shell /usr/sbin/nologin --home-dir /nonexistent laravel
id laravel
```

```text
uid=996(laravel) gid=996(laravel) groups=996(laravel)
```

```bash
# ★★★★ 機密只走 EnvironmentFile，權限 640 root:<服務帳號>
sudo install -o root -g laravel -m 0640 /dev/null /etc/laravel/app-a.env
sudo tee /etc/laravel/app-a.env >/dev/null <<'ENVEOF'
APP_ENV=production
APP_KEY=base64:REPLACE_ME
DB_CONNECTION=mysql
DB_HOST=127.0.0.1
DB_DATABASE=app_a
DB_USERNAME=app_a
DB_PASSWORD=REPLACE_ME
QUEUE_CONNECTION=redis
ENVEOF
stat -c '%a %U:%G %n' /etc/laravel/app-a.env
```

```text
640 root:laravel /etc/laravel/app-a.env
```

> [!danger] ★★★★★ 用 `Environment=` 放密碼，等同貼在公佈欄
> ```ini
> Environment="DB_PASSWORD=P@ssw0rd"      # ✗
> ```
> ```bash
> systemctl show laravel-worker@mail -p Environment      # 任何一般使用者都能執行
> ```
> ```text
> Environment=DB_PASSWORD=P@ssw0rd
> ```
> **不需要 sudo，不需要讀檔權限。** 而且 unit 檔本身是 `0644`，全機可讀。
> 機密一律用 `EnvironmentFile=`（`systemctl show` 只會顯示檔案路徑），
> 更嚴謹的做法見 [[090-03-03-guide-應用安全-機密管理與金鑰保護]]。

unit 檔的版本控管（配合 [[020-02-03-00-idx-標準化-伺服器建置與標準化]] 與 [[020-02-03-01-svc-標準化-新機建置標準流程]]）：

```bash
# repo 放 /srv/ops/units（root 擁有），部署時用 install 複製到 /etc
sudo install -o root -g root -m 0644 \
  /srv/ops/units/laravel-worker@.service /etc/systemd/system/laravel-worker@.service
sudo systemctl daemon-reload
```

★★★ **不要用 symlink 把 `/etc/systemd/system/x.service` 指到 `/home/...` 或 `/srv/...`** ——
一旦服務開了 `ProtectHome=`，或 repo 目錄權限被改成 deploy 可寫，你就同時失去可靠性與安全性。
**用複製，不用連結。**

交接文件必附的一段：

```bash
{
  echo "=== unit 完整內容（含 drop-in）==="
  systemctl cat laravel-worker@mail.service
  echo "=== 實際生效的關鍵屬性 ==="
  systemctl show laravel-worker@mail.service -p ExecStart,User,TimeoutStopUSec,Restart,StateDirectory
  echo "=== 安全評分 ==="
  systemd-analyze security laravel-worker@mail.service | tail -3
  echo "=== 全機被覆寫的 unit ==="
  systemd-delta --type=extended,overridden
} > /srv/ops/handover/laravel-worker-$(date +%F).txt
```

---

## 完整實戰範例

### 情境

委外開發的 Laravel 系統 `app-a` 部署在 `/srv/www/app-a`，
佇列 worker 目前用 **Supervisor** 管三條 queue（`default` / `mail` / `report`）。
交接時發現：Supervisor 的設定沒納入版控、密碼寫在 `.conf` 裡、
機器重開機後 worker 有時起有時不起。要求改成 **systemd template unit**，
並且要能通過機關的組態稽核。

（Supervisor 本身的設定寫法見 [[130-01-04-03-guide-Laravel-佇列排程與Supervisor]]，
Laravel 的佇列設計見 [[070-03-06-guide-Laravel-佇列排程與事件]]。）

### 步驟 1：盤點現況並留下回滾素材

```bash
sudo supervisorctl status
```

```text
app-a-default:app-a-default_00   RUNNING   pid 1841, uptime 12 days, 3:22:10
app-a-mail:app-a-mail_00         RUNNING   pid 1842, uptime 12 days, 3:22:10
app-a-report:app-a-report_00     RUNNING   pid 1843, uptime 12 days, 3:22:10
```

```bash
# ★★★★ 動手前先備份，這是回滾的唯一依據
sudo mkdir -p /srv/ops/rollback/$(date +%F)
sudo cp -a /etc/supervisor/conf.d/ /srv/ops/rollback/$(date +%F)/
sudo grep -E 'command=|numprocs=|stopwaitsecs=|user=' /etc/supervisor/conf.d/app-a.conf
```

```text
command=php /srv/www/app-a/artisan queue:work --queue=mail --sleep=3 --tries=3 --timeout=300
numprocs=1
user=www-data
stopwaitsecs=3600
```

★★★★ `--timeout=300` 與 `stopwaitsecs=3600` 這兩個數字要抄下來，
它們決定了 systemd 這邊的 `TimeoutStopSec=`。

### 步驟 2：建立系統帳號與目錄

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin --home-dir /nonexistent laravel
sudo chown -R laravel:laravel /srv/www/app-a/storage /srv/www/app-a/bootstrap/cache
sudo find /srv/www/app-a/storage -type d -exec chmod 2750 {} \;
sudo install -d -o root -g root -m 0755 /etc/laravel
id laravel
```

```text
uid=996(laravel) gid=996(laravel) groups=996(laravel)
```

### 步驟 3：EnvironmentFile

```bash
sudo install -o root -g laravel -m 0640 /srv/www/app-a/.env /etc/laravel/app-a.env
sudo sed -i 's/^export //' /etc/laravel/app-a.env       # ★★★ EnvironmentFile 不是 shell，export 會壞掉
stat -c '%a %U:%G' /etc/laravel/app-a.env
```

```text
640 root:laravel
```

### 步驟 4：template unit

```bash
sudo tee /etc/systemd/system/laravel-worker@.service >/dev/null <<'UNITEOF'
[Unit]
Description=Laravel queue worker for app-a (%i)
Documentation=https://ops.example.gov.tw/wiki/app-a
After=network-online.target mysql.service redis-server.service
Wants=network-online.target mysql.service redis-server.service
# 注意：刻意用 Wants= 而非 Requires=，MySQL 維護重啟時 worker 不會被連帶停掉

[Service]
Type=simple
User=laravel
Group=laravel
WorkingDirectory=/srv/www/app-a
EnvironmentFile=/etc/laravel/app-a.env

StateDirectory=laravel/%p
StateDirectoryMode=0750
LogsDirectory=laravel/%p
LogsDirectoryMode=0750
RuntimeDirectory=laravel/%p
RuntimeDirectoryMode=0750

ExecStartPre=/usr/bin/php artisan --version
ExecStart=/usr/bin/php artisan queue:work --queue=%i --sleep=3 --tries=3 --timeout=300 --max-time=3600

# ── 停機語意：對齊 --timeout=300 ──────────────────
TimeoutStartSec=60
TimeoutStopSec=360
KillMode=mixed
KillSignal=SIGTERM

# ── 自動復原（策略細節見 04-服務自動復原與看門狗）──
Restart=on-failure
RestartSec=10s

# ── 沙箱 ────────────────────────────────────────
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/srv/www/app-a/storage /srv/www/app-a/bootstrap/cache
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
ProtectProc=invisible
RestrictSUIDSGID=yes
RestrictRealtime=yes
RestrictNamespaces=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
LockPersonality=yes
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
SystemCallArchitectures=native
CapabilityBoundingSet=
AmbientCapabilities=
UMask=0027

# ── 資源與日誌 ──────────────────────────────────
MemoryMax=512M
TasksMax=64
SyslogIdentifier=lw-%i

[Install]
WantedBy=multi-user.target
DefaultInstance=default
UNITEOF
sudo systemctl daemon-reload
```

> [!note] 為什麼沒有 `MemoryDenyWriteExecute=yes`
> PHP 8 開了 OPcache JIT 時會需要可寫可執行頁。這台若沒開 JIT 可以加，
> 但加之前務必先用 `systemd-run` 試跑一輪（步驟 6）。

### 步驟 5：靜態驗證

```bash
systemd-analyze verify /etc/systemd/system/laravel-worker@default.service
echo "verify rc=$?"
```

```text
verify rc=0
```

```bash
systemd-analyze security --offline=true /etc/systemd/system/laravel-worker@.service | tail -3
```

```text
✗ UMask=                  Files created by service are world-readable by default   0.1
→ Overall exposure level for laravel-worker@.service: 2.6 OK 🙂
```

★★★ 從預設的 `9.2 UNSAFE` 降到 `2.6 OK`，這個數字要寫進交接文件與稽核紀錄。

### 步驟 6：不落檔試跑

```bash
sudo systemd-run --unit=trial-worker --collect \
  --property=User=laravel --property=Group=laravel \
  --property=WorkingDirectory=/srv/www/app-a \
  --property=EnvironmentFile=/etc/laravel/app-a.env \
  --property=ProtectSystem=strict \
  --property=ProtectHome=yes \
  --property=ReadWritePaths=/srv/www/app-a/storage \
  /usr/bin/php artisan queue:work --queue=mail --once --stop-when-empty
sleep 5 && journalctl -u trial-worker -n 20 --no-pager
```

```text
8月 28 15:41:02 srv01 php[6210]: [2026-08-28 15:41:02] Processing: App\Jobs\SendNotification
8月 28 15:41:03 srv01 php[6210]: [2026-08-28 15:41:03] Processed:  App\Jobs\SendNotification
8月 28 15:41:03 srv01 systemd[1]: trial-worker.service: Deactivated successfully.
```

★★★★ **看到 `Processed:` 才代表沙箱沒有擋住任何東西。**
若出現 `Read-only file system` 或 `Permission denied`，回步驟 4 補 `ReadWritePaths=`，不要放寬 `ProtectSystem=`。

### 步驟 7：切換

```bash
set -e
sudo supervisorctl stop app-a-default:* app-a-mail:* app-a-report:*   # 先停舊的，避免兩套同時消費 queue
sudo systemctl enable --now laravel-worker@{default,mail,report}.service
sudo systemctl status 'laravel-worker@*' --no-pager | grep -E 'Active|●'
```

```text
● laravel-worker@default.service - Laravel queue worker for app-a (default)
     Active: active (running) since Fri 2026-08-28 15:52:11 CST; 4s ago
● laravel-worker@mail.service - Laravel queue worker for app-a (mail)
     Active: active (running) since Fri 2026-08-28 15:52:11 CST; 4s ago
● laravel-worker@report.service - Laravel queue worker for app-a (report)
     Active: active (running) since Fri 2026-08-28 15:52:11 CST; 4s ago
```

```bash
# 確認 Supervisor 不會在重開機後把舊的 worker 也拉起來（★★★★ 兩套同時跑 = job 被處理兩次）
sudo sed -i 's/^autostart=true/autostart=false/' /etc/supervisor/conf.d/app-a.conf
sudo supervisorctl reread && sudo supervisorctl update
```

### 步驟 8：pre-check 腳本

這支腳本每次改 unit 後都要跑，也可以掛進 CI：

```bash
sudo tee /usr/local/bin/unit-precheck.sh >/dev/null <<'PRECHECK'
#!/usr/bin/env bash
# unit-precheck.sh —— systemd unit 上線前檢查
# 用法：unit-precheck.sh <unit 名或路徑> [<EnvironmentFile 路徑>]
# 任何一項不過即以非 0 退出，可直接接在部署流程或 CI 之後。
set -euo pipefail

UNIT="${1:?用法: $0 <unit> [envfile]}"
ENVFILE="${2:-}"
THRESHOLD="${THRESHOLD:-6}"
FAIL=0

say()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAIL=1; }

# ── 1. 語法與相依驗證 ────────────────────────────
say "1/6 systemd-analyze verify"
if systemd-analyze verify "$UNIT" 2>&1 | tee /tmp/precheck-verify.$$ | grep -qiE 'not executable|bad unit file|unknown (key|section)|refusing'; then
  bad "verify 發現嚴重問題："; sed 's/^/       /' /tmp/precheck-verify.$$
else
  ok "verify 無致命錯誤"
fi
rm -f /tmp/precheck-verify.$$

# ── 2. 安全評分 ──────────────────────────────────
say "2/6 systemd-analyze security（門檻 ${THRESHOLD}）"
if systemd-analyze security --offline=true --threshold="$THRESHOLD" "$UNIT" >/tmp/precheck-sec.$$ 2>&1; then
  ok "$(tail -1 /tmp/precheck-sec.$$)"
else
  bad "$(tail -1 /tmp/precheck-sec.$$)"
  grep '^✗' /tmp/precheck-sec.$$ | head -8 | sed 's/^/       /'
fi
rm -f /tmp/precheck-sec.$$

# ── 3. ExecStart 只能有一條（drop-in 漏清空的頭號症狀）──
say "3/6 ExecStart 數量"
UNITNAME="$(basename "$UNIT")"
if systemctl cat "$UNITNAME" >/dev/null 2>&1; then
  N=$(systemctl show "$UNITNAME" -p ExecStart --value | grep -c 'path=' || true)
  if [[ "$N" -le 1 ]]; then ok "ExecStart 條數 = $N"; else bad "ExecStart 條數 = $N（drop-in 忘了寫空值清空？）"; fi
else
  ok "unit 尚未安裝，略過（部署後再跑一次）"
fi

# ── 4. EnvironmentFile 權限 ──────────────────────
say "4/6 EnvironmentFile 權限"
if [[ -n "$ENVFILE" ]]; then
  if [[ ! -f "$ENVFILE" ]]; then
    bad "$ENVFILE 不存在"
  else
    MODE=$(stat -c '%a' "$ENVFILE"); OWNER=$(stat -c '%U:%G' "$ENVFILE")
    if [[ "$MODE" == "640" || "$MODE" == "600" ]]; then ok "權限 $MODE"; else bad "權限 $MODE（應為 640 或 600）"; fi
    if [[ "${OWNER%%:*}" == "root" ]]; then ok "擁有者 $OWNER"; else bad "擁有者 $OWNER（應為 root:<服務帳號>）"; fi
    if grep -qE '^\s*export ' "$ENVFILE"; then bad "含有 export（EnvironmentFile 不是 shell 腳本）"; else ok "格式為純 KEY=VALUE"; fi
  fi
else
  ok "未指定 EnvironmentFile，略過"
fi

# ── 5. 不得以 root 執行、不得使用 + 前綴 ─────────
say "5/6 執行身分"
SRC="$UNIT"; [[ -f "$SRC" ]] || SRC="$(systemctl show "$UNITNAME" -p FragmentPath --value)"
if grep -qE '^\s*User\s*=' "$SRC"; then ok "有指定 User="; else bad "沒有 User=，將以 root 執行"; fi
if grep -qE '^\s*Exec[A-Za-z]*\s*=\s*\+' "$SRC"; then
  bad "使用了 + 前綴（該行以 root 執行並跳過沙箱），請確認腳本為 root:root 0755"
else
  ok "未使用 + 前綴"
fi

# ── 6. 相依關係 ──────────────────────────────────
say "6/6 開機時序"
if grep -q 'network-online.target' "$SRC"; then
  if grep -qE '^\s*Wants\s*=.*network-online' "$SRC"; then
    ok "After= 與 Wants= network-online.target 都有"
  else
    bad "只有 After=network-online.target，缺 Wants=（該 target 不會被拉起）"
  fi
  for W in systemd-networkd-wait-online.service NetworkManager-wait-online.service; do
    if systemctl is-enabled "$W" >/dev/null 2>&1; then ok "$W 已 enable"; fi
  done
else
  ok "未使用 network-online.target"
fi

echo
if [[ "$FAIL" -eq 0 ]]; then
  printf '\033[32m全部通過\033[0m\n'; exit 0
else
  printf '\033[31m有項目未通過，請修正後再部署\033[0m\n'; exit 1
fi
PRECHECK
sudo chmod 0755 /usr/local/bin/unit-precheck.sh
sudo chown root:root /usr/local/bin/unit-precheck.sh
```

執行：

```bash
sudo /usr/local/bin/unit-precheck.sh \
  /etc/systemd/system/laravel-worker@default.service /etc/laravel/app-a.env
```

```text
== 1/6 systemd-analyze verify ==
  PASS verify 無致命錯誤

== 2/6 systemd-analyze security（門檻 6）==
  PASS → Overall exposure level for laravel-worker@default.service: 2.6 OK 🙂

== 3/6 ExecStart 數量 ==
  PASS ExecStart 條數 = 1

== 4/6 EnvironmentFile 權限 ==
  PASS 權限 640
  PASS 擁有者 root:laravel
  PASS 格式為純 KEY=VALUE

== 5/6 執行身分 ==
  PASS 有指定 User=
  PASS 未使用 + 前綴

== 6/6 開機時序 ==
  PASS After= 與 Wants= network-online.target 都有
  PASS systemd-networkd-wait-online.service 已 enable

全部通過
```

### 步驟 9：驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | unit 語法無誤 | `systemd-analyze verify /etc/systemd/system/laravel-worker@default.service` | 無輸出、`rc=0` | ★★★★ |
| 2 | 合併後只有一條 ExecStart | `systemctl show laravel-worker@mail -p ExecStart \| grep -c path=` | `1` | ★★★★ |
| 3 | 三個實例都在跑 | `systemctl is-active laravel-worker@{default,mail,report}` | 三個 `active` | ★★★ |
| 4 | ★★★★ 三個實例都 **enable** | `ls /etc/systemd/system/multi-user.target.wants/ \| grep -c laravel-worker@` | `3` | ★★★★ |
| 5 | 重開機後仍是三個 | `sudo reboot`，起來後跑第 3、4 項 | 三個 `active` | ★★★★ |
| 6 | 沙箱沒擋住寫入 | `journalctl -u 'laravel-worker@*' -b \| grep -ciE 'read-only\|permission denied'` | `0` | ★★★★ |
| 7 | 安全評分達標 | `systemd-analyze security laravel-worker@mail \| tail -1` | `< 6.0` | ★★★ |
| 8 | kill -9 後會自己回來 | `sudo kill -9 $(systemctl show laravel-worker@mail -p MainPID --value)`；10 秒後看狀態 | `active (running)`，PID 已變 | ★★★ |
| 9 | ★★★★ restart 不砍進行中的 job | 丟一個 60 秒的 job，`systemctl restart laravel-worker@report`，看 job 是否完成 | job 正常結束，無 `SIGKILL` 字樣 | ★★★★ |
| 10 | 機密不外洩 | `systemctl show laravel-worker@mail -p Environment`（用一般帳號執行） | 只有非機密變數，看不到 `DB_PASSWORD` | ★★★★★ |
| 11 | Supervisor 不會搶 | `sudo supervisorctl status` | 三個都 `STOPPED`，且 `autostart=false` | ★★★★ |
| 12 | 交接文件已產出 | `ls -l /srv/ops/handover/` | 有當日的 `systemctl cat` 輸出 | ★★ |

第 9 項的實際驗證方式：

```bash
# 丟一個會跑 60 秒的測試 job
sudo -u laravel php /srv/www/app-a/artisan tinker --execute='dispatch(new \App\Jobs\SlowTest())->onQueue("report");'
sleep 3
sudo systemctl restart laravel-worker@report
journalctl -u laravel-worker@report -n 15 --no-pager | grep -E 'Processed|SIGKILL|timed out'
```

```text
8月 28 16:10:44 srv01 php[7331]: [2026-08-28 16:10:44] Processed:  App\Jobs\SlowTest    # ★★★★ 沒有 SIGKILL
```

### 回滾腳本

```bash
sudo tee /usr/local/sbin/laravel-worker-rollback.sh >/dev/null <<'ROLLBACK'
#!/usr/bin/env bash
# 把 app-a 的 queue worker 從 systemd 退回 Supervisor
set -euo pipefail
BACKUP="${1:?用法: $0 /srv/ops/rollback/<日期>}"
INSTANCES=(default mail report)

echo "== 1. 停用並移除 systemd 實例 =="
for i in "${INSTANCES[@]}"; do
  systemctl disable --now "laravel-worker@${i}.service" 2>/dev/null || true
  echo "  laravel-worker@${i}: $(systemctl is-enabled "laravel-worker@${i}" 2>&1 || true)"
done

echo "== 2. 清掉可能存在的 drop-in 覆寫 =="
systemctl revert 'laravel-worker@.service' 2>/dev/null || true
rm -f /etc/systemd/system/laravel-worker@.service
systemctl daemon-reload
systemctl reset-failed 'laravel-worker@*' 2>/dev/null || true

echo "== 3. 還原 Supervisor 設定 =="
[[ -d "$BACKUP/conf.d" ]] || { echo "找不到備份 $BACKUP/conf.d"; exit 1; }
cp -a "$BACKUP/conf.d/." /etc/supervisor/conf.d/
supervisorctl reread
supervisorctl update
supervisorctl start 'app-a-default:*' 'app-a-mail:*' 'app-a-report:*'

echo "== 4. 驗證 =="
supervisorctl status | grep app-a
if systemctl list-units 'laravel-worker@*' --no-legend | grep -q .; then
  echo "★★★ 仍有殘留的 systemd 實例，請人工確認"; exit 1
fi
echo "回滾完成"
ROLLBACK
sudo chmod 0755 /usr/local/sbin/laravel-worker-rollback.sh
```

```bash
sudo /usr/local/sbin/laravel-worker-rollback.sh /srv/ops/rollback/2026-08-28
```

```text
== 1. 停用並移除 systemd 實例 ==
Removed '/etc/systemd/system/multi-user.target.wants/laravel-worker@default.service'.
  laravel-worker@default: disabled
...
== 4. 驗證 ==
app-a-default:app-a-default_00   RUNNING   pid 8102, uptime 0:00:03
回滾完成
```

★★★ 回滾腳本要跟 unit 檔一起進 git，並且**在正式切換前先在測試機跑過一次**。
沒演練過的回滾等於沒有回滾（見 [[080-03-04-guide-發布-上線檢查表與回退計畫]]）。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ 重開機後服務 failed，手動 `start` 就正常 | 只寫 `After=X` 沒寫 `Wants=X`／`Requires=X`，開機時 X 根本沒被拉起 | `[Unit]` 同時加 `Wants=X` 與 `After=X`；用 `systemctl list-dependencies --after <unit>` 確認 |
| ★★★★ 開機日誌 `Cannot assign requested address` / `Temporary failure in name resolution` | 用了 `network.target` 或漏了 `Wants=network-online.target`，也可能是 wait-online 服務沒 enable | `After=` + `Wants=network-online.target`；`systemctl enable systemd-networkd-wait-online.service`（NM 環境則是 `NetworkManager-wait-online.service`） |
| ★★★★ 資料「消失」：服務寫的檔案在 NFS 上找不到 | 掛載尚未完成服務就啟動，寫進被掛載點蓋住的本機空目錄 | `RequiresMountsFor=/srv/share/uploads`；fstab 加 `_netdev,x-systemd.automount`；改完 fstab 跑 `daemon-reload` |
| ★★★★ 第一次上線正常，重開機後永遠起不來，錯誤是 PID／socket 檔寫不出來 | 手動在 `/run` 底下 `mkdir`，而 `/run` 是 tmpfs，開機即清空 | 改用 `RuntimeDirectory=<name>`（＋`RuntimeDirectoryMode=`），不要自己建 |
| ★★★★ drop-in 之後服務起不來，`Loaded: bad-setting` | `ExecStart=` 是 list 型，drop-in 沒先寫空值清空，變成兩條 | drop-in 內先寫 `ExecStart=` 空行再寫新值；用 `systemctl show -p ExecStart \| grep -c path=` 確認只有 1 |
| ★★★★ 重開機後只有一條 queue 在跑，其他靜默堆積 | template unit 只 `enable` 了一個實例，其他只是 `start` 過 | `systemctl enable --now app@{a,b,c}.service`；驗收查 `multi-user.target.wants/` 底下的連結數 |
| ★★★★ `systemctl stop` 卡 90 秒後出現 `Killing process ... with signal SIGKILL` | 程式不理 SIGTERM（PHP 缺 pcntl、Node 沒註冊 handler），或 `sh -c` 沒 `exec` 導致訊號只到 shell | 應用端註冊 SIGTERM handler；`ExecStart=` 直接指執行檔或用 `exec`；`TimeoutStopSec=` 調到大於最長工作時間 |
| ★★★★ 部署 `restart` 後有交易寫到一半、檔案只產出一半 | `TimeoutStopSec=` 小於單筆工作耗時，工作被 SIGKILL 中斷 | `TimeoutStopSec ≥ job timeout + 30s`；`KillMode=mixed` 讓主程序自己收子程序 |
| ★★★★ 服務啟動即 `Read-only file system` 或 `Permission denied` | `ProtectSystem=strict` / `ProtectHome=yes` / `PrivateTmp=yes` 擋住了它要寫的路徑 | 用 `StateDirectory=`／`LogsDirectory=`／`ReadWritePaths=` 明確開放，**不要**把 `ProtectSystem=` 關掉 |
| ★★★★★ 一般使用者 `systemctl show -p Environment` 就看得到資料庫密碼 | 機密寫在 `Environment=`，而該屬性任何人可讀 | 全部移到 `EnvironmentFile=`，檔案 `640 root:<服務帳號>`；輪替已外洩的密碼 |
| ★★★ 改了 unit 檔卻沒生效，行為還是舊的 | 忘記 `systemctl daemon-reload`（手動編檔案時不會自動 reload） | `daemon-reload` → `restart`；出現 `changed on disk` 警告就是它 |
| ★★★ 上游服務重啟，下游一票服務被一起停掉且沒回來 | 誤用 `Requires=`，停止會沿著相依鏈傳播 | 改成 `Wants=` + `After=`，讓應用自己重試連線；真的需要連動才用 `PartOf=`／`BindsTo=` |
| ★★★ `Type=oneshot` 的服務跑完後，`Requires=` 它的服務立刻失敗 | 沒有 `RemainAfterExit=yes`，跑完變 `inactive`，被視為未滿足 | 環境設定型的 oneshot 加 `RemainAfterExit=yes`（正常狀態是 `active (exited)`） |
| ★★★ 綁 80／443 時 `Permission denied`，但用 root 跑就好 | `CapabilityBoundingSet=` 清空後失去 `CAP_NET_BIND_SERVICE` | 加 `AmbientCapabilities=CAP_NET_BIND_SERVICE`；或改聽高埠由 Nginx 反向代理 |
| ★★★ Node／PHP JIT 服務加了沙箱後立刻 `SIGSEGV` | `MemoryDenyWriteExecute=yes` 擋掉 JIT 需要的可寫可執行頁 | 移除該行，保留其餘沙箱選項 |
| ★★ `systemctl reload` 回報 `Job type reload is not applicable` | unit 沒有 `ExecReload=` | 補 `ExecReload=/bin/kill -HUP $MAINPID`，或改用 `reload-or-restart` |

### 排查步驟

服務「起不來」或「行為不如預期」時，照這個順序走，不要跳步。

**【1】先看 systemd 怎麼判定，而不是先看應用日誌**

```bash
systemctl status laravel-worker@mail --no-pager -l
```

```text
     Active: failed (Result: exit-code) since Fri 2026-08-28 16:22:03 CST; 12s ago
    Process: 8412 ExecStartPre=/usr/bin/php artisan --version (code=exited, status=255/EXCEPTION)
```

- `Process: ExecStartPre=...` 非 0 → **問題在啟動前置步驟**，跳到【3】
- `Main PID: ... (code=exited, status=1/FAILURE)` → 應用自己退出，跳到【4】
- `Result: timeout` → 啟動或停止逾時，跳到【6】
- `Loaded: bad-setting` 或 `Loaded: error` → **unit 檔本身有問題**，跳到【2】

**【2】unit 檔語法與生效值**

```bash
systemd-analyze verify /etc/systemd/system/laravel-worker@default.service
```

看到 `Unknown key ...` → 打錯字或該版本 systemd 不支援（對照本篇的版本註記）。
看到 `more than one ExecStart=` → drop-in 沒清空，跳到【7】。

```bash
systemctl show laravel-worker@mail -p ExecStart,User,WorkingDirectory,ProtectSystem
```

★★★★ **`show` 的輸出才是 systemd 真正在用的值。**
如果這裡的 `ExecStart` 和你以為的不同，就代表有 drop-in 在作怪。

**【3】前置步驟失敗：手動用同一個身分跑一次**

```bash
sudo -u laravel env $(grep -v '^#' /etc/laravel/app-a.env | xargs) \
  /usr/bin/php /srv/www/app-a/artisan --version
```

```text
Laravel Framework 11.9.2
```

手動跑得起來、systemd 跑不起來 → **差別在沙箱或環境變數**，跳到【5】。
手動也跑不起來 → 是應用／相依套件問題，與 systemd 無關。

**【4】應用退出：拿完整日誌，注意時間對齊**

```bash
sudo journalctl -u laravel-worker@mail -b --no-pager | tail -40
sudo journalctl -t lw-mail --since "10 min ago" --no-pager
```

`SyslogIdentifier=` 設對的話，`-t` 過濾比 `-u` 更乾淨（日誌設計見 [[020-01-19-guide-Linux-日誌系統]]）。

**【5】沙箱擋住了什麼**

```bash
sudo journalctl -u laravel-worker@mail -b | grep -iE 'read-only|permission denied|operation not permitted|no such file'
```

```text
8月 28 16:22:01 srv01 php[8420]: file_put_contents(/srv/www/app-a/storage/logs/laravel.log): Read-only file system
```

看到 `Read-only file system` → `ProtectSystem=` 擋的，把路徑加進 `ReadWritePaths=`。
看到 `Operation not permitted` 而路徑正常 → 多半是 `SystemCallFilter=` 或 capability。
用二分法確認到底是哪一項：

```bash
# 先整組拿掉沙箱試跑，能跑就代表確實是沙箱問題，再逐項加回來
sudo systemd-run --unit=nosandbox --collect \
  --property=User=laravel --property=WorkingDirectory=/srv/www/app-a \
  --property=EnvironmentFile=/etc/laravel/app-a.env \
  /usr/bin/php artisan queue:work --queue=mail --once
```

**【6】逾時：分清楚是啟動逾時還是停止逾時**

```bash
systemctl show laravel-worker@mail -p TimeoutStartUSec,TimeoutStopUSec,KillMode
```

```text
TimeoutStartUSec=1min
TimeoutStopUSec=6min
KillMode=mixed
```

```bash
sudo journalctl -u laravel-worker@mail -b | grep -E "timed out|Killing"
```

```text
laravel-worker@mail.service: State 'stop-sigterm' timed out. Killing.
```

`start-...` timed out → 應用起太慢或 `Type=notify` 卻沒送 `READY=1`。
`stop-sigterm` timed out → 程式不理 SIGTERM，回頭看「停機語意」那一節的三種成因。

**【7】drop-in 在哪、誰覆寫了什麼**

```bash
systemctl cat laravel-worker@mail | grep '^# /'
```

```text
# /etc/systemd/system/laravel-worker@.service
# /etc/systemd/system/laravel-worker@.service.d/90-hardening.conf
# /etc/systemd/system/laravel-worker@mail.service.d/override.conf     # ★★★ 只針對 mail 實例的覆寫
```

★★★ **template 的 drop-in 可以同時存在兩層**：`app@.service.d/`（所有實例）與
`app@mail.service.d/`（只有這個實例）。找不到設定從哪來時，先看這裡。

```bash
systemd-delta --type=extended,overridden     # 全機盤點
sudo systemctl revert laravel-worker@mail    # 確定要清掉時
```

**【8】開機時序：把整條鏈攤開**

```bash
systemd-analyze critical-chain laravel-worker@mail.service
```

```text
laravel-worker@mail.service +412ms
└─mysql.service @6.201s +1.994s
  └─network-online.target @6.180s
    └─systemd-networkd-wait-online.service @2.109s +4.070s
      └─systemd-networkd.service @1.882s +215ms
```

★★ `@` 是「這個 unit 開始啟動的時間點」，`+` 是「它花了多久」。
`systemd-networkd-wait-online` 佔了 4 秒 → 多半是在等一張沒插線的網卡，
回去看「network-online.target」那一節的坑一。

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對不要用 `+` 前綴或 `User=root` 執行「別人可寫」的腳本
> ```ini
> ExecStartPre=+/srv/www/app/deploy/pre-start.sh
> ```
> `/srv/www/app/` 會被 CI、deploy key、廠商帳號覆寫。
> 任何能寫入那支腳本的人，只要等下一次 `systemctl restart`，
> 就取得 **root shell**、拿走 `/etc/shadow`、裝上持久化後門。
> 這在機關環境是委外廠商權限失控的典型路徑。
>
> 硬規則：
> 1. `+` 前綴指到的檔案必須 `root:root 0755`，且**路徑上每一層目錄**都不可被他人寫入（用 `namei -l` 逐層檢查）
> 2. 需要 root 但不需要跳過沙箱時用 `!` 而不是 `+`
> 3. 更好的做法是拆成兩個 unit，用 `Wants=`／`After=` 串起來，各自跑各自的身分

> [!danger] ★★★★★ 機密不可以出現在 `Environment=`、unit 檔或指令列參數
> ```bash
> systemctl show <unit> -p Environment      # 任何使用者，不需 sudo
> ps aux | grep myapp                        # 指令列參數全機可見
> ```
> 兩者都會把密碼、API token 原封不動印出來，而且會被監控系統與
> `journalctl` 一起蒐走，形成長期保存的外洩。個資法下這屬於「未採取適當安全措施」。
>
> 正確：`EnvironmentFile=/etc/<app>/app.env`，`640 root:<服務帳號>`，
> 再進一步用 systemd credentials 或外部秘密管理（[[090-03-03-guide-應用安全-機密管理與金鑰保護]]）。

> [!danger] ★★★★ 不要為了讓服務跑起來而把沙箱關掉
> 稽核時最常見的「臨時處置變成永久設定」：
> ```ini
> ProtectSystem=no
> NoNewPrivileges=no
> User=root
> ```
> 每一行都是把一個「應用層漏洞」升級成「整機淪陷」的開關。
> 遇到權限問題的正解永遠是**明確開放最小範圍**（`ReadWritePaths=`、`StateDirectory=`、
> 單一 `AmbientCapabilities=`），不是拆掉圍籬。
> 上線前用 `systemd-analyze security --threshold=6` 把關，分數與改善紀錄一起進交接文件。

> [!warning] ★★★★ 最小權限：一個服務一個帳號
> 把三個委外系統都掛在 `www-data` 底下，等於任一系統被打穿就拿到全部三套的檔案與
> 資料庫憑證。
> ```bash
> sudo useradd --system --no-create-home --shell /usr/sbin/nologin app-a
> sudo useradd --system --no-create-home --shell /usr/sbin/nologin app-b
> ```
> `--shell /usr/sbin/nologin`（RHEL 是 `/sbin/nologin`）避免帳號被拿來互動登入，
> `--no-create-home` 避免多出一個沒人管的家目錄。

> [!warning] ★★★ 稽核軌跡：unit 的每一次變更都要留痕
> 機關組態稽核會問「這個服務是誰、什麼時候、為什麼改成這樣」。
> - unit 檔與 drop-in 全部納入 git，commit 訊息寫變更單號
> - `systemd-delta --type=extended,overridden` 的輸出納入每月巡檢紀錄
> - 交接時附 `systemctl cat` 與 `systemd-analyze security` 的當日輸出
> - `journalctl` 保留期要涵蓋稽核週期（見 [[020-01-19-guide-Linux-日誌系統]]、[[090-02-08-guide-防護-系統強化與稽核]]）

> [!tip] ★★★ 不要讓 systemd 幫你把危險的東西自動重啟
> `Restart=always` 加在一個「設定檔錯誤就退出」的服務上，會讓它每 100 毫秒重啟一次，
> 把 journal 灌爆、把 CPU 吃滿，並且掩蓋真正的錯誤。
> 策略與 `StartLimitBurst=` 的設計見 [[020-02-02-04-svc-systemd-服務自動復原與看門狗]]。

---

## 速查表

### 相依關係

| 寫法 | 效果 | 星級 |
| --- | --- | --- |
| `Wants=X` + `After=X` | ★★★★ **預設就用這組**：幫忙拉起 X、排在它後面、X 掛了我照樣跑 | ★★★★ |
| `Requires=X` + `After=X` | X 失敗我也失敗、X 停我也停 | ★★★ |
| `BindsTo=X` + `After=X` | 比 Requires 更強，X 消失（含裝置拔除）我立刻停 | ★★ |
| `Requisite=X` | 不幫忙啟動，X 當下沒在跑就立刻判我失敗 | ★★ |
| `PartOf=X` | X `restart`／`stop` 時我跟著（單向） | ★★ |
| `RequiresMountsFor=/path` | 自動加對應 `.mount` 的 `Requires=` + `After=` | ★★★★ |
| `Conflicts=X` | 我啟動時 X 會被停掉 | ★★ |

### 開機時序關鍵字

| 目標／服務 | 語意 | 星級 |
| --- | --- | --- |
| `network.target` | 網路子系統起來了，**不保證有 IP** | ★★ |
| `network-online.target` | 網路真的可用（必須 `After=` + `Wants=` 一起寫） | ★★★★ |
| `systemd-networkd-wait-online.service` | netplan／networkd 環境的等待器，要 enable | ★★★★ |
| `NetworkManager-wait-online.service` | NM 環境的等待器 | ★★★ |
| `nss-lookup.target` | DNS 解析可用 | ★★ |
| `remote-fs.target` | 網路檔案系統掛好 | ★★★ |
| `local-fs.target` | 本機檔案系統掛好 | ★★ |
| `time-sync.target` | 時間同步完成（見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]]） | ★★ |

### 目錄委派

| 指令 | 路徑 | stop 時刪 | 星級 |
| --- | --- | --- | --- |
| `RuntimeDirectory=x` | `/run/x` | ★★★★ **會** | ★★★★ |
| `StateDirectory=x` | `/var/lib/x` | 不會 | ★★★ |
| `LogsDirectory=x` | `/var/log/x` | 不會 | ★★★ |
| `CacheDirectory=x` | `/var/cache/x` | 不會 | ★★ |
| `ConfigurationDirectory=x` | `/etc/x`（維持 root 擁有） | 不會 | ★★ |

### Specifier

| `%i` 實例名 | `%I` 還原跳脫的實例名 | `%p` prefix | `%n` 完整 unit 名 |
| --- | --- | --- | --- |
| `%N` 去副檔名 | `%t` `/run` | `%S` `/var/lib` | `%L` `/var/log` |
| `%C` `/var/cache` | `%E` `/etc` | `%H` 主機名 | `%u` `User=` 的名字 |

### 排錯指令

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `systemd-analyze verify <file>` | ★★★★ 不啟動就抓語法／執行檔／相依錯誤 | ★★★★ |
| `systemctl show <u> -p <屬性>` | ★★★★ 看 systemd**實際採用**的值（最終仲裁） | ★★★★ |
| `systemctl cat <u>` | 看合併後的檔案內容與來源檔路徑 | ★★★★ |
| `systemd-analyze security <u>` | 安全評分，`--offline=true` 可掃未安裝的檔案 | ★★★ |
| `systemd-run --unit=t --property=... cmd` | 不落檔試跑，`--collect` 自動清理 | ★★★★ |
| `systemctl list-dependencies --after <u>` | 我在等誰 | ★★★ |
| `systemd-analyze critical-chain <u>` | 開機時序與各段耗時 | ★★★ |
| `systemd-delta --type=extended,overridden` | 全機盤點被覆寫的 unit | ★★★ |
| `systemd-escape -p --suffix=mount <path>` | 算出 mount unit 名稱 | ★★ |
| `systemd-analyze exit-status <n>` | 查退出碼代號 | ★★ |
| `systemctl revert <u>` | 刪掉所有 drop-in 與 `--full` 複本 | ★★★ |

### 停機語意

| 設定 | 預設 | 什麼時候要改 | 星級 |
| --- | --- | --- | --- |
| `TimeoutStopSec=` | 90s | ★★★★ 單筆工作可能超過 90 秒時 | ★★★★ |
| `TimeoutStartSec=` | 90s | 啟動要做遷移、預熱快取時 | ★★★ |
| `KillMode=control-group` | 預設 | 大多數情況維持不動 | ★★★ |
| `KillMode=mixed` | — | 主程序會自己優雅收掉子程序（Nginx、PHP-FPM、queue worker） | ★★★ |
| `SendSIGKILL=no` | `yes` | ★★★ 幾乎不要設，會卡在 `deactivating` | ★★★ |

---

## 練習題

> [!question]- 練習 1：把「只寫 After」的事故重現並修好
> 在測試機上建立兩個 unit：`lab-cache.service`（`Type=simple`，`ExecStart=/bin/sleep infinity`，
> **不要 enable**）與 `lab-app.service`（`ExecStartPre=/bin/systemctl is-active lab-cache`，
> `ExecStart=/bin/sleep infinity`，`[Unit]` 只寫 `After=lab-cache.service`，並且 enable）。
> 重開機後觀察 `lab-app` 的狀態，再把它修好。
>
> **參考解答**
>
> ```bash
> sudo tee /etc/systemd/system/lab-cache.service >/dev/null <<'EOF'
> [Unit]
> Description=Lab cache
> [Service]
> Type=simple
> ExecStart=/bin/sleep infinity
> [Install]
> WantedBy=multi-user.target
> EOF
> sudo tee /etc/systemd/system/lab-app.service >/dev/null <<'EOF'
> [Unit]
> Description=Lab app
> After=lab-cache.service
> [Service]
> Type=simple
> ExecStartPre=/bin/systemctl is-active lab-cache.service
> ExecStart=/bin/sleep infinity
> [Install]
> WantedBy=multi-user.target
> EOF
> sudo systemctl daemon-reload
> sudo systemctl enable lab-app        # 只 enable app，不 enable cache
> sudo reboot
> ```
>
> 重開機後：
> ```text
> ● lab-app.service - Lab app
>      Active: failed (Result: exit-code)
>     Process: 901 ExecStartPre=/bin/systemctl is-active lab-cache.service (code=exited, status=3)
> ```
> `systemctl start lab-app` 卻會成功嗎？不一定 —— 除非你先手動起了 cache。
> 這正是「手動就好、開機就壞」的原型。
>
> **修法**：在 `lab-app.service` 的 `[Unit]` 加一行 `Wants=lab-cache.service`，
> 或者把 `lab-cache` 也 `enable`。前者更好，因為相依關係寫在需要它的那一方，
> 交接時看 unit 檔就懂。
> ```bash
> sudo systemctl edit lab-app
> ```
> ```ini
> [Unit]
> Wants=lab-cache.service
> ```
> ```bash
> sudo systemctl daemon-reload && sudo reboot
> systemctl is-active lab-app lab-cache      # 兩個都是 active
> ```

> [!question]- 練習 2：製造並診斷「兩條 ExecStart」
> 對系統上任一個 `Type=simple` 的服務做 drop-in，故意不清空 `ExecStart=`，
> 觀察 `daemon-reload` 與 `systemctl cat` 的差異，再修好它。
>
> **參考解答**
>
> ```bash
> sudo systemctl edit --drop-in=99-lab.conf cron
> ```
> ```ini
> [Service]
> ExecStart=/usr/sbin/cron -f -L 2
> ```
> ```bash
> sudo systemctl daemon-reload
> systemctl status cron | head -3
> ```
> ```text
> ● cron.service - Regular background program processing daemon
>      Loaded: bad-setting (Reason: Unit cron.service has a bad unit file setting.)
> ```
>
> ★★★★ 關鍵觀察：`systemctl cat cron` 看起來完全正常（就是兩段檔案接在一起），
> **肉眼很難發現有兩條 `ExecStart=`**。真正能一眼看出來的是：
> ```bash
> systemctl show cron -p ExecStart | grep -c 'path='
> ```
> ```text
> 2
> ```
> 或直接：
> ```bash
> systemd-analyze verify cron.service
> ```
> ```text
> cron.service: Service has more than one ExecStart= setting, which is only allowed for Type=oneshot services. Refusing.
> ```
>
> **修法**：在 drop-in 的 `ExecStart=` 之前補一行空值。
> ```ini
> [Service]
> ExecStart=
> ExecStart=/usr/sbin/cron -f -L 2
> ```
> 復原：`sudo rm /etc/systemd/system/cron.service.d/99-lab.conf && sudo systemctl daemon-reload`
> 或 `sudo systemctl revert cron`。

> [!question]- 練習 3：把一個 oneshot 腳本包成有沙箱、有目錄委派的 unit
> 寫一支每次執行都要（1）讀 `/etc/labcollect/labcollect.env`、（2）把結果寫進
> `/var/lib/labcollect/`、（3）在 `/run/labcollect/` 放一個 lock 檔的腳本，
> 包成 `labcollect.service`，要求 `systemd-analyze security` 低於 4.0，
> 且不得手動 `mkdir` 任何目錄。
>
> **參考解答**
>
> ```bash
> sudo useradd --system --no-create-home --shell /usr/sbin/nologin labcollect
> sudo install -o root -g root -m 0755 /dev/stdin /usr/local/bin/labcollect.sh <<'EOF'
> #!/usr/bin/env bash
> set -euo pipefail
> : "${STATE_DIRECTORY:?systemd 應提供}"
> : "${RUNTIME_DIRECTORY:?systemd 應提供}"
> LOCK="$RUNTIME_DIRECTORY/labcollect.lock"
> exec 9>"$LOCK"
> flock -n 9 || { echo "已有另一份在跑"; exit 75; }
> date -Is > "$STATE_DIRECTORY/last-run"
> echo "collected ${TARGET_HOSTS:-none}" >> "$STATE_DIRECTORY/result.log"
> EOF
> sudo install -o root -g labcollect -m 0640 /dev/stdin /etc/labcollect/labcollect.env <<'EOF'
> TARGET_HOSTS=10.20.30.0/24
> EOF
> ```
> （`/etc/labcollect` 由 `ConfigurationDirectory=` 建立，第一次可先手動 `install -d`。）
>
> ```ini
> # /etc/systemd/system/labcollect.service
> [Unit]
> Description=Lab collector (oneshot)
>
> [Service]
> Type=oneshot
> RemainAfterExit=no
> User=labcollect
> Group=labcollect
> EnvironmentFile=/etc/labcollect/labcollect.env
> RuntimeDirectory=labcollect
> RuntimeDirectoryMode=0750
> StateDirectory=labcollect
> StateDirectoryMode=0750
> ConfigurationDirectory=labcollect
> ExecStart=/usr/local/bin/labcollect.sh
> SuccessExitStatus=75
> NoNewPrivileges=yes
> ProtectSystem=strict
> ProtectHome=yes
> PrivateTmp=yes
> PrivateDevices=yes
> ProtectKernelTunables=yes
> ProtectKernelModules=yes
> ProtectControlGroups=yes
> ProtectProc=invisible
> RestrictNamespaces=yes
> RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
> LockPersonality=yes
> MemoryDenyWriteExecute=yes
> SystemCallFilter=@system-service
> SystemCallArchitectures=native
> CapabilityBoundingSet=
> AmbientCapabilities=
> UMask=0027
> ```
>
> ```bash
> sudo systemctl daemon-reload
> systemd-analyze verify /etc/systemd/system/labcollect.service
> sudo systemctl start labcollect
> systemctl status labcollect | head -4
> systemd-analyze security labcollect.service | tail -1
> ```
> ```text
> → Overall exposure level for labcollect.service: 1.9 OK 🙂
> ```
> ★★★ 重點：`SuccessExitStatus=75` 讓「已有另一份在跑」不算失敗（不會觸發告警）；
> `RemainAfterExit=no` 是給 timer 用的形狀（[[020-02-02-02-cmd-systemd-timer與cron選型]]）。

---

## 小測驗

Q1. 一個服務的 `[Unit]` 只寫了 `After=redis-server.service`。開機後它 `failed`，
但你 SSH 上去 `systemctl start` 就正常。最可能的原因是什麼？要加哪一行？

Q2. 是非題：`After=network-online.target` 這一行就足以保證服務啟動時網卡已經拿到 IP。

Q3. 下面這個 drop-in 會發生什麼事？服務是 `Type=simple`。
```ini
[Service]
ExecStart=/usr/local/bin/myapp --new-flag
```

Q4. `systemctl stop myapp` 卡了 90 秒，日誌出現
`State 'stop-sigterm' timed out. Killing.`。列出三個可能成因，以及各自的驗證指令。

Q5. 選擇題：服務需要在 `/run/myapp/` 放 unix socket，下列哪個做法在重開機後仍然可靠？
（A）`ExecStartPre=/bin/mkdir -p /run/myapp`
（B）`RuntimeDirectory=myapp`
（C）安裝時 `mkdir -p /run/myapp && chown myapp: /run/myapp`
（D）在 `/etc/rc.local` 建目錄

Q6. `laravel-worker@.service` 這個 template，你執行了
`systemctl start laravel-worker@{default,mail,report}`，三個都 active。
上線一週後重開機，只有 default 回來。原因是什麼？用哪一行指令可以在上線前就發現？

Q7. 這行設定為什麼是資安事故？
```ini
User=laravel
ExecStartPre=+/srv/www/app-a/scripts/pre-start.sh
```

Q8. 服務加了 `ProtectSystem=strict` 之後日誌出現
`file_put_contents(/var/lib/myapp/cache/x): Read-only file system`。
下列哪個是正解，為什麼其他不是？
（A）`ProtectSystem=no`（B）`ProtectSystem=full`（C）`StateDirectory=myapp`（D）`User=root`

Q9. `Type=simple`、`Type=exec`、`Type=notify` 三者在「啟動失敗偵測」上的差別是什麼？
你的 Nuxt SSR 服務前面有 Nginx 反向代理，應該選哪一個，為什麼？

Q10. 一個用 timer 觸發、每晚跑一次的匯入服務，`Type=oneshot`。
`RemainAfterExit=` 應該設 `yes` 還是 `no`？
如果換成「開機時建立網路 bridge」的一次性服務呢？

> [!question]- 測驗答案
> **Q1.** ★★★★ 原因是 **`After=` 只管順序、不管「有沒有人要啟動對方」**。
> 如果 `redis-server` 本身沒有被 enable，或它的啟動被別的相依鏈延後，
> 開機時就不會有人把它拉起來 —— `After=` 於是等於什麼都沒做。
> 手動 `start` 之所以正常，是因為那個時間點 redis 早就被別的東西帶起來了。
> 修法：`[Unit]` 同時加 `Wants=redis-server.service`（弱相依，redis 掛了我還是嘗試跑，
> 交給應用重試）。要確認相依真的建立了：
> ```bash
> systemctl list-dependencies --after myapp.service | grep redis
> ```
> 對照篇內〈相依關係有兩個維度〉的事故 A。
>
> **Q2.** ★★★★ **錯。** 缺了兩個東西：
> 1. 必須同時寫 `Wants=network-online.target`。這個 target 是「被拉才會到達」的，
>    只寫 `After=` 的話它根本不在啟動序列裡，`After=` 對一個不會啟動的 target 沒有意義。
> 2. 對應的 wait-online 服務要 enable：
>    ```bash
>    systemctl is-enabled systemd-networkd-wait-online.service   # networkd/netplan 環境
>    systemctl is-enabled NetworkManager-wait-online.service     # NM 環境
>    ```
>    沒 enable 的話 `network-online.target` 會「秒到達」，等於沒等。
> 而且即使兩者都對，它只保證「有 IP」，不保證 DNS 可用（要再加 `After=nss-lookup.target`）。
> 見〈開機起不來、手動 start 就好〉。
>
> **Q3.** ★★★★ `ExecStart=` 是 **list 型指令**，drop-in 的寫法是**追加**不是取代，
> 所以合併後會有兩條 `ExecStart=`。對 `Type=simple` 而言這是非法的：
> ```text
> myapp.service: Service has more than one ExecStart= setting, which is only allowed for
> Type=oneshot services. Refusing.
> ```
> `systemctl status` 會顯示 `Loaded: bad-setting`，服務完全無法啟動。
> 若換成 `Type=oneshot` 則不會報錯，而是**兩條依序執行**（更難發現）。
> 正解是先寫一行空值清空：
> ```ini
> [Service]
> ExecStart=
> ExecStart=/usr/local/bin/myapp --new-flag
> ```
> 檢查手段：`systemctl show myapp -p ExecStart | grep -c 'path='` 應該是 `1`。
> ★★★ 注意 `systemctl cat` 看不太出來，要看 `show`。見〈drop-in override 的正式做法〉。
>
> **Q4.** ★★★★ 三個成因與驗證：
> 1. **程式不理 SIGTERM。**
>    ```bash
>    grep SigCgt /proc/$(systemctl show myapp -p MainPID --value)/status
>    php -m | grep -i pcntl        # PHP 服務特別常見
>    ```
> 2. **子程序沒被算進 cgroup／訊號只到 shell。** 用了 `ExecStart=/bin/sh -c '...'`
>    卻沒有 `exec`，或 `KillMode=process`。
>    ```bash
>    systemctl status myapp | sed -n '/CGroup/,$p'    # 看到 sh 與真正的程式並排就是它
>    systemctl show myapp -p KillMode
>    ```
> 3. **`TimeoutStopSec=` 比單筆工作耗時短。**
>    ```bash
>    systemctl show myapp -p TimeoutStopUSec
>    ```
> 對應修法分別是：應用端註冊 handler、`ExecStart=` 直指執行檔或加 `exec`、
> 把 `TimeoutStopSec=` 調到「最長工作 + 30 秒」。見〈停機語意〉。
>
> **Q5.** ★★★★ **（B）`RuntimeDirectory=myapp`**。
> `/run` 是 **tmpfs**，每次開機都是空的：
> - （A）雖然每次啟動都會建，但 `mkdir` 的擁有者是 root，服務帳號可能寫不進去，
>   而且停止時不會清理，殘留的舊 socket 會讓下次啟動失敗。
> - （C）是最經典的地雷：上線當天完全正常，重開機後目錄消失，服務永久起不來，
>   而且沒人會想到問題出在三個月前的一行 `mkdir`。
> - （D）`rc.local` 在多數現代發行版已不預設啟用，時序也無法保證在服務之前。
>
> `RuntimeDirectory=` 會在每次啟動前建好、設好 `User=`／`Group=` 與 `RuntimeDirectoryMode=`，
> 停止時自動清掉，並把路徑放進 `$RUNTIME_DIRECTORY` 給程式用。見〈目錄與權限交給 systemd〉。
>
> **Q6.** ★★★★ 因為 `start` 和 `enable` 是兩回事，而 template unit 的
> **每一個實例都要各自 enable**。你只 `start` 了三個實例（立即生效但不寫入開機序列），
> 而 `enable` 只做過 `@default`。重開機後只有 default 的符號連結存在。
> 症狀最糟的地方是**完全靜默** —— mail 與 report 兩條 queue 沒有 worker，
> 任務只是堆在資料庫裡，沒有任何錯誤日誌。
>
> 上線前檢查：
> ```bash
> ls -1 /etc/systemd/system/multi-user.target.wants/ | grep -c '^laravel-worker@'
> ```
> 應為 `3`。或逐一比對：
> ```bash
> for i in default mail report; do
>   printf '%-8s %s %s\n' "$i" "$(systemctl is-active laravel-worker@$i)" "$(systemctl is-enabled laravel-worker@$i)"
> done
> ```
> 正確做法是一次做完：`systemctl enable --now laravel-worker@{default,mail,report}.service`。
> 見〈Template unit〉。
>
> **Q7.** ★★★★★ `+` 前綴讓那一行**以 root 執行，並且跳過 `User=`、`Group=`、
> `CapabilityBoundingSet=` 與檔案系統沙箱**。而 `/srv/www/app-a/scripts/` 是
> **部署流程會覆寫的目錄** —— 委外廠商、CI 的 deploy key、被打穿的 web 帳號，
> 任何能寫入那支腳本的身分，只要等下一次 `systemctl restart`，
> 就等同拿到 root shell。這是把「應用層權限」直接升級成「整機 root」的後門。
>
> 判斷準則：`+` 指到的檔案必須 `root:root 0755`，而且**路徑上每一層目錄**都不可被他人寫入：
> ```bash
> namei -l /usr/local/sbin/app-pre-start.sh
> ```
> 只要中間有一層是 `drwxrwxr-x deploy deploy`，這個 `+` 就是後門。
> 只需要 root 身分但仍想保留沙箱時用 `!` 而非 `+`。見〈安全性注意事項〉。
>
> **Q8.** ★★★ **（C）`StateDirectory=myapp`**。
> `ProtectSystem=strict` 讓整個檔案系統（含 `/var`）唯讀，只有明確開放的路徑可寫。
> `StateDirectory=myapp` 一次做三件事：建立 `/var/lib/myapp`、
> 把擁有者設成 `User=`／`Group=`、把它加進可寫清單。
> - （A）等於把整層防護拆掉，一個應用層任意檔案寫入漏洞就能改 `/etc` 或 `/usr`。
> - （B）`full` 只保護 `/usr` `/boot` `/etc`，`/var` 可寫 —— 服務會恢復正常，
>   但你是靠降低防護換來的，稽核時說不過去。
> - （D）改用 root 執行是把問題放大到最嚴重。
>
> 若要寫的是應用自己的目錄（例如 Laravel 的 `storage/`），用 `ReadWritePaths=` 明確列出。
> 見〈沙箱化的實務踩雷版〉。
>
> **Q9.** ★★★★ 差別在「systemd 認定啟動完成」的時間點：
> - `simple`：`fork()` 完就算完成。程式在第 2 秒因設定檔錯誤而退出，
>   `systemctl start` 早就回傳成功了 —— 幾乎抓不到任何失敗。
> - `exec`：等 `execve()` 成功。能抓到「執行檔不存在、權限不對、被沙箱擋住」，
>   但抓不到「程式跑起來後才失敗」。
> - `notify`：等應用主動送 `READY=1`。能抓到設定檔錯、埠被佔用、資料庫連不上 —— 最精確。
>
> Nuxt SSR 前面有 Nginx 反向代理，**應該選 `Type=notify`**：
> 用 `simple` 時 systemd 會在 Node 還沒 `listen` 就宣告成功，
> `After=nuxt-ssr.service` 的 Nginx 立刻開始轉發，使用者吃到幾秒鐘的 **502**；
> 部署腳本 `restart` 後馬上打健康檢查也會誤判失敗。
> 改應用只要在 `listen` 的 callback 裡往 `$NOTIFY_SOCKET` 送一個 `READY=1` 即可。
> 不想改程式時的折衷是 `NotifyAccess=all` + `ExecStartPost=` 輪詢 `/healthz` 後
> 呼叫 `systemd-notify --ready`。見〈Type=notify〉。
>
> **Q10.** ★★★ 兩種情況答案相反：
> - **timer 觸發的匯入服務 → `RemainAfterExit=no`。**
>   跑完就要回到 `inactive`，下一次 timer 觸發才會正常啟動。設成 `yes` 的話
>   它會一直停在 `active (exited)`，timer 觸發時 systemd 認為「已經在跑了」而跳過。
> - **開機時建立 bridge 的一次性服務 → `RemainAfterExit=yes`。**
>   否則跑完立刻變 `inactive`，任何 `Requires=` 它的服務會認定相依未滿足而連鎖失敗；
>   `systemctl stop` 也無法觸發它的 `ExecStop=` 清理邏輯。
>   正常狀態長這樣：
>   ```text
>   Active: active (exited) since Fri 2026-08-28 08:30:55 CST; 6h ago
>   ```
> 另外匯入服務常搭 `SuccessExitStatus=75`（EX_TEMPFAIL），
> 讓「來源系統維護中」這種可預期的跳過不算失敗、不觸發告警。
> timer 的寫法見 [[020-02-02-02-cmd-systemd-timer與cron選型]]，本題見〈oneshot + RemainAfterExit〉。

---

## 延伸閱讀

- [[020-01-17-cmd-Linux-systemd服務管理]] —— 本篇的前置：`systemctl` 操作、`status` 判讀、`Type=` 對照表、資源限制
- [[020-02-02-04-svc-systemd-服務自動復原與看門狗]] —— `Restart=` 策略、重啟風暴的抑制、`WatchdogSec=` 與 `OnFailure=` 告警，本篇刻意留給它
- [[020-02-02-02-cmd-systemd-timer與cron選型]] —— 本篇寫好的 oneshot unit 要怎麼被排程觸發、`OnCalendar=` 語法、失敗如何被發現
- [[020-02-02-05-svc-systemd-PM2與systemd整合]] —— Node 服務改用 systemd 時，PM2 自己的 `pm2 startup` 會與你的 unit 打架，這篇講分工與收斂
- [[130-01-04-03-guide-Laravel-佇列排程與Supervisor]] —— Supervisor 的設定寫法與它和 systemd 的取捨（本篇的實戰範例是從它遷過來的）
- [[020-01-10-cmd-Linux-程序管理與訊號]] —— SIGTERM／SIGKILL、程序群組與 cgroup，看懂 `KillMode=` 的前提
- [[090-02-07-guide-防護-SELinux與AppArmor]] —— RHEL 系上 unit 沙箱之外的第二層阻擋，`Permission denied` 查不出原因時看這裡
- [[020-01-15-cmd-Linux-磁碟分割與掛載]] —— `RequiresMountsFor=` 背後的 fstab 與 mount unit
- [systemd.service(5) 官方手冊](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
- [systemd.exec(5) —— 沙箱與目錄委派的完整清單](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
- [systemd.unit(5) —— 相依關係與 specifier 對照表](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html)
- [sd_notify(3) —— Type=notify 的協定細節](https://www.freedesktop.org/software/systemd/man/latest/sd_notify.html)
