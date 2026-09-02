---
title: "安裝與授權"
desc: "Windows 與 Linux 兩邊的 Workstation 安裝步驟、Hyper-V／WSL2 共存衝突的解法、Player 與 Pro 的差別"
aliases: [VMware Workstation 安裝, Workstation Pro, Workstation Player, vmware-installer]
tags: [群組/虛擬機與容器, 主題/虛擬化, 主題/VMware]
category: 虛擬機與容器
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-01-01-guide-虛擬化-虛擬化概念與選型]]"]
updated: 2026-09-02
---

# 安裝與授權

> [!warning] 未實機驗證
> 本篇的選單路徑與畫面文字**以 VMware Workstation 17 為例**，其他版本的選單位置、
> 按鈕文字可能不同。Workstation 的授權條款與下載入口在 Broadcom 併購後多次調整，
> **實際採購與授權方式一律以採購當時的原廠條款為準**，動手前先到原廠網站確認。

> [!abstract] 這篇你會學到
> - Workstation 在本手冊裡的定位：**桌機端虛擬化主線**，用來建各章需要的實驗環境 ★★★
> - Windows 主機與 Linux 主機兩邊的完整安裝步驟，含 Linux 端的核心模組編譯問題 ★★★
> - ★★★★ **與 Hyper-V／WSL2／Device Guard 共存的衝突**——這是最常見的「裝了卻跑不起來」原因
> - Player 與 Pro 的功能差異，以及為什麼本手冊的實驗環境**需要 Pro 才做得完整** ★★★
> - 授權輸入、版本升級、乾淨移除的正確做法 ★★
> - 安裝完成後該做的六項驗證，確定環境真的可用 ★★★

## 前置知識

- [[050-01-01-01-guide-虛擬化-虛擬化概念與選型]]
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]]
- [[020-01-02-guide-Linux-實驗環境準備與初次登入]]

---

## 觀念說明

### ★★★★ Workstation 在本手冊裡的角色

本手冊後面十幾個章節都需要「一台可以亂搞的機器」：練 Linux 指令、架 Nginx、
做憑證鏈、跑 ModSecurity、甚至在虛擬機裡再裝一台 Proxmox VE。這些都不可能拿正式機來做。

**VMware Workstation 就是本手冊的桌機端虛擬化主線**——你在自己的筆電或桌機上跑它，
它幫你開出一整組互相連得到的實驗機。★★★★

| 需求 | 為什麼要 Workstation | 相關章節 |
| --- | --- | --- |
| 練 Linux 指令，弄壞可還原 ★★★★ | 快照三秒回到乾淨狀態 | [[020-01-02-guide-Linux-實驗環境準備與初次登入]] |
| 架 Web／DB 服務並測試 ★★★ | 有完整網路堆疊，不像 WSL2 是模擬的 | 060 群組各章 |
| 多台機器互連（主從、叢集）★★★ | 一台主機開三、五台 VM 放同一個虛擬網段 | [[050-01-02-04-guide-Workstation-網路模式]] |
| 在虛擬機裡再跑虛擬化 ★★★★ | 巢狀虛擬化，PVE／KVM 章節必需 | [[050-01-03-01-svc-PVE-安裝與初始設定]] |
| 驗證安裝流程與 SOP ★★★ | 反覆重來成本近乎零 | 100 群組維運實務 |

> [!note] Workstation 是 Type-2（寄居型）Hypervisor ★★★
> 它跑在你的 Windows／Linux 桌面作業系統**之上**，不是像 ESXi／Proxmox VE 那樣直接跑在裸機上。
> 這代表效能會被主機作業系統吃掉一部分，但換來的是**隨開隨關、和你的桌面環境共存**。
> 型別的差異在 [[050-01-01-01-guide-虛擬化-虛擬化概念與選型]] 有完整比較。

### ★★★ Workstation 產品線：Pro 與 Player

歷史上 VMware 桌面虛擬化有兩條產品線：

| | Workstation **Player** | Workstation **Pro** |
| --- | --- | --- |
| 開／關虛擬機 | ✅ | ✅ |
| 建立新虛擬機 | ✅ | ✅ |
| **快照（Snapshot）** ★★★★★ | ❌ **完全沒有** | ✅ 多重快照、快照樹 |
| **複製（Clone）** ★★★★ | ❌ | ✅ 完整複製＋連結複製 |
| **虛擬網路編輯器** ★★★★ | ❌（只能用預設三種） | ✅ 可自訂多個 VMnet 網段 |
| 同時開多台 VM 的分頁介面 ★★ | 一次一台為主 | ✅ 分頁式管理多台 |
| 加密虛擬機 ★★ | ❌ | ✅ |
| `vmrun` 命令列自動化 ★★★ | 受限 | ✅ |
| 連線到遠端 ESXi／vCenter ★★ | ❌ | ✅ |

> [!danger] ★★★★★ 沒有快照＝這本手冊大半章節做不下去
> 本手冊的教學方式建立在「弄壞可還原」上。Player 沒有快照功能，
> 你改壞 `sshd_config` 或誤刪系統套件之後**只能整台重裝**。
> **請務必使用 Workstation Pro**，不要為了省事用 Player。

> [!warning] 產品線與授權條款近年變動很大 ★★★★
> Broadcom 併購 VMware 之後，桌面虛擬化產品的**產品線編制、下載入口與授權條款
> 經歷了多次調整**（包含 Player 併入 Pro、個人用途免費化等方向）。
> 本手冊**刻意不記載任何版本號、價格與具體條款**，因為寫下來就會過期。
>
> - 採購前：到原廠／代理商確認**當前**的授權型態與適用範圍
> - 機關使用：務必確認你的用途屬於「商業使用」還是「個人使用」，**這兩者的條款不同**
> - 已有舊版授權：確認是否涵蓋要升級的大版本（大版本升級通常需要 Upgrade 授權）
> - **絕對不要**以本手冊或網路文章的說法作為採購依據 ★★★★★

### ★★★★ 系統需求：三個一定要過的門檻

#### 1. CPU 必須支援硬體虛擬化，而且要在 BIOS/UEFI 裡開啟 ★★★★★

| 平台 | 技術名稱 | BIOS/UEFI 裡常見的選項名稱 |
| --- | --- | --- |
| Intel | VT-x（虛擬化）、EPT（記憶體虛擬化） | `Intel Virtualization Technology`、`Intel VT-x`、`VT-d` |
| AMD | AMD-V／SVM、RVI／NPT | `SVM Mode`、`AMD-V`、`SVM Support` |

**沒開啟的症狀**：建立 64 位元虛擬機時直接被擋，或開機時跳出

```text
This host supports Intel VT-x, but Intel VT-x is disabled.
```

或

```text
Binary translation is incompatible with long mode on this platform.
```

在 Windows 主機上可以先用工作管理員確認：**工作管理員 → 效能 → CPU**，
右下角會有一行「虛擬化：已啟用／已停用」。★★★

Linux 主機用指令確認：

```bash
grep -o -m1 -E 'vmx|svm' /proc/cpuinfo
```

```text
vmx
```

有輸出就代表 CPU 支援且 BIOS 已開啟（`vmx` 是 Intel、`svm` 是 AMD）；
**完全沒有輸出**就要進 BIOS/UEFI 開啟。★★★★

> [!tip] 「工作管理員顯示已啟用，Workstation 還是說 VT-x 被停用」★★★★
> 這幾乎一定是 **Hyper-V 把虛擬化功能整個佔走了**，不是 BIOS 的問題。
> 直接跳到下面的〈與 Hyper-V／WSL2 共存〉。

#### 2. 記憶體要夠分 ★★★★

Workstation 的虛擬機記憶體是**真的從主機挖走**的（沒有 ESXi 那種積極的記憶體超配）。

| 主機實體記憶體 | 實際可用來開 VM | 建議情境 |
| --- | --- | --- |
| 8 GB ★★ | 約 3～4 GB | 勉強跑一台 Ubuntu Server（無桌面） |
| 16 GB ★★★ | 約 9～11 GB | 兩到三台 Server VM，本手冊多數章節可行 |
| 32 GB ★★★★ | 約 22～26 GB | 多機實驗、巢狀虛擬化跑 PVE，最舒服 |
| 64 GB | 充裕 | 完整重現機關環境（AD＋Web＋DB＋監控） |

> [!warning] ★★★★ 給主機留 4～6 GB
> 把記憶體配到只剩 2 GB 給主機，結果是主機開始 swap，**整台電腦（含 VM）一起卡死**。
> 詳細配置準則見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]]。

#### 3. 磁碟空間與型式 ★★★★

- 一台 Ubuntu Server 實驗機至少留 **40 GB**；有快照的話再乘 1.5～2 倍
- **強烈建議放 SSD/NVMe**。放傳統硬碟的話，開機要三分鐘、`apt upgrade` 慢到懷疑人生 ★★★★
- Workstation 程式本身裝在系統碟，但**虛擬機檔案可以放在另一顆碟**，這是常見且推薦的做法 ★★★

### ★★★★★ 與 Hyper-V／WSL2 共存：最常見的「裝不起來」

這一節是本篇最重要的部分。**Windows 主機上八成的 Workstation 問題都出在這裡。**

#### 為什麼會衝突

x86 的硬體虛擬化（VT-x／AMD-V）在同一時間**只能被一個 Hypervisor 完整持有**。
Windows 上有一整族功能其實都是「偷偷啟用了 Hyper-V」：

| Windows 功能 | 是否會啟用 Hyper-V 層 | 常見程度 |
| --- | --- | --- |
| Hyper-V 角色／Hyper-V 管理員 ★★★★ | 是 | 明顯 |
| **WSL 2** ★★★★★ | 是（透過 Virtual Machine Platform） | **極常見，最容易忽略** |
| Windows 沙箱（Windows Sandbox）★★★ | 是 | 常見 |
| **記憶體完整性 / 核心隔離**（Core Isolation → Memory Integrity）★★★★★ | 是（VBS） | **新機／新版 Windows 預設可能開著** |
| Credential Guard / Device Guard ★★★★ | 是（VBS） | 機關網域環境常由 GPO 強制開啟 |
| 虛擬機器平台（Virtual Machine Platform）★★★★ | 是 | WSL2、Docker Desktop 會裝 |
| Docker Desktop（WSL2 後端）★★★★ | 間接是 | 開發人員機器很常見 |
| 應用程式防護（Application Guard）★★ | 是 | 少見 |

**症狀**（訊息原文，看到就知道是這件事）：

```text
VMware Workstation and Device/Credential Guard are not compatible.
Workstation can be run after disabling Device/Credential Guard.
```

```text
VMware Workstation and Hyper-V are not compatible.
Remove the Hyper-V role from the system before running VMware Workstation.
```

#### ★★★ 兩條路：共存，或關掉

**路線 A：讓它們共存（新版 Workstation 支援）**

較新版的 Workstation 可以在 Hyper-V 存在時，改用 Windows Hypervisor Platform（WHP）
以「使用者層監視器（ULM）」模式運作，也就是**變成 Hyper-V 之上的客人**。

| 面向 | 共存模式的後果 |
| --- | --- |
| 能不能開 VM | ✅ 可以 |
| 效能 ★★★★ | **明顯較差**，CPU 密集與 I/O 密集工作特別有感 |
| **巢狀虛擬化** ★★★★★ | **通常不可用或極不穩**——PVE／KVM 章節會做不下去 |
| 適合誰 | 一定要留著 WSL2／Docker Desktop 的開發人員，且只跑輕量 VM |

**路線 B：關掉 Hyper-V 相關功能（本手冊建議）★★★★**

本手冊後面要在 Workstation 裡跑 Proxmox VE 與 KVM，**必須要有完整的巢狀虛擬化**，
所以建議走路線 B。

> [!danger] ★★★★★ 關掉之前先想清楚
> 關掉 Hyper-V 層會讓 **WSL2 無法啟動、Docker Desktop 的 WSL2 後端無法運作、
> Windows 沙箱消失**，而且在機關網域裡，**Credential Guard 可能是資安政策強制要求的**。
> - 個人開發機：照下面步驟關掉沒問題，隨時可以開回來
> - **機關配發、受 GPO 管控的電腦**：關閉 Device/Credential Guard 前**務必先問資安單位**，
>   擅自關閉可能違反內部資安規範 ★★★★★

---

## 安裝或基礎操作

### ★★★ Windows 主機：安裝步驟

#### 步驟 1：先處理 Hyper-V（強烈建議在裝之前做）★★★★

以**系統管理員**身分開啟 PowerShell。

**1-1 先盤點目前開了什麼**：

```powershell
Get-ComputerInfo -Property "HyperV*"
```

```text
HyperVisorPresent                                  : True
HyperVRequirementVirtualizationFirmwareEnabled     : True
```

`HyperVisorPresent : True` 代表**目前有 Hypervisor 在跑**（不一定是你自己開的）。★★★★

看有哪些相關功能被啟用：

```powershell
Get-WindowsOptionalFeature -Online |
  Where-Object { $_.FeatureName -match 'Hyper-V|VirtualMachinePlatform|Windows-Subsystem-Linux|Containers|Sandbox' } |
  Select-Object FeatureName, State
```

```text
FeatureName                            State
-----------                            -----
Microsoft-Hyper-V-All                  Enabled
VirtualMachinePlatform                 Enabled
Microsoft-Windows-Subsystem-Linux      Enabled
Containers-DisposableClientVM          Disabled
```

**1-2 關閉功能**（每一行都需要重開機才生效，建議一次下完再重開）：

```powershell
Disable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -NoRestart
Disable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -NoRestart
Disable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -NoRestart
```

> [!note] 也可以用 GUI ★★
> **控制台 → 程式集 → 開啟或關閉 Windows 功能**，取消勾選
> 「Hyper-V」「虛擬機器平台」「Windows 沙箱」「適用於 Linux 的 Windows 子系統」。

**1-3 關閉開機時載入 Hypervisor** ★★★★（這一步最關鍵，很多人漏掉）：

```powershell
bcdedit /set hypervisorlaunchtype off
```

```text
The operation completed successfully.
```

**1-4 關閉記憶體完整性（核心隔離）** ★★★★★：

GUI 路徑：**Windows 安全性 → 裝置安全性 → 核心隔離詳細資料 → 記憶體完整性 → 關閉**，
然後重開機。

也可以改登錄檔（需系統管理員，改完重開機）：

```powershell
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity" -Name "Enabled" -Value 0
```

**1-5 重新開機**，然後確認：

```powershell
Get-ComputerInfo -Property "HyperVisorPresent"
```

```text
HyperVisorPresent : False
```

看到 `False` 才算成功。★★★★ 若仍是 `True`，代表還有某個功能沒關（最常見是漏了
`hypervisorlaunchtype` 或記憶體完整性），或 GPO 又把它設回去了。

> [!tip] 要恢復 Hyper-V／WSL2 時 ★★★
> ```powershell
> bcdedit /set hypervisorlaunchtype auto
> Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -NoRestart
> Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -NoRestart
> ```
> 重開機後 WSL2 就回來了。**這是可逆的，不用怕。** ★★

#### 步驟 2：下載安裝檔 ★★

到原廠／Broadcom 支援入口下載 Windows 版安裝檔（`.exe`）。

> [!danger] ★★★★★ 只從原廠管道下載
> 網路上有大量「免安裝版」「破解版」Workstation。這些檔案：
> - 幾乎都夾帶惡意程式，機關電腦裝下去等於自己開後門
> - 違反授權條款，稽核時是明確缺失
> **一律從原廠或正式代理商取得。**

#### 步驟 3：執行安裝 ★★

1. 對安裝檔按右鍵 → **以系統管理員身分執行**
2. 歡迎畫面 → **下一步**
3. 勾選同意授權合約 → **下一步**
4. 自訂安裝：
   - **安裝位置**：預設在 `C:\Program Files\VMware\VMware Workstation\`，可改 ★
   - **Enhanced Keyboard Driver**（增強型鍵盤驅動）：★★ 建議勾。
     沒有它，在 VM 裡按 `Ctrl+Alt+Del`、日文／韓文輸入法等按鍵可能傳不進去
   - **Add VMware Workstation console tools to system PATH** ★★★：
     **建議勾**，勾了之後才能在命令列直接用 `vmrun`、`vmware-vdiskmanager`
5. 使用者體驗設定（檢查更新、加入改進計畫）：★ 機關環境通常兩個都取消勾選
6. 捷徑選項 → **下一步** → **安裝**
7. 安裝完成後**重新開機**

#### 步驟 4：輸入授權 ★★★

第一次啟動時會出現授權畫面：

- 有授權金鑰：貼上金鑰 → 完成
- 沒有：依當前原廠條款選擇適用的使用方式

安裝後想更改授權：**Help（說明）→ Enter a License Key（輸入授權金鑰）**。

> [!warning] 機關採購的金鑰要納入資產管理 ★★★
> 把金鑰與採購單號、到期日、可安裝台數記進資產清冊。
> 相關做法見 040 群組的〈資訊設備盤點〉與 100 群組維運制度章節。

#### 步驟 5：確認服務有起來 ★★★

```powershell
Get-Service -Name "VMware*" | Select-Object Name, DisplayName, Status
```

```text
Name             DisplayName                         Status
----             -----------                         ------
VMAuthdService   VMware Authorization Service        Running
VMnetDHCP        VMware DHCP Service                 Running
VMUSBArbService  VMware USB Arbitration Service      Running
VMware NAT Service VMware NAT Service                Running
```

| 服務 | 沒跑會怎樣 |
| --- | --- |
| VMware Authorization Service ★★★★ | **VM 完全開不起來**，或說沒有權限存取虛擬機檔案 |
| VMware NAT Service ★★★★ | NAT 模式的 VM 上不了外網 |
| VMware DHCP Service ★★★★ | NAT／Host-only 的 VM 拿不到 IP |
| VMware USB Arbitration Service ★★ | USB 裝置無法接進 VM |

### ★★★ Linux 主機：安裝步驟

Linux 主機安裝比 Windows 麻煩，因為 Workstation 需要編譯兩個核心模組
（`vmmon` 與 `vmnet`），核心一升級就可能要重編。★★★★

#### 步驟 1：安裝編譯環境 ★★★★

```bash
sudo apt update
sudo apt install -y build-essential linux-headers-$(uname -r)
```

確認 headers 真的對得上跑著的核心：

```bash
uname -r
ls -d /usr/src/linux-headers-$(uname -r)
```

```text
6.8.0-45-generic
/usr/src/linux-headers-6.8.0-45-generic
```

> [!warning] ★★★★ 兩者不一致 = 模組一定編不起來
> 常見於「剛 `apt upgrade` 完但還沒重開機」——此時 `uname -r` 是舊核心、
> headers 卻裝了新核心。**先重開機再裝 Workstation。**

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> sudo dnf groupinstall -y "Development Tools"
> sudo dnf install -y kernel-devel-$(uname -r) kernel-headers-$(uname -r) elfutils-libelf-devel
> ```
> RHEL 系上 `kernel-devel` 版本與跑著的核心不同步是常態，
> 裝完務必用 `ls -d /usr/src/kernels/$(uname -r)` 確認目錄存在。★★★

#### 步驟 2：執行 bundle 安裝檔 ★★★

下載回來的是 `.bundle` 檔。加上執行權限後以 root 執行：

```bash
chmod +x VMware-Workstation-Full-*.x86_64.bundle
sudo ./VMware-Workstation-Full-*.x86_64.bundle
```

會開出圖形化安裝精靈（同意條款 → 是否檢查更新 → 是否加入改進計畫 →
輸入授權金鑰 → 安裝）。

想走純文字安裝（無桌面環境或透過 SSH）：

```bash
sudo ./VMware-Workstation-Full-*.x86_64.bundle --console --required --eulas-agreed
```

| 參數 | 作用 |
| --- | --- |
| `--console` ★★★ | 文字模式安裝，不需要 X |
| `--required` ★★ | 只問必要問題 |
| `--eulas-agreed` ★★ | 預先同意授權合約（**你仍須實際閱讀並同意條款**） |

#### 步驟 3：編譯與載入核心模組 ★★★★

第一次啟動 `vmware` 時會自動跳出模組編譯。也可以手動觸發：

```bash
sudo vmware-modconfig --console --install-all
```

成功的話最後會看到模組安裝完成的訊息。確認模組真的載入了：

```bash
lsmod | grep -E '^vmmon|^vmnet'
```

```text
vmnet                  69632  13
vmmon                 143360  0
```

**兩個都要在**。只有 `vmmon` 沒有 `vmnet` 的話，虛擬網路（NAT／Host-only）會整組失效。★★★★

#### 步驟 4：★★★★★ Secure Boot 的處理

如果主機開了 UEFI Secure Boot，未簽章的 `vmmon`／`vmnet` **會被核心拒絕載入**，
症狀是模組編譯成功但 `lsmod` 看不到，`dmesg` 出現：

```text
Loading of unsigned module is rejected
```

有兩個做法：

**做法 A：關閉 Secure Boot（最快，但降低主機安全性）** ★★
進 UEFI 設定關掉 Secure Boot。機關電腦若有資安基準要求開啟 Secure Boot，**不要用這招**。

**做法 B：自己簽章並註冊 MOK（建議）** ★★★★

```bash
# 1. 產生一組簽章用金鑰（放在只有 root 讀得到的目錄）
sudo mkdir -p /root/vmware-signing && cd /root/vmware-signing
sudo openssl req -new -x509 -newkey rsa:2048 -keyout MOK.priv -outform DER -out MOK.der -nodes -days 3650 -subj "/CN=VMware Modules Signing/"

# 2. 簽 vmmon 與 vmnet
sudo /usr/src/linux-headers-$(uname -r)/scripts/sign-file sha256 ./MOK.priv ./MOK.der $(modinfo -n vmmon)
sudo /usr/src/linux-headers-$(uname -r)/scripts/sign-file sha256 ./MOK.priv ./MOK.der $(modinfo -n vmnet)

# 3. 把公鑰註冊進 MOK 清單（會要你設一組一次性密碼）
sudo mokutil --import ./MOK.der
```

```text
input password:
input password again:
```

**重開機**，開機時會進入藍底的 **MOK Manager** 畫面：
`Enroll MOK` → `Continue` → `Yes` → 輸入剛才那組密碼 → `Reboot`。★★★★

> [!danger] ★★★★ MOK 密碼只用這一次，而且沒有第二次機會
> 開機時輸錯或錯過那個畫面，註冊就會被取消，得重跑 `mokutil --import`。
> 密碼可以很簡單（只用一次），但**一定要記得**，不要設了就忘。

重開後驗證：

```bash
sudo mokutil --list-enrolled | grep -A1 "VMware"
lsmod | grep vmmon
```

> [!warning] ★★★★ 核心一升級就要重簽
> 每次 `apt upgrade` 換了核心版本，模組會重新編譯，**簽章不會自動跟著做**。
> 升級核心後如果 Workstation 打不開，先跑 `vmware-modconfig --console --install-all`
> 再重跑上面的步驟 2（簽章）。這是 Linux 主機跑 Workstation 最惱人的長期成本。

#### 步驟 5：確認服務與網路 ★★★

```bash
sudo systemctl status vmware
```

```text
● vmware.service - LSB: This service starts and stops VMware services
     Loaded: loaded (/etc/init.d/vmware; generated)
     Active: active (exited) since ...
```

虛擬網路狀態：

```bash
sudo vmware-networks --status
```

```text
Started NAT service on vmnet8
Started DHCP service on vmnet8
Started DHCP service on vmnet1
```

主機端應該多出兩張虛擬網卡：

```bash
ip -brief addr show | grep vmnet
```

```text
vmnet1  UNKNOWN  192.168.108.1/24
vmnet8  UNKNOWN  192.168.245.1/24
```

> [!note] 你看到的網段數字會和這裡不同 ★★★
> `vmnet1`（Host-only）與 `vmnet8`（NAT）的網段是**安裝時隨機挑的**，
> 每台機器都不一樣。網段規劃與固定方式見 [[050-01-02-04-guide-Workstation-網路模式]]。

---

## 進階應用

### ★★★ 無人值守／批次安裝（Windows）

機關要在多台教育訓練電腦上部署時，一台一台點很浪費時間。
Windows 版安裝檔支援靜默安裝參數：

```powershell
.\VMware-workstation-full-<version>.exe /s /v"/qn EULAS_AGREED=1 AUTOSOFTWAREUPDATE=0 DATACOLLECTION=0 /norestart"
```

| 參數 | 作用 |
| --- | --- |
| `/s` ★★ | 安裝程式本身靜默 |
| `/v"..."` ★★ | 把引號內參數傳給 MSI |
| `/qn` ★★★ | MSI 完全無介面 |
| `EULAS_AGREED=1` ★★★ | 同意授權合約（**仍須實際閱讀並同意**） |
| `AUTOSOFTWAREUPDATE=0` ★★ | 關閉自動更新檢查（機關內網通常連不出去） |
| `DATACOLLECTION=0` ★★ | 不加入使用者體驗改進計畫 |
| `/norestart` ★★★ | 安裝完不自動重開（由部署腳本統一控制） |

> [!warning] 未實機驗證 ★★★
> 靜默安裝的參數名稱**會隨版本調整**。正式大量部署前，
> 先在一台測試機跑一次並檢查安裝紀錄，不要直接推到全部電腦。

### ★★ 命令列工具：確認 PATH 有設好

```powershell
vmrun -T ws list
```

```text
Total running VMs: 0
```

Linux 主機上：

```bash
vmrun -T ws list
```

`vmrun` 是後面章節做自動化（批次開關機、批次快照）的基礎，
用法見 [[050-01-02-03-guide-Workstation-快照與複製]]。★★★

### ★★★ 升級到新的大版本

1. **先把所有 VM 完全關機**（不是暫停，是關機）★★★★
2. 匯出／備份重要的 VM 目錄（見下方「移除」章節的檔案清單）
3. 執行新版安裝檔，它會偵測舊版並詢問是否升級
4. 升級後**第一次開啟舊 VM 時會問要不要升級虛擬硬體版本**

> [!danger] ★★★★★ 虛擬硬體版本升級是單向的
> 把 VM 的硬體版本從 19 升到 21 之後，**舊版 Workstation 就再也打不開這台 VM**。
> - 要跟同事交換 VM 檔案的話，**保持在大家都支援的舊硬體版本**
> - 要升級前**先做完整複製當備份**（見 [[050-01-02-03-guide-Workstation-快照與複製]]）
> - 升級硬體版本的好處通常只是支援更多 vCPU／新裝置，**沒需要就不要升**

Linux 主機升級的額外動作 ★★★：

```bash
sudo vmware-modconfig --console --install-all   # 重編模組
lsmod | grep -E '^vmmon|^vmnet'                  # 確認載入
```

### ★★★ 乾淨移除

**Windows**：控制台 → 程式和功能 → VMware Workstation → 解除安裝。
移除後這些東西**不會**被刪掉，要自己清：

| 殘留 | 路徑 |
| --- | --- |
| 虛擬機檔案 ★★★★ | `C:\Users\<你>\Documents\Virtual Machines\`（或你自訂的位置） |
| 偏好設定 ★★ | `C:\Users\<你>\AppData\Roaming\VMware\preferences.ini` |
| 虛擬網路設定 ★★★ | `C:\ProgramData\VMware\vmnetnat.conf`、`vmnetdhcp.conf` |
| 虛擬網卡 ★★ | 裝置管理員裡的 VMware Network Adapter VMnet1／VMnet8 |

**Linux**：

```bash
sudo vmware-installer -l          # 列出已安裝的 VMware 產品
```

```text
Product Name          Product Version
==================== ==================
vmware-workstation   17.x.x
```

```bash
sudo vmware-installer -u vmware-workstation
```

移除時會問要不要保留設定檔（`/etc/vmware`）。要徹底清乾淨：

```bash
sudo rm -rf /etc/vmware /usr/lib/vmware /var/lib/vmware
```

> [!danger] ★★★★★ `rm -rf` 打錯路徑不可逆
> 上面三個路徑**只包含 VMware 自己的東西**，但你的虛擬機檔案
> （通常在 `~/vmware/`）**不在裡面**——請自己確認位置後再決定要不要刪。
> 刪之前先 `ls` 看一眼是本手冊的鐵律。

---

## 完整實戰範例

### 情境

一台配發的 Windows 11 筆電（16 GB RAM、512 GB NVMe），
使用者原本裝了 WSL2 與 Docker Desktop。現在要把它改造成**本手冊的實驗主機**，
之後要在裡面跑 Ubuntu Server 實驗機，並且要能在 VM 裡再跑 Proxmox VE。

目標：安裝 Workstation Pro、關掉 Hyper-V 層讓巢狀虛擬化可用、驗證環境可用。

### 步驟 1：盤點現況 ★★★

以系統管理員開啟 PowerShell：

```powershell
Get-ComputerInfo -Property "CsTotalPhysicalMemory","HyperVisorPresent","OsName"
```

```text
CsTotalPhysicalMemory : 17179869184
HyperVisorPresent     : True
OsName                : Microsoft Windows 11 專業版
```

```powershell
Get-WindowsOptionalFeature -Online |
  Where-Object { $_.State -eq 'Enabled' -and $_.FeatureName -match 'Hyper-V|VirtualMachinePlatform|Subsystem-Linux|Sandbox' } |
  Select-Object FeatureName
```

```text
FeatureName
-----------
VirtualMachinePlatform
Microsoft-Windows-Subsystem-Linux
```

**判讀**：沒裝 Hyper-V 角色，但 WSL2 需要的「虛擬機器平台」開著，
所以 `HyperVisorPresent` 是 `True`——這就足以讓 Workstation 的巢狀虛擬化失效。★★★★

### 步驟 2：和使用者確認影響 ★★★★

關掉之後 WSL2 與 Docker Desktop（WSL2 後端）會停擺。先確認：

- 使用者是否還需要 WSL2？→ 若需要，改用 **Workstation 裡的 Ubuntu VM** 取代 WSL2，
  其實更接近真實伺服器環境（[[020-01-02-guide-Linux-實驗環境準備與初次登入]] 有比較）
- Docker 練習可以改在 VM 裡裝 Docker Engine（見 050-02 容器化章）

### 步驟 3：備份 WSL2 資料（如果有東西要留）★★★★

```powershell
wsl -l -v
```

```text
  NAME              STATE           VERSION
* Ubuntu-24.04      Stopped         2
```

```powershell
wsl --shutdown
wsl --export Ubuntu-24.04 D:\backup\ubuntu-2404.tar
```

匯出的 tar 檔之後可以用 `wsl --import` 還原，**先備份再關功能**。★★★★

### 步驟 4：關閉 Hyper-V 層 ★★★★

```powershell
Disable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -NoRestart
Disable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -NoRestart
bcdedit /set hypervisorlaunchtype off
```

```text
The operation completed successfully.
```

再從 **Windows 安全性 → 裝置安全性 → 核心隔離詳細資料**，把「記憶體完整性」關閉。

```powershell
Restart-Computer
```

### 步驟 5：驗證 Hypervisor 真的關掉了 ★★★★

重開機後：

```powershell
Get-ComputerInfo -Property "HyperVisorPresent"
```

```text
HyperVisorPresent : False
```

✅ 這一行是整個流程的**成敗關鍵**。還是 `True` 的話回頭找漏掉的功能。

### 步驟 6：安裝 Workstation ★★

右鍵以系統管理員執行安裝檔 → 同意條款 →
勾選「Enhanced Keyboard Driver」與「Add ... console tools to system PATH」→
取消「檢查產品更新」與「加入改進計畫」→ 安裝 → 重開機。

### 步驟 7：輸入授權並完成初次啟動 ★★

啟動 Workstation Pro，依採購取得的方式完成授權。

### 步驟 8：六項驗收檢查 ★★★★

這是本篇最重要的產出——**裝完一定要跑完這六項**，不然問題會延到後面章節才爆。

**① 服務都在跑**

```powershell
Get-Service VMAuthdService,VMnetDHCP,"VMware NAT Service",VMUSBArbService |
  Select-Object Name,Status
```

```text
Name                 Status
----                 ------
VMAuthdService      Running
VMnetDHCP           Running
VMware NAT Service  Running
VMUSBArbService     Running
```

**② 虛擬網卡有出現**

```powershell
Get-NetAdapter | Where-Object { $_.InterfaceDescription -like "*VMware*" } |
  Select-Object Name, Status, InterfaceDescription
```

```text
Name       Status  InterfaceDescription
----       ------  --------------------
VMnet1     Up      VMware Virtual Ethernet Adapter for VMnet1
VMnet8     Up      VMware Virtual Ethernet Adapter for VMnet8
```

**③ 命令列工具進得了 PATH**

```powershell
vmrun -T ws list
```

```text
Total running VMs: 0
```

**④ 虛擬網路編輯器打得開（確認是 Pro 不是 Player）** ★★★
**Edit（編輯）→ Virtual Network Editor（虛擬網路編輯器）**，
需要按「變更設定」提權。看得到 VMnet0／VMnet1／VMnet8 三列就對了。

**⑤ 快照選單存在（Pro 的關鍵功能）** ★★★★
建一台空 VM，確認 **VM → Snapshot（快照）** 選單可用。

**⑥ 巢狀虛擬化選項可勾** ★★★★★
新建一台 VM →**Edit virtual machine settings → Processors**，
確認「**Virtualize Intel VT-x/EPT or AMD-V/RVI**」這個核取方塊**可以勾選且不是灰的**。

> [!danger] ★★★★★ 第 ⑥ 項是灰的 = 後面 PVE／KVM 章節做不了
> 灰掉的原因幾乎都是 Hyper-V 層還在（回到步驟 5）或 BIOS 沒開 VT-x/AMD-V。
> **現在解決，不要拖到要裝 Proxmox 的那天才發現。**
> 詳細排查見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]]。

### 步驟 9：設定虛擬機預設存放位置 ★★★

**Edit → Preferences → Workspace → Default location for virtual machines**，
改成資料碟上的路徑，例如 `D:\VMs\`。

理由：
- 系統碟通常較小，一台 VM 加快照就吃掉幾十 GB ★★★
- 重灌 Windows 時 VM 檔案不會一起消失 ★★★★
- 備份策略可以只針對這個資料夾

### 完成確認

到這裡你有了一台可用的實驗主機。下一步是實際建出第一台虛擬機：
[[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]]。

---

## 常見錯誤與排錯

| 現象（訊息原文） | 原因 | 解法 |
| --- | --- | --- |
| `VMware Workstation and Device/Credential Guard are not compatible.` ★★★★★ | 記憶體完整性／Credential Guard（VBS）啟用中 | 關閉核心隔離的記憶體完整性，必要時停用 Credential Guard 的 GPO，重開機 |
| `VMware Workstation and Hyper-V are not compatible.` ★★★★★ | Hyper-V 角色或虛擬機器平台啟用中 | `Disable-WindowsOptionalFeature` 關掉相關功能 ＋ `bcdedit /set hypervisorlaunchtype off`，重開機 |
| `This host supports Intel VT-x, but Intel VT-x is disabled.` ★★★★ | BIOS/UEFI 未開啟 VT-x，或被其他 Hypervisor 佔用 | 進 BIOS 開啟；若 BIOS 已開則檢查 Hyper-V |
| `Binary translation is incompatible with long mode on this platform.` ★★★★ | 要開 64 位元 VM 但硬體虛擬化不可用 | 同上，開 VT-x/AMD-V |
| VM 可以開，但「Virtualize Intel VT-x/EPT」選項是灰的 ★★★★★ | Hyper-V 層還在（共存模式），或 VM 正在執行中 | 先關 VM 再改設定；仍灰則回頭關 Hyper-V |
| Windows 上 VM 開機跳「無法連線到虛擬機」或權限錯誤 ★★★★ | `VMware Authorization Service` 沒啟動 | `Start-Service VMAuthdService`，並設為自動啟動 |
| NAT 模式的 VM 拿不到 IP ★★★★ | `VMware DHCP Service` 沒跑 | 啟動服務；Linux 上跑 `sudo vmware-networks --start` |
| NAT 模式有 IP 但上不了網 ★★★★ | `VMware NAT Service` 沒跑，或主機防火牆擋住 | 啟動 NAT 服務；見 [[050-01-02-04-guide-Workstation-網路模式]] |
| Linux 主機：`Unable to install all modules` ★★★★ | 缺 `build-essential` 或 headers 版本對不上 | 裝 `linux-headers-$(uname -r)`，確認與 `uname -r` 一致；剛升級核心要先重開機 |
| Linux 主機：模組編譯成功但 `lsmod` 看不到 ★★★★★ | Secure Boot 拒絕載入未簽章模組 | 用 `sign-file` 簽章＋`mokutil --import` 註冊，或關閉 Secure Boot |
| Linux 主機：`dmesg` 出現 `Loading of unsigned module is rejected` ★★★★ | 同上 | 同上 |
| 升級核心後 Workstation 打不開 ★★★★ | 新核心沒有對應模組 | `sudo vmware-modconfig --console --install-all` 後重簽章 |
| 安裝時卡在「正在移除舊版」很久 ★★ | 舊版仍有 VM 在跑或服務卡住 | 先關掉所有 VM 與 Workstation 視窗，必要時重開機再裝 |
| `vmrun` 找不到指令 ★★★ | 安裝時沒勾「Add console tools to PATH」 | 手動把安裝目錄加進 PATH，或用完整路徑呼叫 |
| 找不到快照／複製選單 ★★★★ | 裝到的是 Player 不是 Pro | 改裝 Pro，Player 沒有這些功能 |
| Docker Desktop 關 Hyper-V 後啟動失敗 ★★★ | Docker 的 WSL2 後端依賴虛擬機器平台 | 預期行為；改在 VM 內安裝 Docker Engine |
| 重開機後 `HyperVisorPresent` 又變回 `True` ★★★★ | 網域 GPO 強制啟用 VBS／Credential Guard | 這是政策層問題，**要找資安單位處理，不要自行繞過** |

---

## 安全性注意事項

> [!danger] ★★★★★ 不要用來路不明的安裝檔或授權金鑰
> 破解版 Workstation 是機關資安事件的常見來源。**授權不足就不要裝**，
> 這是採購問題不是技術問題。

> [!danger] ★★★★★ 關閉 Credential Guard 前先問資安單位
> Credential Guard 是防止憑證竊取（如 pass-the-hash）的重要機制。
> 在受管控的機關電腦上關閉它可能違反內部資安基準（見 090 群組 TWGCB 相關章節）。
> **正確做法**：申請一台專用的實驗主機，而不是把日常辦公機的防護關掉。

| 項目 | 風險 | 做法 |
| --- | --- | --- |
| VM 檔案內含正式資料 ★★★★★ | 一個 `.vmdk` 就是整台機器，複製走等於整台被偷 | 實驗機不放正式資料；必要時用 Pro 的 VM 加密功能 |
| 共用實驗主機的多人存取 ★★★ | 他人可直接複製你的 VM | 用作業系統權限保護 VM 目錄；不同人用不同資料夾 |
| VM 直接橋接到機關網段 ★★★★ | 未打補丁的實驗機曝露在正式網路上 | 預設用 NAT 或 Host-only，見 [[050-01-02-04-guide-Workstation-網路模式]] |
| Workstation 自身漏洞 ★★★★ | 曾出現可從 Guest 逃逸到 Host 的漏洞 | 定期更新到原廠支援中的版本；訂閱原廠資安公告 |
| 拖放與共享資料夾 ★★★ | Guest 惡意程式可能沿共享路徑影響 Host | 分析可疑樣本時**關閉**共享資料夾與拖放，見 [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] |
| USB 直通 ★★★ | 隨身碟裡的惡意程式在 Guest／Host 之間流動 | 只在需要時接上，用完立即中斷 |
| 主機關掉 Secure Boot ★★★★ | 降低主機開機鏈的完整性保護 | 優先用 MOK 簽章而不是關 Secure Boot |
| 授權金鑰外流 ★★★ | 金鑰被盜用導致授權稽核缺失 | 金鑰放資產系統，不要寫在共用文件或截圖裡 |

---

## 速查表

### 安裝與移除

| 動作 | Windows | Linux |
| --- | --- | --- |
| 安裝 | 右鍵以管理員執行 `.exe` | `sudo ./VMware-*.bundle` |
| 文字模式安裝 | `/s /v"/qn EULAS_AGREED=1"` | `--console --required --eulas-agreed` |
| 列出已安裝產品 | 控制台 → 程式和功能 | `sudo vmware-installer -l` |
| 移除 | 控制台 → 解除安裝 | `sudo vmware-installer -u vmware-workstation` |
| 重編核心模組 | 不適用 | `sudo vmware-modconfig --console --install-all` |

### Hyper-V 相關（Windows，PowerShell 系統管理員）

| 用途 | 指令 |
| --- | --- |
| 看目前有沒有 Hypervisor ★★★★ | `Get-ComputerInfo -Property "HyperVisorPresent"` |
| 列出啟用中的相關功能 ★★★ | `Get-WindowsOptionalFeature -Online \| Where State -eq Enabled` |
| 關 Hyper-V 角色 ★★★★ | `Disable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -NoRestart` |
| 關虛擬機器平台（WSL2）★★★★ | `Disable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -NoRestart` |
| 關開機載入 Hypervisor ★★★★★ | `bcdedit /set hypervisorlaunchtype off` |
| 恢復 ★★★ | `bcdedit /set hypervisorlaunchtype auto` |
| 備份 WSL2 ★★★★ | `wsl --export <名稱> <路徑.tar>` |
| 還原 WSL2 ★★★ | `wsl --import <名稱> <安裝目錄> <路徑.tar>` |

### 服務名稱

| 服務 | Windows 服務名 | Linux |
| --- | --- | --- |
| 授權／VM 存取 ★★★★ | `VMAuthdService` | `vmware.service` |
| NAT ★★★★ | `VMware NAT Service` | `vmware-networks` |
| DHCP ★★★★ | `VMnetDHCP` | `vmware-networks` |
| USB 仲裁 ★★ | `VMUSBArbService` | `vmware-USBArbitrator` |

### 驗證指令

| 檢查 | 指令 |
| --- | --- |
| CPU 支援虛擬化（Linux）★★★★ | `grep -o -m1 -E 'vmx\|svm' /proc/cpuinfo` |
| 模組是否載入（Linux）★★★★ | `lsmod \| grep -E '^vmmon\|^vmnet'` |
| 虛擬網路狀態（Linux）★★★ | `sudo vmware-networks --status` |
| 虛擬網卡（Linux）★★★ | `ip -brief addr show \| grep vmnet` |
| 虛擬網卡（Windows）★★★ | `Get-NetAdapter \| Where InterfaceDescription -like "*VMware*"` |
| 服務狀態（Windows）★★★★ | `Get-Service VMware*` |
| CLI 可用 ★★★ | `vmrun -T ws list` |
| 核心與 headers 一致（Linux）★★★★ | `uname -r; ls -d /usr/src/linux-headers-$(uname -r)` |
| 已註冊的 MOK ★★★ | `sudo mokutil --list-enrolled` |

### 重要檔案路徑

| 內容 | Windows | Linux |
| --- | --- | --- |
| 程式 ★ | `C:\Program Files\VMware\VMware Workstation\` | `/usr/lib/vmware/` |
| 全域設定 ★★★ | `C:\ProgramData\VMware\` | `/etc/vmware/` |
| 使用者偏好 ★★ | `%APPDATA%\VMware\preferences.ini` | `~/.vmware/preferences` |
| NAT 設定 ★★★★ | `C:\ProgramData\VMware\vmnetnat.conf` | `/etc/vmware/vmnet8/nat/nat.conf` |
| DHCP 設定 ★★★★ | `C:\ProgramData\VMware\vmnetdhcp.conf` | `/etc/vmware/vmnet8/dhcpd/dhcpd.conf` |
| 預設 VM 目錄 ★★★ | `%USERPROFILE%\Documents\Virtual Machines\` | `~/vmware/` |

---

## 練習題

1. 在你自己的電腦上，用**兩種不同方法**確認 CPU 的硬體虛擬化是否已啟用，
   並判斷目前有沒有其他 Hypervisor 佔用它。

2. 假設你的電腦上有一個重要的 WSL2 環境，現在需要關掉 Hyper-V 層來跑 Workstation。
   寫出一份完整的作業程序，包含備份、關閉、驗證、以及事後要如何復原。

3. 在 Linux 主機上模擬「核心升級後 Workstation 打不開」的狀況（不必真的升級，
   直接思考流程即可），列出從發現問題到解決的完整排查步驟。

4. 為你的機關寫一份「Workstation 實驗主機建置檢核表」，
   至少包含系統需求、安裝、驗收六項、以及資安注意事項四大類。

5. 比較「在辦公機上關掉 Credential Guard 來跑 Workstation」與
   「申請一台獨立實驗主機」兩種做法的風險與成本，寫出你的建議與理由。

> [!question]- 練習解答
>
> **1.**
> - 方法一（Windows）：工作管理員 → 效能 → CPU，看右下角「虛擬化」欄位。
> - 方法二（Windows）：PowerShell `Get-ComputerInfo -Property "HyperV*"`，
>   看 `HyperVRequirementVirtualizationFirmwareEnabled`（韌體是否開啟）
>   與 `HyperVisorPresent`（是否已有 Hypervisor 在跑）。
> - Linux：`grep -o -m1 -E 'vmx|svm' /proc/cpuinfo` 有輸出代表可用；
>   另可 `lsmod | grep kvm` 看 KVM 是否已佔用。
> - 判斷：**韌體已啟用但 `HyperVisorPresent : True`** 就是被 Hyper-V 佔走了，
>   不是 BIOS 問題。★★★★
>
> **2.** 程序要點：
> 1. `wsl -l -v` 盤點 → `wsl --shutdown` → `wsl --export` 備份到外部碟
> 2. 通知使用者影響範圍（WSL2、Docker Desktop、Windows 沙箱會停用）
> 3. 確認是否受 GPO 管控；受管控則先報資安單位
> 4. `Disable-WindowsOptionalFeature`（VirtualMachinePlatform、Subsystem-Linux）
> 5. `bcdedit /set hypervisorlaunchtype off`
> 6. 關閉核心隔離的記憶體完整性
> 7. 重開機 → `Get-ComputerInfo -Property "HyperVisorPresent"` 必須是 `False`
> 8. 復原：`bcdedit /set hypervisorlaunchtype auto` ＋ 重新 `Enable-WindowsOptionalFeature`
>    ＋ 重開機 ＋ `wsl --import` 還原備份
>
> **3.** 排查步驟：
> 1. `uname -r` 看目前核心 → 和上次能用時比對
> 2. `lsmod | grep -E '^vmmon|^vmnet'` 確認模組沒載入
> 3. `ls -d /usr/src/linux-headers-$(uname -r)` 確認 headers 存在，
>    不存在就 `sudo apt install linux-headers-$(uname -r)`
> 4. `sudo vmware-modconfig --console --install-all` 重編
> 5. `dmesg | tail` 看有沒有 `Loading of unsigned module is rejected`
> 6. 有的話重跑 `sign-file` 簽 `vmmon` 與 `vmnet`（MOK 已註冊過就不必再 import）
> 7. `modprobe vmmon vmnet` 手動載入驗證
>
> **4.** 檢核表大綱：
> - **系統需求**：CPU 虛擬化已開、RAM ≥16 GB、SSD 剩餘空間 ≥200 GB
> - **安裝**：原廠安裝檔、勾 PATH 與增強鍵盤、關自動更新與資料收集、輸入授權
> - **驗收六項**：服務、虛擬網卡、`vmrun`、虛擬網路編輯器、快照選單、巢狀虛擬化可勾
> - **資安**：VM 存放路徑與權限、預設用 NAT 不橋接、授權金鑰納入資產、
>   Secure Boot 用簽章而非關閉、定期更新版本
>
> **5.** 建議選**獨立實驗主機**：
> - 關掉 Credential Guard 影響的是**日常辦公環境**，那台機器上有真實帳號憑證，
>   風險是持續性的，而且違反資安基準時你要負責 ★★★★★
> - 獨立實驗主機的成本是一次性的硬體費用，而且順便帶來
>   「實驗網路可以和辦公網路隔離」的額外好處
> - 若真的只能用辦公機，至少要有資安單位的書面同意與例外紀錄

---

## 小測驗

Q1. Workstation 屬於 Type-1 還是 Type-2 Hypervisor？這個分類對它的效能與使用情境有什麼影響？

Q2.（是非）Workstation Player 也有快照功能，只是介面藏得比較深。

Q3. 使用者說「工作管理員顯示虛擬化已啟用，但 Workstation 說 VT-x 被停用」。
最可能的原因是什麼？你會先跑哪一行指令來確認？

Q4. 下面這行指令做了什麼？漏掉它會有什麼後果？

```powershell
bcdedit /set hypervisorlaunchtype off
```

Q5.（選擇）以下哪一個 Windows 功能**不會**啟用 Hyper-V 層？
(A) WSL 2　(B) Windows 沙箱　(C) 記憶體完整性　(D) Windows Defender 防火牆

Q6. Linux 主機上跑完 `sudo vmware-modconfig --console --install-all` 顯示成功，
但 `lsmod | grep vmmon` 沒有輸出，`dmesg` 出現
`Loading of unsigned module is rejected`。發生什麼事？怎麼解？

Q7.（簡答）為什麼裝 Workstation 之前建議先重開機（尤其是剛跑完 `apt upgrade`）？

Q8. 本篇「六項驗收檢查」中，哪一項如果失敗會直接影響到後面的 Proxmox VE 與 KVM 章節？為什麼？

Q9.（是非）把虛擬機的硬體版本從 19 升級到 21 之後，還是可以用舊版 Workstation 開啟它。

Q10. 一台受網域 GPO 管控的機關筆電，關掉記憶體完整性並重開機後，
`HyperVisorPresent` 又變回 `True`。你會怎麼處理？

> [!question]- 測驗答案
>
> **Q1.** **Type-2（寄居型）**。它跑在既有的 Windows／Linux 桌面作業系統之上，
> 因此效能會被主機 OS 分掉一部分，但可以隨開隨關、和桌面環境共存，適合當實驗環境。
> ESXi／Proxmox VE 那種直接跑在裸機上的才是 Type-1。
> → 見〈觀念說明〉「Workstation 是 Type-2 Hypervisor」★★★
>
> **Q2.** **錯**。Player **完全沒有**快照與複製功能，不是藏起來。這也是本手冊
> 要求使用 Pro 的主因——沒有快照，「弄壞可還原」的學習方式就不成立。
> → 見〈觀念說明〉Player 與 Pro 對照表 ★★★★★
>
> **Q3.** 最可能是 **Hyper-V 層（含 WSL2、記憶體完整性、Credential Guard）
> 佔走了硬體虛擬化**，不是 BIOS 問題。先跑
> `Get-ComputerInfo -Property "HyperVisorPresent"`，若為 `True` 即確認。
> → 見〈與 Hyper-V／WSL2 共存〉★★★★★
>
> **Q4.** 它把 Windows 開機時**載入 Hypervisor 的行為關掉**。
> 只用 `Disable-WindowsOptionalFeature` 移除功能卻漏掉這一行，
> 開機時仍可能載入 Hypervisor，`HyperVisorPresent` 還是 `True`，
> 巢狀虛擬化依然不可用。這是最常被漏掉的一步。
> → 見〈Windows 主機：安裝步驟〉步驟 1-3 ★★★★
>
> **Q5.** **(D) Windows Defender 防火牆**。防火牆與虛擬化層無關。
> WSL 2 靠虛擬機器平台、Windows 沙箱與記憶體完整性都會啟用 Hyper-V／VBS。
> → 見〈為什麼會衝突〉的功能對照表 ★★★★
>
> **Q6.** **Secure Boot 拒絕載入未簽章的核心模組**。模組編譯成功但無法載入。
> 解法：用 `sign-file` 以自簽金鑰簽 `vmmon` 與 `vmnet`，
> 再 `mokutil --import` 註冊公鑰，重開機時在 MOK Manager 完成 Enroll。
> 不建議直接關閉 Secure Boot。
> → 見〈Secure Boot 的處理〉★★★★★
>
> **Q7.** 因為 `apt upgrade` 可能安裝了新核心，但**尚未重開機時 `uname -r`
> 仍是舊核心**，而 `linux-headers-$(uname -r)` 抓到的是舊版；
> 一旦重開機切到新核心，模組就對不上。先重開機可確保核心與 headers 一致。
> → 見〈Linux 主機：安裝步驟〉步驟 1 ★★★★
>
> **Q8.** **第 ⑥ 項：巢狀虛擬化選項「Virtualize Intel VT-x/EPT or AMD-V/RVI」
> 必須可勾選**。PVE 與 KVM 章節要在 Workstation 的 VM 裡再跑一層虛擬化，
> 沒有這個功能就無法建立巢狀環境。
> → 見〈完整實戰範例〉步驟 8 ★★★★★
>
> **Q9.** **錯**。虛擬硬體版本升級是**單向、不可逆**的，升級後舊版 Workstation
> 就打不開該 VM。要和使用舊版的同事交換 VM，必須保持在共同支援的舊硬體版本。
> → 見〈升級到新的大版本〉★★★★★
>
> **Q10.** 這代表 **VBS／Credential Guard 是由網域 GPO 強制啟用的**，
> 本機關閉會被政策覆寫回去。這是政策層問題：
> 應向資安單位提出申請（說明用途、風險與補償控制），
> 或改申請一台不受該 GPO 管控的獨立實驗主機。
> **不要自行想辦法繞過 GPO**。
> → 見〈常見錯誤與排錯〉最後一列與〈安全性注意事項〉★★★★★

---

## 延伸閱讀

- [[050-01-01-01-guide-虛擬化-虛擬化概念與選型]] — Type-1／Type-2 的完整比較與選型準則
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] — VT-x／EPT 到底做了什麼
- [[050-01-01-03-ref-虛擬化-五平台橫向對照]] — Workstation 與其他四個平台的定位差異
- [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] — 建出第一台實驗機
- [[050-01-02-04-guide-Workstation-網路模式]] — 裝完之後最該搞懂的一件事
- [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] — 巢狀虛擬化與資源配置準則
- [[050-01-05-01-guide-其他虛擬化-VirtualBox定位與取捨]] — 沒有 Workstation 授權時的替代方案
- [[050-01-03-01-svc-PVE-安裝與初始設定]] — 之後要在 Workstation 裡跑的第一個 Type-1 平台
- [[020-01-02-guide-Linux-實驗環境準備與初次登入]] — WSL2 與虛擬機的取捨
