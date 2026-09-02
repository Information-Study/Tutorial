---
title: "PVE 硬體直通與 GPU"
desc: "IOMMU 原理與群組限制、vfio-pci 綁定與黑名單、PCIe passthrough 完整步驟、GPU 直通給 AI 服務，以及直通換來的可用性代價"
aliases: [IOMMU, PCIe passthrough, vfio-pci, GPU 直通, hostpci, ACS override, SR-IOV]
tags: [群組/虛擬機與容器, 虛擬化/pve, 主題/虛擬化]
category: 虛擬化平台
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-03-01-svc-PVE-安裝與初始設定]]", "[[050-01-03-03-guide-PVE-虛擬機管理]]", "[[020-01-26-guide-Linux-核心模組與sysctl調校]]"]
updated: 2026-09-02
---

# PVE 硬體直通與 GPU

> [!abstract] 這篇你會學到
> - **IOMMU 到底在做什麼**，為什麼沒有它就不能把 PCIe 裝置交給虛擬機
> - BIOS／UEFI 要開哪些選項、核心參數 `intel_iommu=on`／`amd_iommu=on` 怎麼加
>   （★★★★ PVE 有 **GRUB 與 systemd-boot 兩種開機路徑**，加錯地方等於沒加）
> - ★★★★★ **IOMMU 群組的限制** —— 同一個群組裡的裝置**必須整組一起直通**，
>   這是九成「為什麼我的顯示卡直通不了」的真正原因
> - 把裝置從主機驅動手上搶過來：**黑名單 + vfio-pci 綁定**
> - 一條龍的 **PCIe passthrough 完整步驟**（q35 + OVMF + hostpci）
> - ★★★★ **GPU 直通給 AI 服務**（Ollama／ComfyUI），以及什麼時候該改用 LXC 而不是 VM
> - ★★★★★ **直通的代價**：不能線上遷移、不能做記憶體氣球、HA 大幅受限
> - 現場最常卡住的十幾個點，每個都給判定方法

> [!warning] 未實機驗證
> 本篇**以 Proxmox VE 8 為例**。IOMMU、vfio、GPU 直通是**極度依賴硬體**的主題：
> 同一份步驟在 A 主機成功、在 B 主機可能整段卡死。
>
> ★★★★★ 文中出現的 **PCI 位址（`01:00.0`）、廠商裝置 ID（`10de:xxxx`）、
> IOMMU 群組編號、`lspci` 與 `dmesg` 輸出，全部是示意值**，
> 你的機器一定不一樣，**不要照抄**，一定要用自己機器上跑出來的值。
>
> ★★★★★ 核心參數、開機載入器行為、可用的 vfio 模組名稱**會隨版本改變**。
> 動手前請以 Proxmox 官方 wiki 的 PCI(e) Passthrough 頁面**當前版本**為準。
>
> ★★★★★ **直通設定弄錯會讓主機開不進 GUI、甚至無法開機。**
> 第一次做請確保你有 **IPMI／iDRAC／iLO 或實體螢幕鍵盤**可以救回來。

---

## 前置知識

- [[050-01-03-01-svc-PVE-安裝與初始設定]] — 你的 PVE 是 GRUB 還是 systemd-boot 開機，這裡有答案
- [[050-01-03-03-guide-PVE-虛擬機管理]] — VM 的 machine type、BIOS、CPU 型別
- [[050-01-03-04-guide-PVE-LXC容器管理]] — ★★★★ GPU 給 AI 服務時，LXC 常常是更好的選擇
- [[050-01-03-07-svc-PVE-叢集與高可用]] — ★★★★★ 直通會直接影響遷移與 HA
- [[020-01-26-guide-Linux-核心模組與sysctl調校]] — `modprobe`、`/etc/modules`、`initramfs`
- [[020-01-27-cmd-Linux-硬體資訊與裝置管理]] — `lspci`、`lsusb`、`dmesg` 的讀法
- [[020-01-25-guide-Linux-開機流程與GRUB救援]] — ★★★★ 改壞開機參數時怎麼救
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] — 硬體輔助虛擬化的整體圖像

---

## 觀念說明

### 先講結論：直通是一場交易 ★★★★★

```
你得到                             你付出
────────────────────────────────────────────────────────
★★★★★ 接近原生的裝置效能            ★★★★★ 不能線上遷移（live migration）
★★★★ 完整的裝置功能與驅動支援       ★★★★★ HA 只能綁在有同款硬體的節點
★★★★ GPU 運算能力（CUDA）           ★★★★ 主機自己不能再用這張卡
★★★ 特殊介面卡（採集卡、加密卡）     ★★★★ 開機參數與模組設定變複雜
                                    ★★★ 主機韌體升級後可能整組重來
```

★★★★★ **如果你的服務需要「隨時可以搬到別的節點」，就不要用直通。**
機關環境裡，直通適合的是「這台就是專門跑這個」的機器：
AI 推論主機、影像處理主機、需要特定介面卡的系統。

### IOMMU 是什麼 ★★★★★

先看沒有 IOMMU 的世界會發生什麼事。

```
【問題】PCIe 裝置有 DMA 能力 —— 它可以自己讀寫實體記憶體

   VM (guest)                   主機實體記憶體
   ┌──────────┐                ┌──────────────────────┐
   │ 驅動程式  │  叫網卡把資料   │ 0x0000 ~ 0x0FFF 主機核心 │ ← ★★★★★ 危險
   │ 說：      │  DMA 到位址 X   │ 0x1000 ~ 0x1FFF 其他 VM  │ ← ★★★★★ 危險
   │ "寫到 X"  │ ───────────►  │ 0x2000 ~ 0x2FFF 這台 VM  │ ← 應該只能碰這裡
   └──────────┘                └──────────────────────┘

   ★★★★★ Guest 眼中的「實體位址」根本不是主機的實體位址。
   如果裝置直接照 guest 給的位址做 DMA，就會寫到別人的記憶體。
```

IOMMU（Input/Output Memory Management Unit）就是**擋在裝置與記憶體之間的位址轉譯器**，
角色等同 CPU 的 MMU，只是服務對象換成 PCIe 裝置。

```
【有 IOMMU】

   PCIe 裝置 ──DMA 請求（guest 位址）──► IOMMU ──► 主機實體位址
                                          │
                                          ├─ 查這台 VM 的頁表
                                          ├─ ★★★★★ 不在允許範圍 → 直接擋掉
                                          └─ 在範圍內 → 轉譯後放行
```

| 廠商 | 技術名稱 | BIOS 裡常見的字樣 |
| --- | --- | --- |
| ★★★★★ Intel | **VT-d**（Virtualization Technology for Directed I/O） | `Intel VT-d`、`VT for Direct I/O`、`Intel Virtualization Technology for Directed I/O` |
| ★★★★★ AMD | **AMD-Vi**（在 BIOS 常寫成 IOMMU） | `IOMMU`、`AMD IOMMU`、`SVM Mode`（SVM 是 CPU 虛擬化，兩個都要開） |

> [!note] ★★★★ VT-x 與 VT-d 是兩件事
> - **VT-x / AMD-V（SVM）**：CPU 的虛擬化擴充，**跑 VM 就需要**。
> - **VT-d / AMD-Vi（IOMMU）**：I/O 的位址隔離，**直通才需要**。
>
> ★★★ 很多 BIOS 把它們放在不同頁籤，只開一個是最常見的失敗原因。

### 中斷重映射（Interrupt Remapping）★★★★

IOMMU 除了轉譯 DMA 位址，還要處理**中斷**。裝置發中斷時同樣不能讓它亂打，
所以需要 **interrupt remapping**。

★★★★★ **如果平台不支援中斷重映射，PVE 預設會拒絕做直通**，
除非你明確允許不安全的中斷（`allow_unsafe_interrupts`）——
那等於把隔離拿掉，**正式環境不要開**。

```bash
dmesg | grep -i 'remapping'
```

```text
[    0.512345] DMAR-IR: Enabled IRQ remapping in x2apic mode
```

看到 `Enabled IRQ remapping` 就是好的。若看到：

```text
[    0.498877] DMAR-IR: This system BIOS has enabled interrupt remapping
              on a chipset that contains an erratum ...
```

★★★★ 代表韌體有已知問題，先去找主機板廠商的 BIOS 更新。

### ★★★★★ IOMMU 群組：整篇最重要的一節

IOMMU 不是以「單一裝置」為單位做隔離，而是以**群組（group）**為單位。
群組的劃分由**硬體拓撲**決定 —— 主要看 PCIe switch／橋接器是否支援
**ACS（Access Control Services）**。ACS 能保證群組內的裝置之間**不能直接互相通訊**，
沒有 ACS，核心就只能保守地把它們歸成一組。

```
【理想情況】每張卡自成一組
  Group 14 ── 01:00.0  GPU
  Group 15 ── 01:00.1  GPU 的 HDMI 音效
              ★★★ 很多主機板上這兩個是同一組，那也很正常，一起直通即可

【常見的麻煩】整條 PCIe 通道擠在一組
  Group 12 ── 00:1c.0  PCI bridge
           ├─ 02:00.0  網路卡  ← ★★★★★ 主機自己在用！
           ├─ 03:00.0  SATA 控制器 ← ★★★★★ 主機的系統碟掛在上面！
           └─ 04:00.0  你想直通的卡
```

★★★★★ **規則：一個 IOMMU 群組必須整組交給同一台 VM，不能拆開。**

所以上面那個例子的結果是：

- 你不能只把 `04:00.0` 給 VM。
- 要直通就得把網卡與 SATA 控制器一起交出去 —— 主機會失去系統碟，**直接死機**。

**這就是「為什麼我的卡直通不了」最常見的真相**，不是設定寫錯，是硬體拓撲不允許。

#### 遇到群組黏在一起，你的選項 ★★★★

| 選項 | 做法 | 風險 |
| --- | --- | --- |
| ★★★★★ **換插槽**（最推薦） | 把卡插到 CPU 直連的 PCIe 插槽（通常是最靠近 CPU 的 x16），常常就分開了 | 無，只是要開機殼 |
| ★★★★ **更新 BIOS** | 部分主機板新版韌體修正了 ACS 回報 | 低 |
| ★★★★ **換主機板／平台** | 伺服器等級平台（Xeon Scalable、EPYC）的 ACS 通常正常 | 花錢 |
| ★★★★★ **ACS override 核心參數** | `pcie_acs_override=downstream,multifunction` 強制拆開群組 | ★★★★★ **破壞隔離保證**，見下方警告 |

> [!danger] ★★★★★ ACS override 是「騙核心」，不是「修好硬體」
> `pcie_acs_override=...` 只是叫核心**假裝**這些裝置之間有隔離。
> 硬體上它們**依然可以繞過 IOMMU 互相 DMA**。
>
> 後果是：**被直通的 VM 有機會攻擊同群組的其他裝置與主機記憶體**。
>
> - **家用／個人實驗機**：可以接受，很多人這樣用。
> - ★★★★★ **機關正式環境、跑不同信任等級工作負載的主機：不要用。**
>   請改用換插槽或換平台的方式解決。
>
> 另外，ACS override 是 **PVE 核心額外帶的修補**，
> 若你換用上游原生核心就沒有這個參數 —— 動手前先確認你的核心支援。

### vfio-pci：把裝置從主機手上拿走 ★★★★★

Linux 開機時，核心會依 PCI ID 自動幫每張卡掛上驅動。
NVIDIA 卡會被 `nouveau` 接走、AMD 卡會被 `amdgpu` 接走、網卡被 `ixgbe` 接走……

★★★★★ **一張卡同一時間只能有一個驅動。**
所以直通的本質是：**不要讓原生驅動碰它，改讓 `vfio-pci` 佔住。**

```
【開機順序與搶裝置的時機】

  ①  UEFI 初始化 → 顯示卡被韌體點亮（efifb / simplefb 接管畫面）
                     ★★★★ 這一步就可能造成後面 BAR 搶不到
  ②  initramfs 載入 → 這裡就要把 vfio-pci 綁上去（★★★★★ 最關鍵的時機）
  ③  根檔案系統掛載 → /etc/modprobe.d/ 生效（★★★ 但可能已經太晚）
  ④  一般驅動載入 → nouveau/amdgpu 若沒被黑名單，就會搶走
```

★★★★★ **所以改完 `/etc/modprobe.d/` 一定要跑 `update-initramfs -u -k all`**，
否則設定只寫在磁碟上、沒進 initramfs，開機時來不及生效。

### 直通的三種粒度 ★★★

| 方式 | 說明 | 適用 |
| --- | --- | --- |
| ★★★★★ **PCIe passthrough** | 整張卡交給一台 VM | GPU、HBA、採集卡、專用網卡 |
| ★★★★ **SR-IOV** | 一張卡在硬體上切成多個 VF（虛擬功能），分給多台 VM | 支援 SR-IOV 的**伺服器網卡**、部分企業級 GPU |
| ★★★ **USB passthrough** | 把單一 USB 裝置或整個 USB 控制器給 VM | UPS 監控線、加密鎖（dongle）、讀卡機 |

★★★★ **USB 直通不需要 IOMMU**（PVE 用 QEMU 的 USB 轉送），設定簡單很多；
但如果要低延遲或裝置很挑，可以直通**整個 USB 控制器**，那就需要 IOMMU。

### 直通後不能做的事 ★★★★★

| 功能 | 直通後 | 原因 |
| --- | --- | --- |
| ★★★★★ **線上遷移 live migration** | ❌ **完全不行** | VM 的記憶體被 pin 住、裝置狀態無法搬 |
| ★★★★ **離線遷移** | ⚠️ 可以，但目標節點要有**同樣位址的同款卡** | `hostpci0` 記的是 PCI 位址 |
| ★★★★★ **HA 自動切換** | ⚠️ 幾乎失效 | 切過去沒有卡，VM 起不來 |
| ★★★★ **記憶體氣球 ballooning** | ❌ 應該關掉 | 直通要求記憶體全部預先配置並鎖定 |
| ★★★ **快照（含記憶體）** | ❌ 通常不行 | 裝置狀態無法存進快照 |
| ★★★ 磁碟快照（不含記憶體） | ✅ 可以 | 只動儲存層 |

> [!tip] ★★★★ 折衷做法
> 機關常見的做法：**把直通機器排除在 HA 之外**，改用
> 「備份 + 快速重建」與「另一台備品機事先裝好同款卡」來達成可用性。
> 見 [[050-01-03-06-svc-PVE-備份與還原]] 與 [[100-02-09-svc-維運-事件處理與升級流程]]。

---

## 安裝或基礎操作

### 步驟零：確認硬體支援 ★★★★★

```bash
# CPU 是否支援虛擬化（vmx = Intel，svm = AMD）
grep -E -o 'vmx|svm' /proc/cpuinfo | sort -u
```

```text
vmx
```

```bash
# 主機板／CPU 型號，寫進你的維運文件
dmidecode -s system-manufacturer -s system-product-name -s baseboard-product-name
```

```text
Dell Inc.
PowerEdge R740
0XXXXX
```

★★★★ 沒有 `vmx`／`svm` 就代表 BIOS 沒開虛擬化，先進 BIOS 開了再說。

### 步驟一：BIOS／UEFI 設定 ★★★★★

| 要開的項目 | Intel 平台常見名稱 | AMD 平台常見名稱 |
| --- | --- | --- |
| ★★★★★ CPU 虛擬化 | `Intel Virtualization Technology (VT-x)` | `SVM Mode` |
| ★★★★★ **IOMMU** | `Intel VT for Directed I/O (VT-d)` | `IOMMU` |
| ★★★ 大型 BAR 支援（GPU 常需要） | `Above 4G Decoding` | `Above 4G Decoding` |
| ★★★ Resizable BAR | `Re-Size BAR Support` | `Re-Size BAR Support` |
| ★★★★ 主要顯示輸出 | `Primary Display` 設成內顯或 `Onboard` | 同左 |
| ★★ SR-IOV（要用才開） | `SR-IOV Support` | `SR-IOV Support` |

> [!warning] ★★★★ `Primary Display` 這一項很多人忽略
> 如果 BIOS 把你要直通的獨顯當成主要顯示卡，開機時韌體會點亮它，
> 導致後面 `vfio-pci` 搶不到記憶體區段（BAR）。
> **能設就設成內顯或伺服器的內建 BMC 顯示**。

### 步驟二：加核心參數 ★★★★★

★★★★★ **PVE 有兩種開機路徑，先確認你是哪一種，加錯地方完全沒效果。**

```bash
proxmox-boot-tool status
```

**輸出 A —— systemd-boot（多半是安裝時選 ZFS + UEFI）**

```text
Re-executing '/usr/sbin/proxmox-boot-tool' in new private mount namespace..
System currently booted with uefi
1234-ABCD is configured with: uefi (versions: 6.8.x-x-pve)
```

**輸出 B —— 沒有被 proxmox-boot-tool 管理，走 GRUB**

```text
System currently booted with legacy bios
E: /etc/kernel/proxmox-boot-uuids does not exist.
```

#### 情況 A：systemd-boot（`/etc/kernel/cmdline`）

```bash
cat /etc/kernel/cmdline
```

```text
root=ZFS=rpool/ROOT/pve-1 boot=zfs
```

★★★★ **這個檔案只有一行**，把參數接在同一行後面：

```bash
cp /etc/kernel/cmdline /etc/kernel/cmdline.bak.$(date +%F)
```

編輯後應該長這樣（Intel）：

```text
root=ZFS=rpool/ROOT/pve-1 boot=zfs intel_iommu=on iommu=pt
```

套用：

```bash
proxmox-boot-tool refresh
```

```text
Running hook script 'proxmox-auto-removal'..
Running hook script 'zz-proxmox-boot'..
Copying and configuring kernels on /dev/disk/by-uuid/1234-ABCD
	Copying kernel and creating boot-entry for 6.8.x-x-pve
```

#### 情況 B：GRUB（`/etc/default/grub`）

```bash
cp /etc/default/grub /etc/default/grub.bak.$(date +%F)
grep GRUB_CMDLINE_LINUX_DEFAULT /etc/default/grub
```

```text
GRUB_CMDLINE_LINUX_DEFAULT="quiet"
```

改成（Intel）：

```ini
GRUB_CMDLINE_LINUX_DEFAULT="quiet intel_iommu=on iommu=pt"
```

AMD 平台：

```ini
GRUB_CMDLINE_LINUX_DEFAULT="quiet amd_iommu=on iommu=pt"
```

套用：

```bash
update-grub
```

```text
Generating grub configuration file ...
Found linux image: /boot/vmlinuz-6.8.x-x-pve
Found initrd image: /boot/initrd.img-6.8.x-x-pve
done
```

#### 參數說明 ★★★★

| 參數 | 作用 | 建議 |
| --- | --- | --- |
| ★★★★★ `intel_iommu=on` | 開啟 Intel IOMMU | Intel 平台一定加（新核心可能已預設開，加了無害） |
| ★★★★★ `amd_iommu=on` | 開啟 AMD IOMMU | AMD 平台通常預設已開，明寫比較保險 |
| ★★★★ `iommu=pt` | passthrough 模式：**主機自己用的裝置繞過 IOMMU 轉譯** | ★★★★ 建議加，可降低主機 I/O 負擔 |
| ★★★★★ `pcie_acs_override=downstream,multifunction` | 強制拆 IOMMU 群組 | ★★★★★ **有安全代價，正式環境不要** |
| ★★★ `initcall_blacklist=sysfb_init` | 阻止韌體 framebuffer 佔住顯卡 | ★★★★ 只在遇到 BAR 搶不到時才加 |
| ★★★ `video=efifb:off` | 關掉 EFI framebuffer | ★★★ 舊方法，較新核心多改用上一列 |

> [!danger] ★★★★★ 加 `initcall_blacklist=sysfb_init` 之後主機主控台會黑掉
> 這是預期行為（主機不再用那張卡輸出畫面）。
> **加之前確定 SSH 進得去、或有 IPMI 可以用**，否則你會失去所有存取途徑。

★★★★★ **改完先不要急著設 VM，先重開機驗證 IOMMU 有起來。**

```bash
reboot
```

### 步驟三：驗證 IOMMU ★★★★★

```bash
dmesg | grep -i -e DMAR -e IOMMU | head -20
```

Intel 平台成功時的樣子（示意）：

```text
[    0.008000] ACPI: DMAR 0x000000006F7B0000 0000A8 (v01 INTEL  ...)
[    0.298765] DMAR: IOMMU enabled
[    0.512345] DMAR: Intel(R) Virtualization Technology for Directed I/O
[    0.512400] DMAR-IR: Enabled IRQ remapping in x2apic mode
```

AMD 平台（示意）：

```text
[    0.320011] AMD-Vi: IOMMU performance counters supported
[    0.334455] AMD-Vi: Found IOMMU cap 0x40
[    0.340099] AMD-Vi: Interrupt remapping enabled
```

再看群組目錄有沒有東西：

```bash
ls /sys/kernel/iommu_groups/ | wc -l
```

```text
42
```

★★★★★ **輸出是 `0` 就代表 IOMMU 沒起來**，回頭檢查 BIOS 與核心參數，
不要往下做。

### 步驟四：列出 IOMMU 群組 ★★★★★

這段腳本每次做直通都會用到，建議存成 `/usr/local/bin/iommu-groups.sh`：

```bash
cat > /usr/local/bin/iommu-groups.sh <<'EOF'
#!/usr/bin/env bash
# 列出所有 IOMMU 群組與群組內的 PCI 裝置
shopt -s nullglob
for g in /sys/kernel/iommu_groups/*/devices/*; do
    n=${g#*/iommu_groups/}
    n=${n%%/*}
    printf 'IOMMU Group %-3s ' "$n"
    lspci -nns "${g##*/}"
done | sort -V -k3
EOF
chmod +x /usr/local/bin/iommu-groups.sh
/usr/local/bin/iommu-groups.sh
```

輸出（★★★ 示意，你的一定不同）：

```text
IOMMU Group 0   00:00.0 Host bridge [0600]: Intel Corporation ... [8086:xxxx] (rev 07)
IOMMU Group 1   00:01.0 PCI bridge [0604]: Intel Corporation ... [8086:xxxx] (rev 07)
IOMMU Group 12  00:1f.2 SATA controller [0106]: Intel Corporation ... [8086:xxxx]
IOMMU Group 14  01:00.0 VGA compatible controller [0300]: NVIDIA Corporation ... [10de:xxxx] (rev a1)
IOMMU Group 14  01:00.1 Audio device [0403]: NVIDIA Corporation ... [10de:yyyy] (rev a1)
IOMMU Group 16  03:00.0 Ethernet controller [0200]: Intel Corporation ... [8086:zzzz]
```

**怎麼讀這份輸出（★★★★★ 這是整篇的判讀關鍵）：**

1. 找到你要直通的卡，記下**群組編號**。
2. 看**同一個群組裡還有誰**。
3. 判定：
   - 只有這張卡（可能含它的音效功能）→ ★★★★★ **可以直通**。
   - 還有 PCI bridge → ★★★ bridge 通常不用真的傳給 VM，多半沒問題。
   - ★★★★★ **還有主機正在用的裝置（SATA、開機用的網卡、NVMe）→ 不能直通**，
     回去看「遇到群組黏在一起，你的選項」。

上面的例子：Group 14 只有 GPU 與它的 HDMI 音效 —— **這是最理想的狀況**，
兩個一起直通即可。

### 步驟五：查出裝置的廠商:裝置 ID ★★★★

```bash
lspci -nn | grep -i -e nvidia -e amd/ati -e vga
```

```text
01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA102 [10de:xxxx] (rev a1)
01:00.1 Audio device [0403]: NVIDIA Corporation GA102 High Definition Audio [10de:yyyy] (rev a1)
```

★★★★ 方括號裡的 `10de:xxxx` 就是 **vendor:device ID**，
`10de` 是 NVIDIA、`1002` 是 AMD、`8086` 是 Intel。

看目前是誰在用這張卡：

```bash
lspci -nnk -s 01:00.0
```

```text
01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA102 [10de:xxxx] (rev a1)
	Subsystem: ... [xxxx:xxxx]
	Kernel driver in use: nouveau
	Kernel modules: nvidiafb, nouveau
```

★★★★★ `Kernel driver in use: nouveau` 代表主機驅動佔著，**必須先趕走**。

### 步驟六：載入 vfio 模組 ★★★★

```bash
cat /etc/modules
```

在檔尾加上：

```ini
# PCIe passthrough 需要的模組
vfio
vfio_iommu_type1
vfio_pci
```

> [!note] ★★★ `vfio_virqfd` 要不要加
> 舊資料常叫你加 `vfio_virqfd`。★★★★ **在較新的核心上這個模組已併入 vfio 本體**，
> 加了會在開機時看到 `modprobe: FATAL: Module vfio_virqfd not found`。
> 判斷方法：`modinfo vfio_virqfd`，找不到就不要加。

### 步驟七：黑名單與 vfio-pci 綁定 ★★★★★

**A. 把原生驅動列黑名單**

```bash
cat > /etc/modprobe.d/blacklist-gpu.conf <<'EOF'
# 不要讓主機的顯示驅動搶走要直通的卡
blacklist nouveau
blacklist nvidia
blacklist nvidiafb
blacklist nvidia_drm
blacklist radeon
blacklist amdgpu
EOF
```

> [!warning] ★★★★★ 只有「這張卡要直通」時才黑名單顯示驅動
> 如果主機上還有**另一張卡要給主機自己用**（例如跑 Ollama 在主機上），
> 黑名單會把那張也一起廢掉。
> 那種情況**改用下面的 ID 綁定**，不要用黑名單。

**B. 用 ID 把卡綁給 vfio-pci**

```bash
cat > /etc/modprobe.d/vfio.conf <<'EOF'
# ★★★★★ 把這裡的 ID 換成你自己 lspci -nn 查到的值
options vfio-pci ids=10de:xxxx,10de:yyyy disable_vga=1
EOF
```

| 選項 | 說明 |
| --- | --- |
| ★★★★★ `ids=` | 逗號分隔的 `vendor:device`，**GPU 與它的音效功能都要列** |
| ★★★ `disable_vga=1` | 不讓 vfio-pci 去接管 VGA 傳統資源，某些主機板需要 |

> [!danger] ★★★★★ ID 綁定是「同型號通吃」
> `ids=` 比對的是型號，不是插槽。
> **如果主機上有兩張一模一樣的卡，兩張都會被 vfio-pci 綁走。**
> 只想綁其中一張時，改用「依 PCI 位址綁定」（見進階應用）。

**C. 重建 initramfs ★★★★★**

```bash
update-initramfs -u -k all
```

```text
update-initramfs: Generating /boot/initrd.img-6.8.x-x-pve
Running hook script 'zz-proxmox-boot'..
	Copying kernel and creating boot-entry for 6.8.x-x-pve
```

★★★★★ **漏掉這一步，前面全部白做。** 這是本篇第二常見的失敗原因。

```bash
reboot
```

### 步驟八：確認 vfio-pci 真的接手了 ★★★★★

```bash
lspci -nnk -s 01:00.0
```

```text
01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA102 [10de:xxxx] (rev a1)
	Subsystem: ... [xxxx:xxxx]
	Kernel driver in use: vfio-pci
	Kernel modules: nvidiafb, nouveau
```

★★★★★ **`Kernel driver in use: vfio-pci` 才算成功。**
還是 `nouveau` 就回去檢查黑名單與 initramfs。

音效功能也要確認：

```bash
lspci -nnk -s 01:00.1 | grep 'driver in use'
```

```text
	Kernel driver in use: vfio-pci
```

---

## 進階應用

### 依 PCI 位址綁定（同型號多卡）★★★★

當主機上有兩張同型號的卡、只想直通其中一張時，`ids=` 不夠用，
改用 driver_override 的方式在開機早期指定：

```bash
cat > /etc/initramfs-tools/scripts/init-top/vfio-bind <<'EOF'
#!/bin/sh
PREREQ=""
prereqs() { echo "$PREREQ"; }
case $1 in prereqs) prereqs; exit 0;; esac

# ★★★★★ 換成你自己的 PCI 位址
for dev in 0000:01:00.0 0000:01:00.1; do
    echo "vfio-pci" > /sys/bus/pci/devices/$dev/driver_override 2>/dev/null
done
EOF
chmod +x /etc/initramfs-tools/scripts/init-top/vfio-bind
update-initramfs -u -k all
```

> [!warning] ★★★★ 位址會變
> PCI 位址（`01:00.0`）取決於**插槽**。換插槽、加卡、某些 BIOS 更新之後都可能改變。
> 用這種方式綁定時，**把插槽位置寫進機房文件**（見 [[040-02-11-guide-機房-資訊設備盤點]]）。

### 建立適合直通的 VM ★★★★★

直通對 VM 的硬體組態有硬性要求：

| 項目 | 設定 | 為什麼 |
| --- | --- | --- |
| ★★★★★ **Machine** | `q35` | ★★★★★ i440fx 沒有真正的 PCIe 匯流排 |
| ★★★★★ **BIOS** | `OVMF (UEFI)` | ★★★★ 現代 GPU 幾乎都需要 UEFI；同時要加 **EFI Disk** |
| ★★★★★ **CPU 型別** | `host` | 讓 guest 看到真實 CPU 特性，驅動才正常 |
| ★★★★ **記憶體 Ballooning** | **關閉** | ★★★★★ 直通要求記憶體預先配置 |
| ★★★ 顯示 Display | 先留 `Default`，直通成功再改 `none` | ★★★★ 太早改成 none，出事就沒有主控台可看 |
| ★★★ SCSI 控制器 | `VirtIO SCSI single` | 效能較好 |

GUI 路徑：**VM → Hardware → Add → PCI Device**。

指令做法：

```bash
# 假設 VM 是 200
qm set 200 --machine q35
qm set 200 --bios ovmf
qm set 200 --efidisk0 local-lvm:1,efitype=4m,pre-enrolled-keys=0
qm set 200 --cpu host
qm set 200 --balloon 0
qm set 200 --hostpci0 0000:01:00,pcie=1
```

```text
update VM 200: -hostpci0 0000:01:00,pcie=1
```

★★★★★ **注意 `0000:01:00` 沒有寫最後的 `.0`** ——
這樣寫代表「這個裝置的**所有功能**」，GPU 與它的 HDMI 音效會一起帶過去。
只想帶單一功能時才寫 `0000:01:00.0`。

檢視結果：

```bash
qm config 200 | grep -E 'machine|bios|cpu|hostpci|balloon'
```

```text
balloon: 0
bios: ovmf
cpu: host
hostpci0: 0000:01:00,pcie=1
machine: q35
```

#### `hostpci` 常用旗標 ★★★★

| 旗標 | 意義 | 注意 |
| --- | --- | --- |
| ★★★★★ `pcie=1` | 以 PCIe 裝置呈現（**需要 q35**） | 不加就是掛在虛擬 PCI 上，效能與相容性都較差 |
| ★★★★ `x-vga=1` | 標記為 VM 的主要顯示卡 | ★★★ 只在需要 VM 從這張卡出畫面時用 |
| ★★★ `rombar=0` | 不讓 VM 讀取裝置 ROM | ★★★ 某些卡在 OVMF 下需要 |
| ★★★ `romfile=<檔名>` | 指定自訂 VBIOS ROM | ★★★★ 檔案放在 `/usr/share/kvm/`，只在確定需要時用 |
| ★★★ `mdev=<型號>` | 使用 mediated device（vGPU） | ★★★★ 需要廠商支援與授權 |

> [!warning] ★★★★ `romfile` 不要亂用
> 網路上很多「抓一份別人的 VBIOS 就好」的說法。
> ★★★★★ **VBIOS 與板卡型號、記憶體顆粒、韌體版本綁定**，用錯的檔案輕則不開，
> 重則讓卡進入異常狀態。沒有明確需求就不要碰這個選項。

### GPU 直通給 AI 服務 ★★★★★

這是機關導入地端 AI 最常見的場景：一台有獨顯的主機，
把 GPU 交給一台 VM，VM 裡跑 [[110-02-01-svc-Ollama-安裝與GPU設定]] 的服務。

#### 決策：VM 直通 vs LXC 分享 ★★★★★

```
        要不要把 GPU 給虛擬機？
                 │
    ┌────────────┴────────────┐
    │                          │
「只有一個 AI 服務要用」   「多個服務要共用同一張卡」
    │                          │
    ▼                          ▼
可以用 VM 直通             ★★★★★ 用 LXC 容器
（隔離最徹底）              （多個容器可共用同一張卡）
    │                          │
    ▼                          ▼
★★★★ 不能遷移              ★★★★ 主機要裝 NVIDIA 驅動
★★★★ 主機不能用這張卡        ★★★ 隔離性較弱
```

| 比較項 | ★★★★ VM + PCIe 直通 | ★★★★★ LXC + 裝置分享 |
| --- | --- | --- |
| 隔離程度 | ★★★★★ 高（獨立核心） | ★★★ 中（共用主機核心） |
| 一張卡給幾台 | ★★★★★ **只能 1 台** | ★★★★★ **多個容器可同時用** |
| 驅動裝在哪 | VM 裡面 | ★★★★★ **主機與容器裡版本必須一致** |
| 主機能不能用 | ❌ 不行 | ✅ 可以 |
| 記憶體開銷 | 較大（整套 OS） | ★★★★ 很小 |
| 適合 | 需要強隔離、要跑 Windows | ★★★★★ **多個 AI 服務共用一張卡（最常見）** |

★★★★★ **實務建議：機關的 AI 主機如果同時要跑 Ollama + OpenWebUI + ComfyUI，
用 LXC 分享比 VM 直通划算得多**，因為一張卡可以同時服務多個容器。
LXC 的裝置分享做法見 [[050-01-03-04-guide-PVE-LXC容器管理]]。

#### VM 直通後在 guest 內的驗證 ★★★★

進入 VM（Ubuntu Server）：

```bash
lspci | grep -i nvidia
```

```text
01:00.0 VGA compatible controller: NVIDIA Corporation GA102 (rev a1)
01:00.1 Audio device: NVIDIA Corporation GA102 High Definition Audio (rev a1)
```

★★★★★ **看得到卡，才代表直通成功。** 接著才是裝驅動：
步驟見 [[110-01-03-guide-AI服務-NVIDIA驅動與CUDA環境]]。

裝完驅動：

```bash
nvidia-smi
```

```text
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 5xx.xx       Driver Version: 5xx.xx       CUDA Version: 12.x     |
|-------------------------------+----------------------+----------------------+
| GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
|   0  NVIDIA ...           Off | 00000000:01:00.0 Off |                  N/A |
+-------------------------------+----------------------+----------------------+
```

★★★★ 注意 `Bus-Id` 是 guest 內部的位址，不一定跟主機的一樣。

最後驗證 Ollama 真的吃到 GPU：

```bash
ollama run llama3 "hello"
nvidia-smi
```

★★★★★ 推論時 `nvidia-smi` 的 **GPU-Util 應該衝高、記憶體被佔用**。
如果推論很慢且 GPU-Util 一直是 0%，代表**還在用 CPU 跑**，
回頭看 [[110-02-01-svc-Ollama-安裝與GPU設定]] 的驅動與 CUDA 檢查。

### SR-IOV：一張網卡切給多台 VM ★★★

支援 SR-IOV 的伺服器網卡可以在硬體上切出多個 **VF（Virtual Function）**。

```
     PF (Physical Function)  ← 主機管理用
        ├── VF 0  →  VM 201
        ├── VF 1  →  VM 202
        └── VF 2  →  VM 203
     ★★★★ 每個 VF 都是獨立的 PCI 裝置，各自直通
```

啟用（★★★ 數字寫進 `sriov_numvfs`）：

```bash
# 先確認這張卡支援幾個 VF
cat /sys/class/net/enp3s0f0/device/sriov_totalvfs
```

```text
8
```

```bash
echo 4 > /sys/class/net/enp3s0f0/device/sriov_numvfs
lspci | grep -i 'virtual function'
```

```text
03:10.0 Ethernet controller: Intel Corporation ... Virtual Function
03:10.1 Ethernet controller: Intel Corporation ... Virtual Function
03:10.2 Ethernet controller: Intel Corporation ... Virtual Function
03:10.3 Ethernet controller: Intel Corporation ... Virtual Function
```

> [!warning] ★★★★ `echo` 到 sysfs 重開機就沒了
> 要持久化必須寫進 systemd unit 或 udev 規則。
> 而且 ★★★★ **改變 VF 數量會重新排列 PCI 位址**，
> 已經直通的 VM 設定可能全部失效 —— 一開始就決定好數量。

### USB 直通 ★★★

比 PCIe 簡單很多，**不需要 IOMMU**。

```bash
qm monitor 200
```

```text
qm> info usbhost
  Bus 1, Addr 5, Port 2, Speed 480 Mb/s
    Class 00: USB device 0403:6001, FT232 USB-Serial
qm> quit
```

兩種綁法：

```bash
# 依 vendor:product（★★★★ 換插槽也有效，但同型號多個會抓錯）
qm set 200 --usb0 host=0403:6001

# 依實體埠（★★★★ 換插槽就失效，但可以精準指定是哪一個孔）
qm set 200 --usb0 host=1-2
```

★★★★ **UPS 監控線、加密鎖（dongle）建議用 `host=<bus>-<port>` 綁埠**，
因為機關常常有多個同型號裝置。相關應用見 [[040-02-06-svc-機房-UPS安裝與監控設定]]。

### NVIDIA 消費級卡的 Code 43 ★★★★

Windows guest 裡 NVIDIA 驅動偵測到自己跑在虛擬機上時，
舊版驅動會拒絕運作，裝置管理員顯示 **Code 43**。

較新的 NVIDIA 驅動已經正式支援在 VM 內使用 GeForce 卡，
所以 ★★★★ **第一步永遠是「把 guest 的驅動更新到新版」**，而不是急著改設定。

若確實需要隱藏虛擬化特徵：

```bash
qm set 200 --cpu host,hidden=1
```

```text
update VM 200: -cpu host,hidden=1
```

> [!warning] ★★★★ 這類「隱藏 hypervisor」的技巧
> 只在明確遇到驅動拒絕載入時才用。
> ★★★ 隱藏 hypervisor 旗標會讓 guest 的部分半虛擬化最佳化失效，效能可能變差。

---

## 完整實戰範例

> **情境**：機關要建一台地端 AI 推論主機。
> 硬體是一台雙路 Xeon 伺服器，內建 BMC 顯示（主機用），
> 另插一張 NVIDIA 獨顯要交給一台 Ubuntu Server VM 跑 Ollama。
> 目標：**從 BIOS 開始，到 VM 裡的 `ollama` 真的用 GPU 出結果。**

### 環境

| 項目 | 值 |
| --- | --- |
| 主機 | `pve-ai01`，Proxmox VE 8 |
| 主機管理 IP | `10.10.0.31/24` |
| BMC（救命用） | `10.10.250.31` ★★★★★ |
| GPU | 插在 CPU 直連 x16 插槽 |
| VM | VMID `210`，Ubuntu Server 24.04，IP `10.10.20.210/24` |
| 主機顯示輸出 | BMC 內建顯示（★★★★ 不會被黑名單影響） |

> [!danger] ★★★★★ 動工前的三件事
> 1. **確認 BMC 可以進得去**，並實際登入一次 remote console。
> 2. 主機上如果已有正式服務，**先做完整備份**（[[050-01-03-06-svc-PVE-備份與還原]]）。
> 3. 這整套流程**至少會重開機三次**，安排在維護窗口做。

### 第 1 步：BIOS

從 BMC 進 BIOS，確認並開啟：

```text
[v] Intel Virtualization Technology (VT-x)     Enabled
[v] Intel VT for Directed I/O (VT-d)           Enabled
[v] Above 4G Decoding                          Enabled
[v] Primary Display                            Onboard / BMC
```

存檔重開。

### 第 2 步：確認 CPU 與開機路徑

```bash
grep -E -o 'vmx|svm' /proc/cpuinfo | sort -u
```

```text
vmx
```

```bash
proxmox-boot-tool status
```

```text
System currently booted with uefi
1234-ABCD is configured with: uefi (versions: 6.8.x-x-pve)
```

★★★★ 走 **systemd-boot**，所以改 `/etc/kernel/cmdline`。

### 第 3 步：加核心參數

```bash
cp /etc/kernel/cmdline /etc/kernel/cmdline.bak.$(date +%F)
cat /etc/kernel/cmdline
```

```text
root=ZFS=rpool/ROOT/pve-1 boot=zfs
```

改成：

```text
root=ZFS=rpool/ROOT/pve-1 boot=zfs intel_iommu=on iommu=pt
```

```bash
proxmox-boot-tool refresh
reboot
```

### 第 4 步：驗證 IOMMU（★★★★★ 沒過就不要往下）

```bash
dmesg | grep -i -e DMAR -e IOMMU | head
```

```text
[    0.298765] DMAR: IOMMU enabled
[    0.512345] DMAR: Intel(R) Virtualization Technology for Directed I/O
[    0.512400] DMAR-IR: Enabled IRQ remapping in x2apic mode
```

```bash
ls /sys/kernel/iommu_groups/ | wc -l
```

```text
38
```

✅ 通過。

### 第 5 步：找卡、看群組

```bash
lspci -nn | grep -i nvidia
```

```text
01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA102 [10de:xxxx] (rev a1)
01:00.1 Audio device [0403]: NVIDIA Corporation GA102 High Definition Audio [10de:yyyy] (rev a1)
```

```bash
/usr/local/bin/iommu-groups.sh | grep -E 'Group (14|15) '
```

```text
IOMMU Group 14  01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA102 [10de:xxxx] (rev a1)
IOMMU Group 14  01:00.1 Audio device [0403]: NVIDIA Corporation GA102 High Definition Audio [10de:yyyy] (rev a1)
```

★★★★★ **Group 14 只有這張卡的兩個功能，沒有夾雜主機在用的裝置 → 可以直通。**

記下要用的 ID：`10de:xxxx`、`10de:yyyy`。

### 第 6 步：模組、黑名單、綁定

```bash
cat >> /etc/modules <<'EOF'

# --- PCIe passthrough ---
vfio
vfio_iommu_type1
vfio_pci
EOF

cat > /etc/modprobe.d/blacklist-gpu.conf <<'EOF'
blacklist nouveau
blacklist nvidia
blacklist nvidiafb
blacklist nvidia_drm
EOF

cat > /etc/modprobe.d/vfio.conf <<'EOF'
options vfio-pci ids=10de:xxxx,10de:yyyy disable_vga=1
EOF

update-initramfs -u -k all
```

```text
update-initramfs: Generating /boot/initrd.img-6.8.x-x-pve
Running hook script 'zz-proxmox-boot'..
	Copying kernel and creating boot-entry for 6.8.x-x-pve
```

```bash
reboot
```

### 第 7 步：確認 vfio-pci 接手 ★★★★★

```bash
lspci -nnk -s 01:00.0 | grep -E 'driver in use|Kernel modules'
lspci -nnk -s 01:00.1 | grep -E 'driver in use'
```

```text
	Kernel driver in use: vfio-pci
	Kernel modules: nvidiafb, nouveau
	Kernel driver in use: vfio-pci
```

```bash
ls -l /dev/vfio/
```

```text
total 0
crw------- 1 root root 241,   0 Sep  2 10:12 14
crw-rw-rw- 1 root root  10, 196 Sep  2 10:12 vfio
```

★★★★ `/dev/vfio/14` 出現，數字對應 IOMMU 群組編號 —— **這是最直接的成功證據**。

### 第 8 步：建立 VM

```bash
qm create 210 \
  --name ai-ollama01 \
  --machine q35 \
  --bios ovmf \
  --cpu host \
  --sockets 1 --cores 8 \
  --memory 32768 --balloon 0 \
  --scsihw virtio-scsi-single \
  --net0 virtio,bridge=vmbr0,tag=20 \
  --ostype l26 \
  --agent 1
```

```text
```

（`qm create` 成功時沒有輸出，★★★ 這是正常的。）

```bash
qm set 210 --efidisk0 local-zfs:1,efitype=4m,pre-enrolled-keys=0
qm set 210 --scsi0 local-zfs:200,discard=on,ssd=1
qm set 210 --ide2 local:iso/ubuntu-24.04-live-server-amd64.iso,media=cdrom
qm set 210 --boot order='scsi0;ide2'
```

★★★★ **先不要加 GPU**，用一般虛擬顯示把 OS 裝好、SSH 通了再說。

### 第 9 步：裝好 OS，設定 SSH

在 VM 內：

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install openssh-server qemu-guest-agent
sudo systemctl enable --now qemu-guest-agent
ip -4 addr show | grep inet
```

```text
    inet 127.0.0.1/8 scope host lo
    inet 10.10.20.210/24 metric 100 brd 10.10.20.255 scope global ens18
```

從別台機器確認 SSH：

```bash
ssh ubuntu@10.10.20.210 'uname -r'
```

```text
6.8.0-xx-generic
```

★★★★★ **這一步過了，之後 GPU 直通把畫面搞爛也還有 SSH 可以救。**

### 第 10 步：把 GPU 掛進去

```bash
qm shutdown 210
qm status 210
```

```text
status: stopped
```

```bash
qm set 210 --hostpci0 0000:01:00,pcie=1
qm config 210 | grep -E 'hostpci|machine|bios|balloon|cpu'
```

```text
balloon: 0
bios: ovmf
cpu: host
hostpci0: 0000:01:00,pcie=1
machine: q35
```

```bash
qm start 210
```

### 第 11 步：guest 內驗證 ★★★★★

```bash
ssh ubuntu@10.10.20.210
lspci | grep -i nvidia
```

```text
01:00.0 VGA compatible controller: NVIDIA Corporation GA102 (rev a1)
01:00.1 Audio device: NVIDIA Corporation GA102 High Definition Audio (rev a1)
```

✅ **卡進去了。**

裝驅動（詳細見 [[110-01-03-guide-AI服務-NVIDIA驅動與CUDA環境]]）：

```bash
sudo ubuntu-drivers devices
```

```text
== /sys/devices/pci0000:00/0000:00:10.0/0000:01:00.0 ==
modalias : pci:v000010DEd0000xxxxsv...
vendor   : NVIDIA Corporation
driver   : nvidia-driver-5xx - distro non-free recommended
```

```bash
sudo apt -y install nvidia-driver-5xx
sudo reboot
```

重開後：

```bash
nvidia-smi
```

```text
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 5xx.xx       Driver Version: 5xx.xx       CUDA Version: 12.x     |
|   0  NVIDIA ...           Off | 00000000:01:00.0 Off |                  N/A |
| 30%   42C    P8    22W / 350W |      1MiB / 24576MiB |      0%      Default |
+-----------------------------------------------------------------------------+
```

### 第 12 步：裝 Ollama 並確認真的用到 GPU

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

```text
>>> Installing ollama to /usr/local
>>> NVIDIA GPU installed.
```

★★★★★ 安裝腳本輸出的 `NVIDIA GPU installed.` 就是第一個好訊號。

```bash
ollama pull llama3
ollama run llama3 "用一句話說明什麼是 IOMMU"
```

另開一個 SSH 連線，推論時同步觀察：

```bash
watch -n1 nvidia-smi
```

```text
| 68%   71C    P2   240W / 350W |   6420MiB / 24576MiB |     94%      Default |
```

★★★★★ **GPU-Util 衝到 90% 以上、記憶體被佔用 —— 直通確實生效。**

### 第 13 步：收尾（★★★★ 最容易被忘記的一步）

```bash
# 1. 記錄設定，收進維運文件
qm config 210 > /root/docs/vm210-config-$(date +%F).txt

# 2. 把「這台不能遷移」寫進註解
qm set 210 --description "AI 推論主機。★★★★★ 有 GPU 直通（0000:01:00），不可線上遷移、不納入 HA。"

# 3. 立即做一次備份
vzdump 210 --storage backup-nfs --mode snapshot --compress zstd
```

```text
INFO: Starting Backup of VM 210 (qemu)
INFO: creating vzdump archive '/mnt/pve/backup-nfs/dump/vzdump-qemu-210-2026_09_02-11_30_00.vma.zst'
INFO: Backup job finished successfully
```

同時更新：

- 機房文件：**這張卡插在哪個插槽**（[[040-02-11-guide-機房-資訊設備盤點]]）
- 叢集規劃：**VM 210 排除在 HA 之外**（[[050-01-03-07-svc-PVE-叢集與高可用]]）
- 變更紀錄（[[100-02-08-guide-維運-變更管理流程]]）

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `ls /sys/kernel/iommu_groups/` 是空的 | BIOS 沒開 VT-d／IOMMU，或核心參數加錯地方 | 進 BIOS 開；用 `proxmox-boot-tool status` 確認是 GRUB 還是 systemd-boot，改對應檔案 |
| ★★★★★ 參數加了但 `/proc/cmdline` 沒有 | 改了 `/etc/default/grub` 卻沒跑 `update-grub`，或改了 `/etc/kernel/cmdline` 卻沒跑 `proxmox-boot-tool refresh` | 跑對應的套用指令再重開 |
| ★★★★★ `lspci -nnk` 顯示 `Kernel driver in use: nouveau` | 黑名單或 vfio.conf 沒進 initramfs | 跑 `update-initramfs -u -k all` 後重開 |
| ★★★★★ VM 啟動報 `vfio 0000:01:00.0: group 14 is not viable` | ★★★★★ **同群組還有裝置沒綁 vfio-pci** | 用 `iommu-groups.sh` 看群組成員，把整組都綁上，或換插槽 |
| ★★★★ `failed to open /dev/vfio/14: Device or resource busy` | 該裝置已被另一台執行中的 VM 佔用 | `qm list` 找出誰在用；一張卡只能給一台 |
| ★★★★ `dmesg`：`vfio-pci 0000:01:00.0: BAR 3: can't reserve [mem 0x...]` | ★★★★ 韌體 framebuffer（efifb／simplefb）佔住了顯示卡的記憶體區段 | BIOS 把主要顯示改成內顯／BMC；仍不行再加 `initcall_blacklist=sysfb_init` |
| ★★★★ 主機重開後主控台一片黑 | 顯示卡被 vfio-pci 接管或 framebuffer 被關掉 | ★★★★ 這是預期行為，改用 SSH／BMC 管理 |
| ★★★★ VM 開得起來但 `lspci` 在 guest 內看不到卡 | `machine` 不是 q35，或 `pcie=1` 沒加 | `qm set <id> --machine q35 --hostpci0 <addr>,pcie=1` |
| ★★★★ Windows 裝置管理員 **Code 43** | 舊版 NVIDIA 驅動拒絕在 VM 內運作，或 VBIOS 問題 | ★★★★ **先把驅動更新到新版**；必要時 `--cpu host,hidden=1` |
| ★★★★ VM 開機卡在 UEFI 畫面 | 沒加 EFI Disk，或 `boot order` 沒設對 | 加 `--efidisk0`，檢查 `qm config` 的 `boot:` |
| ★★★★ `nvidia-smi` 在 guest 回 `No devices were found` | 驅動沒裝／版本不合／nouveau 在 guest 裡搶走 | guest 內也要黑名單 nouveau，重裝官方驅動 |
| ★★★★ 遷移時報 `can't migrate VM with local resources` | ★★★★★ 有 `hostpci` 就不能線上遷移 | 關機後離線遷移，且目標節點要有同位址同款卡 |
| ★★★★ HA 把 VM 切到別節點後起不來 | 目標節點沒有那張卡 | ★★★★★ 直通 VM 不要放進 HA 群組 |
| ★★★ `modprobe: FATAL: Module vfio_virqfd not found` | 新核心已把它併入 vfio | 從 `/etc/modules` 拿掉這行 |
| ★★★ 兩張同型號的卡都被 vfio-pci 綁走 | `ids=` 是比對型號不是插槽 | 改用 `driver_override` 依 PCI 位址綁定 |
| ★★★ 換插槽後 VM 起不來 | PCI 位址變了 | `lspci` 重新查位址，`qm set` 改 `hostpci0` |
| ★★★ SR-IOV 的 VF 重開機後消失 | `sriov_numvfs` 寫在 sysfs，不持久 | 用 systemd unit 或 udev 規則在開機時設定 |
| ★★★ 直通後 VM 記憶體用量顯示異常 | 直通會 pin 住全部記憶體 | 這是正常的；把 balloon 設成 0 並如實規劃容量 |

### 排查流程（★★★★★ 依序做，不要跳）

```
① 主機層：IOMMU 有沒有起來？
   ls /sys/kernel/iommu_groups/ | wc -l   →  0 就停在這裡修
   dmesg | grep -i -e DMAR -e IOMMU
        │ OK
        ▼
② 群組層：這張卡的群組乾不乾淨？
   /usr/local/bin/iommu-groups.sh
        │ 群組內有主機在用的裝置 → ★★★★★ 換插槽，不要硬幹
        ▼
③ 驅動層：vfio-pci 接手了嗎？
   lspci -nnk -s <addr> | grep 'driver in use'
        │ 不是 vfio-pci → 檢查 blacklist + update-initramfs
        ▼
④ 裝置節點：/dev/vfio/<群組號> 存在嗎？
   ls -l /dev/vfio/
        │ 不存在 → 回 ③
        ▼
⑤ VM 層：machine=q35？bios=ovmf？pcie=1？balloon=0？
   qm config <vmid>
        │ 缺一項就補
        ▼
⑥ Guest 層：lspci 看得到卡嗎？
        │ 看不到 → 回 ⑤
        ▼
⑦ 驅動層（guest）：nvidia-smi 有輸出嗎？
        │ 沒有 → guest 裡的驅動問題，不是直通問題
        ▼
   ✅ 完成
```

### 讀 `dmesg` 的重點字串 ★★★★

```bash
dmesg | grep -i -E 'vfio|dmar|iommu|amd-vi' | tail -30
```

| 你看到 | 意思 |
| --- | --- |
| ★★★★★ `DMAR: IOMMU enabled` | IOMMU 起來了 |
| ★★★★ `DMAR-IR: Enabled IRQ remapping` | 中斷重映射正常 |
| ★★★★ `vfio-pci 0000:01:00.0: vgaarb: ...` | vfio-pci 已接手該裝置 |
| ★★★★★ `group N is not viable` | 群組內有裝置沒被綁 |
| ★★★★ `BAR N: can't reserve` | framebuffer 佔住記憶體區段 |
| ★★★ `Device is ineligible for IOMMU domain attach` | 該裝置不能單獨直通 |

---

## 安全性注意事項

### ★★★★★ 直通把「硬體攻擊面」交給了 VM

| 風險 | 說明 | 對策 |
| --- | --- | --- |
| ★★★★★ **裝置韌體被竄改** | VM 內的 root 可以刷卡上的韌體（VBIOS、網卡 firmware），**主機重開後仍在** | 只把裝置給**你信任的 VM**；汰換時**當作已污染處理** |
| ★★★★★ **ACS override 破壞隔離** | 同群組裝置可繞過 IOMMU 互相 DMA | ★★★★★ **正式環境不要用**，改換插槽或換平台 |
| ★★★★ **`allow_unsafe_interrupts`** | 關掉中斷重映射的保護 | ★★★★★ 不要開；平台不支援就換平台 |
| ★★★★ **裝置殘留資料** | GPU 記憶體、NVMe 上的資料在換手給另一台 VM 時可能殘留 | 換手前**主機端重開機**，敏感環境考慮實體換卡 |
| ★★★★ **VM 逃逸的破口變大** | 直通增加了 QEMU/VFIO 的攻擊面 | 保持 PVE 與 QEMU 更新（[[050-01-03-11-svc-PVE-升級與維護]]） |
| ★★★ **主機失去可觀測性** | 主機看不到卡的內部狀態 | 監控改在 guest 內做（[[110-01-08-guide-AI服務-AI服務監控與日誌]]） |

### 可用性風險必須寫進文件 ★★★★★

```
★★★★★ 直通 VM 的災難復原不能靠「切到另一節點」

  必須明確回答的三個問題：
  ① 這張卡壞了，多久可以換到？（備品／保固）
  ② 卡換了之後，VM 設定要改哪裡？（PCI 位址可能不同）
  ③ 這段期間服務怎麼降級運作？（改用 CPU 推論？停用？）
```

★★★★ 把這三題的答案寫進
[[100-02-09-svc-維運-事件處理與升級流程]] 與 [[100-02-13-guide-維運-資產與授權管理]]。

### 權限控管 ★★★★

- ★★★★ PVE 上**只有 root@pam 或有 `Sys.Modify`／`VM.Config.HWType` 權限的人**才能改 `hostpci`。
  一般操作員不要給這個權限，否則他可以把主機正在用的裝置搶走。
  設定方式見 [[050-01-03-08-guide-PVE-使用者權限與API]]。
- ★★★ **guest 內的 root 權限要當成「等同對這張卡有完整實體存取」來管**。

### 稽核與記錄 ★★★

```bash
# 把當前的直通配置留檔，變更管理用
{
  echo "=== $(date -Is) $(hostname) ==="
  /usr/local/bin/iommu-groups.sh
  echo "--- vfio bound ---"
  lspci -nnk | grep -B2 'driver in use: vfio-pci'
  echo "--- VM hostpci ---"
  grep -H hostpci /etc/pve/qemu-server/*.conf
} > /root/docs/passthrough-$(date +%F).txt
```

```text
（檔案內容示意）
=== 2026-09-02T11:45:00+08:00 pve-ai01 ===
IOMMU Group 14  01:00.0 VGA compatible controller ...
--- VM hostpci ---
/etc/pve/qemu-server/210.conf:hostpci0: 0000:01:00,pcie=1
```

---

## 速查表

### 檢查指令 ★★★★★

| 目的 | 指令 |
| --- | --- |
| ★★★★★ 確認 CPU 虛擬化 | `grep -Eo 'vmx\|svm' /proc/cpuinfo \| sort -u` |
| ★★★★★ 確認 IOMMU 起來 | `dmesg \| grep -i -e DMAR -e IOMMU` |
| ★★★★★ 群組數量 | `ls /sys/kernel/iommu_groups/ \| wc -l` |
| ★★★★★ 列出所有群組 | `/usr/local/bin/iommu-groups.sh` |
| ★★★★★ 查裝置 ID | `lspci -nn` |
| ★★★★★ 查誰在用這張卡 | `lspci -nnk -s 01:00.0` |
| ★★★★ 確認 vfio 節點 | `ls -l /dev/vfio/` |
| ★★★★ 目前生效的核心參數 | `cat /proc/cmdline` |
| ★★★★ 開機路徑（GRUB/systemd-boot） | `proxmox-boot-tool status` |
| ★★★ 中斷重映射 | `dmesg \| grep -i remapping` |
| ★★★ 列出可直通的 USB | `qm monitor <vmid>` → `info usbhost` |

### 檔案位置 ★★★★★

| 檔案 | 用途 | 改完要跑 |
| --- | --- | --- |
| ★★★★★ `/etc/kernel/cmdline` | systemd-boot 的核心參數 | `proxmox-boot-tool refresh` |
| ★★★★★ `/etc/default/grub` | GRUB 的核心參數 | `update-grub` |
| ★★★★★ `/etc/modules` | 開機載入的模組 | `update-initramfs -u -k all` |
| ★★★★★ `/etc/modprobe.d/vfio.conf` | vfio-pci 綁定 ID | `update-initramfs -u -k all` |
| ★★★★★ `/etc/modprobe.d/blacklist-gpu.conf` | 黑名單原生驅動 | `update-initramfs -u -k all` |
| ★★★★ `/etc/pve/qemu-server/<vmid>.conf` | VM 設定（含 `hostpci`） | 重開該 VM |
| ★★★ `/sys/kernel/iommu_groups/` | 群組資訊（唯讀） | — |
| ★★★ `/dev/vfio/<群組號>` | 直通用的裝置節點 | — |

### 核心參數 ★★★★

| 參數 | 平台 | 用途 |
| --- | --- | --- |
| ★★★★★ `intel_iommu=on` | Intel | 開 IOMMU |
| ★★★★★ `amd_iommu=on` | AMD | 開 IOMMU |
| ★★★★ `iommu=pt` | 兩者 | passthrough 模式 |
| ★★★★★ `pcie_acs_override=downstream,multifunction` | 兩者 | ★★★★★ 強拆群組，**有安全代價** |
| ★★★ `initcall_blacklist=sysfb_init` | 兩者 | 阻止 framebuffer 佔住顯卡 |
| ★★★ `video=efifb:off` | 兩者 | 舊寫法，同上目的 |

### `qm set` 直通相關 ★★★★

| 指令 | 說明 |
| --- | --- |
| ★★★★★ `qm set <id> --machine q35` | 改成 q35 |
| ★★★★★ `qm set <id> --bios ovmf` | 改成 UEFI（要一起加 efidisk） |
| ★★★★★ `qm set <id> --hostpci0 0000:01:00,pcie=1` | 直通整個裝置的所有功能 |
| ★★★★ `qm set <id> --hostpci0 0000:01:00.0,pcie=1,x-vga=1` | 只給功能 0 並當主顯示 |
| ★★★★ `qm set <id> --balloon 0` | 關掉記憶體氣球 |
| ★★★★ `qm set <id> --cpu host` | CPU 直通型別 |
| ★★★ `qm set <id> --cpu host,hidden=1` | 隱藏 hypervisor 特徵 |
| ★★★ `qm set <id> --usb0 host=1-2` | USB 依實體埠直通 |
| ★★★ `qm set <id> --delete hostpci0` | 移除直通 |

### 判定速查 ★★★★★

| 看到 | 結論 |
| --- | --- |
| ★★★★★ `Kernel driver in use: vfio-pci` | 主機層準備好了 |
| ★★★★★ `/dev/vfio/<N>` 存在 | 群組已可用 |
| ★★★★★ guest 內 `lspci` 看得到卡 | 直通成功 |
| ★★★★★ `nvidia-smi` 有輸出且 Util 會動 | 驅動與運算都正常 |
| ★★★★★ `group N is not viable` | 群組沒綁乾淨 |
| ★★★★ `can't migrate VM with local resources` | 直通導致，正常現象 |

---

## 練習題

1. 在你的 PVE 主機上啟用 IOMMU，並產生一份完整的 IOMMU 群組清單，
   標出哪些群組**可以安全直通**、哪些**不行**（列出理由）。
2. 找一個「不會影響主機運作」的裝置（例如多餘的網卡、USB 控制器），
   完成 vfio-pci 綁定，並確認 `/dev/vfio/` 出現對應節點。
3. 建立一台 q35 + OVMF 的測試 VM，把上題的裝置直通進去，
   在 guest 內用 `lspci` 驗證，然後**移除直通**並確認裝置回到主機手上。
4. 對一台有 `hostpci` 的 VM 嘗試線上遷移，把**錯誤訊息原文抄下來**，
   再說明為什麼會這樣。
5. 寫一份「GPU 直通主機的災難復原程序」，回答本篇「可用性風險」那三個問題。

> [!question]- 練習解答
>
> **1.**
> ```bash
> # 啟用（systemd-boot）
> cp /etc/kernel/cmdline /etc/kernel/cmdline.bak
> # 在同一行末尾加 intel_iommu=on iommu=pt
> proxmox-boot-tool refresh && reboot
>
> # 產生清單
> /usr/local/bin/iommu-groups.sh > /root/docs/iommu-$(hostname)-$(date +%F).txt
> ```
> 判定原則：
> - ★★★★★ **群組內出現 SATA / NVMe / 開機用網卡 → 不可直通**（主機自己在用）。
> - ★★★ 群組內只有 PCI bridge + 目標卡 → 可以。
> - ★★★★ 群組內有另一張你不打算給出去的卡 → 不可，要先換插槽。
>
> **2.**
> ```bash
> lspci -nn | grep -i ethernet       # 找 ID，例如 8086:zzzz
> echo 'options vfio-pci ids=8086:zzzz' > /etc/modprobe.d/vfio.conf
> update-initramfs -u -k all && reboot
> lspci -nnk -s 03:00.0 | grep 'driver in use'   # 應為 vfio-pci
> ls -l /dev/vfio/
> ```
> ★★★★★ **絕對不要拿主機管理 IP 用的那張網卡做這題**，會失聯。
>
> **3.**
> ```bash
> qm create 999 --machine q35 --bios ovmf --cpu host --memory 2048 --balloon 0 \
>   --net0 virtio,bridge=vmbr0 --ostype l26
> qm set 999 --efidisk0 local-lvm:1,efitype=4m
> qm set 999 --scsi0 local-lvm:16 --ide2 local:iso/<你的 iso>,media=cdrom
> qm set 999 --hostpci0 0000:03:00,pcie=1
> qm start 999
> # guest 內：lspci
>
> # 移除
> qm shutdown 999
> qm set 999 --delete hostpci0
> ```
> ★★★★ 移除 `hostpci` 後裝置**不會**自動回到原生驅動，
> 因為 `/etc/modprobe.d/vfio.conf` 還綁著它 —— 要把設定移掉並
> `update-initramfs -u -k all` 後重開，或手動 `modprobe -r vfio-pci` 再綁回。
>
> **4.**
> ```bash
> qm migrate 210 pve-ai02 --online
> ```
> 會看到類似 `can't migrate VM with local resources: hostpci0` 的錯誤。
> ★★★★★ 原因：直通裝置的狀態（暫存器、DMA 對映、卡上記憶體）
> **QEMU 無法序列化搬到另一台機器**，記憶體也被 pin 住不能做迭代複製。
>
> **5.** 復原程序至少要包含：
> - ★★★★★ 備品卡的存放位置與型號（與現役完全相同型號最好）
> - ★★★★★ 換卡後的檢查清單：`lspci -nn` 確認新位址 → `qm set --hostpci0` 改位址 → 開機驗證 `nvidia-smi`
> - ★★★★ 降級方案：Ollama 改用 CPU 推論（慢但可用）或導到備援節點
> - ★★★★ RTO 承諾與通報對象

---

## 小測驗

**Q1.** IOMMU 主要解決什麼問題？
（A）讓 CPU 跑更多虛擬機　（B）限制 PCIe 裝置只能 DMA 到被允許的記憶體範圍
（C）加速磁碟 I/O　（D）壓縮虛擬機記憶體

**Q2.** 是非題：Intel 平台只要在 BIOS 開了 `Intel Virtualization Technology (VT-x)`，
就可以做 PCIe 直通。

**Q3.** `ls /sys/kernel/iommu_groups/ | wc -l` 回傳 `0`，代表什麼？下一步該做什麼？

**Q4.** 你想直通的顯示卡在 IOMMU Group 12，同一群組裡還有主機系統碟用的 SATA 控制器。
下列哪個做法在**機關正式環境**最恰當？
（A）加 `pcie_acs_override=downstream`　（B）把 SATA 控制器也一起直通
（C）把顯示卡換到 CPU 直連的插槽再看群組　（D）改用 `allow_unsafe_interrupts`

**Q5.** 這行指令會發生什麼？

```bash
qm set 210 --hostpci0 0000:01:00,pcie=1
```

**Q6.** 簡答：為什麼改完 `/etc/modprobe.d/vfio.conf` 一定要跑
`update-initramfs -u -k all`？

**Q7.** VM 啟動時報 `vfio 0000:01:00.0: group 14 is not viable`，
最可能的原因是什麼？

**Q8.** 是非題：`options vfio-pci ids=10de:xxxx` 只會綁定 `01:00.0` 這一張卡。

**Q9.** 機關要在一台主機上同時跑 Ollama、OpenWebUI、ComfyUI，共用一張 GPU。
用 VM 直通還是 LXC 分享比較合適？為什麼？

**Q10.** 一台有 `hostpci0` 的 VM 被放進 HA 群組，節點故障後 HA 把它切到另一節點。
會發生什麼事？

> [!question]- 測驗答案
>
> **Q1 → (B)** ★★★★★
> IOMMU 是裝置端的位址轉譯與隔離單元，防止裝置的 DMA 讀寫到不該碰的記憶體。
> 見「IOMMU 是什麼」。
>
> **Q2 → 否** ★★★★★
> VT-x 是 **CPU 虛擬化**，直通需要的是 **VT-d（IOMMU）**，兩個是不同選項、
> 常放在 BIOS 的不同頁籤。見「VT-x 與 VT-d 是兩件事」。
>
> **Q3 → IOMMU 沒有啟用。** ★★★★★
> 下一步：① 進 BIOS 確認 VT-d／IOMMU 已開；
> ② 用 `proxmox-boot-tool status` 判斷是 GRUB 還是 systemd-boot，
> 把 `intel_iommu=on`／`amd_iommu=on` 加到**正確的檔案**並跑對應的套用指令。
> 見「步驟二」「步驟三」。
>
> **Q4 → (C)** ★★★★★
> (A)(D) 都是拿掉硬體隔離保證，正式環境不可接受；
> (B) 會讓主機失去系統碟直接死機。
> ★★★★ 換插槽是零風險且最常成功的做法。見「遇到群組黏在一起，你的選項」。
>
> **Q5 →** 把主機上 PCI 位址 `0000:01:00` 的**所有功能**
> （例如 `.0` 顯示與 `.1` 音效）以 **PCIe 裝置**的形式加到 VM 210。
> ★★★★ 注意末尾沒寫 `.0` 就是「整個裝置」；
> ★★★★★ 且 `pcie=1` 要能生效，VM 的 machine 必須是 **q35**。見「建立適合直通的 VM」。
>
> **Q6 →** 因為原生驅動（nouveau／amdgpu）在**開機很早期**就會搶走裝置。
> ★★★★★ 黑名單與 vfio 綁定必須存在於 **initramfs** 裡才來得及生效，
> 只寫在磁碟上的 `/etc/modprobe.d/` 會太晚。見「vfio-pci：把裝置從主機手上拿走」。
>
> **Q7 → 同一個 IOMMU 群組裡還有裝置沒有綁定到 vfio-pci。** ★★★★★
> 群組必須整組交出去。用 `iommu-groups.sh` 看群組成員，
> 把同組的其他裝置也綁上，或換插槽拆開群組。見「常見錯誤與排錯」。
>
> **Q8 → 否** ★★★★
> `ids=` 比對的是 **vendor:device 型號**，不是插槽位址。
> 主機上任何同型號的卡都會被綁走。要指定單張請用 `driver_override`
> 依 PCI 位址綁定。見「依 PCI 位址綁定」。
>
> **Q9 → LXC 分享。** ★★★★★
> 一張卡透過 PCIe 直通**只能給一台 VM**；LXC 走的是裝置節點分享，
> 多個容器可以同時使用同一張卡，記憶體開銷也小得多。
> 代價是隔離性較弱、主機與容器的驅動版本必須一致。
> 見「決策：VM 直通 vs LXC 分享」。
>
> **Q10 → VM 會在新節點啟動失敗**（新節點沒有那個 PCI 位址的卡，
> 或有卡但位址不同）。★★★★★ **直通 VM 不應納入 HA**，
> 應改用備份 + 備品機的復原策略。見「直通後不能做的事」與「安全性注意事項」。

---

## 延伸閱讀

### 本手冊

- [[050-01-03-03-guide-PVE-虛擬機管理]] — machine type、BIOS、CPU 型別的完整說明
- [[050-01-03-04-guide-PVE-LXC容器管理]] — ★★★★★ 多服務共用 GPU 的正解
- [[050-01-03-07-svc-PVE-叢集與高可用]] — 為什麼直通 VM 要排除在 HA 之外
- [[050-01-03-06-svc-PVE-備份與還原]] — 直通 VM 的備份策略
- [[050-01-03-11-svc-PVE-升級與維護]] — 核心升級後直通可能要重新驗證
- [[050-01-03-12-guide-PVE-故障排除]] — 主機層的整體排查
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] — 硬體輔助虛擬化的原理
- [[020-01-26-guide-Linux-核心模組與sysctl調校]] — modprobe 與 initramfs
- [[020-01-25-guide-Linux-開機流程與GRUB救援]] — ★★★★ 改壞開機參數的救援
- [[020-01-27-cmd-Linux-硬體資訊與裝置管理]] — `lspci` 進階用法
- [[110-01-03-guide-AI服務-NVIDIA驅動與CUDA環境]] — guest 內的驅動安裝
- [[110-02-01-svc-Ollama-安裝與GPU設定]] — ★★★★ 直通完成後的下一步
- [[110-01-01-guide-AI服務-地端AI系統總覽與架構規劃]] — AI 主機的整體規劃
- [[110-01-07-svc-AI服務-AI服務效能調校]] — GPU 資源的實際運用
- [[040-02-11-guide-機房-資訊設備盤點]] — 插槽位置要寫進文件
- [[100-02-08-guide-維運-變更管理流程]] — 直通變更要留紀錄

### 外部資源

- Proxmox VE 官方 wiki：**PCI(e) Passthrough**（★★★★★ 動手前先看當前版本）
- Proxmox VE 官方 wiki：**PCI Passthrough / GPU Passthrough** 的硬體相容性討論
- Linux 核心文件：`Documentation/driver-api/vfio.rst`（VFIO 架構說明）
- 你的主機板／伺服器廠商手冊：**IOMMU 與 PCIe 插槽拓撲**（★★★★ 判斷換哪個插槽時最有用）
- NVIDIA 官方驅動下載頁與 Linux 驅動說明文件
