---
title: "KVM與libvirt架構"
desc: "KVM 核心模組、QEMU 模擬器、libvirt 管理層三者的分工與界線，libvirtd 到 virtqemud 的演進，domain XML 的角色，以及 PVE 底層與 KVM 的真正關係"
aliases: [KVM 架構, libvirt, libvirtd, virtqemud, domain XML, QEMU, KVM 與 PVE 的關係]
tags: [群組/虛擬機與容器, 虛擬化/kvm, 主題/虛擬化]
category: 虛擬化平台
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-01-02-guide-虛擬化-虛擬化底層技術]]", "[[020-01-26-guide-Linux-核心模組與sysctl調校]]"]
updated: 2026-09-02
---

# KVM與libvirt架構

> [!note] 本章在本手冊裡的定位
> 本手冊的虛擬化**主線是 VMware Workstation（桌面測試環境）與 Proxmox VE（機關正式環境）**。
> KVM 章屬於**輔助線**，存在的理由有兩個，而且兩個都很硬：
>
> 1. **單機 Linux 虛擬化**——你只有一台 Linux 伺服器、只想在上面跑三五台 VM，
>    裝一整套 PVE 反而是負擔時，`KVM + libvirt` 就是正解。
> 2. ★★★★★ **理解 PVE 的底層**——PVE 的虛擬化引擎**就是 KVM + QEMU**。
>    看懂這一章，PVE 後台那些看似神秘的選項（CPU type、machine type、
>    VirtIO、快取模式）會全部變成常識，出事時你也才知道要去 `/var/log/` 的哪裡找。
>
> 平台之間的取捨請見 [[050-01-01-03-ref-虛擬化-五平台橫向對照]]。

> [!warning] 未實機驗證
> 本篇以 **Ubuntu Server 24.04 LTS + libvirt 10.x** 為敘述基準。
> libvirt 的**守護行程拆分（`libvirtd` → `virtqemud` 等模組化 daemon）**
> 各發行版切換的版本不同，Debian／Ubuntu 與 RHEL 系的預設值也不一樣；
> QEMU 的 machine type 版本字串（`pc-q35-8.2` 之類）更是每個版本都在變。
> **動手前一律以 `virsh version`、`systemctl status` 與 `man virsh` 的實際輸出為準**。
> 觀念、分層界線與排錯思路不受版本影響。

> [!abstract] 這篇你會學到
> - ★★★★★ **KVM／QEMU／libvirt 三層各做什麼、界線在哪**：
>   誰負責 CPU、誰負責裝置、誰負責管理，講錯一層就會找錯 log
> - 為什麼「KVM 是 Type-1 還是 Type-2」這個問題本身問錯了 ★★★
> - ★★★★ **一台 VM 在 Linux 上到底是什麼**：一個 `qemu-system-x86_64` 程序，
>   用 `ps`、`top`、`kill` 就看得到、殺得掉
> - `libvirtd` 單一守護行程 → `virtqemud` 模組化守護行程的演進，
>   以及**你的機器現在跑的是哪一種怎麼判斷** ★★★★
> - ★★★★ **domain XML 的角色**：它是設定的唯一真相來源，
>   以及為什麼**不能直接用 vim 改** `/etc/libvirt/qemu/*.xml`
> - ★★★★★ **PVE 與 KVM 的真正關係**：PVE 用 KVM+QEMU，
>   **但完全不用 libvirt**，它有自己的 `qm` 與 `/etc/pve/qemu-server/`
> - 什麼時候該用純 KVM、什麼時候該直接上 PVE ★★★★
> - 與 VMware（Workstation／ESXi／vCenter）的概念一一對照 ★★★

## 前置知識

- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] — VT-x／AMD-V、EPT、VirtIO、全虛擬化與半虛擬化
- [[050-01-01-01-guide-虛擬化-虛擬化概念與選型]] — Type-1／Type-2 的分類與意義
- [[050-01-01-03-ref-虛擬化-五平台橫向對照]] — 本手冊五個平台的定位
- [[020-01-26-guide-Linux-核心模組與sysctl調校]] — `lsmod`、`modprobe`、模組參數
- [[020-01-10-cmd-Linux-程序管理與訊號]] — 待會你會用 `ps` 去看 VM 程序
- [[020-01-17-cmd-Linux-systemd服務管理]] — libvirt 是一組 systemd 服務與 socket

---

## 觀念說明

### ★★★★★ 一句話講完三層

先給結論，後面再拆開：

```text
┌─────────────────────────────────────────────────────────────┐
│  virt-manager / virsh / virt-install / Cockpit / OpenStack   │  ← 使用者介面
├─────────────────────────────────────────────────────────────┤
│  libvirt（libvirtd / virtqemud）                             │  ← 管理層
│   ‧ domain XML、storage pool、virtual network                │
│   ‧ 記住「你有哪些 VM」、開機自動啟動、權限控制               │
├─────────────────────────────────────────────────────────────┤
│  QEMU（qemu-system-x86_64）                                  │  ← 使用者空間
│   ‧ 模擬主機板、磁碟控制器、網卡、顯示卡、USB                 │
│   ‧ 一台 VM = 一個 QEMU 程序                                 │
├─────────────────────────────────────────────────────────────┤
│  KVM（kvm.ko + kvm_intel.ko / kvm_amd.ko）→ /dev/kvm         │  ← Linux 核心
│   ‧ 只做 CPU 與記憶體虛擬化，靠 VT-x / AMD-V + EPT / NPT      │
├─────────────────────────────────────────────────────────────┤
│  實體硬體（CPU 必須支援 VT-x 或 AMD-V）                       │
└─────────────────────────────────────────────────────────────┘
```

用一句話記住三者的分工：

> **KVM 讓 CPU 跑得快，QEMU 讓 VM 看起來像一台電腦，libvirt 讓你管得動。**

| 層 | 東西 | 在哪裡 | 沒有它會怎樣 |
| --- | --- | --- | --- |
| **KVM** ★★★★★ | 核心模組 | `kernel` / `/dev/kvm` | QEMU 退回純軟體模擬，慢 10～50 倍 |
| **QEMU** ★★★★★ | 使用者空間程式 | `/usr/bin/qemu-system-x86_64` | 沒有虛擬硬體，VM 根本開不起來 |
| **libvirt** ★★★★ | 守護行程 + 函式庫 | `/usr/sbin/libvirtd` 等 | VM 還是能跑，但要自己手打幾十個 QEMU 參數、關機就忘光 |

### ★★★★★ KVM：核心裡的那一層，只管 CPU 與記憶體

KVM（Kernel-based Virtual Machine）是 **Linux 核心的一個模組**，2007 年併入主線核心。
它做的事情非常窄，窄到很多人誤會它的角色：

**KVM 只做兩件事**：

1. 把 CPU 的硬體虛擬化指令（Intel **VT-x** / AMD **AMD-V**）包成一個可以用的介面
2. 用 **EPT**（Intel）／**NPT**（AMD）做二階分頁轉換，讓客體的記憶體位址能直接對映到實體記憶體

**KVM 不做的事**（這才是重點）：

- ❌ 不模擬磁碟、網卡、顯示卡、USB、主機板 —— 那是 QEMU 的事
- ❌ 不管理 VM 的生命週期、不知道你有幾台 VM —— 那是 libvirt 的事
- ❌ 不提供任何管理介面 —— 它只是一個 `/dev/kvm` 字元裝置

看一下它長什麼樣子：

```bash
lsmod | grep kvm
```

```text
kvm_intel             487424  6
kvm                  1409024  1 kvm_intel
irqbypass              12288  1 kvm
```

```bash
ls -l /dev/kvm
```

```text
crw-rw---- 1 root kvm 10, 232 Sep  2 09:14 /dev/kvm
```

> [!note] ★★★★ `/dev/kvm` 的權限決定了誰能開 VM
> 這個裝置檔屬於 **`kvm` 群組**。QEMU 程序必須能開啟它才能用硬體加速。
> 這就是為什麼 [[050-01-04-02-svc-KVM-安裝與virt-manager]] 裡
> 「加群組、重新登入」那一節那麼重要——**權限沒給對，VM 不是開不起來，
> 就是掉回超慢的純軟體模擬**。

#### ★★★ 所以「KVM 是 Type-1 還是 Type-2」？

這個問題常在考題與文件裡出現，答案是：**這個分類套在 KVM 上本來就不精準**。

| 觀點 | 說法 | 理由 |
| --- | --- | --- |
| 說它是 Type-1 ★★★ | **KVM 把 Linux 核心本身變成 hypervisor** | 虛擬化程式碼跑在 ring -1（VMX root），直接管硬體，中間沒有另一個作業系統 |
| 說它是 Type-2 ★★ | KVM 需要一個完整的 Linux 作業系統才能跑 | 從「要不要先裝一個 OS」的角度看，像 Type-2 |

**業界共識偏向前者**：KVM 是 Type-1，因為決定分類的是「**虛擬化層跟硬體之間有沒有隔一層 OS**」，
而 KVM 就在核心裡，沒有隔。VMware ESXi 是純粹的 Type-1，VMware Workstation 是標準的 Type-2。

實務上的意義是：**別把 KVM 想成「跑在 Linux 上的 VMware Workstation」**，
它的效能等級跟 ESXi 是同一檔的。Type-1／Type-2 的完整討論見
[[050-01-01-01-guide-虛擬化-虛擬化概念與選型]]。

### ★★★★★ QEMU：一台 VM 就是一個程序

QEMU（Quick EMUlator）是**使用者空間的程式**，負責模擬「一台電腦除了 CPU 以外的所有東西」：
晶片組、PCI 匯流排、磁碟控制器、網卡、顯示卡、鍵盤滑鼠、USB 控制器、韌體（SeaBIOS／OVMF）。

QEMU 本身也能模擬 CPU（甚至能模擬 ARM、RISC-V 等跨架構 CPU，這叫 TCG 模式），
但**軟體模擬 CPU 極慢**。所以在 x86 主機上跑 x86 客體時，
QEMU 會把 CPU 的部分**交給 KVM**：

```bash
# 概念示意：QEMU 用 KVM 當加速器
qemu-system-x86_64 -accel kvm -m 2048 -smp 2 ...
```

> [!note] ★★★★ 這是全篇最實用的一個認知
> **一台執行中的 VM，在 Linux 上就是一個 `qemu-system-x86_64` 程序。**
>
> 這代表：
> - `ps`、`top`、`htop` 都看得到它，`%CPU` 就是那台 VM 的 CPU 用量
> - `kill -9 <pid>` 會**直接把那台 VM 斷電**（等同拔插頭，★★★★★ 別亂用）
> - `nice`、`cgroup`、`taskset` 這些 Linux 工具**對 VM 全部有效**
> - VM 的記憶體就是這個程序的 RSS
> - 檔案描述子、開啟的 socket，用 `lsof -p <pid>` 全看得到

實際看一下（VM 已啟動的情況）：

```bash
ps -ef | grep '[q]emu-system' | head -1
```

```text
libvirt+  4821     1 12 09:22 ?        00:03:41 /usr/bin/qemu-system-x86_64 -name guest=web01,debug-threads=on -S -object {"qom-type":"secret",...} -machine pc-q35-8.2,usb=off,vmport=off,dump-guest-core=off,memory-backend=pc.ram -accel kvm -cpu host -m size=2097152k ...
```

幾個可以馬上讀懂的重點：

| 片段 | 意義 |
| --- | --- |
| `libvirt+` | 執行身分是 `libvirt-qemu`（Ubuntu／Debian）。RHEL 系是 `qemu` ★★★ |
| `-name guest=web01` | 這個程序對應哪一台 VM ★★★★ |
| `-machine pc-q35-8.2` | machine type，就是 PVE 後台那個 `q35` ★★★★ |
| `-accel kvm` | ★★★★★ **有這個才是硬體加速**。看到 `-accel tcg` 就是掉回軟體模擬 |
| `-cpu host` | CPU type，跟 PVE 的 `cpu: host` 是同一件事 ★★★★ |

再看它的執行緒：

```bash
ps -L -p 4821 -o pid,tid,comm | head
```

```text
    PID     TID COMMAND
   4821    4821 qemu-system-x86
   4821    4823 qemu-system-x86
   4821    4831 CPU 0/KVM
   4821    4832 CPU 1/KVM
   4821    4834 vnc_worker
```

★★★★ **每一個 vCPU 是一個 `CPU n/KVM` 執行緒**。
這解釋了為什麼「給 VM 8 個 vCPU」在主機上就是「多開 8 條可以搶 CPU 的執行緒」，
以及為什麼超額配置 vCPU 會讓所有 VM 一起變慢（見 [[050-01-03-09-svc-PVE-監控與資源調校]]）。

### ★★★★ libvirt：管理層，而且不只管 KVM

如果只有 KVM + QEMU，你要開一台 VM 得手打一行長達兩三百個字元的 `qemu-system-x86_64` 指令，
關機之後那行指令就消失了。libvirt 就是來解決這件事的。

libvirt 提供：

| 提供什麼 | 具體是什麼 |
| --- | --- |
| **持久化的定義** ★★★★★ | domain XML，存在 `/etc/libvirt/qemu/<name>.xml` |
| **統一的 API** ★★★★ | C 函式庫 `libvirt.so`，另有 Python／Go／Java 等綁定 |
| **命令列工具** ★★★★★ | `virsh` |
| **儲存管理** ★★★★ | storage pool 與 volume（目錄、LVM、iSCSI、NFS、Ceph RBD…） |
| **網路管理** ★★★★ | virtual network（NAT 的 `default`／`virbr0`、橋接、隔離網路） |
| **權限控制** ★★★★ | 透過 polkit 決定誰能操作，不必給 root |
| **遠端存取** ★★★★ | `qemu+ssh://` 之類的連線 URI |
| **快照與遷移** ★★★★ | `snapshot-*`、`migrate` |

> [!note] ★★★ libvirt 不等於 KVM
> libvirt 是一個**抽象層**，底下可以接很多種 hypervisor：
> `qemu:///`（QEMU/KVM）、`lxc:///`、`xen:///`、`vbox:///`、
> `esx://`（連 VMware ESXi）、`bhyve:///`（FreeBSD）……
>
> 所以 `virsh` 連上去的第一件事永遠是**確認 URI**：
> ```bash
> virsh uri
> ```
> ```text
> qemu:///system
> ```
> 這個習慣可以省下大量「我明明建了 VM 為什麼 `virsh list` 是空的」的時間 ★★★★
> （原因幾乎都是你連到了 `qemu:///session`，見 [[050-01-04-02-svc-KVM-安裝與virt-manager]]）。

### ★★★★ libvirtd → virtqemud：守護行程的模組化演進

這是近幾年 libvirt 最大的架構改變，也是**新舊教學文件互相矛盾的主因**。

#### 舊架構：單一 `libvirtd`

歷史上 libvirt 只有一個大守護行程 `libvirtd`，它同時負責 QEMU、儲存、網路、
節點裝置、密鑰、網路過濾規則所有事情。

問題很明顯：

- 一個功能出事，**整個 `libvirtd` 一起掛**，所有 VM 的管理都斷掉
- 想只用 QEMU 功能，還是得把整包網路／儲存的程式碼載進來
- 權限切割困難

#### 新架構：一個功能一個 daemon

libvirt 從 5.7 開始拆分，逐步在各發行版變成預設：

| 模組化 daemon | 負責 | 取代 `libvirtd` 的哪一塊 |
| --- | --- | --- |
| `virtqemud` ★★★★★ | QEMU/KVM 虛擬機 | 核心的 domain 管理 |
| `virtnetworkd` ★★★★ | 虛擬網路（`virbr0`、dnsmasq） | 網路 |
| `virtstoraged` ★★★★ | 儲存池與 volume | 儲存 |
| `virtnodedevd` ★★★ | 主機裝置（PCI 直通會用到） | node device |
| `virtsecretd` ★★★ | 密鑰（如 Ceph 認證） | secret |
| `virtnwfilterd` ★★ | 網路過濾規則 | nwfilter |
| `virtinterfaced` ★★ | 主機網路介面 | interface |
| `virtproxyd` ★★★ | 提供舊版 socket 相容與遠端連線代理 | 相容層 |
| `virtlogd` ★★★ | 客體序列埠／QEMU log 的收集與輪替 | 一直是獨立的 |
| `virtlockd` ★★★ | 磁碟鎖，防止兩個 QEMU 同時開同一個磁碟檔 | 一直是獨立的 |

> [!warning] ★★★★ 你的機器跑的是哪一種？先查再說
> **不要照抄網路上的 `systemctl restart libvirtd`**，在模組化的機器上那可能什麼都沒做到。
>
> ```bash
> systemctl list-units --type=service 'virt*' 'libvirt*' --no-pager
> ```
>
> 模組化架構會看到：
> ```text
> virtlogd.service      loaded active running Virtual machine log manager
> virtnetworkd.service  loaded active running Virtual network daemon
> virtqemud.service     loaded active running Virtualization qemu daemon
> virtstoraged.service  loaded active running Virtualization storage daemon
> ```
>
> 傳統架構會看到：
> ```text
> libvirtd.service      loaded active running Virtualization daemon
> virtlogd.service      loaded active running Virtual machine log manager
> ```
>
> ★★★★ **一般而言 RHEL 9 以後預設模組化、Debian／Ubuntu 較晚才切換**，
> 但兩邊都在變，**以你機器上的實際輸出為準**。

#### ★★★★ socket 啟動（socket activation）：為什麼服務「沒開」也能用

不論新舊架構，libvirt 都大量使用 **systemd socket activation**：
`.socket` 單元先在那裡監聽，**第一次有人連進來時才把 `.service` 叫起來**。

```bash
systemctl status virtqemud.socket
```

```text
● virtqemud.socket - Libvirt qemu local socket
     Loaded: loaded (/usr/lib/systemd/system/virtqemud.socket; enabled; preset: enabled)
     Active: active (listening) since Tue 2026-09-02 09:14:03 CST; 1h 8min ago
     Listen: /run/libvirt/virtqemud-sock (Stream)
```

實務推論 ★★★★：

- `systemctl status virtqemud` 顯示 `inactive (dead)` **不一定是壞了**，
  可能只是還沒有人用過。跑一次 `virsh list` 它就會被叫起來。
- 真正要「開機就啟用」的是 **`.socket`**（`systemctl enable --now virtqemud.socket`）。
- 改了 `/etc/libvirt/qemu.conf` 之後要重啟的是 **`virtqemud.service`**（或 `libvirtd.service`），
  **重啟 daemon 不會影響已經在跑的 VM**（VM 是獨立的 QEMU 程序，見上一節）。

> [!tip] ★★★★ 「重啟 libvirt 會不會把 VM 弄掛？」
> **不會。** VM 是獨立的 QEMU 程序，libvirt 只是透過 monitor socket 跟它們對話。
> 重啟守護行程後 libvirt 會重新接管既有的 VM。
> 這跟 VMware Workstation「關掉主程式 VM 就停」的模型完全不同，是很多人第一次的驚喜。

### ★★★★★ domain XML：設定的唯一真相來源

libvirt 用一份 XML 描述一台 VM（libvirt 的術語叫 **domain**）。

```bash
virsh dumpxml web01 | head -40
```

```xml
<domain type='kvm'>
  <name>web01</name>
  <uuid>7d3f1c92-4a6b-4e81-9f25-3c8a1e7b5d04</uuid>
  <memory unit='KiB'>2097152</memory>
  <currentMemory unit='KiB'>2097152</currentMemory>
  <vcpu placement='static'>2</vcpu>
  <os>
    <type arch='x86_64' machine='pc-q35-8.2'>hvm</type>
    <boot dev='hd'/>
  </os>
  <features>
    <acpi/>
    <apic/>
  </features>
  <cpu mode='host-passthrough' check='none' migratable='on'/>
  <devices>
    <emulator>/usr/bin/qemu-system-x86_64</emulator>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' discard='unmap'/>
      <source file='/var/lib/libvirt/images/web01.qcow2'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <interface type='network'>
      <mac address='52:54:00:a3:1f:8c'/>
      <source network='default'/>
      <model type='virtio'/>
    </interface>
    <console type='pty'>
      <target type='serial' port='0'/>
    </console>
  </devices>
</domain>
```

#### 把它跟 PVE 的設定檔對照著看 ★★★★★

| domain XML | PVE `qm config` | 意義 |
| --- | --- | --- |
| `<domain type='kvm'>` | （隱含） | 用 KVM 加速 |
| `<name>web01</name>` | `name: web01` | VM 名稱 |
| `<memory unit='KiB'>2097152` | `memory: 2048` | 記憶體 |
| `<vcpu>2</vcpu>` | `cores: 2` / `sockets: 1` | vCPU 數 |
| `machine='pc-q35-8.2'` | `machine: q35` | 晶片組型別 |
| `<cpu mode='host-passthrough'>` | `cpu: host` | ★★★★★ CPU type，會影響能不能遷移 |
| `type='qcow2'` | 儲存層決定 | 磁碟格式 |
| `bus='virtio'` | `virtio0` / `scsi0` + `virtio-scsi` | ★★★★★ VirtIO |
| `<model type='virtio'/>` | `net0: virtio=...` | ★★★★★ VirtIO 網卡 |
| `<source network='default'/>` | `bridge=vmbr0` | 接到哪個網路 |

看懂了嗎？**同樣的東西，換了一種寫法而已**。這就是本章對 PVE 使用者的最大價值。

#### ★★★★★ 絕對不要直接 `vim /etc/libvirt/qemu/web01.xml`

這是新手最常犯、而且**改了不會生效還會被覆蓋**的錯誤。

```bash
ls -l /etc/libvirt/qemu/
```

```text
total 12
drwxr-xr-x 3 root root 4096 Sep  2 09:14 networks
-rw------- 1 root root 4823 Sep  2 09:41 web01.xml
```

檔案就在那裡，看起來很好改。但是：

| 為什麼不行 | 說明 |
| --- | --- |
| ★★★★★ **記憶體裡有一份** | 執行中的 `virtqemud` 快取了設定，你改檔案它不知道 |
| ★★★★★ **會被覆寫** | 下一次任何 libvirt 操作寫回設定時，你的修改直接消失 |
| ★★★★ **沒有語法驗證** | 打錯一個標籤，VM 直接無法啟動且訊息難懂 |
| ★★★★ **檔頭就寫了警告** | 檔案第一行就是 `<!-- WARNING: THIS IS AN AUTO-GENERATED FILE... -->` |

**正確做法只有一個**：

```bash
virsh edit web01
```

`virsh edit` 會：叫起 `$EDITOR` → 你改完存檔 → **libvirt 驗證語法** →
寫回設定並同步記憶體中的狀態。詳細操作見 [[050-01-04-03-cmd-KVM-virsh指令實務]]。

> [!warning] ★★★★ 改了 XML 什麼時候生效？
> 跟 PVE 一樣的規則：**硬體層級的變更（CPU、記憶體上限、machine type、
> 磁碟匯流排、網卡型號）要「完整停機再開機」才生效**。
> 客體裡面 `reboot`、`virsh reboot` 都**不會**重建 QEMU 程序，改的東西不會套用。
> 必須 `virsh shutdown` → `virsh start`。

### ★★★★★ PVE 與 KVM 的關係（本篇最重要的一節）

這一節請看兩次。

#### PVE 底層就是 KVM + QEMU

Proxmox VE 不是一個「另一種虛擬化技術」。它是：

```text
Debian（作業系統）
  + KVM + QEMU（虛擬機引擎）        ← 跟本章講的完全是同一個東西
  + LXC（容器引擎）
  + ZFS / Ceph / LVM-thin（儲存）
  + pmxcfs（叢集設定檔系統，掛在 /etc/pve）
  + corosync（叢集通訊）
  + pve-manager（Web 後台）
  + qm / pct / pvesm / pvecm（命令列工具）
```

在 PVE 主機上做一次驗證，最有說服力：

```bash
# 在 PVE 主機上
lsmod | grep kvm
```

```text
kvm_intel             487424  4
kvm                  1409024  1 kvm_intel
```

```bash
ps -ef | grep '[k]vm ' | head -1
```

```text
root      2914     1 15 09:02 ?  01:12:33 /usr/bin/kvm -id 100 -name web01,debug-threads=on -no-shutdown -chardev socket,id=qmp,path=/var/run/qemu-server/100.qmp ...
```

★★★★ 注意 `/usr/bin/kvm` —— 在 Debian 系上這是 `qemu-system-x86_64` 的別名。
**PVE 的 VM 也是一個 QEMU 程序**，跟你在純 Ubuntu 上開的 VM 沒有本質差別。

#### ★★★★★ 但 PVE **完全不用 libvirt**

這是最多人搞錯的一點。**PVE 沒有裝 libvirt，也不用 domain XML。**

Proxmox 自己寫了一整套管理層來取代 libvirt 的位置：

| 功能 | 純 KVM 環境 | Proxmox VE |
| --- | --- | --- |
| 管理守護行程 ★★★★★ | `libvirtd` / `virtqemud` | `pvedaemon`、`pveproxy`、`pvestatd` |
| VM 定義檔 ★★★★★ | `/etc/libvirt/qemu/<name>.xml`（XML） | `/etc/pve/qemu-server/<vmid>.conf`（key: value） |
| 命令列工具 ★★★★★ | `virsh` | `qm` |
| 儲存管理 ★★★★ | `virsh pool-*` | `pvesm`、`/etc/pve/storage.cfg` |
| 網路 ★★★★ | `virsh net-*`（`virbr0`） | Linux bridge `vmbr0`、`/etc/network/interfaces` |
| VM 識別 ★★★★ | 名稱 + UUID | **數字 VMID**（100、101…） |
| 設定同步 ★★★★ | 無（單機） | **pmxcfs 自動在叢集節點間同步** |
| 圖形介面 ★★★★ | `virt-manager`（桌面程式） | Web 後台（瀏覽器） |

> [!note] ★★★★★ 一句話總結
> **PVE 與純 KVM 共用「引擎」（KVM + QEMU），但用了完全不同的「駕駛艙」（管理層）。**
>
> 所以：
> - 你在本章學的**引擎知識**（VirtIO、CPU type、machine type、快取模式、
>   qcow2、一台 VM 就是一個程序）**在 PVE 上 100% 適用** ★★★★★
> - 你在本章學的**指令**（`virsh`）在 PVE 上**完全不能用**，要換成 `qm` ★★★★★
> - 在 PVE 主機上安裝 libvirt **是自找麻煩**（兩套管理層會搶同一批資源與網路），
>   ★★★★★ **不要做**

> [!danger] ★★★★★ 千萬不要在 PVE 主機上 `apt install libvirt-daemon-system`
> 常見的錯誤動機是「我想用 `virsh`」。後果：
> - libvirt 會自己建立 `virbr0` 與一組 NAT 規則，跟 PVE 的 `vmbr0` 與防火牆規則打架
> - libvirt 看不到 PVE 建立的 VM（那些 VM 不是它定義的），`virsh list` 一片空白
> - 兩套 daemon 可能同時嘗試管理主機網路介面
>
> 想用命令列管 PVE？答案是 **`qm`**，見 [[050-01-03-03-guide-PVE-虛擬機管理]]。

#### ★★★★ 那什麼時候該用純 KVM，什麼時候該上 PVE？

| 情境 | 選擇 | 理由 |
| --- | --- | --- |
| 一台 Linux 伺服器，順便跑 2～5 台 VM ★★★★ | **純 KVM + libvirt** | 不必為了虛擬化重灌整台機器；主機還能跑別的服務 |
| 主機已經有既定用途（如資料庫主機）要加開測試 VM ★★★★ | **純 KVM + libvirt** | PVE 會接管整台機器，不適合 |
| 機關的虛擬化平台，要跑 10 台以上 VM ★★★★★ | **PVE** | 備份、快照、叢集、HA、權限、Web 後台全都現成 |
| 要做 HA、線上遷移、共用儲存 ★★★★★ | **PVE**（或 oVirt／OpenStack） | 純 libvirt 要自己搭一堆東西 |
| 需要非資訊人員也能操作 ★★★★ | **PVE** | Web 後台 + 使用者權限 |
| CI／自動化測試機，要用腳本大量開關 VM ★★★★ | **純 KVM + libvirt** | `virsh` + `virt-install` + cloud-init 很輕巧 |
| 要在筆電上開測試機 ★★★★ | **VMware Workstation** | 見 [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] |
| 已經有 VMware 授權與 vCenter ★★★ | **ESXi** | 見 [[050-01-05-02-guide-其他虛擬化-VMwareESXi與採購考量]] |

> [!tip] ★★★★ 機關實務上的常見組合
> **PVE 跑正式服務 + 開發者筆電用 Workstation + 少數單機伺服器用 KVM**。
> 三者的 guest 都是標準的 x86 VM，磁碟格式互轉也有工具（`qemu-img convert`），
> 所以這種混用不會綁死。完整比較見 [[050-01-01-03-ref-虛擬化-五平台橫向對照]]。

### ★★★ 與 VMware 的概念對照

如果你是從 VMware 過來的，這張表可以省你三天：

| VMware | KVM／libvirt 世界 | 說明 |
| --- | --- | --- |
| **ESXi**（裸機 hypervisor） | **Linux 核心 + KVM 模組** ★★★★ | 都是 Type-1 |
| **VMkernel** | Linux kernel | |
| **vmx 程序**（每台 VM 一個） | **`qemu-system-x86_64` 程序** ★★★★★ | 一台 VM 一個程序，概念完全相同 |
| **`.vmx` 設定檔** | **domain XML** ★★★★★ | VM 的定義 |
| **`.vmdk`** | **`.qcow2` / `.raw`** ★★★★ | 磁碟映像 |
| **VMFS datastore** | **storage pool** ★★★★ | 見 [[050-01-04-04-guide-KVM-儲存池與網路]] |
| **vCenter Server** | **libvirt + oVirt／OpenStack／PVE** ★★★★ | 集中管理層 |
| **vSphere Client** | **`virt-manager`／Cockpit／PVE 後台** ★★★ | 圖形介面 |
| **PowerCLI／`govc`** | **`virsh`／`qm`** ★★★★ | 命令列 |
| **VMware Tools** | **`qemu-guest-agent` + VirtIO 驅動** ★★★★★ | 客體代理，見下方警告 |
| **vSwitch／Port Group** | **Linux bridge／libvirt network** ★★★★ | |
| **vMotion** | **`virsh migrate --live`** ★★★★ | 線上遷移 |
| **vmxnet3**（半虛擬化網卡） | **virtio-net** ★★★★★ | |
| **PVSCSI**（半虛擬化磁碟） | **virtio-blk／virtio-scsi** ★★★★★ | |
| **快照（含記憶體）** | **內部快照 / `savevm`** ★★★★ | 見 [[050-01-04-03-cmd-KVM-virsh指令實務]] |
| **獨立磁碟（不快照）** | `<shareable/>` 或 raw + `snapshot='no'` | ★★★ |

> [!warning] ★★★★ VMware Tools 與 qemu-guest-agent 不是同一件事，也不能互換
> - **VMware Tools** 是一整包（驅動 + 服務 + 共享資料夾 + 拖放）
> - **KVM 世界拆成兩塊**：
>   - **VirtIO 驅動**（Linux 內建於核心；**Windows guest 要另外裝 `virtio-win`**）★★★★★
>   - **`qemu-guest-agent`**（讓主機能正常關機、取得 IP、做一致性快照）★★★★
>
> 兩者都要，而且都不會自動出現。

### ★★★ 一台 VM 從開機到跑起來，中間發生什麼

把三層串起來，你就知道出事時該查哪一層：

```text
1. 你打 virsh start web01
        ↓ （Unix socket /run/libvirt/virtqemud-sock）
2. virtqemud 收到請求
        ↓
3. virtqemud 讀 /etc/libvirt/qemu/web01.xml
        ↓
4. virtqemud 把 XML 翻譯成一長串 QEMU 命令列參數
        ↓
5. virtqemud fork/exec 出 qemu-system-x86_64（身分：libvirt-qemu）
        ↓
6. QEMU 開啟 /dev/kvm（★★★★ 權限不足就在這裡失敗）
        ↓
7. QEMU 建立 vCPU 執行緒，透過 KVM ioctl 進入客體模式
        ↓
8. QEMU 開啟磁碟檔（★★★★ AppArmor／SELinux 會在這裡擋）
        ↓
9. 韌體（SeaBIOS 或 OVMF）啟動 → GRUB → 客體 OS
```

| 失敗點 | 去哪裡看 | 典型訊息 |
| --- | --- | --- |
| 步驟 2 ★★★ | `systemctl status virtqemud` | `Failed to connect socket ... No such file or directory` |
| 步驟 3～4 ★★★★ | `virsh start` 的直接輸出 | `XML error: ...` |
| 步驟 6 ★★★★★ | `dmesg`、`journalctl -u virtqemud` | `Could not access KVM kernel module: Permission denied` |
| 步驟 8 ★★★★★ | `/var/log/libvirt/qemu/<name>.log`、`dmesg \| grep -i apparmor` | `Could not open '...qcow2': Permission denied` |
| 步驟 9 ★★★ | `virsh console` | `No bootable device` |

> [!tip] ★★★★★ 記住這一個路徑就好
> **`/var/log/libvirt/qemu/<VM名稱>.log`**
> 這是 QEMU 程序本身的輸出。VM 開不起來、開起來又立刻死掉、
> 客體崩潰——答案九成在這個檔案的最後 30 行。

---

## 安裝或基礎操作

本篇是觀念篇，完整安裝流程在 [[050-01-04-02-svc-KVM-安裝與virt-manager]]。
這裡先做**只讀不寫**的架構驗證，確認你對三層的理解跟機器上的事實一致。

### ★★★★ 步驟一：確認 CPU 支援硬體虛擬化

```bash
grep -c -E '(vmx|svm)' /proc/cpuinfo
```

```text
4
```

- 回傳 **大於 0** → CPU 有 VT-x（`vmx`，Intel）或 AMD-V（`svm`，AMD）
- 回傳 **0** → 要嘛 CPU 不支援，要嘛 **BIOS/UEFI 沒開**，
  要嘛你在虛擬機裡而**巢狀虛擬化沒開**（見 02 篇）

### ★★★★ 步驟二：確認 KVM 模組已載入

```bash
lsmod | grep -E '^kvm'
```

```text
kvm_intel             487424  0
kvm                  1409024  1 kvm_intel
```

沒有輸出的話手動載入看看（★★★ 正常情況下核心會自動載入）：

```bash
sudo modprobe kvm_intel     # AMD 平台是 kvm_amd
```

失敗時看核心怎麼說：

```bash
sudo dmesg | grep -i kvm | tail -5
```

```text
[    2.148311] kvm: disabled by bios
```

★★★★★ `disabled by bios` 就是**去 BIOS/UEFI 打開 VT-x／AMD-V**，
沒有其他解法，軟體上做什麼都沒用。

### ★★★★ 步驟三：確認 `/dev/kvm` 存在且權限正確

```bash
ls -l /dev/kvm
```

```text
crw-rw---- 1 root kvm 10, 232 Sep  2 09:14 /dev/kvm
```

```bash
id
```

```text
uid=1000(ops) gid=1000(ops) groups=1000(ops),4(adm),27(sudo),108(kvm),109(libvirt)
```

★★★★ 你的 `groups` 裡要有 **`kvm`** 與 **`libvirt`**，這是 02 篇的重點之一。

### ★★★ 步驟四：一次看完整體健康度

libvirt 附了一個很好用的自我檢查工具：

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
  QEMU: Checking for cgroup 'devices' controller support                     : WARN (Enable 'devices' in kernel Kconfig file or mount/enable cgroup controller in your system)
  QEMU: Checking for cgroup 'blkio' controller support                       : PASS
  QEMU: Checking for device assignment IOMMU support                         : WARN (No ACPI DMAR table found, IOMMU either disabled in BIOS or not supported by this hardware)
  QEMU: Checking for secure guest support                                    : WARN (Unknown if this platform has Secure Guest support)
```

> [!note] ★★★ WARN 不一定要修
> - `IOMMU` 的 WARN 只影響 **PCI 直通**（顯示卡、網卡直通），
>   一般用途不需要。要做直通請見 [[050-01-03-10-guide-PVE-硬體直通與GPU]] 的觀念。
> - `Secure Guest` 是 AMD SEV／Intel TDX 的機密運算，機關環境通常用不到。
> - ★★★★★ **前三行必須全 PASS**，那三行 FAIL 才是真的不能用。

### ★★★★ 步驟五：確認 libvirt 的守護行程型態與連線 URI

```bash
virsh version
```

```text
Compiled against library: libvirt 10.0.0
Using library: libvirt 10.0.0
Using API: QEMU 10.0.0
Running hypervisor: QEMU 8.2.2
```

```bash
virsh uri
```

```text
qemu:///system
```

```bash
virsh nodeinfo
```

```text
CPU model:           x86_64
CPU(s):              4
CPU frequency:       2904 MHz
CPU socket(s):       1
Core(s) per socket:  4
Thread(s) per core:  1
NUMA cell(s):        1
Memory size:         8123456 KiB
```

★★★★ 這裡的 `CPU(s)` 是**主機的邏輯核心數**，是你分配 vCPU 時的上限依據。

---

## 進階應用

### ★★★★ 讀懂 QEMU 命令列：從 XML 反推實際參數

當你需要知道「libvirt 到底把我的 XML 翻成什麼」，有一個乾淨的方法
（**不必真的啟動 VM**）：

```bash
virsh domxml-to-native qemu-argv --domain web01
```

```text
LC_ALL=C \
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
HOME=/var/lib/libvirt/qemu/domain-1-web01 \
/usr/bin/qemu-system-x86_64 \
-name guest=web01,debug-threads=on \
-machine pc-q35-8.2,usb=off,vmport=off,dump-guest-core=off \
-accel kvm \
-cpu host,migratable=on \
-m size=2097152k \
-smp 2,sockets=1,cores=2,threads=1 \
-blockdev {"driver":"file","filename":"/var/lib/libvirt/images/web01.qcow2","node-name":"libvirt-1-storage"} \
-device {"driver":"virtio-blk-pci","drive":"libvirt-1-format","id":"virtio-disk0","bootindex":1} \
-netdev {"type":"tap","fd":"31","id":"hostnet0"} \
-device {"driver":"virtio-net-pci","netdev":"hostnet0","id":"net0","mac":"52:54:00:a3:1f:8c"} \
...
```

> [!tip] ★★★★ 這招什麼時候用
> 1. **懷疑效能問題出在某個參數**——直接看展開後的參數比猜快
> 2. **要把 VM 從 libvirt 搬到別的平台**（例如搬去 PVE）——對照參數逐項設定
> 3. **看 QEMU 官方文件時**——文件都是用命令列參數寫的，XML 標籤要自己對應
>
> 反方向也有：`virsh domxml-from-native` 可以把 QEMU 參數轉回 XML（★★★ 支援有限）。

### ★★★★ VM 程序、cgroup 與資源控制

libvirt 會替每台 VM 建立一個 systemd scope，這代表你可以用標準 Linux 工具做資源控制。

```bash
systemctl status machine.slice --no-pager | head -20
```

```text
● machine.slice - Virtual Machine and Container Slice
     Loaded: loaded (/usr/lib/systemd/system/machine.slice; static)
     Active: active since Tue 2026-09-02 09:22:11 CST; 47min ago
      Tasks: 12
     Memory: 2.3G
        CPU: 4min 51.203s
     CGroup: /machine.slice
             └─machine-qemu\x2d1\x2dweb01.scope
               └─4821 /usr/bin/qemu-system-x86_64 -name guest=web01,...
```

實用推論 ★★★★：

| 想做什麼 | 怎麼做 |
| --- | --- |
| 看某台 VM 吃掉多少主機 CPU | `systemd-cgtop machine.slice` |
| 限制某台 VM 的 CPU 上限 | `virsh schedinfo` 或 XML 的 `<cputune>` |
| 找出「主機 load 很高」的兇手 | `top` 直接看哪個 `qemu-system-x86_64` %CPU 高，再對 `-name guest=` |
| 綁定 vCPU 到特定實體核心 | `virsh vcpupin`（★★★ 效能敏感場景才需要） |

### ★★★★ 主機記憶體：VM 的記憶體到底怎麼算

```bash
virsh dominfo web01
```

```text
Id:             1
Name:           web01
UUID:           7d3f1c92-4a6b-4e81-9f25-3c8a1e7b5d04
OS Type:        hvm
State:          running
CPU(s):         2
CPU time:       412.3s
Max memory:     2097152 KiB
Used memory:    2097152 KiB
Persistent:     yes
Autostart:      disable
Managed save:   no
Security model: apparmor
Security DOI:   0
```

> [!warning] ★★★★ `Used memory` 不是「客體實際用了多少」
> 它是 **libvirt 分配給這台 VM 的記憶體上限**（`currentMemory`）。
> 要知道客體內部實際用量，需要 **balloon 驅動**回報：
> ```bash
> virsh dommemstat web01
> ```
> 沒裝 balloon 驅動時這個指令只會回傳很少的欄位。
> 這跟 PVE 後台記憶體圖表要靠 balloon 才準是同一件事 ★★★★
> （見 [[050-01-03-09-svc-PVE-監控與資源調校]]）。

### ★★★ libvirt 的設定檔在哪

| 路徑 | 內容 | 誰改 |
| --- | --- | --- |
| `/etc/libvirt/qemu/*.xml` ★★★★★ | domain 定義 | **只能用 `virsh edit`** |
| `/etc/libvirt/qemu/networks/*.xml` ★★★★ | 虛擬網路定義 | `virsh net-edit` |
| `/etc/libvirt/storage/*.xml` ★★★★ | 儲存池定義 | `virsh pool-edit` |
| `/etc/libvirt/qemu.conf` ★★★★ | QEMU 驅動全域設定（執行身分、安全模型、log） | **可以直接編輯**，改完重啟 daemon |
| `/etc/libvirt/libvirtd.conf`／`virtqemud.conf` ★★★ | 守護行程本身的設定 | 直接編輯 |
| `/var/lib/libvirt/images/` ★★★★★ | 預設磁碟映像目錄 | |
| `/var/lib/libvirt/qemu/` ★★★ | 執行期狀態、monitor socket、save 檔 | 不要動 |
| `/var/log/libvirt/qemu/<name>.log` ★★★★★ | **排錯第一站** | |
| `~/.config/libvirt/` ★★★★ | **session 模式**的使用者設定（見 02 篇） | |

### ★★★ libvirt 之上還有什麼

純 libvirt 是「單機」的。要做到 PVE／vCenter 那個層級，社群的答案是再疊一層：

| 專案 | 定位 | 對本手冊的意義 |
| --- | --- | --- |
| **Cockpit + cockpit-machines** ★★★★ | 瀏覽器管理單機 libvirt | 不想裝桌面環境時，這是 `virt-manager` 的替代品 |
| **oVirt** ★★★ | Red Hat 系的虛擬化管理平台 | 概念接近 vCenter，但本手冊選 PVE |
| **OpenStack Nova** ★★ | 雲平台的運算元件，底下也是 libvirt | 規模遠超機關單機需求 |
| **Proxmox VE** ★★★★★ | **不用 libvirt，自己實作管理層** | 本手冊的正式環境主線 |
| **Kubernetes + KubeVirt** ★★ | 在 K8s 裡跑 VM | 進階題目 |

---

## 完整實戰範例

### 情境

你接手一台 Ubuntu Server 24.04（已裝好 KVM，安裝步驟見 02 篇），
上面跑著一台叫 `web01` 的 VM。**你要在不改動任何設定的前提下，
把這台機器的虛擬化架構完整摸清楚**，並產出一份可以交接的紀錄。

這一段是**純讀取、零風險**的，可以直接在正式機上做。

### 步驟 1：確認 hypervisor 層可用

```bash
grep -c -E '(vmx|svm)' /proc/cpuinfo && lsmod | grep -E '^kvm' && ls -l /dev/kvm
```

```text
4
kvm_intel             487424  2
kvm                  1409024  1 kvm_intel
crw-rw---- 1 root kvm 10, 232 Sep  2 09:14 /dev/kvm
```

✅ 硬體虛擬化開著、模組載入了、裝置檔在。

### 步驟 2：確認管理層型態

```bash
systemctl list-units --type=service --state=running 'virt*' 'libvirt*' --no-pager
```

```text
  UNIT                  LOAD   ACTIVE SUB     DESCRIPTION
  virtlogd.service      loaded active running Virtual machine log manager
  virtnetworkd.service  loaded active running Virtual network daemon
  virtqemud.service     loaded active running Virtualization qemu daemon
  virtstoraged.service  loaded active running Virtualization storage daemon
```

✅ **模組化架構**。交接文件上要寫清楚：**重啟服務用 `virtqemud`，不是 `libvirtd`** ★★★★。

### 步驟 3：確認連線 URI 與版本

```bash
virsh uri && virsh version --daemon
```

```text
qemu:///system
Compiled against library: libvirt 10.0.0
Using library: libvirt 10.0.0
Using API: QEMU 10.0.0
Running hypervisor: QEMU 8.2.2
Running against daemon: 10.0.0
```

✅ `qemu:///system` —— 是**系統層級**的 VM，不是使用者的 session VM ★★★★★。

### 步驟 4：列出 VM 並看它的定義

```bash
virsh list --all
```

```text
 Id   Name    State
-----------------------
 1    web01   running
 -    db01    shut off
```

```bash
virsh dominfo web01
```

```text
Id:             1
Name:           web01
UUID:           7d3f1c92-4a6b-4e81-9f25-3c8a1e7b5d04
OS Type:        hvm
State:          running
CPU(s):         2
Max memory:     2097152 KiB
Used memory:    2097152 KiB
Persistent:     yes
Autostart:      disable
Managed save:   no
Security model: apparmor
```

> [!warning] ★★★★ 這裡有一個要記進交接文件的坑
> **`Autostart: disable`** —— 主機重開機後這台 VM **不會自動起來**。
> 正式服務 VM 必須 `virsh autostart web01`。
> 這是接手他人環境時最常見的地雷之一，見 [[050-01-04-03-cmd-KVM-virsh指令實務]]。

### 步驟 5：確認 VM 的關鍵硬體設定

```bash
virsh dumpxml web01 | grep -E '<(cpu|memory|vcpu|type arch|driver|target dev|model type|source)'
```

```text
  <memory unit='KiB'>2097152</memory>
    <type arch='x86_64' machine='pc-q35-8.2'>hvm</type>
  <vcpu placement='static'>2</vcpu>
  <cpu mode='host-passthrough' check='none' migratable='on'/>
      <driver name='qemu' type='qcow2' discard='unmap'/>
      <source file='/var/lib/libvirt/images/web01.qcow2'/>
      <target dev='vda' bus='virtio'/>
      <source network='default'/>
      <model type='virtio'/>
```

逐項判讀 ★★★★：

| 發現 | 判讀 |
| --- | --- |
| `machine='pc-q35-8.2'` | 用 Q35 晶片組（現代） |
| `mode='host-passthrough'` | ★★★★ CPU 直通。**效能最好，但換一台實體機可能開不起來**，跟 PVE 的 `cpu: host` 同義 |
| `type='qcow2'` | qcow2 格式，可做快照 |
| `discard='unmap'` | ★★★★ TRIM 有打通，客體刪檔後空間會還回來 |
| `bus='virtio'` | ✅ 磁碟用 VirtIO |
| `<model type='virtio'/>` | ✅ 網卡用 VirtIO |
| `network='default'` | ★★★★ 接在 libvirt 的 **NAT 網路**上，外部**連不進來** |

> [!warning] ★★★★ `network='default'` 是一個服務規劃問題
> `default` 網路是 NAT（`virbr0`，通常是 `192.168.122.0/24`）。
> VM 出得去、外面進不來。**跑對外服務的 VM 應該用橋接**，
> 見 [[050-01-04-04-guide-KVM-儲存池與網路]]。

### 步驟 6：把 VM 對應到主機上的程序

```bash
virsh dumpxml web01 | grep -o "uuid>[^<]*" 
```

```text
uuid>7d3f1c92-4a6b-4e81-9f25-3c8a1e7b5d04
```

```bash
ps -ef | grep '[q]emu-system' | grep -o 'guest=[^,]*'
```

```text
guest=web01
```

```bash
pgrep -a -f 'guest=web01' | cut -c1-80
```

```text
4821 /usr/bin/qemu-system-x86_64 -name guest=web01,debug-threads=on -S -object
```

```bash
ps -o pid,user,%cpu,%mem,rss,etime -p 4821
```

```text
    PID USER      %CPU %MEM   RSS     ELAPSED
   4821 libvirt+  12.4 26.1 2189432    01:12:44
```

✅ 現在你能明確回答「這台 VM 佔了主機多少資源」——
`RSS` 2.1 GB，`%CPU` 12.4%。★★★★

### 步驟 7：確認磁碟與儲存池

```bash
virsh domblklist web01
```

```text
 Target   Source
---------------------------------------------
 vda      /var/lib/libvirt/images/web01.qcow2
```

```bash
sudo qemu-img info /var/lib/libvirt/images/web01.qcow2
```

```text
image: /var/lib/libvirt/images/web01.qcow2
file format: qcow2
virtual size: 32 GiB (34359738368 bytes)
disk size: 8.71 GiB
cluster_size: 65536
Format specific information:
    compat: 1.1
    lazy refcounts: true
    refcount bits: 16
    corrupt: false
```

★★★★ **`virtual size` 32 GiB 但 `disk size` 只有 8.71 GiB** —— 這是 qcow2 的
**精簡配置（thin provisioning）**。交接時要提醒：**主機磁碟空間的規劃要看虛擬大小總和**，
不能只看目前用量，否則哪天所有 VM 一起長大就爆了 ★★★★★。

### 步驟 8：確認網路

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
virsh domifaddr web01
```

```text
 Name       MAC address          Protocol     Address
-------------------------------------------------------------------------------
 vnet0      52:54:00:a3:1f:8c    ipv4         192.168.122.87/24
```

> [!note] ★★★ `virsh domifaddr` 拿不到 IP 時
> 預設它是去問 `virbr0` 的 DHCP 租約表，所以**橋接網路的 VM 查不到**。
> 那時要改用客體代理：
> ```bash
> virsh domifaddr web01 --source agent
> ```
> 前提是客體裡裝了 `qemu-guest-agent` ★★★★。

### 步驟 9：確認 log 位置並看一眼

```bash
sudo ls -l /var/log/libvirt/qemu/
```

```text
-rw------- 1 root root 12843 Sep  2 09:22 web01.log
-rw------- 1 root root  4211 Aug 28 17:03 db01.log
```

```bash
sudo tail -3 /var/log/libvirt/qemu/web01.log
```

```text
2026-09-02 01:22:11.043+0000: Domain id=1 is tainted: custom-argv
char device redirected to /dev/pts/1 (label charserial0)
2026-09-02 01:22:11.512+0000: starting up libvirt version: 10.0.0, qemu version: 8.2.2, kernel: 6.8.0-45-generic
```

### 步驟 10：整理成交接紀錄

把上面的結果整理成一頁：

```text
【主機】ubuntu-kvm01（Ubuntu Server 24.04 LTS, kernel 6.8.0-45）
  CPU        : 4 邏輯核心，VT-x 已啟用
  記憶體      : 8 GB
  虛擬化層    : KVM(kvm_intel) + QEMU 8.2.2 + libvirt 10.0.0
  守護行程    : ★ 模組化（virtqemud / virtnetworkd / virtstoraged）
                重啟服務請用 systemctl restart virtqemud，不是 libvirtd
  連線 URI    : qemu:///system
  映像目錄    : /var/lib/libvirt/images/
  Log         : /var/log/libvirt/qemu/<VM>.log
  網路        : libvirt default NAT（virbr0 = 192.168.122.1/24）

【VM 清單】
  web01  running  2 vCPU / 2 GB / qcow2 32G(實際 8.7G) / VirtIO 磁碟+網卡
         cpu mode = host-passthrough  ← ★ 換實體機可能開不起來
         autostart = disable          ← ★ 待辦：正式服務應開啟
         IP = 192.168.122.87（NAT，外部無法直連）← ★ 待辦：評估改橋接
  db01   shut off （設定同上，未啟動）

【待辦事項】
  1. web01 開啟 autostart（主機重開機後服務才會回來）
  2. 評估 web01 是否改為橋接網路
  3. 確認客體是否安裝 qemu-guest-agent
  4. 磁碟為精簡配置，需監控 /var/lib/libvirt/images 的實際剩餘空間
```

✅ **完成**。你沒有改動任何設定，但已經完整掌握這台機器的架構、風險與待辦。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| `virsh list` 一片空白，但明明建過 VM ★★★★★ | 連到了 `qemu:///session` 而 VM 定義在 `qemu:///system`（或反之） | `virsh uri` 確認；用 `virsh -c qemu:///system list --all`，或設 `export LIBVIRT_DEFAULT_URI=qemu:///system` |
| `error: failed to connect to the hypervisor` + `Failed to connect socket to '/var/run/libvirt/libvirt-sock': No such file or directory` ★★★★ | 守護行程沒起來，或**機器是模組化架構而你在找舊 socket** | `systemctl status virtqemud.socket libvirtd.socket`，啟用存在的那一個 |
| `systemctl restart libvirtd` 回 `Unit libvirtd.service could not be found` ★★★★ | 已是模組化架構，沒有 `libvirtd` 這個單元 | 改用 `systemctl restart virtqemud`（網路／儲存另有各自的 daemon） |
| 改了 `/etc/libvirt/qemu/web01.xml`，重啟 VM 完全沒生效 ★★★★★ | 直接編輯 XML 檔無效，記憶體中的定義會覆蓋回去 | 一律 `virsh edit web01` |
| `virsh edit` 存檔後回 `error: XML error: ...` ★★★★ | XML 語法或標籤錯誤 | 它會問你要不要重新編輯，選 `y` 回去修；改壞了選放棄 |
| `virsh start` 回 `Could not access KVM kernel module: Permission denied` ★★★★★ | QEMU 執行身分沒有 `/dev/kvm` 權限 | 確認 `ls -l /dev/kvm` 是 `root:kvm 660`；確認 `libvirt-qemu` 在 `kvm` 群組；重啟 `virtqemud` |
| `virsh start` 回 `Could not open '/data/vm/web01.qcow2': Permission denied`，但檔案權限看起來沒問題 ★★★★★ | **AppArmor（Ubuntu）／SELinux（RHEL）** 擋住預設目錄以外的路徑 | `dmesg \| grep -i -E 'apparmor\|avc'` 確認；把映像放回 `/var/lib/libvirt/images/`，或替該路徑加規則（RHEL 用 `semanage fcontext` + `restorecon`） |
| VM 極慢，客體裡跑什麼都卡 ★★★★★ | 掉回 TCG 純軟體模擬 | `ps -ef \| grep qemu-system` 看是 `-accel kvm` 還是 `-accel tcg`；`virsh dumpxml` 看是 `<domain type='kvm'>` 還是 `type='qemu'` |
| `<domain type='qemu'>` 而不是 `'kvm'` ★★★★★ | 建立 VM 時 KVM 不可用（BIOS 沒開／巢狀虛擬化沒開），libvirt 自動降級 | 先修好 KVM，再 `virsh edit` 把 `type='qemu'` 改成 `type='kvm'`，完整停機後啟動 |
| 主機重開機後所有 VM 都沒起來 ★★★★★ | 沒設定 autostart | 逐台 `virsh autostart <name>`；`virsh list --autostart` 確認 |
| `virsh dominfo` 的 `Used memory` 跟客體 `free -m` 對不起來 ★★★ | 那是分配上限不是實際用量 | 客體裝 balloon 驅動後用 `virsh dommemstat` |
| `virsh domifaddr` 查不到 IP ★★★★ | 預設查 `virbr0` 的 DHCP 租約，橋接網路查不到 | 加 `--source agent`（客體需裝 `qemu-guest-agent`）或 `--source arp` |
| 在 PVE 主機上裝了 libvirt，網路開始出怪事 ★★★★★ | libvirt 建了 `virbr0` 與自己的 NAT 規則，跟 PVE 的 `vmbr0`／防火牆衝突 | 移除 libvirt：`systemctl disable --now libvirtd virtqemud virtnetworkd`、`apt purge libvirt-daemon-system`，重開機確認 `virbr0` 消失 |
| 在 PVE 上 `virsh list` 看不到任何 VM ★★★★ | PVE 不用 libvirt，VM 不是 libvirt 定義的 | 用 `qm list`，見 [[050-01-03-03-guide-PVE-虛擬機管理]] |
| VM 開機後主控台一片黑，什麼都沒有 ★★★ | 沒有序列主控台裝置，或客體沒把輸出導到序列埠 | XML 要有 `<console type='pty'>`；客體 GRUB 加 `console=ttyS0` |
| `virt-host-validate` 的 IOMMU 顯示 WARN ★★★ | 主機板／BIOS 沒開 VT-d／AMD-Vi | 只影響 PCI 直通，一般用途可忽略 |
| 主機 `load average` 很高但找不到兇手 ★★★★ | 某台 VM 的 vCPU 在燒 CPU | `top` 找 `%CPU` 最高的 `qemu-system-x86_64`，用 `pgrep -a -f guest=` 對出是哪一台 |
| VM 磁碟明明只用 8 GB，主機空間卻一直掉 ★★★★ | qcow2 精簡配置隨使用量長大，且快照也吃空間 | `qemu-img info` 看實際大小；定期 `fstrim`（需 `discard='unmap'`） |

---

## 安全性注意事項

> [!danger] ★★★★★ `kill -9` 一個 QEMU 程序 = 對那台 VM 拔插頭
> 「一台 VM 就是一個程序」很方便，但也很危險。
> 在主機上 `kill -9 <qemu pid>`（或 `pkill qemu`）會**直接切斷 VM 電源**，
> 客體檔案系統可能損毀、資料庫可能不一致。
> **正常關機一律用 `virsh shutdown`**，`virsh destroy` 已經是最後手段
> （見 [[050-01-04-03-cmd-KVM-virsh指令實務]]）。

> [!warning] ★★★★★ `libvirt` 群組實質上等於這台機器的 root
> 加入 `libvirt` 群組的使用者可以：
> - 建立一台 VM 並把**主機的任何磁碟或檔案**掛進去讀寫
> - 設定 PCI 直通、改主機網路
>
> 所以 **`libvirt` 群組不是一個「比較安全的低權限群組」**，
> 它跟 `sudo` 的實際威力接近。機關環境要控管成員名單，
> 帳號管理見 [[020-01-09-cmd-Linux-使用者與群組管理]]。

> [!warning] ★★★★ 不要為了排錯就關掉 AppArmor／SELinux
> libvirt 的 **sVirt** 會替每台 VM 產生獨立的安全標籤，
> 目的是**讓 A 台 VM 的 QEMU 程序無法讀取 B 台 VM 的磁碟檔**。
> 關掉它等於拆掉 VM 之間最後一道隔離。
> 遇到 `Permission denied` 的正確做法是**加規則**，不是關防護。

| 風險 | 說明 | 對策 |
| --- | --- | --- |
| **管理 socket 曝露** ★★★★★ | libvirt 的 TCP 監聽（`libvirtd_tcp` / 16509）預設關閉，開了又沒認證等於送人整台主機 | 遠端管理**一律走 `qemu+ssh://`**，不要開 TCP |
| **`host-passthrough` 的資訊外洩** ★★★ | 客體看得到主機 CPU 的完整型號與指令集 | 多租戶環境改用具名 CPU model |
| **磁碟映像權限** ★★★★ | `/var/lib/libvirt/images/` 裡是完整的客體磁碟，讀得到就等於拿到客體所有資料 | 目錄權限收緊，不要放在共用目錄 |
| **快照與備份含記憶體** ★★★★ | 內部快照可能含客體記憶體，裡面有明文密碼、金鑰 | 快照檔比照磁碟保護 |
| **巢狀虛擬化擴大攻擊面** ★★★ | 客體能再開 VM，虛擬化層漏洞影響範圍變大 | 正式環境不必要就不要開 |
| **`type='qemu'` 誤降級** ★★★ | 效能崩壞常被誤判為「主機不夠力」而盲目加硬體 | 上線前檢查 `-accel kvm` |
| **`/dev/kvm` 權限放寬** ★★★★ | 有人為了省事把它 `chmod 666` | 恢復 `root:kvm 660`，走群組授權 |

---

## 速查表

### 三層對應

| 你想知道的事 | 屬於哪一層 | 指令 |
| --- | --- | --- |
| CPU 支不支援虛擬化 | KVM ★★★★ | `grep -c -E '(vmx\|svm)' /proc/cpuinfo` |
| KVM 模組載入了嗎 | KVM ★★★★ | `lsmod \| grep '^kvm'` |
| `/dev/kvm` 權限對嗎 | KVM ★★★★★ | `ls -l /dev/kvm` |
| 硬體加速真的開著嗎 | QEMU ★★★★★ | `ps -ef \| grep qemu-system \| grep -o '\-accel [a-z]*'` |
| QEMU 版本 | QEMU ★★★ | `qemu-system-x86_64 --version` |
| VM 佔多少主機資源 | QEMU ★★★★ | `top` / `ps -o rss,%cpu -p <pid>` |
| 我有哪些 VM | libvirt ★★★★★ | `virsh list --all` |
| VM 的完整定義 | libvirt ★★★★★ | `virsh dumpxml <name>` |
| 改 VM 設定 | libvirt ★★★★★ | `virsh edit <name>` |
| 整體健康檢查 | 全部 ★★★★ | `sudo virt-host-validate qemu` |

### 關鍵路徑

| 路徑 | 用途 |
| --- | --- |
| `/dev/kvm` ★★★★★ | KVM 裝置檔 |
| `/etc/libvirt/qemu/<name>.xml` ★★★★★ | domain 定義（**只用 `virsh edit`**） |
| `/etc/libvirt/qemu/networks/` ★★★★ | 虛擬網路定義 |
| `/etc/libvirt/storage/` ★★★★ | 儲存池定義 |
| `/etc/libvirt/qemu.conf` ★★★★ | QEMU 驅動設定（可直接編輯） |
| `/var/lib/libvirt/images/` ★★★★★ | 預設磁碟映像目錄 |
| `/var/log/libvirt/qemu/<name>.log` ★★★★★ | **排錯第一站** |
| `~/.config/libvirt/` ★★★★ | session 模式的使用者設定 |
| `/run/libvirt/virtqemud-sock` ★★★ | 模組化架構的管理 socket |
| `/etc/pve/qemu-server/<vmid>.conf` ★★★★★ | **PVE** 的 VM 設定（對照用） |

### 服務單元對照

| 舊（單一 daemon） | 新（模組化） | 管什麼 |
| --- | --- | --- |
| `libvirtd.service` ★★★★★ | `virtqemud.service` ★★★★★ | VM |
| （同上） | `virtnetworkd.service` ★★★★ | 虛擬網路 |
| （同上） | `virtstoraged.service` ★★★★ | 儲存池 |
| （同上） | `virtnodedevd.service` ★★★ | 主機裝置 |
| `virtlogd.service` ★★★ | `virtlogd.service` ★★★ | 客體 log |
| `virtlockd.service` ★★★ | `virtlockd.service` ★★★ | 磁碟鎖 |

### KVM ↔ PVE ↔ VMware 三方對照

| 概念 | KVM/libvirt | Proxmox VE | VMware |
| --- | --- | --- | --- |
| VM 定義 ★★★★★ | domain XML | `/etc/pve/qemu-server/*.conf` | `.vmx` |
| CLI ★★★★★ | `virsh` | `qm` | PowerCLI / `govc` |
| 磁碟格式 ★★★★ | qcow2 / raw | qcow2 / raw / zvol / LVM | vmdk |
| 半虛擬化磁碟 ★★★★★ | virtio-blk / virtio-scsi | VirtIO SCSI | PVSCSI |
| 半虛擬化網卡 ★★★★★ | virtio-net | VirtIO | vmxnet3 |
| 客體代理 ★★★★ | `qemu-guest-agent` | `qemu-guest-agent` | VMware Tools |
| 線上遷移 ★★★★ | `virsh migrate --live` | 後台 Migrate | vMotion |
| 集中管理 ★★★★ | oVirt / OpenStack | PVE 叢集 | vCenter |

---

## 練習題

**練習 1（★★★）**
在你的 KVM 主機上，只用**一行指令**回答：「這台主機上執行中的 VM，
哪一台佔用的實體記憶體最多？」

> [!question]- 參考答案
> ```bash
> ps -eo rss,args --sort=-rss | grep '[q]emu-system' | head -1 | grep -o 'guest=[^,]*'
> ```
> ```text
> guest=web01
> ```
> 或者更完整地印出數值：
> ```bash
> ps -eo rss,args --sort=-rss | grep '[q]emu-system' | \
>   awk '{for(i=1;i<=NF;i++) if($i ~ /^-name$/) print $1/1024 " MB", $(i+1)}'
> ```
> ```text
> 2138 MB guest=web01,debug-threads=on
> 1054 MB guest=db01,debug-threads=on
> ```
> 重點是理解 **VM 的 RSS 就是那個 QEMU 程序的 RSS** ★★★★，
> 所以所有標準 Linux 工具都直接可用。

**練習 2（★★★★）**
不啟動 VM 的前提下，找出 `web01` 這台 VM 的 **CPU model**、**machine type**、
**磁碟匯流排**與**網卡型號**，並判斷這台 VM 能不能安全地搬到另一台 CPU 世代不同的主機。

> [!question]- 參考答案
> ```bash
> virsh dumpxml web01 | grep -E "<cpu |machine=|bus=|<model type"
> ```
> ```text
>     <type arch='x86_64' machine='pc-q35-8.2'>hvm</type>
>   <cpu mode='host-passthrough' check='none' migratable='on'/>
>       <target dev='vda' bus='virtio'/>
>       <model type='virtio'/>
> ```
> 判斷：
> - machine type `pc-q35-8.2` ★★★ —— 目標主機的 QEMU 版本必須支援這個 machine type
> - **`host-passthrough`** ★★★★★ —— **不能安全搬遷**。客體看到的是來源主機 CPU 的
>   完整指令集，換到指令集較少的 CPU 上，客體可能開機就崩潰（用到不存在的指令）。
>   要搬遷必須改成具名 model（如 `<cpu mode='custom'><model>Nehalem</model></cpu>`）
>   或 `host-model`，而且**要完整停機再開機**才生效。
> - VirtIO 磁碟與網卡 ✅ —— 跟遷移無關，兩邊都是 KVM 就沒問題。
>
> 這跟 PVE 的 `cpu: host` vs `x86-64-v2-AES` 是完全同一個議題 ★★★★★
> （見 [[050-01-03-03-guide-PVE-虛擬機管理]]）。

**練習 3（★★★★）**
你的同事宣稱「這台 KVM 主機的 VM 都很慢，一定是硬體不夠力」。
請設計一個**三行以內**的檢查，先排除「根本沒用到硬體加速」這個可能。

> [!question]- 參考答案
> ```bash
> virsh list --name | while read d; do
>   [ -n "$d" ] && echo -n "$d: " && virsh dumpxml "$d" | grep -o "<domain type='[a-z]*'"
> done
> ```
> ```text
> web01: <domain type='kvm'
> db01: <domain type='qemu'
> ```
> **`db01` 是 `type='qemu'`**，代表它用純軟體模擬（TCG），慢 10～50 倍 ★★★★★。
>
> 更直接的是看實際程序：
> ```bash
> ps -ef | grep '[q]emu-system' | grep -o '\-accel [a-z]*'
> ```
> ```text
> -accel kvm
> -accel tcg
> ```
> 成因通常是**建立 VM 的當下 KVM 不可用**（BIOS 沒開、巢狀虛擬化沒開），
> libvirt 就自動降級寫成 `type='qemu'`，之後即使 KVM 修好了，
> **這台 VM 的定義也不會自己改回來**。要 `virsh edit` 手動改成 `kvm`
> 並完整停機再開機。

**練習 4（★★★★）**
用一段話向你的主管解釋：「我們已經有 Proxmox VE 了，為什麼還要學 KVM？」
要求：不能只講「因為 PVE 底層是 KVM」，要給出兩個**具體可驗證的好處**。

> [!question]- 參考答案
> 參考論述：
>
> 「PVE 後台上的每一個選項，底層都是 KVM/QEMU 的一個參數。學了 KVM，
> 我們有兩個具體的能力：
>
> **第一，出事時查得到原因。** PVE 後台只會顯示『VM 啟動失敗』，
> 真正的原因在 QEMU 的 log 裡。知道 VM 就是一個 QEMU 程序、
> 知道 log 在哪、知道 `-accel kvm` 代表什麼，我們就能自己在
> 十分鐘內定位問題，而不是重開機碰運氣或等原廠支援。★★★★
>
> **第二，選項選得對。** CPU type 選 `host` 還是相容等級、
> 磁碟為什麼一定要用 VirtIO、快取模式選錯會怎樣——這些在 PVE 後台
> 只是幾個下拉選單，但選錯的代價是遷移失敗或資料損毀。
> 懂底層才知道每個選項在做什麼。★★★★★
>
> 另外，我們不是每台伺服器都適合裝 PVE。已經有既定用途的單機伺服器
> 要順便開兩台測試 VM 時，裝 `KVM + libvirt` 幾分鐘就好，
> 不必為此重灌整台機器。」

**練習 5（★★★★★）**
在一台**測試機**上，用 `virsh domxml-to-native` 把一台 VM 的定義轉成 QEMU 命令列，
找出下列三項各對應到哪個參數：**machine type**、**加速器**、**磁碟檔路徑**。
然後說明：如果你要把這台 VM 搬到 PVE，這三項各要在 `qm` 裡設什麼。

> [!question]- 參考答案
> ```bash
> virsh domxml-to-native qemu-argv --domain web01 | tr ' ' '\n' | grep -E '^-machine|^-accel|q35|qcow2|filename'
> ```
> ```text
> -machine
> pc-q35-8.2,usb=off,vmport=off,dump-guest-core=off
> -accel
> kvm
> {"driver":"file","filename":"/var/lib/libvirt/images/web01.qcow2","node-name":"libvirt-1-storage"}
> ```
>
> 搬到 PVE 的對應：
>
> | 項目 | QEMU 參數 | PVE 設定 |
> | --- | --- | --- |
> | machine type | `-machine pc-q35-8.2` | `qm set <id> --machine q35` ★★★★ |
> | 加速器 | `-accel kvm` | PVE 預設就用 KVM（`kvm: 1`），不需設定 ★★★ |
> | 磁碟 | `filename=/var/lib/libvirt/images/web01.qcow2` | 先 `qm importdisk <id> web01.qcow2 <storage>`，再 `qm set <id> --scsi0 <storage>:vm-<id>-disk-0` ★★★★★ |
>
> ★★★★ 實務提醒：搬遷前**務必先在來源把 `cpu` 從 `host-passthrough`
> 改成相容等級**，否則到了 PVE 上 CPU 不同會開不起來。
> 完整的 PVE 匯入流程見 [[050-01-03-03-guide-PVE-虛擬機管理]]。

---

## 小測驗

Q1. 用一句話說明 KVM、QEMU、libvirt 三者各自負責什麼。

Q2. 是非題：`systemctl restart libvirtd` 會把主機上執行中的 VM 全部重開。

Q3. 你用 `vim` 改了 `/etc/libvirt/qemu/web01.xml` 裡的記憶體大小，存檔後 `virsh shutdown` 再 `virsh start`。記憶體會變嗎？為什麼？

Q4. 這行指令的輸出是 `-accel tcg`，代表什麼？後果多嚴重？
```bash
ps -ef | grep '[q]emu-system' | grep -o '\-accel [a-z]*'
```

Q5. 選擇題：在一台 Proxmox VE 主機上執行 `virsh list --all`，最可能的結果是什麼？
（A）列出所有 PVE 上的 VM　（B）指令不存在或列出空清單
（C）列出 LXC 容器　（D）連線失敗但會提示要用 `qm`

Q6. 是非題：Proxmox VE 是一種跟 KVM 不同的虛擬化技術。

Q7. 你在 `virsh dumpxml` 看到 `<domain type='qemu'>`。這台 VM 的效能大約會是 `type='kvm'` 的多少？成因通常是什麼？

Q8. 簡答：`virsh dominfo` 顯示 `Used memory: 2097152 KiB`，但客體裡 `free -m` 顯示只用了 400 MB。這兩個數字矛盾嗎？

Q9. 為什麼「加入 `libvirt` 群組」不能被當成一個低風險的授權動作？

Q10. 一台 VM 啟動失敗，`virsh start` 只回了一句簡短的錯誤。你會依序看哪三個地方？

> [!question]- 測驗答案
> **Q1.** **KVM** 是 Linux 核心模組，只做 **CPU 與記憶體虛擬化**（VT-x／AMD-V、EPT），
> 對外只暴露 `/dev/kvm`。**QEMU** 是使用者空間程式，**模擬 CPU 以外的所有虛擬硬體**
> （晶片組、磁碟控制器、網卡、韌體），一台 VM 就是一個 QEMU 程序。
> **libvirt** 是**管理層**，用 domain XML 記住 VM 的定義、提供 `virsh` 與 API、
> 管理儲存池與虛擬網路。
> 口訣：**KVM 讓 CPU 跑得快，QEMU 讓 VM 看起來像一台電腦，libvirt 讓你管得動。** ★★★★★
> （見「觀念說明 → 一句話講完三層」）
>
> **Q2.** **錯。** VM 是**獨立的 `qemu-system-x86_64` 程序**，
> libvirt 只是透過 monitor socket 跟它們對話。重啟守護行程後 libvirt 會重新接管，
> **執行中的 VM 不受影響**。這跟 VMware Workstation「關掉主程式 VM 就停」完全不同。
> 另外要注意：模組化架構的機器**根本沒有 `libvirtd.service`**，
> 要重啟的是 `virtqemud.service`。★★★★
> （見「觀念說明 → socket 啟動」）
>
> **Q3.** **不會變，而且你的修改很可能已經消失了。** 執行中的守護行程在記憶體裡
> 快取了 domain 定義，你手改檔案它不知道；下一次任何 libvirt 操作寫回設定時，
> 就會用記憶體裡的版本覆蓋掉你的修改。檔案第一行本身就寫著這是自動產生的檔案。
> **正確做法只有 `virsh edit web01`**，它會驗證語法並同步記憶體狀態。
> 而且記憶體大小屬於硬體層級變更，改完必須 **`shutdown` 再 `start`**，
> `reboot` 無效。★★★★★
> （見「觀念說明 → 絕對不要直接 vim」）
>
> **Q4.** 代表這台 VM **沒有使用硬體加速**，QEMU 用 **TCG 純軟體翻譯**在模擬 CPU，
> 效能大約是硬體加速的 **1/10 到 1/50**。後果非常嚴重：客體開機要好幾分鐘、
> 跑任何工作都卡到不能用。常見成因是建立 VM 時 KVM 不可用
> （BIOS 沒開 VT-x、或這台主機本身是 VM 而巢狀虛擬化沒開），
> libvirt 就自動把定義寫成 `<domain type='qemu'>`。
> **修好 KVM 之後定義不會自己改回來**，要手動 `virsh edit`。★★★★★
> （見「常見錯誤與排錯」與「練習 3」）
>
> **Q5.** **（B）**。PVE **不使用 libvirt**——它有自己的管理層（`pvedaemon` 系列）
> 與設定檔（`/etc/pve/qemu-server/<vmid>.conf`），VM 不是由 libvirt 定義的。
> 預設 PVE 上根本沒裝 `virsh`（指令不存在）；就算你自己裝了，
> 也只會看到一份空清單，因為那些 VM 對 libvirt 而言不存在。
> 正確的指令是 **`qm list`**。★★★★★
> （見「觀念說明 → PVE 與 KVM 的關係」）
>
> **Q6.** **錯，而且錯得很關鍵。** PVE 的虛擬機引擎**就是 KVM + QEMU**，
> 在 PVE 主機上 `lsmod | grep kvm` 一樣看得到模組，
> VM 一樣是 QEMU 程序（`/usr/bin/kvm`，即 `qemu-system-x86_64` 的別名）。
> PVE 換掉的是**管理層**：不用 libvirt 與 domain XML，
> 改用自己的 `qm`、`pvesm`、`pvecm` 與 pmxcfs 設定檔系統。
> 一句話：**同一顆引擎，不同的駕駛艙。** ★★★★★
> （見「觀念說明 → PVE 底層就是 KVM + QEMU」）
>
> **Q7.** 大約 **1/10 到 1/50**（工作負載愈依賴 CPU 差距愈大）。
> 成因是**建立 VM 的當下 KVM 不可用**，libvirt 自動降級成純模擬。
> 排查順序：`grep -c -E '(vmx|svm)' /proc/cpuinfo` → `lsmod | grep kvm`
> → `ls -l /dev/kvm` → 都正常的話就是這台 VM 的定義卡在舊狀態，
> `virsh edit` 改 `type='kvm'` 後**完整停機再開機**。★★★★★
> （見「常見錯誤與排錯」）
>
> **Q8.** **不矛盾。** `virsh dominfo` 的 `Used memory` 其實是
> **libvirt 分配給這台 VM 的記憶體上限**（`currentMemory`），
> 不是客體實際使用量。要看客體內部的真實用量，
> 需要 **balloon 驅動**回報，用 `virsh dommemstat <name>`。
> 這跟 PVE 後台的記憶體圖表要靠 balloon 才準是同一件事。★★★★
> （見「進階應用 → 主機記憶體」）
>
> **Q9.** 因為 `libvirt` 群組成員可以**建立一台 VM，並把主機上的任何磁碟或檔案
> 掛進那台 VM 裡讀寫**，也可以設定 PCI 直通、改動主機網路。
> 換句話說，它的實際威力**接近 `sudo`**，只是路徑比較迂迴。
> 把它當成「給開發者的低權限群組」是嚴重的授權誤判，
> 機關環境必須比照特權帳號控管成員名單。★★★★★
> （見「安全性注意事項」）
>
> **Q10.** 依序：
> 1. **`virsh start` 的直接輸出** —— XML 語法錯誤、資源被佔用會在這裡講清楚 ★★★
> 2. **`/var/log/libvirt/qemu/<VM名稱>.log`** —— ★★★★★ QEMU 程序本身的輸出，
>    磁碟開不了、KVM 存取失敗、客體崩潰，答案九成在最後 30 行
> 3. **`journalctl -u virtqemud -n 50`**（或 `libvirtd`）與
>    **`dmesg | grep -i -E 'apparmor|avc'`** —— 守護行程的問題與
>    AppArmor／SELinux 的阻擋紀錄
>
> 記住第 2 個路徑就解決大部分問題。★★★★★
> （見「觀念說明 → 一台 VM 從開機到跑起來」）

---

## 延伸閱讀

**本章其他篇**

- [[050-01-04-02-svc-KVM-安裝與virt-manager]] — 把本篇的架構真的裝起來，用 GUI 開出第一台 VM
- [[050-01-04-03-cmd-KVM-virsh指令實務]] — 用 `virsh` 把 02 篇的操作全部重做一次
- [[050-01-04-04-guide-KVM-儲存池與網路]] — storage pool、qcow2 與 raw、NAT 與橋接
- [[050-01-04-05-guide-KVM-自動化與範本]] — `virt-install`、cloud-init、腳本量產 VM

**虛擬化基礎**

- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] — VT-x／EPT／VirtIO 的原理層說明
- [[050-01-01-01-guide-虛擬化-虛擬化概念與選型]] — Type-1／Type-2 的完整討論
- [[050-01-01-03-ref-虛擬化-五平台橫向對照]] — 五個平台一頁看完
- [[050-01-01-04-guide-虛擬化-機關選型與授權成本]] — 授權與採購角度

**PVE（本篇大量對照的對象）**

- [[050-01-03-03-guide-PVE-虛擬機管理]] — `qm`、VirtIO、CPU type、cloud-init
- [[050-01-03-01-svc-PVE-安裝與初始設定]] — PVE 的安裝與 KVM 驗證
- [[050-01-03-02-guide-PVE-儲存設定]] — PVE 的儲存模型（對照 storage pool）
- [[050-01-03-09-svc-PVE-監控與資源調校]] — 超額配置、balloon 與資源監控

**VMware（本篇對照的另一邊）**

- [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] — Workstation 的 VM 建立
- [[050-01-05-02-guide-其他虛擬化-VMwareESXi與採購考量]] — ESXi 的定位

**Linux 基礎**

- [[020-01-26-guide-Linux-核心模組與sysctl調校]] — `lsmod`、`modprobe`、模組參數
- [[020-01-10-cmd-Linux-程序管理與訊號]] — `ps`、`kill`、訊號
- [[020-01-17-cmd-Linux-systemd服務管理]] — service 與 socket 單元
- [[020-01-19-guide-Linux-日誌系統]] — `journalctl` 與 log 輪替
