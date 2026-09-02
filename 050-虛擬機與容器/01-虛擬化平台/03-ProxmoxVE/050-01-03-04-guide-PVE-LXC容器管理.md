---
title: "PVE LXC 容器管理"
desc: "LXC 與 VM 的取捨、特權與非特權容器的安全差異、範本下載、資源限制、bind mount 的 UID 對應、在 LXC 裡跑 Docker 的注意事項與備份遷移"
aliases: [pct, LXC, 非特權容器, unprivileged container, pveam, bind mount, nesting]
tags: [群組/虛擬機與容器, 虛擬化/pve, 主題/虛擬化]
category: 虛擬化平台
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-03-01-svc-PVE-安裝與初始設定]]", "[[050-01-03-02-guide-PVE-儲存設定]]", "[[050-01-01-01-guide-虛擬化-虛擬化概念與選型]]"]
updated: 2026-09-02
---

# PVE LXC 容器管理

> [!abstract] 這篇你會學到
> - 講清楚 **LXC 與 VM 到底差在哪**：共用核心換來的好處與付出的代價
> - ★★★★ 用一張表決定「**這個服務該放 LXC 還是該開 VM**」，不要憑感覺
> - ★★★★ 徹底搞懂 **特權容器（privileged）與非特權容器（unprivileged）的安全差異**，
>   以及為什麼 Proxmox 官方說「特權容器不是安全邊界」
> - 用 `pveam` 下載範本、用 `pct create` 一行建出容器，並看懂 `/etc/pve/lxc/<VMID>.conf`
> - 設定 **CPU／記憶體／磁碟／I-O 資源限制**，避免一個容器吃垮整台節點
> - ★★★★★ **bind mount 掛主機目錄**：非特權容器的 **UID 位移 100000** 是最多人踩的坑，
>   本篇把 `/etc/subuid`、`/etc/subgid`、`lxc.idmap` 三者的關係一次講完
> - ★★★★ **巢狀容器**：在 LXC 裡跑 Docker 要開哪些 feature、哪些儲存後端會出事
> - 容器的**快照、備份、克隆與跨節點遷移**

> [!warning] 未實機驗證
> 本篇**以 Proxmox VE 8 為例**（cgroup v2、`pct` 指令集）。
> PVE 大版本之間 LXC 的預設值與 feature 旗標會變動，
> 例如 cgroup v1 → v2 的切換就影響過一批舊範本的相容性。
>
> ★★★★★ **文中的指令輸出是「典型長相」，不是你那台機器的實際輸出**：
> 版本號、範本檔名（`debian-12-standard_12.x-1_amd64.tar.zst` 的 `x`）、
> 磁碟大小、UUID 都會不同。上線前務必在你自己的測試節點跑過一遍，
> 並以 `man pct`、`pct help create` 與節點上的 `pveam available` 為準。

## 前置知識

- [[050-01-03-01-svc-PVE-安裝與初始設定]] — 本篇假設你已經有一台可以登入的 PVE 節點
- [[050-01-03-02-guide-PVE-儲存設定]] — ★★★★ **容器 rootfs 放哪裡決定了你能不能做快照**，這是本篇的前提
- [[050-01-03-03-guide-PVE-虛擬機管理]] — VM 那一側的操作，本篇會不斷跟它對照
- [[050-01-01-01-guide-虛擬化-虛擬化概念與選型]] — 全虛擬化／半虛擬化／作業系統層虛擬化的分類
- [[020-01-08-cmd-Linux-檔案權限與擁有者]] — ★★★★ **UID／GID 與 `chown` 一定要先熟**，否則 bind mount 那一節會看不懂
- [[020-01-09-cmd-Linux-使用者與群組管理]] — `/etc/passwd`、`/etc/subuid` 的格式
- [[020-01-17-cmd-Linux-systemd服務管理]] — 容器內外都會用到 `systemctl`
- [[050-02-01-01-svc-Docker-容器概念與Docker安裝]] — 應用容器的觀念，跟 LXC 的「系統容器」是兩件事

---

## 觀念說明

### ★★★★★ 一句話講完差別：VM 帶自己的核心，LXC 借主機的核心

```
┌──────────────── VM（KVM / QEMU）────────────────┐   ┌──────────── LXC 容器 ────────────┐
│                                                 │   │                                  │
│  應用程式  nginx / php-fpm / mysql              │   │  應用程式  nginx / php-fpm       │
│  ────────────────────────────────               │   │  ────────────────────────────    │
│  systemd、glibc、套件庫（完整發行版使用者空間）  │   │  systemd、glibc、套件庫          │
│  ────────────────────────────────               │   │  ────────────────────────────    │
│  ★ Guest Kernel（自己的 Linux 核心）            │   │       ✗ 沒有自己的核心           │
│  ────────────────────────────────               │   │                                  │
│  虛擬硬體（virtio 網卡／磁碟／CPU）              │   │  namespace + cgroup + seccomp    │
└────────────────────┬────────────────────────────┘   └──────────────┬───────────────────┘
                     │                                               │
                     ▼                                               ▼
        ┌────────────────────────────────────────────────────────────────────┐
        │            ★★★★★ 主機（PVE 節點）的 Linux Kernel                   │
        │            —— LXC 容器裡跑的每一個 syscall，都是這顆核心處理的      │
        └────────────────────────────────────────────────────────────────────┘
```

★★★★★ **「共用核心」這四個字同時解釋了 LXC 的所有優點與所有缺點。**

| 面向 | 因為共用核心，所以… | 分類 |
| --- | --- | --- |
| ★★★ 開機速度 | 不用跑 BIOS／GRUB／核心初始化，**1～3 秒就起來** | 優點 |
| ★★★ 記憶體 | 沒有 guest kernel、沒有 guest page cache 重複，**同樣負載省 200～500 MB 起跳** | 優點 |
| ★★★ 磁碟 | rootfs 是主機檔案系統上的一個 subvol／raw 檔，**沒有第二層檔案系統的放大效應** | 優點 |
| ★★★ I-O 與網路 | 少一層虛擬硬體模擬，**接近原生效能** | 優點 |
| ★★ 密度 | 同一台節點塞 3～5 倍數量的服務 | 優點 |
| ★★★★ 核心版本 | ★ **容器無法選自己的核心版本**，主機是 6.8 就大家都是 6.8 | 缺點 |
| ★★★★ 核心模組 | 容器內 `modprobe` 基本上不能用，要載模組請在**主機**載 | 缺點 |
| ★★★★★ 隔離強度 | ★ **核心漏洞 = 逃逸風險**，隔離強度天生弱於 VM | 缺點 |
| ★★★★ 作業系統 | 只能跑 Linux。**Windows、FreeBSD 一律得開 VM** | 缺點 |
| ★★★ 特殊功能 | 自訂 `sysctl`、自己的防火牆規則、iSCSI initiator、掛 NFS 都受限 | 缺點 |
| ★★★ 遷移 | ★ **沒有真正的線上遷移（live migration）**，只有「關機→搬→開機」 | 缺點 |

> [!note] LXC 是「系統容器」，Docker 是「應用容器」★★★
> 兩者都用 namespace + cgroup，但**目標不同**：
>
> | | LXC（PVE 用的） | Docker |
> | --- | --- | --- |
> | 裡面跑什麼 | 一整套發行版，**PID 1 是 systemd** | 通常**一個程序**，PID 1 就是那支程式 |
> | 心智模型 | 「一台很輕的機器」 | 「一個可拋棄的程序封裝」 |
> | 生命週期 | 長期存在，會 `apt upgrade` | 隨時砍掉重建，改設定就重新 build 映像 |
> | 狀態 | 有狀態，資料放 rootfs | 無狀態優先，資料放 volume |
> | 你會怎麼進去 | `pct enter` 然後像平常一樣操作 | `docker exec`，而且不鼓勵手動改 |
>
> ★★★★ **不要用 LXC 的方式管 Docker，也不要用 Docker 的方式管 LXC。**
> 把 LXC 當成「省資源的 VM」來管理，是最不容易出事的心態。

### ★★★★ 決策表：這個服務該放 LXC 還是 VM

直接照表走，有任何一列落在「必須 VM」就開 VM。

| 情境 | 建議 | 理由 |
| --- | --- | --- |
| ★★★ 內部 DNS／DHCP、Pi-hole、Unbound | **LXC** | 純使用者空間服務，資源需求小，重開快 |
| ★★★ 反向代理 Nginx／Apache | **LXC** | 效能接近原生，記憶體省 |
| ★★★ PHP-FPM 應用（Laravel 等） | **LXC** | 同上，且方便一應用一容器 |
| ★★★ MySQL／PostgreSQL（中小型） | **LXC**（但見下方警語） | I-O 少一層，效能好 |
| ★★★ Redis、Memcached | **LXC** | 記憶體型服務最吃「不要多一層 guest kernel」 |
| ★★★ 監控 agent、log 收集、Zabbix Proxy | **LXC** | 輕量常駐 |
| ★★★ 內部 Git、Wiki、檔案分享 | **LXC** | 一般服務 |
| ★★★★ **Windows 任何版本** | ★★★★★ **必須 VM** | LXC 只跑 Linux |
| ★★★★ **OPNsense／pfSense／VyOS 等 BSD 或特製系統** | ★★★★★ **必須 VM** | 非 Linux 核心 |
| ★★★★ **Kubernetes worker node** | **VM** | 需要自己的核心參數、CNI 大量操作 netfilter，LXC 內問題多 |
| ★★★★ **要載自訂核心模組**（WireGuard 舊版、DKMS、ZFS） | **VM** | 容器不能載模組 |
| ★★★★ **要調 `sysctl` 中非 namespaced 的參數** | **VM** | 改了會影響主機或根本改不動 |
| ★★★★ **要 GPU／PCIe 直通給獨佔用途** | **VM** | 見 [[050-01-03-10-guide-PVE-硬體直通與GPU]] |
| ★★★★★ **不受信任的租戶／第三方廠商自行操作** | ★★★★★ **必須 VM** | 隔離強度是關鍵，見下一節 |
| ★★★★ **需要 live migration 零中斷** | **VM** | LXC 沒有真正的線上遷移 |
| ★★★★ **需要與主機不同的核心版本**（測試舊核心、驗證 CVE） | **VM** | 共用核心做不到 |
| ★★★ Docker 主機（跑一堆 compose 專案） | ★★★★ **建議 VM**，能接受風險再用 LXC | 見「巢狀容器」一節 |
| ★★★★ 資料庫需要 **O_DIRECT／大量 fsync 的嚴格保證**、或原廠只支援特定 OS | **VM** | 支援性與可預期性 |

> [!tip] 一個好用的判斷句 ★★★★
> 問自己兩個問題：
> 1. **「它需要動核心嗎？」**（載模組、改 sysctl、跑不同核心版本）→ 需要就開 VM。
> 2. **「它壞掉或被打進去，我能接受它離主機只有一層核心嗎？」**→ 不能接受就開 VM。
>
> 兩題都是「否」→ **放心用 LXC**，你會省下大量記憶體與開機時間。

### ★★★★★ 特權容器與非特權容器：本篇最重要的一節

這是 PVE 建立容器時那個「Unprivileged container」勾勾背後的全部意義。

#### 差別的本質：UID 對應

```
【特權容器 privileged】 unprivileged: 0
┌──────────────────────────┐
│ 容器內 root  UID = 0     │
└────────────┬─────────────┘
             │  ★★★★★ 直接對應
             ▼
┌──────────────────────────┐
│ 主機上      UID = 0      │   ← 就是主機的 root
└──────────────────────────┘
   靠 AppArmor、seccomp、capability drop 擋住危險操作
   ★★★★★ 只要這幾道防線有一個被繞過 → 主機直接淪陷

【非特權容器 unprivileged】 unprivileged: 1（PVE 8 建立時的預設）
┌──────────────────────────┐
│ 容器內 root  UID = 0     │
│ 容器內 www-data UID = 33 │
└────────────┬─────────────┘
             │  ★★★★★ 位移 100000（user namespace）
             ▼
┌──────────────────────────┐
│ 主機上      UID = 100000 │   ← 一個什麼權限都沒有的普通 UID
│ 主機上      UID = 100033 │
└──────────────────────────┘
   ★★★★★ 就算容器內 root 逃出來，在主機眼中也只是 UID 100000
```

#### 兩者的實務差異對照 ★★★★★

| 項目 | 特權容器 | 非特權容器 |
| --- | --- | --- |
| ★★★★★ 官方定位 | **「不視為安全邊界」**（not considered a security boundary） | 建議的預設做法 |
| ★★★★★ 逃逸後果 | 容器 root ≒ **主機 root**，整台節點淪陷 | 只是主機上的 UID 100000，破壞力有限 |
| ★★★★ 主機上檔案的擁有者 | 顯示為 `root`／原本的 UID | 顯示為 `100000`／`100033`（**看起來很奇怪但正常**） |
| ★★★★ bind mount 主機目錄 | 直接可寫 | ★★★★★ **要處理 UID 對應，本篇最大的坑** |
| ★★★ 掛 NFS／CIFS | 加 `mount=nfs` feature 可行 | 預設不行，需 `mount` feature 且限 `root@pam` |
| ★★★ FUSE | 可行 | 需 `fuse=1` feature |
| ★★★ 建立 device node | 可以 | **不行**（`mknod` 被擋） |
| ★★★ 裝置直通（USB／GPU） | 相對容易 | 要額外處理 group 與 idmap，麻煩 |
| ★★★ 舊範本相容性 | 較好 | 少數老舊映像會踩到權限問題 |

> [!danger] ★★★★★ 什麼時候才可以用特權容器
> 只有在**全部**滿足時才考慮：
> 1. 這台節點與這個容器**都在你完全掌控的內部管理網段**，
> 2. 容器內**沒有對外服務**（不對 Internet 開埠、不跑使用者上傳的程式碼），
> 3. 你確實遇到非特權容器做不到的需求（例如某種裝置存取），而且**已經確認沒有替代方案**，
> 4. 你在文件裡記下了「這是特權容器」與**為什麼**。
>
> ★★★★★ **只要容器會對外服務（Web、API、任何使用者可觸及的介面），一律用非特權容器。**
> 對外服務又需要特權功能的話，答案不是「開特權容器」，答案是「**改開 VM**」。

> [!warning] ★★★★★ 建好之後不能直接切換
> `unprivileged` 這個旗標**不是改一行設定就能翻轉的**。
> 從特權改成非特權，rootfs 上所有檔案的 UID／GID 都要整批位移；
> 官方支援的做法是：**備份 → 還原時建成另一種類型**（見 [[050-01-03-06-svc-PVE-備份與還原]]），
> 而不是手改 `/etc/pve/lxc/<VMID>.conf`。
> ★★★★★ 直接把設定檔的 `unprivileged: 1` 改成 `0` 會得到一個**權限全錯、開不起來或行為詭異的容器**。

### 容器的檔案長在哪裡 ★★★

| 東西 | 路徑 | 說明 |
| --- | --- | --- |
| ★★★★ 容器設定檔 | `/etc/pve/lxc/<VMID>.conf` | 在 **pmxcfs**（叢集檔案系統）上，叢集內同步 |
| ★★★ 範本快取 | `/var/lib/vz/template/cache/` | `pveam download local ...` 下載到這裡 |
| ★★★ rootfs（dir 儲存） | `/var/lib/vz/images/<VMID>/vm-<VMID>-disk-0.raw` | 一個含 ext4 的 raw 檔 |
| ★★★ rootfs（ZFS 儲存） | `rpool/data/subvol-<VMID>-disk-0` | 是 **dataset（subvol）**，不是 zvol |
| ★★★ rootfs（LVM-thin） | `/dev/pve/vm-<VMID>-disk-0` | thin LV |
| ★★ 容器日誌 | `/var/log/pve/tasks/` | 建立／啟動／備份的任務日誌 |
| ★★ AppArmor profile | `lxc-container-default-cgns`（預設套用） | 見 [[090-02-07-guide-防護-SELinux與AppArmor]] |
| ★★★ UID 對應範圍 | `/etc/subuid`、`/etc/subgid` | 預設 `root:100000:65536` |

> [!note] ★★★ ZFS 上的容器 rootfs 是 dataset，不是 zvol
> 這件事有兩個實務後果：
> - **好處**：`zfs list` 直接看得到用量、快照很便宜、可以在主機上直接 `ls` 進去看檔案。
> - **要注意**：容器內看到的「磁碟大小」是 ZFS 的 `refquota`，
>   `pct resize` 改的是 quota，不是真的重新分割。
>   ZFS 觀念見 [[020-01-24-guide-進階儲存-ZFS與Btrfs]]。

---

## 安裝或基礎操作

PVE 安裝好之後 LXC 功能就已經在了，不用另外裝套件。以下從「拿到範本」開始。

### 1. 更新並瀏覽範本清單 ★★★

```bash
# 更新 appliance 清單（第一次一定要跑）
pveam update
```

```text
update successful
```

```bash
# 看有哪些系統範本
pveam available --section system
```

```text
system          almalinux-9-default_20240911_amd64.tar.xz
system          alpine-3.20-default_20240908_amd64.tar.xz
system          archlinux-base_20240911-1_amd64.tar.zst
system          debian-11-standard_11.7-1_amd64.tar.zst
system          debian-12-standard_12.7-1_amd64.tar.zst
system          fedora-40-default_20240909_amd64.tar.xz
system          rockylinux-9-default_20240912_amd64.tar.xz
system          ubuntu-22.04-standard_22.04-1_amd64.tar.zst
system          ubuntu-24.04-standard_24.04-2_amd64.tar.zst
```

> [!warning] ★★★ 上面的版本號會隨時間改變
> 你跑出來的檔名幾乎一定跟本篇不同。
> **永遠用你自己 `pveam available` 的輸出去複製檔名**，不要照抄本篇的字串，
> 抄錯會得到 `no such volume`。

其他 section：

```bash
pveam available --section turnkeylinux | head -5
```

```text
turnkeylinux    debian-12-turnkey-nextcloud_18.0-1_amd64.tar.gz
turnkeylinux    debian-12-turnkey-wordpress_18.0-1_amd64.tar.gz
turnkeylinux    debian-12-turnkey-gitlab_18.0-1_amd64.tar.gz
turnkeylinux    debian-12-turnkey-fileserver_18.0-1_amd64.tar.gz
turnkeylinux    debian-12-turnkey-mysql_18.0-1_amd64.tar.gz
```

> [!tip] ★★★ TurnKey 範本適合快速起 demo，不適合正式環境
> 它把應用預先裝好，方便，但**你不知道它裝了什麼、預設密碼是什麼、更新政策是什麼**。
> 機關正式服務請用 `standard` 範本自己裝，流程才可稽核。

### 2. 下載範本 ★★★

```bash
pveam download local debian-12-standard_12.7-1_amd64.tar.zst
```

```text
downloading http://download.proxmox.com/images/system/debian-12-standard_12.7-1_amd64.tar.zst to /var/lib/vz/template/cache/debian-12-standard_12.7-1_amd64.tar.zst
--2026-09-02 10:11:02--  http://download.proxmox.com/images/system/debian-12-standard_12.7-1_amd64.tar.zst
Length: 128574239 (123M) [application/octet-stream]
Saving to: '/var/lib/vz/template/cache/debian-12-standard_12.7-1_amd64.tar.zst.tmp.1836'
100%[==================================>] 122.62M  18.4MB/s    in 6.9s
download of 'http://download.proxmox.com/images/system/debian-12-standard_12.7-1_amd64.tar.zst' to '/var/lib/vz/template/cache/debian-12-standard_12.7-1_amd64.tar.zst' finished
```

確認：

```bash
pveam list local
```

```text
NAME                                                         SIZE
local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst         122.62MB
```

> [!note] ★★★ 範本只能放在有 `vztmpl` 內容類型的儲存
> `local`（目錄型）預設就有。若你在 `pveam download` 指定了不支援的儲存會被拒絕。
> 儲存的 content 設定見 [[050-01-03-02-guide-PVE-儲存設定]]。

### 3. 建立第一個非特權容器 ★★★★

```bash
pct create 201 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname web-lxc01 \
  --unprivileged 1 \
  --cores 2 \
  --memory 2048 \
  --swap 512 \
  --rootfs local-lvm:16 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.10.201/24,gw=192.168.10.254,firewall=1 \
  --nameserver 192.168.10.10 \
  --searchdomain lan.example.gov.tw \
  --onboot 1 \
  --features nesting=1 \
  --password
```

```text
Enter password for the container root user: ********
Retype password: ********
extracting archive '/var/lib/vz/template/cache/debian-12-standard_12.7-1_amd64.tar.zst'
Total bytes read: 421406720 (402MiB, 195MiB/s)
Detected container architecture: amd64
Creating SSH host key 'ssh_host_ed25519_key' ...done
Creating SSH host key 'ssh_host_rsa_key' ...done
Creating SSH host key 'ssh_host_ecdsa_key' ...done
```

**逐項說明**：

| 參數 | 意義 | 重要度 |
| --- | --- | --- |
| `201` | VMID，**全叢集唯一**，VM 與容器共用同一組編號空間 | ★★★ |
| `local:vztmpl/...` | 範本的 volume id，格式是 `<儲存>:vztmpl/<檔名>` | ★★★ |
| `--unprivileged 1` | ★★★★★ **非特權容器**。習慣明寫，不要依賴預設 | ★★★★★ |
| `--rootfs local-lvm:16` | 在 `local-lvm` 配 16 GiB 給 rootfs | ★★★★ |
| `--net0 ...` | 第一張網卡；`firewall=1` 才會套用 PVE 防火牆 | ★★★★ |
| `--onboot 1` | 節點開機時自動啟動 | ★★★ |
| `--features nesting=1` | 允許容器內再跑 namespace（systemd 較穩、Docker 前提） | ★★★★ |
| `--password` | 互動輸入 root 密碼；**不要**寫在指令列上（會進 shell history） | ★★★★ |

> [!tip] ★★★★ 用 SSH 公鑰取代密碼
> ```bash
> pct create 201 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
>   --hostname web-lxc01 --unprivileged 1 \
>   --ssh-public-keys /root/.ssh/authorized_keys \
>   ...其他參數同上
> ```
> 這樣建出來的容器**沒有可用的 root 密碼**，只能用金鑰登入，安全性更好。

### 4. 啟動與進入 ★★★

```bash
pct start 201
pct status 201
```

```text
status: running
```

```bash
# 進到容器裡（等同在容器內開一個 root shell）
pct enter 201
```

```text
root@web-lxc01:~#
```

離開用 `exit` 或 `Ctrl-D`。

```bash
# 不進去，只跑一條指令
pct exec 201 -- hostname -I
```

```text
192.168.10.201
```

```bash
# 接到容器的 console（看得到 systemd 開機訊息，離開是 Ctrl-a q）
pct console 201
```

> [!note] ★★★ `pct enter` 與 `pct console` 差在哪
> - `pct enter`：從主機直接 attach 一個 shell 進去，**不需要容器內的 getty，也不用登入**。網路壞掉照樣進得去。
> - `pct console`：接到容器的虛擬終端機，**會看到登入提示**，行為像接了螢幕鍵盤。
>
> ★★★★ 排錯時優先用 `pct enter`，它對容器狀態的依賴最少。

### 5. 常用生命週期指令 ★★★

```bash
pct list
```

```text
VMID       Status     Lock         Name
201        running                 web-lxc01
202        stopped                 db-lxc01
```

```bash
pct shutdown 201          # 送 ACPI-like 的正常關機，等容器自己收尾
pct stop 201              # ★★★ 直接砍掉，等同拔電，會有資料不一致風險
pct reboot 201
pct destroy 201           # ★★★★★ 刪除容器與 rootfs，不可逆
```

> [!danger] ★★★★★ `pct destroy` 沒有確認提示
> 打下去就沒了，`rootfs` 一併刪除。
> **刪之前先 `pct list` 對一次 VMID 與 hostname**，
> 而且刪之前先確認 [[050-01-03-06-svc-PVE-備份與還原]] 裡的備份確實存在。

### 6. 看懂設定檔 ★★★★

```bash
cat /etc/pve/lxc/201.conf
```

```ini
arch: amd64
cores: 2
features: nesting=1
hostname: web-lxc01
memory: 2048
nameserver: 192.168.10.10
net0: name=eth0,bridge=vmbr0,firewall=1,gw=192.168.10.254,hwaddr=BC:24:11:3A:7C:91,ip=192.168.10.201/24,type=veth
onboot: 1
ostype: debian
rootfs: local-lvm:vm-201-disk-0,size=16G
searchdomain: lan.example.gov.tw
swap: 512
unprivileged: 1
```

| 欄位 | 說明 | 重要度 |
| --- | --- | --- |
| `arch` | 容器架構，跟主機一致 | ★ |
| `ostype` | PVE 用來決定怎麼改網路設定檔（Debian 改 `/etc/network/interfaces`，RHEL 系改 `ifcfg-*`） | ★★★ |
| `features` | `nesting` / `keyctl` / `fuse` / `mount` | ★★★★ |
| `rootfs` | volume id + `size=` | ★★★★ |
| `mp0`…`mp255` | 額外掛載點（下面會大講） | ★★★★ |
| `unprivileged` | ★★★★★ **1 = 非特權**，建好後不要手改 | ★★★★★ |
| `lxc.*` | 直接寫進 LXC 原生設定的逃生門，例如 `lxc.idmap` | ★★★★ |

> [!warning] ★★★★ 改設定檔的正確方式
> 能用 `pct set` 就用 `pct set`：
> ```bash
> pct set 201 --memory 4096 --cores 4
> ```
> ```text
> update VM 201: -cores 4 -memory 4096
> ```
> 手動 `vi /etc/pve/lxc/201.conf` 只用在 `lxc.` 開頭那種 `pct set` 不支援的鍵。
> ★★★ `/etc/pve` 是 **pmxcfs**，寫入會即時同步到叢集其他節點；
> 但它**不接受任意檔案**，不要在裡面放備份副本（`cp 201.conf 201.conf.bak` 可能被拒絕或造成混淆），
> 要留底就複製到 `/root/`。

---

## 進階應用

### 資源限制：CPU ★★★★

三個參數，常被搞混：

| 參數 | 意義 | 典型值 | 重要度 |
| --- | --- | --- | --- |
| `cores` | 容器**看得到幾顆 CPU**（限制可用核心數） | `2` | ★★★★ |
| `cpulimit` | ★ **總量上限**，`1.0` = 一顆核心的算力，可小數 | `1.5` | ★★★★ |
| `cpuunits` | ★ **相對權重**，只有在 CPU 搶不夠時才生效 | 預設 `100`（cgroup v2 語意） | ★★★ |

```bash
pct set 201 --cores 4 --cpulimit 2 --cpuunits 100
```

```text
update VM 201: -cores 4 -cpulimit 2 -cpuunits 100
```

> [!note] ★★★★ `cores` 與 `cpulimit` 要一起看
> - 只設 `cores 4`：容器可以把 4 顆核心吃滿。
> - 設 `cores 4` + `cpulimit 2`：容器**看得到 4 顆**（多執行緒程式排程比較好），
>   但**總算力不會超過 2 顆**。
>
> ★★★★ 機關環境建議的做法是「`cores` 給寬鬆一點、`cpulimit` 卡總量」，
> 這樣單一容器暴衝時不會拖垮整台節點，程式又不會因為只看到 1 顆核心而退化。

### 資源限制：記憶體與 swap ★★★★

```bash
pct set 201 --memory 2048 --swap 512
```

容器內看到的記憶體：

```bash
pct exec 201 -- free -m
```

```text
               total        used        free      shared  buff/cache   available
Mem:            2048         146        1798           0         103        1901
Swap:            512           0         512
```

> [!warning] ★★★★★ LXC 的 swap 不是主機的 swap
> `--swap` 走的是 cgroup 的 memory+swap 限制。
> ★★★★★ **如果主機本身沒有 swap（很多 PVE 節點刻意不開），
> 那容器的 `--swap` 設多少都沒用**，超過 `memory` 就直接 OOM kill。
>
> 症狀：容器內服務被莫名其妙殺掉，主機 `dmesg` 出現
> ```text
> Memory cgroup out of memory: Killed process 18234 (mysqld) total-vm:...
> ```
> ★★★★ 對記憶體敏感的服務（MySQL、Redis、Java）**寧可把 `memory` 給足**，不要指望 swap。

### 資源限制：磁碟與 I-O ★★★★

擴大 rootfs（**只能加大，不能縮小**）：

```bash
pct resize 201 rootfs +8G
```

```text
Size of logical volume pve/vm-201-disk-0 changed from 16.00 GiB (4096 extents) to 24.00 GiB (6144 extents).
Logical volume pve/vm-201-disk-0 successfully resized.
resize2fs 1.47.0 (5-Feb-2023)
Filesystem at /dev/pve/vm-201-disk-0 is mounted on /var/lib/lxc/201/rootfs; on-line resizing required
The filesystem on /dev/pve/vm-201-disk-0 is now 6291456 (4k) blocks long.
```

```bash
pct df 201
```

```text
MP     Volume                    Size   Used  Avail Use% Path
rootfs local-lvm:vm-201-disk-0  23.5G  1.4G  20.9G   7% /
```

> [!danger] ★★★★★ 縮小 rootfs 沒有安全做法
> `pct resize` 只支援加大。想縮小的正確流程是
> **備份 → 用較小的 rootfs 重建容器 → 還原資料**，
> 直接對底層 LV／zvol 動刀會毀掉檔案系統。

I-O 限制（掛載點層級）：

```bash
# 給 rootfs 限制讀寫頻寬與 IOPS
pct set 201 --rootfs local-lvm:vm-201-disk-0,size=24G,mbps_rd=100,mbps_wr=50
```

| 旗標 | 意義 | 重要度 |
| --- | --- | --- |
| `mbps_rd` / `mbps_wr` | 讀／寫頻寬上限（MB/s） | ★★★ |
| `mbps_rd_max` / `mbps_wr_max` | 允許的突發峰值 | ★★ |
| `iops_rd` / `iops_wr` | 讀／寫 IOPS 上限 | ★★★ |

> [!tip] ★★★★ 什麼時候該限 I-O
> 典型場景：某個容器每晚跑 `tar` 備份或 `apt upgrade`，
> 把共用的 SSD 佔滿，導致同節點的資料庫容器延遲飆高。
> ★★★ 對「會做批次作業的容器」限 I-O，比對「重要服務」加優先權更有效。

### ★★★★★ bind mount：把主機目錄掛進容器

這是 LXC 最好用的功能，也是**最多人踩坑的地方**。

#### 兩種掛載點要先分清楚 ★★★★

```bash
# (A) 一般掛載點：由 PVE 從儲存配一顆新磁碟給容器
pct set 201 --mp0 local-lvm:32,mp=/var/www

# (B) bind mount：把「主機上既有的目錄」掛進容器
pct set 201 --mp1 /srv/share/web,mp=/data/web
```

| | (A) 儲存型掛載點 | (B) bind mount |
| --- | --- | --- |
| 來源 | `<儲存>:<大小>` | **主機的絕對路徑** | 
| ★★★★ 會被 `vzdump` 備份嗎 | **會**（除非加 `backup=0`） | ★★★★★ **不會，永遠不會** |
| ★★★★ 支援快照嗎 | 看儲存後端 | ★★★★★ **不支援，會讓整台容器無法做快照** |
| 支援遷移嗎 | 會跟著搬 | ★★★★ **不會**，目標節點要自己準備好同路徑 |
| 典型用途 | 應用資料、資料庫檔 | 共享大容量（NAS 掛載、媒體庫、多容器共用素材） |

> [!danger] ★★★★★ bind mount 不會被備份，這是最常見的資料遺失原因
> 有人把資料庫的 datadir bind mount 到 `/srv/mysql`，
> 每天 `vzdump` 跑得好好的，**還原之後發現資料庫是空的** —— 因為 bind mount 從來沒進過備份檔。
>
> ★★★★★ **規則：容器的「不可再生資料」不要放在 bind mount 上**，
> 放在儲存型掛載點（會被備份），或另外對主機目錄做獨立備份。
> 詳見 [[050-01-03-06-svc-PVE-備份與還原]]。

> [!warning] ★★★★ bind mount 會讓快照選項消失
> 容器只要有任一個 bind mount，PVE 的「Take Snapshot」就會失敗：
> ```text
> TASK ERROR: unable to snapshot container - snapshot feature is not available for bind mounts
> ```
> ★★★ 想保留快照能力，就別用 bind mount，改用儲存型掛載點。

#### ★★★★★ 非特權容器的 UID 位移坑

**現象**：你在主機上建了一個目錄，bind mount 進非特權容器，容器內卻寫不進去。

```bash
# 主機上
mkdir -p /srv/share/web
chown -R www-data:www-data /srv/share/web
ls -ln /srv/share/web
```

```text
total 0
```

```bash
ls -lnd /srv/share/web
```

```text
drwxr-xr-x 2 33 33 4096 Sep  2 10:40 /srv/share/web
```

掛進容器後：

```bash
pct set 201 --mp1 /srv/share/web,mp=/data/web
pct reboot 201
pct exec 201 -- ls -lnd /data/web
```

```text
drwxr-xr-x 2 65534 65534 4096 Sep  2 10:40 /data/web
```

★★★★★ **容器裡看到的是 `65534`（nobody）**，因為：

```
主機 UID 33  ──（非特權容器的對應是「主機 100000+N ↔ 容器 N」）──►  不在對應範圍內
                                                                     ↓
                                                          容器只好顯示 nobody(65534)
                                                          → 容器內任何使用者都寫不進去
```

**正確的三種解法**：

**解法一（最簡單，★★★★ 推薦給大多數情況）：在主機上把擁有者設成位移後的 UID**

容器內想讓 `www-data`（UID 33）能寫，主機上就要 `chown 100033`：

```bash
# 主機上
chown -R 100033:100033 /srv/share/web
ls -lnd /srv/share/web
```

```text
drwxr-xr-x 2 100033 100033 4096 Sep  2 10:42 /srv/share/web
```

```bash
pct exec 201 -- ls -lnd /data/web
```

```text
drwxr-xr-x 2 33 33 4096 Sep  2 10:42 /data/web
```

```bash
pct exec 201 -- sudo -u www-data touch /data/web/ok
pct exec 201 -- ls -l /data/web/ok
```

```text
-rw-r--r-- 1 www-data www-data 0 Sep  2 10:43 /data/web/ok
```

★★★★★ **公式：主機 UID = 100000 + 容器 UID**（在預設的 65536 大小對應下）。

| 容器內身分 | 容器 UID | ★★★★ 主機上要 chown 成 |
| --- | --- | --- |
| root | 0 | `100000` |
| www-data（Debian） | 33 | `100033` |
| mysql（Debian） | 沒有固定值，**要進容器查** | `100000 + 實際 UID` |
| 你自己建的 appuser | 例如 1000 | `101000` |

```bash
# ★★★★ 千萬不要用猜的，進容器查
pct exec 201 -- id -u www-data
```

```text
33
```

**解法二（★★★★ 多容器共用同一份資料時最好用）：用共用群組**

```bash
# 主機上：建一個共用 GID，例如 10100
groupadd -g 110100 lxcshare 2>/dev/null || true
chown -R root:110100 /srv/share/web
chmod -R 2775 /srv/share/web        # setgid，新建檔案自動繼承群組
```

容器內對應到 GID 10100，把服務帳號加進去：

```bash
pct exec 201 -- groupadd -g 10100 lxcshare
pct exec 201 -- usermod -aG lxcshare www-data
pct exec 201 -- id www-data
```

```text
uid=33(www-data) gid=33(www-data) groups=33(www-data),10100(lxcshare)
```

**解法三（★★★★★ 最精準也最容易寫錯）：自訂 `lxc.idmap`，讓某一段 UID 不位移**

情境：主機上 `/srv/share/web` 已經是 `www-data`（UID 33）擁有，
你**不想動主機的權限**（例如它同時被主機上的 Nginx 使用），
就讓容器的 UID 33 直接對應到主機的 UID 33。

★★★★★ 這需要**同時**改兩個地方：

```bash
# 1) 主機 /etc/subuid、/etc/subgid：允許 root 使用 UID 33 這一格
grep -n . /etc/subuid /etc/subgid
```

```text
/etc/subuid:1:root:100000:65536
/etc/subgid:1:root:100000:65536
```

```bash
printf 'root:33:1\n' >> /etc/subuid
printf 'root:33:1\n' >> /etc/subgid
cat /etc/subuid
```

```text
root:100000:65536
root:33:1
```

```bash
# 2) 容器設定檔加 idmap（把 0~32、33、34~65535 切成三段）
cat >> /etc/pve/lxc/201.conf <<'EOF'
lxc.idmap: u 0 100000 33
lxc.idmap: g 0 100000 33
lxc.idmap: u 33 33 1
lxc.idmap: g 33 33 1
lxc.idmap: u 34 100034 65502
lxc.idmap: g 34 100034 65502
EOF
```

`lxc.idmap` 的欄位是 **`<u|g> <容器起始ID> <主機起始ID> <數量>`**：

| 這一行 | 意思 |
| --- | --- |
| `u 0 100000 33` | 容器 UID 0～32 → 主機 100000～100032 |
| `u 33 33 1` | ★★★★★ 容器 UID 33 → 主機 UID 33（**不位移**） |
| `u 34 100034 65502` | 容器 UID 34～65535 → 主機 100034～165535 |

> [!danger] ★★★★★ idmap 三段必須完整覆蓋 0～65535，一個不漏
> 33 + 1 + 65502 = 65536。**算錯就開不起來**：
> ```text
> lxc_map_ids: 245 newuidmap failed to write mapping "newuidmap: uid range [33-34) -> [33-34) not allowed"
> lxc_spawn: 1795 Failed to set up id mapping.
> ```
> 出現這個訊息時檢查兩件事：
> 1. 三段數字加起來是不是 65536，
> 2. `/etc/subuid`、`/etc/subgid` 有沒有**同時**加上那一格。
> ★★★★ 只加 `subuid` 忘了 `subgid` 是最常見的失誤。

> [!tip] ★★★★ 該用哪一種解法
> | 情況 | 建議 |
> | --- | --- |
> | 只有這個容器要用這份資料 | ★★★★ **解法一**（chown 到 100000+N），最單純 |
> | 好幾個容器要共用同一份資料 | ★★★★ **解法二**（共用 GID + setgid） |
> | 主機上的服務也要用同一份資料、UID 不能動 | ★★★ **解法三**（idmap），但寫完一定要驗 |
> | 你只是想「趕快能寫」 | ★★★★★ **不要**因此改用特權容器，那是拿安全換方便 |

#### 唯讀 bind mount 與其他選項 ★★★

```bash
# 唯讀掛載（例如把憑證目錄丟進去給 Nginx 讀）
pct set 201 --mp2 /etc/ssl/internal,mp=/etc/ssl/internal,ro=1
```

| 選項 | 意義 | 重要度 |
| --- | --- | --- |
| `ro=1` | 唯讀 | ★★★ |
| `backup=0` | ★★★ 這個掛載點**不進備份**（只對儲存型掛載點有意義） | ★★★★ |
| `acl=1` | 啟用 POSIX ACL | ★★ |
| `replicate=0` | 不參與 ZFS 複寫 | ★★ |
| `shared=1` | 告訴 PVE 這個路徑在每個節點上都存在（影響遷移判斷） | ★★★ |
| `quota=1` | 啟用磁碟配額（**非特權容器不支援**） | ★★ |
| `size=` | 儲存型掛載點的大小 | ★★★ |

### ★★★★ 巢狀容器：在 LXC 裡跑 Docker

先講結論。

> [!warning] ★★★★★ 官方立場與務實立場
> Proxmox 官方文件對「在 LXC 裡跑 Docker」的態度是**不建議**：
> 巢狀化會削弱隔離、儲存驅動組合容易出事、出問題時很難判斷是哪一層的責任。
>
> ★★★★ 但實務上大量機關這樣用（省記憶體、容器開機快）。
> 本節的立場是：**要做可以，但你必須知道你關掉了什麼、以及會踩到什麼。**
> 正式對外服務、或需要原廠支援的環境，**請開一台 VM 專門跑 Docker**。

#### 必要的 feature ★★★★

```bash
pct set 201 --features nesting=1,keyctl=1
```

| feature | 作用 | 不開會怎樣 | 重要度 |
| --- | --- | --- | --- |
| `nesting=1` | 允許容器內再建立 namespace、並掛載 `/proc`、`/sys` 的巢狀視圖 | Docker daemon 根本起不來 | ★★★★★ |
| `keyctl=1` | 允許使用 kernel keyring（非特權容器預設擋掉） | ★★★★ systemd 服務、部分容器會出現 `keyctl` 相關錯誤 | ★★★★ |
| `fuse=1` | 允許 FUSE | 需要 `fuse-overlayfs` 時會失敗 | ★★★ |
| `mount=nfs;cifs` | 允許容器內掛 NFS／CIFS | ★★★★ 只有 `root@pam` 能設，**會顯著降低隔離** | ★★★★ |

> [!danger] ★★★★★ `nesting=1` 的代價要說清楚
> 開了 `nesting` 等於允許容器內部再做 namespace 操作，
> **攻擊面明顯變大**。搭配非特權容器仍然比特權容器安全得多，
> 但已經不是「預設最緊」的狀態。
> ★★★★★ **絕對不要為了跑 Docker 而同時開 `nesting` 又改成特權容器** ——
> 那基本上等於把主機 root 交出去。

#### ★★★★★ 儲存驅動：這裡最容易翻車

| 容器 rootfs 放在 | Docker 預設 `overlay2` 能用嗎 | 建議 |
| --- | --- | --- |
| ★★★ LVM-thin / 目錄型（底下是 ext4） | **通常可以** | ★★★★ 想在 LXC 跑 Docker 就選這個 |
| ★★★★★ **ZFS subvol** | ★★★★★ **通常不行**，overlay2 在 ZFS dataset 上不被支援 | 換 rootfs 儲存，或改用 `fuse-overlayfs` |
| ★★★ Ceph RBD（上面是 ext4/xfs） | 通常可以 | 可行 |

ZFS 上的典型錯誤：

```text
failed to start daemon: error initializing graphdriver: driver not supported: overlay2
```

或是啟動時退回極慢的 `vfs` 驅動，磁碟用量暴增。

★★★★ 兩條可走的路：

```bash
# 路線 A（推薦）：把容器 rootfs 放在 ext4 之上（local-lvm / dir）
# 建容器時就選 --rootfs local-lvm:32

# 路線 B：容器內改用 fuse-overlayfs
pct set 201 --features nesting=1,keyctl=1,fuse=1
pct exec 201 -- apt-get install -y fuse-overlayfs
pct exec 201 -- bash -c 'cat > /etc/docker/daemon.json' <<'EOF'
{
  "storage-driver": "fuse-overlayfs"
}
EOF
pct exec 201 -- systemctl restart docker
pct exec 201 -- docker info --format '{{.Driver}}'
```

```text
fuse-overlayfs
```

> [!warning] ★★★ `fuse-overlayfs` 比 `overlay2` 慢
> 它走使用者空間，映像層很多、檔案很小的工作負載（例如 `npm install`）會明顯感覺到。
> 建置密集的用途請直接用 VM。

#### 驗證 Docker 真的能動 ★★★

```bash
pct exec 201 -- docker run --rm hello-world
```

```text
Hello from Docker!
This message shows that your installation appears to be working correctly.
```

```bash
pct exec 201 -- docker info | sed -n '1,12p'
```

```text
Client: Docker Engine - Community
 Version:    27.x.x
Server:
 Containers: 0
 Images: 1
 Server Version: 27.x.x
 Storage Driver: overlay2
  Backing Filesystem: extfs
  Supports d_type: true
 Cgroup Driver: systemd
 Cgroup Version: 2
```

★★★★ 三個要確認的欄位：`Storage Driver`、`Backing Filesystem`、`Cgroup Version`。
`Backing Filesystem: zfs` 代表你踩在前面那個雷上。

Docker 本身的觀念與安全設定見 [[050-02-01-01-svc-Docker-容器概念與Docker安裝]] 與 [[050-02-01-08-guide-Docker-安全實務]]。

### 快照 ★★★

```bash
pct snapshot 201 before-upgrade --description "apt full-upgrade 前"
```

```text
Logical volume "snap_vm-201-disk-0_before-upgrade" created.
snapshot create finished successfully
```

```bash
pct listsnapshot 201
```

```text
`-> before-upgrade         2026-09-02 11:05:12     apt full-upgrade 前
    `-> current                                     You are here!
```

```bash
pct rollback 201 before-upgrade
```

```text
rollback snapshot
  Logical volume "vm-201-disk-0" successfully removed.
  Logical volume pve/snap_vm-201-disk-0_before-upgrade renamed to vm-201-disk-0
rollback snapshot finished successfully
```

```bash
pct delsnapshot 201 before-upgrade
```

> [!danger] ★★★★★ 快照不是備份
> - 快照跟 rootfs **住在同一顆儲存上**，儲存壞了兩個一起死。
> - 快照**不會**保護你免於「刪掉整個容器」。
> - LVM-thin 的快照佔用 thin pool 空間，★★★★★ **忘記刪快照會把 thin pool 撐爆，
>   整個 pool 上的容器與 VM 一起變唯讀**。
>
> ★★★★ 快照是「我要做一件可能搞砸的事，做完馬上刪掉」的短期保險。
> 長期保護請看 [[050-01-03-06-svc-PVE-備份與還原]]。

### 克隆與轉成範本 ★★★

```bash
# 完整克隆（獨立一份，來源可刪）
pct clone 201 202 --hostname web-lxc02 --full 1
```

```text
create full clone of mountpoint rootfs (local-lvm:vm-201-disk-0)
  Logical volume "vm-202-disk-0" created.
successfully created clone
```

```bash
# 轉成範本，之後可以做連結克隆（linked clone）
pct template 205
pct clone 205 210 --hostname app01
```

> [!warning] ★★★★ 克隆之後一定要改三樣東西
> 1. **hostname**（`pct set 210 --hostname app01`，並確認容器內 `/etc/hostname`、`/etc/hosts`）
> 2. **IP**（靜態 IP 一定會撞）
> 3. ★★★★ **SSH host key 與任何機器唯一識別**：
>    ```bash
>    pct exec 210 -- bash -c 'rm -f /etc/ssh/ssh_host_* && dpkg-reconfigure -f noninteractive openssh-server'
>    pct exec 210 -- bash -c 'rm -f /etc/machine-id && systemd-machine-id-setup'
>    ```
>    忘了做的話，兩台機器 host key 一樣，客戶端的 `known_hosts` 會錯亂，
>    而且 `machine-id` 相同會讓某些 DHCP 伺服器發同一個 IP。

### 跨節點遷移 ★★★★

```bash
pct migrate 201 pve02 --restart
```

```text
2026-09-02 11:30:01 shutdown CT 201
2026-09-02 11:30:09 starting migration of CT 201 to node 'pve02' (10.20.30.12)
2026-09-02 11:30:09 found local volume 'local-lvm:vm-201-disk-0' (in current VM config)
2026-09-02 11:30:09 copying local disk images
...
2026-09-02 11:32:44 start final cleanup
2026-09-02 11:32:45 start CT 201 on target node
2026-09-02 11:32:48 migration finished successfully (duration 00:02:47)
```

| 情況 | 指令 | 中斷時間 |
| --- | --- | --- |
| 容器已停機 | `pct migrate 201 pve02` | 無（本來就停著） |
| ★★★★ 容器在跑，共用儲存 | `pct migrate 201 pve02 --restart` | ★★★ 只有關機＋開機的秒數 |
| ★★★★ 容器在跑，本機儲存 | `pct migrate 201 pve02 --restart` | ★★★★ 加上複製磁碟的時間，可能好幾分鐘 |

> [!danger] ★★★★★ LXC 沒有真正的線上遷移
> `--restart` 的意思就是 **「幫你關機、搬過去、再開機」**，服務**一定會中斷**。
> 需要零中斷請用 VM 的 live migration（見 [[050-01-03-07-svc-PVE-叢集與高可用]]）。
>
> ★★★★ 另外，**bind mount 不會跟著搬**。
> 目標節點沒有同名路徑的話，容器會在對面起不來：
> ```text
> TASK ERROR: unable to open directory '/srv/share/web' - No such file or directory
> ```

### 主機與容器之間傳檔 ★★★

```bash
pct push 201 /root/app.tar.gz /tmp/app.tar.gz --perms 0640 --user 0 --group 0
pct pull 201 /var/log/nginx/error.log /root/lxc201-nginx-error.log
```

```bash
# 容器沒開機時，把 rootfs 掛到主機上檢查／搶救（★★★★ 排錯很好用）
pct mount 201
```

```text
mounted CT 201 in '/var/lib/lxc/201/rootfs'
```

```bash
ls /var/lib/lxc/201/rootfs
```

```text
bin  boot  dev  etc  home  lib  media  mnt  opt  proc  root  run  sbin  srv  sys  tmp  usr  var
```

```bash
pct unmount 201
```

> [!danger] ★★★★★ `pct mount` 之後一定要 `pct unmount`
> 忘了卸載就去 `pct start`，會得到
> ```text
> TASK ERROR: CT is locked (mounted)
> ```
> 而且在容器啟動時同時從主機寫 rootfs，**有機會弄壞檔案系統**。
> ★★★★ 規則：`pct mount` 只用在容器**停機**時，用完立刻 `pct unmount`。

---

## 完整實戰範例

**目標**：在 PVE 8 節點上，為機關內部的檔案共享服務建一個**非特權 LXC 容器**，
把主機上的 NAS 掛載點以 **bind mount** 提供給容器內的 Nginx，
正確處理 UID 對應，設好資源限制，最後做備份並**驗證還原**。

### 情境與規劃

| 項目 | 值 |
| --- | --- |
| 節點 | `pve01` |
| VMID | `210` |
| hostname | `files-lxc01` |
| 範本 | Debian 12 standard |
| 類型 | ★★★★★ **非特權容器** |
| CPU | `cores 2`、`cpulimit 1.5` |
| 記憶體 | 1024 MB + 512 MB swap |
| rootfs | `local-lvm:12`（放在 ext4/LVM-thin，之後要跑 Docker 也不怕） |
| 網路 | `vmbr0`，`192.168.10.210/24`，GW `192.168.10.254` |
| bind mount | 主機 `/srv/files` → 容器 `/data`（★★★★ 唯讀給 Nginx 用） |
| 服務 | Nginx 提供 `/data` 的檔案索引 |

### 步驟 1：主機端準備共享目錄

```bash
mkdir -p /srv/files/pub
echo "hello from host $(date +%F)" > /srv/files/pub/README.txt
ls -ln /srv/files/pub
```

```text
total 4
-rw-r--r-- 1 0 0 30 Sep  2 13:02 README.txt
```

★★★★ 現在擁有者是主機 root（UID 0），**非特權容器內會看到 nobody**。先放著，步驟 5 再處理。

### 步驟 2：確認範本

```bash
pveam update && pveam list local
```

```text
update successful
NAME                                                         SIZE
local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst         122.62MB
```

沒有的話：

```bash
pveam available --section system | grep debian-12
```

```text
system          debian-12-standard_12.7-1_amd64.tar.zst
```

```bash
pveam download local debian-12-standard_12.7-1_amd64.tar.zst
```

### 步驟 3：建立容器

```bash
pct create 210 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname files-lxc01 \
  --unprivileged 1 \
  --cores 2 --cpulimit 1.5 \
  --memory 1024 --swap 512 \
  --rootfs local-lvm:12 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.10.210/24,gw=192.168.10.254,firewall=1 \
  --nameserver 192.168.10.10 \
  --searchdomain lan.example.gov.tw \
  --onboot 1 \
  --start 0 \
  --ssh-public-keys /root/.ssh/authorized_keys
```

```text
extracting archive '/var/lib/vz/template/cache/debian-12-standard_12.7-1_amd64.tar.zst'
Total bytes read: 421406720 (402MiB, 210MiB/s)
Detected container architecture: amd64
Creating SSH host key 'ssh_host_ed25519_key' ...done
Creating SSH host key 'ssh_host_rsa_key' ...done
Creating SSH host key 'ssh_host_ecdsa_key' ...done
```

**驗證設定**：

```bash
grep -E 'unprivileged|cores|memory|rootfs|net0' /etc/pve/lxc/210.conf
```

```text
cores: 2
memory: 1024
net0: name=eth0,bridge=vmbr0,firewall=1,gw=192.168.10.254,hwaddr=BC:24:11:9E:04:2D,ip=192.168.10.210/24,type=veth
rootfs: local-lvm:vm-210-disk-0,size=12G
unprivileged: 1
```

★★★★★ **`unprivileged: 1` 一定要確認到**。沒有這一行就是特權容器，砍掉重建。

### 步驟 4：啟動並做基本設定

```bash
pct start 210
pct status 210
```

```text
status: running
```

```bash
pct exec 210 -- ip -4 addr show eth0
```

```text
2: eth0@if35: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
    inet 192.168.10.210/24 brd 192.168.10.255 scope global eth0
       valid_lft forever preferred_lft forever
```

```bash
pct exec 210 -- ping -c 2 192.168.10.254
```

```text
PING 192.168.10.254 (192.168.10.254) 56(84) bytes of data.
64 bytes from 192.168.10.254: icmp_seq=1 ttl=64 time=0.312 ms
64 bytes from 192.168.10.254: icmp_seq=2 ttl=64 time=0.288 ms

--- 192.168.10.254 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss, time 1015ms
```

更新與安裝 Nginx：

```bash
pct exec 210 -- apt-get update
pct exec 210 -- apt-get install -y nginx
pct exec 210 -- systemctl is-active nginx
```

```text
active
```

### 步驟 5：★★★★★ 加上 bind mount 並修正 UID 對應

先查容器內 Nginx 用哪個 UID：

```bash
pct exec 210 -- id www-data
```

```text
uid=33(www-data) gid=33(www-data) groups=33(www-data)
```

★★★★ 所以主機端要 `chown 100033`（100000 + 33）。這裡我們要唯讀，
給 `root:100033` 加 `r-x` 就夠了：

```bash
chown -R 100000:100033 /srv/files
chmod -R 750 /srv/files
find /srv/files -type f -exec chmod 640 {} \;
ls -ln /srv/files /srv/files/pub
```

```text
/srv/files:
total 4
drwxr-x--- 2 100000 100033 4096 Sep  2 13:02 pub

/srv/files/pub:
total 4
-rw-r----- 1 100000 100033 30 Sep  2 13:02 README.txt
```

掛上去（唯讀）：

```bash
pct set 210 --mp0 /srv/files,mp=/data,ro=1
```

```text
update VM 210: -mp0 /srv/files,mp=/data,ro=1
```

```bash
pct reboot 210
```

**驗證容器內看得到正確的擁有者**：

```bash
pct exec 210 -- ls -l /data /data/pub
```

```text
/data:
total 4
drwxr-x--- 2 root www-data 4096 Sep  2 13:02 pub

/data/pub:
total 4
-rw-r----- 1 root www-data 30 Sep  2 13:02 README.txt
```

★★★★★ **看到 `www-data` 而不是 `nobody`，代表 UID 對應正確。**

```bash
# 確認 www-data 讀得到
pct exec 210 -- sudo -u www-data cat /data/pub/README.txt
```

```text
hello from host 2026-09-02
```

```bash
# 確認唯讀真的生效（★★★ 這一步要看到失敗才對）
pct exec 210 -- touch /data/pub/should-fail
```

```text
touch: cannot touch '/data/pub/should-fail': Read-only file system
```

### 步驟 6：設定 Nginx 提供檔案索引

```bash
pct exec 210 -- bash -c 'cat > /etc/nginx/sites-available/files.conf' <<'EOF'
server {
    listen 80 default_server;
    server_name files.lan.example.gov.tw;

    root /data;
    autoindex on;
    autoindex_exact_size off;
    autoindex_localtime on;

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF
pct exec 210 -- ln -sf /etc/nginx/sites-available/files.conf /etc/nginx/sites-enabled/files.conf
pct exec 210 -- rm -f /etc/nginx/sites-enabled/default
pct exec 210 -- nginx -t
```

```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

```bash
pct exec 210 -- systemctl reload nginx
curl -s http://192.168.10.210/pub/ | head -12
```

```text
<html>
<head><title>Index of /pub/</title></head>
<body>
<h1>Index of /pub/</h1><hr><pre><a href="../">../</a>
<a href="README.txt">README.txt</a>                                         02-Sep-2026 13:02      30
</pre><hr></body>
</html>
```

```bash
curl -s http://192.168.10.210/pub/README.txt
```

```text
hello from host 2026-09-02
```

★★★★ **服務可用了。** 注意 `README.txt` 是主機上的檔案，容器只是讀它。

### 步驟 7：驗證資源限制真的套上去

```bash
pct exec 210 -- nproc
```

```text
2
```

```bash
pct exec 210 -- free -m | head -2
```

```text
               total        used        free      shared  buff/cache   available
Mem:            1024         112        832           0          79        911
```

```bash
# 在主機上看 cgroup 的實際限制
cat /sys/fs/cgroup/lxc/210/memory.max
```

```text
1073741824
```

```bash
cat /sys/fs/cgroup/lxc/210/cpu.max
```

```text
150000 100000
```

★★★★ `150000 100000` 代表每 100 ms 週期最多用 150 ms CPU 時間 = `cpulimit 1.5`，跟設定一致。

### 步驟 8：★★★★★ 備份，並實際還原驗證

```bash
vzdump 210 --storage local --mode snapshot --compress zstd --notes-template '{{guestname}} 上線前基準'
```

```text
INFO: starting new backup job: vzdump 210 --storage local --mode snapshot --compress zstd
INFO: Starting Backup of VM 210 (lxc)
INFO: CT Name: files-lxc01
INFO: including mount point rootfs ('/') in backup
INFO: excluding bind mount point mp0 ('/data') from backup
INFO: creating vzdump archive '/var/lib/vz/dump/vzdump-lxc-210-2026_09_02-13_40_11.tar.zst'
INFO: Total bytes written: 512901120 (489MiB, 96MiB/s)
INFO: archive file size: 173MB
INFO: Finished Backup of VM 210 (00:00:23)
```

> [!danger] ★★★★★ 注意這一行
> ```text
> INFO: excluding bind mount point mp0 ('/data') from backup
> ```
> ★★★★★ **PVE 明明白白告訴你 bind mount 沒有被備份。**
> 這個容器的還原只能救回 Nginx 設定，救不回 `/srv/files` 的檔案 ——
> 那份資料要靠主機端另外備份。**每次做完備份都去看一眼有沒有這行。**

還原到一個**新的 VMID**（不覆蓋正在跑的 210）：

```bash
pct restore 299 /var/lib/vz/dump/vzdump-lxc-210-2026_09_02-13_40_11.tar.zst \
  --storage local-lvm \
  --hostname files-restore-test \
  --unprivileged 1
```

```text
recovering backed-up configuration from 'local:backup/vzdump-lxc-210-2026_09_02-13_40_11.tar.zst'
  Logical volume "vm-299-disk-0" created.
restoring 'local:backup/vzdump-lxc-210-2026_09_02-13_40_11.tar.zst' now..
Total bytes read: 512901120 (489MiB, 118MiB/s)
Detected container architecture: amd64
```

★★★★ 還原後**先改 IP 再開機**，否則跟 210 撞：

```bash
pct set 299 --net0 name=eth0,bridge=vmbr0,ip=192.168.10.299/24,gw=192.168.10.254,firewall=1
pct set 299 --onboot 0 --delete mp0
pct start 299
pct exec 299 -- systemctl is-active nginx
```

```text
active
```

```bash
pct exec 299 -- nginx -t
```

```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

```bash
pct exec 299 -- ls /data
```

```text
```

★★★★★ **`/data` 是空的** —— 這就是「bind mount 不會被備份」的實際後果，
在演練環境看到它，總比正式停機時看到好。

清理測試容器：

```bash
pct stop 299 && pct destroy 299
pct list
```

```text
VMID       Status     Lock         Name
210        running                 files-lxc01
```

### 步驟 9：補上主機端資料的備份

```bash
# 最陽春但有效：把 bind mount 來源另外打包
mkdir -p /var/backups/srv-files
tar -C /srv --numeric-owner -acf /var/backups/srv-files/files-$(date +%F).tar.zst files
ls -lh /var/backups/srv-files/
```

```text
total 4.0K
-rw-r--r-- 1 root root 1.2K Sep  2 13:52 files-2026-09-02.tar.zst
```

> [!tip] ★★★★★ `--numeric-owner` 不能省
> 非特權容器的檔案擁有者是 `100000`／`100033` 這種**主機上不存在的 UID**。
> 沒有 `--numeric-owner`，`tar` 會嘗試用名稱對應，還原時 UID 會跑掉，
> 結果就是還原完容器又讀不到檔案。

### 完成檢查清單 ★★★★

| # | 檢查項 | 通過條件 |
| --- | --- | --- |
| 1 | `grep unprivileged /etc/pve/lxc/210.conf` | 顯示 `unprivileged: 1` |
| 2 | `pct exec 210 -- ls -l /data/pub` | 擁有者顯示 `www-data`，**不是 nobody** |
| 3 | `pct exec 210 -- touch /data/pub/x` | ★★★ 回 `Read-only file system` |
| 4 | `curl http://192.168.10.210/pub/README.txt` | 拿得到內容 |
| 5 | `cat /sys/fs/cgroup/lxc/210/cpu.max` | `150000 100000` |
| 6 | vzdump 輸出 | 出現 `excluding bind mount point mp0` 且 `Finished Backup` |
| 7 | ★★★★★ 還原到 299 並啟動 | `nginx` 是 `active`、`nginx -t` 成功 |
| 8 | ★★★★★ 主機資料另有備份 | `/var/backups/srv-files/` 有當日檔案 |

---

## 常見錯誤與排錯

| 現象（原文訊息） | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `unable to create CT 201 - no such volume 'local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst'` | 範本沒下載，或檔名版本號抄錯 | `pveam list local` 確認實際檔名，重新 `pveam download` |
| ★★★★ `storage 'local-lvm' does not support container directories` | 該儲存的 content 沒勾 `rootdir` | 到「資料中心 → 儲存」補勾，或換一個支援的儲存 |
| ★★★★★ `lxc_map_ids: 245 newuidmap failed to write mapping` | `lxc.idmap` 三段加起來不等於 65536，或 `/etc/subuid`／`/etc/subgid` 沒同步加 | 重算三段、兩個檔案都要加，見「解法三」 |
| ★★★★★ 容器內 bind mount 目錄顯示為 `nobody:nogroup`，寫不進去 | 非特權容器 UID 位移 100000，主機端擁有者不在對應範圍 | 主機 `chown $((100000+容器UID))`，或用共用 GID／idmap |
| ★★★★ `TASK ERROR: unable to snapshot container - snapshot feature is not available for bind mounts` | 容器有 bind mount | 移除 bind mount，或改用儲存型掛載點 |
| ★★★★★ 備份日誌出現 `excluding bind mount point mp0` 而你以為它有備到 | bind mount 永遠不進 vzdump | 對主機來源目錄另做備份（`tar --numeric-owner` 或檔案級備份工具） |
| ★★★★ `TASK ERROR: CT is locked (mounted)` | 之前 `pct mount` 忘了 `pct unmount` | `pct unmount <VMID>`；仍卡住則 `pct unlock <VMID>` 後再確認 rootfs 沒被佔用 |
| ★★★★ `TASK ERROR: CT is locked (backup)` | 備份中斷留下鎖 | 確認 vzdump 真的沒在跑，再 `pct unlock <VMID>` |
| ★★★★ 容器內服務被無預警 kill，主機 `dmesg` 有 `Memory cgroup out of memory` | 容器記憶體上限太小；或主機無 swap 導致 `--swap` 形同虛設 | 調高 `--memory`；不要靠 swap 撐 |
| ★★★★ `failed to start daemon: error initializing graphdriver: driver not supported: overlay2` | 在 ZFS subvol 上跑 Docker | rootfs 換到 LVM-thin／dir，或改用 `fuse-overlayfs`（需 `fuse=1`） |
| ★★★★ Docker daemon 起不來、`docker info` 找不到 server | 沒開 `nesting=1` | `pct set <VMID> --features nesting=1,keyctl=1` 後重開容器 |
| ★★★ 容器內 `systemctl` 出現 `Failed to connect to bus` | 用 `pct exec` 進去時環境不完整，或容器 PID 1 不是 systemd | 改用 `pct enter`；確認範本是 standard 而非 minimal |
| ★★★ `mount: /mnt/nfs: permission denied` （容器內掛 NFS） | 非特權容器預設不能掛 NFS | 在**主機**掛好再 bind mount 進去（★★★★ 建議），或由 `root@pam` 設 `--features mount=nfs` |
| ★★★ 容器內 `modprobe: FATAL: Module xxx not found in directory /lib/modules/6.8.x` | 容器不能載核心模組 | 在**主機**上 `modprobe`；真的需要自己的模組請改用 VM |
| ★★★★ 克隆出來的兩台容器 SSH 指紋一樣、DHCP 拿到同一個 IP | 沒重生 SSH host key 與 `machine-id` | 見「克隆與轉成範本」的三件事 |
| ★★★★ `pct migrate` 之後容器在目標節點起不來，`unable to open directory '/srv/...'` | bind mount 路徑在目標節點不存在 | 先在目標節點建好同路徑與同權限，或改用共用儲存 |
| ★★★★★ 節點上所有容器與 VM 突然變唯讀，`thin pool` 相關錯誤 | LVM-thin pool 被快照或超額配置撐爆 | `lvs` 看 `Data%`，刪掉舊快照；長期要控管超額配置 |
| ★★★ 容器時間跟主機不同步／時區錯 | 容器沿用範本預設時區 | `pct exec <VMID> -- timedatectl set-timezone Asia/Taipei`；★★★ 時間同步由**主機**負責，容器內不要另裝 NTP |
| ★★★ `pct enter` 之後 `apt-get update` 一直 `Temporary failure resolving` | `--nameserver` 沒設，或容器沿用主機 DNS 但主機 DNS 不通 | `pct set <VMID> --nameserver <DNS IP>` 後重開；或檢查 `/etc/resolv.conf` |
| ★★★ Web 介面看不到「Unprivileged container」勾勾的狀態 | 建好之後 GUI 只顯示唯讀資訊 | 用 `grep unprivileged /etc/pve/lxc/<VMID>.conf` 確認；★★★★★ 不要手改此值 |

> [!tip] ★★★★ 排錯的第一順位：看任務日誌
> Web 介面下方的「Tasks」面板、或指令列：
> ```bash
> pct start 210
> ```
> 失敗時它會直接吐出原因。更完整的日誌在 `/var/log/pve/tasks/`，
> 容器自己的啟動記錄可以用
> ```bash
> lxc-start -n 210 -F -l DEBUG -o /tmp/lxc-210.log
> ```
> 抓（★★★ 這是 LXC 原生指令，只在排錯時用，日常請用 `pct`）。

---

## 安全性注意事項

### ★★★★★ 第一條：預設非特權，例外要留紀錄

| 規則 | 說明 | 重要度 |
| --- | --- | --- |
| 建容器一律 `--unprivileged 1` | 明寫，不依賴預設值 | ★★★★★ |
| 對外服務**禁止**特權容器 | 需要特權功能就改開 VM | ★★★★★ |
| 特權容器要登記在資產清單 | 記下 VMID、原因、負責人、複審日期 | ★★★★ |
| 不要為了「方便」把 AppArmor 關掉 | `lxc.apparmor.profile: unconfined` 等於拆掉最後一道牆 | ★★★★★ |

> [!danger] ★★★★★ 網路上很多教學會叫你加這行
> ```ini
> lxc.apparmor.profile: unconfined
> ```
> ★★★★★ **不要照抄。** 它把 PVE 預設的 AppArmor 侷限整個拿掉，
> 加上特權容器等於容器 root 就是主機 root。
> 真的需要放寬某一項時，正確做法是**寫一個只放寬那一項的自訂 profile**，
> 見 [[090-02-07-guide-防護-SELinux與AppArmor]]。

### ★★★★ 核心是共用的，所以主機更新最重要

```
容器 A 被打進去 → 攻擊者手上有容器內 root
                    ↓
           找一個 Linux 核心的本地提權漏洞
                    ↓
   ★★★★★ 這顆核心是主機的核心 → 影響的是整台節點，包含容器 B、C、D 與所有 VM
```

| 動作 | 頻率 | 重要度 |
| --- | --- | --- |
| 主機 `apt update && apt full-upgrade` 並重開機套用新核心 | 依機關政策，至少每月評估 | ★★★★★ |
| 容器內套件更新 | 每台都要，不要只更新主機 | ★★★★ |
| 訂閱 Proxmox 與發行版的安全公告 | 持續 | ★★★★ |

★★★★ 主機更新流程見 [[050-01-03-11-svc-PVE-升級與維護]]。

### ★★★★ 容器層級的防火牆

```bash
# 網卡上要先 firewall=1，PVE 防火牆才會套到這張介面
pct set 210 --net0 name=eth0,bridge=vmbr0,ip=192.168.10.210/24,gw=192.168.10.254,firewall=1
```

★★★★ PVE 的三層防火牆（資料中心／節點／VM 或 CT）與規則寫法見 [[050-01-03-05-guide-PVE-網路設定]]。
容器內另外裝 `ufw`／`nftables` 也可以，但**兩層規則同時存在時排錯會很痛苦**，
機關環境建議**統一在 PVE 這一層管**，容器內保持乾淨。

### ★★★★ features 是攻擊面開關，能不開就不開

| feature | 風險 | 建議 |
| --- | --- | --- |
| `nesting=1` | 中，允許巢狀 namespace | ★★★ 只有需要跑 systemd-nspawn／Docker 時開 |
| `keyctl=1` | 低到中 | ★★★ 需要時開 |
| `fuse=1` | 中 | 需要時開 |
| ★★★★★ `mount=nfs;cifs` | ★★★★★ **高**，容器可自行掛載檔案系統 | ★★★★★ 盡量改成「主機掛好 + bind mount 進去」 |

### ★★★★ 其他

- ★★★★ **不要用 root 密碼登入容器**，用 SSH 金鑰（`--ssh-public-keys`）。
- ★★★ 容器內同樣要做基本強化：關掉不用的服務、`sshd` 禁 root 密碼登入，見 [[090-02-01-guide-防護-伺服器初始安全設定]]。
- ★★★★ **bind mount 一律先問「需要可寫嗎」**，只讀就加 `ro=1`。
- ★★★★ PVE Web 介面（8006 埠）與容器服務**不要放在同一個網段對外**；
  管理介面只開放給管理網段。
- ★★★ 用 PVE 的權限系統把「誰能操作哪些容器」分開，見 [[050-01-03-08-guide-PVE-使用者權限與API]]。
- ★★★★★ **日誌要送出去**。容器被打掉重建，本機日誌就沒了；
  集中收送見 [[100-01-02-guide-日誌-日誌集中與輪替]]。

---

## 速查表

### 範本

| 指令 | 用途 |
| --- | --- |
| `pveam update` | 更新範本清單 |
| `pveam available --section system` | 列出可用系統範本 |
| `pveam available --section turnkeylinux` | 列出 TurnKey 應用範本 |
| `pveam download local <檔名>` | 下載到 `local` |
| `pveam list local` | 列出已下載範本 |
| `pveam remove local:vztmpl/<檔名>` | 刪除範本 |

### 生命週期

| 指令 | 用途 | 重要度 |
| --- | --- | --- |
| `pct create <ID> <範本> [選項]` | 建立容器 | ★★★★ |
| `pct list` | 列出本節點容器 | ★★★ |
| `pct status <ID>` | 查狀態 | ★★★ |
| `pct start <ID>` / `pct shutdown <ID>` | 開機／正常關機 | ★★★ |
| `pct stop <ID>` | ★★★ **強制停止（等同拔電）** | ★★★★ |
| `pct reboot <ID>` | 重開 | ★★ |
| `pct destroy <ID>` | ★★★★★ **刪除，不可逆** | ★★★★★ |
| `pct unlock <ID>` | 清除卡住的鎖 | ★★★ |

### 進入與操作

| 指令 | 用途 | 重要度 |
| --- | --- | --- |
| `pct enter <ID>` | 直接開 root shell（★★★★ 排錯首選） | ★★★★ |
| `pct exec <ID> -- <指令>` | 跑一條指令 | ★★★★ |
| `pct console <ID>` | 接 console（離開 `Ctrl-a q`） | ★★★ |
| `pct push <ID> <本機檔> <容器路徑>` | 傳檔進去 | ★★★ |
| `pct pull <ID> <容器路徑> <本機檔>` | 抓檔出來 | ★★★ |
| `pct mount <ID>` / `pct unmount <ID>` | ★★★★ 停機時掛 rootfs 搶救 | ★★★★ |

### 設定與資源

| 指令／欄位 | 用途 | 重要度 |
| --- | --- | --- |
| `pct config <ID>` | 顯示目前設定 | ★★★ |
| `pct set <ID> --memory 2048 --cores 2` | 改資源 | ★★★★ |
| `pct set <ID> --cpulimit 1.5` | 總算力上限 | ★★★★ |
| `pct set <ID> --cpuunits 100` | 相對權重 | ★★ |
| `pct resize <ID> rootfs +8G` | ★★★ **只能加大** | ★★★★ |
| `pct df <ID>` | 各掛載點使用率 | ★★★ |
| `pct fsck <ID>` | 停機時檢查 rootfs | ★★★ |
| `/etc/pve/lxc/<ID>.conf` | 設定檔位置 | ★★★★ |

### 掛載點

| 寫法 | 意義 | 重要度 |
| --- | --- | --- |
| `--mp0 local-lvm:32,mp=/var/www` | 儲存型掛載點（**會備份**） | ★★★★ |
| `--mp1 /srv/data,mp=/data` | bind mount（★★★★★ **不會備份、不能快照**） | ★★★★★ |
| `,ro=1` | 唯讀 | ★★★ |
| `,backup=0` | 不納入備份 | ★★★ |
| `,shared=1` | 各節點皆有此路徑 | ★★★ |
| `--delete mp0` | 移除掛載點 | ★★★ |

### UID 對應

| 項目 | 值／指令 | 重要度 |
| --- | --- | --- |
| ★★★★★ 換算公式 | **主機 UID = 100000 + 容器 UID** | ★★★★★ |
| 容器 root | 主機 `100000` | ★★★★ |
| 容器 www-data(33) | 主機 `100033` | ★★★★ |
| 對應範圍設定 | `/etc/subuid`、`/etc/subgid`（預設 `root:100000:65536`） | ★★★★ |
| 自訂對應 | `lxc.idmap: u <容器起> <主機起> <數量>` | ★★★★ |
| 查容器內 UID | `pct exec <ID> -- id -u <帳號>` | ★★★★ |
| 打包時保留數字 UID | `tar --numeric-owner` | ★★★★★ |

### features

| 旗標 | 用途 | 重要度 |
| --- | --- | --- |
| `nesting=1` | 巢狀 namespace（Docker、systemd-nspawn 前提） | ★★★★ |
| `keyctl=1` | kernel keyring | ★★★ |
| `fuse=1` | FUSE（`fuse-overlayfs` 需要） | ★★★ |
| `mount=nfs;cifs` | ★★★★★ 容器內自行掛載（**風險高**，限 `root@pam`） | ★★★★★ |

### 快照／克隆／遷移／備份

| 指令 | 用途 | 重要度 |
| --- | --- | --- |
| `pct snapshot <ID> <名稱>` | 建快照 | ★★★ |
| `pct listsnapshot <ID>` | 列快照 | ★★★ |
| `pct rollback <ID> <名稱>` | 回復 | ★★★★ |
| `pct delsnapshot <ID> <名稱>` | ★★★★ **記得刪，否則吃空間** | ★★★★ |
| `pct clone <來源> <新ID> --full 1` | 完整克隆 | ★★★ |
| `pct template <ID>` | 轉成範本 | ★★ |
| `pct migrate <ID> <節點> --restart` | ★★★★ 遷移（**會中斷**） | ★★★★ |
| `vzdump <ID> --mode snapshot --compress zstd` | 備份 | ★★★★ |
| `pct restore <新ID> <備份檔> --storage <儲存>` | ★★★★★ 還原到新 VMID | ★★★★★ |

---

## 練習題

1. **判斷題實作**：在你的測試節點上，替下列三個服務各決定「LXC 還是 VM」，
   並在紙上寫出理由（每個至少兩條）：(a) 內部 DNS（unbound）、(b) Kubernetes worker、
   (c) 給廠商測試用、由廠商自行登入操作的環境。

2. **建立非特權容器**：用 `pct create` 建一個 VMID 220、hostname `lab-lxc01` 的
   Debian 12 非特權容器，`cores 1`、`memory 512`、`rootfs` 8 GiB，靜態 IP 自行決定。
   建完用 `grep` 確認 `unprivileged: 1`，並用 `pct exec` 確認 `nproc` 與 `free -m` 符合設定。

3. **★★★★★ UID 對應實作**：在主機建立 `/srv/lab`，塞一個檔案。
   把它 bind mount 到容器 220 的 `/lab`。
   先觀察容器內看到的擁有者，再讓容器內的 UID 1000 使用者可以**寫入**這個目錄。
   寫下你用了三種解法中的哪一種、以及為什麼。

4. **快照與 bind mount 的衝突**：對步驟 3 的容器 220 執行 `pct snapshot 220 test`，
   把錯誤訊息原文抄下來。接著移除 bind mount 再試一次，確認可以成功。

5. **★★★★ 備份與還原演練**：對容器 220 做 `vzdump`，
   在備份輸出中找出「排除 bind mount」那一行並抄下來。
   然後 `pct restore` 到 VMID 289，改掉 IP 後啟動，
   進去確認：(a) rootfs 的檔案在不在、(b) bind mount 的內容在不在。

6. **★★★ 資源限制驗證**：把容器 220 設成 `--cores 2 --cpulimit 0.5`，
   在容器內跑 `yes > /dev/null &` 兩份，用主機的 `top` 觀察該容器的 CPU 使用率，
   確認不超過 50%。做完記得把背景程序砍掉。

> [!question]- 練習解答
>
> **1.**
> - (a) 內部 DNS → **LXC**。純使用者空間服務、資源需求小、重開快、不需要動核心。
> - (b) Kubernetes worker → **VM**。kubelet 與 CNI 大量操作 netfilter 與 cgroup，
>   需要自己的核心參數；官方支援矩陣也以 VM／實體機為準。
> - (c) 廠商自行操作 → ★★★★★ **VM**。這是「不受信任的操作者」，
>   隔離強度是首要考量，LXC 共用核心不適合當信任邊界。
>
> **2.**
> ```bash
> pct create 220 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
>   --hostname lab-lxc01 --unprivileged 1 \
>   --cores 1 --memory 512 --swap 256 \
>   --rootfs local-lvm:8 \
>   --net0 name=eth0,bridge=vmbr0,ip=192.168.10.220/24,gw=192.168.10.254,firewall=1 \
>   --password
> pct start 220
> grep unprivileged /etc/pve/lxc/220.conf     # → unprivileged: 1
> pct exec 220 -- nproc                        # → 1
> pct exec 220 -- free -m | head -2            # → total 512
> ```
>
> **3.** 最單純的是**解法一**：
> ```bash
> mkdir -p /srv/lab && echo hi > /srv/lab/a.txt
> pct set 220 --mp0 /srv/lab,mp=/lab
> pct reboot 220
> pct exec 220 -- ls -l /lab          # 一開始是 nobody:nogroup
> chown -R 101000:101000 /srv/lab     # 100000 + 1000
> pct exec 220 -- ls -l /lab          # 變成容器內 UID 1000 的使用者
> ```
> 選解法一的理由：只有一個容器要用這份資料，主機端沒有其他服務依賴這個目錄的擁有者。
> 若主機上的服務也要讀寫同一份資料，才需要走 `lxc.idmap`（解法三）。
>
> **4.**
> ```text
> TASK ERROR: unable to snapshot container - snapshot feature is not available for bind mounts
> ```
> ```bash
> pct set 220 --delete mp0
> pct snapshot 220 test     # 這次成功
> pct delsnapshot 220 test
> ```
> ★★★★ 記得做完把快照刪掉。
>
> **5.** 備份輸出中的關鍵行：
> ```text
> INFO: excluding bind mount point mp0 ('/lab') from backup
> ```
> 還原後 rootfs 的檔案都在，但 `/lab` 是空的（或掛載點不存在）。
> ★★★★★ 這就是重點：**bind mount 的資料要另外備份**。
>
> **6.**
> ```bash
> pct set 220 --cores 2 --cpulimit 0.5
> pct exec 220 -- bash -c 'yes > /dev/null & yes > /dev/null & sleep 20; kill %1 %2'
> # 主機上另開視窗
> top -b -n 1 | head -12        # 觀察兩個 yes 程序合計約 50% 一顆核心
> cat /sys/fs/cgroup/lxc/220/cpu.max
> # → 50000 100000
> ```

---

## 小測驗

**Q1.** LXC 容器與 KVM 虛擬機最根本的差別是什麼？這個差別同時造成了哪一項最大的優點與哪一項最大的缺點？

**Q2.**（是非）把 `/etc/pve/lxc/201.conf` 裡的 `unprivileged: 1` 改成 `unprivileged: 0`，重開容器後就變成特權容器了。

**Q3.**（選擇）非特權容器內的 `www-data`（UID 33），對應到主機上的哪一個 UID？
(A) 33　(B) 65534　(C) 100033　(D) 依機器而異，無法預測

**Q4.** 這行指令會發生什麼事？
```bash
pct set 210 --mp1 /srv/files,mp=/data
```
說出三個後果（提示：備份、快照、遷移）。

**Q5.**（是非）容器有 bind mount 時，`vzdump` 會把 bind mount 的內容一併備份，只是壓縮率比較差。

**Q6.**（選擇）在 LXC 裡跑 Docker，最必要的 feature 是哪一個？
(A) `fuse=1`　(B) `nesting=1`　(C) `mount=nfs`　(D) `keyctl=1`

**Q7.** 容器 rootfs 放在 ZFS 上，Docker 啟動時出現
`error initializing graphdriver: driver not supported: overlay2`。
請說出原因與兩種可行的解法。

**Q8.** 下面這段 `lxc.idmap` 為什麼會讓容器開不起來？
```ini
lxc.idmap: u 0 100000 33
lxc.idmap: u 33 33 1
lxc.idmap: u 34 100034 65500
```

**Q9.**（簡答）`pct migrate 201 pve02 --restart` 對服務可用性的實際影響是什麼？
它跟 VM 的 live migration 差在哪？

**Q10.**（簡答）為什麼機關環境不應該讓「對外提供服務的容器」使用特權容器？
如果它確實需要某個只有特權容器才做得到的功能，正確的處理方式是什麼？

> [!question]- 測驗答案
>
> **A1.** ★★★★★ 最根本的差別是 **VM 有自己的核心、LXC 共用主機核心**。
> - 最大優點：**省資源、開機快**（沒有 guest kernel 與虛擬硬體那一層）。
> - 最大缺點：**隔離強度較弱**（核心漏洞即逃逸風險），且**不能載模組、不能選核心版本**。
> 見「觀念說明 → 一句話講完差別」。
>
> **A2.** ★★★★★ **否。** `unprivileged` 不是切換開關，rootfs 上所有檔案的 UID／GID
> 也要整批位移。手改只會得到一個權限全錯的容器。
> 正確做法是**備份後還原成另一種類型**。見「特權容器與非特權容器」的警語。
>
> **A3.** ★★★★★ **(C) 100033**。公式是 **主機 UID = 100000 + 容器 UID**
> （在預設的 `root:100000:65536` 對應下）。見速查表「UID 對應」。
>
> **A4.** 這是一個 **bind mount**，三個後果：
> 1. ★★★★★ `/srv/files` 的內容**永遠不會進 `vzdump` 備份**（日誌會出現 `excluding bind mount point`）；
> 2. ★★★★ 這台容器**無法再做快照**（`snapshot feature is not available for bind mounts`）；
> 3. ★★★★ 跨節點遷移時**路徑不會跟著搬**，目標節點沒有同路徑就起不來。
> 見「bind mount」一節。
>
> **A5.** ★★★★★ **否。** bind mount **完全不進備份**，
> PVE 會在日誌明白印出 `excluding bind mount point mpN`。
> 這是最常見的資料遺失原因之一。
>
> **A6.** **(B) `nesting=1`**。沒有它 Docker daemon 根本起不來。
> `keyctl=1` 是強烈建議一起開（否則部分服務會出錯），
> `fuse=1` 只有改用 `fuse-overlayfs` 時才需要。見「巢狀容器」。
>
> **A7.** 原因：★★★★★ **Docker 的 `overlay2` 驅動在 ZFS dataset（subvol）上不被支援**。
> 兩種解法：
> 1. ★★★★ 把容器 rootfs 改放在 **LVM-thin 或目錄型儲存**（底層是 ext4）；
> 2. 開 `fuse=1`，容器內裝 `fuse-overlayfs` 並在 `/etc/docker/daemon.json` 指定
>    `"storage-driver": "fuse-overlayfs"`（★★★ 效能較差）。
> 見「儲存驅動：這裡最容易翻車」。
>
> **A8.** ★★★★★ 因為**三段沒有覆蓋完整的 0～65535**：
> 33 + 1 + 65500 = 65534，少了 2 個。必須湊滿 65536（正確是 `u 34 100034 65502`）。
> 另外還要確認 `/etc/subuid` 與 `/etc/subgid` **都**有加上 `root:33:1` 那一格。
> 症狀是 `lxc_map_ids: ... newuidmap failed to write mapping`。見「解法三」。
>
> **A9.** ★★★★★ `--restart` 的實際行為是「**關機 → 搬移 → 在目標節點開機**」，
> **服務一定會中斷**，中斷時間 = 關機 + 磁碟複製（若非共用儲存）+ 開機。
> VM 的 live migration 是記憶體逐步同步後切換，中斷時間在毫秒級。
> ★★★★ **LXC 沒有真正的線上遷移**。見「跨節點遷移」。
>
> **A10.** 因為 ★★★★★ **Proxmox 官方明確指出特權容器不是安全邊界**：
> 容器內 root 直接對應主機 root，一旦服務被攻破（Web 應用漏洞、上傳的程式碼），
> 攻擊者只要繞過 AppArmor／seccomp 其中一道防線，就等於拿到整台節點。
> 正確處理方式：★★★★★ **不是開特權容器，而是改用 VM** ——
> 需要特權功能又要對外服務，代表這個工作負載本來就不適合 LXC。
> 見「安全性注意事項 → 第一條」。

---

## 延伸閱讀

### 本章其他篇

- [[050-01-03-01-svc-PVE-安裝與初始設定]] — 節點安裝、套件庫與初始調整
- [[050-01-03-02-guide-PVE-儲存設定]] — ★★★★ 決定容器能不能快照的關鍵
- [[050-01-03-03-guide-PVE-虛擬機管理]] — 需要 VM 時看這篇
- [[050-01-03-05-guide-PVE-網路設定]] — bridge、VLAN、防火牆三層規則
- [[050-01-03-06-svc-PVE-備份與還原]] — ★★★★★ vzdump 三種模式與還原演練
- [[050-01-03-07-svc-PVE-叢集與高可用]] — 遷移與 HA
- [[050-01-03-08-guide-PVE-使用者權限與API]] — 誰能操作哪些容器
- [[050-01-03-09-svc-PVE-監控與資源調校]] — 容器資源用量觀察
- [[050-01-03-10-guide-PVE-硬體直通與GPU]] — 需要裝置時的做法
- [[050-01-03-11-svc-PVE-升級與維護]] — ★★★★ 主機核心更新流程
- [[050-01-03-12-guide-PVE-故障排除]] — 綜合排錯
- [[050-01-03-13-guide-PVE-建立練習環境]] — 沒有實機時怎麼練

### 相關主題

- [[050-01-01-01-guide-虛擬化-虛擬化概念與選型]] — 虛擬化分類與選型總論
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] — namespace／cgroup 的底層機制
- [[050-02-01-01-svc-Docker-容器概念與Docker安裝]] — 應用容器的觀念
- [[050-02-01-08-guide-Docker-安全實務]] — Docker 的安全設定
- [[020-01-08-cmd-Linux-檔案權限與擁有者]] — UID／GID 與權限位元
- [[020-01-24-guide-進階儲存-ZFS與Btrfs]] — ZFS dataset 與快照
- [[090-02-07-guide-防護-SELinux與AppArmor]] — 強制存取控制
- [[090-02-01-guide-防護-伺服器初始安全設定]] — 容器內也要做的基本強化
- [[100-01-02-guide-日誌-日誌集中與輪替]] — 把容器日誌送出去

### 官方文件

- Proxmox VE 官方文件 `Linux Container (LXC)` 章節 — ★★★★ 動筆前必看，`pct` 完整參數以此為準
- 節點上的手冊頁：`man pct`、`man pct.conf`、`man vzdump`
- `pct help create` — ★★★★ 列出你這個版本實際支援的參數，**比任何網路教學可靠**
