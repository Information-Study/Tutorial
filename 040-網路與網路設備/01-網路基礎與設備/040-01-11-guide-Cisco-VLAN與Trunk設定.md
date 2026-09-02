---
title: "Cisco VLAN 與 Trunk 設定"
desc: "建立 VLAN、access 埠、trunk 與 allowed vlan、native vlan，以及 DTP 與 VTP 兩個現場最常出事的功能"
aliases: [switchport mode trunk, switchport nonegotiate, VTP, DTP, native vlan, trunk allowed vlan]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-10-cmd-Cisco-IOS-基礎操作]]", "[[040-01-03-guide-網路設備-VLAN概念與規劃]]"]
updated: 2026-09-02
---

# Cisco VLAN 與 Trunk 設定

> [!note] 本手冊以 Juniper JunOS 為主線
> 網路設備章節**以 Juniper JunOS 為主線**，對應篇是 [[040-01-06-guide-Juniper-VLAN與Trunk設定]]。
> Cisco 這一篇是**輔助線**，給接手既有 Catalyst 設備的維運人員用。
> VLAN 的規劃原則（要切幾個、怎麼編號、誰跟誰要隔離）不在這裡，
> 在 [[040-01-03-guide-網路設備-VLAN概念與規劃]]；這篇只講**在 Cisco 上怎麼把它做出來**。

> [!abstract] 這篇你會學到
> - ★★★★★ **VTP 是機關現場毀滅性最強的一個功能**：插上一台修訂版號較高的舊交換器，
>   全網 VLAN 在數秒內被清空。為什麼會這樣、怎麼防、接手時第一件事該檢查什麼
> - ★★★★★ `switchport trunk allowed vlan 30` 是**覆蓋**不是新增 ——
>   遠端打下去就斷線的第一名指令，正確寫法是 `add` / `remove`
> - ★★★★ **DTP 自動協商**為什麼要關掉：攻擊者一台筆電就能把 access 埠談成 trunk，
>   拿到全部 VLAN 的流量。`switchport nonegotiate` 一行解決
> - ★★★★ native VLAN 是什麼、為什麼不能用 VLAN 1、雙標籤 VLAN hopping 怎麼防
> - ★★★★ `switchport trunk encapsulation dot1q` 在哪些機型是必須的、
>   在哪些機型打了會報錯
> - ★★★ `vlan.dat` 這個**不在 running-config 裡**的檔案，
>   以及它如何讓「我明明 `write erase` 過了」變成一句空話
> - ★★★ `show vlan brief`、`show interfaces trunk`、`show interfaces switchport` 三個驗證指令怎麼讀
> - 一份可以照抄的接入層交換器 VLAN 標準設定範本

> [!warning] 未實機驗證
> ★★★★★ 本專案**沒有可供驗證的實體 Cisco 設備**。本篇依 Cisco IOS 15.2(7)E
> （Catalyst 2960-X／2960-L）與 IOS-XE 17.x（Catalyst 9200／9300）的官方命令參考撰寫，
> 輸出為依實際格式重建的**示意輸出**。
> ★★★★ **不同機型的 trunk 相關指令差異特別大**（見「觀念說明 → encapsulation 的機型差異」），
> 導入前請務必用 `show version` 確認機型與版本，並在測試環境或 Cisco CML／Packet Tracer
> 先跑過。任何會動到 trunk 的變更，遠端操作一律先 `reload in 5`。

## 前置知識

- [[040-01-10-cmd-Cisco-IOS-基礎操作]] —— 模式階層、`do`、`interface range`、
  ★★★★★ **`reload in 5`**，這篇每一段都會用到
- [[040-01-03-guide-網路設備-VLAN概念與規劃]] —— VLAN 該怎麼切、編號規劃原則
- [[010-02-16-guide-網概-VLAN與網路分段]] —— 802.1Q 標籤、廣播域的基本觀念
- [[010-02-05-guide-網概-MAC位址與交換器]] —— CAM table 與 VLAN 的關係
- [[040-01-06-guide-Juniper-VLAN與Trunk設定]] —— 主線平台的做法

## 觀念說明

### 一條線只走一個 VLAN，還是走全部 —— access 與 trunk

```text
                 ┌──────────── SW-DIST-01 ────────────┐
                 │                                     │
                 │   Gi1/0/8  ◀── trunk ──▶            │
                 └──────┬──────────────────────────────┘
                        │  一條線，封包帶 802.1Q 標籤
                        │  VLAN 30/99/999 都在這條線上跑
                        ▼
                 ┌───── Gi1/0/24 ──── SW-3F-01 ────────┐
                 │                                      │
                 │  Gi1/0/1  access vlan 30 ──▶ PC      │  ← 一條線只走 VLAN 30
                 │  Gi1/0/2  access vlan 30 ──▶ PC      │     封包不帶標籤
                 │  Gi1/0/5  access vlan 20 ──▶ AP      │
                 │  Gi1/0/21 access vlan 999 (shutdown) │
                 └──────────────────────────────────────┘
```

| | access 埠 | trunk 埠 |
| --- | --- | --- |
| 接什麼 | 電腦、印表機、IP 電話、AP（單一 VLAN） | ★ 交換器對交換器、交換器對路由器／防火牆、虛擬化主機 |
| 封包帶標籤嗎 | 不帶（純乙太網路訊框） | ★ 帶 802.1Q VLAN tag（native VLAN 除外） |
| 能走幾個 VLAN | 1 個（＋1 個 voice VLAN） | 多個，由 allowed list 決定 |
| 設定關鍵字 | `switchport mode access` | `switchport mode trunk` |
| 打錯的後果 | 那台機器上不了網 | ★★★★ **整段網路斷、或 VLAN 隔離失效** |

### 三個最容易搞混的名詞 ★★★★

| 名詞 | 是什麼 | 常見誤解 |
| --- | --- | --- |
| **allowed vlan** | ★★★★ 這條 trunk **允許通過**哪些 VLAN | 誤以為不設就是全部都不通（其實預設是 **1-4094 全通**） |
| **native vlan** | ★★★★ 這條 trunk 上**不帶標籤**傳送的那個 VLAN | 誤以為它是「預設 VLAN」；兩端不一致會造成 VLAN 互串 |
| **DTP** | ★★★★ 自動協商「這條線要當 access 還是 trunk」的協定 | 誤以為 `switchport mode trunk` 就已經關掉協商了（★ 沒有） |

### VLAN 的資料存在兩個地方 ★★★★

這是 Cisco 最反直覺的設計之一：

```text
vlan 10
 name MGMT              ← ★★★★ 這段存在 flash:vlan.dat（VLAN 資料庫）
                           在 VTP server / client 模式下【不會】出現在 running-config

interface Gi1/0/2
 switchport access vlan 10   ← 這一行才在 running-config
```

| 資料 | 存在哪 | `write erase` 會清掉嗎 | `show run` 看得到嗎 |
| --- | --- | --- | --- |
| VLAN 編號與名稱 | ★★★★ `flash:vlan.dat` | ★★★★★ **不會** | VTP transparent／off 模式下看得到；server／client 模式下看不到 |
| VTP 網域名稱與修訂版號 | ★★★★★ `flash:vlan.dat` | ★★★★★ **不會** | 不會，要用 `show vtp status` |
| 埠的 VLAN 歸屬 | `running-config` | 會 | 會 |
| trunk 的 allowed／native | `running-config` | 會 | 會 |

> [!danger] ★★★★★ 「我 `write erase` 過了，這是乾淨的機器」是錯的
> 回收機、備品機、從別的機關調撥來的機器，只做 `write erase` + `reload`：
> **VLAN 資料庫和 VTP 修訂版號原封不動地留著。**
> 這台機器一插上網路，如果它的 VTP 修訂版號比你的正式環境高，
> **它會在數秒內把全網的 VLAN 資料庫覆蓋成它自己的版本** —— 下一節詳述。
>
> 徹底清空的完整程序：
>
> ```cisco
> Switch#write erase
> Erasing the nvram filesystem will remove all configuration files! Continue? [confirm]
> [OK]
> Erase of nvram: complete
> Switch#delete flash:vlan.dat
> Delete filename [vlan.dat]?
> Delete flash:/vlan.dat? [confirm]
> Switch#reload
> System configuration has been modified. Save? [yes/no]: no
> Proceed with reload? [confirm]
> ```
>
> 重開後必須看到 `show vtp status` 的 `Configuration Revision : 0`。

### encapsulation 的機型差異 ★★★★

```cisco
!-- Catalyst 3560 / 3750 / 部分 4500：必須先指定封裝，否則 mode trunk 會被拒絕
SW(config-if)#switchport mode trunk
Command rejected: An interface whose trunk encapsulation is "Auto" can not be
configured to "trunk" mode.
SW(config-if)#switchport trunk encapsulation dot1q
SW(config-if)#switchport mode trunk
```

```cisco
!-- Catalyst 2960 / 2960-X / 2960-L / 9200：只支援 dot1q，這個指令不存在
SW(config-if)#switchport trunk encapsulation dot1q
                                ^
% Invalid input detected at '^' marker.
```

| 機型 | `switchport trunk encapsulation dot1q` | 說明 |
| --- | --- | --- |
| Catalyst 2960／2960-X／2960-L | ★★★ **不存在，打了會報錯** | 只支援 802.1Q |
| Catalyst 3560／3750／3560-CX | ★★★★ **必須先打**，否則 `mode trunk` 被拒 | 歷史上支援過 ISL |
| Catalyst 9200／9300（IOS-XE） | 多數版本**不需要**（僅 dot1q） | 以 `?` 確認 |

★★★★ **判斷方法不要用機型硬背，用 `?`**：

```cisco
SW(config-if)#switchport trunk ?
  allowed  Set allowed VLAN characteristics when interface is in trunking mode
  native   Set trunking native characteristics when interface is in trunking mode
  pruning  Set pruning VLAN characteristics when interface is in trunking mode
```

沒有 `encapsulation` 這一項＝你的機型不需要它。

### DTP：預設就開著的自動協商 ★★★★

DTP（Dynamic Trunking Protocol）是 Cisco 私有協定，
兩端會互相商量「我們這條線要當 access 還是 trunk」。

| 本端模式 | 對端 `access` | 對端 `dynamic auto` | 對端 `dynamic desirable` | 對端 `trunk` |
| --- | --- | --- | --- | --- |
| `access` | access | access | access | ★★★★ **不一致，會出問題** |
| `dynamic auto` | access | ★★★ **access**（兩邊都被動 → 談不成 trunk） | trunk | trunk |
| `dynamic desirable` | access | trunk | trunk | trunk |
| `trunk` | ★★★★ 不一致 | trunk | trunk | trunk |

★★★★ 很多 Catalyst 機型的**出廠預設是 `dynamic auto`**（部分是 `dynamic desirable`），
用 `show interfaces <埠> switchport` 的 `Administrative Mode` 欄可以確認。

> [!danger] ★★★★★ DTP 是一個現成的攻擊面
> 攻擊者只要在一個**沒關掉 DTP 的 access 埠**上接一台會發 DTP 的裝置
> （Linux 上用 `yersinia` 之類的工具就能做到），把埠協商成 trunk，
> **這台機器就能看到並注入所有 VLAN 的流量**，VLAN 隔離瞬間歸零。
>
> 更常見的不是攻擊，是**意外**：某人把一台舊交換器接到 access 埠上，
> 兩邊 DTP 談成 trunk，於是兩個本來該隔離的網段就通了，
> 而 `show running-config` 上那個埠**看起來還是 access**（因為協商結果不寫進設定檔）。
>
> ★★★★★ 解法只有一行：**每一個埠都明確指定模式，並加上 `switchport nonegotiate`。**

```cisco
!-- access 埠：明確指定 + 關 DTP
SW(config-if)#switchport mode access
SW(config-if)#switchport access vlan 30
SW(config-if)#switchport nonegotiate

!-- trunk 埠：明確指定 + 關 DTP
SW(config-if)#switchport mode trunk
SW(config-if)#switchport nonegotiate
```

★★★ 注意：`switchport nonegotiate` **只能在明確的 `access` 或 `trunk` 模式下設定**，
在 `dynamic` 模式下會被拒絕：

```cisco
SW(config-if)#switchport nonegotiate
Command rejected: Conflict between 'nonegotiate' and 'dynamic' status.
```

### native VLAN：那個不帶標籤的例外 ★★★★

802.1Q trunk 上每個封包都帶 VLAN 標籤，**只有 native VLAN 的封包不帶**。
預設 native VLAN 是 **VLAN 1**。

```text
trunk 線上跑的東西：
  VLAN 30 的封包 ──▶ [ 乙太標頭 ][ 802.1Q tag = 30 ][ 資料 ]
  VLAN 99 的封包 ──▶ [ 乙太標頭 ][ 802.1Q tag = 99 ][ 資料 ]
  native VLAN 的封包 ─▶ [ 乙太標頭 ][ 資料 ]        ★ 沒有標籤
```

| 風險 | 說明 | 星級 |
| --- | --- | --- |
| **兩端 native VLAN 不一致** | ★★★★ A 端的 VLAN 1 封包會被 B 端當成 VLAN 99 收下 → **兩個 VLAN 互串**，隔離失效 | ★★★★ |
| **native VLAN 用 VLAN 1** | ★★★★ VLAN 1 同時跑 CDP、STP、VTP、DTP 等控制流量，且是所有埠的預設歸屬，攻擊者最容易搭上 | ★★★★ |
| **雙標籤 VLAN hopping** | ★★★★ 攻擊者送出帶兩層標籤的封包，外層是 native VLAN（會被剝掉），內層送進目標 VLAN → 單向注入 | ★★★★ |

★★★★ 三道防線，機關環境全部都要做：

```cisco
!-- 防線 1：native VLAN 改成一個沒人用的專屬 VLAN，且兩端一致
SW(config)#vlan 999
SW(config-vlan)#name NATIVE-UNUSED
SW(config-vlan)#exit
SW(config)#interface GigabitEthernet1/0/24
SW(config-if)#switchport trunk native vlan 999

!-- 防線 2：把 native VLAN 從 allowed list 拿掉（它不需要承載使用者流量）
SW(config-if)#switchport trunk allowed vlan 20,30,99

!-- 防線 3：強制連 native VLAN 也打標籤（★★★ 支援的機型才有）
SW(config)#vlan dot1q tag native
```

> [!warning] ★★★★ 兩端 native VLAN 不一致，CDP 會叫
> ```text
> *Sep  2 11:02:14.331: %CDP-4-NATIVE_VLAN_MISMATCH: Native VLAN mismatch discovered
> on GigabitEthernet1/0/24 (999), with SW-DIST-01 GigabitEthernet1/0/8 (1).
> ```
> ★★★★ 看到這個 log **一定要處理**，不要當成雜訊關掉。
> 它代表兩台交換器對「哪個 VLAN 不打標籤」的認知不同，
> 等於在兩個 VLAN 之間開了一個未受控的通道。
> ★★★ 對端是 Juniper 時 CDP 不會叫（Juniper 用 LLDP），要靠人工核對，更容易漏。

### VTP：本篇最危險的一節 ★★★★★

VTP（VLAN Trunking Protocol）的原意是好的：在一台交換器上建 VLAN，
同網域的其他交換器自動同步，不用一台一台建。

**它的致命設計是「修訂版號（Configuration Revision）比大小」。**

```text
VTP 同步規則：
  收到一個 VTP 通告 ─▶ 網域名稱一樣嗎？ ── 不一樣 ─▶ 忽略
                          │ 一樣
                          ▼
                    對方的修訂版號 > 我的？ ── 否 ─▶ 忽略
                          │ 是
                          ▼
              ★★★★★ 用對方的 VLAN 資料庫【整份覆蓋】我的
                     （不是合併，是覆蓋 —— 我有他沒有的 VLAN 直接消失）
```

> [!danger] ★★★★★ 機關現場最經典的一次全網斷線
> **情境**：某分處的交換器壞了，維運人員從備品櫃拿一台三年前退役的
> Catalyst 2960 出來頂替。那台舊機器：
> - 屬於同一個 VTP 網域（因為當年就在同一個網域裡）
> - `write erase` 過了，但**沒有刪 `vlan.dat`**
> - 修訂版號是 `87`（當年被改過很多次）
>
> 而現在的正式環境修訂版號是 `31`。
>
> **結果**：網路線一插上，這台舊機器發出 VTP 通告，
> 全網每一台 VTP client 與 server 在**數秒內**把 VLAN 資料庫換成三年前的版本。
> 現在才有的 VLAN 全部消失，所有 access 埠的 VLAN 歸屬變成無效，
> **整個機關斷網**，而且從 `show running-config` 完全看不出原因。
>
> ★★★★★ 修復要重建整份 VLAN 資料庫，通常要一到數小時。

**接手任何一台 Cisco 交換器，第一件事就是查 VTP 狀態：**

```cisco
SW-3F-01#show vtp status
VTP Version capable             : 1 to 3
VTP version running             : 1
VTP Domain Name                 : GOVNET
VTP Pruning Mode                : Disabled
VTP Traps Generation            : Disabled
Device ID                       : 001a.2b3c.4d00
Configuration last modified by 10.10.99.31 at 9-2-26 09:14:22
Local updater ID is 10.10.99.31 on interface Vl99 (lowest numbered VLAN interface found)

Feature VLAN:
--------------
VTP Operating Mode                : Server
Maximum VLANs supported locally   : 255
Number of existing VLANs          : 9
Configuration Revision            : 31
MD5 digest                        : 0x2A 0x14 0x9F 0x33 0x7C 0x51 0x08 0xE6
```

要看的三個欄位：

| 欄位 | 危險值 | 安全值 | 星級 |
| --- | --- | --- | --- |
| `VTP Operating Mode` | ★★★★★ `Server` 或 `Client` | `Transparent` 或 `Off` | ★★★★★ |
| `VTP Domain Name` | ★★★★ 有值（且與其他設備相同） | `NULL` 或機關唯一值 | ★★★★ |
| `Configuration Revision` | ★★★★★ 大於 0 | `0` | ★★★★★ |

**四種 VTP 模式**：

| 模式 | 會不會被別人覆蓋 | 會不會覆蓋別人 | 本機能不能建 VLAN | VLAN 存在哪 |
| --- | --- | --- | --- | --- |
| `server` | ★★★★★ 會 | ★★★★★ 會 | 能 | `vlan.dat` |
| `client` | ★★★★★ 會 | 不會 | ★★★ **不能** | `vlan.dat` |
| `transparent` | ★★★ 不會 | 不會（但會轉發通告） | 能 | ★ `vlan.dat` ＋ **`running-config`** |
| `off`（VTPv3） | 不會 | 不會（也不轉發） | 能 | `vlan.dat` ＋ `running-config` |

> [!tip] ★★★★★ 機關環境的標準建議
> **一律使用 `vtp mode transparent`**（或支援 VTPv3 的機型用 `vtp mode off`）。
>
> ```cisco
> SW(config)#vtp mode transparent
> Setting device to VTP Transparent mode for VLANS.
> SW(config)#vtp domain NONE
> Changing VTP domain name from GOVNET to NONE
> ```
>
> 理由：
> 1. ★★★★★ 徹底移除「一台舊機器毀掉全網」的風險
> 2. ★★★★ VLAN 定義會進 `running-config`，**備份設定檔就等於備份了 VLAN**，
>    還原時不用另外處理 `vlan.dat`
> 3. ★★★ 一個機關的 VLAN 數量通常 20 個以內，手動在每台建根本不是負擔
> 4. ★★★ VLAN 變更會留在設定檔的版本歷史裡，稽核查得到是誰改的
>
> 代價：新增 VLAN 要每台交換器都建一次。**這個代價非常划算。**

★★★ 如果組織政策要求必須用 VTP，那就用 **VTPv3**：它引入了
「primary server」機制，只有明確被指定為 primary 的設備才能改資料庫，
且加入網域需要密碼，大幅降低誤覆蓋風險。

```cisco
SW(config)#vtp version 3
SW(config)#vtp domain GOVNET
SW(config)#vtp password Str0ng-VTP-Secret
SW(config)#end
SW#vtp primary vlan
This system is becoming primary server for feature vlan
```

**如何讓一台舊機器的修訂版號歸零**（接入正式環境前的必要程序）：

| 方法 | 指令 | 說明 |
| --- | --- | --- |
| ★★★★★ 刪 `vlan.dat` 後重開 | `delete flash:vlan.dat` → `reload` | 最徹底，同時清掉 VLAN 定義 |
| ★★★★ 改成 transparent | `vtp mode transparent` | 修訂版號歸 0，且不再參與同步 |
| ★★★ 改網域名稱 | `vtp domain <不同的名字>` | 換網域即歸 0，但仍是 server／client |

## 環境準備與安裝

### 本篇的拓樸與 VLAN 規劃

```text
                       10.10.99.254（L3 閘道 / 防火牆）
                              │
                    ┌─────────┴──────────┐
                    │    SW-DIST-01      │  Catalyst 9300, IOS-XE 17.9
                    └─────────┬──────────┘
                       Gi1/0/8│ trunk
                              │ allowed: 20,30,40,99
                              │ native : 999
                    ┌─────────┴──────────┐
                    │     SW-3F-01       │  Catalyst 2960-X, IOS 15.2(7)E3
                    │                    │
                    │ Gi1/0/1-16  → VLAN 30 辦公
                    │ Gi1/0/17-18 → VLAN 20 AP（trunk，帶 VLAN 40 訪客）
                    │ Gi1/0/19-20 → VLAN 40 訪客
                    │ Gi1/0/21-23 → VLAN 999 未用 + shutdown
                    │ Gi1/0/24    → trunk 上行
                    └────────────────────┘
```

| VLAN | 名稱 | 網段 | 用途 |
| --- | --- | --- | --- |
| 20 | `WIFI-AP-MGMT` | 10.10.20.0/24 | 無線 AP 管理 |
| 30 | `OFFICE` | 10.10.30.0/24 | 辦公電腦 |
| 40 | `GUEST` | 10.10.40.0/24 | 訪客無線（★★★ 需與其他 VLAN 完全隔離） |
| 99 | `MGMT` | 10.10.99.0/24 | ★★★★ 網路設備管理 |
| 999 | `NATIVE-UNUSED` | 無 | ★★★★ native VLAN ＋ 未用埠黑洞 |

★★★★ 注意 VLAN 999 身兼兩個角色：trunk 的 native VLAN，以及未用埠的黑洞 VLAN。
它**沒有 SVI、沒有 IP、不出現在任何 allowed list**，是一個純粹的死路。

### 動工前的三項檢查 ★★★★

```cisco
!-- 檢查 1：VTP 模式（★★★★★ 這台會不會被別人的資料庫覆蓋）
SW-3F-01#show vtp status | include Operating Mode|Domain Name|Configuration Revision
VTP Domain Name                 : NULL
VTP Operating Mode                : Transparent
Configuration Revision            : 0
```

```cisco
!-- 檢查 2：現有 VLAN 與埠歸屬
SW-3F-01#show vlan brief
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Gi1/0/1, Gi1/0/2, Gi1/0/3, Gi1/0/4
                                                Gi1/0/5, Gi1/0/6, Gi1/0/7, Gi1/0/8
                                                ... （全部在 VLAN 1）
1002 fddi-default                     act/unsup
1003 token-ring-default               act/unsup
1004 fddinet-default                  act/unsup
1005 trnet-default                    act/unsup
```

```cisco
!-- 檢查 3：現有 trunk（★★★★ 接手時最重要的一張圖）
SW-3F-01#show interfaces trunk

Port        Mode             Encapsulation  Status        Native vlan
Gi1/0/24    desirable        n-802.1q       trunking      1

Port        Vlans allowed on trunk
Gi1/0/24    1-4094

Port        Vlans allowed and active in management domain
Gi1/0/24    1

Port        Vlans in spanning tree forwarding state and not pruned
Gi1/0/24    1
```

★★★★ 這份輸出有兩個紅字：`Mode` 是 `desirable`（DTP 開著），
`Native vlan` 是 `1`，`Vlans allowed` 是 `1-4094`（全開）。三項都要改。
★★★ `Encapsulation` 欄位前綴 `n-` 代表「negotiated（協商而來）」，
明確設定後會變成 `802.1q`。

> [!info]- Juniper JunOS 對照
> | 事情 | Cisco IOS | Juniper JunOS（ELS） |
> | --- | --- | --- |
> | 建 VLAN | `vlan 30` ＋ `name OFFICE` | `set vlans OFFICE vlan-id 30` |
> | access 埠 | `switchport mode access` ＋ `switchport access vlan 30` | `set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access vlan members OFFICE` |
> | trunk 埠 | `switchport mode trunk` | `... interface-mode trunk` |
> | 允許的 VLAN | ★★★★★ `switchport trunk allowed vlan add 30`（不加 `add` 是覆蓋） | `set ... vlan members OFFICE`（★ 天生就是「新增」語意） |
> | 移除某個 VLAN | `switchport trunk allowed vlan remove 30` | `delete ... vlan members OFFICE` |
> | native vlan | `switchport trunk native vlan 999` | `set interfaces ge-0/0/0 native-vlan-id 999` |
> | 關閉自動協商 | ★★★★ `switchport nonegotiate` | ★ JunOS **沒有 DTP**，天生不需要 |
> | VLAN 全網同步 | ★★★★★ VTP（**建議關閉**） | ★ JunOS **沒有等價的危險機制**（MVRP 需明確啟用且不會覆蓋既有設定） |
> | 看 VLAN | `show vlan brief` | `show vlans` |
> | 看 trunk | `show interfaces trunk` | `show ethernet-switching interfaces` |
> | 改壞的保險 | `reload in 5` | `commit confirmed 5` |
>
> ★★★★★ 兩個最大的體感差異：**JunOS 沒有 DTP、沒有 VTP**，
> 所以本篇最危險的那兩節在 JunOS 上根本不存在；
> 而 JunOS 的 `vlan members` 是累加語意，不會發生「少打一個 `add` 就斷全網」。
> 這也是本手冊以 JunOS 為主線的原因之一。詳見 [[040-01-06-guide-Juniper-VLAN與Trunk設定]]。

## 基礎設定

### 步驟 1：確保 VTP 不會害你 ★★★★★

**在建任何 VLAN 之前先做這件事。**

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#vtp mode transparent
Setting device to VTP Transparent mode for VLANS.
SW-3F-01(config)#vtp domain NONE
Changing VTP domain name from GOVNET to NONE
SW-3F-01(config)#end
SW-3F-01#show vtp status | include Operating Mode|Revision
VTP Operating Mode                : Transparent
Configuration Revision            : 0
```

★★★★ 切成 transparent 之後，VLAN 定義才會出現在 `running-config` 裡：

```cisco
SW-3F-01#show running-config | begin ^vlan
vlan 20
 name WIFI-AP-MGMT
!
vlan 30
 name OFFICE
!
```

### 步驟 2：建立 VLAN

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#vlan 20
SW-3F-01(config-vlan)#name WIFI-AP-MGMT
SW-3F-01(config-vlan)#vlan 30
SW-3F-01(config-vlan)#name OFFICE
SW-3F-01(config-vlan)#vlan 40
SW-3F-01(config-vlan)#name GUEST
SW-3F-01(config-vlan)#vlan 99
SW-3F-01(config-vlan)#name MGMT
SW-3F-01(config-vlan)#vlan 999
SW-3F-01(config-vlan)#name NATIVE-UNUSED
SW-3F-01(config-vlan)#exit
SW-3F-01(config)#end
```

★★★ 在 `config-vlan` 模式下可以直接打下一個 `vlan <id>`，不用先 `exit`。

也可以一次建多個（但這樣就沒辦法命名）：

```cisco
SW-3F-01(config)#vlan 20,30,40,99,999
SW-3F-01(config-vlan)#exit
```

**驗證**：

```cisco
SW-3F-01#show vlan brief
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Gi1/0/1, Gi1/0/2, Gi1/0/3, Gi1/0/4
                                                ... （尚未分配）
20   WIFI-AP-MGMT                     active
30   OFFICE                           active
40   GUEST                            active
99   MGMT                             active
999  NATIVE-UNUSED                    active
1002 fddi-default                     act/unsup
```

> [!warning] ★★★ VLAN 名稱不能有空格，且大小寫敏感
> `name OFFICE 3F` 會被當成 `name OFFICE` 加上一個無效參數。
> 用連字號：`name OFFICE-3F`。
> ★★ 名稱只是給人看的，**跨設備不需要一致**（不像 JunOS 用名稱當識別）；
> 但機關內部應該統一，否則盤點時對不起來。

### 步驟 3：設定 access 埠

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface range GigabitEthernet1/0/1 - 16
SW-3F-01(config-if-range)#description USER-3F-OFFICE
SW-3F-01(config-if-range)#switchport mode access
SW-3F-01(config-if-range)#switchport access vlan 30
SW-3F-01(config-if-range)#switchport nonegotiate
SW-3F-01(config-if-range)#spanning-tree portfast
%Warning: portfast should only be enabled on ports connected to a single
 host. Connecting hubs, concentrators, switches, bridges, etc... to this
 interface when portfast is enabled, can cause temporary bridging loops.
 Use with CAUTION
SW-3F-01(config-if-range)#spanning-tree bpduguard enable
SW-3F-01(config-if-range)#no shutdown
SW-3F-01(config-if-range)#end
```

★★★★ **這五行是 access 埠的標準組合，缺一不可**：

| 指令 | 沒設的後果 | 星級 |
| --- | --- | --- |
| `switchport mode access` | ★★★★ 停留在 `dynamic auto`，可能被協商成 trunk | ★★★★ |
| `switchport access vlan 30` | 留在 VLAN 1，隔離失效 | ★★★★ |
| `switchport nonegotiate` | ★★★★ DTP 仍在發封包，可被利用 | ★★★★ |
| `spanning-tree portfast` | 使用者要等 ~30 秒才拿得到 DHCP，被當成「網路很慢」 | ★★★ |
| `spanning-tree bpduguard enable` | ★★★★ 使用者私接小型交換器造成迴圈，全網廣播風暴 | ★★★★ |

★★★ portfast 與 bpduguard 的詳細說明見 [[040-01-13-guide-Cisco-埠設定與安全]]。

**驗證單一埠的完整狀態**：

```cisco
SW-3F-01#show interfaces GigabitEthernet1/0/1 switchport
Name: Gi1/0/1
Switchport: Enabled
Administrative Mode: static access
Operational Mode: static access
Administrative Trunking Encapsulation: dot1q
Operational Trunking Encapsulation: native
Negotiation of Trunking: Off
Access Mode VLAN: 30 (OFFICE)
Trunking Native Mode VLAN: 1 (default)
Administrative Native VLAN tagging: enabled
Voice VLAN: none
Trunking VLANs Enabled: ALL
Pruning VLANs Enabled: 2-1001
Operational private-vlan: none
Capture Mode Disabled
Appliance trust: none
```

★★★★ 要看的三行：

| 欄位 | 應該是 | 意義 |
| --- | --- | --- |
| `Administrative Mode` | `static access` | ★★★★ 你設的模式（`dynamic auto` 代表沒明確設定） |
| `Operational Mode` | `static access` | ★★★★ **實際協商出來的模式**（和上面不一致就有鬼） |
| `Negotiation of Trunking` | ★★★★ `Off` | DTP 已關（`On` 代表 `nonegotiate` 沒設或設失敗） |

### 步驟 4：設定 trunk 埠 ★★★★★

**遠端操作請先上保險**：

```cisco
SW-3F-01#reload in 5
Reload scheduled in 5 minutes by netadm on vty0 (10.10.99.50)
Reload reason: Reload Command
Proceed with reload? [confirm]
```

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface GigabitEthernet1/0/24
SW-3F-01(config-if)#description UPLINK-TO-SW-DIST-01-Gi1/0/8
SW-3F-01(config-if)#switchport trunk native vlan 999
SW-3F-01(config-if)#switchport trunk allowed vlan 20,30,40,99
SW-3F-01(config-if)#switchport mode trunk
SW-3F-01(config-if)#switchport nonegotiate
SW-3F-01(config-if)#end
```

> [!danger] ★★★★★ 指令的順序是刻意的，不要調換
> **先設 `native vlan` 與 `allowed vlan`，最後才 `switchport mode trunk`。**
>
> 如果先打 `switchport mode trunk`，那一瞬間這條 trunk 的 allowed list 是預設的
> **1-4094 全開**、native VLAN 是 **1**。在對端已經是 trunk 的情況下，
> 這會讓所有 VLAN（含你不想給的）短暫互通，並可能觸發 STP 重新收斂。
> 先把參數設好再切模式，切換是一瞬間的事。
>
> ★★★★★ 而 `switchport trunk allowed vlan 20,30,40,99` **沒有 `add`** 是刻意的：
> 這是**初次設定**，我們要的就是覆蓋掉預設的 1-4094。
> **之後要新增 VLAN 時，一定要用 `add`。** 下一節詳述。

**驗證**：

```cisco
SW-3F-01#show interfaces trunk

Port        Mode             Encapsulation  Status        Native vlan
Gi1/0/24    on               802.1q         trunking      999

Port        Vlans allowed on trunk
Gi1/0/24    20,30,40,99

Port        Vlans allowed and active in management domain
Gi1/0/24    20,30,40,99

Port        Vlans in spanning tree forwarding state and not pruned
Gi1/0/24    20,30,40,99
```

★★★★ **四張表要一起讀**：

| 表 | 意義 | 不一致代表什麼 |
| --- | --- | --- |
| `Vlans allowed on trunk` | 你設定允許的 | 這是你的意圖 |
| `Vlans allowed and active in management domain` | ★★★★ **本機真的有建這個 VLAN** 的部分 | 少了某個 VLAN → **你 allowed 了一個本機沒建的 VLAN** |
| `Vlans in spanning tree forwarding state and not pruned` | ★★★★ 真正在轉發的 | 少了某個 VLAN → 被 STP 阻斷或被 VTP pruning 剪掉 |

★★★★★ **這是排錯的黃金三段式**：第一張有、第二張沒有 → 去 `vlan <id>` 建它；
第二張有、第三張沒有 → 去看 STP（[[040-01-16-guide-網路設備-鏈路聚合與STP]]）。

確認 SSH 還通、上行還在，然後：

```cisco
SW-3F-01#reload cancel
SW-3F-01#write memory
Building configuration...
[OK]
```

### 步驟 5：未用埠丟進黑洞 ★★★

```cisco
SW-3F-01(config)#interface range GigabitEthernet1/0/21 - 23
SW-3F-01(config-if-range)#description UNUSED-DO-NOT-PATCH
SW-3F-01(config-if-range)#switchport mode access
SW-3F-01(config-if-range)#switchport access vlan 999
SW-3F-01(config-if-range)#switchport nonegotiate
SW-3F-01(config-if-range)#shutdown
SW-3F-01(config-if-range)#end
```

★★★★ 為什麼要**同時**做「丟 VLAN 999」和 `shutdown` 兩件事？
因為 `shutdown` 可能被別人 `no shutdown` 回來（例如急著接一台機器），
這時它至少還在一個不通任何地方的 VLAN 裡，而不是直接掉進 VLAN 1。
★★★ 兩層防護，見 [[040-01-13-guide-Cisco-埠設定與安全]]。

## 進階設定與調校

### `allowed vlan` 的四個關鍵字 ★★★★★

**這一節是本篇最容易出事的地方，請務必看完。**

| 寫法 | 行為 | 遠端使用風險 |
| --- | --- | --- |
| `switchport trunk allowed vlan 30` | ★★★★★ **整份覆蓋**成只有 30 | ★★★★★ 極高 |
| `switchport trunk allowed vlan add 30` | 在現有清單上**新增** 30 | 低 |
| `switchport trunk allowed vlan remove 30` | 從現有清單**移除** 30 | ★★★★ 中（移到你自己的 VLAN 就斷） |
| `switchport trunk allowed vlan except 30` | 允許 **1-4094 中除了 30 以外**的全部 | ★★★ 中（等於幾乎全開） |
| `switchport trunk allowed vlan all` | 恢復成 1-4094 全開 | ★★★ 中（隔離失效） |
| `switchport trunk allowed vlan none` | ★★★★★ **一個都不允許**，這條 trunk 完全不通 | ★★★★★ 極高 |

> [!danger] ★★★★★ 最貴的一次打字
> ```cisco
> SW-3F-01(config-if)#switchport trunk allowed vlan 50
> ```
> 你以為是「新增 VLAN 50」，實際是「**這條 trunk 從現在起只允許 VLAN 50**」。
> 包含管理 VLAN 99 在內的所有 VLAN 全部被移除，
> **你的 SSH 在按下 Enter 的同一瞬間斷線**，整棟樓斷網。
>
> 正確寫法：
> ```cisco
> SW-3F-01(config-if)#switchport trunk allowed vlan add 50
> ```
>
> ★★★★★ 三個保命習慣：
> 1. 動 trunk 之前一定先 `reload in 5`
> 2. 改之前先 `do show interfaces trunk` 把現況抄下來
> 3. **看到 `allowed vlan` 沒有 `add`／`remove` 就停下來想三秒**

**安全的變更流程**：

```cisco
!-- ① 抄現況
SW-3F-01#show interfaces trunk | begin Vlans allowed on trunk
Port        Vlans allowed on trunk
Gi1/0/24    20,30,40,99

!-- ② 上保險
SW-3F-01#reload in 5
Reload scheduled in 5 minutes by netadm on vty0 (10.10.99.50)
Proceed with reload? [confirm]

!-- ③ 用 add 新增
SW-3F-01#configure terminal
SW-3F-01(config)#interface gi1/0/24
SW-3F-01(config-if)#switchport trunk allowed vlan add 50
SW-3F-01(config-if)#end

!-- ④ 驗證
SW-3F-01#show interfaces trunk | begin Vlans allowed on trunk
Port        Vlans allowed on trunk
Gi1/0/24    20,30,40,50,99

!-- ⑤ 解除保險並存檔
SW-3F-01#reload cancel
SW-3F-01#write memory
```

### VLAN 1 的處理 ★★★★

VLAN 1 不能刪除（IOS 不允許），但可以讓它不承載任何東西：

```cisco
!-- ① 上行 trunk 不允許 VLAN 1 通過
SW-3F-01(config)#interface gi1/0/24
SW-3F-01(config-if)#switchport trunk allowed vlan remove 1

!-- ② VLAN 1 的 SVI 關掉
SW-3F-01(config)#interface Vlan1
SW-3F-01(config-if)#shutdown

!-- ③ 沒有任何 access 埠留在 VLAN 1
SW-3F-01#show vlan brief | begin ^1
1    default                          active
```

★★★★ 第三步的驗證很重要：`show vlan brief` 的 VLAN 1 那列
**Ports 欄應該是空的**。有埠留在那裡就是漏網之魚。

### voice VLAN：一個埠兩個 VLAN ★★★

IP 電話串接電腦的場景，一個埠要同時承載語音（帶標籤）與資料（不帶標籤）：

```cisco
SW-3F-01(config)#vlan 50
SW-3F-01(config-vlan)#name VOICE
SW-3F-01(config-vlan)#exit
SW-3F-01(config)#interface GigabitEthernet1/0/10
SW-3F-01(config-if)#switchport mode access
SW-3F-01(config-if)#switchport access vlan 30
SW-3F-01(config-if)#switchport voice vlan 50
SW-3F-01(config-if)#spanning-tree portfast
SW-3F-01(config-if)#end
```

```cisco
SW-3F-01#show interfaces gi1/0/10 switchport | include VLAN
Access Mode VLAN: 30 (OFFICE)
Trunking Native Mode VLAN: 1 (default)
Voice VLAN: 50 (VOICE)
```

★★★ 這技術上是一種 trunk（IOS 稱之為 access port with voice VLAN），
電話透過 CDP／LLDP-MED 得知該用哪個 VLAN 打標籤。
★★★★ **這也是 port-security 的計數要設成 `maximum 2` 或 `3` 的原因**
（電話一個 MAC、電腦一個 MAC），見 [[040-01-13-guide-Cisco-埠設定與安全]]。

### VTP pruning：看起來很美但別用 ★★★

`vtp pruning` 的作用是「某個 VLAN 在下游沒有任何埠使用時，
自動不讓它的廣播流量走上這條 trunk」。

```cisco
SW-3F-01(config)#vtp pruning
```

★★★★ **不建議在機關環境使用**，理由：

1. ★★★★ 它要求 VTP 模式是 `server`／`client` —— 而我們已經決定關掉 VTP
2. ★★★ 「自動」的東西在排錯時很難解釋，`show interfaces trunk` 的第四張表
   突然少一個 VLAN，你會找很久
3. ★★★ 手動維護精準的 `allowed vlan` list 能達到同樣效果，而且是**明示的**

★★★ 精準的 allowed list 就是最好的 pruning：接入層交換器的上行 trunk
只 allow 它真正用得到的那三四個 VLAN，而不是 1-4094。

### 批次驗證整台交換器的 VLAN 設定 ★★★

```cisco
!-- 每個埠的 access VLAN 一覽
SW-3F-01#show interfaces status | exclude notconnect|disabled
Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   USER-3F-OFFICE     connected    30         a-full a-1000 10/100/1000BaseTX
Gi1/0/10  IPPHONE-3F-014     connected    30         a-full  a-100 10/100/1000BaseTX
Gi1/0/17  AP-3F-01           connected    trunk      a-full a-1000 10/100/1000BaseTX
Gi1/0/24  UPLINK-TO-SW-DIST- connected    trunk      a-full a-1000 10/100/1000BaseTX
```

```cisco
!-- ★★★★ 找出所有「還在 dynamic 模式」的埠（應該一個都沒有）
SW-3F-01#show interfaces switchport | include Name:|Administrative Mode
Name: Gi1/0/1
Administrative Mode: static access
Name: Gi1/0/2
Administrative Mode: static access
...
Name: Gi1/0/24
Administrative Mode: trunk
```

```cisco
!-- ★★★★ 找出所有還允許 VLAN 1 的 trunk
SW-3F-01#show interfaces trunk | begin Vlans allowed on trunk
Port        Vlans allowed on trunk
Gi1/0/17    20,40
Gi1/0/24    20,30,40,99
```

★★★ 沒有 `1` 出現在列表裡＝過關。

## 完整實戰範例

**情境**：三樓辦公室要新增一個訪客無線網段（VLAN 40），
AP 已經買好接在 Gi1/0/17。現在是**上班時間**，你只能從辦公室 SSH 進去改，
**改壞了就是全樓斷網**。現有 trunk 上行只有 VLAN 20/30/99。

### 前置環境

| 項目 | 值 |
| --- | --- |
| 你的位置 | 10.10.99.50（管理網段） |
| 目標設備 | SW-3F-01（10.10.99.31），Catalyst 2960-X，IOS 15.2(7)E3 |
| 上游 | SW-DIST-01 Gi1/0/8（★★★★ 也要改，否則 VLAN 40 到不了防火牆） |
| 要新增 | VLAN 40 `GUEST` |
| AP 埠 | Gi1/0/17（要改成 trunk，native 999，allowed 20,40） |
| 維護視窗 | 無 —— 全程不可中斷既有服務 |

### 步驟 0：建立回退點 ★★★★★

```cisco
SW-3F-01#terminal length 0
SW-3F-01#show running-config
Building configuration...
... （整份複製貼進本機檔案，命名 SW-3F-01-before-20260902.cfg）
```

```cisco
SW-3F-01#copy running-config tftp://10.10.99.20/SW-3F-01-before-20260902.cfg
Address or name of remote host [10.10.99.20]?
Destination filename [SW-3F-01-before-20260902.cfg]?
!!
5127 bytes copied in 1.284 secs (3993 bytes/sec)
```

**驗證**：到備份主機確認檔案存在且大小合理（不是 0 bytes）。

★★★★ 同樣的動作對 SW-DIST-01 也做一次。

### 步驟 1：抄下現況

```cisco
SW-3F-01#show vtp status | include Operating Mode|Revision
VTP Operating Mode                : Transparent
Configuration Revision            : 0

SW-3F-01#show interfaces trunk
Port        Mode             Encapsulation  Status        Native vlan
Gi1/0/24    on               802.1q         trunking      999

Port        Vlans allowed on trunk
Gi1/0/24    20,30,99

SW-3F-01#show interfaces gi1/0/17 switchport | include Mode|VLAN|Negotiation
Administrative Mode: static access
Operational Mode: static access
Negotiation of Trunking: Off
Access Mode VLAN: 20 (WIFI-AP-MGMT)
Trunking Native Mode VLAN: 1 (default)
```

★★★★ **把這三段輸出貼進變更單**。出事時它就是回退的依據。

### 步驟 2：上保險

```cisco
SW-3F-01#reload in 10
Reload scheduled in 10 minutes by netadm on vty0 (10.10.99.50)
Reload reason: Reload Command
Proceed with reload? [confirm]
SW-3F-01#show reload
Reload scheduled in 9 minutes and 54 seconds by netadm on vty0 (10.10.99.50)
```

★★★★★ 對 **SW-DIST-01 也要下 `reload in 10`** —— 上游改壞一樣會斷你。

> [!warning] ★★★★ 兩台設備的 reload 保險要錯開幾分鐘
> 如果兩台同時重開，STP 會重新收斂兩次，中斷時間變長。
> 實務做法：SW-DIST-01 設 `reload in 12`、SW-3F-01 設 `reload in 10`，
> 讓下游先復原。

### 步驟 3：先改上游（VLAN 40 要有路可走）

```cisco
SW-DIST-01#configure terminal
SW-DIST-01(config)#vlan 40
SW-DIST-01(config-vlan)#name GUEST
SW-DIST-01(config-vlan)#exit
SW-DIST-01(config)#interface GigabitEthernet1/0/8
SW-DIST-01(config-if)#switchport trunk allowed vlan add 40
SW-DIST-01(config-if)#end
```

★★★★★ 注意那個 `add`。

**驗證**：

```cisco
SW-DIST-01#show interfaces trunk | begin Vlans allowed on trunk
Port        Vlans allowed on trunk
Gi1/0/8     20,30,40,99
```

★★★ 三樓的辦公電腦此時應該完全沒有感覺 —— 用 ping 確認：

```cisco
SW-DIST-01#ping 10.10.30.14
Type escape sequence to abort.
Sending 5, 100-byte ICMP Echos to 10.10.30.14, timeout is 2 seconds:
!!!!!
Success rate is 100 percent (5/5), round-trip min/avg/max = 1/2/4 ms
```

### 步驟 4：在下游建 VLAN 並開通 trunk

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#vlan 40
SW-3F-01(config-vlan)#name GUEST
SW-3F-01(config-vlan)#exit
SW-3F-01(config)#interface GigabitEthernet1/0/24
SW-3F-01(config-if)#switchport trunk allowed vlan add 40
SW-3F-01(config-if)#end
```

**驗證黃金三段式**：

```cisco
SW-3F-01#show interfaces trunk

Port        Mode             Encapsulation  Status        Native vlan
Gi1/0/24    on               802.1q         trunking      999

Port        Vlans allowed on trunk
Gi1/0/24    20,30,40,99

Port        Vlans allowed and active in management domain
Gi1/0/24    20,30,40,99

Port        Vlans in spanning tree forwarding state and not pruned
Gi1/0/24    20,30,40,99
```

★★★★ 三張表都有 `40` ＝ 通路已經打通。
如果第二張表沒有 40 → 你忘了在本機 `vlan 40`。

★★★ 你的 SSH 還活著嗎？打個 `show clock` 確認 session 沒斷。

### 步驟 5：把 AP 埠改成 trunk

AP 要同時承載自己的管理流量（VLAN 20，不帶標籤）與訪客 SSID（VLAN 40，帶標籤）：

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface GigabitEthernet1/0/17
SW-3F-01(config-if)#description AP-3F-01-TRUNK
SW-3F-01(config-if)#switchport trunk native vlan 20
SW-3F-01(config-if)#switchport trunk allowed vlan 20,40
SW-3F-01(config-if)#switchport mode trunk
SW-3F-01(config-if)#switchport nonegotiate
SW-3F-01(config-if)#spanning-tree portfast trunk
SW-3F-01(config-if)#spanning-tree bpduguard enable
SW-3F-01(config-if)#end
```

★★★★ 三個要注意的點：

| 點 | 說明 |
| --- | --- |
| `native vlan 20` | ★★★ AP 的管理介面不打標籤，所以 native 要設成 AP 的管理 VLAN（**和上行 trunk 的 999 不同，這是刻意的**） |
| `allowed vlan 20,40` | ★★★★ 這裡**沒有 `add`** 是對的 —— 這條 trunk 是全新設定，要覆蓋掉預設的 1-4094 |
| `spanning-tree portfast trunk` | ★★★ trunk 埠接的是單一裝置（AP）不是交換器，需要 `trunk` 關鍵字才能在 trunk 上啟用 portfast |

**驗證**：

```cisco
SW-3F-01#show interfaces trunk

Port        Mode             Encapsulation  Status        Native vlan
Gi1/0/17    on               802.1q         trunking      20
Gi1/0/24    on               802.1q         trunking      999

Port        Vlans allowed on trunk
Gi1/0/17    20,40
Gi1/0/24    20,30,40,99

Port        Vlans allowed and active in management domain
Gi1/0/17    20,40
Gi1/0/24    20,30,40,99

Port        Vlans in spanning tree forwarding state and not pruned
Gi1/0/17    20,40
Gi1/0/24    20,30,40,99
```

```cisco
SW-3F-01#show interfaces gi1/0/17 switchport | include Mode|Native|Negotiation|Trunking VLANs
Administrative Mode: trunk
Operational Mode: trunk
Negotiation of Trunking: Off
Trunking Native Mode VLAN: 20 (WIFI-AP-MGMT)
Trunking VLANs Enabled: 20,40
```

★★★★ `Administrative Mode` 與 `Operational Mode` 都是 `trunk`、
`Negotiation of Trunking` 是 `Off` → 設定正確且 DTP 已關。

### 步驟 6：端到端驗證

```cisco
!-- AP 的管理 IP 通不通（VLAN 20）
SW-3F-01#ping 10.10.20.11
Type escape sequence to abort.
Sending 5, 100-byte ICMP Echos to 10.10.20.11, timeout is 2 seconds:
!!!!!
Success rate is 100 percent (5/5), round-trip min/avg/max = 1/1/2 ms

!-- AP 的 MAC 有沒有學到，在對的 VLAN 裡
SW-3F-01#show mac address-table interface GigabitEthernet1/0/17
          Mac Address Table
-------------------------------------------

Vlan    Mac Address       Type        Ports
----    -----------       --------    -----
  20    00c8.8b1a.2233    DYNAMIC     Gi1/0/17
  40    00c8.8b1a.2234    DYNAMIC     Gi1/0/17
Total Mac Addresses for this criterion: 2
```

★★★★ 看到 VLAN 40 的 MAC 出現在 Gi1/0/17 → 訪客 SSID 的流量已經帶著標籤進來了。

實際拿一台手機連上訪客 SSID，確認：

| 檢查 | 通過條件 |
| --- | --- |
| 拿到 IP | 10.10.40.x（★★★ 拿到 10.10.20.x 代表 VLAN 沒切開） |
| ping 訪客閘道 | 通 |
| ping 辦公網段 10.10.30.14 | ★★★★ **不通**（訪客隔離生效） |
| 上網 | 通 |

★★★★★ 第三項「應該不通」是最重要的驗收項目。訪客能 ping 到內部網段
＝隔離沒做好，這是資安事件不是設定錯誤。

### 步驟 7：確認既有服務沒受影響

```cisco
SW-3F-01#show interfaces status | exclude notconnect|disabled
Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   USER-3F-OFFICE     connected    30         a-full a-1000 10/100/1000BaseTX
Gi1/0/2   USER-3F-OFFICE     connected    30         a-full a-1000 10/100/1000BaseTX
Gi1/0/17  AP-3F-01-TRUNK     connected    trunk      a-full a-1000 10/100/1000BaseTX
Gi1/0/24  UPLINK-TO-SW-DIST- connected    trunk      a-full a-1000 10/100/1000BaseTX

SW-3F-01#show logging | include ERR|DOWN|MISMATCH
（應該沒有新的錯誤）
```

★★★ 特別確認**沒有** `%CDP-4-NATIVE_VLAN_MISMATCH`。

### 步驟 8：解除保險並存檔

```cisco
!-- 先解上游
SW-DIST-01#reload cancel
SW-DIST-01#write memory
Building configuration...
[OK]

!-- 再解下游
SW-3F-01#reload cancel
SW-3F-01#
*Sep  2 14:22:07.114: %SYS-5-SCHEDULED_RELOAD_CANCELLED: Scheduled reload cancelled at
14:22:07 CST Tue Sep 2 2026
SW-3F-01#write memory
Building configuration...
[OK]
```

```cisco
SW-3F-01#show archive config differences system:running-config nvram:startup-config
!Contextual Config Diffs:
!No changes were found
```

```cisco
SW-3F-01#copy running-config tftp://10.10.99.20/SW-3F-01-after-20260902.cfg
!!
5389 bytes copied in 1.312 secs (4108 bytes/sec)
```

### 驗收檢查表 ★★★★

| # | 檢查項 | 通過條件 |
| --- | --- | --- |
| 1 | `show vtp status` | Mode `Transparent`，Revision `0` |
| 2 | `show vlan brief` | VLAN 40 存在且 `active` |
| 3 | `show interfaces trunk` 四張表 | Gi1/0/24 三張表都含 `40` |
| 4 | `show interfaces gi1/0/17 switchport` | Admin/Oper Mode 皆 `trunk`，Negotiation `Off` |
| 5 | `show mac address-table interface gi1/0/17` | 有 VLAN 20 與 VLAN 40 的 MAC |
| 6 | 訪客裝置取得 IP | 10.10.40.x |
| 7 | 訪客 ping 辦公網段 | ★★★★★ **不通** |
| 8 | 辦公電腦上網 | 正常（既有服務未受影響） |
| 9 | `show logging` | 無 `NATIVE_VLAN_MISMATCH`、無 `err-disable` |
| 10 | `show reload` | 兩台都是 `No reload is scheduled.` |
| 11 | `show archive config differences ...` | `No changes were found` |
| 12 | 備份檔 | before 與 after 兩份都存在備份主機 |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| 打完 `switchport trunk allowed vlan 50` 後**全樓斷網**、SSH 立即中斷 | ★★★★★ 忘記 `add`，指令是覆蓋不是新增，管理 VLAN 被移除 | 若事前有 `reload in` 就等它重開；否則接 console 或到上游把該埠改回。**永遠用 `add`／`remove`** |
| 重開機後所有 VLAN 都不見了，`show vlan brief` 只剩預設 | ★★★★★ VTP 被一台修訂版號較高的設備覆蓋 | `show vtp status` 查修訂版號與 `last modified by`；把全網切成 `vtp mode transparent`；從備份設定檔重建 VLAN |
| 新交換器一接上，全網 VLAN 就被改掉 | ★★★★★ 回收機的 `vlan.dat` 沒清，VTP 修訂版號比正式環境高 | 接線**之前**先 `delete flash:vlan.dat` → `reload`，確認 `Configuration Revision : 0` |
| `write erase` + `reload` 之後 VLAN 還在 | ★★★★ VLAN 定義在 `flash:vlan.dat`，不在 NVRAM | 必須另外 `delete flash:vlan.dat` 再 `reload` |
| `Command rejected: An interface whose trunk encapsulation is "Auto" can not be configured to "trunk" mode.` | ★★★★ 3560／3750 等機型必須先指定封裝 | 先打 `switchport trunk encapsulation dot1q`，再 `switchport mode trunk` |
| `switchport trunk encapsulation dot1q` 回 `% Invalid input detected` | ★★★ 2960／9200 只支援 dot1q，沒有這個指令 | 直接跳過這行，`switchport mode trunk` 即可 |
| `Command rejected: Conflict between 'nonegotiate' and 'dynamic' status.` | ★★★ 埠還在 `dynamic auto`／`desirable` 模式 | 先 `switchport mode access` 或 `switchport mode trunk`，再 `switchport nonegotiate` |
| log 一直出現 `%CDP-4-NATIVE_VLAN_MISMATCH` | ★★★★ 兩端 trunk 的 native VLAN 設定不同 | 兩端統一（建議都設成專屬的 999）。**不要用關 CDP 來讓警告消失** |
| 兩個本該隔離的 VLAN 竟然互通 | ★★★★ native VLAN 不一致，或某埠被 DTP 談成 trunk | `show interfaces trunk` 核對 native；`show interfaces switchport` 找 `Operational Mode: trunk` 但你以為是 access 的埠 |
| `show interfaces trunk` 完全沒有輸出 | ★★★ 沒有任何埠處於 trunking 狀態 | `show interfaces <埠> switchport` 看 `Operational Mode`；常見是對端沒設 trunk，或線沒接 |
| `Vlans allowed on trunk` 有 VLAN 40，但 `allowed and active` 沒有 | ★★★★ **本機沒有建這個 VLAN** | `configure terminal` → `vlan 40` → `name GUEST` |
| `allowed and active` 有，但 `forwarding state and not pruned` 沒有 | ★★★★ 該 VLAN 在這條 link 被 STP 阻斷，或被 VTP pruning 剪掉 | `show spanning-tree vlan 40` 看阻斷原因；見 [[040-01-16-guide-網路設備-鏈路聚合與STP]] |
| 使用者插上網路線後要等 30 秒才能用 | ★★★ access 埠沒設 `spanning-tree portfast` | 對所有接單一終端的埠加 `spanning-tree portfast` |
| 一台設備接上 access 埠後全網變慢、廣播暴增 | ★★★★ 使用者私接小型交換器造成迴圈 | 所有 access 埠加 `spanning-tree bpduguard enable`，違規埠會自動 `err-disabled` |
| `vlan 40` 建了但 `show vlan brief` 沒有 | ★★★★ VTP 模式是 `client`，本機不允許建 VLAN | `vtp mode transparent` 之後再建 |
| VLAN 名稱設了但 `show running-config` 看不到 | ★★★ VTP 是 `server`／`client` 模式，VLAN 定義不進 running-config | 切 `transparent`；或接受並改用 `show vlan brief` 查 |
| AP 接上 trunk 後管理介面連不上 | ★★★ AP 的管理流量不打標籤，但 trunk 的 native VLAN 設錯 | `switchport trunk native vlan <AP 管理 VLAN>` |
| 訪客裝置可以 ping 到辦公網段 | ★★★★★ VLAN 隔離未生效（同一 VLAN、或 L3 沒設 ACL） | 確認 `show mac address-table` 中訪客 MAC 在 VLAN 40；隔離要在 L3 閘道用 ACL 做，交換器只負責 L2 分段 |
| 刪 VLAN 之後那些埠的機器全部不通 | ★★★★ `no vlan 30` 之後，原本 access vlan 30 的埠變成 inactive（不會自動回到 VLAN 1） | `show vlan brief` 會看不到該 VLAN；重建 VLAN，或把埠改到別的 VLAN |

## 安全性注意事項

> [!danger] ★★★★★ VLAN 是分段，不是隔離
> VLAN 只在 **L2** 把廣播域切開。兩個 VLAN 之間能不能互通，
> 完全取決於 **L3 閘道（路由器／防火牆／L3 交換器）有沒有放行**。
> **「我把訪客切了 VLAN 所以他們進不了內網」是錯的** ——
> 只要 L3 上兩個網段互相路由得到，VLAN 一點隔離作用都沒有。
> 真正的隔離要在閘道上用 ACL／防火牆政策做，
> 見 [[090-02-06-guide-防護-遠端存取安全]]。

| 項目 | 風險 | 做法 | 星級 |
| --- | --- | --- | --- |
| VTP `server`／`client` 模式 | ★★★★★ 一台修訂版號較高的設備可清空全網 VLAN | 一律 `vtp mode transparent`（或 VTPv3 `off`） | ★★★★★ |
| DTP 開著 | ★★★★ 攻擊者把 access 埠協商成 trunk，取得所有 VLAN 流量 | 每個埠明確 `mode access`／`mode trunk` ＋ `switchport nonegotiate` | ★★★★★ |
| native VLAN 是 VLAN 1 | ★★★★ 雙標籤 VLAN hopping 的前提條件 | 改成專屬未用 VLAN（如 999），並從 allowed list 移除 | ★★★★ |
| native VLAN 兩端不一致 | ★★★★ 兩個 VLAN 互串，隔離失效且難察覺 | 兩端統一；監控 `%CDP-4-NATIVE_VLAN_MISMATCH` | ★★★★ |
| trunk allowed 是 1-4094 | ★★★★ 所有 VLAN 都能走上這條線，橫向移動無阻 | 精準列出真正需要的 VLAN | ★★★★ |
| 埠留在 VLAN 1 | ★★★★ VLAN 1 同時跑控制流量，且是攻擊者的預設落腳點 | 未用埠丟 VLAN 999 ＋ `shutdown` | ★★★★ |
| 沒有 BPDU guard | ★★★★ 使用者私接交換器造成迴圈或搶 root bridge | 所有 access 埠 `spanning-tree bpduguard enable` | ★★★★ |
| 沒有 root guard | ★★★ 下游設備搶成 root bridge，流量路徑全變 | 面向下游的埠 `spanning-tree guard root` | ★★★ |
| `vlan dot1q tag native` 未啟用 | ★★★ 雙標籤攻擊仍有殘餘可能 | 支援的機型啟用它 | ★★★ |
| 管理 VLAN 與使用者 VLAN 混用 | ★★★★★ 使用者網段可直接打到交換器管理介面 | 管理走專屬 VLAN 99，並用 ACL 限制來源，見下一篇 | ★★★★★ |

## 速查表

| 指令 / 設定項 | 說明 | 範例 |
| --- | --- | --- |
| `vlan <id>` | 建立／進入 VLAN 設定 ★★★★ | `SW(config)#vlan 30` |
| `name <名稱>` | 命名 VLAN（不可有空格） ★★★ | `SW(config-vlan)#name OFFICE` |
| `no vlan <id>` | ★★★★ 刪除 VLAN（該 VLAN 的埠會變 inactive） | `SW(config)#no vlan 40` |
| `switchport mode access` | 固定為 access ★★★★ | `SW(config-if)#switchport mode access` |
| `switchport access vlan <id>` | 指派 access VLAN ★★★★ | `... access vlan 30` |
| `switchport voice vlan <id>` | 語音 VLAN（IP 電話） ★★★ | `... voice vlan 50` |
| `switchport mode trunk` | 固定為 trunk ★★★★ | `SW(config-if)#switchport mode trunk` |
| `switchport trunk encapsulation dot1q` | ★★★★ 3560／3750 必須先設；2960／9200 沒有此指令 | `... trunk encapsulation dot1q` |
| `switchport trunk native vlan <id>` | ★★★★ 不打標籤的 VLAN，兩端必須一致 | `... trunk native vlan 999` |
| `switchport trunk allowed vlan <list>` | ★★★★★ **覆蓋**整份清單 | `... allowed vlan 20,30,99` |
| `switchport trunk allowed vlan add <id>` | ★★★★★ **新增**（日常變更一律用這個） | `... allowed vlan add 40` |
| `switchport trunk allowed vlan remove <id>` | 移除 ★★★★ | `... allowed vlan remove 1` |
| `switchport trunk allowed vlan all` | 恢復 1-4094 全開 ★★★ | `... allowed vlan all` |
| `switchport trunk allowed vlan none` | ★★★★★ 全部不允許（等同斷線） | `... allowed vlan none` |
| `switchport nonegotiate` | ★★★★ 關閉 DTP（需先明確設模式） | `SW(config-if)#switchport nonegotiate` |
| `vlan dot1q tag native` | ★★★ 連 native VLAN 也打標籤 | `SW(config)#vlan dot1q tag native` |
| `vtp mode transparent` | ★★★★★ 機關環境標準設定 | `SW(config)#vtp mode transparent` |
| `vtp mode off` | VTPv3 才有，比 transparent 更徹底 ★★★ | `SW(config)#vtp mode off` |
| `vtp domain <名稱>` | 改網域名稱（修訂版號會歸 0） ★★★ | `SW(config)#vtp domain NONE` |
| `delete flash:vlan.dat` | ★★★★★ 清空 VLAN 資料庫與 VTP 版號（需 reload） | `SW#delete flash:vlan.dat` |
| `show vlan brief` | VLAN 清單與埠歸屬 ★★★★ | `SW#show vlan brief` |
| `show vlan id 30` | 單一 VLAN 的詳細資訊 ★★★ | `SW#show vlan id 30` |
| `show interfaces trunk` | ★★★★★ trunk 狀態四張表 | `SW#show int trunk` |
| `show interfaces <埠> switchport` | ★★★★ 單一埠的 admin/oper mode 與 DTP 狀態 | `SW#show int gi1/0/1 switchport` |
| `show vtp status` | ★★★★★ 接手設備第一個要看的 | `SW#show vtp status` |
| `show mac address-table interface <埠>` | 該埠學到哪些 MAC、在哪個 VLAN ★★★★ | `SW#show mac add int gi1/0/17` |
| `spanning-tree portfast` | access 埠免除 30 秒等待 ★★★ | `SW(config-if)#spanning-tree portfast` |
| `spanning-tree portfast trunk` | trunk 埠接單一裝置（如 AP）時用 ★★★ | `... portfast trunk` |
| `spanning-tree bpduguard enable` | ★★★★ 防私接交換器 | `... bpduguard enable` |
| `interface range <a> - <b>` | 批次設定 ★★★ | `SW(config)#int range gi1/0/1 - 16` |
| `reload in 5` / `reload cancel` | ★★★★★ 動 trunk 的必備保險 | `SW#reload in 5` |

## 練習題

> [!question]- 練習 1：VTP 風險自檢
> 拿一台測試交換器（或模擬器），完成以下三件事並記錄輸出：
> ① 查出目前的 VTP 模式、網域、修訂版號
> ② 切成 transparent 並確認修訂版號歸零
> ③ 證明切換之後 VLAN 定義出現在 `running-config` 裡了
>
> **參考解答**
>
> ```cisco
> SW#show vtp status | include Operating Mode|Domain Name|Configuration Revision
> VTP Domain Name                 : GOVNET
> VTP Operating Mode                : Server
> Configuration Revision            : 31
>
> SW#configure terminal
> SW(config)#vtp mode transparent
> Setting device to VTP Transparent mode for VLANS.
> SW(config)#end
> SW#show vtp status | include Operating Mode|Configuration Revision
> VTP Operating Mode                : Transparent
> Configuration Revision            : 0
>
> SW#show running-config | begin ^vlan
> vlan 30
>  name OFFICE
> !
> ```
>
> ★★★★ 第三步是關鍵：transparent 模式下 VLAN 進了 `running-config`，
> 所以你的設定檔備份**同時備份了 VLAN**，還原時不用另外處理 `vlan.dat`。

> [!question]- 練習 2：`add` 與覆蓋的差別
> 在測試機上先設 `switchport trunk allowed vlan 10,20,30`，
> 然後分別執行 `switchport trunk allowed vlan 40` 與
> `switchport trunk allowed vlan add 40`，
> 每次都用 `show interfaces trunk` 記錄結果。
>
> **參考解答**
>
> ```cisco
> SW(config-if)#switchport trunk allowed vlan 10,20,30
> SW(config-if)#do show int trunk | begin Vlans allowed on trunk
> Port        Vlans allowed on trunk
> Gi1/0/24    10,20,30
>
> SW(config-if)#switchport trunk allowed vlan 40
> SW(config-if)#do show int trunk | begin Vlans allowed on trunk
> Port        Vlans allowed on trunk
> Gi1/0/24    40                        ← ★★★★★ 10,20,30 全部消失
>
> SW(config-if)#switchport trunk allowed vlan 10,20,30
> SW(config-if)#switchport trunk allowed vlan add 40
> SW(config-if)#do show int trunk | begin Vlans allowed on trunk
> Port        Vlans allowed on trunk
> Gi1/0/24    10,20,30,40               ← ★ 正確
> ```
>
> ★★★★★ 在正式環境，中間那一步就是「全樓斷網」。

> [!question]- 練習 3：DTP 的實際行為
> 用兩台交換器（或模擬器）接一條線，把 A 端設成 `switchport mode dynamic auto`，
> B 端分別設成 `dynamic auto`、`dynamic desirable`、`trunk`，
> 每次都用 `show interfaces <埠> switchport` 觀察 A 端的 `Operational Mode`。
>
> **參考解答**
>
> | B 端設定 | A 端 `Operational Mode` | 說明 |
> | --- | --- | --- |
> | `dynamic auto` | `static access` | ★★★ 兩邊都被動，沒人開口，談不成 trunk |
> | `dynamic desirable` | `trunk` | B 主動邀請，A 接受 |
> | `trunk` | `trunk` | B 已經是 trunk，A 跟著變 |
>
> ★★★★★ 第三列就是攻擊者利用的路徑：他只要讓自己那端「是 trunk」或
> 「dynamic desirable」，你的 access 埠就自己變成 trunk 了。
> 加上 `switchport mode access` ＋ `switchport nonegotiate` 之後，
> 不管 B 端怎麼設，A 端永遠是 `static access`。

> [!question]- 練習 4：讀懂 `show interfaces trunk` 的四張表
> 以下輸出中，VLAN 40 在哪個階段被擋住？下一步該查什麼？
>
> ```cisco
> Port        Vlans allowed on trunk
> Gi1/0/24    20,30,40,99
>
> Port        Vlans allowed and active in management domain
> Gi1/0/24    20,30,40,99
>
> Port        Vlans in spanning tree forwarding state and not pruned
> Gi1/0/24    20,30,99
> ```
>
> **參考解答**
>
> ★★★★ VLAN 40 通過了前兩關（有 allowed、本機也建了這個 VLAN），
> 但在**第三張表消失** → 它在這條 link 上**沒有處於 STP forwarding 狀態**。
>
> 下一步：
>
> ```cisco
> SW#show spanning-tree vlan 40
> ```
>
> 常見原因：這條 link 對 VLAN 40 而言是 STP 阻斷埠（有備援路徑），
> 或被 VTP pruning 剪掉。前者是正常的（另一條路在轉發），
> 後者要檢查 `show vtp status` 的 `VTP Pruning Mode`。
> 見 [[040-01-16-guide-網路設備-鏈路聚合與STP]]。

> [!question]- 練習 5：接手一台來歷不明的交換器
> 同事給你一台從別的機關調撥來的 Catalyst 2960，說「已經清乾淨了」。
> 在把它接上正式網路之前，你要跑哪些指令確認它真的安全？
> 如果不安全，補救的完整程序是什麼？
>
> **參考解答**
>
> **檢查清單**：
>
> ```cisco
> SW#show vtp status
> ! ★★★★★ 看 Operating Mode / Domain Name / Configuration Revision
> SW#show vlan brief
> ! ★★★★ 看有沒有殘留的 VLAN
> SW#show running-config | include vtp|vlan
> SW#show version | include Configuration register
> ! ★★★★ 確認不是 0x2142
> SW#dir flash:
> ! ★★★ 看 vlan.dat 還在不在
> ```
>
> 危險判定：`Operating Mode` 是 `Server`／`Client`
> **且** `Configuration Revision` 大於 0 **且** `Domain Name` 與你的環境相同
> → ★★★★★ **絕對不能接上網路**。
>
> **補救程序**（全程用 console，不接網路線）：
>
> ```cisco
> SW#write erase
> Erasing the nvram filesystem will remove all configuration files! Continue? [confirm]
> [OK]
> SW#delete flash:vlan.dat
> Delete filename [vlan.dat]?
> Delete flash:/vlan.dat? [confirm]
> SW#reload
> System configuration has been modified. Save? [yes/no]: no
> Proceed with reload? [confirm]
> ```
>
> 重開後驗證：
>
> ```cisco
> Switch#show vtp status | include Operating Mode|Domain Name|Configuration Revision
> VTP Domain Name                 : NULL
> VTP Operating Mode                : Server
> Configuration Revision            : 0
> ```
>
> ★★★★★ `Configuration Revision : 0` 才可以接線。
> 接線前再補一步 `vtp mode transparent`，從此免疫。

## 小測驗

Q1. （選擇）以下哪一個指令會把 trunk 的 allowed vlan 清單從 `20,30,99` 變成只剩 `40`？
(A) `switchport trunk allowed vlan add 40`
(B) `switchport trunk allowed vlan 40`
(C) `switchport trunk allowed vlan except 40`
(D) `switchport trunk allowed vlan remove 40`

Q2. （是非）在一台交換器上執行 `write erase` 然後 `reload`，
所有 VLAN 定義與 VTP 修訂版號都會被清除。

Q3. 你把某個 access 埠設成 `switchport mode access` 但沒設 `switchport nonegotiate`。
攻擊者能利用這一點做什麼？

Q4. 這行指令會發生什麼事？
`SW-3F-01(config-if)#switchport trunk allowed vlan none`

Q5. （簡答）native VLAN 是什麼？為什麼機關環境不該用 VLAN 1 當 native VLAN？

Q6. `show interfaces trunk` 的第二張表（`Vlans allowed and active in management domain`）
少了 VLAN 40，但第一張表有。這代表什麼？怎麼修？

Q7. （是非）VTP `client` 模式的交換器不會覆蓋別人的 VLAN 資料庫，所以是安全的。

Q8. 你在 Catalyst 3750 上打 `switchport mode trunk`，
得到 `Command rejected: An interface whose trunk encapsulation is "Auto"...`。
原因是什麼？在 Catalyst 2960-X 上打同樣的指令會有這個問題嗎？

Q9. `show interfaces gi1/0/5 switchport` 顯示
`Administrative Mode: dynamic auto` 但 `Operational Mode: trunk`。
發生了什麼事？這是不是問題？

Q10. 為什麼設定 trunk 時建議「先設 `native vlan` 與 `allowed vlan`，
最後才打 `switchport mode trunk`」？

> [!question]- 測驗答案
> **Q1.** ★★★★★ **(B)**。不加 `add`／`remove` 的 `allowed vlan` 是**整份覆蓋**。
> (A) 會變成 `20,30,40,99`；(C) 會變成 1-4094 除了 40；(D) 沒有效果（清單裡本來就沒有 40）。
> 見「進階設定與調校 → `allowed vlan` 的四個關鍵字」。
>
> **Q2.** ★★★★★ **否。** `write erase` 只清 NVRAM 裡的 `startup-config`。
> VLAN 定義與 VTP 修訂版號存在 **`flash:vlan.dat`**，完全不受影響。
> 必須額外 `delete flash:vlan.dat` 再 `reload`。
> 這正是「回收機一插上就毀掉全網 VLAN」的成因。
> 見「觀念說明 → VLAN 的資料存在兩個地方」。
>
> **Q3.** ★★★★ 這個埠仍在發送 DTP 封包。攻擊者接上一台會回應 DTP 的裝置
> （模式設為 `trunk` 或 `dynamic desirable`），可以把這個埠**協商成 trunk**，
> 從而看到並注入這條線上所有被允許的 VLAN 流量，VLAN 隔離失效。
> 而且 `show running-config` 上這個埠**看起來還是 access**（協商結果不寫進設定檔），
> 極難察覺。解法：`switchport nonegotiate`。
> 見「觀念說明 → DTP」。
>
> **Q4.** ★★★★★ 這條 trunk 從此**不允許任何 VLAN 通過**，等同斷線。
> 如果這是你的上行埠，SSH 會在 Enter 按下的同一瞬間中斷，
> 且下游所有使用者立即斷網。
> 見「進階設定與調校 → `allowed vlan` 的四個關鍵字」。
>
> **Q5.** ★★★★ native VLAN 是 802.1Q trunk 上**唯一不打標籤**傳送的那個 VLAN，
> 預設是 VLAN 1。不該用 VLAN 1 的理由有三：
> ① VLAN 1 同時承載 CDP／STP／VTP／DTP 等控制流量；
> ② 所有埠的預設歸屬都是 VLAN 1，攻擊者最容易落腳；
> ③ ★★★★ 它是**雙標籤 VLAN hopping** 的前提 —— 外層標籤被剝掉後，
> 內層標籤把封包送進目標 VLAN。
> 應改為一個沒有 SVI、沒有使用者的專屬 VLAN（如 999），
> 並從 allowed list 移除。
> 見「觀念說明 → native VLAN」。
>
> **Q6.** ★★★★ 代表**本機沒有建立 VLAN 40**（allowed 允許了一個不存在的 VLAN）。
> 修法：`configure terminal` → `vlan 40` → `name GUEST`。
> 這是排錯黃金三段式的第一關卡點。
> 見「基礎設定 → 步驟 4」。
>
> **Q7.** ★★★★★ **否，這是最危險的誤解之一。**
> `client` 模式確實不會**主動**覆蓋別人，但它**會被覆蓋**，
> 而且更重要的是：**它自己的 VLAN 資料庫仍會參與修訂版號比較並轉發通告**。
> 一台修訂版號很高的 client 接進來，同樣會讓全網同步到它的版本。
> `client` 唯一的差別只是「本機不能手動建 VLAN」。
> 安全的只有 `transparent` 與 `off`。
> 見「觀念說明 → VTP → 四種 VTP 模式」。
>
> **Q8.** ★★★★ 3750／3560 等機型歷史上支援 ISL 與 802.1Q 兩種封裝，
> 預設是 `Auto`，必須先明確指定 `switchport trunk encapsulation dot1q` 才能切 trunk 模式。
> Catalyst 2960-X **不會**有這個問題 —— 它只支援 802.1Q，
> 因此連 `switchport trunk encapsulation` 這個指令都不存在（打了會回 `% Invalid input`）。
> 判斷方式：在 `config-if` 下打 `switchport trunk ?` 看有沒有 `encapsulation` 選項。
> 見「觀念說明 → encapsulation 的機型差異」。
>
> **Q9.** ★★★★ 這代表這個埠**被 DTP 協商成 trunk 了** ——
> 你的設定意圖（Administrative）是「自動」，實際結果（Operational）是 trunk。
> ★★★★★ **這是問題，而且是資安問題**：一個你以為接使用者電腦的埠，
> 現在能看到所有 VLAN 的流量。
> 處理：`switchport mode access` ＋ `switchport access vlan <id>` ＋
> `switchport nonegotiate`，然後確認 `Operational Mode` 變回 `static access`、
> `Negotiation of Trunking` 變成 `Off`。並追查對端接的是什麼設備。
> 見「基礎設定 → 步驟 3」。
>
> **Q10.** ★★★★ 因為 `switchport mode trunk` 一執行，這條 trunk 立刻以
> **預設值**開始運作：allowed vlan 是 **1-4094 全開**、native vlan 是 **1**。
> 在對端已經是 trunk 的情況下，這個瞬間會讓所有 VLAN（含你不想開放的）互通，
> 可能造成非預期的流量互串，並觸發 STP 重新收斂。
> 先把 native 與 allowed 設好，切換模式就是一瞬間、且一切都是預期內的。
> 見「基礎設定 → 步驟 4」。

## 延伸閱讀

- [[040-01-12-guide-Cisco-管理IP與遠端存取]] —— 有了管理 VLAN，接下來設 SVI 與 SSH
- [[040-01-13-guide-Cisco-埠設定與安全]] —— portfast、bpduguard、port-security 的完整說明
- [[040-01-14-svc-Cisco-設定備份與韌體升級]] —— 把 VLAN 設定納入自動備份
- [[040-01-03-guide-網路設備-VLAN概念與規劃]] —— VLAN 該怎麼切、編號怎麼規劃
- [[040-01-06-guide-Juniper-VLAN與Trunk設定]] —— 主線平台的做法（★ 沒有 DTP／VTP 這兩個坑）
- [[040-01-10-cmd-Cisco-IOS-基礎操作]] —— `reload in`、`interface range`、過濾器
- [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]] —— 兩邊指令一頁式對照
- [[040-01-16-guide-網路設備-鏈路聚合與STP]] —— trunk 上的 VLAN 為什麼被阻斷
- [[010-02-16-guide-網概-VLAN與網路分段]] —— 802.1Q 標籤的封包層級說明
