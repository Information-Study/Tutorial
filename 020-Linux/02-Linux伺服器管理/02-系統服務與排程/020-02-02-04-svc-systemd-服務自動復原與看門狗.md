---
title: "服務自動復原與看門狗"
desc: "三層防線：Restart 策略、watchdog 與健康檢查、OnFailure 告警——讓服務自己爬起來，爬不起來時有人知道"
aliases: [Restart, RestartSec, StartLimitBurst, WatchdogSec, sd_notify, OnFailure, reset-failed, NRestarts]
tags: [群組/Linux, linux/伺服器, 主題/systemd]
category: 系統服務與排程
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-02-02-01-svc-systemd-unit撰寫實戰]]", "[[020-01-17-cmd-Linux-systemd服務管理]]", "[[020-01-10-cmd-Linux-程序管理與訊號]]"]
updated: 2026-08-28
---

# 服務自動復原與看門狗

> [!abstract] 這篇你會學到
> - 讀懂 `Restart=` **七種模式 × 六種退出情境**的完整矩陣，並且知道怎麼**自己驗證**它 ——
>   用 `kill <pid>` 測 `Restart=on-failure` 得到「沒重啟」是全機關最普遍的誤判
> - ★★★★ 算出 `RestartSec=` 與 `StartLimitIntervalSec=` / `StartLimitBurst=` 的**臨界關係**：
>   設太急 → 1 秒內撞上限、服務永久停擺；設太鬆 → 永遠不撞上限、無限重啟灌爆磁碟。
>   **兩種結局都叫「安靜的死亡」**，而預設值剛好是前者
> - 用 `RestartPreventExitStatus=` 把「重啟一萬次也一樣」的設定檔錯誤擋在重啟迴圈外
> - 用 `WatchdogSec=` + `sd_notify` 讓**假死**也算掛掉；改不了程式碼的委外服務改用健康檢查 timer，
>   並且把 liveness（驅動重啟）與 readiness（只驅動告警）分開
> - 用 `OnFailure=alert@%n.service` 把失敗變成一則真的送得出去的告警，
>   再用 `NRestarts` 巡檢補上「一直重啟但沒撞上限所以永遠不告警」這個洞
> - 產出一支可直接執行的 `setup-service-recovery.sh`，含四種故障注入的驗收與完整回滾

---

## 前置知識

| 篇章 | 你需要從那篇帶過來的東西 |
| --- | --- |
| [[020-02-02-01-svc-systemd-unit撰寫實戰]] | unit 三區段、drop-in 與 template unit 的**寫法**、`Type=notify` 的 **READY=1 就緒通知**、`TimeoutStopSec=` / `KillMode=` 停機語意、`systemd-analyze verify` |
| [[020-01-17-cmd-Linux-systemd服務管理]] | `systemctl` 基本操作、`status` 判讀、`enable` 與 `start` 的差別 |
| [[020-01-10-cmd-Linux-程序管理與訊號]] | SIGTERM／SIGKILL／SIGABRT／SIGSTOP 的差別、core dump、cgroup |
| [[020-02-02-02-cmd-systemd-timer與cron選型]] | timer unit 的 `OnCalendar=` / `OnUnitActiveSec=` 語法、`systemctl list-timers` 判讀 |
| [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]] | `flock` 互斥與 `timeout` 保護的完整用法（本篇的告警腳本會直接用） |
| [[020-01-19-guide-Linux-日誌系統]] | `journalctl -u` 過濾、journal 磁碟上限與輪替 |

> [!note] 本篇在本章的位置：**收尾篇**
> 前四篇把「服務怎麼寫、怎麼排程」講完了，**唯獨把「掛掉之後怎麼辦」整包留給本篇**：
>
> | 主題 | 在哪一篇 | 本篇的分工 |
> | --- | --- | --- |
> | unit 三區段、相依、drop-in／template 的**寫法** | [[020-02-02-01-svc-systemd-unit撰寫實戰]] | 本篇只寫「怎麼用」，不重講機制 |
> | `Type=notify` 的 **`READY=1`（就緒）** | [[020-02-02-01-svc-systemd-unit撰寫實戰]] | 本篇負責**同一條 socket 的另一半：`WATCHDOG=1`（心跳）** |
> | timer 語法與 `list-timers` 判讀 | [[020-02-02-02-cmd-systemd-timer與cron選型]] | 本篇寫兩支 timer，但只寫**設計理由與檔案內容** |
> | `flock` 去重、`timeout` 保護 | [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]] | 本篇**只用不教** |
> | PM2 與 systemd 的雙層退避怎麼對齊 | [[020-02-02-05-svc-systemd-PM2與systemd整合]] | 本篇講通則，Node/PM2 情境請看那篇 |
> | 外部監控平台、健康檢查端點設計 | [[100-01-03-guide-日誌-系統監控與告警]]、[[100-01-04-guide-日誌-健康檢查與可用性監控]] | 本篇只做**主機本地、用來驅動重啟**的那一層 |
>
> `Type=notify` 這一組的分工要特別記住：**就緒通知（READY=1）是 01 的，心跳通知（WATCHDOG=1）是本篇的**，
> 兩者走同一個 `$NOTIFY_SOCKET`、受同一個 `NotifyAccess=` 管，但解決的問題完全不同。

---

## 觀念說明

### 自動復原設錯，比不設更危險

先把本篇的核心命題講在最前面。多數人以為自動復原是「有設比沒設好」的加分題，實際上它是一道**會扣分的申論題**：

```text
                    ┌──────────────────────────────────────────────┐
                    │            服務在半夜掛掉了                  │
                    └───────────────────┬──────────────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                               ▼
  沒設 Restart=                   設太急（預設值）                 設太鬆
  服務停在那裡                    RestartSec=100ms                 RestartSec=30
  隔天上班才發現                  StartLimit 10s/5 次              StartLimitIntervalSec=10
        │                               │                               │
        ▼                               ▼                               ▼
  停機 8 小時                     0.5 秒內撞上限                   永遠撞不到上限
  至少「有人會發現」              進 failed 永久停擺               每 30 秒重啟一次
                                  而且沒有任何告警                 一夜 2880 次、寫爆 journal
                                        │                               │
                                        └───────────┬───────────────────┘
                                                    ▼
                                          ★★★★ 兩種「安靜的死亡」
                                        （服務不能用，但沒有人知道）
```

**沒有告警的自動復原，只是把「明顯的停機」換成「隱形的停機」。**
所以本篇不是在教三個設定項，而是在教三層防線怎麼串成一條線。

### 三層防線：本篇的骨幹

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ 第一層：自己爬起來        Restart= / RestartSec= / RestartSteps=             │
│  ┌───────────┐  程序死了   ┌──────────────┐  等 RestartSec  ┌──────────────┐ │
│  │  running  │────────────►│ 判定要不要重啟│────────────────►│ 重新 start   │ │
│  └───────────┘             └──────┬───────┘                 └──────┬───────┘ │
│                                   │ RestartPreventExitStatus= 命中 │         │
│                                   ▼                                ▼         │
│                              直接 failed          StartLimitIntervalSec/Burst │
│                                   │                    撞上限 ──► failed      │
├───────────────────────────────────┼──────────────────────────────┼───────────┤
│ 第二層：假死也算掛        WatchdogSec= + WATCHDOG=1               │           │
│   應用每 T/2 送一次心跳 ──► 沒送到 ──► systemd 送 SIGABRT ────────┘           │
│   （改不了程式碼？改用「健康檢查 timer」，見進階段）                          │
├──────────────────────────────────────────────────────────────────────────────┤
│ 第三層：有人知道          OnFailure=alert@%n.service（只在 failed 觸發）      │
│                           + NRestarts 巡檢 timer（補「一直重啟但沒 failed」） │
│                           + systemctl is-system-running（整機一行健康指標）   │
└──────────────────────────────────────────────────────────────────────────────┘
        ▲                                                             │
        │  ★★★ 天花板：整台機器當掉／網路斷掉時這三層全部失效        │
        └────────► 一定要有外部監控（見 [[100-01-03-guide-日誌-系統監控與告警]]）───────┘
```

三層要**一起設計**。只設第一層＝安靜的死亡；只設第三層＝人半夜爬起來手動 start；
設了第二層卻沒對齊第一層＝假死之後就地停機（本篇最經典的反例，後面會展開）。

### Restart= 七種模式 × 六種退出情境（可以貼在牆上的那張表）

這張表直接對應 `systemd.service(5)` 的 "Exit causes and the effect of the `Restart=` settings"，
但把「維運人員實際會遇到的動作」補進去了：

| 退出情境（實際發生什麼） | `no` | `always` | `on-success` | `on-failure` | `on-abnormal` | `on-abort` | `on-watchdog` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ★★★★ **乾淨退出**：exit 0，或收到 SIGHUP／SIGINT／**SIGTERM**／SIGPIPE，或命中 `SuccessExitStatus=` | ✘ | ✔ | ✔ | ✘ | ✘ | ✘ | ✘ |
| **非 0 退出碼**：exit 1、exit 78（設定檔錯） | ✘ | ✔ | ✘ | ✔ | ✘ | ✘ | ✘ |
| ★★★ **非乾淨訊號**：SIGKILL、SIGSEGV、SIGABRT、SIGBUS | ✘ | ✔ | ✘ | ✔ | ✔ | ✔ | ✘ |
| **逾時**：`TimeoutStartSec=` / `TimeoutStopSec=` / reload 逾時 | ✘ | ✔ | ✘ | ✔ | ✔ | ✘ | ✘ |
| **watchdog 逾時**：`WatchdogSec=` 內沒收到 `WATCHDOG=1` | ✘ | ✔ | ✘ | ✔ | ✔ | ✘ | ✔ |
| **被 OOM killer 殺掉** | ✘ | ✔ | ✘ | ✔ | ✔ | ✘ | ✘ |

三個一定要記住的例外，不在表格裡但優先權更高：

| 例外 | 行為 | 星級 |
| --- | --- | --- |
| `systemctl stop` / `restart` 造成的結束 | **永遠不觸發自動重啟**（systemd 自己弄死的不算掛） | ★★★ |
| 退出碼／訊號列在 `RestartPreventExitStatus=` | **永遠不重啟**，不管 `Restart=` 設什麼 | ★★★★ |
| 退出碼／訊號列在 `RestartForceExitStatus=` | **一定重啟**，不管 `Restart=` 設什麼 | ★★ |

> [!warning] `Type=oneshot` 的限制（官方明文）
> `systemd.service(5)`：*"Type=oneshot services will never be restarted on a clean exit status,
> i.e. `always` and `on-success` are rejected for them."*
> 也就是說 **oneshot 服務不能設 `Restart=always` 或 `on-success`**，`on-failure` 則可以。
> 這對本篇很重要 —— 後面的健康檢查／巡檢都是 oneshot + timer，**它們的重試要靠 timer 的下一次觸發，不是靠 `Restart=`**。
> 另外 `on-abort` 那一欄的「OOM 不重啟」看起來反直覺（OOM 明明是 SIGKILL），
> 但官方表格確實把 OOM 獨立成一列且 `on-abort` 沒有打勾，照表走就對了。

### ★★★★★ 為什麼你用 `kill` 測出來的結果是錯的

這是全機關最普遍、後果最嚴重的一個測試方法誤解，**它單獨值得一個小節**：

```text
維運：「我設了 Restart=on-failure，來測一下」
      kill 12345               ← 預設送 SIGTERM
維運：「……沒有重啟。Restart 根本沒用。」
      改成 Restart=always      ← ★★★★★ 災難從這裡開始
```

`kill` 的**預設訊號是 SIGTERM，而 SIGTERM 屬於「乾淨退出」**（見上表第一列）。
`on-failure` 遇到乾淨退出本來就不重啟 —— **設定完全正確，是測試方法錯了**。

而把它改成 `Restart=always` 的代價是：從此以後**連「設定檔寫錯就退出」也會被無限重啟**，
第一層防線從「保護」變成「放大器」。

正確的驗收要用三種注入方式分別驗，缺一不可：

```bash
# ★★★★ (1) 模擬崩潰 —— 非乾淨訊號，on-failure 應該重啟
sudo systemctl kill -s SIGKILL apply-api.service

# ★★★★ (2) 模擬假死 —— 程序還在、但不回應（第二層防線的測法）
sudo kill -STOP "$(systemctl show apply-api.service -p MainPID --value)"

# ★★★★ (3) 模擬設定錯誤 —— 讓應用以退出碼 78 結束，驗 RestartPreventExitStatus=
sudo systemd-run --unit=exit78-test /bin/sh -c 'exit 78'
```

注意 (1) 用的是 `systemctl kill`（走 systemd，狀態會正確記錄成 unit 的事件）而不是 `kill`。
**永遠不要用 `kill <pid>`（SIGTERM）當作「重啟功能有沒有效」的判準。**

### 一次崩潰在 systemd 裡走完的完整路徑

```text
  主程序結束（exit code 或訊號）
        │
        ▼
  ┌────────────────────────────┐  命中 ──► 直接 failed，不重啟（★★★★ 設定檔錯誤走這條）
  │ RestartPreventExitStatus=? │
  └────────────┬───────────────┘
               │ 未命中
               ▼
  ┌────────────────────────────┐  不該重啟 ──► inactive（乾淨退出）或 failed
  │ Restart= 矩陣判定           │
  └────────────┬───────────────┘
               │ 該重啟
               ▼
  ┌────────────────────────────┐
  │ 等待 RestartSec=           │  有 RestartSteps= 時：10s → 20s → 40s …（v254+）
  └────────────┬───────────────┘
               ▼
  ┌────────────────────────────────────────────────────────┐
  │ StartLimit 檢查：interval 內啟動次數 >= burst ?        │
  └────────┬───────────────────────────────┬───────────────┘
           │ 否                            │ 是 ★★★★
           ▼                               ▼
     重新 start                    Active: failed (Result: start-limit-hit)
     NRestarts + 1                 journal: "Start request repeated too quickly."
     （此時 OnFailure= 不觸發）     │
                                   ├──► 觸發 OnFailure=（第三層防線）
                                   ├──► 觸發 StartLimitAction=（★★★★★ 預設 none，別亂設）
                                   └──► 之後所有 systemctl start 都被擋，直到 reset-failed
```

**看懂這張圖就懂了本篇八成**：`OnFailure=` 掛在最右下角那個分支上，
所以「一直重啟但每次都勉強起得來」的服務永遠走不到那裡 —— 這個洞要靠 `NRestarts` 巡檢補。

---

## 基礎設定

### 第 0 步：先確認你的 systemd 版本

本篇有幾個參數有版本門檻，動筆改設定前先量一下手上的機器：

```bash
systemctl --version | head -1
```

預期輸出：

```text
systemd 249 (249.11-0ubuntu3.12)     # ★★★ 這個數字決定你能不能用 RestartSteps=
```

| 發行版 | systemd 版本（約） | `RestartSteps=`／`RestartMaxDelaySec=`（v254+） | `OnSuccess=`（v249+） | `OOMPolicy=`（v243+） |
| --- | --- | --- | --- | --- |
| Ubuntu 20.04 LTS | 245 | ✘ | ✘ | ✔ |
| Ubuntu 22.04 LTS | 249 | ✘ | ✔ | ✔ |
| ★ Ubuntu 24.04 LTS | 255 | ✔ | ✔ | ✔ |
| RHEL / Rocky 8 | 239 | ✘ | ✘ | ✘ |
| RHEL / Rocky 9 | 250～252 | ✘ | ✔ | ✔ |

> [!tip] 版本判斷的通則
> **機關主機多半停在 Ubuntu 22.04 或 RHEL 8**，也就是**沒有指數退避可用**。
> 這不是問題 —— 用「固定 `RestartSec=10` + `StartLimitIntervalSec=300` / `StartLimitBurst=5`」
> 一樣能收斂，後面〈舊版沒有 RestartSteps 怎麼辦〉會給等效寫法。

### `Restart=` 該選哪一個

| 服務形狀 | 建議值 | 理由 | 星級 |
| --- | --- | --- | --- |
| 長時間執行的網路服務（Nginx、Node API、PHP-FPM） | ★★★★ `on-failure` | 官方明文推薦；`systemctl stop` 不會被打回來，設定檔錯誤（非 0 退出）會被重啟但可用 `RestartPreventExitStatus=` 擋掉 | ★★★★ |
| 佇列 worker（Laravel queue、Sidekiq） | `on-failure` + `SuccessExitStatus=` | worker 被 SIGTERM 優雅收工屬正常，不該當失敗 | ★★★ |
| 「跑完自己該結束、但被殺掉要回來」 | `on-abnormal` | 官方對「可以自行決定結束」的服務的建議選項 | ★★ |
| 只想在假死時處理，其他一律不管 | `on-watchdog` | 極少用，通常搭 `on-failure` 就夠 | ★ |
| 需要 core dump 分析的 C/C++ 服務 | `on-abort` | 只在未捕捉訊號時重啟 | ★ |
| ★★★★ 不確定就用它 | **不要用 `always`** | `always` 連「乾淨退出」都重啟，等於把「設定檔錯誤」變成無限迴圈 | ★★★★ |
| oneshot（健康檢查、巡檢） | `no`（預設） | oneshot 不接受 `always`／`on-success`；重試交給 timer | ★★★ |

### ★★★★ 本篇的核心算術：RestartSec 與 StartLimit 的交互作用

先把三個預設值放在一起看：

```bash
systemctl show apply-api.service -p RestartUSec,StartLimitIntervalUSec,StartLimitBurst
```

預期輸出（**完全沒設定時的預設值**）：

```text
RestartUSec=100ms                # ★★★★ 一百毫秒
StartLimitIntervalUSec=10s       # DefaultStartLimitIntervalSec= 預設 10s
StartLimitBurst=5                # DefaultStartLimitBurst= 預設 5
```

意思是：**服務崩潰迴圈時，systemd 每 100 毫秒重試一次，10 秒內第 5 次就撞上限**。
如果服務啟動只要 50ms 就死，整個過程 **0.6 秒**就結束，然後永久停在 failed。

反過來，很多人「怕重啟太急」把 `RestartSec=30` 拉大卻沒動 interval，
結果 30 秒才重啟一次、10 秒的窗口內永遠只有 1 次啟動 —— **永遠撞不到上限，無限重啟**。

**臨界條件（本篇最該被抄進交接文件的一行）**：

```text
要「撞得到上限」，大致需要：  RestartSec × (Burst − 1) < StartLimitIntervalSec

  ★★★★ 這是必要條件不是充分條件 —— 實際間隔 = RestartSec + 服務從啟動到死掉的時間，
        所以真正的判準是：Burst 次啟動要能塞進 IntervalSec 的滑動窗口內。
```

三組參數組合對照：

| 組合 | 撞上限所需時間 | 實際行為 | 適用情境 | 星級 |
| --- | --- | --- | --- | --- |
| 預設：`RestartSec=100ms`、`300s`… 不，是 `10s` / `5` | **< 1 秒** | 一崩潰就進 failed 永久停擺；短暫的資料庫抖動也會害它停整晚 | ★★★★ **幾乎所有正式服務都不該留在預設** | ★★★★ |
| `RestartSec=30` / `StartLimitIntervalSec=10` / `Burst=5` | **永遠撞不到** | 無限重啟；一夜 2880 次、journal 灌爆 `/var` | 只有在「重啟一定會成功、只是慢」的場景才勉強可用 | ★★★★ |
| ★ **機關建議基準**：`RestartSec=10` / `StartLimitIntervalSec=300` / `Burst=5` | 約 50 秒～5 分鐘 | 五分鐘內重啟五次還不行就放棄、進 failed、**觸發告警** | ★★★★ 一般網路服務的預設值，直接抄 | ★★★★ |
| 資料庫這類重啟很貴的服務：`RestartSec=30` / `IntervalSec=600` / `Burst=3` | 約 1～10 分鐘 | 給資料庫更長的喘息，但仍會收斂 | 資料庫、訊息佇列 | ★★★ |

drop-in 寫法（drop-in 的機制與檔案位置見 [[020-02-02-01-svc-systemd-unit撰寫實戰]]，這裡只寫內容）：

```bash
sudo systemctl edit apply-api.service
```

```ini
# /etc/systemd/system/apply-api.service.d/override.conf
[Unit]
# ★★★★ 這兩個在 [Unit]，不是 [Service]
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Restart=on-failure
RestartSec=10
```

### ★★★★ 寫錯區段不會報錯，只會安靜失效

`StartLimitIntervalSec=` 與 `StartLimitBurst=` 從 systemd 229 起屬於 **`[Unit]`** 區段
（更早的版本在 `[Service]`）。寫在 `[Service]` 的後果在不同版本表現不一，實測（systemd 259）：

```bash
systemd-analyze verify ./t.service
```

預期輸出：

```text
/path/t.service:8: Unknown key 'StartLimitIntervalSec' in section [Service], ignoring.
```

```text
（把 StartLimitBurst= 單獨放在 [Service]：★★★★ 連警告都沒有，rc=0，靜悄悄地不生效）
```

也就是說 **`systemd-analyze verify` 抓得到一半，抓不到另一半**。唯一可靠的驗證是看**生效值**：

```bash
systemctl show apply-api.service -p StartLimitIntervalUSec,StartLimitBurst
```

預期輸出：

```text
StartLimitIntervalUSec=5min      # ★★★★ 看到 5min 才代表 300 秒真的生效
StartLimitBurst=5
```

> [!danger] ★★★★ 這個坑為什麼致命
> 你以為自己設了「五分鐘五次就放棄」的防重啟風暴，實際生效的是**預設的 10 秒五次**。
> 服務第一次抖動就進 failed 永久停擺，而你在事後檢討會上拿著 unit 檔說「我明明設了」。
> **`systemctl cat` 只能證明你寫了什麼，`systemctl show` 才能證明 systemd 收下了什麼。**

### 用退出碼把「重啟也沒用」的失敗排除掉

有一類失敗**重啟一萬次結果都一樣**：設定檔語法錯、憑證過期、必要環境變數沒設、資料庫帳密錯。
這些應該**直接 failed 並告警**，而不是浪費五分鐘做五次注定失敗的重啟。

| 設定項 | 作用 | 典型用法 | 星級 |
| --- | --- | --- | --- |
| ★★★★ `RestartPreventExitStatus=` | 這些退出碼**一律不重啟** | `RestartPreventExitStatus=78` （78 = `CONFIG`，BSD 慣例的「設定檔有問題」） | ★★★★ |
| `RestartForceExitStatus=` | 這些退出碼**一律重啟** | 應用自訂的「請重啟我」訊號，例如 `RestartForceExitStatus=100` | ★★ |
| ★★★ `SuccessExitStatus=` | 把某些退出碼／訊號**視為成功** | worker 收到 SIGTERM 後 `exit 143` → `SuccessExitStatus=143 SIGTERM` | ★★★ |

```ini
[Service]
Restart=on-failure
RestartSec=10
# ★★★★ 設定檔錯誤（78）直接躺平，不做無謂重試 —— 讓 OnFailure= 立刻叫人
RestartPreventExitStatus=78
# ★★★ worker 優雅收工不算失敗
SuccessExitStatus=143 SIGTERM
```

**怎麼查出你的應用用哪些退出碼？** 三個做法，由可靠到不可靠：

```bash
# 【查法 1】直接問 systemd：上一次主程序的退出碼是多少
systemctl show apply-api.service -p ExecMainStatus,ExecMainCode,Result
```

預期輸出：

```text
ExecMainStatus=78                # ★★★★ 這就是你要放進 RestartPreventExitStatus= 的數字
ExecMainCode=1                   # 1 = exited（2 = killed by signal）
Result=exit-code
```

```bash
# 【查法 2】翻 journal，systemd 會直接把退出碼寫成人看得懂的名字
journalctl -u apply-api.service -n 20 --no-pager | grep -i 'main process exited'
```

預期輸出：

```text
Aug 28 03:11:07 srv systemd[1]: apply-api.service: Main process exited, code=exited, status=78/CONFIG
```

```bash
# 【查法 3】把數字翻譯成名字，確認語意
systemd-analyze exit-status 78
```

預期輸出：

```text
NAME   STATUS CLASS
CONFIG     78 BSD
```

> [!warning] ★★★ 委外系統退出碼沒有文件時的保守做法
> 機關的委外系統十有八九沒有「退出碼一覽」這種文件。**不要靠猜**。保守流程：
> 1. **先不要設 `RestartPreventExitStatus=`**，只設 `Restart=on-failure` + 收斂的 StartLimit。
> 2. 觀察一至兩週，用 `journalctl -u <unit> | grep 'status='` 收集實際出現過的退出碼。
> 3. 只把**已經確認「重啟無效」的**那幾個（通常是 78、1 之外的特定值）加進去，一次加一個，並記入變更紀錄（見 [[100-02-08-guide-維運-變更管理流程]]）。
>
> ★★★★ 千萬不要反過來把 `1` 加進 `RestartPreventExitStatus=` —— 絕大多數應用把「任何錯誤」都用 exit 1 表示，
> 加了它等於把整個第一層防線關掉。

### 指數退避：RestartSteps= 與版本相容

固定 `RestartSec=10` 的問題是：下游（資料庫、外部 API）要修 20 分鐘時，你的服務在這 20 分鐘裡
每 10 秒敲一次門，只是在製造 connection 風暴。**指數退避**讓它越敲越慢：

```ini
[Service]
Restart=on-failure
RestartSec=1s                 # 第一次很快，讓短暫抖動幾乎無感
RestartSteps=5                # ★★ 官方建議 3～5
RestartMaxDelaySec=5min       # 退到 5 分鐘就不再拉長
```

官方對這組參數的說明（`systemd.service(5)`，v254 起）：間隔以幾何級數內插，
比值 = `(RestartMaxDelaySec / RestartSec)^(1 / RestartSteps)`，
在 `RestartSteps + 1` 步之後穩定在 `RestartMaxDelaySec`。上面這組實際會產生：

```text
1s → 2.3s → 5.5s → 13s → 30s → 71s …（依比值 (300/1)^(1/5) ≈ 3.13）
```

驗證有沒有生效：

```bash
systemctl show apply-api.service -p RestartUSec,RestartSteps,RestartMaxDelayUSec
```

預期輸出：

```text
RestartUSec=1s
RestartSteps=5
RestartMaxDelayUSec=5min         # ★★★ 舊版會顯示 infinity 且 RestartSteps=0
```

> [!info]- 舊版沒有 RestartSteps= 怎麼辦（Ubuntu 22.04 / RHEL 8）
> systemd < 254 沒有這兩個參數，寫了會被當成未知鍵忽略（等於沒設）。等效替代策略：
>
> ```ini
> [Unit]
> StartLimitIntervalSec=300
> StartLimitBurst=5
>
> [Service]
> Restart=on-failure
> RestartSec=10          # ★★★ 用固定間隔 + 收斂的 StartLimit 取代退避
> ```
>
> 邏輯是「不追求越敲越慢，而是**敲五次就放棄並告警**」——
> 讓第三層防線（`OnFailure=`）接手，由人或由外部監控決定要不要繼續。
> 這在機關情境反而更好：**與其讓機器自己退避半小時，不如五分鐘後就叫人。**
>
> 另一個舊版可用的補救是 `RestartMode=`（也是 v254+，一樣沒有），
> 所以 RHEL 8 上就是「固定間隔 + 早點放棄」這一條路。

### 兩種安靜的死亡，怎麼當場判讀

**死法一：撞上限（有 failed，但沒人看）**

```bash
systemctl status apply-api.service
```

預期輸出：

```text
● apply-api.service - 線上申辦 API
     Active: failed (Result: start-limit-hit) since Sat 2026-08-28 03:11:12 CST; 9h ago
                     ^^^^^^^^^^^^^^^^^^^^^^ ★★★★ 看到 start-limit-hit 就是撞上限
```

```bash
journalctl -u apply-api.service -n 5 --no-pager
```

預期輸出：

```text
systemd[1]: apply-api.service: Start request repeated too quickly.
systemd[1]: apply-api.service: Failed with result 'start-limit-hit'.
systemd[1]: Failed to start 線上申辦 API.
```

★★★★ **這個狀態下 `systemctl start` 會被擋**，而且錯誤訊息跟原因無關，值班人員會卡住：

```bash
sudo systemctl start apply-api.service
```

預期輸出：

```text
Job for apply-api.service failed.
See "systemctl status apply-api.service" and "journalctl -xeu apply-api.service" for details.
```

修好根因之後**必須**清掉計數器（`systemctl reset-failed` 會 flush 這個 unit 的 rate limit 計數）：

```bash
sudo systemctl reset-failed apply-api.service && sudo systemctl start apply-api.service
```

預期輸出：

```text
（沒有輸出＝成功；接著 systemctl is-active apply-api.service 應回 active）
```

**死法二：沒撞上限的無限重啟（連 failed 都沒有）**

```bash
systemctl show apply-api.service -p NRestarts,Result,ExecMainStatus,ActiveEnterTimestamp
```

預期輸出：

```text
NRestarts=2873                                        # ★★★★ 這個數字才是真相
Result=success
ExecMainStatus=0
ActiveEnterTimestamp=Sat 2026-08-28 12:04:31 CST      # ★★★ 「剛剛」才起來 = 一直在重啟
```

```bash
journalctl -u apply-api.service --since -1h | grep -c 'Scheduled restart job'
```

預期輸出：

```text
118          # ★★★★ 一小時 118 次 = 平均 30 秒一次，這是無限重啟不是穩定服務
```

**再往上一層：兩個一行就能接進監控的整機訊號**

```bash
systemctl --failed --no-legend
```

預期輸出：

```text
apply-worker@notify.service loaded failed failed 補件通知佇列 worker
```

```bash
systemctl is-system-running
```

預期輸出：

```text
degraded       # ★★★★ 只要有任何 unit 處於 failed 就會回 degraded（正常是 running）
               # 這一行是最省事的整機健康指標，直接餵給 Zabbix / Wazuh / Nagios
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> 上述指令、參數、預設值在 RHEL 系**完全相同**（systemd 是同一套）。實務差異只有三處：
>
> ```bash
> # ★★★ RHEL 8 是 systemd 239：沒有 RestartSteps= / RestartMaxDelaySec= / OnSuccess=
> systemctl --version | head -1
> ```
>
> - **SELinux**：自訂的告警腳本放 `/usr/local/bin/` 通常標記為 `bin_t`，由 systemd 直接執行沒問題；
>   但若腳本要寫入非標準路徑（例如 `/var/lib/svc-alert/`），需要 `restorecon -Rv` 或補 fcontext，
>   否則會出現「腳本手動跑得動、被 systemd 叫就 Permission denied」的典型 SELinux 症狀：
>   ```bash
>   sudo ausearch -m avc -ts recent | tail -20
>   ```
> - **journal 預設不持久化**：RHEL 系 `/var/log/journal` 可能不存在，重開機後查不到崩潰現場。
>   持久化設定見 [[020-01-19-guide-Linux-日誌系統]]。
> - 套件版 unit 在 `/usr/lib/systemd/system/`（Ubuntu 也是），drop-in 一律放 `/etc/systemd/system/<unit>.d/`。

---

## 進階設定與調校

### 第二層防線之一：WatchdogSec= 的完整機制

**服務「還活著」不等於「還能用」。** 執行緒池死鎖、event loop 被同步 I/O 卡住、
GC 進入 stop-the-world 死循環 —— 這些情況下程序好好地在那裡，`Restart=` 永遠不會被觸發。

```text
  ┌──────────────────────────────────────────────────────────────────┐
  │ unit: WatchdogSec=30s                                            │
  └───────────────────────────┬──────────────────────────────────────┘
                              │ 啟動完成時 watchdog 才開始計時
                              ▼
  systemd 把 WATCHDOG_USEC=30000000 塞進服務的環境變數
                              │
                              ▼
  應用每 15 秒（★★★ 週期的一半以內）送一次：  sd_notify("WATCHDOG=1")
                              │
              ┌───────────────┴───────────────┐
              │ 有收到                        │ 超過 30 秒沒收到
              ▼                               ▼
         繼續正常運作            systemd 判定假死 → 送 WatchdogSignal=（預設 SIGABRT）
                                              │  （會留下 core dump 供事後分析）
                                              ▼
                                    走 Restart= 矩陣的「watchdog 逾時」那一列
                                              │
                          ┌───────────────────┴───────────────────┐
                          │ Restart= 是 on-watchdog/on-failure/   │ Restart=no
                          │ on-abnormal/always → 重新拉起          │ → ★★★★ 就地停機
                          └───────────────────────────────────────┘
```

```ini
[Service]
Type=notify
WatchdogSec=30s
# ★★★★ 致命前提一：沒有這行，watchdog 只會「殺死」不會「復活」
Restart=on-failure
RestartSec=10
# 可選：給 core dump 足夠時間寫完（v243+）
TimeoutAbortSec=30
```

> [!danger] ★★★★ 兩個前提，缺一個就比不設 watchdog 更糟
> **前提一：`WatchdogSec=` 沒搭配 `Restart=`（on-watchdog / on-failure / on-abnormal / always）**
> 假死被 SIGABRT 殺掉之後**就地停機且不會被拉起來**。
> 你本來只是「服務很慢」，設了 watchdog 之後變成「服務完全消失」。
>
> **前提二：主程序必須送得到通知。**
> 官方行為（`systemd.service(5)`）：使用 `Type=notify` 或 `WatchdogSec=` 時，
> **若 `NotifyAccess=` 沒有設定，會被隱含設為 `main`**。
> 所以真正的地雷是這兩種：
> - 你**明確寫了** `NotifyAccess=none` → 所有心跳被丟棄 → 每 30 秒被 SIGABRT 一次。
> - 心跳是由**子程序／worker** 送的（不是 `ExecStart=` 起的那個主程序）→ `main` 收不到，
>   必須設 `NotifyAccess=all`。

驗證 watchdog 真的生效：

```bash
systemctl show apply-api.service -p WatchdogUSec,NotifyAccess,Restart
```

預期輸出：

```text
WatchdogUSec=30s
NotifyAccess=main        # ★★★ Type=notify/WatchdogSec= 下沒寫就會是 main
Restart=on-failure       # ★★★★ 這行是 no 的話，上面兩行設了也是災難
```

### 三種語言的最小可行心跳

**Node.js**（不裝任何套件，直接寫 `$NOTIFY_SOCKET`）：

```javascript
// ★★★ WATCHDOG_USEC 是 systemd 塞進來的微秒數；心跳週期取一半
const dgram = require('dgram')
const sock = process.env.NOTIFY_SOCKET
function notify (msg) {
  if (!sock) return                                    // 不在 systemd 底下就跳過
  const c = dgram.createSocket('unix_dgram')
  c.send(Buffer.from(msg), 0, msg.length,
    sock.startsWith('@') ? '\0' + sock.slice(1) : sock, // abstract socket
    () => c.close())
}
notify('READY=1')                                       // 就緒通知：見 01
const usec = parseInt(process.env.WATCHDOG_USEC || '0', 10)
if (usec > 0) {
  setInterval(() => {
    if (healthyEnough()) notify('WATCHDOG=1')           // ★★★★ 不健康就「不要送」
  }, Math.floor(usec / 1000 / 2))                       // usec → ms，再取一半
}
```

**Python**（`python3-systemd`）：

```python
# Ubuntu: sudo apt install -y python3-systemd
import os, threading
from systemd.daemon import notify

notify("READY=1")
usec = int(os.environ.get("WATCHDOG_USEC", 0))
if usec:
    def beat():
        if queue_worker_alive():        # ★★★ 淺檢查：自己的工作執行緒還活著嗎
            notify("WATCHDOG=1")
        threading.Timer(usec / 1e6 / 2, beat).start()
    beat()
```

**PHP-FPM**：PHP-FPM 主程序**原生支援 systemd notify**，但要用對 unit：

```ini
# /etc/systemd/system/php8.3-fpm.service.d/override.conf
[Service]
# ★★★ php-fpm.conf 內需 daemonize = no；套件的 unit 已是 Type=notify
WatchdogSec=30s
Restart=on-failure
RestartSec=10

[Unit]
StartLimitIntervalSec=300
StartLimitBurst=5
```

```bash
systemctl show php8.3-fpm.service -p Type,WatchdogUSec
```

預期輸出：

```text
Type=notify
WatchdogUSec=30s
```

> [!warning] ★★★★ 判斷準則：不能改程式碼就不要用 watchdog
> `WatchdogSec=` 需要**應用主動送心跳**。委外的 Java WAR、封裝好的商用套件、
> 你沒有原始碼的服務 —— 一律**不要設 `WatchdogSec=`**，設了就是每 30 秒被 SIGABRT 一次。
> 這種服務改走下一節的「健康檢查 timer」，那是從外面看、不需要碰程式碼的做法。
>
> 判斷指令：如果下面這行是空的，代表這個服務根本沒在講 sd_notify 協定：
> ```bash
> systemctl show <unit> -p Type,NotifyAccess,StatusText
> ```

### shell 腳本送 sd_notify 的可靠性坑

`systemd-notify` 看起來很誘人（不用改程式），但它有一個 PID 歸屬問題，
`systemd.service(5)` 講得很白：**通知只有在「送訊息的程序在 PID 1 處理訊息時還活著」，
或「該程序是 systemd 自己 fork 出來的」時，才能被正確歸屬到 unit**；
輔助程序送完就馬上結束的話，**即使設了 `NotifyAccess=all` 也可能被忽略**。

```bash
# ★★★★ 反例：這行有競態，systemd-notify 送完就退出，訊息可能無法歸屬
ExecStartPost=/usr/bin/systemd-notify --ready

# 比較可靠：等到真的健康了再送，且讓送的程序在 cgroup 內
ExecStartPost=/bin/sh -c 'until curl -sf http://127.0.0.1:3000/healthz >/dev/null; do sleep 1; done; systemd-notify --ready'
```

`--pid=` 的語意（`systemd-notify(1)`）：

| 用法 | 意義 | 星級 |
| --- | --- | --- |
| `--pid=auto`（或省略參數） | 用**呼叫 systemd-notify 的那個程序**的 PID | ★★ |
| `--pid=self` | 用 `systemd-notify` 自己的 PID | ★ |
| `--pid=parent` | 用呼叫者的 PID，**即使呼叫者是 systemd 本身** | ★ |
| `--pid=<PID>` | 指定 PID；★★★ **需要足夠權限才成功**，失敗時會退回用自己的 PID | ★★★ |

★★★ 官方另有一段警告值得抄進交接文件：**有權限的 `systemd-notify --pid=` 呼叫，
可以繞過 `NotifyAccess=main` / `exec` 的限制** —— 這既是功能也是風險（見〈安全性注意事項〉）。

**結論**：機關常見的委外 Java／PHP 服務，多半走不了 sd_notify 這條路。
這正是下一節「健康檢查 timer」存在的理由，而不是「因為比較簡單」。

### 第二層防線之二：健康檢查 timer（不需要改程式碼）

一支 oneshot service + 一支 timer，從**外面**看服務還能不能用：

```ini
# /etc/systemd/system/apply-api-health.service
[Unit]
Description=apply-api 健康檢查（liveness，會驅動重啟）
# ★★★ oneshot 不接受 Restart=always/on-success；重試交給 timer 的下一次觸發

[Service]
Type=oneshot
ExecStart=/usr/local/bin/svc-health-check.sh apply-api 3000
OnFailure=alert@apply-api-health.service
```

timer 的語法與 `list-timers` 判讀見 [[020-02-02-02-cmd-systemd-timer與cron選型]]，這裡只給檔案與設計理由：

```ini
# /etc/systemd/system/apply-api-health.timer
[Unit]
Description=每分鐘檢查一次 apply-api

[Timer]
OnBootSec=2min            # ★★★ 開機後給服務兩分鐘暖機，否則開機當下就被判死
OnUnitActiveSec=1min
AccuracySec=5s

[Install]
WantedBy=timers.target
```

檢查腳本必須有的**三個設計**，缺一個就會出事：

```bash
#!/bin/bash
# /usr/local/bin/svc-health-check.sh  —— liveness 檢查，會驅動重啟
set -euo pipefail

SVC="${1:?用法: svc-health-check.sh <服務名> <埠>}"
PORT="${2:?缺少埠號}"
STATE_DIR=/run/svc-health
BUDGET=3                                   # ★★★★ 設計①：重啟預算
MAINT_FLAG="/run/maintenance/${SVC}"

mkdir -p "$STATE_DIR"
FAILFILE="${STATE_DIR}/${SVC}.fails"

# ★★★★ 設計③：維護旗標 —— 部署期間跳過，否則部署到一半被健康檢查重啟
if [[ -e "$MAINT_FLAG" ]]; then
  logger -t svc-health "[$SVC] 維護模式，跳過檢查"
  exit 0
fi

# ★★★★ 設計②：liveness 用「淺檢查」—— 只問「你自己還在嗎」
#        絕對不要在這裡檢查資料庫連線（那是 readiness，只該驅動告警）
if curl -sf --max-time 5 -o /dev/null "http://127.0.0.1:${PORT}/healthz"; then
  : > "$FAILFILE"                          # healthy：計數歸零
  exit 0
fi

FAILS=$(( $(cat "$FAILFILE" 2>/dev/null || echo 0) + 1 ))
echo "$FAILS" > "$FAILFILE"

if (( FAILS > BUDGET )); then
  # 預算用完：不要再重啟了，改成叫人（無限重啟解決不了資料庫掛掉）
  logger -t svc-health -p daemon.err "[$SVC] 連續 ${FAILS} 次健康檢查失敗，已停止自動重啟，請人工介入"
  exit 1                                   # 讓 OnFailure= 接手告警
fi

logger -t svc-health -p daemon.warning "[$SVC] 健康檢查失敗（第 ${FAILS}/${BUDGET} 次），執行重啟"
systemctl restart "${SVC}.service"
```

> [!danger] ★★★★ liveness 與 readiness 一定要分開
> **反例**：健康檢查端點順便查「連不連得到資料庫」，檢查失敗就 `systemctl restart`。
> 資料庫做三十分鐘維護時，**所有前端每分鐘被重啟一次**，
> 每次重啟又建立一批新連線，connection 風暴讓資料庫更起不來 —— 你親手把「一個服務不可用」升級成「全站雪崩」。
>
> | 檢查類型 | 問什麼 | 失敗時該做什麼 |
> | --- | --- | --- |
> | ★★★★ liveness（淺） | 程序活著嗎？埠有回應嗎？event loop 沒卡死嗎？ | **可以重啟** |
> | ★★★★ readiness（深） | 連得到 DB／Redis／上游 API 嗎？ | **只發告警，絕對不要重啟** |
>
> 端點本身該回什麼、外部平台怎麼探測，屬於 [[100-01-04-guide-日誌-健康檢查與可用性監控]]；
> 容器情境的等價設計見 [[050-02-02-04-guide-Compose-網路與健康檢查]]。

### 第三層防線：OnFailure= 告警單元

`OnFailure=` 是 `[Unit]` 區段的設定，指向「本 unit 進入 failed 時要啟動哪些 unit」。
標準做法是配一個 template：

```ini
# 在被監控的服務的 drop-in 裡
[Unit]
OnFailure=alert@%n.service        # ★★★ %n = 完整 unit 名（含 .service）
```

```ini
# /etc/systemd/system/alert@.service
[Unit]
Description=服務失敗告警：%I

[Service]
Type=oneshot
# ★★★★ %I 是「還原跳脫」後的實例名；%i 是跳脫過的版本（會看到 \x2d 之類的東西）
ExecStart=/usr/local/bin/svc-alert.sh "%I"
EnvironmentFile=-/etc/svc-alert.env      # 640，放 webhook token
TimeoutStartSec=30                       # ★★★ 告警腳本卡住不能拖著 job 不放
```

> [!warning] ★★★★ `%i` 與 `%I` 的差別會讓你的告警看不懂
> `OnFailure=alert@%n.service` 傳進去的是 `apply-worker@notify.service`，
> 其中的 `@` 與特殊字元會被跳脫。在 template 內：
> - `%i` → `apply\x2dworker@notify.service`（**告警訊息裡出現 `\x2d` 就是踩到這個**）
> - `%I` → `apply-worker@notify.service` ✔
>
> 需要在腳本裡自己還原時：
> ```bash
> systemd-escape -u 'apply\x2dworker@notify.service'
> ```
> 預期輸出：
> ```text
> apply-worker@notify.service
> ```

> [!danger] ★★★★ `OnFailure=` 的觸發邊界（這決定了它補不補得到洞）
> | 情境 | 會不會觸發 `OnFailure=` | 說明 |
> | --- | --- | --- |
> | 服務崩潰、`Restart=` 已用盡、進 failed | ✔ | 正常的告警路徑 |
> | 撞到 StartLimit（`start-limit-hit`） | ✔ | 也是 failed |
> | ★★★★ 一直重啟但每次都勉強起得來 | **✘** | 從沒進過 failed，**永遠不告警** ← 本篇最大的洞 |
> | 手動 `systemctl stop` | ✘ | 這是對的，維護時不該吵人 |
> | ★★★ `RestartMode=direct`（v254+）自動重啟 | ✘ | 官方明文：direct 模式跳過 `OnSuccess=`／`OnFailure=` |
>
> 結論：**`Restart=` + `StartLimit*` + `OnFailure=` 必須當成一組一起設計。**
> 只有讓服務「會撞到上限」，`OnFailure=` 才有機會被觸發。
> 而「一直重啟卻沒撞上限」那一格，要靠下一節的 `NRestarts` 巡檢補。

順帶兩個相關設定：

| 設定 | 說明 | 星級 |
| --- | --- | --- |
| `OnSuccess=`（v249+） | unit 進入 inactive 時啟動指定 unit；備份成功回報常用 | ★★ |
| `OnFailureJobMode=` | 預設 `replace`；設 `isolate` 時只能列一個 unit。**幾乎不需要動** | ★ |

### 告警腳本的六個必要元素

```bash
#!/bin/bash
# /usr/local/bin/svc-alert.sh —— 由 alert@.service 呼叫
set -euo pipefail

UNIT="${1:?用法: svc-alert.sh <unit名>}"
UNIT="$(systemd-escape -u "$UNIT")"          # ①★★★ 還原跳脫，避免訊息裡出現 \x2d
HOST="$(hostname -f 2>/dev/null || hostname)"
LOCKDIR=/run/svc-alert
DEDUP_SEC=300                                # ②★★★ 五分鐘去重

mkdir -p "$LOCKDIR"
STAMP="${LOCKDIR}/$(printf '%s' "$UNIT" | tr -c 'A-Za-z0-9_.@-' '_').last"

# ②★★★★ 去重限流：資料庫掛掉時 30 個服務同時 failed，不要發 30 封
now=$(date +%s)
if [[ -f "$STAMP" ]] && (( now - $(cat "$STAMP") < DEDUP_SEC )); then
  logger -t svc-alert "[$UNIT] 五分鐘內已告警過，略過"
  exit 0
fi
echo "$now" > "$STAMP"

# ③★★★ 蒐集現場：狀態、退出碼、重啟次數
read -r RESULT STATUS NRESTARTS <<<"$(
  systemctl show "$UNIT" -p Result,ExecMainStatus,NRestarts --value | tr '\n' ' '
)"
TAIL="$(journalctl -u "$UNIT" -n 20 --no-pager -o short-iso 2>/dev/null || echo '(無法取得 journal)')"

MSG="[systemd-failed] host=${HOST} unit=${UNIT} result=${RESULT} exit=${STATUS} restarts=${NRESTARTS}"

# ④★★★★ 管道一：logger → rsyslog → SIEM（最穩、有稽核軌跡，見 [[090-05-09-guide-資安設備-日誌集中與SIEM]]）
logger -t svc-alert -p daemon.err "$MSG"
printf '%s\n' "$TAIL" | logger -t svc-alert -p daemon.info

# ⑤★★★ 管道二：webhook（Token 來自 640 的 EnvironmentFile，不要寫死在 unit）
if [[ -n "${ALERT_WEBHOOK:-}" ]]; then
  # ⑥★★★★ 自身要有 timeout：告警腳本卡住會佔著 systemd 的 job
  timeout 10 curl -sS -m 8 -X POST "$ALERT_WEBHOOK" \
    -H 'Content-Type: application/json' \
    --data "$(printf '{"text":%s}' "$(printf '%s\n\n%s' "$MSG" "$TAIL" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")" \
    >/dev/null || logger -t svc-alert -p daemon.err "[$UNIT] webhook 送出失敗"
fi
exit 0
```

### 「一直重啟卻沒人知道」的主動巡檢

補 `OnFailure=` 補不到的那一格。一支 timer 每 15 分鐘掃全機，比**差值**不比絕對值：

```bash
#!/bin/bash
# /usr/local/bin/restart-storm-watch.sh
set -euo pipefail

SNAP=/var/lib/restart-storm/last.snapshot
THRESHOLD=5                       # 15 分鐘內新增 5 次重啟就算風暴
mkdir -p "$(dirname "$SNAP")"

# ★★★ template 的實例要逐一掃，所以用 list-units 展開，不能只看樣板檔
mapfile -t UNITS < <(systemctl list-units --type=service --state=running,failed \
                       --no-legend --plain | awk '{print $1}')

TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
for u in "${UNITS[@]}"; do
  n="$(systemctl show "$u" -p NRestarts --value 2>/dev/null || echo 0)"
  printf '%s %s\n' "$u" "${n:-0}" >> "$TMP"
done

if [[ -f "$SNAP" ]]; then
  while read -r unit now; do
    prev="$(awk -v u="$unit" '$1==u {print $2}' "$SNAP")"
    [[ -z "${prev:-}" ]] && continue
    # ★★★★ reset-failed 與重新 start 會把 NRestarts 歸零 → 差值可能是負的，直接跳過
    (( now < prev )) && continue
    delta=$(( now - prev ))
    if (( delta >= THRESHOLD )); then
      logger -t restart-storm -p daemon.err \
        "MESSAGE_ID=8c9d1e2f3a4b5c6d7e8f9a0b1c2d3e4f unit=${unit} delta=${delta} total=${now} 重啟風暴"
    fi
  done < "$TMP"
fi
cp -f "$TMP" "$SNAP"

# 順帶把 failed 清單也送一份（這一份跟 OnFailure= 重複，但可抓到 OnFailure 沒設到的 unit）
if failed="$(systemctl list-units --state=failed --no-legend --plain)" && [[ -n "$failed" ]]; then
  printf '%s\n' "$failed" | logger -t restart-storm -p daemon.err
fi
```

```bash
# 手動跑一次看看
sudo /usr/local/bin/restart-storm-watch.sh && sudo journalctl -t restart-storm -n 5 --no-pager
```

預期輸出：

```text
Aug 28 14:00:03 srv restart-storm[4711]: MESSAGE_ID=8c9d... unit=apply-api.service delta=29 total=2873 重啟風暴
```

> [!tip] ★★★ 為什麼一定要比差值
> `systemctl reset-failed` 與服務重新 `start` 都會讓 `NRestarts` **歸零**。
> 比絕對值的告警會在每次維護後基準漂移，然後你會開始「習慣性忽略」這個告警 —— 那就等於沒有。

### 告警真的送得出去嗎（機關現實）

| 管道 | 可靠度 | 適用 | 注意事項 | 星級 |
| --- | --- | --- | --- | --- |
| ★★★★ `logger` → rsyslog → SIEM／Wazuh | 最高 | 所有機關環境 | 有稽核軌跡、離線也留得住；用固定 tag 或 `MESSAGE_ID=` 讓規則好寫 | ★★★★ |
| webhook（Teams／n8n） | 中 | 有對外或內部 API 可達時 | ★★★★ Token **不可**寫在 unit 的 `Environment=`（`systemctl show` 任何人都看得到），要放 640 的 `EnvironmentFile=` | ★★★★ |
| SNMP trap | 中 | 機房既有網管平台 | 需要 `snmptrap` 與既有 OID 規劃，跟網管單位確認 | ★★ |
| ★★★★ 本機 MTA（`sendmail`／`MAILTO`） | **最低** | 幾乎不能單獨依賴 | 機關主機的 MTA 十有八九沒裝、沒設或被防火牆擋在外面 | ★★★★ |

> [!danger] ★★★★ 上線前一定要做的一件事
> 設了 `OnFailure=` 卻**從來沒收過任何一則**，是本篇最常見的「假安全」。上線前務必實測：
> ```bash
> sudo systemctl start alert@test.service
> sudo journalctl -t svc-alert -n 10 --no-pager
> ```
> 預期輸出：
> ```text
> Aug 28 14:22:10 srv svc-alert[5120]: [systemd-failed] host=srv unit=test result=... restarts=...
> ```
> **而且要到 SIEM／Teams 那一端真的看到訊息才算完成**，看到 journal 只代表腳本跑起來了。

> [!warning] ★★★ 這一層的天花板
> 整台機器當掉、網路斷掉、電力中斷時，`Restart=`、`WatchdogSec=`、`OnFailure=` **一封都發不出去**。
> 主機自帶的自動復原是**最後一道防線，不是唯一一道** ——
> 一定要有從機器外面看的探測（見 [[100-01-03-guide-日誌-系統監控與告警]] 與 [[100-01-04-guide-日誌-健康檢查與可用性監控]]）。

### 兩個邊界情況

**(a) 記憶體洩漏型重啟迴圈**

```ini
[Service]
MemoryMax=2G            # 超過就 OOM kill（SIGKILL = 非乾淨訊號）
OOMPolicy=stop          # ★★★ v243+：預設 stop；kill 會連整個 cgroup 一起殺
Restart=on-failure
RestartSec=10
```

洩漏型服務的典型循環是：跑 6 小時 → 記憶體到頂 → OOM kill → Restart → 再跑 6 小時。
`Restart=` 讓它看起來「很穩」，實際上每天悄悄重啟四次，**進行中的請求全部丟掉**。

```bash
journalctl -u apply-api.service --since -1d | grep -i 'oom\|out of memory' | wc -l
```

預期輸出：

```text
4        # ★★★★ 一天四次 OOM = 有洩漏，重啟只是止血
```

> [!warning] ★★★ 處置原則
> 「用排程重啟壓住記憶體洩漏」是**止血，不是修好**。可以做，但必須：
> 1. 在變更紀錄裡寫明「此為暫時性緩解措施」與追蹤到期日（見 [[100-02-08-guide-維運-變更管理流程]]）。
> 2. 保留一次 OOM 當下的 heap dump／`systemd-cgtop` 觀測資料給廠商。
> 3. 排程重啟排在離峰、並先摘出負載平衡（做法見 [[130-01-06-guide-部署-部署自動化]]）。
>
> 另有 `systemd-oomd`（依 PSI 壓力主動殺 cgroup）可用，但它的判準是**整機記憶體壓力**而非單一服務，
> 在單一用途主機上可能反而先殺到你要保的服務，機關共用主機啟用前要實測。

**(b) 服務 watchdog ≠ 硬體 watchdog**

| 項目 | 服務 watchdog | 硬體 watchdog |
| --- | --- | --- |
| 設定位置 | unit 的 `WatchdogSec=` | `/etc/systemd/system.conf` 的 `RuntimeWatchdogSec=` |
| 監看誰 | 單一服務有沒有送心跳 | **PID 1／整個 kernel 有沒有卡死** |
| 觸發後果 | 殺掉該服務（SIGABRT）並依 `Restart=` 拉起 | ★★★★★ **直接硬重開整台機器** |
| 依賴 | `sd_notify` | `/dev/watchdog0` 裝置（`WatchdogDevice=` 可指定） |
| 預設 | 0（關閉） | `RuntimeWatchdogSec=` 預設 0（關閉）；`RebootWatchdogSec=` 預設 10min |

```bash
ls -l /dev/watchdog* 2>/dev/null || echo "無 watchdog 裝置（虛擬機多半沒有）"
```

預期輸出：

```text
無 watchdog 裝置（虛擬機多半沒有）      # ★★★ PVE/VMware 要在 VM 設定裡加上 watchdog 裝置才會有
```

> [!danger] ★★★★ 開啟硬體 watchdog 前一定要評估
> `RuntimeWatchdogSec=30s` 的意思是「PID 1 若 30 秒內沒餵狗，硬體就重開機」。
> 在**機關共用主機**（一台上面跑五個機關的系統）上，一次誤觸等於同時中斷五個系統，
> 而且是**沒有正常關機程序的硬重開**，有檔案系統損毀風險。
> 建議只在「單一用途、有帶外管理（iDRAC／iLO）可救、且已實測過」的機器上啟用。
> 開機流程層級的救援手段見 [[020-01-25-guide-Linux-開機流程與GRUB救援]]，核心參數見 [[020-01-26-guide-Linux-核心模組與sysctl調校]]。

### ★★★★★ 絕對不要順手設的：StartLimitAction= / FailureAction=

```ini
[Unit]
StartLimitAction=reboot-force     # ★★★★★ 服務撞上限 → 強制重開整台機器
FailureAction=reboot-force        # ★★★★★ 服務 failed → 強制重開整台機器
```

官方（`systemd.unit(5)`）對這幾個值的說明：`reboot` 走正常關機程序；
`reboot-force` **強制終止所有程序**（等同 `systemctl reboot -f`）；
`reboot-immediate` **直接呼叫 `reboot(2)`，可能造成資料遺失**（等同 `systemctl reboot -ff`）。

> [!danger] ★★★★★ 為什麼機關情境幾乎都不該用
> - **一台主機通常跑不只一個系統**。申辦系統的 worker 撞上限 → 整台重開 →
>   同一台上的公文系統、報表系統、資料庫全部一起斷線。**一個系統拖垮五個系統。**
> - `reboot-force` / `reboot-immediate` **不做正常關機程序**，資料庫沒有 flush 的機會，
>   有檔案系統損毀與資料遺失風險。
> - 如果根因是「設定檔錯誤」，重開機**不會修好它** —— 你得到的是**無限重開機迴圈**，
>   而且開機時間短到你來不及 SSH 進去改，只能靠實體／帶外管理救。
>
> **唯一可考慮的例外**：單一用途的 appliance（例如專職的網路探針），
> 且**確認有帶外管理（iDRAC／iLO／實體 console）可以救**，並經過變更審查。
> 一般伺服器請一律留在預設值 `none`，靠 `OnFailure=` 叫人來看。

---

## 完整實戰範例

### 情境：某局處線上申辦系統的自動復原全面體檢與補強

**事故經過**

```text
週五 22:10  資料庫連線池耗盡
週五 22:10  apply-api.service（Node 後端）開始崩潰
            設定：Restart=always、RestartSec 用預設 100ms、完全沒設 StartLimit
            → 每 0.1 秒重啟一次，一夜約 30 萬次
            → journal 寫入 12 GB，星期六凌晨把 /var 灌滿
週五 22:40  apply-worker@notify.service（Laravel 佇列 worker）
            因為當天下午改壞的設定檔以退出碼 78 退出
            → 撞上限進 failed，整個週末沒有任何人知道
            → 補件通知信兩天沒發出去
週一 08:50  民眾打 1999 陳情「我上週五補件到現在沒收到通知」

事後查證：三個服務（apply-api、apply-worker@、php8.3-fpm）
          沒有任何一個設了 OnFailure=；健康檢查靠人工每天早上點網頁確認。
```

**要補的東西**：三層防線全部，一支腳本裝完，可回滾。

### 主腳本

```bash
#!/bin/bash
# /usr/local/bin/setup-service-recovery.sh
# 用途：為線上申辦系統的三個服務建立三層自動復原防線
# 用法：sudo setup-service-recovery.sh
set -euo pipefail

TARGETS=(apply-api.service apply-worker@notify.service php8.3-fpm.service)
BACKUP_DIR="/var/backups/service-recovery/$(date +%Y%m%d-%H%M%S)"
DROPIN_TAG="99-recovery.conf"          # ★★★ 固定檔名，回滾時好找
ALERT_ENV=/etc/svc-alert.env

log()  { printf '[%(%F %T)T] %s\n' -1 "$*"; }
die()  { printf '[%(%F %T)T] ★ 失敗：%s\n' -1 "$*" >&2; exit 1; }

# ---------- 前置檢查 ----------
preflight() {
  log "=== 前置檢查 ==="
  [[ $EUID -eq 0 ]] || die "請用 sudo 執行"
  command -v systemctl >/dev/null || die "找不到 systemctl"
  local ver; ver="$(systemctl --version | head -1 | awk '{print $2}')"
  log "systemd 版本：${ver}"
  (( ver >= 254 )) && log "  → 支援 RestartSteps=（本腳本仍採固定 RestartSec，跨版本一致）" \
                   || log "  → ★ 低於 254，無 RestartSteps=，採固定 RestartSec + StartLimit 收斂"
  for u in "${TARGETS[@]}"; do
    systemctl cat "$u" >/dev/null 2>&1 || die "unit 不存在：$u（請先確認服務名稱）"
  done
  command -v curl >/dev/null || die "缺少 curl（健康檢查需要）"
}

# ---------- 1. 現況蒐證與備份 ----------
step1_backup() {
  log "=== 1/5 現況蒐證與備份 → ${BACKUP_DIR} ==="
  install -d -m 0750 "$BACKUP_DIR"
  for u in "${TARGETS[@]}"; do
    local safe; safe="$(printf '%s' "$u" | tr '@/' '__')"
    systemctl show "$u" \
      -p Restart,RestartUSec,StartLimitIntervalUSec,StartLimitBurst \
      -p RestartPreventExitStatus,SuccessExitStatus,WatchdogUSec,NRestarts,Result \
      > "${BACKUP_DIR}/${safe}.show" || die "無法讀取 $u 的狀態"
    systemctl cat "$u" > "${BACKUP_DIR}/${safe}.cat" 2>/dev/null || true
    log "  已備份 $u"
  done
  log "  ★ 回滾時用 ${BACKUP_DIR}/*.show 逐項比對"
}

# ---------- 2. drop-in ----------
write_dropin() {                       # $1=unit  $2=額外的 [Service] 行
  local unit="$1" extra="${2:-}" dir="/etc/systemd/system/${unit}.d"
  install -d -m 0755 "$dir"
  cat > "${dir}/${DROPIN_TAG}" <<EOF
# 由 setup-service-recovery.sh 產生，勿手動編輯
# 機制說明見手冊〈服務自動復原與看門狗〉
[Unit]
StartLimitIntervalSec=300
StartLimitBurst=5
OnFailure=alert@%n.service

[Service]
Restart=on-failure
RestartSec=10
RestartPreventExitStatus=78
${extra}
EOF
  chmod 0644 "${dir}/${DROPIN_TAG}"
}

step2_dropins() {
  log "=== 2/5 建立 drop-in ==="
  write_dropin apply-api.service
  write_dropin apply-worker@notify.service 'SuccessExitStatus=143 SIGTERM'
  write_dropin php8.3-fpm.service 'WatchdogSec=30s'
  systemctl daemon-reload || die "daemon-reload 失敗"
  for u in "${TARGETS[@]}"; do
    systemd-analyze verify "$u" 2>&1 | grep -v '^$' && log "  ★ 上面是 $u 的 verify 訊息，請確認" || true
  done
  log "  drop-in 完成"
}

# ---------- 3. 告警 ----------
step3_alert() {
  log "=== 3/5 安裝告警單元 ==="
  [[ -f "$ALERT_ENV" ]] || { printf 'ALERT_WEBHOOK=\n' > "$ALERT_ENV"; }
  chmod 0640 "$ALERT_ENV"; chown root:root "$ALERT_ENV"   # ★★★★ Token 不可全域可讀
  cat > /etc/systemd/system/alert@.service <<'EOF'
[Unit]
Description=服務失敗告警：%I

[Service]
Type=oneshot
ExecStart=/usr/local/bin/svc-alert.sh "%I"
EnvironmentFile=-/etc/svc-alert.env
TimeoutStartSec=30
EOF
  [[ -x /usr/local/bin/svc-alert.sh ]] || die "請先部署 /usr/local/bin/svc-alert.sh 並 chmod 755"
  systemctl daemon-reload
  log "  alert@.service 就緒"
}

# ---------- 4. 健康檢查 ----------
step4_health() {
  log "=== 4/5 安裝健康檢查 timer ==="
  [[ -x /usr/local/bin/svc-health-check.sh ]] || die "請先部署 /usr/local/bin/svc-health-check.sh"
  install -d -m 0755 /run/maintenance
  cat > /etc/systemd/system/apply-api-health.service <<'EOF'
[Unit]
Description=apply-api 健康檢查（liveness）
OnFailure=alert@apply-api-health.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/svc-health-check.sh apply-api 3000
EOF
  cat > /etc/systemd/system/apply-api-health.timer <<'EOF'
[Unit]
Description=每分鐘檢查一次 apply-api

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=5s

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now apply-api-health.timer || die "無法啟用健康檢查 timer"
  log "  健康檢查 timer 已啟用"
}

# ---------- 5. 重啟風暴巡檢 ----------
step5_stormwatch() {
  log "=== 5/5 安裝重啟風暴巡檢 ==="
  [[ -x /usr/local/bin/restart-storm-watch.sh ]] || die "請先部署 /usr/local/bin/restart-storm-watch.sh"
  install -d -m 0750 /var/lib/restart-storm
  cat > /etc/systemd/system/restart-storm-watch.service <<'EOF'
[Unit]
Description=全機重啟風暴巡檢

[Service]
Type=oneshot
ExecStart=/usr/local/bin/restart-storm-watch.sh
EOF
  cat > /etc/systemd/system/restart-storm-watch.timer <<'EOF'
[Unit]
Description=每 15 分鐘巡檢一次

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now restart-storm-watch.timer || die "無法啟用巡檢 timer"
  log "  巡檢 timer 已啟用"
}

# ---------- 驗證 ----------
verify() {
  log "=== 驗證生效值（★★★★ 只信 show，不信 cat）==="
  local bad=0
  for u in "${TARGETS[@]}"; do
    local out; out="$(systemctl show "$u" -p Restart,RestartUSec,StartLimitIntervalUSec,StartLimitBurst --value | tr '\n' ' ')"
    log "  ${u}: ${out}"
    systemctl show "$u" -p StartLimitIntervalUSec --value | grep -q '5min' || { log "  ★ ${u} 的 StartLimitIntervalSec 未生效！"; bad=1; }
  done
  systemctl list-timers --all --no-pager | grep -E 'apply-api-health|restart-storm' || log "  ★ timer 未列出"
  (( bad == 0 )) || die "有設定未生效，請檢查 drop-in 區段是否寫錯（StartLimit* 必須在 [Unit]）"
  log "=== 全部完成。請接著執行驗收檢查表的四種故障注入 ==="
}

preflight; step1_backup; step2_dropins; step3_alert; step4_health; step5_stormwatch; verify
```

```bash
sudo /usr/local/bin/setup-service-recovery.sh
```

預期輸出（節錄）：

```text
[2026-08-28 14:31:02] === 前置檢查 ===
[2026-08-28 14:31:02] systemd 版本：249
[2026-08-28 14:31:02]   → ★ 低於 254，無 RestartSteps=，採固定 RestartSec + StartLimit 收斂
[2026-08-28 14:31:03] === 1/5 現況蒐證與備份 → /var/backups/service-recovery/20260828-143102 ===
...
[2026-08-28 14:31:06]   apply-api.service: on-failure 10s 5min 5
[2026-08-28 14:31:06] === 全部完成。請接著執行驗收檢查表的四種故障注入 ===
```

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 |
| --- | --- | --- | --- |
| 1 | ★★★★ StartLimit 真的生效 | `systemctl show apply-api -p StartLimitIntervalUSec,StartLimitBurst` | `StartLimitIntervalUSec=5min` / `StartLimitBurst=5`（不是 `10s`） |
| 2 | Restart 策略正確 | `systemctl show apply-api -p Restart,RestartUSec` | `Restart=on-failure` / `RestartUSec=10s` |
| 3 | 退出碼排除生效 | `systemctl show apply-api -p RestartPreventExitStatus` | `RestartPreventExitStatus=78` |
| 4 | ★★★★ **崩潰注入** | `sudo systemctl kill -s SIGKILL apply-api` → 等 15 秒 → `systemctl is-active apply-api` | 回 `active`；`NRestarts` +1；**不**發告警（沒進 failed 是正常的） |
| 5 | ★★★★ **崩潰迴圈注入** | 讓應用連續失敗（例如暫時改壞連線設定）→ 觀察 5 分鐘 | 第 5 次後 `Active: failed (Result: start-limit-hit)`，且**收到一則**告警 |
| 6 | ★★★★ 撞上限後被擋 | `sudo systemctl start apply-api` | `Job for apply-api.service failed.`（這是預期行為，不是新故障） |
| 7 | ★★★★ reset-failed 後恢復 | `sudo systemctl reset-failed apply-api && sudo systemctl start apply-api` | 無輸出，`is-active` 回 `active` |
| 8 | ★★★★ **設定錯誤注入** | 讓應用以 78 退出：`sudo systemd-run --unit=t78 /bin/sh -c 'exit 78'` 後查 `systemctl show apply-api -p ExecMainStatus` | 目標服務**不重啟**、直接 `failed`、**立刻**告警 |
| 9 | ★★★★ **假死注入** | `sudo kill -STOP $(systemctl show apply-api -p MainPID --value)` | 一分鐘內健康檢查判定失敗並重啟（或 watchdog 觸發 SIGABRT）；記得事後 `kill -CONT` |
| 10 | 健康檢查重啟預算 | 連續讓 `/healthz` 失敗 4 次 | 第 4 次起**不再重啟**，改送「請人工介入」告警 |
| 11 | ★★★ 維護旗標有效 | `sudo touch /run/maintenance/apply-api` 後看 `journalctl -t svc-health -n 3` | 出現「維護模式，跳過檢查」，服務不被重啟 |
| 12 | ★★★★ **告警管道實測** | `sudo systemctl start alert@test.service` | SIEM／Teams **那一端**真的看到訊息（只看 journal 不算過） |
| 13 | 巡檢 timer 在跑 | `systemctl list-timers restart-storm-watch.timer --no-pager` | `NEXT` 欄有值、`LEFT` 在 15 分鐘內 |
| 14 | 整機健康指標 | `systemctl is-system-running` | `running`（若回 `degraded` 表示還有 unit 卡在 failed） |

### 回滾腳本

```bash
#!/bin/bash
# /usr/local/bin/rollback-service-recovery.sh
# 用法：sudo rollback-service-recovery.sh /var/backups/service-recovery/20260828-143102
set -euo pipefail

BACKUP_DIR="${1:?用法: rollback-service-recovery.sh <備份目錄>}"
TARGETS=(apply-api.service apply-worker@notify.service php8.3-fpm.service)
DROPIN_TAG="99-recovery.conf"

[[ $EUID -eq 0 ]] || { echo "請用 sudo 執行" >&2; exit 1; }
[[ -d "$BACKUP_DIR" ]] || { echo "備份目錄不存在：$BACKUP_DIR" >&2; exit 1; }

echo "=== 1/4 移除 drop-in ==="
for u in "${TARGETS[@]}"; do
  f="/etc/systemd/system/${u}.d/${DROPIN_TAG}"
  [[ -f "$f" ]] && { rm -f "$f"; echo "  已移除 $f"; }
  rmdir --ignore-fail-on-non-empty "/etc/systemd/system/${u}.d" 2>/dev/null || true
done

echo "=== 2/4 停用並移除 timer 與告警單元 ==="
for t in apply-api-health.timer restart-storm-watch.timer; do
  systemctl disable --now "$t" 2>/dev/null || true
done
rm -f /etc/systemd/system/apply-api-health.{service,timer} \
      /etc/systemd/system/restart-storm-watch.{service,timer} \
      /etc/systemd/system/alert@.service

echo "=== 3/4 daemon-reload 與 reset-failed ==="
systemctl daemon-reload
systemctl reset-failed          # ★★★★ 不做這步，先前撞上限的服務會 start 不起來

echo "=== 4/4 比對是否回到變更前的值 ==="
rc=0
for u in "${TARGETS[@]}"; do
  safe="$(printf '%s' "$u" | tr '@/' '__')"
  before="${BACKUP_DIR}/${safe}.show"
  [[ -f "$before" ]] || { echo "  ★ 找不到 $before，略過比對"; continue; }
  now="$(mktemp)"
  systemctl show "$u" -p Restart,RestartUSec,StartLimitIntervalUSec,StartLimitBurst \
    -p RestartPreventExitStatus,SuccessExitStatus,WatchdogUSec > "$now"
  if diff <(grep -E '^(Restart|StartLimit|Success|Watchdog)' "$before") \
          <(grep -E '^(Restart|StartLimit|Success|Watchdog)' "$now") >/dev/null; then
    echo "  ✔ $u 已回到變更前"
  else
    echo "  ★ $u 與變更前不同："; diff "$before" "$now" || true; rc=1
  fi
  rm -f "$now"
done
exit "$rc"
```

```bash
sudo /usr/local/bin/rollback-service-recovery.sh /var/backups/service-recovery/20260828-143102
```

預期輸出（節錄）：

```text
=== 4/4 比對是否回到變更前的值 ===
  ✔ apply-api.service 已回到變更前
  ✔ apply-worker@notify.service 已回到變更前
  ✔ php8.3-fpm.service 已回到變更前
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 用 `kill <pid>` 測試 `Restart=on-failure`，服務沒重啟，於是改成 `Restart=always` | `kill` 預設送 **SIGTERM，屬於乾淨退出**，`on-failure` 本來就不重啟 —— 設定是對的，測試方法錯了 | 改用 `systemctl kill -s SIGKILL <unit>` 驗證；把 `always` 改回 `on-failure`，否則設定檔錯誤會被無限重啟 |
| ★★★★★ 設了 `StartLimitAction=reboot-force`，一支 worker 掛掉害整台機器重開，且進入重開機迴圈 | 服務層失敗被升級成整機動作，而根因（設定檔錯）重開機修不好 | 立即改回 `StartLimitAction=none`（若已進迴圈，需從 GRUB 進 rescue 或帶外管理，見 [[020-01-25-guide-Linux-開機流程與GRUB救援]]） |
| ★★★★ `systemctl start` 一直回 `Job for x.service failed`，但設定檔明明已修好 | 撞過 StartLimit，rate limit 計數器沒清 | `sudo systemctl reset-failed <unit>` 之後再 start；並把這行寫進部署腳本與交接文件 |
| ★★★★ unit 檔裡明明寫了 `StartLimitIntervalSec=300`，卻還是 10 秒就撞上限 | 寫在 `[Service]` 區段（應在 `[Unit]`）。實測 systemd 259：`StartLimitIntervalSec=` 會有 `Unknown key` 警告，`StartLimitBurst=` **連警告都沒有** | `systemctl show <unit> -p StartLimitIntervalUSec,StartLimitBurst` 看生效值；把兩行移到 `[Unit]` 後 `daemon-reload` |
| ★★★★ 服務一整晚每 30 秒重啟一次，`systemctl status` 卻顯示 `active (running)`，沒有任何告警 | `RestartSec` 大於 `StartLimitIntervalSec`，永遠撞不到上限 → 不會 failed → `OnFailure=` 不觸發 | 調成 `RestartSec × (Burst−1) < IntervalSec`（建議 10／300／5）；加上 `NRestarts` 巡檢 |
| ★★★★ `/var` 被寫滿，`df` 顯示 journal 佔 12 GB | 重啟迴圈把每次啟動失敗都寫進 journal | 止血：`sudo journalctl --vacuum-size=500M`；根因：先收斂重啟策略；輪替設定見 [[020-01-19-guide-Linux-日誌系統]] |
| ★★★★ 設了 `WatchdogSec=30s` 之後，服務每 30 秒被 SIGABRT 一次然後就停在那裡 | 應用根本沒送 `WATCHDOG=1`，而且沒設 `Restart=`（或設成 `no`） | 改不了程式碼就**移除 `WatchdogSec=`**、改用健康檢查 timer；能改就補心跳，並確認 `Restart=on-failure` |
| ★★★★ 資料庫維護三十分鐘，期間所有前端被反覆重啟，資料庫更起不來 | 健康檢查用了「連得到 DB」這種 readiness 深檢查去驅動重啟 | 淺檢查（`/healthz` 只回自身狀態）驅動重啟，深檢查只發告警；並加維護旗標 |
| ★★★★ 設了 `OnFailure=` 半年，一則告警也沒收過 | 告警管道走本機 MTA，而 MTA 沒裝／沒設／被防火牆擋 | 改走 `logger` → rsyslog → SIEM；上線前用 `systemctl start alert@test.service` 實測到「那一端」收到 |
| ★★★ 部署到一半服務被重啟，部署腳本失敗 | 健康檢查 timer 在部署期間把「還沒起來」判定成掛掉 | 部署前 `touch /run/maintenance/<svc>`、部署後 `rm`；腳本首行檢查旗標（見本篇健康檢查腳本） |
| ★★★ 告警訊息裡的 unit 名長成 `apply\x2dworker@notify.service` | template 內用了 `%i`（跳脫過）而不是 `%I` | 改用 `%I`，或在腳本內 `systemd-escape -u` 還原 |
| ★★★ 資料庫掛掉的當下，五分鐘內收到三十封告警信 | 沒有去重限流，三十個相依服務同時 failed | 告警腳本加時間戳去重（本篇 `svc-alert.sh` 的 `DEDUP_SEC`）與 `flock`（用法見 [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]]） |
| ★★★ 每天固定重啟四次，看起來很穩定但偶爾掉請求 | 記憶體洩漏 + `MemoryMax=` 觸發 OOM kill → `Restart=` 自動復原 | `journalctl -u <unit> \| grep -i oom` 確認；重啟只是止血，要開變更單追蹤根因 |
| ★★★ worker 每次部署 `systemctl restart` 後都被記成一次失敗 | worker 收到 SIGTERM 後以 143 退出，被當成非 0 失敗 | `SuccessExitStatus=143 SIGTERM` |
| ★★ oneshot 的健康檢查 unit 加了 `Restart=always`，`daemon-reload` 後服務起不來 | 官方明文：`Type=oneshot` 拒絕 `always` 與 `on-success` | 移除 `Restart=`，重試交給 timer 的下一次觸發 |

### 排查步驟

**【1】先確認「它現在到底是什麼狀態」**

```bash
systemctl status apply-api.service --no-pager | head -8
```

預期輸出：

```text
     Active: failed (Result: start-limit-hit) since ...
```

看到 `Result: start-limit-hit` → 跳【2】。
看到 `Result: exit-code` → 跳【3】。
看到 `active (running)` 但你覺得它有問題 → 跳【4】。
看到 `Result: watchdog` → 跳【6】。

**【2】撞上限：先確認是不是設定太急**

```bash
systemctl show apply-api.service -p RestartUSec,StartLimitIntervalUSec,StartLimitBurst
```

預期輸出：

```text
RestartUSec=100ms
StartLimitIntervalUSec=10s
StartLimitBurst=5          # ★★★★ 三個都是預設值 = 你以為設了但沒生效，或根本沒設
```

三個都是預設值 → 你的設定寫錯區段或寫在不會被讀到的檔案，回頭看〈寫錯區段不會報錯〉。
數值是你設的 → 代表根因是真的修不好，跳【3】找退出碼。

**【3】找出「為什麼掛」的退出碼**

```bash
journalctl -u apply-api.service -n 30 --no-pager | grep -iE 'main process exited|failed with result'
```

預期輸出：

```text
systemd[1]: apply-api.service: Main process exited, code=exited, status=78/CONFIG
systemd[1]: apply-api.service: Failed with result 'exit-code'.
```

`78/CONFIG`、`1/FAILURE` 且每次都一樣 → **設定檔或環境問題，重啟無效**，
修根因後 `reset-failed` 再 start，並考慮把該退出碼加入 `RestartPreventExitStatus=`。
`code=killed, status=9/KILL` → 被 SIGKILL，跳【5】確認是不是 OOM。

**【4】看起來 active，但實際上一直在重啟**

```bash
systemctl show apply-api.service -p NRestarts,ActiveEnterTimestamp
journalctl -u apply-api.service --since -1h | grep -c 'Scheduled restart job'
```

預期輸出：

```text
NRestarts=2873
ActiveEnterTimestamp=Sat 2026-08-28 14:04:31 CST
118
```

`NRestarts` 很大且 `ActiveEnterTimestamp` 是「剛剛」→ 確診無限重啟。
先看【2】的三個參數比值（多半是 `RestartSec` > `IntervalSec`），再看【3】的退出碼。

**【5】確認是不是被記憶體打死的**

```bash
journalctl -u apply-api.service --since -1d | grep -iE 'out of memory|oom-kill|memory limit'
systemctl show apply-api.service -p MemoryMax,MemoryPeak,OOMPolicy
```

預期輸出：

```text
systemd[1]: apply-api.service: A process of this unit has been killed by the OOM killer.
MemoryMax=2147483648
OOMPolicy=stop
```

有 OOM 記錄 → 是洩漏或限額太低，見〈記憶體洩漏型重啟迴圈〉；**不要用調大 `RestartSec` 來掩蓋**。

**【6】watchdog 被觸發：先確認應用到底有沒有在送心跳**

```bash
systemctl show apply-api.service -p WatchdogUSec,NotifyAccess,Type,Restart
journalctl -u apply-api.service | grep -i watchdog | tail -5
```

預期輸出：

```text
WatchdogUSec=30s
NotifyAccess=main
Type=notify
Restart=on-failure
systemd[1]: apply-api.service: Watchdog timeout (limit 30s)!
```

`Restart=no` → ★★★★ 假死後會就地停機，立刻補上 `Restart=on-failure`。
應用其實沒實作心跳（每 30 秒準時觸發一次）→ 移除 `WatchdogSec=`，改健康檢查 timer。

**【7】確認告警到底有沒有被觸發過**

```bash
journalctl -t svc-alert --since -7d --no-pager | tail -10
systemctl show apply-api.service -p OnFailure
```

預期輸出：

```text
OnFailure=alert@apply-api.service          # ★★★ 空的代表根本沒設，第三層防線不存在
```

`OnFailure=` 有設、但 `svc-alert` 完全沒有紀錄 → 服務從沒進過 failed（見【4】的無限重啟），
或告警腳本本身失敗：`systemctl status alert@apply-api.service` 看它的退出碼。

**【8】最後掃一次整機，確認沒有別的 unit 也在安靜地死**

```bash
systemctl is-system-running; systemctl --failed --no-legend
sudo /usr/local/bin/restart-storm-watch.sh; journalctl -t restart-storm -n 10 --no-pager
```

預期輸出：

```text
degraded
apply-worker@notify.service loaded failed failed 補件通知佇列 worker
Aug 28 15:02:11 srv restart-storm[6001]: MESSAGE_ID=8c9d... unit=php8.3-fpm.service delta=7 ...
```

`degraded` → 至少還有一個 unit 在 failed，逐一回到【1】處理。事故的分級與通報見 [[100-02-09-svc-維運-事件處理與升級流程]]，
排查方法論見 [[100-02-10-guide-維運-故障排除方法論]]。

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對不要做的事
> 1. **`StartLimitAction=reboot-force` / `FailureAction=reboot-force`（或 `-immediate`）**
>    一支服務失敗就強制重開整台機器。共用主機上等於一個系統拖垮五個系統；
>    `-force` / `-immediate` 不做正常關機程序，**有檔案系統損毀與資料遺失風險**；
>    若根因是設定檔錯誤，你得到的是無限重開機迴圈。
> 2. **把 webhook Token 寫在 unit 的 `Environment=`。**
>    `systemctl show <unit> -p Environment` **任何本機使用者都讀得到**，
>    `journalctl` 也可能記到。一律放 `EnvironmentFile=`，權限 `640`、`root:root`。
>    ```bash
>    sudo chmod 640 /etc/svc-alert.env && sudo chown root:root /etc/svc-alert.env
>    ```
> 3. **把應用日誌或請求內容整段塞進告警訊息。**
>    線上申辦系統的 journal 裡可能有身分證字號、地址、電話。
>    告警只送 unit 名、`Result`、退出碼、`NRestarts` 與**經過確認不含個資**的最後幾行，
>    寧可讓值班人員自己上機器看，也不要把個資推到 Teams 群組或外部 webhook。
> 4. **在還沒確認有帶外管理（iDRAC／iLO）的機器上啟用硬體 watchdog。**
>    `RuntimeWatchdogSec=` 誤觸會直接硬重開，沒有 console 就只能請人跑機房。

> [!warning] ★★★★ 權限與稽核
> - **告警腳本以 root 執行**（`alert@.service` 由 PID 1 啟動）。因此
>   `/usr/local/bin/svc-alert.sh` 必須是 `root:root 0755` —— 若目錄或檔案可被一般使用者寫入，
>   等於把 root 執行權送出去。上線前檢查：
>   ```bash
>   find /usr/local/bin -maxdepth 1 -name 'svc-*.sh' -o -name 'restart-storm-watch.sh' | xargs ls -l
>   ```
>   預期輸出：
>   ```text
>   -rwxr-xr-x 1 root root 2143 Aug 28 14:30 /usr/local/bin/svc-alert.sh
>   ```
> - ★★★ `systemd-notify --pid=<PID>` 在**有權限**的情況下可以繞過 `NotifyAccess=main`／`exec` 限制
>   （官方 `systemd-notify(1)` 明文）。不要把可寫的腳本放進 `ExecStartPost=` 讓一般使用者有機會插手。
> - **所有 drop-in 與腳本納入 git 版控**，並在變更紀錄寫清楚「為什麼把 `RestartSec` 從 X 改成 Y」。
>   自動復原參數是稽核時會被問「誰改的、為什麼」的項目（見 [[100-02-08-guide-維運-變更管理流程]]）。
> - **維護旗標檔要能自動失效。** `/run/maintenance/<svc>` 放在 tmpfs，重開機自動消失是刻意設計；
>   但部署腳本仍必須用 `trap` 確保異常中斷時也會清掉，否則健康檢查會被永久停用而沒人發現。

> [!warning] ★★★ 個資與稽核軌跡（機關情境）
> 自動重啟會中斷進行中的交易。線上申辦系統若在民眾送出申請的瞬間被健康檢查重啟，
> 可能造成「民眾以為送出了、系統沒收到」的爭議。因此：
> - 重啟事件必須**留下可稽核的紀錄**（`logger` 打進 syslog 並集中到 SIEM，見 [[090-05-09-guide-資安設備-日誌集中與SIEM]]）。
> - 健康檢查的重啟預算不要設太大 —— 反覆重啟等於反覆中斷交易。
> - 重啟時間點與筆數要能對得上應用層的交易紀錄，事後才有辦法回覆陳情。

---

## 速查表

**判斷準則（先看這張）**

| 情況 | 該怎麼做 | 星級 |
| --- | --- | --- |
| 一般網路服務 | `Restart=on-failure` + `RestartSec=10` + `[Unit]` 的 `300`/`5` + `OnFailure=` | ★★★★ |
| 不確定要不要用 `always` | **不要用**，除非你確定「乾淨退出也該重啟」 | ★★★★ |
| 服務會假死、且**可以改程式碼** | `WatchdogSec=` + `Restart=on-failure` | ★★★★ |
| 服務會假死、但**改不了程式碼** | 健康檢查 timer（淺檢查 + 重啟預算 + 維護旗標） | ★★★★ |
| 深度檢查（連得到 DB） | **只發告警，不要重啟** | ★★★★ |
| 想讓整機失敗就重開機 | 幾乎永遠是錯的，留在 `StartLimitAction=none` | ★★★★★ |

**核心設定項**

| 設定項 | 區段 | 預設 | 說明 | 星級 |
| --- | --- | --- | --- | --- |
| `Restart=` | `[Service]` | `no` | 七種模式，見矩陣表 | ★★★★ |
| `RestartSec=` | `[Service]` | `100ms` | ★★★★ 正式服務一律調成 `10` 以上 | ★★★★ |
| `RestartSteps=` / `RestartMaxDelaySec=` | `[Service]` | `0` / `infinity` | 指數退避，**需 systemd v254+** | ★★★ |
| `RestartPreventExitStatus=` | `[Service]` | 空 | 這些退出碼一律不重啟（如 `78`） | ★★★★ |
| `RestartForceExitStatus=` | `[Service]` | 空 | 這些退出碼一律重啟 | ★★ |
| `SuccessExitStatus=` | `[Service]` | 空 | 額外視為成功（如 `143 SIGTERM`） | ★★★ |
| `WatchdogSec=` | `[Service]` | `0` | 心跳逾時，需應用送 `WATCHDOG=1` | ★★★★ |
| `WatchdogSignal=` | `[Service]` | `SIGABRT` | 逾時時送出的訊號 | ★★ |
| `NotifyAccess=` | `[Service]` | `none`（用 `Type=notify` 或 `WatchdogSec=` 時**隱含為 `main`**） | 誰可以送通知 | ★★★★ |
| `OOMPolicy=` | `[Service]` | `stop` | v243+；`kill` 會殺整個 cgroup | ★★ |
| ★★★★ `StartLimitIntervalSec=` | **`[Unit]`** | `10s` | 寫錯區段會安靜失效 | ★★★★ |
| ★★★★ `StartLimitBurst=` | **`[Unit]`** | `5` | 同上，而且連警告都沒有 | ★★★★ |
| `StartLimitAction=` | `[Unit]` | `none` | ★★★★★ 別亂設 reboot 系列 | ★★★★★ |
| `OnFailure=` | `[Unit]` | 空 | **只在進入 failed 時觸發** | ★★★★ |
| `OnSuccess=` | `[Unit]` | 空 | v249+ | ★★ |
| `RuntimeWatchdogSec=` | `system.conf` | `0` | ★★★★★ 硬體 watchdog，會硬重開整台 | ★★★★★ |

**判讀指令**

| 目的 | 指令 | 星級 |
| --- | --- | --- |
| ★★★★ 看**生效值**（不是你寫了什麼） | `systemctl show <u> -p Restart,RestartUSec,StartLimitIntervalUSec,StartLimitBurst` | ★★★★ |
| 看重啟次數與最近一次啟動時間 | `systemctl show <u> -p NRestarts,Result,ExecMainStatus,ActiveEnterTimestamp` | ★★★★ |
| 數一小時內重啟幾次 | `journalctl -u <u> --since -1h \| grep -c 'Scheduled restart job'` | ★★★★ |
| 查退出碼名稱 | `systemd-analyze exit-status 78` | ★★★ |
| ★★★★ 撞上限後解除 | `systemctl reset-failed <u>` | ★★★★ |
| 整機健康一行指標 | `systemctl is-system-running`（`degraded` = 有 unit 掛著） | ★★★★ |
| 列出所有失敗的 unit | `systemctl --failed --no-legend` | ★★★ |
| 驗證 unit 語法 | `systemd-analyze verify <u>`（★★★ 抓不到 `StartLimitBurst=` 放錯區段） | ★★★ |
| 還原跳脫過的 unit 名 | `systemd-escape -u '<name>'` | ★★★ |
| 模擬崩潰 | `systemctl kill -s SIGKILL <u>` | ★★★★ |
| 模擬假死 | `kill -STOP <PID>`（事後記得 `kill -CONT`） | ★★★★ |

**檔案路徑**

| 路徑 | 用途 | 星級 |
| --- | --- | --- |
| `/etc/systemd/system/<unit>.d/99-recovery.conf` | 自動復原 drop-in | ★★★★ |
| `/etc/systemd/system/alert@.service` | 告警 template | ★★★★ |
| `/etc/svc-alert.env` | webhook Token（**640 root:root**） | ★★★★★ |
| `/run/maintenance/<svc>` | 維護旗標（tmpfs，重開機自動消失） | ★★★ |
| `/run/svc-health/<svc>.fails` | 健康檢查連續失敗計數 | ★★ |
| `/var/lib/restart-storm/last.snapshot` | NRestarts 上次快照（比差值用） | ★★★ |
| `/etc/systemd/system.conf` | `RuntimeWatchdogSec=`（硬體 watchdog） | ★★★★★ |

---

## 練習題

> [!question]- 練習 1：算出你手上服務的「撞上限所需時間」
> **題目**：某服務設定為 `RestartSec=5`、`StartLimitIntervalSec=20`、`StartLimitBurst=4`，
> 服務每次啟動後約 2 秒就崩潰。請問它會不會撞到上限？大約多久？如果把 `RestartSec` 改成 `8` 呢？
>
> **參考解答**
> 每一輪的間隔 = `RestartSec` + 服務存活時間 = 5 + 2 = **7 秒**。
> 從第一次啟動算起，第 4 次啟動發生在第 21 秒（0、7、14、21）。
> 滑動窗口是 20 秒，第 4 次在第 21 秒時，窗口內只涵蓋第 7、14、21 秒這三次 —— **恰好差一次，撞不到**。
> 這正是「臨界條件」的意義：`RestartSec × (Burst−1) = 5 × 3 = 15 < 20` 看似成立，
> 但**忽略了服務本身的存活時間**（實際是 7 × 3 = 21 > 20）。
>
> 改成 `RestartSec=8` 後間隔變 10 秒，第 4 次在第 30 秒，窗口內更只有 2～3 次，**更撞不到**，
> 也就是**改得更鬆 = 更接近無限重啟**。
>
> 實作驗證：
> ```bash
> systemctl show <unit> -p NRestarts    # 觀察 10 分鐘，數字持續增加就是撞不到上限
> ```
> 正解是把 `StartLimitIntervalSec` 拉大到 `300` 並保持 `RestartSec=10`：
> 五分鐘內第 5 次一定發生在窗口內，服務會進 failed 並告警。

> [!question]- 練習 2：判斷三個服務各該用哪一種第二層防線
> **題目**：(a) 你自己寫的 Python 收集器；(b) 廠商給的 Java WAR 跑在 Tomcat 上，沒有原始碼；
> (c) 套件安裝的 PHP-FPM。三者都出現過「程序活著但不回應」。各該用 watchdog 還是健康檢查 timer？
>
> **參考解答**
> - **(a) Python 收集器 → `WatchdogSec=`。** 你能改程式碼，用 `python3-systemd` 送 `WATCHDOG=1`，
>   而且心跳可以綁在「工作執行緒還活著」這個真正的內部狀態上，比從外面探測精準得多。
>   記得同時設 `Restart=on-failure`，否則假死後就地停機（★★★★）。
> - **(b) Java WAR → 健康檢查 timer。** 改不了程式碼就**不要設 `WatchdogSec=`**，
>   設了會每 30 秒被 SIGABRT 一次。用 oneshot + timer 打 Tomcat 的淺層端點，
>   配重啟預算與維護旗標。
> - **(c) PHP-FPM → 可以用 `WatchdogSec=`。** PHP-FPM 主程序原生支援 sd_notify，
>   套件的 unit 已是 `Type=notify`，只要在 drop-in 加 `WatchdogSec=30s` + `Restart=on-failure`。
>   驗證：`systemctl show php8.3-fpm -p Type,WatchdogUSec` 要看到 `notify` 與 `30s`。
>   pool 層級的調校見 [[060-03-01-02-guide-PHP-FPM設定與Pool調校]]。

> [!question]- 練習 3：設計一個能抓到「無限重啟」的告警，並說明為什麼不能比絕對值
> **題目**：你要為十台主機加上「服務一直重啟」的告警。請寫出判斷邏輯，
> 並說明為什麼不能用「`NRestarts` > 100 就告警」。
>
> **參考解答**
> **邏輯**：每 15 分鐘取一次全機所有 unit 的 `NRestarts` 快照，與上次快照比**差值**，
> 差值 ≥ 5 就告警；差值為負則跳過（代表計數被歸零）。
>
> **為什麼不能比絕對值**（★★★★）：
> 1. `systemctl reset-failed` 會 flush 計數器，維護後 `NRestarts` 歸零 → 絕對值門檻立刻失效。
> 2. 服務重新 `start`（例如部署）也會歸零。
> 3. 跑了三年、每月正常重啟一次的服務，`NRestarts` 自然會超過 100 —— 絕對值門檻會產生假警報，
>    然後大家開始忽略這個告警，等於沒有。
>
> 差值法的兩個實作要點：template unit 的實例要用 `systemctl list-units` 展開逐一掃
> （只掃樣板檔會漏掉 `apply-worker@notify.service`）；輸出用固定 tag 或 `MESSAGE_ID=`
> 讓 SIEM 規則好寫（見 [[090-05-09-guide-資安設備-日誌集中與SIEM]]）。完整腳本見本篇〈主動巡檢〉。

---

## 小測驗

Q1. 同事設了 `Restart=on-failure`，用 `kill 4231` 測試發現服務沒有重啟，結論是「Restart 沒用」。他錯在哪裡？正確的驗證方式是什麼？

Q2. 是非題：`StartLimitIntervalSec=` 與 `StartLimitBurst=` 寫在 `[Service]` 區段時，`systemd-analyze verify` 一定會報錯，所以不會有人踩到。

Q3. 一個服務設定 `RestartSec=30`、`StartLimitIntervalSec=10`、`StartLimitBurst=5`。它掛掉後會發生什麼？為什麼這比「一崩潰就 failed」更危險？

Q4. 選擇題：以下哪一種情況**會**觸發 `OnFailure=`？
(A) 管理員手動 `systemctl stop`　(B) 服務每 30 秒重啟一次但每次都起得來
(C) 服務撞到 StartLimit 進入 `start-limit-hit`　(D) 服務以 exit 0 正常結束

Q5. 某服務設了 `WatchdogSec=30s` 之後，變成每 30 秒被殺一次然後就完全停住。請說出兩個可能原因，以及各自的驗證指令。

Q6. 這行指令會發生什麼事？為什麼它是驗收流程裡不可省略的一步？
```bash
sudo systemctl start alert@test.service
```

Q7. 部署腳本跑到一半，服務被健康檢查 timer 重啟導致部署失敗。要怎麼修？修法本身又有什麼風險？

Q8. 簡答：為什麼「連得到資料庫」不能拿來驅動自動重啟？請描述一個具體的雪崩過程。

Q9. 值班人員半夜看到 `Job for apply-api.service failed.`，確認設定檔已經修好了但還是起不來。他該下哪一行指令？這個狀態的根本成因是什麼？

Q10. 你的 Ubuntu 22.04 主機上，`RestartSteps=5` 寫進 unit 後 `systemctl show` 顯示 `RestartSteps=0`。原因是什麼？替代方案是什麼？

> [!question]- 測驗答案
> **Q1.** ★★★★★ 他錯在**測試訊號**。`kill` 的預設訊號是 **SIGTERM**，而 SIGTERM 在 systemd 的定義裡
> 屬於**乾淨退出**（與 SIGHUP、SIGINT、SIGPIPE、exit 0 同一類），`on-failure` 對乾淨退出本來就不重啟 ——
> 設定完全正確。這個誤判的危險在於下一步：很多人會因此改成 `Restart=always`，
> 從此連「設定檔寫錯就退出」也會被無限重啟。
> 正確驗證要用三種注入分別驗：
> ```bash
> sudo systemctl kill -s SIGKILL apply-api.service                       # 崩潰
> sudo kill -STOP "$(systemctl show apply-api -p MainPID --value)"       # 假死
> sudo systemd-run --unit=t78 /bin/sh -c 'exit 78'                       # 設定錯誤
> ```
> 見〈為什麼你用 kill 測出來的結果是錯的〉與矩陣表第一列。
>
> **Q2.** ★★★★ **錯（是非題答「非」）**。實測 systemd 259：
> `StartLimitIntervalSec=` 放在 `[Service]` 會出現
> `Unknown key 'StartLimitIntervalSec' in section [Service], ignoring.`，
> 但 **`StartLimitBurst=` 放在 `[Service]` 連警告都沒有，`systemd-analyze verify` 回 rc=0**。
> 所以 verify **只抓得到一半**。唯一可靠的驗證是看生效值：
> ```bash
> systemctl show apply-api -p StartLimitIntervalUSec,StartLimitBurst
> ```
> 看到 `10s` / `5` 就代表你的設定沒生效（那是預設值）。
> 記住：`systemctl cat` 證明你寫了什麼，`systemctl show` 證明 systemd 收下了什麼。
> 見〈寫錯區段不會報錯，只會安靜失效〉。
>
> **Q3.** ★★★★ 它會**無限重啟，永遠不會 failed**。
> 每 30 秒才重啟一次，而窗口只有 10 秒，窗口內永遠只裝得下 1 次啟動，
> 5 次的上限永遠達不到。
> 比「一崩潰就 failed」更危險的原因有三：
> 1. `systemctl status` 顯示 `active (running)`，監控系統的「服務有沒有在跑」檢查會通過。
> 2. 沒有進 failed → **`OnFailure=` 永遠不觸發** → 完全沒有告警。
> 3. 每次啟動失敗都寫 journal，一夜 2880 次可以把 `/var` 灌滿，
>    連帶害死同一台上其他正常的服務。
> 判讀方式：`systemctl show <u> -p NRestarts` 與
> `journalctl -u <u> --since -1h | grep -c 'Scheduled restart job'`。
> 見〈本篇的核心算術〉與〈兩種安靜的死亡〉。
>
> **Q4.** ★★★★ **(C)**。`OnFailure=` **只在 unit 進入 failed 狀態時觸發**。
> - (A) 手動 `stop` 進入的是 `inactive`，不觸發 —— 這是對的，維護時不該吵人。
> - (B) ★★★★ **這是本篇最大的洞**：一直重啟但每次都起得來，從沒進過 failed，永遠不告警。
>   要靠 `NRestarts` 差值巡檢補。
> - (C) `start-limit-hit` 也是 failed 的一種，會觸發。
> - (D) exit 0 進 `inactive`，不觸發（`OnSuccess=` 才管這個，v249+）。
> 另外 `RestartMode=direct`（v254+）的自動重啟會**跳過** `OnSuccess=`／`OnFailure=`，官方明文。
> 結論：`Restart=` + `StartLimit*` + `OnFailure=` 必須當成一組設計。見〈OnFailure= 的觸發邊界〉。
>
> **Q5.** ★★★★ 兩個原因：
> 1. **應用根本沒送 `WATCHDOG=1`**（最常見，尤其是委外／無原始碼的服務）。
>    每 30 秒準時被殺就是這個症狀的特徵。
>    ```bash
>    systemctl show <u> -p Type,NotifyAccess,WatchdogUSec
>    journalctl -u <u> | grep -i 'Watchdog timeout'
>    ```
> 2. **`Restart=` 沒設或設成 `no`**，所以被 SIGABRT 殺掉之後就地停機。
>    ```bash
>    systemctl show <u> -p Restart      # 看到 Restart=no 就是它
>    ```
> 處置：改不了程式碼 → **移除 `WatchdogSec=`**，改用健康檢查 timer；
> 能改 → 補心跳（週期取 `WATCHDOG_USEC` 的一半）並補上 `Restart=on-failure`。
> ★★★★ 沒有 `Restart=` 的 `WatchdogSec=` 比完全不設 watchdog 更糟。見〈WatchdogSec= 的兩個致命前提〉。
>
> **Q6.** ★★★★ 它會直接啟動 `alert@.service` 這個 template 的 `test` 實例，
> 也就是**在不弄壞任何服務的前提下，走完一次完整的告警流程**（腳本執行、logger 寫入、webhook 送出）。
> 不可省略的原因：機關主機最常見的假安全就是「`OnFailure=` 設了半年，一則告警也沒收過」——
> 多半是告警管道走本機 MTA，而 MTA 沒裝、沒設或被防火牆擋在外面。
> ```bash
> sudo systemctl start alert@test.service
> sudo journalctl -t svc-alert -n 10 --no-pager
> ```
> ★★★★ 注意驗收標準：**要在 SIEM／Teams 那一端真的看到訊息才算過**，
> 只看到 journal 有紀錄僅代表腳本跑起來了，不代表訊息送得出去。見〈告警真的送得出去嗎〉。
>
> **Q7.** ★★★ 修法是**維護旗標檔**：部署前 `touch /run/maintenance/apply-api`，
> 健康檢查腳本第一件事就是檢查它，存在就 `exit 0` 跳過；部署完成後刪除。
> ```bash
> sudo touch /run/maintenance/apply-api
> # …部署…
> sudo rm -f /run/maintenance/apply-api
> ```
> ★★★★ 這個修法自帶風險：**旗標忘了刪，健康檢查就被永久停用而沒人發現** ——
> 你把第二層防線關掉了還以為它在。兩個防護：
> 1. 部署腳本用 `trap 'rm -f /run/maintenance/apply-api' EXIT` 確保異常中斷也會清掉。
> 2. 旗標放在 `/run`（tmpfs），重開機自動消失，不會變成永久狀態。
> 進階做法是讓巡檢腳本把「存在超過 30 分鐘的旗標」也列為告警項。見健康檢查腳本〈設計③〉。
>
> **Q8.** ★★★★ 因為那是 **readiness（深檢查）**，不是 liveness。雪崩過程：
> 1. 資料庫進入三十分鐘的例行維護。
> 2. 十台前端的健康檢查每分鐘打一次「連得到 DB 嗎」，全部失敗。
> 3. 十台前端每分鐘各被 `systemctl restart` 一次。
> 4. 每次重啟，應用初始化時都會建立一批新連線（connection pool 預熱）。
> 5. 資料庫一恢復就被十台前端的連線風暴打爆，再次不可用 —— 你把「DB 短暫不可用」
>    升級成「DB 更起不來 + 全部前端在崩潰迴圈」。
> 正確分工：**liveness（程序活著、埠有回應）驅動重啟；readiness（連得到 DB）只驅動告警。**
> 見〈liveness 與 readiness 一定要分開〉。
>
> **Q9.** ★★★★ 該下：
> ```bash
> sudo systemctl reset-failed apply-api.service && sudo systemctl start apply-api.service
> ```
> 根本成因是服務先前**撞到 StartLimit**（`Active: failed (Result: start-limit-hit)`），
> systemd 的 rate limit 計數器還記著，所以之後所有 `start` 都被擋下來 ——
> **這跟設定檔修好了沒關係**。確認方式：
> ```bash
> systemctl status apply-api | grep 'Result:'
> journalctl -u apply-api -n 5 --no-pager | grep 'repeated too quickly'
> ```
> ★★★★ 這一行必須進交接文件與部署腳本，否則值班人員會在半夜對著
> `Start request repeated too quickly` 卡半小時，而錯誤訊息完全沒提示要 `reset-failed`。
> 見〈兩種安靜的死亡〉與排查步驟【2】。
>
> **Q10.** ★★★ 因為 **Ubuntu 22.04 的 systemd 是 249，而 `RestartSteps=` 與 `RestartMaxDelaySec=`
> 是 systemd v254 才加入的**。舊版把它當成未知鍵忽略，所以 `show` 顯示預設值 `0`。
> 先驗版：
> ```bash
> systemctl --version | head -1        # systemd 249 (...)
> systemctl show <u> -p RestartSteps,RestartMaxDelayUSec
> # RestartSteps=0 / RestartMaxDelayUSec=infinity ← 沒生效
> ```
> 替代方案：用「固定 `RestartSec=10` + 收斂的 `StartLimitIntervalSec=300` / `StartLimitBurst=5`」，
> 也就是不追求越敲越慢，而是**敲五次就放棄並讓 `OnFailure=` 叫人**。
> 在機關情境這其實更好：與其讓機器自己退避半小時，不如五分鐘後就有人知道。
> RHEL 8（systemd 239）同理，而且連 `OnSuccess=`（v249+）都沒有。見〈指數退避與版本相容〉。

---

## 延伸閱讀

- [[020-02-02-01-svc-systemd-unit撰寫實戰]] —— unit 三區段、drop-in 與 template 的寫法、`Type=notify` 的 `READY=1` 就緒通知；本篇的心跳（`WATCHDOG=1`）是同一條 socket 的另一半
- [[020-02-02-02-cmd-systemd-timer與cron選型]] —— 本篇兩支 timer 用到的 `OnCalendar=` / `OnUnitActiveSec=` 語法與 `systemctl list-timers` 判讀
- [[020-02-02-03-cmd-systemd-cron排程實務與陷阱]] —— 告警腳本用到的 `flock` 去重與 `timeout` 保護的完整用法
- [[020-02-02-05-svc-systemd-PM2與systemd整合]] —— Node/PM2 情境下，`Restart=` 與 PM2 的 `min_uptime` 該怎麼分層對齊，避免兩層退避互相打架
- [[020-01-17-cmd-Linux-systemd服務管理]] —— `systemctl` 基本操作與 `status` 判讀；本篇假設你已經會這些
- [[020-01-19-guide-Linux-日誌系統]] —— 重啟迴圈灌爆 journal 之後的輪替與磁碟上限設定
- [[100-01-03-guide-日誌-系統監控與告警]] / [[100-01-04-guide-日誌-健康檢查與可用性監控]] —— 本篇是主機自帶的最後一道防線，機器整台當掉時只能靠外部監控
- [[100-02-09-svc-維運-事件處理與升級流程]] —— 告警送出去之後的分級、通報鏈與事後檢討
- [systemd.service(5) —— Restart=、WatchdogSec=、RestartSteps= 的權威定義與退出情境矩陣](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
- [systemd.unit(5) —— StartLimitIntervalSec=、StartLimitBurst=、OnFailure=、StartLimitAction=](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html)
- [sd_notify(3) —— WATCHDOG=1 與 sd_notify_barrier() 的協定細節](https://www.freedesktop.org/software/systemd/man/latest/sd_notify.html)
