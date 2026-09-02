---
title: "VLAN 概念與規劃"
desc: "802.1Q 標籤怎麼加、Access 與 Trunk 的差別、Native VLAN 的坑，以及機關典型 VLAN 規劃表"
aliases: [VLAN, 802.1Q, dot1q, Trunk, Access, Native VLAN, 標籤]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-01-guide-網路設備-網路架構基礎]]", "[[040-01-02-guide-網路設備-IP位址規劃與子網切分]]", "[[010-02-16-guide-網概-VLAN與網路分段]]"]
updated: 2026-09-02
---

# VLAN 概念與規劃

> [!abstract] 這篇你會學到
> - ★★★★★ **802.1Q 標籤到底加在哪、長什麼樣**：4 個位元組插在來源 MAC 之後，
>   看懂它，Access／Trunk／Native 三個概念一次全通
> - ★★★★★ **Access 埠與 Trunk 埠的唯一差別**：出去的時候有沒有帶標籤。
>   一句話講完，剩下的都是推論
> - ★★★★★ **Native VLAN 三個坑**：兩端不一致造成 VLAN 洩漏、
>   預設 VLAN 1 的資安風險、Juniper 與 Cisco 對 Native 的語意差異
> - ★★★★ **VLAN 與子網一對一**：為什麼「一個 VLAN 兩個網段」是災難的開始
> - ★★★★ 機關典型 VLAN 規劃表（辦公／伺服器／管理／訪客／IP 電話／監視器／DMZ），
>   含每一個的**必備管制措施**
> - ★★★★ VLAN 洩漏（VLAN hopping）的兩種手法與對應防護
> - 一個從規劃表到設備落地、含 tcpdump 抓標籤驗證的完整實戰

> [!note] 這篇與 [[010-02-16-guide-網概-VLAN與網路分段]] 的分工
> 那篇是**概論**：VLAN 是什麼、為什麼要分段、對資安有什麼幫助。
> **本篇是規劃與落地**：標籤的位元組結構、Access/Trunk 的實際設定與驗證、
> Native VLAN 的實戰陷阱、機關該切哪幾個 VLAN、每個 VLAN 要配什麼管制。

## 前置知識

- [[010-02-16-guide-網概-VLAN與網路分段]] —— VLAN 的基本概念與分段的資安意義
- [[040-01-01-guide-網路設備-網路架構基礎]] —— 廣播域邊界、MAC 表、L3 邊界的位置
- [[040-01-02-guide-網路設備-IP位址規劃與子網切分]] —— 每個 VLAN 要配一個網段
- [[010-02-05-guide-網概-MAC位址與交換器]] —— frame 的結構與交換器的學習行為
- 會用 `tcpdump` 抓封包（本篇用它來「看見」VLAN 標籤）

## 觀念說明

### ★★★★★ VLAN 存在的三個理由

| # | 理由 | 沒有 VLAN 時的痛 | 星級 |
| --- | --- | --- | --- |
| 1 | **切割廣播域** | 全機關 300 台在同一個廣播域，ARP 廣播量隨主機數平方成長；一台壞掉的 NIC 拖垮全部人 | ★★★★★ |
| 2 | **資安分段的前提** | 訪客與伺服器在同一個二層網路，中間沒有任何設備可以攔 | ★★★★★ |
| 3 | **邏輯分組不受實體位置限制** | 三樓的財務同仁想跟一樓的財務同仁同網段？要重拉線 | ★★★★ |

★★★★ 第 3 點是 VLAN 名字的由來（Virtual LAN，**虛擬**區域網路）：
它讓「在同一個 LAN」這件事從**實體接線**變成**設定值**。

> [!warning] ★★★★★ VLAN 切了不等於隔離了
> 這是本手冊反覆強調的一點：VLAN 只切**廣播域**。
> VLAN 10 與 VLAN 30 之間要不要通、通哪些埠，
> **完全取決於 L3 邊界那台設備上有沒有管制**。
> 只切 VLAN 不做 ACL，等於「把人分成不同房間，但門全部拆掉」。
> 詳見 [[040-01-01-guide-網路設備-網路架構基礎]] 的「東西向流量」。

### ★★★★★ 802.1Q 標籤：4 個位元組插在哪裡

**沒有標籤的乙太網路 frame：**

```text
┌──────────────┬──────────────┬─────────┬────────────┬─────┐
│ 目的 MAC (6) │ 來源 MAC (6) │ 類型(2) │ 資料 46~1500│ FCS │
└──────────────┴──────────────┴─────────┴────────────┴─────┘
                                 0x0800 = IPv4
```

**加了 802.1Q 標籤之後：**

```text
┌──────────────┬──────────────┬═════════════════════┬─────────┬────────────┬─────┐
│ 目的 MAC (6) │ 來源 MAC (6) │  802.1Q 標籤（4）   │ 類型(2) │ 資料        │ FCS │
└──────────────┴──────────────┴═════════════════════┴─────────┴────────────┴─────┘
                              ↑ ★★★★★ 就插在這裡
                              │
        ┌─────────────────────┴──────────────────────┐
        │ TPID (16 bit)  │ PCP(3) │ DEI(1) │ VID(12) │
        │   0x8100       │  優先權 │ 丟棄  │ VLAN ID │
        └────────────────────────────────────────────┘
```

| 欄位 | 位元數 | 意義 | 星級 |
| --- | --- | --- | --- |
| **TPID** | 16 | 固定 `0x8100`，交換器看到它就知道「後面是 VLAN 標籤」 | ★★★★ |
| **PCP** | 3 | 優先權 0～7，★★★★ **QoS 就是靠這 3 個位元**（IP 電話設 5） | ★★★★ |
| **DEI** | 1 | 壅塞時可優先丟棄（早期叫 CFI），實務上很少用 | ★★ |
| **VID** | 12 | ★★★★★ **VLAN ID，範圍 0～4095**，其中 0 與 4095 保留 → **可用 1～4094** | ★★★★★ |

★★★★ **VID 只有 12 個位元**，這就是「VLAN ID 最大 4094」的來源——
不是廠商限制，是標準的位元數限制。

★★★★ **加了 4 個位元組會怎樣**：frame 從最大 1518 變成 1522 位元組。
所以設備上會看到 **baby giant frame** 這個名詞，
以及為什麼有些老舊設備需要調整 MTU。

### ★★★★★ Access 埠與 Trunk 埠：唯一的差別

用一句話講完：

> **Access 埠送出去的 frame 沒有標籤；Trunk 埠送出去的 frame 帶標籤。**

其他所有行為都是從這一句推論出來的：

| 面向 | Access 埠 | Trunk 埠 | 星級 |
| --- | --- | --- | --- |
| **接誰** | 終端（PC、印表機、伺服器、IP 攝影機） | 另一台交換器、路由器、防火牆、AP、虛擬化主機 | ★★★★★ |
| **收到「無標籤」frame** | 打上該埠設定的 VLAN 標籤，進入交換 | ★★★★★ 打上 **Native VLAN** 的標籤（這是坑的來源） | ★★★★★ |
| **收到「有標籤」frame** | ★★★★ 通常直接丟棄（安全考量） | 依標籤分派到對應 VLAN；不在允許清單內則丟棄 | ★★★★ |
| **送出時** | ★★★★★ **拔掉標籤**再送 | ★★★★★ **保留標籤**送出（Native VLAN 例外，見下） | ★★★★★ |
| **承載幾個 VLAN** | 1 個（語音 VLAN 是特例） | 多個 | ★★★★ |
| **終端知不知道 VLAN** | ★★★★★ **完全不知道**，它以為自己在一個普通 LAN | 對端設備必須也懂 802.1Q | ★★★★ |

★★★★★ **最重要的推論**：一般 PC 的網卡**看不懂 802.1Q 標籤**，
所以接 PC 的埠必須是 Access。如果你把 PC 接到 Trunk 埠上，
PC 收到帶標籤的 frame 會直接丟棄 → **接上去但完全不通**。
這是新手最常見的接線錯誤。

### ★★★★★ Native VLAN：三個坑

**Native VLAN 的定義**：Trunk 埠上**唯一不帶標籤傳送**的那個 VLAN。

```text
Trunk 埠承載 VLAN 10, 20, 30，Native VLAN = 1

送出 VLAN 10 的 frame → 帶標籤 [VID=10]
送出 VLAN 20 的 frame → 帶標籤 [VID=20]
送出 VLAN 30 的 frame → 帶標籤 [VID=30]
送出 VLAN  1 的 frame → ★★★★★ 不帶標籤（因為它是 Native）

收到「沒有標籤」的 frame → ★★★★★ 當成 VLAN 1 處理
```

**為什麼要有 Native VLAN？** 歷史原因：早期有些設備（老舊的 hub、
不支援 802.1Q 的裝置）接在 Trunk 上時看不懂標籤，
留一個「不帶標籤」的通道讓它們還能通。**今天幾乎沒有這個需求了。**

#### ★★★★★ 坑 1：兩端 Native VLAN 不一致 → VLAN 洩漏

```text
交換器 A：Trunk 埠 Native VLAN = 1
交換器 B：Trunk 埠 Native VLAN = 99

A 上 VLAN 1 的流量 → 不帶標籤送出 → B 收到無標籤 frame → 當成 VLAN 99
★★★★★ 結果：A 的 VLAN 1 和 B 的 VLAN 99 被「接通」了，
             而且兩邊的設定檔看起來都很正常，完全看不出問題
```

症狀：**兩個本來不該互通的 VLAN 神秘地互通了**，或是
「明明設了 VLAN 卻還是拿到別的網段的 DHCP」。
這種故障可以查一整天，因為每一台設備單獨看都沒錯。

★★★★★ **檢查方式**：兩端各跑一次看 Trunk 設定，比對 Native VLAN。
Cisco 的 CDP 甚至會主動報警 `native VLAN mismatch`。

#### ★★★★★ 坑 2：Native VLAN 用預設的 VLAN 1

VLAN 1 是所有交換器的**出廠預設 VLAN**：

- 所有埠出廠時都在 VLAN 1
- 管理協定（CDP、VTP、STP、DTP）預設在 VLAN 1 上跑
- Native VLAN 預設就是 VLAN 1

★★★★★ **風險**：如果 Native VLAN = VLAN 1，而 VLAN 1 又有使用者終端在裡面，
攻擊者可以用**雙層標籤（double tagging）**手法把封包送進其他 VLAN——
見下方「VLAN 洩漏」。

★★★★★ **標準做法（三件事一起做）**：

```text
1. 把 Native VLAN 改成一個「專用的、什麼都不放的」VLAN，例如 999
2. VLAN 1 完全不使用：所有埠都指派到明確的業務 VLAN
3. Trunk 的允許清單裡不要包含 VLAN 1
```

#### ★★★★ 坑 3：Juniper 與 Cisco 對 Native 的語意不同

| 項目 | Cisco IOS | Juniper JunOS | 星級 |
| --- | --- | --- | --- |
| 設定關鍵字 | `switchport trunk native vlan 999` | `native-vlan-id 999`（在介面下） | ★★★★ |
| 預設值 | VLAN 1 | ★★★★ **預設沒有 native**（無標籤 frame 直接丟棄） | ★★★★★ |
| Native VLAN 是否需在允許清單 | 需要 | ★★★★ 需要，且 JunOS 要另外在 `vlan members` 裡列出來 | ★★★★ |

★★★★★ **這個差異很關鍵**：Juniper Trunk 埠**預設會丟棄無標籤的 frame**，
這其實比 Cisco 的預設值安全。但也造成一個常見症狀：
**「從 Cisco 換成 Juniper 之後，某些流量不通了」**——
因為原本靠 Native VLAN 傳的無標籤流量，在 Juniper 上被丟了。

### ★★★★★ VLAN 與子網一對一

**規則：一個 VLAN 對應一個 IP 網段，不多不少。**

| 反面案例 | 症狀 | 星級 |
| --- | --- | --- |
| **一個 VLAN 兩個網段**（例如 VLAN 10 裡同時有 `10.37.10.0/24` 與 `192.168.5.0/24`） | 兩個網段的主機在同一個廣播域卻互相 ping 不到（要經過路由但沒有路由）；DHCP 亂派；排錯時完全看不懂 | ★★★★★ |
| **一個網段跨兩個 VLAN** | 同網段主機在不同廣播域，ARP 要不到彼此 → **完全不通** | ★★★★★ |
| **VLAN ID 與網段第三段不一致**（VLAN 10 用 `10.37.55.0/24`） | 沒有立即故障，但排錯與寫規則時心智負擔倍增 | ★★★ |

★★★★★ **正確做法**（承接 [[040-01-02-guide-網路設備-IP位址規劃與子網切分]]）：

```text
VLAN 11  ←→  10.37.11.0/24   ←→  irb.11 / interface vlan 11
VLAN 90  ←→  10.37.90.0/26   ←→  irb.90 / interface vlan 90
        一個 VLAN、一個網段、一個 L3 介面，三者編號一致
```

> [!tip] ★★★ 唯一合理的例外：Secondary IP
> 網段搬遷期間，可以在同一個 L3 介面上暫時掛兩個網段（新舊並存），
> 讓遷移過程中的主機都能互通。**這是暫時狀態，遷移完成必須移除舊網段。**
> 見 [[040-01-02-guide-網路設備-IP位址規劃與子網切分]] 的「網段重劃」。

### ★★★★ Voice VLAN：Access 埠上的合法例外

IP 電話的典型接法是「牆上網路孔 → IP 電話 → PC」，
所以**一個埠要同時承載電話（VLAN 51）與 PC（VLAN 11）**：

```text
交換器埠 ge-0/0/5
  ├─ 無標籤流量  → VLAN 11（PC，Access）
  └─ 標籤 VID=51 → VLAN 51（IP 電話，Voice VLAN）

IP 電話自己會：
  1. 透過 LLDP-MED（或 CDP）從交換器學到「語音 VLAN 是 51」
  2. 自己把送出的封包打上 VID=51 標籤與 PCP=5 優先權
  3. 把 PC 送來的無標籤流量原封不動往上傳
```

★★★★ 這在技術上是一個「只允許一個標籤 VLAN 的 Trunk」，
但廠商用 `voice-vlan` / `switchport voice vlan` 這種專用語法包裝，
避免你去手動設 Trunk。**不要自己把它設成完整 Trunk**，
那會讓使用者的 PC 有機會存取其他 VLAN。

### ★★★★★ VLAN 洩漏（VLAN Hopping）：兩種手法

| 手法 | 原理 | 防護 | 星級 |
| --- | --- | --- | --- |
| **Switch Spoofing** | 攻擊者的裝置假裝成交換器，用 DTP（Cisco 的動態 Trunk 協商）把自己的埠**協商成 Trunk**，然後就能存取所有 VLAN | ★★★★★ **所有終端埠強制設為 Access 並關閉 DTP**（Cisco `switchport nonegotiate`）；Juniper 沒有 DTP，天生免疫 | ★★★★★ |
| **Double Tagging** | 攻擊者送出**帶兩層標籤**的 frame：外層是 Native VLAN、內層是目標 VLAN。第一台交換器剝掉外層（因為是 Native，無標籤傳送），第二台看到內層標籤就送進目標 VLAN | ★★★★★ **Native VLAN 改成不使用的專用 VLAN**；Trunk 允許清單排除 Native；終端埠不要在 Native VLAN 裡 | ★★★★★ |

★★★★ **Double Tagging 是單向的**（回不來），所以主要用於攻擊而非竊聽——
但「送得進去」對 DoS 或觸發漏洞已經足夠。

## 安裝或基礎操作

主線 **Juniper JunOS（EX 系列，ELS 語法）**，Cisco 對照放摺疊區塊。

### 步驟 1：先看現況 ★★★★

```text
admin@sw1> show vlans
Routing instance        VLAN name             Tag          Interfaces
default-switch          default               1
                                                           ge-0/0/0.0
                                                           ge-0/0/1.0*
                                                           ge-0/0/2.0
```

★★★★ 全新的交換器只有一個 `default` VLAN（tag 1），所有埠都在裡面。
埠名稱後面的 **`*` 代表該埠目前 link up**。

```text
admin@sw1> show ethernet-switching interface
Routing Instance Name : default-switch
Logical Interface flags (DL - disable learning, AD - packet action drop,
                         LH - MAC limit hit, DN - interface down, ...)

Logical interface    ge-0/0/1.0
Index   : 553    SVLBNH/VENH Index : 0    Groups : 0
Interface flags: Ethernet-Switching
VLAN Name         Tag       MAC        MAC + IP    STP        Logical
                            limit      limit       State      interface flags
default           1         16383      0           Forwarding
```

★★★★★ 這個指令是**排錯時最重要的一個**：它一次告訴你
「這個埠屬於哪些 VLAN、STP 狀態、MAC 學習上限」。

### 步驟 2：建立 VLAN ★★★★

```text
admin@sw1> configure
Entering configuration mode

[edit]
admin@sw1# set vlans VL11-OFFICE-1F vlan-id 11
admin@sw1# set vlans VL12-OFFICE-2F vlan-id 12
admin@sw1# set vlans VL51-VOIP      vlan-id 51
admin@sw1# set vlans VL90-SERVER    vlan-id 90
admin@sw1# set vlans VL99-MGMT      vlan-id 99
admin@sw1# set vlans VL999-NATIVE   vlan-id 999 description "Unused, native only"

[edit]
admin@sw1# show vlans
VL11-OFFICE-1F {
    vlan-id 11;
}
VL12-OFFICE-2F {
    vlan-id 12;
}
VL51-VOIP {
    vlan-id 51;
}
VL90-SERVER {
    vlan-id 90;
}
VL99-MGMT {
    vlan-id 99;
}
VL999-NATIVE {
    description "Unused, native only";
    vlan-id 999;
}
```

★★★★ **VLAN 命名慣例**（機關實務建議）：

```text
VL<ID>-<用途大寫英文>
  VL11-OFFICE-1F、VL90-SERVER、VL99-MGMT

★★★★ 規則：
  - ID 放在名稱裡 → 看名稱就知道 tag，不用再查
  - 全大寫、用連字號 → 跨廠牌都相容（有些設備不吃中文與特殊字元）
  - ★★★★★ 不要用中文，不要用空格
```

### 步驟 3：設定 Access 埠 ★★★★★

```text
[edit]
admin@sw1# set interfaces ge-0/0/1 description "1F-A01 使用者座位"
admin@sw1# set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
admin@sw1# set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members VL11-OFFICE-1F

[edit]
admin@sw1# show | compare
[edit interfaces]
+   ge-0/0/1 {
+       description "1F-A01 使用者座位";
+       unit 0 {
+           family ethernet-switching {
+               interface-mode access;
+               vlan {
+                   members VL11-OFFICE-1F;
+               }
+           }
+       }
+   }

[edit]
admin@sw1# commit confirmed 5
commit confirmed will be automatically rolled back in 5 minutes unless confirmed
commit complete

[edit]
admin@sw1# commit
commit complete
```

★★★★★ **`commit confirmed 5`**：改 VLAN 很容易把自己（或整層樓）切斷，
5 分鐘內沒有再 `commit` 就自動回退。**這是 JunOS 最該養成的習慣。**

批次設定一整排埠：

```text
[edit]
admin@sw1# wildcard range set interfaces ge-0/0/[1-24] unit 0 \
             family ethernet-switching interface-mode access
admin@sw1# wildcard range set interfaces ge-0/0/[1-24] unit 0 \
             family ethernet-switching vlan members VL11-OFFICE-1F
```

★★★★ `wildcard range` 是 JunOS 少數幾個真正省時間的功能，
一次設 24 個埠不用打 24 次。**設定完務必 `show | compare` 確認範圍沒設錯。**

### 步驟 4：設定 Trunk 埠 ★★★★★

```text
[edit]
admin@sw1# set interfaces ge-0/0/48 description "Uplink to core-sw1 ge-0/0/45"
admin@sw1# set interfaces ge-0/0/48 unit 0 family ethernet-switching interface-mode trunk
admin@sw1# set interfaces ge-0/0/48 unit 0 family ethernet-switching \
             vlan members [ VL11-OFFICE-1F VL12-OFFICE-2F VL51-VOIP VL99-MGMT VL999-NATIVE ]
admin@sw1# set interfaces ge-0/0/48 native-vlan-id 999
admin@sw1# commit
commit complete
```

★★★★★ 四個要點，缺一不可：

| # | 要點 | 為什麼 | 星級 |
| --- | --- | --- | --- |
| 1 | `interface-mode trunk` | 決定送出時保留標籤 | ★★★★★ |
| 2 | **明確列出 `vlan members`** | ★★★★★ **不要用 `all`**——只放行需要的 VLAN，這是最基本的最小權限 | ★★★★★ |
| 3 | `native-vlan-id 999` | 用專用的空 VLAN 當 Native，避開 VLAN 1 | ★★★★★ |
| 4 | Native VLAN **也要列在 members 裡** | ★★★★ JunOS 上沒列的話無標籤流量還是會被丟 | ★★★★ |

驗證：

```text
admin@sw1> show ethernet-switching interface ge-0/0/48
Logical interface    ge-0/0/48.0
Index   : 561
Interface flags: Ethernet-Switching
VLAN Name         Tag       MAC        MAC + IP    STP        Logical
                            limit      limit       State      interface flags
VL11-OFFICE-1F    11        16383      0           Forwarding
VL12-OFFICE-2F    12        16383      0           Forwarding
VL51-VOIP         51        16383      0           Forwarding
VL99-MGMT         99        16383      0           Forwarding
VL999-NATIVE      999       16383      0           Forwarding
```

```text
admin@sw1> show vlans VL11-OFFICE-1F
Routing instance        VLAN name             Tag          Interfaces
default-switch          VL11-OFFICE-1F        11
                                                           ge-0/0/1.0*
                                                           ge-0/0/2.0
                                                           ge-0/0/48.0*
```

★★★★★ 這個輸出證明：`ge-0/0/1`（Access）與 `ge-0/0/48`（Trunk）
**都承載 VLAN 11**——這就是「VLAN 跨交換器延伸」的實際樣子。

> [!info]- Cisco IOS 對照
> ```cisco
> ! 建立 VLAN
> Switch(config)# vlan 11
> Switch(config-vlan)#  name VL11-OFFICE-1F
> Switch(config-vlan)# vlan 999
> Switch(config-vlan)#  name VL999-NATIVE
> Switch(config-vlan)# exit
>
> ! Access 埠
> Switch(config)# interface GigabitEthernet1/0/1
> Switch(config-if)#  description 1F-A01
> Switch(config-if)#  switchport mode access          ← ★★★★★ 強制 access，不協商
> Switch(config-if)#  switchport access vlan 11
> Switch(config-if)#  switchport nonegotiate          ← ★★★★★ 關閉 DTP，防 switch spoofing
> Switch(config-if)#  spanning-tree portfast
> Switch(config-if)#  spanning-tree bpduguard enable
> Switch(config-if)# exit
>
> ! 批次設定
> Switch(config)# interface range GigabitEthernet1/0/1-24
> Switch(config-if-range)#  switchport mode access
> Switch(config-if-range)#  switchport access vlan 11
>
> ! Trunk 埠
> Switch(config)# interface GigabitEthernet1/0/48
> Switch(config-if)#  description Uplink to core-sw1
> Switch(config-if)#  switchport trunk encapsulation dot1q   ← 部分機型需要
> Switch(config-if)#  switchport mode trunk
> Switch(config-if)#  switchport trunk allowed vlan 11,12,51,99,999
> Switch(config-if)#  switchport trunk native vlan 999
> Switch(config-if)#  switchport nonegotiate
>
> Switch# show vlan brief
> Switch# show interfaces trunk
> Port        Mode         Encapsulation  Status        Native vlan
> Gi1/0/48    on           802.1q         trunking      999
> Port        Vlans allowed on trunk
> Gi1/0/48    11,12,51,99,999
> ```
> ★★★★★ Cisco 專有的三個重點，Juniper 沒有：
> 1. **DTP（Dynamic Trunking Protocol）**：埠預設會自動協商成 Trunk，
>    這是 switch spoofing 攻擊的入口。**每個終端埠都要加 `switchport nonegotiate`。**
> 2. **`switchport mode access` 必須明寫**，只寫 `switchport access vlan 11` 不夠，
>    埠仍可能被協商成 Trunk。
> 3. **VTP（VLAN Trunking Protocol）**：會自動同步 VLAN 資料庫，
>    ★★★★★ 一台設定錯誤的交換器可以**清空全網的 VLAN 資料庫**。
>    實務建議 `vtp mode transparent` 或 `vtp mode off`，手動管理 VLAN。

### 步驟 5：建立 L3 介面（VLAN 間路由）★★★★

```text
[edit]
admin@core-sw1# set vlans VL11-OFFICE-1F l3-interface irb.11
admin@core-sw1# set interfaces irb unit 11 description "VL11 Office 1F Gateway"
admin@core-sw1# set interfaces irb unit 11 family inet address 10.37.11.254/24
admin@core-sw1# commit confirmed 5
admin@core-sw1# commit

admin@core-sw1> show interfaces terse irb.11
Interface               Admin Link Proto    Local                 Remote
irb.11                  up    up   inet     10.37.11.254/24
```

★★★★ **只有需要在這台設備做閘道的 VLAN 才建 `irb`**。
規劃表寫「L3 邊界在防火牆」的 VLAN（伺服器、訪客、DMZ、監視器），
交換器上**只建 VLAN 不建 `irb`**，讓流量必須送到防火牆。

> [!info]- Cisco IOS 對照
> ```cisco
> Switch(config)# ip routing                        ← ★★★★★ 別忘了這行，否則 SVI 不轉送
> Switch(config)# interface Vlan11
> Switch(config-if)#  description VL11 Office 1F Gateway
> Switch(config-if)#  ip address 10.37.11.254 255.255.255.0
> Switch(config-if)#  no shutdown
> Switch# show ip interface brief | include Vlan
> ```
> ★★★★★ Cisco 的 `ip routing` 預設是**關閉**的，
> 只建 SVI 而忘了開它，症狀是「每個 VLAN 內部都通、VLAN 之間全部不通」，
> 而設定檔看起來完全正常。這是 Cisco 上最經典的漏設。

### 步驟 6：用 tcpdump 親眼看見 VLAN 標籤 ★★★★★

這一步是本篇的精華：**把抽象的「標籤」變成看得見的東西**。

**準備**：找一台 Linux 主機接在 Trunk 埠上（或用埠鏡射把 Trunk 流量複製過來）。

```bash
$ sudo tcpdump -i ens18 -nn -e -c 5 vlan
tcpdump: verbose output suppressed, use -v[v]... for full protocol decode
listening on ens18, link-type EN10MB (Ethernet), snapshot length 262144 bytes
09:31:02.114523 aa:aa:aa:aa:aa:aa > ff:ff:ff:ff:ff:ff, ethertype 802.1Q (0x8100),
  length 64: vlan 11, p 0, ethertype ARP (0x0806),
  Request who-has 10.37.11.254 tell 10.37.11.50, length 46
09:31:02.114891 bb:bb:bb:bb:bb:bb > aa:aa:aa:aa:aa:aa, ethertype 802.1Q (0x8100),
  length 64: vlan 11, p 0, ethertype ARP (0x0806),
  Reply 10.37.11.254 is-at bb:bb:bb:bb:bb:bb, length 46
09:31:03.220118 00:1b:a9:55:66:77 > 01:80:c2:00:00:00, ethertype 802.1Q (0x8100),
  length 64: vlan 51, p 5, ethertype IPv4 (0x0800), 10.37.51.30.5060 > ...
```

★★★★★ 逐項對照前面的標籤結構：

| 輸出片段 | 對應欄位 | 說明 |
| --- | --- | --- |
| `ethertype 802.1Q (0x8100)` | **TPID** | 就是那個固定的 `0x8100` |
| `vlan 11` | **VID** | VLAN ID |
| `p 0` / `p 5` | **PCP** | ★★★★ 優先權；IP 電話那筆是 `p 5`，正是語音的標準優先權 |
| `ethertype ARP` / `ethertype IPv4` | 內層類型 | 標籤後面才是原本的類型欄位 |

**只看某個 VLAN：**

```bash
$ sudo tcpdump -i ens18 -nn -e vlan 11
```

**看沒有標籤的流量（Native VLAN 的流量長這樣）：**

```bash
$ sudo tcpdump -i ens18 -nn -e -c 3 'not vlan'
09:31:10.552310 00:1b:a9:11:22:33 > ff:ff:ff:ff:ff:ff, ethertype ARP (0x0806),
  length 60: Request who-has 10.37.99.30 tell 10.37.99.11, length 46
```

★★★★★ **這是排查 Native VLAN 問題的關鍵手法**：
如果你在 Trunk 上看到不該出現的無標籤流量，代表兩端 Native VLAN 設定有問題。

**在 Linux 上建立 VLAN 子介面（讓一台主機同時在多個 VLAN）：**

```bash
$ sudo ip link add link ens18 name ens18.11 type vlan id 11
$ sudo ip addr add 10.37.11.250/24 dev ens18.11
$ sudo ip link set ens18.11 up

$ ip -d link show ens18.11
5: ens18.11@ens18: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP
    link/ether be:24:11:5a:7c:31 brd ff:ff:ff:ff:ff:ff promiscuity 0
    vlan protocol 802.1Q id 11 <REORDER_HDR>

$ ping -c 2 10.37.11.254
PING 10.37.11.254 (10.37.11.254) 56(84) bytes of data.
64 bytes from 10.37.11.254: icmp_seq=1 ttl=64 time=0.483 ms
64 bytes from 10.37.11.254: icmp_seq=2 ttl=64 time=0.412 ms
```

★★★★ 這是**驗證 Trunk 是否正確承載某個 VLAN** 最快的方法：
在 Trunk 埠上接一台 Linux，建對應的 VLAN 子介面，ping 該 VLAN 的閘道。
通了就代表 Trunk 允許清單、Native VLAN、L3 介面全部正確。

**永久化（netplan）：**

```yaml
# /etc/netplan/02-vlans.yaml
network:
  version: 2
  ethernets:
    ens18: {}
  vlans:
    ens18.11:
      id: 11
      link: ens18
      addresses: [10.37.11.250/24]
    ens18.99:
      id: 99
      link: ens18
      addresses: [10.37.99.20/27]
```

```bash
$ sudo netplan try
Do you want to keep these settings?
Press ENTER before the timeout to accept the new configuration
Changes will revert in 120 seconds
```

## 進階應用

### ★★★★★ 機關典型 VLAN 規劃表

這是本篇最實用的一張表。**每個 VLAN 不只是一個編號，還配一組必備管制**：

| VLAN | 名稱 | 用途 | L3 邊界 | ★ 必備管制措施 | 星級 |
| --- | --- | --- | --- | --- | --- |
| **11-39** | OFFICE-xF | 辦公終端 | 核心 | Access 埠、BPDU guard、MAC limit、DHCP snooping | ★★★★ |
| **41-49** | WIFI-STAFF | 員工無線 | 核心 | 802.1X 或 WPA3-Enterprise；AP 上行為 Trunk | ★★★ |
| **51-59** | VOIP | IP 電話 | 核心 | Voice VLAN、PCP=5 優先權、只放行 SIP/RTP | ★★★★ |
| **61-69** | CCTV | 監視器與門禁 | ★★★★★ **防火牆** | 全靜態 IP、**禁止對外上網**、只放行 NVR 需要的埠 | ★★★★★ |
| **65** | PRINTER | 印表機事務機 | 核心 | DHCP 保留、限制只接受內網列印埠 | ★★★ |
| **70-79** | GUEST | 訪客無線 | ★★★★★ **防火牆** | ★★★★★ **只放行 HTTP/HTTPS/DNS 出外網，內網全阻擋**；AP 客戶端隔離；DHCP 租期 1-2 小時 | ★★★★★ |
| **80-89** | DMZ | 對外服務 | ★★★★★ **防火牆** | 單向規則（外→DMZ 特定埠、DMZ→內網原則禁止） | ★★★★★ |
| **90-98** | SERVER | 內部伺服器 | ★★★★★ **防火牆** | 依服務開埠、東西向也要管制、記錄所有拒絕 | ★★★★★ |
| **99** | MGMT | 網管／帶外管理 | 核心＋ACL | ★★★★★ 只允許資訊室固定 IP 與跳板機、不掛 DHCP、全靜態 | ★★★★★ |
| **999** | NATIVE | Trunk 的 Native | 無 | ★★★★★ **完全不放任何裝置**，純粹佔位 | ★★★★★ |
| **1** | default | 出廠預設 | 無 | ★★★★★ **完全不使用** | ★★★★★ |

★★★★★ **「L3 邊界」與「必備管制措施」這兩欄才是這張表的價值**。
只列 VLAN 編號的規劃表，等於什麼都沒規劃。

### ★★★★ Trunk 允許清單：最小權限原則

```text
❌ 壞做法
admin@sw1# set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members all

✅ 好做法：只列這條 Trunk「真的需要」的 VLAN
admin@sw1# set interfaces ge-0/0/48 unit 0 family ethernet-switching \
             vlan members [ VL11-OFFICE-1F VL51-VOIP VL999-NATIVE ]
```

★★★★★ **為什麼**：
1. **資安**：1F 的交換器不需要承載伺服器 VLAN，放行了就是多一條攻擊路徑。
2. **廣播範圍**：Trunk 上承載的每個 VLAN，其廣播都會佔用這條上行的頻寬。
   放行 20 個 VLAN 卻只用 3 個，等於白白浪費 17 個 VLAN 的廣播流量。
3. **STP**：每個 VLAN 一個 STP 實例（PVST）或映射到 MSTP instance，
   VLAN 越多收斂越慢。

★★★★ **例外**：核心之間的互連 Trunk 通常確實需要承載全部 VLAN，
這時候明列清單即可，仍不建議用 `all`（新增 VLAN 時強迫你思考要不要放行）。

### ★★★★ VLAN 對 STP 的影響

| 模式 | 說明 | VLAN 多時的影響 | 星級 |
| --- | --- | --- | --- |
| **RSTP**（單一實例） | 全部 VLAN 共用一棵樹 | ★★★ 無法做每 VLAN 負載分擔 | ★★★ |
| **VSTP / PVST+** | 每個 VLAN 一棵樹 | ★★★★ VLAN 多時 CPU 負擔大（Juniper VSTP 有數量上限） | ★★★★ |
| **MSTP** | VLAN 分組映射到少數幾棵樹 | ★★★★★ 兼顧負載分擔與擴充性，**大量 VLAN 時的正解** | ★★★★ |

★★★★ **機關規模的實務建議**：VLAN 數量在 20 個以內、
上行用鏈路聚合或 Virtual Chassis 而非依賴 STP 收斂時，
**RSTP 就夠了**，不用引入 MSTP 的複雜度。
詳見 [[040-01-16-guide-網路設備-鏈路聚合與STP]]。

### ★★★★ 虛擬化主機的 Trunk 接法

Proxmox VE / VMware ESXi 上跑多個 VLAN 的 VM 時：

```text
實體交換器埠 → 設為 Trunk，允許清單列出所有 VM 會用到的 VLAN
                ↓
虛擬化主機的實體網卡 → 加入虛擬交換器（Linux bridge / vSwitch）
                ↓
虛擬交換器 → 啟用 VLAN aware
                ↓
每台 VM 的虛擬網卡 → 指定一個 VLAN tag（等同虛擬的 Access 埠）
```

Proxmox VE 的 Linux bridge 設定（`/etc/network/interfaces`）：

```ini
auto vmbr0
iface vmbr0 inet static
    address 10.37.99.21/27
    gateway 10.37.99.30
    bridge-ports enp1s0
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
    bridge-vids 11-13 51 90 99
```

★★★★ 三個常見錯誤：

| 錯誤 | 症狀 | 星級 |
| --- | --- | --- |
| 實體埠設成 Access | ★★★★★ 所有 VM 都只能在一個 VLAN，或全部不通 | ★★★★★ |
| `bridge-vids` 沒列到需要的 VLAN | 該 VLAN 的 VM 不通，其他正常 | ★★★★ |
| 忘記 `bridge-vlan-aware yes` | VLAN tag 設了但沒作用 | ★★★★ |

### ★★★ 語音 VLAN 的完整設定

```text
[edit]
admin@sw1# set interfaces ge-0/0/5 unit 0 family ethernet-switching interface-mode access
admin@sw1# set interfaces ge-0/0/5 unit 0 family ethernet-switching vlan members VL11-OFFICE-1F
admin@sw1# set switch-options voip interface ge-0/0/5.0 vlan VL51-VOIP
admin@sw1# set switch-options voip interface ge-0/0/5.0 forwarding-class assured-forwarding
admin@sw1# set protocols lldp-med interface ge-0/0/5
admin@sw1# commit
```

★★★★ **`lldp-med` 是關鍵**：IP 電話透過 LLDP-MED 從交換器學到
「語音 VLAN 是 51」，才會自己打標籤。沒開 LLDP-MED 的話，
電話拿不到 VLAN 資訊，會落到 Access VLAN（VLAN 11）去搶 DHCP。

> [!info]- Cisco IOS 對照
> ```cisco
> Switch(config)# interface GigabitEthernet1/0/5
> Switch(config-if)#  switchport mode access
> Switch(config-if)#  switchport access vlan 11
> Switch(config-if)#  switchport voice vlan 51
> Switch(config-if)#  mls qos trust cos
> Switch# show interfaces gigabitEthernet 1/0/5 switchport
> Administrative Mode: static access
> Access Mode VLAN: 11 (VL11-OFFICE-1F)
> Voice VLAN: 51 (VL51-VOIP)
> ```

### ★★★★ VLAN 變更的安全流程

改 VLAN 的風險等級和改 IP 一樣高。標準流程：

```text
1. ★★★★★ 先確認你自己是從哪條路連進來的
   show system users     ← 看自己的來源 IP
   若走的是要改的那個 VLAN，先換到帶外管理路徑

2. 備份現有設定
   show configuration | save /var/tmp/before-vlan-change.conf

3. 用 commit confirmed 保護
   commit confirmed 5

4. 驗證（在回退時限內做完）
   show vlans
   show ethernet-switching interface <改動的埠>
   從終端 ping 閘道

5. 確認無誤才 commit
   commit

6. 出問題時回退
   rollback 1 && commit        ← 或直接等 confirmed 逾時自動回退
```

★★★★★ **`commit confirmed` 的倒數期間不要離開終端機**，
也不要在那五分鐘裡做其他修改（後續的 `commit` 會把 confirmed 也一起確認掉）。

## 完整實戰範例

### 情境

承接 [[040-01-02-guide-網路設備-IP位址規劃與子網切分]] 的規劃表，
現在要在實際設備上把 VLAN 落地。

**設備**：
- `core-sw1`：EX4300-48T，核心，做 VLAN 11/12/51/99 的閘道
- `1f-sw1`：EX2300-48P，1F 接入，PoE（供電給 IP 電話與 AP）
- `fw-01`：防火牆，做 VLAN 70/90 的閘道

**目標 VLAN**：

| VLAN | 名稱 | 網段 | 閘道 | L3 邊界 |
| --- | --- | --- | --- | --- |
| 11 | VL11-OFFICE-1F | 10.37.11.0/24 | 10.37.11.254 | core-sw1 |
| 51 | VL51-VOIP | 10.37.51.0/24 | 10.37.51.254 | core-sw1 |
| 70 | VL70-GUEST | 10.37.70.0/25 | 10.37.70.126 | fw-01 |
| 90 | VL90-SERVER | 10.37.90.0/26 | 10.37.90.62 | fw-01 |
| 99 | VL99-MGMT | 10.37.99.0/27 | 10.37.99.30 | core-sw1（含 ACL） |
| 999 | VL999-NATIVE | 不配網段 | 無 | 無 |

**埠規劃（1f-sw1）**：

| 埠 | 用途 | 模式 | VLAN |
| --- | --- | --- | --- |
| ge-0/0/1 ~ 30 | 使用者座位（PC + IP 電話） | Access + Voice | 11 + 51 |
| ge-0/0/31 ~ 40 | 印表機、事務機 | Access | 11 |
| ge-0/0/41 ~ 44 | 無線 AP | Trunk | 11, 70, 999 |
| ge-0/0/45 ~ 46 | 保留 | disable | — |
| ge-0/0/47 | 網管用臨時埠 | Access | 99 |
| ge-0/0/48 | 上行到 core-sw1 | Trunk | 11, 51, 70, 99, 999 |

### 步驟 1：在 1f-sw1 上建 VLAN ★★★★

```text
admin@1f-sw1> configure
Entering configuration mode

[edit]
admin@1f-sw1# set vlans VL11-OFFICE-1F vlan-id 11
admin@1f-sw1# set vlans VL51-VOIP      vlan-id 51
admin@1f-sw1# set vlans VL70-GUEST     vlan-id 70
admin@1f-sw1# set vlans VL99-MGMT      vlan-id 99
admin@1f-sw1# set vlans VL999-NATIVE   vlan-id 999 description "Native only, no host"
```

★★★★ 注意 **1f-sw1 上沒有 VLAN 90**——伺服器 VLAN 不需要延伸到 1F 接入層，
最小權限原則。

### 步驟 2：使用者座位（Access + Voice）★★★★★

```text
[edit]
admin@1f-sw1# wildcard range set interfaces ge-0/0/[1-30] unit 0 \
                family ethernet-switching interface-mode access
admin@1f-sw1# wildcard range set interfaces ge-0/0/[1-30] unit 0 \
                family ethernet-switching vlan members VL11-OFFICE-1F
admin@1f-sw1# wildcard range set switch-options voip interface ge-0/0/[1-30].0 \
                vlan VL51-VOIP
admin@1f-sw1# wildcard range set protocols lldp-med interface ge-0/0/[1-30]

[edit]
admin@1f-sw1# set interfaces ge-0/0/1 description "1F-A01"
admin@1f-sw1# set interfaces ge-0/0/2 description "1F-A02"
```

★★★★ **每個埠都要有 description**。半年後你只會記得「A01 座位」，
不會記得「ge-0/0/1」。埠描述是最便宜的文件。

### 步驟 3：AP 的 Trunk 埠 ★★★★

```text
[edit]
admin@1f-sw1# wildcard range set interfaces ge-0/0/[41-44] unit 0 \
                family ethernet-switching interface-mode trunk
admin@1f-sw1# wildcard range set interfaces ge-0/0/[41-44] unit 0 \
                family ethernet-switching vlan members [ VL11-OFFICE-1F VL70-GUEST VL999-NATIVE ]
admin@1f-sw1# wildcard range set interfaces ge-0/0/[41-44] native-vlan-id 999
admin@1f-sw1# set interfaces ge-0/0/41 description "AP-1F-01"
admin@1f-sw1# set interfaces ge-0/0/42 description "AP-1F-02"
```

★★★★★ AP 需要 Trunk 是因為它同時廣播**員工 SSID（VLAN 11）**與
**訪客 SSID（VLAN 70）**，兩個 SSID 的流量要用不同的標籤送回交換器。

### 步驟 4：上行 Trunk ★★★★★

```text
[edit]
admin@1f-sw1# set interfaces ge-0/0/48 description "Uplink -> core-sw1 ge-0/0/45"
admin@1f-sw1# set interfaces ge-0/0/48 unit 0 family ethernet-switching interface-mode trunk
admin@1f-sw1# set interfaces ge-0/0/48 unit 0 family ethernet-switching \
                vlan members [ VL11-OFFICE-1F VL51-VOIP VL70-GUEST VL99-MGMT VL999-NATIVE ]
admin@1f-sw1# set interfaces ge-0/0/48 native-vlan-id 999
```

### 步驟 5：管理 IP 與未使用埠 ★★★★

```text
[edit]
admin@1f-sw1# set vlans VL99-MGMT l3-interface irb.99
admin@1f-sw1# set interfaces irb unit 99 family inet address 10.37.99.21/27
admin@1f-sw1# set routing-options static route 0.0.0.0/0 next-hop 10.37.99.30

# ★★★★★ 未使用的埠：關閉並放進一個沒有出口的 VLAN
admin@1f-sw1# set vlans VL666-PARKING vlan-id 666 description "Disabled ports"
admin@1f-sw1# wildcard range set interfaces ge-0/0/[45-46] disable
admin@1f-sw1# wildcard range set interfaces ge-0/0/[45-46] unit 0 \
                family ethernet-switching vlan members VL666-PARKING
```

★★★★★ **未使用埠的處理是資安稽核必查項**：
`disable` 讓埠不會 link up，放進 parking VLAN 則是雙保險——
即使有人誤把它 enable，插上去也連不到任何東西。

### 步驟 6：提交與驗證 ★★★★★

```text
[edit]
admin@1f-sw1# show | compare
[edit interfaces]
+   ge-0/0/1 {
+       description 1F-A01;
+       unit 0 {
+           family ethernet-switching {
+               interface-mode access;
+               vlan {
+                   members VL11-OFFICE-1F;
+               }
+           }
+       }
+   }
... （略）

[edit]
admin@1f-sw1# commit confirmed 5
commit confirmed will be automatically rolled back in 5 minutes unless confirmed
commit complete

[edit]
admin@1f-sw1# run show vlans
Routing instance        VLAN name             Tag          Interfaces
default-switch          VL11-OFFICE-1F        11
                                                           ge-0/0/1.0*
                                                           ge-0/0/2.0*
                                                           ...
                                                           ge-0/0/41.0*
                                                           ge-0/0/48.0*
default-switch          VL51-VOIP             51
                                                           ge-0/0/1.0*
                                                           ge-0/0/48.0*
default-switch          VL70-GUEST            70
                                                           ge-0/0/41.0*
                                                           ge-0/0/48.0*
default-switch          VL99-MGMT             99
                                                           ge-0/0/47.0
                                                           ge-0/0/48.0*
default-switch          VL999-NATIVE          999
                                                           ge-0/0/41.0*
                                                           ge-0/0/48.0*

[edit]
admin@1f-sw1# commit
commit complete
```

★★★★★ **檢查點**：
- VLAN 11 同時出現在 Access 埠與 Trunk 埠 ✓
- VLAN 70 **只出現在 AP 埠與上行**，沒有出現在任何使用者座位 ✓
- VLAN 999 只在 Trunk 埠上 ✓（沒有任何終端在裡面）
- **VLAN 90 完全不存在於這台** ✓（伺服器 VLAN 沒有延伸下來）

### 步驟 7：核心端的對應設定 ★★★★

```text
[edit]
admin@core-sw1# set interfaces ge-0/0/45 description "Downlink -> 1f-sw1 ge-0/0/48"
admin@core-sw1# set interfaces ge-0/0/45 unit 0 family ethernet-switching interface-mode trunk
admin@core-sw1# set interfaces ge-0/0/45 unit 0 family ethernet-switching \
                  vlan members [ VL11-OFFICE-1F VL51-VOIP VL70-GUEST VL99-MGMT VL999-NATIVE ]
admin@core-sw1# set interfaces ge-0/0/45 native-vlan-id 999
admin@core-sw1# commit confirmed 5
admin@core-sw1# commit
```

★★★★★ **兩端的 Native VLAN 必須一致（都是 999）**，
允許清單也應該一致。這是 Trunk 設定的第一鐵律。

### 步驟 8：實測驗證 ★★★★★

**8-1 從使用者座位的 PC：**

```text
C:\> ipconfig
   IPv4 位址 . . . . . . . . . . . . : 10.37.11.113
   子網路遮罩 . . . . . . . . . . . .: 255.255.255.0
   預設閘道 . . . . . . . . . . . . .: 10.37.11.254

C:\> ping 10.37.11.254
回覆自 10.37.11.254: 位元組=32 時間<1ms TTL=64
```

✓ 拿到 VLAN 11 的 DHCP 位址（`.100–.199` 範圍內），閘道通。

**8-2 驗證隔離：從 VLAN 11 應該連不到伺服器 VLAN**

```text
C:\> ping 10.37.90.20
要求等候逾時。
要求等候逾時。

C:\> Test-NetConnection 10.37.90.20 -Port 22
警告: TCP connect to (10.37.90.20 : 22) failed
TcpTestSucceeded : False
```

★★★★★ **不通才是對的**——VLAN 90 的閘道在防火牆上，
沒有放行規則就連不到。**這一步是驗收隔離是否生效的關鍵，不能跳過。**

**8-3 在 Trunk 上抓包確認標籤**

在 `ge-0/0/47`（管理埠）接一台 Linux，設鏡射把 `ge-0/0/48` 的流量複製過來：

```text
[edit]
admin@1f-sw1# set forwarding-options analyzer TRUNK-MON input ingress interface ge-0/0/48.0
admin@1f-sw1# set forwarding-options analyzer TRUNK-MON output interface ge-0/0/47.0
admin@1f-sw1# commit
```

```bash
$ sudo tcpdump -i ens18 -nn -e -c 6 vlan
09:47:11.223401 aa:aa:aa:aa:aa:aa > ff:ff:ff:ff:ff:ff, ethertype 802.1Q (0x8100),
  length 64: vlan 11, p 0, ethertype ARP (0x0806),
  Request who-has 10.37.11.254 tell 10.37.11.113, length 46
09:47:11.556210 00:1b:a9:33:44:55 > 01:00:5e:00:00:fb, ethertype 802.1Q (0x8100),
  length 90: vlan 51, p 5, ethertype IPv4 (0x0800),
  10.37.51.42.5353 > 224.0.0.251.5353: 0 [2q] PTR ...
09:47:12.010933 c2:44:11:88:99:aa > ff:ff:ff:ff:ff:ff, ethertype 802.1Q (0x8100),
  length 342: vlan 70, p 0, ethertype IPv4 (0x0800),
  0.0.0.0.68 > 255.255.255.255.67: BOOTP/DHCP, Request from c2:44:11:88:99:aa
```

★★★★★ 三筆各自證明了一件事：

| 封包 | 證明 |
| --- | --- |
| `vlan 11, p 0` ARP | 辦公 VLAN 正常帶標籤通過 Trunk |
| `vlan 51, p 5` | ★★★★ IP 電話的流量帶了標籤**且優先權是 5**，QoS 標記正確 |
| `vlan 70` DHCP Request | 訪客 SSID 的流量走 VLAN 70，沒有跑到 VLAN 11 去 |

**8-4 驗證 Native VLAN 沒有意外流量：**

```bash
$ sudo timeout 60 tcpdump -i ens18 -nn -e 'not vlan' -c 20
0 packets captured
```

★★★★★ **理想結果是 0 個封包**（或只有極少的 STP BPDU）。
如果看到大量無標籤的使用者流量，代表**有終端落在 Native VLAN 裡**，
這正是 double tagging 攻擊的前提條件，必須立刻修正。

### 驗收檢查表

| # | 檢查項 | 驗證指令 | 通過條件 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 所有 VLAN 已建立 | `show vlans` | 與規劃表一致 | ★★★★ |
| 2 | 終端埠全部是 Access | `show ethernet-switching interface` | 沒有終端埠是 trunk | ★★★★★ |
| 3 | Trunk 兩端 Native VLAN 一致 | 兩端 `show configuration interfaces <埠>` | 都是 999 | ★★★★★ |
| 4 | Trunk 允許清單最小化 | 同上 | 沒有 `all`，只列必要 VLAN | ★★★★★ |
| 5 | Native VLAN 沒有任何終端 | `show vlans VL999-NATIVE` | 只有 Trunk 埠 | ★★★★★ |
| 6 | VLAN 1 未使用 | `show vlans default` | 沒有 up 的 access 埠 | ★★★★★ |
| 7 | 未使用埠已 disable | `show interfaces terse \| match down` | 全部 admin down | ★★★★ |
| 8 | 每個埠有 description | `show configuration interfaces` | 無空白 | ★★★ |
| 9 | 終端拿到正確網段 DHCP | 終端 `ipconfig` / `ip -br addr` | 網段與 VLAN 對應 | ★★★★★ |
| 10 | 該隔離的 VLAN 真的不通 | 從辦公 VLAN `Test-NetConnection` 伺服器 | 逾時／拒絕 | ★★★★★ |
| 11 | Trunk 上抓到正確標籤 | `tcpdump -e vlan` | VID 與規劃一致 | ★★★★ |
| 12 | 語音流量優先權正確 | `tcpdump -e vlan 51` | `p 5` | ★★★★ |
| 13 | Native VLAN 無使用者流量 | `tcpdump -e 'not vlan'` | 幾乎 0 封包 | ★★★★★ |
| 14 | 設定已備份 | `show configuration \| save` | 有檔案且已存到外部 | ★★★★ |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 | 星級 |
| --- | --- | --- | --- |
| PC 接上去 link up 但完全不通、拿不到 IP | 埠被設成 Trunk，PC 看不懂標籤而丟棄所有 frame | 改成 `interface-mode access` 並指定 VLAN；Cisco 另加 `switchport nonegotiate` | ★★★★★ |
| 兩個不該互通的 VLAN 神秘互通 | ★★★★★ Trunk 兩端 **Native VLAN 不一致**（VLAN 洩漏） | 兩端都跑 `show configuration interfaces <trunk>` 比對 `native-vlan-id`；統一改成 999 | ★★★★★ |
| Cisco 記錄檔出現 `%CDP-4-NATIVE_VLAN_MISMATCH` | 同上，CDP 主動偵測到 | 依訊息中的兩端埠號修正 Native VLAN | ★★★★★ |
| 從 Cisco 換成 Juniper 後某些流量不通 | JunOS Trunk **預設丟棄無標籤 frame**，原本靠 Native 傳的流量沒了 | 在 JunOS 上明確設 `native-vlan-id` 並把該 VLAN 列入 `vlan members` | ★★★★ |
| 新增 VLAN 後跨交換器不通、同交換器內正常 | 中間的 Trunk 允許清單沒加上新 VLAN | 路徑上**每一條** Trunk 都要加：`set ... vlan members VLxx` | ★★★★★ |
| 每個 VLAN 內部都通、VLAN 之間全部不通（Cisco） | ★★★★★ 忘了下 `ip routing` | `Switch(config)# ip routing`，再確認 `show ip route` 有 connected 路由 | ★★★★★ |
| VLAN 建了、`irb` 也建了，但介面 down | VLAN 裡沒有任何 up 的埠，`irb` 不會 up | 至少要有一個該 VLAN 的埠 link up；或設 `set interfaces irb unit N family inet ... ` 搭配 dummy 埠 | ★★★★ |
| IP 電話拿到辦公 VLAN 的 IP | LLDP-MED 沒開，電話學不到語音 VLAN | `set protocols lldp-med interface <埠>`；Cisco 確認 `switchport voice vlan` | ★★★★ |
| AP 上的訪客 SSID 拿不到 IP | AP 上行埠沒設 Trunk，或允許清單缺訪客 VLAN | 確認 AP 埠是 Trunk 且含訪客 VLAN；檢查 AP 端 SSID 的 VLAN 對應 | ★★★★ |
| 虛擬機拿不到對應 VLAN 的 IP | 實體埠設成 Access，或 bridge 沒開 `vlan-aware`、`bridge-vids` 沒列 | 實體埠改 Trunk；PVE 設 `bridge-vlan-aware yes` 並補 `bridge-vids` | ★★★★ |
| 訪客可以 ping 到內部印表機 | 訪客 VLAN 的閘道設在核心而非防火牆，或防火牆規則沒擋 | 把訪客 VLAN 的 L3 介面移到防火牆；規則改成「只放行對外」 | ★★★★★ |
| `show vlans` 看到某 VLAN 有終端埠，但規劃表說它只該在 Trunk 上 | 有人手動把埠指派錯 VLAN | `show configuration interfaces <埠>` 確認；比對規劃表修正 | ★★★★ |
| 交換器 CPU 高、log 出現大量 `mac move` | VLAN 內有迴圈（兩條線接同兩台設備、或使用者私接小交換器） | 找出兩個埠並拔掉其一；接入埠開 BPDU guard 與 MAC limit | ★★★★★ |
| Cisco 上一台交換器改動後全網 VLAN 消失 | ★★★★★ **VTP 把錯誤的 VLAN 資料庫同步出去** | 立刻把所有交換器改成 `vtp mode transparent`；從備份還原 VLAN | ★★★★★ |
| Trunk 上抓到大量無標籤的使用者流量 | 有終端落在 Native VLAN 裡 | 把該終端埠改到正確的業務 VLAN；Native VLAN 保持淨空 | ★★★★★ |
| 改完 VLAN 自己斷線、救不回來 | 改到自己連線經過的那個 VLAN，且沒有 console/帶外路徑 | ★★★★★ 事前用 `commit confirmed 5`；準備 console 存取，見 [[040-01-04-guide-網路設備-交換器初次設定與連線方式]] | ★★★★★ |
| 新交換器插上就讓全網不通 | 出廠預設所有埠在 VLAN 1，且 STP 參數可能搶成 root | 上架前先在隔離環境完成設定；核心設 root guard | ★★★★★ |

## 安全性注意事項

> [!danger] ★★★★★ VLAN 1 完全不要使用
> VLAN 1 是所有交換器的出廠預設，也是管理協定（STP、CDP、DTP、VTP）
> 預設運行的地方。把使用者放在 VLAN 1 會同時帶來三個問題：
> 1. **Double tagging 攻擊的前提條件**（Native VLAN 預設就是 1）
> 2. 使用者能看到並干擾管理協定
> 3. 任何一台新插上的出廠設備都自動加入你的使用者網段
>
> **標準做法**：所有埠明確指派到業務 VLAN；Trunk 允許清單排除 VLAN 1；
> Native VLAN 改成專用的空 VLAN（例如 999）。

> [!danger] ★★★★★ Native VLAN 必須是「什麼都不放」的專用 VLAN
> Native VLAN 的流量在 Trunk 上是**不帶標籤**傳輸的，
> 這讓它成為 double tagging 攻擊的通道。
> 正確做法：建一個 VLAN 999，**不配 IP、不接任何終端、不建 L3 介面**，
> 只用來當 Trunk 的 Native。這樣即使攻擊者送出雙層標籤封包，
> 外層是 999 也到不了任何地方。

> [!warning] ★★★★★ 終端埠必須強制 Access 並關閉動態協商
> Cisco 的 DTP 會讓埠自動協商成 Trunk，攻擊者只要在自己的機器上
> 模擬交換器行為就能把埠變成 Trunk，然後存取所有 VLAN（switch spoofing）。
>
> ```cisco
> Switch(config-if)# switchport mode access
> Switch(config-if)# switchport nonegotiate
> ```
>
> ★★★★ Juniper 沒有 DTP，天生免疫這個攻擊，但仍應明確設定
> `interface-mode access`，不要依賴預設值。

> [!warning] ★★★★★ Trunk 允許清單就是攻擊面
> 每多放行一個 VLAN，就多一條該 VLAN 可以到達的路徑。
> **1F 的接入交換器不需要承載伺服器 VLAN**——一旦放行了，
> 只要有人能控制 1F 的一個埠或那台交換器，就多一條路可以走。
> 定期稽核每條 Trunk 的允許清單，刪掉不再需要的 VLAN。

> [!warning] ★★★★ 未使用的埠要 disable 並放進 parking VLAN
> 資安稽核的必查項。做法：
> ```text
> set interfaces ge-0/0/45 disable
> set interfaces ge-0/0/45 unit 0 family ethernet-switching vlan members VL666-PARKING
> ```
> 雙保險：`disable` 讓埠不會 link up；即使有人誤 enable，
> parking VLAN 沒有 L3 介面、沒有出口，插上去也到不了任何地方。

> [!warning] ★★★★ 監視器與訪客這兩個 VLAN 最容易被當跳板
> - **監視器**：韌體舊、預設密碼多、常有 CVE。必須獨立 VLAN、
>   閘道在防火牆、**禁止對外網際網路**、只放行到 NVR 的必要埠。
> - **訪客**：閘道在防火牆、只放行 HTTP/HTTPS/DNS 出外網、
>   內網全阻擋、**AP 上啟用客戶端隔離**（訪客之間也不能互連）、
>   DHCP 租期 1～2 小時。
>
> 這兩個網段的規則要**定期驗證**，不能只在建置時測一次。

> [!tip] ★★★★ 搭配的接入層防護
> VLAN 只是分段的骨架，還要配上這些才完整：
> - **BPDU guard**：終端埠收到 BPDU 就關閉（防止私接交換器造成迴圈）
> - **MAC limit**：限制每埠學習的 MAC 數（防 CAM overflow 與私接分享器）
> - **DHCP snooping**：只信任指定埠來的 DHCP 回應（防 rogue DHCP）
> - **Dynamic ARP Inspection**：搭配 DHCP snooping 防 ARP 詐騙
> - **802.1X**：埠級身分認證，未認證的裝置進不了業務 VLAN
>
> 設定細節見 [[040-01-08-guide-Juniper-埠設定與安全]]。

## 速查表

| 概念 | 一句話 | 星級 |
| --- | --- | --- |
| 802.1Q 標籤位置 | 插在來源 MAC 之後、類型欄位之前，共 4 位元組 | ★★★★★ |
| TPID | 固定 `0x8100` | ★★★★ |
| VID 位元數 | 12 bit → VLAN 1～4094 可用 | ★★★★★ |
| PCP | 3 bit 優先權，語音用 5 | ★★★★ |
| Access 埠 | 送出**不帶**標籤；接終端 | ★★★★★ |
| Trunk 埠 | 送出**帶**標籤；接設備 | ★★★★★ |
| Native VLAN | Trunk 上唯一不帶標籤的 VLAN | ★★★★★ |
| Native 不一致 | 造成 VLAN 洩漏，兩端各自看都正常 | ★★★★★ |
| VLAN ↔ 子網 | 一對一，不多不少 | ★★★★★ |
| VLAN 切了 ≠ 隔離了 | 要在 L3 邊界加管制才算隔離 | ★★★★★ |
| Switch spoofing | 假裝成交換器協商 Trunk；防護＝強制 access + 關 DTP | ★★★★★ |
| Double tagging | 雙層標籤鑽 Native VLAN；防護＝Native 用空 VLAN | ★★★★★ |

| 動作 | JunOS | Cisco IOS | 星級 |
| --- | --- | --- | --- |
| 看所有 VLAN | `show vlans` | `show vlan brief` | ★★★★★ |
| 看某 VLAN 的埠 | `show vlans VL11-OFFICE-1F` | `show vlan id 11` | ★★★★ |
| 看埠的 VLAN 歸屬 | `show ethernet-switching interface ge-0/0/1` | `show interfaces gi1/0/1 switchport` | ★★★★★ |
| 看所有 Trunk | `show interfaces terse` ＋ 檢視設定 | `show interfaces trunk` | ★★★★★ |
| 建 VLAN | `set vlans VL11 vlan-id 11` | `vlan 11` + `name VL11` | ★★★★ |
| 設 Access | `set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access` | `switchport mode access` | ★★★★★ |
| 指派 Access VLAN | `... vlan members VL11` | `switchport access vlan 11` | ★★★★★ |
| 設 Trunk | `... interface-mode trunk` | `switchport mode trunk` | ★★★★★ |
| Trunk 允許清單 | `... vlan members [ VL11 VL51 ]` | `switchport trunk allowed vlan 11,51` | ★★★★★ |
| 設 Native VLAN | `set interfaces ge-0/0/48 native-vlan-id 999` | `switchport trunk native vlan 999` | ★★★★★ |
| 關閉動態協商 | （無 DTP，不需要） | `switchport nonegotiate` | ★★★★★ |
| 建 L3 介面 | `set vlans VL11 l3-interface irb.11` ＋ `set interfaces irb unit 11 family inet address ...` | `interface Vlan11` + `ip address ...` | ★★★★ |
| 開啟路由 | 預設開啟 | ★★★★★ `ip routing` | ★★★★★ |
| 語音 VLAN | `set switch-options voip interface ge-0/0/5.0 vlan VL51` | `switchport voice vlan 51` | ★★★★ |
| 批次設埠 | `wildcard range set interfaces ge-0/0/[1-24] ...` | `interface range gi1/0/1-24` | ★★★★ |
| 安全提交 | `commit confirmed 5` | `reload in 10`（未存檔則回退） | ★★★★★ |
| 回退 | `rollback 1` + `commit` | `copy startup-config running-config` | ★★★★ |

| 驗證工具 | 指令 | 看什麼 | 星級 |
| --- | --- | --- | --- |
| 抓所有帶標籤流量 | `sudo tcpdump -i ens18 -nn -e vlan` | VID 與 PCP | ★★★★★ |
| 抓特定 VLAN | `sudo tcpdump -i ens18 -nn -e vlan 11` | 該 VLAN 的流量 | ★★★★ |
| 抓無標籤流量 | `sudo tcpdump -i ens18 -nn -e 'not vlan'` | ★★★★★ Native VLAN 有沒有異常流量 | ★★★★★ |
| 建 VLAN 子介面 | `sudo ip link add link ens18 name ens18.11 type vlan id 11` | — | ★★★★ |
| 看子介面 VLAN | `ip -d link show ens18.11` | `vlan protocol 802.1Q id 11` | ★★★★ |
| 測隔離是否生效 | `nc -vz 10.37.90.20 22` / `Test-NetConnection` | ★★★★★ 該不通就要不通 | ★★★★★ |

| 機關 VLAN 編號慣例 | 用途 | 星級 |
| --- | --- | --- |
| 1 | ★★★★★ 出廠預設，完全不用 | ★★★★★ |
| 11–39 | 辦公終端（依樓層／部門） | ★★★★ |
| 41–49 | 員工無線 | ★★★ |
| 51–59 | IP 電話 | ★★★ |
| 61–69 | 監視器、門禁 | ★★★★ |
| 70–79 | 訪客 | ★★★★ |
| 80–89 | DMZ | ★★★★ |
| 90–98 | 伺服器 | ★★★★★ |
| 99 | 網管／帶外管理 | ★★★★★ |
| 666 | 未使用埠 parking | ★★★★ |
| 999 | Trunk Native 專用（淨空） | ★★★★★ |

## 練習題

> [!question]- 練習 1：看懂 tcpdump 的標籤（★★★★）
> 你在 Trunk 埠的鏡射上抓到這一筆：
>
> ```text
> 10:22:31.445120 00:1b:a9:aa:bb:cc > 01:00:5e:00:00:fb,
>   ethertype 802.1Q (0x8100), length 90: vlan 51, p 5,
>   ethertype IPv4 (0x0800), 10.37.51.42.5353 > 224.0.0.251.5353: ...
> ```
>
> 回答：(a) TPID 是多少？(b) VID 是多少？屬於哪個 VLAN？
> (c) PCP 是多少？代表什麼？(d) 目的 MAC `01:00:5e:...` 是什麼類型的位址？
>
> **參考答案**
> (a) **TPID = `0x8100`**，就是輸出中的 `ethertype 802.1Q (0x8100)`，
> 這是 802.1Q 標籤的固定識別碼。
> (b) **VID = 51**，對應規劃表的 `VL51-VOIP`（IP 電話 VLAN）。
> (c) **PCP = 5**（`p 5`）。★★★★ 5 是語音流量的標準優先權標記，
> 表示這台 IP 電話有正確設定 QoS——這也證明語音 VLAN 設定生效了。
> (d) `01:00:5e:xx:xx:xx` 是 **IPv4 多播（multicast）MAC**。
> 搭配目的 IP `224.0.0.251` 與埠 5353 可知這是 **mDNS**（設備自動探索）封包。

> [!question]- 練習 2：找出設定裡的錯誤（★★★★★）
> 兩台交換器的 Trunk 設定如下，請找出所有問題：
>
> ```text
> # sw-a
> set interfaces ge-0/0/48 unit 0 family ethernet-switching interface-mode trunk
> set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members all
> set interfaces ge-0/0/48 native-vlan-id 1
>
> # sw-b
> set interfaces ge-0/0/48 unit 0 family ethernet-switching interface-mode trunk
> set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members [ VL11 VL51 VL90 ]
> set interfaces ge-0/0/48 native-vlan-id 99
> ```
>
> **參考答案**（4 個問題）
>
> | # | 問題 | 後果 | 星級 |
> | --- | --- | --- | --- |
> | 1 | ★★★★★ **Native VLAN 不一致**（sw-a 是 1、sw-b 是 99） | sw-a 的 VLAN 1 流量與 sw-b 的 VLAN 99（管理網段！）被接通——**使用者可以直接進管理網段** | ★★★★★ |
> | 2 | ★★★★★ **Native VLAN 用 VLAN 1** | double tagging 攻擊的前提；管理協定與使用者流量混在一起 | ★★★★★ |
> | 3 | ★★★★★ **sw-a 用 `vlan members all`** | 所有 VLAN 都放行，違反最小權限；且與 sw-b 的清單不一致，新增 VLAN 時行為不可預期 | ★★★★★ |
> | 4 | ★★★★ **允許清單不一致** | sw-a 放行全部、sw-b 只放三個 → VLAN 70 之類的流量在 sw-a 送得出去但 sw-b 會丟棄，症狀是「單向不通」 | ★★★★ |
>
> **正確設定**：
> ```text
> # 兩端一致
> set interfaces ge-0/0/48 unit 0 family ethernet-switching interface-mode trunk
> set interfaces ge-0/0/48 unit 0 family ethernet-switching \
>     vlan members [ VL11 VL51 VL999-NATIVE ]
> set interfaces ge-0/0/48 native-vlan-id 999
> ```
> ★★★★ 注意：sw-b 原本放行 `VL90`（伺服器），若這條 Trunk 通往接入層，
> 應該一併移除——接入層不需要伺服器 VLAN。

> [!question]- 練習 3：規劃一套機關 VLAN（★★★★）
> 某機關：三層樓、120 名員工、8 台伺服器、
> 32 支 IP 電話、6 台 AP（員工＋訪客兩個 SSID）、
> 24 支網路攝影機、4 台事務機、對外有一台官網伺服器。
>
> 請產出完整 VLAN 規劃表，欄位需包含：VLAN ID、名稱、用途、
> **L3 邊界**、**必備管制措施**。並說明哪些 VLAN 需要延伸到接入層。
>
> **參考答案（示範解）**
>
> | VLAN | 名稱 | 用途 | L3 邊界 | 必備管制 |
> | --- | --- | --- | --- | --- |
> | 11 | VL11-OFFICE-1F | 1F 辦公 | 核心 | Access、BPDU guard、MAC limit、DHCP snooping |
> | 12 | VL12-OFFICE-2F | 2F 辦公 | 核心 | 同上 |
> | 13 | VL13-OFFICE-3F | 3F 辦公 | 核心 | 同上 |
> | 41 | VL41-WIFI-STAFF | 員工無線 | 核心 | WPA3-Enterprise／802.1X |
> | 51 | VL51-VOIP | IP 電話 | 核心 | Voice VLAN、PCP=5、只放行 SIP/RTP |
> | 61 | VL61-CCTV | 網路攝影機 | **防火牆** | 全靜態、**禁止對外上網**、只放行到 NVR |
> | 65 | VL65-PRINTER | 事務機 | 核心 | DHCP 保留、限制列印埠 |
> | 70 | VL70-GUEST | 訪客無線 | **防火牆** | 只放行 HTTP/HTTPS/DNS 出外網、客戶端隔離、租期 2 小時 |
> | 80 | VL80-DMZ | 官網伺服器 | **防火牆** | 外→DMZ 只開 443；DMZ→內網原則禁止 |
> | 90 | VL90-SERVER | 內部伺服器 | **防火牆** | 依服務開埠、東西向管制、記錄拒絕 |
> | 99 | VL99-MGMT | 網管 | 核心＋ACL | 只允許資訊室固定 IP、全靜態 |
> | 666 | VL666-PARKING | 未使用埠 | 無 | 埠 disable |
> | 999 | VL999-NATIVE | Trunk Native | 無 | 淨空，不接任何裝置 |
>
> **延伸到接入層的 VLAN**（★★★★ 最小權限）：
>
> | 接入交換器 | 需承載的 VLAN | 說明 |
> | --- | --- | --- |
> | 1F/2F/3F 樓層交換器 | 該樓層 OFFICE、41、51、65、70、99、999 | ★★★★★ **不含 61、80、90** |
> | 機房交換器 | 90、99、999 | 只給伺服器用 |
> | 監視器專用交換器 | 61、99、999 | 獨立，不與辦公混用 |
> | DMZ 交換器 | 80、99、999 | 接防火牆 DMZ 介面 |
>
> ★★★★★ 關鍵設計：**伺服器（90）、DMZ（80）、監視器（61）三個 VLAN
> 完全不延伸到辦公樓層的接入交換器**。這樣即使有人在辦公室私接設備、
> 或某台樓層交換器被入侵，也碰不到這三個網段的二層。

> [!question]- 練習 4：實作並驗證（★★★★）
> 在實驗環境（實體 EX/Catalyst 或 GNS3/EVE-NG）中：
> 1. 建立 VLAN 11、51、999
> 2. 把 `ge-0/0/1` 設為 Access VLAN 11
> 3. 把 `ge-0/0/48` 設為 Trunk，允許 11、51、999，Native = 999
> 4. 在 `ge-0/0/1` 接一台 PC，確認拿到 VLAN 11 的位址
> 5. 在 Trunk 上做鏡射，用 `tcpdump -e vlan` 抓到帶標籤的流量
> 6. 用 `tcpdump -e 'not vlan'` 確認 Native VLAN 幾乎沒有流量
>
> **驗收標準**
> - `show vlans` 顯示 VLAN 11 同時包含 `ge-0/0/1.0` 與 `ge-0/0/48.0`
> - `show ethernet-switching interface ge-0/0/48` 列出三個 VLAN
> - tcpdump 抓到的封包含 `vlan 11` 字樣
> - ★★★★★ `'not vlan'` 抓到的封包數接近 0（只有偶爾的 STP BPDU）
> - 把 `ge-0/0/1` 誤設成 trunk 後，PC 立刻不通（驗證前面講的原理）

> [!question]- 練習 5：Linux 上驗證 Trunk（★★★）
> 用一台 Linux 主機接在 Trunk 埠上，建立兩個 VLAN 子介面
> （VLAN 11 與 VLAN 99），分別設定 IP，
> 驗證兩個 VLAN 的閘道都 ping 得通。然後寫成 netplan 永久化。
>
> **參考答案**
> ```bash
> $ sudo ip link add link ens18 name ens18.11 type vlan id 11
> $ sudo ip addr add 10.37.11.250/24 dev ens18.11
> $ sudo ip link set ens18.11 up
> $ sudo ip link add link ens18 name ens18.99 type vlan id 99
> $ sudo ip addr add 10.37.99.20/27 dev ens18.99
> $ sudo ip link set ens18.99 up
> $ ping -c 2 10.37.11.254 && ping -c 2 10.37.99.30
> ```
> 永久化：
> ```yaml
> network:
>   version: 2
>   ethernets:
>     ens18: {}
>   vlans:
>     ens18.11: {id: 11, link: ens18, addresses: [10.37.11.250/24]}
>     ens18.99: {id: 99, link: ens18, addresses: [10.37.99.20/27]}
> ```
> ★★★★ 套用時用 `sudo netplan try`。
> ★★★★★ 這個做法本身也是**一台主機同時進入多個 VLAN**，
> 是很方便的驗證工具，但也代表**任何能接到 Trunk 埠的人都能做同樣的事**——
> 這就是為什麼終端埠絕對不能是 Trunk。

> [!question]- 練習 6：模擬 Native VLAN 不一致（★★★★）
> 刻意把 Trunk 兩端的 `native-vlan-id` 設成不同值（例如 A 端 1、B 端 99），
> 然後：
> 1. 在 A 端的 VLAN 1 接一台 PC，設一個 VLAN 99 網段的 IP
> 2. 觀察它能不能 ping 到 VLAN 99 的閘道
> 3. 用 tcpdump 觀察無標籤流量的走向
> 4. 修正 Native VLAN 一致後，重測
>
> **預期結果與說明**
> ★★★★★ 步驟 2 **會通**——這正是問題所在。
> A 端 VLAN 1 的流量以無標籤送出，B 端收到無標籤 frame 就當成 VLAN 99，
> 於是接在 VLAN 1 的 PC 實際上進入了 VLAN 99（管理網段）。
>
> 步驟 3 用 `tcpdump -e 'not vlan'` 會看到**大量無標籤的使用者流量**，
> 這就是 VLAN 洩漏的特徵。
>
> 步驟 4 修正後（兩端都設 999，且 999 淨空），PC 應該完全不通。
>
> ★★★★ 這個實驗值得親手做一次——它會讓你永遠記得
> **「兩端 Native VLAN 一致」不是格式要求，是資安要求**。
> （★★★★★ 只在實驗環境做，絕對不要在正式網路上驗證這件事。）

## 小測驗

Q1. 802.1Q 標籤總共幾個位元組？插在 frame 的哪個位置？
    其中 VID 佔幾個位元？因此 VLAN ID 的可用範圍是多少？

Q2. 用一句話說出 Access 埠與 Trunk 埠最本質的差別。

Q3. 是非題：把一台 PC 接在 Trunk 埠上，PC 可以看到所有 VLAN 的流量。

Q4. Native VLAN 的定義是什麼？如果 Trunk 兩端的 Native VLAN 不一致，
    會發生什麼？為什麼這種故障特別難查？

Q5. 選擇題：下列哪一個是 Native VLAN 的正確設定方式？
    (A) 設成 VLAN 1，因為它是預設值
    (B) 設成使用者最多的辦公 VLAN，效率最好
    (C) 設成一個專用的、不接任何裝置的 VLAN（例如 999）
    (D) 不設，讓它自動協商

Q6. 這行指令會發生什麼：
    `set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members all`
    為什麼實務上不該這樣寫？

Q7. 簡答：某 Cisco 交換器上每個 VLAN 內部都通，但 VLAN 之間全部不通，
    SVI 都建好了、IP 也對。最可能漏了什麼？

Q8. Switch spoofing 與 Double tagging 兩種 VLAN hopping，
    分別的防護措施是什麼？

Q9. 在 Trunk 的鏡射上跑 `sudo tcpdump -i ens18 -nn -e 'not vlan'`，
    抓到大量使用者的 ARP 與 DHCP 封包。這代表什麼問題？該怎麼修？

Q10. 為什麼「一個 VLAN 對應一個 IP 網段」是硬規則？
     如果一個 VLAN 裡放了兩個網段，會出現什麼症狀？

> [!question]- 測驗答案
> **Q1.** ★★★★★ **4 個位元組**，插在**來源 MAC 之後、類型（EtherType）欄位之前**。
> 其中 **VID 佔 12 個位元**，因此理論範圍 0～4095，
> 扣掉保留的 0 與 4095 後，**可用 VLAN ID 是 1～4094**。
> 這就是「VLAN 最多 4094 個」的來源——是標準的位元數限制，不是廠商限制。
> 見「802.1Q 標籤」。
>
> **Q2.** ★★★★★ **Access 埠送出去的 frame 不帶標籤，Trunk 埠送出去的帶標籤。**
> 其他所有差別（接誰、承載幾個 VLAN、收到標籤怎麼處理）都是從這一句推論出來的。
> 見「Access 埠與 Trunk 埠」。
>
> **Q3.** ★★★★★ **錯**。一般 PC 的網卡**看不懂 802.1Q 標籤**，
> 收到帶標籤的 frame 會直接丟棄，所以症狀是**接上去 link up 但完全不通**——
> 看不到任何 VLAN 的流量，連自己的都收不到。
> （例外：如果在 PC 上手動建立 VLAN 子介面，就能進入對應的 VLAN——
> 這正是 Trunk 埠不能開放給終端的原因。）見「練習 5」。
>
> **Q4.** ★★★★★ Native VLAN 是 **Trunk 埠上唯一不帶標籤傳送的那個 VLAN**；
> 收到無標籤 frame 時也會被歸類成 Native VLAN。
> 兩端不一致時，**A 端 Native VLAN 的流量會跑進 B 端的 Native VLAN**，
> 造成兩個不該互通的 VLAN 被接通（VLAN 洩漏）。
> 難查是因為**每一台設備單獨看設定都完全正常**，
> 只有把兩端擺在一起比對才看得出來。見「Native VLAN 三個坑」。
>
> **Q5.** ★★★★★ **(C)**。Native VLAN 的流量不帶標籤，是 double tagging 攻擊的通道，
> 因此必須是一個**專用、淨空、不配 IP、不接裝置、不建 L3 介面**的 VLAN。
> (A) VLAN 1 是最糟的選擇（管理協定都在裡面）；
> (B) 把使用者放在 Native VLAN 等於直接提供攻擊前提；
> (D) Juniper 沒有自動協商，Cisco 的自動協商（DTP）本身就是漏洞。
> 見「安全性注意事項」。
>
> **Q6.** ★★★★★ 它把這條 Trunk 設成**放行所有 VLAN**。
> 三個理由不該這樣寫：
> 1. **資安**——1F 接入交換器不需要伺服器 VLAN，放行了就是多一條攻擊路徑；
> 2. **頻寬**——每個放行的 VLAN 其廣播都佔用這條上行；
> 3. **不可預期**——未來新增 VLAN 時會自動被放行，沒有人會注意到。
> 正確做法是明列 `vlan members [ VL11 VL51 VL999-NATIVE ]`。
> 見「Trunk 允許清單」。
>
> **Q7.** ★★★★★ 最可能漏了 **`ip routing`**。
> Cisco 交換器的路由功能**預設是關閉的**，
> 只建 SVI（`interface Vlan11`）而沒開 `ip routing`，
> 每個 VLAN 內部正常但跨 VLAN 完全不通，而設定檔看起來一切正常。
> 驗證：`show ip route` 若沒有 connected 路由就是這個問題。
> 見「步驟 5」的 Cisco 對照。
>
> **Q8.** ★★★★★
> - **Switch spoofing**（假裝成交換器協商出 Trunk）：
>   **所有終端埠強制 `switchport mode access` 並加 `switchport nonegotiate` 關閉 DTP**。
>   Juniper 沒有 DTP，天生免疫。
> - **Double tagging**（雙層標籤鑽 Native VLAN）：
>   **Native VLAN 改成專用的空 VLAN**（如 999）、Trunk 允許清單排除 VLAN 1、
>   終端埠不要放在 Native VLAN 裡。
>
> 見「VLAN 洩漏」。
>
> **Q9.** ★★★★★ 代表**有終端落在 Native VLAN 裡**——
> 它們的流量在 Trunk 上是不帶標籤傳輸的。
> 這是 double tagging 攻擊的前提條件，也可能表示兩端 Native VLAN 不一致。
> 修法：(1) 把那些終端埠改到正確的業務 VLAN；
> (2) 確認 Trunk 兩端 `native-vlan-id` 一致且指向淨空的 VLAN 999；
> (3) 重測直到 `'not vlan'` 抓不到使用者流量（只剩偶爾的 STP BPDU）。
> 見「步驟 6」與實戰 8-4。
>
> **Q10.** ★★★★★ 因為 VLAN 是**廣播域**、網段是**三層的可達範圍**，
> 兩者必須對齊才能讓「同網段 = 同廣播域 = ARP 找得到彼此」成立。
> 一個 VLAN 放兩個網段時：兩個網段的主機**在同一個廣播域但互相 ping 不到**
> （因為跨網段需要路由，而它們之間沒有路由器），
> DHCP 也會亂派（同一個廣播域上有兩組 DHCP 範圍），
> 且排錯時完全無法用 IP 推斷位置。
> 唯一合理的例外是**網段搬遷期間的暫時並存**，遷移完成必須移除舊網段。
> 見「VLAN 與子網一對一」。

## 延伸閱讀

- [[010-02-16-guide-網概-VLAN與網路分段]] —— VLAN 的概論與分段的資安意義
- [[040-01-01-guide-網路設備-網路架構基礎]] —— 廣播域、L3 邊界與東西向流量
- [[040-01-02-guide-網路設備-IP位址規劃與子網切分]] —— 每個 VLAN 配哪個網段
- [[040-01-06-guide-Juniper-VLAN與Trunk設定]] —— JunOS 的完整設定細節
- [[040-01-11-guide-Cisco-VLAN與Trunk設定]] —— Cisco IOS 的完整設定細節
- [[040-01-08-guide-Juniper-埠設定與安全]] —— BPDU guard、MAC limit、DHCP snooping、802.1X
- [[040-01-16-guide-網路設備-鏈路聚合與STP]] —— Trunk 上的 STP 與鏈路聚合
- [[040-01-17-guide-網路設備-交換器故障排除]] —— VLAN 相關故障的完整排查
- [[040-01-04-guide-網路設備-交換器初次設定與連線方式]] —— 帶外管理路徑的重要性
