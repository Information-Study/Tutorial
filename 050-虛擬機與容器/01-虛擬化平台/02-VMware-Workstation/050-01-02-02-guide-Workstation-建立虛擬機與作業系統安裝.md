---
title: "建立虛擬機與作業系統安裝"
desc: "從新增虛擬機精靈到 Ubuntu Server 裝好上線的完整流程，含 CPU／記憶體／磁碟該給多少的判斷準則、磁碟類型與韌體選擇"
aliases: [新增虛擬機, New Virtual Machine, vmdk, 虛擬硬碟, Ubuntu Server 安裝]
tags: [群組/虛擬機與容器, 主題/虛擬化, 主題/VMware]
category: 虛擬機與容器
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-02-01-svc-Workstation-安裝與授權]]"]
updated: 2026-09-02
---

# 建立虛擬機與作業系統安裝

> [!warning] 未實機驗證
> 本篇的選單路徑與畫面文字**以 VMware Workstation 17 為例**，其他版本的選單位置、
> 按鈕文字與精靈頁數可能不同。Ubuntu Server 安裝程式（Subiquity）的畫面也會隨版本微調，
> 請以你手上 ISO 的實際畫面為準，**觀念與判斷準則不會變**。

> [!abstract] 這篇你會學到
> - 「新增虛擬機精靈」的兩種模式（典型／自訂），以及為什麼本手冊一律走**自訂** ★★★
> - ★★★★ CPU、記憶體、磁碟到底該給多少——**判斷準則與計算方式**，不是抄別人的數字
> - 虛擬磁碟的兩組選擇：**單一檔 vs 分割成多檔**、**預先配置 vs 動態成長**，各自的代價 ★★★★
> - ★★★★ UEFI 與 BIOS 韌體怎麼選，**裝完才發現選錯要重灌**
> - ISO 掛載、開機順序、進不了安裝程式時怎麼救 ★★★
> - **完整走一遍 Ubuntu Server 安裝**，從精靈第一頁到 SSH 連得進去 ★★★★★
> - 首次開機後的四件事：更新、SSH、靜態 IP、快照 ★★★★

## 前置知識

- [[050-01-02-01-svc-Workstation-安裝與授權]]
- [[050-01-01-01-guide-虛擬化-虛擬化概念與選型]]
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]]
- [[020-01-02-guide-Linux-實驗環境準備與初次登入]]

---

## 觀念說明

### ★★★★★ 這一台 VM 是後面十幾章的地基

先講清楚這篇的定位。本手冊從 020 群組的 Linux 基礎，一路到 060 群組的
Nginx／MySQL／PHP，再到 090 群組的憑證與 WAF，全部都需要**一台可以亂搞的 Ubuntu Server**。

這篇要建的就是那一台。它的名字在本手冊裡固定叫 **`lab-ubuntu-base`**，
角色是「乾淨的基礎範本」——裝好、更新完、SSH 開好、快照打好，
然後**不要再動它**。後面每一章要用機器時，都是從它**連結複製**出一台新的來用，
用完就丟。這個做法在 [[050-01-02-03-guide-Workstation-快照與複製]] 有完整說明。

| 這一台的定位 | 說明 |
| --- | --- |
| 名稱 ★★★ | `lab-ubuntu-base` |
| 作業系統 ★★★ | Ubuntu Server 24.04 LTS（本手冊 Linux 主線） |
| 用途 ★★★★ | **只當範本**，不裝任何服務、不改任何設定 |
| 快照 ★★★★ | 裝好後立刻打一個名為 `clean-base` 的快照 |
| 衍生方式 ★★★ | 連結複製（Linked Clone），一台約只多佔幾百 MB |

> [!danger] ★★★★★ 範本機不要拿來做實驗
> 一旦你在 `lab-ubuntu-base` 上裝了 Nginx、改了 `/etc/hosts`、加了測試使用者，
> 之後每一台從它複製出來的機器都會帶著這些垃圾。**範本髒了，等於全部重來**。
> 要做實驗就複製一台出去做。

### ★★★ 兩種建立方式：典型與自訂

Workstation 的新增虛擬機精靈（**File → New Virtual Machine**，或 `Ctrl+N`）
一開始會問你要「典型（Typical）」還是「自訂（Custom / Advanced）」。

| 模式 | 幫你決定什麼 | 適合誰 |
| --- | --- | --- |
| 典型（Typical）★ | 硬體版本、控制器型別、磁碟類型全部用預設 | 只想快速開一台玩玩 |
| 自訂（Custom）★★★★ | 每一項都問你，包含硬體相容性、韌體、控制器 | **本手冊一律用這個** |

**為什麼本手冊堅持用自訂**：典型模式會直接套用預設值，而預設值裡有兩項
（**韌體型別**與**磁碟分割方式**）事後改起來很麻煩，甚至要重灌。
花三十秒多點幾頁，比事後重來划算太多。★★★★

> [!warning] ★★★★ 不要用「Easy Install」（簡易安裝）
> 精靈裡如果你在「安裝來源」直接選了 ISO，Workstation 可能會偵測到作業系統類型，
> 跳出「Easy Install」讓你填帳號密碼，然後幫你**全自動裝完**。
>
> 看起來很方便，但本手冊**不建議**：
> - 它會用自己的一套分割與套件選擇，**你不知道它做了什麼** ★★★
> - 它會自動裝 open-vm-tools 或 VMware Tools，版本不一定是你要的 ★★
> - 你學不到安裝程式的實際畫面，之後裝實體機時會不知所措 ★★★★
>
> 正確做法：精靈裡選「**稍後安裝作業系統（I will install the operating system later）**」，
> 建好空機器之後再自己掛 ISO 開機。

### ★★★★ 硬體配置：該給多少，以及為什麼

這是新手最容易做錯的地方。常見兩種錯法：

1. **給太少** → VM 慢到不能用，或安裝程式直接失敗（記憶體不足）
2. **給太多** → 主機被吃光開始 swap，**主機和 VM 一起變慢**，比給太少還糟 ★★★★

#### CPU 核心數 ★★★★

Workstation 的 CPU 設定有兩欄：**處理器數量（Number of processors）**與
**每顆處理器的核心數（Number of cores per processor）**，相乘才是 VM 看到的
邏輯 CPU 數（vCPU）。

| 主機邏輯 CPU 數 | 單一 VM 建議 vCPU | 說明 |
| --- | --- | --- |
| 4 | 2 | 留一半給主機 ★★★ |
| 8 | 2～4 | 一般實驗 2 就夠 ★★★ |
| 12～16 | 4 | 要跑 PVE 巢狀虛擬化時給 4 ★★★ |
| 16 以上 | 4～8 | 超過 8 幾乎沒有意義 ★★ |

> [!note] ★★★★ 為什麼不是「越多越好」
> Hypervisor 排程一顆 4 vCPU 的 VM 時，傾向要**同時湊到 4 顆實體邏輯 CPU 有空**
> 才排得進去（稱為 co-scheduling 的概念）。vCPU 給越多，越難湊齊，
> **反而更常等待**。同時開三台 4 vCPU 的 VM 在一台 8 執行緒的筆電上，
> 三台都會卡。
>
> 實務準則：**所有同時開機的 VM 的 vCPU 總和，不要超過主機邏輯 CPU 數的 1.5 倍**。★★★★

設定方式（自訂精靈的「處理器設定」頁，或事後 **VM → Settings → Processors**）：

```text
Number of processors:         1
Number of cores per processor: 2
Total processor cores:         2      ← 這是 VM 看到的 vCPU 數
```

> [!tip] ★★★ 用 1 顆處理器 × N 核心，不要用 N 顆處理器 × 1 核心
> 客體作業系統看到「多顆實體 CPU」時可能會啟用 NUMA 相關行為，在單一實體主機上
> 只是增加複雜度沒有好處。另外有些商業軟體是**按實體 CPU 顆數**授權的，
> 給多顆會踩到授權問題。

#### 記憶體 ★★★★

| 用途 | 建議記憶體 | 說明 |
| --- | --- | --- |
| Ubuntu Server 純文字，練指令 ★★★ | 2048 MB | 4096 更舒服 |
| Ubuntu Server + Nginx + PHP-FPM ★★★ | 4096 MB | 060 群組各章 |
| Ubuntu Server + MySQL + Laravel ★★★ | 4096～8192 MB | MySQL 預設就吃不少 |
| Ubuntu Desktop（有桌面）★★★ | 4096 MB 起 | 低於 4 GB 桌面會很卡 |
| 巢狀跑 Proxmox VE ★★★★ | 8192 MB 起 | PVE 本身就要 2 GB |
| Windows Server ★★★ | 4096 MB 起 | 低於 4 GB 幾乎不能用 |

> [!danger] ★★★★★ 記憶體超賣（overcommit）會拖垮主機
> Workstation **允許**你把所有 VM 的記憶體加起來超過主機實體記憶體。
> 超過的部分會被寫進主機的分頁檔或 `.vmem` 交換檔——那是**磁碟**。
>
> 一台 16 GB 的筆電開三台各給 8 GB 的 VM，三台都開機時，
> 主機會開始瘋狂寫磁碟，整台機器（含你的瀏覽器、編輯器）都會停頓數秒到數十秒。
>
> **鐵律：所有同時開機的 VM 記憶體總和 ≤ 主機實體記憶體 − 4 GB**（留給主機作業系統）。
> 16 GB 的機器，同時最多開 12 GB 的 VM。

計算範例（主機 16 GB）：

```text
主機作業系統與桌面環境保留    4 GB
--------------------------------
可分配給 VM                  12 GB

情境 A：一台 Web + 一台 DB
  lab-web    4 GB
  lab-db     4 GB
  合計       8 GB   ← 安全，還有餘裕開第三台

情境 B：一台 PVE 巢狀 + 一台客戶端
  lab-pve    8 GB
  lab-client 2 GB
  合計      10 GB   ← 可以，但別再開第三台
```

#### 磁碟大小 ★★★

| 用途 | 建議大小 | 說明 |
| --- | --- | --- |
| Ubuntu Server 基礎範本 ★★★ | 40 GB | 本手冊標準值 |
| 加上 Docker 映像 ★★★ | 60～80 GB | 映像很吃空間 |
| 資料庫實驗 ★★★ | 60 GB | 含備份檔測試 |
| Ubuntu Desktop ★★ | 60 GB | 桌面套件多 |
| Proxmox VE 巢狀 ★★★ | 80 GB 起 | 裡面還要放 VM |

> [!tip] ★★★★ 磁碟寧可開大，因為預設是「動態成長」
> 選了動態成長（不預先配置）時，**宣告 60 GB 但實際只用 8 GB，磁碟檔就只有約 8 GB**。
> 宣告大一點幾乎沒有成本，但事後要擴充卻很麻煩（要在客體裡動 partition 和 LVM）。
>
> 反過來說，**如果你選了「預先配置」，那宣告多少就立刻佔多少**，那就要精算。

### ★★★★ 虛擬磁碟：兩組互相獨立的選擇

自訂精靈在「指定磁碟容量」那一頁會同時問你兩件事，很多人搞混。
它們是**互相獨立**的兩個選項。

#### 選擇一：預先配置 vs 動態成長

對應精靈上的核取方塊：**Allocate all disk space now（立即配置所有磁碟空間）**。

| | 動態成長（不勾，預設）★★★ | 預先配置（勾選）★★★ |
| --- | --- | --- |
| 建立時耗時 | 幾秒 | 40 GB 可能要數分鐘到數十分鐘 |
| 立即佔用主機空間 | 幾 MB | 宣告多少佔多少 |
| 寫入效能 | 首次寫某區塊時要先擴檔，**略慢** | 一開始就配好，**穩定較快** |
| 磁碟碎片 | 檔案隨用隨長，容易碎 | 一次配置，連續性好 |
| 空間可預期性 ★★★★ | **差**：VM 可能悄悄長到塞爆主機 | 好：一開始就知道要多少 |
| 本手冊建議 | **實驗環境用這個** ★★★★ | 正式環境或效能測試用 |

> [!warning] ★★★★ 動態成長的磁碟「只會長大，不會自動縮小」
> 你在 VM 裡刪掉 10 GB 的檔案，主機上的 `.vmdk` **不會跟著變小**。
> 客體檔案系統只是把區塊標記為可用，Workstation 不知道。
>
> 要真的縮回去必須手動壓實（compact），做法在
> [[050-01-02-06-guide-Workstation-效能調校與疑難排解]]。
> 這是「主機磁碟莫名其妙被吃光」最常見的原因之一。

#### 選擇二：單一檔案 vs 分割成多個檔案

對應精靈上的兩個選項：
**Store virtual disk as a single file** / **Split virtual disk into multiple files**。

| | 單一檔案（single）★★★ | 分割多檔（split，預設）★★★ |
| --- | --- | --- |
| 檔案樣貌 | `lab-ubuntu-base.vmdk` 一個大檔 | `...-s001.vmdk`、`-s002.vmdk`…每個約 2 GB |
| 效能 | 略好（少一層對應）★★ | 略差，但差異通常感覺不出來 |
| 搬到 FAT32／exFAT 隨身碟 ★★★★ | **不行**，FAT32 單檔上限 4 GB | 可以，每片都小於上限 |
| 複製、備份 | 一個大檔搬起來慢但單純 | 多個小檔，可以增量同步 |
| 檔案損毀影響 | 整顆磁碟一起完蛋 | 也是整顆完蛋（不要以為分割就有容錯）★★★ |
| 本手冊建議 | 主機是 NTFS／ext4／APFS 且不搬機 → 單一檔 | **要搬到別台或放隨身碟 → 分割** |

> [!note] ★★★ 分割不等於容錯
> 分割成 20 片，其中一片壞掉，整顆虛擬磁碟一樣讀不回來。
> 分割唯一的意義是**繞過檔案系統的單檔大小限制**，以及讓備份工具比較好處理。

四種組合的實際效果：

```text
動態成長 + 分割（Workstation 預設）
  → 建立快、佔用小、可搬到 exFAT。本手冊實驗環境建議 ★★★★

動態成長 + 單一檔
  → 建立快、佔用小、效能略好。主機是 NTFS/ext4 且不搬機時用 ★★★

預先配置 + 單一檔
  → 建立慢、立刻佔滿、效能最穩。做效能測試或正式用途 ★★★

預先配置 + 分割
  → 建立慢、立刻佔滿、可搬到 exFAT。少見但合法 ★
```

### ★★★★ UEFI 還是 BIOS：裝完才發現選錯要重灌

自訂精靈的「韌體型別（Firmware type）」那一頁會問你要 **BIOS** 還是 **UEFI**，
UEFI 下面還有一個 **Secure Boot** 核取方塊。

| 韌體 | 適用 | 注意 |
| --- | --- | --- |
| BIOS（Legacy）★★ | 舊系統、要模擬老舊環境 | 磁碟用 MBR，**單一分割上限 2 TB** |
| UEFI ★★★★ | **本手冊主線**，現代 Linux／Windows 都支援 | 磁碟用 GPT，需要 ESP 分割區 |
| UEFI + Secure Boot ★★★ | 要驗證簽章載入流程時 | 自編譯核心模組會被擋，實驗時通常關掉 |

> [!danger] ★★★★★ 韌體型別在裝完作業系統之後不能隨便改
> 作業系統的開機載入器（GRUB／Windows Boot Manager）是**按照韌體型別安裝**的。
> 你用 BIOS 裝好 Ubuntu，之後把設定改成 UEFI，開機會直接停在
> `Operating System not found` 或掉進 UEFI Shell。
>
> 反過來也一樣。**改回去就好**——但如果你已經在裡面裝了一堆東西又忘記原本是哪個，
> 就得一個一個試。**建好時就記在 VM 的 Notes 欄位裡**。★★★★

本手冊的選擇：**UEFI，不開 Secure Boot**。理由：

1. 對齊現代實體伺服器的實際狀況，學到的分割觀念可以直接搬過去 ★★★
2. GPT 分割表沒有 2 TB 限制、沒有主分割區只能四個的限制 ★★★
3. 不開 Secure Boot 是因為實驗常需要載入未簽章的核心模組
   （例如 VMware Tools 的舊版模組、自行編譯的驅動）★★★★

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> RHEL 系的安裝程式是 **Anaconda**，不是 Ubuntu 的 Subiquity，畫面完全不同，
> 但虛擬機這一層的設定**完全一樣**：一樣選 UEFI、一樣給 2 vCPU / 4 GB / 40 GB。
>
> 幾個差異：
> - 精靈的「客體作業系統」要選 **Linux → Red Hat Enterprise Linux 9 64-bit**，
>   選錯只影響 Workstation 推薦的預設值與 VMware Tools 版本，不影響能不能裝 ★★
> - Anaconda 的預設分割是 `/boot`、`/`（在 LVM 上）、`swap`，
>   而且**預設會給 `/home` 一個獨立 LV**，根分割區會比 Ubuntu 小很多 ★★★
>   → 實驗機建議手動改成「全部給 `/`」，不然裝套件很快就滿
> - RHEL 9 的最小安裝**預設不裝 `openssh-server` 以外的東西**，
>   安裝時記得在「軟體選擇」勾 **Server**（不要選 Server with GUI）★★★
> - 開機後更新指令是 `sudo dnf upgrade -y`，不是 `apt`

### ★★★ 網路模式：這篇先用 NAT

精靈的「網路類型」頁有四個選項。這一篇**一律先選 NAT**，理由是它最不會出問題：
VM 可以連外網下載套件，主機也連得到 VM。

完整的四種模式比較、可達性矩陣、以及各章實驗環境該選哪一種，
在 [[050-01-02-04-guide-Workstation-網路模式]] 有專篇處理。這裡先照做就好。

### ★★ 控制器與虛擬裝置型別

自訂精靈還會問 I/O 控制器與虛擬磁碟類型。**維持預設即可**，但知道差別有好處：

| 項目 | 預設值（Linux 客體） | 說明 |
| --- | --- | --- |
| I/O 控制器 ★★ | LSI Logic | 相容性最好 |
| 虛擬磁碟類型 ★★★ | NVMe 或 SCSI（依客體而定） | NVMe 效能好但舊系統不認得 |
| 網路卡 ★★ | e1000e 或 VMXNET3 | VMXNET3 是半虛擬化，效能較好但需要 Tools |
| USB 控制器 ★ | USB 3.1 | 要接舊 USB 裝置時降成 2.0 |

> [!tip] ★★★ 磁碟類型選 SCSI 最保險
> NVMe 效能較好，但**部分較舊的 Linux 發行版與 Windows 安裝程式認不到 NVMe**，
> 會卡在「找不到磁碟」。Ubuntu 24.04 兩者都沒問題；
> 如果你要裝的是舊系統，選 **SCSI** 最不會出事。

---

## 安裝或基礎操作

### ★★★ 步驟 0：準備 ISO

從官方來源下載 Ubuntu Server LTS 的 ISO，放在一個固定位置（例如 `D:\ISO\`
或 `~/ISO/`），**不要放在虛擬機資料夾裡面**——不然複製 VM 時會連 ISO 一起複製。

下載後**一定要驗證雜湊**：

```bash
# Linux 主機
sha256sum ubuntu-24.04.3-live-server-amd64.iso
```

預期輸出（範例格式，實際值以官方 `SHA256SUMS` 檔為準）：

```text
c2f4...省略...9a1b  ubuntu-24.04.3-live-server-amd64.iso
```

```powershell
# Windows 主機（PowerShell）
Get-FileHash -Algorithm SHA256 D:\ISO\ubuntu-24.04.3-live-server-amd64.iso
```

預期輸出：

```text
Algorithm       Hash                                                              Path
---------       ----                                                              ----
SHA256          C2F4...省略...9A1B                                                D:\ISO\ubuntu-...iso
```

把這個值和官方 `SHA256SUMS` 檔裡的值比對，**一個字元都不能差**。★★★★

> [!warning] ★★★★ 不驗證雜湊的後果
> ISO 下載到一半斷線、或從來路不明的鏡像站抓到被動過手腳的映像，
> 安裝過程可能中途噴 `Failed to load ldlinux.c32`、或裝完系統莫名其妙壞掉。
> 更嚴重的情況是拿到植入後門的映像——**機關環境絕對不能省這一步**。

### ★★★★ 步驟 1：跑新增虛擬機精靈

**File → New Virtual Machine**（`Ctrl+N`），選 **Custom (advanced)**，然後逐頁：

#### 頁 1：硬體相容性（Hardware compatibility）★★★

```text
Hardware compatibility: Workstation 17.x
```

**保持最新即可**。這個值決定虛擬硬體版本（vHW），影響能用哪些功能
（最大記憶體、最大 vCPU、是否支援某些裝置）。

> [!note] ★★★ 什麼時候要降版
> 如果這台 VM 之後要匯出給用舊版 Workstation 或舊版 ESXi 的同事，
> 就要在這裡選較低的相容性，不然對方**開不起來**。
> 純自用不用管，選最新的。

#### 頁 2：安裝來源 ★★★★

```text
( ) Installer disc
( ) Installer disc image file (iso)
(•) I will install the operating system later.     ← 選這個
```

**一定選第三個**。選前兩個會觸發 Easy Install，理由前面說過了。

#### 頁 3：客體作業系統 ★★★

```text
Guest operating system:  ( ) Microsoft Windows
                         (•) Linux
                         ( ) VMware ESX
                         ( ) Other

Version:                 Ubuntu 64-bit
```

這個選項影響 Workstation 推薦的預設硬體、要裝哪個版本的 VMware Tools、
以及某些最佳化參數。選錯不會不能裝，但會拿到不合適的預設值。

#### 頁 4：名稱與位置 ★★★★

```text
Virtual machine name:  lab-ubuntu-base
Location:              D:\VMs\lab-ubuntu-base
```

> [!danger] ★★★★ 存放位置不要選在 OneDrive／Google Drive／Dropbox 同步資料夾
> 雲端同步軟體會嘗試即時上傳正在被寫入的 `.vmdk`，結果是：
> - 主機 CPU 與網路被吃光 ★★★★
> - 檔案在寫入中被鎖住，**VM 直接當掉或磁碟損毀** ★★★★★
>
> 存放位置也**不要放在網路磁碟機**，除非是 10 GbE 以上的專用儲存。
> 最佳選擇是**主機本機的 SSD**。

命名建議（本手冊慣例）：

| 用途 | 命名 |
| --- | --- |
| 範本 ★★★ | `lab-ubuntu-base`、`lab-rocky-base` |
| Web 實驗 ★★ | `lab-web-nginx`、`lab-web-apache` |
| 資料庫 ★★ | `lab-db-mysql` |
| 網路實驗 ★★ | `lab-net-client01`、`lab-net-router` |

#### 頁 5：韌體型別 ★★★★

```text
Firmware type:  ( ) BIOS
                (•) UEFI
                    [ ] Secure Boot        ← 不勾
```

前面說過的原因：UEFI 對齊現代環境，不勾 Secure Boot 以免載入模組被擋。

#### 頁 6：處理器設定 ★★★★

```text
Number of processors:            1
Number of cores per processor:   2
```

#### 頁 7：記憶體 ★★★★

```text
Memory for this virtual machine:  4096 MB
```

畫面右邊會有三個提示標記：**最小建議**、**建議**、**主機記憶體上限**。
你的值**絕對不要碰到最右邊那條線**。

#### 頁 8：網路類型 ★★★

```text
(•) Use network address translation (NAT)
```

#### 頁 9：I/O 控制器 ★★

```text
(•) LSI Logic  (Recommended)
```

#### 頁 10：磁碟類型 ★★★

```text
( ) IDE
(•) SCSI  (Recommended)
( ) SATA
( ) NVMe
```

#### 頁 11：選擇磁碟 ★★

```text
(•) Create a new virtual disk
( ) Use an existing virtual disk
( ) Use a physical disk (for advanced users)
```

> [!danger] ★★★★★ 絕對不要在實驗環境選「Use a physical disk」
> 這個選項會讓 VM **直接寫入主機的實體磁碟**。選錯目標磁碟，
> 客體作業系統的安裝程式會把你主機的硬碟分割表整個蓋掉。
> 這是不可逆的資料全滅。

#### 頁 12：磁碟容量 ★★★★

```text
Maximum disk size (GB):  40.0

[ ] Allocate all disk space now.        ← 不勾（動態成長）

( ) Store virtual disk as a single file
(•) Split virtual disk into multiple files    ← 預設，本手冊採用
```

#### 頁 13：磁碟檔名 ★

```text
lab-ubuntu-base.vmdk
```

用預設即可。

#### 頁 14：完成前的自訂硬體 ★★★

最後一頁會列出所有設定摘要，有一顆 **Customize Hardware…** 按鈕。
按進去做兩件事：

1. **移除用不到的裝置**：`Printer`、`Sound Card`、`USB Controller`（如果不接 USB）
   —— 少一個虛擬裝置就少一份中斷處理與記憶體開銷 ★★★
2. **確認 CD/DVD 裝置存在**，等一下要掛 ISO ★★★

也把 **Power on this virtual machine after creation** 的勾取消掉——
現在還沒掛 ISO，開了也只會停在 UEFI Shell。

按 **Finish**。

### ★★★★ 步驟 2：掛載 ISO 並確認開機順序

在左邊清單選 `lab-ubuntu-base`，按 **Edit virtual machine settings**
（或 **VM → Settings**，`Ctrl+D`）。

#### 掛 ISO

**Hardware 分頁 → CD/DVD (SATA)**：

```text
Device status:  [v] Connected
                [v] Connect at power on          ← 一定要勾 ★★★★

Connection:     ( ) Use physical drive
                (•) Use ISO image file:
                    D:\ISO\ubuntu-24.04.3-live-server-amd64.iso
```

> [!warning] ★★★★ 忘了勾「Connect at power on」是最常見的失敗
> 沒勾的話，開機時光碟機是斷開狀態，VM 會找不到開機媒體，
> 停在 UEFI 畫面顯示 `>>Start PXE over IPv4` 之類的網路開機嘗試，
> 最後掉進 `UEFI Interactive Shell`。

#### UEFI 的開機順序

BIOS 模式可以在開機瞬間按 `F2` 進 BIOS 設定調開機順序；
**UEFI 模式下 Workstation 沒有傳統 BIOS 畫面**，它會自動嘗試可開機的裝置。

如果需要強制進韌體設定畫面，兩個做法：

```text
方法一：VM → Power → Power On to Firmware
        （最可靠，直接進 UEFI 設定）★★★★

方法二：開機瞬間狂按 Esc
        （視窗要先取得焦點，時間窗只有一兩秒，不好抓）★★
```

> [!tip] ★★★ 抓不到按鍵時間窗，就加開機延遲
> 關掉 VM，在 VM 的 `.vmx` 檔（位於虛擬機資料夾內）最後加一行：
>
> ```ini
> bios.bootDelay = "5000"
> ```
>
> 單位是毫秒，這行讓開機自檢畫面停留 5 秒，你就有充裕時間按鍵。
> **改 `.vmx` 之前 VM 必須是關機狀態**，不然存檔會被覆蓋回去。★★★

### ★★★★★ 步驟 3：完整走一遍 Ubuntu Server 安裝

按 **Power on this virtual machine**（綠色播放鍵）。

> [!tip] ★★★ 滑鼠被 VM 吃掉時按 `Ctrl + Alt`
> 點進 VM 視窗後鍵盤滑鼠會被 VM 抓住，按 `Ctrl + Alt` 放開回主機。
> 裝完 VMware Tools 之後就可以自由進出，見
> [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]]。

#### 3-1 GRUB 開機選單

```text
 *Try or Install Ubuntu Server
  Ubuntu Server with the HWE kernel
  Test memory
```

按 Enter 選第一項。接著會跑一段核心訊息，然後進入安裝程式。

#### 3-2 語言

```text
Use UP, DOWN and ENTER keys to select your language.

  [ English                    ]
  [ 中文（简体）               ]
```

> [!warning] ★★★ 伺服器一律選 English
> 選中文的話，**錯誤訊息會被翻成中文**，你上網 Google 找不到答案；
> 而且某些終端機字型顯示不出中文會變成一堆方塊。
> 機關伺服器的維運慣例就是介面用英文。

#### 3-3 鍵盤配置

```text
Layout:    [ English (US)  v ]
Variant:   [ English (US)  v ]
```

台灣用的鍵盤就是 US 配置，直接 Done。

#### 3-4 安裝類型

```text
(X) Ubuntu Server
( ) Ubuntu Server (minimized)
```

選 **Ubuntu Server**（不要 minimized）。minimized 版本連 `man`、`vim`、
`less` 這些都拔掉了，練習時很痛苦。★★★

#### 3-5 網路設定

```text
NETWORK CONNECTIONS

 ens33  eth  -                                     >
        DHCPv4  192.168.1xx.128/24
        00:0c:29:xx:xx:xx  /  Intel Corporation ...
```

因為前面選了 NAT，這裡應該會**自動拿到 IP**。看到 `192.168.x.128/24` 這類位址就對了。

> [!warning] ★★★★ 這裡沒拿到 IP 就先停下來
> 如果顯示的是空白或 `link down`，代表虛擬網路有問題，繼續裝下去只會在
> 下載套件那一步卡住。先回頭檢查：
> - VM Settings → Network Adapter 的 **Connected** 有沒有勾 ★★★★
> - 主機上的 `VMware NAT Service` 與 `VMware DHCP Service` 有沒有在跑 ★★★★
> - 主機防火牆有沒有擋掉 ★★
>
> 排查方式見 [[050-01-02-04-guide-Workstation-網路模式]]。

**這一步先不要設靜態 IP**——安裝程式設的靜態 IP 有時會和後面 cloud-init
產生的設定打架，等裝完開機後再設，比較乾淨。★★★

#### 3-6 Proxy

```text
Proxy address:  [                                    ]
```

機關內部有 Proxy 才填，格式 `http://proxy.example.gov.tw:3128`。沒有就留空 Done。

#### 3-7 套件庫鏡像

```text
Mirror address:  [ http://tw.archive.ubuntu.com/ubuntu   ]

This mirror location passed tests.
```

看到 `passed tests` 就 Done。如果顯示 `failed`，改成
`http://archive.ubuntu.com/ubuntu` 再試。

#### 3-8 磁碟分割 ★★★★

這是整個安裝過程最需要動腦的一頁。

```text
GUIDED STORAGE CONFIGURATION

(X) Use an entire disk
    [ VMware Virtual disk_...  local disk  40.000G  v ]

    [ ] Set up this disk as an LVM group
        [ ] Encrypt the LVM group with LUKS

( ) Custom storage layout
```

本手冊的選擇：**Use an entire disk，取消勾選 LVM**。

| 選項 | 建議 | 理由 |
| --- | --- | --- |
| Use an entire disk ★★★ | 勾 | 實驗機不需要複雜分割 |
| Set up this disk as an LVM group ★★★ | **取消勾選** | 見下方說明 |
| Encrypt with LUKS ★★★★ | 不勾 | 每次開機要打密碼，實驗機很煩 |

> [!note] ★★★★ 為什麼實驗範本不用 LVM
> LVM 本身很好用（可以線上擴充、做快照），但在這台**範本機**上有兩個問題：
>
> 1. Ubuntu 的 guided LVM 預設**只把約一半的空間配給根 LV**，
>    剩下的留在 VG 裡不動。你以為給了 40 GB，實際 `/` 只有約 20 GB，
>    裝幾個 Docker 映像就滿了，然後你會很困惑 ★★★★
> 2. 之後在 Workstation 這一層擴充虛擬磁碟後，客體裡要做
>    `growpart` → `pvresize` → `lvextend` → `resize2fs` 四步，
>    不用 LVM 只要 `growpart` → `resize2fs` 兩步 ★★★
>
> **練 LVM 是另一回事**，那應該在 [[020-01-15-cmd-Linux-磁碟分割與掛載]]
> 用一顆額外掛上去的虛擬磁碟練，不要動系統碟。

按 Done 之後會看到分割摘要，UEFI 模式下應該長這樣：

```text
FILE SYSTEM SUMMARY

 MOUNT POINT   SIZE  TYPE       DEVICE TYPE
 /             38.7G new ext4   new partition of local disk
 /boot/efi     1.0G  new fat32  new partition of local disk

USED DEVICES
 ...
```

看到 `/boot/efi` 是 `fat32` 就代表 UEFI 韌體設定生效了。★★★
如果沒有這個分割區，代表你剛才韌體選成 BIOS 了。

再按一次 Done，會跳出確認：

```text
Confirm destructive action

Selecting Continue below will begin the installation process and
result in the loss of data on the disks selected to be formatted.

You will not be able to return to this or a previous screen once
the installation has started.

[ No       ]
[ Continue ]
```

選 **Continue**。

> [!danger] ★★★★★ 這個確認畫面在實體機上是真的會毀資料
> 現在你在 VM 裡按下去只會格式化虛擬磁碟，沒關係。
> 但**同一個畫面在實體伺服器上按下去，那顆磁碟的資料就沒了**。
> 養成習慣：在實體機上做到這一步，一定要停下來把裝置名稱與容量念一遍再按。

#### 3-9 使用者設定 ★★★★

```text
Your name:          Lab Admin
Your servers name:  lab-ubuntu-base
Pick a username:    labadmin
Choose a password:  ********
Confirm password:   ********
```

| 欄位 | 建議 | 說明 |
| --- | --- | --- |
| Your name ★ | 隨意 | 只是 GECOS 欄位 |
| Your server's name ★★★ | `lab-ubuntu-base` | 這會變成 hostname，之後複製時要記得改 |
| Pick a username ★★★ | `labadmin` | **不要用 `admin`**，某些套件會佔用這個名字 |
| Password ★★★★ | 實驗機可以簡單，**但不要跟正式環境密碼相同** | 見安全性注意事項 |

#### 3-10 Ubuntu Pro

```text
(X) Skip for now
( ) Enable Ubuntu Pro
```

實驗機選 **Skip for now**。

#### 3-11 SSH 設定 ★★★★

```text
[X] Install OpenSSH server

Import SSH identity:  [ No  v ]
```

**一定要勾 Install OpenSSH server**。沒勾的話裝完只能在 Workstation 的
主控台視窗裡打字，不能複製貼上、不能捲動歷史，非常難用。★★★★

`Import SSH identity` 可以直接從 GitHub 或 Launchpad 拉你的公鑰下來，
機關環境通常連不出去，選 No，之後手動放。

#### 3-12 精選套件（Featured Server Snaps）

```text
[ ] microk8s
[ ] nextcloud
[ ] wekan
[ ] powershell
...
```

**全部不要勾**。這些是 snap 套件，會讓範本變胖而且不一定是你要的版本。★★★

#### 3-13 安裝進行中

畫面會跑安裝日誌，最下方有進度。安裝完會變成：

```text
Install complete!

  [ View full log        ]
  [ Reboot Now           ]
```

**先不要按 Reboot Now**。

#### 3-14 ★★★★ 重開機前先退出 ISO

如果不退出 ISO 就重開，UEFI 可能又從光碟開機，你會再次看到安裝程式，
還以為裝失敗了。

做法：**VM → Removable Devices → CD/DVD (SATA) → Disconnect**，
或直接 `Ctrl+D` 進 Settings 把 `Connect at power on` 取消勾選。

> [!tip] ★★ Ubuntu 的 Subiquity 通常會自己處理
> 新版 Subiquity 在重開機時會提示 `Please remove the installation medium,
> then press ENTER`，並嘗試自動退出虛擬光碟。
> 但**不要依賴它**，自己動手退比較保險。

退完 ISO，按 **Reboot Now**。

---

## 進階應用

### ★★★★ 首次開機後的四件事

開機後看到登入提示：

```text
Ubuntu 24.04.3 LTS lab-ubuntu-base tty1

lab-ubuntu-base login:
```

用剛才設的 `labadmin` 登入。接下來做四件事，做完這台範本就完成了。

#### 事一：確認基本狀態 ★★★

```bash
# 確認 UEFI 開機（有這個目錄且有內容就是 UEFI）
ls /sys/firmware/efi
```

預期輸出：

```text
config_table  efivars  fw_platform_size  fw_vendor  runtime  runtime-map  systab
```

如果顯示 `ls: cannot access '/sys/firmware/efi': No such file or directory`，
代表這台是 BIOS 開機，不是 UEFI。★★★

```bash
# 確認 CPU 與記憶體拿到的量
nproc
free -h
```

預期輸出：

```text
2
               total        used        free      shared  buff/cache   available
Mem:           3.8Gi       324Mi       3.1Gi       1.0Mi       528Mi       3.3Gi
Swap:          3.8Gi          0B       3.8Gi
```

`3.8Gi` 就是你給的 4096 MB（扣掉核心與韌體保留）。

```bash
# 確認磁碟
lsblk
df -h /
```

預期輸出：

```text
NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINTS
sda      8:0    0   40G  0 disk
├─sda1   8:1    0    1G  0 part /boot/efi
└─sda2   8:2    0 38.7G  0 part /

Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2        38G  2.5G   34G   7% /
```

看到 `38G` 而不是 `19G`，代表沒踩到 LVM 只配一半的坑。★★★★

#### 事二：更新系統 ★★★★

```bash
sudo apt update
```

預期輸出（節錄）：

```text
Hit:1 http://tw.archive.ubuntu.com/ubuntu noble InRelease
Get:2 http://tw.archive.ubuntu.com/ubuntu noble-updates InRelease [126 kB]
Get:3 http://security.ubuntu.com/ubuntu noble-security InRelease [126 kB]
...
Fetched 5,842 kB in 4s (1,461 kB/s)
Reading package lists... Done
Building dependency tree... Done
42 packages can be upgraded. Run 'apt list --upgradable' to see them.
```

```bash
sudo apt upgrade -y
```

這一步會跑一陣子。跑完檢查是否需要重開：

```bash
ls /var/run/reboot-required 2>/dev/null && cat /var/run/reboot-required
```

如果輸出：

```text
/var/run/reboot-required
*** System restart required ***
```

就重開機：

```bash
sudo reboot
```

接著裝幾個範本一定要有的工具：

```bash
sudo apt install -y \
  open-vm-tools \
  vim curl wget git \
  net-tools iproute2 dnsutils \
  htop tree unzip
```

| 套件 | 為什麼要 |
| --- | --- |
| `open-vm-tools` ★★★★ | VMware Tools 的開源版，**沒有它時間會飄、關機指令不會生效** |
| `vim` ★★★ | 預設的 `vi` 難用 |
| `curl` / `wget` ★★★ | 後面每一章都在用 |
| `git` ★★★ | 部署實戰章節必需 |
| `net-tools` ★★ | 提供 `netstat`、`ifconfig`（雖然舊，但很多文件還在用） |
| `dnsutils` ★★★ | 提供 `dig`、`nslookup` |
| `htop` ★★ | 看資源使用 |

> [!warning] ★★★★ `open-vm-tools` 不要跳過
> 沒裝的話會遇到：
> - VM 的時間和主機不同步，過幾天差好幾分鐘，**憑證驗證會失敗** ★★★★
> - Workstation 選單的 **Shut Down Guest** 沒反應（只能硬斷電）★★★★
> - 主機看不到 VM 的 IP，`vmrun getGuestIPAddress` 拿不到值 ★★★
> - 沒有共享資料夾、沒有剪貼簿共用 ★★
>
> 詳見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]]。

確認 tools 有在跑：

```bash
systemctl status open-vm-tools --no-pager
```

預期輸出（節錄）：

```text
● open-vm-tools.service - Service for virtual machines hosted on VMware
     Loaded: loaded (/usr/lib/systemd/system/open-vm-tools.service; enabled; ...)
     Active: active (running) since Tue 2026-09-02 10:12:33 CST; 3min ago
```

#### 事三：確認 SSH 並從主機連進來 ★★★★

在 VM 裡查 IP：

```bash
ip -4 addr show ens33
```

預期輸出：

```text
2: ens33: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    inet 192.168.152.128/24 metric 100 brd 192.168.152.255 scope global dynamic ens33
       valid_lft 1503sec preferred_lft 1503sec
```

確認 sshd 在聽：

```bash
sudo ss -tlnp | grep :22
```

預期輸出：

```text
LISTEN 0  4096  0.0.0.0:22  0.0.0.0:*  users:(("sshd",pid=812,fd=3))
LISTEN 0  4096     [::]:22     [::]:*  users:(("sshd",pid=812,fd=4))
```

回到**主機**，用終端機（Windows 用 PowerShell 或 Windows Terminal）連進去：

```bash
ssh labadmin@192.168.152.128
```

第一次連線會問：

```text
The authenticity of host '192.168.152.128 (192.168.152.128)' can't be established.
ED25519 key fingerprint is SHA256:aB3d...省略...
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

輸入 `yes`，再輸入密碼，看到 shell 提示字元就成功了：

```text
labadmin@lab-ubuntu-base:~$
```

從這一刻起，**你可以完全不用 Workstation 的主控台視窗**，
所有操作都在主機的終端機裡做，可以複製貼上、可以開多個分頁。★★★★

> [!tip] ★★★ 順手設定金鑰登入，之後不用一直打密碼
> 在**主機**上：
>
> ```bash
> ssh-keygen -t ed25519 -C "lab"      # 已經有金鑰就跳過
> ssh-copy-id labadmin@192.168.152.128
> ```
>
> 完整的金鑰認證說明在 [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]]。

#### 事四：設定靜態 IP ★★★★

DHCP 給的位址會變。範本機本身雖然平常不開機，但後面複製出去的機器
如果都要固定位址，最乾淨的做法是**在範本階段就寫好靜態設定的骨架**。

Ubuntu Server 用 **Netplan**。先看現有設定：

```bash
ls /etc/netplan/
```

預期輸出：

```text
50-cloud-init.yaml
```

> [!warning] ★★★★ 不要直接改 `50-cloud-init.yaml`
> 這個檔是 cloud-init 產生的，重開機或 cloud-init 重跑時**會被覆蓋回去**，
> 你的修改就消失了。檔案開頭那段註解也是這樣寫的。
>
> 正確做法有兩步：先叫 cloud-init 不要再管網路，再自己建一個新的 netplan 檔。

**第一步：關掉 cloud-init 的網路設定**

```bash
sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg > /dev/null <<'EOF'
network: {config: disabled}
EOF
```

**第二步：寫自己的 netplan 設定**

先確認介面名稱（前面已經看到是 `ens33`）與 NAT 網段的閘道。
NAT 網段的閘道**固定是該網段的 `.2`**（`.1` 是主機的虛擬網卡，`.254` 是 DHCP 伺服器）。
所以如果 DHCP 給你 `192.168.152.128/24`，閘道就是 `192.168.152.2`。★★★★

```bash
sudo tee /etc/netplan/01-static.yaml > /dev/null <<'EOF'
network:
  version: 2
  renderer: networkd
  ethernets:
    ens33:
      dhcp4: false
      addresses:
        - 192.168.152.50/24
      routes:
        - to: default
          via: 192.168.152.2
      nameservers:
        addresses: [192.168.152.2, 1.1.1.1]
EOF
```

Netplan 要求設定檔權限不能太寬鬆：

```bash
sudo chmod 600 /etc/netplan/01-static.yaml
```

**第三步：先試套用，別直接套死** ★★★★★

```bash
sudo netplan try
```

預期輸出：

```text
Do you want to keep these settings?

Press ENTER before the timeout to accept the new configuration

Changes will revert in 120 seconds
Configuration accepted.
```

> [!danger] ★★★★★ 一定要用 `netplan try`，不要直接 `netplan apply`
> 如果設定寫錯（IP 打錯、閘道打錯、介面名稱打錯），`netplan apply` 會**直接把網路弄斷**，
> 而你如果是用 SSH 連進來改的，**當下就斷線，也連不回去了**。
>
> `netplan try` 會套用設定並倒數 120 秒，你沒在時限內按 Enter 確認，
> 它就自動回復成原本的設定。這是遠端改網路唯一安全的做法。
>
> 在 VM 裡至少你還能開 Workstation 主控台救；**在遠端實體機上弄斷網路等於要跑機房**。

確認生效：

```bash
ip -4 addr show ens33 | grep inet
ip route
```

預期輸出：

```text
    inet 192.168.152.50/24 brd 192.168.152.255 scope global ens33
default via 192.168.152.2 dev ens33 proto static
192.168.152.0/24 dev ens33 proto kernel scope link src 192.168.152.50
```

測試連外：

```bash
ping -c 3 192.168.152.2      # 閘道
ping -c 3 1.1.1.1            # 外網 IP
ping -c 3 tw.archive.ubuntu.com   # DNS 解析 + 外網
```

三個都通才算完成。★★★★

> [!warning] ★★★ 靜態 IP 要避開 DHCP 池
> Workstation NAT 網段的 DHCP 池預設大約是 `.128` 到 `.254`。
> 你設 `.50` 是安全的（在池外）。如果設在池內，可能會和 DHCP 發給別台的位址撞號。
> DHCP 池範圍怎麼查、怎麼改，見 [[050-01-02-04-guide-Workstation-網路模式]]。

### ★★★ 事後調整硬體：哪些要關機才能改

| 項目 | 關機才能改？ | 說明 |
| --- | --- | --- |
| 記憶體 ★★★ | **是** | Workstation 不支援線上加記憶體 |
| CPU 核心數 ★★★ | **是** | 同上 |
| 硬碟容量（擴充）★★★ | **是** | 而且**有快照時擴不了** |
| 新增硬碟 ★★ | 建議關機 | SCSI 熱插拔理論可行但不穩 |
| 網路卡模式（NAT↔Bridged）★★ | 否 | 可以線上改，客體會看到網路斷再接 |
| CD/DVD 掛載 ★ | 否 | 隨時可換 ISO |
| USB 裝置 ★ | 否 | 隨時可接 |

> [!danger] ★★★★ 有快照時不能擴充虛擬磁碟
> Settings → Hard Disk → Expand 會變灰，並顯示：
>
> ```text
> This virtual machine has one or more snapshots.
> The disk cannot be expanded while snapshots exist.
> ```
>
> 必須先把所有快照刪掉（合併回主磁碟）才能擴。快照與磁碟鏈的關係見
> [[050-01-02-03-guide-Workstation-快照與複製]]。

### ★★★ 擴充磁碟的完整兩層流程

假設 40 GB 不夠，要擴到 60 GB。**兩層都要動**，只改 Workstation 那一層沒有用。

**第一層：Workstation（VM 關機、無快照）**

```text
VM → Settings → Hard Disk (SCSI) → Expand...
New size: 60 GB
[ Expand ]
```

跳出提示：

```text
The disk has been successfully expanded. You must repartition and expand
the file system from within the guest operating system for the change to
take effect.
```

**第二層：客體作業系統內**

開機進去，先看現況：

```bash
lsblk
```

預期輸出（磁碟變大了，但分割區還是舊的）：

```text
NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINTS
sda      8:0    0   60G  0 disk        ← 磁碟已經 60G
├─sda1   8:1    0    1G  0 part /boot/efi
└─sda2   8:2    0 38.7G  0 part /      ← 分割區還是 38.7G
```

擴分割區（`growpart` 由 `cloud-guest-utils` 提供，Ubuntu Server 預設有）：

```bash
sudo growpart /dev/sda 2
```

> [!warning] ★★★ 注意 `growpart` 的參數是「磁碟 空格 分割號」
> 是 `growpart /dev/sda 2`，**不是** `growpart /dev/sda2`。寫錯會得到
> `FAILED: /dev/sda2: does not exist`。

預期輸出：

```text
CHANGED: partition=2 start=2203648 old: size=81139679 end=83343327 new: size=123082719 end=125286367
```

擴檔案系統：

```bash
sudo resize2fs /dev/sda2
```

預期輸出：

```text
resize2fs 1.47.0 (5-Feb-2023)
Filesystem at /dev/sda2 is mounted on /; on-line resizing required
old_desc_blocks = 5, new_desc_blocks = 8
The filesystem on /dev/sda2 is now 15385339 (4k) blocks long.
```

確認：

```bash
df -h /
```

預期輸出：

```text
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2        58G  2.6G   53G   5% /
```

> [!tip] ★★ XFS 檔案系統用不同的指令
> RHEL 系預設是 XFS，擴充指令是 `sudo xfs_growfs /`（給掛載點，不是裝置）。
> `resize2fs` 只對 ext2/3/4 有效。

### ★★★ 加一顆額外的虛擬磁碟

練分割、練 LVM、練 RAID 時，**不要動系統碟**，加一顆新的來練。

```text
VM → Settings → Add... → Hard Disk → SCSI
→ Create a new virtual disk
→ 10 GB，不勾 Allocate all，Split
```

開機後：

```bash
lsblk
```

預期輸出：

```text
NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINTS
sda      8:0    0   40G  0 disk
├─sda1   8:1    0    1G  0 part /boot/efi
└─sda2   8:2    0 38.7G  0 part /
sdb      8:16   0   10G  0 disk        ← 新的空白磁碟
```

接下來的分割、格式化、掛載、寫 `/etc/fstab`，見
[[020-01-15-cmd-Linux-磁碟分割與掛載]]。

### ★★★ 從命令列操作 VM：`vmrun`

Workstation 有命令列工具 `vmrun`，適合寫成腳本批次開關機。

```bash
# Linux 主機
vmrun -T ws list
```

預期輸出：

```text
Total running VMs: 1
/home/user/VMs/lab-ubuntu-base/lab-ubuntu-base.vmx
```

```bash
# 開機（nogui 表示不開圖形視窗）
vmrun -T ws start /home/user/VMs/lab-ubuntu-base/lab-ubuntu-base.vmx nogui

# 正常關機（需要 VMware Tools／open-vm-tools）
vmrun -T ws stop /home/user/VMs/lab-ubuntu-base/lab-ubuntu-base.vmx soft

# 硬斷電（相當於拔電源）★★★★
vmrun -T ws stop /home/user/VMs/lab-ubuntu-base/lab-ubuntu-base.vmx hard
```

> [!danger] ★★★★ `stop ... hard` 等於直接拔電源
> 檔案系統會處於不一致狀態，下次開機要跑 fsck，嚴重時資料庫檔案損毀。
> **只在 `soft` 沒反應時才用**。

在 Windows 主機上，`vmrun.exe` 位於 Workstation 安裝目錄，
路徑與 PATH 設定見 [[050-01-02-01-svc-Workstation-安裝與授權]]。

---

## 完整實戰範例

### 情境

你是機關的資訊人員，主機是一台 Windows 11 筆電，16 GB 記憶體、512 GB NVMe SSD、
8 核心 16 執行緒的 CPU。Workstation 17 Pro 已經按
[[050-01-02-01-svc-Workstation-安裝與授權]] 裝好並驗證過。

目標：建出本手冊後續各章共用的基礎範本 `lab-ubuntu-base`，
狀態是「Ubuntu Server 24.04 LTS 裝好、更新完、open-vm-tools 裝好、
SSH 可從主機連入、靜態 IP `192.168.152.50`」，最後打上乾淨快照。

### 步驟 1：資源盤點 ★★★

在主機 PowerShell 上確認資源：

```powershell
# 記憶體總量
Get-CimInstance Win32_ComputerSystem | Select-Object -ExpandProperty TotalPhysicalMemory
```

預期輸出：

```text
17179869184
```

換算是 16 GB。

```powershell
# 邏輯 CPU 數
(Get-CimInstance Win32_Processor).NumberOfLogicalProcessors
```

預期輸出：

```text
16
```

```powershell
# D 槽剩餘空間
Get-PSDrive D | Select-Object Used,Free
```

預期輸出：

```text
        Used         Free
        ----         ----
 87241326592 236587810816
```

剩約 220 GB，夠。

**規劃結論**：

| 項目 | 值 | 依據 |
| --- | --- | --- |
| vCPU ★★★ | 2 | 16 邏輯 CPU，單台給 2 綽綽有餘 |
| 記憶體 ★★★★ | 4096 MB | 16 GB − 4 GB 主機 = 12 GB 可用，這台只佔三分之一 |
| 磁碟 ★★★ | 40 GB 動態成長分割 | 實際只會佔約 4 GB |
| 韌體 ★★★★ | UEFI，不開 Secure Boot | 對齊現代伺服器 |
| 網路 ★★★ | NAT | 最不會出問題 |
| 存放位置 ★★★★ | `D:\VMs\` | 不是 C 槽、不在 OneDrive 底下 |

### 步驟 2：準備 ISO 並驗證 ★★★★

```powershell
New-Item -ItemType Directory -Force -Path D:\ISO
# 下載 ubuntu-24.04.3-live-server-amd64.iso 到 D:\ISO\
Get-FileHash -Algorithm SHA256 D:\ISO\ubuntu-24.04.3-live-server-amd64.iso |
  Select-Object -ExpandProperty Hash
```

把輸出的雜湊值和官方 `SHA256SUMS` 比對，一致才往下走。

### 步驟 3：建立虛擬機 ★★★★

`Ctrl+N` → Custom (advanced)，依序：

```text
硬體相容性        Workstation 17.x
安裝來源          I will install the operating system later
客體作業系統      Linux → Ubuntu 64-bit
名稱              lab-ubuntu-base
位置              D:\VMs\lab-ubuntu-base
韌體              UEFI（不勾 Secure Boot）
處理器            1 顆 × 2 核心
記憶體            4096 MB
網路              NAT
I/O 控制器        LSI Logic
磁碟類型          SCSI
磁碟              建立新虛擬磁碟，40 GB，不勾 Allocate all，Split
```

最後一頁 **Customize Hardware…** → 移除 `Printer`、`Sound Card`。
取消勾選 `Power on this virtual machine after creation` → **Finish**。

驗證檔案已建立：

```powershell
Get-ChildItem D:\VMs\lab-ubuntu-base
```

預期輸出：

```text
    Directory: D:\VMs\lab-ubuntu-base

Mode    LastWriteTime         Length Name
----    -------------         ------ ----
-a---   2026/9/2   10:03        8684 lab-ubuntu-base.nvram
-a---   2026/9/2   10:03         365 lab-ubuntu-base.vmdk
-a---   2026/9/2   10:03        2547 lab-ubuntu-base.vmx
-a---   2026/9/2   10:03         276 lab-ubuntu-base.vmxf
```

> [!note] ★★ 此時 `.vmdk` 只有幾百 bytes
> 因為是動態成長，這個檔只是「描述檔」，真正的資料檔（`-s001.vmdk` 等）
> 要等作業系統開始寫入才會產生。★★★

### 步驟 4：掛 ISO ★★★★

```text
VM → Settings → CD/DVD (SATA)
  [v] Connect at power on
  (•) Use ISO image file:  D:\ISO\ubuntu-24.04.3-live-server-amd64.iso
[ OK ]
```

### 步驟 5：安裝 Ubuntu Server ★★★★

開機，依「安裝或基礎操作」第 3 節逐步操作。關鍵選擇再列一次：

| 頁面 | 選擇 |
| --- | --- |
| Language ★★★ | English |
| Keyboard ★ | English (US) |
| Type of install ★★★ | Ubuntu Server（不要 minimized） |
| Network ★★★★ | 確認 `ens33` 拿到 `192.168.152.x` |
| Proxy ★ | 留空 |
| Mirror ★★ | 確認 `passed tests` |
| Storage ★★★★ | Use an entire disk，**取消 LVM** |
| Profile ★★★★ | hostname `lab-ubuntu-base`，帳號 `labadmin` |
| Ubuntu Pro ★ | Skip for now |
| SSH ★★★★ | **勾 Install OpenSSH server** |
| Snaps ★★★ | 全部不勾 |

裝完 → **退出 ISO** → Reboot Now。

### 步驟 6：首次開機驗證 ★★★★

主控台登入 `labadmin`：

```bash
hostnamectl
```

預期輸出：

```text
 Static hostname: lab-ubuntu-base
       Icon name: computer-vm
         Chassis: vm
      Machine ID: 4f2c...省略...
         Boot ID: 9a1e...省略...
  Virtualization: vmware
Operating System: Ubuntu 24.04.3 LTS
          Kernel: Linux 6.8.0-xx-generic
    Architecture: x86-64
```

`Virtualization: vmware` 這行代表核心正確辨識出跑在 VMware 上。★★★

```bash
ls /sys/firmware/efi > /dev/null && echo "UEFI OK"
```

預期輸出：

```text
UEFI OK
```

```bash
df -h /
```

預期輸出：

```text
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2        38G  2.4G   34G   7% /
```

### 步驟 7：更新與安裝工具 ★★★★

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y open-vm-tools vim curl wget git \
  net-tools iproute2 dnsutils htop tree unzip
```

驗證：

```bash
systemctl is-active open-vm-tools
```

預期輸出：

```text
active
```

```bash
vmware-toolbox-cmd -v
```

預期輸出（版本號依套件版本而異）：

```text
12.3.5.1234 (build-xxxxxxx)
```

### 步驟 8：設定靜態 IP ★★★★★

```bash
# 8-1 關掉 cloud-init 的網路管理
sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg > /dev/null <<'EOF'
network: {config: disabled}
EOF

# 8-2 確認介面名稱與現有網段
ip -4 addr show | grep -E '^[0-9]+:|inet '
```

預期輸出：

```text
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    inet 127.0.0.1/8 scope host lo
2: ens33: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    inet 192.168.152.128/24 metric 100 brd 192.168.152.255 scope global dynamic ens33
```

網段是 `192.168.152.0/24`，所以閘道是 `192.168.152.2`。

```bash
# 8-3 寫靜態設定
sudo tee /etc/netplan/01-static.yaml > /dev/null <<'EOF'
network:
  version: 2
  renderer: networkd
  ethernets:
    ens33:
      dhcp4: false
      addresses:
        - 192.168.152.50/24
      routes:
        - to: default
          via: 192.168.152.2
      nameservers:
        addresses: [192.168.152.2, 1.1.1.1]
EOF

sudo chmod 600 /etc/netplan/01-static.yaml

# 8-4 語法檢查
sudo netplan generate
```

沒有輸出就是語法沒問題。有錯會像這樣：

```text
Error in network definition /etc/netplan/01-static.yaml line 8 column 8: expected mapping
```

```bash
# 8-5 安全套用
sudo netplan try
```

畫面顯示倒數時，按 Enter 確認：

```text
Do you want to keep these settings?

Press ENTER before the timeout to accept the new configuration

Changes will revert in 120 seconds
Configuration accepted.
```

驗證三連：

```bash
ip -4 addr show ens33 | grep inet
ping -c 2 192.168.152.2
ping -c 2 1.1.1.1
getent hosts tw.archive.ubuntu.com
```

預期輸出：

```text
    inet 192.168.152.50/24 brd 192.168.152.255 scope global ens33

PING 192.168.152.2 (192.168.152.2) 56(84) bytes of data.
64 bytes from 192.168.152.2: icmp_seq=1 ttl=128 time=0.312 ms
64 bytes from 192.168.152.2: icmp_seq=2 ttl=128 time=0.287 ms

PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=55 time=8.42 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=55 time=8.11 ms

185.125.190.82  tw.archive.ubuntu.com
```

### 步驟 9：從主機 SSH 連入 ★★★★

回到主機的 PowerShell：

```powershell
ssh labadmin@192.168.152.50
```

第一次會問指紋，輸入 `yes`，再輸入密碼。成功會看到：

```text
Welcome to Ubuntu 24.04.3 LTS (GNU/Linux 6.8.0-xx-generic x86_64)

  System information as of Tue Sep  2 10:41:02 CST 2026

  System load:  0.02
  Usage of /:   7.0% of 37.99GB
  Memory usage: 9%
  Swap usage:   0%

labadmin@lab-ubuntu-base:~$
```

設定金鑰登入（可選但強烈建議）：

```powershell
# 主機上，若還沒有金鑰
ssh-keygen -t ed25519 -C "lab"

# Windows 沒有 ssh-copy-id，用這行代替
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh labadmin@192.168.152.50 `
  "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

再連一次應該就不用密碼了。

### 步驟 10：清理範本痕跡 ★★★★

這一步很重要——之後要從這台複製出很多台，有些東西**不能重複**。

```bash
# 清 apt 快取，範本瘦一點
sudo apt clean
sudo apt autoremove -y

# 清日誌
sudo journalctl --rotate
sudo journalctl --vacuum-time=1s

# 清 shell 歷史
history -c
cat /dev/null > ~/.bash_history
```

> [!warning] ★★★★ machine-id 必須在複製後重新產生
> `/etc/machine-id` 是每台機器的唯一識別碼。如果所有複製出來的機器
> 都帶著同一個 machine-id，會造成：
> - systemd-networkd 用 machine-id 產生 DHCP client identifier，
>   **所有機器向 DHCP 要位址時被認為是同一台，互相搶 IP** ★★★★
> - journald 的遠端日誌收集分不清來源 ★★★
>
> 處理方式是在**複製出來的新機器上**執行（不是在範本上）：
>
> ```bash
> sudo rm -f /etc/machine-id
> sudo rm -f /var/lib/dbus/machine-id
> sudo systemd-machine-id-setup
> sudo ln -sf /etc/machine-id /var/lib/dbus/machine-id
> sudo reboot
> ```
>
> 完整的複製流程與要改的所有項目（hostname、machine-id、SSH host key、
> 靜態 IP）在 [[050-01-02-03-guide-Workstation-快照與複製]]。

### 步驟 11：正常關機並打快照 ★★★★★

```bash
sudo shutdown -h now
```

等 Workstation 顯示 VM 已關機（左邊清單的圖示變灰）。

> [!danger] ★★★★★ 一定要在「完全關機」狀態打範本快照
> 開機中打的快照會包含記憶體狀態（`.vmem` 檔可能好幾 GB），
> 而且從它做連結複製時會綁住那個記憶體狀態，非常笨重。
>
> **範本的乾淨快照一定要在關機狀態打**。

```text
VM → Snapshot → Take Snapshot...
Name:        clean-base
Description: Ubuntu 24.04.3 LTS 全新安裝 + 更新至 2026-09-02
             + open-vm-tools + 常用工具
             靜態 IP 192.168.152.50，帳號 labadmin
             未安裝任何服務
[ Take Snapshot ]
```

### 完成確認

逐項核對：

- [ ] `lab-ubuntu-base` 在 Workstation 清單中，狀態為關機 ★★★
- [ ] `D:\VMs\lab-ubuntu-base\` 內有 `.vmx`、`.vmdk`、`-s00N.vmdk`、`.vmsn` ★★★
- [ ] 開機後 `hostnamectl` 顯示 `Virtualization: vmware` ★★★
- [ ] `ls /sys/firmware/efi` 有輸出（UEFI）★★★★
- [ ] `df -h /` 顯示約 38 GB 可用（沒踩 LVM 只配一半）★★★★
- [ ] `systemctl is-active open-vm-tools` 回 `active` ★★★★
- [ ] 主機能 `ssh labadmin@192.168.152.50` 連入 ★★★★
- [ ] VM 內 `ping 1.1.1.1` 與 DNS 解析都通 ★★★★
- [ ] 快照管理員裡有一個名為 `clean-base` 的快照 ★★★★★
- [ ] 範本裡**沒有**安裝任何服務（沒有 nginx、mysql、docker）★★★★★

全部打勾，後面每一章要用機器時，就從這台連結複製。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| 開機停在 `UEFI Interactive Shell` 或 `Shell>` ★★★★ | 找不到可開機媒體：ISO 沒掛、或沒勾 `Connect at power on` | Settings → CD/DVD 勾 `Connected` 與 `Connect at power on`，確認 ISO 路徑正確 |
| 開機顯示 `>>Start PXE over IPv4` 一直重試 ★★★ | 同上，UEFI 找不到磁碟與光碟就去嘗試網路開機 | 掛好 ISO；已裝好系統的話代表開機載入器沒裝上或韌體型別被改過 |
| 裝完重開又進入安裝程式 ★★★ | ISO 沒退出，UEFI 優先從光碟開機 | VM → Removable Devices → CD/DVD → Disconnect，或取消 `Connect at power on` |
| 裝完開機 `Operating System not found` ★★★★ | 裝完後把韌體型別從 UEFI 改成 BIOS（或反過來） | Settings → Options → Advanced 把韌體改回原本的型別 |
| `This host supports Intel VT-x, but Intel VT-x is disabled` ★★★★★ | 主機 BIOS 沒開虛擬化，或被 Hyper-V／Device Guard 佔用 | 進主機 BIOS 開 VT-x／AMD-V；Windows 上關掉 Hyper-V，見 [[050-01-02-01-svc-Workstation-安裝與授權]] |
| `Not enough physical memory is available to power on this virtual machine` ★★★★ | 主機實體記憶體不足，或其他 VM 已佔滿 | 關掉其他 VM；把這台的記憶體調低；Edit → Preferences → Memory 調整配置策略 |
| 安裝程式的網路頁沒拿到 IP ★★★★ | 網路卡沒 Connected、或主機的 VMware NAT／DHCP 服務沒跑 | 勾 Settings → Network Adapter 的 `Connected`；主機檢查 `VMware NAT Service`、`VMware DHCP Service` |
| 套件下載很慢或 `Failed to fetch` ★★★ | 鏡像站不通、或機關 Proxy 沒設 | Mirror 改成 `http://archive.ubuntu.com/ubuntu`；有 Proxy 就在安裝程式的 Proxy 頁填 |
| 裝完 `df -h /` 只有約 19 GB ★★★★ | 安裝時勾了 LVM，guided 只配一半空間給根 LV | `sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv && sudo resize2fs /dev/ubuntu-vg/ubuntu-lv` |
| `growpart /dev/sda2` 回 `FAILED: /dev/sda2: does not exist` ★★★ | 參數格式錯，應為「磁碟 空格 分割號」 | 改成 `sudo growpart /dev/sda 2` |
| Settings 裡 Hard Disk 的 `Expand` 是灰色 ★★★★ | 這台 VM 有快照存在 | 先在快照管理員刪掉全部快照（會合併回主磁碟），再擴充 |
| 磁碟擴充後 `df` 沒變大 ★★★ | 只做了 Workstation 那一層，客體裡沒擴 | 進客體跑 `growpart` + `resize2fs`（XFS 用 `xfs_growfs /`） |
| `netplan apply` 之後 SSH 斷線連不回 ★★★★★ | 靜態設定寫錯（IP／閘道／介面名稱） | 從 Workstation 主控台登入修正；**下次用 `netplan try`** |
| netplan 設定重開機後失效 ★★★★ | 改的是 `50-cloud-init.yaml`，被 cloud-init 蓋回去 | 建 `/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg` 停用，另建自己的 netplan 檔 |
| `netplan try` 回 `Permission denied` 或警告權限太寬 ★★ | netplan 檔案權限大於 600 | `sudo chmod 600 /etc/netplan/*.yaml` |
| 主機磁碟一直變小，VM 裡卻沒長 ★★★★ | 動態成長磁碟只長不縮，刪檔不會讓 `.vmdk` 縮小 | 手動壓實磁碟，見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] |
| VM 時間比主機慢好幾分鐘 ★★★★ | 沒裝 `open-vm-tools`，或時間同步沒啟用 | `sudo apt install -y open-vm-tools`；時間同步詳見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]] |
| 選單的 `Shut Down Guest` 按了沒反應 ★★★ | 沒裝 VMware Tools，主機無法通知客體關機 | 裝 `open-vm-tools`；當下先在客體內 `sudo shutdown -h now` |
| 主機整台變得極慢，硬碟燈狂閃 ★★★★★ | VM 記憶體超賣，主機開始交換 | 立刻關掉部分 VM；重新規劃記憶體配置，總和 ≤ 主機記憶體 − 4 GB |
| VM 檔案偶爾被鎖住、開機報 `.lck` 錯誤 ★★★★ | VM 存在 OneDrive／Dropbox 同步資料夾內 | 把整個 VM 資料夾搬出同步範圍；同步軟體排除 `D:\VMs` |
| 客體看不到 NVMe 磁碟（裝舊系統時）★★★ | 舊安裝程式沒有 NVMe 驅動 | 磁碟類型改用 SCSI 重建虛擬機 |

---

## 安全性注意事項

### ★★★★ 實驗機的密碼不能和正式環境相同

實驗機常常被複製、被匯出、被同事拿去玩，而且密碼往往很簡單。
**一旦你用了正式環境的密碼，等於把正式密碼散佈到一堆來歷不明的 VM 檔案裡**。

規則：

| 環境 | 密碼策略 |
| --- | --- |
| 實驗範本 ★★★ | 專用的簡單密碼，只在實驗網段用 |
| 正式環境 ★★★★★ | 獨立密碼，走密碼管理工具，絕不重用 |
| 對外服務 ★★★★★ | 一律金鑰登入，關掉密碼認證 |

### ★★★★ 範本裡不要放任何憑證、金鑰或機關資料

範本會被複製 N 次，任何放在裡面的東西都會擴散 N 份。

- 不要在範本裡放 `.ssh/id_ed25519`（私鑰）★★★★★
- 不要在範本裡放測試用的伺服器憑證私鑰 ★★★★
- 不要在範本裡放任何機關的實際資料檔 ★★★★★
- 不要在範本的 `~/.bash_history` 留下含密碼的指令 ★★★

### ★★★★ 複製前一定要重新產生的三樣東西

| 項目 | 重複的後果 | 處理 |
| --- | --- | --- |
| `/etc/machine-id` ★★★★ | DHCP 互搶位址、日誌來源混淆 | `systemd-machine-id-setup` |
| SSH host key ★★★★ | 所有機器指紋相同，中間人攻擊偵測失效 | `sudo rm /etc/ssh/ssh_host_* && sudo dpkg-reconfigure openssh-server` |
| hostname ★★★ | 日誌與監控分不出是哪一台 | `sudo hostnamectl set-hostname <新名稱>` |

### ★★★ ISO 的來源與完整性

- 只從發行版官方站或官方鏡像下載 ★★★★
- **一定驗證 SHA256**，不要因為麻煩就跳過 ★★★★
- 機關內部如果有共用 ISO 庫，也要驗證，因為共用目錄可能被誤放或被竄改 ★★★
- 不要用來路不明的「已預裝好的 VM 映像」——那可能夾帶後門 ★★★★★

### ★★★ 實驗機的網路暴露面

NAT 模式下 VM 預設**不會被外網主動連入**，這是它相對安全的原因。
但如果你之後改成 Bridged，VM 就直接掛在機關內網上：

- 內網掃描會掃到它，弱密碼會被爆破 ★★★★
- 它如果被入侵，就是機關內網的一個跳板 ★★★★★
- 機關的資安稽核可能會把它列為未納管設備 ★★★★

所以本手冊的實驗機**除非該章明確需要，否則一律留在 NAT**。
網路模式的取捨見 [[050-01-02-04-guide-Workstation-網路模式]]。

### ★★★ 不要用 Use a physical disk

前面已經警告過，這裡再強調一次：那個選項會讓虛擬機直接對主機的實體磁碟做讀寫。
安裝程式格式化時**沒有任何保護**，選錯裝置就是主機資料全滅，而且不可逆。
實驗環境永遠用「建立新的虛擬磁碟」。★★★★★

### ★★ 停用不需要的虛擬裝置

移除 `Sound Card`、`Printer`、以及不需要時的 `USB Controller`，
除了省資源，也少一份被利用的介面。USB 直通更要小心：
把主機的隨身碟直通給 VM，如果 VM 裡有惡意程式，那顆隨身碟也會被感染。★★★

---

## 速查表

### 精靈設定值（本手冊標準範本）

| 頁面 | 值 |
| --- | --- |
| 精靈模式 | Custom (advanced) |
| 硬體相容性 | Workstation 17.x |
| 安裝來源 | I will install the operating system later |
| 客體 OS | Linux → Ubuntu 64-bit |
| 名稱 | `lab-ubuntu-base` |
| 位置 | `D:\VMs\lab-ubuntu-base`（本機 SSD，非雲端同步） |
| 韌體 | UEFI，不勾 Secure Boot |
| 處理器 | 1 顆 × 2 核心 |
| 記憶體 | 4096 MB |
| 網路 | NAT |
| I/O 控制器 | LSI Logic |
| 磁碟類型 | SCSI |
| 磁碟 | 新建 40 GB，不勾 Allocate all，Split |

### 配置準則

| 資源 | 準則 |
| --- | --- |
| vCPU 總和 | ≤ 主機邏輯 CPU × 1.5 |
| 單台 vCPU | 一般 2，巢狀虛擬化 4 |
| 記憶體總和 | ≤ 主機實體記憶體 − 4 GB |
| 單台記憶體 | Server 純文字 2 GB／含服務 4 GB／巢狀 8 GB |
| 磁碟 | Server 範本 40 GB，含 Docker 60～80 GB |

### 磁碟四種組合

| 組合 | 建立速度 | 立即佔用 | 可放 exFAT | 適用 |
| --- | --- | --- | --- | --- |
| 動態 + 分割 | 快 | 小 | 是 | **本手冊預設** |
| 動態 + 單一檔 | 快 | 小 | 否 | 不搬機時 |
| 預配 + 單一檔 | 慢 | 全部 | 否 | 效能測試 |
| 預配 + 分割 | 慢 | 全部 | 是 | 少見 |

### 常用鍵盤與選單

| 動作 | 操作 |
| --- | --- |
| 新增虛擬機 | `Ctrl+N` |
| VM 設定 | `Ctrl+D` |
| 放開滑鼠鍵盤 | `Ctrl+Alt` |
| 全螢幕切換 | `Ctrl+Alt+Enter` |
| 送出 Ctrl+Alt+Del | `Ctrl+Alt+Insert` |
| 開機進韌體 | VM → Power → Power On to Firmware |
| 退出 ISO | VM → Removable Devices → CD/DVD → Disconnect |
| 打快照 | VM → Snapshot → Take Snapshot |

### 客體內驗證指令

| 目的 | 指令 | 期望 |
| --- | --- | --- |
| 確認跑在 VMware 上 | `hostnamectl` | `Virtualization: vmware` |
| 確認 UEFI | `ls /sys/firmware/efi` | 有輸出 |
| 確認 vCPU | `nproc` | `2` |
| 確認記憶體 | `free -h` | 約 `3.8Gi` |
| 確認磁碟 | `lsblk` / `df -h /` | `sda2` 約 38G |
| 確認 tools | `systemctl is-active open-vm-tools` | `active` |
| 確認 tools 版本 | `vmware-toolbox-cmd -v` | 版本字串 |
| 確認 sshd | `sudo ss -tlnp \| grep :22` | 有 LISTEN |
| 看 IP | `ip -4 addr show ens33` | `inet ...` |
| 看路由 | `ip route` | 有 `default via` |

### 擴充磁碟兩層流程

| 層 | 動作 |
| --- | --- |
| Workstation（關機、無快照） | Settings → Hard Disk → Expand → 新容量 |
| 客體（ext4） | `sudo growpart /dev/sda 2` → `sudo resize2fs /dev/sda2` |
| 客體（XFS） | `sudo growpart /dev/sda 2` → `sudo xfs_growfs /` |
| 客體（LVM） | `growpart` → `pvresize` → `lvextend -l +100%FREE` → `resize2fs` |

### 靜態 IP 三步驟（Ubuntu Netplan）

| 步驟 | 指令 |
| --- | --- |
| 1 停用 cloud-init 網路 | 建 `/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg` 內容 `network: {config: disabled}` |
| 2 寫設定 | 建 `/etc/netplan/01-static.yaml`，`chmod 600` |
| 3 安全套用 | `sudo netplan generate` → `sudo netplan try` → 按 Enter |

### NAT 網段位址慣例

| 位址 | 角色 |
| --- | --- |
| `x.x.x.1` | 主機的 VMnet8 虛擬網卡 |
| `x.x.x.2` | NAT 閘道（VM 的 default gateway 與 DNS） |
| `x.x.x.128 ～ .254` | DHCP 位址池（預設範圍） |
| `x.x.x.254` | DHCP 伺服器 |
| `x.x.x.3 ～ .127` | 建議的靜態位址範圍 |

### `vmrun` 常用指令

| 目的 | 指令 |
| --- | --- |
| 列出執行中的 VM | `vmrun -T ws list` |
| 背景開機 | `vmrun -T ws start <path>.vmx nogui` |
| 正常關機 | `vmrun -T ws stop <path>.vmx soft` |
| 硬斷電 ★★★★ | `vmrun -T ws stop <path>.vmx hard` |
| 查客體 IP | `vmrun -T ws getGuestIPAddress <path>.vmx` |

### 虛擬機資料夾內的檔案

| 副檔名 | 內容 |
| --- | --- |
| `.vmx` | 主設定檔（文字檔，可手改） |
| `.vmdk` | 虛擬磁碟描述檔 |
| `-s00N.vmdk` | 分割磁碟的實際資料片段 |
| `.nvram` | 虛擬 BIOS／UEFI 的 NVRAM |
| `.vmsd` | 快照的中繼資料 |
| `.vmsn` | 快照狀態檔 |
| `.vmem` | 開機中 VM 的記憶體對應檔 |
| `.lck` 目錄 | 執行中的鎖定目錄，正常關機後會消失 |
| `.log` | 執行日誌，排錯必看 |

---

## 練習題

> [!question]- 練習 1：算出你自己主機的配置上限
> 在你自己的主機上查出實體記憶體與邏輯 CPU 數，然後回答：
> （a）你最多可以同時開幾台 4 GB／2 vCPU 的 VM？
> （b）如果要開一台 8 GB 的 PVE 巢狀機，還能同時開幾台 2 GB 的機器？
>
> ---
> **解答**
>
> 查詢指令：
>
> ```powershell
> # Windows
> (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
> (Get-CimInstance Win32_Processor).NumberOfLogicalProcessors
> ```
>
> ```bash
> # Linux
> free -h
> nproc
> ```
>
> 以 16 GB / 16 邏輯 CPU 為例：
>
> - 可分配記憶體 = 16 − 4 = **12 GB**
> - （a）12 ÷ 4 = **3 台**。vCPU 檢查：3 × 2 = 6 ≤ 16 × 1.5 = 24，記憶體是瓶頸。
> - （b）12 − 8 = 4 GB 剩餘 → **2 台** 2 GB 的機器。
>
> 重點是**記憶體幾乎永遠是先撞到的限制**，不是 CPU。★★★★

> [!question]- 練習 2：驗證磁碟是不是真的動態成長
> 建一台 40 GB 動態成長的空白 VM（不裝作業系統），觀察主機上實際佔用多少；
> 然後裝完 Ubuntu Server 再看一次。
>
> ---
> **解答**
>
> ```powershell
> # 建好但還沒開機
> Get-ChildItem D:\VMs\lab-test -Recurse |
>   Measure-Object -Property Length -Sum |
>   Select-Object @{n='MB';e={[math]::Round($_.Sum/1MB,1)}}
> ```
>
> 預期約 **0.1 MB**（只有描述檔與設定檔）。
>
> 裝完 Ubuntu Server 之後再跑一次，預期約 **4000～5000 MB**，
> 遠小於宣告的 40 GB。
>
> 這證明了兩件事：
> 1. 動態成長真的只佔實際用量 ★★★
> 2. 所以你可以放心把磁碟宣告大一點 ★★★
>
> 再進一步：在 VM 裡 `dd if=/dev/zero of=big.bin bs=1M count=2000` 造一個 2 GB 檔，
> 主機端會多約 2 GB；把 `big.bin` 刪掉，**主機端不會縮回去** ★★★★。

> [!question]- 練習 3：故意選錯韌體，觀察症狀
> 把已經裝好的 VM 關機，Settings → Options → Advanced 把韌體從 UEFI 改成 BIOS，
> 開機看看發生什麼。記錄畫面訊息，然後改回去。
>
> ---
> **解答**
>
> 改成 BIOS 後開機，會看到類似：
>
> ```text
> Operating System not found
> ```
>
> 或 UEFI 韌體嘗試網路開機的訊息。**原因**：作業系統的開機載入器裝在 EFI 系統分割區
> (`/boot/efi`)，BIOS 模式的韌體不會去讀那裡，而磁碟的 MBR 沒有可執行的開機碼。
>
> 改回 UEFI 後即可正常開機。
>
> 教訓：**韌體型別在裝完系統後就固定了**，記在 VM 的 Notes 裡。★★★★

> [!question]- 練習 4：完整走一次擴充磁碟
> 把 `lab-ubuntu-base` 的複製品從 40 GB 擴到 60 GB，兩層都做完，並驗證。
>
> ---
> **解答**
>
> 前置：**刪掉全部快照**（有快照 Expand 是灰的）。
>
> ```text
> VM 關機 → Settings → Hard Disk (SCSI) → Expand... → 60 → Expand
> ```
>
> 開機進客體：
>
> ```bash
> lsblk                       # sda 已 60G，sda2 仍 38.7G
> sudo growpart /dev/sda 2
> sudo resize2fs /dev/sda2
> df -h /                     # 應顯示約 58G
> ```
>
> 常見錯誤：只做了 Workstation 那層就以為完成了，`df` 沒變會很困惑。★★★

> [!question]- 練習 5：把靜態 IP 改錯，用 `netplan try` 救回來
> 故意把 `01-static.yaml` 的閘道寫成不存在的 `192.168.152.99`，
> 用 `sudo netplan try`，不要按 Enter，觀察 120 秒後發生什麼。
>
> ---
> **解答**
>
> `netplan try` 會套用新設定，你會發現 `ping 1.1.1.1` 不通
> （因為 default gateway 指到一個不存在的位址）。
>
> 不按 Enter，等 120 秒後畫面顯示：
>
> ```text
> Reverting.
> ```
>
> 網路自動回復成套用前的狀態，`ping` 又通了。
>
> 這就是為什麼遠端改網路**永遠**用 `netplan try` 而不是 `netplan apply`。★★★★★
> 對照組：把同樣的錯誤設定用 `netplan apply` 套用，SSH 會立刻斷線且連不回來，
> 只能從 Workstation 主控台救（實體機就得跑機房）。

> [!question]- 練習 6：找出 open-vm-tools 沒裝的三個症狀
> 把測試機的 `open-vm-tools` 移除，重開機後找出至少三個可觀察到的差異。
>
> ---
> **解答**
>
> ```bash
> sudo apt remove -y open-vm-tools
> sudo reboot
> ```
>
> 可觀察到的症狀：
>
> 1. **VM → Power → Shut Down Guest 沒反應**（只剩 Power Off 硬斷電可用）★★★★
> 2. `vmware-toolbox-cmd -v` 回 `command not found` ★★
> 3. Workstation 的 VM 摘要頁不再顯示客體 IP 位址 ★★★
> 4. `vmrun getGuestIPAddress` 逾時失敗 ★★★
> 5. 把 VM 暫停很久再恢復，時間會停在暫停當下不會自動追上 ★★★★
>
> 裝回去：`sudo apt install -y open-vm-tools && sudo reboot`。

---

## 小測驗

Q1. 新增虛擬機精靈裡，為什麼本手冊要求選「I will install the operating system later」而不是直接指定 ISO？

Q2. 是非題：把虛擬磁碟「分割成多個檔案」可以提供容錯，其中一片壞掉時其他資料還在。

Q3. 主機有 32 GB 記憶體，依照本篇的準則，同時開機的 VM 記憶體總和最多可以到多少？

Q4. 這個指令會發生什麼事？
```bash
sudo growpart /dev/sda2
```

Q5. 選擇題：VM 裝完 Ubuntu 後 `df -h /` 只顯示約 19 GB，宣告的是 40 GB。最可能的原因是？
（A）動態成長磁碟還沒長大　（B）安裝時勾了 LVM，guided 只配一半給根 LV
（C）UEFI 的 ESP 佔掉一半　（D）Workstation 的磁碟壓縮功能

Q6. Workstation NAT 網段裡，VM 的 default gateway 應該設成該網段的哪一個位址？為什麼不是 `.1`？

Q7. 為什麼一定要用 `netplan try` 而不是 `netplan apply`？各自失敗時的後果是什麼？

Q8. 是非題：`/etc/netplan/50-cloud-init.yaml` 是 Ubuntu 的主要網路設定檔，直接修改它是正確做法。

Q9. 一台 VM 有兩個快照，你想把磁碟從 40 GB 擴到 80 GB，Settings 裡的 Expand 按鈕是灰的。為什麼？該怎麼辦？

Q10. 從範本複製出新機器後，有三樣東西一定要重新產生。是哪三樣？各自不改會出什麼問題？

> [!question]- 測驗答案
> **Q1.** 直接指定 ISO 會觸發 Workstation 的 **Easy Install**，它用自己的一套分割與套件選擇全自動裝完，你不知道它做了什麼、也學不到安裝程式的實際畫面。選「稍後安裝」建出空機器，再自己掛 ISO 開機才看得到完整流程。★★★（見「觀念說明 → 兩種建立方式」）
>
> **Q2.** **錯。** 分割成多檔**不提供任何容錯**，其中一片損毀整顆虛擬磁碟就讀不回來。分割唯一的意義是繞過檔案系統的單檔大小限制（例如 FAT32／exFAT 的 4 GB）以及方便備份工具處理。★★★（見「虛擬磁碟 → 選擇二」）
>
> **Q3.** **28 GB**。準則是「所有同時開機的 VM 記憶體總和 ≤ 主機實體記憶體 − 4 GB」，32 − 4 = 28 GB。超過會讓主機開始把 VM 記憶體換到磁碟，主機與 VM 一起停頓。★★★★（見「硬體配置 → 記憶體」）
>
> **Q4.** **會失敗**，輸出 `FAILED: /dev/sda2: does not exist`。`growpart` 的參數格式是「磁碟 空格 分割號」，正確寫法是 `sudo growpart /dev/sda 2`。★★★（見「擴充磁碟的完整兩層流程」）
>
> **Q5.** **（B）**。Ubuntu 安裝程式的 guided LVM 預設只把約一半空間配給根 LV，其餘留在 VG 裡。這是本篇建議實驗範本**不要勾 LVM** 的主要理由。要救的話是 `lvextend -l +100%FREE` 再 `resize2fs`。★★★★（見「磁碟分割」與排錯表）
>
> **Q6.** 設成該網段的 **`.2`**。Workstation NAT 網段的角色分工是：`.1` 是**主機自己的 VMnet8 虛擬網卡**（只是主機在這個網段的一隻腳，不做轉送），`.2` 才是真正做位址轉換往外送的 **NAT 閘道**，`.254` 是 DHCP 伺服器。指到 `.1` 出不去外網。★★★★（見「設定靜態 IP」與速查表）
>
> **Q7.** `netplan try` 套用後倒數 120 秒，沒在時限內按 Enter 確認就**自動回復**成原設定；`netplan apply` 是**立即且永久**套用。設定寫錯時，`apply` 會當場把網路弄斷，SSH 連線立刻中斷而且連不回去——在 VM 裡還能開主控台救，在遠端實體機上就得跑機房。★★★★★（見「事四：設定靜態 IP」）
>
> **Q8.** **錯。** 那個檔是 cloud-init 產生的，重開機或 cloud-init 重跑時會被覆蓋，你的修改會消失。正確做法是先建 `/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg` 停用 cloud-init 的網路管理，再自己另建一個 netplan 檔（例如 `01-static.yaml`）。★★★★（見「事四」與排錯表）
>
> **Q9.** 因為**有快照存在時不能擴充虛擬磁碟**——磁碟資料分散在快照的差異磁碟鏈上，改變基礎磁碟大小會破壞鏈的一致性。做法是先在快照管理員刪掉全部快照（刪除會把差異合併回主磁碟，不會丟資料），Expand 就會變成可按。★★★★（見「事後調整硬體」）
>
> **Q10.** **`/etc/machine-id`**（重複會讓 systemd-networkd 產生相同的 DHCP client identifier，多台機器互搶同一個 IP，日誌來源也分不清）、**SSH host key**（所有機器指紋相同，中間人攻擊的偵測機制失效）、**hostname**（日誌與監控分不出是哪一台）。★★★★（見「步驟 10：清理範本痕跡」與「安全性注意事項」）

---

## 延伸閱讀

- [[050-01-02-01-svc-Workstation-安裝與授權]] — Workstation 本身的安裝、授權與 Hyper-V 共存
- [[050-01-02-03-guide-Workstation-快照與複製]] — 打快照、連結複製、用範本量產實驗機
- [[050-01-02-04-guide-Workstation-網路模式]] — NAT／Bridged／Host-only 的取捨與可達性矩陣
- [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] — VMware Tools 完整說明與檔案交換
- [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] — 磁碟壓實、效能瓶頸排查
- [[050-01-01-01-guide-虛擬化-虛擬化概念與選型]] — Type-1 與 Type-2 的差別
- [[050-01-01-03-ref-虛擬化-五平台橫向對照]] — Workstation 與其他平台的定位比較
- [[050-01-03-01-svc-PVE-安裝與初始設定]] — 在 Workstation 裡巢狀跑 Proxmox VE
- [[020-01-02-guide-Linux-實驗環境準備與初次登入]] — Linux 章節的實驗環境需求
- [[020-01-15-cmd-Linux-磁碟分割與掛載]] — 額外虛擬磁碟的分割、格式化與 fstab
- [[020-01-16-cmd-Linux-網路基礎指令]] — `ip`、`ss`、`ping` 的完整用法
- [[020-01-14-guide-Linux-套件管理]] — apt 的完整操作
- [[020-01-28-cmd-Linux-時間同步NTP與chrony]] — 虛擬機時間飄移的處理
- [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] — SSH 金鑰登入設定
- [[020-02-03-01-svc-標準化-新機建置標準流程]] — 把這套流程制度化成機關的 SOP
