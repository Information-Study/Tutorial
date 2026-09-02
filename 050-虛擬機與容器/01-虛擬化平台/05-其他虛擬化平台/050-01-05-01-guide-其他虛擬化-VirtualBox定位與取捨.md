---
title: "VirtualBox定位與取捨"
desc: "VirtualBox 的定位與適用邊界：基礎套件與 Extension Pack 的授權差異與機關環境的授權風險、與 VMware Workstation 的功能效能對照、精簡安裝與建立 VM 流程、Guest Additions、六種網路模式、共享資料夾、VBoxManage 常用指令，以及「什麼時候該選它、什麼時候絕對不要選它」"
aliases: [VirtualBox, VBox, VBoxManage, Extension Pack, Guest Additions, Oracle VM VirtualBox, vboxsf, vboxdrv]
tags: [群組/虛擬機與容器, 虛擬化/virtualbox, 主題/虛擬化, 主題/授權]
category: 其他虛擬化平台
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-01-01-guide-虛擬化-虛擬化概念與選型]]", "[[050-01-01-03-ref-虛擬化-五平台橫向對照]]"]
updated: 2026-09-02
---

# VirtualBox定位與取捨

> [!note] 本章是補充，不是主線
> ★★★★★ **本手冊的虛擬化主線是 VMware Workstation（桌機端）與 Proxmox VE（機房端）**，
> KVM 為輔。本章（05-其他虛擬化平台）的定位是**補充**，
> 聚焦在**「什麼時候該選它、選了要注意什麼」的選型判斷**，
> 而不是像主線章節那樣寫成完整的逐步操作教學。
> 需要平台之間的全面比較時，請看 [[050-01-01-03-ref-虛擬化-五平台橫向對照]]。

> [!abstract] 這篇你會學到
> - ★★★★★ **VirtualBox 的授權其實有兩層**：基礎套件與 **Extension Pack** 條款不同，
>   **機關環境最大的風險就藏在第二層**
> - ★★★★ VirtualBox 與 **VMware Workstation** 的功能、效能、相容性對照表
> - ★★★ 精簡版的安裝與建立 VM 流程（主線細節看 Workstation 章節，不重複）
> - ★★★★ **Guest Additions** 是什麼、沒裝會怎樣、怎麼確認裝好了
> - ★★★★ **六種網路模式**與 VMware Workstation 三種模式的對照
> - ★★★ **共享資料夾**與 `vboxsf` 群組的權限地雷
> - ★★★★ `VBoxManage` 常用指令（純指令建一台 VM 到能開機）
> - ★★★★★ **什麼時候該選 VirtualBox**：跨平台、免費、教學訓練、與 **Vagrant** 搭配
> - ★★★★★ **什麼時候絕對不要選它**：任何正式服務、機房、需要 HA 或叢集的場合

> [!warning] 未實機驗證
> ★★★★ 本篇的指令與流程以 VirtualBox 7.x 系列在 Windows 11 與 Ubuntu 24.04 桌機上的
> 常見用法撰寫。**版本之間選項名稱會變**（例如 `createhd` 已被 `createmedium` 取代但仍相容），
> 實際執行前請以 `VBoxManage --help <子指令>` 與當前官方文件確認。

> [!danger] ★★★★★ 授權資訊一律以動筆當下重新確認為準
> **本篇不寫具體金額、不引用授權條款原文、不寫「哪一版免費到什麼程度」。**
> VirtualBox 的基礎套件與 Extension Pack 授權條件**不同**，
> 且 Oracle 對 Extension Pack 的商業使用條款曾多次調整。
> **動筆日為 2026-09**，機關要在正式環境（含教育訓練教室、開發測試機）使用時，
> 請由採購或法務單位向 Oracle 或其授權經銷重新確認當期條款，並留下書面紀錄。

---

## 前置知識

- [[050-01-01-01-guide-虛擬化-虛擬化概念與選型]] — ★★★★★ 必讀。
  Type 1／Type 2、hypervisor、快照不是備份等基本概念在那裡定義，本篇不重複
- [[050-01-01-03-ref-虛擬化-五平台橫向對照]] — ★★★★ 五平台的完整對照表與選型決策樹
- [[050-01-01-04-guide-虛擬化-機關選型與授權成本]] — ★★★★ 授權模式的結構性比較與 TCO 試算
- [[050-01-02-01-svc-Workstation-安裝與授權]] — ★★★★ 桌機端主線平台，本篇會不斷與它對照
- [[050-01-02-04-guide-Workstation-網路模式]] — ★★★ 網路模式那一節的對照基準
- [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] — ★★★ 共享資料夾與工具程式的對照基準

> [!tip] ★★★★ 這一篇怎麼用
> 1. **有人問「為什麼不用免費的 VirtualBox 就好」時** → 翻「觀念說明」與「什麼時候不要選它」
> 2. **要在教育訓練教室鋪環境時** → 翻「授權」與「完整實戰範例」
> 3. **已經有人裝了、要評估風險時** → 翻「Extension Pack 在機關環境的授權風險」
> 4. **要把手動點的流程改成腳本時** → 翻「VBoxManage 常用指令」與「速查表」

---

## 觀念說明

### ★★★★ 一、VirtualBox 是什麼、不是什麼

**Oracle VM VirtualBox** 是一套**Type 2（寄居型）**虛擬化軟體：
它裝在既有作業系統（Windows／Linux／macOS）之上，透過一個核心模組
（Linux 上是 `vboxdrv`）取得 CPU 硬體虛擬化能力，再由使用者空間的程序模擬周邊裝置。

| 它是 | 它不是 |
| --- | --- |
| ★★★★ 桌機端的**測試與教學**工具 | ★★★★★ **不是**機房用的虛擬化平台 |
| ★★★★ **跨三大桌機作業系統**的同一套工具 | ★★★ 不是效能最好的桌機虛擬化方案 |
| ★★★★ **Vagrant 的預設 provider**，自動化實驗環境的常見底座 | ★★★★ 不是有叢集、HA、線上遷移的方案 |
| ★★★ 基礎套件為**開源**（GPL 家族授權） | ★★★★★ **Extension Pack 不是開源，授權條件不同** |
| ★★★ 支援快照、複製、OVA 匯入匯出 | ★★★★ 沒有企業級備份機制（無內建排程備份、無備份伺服器） |

> [!note] ★★★★ 為什麼「Type 2」這三個字就決定了它不進機房
> Type 2 的意思是：**宿主作業系統握有實體資源的最終決定權，VirtualBox 只是它的一個程式。**
> 於是：
> - ★★★★★ 宿主機的 **Windows Update／`apt upgrade` 重開機，所有 VM 一起停**
> - ★★★★ 宿主機的**防毒軟體、桌面環境、螢幕保護、休眠**都可能干擾 VM
> - ★★★★ 使用者一登出，背景 VM 的行為就要另外處理（headless 模式）
> - ★★★ 資源被宿主 OS 的排程器與其他應用程式瓜分，效能不可預期
>
> ★★★★★ **正式服務要的是「無人值守、可預期」，Type 2 結構上給不了。**
> 完整說明見 [[050-01-01-01-guide-虛擬化-虛擬化概念與選型]]。

---

### ★★★★★ 二、授權的兩層結構（機關最容易踩的坑）

★★★★★ **這一節是整篇最重要的內容。**

VirtualBox 的安裝檔其實包含**兩個獨立的東西**，授權條件**不一樣**：

| 層 | 內容 | 授權性質 | 機關使用 |
| --- | --- | --- | --- |
| **① 基礎套件（Base Package）** | VirtualBox 主程式、GUI、`VBoxManage`、核心模組、基本的虛擬硬體 | ★★★★ **開源授權（GPL 家族）** | ★★★ 一般而言可自由使用，仍建議留存確認紀錄 |
| **② Extension Pack（擴充套件）** | ★★★★★ **USB 2.0／3.0 控制器、VirtualBox 遠端桌面（VRDE）、磁碟映像加密、NVMe 控制器、Intel 網卡 PXE 開機等** | ★★★★★ **Oracle 專有授權，個人／教育／評估用途與商業用途條款不同** | ★★★★★ **必須先確認，不能預設「反正是免費下載的」** |

> [!danger] ★★★★★ Extension Pack 在機關環境的授權風險
> **這是本篇最需要被記住的一句話：**
>
> ★★★★★ **「可以免費下載」不等於「機關可以免費用」。**
>
> Extension Pack 的下載頁面不會擋你，安裝時也不會要求輸入序號 ——
> **它是「事後稽核制」而不是「事前技術管制」。**
> 這代表：
>
> 1. ★★★★★ **技術上裝得起來，不代表授權上合規。**
>    沒有任何錯誤訊息會提醒你。
> 2. ★★★★★ **機關「內部使用」不必然等於條款所稱的個人用途。**
>    以組織名義、在公務設備上、為公務目的使用，通常會被歸類為與個人使用不同的情形。
>    ★★★★ **這一點務必由採購或法務單位向原廠或授權經銷確認**，不要由工程師自行判斷。
> 3. ★★★★ **稽核時被問到「這套軟體的授權依據是什麼」，答不出來就是缺失。**
>    見 [[100-02-13-guide-維運-資產與授權管理]]。
> 4. ★★★★ 教育訓練教室一次鋪二十台，風險是**乘以二十**。
>
> **不寫具體條款文字、不寫金額**，因為條款會變。
> **動筆日為 2026-09，請於使用前重新確認當期授權條款，並留下書面紀錄。**

> [!tip] ★★★★★ 最省事的作法：不要裝 Extension Pack
> 問自己一個問題：**「我真的需要 Extension Pack 提供的功能嗎？」**
>
> | 你以為需要 | 其實可以 |
> | --- | --- |
> | USB 3.0 直通給 VM | ★★★ 大多數測試情境用**共享資料夾**或**網路傳檔**就夠 |
> | VRDE 遠端桌面連進 VM | ★★★★ 直接在 guest 裡開 **SSH／RDP／VNC**，不必經過 VirtualBox |
> | 磁碟映像加密 | ★★★★ 用 **guest 內的全碟加密**（LUKS／BitLocker），保護層級更完整 |
> | NVMe 虛擬控制器 | ★★★ 測試環境用 SATA／virtio-scsi 就好，效能差異在桌機端不關鍵 |
>
> ★★★★★ **不裝 Extension Pack，授權問題就只剩下基礎套件那一層，風險大幅降低。**

**確認目前有沒有裝 Extension Pack：**

```bash
VBoxManage list extpacks
```

預期輸出（**沒有安裝時**）：

```text
Extension Packs: 0
```

預期輸出（**已安裝時**，版本字串依實際版本而異）：

```text
Extension Packs: 1
Pack no. 0:   Oracle VirtualBox Extension Pack
Version:      7.0.20
Revision:     163906
Edition:
Description:  Oracle Cloud Infrastructure integration, USB 2.0 and USB 3.0 Host Controller, Host Webcam, VirtualBox RDP, PXE ROM, Disk Encryption, NVMe.
VRDE Module:  VBoxVRDP
Usable:       true
Why unusable:
```

★★★★★ **看到 `Extension Packs: 1` 就代表你有一個需要確認授權的元件。**
移除方式：

```bash
VBoxManage extpack uninstall "Oracle VirtualBox Extension Pack"
```

> [!warning] ★★★★ 移除 Extension Pack 之後
> - 已經設定 `--vrde on` 的 VM 會**開不起來**，要先 `VBoxManage modifyvm <名稱> --vrde off`
> - 掛在 USB 2.0／3.0 控制器上的 VM 要改回 USB 1.1 或關閉 USB 控制器
> - ★★★ 移除前先 `VBoxManage list vms` 逐台檢查，不要直接移除了事

---

### ★★★★ 三、與 VMware Workstation 的對照

★★★★★ **本手冊桌機端主線是 VMware Workstation**，所以最實用的比較就是這一張。

**（一）授權與取得**

| 面向 | VirtualBox | VMware Workstation |
| --- | --- | --- |
| 基礎軟體授權 | ★★★★ 開源（GPL 家族） | 商業專有 |
| 取得方式 | 官網免費下載 | ★★★ 依原廠當期政策，須向原廠／經銷確認 |
| ★★★★★ **額外元件授權** | ★★★★★ **Extension Pack 條款不同，須確認** | 單一產品授權，較單純 |
| 稽核複雜度 | ★★★★ **較高**（要分兩層說明） | ★★★ 較低（一份授權文件即可） |
| 供應商鎖定 | 低 | 中 |

> [!note] ★★★★ 一個反直覺的結論
> **「免費」不必然等於「行政成本低」。**
> VirtualBox 的軟體費用是零，但**授權說明、稽核回覆、風險評估的行政工時不是零**；
> 商業授權買下去，稽核時只要出示一份文件。
> ★★★★ 機關選型時**要把行政成本一起算**，見 [[050-01-01-04-guide-虛擬化-機關選型與授權成本]]。

**（二）功能對照**

| 功能 | VirtualBox | VMware Workstation | 說明 |
| --- | --- | --- | --- |
| 快照 | ★★★★ 有，樹狀多分支 | ★★★★ 有，樹狀多分支 | 兩邊都夠用 |
| 複製 VM | ★★★ 完整複製／連結複製 | ★★★★ 完整複製／連結複製 | 概念相同 |
| ★★★★ **Guest 工具程式** | Guest Additions | VMware Tools | 兩邊都**必裝**，見下節 |
| 共享資料夾 | ★★★ 有（`vboxsf`） | ★★★★ 有（HGFS） | ★★★ VMware 在 Windows guest 上較穩定 |
| 拖放與剪貼簿共用 | ★★★ 有 | ★★★★ 有，較穩定 | VirtualBox 在部分桌面環境會失效 |
| 3D／圖形加速 | ★★ 較弱 | ★★★★ **明顯較好** | ★★★★ 要跑圖形工作負載時差別很大 |
| ★★★★ **巢狀虛擬化** | ★★★ 有（`--nested-hw-virt on`） | ★★★★ 有，相容性較好 | 要在 VM 裡再跑 KVM／Hyper-V 時關鍵 |
| USB 直通 | ★★★★★ **USB 2.0／3.0 需 Extension Pack** | ★★★★ 內建 | ★★★★★ 這一列直接牽動授權 |
| 虛擬網路編輯 | ★★★ `VBoxManage` 或 GUI | ★★★★ 內建虛擬網路編輯器 | Workstation 的多網段實驗較好做 |
| 無頭執行 | ★★★★ **原生支援 headless** | ★★★ 需搭配其他機制 | ★★★★ 這是 VirtualBox 少數勝出的項目 |
| ★★★★ **Vagrant 支援** | ★★★★★ **預設 provider，生態最成熟** | ★★★ 需另購外掛或用其他方案 | ★★★★★ 這是選 VirtualBox 最強的理由 |
| macOS 宿主 | ★★★★ 支援（Intel Mac） | ★★ 需改用 VMware Fusion | ★★★ 跨平台一致性 |
| 匯出格式 | OVA／OVF | OVA／OVF、VMX | 兩邊可互通，但要調整硬體設定 |

**（三）效能與穩定性（相對比較，非跑分）**

| 面向 | VirtualBox | VMware Workstation |
| --- | --- | --- |
| CPU 密集工作 | ★★★ 可接受 | ★★★★ 略優 |
| 磁碟 I/O | ★★ **較弱**，大量寫入時明顯 | ★★★★ 較優 |
| 圖形／桌面流暢度 | ★★ 較弱 | ★★★★ **明顯較優** |
| 大量 VM 同時開 | ★★ 較弱 | ★★★ 較優 |
| 與 Windows Hyper-V 共存 | ★★★★★ **歷來最大痛點**，見排錯表 | ★★★★ 較新版本已改善 |
| 版本升級後的相容性 | ★★★ 偶爾需要重裝 Guest Additions | ★★★★ 較穩定 |

> [!warning] ★★★★ 這張表不是跑分結果
> ★★★★ 上面的星號是**相對感受的整理**，不是量測數據。
> 你的硬體、宿主 OS 版本、guest OS、儲存介質都會改變結論。
> **要拿來當採購依據時，請在自己的硬體上實測。**

---

### ★★★★★ 四、什麼時候該選 VirtualBox

| 情境 | 為什麼選它 | 重要度 |
| --- | --- | --- |
| **完全沒有預算，只是要臨時開一台 VM 看看** | 免費、裝了就能用、不必走採購 | ★★★★ |
| **教育訓練／實習生／短期專案的環境** | 一次鋪多台不必逐台買授權（★★★★ 仍須確認 Extension Pack） | ★★★★ |
| **宿主機是 macOS** | ★★★ Workstation 在 macOS 上要改用別的產品線，VirtualBox 一套通吃 | ★★★ |
| **團隊成員的桌機作業系統不一致** | ★★★★ Windows／Linux／macOS 用**同一套指令與同一份 OVA** | ★★★★ |
| **要用 Vagrant 做可重現的實驗環境** | ★★★★★ **VirtualBox 是 Vagrant 生態最成熟的 provider** | ★★★★★ |
| **CI／自動化測試要在本機開臨時 VM** | ★★★★ `VBoxManage` 加 headless 模式很好腳本化 | ★★★★ |
| **只是要驗證一份 OVA 能不能開** | 匯入快、不留痕跡、用完刪掉 | ★★★ |
| **寫文件、錄教學影片** | ★★★ 讀者不必買授權就能照做 | ★★★ |

> [!tip] ★★★★★ 最強的單一理由：Vagrant
> 如果團隊要的是**「一行指令就把一組一模一樣的實驗環境變出來，用完銷毀」**，
> VirtualBox ＋ Vagrant 的組合成熟度是所有桌機方案裡最高的。
> 這種用法下，VirtualBox **不是被當成虛擬化平台在用，而是被當成一個可拋棄的執行器**——
> ★★★★ 這正是它最適合的角色。

---

### ★★★★★ 五、什麼時候絕對不要選 VirtualBox

| 情境 | 為什麼不行 | 重要度 |
| --- | --- | --- |
| **任何對外或對內的正式服務** | ★★★★★ Type 2，宿主重開機服務就停 | ★★★★★ |
| **機房內的伺服器** | ★★★★★ 沒有 IPMI 整合、沒有叢集、沒有 HA | ★★★★★ |
| **需要高可用（HA）或線上遷移** | ★★★★★ 功能不存在 | ★★★★★ |
| **需要集中備份與排程** | ★★★★ 沒有內建備份伺服器概念，得自己刻 | ★★★★ |
| **需要 SLA 或原廠支援** | ★★★★ 支援管道與商業產品不同 | ★★★★ |
| **磁碟 I/O 吃重的資料庫測試** | ★★★ 效能失真，測出來的數字不能用 | ★★★ |
| **需要 GPU 直通做 AI 推論** | ★★★★ 直通支援遠不如 PVE／ESXi | ★★★★ |
| **稽核嚴格、必須清楚交代每一套軟體授權的環境** | ★★★★★ Extension Pack 這一層說明成本高 | ★★★★★ |
| **要跑十台以上 VM 的集中環境** | ★★★★ 這是 PVE 的場合 | ★★★★ |

> [!danger] ★★★★★ 現場最常見的誤用
> **「先用 VirtualBox 開一台跑一下，之後再搬。」**
> ——然後那台「之後再搬」的 VM 跑了三年，變成沒人敢碰的關鍵服務，
> 直到某天宿主機 Windows Update 自動重開機，服務中斷四小時。
>
> ★★★★★ **只要它承載了會有人打電話來問的服務，就已經是正式環境。**
> 正式環境請用 [[050-01-03-01-svc-PVE-安裝與初始設定]]。

---

## 安裝或基礎操作

> [!note] ★★★ 這一節刻意寫得精簡
> 主線平台的安裝流程請看 [[050-01-02-01-svc-Workstation-安裝與授權]]。
> 這裡只寫 **VirtualBox 特有、而且會出事的部分**。

### ★★★ 一、安裝前的三個檢查

**檢查 1：CPU 硬體虛擬化有沒有開**

Linux：

```bash
grep -c -E 'vmx|svm' /proc/cpuinfo
```

預期輸出（有支援時為 CPU 執行緒數，例如）：

```text
8
```

輸出 `0` 代表 BIOS／UEFI 沒開或 CPU 不支援 ——
★★★★ **先進 BIOS 開啟 Intel VT-x／AMD-V，不要浪費時間裝軟體。**

Windows（PowerShell）：

```powershell
Get-ComputerInfo -Property HyperVRequirementVirtualizationFirmwareEnabled
```

預期輸出：

```text
HyperVRequirementVirtualizationFirmwareEnabled
----------------------------------------------
                                          True
```

**檢查 2：★★★★★ Windows 上有沒有其他東西佔用了虛擬化**

```powershell
Get-ComputerInfo -Property HyperVisorPresent
```

預期輸出：

```text
HyperVisorPresent
-----------------
             True
```

★★★★★ **輸出 `True` 代表 Windows 自己已經在跑 hypervisor**
（Hyper-V、WSL2、Windows 沙箱、記憶體完整性／VBS 都會造成這個結果），
VirtualBox 會被迫走相容模式或直接起不來。處理方式見「常見錯誤與排錯」。

**檢查 3：★★★ Linux 上的 Secure Boot**

```bash
mokutil --sb-state
```

預期輸出：

```text
SecureBoot enabled
```

★★★★ Secure Boot 開啟時，**未簽章的 `vboxdrv` 核心模組會載入失敗**，
必須自行簽章並註冊 MOK，或關閉 Secure Boot。這是 Linux 上最常見的第一道關卡。

---

### ★★★ 二、安裝

**Windows**：到官網下載安裝檔，一路下一步即可。
★★★ 安裝過程會**暫時中斷網路**（安裝虛擬網卡驅動），遠端連線操作時要注意。

**Ubuntu／Debian**（★★★ 兩條路線，擇一）：

```bash
# 路線 A：用發行版套件庫（版本較舊，但依賴關係最單純）
sudo apt update
sudo apt install -y virtualbox
```

```bash
# 路線 B：用 Oracle 官方套件庫（版本較新）
# ★★★ 實際的金鑰路徑與 codename 請以官方安裝說明為準，不要照抄舊文件
sudo apt install -y ca-certificates curl gnupg
```

> [!warning] ★★★★ 不要混用兩條路線
> 同時裝了發行版套件與官方套件庫的套件，升級時會互相蓋掉，
> 症狀是「明明裝好了但 `VBoxManage --version` 跟 GUI 版本不一致」。
> ★★★★ **選一條，並在維運文件裡寫清楚選了哪一條。**
> 第三方 APT 套件庫的通用作法見 [[020-02-00-idx-Linux伺服器管理]] 相關章節。

**驗證安裝：**

```bash
VBoxManage --version
```

預期輸出（版本字串依實際安裝而異）：

```text
7.0.20r163906
```

```bash
lsmod | grep vbox
```

預期輸出：

```text
vboxnetadp             28672  0
vboxnetflt             36864  0
vboxdrv               573440  2 vboxnetadp,vboxnetflt
```

★★★★ **`vboxdrv` 沒出現在清單裡，VM 一定開不起來**，先修這個再說。

---

### ★★★ 三、建立一台 VM（GUI 精簡流程）

★★★ 只列決策點，不逐格截圖：

| 步驟 | 選項 | 建議 | 重要度 |
| --- | --- | --- | --- |
| 1 | 名稱與作業系統類型 | ★★★★ **類型要選對**，它決定預設的晶片組、控制器與時鐘設定 | ★★★★ |
| 2 | 記憶體 | ★★★ 不要超過宿主實體記憶體的一半 | ★★★ |
| 3 | 處理器 | ★★★ 不要超過宿主實體核心數；★★★★ 給太多反而更慢 | ★★★★ |
| 4 | 虛擬硬碟 | ★★★ 動態配置（省空間）或固定大小（效能略好） | ★★★ |
| 5 | ★★★★ **EFI 開機** | ★★★★ 新的 Linux／Windows guest 建議勾選 **Enable EFI** | ★★★★ |
| 6 | 顯示記憶體 | ★★★ 桌面環境的 guest 給 128 MB | ★★★ |
| 7 | 網路 | ★★★★ 預設 NAT；需要從宿主連進 guest 時**加第二張 host-only** | ★★★★ |
| 8 | 掛載安裝 ISO | 在「存放裝置」把 ISO 掛到光碟機 | ★★★ |

> [!tip] ★★★★ 一個省時間的習慣
> 裝好 guest OS、更新完、裝好 Guest Additions **之後、開始做實驗之前**，
> 先拍一個名為 `baseline` 的快照。
> ★★★★★ 之後每次實驗做壞了就 restore 回 `baseline`，
> 不必重裝作業系統。這個習慣一年能省下幾十小時。

---

### ★★★★ 四、Guest Additions（必裝）

**Guest Additions 是什麼**：一組裝在 **guest 作業系統裡面**的驅動程式與服務，
對應 VMware 的 VMware Tools。★★★★ **不裝的話下面這些全都不能用或很難用**：

| 功能 | 沒裝 Guest Additions 時 | 重要度 |
| --- | --- | --- |
| 螢幕解析度自動調整 | ★★★★ 卡在固定小視窗，無法拉伸 | ★★★★ |
| 滑鼠指標整合 | ★★★★ 要按 Host Key 才能把滑鼠抓出來 | ★★★★ |
| 共享資料夾 | ★★★★★ **完全不能用**（沒有 `vboxsf` 驅動） | ★★★★★ |
| 剪貼簿共用 | ★★★ 不能用 | ★★★ |
| 拖放檔案 | ★★★ 不能用 | ★★★ |
| 時鐘同步 | ★★★★ guest 時間會飄，日誌時間對不上 | ★★★★ |
| 正常關機（ACPI） | ★★★ 部分 guest 不回應關機訊號 | ★★★ |

**Linux guest 安裝流程：**

```bash
# 1. 先裝編譯所需套件（Ubuntu／Debian）
sudo apt update
sudo apt install -y build-essential dkms linux-headers-$(uname -r)
```

```bash
# 2. 在 VirtualBox 選單點「裝置 → 插入 Guest Additions CD 映像」後，於 guest 內掛載
sudo mkdir -p /mnt/cdrom
sudo mount /dev/cdrom /mnt/cdrom
```

預期輸出：

```text
mount: /mnt/cdrom: WARNING: source write-protected, mounted read-only.
```

★★★ 這行 WARNING 是正常的，光碟本來就唯讀。

```bash
# 3. 執行安裝程式
sudo /mnt/cdrom/VBoxLinuxAdditions.run
```

預期輸出（節錄）：

```text
Verifying archive integrity...  100%   MD5 checksums are OK. All good.
Uncompressing VirtualBox 7.0.20 Guest Additions for Linux  100%
VirtualBox Guest Additions installer
Copying additional installer modules ...
Installing additional modules ...
VirtualBox Guest Additions: Starting.
```

```bash
# 4. 重開機後驗證
sudo reboot
```

```bash
lsmod | grep vboxguest
```

預期輸出：

```text
vboxguest             450560  2 vboxsf
```

★★★★ **看到 `vboxguest` 才算裝成功。**

> [!info]- Rocky／AlmaLinux（RHEL 系）對照
> 套件名稱不同：
>
> ```bash
> sudo dnf install -y epel-release
> sudo dnf install -y gcc make perl kernel-devel-$(uname -r) kernel-headers-$(uname -r) dkms
> sudo /mnt/cdrom/VBoxLinuxAdditions.run
> ```
>
> ★★★★ RHEL 系最常見的失敗原因是 **`kernel-devel` 的版本與執行中的核心不一致**：
>
> ```bash
> uname -r
> rpm -q kernel-devel
> ```
>
> 兩者對不上就先 `sudo dnf update kernel*` 再重開機。

> [!warning] ★★★★ 核心更新後要重編模組
> Linux guest 每次核心更新後，Guest Additions 的模組需要重新編譯。
> 有裝 `dkms` 通常會自動處理；沒裝的話會出現「共享資料夾突然掛不上」的症狀。
> ★★★★ **裝 `dkms` 是必要的，不是選配。**

---

### ★★★★ 五、六種網路模式（與 VMware Workstation 對照）

★★★★★ **這是 VirtualBox 最常被搞混的部分。**
VMware Workstation 主要是三種（NAT／Bridged／Host-only），VirtualBox 有六種。

| VirtualBox 模式 | guest 能上外網 | 宿主連得到 guest | guest 之間互通 | 區網其他機器連得到 guest | 對應 Workstation | 重要度 |
| --- | --- | --- | --- | --- | --- | --- |
| **NAT** | ✅ | ❌（★★★★ 需 port forwarding） | ❌ | ❌ | NAT | ★★★★★ |
| **NAT Network** | ✅ | ❌（需 port forwarding） | ✅ | ❌ | ★★★ 無直接對應 | ★★★★ |
| **Bridged Adapter** | ✅ | ✅ | ✅ | ✅ | Bridged | ★★★★★ |
| **Internal Network** | ❌ | ❌ | ✅ | ❌ | ★★★ 自訂 VMnet（不接主機） | ★★★ |
| **Host-only Adapter** | ❌ | ✅ | ✅ | ❌ | Host-only | ★★★★★ |
| **Generic Driver** | 依驅動 | 依驅動 | 依驅動 | 依驅動 | 無 | ★ |

> [!note] ★★★★★ 兩個最關鍵的差異（背下來）
> 1. ★★★★★ **NAT 與 NAT Network 的差別是「guest 之間能不能互通」。**
>    多台 VM 要組實驗網路又要能上網，**必須用 NAT Network**，不是 NAT。
>    這是最常見的設定錯誤。
> 2. ★★★★★ **Host-only 不能上外網。**
>    很多人設了 host-only 之後抱怨「VM 不能 `apt update`」——
>    ★★★★ **標準解法是給 VM 兩張網卡：nic1 走 NAT 上網、nic2 走 host-only 給宿主連線。**

**★★★★ 標準雙網卡設定（最常用的組合）：**

```bash
VBoxManage modifyvm "lab-ubuntu" --nic1 nat --nic2 hostonly --hostonlyadapter2 vboxnet0
```

**檢視宿主上的 host-only 介面：**

```bash
VBoxManage list hostonlyifs
```

預期輸出（節錄）：

```text
Name:            vboxnet0
GUID:            786f6276-656e-4074-8000-0a0027000000
DHCP:            Disabled
IPAddress:       192.168.56.1
NetworkMask:     255.255.255.0
Status:          Up
```

★★★★ **`192.168.56.x` 是 VirtualBox host-only 的傳統網段**，看到它就知道是 host-only。

**NAT 的 port forwarding（★★★★ 只用 NAT 時要連 SSH 的唯一辦法）：**

```bash
# 把宿主的 2222 埠轉到 guest 的 22 埠
VBoxManage modifyvm "lab-ubuntu" --natpf1 "ssh,tcp,127.0.0.1,2222,,22"
```

之後從宿主連線：

```bash
ssh -p 2222 ops@127.0.0.1
```

★★★★ **綁定 `127.0.0.1` 而不是留空**，否則區網其他機器也連得到這個轉發埠，是資安缺口。

**刪除 port forwarding 規則：**

```bash
VBoxManage modifyvm "lab-ubuntu" --natpf1 delete ssh
```

**建立 NAT Network（多台 VM 互通又要上網時）：**

```bash
VBoxManage natnetwork add --netname labnet --network "10.10.10.0/24" --enable --dhcp on
VBoxManage modifyvm "lab-ubuntu" --nic1 natnetwork --nat-network1 labnet
```

驗證：

```bash
VBoxManage natnetwork list
```

預期輸出（節錄）：

```text
NAT Networks:

Name:         labnet
Network:      10.10.10.0/24
Gateway:      10.10.10.1
DHCP Server:  Yes
Enabled:      Yes
```

> [!info]- 與 [[050-01-02-04-guide-Workstation-網路模式]] 的對照重點
> - ★★★★ Workstation 有**虛擬網路編輯器**可以圖形化建立多個 VMnet；
>   VirtualBox 沒有等價的整合介面，多網段實驗要靠 `VBoxManage` 建 Internal Network。
> - ★★★★ Workstation 的 NAT 網段可以在編輯器裡直接改；
>   VirtualBox 的 NAT 網段是**每台 VM 各自獨立**的，這正是 NAT 模式下 VM 互相看不到的原因。
> - ★★★ 兩邊的 Bridged 行為一致：**guest 直接出現在實體區網上**，
>   ★★★★ 在機關網路裡用 Bridged 前要先確認**有沒有 DHCP 位址管控或 802.1X**，
>   見 [[090-05-13-guide-資安設備-網路存取控制NAC與802.1X]]。

---

### ★★★ 六、共享資料夾

**在宿主上加一個共享資料夾：**

```bash
VBoxManage sharedfolder add "lab-ubuntu" \
  --name share \
  --hostpath /home/ops/vmshare \
  --automount
```

★★★ `--name` 是**共享名稱**，不是路徑；guest 端會用這個名稱掛載。

**Linux guest 端（★★★★ 權限地雷在這裡）：**

```bash
# 自動掛載會掛在 /media/sf_share，但只有 vboxsf 群組成員讀得到
ls -ld /media/sf_share
```

預期輸出：

```text
drwxrwx--- 1 root vboxsf 4096 Sep  2 10:12 /media/sf_share
```

★★★★★ **群組是 `vboxsf`，其他使用者是 `---`。**
一般使用者存取會得到 `Permission denied`。解法：

```bash
sudo usermod -aG vboxsf $USER
```

★★★★ **改完群組必須重新登入（或重開機）才會生效**，
`groups` 指令沒看到 `vboxsf` 就是還沒生效：

```bash
groups
```

預期輸出：

```text
ops adm cdrom sudo dip plugdev vboxsf
```

**手動掛載（不用 automount 時）：**

```bash
sudo mkdir -p /mnt/share
sudo mount -t vboxsf -o uid=$(id -u),gid=$(id -g) share /mnt/share
```

> [!danger] ★★★★★ 共享資料夾不是備份，也不該放正式資料
> - ★★★★★ 共享資料夾**跟著宿主機走**，宿主機壞了資料一起沒
> - ★★★★ guest 在共享資料夾上跑資料庫或大量小檔 I/O，**效能極差且容易鎖檔損毀**
> - ★★★★ 有些程式的 `mmap`／檔案鎖行為在 `vboxsf` 上不正確，會出現難以重現的怪錯
> - ★★★ **共享資料夾只用來傳檔案，不用來當工作目錄。**

---

## 進階應用

### ★★★★ 一、`VBoxManage`：用純指令建一台 VM

★★★★★ **會用 `VBoxManage` 才談得上自動化。** 以下是完整的最小流程。

```bash
VM=lab-ubuntu
ISO=/home/ops/iso/ubuntu-24.04-live-server-amd64.iso
DISK=/home/ops/VirtualBox VMs/$VM/$VM.vdi
```

**步驟 1：建立並註冊 VM**

```bash
VBoxManage createvm --name "$VM" --ostype Ubuntu_64 --register
```

預期輸出：

```text
Virtual machine 'lab-ubuntu' is created and registered.
UUID: 8f2c1a4e-3b5d-4c7a-9e1f-2d6b8c0a5e31
Settings file: '/home/ops/VirtualBox VMs/lab-ubuntu/lab-ubuntu.vbox'
```

★★★ 看不到 `--ostype` 該填什麼時：

```bash
VBoxManage list ostypes | grep -i ubuntu
```

**步驟 2：設定硬體規格**

```bash
VBoxManage modifyvm "$VM" \
  --memory 4096 \
  --cpus 2 \
  --vram 128 \
  --firmware efi \
  --graphicscontroller vmsvga \
  --ioapic on \
  --rtcuseutc on \
  --nic1 nat \
  --nic2 hostonly --hostonlyadapter2 vboxnet0
```

★★★★ `--rtcuseutc on` 對 Linux guest 很重要，否則時區會差好幾小時。

**步驟 3：建立虛擬磁碟**

```bash
VBoxManage createmedium disk --filename "$DISK" --size 40960 --format VDI
```

預期輸出：

```text
0%...10%...20%...30%...40%...50%...60%...70%...80%...90%...100%
Medium created. UUID: 3c9f7b21-8a4e-4d16-b0c3-5f7e2a91d4b8
```

★★★ `--size` 單位是 **MB**，40960 就是 40 GB。

**步驟 4：加控制器並掛載磁碟與 ISO**

```bash
VBoxManage storagectl "$VM" --name "SATA" --add sata --controller IntelAhci --portcount 2
VBoxManage storageattach "$VM" --storagectl "SATA" --port 0 --device 0 --type hdd --medium "$DISK"
VBoxManage storageattach "$VM" --storagectl "SATA" --port 1 --device 0 --type dvddrive --medium "$ISO"
```

**步驟 5：啟動**

```bash
VBoxManage startvm "$VM" --type gui
```

或無頭啟動（★★★★ 伺服器情境或腳本情境用這個）：

```bash
VBoxManage startvm "$VM" --type headless
```

預期輸出：

```text
Waiting for VM "lab-ubuntu" to power on...
VM "lab-ubuntu" has been successfully started.
```

**步驟 6：查狀態**

```bash
VBoxManage list runningvms
```

預期輸出：

```text
"lab-ubuntu" {8f2c1a4e-3b5d-4c7a-9e1f-2d6b8c0a5e31}
```

---

### ★★★ 二、快照、複製與匯出

**快照：**

```bash
VBoxManage snapshot "$VM" take "baseline" --description "OS 安裝完、Guest Additions 已裝"
VBoxManage snapshot "$VM" list
VBoxManage snapshot "$VM" restore "baseline"
VBoxManage snapshot "$VM" delete "baseline"
```

`list` 預期輸出：

```text
Name: baseline (UUID: 5a1b3c7d-2e4f-4a89-b6c1-9d0e8f2a3b4c)
   Name: after-nginx (UUID: 7d2e4f6a-1b3c-4d5e-8f90-a1b2c3d4e5f6) *
```

★★★ 尾端的 `*` 代表目前所在的節點。

> [!danger] ★★★★★ 快照不是備份
> 快照存在同一顆實體磁碟、同一台宿主機上。
> ★★★★★ **磁碟壞了、宿主機被加密勒索，快照跟著一起沒。**
> 而且**快照留越久、鏈越長，效能越差、還原越慢**。
> 完整說明見 [[050-01-02-03-guide-Workstation-快照與複製]] 與
> [[090-03-04-guide-應用安全-備份災難復原與入侵應變]]。

**複製：**

```bash
# 完整複製（獨立，佔空間）
VBoxManage clonevm "$VM" --name "lab-ubuntu-2" --mode all --register

# 連結複製（快、省空間，但依賴母機）
VBoxManage clonevm "$VM" --name "lab-ubuntu-3" --snapshot "baseline" --options link --register
```

★★★★ **連結複製的母機不能刪、不能改**，否則所有子機一起壞。
教育訓練教室鋪環境時很好用，但要在文件裡寫清楚依賴關係。

**匯出與匯入 OVA（★★★★ 跨平台交換的標準作法）：**

```bash
VBoxManage export "$VM" -o /home/ops/export/lab-ubuntu.ova \
  --vsys 0 --product "Lab Ubuntu" --vendor "IT Dept"
```

預期輸出：

```text
0%...10%...20%...30%...40%...50%...60%...70%...80%...90%...100%
Successfully exported 1 machine(s).
```

```bash
VBoxManage import /home/ops/export/lab-ubuntu.ova --vsys 0 --vmname "lab-ubuntu-restored"
```

> [!tip] ★★★★ OVA 是 VirtualBox 與 VMware／PVE 之間的橋
> - ★★★★ VirtualBox 匯出的 OVA **可以匯進 VMware Workstation 與 Proxmox VE**
> - ★★★★ 但匯進去之後**一定要調整**：移除 Guest Additions、
>   檢查磁碟控制器類型、檢查網卡型號、**檢查網卡介面名稱有沒有變**
> - ★★★★★ **網卡介面名稱改變會讓 Linux guest 開機後沒有網路**，
>   這是所有跨平台遷移最常見的中斷原因

---

### ★★★★ 三、Headless 與遠端操作

★★★★ VirtualBox 少數勝過 Workstation 的地方就是**原生的 headless 模式**。

```bash
# 無頭啟動
VBoxManage startvm "$VM" --type headless

# 正常關機（送 ACPI 訊號，等同按電源鍵）
VBoxManage controlvm "$VM" acpipowerbutton

# 強制斷電（★★★★★ 等同拔插頭，可能損毀檔案系統）
VBoxManage controlvm "$VM" poweroff

# 存檔暫停（把記憶體狀態存到磁碟）
VBoxManage controlvm "$VM" savestate
```

> [!danger] ★★★★★ `poweroff` 是不可逆操作
> `VBoxManage controlvm <VM> poweroff` **等同直接拔電源**：
> guest 裡未寫入的資料會遺失，檔案系統可能需要 fsck。
> ★★★★★ **除非 guest 已經完全卡死，否則一律先用 `acpipowerbutton`。**

**取得 guest 的 IP（★★★★ 需已裝 Guest Additions）：**

```bash
VBoxManage guestproperty get "$VM" "/VirtualBox/GuestInfo/Net/1/V4/IP"
```

預期輸出：

```text
Value: 192.168.56.101
```

輸出 `No value set!` 代表 Guest Additions 沒裝或還沒啟動完成。

---

### ★★★★★ 四、與 Vagrant 搭配

★★★★★ **這是選 VirtualBox 最有說服力的理由。**

Vagrant 用一份 `Vagrantfile` 描述整組環境，`vagrant up` 就把 VM 全部建好。

```ruby
# Vagrantfile（★★★ 這是 Ruby 語法的設定檔）
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  config.vm.define "web" do |web|
    web.vm.hostname = "web01"
    web.vm.network "private_network", ip: "192.168.56.11"
    web.vm.provider "virtualbox" do |vb|
      vb.memory = 2048
      vb.cpus = 2
    end
  end

  config.vm.define "db" do |db|
    db.vm.hostname = "db01"
    db.vm.network "private_network", ip: "192.168.56.12"
  end
end
```

```bash
vagrant up
vagrant ssh web
vagrant destroy -f
```

★★★★ **價值不在「省了幾個滑鼠點擊」，而在於**：

| 好處 | 說明 | 重要度 |
| --- | --- | --- |
| **環境可重現** | 每個人跑出來的環境一模一樣 | ★★★★★ |
| **環境進版控** | `Vagrantfile` 進 git，環境變更有紀錄 | ★★★★ |
| **可拋棄** | `destroy` 之後重來，不怕玩壞 | ★★★★ |
| **跨作業系統** | 同一份檔案在 Windows／Linux／macOS 都能跑 | ★★★★ |

搭配 git 的作法見 [[080-03-01-guide-發布-環境分離與設定管理]]。

---

### ★★★ 五、效能調校要點

| 項目 | 建議 | 重要度 |
| --- | --- | --- |
| CPU 數量 | ★★★★ **不要超過實體核心數**，超配在 Type 2 上是負效益 | ★★★★ |
| 記憶體 | ★★★★ 總和不超過宿主實體記憶體的 **50～60%** | ★★★★ |
| 磁碟位置 | ★★★★ **放 SSD／NVMe**，VirtualBox 的 I/O 本來就弱，放機械碟等於自殺 | ★★★★ |
| 主機 I/O 快取 | ★★★ 大量寫入時關閉可避免資料不一致風險 | ★★★ |
| 顯示卡控制器 | ★★★ Linux guest 用 `vmsvga`，Windows guest 用 `vboxsvga` | ★★★ |
| 巢狀虛擬化 | `--nested-hw-virt on`（★★★ 要在 VM 裡跑 KVM／Docker Desktop 時） | ★★★ |
| 半虛擬化介面 | `--paravirtprovider kvm`（Linux guest）／`hyperv`（Windows guest） | ★★★ |
| 防毒軟體 | ★★★★★ **把 VM 目錄加入排除清單**，否則每次磁碟寫入都被掃 | ★★★★★ |
| 宿主電源計畫 | ★★★ Windows 上設成「高效能」，避免降頻 | ★★★ |

```bash
VBoxManage modifyvm "$VM" --nested-hw-virt on --paravirtprovider kvm
```

---

## 完整實戰範例

### 情境

★★★★ 資訊室要在**下週的內部教育訓練**準備十台一模一樣的 Linux 練習環境。
講師會發一個 OVA 檔，學員在自己的筆電（Windows 與 macOS 混雜）匯入就能上課。
課程內容是 Linux 基礎指令與 Nginx 安裝，**不涉及 USB 裝置、不需要遠端桌面**。

★★★★★ **關鍵前提：因為不需要 USB 與 VRDE，所以決定不安裝 Extension Pack，**
**把授權風險限制在基礎套件那一層。**

**環境**：講師的 Ubuntu 24.04 桌機、VirtualBox 7.x、Ubuntu Server 24.04 ISO。

---

### 步驟 1：確認環境與授權狀態 ★★★★★

```bash
VBoxManage --version
```

```text
7.0.20r163906
```

```bash
VBoxManage list extpacks
```

```text
Extension Packs: 0
```

★★★★★ **確認 `Extension Packs: 0`，這一步要截圖存進採購／稽核資料夾。**
若不是 0，先評估是否移除：

```bash
VBoxManage extpack uninstall "Oracle VirtualBox Extension Pack"
```

```bash
grep -c -E 'vmx|svm' /proc/cpuinfo
```

```text
16
```

```bash
lsmod | grep vboxdrv
```

```text
vboxdrv               573440  2 vboxnetadp,vboxnetflt
```

★★★★ 三項都通過才往下走。

---

### 步驟 2：準備 host-only 網路 ★★★★

```bash
VBoxManage list hostonlyifs
```

沒有任何輸出代表還沒建立：

```bash
VBoxManage hostonlyif create
```

```text
0%...10%...20%...30%...40%...50%...60%...70%...80%...90%...100%
Interface 'vboxnet0' was successfully created
```

```bash
VBoxManage hostonlyif ipconfig vboxnet0 --ip 192.168.56.1 --netmask 255.255.255.0
VBoxManage list hostonlyifs
```

```text
Name:            vboxnet0
IPAddress:       192.168.56.1
NetworkMask:     255.255.255.0
Status:          Up
```

---

### 步驟 3：用指令建立範本 VM ★★★★

```bash
VM=training-base
ISO=/home/ops/iso/ubuntu-24.04-live-server-amd64.iso
BASE="$HOME/VirtualBox VMs"

VBoxManage createvm --name "$VM" --ostype Ubuntu_64 --register
```

```text
Virtual machine 'training-base' is created and registered.
UUID: b7d3e9a1-4c2f-4e88-91a5-6f0b3c7d2e14
Settings file: '/home/ops/VirtualBox VMs/training-base/training-base.vbox'
```

```bash
VBoxManage modifyvm "$VM" \
  --memory 2048 --cpus 2 --vram 16 \
  --firmware efi --graphicscontroller vmsvga \
  --ioapic on --rtcuseutc on --audio-driver none \
  --nic1 nat --nic2 hostonly --hostonlyadapter2 vboxnet0
```

★★★ 教學用的 server guest **不需要顯示記憶體與音效**，`--vram 16` 與 `--audio-driver none`
可以省下宿主資源。

```bash
VBoxManage createmedium disk --filename "$BASE/$VM/$VM.vdi" --size 20480 --format VDI
```

```text
0%...100%
Medium created. UUID: 4e8a1c6b-9d2f-4a37-b5e0-1c8d7f2a9b03
```

```bash
VBoxManage storagectl "$VM" --name "SATA" --add sata --controller IntelAhci --portcount 2
VBoxManage storageattach "$VM" --storagectl "SATA" --port 0 --device 0 --type hdd \
  --medium "$BASE/$VM/$VM.vdi"
VBoxManage storageattach "$VM" --storagectl "SATA" --port 1 --device 0 --type dvddrive \
  --medium "$ISO"
```

**驗證設定：**

```bash
VBoxManage showvminfo "$VM" | grep -E 'Memory size|Number of CPUs|NIC 1|NIC 2|Firmware'
```

預期輸出：

```text
Memory size:     2048MB
Number of CPUs:  2
Firmware:        EFI
NIC 1:           MAC: 080027A1B2C3, Attachment: NAT, ...
NIC 2:           MAC: 0800274D5E6F, Attachment: Host-only Interface 'vboxnet0', ...
```

---

### 步驟 4：安裝作業系統 ★★★

```bash
VBoxManage startvm "$VM" --type gui
```

在 guest 裡完成 Ubuntu Server 安裝，重點設定：

| 項目 | 值 | 說明 |
| --- | --- | --- |
| 主機名稱 | `training` | ★★★ 學員之後自己改 |
| 使用者 | `student` | ★★★★ 密碼要在講義上寫清楚 |
| OpenSSH Server | ★★★★ **勾選安裝** | 學員要從宿主 SSH 進來 |
| 磁碟配置 | 整顆使用 LVM | ★★★ 預設即可 |

安裝完成後**先移除 ISO**：

```bash
VBoxManage storageattach "$VM" --storagectl "SATA" --port 1 --device 0 \
  --type dvddrive --medium emptydrive
```

★★★★ **忘了移除 ISO，匯出的 OVA 會把整個 ISO 打包進去，檔案大好幾 GB。**

---

### 步驟 5：guest 內的初始化 ★★★★

```bash
# 在 guest 裡執行
sudo apt update && sudo apt -y upgrade
sudo apt install -y build-essential dkms linux-headers-$(uname -r)
```

掛載並安裝 Guest Additions：

```bash
sudo mount /dev/cdrom /mnt
sudo /mnt/VBoxLinuxAdditions.run
sudo reboot
```

重開機後驗證：

```bash
lsmod | grep vboxguest
```

```text
vboxguest             450560  2 vboxsf
```

設定 host-only 網卡的固定 IP（Ubuntu netplan）：

```yaml
# /etc/netplan/99-hostonly.yaml
network:
  version: 2
  ethernets:
    enp0s8:
      dhcp4: false
      addresses: [192.168.56.101/24]
```

```bash
sudo chmod 600 /etc/netplan/99-hostonly.yaml
sudo netplan apply
ip -4 addr show enp0s8
```

預期輸出：

```text
3: enp0s8: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...
    inet 192.168.56.101/24 brd 192.168.56.255 scope global enp0s8
```

★★★★ **`enp0s8` 是第二張網卡的名稱**，如果不同請以 `ip link` 實際輸出為準。

---

### 步驟 6：清理後拍快照 ★★★★

★★★★ **匯出前一定要清理**，否則每個學員的 VM 都帶著講師的痕跡：

```bash
# 在 guest 裡執行
sudo apt clean
sudo rm -f /etc/ssh/ssh_host_*      # ★★★★ 移除 SSH 主機金鑰，開機時會重新產生
sudo truncate -s 0 /var/log/*.log
history -c
sudo cloud-init clean --logs 2>/dev/null || true
sudo shutdown -h now
```

> [!danger] ★★★★★ 不清 SSH 主機金鑰的後果
> 十台 VM 用**同一組 SSH host key**，等於十台機器在網路上宣稱自己是同一台。
> ★★★★★ 這在教學環境會造成 `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!` 滿天飛，
> 在正式環境則是明確的資安缺失。
> 見 [[090-02-06-guide-防護-遠端存取安全]]。

關機後拍快照：

```bash
VBoxManage snapshot "$VM" take "clean-baseline" \
  --description "OS 更新完、GA 已裝、已清理，可供匯出"
VBoxManage snapshot "$VM" list
```

```text
Name: clean-baseline (UUID: 9a1f4b7c-3d5e-4826-9f0a-1b2c3d4e5f60) *
```

---

### 步驟 7：匯出 OVA ★★★★

```bash
mkdir -p /home/ops/export
VBoxManage export "$VM" -o /home/ops/export/training-2026Q3.ova \
  --vsys 0 \
  --product "IT Training Lab" \
  --vendor "資訊室" \
  --version "2026Q3"
```

```text
0%...10%...20%...30%...40%...50%...60%...70%...80%...90%...100%
Successfully exported 1 machine(s).
```

```bash
ls -lh /home/ops/export/training-2026Q3.ova
sha256sum /home/ops/export/training-2026Q3.ova | tee /home/ops/export/training-2026Q3.ova.sha256
```

預期輸出：

```text
-rw-rw-r-- 1 ops ops 2.1G Sep  2 15:40 /home/ops/export/training-2026Q3.ova
3f9a1c...（64 字元）  /home/ops/export/training-2026Q3.ova
```

★★★★ **一定要附 SHA-256 檢查碼**，學員下載後可自行驗證檔案完整性。

---

### 步驟 8：驗證匯入流程 ★★★★★

★★★★★ **講師必須自己先匯入一次**，不能假設「匯出成功就一定匯得進去」。

```bash
VBoxManage import /home/ops/export/training-2026Q3.ova \
  --vsys 0 --vmname "training-verify"
```

```text
0%...100%
Successfully imported the appliance.
```

```bash
VBoxManage startvm "training-verify" --type headless
```

```text
Waiting for VM "training-verify" to power on...
VM "training-verify" has been successfully started.
```

等 30 秒後從宿主測試連線：

```bash
ssh student@192.168.56.101
```

```text
student@192.168.56.101's password:
Welcome to Ubuntu 24.04 LTS (GNU/Linux 6.8.0-41-generic x86_64)
student@training:~$
```

★★★★ 在 guest 裡再測一次對外網路：

```bash
ping -c 2 1.1.1.1
sudo apt update
```

---

### 完成確認 ★★★★★

| # | 檢查項 | 通過標準 | 重要度 |
| --- | --- | --- | --- |
| 1 | `VBoxManage list extpacks` | ★★★★★ 顯示 `Extension Packs: 0` | ★★★★★ |
| 2 | OVA 檔案大小 | ★★★★ 沒有異常膨脹（表示 ISO 已卸載） | ★★★★ |
| 3 | SHA-256 檢查碼 | ★★★★ 已產生並隨檔案發布 | ★★★★ |
| 4 | 匯入測試 | ★★★★★ 講師已在另一台機器實際匯入成功 | ★★★★★ |
| 5 | SSH 連線 | ★★★★ 從宿主經 `192.168.56.101` 連得進去 | ★★★★ |
| 6 | 對外網路 | ★★★★ guest 內 `apt update` 成功 | ★★★★ |
| 7 | SSH host key | ★★★★★ 已清除，開機時重新產生 | ★★★★★ |
| 8 | Guest Additions | ★★★★ `lsmod \| grep vboxguest` 有輸出 | ★★★★ |
| 9 | 授權紀錄 | ★★★★★ 已把「未安裝 Extension Pack」寫入教育訓練紀錄 | ★★★★★ |
| 10 | 講義 | ★★★ 已寫明 VirtualBox 版本、帳號密碼、匯入步驟 | ★★★ |

---

## 常見錯誤與排錯

| # | 現象 | 原因 | 解法 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | `VT-x is not available (VERR_VMX_NO_VMX)` | ★★★★ BIOS 未開啟硬體虛擬化，或被其他 hypervisor 佔用 | 進 BIOS 開啟 VT-x／AMD-V；Windows 上檢查 `HyperVisorPresent` | ★★★★★ |
| 2 | `VT-x is disabled in the BIOS for all CPU modes (VERR_VMX_MSR_ALL_VMX_DISABLED)` | ★★★★ BIOS 中虛擬化被明確停用 | 進 BIOS 啟用後**完全斷電重開**（僅重開機有時不生效） | ★★★★ |
| 3 | `VERR_VMX_IN_VMX_ROOT_MODE` 或 VM 起不來 | ★★★★★ **Windows 的 Hyper-V／WSL2／VBS 已佔用虛擬化** | 停用 Hyper-V 相關功能與記憶體完整性後重開機；或改用支援共存的較新版本 | ★★★★★ |
| 4 | `Kernel driver not installed (rc=-1908)` | ★★★★ Linux 上 `vboxdrv` 沒載入 | `sudo /sbin/vboxconfig` 重建模組；檢查 `dmesg \| tail` | ★★★★★ |
| 5 | `modprobe vboxdrv failed. Please use 'dmesg' to find out why` 且 dmesg 顯示 `Required key not available` | ★★★★★ **Secure Boot 拒絕未簽章模組** | 自行簽章模組並註冊 MOK，或關閉 Secure Boot | ★★★★★ |
| 6 | 核心更新後 VM 全部開不起來 | ★★★★ 核心模組沒有隨新核心重編 | 裝 `dkms` 與對應的 `linux-headers`，再 `sudo /sbin/vboxconfig` | ★★★★ |
| 7 | guest 內 `mount: unknown filesystem type 'vboxsf'` | ★★★★★ **Guest Additions 沒裝或沒編成功** | 重裝 Guest Additions；確認 `lsmod \| grep vboxsf` | ★★★★★ |
| 8 | 共享資料夾存取 `Permission denied` | ★★★★ 使用者不在 `vboxsf` 群組 | `sudo usermod -aG vboxsf $USER` 後**重新登入** | ★★★★ |
| 9 | 複製 `.vdi` 檔後匯入報 `Cannot register the hard disk ... because a hard disk ... with UUID ... already exists` | ★★★★ 直接複製磁碟檔造成 **UUID 衝突** | `VBoxManage internalcommands sethduuid <檔案>` 產生新 UUID；★★★★ 正確作法是用 `clonevm` 或 `clonemedium` | ★★★★ |
| 10 | Linux guest 開機停在 `This kernel requires an x86-64 CPU` | ★★★★ 選了 64 位元 guest 但硬體虛擬化沒開 | 同 #1；或把 `--ostype` 改成 32 位元 | ★★★★ |
| 11 | 匯入的 OVA 開機後**沒有網路** | ★★★★★ 網卡介面名稱改變（例如 `enp0s3` → `enp0s8`），netplan／`ifcfg` 對不上 | 進 console 用 `ip link` 查實際名稱後修正設定；★★★★ 或改用 `match: macaddress` | ★★★★★ |
| 12 | 螢幕解析度卡在小視窗、拉不大 | ★★★★ Guest Additions 沒裝 | 裝 Guest Additions 並重開機 | ★★★★ |
| 13 | VM 執行中宿主整台變超慢 | ★★★★ 記憶體超配或防毒即時掃描 VM 磁碟檔 | 降低 VM 記憶體；★★★★★ 把 VM 目錄加入防毒排除清單 | ★★★★ |
| 14 | `The virtual machine has terminated unexpectedly during startup with exit code 1` | ★★★ 通常是權限或設定檔問題 | 看 `~/VirtualBox VMs/<VM>/Logs/VBox.log` 最後 30 行 | ★★★★ |
| 15 | 遠端桌面（VRDE）連不上 | ★★★★★ **Extension Pack 沒裝**，VRDE 功能不存在 | 確認授權後再決定是否安裝；★★★★ 建議改用 guest 內的 SSH／RDP | ★★★★★ |
| 16 | USB 隨身碟在 guest 內看不到 | ★★★★★ USB 2.0／3.0 控制器**需要 Extension Pack** | 改用共享資料夾或網路傳檔；★★★★ 需要 USB 就先確認授權 | ★★★★★ |
| 17 | guest 時間一直不對 | ★★★★ 未設 `--rtcuseutc on` 或 Guest Additions 沒裝 | `VBoxManage modifyvm <VM> --rtcuseutc on`；裝 Guest Additions | ★★★ |
| 18 | 兩台 VM 都設 NAT，卻互相 ping 不到 | ★★★★★ **NAT 模式下每台 VM 的 NAT 網段各自獨立** | 改用 **NAT Network** 或 Internal Network | ★★★★★ |
| 19 | 快照越拍越多，VM 越來越慢 | ★★★★ 快照鏈過長，每次讀取都要往上追 | 合併或刪除舊快照；★★★★★ 快照不是備份，長期保存請用匯出 | ★★★★ |
| 20 | Bridged 模式下 guest 拿不到 IP | ★★★★ 機關網路有 DHCP 管控、port security 或 802.1X | 改用 NAT；或向網管申請放行該 MAC | ★★★★ |

> [!tip] ★★★★ 排錯第一步永遠是看日誌
> ```bash
> tail -n 50 "$HOME/VirtualBox VMs/lab-ubuntu/Logs/VBox.log"
> ```
> ★★★★ VirtualBox 的錯誤代碼（`VERR_*`、`NS_ERROR_FAILURE`）在 GUI 上常常只是一行，
> **真正的原因幾乎都在 `VBox.log` 的最後幾十行。**

---

## 安全性注意事項

### ★★★★★ 一、授權合規本身就是資安與稽核議題

★★★★★ 機關的資安稽核會問「這台機器上的每一套軟體，授權依據是什麼」。
VirtualBox 的兩層授權結構讓這題比想像中難回答。

| 稽核可能問的問題 | 該準備的答案 | 重要度 |
| --- | --- | --- |
| 這套軟體從哪裡下載的？ | ★★★★ 官方網站，留下下載日期與檔案雜湊值 | ★★★★ |
| 版本是什麼？ | ★★★ `VBoxManage --version` 的輸出截圖 | ★★★ |
| ★★★★★ **有沒有裝 Extension Pack？** | ★★★★★ `VBoxManage list extpacks` 的輸出截圖 | ★★★★★ |
| ★★★★★ **如果有裝，商業使用的授權依據？** | ★★★★★ **採購或法務單位的書面確認** | ★★★★★ |
| 上面跑了什麼資料？ | ★★★★ 資產清冊；★★★★★ 個資與機敏資料不應放在桌機 VM | ★★★★★ |

見 [[100-02-13-guide-維運-資產與授權管理]] 與 [[090-07-05-guide-資安實踐-ISO27001與ISMS]]。

---

### ★★★★ 二、桌機 VM 的資料落地風險

★★★★★ **桌機端 VM 最大的資安風險不是被入侵，是「資料留在筆電上」。**

| 風險 | 說明 | 對策 | 重要度 |
| --- | --- | --- | --- |
| VM 磁碟檔外流 | ★★★★★ 一個 `.vdi` 或 `.ova` 就是一整台機器，複製走就全帶走 | ★★★★ 宿主機開全碟加密；不把正式資料匯進測試 VM | ★★★★★ |
| 筆電遺失 | ★★★★ VM 內的憑證、金鑰、資料庫連線字串全部外洩 | ★★★★★ 宿主 BitLocker／LUKS + 開機密碼 | ★★★★★ |
| 快照殘留 | ★★★ 以為刪掉的資料還在舊快照裡 | ★★★★ 定期清理快照；退役時整顆磁碟安全抹除 | ★★★★ |
| 共享資料夾 | ★★★★ guest 被入侵時，共享資料夾是通往宿主的直接通道 | ★★★★ 不用時移除共享；不要把家目錄整個分享出去 | ★★★★ |
| ★★★★ **正式資料進測試環境** | ★★★★★ 拿正式資料庫的匯出檔在筆電上測試 | ★★★★★ **一律先去識別化**，見 [[090-03-03-guide-應用安全-機密管理與金鑰保護]] | ★★★★★ |

---

### ★★★★ 三、網路模式的資安含義

| 模式 | 資安風險 | 建議 | 重要度 |
| --- | --- | --- | --- |
| NAT | ★★ 最安全（guest 預設不對外曝露） | ★★★★ 預設選它 | ★★★★ |
| NAT + port forwarding | ★★★★ **綁 `0.0.0.0` 時整個區網都連得到** | ★★★★★ 一律綁 `127.0.0.1` | ★★★★★ |
| Bridged | ★★★★★ **guest 直接出現在機關實體網路上** | ★★★★★ 未經網管同意不要用；VM 也要打修補 | ★★★★★ |
| Host-only | ★★ 低（不通外網） | ★★★★ 實驗網路的首選 | ★★★★ |
| Internal | ★ 最低（完全隔離） | ★★★ 惡意程式分析等場合使用 | ★★★ |

> [!danger] ★★★★★ Bridged 模式在機關網路是一個實質的資安決策
> Bridged 讓 VM 變成機關網路上一台**沒有納入資產管理、沒有裝端點防護、
> 可能沒有打修補的機器**。
> ★★★★★ 這在資安稽核上是明確的缺失。要用 Bridged，
> **先跟網管與資安人員說，並把該 VM 納入資產清冊與修補範圍。**
> 相關規範見 [[090-05-13-guide-資安設備-網路存取控制NAC與802.1X]]。

---

### ★★★★ 四、VM 也需要打修補

★★★★ 常見的錯誤觀念是「反正是測試 VM，不用更新」。
但只要它連得到網路，它就是攻擊面：

```bash
# guest 內定期執行
sudo apt update && sudo apt -y upgrade
```

★★★★ 長期留著的測試 VM 應該納入修補管理流程，
見 [[090-07-03-guide-資安實踐-弱點與修補管理流程]]。
★★★★★ **不打算維護的 VM 就刪掉**，不要放著。

---

### ★★★ 五、不要在正式環境用 VirtualBox 承載服務

★★★★★ 這已經在「什麼時候不要選它」講過，但從資安角度再說一次：

- ★★★★★ **沒有集中日誌**：guest 的日誌散在各台筆電上，SIEM 收不到
- ★★★★ **沒有集中修補**：不知道哪台筆電上還有一台三年沒更新的 VM
- ★★★★ **沒有備份稽核軌跡**：無法證明資料有被備份
- ★★★★★ **宿主機的使用者就是 VM 的管理員**：權限分離做不到

見 [[090-05-09-guide-資安設備-日誌集中與SIEM]] 與 [[100-02-01-guide-維運-維運制度與角色分工]]。

---

## 速查表

### VBoxManage 常用指令

| 目的 | 指令 | 重要度 |
| --- | --- | --- |
| 版本 | `VBoxManage --version` | ★★★ |
| ★★★★★ **列出擴充套件** | `VBoxManage list extpacks` | ★★★★★ |
| 移除擴充套件 | `VBoxManage extpack uninstall "Oracle VirtualBox Extension Pack"` | ★★★★ |
| 列出所有 VM | `VBoxManage list vms` | ★★★★ |
| 列出執行中 VM | `VBoxManage list runningvms` | ★★★★ |
| 列出 OS 類型 | `VBoxManage list ostypes` | ★★★ |
| 列出 host-only 介面 | `VBoxManage list hostonlyifs` | ★★★★ |
| 列出橋接介面 | `VBoxManage list bridgedifs` | ★★★ |
| 列出 NAT Network | `VBoxManage natnetwork list` | ★★★ |
| 建立 VM | `VBoxManage createvm --name <名> --ostype <型> --register` | ★★★★ |
| 改硬體規格 | `VBoxManage modifyvm <名> --memory 4096 --cpus 2` | ★★★★ |
| 建立磁碟 | `VBoxManage createmedium disk --filename <路徑> --size <MB> --format VDI` | ★★★★ |
| 加控制器 | `VBoxManage storagectl <名> --name "SATA" --add sata --controller IntelAhci` | ★★★★ |
| 掛磁碟 | `VBoxManage storageattach <名> --storagectl "SATA" --port 0 --device 0 --type hdd --medium <vdi>` | ★★★★ |
| 掛 ISO | `... --port 1 --device 0 --type dvddrive --medium <iso>` | ★★★★ |
| ★★★★ **卸載 ISO** | `... --type dvddrive --medium emptydrive` | ★★★★ |
| 啟動（GUI） | `VBoxManage startvm <名> --type gui` | ★★★ |
| ★★★★ **無頭啟動** | `VBoxManage startvm <名> --type headless` | ★★★★ |
| 正常關機 | `VBoxManage controlvm <名> acpipowerbutton` | ★★★★ |
| ★★★★★ **強制斷電** | `VBoxManage controlvm <名> poweroff` | ★★★★★ |
| 暫停存檔 | `VBoxManage controlvm <名> savestate` | ★★★ |
| 拍快照 | `VBoxManage snapshot <名> take "<標籤>"` | ★★★★ |
| 列快照 | `VBoxManage snapshot <名> list` | ★★★ |
| 還原快照 | `VBoxManage snapshot <名> restore "<標籤>"` | ★★★★ |
| 刪快照 | `VBoxManage snapshot <名> delete "<標籤>"` | ★★★ |
| 完整複製 | `VBoxManage clonevm <名> --name <新名> --mode all --register` | ★★★★ |
| 連結複製 | `VBoxManage clonevm <名> --name <新名> --snapshot <快照> --options link --register` | ★★★ |
| 匯出 OVA | `VBoxManage export <名> -o <檔案.ova>` | ★★★★ |
| 匯入 OVA | `VBoxManage import <檔案.ova> --vsys 0 --vmname <新名>` | ★★★★ |
| 加共享資料夾 | `VBoxManage sharedfolder add <名> --name share --hostpath <路徑> --automount` | ★★★ |
| NAT 轉埠 | `VBoxManage modifyvm <名> --natpf1 "ssh,tcp,127.0.0.1,2222,,22"` | ★★★★ |
| 刪 NAT 轉埠 | `VBoxManage modifyvm <名> --natpf1 delete ssh` | ★★★ |
| 建 NAT Network | `VBoxManage natnetwork add --netname <名> --network "10.10.10.0/24" --enable --dhcp on` | ★★★★ |
| 建 host-only 介面 | `VBoxManage hostonlyif create` | ★★★★ |
| 查 guest IP | `VBoxManage guestproperty get <名> "/VirtualBox/GuestInfo/Net/1/V4/IP"` | ★★★★ |
| 完整資訊 | `VBoxManage showvminfo <名>` | ★★★★ |
| 修 UUID 衝突 | `VBoxManage internalcommands sethduuid <vdi>` | ★★★ |
| 巢狀虛擬化 | `VBoxManage modifyvm <名> --nested-hw-virt on` | ★★★ |

### 重要路徑

| 路徑 | 內容 | 重要度 |
| --- | --- | --- |
| `~/VirtualBox VMs/` | ★★★★ VM 預設存放位置（Linux／macOS） | ★★★★ |
| `%USERPROFILE%\VirtualBox VMs\` | Windows 上的 VM 存放位置 | ★★★★ |
| `~/VirtualBox VMs/<VM>/<VM>.vbox` | ★★★ VM 設定檔（XML） | ★★★ |
| `~/VirtualBox VMs/<VM>/Logs/VBox.log` | ★★★★★ **排錯第一個要看的檔案** | ★★★★★ |
| `~/.config/VirtualBox/VirtualBox.xml` | 全域設定 | ★★★ |
| `/media/sf_<共享名>` | ★★★★ Linux guest 的自動掛載點 | ★★★★ |
| `/mnt/cdrom/VBoxLinuxAdditions.run` | Guest Additions 安裝程式 | ★★★ |
| `/sbin/vboxconfig` | ★★★★ Linux 上重建核心模組 | ★★★★ |

### 網路模式五秒判定

| 需求 | 選 | 重要度 |
| --- | --- | --- |
| 只要 guest 能上網 | **NAT** | ★★★★ |
| 多台 VM 要互通又要上網 | **NAT Network** | ★★★★★ |
| 宿主要 SSH 進 guest | **加一張 Host-only**（或 NAT 轉埠） | ★★★★★ |
| guest 要被區網其他機器連到 | **Bridged**（★★★★ 先問網管） | ★★★★ |
| 完全隔離的實驗網路 | **Internal Network** | ★★★ |

### 選型五秒判定

| 情境 | 用不用 VirtualBox | 重要度 |
| --- | --- | --- |
| 臨時開一台看看 | ✅ 用 | ★★★★ |
| Vagrant 實驗環境 | ✅ **最推薦** | ★★★★★ |
| 教育訓練教室 | ✅ 用（★★★★ 別裝 Extension Pack） | ★★★★ |
| macOS 宿主 | ✅ 用 | ★★★ |
| 桌機端長期主力 | ❌ 用 **VMware Workstation** | ★★★★ |
| 機房正式服務 | ❌ 用 **Proxmox VE** | ★★★★★ |
| 需要 HA／叢集 | ❌ 用 **Proxmox VE** | ★★★★★ |
| 需要 GPU 直通 | ❌ 用 **Proxmox VE** | ★★★★ |
| 稽核極嚴格的環境 | ❌ 授權說明成本高 | ★★★★ |

### 授權自我檢查三問

| # | 問題 | 通過標準 | 重要度 |
| --- | --- | --- | --- |
| 1 | `VBoxManage list extpacks` 是 0 嗎？ | ★★★★★ 是 0 最單純 | ★★★★★ |
| 2 | 若不是 0，有沒有書面授權依據？ | ★★★★★ 採購／法務的書面確認 | ★★★★★ |
| 3 | 這台機器有沒有進資產清冊？ | ★★★★ 有，且記載軟體版本 | ★★★★ |

---

## 練習題

1. **（授權盤點）** 在你手上任何一台裝了 VirtualBox 的機器上執行
   `VBoxManage list extpacks`，記錄輸出。如果不是 `Extension Packs: 0`，
   列出這台機器上有哪些 VM 實際用到了 Extension Pack 才有的功能
   （USB 2.0/3.0 控制器、VRDE、磁碟加密、NVMe）。

2. **（網路模式驗證）** 建立兩台最小化的 VM，第一次都設成 **NAT**，
   測試它們能不能互相 ping；再都改成同一個 **NAT Network**，重測一次。
   把兩次的結果與你的解釋寫下來。

3. **（雙網卡）** 用 `VBoxManage` 幫一台 VM 設定 nic1 = NAT、
   nic2 = host-only，讓它同時能上外網、又能被宿主 SSH 連進去。
   寫出你用的完整指令與驗證方式。

4. **（Guest Additions 驗證）** 在一台**沒有裝** Guest Additions 的 Linux guest 上
   嘗試掛載共享資料夾，記錄錯誤訊息；裝完之後再試一次。
   說明 `vboxsf` 群組在這件事裡扮演什麼角色。

5. **（OVA 交付）** 依「完整實戰範例」的步驟做出一個可交付的 OVA，
   並在**另一台機器**上匯入驗證。特別檢查：ISO 有沒有卸載、
   SSH host key 有沒有清掉、網卡介面名稱有沒有變。

6. **（選型說明）** 假設有同事提議「機房那台服務就用 VirtualBox 跑，反正免費」。
   寫一段 200 字以內的回覆，說明**技術上與稽核上**各三個不建議的理由，
   並給出替代方案。

> [!question]- 練習解答
> **1.** 重點在於**把授權問題變成可查證的事實**。若輸出為 `Extension Packs: 1`，
> 就要逐台 `VBoxManage showvminfo <VM> | grep -i -E 'usb|vrde'` 檢查是否真的用到。
> ★★★★★ **若沒有任何 VM 需要，直接 `extpack uninstall` 是成本最低的合規作法**；
> 若有需要，就得走採購或法務確認流程並留存書面紀錄。見「授權的兩層結構」一節。
>
> **2.** ★★★★★ **NAT 模式下兩台 VM ping 不到彼此**，因為每台 VM 有各自獨立的 NAT 引擎與網段；
> **NAT Network 下可以互通**，因為它們共用同一個虛擬網段。
> 這是 VirtualBox 與 VMware Workstation 在 NAT 行為上最大的差異，也是最常見的設定錯誤。
> 見「六種網路模式」一節。
>
> **3.**
> ```bash
> VBoxManage modifyvm "lab" --nic1 nat --nic2 hostonly --hostonlyadapter2 vboxnet0
> ```
> 驗證：guest 內 `ping -c2 1.1.1.1`（走 NAT 出去）成功，
> 且宿主 `ssh user@192.168.56.x`（走 host-only）連得進去。
> ★★★★ guest 內要記得替第二張網卡設定 IP，否則 host-only 那側沒有位址。
>
> **4.** 沒裝 Guest Additions 時會得到 `mount: unknown filesystem type 'vboxsf'`，
> 因為 `vboxsf` 這個檔案系統驅動就是 Guest Additions 提供的。
> 裝完之後自動掛載點 `/media/sf_<名稱>` 的群組是 `vboxsf`、其他人無權限，
> ★★★★ 所以使用者必須加入該群組**並重新登入**。見「共享資料夾」一節。
>
> **5.** 三個檢查點對應三種常見事故：ISO 沒卸載 → OVA 肥大；
> SSH host key 沒清 → ★★★★★ 十台機器同一把金鑰，是明確資安缺失；
> 網卡名稱改變 → ★★★★★ 學員匯入後沒網路，是課堂上最常見的災難。
> 見「完整實戰範例」步驟 6～8。
>
> **6.** 技術理由（擇三）：Type 2 架構下宿主重開機服務就停、沒有 HA 與線上遷移、
> 沒有集中備份與排程、磁碟 I/O 效能不足。
> 稽核理由（擇三）：★★★★★ Extension Pack 授權依據難以交代、日誌無法集中到 SIEM、
> 修補管理與資產盤點涵蓋不到、宿主使用者即 VM 管理員導致權限分離失效。
> 替代方案：[[050-01-03-01-svc-PVE-安裝與初始設定]]。

---

## 小測驗

**Q1.**（選擇）VirtualBox 的 Extension Pack 與基礎套件在授權上的關係，下列何者正確？
(A) 兩者授權相同，都是開源
(B) ★ 兩者授權**不同**，Extension Pack 是 Oracle 專有授權，商業使用條款需另行確認
(C) Extension Pack 需要輸入序號才能安裝，所以不會誤用
(D) Extension Pack 只影響效能，不影響授權

**Q2.**（是非）`VBoxManage list extpacks` 輸出 `Extension Packs: 0`，
代表這台機器上不存在需要額外確認商業授權的 VirtualBox 元件。

**Q3.**（簡答）兩台 VM 都設定為 **NAT** 模式，為什麼它們互相 ping 不到？
要讓它們互通又能上外網，應該改用哪一種模式？

**Q4.**（這行指令會發生什麼）
```bash
VBoxManage controlvm lab-ubuntu poweroff
```

**Q5.**（選擇）Linux guest 掛載共享資料夾時出現
`mount: unknown filesystem type 'vboxsf'`，最可能的原因是？
(A) 宿主的共享資料夾路徑打錯
(B) 使用者不在 `vboxsf` 群組
(C) ★ Guest Additions 沒有安裝或核心模組沒編成功
(D) 共享資料夾名稱有中文

**Q6.**（是非）VirtualBox 的快照可以取代備份，因為快照能還原到任意時間點。

**Q7.**（簡答）在 Windows 宿主上執行
`Get-ComputerInfo -Property HyperVisorPresent` 得到 `True`，
這對 VirtualBox 代表什麼？可能會看到什麼錯誤？

**Q8.**（選擇）下列哪一個情境**最適合**選用 VirtualBox？
(A) 機關對外網站的正式主機
(B) 需要 GPU 直通做 AI 推論的伺服器
(C) ★ 用 Vagrant 建立可重現、用完即丟的實驗環境
(D) 需要跨主機線上遷移的虛擬化叢集

**Q9.**（簡答）把一台 VM 匯出成 OVA、發給十位學員之前，
為什麼一定要在 guest 裡執行 `sudo rm -f /etc/ssh/ssh_host_*`？

**Q10.**（這行指令會發生什麼）
```bash
VBoxManage modifyvm lab --natpf1 "ssh,tcp,,2222,,22"
```

> [!question]- 測驗答案
> **Q1. (B)** ★★★★★ Extension Pack 是 Oracle 專有授權，
> **可以免費下載不等於機關可以免費用**，且安裝時不會要求序號，是「事後稽核制」。
> 見「授權的兩層結構」。
>
> **Q2. ✅ 是** ★★★★★ `Extension Packs: 0` 代表只剩基礎套件那一層，
> 授權說明成本大幅降低。這是機關環境最省事的狀態，建議把這個輸出截圖存檔。
> 見「授權的兩層結構」與「授權自我檢查三問」。
>
> **Q3.** ★★★★★ **NAT 模式下每台 VM 有各自獨立的 NAT 引擎與網段**，
> 彼此之間沒有共同的第二層網路，所以 ping 不到。
> 要互通又要上網，改用 **NAT Network**。見「六種網路模式」。
>
> **Q4.** ★★★★★ **等同直接拔電源**：VM 立刻斷電，guest 中未寫入磁碟的資料遺失，
> 檔案系統可能需要 fsck。正常情況應先用 `acpipowerbutton`。
> 見「Headless 與遠端操作」。
>
> **Q5. (C)** ★★★★★ `vboxsf` 這個檔案系統驅動由 Guest Additions 提供，
> 沒裝就根本沒有這個檔案系統類型。（B）造成的是 `Permission denied`，症狀不同。
> 見「共享資料夾」與排錯表 #7、#8。
>
> **Q6. ❌ 非** ★★★★★ 快照與 VM 在**同一顆實體磁碟、同一台宿主機**上，
> 磁碟壞掉或宿主被勒索加密就一起沒。快照只是「短期回復點」，不是備份。
> 見「快照、複製與匯出」。
>
> **Q7.** ★★★★★ 代表 **Windows 自己已經在跑 hypervisor**
> （Hyper-V／WSL2／Windows 沙箱／記憶體完整性 VBS 都會造成），
> VirtualBox 拿不到獨佔的硬體虛擬化，可能出現 `VERR_VMX_IN_VMX_ROOT_MODE`
> 或效能嚴重下降。見排錯表 #3。
>
> **Q8. (C)** ★★★★★ Vagrant 是 VirtualBox 最有說服力的使用情境。
> (A)(B)(D) 都應該用 Proxmox VE。見「什麼時候該選 VirtualBox」與「什麼時候絕對不要選」。
>
> **Q9.** ★★★★★ 不清除的話十台 VM 會共用**同一組 SSH 主機金鑰**，
> 等於十台機器在網路上宣稱自己是同一台，會造成
> `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!` 並且是明確的資安缺失。
> 刪除後 SSH 服務會在下次開機自動重新產生。見「完整實戰範例」步驟 6。
>
> **Q10.** ★★★★ 建立一條 NAT 轉埠規則，把**宿主的 2222 埠**轉到 **guest 的 22 埠**。
> ★★★★★ 但因為主機位址欄留空，它會綁在**所有介面**上，
> 區網內其他機器也連得到，是資安缺口 ——
> 正確寫法是 `"ssh,tcp,127.0.0.1,2222,,22"`。見「六種網路模式」與「安全性注意事項」。

---

## 延伸閱讀

### 同章

- [[050-01-05-02-guide-其他虛擬化-VMwareESXi與採購考量]] — ★★★★ 另一個補充平台：
  ESXi 的定位、授權變動與機關採購考量
- [[050-01-05-00-idx-其他虛擬化-其他虛擬化平台]] — 本章索引

### 選型與授權

- [[050-01-01-03-ref-虛擬化-五平台橫向對照]] — ★★★★★ 五平台完整對照與選型決策樹
- [[050-01-01-04-guide-虛擬化-機關選型與授權成本]] — ★★★★ 授權模式的結構性比較與 TCO 試算
- [[050-01-01-01-guide-虛擬化-虛擬化概念與選型]] — ★★★★ Type 1／Type 2 的定義
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] — ★★★ 硬體虛擬化、VirtIO、巢狀虛擬化的原理

### 主線平台（本篇不斷對照的對象）

- [[050-01-02-01-svc-Workstation-安裝與授權]] — ★★★★★ 桌機端主線
- [[050-01-02-04-guide-Workstation-網路模式]] — ★★★★ 網路模式的對照基準
- [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] — ★★★ 共享資料夾與工具程式對照
- [[050-01-02-03-guide-Workstation-快照與複製]] — ★★★ 快照觀念
- [[050-01-03-01-svc-PVE-安裝與初始設定]] — ★★★★★ 機房端主線，正式環境請用它
- [[050-01-04-01-guide-KVM-KVM與libvirt架構]] — ★★★ Linux 原生虛擬化，自動化情境的另一選擇

### 資安與維運

- [[100-02-13-guide-維運-資產與授權管理]] — ★★★★★ 授權盤點與稽核回覆
- [[090-02-06-guide-防護-遠端存取安全]] — ★★★★ SSH 主機金鑰與遠端連線安全
- [[090-03-03-guide-應用安全-機密管理與金鑰保護]] — ★★★★ 測試環境的資料去識別化
- [[090-07-03-guide-資安實踐-弱點與修補管理流程]] — ★★★ 測試 VM 也要納入修補
- [[090-05-13-guide-資安設備-網路存取控制NAC與802.1X]] — ★★★ Bridged 模式在機關網路的限制

### 環境管理與自動化

- [[080-03-01-guide-發布-環境分離與設定管理]] — ★★★★ 環境進版控的觀念
- [[080-03-02-guide-發布-分支策略與git-flow]] — ★★★ `Vagrantfile` 進 git 的作法
- [[050-02-01-01-svc-Docker-容器概念與Docker安裝]] — ★★★ 很多「開一台 VM 測試」的需求其實用容器更快
