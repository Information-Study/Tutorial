---
title: "效能調校與疑難排解"
desc: "CPU 與記憶體配置準則、虛擬磁碟型式與壓縮、關閉不需要的虛擬裝置、巢狀虛擬化的開啟與驗證，以及完整的常見錯誤排錯表"
aliases: [巢狀虛擬化, nested virtualization, vhv.enable, vmware-vdiskmanager, Workstation 效能, VT-x 未啟用]
tags: [群組/虛擬機與容器, 主題/虛擬化, 主題/VMware]
category: 虛擬機與容器
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]]"]
updated: 2026-09-02
---

# 效能調校與疑難排解

> [!warning] 未實機驗證
> 本篇的選單路徑與畫面文字**以 VMware Workstation 17 為例**，其他版本的選單位置、
> 分頁名稱與勾選項目文字可能不同（`VM → Settings → Processors` 這一頁的選項在不同版本
> 增減過）。`.vmx` 參數與命令列工具的行為亦可能隨版本調整，
> **請以你手上版本的實際畫面與 `--help` 輸出為準**。

> [!abstract] 這篇你會學到
> - 為什麼「配越多越快」是錯的——vCPU 與記憶體的配置準則 ★★★★
> - 給主機留多少資源才不會整台一起卡 ★★★★★
> - 虛擬磁碟放 SSD 與放傳統硬碟的實際差距，以及磁碟型式怎麼選 ★★★★
> - 哪些虛擬裝置可以直接拔掉，拔掉能省什麼 ★★★
> - ★★★★★ **巢狀虛擬化怎麼開、怎麼驗證**——本手冊的 PVE 與 KVM 章節全靠它
> - 磁碟膨脹了怎麼壓回來：Guest 端歸零 → Host 端壓縮的完整流程 ★★★★
> - 快照鏈太長會發生什麼事，以及該留幾層 ★★★★★
> - 一張 20 列以上的排錯表，錯誤訊息寫原文，看到就能對號入座 ★★★★★

## 前置知識

- [[050-01-02-01-svc-Workstation-安裝與授權]]
- [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]]
- [[050-01-02-03-guide-Workstation-快照與複製]]
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]]

---

## 觀念說明

### ★★★★★ 第一原則：資源是從主機挖走的

這是所有調校的起點。Workstation 是 Type-2 Hypervisor，**它跑在你的桌面作業系統之上**，
不像 ESXi／Proxmox VE 那樣獨佔整台機器。

```text
  實體主機 32 GB / 8 核
  ├── Windows 桌面本身（瀏覽器、Office、防毒…）  ← 這些不會消失
  ├── Workstation 程式本身
  ├── VM A（8 GB / 4 vCPU）
  ├── VM B（8 GB / 2 vCPU）
  └── VM C（4 GB / 2 vCPU）
      ↑ 這三台加起來 20 GB / 8 vCPU，主機只剩 12 GB 與「被瓜分的」8 核
```

新手最常見的誤解是「反正 VM 沒在忙，配多一點沒差」。**在 Workstation 上這是錯的**：

| 誤解 | 實際情況 |
| --- | --- |
| 「記憶體配 16 GB，VM 只用 2 GB，其他還給主機」★★★★★ | Workstation 預設會**盡量把 VM 記憶體放進主機實體 RAM**，配多少大致就佔多少 |
| 「vCPU 配 8 顆比 4 顆快」★★★★★ | vCPU 超過實體核心後，Hypervisor 要排隊調度，**反而變慢** |
| 「多開幾台 VM 沒關係，反正閒著」★★★★ | 每台 VM 都有基本開銷（記憶體、背景程序、磁碟 I/O） |
| 「磁碟配 200 GB，反正是動態成長」★★★ | 動態成長沒錯，但**只會長不會縮**，寫過的空間不會自動還你 |

> [!danger] ★★★★★ 主機開始 swap 就全滅
> 把記憶體配到主機只剩 1～2 GB，Windows 會開始把東西丟到 pagefile。
> 這時候**不是只有 VM 慢，是整台電腦（滑鼠都會卡）一起慢**，
> 而且因為 VM 的記憶體檔案也在被換出換入，情況會惡性循環。
> **給主機留 4～6 GB 是硬底線。**

### ★★★★ CPU 配置準則

#### vCPU 到底是什麼

在 Workstation 的 `VM → Settings → Processors` 頁有兩個欄位：

| 欄位 | 意義 |
| --- | --- |
| `Number of processors` ★★★ | 虛擬「插槽」數 |
| `Number of cores per processor` ★★★ | 每個插槽幾核 |
| `Total processor cores` ★★★★ | 兩者相乘＝**實際的 vCPU 總數，這才是重點** |

> [!note] 插槽數與核心數怎麼分配？★★★
> 對絕大多數 Linux Guest 來說**沒有差別**，總數才重要。
> 但有些商業軟體是**按插槽（socket）授權**的，這時候應該
> **1 個插槽 × N 核**，而不是 N 個插槽 × 1 核。
> 練習環境一律用「1 processor × N cores」最單純。

#### ★★★★★ 準則：所有執行中 VM 的 vCPU 總和，不要超過實體核心數

```text
主機：8 核（含超執行緒 16 執行緒）

✅ 好：VM A 4 vCPU + VM B 2 vCPU + VM C 2 vCPU = 8
⚠️ 勉強：總和 12（靠超執行緒硬撐，會有排隊）
❌ 差：VM A 8 + VM B 8 = 16，兩台都很卡
```

**為什麼超配會變慢**：Hypervisor 必須讓一台 VM 的所有 vCPU **同時**拿到實體核心
才能推進（co-scheduling），vCPU 配越多，湊齊的機會越少，等待時間（CPU ready time）越長。
**四核的 VM 反而可能比雙核的 VM 慢**，這是虛擬化裡很反直覺但很真實的現象。★★★★★

#### 實務配置表

| 用途 | 建議 vCPU | 備註 |
| --- | --- | --- |
| Linux Server 練指令、跑 Nginx ★★★ | **2** | 絕大多數實驗機這樣就夠 |
| 資料庫（MySQL／PostgreSQL）★★★ | 2～4 | I/O 通常先卡住，不是 CPU |
| 有桌面的 Linux／Windows ★★★ | 2～4 | 桌面本身吃 CPU |
| Windows Server + AD ★★★ | 2～4 | |
| **要在裡面再跑虛擬化（PVE／KVM）** ★★★★★ | **4 以上** | 巢狀環境還要再分給下一層 |
| 編譯、跑大量測試 ★★ | 4～8 | 這時候才真的需要多核 |

> [!tip] 先配 2，不夠再加 ★★★★
> 加 vCPU 很容易（關機 → 改設定 → 開機），一開始配太多卻不容易發現問題。
> 觀察 Guest 裡的 `uptime` 負載平均與 `top` 的 `%wa`（I/O 等待）：
>
> ```bash
> uptime
> ```
> ```text
>  09:41:02 up 2 days,  3:14,  1 user,  load average: 0.12, 0.20, 0.18
> ```
>
> load average 遠低於 vCPU 數，就代表配太多了。

#### ★★★ 超執行緒怎麼算

主機顯示「8 核 16 執行緒」時，**實體核心是 8**。超執行緒的第二條執行緒
只能提供大約三到四成的額外效能，不能當成一整顆核來算。
保守的算法就是**以實體核心數為上限**。

```powershell
# Windows 主機：查實體核心與邏輯處理器
Get-CimInstance Win32_Processor | Select-Object NumberOfCores, NumberOfLogicalProcessors
```

```text
NumberOfCores NumberOfLogicalProcessors
------------- -------------------------
            8                        16
```

```bash
# Linux 主機
lscpu | grep -E '^CPU\(s\)|Core\(s\) per socket|Socket|Thread'
```

```text
CPU(s):                          16
Thread(s) per core:              2
Core(s) per socket:              8
Socket(s):                       1
```

### ★★★★★ 記憶體配置準則

#### 各角色的最低與建議值

| Guest 角色 | 最低 | 建議 | 說明 |
| --- | --- | --- | --- |
| Ubuntu Server（無桌面）★★★★ | 1 GB | **2 GB** | 練指令、跑 Nginx 綽綽有餘 |
| Ubuntu Server + MySQL ★★★ | 2 GB | **4 GB** | 資料庫吃快取 |
| Ubuntu Desktop ★★★ | 2 GB | **4 GB** | GNOME 本身就吃 1.5 GB |
| Windows Server 2022（Core）★★★ | 2 GB | **4 GB** | |
| Windows Server 2022（Desktop Experience）★★★★ | 4 GB | **6～8 GB** | 開了 AD／DNS 還要再加 |
| Windows 11 ★★★ | 4 GB | **8 GB** | |
| **Proxmox VE（巢狀）** ★★★★★ | 4 GB | **8 GB 以上** | 它自己還要開下一層 VM |
| Ollama 跑小模型 ★★★ | 8 GB | **16 GB** | 見 110 群組相關章節 |

#### ★★★★★ 主機保留量

```text
可分配給 VM 的總記憶體 ≈ 主機實體記憶體 − 主機保留量

主機保留量：
  Windows 11 桌面 + 瀏覽器 + 防毒 →  6 GB
  Linux 桌面                     →  4 GB
  Linux 純文字介面                →  2 GB
```

| 主機 RAM | 保留給主機 | 可分配總量 | 實際能開什麼 |
| --- | --- | --- | --- |
| 8 GB ★★ | 6 GB | **約 2 GB** | 一台 Ubuntu Server，且不要同時開瀏覽器 |
| 16 GB ★★★ | 6 GB | **約 10 GB** | 兩台 Server（2+4）＋一台備用 |
| 32 GB ★★★★ | 6 GB | **約 26 GB** | 巢狀 PVE（8 GB）＋三台 Server，很舒服 |
| 64 GB | 8 GB | 約 56 GB | 完整重現機關環境 |

#### Workstation 的記憶體策略設定 ★★★

`Edit → Preferences → Memory`（以 Workstation 17 為例）三選一：

| 選項 | 行為 | 適用 |
| --- | --- | --- |
| **Fit all virtual machine memory into reserved host RAM** ★★★★ | VM 記憶體全部放實體 RAM，不換出 | **效能最好，建議選這個**；但開太多台會開不起來 |
| Allow some virtual machine memory to be swapped ★★★ | 允許部分換出 | 折衷（多數版本的預設） |
| Allow most virtual machine memory to be swapped ★★ | 大量允許換出 | 記憶體嚴重不足時的救急，**效能很差** |

> [!warning] ★★★★ 選了「Fit all」之後 VM 開不起來，是正常的
> 你會看到：
> ```text
> Not enough physical memory is available to power on this virtual machine
> with its configured settings.
> ```
> 這代表**你配太多了**，正確反應是調降 VM 記憶體或關掉其他 VM，
> **不是**把設定改成「Allow most … swapped」硬開。後者只會讓整台機器一起爛。

#### ★★★ 記憶體氣球（Balloon）

Guest 裡的 `vmw_balloon` 驅動（VMware Tools 的一部分）讓 Host 可以在記憶體吃緊時
「向 Guest 借回」閒置頁面。

```bash
# Guest 裡查目前被借走多少
vmware-toolbox-cmd stat balloon
```

```text
0 MB
```

沒裝 Tools 就沒有這個機制。這是「一定要裝 Tools」的理由之一，
見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]]。

### ★★★★★ 虛擬磁碟：放哪裡比什麼型式都重要

#### SSD 與傳統硬碟的差距

這是**單一投資報酬率最高的調校**，沒有之一。

| 操作 | NVMe SSD | SATA SSD | 傳統硬碟 7200rpm |
| --- | --- | --- | --- |
| Ubuntu Server 開機到登入提示 ★★★★ | 數秒 | 十幾秒 | **一分鐘以上** |
| `apt update && apt upgrade` ★★★★ | 順暢 | 順暢 | **慢到懷疑人生** |
| 建立快照 ★★★★ | 幾秒 | 十幾秒 | 數分鐘 |
| 還原快照 ★★★★★ | 幾秒 | 十幾秒 | **數分鐘到十幾分鐘** |
| 同時開三台 VM ★★★★★ | 可行 | 尚可 | **磁頭來回尋道，全部卡死** |

> [!danger] ★★★★★ 虛擬磁碟放傳統硬碟＝這本手冊做不下去
> 本手冊的教學方式高度依賴快照（改壞就還原）。在傳統硬碟上，
> 「還原快照」這個動作要等好幾分鐘，實驗節奏整個斷掉。
> **如果只能升級一個東西，升級成 SSD。**

> [!tip] Workstation 程式與 VM 檔案可以分開放 ★★★★
> 程式裝在系統碟（C:），**VM 檔案放另一顆 SSD**（例如 `D:\VMs\`），
> 這是很常見且推薦的配置。設定位置：
> `Edit → Preferences → Workspace → Default location for virtual machines`。

#### 磁碟型式：三個選項的取捨

建立虛擬磁碟時 Workstation 會問兩個問題：

**問題一：要不要立刻配置全部空間？**

| 選項 | 別名 | 行為 | 取捨 |
| --- | --- | --- | --- |
| **不勾** `Allocate all disk space now` ★★★★ | Thin／動態成長 | `.vmdk` 從很小開始，用多少長多少 | **省空間，建議用**；寫入時要擴檔，有一點點額外開銷 |
| 勾選 ★★★ | Thick／預先配置 | 建立時就佔滿整個容量 | 效能略好、不會因主機碟滿而爆掉；但很占空間，建立要等 |

**問題二：要不要切成多個檔案？**

| 選項 | 行為 | 取捨 |
| --- | --- | --- |
| `Split virtual disk into multiple files` ★★★ | 切成一堆 2 GB 的 `-s001.vmdk`、`-s002.vmdk` | 可放進 FAT32／exFAT、備份時方便分批；檔案數量多 |
| `Store virtual disk as a single file` ★★★ | 單一大檔 | 管理單純、效能略好；需要檔案系統支援大檔（NTFS／ext4 沒問題） |

**本手冊的建議 ★★★★**：放在 NTFS 或 ext4 的 SSD 上 → **不預先配置 ＋ 單一檔案**。

#### ★★★★ 磁碟控制器型式

`VM → Settings → Hard Disk → Advanced`（新增磁碟時也會問）：

| 控制器 | 效能 | 相容性 | 建議 |
| --- | --- | --- | --- |
| **NVMe** ★★★★ | 最好 | 需要較新的 Guest OS 與驅動 | 現代 Linux／Windows 10 以後，**建議用這個** |
| **SCSI（含 Paravirtual）** ★★★★ | 好 | 需要 Tools 提供的 `vmw_pvscsi` | 通用選擇，Server 類 Guest 的預設 |
| SATA ★★ | 普通 | 最好 | 老系統或有相容性問題時 |
| IDE ★ | 差 | 最好 | 只有很古老的系統才需要 |

> [!warning] ★★★★ 不要在裝好系統之後亂換控制器
> Guest 的開機流程需要對應的驅動才找得到系統碟。裝好之後把 SCSI 換成 NVMe，
> 開機會直接停在：
> ```text
> Operating System not found
> ```
> 要換的話得先在 Guest 裡把新驅動載進 initramfs，成本遠高於重建一台。

### ★★★ 關掉不需要的虛擬裝置

每個虛擬裝置都要 Hypervisor 花力氣模擬。實驗用的 Server VM 上，
下面這些幾乎都可以直接移除：

| 裝置 | 能不能拔 | 拔掉的好處 |
| --- | --- | --- |
| **軟碟機（Floppy）** ★★★★ | **一定要拔** | 現代系統完全用不到，還可能拖慢開機偵測 |
| 音效卡（Sound Card）★★★★ | Server 拔掉 | 少一個模擬裝置與一次中斷來源 |
| 印表機（Printer）★★★★ | 拔掉 | Workstation 的印表機重導功能，Server 用不到 |
| 攝影機／USB 控制器 ★★★ | Server 拔掉 | 少一個 USB 仲裁的來源；也減少資安暴露面 |
| 序列埠／並列埠 ★★★ | 沒用到就拔 | |
| **光碟機（CD/DVD）** ★★★★ | **不要拔，改成「不連線」** | 之後還要掛 ISO；但**開機時不要自動連線**，避免從光碟開機 |
| 顯示卡 3D 加速 ★★★ | Server 關掉 | `Display → Accelerate 3D graphics` 取消勾選，省 Host GPU 資源 |
| 網路卡 ★ | 保留 | 但用不到的第二張網卡要移除 |

> [!tip] ★★★ 一次做好，範本機受惠
> 這些調整應該在**建立範本機（Template）時就做好**，之後複製出去的每一台都受惠。
> 見 [[050-01-02-03-guide-Workstation-快照與複製]]。

---

## 安裝或基礎操作

### ★★★★ 調整 CPU 與記憶體

**VM 必須完全關機**（不是 Suspend）才能改。

1. 選中 VM → `VM → Settings`（或 `Ctrl+D`）
2. `Hardware` 分頁 → `Memory`：拖曳滑桿或直接輸入數值
   - 畫面上會有三個彩色標記：`Guest OS 建議`、`建議記憶體`、`最大建議值` ★★★
   - **不要超過「最大建議值」那條線**，超過就是在跟主機搶
3. `Hardware` 分頁 → `Processors`：設定 `Number of processors` 與
   `Number of cores per processor`
4. `OK` 後開機

Guest 裡驗證：

```bash
nproc
free -h
```

```text
2
               total        used        free      shared  buff/cache   available
Mem:           3.8Gi       412Mi       2.9Gi       1.0Mi       541Mi       3.2Gi
Swap:          3.8Gi          0B       3.8Gi
```

```powershell
# Windows Guest
Get-CimInstance Win32_ComputerSystem | Select-Object NumberOfLogicalProcessors, TotalPhysicalMemory
```

### ★★★ 移除不需要的裝置

`VM → Settings → Hardware` 分頁，選中裝置後按下方的 `Remove`：

```text
Floppy          → Remove
Sound Card      → Remove
Printer         → Remove
USB Controller  → Remove（Server 用；要接隨身碟時再加回來）
```

光碟機保留但取消自動連線：選中 `CD/DVD (SATA)` →
右側 `Device status` 的 `Connect at power on` **取消勾選** ★★★

3D 加速：`Display` → 取消勾選 `Accelerate 3D graphics` ★★★

### ★★★ 主機端的設定

#### 把 VM 目錄排除在防毒即時掃描之外 ★★★★★

這是**效果最明顯但最常被忽略**的一項。防毒軟體會即時掃描 `.vmdk` 的每一次寫入，
而 VM 一開機就是持續的大量寫入。

```powershell
# Windows Defender：把 VM 目錄加入排除清單（系統管理員 PowerShell）
Add-MpPreference -ExclusionPath 'D:\VMs'
Add-MpPreference -ExclusionProcess 'vmware-vmx.exe'
Get-MpPreference | Select-Object -ExpandProperty ExclusionPath
```

```text
D:\VMs
```

> [!warning] ★★★★ 排除掃描是有代價的
> 排除之後，VM 檔案不再受即時防護。這在**專用實驗主機**上是合理取捨，
> 但在日常辦公機上要先評估。折衷做法：只排除 `vmware-vmx.exe` 這個程序，
> 不排除整個目錄。機關環境請先與資安單位確認。

#### 記憶體策略

`Edit → Preferences → Memory` → 選 **`Fit all virtual machine memory into reserved host RAM`** ★★★★

#### 電源計畫（筆電特別重要）★★★

```powershell
# 查目前電源計畫
powercfg /getactivescheme
```

```text
電源結構 GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (高效能)
```

筆電在「省電」模式下 CPU 會降頻，VM 會慢得莫名其妙。跑 VM 時切到高效能，
而且**插著電源**。

---

## 進階應用

### ★★★★★ 巢狀虛擬化（Nested Virtualization）

**這一節是本篇最重要的部分。** 本手冊後面的 Proxmox VE 章節與 KVM 章節，
都要在 Workstation 的虛擬機裡**再跑一層虛擬化**——沒有這個功能，那幾章做不下去。

#### 什麼是巢狀虛擬化

```text
  ┌─ 實體主機（Windows / Linux）─────────────────────────┐
  │  CPU 支援 VT-x / AMD-V                                │
  │                                                       │
  │  ┌─ VMware Workstation ────────────────────────────┐  │
  │  │                                                 │  │
  │  │  ┌─ VM：Proxmox VE ───────────────────────────┐ │  │
  │  │  │  需要 /dev/kvm ← ★ VT-x 必須「透傳」進來  │ │  │
  │  │  │                                            │ │  │
  │  │  │   ┌─ 再一層 VM：Ubuntu ─┐                  │ │  │
  │  │  │   └─────────────────────┘                  │ │  │
  │  │  └────────────────────────────────────────────┘ │  │
  │  └─────────────────────────────────────────────────┘  │
  └───────────────────────────────────────────────────────┘
```

第二層的 Hypervisor（PVE 的 KVM）需要用到 CPU 的硬體虛擬化指令。
預設情況下 Workstation **不會**把這些指令暴露給 Guest，
所以 PVE 裝起來之後開 VM 會報「KVM 不可用」。

**解法就是勾一個選項，把 VT-x／AMD-V 透傳給 Guest。**

#### ★★★★★ 先確認三個前提

**前提一：Host CPU 必須支援 EPT（Intel）或 RVI／NPT（AMD）**

只有 VT-x 是不夠的，**巢狀虛擬化需要第二層位址轉譯**。
2010 年之後的 Intel Core i 系列與 AMD 處理器基本上都有。

```bash
# Linux Host
grep -o -m1 -E 'ept|npt' /proc/cpuinfo
```

```text
ept
```

```powershell
# Windows Host：先確認虛擬化本身是啟用的
Get-ComputerInfo -Property "HyperVRequirementVirtualizationFirmwareEnabled"
```

```text
HyperVRequirementVirtualizationFirmwareEnabled
---------------------------------------------
                                         True
```

**前提二：★★★★★ Host 上不能有其他 Hypervisor 佔用**

這是最常見的失敗原因。**Windows 上只要 Hyper-V／WSL2／記憶體完整性
（VBS）任何一個開著，巢狀虛擬化就不可用**（就算 Workstation 能以共存模式開 VM，
巢狀也通常不能用）。

```powershell
Get-ComputerInfo -Property "HyperVisorPresent"
```

```text
HyperVisorPresent
-----------------
            False
```

**必須是 `False`。** 是 `True` 的話回去看
[[050-01-02-01-svc-Workstation-安裝與授權]] 的〈與 Hyper-V／WSL2 共存〉一節，
把 Hyper-V 層關掉並重開機。

**前提三：VM 的虛擬硬體版本要夠新 ★★★**

從很舊的 VM 沿用過來的話，`Processors` 頁上可能根本沒有那個勾選框。
用 `VM → Manage → Change Hardware Compatibility…` 升級。

> [!danger] ★★★★★ 虛擬硬體版本升級是不可逆的
> 升級之後，**舊版 Workstation 就打不開這台 VM 了**。
> 要和使用舊版的同事交換 VM 時要特別注意。升級前先做快照或完整複製。

#### 開啟步驟

1. **VM 完全關機**（Suspend 狀態不行）★★★★
2. `VM → Settings → Hardware → Processors`
3. 在 `Virtualization engine` 區塊勾選：

| 選項 | 作用 | 何時要勾 |
| --- | --- | --- |
| **`Virtualize Intel VT-x/EPT or AMD-V/RVI`** ★★★★★ | **把硬體虛擬化透傳給 Guest** | **跑 PVE／KVM／ESXi／Hyper-V／Android 模擬器時必勾** |
| `Virtualize CPU performance counters` ★★★ | 透傳效能計數器 | Guest 內要跑 `perf`／效能分析工具時 |
| `Virtualize IOMMU (IO memory management unit)` ★★★ | 透傳 IOMMU | Guest 內要做**裝置直通**（PCI passthrough）時 |

4. 建議同時把 `Number of processors` 設成 1、`cores per processor` 設成 **4 以上** ★★★★
   （巢狀環境要再分給下一層）
5. `OK` → 開機

#### 直接改 `.vmx`（VM 必須關機）★★★★

GUI 的勾選最後就是寫成這幾行，用腳本批次處理時直接改檔比較快：

```ini
vhv.enable = "TRUE"
vpmc.enable = "TRUE"
vvtd.enable = "TRUE"
```

| 參數 | 對應的勾選 |
| --- | --- |
| `vhv.enable` ★★★★★ | Virtualize Intel VT-x/EPT or AMD-V/RVI |
| `vpmc.enable` ★★★ | Virtualize CPU performance counters |
| `vvtd.enable` ★★★ | Virtualize IOMMU |

> [!warning] ★★★★ 改 `.vmx` 一定要在 VM 完全關機時
> VM 執行中或 Suspend 狀態時，Workstation 持有這個檔案，
> 你的修改會在 VM 關機時被覆蓋掉。

#### ★★★★★ 在 Guest 裡驗證 VT-x 真的透傳進來了

**這是最關鍵的一步。不驗證就往下做 PVE，會在很後面才發現白忙一場。**

**檢查一：CPU 旗標**

```bash
grep -c -E 'vmx|svm' /proc/cpuinfo
```

```text
4
```

**回傳數字等於 vCPU 數就成功了**；回傳 `0` 代表沒透傳進來。★★★★★

看是哪一種：

```bash
grep -o -m1 -E 'vmx|svm' /proc/cpuinfo
```

```text
vmx
```

**檢查二：`lscpu`**

```bash
lscpu | grep -i -E 'virtual|hypervisor'
```

```text
Virtualization:                  VT-x
Hypervisor vendor:               VMware
Virtualization type:             full
```

**`Virtualization: VT-x` 這一行有出現，就代表透傳成功。** ★★★★★
（`Hypervisor vendor: VMware` 只是說明自己在 VMware 裡，兩件事不一樣。）

**檢查三：`kvm-ok`（Ubuntu／Debian，最直接）** ★★★★★

```bash
sudo apt install -y cpu-checker
sudo kvm-ok
```

成功：

```text
INFO: /dev/kvm exists
KVM acceleration can be used
```

失敗：

```text
INFO: Your CPU does not support KVM extensions
KVM acceleration can NOT be used
```

**檢查四：`/dev/kvm` 裝置節點**

```bash
ls -l /dev/kvm
```

```text
crw-rw---- 1 root kvm 10, 232 Sep  2 09:50 /dev/kvm
```

```bash
lsmod | grep kvm
```

```text
kvm_intel             372736  0
kvm                  1146880  1 kvm_intel
irqbypass              12288  1 kvm
```

看到 `kvm_intel`（或 AMD 的 `kvm_amd`）已載入，就是完全成功。★★★★★

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> RHEL 系沒有 `kvm-ok`，用等效檢查：
>
> ```bash
> grep -c -E 'vmx|svm' /proc/cpuinfo
> lsmod | grep kvm
> ls -l /dev/kvm
> sudo dnf install -y qemu-kvm libvirt
> sudo systemctl enable --now libvirtd
> virt-host-validate
> ```
>
> `virt-host-validate` 會逐項檢查並給出 `PASS` / `WARN` / `FAIL`：
>
> ```text
>   QEMU: Checking for hardware virtualization                    : PASS
>   QEMU: Checking if device /dev/kvm exists                      : PASS
>   QEMU: Checking if device /dev/kvm is accessible               : PASS
> ```
>
> 第一項 `FAIL` 就是巢狀虛擬化沒開成功。★★★★★

**Proxmox VE Guest 上的驗證** ★★★★★：

裝好 PVE 後，在它的 shell 裡：

```bash
grep -c -E 'vmx|svm' /proc/cpuinfo
lsmod | grep kvm
pveversion
```

Web 介面上建立 VM 時，如果 `KVM hardware virtualization` 是灰色的或建立後開不了機，
就是巢狀沒開成功。詳見 [[050-01-03-01-svc-PVE-安裝與初始設定]]。

#### 巢狀虛擬化的常見錯誤訊息

| 訊息（原文） | 意義 |
| --- | --- |
| `Virtualized Intel VT-x/EPT is not supported on this platform.` ★★★★★ | Host CPU 不支援 EPT，或 Host 上有其他 Hypervisor 佔用 |
| `This host does not support "Intel EPT" hardware assisted MMU virtualization.` ★★★★ | Host CPU 缺 EPT |
| `Binary translation is incompatible with long mode on this platform.` ★★★★ | VT-x 完全沒有（BIOS 沒開或被佔用） |
| `VMware Workstation and Hyper-V are not compatible.` ★★★★★ | Hyper-V 層還開著 |
| Guest 內 `KVM acceleration can NOT be used` ★★★★★ | 勾選沒生效，或改 `.vmx` 時 VM 沒關機 |

> [!warning] ★★★★ 巢狀環境的效能一定比較差
> 第二層 VM 的每一次特權操作都要多穿過一層 Hypervisor。
> 巢狀跑出來的 PVE 適合**學介面、練流程、驗證設定**，
> **不要拿巢狀環境的效能數據去推論實體環境**。

---

### ★★★★ 磁碟膨脹與壓縮

#### 為什麼 `.vmdk` 只長不縮

動態成長的虛擬磁碟，在 Guest 寫入時擴大；但 Guest **刪除**檔案時，
只是把檔案系統的區塊標記成可用，**`.vmdk` 完全不知道**，所以檔案大小不會變。

```text
Guest 裡：df 顯示用了 8 GB
Host 上：.vmdk 已經 45 GB
         ↑ 這 37 GB 是「曾經寫過但已經刪掉」的空間
```

#### ★★★★★ 正確的壓縮流程：先歸零，再壓縮

**只做 Host 端的 Compact 是沒用的**，因為 Host 分不出哪些區塊是垃圾。
必須先在 Guest 裡把可用空間**寫成 0**，Host 才認得出來。

**步驟 1（Guest 端，Linux）：清乾淨 + 歸零**

```bash
# 先清掉不需要的東西
sudo apt clean
sudo journalctl --vacuum-time=1d
```

方法 A：用 Tools 的內建功能（最省事）★★★★

```bash
sudo vmware-toolbox-cmd disk shrink /
```

```text
Please disregard any warnings about disk space for the duration of shrink process.
Progress: 100 [=======================>]
Disk shrinking complete.
```

方法 B：手動歸零（沒有 Tools 或 Tools 的功能不可用時）★★★★

```bash
sudo dd if=/dev/zero of=/zero.fill bs=1M status=progress
sudo sync
sudo rm -f /zero.fill
```

```text
dd: error writing '/zero.fill': No space left on device
41231+0 records in
41230+0 records out
43232788480 bytes (43 GB, 40 GiB) copied, 96.3 s, 449 MB/s
```

> [!danger] ★★★★★ `dd` 會把磁碟塞爆，這是預期行為
> 它一定會以 `No space left on device` 結束——**這就是目的**。
> 但過程中磁碟是滿的，**正在跑的服務可能因為寫不進去而出錯或損毀資料**。
> 執行前務必：①先做快照；②停掉資料庫等會寫入的服務；
> ③**絕對不要在正式機上做**。
>
> 也要注意這個動作會讓 Host 上的 `.vmdk` **先暴增到滿容量**，
> 主機碟空間不夠的話會直接失敗。

方法 C（Windows Guest）★★★

Windows Guest 上 VMware Tools 的介面裡有「Shrink」分頁，或使用微軟 Sysinternals 的
`sdelete`：

```powershell
sdelete64.exe -z C:
```

**步驟 2（Host 端）：壓縮**

**VM 必須完全關機，而且沒有任何快照。** ★★★★★

GUI 做法：`VM → Manage → Clean Up Disks…`（Workstation 17）
或 `VM → Settings → Hard Disk → Utilities → Compact`

命令列做法（`vmware-vdiskmanager` 隨 Workstation 附帶）：

```powershell
& 'C:\Program Files\VMware\VMware Workstation\vmware-vdiskmanager.exe' -k "D:\VMs\ubuntu\ubuntu.vmdk"
```

```text
  Shrink: 100% done.
Shrink completed successfully.
```

```bash
# Linux Host
vmware-vdiskmanager -k /home/user/vmware/ubuntu/ubuntu.vmdk
```

驗證：

```powershell
Get-Item 'D:\VMs\ubuntu\ubuntu*.vmdk' | Measure-Object -Property Length -Sum
```

> [!danger] ★★★★★ 有快照就不能壓縮
> 快照鏈裡的 delta 檔案讓壓縮無法安全進行。Workstation 會拒絕，或選單是灰色的。
> **要壓縮就得先刪除所有快照**（`Snapshot Manager → Delete All`），
> 這個動作**不可逆**，做之前想清楚。

#### ★★★ 碎片整理（Defragment）

```powershell
& 'C:\Program Files\VMware\VMware Workstation\vmware-vdiskmanager.exe' -d "D:\VMs\ubuntu\ubuntu.vmdk"
```

或 `VM → Settings → Hard Disk → Utilities → Defragment`。

> [!tip] SSD 上不需要做碎片整理 ★★★★
> `-d` 的用意是把 `.vmdk` 內部散落的區塊整理到一起，減少實體磁頭尋道。
> **SSD 沒有磁頭，沒有尋道成本**，做這個只是白白製造大量寫入、消耗壽命。
> **SSD 上只做壓縮（`-k`），不做碎片整理（`-d`）。**

#### `vmware-vdiskmanager` 常用選項

| 選項 | 作用 | 注意 |
| --- | --- | --- |
| `-k <vmdk>` ★★★★★ | 壓縮（shrink） | 需先在 Guest 歸零；不能有快照 |
| `-d <vmdk>` ★★★ | 碎片整理 | **SSD 不要做** |
| `-x <大小> <vmdk>` ★★★★ | 擴大磁碟 | **只擴大 `.vmdk`，Guest 裡還要自己擴分割區與檔案系統** |
| `-r <來源> -t <型別> <目標>` ★★★ | 轉換型式（thin↔thick、split↔single） | 需要足夠空間放目標檔 |
| `-R <vmdk>` ★★★ | 檢查並修復磁碟鏈一致性 | 遇到 `Cannot open the disk` 時可試 |
| `-c -s <大小> -a <介面> -t <型別> <vmdk>` ★★ | 建立新的虛擬磁碟 | 手動建磁碟時用 |

> [!warning] ★★★★★ `-x` 擴大之後 Guest 不會自動變大
> 擴大 `.vmdk` 只是把「盤子」變大，Guest 裡的分割表與檔案系統完全不知情。
> 還要在 Guest 裡做：
> ```bash
> sudo growpart /dev/sda 3          # 擴大分割區
> sudo pvresize /dev/sda3           # LVM：擴大 PV
> sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
> sudo resize2fs /dev/ubuntu-vg/ubuntu-lv   # ext4
> # 或 xfs_growfs /                          # xfs
> df -h /
> ```
> **做這些之前一定要先關機做完整複製或快照。**

### ★★★★★ 快照鏈：不是越多越好

#### 快照鏈怎麼拖慢一切

每做一個快照，Workstation 就凍結目前的 `.vmdk`，新建一個 delta 檔案接續寫入。

```text
base.vmdk  ←  000001.vmdk  ←  000002.vmdk  ←  000003.vmdk（目前在寫）
   唯讀          唯讀            唯讀             可寫
```

讀取一個區塊時，要**從最新的 delta 往回找**，直到找到為止。
鏈越長，每次讀取要走的層數越多。

| 快照層數 | 影響 |
| --- | --- |
| 1～2 層 ★★ | 幾乎感覺不到 |
| 3～5 層 ★★★ | 開始有感，磁碟 I/O 變慢 |
| 6～10 層 ★★★★ | 明顯拖慢，空間快速膨脹 |
| 10 層以上 ★★★★★ | **嚴重拖慢；刪除快照時要合併大量資料，可能跑好幾小時且中途不能斷電** |

#### 準則 ★★★★★

| 準則 | 理由 |
| --- | --- |
| 快照鏈**不超過 3 層** | 超過就開始明顯拖慢 |
| 快照**不要留超過一週** | 留越久，delta 越大，刪除時合併越久 |
| 快照**不是備份** | 它和 base 磁碟放在一起，Host 硬碟壞了兩個一起沒 |
| 「乾淨基準」用**完整複製**而不是快照 | 複製是獨立的檔案，不會拖慢原機 |
| 刪快照前**先確認主機碟有足夠空間** | 合併過程需要額外空間 |
| **不要在 VM 執行中刪除大型快照** | 合併期間效能極差，且風險較高 |

完整的快照策略見 [[050-01-02-03-guide-Workstation-快照與複製]]。

### ★★★ 其他調校項目

| 項目 | 位置／做法 | 效果 |
| --- | --- | --- |
| 關閉 Guest 內的圖形介面 ★★★★ | `sudo systemctl set-default multi-user.target` | Server VM 省下 1 GB 以上記憶體 |
| Guest 內移除不用的服務 ★★★ | `systemctl disable snapd bluetooth` 等 | 減少開機時間與背景 I/O |
| Guest 用 `noatime` 掛載 ★★★ | `/etc/fstab` 加 `noatime` | 減少讀取時的寫入 |
| Host 端關閉 Workstation 的自動更新檢查 ★★ | `Edit → Preferences → Updates` | 減少啟動延遲 |
| Host 端關閉共用 VM／VMware Server 功能 ★★ | `Edit → Preferences → Shared VMs` | 少一個背景服務 |
| 用連結複製（Linked Clone）省空間 ★★★ | `VM → Manage → Clone` | 多台同基底的 VM 只佔一份空間，但**效能較差且互相依賴** |

> [!danger] ★★★★★ 側通道緩解（Side Channel Mitigations）不要隨便關
> Workstation 的 `Processors` 頁上有一個
> `Disable side channel mitigations for Hyper-V enabled hosts`（版本不同名稱略有差異）。
> 關掉它確實能明顯提升效能，因為省下 Spectre／Meltdown 這類漏洞的緩解成本。
>
> **但這等於關掉針對推測執行漏洞的防護**，在共用主機或跑不信任的 Guest 時
> 可能讓資料被跨 VM 竊取。
> **機關環境不要動它**，除非是完全隔離、只跑自己東西的專用實驗機，
> 而且要有書面的例外紀錄。

---

## 完整實戰範例

**情境**：整備一台「巢狀 Proxmox VE 實驗機」——這是本手冊 PVE 章節的前置作業。
主機是 32 GB / 8 核 / NVMe SSD 的 Windows 11。

### 步驟 1：確認 Host 端沒有其他 Hypervisor

```powershell
Get-ComputerInfo -Property "HyperVisorPresent","HyperVRequirementVirtualizationFirmwareEnabled"
```

```text
HyperVisorPresent HyperVRequirementVirtualizationFirmwareEnabled
----------------- ---------------------------------------------
            False                                          True
```

**必須是 `False` ＋ `True`。** ★★★★★
`HyperVisorPresent` 是 `True` 就先回
[[050-01-02-01-svc-Workstation-安裝與授權]] 關掉 Hyper-V 層。

### 步驟 2：確認 Host CPU 支援 EPT／RVI

```powershell
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
```

```text
Name                                       NumberOfCores NumberOfLogicalProcessors
----                                       ------------- -------------------------
12th Gen Intel(R) Core(TM) i7-12700                   12                        20
```

2010 年後的 Intel Core i 系列都有 EPT。真的要確認可以查原廠規格頁的
「Intel VT-x with Extended Page Tables (EPT)」欄位。

### 步驟 3：確認主機碟空間

```powershell
Get-PSDrive D | Select-Object Used, Free
```

```text
        Used         Free
        ----         ----
231000000000  247000000000
```

PVE 巢狀環境建議至少留 **150 GB**（PVE 自己 + 它裡面的 VM + 快照）。★★★★

### 步驟 4：建立 VM 並配置資源

以 `新增虛擬機器精靈` 建立（詳見
[[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]]），
Guest OS 選 `Linux → Debian 12.x 64-bit`（PVE 基於 Debian）。

建好後 `VM → Settings`，依下表調整：

| 項目 | 設定值 | 理由 |
| --- | --- | --- |
| Memory ★★★★★ | **8192 MB** | PVE 本身約 2 GB，留 6 GB 給它開下一層 |
| Processors ★★★★★ | 1 processor × **4 cores** | 巢狀要再分下去 |
| Hard Disk ★★★★ | **120 GB**，不預先配置，單一檔案，NVMe 控制器 | 動態成長省空間 |
| Network Adapter ★★★ | NAT | PVE 需要對外抓套件；見 [[050-01-02-04-guide-Workstation-網路模式]] |
| Floppy ★★★★ | **Remove** | 用不到 |
| Sound Card ★★★★ | **Remove** | Server 用不到 |
| Printer ★★★★ | **Remove** | 用不到 |
| USB Controller ★★★ | **Remove** | Server 用不到 |
| Display → Accelerate 3D ★★★ | 取消勾選 | 省 Host GPU |

### 步驟 5：★★★★★ 開啟巢狀虛擬化

`VM → Settings → Hardware → Processors`：

```text
Number of processors:          1
Number of cores per processor: 4
Total processor cores:         4

Virtualization engine:
  [✓] Virtualize Intel VT-x/EPT or AMD-V/RVI      ← ★★★★★ 必勾
  [✓] Virtualize CPU performance counters         ← 建議勾
  [ ] Virtualize IOMMU (IO memory management unit) ← 要做裝置直通才勾
```

按 `OK`。

驗證設定真的寫進去了（VM 關機狀態）：

```powershell
Select-String -Path 'D:\VMs\pve\pve.vmx' -Pattern 'vhv|vpmc|vvtd'
```

```text
D:\VMs\pve\pve.vmx:42:vhv.enable = "TRUE"
D:\VMs\pve\pve.vmx:43:vpmc.enable = "TRUE"
```

### 步驟 6：Host 端排除防毒掃描

```powershell
Add-MpPreference -ExclusionPath 'D:\VMs'
Add-MpPreference -ExclusionProcess 'vmware-vmx.exe'
```

### 步驟 7：先裝一台 Ubuntu 驗證巢狀有沒有生效

**不要直接裝 PVE。** 先用同樣設定裝一台 Ubuntu Server（或用 Live CD 開機），
在裡面驗證 VT-x 透傳成功，再去裝 PVE——否則 PVE 裝完才發現不行，
等於白花一小時。★★★★★

在 Ubuntu Guest 裡：

```bash
grep -c -E 'vmx|svm' /proc/cpuinfo
```

```text
4
```

```bash
lscpu | grep -i -E 'virtualization|hypervisor vendor'
```

```text
Virtualization:                  VT-x
Hypervisor vendor:               VMware
```

```bash
sudo apt update && sudo apt install -y cpu-checker
sudo kvm-ok
```

```text
INFO: /dev/kvm exists
KVM acceleration can be used
```

```bash
ls -l /dev/kvm
lsmod | grep kvm
```

```text
crw-rw---- 1 root kvm 10, 232 Sep  2 10:02 /dev/kvm
kvm_intel             372736  0
kvm                  1146880  1 kvm_intel
irqbypass              12288  1 kvm
```

**四項全過，巢狀虛擬化確認可用。** ★★★★★

如果 `kvm-ok` 顯示 `KVM acceleration can NOT be used`：

| 檢查順序 | 動作 |
| --- | --- |
| 1 ★★★★★ | Host 上 `HyperVisorPresent` 是不是 `True`？是就先關 Hyper-V 層並重開機 |
| 2 ★★★★★ | `Processors` 頁的勾選有沒有真的存進去？`.vmx` 裡有沒有 `vhv.enable = "TRUE"` |
| 3 ★★★★ | 改 `.vmx` 時 VM 是不是 Suspend 而不是完全關機？ |
| 4 ★★★★ | 虛擬硬體版本太舊？`VM → Manage → Change Hardware Compatibility` |
| 5 ★★★ | Host CPU 真的有 EPT／RVI 嗎？查原廠規格 |

### 步驟 8：安裝 Proxmox VE 並在裡面驗證

裝好 PVE 後（步驟見 [[050-01-03-01-svc-PVE-安裝與初始設定]]），
在 PVE 的 shell 裡再驗證一次：

```bash
grep -c -E 'vmx|svm' /proc/cpuinfo
lsmod | grep kvm
pveversion
```

```text
4
kvm_intel             372736  0
kvm                  1146880  1 kvm_intel
irqbypass              12288  1 kvm
pve-manager/8.x.x/xxxxxxxx (running kernel: 6.x.x-x-pve)
```

### 步驟 9：做基準快照

```text
VM → Snapshot → Take Snapshot…
名稱：pve-clean-nested-ok
描述：PVE 安裝完成、巢狀虛擬化已驗證、尚未建立任何 VM
```

### 步驟 10：觀察 Host 端負載

開著 PVE 的情況下，在 Host 上：

```powershell
Get-Counter '\Processor(_Total)\% Processor Time','\Memory\Available MBytes' -SampleInterval 2 -MaxSamples 3
```

```text
Timestamp                 CounterSamples
---------                 --------------
2026/9/2 上午 10:05:12    \\HOST\processor(_total)\% processor time : 18.4
                          \\HOST\memory\available mbytes : 19204
```

`Available MBytes` **要維持在 4000 以上**（約 4 GB）。★★★★★
低於這個數字就代表配太多，要調降 VM 記憶體。

### 驗收檢核表

| # | 檢查項 | 通過條件 |
| --- | --- | --- |
| 1 ★★★★★ | Host 無其他 Hypervisor | `HyperVisorPresent` = `False` |
| 2 ★★★★★ | `.vmx` 有巢狀參數 | 含 `vhv.enable = "TRUE"` |
| 3 ★★★★★ | Guest CPU 有 vmx/svm | `grep -c -E 'vmx\|svm' /proc/cpuinfo` = vCPU 數 |
| 4 ★★★★★ | `lscpu` 顯示 VT-x | 有 `Virtualization: VT-x` |
| 5 ★★★★★ | KVM 可用 | `kvm-ok` 顯示 `KVM acceleration can be used` |
| 6 ★★★★ | `/dev/kvm` 存在 | `ls -l /dev/kvm` 有輸出 |
| 7 ★★★★ | Host 記憶體有餘裕 | Available ≥ 4 GB |
| 8 ★★★ | 不需要的裝置已移除 | Settings 裡沒有 Floppy／Sound／Printer |
| 9 ★★★ | 防毒已排除 VM 目錄 | `Get-MpPreference` 的 ExclusionPath 含 VM 目錄 |
| 10 ★★★ | 已建立基準快照 | Snapshot Manager 看得到 |

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| `This host supports Intel VT-x, but Intel VT-x is disabled.` ★★★★★ | BIOS/UEFI 沒開啟虛擬化，或已被其他 Hypervisor 佔用 | 進 BIOS 開啟 `Intel Virtualization Technology` / `SVM Mode`；已開啟就查 `HyperVisorPresent` |
| `Binary translation is incompatible with long mode on this platform.` ★★★★★ | 完全沒有 VT-x／AMD-V 可用 | 同上；筆電更新 BIOS 後常會被重設回停用 |
| `VMware Workstation and Hyper-V are not compatible.` ★★★★★ | Hyper-V／WSL2／VBS 佔用虛擬化 | `bcdedit /set hypervisorlaunchtype off` ＋ 關閉相關 Windows 功能 ＋ 重開機，詳見 [[050-01-02-01-svc-Workstation-安裝與授權]] |
| `VMware Workstation and Device/Credential Guard are not compatible.` ★★★★★ | VBS／Credential Guard 開著（機關電腦常由 GPO 強制） | 關閉核心隔離的記憶體完整性；受 GPO 管控時**要找資安單位處理，不要自行繞過** |
| `Virtualized Intel VT-x/EPT is not supported on this platform.` ★★★★★ | 巢狀虛擬化不可用：Host 缺 EPT，或仍有其他 Hypervisor | 先確認 `HyperVisorPresent` = `False`；再確認 CPU 支援 EPT／RVI |
| Guest 內 `kvm-ok` 顯示 `KVM acceleration can NOT be used` ★★★★★ | `Virtualize Intel VT-x/EPT` 沒勾，或改 `.vmx` 時 VM 不是完全關機 | 完全關機後勾選；確認 `.vmx` 裡有 `vhv.enable = "TRUE"` |
| `Processors` 頁上根本沒有巢狀虛擬化的勾選框 ★★★★ | 虛擬硬體版本太舊 | `VM → Manage → Change Hardware Compatibility…` 升級（**不可逆，先備份**） |
| `Not enough physical memory is available to power on this virtual machine with its configured settings.` ★★★★★ | 記憶體配太多，或偏好設為「Fit all」而實體 RAM 不足 | 調降 VM 記憶體、關掉其他 VM；**不要**改成「Allow most … swapped」硬開 |
| `There is not enough space on the file system for the selected operation.` ★★★★★ | 主機碟空間不足（快照與 delta 檔案吃掉了） | 清理主機碟；刪除舊快照；把 VM 搬到空間較大的碟；壓縮 `.vmdk` |
| **VM 執行中突然暫停，提示磁碟空間不足** ★★★★★ | 主機碟寫滿，Workstation 為保護資料而暫停 VM | **先清出空間再按 Retry**（按 Abort 可能造成 Guest 檔案系統損壞） |
| `This virtual machine appears to be in use.` `Take Ownership / Cancel` ★★★★★ | 上次非正常結束，`.lck` 鎖目錄殘留 | **確認沒有其他 Workstation 正在開這台 VM**，再按 `Take Ownership`；仍失敗就關掉 Workstation 後手動刪除 VM 目錄下的 `*.lck` 資料夾 |
| `Cannot open the disk 'xxx.vmdk' or one of the snapshot disks it depends on.` ★★★★★ | `.lck` 鎖殘留、快照鏈檔案缺失或被移動過 | 刪 `*.lck`；確認 `-000001.vmdk` 等 delta 檔案都在同一目錄；`vmware-vdiskmanager -R` 檢查鏈 |
| `Failed to lock the file` ★★★★ | 同上，或防毒／備份軟體正鎖著檔案 | 排除防毒掃描；關掉正在跑的備份工作；刪 `.lck` |
| `Operating System not found` / `No bootable device` ★★★★ | 磁碟未連接、開機順序錯、裝好系統後換了控制器型式 | 檢查 `Hard Disk` 的 `Connect at power on`；`BIOS → Boot` 順序；把控制器改回原本的型式 |
| VM 開機一直進到網路開機（PXE）畫面 ★★★ | 找不到可開機磁碟，退回網路開機 | 同上；確認 ISO 是否還掛著、是否誤裝到別顆磁碟 |
| Guest 網路完全不通 ★★★★ | Host 上 VMware 的 NAT／DHCP 服務沒跑，或虛擬網卡被停用 | `Get-Service VMware*` 確認 `VMware NAT Service`、`VMnetDHCP` 為 Running；`Virtual Network Editor → Restore Defaults`；詳見 [[050-01-02-04-guide-Workstation-網路模式]] |
| **效能突然變慢，之前都好好的** ★★★★★ | ①快照鏈變長 ②主機碟快滿 ③防毒開始掃 VM 目錄 ④筆電切到省電模式 ⑤別人也在用同一台主機 | 依序檢查：快照數量、主機碟剩餘空間、防毒排除清單、電源計畫、Host 的工作管理員 |
| Guest 裡 `top` 的 `%wa`（I/O wait）長期偏高 ★★★★ | 磁碟太慢（傳統硬碟）或多台 VM 搶同一顆碟 | 把 `.vmdk` 搬到 SSD；減少同時執行的 VM 數 |
| Guest 裡 load average 遠高於 vCPU 數 ★★★★ | vCPU 配太少，或 Host CPU 被超配 | 加 vCPU；或減少同時執行的 VM 使 vCPU 總和不超過實體核心數 |
| **配了 8 vCPU 反而比 2 vCPU 慢** ★★★★★ | vCPU 超配導致 co-scheduling 等待（CPU ready time 高） | 降回 2～4 vCPU；讓所有執行中 VM 的 vCPU 總和 ≤ 實體核心數 |
| `.vmdk` 越來越大，Guest 裡 `df` 卻沒用那麼多 ★★★★ | 動態磁碟只長不縮 | Guest 端 `vmware-toolbox-cmd disk shrink /` 歸零 → Host 端 `vmware-vdiskmanager -k` 壓縮 |
| 壓縮選單是灰色的／壓縮失敗 ★★★★★ | 存在快照，或 VM 不是完全關機 | 刪除所有快照（**不可逆**）並完全關機後再壓縮 |
| 刪除快照時 VM 卡住很久甚至看似當機 ★★★★★ | delta 檔案很大，正在合併回 base | **不要強制關閉、不要斷電**，讓它跑完；下次不要讓快照鏈長成這樣 |
| `Transport (VMDB) error -14: Pipe connection has been broken.` ★★★★ | Workstation 背景服務異常結束 | 關閉所有 Workstation 視窗，重啟 `VMware Authorization Service`（`VMAuthdService`）；必要時重開機 |
| Linux Host：`Could not open /dev/vmmon: No such file or directory.` ★★★★★ | 核心模組沒載入（核心升級後未重編，或 Secure Boot 拒絕未簽章模組） | `sudo vmware-modconfig --console --install-all`；`dmesg` 看有無 `Loading of unsigned module is rejected`，有的話用 MOK 簽章 |
| `VMware Workstation unrecoverable error: (vcpu-0)` ★★★★★ | 多種原因：主機記憶體不足、硬體不穩、版本相容問題 | 記下 `vmware.log`（VM 目錄下）的錯誤段落；先降低 vCPU 與記憶體測試；跑 Host 記憶體檢測 |
| 開機很慢，停在偵測裝置階段 ★★★ | 殘留的軟碟機、序列埠等虛擬裝置 | 移除 Floppy、Serial、Parallel、Sound、Printer |
| Windows Host 上 VM 一開機整台就卡 ★★★★ | 記憶體超配導致主機 swap | 調降 VM 記憶體，確保 Host `Available MBytes` ≥ 4000 |

> [!tip] ★★★★★ 排錯的第一站永遠是 `vmware.log`
> 每台 VM 的目錄下都有 `vmware.log`（以及 `vmware-0.log`、`vmware-1.log` 等舊檔）。
> VM 開不起來、異常結束時，**答案幾乎都在裡面**。
>
> ```powershell
> Get-Content 'D:\VMs\pve\vmware.log' -Tail 50
> ```
>
> ```bash
> tail -n 50 ~/vmware/pve/vmware.log
> ```
>
> 找關鍵字：`Msg_Post`、`error`、`failed`、`VMX has left the building`。

---

## 安全性注意事項

> [!danger] ★★★★★ 巢狀虛擬化擴大了攻擊面
> 開啟 `vhv.enable` 等於把 CPU 的特權指令暴露給 Guest。
> 歷史上出現過從 Guest 逃逸到 Host 的漏洞，巢狀環境讓這條路更複雜也更危險。
> **只在需要的 VM 上開啟，不要當成預設值套用到所有機器。**

| 項目 | 風險 | 做法 |
| --- | --- | --- |
| 側通道緩解被關閉 ★★★★★ | 推測執行漏洞可能導致跨 VM 資料洩漏 | 機關環境**不要關**；要關必須是完全隔離的專用實驗機並留書面例外 |
| 防毒排除整個 VM 目錄 ★★★★ | 惡意的 `.vmdk` 或下載到該目錄的檔案不再被掃描 | 優先只排除 `vmware-vmx.exe` 程序；VM 目錄不要當下載資料夾 |
| 巢狀環境的 Guest 未更新 ★★★★ | 兩層都是舊系統，漏洞疊加 | 實驗機也要定期 `apt upgrade`；長期不用就關機或刪除 |
| `.vmdk` 就是整台機器 ★★★★★ | 複製走一個檔案＝整台被偷 | 實驗機不放正式資料；必要時用 Pro 的 VM 加密 |
| 快照當成備份 ★★★★★ | 主機硬碟壞掉，base 與快照一起沒 | 快照不是備份；重要 VM 要**複製到另一顆碟或外部儲存** |
| 磁碟壓縮前忘記做備份 ★★★★ | 壓縮異常中斷可能損壞 `.vmdk` | 壓縮前先完整複製整個 VM 目錄 |
| `dd if=/dev/zero` 歸零 ★★★★★ | 過程中磁碟寫滿，執行中的服務可能損壞資料 | 先做快照、先停服務；**絕不在正式機執行** |
| 刪除所有快照以便壓縮 ★★★★★ | 不可逆，之前的還原點全部消失 | 先確認不再需要；必要的還原點改用完整複製保存 |
| Workstation 版本過舊 ★★★★ | 曾出現 Guest-to-Host 逃逸漏洞 | 保持在原廠支援中的版本；訂閱原廠資安公告 |
| 實驗 VM 橋接到機關網段 ★★★★★ | 未打補丁的實驗機直接曝露在正式網路 | 預設用 NAT 或 Host-only，見 [[050-01-02-04-guide-Workstation-網路模式]] |

---

## 速查表

### CPU 與記憶體

| 項目 | 準則 |
| --- | --- |
| vCPU 總和上限 ★★★★★ | **≤ 主機實體核心數**（不算超執行緒） |
| 一般 Linux Server ★★★★ | 2 vCPU / 2 GB |
| 資料庫 VM ★★★ | 2～4 vCPU / 4 GB |
| **巢狀 PVE** ★★★★★ | **4 vCPU / 8 GB 以上** |
| 主機保留（Windows 桌面）★★★★★ | **6 GB** |
| 主機保留（Linux 文字介面）★★★ | 2 GB |
| 記憶體策略 ★★★★ | `Edit → Preferences → Memory` 選 `Fit all …` |
| 插槽 vs 核心 ★★★ | 一律 1 processor × N cores（除非軟體按插槽授權） |

### 巢狀虛擬化

| 項目 | 內容 |
| --- | --- |
| GUI 位置 ★★★★★ | `VM → Settings → Processors → Virtualization engine` |
| 必勾選項 ★★★★★ | `Virtualize Intel VT-x/EPT or AMD-V/RVI` |
| `.vmx` 參數 ★★★★★ | `vhv.enable = "TRUE"` |
| 效能計數器 ★★★ | `vpmc.enable = "TRUE"` |
| IOMMU（裝置直通）★★★ | `vvtd.enable = "TRUE"` |
| 前提一 ★★★★★ | Host `HyperVisorPresent` 必須是 `False` |
| 前提二 ★★★★★ | Host CPU 支援 EPT（Intel）／RVI‑NPT（AMD） |
| 前提三 ★★★ | 虛擬硬體版本夠新 |
| 驗證 1 ★★★★★ | `grep -c -E 'vmx\|svm' /proc/cpuinfo` = vCPU 數 |
| 驗證 2 ★★★★★ | `lscpu \| grep -i virtual` 有 `Virtualization: VT-x` |
| 驗證 3 ★★★★★ | `sudo kvm-ok` → `KVM acceleration can be used` |
| 驗證 4 ★★★★ | `ls -l /dev/kvm` 存在、`lsmod \| grep kvm` 有 `kvm_intel`／`kvm_amd` |
| 驗證（RHEL 系）★★★★ | `virt-host-validate` 前三項 `PASS` |

### 磁碟

| 動作 | 指令／位置 |
| --- | --- |
| Guest 歸零（Tools）★★★★★ | `sudo vmware-toolbox-cmd disk shrink /` |
| Guest 歸零（手動）★★★★ | `sudo dd if=/dev/zero of=/zero.fill bs=1M; sync; rm /zero.fill` |
| Guest 歸零（Windows）★★★ | `sdelete64.exe -z C:` |
| Host 壓縮 ★★★★★ | `vmware-vdiskmanager -k <vmdk>` |
| Host 碎片整理 ★★★ | `vmware-vdiskmanager -d <vmdk>`（**SSD 不要做**） |
| 擴大磁碟 ★★★★ | `vmware-vdiskmanager -x 200GB <vmdk>` |
| 轉換型式 ★★★ | `vmware-vdiskmanager -r <來源> -t <型別> <目標>` |
| 檢查磁碟鏈 ★★★ | `vmware-vdiskmanager -R <vmdk>` |
| GUI 清理 ★★★★ | `VM → Manage → Clean Up Disks…` |
| 壓縮前提 ★★★★★ | **完全關機 ＋ 沒有任何快照** |
| Guest 端擴充分割區 ★★★★ | `growpart` → `pvresize` → `lvextend` → `resize2fs` / `xfs_growfs` |

### 診斷

| 檢查 | 指令 |
| --- | --- |
| **VM 日誌** ★★★★★ | VM 目錄下的 `vmware.log`（找 `Msg_Post`／`error`） |
| Host 有無其他 Hypervisor ★★★★★ | `Get-ComputerInfo -Property "HyperVisorPresent"` |
| Host 實體核心數 ★★★★ | `Get-CimInstance Win32_Processor \| Select NumberOfCores` |
| Host 可用記憶體 ★★★★★ | `Get-Counter '\Memory\Available MBytes'` |
| VMware 服務 ★★★★ | `Get-Service VMware*` |
| Guest vCPU 數 ★★★ | `nproc` |
| Guest 記憶體 ★★★ | `free -h` |
| Guest 負載 ★★★★ | `uptime`（load average vs vCPU 數） |
| Guest I/O 等待 ★★★★ | `top` 看 `%wa`；`iostat -x 2` |
| Guest 磁碟用量 ★★★ | `df -h` |
| 氣球佔用 ★★★ | `vmware-toolbox-cmd stat balloon` |
| 實際 CPU 速度 ★★★ | `vmware-toolbox-cmd stat speed` |
| Linux Host 模組 ★★★★ | `lsmod \| grep -E '^vmmon\|^vmnet'` |
| Linux Host 重編模組 ★★★★ | `sudo vmware-modconfig --console --install-all` |

### 該拔掉的虛擬裝置

| 裝置 | Server VM |
| --- | --- |
| Floppy ★★★★ | 移除 |
| Sound Card ★★★★ | 移除 |
| Printer ★★★★ | 移除 |
| USB Controller ★★★ | 移除 |
| Serial / Parallel Port ★★★ | 移除 |
| CD/DVD ★★★★ | 保留但取消 `Connect at power on` |
| Accelerate 3D graphics ★★★ | 取消勾選 |

---

## 練習題

1. 算出你自己這台主機「可以同時開幾台什麼規格的 VM」。列出實體核心數、
   實體記憶體、主機保留量，以及你的分配方案，並說明每一項的理由。

2. 在一台現有的實驗 VM 上完成完整的磁碟壓縮流程：記錄壓縮前後 `.vmdk` 的實際大小、
   Guest 裡 `df -h` 的數字，以及整個流程花的時間。過程中你遇到什麼阻礙？

3. 開啟巢狀虛擬化，用本篇的四種方法逐一驗證，把每一個指令的實際輸出貼出來。
   然後**故意把 `Virtualize Intel VT-x/EPT` 取消勾選**再驗證一次，比較兩組輸出的差異。

4. 建立一個有 5 層快照的 VM（每層之間都做一些檔案寫入），
   測量從最新狀態還原到第 1 層所花的時間，以及 VM 目錄的總大小變化。
   然後刪除所有快照，記錄合併花了多久。

5. 一位同事說「我的 VM 明明配了 8 顆 CPU、16 GB 記憶體，比同事配 2 顆 4 GB 的還慢」。
   寫出你的完整排查流程（至少 6 個檢查點），以及最可能的兩個原因。

6. 為你的機關寫一份「Workstation 實驗機標準規格表」，
   針對「一般 Linux 練習機」「資料庫機」「巢狀 PVE 機」三種角色，
   分別定出 vCPU、記憶體、磁碟、要移除的裝置與必要的勾選項目。

> [!question]- 練習解答
>
> **1.** 範例（16 GB / 6 核主機、Windows 11）：
> - 主機保留 6 GB → 可分配約 10 GB
> - vCPU 上限 6
> - 方案：Ubuntu Server A（2 vCPU/2 GB）＋ Ubuntu Server B（2 vCPU/2 GB）
>   ＋ MySQL 機（2 vCPU/4 GB）＝ 6 vCPU / 8 GB，還留 2 GB 緩衝
> - **這台主機不適合跑巢狀 PVE**（PVE 自己就要 8 GB）——這就是算這筆帳的意義。★★★★
>
> **2.** 重點是**必須先在 Guest 歸零**。只做 Host 端 Compact 通常縮不了多少，
> 因為 Host 分不出哪些區塊是已刪除的資料。
> 常見阻礙：①有快照 → 壓縮選單是灰的，要先刪快照；
> ②主機碟空間不足 → `dd` 歸零時 `.vmdk` 會先暴增到滿容量。★★★★★
>
> **3.** 勾選時：`grep -c` 回傳 vCPU 數、`lscpu` 有 `Virtualization: VT-x`、
> `kvm-ok` 說可用、`/dev/kvm` 存在。
> 取消勾選後：`grep -c` 回傳 **0**、`lscpu` **沒有** `Virtualization` 那一行、
> `kvm-ok` 顯示 `Your CPU does not support KVM extensions`、`/dev/kvm` 不存在。
> **這組對照就是判斷巢狀有沒有生效的標準答案。** ★★★★★
>
> **4.** 預期觀察：
> - 快照數增加後，VM 的一般操作（尤其 `apt upgrade` 這種大量寫入）明顯變慢
> - VM 目錄總大小遠大於 Guest 裡 `df` 顯示的用量
> - 還原到第 1 層的時間隨鏈長度增加
> - **刪除所有快照時要合併大量資料，可能跑很久**，而且期間不能中斷
> 結論：快照鏈控制在 3 層以內。★★★★★
>
> **5.** 排查流程：
> 1. Host 實體核心數是多少？8 vCPU 是不是已經超配 ★★★★★
> 2. 所有執行中 VM 的 vCPU 總和是多少
> 3. Host `Available MBytes` 剩多少，有沒有在 swap ★★★★★
> 4. VM 有幾層快照 ★★★★
> 5. `.vmdk` 放在 SSD 還是傳統硬碟 ★★★★★
> 6. 防毒有沒有排除 VM 目錄 ★★★★
> 7. 筆電是不是在省電模式 ★★★
> 8. Guest 裡 `uptime` 的 load average 與 `top` 的 `%wa`
>
> 最可能的兩個原因：**①vCPU 超配導致 co-scheduling 等待**；
> **②記憶體配太多導致 Host swap**。這位同事的兩個「配很多」剛好就是變慢的原因。★★★★★
>
> **6.** 規格表大綱：
>
> | 角色 | vCPU | RAM | 磁碟 | 移除裝置 | 勾選 |
> | --- | --- | --- | --- | --- | --- |
> | 一般 Linux 練習機 | 2 | 2 GB | 40 GB 動態 | Floppy/Sound/Printer/USB | — |
> | 資料庫機 | 2～4 | 4 GB | 60 GB 動態、NVMe 控制器 | 同上 | — |
> | 巢狀 PVE 機 | 4 | 8 GB | 120 GB 動態 | 同上 | **Virtualize VT-x/EPT** ★★★★★ |
>
> 三者共通：CD/DVD 取消 `Connect at power on`、關 3D 加速、
> Host 端排除防毒掃描、`.vmdk` 放 SSD。

---

## 小測驗

Q1. 主機是 8 核 32 GB 的 Windows 11。你要同時開三台 VM，
分別是 4 vCPU、4 vCPU、2 vCPU，記憶體各 8 GB。這個配置有什麼問題？

Q2.（是非）VM 的記憶體配 16 GB 但 Guest 裡只用了 2 GB，
所以其餘 14 GB 主機還是可以拿去用。

Q3. 要在 Workstation 的 VM 裡安裝 Proxmox VE 並在裡面開虛擬機。
請寫出：要勾哪個選項、對應的 `.vmx` 參數是什麼、以及**三個前提條件**。

Q4. 下面這行指令在 Guest 裡回傳 `0`，代表什麼？接下來你會檢查什麼？

```bash
grep -c -E 'vmx|svm' /proc/cpuinfo
```

Q5.（選擇）以下哪一個**不是**巢狀虛擬化失敗的可能原因？
(A) Host 上 WSL2 開著　(B) 改 `.vmx` 時 VM 是 Suspend 狀態
(C) VM 的網路模式設成 Host-only　(D) 虛擬硬體版本太舊

Q6. `.vmdk` 已經 80 GB，Guest 裡 `df -h` 只顯示用了 12 GB。
寫出把它縮回來的完整流程（Guest 端與 Host 端各做什麼），以及兩個前提條件。

Q7.（是非）虛擬磁碟放在 SSD 上時，定期跑 `vmware-vdiskmanager -d` 做碎片整理
可以維持效能。

Q8. 使用者反映「VM 昨天還很快，今天突然變超慢，什麼都沒改」。
列出你的前五個檢查點，並說明各自的判斷依據。

Q9. 下面這串指令在做什麼？為什麼一定要先做快照、先停服務？
最後那個「錯誤訊息」為什麼其實是正常的？

```bash
sudo dd if=/dev/zero of=/zero.fill bs=1M
sudo sync
sudo rm -f /zero.fill
```

Q10. 一台 VM 有 12 層快照。使用者想壓縮 `.vmdk` 釋放空間。
你會怎麼回答？過程中有哪兩個不可逆或高風險的環節要先講清楚？

> [!question]- 測驗答案
>
> **Q1.** 兩個問題：
> ①**vCPU 總和 10 > 實體核心 8**，超配會造成 co-scheduling 等待，三台都變慢；
> ②**記憶體總和 24 GB，只留 8 GB 給主機**——雖然還不算爆，但 Windows 11 桌面
> 加上瀏覽器很容易吃掉，一旦開始 swap 整台會一起卡。
> 建議調成 4+2+2 vCPU、8+4+4 GB。
> → 見〈CPU 配置準則〉與〈記憶體配置準則〉★★★★★
>
> **Q2.** **錯**。Workstation 的預設策略（尤其選了 `Fit all virtual machine memory
> into reserved host RAM`）會盡量把 VM 記憶體放進主機實體 RAM，**配多少大致就佔多少**。
> 只有裝了 Tools 的氣球驅動能讓 Host 借回部分閒置頁面，且效果有限。
> → 見〈第一原則〉的誤解對照表 ★★★★★
>
> **Q3.** 勾 **`Virtualize Intel VT-x/EPT or AMD-V/RVI`**
> （`VM → Settings → Processors → Virtualization engine`），
> 對應 `.vmx` 參數是 **`vhv.enable = "TRUE"`**。三個前提：
> ①Host CPU 支援 EPT（Intel）或 RVI／NPT（AMD）；
> ②**Host 上沒有其他 Hypervisor 佔用**（`HyperVisorPresent` 必須是 `False`）；
> ③VM 的虛擬硬體版本夠新。
> → 見〈巢狀虛擬化〉★★★★★
>
> **Q4.** 代表 **Guest 的 CPU 完全沒有 `vmx`／`svm` 旗標，也就是硬體虛擬化沒有透傳進來**，
> 在裡面裝 PVE／KVM 一定失敗。接下來依序檢查：
> ①Host 的 `HyperVisorPresent` 是不是 `True`；
> ②`.vmx` 裡有沒有 `vhv.enable = "TRUE"`；
> ③改設定時 VM 是不是完全關機；④虛擬硬體版本。
> → 見〈在 Guest 裡驗證〉與其後的檢查順序表 ★★★★★
>
> **Q5.** **(C) VM 的網路模式設成 Host-only**。網路模式與 CPU 特權指令的透傳
> 完全無關。(A)(B)(D) 都是真正常見的失敗原因。
> → 見〈巢狀虛擬化〉前提與錯誤訊息表 ★★★★
>
> **Q6.** 流程：
> 1. **Guest 端歸零**：`sudo vmware-toolbox-cmd disk shrink /`
>    （或 `dd if=/dev/zero` 後刪除）
> 2. Guest 完全關機
> 3. **Host 端壓縮**：`vmware-vdiskmanager -k <vmdk>`
>    或 `VM → Manage → Clean Up Disks…`
>
> 兩個前提：**①VM 完全關機（不是 Suspend）；②沒有任何快照。**
> 只做 Host 端 Compact 而略過 Guest 歸零，通常縮不了多少。
> → 見〈磁碟膨脹與壓縮〉★★★★★
>
> **Q7.** **錯**。碎片整理的目的是減少實體磁頭尋道，**SSD 沒有磁頭**，
> 做這個只是製造大量無謂寫入、消耗 SSD 壽命。
> **SSD 上只做壓縮（`-k`），不做碎片整理（`-d`）。**
> → 見〈碎片整理〉的 tip ★★★★
>
> **Q8.** 前五個檢查點：
> 1. **快照層數**——是不是又疊了好幾層（Snapshot Manager）★★★★★
> 2. **主機碟剩餘空間**——快滿時效能會斷崖式下降 ★★★★★
> 3. **防毒排除清單**——是不是被更新或 GPO 重設，又開始掃 VM 目錄 ★★★★
> 4. **電源計畫**——筆電是不是拔了電源切到省電模式導致降頻 ★★★
> 5. **Host 端負載**——工作管理員看是不是有別的程式（或別台 VM）在吃資源 ★★★★
> 另可看 Guest 的 `top` `%wa` 判斷是不是卡在 I/O。
> → 見〈常見錯誤與排錯〉「效能突然變慢」那一列 ★★★★★
>
> **Q9.** 它把整顆磁碟的可用空間**寫滿 0**，讓 Host 端的壓縮動作認得出哪些區塊
> 是已刪除的垃圾。
> - **先做快照**：過程有風險，出事要能還原
> - **先停服務**：過程中磁碟是滿的，正在寫入的資料庫等服務可能出錯或損毀資料 ★★★★★
> - 最後的 `No space left on device` **就是目的達成的訊號**——要把空間填滿才有效，
>   所以它一定會以這個訊息結束。
> → 見〈正確的壓縮流程〉的 danger ★★★★★
>
> **Q10.** 回答要點：**有快照就不能壓縮**，必須先刪除所有快照。
> 兩個要先講清楚的環節：
> ①**刪除快照是不可逆的**——所有還原點會永久消失，先確認不再需要，
> 必要的狀態改用完整複製另外保存；
> ②**合併 12 層快照可能跑很久且不能中斷**，期間效能極差，
> 而且**主機碟要有足夠空間**放合併過程的資料，空間不足會失敗甚至損壞磁碟鏈。
> 順帶建議：以後快照鏈控制在 3 層以內、不要留超過一週。
> → 見〈快照鏈〉與〈磁碟膨脹與壓縮〉★★★★★

---

## 延伸閱讀

- [[050-01-02-01-svc-Workstation-安裝與授權]] — Hyper-V 衝突是巢狀虛擬化的頭號殺手
- [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] — 建立時就把資源配對
- [[050-01-02-03-guide-Workstation-快照與複製]] — 快照策略與連結複製的取捨
- [[050-01-02-04-guide-Workstation-網路模式]] — 網路不通時的排查起點
- [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] — 氣球驅動與 `disk shrink` 都來自 Tools
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] — EPT／RVI 在做什麼，為什麼巢狀需要它
- [[050-01-03-01-svc-PVE-安裝與初始設定]] — 巢狀環境備好後的第一站
- [[050-01-04-02-svc-KVM-安裝與virt-manager]] — 在 Linux VM 裡再跑一層 KVM
- [[050-01-03-09-svc-PVE-監控與資源調校]] — Type-1 平台的資源調校思路差在哪
