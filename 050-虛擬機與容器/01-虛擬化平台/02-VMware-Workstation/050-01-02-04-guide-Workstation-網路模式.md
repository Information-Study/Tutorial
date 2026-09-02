---
title: "網路模式"
desc: "NAT／Bridged／Host-only／自訂 VMnet 與 LAN Segment 的封包路徑、可達性矩陣、虛擬網路編輯器操作、NAT 埠轉發與固定 IP 設定，並指出本手冊各章實驗該用哪一種模式"
aliases: [VMnet, VMnet0, VMnet1, VMnet8, Bridged, NAT, Host-only, LAN Segment, 虛擬網路編輯器, 埠轉發, port forwarding, 橋接, 僅限主機]
tags: [群組/虛擬機與容器, 主題/虛擬化, 主題/VMware]
category: 虛擬機與容器
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]]"]
updated: 2026-09-02
---

# 網路模式

> [!warning] 未實機驗證
> 本篇的選單路徑與畫面文字**以 VMware Workstation 17 為例**，
> 其他版本的選單位置、按鈕文字與對話框名稱可能不同。
> 設定檔路徑（`vmnetnat.conf`、`vmnetdhcp.conf` 等）在不同版本與作業系統上也可能改變，
> **請以你手上這台的實際路徑為準**。★★★★★ **觀念、封包路徑與可達性矩陣不會變。**

> [!abstract] 這篇你會學到
> - ★★★★★ **NAT／Bridged／Host-only／自訂 VMnet** 四種模式的**封包路徑圖**
>   —— 看懂圖，八成的網路問題自己就會排了
> - ★★★★★ 一張**可達性矩陣**：四種模式 × 五個方向全部填滿，
>   「為什麼我 ping 不到」直接查表
> - ★★★★ **虛擬網路編輯器**怎麼用：新增 VMnet、改網段、開關 DHCP
> - ★★★★ **NAT 埠轉發**：讓實體機（甚至同事的電腦）連進 VM 裡的服務
> - ★★★★★ **本手冊各章實驗環境該選哪一種模式** —— 一張對照表講完
> - ★★★★ **固定 IP** 的兩種做法：VM 內設 Netplan，或在 DHCP 做保留
> - ★★★★ 常見的九個網路故障：拿不到 IP、無線網卡 Bridged 失敗、
>   公司網路禁止多 MAC 時怎麼辦

---

## 前置知識

- [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] — ★★★★★ 必讀。
  本篇假設你手上已經有一台裝好的 `lab-ubuntu-base`
- [[050-01-02-01-svc-Workstation-安裝與授權]] — ★★★ 安裝時就產生了 VMnet1 與 VMnet8
- [[010-02-08-guide-網概-NAT與私有位址]] — ★★★★★ **NAT 模式看不懂，多半是這篇沒讀**
- [[010-02-06-guide-網概-IP位址與子網路]] — ★★★★ 網段、遮罩、閘道的基本功
- [[010-02-12-guide-網概-DHCP自動取得設定]] — ★★★★ VMware 內建的 DHCP 就是這個東西
- [[020-01-16-cmd-Linux-網路基礎指令]] — ★★★★ `ip a`、`ip r`、`ping`、`ss` 的用法

> [!tip] ★★★★ 這篇怎麼查
> | 你的問題 | 直接翻到 |
> | --- | --- |
> | 「該選哪一種？」 | 「本手冊各章實驗環境選哪一種」 |
> | 「為什麼 ping 不到？」 | 「可達性矩陣」 |
> | 「實體機瀏覽器要連進 VM」 | 「NAT 埠轉發」 |
> | 「要改成 192.168.100.0/24」 | 「虛擬網路編輯器」 |
> | 「VM 拿不到 IP」 | 「常見錯誤與排錯」 |

---

## 觀念說明

### ★★★★★ 一、先建立正確的心智模型：主機裡有一組看不見的網路設備

★★★★★ **最重要的一句話：Workstation 在你的主機裡「蓋了一座小機房」。**

裝完 Workstation 之後，你的作業系統裡多了四種東西（雖然你看不見）：

| 元件 | 相當於實體世界的什麼 | 說明 |
| --- | --- | --- |
| ★★★★★ **虛擬交換器（VMnet）** | 一台無網管交換器 | 每個 VMnet 就是一台獨立的交換器，接在同一台上的 VM 才互通 |
| ★★★★ **主機虛擬網卡** | 主機身上多插一張網卡，接到那台交換器 | Windows「網路連線」裡看得到 `VMware Network Adapter VMnet1/VMnet8` |
| ★★★★★ **虛擬 NAT 裝置** | 一台小型 IP 分享器 | 只掛在 VMnet8 上，負責把 VM 的封包換成主機的來源位址送出去 |
| ★★★★ **虛擬 DHCP 伺服器** | 分享器裡的 DHCP 功能 | 掛在 VMnet1、VMnet8（以及你開啟 DHCP 的自訂 VMnet）上 |

★★★★★ **「網路模式」的本質，就是「這張虛擬網卡要插在哪一台虛擬交換器上」。**
一旦你這樣理解，四種模式就只是四種接線方式而已。

#### ★★★★ VMnet 編號慣例

| VMnet | 預設用途 | 有 NAT？ | 有 DHCP？ | 主機有網卡接上去？ |
| --- | --- | --- | --- | --- |
| ★★★★★ **VMnet0** | **Bridged（橋接）** | ✗ | ✗（用實體網路的 DHCP） | 用實體網卡本身 |
| ★★★★ **VMnet1** | **Host-only（僅限主機）** | ✗ | ✓ | ✓ |
| ★★★★★ **VMnet8** | **NAT** | ✓ | ✓ | ✓ |
| ★★★ VMnet2～VMnet7、VMnet9 以上 | **自訂**，預設不存在 | 可選 | 可選 | 可選 |

> [!note] ★★★ 為什麼是 0、1、8 這三個奇怪的號碼
> 這是 VMware 從很早以前沿用下來的慣例，沒有特別的技術理由。
> ★★★★ 記住就好：**0 = 橋接、1 = 僅限主機、8 = NAT**。
> 在 Linux 主機上，這些會以 `vmnet1`、`vmnet8` 等網路介面的形式出現。

---

### ★★★★★ 二、Bridged（橋接）：VM 直接站在實體網路上

#### 封包路徑

```text
                    ┌──────────────────────────────────────┐
                    │            實體主機（你的桌機）          │
                    │                                      │
  ┌──────────┐      │   ┌──────────┐      ┌────────────┐   │
  │   VM     │      │   │ VMnet0   │      │  主機 OS    │   │
  │ ens33    ├──────┼──►│ 橋接器    │◄─────┤  網路堆疊   │   │
  │10.1.1.57 │      │   │(不做NAT) │      │ 10.1.1.20  │   │
  └──────────┘      │   └────┬─────┘      └────────────┘   │
                    │        │                              │
                    └────────┼──────────────────────────────┘
                             │  ★★★★★ VM 的封包帶著自己的
                             │      MAC 與 IP 直接送出去
                             ▼
                    ┌─────────────────┐
                    │  實體交換器       │  ← 交換器上會看到「兩個 MAC」
                    └────────┬────────┘     （主機一個、VM 一個）
                             │
                    ┌────────▼────────┐
                    │  公司路由器/DHCP  │  ← VM 直接跟它要 IP
                    └────────┬────────┘
                             │
                          網際網路
```

#### ★★★★★ 關鍵特性

| 特性 | 說明 |
| --- | --- |
| VM 的 IP 來源 ★★★★★ | **實體網路的 DHCP**（公司分享器／路由器），不是 VMware 給的 |
| VM 的 IP 網段 ★★★★ | **和主機同網段**（例：主機 10.1.1.20，VM 10.1.1.57） |
| 對外網路而言 ★★★★★ | **VM 是一台獨立的實體電腦**，跟主機是兩台機器 |
| 網路上看到幾個 MAC ★★★★★ | **兩個以上**（主機 + 每一台 Bridged 的 VM） |
| 別人連得進來嗎 ★★★★★ | **連得進來**（只要防火牆放行），不需要埠轉發 |

> [!danger] ★★★★★ Bridged 是四種模式中「暴露程度最高」的
> VM 直接暴露在整個實體網路上。若那台 VM 是**沒更新過的測試機**，
> 它就是網路上的一個破口。
> ★★★★★ **在機關網路上開 Bridged 之前，先確認：**
> 1. 這台 VM 的密碼夠強嗎？
> 2. 防火牆開了嗎？→ [[090-02-02-guide-防火牆-ufw基礎與實務]]
> 3. 機關的資安政策允許嗎？

> [!warning] ★★★★ Bridged 最常見的兩個失敗場景
> 1. ★★★★★ **無線網卡**：許多無線網路（尤其是企業級 AP、802.1X 認證、
>    或有 MAC 過濾的環境）**只允許一個 MAC 位址**。
>    VM 的 MAC 送出去會被 AP 丟掉，結果就是「VM 拿不到 IP」。
> 2. ★★★★★ **公司網路的埠安全（port security）**：
>    交換器上若設了「每埠最多學習 1 個 MAC」，VM 的 MAC 一出現，
>    ★★★★★ **整個埠可能被關掉（err-disable）—— 連你自己的主機都斷網**。
>    這在機關網路上發生過不只一次。
>
> ★★★★★ **這兩種情況的正解都是：改用 NAT 模式。** 見排錯表。

---

### ★★★★★ 三、NAT：VM 躲在主機後面（本手冊預設）

#### 封包路徑

```text
        ┌────────────────────────────────────────────────────────────┐
        │                    實體主機（你的桌機）                        │
        │                                                            │
        │  ┌──────────┐   ┌─────────────────┐   ┌─────────────────┐  │
        │  │   VM     │   │     VMnet8      │   │  主機虛擬網卡     │  │
        │  │ ens33    ├──►│  虛擬交換器      │◄──┤ VMnet8 介面      │  │
        │  │.100.128  │   │                 │   │  192.168.100.1  │  │
        │  └──────────┘   └───┬─────────┬───┘   └─────────────────┘  │
        │                     │         │                            │
        │        ┌────────────▼──┐  ┌───▼──────────────┐             │
        │        │  虛擬 NAT 裝置  │  │  虛擬 DHCP 伺服器  │             │
        │        │ 192.168.100.2 │  │ 192.168.100.254  │             │
        │        │  ★ 也當 DNS   │  └──────────────────┘             │
        │        └────────┬──────┘                                   │
        │                 │  ★★★★★ 在這裡把來源位址換成主機的位址        │
        │        ┌────────▼────────┐                                 │
        │        │  主機實體網卡     │  10.1.1.20                      │
        │        └────────┬────────┘                                 │
        └─────────────────┼──────────────────────────────────────────┘
                          │
                          ▼   對外網路只看到「主機」這一台，
                    實體交換器 / 路由器     看不到 VM 的存在
                          │
                       網際網路
```

#### ★★★★★ NAT 網段的三個固定角色

★★★★★ **這三個位址一定要背起來，排錯時每次都用得到**（`x` 由安裝時隨機決定）：

| 位址 | 角色 | 誰在用 |
| --- | --- | --- |
| `192.168.x.1` ★★★★ | **主機在這個網段上的位址** | 主機虛擬網卡 VMnet8 |
| `192.168.x.2` ★★★★★ | **預設閘道（NAT 裝置）**，通常兼任 **DNS 轉送** | VM 的 default gateway 要指這裡 |
| `192.168.x.254` ★★★★ | **DHCP 伺服器** | 發 IP 給 VM |
| `192.168.x.128–254` ★★★ | 預設的 DHCP 動態範圍（大致，可調） | 自動配發區 |

> [!danger] ★★★★★ 設固定 IP 時最常見的錯誤
> 把預設閘道寫成 `192.168.x.1`（主機那張網卡）。
> ★★★★★ **那個位址不會幫你轉送封包出去，會變成「ping 得到主機，
> 但連不上網際網路」。** 閘道必須是 `.2`。

#### ★★★★ 關鍵特性

| 特性 | 說明 |
| --- | --- |
| VM 的 IP 來源 | VMware 內建 DHCP（`.254`） |
| 對外網路而言 ★★★★★ | **看不到 VM**，只看到主機一台 |
| 網路上看到幾個 MAC ★★★★★ | **只有主機一個** —— 這正是它能在嚴格網路環境存活的原因 |
| VM 上網 ★★★★ | ✓ 可以（經 NAT） |
| 外部連進 VM ★★★★★ | ✗ 預設不行，**要設埠轉發** |
| 換網路環境（辦公室↔家裡）★★★★★ | ✓ **VM 的 IP 完全不變**，這是 NAT 最大的優點 |

> [!tip] ★★★★★ 為什麼本手冊絕大多數實驗都用 NAT
> 1. ★★★★★ **VM 的 IP 不會因為你換網路環境而改變。**
>    筆電從辦公室帶回家，VM 還是 `192.168.100.50`，`ssh` 的設定不用改。
> 2. ★★★★★ **不會在公司網路上多出 MAC**，不會觸發埠安全，不會被資安室關切。
> 3. ★★★★ **VM 有網路可以 `apt update`**，做實驗方便。
> 4. ★★★★ **主機可以直接連到 VM**（同在 VMnet8 上），SSH 完全沒問題。

---

### ★★★★ 四、Host-only（僅限主機）：關在房間裡，只跟主機講話

#### 封包路徑

```text
        ┌──────────────────────────────────────────────────┐
        │                  實體主機                          │
        │                                                  │
        │  ┌──────────┐   ┌─────────────┐  ┌────────────┐  │
        │  │  VM A    ├──►│   VMnet1    │◄─┤ 主機虛擬網卡 │  │
        │  │.1.128    │   │  虛擬交換器   │  │ 192.168.1.1│  │
        │  └──────────┘   │             │  └────────────┘  │
        │  ┌──────────┐   │             │                  │
        │  │  VM B    ├──►│             │  ┌────────────┐  │
        │  │.1.129    │   │             │◄─┤ 虛擬 DHCP   │  │
        │  └──────────┘   └─────────────┘  │ .1.254     │  │
        │                       ✗          └────────────┘  │
        │                       │  ★★★★★ 沒有 NAT 裝置       │
        │                       ✗   封包出不去                │
        │  ┌────────────────┐                               │
        │  │  主機實體網卡    │  （完全沒有連過來）              │
        │  └────────┬───────┘                               │
        └───────────┼──────────────────────────────────────┘
                    ✗   ← ★★★★★ VM 無法連網際網路
                 網際網路
```

#### ★★★★ 關鍵特性

| 特性 | 說明 |
| --- | --- |
| VM 上網 ★★★★★ | ✗ **不行**（沒有 NAT 裝置） |
| VM ↔ 主機 ★★★★ | ✓ 可以（經主機的 VMnet1 網卡） |
| VM ↔ VM（同 VMnet1）★★★★ | ✓ 可以 |
| 外部 ↔ VM ★★★★ | ✗ 完全不行 |
| DHCP ★★★ | ✓ 有（可在虛擬網路編輯器關掉） |

★★★★ **典型用途**：測惡意程式、測不該連外的系統、
或要確保「這台機器絕對不會不小心去更新」的場景。

> [!warning] ★★★★ Host-only 不是「完全隔離」
> 它跟**主機**是通的。若你要的是「連主機都碰不到」的絕對隔離，
> 要用 **LAN Segment**（見下一節）。
> ★★★★★ 這個差別在做惡意程式分析時很重要 —— 主機被打進去就前功盡棄。

---

### ★★★★ 五、自訂 VMnet 與 LAN Segment：自己蓋網段

#### 自訂 VMnet（VMnet2～VMnet7、VMnet9 以上）

★★★★ 你可以自己開一個 VMnet，並**逐項決定**它的行為：

| 可選項 | 開啟時 | 關閉時 |
| --- | --- | --- |
| ★★★★ **連到主機（Host-only 勾選）** | 主機多一張網卡接進去，可以互通 | 主機碰不到這個網段 |
| ★★★★ **NAT** | 這個網段可以上網 | 出不去 |
| ★★★★ **本機 DHCP** | 自動配發 IP | ★★★★★ **要自己在 VM 內設固定 IP** |
| ★★★ **子網位址／遮罩** | 自己指定，例如 `10.10.20.0/24` | — |

★★★★★ **這是模擬「多網段 + 路由」實驗的關鍵工具。**

#### LAN Segment（區域網段）★★★★

```text
   ┌──────────┐        ┌──────────────────┐        ┌──────────┐
   │  VM A    ├───────►│   LAN Segment    │◄───────┤  VM B    │
   │          │        │  「lab-dmz」       │        │          │
   └──────────┘        └──────────────────┘        └──────────┘
                              ✗   ✗
                              │   │
                     主機 ✗───┘   └───✗ 網際網路

   ★★★★★ 完全封閉：沒有主機網卡、沒有 NAT、沒有 DHCP
          VM 之間互通，但對外完全不存在
```

| 特性 | LAN Segment | Host-only |
| --- | --- | --- |
| VM ↔ VM | ✓ | ✓ |
| VM ↔ 主機 | ★★★★★ **✗ 完全不通** | ✓ 通 |
| VM ↔ 外網 | ✗ | ✗ |
| DHCP | ★★★★★ **沒有，一定要自己設固定 IP** | ✓ 有 |
| 建立方式 ★★★ | 在 VM 的網路卡設定裡按「LAN 區段」直接命名建立 | 要用虛擬網路編輯器 |

★★★★★ **LAN Segment 是「真正的隔離」**，也是模擬 DMZ、內網、
或防火牆兩側最乾淨的做法。

---

### ★★★★★ 六、可達性矩陣（查表用）

★★★★★ **這張表印出來貼在螢幕邊。「為什麼 ping 不到」九成能在這裡找到答案。**

| 方向 | Bridged | NAT | Host-only | 自訂 VMnet（全關） | LAN Segment |
| --- | --- | --- | --- | --- | --- |
| **VM ↔ VM（同一個 VMnet）** | ✓ ★★★★ | ✓ ★★★★ | ✓ ★★★★ | ✓ ★★★★ | ✓ ★★★★ |
| **VM ↔ VM（不同 VMnet）** | ✗ ★★★★ | ✗ ★★★★ | ✗ ★★★★ | ✗ ★★★★ | ✗ ★★★★ |
| **VM → 主機** | ✓ ★★★ | ✓（走 `.1`）★★★★ | ✓（走 `.1`）★★★★ | 僅當勾了 Host-only ★★★ | ★★★★★ **✗** |
| **主機 → VM** | ✓ ★★★ | ★★★★★ **✓（同在 VMnet8，直接連）** | ✓ ★★★★ | 僅當勾了 Host-only ★★★ | ★★★★★ **✗** |
| **VM → 外網** | ✓ ★★★★ | ✓（經 NAT）★★★★ | ★★★★★ **✗** | 僅當開了 NAT ★★★ | ✗ ★★★★ |
| **外網 → VM** | ✓（防火牆放行即可）★★★★ | ★★★★★ **✗，需埠轉發** | ✗ ★★★★ | ✗ ★★★★ | ✗ ★★★★ |

> [!danger] ★★★★★ 表中最容易搞混的一格：NAT 模式下「主機 → VM」是通的
> 很多人以為「NAT 就是外面連不進來，所以主機也連不進去」—— **錯**。
> ★★★★★ **主機身上有一張 VMnet8 的網卡，跟 VM 在同一個網段，
> 所以主機可以直接 `ssh` 進 VM，完全不用埠轉發。**
> 埠轉發是給「主機以外的機器」用的。

> [!note] ★★★★ 第二個容易搞混：不同 VMnet 之間預設不通
> VMnet1 上的 VM 和 VMnet8 上的 VM，就像插在兩台沒有互連的交換器上。
> ★★★★★ **要讓它們通，只有一個辦法：找一台有兩張網卡的 VM 當路由器**
> —— 這正是「完整實戰範例」要做的事。

---

### ★★★★★ 七、本手冊各章實驗環境該選哪一種

★★★★★ **這一節是本篇最實用的部分。** 照這張表選，不會錯。

| 你要做的實驗 | 選這個模式 | 為什麼 |
| --- | --- | --- |
| ★★★★★ **學 Linux 指令、Shell 腳本、權限、程序** | **NAT** | 有網路可 `apt install`，主機可 SSH，IP 不隨環境變。→ [[020-01-03-cmd-Linux-終端機與Shell入門]] |
| ★★★★★ **架 Nginx／Apache，要從實體機瀏覽器連進去** | **NAT** | ★★★★★ **主機瀏覽器直接打 VM 的 IP 就通**，不需要埠轉發 |
| ★★★★ **要讓「同事的電腦」也連得進你的測試網站** | ★★★★ **NAT + 埠轉發**，或 **Bridged** | 先試埠轉發；受限於公司網路政策才考慮 Bridged |
| ★★★★ **裝資料庫、PHP-FPM、Laravel 等單機服務** | **NAT** | 同上 |
| ★★★★★ **模擬多網段與路由（防火牆、VLAN 概念）** | ★★★★★ **NAT（對外那張）+ 自訂 VMnet2/3（內網那幾張）** | 路由器 VM 兩張網卡，一張對外一張對內。見「完整實戰範例」 |
| ★★★★ **模擬 DMZ 與內網兩層架構** | **自訂 VMnet2（DMZ）+ VMnet3（內網）** | 各自獨立網段，中間放防火牆 VM |
| ★★★★★ **要絕對隔離（惡意程式、可疑檔案）** | ★★★★★ **LAN Segment** | 主機都碰不到，是四種裡最安全的 |
| ★★★★ **不能連外但要跟主機交換檔案的測試** | **Host-only** | 出不去，但主機通 |
| ★★★★ **多台 VM 組叢集（PVE 巢狀、Ceph 練習）** | ★★★★ **NAT（管理網）+ 自訂 VMnet（叢集網）** | 模擬「管理流量與叢集流量分離」→ [[050-01-03-07-svc-PVE-叢集與高可用]] |
| ★★★ **要模擬「網路斷線」的故障情境** | 任何模式，把網路卡的**「已連線」取消勾選** | 相當於把網路線拔掉，比改模式快 |
| ★★★★ **VM 要當 DHCP／DNS 伺服器練習** | ★★★★★ **自訂 VMnet，並關掉 VMware 的 DHCP** | ★★★★★ 不關的話兩個 DHCP 會打架 |
| ★★★ **筆電在沒有網路的地方做實驗** | **NAT 或 Host-only** | Bridged 在沒有實體網路時拿不到 IP |

> [!tip] ★★★★★ 一句話總結
> **不知道要選什麼的時候，選 NAT。** 本手冊 90% 的實驗都用 NAT，
> 只有「模擬多網段」與「絕對隔離」這兩種情況才需要別的。

---

## 安裝或基礎操作

### ★★★★ 步驟 1：查看與切換單一 VM 的網路模式

**VM → Settings（`Ctrl+D`）→ 左側選 Network Adapter**，右側會看到：

```text
┌─ Device status ────────────────────────────────┐
│  ☑ Connected              ← 相當於「網路線插著」   │
│  ☑ Connect at power on    ← 開機自動連上          │
├─ Network connection ───────────────────────────┤
│  ○ Bridged: Connected directly to the physical │
│    network                                     │
│      ☐ Replicate physical network connection   │
│        state                                   │
│  ● NAT: Used to share the host's IP address    │
│  ○ Host-only: A private network shared with    │
│    the host                                    │
│  ○ Custom: Specific virtual network            │
│      [ VMnet2  ▼ ]                             │
│  ○ LAN segment:  [ (none)  ▼ ]  [ LAN Segments…]│
├────────────────────────────────────────────────┤
│  [ Advanced… ]   ← MAC 位址、頻寬限制、封包遺失模擬 │
└────────────────────────────────────────────────┘
```

| 選項 | 說明 |
| --- | --- |
| ★★★★★ **Connected** | 取消勾選 = **拔網路線**。模擬斷線故障最快的方法 |
| ★★★★ **Connect at power on** | 沒勾的話，開機後網路是斷的（★★★★ 這是「開機後沒網路」的常見原因） |
| ★★★ **Replicate physical network connection state** | Bridged 專用：主機網路斷了，VM 也跟著斷 |
| ★★★★ **Custom** | 指定接到哪一個 VMnet |
| ★★★★ **Advanced…** | ★★★★ 可以**手動指定 MAC**，也可以模擬頻寬限制與封包遺失（做網路測試很好用） |

> [!warning] ★★★★ 大部分設定可以在 VM 開機中改
> 網路模式的切換通常**不需要關機**，改完 VM 內重新取得 IP 即可。
> 但 ★★★★ **新增或移除整張網路卡，多數情況要關機**。
> 改完之後在 VM 內執行 `sudo dhclient -r ens33 && sudo dhclient ens33`
> 或直接 `sudo netplan apply` 重新取得位址。

---

### ★★★★★ 步驟 2：打開虛擬網路編輯器

#### Windows 主機

**Edit → Virtual Network Editor**。

> [!warning] ★★★★★ 一定要按「Change Settings」
> 開啟後畫面預設是**唯讀**的，左下角有一顆 **Change Settings** 按鈕，
> 按下去會提升為系統管理員權限，之後才改得動。
> ★★★★★ **「改了沒反應」九成是忘記按這顆。**

#### Linux 主機

```bash
sudo vmware-netcfg
```

★★★ 若指令不存在，改用 `sudo /usr/bin/vmware-netcfg`；
不同版本的路徑可能不同（本篇未實機驗證）。

#### 畫面內容

```text
┌─ Virtual Network Editor ───────────────────────────────────────┐
│ Name     Type          External Connection   Host Connection  DHCP  Subnet Address │
│ VMnet0   Bridged       Auto-bridging          -               -     -              │
│ VMnet1   Host-only     -                      Connected       Enabled 192.168.181.0│
│ VMnet8   NAT           NAT                    Connected       Enabled 192.168.100.0│
│                                                                                    │
│                      [ Add Network… ] [ Remove Network ] [ Rename Network… ]       │
├────────────────────────────────────────────────────────────────┤
│ VMnet Information                                              │
│  ○ Bridged (connect VMs directly to the external network)      │
│      Bridged to: [ Automatic ▼ ]   [ Automatic Settings… ]     │
│  ● NAT (shared host's IP address with VMs)   [ NAT Settings… ] │
│  ○ Host-only (connect VMs internally in a private network)     │
│  ☑ Connect a host virtual adapter to this network              │
│  ☑ Use local DHCP service to distribute IP address to VMs      │
│      [ DHCP Settings… ]                                        │
│  Subnet IP: [192.168.100.0]  Subnet mask: [255.255.255.0]      │
└────────────────────────────────────────────────────────────────┘
```

★★★★★ **四個最常用的操作**：

| 要做什麼 | 怎麼做 |
| --- | --- |
| ★★★★ 改 NAT 網段 | 選 VMnet8 → 改 **Subnet IP** → Apply |
| ★★★★ 新增自訂網段 | **Add Network…** → 選 VMnet2 → 設定 Host-only／NAT／DHCP |
| ★★★★★ 關掉某網段的 DHCP | 取消 **Use local DHCP service** 勾選 |
| ★★★★ 設 NAT 埠轉發 | 選 VMnet8 → **NAT Settings… → Port Forwarding** |

> [!danger] ★★★★★ 改網段會讓所有 VM 的 IP 全部改變
> 改 VMnet8 的 Subnet IP 之後：
> - 用 DHCP 的 VM：重新取得後會拿到**新網段**的位址
> - ★★★★★ **設了固定 IP 的 VM：直接失聯**，要進主控台改 Netplan
> - ★★★★ **埠轉發規則裡的目的 IP 也要一併改**，否則轉發指到不存在的位址
>
> ★★★★★ **改網段前先把用到它的 VM 清點一遍。**

---

### ★★★★ 步驟 3：查出目前的 NAT 網段是什麼

#### 方法一：從虛擬網路編輯器看（最直接）★★★★

看 VMnet8 那一列的 **Subnet Address** 欄。

#### 方法二：從主機的網路介面看 ★★★★

Windows 主機（PowerShell）：

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.InterfaceAlias -like "*VMnet*" } |
    Select-Object InterfaceAlias, IPAddress, PrefixLength
```

預期輸出：

```text
InterfaceAlias                        IPAddress       PrefixLength
--------------                        ---------       ------------
VMware Network Adapter VMnet1         192.168.181.1             24
VMware Network Adapter VMnet8         192.168.100.1             24
```

Linux 主機：

```bash
ip -4 addr show | grep -A2 vmnet
```

預期輸出：

```text
5: vmnet1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...
    inet 192.168.181.1/24 brd 192.168.181.255 scope global vmnet1
6: vmnet8: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...
    inet 192.168.100.1/24 brd 192.168.100.255 scope global vmnet8
```

★★★★★ **看到 `192.168.100.1` 就知道：網段是 `192.168.100.0/24`、
閘道是 `192.168.100.2`、DHCP 是 `192.168.100.254`。**

#### 方法三：從 VM 內看（最實用）★★★★★

```bash
ip route
```

預期輸出：

```text
default via 192.168.100.2 dev ens33 proto dhcp src 192.168.100.128 metric 100
192.168.100.0/24 dev ens33 proto kernel scope link src 192.168.100.128 metric 100
```

★★★★★ **`default via` 後面那個就是 NAT 閘道。** 記住它，設固定 IP 時要用。

---

### ★★★★ 步驟 4：在 VM 內驗證網路模式是否如預期

一套四個指令，★★★★★ **每次改完網路設定都跑一遍**：

```bash
# 1. 我拿到什麼 IP？
ip -brief addr show

# 2. 我的閘道是誰？
ip route

# 3. 通不通到閘道？
ping -c 3 192.168.100.2

# 4. 出得去嗎？DNS 解得開嗎？
ping -c 3 1.1.1.1
getent hosts tw.archive.ubuntu.com
```

預期輸出：

```text
lo               UNKNOWN        127.0.0.1/8 ::1/128
ens33            UP             192.168.100.128/24 fe80::20c:29ff:fe3a:1b2c/64

default via 192.168.100.2 dev ens33 proto dhcp src 192.168.100.128 metric 100
192.168.100.0/24 dev ens33 proto kernel scope link src 192.168.100.128 metric 100

PING 192.168.100.2 (192.168.100.2) 56(84) bytes of data.
64 bytes from 192.168.100.2: icmp_seq=1 ttl=128 time=0.312 ms
--- 192.168.100.2 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2033ms

PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=55 time=8.42 ms
--- 1.1.1.1 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2004ms

185.125.190.36  tw.archive.ubuntu.com
```

★★★★★ **這四步的診斷邏輯**：

| 哪一步失敗 | 代表什麼 |
| --- | --- |
| 1 沒有 IP | ★★★★★ **DHCP 沒拿到** → 網路卡沒連線／DHCP 被關掉／模式選錯 |
| 2 沒有 default route | ★★★★ 固定 IP 沒設閘道，或 DHCP 只給了位址 |
| 3 ping 不到閘道 | ★★★★ 網段設錯，或不在同一個 VMnet 上 |
| 4 ping 得到 `1.1.1.1` 但域名解不開 | ★★★★★ **純 DNS 問題**，不是網路不通 |
| 3 通但 4 不通 | ★★★★ Host-only 模式（本來就出不去），或主機防火牆擋了 NAT |

---

### ★★★★★ 步驟 5：在 VM 內設固定 IP（Netplan）

★★★★★ **實驗環境的 VM 一定要固定 IP**，否則每次開機 IP 都可能變，
SSH 設定、Nginx 設定、憑證的 SAN 全都要跟著改。

#### 先確認網卡名稱

```bash
ip -brief link show
```

```text
lo               UNKNOWN        00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP>
ens33            UP             00:0c:29:3a:1b:2c <BROADCAST,MULTICAST,UP,LOWER_UP>
```

★★★★ **Workstation 的網卡名稱慣例**：

| 虛擬網卡型別 | 常見介面名稱 |
| --- | --- |
| e1000／e1000e ★★★★ | `ens33`（有時 `ens32`） |
| VMXNET3 ★★★★ | `ens160`（有時 `ens192`） |

★★★★★ **不要照抄別人的名稱，一定要先 `ip -brief link show` 看自己的。**

#### 編輯 Netplan

```bash
sudo nano /etc/netplan/50-cloud-init.yaml
```

```yaml
network:
  version: 2
  ethernets:
    ens33:
      dhcp4: false
      addresses:
        - 192.168.100.50/24
      routes:
        - to: default
          via: 192.168.100.2
      nameservers:
        addresses:
          - 192.168.100.2
          - 1.1.1.1
```

> [!danger] ★★★★★ 三個致命細節
> 1. ★★★★★ **閘道是 `.2` 不是 `.1`。** `.1` 是主機的網卡，不會轉送封包出去。
> 2. ★★★★ **位址要選在 DHCP 動態範圍之外**（預設動態範圍約從 `.128` 起），
>    建議用 `.10`～`.99`，避免跟 DHCP 發出去的位址撞在一起。
> 3. ★★★★★ **YAML 用空格縮排，絕對不能用 Tab。**
>    用 Tab 會得到 `found character '\t' that cannot start any token`。

#### 套用並驗證

```bash
sudo chmod 600 /etc/netplan/50-cloud-init.yaml
sudo netplan try
```

`netplan try` 會套用設定並倒數 120 秒，★★★★★ **沒有按 Enter 確認就自動還原** ——
這是防止把自己鎖在外面的救命機制。確認連線還在，按 Enter：

```text
Do you want to keep these settings?

Press ENTER before the timeout to accept the new configuration

Changes will revert in 118 seconds
Configuration accepted.
```

驗證：

```bash
ip -brief addr show ens33
ip route
ping -c 2 192.168.100.2
ping -c 2 1.1.1.1
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> RHEL 系沒有 Netplan，用 **NetworkManager**。同樣一件事：
>
> ```bash
> # 看目前連線名稱
> nmcli connection show
>
> # 設固定 IP（連線名稱以實際輸出為準，常見為 ens33 或 "System ens33"）
> sudo nmcli connection modify ens33 \
>     ipv4.method manual \
>     ipv4.addresses 192.168.100.50/24 \
>     ipv4.gateway 192.168.100.2 \
>     ipv4.dns "192.168.100.2 1.1.1.1"
>
> # 套用
> sudo nmcli connection up ens33
>
> # 驗證
> nmcli -f IP4 device show ens33
> ```
>
> ★★★★ 閘道一樣是 `.2`，動態範圍一樣要避開。
> ★★★ RHEL 9 已不再使用 `/etc/sysconfig/network-scripts/ifcfg-*`，
> 一律走 NetworkManager 的 keyfile。

---

## 進階應用

### ★★★★ 一、新增一個自訂 VMnet（模擬第二個網段）

情境：要做一個**只有內部機器互通、不能上網**的 `10.10.20.0/24` 網段。

1. **Edit → Virtual Network Editor → Change Settings**
2. **Add Network… → 選 VMnet2 → OK**
3. 選中 VMnet2，設定：

| 選項 | 設定 | 理由 |
| --- | --- | --- |
| 類型 | **Host-only** | ★★★★ 不要選 NAT，我們不想讓它直接上網 |
| ☐ Connect a host virtual adapter | ★★★★ **取消勾選** | 主機不需要接進來（更乾淨的隔離） |
| ☐ Use local DHCP service | ★★★★★ **取消勾選** | 這個網段我們要自己控制 IP |
| Subnet IP | `10.10.20.0` | |
| Subnet mask | `255.255.255.0` | |

4. **Apply → OK**
5. 在要接進去的 VM：**Settings → Network Adapter → Custom → VMnet2**

★★★★★ **因為關掉了 DHCP，這個網段上的每一台 VM 都必須自己設固定 IP。**

```yaml
network:
  version: 2
  ethernets:
    ens34:
      dhcp4: false
      addresses:
        - 10.10.20.11/24
      # ★★★★ 注意：這裡故意不設 routes 與 nameservers
      #        因為這個網段本來就不該上網
```

---

### ★★★★★ 二、NAT 埠轉發：讓外面連進 VM 裡的服務

#### 什麼時候需要

| 情境 | 需要埠轉發嗎 |
| --- | --- |
| ★★★★★ **主機的瀏覽器**要連 VM 的網站 | **不需要**，直接打 `http://192.168.100.50` |
| ★★★★★ **同事的電腦**要連你 VM 的網站 | ★★★★★ **需要** |
| ★★★★ 手機要連 VM 的 API 測試 | ★★★★ 需要 |
| ★★★★ 想用 `localhost:8080` 連 VM 的服務（打字比較快） | ★★★ 可以設，但不是必要 |

#### GUI 設定步驟

1. **Virtual Network Editor → Change Settings**
2. 選 **VMnet8** → **NAT Settings…**
3. **Port Forwarding** 區塊 → **Add…**

```text
┌─ Map Incoming Port ────────────────────┐
│  Host port:        [ 8080 ]            │  ← 主機上開的埠
│  Type:             ( ) TCP  ( ) UDP    │
│  Virtual machine IP address:           │
│                    [ 192.168.100.50 ]  │  ← VM 的 IP
│  Virtual machine port: [ 80 ]          │  ← VM 上服務的埠
│  Description:      [ lab web ]         │
└────────────────────────────────────────┘
```

4. **OK → OK → Apply**

★★★★★ **設完之後，任何能連到「主機 IP」的機器，
打 `http://<主機IP>:8080` 就會被轉到 VM 的 80 埠。**

#### 驗證

在主機上：

```bash
curl -I http://127.0.0.1:8080
```

預期輸出：

```text
HTTP/1.1 200 OK
Server: nginx
Date: Tue, 02 Sep 2026 03:11:47 GMT
Content-Type: text/html
Connection: keep-alive
```

在同事的電腦上（主機 IP 假設為 `10.1.1.20`）：

```bash
curl -I http://10.1.1.20:8080
```

> [!warning] ★★★★★ 埠轉發設好了卻連不進來？依序查這四項
> 1. ★★★★★ **VM 的 IP 是不是固定的？** 若是 DHCP，重開機 IP 一變，
>    轉發規則就指到空氣。**埠轉發的前提永遠是 VM 要有固定 IP。**
> 2. ★★★★ **VM 內的防火牆**有沒有放行？`sudo ufw status`
> 3. ★★★★★ **主機的防火牆**（Windows Defender 防火牆）有沒有擋 8080？
>    ★★★★★ 主機防火牆多半預設只允許「私人網路」，
>    公司網路若被判定為「公用網路」，外面就連不進來。
> 4. ★★★★ **服務有沒有監聽在 `0.0.0.0` 而不是 `127.0.0.1`？**
>    在 VM 內用 `ss -tlnp` 確認。

#### 設定檔位置（進階）★★★

★★★ GUI 改的其實是這個檔案（路徑依版本與 OS 而異，未實機驗證）：

- Windows：`C:\ProgramData\VMware\vmnetnat.conf`
- Linux：`/etc/vmware/vmnet8/nat/nat.conf`

```ini
[incomingtcp]
# 主機埠 = VM位址:VM埠
8080 = 192.168.100.50:80
2222 = 192.168.100.50:22

[incomingudp]
5514 = 192.168.100.60:514
```

★★★★ 手改設定檔之後要重啟 NAT 服務：

- Windows：在「服務」中重啟 **VMware NAT Service**
- Linux：`sudo vmware-networks --stop && sudo vmware-networks --start`

★★★★★ **建議還是用 GUI 改**，手改容易忘記重啟服務，或被 GUI 覆蓋掉。

---

### ★★★★ 三、DHCP 保留：不進 VM 也能固定 IP

★★★★ 若你不想（或不能）進 VM 改 Netplan，可以在 VMware 的 DHCP 上做保留，
綁定 MAC 與 IP。

#### 先查 VM 的 MAC

在 VM 內：

```bash
ip -brief link show ens33
```

```text
ens33            UP             00:0c:29:3a:1b:2c <BROADCAST,MULTICAST,UP,LOWER_UP>
```

★★★ 或在 **VM Settings → Network Adapter → Advanced…** 直接看。

> [!note] ★★★ VMware 的 MAC 前綴
> | 前綴 | 意義 |
> | --- | --- |
> | `00:0C:29` ★★★★ | Workstation 自動產生的 MAC，最常見 |
> | `00:50:56` ★★★ | 手動指定或由 vSphere 配發的範圍 |
> | `00:05:69` ★★ | 較舊版本產生的 MAC |
>
> ★★★★ 看到這三個前綴，就知道那台機器是 VMware 的虛擬機。
> ★★★★★ 反過來說，**這也是資安人員在網路上抓「私接虛擬機」的方法**。

#### 編輯 DHCP 設定檔

★★★ 路徑（依版本與 OS 而異，未實機驗證）：

- Windows：`C:\ProgramData\VMware\vmnetdhcp.conf`
- Linux：`/etc/vmware/vmnet8/dhcpd/dhcpd.conf`

在檔案**結尾**加上（★★★★ 注意檔案裡有「不要編輯這行以上」的註解區，
自訂內容要加在指定的位置）：

```text
host lab-web01 {
    hardware ethernet 00:0c:29:3a:1b:2c;
    fixed-address 192.168.100.50;
}
```

重啟 DHCP 服務後，VM 重新取得位址即可。

| 做法 | 優點 | 缺點 |
| --- | --- | --- |
| ★★★★★ **VM 內設 Netplan** | 跟真實伺服器一樣，**練到的是可以帶去正式環境的技能** | 要進 VM 改 |
| ★★★ **DHCP 保留** | 不用進 VM；VM 複製後改 MAC 就換 IP | ★★★★ 換一台主機做實驗就失效，**不可攜** |

★★★★★ **本手冊主線用 Netplan**，理由是「練到的東西能用在正式環境」。

---

### ★★★★ 四、一台 VM 掛多張網路卡（做路由器／防火牆）

★★★★★ **這是模擬多網段的關鍵技巧。**

1. VM **關機**
2. **Settings → Add… → Network Adapter → Finish**
3. 把第一張設 **NAT**（對外），第二張設 **Custom → VMnet2**（對內）
4. 開機後在 VM 內確認：

```bash
ip -brief addr show
```

```text
lo               UNKNOWN        127.0.0.1/8 ::1/128
ens33            UP             192.168.100.60/24
ens34            UP             10.10.20.1/24
```

★★★★★ **怎麼分辨哪張是哪張？** 兩個方法：

| 方法 | 做法 |
| --- | --- |
| ★★★★ 看 IP | 有 `192.168.100.x` 的就是 NAT 那張 |
| ★★★★★ 對 MAC | 在 **Settings → Network Adapter → Advanced…** 看每張卡的 MAC，
與 `ip -brief link show` 的輸出比對。**這個方法最可靠** |

> [!danger] ★★★★★ 加網卡之後，順序可能會變
> 加了第二張網卡之後，**原本的 `ens33` 有可能變成別的名稱**，
> 導致 Netplan 設定失效、VM 開機後連不上。
> ★★★★★ **加網卡之前先在主控台（不是 SSH）操作**，
> 或改用 Netplan 的 `match` 依 MAC 位址指定，避免被介面改名咬到：
>
> ```yaml
> network:
>   version: 2
>   ethernets:
>     wan:
>       match:
>         macaddress: "00:0c:29:3a:1b:2c"
>       set-name: wan
>       dhcp4: true
>     lan:
>       match:
>         macaddress: "00:0c:29:3a:1b:36"
>       set-name: lan
>       dhcp4: false
>       addresses: [10.10.20.1/24]
> ```

---

### ★★★ 五、直接編輯 `.vmx` 檔（進階／批次）

★★★ VM 的網路設定最終存在 `.vmx` 檔裡（VM 必須**關機**才能改）：

```text
ethernet0.present = "TRUE"
ethernet0.connectionType = "nat"
ethernet0.virtualDev = "e1000e"
ethernet0.addressType = "generated"
ethernet0.generatedAddress = "00:0c:29:3a:1b:2c"
ethernet0.startConnected = "TRUE"

ethernet1.present = "TRUE"
ethernet1.connectionType = "custom"
ethernet1.vnet = "VMnet2"
ethernet1.virtualDev = "e1000e"
ethernet1.startConnected = "TRUE"
```

| 參數 | 可用值 | 說明 |
| --- | --- | --- |
| `connectionType` ★★★★ | `bridged` / `nat` / `hostonly` / `custom` | 網路模式 |
| `vnet` ★★★★ | `VMnet2` 等 | `custom` 時指定哪一個 VMnet |
| `startConnected` ★★★ | `TRUE` / `FALSE` | 相當於「Connect at power on」 |
| `virtualDev` ★★★ | `e1000` / `e1000e` / `vmxnet3` | 虛擬網卡型別 |
| `addressType` ★★★ | `generated` / `static` | MAC 產生方式 |

> [!warning] ★★★★★ 改 `.vmx` 的兩條鐵律
> 1. ★★★★★ **VM 一定要完全關機**（不是暫停），否則 Workstation 會覆蓋掉你的修改。
> 2. ★★★★ **先備份 `.vmx`**。這個檔壞掉，VM 就開不起來。
>
> ★★★ 日常操作請用 GUI；改 `.vmx` 只在要批次處理很多台時才划算。

---

## 完整實戰範例

### 情境

★★★★★ **目標：建一個「雙網段 + 路由器」的實驗環境**，
用來練習路由、防火牆與網段隔離，並讓**同事的電腦**也能連到內網那台的網站。

```text
                                    ┌─────────────────────┐
   同事的電腦 ──► 主機 IP:8080 ──►   │   實體主機（你的桌機） │
                                    │  10.1.1.20          │
                                    └──────────┬──────────┘
                                               │ NAT 埠轉發 8080
                                    ┌──────────▼──────────┐
   ┌───────────────────────────┐    │      VMnet8 (NAT)   │
   │  lab-router               │    │   192.168.100.0/24  │
   │  ens33: 192.168.100.60 ───┼────┤   閘道 .2            │
   │  ens34: 10.10.20.1        │    └─────────────────────┘
   │  ★ 開啟 IP 轉送 + NAT      │
   └───────────┬───────────────┘
               │
   ┌───────────▼───────────────┐
   │      VMnet2（自訂，無 DHCP） │
   │      10.10.20.0/24        │
   └───────────┬───────────────┘
               │
   ┌───────────▼───────────────┐
   │  lab-web01                │
   │  ens33: 10.10.20.11       │
   │  跑 Nginx（80 埠）          │
   │  ★ 沒有對外通路，只能經 router │
   └───────────────────────────┘
```

**前置條件**：手上有一台裝好的 `lab-ubuntu-base`（見
[[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]]），
並已打好 `clean-base` 快照。

---

### 步驟 1：建立自訂網段 VMnet2 ★★★★

1. **Edit → Virtual Network Editor → Change Settings**
2. **Add Network… → VMnet2 → OK**
3. 設定：
   - 類型：**Host-only**
   - ☐ Connect a host virtual adapter to this network（**取消勾選**）
   - ☐ Use local DHCP service（★★★★★ **取消勾選**）
   - Subnet IP：`10.10.20.0`　Subnet mask：`255.255.255.0`
4. **Apply**

驗證（Windows 主機，PowerShell）：

```powershell
Get-NetAdapter | Where-Object { $_.Name -like "*VMnet*" } | Select-Object Name, Status
```

```text
Name                            Status
----                            ------
VMware Network Adapter VMnet1   Up
VMware Network Adapter VMnet8   Up
```

★★★★★ **VMnet2 不應該出現在這裡** —— 因為我們取消了「連到主機」，
主機身上不會有它的網卡。**看不到才是對的。**

---

### 步驟 2：從範本複製兩台 VM ★★★★

依 [[050-01-02-03-guide-Workstation-快照與複製]] 的做法，
從 `lab-ubuntu-base` 的 `clean-base` 快照**連結複製**兩台：

| 名稱 | 角色 |
| --- | --- |
| `lab-router` | 兩張網卡，做路由 |
| `lab-web01` | 一張網卡，只在內網 |

★★★★★ **複製後一定要做的三件事**（否則兩台會互相干擾）：

```bash
# 1. 改主機名稱
sudo hostnamectl set-hostname lab-router

# 2. 改 /etc/hosts 裡的舊名稱
sudo sed -i 's/lab-ubuntu-base/lab-router/g' /etc/hosts

# 3. ★★★★★ 重新產生 machine-id（否則兩台會拿到同一個 DHCP 位址）
sudo rm -f /etc/machine-id
sudo systemd-machine-id-setup
```

驗證：

```bash
hostnamectl | head -3
cat /etc/machine-id
```

```text
 Static hostname: lab-router
       Icon name: computer-vm
         Chassis: vm
b3c1f0a24e6d4b0f9a7e2c81d5f60934
```

---

### 步驟 3：設定 `lab-router` 的兩張網卡 ★★★★★

**VM 關機** → **Settings → Add… → Network Adapter → Finish**，然後：

| 網卡 | 模式 |
| --- | --- |
| Network Adapter | **NAT** |
| Network Adapter 2 | **Custom → VMnet2** |

開機後確認兩張卡與各自的 MAC：

```bash
ip -brief link show
```

```text
lo               UNKNOWN        00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP>
ens33            UP             00:0c:29:3a:1b:2c <BROADCAST,MULTICAST,UP,LOWER_UP>
ens34            DOWN           00:0c:29:3a:1b:36 <BROADCAST,MULTICAST>
```

★★★★ `ens34` 顯示 `DOWN` 是正常的 —— 還沒設定，所以沒有啟用。

編輯 Netplan：

```bash
sudo nano /etc/netplan/50-cloud-init.yaml
```

```yaml
network:
  version: 2
  ethernets:
    ens33:
      dhcp4: false
      addresses:
        - 192.168.100.60/24
      routes:
        - to: default
          via: 192.168.100.2
      nameservers:
        addresses: [192.168.100.2, 1.1.1.1]
    ens34:
      dhcp4: false
      addresses:
        - 10.10.20.1/24
      # ★★★★★ 內網這張不設 default route，
      #        否則會有兩條預設路由互相打架
```

```bash
sudo chmod 600 /etc/netplan/50-cloud-init.yaml
sudo netplan try
```

驗證：

```bash
ip -brief addr show
ip route
```

```text
lo               UNKNOWN        127.0.0.1/8 ::1/128
ens33            UP             192.168.100.60/24
ens34            UP             10.10.20.1/24

default via 192.168.100.2 dev ens33 proto static
10.10.20.0/24 dev ens34 proto kernel scope link src 10.10.20.1
192.168.100.0/24 dev ens33 proto kernel scope link src 192.168.100.60
```

★★★★★ **只有一條 `default via`** —— 這是對的。

---

### 步驟 4：設定 `lab-web01`（只在內網） ★★★★

**Settings → Network Adapter → Custom → VMnet2**（只有這一張）。

★★★★★ **因為 VMnet2 沒有 DHCP，這台開機後不會有 IP，
必須從 Workstation 的主控台視窗登入**（不能 SSH，因為還不通）。

```bash
sudo hostnamectl set-hostname lab-web01
sudo nano /etc/netplan/50-cloud-init.yaml
```

```yaml
network:
  version: 2
  ethernets:
    ens33:
      dhcp4: false
      addresses:
        - 10.10.20.11/24
      routes:
        - to: default
          via: 10.10.20.1     # ★★★★★ 閘道指向 lab-router 的內網卡
      nameservers:
        addresses: [192.168.100.2, 1.1.1.1]
```

```bash
sudo chmod 600 /etc/netplan/50-cloud-init.yaml
sudo netplan apply
ip route
ping -c 2 10.10.20.1
```

```text
default via 10.10.20.1 dev ens33 proto static
10.10.20.0/24 dev ens33 proto kernel scope link src 10.10.20.11

PING 10.10.20.1 (10.10.20.1) 56(84) bytes of data.
64 bytes from 10.10.20.1: icmp_seq=1 ttl=64 time=0.428 ms
--- 10.10.20.1 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss, time 1002ms
```

★★★★ **ping 得到 router 了**。但現在還上不了網：

```bash
ping -c 2 1.1.1.1
```

```text
PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
--- 1.1.1.1 ping statistics ---
2 packets transmitted, 0 received, 100% packet loss, time 1023ms
```

★★★★★ **這是預期的** —— router 還沒開啟轉送功能。

---

### 步驟 5：在 `lab-router` 上開啟 IP 轉送與 NAT ★★★★★

回到 `lab-router`：

```bash
# 1. 開啟 IPv4 轉送（永久生效）
echo 'net.ipv4.ip_forward=1' | sudo tee /etc/sysctl.d/99-lab-router.conf
sudo sysctl --system | grep ip_forward
```

```text
* Applying /etc/sysctl.d/99-lab-router.conf ...
net.ipv4.ip_forward = 1
```

```bash
# 2. 設定 NAT（把 10.10.20.0/24 的來源位址換成 router 的對外位址）
sudo apt update && sudo apt install -y nftables
sudo nft add table ip lab
sudo nft 'add chain ip lab postrouting { type nat hook postrouting priority srcnat; }'
sudo nft add rule ip lab postrouting ip saddr 10.10.20.0/24 oifname "ens33" masquerade

# 3. 確認規則
sudo nft list table ip lab
```

```text
table ip lab {
	chain postrouting {
		type nat hook postrouting priority srcnat; policy accept;
		ip saddr 10.10.20.0/24 oifname "ens33" masquerade
	}
}
```

```bash
# 4. 存檔讓重開機後仍生效
sudo sh -c 'nft list ruleset > /etc/nftables.conf'
sudo systemctl enable --now nftables
```

★★★★ 回到 `lab-web01` 驗證：

```bash
ping -c 2 1.1.1.1
getent hosts tw.archive.ubuntu.com
```

```text
PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=54 time=9.13 ms
--- 1.1.1.1 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss, time 1002ms

185.125.190.36  tw.archive.ubuntu.com
```

★★★★★ **內網那台透過 router 上網了。** 這就是「兩個 VMnet 之間怎麼互通」的答案。

---

### 步驟 6：在 `lab-web01` 上架 Nginx ★★★★

```bash
sudo apt update && sudo apt install -y nginx
echo '<h1>lab-web01 on 10.10.20.11</h1>' | sudo tee /var/www/html/index.html
sudo systemctl enable --now nginx
ss -tlnp | grep ':80'
```

```text
LISTEN 0      511          0.0.0.0:80        0.0.0.0:*    users:(("nginx",pid=1421,fd=5))
LISTEN 0      511             [::]:80           [::]:*    users:(("nginx",pid=1421,fd=5))
```

★★★★★ **`0.0.0.0:80` 很重要** —— 若這裡顯示 `127.0.0.1:80`，
外面永遠連不進來。

在 `lab-router` 上測試（同網段，應該直接通）：

```bash
curl -I http://10.10.20.11
```

```text
HTTP/1.1 200 OK
Server: nginx/1.24.0 (Ubuntu)
Content-Type: text/html
Connection: keep-alive
```

---

### 步驟 7：把服務一路轉發到主機外面 ★★★★★

現在的問題：**主機與同事的電腦都在 `192.168.100.0/24` 或實體網路上，
碰不到 `10.10.20.11`**。需要兩層轉發。

#### 第一層：router 上的埠轉發（10.10.20.11:80 → router:8080）

```bash
# 在 lab-router 上
sudo nft 'add chain ip lab prerouting { type nat hook prerouting priority dstnat; }'
sudo nft add rule ip lab prerouting iifname "ens33" tcp dport 8080 dnat to 10.10.20.11:80
sudo sh -c 'nft list ruleset > /etc/nftables.conf'
```

主機上測試（★★★★★ 主機與 router 同在 VMnet8，所以主機打得到）：

```bash
curl -s http://192.168.100.60:8080
```

```text
<h1>lab-web01 on 10.10.20.11</h1>
```

#### 第二層：Workstation 的 NAT 埠轉發（主機:8080 → 192.168.100.60:8080）

1. **Virtual Network Editor → Change Settings → VMnet8 → NAT Settings… → Add…**

| 欄位 | 值 |
| --- | --- |
| Host port | `8080` |
| Type | TCP |
| Virtual machine IP address | `192.168.100.60` |
| Virtual machine port | `8080` |
| Description | `lab-web01 via router` |

2. **OK → OK → Apply**

主機上測試：

```bash
curl -s http://127.0.0.1:8080
```

```text
<h1>lab-web01 on 10.10.20.11</h1>
```

同事的電腦上（主機 IP 為 `10.1.1.20`）：

```bash
curl -s http://10.1.1.20:8080
```

```text
<h1>lab-web01 on 10.10.20.11</h1>
```

★★★★★ **完成。封包路徑走了整整四層 NAT**：

```text
同事的電腦 10.1.1.x
   │  http://10.1.1.20:8080
   ▼
主機 10.1.1.20  （Workstation NAT 埠轉發）
   │  → 192.168.100.60:8080
   ▼
lab-router ens33 192.168.100.60  （nftables DNAT）
   │  → 10.10.20.11:80
   ▼
lab-web01 10.10.20.11:80  → Nginx 回應
```

---

### 步驟 8：驗證隔離確實有效 ★★★★

★★★★★ **做完要反過來驗證「不該通的真的不通」**，否則隔離是假的。

在**主機**上直接試內網位址：

```bash
ping -c 2 10.10.20.11
```

```text
PING 10.10.20.11 (10.10.20.11) 56(84) bytes of data.
--- 10.10.20.11 ping statistics ---
2 packets transmitted, 0 received, 100% packet loss, time 1024ms
```

★★★★★ **不通才是對的。** 主機沒有 VMnet2 的網卡，也沒有到 `10.10.20.0/24` 的路由，
唯一的通路就是我們刻意開的那條 8080 埠轉發。

在 `lab-web01` 上確認自己確實只有一張網卡、一條出路：

```bash
ip -brief addr show
ip route
```

```text
lo               UNKNOWN        127.0.0.1/8 ::1/128
ens33            UP             10.10.20.11/24

default via 10.10.20.1 dev ens33 proto static
10.10.20.0/24 dev ens33 proto kernel scope link src 10.10.20.11
```

---

### 完成確認 ★★★★★

| 檢查項 | 驗證指令／方法 | 預期 |
| --- | --- | --- |
| VMnet2 存在且無 DHCP、無主機網卡 | 虛擬網路編輯器 | 主機的網路連線裡看不到 VMnet2 |
| `lab-router` 有兩張卡、只有一條預設路由 | `ip route` | 只有一行 `default via 192.168.100.2` |
| `lab-web01` 可 ping 到 router | `ping 10.10.20.1` | 0% loss |
| `lab-web01` 可上網 | `ping 1.1.1.1` | 0% loss |
| `lab-web01` DNS 可用 | `getent hosts tw.archive.ubuntu.com` | 有回應 IP |
| Nginx 監聽 `0.0.0.0:80` | `ss -tlnp \| grep :80` | 顯示 `0.0.0.0:80` |
| 主機可經 router 連到網站 | `curl http://192.168.100.60:8080` | 回傳 HTML |
| 主機可經埠轉發連到網站 | `curl http://127.0.0.1:8080` | 回傳 HTML |
| ★★★★★ 主機**不能**直接連內網 | `ping 10.10.20.11` | **100% loss（正確）** |
| 重開機後設定仍在 | 全部重開機再測一次 | 全部通過 |

★★★★★ **最後一列最重要。** 沒有重開機驗證過的設定，不能算做完。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| VM 開機後完全沒有 IP，`ip a` 只有 `lo` ★★★★★ | 網路卡的 **Connect at power on** 沒勾，或 **Connected** 被取消 | VM Settings → Network Adapter，兩個勾選框都勾起來 |
| Bridged 模式下 VM 拿不到 IP（有線正常，無線就不行）★★★★★ | ★★★★★ **無線 AP 只允許一個 MAC**，或有 802.1X 認證 | **改用 NAT 模式**。這是無線環境下唯一可靠的做法 |
| 一開 Bridged，連主機自己都斷網 ★★★★★ | 交換器埠安全（port security）偵測到第二個 MAC，把埠 `err-disable` | ★★★★★ **立刻改回 NAT**；請網管重新啟用該埠。**在機關網路上請避免 Bridged** |
| Bridged 拿到 `169.254.x.x` ★★★★ | 找不到 DHCP（自動橋接綁到錯的實體網卡，例如綁到沒插線的有線網卡） | 虛擬網路編輯器 → VMnet0 → **Automatic Settings…** → 只勾選實際在用的那張網卡 |
| NAT 模式，`ping` 得到主機但上不了網 ★★★★★ | ★★★★★ **閘道設成 `.1`（主機網卡）而不是 `.2`（NAT 裝置）** | Netplan 的 `via` 改成 `192.168.x.2`，`sudo netplan apply` |
| `ping 1.1.1.1` 通，但 `apt update` 失敗 ★★★★★ | 純 DNS 問題，`nameservers` 沒設或設錯 | Netplan 的 `nameservers.addresses` 加 `192.168.x.2`；`resolvectl status` 確認 |
| 改了網段之後 VM 全部失聯 ★★★★★ | 設固定 IP 的 VM 還留在舊網段 | 從 Workstation **主控台視窗**（不是 SSH）登入，改 Netplan 到新網段 |
| 埠轉發設好了，主機 `curl 127.0.0.1:8080` 不通 ★★★★ | VM 的 IP 是 DHCP，重開機後變了，轉發規則指到空位址 | ★★★★★ **埠轉發的前提是 VM 固定 IP**；先設好 Netplan 再設轉發 |
| 主機自己連得到，同事連不到 ★★★★★ | ★★★★★ **主機的 Windows 防火牆**擋住，或該網路被判定為「公用網路」 | 在主機防火牆為該埠建立輸入規則，並確認網路設定檔為「私人」 |
| 服務在 VM 內 `curl 127.0.0.1` 通、從外面不通 ★★★★★ | 服務只監聽 `127.0.0.1`，沒有監聽 `0.0.0.0` | `ss -tlnp` 確認；改服務設定監聽 `0.0.0.0` 或指定位址 |
| VM 之間 ping 不到，明明都在同一台主機上 ★★★★ | ★★★★★ **兩台在不同的 VMnet 上**（一台 NAT、一台 Host-only） | 查可達性矩陣；把兩台改到同一個 VMnet，或加一台雙網卡 router |
| 兩台複製出來的 VM 搶同一個 IP ★★★★★ | 複製時沒重新產生 `machine-id`（DHCP 用它當識別碼） | `sudo rm -f /etc/machine-id && sudo systemd-machine-id-setup`，重開機 |
| 加了第二張網卡之後，SSH 連不上了 ★★★★★ | ★★★★★ 介面改名（`ens33` → 別的），Netplan 設定套不上 | 從主控台登入，`ip -brief link show` 確認新名稱；改用 `match: macaddress` + `set-name` |
| Netplan 套用失敗：`found character '\t'` ★★★★ | YAML 用了 Tab 縮排 | 全部改成空格。★★★★ 編輯器設定「Tab 轉空格」 |
| Netplan 警告權限太寬 ★★★ | 設定檔權限預設為 `644` | `sudo chmod 600 /etc/netplan/*.yaml` |
| 虛擬網路編輯器改了設定但沒生效 ★★★★★ | ★★★★★ **忘記按左下角的「Change Settings」提升權限**，或沒按 Apply | 按 Change Settings → 重改 → Apply → OK |
| VMnet2 上的 VM 一直拿不到 IP ★★★★ | 該網段刻意關掉了 DHCP | ★★★★★ 這是設計如此，**必須手動設固定 IP** |
| 自訂網段的 VM 有 IP 但上不了網 ★★★★ | 該 VMnet 沒開 NAT，且沒有 router VM 做轉送 | 開 NAT，或依「完整實戰範例」建一台 router VM |
| VM 自己架的 DHCP 發不出 IP ★★★★★ | ★★★★★ **VMware 的 DHCP 也在同一個網段上搶答**，兩個 DHCP 打架 | 虛擬網路編輯器裡把該 VMnet 的 **Use local DHCP service** 取消勾選 |
| 抓封包時看不到其他 VM 的流量 ★★★ | 虛擬交換器預設不允許混雜模式（promiscuous mode） | Linux 主機需調整 `/dev/vmnet*` 的權限；★★★ 一般實驗改用「在目標 VM 上抓」更簡單 |
| 主機睡眠喚醒後 VM 網路不通 ★★★ | 虛擬網路服務在喚醒後狀態異常 | 重啟 VMware NAT／DHCP 服務；或把 VM 的網路卡取消勾選 Connected 再勾回來 |

---

## 安全性注意事項

### ★★★★★ 一、Bridged 是把測試機直接放到機關網路上

★★★★★ **這是本篇最重要的資安提醒。**
Bridged 模式下，那台**沒更新過、密碼是 `test1234`、防火牆沒開**的實驗機，
就是機關網路上的一台真實主機，任何人都掃得到、連得到。

| 情境 | 建議 |
| --- | --- |
| 在機關網路上做實驗 ★★★★★ | **一律用 NAT**，不要用 Bridged |
| 真的必須用 Bridged ★★★★ | 先開防火牆、改強密碼、關掉不必要的服務、**做完立刻改回 NAT** |
| 家裡／隔離的實驗網路 ★★★ | Bridged 可接受，但仍建議開防火牆 |

★★★★ 防火牆做法見 [[090-02-02-guide-防火牆-ufw基礎與實務]]。

### ★★★★★ 二、埠轉發等於在主機上開了一個對外的門

設了 `8080 → 192.168.100.50:80`，就代表**任何連得到你主機的人**
都能連到那台 VM 的網站。

| 要做的事 | 說明 |
| --- | --- |
| ★★★★★ **用完就刪** | 實驗結束後把埠轉發規則刪掉，不要一直留著 |
| ★★★★ **不要轉發 22 埠** | 把 VM 的 SSH 開到實體網路上，風險極高 |
| ★★★★ **用高位埠不用標準埠** | 用 8080 而不是 80，降低被自動掃描器命中的機率 |
| ★★★★ **主機防火牆限制來源** | 只允許特定同事的 IP 連該埠 |
| ★★★★★ **不要轉發含真實資料的服務** | 實驗機上不該有機關資料；有的話更不該開對外 |

### ★★★★ 三、實驗機上不要放任何真實資料與憑證

★★★★★ **實驗環境的定位是「可以隨時砍掉重建」**，
所以它的備份、稽核、修補一定不如正式環境。因此：

- ★★★★★ 不要把機關的資料庫倒進實驗機
- ★★★★★ 不要在實驗機放正式環境的**私鑰、憑證、API token**
- ★★★★ 實驗機的密碼**不可以**與正式環境相同
- ★★★ 練習用的憑證一律自簽 → [[090-01-05-guide-PKI-自簽憑證快速產生]]

### ★★★★ 四、Host-only 不等於隔離，LAN Segment 才是

★★★★★ **要分析可疑檔案或惡意程式時，Host-only 不夠。**
Host-only 與主機是通的，惡意程式可以嘗試攻擊主機。

| 隔離需求 | 該用 |
| --- | --- |
| 只是不想連外 ★★★ | Host-only |
| ★★★★★ **真正的隔離分析** | **LAN Segment**（主機完全碰不到）＋ 分析完直接還原快照 |

★★★★ 且要記得：**分析完務必還原到乾淨快照**，不要留著繼續用。

### ★★★ 五、虛擬機的 MAC 在網路上是看得出來的

`00:0C:29`、`00:50:56`、`00:05:69` 這些前綴一出現在交換器的 MAC 表上，
網管就知道有人在跑虛擬機。★★★★ **不要以為 Bridged 開了沒人會發現** ——
機關的資安監控通常會抓這個。若有正當需求，事前向資安單位報備。

### ★★★ 六、共享資料夾與網路是兩條獨立的攻擊路徑

★★★★ 就算網路設成 Host-only 或 LAN Segment，
若你開了 **共享資料夾（Shared Folders）**，VM 仍然碰得到主機的檔案。
★★★★★ **做隔離分析時，共享資料夾與拖放、剪貼簿共享要一併關掉。**
見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]]。

---

## 速查表

### 四種模式一行判斷

| 模式 | VMnet | 一句話 |
| --- | --- | --- |
| **Bridged** ★★★★ | VMnet0 | VM 是實體網路上的一台獨立電腦 |
| **NAT** ★★★★★ | VMnet8 | VM 躲在主機後面；**本手冊預設** |
| **Host-only** ★★★★ | VMnet1 | 只跟主機通，出不去 |
| **自訂 VMnet** ★★★★ | VMnet2～7、9+ | 自己蓋網段，NAT／DHCP／主機網卡逐項可選 |
| **LAN Segment** ★★★★ | — | 完全封閉，連主機都碰不到，**沒有 DHCP** |

### NAT 網段三個固定位址

| 位址 | 角色 |
| --- | --- |
| `192.168.x.1` ★★★★ | 主機的 VMnet8 網卡（**不是閘道**） |
| `192.168.x.2` ★★★★★ | **預設閘道 + DNS 轉送** |
| `192.168.x.254` ★★★★ | DHCP 伺服器 |
| `192.168.x.128–254` ★★★ | 預設動態範圍（固定 IP 請避開，用 `.10`–`.99`） |

### 可達性矩陣（極簡版）

| 方向 | Bridged | NAT | Host-only | LAN Seg |
| --- | --- | --- | --- | --- |
| VM ↔ 同網段 VM | ✓ | ✓ | ✓ | ✓ |
| VM ↔ 主機 | ✓ | ✓ | ✓ | ★★★★★ ✗ |
| VM → 外網 | ✓ | ✓ | ✗ | ✗ |
| 外網 → VM | ✓ | ★★★★★ 需埠轉發 | ✗ | ✗ |

### 實驗要用哪一種

| 實驗 | 模式 |
| --- | --- |
| 學 Linux 指令 ★★★★★ | NAT |
| 架 Web 從主機瀏覽器連 ★★★★★ | NAT（不需埠轉發） |
| 讓同事連進來 ★★★★ | NAT + 埠轉發 |
| 多網段與路由 ★★★★★ | NAT + 自訂 VMnet |
| 絕對隔離 ★★★★★ | LAN Segment |
| 不連外但要跟主機互通 ★★★★ | Host-only |
| 練習架 DHCP 伺服器 ★★★★ | 自訂 VMnet（**關掉 VMware DHCP**） |

### 常用操作路徑

| 要做什麼 | 路徑 |
| --- | --- |
| 改單台 VM 的模式 ★★★★ | VM → Settings（`Ctrl+D`）→ Network Adapter |
| 模擬拔網路線 ★★★★ | 同上，取消 **Connected** 勾選 |
| 看／改 MAC ★★★ | 同上 → **Advanced…** |
| 開虛擬網路編輯器（Windows）★★★★ | Edit → Virtual Network Editor → **Change Settings** |
| 開虛擬網路編輯器（Linux）★★★ | `sudo vmware-netcfg` |
| 新增 VMnet ★★★★ | 編輯器 → **Add Network…** |
| 設埠轉發 ★★★★★ | 編輯器 → VMnet8 → **NAT Settings… → Port Forwarding → Add…** |
| 關某網段的 DHCP ★★★★ | 編輯器 → 選該 VMnet → 取消 **Use local DHCP service** |

### VM 內驗證四步

| # | 指令 | 看什麼 |
| --- | --- | --- |
| 1 ★★★★ | `ip -brief addr show` | 有沒有拿到 IP |
| 2 ★★★★★ | `ip route` | `default via` 是不是 `.2` |
| 3 ★★★★ | `ping -c 3 192.168.x.2` | 通不通到閘道 |
| 4 ★★★★ | `ping -c 3 1.1.1.1` ＋ `getent hosts <網域>` | 分辨「不通」還是「DNS 壞」 |
| 補 ★★★★★ | `ss -tlnp \| grep ':80'` | 服務有沒有監聽 `0.0.0.0` |

### Netplan 固定 IP 範本

```yaml
network:
  version: 2
  ethernets:
    ens33:
      dhcp4: false
      addresses: [192.168.100.50/24]
      routes:
        - to: default
          via: 192.168.100.2      # ★★★★★ 是 .2 不是 .1
      nameservers:
        addresses: [192.168.100.2, 1.1.1.1]
```

| 步驟 | 指令 |
| --- | --- |
| 修權限 ★★★ | `sudo chmod 600 /etc/netplan/*.yaml` |
| 安全套用 ★★★★★ | `sudo netplan try`（120 秒沒確認自動還原） |
| 直接套用 ★★★ | `sudo netplan apply` |
| 檢查語法 ★★★ | `sudo netplan generate` |

### `.vmx` 網路參數

| 參數 | 值 |
| --- | --- |
| `ethernet0.connectionType` ★★★★ | `bridged` / `nat` / `hostonly` / `custom` |
| `ethernet0.vnet` ★★★★ | `VMnet2`（`custom` 時使用） |
| `ethernet0.startConnected` ★★★ | `TRUE` / `FALSE` |
| `ethernet0.virtualDev` ★★★ | `e1000` / `e1000e` / `vmxnet3` |

### VMware MAC 前綴

| 前綴 | 意義 |
| --- | --- |
| `00:0C:29` ★★★★ | Workstation 自動產生 |
| `00:50:56` ★★★ | 手動指定或 vSphere 配發 |
| `00:05:69` ★★ | 舊版本產生 |

---

## 練習題

> [!question]- 練習 1：判斷模式並驗證 ★★★★
> 你接手一台別人建的 VM，`ip route` 顯示：
>
> ```text
> default via 10.1.1.254 dev ens33 proto dhcp src 10.1.1.87 metric 100
> 10.1.1.0/24 dev ens33 proto kernel scope link src 10.1.1.87 metric 100
> ```
>
> 主機的 IP 是 `10.1.1.20`。請判斷這台 VM 是哪一種網路模式，並說出兩個判斷理由。
> 若你要把它改成 NAT，改完之後要做哪三件事？
>
> ★★★★★ 參考答案：
> **是 Bridged 模式。** 兩個理由：
> 1. ★★★★★ **VM 的 IP 與主機同網段**（`10.1.1.87` vs `10.1.1.20`），
>    這是 Bridged 的標誌。NAT 模式下 VM 會在 `192.168.x.0/24` 之類的私有網段。
> 2. ★★★★ **閘道是 `10.1.1.254`**，那是實體網路的路由器，不是 VMware 的 `.2`。
>
> **改成 NAT 之後要做三件事**：
> 1. VM 內重新取得位址：`sudo netplan apply` 或 `sudo dhclient -r ens33 && sudo dhclient ens33`
> 2. ★★★★★ **重新確認閘道**：`ip route` 應顯示 `default via 192.168.x.2`
> 3. ★★★★ **更新所有指向舊 IP 的設定**：SSH 的 `~/.ssh/config`、
>    Nginx 的 `server_name`、`/etc/hosts`、監控設定等

> [!question]- 練習 2：查可達性矩陣 ★★★★★
> 三台 VM：
> - `vm-a`：NAT
> - `vm-b`：NAT
> - `vm-c`：Host-only（VMnet1）
>
> 請回答（並說明原因）：
> (a) `vm-a` ping 得到 `vm-b` 嗎？
> (b) `vm-a` ping 得到 `vm-c` 嗎？
> (c) 主機 ping 得到 `vm-c` 嗎？
> (d) `vm-c` 可以 `apt update` 嗎？
> (e) 要讓 `vm-c` 也能上網，有哪兩種做法？
>
> ★★★★★ 參考答案：
> **(a) 可以。** 兩台都在 VMnet8 這台虛擬交換器上，同一個網段。
>
> **(b) 不行。** ★★★★★ **不同 VMnet 之間預設不通**，
> 就像插在兩台沒有互連的交換器上。
>
> **(c) 可以。** 主機身上有一張 VMnet1 的網卡（`192.168.x.1`），
> 與 `vm-c` 同網段。
>
> **(d) 不行。** ★★★★★ Host-only 網段上**沒有 NAT 裝置**，封包出不去。
>
> **(e) 兩種做法**：
> 1. ★★★★ 把 `vm-c` 改成 **NAT 模式**（最簡單）
> 2. ★★★★★ 給 `vm-c` **加第二張 NAT 網卡**，或建一台
>    「一張 NAT + 一張 Host-only」的 router VM 做轉送
>    （做法見「完整實戰範例」步驟 5）

> [!question]- 練習 3：埠轉發的四層排錯 ★★★★★
> 你設好了埠轉發 `8080 → 192.168.100.50:80`，
> 但同事打 `http://<你的主機IP>:8080` 連不上。
> 而你自己在主機上 `curl http://192.168.100.50` 是通的。
>
> 請列出你的排查順序（至少四步），每一步寫出指令或檢查點。
>
> ★★★★★ 參考答案：
> 因為「主機直連 VM 是通的」，代表 **VM 本身與服務都沒問題**，
> 問題一定在「主機到 VM」這一段或主機的對外。★★★★★ 由內而外查：
>
> **第 1 步 — 主機自己走轉發通不通？**
> ```bash
> curl -I http://127.0.0.1:8080
> ```
> 不通 → 轉發規則本身有問題（IP 打錯、忘記按 Apply、NAT 服務沒重啟）。
>
> **第 2 步 — VM 的 IP 是不是固定的？** ★★★★★
> 若是 DHCP，重開機後 IP 已經變了，規則指到空位址。
> 在 VM 內 `ip -brief addr show` 對照規則裡的 IP。
>
> **第 3 步 — 主機防火牆有沒有放行 8080？** ★★★★★
> Windows Defender 防火牆的輸入規則；★★★★ 並確認目前網路設定檔
> 是「私人」而不是「公用」—— 公用網路的規則嚴格得多。
>
> **第 4 步 — 同事真的連得到你的主機嗎？**
> ```bash
> # 在同事的電腦上
> ping <你的主機IP>
> ```
> 不通 → 是實體網路的問題（不同 VLAN、網路隔離政策），
> ★★★★ 與 Workstation 無關。
>
> **補充**：也要確認 VM 內的 `ufw` 有放行 80，
> 以及 Nginx 監聽 `0.0.0.0:80` 而非 `127.0.0.1:80`（`ss -tlnp`）。

> [!question]- 練習 4：設計一個三層隔離實驗環境 ★★★★
> 要模擬「網際網路 → DMZ（Web）→ 內網（DB）」三層架構，
> 其中 DB 那台**絕對不能**連到網際網路，也不能被主機直接碰到。
>
> 請規劃：需要幾個 VMnet？各是什麼設定？幾台 VM？各接哪裡？
>
> ★★★★ 參考答案：
> **需要兩個自訂網段 + NAT，共三台 VM。**
>
> | VMnet | 設定 | 代表 |
> | --- | --- | --- |
> | VMnet8（NAT） | 現成 | 「網際網路」側 |
> | VMnet2 | Host-only、**不接主機網卡**、**關 DHCP**、`10.10.30.0/24` | DMZ |
> | VMnet3 | Host-only、**不接主機網卡**、**關 DHCP**、`10.10.40.0/24` | 內網 |
>
> | VM | 網卡 | 說明 |
> | --- | --- | --- |
> | `lab-fw` | ens33=NAT、ens34=VMnet2、ens35=VMnet3 | ★★★★★ 三張卡的防火牆／路由器 |
> | `lab-web` | VMnet2，`10.10.30.11` | DMZ 的 Web 伺服器 |
> | `lab-db` | VMnet3，`10.10.40.11` | ★★★★★ 內網 DB |
>
> ★★★★★ **關鍵設定**：
> 1. `lab-db` 的 Netplan **不設 default route**，
>    或設成指向 `10.10.40.1`（防火牆）但由防火牆規則擋掉對外流量。
> 2. `lab-fw` 上用 nftables 只允許 `10.10.30.11 → 10.10.40.11:3306`，
>    ★★★★★ **拒絕 `10.10.40.0/24` 的所有對外 masquerade**。
> 3. VMnet3 **不接主機網卡** → 主機碰不到 DB。
>
> ★★★★ **驗證**：在 `lab-db` 上 `ping 1.1.1.1` 必須失敗，
> 在主機上 `ping 10.10.40.11` 也必須失敗；
> 但 `lab-web` 連 `10.10.40.11:3306` 要成功。
>
> ★★★★★ 若連「經由防火牆」都不允許，就改用 **LAN Segment** —— 更徹底。

---

## 小測驗

Q1.（選擇）VM 設定為 NAT 模式，網段為 `192.168.100.0/24`。
VM 的預設閘道應該設成哪一個？
(A) 192.168.100.1　(B) 192.168.100.2　(C) 192.168.100.254　(D) 主機的實體 IP

Q2.（是非）NAT 模式下，主機要連到 VM 裡的網站，必須先設埠轉發。

Q3. 公司無線網路上，VM 設成 Bridged 之後一直拿不到 IP。原因是什麼？該怎麼辦？

Q4. Host-only 與 LAN Segment 最關鍵的差別是什麼？做惡意程式分析時該選哪一個？

Q5. 這行指令的輸出如下，請說明這台 VM 是什麼模式，以及它能不能上網。

```bash
ip route
```

```text
192.168.181.0/24 dev ens33 proto kernel scope link src 192.168.181.130
```

Q6. 兩台從同一個範本複製出來的 VM，開機後搶到同一個 IP。原因與解法是什麼？

Q7.（選擇）你在自訂 VMnet2 上架了一台 DHCP 伺服器來練習，
但客戶端拿到的 IP 不是你發的。最可能的原因是？
(A) DHCP 設定檔語法錯誤　(B) VMware 的 DHCP 也在同一網段搶答
(C) VMnet2 沒有連到主機　(D) 客戶端網卡沒啟用

Q8. 為什麼在機關網路上做實驗時，本手冊強烈建議用 NAT 而不是 Bridged？請說出兩個理由。

Q9. `ping 1.1.1.1` 通，但 `apt update` 失敗。這代表問題出在哪一層？該查什麼？

Q10. 你為 VM 加了第二張網路卡，重開機後 SSH 連不上了。
最可能發生了什麼？要怎麼避免這個問題？

> [!question]- 測驗答案
> **Q1. (B) 192.168.100.2。**
> `.1` 是主機在 VMnet8 上的網卡，**它不會幫你轉送封包出去**；
> `.2` 才是虛擬 NAT 裝置（同時兼任 DNS 轉送）；`.254` 是 DHCP 伺服器。
> ★★★★★ 設成 `.1` 的症狀是「ping 得到主機，但上不了網」。
> 見「NAT 網段的三個固定角色」。
>
> **Q2. 否。** ★★★★★ **主機身上有一張 VMnet8 的網卡，與 VM 同網段，
> 可以直接連。** 埠轉發是給「主機以外的機器」用的。
> 這是可達性矩陣裡最容易搞混的一格。
>
> **Q3. 無線 AP（或 802.1X 認證、MAC 過濾）通常只允許一個 MAC 位址**，
> VM 的 MAC 送出去會被丟掉，所以 DHCP 要不到 IP。
> ★★★★★ **解法：改用 NAT 模式** —— NAT 模式下網路上只會看到主機一個 MAC。
> 見排錯表第 2 列。
>
> **Q4. 差別在「VM 與主機通不通」。**
> Host-only：VM 與主機**互通**；LAN Segment：★★★★★ **連主機都完全碰不到**，
> 而且沒有 DHCP，必須手動設固定 IP。
> ★★★★★ **惡意程式分析要用 LAN Segment**，因為 Host-only 下惡意程式
> 仍可嘗試攻擊主機。分析完務必還原快照。見「安全性注意事項」第四節。
>
> **Q5. 是 Host-only 模式（VMnet1），不能上網。**
> 判斷依據：★★★★★ **輸出裡完全沒有 `default via` 這一行**，
> 代表沒有預設路由，封包出不了本網段；
> 而 `192.168.181.0/24` 是 VMnet1 的典型網段。
> 見「Host-only」與「VM 內驗證四步」。
>
> **Q6. 複製時沒有重新產生 `/etc/machine-id`。**
> systemd-networkd 會用 machine-id 產生 DHCP 的識別碼，
> 兩台一樣就會拿到同一個位址。
> 解法：★★★★★ `sudo rm -f /etc/machine-id && sudo systemd-machine-id-setup`，
> 然後重開機。見「完整實戰範例」步驟 2 與排錯表。
>
> **Q7. (B) VMware 的 DHCP 也在同一網段搶答。**
> ★★★★★ 兩個 DHCP 在同一個廣播網域上，客戶端會採用**先回應的那一個**，
> 通常是反應更快的 VMware 內建 DHCP。
> 解法：虛擬網路編輯器 → 該 VMnet → 取消 **Use local DHCP service** 勾選。
> 見「本手冊各章實驗環境選哪一種」與排錯表。
>
> **Q8. 兩個理由（任舉其二）**：
> 1. ★★★★★ **資安暴露**：Bridged 會把沒更新、密碼弱的實驗機
>    直接放到機關網路上，任何人都掃得到。
> 2. ★★★★★ **會觸發交換器的埠安全**：多出來的 MAC 可能讓整個埠被
>    `err-disable`，連你自己的主機都斷網。
> 3. ★★★★ **NAT 的 IP 不隨環境改變**，筆電帶回家 VM 的 IP 不變，設定不用改。
> 見「安全性注意事項」第一節。
>
> **Q9. 問題在 DNS 這一層，不是網路連通性。**
> 能 ping 通 `1.1.1.1` 代表 IP 層與路由都正常。
> ★★★★ 該查：Netplan 的 `nameservers.addresses` 有沒有設；
> `resolvectl status` 看實際使用的 DNS；
> 用 `getent hosts tw.archive.ubuntu.com` 直接測解析。
> ★★★★ NAT 模式下把 DNS 指向 `192.168.x.2` 即可。見「VM 內驗證四步」。
>
> **Q10. 網路介面改名了。**
> 加了第二張卡之後，原本的 `ens33` 可能變成別的名稱，
> Netplan 裡寫死的介面名稱就對不上，VM 開機後沒有 IP，SSH 自然連不上。
> ★★★★★ **避免方法**：加網卡前先從 Workstation 主控台（不是 SSH）操作；
> 並改用 Netplan 的 `match: macaddress:` 搭配 `set-name:` 綁定介面，
> 這樣名稱就不會浮動。見「一台 VM 掛多張網路卡」。

---

## 延伸閱讀

### 同章

- [[050-01-02-00-idx-Workstation-VMware-Workstation]] — 本章索引
- [[050-01-02-01-svc-Workstation-安裝與授權]] — ★★★ VMnet1／VMnet8 就是安裝時建立的
- [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] — ★★★★★ 本篇的前置
- [[050-01-02-03-guide-Workstation-快照與複製]] — ★★★★ 複製 VM 後要重設 machine-id
- [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] — ★★★★ 隔離時要一併關掉
- [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] — ★★★ 網路以外的疑難排解

### 網路觀念

- [[010-02-08-guide-網概-NAT與私有位址]] — ★★★★★ NAT 到底在做什麼
- [[010-02-06-guide-網概-IP位址與子網路]] — ★★★★ 網段與遮罩
- [[010-02-05-guide-網概-MAC位址與交換器]] — ★★★★ 為什麼 Bridged 會多一個 MAC
- [[010-02-07-guide-網概-路由與封包旅程]] — ★★★★ 預設路由與轉送
- [[010-02-12-guide-網概-DHCP自動取得設定]] — ★★★★ 兩個 DHCP 為什麼會打架
- [[010-02-11-guide-網概-DNS網域名稱系統]] — ★★★ ping 得通但解不開名稱時
- [[010-02-17-guide-網概-網路排錯入門]] — ★★★★ 由內而外的排錯順序
- [[040-01-03-guide-網路設備-VLAN概念與規劃]] — ★★★ VMnet 與 VLAN 的類比

### Linux 端設定

- [[020-01-16-cmd-Linux-網路基礎指令]] — ★★★★★ `ip`、`ss`、`ping` 完整用法
- [[020-02-01-01-cmd-SSH-原理與第一次連線]] — ★★★★ 從主機 SSH 進 VM
- [[090-02-02-guide-防火牆-ufw基礎與實務]] — ★★★★ VM 內的防火牆
- [[090-02-03-guide-防火牆-nftables與iptables]] — ★★★★ 實戰範例用到的 nftables

### 其他平台的網路

- [[050-01-03-05-guide-PVE-網路設定]] — ★★★★ Proxmox VE 的 Linux bridge 與 VLAN
- [[050-02-01-05-guide-Docker-網路]] — ★★★ 容器的 bridge 網路，觀念高度相似
- [[130-01-01-guide-部署-部署共通觀念]] — ★★★ 實驗環境與正式環境的差異
