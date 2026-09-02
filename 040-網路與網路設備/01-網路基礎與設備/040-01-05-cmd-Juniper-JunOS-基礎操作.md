---
title: "Juniper JunOS 基礎操作"
desc: "operational／configuration 兩種模式、candidate 與 active 的差別，以及 commit check／commit confirmed／rollback 這套「改壞了也回得來」的機制"
aliases: [JunOS, Junos CLI, commit confirmed, rollback, configure exclusive, display set]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-04-guide-網路設備-交換器初次設定與連線方式]]", "[[010-02-05-guide-網概-MAC位址與交換器]]"]
updated: 2026-09-02
---

# Juniper JunOS 基礎操作

> [!abstract] 這篇你會學到
> - ★★★★★ JunOS 最重要的一件事：**你打的每一條 `set` 都只改到 candidate（草稿），不 `commit` 就不生效** ——
>   這是 JunOS 與 Cisco IOS 最大的心智差異，也是所有安全性的來源
> - ★★★★★ `commit confirmed` —— 遠端改設定時**唯一**能救你的指令。改完自己把自己踢掉？
>   時間一到設備自動回到改之前的樣子，你重連就好
> - ★★★★★ `rollback 0~49` 與 `rollback rescue`：JunOS 自動保存 50 份歷史設定，
>   「回到十分鐘前那個好好的狀態」是一行指令的事
> - ★★★★ `show | compare` —— 送出前先看「我到底改了什麼」，這一步做了可以擋掉八成事故
> - ★★★★ `configure` / `configure exclusive` / `configure private` 三種進入設定模式的差別，
>   以及兩個人同時改設定時會發生什麼事
> - ★★★★ 介面命名 `ge-0/0/0.0` 每一段的意思，以及「實體介面」與「邏輯介面 unit」為什麼要分開
> - ★★★ `show configuration | display set` 把階層式設定翻譯回可貼上的 `set` 指令
> - ★★★ `request system` 系列：重開機、關機、還原出廠、備份快照
> - 產出一份「遠端改 JunOS 設定不斷線 SOP」與驗收檢查表

> [!warning] 未實機驗證
> ★★★★★ **本專案沒有可長期使用的實體 Juniper 設備**，本篇（以及 06～09 篇）的指令與輸出
> 依 Juniper 官方 Junos CLI 文件、`EX` 系列交換器設定指南整理撰寫，格式與欄位可能因
> **機型（EX2300／EX3400／EX4300／EX4600／QFX／SRX／MX）** 與 **Junos 版本（15.1／18.x／21.4／23.x）**
> 而有差異。導入前務必：
> 1. 在**測試機或 vLabs／vJunos** 上先跑過一次
> 2. 對每一條不確定的指令用 CLI 內建的 `?` 與 `help reference` 確認該機型是否支援
> 3. 正式環境一律走本篇「完整實戰範例」的 `commit confirmed` 流程

## 前置知識

- [[040-01-04-guide-網路設備-交換器初次設定與連線方式]] —— console 線、鮑率、第一次開機要做什麼
- [[010-02-05-guide-網概-MAC位址與交換器]] —— 交換器在做什麼、MAC 表怎麼運作
- [[010-02-16-guide-網概-VLAN與網路分段]] —— VLAN 的概念（本篇只碰 CLI，VLAN 設定在 06 篇）
- [[020-02-01-01-cmd-SSH-原理與第一次連線]] —— 之後要用 SSH 管交換器，先懂 SSH 這一端
- 會用文字編輯器、看得懂縮排階層（JunOS 設定長得像 JSON／nginx.conf，不是一行一行的清單）

## 觀念說明

### JunOS 有三個「地方」，先分清楚你人在哪裡 ★★★★★

Junos OS 底層是 FreeBSD，所以你會遇到**三種提示符號**，代表三個完全不同的環境：

```text
root@ex4300-1:~ #          ← ① UNIX shell（FreeBSD）。打 cli 進入 CLI
root@ex4300-1>             ← ② operational mode（操作模式）。只能「看」與「做動作」，不能改設定
root@ex4300-1#             ← ③ configuration mode（設定模式）。可以改設定，上面會有 [edit] 行

[edit]
root@ex4300-1#
```

| 提示符號結尾 | 你在哪 | 能做什麼 | 怎麼離開 |
| --- | --- | --- | --- |
| `%` 或 `#`（**沒有** `[edit]`） | UNIX shell | 跑 FreeBSD 指令，★★★★★ 新手不要待在這裡 | `cli` |
| `>` | operational mode | `show`、`ping`、`request`、`file`、`monitor` | `exit` 回 shell／登出 |
| `#`（**上面有** `[edit]`） | configuration mode | `set`、`delete`、`commit`、`rollback` | `exit` 回 operational |

★★★★★ **看到 `#` 不要直覺以為是 root shell。** JunOS 的設定模式提示符號也是 `#`。
判斷方式：**上一行有沒有 `[edit ...]`**。有 `[edit]` 就是設定模式，沒有就是 shell。
在 shell 裡亂打 `set` 什麼都不會發生，在設定模式裡打 `ls` 會被拒絕。

> [!danger] ★★★★★ 不要用 shell 直接編輯 `/config/juniper.conf.gz`
> 那是 commit 產生的結果檔，手改**不會**被載入、下一次 commit 就被覆蓋，
> 更糟的是會讓「設定檔」與「實際執行的設定」不一致，事後查不出原因。
> 唯一正確的改設定管道是 configuration mode 的 `set` / `delete` / `load`。

### candidate 與 active —— JunOS 的核心 ★★★★★

這是 JunOS 與 Cisco IOS 最根本的差別，也是你必須第一天就記住的一件事：

```text
                    你打的指令
                        │
                        ▼
   ┌────────────────────────────────────┐
   │  candidate configuration（候選設定）│   ← set / delete / load 改的是這裡
   │  = 草稿，改幾百行都不影響流量        │      改再多都「還沒生效」
   └────────────────────────────────────┘
                        │
                 commit（★★★★★ 唯一的分水嶺）
                        │  ① 語法檢查  ② 語意檢查（constraint check）
                        │  ③ 通知各進程套用  ④ 寫入 /config/juniper.conf.gz
                        ▼
   ┌────────────────────────────────────┐
   │  active configuration（生效設定）   │   ← 真正在轉封包用的設定
   │  = 同時就是「已存檔」的設定          │      斷電再開還是它
   └────────────────────────────────────┘
                        │
                        ▼  每 commit 一次，舊的 active 就往下推一格
   rollback 1 → 2 → 3 → … → 49（★★★★ 自動保存 50 份，不用你手動備份）
```

| Cisco IOS 習慣 | JunOS 對應 | 差在哪 ★ |
| --- | --- | --- |
| 打完 `switchport mode access` **立刻生效** | `set ... interface-mode access` 只進 candidate | ★★★★★ JunOS 給你「按下 Enter 之後還能反悔」的空間 |
| `copy running-config startup-config` 才存檔 | `commit` **同時**生效與存檔 | ★★★★ JunOS **沒有** write memory，忘記存檔這種事不存在 |
| 想比較改了什麼要靠人眼或外部工具 | `show \| compare` | ★★★★★ 內建 diff，送出前一定要看 |
| 回退靠 `copy startup-config running-config` 或重開機 | `rollback N` + `commit` | ★★★★★ 50 份歷史，任意一份一行回去 |
| 遠端改設定把自己鎖掉 = 派人去現場 | `commit confirmed` 自動回滾 | ★★★★★ 這一項就值得學 JunOS |

> [!note] 為什麼「不立刻生效」這麼重要 ★★★★★
> 想像你要改 trunk 的 VLAN 成員清單：Cisco 上你必須先 `no switchport trunk allowed vlan` 再重加，
> **中間那一瞬間 trunk 是空的，整棟樓斷線**。
> JunOS 上你在 candidate 裡刪了再加，`commit` 是**一次原子性地**套用最終狀態 ——
> 從來沒有「中間那一瞬間」。這叫 **transactional configuration**，是 JunOS 的招牌。

### 介面命名 `ge-0/0/0.0` 怎麼讀 ★★★★

```text
        ge  -  0  /  0  /  0  .  0
        │      │     │     │     └── unit：邏輯介面（Cisco 的 sub-interface）
        │      │     │     └──────── port：埠號（面板上第幾個孔，從 0 開始）
        │      │     └────────────── PIC：介面卡上的子卡編號（固定埠交換器多半是 0）
        │      └──────────────────── FPC：插槽／堆疊成員編號（★★★ Virtual Chassis 時 = member id）
        └─────────────────────────── 媒體類型與速率
```

| 前綴 | 意義 | 常見場合 ★ |
| --- | --- | --- |
| `ge-` | Gigabit Ethernet（1G） | ★★★★ EX 交換器最常見 |
| `xe-` | 10 Gigabit Ethernet | ★★★ 上聯埠、SFP+ |
| `et-` | 25G／40G／100G | ★★ QFX、EX4600 以上 |
| `fe-` | Fast Ethernet（100M） | ★ 老設備 |
| `ae0` | Aggregated Ethernet（鏈路聚合，等同 Cisco Port-channel） | ★★★ 見 [[040-01-16-guide-網路設備-鏈路聚合與STP]] |
| `irb` | Integrated Routing and Bridging，L3 VLAN 介面（**ELS** 機種） | ★★★★★ 管理 IP 用它，見 07 篇 |
| `vlan` | 舊版（**非 ELS**）的 L3 VLAN 介面，功能同 `irb` | ★★★★ 版本差異，見 07 篇 |
| `lo0` | Loopback；★★★★ **保護 Routing Engine 的防火牆過濾器掛在這裡** | ★★★★ 見 07 篇 |
| `me0` / `em0` / `fxp0` | 帶外管理埠（依機型不同） | ★★★★ 見 07 篇 |

★★★★ **`ge-0/0/0` 與 `ge-0/0/0.0` 是兩個不同的東西**：前者是實體埠（管 speed、duplex、MTU、description），
後者是它底下的邏輯單元（管 `family inet` 的 IP、`family ethernet-switching` 的 VLAN）。
二層交換埠幾乎永遠只用 `unit 0`；`set interfaces ge-0/0/1 unit 0 family ethernet-switching ...` 這串每個字都有意義，
少打 `unit 0` 會被 CLI 直接擋下來。

★★★ **Virtual Chassis（堆疊）** 時第一段數字＝成員編號。`ge-1/0/5` 是第 2 台機器（member 1）的第 6 個埠。
上架前沒把 member id 規劃好，日後看設定會非常痛苦。

### 設定是一棵樹，不是一份清單 ★★★★

JunOS 設定天生就是階層結構。同一份設定有**兩種顯示格式**，內容完全一樣：

```junos
## 階層格式（curly brace）—— show configuration 預設長這樣
interfaces {
    ge-0/0/1 {
        description "PC-3F-A12";
        unit 0 {
            family ethernet-switching {
                interface-mode access;
                vlan {
                    members OFFICE;
                }
            }
        }
    }
}
```

```junos
## set 格式 —— show configuration | display set 的輸出，可以直接複製貼上
set interfaces ge-0/0/1 description "PC-3F-A12"
set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members OFFICE
```

★★★★★ **交接文件、變更單、備份，一律用 `| display set` 格式。**
理由：階層格式看得舒服但不能貼；set 格式一行一個完整路徑，貼進另一台設備就是完整設定，
`grep` 也好找。「這個埠到底設了什麼」用 `show configuration interfaces ge-0/0/1 | display set` 一次看完。

本篇主線設備假設為 **EX 系列交換器（ELS，Junos 21.4 以後）**，
與非 ELS 舊機種的語法差異集中在 06、08 兩篇的摺疊區塊。

## 環境準備與安裝

### 步驟 0：連上去，確認你在跟什麼東西講話 ★★★★

console 線的接法、鮑率（**9600 8N1**）與 USB 轉接見 [[040-01-04-guide-網路設備-交換器初次設定與連線方式]]。
連上後第一件事是把下面這三組指令跑完 —— **不同機型、不同版本行為差很多，猜錯就是事故。**

```text
login: root
Password:

--- JUNOS 21.4R3-S5.4 Kernel 64-bit  JNPR-12.1-20230815.0eb1b2a_buil
root@ex4300-1:~ #
```

★★★★★ 用 root 登入**直接落在 UNIX shell**（提示符號 `~ #`），不是 CLI。打 `cli` 才會進 operational mode：

```text
root@ex4300-1:~ # cli
root@ex4300-1>
```

★★★ 一般帳號（`class super-user`）登入則是**直接進 operational mode**，不會經過 shell。
這也是「不要用 root 做日常維運」的另一個理由，見 [[040-01-07-guide-Juniper-管理IP與遠端存取]]。

```text
root@ex4300-1> show version
Hostname: ex4300-1
Model: ex4300-48t
Junos: 21.4R3-S5.4
JUNOS EX  Software Suite [21.4R3-S5.4]
JUNOS Web Management Platform Package [21.4R3-S5.4]
...
```

```text
root@ex4300-1> show chassis hardware
Hardware inventory:
Item             Version  Part number  Serial number     Description
Chassis                                PE3721480001      EX4300-48T
Routing Engine 0 REV 15   650-044930   BUILTIN           EX4300-48T
FPC 0            REV 15   650-044930   BUILTIN           EX4300-48T
  CPU                     BUILTIN      BUILTIN           FPC CPU
  PIC 0          REV 15   BUILTIN      BUILTIN           48x10/100/1000 Base-T
  PIC 1          REV 15   611-061396   MY3721300123      4x40GE QSFP+
Power Supply 0   REV 04   740-046873   1EDN3721234       JPSU-350-AC-AFO
Fan Tray 0                                               Fan Module, Airflow Out
```

★★★★ `show chassis hardware` 是盤點的第一手資料：**機型、序號、電源與風扇是否都在**。
序號要抄進資產表（見 [[040-01-18-guide-網路設備-網路設備盤點與文件化]]），報修 RMA 時第一個被問的就是它。

```text
root@ex4300-1> show system alarms
2 alarms currently active
Alarm time               Class  Description
2026-09-01 03:12:41 CST  Minor  Rescue configuration is not set
2026-08-30 11:04:07 CST  Minor  Host 0 Boot from backup root
```

| 常見告警 | 意思 | 該做什麼 ★ |
| --- | --- | --- |
| `Rescue configuration is not set` | 沒存救援設定 | ★★★★ 立刻 `request system configuration rescue save`，見 09 篇 |
| `Host 0 Boot from backup root` | ★★★★★ 主分割區壞了，這次是**從備援分割區開機**的 | 立刻處理，見 [[040-01-09-svc-Juniper-設定備份與韌體升級]] |
| `Management Ethernet Link Down` | 帶外管理埠沒接線 | ★★ 確認是否刻意 |
| `PEM 1 Not OK` | 第二顆電源沒電／沒插 | ★★★★ 冗餘失效，機房排修 |

### 步驟 1：先把 CLI 調成人類可用的樣子 ★★★

預設 CLI 每 24 行就分頁（`---(more)---`），複製貼上會夾雜控制字元。這三行**強烈建議**每次上機先打：

```text
root@ex4300-1> set cli screen-length 0
Screen length set to 0

root@ex4300-1> set cli screen-width 0
Screen width set to 0

root@ex4300-1> set cli timestamp
Sep 02 09:14:07
CLI timestamp set to: %b %d %T
```

| 指令 | 作用 | 星級 |
| --- | --- | --- |
| `set cli screen-length 0` | 關掉分頁，輸出一次吐完，好複製 | ★★★★ 抓資料必開 |
| `set cli screen-width 0` | 不自動折行，表格才不會斷掉 | ★★★ |
| `set cli timestamp` | 每個指令前面印時間，★★★★ **故障處理留紀錄的關鍵** | ★★★★ |
| `set cli idle-timeout 15` | 15 分鐘沒動作自動登出（僅本次連線） | ★★★ |
| `set cli complete-on-space off` | 空白鍵不自動補完（習慣 Cisco 的人會想關） | ★★ |

★★★★ 這些 `set cli` 是 **operational mode 的指令，只影響本次連線，不寫進設定檔**。
不要把它跟 configuration mode 的 `set` 搞混 —— 這是新手最常見的困惑之一。
要讓所有人都套用，得在設定模式寫 `set system login class ... idle-timeout`（見 07 篇）。

### 步驟 2：學會問 CLI，而不是憑記憶 ★★★★★

JunOS 的線上說明比大多數網路設備完整，**這一節比背指令重要得多**：

```text
root@ex4300-1> show ?
Possible completions:
  arp                  Show system Address Resolution Protocol table entries
  chassis              Show chassis information
  configuration        Show current configuration
  ethernet-switching   Show ethernet-switching information
  interfaces           Show interface information
  log                  Show contents of log file
  route                Show routing table information
  system               Show system information
  version              Show software process revision levels
  vlans                Show VLAN information
```

| 用法 | 回答什麼問題 | 星級 |
| --- | --- | --- |
| `?`（單獨或接在指令後） | 這個位置可以打什麼 | ★★★★★ 最常用 |
| `Tab` 或 `Space` | 自動補完 | ★★★★ |
| `help topic <主題> <關鍵字>` | 這個功能的**觀念**說明 | ★★★ |
| `help reference <主題> <關鍵字>` | 這個設定項的**語法與參數**（等同手冊） | ★★★★ |
| `help apropos <字串>` | 哪些指令跟這個字有關 | ★★★ 忘記指令名稱時用 |
| `show configuration \| display set \| match <字>` | 現在誰設了這個 | ★★★★★ |

```text
root@ex4300-1> help apropos "storm control"
help topic ethernet-switching storm-control
    Configure storm control
help reference ethernet-switching storm-control
    storm-control
set forwarding-options storm-control-profiles <name>
    Storm control profile
```

★★★★★ **本篇（與 06～09 篇）任何一條你不確定的指令，先在該機型上打 `?` 與 `help reference` 確認。**
Junos 版本之間差異真的很大，官方文件寫的版本不一定就是你手上這台。

### 步驟 3：operational mode 常用指令巡禮 ★★★

```text
root@ex4300-1> show interfaces terse | match ge-0/0/1
ge-0/0/1                up    up
ge-0/0/1.0              up    up   eth-switch
ge-0/0/10               up    down
ge-0/0/11               down  down
```

★★★★ 兩個 `up/down` 欄位意思不一樣：**第一欄是「管理狀態」（有沒有被 `disable`），第二欄是「實體連線狀態」**。

| 顯示 | 意思 | 常見原因 ★ |
| --- | --- | --- |
| `up up` | 正常 | — |
| `up down` | 沒被停用，但**沒有 link** | ★★★★ 線沒插／對端關機／線壞／SFP 問題 |
| `down down` | ★★★★ 被 `set interfaces ge-0/0/x disable` 停用了 | 檢查是不是刻意封埠 |
| `up up` 但 unit 那行沒出現 | 實體有 link，但**沒設 `unit 0`**，不會轉任何流量 | ★★★★ 新埠常忘 |

```text
root@ex4300-1> show system uptime
Current time: 2026-09-02 09:20:33 CST
Time Source:  NTP CLOCK
System booted: 2026-08-30 11:03:52 CST (2d 22:16 ago)
Protocols started: 2026-08-30 11:05:10 CST (2d 22:15 ago)
Last configured: 2026-09-01 16:42:08 CST (16:38:25 ago) by netadmin
```

★★★★ `Last configured ... by netadmin` 是**追查「誰在什麼時候動了設定」的第一條線索**，
接著用 `show system commit` 看完整歷史。

```text
root@ex4300-1> show system commit
0   2026-09-01 16:42:08 CST by netadmin via cli
    commit confirmed, rollback in 5mins
1   2026-09-01 16:38:55 CST by netadmin via cli
    新增 3F 會議室 VLAN
2   2026-08-30 11:20:41 CST by root via cli
3   2026-08-25 09:03:12 CST by netadmin via netconf
```

★★★★★ 第一欄的數字**就是 `rollback N` 的 N**。`0` 是目前生效的設定，`1` 是上一版。
第二行是 `commit comment` 留下的訊息 —— 這也是為什麼要求「每次 commit 都要寫 comment」。

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `show interfaces terse` | 所有埠一覽（最常用） | ★★★★★ |
| `show interfaces descriptions` | 只看埠描述，做為現場對照表 | ★★★★ |
| `show ethernet-switching table` | MAC 位址表（Cisco 的 `show mac address-table`） | ★★★★★ |
| `show vlans` | VLAN 與成員埠 | ★★★★★ |
| `show system storage` | 磁碟用量，★★★★ 升級前必看 | ★★★★ |
| `show system users` | 誰在線上 | ★★★ |
| `show log messages \| last 50` | 系統日誌尾巴 | ★★★★ |
| `monitor start messages` | 即時追日誌（`monitor stop` 停止，`Esc q` 暫停畫面） | ★★★ |
| `show configuration \| display set` | 完整設定（set 格式） | ★★★★★ |
| `request system reboot` | 重開機 | ★★★★★ 危險 |

### 步驟 4：管道（pipe）—— JunOS CLI 真正的生產力 ★★★★

```text
root@ex4300-1> show interfaces terse | match "up    down" | count
Count: 12 lines
```

| 管道 | 作用 | 相當於 Linux |
| --- | --- | --- |
| `\| match <regex>` | 只留符合的行 | `grep` |
| `\| except <regex>` | 濾掉符合的行 | `grep -v` |
| `\| find <regex>` | ★★★ 從第一次符合的地方**往下全印** | `sed -n '/x/,$p'` |
| `\| count` | 只印行數 | `wc -l` |
| `\| last 20` / `\| trim 5` | 尾 20 行／砍掉每行前 5 字 | `tail` / `cut` |
| `\| no-more` | 本次輸出不分頁 | — |
| `\| display set` | 階層設定翻成 `set` 指令 | ★★★★★ |
| `\| display inheritance` | ★★★ 展開 `apply-groups` 繼承來的設定 | — |
| `\| display xml` | 輸出 XML，自動化用 | ★★ |
| `\| save /var/tmp/x.txt` | ★★★★ 存成檔案（之後 `file copy` 帶走） | `> file` |
| `\| compare` | 只在設定模式可用，比較 candidate 與 active | ★★★★★ |

```text
root@ex4300-1> show configuration | display set | match "ge-0/0/1 " | save /var/tmp/port1.txt
Wrote 4 lines of output to '/var/tmp/port1.txt'
```

★★★ `match` 吃的是正規表示式，字串含空白或特殊字元要加雙引號。
`match "ge-0/0/1 "`（結尾帶空白）可以避免 `ge-0/0/10`～`ge-0/0/19` 一起被抓進來，這是很實用的小技巧。

## 基礎設定

### 進入 configuration mode 的三種方式 ★★★★★

```text
root@ex4300-1> configure
Entering configuration mode
Users currently editing the configuration:
  netadmin terminal p1 (pid 4412) on since 2026-09-02 09:02:11 CST
      [edit]

[edit]
root@ex4300-1#
```

| 指令 | candidate 是誰的 | 別人也能改嗎 | 什麼時候用 | 星級 |
| --- | --- | --- | --- | --- |
| `configure` | **全機共用一份** | ★★★★★ 可以，而且你 `commit` 會**連他沒做完的改動一起送出** | 只有你一個人時 | ★★★ |
| `configure exclusive` | 共用那份，但**上鎖** | 別人完全進不來（可以 `configure` 唯讀看） | ★★★★★ **正式環境變更一律用這個** | ★★★★★ |
| `configure private` | **你自己一份副本** | 可以，各改各的，commit 時合併 | 多人同時做不相干的變更 | ★★★★ |

```text
root@ex4300-1> configure exclusive
warning: uncommitted changes will be discarded on exit
Entering configuration mode

[edit]
root@ex4300-1#
```

別人這時候想進來會看到：

```text
root@ex4300-1> configure
error: configuration database locked by:
  netadmin terminal p0 (pid 4681) on since 2026-09-02 09:31:02 CST, idle 00:01:12
      exclusive [edit]
```

> [!danger] ★★★★★ 用 `configure`（共用模式）時，`commit` 會送出「所有人」的未提交改動
> 真實事故長這樣：A 工程師在 candidate 裡半途做到一半的 VLAN 改動還沒完成，
> B 工程師登入用 `configure` 改了個埠描述就 `commit` ——
> **A 那份半成品跟著上線了**，整層樓斷網，而且從日誌看是 B 送的，A 完全不知情。
> 防法只有一個：**正式環境變更一律 `configure exclusive`**。
> 進去之後先 `show | compare`，看到不是自己改的東西就 `rollback` 清乾淨再開工。

★★★★ `configure private` 的 `commit` 語意要注意：它會把**你的**改動合併到共用 candidate 再 commit，
若別人改了同一個欄位會出現 `error: configuration database modified` 之類的衝突，
需要 `update` 或 `rollback` 重來。多人環境建議還是排班用 `exclusive`。

### 移動、設定、刪除 ★★★★

```text
[edit]
root@ex4300-1# edit interfaces ge-0/0/1

[edit interfaces ge-0/0/1]
root@ex4300-1# set description "PC-3F-A12 王小明"

[edit interfaces ge-0/0/1]
root@ex4300-1# up

[edit interfaces]
root@ex4300-1# top

[edit]
root@ex4300-1#
```

| 指令 | 作用 | 星級 |
| --- | --- | --- |
| `edit <路徑>` | 進入某個階層（之後的 `set` 都相對於它） | ★★★★ |
| `up` / `up 2` | 往上一層／兩層 | ★★★ |
| `top` | 直接回根 | ★★★★ |
| `exit` | 從階層退出；已在根則離開設定模式 | ★★★★ |
| `set <路徑> <值>` | 新增或修改 | ★★★★★ |
| `delete <路徑>` | ★★★★★ **刪除該路徑「以下所有東西」** | ★★★★★ |
| `deactivate <路徑>` | 保留設定但停用（顯示為 `inactive:`） | ★★★★ |
| `activate <路徑>` | 重新啟用 | ★★★ |
| `rename <舊> to <新>` | 改名 | ★★ |
| `copy <來源> to <目標>` | 複製整段（★★★ 開新埠很好用） | ★★★ |
| `annotate <路徑> "註解"` | 在設定檔裡留註解 | ★★★ |
| `wildcard delete interfaces ge-0/0/*` | ★★★★★ 萬用字元批次刪，威力極大也極危險 | ★★★★★ |

> [!danger] ★★★★★ `delete` 沒有「只刪一行」這回事
> `delete interfaces ge-0/0/1` 會把這個埠的 description、unit、VLAN 成員**整棵子樹**全部刪掉。
> 想只拿掉一個 VLAN 成員必須寫完整路徑：
> `delete interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members GUEST`。
> ★★★★★ **最恐怖的是 `delete interfaces`（不接埠名）** —— 一秒清空全部介面設定。
> 唯一的保險是 `commit` 之前先 `show | compare`。

`deactivate` 是很多人不知道但極好用的功能 —— **暫時關掉一段設定但不刪除**：

```text
[edit]
root@ex4300-1# deactivate protocols rstp interface ge-0/0/20

[edit]
root@ex4300-1# show protocols rstp interface ge-0/0/20
inactive: interface ge-0/0/20 {
    edge;
}
```

★★★★ 排錯時懷疑某段設定是元兇，**`deactivate` 比 `delete` 安全一百倍** ——
`commit` 驗證完發現不是它，`activate` 一行就回來，不必重打。

### `show | compare` —— 送出前的最後一道關卡 ★★★★★

```text
[edit]
root@ex4300-1# show | compare
[edit interfaces ge-0/0/1]
+   description "PC-3F-A12 王小明";
[edit interfaces ge-0/0/1 unit 0 family ethernet-switching]
-      vlan {
-          members OFFICE;
-      }
+      vlan {
+          members MEETING;
+      }
[edit vlans]
+   MEETING {
+       vlan-id 40;
+   }
```

| 符號 | 意思 |
| --- | --- |
| `+` | candidate 有、active 沒有 → **這次會新增** |
| `-` | active 有、candidate 沒有 → ★★★★★ **這次會刪掉** |
| `[edit ...]` | 下面那幾行改動發生在哪個階層 |

★★★★★ **`commit` 之前不看 `show | compare` 等於閉著眼睛按 Enter。**
特別注意 `-` 開頭的行：那是你**正在刪掉**的東西，八成的事故都是「刪到不該刪的」。

```text
[edit]
root@ex4300-1# show | compare rollback 3
```

★★★★ 加上 `rollback N` 可以比較 candidate 跟**任意一個歷史版本**的差異。
「這禮拜總共改了什麼」就是 `show | compare rollback 5`。

還有一個常被忽略但排錯超好用的：

```text
[edit]
root@ex4300-1# show interfaces ge-0/0/1 | display set
set interfaces ge-0/0/1 description "PC-3F-A12 王小明"
set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members MEETING
```

★★★★ 設定模式的 `show` 看的是 **candidate**；operational 模式的 `show configuration` 看的是 **active**。
兩邊輸出不一樣不是 bug，是你有東西還沒 commit。

### `commit check` —— 只驗不送 ★★★★

```text
[edit]
root@ex4300-1# commit check
configuration check succeeds
```

驗證失敗時：

```text
[edit]
root@ex4300-1# commit check
[edit interfaces ge-0/0/1 unit 0 family ethernet-switching vlan]
  'members MEETING'
    VLAN MEETING does not exist
error: configuration check-out failed
```

★★★★★ `commit check` 做的**不只是語法檢查**，還包含 JunOS 的 **constraint check（語意檢查）**：
引用了不存在的 VLAN、把同一個 IP 設在兩個介面、`irb` 沒對應到任何 VLAN、
`root-authentication` 沒設就想 commit ——這些都會在這一關被擋下來。
這是 JunOS 比 Cisco IOS 明顯優越的地方：**大量的設定錯誤在生效之前就被攔截**。

```text
[edit]
root@ex4300-1# commit check
[edit system]
  Missing mandatory statement: 'root-authentication'
error: commit failed: (missing statements)
```

★★★★ 這是 `load factory-default` 之後最常見的一個錯誤 —— **JunOS 強制要求先設 root 密碼才准 commit**。

### `commit` 的各種形式 ★★★★

```text
[edit]
root@ex4300-1# commit comment "CR-2026-0412 3F 會議室改 VLAN 40"
commit complete
```

| 形式 | 作用 | 星級 |
| --- | --- | --- |
| `commit` | 送出 | ★★★★★ |
| `commit comment "文字"` | ★★★★★ 送出並在 `show system commit` 留下說明 | ★★★★★ |
| `commit and-quit` | 送出後直接離開設定模式 | ★★★ |
| `commit confirmed <分鐘>` | ★★★★★ 送出但需要二次確認，否則自動回滾 | ★★★★★ |
| `commit at "23:30:00"` | 排程在指定時間送出（★★★ 變更時窗用） | ★★★ |
| `commit synchronize` | 雙 RE 機種同步到備援 RE | ★★★ |
| `commit \| display detail` | 印出 commit 每一步在做什麼（排錯用） | ★★ |

★★★★★ **`commit comment` 請視為強制規定**。網路設備出事時最貴的成本是「查不出誰為什麼改了什麼」；
一行 comment 寫上變更單號，事後追查是幾秒鐘的事。這條也應該寫進
[[100-02-08-guide-維運-變更管理流程]] 的作業規範。

```text
[edit]
root@ex4300-1# commit at "23:30:00" comment "CR-2026-0412 夜間變更時窗"
configuration check succeeds
commit at will be executed at 2026-09-02 23:30:00 CST
The configuration has been changed but not committed
Exiting configuration mode
```

★★★ 排程 commit 可以用 `clear system commit` 取消：

```text
root@ex4300-1> clear system commit
Pending commit cleared
```

### `commit confirmed` —— 遠端改設定的救命索 ★★★★★

這是**整篇最重要的一節**。請把它背起來。

```text
[edit]
root@ex4300-1# commit confirmed 5
commit confirmed will be automatically rolled back in 5 minutes unless confirmed
commit complete

[edit]
root@ex4300-1#
```

設定**立刻生效**了，但 JunOS 同時啟動一個 5 分鐘的倒數計時器：

```text
時間軸
 t=0   commit confirmed 5   → 新設定生效，倒數開始
 │
 ├─ 情境 A：你還連得上 → 在 5 分鐘內打 commit
 │     root@ex4300-1# commit
 │     commit complete            ← ★★★★★ 這樣才是真正定案
 │
 └─ 情境 B：你被自己踢掉了 → 什麼都不用做
       t=5min  設備自己執行 rollback 1 + commit
       broadcast message：
       Warning: Commit was not confirmed; automatic rollback complete.
       ← 設定回到改之前，你重新連上去就好
```

> [!danger] ★★★★★ 遠端（SSH）改任何一項「可能影響到你自己連線」的設定，一律用 `commit confirmed`
> 這些改動全部算在內，一項都不能省：
> - 管理介面（`irb`／`me0`／`fxp0`）的 IP、遮罩
> - 預設路由 `routing-options static route 0.0.0.0/0`
> - `system services ssh` 的任何設定（含 `connection-limit`、`ciphers`）
> - `lo0` 上保護 Routing Engine 的 firewall filter ★★★★★（最容易把自己鎖死）
> - 上聯埠的 VLAN 成員、trunk 設定、`native-vlan-id`
> - `system login` 使用者、class、認證方式
> - 韌體升級前後的設定調整（見 [[040-01-09-svc-Juniper-設定備份與韌體升級]]）
>
> 忘記加 `confirmed` 而改壞管理面 = **開車去機房接 console 線**。
> 機房在別的縣市的話，這一趟至少半天。

★★★★ 常見的三個誤解，一定要澄清：

| 誤解 | 事實 |
| --- | --- |
| 「`commit confirmed` 是不生效，等確認才生效」 | ★★★★★ **錯。設定馬上就生效了**，只是準備了一個自動反悔的計時器 |
| 「確認要打 `commit confirm`」 | ★★★★ **錯。確認就是打普通的 `commit`**（或 `commit check` 之後 `commit`） |
| 「不寫分鐘數就是不啟用」 | ★★★ **錯。`commit confirmed` 不接數字＝預設 10 分鐘** |

★★★ 還沒測完但快到期？**再打一次 `commit confirmed 5` 就是延長**（重新計時），不是套用新變更。
★★★★ 確定改壞了、不想等：直接 `rollback 1` 然後 `commit`，立刻回去。

```text
[edit]
root@ex4300-1# commit confirmed 5
commit confirmed will be automatically rolled back in 5 minutes unless confirmed
commit complete

... 測試發現不對 ...

[edit]
root@ex4300-1# rollback 1
load complete

[edit]
root@ex4300-1# commit
commit complete
```

> [!tip] ★★★★ 給時間要給夠，但也不能太長
> 5 分鐘夠不夠？看你要驗什麼。只是改一個 access 埠的 VLAN，5 分鐘綽綽有餘；
> 要跨到另一棟樓、找人幫忙插網線測試，給 15 分鐘。
> ★★★★ **太短的風險是「測到一半設定自己回去了」**，你會誤判成設定沒生效而重複操作；
> 太長的風險是「真的斷線時要等很久才恢復」。
> 一般實務：本機測 5 分鐘、需要協同測試 10～15 分鐘、跨單位協調 30 分鐘。

### `rollback` —— 五十份免費的後悔藥 ★★★★★

```text
[edit]
root@ex4300-1# rollback 1
load complete

[edit]
root@ex4300-1# show | compare
[edit vlans]
-   MEETING {
-       vlan-id 40;
-   }
```

★★★★★ **`rollback` 只是把歷史版本「載入 candidate」，還要 `commit` 才真的回去。**
這是新手最常踩的坑：打完 `rollback 1` 就以為好了，其實什麼都沒變。
好處是你可以先 `show | compare` 確認「回去之後長什麼樣」再決定要不要送。

| 指令 | 回到哪 | 星級 |
| --- | --- | --- |
| `rollback` 或 `rollback 0` | 丟掉所有未 commit 的改動，回到目前生效的設定 | ★★★★★ |
| `rollback 1` | 上一個 commit 版本 | ★★★★★ |
| `rollback N`（N ≤ 49） | 往前第 N 版 | ★★★★ |
| `rollback rescue` | ★★★★★ 手動存的「救援設定」（不受 50 版輪替影響） | ★★★★★ |
| `show system rollback` / `show system commit` | 列出可用版本與時間 | ★★★★ |

★★★★ **`rollback 0` 是「取消我剛剛打的一堆東西」的正確做法。**
進了設定模式打了半天發現方向錯了，不要一條一條 `delete`，`rollback 0` 一次清乾淨。

★★★★★ 檔案實際位置（09 篇會再用到）：

| 版本 | 路徑 |
| --- | --- |
| rollback 0（active） | `/config/juniper.conf.gz` |
| rollback 1～3 | `/config/juniper.conf.1.gz` ～ `.3.gz` |
| rollback 4～49 | `/var/db/config/juniper.conf.4.gz` ～ `.49.gz` |
| rescue | `/config/rescue.conf.gz` |

★★★★★ **50 份不是無限的。** 每 commit 一次就往下推一格，密集調整一天就可能把「上禮拜那個好版本」擠出去。
所以每個穩定狀態都要 `request system configuration rescue save`（09 篇）並外部備份。

## 進階設定與調校

### `load` —— 把外部設定倒進來 ★★★★

```text
[edit]
root@ex4300-1# load set terminal
[Type ^D at a new line to end input]
set vlans MEETING vlan-id 40
set vlans MEETING description "3F 會議室"
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members MEETING
^D
load complete
```

| 形式 | 語意 | 何時用 | 星級 |
| --- | --- | --- | --- |
| `load merge <檔案>` | 把檔案內容**合併**進 candidate（階層格式） | 加一段新設定 | ★★★★ |
| `load merge terminal relative` | 從螢幕貼入，且路徑相對於目前階層 | ★★★★ 貼片段最好用 | ★★★★ |
| `load set <檔案>` / `load set terminal` | 檔案／貼上的是 **`set` 格式** | ★★★★★ 最直覺 | ★★★★★ |
| `load replace <檔案>` | 檔案中標了 `replace:` 的段落**整段換掉** | 換整個 VLAN 區塊 | ★★★ |
| `load override <檔案>` | ★★★★★ **整份設定換掉**（等同從零裝機） | 大整修、災難復原 | ★★★★★ |
| `load patch <檔案>` | 套用 `show \| compare` 產生的差異檔 | 標準化派送 | ★★ |
| `load factory-default` | ★★★★★ 回到出廠設定（**會清掉你的管理 IP**） | 設備汰換前清資料 | ★★★★★ |

> [!danger] ★★★★★ `load override` 與 `load factory-default` 會清掉管理 IP
> 這兩個指令會讓**遠端連線立刻斷掉且回不來**。
> 遠端操作絕對禁止；一定要做的話：接 console 線、人在設備旁邊。
> `load factory-default` 之後 commit 前**必須**先 `set system root-authentication plain-text-password`，
> 否則會被 `Missing mandatory statement: 'root-authentication'` 擋住 —— 這其實是保護你。

★★★★ 一個很實用的組合：把備份還原到新設備上（換機情境，見 [[040-01-19-guide-網路設備-交換器汰換與遷移實務]]）：

```text
root@ex4300-new> file copy scp://netadmin@10.99.0.5//backup/ex4300-1.set /var/tmp/restore.set
Password for netadmin@10.99.0.5:
/var/tmp/restore.set                          100%   14KB   3.2MB/s   00:00

root@ex4300-new> configure exclusive
Entering configuration mode

[edit]
root@ex4300-new# load set /var/tmp/restore.set
load complete

[edit]
root@ex4300-new# show | compare | no-more
... 仔細檢查 ...

[edit]
root@ex4300-new# commit check
configuration check succeeds
```

### `apply-groups` —— 一份範本套到全部埠 ★★★

```junos
set groups ACCESS-PORT interfaces <ge-0/0/*> unit 0 family ethernet-switching interface-mode access
set groups ACCESS-PORT interfaces <ge-0/0/*> unit 0 family ethernet-switching storm-control SC-DEFAULT
set apply-groups ACCESS-PORT
```

★★★ 48 個埠不用打 48 次。看繼承後的實際結果要用：

```text
root@ex4300-1> show configuration interfaces ge-0/0/5 | display inheritance
##
## 'interface-mode' was inherited from group 'ACCESS-PORT'
##
unit 0 {
    family ethernet-switching {
        interface-mode access;
    }
}
```

★★★★ **`show configuration` 預設看不到繼承來的設定** —— 這會讓人以為「這個埠什麼都沒設」。
排錯時只要設備有用 `apply-groups`，一律加 `| display inheritance`。
（`groups` 的完整用法留給 [[040-01-18-guide-網路設備-網路設備盤點與文件化]] 與標準化章節
[[020-02-03-02-ref-標準化-基準設定與範本化]]。）

### `request system` 系列 ★★★★★

```text
root@ex4300-1> request system reboot
Reboot the system ? [yes,no] (no) yes

*** FINAL System shutdown message from root@ex4300-1 ***
System going down IMMEDIATELY
Shutdown NOW!
```

| 指令 | 作用 | 星級 |
| --- | --- | --- |
| `request system reboot` | 立即重開 | ★★★★★ |
| `request system reboot in 10` | 10 分鐘後重開（★★★★★ 遠端改設定的另一道保險） | ★★★★★ |
| `request system reboot at "03:00"` | 指定時間重開 | ★★★ |
| `clear system reboot` | 取消排定的重開 | ★★★★★ |
| `request system halt` | 停機（不斷電，需人到現場） | ★★★★ |
| `request system power-off` | 關機斷電 | ★★★★ |
| `request system zeroize` | ★★★★★ **抹除所有設定與金鑰**，設備報廢／退租前用 | ★★★★★ |
| `request system snapshot` | 建立系統快照到備援分割區（09 篇） | ★★★★ |
| `request system configuration rescue save` | 存救援設定 | ★★★★★ |
| `request system storage cleanup` | 清出磁碟空間（升級前必跑） | ★★★★ |
| `request system software add ...` | 安裝韌體（09 篇） | ★★★★★ |
| `request support information \| save /var/tmp/rsi.txt` | 一次抓齊 TAC 報修要的資訊 | ★★★★ |

> [!tip] ★★★★★ `request system reboot in 10` 是 `commit confirmed` 的兄弟
> 有些改動（例如某些 firewall filter 或介面設定）`commit confirmed` 的自動回滾**還是救不回**你的連線。
> 這時候的招式是：**先排一個 10 分鐘後的重開機，再做變更**。
> 改完連得上 → `clear system reboot` 取消；連不上 → 10 分鐘後設備重開，
> 若你的變更沒 commit 就會消失（重開會載入 `/config/juniper.conf.gz`）。
> ★★★★ 注意這招只在「變更沒 commit」時有效，commit 過的設定重開機還是在。
> 真正的組合技是 09 篇的「`request system reboot in N` + `commit confirmed`」雙保險。

> [!danger] ★★★★★ `request system zeroize` 不可逆
> 它會抹掉設定、日誌、SSH host key、以及**所有儲存的憑證與金鑰**，
> 設備回到剛出廠的樣子，連管理 IP 都沒有。這是設備**退租、報廢、轉手前**的標準程序
> （見 [[040-02-12-guide-機房-設備生命週期管理]]），日常維運絕對不要靠近它。

### 檔案操作與設定外送 ★★★

```text
root@ex4300-1> file list /var/tmp/

/var/tmp/:
gres-tp/
install/
port1.txt
restore.set
rtsdb/

root@ex4300-1> file show /var/tmp/port1.txt
set interfaces ge-0/0/1 description "PC-3F-A12 王小明"
set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members MEETING

root@ex4300-1> file copy /var/tmp/port1.txt scp://netadmin@10.99.0.5//backup/
Password for netadmin@10.99.0.5:
/var/tmp/port1.txt                            100%  180B   0.2KB/s   00:00
```

★★★★ `file copy` 支援 `scp://`、`ftp://`、`http://`。
★★★★★ **`scp://user@host//absolute/path` 要打兩條斜線** —— 第一條是 host 與 path 的分隔，
第二條是絕對路徑的根。只打一條會被當成相對於該使用者家目錄，寫到奇怪的地方。
完整的自動備份（`system archival`）留在 [[040-01-09-svc-Juniper-設定備份與韌體升級]]。

> [!info]- Cisco IOS 對照（簡表，完整內容見 [[040-01-10-cmd-Cisco-IOS-基礎操作]]）
> | 目的 | JunOS | Cisco IOS |
> | --- | --- | --- |
> | 進設定模式 | `configure` / `configure exclusive` | `configure terminal` |
> | 改設定 | `set ...` | 直接下指令 |
> | 刪設定 | `delete ...` | `no ...` |
> | 看差異 | `show \| compare` | ★ 無內建，靠 `archive config` 或外部工具 |
> | 生效 | `commit` | ★★★★★ 打完就生效（沒有 candidate 概念） |
> | 存檔 | `commit`（同時完成） | `copy running-config startup-config` / `write memory` |
> | 語法驗證 | `commit check` | ★ 無 |
> | 自動回滾 | `commit confirmed N` | `reload in N` + `configure replace`（IOS-XE 有 `configure confirm`） |
> | 回上一版 | `rollback 1` + `commit` | `configure replace flash:backup force` |
> | 看設定 | `show configuration \| display set` | `show running-config` |
> | 存救援設定 | `request system configuration rescue save` | `archive config` |
> | 重開機 | `request system reboot` | `reload` |
> | 出廠預設 | `load factory-default` | `erase startup-config` + `reload` |
> | 分頁關閉 | `set cli screen-length 0` | `terminal length 0` |
> | 管道過濾 | `\| match` / `\| except` | `\| include` / `\| exclude` |
>
> ★★★★★ 最關鍵的心智差異只有一句：**Cisco 是「打了就生效、忘記存檔就白做」，
> JunOS 是「打了不生效、commit 才同時生效與存檔」。** 兩種都會踩雷，但踩的方向完全相反。
> 完整雙欄對照見 [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]]。

## 完整實戰範例

**情境**：你人在辦公室，用 SSH 連進機房的 EX4300-48T（`ex4300-1`，管理 IP `10.99.0.11`）。
需求是把 3F 會議室的兩個埠 `ge-0/0/1`、`ge-0/0/2` 從 OFFICE VLAN 改到新的 MEETING VLAN（vlan-id 40），
並且讓上聯 trunk `ge-0/0/48` 帶這個新 VLAN。

★★★★★ **這是一個會動到上聯 trunk 的變更，做錯整台交換器離線。全程走 `commit confirmed`。**

### 步驟 1：留下「動手之前」的完整現況 ★★★★★

```text
netadmin@ex4300-1> set cli screen-length 0
Screen length set to 0

netadmin@ex4300-1> set cli timestamp
Sep 02 14:02:11
CLI timestamp set to: %b %d %T

netadmin@ex4300-1> show system commit | last 5
Sep 02 14:02:19
0   2026-08-30 11:20:41 CST by netadmin via cli
    CR-2026-0388 上聯改 ae0

netadmin@ex4300-1> show configuration | display set | save /var/tmp/before-CR0412.set
Sep 02 14:02:31
Wrote 412 lines of output to '/var/tmp/before-CR0412.set'

netadmin@ex4300-1> show vlans | save /var/tmp/before-vlans.txt
netadmin@ex4300-1> show interfaces descriptions | save /var/tmp/before-desc.txt
```

★★★★★ **「改之前的樣子」比「改之後的樣子」更值錢。** 出事時你要回到哪裡？就是這份。
把它 `file copy` 帶出設備（設備自己壞掉時，存在設備裡的備份也沒了）：

```text
netadmin@ex4300-1> file copy /var/tmp/before-CR0412.set scp://netadmin@10.99.0.5//backup/ex4300-1/
Password for netadmin@10.99.0.5:
/var/tmp/before-CR0412.set                    100%   18KB   4.1MB/s   00:00
```

### 步驟 2：存一份 rescue 設定 ★★★★★

```text
netadmin@ex4300-1> request system configuration rescue save
Sep 02 14:03:05

netadmin@ex4300-1> show system alarms
Sep 02 14:03:12
No alarms currently active
```

★★★★ 剛才 `Rescue configuration is not set` 的告警消失了，代表存成功。
之後不管改成什麼樣子，`rollback rescue` + `commit` 一定回得到現在這個好狀態。

### 步驟 3：獨占設定模式，確認 candidate 是乾淨的 ★★★★★

```text
netadmin@ex4300-1> configure exclusive
Sep 02 14:03:40
warning: uncommitted changes will be discarded on exit
Entering configuration mode

[edit]
netadmin@ex4300-1# show | compare

[edit]
netadmin@ex4300-1#
```

★★★★★ `show | compare` **什麼都沒印 = candidate 與 active 一致 = 沒有別人的半成品**。
有東西印出來？先問清楚是誰的，或直接 `rollback 0` 清掉再開工。

### 步驟 4：改設定（先做不影響流量的部分）★★★★

```text
[edit]
netadmin@ex4300-1# set vlans MEETING vlan-id 40
[edit]
netadmin@ex4300-1# set vlans MEETING description "3F 會議室 CR-2026-0412"
[edit]
netadmin@ex4300-1# set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members MEETING
```

★★★ 順序很重要：**先把 VLAN 建好、trunk 先放行，最後才動 access 埠**。
反過來做的話，access 埠改到一個 trunk 還沒放行的 VLAN，那段時間會員工會斷網。

```text
[edit]
netadmin@ex4300-1# set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members MEETING
[edit]
netadmin@ex4300-1# delete interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members OFFICE
[edit]
netadmin@ex4300-1# set interfaces ge-0/0/1 description "3F-MEETING-A CR-2026-0412"
[edit]
netadmin@ex4300-1# set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members MEETING
[edit]
netadmin@ex4300-1# delete interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members OFFICE
[edit]
netadmin@ex4300-1# set interfaces ge-0/0/2 description "3F-MEETING-B CR-2026-0412"
```

### 步驟 5：看差異，逐行對照變更單 ★★★★★

```text
[edit]
netadmin@ex4300-1# show | compare
[edit interfaces ge-0/0/1]
+   description "3F-MEETING-A CR-2026-0412";
[edit interfaces ge-0/0/1 unit 0 family ethernet-switching vlan]
-       members OFFICE;
+       members MEETING;
[edit interfaces ge-0/0/2]
+   description "3F-MEETING-B CR-2026-0412";
[edit interfaces ge-0/0/2 unit 0 family ethernet-switching vlan]
-       members OFFICE;
+       members MEETING;
[edit interfaces ge-0/0/48 unit 0 family ethernet-switching vlan]
       members [ OFFICE VOICE SERVER ];
+      members MEETING;
[edit]
+  vlans {
+      MEETING {
+          vlan-id 40;
+          description "3F 會議室 CR-2026-0412";
+      }
+  }
```

★★★★★ 逐行檢查清單：

- [ ] 只有 `ge-0/0/1`、`ge-0/0/2`、`ge-0/0/48`、`vlans` 四個地方被動到？**沒有其他埠**？
- [ ] `ge-0/0/48` 那段是 `+ members MEETING`（**新增**），不是把原本三個 VLAN 換掉？★★★★★
- [ ] `-` 開頭的行只有 `members OFFICE`（在 1、2 兩個埠上）？
- [ ] `vlan-id 40` 沒跟現有 VLAN 撞號？（用 `run show vlans | match 40` 確認）

```text
[edit]
netadmin@ex4300-1# run show vlans brief | match " 40 "

[edit]
netadmin@ex4300-1#
```

★★★★ **設定模式裡用 `run` 前綴可以直接跑 operational 指令**，不用退出去。這是排錯時的必備技巧。

### 步驟 6：`commit check` 再 `commit confirmed` ★★★★★

```text
[edit]
netadmin@ex4300-1# commit check
Sep 02 14:09:02
configuration check succeeds

[edit]
netadmin@ex4300-1# commit confirmed 10 comment "CR-2026-0412 3F 會議室 VLAN 40"
Sep 02 14:09:20
commit confirmed will be automatically rolled back in 10 minutes unless confirmed
commit complete

[edit]
netadmin@ex4300-1#
```

★★★★★ **此時起你有 10 分鐘。時鐘開始跑了。**
★★★★ 不要離開設定模式去做別的事 —— 保持這個 session 開著，它是你確認的唯一管道。

### 步驟 7：在時限內驗證 ★★★★★

```text
[edit]
netadmin@ex4300-1# run show vlans MEETING
Sep 02 14:09:41
Routing instance        VLAN name             Tag       Interfaces
default-switch          MEETING               40
                                                        ge-0/0/1.0*
                                                        ge-0/0/2.0*
                                                        ge-0/0/48.0*
```

★★★★ 星號 `*` 代表**該介面目前 up**。三個埠都有星號 = 都活著。

```text
[edit]
netadmin@ex4300-1# run show ethernet-switching table vlan-id 40
Sep 02 14:10:05
Vlan name   MAC address        MAC flags  Age    Logical interface  NH Index  RTR ID
MEETING     b4:0c:25:1a:3f:e2   D            -   ge-0/0/1.0         0         0
MEETING     b4:0c:25:1a:40:11   D            -   ge-0/0/2.0         0         0
```

★★★★★ **看到會議室 PC 的 MAC 出現在新 VLAN，才算真的通了。** 只看 `show vlans` 有埠是不夠的。

```text
[edit]
netadmin@ex4300-1# run show interfaces ge-0/0/48 extensive | match "Errors|Drops|CRC"
Sep 02 14:10:33
  Input errors:
    Errors: 0, Drops: 0, Framing errors: 0, Runts: 0, Policed discards: 0,
  Output errors:
    Carrier transitions: 2, Errors: 0, Drops: 0, Collisions: 0,
```

★★★ 上聯埠沒有暴增的錯誤計數。同時請會議室的人實測：
`ping` 得到閘道、開得了內網系統、DHCP 拿得到 40 網段的位址。

### 步驟 8：確認定案 ★★★★★

```text
[edit]
netadmin@ex4300-1# commit comment "CR-2026-0412 驗證通過，確認定案"
Sep 02 14:12:58
commit complete

[edit]
netadmin@ex4300-1# exit
Exiting configuration mode

netadmin@ex4300-1> show system commit | last 4
Sep 02 14:13:10
0   2026-09-02 14:12:58 CST by netadmin via cli
    CR-2026-0412 驗證通過，確認定案
1   2026-09-02 14:09:20 CST by netadmin via cli
    CR-2026-0412 3F 會議室 VLAN 40
2   2026-08-30 11:20:41 CST by netadmin via cli
    CR-2026-0388 上聯改 ae0
```

★★★★★ **看到 rollback 0 是你剛剛那筆 comment，才算完成。**
如果 `show system commit` 顯示 `automatic rollback` 之類的字樣，代表確認失敗、設定已經回去了。

### 步驟 9：留下「改之後」的紀錄並更新文件 ★★★★

```text
netadmin@ex4300-1> show configuration | display set | save /var/tmp/after-CR0412.set
Sep 02 14:14:02
Wrote 419 lines of output to '/var/tmp/after-CR0412.set'

netadmin@ex4300-1> file copy /var/tmp/after-CR0412.set scp://netadmin@10.99.0.5//backup/ex4300-1/
Password for netadmin@10.99.0.5:

netadmin@ex4300-1> request system configuration rescue save
Sep 02 14:14:40
```

★★★★ 新狀態穩定後**重存一次 rescue**。並把 before/after 兩份 `set` 檔附進變更單
（見 [[100-02-08-guide-維運-變更管理流程]]），埠對照表更新到
[[040-01-18-guide-網路設備-網路設備盤點與文件化]] 的盤點表。

### 驗收檢查表 ★★★★★

| # | 檢查項 | 通過標準 | 星級 |
| --- | --- | --- | --- |
| 1 | 動手前有存 before 設定並帶出設備 | `.set` 檔在備份伺服器上 | ★★★★★ |
| 2 | 動手前 rescue 已更新 | `show system alarms` 無 rescue 告警 | ★★★★★ |
| 3 | 用 `configure exclusive` | 進入時無他人 candidate 殘留 | ★★★★★ |
| 4 | `show \| compare` 逐行核對過 | 只動到變更單上的項目 | ★★★★★ |
| 5 | `commit check` 通過 | `configuration check succeeds` | ★★★★ |
| 6 | 用 `commit confirmed` 送出 | 輸出有 `will be automatically rolled back` | ★★★★★ |
| 7 | VLAN 成員正確 | `show vlans <名稱>` 三個埠都有 `*` | ★★★★ |
| 8 | 學到 MAC | `show ethernet-switching table vlan-id 40` 有終端 MAC | ★★★★★ |
| 9 | 使用者實測 | 拿得到 DHCP、ping 得到閘道、開得了系統 | ★★★★★ |
| 10 | 已 `commit` 確認 | `show system commit` 第 0 筆是確認那筆 | ★★★★★ |
| 11 | 上聯錯誤計數沒暴增 | `show interfaces ... extensive` Errors 未增加 | ★★★ |
| 12 | after 設定已備份、rescue 已重存 | 備份伺服器有 after 檔 | ★★★★ |
| 13 | 變更單、盤點表已更新 | 文件與現況一致 | ★★★★ |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 打了一堆 `set`，離開後發現設定完全沒生效 | 沒 `commit`。JunOS 的 `set` 只改 candidate | 重新 `configure` → `set` → `show \| compare` → `commit`。★★★★ 離開時 CLI 有問 `Exit with uncommitted changes? [yes,no]`，選 yes 就丟掉了 |
| ★★★★★ 遠端改完管理 IP／路由後 SSH 斷線，再也連不上 | 沒用 `commit confirmed`，設定已經永久生效 | 這次只能派人接 console。★★★★★ 以後所有動到管理面的變更一律 `commit confirmed 10` |
| ★★★★★ `commit confirmed` 之後過了時限，設定自己不見了 | 忘記在時限內打 `commit` 二次確認 | 那是**功能不是故障**。重做一次，這次記得確認。`show system commit` 可看到 `automatic rollback` |
| ★★★★★ 打了 `rollback 1` 但設定還是舊的 | `rollback` 只載入 candidate，**沒 commit** | `rollback 1` 之後一定要 `commit`。先 `show \| compare` 確認會變成什麼樣 |
| ★★★★★ 自己 commit 之後別人的半成品也上線了 | 用了共用的 `configure` 而非 `configure exclusive` | 正式環境一律 `configure exclusive`；進去先 `show \| compare` 確認乾淨 |
| ★★★★ `error: configuration database locked by: netadmin terminal p0` | 別人正用 `configure exclusive` | ★★★★ 不要硬搶。`show system users` 找到人問；真的無人回應且確定是殘留 session，請主管授權後用 `request system logout user <帳號>` 或 `clear system login` 處理 |
| ★★★★★ `commit` 失敗：`Missing mandatory statement: 'root-authentication'` | `load factory-default` 之後 root 密碼還沒設 | `set system root-authentication plain-text-password` 依提示輸入兩次，再 `commit` |
| ★★★★ `commit check` 失敗：`VLAN xxx does not exist` | 介面引用了還沒建立的 VLAN | 先 `set vlans xxx vlan-id N` 再 commit。★★★ JunOS 是**整份一起檢查**，順序不重要，缺就是缺 |
| ★★★★ 打 `set` 得到 `unknown command` | 你人在 UNIX shell 或 operational mode，不在設定模式 | 看提示符號上方有沒有 `[edit]`。shell → `cli` → `configure` |
| ★★★★ 打 `show interfaces` 在設定模式得到奇怪的結果 | 設定模式的 `show` 看的是 **candidate 設定**，不是介面狀態 | 用 `run show interfaces terse`，或 `exit` 回 operational |
| ★★★★ 想刪一個 VLAN 成員，結果整個埠設定都不見了 | `delete interfaces ge-0/0/1` 刪的是整棵子樹 | ★★★★★ 寫完整路徑到 `... vlan members OFFICE`。已經刪掉就 `rollback 0` 重來（**還沒 commit 的話**） |
| ★★★★ `show configuration` 看不到明明有設的東西 | 設定來自 `apply-groups` 繼承 | 加 `\| display inheritance`；或用 `show configuration \| display set \| match <關鍵字>` |
| ★★★★ 設定明明在，功能卻沒作用，且 `show` 時該段前面有 `inactive:` | 被 `deactivate` 停用了 | `activate <路徑>` 再 `commit` |
| ★★★ `file copy` 到 SCP 伺服器，檔案跑到奇怪的位置 | `scp://user@host/path` 只打了一條斜線＝相對於家目錄 | ★★★★ 絕對路徑要打**兩條**：`scp://user@host//backup/x.set` |
| ★★★ 輸出被 `---(more 23%)---` 卡住，複製不完整 | CLI 預設分頁 | `set cli screen-length 0`，或指令後加 `\| no-more` |
| ★★★ `commit` 很慢甚至逾時 | 設定很大、或某個 daemon 卡住 | `commit \| display detail` 看卡在哪一步；`show system processes extensive` 看負載；必要時 `restart <daemon>` |
| ★★★ 排程的 `commit at` 到時間沒送出 | 中途有人下了 `clear system commit`，或設備重開過 | `show system commit` 確認是否還有 pending；重新排程 |

### 排查步驟

**【1】先確認「你人在哪一層」★★★★★**

```text
root@ex4300-1:~ #
```

- 提示符號是 `~ #` 或 `%` → **UNIX shell**，打 `cli`
- 提示符號是 `>` → operational mode，要改設定打 `configure exclusive`
- 提示符號是 `#` 且上一行有 `[edit ...]` → configuration mode，可以 `set`

**【2】確認「你以為的設定」到底 commit 了沒 ★★★★★**

```text
[edit]
root@ex4300-1# show | compare
[edit vlans]
+   MEETING {
+       vlan-id 40;
+   }
```

**有輸出 = 這些東西還在 candidate、還沒生效。** 這是「改了沒反應」最常見的原因，
先排除它再往下查。沒有輸出才代表你的改動確實已經生效。

**【3】確認「現在生效的設定」而不是「你記得的設定」★★★★**

```text
root@ex4300-1> show configuration interfaces ge-0/0/1 | display set
set interfaces ge-0/0/1 description "PC-3F-A12 王小明"
set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members OFFICE
```

跟你以為的不一樣 → 跳【4】。一樣但功能不對 → 那是設定邏輯問題，跳到對應主題篇章
（VLAN 看 06 篇、管理與存取看 07 篇、埠參數看 08 篇）。

**【4】找出「這個設定是誰、什麼時候改的」★★★★★**

```text
root@ex4300-1> show system commit | last 10
0   2026-09-02 14:12:58 CST by netadmin via cli
    CR-2026-0412 驗證通過，確認定案
1   2026-09-02 14:09:20 CST by netadmin via cli
    CR-2026-0412 3F 會議室 VLAN 40
2   2026-09-02 09:41:03 CST by root via cli
```

★★★★ 沒有 comment 的那筆（`by root via cli`）通常就是問題來源 —— 有人手動改了沒留紀錄。
接著比對它前後的差異：

```text
root@ex4300-1> configure
[edit]
root@ex4300-1# show | compare rollback 3
[edit protocols rstp interface ge-0/0/20]
-    edge;
```

**看到那筆改動改了什麼，答案通常就在這裡。**

**【5】確認是不是繼承或被停用 ★★★**

```text
root@ex4300-1> show configuration interfaces ge-0/0/5 | display inheritance | match "inherited|inactive"
## 'interface-mode' was inherited from group 'ACCESS-PORT'
```

**【6】回到已知的好狀態 ★★★★★**

排除不了、而且服務中斷中 —— **不要繼續在生產環境試**。先恢復服務：

```text
[edit]
root@ex4300-1# rollback 1

[edit]
root@ex4300-1# show | compare        ← 確認會變回什麼樣

[edit]
root@ex4300-1# commit confirmed 5
commit confirmed will be automatically rolled back in 5 minutes unless confirmed
commit complete

... 確認服務恢復 ...

[edit]
root@ex4300-1# commit
commit complete
```

★★★★ 連 `rollback 1` 都不對（可能連續改壞好幾版）就用 `rollback rescue`，
那是你上次確認好用的狀態。恢復服務之後再慢慢在測試機上重現問題。

**【7】設備連不進去了 ★★★★★**

SSH 不通、ping 不到 —— 依序：

| 順序 | 動作 | 說明 |
| --- | --- | --- |
| 1 | 等 `commit confirmed` 的時限過完 | 若你有用，設備會自己回去。★★★★★ 這就是為什麼要用它 |
| 2 | 從帶外管理埠（`me0`／`em0`／`fxp0`）試 | 走完全不同的路徑，見 07 篇 |
| 3 | 從鄰近設備 `telnet 10.99.0.11 22` 測 | 判斷是網路不通還是服務掛了 |
| 4 | 接 console 線 | 最後手段，需要人到現場 |

## 安全性注意事項

> [!danger] ★★★★★ 遠端變更沒有 `commit confirmed` = 沒有安全網
> 這一條不是建議，是紀律。網路設備的遠端管理與伺服器不同 ——
> 伺服器改壞了還能從別台跳過去，交換器改壞了**連路徑本身都不見了**。
> 把「所有遠端 commit 一律 `commit confirmed`」寫進 SOP，違反就是缺失。

| 項目 | 風險 | 做法 | 星級 |
| --- | --- | --- | --- |
| root 直接登入 | 誰做的查不到 | ★★★★★ 建個人帳號（07 篇），`set system services ssh root-login deny` | ★★★★★ |
| `commit` 不寫 comment | 事後無法追溯 | ★★★★★ 一律 `commit comment "<變更單號> <內容>"` | ★★★★★ |
| 用共用 `configure` | 送出別人的半成品 | ★★★★★ 正式環境 `configure exclusive` | ★★★★★ |
| 沒有外部備份 | 設備故障＝設定全失 | ★★★★ `system archival transfer-on-commit`（09 篇）+ 每次變更手動 `file copy` | ★★★★★ |
| rescue 沒設或很舊 | 災難時沒有已知好狀態 | ★★★★ 每次變更確認後重存 `request system configuration rescue save` | ★★★★★ |
| `load override` / `load factory-default` 遠端執行 | 立即斷線且回不來 | ★★★★★ 僅限 console；操作前雙人覆核 | ★★★★★ |
| `request system zeroize` 誤用 | 不可逆，抹除一切 | ★★★★★ 僅用於設備退役；需主管書面核可 | ★★★★★ |
| 設定備份檔外流 | 內含加密密碼雜湊、SNMP community、RADIUS secret | ★★★★★ 備份存放區限權限、加密；不放共用磁碟機 | ★★★★★ |
| `set cli` 誤以為是永久設定 | 以為套用了 idle-timeout，其實沒有 | ★★★ 永久設定要寫在 `system login class` | ★★★ |
| 沒關 telnet | 帳密明文傳輸 | ★★★★★ `delete system services telnet`（07 篇） | ★★★★★ |
| 螢幕貼上一大段 `set` | 貼一半斷線、順序錯誤 | ★★★★ 用 `load set terminal` 一次載入，`^D` 結束，再 `show \| compare` | ★★★★ |

> [!warning] ★★★★ 備份檔裡有機敏資料
> `show configuration | display set` 的輸出包含
> `encrypted-password "$6$..."`（密碼雜湊，可離線暴力破解）、
> `snmp community "..."`、RADIUS 的 `secret "$9$..."`（★★★ Junos `$9$` 是**可逆**的弱編碼，
> 網路上有現成解碼器，等同明文）。
> 備份檔的保護等級必須比照密碼檔：專用目錄、限定權限、傳輸走 SCP 不走 FTP、
> 不要丟進沒有存取控制的共用資料夾或聊天軟體。相關原則見
> [[090-02-01-guide-防護-伺服器初始安全設定]]。

## 速查表

| 指令 | 說明 | 星級 |
| --- | --- | --- |
| `cli` | 從 UNIX shell 進入 operational mode | ★★★★ |
| `configure` | 進入設定模式（**共用** candidate） | ★★★ |
| `configure exclusive` | 進入設定模式並**上鎖**（正式環境用這個） | ★★★★★ |
| `configure private` | 進入設定模式，使用**自己的**副本 | ★★★★ |
| `set <路徑> <值>` | 新增／修改 candidate 設定 | ★★★★★ |
| `delete <路徑>` | 刪除該路徑**以下所有內容** | ★★★★★ |
| `deactivate <路徑>` / `activate <路徑>` | 暫停／恢復一段設定（不刪除） | ★★★★ |
| `show \| compare` | candidate 與 active 的差異（送出前必看） | ★★★★★ |
| `show \| compare rollback N` | 與第 N 版歷史設定的差異 | ★★★★ |
| `commit check` | 只做語法＋語意驗證，不送出 | ★★★★ |
| `commit comment "文字"` | 送出並留下說明 | ★★★★★ |
| `commit confirmed <分鐘>` | 送出，逾時未確認自動回滾（**遠端必用**） | ★★★★★ |
| `commit`（confirmed 之後） | 二次確認，讓變更定案 | ★★★★★ |
| `commit and-quit` | 送出後離開設定模式 | ★★★ |
| `commit at "23:30:00"` | 排程送出；`clear system commit` 取消 | ★★★ |
| `rollback 0` | 丟棄所有未 commit 的改動 | ★★★★★ |
| `rollback N` + `commit` | 回到第 N 版（0～49） | ★★★★★ |
| `rollback rescue` + `commit` | 回到手動存的救援設定 | ★★★★★ |
| `run <operational 指令>` | 在設定模式直接跑操作指令 | ★★★★ |
| `top` / `up` / `edit <路徑>` / `exit` | 階層導覽 | ★★★★ |
| `load set terminal` … `^D` | 從螢幕貼入 `set` 格式設定 | ★★★★★ |
| `load merge terminal relative` | 貼入階層片段（相對目前階層） | ★★★★ |
| `load override <檔案>` | ★★★★★ 整份取代（遠端禁用） | ★★★★★ |
| `load factory-default` | ★★★★★ 回出廠（會清掉管理 IP） | ★★★★★ |
| `show configuration \| display set` | 完整設定（可貼上的 set 格式） | ★★★★★ |
| `show configuration \| display inheritance` | 展開 `apply-groups` 繼承的設定 | ★★★ |
| `show system commit` | commit 歷史（第一欄就是 rollback 編號） | ★★★★★ |
| `show system uptime` | 開機時間、最後設定時間與人 | ★★★★ |
| `show system alarms` / `show chassis alarms` | 系統／硬體告警 | ★★★★ |
| `show version` / `show chassis hardware` | 版本／機型與序號 | ★★★★ |
| `show interfaces terse` | 所有介面狀態（管理／實體兩欄） | ★★★★★ |
| `show interfaces descriptions` | 介面描述一覽 | ★★★★ |
| `show ethernet-switching table` | MAC 位址表 | ★★★★★ |
| `show system storage` | 磁碟用量（升級前必看） | ★★★★ |
| `show log messages \| last 50` | 系統日誌 | ★★★★ |
| `monitor start messages` / `monitor stop` | 即時追日誌 | ★★★ |
| `file list` / `file show` / `file copy` / `file delete` | 檔案操作 | ★★★★ |
| `file copy X scp://u@h//abs/path` | 傳到外部（★★★★★ **兩條斜線**） | ★★★★ |
| `request system configuration rescue save` | 存救援設定 | ★★★★★ |
| `request system reboot in 10` / `clear system reboot` | 排程重開／取消 | ★★★★★ |
| `request system zeroize` | ★★★★★ 抹除一切（僅退役用） | ★★★★★ |
| `set cli screen-length 0` | 關分頁（僅本次連線） | ★★★★ |
| `set cli timestamp` | 每個指令加時間戳 | ★★★★ |
| `\| match` / `\| except` / `\| count` / `\| last N` / `\| no-more` / `\| save` | 管道 | ★★★★ |
| `?` / `help reference <主題>` / `help apropos <字>` | 線上說明 | ★★★★★ |
| `/config/juniper.conf.gz` | active 設定檔位置 | ★★★ |
| `/config/rescue.conf.gz` | 救援設定檔位置 | ★★★ |

## 練習題

> [!question]- 練習 1：在測試設備上完整走一遍 candidate → commit 流程 ★★★★
> 找一台實驗用交換器（或 vJunos／vLabs），完成：
> 1. 從 console 登入，`cli` 進 operational mode，關掉分頁並開啟 timestamp
> 2. `show system commit` 記下目前的 rollback 0 是什麼
> 3. `configure exclusive` 進入，`show | compare` 確認乾淨
> 4. `set interfaces ge-0/0/10 description "練習用-請勿使用"`
> 5. **先不要 commit**，另開一個 session 用 `show configuration interfaces ge-0/0/10` 看看有沒有這行
> 6. 回原 session `show | compare` 確認差異，`commit check`，然後 `commit comment "練習 1"`
> 7. 再用另一個 session 確認這次看得到了
>
> **要回答的問題**：第 5 步為什麼看不到？如果第 6 步之前你直接 `exit`，CLI 會問什麼？
> 選 yes 之後那行設定去哪了？

> [!question]- 練習 2：`commit confirmed` 的自動回滾 ★★★★★
> **這題一定要在測試設備上做，而且要親眼看到回滾發生。**
> 1. 記下目前的 `show interfaces terse | match ge-0/0/10`
> 2. `configure exclusive`，`set interfaces ge-0/0/10 disable`
> 3. `commit confirmed 2`
> 4. `run show interfaces terse | match ge-0/0/10` 確認變成 `down down`
> 5. **什麼都不要做**，等兩分鐘
> 6. 觀察畫面出現的 broadcast message，再看一次介面狀態
> 7. `exit` 後 `show system commit`，看那兩筆紀錄長什麼樣
>
> **要回答的問題**：第 6 步的訊息原文是什麼？介面回到什麼狀態？
> 如果第 5 步你打了 `commit`，結果會怎樣？打 `rollback 1` + `commit` 又會怎樣？

> [!question]- 練習 3：用 `show | compare` 抓出危險變更 ★★★★★
> 在測試設備上，把上聯 trunk（假設 `ge-0/0/48`，目前 `members [ OFFICE VOICE SERVER ]`）
> 用**兩種寫法**各改一次，每次都只看 `show | compare` **不要 commit**：
>
> A. `set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members MEETING`
> B. `delete interfaces ge-0/0/48 unit 0 family ethernet-switching vlan`
>    然後 `set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members MEETING`
>
> 每次做完看完 diff 就 `rollback 0`。
>
> **要回答的問題**：兩個 diff 差在哪裡？B 如果不小心 commit 了會發生什麼事？
> 從 diff 的哪一個特徵可以一眼認出「這是危險變更」？

> [!question]- 練習 4：從備份還原到一台空設備 ★★★★
> 1. 在測試設備 A 上 `show configuration | display set | save /var/tmp/a.set`
> 2. `file copy /var/tmp/a.set scp://<你的帳號>@<你的電腦>//tmp/`（或用 `file show` 複製貼上）
> 3. 在測試設備 B 上 `load factory-default`、設 root 密碼、`commit`
> 4. 把 a.set 弄到 B 上（`file copy` 或 `load set terminal` 貼上）
> 5. `load set /var/tmp/a.set`，`show | compare | no-more` 檢查，`commit check`
>
> **要回答的問題**：`load set` 之後 diff 裡有沒有東西是**不該原封不動搬過去**的？
> （提示：主機名稱、管理 IP、序號相關、憑證、SSH host key）
> 換機的完整流程見 [[040-01-19-guide-網路設備-交換器汰換與遷移實務]]。

> [!question]- 練習 5：寫出你們單位的「JunOS 遠端變更 SOP」★★★★
> 依本篇「完整實戰範例」的九個步驟，寫成一頁 A4 的作業程序，內容至少要有：
> - 動手前必做的三件事（備份、rescue、確認 candidate 乾淨）
> - `configure exclusive` 的規定與例外
> - `commit comment` 的格式（要含變更單號）
> - `commit confirmed` 的時間怎麼決定
> - 驗證項目清單（依你們的服務類型）
> - 出事時的回退決策樹（多久沒恢復就 rollback）
>
> 完成後與 [[100-02-08-guide-維運-變更管理流程]] 對照，補上簽核與通知的部分。

## 小測驗

Q1. 你 SSH 進交換器，看到提示符號是 `root@ex4300-1#`。你怎麼判斷自己在 UNIX shell 還是 configuration mode？兩者打 `set interfaces ge-0/0/1 disable` 分別會發生什麼事？

Q2. 是非題：在 JunOS 上 `commit` 之後還要另外存檔，否則重開機設定會消失。請說明理由。

Q3. 這行指令會發生什麼事：`delete interfaces ge-0/0/48`？如果你的本意是「把 GUEST 這個 VLAN 從這個 trunk 拿掉」，正確的指令應該怎麼寫？

Q4. 你打了 `commit confirmed 5`，然後測試發現一切正常。接下來你應該打什麼？如果打成 `commit confirm` 或什麼都不打，各會發生什麼？

Q5. 同事說「我 rollback 1 了但設定沒變」。診斷與正確做法？

Q6. `configure`、`configure exclusive`、`configure private` 三者的 candidate 各自屬於誰？舉一個「用 `configure` 而不是 `configure exclusive` 造成事故」的具體情境。

Q7. `show interfaces terse` 顯示 `ge-0/0/11  down  down`，而 `ge-0/0/10  up  down`。兩者的差別是什麼？各自該往哪個方向排查？

Q8. 你要遠端把交換器的預設路由從 `10.99.0.1` 改成 `10.99.0.254`。請寫出完整的指令序列（含進入模式、備份、驗證、確認），並說明每一步為什麼不能省。

Q9. `show configuration interfaces ge-0/0/5` 印出來是空的，但這個埠明明有在轉流量。有哪兩個可能原因？各用什麼指令證實？

Q10. 為什麼交換器的設定備份檔要比照密碼檔保護？舉出檔案裡至少三種機敏內容，並說明 Junos 的 `$9$` 前綴代表什麼風險。

> [!question]- 測驗答案
> **Q1.** ★★★★★ **看提示符號的「上一行」有沒有 `[edit ...]`**。有 `[edit]` 就是 configuration mode，
> 沒有就是 UNIX shell（root 登入時預設落在 shell，提示符號是 `root@host:~ #`）。
> 在 shell 打 `set interfaces ge-0/0/1 disable` 會得到 `set: Variable name must begin with a letter.`
> 之類的 shell 錯誤（`set` 在 FreeBSD shell 是內建指令，**什麼設定都不會改**）；
> 在 configuration mode 則會把該埠加入 candidate 的停用清單，**但要 `commit` 才真的斷掉**。
> ★★★★ 這是新手最常見的困惑：以為指令沒作用，其實是打錯地方。見「觀念說明」。
>
> **Q2.** ★★★★★ **錯。** JunOS 的 `commit` **同時完成「生效」與「存檔」** ——
> 它會把 candidate 寫進 `/config/juniper.conf.gz`，那就是開機時載入的檔案。
> JunOS **沒有** Cisco 的 `write memory` / `copy running-config startup-config` 這個步驟，
> 「忘記存檔所以重開機設定不見」這種事在 JunOS 上不會發生。
> ★★★★ 反過來說，JunOS 的陷阱是相反方向的：**打了 `set` 卻忘記 `commit`，設定完全沒生效**。
> 見「candidate 與 active」。
>
> **Q3.** ★★★★★ `delete interfaces ge-0/0/48` 會刪掉這個介面**底下所有設定** ——
> description、`unit 0`、`family ethernet-switching`、trunk 模式、**全部的 VLAN 成員**，
> 等於這個上聯埠變成一個什麼都沒設的裸埠，commit 後**整台交換器對外斷線**。
> 正確寫法要指到最末端的節點：
> `delete interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members GUEST`。
> ★★★★★ 保險做法是刪完先 `show | compare`，看到 diff 只有 `- members GUEST;` 一行才 commit；
> 若看到一整片 `-`，立刻 `rollback 0`。見「移動、設定、刪除」。
>
> **Q4.** ★★★★★ 應該打**普通的 `commit`**（建議 `commit comment "..."`），這樣才是二次確認、讓變更定案。
> - 打 `commit confirm`（沒有 `ed`）：那是**另一種寫法的同義指令**還是會被 CLI 補完成 `confirmed`，
>   ★★★ 但若你打成 `commit confirmed`（再一次帶 confirmed），效果是**延長計時**而非確認 —— 時間到還是會滾回去。
> - 什麼都不打：5 分鐘後設備自動執行 rollback + commit，
>   畫面出現 `Warning: Commit was not confirmed; automatic rollback complete.`，
>   你的變更全部消失（不是壞掉，是設計如此）。
> ★★★★ 記法：**confirmed 是「先斬後奏」，commit 是「奏准」**。見「commit confirmed」。
>
> **Q5.** ★★★★★ 因為 **`rollback N` 只是把第 N 版設定「載入 candidate」，還沒生效**。
> 診斷：`show | compare` 會看到一堆 `+`／`-`（那就是「還沒套用的回退內容」）。
> 正確做法：`rollback 1` → `show | compare`（確認回去之後長什麼樣）→ `commit`。
> ★★★★ 遠端做回退時仍然建議 `commit confirmed 5`，因為「回退」本身也可能踩到別的雷。
> 見「rollback」。
>
> **Q6.**
> - `configure`：★★★ 全機**共用一份** candidate。誰 commit，**所有人的未提交改動都會一起送出**。
> - `configure exclusive`：★★★★★ 用共用那份但**上鎖**，其他人進不來。正式環境標準做法。
> - `configure private`：★★★★ 每個人**自己一份副本**，commit 時合併回共用 candidate。
>
> 事故情境：A 工程師用 `configure` 改到一半（例如已經 `delete` 了 trunk 的 VLAN 成員、
> 還沒重新 `set` 回去）就被叫去開會；B 工程師登入用 `configure`、只改了一個埠描述就 `commit` ——
> **A 那個「刪掉一半」的狀態跟著上線**，上聯 trunk 的 VLAN 不見，整棟樓斷網，
> 而且 `show system commit` 顯示是 B 送的，B 完全不知道自己送了什麼。
> ★★★★★ 防法：正式環境一律 `configure exclusive`，且進去先 `show | compare` 確認乾淨。
> 見「進入 configuration mode 的三種方式」。
>
> **Q7.** ★★★★ 第一欄是**管理狀態**（Admin），第二欄是**實體連線狀態**（Link）。
> - `down down`（ge-0/0/11）：★★★★ 這個埠被 `set interfaces ge-0/0/11 disable` **人為停用**了。
>   排查方向是設定：`show configuration interfaces ge-0/0/11 | display set`，
>   確認是不是刻意封埠（08 篇的未用埠管理政策），是的話這是正常狀態。
> - `up down`（ge-0/0/10）：★★★★ 沒被停用，但**沒有 link**。排查方向是實體層：
>   線有沒有插好、對端設備開機了嗎、換一條線、換一個埠、SFP 用
>   `show interfaces diagnostics optics` 看光功率、`show interfaces ge-0/0/10 extensive`
>   看 `Carrier transitions` 是不是一直跳（線鬆或協商問題）。見「operational 指令巡禮」與 08 篇。
>
> **Q8.** ★★★★★ 這是**動到管理面**的變更，改錯直接斷線。完整序列：
> ```text
> netadmin@sw> show configuration routing-options | display set | save /var/tmp/before-route.set
> netadmin@sw> request system configuration rescue save
> netadmin@sw> configure exclusive
> [edit]
> netadmin@sw# show | compare                      ← 確認乾淨
> [edit]
> netadmin@sw# delete routing-options static route 0.0.0.0/0
> [edit]
> netadmin@sw# set routing-options static route 0.0.0.0/0 next-hop 10.99.0.254
> [edit]
> netadmin@sw# show | compare                      ← 只有這兩行
> [edit]
> netadmin@sw# commit check
> [edit]
> netadmin@sw# commit confirmed 5 comment "CR-xxxx 改預設路由"
> [edit]
> netadmin@sw# run ping 8.8.8.8 count 3            ← 或 ping 你的管理站
> [edit]
> netadmin@sw# commit comment "CR-xxxx 驗證通過"
> ```
> 每一步不能省的理由：**備份**＝出事有東西可還原；**rescue**＝最後防線；
> **exclusive**＝不會送出別人的東西；**compare**＝確認沒誤刪其他路由；
> **check**＝擋掉語意錯誤（例如 next-hop 不在任何直連網段）；
> ★★★★★ **confirmed**＝新閘道如果根本不通、你 SSH 斷掉，5 分鐘後自動回舊的；
> **驗證**＝證明真的通了；**二次 commit**＝定案。少任何一步都是在賭。見「完整實戰範例」。
>
> **Q9.** ★★★★ 兩個可能：
> 1. **設定來自 `apply-groups` 繼承**。`show configuration` 預設不顯示繼承來的內容。
>    證實：`show configuration interfaces ge-0/0/5 | display inheritance`，
>    會看到 `## 'interface-mode' was inherited from group 'ACCESS-PORT'`。
> 2. **你看的是 candidate 而它跟 active 不同**，或反過來 —— 例如你在 operational mode 看 active，
>    但改動還在別人的 candidate 裡（那就還沒生效，埠當然是用舊設定在跑）。
>    證實：進 `configure` 後 `show | compare`，有輸出代表兩邊不一致。
>
> ★★★ 第三個較少見但要知道的可能：這台是 Virtual Chassis，你看錯成員了
> （`ge-0/0/5` 是 member 0，實際在跑的是 `ge-1/0/5`）。見「apply-groups」與「排查步驟【5】」。
>
> **Q10.** ★★★★★ 因為備份檔就是一份**可離線分析的完整安全組態**。至少三種機敏內容：
> 1. `set system root-authentication encrypted-password "$6$..."` 與各使用者的密碼雜湊
>    —— 可以拿去離線暴力破解／字典攻擊。
> 2. `set snmp community "..."` —— SNMP community 字串，拿到就能讀（甚至寫）設備狀態。
> 3. `set access radius-server 10.0.0.5 secret "$9$..."` 與各種 `$9$` 編碼的密碼。
>
> ★★★★★ **`$9$` 是 Junos 的可逆編碼，不是雜湊。** 網路上有大量現成的解碼工具，
> 幾秒鐘就能還原成明文，因此**應該直接視同明文密碼**。
> （`$6$` 是 SHA-512 crypt，屬於不可逆雜湊，但仍可被離線破解，一樣要保護。）
> 另外備份檔還洩漏完整的網路拓樸、VLAN 規劃、ACL 規則、管理網段位置 ——
> 對攻擊者而言這是一張現成的作戰地圖。
> 保護方式：專用備份目錄限定權限、傳輸走 SCP／SFTP（不用 FTP／TFTP）、
> 備份區加密、不放共用磁碟機或聊天軟體、保存期限與銷毀程序納入規範。
> 見「安全性注意事項」與 [[090-02-01-guide-防護-伺服器初始安全設定]]。

## 延伸閱讀

- [[040-01-06-guide-Juniper-VLAN與Trunk設定]] —— 接下來就是把埠丟進 VLAN，ELS 與非 ELS 語法差異全在那篇
- [[040-01-07-guide-Juniper-管理IP與遠端存取]] —— `irb`／`me0` 管理 IP、SSH、使用者 class、保護 RE 的 firewall filter
- [[040-01-08-guide-Juniper-埠設定與安全]] —— speed／MTU／storm-control／MAC 限制／未用埠處理
- [[040-01-09-svc-Juniper-設定備份與韌體升級]] —— `system archival`、`request system software add`、雙分割區與 snapshot
- [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]] —— 兩邊指令的完整雙欄對照表
- [[040-01-10-cmd-Cisco-IOS-基礎操作]] —— Cisco 那一側的完整內容
- [[040-01-04-guide-網路設備-交換器初次設定與連線方式]] —— console 線、鮑率、第一次開機
- [[040-01-17-guide-網路設備-交換器故障排除]] —— 跨廠牌的通用排錯流程
- [[040-01-18-guide-網路設備-網路設備盤點與文件化]] —— 序號、埠對照表、設定基準怎麼管
- [[100-02-08-guide-維運-變更管理流程]] —— 變更單、時窗、簽核與回退計畫
- [[100-02-10-guide-維運-故障排除方法論]] —— 「先恢復服務再找原因」的決策原則
- Juniper CLI User Guide：<https://www.juniper.net/documentation/us/en/software/junos/cli/>
- Junos Configuration Basics（commit／rollback／candidate）：<https://www.juniper.net/documentation/us/en/software/junos/junos-overview/>
- Day One 系列免費電子書（Juniper 官方入門教材）：<https://www.juniper.net/documentation/jnbooks/us/en/day-one-books/>
