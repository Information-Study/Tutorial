---
title: "安裝與virt-manager"
desc: "硬體支援檢查與巢狀虛擬化、套件安裝（Ubuntu 與 RHEL）、libvirt 群組與權限為什麼要重新登入、system 與 session 模式的差別，以及用 virt-manager 建出第一台 VM"
aliases: [kvm-ok, virt-manager, libvirt 群組, qemu session 模式, qemu system 模式, virt-host-validate]
tags: [群組/虛擬機與容器, 虛擬化/kvm, 主題/虛擬化]
category: 虛擬化平台
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-04-01-guide-KVM-KVM與libvirt架構]]", "[[020-01-14-guide-Linux-套件管理]]"]
updated: 2026-09-02
---

# 安裝與virt-manager

> [!note] 本章在本手冊裡的定位
> 本手冊的虛擬化**主線是 VMware Workstation（桌面測試環境）與 Proxmox VE（機關正式環境）**。
> KVM 章屬於輔助線，供**單機 Linux 虛擬化**與**理解 PVE 底層**之用。
> 平台之間的取捨請見 [[050-01-01-03-ref-虛擬化-五平台橫向對照]]。

> [!warning] 未實機驗證
> 本篇以 **Ubuntu Server 24.04 LTS** 為主線、**Rocky Linux 9** 為對照。
> 套件名稱（`qemu-kvm` 在新版 Ubuntu 已是轉移套件）、
> 守護行程單元名稱（`libvirtd` vs `virtqemud`）、
> `virt-manager` 的選單文字都會隨版本改變。
> **動手前請以 `apt search` / `dnf search` 與 `systemctl list-units` 的實際輸出為準**。
> 步驟邏輯、權限模型與排錯思路不受版本影響。

> [!abstract] 這篇你會學到
> - ★★★★★ **硬體支援怎麼確認**：`kvm-ok`、`/dev/kvm`、CPU 旗標，三個都要看
> - ★★★★★ **本手冊的假設環境是「VMware Workstation 裡的 Ubuntu Server 再裝 KVM」**，
>   所以**巢狀虛擬化必須先開**，這一步沒做後面全部白費
> - 套件到底要裝哪些（Ubuntu 與 RHEL 系完整對照），以及哪些是可以不裝的 ★★★★
> - ★★★★★ **`libvirt` 群組與權限**：為什麼加了群組還要**重新登入**、
>   `newgrp` 能不能救、`id` 與 `groups` 為什麼結果不一樣
> - ★★★★★ **`qemu:///system` 與 `qemu:///session` 的差別** —— 新手 90% 的
>   「我的 VM 不見了」都是這個
> - `virt-manager` 圖形化建立第一台 VM 的**完整流程**，每一頁每個選項怎麼選 ★★★★
> - ★★★★ **遠端管理**：在有桌面的機器上用 `qemu+ssh://` 管遠端的無頭伺服器
> - 沒有桌面環境時的替代方案（Cockpit、X11 forwarding、`virt-install`）★★★

## 前置知識

- [[050-01-04-01-guide-KVM-KVM與libvirt架構]] — **必讀**，本篇假設你知道三層分工
- [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] — ★★★★★ **巢狀虛擬化怎麼開**
- [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] — 先有一台 Ubuntu Server VM
- [[020-01-14-guide-Linux-套件管理]] — `apt` / `dnf`
- [[020-01-09-cmd-Linux-使用者與群組管理]] — 群組、`usermod`、`id`
- [[020-01-08-cmd-Linux-檔案權限與擁有者]] — 裝置檔權限
- [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] — 遠端管理要用

---

## 觀念說明

### ★★★★★ 本手冊的實驗環境：VM 裡面再裝 KVM（巢狀虛擬化）

先把環境講清楚，不然後面每一步都會踩坑。

本手冊假設**大多數讀者沒有一台可以隨便重灌的實體伺服器**，所以 KVM 章的實驗環境是：

```text
你的實體電腦（Windows 或 Linux）
  └─ VMware Workstation                    ← 第一層虛擬化
       └─ Ubuntu Server 24.04（一台 VM）    ← 你要在這裡裝 KVM
            └─ KVM 開出來的 VM              ← 第二層虛擬化 ★★★★★
```

**在虛擬機裡面再開虛擬機，就叫巢狀虛擬化（nested virtualization）。**

> [!danger] ★★★★★ 第一件事：在 VMware Workstation 裡打開巢狀虛擬化
> 這個開關**預設是關的**。沒開的話，客體裡看不到 `vmx`／`svm` CPU 旗標，
> KVM 完全裝不起來，或裝起來只能用超慢的軟體模擬。
>
> 步驟（Ubuntu Server 那台 VM **必須先關機**）：
> 1. VM → Settings → **Processors**
> 2. 勾選 **`Virtualize Intel VT-x/EPT or AMD-V/RVI`**
> 3. 確定，再開機
>
> 詳細說明與 Windows 主機上 Hyper-V／WSL2 造成的衝突，
> 見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]]。

> [!warning] ★★★★ 巢狀虛擬化的三個限制，先知道再動手
> 1. **效能會打折**。第二層 VM 的 I/O 與 CPU 都比第一層慢，
>    這是實驗環境，**不要拿來跑正式服務或做效能評測**。
> 2. **記憶體要夠**。第二層 VM 的記憶體是從第一層 VM 的記憶體切出來的。
>    實體機 16 GB → Ubuntu Server VM 給 8 GB → 裡面的 KVM VM 頂多給 2～4 GB。
> 3. **Windows 主機上若啟用了 Hyper-V／WSL2／VBS**，
>    VMware Workstation 會以另一種模式執行，巢狀虛擬化的可用性與效能都會受影響。
>    這在 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 有完整處理。

> [!tip] ★★★ 有實體機的話
> 如果你有一台可以裝 Ubuntu Server 的實體機（哪怕是舊筆電），
> **強烈建議直接用實體機做這一章**。省掉巢狀虛擬化的所有麻煩，
> 而且效能差距非常明顯。BIOS/UEFI 裡把 VT-x／AMD-V 打開即可。

### ★★★★★ `qemu:///system` 與 `qemu:///session`：先搞懂再安裝

這是 KVM 新手最常卡、而且卡了完全不知道自己卡在哪的地方。**請務必看完這一節。**

libvirt 有兩種完全獨立的執行模式：

| | `qemu:///system` ★★★★★ | `qemu:///session` ★★★★ |
| --- | --- | --- |
| **中文常稱** | 系統模式 | 使用者模式 / session 模式 |
| **守護行程** | 系統層級的 `virtqemud`／`libvirtd`（root 啟動） | **每個使用者自己一份** |
| **QEMU 執行身分** | `libvirt-qemu`（Ubuntu）/ `qemu`（RHEL） | **就是你自己這個帳號** |
| **VM 定義存在哪** | `/etc/libvirt/qemu/` | `~/.config/libvirt/qemu/` |
| **磁碟預設放哪** | `/var/lib/libvirt/images/` | `~/.local/share/libvirt/images/` |
| **能不能用 `virbr0` NAT 網路** | ✅ 可以 | ❌ **不行**（要 root 權限建 bridge 與 TAP） |
| **網路只能用** | bridge / NAT / 直通，任你選 | **使用者模式網路（SLIRP／passt）** ★★★★ |
| **能不能開機自動啟動 VM** | ✅ `virsh autostart` | ❌ 使用者沒登入就沒有 daemon |
| **需要什麼權限** | `libvirt` 群組成員（或 root） | 完全不需要特權 |
| **適合** | ★★★★★ **伺服器、正式用途** | 桌面上的個人測試 VM |

#### ★★★★★ 為什麼這件事會害死人

情境重現，這在現場天天發生：

```bash
# 你在有桌面的 Ubuntu 上打開 virt-manager，建了一台 VM，一切正常
# 隔天你 ssh 進去想用指令管理
virsh list --all
```

```text
 Id   Name   State
--------------------
```

**一片空白。VM 不見了。**

原因：`virt-manager` 在桌面上預設可能連到 **`qemu:///session`**（或你手動加了 session 連線），
而你在終端機打 `virsh` 時，**如果沒有設定，`virsh` 的預設行為會依身分而異**——
以一般使用者身分執行時可能落到 `qemu:///session`，以 root 執行時則是 `qemu:///system`。
兩邊是**完全獨立的兩個世界**，互相看不到對方的 VM。

★★★★★ **解決方法：養成兩個習慣**

```bash
# 習慣一：任何時候先確認自己在哪個世界
virsh uri
```

```text
qemu:///system
```

```bash
# 習慣二：在 shell 設定檔裡固定下來（伺服器上一律用 system）
echo 'export LIBVIRT_DEFAULT_URI=qemu:///system' >> ~/.bashrc
source ~/.bashrc
```

或者每次都明確指定：

```bash
virsh -c qemu:///system list --all
```

> [!warning] ★★★★★ 本手冊的一致約定
> **本章從頭到尾都使用 `qemu:///system`。**
> 理由：我們在寫伺服器維運手冊，正式服務 VM 一定要能**開機自動啟動**、
> 一定要能用**橋接網路**，這兩點 session 模式都做不到。
>
> 但你必須知道 session 模式存在，因為：
> 1. 你會在網路上看到大量 session 模式的教學，指令看起來一樣但結果不同
> 2. 有些桌面工具預設用 session
> 3. `virt-manager` 第一次開啟時的連線清單裡兩個都會出現

#### ★★★ session 模式什麼時候真的有用

不是說 session 模式沒用。它的正當用途是：

- **開發者在自己的桌機上開測試 VM**，不想（也不該）拿到 `libvirt` 群組權限
- **共用的開發主機**，每個人的 VM 互相隔離，誰也看不到誰的
- **不需要對外服務**的 VM（session 的使用者模式網路出得去、進不來）

### ★★★★★ `libvirt` 群組與權限：為什麼加了群組還要重新登入

裝完 KVM 後最常見的第一個錯誤：

```bash
virsh -c qemu:///system list --all
```

```text
error: failed to connect to the hypervisor
error: Failed to connect socket to '/var/run/libvirt/virtqemud-sock': Permission denied
```

你明明已經跑過 `sudo usermod -aG libvirt $USER` 了。為什麼還是不行？

#### ★★★★★ 原因：群組成員資格是在「登入的那一刻」載入程序的

Linux 的權限模型是這樣運作的：

```text
1. 你登入 → login 程序查 /etc/group，把你所屬的所有群組
             寫進「你的 shell 程序」的憑證（supplementary groups）
2. 你在 shell 裡開的每一個程式 → 繼承 shell 的群組憑證
3. 你跑 usermod -aG libvirt ops → 只改了 /etc/group 這個「檔案」
4. 你現在的 shell → 憑證還是登入當下那一份，★★★★★ 完全不知道檔案變了
```

**所以：改群組必須重新登入，這不是 libvirt 的問題，是 Linux 的基本行為。**

#### ★★★★ 用兩個指令看出差別

這是最能建立正確直覺的實驗：

```bash
# 看「檔案裡」現在寫的（已更新）
id -nG ops
```

```text
ops adm sudo kvm libvirt
```

```bash
# 看「我這個 shell 程序」實際持有的（還沒更新）
id -nG
```

```text
ops adm sudo
```

★★★★★ **兩個輸出不一樣，就是這個問題。**
`id -nG <使用者名稱>` 去查檔案，`id -nG`（不帶參數）看當前程序的憑證。

#### ★★★★ 四種讓它生效的方法，優劣不同

| 方法 | 指令 | 影響範圍 | 評價 |
| --- | --- | --- | --- |
| **完整登出再登入** ★★★★★ | 關掉 SSH 重連 / 登出桌面再登入 | 全部 | ✅ **最推薦，最乾淨** |
| **重新開機** ★★★ | `sudo reboot` | 全部 | ✅ 一定有效，但沒必要 |
| **`newgrp`** ★★★ | `newgrp libvirt` | **只有目前這個 shell** | ⚠️ 應急可用，但**新開的分頁又是舊憑證**，很容易誤判 |
| **`sudo`** ★★★ | `sudo virsh list --all` | 單一指令 | ⚠️ 能動，但你就繞過了群組授權的意義 |

> [!warning] ★★★★ `newgrp` 的陷阱
> `newgrp libvirt` 會開一個**新的子 shell**，這個子 shell 有 `libvirt` 群組。
> 但是：
> - 你另外開的終端機分頁**沒有**
> - 你 `exit` 之後就回到舊環境
> - 你用 `screen`／`tmux` 開的新視窗**沒有**
>
> 結果是「有時候可以有時候不行」，比完全不能動還難查。
> **正確做法就是登出再登入。**

#### ★★★ 兩個群組，作用不同

| 群組 | 給誰用 | 作用 |
| --- | --- | --- |
| **`libvirt`** ★★★★★ | 你（管理者） | 有權連上 libvirt 的管理 socket，也就是「能不能管 VM」 |
| **`kvm`** ★★★★ | QEMU 程序 | 能不能開啟 `/dev/kvm`，也就是「VM 能不能硬體加速」 |

★★★★ 一般使用者只需要 `libvirt`；`kvm` 群組主要是給 QEMU 的執行身分
（`libvirt-qemu` / `qemu`）用的，安裝套件時會自動設好。
把自己也加進 `kvm` 沒有壞處（某些工具如 `qemu-system-x86_64` 直接執行時需要）。

> [!danger] ★★★★★ 再說一次：`libvirt` 群組的威力接近 root
> 群組成員可以建一台 VM，把**主機上的任何區塊裝置或檔案**掛進去讀寫
> （包括 `/dev/sda`），等於能繞過檔案權限讀取整顆磁碟。
> **不要把它當成「安全的低權限群組」隨便發給人。**

### ★★★ 圖形化管理有哪些選擇

`virt-manager` 是**桌面 GTK 程式**，需要圖形環境。伺服器通常沒有桌面。三種常見做法：

| 做法 | 怎麼運作 | 適合 | 注意 |
| --- | --- | --- | --- |
| **本機桌面 + `qemu+ssh://` 遠端連線** ★★★★★ | `virt-manager` 裝在你的工作機，透過 SSH 管遠端伺服器 | **最推薦** | 需要 SSH 金鑰，見下方實戰 |
| **X11 forwarding** ★★★ | `ssh -X` 把伺服器上的 `virt-manager` 畫面轉過來 | 臨時用 | 慢、字型可能怪、伺服器要裝一堆 GUI 相依套件 |
| **Cockpit + cockpit-machines** ★★★★ | 瀏覽器管理 | 伺服器不想裝桌面又想有圖形介面 | 功能比 `virt-manager` 少 |
| **純命令列** ★★★★★ | `virsh` + `virt-install` | 正式維運、自動化 | 見 [[050-01-04-03-cmd-KVM-virsh指令實務]] |

---

## 安裝或基礎操作

### ★★★★★ 步驟 0：先確認硬體支援（三個檢查，缺一不可）

**在還沒裝任何套件之前先做這一步。** 如果這裡不過，裝了也是白裝。

#### 檢查 1：CPU 旗標

```bash
grep -c -E '(vmx|svm)' /proc/cpuinfo
```

```text
4
```

| 結果 | 意義 | 怎麼辦 |
| --- | --- | --- |
| **大於 0** ★★★★★ | ✅ CPU 有 VT-x（Intel，`vmx`）或 AMD-V（AMD，`svm`） | 繼續 |
| **0**（實體機） ★★★★★ | BIOS/UEFI 沒開，或 CPU 太舊 | 進 BIOS 打開 `Intel VT-x` / `SVM Mode` |
| **0**（在 VMware VM 裡） ★★★★★ | **巢狀虛擬化沒開** | 關機 → VM Settings → Processors → 勾 `Virtualize Intel VT-x/EPT` |

看實際是哪一種：

```bash
grep -o -m1 -E '(vmx|svm)' /proc/cpuinfo
```

```text
vmx
```

#### 檢查 2：`kvm-ok`

Ubuntu／Debian 有一個專門的小工具：

```bash
sudo apt install -y cpu-checker
kvm-ok
```

成功時：

```text
INFO: /dev/kvm exists
KVM acceleration can be used
```

失敗時的三種典型輸出 ★★★★★：

```text
INFO: Your CPU does not support KVM extensions
KVM acceleration can NOT be used
```
→ CPU 旗標沒有。實體機去 BIOS，虛擬機去開巢狀虛擬化。

```text
INFO: KVM is disabled by your BIOS
HINT: Enter your BIOS setup and enable Virtualization Technology (VT),
      and then hard poweroff/poweron your system
KVM acceleration can NOT be used
```
→ ★★★★★ 注意提示裡的 **hard poweroff**：某些主機板改了 BIOS 設定後
必須**完全斷電再開機**（不是 reboot）才會生效。

```text
INFO: /dev/kvm does not exist
HINT:   sudo modprobe kvm_intel
```
→ 模組沒載入，照它說的做。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> RHEL 系**沒有 `kvm-ok`**（`cpu-checker` 不在預設倉庫）。改用：
>
> ```bash
> lscpu | grep -i virtualization
> ```
> ```text
> Virtualization:                       VT-x
> ```
>
> 或直接看旗標：
> ```bash
> grep -E -c '(vmx|svm)' /proc/cpuinfo
> ```
>
> 裝完 libvirt 後，`virt-host-validate` 是兩邊通用且更完整的工具。

#### 檢查 3：`/dev/kvm` 存在

```bash
ls -l /dev/kvm
```

```text
crw-rw---- 1 root kvm 10, 232 Sep  2 09:14 /dev/kvm
```

沒有這個檔就手動載入模組：

```bash
sudo modprobe kvm_intel      # AMD 平台用 kvm_amd
lsmod | grep '^kvm'
```

```text
kvm_intel             487424  0
kvm                  1409024  1 kvm_intel
```

還是失敗就看核心說什麼：

```bash
sudo dmesg | grep -i kvm | tail -5
```

```text
[    2.148311] kvm: disabled by bios
```

★★★★★ `disabled by bios` 沒有軟體解法，只能去 BIOS/UEFI 開。

#### ★★★★ 加碼：確認巢狀虛擬化在「主機端」是開的

如果你是在 VMware Workstation 的 Ubuntu Server 裡，
上面三個檢查通過就代表 Workstation 那層已經開好了。

但如果你**還想在這台 KVM 上再開一層**（不建議，但有人會試），
要確認 KVM 自己的 nested 參數：

```bash
cat /sys/module/kvm_intel/parameters/nested
```

```text
Y
```

AMD 平台是 `/sys/module/kvm_amd/parameters/nested`。
`N` 的話要寫模組參數（見 [[020-01-26-guide-Linux-核心模組與sysctl調校]]）。

### ★★★★ 步驟 1：安裝套件

#### Ubuntu / Debian（主線）

```bash
sudo apt update
sudo apt install -y \
  qemu-system-x86 \
  libvirt-daemon-system \
  libvirt-clients \
  virtinst \
  bridge-utils \
  cpu-checker
```

```text
Reading package lists... Done
Building dependency tree... Done
The following additional packages will be installed:
  ipxe-qemu libvirt-daemon libvirt-daemon-driver-qemu qemu-utils
  seabios ovmf dnsmasq-base ...
Setting up libvirt-daemon-system (10.0.0-2ubuntu8) ...
Created symlink /etc/systemd/system/multi-user.target.wants/libvirtd.service ...
```

逐項說明它們是什麼 ★★★★：

| 套件 | 作用 | 一定要嗎 |
| --- | --- | --- |
| `qemu-system-x86` ★★★★★ | QEMU 本體（x86 客體） | ✅ 必要 |
| `libvirt-daemon-system` ★★★★★ | libvirt 守護行程 + systemd 單元 + 預設網路 | ✅ 必要 |
| `libvirt-clients` ★★★★★ | **`virsh` 在這個套件裡** | ✅ 必要 |
| `virtinst` ★★★★ | `virt-install`、`virt-clone`、`virt-xml` | ✅ 強烈建議 |
| `bridge-utils` ★★★ | `brctl`（舊工具，現在多用 `ip link`） | 選用 |
| `cpu-checker` ★★★ | `kvm-ok` | 選用 |
| `qemu-utils` ★★★★ | **`qemu-img`**（會被相依帶進來） | ✅ 必要 |
| `ovmf` ★★★★ | UEFI 韌體，要開 UEFI 客體才需要 | 建議 |
| `virt-manager` ★★★★ | **圖形介面，只在有桌面時裝** | 看情況 |

> [!note] ★★★★ `qemu-kvm` 這個套件名
> 舊教學會寫 `apt install qemu-kvm`。在較新的 Ubuntu／Debian 上
> **`qemu-kvm` 已經是一個轉移套件（transitional package）**，
> 真正的內容在 `qemu-system-x86`。裝哪一個都會得到正確結果，
> 但**寫文件時應該寫 `qemu-system-x86`**。
> 不確定時查一下：
> ```bash
> apt show qemu-kvm 2>/dev/null | head -5
> ```

有桌面環境的話再加：

```bash
sudo apt install -y virt-manager virt-viewer
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> **方法 A：裝套件群組（最省事）** ★★★★
> ```bash
> sudo dnf group install "Virtualization Host"
> ```
> ```text
> Group: Virtualization Host
>  Description: Minimal virtualization host installation
>  Mandatory Packages:
>    libvirt
>    qemu-kvm
> ```
>
> **方法 B：逐項指定（比較清楚）** ★★★★★
> ```bash
> sudo dnf install -y \
>   qemu-kvm \
>   libvirt \
>   libvirt-client \
>   virt-install \
>   libguestfs-tools
> ```
>
> 有桌面時：
> ```bash
> sudo dnf install -y virt-manager virt-viewer
> ```
>
> **套件名稱對照** ★★★★：
>
> | Ubuntu / Debian | Rocky / AlmaLinux |
> | --- | --- |
> | `qemu-system-x86` | `qemu-kvm` |
> | `libvirt-daemon-system` | `libvirt` |
> | `libvirt-clients` | `libvirt-client` |
> | `virtinst` | `virt-install` |
> | `qemu-utils`（`qemu-img`） | `qemu-img` |
> | `ovmf` | `edk2-ovmf` |
>
> **★★★★★ 三個一定要記住的差異**：
> 1. **QEMU 執行身分是 `qemu`，不是 `libvirt-qemu`**
> 2. **強制存取控制是 SELinux（sVirt），不是 AppArmor** —— 磁碟放在
>    `/var/lib/libvirt/images/` 以外的路徑時要處理 context
> 3. **RHEL 9 起預設是模組化 daemon（`virtqemud`）**，
>    `systemctl restart libvirtd` 可能會回「Unit not found」
>
> **啟動服務**（RHEL 9 模組化）：
> ```bash
> sudo systemctl enable --now virtqemud.socket virtnetworkd.socket virtstoraged.socket
> ```

### ★★★★ 步驟 2：確認服務起來了

先搞清楚你的機器是哪一種架構（見 [[050-01-04-01-guide-KVM-KVM與libvirt架構]]）：

```bash
systemctl list-units --type=service 'virt*' 'libvirt*' --no-pager
```

模組化架構：

```text
  UNIT                  LOAD   ACTIVE SUB     DESCRIPTION
  virtlogd.service      loaded active running Virtual machine log manager
  virtnetworkd.service  loaded active running Virtual network daemon
  virtqemud.service     loaded active running Virtualization qemu daemon
  virtstoraged.service  loaded active running Virtualization storage daemon
```

傳統架構：

```text
  UNIT                  LOAD   ACTIVE SUB     DESCRIPTION
  libvirtd.service      loaded active running Virtualization daemon
  virtlogd.service      loaded active running Virtual machine log manager
```

★★★★ **把你看到的結果記下來**，後面所有「重啟服務」的指令都要用對名稱。

沒起來的話：

```bash
# 傳統架構
sudo systemctl enable --now libvirtd

# 模組化架構
sudo systemctl enable --now virtqemud.socket virtnetworkd.socket virtstoraged.socket
```

> [!note] ★★★ 為什麼模組化架構要 enable 的是 `.socket`
> 因為它們用 **systemd socket activation** —— socket 先監聽，
> 有人連進來才叫起 service。所以 `systemctl status virtqemud`
> 顯示 `inactive` **不代表壞了**，跑一次 `virsh list` 它就會起來。

### ★★★★★ 步驟 3：加入群組並重新登入

```bash
sudo usermod -aG libvirt,kvm $USER
```

```bash
# 驗證「檔案裡」寫對了
id -nG $USER
```

```text
ops adm sudo kvm libvirt
```

```bash
# 驗證「目前 shell」還沒生效（這是預期行為）
id -nG
```

```text
ops adm sudo
```

★★★★★ **現在完整登出再登入**（SSH 就是關掉連線重連，桌面就是登出）。

```bash
# 重新登入後再看一次
id -nG
```

```text
ops adm sudo kvm libvirt
```

✅ 現在兩個輸出一致了。

```bash
# 最終驗證：不用 sudo 就能連上
virsh -c qemu:///system list --all
```

```text
 Id   Name   State
--------------------
```

沒有錯誤訊息就是成功（清單是空的很正常，還沒建 VM）。

### ★★★★★ 步驟 4：固定 `LIBVIRT_DEFAULT_URI`

**這一步不做，你以後一定會踩到「VM 不見了」。**

```bash
echo 'export LIBVIRT_DEFAULT_URI=qemu:///system' >> ~/.bashrc
source ~/.bashrc
virsh uri
```

```text
qemu:///system
```

> [!tip] ★★★★ 全機器套用
> 如果這台機器上有多個管理者，寫在 `/etc/profile.d/` 更保險：
> ```bash
> echo 'export LIBVIRT_DEFAULT_URI=qemu:///system' | \
>   sudo tee /etc/profile.d/libvirt-uri.sh
> ```
> 下次每個人登入都會套用。

### ★★★★ 步驟 5：完整健康檢查

```bash
sudo virt-host-validate qemu
```

```text
  QEMU: Checking for hardware virtualization                                 : PASS
  QEMU: Checking if device /dev/kvm exists                                   : PASS
  QEMU: Checking if device /dev/kvm is accessible                            : PASS
  QEMU: Checking if device /dev/vhost-net exists                             : PASS
  QEMU: Checking if device /dev/net/tun exists                               : PASS
  QEMU: Checking for cgroup 'cpu' controller support                         : PASS
  QEMU: Checking for cgroup 'cpuacct' controller support                     : PASS
  QEMU: Checking for cgroup 'cpuset' controller support                      : PASS
  QEMU: Checking for cgroup 'memory' controller support                      : PASS
  QEMU: Checking for cgroup 'blkio' controller support                       : PASS
  QEMU: Checking for device assignment IOMMU support                         : WARN (No ACPI DMAR table found, IOMMU either disabled in BIOS or not supported by this hardware)
  QEMU: Checking for secure guest support                                    : WARN (Unknown if this platform has Secure Guest support)
```

★★★★★ **前三行必須 PASS**，其餘 WARN 對一般用途無妨（IOMMU 只影響 PCI 直通）。

### ★★★★ 步驟 6：確認預設網路

```bash
virsh net-list --all
```

```text
 Name      State    Autostart   Persistent
--------------------------------------------
 default   active   yes         yes
```

```bash
ip -br addr show virbr0
```

```text
virbr0           UP             192.168.122.1/24
```

如果 `default` 是 `inactive`：

```bash
virsh net-start default
virsh net-autostart default
```

> [!warning] ★★★★ `default` 是 NAT，外部連不進來
> VM 接在 `default` 上可以**出去**（上網、`apt update`），但**外面連不進來**。
> 學習階段完全夠用；要跑對外服務就要改**橋接**，
> 見 [[050-01-04-04-guide-KVM-儲存池與網路]]。

### ★★★★ 步驟 7：準備安裝媒體

```bash
sudo mkdir -p /var/lib/libvirt/images/iso
cd /var/lib/libvirt/images/iso
sudo wget https://releases.ubuntu.com/24.04/ubuntu-24.04-live-server-amd64.iso
```

> [!warning] ★★★ 版本字串會變
> 上面的檔名只是示意。**請到 <https://releases.ubuntu.com/> 確認當前的實際檔名與
> SHA256**，不要照抄。下載後務必驗證：
> ```bash
> sha256sum ubuntu-24.04-live-server-amd64.iso
> ```

```bash
ls -lh /var/lib/libvirt/images/iso/
```

```text
total 2.6G
-rw-r--r-- 1 root root 2.6G Sep  2 10:03 ubuntu-24.04-live-server-amd64.iso
```

> [!danger] ★★★★ ISO 的權限：AppArmor 會擋
> 把 ISO 放在 `/var/lib/libvirt/images/` 底下（或它的子目錄）是**最安全的做法**，
> 因為 libvirt 的 AppArmor／SELinux 規則預設允許這個路徑。
> 放在 `/home/xxx/Downloads/` 之類的地方，
> 十之八九會得到 `Could not open ... : Permission denied`。
> 詳見「常見錯誤與排錯」。

---

## 進階應用

### ★★★★ 遠端管理：`qemu+ssh://`

伺服器沒有桌面，但你的工作機（Ubuntu 桌面版 / Fedora / 甚至 macOS）有。
把 `virt-manager` 裝在工作機上，透過 SSH 管遠端伺服器——**這是最推薦的做法**。

#### 前提：SSH 金鑰登入

```bash
# 在你的工作機上
ssh-copy-id ops@192.168.1.50
ssh ops@192.168.1.50 'echo ok'
```

```text
ok
```

★★★★★ **一定要用金鑰，不要用密碼**。`virt-manager` 會頻繁建立連線，
密碼登入會不斷跳提示，而且無法自動重連。設定見 [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]]。

#### 遠端的那台伺服器要有 `libvirt-clients`

`qemu+ssh://` 的原理是：在遠端執行 `virt-ssh-helper`（或舊版的 `nc`）
把 libvirt 的 socket 轉出來。所以遠端伺服器上必須裝 `libvirt-clients`。

#### 用 `virsh` 先測

```bash
# 在你的工作機上
virsh -c qemu+ssh://ops@192.168.1.50/system list --all
```

```text
 Id   Name   State
--------------------
```

沒有錯誤就通了。

#### 在 `virt-manager` 裡加入

1. 開啟 `virt-manager`
2. 選單 **File → Add Connection…**
3. **Hypervisor** 選 `QEMU/KVM`
4. 勾選 **`Connect to remote host over SSH`**
5. **Username** 填 `ops`，**Hostname** 填 `192.168.1.50`
6. 勾 **`Autoconnect`**（下次開啟自動連）
7. 下方會顯示產生的 URI：`qemu+ssh://ops@192.168.1.50/system` ★★★★
8. **Connect**

> [!warning] ★★★★ 遠端連線的三個常見卡點
> | 症狀 | 原因 | 解法 |
> | --- | --- | --- |
> | 一直跳密碼視窗 | 沒設 SSH 金鑰 | `ssh-copy-id`，並確認 `ssh-agent` 有載入金鑰 |
> | `Cannot recv data: ... Host key verification failed` ★★★★ | 工作機的 `known_hosts` 沒有這台主機 | 先手動 `ssh` 一次接受指紋 |
> | 連上但主控台（VNC）打不開 ★★★★ | VNC 只綁在遠端的 `127.0.0.1` | 這是**正確的安全設定**；`virt-manager` 會自動用 SSH 通道轉發，若失敗檢查遠端有無 `libvirt-clients` |

> [!danger] ★★★★★ 不要開 libvirt 的 TCP 監聽
> 網路上有些教學會叫你改 `libvirtd.conf` 打開 `listen_tcp = 1`（port 16509）。
> **不要這樣做。** 那個介面預設沒有加密也沒有認證，
> 開了等於把整台主機的 root 權限放到網路上。
> **遠端管理一律走 `qemu+ssh://`。**

### ★★★ 沒有桌面時的替代方案

#### 方案 A：Cockpit（推薦）★★★★

```bash
sudo apt install -y cockpit cockpit-machines
sudo systemctl enable --now cockpit.socket
```

```bash
sudo ss -tlnp | grep 9090
```

```text
LISTEN 0  4096  *:9090  *:*  users:(("systemd",pid=1,fd=68))
```

瀏覽器開 `https://<伺服器IP>:9090`，用系統帳號登入，左側就有「虛擬機」。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> sudo dnf install -y cockpit cockpit-machines
> sudo systemctl enable --now cockpit.socket
> sudo firewall-cmd --add-service=cockpit --permanent
> sudo firewall-cmd --reload
> ```
> RHEL 系預設就有 Cockpit（`cockpit.socket` 常已啟用），只要加 `cockpit-machines`。

#### 方案 B：X11 forwarding（臨時用）★★★

```bash
# 伺服器上：sshd 要允許 X11
sudo sed -i 's/^#\?X11Forwarding.*/X11Forwarding yes/' /etc/ssh/sshd_config
sudo systemctl restart ssh
sudo apt install -y virt-manager xauth
```

```bash
# 工作機上
ssh -X ops@192.168.1.50
virt-manager &
```

★★★ 慢、需要在伺服器上裝一堆 GUI 相依套件，**只建議臨時用**。

#### 方案 C：純命令列 ★★★★★

`virt-install` + `virsh`，見 [[050-01-04-03-cmd-KVM-virsh指令實務]] 與
[[050-01-04-05-guide-KVM-自動化與範本]]。**正式維運環境的正解。**

### ★★★ `virt-manager` 主要偏好設定

**Edit → Preferences** 裡有幾個值得調的：

| 分頁 | 設定 | 建議 | 為什麼 |
| --- | --- | --- | --- |
| General | Enable system tray icon | 看習慣 | |
| Polling | Poll CPU / Disk / Network usage | ★★★ 全部勾 | 才會有資源圖表 |
| Console | Graphical console scaling | `Always` | 視窗大小自動配合 |
| Console | Resize guest with window | 勾（客體要有 SPICE agent） | ★★★ 拉視窗客體解析度跟著變 |
| Console | Grab keys | 記住這組鍵 | ★★★★ 滑鼠被 VM 抓住時用來放開 |
| New VM | Graphics type | `SPICE`（有 GUI 客體）/ `VNC` | |
| Feedback | Confirm forced poweroff | ★★★★★ **勾** | 避免手滑對正式 VM 強制斷電 |

---

## 完整實戰範例

### 目標

在一台 **VMware Workstation 裡的 Ubuntu Server 24.04**（4 vCPU / 8 GB / 60 GB）上，
從零裝好 KVM，並用 `virt-manager`（從有桌面的工作機遠端連線）
建出**第一台 VM `web01`**，裝好 Ubuntu Server，確認可以上網。

★★★★★ **這台 `web01` 會被 [[050-01-04-03-cmd-KVM-virsh指令實務]] 全程接手**，
所以請照著命名。

### 階段 A：確認巢狀虛擬化（在 VMware Workstation 這一層做）

1. **關閉** Ubuntu Server 這台 VM（不是暫停，是關機）
2. VM → **Settings** → **Processors**
3. 勾選 **`Virtualize Intel VT-x/EPT or AMD-V/RVI`**
4. 順便確認 **Number of processors × Number of cores** 合計至少 4
5. **Memory** 至少 8 GB
6. OK → 開機

開機後在 Ubuntu Server 裡驗證：

```bash
grep -c -E '(vmx|svm)' /proc/cpuinfo
```

```text
4
```

★★★★★ **這裡是 0 就不要往下做**，回去檢查 Workstation 的設定與
[[050-01-02-06-guide-Workstation-效能調校與疑難排解]]。

### 階段 B：安裝

```bash
sudo apt update && sudo apt upgrade -y
```

```bash
sudo apt install -y qemu-system-x86 libvirt-daemon-system libvirt-clients \
  virtinst bridge-utils cpu-checker
```

```bash
kvm-ok
```

```text
INFO: /dev/kvm exists
KVM acceleration can be used
```

```bash
sudo virt-host-validate qemu | head -3
```

```text
  QEMU: Checking for hardware virtualization                                 : PASS
  QEMU: Checking if device /dev/kvm exists                                   : PASS
  QEMU: Checking if device /dev/kvm is accessible                            : PASS
```

✅ 三個 PASS。

### 階段 C：權限

```bash
sudo usermod -aG libvirt,kvm $USER
id -nG $USER
```

```text
ops adm sudo kvm libvirt
```

```bash
id -nG
```

```text
ops adm sudo
```

★★★★★ 不一致 → **登出重新登入**（SSH 就 `exit` 再連一次）。

```bash
# 重新登入後
id -nG
```

```text
ops adm sudo kvm libvirt
```

```bash
echo 'export LIBVIRT_DEFAULT_URI=qemu:///system' >> ~/.bashrc
source ~/.bashrc
virsh uri && virsh list --all
```

```text
qemu:///system
 Id   Name   State
--------------------
```

✅ 不用 `sudo` 也能連。

### 階段 D：確認網路與準備 ISO

```bash
virsh net-list --all
```

```text
 Name      State    Autostart   Persistent
--------------------------------------------
 default   active   yes         yes
```

```bash
ip -br addr show virbr0
```

```text
virbr0           UP             192.168.122.1/24
```

```bash
sudo mkdir -p /var/lib/libvirt/images/iso
cd /var/lib/libvirt/images/iso
sudo wget https://releases.ubuntu.com/24.04/ubuntu-24.04-live-server-amd64.iso
ls -lh
```

```text
total 2.6G
-rw-r--r-- 1 root root 2.6G Sep  2 10:03 ubuntu-24.04-live-server-amd64.iso
```

### 階段 E：從工作機遠端連上

在**你的桌面工作機**（有 GUI 的那台）上：

```bash
sudo apt install -y virt-manager virt-viewer
ssh-copy-id ops@192.168.1.50
virsh -c qemu+ssh://ops@192.168.1.50/system list --all
```

```text
 Id   Name   State
--------------------
```

✅ 通了。開 `virt-manager`：

1. **File → Add Connection…**
2. Hypervisor：`QEMU/KVM`
3. 勾 `Connect to remote host over SSH`
4. Username `ops`，Hostname `192.168.1.50`
5. 勾 `Autoconnect`
6. **Connect**

左側樹狀清單出現 `QEMU/KVM: 192.168.1.50`，狀態 `Connected`。

### 階段 F：用 `virt-manager` 建立 `web01`

點選那個連線 → 左上角 **Create a new virtual machine** 按鈕。

#### 第 1 頁：選擇安裝方式

| 選項 | 選什麼 | 說明 |
| --- | --- | --- |
| **Local install media (ISO image or CDROM)** ★★★★★ | ✅ **選這個** | 用我們剛下載的 ISO |
| Network Install (HTTP, HTTPS, FTP) | | 直接從網路 mirror 裝，不用先下載 ISO |
| Import existing disk image ★★★★ | | **匯入 cloud image 時用這個**，見 05 篇 |
| Manual install | | 先建空機再裝 |

→ **Forward**

#### 第 2 頁：選 ISO 與作業系統

1. **Browse…** → 左側選 `default` 儲存池 → 找不到 ISO 的話：
   - 點左下角 **`+`** 建立一個新 pool 指向 `/var/lib/libvirt/images/iso`，或
   - ★★★★ 更簡單：**Browse Local**（只在本機連線時可用；遠端連線時必須用 pool）
2. **Choose the operating system you are installing**
   - 通常會自動偵測。沒偵測到就取消勾選 `Automatically detect...`，
     手動搜尋 `Ubuntu 24.04`

> [!warning] ★★★★★ 遠端連線時「Browse Local」是灰的
> 因為 `virt-manager` 跑在你的工作機上，但 VM 要在**遠端伺服器**上開，
> ISO 必須存在**遠端**的儲存池裡。這是很多人第一次遠端建 VM 時最困惑的一點。
>
> 解法：把 ISO 放在遠端的 `/var/lib/libvirt/images/`（`default` pool 就會看到），
> 或在遠端建一個指向 ISO 目錄的 pool：
> ```bash
> # 在遠端伺服器上
> virsh pool-define-as iso dir --target /var/lib/libvirt/images/iso
> virsh pool-build iso
> virsh pool-start iso
> virsh pool-autostart iso
> ```

> [!note] ★★★★ 為什麼「選對作業系統」很重要
> 這不只是個標籤。`virt-manager` 會根據它套用 **osinfo** 資料庫裡的預設值：
> 磁碟匯流排要不要用 VirtIO、網卡型號、要不要 UEFI、建議的記憶體。
> **選錯（例如選成 Generic）可能讓它退回 IDE 磁碟與 e1000 網卡，效能差很多** ★★★★★。

→ **Forward**

#### 第 3 頁：記憶體與 CPU

| 欄位 | 本例填 | 判斷準則 |
| --- | --- | --- |
| **Memory (RAM)** | `2048` MiB | ★★★★ 巢狀環境下主機只有 8 GB，別給太多 |
| **CPUs** | `2` | ★★★★ 不要超過主機邏輯核心數；巢狀環境給 2 就好 |

★★★★ 頁面會顯示 `Up to N available`，那是主機的上限。

→ **Forward**

#### 第 4 頁：儲存

| 選項 | 選什麼 |
| --- | --- |
| **Enable storage for this virtual machine** | ✅ 勾 |
| **Create a disk image for the virtual machine** ★★★★★ | ✅ 選這個，填 **`20.0` GiB** |
| Select or create custom storage | 要放到非預設 pool 或用既有磁碟時才選 |

★★★★ 這會在 `/var/lib/libvirt/images/web01.qcow2` 建一個 **qcow2 精簡配置**的檔案，
一開始只佔幾百 KB，用多少長多少。

→ **Forward**

#### 第 5 頁：名稱、網路，與「開始安裝前先修改設定」

| 欄位 | 填什麼 |
| --- | --- |
| **Name** ★★★★★ | `web01` |
| **Network selection** | `Virtual network 'default': NAT` |
| **`Customize configuration before install`** ★★★★★ | ✅ **一定要勾** |

> [!tip] ★★★★★ 為什麼一定要勾「Customize configuration before install」
> 因為有些設定**只能在安裝前改**，或改了要重開機才生效
> （CPU model、磁碟匯流排、網卡型號、韌體 BIOS/UEFI）。
> 勾了之後會多一個設定畫面，可以在真的開機之前把這些調好，
> 省掉「裝完才發現用的是 IDE 磁碟」的重來。

→ **Finish**（此時還不會開機）

#### 第 6 頁：安裝前的設定調整

左側清單逐項檢查：

**`Overview`**

| 項目 | 檢查什麼 |
| --- | --- |
| **Chipset** ★★★★ | `Q35`（現代機器都選這個；`i440FX` 是給很舊的客體） |
| **Firmware** ★★★★ | `BIOS` 或 `UEFI`。★★★★★ **這個安裝後就不能改**，改了開不了機。Ubuntu 兩者都支援；要跟 Secure Boot 有關就選 UEFI |

**`CPUs`**

| 項目 | 建議 |
| --- | --- |
| **Model** ★★★★★ | 單機不遷移 → `host-passthrough`（效能最好）。**未來可能搬到別台 → 選具名 model** |
| Topology | 不用動，除非客體軟體按 socket 授權 |

★★★★ 這跟 PVE 的 `cpu: host` vs `x86-64-v2-AES` 是同一個議題，
見 [[050-01-03-03-guide-PVE-虛擬機管理]]。

**`SATA Disk 1`** → 展開 **Advanced options**

| 項目 | 建議 | 為什麼 |
| --- | --- | --- |
| **Disk bus** ★★★★★ | 改成 **`VirtIO`** | 效能差距最大的單一決定 |
| **Cache mode** ★★★★ | `none`（安全）或 `writeback`（快但斷電風險） | 見 PVE 篇的完整討論 |
| **Discard mode** ★★★★ | `unmap` | 客體刪檔後空間才會還回主機 |

改成 VirtIO 後左側標籤會變成 **`VirtIO Disk 1`**，裝置名從 `sda` 變 `vda`。

**`NIC :xx:xx:xx`**

| 項目 | 建議 |
| --- | --- |
| **Device model** ★★★★★ | **`virtio`** |
| Network source | `Virtual network 'default': NAT` |

**`Display Spice` / `Video`**

保持預設即可。★★★ 純伺服器客體其實用不到顯示，但安裝過程需要看畫面。

**加一個序列主控台（強烈建議）** ★★★★

左下角 **Add Hardware** → **Serial** → Device Type `Pty` → **Finish**。

> [!tip] ★★★★★ 為什麼要加序列主控台
> 有了它，你之後可以在伺服器上直接
> ```bash
> virsh console web01
> ```
> 用純文字連進客體，**不需要任何圖形介面**。
> 這在「SSH 進不去、必須看開機畫面」的時候是救命工具。
> 客體端還要在 GRUB 加 `console=ttyS0`，見 03 篇。

檢查完 → 左上角 **Begin Installation**

#### 第 7 頁：安裝作業系統

VM 開機，進入 Ubuntu Server 的安裝程式。重點步驟：

1. 語言 → English
2. 網路 → 應該會自動從 `virbr0` 的 DHCP 拿到 `192.168.122.x` ★★★★
   - **拿不到 IP** → 回去確認 `default` 網路是 `active`
3. 儲存 → 使用整顆磁碟。★★★★ 這裡看到的裝置名應該是 **`vda`**（VirtIO），
   不是 `sda`。是 `sda` 就代表磁碟匯流排沒改成 VirtIO
4. Profile → 主機名稱填 `web01`，建立使用者
5. ★★★★★ **勾選 `Install OpenSSH server`**（不然裝完連不進去）
6. 等待安裝完成 → **Reboot Now**

> [!warning] ★★★ 重開機後又進入安裝程式
> ISO 還掛著而且開機順序在硬碟之前。在 `virt-manager` 裡：
> VM 視窗 → 燈泡圖示（Show virtual hardware details）→
> **`SATA CDROM 1`** → **Disconnect**，然後重開機。
> 或者在 **Boot Options** 裡把硬碟排到前面。

### 階段 G：驗證

VM 開機後，在 `virt-manager` 的主控台登入，或從伺服器上：

```bash
# 在 KVM 主機上
virsh list --all
```

```text
 Id   Name    State
-----------------------
 1    web01   running
```

```bash
virsh domifaddr web01
```

```text
 Name       MAC address          Protocol     Address
-------------------------------------------------------------------------------
 vnet0      52:54:00:a3:1f:8c    ipv4         192.168.122.87/24
```

```bash
ssh ops@192.168.122.87
```

在客體裡確認 VirtIO 生效 ★★★★★：

```bash
# 客體內
lsblk
```

```text
NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINTS
vda    252:0    0   20G  0 disk
├─vda1 252:1    0    1M  0 part
├─vda2 252:2    0  1.8G  0 part /boot
└─vda3 252:3    0 18.2G  0 part
```

★★★★★ **裝置名是 `vda` 不是 `sda`** → VirtIO 磁碟正確。

```bash
# 客體內
lspci | grep -i virtio
```

```text
00:03.0 Ethernet controller: Red Hat, Inc. Virtio 1.0 network device (rev 01)
00:05.0 SCSI storage controller: Red Hat, Inc. Virtio 1.0 block device (rev 01)
00:06.0 Unclassified device [00ff]: Red Hat, Inc. Virtio 1.0 memory balloon (rev 01)
```

✅ 網卡、磁碟、balloon 三個 VirtIO 裝置都在。

```bash
# 客體內：確認能上網
ping -c 2 1.1.1.1
```

```text
PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=55 time=8.42 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=55 time=8.31 ms
```

### 階段 H：裝客體代理與設定自動啟動（收尾，★★★★★ 別忘）

```bash
# 客體內
sudo apt install -y qemu-guest-agent
sudo systemctl enable --now qemu-guest-agent
systemctl is-active qemu-guest-agent
```

```text
active
```

回到 KVM 主機驗證代理通了：

```bash
virsh qemu-agent-command web01 '{"execute":"guest-info"}' | head -c 120
```

```text
{"return":{"version":"8.2.2","supported_commands":[{"enabled":true,"name":"guest-get-cpustats","success-response":true},
```

✅ 有回應就代表 agent 通了。現在 `virsh shutdown` 才能正常關機。

```bash
# 主機上：設定開機自動啟動
virsh autostart web01
```

```text
Domain 'web01' marked as autostarted
```

```bash
virsh dominfo web01 | grep -E 'Autostart|State'
```

```text
State:          running
Autostart:      enable
```

✅ **完成。** 你有了一台可用的 VM，而且主機重開機後它會自己回來。

### 收尾檢查清單

| 項目 | 指令 | 期望 |
| --- | --- | --- |
| VM 存在且執行中 ★★★★ | `virsh list --all` | `web01running` |
| 用的是 KVM 不是 TCG ★★★★★ | `virsh dumpxml web01 \| grep "domain type"` | `<domain type='kvm'>` |
| 磁碟是 VirtIO ★★★★★ | `virsh dumpxml web01 \| grep "bus="` | `bus='virtio'` |
| 網卡是 VirtIO ★★★★★ | `virsh dumpxml web01 \| grep "model type"` | `type='virtio'` |
| 自動啟動 ★★★★★ | `virsh dominfo web01 \| grep Autostart` | `enable` |
| 客體代理 ★★★★ | `virsh domifaddr web01 --source agent` | 顯示 IP |
| SSH 可連 ★★★★ | `ssh ops@192.168.122.87` | 登入成功 |

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| `kvm-ok` 回 `INFO: Your CPU does not support KVM extensions` ★★★★★ | CPU 旗標沒有 | 實體機：BIOS 開 VT-x／SVM。VMware VM：關機後 Settings → Processors 勾 `Virtualize Intel VT-x/EPT` |
| `kvm-ok` 回 `KVM is disabled by your BIOS` ★★★★★ | BIOS 有選項但關著 | 進 BIOS 打開，然後**完全斷電再開機**（`reboot` 可能不夠） |
| `/dev/kvm does not exist` ★★★★ | 模組沒載入 | `sudo modprobe kvm_intel`（AMD 用 `kvm_amd`）；`dmesg \| grep kvm` 看原因 |
| `virsh list` 回 `Failed to connect socket to '/var/run/libvirt/virtqemud-sock': Permission denied` ★★★★★ | 使用者不在 `libvirt` 群組，或**加了群組但沒重新登入** | `id -nG` 對 `id -nG $USER`；不一致就登出重新登入 |
| `Failed to connect socket ... No such file or directory` ★★★★ | 守護行程沒起來，或**在模組化架構上找舊 socket** | `systemctl list-units 'virt*' 'libvirt*'` 看實際有哪些；`enable --now` 對應的 `.socket` |
| `systemctl restart libvirtd` 回 `Unit libvirtd.service could not be found` ★★★★ | 模組化架構 | 改用 `systemctl restart virtqemud` |
| **`virsh list --all` 是空的但 `virt-manager` 明明有 VM** ★★★★★ | **連到了不同的 URI（session vs system）** | `virsh uri` 確認；設 `export LIBVIRT_DEFAULT_URI=qemu:///system` |
| VM 啟動失敗：`Could not open '/home/ops/iso/xxx.iso': Permission denied`，但 `ls -l` 看起來權限沒問題 ★★★★★ | **AppArmor**（Ubuntu）擋住 `/var/lib/libvirt/images/` 以外的路徑 | 把 ISO／磁碟移到 `/var/lib/libvirt/images/`；`dmesg \| grep -i apparmor` 確認；家目錄還要確認 `others` 有 `x` 權限 |
| 同上但在 Rocky/Alma ★★★★★ | **SELinux** context 不對 | `sudo semanage fcontext -a -t virt_image_t "/data/vm(/.*)?" && sudo restorecon -Rv /data/vm`（需 `policycoreutils-python-utils`） |
| VM 慢到不能用，客體開機要五分鐘 ★★★★★ | 掉回 TCG 軟體模擬 | `virsh dumpxml <vm> \| grep "domain type"`，是 `'qemu'` 就代表建立時 KVM 不可用；修好 KVM 後 `virsh edit` 改成 `'kvm'`，**完整停機再開機** |
| Ubuntu 安裝程式裡磁碟顯示為 `sda` 而不是 `vda` ★★★★ | 磁碟匯流排還是 SATA/IDE | 停機 → `virsh edit` 或 virt-manager 把 `bus` 改成 `virtio`（已裝好的系統改這個要小心，`/etc/fstab` 若用裝置名會開不了機，用 UUID 就沒事） |
| 客體拿不到 IP ★★★★ | `default` 網路沒啟動，或 dnsmasq 沒跑 | `virsh net-list --all`；`virsh net-start default && virsh net-autostart default` |
| 主機重開機後 VM 全都沒起來 ★★★★★ | 沒設 autostart | 逐台 `virsh autostart <name>`；`virsh list --autostart` 確認 |
| `virt-manager` 遠端連線一直跳密碼 ★★★★ | 沒設 SSH 金鑰 | `ssh-copy-id`；確認 `ssh-agent` 載入了金鑰 |
| `virt-manager` 遠端連線報 `Host key verification failed` ★★★★ | 工作機的 `known_hosts` 沒這台主機 | 先手動 `ssh` 一次接受指紋 |
| 遠端建 VM 時 **Browse Local 是灰的** ★★★★ | ISO 必須存在**遠端**的儲存池裡 | 在遠端建一個指向 ISO 目錄的 pool（`virsh pool-define-as iso dir --target ...`） |
| `virsh shutdown` 卡住不關機 ★★★★★ | 客體沒裝 `qemu-guest-agent`，且 ACPI 訊號被忽略 | 客體裝 `qemu-guest-agent`；緊急時 `virsh destroy`（**強制斷電**，見 03 篇） |
| 重開機後又進入 ISO 安裝程式 ★★★ | ISO 還掛著且開機順序在硬碟前 | virt-manager 把 CDROM `Disconnect`，或調整 Boot Options |
| 巢狀環境下客體很卡、磁碟 I/O 極慢 ★★★ | 巢狀虛擬化的本質限制 | 這是預期的；確認第一層 Workstation VM 的磁碟放在 SSD 上，見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] |
| `virt-host-validate` 的 IOMMU 顯示 WARN ★★★ | BIOS 沒開 VT-d／AMD-Vi | 只影響 PCI 直通，一般用途可忽略 |
| `newgrp libvirt` 之後可以，開新分頁又不行 ★★★★ | `newgrp` 只影響那個子 shell | 登出重新登入 |

---

## 安全性注意事項

> [!danger] ★★★★★ `libvirt` 群組 ≈ root
> 前面說過但值得再說一次：群組成員可以建一台 VM 把 `/dev/sda` 掛進去，
> 直接讀寫整顆實體磁碟，完全繞過檔案權限。
> **機關環境請把 `libvirt` 群組成員名單當成特權帳號清單管理**，
> 定期稽核，離職立刻移除。帳號管理見 [[020-01-09-cmd-Linux-使用者與群組管理]]。

> [!danger] ★★★★★ 絕對不要開 libvirt 的 TCP 監聽（port 16509 / 16514）
> 舊教學常出現 `listen_tcp = 1` + `auth_tcp = "none"`。
> 那等於把主機 root 權限公開在網路上。
> **遠端管理一律 `qemu+ssh://`**，加密與認證都由 SSH 負責。

| 風險 | 說明 | 對策 |
| --- | --- | --- |
| **關掉 AppArmor／SELinux 來「解決」權限問題** ★★★★★ | sVirt 的作用是讓 A 台 VM 的 QEMU 程序讀不到 B 台 VM 的磁碟，關掉就沒有隔離 | 加規則，不要關防護 |
| **`/dev/kvm` 被 `chmod 666`** ★★★★ | 任何本機使用者都能直接開 VM | 恢復 `root:kvm 660` |
| **ISO 未驗證雜湊** ★★★★ | 下載到被竄改的映像等於一開始就被植入 | 一律 `sha256sum` 比對官方值 |
| **VM 磁碟目錄權限過寬** ★★★★ | `/var/lib/libvirt/images/` 裡是完整的客體磁碟 | 目錄不要 `chmod 777`，不要放在共用目錄 |
| **VNC/SPICE 監聽 0.0.0.0** ★★★★★ | 主控台無認證直接暴露 = 任何人都能操作客體 | 保持預設綁 `127.0.0.1`，透過 SSH 通道存取 |
| **X11 forwarding 長期開啟** ★★★ | 擴大 SSH 攻擊面，且要在伺服器裝大量 GUI 套件 | 臨時用完就關；長期用 Cockpit 或本機 `virt-manager` |
| **巢狀虛擬化開在正式機** ★★★ | 虛擬化層漏洞的影響範圍變大 | 正式環境沒需求就不要開 |
| **客體 `qemu-guest-agent` 的權限** ★★★ | 主機端可透過 agent 在客體內執行指令 | 這是設計如此；要注意的是**能操作主機 libvirt 的人 = 能操作所有客體內部** |
| **預設 NAT 網路的誤判** ★★★ | 以為 NAT 就安全，其實客體出得去，被入侵後可對內網掃描 | 客體照樣要做防火牆與更新 |

---

## 速查表

### 安裝前檢查

| 檢查 | 指令 | 期望 |
| --- | --- | --- |
| CPU 旗標 ★★★★★ | `grep -c -E '(vmx\|svm)' /proc/cpuinfo` | `> 0` |
| 是 Intel 還 AMD ★★★ | `grep -o -m1 -E '(vmx\|svm)' /proc/cpuinfo` | `vmx` / `svm` |
| KVM 可用（Ubuntu）★★★★★ | `kvm-ok` | `KVM acceleration can be used` |
| KVM 可用（RHEL）★★★★ | `lscpu \| grep -i virtualization` | `VT-x` / `AMD-V` |
| 模組載入 ★★★★ | `lsmod \| grep '^kvm'` | 有 `kvm` 與 `kvm_intel`/`kvm_amd` |
| 裝置檔 ★★★★★ | `ls -l /dev/kvm` | `crw-rw---- root kvm` |
| 全面檢查 ★★★★ | `sudo virt-host-validate qemu` | 前三行 PASS |
| 巢狀（KVM 層）★★★ | `cat /sys/module/kvm_intel/parameters/nested` | `Y` |

### 套件對照

| 用途 | Ubuntu / Debian | Rocky / AlmaLinux |
| --- | --- | --- |
| QEMU ★★★★★ | `qemu-system-x86` | `qemu-kvm` |
| libvirt 守護行程 ★★★★★ | `libvirt-daemon-system` | `libvirt` |
| `virsh` ★★★★★ | `libvirt-clients` | `libvirt-client` |
| `virt-install` ★★★★ | `virtinst` | `virt-install` |
| `qemu-img` ★★★★ | `qemu-utils` | `qemu-img` |
| UEFI 韌體 ★★★ | `ovmf` | `edk2-ovmf` |
| GUI ★★★★ | `virt-manager` | `virt-manager` |
| `kvm-ok` ★★★ | `cpu-checker` | （無） |
| Web GUI ★★★★ | `cockpit cockpit-machines` | `cockpit cockpit-machines` |

### 權限相關

| 想做什麼 | 指令 |
| --- | --- |
| 加入群組 ★★★★★ | `sudo usermod -aG libvirt,kvm $USER` |
| 看**檔案裡**的群組 ★★★★★ | `id -nG $USER` |
| 看**目前 shell**的群組 ★★★★★ | `id -nG` |
| 讓群組生效 ★★★★★ | **登出再登入**（`newgrp libvirt` 只影響當前 shell） |
| 確認能連上 ★★★★ | `virsh -c qemu:///system list --all` |
| QEMU 執行身分（Ubuntu） ★★★ | `libvirt-qemu` |
| QEMU 執行身分（RHEL） ★★★ | `qemu` |

### 連線 URI

| URI | 意義 |
| --- | --- |
| `qemu:///system` ★★★★★ | 本機系統模式（**伺服器用這個**） |
| `qemu:///session` ★★★★ | 本機使用者模式 |
| `qemu+ssh://user@host/system` ★★★★★ | 遠端系統模式（**遠端管理用這個**） |
| `virsh uri` ★★★★★ | 看目前連到哪 |
| `export LIBVIRT_DEFAULT_URI=qemu:///system` ★★★★★ | 固定預設值 |

### 服務管理

| 架構 | 啟用 | 重啟 |
| --- | --- | --- |
| 傳統 ★★★★ | `systemctl enable --now libvirtd` | `systemctl restart libvirtd` |
| 模組化 ★★★★★ | `systemctl enable --now virtqemud.socket virtnetworkd.socket virtstoraged.socket` | `systemctl restart virtqemud` |
| 先確認是哪一種 ★★★★★ | `systemctl list-units 'virt*' 'libvirt*'` | |

### 常用路徑

| 路徑 | 內容 |
| --- | --- |
| `/var/lib/libvirt/images/` ★★★★★ | 預設磁碟與 ISO 存放處（**AppArmor 允許**） |
| `/etc/libvirt/qemu/` ★★★★ | domain XML（只用 `virsh edit`） |
| `/var/log/libvirt/qemu/<name>.log` ★★★★★ | **排錯第一站** |
| `~/.config/libvirt/` ★★★★ | session 模式的使用者設定 |
| `/etc/libvirt/qemu.conf` ★★★ | QEMU 驅動設定（可直接編輯） |

---

## 練習題

**練習 1（★★★★）**
在你的 Ubuntu Server 上，寫一個**一行指令**，判斷「這台機器現在能不能用 KVM 硬體加速」，
並且**在不能用時印出最可能的原因**。

> [!question]- 參考答案
> ```bash
> if [ -e /dev/kvm ] && [ "$(grep -c -E '(vmx|svm)' /proc/cpuinfo)" -gt 0 ]; then echo "OK"; elif [ "$(grep -c -E '(vmx|svm)' /proc/cpuinfo)" -eq 0 ]; then echo "NG: CPU 旗標不存在 → BIOS 未開 VT-x/AMD-V，或巢狀虛擬化未開"; else echo "NG: 旗標有但 /dev/kvm 不存在 → 執行 sudo modprobe kvm_intel"; fi
> ```
> ```text
> OK
> ```
> 重點是理解**兩個條件是獨立的**：
> - CPU 旗標存在 ≠ 模組載入了
> - 模組載入了 ≠ 你有權限用（那是第三個條件，`ls -l /dev/kvm` + `id -nG`）

**練習 2（★★★★★）**
故意重現「加了群組卻不能用」的情境，並用兩個指令證明問題所在。

> [!question]- 參考答案
> ```bash
> # 1. 先確認自己不在群組（若已在，先移除來重現）
> sudo gpasswd -d $USER libvirt
> ```
> ```text
> Removing user ops from group libvirt
> ```
> ```bash
> # 2. 重新登入後確認連不上
> virsh -c qemu:///system list --all
> ```
> ```text
> error: failed to connect to the hypervisor
> error: Failed to connect socket to '/var/run/libvirt/virtqemud-sock': Permission denied
> ```
> ```bash
> # 3. 加回群組
> sudo usermod -aG libvirt $USER
> ```
> ```bash
> # 4. ★★★★★ 關鍵：兩個指令證明差異
> id -nG $USER    # 檔案裡的（已更新）
> id -nG          # 這個 shell 的（還是舊的）
> ```
> ```text
> ops adm sudo kvm libvirt
> ops adm sudo kvm
> ```
> **兩者不一致，就是問題所在。**
> 群組成員資格在**登入那一刻**被寫進程序憑證，改 `/etc/group` 不會回頭改已存在的程序。
> 登出重新登入後兩者一致，`virsh` 就能用。★★★★★

**練習 3（★★★★★）**
在同一台機器上，用同一個帳號建立兩台名字都叫 `test01` 的 VM 定義：
一台在 `qemu:///system`，一台在 `qemu:///session`。
然後證明「這兩個世界互相看不到」。

> [!question]- 參考答案
> ```bash
> # 在 system 模式建一個最小定義（不啟動）
> virt-install --connect qemu:///system --name test01 \
>   --memory 512 --vcpus 1 --disk none --boot hd \
>   --os-variant generic --import --noautoconsole --print-xml > /tmp/sys.xml
> virsh -c qemu:///system define /tmp/sys.xml
> ```
> ```text
> Domain 'test01' defined from /tmp/sys.xml
> ```
> ```bash
> # 在 session 模式建同名的
> virsh -c qemu:///session define /tmp/sys.xml
> ```
> ```text
> Domain 'test01' defined from /tmp/sys.xml
> ```
> ★★★★★ **同名沒有衝突**，因為是兩個完全獨立的命名空間。
>
> 證明互相看不到：
> ```bash
> virsh -c qemu:///system list --all
> virsh -c qemu:///session list --all
> ```
> ```text
>  Id   Name     State
> ------------------------
>  -    test01   shut off
> 
>  Id   Name     State
> ------------------------
>  -    test01   shut off
> ```
> 看起來一樣，但定義檔在不同地方：
> ```bash
> sudo ls /etc/libvirt/qemu/*.xml
> ls ~/.config/libvirt/qemu/*.xml
> ```
> ```text
> /etc/libvirt/qemu/test01.xml
> /home/ops/.config/libvirt/qemu/test01.xml
> ```
> **清理**：
> ```bash
> virsh -c qemu:///system undefine test01
> virsh -c qemu:///session undefine test01
> ```
>
> 這個實驗做完，你以後再也不會被「VM 不見了」困住。★★★★★

**練習 4（★★★★）**
把 `web01` 的 ISO 移到你的家目錄，然後啟動 VM，觀察錯誤訊息，
並用 `dmesg` 找出真正的原因。做完把它移回去。

> [!question]- 參考答案
> ```bash
> sudo cp /var/lib/libvirt/images/iso/ubuntu-24.04-live-server-amd64.iso ~/
> virsh destroy web01 2>/dev/null
> virt-xml web01 --edit --cdrom /home/ops/ubuntu-24.04-live-server-amd64.iso
> virsh start web01
> ```
> ```text
> error: Failed to start domain 'web01'
> error: internal error: process exited while connecting to monitor: ... Could not open '/home/ops/ubuntu-24.04-live-server-amd64.iso': Permission denied
> ```
> 找真正的原因：
> ```bash
> sudo dmesg | grep -i apparmor | tail -3
> ```
> ```text
> [ 8421.113049] audit: type=1400 audit(1756795234.881:142): apparmor="DENIED" operation="open" profile="libvirt-7d3f1c92-4a6b-4e81-9f25-3c8a1e7b5d04" name="/home/ops/ubuntu-24.04-live-server-amd64.iso" pid=6142 comm="qemu-system-x86" requested_mask="r" denied_mask="r"
> ```
> ★★★★★ **不是檔案權限問題，是 AppArmor 的 profile 不允許這個路徑。**
> 這就是為什麼「`ls -l` 看起來明明可讀卻開不了」。
>
> 正確解法（由好到壞）：
> 1. ★★★★★ **把映像放回 `/var/lib/libvirt/images/`** —— 最簡單也最安全
> 2. ★★★ 建立一個 libvirt 儲存池指向新目錄（libvirt 會自動處理 AppArmor 規則）
> 3. ★★ 手動編輯 AppArmor 的 local 覆寫規則
> 4. ★（不要做）關掉 AppArmor
>
> 復原：
> ```bash
> virt-xml web01 --edit --cdrom /var/lib/libvirt/images/iso/ubuntu-24.04-live-server-amd64.iso
> rm ~/ubuntu-24.04-live-server-amd64.iso
> ```
>
> RHEL 系上等價的訊息會出現在 `ausearch -m avc -ts recent` 或 `/var/log/audit/audit.log`。

**練習 5（★★★★）**
從你的桌面工作機設定 `qemu+ssh://` 遠端管理，並回答：
為什麼建立 VM 時 `Browse Local` 按鈕是灰的？

> [!question]- 參考答案
> ```bash
> # 工作機上
> ssh-copy-id ops@192.168.1.50
> virsh -c qemu+ssh://ops@192.168.1.50/system list --all
> ```
> ```text
>  Id   Name    State
> -----------------------
>  1    web01   running
> ```
> `virt-manager` → File → Add Connection → 勾 `Connect to remote host over SSH`。
>
> **`Browse Local` 是灰的，因為：**
> `virt-manager` 這個**程式**跑在你的工作機上，但 **VM 實際要在遠端伺服器上開**。
> 遠端的 QEMU 程序只能讀取**遠端**檔案系統上的檔案，
> 你工作機硬碟上的 ISO 對它而言不存在。★★★★★
>
> 所以遠端建 VM 時，安裝媒體必須：
> - 放在遠端的 `/var/lib/libvirt/images/`（`default` pool 會看到），或
> - 在遠端建立一個 pool 指向 ISO 目錄：
>   ```bash
>   # 在遠端伺服器上
>   virsh pool-define-as iso dir --target /var/lib/libvirt/images/iso
>   virsh pool-build iso && virsh pool-start iso && virsh pool-autostart iso
>   ```
> - 或改用 **Network Install**，讓遠端直接從網路 mirror 下載
>
> 這個限制同樣適用於磁碟映像匯入。詳見 [[050-01-04-04-guide-KVM-儲存池與網路]]。

---

## 小測驗

Q1. 你在 VMware Workstation 的 Ubuntu Server 裡跑 `kvm-ok`，得到 `Your CPU does not support KVM extensions`。實體機的 CPU 明明是 Intel i7。問題出在哪？怎麼解決？

Q2. 是非題：跑完 `sudo usermod -aG libvirt $USER` 之後，當前的終端機馬上就能用 `virsh` 管理 VM。

Q3. 這兩行輸出不一樣，代表什麼？
```bash
id -nG ops     # → ops adm sudo kvm libvirt
id -nG         # → ops adm sudo
```

Q4. 選擇題：伺服器上要跑正式服務 VM，必須用哪一種模式？為什麼？
（A）`qemu:///session`，比較安全　（B）`qemu:///system`，因為只有它能設定開機自動啟動與橋接網路
（C）兩種都可以　（D）看客體作業系統決定

Q5. 你用 `virt-manager` 在桌面上建了 VM，隔天 SSH 進去 `virsh list --all` 卻是空的。列出兩個檢查步驟。

Q6. VM 啟動失敗，訊息是 `Could not open '/home/ops/vm/web01.qcow2': Permission denied`。你已經確認 `ls -l` 顯示檔案是 `644` 且擁有者正確。真正的原因是什麼？

Q7. 簡答：`virt-manager` 建立 VM 的第 5 頁為什麼建議一定要勾 `Customize configuration before install`？

Q8. 客體 Ubuntu 安裝程式裡，磁碟顯示為 `sda` 而不是 `vda`。代表什麼？影響是什麼？

Q9. 是非題：`newgrp libvirt` 是「加了群組不用重新登入」的完美替代方案。

Q10. 你想從辦公室的桌機管理機房裡一台沒有桌面的 KVM 伺服器。列出你會用的連線 URI，以及**絕對不該**採用的做法。

> [!question]- 測驗答案
> **Q1.** 問題出在 **VMware Workstation 沒有開啟巢狀虛擬化**。
> 實體 CPU 支援不等於客體看得到——Workstation 預設**不會**把 VT-x 暴露給客體。
> 解法：把 Ubuntu Server 這台 VM **關機**，
> VM → Settings → **Processors** → 勾選
> **`Virtualize Intel VT-x/EPT or AMD-V/RVI`**，再開機。
> 開機後 `grep -c -E '(vmx|svm)' /proc/cpuinfo` 應該大於 0。
> Windows 主機若啟用了 Hyper-V／WSL2，還可能有額外衝突，
> 見 [[050-01-02-06-guide-Workstation-效能調校與疑難排解]]。★★★★★
> （見「觀念說明 → 本手冊的實驗環境」）
>
> **Q2.** **錯。** 群組成員資格是在**登入那一刻**被寫進 shell 程序的
> supplementary groups 憑證裡的。`usermod` 只改了 `/etc/group` 這個檔案，
> **已經存在的 shell 程序完全不知道**。必須**登出再登入**（或重開機）。
> 這不是 libvirt 的特殊行為，是 Linux 權限模型的基本規則。★★★★★
> （見「觀念說明 → 為什麼加了群組還要重新登入」）
>
> **Q3.** 代表**「檔案裡已經改好，但目前這個 shell 還沒生效」**。
> - `id -nG ops` 帶了使用者名稱 → 去查 `/etc/group` **檔案**，
>   所以看得到剛加上的 `libvirt`
> - `id -nG` 不帶參數 → 顯示**當前程序實際持有的憑證**，
>   還是登入當下那一份
>
> 這組指令是診斷「加了群組不能用」最快的方法。解法：登出重新登入。★★★★★
> （見「觀念說明 → 用兩個指令看出差別」）
>
> **Q4.** **（B）**。`qemu:///session` 有兩個致命限制：
> **不能用 `virbr0` 或橋接網路**（建 TAP 裝置需要 root 權限，
> 只能用使用者模式網路，外部連不進來），
> 以及**不能開機自動啟動**（daemon 依附於使用者 session，沒登入就沒有）。
> 正式服務 VM 兩者都是必要條件。
> session 模式的正當用途是桌面上的個人測試 VM。★★★★★
> （見「觀念說明 → system 與 session」）
>
> **Q5.** 兩個檢查：
> 1. **`virsh uri`** ★★★★★ —— 看你現在連到 `qemu:///system` 還是
>    `qemu:///session`。這是九成情況的答案。
> 2. **`virsh -c qemu:///session list --all`** 與
>    **`virsh -c qemu:///system list --all`** 都跑一次，看 VM 在哪一邊。
>
> 找到之後永久修正：`export LIBVIRT_DEFAULT_URI=qemu:///system` 寫進 `~/.bashrc`
> （或 `/etc/profile.d/`），並在 `virt-manager` 裡確認用的是 system 連線。★★★★★
> （見「觀念說明 → 為什麼這件事會害死人」）
>
> **Q6.** 真正的原因是 **AppArmor（Ubuntu）或 SELinux（RHEL）**
> 的強制存取控制擋住了 `/var/lib/libvirt/images/` 以外的路徑。
> POSIX 檔案權限（`644`、擁有者）**通過了**，但 MAC 層另外否決。
> 確認方式：`sudo dmesg | grep -i apparmor`（會看到 `apparmor="DENIED"`），
> RHEL 用 `sudo ausearch -m avc -ts recent`。
> 正確解法是**把映像放回 `/var/lib/libvirt/images/`**，
> 或建立 libvirt 儲存池指向該目錄（libvirt 會自動處理規則），
> ★★★★★ **不要關掉 AppArmor／SELinux**——那會拆掉 VM 之間的隔離。
> （見「常見錯誤與排錯」與「練習 4」）
>
> **Q7.** 因為有些設定**只能在安裝前決定，或改了必須完整停機才生效**：
> **韌體 BIOS/UEFI**（安裝後改會開不了機）、**磁碟匯流排**（IDE/SATA → VirtIO）、
> **網卡型號**、**CPU model**、**晶片組 Q35/i440FX**。
> 勾了之後多出一個設定畫面，可以在真正開機安裝之前把這些調好，
> 避免「裝完才發現磁碟用的是 SATA、網卡是 e1000」而必須重來。★★★★★
> （見「完整實戰範例 → 第 5 頁」）
>
> **Q8.** 代表**磁碟匯流排不是 VirtIO**（是 SATA 或 IDE 的模擬裝置）。
> 影響是**磁碟 I/O 效能大幅下降**——模擬裝置每次 I/O 都要大量 VM exit，
> VirtIO 則透過共享記憶體的環形佇列批次處理。
> 解法是停機後把 `bus` 改成 `virtio`。
> ★★★★ 注意：**對已經安裝好的系統改匯流排要小心**——
> 裝置名會從 `sda` 變成 `vda`，若 `/etc/fstab` 或 GRUB 用的是裝置名而非 UUID，
> 客體會開不了機。現代發行版預設用 UUID，通常沒事，但改之前先確認。
> （見「完整實戰範例 → 第 6 頁」與「常見錯誤與排錯」）
>
> **Q9.** **錯。** `newgrp libvirt` 只會開一個**擁有該群組的子 shell**，
> 影響範圍極窄：另開的終端機分頁沒有、`exit` 之後就沒有、
> `tmux`／`screen` 開的新視窗也沒有。
> 結果是「有時候可以有時候不行」，**比完全不能動還難診斷**。
> 應急可以用，但正確做法永遠是**登出再登入**。★★★★
> （見「觀念說明 → 四種讓它生效的方法」）
>
> **Q10.** **會用的**：
> ```text
> qemu+ssh://ops@<伺服器IP>/system
> ```
> 在桌機裝 `virt-manager` + `virt-viewer`，先設好 **SSH 金鑰登入**
> （`ssh-copy-id`），然後 File → Add Connection → 勾
> `Connect to remote host over SSH`。VNC/SPICE 主控台會自動走 SSH 通道轉發。
>
> **★★★★★ 絕對不該做的**：
> 1. **打開 libvirt 的 TCP 監聽**（`listen_tcp = 1`，port 16509，
>    尤其配上 `auth_tcp = "none"`）——那等於把主機 root 權限公開在網路上
> 2. **把 VNC/SPICE 綁到 `0.0.0.0`** 讓人直接連——主控台無認證，
>    等於任何人都能操作客體
> 3. 長期開著 `ssh -X` 並在伺服器裝一整套 GUI 相依套件
>
> 想要瀏覽器介面的話，正確選項是 **Cockpit + cockpit-machines**（走 HTTPS/9090）。★★★★★
> （見「進階應用 → 遠端管理」與「安全性注意事項」）

---

## 延伸閱讀

**本章其他篇**

- [[050-01-04-01-guide-KVM-KVM與libvirt架構]] — 三層分工、domain XML、PVE 與 KVM 的關係
- [[050-01-04-03-cmd-KVM-virsh指令實務]] — ★★★★★ **接續本篇**，把 `web01` 全部改用指令重做
- [[050-01-04-04-guide-KVM-儲存池與網路]] — storage pool、NAT 改橋接
- [[050-01-04-05-guide-KVM-自動化與範本]] — `virt-install`、cloud-init 量產 VM

**Workstation（本篇的第一層環境）**

- [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] — ★★★★★ **巢狀虛擬化怎麼開**
- [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] — 先做出 Ubuntu Server 那台 VM
- [[050-01-02-04-guide-Workstation-網路模式]] — NAT／Bridged／Host-only

**PVE（對照）**

- [[050-01-03-01-svc-PVE-安裝與初始設定]] — PVE 端的 KVM 驗證
- [[050-01-03-03-guide-PVE-虛擬機管理]] — VirtIO、CPU type、快取模式的完整討論

**虛擬化基礎**

- [[050-01-01-03-ref-虛擬化-五平台橫向對照]] — 平台取捨
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] — VT-x、EPT、VirtIO 原理

**Linux 基礎**

- [[020-01-14-guide-Linux-套件管理]] — `apt` / `dnf`
- [[020-01-09-cmd-Linux-使用者與群組管理]] — 群組、`usermod`、`id`
- [[020-01-08-cmd-Linux-檔案權限與擁有者]] — 裝置檔權限
- [[020-01-26-guide-Linux-核心模組與sysctl調校]] — `modprobe` 與模組參數
- [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] — 遠端管理的前提
- [[020-01-17-cmd-Linux-systemd服務管理]] — service 與 socket 單元
