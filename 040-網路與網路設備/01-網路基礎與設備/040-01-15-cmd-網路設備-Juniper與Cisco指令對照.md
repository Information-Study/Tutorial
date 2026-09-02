---
title: "Cisco 與 Juniper 指令對照"
desc: "JunOS 與 IOS 的一頁式指令對照，含候選設定 vs 直接生效的思維模式差異"
aliases: [JunOS Cisco 對照, 指令對照表, commit confirmed, reload in]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-05-cmd-Juniper-JunOS-基礎操作]]", "[[040-01-10-cmd-Cisco-IOS-基礎操作]]"]
updated: 2026-09-02
---

# Cisco 與 Juniper 指令對照

> [!abstract] 這篇你會學到
> - ★★★★★ 兩家的**思維模式差異**：JunOS 是「候選設定 → commit 才生效」，
>   IOS 是「打完 Enter 就生效」。搞錯這一點，你會在遠端把自己踢下線
> - ★★★★★ 兩家各自的「救命指令」：JunOS `commit confirmed`、IOS `reload in` —— 
>   遠端動設定**沒開這道保險就是在賭**
> - ★★★★ 九大類指令的左右對照：檢視狀態／介面／VLAN／Trunk／管理 IP 與路由／
>   SSH 與帳號／儲存與備份／重開與升級／除錯
> - ★★★★ 語意相近但**行為完全不同**的陷阱指令（`show configuration` vs `show running-config`、
>   `save` vs `write memory`、`rollback` vs `configure replace`）
> - ★★★ 階層式（JunOS）與扁平式（IOS）設定檔的閱讀方法，以及 `| display set` 這個橋樑

> [!warning] 未實機驗證
> 本篇指令依 Juniper JunOS（EX 系列交換器、ELS 軟體）與 Cisco IOS／IOS-XE
> （Catalyst 系列）官方文件整理，撰稿環境**沒有實體交換器可逐條驗證**。
> 不同機型、不同軟體版本的指令會有差異（尤其是 JunOS 的 ELS 與 non-ELS、
> IOS 的 `switchport` 支援與否）。**上線前務必在實驗機或維護窗口內先試跑一次**，
> 並以你手上設備的 `show version` 對應官方文件為準。

> [!info] 本篇的定位
> 本手冊的網路設備主線是 **Juniper JunOS**，Cisco IOS 為輔助對照線。
> 但這一篇是**對照速查表**，兩者並列呈現；表格一律 **JunOS 放左欄、IOS 放右欄**。
> 想學單一平台的完整操作，請看 [[040-01-05-cmd-Juniper-JunOS-基礎操作]] 或
> [[040-01-10-cmd-Cisco-IOS-基礎操作]]。

## 前置知識

- [[040-01-05-cmd-Juniper-JunOS-基礎操作]] —— operational mode 與 configuration mode 的切換
- [[040-01-10-cmd-Cisco-IOS-基礎操作]] —— user EXEC／privileged EXEC／global config 三層模式
- [[040-01-03-guide-網路設備-VLAN概念與規劃]] —— VLAN ID、access／trunk 的意義
- [[040-01-04-guide-網路設備-交換器初次設定與連線方式]] —— Console 線、開機、第一次登入
- [[010-02-05-guide-網概-MAC位址與交換器]] —— MAC 表與二層轉送的基本原理

## 觀念說明

### 為什麼不能只背指令 ★★★★★

很多人拿到對照表就開始「查表打字」，結果在 JunOS 上打完 `set` 就走人，
隔天發現設定完全沒生效；或是在 IOS 上打完 `shutdown` 才想起那是自己的上行埠。

**兩家的差別不是指令名稱，是「設定什麼時候生效」與「錯了怎麼救」。**
把下面這張圖看懂，比背 200 條指令有用。

```text
JunOS（候選設定模型）                    IOS（直接生效模型）
─────────────────────────────           ─────────────────────────────
  running configuration                    running-config
   （目前正在跑的）                          （目前正在跑的）
          │                                        ▲
          │ configure                              │ 你每按一次 Enter
          ▼                                        │ 就直接改到這裡  ★★★★★
  candidate configuration                          │
   （草稿，改再多都不影響服務）  ★★★★★      configure terminal
          │                                        │
          │ show | compare  ← 先看差異             │ （沒有草稿、沒有預覽）
          │ commit check    ← 先驗語法              │
          │ commit          ← 這一刻才生效          │
          ▼                                        ▼
  running configuration                    running-config（已生效）
          │                                        │
          │ rollback 1 → commit                    │ copy running startup
          │ （回到上一版）                           │ （不做的話重開就沒了）★★★★
          ▼                                        ▼
     上一版設定                              startup-config
```

| 面向 | JunOS | Cisco IOS | 星級 |
| --- | --- | --- | --- |
| 設定生效時機 | 打 `commit` 才生效 | **打完 Enter 立刻生效** | ★★★★★ |
| 有沒有草稿 | 有（candidate） | 沒有 | ★★★★★ |
| 改壞了怎麼回 | `rollback 1` 再 `commit`（保留 50 版） | 只能手動打回去，或 `configure replace` | ★★★★★ |
| 重開機會不會掉設定 | 不會，`commit` 就等於存檔 | **會**，要另外 `write memory` | ★★★★ |
| 設定檔長相 | 階層式（大括號巢狀） | 扁平式（一行一條，靠縮排分區） | ★★★ |
| 遠端保險機制 | `commit confirmed 5` | `reload in 10` | ★★★★★ |

### 差異一：候選設定 vs 直接生效 ★★★★★

**JunOS**：進 `configure` 之後你動的是一份**副本**。副本改到天翻地覆，
交換器還是照舊在跑。只有 `commit` 那一瞬間才整份換過去。

```text
admin@sw01> configure
Entering configuration mode

[edit]
admin@sw01# set interfaces ge-0/0/10 disable      ← 此時埠還是通的
[edit]
admin@sw01# show | compare                        ← 看看我到底改了什麼
[edit interfaces]
+   ge-0/0/10 {
+       disable;
+   }
[edit]
admin@sw01# commit                                ← 這一刻埠才真的斷
commit complete
```

**IOS**：沒有草稿。你打 `shutdown` 的那一瞬間埠就斷了。

```cisco
sw01# configure terminal
sw01(config)# interface GigabitEthernet1/0/10
sw01(config-if)# shutdown          ← 埠立刻斷，沒有反悔的空間  ★★★★★
```

> [!danger] ★★★★★ 這是遠端維護最常見的翻車點
> 在 IOS 上遠端改上行埠的 VLAN、改管理 IP、改 ACL，**只要一行打錯，你當下就斷線**，
> 而且因為設定已經生效在 running-config，重連也連不上，只能去機房插 Console。
> JunOS 因為有 candidate，只要不 commit 就永遠安全 —— 但反過來說，
> **JunOS 的人常犯的錯是「改完忘記 commit」**，以為做完了其實什麼都沒發生。

### 差異二：`commit confirmed` vs `reload in` ★★★★★

兩家都提供了「遠端動刀的保險」，但機制完全不同，別搞混。

| | JunOS `commit confirmed` | IOS `reload in` |
| --- | --- | --- |
| 做什麼 | 設定**先生效**，但時限內不再確認就**自動回上一版** | 排定一個**重開機**，時限到就重開 |
| 回到哪裡 | 上一份 committed 設定（記憶體內，不用重開） | **startup-config**（所以必須「先別存檔」） |
| 確認方式 | 再打一次 `commit`（或 `commit check` 後 `commit`） | `reload cancel` |
| 服務中斷 | 無（只是換設定） | **有，整台重開** ★★★★ |
| 星級 | ★★★★★ 必用 | ★★★★★ 必用，但代價較大 |

**JunOS 的標準遠端流程**：

```text
admin@sw01# commit confirmed 5
commit confirmed will be automatically rolled back in 5 minutes unless confirmed
commit complete

  ← 這裡去測：ping、SSH 重連、業務確認
  ← 沒問題的話：

admin@sw01# commit
commit complete
  ← 保險解除，設定定案

  ← 如果連不上了：什麼都不用做，5 分鐘後自動回到改之前
```

**IOS 的標準遠端流程**：

```cisco
sw01# reload in 10
Reload scheduled in 10 minutes by admin on vty0
Proceed with reload? [confirm]

sw01# configure terminal
  ← 這裡動你要動的設定（注意：**不要** write memory）
sw01# end

  ← 去測：ping、SSH 重連、業務確認
  ← 沒問題的話：

sw01# reload cancel
sw01# write memory        ← 這一步才把設定存進 startup-config

  ← 如果連不上了：10 分鐘後自動重開，開機讀 startup-config = 改之前的設定
```

> [!warning] ★★★★★ IOS 的 `reload in` 有兩個致命細節
> 1. **改設定前絕對不能 `write memory`**。存了就等於把壞設定寫進 startup-config，
>    重開之後還是壞的，保險完全失效。
> 2. **確認沒問題之後一定要 `reload cancel`**，不然十分鐘後整台交換器真的會重開。
>    這是本篇唯一一個「忘記做會造成計畫外停機」的指令。

### 差異三：階層式 vs 扁平式設定 ★★★

**JunOS 的設定檔是巢狀的**，用大括號分層：

```text
interfaces {
    ge-0/0/1 {
        description "PC-A1F-001";
        unit 0 {
            family ethernet-switching {
                interface-mode access;
                vlan {
                    members V10-OFFICE;
                }
            }
        }
    }
}
```

**IOS 的設定檔是扁平的**，一行一條，靠縮排表示屬於哪個介面：

```cisco
interface GigabitEthernet1/0/1
 description PC-A1F-001
 switchport mode access
 switchport access vlan 10
```

★★★★ **JunOS 的 `| display set` 是兩種世界的橋樑** —— 它把階層式設定攤平成
一行一條的 `set` 指令，長得就像 IOS，也是你**複製貼上到別台設備**的正確做法：

```text
admin@sw01> show configuration interfaces ge-0/0/1 | display set
set interfaces ge-0/0/1 description "PC-A1F-001"
set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members V10-OFFICE
```

反過來，`show configuration | display set` 的輸出可以直接在 configuration mode
用 `load set terminal` 灌回去，這是 JunOS 做批次設定與設備複製的核心手法。

### 差異四：VLAN 用名字還是用號碼 ★★★★

這是實務上最容易出錯的一個差異。

| | JunOS（ELS） | IOS |
| --- | --- | --- |
| VLAN 的識別 | **名稱**（`V10-OFFICE`），VLAN ID 是屬性 | **號碼**（`10`），名稱只是註解 |
| 定義 | `set vlans V10-OFFICE vlan-id 10` | `vlan 10` + `name OFFICE` |
| 套到埠上 | `vlan members V10-OFFICE`（用名字） | `switchport access vlan 10`（用號碼） |
| 打錯的後果 | 名字打錯 → **commit 會擋下來**（找不到該 vlan） | 號碼打錯 → **靜默建立一個新 VLAN**，埠變孤島 ★★★★ |

★★★★ IOS 這個「打錯號碼會自動建 VLAN」的行為是無數次「這台電腦怎麼上不了網」
的元凶：你想打 `vlan 10` 打成 `vlan 100`，IOS 不會抱怨，只會安靜地把埠丟進一個
**沒有任何其他成員、也沒有上行的 VLAN 100**。詳見 [[040-01-17-guide-網路設備-交換器故障排除]]。

### 差異五：介面命名 ★★★

| 概念 | JunOS | IOS |
| --- | --- | --- |
| 實體埠 | `ge-0/0/1`（1G）、`xe-0/0/49`（10G）、`et-0/0/1`（40G/100G） | `GigabitEthernet1/0/1`、`TenGigabitEthernet1/0/1` |
| 縮寫 | 不可縮寫（但可用 Tab 補完） | 可縮寫：`int gi1/0/1`、`int g1/0/1` |
| 編號意義 | `類型-機箱/線卡/埠` | `模組/子模組/埠`（堆疊時第一碼是成員編號） |
| 邏輯單元 | `ge-0/0/1.0`（unit 0），二層一律 unit 0 ★★★ | 沒有這層概念 |
| 聚合介面 | `ae0` | `Port-channel1`（縮寫 `Po1`） |
| 三層介面 | `irb.10`（ELS）／`vlan.10`（舊版） | `interface Vlan10` |
| 管理專用埠 | `me0`（獨立管理埠，不走轉送平面）★★★★ | 部分機型有 `GigabitEthernet0/0`（mgmt vrf） |

> [!note] ★★★ JunOS 的 `unit` 是什麼
> JunOS 把「實體介面」與「邏輯介面」分開。`ge-0/0/1` 是實體埠，
> `ge-0/0/1.0` 是它上面的第 0 個邏輯單元。二層交換設定一律掛在 **unit 0**，
> 所以你會一直看到 `unit 0 family ethernet-switching`。
> 三層子介面（802.1Q tagging）才會用到 unit 10、unit 20。

## 安裝或基礎操作

### 登入與模式切換 ★★★★

**JunOS 三個層次**：shell → operational mode → configuration mode。

```text
login: admin
Password:

--- JUNOS 21.4R3-S4.9 Kernel 64-bit  JNPR-12.1-20230...
admin@sw01> _                          ← operational mode，提示字元是 >

admin@sw01> configure
Entering configuration mode

[edit]
admin@sw01# _                          ← configuration mode，提示字元是 #
```

**IOS 三個層次**：user EXEC → privileged EXEC → global configuration。

```cisco
Username: admin
Password:

sw01> _                                ← user EXEC，提示字元是 >
sw01> enable
Password:
sw01# _                                ← privileged EXEC，提示字元是 #
sw01# configure terminal
sw01(config)# _                        ← global config
```

> [!warning] ★★★★★ `#` 在兩家的意義完全相反
> - **IOS 的 `#`** = privileged EXEC，是**檢視與操作**模式，打指令不會改設定。
> - **JunOS 的 `#`** = configuration mode，是**設定**模式，打 `set` 就是在改草稿。
>
> 從 IOS 轉 JunOS 的人最常犯的錯：看到 `#` 就以為安全，其實已經在編輯設定了。
> 反過來，從 JunOS 轉 IOS 的人看到 `#` 以為要 commit，結果 IOS 早就生效了。

### 模式對照表 ★★★★

| 動作 | JunOS | IOS |
| --- | --- | --- |
| 進入特權／設定 | `configure` 或 `edit` | `enable` 然後 `configure terminal` |
| 獨占式編輯（防同時改） | `configure exclusive` ★★★ | 無對等指令（靠流程管控） |
| 私有草稿（多人各改各的） | `configure private` ★★★ | 無對等指令 |
| 離開設定模式 | `exit`（未 commit 會提示）／`quit` | `end`（回 privileged）／`exit`（退一層） |
| 設定後直接離開 | `commit and-quit` | 無需（已生效），`end` 即可 |
| 中斷目前輸出 | `Ctrl+C` 或 `q` | `Ctrl+Shift+6`（部分機型 `Ctrl+C`） |
| 補完指令 | `Tab` 或 `Space` | `Tab` |
| 顯示可用選項 | `?`（不必按 Enter） | `?` |
| 分頁關閉 | `set cli screen-length 0` | `terminal length 0` ★★★ |
| 分頁寬度 | `set cli screen-width 0` | `terminal width 0` |

> [!tip] ★★★ 抓設定回來存檔前先關分頁
> 兩邊都一樣：不關掉分頁，`show` 的輸出會被 `---(more)---` 切碎，
> 貼回文字檔時滿滿的分頁符號。**每次登入先關分頁**，這是備份設定的第一步。
> 註：JunOS 的 `set cli screen-length 0` 是 operational mode 指令，只影響本次 session。

### 刪除與否定 ★★★★

| 動作 | JunOS | IOS |
| --- | --- | --- |
| 刪掉一條設定 | `delete interfaces ge-0/0/1 description` | `no description` |
| 刪掉整個區塊 | `delete interfaces ge-0/0/1` ★★★★ | `default interface Gi1/0/1` ★★★★ |
| 停用但保留設定 | `deactivate interfaces ge-0/0/1` ★★★ | 無直接對等（只能 `shutdown`） |
| 重新啟用 | `activate interfaces ge-0/0/1` | `no shutdown` |
| 加註解 | `annotate interfaces ge-0/0/1 "..."` | `!` 開頭的行（不會存進 startup） |

> [!danger] ★★★★★ `delete` 與 `default interface` 都會把整塊設定清光
> JunOS 的 `delete interfaces` **不帶任何後綴**會刪掉**所有介面**的設定。
> IOS 的 `default interface Gi1/0/1` 會把該埠恢復原廠，包含 description、VLAN、
> 安全設定全部消失。動手前先 `show | compare`（JunOS）或先把該埠設定貼出來存檔（IOS）。

## 進階應用

以下九張表是本篇的核心。**左欄 JunOS、右欄 IOS**。
標 `[op]` 表示 operational mode（JunOS）／privileged EXEC（IOS）；
標 `[cfg]` 表示設定模式。

### 一、檢視狀態 ★★★★

| 目的 | JunOS `[op]` | Cisco IOS `[op]` | 星級 |
| --- | --- | --- | --- |
| 軟體版本 | `show version` | `show version` | ★★★ |
| 硬體清單與序號 | `show chassis hardware` | `show inventory` | ★★★★ |
| 開機多久 | `show system uptime` | `show version \| include uptime` | ★★ |
| 目前告警 | `show system alarms` ★★★★ | `show logging \| include %` | ★★★★ |
| 機箱環境（溫度／風扇） | `show chassis environment` | `show environment all` | ★★★ |
| 電源狀態 | `show chassis environment power` | `show power inline`（PoE）／`show environment power` | ★★★ |
| CPU 與記憶體 | `show chassis routing-engine` | `show processes cpu sorted` | ★★★ |
| 儲存空間 | `show system storage` | `show file systems` | ★★ |
| 目前登入者 | `show system users` | `show users` | ★★ |
| 系統日誌 | `show log messages \| last 50` | `show logging` | ★★★★ |
| 即時看日誌 | `monitor start messages` ／ `monitor stop` | `terminal monitor`（配合 vty） ★★★ | ★★★ |
| 完整設定 | `show configuration` ★★★★ | `show running-config` ★★★★ | ★★★★ |
| 攤平的設定 | `show configuration \| display set` ★★★★★ | （原本就是攤平的） | ★★★★★ |
| 存檔的設定 | `show configuration`（等同，commit 即存檔） | `show startup-config` ★★★★ | ★★★★ |
| 設定差異 | `show \| compare rollback 1` ★★★★★ | `show archive config differences`（需開 archive） | ★★★★ |

> [!warning] ★★★★★ `show configuration` 與 `show running-config` 不是同一件事
> JunOS 的 `show configuration` 顯示的是**已 commit 的設定**（也就是永久設定）。
> IOS 的 `show running-config` 顯示的是**記憶體中正在跑的設定，可能還沒存檔**。
> 要看 IOS 的永久設定必須用 `show startup-config`。
> ★★★★ 稽核時抓錯這一個，你抓到的可能是重開就會消失的設定。

### 二、介面 ★★★★

| 目的 | JunOS | Cisco IOS | 星級 |
| --- | --- | --- | --- |
| 所有埠一覽 | `show interfaces terse` ★★★★★ | `show interfaces status` ★★★★★ | ★★★★★ |
| 只看有 IP 的 | `show interfaces terse \| match inet` | `show ip interface brief` | ★★★★ |
| 單埠詳細 | `show interfaces ge-0/0/1 extensive` ★★★★★ | `show interfaces Gi1/0/1` ★★★★★ | ★★★★★ |
| 只看錯誤計數 | `show interfaces ge-0/0/1 extensive \| match error` | `show interfaces counters errors` ★★★★ | ★★★★ |
| 介面描述一覽 | `show interfaces descriptions` ★★★★ | `show interfaces description` ★★★★ | ★★★★ |
| 即時流量 | `monitor interface ge-0/0/1` ★★★ | `show interfaces Gi1/0/1 \| include rate` | ★★★ |
| 全機流量排行 | `monitor interface traffic` ★★★★ | `show interfaces counters` | ★★★ |
| 光模組讀值 | `show interfaces diagnostics optics ge-0/0/49` ★★★★ | `show interfaces Gi1/0/49 transceiver detail` ★★★★ | ★★★★ |
| 清除計數器 | `clear interfaces statistics ge-0/0/1` ★★★★ | `clear counters GigabitEthernet1/0/1` ★★★★ | ★★★★ |
| 設定描述 `[cfg]` | `set interfaces ge-0/0/1 description "..."` | `interface Gi1/0/1` + `description ...` | ★★★★ |
| 關閉埠 `[cfg]` | `set interfaces ge-0/0/1 disable` | `shutdown` | ★★★★ |
| 開啟埠 `[cfg]` | `delete interfaces ge-0/0/1 disable` | `no shutdown` | ★★★★ |
| 固定速率雙工 `[cfg]` | `set interfaces ge-0/0/1 speed 1g` ＋ `link-mode full-duplex` | `speed 1000` ＋ `duplex full` | ★★★★ |
| 設 MTU `[cfg]` | `set interfaces ge-0/0/1 mtu 9216` | `mtu 9216`（部分機型為全域 `system mtu`）★★★ | ★★★ |

> [!tip] ★★★★★ 兩邊各自最該背的一條
> - JunOS：**`show interfaces terse`** —— 一頁看完全部埠的 Admin／Link 狀態。
> - IOS：**`show interfaces status`** —— 一頁看完埠名、描述、狀態、VLAN、雙工、速率、型號。
>
> 到現場接手一台不認識的交換器，先打這一條，什麼都清楚了。

`show interfaces terse` 的輸出長相：

```text
admin@sw01> show interfaces terse
Interface               Admin Link Proto    Local                 Remote
ge-0/0/0                up    up
ge-0/0/0.0              up    up   eth-switch
ge-0/0/1                up    down                                        ← 沒接線或對端關了
ge-0/0/1.0              up    down eth-switch
ge-0/0/10               down  down                                        ← 被 disable 了 ★★★★
ge-0/0/10.0             up    down eth-switch
irb                     up    up
irb.10                  up    up   inet     10.10.10.2/24
me0                     up    up
me0.0                   up    up   inet     192.168.99.2/24
```

★★★★ **Admin `down` 與 Link `down` 意義完全不同**：Admin down 是「人為關掉」，
Link down 是「實體沒通」。IOS 對應的顯示是 `administratively down` vs `notconnect`。

`show interfaces status` 的輸出長相：

```cisco
sw01# show interfaces status

Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   PC-A1F-001         connected    10           full   1000 10/100/1000BaseTX
Gi1/0/2                      notconnect   10           auto   auto 10/100/1000BaseTX
Gi1/0/3   AP-A1F-01          connected    trunk        full   1000 10/100/1000BaseTX
Gi1/0/10  RESERVED           disabled     10           auto   auto 10/100/1000BaseTX
Gi1/0/11  PRINTER            err-disabled 10           auto   auto 10/100/1000BaseTX
Te1/0/49  UPLINK-CORE-01     connected    trunk        full  10G   10Gbase-SR
```

| Status | 意義 | 星級 |
| --- | --- | --- |
| `connected` | 正常通了 | ★ |
| `notconnect` | 沒接線／對端沒開／線壞 | ★★★ |
| `disabled` | 人為 `shutdown` | ★★★ |
| `err-disabled` | **被保護機制關掉**（BPDU guard、port-security…）★★★★★ | ★★★★★ |
| `monitoring` | 被設為 SPAN 目的埠 | ★★ |

### 三、VLAN ★★★★

| 目的 | JunOS（ELS） | Cisco IOS | 星級 |
| --- | --- | --- | --- |
| 看所有 VLAN | `show vlans` ★★★★ | `show vlan brief` ★★★★ | ★★★★ |
| 看單一 VLAN 成員 | `show vlans V10-OFFICE detail` | `show vlan id 10` | ★★★ |
| 看某埠屬於哪個 VLAN | `show ethernet-switching interface ge-0/0/1` ★★★★ | `show interfaces Gi1/0/1 switchport` ★★★★ | ★★★★ |
| MAC 位址表 | `show ethernet-switching table` ★★★★★ | `show mac address-table` ★★★★★ | ★★★★★ |
| 查某個 MAC 在哪個埠 | `show ethernet-switching table \| match 00:1b:21` | `show mac address-table address 001b.2100.0000` | ★★★★ |
| 某埠學到幾個 MAC | `show ethernet-switching table interface ge-0/0/1` | `show mac address-table interface Gi1/0/1` | ★★★★ |
| 清 MAC 表 | `clear ethernet-switching table` ★★★ | `clear mac address-table dynamic` ★★★ | ★★★ |
| 建立 VLAN `[cfg]` | `set vlans V10-OFFICE vlan-id 10` | `vlan 10` + `name OFFICE` | ★★★★ |
| 設為 access 埠 `[cfg]` | `set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access` | `switchport mode access` | ★★★★ |
| 指定 access VLAN `[cfg]` | `set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members V10-OFFICE` | `switchport access vlan 10` | ★★★★ |
| Voice VLAN `[cfg]` | `set switch-options voip interface ge-0/0/1 vlan V20-VOICE` ★★★ | `switchport voice vlan 20` ★★★ | ★★★ |

★★★ **MAC 位址格式兩家寫法不同**：JunOS 用冒號分隔（`00:1b:21:aa:bb:cc`），
IOS 用點分隔的三組（`001b.21aa.bbcc`）。從一邊複製到另一邊要轉換，這是查 MAC 時的常見卡點。

### 四、Trunk ★★★★★

| 目的 | JunOS（ELS） | Cisco IOS | 星級 |
| --- | --- | --- | --- |
| 看 trunk 狀態 | `show ethernet-switching interface` | `show interfaces trunk` ★★★★★ | ★★★★★ |
| 設為 trunk `[cfg]` | `set interfaces ge-0/0/48 unit 0 family ethernet-switching interface-mode trunk` | `switchport mode trunk` | ★★★★ |
| 指定允許的 VLAN `[cfg]` | `set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members [ V10-OFFICE V20-VOICE ]` | `switchport trunk allowed vlan 10,20` ★★★★★ | ★★★★★ |
| 允許全部 VLAN `[cfg]` | `vlan members all` ★★★ | `switchport trunk allowed vlan all` ★★★ | ★★★ |
| **追加**一個 VLAN `[cfg]` | 再打一次 `set ... vlan members V30-SRV`（自動累加）★★★★ | `switchport trunk allowed vlan add 30` ★★★★★ | ★★★★★ |
| 移除一個 VLAN `[cfg]` | `delete interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members V30-SRV` | `switchport trunk allowed vlan remove 30` | ★★★★ |
| Native VLAN `[cfg]` | `set interfaces ge-0/0/48 native-vlan-id 999` ★★★★ | `switchport trunk native vlan 999` ★★★★ | ★★★★ |
| 關閉自動協商 `[cfg]` | （JunOS 無 DTP，本來就不協商）★★★★ | `switchport nonegotiate` ★★★★ | ★★★★ |

> [!danger] ★★★★★ IOS 的 `switchport trunk allowed vlan 30` 會**取代**而不是**追加**
> 這是 Cisco 平台最惡名昭彰的一行指令。你想「再加一個 VLAN 30」，
> 打了 `switchport trunk allowed vlan 30`，結果原本允許的 10、20 **全部消失**，
> 該 trunk 上兩個 VLAN 的流量瞬間全斷。
> **要追加一定要打 `add`：`switchport trunk allowed vlan add 30`。**
> JunOS 這邊 `set ... vlan members` 天生就是累加語意，反而不會踩到。

> [!warning] ★★★★ JunOS 沒有 DTP，所以 trunk 不會「自己協商出來」
> Cisco 的預設 `switchport mode dynamic auto/desirable` 會讓兩台 Cisco 自動變成 trunk。
> Juniper 沒有這個機制，**兩端都必須手動設成 trunk**。
> 混廠環境（Cisco 接 Juniper）務必在 Cisco 端明確 `switchport mode trunk` ＋ `switchport nonegotiate`，
> 否則 Cisco 端會停在 access 模式，只有 native VLAN 通得過去 —— 症狀就是「通一半」。

### 五、管理 IP 與路由 ★★★★

| 目的 | JunOS | Cisco IOS | 星級 |
| --- | --- | --- | --- |
| 看路由表 | `show route` ★★★★ | `show ip route` ★★★★ | ★★★★ |
| 看預設路由 | `show route 0.0.0.0/0` | `show ip route 0.0.0.0` | ★★★ |
| 看 ARP 表 | `show arp` ★★★★ | `show ip arp` ★★★★ | ★★★★ |
| 清 ARP | `clear arp` | `clear ip arp` | ★★ |
| ping | `ping 10.10.10.1 count 5` ★★★ | `ping 10.10.10.1` | ★★★ |
| 指定來源 ping | `ping 8.8.8.8 source 10.10.10.2` ★★★★ | `ping 8.8.8.8 source Vlan10` ★★★★ | ★★★★ |
| traceroute | `traceroute 8.8.8.8` | `traceroute 8.8.8.8` | ★★★ |
| 建三層介面 `[cfg]` | `set interfaces irb unit 10 family inet address 10.10.10.2/24` | `interface Vlan10` + `ip address 10.10.10.2 255.255.255.0` | ★★★★ |
| 把 VLAN 綁三層介面 `[cfg]` | `set vlans V10-OFFICE l3-interface irb.10` ★★★★ | （`interface Vlan10` 自動對應 VLAN 10） | ★★★★ |
| 帶外管理埠 `[cfg]` | `set interfaces me0 unit 0 family inet address 192.168.99.2/24` ★★★★ | `interface GigabitEthernet0/0` + `ip address ...`（視機型） | ★★★★ |
| 預設路由 `[cfg]` | `set routing-options static route 0.0.0.0/0 next-hop 10.10.10.1` | `ip route 0.0.0.0 0.0.0.0 10.10.10.1` | ★★★★ |
| 開三層轉送 `[cfg]` | （EX 預設即可路由 irb 介面） | `ip routing` ★★★★（IOS 交換器預設是關的） | ★★★★ |
| 主機名稱 `[cfg]` | `set system host-name sw-a1f-01` | `hostname sw-a1f-01` | ★★★ |
| DNS `[cfg]` | `set system name-server 10.10.20.10` | `ip name-server 10.10.20.10` | ★★ |
| NTP `[cfg]` | `set system ntp server 10.10.20.11` ★★★★ | `ntp server 10.10.20.11` ★★★★ | ★★★★ |
| 時區 `[cfg]` | `set system time-zone Asia/Taipei` | `clock timezone CST 8` | ★★★ |
| syslog 外送 `[cfg]` | `set system syslog host 10.10.20.5 any notice` ★★★★ | `logging host 10.10.20.5` ★★★★ | ★★★★ |

> [!warning] ★★★★ 網路遮罩寫法不同，複製貼上必翻車
> JunOS 一律用 **CIDR**（`10.10.10.2/24`），IOS 大多用**點分十進位遮罩**
> （`10.10.10.2 255.255.255.0`）。`ip route` 也是：`ip route 0.0.0.0 0.0.0.0 next-hop`。
> IOS 只有 `ip prefix-list`、OSPF `network` 等少數地方用 wildcard mask（`0.0.0.255`），
> 那又是第三種寫法，別搞混。

### 六、SSH 與帳號 ★★★★

| 目的 | JunOS | Cisco IOS | 星級 |
| --- | --- | --- | --- |
| 啟用 SSH `[cfg]` | `set system services ssh` ★★★★ | `crypto key generate rsa modulus 2048` ＋ `ip ssh version 2` ★★★★ | ★★★★ |
| 停用 telnet `[cfg]` | `delete system services telnet` ★★★★★ | `line vty 0 15` + `transport input ssh` ★★★★★ | ★★★★★ |
| 禁止 root 直接 SSH `[cfg]` | `set system services ssh root-login deny` ★★★★ | （IOS 無 root 概念，用 `enable secret`） | ★★★★ |
| 建立本機帳號 `[cfg]` | `set system login user netadm class super-user authentication plain-text-password` | `username netadm privilege 15 secret <pw>` | ★★★★ |
| 加 SSH 公鑰 `[cfg]` | `set system login user netadm authentication ssh-rsa "ssh-rsa AAAA..."` ★★★★ | `ip ssh pubkey-chain` → `username netadm` → `key-string` ★★★ | ★★★★ |
| 設定 enable 密碼 `[cfg]` | （無此概念，靠 class 授權） | `enable secret <pw>` ★★★★ | ★★★★ |
| 加密設定檔中的密碼 `[cfg]` | （JunOS 預設就雜湊儲存）★★★★ | `service password-encryption` ★★★（只是弱混淆，非加密） | ★★★★ |
| 登入前標語 `[cfg]` | `set system login message "..."` ★★★ | `banner motd ^C ... ^C` ★★★ | ★★★ |
| 閒置逾時 `[cfg]` | `set system login idle-timeout 10` ★★★ | `line vty 0 15` + `exec-timeout 10 0` ★★★ | ★★★ |
| 限制管理來源 `[cfg]` | firewall filter 套 `lo0` ★★★★ | `line vty 0 15` + `access-class 10 in` ★★★★ | ★★★★ |
| RADIUS 認證 `[cfg]` | `set system radius-server 10.10.20.20 secret <s>` ＋ `set system authentication-order [ radius password ]` ★★★★ | `aaa new-model` ＋ `radius server ...` ＋ `aaa authentication login default group radius local` ★★★★ | ★★★★ |
| 看誰登入過 | `show system login`／`show log messages \| match "login"` | `show logging \| include LOGIN` | ★★★ |

> [!danger] ★★★★★ `authentication-order` 一定要留 `password` 當後路
> JunOS 的 `set system authentication-order [ radius password ]` 表示先問 RADIUS、
> RADIUS 沒回應才用本機密碼。**如果只寫 `radius`，RADIUS 掛掉時你就完全登不進去**，
> 只能去現場插 Console。IOS 的 `aaa authentication login default group radius local`
> 最後那個 `local` 是同樣的道理，**絕對不能省**。

### 七、儲存與備份 ★★★★★

| 目的 | JunOS | Cisco IOS | 星級 |
| --- | --- | --- | --- |
| 存檔（讓設定活過重開） | `commit` ★★★★★（commit 即存檔） | `write memory` 或 `copy running-config startup-config` ★★★★★ | ★★★★★ |
| 存成本機檔案 | `save /var/tmp/sw01.conf` `[cfg]` ★★★★ | `copy running-config flash:sw01.cfg` ★★★★ | ★★★★ |
| 送到 SCP 伺服器 | `file copy /var/tmp/sw01.conf scp://user@10.10.20.30//backup/` ★★★★ | `copy running-config scp://user@10.10.20.30/backup/sw01.cfg` ★★★★ | ★★★★ |
| 送到 TFTP | `file copy /var/tmp/sw01.conf tftp://10.10.20.30/sw01.conf` | `copy running-config tftp:` | ★★★ |
| 自動備份（每次 commit） | `set system archival configuration transfer-on-commit` ＋ `archive-sites "scp://..."` ★★★★★ | `archive` ＋ `path scp://...` ＋ `write-memory` ★★★★★ | ★★★★★ |
| 定時備份 | `set system archival configuration transfer-interval 60` | `archive` ＋ `time-period 1440` | ★★★★ |
| 看歷史版本 | `show system commit` ★★★★★ | `show archive` ★★★★ | ★★★★ |
| 比對前一版 | `show \| compare rollback 1` `[cfg]` ★★★★★ | `show archive config differences` ★★★★ | ★★★★★ |
| 回到前一版 | `rollback 1` ＋ `commit` ★★★★★ | `configure replace flash:sw01.cfg` ★★★★ | ★★★★★ |
| 回到原廠 | `load factory-default` ＋ 設 root 密碼 ＋ `commit` ★★★★★ | `write erase` ＋ `reload` ★★★★★ | ★★★★★ |
| 匯入設定（覆蓋） | `load override /var/tmp/sw01.conf` ★★★★★ | `configure replace flash:sw01.cfg` ★★★★★ | ★★★★★ |
| 匯入設定（合併） | `load merge /var/tmp/part.conf` ★★★★ | `copy flash:part.cfg running-config` ★★★★ | ★★★★ |
| 貼上 set 指令 | `load set terminal` ★★★★★ | 直接在 `config t` 下貼 | ★★★★★ |

> [!danger] ★★★★★ IOS 的 `copy tftp: running-config` 是**合併**不是**覆蓋**
> 很多人以為「把備份灌回去」就會回到備份當時的樣子 —— 錯。
> `copy ... running-config` 是把備份檔的每一行**當成你在 config 模式打進去**，
> 所以**備份檔裡沒有的設定會原封不動留著**。要真正覆蓋必須用
> `configure replace flash:sw01.cfg`。
> JunOS 對應的差別是 `load merge`（合併）與 `load override`（整份取代）。

★★★★★ `show system commit` 是 JunOS 最有價值的稽核指令之一：

```text
admin@sw01> show system commit
0   2026-09-02 14:22:10 CST by netadm via cli
    commit confirmed, rollback in 5mins
1   2026-09-02 09:05:44 CST by netadm via cli
    "新增 V30-SRV 到 ae0 trunk"
2   2026-08-28 16:40:02 CST by admin via netconf
3   2026-08-15 11:12:33 CST by netadm via cli
```

搭配 `set system commit ... ` 相關的 commit comment 習慣（`commit comment "工單 CHG-2026-0912"`），
你等於在交換器上有了一份**免費的變更履歷**。詳見 [[040-01-18-guide-網路設備-網路設備盤點與文件化]]。

### 八、重開與升級 ★★★★★

| 目的 | JunOS | Cisco IOS | 星級 |
| --- | --- | --- | --- |
| 立刻重開 | `request system reboot` ★★★★★ | `reload` ★★★★★ | ★★★★★ |
| 排定重開（保險） | （用 `commit confirmed` 取代）★★★★★ | `reload in 10` ★★★★★ | ★★★★★ |
| 指定時間重開 | `request system reboot at 23:00` ★★★★ | `reload at 23:00` ★★★★ | ★★★★ |
| 取消排定重開 | `clear system reboot` ★★★★ | `reload cancel` ★★★★★ | ★★★★★ |
| 關機（可斷電） | `request system halt` ★★★★ | （IOS 交換器一般直接斷電） | ★★★★ |
| 看目前韌體 | `show version` | `show version` | ★★★ |
| 看可開機的映像 | `show system snapshot media internal` ★★★ | `show boot` ／ `dir flash:` ★★★★ | ★★★ |
| 上傳映像 | `file copy scp://user@host//path/jinstall.tgz /var/tmp/` ★★★★ | `copy scp://user@host/c3850.bin flash:` ★★★★ | ★★★★ |
| 安裝韌體 | `request system software add /var/tmp/jinstall.tgz` ★★★★★ | `install add file flash:xxx.bin activate commit`（IOS-XE）★★★★★ | ★★★★★ |
| 安裝後重開 | `request system software add ... reboot` | （`install ... activate` 會自動重開） | ★★★★★ |
| 備份開機映像 | `request system snapshot` ★★★★ | （靠 flash 內保留舊映像） | ★★★★ |
| 指定開機檔 | （由 snapshot／package 管理） | `boot system flash:xxx.bin` ★★★★ | ★★★★ |

> [!danger] ★★★★★ 升級前四件事，缺一件都不要按下去
> 1. **設定備份已抓下來並確認可讀**（不是「應該有備份」，是打開看過）
> 2. **韌體檔的 checksum 比對過**（`file checksum md5 /var/tmp/xxx.tgz`／`verify /md5 flash:xxx.bin`）
> 3. **Console 線已接好或 KVM 可用** —— 升級失敗時網路一定連不上
> 4. **確認可用空間夠**（`show system storage`／`dir flash:`），空間不足是升級中斷最常見原因
>
> 詳細流程見 [[040-01-09-svc-Juniper-設定備份與韌體升級]] 與 [[040-01-14-svc-Cisco-設定備份與韌體升級]]。

### 九、除錯 ★★★★

| 目的 | JunOS | Cisco IOS | 星級 |
| --- | --- | --- | --- |
| 鄰居探索 | `show lldp neighbors` ★★★★★ | `show cdp neighbors detail` ／ `show lldp neighbors` ★★★★★ | ★★★★★ |
| STP 全貌 | `show spanning-tree bridge` ★★★★ | `show spanning-tree summary` ★★★★ | ★★★★ |
| STP 埠角色 | `show spanning-tree interface` ★★★★ | `show spanning-tree` ★★★★ | ★★★★ |
| 誰是根橋 | `show spanning-tree bridge \| match Root` | `show spanning-tree root` ★★★★ | ★★★★ |
| 被保護擋掉的埠 | `show spanning-tree interface \| match BLK` | `show spanning-tree inconsistentports` ★★★★★ | ★★★★★ |
| 聚合狀態 | `show lacp interfaces ae0` ★★★★★ | `show etherchannel summary` ★★★★★ | ★★★★★ |
| 抓封包 | `monitor traffic interface ge-0/0/1` ★★★★ | `monitor capture`（IOS-XE）★★★ | ★★★★ |
| 埠鏡像 `[cfg]` | `set forwarding-options analyzer A input ingress interface ge-0/0/1` ＋ `output interface ge-0/0/48` ★★★★ | `monitor session 1 source interface Gi1/0/1` ＋ `destination interface Gi1/0/48` ★★★★ | ★★★★ |
| 看 err-disable 原因 | `show log messages \| match ge-0/0/11` | `show interfaces status err-disabled` ★★★★★ | ★★★★★ |
| 恢復 err-disable | 排除原因後 `clear ethernet-switching ...` 或關開埠 | `shutdown` ＋ `no shutdown`，或設 `errdisable recovery` ★★★★ | ★★★★ |
| DHCP snooping 綁定表 | `show dhcp-security binding` ★★★ | `show ip dhcp snooping binding` ★★★ | ★★★ |
| 儲存空間滿了 | `request system storage cleanup` ★★★★ | `delete flash:xxx` ／ `squeeze flash:` ★★★ | ★★★ |

> [!tip] ★★★★★ 到現場的前五條指令（不分廠牌）
> 1. **鄰居**：對面是誰？（`show lldp neighbors`）
> 2. **埠狀態**：哪些通、哪些不通？（`show interfaces terse` / `show interfaces status`）
> 3. **錯誤計數**：有沒有實體層問題？（`show interfaces ... extensive` / `show interfaces counters errors`）
> 4. **MAC 表**：目標裝置學到了嗎？（`show ethernet-switching table` / `show mac address-table`）
> 5. **STP**：拓樸有沒有在震盪？（`show spanning-tree ...`）
>
> 這五條在 [[040-01-17-guide-網路設備-交換器故障排除]] 有完整的判讀流程。

## 完整實戰範例

**情境**：機房新增一個伺服器 VLAN `V30-SRV`（VLAN ID 30，網段 10.10.30.0/24），
需要在接取層交換器 `sw-a1f-01` 上：

1. 建立 VLAN 30
2. 把 `ge-0/0/20` ~ `ge-0/0/23`（IOS：`Gi1/0/20-23`）設成該 VLAN 的 access 埠
3. 在往核心的上行 trunk 上放行 VLAN 30
4. 在交換器上建 VLAN 30 的三層介面 10.10.30.2/24（暫做測試用）
5. 全程遠端操作，**不能把自己踢下線**

同一個需求，兩個平台各做一次。**你會看到，難的不是指令，是保險機制。**

### 步驟 0：兩邊都先做的事 ★★★★

```text
# JunOS
admin@sw01> set cli screen-length 0                      ← 關分頁
admin@sw01> show configuration | display set > /var/tmp/before.set   ← 存一份改前設定
admin@sw01> show interfaces trunk 2>/dev/null; show ethernet-switching interface ge-0/0/48
admin@sw01> show vlans
```

```cisco
! IOS
sw01# terminal length 0
sw01# show running-config              ← 全文複製到本機文字檔，這就是你的回退依據
sw01# show interfaces trunk
sw01# show vlan brief
```

> [!warning] ★★★★★ 「改之前先存一份」不是形式主義
> IOS 沒有 rollback，**你貼出來的那份 running-config 就是唯一的回退依據**。
> JunOS 雖然有 rollback 50 版，但如果過程中發生斷電、Routing Engine 切換，
> 那份 `before.set` 一樣是保命符。

### JunOS 版完整流程

**步驟 1：進設定模式（用 exclusive 防同事同時改）**

```text
admin@sw01> configure exclusive
warning: uncommitted changes will be discarded on exit
Entering configuration mode

[edit]
admin@sw01#
```

**步驟 2：建立 VLAN**

```text
[edit]
admin@sw01# set vlans V30-SRV vlan-id 30
admin@sw01# set vlans V30-SRV description "Server segment 10.10.30.0/24"
```

**步驟 3：設定四個 access 埠**

```text
[edit]
admin@sw01# set interfaces ge-0/0/20 description "SRV-ESX-01-NIC0"
admin@sw01# set interfaces ge-0/0/20 unit 0 family ethernet-switching interface-mode access
admin@sw01# set interfaces ge-0/0/20 unit 0 family ethernet-switching vlan members V30-SRV
admin@sw01# set interfaces ge-0/0/21 description "SRV-ESX-02-NIC0"
admin@sw01# set interfaces ge-0/0/21 unit 0 family ethernet-switching interface-mode access
admin@sw01# set interfaces ge-0/0/21 unit 0 family ethernet-switching vlan members V30-SRV
admin@sw01# set interfaces ge-0/0/22 description "SRV-BACKUP-01"
admin@sw01# set interfaces ge-0/0/22 unit 0 family ethernet-switching interface-mode access
admin@sw01# set interfaces ge-0/0/22 unit 0 family ethernet-switching vlan members V30-SRV
admin@sw01# set interfaces ge-0/0/23 description "RESERVED-SRV"
admin@sw01# set interfaces ge-0/0/23 unit 0 family ethernet-switching interface-mode access
admin@sw01# set interfaces ge-0/0/23 unit 0 family ethernet-switching vlan members V30-SRV
```

**步驟 4：上行 trunk 放行 VLAN 30（★★★★★ 危險動作）**

```text
[edit]
admin@sw01# set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members V30-SRV
```

★★★★★ JunOS 這裡是**累加**語意，不會動到原本的 `V10-OFFICE`、`V20-VOICE`。
但**還是要用 `show | compare` 確認**：

```text
[edit]
admin@sw01# show | compare
[edit interfaces]
+   ge-0/0/20 {
+       description "SRV-ESX-01-NIC0";
+       unit 0 {
+           family ethernet-switching {
+               interface-mode access;
+               vlan {
+                   members V30-SRV;
+               }
+           }
+       }
+   }
...
[edit interfaces ge-0/0/48 unit 0 family ethernet-switching vlan]
        members [ V10-OFFICE V20-VOICE ];
+       members V30-SRV;                       ← 只多了這行，原本的都在  ★★★★★
[edit]
+  vlans {
+      V30-SRV {
+          description "Server segment 10.10.30.0/24";
+          vlan-id 30;
+      }
+  }
```

**步驟 5：建三層介面**

```text
[edit]
admin@sw01# set interfaces irb unit 30 family inet address 10.10.30.2/24
admin@sw01# set vlans V30-SRV l3-interface irb.30
```

**步驟 6：語法檢查（不生效，純驗證）**

```text
[edit]
admin@sw01# commit check
configuration check succeeds
```

★★★★★ `commit check` 只驗語法與參照完整性（例如 `l3-interface irb.30` 有沒有對應的
`irb unit 30`）。它**不會**告訴你「這個 VLAN ID 是不是你要的」。語意還是要靠 `show | compare` 自己看。

**步驟 7：帶保險上線**

```text
[edit]
admin@sw01# commit confirmed 5 comment "CHG-2026-0912 新增 V30-SRV"
commit confirmed will be automatically rolled back in 5 minutes unless confirmed
commit complete
```

**步驟 8：五分鐘內完成驗證**

```text
admin@sw01# run show vlans V30-SRV            ← 在 config mode 用 run 執行 op 指令  ★★★★
Routing instance        VLAN name             Tag          Interfaces
default-switch          V30-SRV               30
                                                           ge-0/0/20.0
                                                           ge-0/0/21.0
                                                           ge-0/0/22.0
                                                           ge-0/0/23.0
                                                           ge-0/0/48.0*

admin@sw01# run show interfaces terse irb.30
Interface               Admin Link Proto    Local                 Remote
irb.30                  up    up   inet     10.10.30.2/24

admin@sw01# run ping 10.10.30.1 count 3       ← ping 核心的 VLAN 30 閘道
PING 10.10.30.1 (10.10.30.1): 56 data bytes
64 bytes from 10.10.30.1: icmp_seq=0 ttl=64 time=0.512 ms
64 bytes from 10.10.30.1: icmp_seq=1 ttl=64 time=0.487 ms
64 bytes from 10.10.30.1: icmp_seq=2 ttl=64 time=0.501 ms
--- 10.10.30.1 ping statistics ---
3 packets transmitted, 3 packets received, 0% packet loss
```

★★★★ `ge-0/0/48.0*` 後面那個星號表示**這是 trunk 埠上的 tagged 成員**，正是我們要的。

**步驟 9：確認定案**

```text
[edit]
admin@sw01# commit comment "CHG-2026-0912 確認"
commit complete

[edit]
admin@sw01# exit
Exiting configuration mode

admin@sw01> show system commit | head -3
0   2026-09-02 15:04:22 CST by netadm via cli
    "CHG-2026-0912 確認"
1   2026-09-02 15:00:11 CST by netadm via cli
```

**如果驗證失敗**：什麼都不用做。五分鐘後 JunOS 自動回滾，你的 SSH 會恢復。
主動想立刻回去的話：

```text
[edit]
admin@sw01# rollback 1
load complete
admin@sw01# commit
commit complete
```

### IOS 版完整流程

**步驟 1：先開保險（★★★★★ 這是 IOS 版與 JunOS 版最大的差別）**

```cisco
sw01# reload in 10
Reload scheduled in 10 minutes by netadm on vty0
Reload reason: change CHG-2026-0912
Proceed with reload? [confirm]y

sw01# show reload
Reload scheduled in 9 minutes and 51 seconds by netadm on vty0
```

**步驟 2：建立 VLAN**

```cisco
sw01# configure terminal
sw01(config)# vlan 30
sw01(config-vlan)# name SRV
sw01(config-vlan)# exit
```

**步驟 3：設定四個 access 埠（用 `interface range` 一次做完）**

```cisco
sw01(config)# interface range GigabitEthernet1/0/20 - 23
sw01(config-if-range)# switchport mode access
sw01(config-if-range)# switchport access vlan 30
sw01(config-if-range)# spanning-tree portfast
sw01(config-if-range)# exit
sw01(config)# interface Gi1/0/20
sw01(config-if)# description SRV-ESX-01-NIC0
sw01(config-if)# exit
sw01(config)# interface Gi1/0/21
sw01(config-if)# description SRV-ESX-02-NIC0
sw01(config-if)# exit
```

**步驟 4：上行 trunk 放行 VLAN 30（★★★★★ 最容易全斷的一行）**

```cisco
sw01(config)# interface TenGigabitEthernet1/0/49
sw01(config-if)# switchport trunk allowed vlan add 30
                                              ^^^
                    ← 沒有這個 add，VLAN 10、20 立刻全斷  ★★★★★
sw01(config-if)# exit
```

**步驟 5：建三層介面**

```cisco
sw01(config)# interface Vlan30
sw01(config-if)# description SRV-SVI
sw01(config-if)# ip address 10.10.30.2 255.255.255.0
sw01(config-if)# no shutdown
sw01(config-if)# end
```

**步驟 6：驗證（保險還在跑，剩下大約 6 分鐘）**

```cisco
sw01# show vlan id 30

VLAN Name           Status    Ports
---- -------------- --------- -------------------------------
30   SRV            active    Gi1/0/20, Gi1/0/21, Gi1/0/22, Gi1/0/23

sw01# show interfaces trunk

Port        Mode      Encapsulation  Status     Native vlan
Te1/0/49    on        802.1q         trunking   999

Port        Vlans allowed on trunk
Te1/0/49    10,20,30                      ← 10、20 都還在，30 加上去了  ★★★★★

Port        Vlans allowed and active in management domain
Te1/0/49    10,20,30

sw01# show ip interface brief | include Vlan30
Vlan30                 10.10.30.2      YES manual up                    up

sw01# ping 10.10.30.1
Type escape sequence to abort.
Sending 5, 100-byte ICMP Echos to 10.10.30.1, timeout is 2 seconds:
!!!!!
Success rate is 100 percent (5/5), round-trip min/avg/max = 1/1/2 ms
```

**步驟 7：解除保險並存檔（★★★★★ 順序不能顛倒也不能漏）**

```cisco
sw01# reload cancel

***
*** --- SHUTDOWN ABORTED ---
***

sw01# write memory
Building configuration...
[OK]

sw01# show archive
The maximum archive configurations allowed is 10.
The next archive file will be named flash:/archive/sw01-4
 Archive #  Name
   1        flash:/archive/sw01-1
   2        flash:/archive/sw01-2
   3        flash:/archive/sw01-3 <- Most Recent
```

**如果驗證失敗**：**什麼都不要做，也絕對不要 `write memory`。**
十分鐘一到交換器自動重開，開機讀取 startup-config（＝改之前的設定），一切復原。
如果你當下還連得上、想立刻回去：

```cisco
sw01# configure replace flash:sw01-before.cfg
This will apply all necessary additions and deletions
to replace the current running configuration with the
contents of the specified configuration file, which is
assumed to be a complete configuration, not a partial
configuration. Enter Y if you are sure you want to proceed. ? [no]: y
```

### 兩版流程的差別總結 ★★★★★

| 步驟 | JunOS | IOS |
| --- | --- | --- |
| 改設定會不會立刻影響服務 | 不會（candidate） | **會** |
| 上線前可以看差異嗎 | 可以（`show \| compare`） | 不行 |
| 保險機制 | `commit confirmed 5`（不重開） | `reload in 10`（**會重開**） |
| 保險什麼時候開 | commit 的那一刻 | **改設定之前** |
| 要不要另外存檔 | 不用，commit 即存檔 | **要**，`write memory` |
| 失敗回退 | 等它自動 rollback，或 `rollback 1` + `commit` | 等它重開，或 `configure replace` |
| 全程風險 | 低 | 中～高（保險本身就是一次重開） |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 | 星級 |
| --- | --- | --- | --- |
| JunOS 打完 `set` 一堆指令，設定完全沒生效 | **忘記 `commit`**，改的只是 candidate | 回 configuration mode，`show \| compare` 確認草稿還在，然後 `commit` | ★★★★★ |
| JunOS `exit` 時出現 `The configuration has been changed but not committed` | 有未提交的變更 | 要留就 `commit`；要丟就 `rollback 0` 再 `exit` | ★★★★ |
| IOS 改完設定隔天重開全沒了 | **沒有 `write memory`**，只改到 running-config | 每次改完必存；用 `archive` + `write-memory` 自動化 | ★★★★★ |
| IOS 打 `switchport trunk allowed vlan 30` 後，其他 VLAN 全斷 | **少了 `add`**，這是取代語意 | `switchport trunk allowed vlan 10,20,30` 補回去；日後一律用 `add`/`remove` | ★★★★★ |
| JunOS `commit` 出現 `error: interface-range ... not found` 之類參照錯誤 | 引用了不存在的 VLAN 名稱／介面 | `commit check` 看完整錯誤，補上缺的定義再 commit | ★★★★ |
| JunOS `commit` 出現 `error: configuration database locked by user admin` | 別人用 `configure exclusive` 佔住了 | `show system users` 找出是誰；確認無人在用可用 `request system logout user <name>` | ★★★★ |
| 遠端改完就斷線，重連也連不上（IOS） | 設定已生效且已存檔，沒有回退機制 | 只能到現場插 Console；**下次務必先 `reload in`** | ★★★★★ |
| JunOS `commit confirmed` 後過五分鐘設定不見了 | 忘記再打一次 `commit` 確認 | 這是設計如此；重做一次並記得確認 | ★★★★ |
| IOS 十分鐘後交換器突然重開 | `reload in` 之後**忘記 `reload cancel`** | 每次驗證完立刻 `reload cancel`；寫進 SOP 檢查表 | ★★★★★ |
| 從備份還原 IOS 設定，舊的錯誤設定還在 | `copy tftp: running-config` 是**合併**不是覆蓋 | 用 `configure replace flash:xxx.cfg` | ★★★★★ |
| JunOS 貼上一大段 `set` 指令，很多行被吃掉 | 終端機貼上速度太快，或沒進 `load set terminal` | 用 `load set terminal`，貼完按 `Ctrl+D` 結束 | ★★★★ |
| Cisco 端與 Juniper 端接起來只有一個 VLAN 通 | Cisco 停在 DTP `dynamic auto`，沒真的變 trunk | Cisco 端明確 `switchport mode trunk` ＋ `switchport nonegotiate` | ★★★★ |
| 兩端 native VLAN 不一致，log 一直跳 `Native VLAN mismatch` | 一端 native 1、另一端 native 999 | 統一 native VLAN；建議兩端都用一個**沒有任何主機**的 VLAN | ★★★★ |
| `show interfaces status` 顯示 `err-disabled` | BPDU guard／port-security／UDLD 觸發 | `show interfaces status err-disabled` 看原因，排除後 `shutdown`＋`no shutdown` | ★★★★★ |
| JunOS 找不到 `show vlan brief` 這條指令 | 那是 IOS 語法 | JunOS 是 `show vlans`；用 `?` 逐層探索正確語法 | ★★★ |
| IOS 貼上 JunOS 抓來的 IP，報 `Invalid input detected` | JunOS 用 CIDR、IOS 用點分遮罩 | `10.10.30.2/24` → `ip address 10.10.30.2 255.255.255.0` | ★★★★ |
| 查 MAC 查不到，但裝置明明在線 | MAC 格式寫錯（冒號 vs 點分） | JunOS `00:1b:21:aa:bb:cc`／IOS `001b.21aa.bbcc` | ★★★ |
| `show configuration` 輸出被 `---(more)---` 切碎 | 沒關分頁 | JunOS `set cli screen-length 0`／IOS `terminal length 0` | ★★★ |
| JunOS `rollback 1` 之後設定還是舊的 | `rollback` 只是把舊版載進 candidate，**還要 `commit`** | `rollback 1` 後接 `commit` | ★★★★★ |

## 安全性注意事項

> [!danger] ★★★★★ 三條不可逆、會直接毀掉正式環境的指令
> | 指令 | 後果 |
> | --- | --- |
> | `request system zeroize`（JunOS） | 抹掉**所有**設定、日誌、金鑰，回到出廠且**無法 rollback**。只能重新從 Console 建置 |
> | `write erase` ＋ `reload`（IOS） | 清空 startup-config 後重開，開機後是空白設定，遠端完全連不上 |
> | `delete interfaces`（JunOS，不帶介面名） | 刪掉**全部**介面設定；一旦 commit，整台交換器變啞巴 |
>
> 這三條**只在你人在機房、Console 線已接、且已確認備份可還原**時才輸入。

### 帳號與存取 ★★★★

| 項目 | 建議 | 星級 |
| --- | --- | --- |
| Telnet | **一律關閉**。JunOS `delete system services telnet`；IOS `transport input ssh` | ★★★★★ |
| HTTP 管理介面 | 關閉或改 HTTPS。JunOS `delete system services web-management http` | ★★★★ |
| 預設帳號密碼 | 上架第一件事就改；`admin/admin`、`root` 空密碼是稽核必扣分項 | ★★★★★ |
| 管理來源限制 | 只允許管理網段連進來（JunOS 用 `lo0` firewall filter，IOS 用 `access-class`） | ★★★★ |
| 共用帳號 | 禁止。每人一個帳號才追得到是誰改的 | ★★★★ |
| SNMP community | 不要用 `public`/`private`；能用 SNMPv3 就用 v3 | ★★★★ |
| 帶外管理埠（`me0`） | 接到**獨立的管理交換器**，不要跟業務網段混在一起 | ★★★★ |
| 閒置逾時 | 設 10 分鐘，避免有人開著 session 去吃飯 | ★★★ |

### 設定安全 ★★★★

- ★★★★★ **設定備份要當機敏資料保管**。設定檔裡有雜湊過的密碼、SNMP community、
  RADIUS shared secret、完整網段規劃 —— 外洩等於把整張網路藍圖送人。
  放 git 也要放**私有 repo**，並考慮把 secret 段落遮蔽，做法見
  [[040-01-18-guide-網路設備-網路設備盤點與文件化]]。
- ★★★★ **IOS 的 `service password-encryption` 是 Type 7，屬於可逆混淆不是加密**，
  網路上到處都是解碼器。真正該做的是 `enable secret`（Type 5/8/9）與 `username ... secret`。
- ★★★★ **JunOS 的設定檔密碼欄位是 `$6$...` 雜湊**（SHA-512 crypt），相對安全，
  但仍可離線暴力破解，弱密碼一樣會被撈出來。
- ★★★ **commit comment 不要寫密碼或個資**，它會永久留在 `show system commit` 裡。

### 變更紀律 ★★★★★

| 規則 | 說明 | 星級 |
| --- | --- | --- |
| 遠端改設定必開保險 | JunOS `commit confirmed`／IOS `reload in` | ★★★★★ |
| 改前先存一份 | `show configuration \| display set`／`show running-config` 存本機 | ★★★★★ |
| 改後 24 小時內不做第二次變更 | 讓問題有時間浮現 | ★★★ |
| 一次只改一件事 | 出事才知道是哪一改造成的 | ★★★★ |
| 變更留單號 | `commit comment "CHG-2026-0912"`；表單見 vault 的 `_表單範本/100-02-06-變更管理申請單.docx` | ★★★★ |

## 速查表

### 救命指令（背起來）★★★★★

| 情境 | JunOS | Cisco IOS |
| --- | --- | --- |
| 我要看差異再決定 | `show \| compare` | （無，先存 running-config） |
| 我要遠端動刀 | `commit confirmed 5` | `reload in 10` |
| 我改壞了要回去 | `rollback 1` ＋ `commit` | `configure replace flash:before.cfg` |
| 我要取消保險 | 再打一次 `commit` | `reload cancel` |
| 我要確保重開不掉設定 | `commit`（本身即存檔） | `write memory` |
| 我要丟掉草稿重來 | `rollback 0` | （無草稿概念） |
| 我要看誰什麼時候改了什麼 | `show system commit` | `show archive` |

### 模式與導覽

| 動作 | JunOS | Cisco IOS |
| --- | --- | --- |
| 進設定模式 | `configure` | `enable` → `configure terminal` |
| 離開設定模式 | `exit` / `quit` | `end` |
| 設定模式下跑檢視指令 | `run show interfaces terse` ★★★★ | `do show interfaces status` ★★★★ |
| 關閉分頁 | `set cli screen-length 0` | `terminal length 0` |
| 過濾輸出 | `\| match <字串>` | `\| include <字串>` |
| 排除輸出 | `\| except <字串>` | `\| exclude <字串>` |
| 從某段開始顯示 | `\| find <字串>` | `\| begin <字串>` |
| 存到檔案 | `\| save /var/tmp/x.txt` | `\| redirect flash:x.txt` |
| 計算行數 | `\| count` | `\| count` |

### 九大類一行速記

| 類別 | JunOS 代表指令 | Cisco IOS 代表指令 |
| --- | --- | --- |
| 檢視狀態 | `show chassis hardware` | `show inventory` |
| 介面 | `show interfaces terse` | `show interfaces status` |
| VLAN | `show vlans` | `show vlan brief` |
| Trunk | `show ethernet-switching interface` | `show interfaces trunk` |
| 管理 IP／路由 | `show route` | `show ip route` |
| SSH／帳號 | `set system services ssh` | `ip ssh version 2` |
| 儲存與備份 | `commit` ／ `file copy ... scp://` | `write memory` ／ `copy run scp:` |
| 重開與升級 | `request system reboot` | `reload` |
| 除錯 | `show lldp neighbors` | `show cdp neighbors detail` |

### 語意陷阱對照 ★★★★★

| 你以為的事 | JunOS 真相 | IOS 真相 |
| --- | --- | --- |
| `#` 代表安全模式 | **錯**，`#` 是設定模式 | 對，`#` 是 privileged EXEC |
| 打完就生效 | **錯**，要 commit | 對 |
| 重開設定還在 | 對（commit 即存檔） | **錯**，要 write memory |
| trunk 加 VLAN 是累加 | 對 | **錯**，沒 `add` 就是取代 |
| 還原備份會覆蓋 | `load override` 才會 | `copy ... run` **不會**，要 `configure replace` |
| VLAN 打錯號碼會報錯 | 對（名字找不到會擋） | **錯**，會自動建新 VLAN |
| trunk 會自己協商出來 | **錯**，JunOS 無 DTP | 預設會（`dynamic auto/desirable`） |

## 練習題

> [!question]- 練習 1：把 IOS 設定翻譯成 JunOS ★★★
> 下面這段 IOS 設定，請改寫成 JunOS 的 `set` 指令：
>
> ```cisco
> vlan 40
>  name GUEST
> !
> interface GigabitEthernet1/0/30
>  description GUEST-AP-B2F
>  switchport mode access
>  switchport access vlan 40
> !
> interface TenGigabitEthernet1/0/49
>  switchport trunk allowed vlan add 40
> ```
>
> **參考答案**
>
> ```text
> set vlans V40-GUEST vlan-id 40
> set interfaces ge-0/0/30 description "GUEST-AP-B2F"
> set interfaces ge-0/0/30 unit 0 family ethernet-switching interface-mode access
> set interfaces ge-0/0/30 unit 0 family ethernet-switching vlan members V40-GUEST
> set interfaces xe-0/0/49 unit 0 family ethernet-switching vlan members V40-GUEST
> ```
>
> 三個重點：
> 1. JunOS 用 **VLAN 名稱**掛到埠上，不是 VLAN ID；VLAN 名稱要先定義。
> 2. 二層設定一律在 **`unit 0 family ethernet-switching`** 底下。
> 3. trunk 加 VLAN 直接再打一條 `set ... vlan members`，**天生累加**，不需要 `add` 關鍵字。

> [!question]- 練習 2：找出這個流程的兩個致命錯誤 ★★★★★
> 某工程師遠端在 IOS 交換器上改設定，流程如下：
>
> ```cisco
> sw01# configure terminal
> sw01(config)# interface Te1/0/49
> sw01(config-if)# switchport trunk allowed vlan 30
> sw01(config-if)# end
> sw01# write memory
> sw01# reload in 10
> ```
>
> 請指出兩個致命錯誤，並寫出正確流程。
>
> **參考答案**
>
> **錯誤一（★★★★★）**：`switchport trunk allowed vlan 30` 少了 `add`。
> 這一行把 trunk 上允許的 VLAN **整組換成只剩 30**，原本的 VLAN 10、20 立刻全斷。
> 正確寫法是 `switchport trunk allowed vlan add 30`。
>
> **錯誤二（★★★★★）**：`write memory` 在 `reload in` **之前**執行。
> 這等於把壞掉的設定寫進 startup-config，十分鐘後重開，讀到的還是壞設定 —— 
> 保險完全失效，而且多了一次計畫外停機。
>
> **正確流程**：
>
> ```cisco
> sw01# show running-config          ← 先存一份到本機
> sw01# reload in 10                 ← 先開保險
> sw01# configure terminal
> sw01(config)# interface Te1/0/49
> sw01(config-if)# switchport trunk allowed vlan add 30
> sw01(config-if)# end
> sw01# show interfaces trunk        ← 驗證：10,20,30 都在
> sw01# reload cancel                ← 確認沒問題才解除保險
> sw01# write memory                 ← 最後才存檔
> ```

> [!question]- 練習 3：JunOS 的三個「看差異」指令有什麼不同 ★★★★
> 說明下面三條指令各自回答什麼問題：
>
> ```text
> show | compare
> show | compare rollback 1
> show configuration | display set
> ```
>
> **參考答案**
>
> | 指令 | 回答的問題 | 用在什麼時候 |
> | --- | --- | --- |
> | `show \| compare` | **我這次還沒 commit 的草稿改了什麼？** 比對 candidate 與目前生效的設定 | commit **之前**，最後一道人工檢查 ★★★★★ |
> | `show \| compare rollback 1` | **上一次 commit 改了什麼？** 比對目前生效的設定與前一版 | 事後稽核、交班說明、事故回溯 ★★★★ |
> | `show configuration \| display set` | **這台設備的完整設定攤平長怎樣？** | 抓備份、複製設定到另一台、貼進工單 ★★★★★ |
>
> 三者的共同前提：`show | compare` 系列**只能在 configuration mode 用**，
> `show configuration` 在兩種模式都能用（operational mode 直接打，configuration mode 要加 `run`）。

> [!question]- 練習 4：對照表補完 ★★★
> 填出下列 IOS 指令的 JunOS 對應：
>
> 1. `show mac address-table interface Gi1/0/5`
> 2. `show interfaces counters errors`
> 3. `clear counters GigabitEthernet1/0/5`
> 4. `copy running-config scp://user@10.10.20.30/sw01.cfg`
> 5. `do show ip route`
>
> **參考答案**
>
> 1. `show ethernet-switching table interface ge-0/0/5`
> 2. `show interfaces ge-0/0/5 extensive | match error`（JunOS 沒有單一「全機錯誤計數」指令，
>    要逐埠看 `extensive`，或用 `show interfaces extensive | match "Interface|error"` 過濾）
> 3. `clear interfaces statistics ge-0/0/5`
> 4. `file copy /var/tmp/sw01.conf scp://user@10.10.20.30//backup/sw01.conf`
>    （先在 configuration mode 用 `save /var/tmp/sw01.conf` 產生檔案）
> 5. `run show route`（`run` 之於 JunOS，等同 `do` 之於 IOS）★★★★

> [!question]- 練習 5：設計一份「遠端變更檢查表」★★★★
> 依本篇內容，為你的機關設計一份適用於兩個平台的遠端變更前檢查表（至少 8 項）。
>
> **參考答案**
>
> | # | 檢查項 | JunOS | IOS |
> | --- | --- | --- | --- |
> | 1 | 變更單號已核准 | 兩平台共通（`_表單範本/100-02-06-變更管理申請單.docx`） | 同左 |
> | 2 | Console／KVM 可用，或現場有人 | 共通 ★★★★★ | 同左 |
> | 3 | 改前設定已抓下並開啟確認 | `show configuration \| display set` | `show running-config` |
> | 4 | 關閉分頁 | `set cli screen-length 0` | `terminal length 0` |
> | 5 | 保險已開 | `commit confirmed 5` | `reload in 10`（且**未** write memory）★★★★★ |
> | 6 | 差異已人工確認 | `show \| compare` | 逐行比對貼上的指令 |
> | 7 | 驗證項目已列好（ping／trunk／VLAN／業務） | 共通 | 同左 |
> | 8 | 回退指令已預先寫好貼在手邊 | `rollback 1` + `commit` | `configure replace flash:before.cfg` |
> | 9 | 完成後存檔 | `commit comment "..."` | `reload cancel` → `write memory` |
> | 10 | 文件與盤點表已更新 | 共通 | 同左 |

## 小測驗

Q1. （是非）在 JunOS 的 configuration mode 打完 `set interfaces ge-0/0/10 disable` 之後，
ge-0/0/10 這個埠會立刻斷線。

Q2. （選擇）在 Cisco IOS 上，某 trunk 埠原本 `switchport trunk allowed vlan 10,20`，
你打了 `switchport trunk allowed vlan 30`。結果是？
（A）允許 10,20,30 （B）只允許 30 （C）指令被拒絕 （D）只允許 10,20

Q3. （簡答）JunOS 的 `commit confirmed 5` 與 IOS 的 `reload in 10`，
在「回退到哪裡」與「有沒有服務中斷」這兩件事上有什麼不同？

Q4. （這行指令會發生什麼）
```cisco
sw01# copy tftp: running-config
```
你打算用它把三天前的備份還原回去。實際上會發生什麼？

Q5. （選擇）下列哪一組是 JunOS 與 IOS 的正確對應？
（A）`show vlans` ↔ `show vlan brief`
（B）`show configuration` ↔ `show running-config`
（C）`commit` ↔ `write memory`
（D）以上皆是，但（B）在語意上有陷阱

Q6. （是非）JunOS 沒有 DTP，所以 Juniper 與 Cisco 對接時，Cisco 端可以放心用預設的
`switchport mode dynamic auto`。

Q7. （簡答）在 JunOS configuration mode 想執行 `show interfaces terse`，
要怎麼打？IOS 在 `config)#` 底下想執行 `show ip route` 又要怎麼打？

Q8. （選擇）在 IOS 上不小心把 access 埠的 VLAN 打成 `switchport access vlan 100`
（原本要打 10），而交換器上並沒有 VLAN 100。會發生什麼？
（A）指令被拒絕 （B）埠保持原本的 VLAN 10 （C）IOS 自動建立 VLAN 100 並把埠丟進去
（D）埠變成 trunk

Q9. （簡答）JunOS `load merge` 與 `load override` 差在哪？各自對應 IOS 的哪個做法？

Q10. （這行指令會發生什麼）
```text
[edit]
admin@sw01# rollback 1
```
打完這一行之後，設備上正在跑的設定變了嗎？

> [!question]- 測驗答案
> **Q1.** **否。** JunOS 的 `set` 只改 candidate configuration，**要 `commit` 才生效**。
> 這也是 JunOS 最大的安全優勢，同時也是新手最常犯的錯（改完忘記 commit）。
> → 見「觀念說明／差異一：候選設定 vs 直接生效」
>
> **Q2.** **（B）只允許 30。** ★★★★★ `switchport trunk allowed vlan <list>` 是**取代**語意，
> VLAN 10 與 20 的流量會立刻中斷。要追加必須用 `switchport trunk allowed vlan add 30`。
> → 見「進階應用／四、Trunk」
>
> **Q3.**
> - **回退到哪裡**：`commit confirmed` 回到**上一份 committed 設定**（在記憶體中換設定）；
>   `reload in` 是重開機後讀取 **startup-config**，所以你**必須事先不要 write memory**。
> - **服務中斷**：`commit confirmed` 回滾時**不重開、不中斷**；
>   `reload in` 觸發時是**整台交換器重開**，該台底下所有裝置斷線數分鐘。 ★★★★★
> → 見「觀念說明／差異二」
>
> **Q4.** ★★★★★ **它是「合併」不是「覆蓋」。** IOS 會把備份檔的每一行當成你在 config 模式打進去，
> 所以備份檔**沒有**的設定（例如這三天新加的錯誤 ACL）會原封不動留著。
> 真正要覆蓋必須用 `configure replace flash:xxx.cfg`。
> → 見「進階應用／七、儲存與備份」
>
> **Q5.** **（D）。** （A）（B）（C）三組對應都成立，但（B）有陷阱：
> JunOS `show configuration` 顯示的是**已 commit 的永久設定**，
> IOS `show running-config` 顯示的是**可能還沒存檔的記憶體設定**。
> 稽核時要抓 IOS 的永久設定得用 `show startup-config`。
> → 見「進階應用／一、檢視狀態」
>
> **Q6.** **否。** ★★★★ 正因為 JunOS 沒有 DTP，Cisco 端不會收到協商封包，
> `dynamic auto` 會停在 **access 模式**，結果只有 native VLAN 通得過去 —— 典型的「通一半」。
> 混廠環境 Cisco 端必須 `switchport mode trunk` ＋ `switchport nonegotiate`。
> → 見「進階應用／四、Trunk」
>
> **Q7.** JunOS 用 **`run`**：`run show interfaces terse`。
> IOS 用 **`do`**：`do show ip route`。兩個關鍵字功能完全對應，都是「在設定模式借用檢視指令」。
> → 見「速查表／模式與導覽」
>
> **Q8.** **（C）IOS 自動建立 VLAN 100 並把埠丟進去。** ★★★★
> 不會有任何警告，該埠變成一個沒有其他成員、也沒有上行的孤島，
> 症狀是「這台電腦連 DHCP 都拿不到」。
> JunOS 因為用 VLAN **名稱**引用，打錯名字 `commit` 會直接擋下來。
> → 見「觀念說明／差異四」
>
> **Q9.**
> - `load merge`：把檔案內容**疊加**到 candidate，原有設定保留 → 對應 IOS 的 `copy ... running-config`。
> - `load override`：用檔案內容**整份取代** candidate → 對應 IOS 的 `configure replace`。
> - 兩者都還需要 `commit` 才生效。 ★★★★★
> → 見「進階應用／七、儲存與備份」
>
> **Q10.** **沒有變。** `rollback 1` 只是把「前一版設定」載進 **candidate**，
> 正在跑的還是目前那一版。**必須再打 `commit`** 才會真的回退。
> 這是 JunOS 新手第二常見的錯（第一常見是忘記 commit）。
> → 見「常見錯誤與排錯」最後一列

## 延伸閱讀

- [[040-01-05-cmd-Juniper-JunOS-基礎操作]] —— JunOS 模式、CLI 導覽、commit 完整說明
- [[040-01-10-cmd-Cisco-IOS-基礎操作]] —— IOS 模式、running/startup-config 完整說明
- [[040-01-06-guide-Juniper-VLAN與Trunk設定]] —— JunOS 的 VLAN 與 trunk 深入設定
- [[040-01-11-guide-Cisco-VLAN與Trunk設定]] —— IOS 的 VLAN 與 trunk 深入設定
- [[040-01-07-guide-Juniper-管理IP與遠端存取]] —— irb、me0、SSH 與管理面隔離
- [[040-01-12-guide-Cisco-管理IP與遠端存取]] —— SVI、vty、access-class
- [[040-01-09-svc-Juniper-設定備份與韌體升級]] —— archival 自動備份與 JunOS 升級流程
- [[040-01-14-svc-Cisco-設定備份與韌體升級]] —— archive 自動備份與 IOS-XE 升級流程
- [[040-01-16-guide-網路設備-鏈路聚合與STP]] —— ae／Port-channel 與 STP 防護的兩平台設定
- [[040-01-17-guide-網路設備-交換器故障排除]] —— 依症狀編號的排查流程
- [[040-01-18-guide-網路設備-網路設備盤點與文件化]] —— 用 git 管交換器設定
- [[040-01-19-guide-網路設備-交換器汰換與遷移實務]] —— 跨平台設定移轉的實務流程
- [[100-02-08-guide-維運-變更管理流程]] —— 變更單、停機窗口與核准機制
