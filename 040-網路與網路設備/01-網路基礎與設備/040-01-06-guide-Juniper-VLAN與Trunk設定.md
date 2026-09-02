---
title: "Juniper VLAN 與 Trunk 設定"
desc: "vlans 階層、interface-mode access／trunk、members 與 native-vlan-id，以及 ELS 與非 ELS 兩套語法差在哪"
aliases: [interface-mode, port-mode, native-vlan-id, ELS, family ethernet-switching, show vlans]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-05-cmd-Juniper-JunOS-基礎操作]]", "[[040-01-03-guide-網路設備-VLAN概念與規劃]]"]
updated: 2026-09-02
---

# Juniper VLAN 與 Trunk 設定

> [!abstract] 這篇你會學到
> - ★★★★★ **ELS 與非 ELS 是兩套語法**：`interface-mode` vs `port-mode`、`irb` vs `vlan`。
>   照網路上找到的範例貼上去卻報錯，九成是踩到這件事
> - ★★★★★ 改 trunk 的 `vlan members` 時，`set` 是**追加**、`delete` 才是移除 ——
>   用錯順序會讓上聯瞬間掉光 VLAN
> - ★★★★ `native-vlan-id` 到底解決什麼問題、兩端不一致會發生什麼（VLAN 混流，而且不會報錯）
> - ★★★★ `family ethernet-switching` 這一層為什麼非寫不可，漏了會怎樣
> - ★★★★ 三個驗證指令的分工：`show vlans` 看設定、`show ethernet-switching interface` 看 tagging、
>   `show ethernet-switching table` 看**真的有沒有學到 MAC**
> - ★★★ VLAN 範圍（`vlan-id-list`）、語音 VLAN、`members all` 的用法與地雷
> - ★★★★ JunOS **沒有 VTP**，VLAN 要一台一台建（或用 MVRP，但多數機關不開）
> - 產出一份「新增一個 VLAN 到整棟樓」的完整實戰流程與驗收檢查表

> [!warning] 未實機驗證
> ★★★★★ 本專案沒有實體 Juniper 設備可驗證。本篇以 **EX 系列（ELS，Junos 21.4）** 為主線，
> 非 ELS 語法依 Juniper 官方 EX2200／EX3300／EX4200 文件整理，輸出格式可能與你手上機型不同。
> **動手前務必在該機型上用 `?` 與 `help reference` 確認語法**，並依
> [[040-01-05-cmd-Juniper-JunOS-基礎操作]] 的 `commit confirmed` 流程操作。

## 前置知識

- [[040-01-05-cmd-Juniper-JunOS-基礎操作]] —— candidate／commit／rollback，本篇全部建立在這之上
- [[040-01-03-guide-網路設備-VLAN概念與規劃]] —— VLAN 編號怎麼配、一個機關該切幾個 VLAN
- [[010-02-16-guide-網概-VLAN與網路分段]] —— 802.1Q tag、access／trunk 的原理
- [[010-02-05-guide-網概-MAC位址與交換器]] —— MAC 表怎麼學、廣播網域是什麼
- [[040-01-02-guide-網路設備-IP位址規劃與子網切分]] —— 每個 VLAN 對應一個網段，兩者要一起規劃

## 觀念說明

### ELS 與非 ELS —— 動筆前先確認你的機型屬於哪一邊 ★★★★★

Juniper 在 2013 年前後把 EX 系列的二層設定語法整個重寫，稱為
**ELS（Enhanced Layer 2 Software，增強型二層軟體）**。兩套語法**互不相容**，
而且**同一條指令在錯的機型上會直接被 CLI 拒絕**。

| 項目 | 非 ELS（舊） | ELS（新） |
| --- | --- | --- |
| 存取／幹道模式 | `port-mode access\|trunk` | ★★★★★ `interface-mode access\|trunk` |
| L3 VLAN 介面 | `vlan.10` | ★★★★★ `irb.10` |
| VLAN 綁 L3 介面 | `set vlans X l3-interface vlan.10` | `set vlans X l3-interface irb.10` |
| native VLAN 設在哪 | `... unit 0 family ethernet-switching native-vlan-id N` | ★★★★ `set interfaces ge-0/0/48 native-vlan-id N`（實體層） |
| 二層全域選項 | `ethernet-switching-options` | ★★★★ `switch-options` |
| 檢視介面 | `show ethernet-switching interfaces`（複數） | `show ethernet-switching interface`（單數） |
| 常見機型 | EX2200／EX3200／EX3300／EX4200／EX4500 | EX2300／EX3400／EX4300／EX4400／EX4600／QFX 系列 |

★★★★★ **怎麼判斷手上這台是哪一種？** 不要猜，用 CLI 問：

```text
netadmin@sw> configure
[edit]
netadmin@sw# set interfaces ge-0/0/1 unit 0 family ethernet-switching ?
Possible completions:
+ apply-groups         Groups from which to inherit configuration data
  filter               Packet filtering
  interface-mode       Interface mode (access or trunk)
  recovery-timeout     Storm control recovery timeout
  storm-control        Storm control profile
+ vlan                 Virtual LAN membership
```

看到 **`interface-mode`** → ELS。看到 **`port-mode`** → 非 ELS。

另一個快速判斷法：

```text
netadmin@sw> show interfaces terse | match "^irb|^vlan"
irb                     up    up
irb.10                  up    up   inet     10.10.10.2/24
```

有 `irb` → ELS；有 `vlan.10` → 非 ELS。

> [!danger] ★★★★★ 網路上抄來的設定不能直接貼
> 部落格與論壇上的 Juniper VLAN 範例大量是 2012～2015 年的非 ELS 寫法。
> 直接貼到 EX4300 上會得到：
> ```text
> [edit interfaces ge-0/0/1 unit 0 family ethernet-switching]
>   'port-mode'
>     syntax error.
> ```
> 這算是**運氣好**的情況 —— CLI 擋下來了。真正危險的是那些**兩邊都合法但語意不同**的地方，
> 例如 `native-vlan-id` 設在實體層還是 unit 層：寫錯位置有可能 commit 成功但沒有作用，
> 造成 native VLAN 的流量被丟棄，而且**不會有任何錯誤訊息**。

**本篇以下所有主線範例都是 ELS 語法**，每一節結尾附非 ELS 的對照。

### `family ethernet-switching` 這層在幹嘛 ★★★★

JunOS 的介面預設「什麼都不是」。你必須明確告訴它這個邏輯單元要跑哪一種協定家族：

```text
set interfaces ge-0/0/1 unit 0 family ethernet-switching   ← 我是二層交換埠
set interfaces irb    unit 10 family inet address 10.10.10.2/24   ← 我是三層 IP 介面
set interfaces me0    unit 0 family inet address 10.99.0.11/24    ← 帶外管理，也是三層
```

| family | 意義 | 用在哪 |
| --- | --- | --- |
| `ethernet-switching` | ★★★★★ 二層交換（VLAN、MAC 學習） | 所有 access／trunk 埠 |
| `inet` | IPv4 | `irb`、`me0`、`lo0`、路由埠 |
| `inet6` | IPv6 | 同上 |
| `mpls` / `iso` | MPLS／IS-IS | 服務供應商網路，本手冊不涵蓋 |

★★★★ **同一個 unit 不能同時是 `ethernet-switching` 和 `inet`**（EX 上會被 commit check 擋掉）。
需要 VLAN 又需要 IP 的做法是：埠設 `ethernet-switching`，IP 設在 `irb.<vlan>` 上。

★★★★ 忘記寫 `family ethernet-switching` 的症狀很典型：
`show interfaces terse` 看得到 `ge-0/0/1  up  up`，但**沒有 `ge-0/0/1.0` 那一行**，
`show vlans` 裡也找不到這個埠，接上去的電腦拿不到 DHCP。

### access 與 trunk：`interface-mode` 決定 tag 怎麼處理 ★★★★★

```text
                       ┌──────────────────────────────────┐
    PC（不懂 VLAN）     │           EX 交換器               │
      無 tag 的封包 ───▶│ ge-0/0/1                          │
                       │ interface-mode access             │
                       │ vlan members OFFICE (vlan-id 10)  │
                       │   ↓ 進來時「打上」tag 10          │
                       │   內部交換依 tag 10 決定去哪       │
                       │   ↓                                │
                       │ ge-0/0/48                         │──▶ 核心交換器
                       │ interface-mode trunk              │    帶 tag 10 的封包
                       │ vlan members [OFFICE VOICE SERVER]│
                       │   ↓ 出去時「保留」tag             │
                       └──────────────────────────────────┘
```

| | access 埠 | trunk 埠 |
| --- | --- | --- |
| 接什麼 | ★★★★★ 終端設備（PC、印表機、IP 攝影機、AP 的管理埠） | ★★★★★ 另一台交換器、防火牆、虛擬化主機、AP 的資料埠 |
| VLAN 數量 | 通常 **1 個**（語音 VLAN 是例外） | 多個 |
| 進來的封包 | 無 tag → 打上 access VLAN 的 tag | 有 tag → 依 tag 分派；無 tag → 歸 native VLAN |
| 出去的封包 | ★★★★ **移除 tag** | ★★★★ **保留 tag**（native VLAN 除外，見下） |
| 設定關鍵字 | `interface-mode access` | `interface-mode trunk` |

★★★★★ **最常見的錯誤：把接 PC 的埠設成 trunk，或把上聯埠設成 access。**
前者的症狀是 PC 有時候通有時候不通（走到 native VLAN 去了）；
後者的症狀是「整台交換器只剩一個 VLAN 通得出去」。

### `native-vlan-id` —— trunk 上那些沒有 tag 的封包怎麼辦 ★★★★

trunk 埠收到**沒有 802.1Q tag** 的封包時，JunOS 要有個地方擺它，那就是 native VLAN：

```junos
set interfaces ge-0/0/48 native-vlan-id 999
set interfaces ge-0/0/48 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members [ OFFICE VOICE SERVER PARKING ]
```

★★★★ **ELS 的 `native-vlan-id` 設在實體介面層級**（不在 `unit 0 family ethernet-switching` 底下）。
非 ELS 則相反。這是兩套語法最容易搞混的一點。

| 情境 | 結果 | 星級 |
| --- | --- | --- |
| 兩端 native VLAN **一致** | ★ 正常 | ★ |
| 兩端 native VLAN **不一致**（一邊 1、一邊 999） | ★★★★★ **兩個 VLAN 的流量被接在一起**（VLAN leaking），而且**兩邊都不會報錯** | ★★★★★ |
| trunk 沒設 native-vlan-id | 無 tag 封包依機型／版本行為不同，可能被丟棄或歸 VLAN 1 | ★★★★ |
| native VLAN 沒放進 `vlan members` | ★★★★ 該 VLAN 的無 tag 流量進得來但轉不出去 | ★★★★ |

> [!danger] ★★★★★ native VLAN 不一致是「不會報錯的斷網」
> Cisco 有 CDP／DTP 會在 log 裡叫 `%CDP-4-NATIVE_VLAN_MISMATCH`，
> Juniper **沒有這個檢查**（LLDP 不比對 native VLAN）。
> 症狀是某個 VLAN 的裝置偶爾能 ping 到別的 VLAN、DHCP 拿到錯誤網段的位址、
> 廣播風暴莫名跨網段 —— 查上一整天都查不到，因為兩端的設定「各自看起來都正確」。
>
> **防法（機關網路建議直接寫成標準）**：
> 1. ★★★★★ 所有 trunk 的 native VLAN 統一用一個**沒有任何裝置**的專用 VLAN（例如 999 `PARKING`）
> 2. ★★★★ **絕對不要用 VLAN 1 當 native**（VLAN hopping 攻擊的第一步）
> 3. ★★★★ 把 native VLAN 也放進 `vlan members`，讓行為明確
> 4. ★★★ 兩端設備的 trunk 設定寫成同一份範本，一起變更

### JunOS 沒有 VTP ★★★★

習慣 Cisco 的人會找「VLAN 資料庫自動同步」—— JunOS 沒有 VTP。

| 方式 | JunOS | 說明 |
| --- | --- | --- |
| 手動 | ★★★★★ **每一台交換器各自 `set vlans`** | 機關環境的標準做法 |
| MVRP（802.1ak） | `set protocols mvrp interface all` | ★★ 動態註冊 VLAN；多數機關不開，因為「自動」在網路上通常等於「不可預測」 |

★★★★ 這其實是好事：VTP 曾造成大量「新交換器一插上去就把整個 VLAN 資料庫清空」的經典事故。
JunOS 的做法是明確、可版控、可用 `show configuration | display set` 核對的。
代價是**新增一個 VLAN 要在路徑上每一台交換器都做一次** —— 所以更需要標準化與盤點文件
（見 [[040-01-18-guide-網路設備-網路設備盤點與文件化]]）。

### 預設的 `default` VLAN ★★★★

一台剛出廠的 EX 交換器，所有埠都已經是 `family ethernet-switching`、access 模式、
屬於一個叫 `default` 的 VLAN：

```text
netadmin@sw> show vlans
Routing instance        VLAN name             Tag       Interfaces
default-switch          default
                                                        ge-0/0/0.0*
                                                        ge-0/0/1.0*
                                                        ge-0/0/2.0
                                                        ...
```

★★★★★ `default` VLAN **沒有 vlan-id**（Tag 欄是空的），它代表「未 tag 的預設廣播網域」。
★★★★ **不要把正式服務放在 `default` 裡**：它無法設 `l3-interface`（無 tag）、
無法在 trunk 上明確帶走、跨交換器行為容易出乎意料。
建置新交換器的第一步就是**建立正式 VLAN 並把埠移出 `default`**。

## 環境準備與安裝

本篇的範例拓樸（後面實戰範例會用到）：

```text
                      ┌─────────────────┐
                      │  core-ex4300    │
                      │  (核心/L3)       │
                      └────────┬────────┘
                               │ ge-0/0/48  trunk
                               │ members [ OFFICE VOICE SERVER MGMT PARKING ]
                               │ native-vlan-id 999
                      ┌────────┴────────┐
                      │  acc-3f-ex2300  │  接取層交換器
                      │                 │
   PC   ge-0/0/1 ─────┤ access OFFICE   │
   IP話機 ge-0/0/2 ────┤ access OFFICE   │ + voip VOICE
   印表機 ge-0/0/3 ────┤ access OFFICE   │
   未使用 ge-0/0/20 ───┤ disable + PARKING
                      └─────────────────┘

VLAN 規劃
  10  OFFICE   10.10.10.0/24    辦公 PC
  20  VOICE    10.10.20.0/24    IP 電話
  30  SERVER   10.10.30.0/24    機房伺服器
  99  MGMT     10.99.0.0/24     設備管理（見 07 篇）
  999 PARKING  （無 IP）        未用埠隔離 + trunk native VLAN
```

### 步驟 0：確認機型、版本與現況 ★★★★

```text
netadmin@acc-3f-ex2300> show version | match "Model|Junos:"
Model: ex2300-48t
Junos: 21.4R3-S5.4

netadmin@acc-3f-ex2300> show vlans
Routing instance        VLAN name             Tag       Interfaces
default-switch          default
                                                        ge-0/0/0.0*
                                                        ge-0/0/1.0*
                                                        ...
```

★★★★ EX2300 是 **ELS** 機種，所以用 `interface-mode`。真的不確定就照前面「觀念說明」的方法用 `?` 問。

```text
netadmin@acc-3f-ex2300> show ethernet-switching interface | match "Logical interface" -A 3
Logical interface        Vlan name            Tagging     Blocking
ge-0/0/0.0               default              untagged    unblocked
ge-0/0/1.0               default              untagged    unblocked
```

## 基礎設定

以下五步是「建一個 VLAN 並讓它跨交換器通」的最小完整流程，順序不要跳。

### 步驟 1：建立 VLAN ★★★★★

```text
netadmin@acc-3f-ex2300> configure exclusive
Entering configuration mode

[edit]
netadmin@acc-3f-ex2300# set vlans OFFICE vlan-id 10
[edit]
netadmin@acc-3f-ex2300# set vlans OFFICE description "辦公 PC 網段 10.10.10.0/24"
[edit]
netadmin@acc-3f-ex2300# set vlans VOICE vlan-id 20
[edit]
netadmin@acc-3f-ex2300# set vlans VOICE description "IP 電話"
[edit]
netadmin@acc-3f-ex2300# set vlans SERVER vlan-id 30
[edit]
netadmin@acc-3f-ex2300# set vlans MGMT vlan-id 99
[edit]
netadmin@acc-3f-ex2300# set vlans MGMT description "設備管理，勿接終端"
[edit]
netadmin@acc-3f-ex2300# set vlans PARKING vlan-id 999
[edit]
netadmin@acc-3f-ex2300# set vlans PARKING description "未用埠隔離 + trunk native，無 L3"
```

```text
[edit]
netadmin@acc-3f-ex2300# show vlans
OFFICE {
    description "辦公 PC 網段 10.10.10.0/24";
    vlan-id 10;
}
VOICE {
    description "IP 電話";
    vlan-id 20;
}
SERVER {
    vlan-id 30;
}
MGMT {
    description "設備管理，勿接終端";
    vlan-id 99;
}
PARKING {
    description "未用埠隔離 + trunk native，無 L3";
    vlan-id 999;
}
```

> [!tip] ★★★★ VLAN 名稱與 vlan-id 的命名規範
> - 名稱用**大寫英文**、有意義、全機關統一（`OFFICE` 不要有的地方寫 `office`、有的寫 `Office`）
>   —— ★★★★ JunOS 的 VLAN 名稱**大小寫敏感**，`members office` 找不到 `OFFICE` 會直接 commit 失敗
> - ★★★★ 名稱裡不要有空白與中文，否則每次都要加引號，複製貼上容易出錯
> - `description` 寫用途與網段，這是三年後接手的人唯一的線索
> - vlan-id 全機關統一：**同一個用途在每一台設備上都是同一個號碼**。
>   規劃原則見 [[040-01-03-guide-網路設備-VLAN概念與規劃]]

### 步驟 2：設定 access 埠 ★★★★★

```text
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/1 description "3F-A12 王小明 PC"
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members OFFICE
```

```text
[edit]
netadmin@acc-3f-ex2300# show interfaces ge-0/0/1
description "3F-A12 王小明 PC";
unit 0 {
    family ethernet-switching {
        interface-mode access;
        vlan {
            members OFFICE;
        }
    }
}
```

★★★★ access 埠的 `vlan members` **只能有一個**（語音 VLAN 是特例，走 `switch-options voip`）。
硬寫兩個會被 commit check 擋掉：

```text
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members VOICE
[edit]
netadmin@acc-3f-ex2300# commit check
[edit interfaces ge-0/0/1 unit 0 family ethernet-switching]
  'vlan'
    Interface ge-0/0/1.0 is in access mode and can have only one VLAN member
error: configuration check-out failed
```

★★★★ 這種「commit check 幫你擋下來」正是 JunOS 的價值。在 Cisco 上你會打完就生效然後開始找原因。

### 步驟 3：設定 trunk 埠 ★★★★★

```text
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/48 description "UPLINK to core-ex4300 ge-0/0/12"
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/48 native-vlan-id 999
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/48 unit 0 family ethernet-switching interface-mode trunk
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members [ OFFICE VOICE SERVER MGMT PARKING ]
```

```text
[edit]
netadmin@acc-3f-ex2300# show interfaces ge-0/0/48
description "UPLINK to core-ex4300 ge-0/0/12";
native-vlan-id 999;
unit 0 {
    family ethernet-switching {
        interface-mode trunk;
        vlan {
            members [ OFFICE VOICE SERVER MGMT PARKING ];
        }
    }
}
```

★★★★★ **中括號 `[ ... ]` 是一次設定多個值的語法**，前後要有空白。
也可以分開打，效果完全一樣：

```text
set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members OFFICE
set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members VOICE
```

### 步驟 4：★★★★★ 修改 trunk 成員時最容易出事的地方

> [!danger] ★★★★★ `set vlan members` 是「追加」，不是「取代」
> 這是 JunOS 與 Cisco 語意最不一樣、也最容易釀成事故的一點。
>
> | 你想做的事 | Cisco IOS | JunOS |
> | --- | --- | --- |
> | 加一個 VLAN | `switchport trunk allowed vlan add 40` | `set ... vlan members MEETING` |
> | ★★★★★ **設定為只有這些** | `switchport trunk allowed vlan 10,20,40` | ★★★★★ 要先 `delete ... vlan` 再 `set` |
> | 移除一個 VLAN | `switchport trunk allowed vlan remove 20` | `delete ... vlan members VOICE` |
>
> ★★★★★ Cisco 的 `switchport trunk allowed vlan 10,20`（不加 `add`）是**整組取代**，
> 打錯的話那一瞬間其他 VLAN 全斷 —— 這是 Cisco 的經典事故。
> JunOS 的 `set` 是追加，反而比較安全；但也因此**「我以為我把清單換掉了」是 JunOS 的對應陷阱**：
> 你以為 trunk 現在只有 OFFICE，實際上舊的 GUEST 還在上面，稽核時被抓到「隔離失效」。
>
> **唯一可靠的做法：改完一定 `show | compare` 看最終結果。**

```text
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members MEETING
[edit]
netadmin@acc-3f-ex2300# show | compare
[edit interfaces ge-0/0/48 unit 0 family ethernet-switching vlan]
       members [ OFFICE VOICE SERVER MGMT PARKING ];
+      members MEETING;
```

★★★★ 沒有 `-` 開頭的行 = 這是純新增，原本的都在。這是你要看到的樣子。

反例 —— **危險的寫法**：

```text
[edit]
netadmin@acc-3f-ex2300# delete interfaces ge-0/0/48 unit 0 family ethernet-switching vlan
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members MEETING
[edit]
netadmin@acc-3f-ex2300# show | compare
[edit interfaces ge-0/0/48 unit 0 family ethernet-switching vlan]
-      members [ OFFICE VOICE SERVER MGMT PARKING ];
+      members MEETING;
```

★★★★★ 看到那一行 `-  members [ ... ]` 就要停手。這個 commit 下去，
**這台交換器上除了 MEETING 之外所有 VLAN 全部對外斷線**。
好消息是 JunOS 是 transactional —— 只要你在 commit 前看到，`rollback 0` 就沒事了。

### 步驟 5：`commit confirmed` 送出並驗證 ★★★★★

```text
[edit]
netadmin@acc-3f-ex2300# commit check
configuration check succeeds
[edit]
netadmin@acc-3f-ex2300# commit confirmed 10 comment "CR-2026-0501 3F VLAN 建置"
commit confirmed will be automatically rolled back in 10 minutes unless confirmed
commit complete
```

驗證三件套（★★★★★ 三個都要看，缺一個就不算驗完）：

```text
[edit]
netadmin@acc-3f-ex2300# run show vlans
Routing instance        VLAN name             Tag       Interfaces
default-switch          MGMT                  99
                                                        ge-0/0/48.0*
default-switch          OFFICE                10
                                                        ge-0/0/1.0*
                                                        ge-0/0/2.0*
                                                        ge-0/0/3.0
                                                        ge-0/0/48.0*
default-switch          PARKING               999
                                                        ge-0/0/48.0*
default-switch          SERVER                30
                                                        ge-0/0/48.0*
default-switch          VOICE                 20
                                                        ge-0/0/2.0*
                                                        ge-0/0/48.0*
default-switch          default
                                                        ge-0/0/4.0
                                                        ...
```

★★★★ `*` 代表該介面目前 **up**。`ge-0/0/3.0` 沒有星號 = 印表機沒開機或線沒插。

```text
[edit]
netadmin@acc-3f-ex2300# run show ethernet-switching interface ge-0/0/48.0
Routing Instance Name : default-switch
Logical Interface flags (DL - disable learning, AD - packet action drop,
                         LH - MAC limit hit, DN - interface down,
                         MMAS - Mac-move action shutdown, AS - Autostate-exclude enabled,
                         SCTL - shutdown by Storm-control, MI - MAC+IP limit hit)

Logical interface        Vlan name            Tagging     Blocking
ge-0/0/48.0              MGMT                 tagged      unblocked
                         OFFICE               tagged      unblocked
                         PARKING              untagged    unblocked
                         SERVER               tagged      unblocked
                         VOICE                tagged      unblocked
```

★★★★★ **這是驗證 native VLAN 是否生效的唯一可靠方式**：
`PARKING` 顯示 **`untagged`**，其他都是 `tagged` —— 這代表 `native-vlan-id 999` 有作用。
如果 `PARKING` 也是 `tagged`，表示 native-vlan-id 沒設好（很可能設錯階層）。

```text
[edit]
netadmin@acc-3f-ex2300# run show ethernet-switching table
MAC flags (S - static MAC, D - dynamic MAC, L - locally learned, P - Persistent static
           SE - statistics enabled, NM - non configured MAC, R - remote PE MAC, O - ovsdb MAC)

Ethernet switching table : 5 entries, 5 learned
Routing instance : default-switch
   Vlan                MAC                 MAC      Logical                SVLBNH/  Active
   name                address             flags    interface              VENH Index  source
   OFFICE              b4:0c:25:1a:3f:e2   D        ge-0/0/1.0
   OFFICE              00:1b:21:8c:44:07   D        ge-0/0/48.0
   VOICE               00:04:f2:aa:19:c3   D        ge-0/0/2.0
   SERVER              e4:5f:01:22:8b:90   D        ge-0/0/48.0
   MGMT                2c:6b:f5:11:0a:7e   D        ge-0/0/48.0
```

★★★★★ **看到終端裝置的 MAC 學在正確的 VLAN 與正確的埠上，才算真的通了。**
只看 `show vlans` 有埠是不夠的 —— 那只證明「設定寫對了」，不證明「流量走得通」。

```text
[edit]
netadmin@acc-3f-ex2300# commit comment "CR-2026-0501 驗證通過，確認定案"
commit complete
```

> [!info]- 非 ELS（EX2200／EX3300／EX4200 等舊機種）對照
> 同一份設定在非 ELS 機型上要這樣寫：
>
> ```junos
> ## VLAN 定義（幾乎一樣，只有 l3-interface 不同）
> set vlans office vlan-id 10
> set vlans office description "辦公 PC 網段"
> set vlans office l3-interface vlan.10          ## ★★★★★ ELS 是 irb.10
>
> ## access 埠
> set interfaces ge-0/0/1 unit 0 family ethernet-switching port-mode access
> set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members office
>
> ## trunk 埠（★★★★ native-vlan-id 在 unit 底下，不在實體層）
> set interfaces ge-0/0/48 unit 0 family ethernet-switching port-mode trunk
> set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members [ office voice server ]
> set interfaces ge-0/0/48 unit 0 family ethernet-switching native-vlan-id 999
> ```
>
> 驗證指令也不同：
> ```text
> show vlans
> show ethernet-switching interfaces          ## ★★★★ 複數 s
> show ethernet-switching table
> ```
>
> ★★★★★ **非 ELS 的 `show ethernet-switching interfaces` 輸出欄位與 ELS 差很多**，
> 不要拿本篇的輸出去對照。用 `?` 確認該版本支援哪些子選項。
>
> ★★★ 二層全域選項的階層也不同：非 ELS 是 `ethernet-switching-options`，
> ELS 是 `switch-options`（storm-control 又更特別，見 08 篇）。

> [!info]- Cisco IOS 對照（簡表，完整內容見 [[040-01-11-guide-Cisco-VLAN與Trunk設定]]）
> | 目的 | JunOS（ELS） | Cisco IOS |
> | --- | --- | --- |
> | 建 VLAN | `set vlans OFFICE vlan-id 10` | `vlan 10` + `name OFFICE` |
> | access 埠 | `set int ge-0/0/1 unit 0 family ethernet-switching interface-mode access` | `switchport mode access` |
> | access VLAN | `... vlan members OFFICE` | `switchport access vlan 10` |
> | trunk 埠 | `... interface-mode trunk` | `switchport mode trunk` + `switchport trunk encapsulation dot1q` |
> | trunk 放行 VLAN | `... vlan members [ A B C ]`（★★★★★ **追加**） | `switchport trunk allowed vlan 10,20,30`（★★★★★ **取代**） |
> | 加一個 VLAN 到 trunk | `set ... vlan members D` | `switchport trunk allowed vlan add 40` |
> | native VLAN | `set int ge-0/0/48 native-vlan-id 999` | `switchport trunk native vlan 999` |
> | L3 VLAN 介面 | `set int irb unit 10 family inet address ...` + `set vlans OFFICE l3-interface irb.10` | `interface Vlan10` + `ip address ...` |
> | 看 VLAN | `show vlans` | `show vlan brief` |
> | 看 trunk | `show ethernet-switching interface` | `show interfaces trunk` |
> | 看 MAC | `show ethernet-switching table` | `show mac address-table` |
> | VLAN 同步協定 | ★★★★ 無 VTP（可用 MVRP） | VTP |
> | native 不一致告警 | ★★★★★ **無**（要自己核對） | `%CDP-4-NATIVE_VLAN_MISMATCH` |
>
> 完整雙欄對照見 [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]]。

## 進階設定與調校

### VLAN 範圍與批次設定 ★★★

一次建一整段連號 VLAN（ELS）：

```junos
set vlans VLAN-100-110 vlan-id-list 100-110
```

trunk 成員也可以直接寫 vlan-id 或範圍，不一定要用名稱：

```junos
set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members 100-110
set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members 10
```

| 寫法 | 意思 | 星級 |
| --- | --- | --- |
| `vlan members OFFICE` | 依名稱 | ★★★★★ 建議，可讀性最好 |
| `vlan members 10` | 依 vlan-id | ★★★ 混用會讓文件難維護 |
| `vlan members 100-110` | 範圍 | ★★★ 大量 VLAN 時 |
| `vlan members all` | ★★★★★ **這台上所有 VLAN** | ★★★★★ 危險，見下 |

> [!danger] ★★★★★ `vlan members all` 在機關網路是資安缺失
> 它的意思是「這台交換器上定義的所有 VLAN 都從這個 trunk 走」。
> 問題有三個：
> 1. ★★★★★ **未來新增的任何 VLAN 都會自動被放行** —— 你以後建一個「機密資料 VLAN」，
>    它自動就跑到這條 trunk 上去了，而你不會收到任何通知
> 2. ★★★★ **稽核無法證明隔離** —— 資安稽核問「請證明 A 網段到不了 B 網段」，
>    `members all` 沒辦法回答
> 3. ★★★ 廣播與未知單播的複製範圍變大，浪費上聯頻寬
>
> **正確做法：明列需要的 VLAN（白名單）。** 多打幾個字換來的是可稽核、可預測。

### 語音 VLAN（VoIP）★★★★

IP 話機的典型接法是「話機接牆上、PC 再接話機」，一個埠要同時承載兩個 VLAN：
話機走 tagged 的 VOICE、PC 走 untagged 的 OFFICE。

```junos
## ELS
set interfaces ge-0/0/2 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members OFFICE
set switch-options voip interface ge-0/0/2.0 vlan VOICE
set switch-options voip interface ge-0/0/2.0 forwarding-class expedited-forwarding
```

```text
netadmin@sw> show ethernet-switching interface ge-0/0/2.0
Logical interface        Vlan name            Tagging     Blocking
ge-0/0/2.0               OFFICE               untagged    unblocked
                         VOICE                tagged      unblocked
```

★★★★ 話機怎麼知道要用 VLAN 20？靠 **LLDP-MED**：

```junos
set protocols lldp interface all
set protocols lldp-med interface all
```

★★★★★ 沒開 LLDP-MED，話機不知道語音 VLAN，會用 untagged 落到 OFFICE VLAN，
症狀是「電話可以打但語音品質很差」（沒吃到 QoS）或「話機拿不到 DHCP」。

> [!info]- 非 ELS 的語音 VLAN
> ```junos
> set ethernet-switching-options voip interface ge-0/0/2.0 vlan voice
> set ethernet-switching-options voip interface ge-0/0/2.0 forwarding-class expedited-forwarding
> ```
> ★★★ 階層從 `switch-options` 變成 `ethernet-switching-options`，其餘概念相同。

> [!warning] ★★★ 未實機驗證
> `switch-options voip` 的支援情況依機型與 Junos 版本而異，部分較新版本改用
> `set vlans VOICE ...` 搭配 802.1X 的動態 VLAN 指派。
> 導入前請用 `set switch-options voip ?` 確認，並與話機廠商的設定指南對照。

### L3 VLAN 介面（`irb`）★★★★

VLAN 之間要互通，需要一個三層閘道。在核心交換器上：

```junos
set interfaces irb unit 10 family inet address 10.10.10.254/24
set interfaces irb unit 20 family inet address 10.10.20.254/24
set interfaces irb unit 30 family inet address 10.10.30.254/24
set vlans OFFICE l3-interface irb.10
set vlans VOICE  l3-interface irb.20
set vlans SERVER l3-interface irb.30
```

★★★★ **`irb` 的 unit 編號慣例用 vlan-id**（`irb.10` 對 VLAN 10）。技術上不強制，
但混用會讓三年後接手的人抓狂。

```text
netadmin@core> show interfaces terse | match irb
irb                     up    up
irb.10                  up    up   inet     10.10.10.254/24
irb.20                  up    up   inet     10.10.20.254/24
irb.30                  up    up   inet     10.10.30.254/24
```

★★★★ **`irb.X` 只有在該 VLAN 至少有一個 up 的成員埠時才會 up**（autostate）。
新建的 VLAN 還沒接任何裝置，`irb` 會是 `up down`，這是正常的，不是故障。

★★★★★ 管理 IP 的完整做法（含帶外管理、預設路由、SSH）在
[[040-01-07-guide-Juniper-管理IP與遠端存取]]，本篇只講 VLAN 側。

### VLAN 隔離與私有 VLAN ★★★

同一個 VLAN 內的裝置預設可以互通。要讓它們彼此隔離（例如訪客 Wi-Fi、旅館房間網路），
ELS 提供 private VLAN：

```junos
set vlans GUEST-PRIMARY vlan-id 200
set vlans GUEST-PRIMARY private-vlan primary
set vlans GUEST-ISOLATED vlan-id 201
set vlans GUEST-ISOLATED private-vlan isolated
set vlans GUEST-ISOLATED primary-vlan GUEST-PRIMARY
```

> [!warning] ★★★★ 未實機驗證，且 private VLAN 支援度差異很大
> Private VLAN 的支援情況**依機型差異極大**（EX2300 等入門機種可能不支援，
> 或只支援單一交換器內的 PVLAN 而不支援跨交換器）。
> 需求若只是「同一 VLAN 內互相看不到」，多數情況下用
> **無線控制器的 client isolation** 或 **firewall filter**（08 篇）更簡單可靠。
> 導入前請查該機型的 Feature Explorer 與 Junos 版本說明。

### 用 `apply-groups` 統一 access 埠設定 ★★★

48 個埠不想打 48 次：

```junos
set groups ACC-PORT interfaces <ge-0/0/[0-9]> unit 0 family ethernet-switching interface-mode access
set groups ACC-PORT interfaces <ge-0/0/[0-9]> unit 0 family ethernet-switching vlan members OFFICE
set apply-groups ACC-PORT
```

★★★★ 檢查繼承結果一定要加 `| display inheritance`：

```text
netadmin@sw> show configuration interfaces ge-0/0/5 | display inheritance
##
## 'interface-mode' was inherited from group 'ACC-PORT'
##
unit 0 {
    family ethernet-switching {
        interface-mode access;
##
## 'OFFICE' was inherited from group 'ACC-PORT'
##
        vlan {
            members OFFICE;
        }
    }
}
```

★★★★ **`apply-groups` 是雙面刃**：好處是一致性，壞處是「`show configuration` 看起來空空的」，
排錯的人會誤以為埠沒設定。用 `apply-groups` 的設備必須在盤點文件裡明確註記
（見 [[040-01-18-guide-網路設備-網路設備盤點與文件化]]）。

### MAC 表相關的觀察與調整 ★★★

```text
netadmin@sw> show ethernet-switching table summary
Ethernet switching table : 428 entries, 428 learned
Routing instance : default-switch

netadmin@sw> show ethernet-switching table vlan-id 10 | count
Count: 214 lines

netadmin@sw> clear ethernet-switching table
```

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `show ethernet-switching table` | 完整 MAC 表 | ★★★★★ |
| `show ethernet-switching table vlan-id 10` | 只看某 VLAN | ★★★★ |
| `show ethernet-switching table interface ge-0/0/1.0` | 這個埠後面掛了幾台 | ★★★★ 抓私接 hub |
| `show ethernet-switching table summary` | 總筆數 | ★★★ |
| `clear ethernet-switching table` | ★★★★ 清空重學（排錯用，會短暫氾洪） | ★★★★ |
| `set vlans OFFICE switch-options mac-table-aging-time 600` | 調整老化時間（預設 300 秒） | ★★ |

> [!warning] ★★★★ `clear ethernet-switching table` 會造成短暫流量氾洪
> 清空之後交換器必須重新學習，這段期間所有單播都變成廣播（unknown unicast flooding）。
> 在流量大的核心交換器上做，可能造成明顯的效能抖動。
> **排錯時優先用 `clear ethernet-switching table interface ge-0/0/1.0` 只清一個埠。**

## 完整實戰範例

**情境**：機關要在 3F 新增一個「會議室」VLAN（`MEETING`，vlan-id 40，網段 10.10.40.0/24），
需要：

1. 核心交換器 `core-ex4300` 建 VLAN、設 `irb.40` 當閘道、上聯 trunk 放行
2. 接取交換器 `acc-3f-ex2300` 建同一個 VLAN、trunk 放行、把 `ge-0/0/10`～`ge-0/0/13` 四個埠改成 MEETING
3. 驗證：會議室 PC 拿得到 10.10.40.x 的 DHCP、ping 得到閘道、上得了內網系統

★★★★★ **順序極重要：從核心往接取做，先建 VLAN 與 trunk，最後才動 access 埠。**
反過來做的話，access 埠改到一個上游還沒放行的 VLAN，使用者立刻斷網。

### 步驟 1：兩台都先備份與存 rescue ★★★★★

```text
netadmin@core-ex4300> show configuration | display set | save /var/tmp/core-before-CR0512.set
Wrote 683 lines of output to '/var/tmp/core-before-CR0512.set'

netadmin@core-ex4300> file copy /var/tmp/core-before-CR0512.set scp://netadmin@10.99.0.5//backup/core-ex4300/
Password for netadmin@10.99.0.5:

netadmin@core-ex4300> request system configuration rescue save
```

```text
netadmin@acc-3f-ex2300> show configuration | display set | save /var/tmp/acc3f-before-CR0512.set
netadmin@acc-3f-ex2300> file copy /var/tmp/acc3f-before-CR0512.set scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/
netadmin@acc-3f-ex2300> request system configuration rescue save
```

### 步驟 2：確認 vlan-id 40 沒被別人用掉 ★★★★

```text
netadmin@core-ex4300> show vlans brief | match " 40 "

netadmin@core-ex4300> show configuration vlans | display set | match "vlan-id 40"

netadmin@acc-3f-ex2300> show configuration vlans | display set | match "vlan-id 40"
```

★★★★ 三個指令都沒輸出 = 40 是乾淨的。
★★★★★ **不要只查你要改的那兩台** —— 同一個廣播網域裡任何一台用了 40 都會衝突。
盤點表（[[040-01-18-guide-網路設備-網路設備盤點與文件化]]）就是為了這一刻存在的。

### 步驟 3：核心交換器 —— 建 VLAN、irb、trunk ★★★★★

```text
netadmin@core-ex4300> configure exclusive
Entering configuration mode

[edit]
netadmin@core-ex4300# show | compare

[edit]
netadmin@core-ex4300# set vlans MEETING vlan-id 40
[edit]
netadmin@core-ex4300# set vlans MEETING description "3F 會議室 10.10.40.0/24 CR-2026-0512"
[edit]
netadmin@core-ex4300# set interfaces irb unit 40 description "GW for MEETING"
[edit]
netadmin@core-ex4300# set interfaces irb unit 40 family inet address 10.10.40.254/24
[edit]
netadmin@core-ex4300# set vlans MEETING l3-interface irb.40
[edit]
netadmin@core-ex4300# set interfaces ge-0/0/12 unit 0 family ethernet-switching vlan members MEETING
```

★★★★ `ge-0/0/12` 是核心接到 3F 接取交換器的那條 trunk，**只加不刪**。

```text
[edit]
netadmin@core-ex4300# show | compare
[edit interfaces]
+   irb {
+       unit 40 {
+           description "GW for MEETING";
+           family inet {
+               address 10.10.40.254/24;
+           }
+       }
+   }
[edit interfaces ge-0/0/12 unit 0 family ethernet-switching vlan]
       members [ OFFICE VOICE SERVER MGMT PARKING ];
+      members MEETING;
[edit vlans]
+   MEETING {
+       description "3F 會議室 10.10.40.0/24 CR-2026-0512";
+       vlan-id 40;
+       l3-interface irb.40;
+   }
```

★★★★★ 逐行檢查：
- `ge-0/0/12` 那段是 **`+ members MEETING`**（新增），**沒有** `- members [ ... ]`（取代）✔
- `irb` 只多了 `unit 40`，沒有動到 unit 10/20/30 ✔
- 沒有動到其他任何介面 ✔

```text
[edit]
netadmin@core-ex4300# commit check
configuration check succeeds
[edit]
netadmin@core-ex4300# commit confirmed 10 comment "CR-2026-0512 核心新增 MEETING VLAN 40"
commit confirmed will be automatically rolled back in 10 minutes unless confirmed
commit complete
```

```text
[edit]
netadmin@core-ex4300# run show vlans MEETING
Routing instance        VLAN name             Tag       Interfaces
default-switch          MEETING               40
                                                        ge-0/0/12.0*

[edit]
netadmin@core-ex4300# run show interfaces terse irb.40
Interface               Admin Link Proto    Local                 Remote
irb.40                  up    down inet     10.10.40.254/24
```

★★★★ `irb.40` 現在是 `up down` —— **正常**。還沒有任何裝置在 VLAN 40 裡，
autostate 把它拉下來了。等接取層的 PC 上線就會變 `up up`。

```text
[edit]
netadmin@core-ex4300# commit comment "CR-2026-0512 核心端確認"
commit complete
```

### 步驟 4：接取交換器 —— 建 VLAN、trunk 放行 ★★★★★

```text
netadmin@acc-3f-ex2300> configure exclusive
Entering configuration mode

[edit]
netadmin@acc-3f-ex2300# show | compare

[edit]
netadmin@acc-3f-ex2300# set vlans MEETING vlan-id 40
[edit]
netadmin@acc-3f-ex2300# set vlans MEETING description "3F 會議室 CR-2026-0512"
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members MEETING
[edit]
netadmin@acc-3f-ex2300# show | compare
[edit interfaces ge-0/0/48 unit 0 family ethernet-switching vlan]
       members [ OFFICE VOICE SERVER MGMT PARKING ];
+      members MEETING;
[edit vlans]
+   MEETING {
+       description "3F 會議室 CR-2026-0512";
+       vlan-id 40;
+   }
```

★★★★ 接取交換器**不需要** `l3-interface`（閘道在核心）。
接取層也設 `irb` 會造成同一個網段有兩個閘道，是典型的設計錯誤。

```text
[edit]
netadmin@acc-3f-ex2300# commit check
configuration check succeeds
[edit]
netadmin@acc-3f-ex2300# commit confirmed 10 comment "CR-2026-0512 接取層 MEETING VLAN"
commit confirmed will be automatically rolled back in 10 minutes unless confirmed
commit complete

[edit]
netadmin@acc-3f-ex2300# run show ethernet-switching interface ge-0/0/48.0
Logical interface        Vlan name            Tagging     Blocking
ge-0/0/48.0              MEETING              tagged      unblocked
                         MGMT                 tagged      unblocked
                         OFFICE               tagged      unblocked
                         PARKING              untagged    unblocked
                         SERVER               tagged      unblocked
                         VOICE                tagged      unblocked

[edit]
netadmin@acc-3f-ex2300# commit comment "CR-2026-0512 接取層 trunk 確認"
commit complete
```

★★★★★ **MEETING 顯示 `tagged`、PARKING 還是 `untagged`** —— trunk 正確，native VLAN 沒被動到。

### 步驟 5：改 access 埠（★★★★★ 這一步才會影響使用者）

```text
[edit]
netadmin@acc-3f-ex2300# configure exclusive
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/10 description "3F-MEETING-1 CR-2026-0512"
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/10 unit 0 family ethernet-switching interface-mode access
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/10 unit 0 family ethernet-switching vlan members MEETING
[edit]
netadmin@acc-3f-ex2300# delete interfaces ge-0/0/10 unit 0 family ethernet-switching vlan members OFFICE
```

四個埠都做完之後：

```text
[edit]
netadmin@acc-3f-ex2300# show | compare
[edit interfaces ge-0/0/10]
+   description "3F-MEETING-1 CR-2026-0512";
[edit interfaces ge-0/0/10 unit 0 family ethernet-switching vlan]
-       members OFFICE;
+       members MEETING;
[edit interfaces ge-0/0/11]
+   description "3F-MEETING-2 CR-2026-0512";
[edit interfaces ge-0/0/11 unit 0 family ethernet-switching vlan]
-       members OFFICE;
+       members MEETING;
[edit interfaces ge-0/0/12]
+   description "3F-MEETING-3 CR-2026-0512";
[edit interfaces ge-0/0/12 unit 0 family ethernet-switching vlan]
-       members OFFICE;
+       members MEETING;
[edit interfaces ge-0/0/13]
+   description "3F-MEETING-4 CR-2026-0512";
[edit interfaces ge-0/0/13 unit 0 family ethernet-switching vlan]
-       members OFFICE;
+       members MEETING;
```

★★★★★ **只有 10～13 四個埠**，`ge-0/0/48` 完全沒被動到。這就是你要看到的 diff。

```text
[edit]
netadmin@acc-3f-ex2300# commit check
configuration check succeeds
[edit]
netadmin@acc-3f-ex2300# commit confirmed 15 comment "CR-2026-0512 3F 會議室四埠改 MEETING"
commit confirmed will be automatically rolled back in 15 minutes unless confirmed
commit complete
```

★★★★ 這次給 15 分鐘 —— 需要請人到會議室實際插電腦測試，時間要留夠。

### 步驟 6：驗證 ★★★★★

請會議室的人把筆電接上 `ge-0/0/10`，然後：

```text
[edit]
netadmin@acc-3f-ex2300# run show ethernet-switching table vlan-id 40
Ethernet switching table : 2 entries, 2 learned
Routing instance : default-switch
   Vlan                MAC                 MAC      Logical                SVLBNH/  Active
   name                address             flags    interface              VENH Index  source
   MEETING             a0:ce:c8:33:71:04   D        ge-0/0/10.0
   MEETING             2c:6b:f5:11:0a:7e   D        ge-0/0/48.0
```

★★★★★ 筆電的 MAC 學在 `ge-0/0/10.0`、VLAN 是 MEETING —— 二層通了。

```text
netadmin@core-ex4300> show interfaces terse irb.40
Interface               Admin Link Proto    Local                 Remote
irb.40                  up    up   inet     10.10.40.254/24
```

★★★★ `irb.40` 從 `up down` 變成 `up up` —— autostate 生效，三層閘道活了。

```text
netadmin@core-ex4300> show arp interface irb.40
MAC Address       Address         Name          Interface     Flags
a0:ce:c8:33:71:04 10.10.40.37     10.10.40.37   irb.40        none
```

★★★★★ 筆電拿到 `10.10.40.37`（DHCP relay 有正常運作）並被核心學到 ARP —— 三層也通了。

現場再確認三件事（★★★★★ 這三個一定要人實際測，不能只看指令）：

| 驗證項 | 通過標準 |
| --- | --- |
| DHCP | `ipconfig`／`ip a` 顯示 `10.10.40.x`，閘道 `10.10.40.254` |
| 閘道連通 | `ping 10.10.40.254` 有回應 |
| 服務連通 | 開得了公文系統／內網首頁；`ping` 得到 DNS 伺服器 |

```text
[edit]
netadmin@acc-3f-ex2300# commit comment "CR-2026-0512 現場驗證通過，確認定案"
commit complete
```

### 步驟 7：收尾 ★★★★

```text
netadmin@acc-3f-ex2300> show configuration | display set | save /var/tmp/acc3f-after-CR0512.set
netadmin@acc-3f-ex2300> file copy /var/tmp/acc3f-after-CR0512.set scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/
netadmin@acc-3f-ex2300> request system configuration rescue save

netadmin@core-ex4300> show configuration | display set | save /var/tmp/core-after-CR0512.set
netadmin@core-ex4300> file copy /var/tmp/core-after-CR0512.set scp://netadmin@10.99.0.5//backup/core-ex4300/
netadmin@core-ex4300> request system configuration rescue save
```

同時更新：VLAN 對照表、埠對照表、IP 網段規劃表（三份文件缺一不可）。

### 驗收檢查表 ★★★★★

| # | 檢查項 | 通過標準 | 星級 |
| --- | --- | --- | --- |
| 1 | vlan-id 40 全網段唯一 | 所有相關設備都查過，無衝突 | ★★★★★ |
| 2 | 兩台都先備份且存 rescue | 備份伺服器上有 before 檔 | ★★★★★ |
| 3 | 順序是「核心 → 接取 → access 埠」 | 變更紀錄時間順序正確 | ★★★★ |
| 4 | trunk 的 diff 只有 `+ members` | 沒有 `- members [ ... ]` | ★★★★★ |
| 5 | 全程 `commit confirmed` | 每次輸出都有 `automatically rolled back` | ★★★★★ |
| 6 | `show vlans MEETING` 成員正確 | 核心有 trunk、接取有 trunk + 四個 access | ★★★★ |
| 7 | `show ethernet-switching interface` tagging 正確 | MEETING tagged、PARKING 仍 untagged | ★★★★★ |
| 8 | MAC 學到正確 VLAN／埠 | `show ethernet-switching table vlan-id 40` | ★★★★★ |
| 9 | `irb.40` 變 `up up` | 至少一個成員埠上線後 | ★★★★ |
| 10 | 使用者實測 DHCP／閘道／服務 | 三項全過 | ★★★★★ |
| 11 | 兩台都已 `commit` 二次確認 | `show system commit` 第 0 筆是確認那筆 | ★★★★★ |
| 12 | after 備份、rescue 重存 | 備份伺服器上有 after 檔 | ★★★★ |
| 13 | VLAN 表／埠表／IP 表已更新 | 文件與現況一致 | ★★★★ |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 貼上網路找的設定，得到 `'port-mode' syntax error` | 這是**非 ELS** 語法，你的機型是 ELS | 改用 `interface-mode`。用 `set ... family ethernet-switching ?` 確認機型屬於哪一套 |
| ★★★★★ `commit` 失敗：`VLAN MEETING does not exist` | 介面引用了還沒建立的 VLAN，或**名稱大小寫不符** | 先 `set vlans MEETING vlan-id 40`。★★★★ 名稱大小寫敏感，`meeting` ≠ `MEETING` |
| ★★★★★ 改完 trunk 之後整台交換器只剩一個 VLAN 通 | 用了 `delete ... vlan` 再 `set`，把成員清單整組換掉 | `rollback 1` + `commit` 立刻恢復。以後改 trunk 一律 `show \| compare` 確認沒有 `- members [ ... ]` |
| ★★★★★ 兩個 VLAN 的裝置莫名互通、DHCP 拿到錯誤網段 | trunk 兩端 **native VLAN 不一致** | 兩端 `show ethernet-switching interface <trunk>` 比對哪一個 VLAN 是 `untagged`，統一成同一個專用 VLAN |
| ★★★★ PC 接上去完全沒反應，`show interfaces terse` 沒有 `.0` 那行 | 忘記設 `unit 0 family ethernet-switching` | `set interfaces ge-0/0/x unit 0 family ethernet-switching interface-mode access` + `vlan members` |
| ★★★★ `show vlans` 看得到埠，但 `show ethernet-switching table` 學不到 MAC | 實體層不通（線／SFP／對端關機），或對端 VLAN 沒對上 | `show interfaces ge-0/0/x extensive` 看 link 與錯誤計數；對端也查一次 VLAN |
| ★★★★ access 埠設兩個 VLAN 被擋：`can have only one VLAN member` | access 模式限制 | 需要兩個 VLAN 就用語音 VLAN（`switch-options voip`）或改成 trunk（要確定對端支援） |
| ★★★★ 上聯 trunk 某個 VLAN 通不了，但設定看起來正確 | 對端 trunk 的 `vlan members` 沒放這個 VLAN | ★★★★★ **trunk 是雙向的，兩端都要放行**。兩端各跑一次 `show ethernet-switching interface` |
| ★★★★ `irb.40` 一直是 `up down`，閘道不通 | 該 VLAN 沒有任何 up 的成員埠（autostate） | 接一台裝置上去；或確認 trunk 有帶這個 VLAN。★★★ 真的要強制 up 可用 `set interfaces irb unit 40 ... ` 相關 autostate-exclude 選項，但通常不該這樣做 |
| ★★★★ `show configuration interfaces ge-0/0/5` 是空的，但埠有在運作 | 設定來自 `apply-groups` | 加 `\| display inheritance` |
| ★★★ 建了 VLAN 但 `show vlans` 裡沒有任何介面 | VLAN 建了，但沒有任何埠 `vlan members` 到它 | 確認 access 埠與 trunk 都有加成員 |
| ★★★ 語音 VLAN 設好但話機拿不到 VLAN 20 | 沒開 LLDP-MED，話機不知道要打 tag | `set protocols lldp interface all` + `set protocols lldp-med interface all` |
| ★★★ trunk 上明明沒放行某 VLAN，流量卻通 | 用了 `vlan members all` | 改成白名單明列；`show ethernet-switching interface` 會列出實際帶了哪些 |
| ★★★ 新增 VLAN 之後某些設備斷線 | vlan-id 與別的設備衝突（同號不同用途） | 全網段查 `show configuration vlans \| display set \| match "vlan-id N"`；盤點表補齊 |
| ★★★ MAC 表某個埠學到幾十個 MAC | 那個埠後面私接了 hub／交換器 | `show ethernet-switching table interface ge-0/0/x`；依政策處理（08 篇的 `interface-mac-limit`） |
| ★★ 大量 unknown unicast 氾洪、頻寬異常 | MAC 表被清空、或單向流量造成 MAC 老化 | `show ethernet-switching table summary` 看筆數；檢查是否有非對稱路由 |

### 排查步驟

**【1】先確認設定真的 commit 了 ★★★★★**

```text
[edit]
netadmin@sw# show | compare
```

有輸出 = 你的改動還在 candidate。這永遠是第一個要排除的。

**【2】確認 VLAN 存在、且埠是它的成員 ★★★★★**

```text
netadmin@sw> show vlans MEETING
Routing instance        VLAN name             Tag       Interfaces
default-switch          MEETING               40
                                                        ge-0/0/10.0*
                                                        ge-0/0/48.0*
```

- ★★★★ **VLAN 不存在** → `set vlans ... vlan-id N`
- ★★★★ **有 VLAN 但沒有 access 埠** → 埠沒設 `vlan members`
- ★★★★★ **有 access 埠但沒有 trunk 埠** → 上聯沒放行，這個 VLAN 出不了這台交換器
- ★★★★ **有埠但沒有 `*`** → 那個埠實體 down，跳【5】

**【3】確認 tag 行為（access／trunk／native）★★★★★**

```text
netadmin@sw> show ethernet-switching interface ge-0/0/10.0
Logical interface        Vlan name            Tagging     Blocking
ge-0/0/10.0              MEETING              untagged    unblocked
```

| 看到什麼 | 意思 |
| --- | --- |
| access 埠顯示 `untagged` | ★★★★ 正確 |
| access 埠顯示 `tagged` | ★★★★★ 這個埠其實是 trunk 模式，接 PC 會不通 |
| trunk 埠某 VLAN 顯示 `untagged` | ★★★★ 那就是 native VLAN。**確認是你要的那一個** |
| `Blocking` 欄不是 `unblocked` | ★★★★★ 被 STP 阻斷了，見 [[040-01-16-guide-網路設備-鏈路聚合與STP]] |

**【4】確認真的有學到 MAC ★★★★★**

```text
netadmin@sw> show ethernet-switching table vlan-id 40
Ethernet switching table : 0 entries, 0 learned
```

**0 筆 = 二層根本沒通。** 這是設定正確但實際不通的決定性證據，往【5】查實體層。
有學到 MAC 但使用者說不通 → 問題在三層（閘道、DHCP、路由、防火牆），不在 VLAN。

**【5】實體層 ★★★★**

```text
netadmin@sw> show interfaces ge-0/0/10 | match "Physical|Link-level|Last flapped"
Physical interface: ge-0/0/10, Enabled, Physical link is Down
  Link-level type: Ethernet, MTU: 1514, Speed: Auto, Duplex: Auto
  Last flapped   : 2026-09-02 08:12:44 CST (06:31:22 ago)
```

- `Physical link is Down` → 線、對端、SFP。埠參數與錯誤計數的完整排查見
  [[040-01-08-guide-Juniper-埠設定與安全]]
- `Enabled` 變成 `Administratively down` → 這個埠被 `disable` 了

**【6】對端也查一次 ★★★★★**

```text
netadmin@core-ex4300> show ethernet-switching interface ge-0/0/12.0
```

★★★★★ **trunk 問題有一半是「只改了一端」。** 兩端的 `vlan members` 與 native VLAN 都要對得上。
機關網路的標準做法是：trunk 的兩端設定寫在同一張變更單上，一起改、一起驗。

**【7】還是不通就先恢復服務 ★★★★★**

```text
[edit]
netadmin@sw# rollback 1
[edit]
netadmin@sw# show | compare
[edit]
netadmin@sw# commit confirmed 5
```

先讓使用者能上班，再到測試環境慢慢重現。原則見 [[100-02-10-guide-維運-故障排除方法論]]。

## 安全性注意事項

> [!danger] ★★★★★ VLAN 是「分段」不是「隔離」
> VLAN 讓不同群組在**二層**上分開，但只要有 `irb` 三層閘道，
> VLAN 之間預設就是**可以互相路由的**。「我把伺服器放在獨立 VLAN 所以很安全」是常見的誤解。
> 真正的隔離需要在 `irb` 或 trunk 上套 **firewall filter**（見 08 篇與
> [[090-02-08-guide-防護-系統強化與稽核]]），或把流量導到防火牆做政策管制。

| 項目 | 風險 | 做法 | 星級 |
| --- | --- | --- | --- |
| 用 VLAN 1 當 native | ★★★★★ VLAN hopping（double tagging）攻擊的前提 | native 用專用的 PARKING VLAN（999），且該 VLAN 不接任何裝置、不給 L3 | ★★★★★ |
| trunk 用 `vlan members all` | 未來新 VLAN 自動放行，稽核無法證明隔離 | ★★★★★ 一律白名單明列 | ★★★★★ |
| 未使用的埠留在 `default` VLAN | 任何人插上網線就進了預設廣播網域 | ★★★★★ 未用埠 `disable` + 丟進 PARKING，見 08 篇 | ★★★★★ |
| 接取埠設成 trunk | ★★★★★ 使用者的設備可以自行選擇進入任何 VLAN | 接終端一律 access；trunk 埠列冊管理 | ★★★★★ |
| VLAN 名稱／描述沒寫 | 三年後沒人知道哪個 VLAN 能不能停用，只好都留著 | `description` 寫用途、網段、負責單位 | ★★★★ |
| 管理 VLAN 與使用者 VLAN 同一個 | ★★★★★ 使用者可直接掃描、攻擊設備管理介面 | 管理走獨立 VLAN（MGMT 99）或帶外管理，見 07 篇 | ★★★★★ |
| 語音 VLAN 沒隔離 | 話機網段可以被 PC 直接存取 | VOICE VLAN 套 filter 只放行 SIP／RTP 與 TFTP | ★★★ |
| 開 MVRP 自動註冊 VLAN | 接上一台設定錯誤的設備就影響全網 | ★★★★ 機關環境不建議開，手動管理 | ★★★★ |
| 設定備份未加保護 | 完整 VLAN 與網段規劃外洩＝攻擊地圖 | 備份區限權限、走 SCP、不放共用槽 | ★★★★★ |
| trunk 只改一端就上線 | 兩端不一致造成 VLAN 混流或斷線 | 兩端寫同一張變更單，一起改一起驗 | ★★★★ |

> [!warning] ★★★★ 稽核常見缺失：「無法提出 VLAN 與埠的對應清單」
> 資安稽核會要求提出「哪些埠屬於哪個 VLAN、為什麼」。
> 現場臨時用 `show vlans` 導出來是可以的，但**證明不了「這就是設計如此」**。
> 正確做法是維護一份與設備同步的埠對照表（見
> [[040-01-18-guide-網路設備-網路設備盤點與文件化]]），
> 並用 `show configuration vlans | display set` 的備份做為佐證。

## 速查表

| 指令 / 設定項 | 說明 | 星級 |
| --- | --- | --- |
| `set vlans OFFICE vlan-id 10` | 建立 VLAN（名稱大小寫敏感） | ★★★★★ |
| `set vlans OFFICE description "..."` | VLAN 用途說明 | ★★★★ |
| `set vlans OFFICE l3-interface irb.10` | 綁三層閘道介面（**ELS**） | ★★★★ |
| `set vlans office l3-interface vlan.10` | 同上（**非 ELS**） | ★★★ |
| `set vlans V100-110 vlan-id-list 100-110` | 一次建立連號 VLAN | ★★ |
| `set int ge-0/0/1 unit 0 family ethernet-switching interface-mode access` | access 埠（**ELS**） | ★★★★★ |
| `set int ge-0/0/1 unit 0 family ethernet-switching port-mode access` | access 埠（**非 ELS**） | ★★★★ |
| `set int ge-0/0/1 unit 0 family ethernet-switching vlan members OFFICE` | 指定 VLAN 成員 | ★★★★★ |
| `set int ge-0/0/48 unit 0 family ethernet-switching interface-mode trunk` | trunk 埠（**ELS**） | ★★★★★ |
| `set int ge-0/0/48 unit 0 family ethernet-switching vlan members [ A B C ]` | 多個 VLAN（★★★★★ **追加語意**） | ★★★★★ |
| `delete int ge-0/0/48 unit 0 family ethernet-switching vlan members B` | 移除單一 VLAN（要寫完整路徑） | ★★★★★ |
| `set int ge-0/0/48 native-vlan-id 999` | native VLAN（**ELS**，實體層） | ★★★★ |
| `set int ge-0/0/48 unit 0 family ethernet-switching native-vlan-id 999` | native VLAN（**非 ELS**，unit 層） | ★★★★ |
| `set switch-options voip interface ge-0/0/2.0 vlan VOICE` | 語音 VLAN（**ELS**） | ★★★ |
| `set ethernet-switching-options voip interface ge-0/0/2.0 vlan voice` | 語音 VLAN（**非 ELS**） | ★★★ |
| `set protocols lldp interface all` + `lldp-med` | 讓話機知道語音 VLAN | ★★★★ |
| `set int irb unit 10 family inet address 10.10.10.254/24` | 三層閘道 IP | ★★★★ |
| `set interfaces ge-0/0/20 disable` | 停用未用埠 | ★★★★★ |
| `show vlans` | VLAN 與成員埠（`*` = up） | ★★★★★ |
| `show vlans MEETING` / `show vlans brief` / `show vlans extensive` | 單一／簡要／詳細 | ★★★★ |
| `show ethernet-switching interface`（ELS） | 每個邏輯介面帶哪些 VLAN、tagged 或 untagged | ★★★★★ |
| `show ethernet-switching interfaces`（非 ELS） | 同上（★★★★ 指令名稱多一個 s） | ★★★★ |
| `show ethernet-switching table` | MAC 表（**真的通了才會有**） | ★★★★★ |
| `show ethernet-switching table vlan-id 40` | 只看某 VLAN 的 MAC | ★★★★ |
| `show ethernet-switching table interface ge-0/0/1.0` | 這個埠後面掛了幾台（抓私接 hub） | ★★★★ |
| `clear ethernet-switching table interface ge-0/0/1.0` | 只清單一埠（避免全表氾洪） | ★★★ |
| `show interfaces terse \| match irb` | 所有 L3 VLAN 介面狀態 | ★★★★ |
| `show configuration vlans \| display set` | 匯出 VLAN 設定（備份／稽核佐證） | ★★★★★ |
| `show configuration interfaces ge-0/0/5 \| display inheritance` | 展開 `apply-groups` 繼承 | ★★★ |
| `show \| compare` | ★★★★★ commit 前必看，特別注意 `- members [ ... ]` | ★★★★★ |
| `commit confirmed 10 comment "..."` | 遠端變更標準做法 | ★★★★★ |
| `interface-mode` vs `port-mode` | ★★★★★ ELS vs 非 ELS 的分水嶺 | ★★★★★ |
| `irb.N` vs `vlan.N` | 同上，L3 VLAN 介面命名 | ★★★★★ |
| `switch-options` vs `ethernet-switching-options` | 同上，二層全域選項階層 | ★★★★ |

## 練習題

> [!question]- 練習 1：判定機型屬於 ELS 還是非 ELS ★★★★★
> 在你能碰到的每一台 Juniper 交換器上（或 vJunos 模擬環境）：
> 1. `show version | match "Model|Junos:"` 記下機型與版本
> 2. 進 `configure`，打 `set interfaces ge-0/0/1 unit 0 family ethernet-switching ?`
> 3. 記下看到的是 `interface-mode` 還是 `port-mode`
> 4. `show interfaces terse | match "^irb|^vlan"` 交叉驗證
> 5. `rollback 0` 離開
>
> 做成一張表：機型 / Junos 版本 / ELS 或非 ELS / L3 介面名稱。
> 這張表要放進 [[040-01-18-guide-網路設備-網路設備盤點與文件化]] 的設備清冊。

> [!question]- 練習 2：親手製造並修復「trunk 成員被清空」★★★★★
> **務必在測試設備上做。**
> 1. 建三個 VLAN（A/B/C），設一個 trunk `members [ A B C ]`，`commit`
> 2. 記下 `show ethernet-switching interface <trunk>` 的輸出
> 3. `delete interfaces <trunk> unit 0 family ethernet-switching vlan`
> 4. `set interfaces <trunk> unit 0 family ethernet-switching vlan members A`
> 5. `show | compare` —— **仔細看那個 `-` 開頭的行**
> 6. `rollback 0`，確認 `show | compare` 空了
> 7. 改用正確做法：只 `delete ... vlan members B`，再 `show | compare`
>
> **要回答的問題**：第 5 步的 diff 跟第 7 步差在哪？如果第 5 步不小心 commit 了，
> 使用者會遇到什麼現象？你要用哪一個指令在 30 秒內恢復？

> [!question]- 練習 3：native VLAN 不一致的實驗 ★★★★★
> 用兩台測試交換器串一條 trunk：
> 1. 兩端都設 `native-vlan-id 999`，兩端 members 都放 `[ A B PARKING ]`，各接一台 PC 在 VLAN A
> 2. 確認兩台 PC 互通、`show ethernet-switching interface <trunk>` 兩端都顯示 PARKING `untagged`
> 3. 把其中一端改成 `native-vlan-id 998`（先建 VLAN 998），`commit`
> 4. 觀察：有沒有任何錯誤訊息？兩端的 `show ethernet-switching interface` 各顯示什麼？
> 5. 在 native VLAN 上接一台 PC，看它能不能跟對端 native VLAN 上的裝置互通
>
> **要回答的問題**：設備有沒有告訴你設定錯了？如果沒有，維運人員要靠什麼發現這個問題？
> 寫出一個可以排進每季維護（[[100-02-05-guide-維運-每季維護作業]]）的檢查程序。

> [!question]- 練習 4：把整台交換器的 VLAN 與埠對照匯出成文件 ★★★★
> 1. `show vlans | save /var/tmp/vlans.txt`
> 2. `show ethernet-switching interface | save /var/tmp/eth-int.txt`
> 3. `show interfaces descriptions | save /var/tmp/desc.txt`
> 4. `show configuration vlans | display set | save /var/tmp/vlans.set`
> 5. 全部 `file copy` 到你的電腦
> 6. 整理成一張表：埠號 / 描述 / 模式（access/trunk） / VLAN / 用途 / 是否啟用
>
> **要回答的問題**：哪些埠在 `default` VLAN 裡？哪些埠沒有 description？
> 這兩類各代表什麼管理問題？依 08 篇的政策，它們應該被怎麼處理？

> [!question]- 練習 5：規劃一份 VLAN 標準 ★★★★
> 依你們單位的實際情況，寫出一份 VLAN 命名與編號標準，至少包含：
> - VLAN 編號分段規則（例如 10-49 使用者、50-89 伺服器、90-99 管理、900+ 特殊用途）
> - 名稱規則（大小寫、允許字元、長度）
> - 每個 VLAN 必填的 `description` 格式
> - native VLAN 的統一規定
> - 未用埠的處理政策
> - 新增 VLAN 的作業流程（誰核准、要更新哪些文件、要在哪些設備上做）
>
> 與 [[040-01-03-guide-網路設備-VLAN概念與規劃]] 和
> [[040-01-02-guide-網路設備-IP位址規劃與子網切分]] 對照，確認 VLAN 與網段一一對應。

## 小測驗

Q1. 你把網路上找到的 `set interfaces ge-0/0/1 unit 0 family ethernet-switching port-mode access` 貼到 EX4300 上，CLI 報 syntax error。原因是什麼？正確的寫法？你要怎麼在動手前就知道該用哪一套？

Q2. 這行指令會發生什麼事：`set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members MEETING`（該 trunk 原本是 `members [ OFFICE VOICE SERVER ]`）？跟 Cisco 的 `switchport trunk allowed vlan 40` 語意有什麼致命差異？

Q3. 是非題：JunOS 的 trunk 兩端 native VLAN 不一致時，設備會在日誌裡產生告警。請說明理由與影響。

Q4. `show vlans MEETING` 顯示有 `ge-0/0/10.0*` 和 `ge-0/0/48.0*` 兩個成員，但使用者說不通。你接下來要看哪一個指令？看到什麼結果代表「二層根本沒通」？

Q5. `show ethernet-switching interface ge-0/0/1.0` 顯示這個接 PC 的埠是 `tagged`。這代表什麼？使用者會遇到什麼現象？

Q6. 核心交換器上 `irb.40` 一直顯示 `up down`，`show configuration interfaces irb unit 40` 看起來完全正確。最可能的原因是什麼？這算故障嗎？

Q7. 為什麼 trunk 不該用 `vlan members all`？請從「未來變更」「稽核」「效能」三個角度各講一點。

Q8. 一個 access 埠要同時讓 IP 話機（VLAN 20）與掛在話機後面的 PC（VLAN 10）使用。JunOS（ELS）上完整的設定是什麼？漏掉哪一項會造成「話機拿不到語音 VLAN」？

Q9. 你要在核心與接取兩台交換器上新增一個 VLAN，並把四個 access 埠改過去。正確的執行順序是什麼？順序做反會發生什麼？

Q10. 稽核人員問「請證明會計 VLAN 的流量不會跑到訪客 VLAN」。你會提出哪些指令輸出與文件？為什麼「我們用了不同的 VLAN」這個回答不足以構成證明？

> [!question]- 測驗答案
> **Q1.** ★★★★★ 因為 `port-mode` 是 **非 ELS**（EX2200／EX3200／EX3300／EX4200 等舊機種）的語法，
> 而 EX4300 是 **ELS** 機種，關鍵字改成了 `interface-mode`。
> 正確寫法：`set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access`。
> ★★★★★ 動手前的判定方法有兩個，都不用猜：
> 1. 在設定模式打 `set interfaces ge-0/0/1 unit 0 family ethernet-switching ?`，
>    看補完清單裡出現的是 `interface-mode` 還是 `port-mode`
> 2. `show interfaces terse | match "^irb|^vlan"` —— 有 `irb` 是 ELS，有 `vlan.N` 是非 ELS
>
> 連帶要記得換的還有：`irb` vs `vlan`、`switch-options` vs `ethernet-switching-options`、
> `show ethernet-switching interface`（單數）vs `interfaces`（複數）、native-vlan-id 的階層位置。
> 見「ELS 與非 ELS」。
>
> **Q2.** ★★★★★ JunOS 的 `set ... vlan members X` 是**追加**，結果是
> `members [ OFFICE VOICE SERVER MEETING ]` —— 原本三個 VLAN 都還在，這是安全的操作。
> ★★★★★ **致命差異**：Cisco 的 `switchport trunk allowed vlan 40`（不帶 `add`）是**整組取代**，
> 打下去的瞬間 OFFICE／VOICE／SERVER 全部從這條 trunk 消失，整台交換器只剩 VLAN 40 通得出去。
> Cisco 上要追加必須寫 `switchport trunk allowed vlan add 40`。
>
> ★★★★ 反過來，JunOS 的對應陷阱是「我以為我把清單換掉了，其實舊的還在」——
> 想清乾淨要先 `delete ... vlan` 再 `set`，而那個 `delete` 才是真正危險的指令。
> **兩種平台的共同解法都是 commit／送出前確認最終狀態**，JunOS 有 `show | compare` 可以直接看。
> 見「修改 trunk 成員時最容易出事的地方」。
>
> **Q3.** ★★★★★ **錯，JunOS 不會告警。**
> Cisco 有 CDP 會產生 `%CDP-4-NATIVE_VLAN_MISMATCH`，Juniper 用 LLDP 而 LLDP **不比對 native VLAN**，
> 所以兩端設不一致時**兩邊都認為自己是對的、完全不會報錯**。
> 影響：兩個不同 VLAN 的無 tag 流量被接在一起（VLAN leaking）——
> A 端 native 是 1、B 端 native 是 999，那麼 A 的 VLAN 1 流量會跑進 B 的 VLAN 999，反之亦然。
> 症狀是裝置偶爾能 ping 到不該通的網段、DHCP 拿到錯誤網段的位址、廣播跨網段。
> ★★★★★ 這是「查一整天都查不到」的典型案例，因為兩端的設定各自看起來都正確。
> 防法：全機關 native VLAN 統一用一個沒有任何裝置的專用 VLAN，
> 並把「兩端 `show ethernet-switching interface` 比對 untagged 的是哪一個 VLAN」排進定期檢查。
> 見「native-vlan-id」。
>
> **Q4.** ★★★★★ 下一個要看 **`show ethernet-switching table vlan-id 40`**。
> `show vlans` 只證明「設定寫對了、埠是這個 VLAN 的成員、且介面 up」，
> **不證明流量真的走得通**。
> 看到 `Ethernet switching table : 0 entries, 0 learned` ——
> **二層根本沒學到任何 MAC，等於完全沒通**，要往實體層與對端設定查
> （線、SFP、對端關機、對端 VLAN 沒對上）。
> 反過來如果 MAC 學得到，那問題就不在 VLAN 而在三層（閘道、DHCP relay、路由、防火牆），
> 排查方向完全不同。見「排查步驟【4】」。
>
> **Q5.** ★★★★★ 代表這個埠實際上是 **trunk 模式**（或它在該 VLAN 上是以 tagged 成員存在），
> 不是 access。一般 PC 的網卡不會處理 802.1Q tag，所以：
> - PC 送出的無 tag 封包會落到 **native VLAN**（若有設）或被丟棄
> - 交換器送給 PC 的封包帶著 tag，PC 網卡直接丟掉
>
> 使用者的現象是「網路孔沒反應」「拿不到 IP」，或更難查的「有時候通有時候不通」
> （通的時候是走 native VLAN，走到錯誤的網段去了）。
> 修正：`set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access`
> 並確認 `vlan members` 只有一個。
> ★★★★ 資安上這也是缺失：接取埠是 trunk，使用者可以自己打 tag 進入任何 VLAN。
> 見「access 與 trunk」與「安全性注意事項」。
>
> **Q6.** ★★★★ 最可能的原因是 **autostate** —— `irb.N` 只有在對應 VLAN 至少有一個
> **up 的成員埠**時才會 up。新建的 VLAN 還沒接任何裝置，或該 VLAN 只存在於 trunk
> 但下游還沒有裝置上線，`irb` 就會是 `up down`。
> ★★★★ **這不是故障，是設計行為**（避免對一個沒有任何裝置的網段宣告路由）。
> 驗證：`show vlans MEETING` 看有沒有帶 `*` 的成員；接一台裝置上去後再看，
> 應該會變成 `up up`，而且核心的 `show route` 也會出現該網段的直連路由。
> 見「L3 VLAN 介面（irb）」與「完整實戰範例步驟 6」。
>
> **Q7.** ★★★★★
> 1. **未來變更**：`members all` 的意思是「這台上所有 VLAN」，
>    所以**日後任何人新增的任何 VLAN 都會自動跑到這條 trunk 上**，
>    包括你原本刻意要隔離的機密網段，而且沒有任何人會收到通知。
> 2. **稽核**：稽核要求「證明 A 網段到不了 B 網段」，`members all` 讓你無法用設定佐證，
>    只能說「目前沒有」——這不構成控制措施，會被開缺失。
> 3. **效能**：廣播、未知單播、多播的複製範圍變大，全部塞進這條上聯，
>    在核心與接取之間浪費頻寬；VLAN 數量多時尤其明顯。
>
> 正確做法是白名單明列。多打幾個字換來可預測、可稽核、可版控。見「VLAN 範圍與批次設定」。
>
> **Q8.** ★★★★ ELS 完整設定：
> ```junos
> set interfaces ge-0/0/2 description "3F-A13 話機+PC"
> set interfaces ge-0/0/2 unit 0 family ethernet-switching interface-mode access
> set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members OFFICE
> set switch-options voip interface ge-0/0/2.0 vlan VOICE
> set switch-options voip interface ge-0/0/2.0 forwarding-class expedited-forwarding
> set protocols lldp interface all
> set protocols lldp-med interface all
> ```
> ★★★★★ **漏掉 `lldp-med` 就會造成「話機拿不到語音 VLAN」** ——
> 話機是靠 LLDP-MED 從交換器學到「你應該用 VLAN 20 並打 tag」的。
> 沒有它，話機會用 untagged 送出，落到 OFFICE VLAN，
> 症狀是拿不到話機專用的 DHCP／TFTP 設定，或通話品質很差（沒吃到 QoS）。
> 驗證：`show ethernet-switching interface ge-0/0/2.0` 應該顯示
> OFFICE `untagged` 與 VOICE `tagged` 兩行。見「語音 VLAN」。
>
> **Q9.** ★★★★★ 正確順序是 **核心 → 接取 → access 埠**，也就是**由上而下、先鋪路再導流**：
> 1. 核心：建 VLAN、設 `irb` 閘道、下聯 trunk 加 members
> 2. 接取：建同一個 VLAN、上聯 trunk 加 members
> 3. 接取：把 access 埠改到新 VLAN（這一步才會影響使用者）
>
> 順序做反（先改 access 埠）的後果：★★★★★ 使用者的埠已經進了新 VLAN，
> 但上游 trunk 還沒放行、核心也還沒有閘道 —— **這些使用者立刻完全斷網**，
> 而且中間你還要花時間去核心設定，斷線時間就是那幾分鐘。
> 若中途發現核心那邊有問題要回退，斷線時間更長。
> ★★★★ 同樣的原則反過來也適用：**移除一個 VLAN 時要由下而上** ——
> 先把 access 埠移走，最後才收 trunk 與核心的設定。見「完整實戰範例」。
>
> **Q10.** ★★★★★ 要提出的是**設定佐證 + 控制措施 + 文件**三件套：
> 1. `show configuration vlans | display set` 與
>    `show configuration interfaces | display set` 的完整輸出（證明 VLAN 定義與埠歸屬）
> 2. `show ethernet-switching interface`（證明每條 trunk 實際帶了哪些 VLAN，
>    以及沒有用 `members all`）
> 3. ★★★★★ **三層管制的證據** —— `show configuration firewall`、
>    `irb` 上套用的 filter、或防火牆政策的截圖／匯出
> 4. 埠對照表與 VLAN 規劃文件（證明這是設計，不是巧合）
>
> ★★★★★ 「我們用了不同的 VLAN」**不足以構成證明**，因為 VLAN 只是**二層分段**：
> 只要核心上兩個 VLAN 都有 `irb` 閘道，而中間沒有任何過濾規則，
> **這兩個網段預設就是可以互相路由的**，會計網段的封包送到閘道後照樣會被轉去訪客網段。
> 真正的隔離必須在三層做：`irb` 套 firewall filter、或把 VLAN 間流量導到防火牆做政策管制。
> 見「安全性注意事項」與 [[090-02-08-guide-防護-系統強化與稽核]]。

## 延伸閱讀

- [[040-01-05-cmd-Juniper-JunOS-基礎操作]] —— candidate／commit confirmed／rollback，本篇的操作基礎
- [[040-01-07-guide-Juniper-管理IP與遠端存取]] —— `irb`／`me0` 管理 IP、SSH、使用者權限、保護 RE 的 filter
- [[040-01-08-guide-Juniper-埠設定與安全]] —— speed／MTU／storm-control／MAC 限制／未用埠隔離
- [[040-01-09-svc-Juniper-設定備份與韌體升級]] —— VLAN 設定的備份、還原與換機
- [[040-01-16-guide-網路設備-鏈路聚合與STP]] —— trunk 做成 `ae0`、STP 在 VLAN 上的行為
- [[040-01-11-guide-Cisco-VLAN與Trunk設定]] —— Cisco 那一側的完整內容
- [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]] —— 兩邊指令的完整雙欄對照
- [[040-01-03-guide-網路設備-VLAN概念與規劃]] —— VLAN 編號怎麼配、切幾個才合理
- [[040-01-02-guide-網路設備-IP位址規劃與子網切分]] —— VLAN 與網段的一一對應
- [[040-01-17-guide-網路設備-交換器故障排除]] —— 跨廠牌的通用排錯流程
- [[040-01-18-guide-網路設備-網路設備盤點與文件化]] —— VLAN 表、埠對照表怎麼維護
- [[010-02-16-guide-網概-VLAN與網路分段]] —— 802.1Q 原理複習
- Juniper EX Series Ethernet Switching User Guide：<https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/>
- Juniper Feature Explorer（查某機型／版本支援哪些功能）：<https://apps.juniper.net/feature-explorer/>
