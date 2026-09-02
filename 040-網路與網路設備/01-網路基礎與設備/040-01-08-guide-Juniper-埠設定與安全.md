---
title: "Juniper 埠設定與安全"
desc: "speed／duplex／MTU、storm-control、MAC 限制與 persistent MAC、802.1X、未用埠隔離，以及用 show interfaces extensive 讀錯誤計數"
aliases: [storm-control, interface-mac-limit, persistent-learning, dot1x, show interfaces extensive, ether-options]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-05-cmd-Juniper-JunOS-基礎操作]]", "[[040-01-06-guide-Juniper-VLAN與Trunk設定]]"]
updated: 2026-09-02
---

# Juniper 埠設定與安全

> [!abstract] 這篇你會學到
> - ★★★★★ **雙工不匹配（duplex mismatch）** —— 一邊自動協商、一邊手動鎖定就會發生，
>   症狀是「通但超級慢」，而且兩邊的 `show interfaces` 都說自己正常
> - ★★★★★ JunOS 的 **MTU 含二層標頭**，跟 Cisco 的算法差 14～18 bytes，
>   兩端設同一個數字反而不匹配
> - ★★★★★ **未使用的埠一律 `disable` 並丟進隔離 VLAN** —— 這是資安稽核必查、
>   也是最容易做卻最常被忽略的一項
> - ★★★★ `storm-control` 擋廣播風暴，以及 `action-shutdown` 之後怎麼自動恢復
> - ★★★★ `interface-mac-limit` 與 `persistent-learning`（sticky MAC）：
>   限制一個埠能學幾個 MAC，抓私接的 hub 與交換器
> - ★★★★ `show interfaces extensive` 的錯誤計數怎麼讀：
>   CRC/Align、Framing errors、Carrier transitions、Runts 各自代表什麼故障
> - ★★★ 802.1X 埠認證的架構、`guest-vlan`／`server-reject-vlan`，以及導入前要先想清楚的事
> - ★★★ SFP 光功率診斷、PoE 管理、BPDU 保護
> - 產出一份「48 埠接取交換器安全基準」與逐埠檢查表

> [!warning] 未實機驗證
> ★★★★★ 本專案沒有實體 Juniper 設備可驗證。本篇以 **EX 系列（ELS，Junos 21.4）** 為主線。
> **埠參數的階層（`ether-options` / `gigether-options` / 直接在實體介面下）、
> `storm-control`／`interface-mac-limit`／`dhcp-security`／`poe` 的支援度與語法，
> 依機型與 Junos 版本差異極大。**
> 每一節動筆前請在該機型上用 `?` 與 `help reference` 確認，
> 並全程走 [[040-01-05-cmd-Juniper-JunOS-基礎操作]] 的 `commit confirmed` 流程。

## 前置知識

- [[040-01-05-cmd-Juniper-JunOS-基礎操作]] —— `show | compare`、`commit confirmed`、`rollback`
- [[040-01-06-guide-Juniper-VLAN與Trunk設定]] —— 隔離 VLAN、access／trunk 的差別
- [[040-01-07-guide-Juniper-管理IP與遠端存取]] —— RADIUS 伺服器設定（802.1X 會用到）
- [[010-02-04-guide-網概-線材與實體層]] —— 雙絞線、光纖、SFP 的基本概念
- [[010-02-05-guide-網概-MAC位址與交換器]] —— MAC 學習與廣播風暴的原理

## 觀念說明

### 一個埠要管的四件事 ★★★★

```text
  ┌─────────────────────────────────────────────────────────────┐
  │ ① 實體參數  speed / duplex / auto-negotiation / MTU / PoE   │
  │    → 決定「線路能不能正常跑」                                │
  ├─────────────────────────────────────────────────────────────┤
  │ ② 二層歸屬  interface-mode / vlan members / native-vlan-id   │
  │    → 決定「流量進了哪個廣播網域」（06 篇）                    │
  ├─────────────────────────────────────────────────────────────┤
  │ ③ 保護機制  storm-control / mac-limit / BPDU / dot1x         │
  │    → 決定「誰可以接、接了能做什麼、出事會不會擴散」           │
  ├─────────────────────────────────────────────────────────────┤
  │ ④ 管理資訊  description / disable                            │
  │    → 決定「三年後接手的人看不看得懂」                         │
  └─────────────────────────────────────────────────────────────┘
```

★★★★ 大多數機關做完 ② 就停了。①③④ 才是把網路從「會動」變成「可維運、可稽核」的關鍵。

### 自動協商與雙工不匹配 ★★★★★

```text
      交換器 ge-0/0/10                          伺服器 eth0
   auto-negotiation: Enabled          ←→    手動鎖定 1000/full
              │                                    │
              ▼                                    ▼
   對方不參與協商，我只好                   我不送協商訊號，
   fallback 到「半雙工」                    直接用 1000/full 送
              │                                    │
              └────────► 一邊半雙工、一邊全雙工 ◄──┘
                              ★★★★★
        症狀：能通、但速度慢到不可思議（10Mbps 級）、
              大檔案傳輸會停頓、交換器端出現 Collisions 與 FCS errors
        致命點：兩邊的 show 指令看起來都「正常」，link 是 up 的
```

★★★★★ **鐵律：兩端要嘛都自動協商，要嘛都手動鎖定同樣的值。絕對不要一邊一種。**

```text
netadmin@sw> show interfaces ge-0/0/10 | match "Speed|Auto-negotiation|Link-level"
  Link-level type: Ethernet, MTU: 1514, LAN-PHY mode, Speed: 1000mbps,
  Flow control: Disabled, Auto-negotiation: Enabled, Remote fault: Online
```

| 情況 | 結果 | 星級 |
| --- | --- | --- |
| 兩端都 auto | ★★★★★ **正常，這是預設也是建議做法** | ★★★★★ |
| 兩端都手動鎖 1000/full | 正常（但換設備時容易忘記，維護成本高） | ★★★ |
| 一端 auto、一端手動 | ★★★★★ **半雙工 vs 全雙工，通但極慢** | ★★★★★ |
| 兩端手動但速率不同 | link 起不來 | ★★★ 至少容易發現 |

★★★★ **千兆（1000BASE-T）以上規格強制要求自動協商**，手動鎖定 1000M 在很多設備上根本不被接受。
現代環境「不要手動設 speed／duplex」幾乎是唯一正解，除非對接老舊設備或特殊儀器。

### JunOS 的 MTU 跟 Cisco 算的不是同一個東西 ★★★★★

```text
   一個乙太網路訊框
   ┌────────────┬──────┬─────────────────────────┬─────┐
   │ 目的+來源MAC│ Type │        Payload          │ FCS │
   │   12 bytes │ 2 B  │      1500 bytes         │ 4 B │
   └────────────┴──────┴─────────────────────────┴─────┘
    └──────── 14 bytes ────────┘

   Cisco  的 mtu 1500  ＝ 只算 Payload
   JunOS  的 mtu 1514  ＝ Payload + 14 bytes 二層標頭（不含 FCS）
   ★★★★★ 兩邊都寫 1500，實際上 JunOS 少了 14 bytes
```

| 需求 | JunOS `mtu` | Cisco `mtu` |
| --- | --- | --- |
| 標準乙太網路 | ★★★★ `1514`（預設，不用設） | `1500` |
| 帶一個 VLAN tag | `1518` | `1504`（或 `system mtu`） |
| Jumbo frame 9000 payload | ★★★★ `9014`～`9216`（依機型上限） | `9000` |

```text
netadmin@sw> show interfaces ge-0/0/10 | match MTU
  Link-level type: Ethernet, MTU: 1514, LAN-PHY mode, Speed: 1000mbps,
```

> [!danger] ★★★★★ Jumbo frame 是「整條路徑上每一個裝置都要一致」的設定
> 只改交換器不改伺服器、或路徑上有一台沒改，症狀是：
> **小封包（ping、SSH）完全正常，大封包（檔案傳輸、iSCSI、NFS、備份）卡死或極慢**。
> 而且因為 ping 預設是小封包，你會覺得「網路明明是通的」。
>
> 診斷方式（從主機端）：
> ```bash
> $ ping -M do -s 8972 10.10.30.20      # 8972 + 28 = 9000
> ping: local error: message too long, mtu=1500
> ```
> `-M do` 是「不准分片」，這樣才測得出真正的路徑 MTU。
> ★★★★ 導入 jumbo frame 前先畫出完整路徑圖，列出每一台設備與它的 MTU 設定值，
> 一台一台確認。這件事的複雜度通常被低估。

### 未使用的埠是最常被忽略的資安破口 ★★★★★

```text
   會議室牆上有 8 個網路孔，實際只用 2 個。
   剩下 6 個孔 → 交換器上 6 個埠 → 預設是 up、屬於 default VLAN

   任何人（訪客、廠商、清潔人員、社交工程攻擊者）
   帶一條網路線插上去 → 立刻進入內部網路
   ★★★★★ 不需要密碼、不需要帳號、不會有任何紀錄
```

★★★★★ **標準做法是三件事一起做**：

| 措施 | 指令 | 作用 | 星級 |
| --- | --- | --- | --- |
| 1. 停用 | `set interfaces ge-0/0/20 disable` | ★★★★★ 埠完全不通電（邏輯上），插了也沒反應 | ★★★★★ |
| 2. 丟進隔離 VLAN | `... vlan members PARKING` | ★★★★ 萬一被誤啟用，也只到一個什麼都沒有的 VLAN | ★★★★ |
| 3. 標註 | `set interfaces ge-0/0/20 description "UNUSED - disabled 2026-09-02"` | ★★★★ 讓下一個人知道這是刻意的，不是忘記設 | ★★★★ |

★★★★★ 只做第 1 項不夠：日後有人為了「借一個埠用一下」把 `disable` 拿掉，
就直接掉進 `default` VLAN 或上一個使用者的 VLAN 裡。
只做第 2 項也不夠：埠是活的，攻擊者插上去至少能做二層攻擊、送 DHCP、跑 LLDP 探測。

### 埠描述的命名規範 ★★★★

★★★★★ **沒有 description 的埠等於沒有文件。** 排錯時「這條線通到哪裡」是最常問也最查不到的問題。

建議格式（依貴單位調整，重點是**全機關一致**）：

```text
<用途類別>-<位置>-<對象>[-<備註>]

範例：
  "PC-3F-A12-王小明"                     終端使用者
  "AP-3F-會議室東側"                     無線基地台
  "PRN-3F-影印室-HP4525"                 印表機
  "SRV-機房-R12U08-web01-eth0"           伺服器
  "UPLINK-to-core-ex4300-ge-0/0/12"      ★★★★★ 上聯，寫清楚對端設備與埠
  "CAM-1F-大門-IPCAM07"                  監視器
  "UNUSED - disabled 2026-09-02"         ★★★★ 未使用
  "RESERVED - 4F 擴充預留 2027Q1"        保留
```

★★★★★ **上聯埠的 description 一定要寫「對端設備名 + 對端埠號」**。
半夜出事的時候，這一行字決定你要花 5 分鐘還是 2 小時。

```text
netadmin@sw> show interfaces descriptions
Interface       Admin  Link  Description
ge-0/0/1        up     up    PC-3F-A12-王小明
ge-0/0/2        up     up    PC-3F-A13-李小華
ge-0/0/10       up     up    AP-3F-會議室東側
ge-0/0/20       down   down  UNUSED - disabled 2026-09-02
ge-0/0/48       up     up    UPLINK-to-core-ex4300-ge-0/0/12
```

★★★★ 這一份輸出可以直接當成埠對照表的原始資料，定期匯出存檔
（見 [[040-01-18-guide-網路設備-網路設備盤點與文件化]]）。

## 環境準備與安裝

### 步驟 1：埠描述與未用埠隔離 ★★★★★

```text
netadmin@sw> configure exclusive
Entering configuration mode

[edit]
netadmin@sw# set interfaces ge-0/0/1 description "PC-3F-A12-王小明"
[edit]
netadmin@sw# set interfaces ge-0/0/2 description "PC-3F-A13-李小華"
[edit]
netadmin@sw# set interfaces ge-0/0/10 description "AP-3F-會議室東側"
[edit]
netadmin@sw# set interfaces ge-0/0/48 description "UPLINK-to-core-ex4300-ge-0/0/12"
```

未使用的埠（本例是 20～47）—— ★★★★ 用 `wildcard` 一次做完，但**做之前一定要先確認範圍**：

```text
[edit]
netadmin@sw# run show interfaces terse | match "^ge-0/0/(2[0-9]|3[0-9]|4[0-7]) " | match " up    up"

[edit]
netadmin@sw#
```

★★★★★ **沒有輸出 = 這個範圍內沒有任何埠是活的**，可以安全停用。
有輸出就代表有人在用，先查清楚是誰。

```text
[edit]
netadmin@sw# wildcard range set interfaces ge-0/0/[20-47] disable
[edit]
netadmin@sw# wildcard range set interfaces ge-0/0/[20-47] description "UNUSED - disabled 2026-09-02 CR-0601"
[edit]
netadmin@sw# wildcard range set interfaces ge-0/0/[20-47] unit 0 family ethernet-switching interface-mode access
[edit]
netadmin@sw# wildcard range set interfaces ge-0/0/[20-47] unit 0 family ethernet-switching vlan members PARKING
```

> [!warning] ★★★★★ `wildcard range` 一次動 28 個埠，`show | compare` 一定要看完
> `| no-more` 加上去，把 diff 從頭看到尾。
> 確認：(a) 範圍正確 (b) 沒有動到 `ge-0/0/48`（上聯）(c) 沒有動到還在用的埠。
> 弄錯就是一整層樓斷網 —— 好消息是 JunOS 讓你在 commit 前看得到。

```text
[edit]
netadmin@sw# show | compare | no-more
[edit interfaces]
+   ge-0/0/20 {
+       description "UNUSED - disabled 2026-09-02 CR-0601";
+       disable;
+       unit 0 {
+           family ethernet-switching {
+               interface-mode access;
+               vlan {
+                   members PARKING;
+               }
+           }
+       }
+   }
... (21～47 相同) ...

[edit]
netadmin@sw# commit confirmed 10 comment "CR-0601 埠描述與未用埠隔離"
commit confirmed will be automatically rolled back in 10 minutes unless confirmed
commit complete
```

```text
[edit]
netadmin@sw# run show interfaces descriptions | match UNUSED | count
Count: 28 lines

[edit]
netadmin@sw# run show interfaces terse | match "^ge-0/0/2[0-9] "
ge-0/0/20               down  down
ge-0/0/21               down  down
...
```

★★★★ `down down`（第一欄是管理狀態）= 確實被停用了。

```text
[edit]
netadmin@sw# commit comment "CR-0601 驗證通過"
commit complete
```

### 步驟 2：速率與雙工（★★★★ 通常不用設）

```junos
## ELS（EX4300 等）—— 依機型可能在實體介面層或 gigether-options 底下
set interfaces ge-0/0/30 speed 100m
set interfaces ge-0/0/30 link-mode full-duplex
set interfaces ge-0/0/30 gigether-options no-auto-negotiation
```

> [!info]- 非 ELS（EX2200／EX3300／EX4200 等）
> ```junos
> set interfaces ge-0/0/30 ether-options speed 100m
> set interfaces ge-0/0/30 ether-options link-mode full-duplex
> set interfaces ge-0/0/30 ether-options no-auto-negotiation
> ```
> ★★★★ 階層是 `ether-options`（非 ELS）vs `gigether-options`（部分 ELS 機種）。
> **一定要用 `set interfaces ge-0/0/30 ?` 確認你的機型是哪一種。**

> [!danger] ★★★★★ 手動鎖定 speed／duplex 之前先想清楚三件事
> 1. **對端也要一起改。** 只改一端就是製造 duplex mismatch。
> 2. **改完會 link flap。** 這個埠會斷線幾秒，接的是伺服器就會影響服務。
> 3. **要留紀錄。** description 或 `annotate` 寫明「為什麼手動鎖」，
>    否則三年後換設備的人會照抄這個設定到一個根本不需要的埠上。
>
> ★★★★★ **現代環境的建議是：不要手動設。** 遇到協商問題優先換線、換 SFP、
> 換埠、更新對端網卡驅動，最後才考慮手動鎖定。

### 步驟 3：MTU（★★★ 只在需要 jumbo frame 時設）

```junos
## 伺服器網段需要 jumbo frame（例如 iSCSI／NFS／備份網路）
set interfaces ge-0/0/40 mtu 9192
set interfaces ge-0/0/41 mtu 9192
set interfaces ge-0/0/48 mtu 9192
```

★★★★★ **路徑上每一個埠都要設**，包含上聯 trunk（本例的 `ge-0/0/48`）。
漏掉一個，那條路上的大封包就會被丟。

```text
[edit]
netadmin@sw# run show interfaces ge-0/0/40 | match MTU
  Link-level type: Ethernet, MTU: 9192, LAN-PHY mode, Speed: 1000mbps,
```

從伺服器端驗證（★★★★★ 這才是真正的證據）：

```bash
$ ping -M do -s 8972 -c 3 10.10.30.21
PING 10.10.30.21 (10.10.30.21) 8972(9000) bytes of data.
8980 bytes from 10.10.30.21: icmp_seq=1 ttl=64 time=0.412 ms
8980 bytes from 10.10.30.21: icmp_seq=2 ttl=64 time=0.398 ms
8980 bytes from 10.10.30.21: icmp_seq=3 ttl=64 time=0.401 ms

--- 10.10.30.21 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
```

## 基礎設定

實體參數與埠管理就緒之後，接下來是三項「出事時把災情關在一個埠裡」的保護機制。

### 步驟 4：storm-control 廣播風暴抑制 ★★★★

廣播風暴的成因通常是**環路**（有人把兩個網路孔用一條線接起來）或**故障網卡**。
沒有 storm-control 的話，一台交換器的環路可以在幾秒內癱瘓整個廣播網域。

```junos
## ELS
set forwarding-options storm-control-profiles SC-ACCESS all bandwidth-percentage 3
set forwarding-options storm-control-profiles SC-ACCESS all no-unknown-unicast
set interfaces ge-0/0/1 unit 0 family ethernet-switching storm-control SC-ACCESS
```

| 設定 | 意義 | 星級 |
| --- | --- | --- |
| `all bandwidth-percentage 3` | ★★★★ BUM 流量（廣播／未知單播／多播）合計不得超過埠速的 3% | ★★★★ |
| `no-unknown-unicast` | ★★★★ **把未知單播排除在限制之外**（避免正常的 MAC 老化氾洪被誤殺） | ★★★★ |
| `no-multicast` | 把多播排除（有跑 IPTV／多播應用時需要） | ★★★ |
| `no-broadcast` | 把廣播排除（★★ 幾乎沒有理由這樣做） | ★★ |
| `action-shutdown` | ★★★★★ 超標就把埠關掉（比單純丟棄更徹底，但也更容易誤傷） | ★★★★★ |

```junos
## 加上 action-shutdown 與自動恢復
set forwarding-options storm-control-profiles SC-ACCESS action-shutdown
set interfaces ge-0/0/1 unit 0 family ethernet-switching recovery-timeout 300
```

> [!warning] ★★★★★ `action-shutdown` 沒有搭配 `recovery-timeout` 就是「人工才能救」
> 埠被關掉之後**不會自己回來**，要有人手動 `clear ethernet-switching recovery-timeout`
> 或改設定。半夜一台印表機網卡發瘋觸發 shutdown，整層樓的人早上上班發現網路不通，
> 而你要跑一趟或遠端一個一個埠去解。
>
> ★★★★ 導入建議的順序：
> 1. 先**只設 bandwidth-percentage、不加 action-shutdown**，跑一個月
> 2. `show interfaces ... extensive` 觀察有沒有埠一直觸發（那代表門檻太低）
> 3. 門檻調到合適值之後，再加 `action-shutdown` + `recovery-timeout 300`
> 4. 上聯 trunk **不要**套 storm-control（正常流量本來就大，誤殺代價極高）

> [!info]- 非 ELS 的 storm-control
> ```junos
> set ethernet-switching-options storm-control interface all level 3
> set ethernet-switching-options storm-control interface all no-unknown-unicast
> set ethernet-switching-options storm-control interface ge-0/0/48.0 no-broadcast no-multicast no-unknown-unicast
> ```
> ★★★ 非 ELS 用 `level`（百分比）而不是 profile。
> 上聯埠可以用 `no-*` 三個全下等於實質關閉。
> 自動恢復用 `set protocols layer2-control port-error-disable disable-timeout 300`。

```text
netadmin@sw> show log messages | match "storm|SC_" | last 5
Sep  2 11:04:22  sw l2ald[3212]: L2ALD_ST_CTL_IN_EFFECT: ge-0/0/17.0: storm control in effect on the port
Sep  2 11:09:22  sw l2ald[3212]: L2ALD_ST_CTL_DISABLED: ge-0/0/17.0: storm control disabled the port
```

★★★★★ 看到這兩行就代表 `ge-0/0/17` 那邊有環路或故障設備，**去現場拔線比在 CLI 想辦法快**。

### 步驟 5：MAC 數量限制與 sticky MAC ★★★★

一個接 PC 的埠正常只會學到 1～2 個 MAC。學到 20 個代表**後面私接了 hub 或交換器**。

```junos
## ELS
set switch-options interface ge-0/0/1.0 interface-mac-limit 3
set switch-options interface ge-0/0/1.0 interface-mac-limit packet-action drop
```

| `packet-action` | 行為 | 星級 |
| --- | --- | --- |
| `drop` | ★★★★ 超過的 MAC 學不進來，封包丟棄，**埠還活著** | ★★★★ |
| `drop-and-log` | 同上 + 寫日誌 | ★★★★★ 建議用這個 |
| `log` | 只記錄不阻擋（觀察期用） | ★★★★ |
| `shutdown` | ★★★★★ 直接關埠（要配 recovery-timeout） | ★★★★★ |
| `none` | 不做任何事 | ★ |

★★★★ **建議值**：一般辦公 PC 埠 `3`（PC + 可能的虛擬機／IP 話機）、
會議室 `5`、AP 埠 `不要設`（AP 後面掛的無線用戶端 MAC 全部會學到這個埠）、
trunk 上聯 **絕對不要設**。

**persistent MAC（sticky MAC）** —— 把學到的 MAC 記起來，重開機也不忘：

```junos
set switch-options interface ge-0/0/1.0 persistent-learning
```

```text
netadmin@sw> show ethernet-switching table interface ge-0/0/1.0
MAC flags (S - static MAC, D - dynamic MAC, L - locally learned, P - Persistent static
           SE - statistics enabled, NM - non configured MAC, R - remote PE MAC, O - ovsdb MAC)

Ethernet switching table : 1 entries, 1 learned
Routing instance : default-switch
   Vlan                MAC                 MAC      Logical                SVLBNH/  Active
   name                address             flags    interface              VENH Index  source
   OFFICE              b4:0c:25:1a:3f:e2   DLP      ge-0/0/1.0
```

★★★★ `MAC flags` 出現 **`P`** 就代表這個 MAC 已經被記成 persistent。

換一台電腦時要先清掉舊的：

```text
netadmin@sw> clear ethernet-switching table persistent-learning interface ge-0/0/1.0
```

> [!danger] ★★★★★ persistent MAC 的維運成本很高，導入前務必評估
> 好處是「換了電腦就不能上網」，聽起來很安全。實際上：
> - 使用者換筆電、換網卡、修電腦回來 → 網路不通 → 打電話給你
> - 你要記得跑 `clear ethernet-switching table persistent-learning interface X`
> - 一個 500 人的機關，每天都會有幾件
>
> ★★★★ **建議只用在真正需要的地方**：機房伺服器埠、監視器埠、
> 門禁與工控設備埠 —— 這些設備本來就不會亂換。
> 一般辦公室埠用 `interface-mac-limit` + `drop-and-log` 就夠了，
> 想做真正的埠級身分管制請走 802.1X。

> [!info]- 非 ELS 的 MAC 限制
> ```junos
> set ethernet-switching-options secure-access-port interface ge-0/0/1.0 mac-limit 3 action drop
> set ethernet-switching-options secure-access-port interface ge-0/0/1.0 persistent-learning
> ```
> ★★★ 階層在 `ethernet-switching-options secure-access-port` 底下。

> [!warning] ★★★★ 未實機驗證
> `interface-mac-limit`、`persistent-learning`、`mac-move-limit` 的可用選項與行為
> **依機型與 Junos 版本差異很大**（部分入門機種功能受限）。
> 導入前用 `set switch-options interface ge-0/0/1.0 ?` 確認，
> 並在測試埠上實際插拔驗證行為符合預期。

### 步驟 6：BPDU 保護 ★★★★

接終端的埠**不應該**收到 STP 的 BPDU。收到就代表有人接了一台交換器上去
（可能是無意的，也可能是攻擊者想搶 root bridge）。

```junos
set protocols rstp interface ge-0/0/1 edge
set protocols rstp interface ge-0/0/1 no-root-port
set protocols rstp bpdu-block-on-edge
set protocols layer2-control bpdu-block disable-timeout 300
```

| 設定 | 意義 | 星級 |
| --- | --- | --- |
| `edge` | ★★★★ 宣告這是終端埠，link up 後立刻進 forwarding（等同 Cisco portfast） | ★★★★ |
| `no-root-port` | ★★★★ 這個埠永遠不能成為 root port（等同 Cisco root guard） | ★★★★ |
| `bpdu-block-on-edge` | ★★★★★ edge 埠收到 BPDU 就把埠停掉（等同 Cisco BPDU guard） | ★★★★★ |
| `bpdu-block disable-timeout 300` | ★★★★ 停掉之後 300 秒自動恢復 | ★★★★ |

```text
netadmin@sw> show log messages | match BPDU | last 3
Sep  2 13:22:07  sw eswd[3341]: ESWD_BPDU_BLOCK_PORT_DISABLED: ge-0/0/14: BPDU Block: Port disabled
```

★★★★★ 這一行代表 `ge-0/0/14` 收到了 BPDU 並被保護機制關掉 ——
**去現場看那個孔接了什麼**。STP 的完整說明見 [[040-01-16-guide-網路設備-鏈路聚合與STP]]。

> [!warning] ★★★ 未實機驗證
> `bpdu-block-on-edge` 與 `layer2-control bpdu-block` 的階層與選項名稱依版本略有差異。
> 用 `set protocols rstp ?` 與 `set protocols layer2-control ?` 確認。

## 進階設定與調校

### 用 `show interfaces extensive` 讀懂錯誤計數 ★★★★★

★★★★★ **這是網路排錯最重要的一個指令**。「線路有問題」不是感覺，是這裡的數字。

```text
netadmin@sw> show interfaces ge-0/0/10 extensive
Physical interface: ge-0/0/10, Enabled, Physical link is Up
  Interface index: 651, SNMP ifIndex: 512, Generation: 154
  Link-level type: Ethernet, MTU: 1514, LAN-PHY mode, Speed: 1000mbps,
  BPDU Error: None, Loop Detect PDU Error: None, Ethernet-Switching Error: None,
  MAC-REWRITE Error: None, Loopback: Disabled, Source filtering: Disabled,
  Flow control: Disabled, Auto-negotiation: Enabled, Remote fault: Online
  Device flags   : Present Running
  Interface flags: SNMP-Traps Internal: 0x4000
  CoS queues     : 12 supported, 12 maximum usable queues
  Current address: 2c:6b:f5:11:0a:8a, Hardware address: 2c:6b:f5:11:0a:8a
  Last flapped   : 2026-09-01 09:14:22 CST (1d 08:12:41 ago)
  Statistics last cleared: 2026-08-25 10:00:00 CST (8d 07:12:41 ago)
  Traffic statistics:
   Input  bytes  :           8341229184                 4128 bps
   Output bytes  :           2214887401                 1872 bps
   Input  packets:             18229144                    6 pps
   Output packets:              9114221                    3 pps
  Input errors:
    Errors: 0, Drops: 0, Framing errors: 1842, Runts: 0, Policed discards: 0,
    L3 incompletes: 0, L2 channel errors: 0, L2 mismatch timeouts: 0,
    FIFO errors: 0, Resource errors: 0
  Output errors:
    Carrier transitions: 14, Errors: 0, Drops: 0, Collisions: 0, Aged packets: 0,
    FIFO errors: 0, HS link CRC errors: 0, MTU errors: 0, Resource errors: 0
  MAC statistics:                      Receive         Transmit
    Total octets                    8341229184       2214887401
    Total packets                     18229144          9114221
    Unicast packets                   17998221          9001442
    Broadcast packets                   180422            88221
    Multicast packets                    50501            24558
    CRC/Align errors                      1842                0
    FIFO errors                              0                0
    MAC control frames                       0                0
    MAC pause frames                         0                0
    Oversized frames                         0
    Jabber frames                            0
    Fragment frames                          0
```

★★★★★ **計數器判讀對照表**（背下來，這是現場最有用的一頁）：

| 計數器 | 不為零代表 | 該做什麼 | 星級 |
| --- | --- | --- | --- |
| `CRC/Align errors` / `Framing errors` | ★★★★★ **實體層有問題**：線材劣化、接頭氧化、彎折過度、超長、電磁干擾、SFP 故障 | 換線 → 換埠 → 換 SFP。這是最常見也最明確的實體故障訊號 | ★★★★★ |
| `Carrier transitions` 持續增加 | ★★★★★ **link 一直起起落落（flapping）** —— 線鬆、接頭沒卡好、對端設備重開、省電模式 | `Last flapped` 對照時間；先重插線材與接頭 | ★★★★★ |
| `Collisions` | ★★★★★ **雙工不匹配**（全雙工環境不該有碰撞） | 檢查兩端 auto-negotiation 設定 | ★★★★★ |
| `Runts` | 訊框太短（< 64 bytes），通常伴隨碰撞或線材問題 | 同 CRC | ★★★★ |
| `Oversized frames` / `Jabber frames` | 對端網卡故障，或 MTU 不匹配 | 檢查對端網卡、MTU 設定 | ★★★★ |
| `Fragment frames` | 太短 + CRC 錯，典型的實體層劣化 | 換線 | ★★★★ |
| `Input Drops` | 輸入緩衝滿了，通常是流量超過處理能力 | 看流量統計，考慮升速或聚合 | ★★★ |
| `Output Drops` | 輸出佇列滿了（壅塞） | 該埠頻寬不足，考慮 QoS 或升速 | ★★★ |
| `MTU errors` | ★★★★ 收到超過本埠 MTU 的訊框 | 兩端 MTU 不一致，見前面的 MTU 章節 | ★★★★ |
| `MAC pause frames` | 對端在要求流量控制 | 對端壅塞或網卡設定；★★★ 交換器上通常建議關掉 flow control | ★★★ |
| `Policed discards` | 被 policer（例如 storm-control）丟掉 | 檢查 storm-control 門檻是否太低 | ★★★★ |
| `L3 incompletes` | 收到無法解析的三層標頭 | 通常是異常流量或攻擊 | ★★★ |

> [!tip] ★★★★★ 計數器是「累積值」，要看的是「增加速度」
> `CRC/Align errors: 1842` 這個數字本身沒有意義 —— 它可能是三年前某次插拔留下的。
> 正確的判讀方式：
> ```text
> netadmin@sw> clear interfaces statistics ge-0/0/10
> ... 等 10 分鐘 ...
> netadmin@sw> show interfaces ge-0/0/10 extensive | match "CRC|Framing|Carrier|Statistics last"
>   Statistics last cleared: 2026-09-02 14:00:00 CST (00:10:04 ago)
>     Errors: 0, Drops: 0, Framing errors: 0, Runts: 0, Policed discards: 0,
>     Carrier transitions: 0, Errors: 0, Drops: 0, Collisions: 0, Aged packets: 0,
>     CRC/Align errors                         0                0
> ```
> **清掉之後十分鐘內還在漲 = 現在進行式的故障。**
> `Statistics last cleared` 那一行就是為了讓你知道「這些數字累積了多久」。

★★★★ 一次掃全機所有埠的錯誤（★★★★★ 每月維護必做）：

```text
netadmin@sw> show interfaces extensive | match "Physical interface|CRC/Align" | no-more
Physical interface: ge-0/0/0, Enabled, Physical link is Up
    CRC/Align errors                         0                0
Physical interface: ge-0/0/1, Enabled, Physical link is Up
    CRC/Align errors                         0                0
Physical interface: ge-0/0/10, Enabled, Physical link is Up
    CRC/Align errors                      1842                0
...
```

### SFP 光模組診斷 ★★★★

光纖鏈路的錯誤有很大比例來自光功率不足（髒污、彎折、模組老化）。

```text
netadmin@sw> show interfaces diagnostics optics xe-0/1/0
Physical interface: xe-0/1/0
    Laser bias current                        :  6.234 mA
    Laser output power                        :  0.5150 mW / -2.88 dBm
    Module temperature                        :  42 degrees C / 108 degrees F
    Module voltage                            :  3.3120 V
    Receiver signal average optical power     :  0.3421 mW / -4.66 dBm
    Laser bias current high alarm             :  Off
    Laser bias current low alarm              :  Off
    Laser output power high alarm             :  Off
    Laser output power low alarm              :  Off
    Module temperature high alarm             :  Off
    Receiver signal power high alarm          :  Off
    Receiver signal power low alarm           :  Off
    Receiver signal power low warning         :  Off
    Laser rx power low alarm threshold        :  0.0158 mW / -18.01 dBm
    Laser rx power low warning threshold      :  0.0398 mW / -14.00 dBm
```

★★★★★ 判讀重點：

| 項目 | 健康值（參考） | 異常代表 |
| --- | --- | --- |
| `Receiver signal average optical power` | ★★★★★ 要**明顯高於** low warning threshold | 接近或低於門檻 = 光衰太大，清潔接頭／檢查彎折／換跳線 |
| `Laser output power` | 在模組規格範圍內 | 太低＝模組老化 |
| `Module temperature` | 一般 < 70°C | 太高＝機櫃散熱不良（見 [[040-02-02-guide-機房-空調系統與溫溼度監控]]） |
| 各種 `alarm` / `warning` | 全部 `Off` | 有 `On` 就是明確故障 |

★★★★ **接收光功率是 `-40 dBm` 或顯示極低值** = 對端沒有光送過來（對端埠關了、光纖斷了、TX/RX 接反）。

> [!warning] ★★★ 未實機驗證
> `show interfaces diagnostics optics` 只對支援 DOM（Digital Optical Monitoring）的模組有效。
> 非原廠模組可能回報不完整或不正確的數值。
> Juniper 對第三方光模組不提供支援，故障排除時 TAC 會要求換回原廠模組測試。

### PoE 管理 ★★★

```junos
set poe interface ge-0/0/10 maximum-power 15.4
set poe interface ge-0/0/10 priority high
set poe interface ge-0/0/20 disable
set poe management class
```

```text
netadmin@sw> show poe controller
Controller  Maximum   Power        Guard    Management  Status      Lldp
index       power     consumption  band                             Priority
0           370.00W   48.30W       0W       Class       AT_MODE     Disabled

netadmin@sw> show poe interface
Interface  Admin   Oper   Max        Priority  Power      Class  Power
           status  status power                consumption
ge-0/0/10  Enabled ON     15.4W      High      12.10W     3      Enabled
ge-0/0/11  Enabled ON     15.4W      Low       6.20W      2      Enabled
ge-0/0/20  Disabled OFF   0.0W       Low       0.00W      not-applicable
```

| 實務重點 | 說明 | 星級 |
| --- | --- | --- |
| 不需要 PoE 的埠一律 `disable` | ★★★★ 省電源預算，也避免誤供電損壞設備 | ★★★★ |
| `priority` 分級 | ★★★★★ 電源不足時，低優先的埠先被切斷。**AP 與監視器設 high，其他 low** | ★★★★ |
| 總功率預算要算 | ★★★★★ 24 埠 PoE+ 全滿 = 720W，但電源可能只有 370W | ★★★★★ |
| 換 AP 前先看 `Class` | Class 4（PoE+ 30W）插在只支援 802.3af（15.4W）的埠上會起不來 | ★★★★ |

★★★★ PoE 供電規劃與機櫃電力的關係見 [[040-02-04-guide-機房-電力系統與配電]]。

### 802.1X 埠認證 ★★★

802.1X 是「插上網線也要先通過認證才能用網路」，是埠級身分管制的正解。

```text
   PC（Supplicant）──── EX 交換器（Authenticator）──── RADIUS（Authentication Server）
        │                        │                            │
        │  ①EAPOL-Start          │                            │
        │───────────────────────▶│                            │
        │  ②EAP-Request Identity │                            │
        │◀───────────────────────│                            │
        │  ③EAP-Response         │  ④RADIUS Access-Request    │
        │───────────────────────▶│───────────────────────────▶│
        │                        │  ⑤Access-Accept + VLAN     │
        │  ⑥EAP-Success          │◀───────────────────────────│
        │◀───────────────────────│                            │
        │        ★★★★★ 通過之後埠才開始轉發，並套用 RADIUS 指定的 VLAN
```

```junos
## RADIUS 伺服器（access 階層，與 system 階層的登入用 RADIUS 是不同的設定）
set access radius-server 10.99.0.40 secret "請改成你們的共用密鑰"
set access radius-server 10.99.0.40 source-address 10.99.0.11
set access radius-server 10.99.0.40 timeout 5
set access radius-server 10.99.0.40 retry 3
set access profile DOT1X-PROFILE authentication-order radius
set access profile DOT1X-PROFILE radius authentication-server 10.99.0.40

## 802.1X authenticator
set protocols dot1x authenticator authentication-profile-name DOT1X-PROFILE
set protocols dot1x authenticator interface ge-0/0/1.0 supplicant single-secure
set protocols dot1x authenticator interface ge-0/0/1.0 retries 3
set protocols dot1x authenticator interface ge-0/0/1.0 transmit-period 30
set protocols dot1x authenticator interface ge-0/0/1.0 supplicant-timeout 30
set protocols dot1x authenticator interface ge-0/0/1.0 mac-radius
set protocols dot1x authenticator interface ge-0/0/1.0 guest-vlan GUEST
set protocols dot1x authenticator interface ge-0/0/1.0 server-reject-vlan QUARANTINE
```

| 設定 | 意義 | 星級 |
| --- | --- | --- |
| `supplicant single` | 第一個認證通過的裝置就開埠（後面的沾光） | ★★ |
| `supplicant single-secure` | ★★★★ 只允許**一個**已認證的 MAC | ★★★★ |
| `supplicant multiple` | ★★★★ 每個 MAC 各自認證（話機 + PC 的情境要用這個） | ★★★★ |
| `mac-radius` | ★★★★★ 不支援 802.1X 的設備（印表機、監視器）改用 MAC 位址當帳密向 RADIUS 認證 | ★★★★★ |
| `guest-vlan GUEST` | ★★★★ 完全沒回應 EAPOL 的裝置丟到訪客 VLAN | ★★★★ |
| `server-reject-vlan QUARANTINE` | ★★★★ 認證失敗的丟到隔離 VLAN（而不是完全斷網） | ★★★★ |
| `transmit-period` / `retries` / `supplicant-timeout` | 重試與逾時參數 | ★★★ |

```text
netadmin@sw> show dot1x interface ge-0/0/1.0
802.1X Information:
Interface       Role           State          MAC address        User
ge-0/0/1.0      Authenticator  Authenticated  B4:0C:25:1A:3F:E2  wang@example.gov.tw

netadmin@sw> show dot1x interface ge-0/0/1.0 detail
ge-0/0/1.0
  Role: Authenticator
  Administrative state: Auto
  Supplicant mode: Single-secure
  Number of retries: 3
  Quiet period: 60 seconds
  Transmit period: 30 seconds
  Mac Radius: Enabled
  Guest VLAN member: GUEST
  Server reject VLAN: QUARANTINE
  Number of connected supplicants: 1
    Supplicant: wang@example.gov.tw, B4:0C:25:1A:3F:E2
      Operational state: Authenticated
      Authentication method: Radius
      Authenticated VLAN: OFFICE
```

> [!danger] ★★★★★ 802.1X 是資安效益很高、但導入代價也很高的專案，不要只憑一篇教學就上線
> 導入前必須先想清楚的六件事：
> 1. ★★★★★ **不支援 802.1X 的設備怎麼辦**：印表機、監視器、IP 話機、門禁、電梯、
>    冷氣控制器、老舊儀器 —— 全部要走 `mac-radius`，而 MAC 清單要人工維護
> 2. ★★★★★ **RADIUS 伺服器掛掉怎麼辦**：全機關都上不了網。必須做冗餘，
>    並設計 fail-open 或 fail-to-VLAN 的策略
> 3. ★★★★ **憑證怎麼發**：EAP-TLS 要每台電腦一張憑證，
>    見 [[090-01-00-idx-PKI-憑證與PKI]]（若走 PEAP/MSCHAPv2 則綁 AD 帳號）
> 4. ★★★★ **訪客與廠商怎麼辦**：guest-vlan 的設計與存取範圍
> 5. ★★★★ **使用者教育與客服量**：導入初期客服電話會暴增
> 6. ★★★★ **分階段導入**：先在一層樓、一個部門試辦；
>    先用 `guest-vlan` 讓失敗的人還能上網（監控模式），確認 MAC 清單完整後才收緊
>
> ★★★ 沒有這些配套的話，`interface-mac-limit` + 未用埠停用 + 實體管制
> 已經可以擋掉大部分的隨機接入風險，成本低很多。

> [!warning] ★★★★ 未實機驗證
> 802.1X 的參數名稱與行為（尤其 `supplicant` 模式、`guest-vlan` 與語音 VLAN 的互動、
> 動態 VLAN 指派需要的 RADIUS 屬性）依 Junos 版本差異很大。
> 導入前務必在測試環境完整驗證，並與 RADIUS 端（FreeRADIUS／NPS／ISE）的設定一起測。

### DHCP snooping、動態 ARP 檢查與 IP source guard ★★★

```junos
## ELS
set vlans OFFICE forwarding-options dhcp-security
set vlans OFFICE forwarding-options dhcp-security arp-inspection
set vlans OFFICE forwarding-options dhcp-security ip-source-guard
set vlans OFFICE forwarding-options dhcp-security group TRUSTED overrides trusted
set vlans OFFICE forwarding-options dhcp-security group TRUSTED interface ge-0/0/48.0
```

| 功能 | 擋什麼 | 星級 |
| --- | --- | --- |
| `dhcp-security`（DHCP snooping） | ★★★★★ **私接的 DHCP 伺服器**（無線分享器插反是最常見的事故） | ★★★★★ |
| `arp-inspection` | ★★★★ ARP 欺騙／中間人攻擊 | ★★★★ |
| `ip-source-guard` | ★★★★ 偽造來源 IP | ★★★★ |
| `group TRUSTED ... interface` | ★★★★★ **上聯 trunk 必須標為 trusted**，否則合法的 DHCP 回應也會被擋 | ★★★★★ |

```text
netadmin@sw> show dhcp-security binding
IP address        MAC address       Vlan     Expires   State       Interface
10.10.10.37       b4:0c:25:1a:3f:e2 OFFICE   84122     BOUND       ge-0/0/1.0
10.10.10.41       a0:ce:c8:33:71:04 OFFICE   83901     BOUND       ge-0/0/2.0
```

> [!danger] ★★★★★ 忘記把上聯標為 trusted = 整層樓拿不到 IP
> DHCP snooping 的預設是「所有埠都不信任」，只有標為 trusted 的埠可以送出
> DHCP OFFER／ACK。忘記標上聯 trunk 的話，合法 DHCP 伺服器的回應會被交換器丟掉，
> **使用者全部拿不到 IP，而 DHCP 伺服器那邊看起來一切正常**。
> ★★★★★ 這個設定一律 `commit confirmed`，並且在**一個 VLAN、一層樓**試辦後才推廣。

> [!info]- 非 ELS 的對應設定
> ```junos
> set ethernet-switching-options secure-access-port vlan office examine-dhcp
> set ethernet-switching-options secure-access-port vlan office arp-inspection
> set ethernet-switching-options secure-access-port vlan office ip-source-guard
> set ethernet-switching-options secure-access-port interface ge-0/0/48.0 dhcp-trusted
> ```
> 綁定表用 `show dhcp snooping binding`。

> [!warning] ★★★★ 未實機驗證
> `dhcp-security` 的階層（`vlans <name> forwarding-options` vs 全域 `forwarding-options`）、
> trusted 介面的指定方式在不同 Junos 版本有變動。
> 用 `set vlans OFFICE forwarding-options ?` 確認，並在測試 VLAN 上實測 DHCP 取得流程。

> [!info]- Cisco IOS 對照（簡表，完整內容見 [[040-01-13-guide-Cisco-埠設定與安全]]）
> | 目的 | JunOS（ELS） | Cisco IOS |
> | --- | --- | --- |
> | 埠描述 | `set interfaces ge-0/0/1 description "..."` | `description ...` |
> | 停用埠 | `set interfaces ge-0/0/1 disable` | `shutdown` |
> | 速率／雙工 | `set int ge-0/0/1 speed 100m` + `link-mode full-duplex` | `speed 100` + `duplex full` |
> | MTU | ★★★★★ `mtu 9192`（**含二層標頭**） | `mtu 9000`（只算 payload） |
> | 廣播風暴抑制 | `forwarding-options storm-control-profiles` + 套到埠 | `storm-control broadcast level 3.00` |
> | 超標關埠 | `action-shutdown` + `recovery-timeout` | `storm-control action shutdown` + `errdisable recovery` |
> | MAC 數量限制 | `switch-options interface X interface-mac-limit 3` | `switchport port-security maximum 3` |
> | sticky MAC | `switch-options interface X persistent-learning` | `switchport port-security mac-address sticky` |
> | portfast | `set protocols rstp interface ge-0/0/1 edge` | `spanning-tree portfast` |
> | BPDU guard | `set protocols rstp bpdu-block-on-edge` | `spanning-tree bpduguard enable` |
> | root guard | `set protocols rstp interface X no-root-port` | `spanning-tree guard root` |
> | DHCP snooping | `set vlans X forwarding-options dhcp-security` | `ip dhcp snooping vlan X` |
> | 802.1X | `set protocols dot1x authenticator interface X ...` | `dot1x port-control auto` |
> | 看錯誤計數 | ★★★★★ `show interfaces X extensive` | `show interfaces X` / `show interfaces counters errors` |
> | 看光模組 | `show interfaces diagnostics optics X` | `show interfaces transceiver detail` |
> | PoE | `show poe interface` / `set poe interface X priority high` | `show power inline` / `power inline` |
>
> 完整對照見 [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]]。

## 完整實戰範例

**情境**：一台 EX2300-48T 接取交換器（`acc-3f-ex2300`）已經完成 VLAN 與管理設定
（06、07 篇），現在要套用「接取層安全基準」。目標：

- 1～16 埠：辦公 PC（OFFICE VLAN）
- 17～18 埠：無線 AP（trunk，帶 OFFICE + GUEST）
- 19 埠：印表機
- 20～47 埠：未使用 → 停用 + 隔離
- 48 埠：上聯 trunk
- 全部：描述、storm-control、MAC 限制、BPDU 保護

### 步驟 1：留下動手前的完整基準線 ★★★★★

```text
netadmin@acc-3f-ex2300> set cli screen-length 0
netadmin@acc-3f-ex2300> set cli timestamp

netadmin@acc-3f-ex2300> show configuration | display set | save /var/tmp/before-CR0601.set
Wrote 156 lines of output to '/var/tmp/before-CR0601.set'

netadmin@acc-3f-ex2300> show interfaces descriptions | save /var/tmp/before-desc.txt
netadmin@acc-3f-ex2300> show interfaces terse | save /var/tmp/before-terse.txt
netadmin@acc-3f-ex2300> show ethernet-switching table | save /var/tmp/before-mac.txt

netadmin@acc-3f-ex2300> file copy /var/tmp/before-CR0601.set scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/
Password for netadmin@10.99.0.5:

netadmin@acc-3f-ex2300> request system configuration rescue save
```

### 步驟 2：★★★★★ 先確認哪些埠真的沒在用

**這一步不能跳。** 「看起來沒在用」跟「真的沒在用」是兩回事 ——
使用者可能只是今天請假、印表機可能週末才開。

```text
netadmin@acc-3f-ex2300> show ethernet-switching table | match "ge-0/0/" | count
Count: 19 lines

netadmin@acc-3f-ex2300> show interfaces terse | match "^ge-0/0/[0-9]+ " | match "up    up"
ge-0/0/1                up    up
ge-0/0/2                up    up
...
ge-0/0/17               up    up
ge-0/0/18               up    up
ge-0/0/19               up    up
ge-0/0/48               up    up
```

★★★★★ **更嚴謹的做法：看每個埠「最後一次有 link」是什麼時候**：

```text
netadmin@acc-3f-ex2300> show interfaces extensive | match "Physical interface|Last flapped" | no-more
Physical interface: ge-0/0/20, Enabled, Physical link is Down
  Last flapped   : Never
Physical interface: ge-0/0/21, Enabled, Physical link is Down
  Last flapped   : Never
Physical interface: ge-0/0/33, Enabled, Physical link is Down
  Last flapped   : 2026-06-14 09:22:41 CST (80d 05:41:12 ago)
```

★★★★★ `Last flapped: Never` = 這台設備上線以來**從來沒有東西插過** → 安全可停用。
★★★★ `80 天前有 link` → 要查清楚。可能是季報表才用的臨時工作站，
停用之後三個月後才有人來抱怨。**這種埠先發公告、標為 RESERVED、不要直接停。**

### 步驟 3：埠描述 ★★★★

```text
netadmin@acc-3f-ex2300> configure exclusive
Entering configuration mode

[edit]
netadmin@acc-3f-ex2300# show | compare

[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/1 description "PC-3F-A12-王小明"
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/2 description "PC-3F-A13-李小華"
... (3～16 略) ...
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/17 description "AP-3F-東側-JNP-AP01"
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/18 description "AP-3F-西側-JNP-AP02"
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/19 description "PRN-3F-影印室-HP4525"
[edit]
netadmin@acc-3f-ex2300# set interfaces ge-0/0/48 description "UPLINK-to-core-ex4300-ge-0/0/12"
```

### 步驟 4：未用埠停用與隔離 ★★★★★

```text
[edit]
netadmin@acc-3f-ex2300# wildcard range set interfaces ge-0/0/[20-47] description "UNUSED - disabled 2026-09-02 CR-0601"
[edit]
netadmin@acc-3f-ex2300# wildcard range set interfaces ge-0/0/[20-47] disable
[edit]
netadmin@acc-3f-ex2300# wildcard range set interfaces ge-0/0/[20-47] unit 0 family ethernet-switching interface-mode access
[edit]
netadmin@acc-3f-ex2300# wildcard range set interfaces ge-0/0/[20-47] unit 0 family ethernet-switching vlan members PARKING
```

★★★★ 順便把 PoE 也關掉（省電源預算）：

```text
[edit]
netadmin@acc-3f-ex2300# wildcard range set poe interface ge-0/0/[20-47] disable
```

### 步驟 5：storm-control ★★★★

```text
[edit]
netadmin@acc-3f-ex2300# set forwarding-options storm-control-profiles SC-ACCESS all bandwidth-percentage 3
[edit]
netadmin@acc-3f-ex2300# set forwarding-options storm-control-profiles SC-ACCESS all no-unknown-unicast
[edit]
netadmin@acc-3f-ex2300# wildcard range set interfaces ge-0/0/[1-19] unit 0 family ethernet-switching storm-control SC-ACCESS
```

★★★★★ **注意：`ge-0/0/48`（上聯）沒有套。** 上聯的正常流量本來就大，
套上去很容易誤殺，而且上聯出問題影響範圍是整台交換器。

★★★★ 第一階段**不加 `action-shutdown`**，先觀察一個月。

### 步驟 6：MAC 限制與 BPDU 保護 ★★★★

```text
## PC 埠：最多 3 個 MAC，超過就丟並記錄
[edit]
netadmin@acc-3f-ex2300# wildcard range set switch-options interface ge-0/0/[1-16].0 interface-mac-limit 3
[edit]
netadmin@acc-3f-ex2300# wildcard range set switch-options interface ge-0/0/[1-16].0 interface-mac-limit packet-action drop-and-log

## 印表機埠：只准 1 個
[edit]
netadmin@acc-3f-ex2300# set switch-options interface ge-0/0/19.0 interface-mac-limit 1
[edit]
netadmin@acc-3f-ex2300# set switch-options interface ge-0/0/19.0 interface-mac-limit packet-action drop-and-log

## ★★★★★ AP 埠（17、18）與上聯（48）不設 MAC 限制
##    AP 後面所有無線用戶端的 MAC 都會學在這個埠上

## BPDU 保護：只給終端埠
[edit]
netadmin@acc-3f-ex2300# wildcard range set protocols rstp interface ge-0/0/[1-19] edge
[edit]
netadmin@acc-3f-ex2300# wildcard range set protocols rstp interface ge-0/0/[1-19] no-root-port
[edit]
netadmin@acc-3f-ex2300# set protocols rstp bpdu-block-on-edge
[edit]
netadmin@acc-3f-ex2300# set protocols layer2-control bpdu-block disable-timeout 300
```

### 步驟 7：檢查差異 ★★★★★

```text
[edit]
netadmin@acc-3f-ex2300# show | compare | no-more
```

★★★★★ 逐項核對清單：

- [ ] `ge-0/0/48`（上聯）**只有** description 被加上，沒有 disable、沒有 storm-control、沒有 mac-limit
- [ ] `ge-0/0/17`、`ge-0/0/18`（AP）沒有 mac-limit
- [ ] 停用的範圍是 20～47，**沒有多也沒有少**
- [ ] 沒有任何 `-` 開頭的行（這次全部是新增，不該刪掉任何既有設定）
- [ ] `storm-control` 只套在 1～19

```text
[edit]
netadmin@acc-3f-ex2300# show | compare | match "^-" | count
Count: 0 lines
```

★★★★★ **`-` 開頭的行是 0 = 這次變更純新增，不會刪掉任何東西。** 這是最安心的 diff。

### 步驟 8：送出並驗證 ★★★★★

```text
[edit]
netadmin@acc-3f-ex2300# commit check
configuration check succeeds
[edit]
netadmin@acc-3f-ex2300# commit confirmed 15 comment "CR-0601 3F 接取層安全基準"
commit confirmed will be automatically rolled back in 15 minutes unless confirmed
commit complete
```

```text
[edit]
netadmin@acc-3f-ex2300# run show interfaces descriptions | no-more
Interface       Admin  Link  Description
ge-0/0/1        up     up    PC-3F-A12-王小明
ge-0/0/2        up     up    PC-3F-A13-李小華
...
ge-0/0/17       up     up    AP-3F-東側-JNP-AP01
ge-0/0/18       up     up    AP-3F-西側-JNP-AP02
ge-0/0/19       up     up    PRN-3F-影印室-HP4525
ge-0/0/20       down   down  UNUSED - disabled 2026-09-02 CR-0601
...
ge-0/0/47       down   down  UNUSED - disabled 2026-09-02 CR-0601
ge-0/0/48       up     up    UPLINK-to-core-ex4300-ge-0/0/12
```

```text
[edit]
netadmin@acc-3f-ex2300# run show ethernet-switching table | count
Count: 23 lines
```

★★★★★ **MAC 表的筆數跟動手前一樣（19 個埠的裝置都還在）** —— 沒有人被誤斷。

```text
[edit]
netadmin@acc-3f-ex2300# run show interfaces terse | match "up    up" | count
Count: 42 lines
```

★★★★ 對照 `/var/tmp/before-terse.txt`，活著的埠數量沒有減少。

★★★★★ **實體驗證**（請人在現場做，這一步不能省）：

| 測試 | 預期結果 |
| --- | --- |
| 一台 PC 正常上網 | 通 |
| 無線 AP 的用戶端正常上網 | 通 |
| 印表機列印測試頁 | 通 |
| ★★★★★ 把網線插進 `ge-0/0/25`（已停用的孔） | **完全沒反應，網卡連 link 燈都不亮** |
| ★★★★ 把一台小交換器插進 `ge-0/0/5` | 觸發 BPDU 保護，埠被停掉，日誌有紀錄 |

```text
[edit]
netadmin@acc-3f-ex2300# run show log messages | match "BPDU|MAC_LIMIT|storm" | last 5
Sep  2 16:41:12  acc-3f-ex2300 eswd[3341]: ESWD_BPDU_BLOCK_PORT_DISABLED: ge-0/0/5: BPDU Block: Port disabled
```

★★★★ 測完把埠恢復：

```text
netadmin@acc-3f-ex2300> clear error bpdu interface ge-0/0/5
```

（★★★ 指令名稱依版本可能是 `clear ethernet-switching bpdu-error interface ...`，用 `clear ?` 確認。）

```text
[edit]
netadmin@acc-3f-ex2300# commit comment "CR-0601 驗證通過，確認定案"
commit complete
```

### 步驟 9：收尾 ★★★★

```text
netadmin@acc-3f-ex2300> show configuration | display set | save /var/tmp/after-CR0601.set
netadmin@acc-3f-ex2300> show interfaces descriptions | save /var/tmp/after-desc.txt
netadmin@acc-3f-ex2300> file copy /var/tmp/after-CR0601.set scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/
netadmin@acc-3f-ex2300> file copy /var/tmp/after-desc.txt scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/
netadmin@acc-3f-ex2300> request system configuration rescue save
```

★★★★ `after-desc.txt` 直接就是新版的埠對照表，貼進
[[040-01-18-guide-網路設備-網路設備盤點與文件化]] 的盤點文件。

### 驗收檢查表 ★★★★★

| # | 檢查項 | 通過標準 | 星級 |
| --- | --- | --- | --- |
| 1 | 動手前備份、rescue、MAC 表快照 | 備份伺服器上有 before 三份檔 | ★★★★★ |
| 2 | 未用埠判定依據充分 | 用 `Last flapped: Never` 而非只看當下狀態 | ★★★★★ |
| 3 | 每個啟用的埠都有 description | `show interfaces descriptions` 無空白 | ★★★★ |
| 4 | 上聯埠 description 含對端設備與埠號 | 例：`UPLINK-to-core-ex4300-ge-0/0/12` | ★★★★★ |
| 5 | 未用埠已 `disable` | `show interfaces terse` 顯示 `down down` | ★★★★★ |
| 6 | 未用埠已在隔離 VLAN | `show vlans PARKING` 含這些埠 | ★★★★ |
| 7 | 上聯埠**沒有**被套 storm-control／mac-limit | `show \| compare` 核對過 | ★★★★★ |
| 8 | AP 埠**沒有**被套 mac-limit | 同上 | ★★★★★ |
| 9 | diff 沒有任何 `-` 開頭的行 | `show \| compare \| match "^-" \| count` = 0 | ★★★★★ |
| 10 | 全程 `commit confirmed` | 輸出有 `automatically rolled back` | ★★★★★ |
| 11 | MAC 表筆數未減少 | 對照 before 快照 | ★★★★★ |
| 12 | 現場實測：停用的孔插了沒反應 | 網卡無 link | ★★★★★ |
| 13 | 現場實測：既有使用者不受影響 | PC／AP／印表機都正常 | ★★★★★ |
| 14 | 已 `commit` 二次確認 | `show system commit` 第 0 筆正確 | ★★★★★ |
| 15 | after 備份與埠對照表已更新 | 文件與現況一致 | ★★★★ |
| 16 | 錯誤計數已清零做為新基準線 | `clear interfaces statistics all` | ★★★ |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 網路「通但超級慢」，大檔案傳到一半停住 | 雙工不匹配：一端 auto、一端手動鎖定 | `show interfaces X extensive` 看 `Collisions` 與 `CRC/Align errors`；兩端統一為 auto |
| ★★★★★ 小封包正常、大封包（備份／NFS／iSCSI）失敗 | MTU 不匹配，路徑上有裝置沒設 jumbo frame | 主機端 `ping -M do -s 8972` 定位；★★★★ 記得 JunOS 的 MTU 含 14 bytes 二層標頭 |
| ★★★★★ 套用 `wildcard range` 之後一整片使用者斷網 | 範圍寫錯，把還在用的埠一起停了 | 立刻 `rollback 1` + `commit`。★★★★★ 以後 `show \| compare \| no-more` 逐行看完再 commit |
| ★★★★★ 開了 DHCP snooping 後整層樓拿不到 IP | 上聯 trunk 沒標為 trusted | `set vlans X forwarding-options dhcp-security group TRUSTED interface ge-0/0/48.0`；先 `rollback` 恢復服務 |
| ★★★★★ storm-control 把埠關掉且不會自己回來 | `action-shutdown` 沒配 `recovery-timeout` | 加上 `recovery-timeout 300`；先手動 `clear` 恢復。★★★★ 導入時先不要開 action-shutdown |
| ★★★★ 印表機／監視器每天早上都斷線 | `persistent-learning` 記住了舊 MAC，或 `interface-mac-limit` 太低 | `show ethernet-switching table interface X` 看實際學到幾個；`clear ethernet-switching table persistent-learning interface X` |
| ★★★★ AP 底下的無線用戶端只有前幾個能上網 | AP 埠被套了 `interface-mac-limit` | ★★★★★ AP 埠與 trunk **不要**設 MAC 限制，移除該設定 |
| ★★★★ `CRC/Align errors` 持續增加 | 線材劣化、接頭氧化、彎折過度、超長、干擾、SFP 故障 | `clear interfaces statistics X` 後觀察 10 分鐘；依序換線 → 換埠 → 換 SFP |
| ★★★★ `Carrier transitions` 一直漲，使用者說「網路一下有一下沒有」 | link flapping：線鬆、接頭沒卡好、對端省電模式、對端重開 | `Last flapped` 對照時間；重插線材；檢查對端網卡電源管理設定 |
| ★★★★ 光纖埠 link 起不來 | TX/RX 接反、光衰太大、模組不相容、對端埠關閉 | `show interfaces diagnostics optics X` 看接收光功率；對調 TX/RX 試試 |
| ★★★★ 新裝的 AP 起不來，PoE 沒供電 | AP 是 PoE+（Class 4）但埠或交換器只支援 802.3af；或總功率預算已滿 | `show poe interface` 看 Class 與狀態；`show poe controller` 看總功耗 |
| ★★★★ 某個埠學到幾十個 MAC | 後面私接了 hub 或交換器 | `show ethernet-switching table interface X`；依政策處理，並考慮 BPDU 保護 |
| ★★★ 開了 BPDU 保護後某些埠一直被關 | 那個埠真的接了交換器（可能是合法的） | 確認用途；合法的話移除 `edge` 設定；不合法就是找到問題了 |
| ★★★ 停用埠之後有人抱怨「這個孔以前可以用」 | 判定未用埠時只看當下狀態 | 用 `Last flapped` 而非即時狀態；恢復該埠並改標為 RESERVED |
| ★★★ `set interfaces X speed 100m` 被拒或無效 | 階層錯誤（`ether-options` vs `gigether-options` vs 實體層） | `set interfaces X ?` 確認該機型的正確階層 |
| ★★★ `show poe` 系列指令不存在 | 該機型沒有 PoE 功能 | `show chassis hardware` 確認機型；非 PoE 機種沒有這些指令 |
| ★★ `show interfaces diagnostics optics` 沒有數值 | 該模組不支援 DOM，或是銅纜 SFP | 換支援 DOM 的模組才看得到 |

### 排查步驟

**【1】先確認實體層有沒有錯誤 ★★★★★**

```text
netadmin@sw> clear interfaces statistics ge-0/0/10
netadmin@sw> show interfaces ge-0/0/10 extensive | match "Statistics last|CRC|Framing|Runts|Collisions|Carrier"
  Statistics last cleared: 2026-09-02 14:00:00 CST (00:00:03 ago)
    Errors: 0, Drops: 0, Framing errors: 0, Runts: 0, Policed discards: 0,
    Carrier transitions: 0, Errors: 0, Drops: 0, Collisions: 0, Aged packets: 0,
    CRC/Align errors                         0                0
```

等 10 分鐘再看一次。**還在漲就是現在進行式的實體故障**，跳【2】；都是 0 就跳【3】。

**【2】實體故障的縮小範圍法 ★★★★★**

★★★★★ 每次只換一個變數，順序固定：

| 順序 | 動作 | 排除什麼 |
| --- | --- | --- |
| 1 | 重插兩端接頭（聽到「喀」聲） | 接觸不良（最常見） |
| 2 | 換一條**已知良好**的跳線 | 線材 |
| 3 | 把線插到交換器的**另一個埠** | 交換器埠／SFP |
| 4 | 把對端接到**另一台設備** | 對端網卡 |
| 5 | 用線材測試儀測固定佈線 | 牆內佈線 |

★★★★ 每換一次就 `clear interfaces statistics` 再觀察，才知道是不是換對了。

**【3】確認雙工與速率 ★★★★★**

```text
netadmin@sw> show interfaces ge-0/0/10 | match "Speed|Auto-negotiation"
  Link-level type: Ethernet, MTU: 1514, LAN-PHY mode, Speed: 100mbps,
  Flow control: Disabled, Auto-negotiation: Disabled, Remote fault: Online
```

★★★★★ `Auto-negotiation: Disabled` + 對端是 auto = **就是這個問題**。
`Collisions` 不為零也是決定性證據（全雙工不該有碰撞）。

**【4】確認不是被保護機制擋住 ★★★★★**

```text
netadmin@sw> show interfaces ge-0/0/10 | match "Enabled|Error"
Physical interface: ge-0/0/10, Enabled, Physical link is Up
  BPDU Error: None, Loop Detect PDU Error: None, Ethernet-Switching Error: None,

netadmin@sw> show log messages | match "ge-0/0/10" | last 20
Sep  2 16:41:12  sw eswd[3341]: ESWD_MAC_LIMIT_EXCEEDED: ge-0/0/10.0: mac limit exceeded
```

| 看到什麼 | 元兇 |
| --- | --- |
| `BPDU Error: Detected` | ★★★★★ BPDU 保護，接了交換器 |
| `ESWD_MAC_LIMIT_EXCEEDED` | ★★★★ MAC 數量超過 `interface-mac-limit` |
| `L2ALD_ST_CTL_DISABLED` | ★★★★ storm-control 觸發 shutdown |
| `Physical interface: X, Administratively down` | ★★★★ 被 `disable` 了 |

**【5】確認 MAC 有沒有學到、學了幾個 ★★★★**

```text
netadmin@sw> show ethernet-switching table interface ge-0/0/10.0
Ethernet switching table : 24 entries, 24 learned
Routing instance : default-switch
   Vlan       MAC                 MAC      Logical                SVLBNH/  Active
   name       address             flags    interface              VENH Index  source
   OFFICE     b4:0c:25:1a:3f:e2   D        ge-0/0/10.0
   OFFICE     a0:ce:c8:33:71:04   D        ge-0/0/10.0
   ... 共 24 個 ...
```

★★★★★ **一個 access 埠學到 24 個 MAC = 後面接了 hub 或交換器**（或是 AP）。
去現場看那個孔。

**【6】光纖鏈路 ★★★★**

```text
netadmin@sw> show interfaces diagnostics optics xe-0/1/0 | match "Receiver signal|low warning|low alarm"
    Receiver signal average optical power     :  0.0231 mW / -16.36 dBm
    Receiver signal power low alarm           :  Off
    Receiver signal power low warning         :  On
    Laser rx power low alarm threshold        :  0.0158 mW / -18.01 dBm
    Laser rx power low warning threshold      :  0.0398 mW / -14.00 dBm
```

★★★★★ `-16.36 dBm` 已經低於 warning 門檻（-14.00）—— **光衰過大**。
清潔兩端接頭（專用清潔筆，不要用衛生紙）、檢查有沒有過度彎折、
必要時用光功率計逐段量測。

**【7】還是找不到就先恢復服務 ★★★★★**

```text
[edit]
netadmin@sw# rollback 1
[edit]
netadmin@sw# show | compare
[edit]
netadmin@sw# commit confirmed 5
```

原則見 [[100-02-10-guide-維運-故障排除方法論]]，跨廠牌通用流程見
[[040-01-17-guide-網路設備-交換器故障排除]]。

## 安全性注意事項

> [!danger] ★★★★★ 實體存取控制是所有網路安全的前提
> 本篇所有的埠安全機制（未用埠停用、MAC 限制、802.1X、DHCP snooping）
> 都只是**縱深防禦的其中一層**。如果任何人都能自由進出弱電間、
> 拔掉一台印表機的線把自己的筆電接上去，這些設定只是提高門檻，不是解決問題。
> 實體管制見 [[040-02-13-guide-機房-機房實體安全]]。

| 項目 | 風險 | 做法 | 星級 |
| --- | --- | --- | --- |
| 未使用的埠是 up 的 | ★★★★★ 任何人插線就進內網，無紀錄 | `disable` + 隔離 VLAN + description 三件套 | ★★★★★ |
| 埠沒有 description | 排錯時不知道通到哪，也無法稽核 | 全機關統一命名規範，定期匯出核對 | ★★★★ |
| 沒有 storm-control | 一個環路癱瘓整個廣播網域 | 接取埠套 3%～5%；★★★★ 上聯不套 | ★★★★ |
| 沒有 BPDU 保護 | 使用者接一台交換器就可能搶走 root bridge，改變全網拓樸 | `edge` + `no-root-port` + `bpdu-block-on-edge` | ★★★★ |
| 沒有 MAC 數量限制 | 私接 hub／交換器無法察覺 | 一般埠 `interface-mac-limit 3` + `drop-and-log` | ★★★★ |
| 沒有 DHCP snooping | ★★★★★ 私接無線分享器（WAN/LAN 插反）發出錯誤 DHCP，整層樓上不了網 | `dhcp-security` + 上聯 trusted | ★★★★★ |
| 沒有 ARP inspection | ARP 欺騙／中間人攻擊 | `arp-inspection`（需先有 DHCP snooping 綁定表） | ★★★★ |
| 接取埠設成 trunk | ★★★★★ 使用者可自行進入任何 VLAN | 接終端一律 access（06 篇） | ★★★★★ |
| PoE 全開 | 電源預算被吃光，重要 AP 反而斷電 | 不需要的埠 `poe disable`；重要設備 `priority high` | ★★★★ |
| 沒有定期看錯誤計數 | 線材劣化到斷線才知道 | 每月匯出 `CRC/Align` 掃描，見 [[100-02-04-guide-維運-每月維護作業]] | ★★★★ |
| 光模組溫度過高沒人管 | 模組壽命縮短，突發性斷線 | 納入巡檢，見 [[040-02-10-guide-機房-機房巡檢與紀錄]] | ★★★ |
| 802.1X 沒有 fallback 設計 | RADIUS 掛掉全機關斷網 | 冗餘 RADIUS + `server-reject-vlan` + 分階段導入 | ★★★★★ |
| persistent MAC 沒有解除流程 | 使用者換電腦就卡住，客服量暴增 | 寫進工單流程；只用在不會換的設備上 | ★★★★ |

> [!warning] ★★★★ 稽核常見缺失（埠層級）
> 1. **未使用網路埠未停用** —— 這是最常見、最容易被抓、也最容易改的一項
> 2. 網路埠無用途標示，無法提出埠與使用者的對應清單
> 3. 未設定廣播風暴抑制
> 4. 未防範未經授權的網路設備接入（無 802.1X／MAC 限制／DHCP snooping）
> 5. 未定期檢視介面錯誤計數與線路品質
>
> 第 1、2 項用本篇「完整實戰範例」的流程一天就能改完，且不需要任何額外採購。
> **投資報酬率最高的資安改善之一。**

## 速查表

| 指令 / 設定項 | 說明 | 星級 |
| --- | --- | --- |
| `set interfaces ge-0/0/1 description "..."` | 埠描述（★★★★ 上聯要寫對端設備與埠） | ★★★★★ |
| `set interfaces ge-0/0/20 disable` | 停用埠 | ★★★★★ |
| `wildcard range set interfaces ge-0/0/[20-47] disable` | 批次停用（★★★★★ 先 `show \| compare`） | ★★★★★ |
| `set interfaces ge-0/0/1 speed 100m` / `link-mode full-duplex` | 手動鎖速率／雙工（★★★★ 通常不要設） | ★★★ |
| `set interfaces ge-0/0/1 gigether-options no-auto-negotiation` | 關自動協商（ELS；非 ELS 用 `ether-options`） | ★★★ |
| `set interfaces ge-0/0/40 mtu 9192` | ★★★★★ JunOS 的 MTU **含 14 bytes 二層標頭** | ★★★★ |
| `set forwarding-options storm-control-profiles P all bandwidth-percentage 3` | 風暴抑制門檻（ELS） | ★★★★ |
| `set forwarding-options storm-control-profiles P all no-unknown-unicast` | 排除未知單播 | ★★★★ |
| `set forwarding-options storm-control-profiles P action-shutdown` | ★★★★★ 超標關埠（要配 recovery-timeout） | ★★★★★ |
| `set interfaces ge-0/0/1 unit 0 family ethernet-switching storm-control P` | 套到埠 | ★★★★ |
| `set interfaces ge-0/0/1 unit 0 family ethernet-switching recovery-timeout 300` | 自動恢復 | ★★★★ |
| `set ethernet-switching-options storm-control interface all level 3` | 風暴抑制（**非 ELS**） | ★★★ |
| `set switch-options interface ge-0/0/1.0 interface-mac-limit 3` | MAC 數量上限（ELS） | ★★★★ |
| `set switch-options interface ge-0/0/1.0 interface-mac-limit packet-action drop-and-log` | 超過時的動作 | ★★★★ |
| `set switch-options interface ge-0/0/1.0 persistent-learning` | sticky MAC（ELS） | ★★★★ |
| `clear ethernet-switching table persistent-learning interface X` | 解除 sticky MAC | ★★★★ |
| `set ethernet-switching-options secure-access-port interface X mac-limit 3 action drop` | MAC 限制（**非 ELS**） | ★★★ |
| `set protocols rstp interface ge-0/0/1 edge` | 終端埠快速轉發（≈ portfast） | ★★★★ |
| `set protocols rstp interface ge-0/0/1 no-root-port` | ≈ root guard | ★★★★ |
| `set protocols rstp bpdu-block-on-edge` | ★★★★★ ≈ BPDU guard | ★★★★★ |
| `set protocols layer2-control bpdu-block disable-timeout 300` | BPDU 保護自動恢復 | ★★★★ |
| `set vlans X forwarding-options dhcp-security` | DHCP snooping（ELS） | ★★★★★ |
| `set vlans X forwarding-options dhcp-security arp-inspection` | 動態 ARP 檢查 | ★★★★ |
| `set vlans X forwarding-options dhcp-security group TRUSTED interface ge-0/0/48.0` | ★★★★★ 上聯標 trusted（不設就全斷） | ★★★★★ |
| `show dhcp-security binding` | DHCP 綁定表 | ★★★★ |
| `set protocols dot1x authenticator interface X supplicant multiple` | 802.1X（每 MAC 各自認證） | ★★★ |
| `set protocols dot1x authenticator interface X mac-radius` | 不支援 802.1X 的設備走 MAC 認證 | ★★★★ |
| `set protocols dot1x authenticator interface X guest-vlan GUEST` | 無回應丟訪客 VLAN | ★★★★ |
| `show dot1x interface` / `show dot1x interface X detail` | 802.1X 狀態 | ★★★ |
| `show interfaces descriptions` | ★★★★★ 埠對照表的原始資料 | ★★★★★ |
| `show interfaces terse` | 管理／實體狀態一覽 | ★★★★★ |
| `show interfaces X extensive` | ★★★★★ 錯誤計數（排錯最重要的指令） | ★★★★★ |
| `show interfaces extensive \| match "Physical interface\|CRC/Align" \| no-more` | 全機掃錯誤 | ★★★★★ |
| `clear interfaces statistics X` / `all` | ★★★★★ 清計數器建立新基準線 | ★★★★★ |
| `show interfaces X extensive \| match "Last flapped\|Statistics last"` | 上次 flap 與計數起算時間 | ★★★★ |
| `show interfaces diagnostics optics X` | SFP 光功率與溫度 | ★★★★ |
| `show ethernet-switching table interface X` | 這個埠學到幾個 MAC | ★★★★★ |
| `show poe controller` / `show poe interface` | PoE 總功耗與逐埠狀態 | ★★★ |
| `set poe interface X disable` / `priority high` | PoE 管理 | ★★★ |
| `CRC/Align errors` 增加 | ★★★★★ 實體層：換線 → 換埠 → 換 SFP | ★★★★★ |
| `Carrier transitions` 增加 | ★★★★★ link flapping：重插線材、查對端 | ★★★★★ |
| `Collisions` 不為零 | ★★★★★ 雙工不匹配 | ★★★★★ |

## 練習題

> [!question]- 練習 1：找出你們網路裡所有「沒在用卻是 up」的埠 ★★★★★
> 對每一台交換器：
> 1. `show interfaces extensive | match "Physical interface|Last flapped" | no-more | save /var/tmp/flap.txt`
> 2. `show interfaces descriptions | save /var/tmp/desc.txt`
> 3. `file copy` 帶回來，整理成表：埠號 / description / 管理狀態 / Last flapped
> 4. 篩出「Admin 是 up 但 Last flapped 是 Never，或超過 180 天」的埠
> 5. 統計數量
>
> **要回答的問題**：這些埠佔全部的幾成？如果現在有人拿一台筆電進你們的辦公室，
> 他有多少個孔可以插？把這個數字寫進資安風險報告，比講一百句道理有效。
> **不要直接停用**，先走變更流程與公告（[[100-02-08-guide-維運-變更管理流程]]）。

> [!question]- 練習 2：親手製造並診斷雙工不匹配 ★★★★★
> 在測試環境（一台交換器 + 一台 Linux）：
> 1. 兩端都 auto，`iperf3` 測一次速度，記下數字
> 2. `show interfaces X extensive` 記下 `Collisions` 與 `CRC/Align errors`
> 3. 交換器端手動鎖 `speed 100m` + `link-mode full-duplex` + `no-auto-negotiation`，
>    Linux 端**保持 auto**
> 4. 再測一次 `iperf3`，再看一次計數器
> 5. Linux 端也手動鎖成 100/full（`ethtool -s eth0 speed 100 duplex full autoneg off`），
>    第三次測試
> 6. 全部恢復成 auto
>
> **要回答的問題**：第 4 步的速度掉了多少？`Collisions` 漲了嗎？
> 兩端的 `ethtool eth0` 與 `show interfaces X` 分別顯示什麼？
> **為什麼光看「link 是 up 的」完全診斷不出這個問題？**

> [!question]- 練習 3：storm-control 的門檻怎麼訂 ★★★★
> 1. 在測試交換器上套 `bandwidth-percentage 1`（故意設很低），**不加 action-shutdown**
> 2. 從一台 PC 產生大量廣播（例如跑 `ping -b` 廣播位址，或用 hping3）
> 3. `show log messages | match storm` 觀察觸發
> 4. `show interfaces X extensive | match "Policed discards"` 看被丟了多少
> 5. 逐步調高到 3%、5%，觀察正常流量會不會誤觸發
> 6. 最後加上 `action-shutdown` + `recovery-timeout 60`，再測一次，觀察埠被關與自動恢復
>
> **要回答的問題**：你們環境的正常廣播流量佔多少百分比？
> 訂多少門檻既能擋住環路又不會誤殺？為什麼上聯 trunk 不該套？

> [!question]- 練習 4：讀懂一份 `show interfaces extensive` ★★★★★
> 挑三個埠（一個正常、一個有錯誤、一個是光纖上聯）：
> 1. `show interfaces X extensive | save /var/tmp/X.txt`
> 2. `clear interfaces statistics X`
> 3. 等 30 分鐘
> 4. 再存一次，比較兩份的差異
> 5. 對照本篇的「計數器判讀對照表」，判斷每個埠的健康狀況
> 6. 光纖埠再加做 `show interfaces diagnostics optics X`
>
> **要回答的問題**：哪些計數器在 30 分鐘內有增加？增加多少算異常？
> `Statistics last cleared` 那一行為什麼是判讀的關鍵？
> 把這個流程寫成可以排進每月維護的檢查表（[[100-02-04-guide-維運-每月維護作業]]）。

> [!question]- 練習 5：寫一份「接取交換器安全基準」★★★★
> 依本篇的完整實戰範例，寫出可套用到所有接取交換器的基準，包含：
> - 埠角色分類（PC／AP／印表機／伺服器／上聯／未用／保留）
> - 每一類的 description 格式
> - 每一類該套哪些保護（storm-control、mac-limit、BPDU、PoE 優先權）
> - ★★★★★ **明確列出「哪些埠絕對不能套哪些設定」**（上聯不套 storm-control、
>   AP 不套 mac-limit……）
> - 未用埠的判定標準與處理流程
> - 變更後的驗證清單
>
> 與 [[020-02-03-02-ref-標準化-基準設定與範本化]] 對照，思考怎麼用 `apply-groups` 派送。

## 小測驗

Q1. 使用者說「網路是通的但慢到不能用，傳大檔案會停住」。`show interfaces terse` 顯示 `up up`。你要看哪一個指令的哪幾個計數器？看到什麼就能確定是雙工不匹配？

Q2. 交換器上設 `mtu 1500`、伺服器上設 `mtu 1500`。為什麼這樣其實不匹配？JunOS 要設多少才等於 Cisco/Linux 的 1500？

Q3. 這行指令會發生什麼事：`wildcard range set interfaces ge-0/0/[20-47] disable`？執行之前你一定要先做哪兩件事？

Q4. 未使用的埠只做 `disable` 而不丟進隔離 VLAN，還有什麼風險？只丟進隔離 VLAN 而不 `disable` 又有什麼風險？

Q5. 是非題：`interface-mac-limit 3` 應該套用在所有接取埠上，包括接無線 AP 的埠。請說明理由。

Q6. 你開了 DHCP snooping（`dhcp-security`），commit 之後整層樓的人都拿不到 IP，但 DHCP 伺服器的日誌顯示一切正常。診斷與解法？

Q7. `show interfaces diagnostics optics xe-0/1/0` 顯示 `Receiver signal average optical power : -16.36 dBm`，而 `Laser rx power low warning threshold : -14.00 dBm`。代表什麼？依序要做什麼？

Q8. `storm-control` 加了 `action-shutdown` 但沒加 `recovery-timeout`，半夜一台故障網卡觸發了它。隔天早上會發生什麼？正確的導入順序應該是什麼？

Q9. 你要導入 802.1X。除了交換器與 RADIUS 的設定之外，請列出至少四項必須先想清楚的配套，並各說明不處理的後果。

Q10. `show interfaces ge-0/0/10 extensive` 顯示 `CRC/Align errors: 1842`。你能不能據此判定這條線有問題？如果不能，正確的判定流程是什麼？

> [!question]- 測驗答案
> **Q1.** ★★★★★ 要看 **`show interfaces ge-0/0/X extensive`**，重點三個地方：
> 1. `Collisions`（在 Output errors 那一段）—— ★★★★★ **全雙工環境不應該有任何碰撞**，
>    不為零就是決定性證據
> 2. `CRC/Align errors` / `Framing errors` / `Runts` —— 通常會一起漲
> 3. 標頭那行的 `Auto-negotiation: Enabled/Disabled` 與 `Speed`
>
> 確定是雙工不匹配的組合：**交換器端 `Auto-negotiation: Disabled`（或反之），
> 而 `Collisions` 持續增加**。
> ★★★★★ 關鍵是「兩邊的 link 都是 up、兩邊的 `show` 看起來都正常」——
> 這正是這個故障難查的原因，只有錯誤計數會說實話。
> 修正：兩端統一為自動協商（現代環境的正解），或兩端都手動鎖同樣的值。
> 見「自動協商與雙工不匹配」與「排查步驟【3】」。
>
> **Q2.** ★★★★★ 因為 **JunOS 的 `mtu` 包含 14 bytes 的乙太網路二層標頭**
> （目的 MAC 6 + 來源 MAC 6 + Type 2），而 Cisco／Linux 的 MTU 只算 payload。
> 所以 JunOS 上設 `mtu 1500` 實際只允許 **1486 bytes 的 payload**，比對端少 14 bytes。
> 正確對應：
> - 標準乙太網路：JunOS `1514`（這也是預設值，通常不用設）
> - 帶一個 VLAN tag：JunOS `1518`
> - Jumbo 9000 payload：JunOS `9014` 以上（依機型上限，常見設 9192／9216）
>
> ★★★★ 症狀是「小封包正常、大封包失敗」，因為 ping 預設 56 bytes 完全不受影響。
> 診斷用 `ping -M do -s 8972`（不准分片）。見「JunOS 的 MTU」。
>
> **Q3.** ★★★★★ 它會把 `ge-0/0/20` 到 `ge-0/0/47` **共 28 個埠全部停用**（加進 candidate）。
> commit 之後這些埠變成 `down down`，插線完全沒反應。
>
> 執行前一定要先做的兩件事：
> 1. ★★★★★ **確認這個範圍內真的沒有埠在用**。不能只看當下的
>    `show interfaces terse`（使用者可能請假、印表機可能週末才開），
>    要用 `show interfaces extensive | match "Physical interface|Last flapped"`
>    找出 `Last flapped: Never` 或很久以前的埠。
> 2. ★★★★★ **`show | compare | no-more` 逐行看完**，確認：
>    範圍正確、沒有動到上聯（`ge-0/0/48`）、沒有動到還在用的埠。
>
> 然後才是 `commit check` → `commit confirmed 15`。
> ★★★★ 弄錯範圍就是一整片使用者斷網，但只要在 commit 前發現，`rollback 0` 就沒事。
> 見「未用埠停用與隔離」。
>
> **Q4.** ★★★★★
> - **只 `disable` 不隔離**：日後有人為了「借一個埠用一下」把 `disable` 拿掉，
>   埠就直接掉進 `default` VLAN 或上一個使用者留下的 VLAN 裡。
>   那個 VLAN 可能是伺服器網段、可能是管理網段 —— **一個臨時的方便造成永久的破口**。
> - **只隔離不 `disable`**：埠是活的，插上去就有 link。攻擊者可以：
>   在隔離 VLAN 內做二層攻擊、送 DHCP 探測網路、跑 LLDP 找出交換器型號與版本、
>   嘗試 VLAN hopping、或單純製造廣播風暴。而且**這一切都不會留下任何紀錄**。
>
> ★★★★★ 所以標準做法是三件事一起做：`disable` + 隔離 VLAN + description 標註。
> 第三項是給「下一個人」看的，讓他知道這是刻意的設計而不是漏設。
> 見「未使用的埠是最常被忽略的資安破口」。
>
> **Q5.** ★★★★★ **錯，AP 埠絕對不能套。**
> 無線 AP 底下所有連上來的無線用戶端，它們的 MAC 位址**全部都會學在 AP 那個埠上**
> （AP 是二層橋接，不做 NAT）。一台 AP 接 30 個用戶端，那個埠就會有 30 個 MAC。
> 設了 `interface-mac-limit 3` 的結果：**只有前 3 個連上的人能上網，之後的全部被丟棄**，
> 而且症狀是「無線有時候能用有時候不能用」，極難診斷。
>
> ★★★★ 同樣不能套的還有：
> - **上聯 trunk**（對端整台交換器的 MAC 都會學過來）
> - 接虛擬化主機的埠（每台 VM 一個 MAC）
> - 接 IP 話機 + PC 的埠（要留 2 個以上）
>
> 適合套的是：一般辦公 PC 埠（3）、印表機埠（1）、監視器埠（1）。
> 見「MAC 數量限制與 sticky MAC」。
>
> **Q6.** ★★★★★ 診斷：**上聯 trunk 沒有被標記為 trusted。**
> DHCP snooping 的預設行為是「**所有埠都不信任**」，只有 trusted 埠可以送出
> DHCP OFFER 與 ACK。你的合法 DHCP 伺服器在上游，它的回應從上聯 trunk 進來，
> 但那個埠是 untrusted → ★★★★★ **交換器把合法的 DHCP 回應丟掉了**。
> 而 DHCP 伺服器那邊看起來完全正常，因為它確實有送出回應，只是被中途丟棄。
>
> 解法：
> ```junos
> set vlans OFFICE forwarding-options dhcp-security group TRUSTED overrides trusted
> set vlans OFFICE forwarding-options dhcp-security group TRUSTED interface ge-0/0/48.0
> ```
> ★★★★★ 但**現在服務中斷中，第一件事是恢復服務**：`rollback 1` + `commit`
> （或等 `commit confirmed` 自動回滾），把使用者救回來，再到測試 VLAN 上把 trusted 設對。
> 見「DHCP snooping」與 [[100-02-10-guide-維運-故障排除方法論]]。
>
> **Q7.** ★★★★★ 代表**接收到的光功率已經低於警告門檻**（-16.36 比 -14.00 更小／更弱），
> 也就是**光衰過大**。這條鏈路現在可能還通，但已經在故障邊緣 ——
> 典型症狀是間歇性斷線、CRC 錯誤增加、天氣變熱時更容易出事。
>
> 依序要做的事：
> 1. ★★★★★ **清潔兩端的光纖接頭與模組端口**（用專用清潔筆或無塵拭鏡紙 + 酒精，
>    ★★★★ **絕對不要用衛生紙或衣服**，會留下棉絮讓情況更糟）
> 2. 檢查跳線有沒有被壓到、過度彎折（彎曲半徑小於規格）、被門夾到
> 3. 換一條**已知良好**的跳線測試
> 4. 對端也做一次同樣的檢查（光衰可能發生在任何一段）
> 5. 用光功率計逐段量測，找出衰減發生在哪一段固定佈線
> 6. 以上都排除就是模組老化，換模組
>
> ★★★★ 同時要看 `Module temperature` —— 溫度過高也會讓輸出下降，
> 那是機櫃散熱問題（[[040-02-02-guide-機房-空調系統與溫溼度監控]]）。
> 見「SFP 光模組診斷」與「排查步驟【6】」。
>
> **Q8.** ★★★★★ 隔天早上：**那個埠還是關著的，而且不會自己恢復**。
> `action-shutdown` 把埠停用之後需要人工介入才會回來，所以：
> - 使用者上班發現網路不通 → 打電話 → 你要遠端或到現場一個一個埠處理
> - 如果觸發的是多個埠（例如環路造成的連鎖反應），早上就是一團混亂
> - 更糟的是：如果你不知道有這個設定，會花很久時間在找「為什麼這個埠是 down 的」
>
> ★★★★★ 正確的導入順序（四階段）：
> 1. **只設 `bandwidth-percentage`，不加 `action-shutdown`**，套在接取埠上
> 2. 跑一個月，觀察 `show log messages | match storm` 與 `Policed discards`，
>    確認正常流量不會誤觸發（誤觸發代表門檻太低，要調高）
> 3. 門檻調到合適值後，才加上 `action-shutdown`
> 4. ★★★★★ **同時一定要加 `recovery-timeout 300`**，讓埠 5 分鐘後自己回來 ——
>    真的有環路的話它會再被關掉，但至少偶發性的觸發不需要人工處理
>
> ★★★★ 另外：**上聯 trunk 永遠不要套 storm-control**，誤殺的代價是整台交換器離線。
> 見「storm-control 廣播風暴抑制」。
>
> **Q9.** ★★★★★ 至少四項（實際上六項都該處理）：
> 1. **不支援 802.1X 的設備清單**：印表機、監視器、IP 話機、門禁、
>    冷氣控制器、電梯、老舊儀器。★★★★★ 不處理的後果：**這些設備全部斷網**，
>    而且往往是最關鍵的（門禁進不去、監視器沒畫面）。
>    解法是 `mac-radius` + 人工維護 MAC 清單。
> 2. **RADIUS 冗餘與失效策略**：不處理的後果是 ★★★★★
>    **RADIUS 掛掉的那一刻全機關斷網**，而且重開機的設備再也認證不上。
>    要有兩台以上 RADIUS，並設計 `server-reject-vlan` 或 fail-open 策略。
> 3. **憑證或帳號來源**：EAP-TLS 要每台電腦一張憑證（誰發、怎麼佈署、怎麼撤銷）；
>    PEAP 要綁 AD。不處理的後果是專案卡在「使用者不知道要輸入什麼」。
> 4. **訪客與廠商**：`guest-vlan` 的設計、能存取什麼、要不要另外做認證入口。
>    不處理的後果是廠商來維護時沒網路，最後有人乾脆把 802.1X 關掉。
> 5. **使用者教育與客服量**：導入初期客服電話會暴增，要先準備 FAQ 與現場支援。
> 6. ★★★★★ **分階段導入**：先一層樓、先監控模式（失敗也放行到 guest-vlan）、
>    收集完整的 MAC 與帳號清單後才收緊。一次全機關上線幾乎必定失敗。
>
> 見「802.1X 埠認證」的 danger callout。
>
> **Q10.** ★★★★★ **不能。** `CRC/Align errors: 1842` 是**累積值**，
> 它可能是三年前某次插拔、某次搬機櫃、或設備剛上線時留下的，
> 跟「現在這條線好不好」完全沒有關係。
>
> 正確的判定流程：
> 1. 先看 `Statistics last cleared: ...` 那一行 —— 這些數字累積了多久？
>    如果是「8 天前清的」，1842 個錯誤分散在 8 天可能不算什麼；
>    如果是「10 分鐘前清的」，那就是嚴重故障。
> 2. ★★★★★ **`clear interfaces statistics ge-0/0/10`** 歸零
> 3. 等 10～30 分鐘（流量大的埠 10 分鐘就夠，冷門埠要更久）
> 4. 再看一次 `show interfaces ge-0/0/10 extensive | match "CRC|Framing|Carrier|Statistics last"`
> 5. **還在漲 = 現在進行式的故障**，進入實體層縮小範圍法：
>    重插接頭 → 換跳線 → 換交換器埠 → 換對端設備 → 測固定佈線，
>    ★★★★ 每次只換一個變數，且每次都重新 clear 再觀察
> 6. 都沒漲 = 歷史遺留，記錄下來但不用處理
>
> ★★★★ 這個「清零 → 觀察增量」的原則適用於**所有**累積型計數器，
> 是網路排錯最基本也最常被忽略的一步。見「用 `show interfaces extensive` 讀懂錯誤計數」。

## 延伸閱讀

- [[040-01-05-cmd-Juniper-JunOS-基礎操作]] —— `commit confirmed`、`wildcard range`、`show | compare`
- [[040-01-06-guide-Juniper-VLAN與Trunk設定]] —— 隔離 VLAN、access／trunk、`switch-options` 階層
- [[040-01-07-guide-Juniper-管理IP與遠端存取]] —— RADIUS 設定（802.1X 共用）、管理面防護
- [[040-01-09-svc-Juniper-設定備份與韌體升級]] —— 埠設定的備份與換機還原
- [[040-01-16-guide-網路設備-鏈路聚合與STP]] —— STP 完整說明、`edge`／root guard 的原理
- [[040-01-17-guide-網路設備-交換器故障排除]] —— 跨廠牌的通用排錯流程
- [[040-01-13-guide-Cisco-埠設定與安全]] —— Cisco 那一側（port-security、errdisable、CoPP）
- [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]] —— 兩邊指令對照
- [[040-01-18-guide-網路設備-網路設備盤點與文件化]] —— 埠對照表怎麼維護
- [[010-02-04-guide-網概-線材與實體層]] —— 雙絞線等級、光纖種類、SFP 規格
- [[040-02-08-guide-機房-結構化佈線與標籤規範]] —— 實體佈線與標籤，與埠 description 對應
- [[040-02-13-guide-機房-機房實體安全]] —— 實體存取控制，埠安全的前提
- [[100-02-04-guide-維運-每月維護作業]] —— 錯誤計數掃描排進定期維護
- [[090-02-08-guide-防護-系統強化與稽核]] —— 稽核項目與佐證
- Juniper EX Series Interfaces User Guide：<https://www.juniper.net/documentation/us/en/software/junos/interfaces-ethernet-switches/>
- Juniper Port Security User Guide（MAC limit／DHCP snooping／802.1X）：<https://www.juniper.net/documentation/us/en/software/junos/security-services/>
- Juniper Feature Explorer（確認機型是否支援某功能）：<https://apps.juniper.net/feature-explorer/>
