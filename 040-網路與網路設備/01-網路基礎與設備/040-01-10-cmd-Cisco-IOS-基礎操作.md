---
title: "Cisco IOS 基礎操作"
desc: "模式階層、do 指令、show 系列、running-config 與 startup-config 的差別與 write memory"
aliases: [Cisco IOS, enable, configure terminal, write memory, show running-config, terminal length 0]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-04-guide-網路設備-交換器初次設定與連線方式]]", "[[010-02-05-guide-網概-MAC位址與交換器]]"]
updated: 2026-09-02
---

# Cisco IOS 基礎操作

> [!note] 本手冊以 Juniper JunOS 為主線
> 本手冊的網路設備章節**以 Juniper JunOS 為主線**（見 [[040-01-05-cmd-Juniper-JunOS-基礎操作]]）。
> Cisco 這一組五篇的定位是**輔助線**：機關現場仍有大量在保或已過保的 Catalyst 交換器與
> ISR 路由器需要維運，接手時你不能說「我只會 JunOS」。
> 內容深度不打折，但**新採購請優先評估 JunOS 平台**，理由見 [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]]。

> [!abstract] 這篇你會學到
> - ★★★★★ **running-config 與 startup-config 是兩份不同的東西**：IOS 打完指令**當下就生效**，
>   但沒 `write memory` 就等於沒存 —— 這是 Cisco 世界最貴的一堂課
> - ★★★★★ 遠端改設定前先 `reload in 5`：改壞了、斷線了，五分鐘後設備自己重開回到
>   startup-config，等同 JunOS 的 `commit confirmed`
> - ★★★★ 四層模式階層（user EXEC → privileged EXEC → global config → interface config）
>   與提示符號怎麼讀，`exit` 與 `end` 差在哪
> - ★★★★ 在 config 模式下用 `do show ...` 查狀態，不用退出來再進去
> - ★★★★ `terminal length 0` 讓輸出不分頁，是所有「抓設定貼進工單」的前提
> - ★★★ 介面命名 `GigabitEthernet1/0/24` 三個數字各代表什麼，以及 `interface range` 批次設定
> - ★★★ `show run | section`、`| include`、`| begin` 三種過濾器，從 4000 行設定裡挖出你要的十行
> - 一份可以直接貼進交接文件的 30 列速查表

> [!warning] 未實機驗證
> ★★★★★ 本專案**沒有可供驗證的實體 Cisco 設備**。本篇所有指令依 Cisco IOS 15.2(7)E
> （Catalyst 2960-X／2960-L 系列）與 IOS-XE 17.x（Catalyst 9200／9300 系列）的官方
> 命令參考撰寫，輸出範例為依實際格式重建的**示意輸出**，機器序號、MD5、uptime 等
> 為虛構值。**不同 IOS 版本與不同機型的指令差異很大**，導入前務必：
> 1. 先在測試機或 Cisco Packet Tracer／CML 跑一遍
> 2. 用 `show version` 確認你的版本，再對照 Cisco 官方該版本的 Command Reference
> 3. 任何會中斷服務的指令，先照本篇「完整實戰範例」的 `reload in` 保險做法

## 前置知識

- [[040-01-04-guide-網路設備-交換器初次設定與連線方式]] —— Console 線、RJ45-to-USB 轉接、
  終端機軟體參數（9600 8N1）。**這篇假設你已經看得到設備的提示符號了。**
- [[010-02-05-guide-網概-MAC位址與交換器]] —— 交換器為什麼要學 MAC、CAM table 是什麼
- [[010-02-16-guide-網概-VLAN與網路分段]] —— VLAN 的觀念（設定寫法在下一篇）
- [[040-01-05-cmd-Juniper-JunOS-基礎操作]] —— 主線平台，兩邊對照著看效果最好

## 觀念說明

### IOS 最違反直覺的一件事：打完就生效，但沒存就會不見 ★★★★★

如果你是從 JunOS 或 Linux 過來的，第一個必須改掉的直覺是：

```text
JunOS：  改設定 ─▶ candidate config（草稿，不生效）─▶ commit ─▶ 生效且已存檔
Linux ： 改設定檔（已存檔，不生效）─▶ systemctl reload ─▶ 生效
Cisco ： 改設定 ─▶ ★ 立刻生效（running-config，只在 RAM）
                 ─▶ write memory ─▶ 才寫進 startup-config（NVRAM）
```

意思是 Cisco IOS 同時做了兩件會害死人的事：

| 特性 | 後果 | 星級 |
| --- | --- | --- |
| **沒有草稿區**，敲下 Enter 就生效 | 打錯一個 `shutdown` 立刻斷線，沒有 rollback 可按 | ★★★★★ |
| **生效與存檔分離**，忘記 `write` 就白做 | 三小時的設定，跳電後全部回到昨天 | ★★★★★ |
| 反過來也成立 | 改壞了**只要沒存**，重開機就自動復原 —— 這是救命特性 | ★★★★★ |

★★★★★ 最後一列請畫起來。**「沒存 = 重開就復原」正是 `reload in 5` 這個保命招的原理。**

### 兩份設定檔

| 名稱 | 存在哪 | 掉電會不會消失 | 怎麼看 |
| --- | --- | --- | --- |
| `running-config` | RAM | ★★★★★ **會消失** | `show running-config`（簡寫 `sh run`） |
| `startup-config` | NVRAM | 不會 | `show startup-config`（簡寫 `sh start`） |

存檔的兩種寫法**完全等價**，選一種用熟就好：

```cisco
SW-CORE-01#write memory
Building configuration...
[OK]
```

```cisco
SW-CORE-01#copy running-config startup-config
Destination filename [startup-config]?
Building configuration...
[OK]
```

> [!tip] ★★★★ 判斷「有沒有未存檔的變更」
> 最快的方法是比對兩份設定：
>
> ```cisco
> SW-CORE-01#show archive config differences system:running-config nvram:startup-config
> !Contextual Config Diffs:
> +interface GigabitEthernet1/0/8
> + description TEMP-TEST
> ```
>
> 有輸出＝有東西沒存。沒有差異時只會回一行 `!No changes were found`。
> ★★★ 這個指令在較舊的 IOS 12.x 上不一定存在，退而求其次可以用
> `show running-config | redirect flash:run.txt` 自己比對，或直接看
> `show run` 開頭那行 `Last configuration change at ...`
> 是不是比 `Last configuration change ... by ...` 之後的存檔時間新。

### 四層模式階層 ★★★★

IOS 的每一層都有自己能用的指令集，**提示符號就是你的座標**：

```text
連上 console／SSH
      │
      ▼
Switch>                         ← user EXEC（唯讀，幾乎什麼都不能做）
      │  enable
      ▼
Switch#                         ← privileged EXEC（★ 全部 show、reload、copy、debug）
      │  configure terminal
      ▼
Switch(config)#                 ← global config（改設備層級設定）
      │
      ├─ interface Gi1/0/1  ─▶ Switch(config-if)#     介面設定
      ├─ line vty 0 4       ─▶ Switch(config-line)#   終端線路設定
      ├─ vlan 10            ─▶ Switch(config-vlan)#   VLAN 設定
      ├─ router ospf 1      ─▶ Switch(config-router)# 路由協定
      └─ ip access-list standard MGMT ─▶ Switch(config-std-nacl)#
```

| 提示符號 | 模式 | 進入方式 | 你在這裡能做什麼 |
| --- | --- | --- | --- |
| `Switch>` | user EXEC | 登入後的預設 | `ping`、`show version`、`show clock`，其他多半被擋 |
| `Switch#` | privileged EXEC | `enable` | ★★★★ 所有 `show`、`copy`、`reload`、`write`、`debug` |
| `Switch(config)#` | global config | `configure terminal` | ★★★★ 改主機名、VLAN、AAA、ACL、全域參數 |
| `Switch(config-if)#` | interface | `interface <名稱>` | 改單一介面 |
| `Switch(config-if-range)#` | interface range | `interface range <範圍>` | ★★★ 批次改多個介面 |
| `Switch(config-line)#` | line | `line con 0` / `line vty 0 4` | 改 console／SSH 線路行為 |
| `Switch(config-vlan)#` | vlan | `vlan 10` | 命名 VLAN |
| `rommon 1 >` | ROMMON | 開機時 Ctrl+Break | ★★★★★ 救援模式，密碼救援與壞映像檔開機 |

### `exit` 與 `end` 的差別 ★★★

| 指令 | 行為 |
| --- | --- |
| `exit` | **退一層**。在 `config-if` 打就回到 `config`，在 `config` 打就回到 `#` |
| `end`（或 `Ctrl+Z`） | ★★★ **不管在第幾層，一次跳回 privileged EXEC `#`** |
| `disable` | 從 `#` 降回 `>` |
| `logout` / `exit`（在 `#`） | 斷開這條 session |

★★★ 實務上打完設定一律用 `end`，因為你不需要數自己在第幾層。

### 介面命名怎麼讀 ★★★

```text
GigabitEthernet1/0/24
└────┬────────┘ │ │ └─ 埠號（該模組上的第幾個埠）
     │          │ └─── 模組／子插槽（固定埠通常是 0）
     │          └───── 堆疊成員編號（stack member，單機一律 1）
     └──────────────── 介面型態與速率
```

| 寫法 | 常見於 | 說明 |
| --- | --- | --- |
| `FastEthernet0/1`（`Fa0/1`） | 2950／2960 舊款、ISR 路由器 | 100 Mbps |
| `GigabitEthernet0/1`（`Gi0/1`） | ★ ISR 路由器、非堆疊機型 | 兩段式編號 |
| `GigabitEthernet1/0/24`（`Gi1/0/24`） | ★★★ Catalyst 2960-X／9200／9300 | 三段式，第一碼是堆疊成員 |
| `TenGigabitEthernet1/1/1`（`Te1/1/1`） | 上行模組 | 10G 上行埠 |
| `Port-channel1`（`Po1`） | 鏈路聚合 | 邏輯介面，見 [[040-01-16-guide-網路設備-鏈路聚合與STP]] |
| `Vlan99`（`Vl99`） | SVI | 邏輯介面，交換器的管理 IP 掛這裡 |

★★★★ **簡寫可以用在指令輸入，但寫進工單與交接文件時一律寫全名。**
`Gi1/0/24` 在不同人手上會被讀成 `GigabitEthernet1/0/24` 或
`GigabitEthernet1/0/2` 加上打錯的 `4`，全名沒有這個問題。

## 環境準備與安裝

### 步驟 0：先確認你手上是什麼機器、什麼版本 ★★★★

**任何動作之前先跑這三個指令**，它決定了本篇後面每一段對你適不適用：

```cisco
SW-CORE-01>enable
Password:
SW-CORE-01#show version
Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E3, RELEASE SOFTWARE (fc2)
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2020 by Cisco Systems, Inc.
Compiled Thu 09-Apr-20 14:38 by prod_rel_team

ROM: Bootstrap program is C2960X boot loader
BOOTLDR: C2960X Boot Loader (C2960X-HBOOT-M) Version 15.2(4r)E1, RELEASE SOFTWARE (fc4)

SW-CORE-01 uptime is 41 weeks, 2 days, 6 hours, 18 minutes
System returned to ROM by power-on
System restarted at 08:12:03 UTC Mon Nov 18 2025
System image file is "flash:/c2960x-universalk9-mz.152-7.E3.bin"
Last reload reason: power-on

cisco WS-C2960X-24TS-L (APM86392) processor (revision D0) with 131072K bytes of memory.
Processor board ID FOC2148XXXX
Last reset from power-on
1 Virtual Ethernet interface
24 Gigabit Ethernet interfaces
4 Ten Gigabit Ethernet interfaces
The password-recovery mechanism is enabled.

512K bytes of flash-simulated non-volatile configuration memory.
Base ethernet MAC Address       : 00:1A:2B:3C:4D:00
Motherboard assembly number     : 73-16000-04
Model number                    : WS-C2960X-24TS-L
System serial number            : FOC2148XXXX

Configuration register is 0xF
```

要抓出來記在交接文件裡的五個欄位：

| 欄位 | 範例值 | 為什麼重要 | 星級 |
| --- | --- | --- | --- |
| `Version` | `15.2(7)E3` | ★★★★ 決定你能用哪些指令，也決定有沒有中 CVE |
| `Model number` | `WS-C2960X-24TS-L` | ★★★★ `-L` 是 LAN Base 授權，**不支援完整路由功能** |
| `System serial number` | `FOC2148XXXX` | ★★★ 報修、查保固、查 EoL 都靠它 |
| `System image file` | `flash:/c2960x-...bin` | ★★★★ 升級時要保留舊映像檔當退路 |
| `Configuration register` | `0xF`（交換器）／`0x2102`（路由器） | ★★★★★ 被改成 `0x2142` 會**開機時跳過 startup-config** |

> [!danger] ★★★★★ Configuration register 是 `0x2142` 代表這台機器現在會忽略設定檔開機
> `0x2142` 是密碼救援程序用的值，救援完必須改回 `0x2102`
> （`config-register 0x2102` 後 `write memory`）。忘記改回去的下場是：
> **下次跳電後這台交換器變成空白設定，整層樓斷網**，而且你會查很久才想到是這裡。
> 交換器（2960 系列）正常值是 `0xF`，路由器（ISR）正常值是 `0x2102`。

### 步驟 1：把終端機調成能用的樣子 ★★★★

**第一次連上任何一台 Cisco 設備，先打這一行**：

```cisco
SW-CORE-01#terminal length 0
```

沒有輸出，但它取消了 `--More--` 分頁。差別是：

```cisco
!-- 沒設 terminal length 0
SW-CORE-01#show running-config
Building configuration...

Current configuration : 4213 bytes
!
version 15.2
 --More--            ← ★★★ 卡在這裡，要一直按空白鍵，複製時還會夾雜分頁符號
```

```cisco
!-- 設了之後
SW-CORE-01#show running-config
Building configuration...

Current configuration : 4213 bytes
!
... (一次吐完 4213 bytes，可以整段複製貼進工單)
```

| 指令 | 作用 | 星級 |
| --- | --- | --- |
| `terminal length 0` | ★★★★ 本次 session 不分頁（斷線後失效） |
| `terminal length 24` | 恢復成每 24 行分頁 |
| `terminal width 512` | ★★★ 避免長行被折斷，`show run` 貼出來才不會亂 |
| `terminal monitor` | ★★★★ **在 SSH／telnet session 裡看得到 log 訊息**（console 本來就看得到） |
| `terminal no monitor` | 關掉 log 洗版 |

> [!warning] ★★★★ `terminal monitor` 加上 `debug` 是遠端斷線的經典死法
> 在 vty session 開 `terminal monitor` 再開一個高流量的 `debug ip packet`，
> log 訊息會塞爆你的 session，**你連要打 `undebug all` 的鍵盤輸入都送不出去**。
> 保命寫法：開 debug 之前先設好 `reload in 10`，或養成習慣用
> `show logging` 事後看，而不是即時 `debug`。
> 真的卡住了，按 **Ctrl+Shift+6** 送 break，或另開一條 session 打
> `undebug all`（可簡寫成 `u all`）。

### 步驟 2：跳過開機精靈

全新設備或 `erase startup-config` 之後開機會問：

```cisco
         --- System Configuration Dialog ---

Would you like to enter the initial configuration dialog? [yes/no]: no

Would you like to terminate autoinstall? [yes]: yes

Press RETURN to get started!

Switch>
```

★★★★ **一律回 `no`**。開機精靈產生的設定不符合機關的命名與安全規範，
自己一行一行打反而快，而且你會知道每一行是什麼。

> [!info]- Juniper JunOS 對照
> | 事情 | Cisco IOS | Juniper JunOS |
> | --- | --- | --- |
> | 進入特權模式 | `enable` | 登入即是（權限由使用者 class 決定） |
> | 進入設定模式 | `configure terminal` | `configure` 或 `edit`（★ JunOS 有獨立的 candidate 區） |
> | 設定何時生效 | ★★★★★ **打完立刻生效** | `commit` 之後才生效 |
> | 設定何時存檔 | ★★★★★ `write memory`（分開的動作） | `commit` **同時**生效與存檔 |
> | 帶保險的變更 | `reload in 5` ＋ 事後 `write` | ★ `commit confirmed 5` |
> | 看設定 | `show running-config` | `show configuration`（設定模式下 `show`） |
> | 看即時狀態 | `show interfaces status` | `show interfaces terse`（運維模式） |
> | 設定模式下查狀態 | ★★★★ `do show ...` | `run show ...` |
> | 回上一層 | `exit` | `up` |
> | 回頂層 | `end` 或 `Ctrl+Z` | `top` |
> | 不分頁 | `terminal length 0` | `set cli screen-length 0` |
> | 刪一行設定 | 在原指令前加 `no` | `delete <路徑>` |
>
> 完整對照見 [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]]，
> JunOS 的操作流程見 [[040-01-05-cmd-Juniper-JunOS-基礎操作]]。

## 基礎設定

### 進出各層模式

```cisco
Switch>enable
Switch#configure terminal
Enter configuration commands, one per line.  End with CNTL/Z.
Switch(config)#hostname SW-CORE-01
SW-CORE-01(config)#
```

★★★ 注意 `hostname` 一打完，**提示符號當場就變了** —— 這就是「立刻生效」最直觀的證明。

```cisco
SW-CORE-01(config)#interface GigabitEthernet1/0/24
SW-CORE-01(config-if)#description UPLINK-TO-SW-DIST-01
SW-CORE-01(config-if)#exit
SW-CORE-01(config)#exit
SW-CORE-01#
```

### 三個讓你少打七成字的技巧 ★★★★

**1. 縮寫**：只要不歧義，打前幾個字母就好。

```cisco
SW-CORE-01#sh ru                     ← show running-config
SW-CORE-01#conf t                    ← configure terminal
SW-CORE-01(config)#int gi1/0/1       ← interface GigabitEthernet1/0/1
SW-CORE-01(config-if)#no shut        ← no shutdown
SW-CORE-01#wr                        ← write memory
```

歧義時會被擋下來，這時多打一個字母即可：

```cisco
SW-CORE-01#s
% Ambiguous command:  "s"
SW-CORE-01#sh
% Type "show ?" for a list of subcommands
```

**2. Tab 補全**：打前幾個字母按 `Tab`，IOS 會補完整。
★★★ 寫給別人看的操作紀錄請用 Tab 補成全名，不要留縮寫。

**3. `?` 線上說明**：三種用法一定要會。

```cisco
SW-CORE-01#show ?
  aaa           Show AAA values
  access-lists  List access lists
  archive       Archive functions
  arp           ARP table
  ...
```

```cisco
SW-CORE-01#show ip int?
interface  interfaces
```

★★★ 注意 `int?`（**沒有空格**）＝「以 int 開頭的關鍵字有哪些」；
`int ?`（**有空格**）＝「int 後面可以接什麼」。這兩個差一個空格，意義完全不同。

```cisco
SW-CORE-01(config-if)#switchport mode ?
  access        Set trunking mode to ACCESS unconditionally
  dot1q-tunnel  set trunking mode to TUNNEL unconditionally
  dynamic       Set trunking mode to dynamically negotiate access or trunk mode
  trunk         Set trunking mode to TRUNK unconditionally
```

### `do`：不用退出設定模式就能查狀態 ★★★★

在 `config` 或 `config-if` 模式下，`show` 是**不能直接用**的：

```cisco
SW-CORE-01(config)#show ip interface brief
                   ^
% Invalid input detected at '^' marker.
```

前面加 `do` 就可以：

```cisco
SW-CORE-01(config)#do show ip interface brief
Interface              IP-Address      OK? Method Status                Protocol
Vlan1                  unassigned      YES NVRAM  administratively down down
Vlan99                 10.10.99.11     YES NVRAM  up                    up
GigabitEthernet1/0/1   unassigned      YES unset  up                    up
GigabitEthernet1/0/2   unassigned      YES unset  up                    up
GigabitEthernet1/0/3   unassigned      YES unset  down                  down
```

★★★★ `do` 對排錯效率的影響非常大：改一個介面 → `do show int gi1/0/1 status`
→ 沒好 → 再改，中間完全不用進出模式。
★★ `do write memory`、`do copy run start` 也成立，但**存檔還是建議 `end` 之後再做**，
避免半套設定被存進去。

### 一定要背起來的 show 指令 ★★★★

```cisco
SW-CORE-01#show ip interface brief
Interface              IP-Address      OK? Method Status                Protocol
Vlan99                 10.10.99.11     YES NVRAM  up                    up
GigabitEthernet1/0/1   unassigned      YES unset  up                    up
GigabitEthernet1/0/4   unassigned      YES unset  administratively down down
```

★★★★ `Status` 與 `Protocol` 兩欄要分開讀：

| Status | Protocol | 意義 |
| --- | --- | --- |
| `up` | `up` | 正常 |
| `up` | `down` | ★★★★ 實體連上了但協定沒起來（封裝不合、keepalive 失敗） |
| `down` | `down` | ★★★ 沒接線、對端關機、線壞了 |
| `administratively down` | `down` | ★★★ **有人打了 `shutdown`**，要 `no shutdown` |

```cisco
SW-CORE-01#show interfaces status
Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   AP-3F-01           connected    20         a-full  a-100 10/100/1000BaseTX
Gi1/0/2   PC-ACCT-014        connected    30         a-full a-1000 10/100/1000BaseTX
Gi1/0/3                      notconnect   1            auto   auto 10/100/1000BaseTX
Gi1/0/4                      disabled     999          auto   auto 10/100/1000BaseTX
Gi1/0/5                      err-disabled 30           auto   auto 10/100/1000BaseTX
Gi1/0/24  UPLINK-TO-DIST-01  connected    trunk      a-full a-1000 10/100/1000BaseTX
```

| Status 值 | 意義 | 星級 |
| --- | --- | --- |
| `connected` | 連線正常 | |
| `notconnect` | ★★★ 沒偵測到對端（線沒插、對端關機、線材壞） | ★★★ |
| `disabled` | ★★★ 管理者下了 `shutdown` | ★★★ |
| `err-disabled` | ★★★★ **被保護機制關掉**（port-security、BPDU guard、duplex mismatch） | ★★★★ |
| `monitoring` | SPAN 目的埠 | ★ |

★★★ `Duplex`／`Speed` 欄位前面的 `a-` 代表 **auto-negotiated（自動協商得到的結果）**。
沒有 `a-` 前綴＝人工寫死。詳見 [[040-01-13-guide-Cisco-埠設定與安全]]。

```cisco
SW-CORE-01#show vlan brief
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Gi1/0/6, Gi1/0/7, Gi1/0/8
10   MGMT                             active
20   WIFI-AP                          active    Gi1/0/1
30   OFFICE                           active    Gi1/0/2, Gi1/0/5
999  UNUSED-BLACKHOLE                 active    Gi1/0/4
1002 fddi-default                     act/unsup
1003 token-ring-default               act/unsup
1004 fddinet-default                  act/unsup
1005 trnet-default                    act/unsup
```

★★ 1002～1005 是遠古遺留的預設 VLAN，`act/unsup` 是正常的，不要去刪它。

```cisco
SW-CORE-01#show mac address-table
          Mac Address Table
-------------------------------------------

Vlan    Mac Address       Type        Ports
----    -----------       --------    -----
 All    0100.0ccc.cccc    STATIC      CPU
 All    0180.c200.0000    STATIC      CPU
  20    0050.56a1.2b3c    DYNAMIC     Gi1/0/1
  30    b827.ebaa.1122    DYNAMIC     Gi1/0/2
  99    0011.2233.4455    DYNAMIC     Gi1/0/24
Total Mac Addresses for this criterion: 5
```

★★★★ **這是「某台電腦到底插在哪個埠」的標準查法**：

```cisco
SW-CORE-01#show mac address-table address 0050.56a1.2b3c
          Mac Address Table
-------------------------------------------

Vlan    Mac Address       Type        Ports
----    -----------       --------    -----
  20    0050.56a1.2b3c    DYNAMIC     Gi1/0/1
```

```cisco
SW-CORE-01#show cdp neighbors
Capability Codes: R - Router, T - Trans Bridge, B - Source Route Bridge
                  S - Switch, H - Host, I - IGMP, r - Repeater, P - Phone,
                  D - Remote, C - CVTA, M - Two-port Mac Relay

Device ID        Local Intrfce     Holdtme    Capability  Platform  Port ID
SW-DIST-01       Gig 1/0/24        163              R S I WS-C3850- Gig 1/0/5
AP-3F-01         Gig 1/0/1         142                  T AIR-AP185 Gig 0
```

★★★★ **CDP 是「這條線接到哪台設備」最快的答案**，比翻線路圖快。
`show cdp neighbors detail` 還會給對端的管理 IP 與 IOS 版本。
★★★★ 但也因此 CDP 是資訊洩漏來源 —— 面向使用者的埠應該
`no cdp enable`，安全考量見本篇「安全性注意事項」。

| 指令 | 回答什麼問題 | 星級 |
| --- | --- | --- |
| `show version` | 型號、版本、序號、uptime、config-register | ★★★★ |
| `show running-config` | 現在生效的完整設定 | ★★★★★ |
| `show startup-config` | 重開機後會變成什麼樣子 | ★★★★★ |
| `show ip interface brief` | 每個介面的 IP 與 up/down | ★★★★ |
| `show interfaces status` | ★ 每個埠的 VLAN、速率、雙工、連線狀態 | ★★★★ |
| `show vlan brief` | VLAN 清單與各埠歸屬 | ★★★★ |
| `show mac address-table` | 哪台機器接在哪個埠 | ★★★★ |
| `show cdp neighbors detail` | 對端是什麼設備、IP、版本 | ★★★★ |
| `show interfaces counters errors` | 實體層錯誤統計（線材與雙工問題） | ★★★★ |
| `show logging` | 系統 log（設備上的緩衝區） | ★★★★ |
| `show processes cpu sorted` | CPU 被誰吃掉 | ★★★ |
| `show inventory` | 各模組／SFP 的型號與序號 | ★★★ |
| `show users` | 誰正連在這台設備上 | ★★★ |
| `show clock` | 現在時間（★★★ log 對得起來的前提） | ★★★ |
| `show flash:` | flash 裡有哪些映像檔、剩多少空間 | ★★★ |

### 刪設定就是在原指令前加 `no` ★★★

```cisco
SW-CORE-01(config-if)#description TEMP
SW-CORE-01(config-if)#do show run interface gi1/0/8
Building configuration...

Current configuration : 62 bytes
!
interface GigabitEthernet1/0/8
 description TEMP
end

SW-CORE-01(config-if)#no description
SW-CORE-01(config-if)#do show run interface gi1/0/8
Building configuration...

Current configuration : 41 bytes
!
interface GigabitEthernet1/0/8
end
```

★★★★ `default interface GigabitEthernet1/0/8` 可以**把整個介面打回原廠預設**，
比一行一行 `no` 快，是接手別人爛設定時最好用的一招。但它會**瞬間清掉所有設定
（含 VLAN 歸屬）**，對正在使用中的埠等同斷網，只能對確認閒置的埠用。

## 進階設定與調校

### `interface range`：一次改一整排埠 ★★★

```cisco
SW-CORE-01(config)#interface range GigabitEthernet1/0/1 - 12
SW-CORE-01(config-if-range)#description USER-PORT-1F
SW-CORE-01(config-if-range)#switchport mode access
SW-CORE-01(config-if-range)#switchport access vlan 30
SW-CORE-01(config-if-range)#spanning-tree portfast
%Warning: portfast should only be enabled on ports connected to a single
 host. Connecting hubs, concentrators, switches, bridges, etc... to this
 interface when portfast is enabled, can cause temporary bridging loops.
 Use with CAUTION
SW-CORE-01(config-if-range)#end
```

不連續的範圍用逗號分隔：

```cisco
SW-CORE-01(config)#interface range gi1/0/1 - 4, gi1/0/9, gi1/0/13 - 16
```

常用的範圍還可以取名字（`interface range macro`）：

```cisco
SW-CORE-01(config)#define interface-range USER-PORTS GigabitEthernet1/0/1 - 20
SW-CORE-01(config)#interface range macro USER-PORTS
SW-CORE-01(config-if-range)#
```

> [!danger] ★★★★★ `interface range` 是最容易一次弄斷整層樓的指令
> 打 `interface range gi1/0/1 - 24` 之後接 `shutdown`，**24 個埠同時斷**，
> 包含你自己那條上行。範圍打錯一個數字的代價是幾十個使用者同時報修。
> 保命規則：
> 1. ★★★★★ 執行前先 `show interfaces status` 確認範圍內**沒有上行埠**
> 2. ★★★★★ 遠端操作一律先 `reload in 5`
> 3. ★★★ 先對一個埠試，確認結果正確再套範圍

### 過濾器：從 4000 行設定裡挖出你要的十行 ★★★★

```cisco
SW-CORE-01#show running-config | include vlan
 switchport access vlan 30
 switchport trunk native vlan 999
 switchport trunk allowed vlan 10,20,30,999
```

```cisco
SW-CORE-01#show running-config | section interface GigabitEthernet1/0/24
interface GigabitEthernet1/0/24
 description UPLINK-TO-SW-DIST-01
 switchport trunk native vlan 999
 switchport trunk allowed vlan 10,20,30,999
 switchport mode trunk
 switchport nonegotiate
```

| 過濾器 | 作用 | 星級 |
| --- | --- | --- |
| `\| include <字串>` | 只顯示**含有**該字串的行 | ★★★★ |
| `\| exclude <字串>` | 排除含有該字串的行 | ★★★ |
| `\| section <字串>` | ★ 顯示**整個區塊**（含子行），查介面設定必用 | ★★★★ |
| `\| begin <字串>` | 從第一次出現的地方開始往下全印 | ★★★ |
| `\| count` | 只回傳行數 | ★★ |
| `\| redirect flash:out.txt` | ★★★ 輸出寫進檔案而不是螢幕 | ★★★ |
| `\| tee flash:out.txt` | 同時顯示與寫檔 | ★★ |

★★★ 過濾器吃**正規表示式**：`show run | include ^interface` 只列出頂層 interface 行。

實用組合：

```cisco
!-- 快速盤點哪些埠有描述、對應什麼
SW-CORE-01#show interfaces description | exclude admin down
Interface                      Status         Protocol Description
Gi1/0/1                        up             up       AP-3F-01
Gi1/0/24                       up             up       UPLINK-TO-SW-DIST-01
Vl99                           up             up       MGMT-SVI

!-- 只看有錯誤計數的埠
SW-CORE-01#show interfaces counters errors | exclude    0           0           0
Port        Align-Err     FCS-Err    Xmit-Err     Rcv-Err  UnderSize  OutDiscards
Gi1/0/5          14213        8891           0       23104          0           0
```

### 別名：把常打的長指令縮成三個字母 ★★

```cisco
SW-CORE-01(config)#alias exec sis show interfaces status
SW-CORE-01(config)#alias exec sib show ip interface brief
SW-CORE-01(config)#alias exec wr! write memory
SW-CORE-01(config)#end
SW-CORE-01#sis
Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   AP-3F-01           connected    20         a-full  a-100 10/100/1000BaseTX
```

★★ 別名會寫進設定檔，**接手的人看到 `sis` 會一頭霧水**。機關環境建議
只設一組全機關統一的別名，並寫進交接文件，不要各自發明。

### 讓 log 帶得上時間 ★★★★

```cisco
SW-CORE-01(config)#service timestamps debug datetime msec localtime show-timezone
SW-CORE-01(config)#service timestamps log datetime msec localtime show-timezone
SW-CORE-01(config)#clock timezone CST 8
SW-CORE-01(config)#ntp server 10.10.99.1
SW-CORE-01(config)#logging buffered 65536 informational
SW-CORE-01(config)#logging host 10.10.99.30
```

```cisco
SW-CORE-01#show clock
09:31:44.219 CST Tue Sep 2 2026
SW-CORE-01#show ntp status
Clock is synchronized, stratum 3, reference is 10.10.99.1
```

> [!warning] ★★★★★ 沒設 NTP 的設備，log 等於廢紙
> 預設沒有時間來源時 IOS 的 log 會長成 `*Mar  1 00:04:12.345:`（開機後的相對時間）。
> 出事時你**無法把交換器 log 跟防火牆、伺服器 log 對在一起**，事故調查直接卡死。
> 所有設備上線前必設 NTP，NTP 伺服器建置見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]]，
> log 集中收容見 [[100-01-02-guide-日誌-日誌集中與輪替]]。

### `logging synchronous`：不要讓 log 打斷你打字 ★★★

沒設的時候，log 訊息會插進你正在打的指令中間：

```cisco
SW-CORE-01(config)#interface gi1/0/
*Sep  2 09:33:01.442: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/5, changed state to down
```

你的 `interface gi1/0/` 還在那裡（其實還在 buffer 裡），但畫面已經亂了。設定：

```cisco
SW-CORE-01(config)#line console 0
SW-CORE-01(config-line)#logging synchronous
SW-CORE-01(config-line)#exec-timeout 10 0
SW-CORE-01(config-line)#line vty 0 15
SW-CORE-01(config-line)#logging synchronous
SW-CORE-01(config-line)#exec-timeout 5 0
```

★★★ 之後 log 出現時 IOS 會**自動把你打到一半的那行重印一次**在 log 下面。

### 遠端操作的保命符：`reload in` ★★★★★

這是本篇最重要的一段。

```cisco
SW-CORE-01#reload in 5
Reload scheduled in 5 minutes by netadm on vty0 (10.10.99.50)
Reload reason: Reload Command
Proceed with reload? [confirm]
SW-CORE-01#
```

原理就是本篇開頭那條：**沒 `write memory` 的變更活在 RAM 裡，重開就沒了。**

```text
reload in 5
   │
   ├─ 你改設定 ─▶ 立刻生效 ─▶ 你還連得上 ─▶ reload cancel ─▶ write memory ─▶ 收工
   │
   └─ 你改設定 ─▶ 立刻生效 ─▶ ★ 你斷線了 ─▶ 什麼都不用做
                                            ─▶ 5 分鐘後設備自己重開
                                            ─▶ 回到 startup-config ─▶ 你又連得上了
```

```cisco
SW-CORE-01#show reload
Reload scheduled in 4 minutes and 12 seconds by netadm on vty0 (10.10.99.50)
Reload reason: Reload Command
```

```cisco
SW-CORE-01#reload cancel
SW-CORE-01#
*Sep  2 09:40:18.771: %SYS-5-SCHEDULED_RELOAD_CANCELLED: Scheduled reload cancelled at
09:40:18 CST Tue Sep 2 2026
```

| 指令 | 作用 | 星級 |
| --- | --- | --- |
| `reload in 5` | 5 分鐘後重開 | ★★★★★ |
| `reload in 0 30` | 30 分鐘後重開（`in <小時> <分鐘>`） | ★★★ |
| `reload at 03:00` | 指定時間重開（★★ 需先設好 clock） | ★★★ |
| `reload cancel` | ★★★★★ 取消排程，**確認一切正常後第一件事** | ★★★★★ |
| `show reload` | 還剩多久 | ★★★★ |

> [!danger] ★★★★★ 三個一定要記住的細節
> 1. **`reload in` 之前絕對不能先 `write memory`**。存了檔就等於把壞設定寫進
>    startup-config，重開後照樣是壞的，保險完全失效。
> 2. **確認成功後第一件事是 `reload cancel`，第二件事才是 `write memory`。**
>    順序反了不會出事，但漏掉 `reload cancel` 會在五分鐘後把正在服務的設備重開。
> 3. **重開會斷線 1～3 分鐘**（交換器開機時間，堆疊更久）。這是保險的代價，
>    所以變更請排在維護時段，並事先告知使用者。
>
> ★★★ IOS 12.4(20)T／IOS-XE 之後另有 `configure terminal revert timer 5`
> ＋ `configure confirm` 的組合，行為更接近 JunOS 的 `commit confirmed`
> （逾時只回滾設定、不重開機）。詳見 [[040-01-14-svc-Cisco-設定備份與韌體升級]]。

## 完整實戰範例

**情境**：機關新購一台 Catalyst 2960-X，要從開箱狀態設定到「可遠端管理、設定已備份、
交接文件可交付」。全程只有 console 線，網路還沒接。

### 環境與前置

| 項目 | 值 |
| --- | --- |
| 設備 | Catalyst WS-C2960X-24TS-L，IOS 15.2(7)E3 |
| 主機名 | `SW-3F-01` |
| 管理 VLAN | 99（`MGMT`） |
| 管理 IP | 10.10.99.31/24 |
| 管理閘道 | 10.10.99.254 |
| NTP／Syslog | 10.10.99.30 |
| 上行埠 | Gi1/0/24 → SW-DIST-01 Gi1/0/8 |
| 備份主機 | 10.10.99.20（TFTP，見第 14 篇改用 SCP） |

### 步驟 1：連上 console 並確認乾淨狀態

```cisco
Switch>enable
Switch#show version | include Version|Model number|serial
Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E3, RELEASE SOFTWARE (fc2)
Model number                    : WS-C2960X-24TS-L
System serial number            : FOC2231YYYY
Switch#show running-config | include hostname|version
version 15.2
hostname Switch
```

**驗證**：`hostname Switch` 代表這是原廠狀態。若不是（例如是回收機），先確認可以清空，
再執行下一步。

```cisco
Switch#write erase
Erasing the nvram filesystem will remove all configuration files! Continue? [confirm]
[OK]
Erase of nvram: complete
Switch#delete flash:vlan.dat
Delete filename [vlan.dat]?
Delete flash:/vlan.dat? [confirm]
Switch#reload
System configuration has been modified. Save? [yes/no]: no
Proceed with reload? [confirm]
```

> [!danger] ★★★★★ `write erase` 與 `delete flash:vlan.dat` 都是不可逆的
> `vlan.dat` 是 VLAN 資料庫，**不在 `running-config` 裡**，所以只做 `write erase`
> 舊 VLAN 還會留著，這是回收機最常見的陷阱（也是 VTP 修訂版號沒歸零的元凶，
> 見 [[040-01-11-guide-Cisco-VLAN與Trunk設定]]）。
> **對生產中的設備打這兩行等於毀掉它。** 執行前務必確認你面前這台真的是要重灌的那台。

### 步驟 2：終端機基本設定與主機名

```cisco
Switch#terminal length 0
Switch#terminal width 512
Switch#configure terminal
Enter configuration commands, one per line.  End with CNTL/Z.
Switch(config)#hostname SW-3F-01
SW-3F-01(config)#no ip domain-lookup
SW-3F-01(config)#service timestamps log datetime msec localtime show-timezone
SW-3F-01(config)#service timestamps debug datetime msec localtime show-timezone
SW-3F-01(config)#clock timezone CST 8
SW-3F-01(config)#end
SW-3F-01#
```

★★★★ `no ip domain-lookup` 非常重要：沒關掉它的話，你打錯指令時 IOS 會把
錯字當主機名去做 DNS 查詢，**卡住 30 秒以上**：

```cisco
SW-3F-01#shwo run
Translating "shwo"...domain server (255.255.255.255)
% Unknown command or computer name, or unable to find computer address
```

> [!warning] ★★★ 指令名稱有版本差異
> IOS 15.x：`no ip domain-lookup`。
> 部分 IOS-XE 16.x／17.x：`no ip domain lookup`（**中間是空格不是連字號**）。
> 打了報 `% Invalid input` 就換另一種寫法，或用 `no ip domain ?` 查。

**驗證**：

```cisco
SW-3F-01#show clock
09:52:10.114 CST Tue Sep 2 2026
```

### 步驟 3：先設定時間與 log，再做其他事

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#ntp server 10.10.99.30
SW-3F-01(config)#logging buffered 65536 informational
SW-3F-01(config)#logging host 10.10.99.30
SW-3F-01(config)#logging trap informational
SW-3F-01(config)#end
```

**驗證**（NTP 同步需要幾分鐘，先往下做，最後再回頭確認）：

```cisco
SW-3F-01#show ntp associations
  address         ref clock       st   when   poll reach  delay  offset   disp
 ~10.10.99.30     10.10.99.1       2      9     64     1  0.892   0.104  7.812
 * sys.peer, # selected, + candidate, - outlyer, x falseticker, ~ configured
```

★★★ 一開始 `reach` 是 `1`，同步完成後 address 前會出現 `*`。

### 步驟 4：建立管理 VLAN 與 SVI

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#vlan 99
SW-3F-01(config-vlan)#name MGMT
SW-3F-01(config-vlan)#exit
SW-3F-01(config)#interface Vlan99
SW-3F-01(config-if)#description MGMT-SVI
SW-3F-01(config-if)#ip address 10.10.99.31 255.255.255.0
SW-3F-01(config-if)#no shutdown
SW-3F-01(config-if)#exit
SW-3F-01(config)#ip default-gateway 10.10.99.254
SW-3F-01(config)#interface Vlan1
SW-3F-01(config-if)#shutdown
SW-3F-01(config-if)#end
```

★★★★ 最後兩行是刻意的：**預設 VLAN 1 的 SVI 一律關掉**，管理流量走專屬 VLAN。
細節與 SSH 啟用見 [[040-01-12-guide-Cisco-管理IP與遠端存取]]。

**驗證**（此時 Gi1/0/24 還沒接線，SVI 會是 down，這是正常的）：

```cisco
SW-3F-01#show ip interface brief | include Vlan
Vlan1                  unassigned      YES manual administratively down down
Vlan99                 10.10.99.31     YES manual down                  down
```

### 步驟 5：設定上行埠並接線

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface GigabitEthernet1/0/24
SW-3F-01(config-if)#description UPLINK-TO-SW-DIST-01-Gi1/0/8
SW-3F-01(config-if)#switchport trunk native vlan 999
SW-3F-01(config-if)#switchport trunk allowed vlan 30,99,999
SW-3F-01(config-if)#switchport mode trunk
SW-3F-01(config-if)#switchport nonegotiate
SW-3F-01(config-if)#end
```

接上網路線，等 15～30 秒（STP 收斂）後驗證：

```cisco
SW-3F-01#show interfaces status | include Gi1/0/24
Gi1/0/24  UPLINK-TO-SW-DIST- connected    trunk      a-full a-1000 10/100/1000BaseTX

SW-3F-01#show ip interface brief | include Vlan99
Vlan99                 10.10.99.31     YES manual up                    up

SW-3F-01#show cdp neighbors GigabitEthernet1/0/24 detail | include Device ID|IP address|Version
Device ID: SW-DIST-01
  IP address: 10.10.99.1
Version :
Cisco IOS Software, IOS-XE Software, Catalyst L3 Switch Software
```

★★★★ `show cdp neighbors detail` 對上了預期的對端設備，**才算接線正確**。
接錯配線架是機關現場最常見的低級錯誤。

```cisco
SW-3F-01#ping 10.10.99.254
Type escape sequence to abort.
Sending 5, 100-byte ICMP Echos to 10.10.99.254, timeout is 2 seconds:
!!!!!
Success rate is 100 percent (5/5), round-trip min/avg/max = 1/1/4 ms
```

★★★ `!` 是成功，`.` 是逾時，`U` 是 unreachable，`?` 是未知封包。
`Success rate is 100 percent` 才算過關。

### 步驟 6：先別存檔 —— 用 `reload in` 做完剩下的變更

**從這一步起你改用 SSH 從 10.10.99.50 連線**（SSH 啟用步驟見下一篇），
所以要開始上保險：

```cisco
SW-3F-01#reload in 10
Reload scheduled in 10 minutes by netadm on vty0 (10.10.99.50)
Reload reason: Reload Command
Proceed with reload? [confirm]
SW-3F-01#show reload
Reload scheduled in 9 minutes and 51 seconds by netadm on vty0 (10.10.99.50)
```

接著批次設定使用者埠：

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface range GigabitEthernet1/0/1 - 20
SW-3F-01(config-if-range)#description USER-PORT-3F
SW-3F-01(config-if-range)#switchport mode access
SW-3F-01(config-if-range)#switchport access vlan 30
SW-3F-01(config-if-range)#spanning-tree portfast
SW-3F-01(config-if-range)#spanning-tree bpduguard enable
SW-3F-01(config-if-range)#no shutdown
SW-3F-01(config-if-range)#exit
SW-3F-01(config)#interface range GigabitEthernet1/0/21 - 23
SW-3F-01(config-if-range)#description UNUSED
SW-3F-01(config-if-range)#switchport mode access
SW-3F-01(config-if-range)#switchport access vlan 999
SW-3F-01(config-if-range)#shutdown
SW-3F-01(config-if-range)#end
```

**驗證**：

```cisco
SW-3F-01#show interfaces status
Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   USER-PORT-3F       notconnect   30           auto   auto 10/100/1000BaseTX
Gi1/0/2   USER-PORT-3F       connected    30         a-full a-1000 10/100/1000BaseTX
...
Gi1/0/21  UNUSED             disabled     999          auto   auto 10/100/1000BaseTX
Gi1/0/22  UNUSED             disabled     999          auto   auto 10/100/1000BaseTX
Gi1/0/23  UNUSED             disabled     999          auto   auto 10/100/1000BaseTX
Gi1/0/24  UPLINK-TO-SW-DIST- connected    trunk      a-full a-1000 10/100/1000BaseTX
```

★★★★ 你的 SSH session **還活著**，代表設定沒有把自己鎖在外面。

### 步驟 7：解除保險並存檔

```cisco
SW-3F-01#reload cancel
SW-3F-01#
*Sep  2 10:14:33.882: %SYS-5-SCHEDULED_RELOAD_CANCELLED: Scheduled reload cancelled at
10:14:33 CST Tue Sep 2 2026
SW-3F-01#show reload
No reload is scheduled.
SW-3F-01#write memory
Building configuration...
[OK]
```

**驗證兩份設定已經一致**：

```cisco
SW-3F-01#show archive config differences system:running-config nvram:startup-config
!Contextual Config Diffs:
!No changes were found
```

### 步驟 8：備份與交接文件

```cisco
SW-3F-01#copy running-config tftp://10.10.99.20/SW-3F-01-20260902.cfg
Address or name of remote host [10.10.99.20]?
Destination filename [SW-3F-01-20260902.cfg]?
!!
5127 bytes copied in 1.284 secs (3993 bytes/sec)
```

★★★ TFTP 只適合封閉的管理網段，正式做法請改用 SCP 並排程自動備份，
見 [[040-01-14-svc-Cisco-設定備份與韌體升級]]。

最後把這三份輸出貼進交接文件：

```cisco
SW-3F-01#show version | include Model number|System serial|Version 15
SW-3F-01#show interfaces description
SW-3F-01#show running-config
```

### 驗收檢查表 ★★★★

| # | 檢查項 | 通過條件 |
| --- | --- | --- |
| 1 | `show version` | 型號、序號、版本已記錄 |
| 2 | `show clock` | 時間正確，時區為 CST |
| 3 | `show ntp associations` | 有 `*` 標記，已同步 |
| 4 | `show ip interface brief \| include Vlan` | Vlan99 `up/up`、Vlan1 `administratively down` |
| 5 | `ping <閘道>` | `Success rate is 100 percent` |
| 6 | `show cdp neighbors detail` | 對端是預期的設備與埠 |
| 7 | `show interfaces status` | 沒有非預期的 `err-disabled` |
| 8 | `show reload` | `No reload is scheduled.` |
| 9 | `show archive config differences ...` | `No changes were found` |
| 10 | 備份檔 | 備份主機上有今天日期的 `.cfg`，且可開啟 |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| 重開機後所有設定都不見了 | ★★★★★ 忘記 `write memory`，設定只在 running-config | 沒有救援方式，只能重打。養成「離開設定模式就 `end` 然後 `wr`」的肌肉記憶；重要變更前先 `copy run tftp:` 留底 |
| `% Invalid input detected at '^' marker.` | ★★★★ 模式不對（在 `>` 或 `(config)#` 打了 `#` 才有的指令），或該版本沒有這個關鍵字 | 看 `^` 指到哪個字；用 `?` 確認這一層可用的關鍵字；確認 `show version` 的版本是否支援 |
| `% Ambiguous command: "s"` | 縮寫太短，有多個指令符合 | 多打幾個字母，或用 `s?` 列出候選 |
| `% Incomplete command.` | 指令還沒打完（少了必要參數） | 在該指令後加空格與 `?` 看還要接什麼 |
| 打錯字後卡住 30 秒，出現 `Translating "xxx"...domain server (255.255.255.255)` | ★★★★ 沒關 DNS 查詢 | `configure terminal` → `no ip domain-lookup`（IOS-XE 部分版本為 `no ip domain lookup`） |
| `show run` 一直卡在 `--More--` | 沒設 `terminal length 0` | `terminal length 0`；注意這是 per-session，斷線就要重設 |
| SSH 連進去看不到任何 log 訊息 | ★★★ vty session 預設不顯示 console log | `terminal monitor`（用完 `terminal no monitor`） |
| log 時間都是 `*Mar 1 00:04:12` | ★★★★ 沒有時間來源，顯示的是開機後相對時間 | 設 `clock timezone`、`ntp server`、`service timestamps log datetime` |
| 介面 `administratively down` | 有人下過 `shutdown` | 進該介面 `no shutdown`；查 `show archive log config all` 看是誰改的 |
| 介面 `err-disabled` | ★★★★ 被 port-security／BPDU guard／UDLD 關掉 | `show interfaces status err-disabled` 看原因；排除肇因後 `shutdown` → `no shutdown`。詳見 [[040-01-13-guide-Cisco-埠設定與安全]] |
| 遠端改設定後 SSH 斷線再也連不上 | ★★★★★ 改壞了 ACL／VLAN／trunk 且已 `write memory` | 若事前有 `reload in` 則等它自己重開；否則只能到現場接 console。**這就是 `reload in` 存在的理由** |
| 跳電後交換器變成空白設定 | ★★★★★ `config-register` 被留在 `0x2142`（密碼救援後沒改回來） | `show version` 看最後一行；`configure terminal` → `config-register 0x2102`（交換器 `0xF`）→ `write memory` |
| `interface range` 打完發現改錯一整排埠 | ★★★★ 範圍寫錯 | 若尚未 `write memory`，`reload` 即可全數復原；已存檔則從備份 `configure replace` 還原 |
| `default interface` 之後該埠完全不通 | ★★★★ 打回原廠＝回到 VLAN 1、無描述、可能自動協商為 dynamic | 重新套用該埠的標準設定範本 |
| 貼一大段設定進 console，中間有幾行沒吃到 | ★★★ 終端機送字太快，IOS 來不及處理 | 終端機軟體設定字元／行延遲（例如 5ms／100ms）；或改用 `copy tftp: running-config` 匯入 |
| `copy running-config startup-config` 回 `%Error opening nvram:` | ★★★★ NVRAM 故障或檔案系統損毀 | `show file systems` 確認 nvram 存在；報修。**先把設定 `copy run tftp:` 存出來** |
| `show cdp neighbors` 什麼都沒有 | 對端關了 CDP、對端不是 Cisco、或本機 `no cdp run` | `show cdp` 確認全域狀態；Juniper 對端要改看 LLDP：`show lldp neighbors` |

## 安全性注意事項

> [!warning] ★★★★ 預設狀態的 Cisco 交換器對機關來說是不合格的
> 出廠設定沒有 enable 密碼、Telnet 可用、HTTP 管理介面開著、所有埠都在 VLAN 1、
> CDP 對所有埠廣播。**接上網路的那一刻就是資安事件。**

| 項目 | 風險 | 做法 | 星級 |
| --- | --- | --- | --- |
| 沒有 `enable secret` | 任何連上 console 的人都是管理員 | `enable secret <強密碼>`，**不要用 `enable password`** | ★★★★★ |
| `enable password` ＋ `service password-encryption` | ★★★★★ 那是 Type 7 編碼，**線上工具三秒還原明文** | 一律改用 `enable secret`（雜湊），細節見下一篇 | ★★★★★ |
| Telnet 開著 | 帳密明文在網路上跑 | `line vty 0 15` → `transport input ssh` | ★★★★★ |
| HTTP 管理介面 | 老舊 Web UI 是 CVE 重災區 | `no ip http server` ＋ `no ip http secure-server` | ★★★★ |
| CDP 對使用者埠廣播 | ★★★★ 洩漏型號、IOS 版本、管理 IP，是攻擊者的偵察起點 | 上行與設備間保留 CDP；使用者埠 `no cdp enable` | ★★★★ |
| 沒有登入警告標語 | 部分法遵要求需有明示 | `banner motd` 設定授權使用聲明 | ★★★ |
| `exec-timeout 0 0` | ★★★★ session 永不逾時，離開座位＝把管理權留在桌上 | `exec-timeout 5 0`（console 可放寬到 10 分鐘） | ★★★★ |
| `debug` 忘記關 | CPU 飆高造成轉發異常，等同自我 DoS | 用完立刻 `undebug all`；正式環境優先看 `show logging` | ★★★★ |
| 設定檔用 TFTP 傳輸 | 明文，且**設定檔裡有密碼雜湊與 SNMP community** | 改用 SCP；備份存放區要限制存取 | ★★★★ |
| 交接文件貼完整 `show run` | 同上，等於把雜湊值散布出去 | 交付前遮蔽 `secret`／`key`／`community` 行 | ★★★★ |

★★★ 完整的安全基線設定請照 [[040-01-12-guide-Cisco-管理IP與遠端存取]] 與
[[090-02-06-guide-防護-遠端存取安全]] 逐項套用。

## 速查表

| 指令 / 設定項 | 說明 | 範例 |
| --- | --- | --- |
| `enable` | 進入 privileged EXEC ★★★★ | `Switch>enable` |
| `disable` | 退回 user EXEC | `Switch#disable` |
| `configure terminal`（`conf t`） | 進入 global config ★★★★ | `SW#conf t` |
| `exit` | 退一層 | `SW(config-if)#exit` |
| `end`（`Ctrl+Z`） | ★★★ 直接回 privileged EXEC | `SW(config-if)#end` |
| `do <EXEC 指令>` | ★★★★ 在設定模式下執行 show／ping | `SW(config)#do show ip int brief` |
| `write memory`（`wr`） | ★★★★★ running → startup | `SW#wr` |
| `copy running-config startup-config` | 同上，完整寫法 ★★★★★ | `SW#copy run start` |
| `show running-config`（`sh run`） | 目前生效設定 ★★★★★ | `SW#sh run \| section Gi1/0/24` |
| `show startup-config` | 重開後會變成的設定 ★★★★ | `SW#sh start` |
| `show version` | 型號／版本／序號／config-register ★★★★ | `SW#sh ver \| in Model` |
| `show ip interface brief` | 介面 IP 與 up/down ★★★★ | `SW#sh ip int br` |
| `show interfaces status` | ★★★★ 埠的 VLAN／速率／雙工／狀態 | `SW#sh int status` |
| `show interfaces description` | 埠描述一覽 ★★★ | `SW#sh int desc` |
| `show interfaces counters errors` | 實體層錯誤統計 ★★★★ | `SW#sh int counters errors` |
| `show vlan brief` | VLAN 與埠歸屬 ★★★★ | `SW#sh vlan br` |
| `show mac address-table address <mac>` | ★★★★ 某台機器插在哪個埠 | `SW#sh mac add addr 0050.56a1.2b3c` |
| `show cdp neighbors detail` | ★★★★ 對端設備、IP、版本 | `SW#sh cdp nei det` |
| `show lldp neighbors` | 非 Cisco 對端（如 Juniper）用這個 ★★★ | `SW#sh lldp nei` |
| `show logging` | 設備上的 log 緩衝區 ★★★★ | `SW#sh log \| in ERR` |
| `show users` | 誰正連在這台設備 ★★★ | `SW#sh users` |
| `show clock` / `show ntp associations` | 時間與同步狀態 ★★★ | `SW#sh ntp asso` |
| `show flash:` / `dir flash:` | flash 內容與剩餘空間 ★★★ | `SW#dir flash:` |
| `show reload` | 排程重開還剩多久 ★★★★ | `SW#sh reload` |
| `reload in 5` | ★★★★★ 遠端變更保命符 | `SW#reload in 5` |
| `reload cancel` | ★★★★★ 確認成功後立刻執行 | `SW#reload cancel` |
| `terminal length 0` | ★★★★ 取消分頁（per-session） | `SW#term len 0` |
| `terminal monitor` | ★★★★ 在 SSH session 顯示 log | `SW#term mon` |
| `interface range <a> - <b>` | ★★★ 批次設定介面 | `SW(config)#int range gi1/0/1 - 12` |
| `default interface <名稱>` | ★★★★ 把介面打回原廠（會斷網） | `SW(config)#default int gi1/0/8` |
| `no <原指令>` | 刪除該行設定 ★★★ | `SW(config-if)#no description` |
| `\| include` / `\| exclude` / `\| section` | ★★★★ 輸出過濾 | `SW#sh run \| sec vty` |
| `no ip domain-lookup` | ★★★★ 打錯字不會卡 30 秒 | `SW(config)#no ip domain-lookup` |
| `logging synchronous` | ★★★ log 不打斷你打字 | `SW(config-line)#logging synchronous` |
| `Ctrl+Shift+6` | ★★★ 中斷正在跑的指令（break） | ping／traceroute 中途取消 |
| `Ctrl+A` / `Ctrl+E` | 游標移到行首／行尾 ★★ | 編輯長指令用 |
| `show history` | 這條 session 打過的指令 ★★ | `SW#sh history` |

## 練習題

> [!question]- 練習 1：模式與提示符號
> 從剛登入的 `Switch>` 開始，用最少的指令走到「設定 Gi1/0/5 的描述」，
> 再用一個指令直接回到 `#`。把每一步的提示符號寫下來。
>
> **參考解答**
>
> ```cisco
> Switch>enable
> Switch#configure terminal
> Switch(config)#interface GigabitEthernet1/0/5
> Switch(config-if)#description TEST-PORT
> Switch(config-if)#end
> Switch#
> ```
>
> 四步：`enable` → `configure terminal` → `interface ...` → 設定；
> 回頂層用 `end`（或 `Ctrl+Z`），★★★ 不是 `exit`（`exit` 要按三次）。

> [!question]- 練習 2：驗證「有沒有忘記存檔」
> 在測試機上把 Gi1/0/8 的描述改成 `PRACTICE`，**不要存檔**，
> 然後用兩種方法證明 running-config 與 startup-config 不一致。
>
> **參考解答**
>
> 方法一（★★★★ 最直接）：
>
> ```cisco
> SW#show archive config differences system:running-config nvram:startup-config
> !Contextual Config Diffs:
> +interface GigabitEthernet1/0/8
> + description PRACTICE
> ```
>
> 方法二（版本太舊沒有上面那個指令時）：
>
> ```cisco
> SW#show running-config | section GigabitEthernet1/0/8
> interface GigabitEthernet1/0/8
>  description PRACTICE
> SW#show startup-config | section GigabitEthernet1/0/8
> interface GigabitEthernet1/0/8
> ```
>
> 兩邊不一樣＝沒存檔。接著 `write memory` 再跑一次，應該變成
> `!No changes were found`。

> [!question]- 練習 3：`reload in` 的完整演練
> 在測試機上模擬一次「遠端改設定改壞」：SSH 連入後先 `reload in 3`，
> 然後故意把你自己連線用的 VLAN 從上行 trunk 的 allowed list 移除，
> 觀察會發生什麼，以及三分鐘後的結果。
>
> **參考解答**
>
> ```cisco
> SW#reload in 3
> Reload scheduled in 3 minutes by netadm on vty0 (10.10.99.50)
> Proceed with reload? [confirm]
> SW#configure terminal
> SW(config)#interface gi1/0/24
> SW(config-if)#switchport trunk allowed vlan 30
>                                   ← ★ 這一行執行後你的 SSH 立刻斷線
> ```
>
> 你會看到終端機停止回應。**什麼都不要做**，等三分鐘。設備自動重開後
> 回到 startup-config（allowed vlan 仍含 99），SSH 恢復。
>
> ★★★★★ 這題要體會的是：如果你在 `reload in 3` **之前**先打了 `write memory`，
> 這個保險就完全失效 —— 重開後壞設定還在，你只能去現場。
>
> ★★★★ 另外注意 `switchport trunk allowed vlan 30` 是**覆蓋**不是新增，
> 要新增得用 `switchport trunk allowed vlan add 30`，見 [[040-01-11-guide-Cisco-VLAN與Trunk設定]]。

> [!question]- 練習 4：用過濾器做盤點
> 用一行指令列出「所有目前是 connected 狀態且不在 VLAN 1 的埠」，
> 再用一行列出「所有帶有 description 的介面」。
>
> **參考解答**
>
> ```cisco
> SW#show interfaces status | include connected
> Gi1/0/1   AP-3F-01           connected    20         a-full  a-100 10/100/1000BaseTX
> Gi1/0/2   PC-ACCT-014        connected    30         a-full a-1000 10/100/1000BaseTX
> Gi1/0/24  UPLINK-TO-DIST-01  connected    trunk      a-full a-1000 10/100/1000BaseTX
> ```
>
> ★★★ `include connected` 也會抓到 `notconnect`（因為含有 `connect`），
> 要精確的話用 `include  connected `（前後留空格）或
> `show interfaces status | exclude notconnect|disabled|err-disabled`。
>
> ```cisco
> SW#show interfaces description | exclude ^Interface|admin down
> ```
>
> 或直接 `show running-config | include ^interface| description`。

> [!question]- 練習 5：交接文件的最小輸出集
> 假設你明天離職，要留給接手的人一份「這台交換器現在長什麼樣」的文件。
> 列出你會執行哪五個指令，以及每個指令回答了什麼問題。
>
> **參考解答**
>
> | 指令 | 回答 |
> | --- | --- |
> | `show version` | 型號、序號、IOS 版本、config-register（★★★★ 保固與升級規劃的依據） |
> | `show running-config` | 完整設定（★★★★ 交付前要遮掉 `secret`／`community` 行） |
> | `show interfaces description` | 每個埠接什麼（★★★★ 沒有這個，接手的人等於重新盤點） |
> | `show vlan brief` | VLAN 規劃與埠歸屬 |
> | `show cdp neighbors detail`（或 `show lldp neighbors`） | 這台在拓樸中的位置、上下游是誰 |
>
> ★★★ 再加一個 `show inventory` 記錄 SFP 型號與序號會更完整。
> 文件化的標準格式見 [[040-01-18-guide-網路設備-網路設備盤點與文件化]]。

## 小測驗

Q1. 你在 `SW(config-if)#` 下打了 `switchport access vlan 30`，然後直接把 console 線拔掉走人。
三天後跳電，設備重開。這個 VLAN 設定還在嗎？為什麼？

Q2. （選擇）以下哪一個指令**不會**把 running-config 寫進 NVRAM？
(A) `write memory` (B) `copy run start` (C) `copy running-config tftp:` (D) `wr`

Q3. （是非）`exit` 和 `end` 在 `Switch(config-if)#` 下的效果是一樣的。

Q4. 這行指令會發生什麼事？
`SW-CORE-01#reload in 5`
接著你發現設定改對了，還連得上。你接下來要依序做哪兩件事？順序反了會怎樣？

Q5. `show interfaces status` 顯示某埠是 `err-disabled`，跟 `disabled` 差在哪裡？
各自要怎麼處理？

Q6. （簡答）`GigabitEthernet1/0/24` 這個名稱裡的三個數字分別代表什麼？

Q7. 你在 `SW(config)#` 下打 `show ip interface brief`，得到
`% Invalid input detected at '^' marker.`。有兩種方式可以查到你要的資訊，
分別是什麼？哪一種比較有效率？

Q8. （是非）`enable password` 加上 `service password-encryption` 之後，
密碼在設定檔裡就是安全的了。

Q9. 同事說「我把 `config-register` 設成 `0x2142` 做完密碼救援了」，
你聽到之後應該立刻追問什麼？不追問的後果是什麼？

Q10. `switchport trunk allowed vlan 30` 和
`switchport trunk allowed vlan add 30` 差在哪裡？
在遠端操作時哪一個比較危險？

> [!question]- 測驗答案
> **Q1.** ★★★★★ **不在了。** 打完指令只寫進 running-config（RAM），
> 沒有 `write memory` 就不會進 startup-config（NVRAM），掉電即消失。
> 見「觀念說明 → IOS 最違反直覺的一件事」。
>
> **Q2.** ★★★★ **(C)**。`copy running-config tftp:` 是把設定**複製到外部 TFTP 伺服器**，
> 是備份動作，跟存進 NVRAM 無關。(A)(B)(D) 三者完全等價。
> 見「觀念說明 → 兩份設定檔」。
>
> **Q3.** ★★★ **否。** `exit` 只退一層（回到 `SW(config)#`），
> `end` 不管在第幾層都直接回 `SW#`。實務上一律用 `end`。
> 見「觀念說明 → `exit` 與 `end` 的差別」。
>
> **Q4.** ★★★★★ 排程五分鐘後重新開機，重開後會載入 **startup-config**，
> 所以任何未存檔的變更都會被丟掉 —— 這正是保險機制。
> 接下來依序：**① `reload cancel` ② `write memory`**。
> 順序反了（先 `write` 再 `cancel`）本身不會出事，但**如果忘了 `reload cancel`**，
> 五分鐘後正在服務的設備會突然重開，造成計畫外中斷。
> 更嚴重的錯誤是在 `reload in` **之前**就 `write memory`，那樣保險完全失效。
> 見「進階設定與調校 → 遠端操作的保命符」。
>
> **Q5.** ★★★★ `disabled` ＝ 有人下了 `shutdown`（管理性關閉），`no shutdown` 即可恢復。
> `err-disabled` ＝ **被保護機制自動關掉**（port-security 違規、BPDU guard、
> duplex mismatch、UDLD 等），要先用 `show interfaces status err-disabled`
> 查出原因並排除肇因，再 `shutdown` → `no shutdown` 恢復；
> 光 `no shutdown` 而不排除肇因，它會立刻再次進 err-disabled。
> 見「基礎設定 → 一定要背起來的 show 指令」與 [[040-01-13-guide-Cisco-埠設定與安全]]。
>
> **Q6.** ★★★ 依序是**堆疊成員編號（stack member）／模組或子插槽／埠號**。
> 單機時第一碼固定是 1，固定埠的第二碼固定是 0。
> 舊機型（如 ISR 路由器）只有兩段，如 `GigabitEthernet0/1`。
> 見「觀念說明 → 介面命名怎麼讀」。
>
> **Q7.** ★★★★ 方式一：`end` 退回 `SW#` 再打 `show ip interface brief`，
> 查完再 `configure terminal` 進去。
> 方式二（★ 較有效率）：直接在設定模式下打 `do show ip interface brief`，
> 不用進出模式，接著就能繼續改設定。
> 見「基礎設定 → `do`」。
>
> **Q8.** ★★★★★ **否。** `service password-encryption` 產生的是 **Type 7 編碼**，
> 那是可逆的編碼不是雜湊，網路上的還原工具三秒還原明文。
> 它只能防「肩窺」，不能防拿到設定檔的人。
> 正確做法是用 `enable secret`（雜湊）與 `username ... secret`。
> 見「安全性注意事項」與 [[040-01-12-guide-Cisco-管理IP與遠端存取]]。
>
> **Q9.** ★★★★★ 追問「**你救援完有沒有把 config-register 改回 `0x2102`
> （交換器是 `0xF`）並 `write memory`？**」
> `0x2142` 的意思是「開機時忽略 startup-config」，留著不改的後果是
> **下次跳電或重開後這台設備變成空白設定，整段網路中斷**，
> 而且從 `show running-config` 完全看不出異常，只有 `show version` 最後一行看得到。
> 見「環境準備與安裝 → 步驟 0」。
>
> **Q10.** ★★★★★ `switchport trunk allowed vlan 30` 是**覆蓋整份清單**，
> 執行後這條 trunk 只剩 VLAN 30 能通；
> `switchport trunk allowed vlan add 30` 是**在現有清單上新增**。
> 遠端操作時**前者極度危險** —— 如果你的管理 VLAN 不是 30，
> 敲下 Enter 的瞬間你就斷線了。這也是為什麼遠端改 trunk 一定要先 `reload in`。
> 見 [[040-01-11-guide-Cisco-VLAN與Trunk設定]]。

## 延伸閱讀

- [[040-01-11-guide-Cisco-VLAN與Trunk設定]] —— 接下來就是把埠分進 VLAN
- [[040-01-12-guide-Cisco-管理IP與遠端存取]] —— SVI、SSH、ACL，讓這台設備能安全遠端管理
- [[040-01-13-guide-Cisco-埠設定與安全]] —— port-security、portfast、未用埠處理
- [[040-01-14-svc-Cisco-設定備份與韌體升級]] —— `archive`、`configure replace`、IOS 升級與回退
- [[040-01-05-cmd-Juniper-JunOS-基礎操作]] —— 主線平台的對應章節
- [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]] —— 兩邊指令一頁式對照
- [[040-01-04-guide-網路設備-交換器初次設定與連線方式]] —— console 線與終端機參數
- [[040-01-17-guide-網路設備-交換器故障排除]] —— 系統化的排錯流程
- [[040-01-18-guide-網路設備-網路設備盤點與文件化]] —— 交接文件該長什麼樣
