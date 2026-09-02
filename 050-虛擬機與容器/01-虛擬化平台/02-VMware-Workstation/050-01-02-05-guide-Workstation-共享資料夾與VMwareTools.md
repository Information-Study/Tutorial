---
title: "共享資料夾與VMwareTools"
desc: "VMware Tools 與 open-vm-tools 的差異、Windows／Linux 兩邊的安裝、共享資料夾與 /mnt/hgfs 自動掛載、剪貼簿拖放，以及時間同步的坑"
aliases: [VMware Tools, open-vm-tools, vmhgfs-fuse, 共享資料夾, Shared Folders, vmware-toolbox-cmd]
tags: [群組/虛擬機與容器, 主題/虛擬化, 主題/VMware]
category: 虛擬機與容器
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]]"]
updated: 2026-09-02
---

# 共享資料夾與VMwareTools

> [!warning] 未實機驗證
> 本篇的選單路徑與畫面文字**以 VMware Workstation 17 為例**，其他版本的選單位置與
> 按鈕文字可能不同（尤其 `VM → Settings → Options` 這一層在不同版本有過調整）。
> Guest 端的套件名稱與服務名稱則依發行版版本而異，**動手前先用本篇的驗證指令確認實際狀態**，
> 不要照抄指令就當成功。

> [!abstract] 這篇你會學到
> - VMware Tools 與 open-vm-tools 到底差在哪、什麼時候該用哪一個 ★★★★
> - Tools 沒裝好會出現哪些症狀——一張對照表讓你從症狀反推原因 ★★★★
> - Windows Guest 與 Linux Guest 兩邊的完整安裝步驟與驗證方式 ★★★
> - 共享資料夾的設定、Windows 端的 `\\vmware-host\` 與 Linux 端的 `/mnt/hgfs` ★★★★
> - ★★★★★ **`/mnt/hgfs` 開機自動掛載**——這是新手最常卡住的地方，因為現代的
>   open-vm-tools 走 FUSE，`/mnt/hgfs` **不會自己出現**
> - 剪貼簿、拖放、自動調整解析度的開關位置與 `.vmx` 參數 ★★★
> - ★★★★★ **時間同步的坑**：主機睡眠醒來後 VM 時間跑掉、Tools 授時與 chrony 打架
> - `vmware-toolbox-cmd` 這支被低估的診斷工具怎麼用 ★★★

## 前置知識

- [[050-01-02-01-svc-Workstation-安裝與授權]]
- [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]]
- [[020-01-17-cmd-Linux-systemd服務管理]]
- [[020-01-28-cmd-Linux-時間同步NTP與chrony]]

---

## 觀念說明

### ★★★★ 什麼是 VMware Tools

一台剛裝好作業系統的虛擬機，其實處在「半殘」狀態：滑鼠移出視窗要按 `Ctrl+Alt` 才放得出來、
畫面解析度固定在某個奇怪的值、關機要進 Guest 裡自己下指令、主機看不到 VM 的 IP。

原因是 **Guest 作業系統並不知道自己跑在虛擬機裡**，它用的是通用驅動程式，
而 Hypervisor 提供的那些「虛擬硬體」需要專屬驅動才能發揮效能與功能。

**VMware Tools 就是補上這一層的東西**——它不是一個程式，而是一整組
「Guest 內的驅動程式 ＋ 一支常駐服務 ＋ 一組公用程式」。★★★★

| 元件 | 類型 | 作用 | 沒有它會怎樣 |
| --- | --- | --- | --- |
| `vmtoolsd` ★★★★ | 常駐服務 | 與 Host 的 Hypervisor 通道（backdoor／VMCI）溝通，執行心跳、電源事件、資訊回報 | Host 看不到 VM 的 IP，「關機／重新啟動 Guest」選單無效 |
| SVGA 顯示驅動 ★★★★ | 驅動 | 加速 2D／3D 繪圖、支援任意解析度 | 畫面卡頓、解析度無法隨視窗調整 |
| `vmxnet3` ★★★★ | 網路驅動 | 高效能半虛擬化網卡 | 只能用 e1000e 模擬網卡，吞吐低、CPU 佔用高 |
| `vmw_pvscsi` ★★★ | 儲存驅動 | 半虛擬化 SCSI 控制器 | 只能用 LSI Logic 模擬控制器，I/O 較慢 |
| `vmw_balloon` ★★★ | 記憶體驅動 | 記憶體氣球，讓 Host 回收 Guest 閒置記憶體 | Host 無法動態回收，記憶體壓力大時整台卡 |
| `vmw_vmci` / `vsock` ★★★ | 通訊驅動 | Host 與 Guest 之間的高速通道，HGFS 與多項功能都靠它 | 共享資料夾、部分 Tools 功能不可用 |
| **HGFS**（Host-Guest File System）★★★★ | 檔案系統 | 共享資料夾的實作 | `/mnt/hgfs` 沒東西、Windows 看不到 `\\vmware-host` |
| 滑鼠整合驅動 ★★★ | 驅動 | 滑鼠自由進出 VM 視窗，不必按 `Ctrl+Alt` | 每次都要按 `Ctrl+Alt` 釋放滑鼠 |
| 剪貼簿／拖放代理 ★★★ | 服務元件 | Host 與 Guest 互相複製貼上、拖放檔案 | 只能用共享資料夾或 SSH 搬檔 |
| 時間同步元件 ★★★★★ | 服務元件 | 從 Host 取得時間校正 Guest 時鐘 | 睡眠／快照還原後時間大跑偏（但**開著也有坑**，見後面） |
| 靜默快照（quiesce）腳本 ★★★★ | 腳本 | 快照前 flush 檔案系統、跑 pre-freeze/post-thaw | 快照是「當機一致」而非「檔案系統一致」 |

> [!note] Tools 是「Guest 端」的東西 ★★★
> 它裝在虛擬機**裡面**，不是裝在你的桌機上。所以每建一台新 VM 就要裝一次，
> 而且**每一種 Guest OS 的裝法都不一樣**。這也是為什麼建範本機（Template）時
> 應該先把 Tools 裝好再封裝——見 [[050-01-02-03-guide-Workstation-快照與複製]]。

### ★★★★★ VMware Tools 與 open-vm-tools 的差別

這是本篇最需要先講清楚的一件事，因為選錯會踩雷。

| | **VMware Tools**（原廠版） | **open-vm-tools**（開源版） |
| --- | --- | --- |
| 誰維護 ★★★★ | VMware／Broadcom | 開源社群，**由各 Linux 發行版打包進官方套件庫** |
| 授權 | 原廠授權 | 開源授權 |
| 取得方式 ★★★★ | Workstation 選單「Install VMware Tools」掛載 ISO，手動執行安裝程式 | `apt install` / `dnf install`，**一行指令** |
| 更新方式 ★★★★★ | 手動重跑安裝程式；Workstation 升級後常提示「Tools 過舊」 | **跟著系統 `apt upgrade` 一起更新**，不必額外管 |
| 核心模組相容性 ★★★★★ | 核心升級後可能編不過、需重跑安裝程式 | 模組已進入 Linux 主線核心，**跟著核心一起更新，不會編不過** |
| Linux Guest 支援 ★★★★★ | 可用，但**原廠已明確建議改用 open-vm-tools** | **官方推薦做法** |
| Windows Guest 支援 ★★★★★ | **唯一選擇** | ❌ 不提供 Windows 版 |
| 舊版／冷門系統 ★★★ | 支援較廣（老舊核心、非主流發行版） | 只涵蓋發行版有打包的版本 |
| 共享資料夾實作 ★★★★ | 舊版帶 `vmhgfs` 核心模組 | 走 **`vmhgfs-fuse`**（使用者空間 FUSE） |

**結論（背下來就好）★★★★★**：

```text
Windows Guest   →  裝原廠 VMware Tools（沒有別的選擇）
Linux Guest     →  裝發行版套件庫的 open-vm-tools（不要去掛 ISO 裝原廠版）
```

> [!danger] ★★★★★ 不要在現代 Linux 上裝原廠 VMware Tools
> 常見的災難流程是：使用者照著十年前的網路文章，掛 ISO、解壓 `VMwareTools-*.tar.gz`、
> 跑 `vmware-install.pl`。結果：
> 1. 它會把自己的 `vmhgfs`、`vmxnet` 模組硬塞進系統
> 2. 下一次 `apt upgrade` 換了核心，模組編不過，**開機後網路卡不見**
> 3. 想移除卻找不到乾淨的移除方式（要跑 `vmware-uninstall-tools.pl`，而且常有殘留）
>
> **正確做法就是 `apt install open-vm-tools`。** 如果機器上已經誤裝原廠版，
> 先跑 `sudo /usr/bin/vmware-uninstall-tools.pl` 移除乾淨，再裝 open-vm-tools。

> [!tip] 兩個套件不要搞混 ★★★★
> - `open-vm-tools`：**伺服器用**。含 `vmtoolsd`、`vmhgfs-fuse`、`vmware-toolbox-cmd`。
>   無桌面的 Ubuntu Server 裝這個就夠。
> - `open-vm-tools-desktop`：**有桌面才裝**。額外提供剪貼簿共享、拖放、
>   自動調整解析度所需的元件（依賴 X11／Wayland 環境）。
>
> 在 Ubuntu Server 上裝 `-desktop` 會拖進一堆 X11 相依套件，沒必要。

### ★★★★ Tools 沒裝好的症狀對照表

這張表是本篇最實用的部分——**從症狀反推原因**，不用一項一項猜。

| 症狀 | 最可能的原因 | 先確認什麼 |
| --- | --- | --- |
| 滑鼠移出 VM 視窗要按 `Ctrl+Alt` ★★★ | Tools 完全沒裝，或滑鼠整合驅動沒載入 | `vmtoolsd` 有沒有在跑 |
| 視窗放大／全螢幕後畫面沒跟著變大，四周留黑邊 ★★★★ | 顯示驅動沒裝，或 `open-vm-tools-desktop` 沒裝 | Guest 是不是有桌面環境；`-desktop` 套件是否安裝 |
| 解析度選單只有 800×600、1024×768 幾個固定值 ★★★ | 同上 | 同上 |
| Workstation 主畫面看不到 VM 的 IP 位址 ★★★★ | `vmtoolsd` 沒在跑（Host 靠它回報） | `systemctl status open-vm-tools` |
| 選單的「Shut Down Guest」「Restart Guest」是灰色的 ★★★★ | 同上，電源事件要靠 Tools 傳達 | 同上 |
| Host 與 Guest 之間無法複製貼上文字 ★★★ | 沒裝 `-desktop`，或 Guest Isolation 關閉了剪貼簿 | VM 設定 → Options → Guest Isolation |
| 拖放檔案進 VM 沒反應 ★★★ | 同上 | 同上 |
| `/mnt/hgfs` 是空的或根本不存在 ★★★★★ | **共享資料夾沒啟用，或沒掛載 `vmhgfs-fuse`** | 見〈共享資料夾〉整節 |
| Windows Guest 找不到 `\\vmware-host\Shared Folders` ★★★★ | 共享資料夾設定為「Disabled」 | VM 設定 → Options → Shared Folders |
| 網路吞吐量明顯偏低、大量傳輸時 CPU 飆高 ★★★ | 網卡驅動退回 e1000e 模擬模式 | `lspci` 看網卡型號、`ethtool -i` 看驅動 |
| 快照還原或主機睡眠醒來後**時間差了好幾小時** ★★★★★ | 時間同步沒設好 | 見〈時間同步的坑〉整節 |
| VM 關機後 Host 記憶體沒有立刻釋放，開機時 Host 很卡 ★★ | 氣球驅動未載入（影響有限） | `lsmod \| grep vmw_balloon` |
| Workstation 一直跳「VMware Tools 已過期」提示 ★★★ | 裝的是原廠版且版本落後 | Linux 就改用 open-vm-tools，Windows 重跑安裝程式 |

### ★★★★ HGFS：共享資料夾到底怎麼運作

共享資料夾（Shared Folders）的完整名稱是 **HGFS（Host-Guest File System）**，
它讓 Host 上的一個目錄「出現」在 Guest 裡。

```text
  Host（你的桌機）                     Guest（虛擬機）
  ┌──────────────────────┐            ┌──────────────────────────┐
  │ D:\vm-share\          │            │ Windows:                 │
  │   ├ setup.iso         │  ← HGFS →  │   \\vmware-host\Shared…  │
  │   ├ nginx.conf        │  （VMCI）  │   或對應成 Z:            │
  │   └ backup/           │            │ Linux:                   │
  └──────────────────────┘            │   /mnt/hgfs/<共享名稱>   │
                                       └──────────────────────────┘
```

三個關鍵事實，先記住可以少踩很多坑：

1. **HGFS 不是網路磁碟。★★★★** 它不走 TCP/IP，走的是 Host 與 Guest 之間的
   VMCI 通道，所以就算 VM 的網路完全不通，共享資料夾照樣能用。
   這在「網路設錯了要進去救」的時候特別有用。
2. **它不是 POSIX 完整的檔案系統。★★★★★** 不支援硬連結、不支援 UNIX 權限位元
   （所有檔案看起來都是同一個 uid/gid）、`chmod` 大多無效、
   **不適合放需要精確權限的東西**（例如 `~/.ssh` 或 Git 工作目錄）。
3. **現代 Linux 上它是 FUSE 掛載，不會自動出現。★★★★★**
   舊版有 `vmhgfs` 核心模組會自動把 `/mnt/hgfs` 掛好；
   open-vm-tools 改用使用者空間的 `vmhgfs-fuse`，**你必須自己掛載或寫進 `/etc/fstab`**。
   這就是「我在 Workstation 裡設好共享資料夾了，可是 Guest 裡 `/mnt/hgfs` 是空的」
   這個經典問題的答案。

> [!warning] ★★★★ 共享資料夾不適合當「部署路徑」
> 拿 HGFS 直接放 Web 根目錄或資料庫檔案，會遇到權限錯亂、`inotify` 失效、
> 效能低落、檔案鎖行為異常等一連串問題。
> **共享資料夾的正確定位是「搬檔案用的臨時通道」**，
> 真正要跑的東西請複製進 Guest 的本機檔案系統。

---

## 安裝或基礎操作

### ★★★★ Linux Guest：安裝 open-vm-tools

以 Ubuntu Server 為主線。

#### 步驟 1：確認自己真的在 VMware 虛擬機裡

```bash
sudo dmidecode -s system-product-name
```

```text
VMware Virtual Platform
```

或用 systemd 的偵測：

```bash
systemd-detect-virt
```

```text
vmware
```

> [!tip] `systemd-detect-virt` 是寫腳本時的好朋友 ★★★
> 它在實體機上回傳 `none` 且離開碼為 1，可以用來寫「只有虛擬機才做」的自動化：
>
> ```bash
> if systemd-detect-virt --quiet; then
>     echo "這是虛擬機，安裝 open-vm-tools"
> fi
> ```

#### 步驟 2：安裝

```bash
sudo apt update
sudo apt install -y open-vm-tools
```

有桌面環境（Ubuntu Desktop）才另外加：

```bash
sudo apt install -y open-vm-tools-desktop
```

```text
Reading package lists... Done
Building dependency tree... Done
The following NEW packages will be installed:
  open-vm-tools
0 upgraded, 1 newly installed, 0 to remove and 0 not upgraded.
...
Created symlink /etc/systemd/system/multi-user.target.wants/open-vm-tools.service → /lib/systemd/system/open-vm-tools.service.
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> sudo dnf install -y open-vm-tools
> # 有桌面才裝：
> sudo dnf install -y open-vm-tools-desktop
> sudo systemctl enable --now vmtoolsd.service
> ```
>
> **服務名稱不一樣，這是最容易踩的差異 ★★★★**：
>
> | | Ubuntu / Debian | Rocky / AlmaLinux |
> | --- | --- | --- |
> | 服務名 | `open-vm-tools.service` | `vmtoolsd.service` |
> | 查狀態 | `systemctl status open-vm-tools` | `systemctl status vmtoolsd` |
> | 桌面套件 | `open-vm-tools-desktop` | `open-vm-tools-desktop` |
>
> RHEL 系的 minimal 安裝在偵測到 VMware 平台時，**安裝程式常已自動裝好 open-vm-tools**，
> 先用 `rpm -q open-vm-tools` 確認再裝。

#### 步驟 3：確認服務有跑起來

```bash
systemctl status open-vm-tools --no-pager
```

```text
● open-vm-tools.service - Service for virtual machines hosted on VMware
     Loaded: loaded (/lib/systemd/system/open-vm-tools.service; enabled; vendor preset: enabled)
     Active: active (running) since Wed 2026-09-02 09:14:03 CST; 12s ago
   Main PID: 1183 (vmtoolsd)
      Tasks: 3 (limit: 4613)
     CGroup: /system.slice/open-vm-tools.service
             └─1183 /usr/bin/vmtoolsd
```

`Active: active (running)` 就對了。★★★★

#### 步驟 4：確認版本與核心模組

```bash
vmware-toolbox-cmd -v
```

```text
12.3.5.46049 (build-22544099)
```

```bash
lsmod | grep -E 'vmw_|vmxnet|vsock'
```

```text
vmw_vsock_vmci_transport    32768  1
vsock                       49152  2 vmw_vsock_vmci_transport
vmw_balloon                 24576  0
vmxnet3                     69632  0
vmw_vmci                    90112  2 vmw_vsock_vmci_transport,vmw_balloon
vmw_pvscsi                  24576  2
```

看到 `vmw_vmci` 就代表 Host-Guest 通道可用，共享資料夾才有機會運作。★★★★

> [!note] 沒有 `vmhgfs` 是正常的 ★★★★★
> 很多舊教學會叫你確認 `lsmod | grep vmhgfs`。**現代系統上這個模組不存在**，
> 因為 open-vm-tools 改用 FUSE。看不到它不是錯誤，不要因此去裝原廠 Tools。

#### 步驟 5：驗證 Host 端看得到 VM 資訊 ★★★

回到 Workstation 主視窗，選中這台 VM，畫面下方或右側應該出現
`IP address: 192.168.x.x`。**看得到 IP 就代表 `vmtoolsd` 與 Host 的通道已通。**

### ★★★★ Windows Guest：安裝 VMware Tools

Windows Guest **只能裝原廠版**，沒有 open-vm-tools 可選。

#### 步驟 1：掛載 Tools ISO

在 Workstation 選單：**VM → Install VMware Tools…**（以 Workstation 17 為例）

如果 VM 的光碟機正掛著安裝 ISO，這個選單會是灰色的——先到
`VM → Settings → CD/DVD` 把它設回 `Use physical drive` 或退出光碟再試。★★★

#### 步驟 2：在 Guest 裡執行安裝程式

Windows Guest 裡會多出一台光碟機。若沒有自動播放，開檔案總管進去手動執行：

```text
D:\setup64.exe        （64 位元 Windows）
D:\setup.exe          （32 位元 Windows）
```

安裝精靈選 **Typical（典型）** 即可；只有在需要把 VM 搬去 ESXi 時才選 Complete。

#### 步驟 3：重新開機

**一定要重開機**，顯示驅動與網卡驅動要重開才生效。★★★

#### 步驟 4：驗證

```powershell
Get-Service VMTools
```

```text
Status   Name               DisplayName
------   ----               -----------
Running  VMTools            VMware Tools
```

```powershell
& 'C:\Program Files\VMware\VMware Tools\VMwareToolboxCmd.exe' -v
```

```text
12.3.5.46049 (build-22544099)
```

系統匣（右下角）也會出現 VMware Tools 的圖示。★★

> [!tip] 靜默安裝（做範本機時很好用）★★★
> ```powershell
> D:\setup64.exe /S /v "/qn REBOOT=R"
> ```
> `/S` 是安裝程式本身靜默、`/v "/qn"` 傳給底層的 MSI、`REBOOT=R` 表示不自動重開機。
> 建 Windows 範本機時搭配自動化腳本使用，見
> [[050-01-02-03-guide-Workstation-快照與複製]]。

### ★★★★★ 共享資料夾：Host 端設定

不管 Guest 是什麼作業系統，**Host 端的設定步驟都一樣**。

#### 步驟 1：在 Host 上準備一個目錄

```powershell
# Windows Host
New-Item -ItemType Directory -Path 'D:\vm-share' -Force
```

```bash
# Linux Host
mkdir -p ~/vm-share
```

> [!warning] ★★★★ 不要直接分享整顆磁碟或使用者家目錄
> 分享 `C:\` 或 `/home/你` 等於把整台主機的檔案攤在 Guest 面前。
> 一旦 Guest 中毒或被入侵，Host 的資料就跟著遭殃。
> **只分享一個專用的中繼目錄。**

#### 步驟 2：VM 必須先關機或至少先設定好

`VM → Settings → Options 分頁 → Shared Folders`（以 Workstation 17 為例）

| 選項 | 意義 | 建議 |
| --- | --- | --- |
| **Disabled** | 完全關閉 | 分析可疑樣本、跑不信任的軟體時選這個 ★★★★ |
| **Always enabled** | 永遠開啟 | 日常實驗機用這個 ★★★ |
| **Enabled until next power off or suspend** | 只在這次開機期間有效 | 臨時搬一次檔案時用 ★★ |

#### 步驟 3：按 `Add…` 新增一個共享

精靈會問三件事：

| 欄位 | 說明 | 範例 |
| --- | --- | --- |
| **Host path** ★★★ | Host 上的實際路徑 | `D:\vm-share` |
| **Name** ★★★★ | Guest 裡看到的名稱 | `share`（**用純英文小寫，不要用中文或空白**） |
| **Enable this share** | 這一條是否生效 | 勾選 |
| **Read-only** ★★★★ | Guest 只能讀不能寫 | 放安裝檔的共享建議勾起來 |

> [!danger] ★★★★★ 共享名稱不要用中文或空白
> Windows Guest 還算能忍，但 Linux Guest 掛載後路徑會變成
> `/mnt/hgfs/我的 資料夾`，寫進 `/etc/fstab` 或腳本時各種跳脫問題接踵而至。
> **一律用 `share`、`iso`、`backup` 這種純英文小寫名稱。**

#### 步驟 4：Windows Guest 的額外選項 ★★★

精靈或設定畫面上有一個 **`Map as a network drive in Windows guests`**。
勾了之後 Guest 裡會出現 `Z:` 磁碟機；不勾則要自己走
`\\vmware-host\Shared Folders\<Name>`。

### ★★★★ 共享資料夾：Windows Guest 端

設好之後直接在檔案總管的網址列輸入：

```text
\\vmware-host\Shared Folders\share
```

要自己對應成磁碟機：

```powershell
net use Z: "\\vmware-host\Shared Folders\share" /persistent:yes
```

```text
命令已順利完成。
```

驗證：

```powershell
Get-ChildItem Z:\
```

移除對應：

```powershell
net use Z: /delete
```

> [!warning] ★★★ 找不到 `\\vmware-host` 的兩個原因
> 1. **共享資料夾設定是 Disabled**——回 Host 端設定畫面看
> 2. **VMware Tools 沒裝或服務沒跑**——`Get-Service VMTools` 確認
>
> 這跟 Windows 的網路芳鄰、SMB 設定**完全無關**，不要往那邊查。

### ★★★★★ 共享資料夾：Linux Guest 端與 `/mnt/hgfs`

這是全篇最容易卡住的地方，慢慢來。

#### 步驟 1：確認 Host 端的共享有傳進來

```bash
vmware-hgfsclient
```

```text
share
iso
```

**這一步是分水嶺 ★★★★★**：

- **有列出名稱** → Host 端設定正確，問題只在 Guest 沒掛載，往下做
- **沒有輸出** → Host 端沒設好（Disabled，或根本沒 Add），回 Workstation 設定
- **`command not found`** → open-vm-tools 沒裝

#### 步驟 2：建立掛載點

```bash
sudo mkdir -p /mnt/hgfs
```

#### 步驟 3：手動掛載一次（先確認能不能用）

```bash
sudo /usr/bin/vmhgfs-fuse .host:/ /mnt/hgfs -o subtype=vmhgfs-fuse,allow_other
```

沒有輸出就是成功。驗證：

```bash
ls -l /mnt/hgfs/
```

```text
total 4
drwxrwxr-x 1 root root 4096 Sep  2 09:20 iso
drwxrwxr-x 1 root root 4096 Sep  2 09:20 share
```

```bash
df -hT | grep hgfs
```

```text
vmhgfs-fuse    fuse.vmhgfs-fuse  477G  231G  247G  49% /mnt/hgfs
```

> [!note] `.host:/` 是什麼 ★★★
> 這是 HGFS 的固定「來源位址」，代表「Host 上所有已啟用的共享」。
> 掛在 `/mnt/hgfs` 之後，**每個共享會變成底下的一個子目錄**。
> 也可以只掛單一共享：`vmhgfs-fuse .host:/share /mnt/share`。

> [!warning] `allow_other` 是什麼、為什麼幾乎一定要加 ★★★★
> FUSE 預設只有**掛載者本人**看得到掛載內容。用 `sudo` 掛就代表只有 root 看得到，
> 一般使用者 `ls /mnt/hgfs` 會得到 `Permission denied`。
> 加上 `allow_other` 才開放給其他使用者。
>
> 某些系統需要先在 `/etc/fuse.conf` 裡取消註解 `user_allow_other` 這一行，
> 否則掛載會失敗並顯示 `option allow_other only allowed if 'user_allow_other' is set in /etc/fuse.conf`。

#### 步驟 4：★★★★★ 設定開機自動掛載

手動掛載重開機就沒了。要永久生效，寫進 `/etc/fstab`：

```bash
sudo cp /etc/fstab /etc/fstab.bak-$(date +%F)
echo '.host:/  /mnt/hgfs  fuse.vmhgfs-fuse  allow_other,defaults,nofail  0  0' | sudo tee -a /etc/fstab
```

各欄位意義：

| 欄位 | 值 | 說明 |
| --- | --- | --- |
| 裝置 | `.host:/` | HGFS 的固定來源 ★★★ |
| 掛載點 | `/mnt/hgfs` | 要先存在 ★★★ |
| 型別 | `fuse.vmhgfs-fuse` | **必須是這個寫法**，不是 `vmhgfs` ★★★★★ |
| 選項 | `allow_other,defaults,nofail` | `nofail` 是關鍵，見下方警告 ★★★★★ |
| dump | `0` | 不備份 |
| pass | `0` | **不做 fsck，一定要 0** ★★★★ |

> [!danger] ★★★★★ `nofail` 沒加，開機會卡在救援模式
> 如果哪天你把共享資料夾設成 Disabled、或把這台 VM 複製到沒有該共享的環境，
> 掛載會失敗。**沒有 `nofail` 的話 systemd 會判定必要掛載點失敗，
> 把開機流程丟進 emergency mode，畫面停在一個要你輸入 root 密碼的提示。**
>
> 對一台沒有主控台可用的遠端 VM 來說，這等於整台失聯。
> **`nofail` 一定要加。** 同理，第六欄的 fsck pass 也必須是 `0`。

改完 `fstab` **先在原地驗證，不要直接重開機** ★★★★★：

```bash
sudo umount /mnt/hgfs 2>/dev/null
sudo mount -a
df -hT | grep hgfs
```

```text
vmhgfs-fuse    fuse.vmhgfs-fuse  477G  231G  247G  49% /mnt/hgfs
```

`mount -a` 沒有噴錯、`df` 看得到，才代表重開機也會成功。

> [!tip] 更保險的做法：`x-systemd.automount` ★★★★
> ```text
> .host:/  /mnt/hgfs  fuse.vmhgfs-fuse  allow_other,defaults,nofail,x-systemd.automount,x-systemd.idle-timeout=60  0  0
> ```
> 加上 `x-systemd.automount` 之後，systemd **不會在開機時就掛載**，
> 而是等到有人真的存取 `/mnt/hgfs` 時才掛。
> 好處是開機流程完全不受 HGFS 影響，缺點是第一次存取會有一點延遲。
> 對「共享資料夾只是偶爾用一下」的實驗機來說，這個做法更適合。

#### 步驟 5：處理權限（讓一般使用者能寫入）★★★★

HGFS 沒有真正的 UNIX 權限，掛載後所有檔案的擁有者由掛載選項決定。
如果想讓 `ubuntu` 這個使用者直接讀寫：

```bash
id -u ubuntu; id -g ubuntu
```

```text
1000
1000
```

```text
.host:/  /mnt/hgfs  fuse.vmhgfs-fuse  allow_other,uid=1000,gid=1000,umask=0022,defaults,nofail  0  0
```

| 選項 | 作用 |
| --- | --- |
| `uid=1000` ★★★ | 檔案顯示為此 uid 擁有 |
| `gid=1000` ★★★ | 檔案顯示為此 gid 擁有 |
| `umask=0022` ★★ | 遮罩，得到 `rwxr-xr-x` |
| `allow_other` ★★★★ | 開放給掛載者以外的使用者 |
| `ro` ★★★ | 唯讀掛載（Host 端也可以設 Read-only，兩層都能設） |

---

## 進階應用

### ★★★ 剪貼簿與拖放

#### 開關在哪裡

**全域偏好**（影響所有 VM）：`Edit → Preferences → 相關分頁`

**單一 VM**：`VM → Settings → Options 分頁 → Guest Isolation`（以 Workstation 17 為例）

| 選項 | 意義 |
| --- | --- |
| `Enable drag and drop` ★★★ | Host 與 Guest 之間拖放檔案 |
| `Enable copy and paste` ★★★ | 共用剪貼簿（文字與小型檔案） |

#### 用 `.vmx` 參數強制關閉 ★★★★

GUI 的勾選最後也是寫進 `.vmx`，但直接寫檔可以做到「鎖死」，
在建範本機或做安全加固時比較方便。VM **必須完全關機**才能改：

```ini
isolation.tools.copy.disable = "TRUE"
isolation.tools.paste.disable = "TRUE"
isolation.tools.dnd.disable = "TRUE"
isolation.tools.hgfs.disable = "TRUE"
```

| 參數 | 關掉什麼 |
| --- | --- |
| `isolation.tools.copy.disable` ★★★ | 從 Guest 複製到 Host |
| `isolation.tools.paste.disable` ★★★ | 從 Host 貼到 Guest |
| `isolation.tools.dnd.disable` ★★★ | 拖放 |
| `isolation.tools.hgfs.disable` ★★★★ | **共享資料夾整個關掉** |

> [!danger] ★★★★★ 分析可疑檔案時，這四項全部設 TRUE
> 惡意程式的橫向移動途徑之一就是共享資料夾與剪貼簿。
> 要在 VM 裡開啟來路不明的檔案時：關掉這四項、網路改 Host-only 或斷線、
> 事前做好快照，做完直接還原快照。網路模式見
> [[050-01-02-04-guide-Workstation-網路模式]]。

#### 剪貼簿不能用的排查順序 ★★★

1. Guest 有沒有裝 `open-vm-tools-desktop`（純 `open-vm-tools` 沒有剪貼簿功能）
2. `VM → Settings → Options → Guest Isolation` 兩個勾有沒有勾
3. Guest 桌面的相關程序在不在：

```bash
pgrep -a vmtoolsd
```

```text
1183 /usr/bin/vmtoolsd
2841 /usr/bin/vmtoolsd -n vmusr
```

**要有 `-n vmusr` 那一支**（使用者層的 Tools 服務）才有剪貼簿。★★★★
沒有就重新登出登入桌面，或確認 `-desktop` 套件有裝。

### ★★★ 自動調整解析度

`View → Autofit Guest` 與 `View → Autofit Window`（以 Workstation 17 為例）：

| 選項 | 行為 |
| --- | --- |
| **Autofit Guest** ★★★ | 拉動 Workstation 視窗時，**Guest 解析度跟著改** |
| **Autofit Window** ★★ | 反過來：Guest 改解析度時，**視窗大小跟著改** |

沒有作用時的檢查順序：

1. `open-vm-tools-desktop` 有沒有裝
2. Guest 是不是純文字介面（沒有桌面就不會有這個功能，這是正常的）★★★
3. Wayland 環境下部分版本支援不完整，改用 X11 工作階段試試 ★★

Linux Guest 上也可以手動改：

```bash
xrandr --output Virtual-1 --mode 1920x1080
```

先看有哪些輸出與模式：

```bash
xrandr
```

```text
Screen 0: minimum 1 x 1, current 1920 x 1080, maximum 8192 x 8192
Virtual-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 0mm x 0mm
   1920x1080     60.00*+
   1600x1200     60.00
   1280x1024     60.00
```

### ★★★★ `vmware-toolbox-cmd`：被低估的診斷工具

open-vm-tools 附帶的這支命令列工具，能問到很多 Host 端的資訊。

```bash
vmware-toolbox-cmd help
```

常用子命令：

```bash
# 版本
vmware-toolbox-cmd -v
```

```text
12.3.5.46049 (build-22544099)
```

```bash
# Host 目前的時間（UTC）★★★★
vmware-toolbox-cmd stat hosttime
```

```text
02 Sep 2026 01:23:45
```

```bash
# 這台 VM 實際拿到多少 CPU 速度 ★★★
vmware-toolbox-cmd stat speed
```

```text
2904 MHz
```

```bash
# 氣球驅動目前收走多少記憶體 ★★★★
vmware-toolbox-cmd stat balloon
```

```text
0 MB
```

```bash
# 時間同步目前是開還關 ★★★★★
vmware-toolbox-cmd timesync status
```

```text
Disabled
```

```bash
# 列出 Guest 看到的虛擬磁碟
vmware-toolbox-cmd disk list
```

```text
/
/boot
```

```bash
# 通知 Host 這顆磁碟可以回收空白區塊（磁碟壓縮的 Guest 端動作）★★★★
sudo vmware-toolbox-cmd disk shrink /
```

> [!warning] ★★★★ `disk shrink` 會讓 VM 暫停一段時間
> 壓縮期間 VM 幾乎沒有回應，資料量大時可能好幾分鐘。
> 完整的磁碟壓縮流程與注意事項見
> [[050-01-02-06-guide-Workstation-效能調校與疑難排解]]。

```bash
# 查與設定 Tools 的組態值 ★★★
vmware-toolbox-cmd config get guestinfo poll-interval
```

### ★★★★ Host 與 Guest 之間傳資訊：guestinfo

`vmware-rpctool` 可以讓 Guest 讀取 Host 在 `.vmx` 裡設定的自訂變數，
做自動化佈署（例如把 IP 設定塞進去讓 Guest 開機時自己套用）時很好用。

Host 端在 `.vmx` 裡加：

```ini
guestinfo.role = "web"
guestinfo.site = "hq"
```

Guest 端讀取：

```bash
sudo vmware-rpctool "info-get guestinfo.role"
```

```text
web
```

搭配 cloud-init 或開機腳本，就能做到「同一個範本開出來的機器，
依 `.vmx` 的設定自動變成不同角色」。★★★

### ★★★★ 快照前後的自訂腳本

Tools 支援在特定事件時執行腳本，這是「靜默快照」的實作基礎。

腳本目錄（open-vm-tools）：

```bash
ls /etc/vmware-tools/scripts/vmware/
```

```text
network        poweron-vm-default   resume-vm-default
shutdown-vm-default   suspend-vm-default
```

| 腳本 | 觸發時機 | 典型用途 |
| --- | --- | --- |
| `poweron-vm-default` ★★ | VM 開機 | 啟動額外服務 |
| `suspend-vm-default` ★★★ | 暫停前 | 停掉資料庫寫入、flush |
| `resume-vm-default` ★★★★ | 恢復後 | **重新校時**（見下一節）、重啟服務 |
| `shutdown-vm-default` ★★ | 關機前 | 收尾 |

> [!tip] 不要直接改預設腳本 ★★★
> 套件更新會覆蓋 `*-default`。正確做法是在
> `/etc/vmware-tools/tools.conf` 裡指定自己的腳本路徑，
> 或把自訂邏輯放進 systemd 的 `suspend.target` 相關 unit。

---

### ★★★★★ 時間同步的坑

這一節是本篇的重點，**踩到的人非常多，而且症狀千奇百怪**。

#### 為什麼虛擬機的時間會跑掉

實體機的時鐘來自主機板上獨立供電的 RTC 晶片，很準。
虛擬機沒有真正的晶片，它的時間是**由 Hypervisor 模擬出來的中斷次數推算的**。

一旦 Host 忙不過來（CPU 超賣、你在做大量 I/O）或**整台 Host 進入睡眠**，
VM 收不到該收的時間中斷，時鐘就開始漏拍：

| 情境 | 時間會怎樣 | 嚴重度 |
| --- | --- | --- |
| **Host 進入睡眠／休眠再喚醒** ★★★★★ | VM 的時鐘從睡著那一刻繼續走，醒來後**慢了整整睡眠的時間** | 筆電使用者天天遇到 |
| 還原快照 ★★★★★ | 時間跳回快照當時，可能倒退好幾天 | 極常見 |
| 暫停（Suspend）後恢復 ★★★★ | 同睡眠情境 | 常見 |
| Host CPU 長時間滿載 ★★★ | 慢慢漂移，一天差幾秒到幾分鐘 | 慢性 |
| VM 被大量 I/O 卡住 ★★ | 短暫漂移 | 輕微 |

#### 時間跑掉的後果 ★★★★★

不要覺得「差幾分鐘沒差」，實際會炸的東西非常多：

| 影響 | 症狀 |
| --- | --- |
| **TLS／HTTPS 憑證驗證** ★★★★★ | `certificate is not yet valid` 或 `has expired`，所有 HTTPS 連線失敗 |
| **Kerberos／AD 網域登入** ★★★★★ | 時間差超過 5 分鐘直接拒絕認證，網域加入失敗 |
| `apt update` ★★★★ | `Release file ... is not valid yet` |
| 日誌關聯分析 ★★★★ | 多台機器時間對不上，事件根本排不出先後 |
| 排程工作 ★★★ | cron／systemd timer 在錯誤的時間點爆發性執行 |
| TOTP 兩步驟驗證 ★★★★ | 驗證碼永遠是錯的 |
| 資料庫複寫 ★★★★ | 時間戳異常，複寫延遲判斷失準 |

#### ★★★★★ 兩套授時機制在打架

這是核心問題。一台 Linux VM 上**同時存在兩個想校正時鐘的東西**：

```text
  ┌─ VMware Tools 時間同步 ──→ 從 Host 的時鐘抄
  │                            （Host 自己準不準？不一定）
  時鐘
  │
  └─ chrony / systemd-timesyncd ─→ 從 NTP 伺服器抄
                                   （準，但需要網路）
```

兩邊各自校正的結果就是**時鐘反覆被拉來拉去**，
`chronyc tracking` 顯示的偏移一直跳、日誌裡出現大量 `System clock was stepped`。

#### ★★★★★ 決策：選一套，關掉另一套

| 情境 | 建議做法 |
| --- | --- |
| **伺服器類實驗機**（Web／DB／AD／監控）★★★★★ | **關掉 Tools 時間同步，用 chrony 走 NTP** |
| **完全沒有網路的隔離實驗機** ★★★★ | 反過來：**開 Tools 時間同步，停掉 chrony** |
| 桌面型 VM、只是拿來點一點 ★★ | 兩者擇一即可，通常保留 chrony |
| **要加入 AD 網域的 VM** ★★★★★ | 一律用 NTP，而且**授時來源要是網域控制站** |

> [!danger] ★★★★★ 最糟的組合：兩個都開著
> Tools 從 Host 抄一個時間、chrony 從 NTP 抄另一個時間，兩邊差一點點，
> 時鐘就被來回 step。這種機器的日誌時間戳完全不能信，
> 排查故障時你會被自己的日誌騙。**務必二選一。**

#### 做法 A：關掉 Tools 時間同步，交給 chrony（建議）★★★★★

**步驟 1：關掉 Tools 的週期性同步**

```bash
sudo vmware-toolbox-cmd timesync disable
vmware-toolbox-cmd timesync status
```

```text
Disabled
```

**步驟 2：★★★★★ 關掉「事件觸發」的同步**

這一步幾乎所有教學都漏掉。即使 `timesync disable`，
**在「恢復暫停」「還原快照」「開機」這些事件發生時，Tools 仍然會做一次性的校時**。
要完全關掉，必須改 `.vmx`（VM 需完全關機）：

```ini
tools.syncTime = "FALSE"
time.synchronize.continue = "FALSE"
time.synchronize.restore = "FALSE"
time.synchronize.resume.disk = "FALSE"
time.synchronize.shrink = "FALSE"
time.synchronize.tools.startup = "FALSE"
```

| 參數 | 關掉哪一種校時 |
| --- | --- |
| `tools.syncTime` ★★★★ | 週期性同步（等同 `timesync disable`） |
| `time.synchronize.continue` ★★★★ | VM 從暫停恢復後 |
| `time.synchronize.restore` ★★★★★ | **還原快照後**——最容易被忽略的一項 |
| `time.synchronize.resume.disk` ★★★ | 磁碟恢復後 |
| `time.synchronize.shrink` ★★★ | 磁碟壓縮後 |
| `time.synchronize.tools.startup` ★★★★ | Tools 服務啟動時（＝每次開機） |

**步驟 3：設定 chrony**

```bash
sudo apt install -y chrony
```

編輯 `/etc/chrony/chrony.conf`，把授時來源改成機關內部的 NTP 或國內來源：

```ini
# 機關內部 NTP（優先）
server ntp.example.gov.tw iburst

# 允許開機時一次性大幅校正（前 3 次校正，偏差超過 1 秒就直接 step）
makestep 1.0 3

# 不要讓 chrony 去寫 RTC（虛擬機沒有真正的 RTC）
# rtcsync
```

> [!warning] ★★★★ 虛擬機上把 `rtcsync` 註解掉
> `rtcsync` 是叫核心定期把系統時間寫回硬體時鐘。虛擬機的「硬體時鐘」是模擬的，
> 這個動作意義不大，而且與 Hypervisor 的時間處理可能互相干擾。

**步驟 4：套用並驗證**

```bash
sudo systemctl restart chrony
sudo systemctl enable chrony
chronyc tracking
```

```text
Reference ID    : C0A80101 (ntp.example.gov.tw)
Stratum         : 3
Ref time (UTC)  : Wed Sep 02 01:30:12 2026
System time     : 0.000021374 seconds slow of NTP time
Last offset     : -0.000018231 seconds
RMS offset      : 0.000044912 seconds
Frequency       : 12.345 ppm slow
Skew            : 0.089 ppm
Root delay      : 0.002134 seconds
Root dispersion : 0.000891 seconds
Update interval : 64.2 seconds
Leap status     : Normal
```

**判讀重點 ★★★★**：

- `Stratum` 不是 `0` 或 `16` → 有正常授時來源
- `System time` 的偏差是**毫秒等級以下** → 正常
- `Leap status : Normal` → 沒有異常

```bash
chronyc sources -v
```

```text
MS Name/IP address         Stratum Poll Reach LastRx Last sample
===============================================================================
^* ntp.example.gov.tw            2   6   377    31   -18us[  -21us] +/-  2.1ms
```

行首的 `^*` 代表這是目前選用的來源。★★★★
如果全部都是 `^?`（無法連線）就是網路或防火牆問題。

#### 做法 B：沒有網路時，改用 Tools 授時 ★★★★

隔離環境（Host-only 網路、沒有對外連線）拿不到 NTP，這時反過來：

```bash
sudo systemctl disable --now chrony
sudo timedatectl set-ntp false
sudo vmware-toolbox-cmd timesync enable
vmware-toolbox-cmd timesync status
```

```text
Enabled
```

> [!warning] ★★★★ 這時候「Host 準不準」就決定一切
> Tools 是從 Host 抄時間。Host 自己時間錯了，所有 VM 一起錯。
> 用這個做法之前，**先確認 Host 端的時間是正確的**
> （Windows 上 `w32tm /query /status`）。

#### ★★★★★ 主機睡眠醒來後的緊急處理

筆電闔上蓋子、隔天打開，VM 時間慢了 15 小時。這時候：

```bash
# 1. 先看差多少
date; vmware-toolbox-cmd stat hosttime
```

```text
Tue Sep  1 18:42:03 CST 2026
02 Sep 2026 01:33:11
```

Guest 顯示昨天下午、Host 已經是今天凌晨（UTC）——確認時間跑掉了。

```bash
# 2. 用 chrony 強制立刻校正（不等它慢慢 slew）★★★★★
sudo chronyc makestep
```

```text
200 OK
```

```bash
# 3. 驗證
date
timedatectl
```

```text
               Local time: Wed 2026-09-02 09:33:15 CST
           Universal time: Wed 2026-09-02 01:33:15 UTC
                 RTC time: Wed 2026-09-02 01:33:15
                Time zone: Asia/Taipei (CST, +0800)
System clock synchronized: yes
              NTP service: active
```

`System clock synchronized: yes` 就對了。★★★★

> [!danger] ★★★★★ `chronyc makestep` 會讓時鐘瞬間跳躍
> 對正在跑的資料庫、Java 應用、有 TTL 邏輯的服務來說，**時鐘瞬間跳幾小時
> 可能造成資料異常或程式當掉**。在正式環境不要隨便下這個指令；
> 實驗機沒關係，但如果 VM 上正跑著東西，**先停服務再校時，校完再啟動**。

> [!tip] 睡眠恢復後自動校時 ★★★★
> 與其每次手動下 `makestep`，不如讓系統自己做。
> 建立 `/etc/systemd/system/chrony-resume.service`：
>
> ```ini
> [Unit]
> Description=Force chrony step after resume
> After=suspend.target hibernate.target
>
> [Service]
> Type=oneshot
> ExecStart=/usr/bin/chronyc makestep
>
> [Install]
> WantedBy=suspend.target hibernate.target
> ```
>
> ```bash
> sudo systemctl daemon-reload
> sudo systemctl enable chrony-resume.service
> ```
>
> 注意這是針對 **Guest 自己被暫停**的情境；Host 睡眠而 Guest 仍在執行時，
> Guest 不一定會收到 suspend 事件，該情境仍需靠 chrony 的常態校正慢慢拉回，
> 或手動 `makestep`。

---

## 完整實戰範例

**情境**：新建了一台 Ubuntu Server 24.04 實驗機，要把它整備成「本手冊各章可直接使用」
的狀態——Tools 裝好、共享資料夾開機自動掛載、時間走 NTP 且不與 Tools 打架。

**前置條件**：

- Host：Windows 11，Workstation 17 Pro
- Guest：Ubuntu Server 24.04，已完成安裝，可用 `ubuntu` 帳號登入
- Guest 網路為 NAT（可對外），見 [[050-01-02-04-guide-Workstation-網路模式]]

### 步驟 1：Host 端建立共享目錄

```powershell
New-Item -ItemType Directory -Path 'D:\vm-share' -Force
New-Item -ItemType Directory -Path 'D:\vm-iso' -Force
'hello from host' | Out-File -Encoding utf8 'D:\vm-share\test.txt'
```

```text
    目錄: D:\

Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
d-----         2026/9/2  上午 09:05                vm-share
```

### 步驟 2：VM 關機，設定共享資料夾

在 Guest 裡：

```bash
sudo poweroff
```

Workstation：`VM → Settings → Options → Shared Folders`

1. 選 **Always enabled**
2. `Add…` → Host path `D:\vm-share` → Name `share` → 勾 Enable
3. `Add…` → Host path `D:\vm-iso` → Name `iso` → 勾 Enable → **勾 Read-only** ★★★★
4. `OK`

### 步驟 3：★★★ 先關掉 Tools 的時間同步（在 `.vmx` 裡）

VM 仍在關機狀態。用文字編輯器開啟 `.vmx`（路徑可在 VM Settings 的
`Options → General → 工作目錄` 找到）：

```ini
tools.syncTime = "FALSE"
time.synchronize.continue = "FALSE"
time.synchronize.restore = "FALSE"
time.synchronize.resume.disk = "FALSE"
time.synchronize.shrink = "FALSE"
time.synchronize.tools.startup = "FALSE"
```

存檔。

> [!warning] ★★★★ 改 `.vmx` 一定要在 VM 完全關機時
> VM 在執行中（或 Suspend 狀態）時 Workstation 持有這個檔案，
> 你的修改會在 VM 關機時被程式寫回去的內容覆蓋掉。

### 步驟 4：開機，安裝 open-vm-tools

```bash
sudo apt update
sudo apt install -y open-vm-tools
```

驗證：

```bash
systemctl is-active open-vm-tools
vmware-toolbox-cmd -v
```

```text
active
12.3.5.46049 (build-22544099)
```

### 步驟 5：確認共享有傳進來

```bash
vmware-hgfsclient
```

```text
share
iso
```

**沒有輸出就回步驟 2 檢查**，不要往下做。★★★★

### 步驟 6：確認 FUSE 允許其他使用者

```bash
grep -n user_allow_other /etc/fuse.conf
```

```text
10:#user_allow_other
```

被註解掉了，取消註解：

```bash
sudo sed -i 's/^#user_allow_other/user_allow_other/' /etc/fuse.conf
grep -n user_allow_other /etc/fuse.conf
```

```text
10:user_allow_other
```

### 步驟 7：建立掛載點並手動掛載測試

```bash
sudo mkdir -p /mnt/hgfs
sudo /usr/bin/vmhgfs-fuse .host:/ /mnt/hgfs -o subtype=vmhgfs-fuse,allow_other,uid=1000,gid=1000
ls -l /mnt/hgfs/
cat /mnt/hgfs/share/test.txt
```

```text
total 0
drwxr-xr-x 1 ubuntu ubuntu 4096 Sep  2 09:05 iso
drwxr-xr-x 1 ubuntu ubuntu 4096 Sep  2 09:05 share
hello from host
```

**看到 `hello from host` 代表 Host → Guest 方向通了。** ★★★★

反向測試：

```bash
echo 'hello from guest' > /mnt/hgfs/share/from-guest.txt
ls -l /mnt/hgfs/share/
```

```text
total 1
-rw-r--r-- 1 ubuntu ubuntu 17 Sep  2 09:12 from-guest.txt
-rw-r--r-- 1 ubuntu ubuntu 16 Sep  2 09:05 test.txt
```

回 Host 確認 `D:\vm-share\from-guest.txt` 真的出現了。★★★

順便驗證唯讀共享確實是唯讀的：

```bash
touch /mnt/hgfs/iso/should-fail
```

```text
touch: cannot touch '/mnt/hgfs/iso/should-fail': Read-only file system
```

### 步驟 8：★★★★★ 寫進 `/etc/fstab`

```bash
sudo cp /etc/fstab /etc/fstab.bak-$(date +%F)
echo '.host:/  /mnt/hgfs  fuse.vmhgfs-fuse  allow_other,uid=1000,gid=1000,defaults,nofail,x-systemd.automount  0  0' | sudo tee -a /etc/fstab
tail -n 2 /etc/fstab
```

```text
.host:/  /mnt/hgfs  fuse.vmhgfs-fuse  allow_other,uid=1000,gid=1000,defaults,nofail,x-systemd.automount  0  0
```

原地驗證：

```bash
sudo umount /mnt/hgfs
sudo systemctl daemon-reload
sudo mount -a
df -hT | grep hgfs
```

```text
vmhgfs-fuse    fuse.vmhgfs-fuse  477G  231G  247G  49% /mnt/hgfs
```

### 步驟 9：確認 Tools 時間同步真的關著

```bash
vmware-toolbox-cmd timesync status
```

```text
Disabled
```

### 步驟 10：設定 chrony

```bash
sudo apt install -y chrony
sudo cp /etc/chrony/chrony.conf /etc/chrony/chrony.conf.bak
```

編輯 `/etc/chrony/chrony.conf`，加入（或調整）：

```ini
server tock.stdtime.gov.tw iburst
server watch.stdtime.gov.tw iburst
makestep 1.0 3
```

```bash
sudo systemctl restart chrony
sudo systemctl enable chrony
sleep 10
chronyc sources -v | tail -n 4
```

```text
MS Name/IP address         Stratum Poll Reach LastRx Last sample
===============================================================================
^* tock.stdtime.gov.tw           1   6   17     8   +112us[ +142us] +/-  8.9ms
^- watch.stdtime.gov.tw          1   6   17     9   +203us[ +203us] +/-  9.4ms
```

### 步驟 11：重新開機做最終驗收

```bash
sudo reboot
```

登入後，一次跑完所有驗收項目：

```bash
echo '--- Tools ---'
systemctl is-active open-vm-tools
vmware-toolbox-cmd -v
echo '--- 共享資料夾 ---'
vmware-hgfsclient
ls /mnt/hgfs/
cat /mnt/hgfs/share/test.txt
echo '--- 時間 ---'
vmware-toolbox-cmd timesync status
timedatectl | grep -E 'Local time|synchronized|NTP service'
```

```text
--- Tools ---
active
12.3.5.46049 (build-22544099)
--- 共享資料夾 ---
share
iso
iso  share
hello from host
--- 時間 ---
Disabled
               Local time: Wed 2026-09-02 09:40:22 CST
System clock synchronized: yes
              NTP service: active
```

**七項全過就完成了。** ★★★★★

### 步驟 12：做一個快照存起來

```text
VM → Snapshot → Take Snapshot…
名稱：base-tools-ok
描述：open-vm-tools + hgfs 自動掛載 + chrony NTP 完成
```

之後所有實驗都從這個快照長出去。做法見
[[050-01-02-03-guide-Workstation-快照與複製]]。

### 驗收檢核表

| # | 檢查項 | 通過條件 |
| --- | --- | --- |
| 1 | Tools 服務 ★★★★ | `systemctl is-active open-vm-tools` = `active` |
| 2 | Host 看得到 IP ★★★ | Workstation 主畫面顯示 VM 的 IP |
| 3 | 共享清單 ★★★★ | `vmware-hgfsclient` 列出 `share` `iso` |
| 4 | 開機自動掛載 ★★★★★ | 重開機後 `ls /mnt/hgfs` 有內容 |
| 5 | 雙向讀寫 ★★★★ | Guest 建的檔案在 Host 看得到 |
| 6 | 唯讀共享生效 ★★★ | 在 `iso` 裡 `touch` 得到 `Read-only file system` |
| 7 | Tools 授時已關 ★★★★★ | `timesync status` = `Disabled` |
| 8 | NTP 正常 ★★★★★ | `chronyc sources` 有 `^*` 來源 |

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| `vmware-hgfsclient: command not found` ★★★ | open-vm-tools 沒裝 | `sudo apt install open-vm-tools` |
| `vmware-hgfsclient` 沒有任何輸出 ★★★★★ | Host 端共享資料夾是 Disabled，或沒有 Add 任何共享 | `VM → Settings → Options → Shared Folders` 設為 Always enabled 並新增共享 |
| `/mnt/hgfs` 存在但完全是空的 ★★★★★ | **只建了目錄沒有掛載**——open-vm-tools 走 FUSE，不會自動掛 | `sudo vmhgfs-fuse .host:/ /mnt/hgfs -o allow_other`，再寫進 `/etc/fstab` |
| `/mnt/hgfs` 根本不存在 ★★★★ | 掛載點沒建 | `sudo mkdir -p /mnt/hgfs` |
| `fusermount: option allow_other only allowed if 'user_allow_other' is set in /etc/fuse.conf` ★★★★ | FUSE 未開放給其他使用者 | 取消註解 `/etc/fuse.conf` 裡的 `user_allow_other` |
| 一般使用者 `ls /mnt/hgfs` 得到 `Permission denied` ★★★★ | 用 root 掛載且沒加 `allow_other` | 重新掛載時加 `allow_other`，或加 `uid=`／`gid=` |
| `mount: unknown filesystem type 'vmhgfs'` ★★★★ | fstab 型別寫成舊的 `vmhgfs` | 改成 **`fuse.vmhgfs-fuse`** |
| **重開機卡在 emergency mode，要求輸入 root 密碼** ★★★★★ | `/etc/fstab` 的 HGFS 那行掛載失敗且沒加 `nofail` | 進 emergency shell → `mount -o remount,rw /` → 編輯 `/etc/fstab` 加 `nofail`（或註解掉該行）→ `reboot` |
| Windows Guest 找不到 `\\vmware-host\Shared Folders` ★★★★ | 共享是 Disabled，或 VMware Tools 未安裝／服務未啟動 | 設為 Always enabled；`Get-Service VMTools` 確認為 Running |
| 掛載成功但看不到剛在 Host 建立的新檔案 ★★★ | HGFS 的目錄快取尚未更新 | `ls` 上層目錄一次通常就會刷新；必要時 `umount` 後重掛 |
| 在共享資料夾裡跑 `git clone` 或 `npm install` 出現大量權限／連結錯誤 ★★★★ | HGFS 不支援符號連結與完整 POSIX 權限 | **不要在 `/mnt/hgfs` 裡做開發**，複製到本機路徑再操作 |
| 剪貼簿無法複製貼上 ★★★ | 只裝了 `open-vm-tools`，缺 `-desktop`；或 Guest Isolation 關閉 | 裝 `open-vm-tools-desktop`；勾選 `Enable copy and paste`；確認有 `vmtoolsd -n vmusr` 程序 |
| 拖放檔案進 VM 沒反應 ★★★ | 同上 | 同上，並改用共享資料夾作為替代 |
| 視窗放大但 Guest 解析度不變 ★★★★ | 缺 `-desktop`，或 `View → Autofit Guest` 未開 | 裝 `-desktop`、開 Autofit Guest；純文字介面 Guest 沒有此功能屬正常 |
| Workstation 一直提示「VMware Tools 已過期」★★★ | Guest 裝的是原廠 Tools 且版本落後 | Linux 改用 open-vm-tools（提示會消失）；Windows 重跑安裝程式 |
| Linux Guest 升級核心後網路卡消失 ★★★★★ | 曾用 `vmware-install.pl` 裝原廠 Tools，模組編不過 | `sudo /usr/bin/vmware-uninstall-tools.pl` 移除，改裝 `open-vm-tools`，重開機 |
| 主機睡眠喚醒後 Guest 時間慢了好幾小時 ★★★★★ | 虛擬時鐘在 Host 睡眠期間停止推進 | `sudo chronyc makestep` 立即校正；長期解法是設好 NTP 並考慮加 resume 自動校時 unit |
| `journalctl` 大量 `System clock was stepped by …` ★★★★★ | Tools 授時與 chrony 同時開著互相打架 | 二選一：`vmware-toolbox-cmd timesync disable` ＋ `.vmx` 的六個 `time.synchronize.*` 全設 FALSE |
| 還原快照後時間跳回過去，`apt update` 報 `not valid yet` ★★★★★ | 快照還原時 Tools 做了一次性校時，或 chrony 尚未追上 | 設 `time.synchronize.restore = "FALSE"`；還原後手動 `sudo chronyc makestep` |
| 加入 AD 網域失敗，提示時間差異過大 ★★★★★ | Guest 時間與網域控制站差超過 5 分鐘 | 把 chrony 的 `server` 指向網域控制站，`chronyc makestep` 後重試 |
| `chronyc sources` 全部顯示 `^?` ★★★★ | 網路不通或 UDP/123 被擋 | 確認 VM 網路模式與對外連線；隔離環境改用 Tools 授時 |
| `vmware-toolbox-cmd timesync status` 顯示 `Disabled` 但時間仍會被改 ★★★★★ | 只關了週期性同步，事件觸發的同步仍開著 | 在 `.vmx` 補上 `time.synchronize.restore`／`.continue`／`.tools.startup` 等六項 |
| 改了 `.vmx` 但重開後設定不見了 ★★★★ | 改檔時 VM 不是完全關機（執行中或 Suspend） | 完全關機（不是 Suspend）後再改，存檔後才開機 |

---

## 安全性注意事項

> [!danger] ★★★★★ 共享資料夾是 Host 與 Guest 之間最短的攻擊路徑
> Guest 裡的惡意程式可以直接寫入 Host 上的共享目錄。如果那個目錄剛好是
> Host 的下載資料夾或某個會被自動掃描／自動執行的位置，就等於直通 Host。

| 項目 | 風險 | 做法 |
| --- | --- | --- |
| 分享範圍過大 ★★★★★ | 分享 `C:\` 或家目錄等於整台主機曝露 | 只分享一個專用中繼目錄，不放其他資料 |
| 未使用時仍保持啟用 ★★★★ | 隨時可被 Guest 存取 | 平常設 **Disabled**，要用再開；或用「Enabled until next power off」 |
| 分析可疑樣本時開著共享 ★★★★★ | 惡意程式沿共享路徑污染 Host | 四個 `isolation.tools.*.disable` 全設 `TRUE`，網路改 Host-only，事前做快照 |
| 唯讀共享沒設 ★★★★ | Guest 可竄改 Host 上的安裝檔／設定檔 | 放 ISO 與安裝檔的共享一律勾 **Read-only** |
| 用共享資料夾放憑證私鑰 ★★★★★ | HGFS 無法表達 `0600` 權限，私鑰形同公開 | **私鑰絕不放共享資料夾**，用 `scp` 傳並在 Guest 內設好權限，見 [[090-01-00-idx-PKI-憑證與PKI]] |
| 剪貼簿長期開著 ★★★ | 從 Host 複製的密碼可能被 Guest 內程式讀取 | 處理敏感資訊時關閉剪貼簿共享 |
| 拖放功能 ★★★ | 誤把 Host 的敏感檔案拖進不受信任的 VM | 不需要就關掉 |
| 時間不同步 ★★★★★ | 憑證驗證失效、日誌時間戳不可信、鑑識時序錯亂 | 依本篇設好單一授時來源；資安相關 VM 的時間必須正確 |
| Tools 版本過舊 ★★★★ | Tools 本身曾出現安全性更新 | Linux 用 open-vm-tools 隨系統更新；Windows 定期重跑安裝程式 |
| `guestinfo` 塞入敏感資料 ★★★★ | `.vmx` 是純文字，任何能讀該檔的人都看得到 | 不要把密碼、金鑰寫進 `guestinfo.*` |
| 範本機殘留共享設定 ★★★ | 複製出去的 VM 自動帶著對 Host 的共享 | 封裝範本前把共享設為 Disabled 並移除所有共享項目 |

---

## 速查表

### 安裝

| 動作 | 指令 |
| --- | --- |
| 確認在虛擬機裡 ★★★ | `systemd-detect-virt` → `vmware` |
| 確認虛擬平台 ★★ | `sudo dmidecode -s system-product-name` |
| 安裝（Ubuntu／Debian）★★★★ | `sudo apt install -y open-vm-tools` |
| 安裝桌面元件 ★★★ | `sudo apt install -y open-vm-tools-desktop` |
| 安裝（Rocky／Alma）★★★ | `sudo dnf install -y open-vm-tools` |
| 服務名（Ubuntu）★★★★ | `open-vm-tools.service` |
| 服務名（RHEL 系）★★★★ | `vmtoolsd.service` |
| 移除誤裝的原廠版 ★★★★★ | `sudo /usr/bin/vmware-uninstall-tools.pl` |
| Windows Guest 安裝 ★★★★ | `VM → Install VMware Tools` → `D:\setup64.exe` |
| Windows 靜默安裝 ★★★ | `D:\setup64.exe /S /v "/qn REBOOT=R"` |

### 驗證

| 檢查 | 指令 | 預期 |
| --- | --- | --- |
| 服務狀態 ★★★★ | `systemctl is-active open-vm-tools` | `active` |
| Tools 版本 ★★★ | `vmware-toolbox-cmd -v` | 版本字串 |
| 核心模組 ★★★ | `lsmod \| grep -E 'vmw_\|vmxnet'` | 列出多個模組 |
| 使用者層服務（剪貼簿）★★★★ | `pgrep -a vmtoolsd` | 要有 `-n vmusr` 那支 |
| Windows 服務 ★★★★ | `Get-Service VMTools` | `Running` |

### 共享資料夾

| 動作 | 指令／路徑 |
| --- | --- |
| 列出可用共享 ★★★★★ | `vmware-hgfsclient` |
| 手動掛載全部 ★★★★★ | `sudo vmhgfs-fuse .host:/ /mnt/hgfs -o allow_other` |
| 只掛單一共享 ★★★ | `sudo vmhgfs-fuse .host:/share /mnt/share -o allow_other` |
| 卸載 ★★★ | `sudo umount /mnt/hgfs` |
| `fstab` 寫法 ★★★★★ | `.host:/ /mnt/hgfs fuse.vmhgfs-fuse allow_other,defaults,nofail 0 0` |
| 檔案系統型別 ★★★★★ | **`fuse.vmhgfs-fuse`**（不是 `vmhgfs`） |
| 允許非掛載者存取 ★★★★ | `/etc/fuse.conf` 的 `user_allow_other` |
| 原地驗證 fstab ★★★★★ | `sudo mount -a` 且無錯誤 |
| Windows UNC 路徑 ★★★★ | `\\vmware-host\Shared Folders\<Name>` |
| Windows 對應磁碟機 ★★★ | `net use Z: "\\vmware-host\Shared Folders\share" /persistent:yes` |

### `vmware-toolbox-cmd`

| 用途 | 指令 |
| --- | --- |
| 版本 ★★★ | `vmware-toolbox-cmd -v` |
| Host 時間（UTC）★★★★ | `vmware-toolbox-cmd stat hosttime` |
| 實際 CPU 速度 ★★★ | `vmware-toolbox-cmd stat speed` |
| 氣球佔用 ★★★ | `vmware-toolbox-cmd stat balloon` |
| 時間同步狀態 ★★★★★ | `vmware-toolbox-cmd timesync status` |
| 關閉時間同步 ★★★★★ | `sudo vmware-toolbox-cmd timesync disable` |
| 開啟時間同步 ★★★★ | `sudo vmware-toolbox-cmd timesync enable` |
| 列出磁碟 ★★ | `vmware-toolbox-cmd disk list` |
| 通知可回收空間 ★★★★ | `sudo vmware-toolbox-cmd disk shrink /` |

### 時間

| 動作 | 指令 |
| --- | --- |
| 看整體時間狀態 ★★★★ | `timedatectl` |
| chrony 追蹤狀態 ★★★★★ | `chronyc tracking` |
| chrony 來源清單 ★★★★★ | `chronyc sources -v` |
| **立即強制校正** ★★★★★ | `sudo chronyc makestep` |
| 設定檔 ★★★ | `/etc/chrony/chrony.conf`（Ubuntu）、`/etc/chrony.conf`（RHEL） |
| 關閉 systemd 授時 ★★★ | `sudo timedatectl set-ntp false` |

### `.vmx` 參數

| 參數 | 作用 |
| --- | --- |
| `tools.syncTime = "FALSE"` ★★★★ | 關週期性校時 |
| `time.synchronize.restore = "FALSE"` ★★★★★ | 關「還原快照後」校時 |
| `time.synchronize.continue = "FALSE"` ★★★★ | 關「恢復暫停後」校時 |
| `time.synchronize.tools.startup = "FALSE"` ★★★★ | 關「Tools 啟動時」校時 |
| `time.synchronize.resume.disk = "FALSE"` ★★★ | 關「磁碟恢復後」校時 |
| `time.synchronize.shrink = "FALSE"` ★★★ | 關「磁碟壓縮後」校時 |
| `isolation.tools.hgfs.disable = "TRUE"` ★★★★ | 關共享資料夾 |
| `isolation.tools.copy.disable = "TRUE"` ★★★ | 關 Guest→Host 複製 |
| `isolation.tools.paste.disable = "TRUE"` ★★★ | 關 Host→Guest 貼上 |
| `isolation.tools.dnd.disable = "TRUE"` ★★★ | 關拖放 |

---

## 練習題

1. 在一台全新的 Ubuntu Server VM 上，從零完成本篇的「驗收檢核表」八項，
   並把過程中每一步的實際輸出記錄下來。哪一步你花的時間最久？為什麼？

2. 故意把 `/etc/fstab` 裡 HGFS 那行的 `nofail` 拿掉，然後在 Workstation 把共享資料夾
   設成 Disabled，重新開機。記錄你看到的畫面，並寫出從那個畫面救回系統的完整步驟。
   （做這題之前**先做快照**。）

3. 在 VM 裡同時啟用 `vmware-toolbox-cmd timesync enable` 與 chrony，
   放置一段時間後用 `journalctl -u chrony` 觀察日誌。你看到什麼？
   再關掉其中一邊，比較日誌的差異。

4. 建立一個唯讀共享放 ISO、一個可寫共享放交換檔案，讓 `ubuntu` 使用者
   不需要 `sudo` 就能讀寫可寫的那個。寫出你的 `fstab` 那一行並說明每個選項的理由。

5. 為你的機關寫一份「VM 交付前的 Tools 與時間檢查表」，
   要能讓一個沒看過本篇的同事照著做。

6. 思考題：為什麼本篇一再強調「不要在 `/mnt/hgfs` 裡做開發或部署」？
   列出至少四個具體會出問題的場景。

> [!question]- 練習解答
>
> **1.** 常見的卡關點是**步驟 6 的 `/etc/fuse.conf`**（沒開 `user_allow_other`
> 導致 `allow_other` 掛載失敗）與**步驟 8 的 fstab 型別**（寫成 `vmhgfs` 而不是
> `fuse.vmhgfs-fuse`）。建議把 `sudo mount -a` 當成必經關卡，
> **在原地驗證通過才重開機**，可以省下大量來回。★★★★
>
> **2.** 你會看到類似：
> ```text
> You are in emergency mode. After logging in, type "journalctl -xb" to view
> system logs, ... Give root password for maintenance:
> ```
> 救回步驟：
> 1. 輸入 root 密碼（或 Ubuntu 預設無 root 密碼時，改從 GRUB 進 recovery mode）
> 2. `mount -o remount,rw /` 讓根目錄可寫
> 3. `vi /etc/fstab`，把 HGFS 那行註解掉，或補上 `nofail`
> 4. `systemctl daemon-reload`
> 5. `reboot`
>
> 結論：**`nofail` 是保命參數**，任何「可能不存在」的掛載點都要加。★★★★★
>
> **3.** 兩邊都開時，`journalctl -u chrony` 會出現反覆的
> `System clock was stepped by …` 或偏移量在正負之間跳動——這就是兩套授時打架的證據。
> 關掉 Tools 授時後，日誌會安靜下來，`chronyc tracking` 的
> `System time` 偏差穩定在毫秒等級。★★★★★
>
> **4.** Host 端：`iso` 共享勾 Read-only、`share` 共享不勾。
> Guest 端 fstab：
> ```text
> .host:/  /mnt/hgfs  fuse.vmhgfs-fuse  allow_other,uid=1000,gid=1000,defaults,nofail,x-systemd.automount  0  0
> ```
> - `allow_other`：root 掛載後開放給其他使用者，否則 `ubuntu` 看不到 ★★★★
> - `uid=1000,gid=1000`：檔案顯示為 `ubuntu` 擁有，不必 `sudo` 就能寫 ★★★★
> - `nofail`：共享消失時不會卡開機 ★★★★★
> - `x-systemd.automount`：延遲到實際存取才掛，開機更穩 ★★★
> - 第六欄 `0`：HGFS 不能做 fsck ★★★★
>
> 唯讀是**在 Host 端設的**，Guest 端不需要另外加 `ro`（兩層都設也可以，更保險）。
>
> **5.** 檢查表大綱：
> - **Tools**：服務 active、版本可查、Host 看得到 IP
> - **共享**：確認是否需要；不需要就設 Disabled 並移除項目
> - **時間**：`timesync status` 為 `Disabled`、`chronyc sources` 有 `^*`、
>   `timedatectl` 顯示 `System clock synchronized: yes`
> - **安全**：私鑰不在共享路徑、`isolation.tools.*` 依用途設定
> - **交付**：做一個乾淨快照並命名
>
> **6.** 四個場景：
> 1. **Git**：HGFS 不支援符號連結與檔案模式位元，`git status` 會顯示整個工作區都被改過 ★★★★
> 2. **`npm install` / `composer install`**：大量小檔案 I/O 走 HGFS 極慢，且建符號連結會失敗 ★★★★
> 3. **開發伺服器的熱重載**：HGFS 不提供 `inotify` 事件，改檔案不會觸發重新編譯 ★★★★
> 4. **Web 根目錄**：無法設定 `www-data` 的擁有者與 `0640` 權限，
>    要嘛全開要嘛完全不能讀，權限模型整個失效 ★★★★★
>
> 另外還有：資料庫檔案放 HGFS 會因檔案鎖行為異常而損毀 ★★★★★。

---

## 小測驗

Q1. Linux Guest 應該裝原廠 VMware Tools 還是 open-vm-tools？說出至少兩個理由。

Q2.（是非）在現代 Ubuntu 上跑 `lsmod | grep vmhgfs` 沒有輸出，代表 Tools 沒裝好。

Q3. 使用者說「我在 Workstation 裡設好共享資料夾了，可是 Guest 的 `/mnt/hgfs` 是空的」。
你會先下哪一行指令來分辨是 Host 端問題還是 Guest 端問題？兩種結果各代表什麼？

Q4. 下面這行 `/etc/fstab` 有兩個嚴重問題，找出來並說明後果。

```text
.host:/  /mnt/hgfs  vmhgfs  allow_other,defaults  0  2
```

Q5.（選擇）Guest 裡可以複製貼上文字，但拖放檔案沒反應。最不可能的原因是哪一個？
(A) `Enable drag and drop` 沒勾　(B) `open-vm-tools-desktop` 沒裝
(C) VM 的網路是 Host-only　(D) `isolation.tools.dnd.disable` 被設為 `TRUE`

Q6. 已經跑了 `vmware-toolbox-cmd timesync disable`，
為什麼還原快照之後時間仍然被改掉？怎麼徹底解決？

Q7.（簡答）為什麼建議在虛擬機的 `chrony.conf` 裡把 `rtcsync` 註解掉？

Q8. 筆電闔蓋一晚後，VM 時間慢了 15 小時，上面正跑著一個 MySQL。
你會怎麼處理？直接下 `sudo chronyc makestep` 有什麼風險？

Q9.（是非）共享資料夾走的是 TCP/IP，所以 VM 網路不通時共享資料夾也不能用。

Q10. 一台要加入 AD 網域的 Windows VM，加入時提示時間差異過大。
列出你的排查與處理順序。

> [!question]- 測驗答案
>
> **Q1.** **open-vm-tools**。理由（任兩個）：
> ①原廠已建議 Linux 改用 open-vm-tools；②跟著 `apt upgrade` 一起更新，不必手動維護；
> ③模組已進主線核心，核心升級不會編不過；④一行 `apt install` 就好，
> 不必掛 ISO 解壓跑腳本。
> → 見〈VMware Tools 與 open-vm-tools 的差別〉★★★★★
>
> **Q2.** **錯**。`vmhgfs` 核心模組在現代系統上**本來就不存在**，
> open-vm-tools 改用使用者空間的 `vmhgfs-fuse`。要驗證 Tools 是否正常，
> 應該看 `systemctl is-active open-vm-tools` 與 `vmware-toolbox-cmd -v`。
> → 見〈安裝或基礎操作〉步驟 4 的 note ★★★★★
>
> **Q3.** 先下 **`vmware-hgfsclient`**。
> - **有列出共享名稱** → Host 端設定正確，問題在 Guest 沒掛載，去做 `vmhgfs-fuse` 掛載
> - **沒有輸出** → Host 端的共享資料夾是 Disabled 或沒有 Add，回 Workstation 設定
> 這一行指令可以省掉一半的猜測。
> → 見〈共享資料夾：Linux Guest 端〉步驟 1 ★★★★★
>
> **Q4.** 兩個問題：
> ①**檔案系統型別寫成 `vmhgfs`**，正確是 `fuse.vmhgfs-fuse`，
> 否則 `mount` 會報 `unknown filesystem type`；
> ②**第六欄 fsck pass 是 `2`**，系統開機時會試著對 HGFS 做 fsck，
> 加上沒有 `nofail`，失敗時會把開機流程丟進 emergency mode。
> 正確寫法：`.host:/ /mnt/hgfs fuse.vmhgfs-fuse allow_other,defaults,nofail 0 0`。
> → 見〈步驟 4：設定開機自動掛載〉★★★★★
>
> **Q5.** **(C) VM 的網路是 Host-only**。共享資料夾與拖放走的是 VMCI 通道，
> **與 TCP/IP 網路完全無關**，網路模式不影響這些功能。
> (A)(B)(D) 都是真正可能的原因。
> → 見〈HGFS 到底怎麼運作〉關鍵事實 1 ★★★★
>
> **Q6.** 因為 `timesync disable` **只關掉週期性同步**，
> 「還原快照後」「恢復暫停後」「Tools 啟動時」等**事件觸發的一次性校時仍然生效**。
> 徹底解法是在 `.vmx`（VM 完全關機時）補上
> `time.synchronize.restore = "FALSE"` 等六個參數。
> → 見〈做法 A〉步驟 2 ★★★★★
>
> **Q7.** `rtcsync` 是叫核心定期把系統時間寫回硬體時鐘，
> 但**虛擬機的「硬體時鐘」是 Hypervisor 模擬的**，這個寫回動作意義不大，
> 且可能與 Hypervisor 自身的時間處理互相干擾。
> → 見〈做法 A〉步驟 3 的 warning ★★★★
>
> **Q8.** 順序是：**先停 MySQL → 再校時 → 再啟動 MySQL**。
> 直接 `chronyc makestep` 的風險是**時鐘瞬間往前跳 15 小時**，
> 正在執行的資料庫、有 TTL/逾時邏輯的程式可能出現資料異常、
> 連線大量逾時甚至程序當掉。實驗機無所謂，有服務在跑就要先停。
> → 見〈主機睡眠醒來後的緊急處理〉的 danger ★★★★★
>
> **Q9.** **錯**。共享資料夾走 **VMCI（Host-Guest 通道）**，不走 TCP/IP。
> 這正是它的價值之一：**網路設壞了進不去的時候，還能靠共享資料夾搬檔案救援**。
> → 見〈HGFS 到底怎麼運作〉關鍵事實 1 ★★★★
>
> **Q10.** 排查順序：
> 1. 比對 Guest 與網域控制站的時間差（Kerberos 預設容忍 5 分鐘）
> 2. 確認 Guest 是不是同時開著 Tools 授時與 NTP 在打架
> 3. 關掉 Tools 授時（含 `.vmx` 的 `time.synchronize.*` 六項）
> 4. 把授時來源指向**網域控制站**（AD 環境的標準做法）
> 5. 強制校時後確認 `System clock synchronized: yes`
> 6. 重新執行加入網域
> → 見〈時間跑掉的後果〉與〈常見錯誤與排錯〉相關列 ★★★★★

---

## 延伸閱讀

- [[050-01-02-01-svc-Workstation-安裝與授權]] — Host 端安裝與 Hyper-V 衝突處理
- [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] — 先有 VM 才有 Tools
- [[050-01-02-03-guide-Workstation-快照與複製]] — 裝好 Tools 後做的第一個乾淨快照
- [[050-01-02-04-guide-Workstation-網路模式]] — 共享資料夾不走網路，但其他東西走
- [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] — 磁碟壓縮、巢狀虛擬化與完整排錯表
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] — 半虛擬化驅動為什麼比模擬裝置快
- [[020-01-17-cmd-Linux-systemd服務管理]] — `systemctl`、mount unit 與 automount
- [[020-01-28-cmd-Linux-時間同步NTP與chrony]] — chrony 的完整設定與判讀
- [[050-01-03-01-svc-PVE-安裝與初始設定]] — 換到 Type-1 平台後，對應的是 QEMU Guest Agent
