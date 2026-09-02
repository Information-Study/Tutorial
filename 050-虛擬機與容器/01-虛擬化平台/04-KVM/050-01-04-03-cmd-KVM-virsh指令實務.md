---
title: "virsh指令實務"
desc: "virsh 完整生命週期指令、destroy 為什麼不是刪除、dumpxml 與 edit 改設定、內部與外部快照的差別、console 連線與退出、線上遷移，以及 virsh 與 qm 的對照表"
aliases: [virsh, virsh destroy, virsh undefine, snapshot-create-as, virsh console, virsh migrate, virsh 與 qm 對照]
tags: [群組/虛擬機與容器, 虛擬化/kvm, 主題/虛擬化]
category: 虛擬化平台
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[050-01-04-02-svc-KVM-安裝與virt-manager]]", "[[050-01-04-01-guide-KVM-KVM與libvirt架構]]"]
updated: 2026-09-02
---

# virsh指令實務

> [!note] 本章在本手冊裡的定位
> 本手冊的虛擬化**主線是 VMware Workstation（桌面測試環境）與 Proxmox VE（機關正式環境）**。
> KVM 章屬於輔助線，供**單機 Linux 虛擬化**與**理解 PVE 底層**之用。
> 平台之間的取捨請見 [[050-01-01-03-ref-虛擬化-五平台橫向對照]]。
>
> ★★★★ 本篇的所有 `virsh` 指令**在 PVE 主機上都不能用**（PVE 不使用 libvirt），
> 但每一個指令都有對應的 `qm` 指令，本篇最後有完整對照表。

> [!warning] 未實機驗證
> 本篇以 **libvirt 10.x + QEMU 8.x** 為敘述基準。
> `virsh` 的**子指令名稱非常穩定**，但部分旗標（尤其是快照與遷移相關）
> 在不同版本的支援程度不同——**外部快照的 revert 支援**就是最典型的例子。
> **執行前請以 `virsh help <子指令>` 與 `man virsh` 的實際輸出為準**，
> 破壞性操作務必先在測試 VM 上驗證。

> [!abstract] 這篇你會學到
> - `virsh` 的**完整生命週期**：`define` → `start` → `shutdown` → `undefine`，
>   以及「持久 domain」與「暫態 domain」的差別 ★★★★
> - ★★★★★ **`destroy` 是強制斷電，不是刪除**——`virsh` 裡命名最危險的指令，
>   而真正的刪除是 `undefine`
> - `dumpxml`、`edit`、`virt-xml` 三種改設定的方法，以及**什麼時候才生效** ★★★★
> - ★★★★★ **內部快照與外部快照**：qcow2 內部快照能 revert 但只能用 qcow2；
>   外部快照更彈性但 **revert 的支援在舊版 libvirt 上是坑**
> - `virsh console` 怎麼連、★★★★ **怎麼退出（`Ctrl+]`）**、
>   客體端要做什麼設定才會有畫面
> - 線上遷移 `migrate --live` 的完整前提與流程 ★★★★
> - ★★★★★ **`virsh` 與 PVE `qm` 的完整對照表**
> - 把 02 篇用 `virt-manager` 做的事，全部改用指令重做一次

## 前置知識

- [[050-01-04-02-svc-KVM-安裝與virt-manager]] — **必做**，本篇直接接手那台 `web01`
- [[050-01-04-01-guide-KVM-KVM與libvirt架構]] — domain XML、三層分工
- [[020-01-10-cmd-Linux-程序管理與訊號]] — VM 就是一個程序，`kill` 的意義
- [[020-01-21-cmd-Linux-Shell腳本入門]] — 批次操作會用到迴圈
- [[050-01-03-03-guide-PVE-虛擬機管理]] — 對照 `qm` 的用法

---

## 觀念說明

### ★★★★★ 先搞清楚四個狀態，才不會下錯指令

libvirt 的 domain 有兩個獨立的維度，很多人把它們混在一起：

| 維度 | 兩種狀態 | 決定於 |
| --- | --- | --- |
| **有沒有定義** | **persistent**（有定義檔）／ **transient**（暫態，關掉就消失） | 是否 `define` 過 |
| **有沒有在跑** | **running**（執行中）／ **shut off**（停止） | 是否 `start` 過 |

四種組合：

```text
                    有定義（persistent）        沒定義（transient）
                ┌────────────────────────┬──────────────────────────┐
  執行中        │  正常的 VM              │  virsh create 出來的     │
  (running)     │  virsh list 看得到      │  ★★★★ 關掉就永久消失     │
                ├────────────────────────┼──────────────────────────┤
  停止          │  virsh list --all       │  ★ 不存在                │
  (shut off)    │  看得到                 │  （沒定義又沒跑 = 沒有）  │
                └────────────────────────┴──────────────────────────┘
```

★★★★★ **這解釋了 `virsh list` 與 `virsh list --all` 的差別**：

```bash
virsh list
```

```text
 Id   Name    State
-----------------------
 1    web01   running
```

```bash
virsh list --all
```

```text
 Id   Name    State
-----------------------
 1    web01   running
 -    db01    shut off
```

★★★★ **`virsh list` 只顯示執行中的**。這是新手第二常見的「我的 VM 不見了」
（第一常見是 system/session 搞混，見 [[050-01-04-02-svc-KVM-安裝與virt-manager]]）。
**養成永遠打 `virsh list --all` 的習慣。**

執行中的 VM 有 `Id`（數字），停止的顯示 `-`。★★★ **`Id` 會在每次啟動時改變**，
所以腳本裡要用**名稱或 UUID**，不要用 Id。

### ★★★★★ 生命週期指令：這一節請看兩次

這是全篇最危險也最重要的部分。

```text
                    ┌─────────────────┐
     define ───────►│  已定義、未執行  │◄─────── shutdown / destroy
   （寫入 XML）      │   (shut off)    │
                    └────────┬────────┘
                             │ start
                             ▼
                    ┌─────────────────┐
                    │    執行中        │
                    │   (running)     │
                    └────────┬────────┘
                             │
              shutdown ──────┤────── destroy
            （優雅關機）      │      （★★★★★ 強制斷電）
                             ▼
                    ┌─────────────────┐
                    │  已定義、未執行  │
                    └────────┬────────┘
                             │ undefine
                             ▼
                        ★★★★★ 真正的刪除
                       （定義消失；磁碟預設保留）
```

#### ★★★★★ `destroy` 不是刪除，是拔插頭

**這是 `virsh` 裡命名最糟糕、也最容易釀成事故的指令。**

| 指令 | 你以為 | 實際上 |
| --- | --- | --- |
| `virsh destroy web01` | ❌ 刪掉這台 VM | ★★★★★ **立即切斷電源**，VM 還在，磁碟還在 |
| `virsh undefine web01` | ❌ 停止 VM | ★★★★★ **刪除定義**（VM 若在跑，會變成暫態，繼續跑） |

用 PVE 的話講：

| virsh | PVE `qm` | 意義 |
| --- | --- | --- |
| `virsh shutdown` ★★★★ | `qm shutdown` | 優雅關機（ACPI 或 guest agent） |
| `virsh destroy` ★★★★★ | **`qm stop`** | **強制斷電** |
| `virsh undefine` ★★★★★ | **`qm destroy`** | **刪除定義** |

> [!danger] ★★★★★ 注意 `destroy` 這個字在兩個平台的意義完全相反
> - **libvirt 的 `destroy`** = 強制斷電（PVE 的 `qm stop`）
> - **PVE 的 `qm destroy`** = 刪除 VM（libvirt 的 `undefine`）
>
> **在兩個平台之間切換的人，這裡出事的機率極高。**
> 記憶法：libvirt 的 `destroy` 是「destroy the running instance（摧毀執行實例）」，
> 不是 destroy the VM。

#### ★★★★★ `destroy` 的實際後果

```bash
virsh destroy web01
```

```text
Domain 'web01' destroyed
```

看起來像「刪掉了」，實際上：

```bash
virsh list --all
```

```text
 Id   Name    State
-----------------------
 -    web01   shut off
```

VM 還在，只是**被拔了插頭**。後果等同於：

- 客體檔案系統處於**不一致狀態**（可能需要 fsck）
- 沒寫回磁碟的資料**遺失**
- 資料庫可能**損毀**
- 客體下次開機可能跑 journal recovery，或直接進 emergency mode

> [!warning] ★★★★★ 正確的關機順序
> ```bash
> # 1. 先試優雅關機
> virsh shutdown web01
>
> # 2. 等一下，看看狀態
> virsh domstate web01
>
> # 3. 沒反應？先進去看看卡在哪
> virsh console web01
>
> # 4. 真的救不了，才用 destroy
> virsh destroy web01
>
> # 5. ★★★★ 之後開機要檢查檔案系統
> ```

#### ★★★★ `shutdown` 為什麼常常沒反應

`virsh shutdown` 的運作方式有兩種：

| 模式 | 原理 | 客體要有什麼 |
| --- | --- | --- |
| **`--mode acpi`**（多為預設） ★★★★ | 送出 ACPI 電源鍵訊號 | 客體要有 `acpid` 或桌面環境在監聽 |
| **`--mode agent`** ★★★★★ | 透過 `qemu-guest-agent` 叫客體執行關機 | 客體要裝 `qemu-guest-agent` |

```bash
virsh shutdown web01 --mode agent
```

```text
Domain 'web01' is being shutdown
```

> [!tip] ★★★★★ 為什麼一定要裝 `qemu-guest-agent`
> - ACPI 訊號**只是一個請求**，客體可以忽略（極簡容器化映像常常沒裝 `acpid`）
> - guest agent 是**直接叫客體執行 `shutdown`**，可靠得多
> - agent 還提供：查客體 IP（`domifaddr --source agent`）、
>   檔案系統凍結（一致性快照）、查客體資訊
>
> 客體端安裝：
> ```bash
> sudo apt install -y qemu-guest-agent
> sudo systemctl enable --now qemu-guest-agent
> ```

#### ★★★★★ `undefine`：真正的刪除，但預設不刪磁碟

```bash
virsh undefine web01
```

```text
Domain 'web01' has been undefined
```

★★★★★ **這只刪了 `/etc/libvirt/qemu/web01.xml`，磁碟檔還在！**

```bash
ls -lh /var/lib/libvirt/images/
```

```text
-rw------- 1 libvirt-qemu kvm 8.7G Sep  2 11:03 web01.qcow2
```

這是**刻意的設計**（避免手滑刪掉資料），但也造成兩個問題：

1. ★★★★ **磁碟空間慢慢被孤兒檔吃光**，而 `virsh list --all` 看不到它們
2. ★★★ 想重建同名 VM 時會撞到既有檔案

要連磁碟一起刪：

```bash
virsh undefine web01 --remove-all-storage
```

```text
Domain 'web01' has been undefined
Volume 'vda'(/var/lib/libvirt/images/web01.qcow2) removed.
```

> [!danger] ★★★★★ `--remove-all-storage` 是不可逆的
> 它會刪掉這台 VM 所有的磁碟檔。**執行前務必先 `virsh domblklist` 看清楚會刪什麼**：
> ```bash
> virsh domblklist web01
> ```
> ```text
>  Target   Source
> ---------------------------------------------
>  vda      /var/lib/libvirt/images/web01.qcow2
>  sda      /var/lib/libvirt/images/iso/ubuntu-24.04-live-server-amd64.iso
> ```
> ★★★★★ **注意**：如果 ISO 還掛著，某些版本可能一併嘗試移除。
> 保險做法是**先卸掉 CDROM 再 undefine**。

> [!warning] ★★★★ UEFI 客體要加 `--nvram`
> 用 UEFI（OVMF）開機的 VM 有一個獨立的 NVRAM 檔存放開機變數。
> `undefine` 時如果不處理，會報錯或留下孤兒檔：
> ```text
> error: Requested operation is not valid: cannot undefine domain with nvram
> ```
> 解法：
> ```bash
> virsh undefine web01 --nvram
> # 或連磁碟一起
> virsh undefine web01 --nvram --remove-all-storage
> ```

#### ★★★★ `define` vs `create`：一字之差，天差地遠

| 指令 | 做什麼 | 結果 |
| --- | --- | --- |
| **`virsh define x.xml`** ★★★★★ | 只**註冊定義**，不啟動 | persistent domain，關機後還在 |
| **`virsh create x.xml`** ★★★★★ | **直接從 XML 啟動**，不註冊 | **transient domain，關掉就永遠消失** |

```bash
virsh create /tmp/test.xml
```

```text
Domain 'test' created from /tmp/test.xml
```

```bash
virsh list --all
```

```text
 Id   Name   State
----------------------
 2    test   running
```

看起來一切正常。但是：

```bash
virsh shutdown test
virsh list --all
```

```text
 Id   Name    State
-----------------------
 1    web01   running
```

★★★★★ **`test` 消失了。** 定義從來沒被寫進磁碟。

> [!danger] ★★★★★ 這是真的會出事的坑
> 有人用 `virsh create` 開了一台「臨時測試機」，
> 用著用著變成半正式的服務跑了三個月。某天主機重開機——**VM 永遠消失了**，
> 只剩下一個孤兒 qcow2 檔（資料還在，但設定要重建）。
>
> **維運環境一律用 `define` + `start`，不要用 `create`。**
>
> 補救：暫態 domain 還在跑時可以「就地轉正」：
> ```bash
> virsh dumpxml test > /root/test.xml
> virsh define /root/test.xml
> virsh dominfo test | grep Persistent
> ```
> ```text
> Persistent:     yes
> ```

### ★★★★ 改設定的三種方法

| 方法 | 用法 | 適合 |
| --- | --- | --- |
| **`virsh edit`** ★★★★★ | 開編輯器改整份 XML，存檔時驗證語法 | **互動式修改，最常用** |
| **`virt-xml`** ★★★★ | 命令列單項修改，可寫進腳本 | **自動化、批次** |
| **`virsh set*` 系列** ★★★★ | `setmem`、`setvcpus`、`attach-disk` 等 | 特定操作，部分支援熱插拔 |

★★★★★ **三種都可以，唯獨不能直接 `vim /etc/libvirt/qemu/*.xml`**
（原因見 [[050-01-04-01-guide-KVM-KVM與libvirt架構]]）。

#### ★★★★★ 什麼時候生效：三個層級

這是改設定時最重要的判斷：

| 變更類型 | 何時生效 | 例子 |
| --- | --- | --- |
| **需要完整停機再開機** ★★★★★ | `shutdown` → `start`。**`reboot` 無效** | CPU model、machine type、磁碟匯流排、網卡型號、韌體、記憶體上限 |
| **可以熱插拔（live）** ★★★★ | 立即生效，加 `--live` | 加／移除磁碟、網卡、CPU 數量（在 `maxvcpus` 內）、balloon 記憶體 |
| **只影響下次開機** ★★★★ | 加 `--config` | 大部分持久性設定 |

> [!warning] ★★★★★ `virsh reboot` 不會套用硬體變更
> 跟 PVE 的 `qm reboot` 完全一樣的坑：
> `reboot` 是**在客體裡面重開機**，**底層的 QEMU 程序沒有重建**，
> 所以硬體層級的設定變更不會生效。
> **必須 `virsh shutdown` 之後再 `virsh start`。**

`virt-xml` 的三個關鍵旗標 ★★★★：

```bash
virt-xml web01 --edit --memory 4096 --config    # 只改定義，下次開機生效
virt-xml web01 --edit --memory 4096 --update    # 只改執行中的（不持久）
virt-xml web01 --edit --memory 4096 --config --update   # 兩者都改
```

### ★★★★★ 快照：內部與外部的差別（這一節決定你會不會踩雷）

libvirt 的快照有**兩種完全不同的實作**，指令看起來很像，行為天差地遠。

| | **內部快照（internal）** ★★★★★ | **外部快照（external）** ★★★★★ |
| --- | --- | --- |
| **怎麼建** | `virsh snapshot-create-as <vm> <name>` | 加 `--disk-only` 或指定 `--diskspec ...,snapshot=external` |
| **存在哪** | ★★★★ **存在同一個 qcow2 檔內部** | ★★★★ **新建一個 overlay 檔**，原檔變成唯讀 backing file |
| **磁碟格式限制** | ★★★★★ **只支援 qcow2**（raw 不行） | 任何格式都行（overlay 一定是 qcow2） |
| **能不能存記憶體** | ✅ 可以（VM 執行中做就會存） | ⚠️ 要另外指定 `--memspec` |
| **`snapshot-revert`** | ✅ **支援良好** | ★★★★★ **舊版 libvirt 不支援**，是最大的坑 |
| **刪除快照** | `snapshot-delete`，直接合併 | ★★★★ 要用 `blockcommit` 把 overlay 合回去 |
| **效能影響** | 快照多了之後寫入變慢 | overlay 鏈越長讀取越慢 |
| **適合** | ★★★★ **單機、qcow2、要能快速回復** | ★★★★ 備份（配合 `blockcommit`）、LVM/raw 磁碟 |

#### ★★★★★ 外部快照 revert 的坑

這是本篇最需要警告的一點：

```bash
virsh snapshot-revert web01 backup-20260902
```

在較舊的 libvirt 上會得到：

```text
error: unsupported configuration: revert to external snapshot not supported yet
```

> [!danger] ★★★★★ 做快照之前先確認你的 libvirt 支援什麼
> **不要假設「我做了快照就一定能回復」。** 建立快照後**立刻測試一次 revert**，
> 這是唯一可靠的驗證方式。
>
> 較新的 libvirt 版本已陸續加入外部快照的 revert 支援，
> 但**各發行版帶的版本不同**。動手前：
> ```bash
> virsh version
> virsh help snapshot-revert
> ```
> 並在**測試 VM** 上完整走一次「建快照 → 改東西 → revert → 確認回到舊狀態」。

> [!tip] ★★★★★ 本手冊的建議
> **單機 KVM 的日常快照，用內部快照（qcow2）。** 它的 revert 支援最穩定，
> 指令最簡單，適合「改設定前先留一手」這個最常見的需求。
>
> **要做備份就不要用快照，用備份。** 快照不是備份——
> 快照跟原磁碟在同一顆實體硬碟上，硬碟壞了兩個一起沒。
> 備份觀念見 [[050-01-03-06-svc-PVE-備份與還原]]。

#### ★★★★ 快照與記憶體狀態

在 VM **執行中**做內部快照，libvirt 預設會**一併儲存記憶體狀態**：

```bash
virsh snapshot-create-as web01 before-upgrade "升級前"
```

```text
Domain snapshot before-upgrade created
```

revert 之後，VM 會回到**當時執行中的那一瞬間**（連正在跑的程式都還在）。
這跟 VMware 的「含記憶體快照」是同一件事。

★★★★ 代價：
- 快照建立時 VM 會**短暫暫停**（要把記憶體寫出去），記憶體越大暫停越久
- 快照檔會大很多（多出約等於記憶體大小的量）

只要磁碟狀態不要記憶體：

```bash
virsh shutdown web01           # 關機後做，最乾淨
virsh snapshot-create-as web01 clean-install "乾淨安裝"
```

### ★★★★ `virsh console`：救命工具

當客體的 SSH 進不去（防火牆設錯、網路設定錯、開機卡住），
`virsh console` 是你**唯一的進入方式**。

```bash
virsh console web01
```

```text
Connected to domain 'web01'
Escape character is ^] (Ctrl + ])
```

★★★★★ **記住退出鍵是 `Ctrl + ]`**（Ctrl 加右中括號）。
不是 `Ctrl+C`（那會傳給客體）、不是 `exit`。

> [!warning] ★★★★★ `virsh console` 沒有畫面的兩個原因
> 連上去之後一片空白，按 Enter 也沒反應。原因幾乎一定是這兩個之一：
>
> **原因 1：VM 沒有序列主控台裝置**
> ```bash
> virsh dumpxml web01 | grep -A2 '<console'
> ```
> ```text
>     <console type='pty' tty='/dev/pts/1'>
>       <source path='/dev/pts/1'/>
>       <target type='serial' port='0'/>
> ```
> 沒有這一段就要加（見下方實戰）。
>
> **原因 2（更常見）：客體沒有把輸出導到序列埠** ★★★★★
> 一般安裝的 Linux 只把訊息輸出到虛擬顯示卡。要讓序列埠有東西，
> 客體裡要設定 GRUB（見下方「進階應用」）。

### ★★★ 遷移：`migrate --live`

把執行中的 VM 從一台主機搬到另一台，**客體不中斷**（PVE 後台的 Migrate、VMware 的 vMotion）。

```bash
virsh migrate --live --verbose web01 qemu+ssh://kvm02/system
```

★★★★★ **前提條件（缺一不可）**：

| 前提 | 說明 |
| --- | --- |
| **兩端都能用 KVM** ★★★★★ | 廢話但常被忽略 |
| **CPU 相容** ★★★★★ | 目標主機的 CPU 必須支援來源主機客體看到的所有指令集。**`host-passthrough` 是最大的地雷** |
| **共用儲存** ★★★★★ | 兩端要能用**同一個路徑**存取同一份磁碟（NFS、iSCSI、Ceph）。沒有共用儲存就要加 `--copy-storage-all`（慢很多） |
| **網路相通** ★★★★ | 兩端的橋接／VLAN 設定要一致，不然搬過去網路就斷了 |
| **SSH 金鑰互通** ★★★★ | `qemu+ssh://` 要能免密碼連 |
| **QEMU / machine type 相容** ★★★★ | 目標主機的 QEMU 要支援來源的 machine type |

> [!danger] ★★★★★ `host-passthrough` + 遷移 = 客體崩潰
> `<cpu mode='host-passthrough'/>` 會把來源主機 CPU 的**完整指令集**暴露給客體。
> 客體的程式（尤其是編譯過最佳化的函式庫）會用上那些指令。
> 搬到指令集較少的 CPU 上，客體會在執行到那些指令時**直接崩潰**（illegal instruction）。
>
> 要能遷移，CPU 必須改成**具名 model** 或 `host-model`：
> ```xml
> <cpu mode='custom' match='exact' check='partial'>
>   <model fallback='allow'>Nehalem</model>
> </cpu>
> ```
> ★★★★ **準則跟 PVE 完全一樣：以叢集裡最舊的那台 CPU 為準**
> （見 [[050-01-03-03-guide-PVE-虛擬機管理]]）。

★★★★ 兩個重要旗標：

```bash
# 讓 VM 在目標主機上變成 persistent（不加的話搬過去是暫態的！）
virsh migrate --live --persistent web01 qemu+ssh://kvm02/system

# 搬完把來源端的定義刪掉（不然兩邊都有定義，很容易誤開）
virsh migrate --live --persistent --undefinesource web01 qemu+ssh://kvm02/system
```

> [!warning] ★★★★★ 不加 `--persistent` 的後果
> 遷移過去的 VM 在目標主機上是**暫態 domain**。目標主機重開機後 VM 就消失了。
> 這是遷移最常被忽略的細節。

### ★★★ 沒有共用儲存的遷移

單機 KVM 環境通常沒有共用儲存。`--copy-storage-all` 可以連磁碟一起搬：

```bash
# 目標主機上要先建好同樣大小的空磁碟檔
# 在 kvm02 上：
qemu-img create -f qcow2 /var/lib/libvirt/images/web01.qcow2 20G
```

```bash
# 來源主機上：
virsh migrate --live --persistent --copy-storage-all \
  web01 qemu+ssh://kvm02/system
```

★★★ 這會把整顆磁碟透過網路複製過去，**很慢**（20 GB 在 1 Gbps 上要幾分鐘），
而且過程中 VM 的寫入要同步到兩邊。**小型環境用「關機 → `scp` 磁碟 → 目標端 `define`」
反而更快更可靠。**

---

## 安裝或基礎操作

★★★★ 每一節都給「輸入 → 你會看到什麼」。假設你已完成 02 篇，
手上有一台叫 `web01` 的 VM。

### ★★★★ 查詢類（安全，可隨便跑）

```bash
virsh uri
```

```text
qemu:///system
```

```bash
virsh list --all
```

```text
 Id   Name    State
-----------------------
 1    web01   running
```

```bash
virsh domstate web01
```

```text
running
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
CPU time:       412.3s
Max memory:     2097152 KiB
Used memory:    2097152 KiB
Persistent:     yes
Autostart:      enable
Managed save:   no
Security model: apparmor
Security DOI:   0
```

★★★★ 三個一定要看的欄位：**`State`**、**`Persistent`**、**`Autostart`**。

```bash
virsh domblklist web01
```

```text
 Target   Source
---------------------------------------------
 vda      /var/lib/libvirt/images/web01.qcow2
```

```bash
virsh domiflist web01
```

```text
 Interface   Type      Source    Model    MAC
-----------------------------------------------------------------
 vnet0       network   default   virtio   52:54:00:a3:1f:8c
```

```bash
virsh domifaddr web01
```

```text
 Name       MAC address          Protocol     Address
-------------------------------------------------------------------------------
 vnet0      52:54:00:a3:1f:8c    ipv4         192.168.122.87/24
```

★★★★ 橋接網路查不到 IP 時：

```bash
virsh domifaddr web01 --source agent
```

```bash
virsh domblkinfo web01 vda
```

```text
Capacity:       21474836480
Allocation:     9345789952
Physical:       9345789952
```

★★★★ `Capacity` 是虛擬大小，`Allocation` 是實際佔用（qcow2 精簡配置）。

### ★★★★★ 生命週期類（會改變狀態，小心）

```bash
virsh start web01
```

```text
Domain 'web01' started
```

```bash
virsh shutdown web01
```

```text
Domain 'web01' is being shutdown
```

★★★★ 注意訊息是 **"is being shutdown"**（正在關機中），
指令**立刻返回**，不代表關完了。要等就自己輪詢：

```bash
while [ "$(virsh domstate web01)" != "shut off" ]; do sleep 2; done; echo "已關機"
```

```text
已關機
```

```bash
virsh reboot web01
```

```text
Domain 'web01' is being rebooted
```

★★★★★ 再說一次：**`reboot` 不會套用硬體設定變更**。

```bash
virsh destroy web01
```

```text
Domain 'web01' destroyed
```

★★★★★ **這是拔插頭，不是刪除。**

```bash
virsh suspend web01     # 暫停（凍結 vCPU，記憶體仍佔用）
```

```text
Domain 'web01' suspended
```

```bash
virsh resume web01
```

```text
Domain 'web01' resumed
```

★★★ `suspend` 只是暫停執行，記憶體**還在主機 RAM 裡**，不省記憶體。
要真的釋放記憶體用 `managedsave`：

```bash
virsh managedsave web01
```

```text
Domain 'web01' state saved by libvirt
```

★★★★ 這會把記憶體狀態寫到磁碟然後關掉 VM（類似筆電的休眠）。
下次 `virsh start` 會從那個狀態恢復。

```bash
virsh dominfo web01 | grep 'Managed save'
```

```text
Managed save:   yes
```

> [!warning] ★★★★ `Managed save: yes` 是一個容易忘記的狀態
> 有 managedsave 檔存在時，`virsh start` **會忽略你對 XML 的所有修改**
> （因為它是從記憶體映像恢復，硬體必須完全一樣）。
> 要丟掉這個狀態做乾淨開機：
> ```bash
> virsh managedsave-remove web01
> virsh start web01
> ```

### ★★★★ 自動啟動

```bash
virsh autostart web01
```

```text
Domain 'web01' marked as autostarted
```

```bash
virsh autostart --disable web01
```

```text
Domain 'web01' unmarked as autostarted
```

★★★ 它實際上做的事是建一個符號連結：

```bash
ls -l /etc/libvirt/qemu/autostart/
```

```text
lrwxrwxrwx 1 root root 30 Sep  2 11:22 web01.xml -> /etc/libvirt/qemu/web01.xml
```

```bash
virsh list --all --autostart
```

```text
 Id   Name    State
-----------------------
 1    web01   running
```

### ★★★★ 改設定

```bash
virsh dumpxml web01 > /root/web01-backup.xml
```

★★★★★ **改任何東西之前先備份 XML**，這是零成本的保險。

```bash
EDITOR=vim virsh edit web01
```

存檔後：

```text
Domain 'web01' XML configuration edited.
```

語法錯誤時：

```text
error: XML error: Unknown mode 'host-passthroughh' in CPU mode
Failed. Try again? [y,n,i,f,?]:
```

★★★★ 選 `y` 回去修，`n` 放棄修改，`i` 強制接受（**不建議**）。

命令列改法：

```bash
virsh setmem web01 4194304 --config      # 單位是 KiB，4 GiB
virsh setvcpus web01 4 --config
```

```bash
virt-xml web01 --edit --memory 4096,currentMemory=4096 --config
```

```text
Domain 'web01' defined successfully.
Changes will take effect after the domain is fully powered off.
```

★★★★★ 注意最後那句提示：**"after the domain is fully powered off"**。

### ★★★★ 快照

```bash
virsh snapshot-create-as web01 snap01 "第一個快照"
```

```text
Domain snapshot snap01 created
```

```bash
virsh snapshot-list web01
```

```text
 Name     Creation Time               State
------------------------------------------------
 snap01   2026-09-02 11:31:04 +0800   running
```

★★★ `State` 是 `running` 代表快照含記憶體狀態；VM 關機時做的會是 `shutoff`。

```bash
virsh snapshot-info web01 snap01
```

```text
Name:           snap01
Domain:         web01
Current:        yes
State:          running
Location:       internal
Parent:         -
Children:       0
Descendants:    0
Metadata:       yes
```

★★★★★ **`Location: internal`** 就是內部快照。

```bash
virsh snapshot-revert web01 snap01
```

（成功時沒有輸出）

```bash
virsh snapshot-delete web01 snap01
```

```text
Domain snapshot snap01 deleted
```

### ★★★★ 主控台

```bash
virsh console web01
```

```text
Connected to domain 'web01'
Escape character is ^] (Ctrl + ])

Ubuntu 24.04 LTS web01 ttyS0

web01 login:
```

★★★★★ 退出：**`Ctrl + ]`**

---

## 進階應用

### ★★★★★ 讓 `virsh console` 真的有畫面（客體端設定）

這是本篇最實用的技巧之一。分兩邊做。

#### 主機端：確認有序列裝置

```bash
virsh dumpxml web01 | grep -A3 '<serial\|<console'
```

沒有的話加上（VM 要關機）：

```bash
virsh shutdown web01
virt-xml web01 --add-device --console pty,target_type=serial
```

```text
Domain 'web01' defined successfully.
```

或用 `virsh edit` 在 `<devices>` 裡加：

```xml
<serial type='pty'>
  <target type='isa-serial' port='0'>
    <model name='isa-serial'/>
  </target>
</serial>
<console type='pty'>
  <target type='serial' port='0'/>
</console>
```

#### ★★★★★ 客體端：把核心訊息導到序列埠

先在客體裡（透過 SSH 或圖形主控台）：

```bash
sudo vim /etc/default/grub
```

```ini
GRUB_CMDLINE_LINUX_DEFAULT=""
GRUB_CMDLINE_LINUX="console=tty0 console=ttyS0,115200n8"
GRUB_TERMINAL="console serial"
GRUB_SERIAL_COMMAND="serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1"
```

```bash
sudo update-grub
```

```text
Sourcing file `/etc/default/grub'
Generating grub configuration file ...
Found linux image: /boot/vmlinuz-6.8.0-45-generic
done
```

```bash
sudo systemctl enable --now serial-getty@ttyS0.service
sudo reboot
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> 檔案位置一樣是 `/etc/default/grub`，但重建設定的指令不同：
>
> ```bash
> # BIOS 開機
> sudo grub2-mkconfig -o /boot/grub2/grub.cfg
>
> # UEFI 開機
> sudo grub2-mkconfig -o /boot/efi/EFI/rocky/grub.cfg
> ```
>
> 更推薦的做法是用 `grubby`（RHEL 系的工具）：
> ```bash
> sudo grubby --update-kernel=ALL --args="console=tty0 console=ttyS0,115200n8"
> ```
>
> 然後一樣：
> ```bash
> sudo systemctl enable --now serial-getty@ttyS0.service
> ```

重開機後：

```bash
# 主機上
virsh console web01
```

```text
Connected to domain 'web01'
Escape character is ^] (Ctrl + ])

[    0.000000] Linux version 6.8.0-45-generic ...
[    1.204118] systemd[1]: Detected virtualization kvm.
...
Ubuntu 24.04 LTS web01 ttyS0

web01 login: ops
Password:
```

★★★★★ **現在你連客體的開機訊息都看得到**。
SSH 進不去、開機卡在 fsck、網路設定改壞——全部救得回來。

> [!tip] ★★★★★ 這一步應該做在範本裡
> 把序列主控台設好之後再做成範本，之後複製出來的每一台 VM 都有這個保險。
> 見 [[050-01-04-05-guide-KVM-自動化與範本]]。

### ★★★★ 熱插拔：不關機加磁碟與網卡

```bash
# 先建一個新磁碟
sudo qemu-img create -f qcow2 /var/lib/libvirt/images/web01-data.qcow2 10G
```

```text
Formatting '/var/lib/libvirt/images/web01-data.qcow2', fmt=qcow2 cluster_size=65536 extended_l2=off compression_type=zlib size=10737418240 lazy_refcounts=off refcount_bits=16
```

```bash
virsh attach-disk web01 \
  /var/lib/libvirt/images/web01-data.qcow2 vdb \
  --driver qemu --subdriver qcow2 --targetbus virtio \
  --live --config
```

```text
Disk attached successfully
```

★★★★★ **`--live --config` 兩個都要加**：
- `--live` = 立刻對執行中的 VM 生效
- `--config` = 也寫進定義檔，下次開機還在
- **只加 `--live`** → 重開機後磁碟不見了
- **只加 `--config`** → 現在看不到，要重開機

客體裡驗證：

```bash
# 客體內
lsblk
```

```text
NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINTS
vda    252:0    0   20G  0 disk
├─vda1 252:1    0    1M  0 part
├─vda2 252:2    0  1.8G  0 part /boot
└─vda3 252:3    0 18.2G  0 part /
vdb    252:16   0   10G  0 disk
```

✅ `vdb` 出現了，不用重開機。

移除：

```bash
virsh detach-disk web01 vdb --live --config
```

```text
Disk detached successfully
```

> [!danger] ★★★★★ 拔磁碟前一定要先在客體裡 `umount`
> 直接 `detach-disk` 一個掛載中的磁碟，等同於**熱拔硬碟**，
> 檔案系統會損毀。正確順序：
> 1. 客體裡 `sudo umount /mnt/data`
> 2. 客體裡把 `/etc/fstab` 的那一行移除
> 3. 主機上 `virsh detach-disk`

網卡也一樣：

```bash
virsh attach-interface web01 --type network --source default \
  --model virtio --live --config
```

```text
Interface attached successfully
```

### ★★★★ 批次操作

```bash
# 全部優雅關機
for d in $(virsh list --name); do
  echo "關閉 $d ..."
  virsh shutdown "$d"
done
```

```text
關閉 web01 ...
Domain 'web01' is being shutdown
關閉 db01 ...
Domain 'db01' is being shutdown
```

```bash
# 等全部關完（最多等 120 秒）
timeout 120 bash -c 'while [ -n "$(virsh list --name)" ]; do sleep 3; done' \
  && echo "全部已關機" || echo "逾時，還有 VM 在跑"
```

```text
全部已關機
```

```bash
# 全部開機
for d in $(virsh list --name --inactive); do virsh start "$d"; done
```

```text
Domain 'web01' started
Domain 'db01' started
```

```bash
# 檢查所有 VM 的 autostart 狀態（★★★★ 接手環境必做）
for d in $(virsh list --all --name); do
  [ -n "$d" ] && printf "%-12s %s\n" "$d" "$(virsh dominfo "$d" | awk '/Autostart/{print $2}')"
done
```

```text
web01        enable
db01         disable
```

★★★★ `db01` 是 `disable`，主機重開機後不會回來。

```bash
# 備份所有 VM 的定義（★★★★★ 建議寫成每日 cron）
mkdir -p /root/libvirt-backup/$(date +%F)
for d in $(virsh list --all --name); do
  [ -n "$d" ] && virsh dumpxml "$d" > "/root/libvirt-backup/$(date +%F)/$d.xml"
done
ls /root/libvirt-backup/$(date +%F)/
```

```text
db01.xml  web01.xml
```

### ★★★ 外部快照與 `blockcommit`（備份用法）

外部快照最實用的場景不是「回復」，而是**做一致性備份**：

```bash
# 1. 建立外部快照（原磁碟凍結成唯讀，新寫入到 overlay）
virsh snapshot-create-as web01 backup-tmp \
  --disk-only --atomic --no-metadata \
  --diskspec vda,file=/var/lib/libvirt/images/web01-overlay.qcow2
```

```text
Domain snapshot backup-tmp created
```

```bash
virsh domblklist web01
```

```text
 Target   Source
-----------------------------------------------------
 vda      /var/lib/libvirt/images/web01-overlay.qcow2
```

★★★★ 現在原本的 `web01.qcow2` 是**唯讀且狀態凍結的**，可以安全複製：

```bash
# 2. 複製原檔（這是你的備份）
sudo cp /var/lib/libvirt/images/web01.qcow2 /backup/web01-$(date +%F).qcow2
```

```bash
# 3. 把 overlay 合併回原檔，恢復原本的結構
virsh blockcommit web01 vda --active --pivot --verbose
```

```text
Block commit: [100 %]
Successfully pivoted
```

```bash
virsh domblklist web01
```

```text
 Target   Source
---------------------------------------------
 vda      /var/lib/libvirt/images/web01.qcow2
```

```bash
sudo rm /var/lib/libvirt/images/web01-overlay.qcow2
```

> [!warning] ★★★★★ 用 `--no-metadata` 的理由與代價
> `--no-metadata` 讓 libvirt 不保留快照的中繼資料，
> 這樣做完 `blockcommit` 之後不會留下一個「指向已不存在檔案」的殭屍快照記錄。
> 代價是**這個快照不能用 `snapshot-revert` 回復**——但我們本來就是拿它做備份，
> 不是拿來回復的。
>
> ★★★★★ **`blockcommit` 失敗時千萬不要手動刪 overlay 檔**，
> 那會讓 VM 的磁碟鏈斷掉，資料就真的救不回來了。先確認 `blockcommit` 成功。

> [!tip] ★★★★ 加上 guest agent 讓備份一致
> 上面的流程在客體「執行中」做，檔案系統可能有未寫入的資料。
> 加 `--quiesce` 會透過 `qemu-guest-agent` 先凍結客體檔案系統：
> ```bash
> virsh snapshot-create-as web01 backup-tmp --disk-only --atomic \
>   --quiesce --no-metadata --diskspec vda,file=/var/lib/libvirt/images/web01-overlay.qcow2
> ```
> 客體必須裝 `qemu-guest-agent`，否則會報
> `error: argument unsupported: QEMU guest agent is not configured`。

### ★★★★★ `virsh` 與 PVE `qm` 完整對照表

★★★★★ **這張表建議印出來貼在旁邊。**

| 做什麼 | `virsh`（KVM/libvirt） | `qm`（Proxmox VE） |
| --- | --- | --- |
| 列出所有 VM ★★★★★ | `virsh list --all` | `qm list` |
| 列出執行中 ★★★★ | `virsh list` | `qm list \| grep running` |
| 看 VM 設定 ★★★★★ | `virsh dumpxml <name>` | `qm config <vmid>` |
| 改設定（互動）★★★★★ | `virsh edit <name>` | `nano /etc/pve/qemu-server/<vmid>.conf` |
| 改設定（指令）★★★★ | `virt-xml <name> --edit ...` | `qm set <vmid> --<key> <value>` |
| 開機 ★★★★★ | `virsh start <name>` | `qm start <vmid>` |
| 優雅關機 ★★★★★ | `virsh shutdown <name>` | `qm shutdown <vmid>` |
| **強制斷電** ★★★★★ | **`virsh destroy <name>`** | **`qm stop <vmid>`** |
| **刪除 VM** ★★★★★ | **`virsh undefine <name>`** | **`qm destroy <vmid>`** |
| 刪除含磁碟 ★★★★★ | `virsh undefine <name> --remove-all-storage` | `qm destroy <vmid> --purge` |
| 重開機 ★★★★ | `virsh reboot <name>` | `qm reboot <vmid>` |
| 暫停 ★★★ | `virsh suspend <name>` | `qm suspend <vmid>` |
| 恢復 ★★★ | `virsh resume <name>` | `qm resume <vmid>` |
| 主控台（文字）★★★★★ | `virsh console <name>`（退出 `Ctrl+]`） | `qm terminal <vmid>` |
| 狀態 ★★★★ | `virsh domstate <name>` | `qm status <vmid>` |
| 開機自動啟動 ★★★★★ | `virsh autostart <name>` | `qm set <vmid> --onboot 1` |
| 列出磁碟 ★★★★ | `virsh domblklist <name>` | `qm config <vmid> \| grep -E 'scsi\|virtio\|ide\|sata'` |
| 列出網卡 ★★★★ | `virsh domiflist <name>` | `qm config <vmid> \| grep net` |
| 查客體 IP ★★★★ | `virsh domifaddr <name> --source agent` | `qm guest cmd <vmid> network-get-interfaces` |
| 建快照 ★★★★★ | `virsh snapshot-create-as <name> <snap>` | `qm snapshot <vmid> <snap>` |
| 列快照 ★★★★ | `virsh snapshot-list <name>` | `qm listsnapshot <vmid>` |
| 回復快照 ★★★★★ | `virsh snapshot-revert <name> <snap>` | `qm rollback <vmid> <snap>` |
| 刪快照 ★★★★ | `virsh snapshot-delete <name> <snap>` | `qm delsnapshot <vmid> <snap>` |
| 複製 VM ★★★★ | `virt-clone --original <a> --name <b> --auto-clone` | `qm clone <vmid> <newid>` |
| 做成範本 ★★★★ | （手動流程，見 05 篇） | `qm template <vmid>` |
| 線上遷移 ★★★★ | `virsh migrate --live --persistent <name> qemu+ssh://<host>/system` | `qm migrate <vmid> <node> --online` |
| 改記憶體 ★★★★ | `virsh setmem <name> <KiB> --config` | `qm set <vmid> --memory <MB>` |
| 改 CPU 數 ★★★★ | `virsh setvcpus <name> <n> --config` | `qm set <vmid> --cores <n>` |
| 加磁碟 ★★★★ | `virsh attach-disk ... --live --config` | `qm set <vmid> --scsi1 <storage>:<size>` |
| 調整磁碟大小 ★★★★ | `qemu-img resize <file> +10G` + `virsh blockresize` | `qm resize <vmid> scsi0 +10G` |
| 建立 VM ★★★★ | `virt-install ...` | `qm create <vmid> ...` |
| 匯入磁碟 ★★★★ | `virt-install --import --disk ...` | `qm importdisk <vmid> <file> <storage>` |
| 設定檔位置 ★★★★★ | `/etc/libvirt/qemu/<name>.xml` | `/etc/pve/qemu-server/<vmid>.conf` |
| 磁碟位置 ★★★★ | `/var/lib/libvirt/images/` | 由 storage 定義（`pvesm status`） |
| 主要 log ★★★★★ | `/var/log/libvirt/qemu/<name>.log` | `/var/log/pve/tasks/`、`journalctl -u pvedaemon` |

★★★★★ **表格裡最危險的兩列已加粗**：`destroy` 與 `undefine` 在兩個平台的意義是**反的**。

---

## 完整實戰範例

### 目標

把 02 篇用 `virt-manager` 做過的事情，**全部改用 `virsh` 指令重做一次**，
並額外完成 GUI 做不到或很麻煩的操作：XML 編輯、序列主控台、快照與回復、
熱插拔磁碟、批次備份。

★★★★ 全程在 KVM 主機的終端機上完成，**不需要任何圖形介面**。

### 步驟 0：環境確認

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

```bash
virsh list --all
```

```text
 Id   Name    State
-----------------------
 1    web01   running
```

### 步驟 1：先備份定義（★★★★★ 每次動手前的固定動作）

```bash
sudo mkdir -p /root/libvirt-backup
virsh dumpxml web01 > /root/libvirt-backup/web01-before.xml
wc -l /root/libvirt-backup/web01-before.xml
```

```text
78 /root/libvirt-backup/web01-before.xml
```

### 步驟 2：完整盤點這台 VM

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
Autostart:      enable
Managed save:   no
Security model: apparmor
Security DOI:   0
```

```bash
virsh domblklist web01 && virsh domiflist web01 && virsh domifaddr web01
```

```text
 Target   Source
---------------------------------------------
 vda      /var/lib/libvirt/images/web01.qcow2

 Interface   Type      Source    Model    MAC
-----------------------------------------------------------------
 vnet0       network   default   virtio   52:54:00:a3:1f:8c

 Name       MAC address          Protocol     Address
-------------------------------------------------------------------------------
 vnet0      52:54:00:a3:1f:8c    ipv4         192.168.122.87/24
```

### 步驟 3：設定序列主控台（GUI 做不到的部分）

先關機（加序列裝置屬於硬體變更）：

```bash
virsh shutdown web01
while [ "$(virsh domstate web01)" != "shut off" ]; do sleep 2; done
virsh domstate web01
```

```text
shut off
```

```bash
virsh dumpxml web01 | grep -c '<console'
```

```text
1
```

★★★ 已經有了（02 篇加過）。沒有的話：

```bash
virt-xml web01 --add-device --console pty,target_type=serial
```

```text
Domain 'web01' defined successfully.
```

```bash
virsh start web01
```

```text
Domain 'web01' started
```

現在到客體裡設定 GRUB：

```bash
ssh ops@192.168.122.87
```

```bash
# 客體內
sudo sed -i 's/^GRUB_CMDLINE_LINUX=.*/GRUB_CMDLINE_LINUX="console=tty0 console=ttyS0,115200n8"/' /etc/default/grub
grep GRUB_CMDLINE_LINUX= /etc/default/grub
```

```text
GRUB_CMDLINE_LINUX="console=tty0 console=ttyS0,115200n8"
```

```bash
# 客體內
sudo update-grub && sudo systemctl enable --now serial-getty@ttyS0.service
sudo reboot
```

```text
Generating grub configuration file ...
done
Created symlink /etc/systemd/system/getty.target.wants/serial-getty@ttyS0.service ...
```

回到主機測試：

```bash
virsh console web01
```

```text
Connected to domain 'web01'
Escape character is ^] (Ctrl + ])

Ubuntu 24.04 LTS web01 ttyS0

web01 login:
```

✅ 有畫面了。★★★★★ 按 **`Ctrl + ]`** 退出。

### 步驟 4：建立快照（改動前的保險）

```bash
virsh snapshot-create-as web01 baseline "序列主控台設定完成的乾淨狀態"
```

```text
Domain snapshot baseline created
```

```bash
virsh snapshot-list web01
```

```text
 Name       Creation Time               State
--------------------------------------------------
 baseline   2026-09-02 13:04:21 +0800   running
```

```bash
virsh snapshot-info web01 baseline | grep Location
```

```text
Location:       internal
```

★★★★ 確認是 `internal`（內部快照），revert 支援最穩定。

```bash
sudo qemu-img info /var/lib/libvirt/images/web01.qcow2 | tail -8
```

```text
Snapshot list:
ID        TAG              VM_SIZE                DATE     VM_CLOCK     ICOUNT
1         baseline           2.03 GiB 2026-09-02 13:04:21 00:41:12.831          0
Format specific information:
    compat: 1.1
    lazy refcounts: true
    refcount bits: 16
```

★★★★ **`VM_SIZE 2.03 GiB` 就是被存下來的記憶體狀態**，等於 VM 的記憶體大小。

### 步驟 5：故意搞壞，然後回復（驗證快照真的能用）

★★★★★ **這一步是本篇最重要的實作。快照沒測過就不算有快照。**

```bash
ssh ops@192.168.122.87
```

```bash
# 客體內：做一個明顯的破壞
sudo mv /etc/ssh/sshd_config /etc/ssh/sshd_config.broken
echo "Port 9999" | sudo tee /etc/ssh/sshd_config
sudo systemctl restart ssh
```

```text
Port 9999
```

```bash
# 從主機上：SSH 果然連不上了
ssh -o ConnectTimeout=5 ops@192.168.122.87
```

```text
ssh: connect to host 192.168.122.87 port 22: Connection refused
```

★★★★ 這就是「SSH 進不去」的情境。**先用序列主控台確認 VM 還活著**：

```bash
virsh console web01
```

```text
Connected to domain 'web01'
Escape character is ^] (Ctrl + ])

web01 login:
```

（`Ctrl + ]` 退出）

現在回復快照：

```bash
virsh snapshot-revert web01 baseline
```

（成功時沒有輸出）

```bash
virsh domstate web01
```

```text
running
```

★★★★ VM **直接回到快照當時的執行狀態**，不需要重新開機。

```bash
ssh ops@192.168.122.87 'ls -l /etc/ssh/sshd_config'
```

```text
-rw-r--r-- 1 root root 3253 Mar 20 09:11 /etc/ssh/sshd_config
```

✅ **檔案回來了，SSH 也通了。** 快照確實可用。

### 步驟 6：修改硬體設定（示範「什麼時候才生效」）

把記憶體從 2 GB 改成 3 GB：

```bash
virt-xml web01 --edit --memory 3072,currentMemory=3072 --config
```

```text
Domain 'web01' defined successfully.
Changes will take effect after the domain is fully powered off.
```

★★★★★ **注意那句提示。** 先示範 `reboot` 無效：

```bash
virsh reboot web01
sleep 30
virsh dominfo web01 | grep -i memory
```

```text
Max memory:     2097152 KiB
Used memory:    2097152 KiB
```

★★★★★ **還是 2 GB。`reboot` 不會套用硬體變更。**

正確做法：

```bash
virsh shutdown web01
while [ "$(virsh domstate web01)" != "shut off" ]; do sleep 2; done
virsh start web01
virsh dominfo web01 | grep -i memory
```

```text
Max memory:     3145728 KiB
Used memory:    3145728 KiB
```

✅ 現在是 3 GB。客體裡驗證：

```bash
ssh ops@192.168.122.87 'free -h | head -2'
```

```text
               total        used        free      shared  buff/cache   available
Mem:           2.9Gi       246Mi       2.4Gi       1.0Mi       334Mi       2.6Gi
```

### 步驟 7：熱插拔一顆資料磁碟

```bash
sudo qemu-img create -f qcow2 /var/lib/libvirt/images/web01-data.qcow2 10G
```

```text
Formatting '/var/lib/libvirt/images/web01-data.qcow2', fmt=qcow2 cluster_size=65536 extended_l2=off compression_type=zlib size=10737418240 lazy_refcounts=off refcount_bits=16
```

```bash
virsh attach-disk web01 /var/lib/libvirt/images/web01-data.qcow2 vdb \
  --driver qemu --subdriver qcow2 --targetbus virtio --live --config
```

```text
Disk attached successfully
```

```bash
virsh domblklist web01
```

```text
 Target   Source
--------------------------------------------------
 vda      /var/lib/libvirt/images/web01.qcow2
 vdb      /var/lib/libvirt/images/web01-data.qcow2
```

客體裡（**不用重開機**）：

```bash
ssh ops@192.168.122.87
```

```bash
# 客體內
lsblk | grep vdb
```

```text
vdb    252:16   0   10G  0 disk
```

```bash
# 客體內：格式化並掛載
sudo mkfs.ext4 -L data /dev/vdb
sudo mkdir -p /srv/data
echo "LABEL=data /srv/data ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab
sudo mount -a
df -h /srv/data
```

```text
Filesystem      Size  Used Avail Use% Mounted on
/dev/vdb        9.8G   24K  9.3G   1% /srv/data
```

★★★★ **`nofail` 很重要**：萬一哪天磁碟被拔掉，客體不會卡在開機時的 fsck。

### 步驟 8：用 `virsh edit` 直接改 XML

示範改磁碟的 discard 設定（讓客體刪檔後空間還回主機）：

```bash
virsh shutdown web01
while [ "$(virsh domstate web01)" != "shut off" ]; do sleep 2; done
EDITOR=vim virsh edit web01
```

在編輯器裡找到 `vda` 那段，把：

```xml
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source file='/var/lib/libvirt/images/web01.qcow2'/>
      <target dev='vda' bus='virtio'/>
```

改成：

```xml
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' discard='unmap'/>
      <source file='/var/lib/libvirt/images/web01.qcow2'/>
      <target dev='vda' bus='virtio'/>
```

存檔：

```text
Domain 'web01' XML configuration edited.
```

```bash
virsh start web01
virsh dumpxml web01 | grep discard
```

```text
      <driver name='qemu' type='qcow2' discard='unmap'/>
```

驗證 TRIM 真的通了：

```bash
ssh ops@192.168.122.87 'sudo fstrim -av'
```

```text
/srv/data: 9.2 GiB (9876543210 bytes) trimmed on /dev/vdb
/: 16.1 GiB (17284567890 bytes) trimmed on /dev/vda3
```

✅ 有輸出就代表 discard 鏈路打通了 ★★★★。

### 步驟 9：故意犯錯——`destroy` 之後會怎樣

★★★★★ **在測試 VM 上做，不要在正式機上做。**

```bash
virsh destroy web01
```

```text
Domain 'web01' destroyed
```

```bash
virsh list --all
```

```text
 Id   Name    State
-----------------------
 -    web01   shut off
```

★★★★★ **VM 沒有被刪掉**，只是被強制斷電了。

```bash
virsh start web01
sleep 40
virsh console web01
```

在主控台裡可能會看到（視當時是否有未寫入的資料）：

```text
[    3.421887] EXT4-fs (vda3): recovery complete
[    3.428104] EXT4-fs (vda3): mounted filesystem ... with ordered data mode
```

★★★★ **`recovery complete` 就是檔案系統在做 journal 復原**——
這是強制斷電的直接後果。這次只是 journal 能救回來；
如果當時剛好在寫資料庫，情況會嚴重得多。

### 步驟 10：清理快照

```bash
virsh snapshot-list web01
```

```text
 Name       Creation Time               State
--------------------------------------------------
 baseline   2026-09-02 13:04:21 +0800   running
```

```bash
virsh snapshot-delete web01 baseline
```

```text
Domain snapshot baseline deleted
```

```bash
sudo qemu-img info /var/lib/libvirt/images/web01.qcow2 | grep -A2 'Snapshot list' || echo "沒有快照了"
```

```text
沒有快照了
```

★★★★ **快照留著會持續佔空間並拖慢寫入**，用完就刪。

### 步驟 11：建立每日 XML 備份的排程

```bash
sudo tee /usr/local/sbin/backup-libvirt-xml.sh > /dev/null <<'EOF'
#!/bin/bash
set -euo pipefail
DEST="/root/libvirt-backup/$(date +%F)"
mkdir -p "$DEST"
for d in $(virsh list --all --name); do
  [ -n "$d" ] || continue
  virsh dumpxml "$d" > "$DEST/$d.xml"
done
# 保留 30 天
find /root/libvirt-backup -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
echo "$(date '+%F %T') 備份完成：$DEST"
EOF
sudo chmod 750 /usr/local/sbin/backup-libvirt-xml.sh
sudo /usr/local/sbin/backup-libvirt-xml.sh
```

```text
2026-09-02 13:48:02 備份完成：/root/libvirt-backup/2026-09-02
```

```bash
sudo tee /etc/cron.d/libvirt-xml-backup > /dev/null <<'EOF'
15 2 * * * root /usr/local/sbin/backup-libvirt-xml.sh >> /var/log/libvirt-xml-backup.log 2>&1
EOF
sudo systemctl restart cron
```

> [!warning] ★★★★ 這只備份「設定」，不是備份「資料」
> XML 只有幾 KB，備份很便宜，而且重建 VM 時省下大量時間。
> 但**磁碟映像要另外備份**（見「進階應用 → 外部快照與 blockcommit」）。
> 完整的備份策略觀念見 [[050-01-03-06-svc-PVE-備份與還原]]。

### 步驟 12：最終確認

```bash
virsh list --all
```

```text
 Id   Name    State
-----------------------
 3    web01   running
```

```bash
virsh dominfo web01 | grep -E 'State|Persistent|Autostart|Managed'
```

```text
State:          running
Persistent:     yes
Autostart:      enable
Managed save:   no
```

```bash
virsh dumpxml web01 | grep -E "domain type|bus=|model type|discard"
```

```text
<domain type='kvm'>
      <driver name='qemu' type='qcow2' discard='unmap'/>
      <target dev='vda' bus='virtio'/>
      <target dev='vdb' bus='virtio'/>
      <model type='virtio'/>
```

✅ **全部到位**：KVM 加速、VirtIO 磁碟與網卡、discard 打通、
持久定義、自動啟動、序列主控台可用、快照驗證過、XML 每日備份。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| 打了 `virsh destroy` 以為是刪除，結果服務中斷 ★★★★★ | **`destroy` 是強制斷電，不是刪除** | 開機後檢查客體檔案系統；記住 `destroy`＝PVE 的 `qm stop`，刪除是 `undefine` |
| `virsh undefine` 之後磁碟空間沒釋放 ★★★★★ | `undefine` 預設**不刪磁碟** | 先 `virsh domblklist` 看清楚，再 `undefine --remove-all-storage`；已 undefine 的手動刪 `/var/lib/libvirt/images/*.qcow2` |
| `virsh undefine` 回 `cannot undefine domain with nvram` ★★★★ | UEFI 客體有 NVRAM 檔 | `virsh undefine <name> --nvram` |
| `virsh list` 看不到某台 VM，但它明明存在 ★★★★★ | `virsh list` **只顯示執行中的** | 用 `virsh list --all` |
| 主機重開機後某台 VM 永遠消失了 ★★★★★ | 那是用 `virsh create` 開的**暫態 domain** | 一律用 `define` + `start`；還在跑的可 `dumpxml` 後 `define` 轉正 |
| `virsh shutdown` 完全沒反應 ★★★★★ | 客體沒裝 `qemu-guest-agent`，ACPI 訊號也被忽略 | 客體裝 `qemu-guest-agent`；改用 `--mode agent`；先 `virsh console` 進去看卡在哪 |
| `virsh shutdown --mode agent` 回 `Guest agent is not responding` ★★★★ | agent 沒裝或沒啟動 | 客體 `systemctl enable --now qemu-guest-agent`；XML 要有 `<channel type='unix'>` 的 `org.qemu.guest_agent.0` |
| 改了 XML，`virsh reboot` 之後沒生效 ★★★★★ | `reboot` 不重建 QEMU 程序 | `virsh shutdown` → `virsh start` |
| 改了 XML，完整停機再開機還是沒生效 ★★★★ | 有 **managedsave** 狀態，開機是從記憶體映像恢復 | `virsh dominfo` 看 `Managed save`；`virsh managedsave-remove <name>` 後再 `start` |
| `virsh console` 連上去一片空白 ★★★★★ | 客體沒把輸出導到序列埠 | 客體 GRUB 加 `console=ttyS0,115200n8`、`update-grub`、`systemctl enable --now serial-getty@ttyS0` |
| `virsh console` 退不出來 ★★★★ | 用了 `Ctrl+C`（會傳給客體） | 退出鍵是 **`Ctrl + ]`** |
| `virsh console` 回 `Cannot access console: Operation not permitted` ★★★ | 已經有另一個工作階段佔用主控台 | 找出並關掉那個 session，或 `virsh console <name> --force` |
| `snapshot-revert` 回 `revert to external snapshot not supported yet` ★★★★★ | 那是**外部快照**，舊版 libvirt 不支援 revert | 用**內部快照**（qcow2，不加 `--disk-only`）；或升級 libvirt 後先在測試機驗證 |
| `snapshot-create-as` 回 `internal snapshots are not supported with format 'raw'` ★★★★ | 內部快照**只支援 qcow2** | `qemu-img convert -O qcow2` 轉檔，或改用外部快照 |
| 刪了外部快照的 overlay 檔，VM 就開不起來了 ★★★★★ | 磁碟鏈斷了，資料在 overlay 裡 | **無解，只能還原備份**。正確做法是先 `blockcommit --pivot` 合併回去再刪 |
| `blockcommit` 卡住不動 ★★★ | 磁碟 I/O 忙碌，或 VM 寫入量大 | 加 `--verbose` 看進度；離峰時段做；必要時 `virsh blockjob <name> vda --abort` |
| 快照做完 VM 變得很慢 ★★★★ | 快照鏈太長，每次讀取都要往上追 | 定期清理快照；不要把快照當備份長期留著 |
| `attach-disk` 之後重開機磁碟不見了 ★★★★★ | 只加了 `--live` 沒加 `--config` | `--live --config` 兩個都要加 |
| `detach-disk` 之後客體檔案系統壞了 ★★★★★ | 磁碟還掛載中就被拔掉 | 先在客體 `umount` 並移除 `/etc/fstab` 那一行，再 detach |
| `migrate --live` 回 `Unsafe migration: Migration without shared storage is unsafe` ★★★★ | 沒有共用儲存 | 加 `--copy-storage-all`（慢）；或關機搬；或建置共用儲存 |
| 遷移過去後目標主機重開機，VM 消失了 ★★★★★ | 沒加 `--persistent`，是暫態 domain | `virsh migrate --live --persistent` |
| 遷移過去客體立刻崩潰 ★★★★★ | `host-passthrough` + CPU 指令集不同 | 改成具名 CPU model 或 `host-model`，**以最舊的那台 CPU 為準**，改完要完整停機再開機 |
| 遷移後兩台主機上都有這台 VM 的定義 ★★★★ | 沒加 `--undefinesource` | 手動在來源端 `virsh undefine`（★★★★★ 確認磁碟不會被誤刪） |
| `virsh edit` 存檔後回 `Failed. Try again? [y,n,i,f,?]` ★★★★ | XML 語法或值不合法 | 選 `y` 回去改；**不要選 `i`（強制接受）** |
| `virsh setmem` 回 `cannot set memory higher than max memory` ★★★★ | 想設的值超過 `<memory>`（上限） | 先改 `--config` 的 `memory` 上限，完整停機再開機 |
| 腳本裡用 domain Id 結果錯亂 ★★★★ | **Id 每次啟動都會變** | 腳本一律用**名稱或 UUID** |
| 大量 VM 一起 `shutdown` 之後主機掛了很久 ★★★ | 全部同時寫入磁碟 | 加間隔逐台關；或用 `virsh managedsave` |

---

## 安全性注意事項

> [!danger] ★★★★★ 三個不可逆的指令，執行前一定要停下來確認
> | 指令 | 後果 |
> | --- | --- |
> | `virsh destroy <name>` | **立即斷電**，客體資料可能損毀 |
> | `virsh undefine <name> --remove-all-storage` | **磁碟檔永久刪除** |
> | `virsh snapshot-revert <name> <snap>` | **快照之後的所有變更全部消失** |
>
> 建議在正式環境養成習慣：
> ```bash
> # 執行破壞性指令前，先確認你打的是哪一台
> virsh dominfo <name> && virsh domblklist <name>
> ```

> [!warning] ★★★★★ 不要在腳本裡無條件使用 `destroy`
> 常見的錯誤寫法：
> ```bash
> # ❌ 危險：無條件強制斷電
> virsh destroy "$VM"; virsh start "$VM"
> ```
> 正確寫法：
> ```bash
> # ✅ 先優雅關機，逾時才強制
> virsh shutdown "$VM"
> for i in $(seq 1 60); do
>   [ "$(virsh domstate "$VM")" = "shut off" ] && break
>   sleep 2
> done
> if [ "$(virsh domstate "$VM")" != "shut off" ]; then
>   echo "警告：$VM 逾時未關機，執行強制斷電" >&2
>   virsh destroy "$VM"
> fi
> virsh start "$VM"
> ```

| 風險 | 說明 | 對策 |
| --- | --- | --- |
| **`virsh` 與 `qm` 的 `destroy` 意義相反** ★★★★★ | 同時管理兩個平台的人最容易出事 | 對照表印出來貼旁邊；腳本加上平台判斷 |
| **`--remove-all-storage` 誤刪** ★★★★★ | 磁碟沒有回收桶 | 先 `domblklist` 確認；重要 VM 先做磁碟備份 |
| **快照被當成備份** ★★★★★ | 快照跟原磁碟在同一顆硬碟，硬碟壞了一起沒 | 快照是「短期回復點」，備份要異地 |
| **記憶體快照含敏感資料** ★★★★ | 內部快照存了完整記憶體，裡面有明文密碼、金鑰、session token | 快照檔比照磁碟保護，用完就刪 |
| **`virsh console` 是無認證的主機層存取** ★★★★ | 能執行 `virsh` 的人可直接進客體的 `getty` | 這是設計如此；控管 `libvirt` 群組成員 |
| **`migrate` 的資料在網路上傳輸** ★★★★ | 客體記憶體（含機敏資料）會經過網路 | 走 `qemu+ssh://`（已加密）；不要用未加密的 TCP 遷移 |
| **XML 備份含 VNC 密碼與磁碟路徑** ★★★★ | `dumpxml` 的內容可能有 `<graphics passwd='...'>` | 備份目錄權限收緊（`chmod 700`），不要放進 git |
| **`virsh edit` 用 `i` 強制接受不合法設定** ★★★★ | 可能造成 VM 開不起來或安全設定失效 | 永遠不要選 `i` |
| **暫態 domain 跑正式服務** ★★★★★ | 主機重開機服務永久消失，且沒有任何警告 | `virsh list --all` 定期檢查 `Persistent` 欄位 |
| **未設 autostart 的正式 VM** ★★★★★ | 主機重開機後服務不會回來，可能拖到有人抱怨才發現 | 建 VM 的 SOP 最後一步固定加 `virsh autostart` |

---

## 速查表

### 生命週期（★★★★★ 最重要的六個）

| 做什麼 | 指令 | 注意 |
| --- | --- | --- |
| 註冊定義（不啟動）★★★★★ | `virsh define <file>.xml` | 產生 persistent domain |
| ⚠️ 直接啟動（不註冊）★★★★★ | `virsh create <file>.xml` | **暫態，關掉就消失，維運勿用** |
| 開機 ★★★★★ | `virsh start <name>` | |
| 優雅關機 ★★★★★ | `virsh shutdown <name>` | 需要 ACPI 或 guest agent |
| ⚠️ **強制斷電** ★★★★★ | `virsh destroy <name>` | **不是刪除！等同拔插頭** |
| ⚠️ **刪除定義** ★★★★★ | `virsh undefine <name>` | **磁碟預設保留** |
| 刪除含磁碟 ★★★★★ | `virsh undefine <name> --remove-all-storage` | 不可逆 |
| UEFI 客體刪除 ★★★★ | `virsh undefine <name> --nvram` | |
| 重開機 ★★★★ | `virsh reboot <name>` | **不套用硬體變更** |
| 暫停／恢復 ★★★ | `virsh suspend` / `virsh resume` | 記憶體仍佔用 |
| 休眠到磁碟 ★★★★ | `virsh managedsave <name>` | `managedsave-remove` 清除 |
| 開機自動啟動 ★★★★★ | `virsh autostart <name>` | `--disable` 取消 |

### 查詢

| 做什麼 | 指令 |
| --- | --- |
| 所有 VM ★★★★★ | `virsh list --all` |
| 只看名稱（腳本用）★★★★ | `virsh list --all --name` |
| 目前連到哪 ★★★★★ | `virsh uri` |
| 單一狀態 ★★★★ | `virsh domstate <name>` |
| 完整資訊 ★★★★★ | `virsh dominfo <name>` |
| 完整 XML ★★★★★ | `virsh dumpxml <name>` |
| 磁碟清單 ★★★★★ | `virsh domblklist <name>` |
| 磁碟用量 ★★★★ | `virsh domblkinfo <name> vda` |
| 網卡清單 ★★★★ | `virsh domiflist <name>` |
| 客體 IP ★★★★ | `virsh domifaddr <name> [--source agent]` |
| 記憶體統計 ★★★ | `virsh dommemstat <name>` |
| 主機資訊 ★★★ | `virsh nodeinfo` |
| 版本 ★★★ | `virsh version --daemon` |
| 展開成 QEMU 參數 ★★★ | `virsh domxml-to-native qemu-argv --domain <name>` |

### 修改設定

| 做什麼 | 指令 | 生效時機 |
| --- | --- | --- |
| 互動編輯 ★★★★★ | `virsh edit <name>` | 依變更類型 |
| 命令列編輯 ★★★★ | `virt-xml <name> --edit --<opt> <val> --config` | 下次完整開機 |
| 記憶體 ★★★★ | `virsh setmem <name> <KiB> --config` | 完整停機再開機 |
| vCPU ★★★★ | `virsh setvcpus <name> <n> --config` | 完整停機再開機 |
| 加磁碟 ★★★★★ | `virsh attach-disk <name> <file> <target> --live --config` | 立即（VirtIO 支援熱插） |
| 拔磁碟 ★★★★ | `virsh detach-disk <name> <target> --live --config` | 立即（**先 umount**） |
| 加網卡 ★★★★ | `virsh attach-interface <name> --type network --source default --model virtio --live --config` | 立即 |
| 磁碟擴充 ★★★★ | `qemu-img resize <file> +10G` 然後 `virsh blockresize <name> <file> <size>` | 客體要自己 growpart |

### 快照

| 做什麼 | 指令 |
| --- | --- |
| 建內部快照 ★★★★★ | `virsh snapshot-create-as <name> <snap> "描述"` |
| 建外部快照（備份用）★★★★ | `virsh snapshot-create-as <name> <snap> --disk-only --atomic --no-metadata --diskspec vda,file=<overlay>` |
| 列出 ★★★★ | `virsh snapshot-list <name>` |
| 詳細（看 internal/external）★★★★★ | `virsh snapshot-info <name> <snap>` |
| 回復 ★★★★★ | `virsh snapshot-revert <name> <snap>` |
| 刪除 ★★★★ | `virsh snapshot-delete <name> <snap>` |
| 合併 overlay ★★★★★ | `virsh blockcommit <name> vda --active --pivot --verbose` |
| 看 qcow2 內的快照 ★★★★ | `qemu-img info <file>` |

### 主控台與遷移

| 做什麼 | 指令 |
| --- | --- |
| 文字主控台 ★★★★★ | `virsh console <name>` |
| **退出主控台** ★★★★★ | **`Ctrl + ]`** |
| 客體端設定 ★★★★★ | GRUB 加 `console=ttyS0,115200n8` + `serial-getty@ttyS0` |
| 線上遷移 ★★★★ | `virsh migrate --live --persistent <name> qemu+ssh://<host>/system` |
| 遷移並刪來源 ★★★★ | 加 `--undefinesource` |
| 無共用儲存 ★★★ | 加 `--copy-storage-all` |
| 遠端操作 ★★★★ | `virsh -c qemu+ssh://user@host/system <指令>` |

### `virsh` ↔ `qm` 危險對照（★★★★★ 背起來）

| 意義 | virsh | qm |
| --- | --- | --- |
| 優雅關機 | `virsh shutdown` | `qm shutdown` |
| **強制斷電** | **`virsh destroy`** | **`qm stop`** |
| **刪除 VM** | **`virsh undefine`** | **`qm destroy`** |

---

## 練習題

**練習 1（★★★★★）**
在測試 VM 上實測：`virsh destroy` 之後 VM 還在不在？磁碟還在不在？
`virsh undefine` 之後呢？用指令證明每一步的結果。

> [!question]- 參考答案
> ```bash
> virsh list --all
> ```
> ```text
>  Id   Name     State
> ------------------------
>  4    test01   running
> ```
> ```bash
> virsh domblklist test01
> ```
> ```text
>  Target   Source
> ----------------------------------------------
>  vda      /var/lib/libvirt/images/test01.qcow2
> ```
> ```bash
> virsh destroy test01 && virsh list --all
> ```
> ```text
> Domain 'test01' destroyed
>  Id   Name     State
> ------------------------
>  -    test01   shut off
> ```
> ★★★★★ **VM 還在**（只是被斷電了）。
> ```bash
> ls -lh /var/lib/libvirt/images/test01.qcow2
> ```
> ```text
> -rw------- 1 libvirt-qemu kvm 2.1G Sep  2 14:12 /var/lib/libvirt/images/test01.qcow2
> ```
> ★★★★★ **磁碟也還在。**
> ```bash
> virsh undefine test01 && virsh list --all
> ```
> ```text
> Domain 'test01' has been undefined
>  Id   Name    State
> -----------------------
>  1    web01   running
> ```
> ★★★★★ **定義消失了**，但：
> ```bash
> ls -lh /var/lib/libvirt/images/test01.qcow2
> ```
> ```text
> -rw------- 1 libvirt-qemu kvm 2.1G Sep  2 14:12 /var/lib/libvirt/images/test01.qcow2
> ```
> ★★★★★ **磁碟仍然在，變成孤兒檔。**
>
> 結論：`destroy` ≠ 刪除，`undefine` ≠ 刪磁碟。
> 完整清除要 `virsh undefine <name> --remove-all-storage`。

**練習 2（★★★★★）**
寫一個腳本，安全地重啟一台 VM：先優雅關機，最多等 120 秒，
逾時才強制斷電，然後開機並確認狀態。

> [!question]- 參考答案
> ```bash
> sudo tee /usr/local/sbin/safe-restart-vm.sh > /dev/null <<'EOF'
> #!/bin/bash
> set -euo pipefail
> VM="${1:?用法: safe-restart-vm.sh <domain名稱>}"
> TIMEOUT=120
>
> if ! virsh dominfo "$VM" >/dev/null 2>&1; then
>   echo "錯誤：找不到 domain '$VM'" >&2
>   exit 1
> fi
>
> echo "[1/3] 優雅關機 $VM ..."
> virsh shutdown "$VM" || true
>
> elapsed=0
> while [ "$(virsh domstate "$VM")" != "shut off" ]; do
>   sleep 3
>   elapsed=$((elapsed + 3))
>   if [ "$elapsed" -ge "$TIMEOUT" ]; then
>     echo "[!] 逾時 ${TIMEOUT}s，執行強制斷電（資料可能不一致）" >&2
>     virsh destroy "$VM"
>     break
>   fi
> done
>
> echo "[2/3] 啟動 $VM ..."
> virsh start "$VM"
>
> echo "[3/3] 確認狀態"
> virsh domstate "$VM"
> EOF
> sudo chmod 750 /usr/local/sbin/safe-restart-vm.sh
> sudo /usr/local/sbin/safe-restart-vm.sh web01
> ```
> ```text
> [1/3] 優雅關機 web01 ...
> Domain 'web01' is being shutdown
> [2/3] 啟動 web01 ...
> Domain 'web01' started
> [3/3] 確認狀態
> running
> ```
> ★★★★★ 三個關鍵設計：
> 1. **先驗證 domain 存在**（`dominfo`），避免對錯的名字動手
> 2. **輪詢等待**而不是固定 `sleep`
> 3. **逾時才 `destroy`，而且印出警告到 stderr**——留下紀錄

**練習 3（★★★★★）**
建立內部快照 → 在客體裡刪掉一個重要檔案 → 回復快照 → 證明檔案回來了。
然後回答：如果這是外部快照，會發生什麼？

> [!question]- 參考答案
> ```bash
> virsh snapshot-create-as web01 test-revert "回復測試"
> virsh snapshot-info web01 test-revert | grep Location
> ```
> ```text
> Domain snapshot test-revert created
> Location:       internal
> ```
> ```bash
> ssh ops@192.168.122.87 'echo "重要資料" | sudo tee /etc/myapp.conf && ls -l /etc/myapp.conf'
> ```
> ```text
> 重要資料
> -rw-r--r-- 1 root root 13 Sep  2 14:31 /etc/myapp.conf
> ```
>
> 等一下——這裡有個關鍵細節 ★★★★★：**這個檔案是在快照之後建立的，
> 所以回復快照會讓它消失**。這正是要示範的。
>
> ```bash
> virsh snapshot-revert web01 test-revert
> ssh ops@192.168.122.87 'ls -l /etc/myapp.conf'
> ```
> ```text
> ls: cannot access '/etc/myapp.conf': No such file or directory
> ```
> ★★★★★ **快照之後的所有變更都消失了**——這既是快照的價值，也是它的風險。
>
> **如果是外部快照**：
> ```bash
> virsh snapshot-create-as web01 ext-snap --disk-only --atomic \
>   --diskspec vda,file=/var/lib/libvirt/images/web01-ext.qcow2
> virsh snapshot-revert web01 ext-snap
> ```
> 在較舊的 libvirt 上會得到：
> ```text
> error: unsupported configuration: revert to external snapshot not supported yet
> ```
> ★★★★★ **這就是外部快照最大的坑**：你以為有保險，實際上回不去。
> 外部快照的正確用途是**配合 `blockcommit` 做備份**，不是回復。
>
> 清理：
> ```bash
> virsh snapshot-delete web01 test-revert
> ```

**練習 4（★★★★）**
把一台 VM 的記憶體改成 4 GB。先用 `virsh reboot` 試，觀察沒生效；
再用正確方法讓它生效。全程用指令證明。

> [!question]- 參考答案
> ```bash
> virsh dominfo web01 | grep -i 'Max memory'
> ```
> ```text
> Max memory:     3145728 KiB
> ```
> ```bash
> virt-xml web01 --edit --memory 4096,currentMemory=4096 --config
> ```
> ```text
> Domain 'web01' defined successfully.
> Changes will take effect after the domain is fully powered off.
> ```
> **錯誤做法：**
> ```bash
> virsh reboot web01 && sleep 40 && virsh dominfo web01 | grep -i 'Max memory'
> ```
> ```text
> Domain 'web01' is being rebooted
> Max memory:     3145728 KiB
> ```
> ★★★★★ **沒變。** 因為 `reboot` 只是在客體裡面重開機，
> **底層的 QEMU 程序沒有被重建**，它啟動時載入的還是舊參數。
>
> **正確做法：**
> ```bash
> virsh shutdown web01
> while [ "$(virsh domstate web01)" != "shut off" ]; do sleep 2; done
> virsh start web01
> virsh dominfo web01 | grep -i 'Max memory'
> ```
> ```text
> Domain 'web01' is being shutdown
> Domain 'web01' started
> Max memory:     4194304 KiB
> ```
> ✅ 4 GiB。客體裡確認：
> ```bash
> ssh ops@192.168.122.87 'free -h | awk "NR==2{print \$2}"'
> ```
> ```text
> 3.8Gi
> ```
> ★★★ 顯示 3.8 Gi 是正常的（韌體與核心會保留一部分）。
>
> 同樣規則適用於：CPU model、machine type、磁碟匯流排、網卡型號、韌體。
> **這跟 PVE 的 `qm reboot` 完全一樣**（見 [[050-01-03-03-guide-PVE-虛擬機管理]]）。

**練習 5（★★★★★）**
你接手一台陌生的 KVM 主機。寫一段指令，一次列出所有 VM 的：
名稱、狀態、是否 persistent、是否 autostart、CPU 數、記憶體、磁碟路徑。
並指出這份清單裡你最該先處理的兩個風險。

> [!question]- 參考答案
> ```bash
> printf "%-12s %-10s %-6s %-9s %-4s %-8s %s\n" \
>   "NAME" "STATE" "PERSIS" "AUTOSTART" "CPU" "MEM(MB)" "DISK"
> for d in $(virsh list --all --name); do
>   [ -n "$d" ] || continue
>   info=$(virsh dominfo "$d")
>   printf "%-12s %-10s %-6s %-9s %-4s %-8s %s\n" \
>     "$d" \
>     "$(echo "$info" | awk -F': *' '/^State/{print $2}')" \
>     "$(echo "$info" | awk -F': *' '/^Persistent/{print $2}')" \
>     "$(echo "$info" | awk -F': *' '/^Autostart/{print $2}')" \
>     "$(echo "$info" | awk -F': *' '/^CPU\(s\)/{print $2}')" \
>     "$(( $(echo "$info" | awk -F': *' '/^Max memory/{print $2}' | tr -dc 0-9) / 1024 ))" \
>     "$(virsh domblklist "$d" --details 2>/dev/null | awk '/disk/{printf "%s ", $4}')"
> done
> ```
> ```text
> NAME         STATE      PERSIS AUTOSTART CPU  MEM(MB)  DISK
> web01        running    yes    enable    2    4096     /var/lib/libvirt/images/web01.qcow2 /var/lib/libvirt/images/web01-data.qcow2
> db01         running    yes    disable   4    8192     /var/lib/libvirt/images/db01.qcow2
> tmpbox       running    no     disable   1    1024     /var/lib/libvirt/images/tmpbox.qcow2
> ```
>
> **★★★★★ 兩個最該先處理的風險：**
>
> **風險 1：`tmpbox` 的 `Persistent: no`** ★★★★★
> 這是一台**暫態 domain**（用 `virsh create` 開的）。
> **主機一重開機它就永遠消失**，只剩孤兒 qcow2 檔。
> 如果上面跑了任何有用的東西，這是定時炸彈。
> 立即補救：
> ```bash
> virsh dumpxml tmpbox > /root/tmpbox.xml
> virsh define /root/tmpbox.xml
> virsh dominfo tmpbox | grep Persistent
> ```
> ```text
> Persistent:     yes
> ```
>
> **風險 2：`db01` 的 `Autostart: disable`** ★★★★★
> 這是一台正在跑的資料庫 VM，但主機重開機後**不會自己起來**。
> 停電或計畫性維護之後，服務不會回來，而且可能沒人立刻發現。
> ```bash
> virsh autostart db01
> ```
> ```text
> Domain 'db01' marked as autostarted
> ```
>
> ★★★★ 另外值得注意的：`db01` 有 4 vCPU + 8 GB，
> 加上其他兩台總共 7 vCPU 與 13 GB。要對照 `virsh nodeinfo`
> 確認主機資源夠不夠，避免超額配置造成整體效能下滑。

---

## 小測驗

Q1. 這行指令會發生什麼？VM 會被刪掉嗎？磁碟呢？
```bash
virsh destroy web01
```

Q2. 是非題：`virsh undefine web01` 會把 `/var/lib/libvirt/images/web01.qcow2` 一起刪掉。

Q3. 選擇題：`virsh destroy` 對應到 PVE 的哪個指令？
（A）`qm destroy`　（B）`qm stop`　（C）`qm shutdown`　（D）`qm reset`

Q4. 你用 `virt-xml web01 --edit --memory 4096 --config` 改了記憶體，然後 `virsh reboot web01`。生效了嗎？為什麼？

Q5. `virsh create /tmp/vm.xml` 與 `virsh define /tmp/vm.xml` 差在哪？哪一個在維運環境絕對不該用？為什麼？

Q6. 簡答：`virsh console web01` 連上去一片空白，按 Enter 也沒反應。列出兩個檢查方向。

Q7. 你在 `virsh console` 裡面，想退出回到主機的 shell。按什麼鍵？按 `Ctrl+C` 會發生什麼？

Q8. `virsh snapshot-revert web01 backup01` 回報 `unsupported configuration: revert to external snapshot not supported yet`。原因是什麼？建立快照時該怎麼做才不會遇到這個？

Q9. 你執行 `virsh migrate --live web01 qemu+ssh://kvm02/system` 成功了，一週後 kvm02 例行重開機，`web01` 消失了。少了哪個旗標？

Q10. 是非題：`virsh attach-disk web01 /path/disk.qcow2 vdb --live` 加上去的磁碟，重開機後還在。

> [!question]- 測驗答案
> **Q1.** ★★★★★ **這是「強制斷電」，等同於拔掉電源線。**
> - VM **不會被刪掉**——定義還在，`virsh list --all` 看得到，狀態變成 `shut off`
> - 磁碟**完全不受影響**
> - 但客體的檔案系統**處於不一致狀態**：未寫入的資料遺失，
>   下次開機可能要跑 journal recovery，資料庫可能損毀
>
> 這是 `virsh` 裡命名最糟糕的指令。它的意思是
> "destroy the running instance"，不是 destroy the VM。
> 對應 PVE 的 `qm stop`。★★★★★
> （見「觀念說明 → destroy 不是刪除」）
>
> **Q2.** **錯。** `undefine` **預設不刪磁碟**，只刪掉
> `/etc/libvirt/qemu/web01.xml` 這個定義檔。磁碟會變成一個
> `virsh list --all` 看不到的**孤兒檔**，長期下來會默默吃光空間。
> 要連磁碟一起刪：`virsh undefine web01 --remove-all-storage`
> （★★★★★ 不可逆，執行前務必先 `virsh domblklist` 確認會刪什麼）。
> UEFI 客體還要加 `--nvram`。★★★★★
> （見「觀念說明 → undefine」）
>
> **Q3.** **（B）`qm stop`**。
> ★★★★★ 這是跨平台維運最危險的一組對照，因為兩邊的 `destroy` 意義**相反**：
>
> | 意義 | virsh | qm |
> | --- | --- | --- |
> | 強制斷電 | **`virsh destroy`** | **`qm stop`** |
> | 刪除 VM | **`virsh undefine`** | **`qm destroy`** |
>
> 同時管兩個平台的人請把這張表印出來。
> （見「進階應用 → virsh 與 qm 對照表」）
>
> **Q4.** **沒有生效。** `virsh reboot` 是**在客體作業系統裡面重開機**，
> **底層的 QEMU 程序沒有被銷毀重建**，所以它啟動時載入的參數還是舊的。
> 硬體層級的變更（記憶體、CPU model、machine type、磁碟匯流排、網卡型號、韌體）
> 一律需要 **`virsh shutdown` → `virsh start`** 的完整停機開機循環。
> `virt-xml` 本身也會提示 `Changes will take effect after the domain is
> fully powered off.`。這跟 PVE 的 `qm reboot` 是完全一樣的坑。★★★★★
> （見「觀念說明 → 什麼時候生效」與「練習 4」）
>
> **Q5.** - **`virsh define`** ★★★★★：只把定義註冊進 libvirt，**不啟動**。
>   產生 **persistent domain**，定義寫進 `/etc/libvirt/qemu/`，永久存在。
> - **`virsh create`** ★★★★★：**直接從 XML 啟動，但不註冊定義**。
>   產生 **transient（暫態）domain**——**一旦關機或主機重開機，這台 VM 就永遠消失**，
>   只留下一個孤兒磁碟檔。
>
> **維運環境絕對不該用 `create`**，因為它沒有任何警告，
> VM 看起來完全正常（`virsh list` 也看得到），
> 直到某次重開機才發現服務永久不見了。
> 檢查方法是看 `virsh dominfo` 的 **`Persistent`** 欄位。
> 已經跑起來的暫態 domain 可以就地轉正：
> `virsh dumpxml <name> > /root/<name>.xml && virsh define /root/<name>.xml`。★★★★★
> （見「觀念說明 → define vs create」與「練習 5」）
>
> **Q6.** 兩個檢查方向：
> 1. **VM 有沒有序列主控台裝置** ★★★★
>    ```bash
>    virsh dumpxml web01 | grep -A2 '<console'
>    ```
>    沒有就用 `virt-xml web01 --add-device --console pty,target_type=serial` 加上
>    （**要關機才能加**）。
> 2. **客體有沒有把輸出導到序列埠**（★★★★★ 更常見的原因）
>    一般安裝的 Linux 只把訊息送到虛擬顯示卡。客體裡要設定：
>    ```bash
>    # /etc/default/grub
>    GRUB_CMDLINE_LINUX="console=tty0 console=ttyS0,115200n8"
>    ```
>    然後 `sudo update-grub`（RHEL 系用 `grub2-mkconfig` 或 `grubby`）
>    並 `sudo systemctl enable --now serial-getty@ttyS0.service`。
>
> ★★★★ 這一步建議做在範本裡，之後每台 VM 都有這個保險。
> （見「進階應用 → 讓 virsh console 真的有畫面」）
>
> **Q7.** 退出鍵是 **`Ctrl + ]`**（Ctrl 加右中括號）。
> 連線時的第一行就會提示：`Escape character is ^] (Ctrl + ])`。
>
> 按 **`Ctrl+C` 會被傳送到客體**——就像你在客體的實體鍵盤上按了 Ctrl+C，
> 會中斷客體裡正在執行的程式，**但不會讓你離開主控台**。
> 打 `exit` 也只是登出客體的 shell，不會斷開連線。★★★★★
> （見「觀念說明 → virsh console」）
>
> **Q8.** 原因是 **`backup01` 是一個外部快照（external snapshot）**，
> 而該版本的 libvirt 不支援對外部快照做 revert。
> 外部快照是把原磁碟凍結成唯讀的 backing file、新寫入導向 overlay 檔，
> 回復需要重寫磁碟鏈，實作複雜度高，歷史上長期未支援。
>
> **要避免這個問題，建立快照時就不要加 `--disk-only`**，
> 直接 `virsh snapshot-create-as web01 <名稱> "描述"` 建**內部快照**
> （存在 qcow2 檔內部，前提是磁碟必須是 qcow2 格式）。
> 建完用 `virsh snapshot-info` 確認 **`Location: internal`**。
>
> ★★★★★ 更重要的原則：**快照建立後要立刻測試一次 revert**，
> 沒測過的快照不算保險。外部快照的正確用途是配合
> `blockcommit --pivot` 做**備份**，不是回復。★★★★★
> （見「觀念說明 → 快照」與「練習 3」）
>
> **Q9.** 少了 **`--persistent`**。
> 不加這個旗標時，遷移過去的 VM 在目標主機上是**暫態 domain**——
> 它會正常執行，`virsh list` 也看得到，但**定義從來沒有寫進
> `/etc/libvirt/qemu/`**，目標主機一重開機就永遠消失。
>
> 正確寫法：
> ```bash
> virsh migrate --live --persistent --undefinesource web01 qemu+ssh://kvm02/system
> ```
> `--undefinesource` 另外處理「來源端也還留著定義」的問題，
> 避免兩台主機上都有同一台 VM 的定義而被誤開（★★★★★ 兩邊同時開會直接毀掉磁碟）。
> ★★★★★
> （見「觀念說明 → 遷移」）
>
> **Q10.** **錯。** 只加 `--live` 的話，磁碟**只掛給執行中的 QEMU 程序**，
> **沒有寫進定義檔**，VM 一重開機磁碟就不見了
> （客體的 `/etc/fstab` 若沒加 `nofail` 還會卡在開機）。
>
> 正確做法是 **`--live --config` 兩個都加**：
> - `--live` = 立刻對執行中的 VM 生效（不用重開機）
> - `--config` = 寫進定義檔，下次開機還在
>
> 反過來只加 `--config` 則是「現在看不到，重開機才有」。
> ★★★★★ 另外提醒：**拔磁碟前一定要先在客體裡 `umount`**，
> 直接 `detach-disk` 等同熱拔硬碟，檔案系統會損毀。★★★★★
> （見「進階應用 → 熱插拔」）

---

## 延伸閱讀

**本章其他篇**

- [[050-01-04-01-guide-KVM-KVM與libvirt架構]] — KVM/QEMU/libvirt 三層、domain XML、PVE 關係
- [[050-01-04-02-svc-KVM-安裝與virt-manager]] — ★★★★★ **本篇的前置**，安裝、權限、GUI 建立 VM
- [[050-01-04-04-guide-KVM-儲存池與網路]] — `virsh pool-*`、`virsh net-*`、NAT 改橋接
- [[050-01-04-05-guide-KVM-自動化與範本]] — `virt-install`、`virt-clone`、cloud-init

**PVE（`qm` 對照的來源）**

- [[050-01-03-03-guide-PVE-虛擬機管理]] — ★★★★★ `qm` 的完整用法、CPU type、VirtIO
- [[050-01-03-06-svc-PVE-備份與還原]] — 備份策略（快照不是備份）
- [[050-01-03-07-svc-PVE-叢集與高可用]] — 遷移與 HA 的完整條件
- [[050-01-03-12-guide-PVE-故障排除]] — 對照本篇的排錯思路

**虛擬化基礎**

- [[050-01-01-03-ref-虛擬化-五平台橫向對照]] — 平台取捨
- [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] — VirtIO、CPU 指令集與遷移相容性

**VMware（概念對照）**

- [[050-01-02-03-guide-Workstation-快照與複製]] — Workstation 的快照模型
- [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] — 巢狀虛擬化環境

**Linux 基礎**

- [[020-01-10-cmd-Linux-程序管理與訊號]] — VM 就是程序，`kill` 的意義
- [[020-01-21-cmd-Linux-Shell腳本入門]] — 批次操作腳本
- [[020-01-18-guide-Linux-排程工作]] — 每日 XML 備份的 cron 設定
- [[020-01-15-cmd-Linux-磁碟分割與掛載]] — 客體裡的磁碟格式化與 `fstab`
- [[020-01-25-guide-Linux-開機流程與GRUB救援]] — 序列主控台的 GRUB 設定
