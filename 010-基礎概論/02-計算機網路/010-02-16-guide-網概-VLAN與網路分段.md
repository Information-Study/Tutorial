---
title: "VLAN 與網路分段"
desc: "一台交換器怎麼切成好幾個互不干擾的網路"
aliases: [VLAN, Trunk, Access, 802.1Q, STP, 生成樹, 網路分段]
tags: [群組/基礎概論, 網概/入門, 主題/計算機網路]
category: 計算機網路
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[010-02-05-guide-網概-MAC位址與交換器]]", "[[010-02-06-guide-網概-IP位址與子網路]]"]
updated: 2026-08-29
---

# VLAN 與網路分段

> [!abstract] 這篇你會學到
> - 用**辦公大樓隔間**的比喻理解 VLAN 要解決什麼問題
> - 分辨 **Access 埠**與 **Trunk 埠**，看懂 802.1Q 標籤
> - 知道 **VLAN 間通訊需要什麼**（單臂路由 vs 三層交換器）
> - 理解 **STP 生成樹協定**要防止的「廣播風暴」有多可怕
> - 認識網路分段的**資安價值**，以及怎麼規劃
> - 學會 VLAN 相關的排錯

## 前置知識

- [[010-02-05-guide-網概-MAC位址與交換器]] — 廣播網域的概念
- [[010-02-06-guide-網概-IP位址與子網路]] — 網段規劃

---

## 觀念說明

### 問題：一台交換器就是一個廣播網域

回顧 [[010-02-05-guide-網概-MAC位址與交換器]]：
**交換器切開了碰撞網域，但廣播網域仍然是同一個。**

```
一台 48 埠交換器，接了 48 台設備
→ 全部在同一個廣播網域
→ 任何一次 ARP 廣播，48 台都要處理
```

**這造成三個問題**：

| 問題 | 說明 |
| --- | --- |
| **廣播流量** | 設備越多，廣播越多，浪費頻寬與 CPU |
| **資安** | **一台中毒可以直接攻擊其他 47 台**（同網段不經過路由器，防火牆管不到） |
| **管理** | 印表機、監視器、伺服器、使用者電腦全混在一起 |

### 傳統解法：買更多台交換器（很貴）

```
使用者部門 → 交換器 A（獨立）
伺服器     → 交換器 B（獨立）
訪客       → 交換器 C（獨立）
```

**問題**：
- 每個網段都要**買一台實體交換器**
- 3 樓的使用者與 5 樓的使用者要在同一個網段？**要拉專線**
- 某個網段只有 3 台設備，卻要用掉一台 24 埠交換器 —— **浪費**

### VLAN：用軟體做隔間

**VLAN**（Virtual LAN，虛擬區域網路）
讓你在**一台實體交換器上，邏輯地切出多個獨立的網路**。

> [!example] 核心比喻：辦公大樓的隔間
> **沒有 VLAN**：一個大通鋪，所有部門擠在一起，
> 一個人講話全部的人都聽得到。
>
> **有 VLAN**：用隔板把同一層樓隔成好幾間辦公室。
> - 每間辦公室裡的人可以自由交談
> - **不同辦公室之間聽不到彼此**
> - 要跨辦公室溝通，**必須走走廊（路由器）**，
>   而走廊上可以設警衛（防火牆）
>
> **關鍵**：這些隔板是**軟體設定的，隨時可以改**，
> 不用真的去砌一道牆。

```mermaid
graph TD
    subgraph SW["一台實體交換器"]
        subgraph V10["VLAN 10 - 使用者"]
            P1[Port 1] 
            P2[Port 2]
        end
        subgraph V20["VLAN 20 - 伺服器"]
            P3[Port 3]
            P4[Port 4]
        end
        subgraph V99["VLAN 99 - 訪客"]
            P5[Port 5]
        end
    end
    V10 -.需經路由器.-> R[路由器/防火牆]
    V20 -.需經路由器.-> R
    V99 -.需經路由器.-> R
```

> [!note] VLAN 的三個效果
> 1. **切開廣播網域** —— 每個 VLAN 是獨立的廣播網域
> 2. **邏輯隔離** —— 不同 VLAN 的設備**無法直接通訊**
> 3. **不受實體位置限制** —— 3 樓與 5 樓的設備可以在同一個 VLAN

---

## Access 埠與 Trunk 埠

這是 VLAN 最核心的兩個概念。

| | **Access 埠** | **Trunk 埠** |
| --- | --- | --- |
| 接什麼 | **終端設備**（電腦、印表機、AP） | **交換器 ↔ 交換器**、交換器 ↔ 路由器 |
| 屬於幾個 VLAN | **只有一個** | **多個（甚至全部）** |
| 封包有標籤嗎 | **沒有**（終端設備不懂 VLAN） | **有 802.1Q 標籤** |
| 比喻 | **辦公室的門**（你只能進自己那間） | **走廊**（所有部門的人都在上面走，但身上掛著識別證） |

### 先講三件 JunOS 與 IOS 不一樣的地方

本手冊的交換器主線是 **Juniper JunOS**，Cisco IOS 放在摺疊的對照區塊裡。
後面所有設定範例都建立在這三點上：

| | **Juniper JunOS** | **Cisco IOS** |
| --- | --- | --- |
| 介面命名 | `ge-0/0/5`（**槽/PIC/埠**，**從 0 開始數**） | `GigabitEthernet0/5`（從 1 開始數） |
| 設定何時生效 | **打完還沒生效，要 `commit`** | **打完就生效** |
| VLAN 怎麼指定 | 先定義**名稱**（`vlans USERS vlan-id 10`），介面引用**名稱** | 介面直接寫**號碼** |

> [!warning] 未實機驗證
> 本篇的 JunOS 設定依 Juniper 官方文件撰寫，未在實機驗證。
> 實作前請對照你手上設備的 Junos 版本 —— 特別注意
> **ELS（Enhanced Layer 2 Software）與非 ELS 的語法不同**，
> 本篇一律使用 ELS 語法（現行 EX 系列）。

> [!tip] `commit confirmed` 是改遠端設備的保命符
> ```junos
> user@switch# commit confirmed 5
> ```
> 設定**先套用**，但**如果 5 分鐘內沒有再打一次 `commit`，設備會自動回滾**。
> 萬一你改壞了 Trunk 把自己鎖在門外，等 5 分鐘設備就自己救自己。
>
> 其他每天都會用到的：
> ```junos
> user@switch# show | compare      # 這次改了什麼（還沒生效，先看過再 commit）
> user@switch# show | display set  # 把設定樹轉成 set 指令，方便複製與比對
> user@switch# rollback 0          # 丟掉還沒 commit 的修改
> user@switch# rollback 1          # 退回上一版已 commit 的設定（再 commit 才生效）
> ```
> **IOS 沒有這個機制** —— 打錯一行 ACL 就當場斷線，
> 只能靠 `reload in 5` 這種土法煉鋼的做法先排好定時重開機。

### Access 埠：終端設備接的地方

```junos
# 先建立 VLAN（JunOS 的 VLAN 用「名稱」，vlan-id 只是它的號碼）
set vlans USERS vlan-id 10

# 再設定介面
set interfaces ge-0/0/5 description "3F-A12-會計室王小姐"
set interfaces ge-0/0/5 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/5 unit 0 family ethernet-switching vlan members USERS

# 終端設備的埠：設成 STP 邊緣埠，並開啟 BPDU 保護
set protocols rstp interface ge-0/0/5 edge
set protocols rstp bpdu-block-on-edge
```

> [!info]- Cisco IOS 對照
> ```cisco
> interface GigabitEthernet0/5
>  description ** 3F-A12-會計室王小姐 **
>  switchport mode access
>  switchport access vlan 10        ! 這個埠屬於 VLAN 10
>  spanning-tree portfast           ! 快速啟用（終端設備用）
>  spanning-tree bpduguard enable   ! 防止有人接交換器進來
> ```
> **三個觀念差異**：
> 1. IOS 的 `spanning-tree portfast` 對應 JunOS 的 `edge`；
>    `spanning-tree bpduguard enable` 對應 `bpdu-block-on-edge` ——
>    但 **JunOS 的 `bpdu-block-on-edge` 是全域設定**，一次涵蓋所有 edge 埠，
>    IOS 則是逐埠設（或用 `spanning-tree portfast bpduguard default` 設全域）。
> 2. IOS 直接寫 `switchport access vlan 10`；
>    JunOS 必須先 `set vlans USERS vlan-id 10`，介面再引用名稱 `USERS`。
>    **VLAN 沒先建，介面那行 commit 會直接報錯** —— 這是 JunOS 新手最常撞的牆。
> 3. 這段 JunOS 設定**打完還沒生效**，要 `commit`。

> [!tip] 終端設備完全不知道 VLAN 的存在
> 你的電腦送出一個普通的乙太網路 Frame（**沒有 VLAN 標籤**），
> 交換器收到後，**依照那個埠的設定**，
> 在內部把它標記為「這是 VLAN 10 的流量」。
>
> 送出去給電腦時，交換器會**把標籤拿掉**再送。
>
> **所以電腦完全不用做任何設定** —— 這是 VLAN 好用的原因。

### Trunk 埠：交換器之間的通道

**問題**：兩台交換器之間只有一條線，
但兩邊都有 VLAN 10、20、99 的設備。
**這條線上的封包，怎麼知道自己屬於哪個 VLAN？**

**答案：802.1Q 標籤（VLAN Tag）**。

```
原本的 Frame:
┌─────────┬─────────┬──────┬──────────┬─────┐
│ 目的MAC  │ 來源MAC  │ 類型 │ Payload  │ FCS │
└─────────┴─────────┴──────┴──────────┴─────┘

加上 802.1Q 標籤（4 位元組）:
┌─────────┬─────────┬═══════════┬──────┬──────────┬─────┐
│ 目的MAC  │ 來源MAC  │ 802.1Q 標籤 │ 類型 │ Payload  │ FCS │
└─────────┴─────────┴═══════════┴──────┴──────────┴─────┘
                      └ VLAN ID (12 bit)
                        + 優先序 (3 bit, CoS)
```

| 欄位 | 說明 |
| --- | --- |
| **VLAN ID** | **12 位元 → 1～4094**（0 與 4095 保留） |
| **PCP / CoS** | 3 位元，**服務品質優先序**（0～7，語音通常用 5） |
| TPID | 標示「這是 802.1Q 標籤」（`0x8100`） |

```junos
# Trunk 上要通過的 VLAN，每一個都要先定義
set vlans USERS vlan-id 10
set vlans SERVERS vlan-id 20
set vlans PRINTERS vlan-id 30
set vlans GUEST vlan-id 99
set vlans BLACKHOLE vlan-id 999

# ge-0/0/23 是這台交換器的「第 24 埠」（JunOS 從 0 開始數）
set interfaces ge-0/0/23 description "Trunk to Core Switch"
set interfaces ge-0/0/23 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/23 unit 0 family ethernet-switching vlan members [ USERS SERVERS PRINTERS GUEST BLACKHOLE ]
set interfaces ge-0/0/23 native-vlan-id 999
```

> [!warning] JunOS 的 native VLAN 必須也列在 `vlan members` 裡
> `native-vlan-id 999` 只是說「untagged 的封包算 999」，
> **如果 `BLACKHOLE`（999）沒有出現在 `vlan members` 清單中，untagged 封包會被丟掉**。
> 這一點與 IOS 不同，是 JunOS Trunk 設定最常見的坑。

> [!info]- Cisco IOS 對照
> ```cisco
> interface GigabitEthernet0/24
>  description ** Trunk to Core Switch **
>  switchport mode trunk
>  switchport trunk allowed vlan 10,20,30,99     ! 只允許這些 VLAN 通過
>  switchport trunk native vlan 999              ! 見下方警告
> ```
> **兩個觀念差異**：
> 1. **埠號差一**：IOS 的 `Gi0/24` 是第 24 埠，JunOS 要寫 `ge-0/0/23` 才是第 24 埠。
> 2. IOS 的 native VLAN **不必**出現在 `switchport trunk allowed vlan` 清單裡也能運作；
>    JunOS 的 `native-vlan-id` **一定要**在 `vlan members` 裡。

> [!warning] Native VLAN：Trunk 上唯一「不打標籤」的 VLAN
> 802.1Q 規定 Trunk 上有一個 **Native VLAN**，
> 它的流量**不加標籤**就送出去（為了相容不懂 VLAN 的舊設備）。
>
> **預設是 VLAN 1** —— **這是資安問題**。
>
> **VLAN Hopping 攻擊**：
> 攻擊者送出**已經帶有 VLAN 標籤**的封包，
> 如果他所在的 VLAN 剛好是 Native VLAN（沒標籤），
> 交換器會把他的封包當成 Trunk 流量，
> **讓他跳到另一個 VLAN**。
>
> **防護**：
> ```junos
> # 1. Native VLAN 改成一個沒有任何設備的閒置 VLAN（記得它也要在 members 裡）
> set interfaces ge-0/0/23 native-vlan-id 999
> set interfaces ge-0/0/23 unit 0 family ethernet-switching vlan members BLACKHOLE
>
> # 2. 明確限制 Trunk 能通過的 VLAN（沒列到的就過不去）
> set interfaces ge-0/0/23 unit 0 family ethernet-switching vlan members [ USERS SERVERS PRINTERS ]
>
> # 3. 所有 Access 埠明確設為 access 模式，不要留白讓平台預設決定
> set interfaces interface-range USER-PORTS member-range ge-0/0/0 to ge-0/0/19
> set interfaces interface-range USER-PORTS unit 0 family ethernet-switching interface-mode access
> set interfaces interface-range USER-PORTS unit 0 family ethernet-switching vlan members USERS
> ```
> **JunOS 沒有 DTP**，介面不會自己協商變成 Trunk，
> 所以沒有「關閉自動協商」這個步驟 —— 少一個要防的洞。
>
> > [!info]- Cisco IOS 對照
> > ```cisco
> > ! 1. Native VLAN 改成一個沒有任何設備的閒置 VLAN
> > switchport trunk native vlan 999
> >
> > ! 2. 明確限制 Trunk 允許的 VLAN
> > switchport trunk allowed vlan 10,20,30
> >
> > ! 3. 所有 Access 埠明確設為 access 模式，關閉自動協商
> > interface range Gi0/1 - 20
> >  switchport mode access
> >  switchport nonegotiate          ! 關閉 DTP，防止被誘導成 Trunk
> > ```
> > IOS 多了第 3 步的 `switchport nonegotiate`，因為 IOS 的埠預設會跑 DTP。
> > JunOS 的 `interface-range` 則對應 IOS 的 `interface range`，
> > 差別是 JunOS 的介面範圍要**先取名字**，之後所有共通設定都掛在那個名字底下。

> [!danger] DTP：JunOS 沒有這個東西，但你的網路裡很可能有 Cisco
> **JunOS 不支援 DTP（動態 Trunk 協定）** ——
> Juniper 的介面不會自己協商成 Trunk，你沒寫 `interface-mode trunk` 它就不是 Trunk。
> 這一點 JunOS 天生就比較安全。
>
> **但只要網路裡混有一台 Cisco，這個風險就存在**：
> Cisco 的埠預設是 `dynamic auto` 或 `dynamic desirable`，
> **會自動協商要不要變成 Trunk**。
> 攻擊者只要送出 DTP 封包，
> **就能讓自己接的那個埠變成 Trunk，看到所有 VLAN 的流量**。
>
> **JunOS 這邊該做的**：所有接終端設備的埠都明確寫出模式與所屬 VLAN，
> 不要空著讓平台預設決定。
> ```junos
> set interfaces ge-0/0/5 unit 0 family ethernet-switching interface-mode access
> set interfaces ge-0/0/5 unit 0 family ethernet-switching vlan members USERS
> ```
>
> > [!info]- Cisco IOS 對照
> > ```cisco
> > switchport mode access
> > switchport nonegotiate
> > ```
> > `switchport nonegotiate` 就是**關掉 DTP**。
> > JunOS 沒有對應指令，因為它根本不跑 DTP —— 這是少數
> > 「不用設定就比較安全」的地方。

---

## VLAN 間通訊

> [!note] VLAN 之間預設「完全不通」
> 這是重點也是價值所在。
>
> VLAN 10 的電腦要連 VLAN 20 的伺服器，
> **必須經過一個第 3 層的設備（路由器或三層交換器）**。
>
> **而這正是資安控制點** —— 你可以在那裡放防火牆規則。

### 方案一：單臂路由（Router on a Stick）

用**一台路由器 + 一條 Trunk 線**，
在路由器上建立多個**子介面**，每個對應一個 VLAN。

```mermaid
graph LR
    R["路由器<br/>ge-0/0/0.10 = 192.168.10.1<br/>ge-0/0/0.20 = 192.168.20.1<br/>ge-0/0/0.99 = 192.168.99.1"]
    R ---|"一條 Trunk"| SW["交換器"]
    SW --- V10["VLAN 10 設備"]
    SW --- V20["VLAN 20 設備"]
    SW --- V99["VLAN 99 設備"]
```

```junos
# 路由器（MX / SRX）上：實體介面先開啟 VLAN 標籤功能
set interfaces ge-0/0/0 vlan-tagging

# 每個 VLAN 一個邏輯單元（unit），unit 編號習慣寫得跟 VLAN ID 一樣
set interfaces ge-0/0/0 unit 10 vlan-id 10
set interfaces ge-0/0/0 unit 10 family inet address 192.168.10.1/24

set interfaces ge-0/0/0 unit 20 vlan-id 20
set interfaces ge-0/0/0 unit 20 family inet address 192.168.20.1/24
```

> [!info]- Cisco IOS 對照
> ```cisco
> ! 路由器上
> interface GigabitEthernet0/0.10
>  encapsulation dot1Q 10
>  ip address 192.168.10.1 255.255.255.0
> !
> interface GigabitEthernet0/0.20
>  encapsulation dot1Q 20
>  ip address 192.168.20.1 255.255.255.0
> ```
> **三個觀念差異**：
> 1. IOS 建的是**子介面**（`Gi0/0.10`）並在上面寫 `encapsulation dot1Q 10`；
>    JunOS 建的是**邏輯單元 unit**，而且要**先在實體介面開 `vlan-tagging`**，
>    否則那些 unit 不會生效。
> 2. **unit 編號與 vlan-id 是兩件不同的事**，只是慣例寫成一樣。
>    真正決定標籤的是 `vlan-id 10` 那一行，不是 `unit 10`。
> 3. 遮罩寫法：JunOS 一律用 `/24`，IOS 用 `255.255.255.0`。

| 優點 | 缺點 |
| --- | --- |
| **便宜**（只要一台路由器） | **所有 VLAN 間流量都擠在同一條線上** |
| 設定簡單 | 那條線容易成為瓶頸 |
| 適合小型網路 | 路由器的轉送速度較慢（軟體） |

### 方案二：三層交換器（JunOS 叫 IRB，Cisco 叫 SVI）

在交換器上直接建立一個「VLAN 的三層介面」，由交換器**用硬體 ASIC 做路由**。

- **JunOS**：**IRB**（Integrated Routing and Bridging，整合路由與橋接），介面叫 `irb.10`
- **Cisco**：**SVI**（Switched Virtual Interface），介面叫 `Vlan10`

名字不同，做的事完全一樣。

```junos
# 三層交換器上：建 VLAN → 綁 irb 介面 → 給 irb 介面 IP
set vlans USERS vlan-id 10
set vlans USERS l3-interface irb.10
set interfaces irb unit 10 family inet address 192.168.10.1/24

set vlans SERVERS vlan-id 20
set vlans SERVERS l3-interface irb.20
set interfaces irb unit 20 family inet address 192.168.20.1/24
```

> [!tip] JunOS 不需要「啟用路由」這一行
> IOS 上最常被漏掉的 `ip routing`，**JunOS 沒有對應指令** ——
> 兩個 irb 介面之間預設就會互相路由，設好 IP 就通了。
>
> 但 JunOS 有另一個要注意的：
> **`irb.10` 要等 VLAN 10 裡至少有一個成員埠 up，它才會 up**。
> 全新設定好卻 ping 不到閘道時，先看那個 VLAN 有沒有活著的埠。

> [!info]- Cisco IOS 對照
> ```cisco
> ! 三層交換器上
> ip routing                          ! 啟用路由功能（很多人忘記這行！）
> !
> interface Vlan10
>  ip address 192.168.10.1 255.255.255.0
> !
> interface Vlan20
>  ip address 192.168.20.1 255.255.255.0
> ```
> **兩個觀念差異**：
> 1. **`ip routing` 是 IOS 特有的開關**，不打這行 SVI 之間不會路由 ——
>    這是 IOS 上最經典的疏漏。JunOS 沒有這個開關。
> 2. IOS 的 `interface Vlan10` 一寫下去就自動對應 VLAN 10；
>    JunOS 要**明確用 `set vlans USERS l3-interface irb.10` 把兩者綁起來**，
>    `irb` 的 unit 編號和 VLAN ID 並沒有自動關係（只是慣例對齊）。

| 優點 | 缺點 |
| --- | --- |
| **極快**（硬體轉送，線速） | 較貴 |
| 埠數多 | 進階功能（NAT、VPN）較少 |
| **企業網路的標準做法** | |

> [!tip] 典型的企業架構
> ```
> 網際網路
>     │
> [防火牆]  ← 對外的 NAT、VPN、進階過濾
>     │
> [三層核心交換器]  ← 內部 VLAN 間高速路由 + ACL
>     ├── 二層交換器（1F）
>     ├── 二層交換器（2F）
>     └── 二層交換器（3F）
> ```
>
> **內部 VLAN 間走三層交換器**（快、埠多）；
> **對外走防火牆**（功能多、可深度檢查）。
>
> 見 [[040-01-01-guide-網路設備-網路架構基礎]]。

---

## STP：防止廣播風暴

### 問題：迴圈會讓網路瞬間癱瘓

```mermaid
graph LR
    SW1[交換器 1] --- SW2[交換器 2]
    SW2 --- SW3[交換器 3]
    SW3 --- SW1
```

> [!danger] 為什麼迴圈這麼可怕
> **一個廣播封包（例如一次 ARP 查詢）進入迴圈後**：
>
> 1. 交換器 1 收到 → 從所有其他埠送出
> 2. 交換器 2 與 3 收到 → 各自再從所有埠送出
> 3. 交換器 1 又收到（兩份）→ 再送出
> 4. **封包數量呈指數成長**
>
> **而且第 2 層的 Frame 沒有 TTL** ——
> 不像 IP 封包會遞減後死掉，**Frame 會永遠循環下去**。
>
> **結果（幾秒內發生）**：
> - 頻寬瞬間被 100% 佔滿
> - 交換器 CPU 100%，**完全失去回應**
> - **MAC 表不斷震盪**（同一個 MAC 一直從不同埠出現）
> - **整個網路完全癱瘓**
>
> 這叫 **廣播風暴（Broadcast Storm）**。

> [!warning] 最常見的成因不是設計錯誤，而是「有人接錯線」
> **真實案例的典型情境**：
> - 同仁想「多一個網路孔」，把一條網路線的兩端插進牆上兩個網路孔
> - 有人把小型交換器的兩個埠接在一起
> - 整理機櫃時不小心接錯
>
> **症狀**：所有交換器的**指示燈同步狂閃**，整層樓網路癱瘓。

### STP 的解法：邏輯上「切斷」一條路

**STP**（Spanning Tree Protocol，生成樹協定）是
「**OSI 第 2 層的協定，一般在交換器上執行**」，
目的是「**防止在網路拓樸中出現迴圈進而產生廣播風暴**」。

```mermaid
graph LR
    SW1[交換器 1<br/>Root Bridge] --- SW2[交換器 2]
    SW2 --- SW3[交換器 3]
    SW3 -.->|"被 STP 阻斷<br/>Blocking"| SW1
```

**運作原理**：

| 步驟 | 說明 |
| --- | --- |
| 1 | 交換器之間交換 **BPDU** 訊息 |
| 2 | 選出一台 **Root Bridge**（根橋，優先序最小的） |
| 3 | 每台交換器算出到 Root 的最短路徑 |
| 4 | **把會造成迴圈的埠設為 Blocking（阻斷）** |
| 5 | 主線路斷掉時，**自動把備用埠改為 Forwarding** |

> [!tip] STP 的價值不只是防迴圈，還有「自動備援」
> 你可以**刻意接兩條線**做冗餘：
> - 平常 STP 會阻斷其中一條
> - **主線斷了，STP 自動啟用備用線路**
>
> 「確保網路的拓樸被重新計算，如此一來就不會讓部分的問題影響整個網路的連通。」

### STP 的版本

| 版本 | 標準 | 收斂時間 | 說明 |
| --- | --- | --- | --- |
| STP | 802.1D | **30～50 秒** | 原始版本，太慢 |
| **RSTP** | **802.1w** | **1～6 秒** | **快速生成樹，現代標準** |
| MSTP | 802.1s | 快 | 多個 VLAN 共用一棵樹，節省資源 |
| **VSTP** | **Juniper** | 快 | **每個 VLAN 一棵樹**，與 Cisco PVST+ 相容 |
| PVST+ / Rapid-PVST+ | Cisco | 快 | **每個 VLAN 一棵樹**，可做流量負載分擔 |

> [!warning] 傳統 STP 的 30～50 秒收斂太慢
> 主線斷掉後，要等 30～50 秒 STP 才會啟用備用路徑 ——
> 這段時間網路是**完全不通**的。
>
> **現代網路應該使用 RSTP（802.1w）** ——
> Juniper EX 系列**出廠預設就是 RSTP**，
> Cisco 則要明確下 `spanning-tree mode rapid-pvst` 才會用快的。

### 必做的 STP 保護設定

```junos
# 1. 使用快速版本（EX 系列預設就跑 RSTP，這裡明確寫出來）
set protocols rstp

# 2. 明確指定 Root Bridge（不要讓它隨機選）
#    數字越小越優先，必須是 4096 的倍數
set protocols rstp bridge-priority 4096

# 3. 接使用者的埠：邊緣埠 + BPDU 保護
set interfaces interface-range USER-PORTS member-range ge-0/0/0 to ge-0/0/19
set interfaces interface-range USER-PORTS unit 0 family ethernet-switching interface-mode access
set protocols rstp interface ge-0/0/0 edge
set protocols rstp interface ge-0/0/1 edge
# （其餘使用者埠比照辦理，逐埠列出）
set protocols rstp bpdu-block-on-edge        # 邊緣埠收到 BPDU 就把它關掉

# 4. 廣播風暴抑制
set forwarding-options storm-control-profiles SC-5 all bandwidth-percentage 5
set forwarding-options storm-control-profiles SC-5 action-shutdown   # 不加這行就只丟封包
set interfaces interface-range USER-PORTS unit 0 family ethernet-switching storm-control SC-5
```

> [!warning] 未實機驗證
> 本段 JunOS 設定依 Juniper 官方文件撰寫，未在實機驗證。
> 另外，**`interface-range` 的名稱能不能直接用在 `protocols rstp interface` 底下，
> 各版本行為不一致** —— 保險起見，`edge` 這類 STP 設定請逐埠列出。

> [!tip] 被 BPDU Guard 關掉的埠怎麼救回來
> ```junos
> user@switch> clear ethernet-switching bpdu-error interface ge-0/0/5
> ```
> 或事先設定自動恢復：
> ```junos
> set protocols rstp bpdu-block-on-edge disable-timeout 300
> ```
> 300 秒後自動重新啟用該埠 —— 這樣不必為了每次誤觸都跑一趟現場。

> [!info]- Cisco IOS 對照
> ```cisco
> ! 1. 使用快速版本
> spanning-tree mode rapid-pvst
>
> ! 2. 明確指定 Root Bridge（不要讓它隨機選）
> spanning-tree vlan 10,20,30 root primary      ! 在核心交換器上
>
> ! 3. 接使用者的埠：PortFast + BPDU Guard
> interface range GigabitEthernet0/1 - 20
>  switchport mode access
>  spanning-tree portfast
>  spanning-tree bpduguard enable       ! 收到 BPDU 就關閉該埠
>
> ! 4. 廣播風暴抑制
> interface range GigabitEthernet0/1 - 20
>  storm-control broadcast level 5.00   ! 廣播超過 5% 頻寬就抑制
>  storm-control action shutdown        ! 或直接關埠
> ```
> **三個觀念差異**：
> 1. **每 VLAN 一棵樹 vs 整台一棵樹**：IOS 的 `rapid-pvst` 是每個 VLAN 各跑一棵樹；
>    JunOS 的 `rstp` 是**整台只有一棵樹**。
>    要做到「每 VLAN 一棵樹」，JunOS 要改用 **VSTP**
>    （`set protocols vstp vlan USERS bridge-priority 4096`），它與 Cisco PVST+ 相容。
> 2. IOS 的 `root primary` 會**自動幫你算出一個夠小的優先序**；
>    JunOS 要自己填 `bridge-priority`（4096 的倍數）。
> 3. IOS 的 BPDU Guard 是**逐埠**設定；
>    JunOS 的 `bpdu-block-on-edge` 是**全域一次涵蓋所有 edge 埠**。

> [!tip] BPDU Guard 是防止「有人接錯線」的關鍵
> **PortFast** 讓終端設備的埠跳過 STP 的等待，插上就能用（省 30 秒）。
>
> 但這也帶來風險：如果有人在那個埠接了一台交換器，就可能形成迴圈。
>
> **BPDU Guard 的邏輯很簡單**：
> 「這個埠應該接終端設備，**終端設備不會發 BPDU**。
> 所以**如果收到 BPDU，代表有人接了交換器 → 立刻關閉這個埠**。」
>
> **PortFast + BPDU Guard 應該一起設定在所有使用者埠上。**
> 這一組設定能防止絕大多數的意外迴圈事故。

---

## 網路分段的資安價值

> [!note] 這是 VLAN 最重要的用途
> 分段的核心價值是**限制「橫向移動（Lateral Movement）」**。
>
> **沒有分段**：
> ```
> 一台電腦中了勒索軟體
>   → 同網段的 200 台機器全部可以直接連到
>   → 幾小時內全部被加密
> ```
>
> **有分段**：
> ```
> 一台電腦中了勒索軟體
>   → 只能影響同 VLAN 的 50 台
>   → 要跨到伺服器 VLAN 必須經過防火牆
>   → 防火牆只開放 443，勒索軟體用的 445 被擋
>   → 損害被控制住
> ```

### 典型的分段規劃

| VLAN | 用途 | 可以連到哪裡 |
| --- | --- | --- |
| **10** | 使用者電腦 | 網際網路、伺服器的特定埠 |
| **20** | 伺服器 | 網際網路（受限）、資料庫 VLAN |
| **30** | 資料庫 | **只接受伺服器 VLAN 的連線**，不能主動對外 |
| **40** | 印表機／IoT | **只能連印表機伺服器**，不能上網 |
| **50** | 監視系統 | 只能連 NVR |
| **60** | VoIP 電話 | 只能連話務伺服器（並設 QoS 優先序） |
| **99** | 訪客 | **只能上網，完全不能碰內部** |
| **100** | **網路設備管理** | **最嚴格** —— 只允許特定跳板機存取 |
| **999** | 未使用（Native VLAN / 黑洞） | 什麼都不通 |

> [!danger] 管理 VLAN 是最高價值的目標
> **VLAN 100（網路設備管理）**包含：
> 交換器、防火牆、AP 控制器、**伺服器的 iDRAC/iLO/IPMI**、UPS 管理卡。
>
> 攻下這裡等於**完全控制整個網路與所有伺服器**
> （IPMI 可以在作業系統關機時開關機、掛載虛擬光碟）。
>
> **必做**：
> 1. **絕對不能連到網際網路**
> 2. **只允許從特定的跳板機（Bastion）存取**
> 3. 所有管理介面**改掉預設密碼**、啟用 MFA
> 4. **完整的存取日誌**
> 5. 韌體定期更新
>
> 見 [[040-01-12-guide-Cisco-管理IP與遠端存取]] 與 [[090-05-12-guide-資安設備-零信任架構與微分段]]。

> [!warning] 「切了 VLAN」不等於「有資安」
> 這是最常見的誤區。
>
> 如果你切了 5 個 VLAN，
> 但**三層交換器上完全沒有 ACL，所有 VLAN 之間互通** ——
> 那你只是把一個大廣播網域切成五個小的，
> **資安效果幾乎是零**。
>
> **真正的分段 = VLAN + 明確的存取控制規則**。
>
> ```junos
> # 範例：訪客 VLAN 只能上網，不能碰內部
> set firewall family inet filter GUEST-OUT term BLOCK-INTERNAL from source-address 192.168.99.0/24
> set firewall family inet filter GUEST-OUT term BLOCK-INTERNAL from destination-address 10.0.0.0/8
> set firewall family inet filter GUEST-OUT term BLOCK-INTERNAL from destination-address 192.168.0.0/16
> set firewall family inet filter GUEST-OUT term BLOCK-INTERNAL then discard
> set firewall family inet filter GUEST-OUT term ALLOW-REST then accept
>
> # 套在訪客 VLAN 的 irb 介面上，方向 input（從訪客進來的方向）
> set interfaces irb unit 99 family inet filter input GUEST-OUT
> ```
> **JunOS 的 filter 是「由上往下，第一個命中的 term 就結束」**，順序決定一切；
> 而且**沒被任何 term 命中的封包會被隱含丟棄**，
> 所以最後一定要補一個 `then accept` 的 term，否則訪客連網際網路都上不了。
>
> > [!info]- Cisco IOS 對照
> > ```cisco
> > ! 範例：訪客 VLAN 只能上網，不能碰內部
> > ip access-list extended GUEST-OUT
> >  deny   ip 192.168.99.0 0.0.0.255 10.0.0.0 0.255.255.255
> >  deny   ip 192.168.99.0 0.0.0.255 192.168.0.0 0.0.255.255
> >  permit ip 192.168.99.0 0.0.0.255 any
> > !
> > interface Vlan99
> >  ip access-group GUEST-OUT in
> > ```
> > **兩個觀念差異**：
> > 1. IOS 用**反遮罩（wildcard mask）** `0.0.0.255`；JunOS 直接寫 `/24`。
> > 2. IOS 一條 ACE 就是一列；JunOS 一個 term 可以有多個 `from` 條件，
> >    **同類型的條件（多個 destination-address）是「或」，不同類型之間是「且」**。

---

## 完整實戰範例

### 在 Linux 上使用 VLAN

Linux 主機也可以直接處理 802.1Q 標籤（常用於虛擬化主機）。

```bash
# 載入 8021q 模組
$ sudo modprobe 8021q

# 在 eth0 上建立 VLAN 10 的子介面
$ sudo ip link add link eth0 name eth0.10 type vlan id 10
$ sudo ip addr add 192.168.10.50/24 dev eth0.10
$ sudo ip link set eth0.10 up

# 建立 VLAN 20
$ sudo ip link add link eth0 name eth0.20 type vlan id 20
$ sudo ip addr add 192.168.20.50/24 dev eth0.20
$ sudo ip link set eth0.20 up

# 查看
$ ip -d link show eth0.10
5: eth0.10@eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    vlan protocol 802.1Q id 10 <REORDER_HDR>
                            ^^ VLAN ID

$ ip addr show | grep -A2 'eth0\.'
```

**永久設定（netplan）**：

```yaml
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: no
  vlans:
    eth0.10:
      id: 10
      link: eth0
      addresses: [192.168.10.50/24]
      routes:
        - to: default
          via: 192.168.10.1
    eth0.20:
      id: 20
      link: eth0
      addresses: [192.168.20.50/24]
```

> [!tip] 這在虛擬化主機上很常用
> Proxmox VE 或 VMware 主機接一條 **Trunk 線**，
> 然後把不同的 VM 指派到不同的 VLAN ——
> 一條實體線就能服務所有 VLAN。
>
> 見 `40-虛擬化平台` 章節。

### 抓帶 VLAN 標籤的封包

```bash
# 抓所有帶 VLAN 標籤的封包
$ sudo tcpdump -i eth0 -e -n vlan

10:23:45.123 00:1a:2b:3c:4d:5e > 00:11:22:33:44:55,
  ethertype 802.1Q (0x8100), length 102: vlan 10, p 0,
                                          ^^^^^^^ VLAN ID = 10
  ethertype IPv4 (0x0800), 192.168.10.50 > 192.168.10.1: ICMP echo request

# 只抓特定 VLAN
$ sudo tcpdump -i eth0 -n vlan 20
```

> [!tip] 這是驗證 Trunk 設定的最佳方法
> 在 Trunk 線上抓封包，你應該看到**多個不同 VLAN ID** 的流量。
>
> 如果只看到一個 VLAN，代表：
> - `switchport trunk allowed vlan` 設得太窄
> - 或那個埠根本不是 Trunk

### 交換器上的完整設定範例

```junos
# ===== 建立 VLAN =====
set vlans USERS vlan-id 10
set vlans SERVERS vlan-id 20
set vlans GUEST vlan-id 99
set vlans BLACKHOLE vlan-id 999

# ===== 使用者埠（Access，ge-0/0/0 ～ ge-0/0/19）=====
set interfaces interface-range USER-PORTS member-range ge-0/0/0 to ge-0/0/19
set interfaces interface-range USER-PORTS description "User Access Ports"
set interfaces interface-range USER-PORTS unit 0 family ethernet-switching interface-mode access
set interfaces interface-range USER-PORTS unit 0 family ethernet-switching vlan members USERS
set interfaces interface-range USER-PORTS unit 0 family ethernet-switching storm-control SC-5

# 廣播風暴抑制：超過 5% 頻寬就丟
set forwarding-options storm-control-profiles SC-5 all bandwidth-percentage 5

# STP 邊緣埠 + BPDU 保護（逐埠列出，此處只示範前兩埠）
set protocols rstp interface ge-0/0/0 edge
set protocols rstp interface ge-0/0/1 edge
set protocols rstp bpdu-block-on-edge

# 埠上最多學 2 個 MAC，超過就丟（相當於 IOS 的 port-security）
set switch-options interface ge-0/0/0 interface-mac-limit 2 packet-action drop
set switch-options interface ge-0/0/1 interface-mac-limit 2 packet-action drop

# ===== 未使用的埠 =====
set interfaces interface-range UNUSED member-range ge-0/0/20 to ge-0/0/22
set interfaces interface-range UNUSED description "UNUSED"
set interfaces interface-range UNUSED unit 0 family ethernet-switching interface-mode access
set interfaces interface-range UNUSED unit 0 family ethernet-switching vlan members BLACKHOLE
set interfaces ge-0/0/20 disable
set interfaces ge-0/0/21 disable
set interfaces ge-0/0/22 disable

# ===== Trunk 埠（ge-0/0/23 就是第 24 埠）=====
set interfaces ge-0/0/23 description "Trunk to Core"
set interfaces ge-0/0/23 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/23 unit 0 family ethernet-switching vlan members [ USERS SERVERS GUEST BLACKHOLE ]
set interfaces ge-0/0/23 native-vlan-id 999

# ===== STP =====
set protocols rstp bridge-priority 4096
```

**存檔（一定要做，而且遠端作業請先用 `commit confirmed`）**：

```junos
user@switch# show | compare        # 先看清楚這次改了什麼
user@switch# commit confirmed 5    # 先套用，5 分鐘內沒再 commit 就自動回滾
# ...確認自己還連得上、網路正常...
user@switch# commit                # 確認保留
```

> [!info]- Cisco IOS 對照
> ```cisco
> ! ===== 建立 VLAN =====
> vlan 10
>  name USERS
> vlan 20
>  name SERVERS
> vlan 99
>  name GUEST
> vlan 999
>  name BLACKHOLE
>
> ! ===== 使用者埠（Access）=====
> interface range GigabitEthernet0/1 - 20
>  description ** User Access Ports **
>  switchport mode access
>  switchport access vlan 10
>  switchport nonegotiate                  ! 關閉 DTP
>  spanning-tree portfast
>  spanning-tree bpduguard enable
>  storm-control broadcast level 5.00
>  switchport port-security
>  switchport port-security maximum 2
>  switchport port-security violation restrict
>
> ! ===== 未使用的埠 =====
> interface range GigabitEthernet0/21 - 22
>  description ** UNUSED **
>  switchport access vlan 999
>  shutdown
>
> ! ===== Trunk 埠 =====
> interface GigabitEthernet0/24
>  description ** Trunk to Core **
>  switchport mode trunk
>  switchport trunk allowed vlan 10,20,99
>  switchport trunk native vlan 999        ! 不要用預設的 VLAN 1
>  switchport nonegotiate
>
> ! ===== STP =====
> spanning-tree mode rapid-pvst
> spanning-tree vlan 10,20,99 priority 4096   ! 若這是核心交換器
> ```
> **對照重點**：
> - `switchport port-security maximum 2` → `interface-mac-limit 2 packet-action drop`
> - `storm-control broadcast level 5.00` → `storm-control-profiles ... bandwidth-percentage 5`
> - `spanning-tree vlan ... priority 4096` → `protocols rstp bridge-priority 4096`
>   （要做到每 VLAN 一棵樹才需要換成 `protocols vstp`）
> - IOS 打完就生效，**沒有 commit 這一步**，也沒有 `commit confirmed` 的自動回滾。

### 驗證指令

> [!warning] 未實機驗證
> 以下指令依 Juniper 官方文件整理，**輸出為示意格式**，未在實機驗證。
> 欄位寬度與細部欄位會隨 Junos 版本與機型不同。

```junos
# 看 VLAN 與埠的對應（星號代表該介面目前是 up）
user@switch> show vlans
Routing instance     VLAN name     Tag     Interfaces
default-switch       USERS         10
                                           ge-0/0/0.0*
                                           ge-0/0/1.0*
default-switch       SERVERS       20
                                           ge-0/0/10.0*
default-switch       GUEST         99
                                           ge-0/0/17.0
default-switch       BLACKHOLE     999
                                           ge-0/0/23.0*

# 看每個埠是 access 還是 trunk、屬於哪些 VLAN、有沒有被 STP 擋住
user@switch> show ethernet-switching interfaces
Interface    State    VLAN members    Tag    Tagging    Blocking
ge-0/0/5.0   up       USERS           10     untagged   unblocked
ge-0/0/23.0  up       USERS           10     tagged     unblocked
                      SERVERS         20     tagged     unblocked
                      BLACKHOLE       999    untagged   unblocked

# 看 Trunk 的詳細狀態（含 native VLAN）
user@switch> show interfaces ge-0/0/23 extensive

# 看 STP：誰是 Root、我到 Root 的成本
user@switch> show spanning-tree bridge

# 看每個埠的 STP 角色與狀態（FWD 轉送 / BLK 阻斷）
user@switch> show spanning-tree interface

# 看 MAC 表（相當於 IOS 的 show mac address-table）
user@switch> show ethernet-switching table

# 看三層介面（irb）
user@switch> show interfaces terse | match irb

# 把某個埠的設定用 set 格式印出來，最好複製也最好比對
user@switch> show configuration interfaces ge-0/0/5 | display set
```

> [!tip] `| display set` 是 JunOS 最實用的一招
> Junos 預設用階層式的大括號顯示設定，看得懂但不好複製。
> 加上 `| display set` 就會攤平成一行一行的 `set` 指令 ——
> **貼到另一台設備上就能直接跑**，也方便用 diff 比對兩台設備的差異。

> [!info]- Cisco IOS 對照
> ```cisco
> ! 看 VLAN 與埠的對應
> switch# show vlan brief
> VLAN Name       Status    Ports
> ---- ---------- --------- -------------------------------
> 10   USERS      active    Gi0/1, Gi0/2, Gi0/3, ...
> 20   SERVERS    active    Gi0/11, Gi0/12
> 99   GUEST      active    Gi0/18
> 999  BLACKHOLE  active    Gi0/21, Gi0/22
>
> ! 看 Trunk 狀態
> switch# show interfaces trunk
> Port      Mode  Encapsulation  Status    Native vlan
> Gi0/24    on    802.1q         trunking  999
> Port      Vlans allowed on trunk
> Gi0/24    10,20,99
>
> ! 看 STP 狀態
> switch# show spanning-tree vlan 10
> VLAN0010
>   Root ID    Priority 4106
>              Address  0011.2233.4455
>              This bridge is the root          ← 我是 Root
> Interface     Role Sts Cost  Prio.Nbr Type
> Gi0/24        Desg FWD 4     128.24   P2p
> Gi0/23        Altn BLK 4     128.23   P2p    ← 被阻斷（防迴圈）
>                    ^^^
>
> ! 看某個埠的詳細設定
> switch# show interfaces GigabitEthernet0/5 switchport
> ```
> **一個觀念差異**：IOS 的 `show` 指令在特權模式（`switch#`）下打；
> JunOS 的 `show` 指令在**操作模式**（`user@switch>`）下打，
> **設定模式（`user@switch#`）裡的 `show` 是看設定，不是看狀態** ——
> 在設定模式下要看狀態，要在指令前加 `run`，例如 `run show vlans`。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法（JunOS） |
| --- | --- | --- |
| 電腦拿不到 IP（`169.254.x.x`） | **接到錯誤的 VLAN**（沒有 DHCP） | `show ethernet-switching interfaces` 檢查該埠的 VLAN |
| **設定打完了卻完全沒作用** | **忘了 `commit`** | `commit`（JunOS 的頭號新手陷阱） |
| 介面那行 commit 直接報錯 | **引用了還沒建立的 VLAN 名稱** | 先 `set vlans <名稱> vlan-id <號碼>` |
| 同 VLAN 內通，跨 VLAN 不通 | **沒有第 3 層設備**做路由 | 建 `irb` 介面，並用 `set vlans X l3-interface irb.N` 綁定 |
| 建了 `irb` 介面但它是 down | **那個 VLAN 裡沒有任何 up 的成員埠** | 先讓該 VLAN 至少有一個埠接上並 up |
| 某個 VLAN 跨不到另一台交換器 | **Trunk 沒有帶那個 VLAN** | `set interfaces ge-0/0/23 unit 0 family ethernet-switching vlan members PRINTERS` |
| Trunk 上的 untagged 封包全部消失 | **`native-vlan-id` 沒列進 `vlan members`** | 把 native VLAN 也加進 `vlan members` |
| Trunk 兩端 Native VLAN 不一致 | 設定不對稱 | 兩端都設相同的 native VLAN；用 `show lldp neighbors` 對照（**JunOS 用 LLDP，不是 CDP**） |
| **整層樓網路癱瘓、燈狂閃** | **廣播風暴（迴圈）** | 立刻找出重複接線；啟用 RSTP + `bpdu-block-on-edge` |
| 主線斷了要等 30 秒才恢復 | 用了傳統 STP | 改用 **RSTP**（EX 預設）或 MSTP |
| 插上電腦要等 30 秒才能用 | 沒設邊緣埠 | `set protocols rstp interface ge-0/0/x edge` |
| 有人接了分享器造成迴圈 | 沒有 BPDU 保護 | `set protocols rstp bpdu-block-on-edge` |
| 埠被 BPDU 保護關掉後起不來 | 需要手動清除 | `clear ethernet-switching bpdu-error interface ge-0/0/x` |
| 訪客可以存取內部伺服器 | **只切 VLAN 沒設過濾規則** | 在 `irb` 介面上套 `firewall filter` |
| 攻擊者跳到別的 VLAN | **VLAN Hopping**（Native VLAN） | native VLAN 改成閒置 VLAN；明確設 `interface-mode access` |
| VM 拿不到正確 VLAN 的 IP | 虛擬交換器的 VLAN 設定錯 | 檢查 hypervisor 的 port group VLAN ID |

> [!info]- Cisco IOS 對照
> ```cisco
> ! 對應的 IOS 解法（指令形式）
> show interfaces Gi0/x switchport      ! 檢查該埠的 VLAN 與模式
> ip routing                            ! 三層交換器沒開這個，SVI 之間不會路由
> switchport trunk allowed vlan add 30  ! 讓 Trunk 多帶一個 VLAN
> spanning-tree mode rapid-pvst         ! 換成快速收斂的版本
> spanning-tree portfast                ! 插上就能用
> spanning-tree bpduguard enable        ! 防止有人接交換器造成迴圈
> switchport nonegotiate                ! 關閉 DTP，防 VLAN Hopping
> ```
>
> | 現象 | 原因 | 解法（Cisco IOS） |
> | --- | --- | --- |
> | 電腦拿不到 IP（`169.254.x.x`） | **接到錯誤的 VLAN**（沒有 DHCP） | `show interfaces Gi0/x switchport` 檢查 VLAN |
> | 同 VLAN 內通，跨 VLAN 不通 | **沒有第 3 層設備**做路由 | 設定 SVI 或單臂路由；**檢查 `ip routing` 有沒有開** |
> | 三層交換器設了 SVI 但還是不通 | **忘了 `ip routing`** | `ip routing`（這是最常見的疏漏） |
> | 某個 VLAN 跨不到另一台交換器 | **Trunk 沒有允許那個 VLAN** | `switchport trunk allowed vlan add 30` |
> | Trunk 兩端 Native VLAN 不一致 | 設定不對稱 | 兩端都設相同的 Native VLAN；CDP 會告警 |
> | **整層樓網路癱瘓、燈狂閃** | **廣播風暴（迴圈）** | 立刻找出重複接線；啟用 STP + BPDU Guard |
> | 主線斷了要等 30 秒才恢復 | 用了傳統 STP | 改用 **rapid-pvst** 或 MSTP |
> | 插上電腦要等 30 秒才能用 | 沒設 PortFast | `spanning-tree portfast` |
> | 有人接了分享器造成迴圈 | 沒有 BPDU Guard | `spanning-tree bpduguard enable` |
> | 訪客可以存取內部伺服器 | **只切 VLAN 沒設 ACL** | 在 SVI 上套用 ACL |
> | 攻擊者跳到別的 VLAN | **VLAN Hopping**（Native VLAN 或 DTP） | 改 Native VLAN、`switchport nonegotiate` |
> | VM 拿不到正確 VLAN 的 IP | 虛擬交換器的 VLAN 設定錯 | 檢查 hypervisor 的 port group VLAN ID |
>
> **IOS 沒有 `commit` 這一步**，所以也沒有「忘記 commit」這個現象；
> 代價是打錯就當場生效，沒有 `commit confirmed` 的自動回滾可以救。

> [!tip] VLAN 排錯的四步驟
> ```
> 0. （JunOS 專屬）我到底 commit 了沒？
>    → show | compare        ← 在設定模式下，有輸出就代表還沒生效
>
> 1. 這個埠是 access 還是 trunk？屬於哪個 VLAN？
>    → show ethernet-switching interfaces
>
> 2. 這個 VLAN 存在嗎？有哪些埠是 up 的（帶星號）？
>    → show vlans
>
> 3. Trunk 有帶這個 VLAN 嗎？native-vlan-id 也在 members 裡嗎？
>    → show configuration interfaces ge-0/0/23 | display set
>
> 4. 有第 3 層介面（irb）嗎？它 up 了嗎？
>    → show interfaces terse | match irb
> ```
>
> > [!info]- Cisco IOS 對照
> > ```cisco
> > ! 1. 這個埠是 Access 還是 Trunk？屬於哪個 VLAN？
> > show interfaces Gi0/x switchport
> >
> > ! 2. 這個 VLAN 存在嗎？狀態是 active 嗎？
> > show vlan brief
> >
> > ! 3. Trunk 有允許這個 VLAN 通過嗎？
> > show interfaces trunk
> >
> > ! 4. 有第 3 層介面（SVI）嗎？ip routing 開了嗎？
> > show ip interface brief | include Vlan
> > show running-config | include ip routing
> > ```
> > IOS 沒有第 0 步（打完就生效）；
> > 但多了一個 JunOS 沒有的檢查點：**`ip routing` 到底開了沒**。

---

## 安全性注意事項

> [!danger] VLAN Hopping 的兩種手法
> **一、Switch Spoofing（利用 DTP）**
> 攻擊者送出 DTP 封包，誘導交換器把他的埠變成 Trunk，
> **然後就看得到所有 VLAN 的流量**。
>
> **防護**：所有 Access 埠設 `switchport mode access` + `switchport nonegotiate`
>
> **二、Double Tagging（利用 Native VLAN）**
> 攻擊者送出**帶兩層 VLAN 標籤**的封包：
> ```
> [外層標籤 = Native VLAN][內層標籤 = 目標 VLAN][資料]
> ```
> 第一台交換器**剝掉外層**（因為是 Native VLAN，不打標籤），
> 送到 Trunk 上；第二台交換器看到**內層標籤**，
> 就把它送進目標 VLAN。
>
> **防護**：Native VLAN 改成**沒有任何設備的閒置 VLAN**（如 999）

> [!warning] 未使用的埠一定要處理
> ```junos
> set interfaces interface-range UNUSED member-range ge-0/0/20 to ge-0/0/22
> set interfaces interface-range UNUSED description "UNUSED - DISABLED"
> set interfaces interface-range UNUSED unit 0 family ethernet-switching interface-mode access
> set interfaces interface-range UNUSED unit 0 family ethernet-switching vlan members BLACKHOLE
>
> # 逐埠關閉（disable 寫在實體介面上最保險）
> set interfaces ge-0/0/20 disable
> set interfaces ge-0/0/21 disable
> set interfaces ge-0/0/22 disable
> ```
> **兩件事都要做**：丟到黑洞 VLAN（`BLACKHOLE` = 999）**而且** `disable`。
> 只做其中一件都不夠 —— 只 disable 沒歸黑洞，日後有人開起來就直接進辦公 VLAN。
>
> > [!info]- Cisco IOS 對照
> > ```cisco
> > interface range GigabitEthernet0/21 - 24
> >  description ** UNUSED - DISABLED **
> >  switchport access vlan 999      ! 丟到黑洞 VLAN
> >  shutdown                         ! 並且關閉
> > ```
> > IOS 的 `shutdown` 對應 JunOS 的 `disable`；
> > 要重新啟用時，IOS 是 `no shutdown`，JunOS 是 `delete interfaces ge-0/0/20 disable`
> > （**JunOS 用 `delete` 取消一項設定，不是 `no`**）。
>
> 沒有做這件事的話，**任何人走進會議室插上網路線，
> 就直接進了你的辦公 VLAN**。
>
> 這是**成本為零、效果極大**的防護。

> [!tip] VLAN 不是萬能的：VLAN 的隔離不是「安全邊界」
> 這一點需要正確認識。
>
> VLAN 提供的是**邏輯隔離**，它依賴交換器正確運作。
> 如果交換器本身被攻破、或設定錯誤，隔離就失效了。
>
> **高安全需求的環境**（如處理機密資料的網段）
> 應該考慮：
> | 做法 | 說明 |
> | --- | --- |
> | **實體隔離** | 完全獨立的交換器與線路（air gap） |
> | **獨立防火牆** | 不只是 ACL，而是有狀態檢查的防火牆 |
> | **微分段** | 連同一個 VLAN 內的機器之間也要驗證 |
> | **零信任** | 不預設信任任何網路位置 |
>
> 見 [[090-05-12-guide-資安設備-零信任架構與微分段]]。

> [!warning] 語音 VLAN 的特殊考量
> IP 話機通常這樣接：
> ```
> 交換器 ──→ IP 話機 ──→ 電腦
> ```
> 話機內建一個小型交換器，同一條線同時傳語音（VLAN 60）與資料（VLAN 10）。
>
> ```junos
> set vlans VOICE vlan-id 60
>
> # 埠本身是 access，帶資料 VLAN（不打標籤，給電腦用）
> set interfaces ge-0/0/5 unit 0 family ethernet-switching interface-mode access
> set interfaces ge-0/0/5 unit 0 family ethernet-switching vlan members USERS
>
> # 再宣告這個埠是 VoIP 埠，語音走 VOICE VLAN（打標籤，給話機用）
> set switch-options voip interface ge-0/0/5.0 vlan VOICE
> set switch-options voip interface ge-0/0/5.0 forwarding-class assured-forwarding
>
> # 話機靠 LLDP-MED 才知道要用哪個語音 VLAN
> set protocols lldp-med interface ge-0/0/5
> set protocols rstp interface ge-0/0/5 edge
> ```
> **一個觀念差異**：IOS 的 `switchport voice vlan 60` 一行就完事；
> JunOS 要在 `switch-options voip` 底下宣告，而且**通常要搭配 LLDP-MED**
> 讓話機自己學到語音 VLAN。`forwarding-class assured-forwarding` 則是
> 順手把語音流量放進較有保障的服務類別。
>
> > [!info]- Cisco IOS 對照
> > ```cisco
> > interface GigabitEthernet0/5
> >  switchport mode access
> >  switchport access vlan 10        ! 電腦的資料 VLAN（不打標籤）
> >  switchport voice vlan 60         ! 話機的語音 VLAN（打標籤）
> >  spanning-tree portfast
> > ```
> > IOS 的話機同樣是靠 CDP 或 LLDP-MED 學到語音 VLAN，
> > 只是 Cisco 話機配 Cisco 交換器時走 CDP，**JunOS 環境一律走 LLDP-MED**。
>
> **資安考量**：這個埠實際上同時屬於兩個 VLAN，
> 攻擊者若拔掉話機直接接電腦，
> **可能可以偽造語音 VLAN 的標籤**。
> 高安全環境應考慮用 802.1X 驗證話機身分。

---

## 速查表

### Access vs Trunk

| | Access | Trunk |
| --- | --- | --- |
| 接什麼 | 終端設備 | 交換器/路由器之間 |
| VLAN 數 | **1 個** | **多個** |
| 標籤 | **無** | **802.1Q** |
| 比喻 | 辦公室的門 | 走廊 |

### 802.1Q 標籤

```
4 位元組，包含：
  VLAN ID: 12 bit → 1～4094
  PCP/CoS: 3 bit  → 優先序 0～7
```

### VLAN 間通訊方案

| 方案 | 說明 | 適合 |
| --- | --- | --- |
| **單臂路由** | 一台路由器 + Trunk + 邏輯單元／子介面 | 小型網路 |
| **三層交換器** | 交換器硬體路由（JunOS 叫 **IRB**，Cisco 叫 **SVI**） | **企業標準** |

**JunOS：`set vlans X l3-interface irb.N` 這行綁定不能漏，
而且 irb 要等 VLAN 裡有 up 的成員埠才會起來。**
（Cisco 那邊對應的坑是**別忘了 `ip routing`**。）

### STP 版本

| 版本 | 收斂時間 |
| --- | --- |
| STP (802.1D) | 30～50 秒 ❌ |
| **RSTP (802.1w)** | **1～6 秒** ✅ |
| Rapid-PVST+ | 快，每 VLAN 一棵樹 |

### 必做的埠設定

**使用者埠（Access）**：
```junos
set interfaces ge-0/0/5 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/5 unit 0 family ethernet-switching vlan members USERS
set interfaces ge-0/0/5 unit 0 family ethernet-switching storm-control SC-5
set protocols rstp interface ge-0/0/5 edge
set protocols rstp bpdu-block-on-edge
set switch-options interface ge-0/0/5 interface-mac-limit 2 packet-action drop
```

**Trunk 埠**：
```junos
set interfaces ge-0/0/23 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/23 unit 0 family ethernet-switching vlan members [ USERS SERVERS GUEST BLACKHOLE ]
set interfaces ge-0/0/23 native-vlan-id 999
```

**未使用的埠**：
```junos
set interfaces ge-0/0/22 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/22 unit 0 family ethernet-switching vlan members BLACKHOLE
set interfaces ge-0/0/22 disable
```

**最後別忘了**：`commit`（遠端作業先 `commit confirmed 5`）。

> [!info]- Cisco IOS 對照
> **使用者埠（Access）**：
> ```cisco
> switchport mode access
> switchport access vlan 10
> switchport nonegotiate            ! 防 VLAN Hopping
> spanning-tree portfast
> spanning-tree bpduguard enable    ! 防迴圈
> storm-control broadcast level 5
> switchport port-security
> ```
>
> **Trunk 埠**：
> ```cisco
> switchport mode trunk
> switchport trunk allowed vlan 10,20,99    ! 明確限制
> switchport trunk native vlan 999          ! 不用 VLAN 1
> switchport nonegotiate
> ```
>
> **未使用的埠**：
> ```cisco
> switchport access vlan 999
> shutdown
> ```
>
> IOS 這三段打完就生效；JunOS 那三段要 `commit` 才算數。

### 驗證指令

| 目的 | 指令（JunOS） |
| --- | --- |
| VLAN 與埠對應 | `show vlans` |
| 每個埠的模式與 VLAN | `show ethernet-switching interfaces` |
| Trunk 細節 | `show interfaces ge-0/0/23 extensive` |
| 單一埠設定（set 格式） | `show configuration interfaces ge-0/0/5 \| display set` |
| STP 狀態 | `show spanning-tree bridge`、`show spanning-tree interface` |
| MAC 表 | `show ethernet-switching table` |
| 三層介面（irb） | `show interfaces terse \| match irb` |
| 這次改了什麼（設定模式） | `show \| compare` |
| 鄰居設備 | `show lldp neighbors` |
| Linux 建 VLAN | `ip link add link eth0 name eth0.10 type vlan id 10` |
| 抓 VLAN 封包 | `sudo tcpdump -e -n vlan` |

> [!info]- Cisco IOS 對照
> | 目的 | 指令（Cisco IOS） |
> | --- | --- |
> | VLAN 與埠對應 | `show vlan brief` |
> | Trunk 狀態 | `show interfaces trunk` |
> | 單一埠設定 | `show interfaces Gi0/x switchport` |
> | STP 狀態 | `show spanning-tree vlan 10` |
> | SVI 介面 | `show ip interface brief \| include Vlan` |
> | MAC 表 | `show mac address-table` |
> | 鄰居設備 | `show cdp neighbors`（或 `show lldp neighbors`） |
>
> **JunOS 的 `show` 要在操作模式（`>`）下打**；
> 在設定模式（`#`）裡要看狀態，前面加 `run`，例如 `run show vlans`。

---

## 練習題

> [!question]- 練習 1：在 Linux 上實作 VLAN
> ```bash
> sudo modprobe 8021q
> sudo ip link add link eth0 name eth0.10 type vlan id 10
> sudo ip addr add 192.168.10.50/24 dev eth0.10
> sudo ip link set eth0.10 up
> ip -d link show eth0.10
> ```
> 然後在另一個終端機抓封包：
> ```bash
> sudo tcpdump -i eth0 -e -n vlan
> ```
> 從 `eth0.10` ping 一個位址，觀察封包裡的 `vlan 10` 標籤。

> [!question]- 練習 2：規劃機關的 VLAN
> 為一個 150 人的機關規劃 VLAN，包含：
> 使用者電腦、伺服器、資料庫、印表機、監視系統、IP 話機、訪客、網路設備管理。
>
> 回答：
> 1. 各給哪個 VLAN ID 與網段？
> 2. **哪些 VLAN 之間需要通？哪些必須完全隔離？**
> 3. 管理 VLAN 該有哪些額外的保護？
> 4. Native VLAN 該設什麼？
>
> 參考方向見本篇「典型的分段規劃」表格。
> 重點：**訪客與 IoT 完全不能碰內部；管理 VLAN 只允許跳板機**。

> [!question]- 練習 3：診斷 VLAN 問題
> 情境：3 樓某個使用者的電腦拿到 `169.254.x.x`，其他人都正常。
>
> 寫出你的排查步驟（至少五步）。
>
> 參考答案（JunOS）：
> ```
> 1. 實體層：ethtool 看有沒有 Link（線、埠）
> 2. 找出他接在交換器的哪個埠
>    → show ethernet-switching table（用 MAC 反查），或看埠的 description
> 3. show ethernet-switching interfaces
>    → 這個埠是 access 嗎？VLAN members 是哪個？是不是被設錯了？
> 4. show vlans → 那個 VLAN 存在嗎？這個埠在清單裡而且帶星號（up）嗎？
> 5. 那個 VLAN 有 DHCP 嗎？
>    → irb 介面上有沒有設 DHCP relay？
>      show configuration forwarding-options dhcp-relay | display set
> 6. 檢查是不是被 MAC limit 或 BPDU 保護擋掉了
>    → show ethernet-switching interfaces（看 Blocking 欄位）
>    → 若是 BPDU 保護：clear ethernet-switching bpdu-error interface ge-0/0/x
> ```
>
> > [!info]- Cisco IOS 對照
> > ```cisco
> > ! 1. 實體層：看有沒有 Link
> > ! 2. 找出他接在交換器的哪個埠
> > show mac address-table
> > ! 3. 這個埠是 access 嗎？屬於哪個 VLAN？
> > show interfaces Gi0/x switchport
> > ! 4. 那個 VLAN 存在且 active 嗎？
> > show vlan brief
> > ! 5. 那個 VLAN 有 DHCP 嗎？SVI 上有沒有 ip helper-address？
> > show running-config interface Vlan10
> > ! 6. 檢查 port-security 有沒有把埠 err-disabled
> > show interfaces status err-disabled
> > ```

---

## 小測驗

Q1. 用「辦公大樓隔間」的比喻說明 VLAN。它帶來哪三個效果？

Q2. Access 埠與 Trunk 埠的差別是什麼？各接什麼設備？

Q3. 802.1Q 標籤有幾位元組？VLAN ID 佔幾位元、範圍是多少？

Q4. 什麼是 Native VLAN？為什麼預設的 VLAN 1 是資安問題？

Q5. VLAN Hopping 有哪兩種手法？各該怎麼防護？

Q6. VLAN 之間要通訊需要什麼？單臂路由與三層交換器各有什麼優缺點？

Q7. **為什麼第 2 層的迴圈比第 3 層的路由迴圈更可怕**？

Q8. STP 除了防迴圈，還有什麼價值？為什麼要用 RSTP 而不是傳統 STP？

Q9. PortFast 與 BPDU Guard 為什麼要一起設定？BPDU Guard 的判斷邏輯是什麼？

Q10. 「切了 VLAN 就有資安」這句話錯在哪裡？管理 VLAN 為什麼是最高價值的目標？

> [!question]- 測驗答案
> **Q1.** VLAN 就像**用隔板把一層樓隔成好幾間辦公室**：
> 每間裡面的人可以自由交談，**不同辦公室之間聽不到彼此**，
> 要跨辦公室溝通**必須走走廊（路由器）**，而走廊上可以設警衛（防火牆）。
> 關鍵是這些隔板是**軟體設定的，隨時可以改**。
> **三個效果**：①**切開廣播網域**；②**邏輯隔離**（不同 VLAN 無法直接通訊）；
> ③**不受實體位置限制**（3 樓與 5 樓可在同一 VLAN）。
>
> **Q2.** **Access 埠**接**終端設備**（電腦、印表機、AP），
> **只屬於一個 VLAN**，封包**沒有標籤**（終端設備不懂 VLAN）；
> **Trunk 埠**接**交換器之間或交換器與路由器**，
> **可承載多個 VLAN**，封包帶有 **802.1Q 標籤**。
> 比喻：Access 是「辦公室的門」，Trunk 是「走廊」。
>
> **Q3.** 802.1Q 標籤是 **4 位元組**。
> **VLAN ID 佔 12 位元**，範圍 **1～4094**（0 與 4095 保留）。
> 另外有 3 位元的 **PCP/CoS**（服務品質優先序 0～7）與 TPID。
>
> **Q4.** **Native VLAN 是 Trunk 上唯一「不打標籤」的 VLAN**
> （為了相容不懂 VLAN 的舊設備）。
> 預設是 VLAN 1，這是資安問題，因為它讓 **Double Tagging 的
> VLAN Hopping 攻擊**成為可能 ——
> 攻擊者送出帶兩層標籤的封包，第一台交換器剝掉外層（Native，不打標籤），
> 第二台看到內層標籤就把它送進目標 VLAN。
> 應改成**沒有任何設備的閒置 VLAN**（如 999）。
> **JunOS 額外要注意**：`native-vlan-id` 指定的那個 VLAN
> **必須同時列在該 Trunk 的 `vlan members` 裡**，否則 untagged 封包會被直接丟掉。
>
> **Q5.** ①**Switch Spoofing（利用 DTP）** ——
> 攻擊者送 DTP 封包誘導交換器把他的埠變成 Trunk，
> 就能看到所有 VLAN 的流量。
> **防護**：**JunOS 不支援 DTP，介面不會自動協商成 Trunk**，天生沒有這個洞；
> 但仍要把每個 Access 埠明確寫成
> `set interfaces ge-0/0/x unit 0 family ethernet-switching interface-mode access`，
> 不要留白讓平台預設決定。
> （Cisco IOS 則必須加 `switchport mode access` + `switchport nonegotiate` 關掉 DTP。）
> ②**Double Tagging（利用 Native VLAN）** —— 見 Q4。
> **防護**：native VLAN 改成閒置的 VLAN（如 999），
> 並記得在 JunOS 上把它一併列進 Trunk 的 `vlan members`。
>
> **Q6.** VLAN 之間要通訊必須經過**第 3 層設備**（路由器或三層交換器）。
> **單臂路由**：一台路由器 + 一條 Trunk + 多個邏輯單元（JunOS 的 `unit`，
> 對應 IOS 的子介面）—— **便宜、設定簡單**，
> 但**所有 VLAN 間流量都擠在同一條線上**，容易成為瓶頸；
> **三層交換器**：交換器用**硬體 ASIC 做路由**，
> JunOS 叫 **IRB**（`irb.10`），Cisco 叫 **SVI**（`interface Vlan10`）——
> **極快、埠多，是企業標準做法**，但較貴且進階功能（NAT、VPN）較少。
> **JunOS 要記得 `set vlans USERS l3-interface irb.10` 這行綁定**，
> 而且 `irb` 介面要等該 VLAN 裡有 up 的成員埠才會起來；
> **JunOS 沒有「啟用路由」的開關**（Cisco 那邊則是最常漏掉的 `ip routing`）。
>
> **Q7.** 因為**第 2 層的 Frame 沒有 TTL** ——
> 不像 IP 封包會遞減後死掉，**Frame 會永遠循環下去**。
> 一個廣播封包進入迴圈後會**呈指數成長**，
> 幾秒內就讓頻寬 100% 佔滿、交換器 CPU 100% 失去回應、
> MAC 表不斷震盪，**整個網路完全癱瘓**（廣播風暴）。
> 而且最常見的成因不是設計錯誤，而是**有人不小心把一條線的兩端插進兩個網路孔**。
>
> **Q8.** 除了防迴圈，STP 還提供**自動備援** ——
> 你可以刻意接兩條線做冗餘，平常 STP 阻斷其中一條，
> **主線斷了就自動啟用備用線路**。
> 要用 RSTP 是因為**傳統 STP 的收斂時間長達 30～50 秒**，
> 主線斷掉後這段時間網路完全不通；
> **RSTP（802.1w）只要 1～6 秒**。
>
> **Q9.** **PortFast** 讓終端設備的埠跳過 STP 等待，插上就能用（省 30 秒），
> 但也帶來風險 —— 如果有人在那個埠接了交換器就可能形成迴圈。
> **BPDU Guard 的邏輯**：「這個埠應該接終端設備，
> **終端設備不會發 BPDU**；所以**如果收到 BPDU，
> 代表有人接了交換器 → 立刻關閉這個埠**。」
> 兩者一起設定能防止絕大多數的意外迴圈事故。
>
> **Q10.** 錯在**「切了 VLAN」不等於「有存取控制」**。
> 如果三層交換器上完全沒有 ACL、所有 VLAN 之間互通，
> 那只是把一個大廣播網域切成幾個小的，**資安效果幾乎是零**。
> **真正的分段 = VLAN + 明確的存取控制規則。**
> **管理 VLAN 是最高價值目標**，因為它包含交換器、防火牆、AP 控制器、
> **伺服器的 iDRAC/iLO/IPMI**、UPS 管理卡 ——
> 攻下它等於**完全控制整個網路與所有伺服器**
> （IPMI 可在作業系統關機時開關機、掛載虛擬光碟）。
> 必做：絕不連網際網路、只允許特定跳板機存取、改預設密碼、啟用 MFA、完整日誌。

---

## 延伸閱讀

- [[010-02-05-guide-網概-MAC位址與交換器]] — 廣播網域與交換器基礎
- [[010-02-06-guide-網概-IP位址與子網路]] — 每個 VLAN 對應一個網段
- [[010-02-07-guide-網概-路由與封包旅程]] — VLAN 間路由
- [[010-02-12-guide-網概-DHCP自動取得設定]] — 跨 VLAN 的 DHCP Relay
- [[010-02-18-guide-網概-網路安全基礎]] — 網路分段的資安價值
- [[040-01-03-guide-網路設備-VLAN概念與規劃]] — 企業 VLAN 規劃實戰（進階）
- [[040-01-13-guide-Cisco-埠設定與安全]] — 埠安全完整設定（進階）
- [[090-05-12-guide-資安設備-零信任架構與微分段]] — 比 VLAN 更細緻的隔離（進階）
