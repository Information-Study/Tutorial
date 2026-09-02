---
title: "鏈路聚合與 STP"
desc: "LACP/ae 聚合、RSTP 根橋規劃、root/BPDU/loop guard 與廣播風暴的現場急救"
aliases: [LACP, LAG, ae0, EtherChannel, Port-channel, STP, RSTP, MSTP, BPDU guard, 廣播風暴]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-06-guide-Juniper-VLAN與Trunk設定]]", "[[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]]"]
updated: 2026-09-02
---

# 鏈路聚合與 STP

> [!abstract] 這篇你會學到
> - ★★★★★ **廣播風暴的現場症狀與三分鐘急救 SOP** —— 全機房燈同步狂閃、
>   SSH 連不上交換器、整層樓斷網。這是網管生涯最恐怖的一天，先學會怎麼救
> - ★★★★★ 為什麼「兩台交換器接兩條線」不是備援而是**災難**，以及 STP 憑什麼救你
> - ★★★★ LACP 聚合（JunOS `ae0`／IOS `Port-channel1`）從零到通，
>   以及 **active／passive／on 三種模式配錯會發生什麼**
> - ★★★★ 聚合的頻寬真相：4 條 1G 綁一起，**單一檔案傳輸還是只有 1G**
> - ★★★★★ 根橋不是「選出來的最好那台」，是「**最爛的那台也可能當選**」——
>   為什麼一定要手動指定 bridge priority
> - ★★★★★ 三道護欄：**root guard／BPDU guard／loop guard** 各擋什麼、
>   為什麼三個都要開、開錯位置會擋掉自己的上行
> - ★★★ 埠角色（Root／Designated／Alternate／Backup）與埠狀態
>   （Discarding／Learning／Forwarding）怎麼讀

> [!warning] 未實機驗證
> 本篇的 JunOS（EX 系列、ELS 軟體）與 Cisco IOS 指令依 Juniper 與 Cisco 官方文件整理，
> 撰稿環境**沒有實體交換器可逐條驗證**，輸出範例為依文件格式撰寫的示意。
> 不同機型與軟體版本在 storm-control、loop protection、MSTP 的語法上差異不小。
> **導入前務必在實驗環境或維護窗口內先跑過一次**，並以你手上設備的官方文件為準。

## 前置知識

- [[040-01-06-guide-Juniper-VLAN與Trunk設定]] —— trunk 是聚合與 STP 的基礎
- [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]] —— candidate／commit confirmed 的保險機制
- [[010-02-05-guide-網概-MAC位址與交換器]] —— MAC 學習、氾流（flooding）、為什麼會形成環路
- [[040-01-03-guide-網路設備-VLAN概念與規劃]] —— VLAN 與 STP instance 的關係
- [[040-01-01-guide-網路設備-網路架構基礎]] —— 接取層／匯聚層／核心層的三層架構

## 觀念說明

### 一、二層網路為什麼會被自己害死 ★★★★★

三層 IP 封包有 **TTL** 欄位，每經過一個路由器減一，減到 0 就丟棄 —— 
所以 IP 封包永遠不會無限繞。

**二層 Ethernet frame 沒有 TTL。** 這一句話就是本篇存在的理由。

```text
                 ┌──────────┐
                 │  sw-core │
                 └─┬──────┬─┘
                   │      │        ← 兩台交換器之間接了「兩條」線
                 ┌─┴──────┴─┐
                 │  sw-a1f  │
                 └──────────┘

有人送出一個廣播（例如 ARP request）：

  sw-a1f 從 A 線送出去 ─▶ sw-core 收到 ─▶ 從 B 線氾流回來
  sw-a1f 從 B 線收到  ─▶ 這是廣播，再從 A 線氾流出去
  sw-core 從 A 線收到  ─▶ 再從 B 線氾流回來
  ...

每繞一圈，交換器就再複製一份。因為沒有 TTL，這個過程 **永遠不會停**。
毫秒等級之內，這一個 frame 會變成每秒數百萬個 frame。  ★★★★★
```

後果是三重的，而且互相加乘：

| 後果 | 現象 | 星級 |
| --- | --- | --- |
| **頻寬被佔滿** | 所有埠的流量瞬間跑到線速，正常封包完全擠不進去 | ★★★★★ |
| **交換器 CPU 燒滿** | 廣播要送 CPU 處理，CPU 100% → **SSH／Console 都變得極慢或無回應** | ★★★★★ |
| **MAC 表崩壞** | 同一個 MAC 一下從 A 埠學到、一下從 B 埠學到，不停覆寫，單播也開始亂送 | ★★★★★ |

★★★★★ 最惡毒的地方在於：**交換器 CPU 被打滿之後，你連進去改設定的能力也一起沒了。**
這就是為什麼廣播風暴幾乎一定要靠「跑去機房拔線」解決。

### 二、STP 的核心想法：主動把多餘的路關掉 ★★★★★

Spanning Tree Protocol 的邏輯非常單純：

> 讓交換器們互相通報，算出一棵**沒有環路的樹**，
> 樹以外的多餘鏈路**主動阻斷（blocking）**，只在主路徑掛掉時才放行。

```text
             ┌──────────┐  ← 根橋（Root Bridge），樹根
             │  sw-core │     所有埠都是 Designated，全部 Forwarding
             └─┬──────┬─┘
       A 線    │      │   B 線
               │      │
             ┌─┴──────┴─┐
             │  sw-a1f  │
             └──────────┘
              Root Port  Alternate Port
              （通）      （阻斷，BLK）★★★★★

A 線斷掉 ─▶ B 線的 Alternate Port 轉成 Root Port ─▶ 開始轉送
（RSTP 通常 1～2 秒內完成，傳統 STP 要 30～50 秒）
```

**重點觀念**：STP 阻斷的埠**實體上是通的、燈是亮的**，只是不轉送資料 frame（BPDU 仍會收）。
所以「線都插好了、燈也亮了、就是不通」很可能是 STP 正在阻斷 —— 這在
[[040-01-17-guide-網路設備-交換器故障排除]] 是排查清單上的固定一項。

### 三、STP 的三個世代 ★★★★

| 版本 | 標準 | 收斂時間 | 每個 VLAN 一棵樹？ | 現在還該用嗎 |
| --- | --- | --- | --- | --- |
| **STP** | 802.1D | 30～50 秒 ★★★★★ | 否（整台一棵） | ★ 不該，太慢 |
| **RSTP** | 802.1w | 1～2 秒 | 否（整台一棵） | ★★★★★ **中小型網路的預設答案** |
| **MSTP** | 802.1s | 1～2 秒 | 是（VLAN 分組，每組一棵） | ★★★ 大型／需要負載分擔時 |
| PVST+／Rapid PVST+ | Cisco 私有 | 30 秒／1～2 秒 | 是（每個 VLAN 一棵） | ★★★ 純 Cisco 環境 |

★★★★★ **JunOS 的 EX 交換器預設就跑 RSTP**（`protocols rstp`），這是好事。
Cisco 的預設是 **PVST+**（舊）或 **Rapid PVST+**（新機型），是 Cisco 私有協定。

> [!warning] ★★★★ 混廠環境的相容性
> Cisco 的 Rapid PVST+ 與標準 RSTP **可以互通**，但互通時 Cisco 那邊會把
> 標準 RSTP 網域整個視為一個「VLAN 1 的樹」來處理，行為會比純 Cisco 環境難預測。
> **Juniper 與 Cisco 混用時，建議兩邊都統一跑 MSTP**（兩家都支援 802.1s 標準），
> 或至少確認拓樸夠簡單、根橋位置明確。這一段請務必在實驗環境驗證再上線。

### 四、根橋是怎麼「選」出來的 ★★★★★

STP 用 **Bridge ID** 比大小，**數字最小的當根橋**。Bridge ID 由兩段組成：

```text
Bridge ID  =  Bridge Priority (16 bits)  +  Bridge MAC Address (48 bits)
              ─────────────────────────      ──────────────────────────
              可設定，預設 32768             出廠燒死，改不了
              必須是 4096 的倍數 ★★★★
              （0, 4096, 8192, ..., 61440）

比較規則：
  1. 先比 Priority，小的贏
  2. Priority 一樣 → 比 MAC，小的贏  ★★★★★
```

> [!danger] ★★★★★ 不指定 priority 的下場：最老的那台當根橋
> 所有交換器出廠 priority 都是 32768，所以比的是 **MAC 位址**。
> MAC 位址小 ≈ 出廠早 ≈ **機房裡最老、效能最差、可能明年就要汰換的那一台**。
>
> 於是你的網路核心變成一台十年前的接取層小交換器：
> - 所有跨 VLAN 流量繞經它 → 效能瓶頸
> - 它一重開，**全網路 STP 重新收斂**，整棟樓閃斷
> - 有人把它拔掉汰換 → 沒人知道那是根橋 → 全網重新收斂
>
> **每一個 STP 網域都必須手動指定根橋與備援根橋。這不是最佳實務，這是基本要求。**

**標準做法**：

| 角色 | 設備 | Priority | 星級 |
| --- | --- | --- | --- |
| 主根橋 | 核心交換器 A（或匯聚層主機） | **4096** | ★★★★★ |
| 備援根橋 | 核心交換器 B | **8192** | ★★★★★ |
| 其他所有交換器 | 接取層 | 保持 32768，或明確設 **61440** | ★★★ |

★★★★ 把接取層全部設成 61440（最大值）是很值得的一道保險：
就算有人插了一台不明來源的交換器進來，它的預設 32768 也贏不過…… 
等等，32768 < 61440，所以它**會贏**。
這正是為什麼**光靠 priority 不夠，還必須開 root guard**（見下一節）。

### 五、埠角色與埠狀態，兩件不同的事 ★★★★

初學者最常混淆的地方。**角色（Role）是「這個埠在樹裡的定位」，
狀態（State）是「這個埠現在轉不轉送資料」。**

**RSTP 的四種埠角色**：

| 角色 | 意義 | 轉送嗎 | 星級 |
| --- | --- | --- | --- |
| **Root Port（RP）** | 這台交換器**通往根橋的最佳路徑**，每台非根橋**有且只有一個** | 是 | ★★★★★ |
| **Designated Port（DP）** | 這條網段上**負責往下轉送**的埠；根橋的所有埠都是 DP | 是 | ★★★★ |
| **Alternate Port（AP）** | 通往根橋的**備援路徑**，被阻斷 | 否 ★★★★★ | ★★★★★ |
| **Backup Port（BP）** | 同一網段上的備援（少見，通常是接到 hub 才出現） | 否 | ★★ |

**RSTP 的三種埠狀態**（比傳統 STP 的五種簡化了）：

| 狀態 | 學 MAC？ | 轉送資料？ | 收送 BPDU？ |
| --- | --- | --- | --- |
| **Discarding** | 否 | 否 | 收 | 
| **Learning** | 是 | 否 | 收送 |
| **Forwarding** | 是 | 是 | 收送 |

> [!note] ★★★ 傳統 STP 的五種狀態對照
> 802.1D 有 Disabled／Blocking／Listening／Learning／Forwarding 五種，
> 而且 Blocking → Listening（15 秒）→ Learning（15 秒）→ Forwarding，
> **最少要等 30 秒**，加上 max-age 20 秒最多到 50 秒。
> RSTP 把 Disabled／Blocking／Listening 合併成 **Discarding**，
> 並用 proposal／agreement 握手取代計時器，收斂降到 1～2 秒。
> 這就是「別再用 802.1D」的理由。

### 六、鏈路聚合：把多條線變成一條 ★★★★

STP 的代價是**備援鏈路完全閒置**。四條 1G 上行，STP 只讓一條通，
其餘三條純粹當備胎 —— 這在頻寬吃緊的機房是無法接受的。

**鏈路聚合（Link Aggregation）**把多條實體鏈路綁成一個邏輯介面：

```text
   sw-a1f                                sw-core
  ┌───────┐   ge-0/0/49 ══════════════  ┌───────┐
  │       │   ge-0/0/50 ══════════════  │       │
  │  ae0  │   ge-0/0/51 ══════════════  │  ae0  │
  │       │   ge-0/0/52 ══════════════  │       │
  └───────┘                             └───────┘
      ▲                                     ▲
   STP 只看到「一個 ae0 介面」，不會判定為環路  ★★★★★
   四條線全部同時轉送，總頻寬 4G
   斷一條 → ae0 還在，STP 完全不重新收斂（子秒級）★★★★★
```

★★★★★ **這是聚合相對於 STP 備援的最大價值**：
斷一條線時**沒有 STP 收斂事件**，上層應用連察覺都不會察覺。

### 七、聚合的頻寬真相：4×1G ≠ 4G ★★★★

這是最容易讓人失望的一點，也是必須先跟主管講清楚的一點。

> [!warning] ★★★★ 聚合是「**多條流各走各的**」，不是「一條流變寬」
> 交換器對每個 frame 算一個 hash（依來源／目的 MAC、IP、埠號），
> 用 hash 結果決定「這個封包走哪一條實體線」。**同一條 TCP 連線的封包 hash 一定相同**，
> 所以永遠走同一條線。
>
> 結果：
> - 一台伺服器對一台伺服器傳一個大檔 → **只會用到 1G**，不管你綁幾條 ★★★★
> - 100 個使用者各自連不同伺服器 → 可以填滿 4G ★★★
> - 兩台伺服器之間 NFS 備份 → **只有 1G**，聚合完全幫不上忙 ★★★★

| 需求 | 聚合幫得上忙嗎 | 該怎麼做 |
| --- | --- | --- |
| 上行總頻寬不夠（很多使用者） | ★★★★★ 幫得上 | 聚合 |
| 單一伺服器備份太慢 | ★ 幫不上 | 換 10G 單埠 |
| 上行斷線就全樓斷網 | ★★★★★ 幫得上 | 聚合（或雙上行 + STP） |
| 跨 VLAN 路由效能不足 | ★ 幫不上 | 換三層交換器／核心升級 |

★★★ **hash 演算法可以調整**，但只能改變「分佈得均不均勻」，改不了「單流不會分割」。

| 平台 | 調整 hash 的方式 |
| --- | --- |
| JunOS | `set forwarding-options enhanced-hash-key ...`（機型差異大，查該機型文件）★★ |
| IOS | `port-channel load-balance src-dst-ip` ★★★ |

★★★★ 實務建議：**預設用 `src-dst-ip`**（或 `src-dst-mixed-ip-port`）。
只用 `src-mac`／`dst-mac` 在「一台伺服器對很多客戶端」的場景會嚴重不平均。

### 八、LACP vs 靜態聚合 ★★★★★

| 模式 | JunOS | IOS | 會不會協商 | 星級 |
| --- | --- | --- | --- | --- |
| **LACP active**（主動發起） | `lacp active` | `channel-group 1 mode active` | 會，主動送 LACP PDU | ★★★★★ |
| **LACP passive**（被動回應） | `lacp passive` | `channel-group 1 mode passive` | 會，但只回應不主動 | ★★★ |
| **靜態／強制**（不協商） | 不設 `lacp` 語句 | `channel-group 1 mode on` | **不會** ★★★★★ | ★ 不建議 |
| PAgP（Cisco 私有） | 不支援 | `mode desirable`／`mode auto` | 會（Cisco 之間） | ★ 混廠不可用 |

**組合結果表**（★★★★★ 這張表要背）：

| 一端 | 另一端 | 結果 |
| --- | --- | --- |
| active | active | ✅ 成功（**建議做法**） |
| active | passive | ✅ 成功 |
| passive | passive | ❌ **不會成立**，雙方都在等對方開口 ★★★★ |
| on | on | ✅ 成立，但**沒有任何檢查機制** |
| **on** | **active** | ❌ **最危險的組合** ★★★★★ |
| active | 沒設聚合 | ❌ 但通常會被 LACP 擋住，安全 |
| **on** | **沒設聚合** | ❌ **會造成環路！** ★★★★★ |

> [!danger] ★★★★★ 為什麼 `mode on` 是災難的溫床
> `mode on` 是「我不管對面怎麼想，這幾條線就是一組」。
> 如果對面**還沒設好聚合**（或設錯了、或某條線接錯埠），
> 對面會把這幾條線當成**幾條獨立的線**，而 STP 又因為這一端顯示是一個邏輯埠而不阻斷 —— 
> **恭喜，你得到一個 STP 看不見的環路**，接著就是廣播風暴。
>
> **一律使用 LACP（兩端都 active）。** LACP 會在協商成功前保持鏈路不轉送，
> 這是它相對於靜態聚合最重要的安全價值。

★★★ **LACP 心跳間隔**：`fast`（每 1 秒）vs `slow`（每 30 秒）。
`fast` 偵測對端失效約 3 秒，`slow` 要 90 秒。
**兩端要設成一樣**，否則會不穩。上行鏈路建議 `fast`。

## 安裝或基礎操作

### 環境假設

```text
                  ┌───────────────────┐
                  │   sw-core-01      │  Priority 4096（主根橋）
                  │   (EX4300)        │
                  └───┬───────────┬───┘
              ae0 ×2  │           │  ae1 ×2
                      │           │
        ┌─────────────┴──┐   ┌────┴───────────┐
        │  sw-a1f-01     │   │  sw-a2f-01     │  Priority 61440
        │  (EX2300)      │   │  (EX2300)      │
        └────────────────┘   └────────────────┘
             接取埠 ge-0/0/0 ~ ge-0/0/23（VLAN 10 / 20）
             上行埠 ge-0/0/24, ge-0/0/25 → ae0

VLAN：V10-OFFICE(10)、V20-VOICE(20)、V999-NATIVE(999，無主機)
```

> [!warning] ★★★★★ 施工順序決定你會不會造成風暴
> **一定要先在兩端都把聚合設定完成、確認 LACP 起來之後，才接上第二條線。**
> 正確順序：
> 1. 先只接**一條**線，確認基本連通
> 2. 兩端都設好 `ae0` 與 LACP，`commit`
> 3. 確認第一條線已經成為 ae0 的成員（`show lacp interfaces ae0`）
> 4. **這時才接第二條線**
> 5. 確認第二條也 bundled
>
> 反過來（先接兩條線再慢慢設定）＝ 在設定完成前你有一個裸露的環路。
> 若對端已設好 STP 通常擋得住，但**不要把安全寄託在「通常」上**。

### JunOS：建立 ae0 聚合 ★★★★

**步驟 1：宣告要用幾個 ae 介面**

★★★★★ 這一步是 JunOS 專有、也最常被漏掉的一步。
不宣告 `device-count`，`ae0` 這個介面根本不存在，後面所有設定都會 commit 失敗。

```text
[edit]
admin@sw-a1f-01# set chassis aggregated-devices ethernet device-count 4
```

**步驟 2：把實體埠掛到 ae0**

★★★★ 注意：成員埠上**不能有任何 family 設定**（`family ethernet-switching`、
`family inet` 都不行），只能有 `ether-options 802.3ad`。有殘留設定會 commit 失敗。

```text
[edit]
admin@sw-a1f-01# delete interfaces ge-0/0/24 unit 0          ← 先清掉舊的二層設定
admin@sw-a1f-01# delete interfaces ge-0/0/25 unit 0
admin@sw-a1f-01# set interfaces ge-0/0/24 description "UPLINK-CORE01-ae0-member"
admin@sw-a1f-01# set interfaces ge-0/0/24 ether-options 802.3ad ae0
admin@sw-a1f-01# set interfaces ge-0/0/25 description "UPLINK-CORE01-ae0-member"
admin@sw-a1f-01# set interfaces ge-0/0/25 ether-options 802.3ad ae0
```

**步驟 3：設定 ae0 本身**

```text
[edit]
admin@sw-a1f-01# set interfaces ae0 description "UPLINK to sw-core-01"
admin@sw-a1f-01# set interfaces ae0 aggregated-ether-options lacp active
admin@sw-a1f-01# set interfaces ae0 aggregated-ether-options lacp periodic fast
admin@sw-a1f-01# set interfaces ae0 aggregated-ether-options minimum-links 1
admin@sw-a1f-01# set interfaces ae0 unit 0 family ethernet-switching interface-mode trunk
admin@sw-a1f-01# set interfaces ae0 unit 0 family ethernet-switching vlan members [ V10-OFFICE V20-VOICE ]
admin@sw-a1f-01# set interfaces ae0 native-vlan-id 999
```

**步驟 4：檢查再上線**

```text
[edit]
admin@sw-a1f-01# show | compare
admin@sw-a1f-01# commit confirmed 5 comment "CHG-2026-0921 建立 ae0"
commit confirmed will be automatically rolled back in 5 minutes unless confirmed
commit complete
```

**步驟 5：驗證**

```text
admin@sw-a1f-01> show interfaces ae0 terse
Interface               Admin Link Proto    Local                 Remote
ae0                     up    up
ae0.0                   up    up   eth-switch

admin@sw-a1f-01> show lacp interfaces ae0
Aggregated interface: ae0
    LACP state:       Role   Exp   Def  Dist  Col  Syn  Aggr  Timeout  Activity
      ge-0/0/24       Actor    No    No   Yes  Yes  Yes   Yes     Fast    Active
      ge-0/0/24     Partner    No    No   Yes  Yes  Yes   Yes     Fast    Active
      ge-0/0/25       Actor    No    No   Yes  Yes  Yes   Yes     Fast    Active
      ge-0/0/25     Partner    No    No   Yes  Yes  Yes   Yes     Fast    Active
    LACP protocol:        Receive State  Transmit State          Mux State
      ge-0/0/24                 Current   Fast periodic Collecting distributing
      ge-0/0/25                 Current   Fast periodic Collecting distributing
```

★★★★★ **判讀重點**：

| 欄位 | 正常值 | 不正常代表什麼 |
| --- | --- | --- |
| `Dist` / `Col` / `Syn` | 全 `Yes` | 有 `No` = 尚未完成協商 ★★★★ |
| `Def`（Defaulted） | `No` | `Yes` = **沒收到對端 LACP PDU**，對面沒設或設成 passive/on ★★★★★ |
| `Exp`（Expired） | `No` | `Yes` = 曾收到但現在逾時，線路或對端有問題 ★★★★ |
| `Timeout` | 兩端一致 | 不一致會不穩 ★★★ |
| `Mux State` | `Collecting distributing` | 其他值 = 沒有在轉送 ★★★★★ |

```text
admin@sw-a1f-01> show interfaces ae0 extensive | match "Speed|Link|LACP"
  Link-level type: Ethernet, MTU: 1514, Speed: 2Gbps, ...
                                              ^^^^^^  ← 兩條 1G 綁起來  ★★★★
```

> [!info]- Cisco IOS 對照：建立 Port-channel1
> ```cisco
> ! 步驟 1：先建邏輯介面（IOS 也可以在 channel-group 時自動建立）
> sw-a1f-01(config)# interface Port-channel1
> sw-a1f-01(config-if)# description UPLINK to sw-core-01
> sw-a1f-01(config-if)# switchport mode trunk
> sw-a1f-01(config-if)# switchport trunk allowed vlan 10,20
> sw-a1f-01(config-if)# switchport trunk native vlan 999
> sw-a1f-01(config-if)# exit
>
> ! 步驟 2：把成員埠加進去
> sw-a1f-01(config)# interface range GigabitEthernet1/0/24 - 25
> sw-a1f-01(config-if-range)# description UPLINK-CORE01-Po1-member
> sw-a1f-01(config-if-range)# switchport mode trunk
> sw-a1f-01(config-if-range)# switchport trunk allowed vlan 10,20
> sw-a1f-01(config-if-range)# switchport trunk native vlan 999
> sw-a1f-01(config-if-range)# channel-protocol lacp
> sw-a1f-01(config-if-range)# channel-group 1 mode active
> sw-a1f-01(config-if-range)# end
>
> ! 步驟 3：驗證
> sw-a1f-01# show etherchannel summary
> Flags:  D - down        P - bundled in port-channel
>         I - stand-alone s - suspended
>         H - Hot-standby (LACP only)
>         R - Layer3      S - Layer2
>         U - in use      f - failed to allocate aggregator
>
> Number of channel-groups in use: 1
> Number of aggregators:           1
>
> Group  Port-channel  Protocol    Ports
> ------+-------------+-----------+-----------------------------------------
> 1      Po1(SU)         LACP      Gi1/0/24(P)  Gi1/0/25(P)
>
> sw-a1f-01# show lacp neighbor
> Flags:  S - Device is requesting Slow LACPDUs
>         F - Device is requesting Fast LACPDUs
>         A - Device is in Active mode       P - Device is in Passive mode
>
> Channel group 1 neighbors
> Partner's information:
>           LACP port                        Admin  Oper   Port    Port
> Port      Flags   Priority  Dev ID          Age   key    Key    Number  State
> Gi1/0/24  FA      32768     0011.2233.4455  12s   0x0    0x1    0x19    0x3D
> Gi1/0/25  FA      32768     0011.2233.4455  10s   0x0    0x1    0x1A    0x3D
> ```
>
> ★★★★★ **`show etherchannel summary` 的旗標判讀**：
>
> | 旗標 | 意義 | 該做什麼 |
> | --- | --- | --- |
> | `Po1(SU)` | Layer2 + in use = 正常 | 無 |
> | `Gi1/0/24(P)` | bundled = 正常成員 | 無 |
> | `Gi1/0/24(I)` | **stand-alone** = 沒能加入，單獨在跑 ★★★★★ | 檢查對端設定，這是**潛在環路** |
> | `Gi1/0/24(s)` | **suspended** = 被暫停 | 通常是兩端參數不一致 ★★★★ |
> | `Gi1/0/24(D)` | down | 線沒接或對端關了 |
> | `Po1(SD)` | 整個 channel down | 沒有任何成員 bundled |
>
> ★★★★★ 看到 `(I)` **必須立刻處理**。它表示這條線沒有被納入 Port-channel，
> 但**實體上還在轉送**，等於一條 STP 不見得看得到的旁路。

### JunOS：RSTP 基本設定 ★★★★★

EX 交換器預設就跑 RSTP，但**預設不會幫你指定根橋，也不會幫你開任何護欄**。

**核心交換器（主根橋）**：

```text
[edit]
admin@sw-core-01# set protocols rstp bridge-priority 4096
admin@sw-core-01# set protocols rstp interface all
```

**接取層交換器**：

```text
[edit]
admin@sw-a1f-01# set protocols rstp bridge-priority 61440
admin@sw-a1f-01# set protocols rstp interface all
```

**驗證**：

```text
admin@sw-a1f-01> show spanning-tree bridge
STP bridge parameters
Context ID                          : 0
Enabled protocol                    : RSTP
  Root ID                           : 4096.00:11:22:33:44:55     ← 根橋是 core-01 ★★★★★
  Root cost                         : 20000
  Root port                         : ae0
  Hello time                        : 2 seconds
  Maximum age                       : 20 seconds
  Forward delay                     : 15 seconds
  Message age                       : 1
  Number of topology changes        : 3
  Time since last topology change   : 86400 seconds              ← 24 小時沒變動 = 穩定 ★★★★
  Local parameters
    Bridge ID                       : 61440.00:aa:bb:cc:dd:ee
    Extended system ID              : 0
```

★★★★★ **`Number of topology changes` 與 `Time since last topology change` 是最有價值的兩個欄位。**
如果 `Time since last topology change` 一直是個位數秒，代表**拓樸正在震盪**，
那就是你網路不穩的根因。

```text
admin@sw-a1f-01> show spanning-tree interface

Spanning tree interface parameters for instance 0

Interface    Port ID    Designated      Designated         Port    State  Role
                         port ID        bridge ID          Cost
ae0            128:1       128:1  4096.001122334455        20000    FWD    ROOT
ge-0/0/0       128:2       128:2 61440.00aabbccddee       200000    FWD    DESG
ge-0/0/1       128:3       128:3 61440.00aabbccddee       200000    FWD    DESG
ge-0/0/26      128:27      128:5  4096.001122334455        20000    BLK    ALT
```

| Role | State | 意義 |
| --- | --- | --- |
| `ROOT` | `FWD` | 通往根橋的主路徑，正常 ★★★★ |
| `DESG` | `FWD` | 往下游的埠，正常 |
| `ALT` | `BLK` | **備援路徑，被 STP 阻斷** —— 這是 STP 正在工作的證據 ★★★★★ |
| `BKUP` | `BLK` | 同網段備援（少見） |
| 任何 | `DIS` | 埠被關閉或 STP 停用 |

> [!info]- Cisco IOS 對照：Rapid PVST+ 基本設定
> ```cisco
> ! 核心交換器
> sw-core-01(config)# spanning-tree mode rapid-pvst
> sw-core-01(config)# spanning-tree vlan 1-4094 priority 4096
> ! 或用巨集（IOS 會自動算出比目前根橋小的值）
> sw-core-01(config)# spanning-tree vlan 10,20 root primary
>
> ! 備援核心
> sw-core-02(config)# spanning-tree mode rapid-pvst
> sw-core-02(config)# spanning-tree vlan 10,20 root secondary
>
> ! 接取層
> sw-a1f-01(config)# spanning-tree mode rapid-pvst
> sw-a1f-01(config)# spanning-tree vlan 1-4094 priority 61440
> ```
>
> ★★★★ **`root primary` 是巨集不是設定值**：IOS 會去看目前的根橋 priority，
> 設一個比它小的值（通常是 24576 或更低）寫進設定。
> 這表示**它只在你打的當下有效** —— 如果之後有人加入一台 priority 更小的設備，
> 你的「root primary」就失效了。**正式環境建議直接寫死 `priority 4096`。**
>
> ```cisco
> sw-a1f-01# show spanning-tree vlan 10
>
> VLAN0010
>   Spanning tree enabled protocol rstp
>   Root ID    Priority    4106
>              Address     0011.2233.4455
>              Cost        3
>              Port        56 (Port-channel1)
>              Hello Time  2 sec  Max Age 20 sec  Forward Delay 15 sec
>
>   Bridge ID  Priority    61450  (priority 61440 sys-id-ext 10)
>              Address     00aa.bbcc.ddee
>              Hello Time  2 sec  Max Age 20 sec  Forward Delay 15 sec
>              Aging Time  300 sec
>
> Interface           Role Sts Cost      Prio.Nbr Type
> ------------------- ---- --- --------- -------- --------------------------------
> Gi1/0/1             Desg FWD 4         128.1    P2p Edge
> Gi1/0/26            Altn BLK 4         128.26   P2p
> Po1                 Root FWD 3         128.56   P2p
> ```
>
> ★★★ 注意 `Priority 4106 = 4096 + 10`：Cisco 的 PVST+ 把 VLAN ID 加進
> priority 的「extended system ID」欄位，所以你看到的數字會比你設的大一點點。
> 這是正常的，不是設錯。

## 進階應用

### 一、三道護欄：root guard／BPDU guard／loop guard ★★★★★

光把 RSTP 打開只是「有 STP」，不代表「安全」。
真正決定你會不會出事的是這三道護欄。

| 護欄 | 擋什麼 | 該裝在哪 | 觸發後 | 星級 |
| --- | --- | --- | --- | --- |
| **BPDU guard** | 使用者埠**收到任何 BPDU** | 所有**邊緣／使用者埠** | 埠被關掉 | ★★★★★ |
| **Root guard** | 對端宣稱自己是更好的根橋 | **朝下游**的埠（接取層方向） | 該埠進入 root-inconsistent（阻斷） | ★★★★★ |
| **Loop guard** | 原本收得到 BPDU 的埠**突然收不到了** | **Root Port 與 Alternate Port**（上行方向） | 該埠進入 loop-inconsistent（阻斷） | ★★★★ |

```text
             ┌──────────────┐
             │  sw-core-01  │  根橋
             └──┬────────┬──┘
                │        │
   loop guard ──┤        ├── loop guard      ← 裝在上行（Root/Alternate）★★★★
                │        │
             ┌──┴────────┴──┐
             │  sw-a1f-01   │
             └──┬───┬───┬───┘
   root guard ──┘   │   └── root guard        ← 裝在下行 ★★★★★
                    │
              BPDU guard                       ← 裝在使用者埠 ★★★★★
                    │
                 [ 使用者 PC ]
```

#### BPDU guard：擋「使用者偷接交換器」★★★★★

**這是機關網路最常發生的事故來源。** 有人覺得埠不夠，
自己從家裡帶一台幾百塊的小交換器（或無線 AP 開了橋接模式）接上牆上的網路孔，
然後**另一條線也插進同一台**——瞬間環路。

BPDU guard 的邏輯：**使用者埠不應該收到 BPDU，收到就代表有人接了交換器。**

**JunOS**：

```text
[edit]
admin@sw-a1f-01# set protocols rstp interface ge-0/0/0 edge
admin@sw-a1f-01# set protocols rstp interface ge-0/0/1 edge
admin@sw-a1f-01# set protocols rstp bpdu-block-on-edge
admin@sw-a1f-01# set protocols layer2-control bpdu-block disable-timeout 300
```

★★★★★ 三行的意義：
1. `edge` = 宣告這是邊緣埠（等同 Cisco 的 PortFast，接上就直接 Forwarding，不等 STP）
2. `bpdu-block-on-edge` = **所有 edge 埠一旦收到 BPDU 就阻斷**
3. `disable-timeout 300` = 阻斷 300 秒後自動嘗試恢復（不設的話要人工介入）★★★★

**驗證**：

```text
admin@sw-a1f-01> show spanning-tree interface ge-0/0/5

Spanning tree interface parameters for instance 0

Interface    Port ID    Designated      Designated         Port    State  Role
                         port ID        bridge ID          Cost
ge-0/0/5       128:6       128:6 61440.00aabbccddee       200000    BLK    DIS
```

```text
admin@sw-a1f-01> show log messages | match ge-0/0/5 | last 5
Sep  2 14:32:11 sw-a1f-01 l2cpd[1523]: BPDU_BLOCK: ge-0/0/5 is blocked due to BPDU received
```

> [!info]- Cisco IOS 對照：PortFast + BPDU guard
> ```cisco
> ! 建議做法：全域預設，避免漏掉某個埠
> sw-a1f-01(config)# spanning-tree portfast edge default
> sw-a1f-01(config)# spanning-tree portfast bpduguard default
>
> ! 上行埠必須明確排除（否則會被當成邊緣埠）★★★★★
> sw-a1f-01(config)# interface Port-channel1
> sw-a1f-01(config-if)# spanning-tree portfast disable
> sw-a1f-01(config-if)# exit
>
> ! 自動恢復
> sw-a1f-01(config)# errdisable recovery cause bpduguard
> sw-a1f-01(config)# errdisable recovery interval 300
> ```
>
> 觸發時的日誌與狀態：
>
> ```cisco
> %SPANTREE-2-BLOCK_BPDUGUARD: Received BPDU on port GigabitEthernet1/0/5 with BPDU Guard enabled. Disabling port.
> %PM-4-ERR_DISABLE: bpduguard error detected on Gi1/0/5, putting Gi1/0/5 in err-disable state
>
> sw-a1f-01# show interfaces status err-disabled
> Port      Name               Status       Reason               Err-disabled Vlans
> Gi1/0/5   PC-A1F-005         err-disabled bpduguard
> ```
>
> ★★★★★ 手動恢復（排除原因之後）：
> ```cisco
> sw-a1f-01(config)# interface Gi1/0/5
> sw-a1f-01(config-if)# shutdown
> sw-a1f-01(config-if)# no shutdown
> ```

> [!danger] ★★★★★ 千萬不要把 BPDU guard 開在上行埠
> 上行埠**本來就會收到 BPDU**（那是正常的 STP 運作）。
> 一旦你在上行埠開了 BPDU guard，**上行會在幾秒內被自己關掉，整台交換器下線**。
> 這是「開護欄反而造成事故」最常見的一種。
>
> JunOS 的 `bpdu-block-on-edge` 因為只作用在標了 `edge` 的埠，相對安全 —— 
> 但前提是**你沒有誤把上行埠標成 `edge`**。
> Cisco 的 `spanning-tree portfast bpduguard default` 也是只作用在 PortFast 埠，
> 所以**上行埠必須明確 `spanning-tree portfast disable`**。

#### Root guard：擋「不該當根橋的設備當了根橋」★★★★★

情境：某部門自己買了一台交換器，出廠 priority 32768，
比你接取層設的 61440 **小**，於是它變成整棟樓的根橋。
所有流量開始繞經那台放在茶水間櫃子裡的無風扇交換器。

Root guard 的邏輯：**這個埠的方向不應該出現「比目前根橋更好」的 BPDU。
出現了就把這個埠阻斷。**

**JunOS**：

```text
[edit]
admin@sw-a1f-01# set protocols rstp interface ge-0/0/0 no-root-port
admin@sw-a1f-01# set protocols rstp interface ge-0/0/1 no-root-port
```

★★★ JunOS 把 root guard 叫做 **`no-root-port`**：字面意思是
「這個埠永遠不准變成 Root Port」，正好就是 root guard 的效果。

**驗證**：

```text
admin@sw-a1f-01> show spanning-tree interface ge-0/0/8

Interface    Port ID    Designated      Designated         Port    State  Role
                         port ID        bridge ID          Cost
ge-0/0/8       128:9       128:9 61440.00aabbccddee       200000    BLK    DIS

admin@sw-a1f-01> show log messages | match root
Sep  2 15:10:44 sw-a1f-01 l2cpd[1523]: ROOT_PROTECT: ge-0/0/8 received superior BPDU, blocking
```

> [!info]- Cisco IOS 對照：Root guard
> ```cisco
> sw-a1f-01(config)# interface range Gi1/0/1 - 23
> sw-a1f-01(config-if-range)# spanning-tree guard root
> ```
>
> 觸發時：
>
> ```cisco
> %SPANTREE-2-ROOTGUARD_BLOCK: Root guard blocking port GigabitEthernet1/0/8 on VLAN0010.
>
> sw-a1f-01# show spanning-tree inconsistentports
>
> Name                 Interface              Inconsistency
> -------------------- ---------------------- ------------------
> VLAN0010             GigabitEthernet1/0/8   Root Inconsistent
>
> Number of inconsistent ports (segments) in the system : 1
> ```
>
> ★★★★★ **`show spanning-tree inconsistentports` 是 IOS 排查護欄的第一條指令。**
> 使用者說「插了線但不通」，這一條會直接告訴你是不是被 guard 擋掉的。
>
> ★★★★ Root guard **會自動恢復**：對端不再送 superior BPDU 之後（例如那台違規交換器被拔掉），
> 埠會自己回到正常。不需要 `shutdown`／`no shutdown`。

#### Loop guard：擋「單向鏈路」造成的環路 ★★★★

這是最難懂、但在光纖環境最重要的一道。

**情境**：一條光纖鏈路，TX 這一芯好好的、RX 那一芯斷了（或光模組單向故障）。
結果是：**實體 Link 看起來是 up 的，但一端收不到對端的 BPDU。**

```text
     sw-core                        sw-a1f
     ┌──────┐   TX ──────▶  RX     ┌──────┐
     │      │                      │      │
     │      │   RX  ✗   斷  TX     │      │  ← Alternate Port（原本 BLK）
     └──────┘                      └──────┘

  sw-a1f 的 Alternate Port 收不到 BPDU 了
  ─▶ STP 認為「上游沒了，這條路可以放行」
  ─▶ 從 BLK 轉成 FWD                                  ★★★★★
  ─▶ 但另一條路徑還在
  ─▶ **環路成立，廣播風暴**
```

Loop guard 的邏輯：**原本收得到 BPDU 的埠，突然收不到了 → 不要放行，改成阻斷。**

**JunOS**：

```text
[edit]
admin@sw-a1f-01# set protocols rstp interface ae0 bpdu-timeout-action block
admin@sw-a1f-01# set protocols rstp interface ge-0/0/26 bpdu-timeout-action block
```

★★★ `bpdu-timeout-action` 可以設 `block`（阻斷）與／或 `alarm`（發告警）。
兩個都設是常見做法：

```text
[edit]
admin@sw-a1f-01# set protocols rstp interface ae0 bpdu-timeout-action block
admin@sw-a1f-01# set protocols rstp interface ae0 bpdu-timeout-action alarm
```

> [!info]- Cisco IOS 對照：Loop guard 與 UDLD
> ```cisco
> ! 全域啟用（只作用在 Root Port 與 Alternate Port，安全）★★★★
> sw-a1f-01(config)# spanning-tree loopguard default
>
> ! 或單埠指定
> sw-a1f-01(config)# interface Po1
> sw-a1f-01(config-if)# spanning-tree guard loop
> ```
>
> 觸發時：
> ```cisco
> %SPANTREE-2-LOOPGUARD_BLOCK: Loop guard blocking port Port-channel1 on VLAN0010.
> ```
>
> ★★★★ **UDLD 是解決同一個問題的另一種手段**（而且更直接）：
> 它主動送探測封包確認雙向都通，發現單向就把埠關掉。
> ```cisco
> sw-a1f-01(config)# udld enable                    ! 全域（只對光纖埠生效）
> sw-a1f-01(config)# interface Te1/0/49
> sw-a1f-01(config-if)# udld port aggressive        ! 對該埠強制啟用
> ```
> **光纖鏈路建議 loop guard 與 UDLD 兩者都開**：
> loop guard 是 STP 層的保險，UDLD 是實體層的偵測。
>
> JunOS 沒有 UDLD（那是 Cisco 私有），對等機制是
> `bpdu-timeout-action` 加上介面層的 `hold-time`／LACP fast 心跳。
> 混廠環境不要指望 UDLD 能跨廠牌運作。

> [!danger] ★★★★★ Loop guard 千萬不要開在使用者埠
> 使用者埠**本來就永遠收不到 BPDU**。開了 loop guard，這些埠會全部被判定為
> 「收不到 BPDU」而阻斷，**整層樓的使用者立刻斷網**。
>
> - JunOS：只在**上行埠**（ae0、備援上行）逐埠設 `bpdu-timeout-action block`
> - IOS：用全域的 `spanning-tree loopguard default`，
>   它**只作用在 Root Port 與 Alternate Port**，不會誤傷使用者埠 ★★★★

#### 三道護欄的部署矩陣 ★★★★★

| 埠類型 | BPDU guard | Root guard | Loop guard | PortFast/edge |
| --- | --- | --- | --- | --- |
| 使用者埠（PC、印表機） | ✅ **必開** | ✅ 建議 | ❌ **絕不可開** | ✅ 必開 |
| AP／IP 電話埠 | ✅ 必開 | ✅ 建議 | ❌ 絕不可開 | ✅ 必開 |
| 往下游交換器的埠 | ❌ 不可開 | ✅ **必開** | ⚠️ 視情況 | ❌ 不可開 |
| 往上游／核心的埠（Root Port） | ❌ **絕不可開** | ❌ 不可開 | ✅ **必開** | ❌ 不可開 |
| 備援上行（Alternate Port） | ❌ 絕不可開 | ❌ 不可開 | ✅ **必開** | ❌ 不可開 |
| 未使用的埠 | — | — | — | 建議直接 `disable`／`shutdown` ★★★★ |

### 二、Storm control：最後一道防線 ★★★★

護欄都可能被繞過（例如有人用一台會透通 BPDU 的媒體轉換器）。
Storm control 是**不管原因、直接限制廣播流量佔比**的保險。

**JunOS**：

```text
[edit]
admin@sw-a1f-01# set forwarding-options storm-control-profiles SC-USER all bandwidth-percentage 5
admin@sw-a1f-01# set interfaces ge-0/0/0 unit 0 family ethernet-switching storm-control SC-USER
```

★★★ `all` 表示廣播、未知單播、多播全部納入計算；
也可以只針對 `broadcast`。`bandwidth-percentage 5` 表示超過線速 5% 就丟棄。

★★★★ 加上 `action-shutdown` 可以在超標時直接關埠：

```text
[edit]
admin@sw-a1f-01# set forwarding-options storm-control-profiles SC-USER action-shutdown
```

> [!info]- Cisco IOS 對照：storm-control
> ```cisco
> sw-a1f-01(config)# interface range Gi1/0/1 - 23
> sw-a1f-01(config-if-range)# storm-control broadcast level 5.00
> sw-a1f-01(config-if-range)# storm-control multicast level 10.00
> sw-a1f-01(config-if-range)# storm-control action trap
> ! 或更激進：超標直接關埠
> ! sw-a1f-01(config-if-range)# storm-control action shutdown
>
> sw-a1f-01# show storm-control broadcast
> Interface  Filter State   Upper        Lower        Current
> ---------  -------------  -----------  -----------  ----------
> Gi1/0/1    Forwarding       5.00%        5.00%        0.02%
> Gi1/0/2    Blocking         5.00%        5.00%        4.98%   ← 正在限流 ★★★★
> ```

> [!warning] ★★★ storm-control 的門檻不能設太低
> 5% 對一般辦公埠很合理，但**影像串流、多播應用、PXE 開機、備份廣播**都可能正常超過。
> 建議：
> 1. 先設 `action trap`（只告警不阻斷）跑一週，看看正常流量的實際佔比
> 2. 依觀察結果訂門檻（取正常峰值的 2～3 倍）
> 3. 使用者埠可以設嚴一點，伺服器埠與上行埠**不要設 `action shutdown`**

### 三、MSTP：讓備援鏈路也能載流量 ★★★

RSTP 的問題：**同一時間只有一棵樹，備援鏈路完全閒置。**
MSTP 讓你把 VLAN 分組，每組跑一棵獨立的樹，不同組的根橋放不同台。

```text
  Instance 1（VLAN 10-19）根橋 = core-01     →  ae0 通，ae1 阻斷
  Instance 2（VLAN 20-29）根橋 = core-02     →  ae1 通，ae0 阻斷

  兩條上行都在載流量，互為備援。 ★★★★
```

**JunOS**：

```text
[edit]
admin@sw-a1f-01# set protocols mstp configuration-name REGION-HQ
admin@sw-a1f-01# set protocols mstp revision-level 1
admin@sw-a1f-01# set protocols mstp msti 1 vlan 10-19
admin@sw-a1f-01# set protocols mstp msti 2 vlan 20-29
admin@sw-a1f-01# set protocols mstp interface all
```

核心 01（instance 1 的根）：

```text
[edit]
admin@sw-core-01# set protocols mstp configuration-name REGION-HQ
admin@sw-core-01# set protocols mstp revision-level 1
admin@sw-core-01# set protocols mstp msti 1 vlan 10-19
admin@sw-core-01# set protocols mstp msti 2 vlan 20-29
admin@sw-core-01# set protocols mstp msti 1 bridge-priority 4096
admin@sw-core-01# set protocols mstp msti 2 bridge-priority 8192
```

> [!danger] ★★★★★ MSTP 的三個參數必須全網完全一致
> **`configuration-name`、`revision-level`、VLAN 對 instance 的對應表** —— 
> 這三者組成 MST region 的識別。**任何一個字元不同，兩台就屬於不同 region**，
> 邊界會退化成單一 CST，你精心設計的負載分擔完全失效，
> 而且**症狀非常隱晦**（網路看起來會通，只是備援鏈路又閒置了）。
>
> 驗證方式：
> ```text
> admin@sw-a1f-01> show spanning-tree mstp configuration
> MSTP information
> Context identifier            : 0
> Region name                   : REGION-HQ
> Revision                      : 1
> Configuration digest          : 0x3ab68794f6f9b3f0a6d1e0c0f9c0a1b2
> ```
> ★★★★★ **`Configuration digest` 是三個參數的雜湊。所有同 region 的設備必須完全相同。**
> 比對這個 digest 比逐條核對 VLAN 對應快一百倍。

> [!info]- Cisco IOS 對照：MST
> ```cisco
> sw-a1f-01(config)# spanning-tree mode mst
> sw-a1f-01(config)# spanning-tree mst configuration
> sw-a1f-01(config-mst)# name REGION-HQ
> sw-a1f-01(config-mst)# revision 1
> sw-a1f-01(config-mst)# instance 1 vlan 10-19
> sw-a1f-01(config-mst)# instance 2 vlan 20-29
> sw-a1f-01(config-mst)# show pending          ! ★★★★ 送出前先看差異
> sw-a1f-01(config-mst)# exit                  ! exit 才套用
>
> ! 核心 01
> sw-core-01(config)# spanning-tree mst 1 priority 4096
> sw-core-01(config)# spanning-tree mst 2 priority 8192
>
> sw-a1f-01# show spanning-tree mst configuration
> Name      [REGION-HQ]
> Revision  1     Instances configured 3
>
> Instance  Vlans mapped
> --------  ---------------------------------------------------------------------
> 0         1-9,30-4094
> 1         10-19
> 2         20-29
> -------------------------------------------------------------------------------
> ```
>
> ★★★★ IOS 的 `spanning-tree mst configuration` 是**少數有「候選設定」概念的 IOS 子模式**：
> 你改的東西要 `exit` 才會套用，`show pending` 可以先看，`abort` 可以放棄。
> 這是 Cisco 承認「MST 參數改錯會炸掉整個網路」而特地設計的保護。

### 四、聚合的進階參數 ★★★

| 參數 | JunOS | IOS | 說明 | 星級 |
| --- | --- | --- | --- | --- |
| 最少成員數 | `minimum-links 2` | `port-channel min-links 2` | 少於 N 條就整個 ae 下線 ★★★★ | ★★★★ |
| 心跳快慢 | `lacp periodic fast` | `lacp rate fast` | fast=1 秒，兩端要一致 | ★★★★ |
| 系統優先權 | `set chassis aggregated-devices ethernet lacp system-priority 100` | `lacp system-priority 100` | 決定誰主導成員選擇 | ★★ |
| 負載分散演算法 | `enhanced-hash-key`（機型相依） | `port-channel load-balance src-dst-ip` | 見「頻寬真相」 | ★★★ |
| 強制速率一致 | `link-speed 1g` | （IOS 自動要求一致） | 防止 1G 與 100M 混在一組 | ★★★ |

> [!warning] ★★★★ `minimum-links` 的兩面性
> 假設 ae0 有 4 條線、`minimum-links 3`。斷了 2 條之後，
> **JunOS 會主動把整個 ae0 下線**，讓 STP 切到備援路徑。
>
> 好處：避免「剩 2 條線但流量還是照 4 條在推」造成的嚴重壅塞。
> 壞處：**如果沒有備援路徑，你等於自己把還能用的 2 條線關掉，直接斷網。** ★★★★★
>
> 判斷原則：
> - 有 STP 備援路徑 → 設 `minimum-links` 為總數的一半以上
> - **沒有備援路徑 → 設 `minimum-links 1`**（有一條算一條）

### 五、廣播風暴的現場急救 SOP ★★★★★

這一節是本篇最重要的部分。**請印出來貼在機房牆上。**

#### 症狀辨識 ★★★★★

| 症狀 | 說明 |
| --- | --- |
| **全機櫃的埠 LED 同步狂閃** | 最明顯的特徵。正常流量是散亂閃爍，風暴是**整排燈幾乎同一節奏**、亮度接近全亮 ★★★★★ |
| **整層／整棟斷網，不是單一使用者** | 影響範圍是「一個二層網域」 |
| **SSH／Web 連交換器完全沒回應或極慢** | 交換器 CPU 被廣播打滿 ★★★★★ |
| **Console 也很慢，打字有延遲** | 同上，CPU 100% |
| **日誌狂噴 MAC 移動訊息** | IOS：`%SW_MATM-4-MACFLAP_NOTIF`；JunOS：`l2ald` 的 MAC move 訊息 ★★★★★ |
| **ping 閘道 100% 掉包或極高延遲** | |
| **重開交換器後好三十秒又壞** | ★★★★★ 這幾乎可以確診是環路，不是設備故障 |

> [!danger] ★★★★★ 「重開好一下又壞」是環路的招牌症狀
> 很多人第一反應是「交換器壞了，重開看看」。重開後 MAC 表清空、
> 緩衝區清空，網路確實會恢復十幾秒到一分鐘 —— **然後又壞掉。**
> 這個「好一下又壞」的循環就是環路的指紋。
> 不要再重開第三次了，去找環路。

#### 三分鐘急救流程 ★★★★★

```text
第 0 分鐘：確認範圍
  ├─ 影響一整個 VLAN／一整層樓？ ──▶ 高度懷疑二層環路，往下走
  └─ 只有單一使用者？             ──▶ 不是風暴，走
                                     [[040-01-17-guide-網路設備-交換器故障排除]]

第 1 分鐘：問「最近有誰動了什麼」  ★★★★★
  ├─ 有人施工／插線／搬設備／換 AP？  ──▶ 直接去那個位置，拔掉他插的線
  ├─ 剛剛做過變更？                   ──▶ 立刻回退（JunOS rollback / IOS 回退設定）
  └─ 完全沒人動？                      ──▶ 往下走（可能是光纖單向故障）

第 2 分鐘：取得可用的管理通道
  ├─ SSH 連得上（慢但會回）           ──▶ 用 SSH
  ├─ SSH 完全連不上                    ──▶ **接 Console 線**（風暴時 Console 是唯一可靠通道）★★★★★
  └─ 帶外管理埠（me0 / mgmt）可用       ──▶ 用它，帶外不受轉送平面影響 ★★★★

第 3 分鐘：定位環路埠
  ├─ 看哪些埠的流量爆掉（見下方指令）
  ├─ 看 MAC flapping 日誌指向哪兩個埠   ★★★★★
  └─ 找到後：**先關埠，不要拔線**（關埠可追溯、可還原）

之後：
  └─ 恢復確認 ──▶ 補上 BPDU guard／storm-control ──▶ 寫事件單
```

#### 定位指令 ★★★★★

**JunOS**：

```text
admin@sw-a1f-01> show interfaces extensive | match "Physical interface|Input  rate|Output rate"
Physical interface: ge-0/0/0, Enabled, Physical link is Up
  Input  rate     :  1024 bps (2 pps)
  Output rate     :  2048 bps (3 pps)
Physical interface: ge-0/0/7, Enabled, Physical link is Up
  Input  rate     : 987654321 bps (912345 pps)      ← 這裡  ★★★★★
  Output rate     : 998877665 bps (923456 pps)
```

★★★★★ **風暴埠的特徵是 input 與 output 同時接近線速，而且 pps 大得離譜。**
一個正常辦公埠平時 pps 是個位數到幾百，風暴時是**幾十萬**。

MAC 飄移日誌：

```text
admin@sw-a1f-01> show log messages | match "mac|MAC" | last 20
Sep  2 16:12:03 sw-a1f-01 l2ald[1789]: MAC move detected: 00:1b:21:aa:bb:cc moved from ge-0/0/7.0 to ge-0/0/12.0
Sep  2 16:12:03 sw-a1f-01 l2ald[1789]: MAC move detected: 00:1b:21:aa:bb:cc moved from ge-0/0/12.0 to ge-0/0/7.0
Sep  2 16:12:03 sw-a1f-01 l2ald[1789]: MAC move detected: 00:1b:21:aa:bb:cc moved from ge-0/0/7.0 to ge-0/0/12.0
```

★★★★★ **同一個 MAC 在兩個埠之間高速來回 —— 環路就在這兩個埠之間。**
這是最精確的定位方法。

緊急關埠：

```text
admin@sw-a1f-01> configure
[edit]
admin@sw-a1f-01# set interfaces ge-0/0/12 disable
admin@sw-a1f-01# commit
commit complete
```

> [!warning] ★★★★ 風暴中 commit 可能會很慢
> CPU 被打滿時，`commit` 可能要等 30 秒到數分鐘。**耐心等，不要重複下指令。**
> 如果實在等不到，才考慮直接拔線 —— 但**一定要記下拔了哪一條**，
> 並在事後補進事件單與盤點表。

> [!info]- Cisco IOS 對照：風暴定位
> ```cisco
> ! 找流量爆掉的埠
> sw-a1f-01# show interfaces | include line protocol|input rate|output rate
> GigabitEthernet1/0/7 is up, line protocol is up
>   5 minute input rate 987654000 bits/sec, 912345 packets/sec
>   5 minute output rate 998877000 bits/sec, 923456 packets/sec
>
> ! 或看利用率排行
> sw-a1f-01# show interfaces counters
>
> ! MAC flapping 日誌  ★★★★★
> sw-a1f-01# show logging | include MACFLAP
> %SW_MATM-4-MACFLAP_NOTIF: Host 001b.21aa.bbcc in vlan 10 is flapping between port Gi1/0/7 and port Gi1/0/12
>
> ! STP 拓樸變動次數
> sw-a1f-01# show spanning-tree detail | include changes
>   Number of topology changes 8472 last change occurred 00:00:01 ago
>                              ^^^^                       ^^^^^^^^^  ★★★★★
>                              數字大且一直在變 = 拓樸震盪
>
> ! 緊急關埠
> sw-a1f-01# configure terminal
> sw-a1f-01(config)# interface Gi1/0/12
> sw-a1f-01(config-if)# shutdown
> ```
>
> ★★★ IOS 的 `%SW_MATM-4-MACFLAP_NOTIF` 訊息**直接告訴你是哪兩個埠**，
> 這是排查環路最有效率的一行日誌。前提是 `logging buffered` 有開，
> 而且日誌有送到集中伺服器（見 [[100-01-02-guide-日誌-日誌集中與輪替]]）——
> 因為風暴中你可能連不上交換器，**只能靠集中日誌看發生了什麼**。

#### 事後必做四件事 ★★★★

| # | 動作 | 說明 |
| --- | --- | --- |
| 1 | 補上 BPDU guard | 所有使用者埠，一個都不能漏 ★★★★★ |
| 2 | 補上 storm-control | 至少先 `action trap` 蒐集基準 ★★★★ |
| 3 | 未使用埠全部 disable | 沒插線的埠關掉，直接消滅一整類風險 ★★★★ |
| 4 | 寫事件單並更新盤點 | 表單在 vault 的 `_表單範本/100-02-07-事件處理紀錄單.docx`；更新埠位表見 [[040-01-18-guide-網路設備-網路設備盤點與文件化]] | ★★★ |

## 完整實戰範例

**目標**：把一個「兩台接取層 + 一台核心、目前只有單上行、沒有任何 STP 護欄」的
現況網路，升級成「雙上行 LACP 聚合 + RSTP 根橋明確 + 三道護欄齊備」的架構。

**時間**：維護窗口 22:00～01:00（三小時）。
**回退**：全程 `commit confirmed`，任何一步驗證失敗立即 rollback。

### 現況與目標

```text
現況：                                目標：
  core-01                              core-01（RSTP priority 4096）
     │ ge-0/0/0（單條 1G）                  ║ ae0（2×1G LACP）
     │                                     ║
  a1f-01                               a1f-01（priority 61440，護欄齊備）
```

### 階段 0：施工前準備（22:00～22:20）★★★★★

```text
# 兩台都做
admin@sw-core-01> set cli screen-length 0
admin@sw-core-01> show configuration | display set | save /var/tmp/core01-before-20260902.set
Wrote 412 lines of output to '/var/tmp/core01-before-20260902.set'

admin@sw-core-01> file copy /var/tmp/core01-before-20260902.set scp://netadm@10.10.20.30//backup/net/
netadm@10.10.20.30's password:
core01-before-20260902.set          100%   18KB  18.3KB/s   00:00
```

記錄改前基準：

```text
admin@sw-a1f-01> show spanning-tree bridge | match "Root ID|Bridge ID|topology"
  Root ID                           : 32768.00aabbccddee      ← ★★★★ 現在根橋是 a1f-01 自己！
    Bridge ID                       : 32768.00aabbccddee
  Number of topology changes        : 147

admin@sw-a1f-01> show interfaces terse | match "ge-0/0/(24|25)"
ge-0/0/24               up    up
ge-0/0/24.0             up    up   eth-switch
ge-0/0/25               up    down                            ← 第二條線還沒接
```

★★★★★ 這裡就發現了第一個問題：**根橋是接取層交換器 a1f-01**（priority 都是預設 32768，
它的 MAC 比 core-01 小）。所有跨 VLAN 流量都在繞路。

**驗收基準記錄**（施工後要對照）：

| 項目 | 施工前 |
| --- | --- |
| 根橋 | 32768.00aabbccddee（a1f-01，錯誤）|
| 上行頻寬 | 1 Gbps |
| 上行冗餘 | 無 |
| 拓樸變動次數 | 147 |
| 使用者 ping 閘道 | 平均 0.4 ms，0% loss |

### 階段 1：先修 STP 根橋（22:20～22:40）★★★★★

★★★★★ **順序很重要：先把 STP 弄對，再動聚合。**
如果先做聚合，過程中的拓樸變動會在錯誤的根橋下重新收斂，狀況更難判讀。

**core-01**：

```text
admin@sw-core-01> configure exclusive
[edit]
admin@sw-core-01# set protocols rstp bridge-priority 4096
admin@sw-core-01# set protocols rstp interface all
admin@sw-core-01# show | compare
[edit protocols]
+   rstp {
+       bridge-priority 4096;
+       interface all;
+   }
admin@sw-core-01# commit confirmed 5 comment "CHG-2026-0921 step1 set root bridge"
commit confirmed will be automatically rolled back in 5 minutes unless confirmed
commit complete
```

**驗證（會有一次短暫的拓樸收斂，1～2 秒）**：

```text
admin@sw-core-01# run show spanning-tree bridge | match "Root ID|Bridge ID"
  Root ID                           : 4096.001122334455        ← core-01 自己 ★★★★★
    Bridge ID                       : 4096.001122334455

admin@sw-core-01# run ping 10.10.10.100 count 5 rapid
PING 10.10.10.100 (10.10.10.100): 56 data bytes
!!!!!
--- 10.10.10.100 ping statistics ---
5 packets transmitted, 5 packets received, 0% packet loss
round-trip min/avg/max/stddev = 0.412/0.489/0.601/0.071 ms
```

```text
admin@sw-core-01# commit comment "CHG-2026-0921 step1 confirmed"
commit complete
```

**a1f-01**：

```text
admin@sw-a1f-01> configure exclusive
[edit]
admin@sw-a1f-01# set protocols rstp bridge-priority 61440
admin@sw-a1f-01# set protocols rstp interface all
admin@sw-a1f-01# commit confirmed 5 comment "CHG-2026-0921 step1 access priority"
commit complete
[edit]
admin@sw-a1f-01# run show spanning-tree bridge | match "Root ID|Root port"
  Root ID                           : 4096.001122334455
  Root port                         : ge-0/0/24                ← 上行變成 Root Port ★★★★
admin@sw-a1f-01# commit comment "CHG-2026-0921 step1 confirmed"
commit complete
```

### 階段 2：建立聚合（22:40～23:20）★★★★★

★★★★★ **關鍵：第二條線這時候還沒接。全程只有一條線在跑。**

**core-01 端先設**：

```text
[edit]
admin@sw-core-01# set chassis aggregated-devices ethernet device-count 4
admin@sw-core-01# delete interfaces ge-0/0/0 unit 0
admin@sw-core-01# set interfaces ge-0/0/0 description "a1f-01-ae0-member"
admin@sw-core-01# set interfaces ge-0/0/0 ether-options 802.3ad ae0
admin@sw-core-01# set interfaces ae0 description "DOWNLINK to sw-a1f-01"
admin@sw-core-01# set interfaces ae0 aggregated-ether-options lacp active
admin@sw-core-01# set interfaces ae0 aggregated-ether-options lacp periodic fast
admin@sw-core-01# set interfaces ae0 aggregated-ether-options minimum-links 1
admin@sw-core-01# set interfaces ae0 unit 0 family ethernet-switching interface-mode trunk
admin@sw-core-01# set interfaces ae0 unit 0 family ethernet-switching vlan members [ V10-OFFICE V20-VOICE ]
admin@sw-core-01# set interfaces ae0 native-vlan-id 999
admin@sw-core-01# commit check
configuration check succeeds
```

> [!danger] ★★★★★ 這一個 commit 會讓上行短暫中斷
> `delete interfaces ge-0/0/0 unit 0` 加上重新掛進 ae0，
> 這條唯一的上行會斷約 5～15 秒。**這就是為什麼要在維護窗口做。**
> 而且 **core-01 端 commit 之後、a1f-01 端 commit 之前，兩端不匹配，上行是完全不通的** —— 
> 所以**兩端都必須從 Console 或帶外管理埠操作，不能用 SSH 走業務網路**。

```text
admin@sw-core-01# commit confirmed 10 comment "CHG-2026-0921 step2 core ae0"
commit confirmed will be automatically rolled back in 10 minutes unless confirmed
commit complete
```

**a1f-01 端接著設（從 Console 操作）**：

```text
[edit]
admin@sw-a1f-01# set chassis aggregated-devices ethernet device-count 4
admin@sw-a1f-01# delete interfaces ge-0/0/24 unit 0
admin@sw-a1f-01# set interfaces ge-0/0/24 description "core-01-ae0-member"
admin@sw-a1f-01# set interfaces ge-0/0/24 ether-options 802.3ad ae0
admin@sw-a1f-01# set interfaces ae0 description "UPLINK to sw-core-01"
admin@sw-a1f-01# set interfaces ae0 aggregated-ether-options lacp active
admin@sw-a1f-01# set interfaces ae0 aggregated-ether-options lacp periodic fast
admin@sw-a1f-01# set interfaces ae0 aggregated-ether-options minimum-links 1
admin@sw-a1f-01# set interfaces ae0 unit 0 family ethernet-switching interface-mode trunk
admin@sw-a1f-01# set interfaces ae0 unit 0 family ethernet-switching vlan members [ V10-OFFICE V20-VOICE ]
admin@sw-a1f-01# set interfaces ae0 native-vlan-id 999
admin@sw-a1f-01# commit confirmed 10 comment "CHG-2026-0921 step2 access ae0"
commit complete
```

**驗證（單一成員的 ae0）**：

```text
admin@sw-a1f-01# run show lacp interfaces ae0
Aggregated interface: ae0
    LACP state:       Role   Exp   Def  Dist  Col  Syn  Aggr  Timeout  Activity
      ge-0/0/24       Actor    No    No   Yes  Yes  Yes   Yes     Fast    Active
      ge-0/0/24     Partner    No    No   Yes  Yes  Yes   Yes     Fast    Active
    LACP protocol:        Receive State  Transmit State          Mux State
      ge-0/0/24                 Current   Fast periodic Collecting distributing

admin@sw-a1f-01# run show interfaces ae0 terse
Interface               Admin Link Proto    Local                 Remote
ae0                     up    up
ae0.0                   up    up   eth-switch

admin@sw-a1f-01# run ping 10.10.10.1 count 5 rapid
!!!!!
5 packets transmitted, 5 packets received, 0% packet loss
```

★★★★★ `Def` 兩邊都是 `No`、`Mux State` 是 `Collecting distributing` —— LACP 協商成功。
**只有看到這個結果，才可以接第二條線。**

兩端都確認：

```text
admin@sw-core-01# commit comment "CHG-2026-0921 step2 confirmed"
admin@sw-a1f-01# commit comment "CHG-2026-0921 step2 confirmed"
```

### 階段 3：加入第二條實體線（23:20～23:40）★★★★

**先做設定，最後才插線。**

```text
# core-01
[edit]
admin@sw-core-01# delete interfaces ge-0/0/1 unit 0
admin@sw-core-01# set interfaces ge-0/0/1 description "a1f-01-ae0-member"
admin@sw-core-01# set interfaces ge-0/0/1 ether-options 802.3ad ae0
admin@sw-core-01# commit comment "CHG-2026-0921 step3 core member2"
commit complete

# a1f-01
[edit]
admin@sw-a1f-01# delete interfaces ge-0/0/25 unit 0
admin@sw-a1f-01# set interfaces ge-0/0/25 description "core-01-ae0-member"
admin@sw-a1f-01# set interfaces ge-0/0/25 ether-options 802.3ad ae0
admin@sw-a1f-01# commit comment "CHG-2026-0921 step3 access member2"
commit complete
```

★★★ 這兩個 commit **不需要 confirmed**：成員埠目前沒接線，設定不會影響現有流量。

**現在才把第二條線插上**（core-01 ge-0/0/1 ↔ a1f-01 ge-0/0/25）：

```text
admin@sw-a1f-01> show lacp interfaces ae0
Aggregated interface: ae0
    LACP state:       Role   Exp   Def  Dist  Col  Syn  Aggr  Timeout  Activity
      ge-0/0/24       Actor    No    No   Yes  Yes  Yes   Yes     Fast    Active
      ge-0/0/24     Partner    No    No   Yes  Yes  Yes   Yes     Fast    Active
      ge-0/0/25       Actor    No    No   Yes  Yes  Yes   Yes     Fast    Active
      ge-0/0/25     Partner    No    No   Yes  Yes  Yes   Yes     Fast    Active

admin@sw-a1f-01> show interfaces ae0 extensive | match Speed
  Link-level type: Ethernet, MTU: 1514, Speed: 2Gbps, ...     ← 2 Gbps ★★★★★
```

**斷線測試（★★★★★ 這是本次施工的核心驗收項）**：

在一台使用者 PC 上開持續 ping：

```bash
$ ping -i 0.2 10.10.10.1
```

然後拔掉 ge-0/0/24 那條線：

```text
admin@sw-a1f-01> show lacp interfaces ae0
    LACP state:       Role   Exp   Def  Dist  Col  Syn  Aggr  Timeout  Activity
      ge-0/0/24       Actor    No   Yes    No   No   No   Yes     Fast    Active   ← Def=Yes
      ge-0/0/25       Actor    No    No   Yes  Yes  Yes   Yes     Fast    Active

admin@sw-a1f-01> show interfaces ae0 extensive | match Speed
  Link-level type: Ethernet, MTU: 1514, Speed: 1Gbps, ...     ← 降到 1G，但沒斷 ★★★★★
```

PC 端的 ping 應該**完全沒有掉包，或最多掉 1 個**。
這就是聚合相對 STP 備援的價值：**沒有 STP 收斂事件**。

```text
admin@sw-a1f-01> show spanning-tree bridge | match topology
  Number of topology changes        : 3
  Time since last topology change   : 4820 seconds      ← 拔線沒有造成拓樸變動 ★★★★★
```

**把線插回去**，確認 Speed 回到 2Gbps。

### 階段 4：部署三道護欄（23:40～00:30）★★★★★

```text
# a1f-01：使用者埠（ge-0/0/0 ~ ge-0/0/23）
[edit]
admin@sw-a1f-01# set interfaces interface-range USER-PORTS member-range ge-0/0/0 to ge-0/0/23
admin@sw-a1f-01# set protocols rstp interface ge-0/0/0 edge
...（逐埠設定；JunOS 的 protocols rstp 不支援 interface-range，需逐一列出）★★★
```

> [!warning] ★★★ JunOS 的 `interface-range` 不能用在 `protocols rstp` 底下
> `interfaces interface-range` 只能簡化 `set interfaces ...` 的設定。
> `protocols rstp interface <name>` 必須逐埠列出。
> 實務做法：**用 `| display set` 產生一份清單，在文字編輯器裡批次產生指令，
> 再用 `load set terminal` 貼回去**。這是 JunOS 批次設定的標準手法。

先在本機產生指令：

```bash
$ for i in $(seq 0 23); do
    echo "set protocols rstp interface ge-0/0/$i edge"
    echo "set protocols rstp interface ge-0/0/$i no-root-port"
  done > /tmp/guards.set
$ wc -l /tmp/guards.set
48 /tmp/guards.set
```

貼回交換器：

```text
[edit]
admin@sw-a1f-01# load set terminal
[Type ^D at a new line to end input]
set protocols rstp interface ge-0/0/0 edge
set protocols rstp interface ge-0/0/0 no-root-port
...
（貼上全部 48 行，然後按 Ctrl+D）
load complete

[edit]
admin@sw-a1f-01# set protocols rstp bpdu-block-on-edge
admin@sw-a1f-01# set protocols layer2-control bpdu-block disable-timeout 300
admin@sw-a1f-01# set protocols rstp interface ae0 bpdu-timeout-action block
admin@sw-a1f-01# set protocols rstp interface ae0 bpdu-timeout-action alarm
```

★★★★★ **檢查最重要的一件事：上行埠絕對不能有 `edge`**：

```text
[edit]
admin@sw-a1f-01# show protocols rstp | display set | match "ae0"
set protocols rstp interface ae0 bpdu-timeout-action block
set protocols rstp interface ae0 bpdu-timeout-action alarm
                                  ← 沒有 edge、沒有 no-root-port  ✓ ★★★★★

admin@sw-a1f-01# show protocols rstp | display set | match "edge" | count
Count: 24 lines                   ← 剛好 24 個使用者埠  ✓
```

```text
[edit]
admin@sw-a1f-01# commit confirmed 5 comment "CHG-2026-0921 step4 guards"
commit complete
[edit]
admin@sw-a1f-01# run show spanning-tree interface | match "ge-0/0/(0|1|2)\b"
ge-0/0/0       128:2       128:2 61440.00aabbccddee       200000    FWD    DESG
ge-0/0/1       128:3       128:3 61440.00aabbccddee       200000    FWD    DESG
ge-0/0/2       128:4       128:4 61440.00aabbccddee       200000    FWD    DESG
                                                                    ↑ 使用者埠仍正常轉送 ✓
admin@sw-a1f-01# commit comment "CHG-2026-0921 step4 confirmed"
```

### 階段 5：護欄實測（00:30～00:45）★★★★★

★★★★★ **沒有實測過的護欄等於沒有護欄。**

**測試 BPDU guard**：拿一台小型交換器（或啟用 STP 的測試設備），
接到閒置的 ge-0/0/23：

```text
admin@sw-a1f-01> show spanning-tree interface ge-0/0/23
ge-0/0/23      128:24      128:24 61440.00aabbccddee      200000    BLK    DIS
                                                                     ↑ 被擋下 ✓ ★★★★★

admin@sw-a1f-01> show log messages | match ge-0/0/23 | last 2
Sep  3 00:34:12 sw-a1f-01 l2cpd[1523]: BPDU_BLOCK: ge-0/0/23 is blocked due to BPDU received
```

拔掉測試交換器，等 300 秒（`disable-timeout`）：

```text
admin@sw-a1f-01> show spanning-tree interface ge-0/0/23
ge-0/0/23      128:24      128:24 61440.00aabbccddee      200000    FWD    DESG
                                                                     ↑ 自動恢復 ✓ ★★★★
```

### 階段 6：驗收與收尾（00:45～01:00）★★★★

**驗收清單**：

| # | 項目 | 指令 | 通過標準 | 結果 |
| --- | --- | --- | --- | --- |
| 1 | 根橋正確 | `show spanning-tree bridge` | Root ID = 4096.001122334455 | ✓ |
| 2 | 上行是 Root Port | `show spanning-tree interface` | ae0 = FWD/ROOT | ✓ |
| 3 | ae0 兩條線都 bundled | `show lacp interfaces ae0` | 兩埠 Def=No, Mux=Collecting distributing | ✓ |
| 4 | 聚合頻寬 | `show interfaces ae0 extensive` | Speed: 2Gbps | ✓ |
| 5 | 斷一條不掉包 | 持續 ping + 拔線 | 掉包 ≤ 1 | ✓ |
| 6 | 使用者埠有 edge | `show protocols rstp \| display set \| match edge \| count` | 24 | ✓ |
| 7 | 上行埠**沒有** edge | `show protocols rstp \| display set \| match ae0` | 無 edge ★★★★★ | ✓ |
| 8 | BPDU guard 實測 | 接測試交換器 | 埠被 BLK | ✓ |
| 9 | 拓樸穩定 | 觀察 30 分鐘 | topology changes 不再增加 | ✓ |
| 10 | 使用者連線正常 | 抽測 5 台 PC ping 閘道 + 開內部網站 | 全通 | ✓ |

**收尾**：

```text
admin@sw-a1f-01> show configuration | display set | save /var/tmp/a1f01-after-20260902.set
admin@sw-a1f-01> file copy /var/tmp/a1f01-after-20260902.set scp://netadm@10.10.20.30//backup/net/
```

**必須更新的文件**（詳見 [[040-01-18-guide-網路設備-網路設備盤點與文件化]]）：

| 文件 | 更新內容 |
| --- | --- |
| 邏輯拓樸圖 | 單線改雙線 ae0，標註根橋位置與 priority |
| 埠位表 | ge-0/0/24、ge-0/0/25 用途改為 ae0 member |
| 線路標示紀錄 | 新增第二條上行線的標籤（`_表單範本/040-02-04-線路標示紀錄.docx`）|
| 設定 git repo | commit 施工後設定，訊息帶變更單號 |
| 變更申請單 | 填寫實際執行結果與驗收清單（`_表單範本/100-02-06-變更管理申請單.docx`）|

## 常見錯誤與排錯

| 現象 | 原因 | 解法 | 星級 |
| --- | --- | --- | --- |
| JunOS commit 報 `ae0: interface does not exist` | 沒設 `chassis aggregated-devices ethernet device-count` | 先設 device-count 再設 ae0 | ★★★★★ |
| JunOS commit 報 `ge-0/0/24: Only one family can be configured` 或類似 | 成員埠上還有 `unit 0 family ethernet-switching` 殘留 | `delete interfaces ge-0/0/24 unit 0` 後再掛 802.3ad | ★★★★ |
| `show lacp interfaces ae0` 的 `Def` 欄是 `Yes` | **沒收到對端 LACP PDU**：對端沒設、設成 passive/on、或線接錯埠 | 檢查對端設定與實體接線；兩端都改 active | ★★★★★ |
| `Mux State` 停在 `Detached` 或 `Waiting` | 協商未完成，常見於速率／雙工不一致 | 確認兩端速率相同；必要時明確設 `link-speed` | ★★★★ |
| IOS `show etherchannel summary` 出現 `(I)` stand-alone | 該埠沒能加入 Port-channel，仍在獨立轉送 | ★★★★★ **潛在環路**，立即 `shutdown` 該埠，查對端設定 | ★★★★★ |
| IOS 出現 `(s)` suspended | 兩端 VLAN allowed list、native VLAN、速率或雙工不一致 | 逐項比對兩端 `show interfaces switchport` | ★★★★ |
| 聚合設好了但吞吐量還是只有單條 | hash 落在同一條線上（單一大流） | 這是設計如此，見「聚合的頻寬真相」；改 hash 演算法只能改善多流分佈 | ★★★★ |
| 一端 `mode on`、另一端 `mode active` | 靜態端不協商、動態端協商不成 | 兩端統一 LACP active；`mode on` 是環路溫床 | ★★★★★ |
| 全網路根橋是一台接取層小交換器 | 沒有手動設 bridge-priority，比 MAC 大小 | 核心設 4096、備援設 8192、接取層設 61440 | ★★★★★ |
| Cisco `spanning-tree vlan X root primary` 過一陣子失效 | 那是巨集，只在下指令當下計算一次 | 改成寫死 `spanning-tree vlan X priority 4096` | ★★★★ |
| 使用者插線後要等 30 秒才通 | 該埠沒設 PortFast／edge，走完整 STP 狀態機 | 使用者埠一律設 `edge`／`portfast` | ★★★★ |
| 設了 PortFast 之後偶爾出現短暫環路 | PortFast 埠接上就轉送，若接的是交換器就出事 | **PortFast 必須配 BPDU guard**，兩者一定成對 | ★★★★★ |
| 開了 BPDU guard 之後上行整個斷掉 | 誤把上行埠設成 edge／PortFast | 上行埠移除 edge；IOS 明確 `spanning-tree portfast disable` | ★★★★★ |
| 開了 loop guard 之後使用者埠全斷 | 誤把 loop guard 開在使用者埠（本來就收不到 BPDU） | 只在 Root/Alternate Port 開；IOS 用 `loopguard default` 較安全 | ★★★★★ |
| `show spanning-tree inconsistentports` 顯示 Root Inconsistent | Root guard 擋到了下游送來的 superior BPDU | 找出那台違規設備（通常是使用者私接的交換器）並移除 | ★★★★ |
| MSTP 設好了但備援鏈路還是閒置 | region 參數不一致，退化成單一 CST | 比對三台的 `Configuration digest` 是否完全相同 | ★★★★★ |
| 光纖鏈路 Link up 但流量不通，且偶發環路 | 單向鏈路（一芯斷或光模組單向故障） | 開 loop guard（＋Cisco 的 UDLD）；換光纖跳線與模組實測 | ★★★★★ |
| 網路每隔幾分鐘卡一下 | STP 拓樸震盪；常見於某條線 flapping 或某埠沒設 edge | `show spanning-tree bridge` 看 topology changes；找出 flapping 的埠 | ★★★★★ |
| 重開交換器後好三十秒又壞 | 環路 | 不要再重開，走「三分鐘急救流程」定位環路埠 | ★★★★★ |
| storm-control 上線後某些應用不能用 | 門檻設太低，正常多播／廣播被丟 | 先改 `action trap` 收集基準，依實際峰值調門檻 | ★★★ |

## 安全性注意事項

> [!danger] ★★★★★ 三個會直接造成全網中斷的操作
> | 操作 | 後果 |
> | --- | --- |
> | 在上行埠開 BPDU guard／設 edge | 上行數秒內被自己關掉，整台交換器脫離網路 |
> | 在使用者埠開 loop guard | 該埠因「收不到 BPDU」被判定異常而阻斷，整層樓斷網 |
> | 改動 MSTP 的 region 三參數但只改一台 | 該台脫離 region，拓樸重算，可能造成環路或大量流量繞路 |

### 把「使用者私接交換器」當成必然會發生的事 ★★★★★

這不是假設，是機關網路的常態。防線要疊三層：

| 層 | 機制 | 擋住什麼 |
| --- | --- | --- |
| 1 | **BPDU guard** | 有 STP 的交換器（大多數） ★★★★★ |
| 2 | **MAC limit／port security** | 沒有 STP 的啞交換器或 hub（BPDU guard 擋不到）★★★★ |
| 3 | **Storm control** | 前兩層都失守時的最後限流 ★★★★ |

**MAC limit（JunOS）**：

```text
[edit]
admin@sw-a1f-01# set switch-options interface ge-0/0/5 interface-mac-limit 3
admin@sw-a1f-01# set switch-options interface ge-0/0/5 interface-mac-limit packet-action drop
```

★★★ 一般辦公埠設 2～3 個 MAC（PC + IP 電話 + 虛擬機橋接），
超過就代表後面接了東西。設 `packet-action drop` 而不是 `shut` 比較不會誤傷。

> [!info]- Cisco IOS 對照：port-security
> ```cisco
> sw-a1f-01(config)# interface Gi1/0/5
> sw-a1f-01(config-if)# switchport port-security
> sw-a1f-01(config-if)# switchport port-security maximum 3
> sw-a1f-01(config-if)# switchport port-security violation restrict
> sw-a1f-01(config-if)# switchport port-security aging time 60
> sw-a1f-01(config-if)# switchport port-security aging type inactivity
> ```
> ★★★★ `violation` 三種模式：
> - `protect`：丟棄超額 MAC 的封包，不告警（不建議，出事你不會知道）
> - `restrict`：丟棄 + 告警 + 計數 ★★★★ **建議值**
> - `shutdown`：直接 err-disable（預設值，但容易誤傷，例如使用者換電腦）

### 未使用的埠 ★★★★

```text
[edit]
admin@sw-a1f-01# set interfaces ge-0/0/20 disable
admin@sw-a1f-01# set interfaces ge-0/0/20 description "UNUSED - disabled 2026-09-02"
```

★★★★ **關掉未使用的埠是投報率最高的一個動作**：
一次消滅「未授權接入」「意外環路」「未經核准的設備上線」三類風險。
記得在 description 註明日期，日後才知道是刻意關的還是壞的。

### 設定與日誌 ★★★

- ★★★★ **STP 相關日誌一定要送到集中伺服器**。風暴發生時你連不上交換器，
  集中日誌是唯一能還原現場的東西。設定見 [[100-01-02-guide-日誌-日誌集中與輪替]]。
- ★★★★ 對 `topology changes` 做監控告警：短時間內暴增就是拓樸震盪的前兆。
  監控設定見 [[100-01-03-guide-日誌-系統監控與告警]]。
- ★★★ 每次改 STP 或聚合都留 commit comment 帶變更單號，事後查得到是誰改的。

## 速查表

### LACP／聚合

| 目的 | JunOS | Cisco IOS |
| --- | --- | --- |
| 宣告聚合介面數量 | `set chassis aggregated-devices ethernet device-count 4` ★★★★★ | （建 `interface Port-channel1` 即可） |
| 掛成員埠 | `set interfaces ge-0/0/24 ether-options 802.3ad ae0` | `channel-group 1 mode active` |
| 啟用 LACP | `set interfaces ae0 aggregated-ether-options lacp active` | `channel-group 1 mode active` |
| 快心跳 | `... lacp periodic fast` | `lacp rate fast` |
| 最少成員 | `... minimum-links 2` | `port-channel min-links 2` |
| 看聚合狀態 | `show lacp interfaces ae0` ★★★★★ | `show etherchannel summary` ★★★★★ |
| 看對端資訊 | `show lacp interfaces ae0 extensive` | `show lacp neighbor` |
| 看聚合頻寬 | `show interfaces ae0 extensive \| match Speed` | `show interfaces Po1` |
| 負載分散演算法 | `enhanced-hash-key`（機型相依） | `port-channel load-balance src-dst-ip` |

### STP

| 目的 | JunOS | Cisco IOS |
| --- | --- | --- |
| 啟用 RSTP | `set protocols rstp` ★★★★ | `spanning-tree mode rapid-pvst` |
| 啟用 MSTP | `set protocols mstp` | `spanning-tree mode mst` |
| 設根橋 | `set protocols rstp bridge-priority 4096` ★★★★★ | `spanning-tree vlan X priority 4096` ★★★★★ |
| 邊緣埠 | `set protocols rstp interface ge-0/0/1 edge` | `spanning-tree portfast edge` |
| 全域邊緣預設 | （逐埠設定） | `spanning-tree portfast edge default` ★★★★ |
| 埠路徑成本 | `set protocols rstp interface ge-0/0/1 cost 20000` | `spanning-tree cost 4` |
| 看根橋 | `show spanning-tree bridge` ★★★★★ | `show spanning-tree root` ★★★★★ |
| 看埠角色狀態 | `show spanning-tree interface` ★★★★★ | `show spanning-tree` ★★★★★ |
| 看拓樸變動 | `show spanning-tree bridge \| match topology` ★★★★★ | `show spanning-tree detail \| include changes` ★★★★★ |
| 看被擋的埠 | `show spanning-tree interface \| match BLK` | `show spanning-tree inconsistentports` ★★★★★ |
| MSTP region 檢查 | `show spanning-tree mstp configuration` ★★★★★ | `show spanning-tree mst configuration` ★★★★★ |

### 三道護欄

| 護欄 | JunOS | Cisco IOS | 裝哪裡 |
| --- | --- | --- | --- |
| BPDU guard | `set protocols rstp bpdu-block-on-edge` ★★★★★ | `spanning-tree portfast bpduguard default` ★★★★★ | 使用者埠 |
| BPDU guard 自動恢復 | `set protocols layer2-control bpdu-block disable-timeout 300` | `errdisable recovery cause bpduguard` + `interval 300` | — |
| Root guard | `set protocols rstp interface ge-0/0/1 no-root-port` ★★★★★ | `spanning-tree guard root` ★★★★★ | 下游埠 |
| Loop guard | `set protocols rstp interface ae0 bpdu-timeout-action block` ★★★★ | `spanning-tree loopguard default` ★★★★ | 上行埠 |
| 單向偵測 | （無 UDLD 對等物） | `udld port aggressive` ★★★★ | 光纖埠 |
| Storm control | `set forwarding-options storm-control-profiles SC all bandwidth-percentage 5` | `storm-control broadcast level 5.00` | 使用者埠 |
| MAC 上限 | `set switch-options interface ge-0/0/5 interface-mac-limit 3` | `switchport port-security maximum 3` | 使用者埠 |

### 風暴急救

| 步驟 | JunOS | Cisco IOS |
| --- | --- | --- |
| 找爆流量的埠 | `show interfaces extensive \| match "Physical interface\|Input  rate"` | `show interfaces \| include line protocol\|input rate` |
| 找 MAC 飄移 | `show log messages \| match "MAC move"` ★★★★★ | `show logging \| include MACFLAP` ★★★★★ |
| 看拓樸震盪 | `show spanning-tree bridge \| match topology` | `show spanning-tree detail \| include changes` |
| 緊急關埠 | `set interfaces ge-0/0/12 disable` ＋ `commit` | `interface Gi1/0/12` ＋ `shutdown` |
| 可靠的管理通道 | Console ／ `me0` 帶外埠 ★★★★★ | Console ／ mgmt 埠 ★★★★★ |

### 數字速記

| 數字 | 意義 |
| --- | --- |
| 32768 | Bridge priority 預設值 ★★★★ |
| 4096 | Priority 的最小步進；主根橋建議值 ★★★★★ |
| 8192 | 備援根橋建議值 ★★★★ |
| 61440 | Priority 最大值；接取層建議值 ★★★ |
| 2 秒 | Hello time 預設 |
| 20 秒 | Max age 預設 |
| 15 秒 | Forward delay 預設 |
| 30～50 秒 | 傳統 STP 收斂時間 ★★★★ |
| 1～2 秒 | RSTP 收斂時間 ★★★★★ |
| 1 秒／30 秒 | LACP fast／slow 心跳 |
| 3 秒／90 秒 | LACP fast／slow 偵測失效時間 ★★★ |
| 300 秒 | MAC 表老化時間預設（兩家皆是） ★★★ |

## 練習題

> [!question]- 練習 1：判讀 LACP 輸出 ★★★★★
> 你在 sw-a1f-01 看到：
>
> ```text
> admin@sw-a1f-01> show lacp interfaces ae0
> Aggregated interface: ae0
>     LACP state:       Role   Exp   Def  Dist  Col  Syn  Aggr  Timeout  Activity
>       ge-0/0/24       Actor    No    No   Yes  Yes  Yes   Yes     Fast    Active
>       ge-0/0/24     Partner    No    No   Yes  Yes  Yes   Yes     Fast    Active
>       ge-0/0/25       Actor    No   Yes    No   No   No   Yes     Fast    Active
> ```
>
> ge-0/0/25 發生了什麼？請列出三個最可能的原因與對應的檢查方式。
>
> **參考答案**
>
> **`Def`（Defaulted）= `Yes` 表示這個埠完全沒有收到對端的 LACP PDU**，
> 所以套用預設值，`Dist`／`Col`／`Syn` 全部是 `No`，這條線**沒有納入聚合、不轉送流量**。
> 注意輸出裡連 `Partner` 那一列都沒出現 —— 因為根本沒有 partner。
>
> | 可能原因 | 檢查方式 | 星級 |
> | --- | --- | --- |
> | 對端沒有設定聚合，或設成 `mode on`（不送 LACP PDU） | 到對端 `show lacp interfaces ae0` / `show etherchannel summary` | ★★★★★ |
> | 線接錯埠（接到對端的另一個 ae 或一般埠） | `show lldp neighbors ge-0/0/25` 看對面到底是誰的哪個埠 | ★★★★★ |
> | 實體層問題（線壞、光模組單向故障） | `show interfaces ge-0/0/25 extensive` 看 Link 狀態與錯誤計數 | ★★★★ |
>
> ★★★★ 補充：如果對端設成 LACP **passive** 而本端也是 passive，也會是這個結果 —— 
> 兩邊都在等對方先開口。**至少一端必須是 active，建議兩端都 active。**

> [!question]- 練習 2：規劃三道護欄的部署位置 ★★★★★
> 拓樸如下，請寫出每一個埠應該套用哪些護欄：
>
> ```text
>            core-01 (priority 4096)
>              │ ae0
>            a1f-01
>       ┌──────┼──────┬─────────┐
>   ge-0/0/1  ge-0/0/2  ge-0/0/20  ge-0/0/26
>     PC       IP電話    b1f-01     （備援上行到 core-02，STP 阻斷中）
>                       (下游交換器)
> ```
>
> **參考答案**
>
> | 埠 | 角色 | edge/PortFast | BPDU guard | Root guard | Loop guard |
> | --- | --- | --- | --- | --- | --- |
> | `ae0` | Root Port（上行） | ❌ **絕不可** | ❌ **絕不可** ★★★★★ | ❌ | ✅ **必開** |
> | `ge-0/0/1` | 使用者（PC） | ✅ | ✅ | ✅ 建議 | ❌ **絕不可** ★★★★★ |
> | `ge-0/0/2` | 使用者（IP 電話） | ✅ | ✅ | ✅ 建議 | ❌ 絕不可 |
> | `ge-0/0/20` | 往下游交換器 | ❌ | ❌ | ✅ **必開** ★★★★★ | ⚠️ 可選 |
> | `ge-0/0/26` | Alternate Port（備援上行） | ❌ | ❌ 絕不可 | ❌ | ✅ **必開** ★★★★★ |
>
> JunOS 設定：
> ```text
> set protocols rstp interface ge-0/0/1 edge
> set protocols rstp interface ge-0/0/1 no-root-port
> set protocols rstp interface ge-0/0/2 edge
> set protocols rstp interface ge-0/0/2 no-root-port
> set protocols rstp interface ge-0/0/20 no-root-port
> set protocols rstp interface ae0 bpdu-timeout-action block
> set protocols rstp interface ge-0/0/26 bpdu-timeout-action block
> set protocols rstp bpdu-block-on-edge
> set protocols layer2-control bpdu-block disable-timeout 300
> ```
>
> ★★★★★ **最容易犯的錯**：把 `ae0` 或 `ge-0/0/26` 誤設成 `edge`。
> 上行埠本來就會收到 BPDU，設了 edge + `bpdu-block-on-edge` 之後
> 這台交換器會在幾秒內把自己所有上行關掉。

> [!question]- 練習 3：計算誰會當根橋 ★★★★
> 四台交換器，設定如下。誰會是根橋？如果那台掛掉，換誰？
>
> | 交換器 | Priority | MAC |
> | --- | --- | --- |
> | core-01 | 32768（預設） | `00:11:22:33:44:55` |
> | core-02 | 32768（預設） | `00:11:22:33:44:66` |
> | a1f-01 | 32768（預設） | `00:0a:0b:0c:0d:0e` |
> | b1f-01 | 32768（預設） | `00:ff:ee:dd:cc:bb` |
>
> **參考答案**
>
> **根橋是 a1f-01**（接取層交換器）。因為 priority 全部相同（32768），
> 比的是 MAC 位址大小，`00:0a:...` 是四者中最小的。
>
> a1f-01 掛掉後，換 **core-01**（`00:11:...` 是剩下三台中最小的）。
>
> ★★★★★ 這正是本篇強調「**必須手動指定 priority**」的原因：
> 預設情況下，你的網路核心會由「哪台交換器的 MAC 位址最小」決定，
> 而這通常等於「哪台最老」。正確設法：
>
> ```text
> # core-01
> set protocols rstp bridge-priority 4096
> # core-02
> set protocols rstp bridge-priority 8192
> # a1f-01 / b1f-01
> set protocols rstp bridge-priority 61440
> ```
>
> ★★★★ 額外注意：光設 priority 還不夠。有人插一台預設 32768 的新交換器進來，
> 它就贏過接取層的 61440。所以**還要在下游埠開 root guard**。

> [!question]- 練習 4：現場急救演練 ★★★★★
> 早上九點，總機打電話說「三樓全部不能上網」。你 SSH 連 sw-c3f-01 沒有回應，
> ping 它的管理 IP 掉包 90%。請寫出你接下來十五分鐘的行動順序。
>
> **參考答案**
>
> | 分鐘 | 動作 | 理由 |
> | --- | --- | --- |
> | 0-1 | 確認影響範圍：只有三樓還是全棟？問資訊室其他人有沒有異常 | 範圍決定是二層環路還是別的問題 ★★★★ |
> | 1-2 | **問「今天早上誰動了什麼」** —— 打給三樓總務、問有沒有人搬桌子、接設備、新來的同仁報到 | ★★★★★ 環路九成來自人為施工，這一步常常直接破案 |
> | 2-3 | 看集中日誌伺服器（不是交換器本身）搜尋 MACFLAP／MAC move／topology change | ★★★★★ 交換器連不上時，集中日誌是唯一的現場紀錄 |
> | 3-5 | 帶 Console 線與筆電**去三樓機櫃** | 風暴時 SSH 不可靠，Console 是唯一穩定通道 |
> | 5-6 | 到現場先看燈：整排埠燈同步狂閃 → 確診風暴 | ★★★★★ |
> | 6-8 | 接 Console 登入，跑 `show interfaces extensive \| match "Physical interface\|Input  rate"` 找 pps 幾十萬的埠 | 定位環路埠 |
> | 8-9 | 交叉比對 `show log messages \| match "MAC move"`，確認是哪兩個埠在飄 | ★★★★★ 最精確的定位法 |
> | 9-10 | 對該埠 `set interfaces ge-0/0/X disable` ＋ `commit`（可能要等 30 秒） | **關埠而不是拔線**，可追溯 |
> | 10-12 | 確認網路恢復：ping 閘道、抽測兩台 PC、看 topology changes 停止增加 | |
> | 12-15 | 去現場看那個埠的牆上網路孔接了什麼；拍照存證；填事件單 | `_表單範本/100-02-07-事件處理紀錄單.docx` |
>
> **當天稍後必做**：把三樓所有使用者埠補上 `edge` + `bpdu-block-on-edge`，
> 未使用埠全部 disable。★★★★★ 這次能發生，就代表護欄沒做完。

> [!question]- 練習 5：設計一份 STP 與聚合的巡檢項目 ★★★★
> 為每月巡檢設計 6 項與 STP／聚合相關的檢查，寫出指令與判定標準。
>
> **參考答案**
>
> | # | 檢查項 | JunOS 指令 | 判定標準 | 星級 |
> | --- | --- | --- | --- | --- |
> | 1 | 根橋位置正確 | `show spanning-tree bridge \| match "Root ID"` | 全網都指向核心的 4096.xxxx | ★★★★★ |
> | 2 | 拓樸未震盪 | `show spanning-tree bridge \| match topology` | `Time since last topology change` > 7 天 | ★★★★★ |
> | 3 | 沒有非預期的阻斷埠 | `show spanning-tree interface \| match BLK` | 只有規劃中的備援埠是 BLK | ★★★★ |
> | 4 | 聚合成員數正確 | `show lacp interfaces ae0` | 所有成員 `Def=No`、`Mux=Collecting distributing` | ★★★★★ |
> | 5 | 聚合頻寬正確 | `show interfaces ae0 extensive \| match Speed` | 等於「單條速率 × 成員數」 | ★★★★ |
> | 6 | 護欄設定沒被改掉 | `show protocols rstp \| display set \| match "edge\|no-root-port"` ＋ 與 git 內基準比對 | 與 baseline 完全一致 | ★★★★★ |
>
> ★★★★ 第 6 項最好自動化：把每台設定 `| display set` 抓下來丟進 git，
> 用 `git diff` 比對月初與月末。做法見 [[040-01-18-guide-網路設備-網路設備盤點與文件化]]。
> 巡檢表格式參考 vault 的 `_表單範本/100-02-03-每月維護檢查表.docx`。

## 小測驗

Q1. （是非）在交換器之間接兩條線就有備援，只要有一條斷了另一條會接手，
所以不需要特別設定 STP。

Q2. （選擇）四條 1G 鏈路做 LACP 聚合後，一台伺服器用 scp 傳一個 100 GB 的檔案到另一台伺服器，
最高可以跑到多少？
（A）4 Gbps （B）約 1 Gbps （C）2 Gbps （D）視 hash 演算法可達 4 Gbps

Q3. （簡答）BPDU guard、root guard、loop guard 分別該裝在哪一類埠上？
如果把 loop guard 裝在使用者埠會發生什麼？

Q4. （這行指令會發生什麼）
```text
[edit]
admin@sw-a1f-01# set protocols rstp interface ae0 edge
admin@sw-a1f-01# set protocols rstp bpdu-block-on-edge
admin@sw-a1f-01# commit
```
ae0 是這台交換器唯一的上行。commit 之後會發生什麼？

Q5. （選擇）`show lacp interfaces ae0` 中某成員埠的 `Def` 欄顯示 `Yes`，最可能的原因是？
（A）該埠實體斷線 （B）該埠沒有收到對端的 LACP PDU （C）該埠速率設定錯誤
（D）該埠被 STP 阻斷

Q6. （是非）Cisco 的 `spanning-tree vlan 10 root primary` 是一個永久生效的設定，
之後就算加入 priority 更低的設備，這台仍然會是根橋。

Q7. （簡答）你在 `show etherchannel summary` 看到 `Gi1/0/25(I)`。
`(I)` 代表什麼？為什麼這是必須立刻處理的狀況？

Q8. （選擇）交換器重開後網路好三十秒又壞，重複好幾次。最可能是？
（A）交換器硬體故障 （B）韌體 bug （C）二層環路 （D）DHCP 位址池用完

Q9. （簡答）MSTP 的哪三個參數必須在全網完全一致？有一個快速比對的方法是什麼？

Q10. （這行指令會發生什麼）ae0 目前有 4 個成員、設定 `minimum-links 3`，
現在斷了 2 條線，而這台交換器**沒有其他備援上行**。會發生什麼？

> [!question]- 測驗答案
> **Q1.** **否。** ★★★★★ 兩條線之間如果沒有 STP（或聚合）管理，
> 二層 frame 沒有 TTL，廣播會在兩條線之間無限繞行，**幾秒內形成廣播風暴**，
> 整個二層網域癱瘓。這不是備援，是災難。
> → 見「觀念說明／一、二層網路為什麼會被自己害死」
>
> **Q2.** **（B）約 1 Gbps。** ★★★★ 聚合是依 hash 把**不同的流**分到不同實體線，
> 同一條 TCP 連線的所有封包 hash 相同，永遠走同一條線。
> 改 hash 演算法只能改善「多條流的分佈均勻度」，改不了「單一條流不會被分割」。
> → 見「觀念說明／七、聚合的頻寬真相」
>
> **Q3.**
> - **BPDU guard** → 使用者／邊緣埠（收到 BPDU 就代表有人私接交換器）
> - **Root guard** → 朝下游的埠（防止下游設備搶當根橋）
> - **Loop guard** → 上行的 Root Port 與 Alternate Port（防單向鏈路造成的環路）
>
> ★★★★★ 把 loop guard 裝在使用者埠：使用者埠**本來就永遠收不到 BPDU**，
> loop guard 會把它們全部判定為異常並阻斷，**整層樓的使用者立刻斷網**。
> → 見「進階應用／一、三道護欄」與部署矩陣
>
> **Q4.** ★★★★★ **這台交換器會在數秒內把自己的唯一上行關掉，整台脫離網路。**
> `edge` 宣告 ae0 是邊緣埠，`bpdu-block-on-edge` 讓所有邊緣埠一收到 BPDU 就阻斷；
> 而上行**本來就會持續收到核心送來的 BPDU**，所以立刻觸發。
> 之後只能從 Console 或 me0 帶外埠進去 rollback。
> **這是「開護欄反而造成事故」最典型的一種。**
> → 見「進階應用／BPDU guard」的 danger callout
>
> **Q5.** **（B）該埠沒有收到對端的 LACP PDU。** `Def` = Defaulted，
> 表示只能套用預設值。常見原因：對端沒設聚合、對端設成 `mode on`（不送 PDU）、
> 兩端都是 passive、或線接錯埠。
> → 見「安裝或基礎操作／JunOS：建立 ae0 聚合」的判讀表
>
> **Q6.** **否。** ★★★★ `root primary` 是一個**巨集**，IOS 在你下指令的當下
> 去看目前根橋的 priority，算一個更小的值寫進設定，之後就不再重算。
> 如果日後加入 priority 更小的設備，它就會奪走根橋地位。
> **正式環境應該直接寫死 `spanning-tree vlan 10 priority 4096`。**
> → 見「安裝或基礎操作／Cisco IOS 對照：Rapid PVST+」
>
> **Q7.** ★★★★★ `(I)` = **stand-alone**，表示這個埠**沒能加入 Port-channel，
> 正在以獨立實體埠的身分轉送流量**。
> 危險之處：對端可能認為它是 Port-channel 的一部分（於是 STP 只看到一個邏輯埠），
> 而本端把它當獨立埠 —— **這就形成一個 STP 看不見的環路**，
> 隨時可能爆發廣播風暴。應立刻 `shutdown` 該埠，再查對端設定與接線。
> → 見「安裝或基礎操作／Cisco IOS 對照」的旗標判讀表
>
> **Q8.** **（C）二層環路。** ★★★★★ 重開後 MAC 表與緩衝區清空，網路會短暫恢復，
> 但環路還在，廣播很快又累積起來 —— 這個「好一下又壞」的循環是環路的招牌指紋。
> 不要再重開，改走「三分鐘急救流程」定位環路埠。
> → 見「進階應用／五、廣播風暴的現場急救」
>
> **Q9.** 三個參數：**`configuration-name`（region 名稱）、`revision-level`（修訂版號）、
> VLAN 對 instance 的對應表**。任何一個不同，兩台就屬於不同 region。
>
> 快速比對法：★★★★★ 看 **`Configuration digest`**
> （`show spanning-tree mstp configuration` / `show spanning-tree mst configuration`）——
> 它是這三個參數的雜湊值，**同 region 的設備必須完全相同**。
> 比逐條核對 VLAN 對應快非常多。
> → 見「進階應用／三、MSTP」
>
> **Q10.** ★★★★★ **JunOS 會把整個 ae0 下線，交換器完全斷網。**
> `minimum-links 3` 表示「成員少於 3 條就整個聚合視為失效」，
> 目的是讓 STP 切到備援路徑。但題目說**沒有其他備援上行** —— 
> 於是你等於自己把還能用的 2 條線關掉，造成本來不會發生的斷網。
>
> **判斷原則**：有備援路徑才設較高的 `minimum-links`；
> **沒有備援路徑就設 `minimum-links 1`**。
> → 見「進階應用／四、聚合的進階參數」的 warning callout

## 延伸閱讀

- [[040-01-17-guide-網路設備-交換器故障排除]] —— 依症狀編號的完整排查流程，含環路與雙工不一致
- [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]] —— 兩平台指令一頁式對照與 commit/reload 保險
- [[040-01-06-guide-Juniper-VLAN與Trunk設定]] —— trunk 與 VLAN 的完整設定
- [[040-01-11-guide-Cisco-VLAN與Trunk設定]] —— IOS 端的 trunk 設定
- [[040-01-08-guide-Juniper-埠設定與安全]] —— MAC limit、DHCP snooping 等埠層安全
- [[040-01-13-guide-Cisco-埠設定與安全]] —— port-security 與 DAI
- [[040-01-01-guide-網路設備-網路架構基礎]] —— 三層架構與備援設計
- [[040-01-18-guide-網路設備-網路設備盤點與文件化]] —— 用 git 管交換器設定、拓樸圖怎麼畫
- [[040-01-19-guide-網路設備-交換器汰換與遷移實務]] —— 汰換時的 STP 與聚合處理
- [[010-02-05-guide-網概-MAC位址與交換器]] —— MAC 學習與氾流的基礎原理
- [[100-01-03-guide-日誌-系統監控與告警]] —— 對 topology change 做監控告警
- [[100-01-02-guide-日誌-日誌集中與輪替]] —— 風暴時唯一能還原現場的東西
