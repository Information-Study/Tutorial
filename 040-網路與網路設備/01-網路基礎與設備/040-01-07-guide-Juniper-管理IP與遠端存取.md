---
title: "Juniper 管理 IP 與遠端存取"
desc: "irb／me0 兩種管理路徑、static route、SSH 與使用者 class，以及掛在 lo0 上保護 Routing Engine 的 firewall filter"
aliases: [irb, fxp0, me0, em0, mgmt_junos, lo0 filter, system login class, root-authentication]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-05-cmd-Juniper-JunOS-基礎操作]]", "[[040-01-06-guide-Juniper-VLAN與Trunk設定]]"]
updated: 2026-09-02
---

# Juniper 管理 IP 與遠端存取

> [!abstract] 這篇你會學到
> - ★★★★★ **帶內（in-band）與帶外（out-of-band）兩條管理路徑**的差別，以及為什麼機關網路
>   兩條都要有 —— 只有一條的話，改壞它就等於買車票去機房
> - ★★★★★ 掛在 `lo0` 上的 **firewall filter 保護 Routing Engine** —— 這是交換器最重要的一道防護，
>   也是**最容易把自己永久鎖在門外**的一個設定
> - ★★★★ `irb`（ELS）／`vlan`（非 ELS）帶內管理 IP、`me0`／`em0`／`fxp0` 帶外管理埠的差異與選擇
> - ★★★★ `system login class` 自訂權限：讓值班人員只能看不能改，且每一條指令都留下稽核紀錄
> - ★★★★ SSH 加固：關 root 登入、關密碼登入改用金鑰、連線速率限制、演算法清單
> - ★★★★ `set system syslog ... interactive-commands any` —— 記錄「誰打了哪一條指令」，
>   資安稽核的必備項目
> - ★★★ NTP、DNS、hostname、時區、登入警語，以及 RADIUS／TACACS+ 集中認證的接法
> - 產出一份可直接套用的「機關交換器管理面基準設定」與不鎖門 SOP

> [!warning] 未實機驗證
> ★★★★★ 本專案沒有實體 Juniper 設備可驗證。本篇以 **EX 系列（ELS，Junos 21.4）** 為主線，
> 帶外管理埠名稱（`me0` / `em0` / `fxp0`）、`mgmt_junos` 管理路由執行個體、
> SSH 演算法清單的支援程度**依機型與版本差異極大**。
> 動手前務必在該機型上用 `?`、`help reference` 與
> `show interfaces terse | match "fxp0|me0|em0"` 確認，
> 並全程走 [[040-01-05-cmd-Juniper-JunOS-基礎操作]] 的 `commit confirmed` 流程。

## 前置知識

- [[040-01-05-cmd-Juniper-JunOS-基礎操作]] —— `commit confirmed` 是本篇每一節的前提
- [[040-01-06-guide-Juniper-VLAN與Trunk設定]] —— 帶內管理 IP 要掛在某個 VLAN 的 `irb` 上
- [[040-01-02-guide-網路設備-IP位址規劃與子網切分]] —— 管理網段要獨立規劃
- [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] —— 交換器也用金鑰登入，金鑰怎麼產、怎麼管
- [[020-02-01-04-svc-sshd-伺服器端設定]] —— 「改遠端存取設定不把自己鎖在外面」的同一套思維
- [[090-02-06-guide-防護-遠端存取安全]] —— 遠端管理的通用安全原則

## 觀念說明

### 兩條管理路徑：帶內與帶外 ★★★★★

```text
       ┌──────────── 帶外管理（out-of-band, OOB）────────────┐
       │                                                     │
   管理站 ──── 獨立的管理交換器 ──── me0/em0/fxp0 ──┐        │
  10.99.1.5         （只接管理埠）      10.99.0.11  │        │
                                                    │        │
                                          ┌─────────▼────────▼──┐
                                          │   EX 交換器          │
                                          │                      │
   使用者網路 ─── ge-0/0/48 (trunk) ──────▶│ irb.99  10.99.0.11  │
                    帶 VLAN 99             │                      │
       │                                   └──────────────────────┘
       └──────────── 帶內管理（in-band）─────────────┘
```

| | 帶內（in-band） | 帶外（out-of-band, OOB） |
| --- | --- | --- |
| 走哪條路 | 使用者資料走的同一批實體線路 | ★★★★★ **完全獨立的管理網路** |
| JunOS 介面 | `irb.99`（ELS）／`vlan.99`（非 ELS） | `me0` / `em0` / `fxp0`（依機型） |
| 成本 | ★★★★★ 零（用現有線路） | 要多一台管理交換器與多一條線 |
| 改壞 trunk／VLAN 時 | ★★★★★ **管理連線一起斷** | ★★★★★ **還連得上** |
| 設備轉發功能故障時 | 連不上 | ★★★★ 通常還連得上（走 RE 直連） |
| 韌體升級中途 | 可能斷 | ★★★★ 相對穩定 |
| 常見做法 | 中小型機關只有這個 | ★★★★★ 機房核心設備一定要有 |

> [!danger] ★★★★★ 只有帶內管理 = 每次變更都在走鋼索
> 帶內管理的致命問題是：**你要改的東西（VLAN、trunk、埠設定）和你連線用的路徑是同一條**。
> 改錯上聯 trunk 的 `vlan members`，管理 VLAN 一起消失，你在斷線的那一刻同時失去了修復的能力。
>
> 這就是為什麼 [[040-01-05-cmd-Juniper-JunOS-基礎操作]] 一直強調 `commit confirmed` ——
> 沒有帶外管理時，**`commit confirmed` 是你唯一的救生索**。
>
> 機房核心設備的建議配置：帶外管理埠接到一台獨立的管理交換器，
> 該交換器再接一台可以撥號或走 4G 的遠端存取設備（或至少接 console server）。
> 這筆錢在第一次半夜出事的時候就回本了。

### 帶外管理埠的名稱依機型不同 ★★★★

★★★★★ **不要猜，用指令看**：

```text
netadmin@sw> show interfaces terse | match "fxp0|me0|em0|vme"
me0                     up    up
me0.0                   up    up   inet     10.99.0.11/24
```

| 介面名稱 | 常見機型 | 備註 |
| --- | --- | --- |
| `me0` | ★★★★ EX2200／EX2300／EX3300／EX3400／EX4200 等多數 EX 交換器 | Management Ethernet |
| `em0` | ★★★ EX4300／EX4600／QFX 系列（依版本） | |
| `fxp0` | ★★★★ SRX 防火牆、MX 路由器、M/T 系列、vSRX | |
| `vme` | ★★★ Virtual Chassis 的虛擬管理介面 | 堆疊時用它，IP 跟著 master 走 |

★★★★★ **Virtual Chassis（堆疊）務必用 `vme`**：如果把管理 IP 設在某一台的 `me0` 上，
那台當機時整個堆疊就管不到了。`vme` 的 IP 會自動跟著目前的 master 成員走。

> [!warning] ★★★★ 帶外管理埠不是交換埠
> `me0` / `em0` / `fxp0` **只連到 Routing Engine，不參與封包轉發**。
> 你不能把它當成一般的網路孔用，也不能把它加進 VLAN。
> 它的唯一用途就是管理，而且 ★★★★ **預設沒有 IP，一定要手動設**。

### 管理路由執行個體 `mgmt_junos` ★★★

較新的 Junos（多數 17.3 以後的平台）支援把帶外管理埠丟進一個**獨立的路由執行個體**：

```junos
set system management-instance
set interfaces em0 unit 0 family inet address 10.99.0.11/24
set routing-instances mgmt_junos routing-options static route 0.0.0.0/0 next-hop 10.99.0.1
```

| | 不用 `management-instance` | 用 `management-instance` |
| --- | --- | --- |
| 管理埠的路由 | ★★★★ 跟資料平面**共用**同一張路由表 | 獨立的 `mgmt_junos` VRF |
| 兩條預設路由 | ★★★★★ **會打架**（管理的 0.0.0.0/0 可能蓋掉資料的） | 各自獨立，互不干擾 |
| 管理流量誤入資料網路 | 有可能 | ★★★★ 不會 |
| 設定複雜度 | 低 | 中（syslog、NTP、SNMP 都要指定 routing-instance） |

> [!warning] ★★★★ 未實機驗證，且啟用後會斷線
> `set system management-instance` **會把管理埠搬進另一個 VRF**，
> commit 的那一刻既有的管理連線會中斷，而且原本的 `routing-options static route`
> 對它不再有效。
> ★★★★★ **只在 console 前面或有另一條可用路徑時才做這個變更**，
> 並且要同步調整 `syslog`／`ntp`／`snmp`／`tacplus-server` 的 `routing-instance` 設定，
> 否則這些服務會全部送不出去。支援情況與設定細節請查該機型的 Junos 版本文件。

本篇主線採**不使用 `management-instance`** 的簡單做法（多數機關的 EX 交換器適用），
並在需要時註明差異。

### Routing Engine 與 Packet Forwarding Engine ★★★★

理解 `lo0` filter 為什麼有效，要先知道 JunOS 的兩顆大腦：

```text
   ┌─────────────────────────────────────────────────────┐
   │  Routing Engine（RE）—— 控制平面                     │
   │  跑 Junos、CLI、SSH、SNMP、路由協定、syslog          │
   │  ★★★★★ 效能有限，被打就整台設備管不動              │
   └────────────────────┬────────────────────────────────┘
                        │ 內部通道
   ┌────────────────────▼────────────────────────────────┐
   │  Packet Forwarding Engine（PFE）—— 轉發平面          │
   │  ASIC 硬體轉發，線速                                  │
   │  一般使用者流量「只經過這裡」，不打擾 RE             │
   └─────────────────────────────────────────────────────┘

   哪些封包會被送上 RE？
   ★★★★★ 目的地是「設備自己的任一個 IP」的封包 ——
   SSH、SNMP、ping 設備、路由協定、以及…… 攻擊者的掃描與洪水
```

★★★★★ **`lo0` 上的 input filter 就是「上 RE 的總關卡」**。
不管封包從 `ge-0/0/1`、`irb.99` 還是 `me0` 進來，只要目的地是設備本身，就必須通過它。
這是 Juniper 保護控制平面的標準做法，等同 Cisco 的 CoPP（Control Plane Policing）。

> [!danger] ★★★★★ `lo0` filter 是本手冊最危險的一個設定
> JunOS 的 firewall filter **結尾有隱含的 deny**（沒有任何 term 命中就丟棄）。
> 也就是說：**只要你漏掉一個必要的協定，那個功能就立刻停止運作**，而且沒有警告。
> 最常見的兩種災難：
> 1. ★★★★★ 忘記放行自己的來源 IP 的 SSH → **commit 那一秒你就被踢出去，再也連不回來**
> 2. ★★★★★ 忘記放行 OSPF／VRRP／BFD／DHCP → 路由鄰居掉光、閘道漂移、整棟樓斷網
>
> **鐵律：`lo0` filter 的任何變更，一律 `commit confirmed 10`，而且最好人在 console 前面。**

## 環境準備與安裝

延續 06 篇的拓樸，管理面規劃如下：

```text
VLAN 99  MGMT      10.99.0.0/24    設備管理（帶內）
                   10.99.0.1       閘道（核心 irb.99 或防火牆）
                   10.99.0.11      acc-3f-ex2300
                   10.99.0.12      acc-4f-ex2300
                   10.99.0.20      syslog 伺服器
                   10.99.0.30/31   NTP + DNS
                   10.99.0.40      RADIUS
                   10.99.1.0/24    管理站網段（網管人員的電腦）
```

### 步驟 1：主機名稱、時區、DNS ★★★★

```text
netadmin@sw> configure exclusive
Entering configuration mode

[edit]
netadmin@sw# set system host-name acc-3f-ex2300
[edit]
netadmin@sw# set system domain-name net.example.gov.tw
[edit]
netadmin@sw# set system time-zone Asia/Taipei
[edit]
netadmin@sw# set system name-server 10.99.0.30
[edit]
netadmin@sw# set system name-server 10.99.0.31
```

★★★★★ **主機名稱要有規則且能定位**。`acc-3f-ex2300` 一眼看得出「接取層／三樓／EX2300」。
`switch1`、`sw-new`、`test` 這種名字三年後沒有人知道它在哪裡。
命名規範建議寫進 [[040-01-18-guide-網路設備-網路設備盤點與文件化]]。

★★★★ `set system time-zone Asia/Taipei` 一定要設。時區錯誤會讓 syslog 的時間對不上，
資安事件調查時「這兩台設備的時間差八小時」是很常見的痛。

### 步驟 2：NTP —— 時間對不上的日誌等於沒有日誌 ★★★★★

```text
[edit]
netadmin@sw# set system ntp server 10.99.0.30
[edit]
netadmin@sw# set system ntp server 10.99.0.31
[edit]
netadmin@sw# set system ntp boot-server 10.99.0.30
```

★★★★ `boot-server` 是開機時用來**強制對時**的（`ntpdate` 行為）。
沒設的話設備開機後時間可能差很多，而 NTP 的漸進校時要很久才會追上。

```text
netadmin@sw> show ntp associations
     remote           refid      st t when poll reach   delay   offset  jitter
==============================================================================
*10.99.0.30      118.163.81.61    2 -   41   64  377    0.412   -0.083   0.041
+10.99.0.31      118.163.81.62    2 -   38   64  377    0.398    0.127   0.055

netadmin@sw> show system uptime | match "Current time|Time Source"
Current time: 2026-09-02 15:12:07 CST
Time Source:  NTP CLOCK
```

★★★★★ 三個判讀重點：
- `remote` 前面的 **`*`** 代表目前選用的來源，**`+`** 是候選。★★★★ 兩個都沒有符號 = 沒對到時間
- `reach` 是八進位的可達性歷史，**`377` 代表最近八次都成功**
- `Time Source: NTP CLOCK` ★★★★ 若顯示 `LOCAL CLOCK` 就是完全沒對到

## 基礎設定

身分與時間就緒之後，接下來是管理面的三根支柱：**位址、帳號、服務**。

### 步驟 3：帶內管理 IP（`irb`）★★★★★

★★★★ 前提：VLAN 99 已經建好，且上聯 trunk 有帶 MGMT（見 06 篇）。

```text
[edit]
netadmin@sw# set vlans MGMT vlan-id 99
[edit]
netadmin@sw# set vlans MGMT description "設備管理專用，勿接終端"
[edit]
netadmin@sw# set interfaces irb unit 99 description "MGMT in-band"
[edit]
netadmin@sw# set interfaces irb unit 99 family inet address 10.99.0.11/24
[edit]
netadmin@sw# set vlans MGMT l3-interface irb.99
[edit]
netadmin@sw# set routing-options static route 0.0.0.0/0 next-hop 10.99.0.1
[edit]
netadmin@sw# set routing-options static route 0.0.0.0/0 retain no-readvertise
```

| 設定 | 意義 | 星級 |
| --- | --- | --- |
| `irb unit 99` | 對應 VLAN 99（★★★★ unit 編號用 vlan-id 是慣例） | ★★★★ |
| `family inet address 10.99.0.11/24` | 管理 IP 與遮罩 | ★★★★★ |
| `l3-interface irb.99` | 把 VLAN 綁到這個三層介面 | ★★★★★ |
| `static route 0.0.0.0/0 next-hop` | ★★★★★ 沒有它，只能從同網段管理 | ★★★★★ |
| `retain` | ★★★ Junos 重啟或 rpd 掛掉時保留這條路由 | ★★★ |
| `no-readvertise` | ★★★ 防止這條管理用預設路由被重分佈到 OSPF／BGP | ★★★ |

```text
[edit]
netadmin@sw# commit confirmed 10 comment "CR-xxxx 設定管理 IP"
commit confirmed will be automatically rolled back in 10 minutes unless confirmed
commit complete

[edit]
netadmin@sw# run show interfaces terse irb.99
Interface               Admin Link Proto    Local                 Remote
irb.99                  up    up   inet     10.99.0.11/24

[edit]
netadmin@sw# run show route 0.0.0.0/0
inet.0: 6 destinations, 6 routes (6 active, 0 holddown, 0 hidden)
+ = Active Route, - = Last Active, * = Both

0.0.0.0/0          *[Static/5] 00:00:41
                    >  to 10.99.0.1 via irb.99

[edit]
netadmin@sw# run ping 10.99.0.1 count 3
PING 10.99.0.1 (10.99.0.1): 56 data bytes
64 bytes from 10.99.0.1: icmp_seq=0 ttl=64 time=0.611 ms
64 bytes from 10.99.0.1: icmp_seq=1 ttl=64 time=0.492 ms
64 bytes from 10.99.0.1: icmp_seq=2 ttl=64 time=0.503 ms

--- 10.99.0.1 ping statistics ---
3 packets transmitted, 3 packets received, 0% packet loss
```

★★★★ `irb.99` 是 `up up`（VLAN 99 至少有一個 up 的成員 —— 上聯 trunk 就算）、
路由表有預設路由、ping 得到閘道 —— 三項都過才 `commit` 確認。

> [!info]- 非 ELS 機種的帶內管理 IP
> ```junos
> set vlans mgmt vlan-id 99
> set vlans mgmt l3-interface vlan.99        ## ★★★★★ 不是 irb
> set interfaces vlan unit 99 family inet address 10.99.0.11/24
> set routing-options static route 0.0.0.0/0 next-hop 10.99.0.1
> ```
> 驗證用 `show interfaces terse vlan.99`。其餘概念完全相同。

### 步驟 4：帶外管理 IP（`me0`）★★★★

```text
[edit]
netadmin@sw# set interfaces me0 description "OOB management to mgmt-switch ge-0/0/3"
[edit]
netadmin@sw# set interfaces me0 unit 0 family inet address 10.98.0.11/24
```

```text
[edit]
netadmin@sw# run show interfaces terse me0
Interface               Admin Link Proto    Local                 Remote
me0                     up    up
me0.0                   up    up   inet     10.98.0.11/24
```

★★★★ **帶外網段建議與帶內管理網段分開**（本例 10.98.0.0/24 vs 10.99.0.0/24）。
兩個網段用同一個號碼會造成路由混亂，而且失去「兩條獨立路徑」的意義。

★★★★★ **帶外管理沒有預設路由怎麼辦？** 三個選項：

| 做法 | 說明 | 星級 |
| --- | --- | --- |
| 管理站與設備**同網段** | 最單純，管理交換器就是一個扁平網段 | ★★★★★ 推薦 |
| 加一條指向帶外閘道的路由 | ★★★★★ **會跟帶內的預設路由打架**，要用不同 metric 或改用 `management-instance` | ★★ |
| 用 `set system management-instance` | 帶外走獨立 VRF，最乾淨 | ★★★ 版本／機型限制 |

> [!warning] ★★★★★ 帶內與帶外都設預設路由 = 兩條 0.0.0.0/0 打架
> Junos 只會選一條 active。你以為管理流量走帶外，其實走帶內（或反過來），
> 而且**在你改壞帶內時才會發現帶外根本沒通** —— 那正好是你最需要它的時候。
> 檢查方式：`show route 0.0.0.0/0` 只會有一條帶 `*`。
> 正解是帶外管理站與設備同網段（不需要路由），或用 `management-instance`。

### 步驟 5：root 密碼與個人帳號 ★★★★★

```text
[edit]
netadmin@sw# set system root-authentication plain-text-password
New password:
Retype new password:
```

★★★★★ **`plain-text-password` 是「用互動方式輸入」，不是「明文儲存」** ——
輸入後 JunOS 會存成雜湊：

```text
[edit]
netadmin@sw# show system root-authentication
encrypted-password "$6$Kx8vQ2mN$3fJz...省略...9pQ2"; ## SECRET-DATA
```

★★★★ 想直接貼雜湊（例如從標準範本派送）可以用：

```junos
set system root-authentication encrypted-password "$6$Kx8vQ2mN$3fJz...9pQ2"
```

★★★★★ 也可以（而且建議）給 root 加 SSH 金鑰，但**仍然要設密碼** ——
console 登入需要密碼，而 console 是你最後的救命管道：

```junos
set system root-authentication ssh-ed25519 "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... netadmin@mgmt"
```

建立個人帳號：

```text
[edit]
netadmin@sw# set system login user netadmin full-name "網路管理員 王大明"
[edit]
netadmin@sw# set system login user netadmin uid 2001
[edit]
netadmin@sw# set system login user netadmin class super-user
[edit]
netadmin@sw# set system login user netadmin authentication ssh-ed25519 "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... wang@mgmt"
[edit]
netadmin@sw# set system login user netadmin authentication plain-text-password
New password:
Retype new password:
```

> [!danger] ★★★★★ 共用 root 帳號 = 沒有稽核軌跡
> `show system commit` 全部顯示 `by root` 的話，你永遠查不出是誰改的。
> 機關資安基準幾乎都要求「可識別個人的帳號」。標準做法：
> 1. ★★★★★ 每個維運人員一個帳號，`full-name` 寫真實姓名
> 2. ★★★★★ `set system services ssh root-login deny` 禁止 root 直接 SSH
> 3. ★★★★ root 密碼封存（信封簽章、保險櫃），只在 console 救援時用
> 4. ★★★★ 人員異動時第一時間 `delete system login user <帳號>`
> 5. ★★★ 更好的做法是接 RADIUS／TACACS+ 集中認證（見「進階設定與調校」）

### 步驟 6：SSH 與關掉不該開的服務 ★★★★★

```text
[edit]
netadmin@sw# set system services ssh root-login deny
[edit]
netadmin@sw# set system services ssh protocol-version v2
[edit]
netadmin@sw# set system services ssh connection-limit 10
[edit]
netadmin@sw# set system services ssh rate-limit 4
[edit]
netadmin@sw# set system services ssh client-alive-interval 300
[edit]
netadmin@sw# set system services ssh client-alive-count-max 3
[edit]
netadmin@sw# delete system services telnet
[edit]
netadmin@sw# delete system services web-management
[edit]
netadmin@sw# delete system services ftp
```

| 設定 | 意義 | 星級 |
| --- | --- | --- |
| `root-login deny` | ★★★★★ 禁止 root 直接 SSH（`deny-password` 是「只准金鑰」） | ★★★★★ |
| `protocol-version v2` | 只用 SSHv2（v1 早已破解） | ★★★★ |
| `connection-limit 10` | 同時最多 10 條 SSH 連線 | ★★★★ |
| `rate-limit 4` | 每分鐘最多 4 次連線嘗試，★★★★ 擋暴力破解 | ★★★★ |
| `client-alive-interval 300` | 每 300 秒送一次保活探測 | ★★★ |
| `client-alive-count-max 3` | 連續 3 次沒回應就斷（清掉殭屍 session） | ★★★ |
| `no-passwords` | ★★★★★ **只准金鑰登入**（見下方警告） | ★★★★ |
| `delete system services telnet` | ★★★★★ Telnet 帳密明文傳輸，必關 | ★★★★★ |
| `delete system services web-management` | ★★★★★ J-Web 歷年多個高風險 CVE，不用就關 | ★★★★★ |
| `delete system services ftp` | 明文，改用 SCP | ★★★★ |

> [!danger] ★★★★★ `set system services ssh no-passwords` 之前，先確認金鑰真的能登入
> 這個設定會**關掉所有密碼認證**。如果你的公鑰貼錯一個字元、格式不對、
> 或貼到了別的帳號底下，commit 之後**沒有任何人能用 SSH 登入**（只剩 console）。
> 正確順序：
> 1. 先設好 `authentication ssh-ed25519 "..."` 並 `commit`
> 2. ★★★★★ **另開一個視窗實測金鑰登入成功**
> 3. 確認成功後才加 `no-passwords`，且用 `commit confirmed 10`
> 4. 用第三個視窗再測一次，確認後才 `commit`
>
> 同樣的邏輯與 [[020-02-01-04-svc-sshd-伺服器端設定]] 的「不鎖門 SOP」完全一致。

```text
[edit]
netadmin@sw# show system services
ssh {
    root-login deny;
    protocol-version v2;
    connection-limit 10;
    rate-limit 4;
    client-alive-interval 300;
    client-alive-count-max 3;
}
netconf {
    ssh;
}
```

★★★ `netconf ssh` 建議保留 —— 自動化備份與組態管理工具（Ansible、Salt、
[[020-02-03-05-svc-標準化-自動化佈建入門]]）需要它，而且它走的是同一條加密的 SSH 通道。

### 步驟 7：登入警語與登入失敗鎖定 ★★★★

```text
[edit]
netadmin@sw# set system login message "本設備為 XX 機關資產，僅限授權人員使用。\n所有操作均記錄於稽核日誌。\n"
[edit]
netadmin@sw# set system login announcement "acc-3f-ex2300 / 3F 接取層 / 維運窗口分機 1234\n"
[edit]
netadmin@sw# set system login retry-options tries-before-disconnect 3
[edit]
netadmin@sw# set system login retry-options backoff-threshold 2
[edit]
netadmin@sw# set system login retry-options backoff-factor 5
[edit]
netadmin@sw# set system login retry-options lockout-period 5
```

| 設定 | 意義 | 星級 |
| --- | --- | --- |
| `login message` | ★★★★ **登入前**顯示（法律警語，稽核必要項目） | ★★★★ |
| `login announcement` | 登入**後**顯示（設備用途、聯絡窗口） | ★★★ |
| `tries-before-disconnect 3` | 密碼錯 3 次就切斷連線 | ★★★★ |
| `backoff-threshold 2` | 錯 2 次之後開始延遲 | ★★★ |
| `backoff-factor 5` | 每多錯一次多等 5 秒 | ★★★ |
| `lockout-period 5` | ★★★★ 觸發後鎖定該帳號 5 分鐘 | ★★★★ |

★★★★ 密碼政策（機關常見要求，實際值依貴單位資安規定）：

```junos
set system login password minimum-length 12
set system login password format sha512
set system login password change-type character-sets
set system login password minimum-character-changes 4
```

> [!warning] ★★★ 未實機驗證
> `password` 底下可用的子選項（`minimum-numerics`、`minimum-upper-cases`、
> `maximum-length` 等）依 Junos 版本而異。導入 TWGCB 或機關基準前，
> 請用 `set system login password ?` 確認該版本支援哪些項目，
> 並對照 [[090-06-04-guide-TWGCB-Linux本機導入]] 的作法建立設備類的基準表。

### 步驟 8：syslog —— 稽核軌跡的來源 ★★★★★

```text
[edit]
netadmin@sw# set system syslog host 10.99.0.20 any notice
[edit]
netadmin@sw# set system syslog host 10.99.0.20 authorization info
[edit]
netadmin@sw# set system syslog host 10.99.0.20 interactive-commands any
[edit]
netadmin@sw# set system syslog host 10.99.0.20 source-address 10.99.0.11
[edit]
netadmin@sw# set system syslog file messages any notice
[edit]
netadmin@sw# set system syslog file messages authorization info
[edit]
netadmin@sw# set system syslog file messages archive size 1m files 10
[edit]
netadmin@sw# set system syslog file cli-audit interactive-commands any
[edit]
netadmin@sw# set system syslog file cli-audit archive size 1m files 10
```

★★★★★ **`interactive-commands any` 是整段設定裡最重要的一行。**
它會記錄**每一個人打的每一條 CLI 指令**：

```text
netadmin@sw> show log cli-audit | last 8
Sep  2 15:41:02  acc-3f-ex2300 mgd[4412]: UI_CMDLINE_READ_LINE: User 'netadmin', command 'configure exclusive '
Sep  2 15:41:15  acc-3f-ex2300 mgd[4412]: UI_CMDLINE_READ_LINE: User 'netadmin', command 'set interfaces ge-0/0/10 disable '
Sep  2 15:41:22  acc-3f-ex2300 mgd[4412]: UI_CMDLINE_READ_LINE: User 'netadmin', command 'show | compare '
Sep  2 15:41:35  acc-3f-ex2300 mgd[4412]: UI_CMDLINE_READ_LINE: User 'netadmin', command 'commit confirmed 5 '
Sep  2 15:41:35  acc-3f-ex2300 mgd[4412]: UI_COMMIT: User 'netadmin' requested 'commit confirmed' operation (comment: none)
```

★★★★★ **這是「誰在什麼時候做了什麼」唯一完整的紀錄**，也是資安事件調查與稽核的核心證據。
`show system commit` 只記錄 commit，`cli-audit` 連「看了什麼」都記得。

★★★★ **一定要同時送到外部 syslog 伺服器**：設備本機的日誌在設備被入侵或故障時就沒了。
集中日誌的架設見 [[100-01-02-guide-日誌-日誌集中與輪替]]。

| syslog facility | 記什麼 | 星級 |
| --- | --- | --- |
| `any notice` | 一般系統訊息（介面 up/down、commit、告警） | ★★★★ |
| `authorization info` | ★★★★★ 登入成功／失敗、認證事件 | ★★★★★ |
| `interactive-commands any` | ★★★★★ 每一條 CLI 指令 | ★★★★★ |
| `change-log info` | 設定變更的細節 | ★★★★ |
| `daemon info` | 各服務程序訊息 | ★★★ |
| `kernel info` | 核心訊息 | ★★ |
| `pfe info` | 轉發平面訊息 | ★★ |

## 進階設定與調校

### `system login class` —— 讓值班人員只能看不能改 ★★★★★

JunOS 內建四個 class：

| class | 權限 | 適用 |
| --- | --- | --- |
| `super-user` | ★★★★★ 全部（等同 root） | 網路管理員 |
| `operator` | `clear` `network` `reset` `trace` `view` | 可執行操作但看不到設定 |
| `read-only` | `view` | 只能看狀態 |
| `unauthorized` | 無 | 停用中的帳號 |

★★★★ 內建的 class 常常不夠用。例如「值班人員可以看設定、可以 ping／traceroute，
但不能改設定、不能重開機」—— 這要自訂：

```junos
set system login class NOC permissions [ view view-configuration ]
set system login class NOC allow-commands "^(show|ping|traceroute|monitor|test|help|set cli)"
set system login class NOC deny-commands "^(request|start shell|file|clear ethernet-switching table|configure)"
set system login class NOC idle-timeout 15
set system login class NOC login-alarms

set system login user duty01 full-name "值班人員 A"
set system login user duty01 class NOC
set system login user duty01 authentication plain-text-password
```

| 設定 | 意義 | 星級 |
| --- | --- | --- |
| `permissions [ view view-configuration ]` | ★★★★ 可看狀態與設定，不可修改 | ★★★★ |
| `allow-commands "<regex>"` | 白名單（正規表示式） | ★★★★ |
| `deny-commands "<regex>"` | ★★★★★ 黑名單，**優先於 allow** | ★★★★★ |
| `idle-timeout 15` | ★★★★ 15 分鐘閒置自動登出（稽核常見要求） | ★★★★ |
| `allow-configuration` / `deny-configuration` | 限制可以改哪些設定階層 | ★★★ |
| `login-alarms` | 登入時顯示目前的系統告警 | ★★★ |

> [!warning] ★★★★ `allow-commands` / `deny-commands` 是正規表示式，很容易寫漏
> 常見錯誤是 `deny-commands "request"` —— 這會擋掉**任何含有 request 的指令**，
> 包含 `show ... | match request`。加上 `^` 錨定開頭比較安全。
> ★★★★★ **每次改完一定要用該帳號實際登入測試**，確認：
> (a) 該擋的擋住了 (b) 該給的權限還在。
> 只看設定檔是驗不出正規表示式的漏洞的。

驗證方式：

```text
duty01@sw> configure
                ^
unknown command.

duty01@sw> show configuration interfaces ge-0/0/1
description "3F-A12 王小明 PC";
unit 0 {
    family ethernet-switching {
        interface-mode access;
        vlan {
            members OFFICE;
        }
    }
}

duty01@sw> request system reboot
                ^
unknown command.
```

### 保護 Routing Engine 的 `lo0` firewall filter ★★★★★

> [!danger] ★★★★★ 這一節的每一次 commit 都必須是 `commit confirmed`
> 寫錯就是立刻斷線、路由協定掉光。**強烈建議第一次在測試設備上做，或人在 console 前面。**

**第一步：定義允許的來源（prefix-list）**

```junos
set policy-options prefix-list MGMT-HOSTS 10.99.1.0/24
set policy-options prefix-list MGMT-HOSTS 10.99.0.20/32
set policy-options prefix-list MGMT-HOSTS 10.99.0.30/32
set policy-options prefix-list LOCAL-SUBNETS 10.99.0.0/24
set policy-options prefix-list NTP-SERVERS 10.99.0.30/32
set policy-options prefix-list NTP-SERVERS 10.99.0.31/32
```

★★★★ 用 prefix-list 而不是把 IP 寫死在 filter 裡：日後增減管理站只要改一個地方。

**第二步：寫 filter（★★★★★ term 的順序就是比對順序，第一個命中就結束）**

```junos
## ── 管理協定：只准管理網段 ──
set firewall family inet filter PROTECT-RE term MGMT-SSH from source-prefix-list MGMT-HOSTS
set firewall family inet filter PROTECT-RE term MGMT-SSH from protocol tcp
set firewall family inet filter PROTECT-RE term MGMT-SSH from destination-port ssh
set firewall family inet filter PROTECT-RE term MGMT-SSH then count re-ssh-accept
set firewall family inet filter PROTECT-RE term MGMT-SSH then accept

set firewall family inet filter PROTECT-RE term MGMT-SNMP from source-prefix-list MGMT-HOSTS
set firewall family inet filter PROTECT-RE term MGMT-SNMP from protocol udp
set firewall family inet filter PROTECT-RE term MGMT-SNMP from destination-port snmp
set firewall family inet filter PROTECT-RE term MGMT-SNMP then accept

## ── 其他來源想連 SSH／SNMP：記錄並丟棄 ──
set firewall family inet filter PROTECT-RE term DENY-MGMT from protocol tcp
set firewall family inet filter PROTECT-RE term DENY-MGMT from protocol udp
set firewall family inet filter PROTECT-RE term DENY-MGMT from destination-port ssh
set firewall family inet filter PROTECT-RE term DENY-MGMT from destination-port telnet
set firewall family inet filter PROTECT-RE term DENY-MGMT from destination-port snmp
set firewall family inet filter PROTECT-RE term DENY-MGMT then count re-mgmt-deny
set firewall family inet filter PROTECT-RE term DENY-MGMT then log
set firewall family inet filter PROTECT-RE term DENY-MGMT then discard

## ── 基礎服務：一定要放行，否則設備自己會壞 ──
set firewall family inet filter PROTECT-RE term NTP from source-prefix-list NTP-SERVERS
set firewall family inet filter PROTECT-RE term NTP from protocol udp
set firewall family inet filter PROTECT-RE term NTP from port ntp
set firewall family inet filter PROTECT-RE term NTP then accept

set firewall family inet filter PROTECT-RE term DNS-REPLY from protocol udp
set firewall family inet filter PROTECT-RE term DNS-REPLY from source-port domain
set firewall family inet filter PROTECT-RE term DNS-REPLY then accept

set firewall family inet filter PROTECT-RE term DHCP from protocol udp
set firewall family inet filter PROTECT-RE term DHCP from destination-port [ 67 68 ]
set firewall family inet filter PROTECT-RE term DHCP then accept

## ── ICMP：限速放行，方便排錯又不怕被 ping flood ──
set firewall policer ICMP-POLICER if-exceeding bandwidth-limit 1m
set firewall policer ICMP-POLICER if-exceeding burst-size-limit 15k
set firewall policer ICMP-POLICER then discard
set firewall family inet filter PROTECT-RE term ICMP from protocol icmp
set firewall family inet filter PROTECT-RE term ICMP then policer ICMP-POLICER
set firewall family inet filter PROTECT-RE term ICMP then accept

## ── 設備自己發起的連線，其回應要能回來 ──
set firewall family inet filter PROTECT-RE term ESTABLISHED from protocol tcp
set firewall family inet filter PROTECT-RE term ESTABLISHED from tcp-established
set firewall family inet filter PROTECT-RE term ESTABLISHED then accept

## ── 最後：記錄並丟棄其餘一切 ──
set firewall family inet filter PROTECT-RE term DEFAULT-DENY then count re-default-deny
set firewall family inet filter PROTECT-RE term DEFAULT-DENY then log
set firewall family inet filter PROTECT-RE term DEFAULT-DENY then discard
```

**第三步：套用（★★★★★ 這一步才會生效，也是危險的那一步）**

```text
[edit]
netadmin@sw# set interfaces lo0 unit 0 family inet filter input PROTECT-RE
[edit]
netadmin@sw# show | compare
[edit interfaces lo0 unit 0 family inet]
+    filter {
+        input PROTECT-RE;
+    }
[edit]
netadmin@sw# commit confirmed 10 comment "CR-xxxx 套用 RE 保護 filter"
commit confirmed will be automatically rolled back in 10 minutes unless confirmed
commit complete
```

**第四步：立刻驗證（★★★★★ 時間在跑）**

```text
[edit]
netadmin@sw# run show firewall filter PROTECT-RE
Filter: PROTECT-RE
Counters:
Name                                                Bytes              Packets
re-default-deny                                      2418                   31
re-mgmt-deny                                            0                    0
re-ssh-accept                                       48211                  312
```

★★★★★ 判讀：
- `re-ssh-accept` 有在增加 → **你的連線是被 accept 的**（安全）
- `re-mgmt-deny` 突然暴增 → 有你沒想到的來源在連管理埠，**先確認不是監控系統**
- `re-default-deny` 一直暴增 → ★★★★★ **你漏放行了某個必要協定**，趕快看 log

```text
[edit]
netadmin@sw# run show log messages | match "PROTECT-RE" | last 10
Sep  2 16:03:12  acc-3f-ex2300 fpc0 PFE_FW_SYSLOG_IP: FW: lo0.0   D   ospf 10.99.0.1  224.0.0.5  0  0 (1 packets)
```

★★★★★ **看到 OSPF 被丟棄就要立刻 `rollback 1` + `commit`** —— 再等下去路由鄰居就掉了。

★★★★ 另外開一個新的 SSH 連線測試（**不要只靠現有連線**，`tcp-established` 可能讓舊連線繼續活著
而新連線其實已經被擋）：

```text
$ ssh netadmin@10.99.0.11
netadmin@10.99.0.11's password:
--- JUNOS 21.4R3-S5.4 ...
netadmin@acc-3f-ex2300>
```

**第五步：確認**

```text
[edit]
netadmin@sw# commit comment "CR-xxxx RE filter 驗證通過"
commit complete
```

> [!danger] ★★★★★ 部署 `lo0` filter 前，先列出這台設備「需要哪些協定」
> 漏掉任何一項就是斷線或功能停擺。至少要盤點：
>
> | 協定 | 何時需要 | 漏掉的後果 |
> | --- | --- | --- |
> | SSH（tcp/22） | ★★★★★ 永遠 | 你被鎖在門外 |
> | ICMP | ★★★★ 排錯 | ping 不到設備，監控報警 |
> | NTP（udp/123） | ★★★★ 對時 | 時間漂移，日誌時間錯亂 |
> | DNS 回應（udp/53 source） | ★★★ 設備做名稱解析 | `ping google.com` 失敗 |
> | SNMP（udp/161） | ★★★★ 監控 | 監控系統全紅 |
> | syslog（udp/514 **出去**） | ★★★★ 送日誌 | 出方向不受 input filter 管，通常沒事 |
> | OSPF（ip proto 89 / 224.0.0.5-6） | ★★★★★ 有跑動態路由時 | **鄰居掉光、路由全失** |
> | BGP（tcp/179） | ★★★★★ 有跑 BGP 時 | 同上 |
> | VRRP（ip proto 112 / 224.0.0.18） | ★★★★★ 有做閘道冗餘時 | **閘道漂移或雙 master** |
> | BFD（udp/3784-3785） | ★★★★ 有用快速偵測時 | 鄰居誤判為 down |
> | DHCP（udp/67,68） | ★★★★ 有做 relay 時 | 使用者拿不到 IP |
> | LLDP／STP | ★★★★ 二層協定 | ★★★ 這些是 L2，**不經過 `lo0` inet filter** |
> | TACACS+／RADIUS 回應 | ★★★★ 集中認證 | **所有人都登不進來** |
> | NETCONF（tcp/830） | ★★★ 自動化 | 備份與組態管理失敗 |
>
> ★★★★ 起步建議：**先只寫 `then count` 與 `then accept`（不 discard）跑一週**，
> 看計數器確認每個 term 都有命中、`DEFAULT-DENY` 的計數是不是有非預期流量，
> 再把 `DEFAULT-DENY` 改成 `discard`。

### RADIUS／TACACS+ 集中認證 ★★★★

```junos
set system radius-server 10.99.0.40 secret "請改成你們的共用密鑰"
set system radius-server 10.99.0.40 source-address 10.99.0.11
set system radius-server 10.99.0.40 timeout 5
set system radius-server 10.99.0.40 retry 3
set system radius-server 10.99.0.41 secret "請改成你們的共用密鑰"
set system radius-server 10.99.0.41 source-address 10.99.0.11

set system authentication-order [ radius password ]

## ★★★★★ 特殊帳號 remote：RADIUS 認證成功但本機沒有對應帳號時套用的樣板
set system login user remote full-name "RADIUS template account"
set system login user remote class read-only
```

| 設定 | 意義 | 星級 |
| --- | --- | --- |
| `authentication-order [ radius password ]` | ★★★★★ 先問 RADIUS，再退回本機密碼 | ★★★★★ |
| `authentication-order radius`（只有一個） | ★★★★★ 只問 RADIUS；**伺服器沒回應時仍會退回本機密碼**，但被明確拒絕時不會 | ★★★★★ |
| `user remote` | ★★★★ RADIUS 通過但本機無此帳號時，套用這個帳號的 class | ★★★★ |
| `source-address` | ★★★★ 固定來源 IP，RADIUS 端的用戶端清單才好設 | ★★★★ |
| TACACS+ 版本 | `set system tacplus-server 10.99.0.41 secret "..."` | ★★★ |
| 記帳 | `set system accounting events [ login change-log interactive-commands ]` + `set system accounting destination tacplus` | ★★★★ |

> [!danger] ★★★★★ 接上集中認證之後，本機帳號千萬不要刪
> RADIUS／TACACS+ 伺服器掛掉、網路斷掉、或共用密鑰打錯的時候，
> **本機帳號是你唯一進得去的方式**。
> `authentication-order [ radius password ]` 裡那個 `password` 就是這個保險。
> ★★★★ 對應的作業規定：本機保留一個「緊急帳號」，密碼封存、定期更換、
> 使用時必須事後報備。這也是機關資安稽核會問的題目。

> [!warning] ★★★★ 未實機驗證
> Junos 在「RADIUS 伺服器無回應」與「RADIUS 明確拒絕」兩種情況下的 fallback 行為
> 依版本有細微差異。**導入前務必實測**：
> (a) 把 RADIUS 伺服器關掉，確認本機帳號還登得進去
> (b) 用錯誤密碼測 RADIUS 拒絕的情形，確認行為符合預期

### SNMP 監控接入 ★★★

```junos
## SNMPv2c（★★★ community 明文傳輸，只能在受控管理網段用）
set snmp location "3F 弱電間 A 機櫃"
set snmp contact "資訊室 分機 1234"
set snmp community <請改成隨機字串> authorization read-only
set snmp community <請改成隨機字串> clients 10.99.0.20/32
set snmp community <請改成隨機字串> clients 0.0.0.0/0 restrict
```

★★★★★ 那行 `clients 0.0.0.0/0 restrict` 是**必要的**：它明確拒絕其他來源。
沒有它，只寫 allow 清單在某些版本上不會產生預期的拒絕行為。

```junos
## SNMPv3（★★★★ 有認證與加密，建議用這個）
set snmp v3 usm local-engine user monitor authentication-sha authentication-password "請改成強密碼"
set snmp v3 usm local-engine user monitor privacy-aes128 privacy-password "請改成強密碼"
set snmp v3 vacm security-to-group security-model usm security-name monitor group RO-GROUP
set snmp v3 vacm access group RO-GROUP default-context-prefix security-model usm security-level privacy read-view all-view
set snmp view all-view oid .1 include
```

★★★★★ **SNMPv2c 的 community 等同明文密碼**，而且很多機關還在用 `public`／`private`。
稽核抽查一定會抓。監控系統的完整規劃見
[[100-01-03-guide-日誌-系統監控與告警]]。

> [!info]- Cisco IOS 對照（簡表，完整內容見 [[040-01-12-guide-Cisco-管理IP與遠端存取]]）
> | 目的 | JunOS | Cisco IOS |
> | --- | --- | --- |
> | 帶內管理 IP | `set int irb unit 99 family inet address 10.99.0.11/24` | `interface Vlan99` + `ip address 10.99.0.11 255.255.255.0` |
> | 帶外管理埠 | `set int me0 unit 0 family inet address ...` | `interface GigabitEthernet0/0` + `vrf forwarding Mgmt-vrf` |
> | 預設路由 | `set routing-options static route 0.0.0.0/0 next-hop X` | `ip default-gateway X` 或 `ip route 0.0.0.0 0.0.0.0 X` |
> | 主機名稱 | `set system host-name X` | `hostname X` |
> | 建帳號 | `set system login user U class super-user` | `username U privilege 15 secret ...` |
> | 權限分級 | `class` + `permissions` + `allow/deny-commands` | privilege level 0-15 + `privilege exec level` |
> | 啟用 SSH | `set system services ssh`（★★★ 不需產生金鑰） | `crypto key generate rsa` + `ip ssh version 2` + `transport input ssh` |
> | 禁 root SSH | `set system services ssh root-login deny` | `no ip http server` 等 + AAA 設計 |
> | 關 Telnet | `delete system services telnet` | `line vty 0 15` + `transport input ssh` |
> | 保護控制平面 | ★★★★★ `lo0` input filter | ★★★★★ CoPP（`control-plane` + service-policy） |
> | 登入警語 | `set system login message "..."` | `banner login ^...^` |
> | 稽核每條指令 | `set system syslog ... interactive-commands any` | `archive` + `log config` + `logging enable` |
> | NTP | `set system ntp server X` | `ntp server X` |
> | 集中認證 | `set system authentication-order [ radius password ]` | `aaa new-model` + `aaa authentication login` |
>
> ★★★★★ 最大差異是**控制平面保護**：Cisco 用 CoPP（QoS 政策掛在 `control-plane`），
> JunOS 用 firewall filter 掛在 `lo0`。兩者概念一樣、寫法完全不同，
> **共同點是都極容易把自己鎖在門外**。完整對照見
> [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]]。

## 完整實戰範例

**情境**：一台剛開箱的 EX2300-48T，要從「什麼都沒有」變成「符合機關基準、可遠端管理」。
你人在機房，接著 console 線。做完之後要能從辦公室 SSH 進來。

### 步驟 1：console 登入，確認起點 ★★★★

```text
Amnesiac (ttyu0)

login: root

--- JUNOS 21.4R3-S5.4 Kernel 64-bit
root@:~ # cli
root@> show version | match "Model|Junos:"
Model: ex2300-48t
Junos: 21.4R3-S5.4

root@> show configuration | display set | count
Count: 8 lines
```

★★★★ `Amnesiac` 是 JunOS 對「還沒設 hostname」的稱呼，代表這是一台乾淨的設備。

```text
root@> show interfaces terse | match "me0|em0|fxp0"
me0                     up    down
```

★★★★ 這台用 `me0`，目前沒有 IP、線也沒接。

### 步驟 2：★★★★★ 先設 root 密碼（不設就不能 commit）

```text
root@> configure exclusive
Entering configuration mode

[edit]
root@# set system root-authentication plain-text-password
New password:
Retype new password:

[edit]
root@# set system host-name acc-3f-ex2300
[edit]
root@# set system domain-name net.example.gov.tw
[edit]
root@# set system time-zone Asia/Taipei
[edit]
root@# set system name-server 10.99.0.30
[edit]
root@# set system name-server 10.99.0.31
[edit]
root@# commit comment "基準設定 1/6：身分與時區"
commit complete

[edit]
root@acc-3f-ex2300#
```

★★★★ 提示符號立刻變成新的 hostname —— commit 生效的證據。

### 步驟 3：個人帳號與權限 class ★★★★★

```text
[edit]
root@acc-3f-ex2300# set system login class NOC permissions [ view view-configuration ]
[edit]
root@acc-3f-ex2300# set system login class NOC allow-commands "^(show|ping|traceroute|monitor|help|set cli)"
[edit]
root@acc-3f-ex2300# set system login class NOC deny-commands "^(request|configure|start shell|file)"
[edit]
root@acc-3f-ex2300# set system login class NOC idle-timeout 15

[edit]
root@acc-3f-ex2300# set system login user netadmin full-name "網路管理員 王大明"
[edit]
root@acc-3f-ex2300# set system login user netadmin uid 2001
[edit]
root@acc-3f-ex2300# set system login user netadmin class super-user
[edit]
root@acc-3f-ex2300# set system login user netadmin authentication ssh-ed25519 "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIH8kQ2mZ... wang@mgmt-pc"
[edit]
root@acc-3f-ex2300# set system login user netadmin authentication plain-text-password
New password:
Retype new password:

[edit]
root@acc-3f-ex2300# set system login user duty01 full-name "值班人員 A"
[edit]
root@acc-3f-ex2300# set system login user duty01 uid 2101
[edit]
root@acc-3f-ex2300# set system login user duty01 class NOC
[edit]
root@acc-3f-ex2300# set system login user duty01 authentication plain-text-password
New password:
Retype new password:

[edit]
root@acc-3f-ex2300# commit comment "基準設定 2/6：帳號與權限"
commit complete
```

### 步驟 4：管理 VLAN 與 IP ★★★★★

```text
[edit]
root@acc-3f-ex2300# set vlans MGMT vlan-id 99
[edit]
root@acc-3f-ex2300# set vlans MGMT description "設備管理專用，勿接終端"
[edit]
root@acc-3f-ex2300# set interfaces irb unit 99 description "MGMT in-band 10.99.0.11"
[edit]
root@acc-3f-ex2300# set interfaces irb unit 99 family inet address 10.99.0.11/24
[edit]
root@acc-3f-ex2300# set vlans MGMT l3-interface irb.99
[edit]
root@acc-3f-ex2300# set routing-options static route 0.0.0.0/0 next-hop 10.99.0.1
[edit]
root@acc-3f-ex2300# set routing-options static route 0.0.0.0/0 retain no-readvertise

## 上聯 trunk 要帶 MGMT VLAN，否則管理 IP 出不去
[edit]
root@acc-3f-ex2300# set interfaces ge-0/0/48 description "UPLINK to core-ex4300 ge-0/0/12"
[edit]
root@acc-3f-ex2300# set interfaces ge-0/0/48 native-vlan-id 999
[edit]
root@acc-3f-ex2300# set interfaces ge-0/0/48 unit 0 family ethernet-switching interface-mode trunk
[edit]
root@acc-3f-ex2300# set interfaces ge-0/0/48 unit 0 family ethernet-switching vlan members [ MGMT PARKING ]
[edit]
root@acc-3f-ex2300# set vlans PARKING vlan-id 999

## 帶外管理埠
[edit]
root@acc-3f-ex2300# set interfaces me0 description "OOB to mgmt-switch ge-0/0/3"
[edit]
root@acc-3f-ex2300# set interfaces me0 unit 0 family inet address 10.98.0.11/24

[edit]
root@acc-3f-ex2300# commit comment "基準設定 3/6：管理 IP 與上聯"
commit complete
```

```text
[edit]
root@acc-3f-ex2300# run show interfaces terse | match "irb.99|me0.0"
irb.99                  up    up   inet     10.99.0.11/24
me0.0                   up    up   inet     10.98.0.11/24

[edit]
root@acc-3f-ex2300# run ping 10.99.0.1 count 3
PING 10.99.0.1 (10.99.0.1): 56 data bytes
64 bytes from 10.99.0.1: icmp_seq=0 ttl=64 time=0.702 ms
64 bytes from 10.99.0.1: icmp_seq=1 ttl=64 time=0.488 ms
64 bytes from 10.99.0.1: icmp_seq=2 ttl=64 time=0.501 ms

--- 10.99.0.1 ping statistics ---
3 packets transmitted, 3 packets received, 0% packet loss
```

★★★★★ **在 console 前面就把兩條管理路徑都測通**，這是離開機房前必須完成的事。

### 步驟 5：SSH 與服務加固 ★★★★★

```text
[edit]
root@acc-3f-ex2300# set system services ssh root-login deny
[edit]
root@acc-3f-ex2300# set system services ssh protocol-version v2
[edit]
root@acc-3f-ex2300# set system services ssh connection-limit 10
[edit]
root@acc-3f-ex2300# set system services ssh rate-limit 4
[edit]
root@acc-3f-ex2300# set system services ssh client-alive-interval 300
[edit]
root@acc-3f-ex2300# set system services ssh client-alive-count-max 3
[edit]
root@acc-3f-ex2300# set system services netconf ssh
[edit]
root@acc-3f-ex2300# delete system services telnet
[edit]
root@acc-3f-ex2300# delete system services web-management
[edit]
root@acc-3f-ex2300# set system login message "本設備為 XX 機關資產，僅限授權人員使用。\n所有操作均記錄於稽核日誌。\n"
[edit]
root@acc-3f-ex2300# set system login announcement "acc-3f-ex2300 / 3F 接取層 / 維運窗口分機 1234\n"
[edit]
root@acc-3f-ex2300# set system login retry-options tries-before-disconnect 3
[edit]
root@acc-3f-ex2300# set system login retry-options backoff-threshold 2
[edit]
root@acc-3f-ex2300# set system login retry-options backoff-factor 5
[edit]
root@acc-3f-ex2300# set system login retry-options lockout-period 5
[edit]
root@acc-3f-ex2300# commit comment "基準設定 4/6：SSH 與登入政策"
commit complete
```

**★★★★★ 此時從辦公室實測 SSH（人還在 console 前面，出事馬上救得回來）**：

```text
$ ssh netadmin@10.99.0.11
本設備為 XX 機關資產，僅限授權人員使用。
所有操作均記錄於稽核日誌。

netadmin@10.99.0.11's password:
acc-3f-ex2300 / 3F 接取層 / 維運窗口分機 1234

--- JUNOS 21.4R3-S5.4 ...
netadmin@acc-3f-ex2300>
```

```text
$ ssh root@10.99.0.11
本設備為 XX 機關資產，僅限授權人員使用。
所有操作均記錄於稽核日誌。

root@10.99.0.11's password:
Permission denied, please try again.
```

★★★★★ 個人帳號登得進、root 被拒 —— 這兩件事都要實測。

### 步驟 6：NTP 與 syslog ★★★★

```text
[edit]
root@acc-3f-ex2300# set system ntp server 10.99.0.30
[edit]
root@acc-3f-ex2300# set system ntp server 10.99.0.31
[edit]
root@acc-3f-ex2300# set system ntp boot-server 10.99.0.30
[edit]
root@acc-3f-ex2300# set system syslog host 10.99.0.20 any notice
[edit]
root@acc-3f-ex2300# set system syslog host 10.99.0.20 authorization info
[edit]
root@acc-3f-ex2300# set system syslog host 10.99.0.20 interactive-commands any
[edit]
root@acc-3f-ex2300# set system syslog host 10.99.0.20 source-address 10.99.0.11
[edit]
root@acc-3f-ex2300# set system syslog file messages any notice
[edit]
root@acc-3f-ex2300# set system syslog file messages authorization info
[edit]
root@acc-3f-ex2300# set system syslog file messages archive size 1m files 10
[edit]
root@acc-3f-ex2300# set system syslog file cli-audit interactive-commands any
[edit]
root@acc-3f-ex2300# set system syslog file cli-audit archive size 1m files 10
[edit]
root@acc-3f-ex2300# commit comment "基準設定 5/6：NTP 與 syslog"
commit complete
```

```text
[edit]
root@acc-3f-ex2300# run show ntp associations
     remote           refid      st t when poll reach   delay   offset  jitter
==============================================================================
*10.99.0.30      118.163.81.61    2 -   12   64    1    0.412   -1.083   0.041
```

★★★★ `reach` 剛設好時是 `1`（只成功一次），過幾分鐘要變成 `377`。
到 syslog 伺服器上確認有收到這台的訊息（★★★★ **一定要去對面確認，不能只看送出端**）。

### 步驟 7：`lo0` filter（★★★★★ 最危險的一步）

★★★★★ 人**還在 console 前面**，這是做這一步的最佳時機。

```text
[edit]
root@acc-3f-ex2300# set policy-options prefix-list MGMT-HOSTS 10.99.1.0/24
[edit]
root@acc-3f-ex2300# set policy-options prefix-list MGMT-HOSTS 10.99.0.0/24
[edit]
root@acc-3f-ex2300# set policy-options prefix-list NTP-SERVERS 10.99.0.30/32
[edit]
root@acc-3f-ex2300# set policy-options prefix-list NTP-SERVERS 10.99.0.31/32
```

（filter 內容同「進階設定與調校」那一節，此處用 `load set terminal` 一次貼入）

```text
[edit]
root@acc-3f-ex2300# load set terminal
[Type ^D at a new line to end input]
set firewall family inet filter PROTECT-RE term MGMT-SSH from source-prefix-list MGMT-HOSTS
set firewall family inet filter PROTECT-RE term MGMT-SSH from protocol tcp
set firewall family inet filter PROTECT-RE term MGMT-SSH from destination-port ssh
set firewall family inet filter PROTECT-RE term MGMT-SSH then count re-ssh-accept
set firewall family inet filter PROTECT-RE term MGMT-SSH then accept
... (省略，同前一節) ...
set firewall family inet filter PROTECT-RE term DEFAULT-DENY then count re-default-deny
set firewall family inet filter PROTECT-RE term DEFAULT-DENY then log
set firewall family inet filter PROTECT-RE term DEFAULT-DENY then discard
^D
load complete

[edit]
root@acc-3f-ex2300# set interfaces lo0 unit 0 family inet filter input PROTECT-RE
[edit]
root@acc-3f-ex2300# commit check
configuration check succeeds
[edit]
root@acc-3f-ex2300# commit confirmed 10 comment "基準設定 6/6：RE 保護 filter"
commit confirmed will be automatically rolled back in 10 minutes unless confirmed
commit complete
```

**★★★★★ 十分鐘內要完成的驗證**：

```text
[edit]
root@acc-3f-ex2300# run show firewall filter PROTECT-RE
Filter: PROTECT-RE
Counters:
Name                                                Bytes              Packets
re-default-deny                                       288                    4
re-mgmt-deny                                            0                    0
re-ssh-accept                                        6142                   58
```

```text
[edit]
root@acc-3f-ex2300# run show log messages | match "PROTECT-RE|FW:" | last 10
Sep  2 17:22:41  acc-3f-ex2300 fpc0 PFE_FW_SYSLOG_IP: FW: lo0.0   D   igmp 10.99.0.1  224.0.0.1  0  0 (4 packets)
```

★★★★ 只有 IGMP 被丟（這台沒跑多播，可接受）。**沒有看到 OSPF／VRRP／NTP 被丟** —— 通過。

從辦公室新開一個 SSH 連線：

```text
$ ssh netadmin@10.99.0.11
netadmin@acc-3f-ex2300>
```

★★★★★ **新連線成功**（不是靠既有連線）。可以確認了：

```text
[edit]
root@acc-3f-ex2300# commit comment "基準設定 6/6 驗證通過"
commit complete
```

### 步驟 8：收尾 ★★★★

```text
[edit]
root@acc-3f-ex2300# exit
Exiting configuration mode

netadmin@acc-3f-ex2300> request system configuration rescue save

netadmin@acc-3f-ex2300> show configuration | display set | save /var/tmp/acc3f-baseline.set
Wrote 128 lines of output to '/var/tmp/acc3f-baseline.set'

netadmin@acc-3f-ex2300> file copy /var/tmp/acc3f-baseline.set scp://netadmin@10.99.0.5//backup/acc-3f-ex2300/
Password for netadmin@10.99.0.5:
```

### 驗收檢查表 ★★★★★

| # | 檢查項 | 通過標準 | 星級 |
| --- | --- | --- | --- |
| 1 | hostname 依命名規範 | 看得出層級／位置／機型 | ★★★★ |
| 2 | 時區與 NTP | `show ntp associations` 有 `*`、`reach 377`；`Time Source: NTP CLOCK` | ★★★★ |
| 3 | 帶內管理 IP 通 | `ping` 得到閘道；`show route 0.0.0.0/0` 有一條 active | ★★★★★ |
| 4 | 帶外管理 IP 通 | 從管理站 ping 得到 `me0` 的位址 | ★★★★★ |
| 5 | 只有一條 active 預設路由 | `show route 0.0.0.0/0` 沒有兩條打架 | ★★★★ |
| 6 | root 密碼已設且封存 | console 登得進；密碼在保險櫃 | ★★★★★ |
| 7 | root SSH 被拒 | `ssh root@<IP>` 得到 Permission denied | ★★★★★ |
| 8 | 個人帳號可 SSH | 金鑰與密碼都測過 | ★★★★★ |
| 9 | 受限 class 實測過 | `duty01` 打 `configure`／`request system reboot` 都被擋 | ★★★★ |
| 10 | Telnet／J-Web／FTP 已關 | `show system services` 只剩 ssh 與 netconf | ★★★★★ |
| 11 | 登入警語顯示 | SSH 連線時看得到 | ★★★★ |
| 12 | 登入失敗鎖定 | 故意打錯三次會被切斷 | ★★★ |
| 13 | syslog 送到集中伺服器 | ★★★★★ **在 syslog 伺服器端看得到這台的訊息** | ★★★★★ |
| 14 | `interactive-commands` 有記錄 | `show log cli-audit` 看得到剛才打的指令 | ★★★★★ |
| 15 | `lo0` filter 已套用 | `show firewall filter PROTECT-RE` 有計數 | ★★★★★ |
| 16 | filter 沒誤擋必要協定 | `re-default-deny` 的 log 裡沒有 OSPF／VRRP／NTP | ★★★★★ |
| 17 | filter 套用後新 SSH 連得上 | 開新視窗實測，不靠既有連線 | ★★★★★ |
| 18 | rescue 已存、設定已外部備份 | 備份伺服器上有基準檔 | ★★★★★ |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 套用 `lo0` filter 後立刻斷線，再也連不上 | filter 沒放行你的來源 IP 的 SSH，或 term 順序寫錯被前面的 deny 攔截 | 若有用 `commit confirmed` 就等時限自動回滾；否則只能接 console `rollback 1` + `commit`。★★★★★ 以後這種變更一律 confirmed |
| ★★★★★ 套用 `lo0` filter 後路由鄰居全掉、閘道漂移 | 漏放行 OSPF（proto 89）／VRRP（proto 112）／BFD | `show log messages \| match FW:` 找出被丟的協定，補 term 後 `commit confirmed`。★★★★ 起步階段先只 `count` 不 `discard` |
| ★★★★★ 設好管理 IP 但 ping 不到 | 上聯 trunk 沒帶管理 VLAN／對端沒放行／VLAN 沒建 | `show ethernet-switching interface <trunk>` 兩端都看，確認 MGMT 在清單裡且 tagged |
| ★★★★★ `commit` 失敗：`Missing mandatory statement: 'root-authentication'` | 新機或 `load factory-default` 之後沒設 root 密碼 | `set system root-authentication plain-text-password` 依提示輸入兩次 |
| ★★★★★ 加了 `no-passwords` 之後所有人都登不進去 | 金鑰貼錯、格式不對、或貼到別的帳號 | console 進入 → `delete system services ssh no-passwords` → `commit`。★★★★★ 以後先實測金鑰登入成功再加 |
| ★★★★ 管理流量走錯路徑／帶外根本沒通 | 帶內與帶外各設了一條 0.0.0.0/0，只有一條 active | `show route 0.0.0.0/0` 看誰是 `*`。★★★★ 正解是帶外與管理站同網段，或用 `management-instance` |
| ★★★★ `irb.99` 一直 `up down` | VLAN 99 沒有任何 up 的成員埠（autostate） | 確認上聯 trunk 有帶 MGMT 且 trunk 是 up；`show vlans MGMT` 看有沒有帶 `*` 的成員 |
| ★★★★ 自訂 class 的人連 `show` 都不能用 | `allow-commands` 正規表示式寫錯，或 `deny-commands` 太寬 | 用該帳號實測；`deny-commands` 加 `^` 錨定開頭；`permissions` 至少要有 `view` |
| ★★★★ 監控系統抓不到 SNMP | `lo0` filter 沒放行 SNMP，或 `clients` 沒包含監控主機 | `show firewall filter PROTECT-RE` 看 deny 計數；`show configuration snmp \| display set` 核對 clients |
| ★★★★ syslog 伺服器收不到訊息 | `source-address` 沒設造成來源 IP 不固定被防火牆擋、或 syslog 伺服器沒開 udp/514 | 在 syslog 端 `tcpdump -i any port 514` 確認有無封包；`set system syslog host X source-address <管理IP>` |
| ★★★★ 時間差好幾小時，日誌對不上 | 沒設 `time-zone`，或 NTP 沒對到 | `show system uptime` 看 `Time Source`；`show ntp associations` 看有沒有 `*` |
| ★★★ 接了 RADIUS 之後所有人都登不進去 | RADIUS 不可達、共用密鑰打錯、`authentication-order` 只寫 radius | console 進入 → `set system authentication-order [ radius password ]` → `commit`。★★★★★ 本機緊急帳號永遠不要刪 |
| ★★★ SSH 連線一直被拒，日誌顯示 rate limit | `rate-limit` 設太低，或有監控系統／腳本頻繁連線 | 調高 `rate-limit`；或把自動化改用 NETCONF 長連線 |
| ★★★ 登入後幾分鐘就被踢出去 | `class` 的 `idle-timeout` 或 `client-alive` 設定 | 依作業需要調整；★★★ 稽核要求的 15 分鐘閒置登出是合理的，不要因為不方便就關掉 |
| ★★★ `show configuration` 看不到密碼原文 | 正常，JunOS 只存雜湊 | 忘記密碼只能重設；★★★★ 別想著從備份還原「原本的密碼」 |
| ★★ 帶外埠 `me0` 一直 down | 線沒接、對端管理交換器沒設、或該機型的管理埠是 `em0` | `show interfaces terse \| match "me0\|em0\|fxp0"` 確認名稱 |

### 排查步驟

**【1】先判斷是「網路不通」還是「服務不給進」★★★★★**

從管理站：

```bash
$ ping -c 3 10.99.0.11
PING 10.99.0.11 (10.99.0.11) 56(84) bytes of data.
64 bytes from 10.99.0.11: icmp_seq=1 ttl=64 time=0.821 ms

$ nc -vz 10.99.0.11 22
Connection to 10.99.0.11 22 port [tcp/ssh] succeeded!
```

| 結果 | 意思 | 往哪查 |
| --- | --- | --- |
| ping 不到 | 二層或三層不通 | 【2】 |
| ping 得到但 22 埠不通 | ★★★★★ SSH 沒開、或被 `lo0` filter 擋 | 【4】 |
| 22 埠通但登不進 | 帳號／密碼／金鑰／class 問題 | 【5】 |

**【2】設備自己看得到自己的管理介面嗎 ★★★★**

從 console：

```text
netadmin@sw> show interfaces terse | match "irb.99|me0.0"
irb.99                  up    down inet     10.99.0.11/24
```

`up down` → VLAN 沒有 up 的成員（autostate），檢查 `show vlans MGMT`。

**【3】路由與上聯 ★★★★★**

```text
netadmin@sw> show route 0.0.0.0/0
inet.0: 6 destinations, 6 routes (6 active, 0 holddown, 0 hidden)
0.0.0.0/0          *[Static/5] 02:14:33
                    >  to 10.99.0.1 via irb.99

netadmin@sw> ping 10.99.0.1 count 3 rapid
PING 10.99.0.1 (10.99.0.1): 56 data bytes
!!!
--- 10.99.0.1 ping statistics ---
3 packets transmitted, 3 packets received, 0% packet loss
```

★★★★★ **ping 不到閘道 = 二層問題**，回去查上聯 trunk 有沒有帶管理 VLAN
（[[040-01-06-guide-Juniper-VLAN與Trunk設定]] 的排查步驟）。

**【4】是不是被 `lo0` filter 擋了 ★★★★★**

```text
netadmin@sw> show firewall filter PROTECT-RE
Filter: PROTECT-RE
Counters:
Name                                                Bytes              Packets
re-default-deny                                    148221                 1842
re-mgmt-deny                                         4128                   43
re-ssh-accept                                           0                    0
```

★★★★★ `re-ssh-accept` 是 0 而 `re-mgmt-deny` 在漲 → **你的來源 IP 不在 `MGMT-HOSTS` 裡**。

```text
netadmin@sw> show configuration policy-options prefix-list MGMT-HOSTS | display set
set policy-options prefix-list MGMT-HOSTS 10.99.1.0/24
```

管理站是 `10.99.2.7`？那就對了 —— 補進 prefix-list（**用 `commit confirmed`**）。

```text
netadmin@sw> show log messages | match "FW:" | last 20
Sep  2 18:04:11  sw fpc0 PFE_FW_SYSLOG_IP: FW: lo0.0   D   tcp 10.99.2.7  10.99.0.11  51234  22 (1 packets)
```

★★★★★ 這一行直接告訴你：來源 `10.99.2.7` 想連 `10.99.0.11:22` 被丟棄（`D` = discard）。

**【5】服務與帳號 ★★★★**

```text
netadmin@sw> show configuration system services
ssh {
    root-login deny;
    connection-limit 10;
    rate-limit 4;
}

netadmin@sw> show configuration system login | display set | match "user|class"
set system login class NOC permissions view
set system login user netadmin class super-user
set system login user duty01 class NOC

netadmin@sw> show log messages | match "sshd|LOGIN" | last 20
Sep  2 18:06:22  sw sshd[6721]: Failed password for duty01 from 10.99.1.5 port 51290 ssh2
Sep  2 18:06:30  sw sshd[6721]: Accepted publickey for netadmin from 10.99.1.5 port 51293 ssh2: ED25519 SHA256:9Xk4mZ...
```

★★★★★ `Failed password` vs `Accepted publickey` —— 一眼看出是密碼問題還是金鑰問題。

**【6】誰在什麼時候改壞的 ★★★★★**

```text
netadmin@sw> show system commit | last 5
0   2026-09-02 17:58:03 CST by duty01 via cli
1   2026-09-02 14:12:58 CST by netadmin via cli
    CR-2026-0512 驗證通過

netadmin@sw> show log cli-audit | match "duty01" | last 20
Sep  2 17:57:41  sw mgd[4412]: UI_CMDLINE_READ_LINE: User 'duty01', command 'configure '
Sep  2 17:57:55  sw mgd[4412]: UI_CMDLINE_READ_LINE: User 'duty01', command 'delete system services ssh rate-limit '
```

★★★★★ 這正是 `interactive-commands any` 的價值。
（順帶一提：`duty01` 能進 `configure` 代表 class 設定有漏洞，要一起修。）

**【7】最後手段 ★★★★★**

| 順序 | 動作 |
| --- | --- |
| 1 | 等 `commit confirmed` 時限自動回滾 |
| 2 | 走**另一條**管理路徑（帶內壞了走帶外，反之亦然） |
| 3 | 從鄰近設備跳：`ssh netadmin@10.99.0.11` |
| 4 | 接 console 線 → `rollback 1` 或 `rollback rescue` → `commit` |

## 安全性注意事項

> [!danger] ★★★★★ 管理面是攻擊者的首要目標
> 拿到交換器的管理權限，攻擊者可以：把自己的埠加進任何 VLAN、
> 做 port mirroring 把流量複製走、改路由把流量導到自己的機器、
> 直接關掉整棟樓的網路。**交換器的管理面必須比伺服器管得更嚴。**

| 項目 | 風險 | 做法 | 星級 |
| --- | --- | --- | --- |
| 管理 VLAN 與使用者 VLAN 共用 | ★★★★★ 任何員工都能掃描、攻擊設備 | 管理走獨立 VLAN，且 `lo0` filter 只放行管理網段 | ★★★★★ |
| 沒有 `lo0` filter | 全網任何人都能對 RE 送封包，可被 DoS | 部署 PROTECT-RE，含 ICMP policer | ★★★★★ |
| 開著 Telnet | ★★★★★ 帳密明文，同網段抓包即得 | `delete system services telnet` | ★★★★★ |
| 開著 J-Web（web-management） | ★★★★★ 歷年多個高風險 CVE，常被大規模掃描利用 | 不用就 `delete`；一定要用則限管理網段 + HTTPS + 更新韌體 | ★★★★★ |
| 共用 root 帳號 | 無稽核軌跡 | 個人帳號 + `root-login deny` + root 密碼封存 | ★★★★★ |
| SNMPv2c 用 `public`／`private` | ★★★★★ 等同無密碼，掃描工具預設就會試 | 改 SNMPv3；至少改成隨機字串 + `clients` 限制 | ★★★★★ |
| 沒送 syslog 到外部 | 設備被入侵後日誌一起沒了 | ★★★★★ 送集中日誌，含 `interactive-commands` | ★★★★★ |
| 沒有 `interactive-commands` 稽核 | 查不出誰做了什麼 | ★★★★★ 設備類基準必列項目 | ★★★★★ |
| 沒有閒置登出 | 離開座位的 session 被利用 | `class` 設 `idle-timeout 15` | ★★★★ |
| 人員異動未停用帳號 | 離職者仍可登入 | 納入離職檢查表；定期比對 `show configuration system login` 與人事名冊 | ★★★★★ |
| 集中認證沒有本機備援 | 認證伺服器掛掉＝全員鎖在外面 | ★★★★★ `authentication-order [ radius password ]` + 封存的緊急帳號 | ★★★★★ |
| 弱密碼 | 暴力破解 | `login password minimum-length 12` + `retry-options lockout-period` | ★★★★ |
| 設定備份含 `$9$` 密碼 | ★★★★★ `$9$` 可逆，等同明文 | 備份區限權限、加密、走 SCP | ★★★★★ |
| 沒有登入警語 | 法律上難以主張「未經授權」 | `set system login message`，內容洽法制單位 | ★★★★ |
| 帶外管理網路沒隔離 | 帶外變成另一個攻擊面 | 帶外網段不對外、不與辦公網互通；實體限制在機房內 | ★★★★★ |

> [!warning] ★★★★ 稽核常見缺失清單（設備類）
> 依機關資安稽核經驗，Juniper／Cisco 交換器最常被開的缺失是：
> 1. 仍開啟 Telnet 或 HTTP 管理介面
> 2. 使用共用帳號（無法識別個人）
> 3. SNMP community 為預設值或未限制來源
> 4. 未設定閒置逾時登出
> 5. 未將日誌送至集中日誌伺服器
> 6. 未保留指令層級的稽核紀錄
> 7. 韌體版本過舊且無升級計畫（見 [[040-01-09-svc-Juniper-設定備份與韌體升級]]）
> 8. 無設定備份或備份未定期驗證可還原
>
> 本篇的基準設定涵蓋 1～6，7～8 見 09 篇。
> 對照 TWGCB 的做法見 [[090-06-04-guide-TWGCB-Linux本機導入]]（設備類需另行對應）。

## 速查表

| 指令 / 設定項 | 說明 | 星級 |
| --- | --- | --- |
| `set system host-name X` | 主機名稱 | ★★★★ |
| `set system domain-name X` / `set system name-server X` | 網域與 DNS | ★★★ |
| `set system time-zone Asia/Taipei` | 時區 | ★★★★ |
| `set system ntp server X` / `boot-server X` | NTP | ★★★★ |
| `show ntp associations` | 對時狀態（`*` 選中、`reach 377` 正常） | ★★★★ |
| `set interfaces irb unit 99 family inet address 10.99.0.11/24` | 帶內管理 IP（**ELS**） | ★★★★★ |
| `set interfaces vlan unit 99 family inet address ...` | 帶內管理 IP（**非 ELS**） | ★★★★ |
| `set vlans MGMT l3-interface irb.99` | VLAN 綁三層介面 | ★★★★★ |
| `set interfaces me0 unit 0 family inet address 10.98.0.11/24` | 帶外管理 IP | ★★★★ |
| `show interfaces terse \| match "fxp0\|me0\|em0\|vme"` | 確認帶外埠名稱 | ★★★★★ |
| `set routing-options static route 0.0.0.0/0 next-hop X` | 預設路由 | ★★★★★ |
| `set routing-options static route 0.0.0.0/0 retain no-readvertise` | 保留且不重分佈 | ★★★ |
| `show route 0.0.0.0/0` | ★★★★ 確認只有一條 active | ★★★★ |
| `set system management-instance` | 帶外走獨立 `mgmt_junos` VRF（★★★★ 會斷線） | ★★★ |
| `set system root-authentication plain-text-password` | 設 root 密碼（互動輸入） | ★★★★★ |
| `set system root-authentication ssh-ed25519 "..."` | root 的 SSH 金鑰 | ★★★★ |
| `set system login user U class super-user` | 建帳號 | ★★★★★ |
| `set system login user U authentication ssh-ed25519 "..."` | 帳號的 SSH 公鑰 | ★★★★ |
| `set system login class C permissions [ view view-configuration ]` | 自訂權限 class | ★★★★ |
| `set system login class C allow-commands "^(show\|ping)"` | 指令白名單 | ★★★★ |
| `set system login class C deny-commands "^(request\|configure)"` | ★★★★★ 黑名單優先 | ★★★★★ |
| `set system login class C idle-timeout 15` | 閒置登出 | ★★★★ |
| `set system services ssh root-login deny` | 禁 root SSH | ★★★★★ |
| `set system services ssh connection-limit 10` / `rate-limit 4` | 連線與速率限制 | ★★★★ |
| `set system services ssh no-passwords` | ★★★★★ 只准金鑰（先測過再開） | ★★★★ |
| `set system services netconf ssh` | 自動化用 | ★★★ |
| `delete system services telnet` / `web-management` / `ftp` | 關掉明文與高風險服務 | ★★★★★ |
| `set system login message "..."` / `announcement "..."` | 登入前／後訊息 | ★★★★ |
| `set system login retry-options lockout-period 5` | 登入失敗鎖定 | ★★★★ |
| `set system syslog host X any notice` | 送集中日誌 | ★★★★★ |
| `set system syslog host X interactive-commands any` | ★★★★★ 記錄每一條指令 | ★★★★★ |
| `set system syslog host X source-address <管理IP>` | 固定來源 IP | ★★★★ |
| `show log cli-audit` / `show log messages` | 看日誌 | ★★★★ |
| `set policy-options prefix-list MGMT-HOSTS 10.99.1.0/24` | 管理來源白名單 | ★★★★ |
| `set firewall family inet filter PROTECT-RE term T from ...` | RE 保護規則 | ★★★★★ |
| `set interfaces lo0 unit 0 family inet filter input PROTECT-RE` | ★★★★★ 套用（最危險的一行） | ★★★★★ |
| `show firewall filter PROTECT-RE` | 各 term 的封包計數 | ★★★★★ |
| `show log messages \| match "FW:"` | 被 filter 丟棄的封包明細 | ★★★★★ |
| `set system radius-server X secret "..."` | RADIUS | ★★★★ |
| `set system authentication-order [ radius password ]` | ★★★★★ 保留本機備援 | ★★★★★ |
| `set system login user remote class read-only` | RADIUS 使用者的樣板帳號 | ★★★★ |
| `set snmp community <字串> clients 10.99.0.20/32` | SNMP 來源限制 | ★★★★ |
| `set snmp v3 usm local-engine user ...` | SNMPv3（建議） | ★★★★ |
| `show system users` | 誰在線上 | ★★★ |
| `request system logout user U` | 踢掉某個使用者的 session | ★★★ |

## 練習題

> [!question]- 練習 1：找出你們每一台設備的帶外管理埠名稱 ★★★★
> 對能碰到的每一台 Juniper 設備：
> 1. `show interfaces terse | match "fxp0|me0|em0|vme"` 記下介面名稱與是否有 IP
> 2. `show chassis hardware | match Chassis` 記下機型
> 3. 檢查該介面實體上有沒有接線（`show interfaces <name> | match "Physical link"`）
> 4. 若有 IP，從管理站測 ping 與 SSH
>
> 做成一張表：機型 / 帶外埠名稱 / IP / 實際接了嗎 / 通不通。
> **要回答的問題**：有幾台其實「設了帶外 IP 但線根本沒接」？
> 這種情況為什麼比「沒設」更危險？

> [!question]- 練習 2：建立一個受限的值班帳號並實測 ★★★★★
> 在測試設備上：
> 1. 建 `class NOC`，權限為 `[ view view-configuration ]`，
>    `allow-commands "^(show|ping|traceroute|monitor|help|set cli)"`，
>    `deny-commands "^(request|configure|start shell|file)"`，`idle-timeout 15`
> 2. 建帳號 `duty-test` 用這個 class
> 3. `commit`
> 4. ★★★★★ **用 `duty-test` 實際登入**，逐一測試：
>    `show configuration` / `show interfaces terse` / `ping 8.8.8.8` /
>    `configure` / `request system reboot` / `file list` / `start shell`
> 5. 記下哪些成功、哪些被擋
>
> **要回答的問題**：有沒有你以為會被擋卻沒擋住的指令？
> 正規表示式要怎麼改？為什麼「只看設定檔」驗不出這種漏洞？

> [!question]- 練習 3：`lo0` filter 的漸進部署 ★★★★★
> **務必在測試設備上做，人在 console 前面。**
> 1. 寫一個 `PROTECT-RE-AUDIT` filter，每個 term 都只有 `then count <名稱>` 與 `then accept`
>    （**完全不 discard**），最後一個 term 是 `then count catch-all` + `then accept`
> 2. 套用到 `lo0`，`commit confirmed 10`，確認一切正常後 `commit`
> 3. 讓它跑 30 分鐘（或一天），期間正常使用設備、跑監控、做備份
> 4. `show firewall filter PROTECT-RE-AUDIT` 看每個計數器
> 5. 特別看 `catch-all` 的數字 —— **那些就是你原本會誤擋的流量**
> 6. 把 `catch-all` 改成 `then log` + `then discard`，觀察 `show log messages | match FW:`
>
> **要回答的問題**：`catch-all` 抓到了哪些你沒想到的協定？
> 為什麼這種「先觀察再封鎖」的做法比直接寫 deny 安全得多？
> 同樣的原則在防火牆規則設計上怎麼應用（見 [[090-02-03-guide-防火牆-nftables與iptables]]）？

> [!question]- 練習 4：驗證稽核軌跡的完整性 ★★★★
> 1. 在測試設備上設好 `set system syslog file cli-audit interactive-commands any`
> 2. 用兩個不同帳號各登入一次，各做一些操作（含一次 `commit`）
> 3. `show log cli-audit` 檢查是否每一條指令都有記錄、有沒有帳號名稱
> 4. `show system commit` 對照
> 5. 把 syslog 也送到一台測試用的 Linux（`rsyslog` 開 udp/514），
>    確認遠端也收得到（見 [[100-01-02-guide-日誌-日誌集中與輪替]]）
>
> **要回答的問題**：本機日誌與遠端日誌的內容一致嗎？
> 如果有人用 `class` 有 `maintenance` 權限的帳號刪掉本機日誌檔，遠端還留得住嗎？
> 這說明了什麼？

> [!question]- 練習 5：寫一份「機關交換器管理面基準」★★★★
> 依本篇的「完整實戰範例」，整理成一份可以派送到所有交換器的 `set` 格式基準檔，包含：
> - 身分（hostname 規則、時區、DNS）
> - 時間（NTP 伺服器）
> - 帳號與權限（哪些 class、哪些帳號、認證方式）
> - 服務（開哪些、關哪些）
> - 登入政策（警語、重試限制、閒置逾時）
> - 日誌（送到哪、記哪些）
> - `lo0` filter（放行清單）
>
> 把「每台不同的部分」（hostname、IP）標記出來做為變數。
> 與 [[020-02-03-02-ref-標準化-基準設定與範本化]] 的做法對照，
> 思考怎麼用 `apply-groups` 或自動化工具派送。

## 小測驗

Q1. 帶內管理與帶外管理各是什麼？舉一個「只有帶內管理會出大事、有帶外管理就沒事」的具體情境。

Q2. 你在 `lo0` 上套用了一個 firewall filter，裡面有 SSH、SNMP、ICMP 三個 accept 的 term，沒有寫任何 deny。commit 之後 OSPF 鄰居全掉了。為什麼？

Q3. 這行指令會發生什麼事：`set system services ssh no-passwords`？在什麼前提下它是安全的？什麼前提下會造成災難？

Q4. 是非題：`set system root-authentication plain-text-password` 會把密碼以明文存在設定檔裡。請說明理由。

Q5. 你的設備同時設了帶內 `irb.99`（10.99.0.11/24，閘道 10.99.0.1）與帶外 `me0`（10.98.0.11/24，閘道 10.98.0.1），兩邊都寫了 `0.0.0.0/0` 的靜態路由。會發生什麼事？怎麼確認？正解是什麼？

Q6. `set system authentication-order radius`（只有 radius）與 `[ radius password ]` 差在哪？為什麼機關環境一定要用後者？除了這個設定，還要搭配什麼作業規定？

Q7. `show firewall filter PROTECT-RE` 顯示 `re-ssh-accept` 是 0，`re-mgmt-deny` 是 4128 bytes / 43 packets。診斷是什麼？下一步要看哪個指令確認？

Q8. 為什麼 `set system syslog ... interactive-commands any` 對資安稽核特別重要？它記錄的內容跟 `show system commit` 有什麼不同？

Q9. 一個 `class` 設了 `permissions [ view view-configuration ]` 且 `deny-commands "request"`。這個 `deny-commands` 有什麼潛在問題？怎麼寫比較好？

Q10. 你要遠端把 `lo0` 上的 PROTECT-RE filter 加一條新的 term（放行新的監控主機）。請寫出完整的作業步驟，並說明每一步的目的。

> [!question]- 測驗答案
> **Q1.** ★★★★★
> - **帶內（in-band）**：管理流量走**使用者資料同一批實體線路與 VLAN**，
>   在 JunOS 上是 `irb.99`（ELS）或 `vlan.99`（非 ELS）。成本零，但與資料面共命運。
> - **帶外（out-of-band, OOB）**：走**完全獨立的管理網路**，
>   透過設備的專用管理埠 `me0` / `em0` / `fxp0`，只連到 Routing Engine，不參與轉發。
>
> 具體情境：你遠端修改上聯 trunk 的 `vlan members`，
> 不小心用了 `delete ... vlan` 再 `set`，把 MGMT VLAN 一起清掉了。
> ★★★★★ 只有帶內管理 → 管理 VLAN 從 trunk 上消失，**你在斷線的同一瞬間失去修復能力**，
> 只能開車去機房接 console（若沒用 `commit confirmed`）。
> 有帶外管理 → 帶外那條路完全沒被動到，你照樣連得上，`rollback 1` + `commit` 三十秒解決。
> 見「兩條管理路徑」。
>
> **Q2.** ★★★★★ 因為 **JunOS 的 firewall filter 結尾有隱含的 deny** ——
> 沒有任何 term 命中的封包一律被丟棄，不需要你寫 deny。
> OSPF 用 IP protocol 89、送到多播位址 224.0.0.5／224.0.0.6，
> 目的地是設備自己，所以會經過 `lo0` 的 input filter；
> 而你的三個 term 都不匹配它，於是落到隱含 deny 被丟掉，鄰居關係在 dead interval 後全部斷開。
> ★★★★★ 這是 `lo0` filter 最經典的災難：**你以為「只是加了幾條允許」，實際上是「只允許這幾條」**。
> 補救：`rollback 1` + `commit`，然後補上 OSPF／VRRP／BFD 等必要 term。
> 預防：先用只有 `count` + `accept` 的觀察版跑一段時間，看 `catch-all` 抓到什麼再收緊。
> 見「保護 Routing Engine 的 lo0 firewall filter」與練習 3。
>
> **Q3.** ★★★★★ 它會**關閉所有密碼認證，只接受 SSH 公鑰**。
> - **安全的前提**：(a) 你已經在該帳號設好 `authentication ssh-ed25519 "..."`
>   (b) ★★★★★ **已經另開視窗實測金鑰登入成功** (c) 用 `commit confirmed 10` 送出
>   (d) 再用第三個視窗確認後才 `commit`。
> - **災難的前提**：公鑰貼錯一個字元、貼成了 `.pub` 以外的格式、
>   貼到別的帳號底下、或根本忘了設 —— commit 之後**沒有任何人能用 SSH 進來**，
>   只剩 console 可救。若這台在別的縣市，就是一趟出差。
>
> ★★★★ 這跟 [[020-02-01-04-svc-sshd-伺服器端設定]] 的「不鎖門 SOP」是同一個道理：
> **關掉一種認證方式之前，先證明另一種真的能用。** 見「SSH 與關掉不該開的服務」。
>
> **Q4.** ★★★★★ **錯。** `plain-text-password` 指的是**輸入方式**（互動式輸入明文，
> 不是在指令列上打），不是儲存方式。JunOS 收到之後會立刻雜湊，
> 設定檔裡存的是 `encrypted-password "$6$..."`（SHA-512 crypt），並標註 `## SECRET-DATA`。
> ★★★★ 相對的，`set system root-authentication encrypted-password "$6$..."`
> 是「我已經有雜湊了，直接貼給你」，用於從標準範本派送。
> ★★★★★ 但要注意：設定檔裡的雜湊仍可被離線暴力破解，而某些欄位（RADIUS secret、
> SNMP community）用的是 **`$9$` 可逆編碼，等同明文** ——
> 所以備份檔一律比照密碼檔保護。見「root 密碼與個人帳號」與「安全性注意事項」。
>
> **Q5.** ★★★★★ 兩條 `0.0.0.0/0` **會打架，Junos 只會挑一條當 active**
> （同為 Static/5 時依內部規則擇一，結果不見得是你想要的）。
> 後果是：你以為帶外管理走 `me0`，實際上所有回程流量都從 `irb.99` 出去；
> ★★★★★ **而你會在「改壞帶內」的那一刻才發現帶外其實從來沒通過** —— 那正是你最需要它的時候。
>
> 確認方式：`show route 0.0.0.0/0`，只會有一條帶 `*`（Both / Active）；
> 另一條會是非 active。
>
> 正解（依偏好排序）：
> 1. ★★★★★ **帶外管理站與設備同網段**（10.98.0.0/24 扁平），完全不需要路由 —— 最單純可靠
> 2. ★★★ 用 `set system management-instance` 把帶外埠放進獨立的 `mgmt_junos` VRF，
>    兩張路由表互不干擾（★★★★ 但 commit 時會斷線，且 syslog／NTP／SNMP 都要調整）
> 3. ★★ 只給帶外一條**明細路由**（指向管理站網段）而不是預設路由
>
> 見「帶外管理 IP（me0）」。
>
> **Q6.** ★★★★★
> - `authentication-order radius`（只有一個）：只問 RADIUS。
>   ★★★★ 文件上的行為是「RADIUS 伺服器**沒有回應**時會退回本機密碼，
>   但 RADIUS **明確拒絕**時就是拒絕」。
> - `authentication-order [ radius password ]`：先問 RADIUS，
>   不論無回應或被拒都會再試本機密碼。
>
> ★★★★★ 機關環境一定要用後者的理由：**RADIUS 伺服器、中間網路、共用密鑰任何一環出問題，
> 你都還進得去**。網路設備出事的時候，往往就是認證伺服器也連不到的時候。
>
> 搭配的作業規定（缺一不可）：
> 1. ★★★★★ 本機保留至少一個「緊急帳號」，**永遠不要刪**
> 2. 該帳號密碼封存（信封簽章／保險櫃），定期更換
> 3. 使用時必須事後報備並記錄
> 4. ★★★★ 定期演練：把 RADIUS 關掉，確認本機帳號真的登得進去
>
> 見「RADIUS／TACACS+ 集中認證」。
>
> **Q7.** ★★★★★ 診斷：**你的來源 IP 不在允許清單裡，SSH 被 `DENY-MGMT` term 攔下了**。
> `re-ssh-accept` 是 0 代表**沒有任何封包命中 accept 那個 term**，
> 而 `re-mgmt-deny` 在漲代表有人（就是你）在敲管理埠但被丟棄。
>
> 下一步兩個指令：
> 1. `show log messages | match "FW:" | last 20` ——
>    會直接印出被丟的封包：來源 IP、目的 IP、埠號、動作（`D` = discard）
> 2. `show configuration policy-options prefix-list MGMT-HOSTS | display set` ——
>    對照你的管理站 IP 是否在裡面
>
> 修正：把管理站網段補進 prefix-list，★★★★★ **用 `commit confirmed 10`**
> （改 `lo0` filter 相關設定永遠要 confirmed）。見「排查步驟【4】」。
>
> **Q8.** ★★★★★ 因為它記錄的是**每一個人打的每一條 CLI 指令**，含帳號、時間、完整指令字串：
> ```text
> Sep  2 15:41:15 sw mgd[4412]: UI_CMDLINE_READ_LINE: User 'netadmin', command 'set interfaces ge-0/0/10 disable '
> ```
> 與 `show system commit` 的差別：
>
> | | `show system commit` | `interactive-commands` |
> | --- | --- | --- |
> | 記錄什麼 | 只有 **commit 事件**（時間、帳號、comment） | ★★★★★ **每一條指令**，含 `show`、`ping`、進出設定模式 |
> | 未 commit 的操作 | 完全不記 | 記 |
> | 只是「看」的行為 | 不記 | ★★★★★ 記（誰在什麼時候查了什麼） |
> | 保留位置 | 設備本機 | 本機檔案 + 可送遠端 syslog |
> | 保留數量 | ★★★★ 最多 50 筆，會被擠掉 | 依 `archive size/files` 與遠端保存期限 |
>
> ★★★★★ 資安事件調查要回答的是「攻擊者進來之後做了什麼」，
> 而 `show system commit` 只看得到「他改了設定」，看不到「他先掃了哪些資訊」。
> 加上必須送到**外部**日誌伺服器（設備被入侵後本機日誌可能被刪），才構成完整的稽核軌跡。
> 見「syslog」與 [[100-01-02-guide-日誌-日誌集中與輪替]]。
>
> **Q9.** ★★★★★ 問題是 **`deny-commands "request"` 是沒有錨定的正規表示式，
> 會匹配「任何位置含有 request 這個字串」的指令**，例如：
> - `show log messages | match request` —— 只是想過濾日誌，卻被擋
> - `show configuration | display set | match request` —— 同上
> - 未來任何新增的、名稱裡含 request 的指令
>
> 反過來也可能**擋不夠**：如果本意是擋所有 `request` 開頭的操作型指令，
> 沒有錨定時雖然會擋到，但同時誤傷一大片，使用者會覺得「這個帳號根本沒法用」。
>
> ★★★★ 比較好的寫法：`set system login class C deny-commands "^(request|start shell|file delete|clear)"`
> —— 用 `^` 錨定開頭、用 `(A|B|C)` 明確列舉。
> ★★★★★ 而且不論怎麼寫，**都必須用該帳號實際登入逐條測試**：
> (a) 該擋的擋住了 (b) 該給的權限還在。正規表示式的漏洞是看設定檔看不出來的。
> 見「system login class」與練習 2。
>
> **Q10.** ★★★★★ 完整步驟（每一步都不能省）：
> ```text
> ## 1. 備份現況 —— 出事有東西可比對
> netadmin@sw> show configuration | display set | save /var/tmp/before-CRxxxx.set
> netadmin@sw> file copy /var/tmp/before-CRxxxx.set scp://netadmin@10.99.0.5//backup/sw/
>
> ## 2. 存 rescue —— 最後防線
> netadmin@sw> request system configuration rescue save
>
> ## 3. 記下目前的計數器 —— 之後才知道有沒有變化
> netadmin@sw> show firewall filter PROTECT-RE
>
> ## 4. 獨占設定模式並確認 candidate 乾淨
> netadmin@sw> configure exclusive
> [edit]
> netadmin@sw# show | compare
>
> ## 5. 改設定 —— 加進 prefix-list 比新增 term 安全（不動 term 順序）
> [edit]
> netadmin@sw# set policy-options prefix-list MGMT-HOSTS 10.99.3.20/32
>
> ## 6. 看差異 —— 確認只動到這一行
> [edit]
> netadmin@sw# show | compare
>
> ## 7. 語意驗證
> [edit]
> netadmin@sw# commit check
>
> ## 8. ★★★★★ commit confirmed —— 改壞了會自己回去
> [edit]
> netadmin@sw# commit confirmed 10 comment "CRxxxx 新增監控主機到 RE 白名單"
>
> ## 9. 驗證：新監控主機連得上、既有連線沒斷、沒有非預期的 deny
> [edit]
> netadmin@sw# run show firewall filter PROTECT-RE
> [edit]
> netadmin@sw# run show log messages | match "FW:" | last 20
> ## 並請監控端實測 SNMP／SSH
>
> ## 10. 確認定案
> [edit]
> netadmin@sw# commit comment "CRxxxx 驗證通過"
>
> ## 11. 收尾
> netadmin@sw> show configuration | display set | save /var/tmp/after-CRxxxx.set
> netadmin@sw> file copy /var/tmp/after-CRxxxx.set scp://netadmin@10.99.0.5//backup/sw/
> netadmin@sw> request system configuration rescue save
> ```
> ★★★★★ 關鍵是第 5 步的做法：**改 prefix-list 而不是新增 term**，
> 因為 filter 的 term 是有順序的，插錯位置可能被前面的 deny 攔截，
> 或反而讓後面的規則失效。能用資料（prefix-list）解決的就不要動邏輯（term）。
> 見「完整實戰範例」與「進階設定與調校」。

## 延伸閱讀

- [[040-01-05-cmd-Juniper-JunOS-基礎操作]] —— `commit confirmed`／`rollback`，本篇每一步的安全網
- [[040-01-06-guide-Juniper-VLAN與Trunk設定]] —— 管理 VLAN 怎麼建、trunk 怎麼帶
- [[040-01-08-guide-Juniper-埠設定與安全]] —— 埠層級的防護、未用埠隔離
- [[040-01-09-svc-Juniper-設定備份與韌體升級]] —— 備份自動化、韌體漏洞修補
- [[040-01-12-guide-Cisco-管理IP與遠端存取]] —— Cisco 那一側的完整內容（含 CoPP）
- [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]] —— 兩邊指令對照
- [[020-02-01-04-svc-sshd-伺服器端設定]] —— 「不鎖門 SOP」的完整版，思維與本篇一致
- [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] —— 金鑰怎麼產、怎麼管、怎麼輪替
- [[090-02-06-guide-防護-遠端存取安全]] —— 遠端管理的通用安全原則
- [[090-02-08-guide-防護-系統強化與稽核]] —— 稽核項目與佐證怎麼準備
- [[100-01-02-guide-日誌-日誌集中與輪替]] —— syslog 伺服器怎麼架、保存多久
- [[100-01-03-guide-日誌-系統監控與告警]] —— SNMP 監控接入的完整規劃
- [[040-01-18-guide-網路設備-網路設備盤點與文件化]] —— 管理 IP、帳號、序號怎麼列冊
- Juniper Access Privilege User Guide（login class 與 permissions）：<https://www.juniper.net/documentation/us/en/software/junos/user-access/>
- Juniper Routing Engine Protection（`lo0` filter 官方範例）：<https://www.juniper.net/documentation/us/en/software/junos/routing-policy/>
- Juniper Day One: Securing the Routing Engine（免費電子書）：<https://www.juniper.net/documentation/jnbooks/us/en/day-one-books/>
