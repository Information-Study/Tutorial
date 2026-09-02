---
title: "VMware Workstation 常見故障排除"
desc: "依症狀查的 Workstation 排錯索引：裝不起來、開不了機、沒有 IP、空間爆掉、變慢、巢狀虛擬化與檔案救援，附一頁式急救卡與症狀對照表"
aliases: [Workstation 故障排除, Workstation 排錯, VMware Workstation 疑難排解手冊, VM 開不起來]
tags: [群組/虛擬機與容器, 主題/故障排除]
category: VMware Workstation
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: []
updated: 2026-09-02
---

# VMware Workstation 常見故障排除

> [!warning] 未實機驗證
> 本篇整理自本章六篇教學的內容與常見現場情境。錯誤訊息原文引自各篇已收錄的訊息，
> 選單路徑以 **Workstation 17 Pro** 為例；其他版本的選單位置可能不同，
> 動手前請以你手上那一版實際看到的畫面為準。
> 涉及刪檔、刪快照、改韌體型別的步驟**沒有在每一種主機組合上逐一驗證過**，
> 照做前先看該段的 `> [!danger]`。

> [!abstract] 怎麼用這份手冊
> - 依「**你看到什麼症狀**」查，不是依「這屬於哪一個技術主題」查。
> - 流程固定是：**找到症狀 → 看判斷分流 → 照編號步驟做 → 想懂原理再點進原文**。
> - ★★★★★ 本手冊**不重講原理**。每個情境結尾的「原理詳見」就是原文入口。
> - ★★★★★ 本篇是**六篇的上層總索引**。
>   [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 已經有一張 27 列的排錯總表，
>   單一訊息對單一解法的東西**直接連過去**，這裡不重抄；
>   本篇的篇幅留給**跨篇情境**與**完整的排查流程**。
> - ★★★★★ 動手之前先問自己兩句話：
>   1. **這台 VM 裡有沒有你不想失去的東西？** 有的話，第一個動作是把整個 VM 資料夾複製一份，
>      不是按 Retry、不是刪快照、不是刪 `.lck`。
>   2. **這是「VM 的問題」還是「主機的問題」？** 兩者的排查方向完全相反 ——
>      一台不對勁多半是 VM，全部都不對勁多半是主機。

---

## 一頁式急救卡

★★★★★ **緊急時只看這一頁。** 依序做，不要跳。

```text
【0】先保命：VM 裡有重要資料嗎？
     有 → 完全關機（不是 Suspend），把整個 VM 資料夾複製到另一顆碟，再往下做
     沒有 → 直接往下

【1】看主機還剩多少空間           ← 空間不足是最常被忽略的根因
     Windows: Get-PSDrive C,D | Select Name,Used,Free
     Linux  : df -h ~/vmware
     剩不到 20% → 先清空間，很多症狀會自己消失

【2】看那台 VM 的日誌             ← 排錯的第一站，永遠是它
     VM 資料夾裡的 vmware.log
     找關鍵字：Msg_Post / error / failed / VMX has left the building

【3】看主機上還有沒有別的 Hypervisor（Windows 才有這個問題）
     Get-ComputerInfo -Property "HyperVisorPresent"
     True → 幾乎所有「開不起來」「巢狀跑不動」都是它，走情境一

【4】看 VMware 的服務有沒有在跑
     Windows: Get-Service VMware*
     Linux  : lsmod | grep -E '^vmmon|^vmnet'
     沒跑 → 網路不通、VM 打不開多半來自這裡

【5】看快照有幾個
     VM → Snapshot → Snapshot Manager（Ctrl+M）
     ≥ 3 個或存在超過兩週 → 效能與空間問題八成在這裡

【6】還是不行，就縮小範圍
     新建一台最小 VM（1 vCPU / 1 GB / 空磁碟）能不能開機？
       能開 → 問題在那台 VM 的設定或檔案
       不能開 → 問題在主機（Hypervisor 佔用、模組、授權服務）
```

> [!danger] ★★★★★ 急救卡上唯一不能做的事
> 看到「磁碟空間不足，VM 已暫停」的對話框時，**不要按 Abort**。
> 按 Abort 等同對執行中的 Guest 硬斷電，檔案系統可能損壞。
> **正確做法是先到主機上清出空間，再回來按 Retry。**
> 詳見〈情境五〉。

---

## 快速索引（依症狀）

★★★★★ **這張表印出來貼在螢幕邊。** 找到最像的那一列，跳到對應情境。

| 症狀（你會看到的） | 最可能的原因 | 先做這件事 | 跳到 |
| --- | --- | --- | --- |
| ★★★★★ `VMware Workstation and Hyper-V are not compatible.` | Hyper-V／WSL2／虛擬機器平台佔用 VT-x | `Get-ComputerInfo -Property "HyperVisorPresent"` | 情境一 |
| ★★★★★ `VMware Workstation and Device/Credential Guard are not compatible.` | VBS／記憶體完整性開著（機關電腦常由 GPO 強制） | 同上，並確認是不是 GPO 管的 | 情境一 |
| ★★★★★ `This host supports Intel VT-x, but Intel VT-x is disabled.` | 主機 BIOS 沒開虛擬化，或被別的 Hypervisor 佔走 | 進 BIOS 看 `Intel Virtualization Technology` / `SVM Mode` | 情境一 |
| ★★★★★ Linux 主機 `Could not open /dev/vmmon` | 核心模組沒載入／Secure Boot 拒絕未簽章模組 | `lsmod \| grep -E '^vmmon\|^vmnet'` | 情境一 |
| ★★★★★ `Not enough physical memory is available to power on…` | 記憶體配太多，主機沒那麼多可用 RAM | `Get-Counter '\Memory\Available MBytes'` | 情境二 |
| ★★★★ 開機停在 `UEFI Interactive Shell` 或 `Shell>` | 找不到可開機媒體：ISO 沒掛或磁碟沒接 | Settings → CD/DVD、Hard Disk 的 `Connected` | 情境二 |
| ★★★★ 開機一直 `>>Start PXE over IPv4` | 同上，韌體找不到磁碟就去試網路開機 | 檢查開機順序與磁碟連接 | 情境二 |
| ★★★★ 裝完之後 `Operating System not found` | 裝完把韌體型別從 UEFI 改成 BIOS（或反過來） | Settings → Options → Advanced 看韌體型別 | 情境二／十一 |
| ★★★★★ `VMware Workstation unrecoverable error: (vcpu-0)` | 記憶體不足、硬體不穩、版本相容性 | 讀 `vmware.log` 最後 50 行 | 情境二 |
| ★★★★★ `This virtual machine appears to be in use.` | 上次非正常結束，`.lck` 鎖目錄殘留 | 先確認沒有第二個 Workstation 開著它 | 情境十二 |
| ★★★★★ VM 完全沒有 IP，`ip a` 只有 `lo` | 網路卡沒勾 `Connected` / `Connect at power on` | Settings → Network Adapter | 情境三 |
| ★★★★★ Bridged 在無線網卡上拿不到 IP | 無線 AP 只允許一個 MAC，或有 802.1X | **改用 NAT** | 情境三 |
| ★★★★★ 一開 Bridged，連主機自己都斷網 | 交換器埠安全偵測到第二個 MAC，把埠 `err-disable` | **立刻改回 NAT**，請網管恢復該埠 | 情境三 |
| ★★★★★ NAT 下 ping 得到主機卻上不了網 | 閘道設成 `.1`（主機網卡）而不是 `.2`（NAT 裝置） | `ip route` 看 `default via` | 情境三 |
| ★★★★ `ping 1.1.1.1` 通但 `apt update` 失敗 | 純 DNS 問題 | `getent hosts archive.ubuntu.com` | 情境三 |
| ★★★★★ 主機連得到 VM 的網站，同事連不到 | NAT 沒設埠轉發，或主機防火牆擋住 | 先分清楚「誰連不到」 | 情境四 |
| ★★★★★ VM 內 `curl 127.0.0.1` 通、外面不通 | 服務只監聽 `127.0.0.1` | `ss -tlnp \| grep ':80'` | 情境四 |
| ★★★★ 埠轉發設好了，主機 `curl 127.0.0.1:8080` 不通 | VM 用 DHCP，IP 換了，規則指到空位址 | 先把 VM 設成固定 IP | 情境四 |
| ★★★★★ 主機碟莫名被吃光 | 快照鏈成長 + 動態磁碟只長不縮 | `Ctrl+M` 看快照數量 | 情境五 |
| ★★★★★ VM 執行中突然暫停，提示磁碟空間不足 | 主機碟寫滿，Workstation 為保護資料暫停 VM | **清空間後按 Retry，不要按 Abort** | 情境五 |
| ★★★★ `.vmdk` 很大但 Guest 裡 `df` 沒那麼多 | 動態磁碟只長不縮 | 先 Guest 歸零，再 Host 壓縮 | 情境五 |
| ★★★★★ 效能突然變慢，之前都好好的 | 快照鏈、主機碟快滿、防毒掃描、省電模式、別人也在用 | 依序查五件事 | 情境六 |
| ★★★★★ 配 8 vCPU 反而比 2 vCPU 慢 | vCPU 超配，co-scheduling 等待 | 降回 2～4 vCPU | 情境六 |
| ★★★★ Guest `top` 的 `%wa` 長期偏高 | 磁碟太慢或多台 VM 搶同一顆碟 | 把 `.vmdk` 搬到 SSD | 情境六 |
| ★★★★★ Guest 裡 `kvm-ok` 說 `KVM acceleration can NOT be used` | 沒勾 `Virtualize Intel VT-x/EPT`，或改 `.vmx` 時 VM 沒完全關機 | 完全關機後勾選 | 情境七 |
| ★★★★ `Processors` 頁上沒有巢狀虛擬化的勾選框 | 虛擬硬體版本太舊 | Change Hardware Compatibility（**不可逆**） | 情境七 |
| ★★★★★ `Virtualized Intel VT-x/EPT is not supported on this platform.` | Host 缺 EPT／RVI，或仍有其他 Hypervisor | 先確認 `HyperVisorPresent` = `False` | 情境七 |
| ★★★★★ `/mnt/hgfs` 是空的或不存在 | open-vm-tools 走 FUSE，**不會自動掛** | `vmware-hgfsclient` 先看有沒有共享 | 情境八 |
| ★★★★ Workstation 看不到 VM 的 IP、`Shut Down Guest` 是灰的 | `vmtoolsd` 沒在跑 | `systemctl status open-vm-tools` | 情境八 |
| ★★★★★ Linux Guest 升級核心後網路卡消失 | 誤裝原廠 Tools，模組編不過 | `vmware-uninstall-tools.pl` 後改裝 open-vm-tools | 情境八 |
| ★★★★★ 主機睡眠喚醒後 Guest 時間慢好幾小時 | 虛擬時鐘在 Host 睡眠期間停止推進 | `sudo chronyc makestep` | 情境九 |
| ★★★★★ `journalctl` 一堆 `System clock was stepped by …` | Tools 授時與 chrony 同時開著在打架 | 二選一，關掉另一套 | 情境九 |
| ★★★★ 還原快照後 `apt update` 報 `not valid yet` | 時間跳回過去 | `time.synchronize.restore = "FALSE"` | 情境九 |
| ★★★★★ 兩台複製出來的機器搶同一個 IP | `machine-id` 相同，DHCP 識別碼撞在一起 | `systemd-machine-id-setup` | 情境十 |
| ★★★★ 兩台機器 SSH 指紋一模一樣 | 複製後沒重新產生 SSH host key | `ssh-keygen -A` | 情境十 |
| ★★★ SSH 報 `REMOTE HOST IDENTIFICATION HAS CHANGED` | 這個 IP 換了一台機器（**通常是正常的**） | `ssh-keygen -R <IP>` | 情境十 |
| ★★★★ 升級 Workstation 後舊 VM 提示 Tools 過期／開不起來 | 硬體相容性、模組、Tools 版本三層之一 | 先確認能不能開，再談 Tools | 情境十一 |
| ★★★★★ `Cannot open the disk 'xxx.vmdk' or one of the snapshot disks…` | `.lck` 殘留、快照鏈檔案缺失或被搬過 | **先整個資料夾備份**再動手 | 情境十二 |
| ★★★★★ 連結複製的 VM 開不起來，抱怨找不到磁碟 | 來源 VM 被刪除、改名或搬移 | 把來源還原到原路徑原名稱 | 情境十二 |
| ★★★★★ 刪快照跑到一半失敗，VM 開不起來 | 合併過程中斷，或主機空間不足 | 先清空間，讀 `vmware.log` | 情境十二 |

---

## 依情境展開

### ★★★★★ 情境一：裝不起來，或裝好了開不了任何 VM

**現象**：安裝程式報錯、或 Workstation 開得起來但一按 Power On 就跳錯誤視窗。
訊息通常是下面四種之一：

```text
（A）VMware Workstation and Hyper-V are not compatible.
     Remove the Hyper-V role from the system before running VMware Workstation.
                                         ★★★★★ Windows：Hyper-V 層還在

（B）VMware Workstation and Device/Credential Guard are not compatible.
     Workstation can be run after disabling Device/Credential Guard.
                                         ★★★★★ Windows：VBS 開著

（C）This host supports Intel VT-x, but Intel VT-x is disabled.
     Binary translation is incompatible with long mode on this platform.
                                         ★★★★★ 硬體虛擬化根本沒開

（D）Could not open /dev/vmmon: No such file or directory.
                                         ★★★★★ Linux 主機：核心模組沒載入
```

**判斷分流**：

```text
主機是 Windows → 走【1】（八成是 Hyper-V 層，不管訊息長怎樣）
主機是 Linux   → 走【4】（八成是核心模組或 Secure Boot）
兩邊都查完還是不行 → 走【5】，回到 BIOS/UEFI
```

**處置步驟**：

【1】★★★★★ Windows：先問系統「現在有沒有 Hypervisor 在跑」。這一句是整個情境的分水嶺。

```powershell
Get-ComputerInfo -Property "HyperVisorPresent"
```

```text
HyperVisorPresent
-----------------
             True     ← ★★★★★ 有東西佔著 VT-x，就是它
```

`True` 就往下做；`False` 而還是報錯，跳到【5】。

【2】★★★★ 找出是「哪一個」功能把 Hyper-V 層拉起來的。
★★★★★ **最常被忽略的不是 Hyper-V 角色本身，是 WSL 2 與「記憶體完整性」。**

```powershell
Get-WindowsOptionalFeature -Online | Where State -eq Enabled |
    Select-Object FeatureName
```

| 看到這個功能啟用中 | 它會不會拉起 Hyper-V 層 | 常見程度 |
| --- | --- | --- |
| `Microsoft-Hyper-V-All` ★★★★ | 會 | 明顯，通常自己知道 |
| `VirtualMachinePlatform` ★★★★★ | 會（**WSL2、Docker Desktop 都會裝它**） | **極常見，最容易忽略** |
| `Containers-DisposableClientVM`（Windows 沙箱）★★★ | 會 | 常見 |
| 核心隔離 → 記憶體完整性（VBS）★★★★★ | 會（不在這個清單裡，要去「Windows 安全性」看） | **新機／新版 Windows 預設可能開著** |
| Credential Guard / Device Guard ★★★★ | 會（**機關網域常由 GPO 強制**） | 機關電腦常見 |

【3】★★★★ 關掉並重開機。**三件事都要做，少一件就白做。**

```powershell
# 以系統管理員執行
Disable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -NoRestart
Disable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -NoRestart
bcdedit /set hypervisorlaunchtype off
Restart-Computer
```

重開機後再驗一次，**一定要是 `False`**：

```powershell
Get-ComputerInfo -Property "HyperVisorPresent"
```

```text
HyperVisorPresent
-----------------
            False     ★★★★★ 到這裡才算真的關掉
```

> [!danger] ★★★★★ 關掉之前先想清楚，機關電腦更要先問
> 關掉 Hyper-V 層之後：**WSL2 起不來、Docker Desktop 的 WSL2 後端不能用、
> Windows 沙箱消失**。要留 WSL2 的資料，先 `wsl --export <名稱> <路徑.tar>`。
>
> ★★★★★ **受 GPO 管控的機關配發電腦，關閉 Device/Credential Guard 前務必先問資安單位。**
> 那是防止憑證竊取的機制，擅自關閉可能違反內部資安基準。
> 正確做法是**申請一台專用實驗主機**，而不是把日常辦公機的防護關掉。

【4】★★★★★ Linux 主機：模組沒載入，或 Secure Boot 把它擋掉了。

```bash
lsmod | grep -E '^vmmon|^vmnet'
```

沒有任何輸出就重編模組：

```bash
sudo vmware-modconfig --console --install-all
```

編完仍看不到模組，去看核心有沒有明講「我拒絕了」：

```bash
sudo dmesg | grep -i 'module'
```

```text
[  312.884211] Loading of unsigned module is rejected     ★★★★★ Secure Boot 擋的
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| `Unable to install all modules` ★★★★ | 缺 `build-essential` 或 headers 與 `uname -r` 對不上 | 裝 `linux-headers-$(uname -r)`；剛升核心要**先重開機再編** |
| 編譯成功但 `lsmod` 看不到 ★★★★★ | Secure Boot 拒絕未簽章模組 | 用 `sign-file` 簽章 ＋ `mokutil --import` 註冊；**優先簽章，不要直接關 Secure Boot** |
| `dmesg` 出現 `Loading of unsigned module is rejected` ★★★★ | 同上 | 同上 |
| 升級核心後 Workstation 打不開 ★★★★ | 新核心沒有對應模組 | `sudo vmware-modconfig --console --install-all` 後**重新簽章** |

【5】★★★★★ 走到這裡代表沒有其他 Hypervisor，那就是**硬體那一層根本沒開**。
進主機的 BIOS/UEFI，找這兩個其中之一並啟用：

```text
Intel 平台：Intel Virtualization Technology（有些機器叫 Intel VT-x）
AMD  平台：SVM Mode
```

★★★★ **筆電更新 BIOS 之後，這個選項常會被重設回停用。**
「昨天還好好的，今天就開不了」而你剛好更新過韌體，先來這裡看一眼。

【6】★★★ 服務層的兩個小坑，訊息不一樣但很容易混進來：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| VM 開機跳「無法連線到虛擬機」或權限錯誤 ★★★★ | `VMware Authorization Service` 沒啟動 | `Start-Service VMAuthdService`，並設為自動啟動 |
| `Transport (VMDB) error -14: Pipe connection has been broken.` ★★★★ | Workstation 背景服務異常結束 | 關掉所有 Workstation 視窗，重啟 `VMAuthdService`；必要時重開機 |
| 找不到快照／複製選單 ★★★★ | 裝到的是 **Player 不是 Pro** | Player 沒有這些功能，改裝 Pro |
| `vmrun` 找不到指令 ★★★ | 安裝時沒勾「Add console tools to PATH」 | 把安裝目錄加進 PATH，或用完整路徑呼叫 |

**原理詳見**：[[050-01-02-01-svc-Workstation-安裝與授權]] 的〈與 Hyper-V／WSL2 共存〉與〈常見錯誤與排錯〉。
「共存模式」（讓 Workstation 跑在 Hyper-V 之上）能開 VM 但**效能明顯較差、巢狀虛擬化通常不可用**，
取捨表也在那一節。

---

### ★★★★★ 情境二：VM 開不起來、卡在開機畫面，或跳 `Internal error`

**現象**：Workstation 本身正常（別台 VM 開得起來），就這一台有問題。
分成三種完全不同的情況，**不要混在一起查**。

**判斷分流**：★★★★★ 先問一句：**它「開得起來」嗎？**

```text
連 Power On 都被拒絕，跳對話框            → 走【1】（資源／授權／鎖檔層）
開得起來，但停在韌體畫面（Shell> / PXE）  → 走【2】（找不到開機媒體）
開得起來，進到 Guest 才出事（藍屏、panic）→ 走【3】（Guest 自己的問題）
開到一半整台 VM 消失、跳 unrecoverable    → 走【4】（讀 vmware.log）
```

【1】★★★★★ Power On 就被拒絕。看訊息對表：

| 訊息 | 原因 | 解法 |
| --- | --- | --- |
| `Not enough physical memory is available to power on this virtual machine with its configured settings.` ★★★★★ | 記憶體配太多，或偏好設成 `Fit all` 而實體 RAM 不足 | 調降 VM 記憶體、關掉其他 VM。**不要**改成「Allow most … swapped」硬開 |
| `This virtual machine appears to be in use.` ★★★★★ | 上次非正常結束，`.lck` 殘留 | 見〈情境十二〉，**先確認沒有第二個 Workstation 開著它** |
| `Cannot open the disk 'xxx.vmdk' or one of the snapshot disks it depends on.` ★★★★★ | 快照鏈缺檔、檔案被搬過、`.lck` 殘留 | 見〈情境十二〉 |
| `Failed to lock the file` ★★★★ | 同上，或防毒／備份軟體正鎖著檔案 | 排除防毒掃描、停掉備份工作、刪 `.lck` |
| `This host supports Intel VT-x, but Intel VT-x is disabled.` ★★★★★ | 主機層問題 | 回〈情境一〉 |

先確認主機到底剩多少記憶體，不要用感覺的：

```powershell
Get-Counter '\Memory\Available MBytes'
```

```text
CounterSamples
--------------
\\PC-LAB01\memory\available mbytes :
     2145        ← ★★★★★ 只剩 2 GB，這台主機不該再開新 VM
```

★★★★★ **給主機留 4～6 GB 是硬底線**（Windows 桌面留 6 GB、Linux 純文字介面留 2 GB）。

【2】★★★★ 開得起來但停在韌體畫面。三種畫面，同一個根因：**韌體找不到能開機的東西**。

```text
（A）UEFI Interactive Shell v2.2
     Shell>                                  ★★★★ 什麼都沒找到

（B）>>Start PXE over IPv4.                   ★★★ 退回網路開機
     （一直重試）

（C）Operating System not found               ★★★★ 有磁碟但沒有開機載入器
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| 還沒裝系統就進 Shell / PXE ★★★★ | ISO 沒掛，或 CD/DVD 沒勾 `Connect at power on` | Settings → CD/DVD 勾 `Connected` 與 `Connect at power on`，確認 ISO 路徑正確 |
| 裝完重開又跑進安裝程式 ★★★ | ISO 沒退出，韌體優先從光碟開機 | `VM → Removable Devices → CD/DVD → Disconnect`，或取消 `Connect at power on` |
| ★★★★★ 裝完之後 `Operating System not found` | **裝完把韌體型別從 UEFI 改成 BIOS（或反過來）** | Settings → Options → Advanced 把韌體改回原本的型別 |
| 磁碟根本沒接上 ★★★★ | Hard Disk 的 `Connect at power on` 沒勾，或裝完換了控制器型式 | 檢查該勾選框；控制器改回原本型式 |
| 舊系統看不到 NVMe 磁碟 ★★★ | 舊安裝程式沒有 NVMe 驅動 | 磁碟類型改用 **SCSI** 重建虛擬機 |

> [!danger] ★★★★★ 韌體型別裝完之後不能隨便改
> 開機載入器（GRUB／Windows Boot Manager）是**按照韌體型別安裝**的。
> 用 BIOS 裝好的系統改成 UEFI，開機就會停在 `Operating System not found` 或掉進 UEFI Shell。
> 反過來也一樣。**改回去就好** —— 但如果你已經忘記原本是哪一個，就得一個一個試。
> ★★★★ 建 VM 的時候就把韌體型別寫進 VM 的 Notes 欄位。

【3】★★★ 進到 Guest 才出事（Linux kernel panic、Windows 藍屏）。
★★★★★ **這一層已經不是 Workstation 的問題，是 Guest 作業系統的問題。**
Workstation 這邊只需要確認三件事，其餘照實體機的排錯流程走：

```text
① 這台 VM 最近改過硬體嗎？（換控制器型式、拔磁碟、改 CPU）
     → 改回去試試看
② 最近在 Guest 裡升級過核心嗎？
     → 從 GRUB 選單挑上一版核心開機
③ 有沒有一個「還好的」快照？
     → Ctrl+M → 選那個快照 → Go To（但先看下面的警告）
```

> [!danger] ★★★★★ Go To 之前一定要先對「現在的狀態」拍一個快照
> 回復快照會**丟掉快照之後的所有改動，而且不可逆**。
> 很多人是回復完才想起來「那份東西還沒複製出來」。
> **標準動作：Take Snapshot（取名 `before-revert`）→ 再 Go To。**

Linux Guest 掉進 emergency mode 的處理與實體機完全相同，走
[[020-01-98-trouble-Linux-常見故障排除]] 與 [[020-01-25-guide-Linux-開機流程與GRUB救援]]。

【4】★★★★★ VM 突然消失、跳 `VMware Workstation unrecoverable error: (vcpu-0)`。
**答案幾乎都在 `vmware.log` 裡。** 每台 VM 的目錄下都有它（外加 `vmware-0.log`、`vmware-1.log` 等舊檔）。

```powershell
Get-Content 'D:\VMs\lab-ubuntu\vmware.log' -Tail 50
```

```bash
tail -n 50 ~/vmware/lab-ubuntu/vmware.log
```

★★★★★ 找這四個關鍵字：`Msg_Post`、`error`、`failed`、`VMX has left the building`。

| 日誌裡看到 | 通常代表 | 下一步 |
| --- | --- | --- |
| `Msg_Post: Error` 後面接完整訊息 ★★★★★ | 就是彈窗上那一句 | 回上面的表對照 |
| `VMX has left the building` ★★★★ | VMX 程序異常結束 | 看它前面幾行，通常有真正的原因 |
| 大量磁碟相關 `failed` ★★★★ | 檔案層問題 | 走〈情境十二〉 |
| 找不到明顯錯誤 ★★★★ | 主機記憶體不足、硬體不穩、版本相容性 | **先降低 vCPU 與記憶體測試**；跑主機記憶體檢測 |

**原理詳見**：
[[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] 的〈UEFI 還是 BIOS〉與〈常見錯誤與排錯〉、
[[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈記憶體配置準則〉與那張 27 列排錯總表。

---

### ★★★★★ 情境三：VM 拿不到 IP，或有 IP 但不通

**現象**：`ip a` 沒有 IPv4、拿到 `169.254.x.x`、ping 得到主機卻上不了網、
`ping` 通但 `apt update` 失敗。

**判斷分流**：★★★★★ **照這四步走，每一步只回答一個問題，不要跳。**

```text
【1】有沒有拿到 IP？        ip -brief addr show
       沒有 → 走【1】（虛擬網卡層 / DHCP 層）
【2】預設路由對不對？       ip route
       .1 不是 .2 → 走【2】（NAT 模式最經典的錯）
【3】通不通到閘道？         ping -c 3 192.168.x.2
       不通 → 走【3】（模式選錯 / 主機服務沒跑）
【4】是網路壞還是 DNS 壞？  ping -c 3 1.1.1.1  vs  getent hosts archive.ubuntu.com
       前者通後者不通 → 走【4】（純 DNS）
```

【1】★★★★★ 完全沒有 IP，`ip a` 只有 `lo`。**先看虛擬網路線有沒有插上。**

```bash
ip -brief addr show
```

```text
lo               UNKNOWN        127.0.0.1/8 ::1/128
ens33            DOWN                              ← ★★★★★ 連 UP 都不是
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| 介面是 `DOWN`，完全沒 IP ★★★★★ | 網路卡的 `Connect at power on` 沒勾，或 `Connected` 被取消 | Settings → Network Adapter，**兩個勾選框都要勾** |
| 介面 `UP` 但沒 IPv4 ★★★★ | 主機的 `VMware DHCP Service`（`VMnetDHCP`）沒跑 | `Get-Service VMware*` 確認；Linux 跑 `sudo vmware-networks --start` |
| 拿到 `169.254.x.x` ★★★★ | 找不到 DHCP。Bridged 自動橋接綁到沒插線的那張實體網卡 | 虛擬網路編輯器 → VMnet0 → `Automatic Settings…` → **只勾實際在用的那張網卡** |
| VMnet2 之類的自訂網段一直拿不到 IP ★★★★ | 該網段刻意關掉了 DHCP | ★★★★★ **這是設計如此，必須手動設固定 IP** |
| VM 自己架的 DHCP 發不出 IP ★★★★★ | **VMware 的 DHCP 也在同一網段搶答**，兩個 DHCP 打架 | 虛擬網路編輯器 → 該 VMnet → 取消 `Use local DHCP service` |
| 主機睡眠喚醒後整個網路不通 ★★★ | 虛擬網路服務在喚醒後狀態異常 | 重啟 VMware NAT／DHCP 服務；或把網路卡取消 `Connected` 再勾回來 |

【2】★★★★★ **NAT 模式最經典的一個錯：閘道寫成 `.1`。**

```bash
ip route
```

```text
default via 192.168.100.1 dev ens33 proto static     ← ★★★★★ 錯了
```

NAT 網段上有三個固定位址，角色完全不同：

| 位址 | 角色 | 常見誤會 |
| --- | --- | --- |
| `192.168.x.1` ★★★★ | **主機的 VMnet8 網卡** | ★★★★★ 很多人以為它是閘道 —— **它不是** |
| `192.168.x.2` ★★★★★ | **預設閘道 ＋ DNS 轉送** | 這個才是要填進 `via` 的 |
| `192.168.x.254` ★★★★ | DHCP 伺服器 | — |
| `192.168.x.128–254` ★★★ | 預設動態範圍 | 設固定 IP 要**避開**，用 `.10`–`.99` |

Netplan 改法（`192.168.100.x` 只是例子，實際網段用你自己查到的）：

```yaml
network:
  version: 2
  ethernets:
    ens33:
      dhcp4: false
      addresses: [192.168.100.50/24]
      routes:
        - to: default
          via: 192.168.100.2      # ★★★★★ 是 .2 不是 .1
      nameservers:
        addresses: [192.168.100.2, 1.1.1.1]
```

```bash
sudo chmod 600 /etc/netplan/*.yaml
sudo netplan try            # ★★★★★ 用 try 不要用 apply，設錯會自動還原
```

> [!warning] ★★★★★ 遠端改網路設定一律用 `netplan try`
> `netplan apply` 設錯就直接失聯，只能開 Workstation 的**主控台視窗**進去救。
> `netplan try` 有倒數，沒按 Enter 確認就自動還原。

【3】★★★★★ Bridged 專屬的三個坑。**這一組是機關環境最容易出事的地方。**

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ Bridged 有線正常、無線就拿不到 IP | **無線 AP 只允許一個 MAC**，或有 802.1X 認證 | **改用 NAT。** 這是無線環境下唯一可靠的做法 |
| ★★★★★ 一開 Bridged，連主機自己都斷網 | 交換器埠安全（port security）偵測到第二個 MAC，把埠 `err-disable` | ★★★★★ **立刻改回 NAT**，請網管重新啟用該埠 |
| ★★★★ 公司網路禁止多 MAC，一橋接就被隔離 | 同上，機關網路常見的 NAC 政策 | 同上；**在機關網路上請避免 Bridged** |

> [!danger] ★★★★★ Bridged 是把一台沒打補丁的實驗機直接放到機關網路上
> 它拿的是實體網段的 IP，在網管眼裡就是一台新電腦，還帶著看得出來的 VMware MAC 前綴
> （`00:0C:29`、`00:50:56`）。
> **本手冊的預設一律是 NAT**；需要讓別人連進來時，優先用 NAT ＋ 埠轉發，
> 而不是改成 Bridged。

【4】★★★★ ping 得通 IP 但域名不通 —— 純 DNS 問題，不要再去查路由。

```bash
ping -c 3 1.1.1.1                     # 通 → 網路層沒問題
getent hosts archive.ubuntu.com       # 沒輸出 → 就是 DNS
resolvectl status
```

解法：Netplan 的 `nameservers.addresses` 加上 `192.168.x.2`（NAT 的 DNS 轉送），
或直接指定內部 DNS。

【5】★★★★ 兩台 VM 明明在同一台主機上卻 ping 不到。★★★★★ **九成是在不同的 VMnet 上。**

| 方向 | Bridged | NAT | Host-only | LAN Segment |
| --- | --- | --- | --- | --- |
| VM ↔ 同一個 VMnet 的 VM | ✓ | ✓ | ✓ | ✓ |
| ★★★★★ VM ↔ **不同** VMnet 的 VM | ✗ | ✗ | ✗ | ✗ |
| VM ↔ 主機 | ✓ | ✓ | ✓ | ★★★★★ **✗** |
| VM → 外網 | ✓ | ✓ | ✗ | ✗ |
| 外網 → VM | ✓ | ★★★★★ 需埠轉發 | ✗ | ✗ |

★★★★★ **不同 VMnet 之間預設不通，就像插在兩台沒有互連的交換器上。**
要讓它們通只有一個辦法：**放一台有兩張網卡的 VM 當路由器**。

**原理詳見**：[[050-01-02-04-guide-Workstation-網路模式]] 的〈可達性矩陣〉、
〈本手冊各章實驗環境該選哪一種〉與〈常見錯誤與排錯〉。

---

### ★★★★ 情境四：主機自己連得到 VM 的服務，別人連不到

**現象**：你在主機瀏覽器打 `http://192.168.100.50` 看得到網站，
同事在他自己的電腦上打同一個位址什麼都沒有。

> [!note] ★★★★★ 先把一個常見誤會講清楚
> 很多人以為「NAT 就是外面連不進來，所以主機也連不進去」—— **錯**。
> **主機身上有一張 VMnet8 網卡，跟 VM 在同一個網段，所以主機可以直接連進 VM，
> 完全不需要埠轉發。** 埠轉發是給「**主機以外**的機器」用的。

**判斷分流**：★★★★★ **先分清楚「誰連不到」，三種答案三條路。**

```text
連 VM 自己都連不到（VM 內 curl 127.0.0.1 就不通）  → 走【1】服務層
VM 內通、主機不通                                   → 走【2】網路模式與防火牆
主機通、同事不通                                     → 走【3】埠轉發與主機防火牆
```

【1】★★★★★ 先在 VM 裡面確認服務真的在聽，而且**聽在對的位址上**。

```bash
ss -tlnp | grep ':80'
```

```text
LISTEN 0  511  127.0.0.1:80   0.0.0.0:*  users:(("nginx",pid=812,fd=6))
                ↑ ★★★★★ 只監聽 127.0.0.1，外面永遠連不到
```

```text
LISTEN 0  511    0.0.0.0:80   0.0.0.0:*  users:(("nginx",pid=812,fd=6))
                ↑ 這樣才對
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ VM 內 `curl 127.0.0.1` 通、從外面不通 | 服務只監聽 `127.0.0.1` | 改服務設定監聽 `0.0.0.0` 或指定位址 |
| VM 內 `curl` 也不通 ★★★★ | 服務根本沒起來 | `systemctl status <服務>` |
| 主機 ping 得到 VM 但連不到埠 ★★★★ | Guest 自己的防火牆擋著 | `sudo ufw status`；RHEL 系 `sudo firewall-cmd --list-all` |

【2】★★★★ VM 內通、主機不通。查網路模式：

```text
Host-only / LAN Segment ？ → LAN Segment 連主機都碰不到，這是設計如此
不同 VMnet ？              → 主機的哪一張虛擬網卡在那個網段上
```

【3】★★★★★ 主機通、同事不通。這才是真正要設埠轉發的情況。**兩層都要通。**

```text
   同事的電腦
      │  ① 主機的 Windows 防火牆要放行  ← ★★★★★ 最常漏的一層
      ▼
   主機 :8080
      │  ② VMware 的 NAT 埠轉發規則
      ▼
   VM 192.168.100.50 :80
      │  ③ Guest 防火牆 + 服務監聽 0.0.0.0
      ▼
   Nginx
```

設定位置：**虛擬網路編輯器 → VMnet8 → `NAT Settings…` → `Port Forwarding` → `Add…`**
（Windows 要先按左下角的 **Change Settings** 提升權限；Linux 用 `sudo vmware-netcfg`）。

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 埠轉發設好了，主機 `curl 127.0.0.1:8080` 還是不通 | **VM 用 DHCP，重開機 IP 換了**，規則指到空位址 | ★★★★★ **埠轉發的前提是 VM 固定 IP**，先設好 Netplan 再設轉發 |
| ★★★★★ 主機自己連得到，同事連不到 | **主機的 Windows 防火牆**擋住，或該網路被判定為「公用網路」 | 為該埠建立輸入規則，並確認網路設定檔為「私人」 |
| 改了虛擬網路編輯器但沒生效 ★★★★★ | ★★★★★ **忘記按 Change Settings**，或沒按 Apply | Change Settings → 重改 → Apply → OK |
| 自訂網段的 VM 有 IP 但上不了網 ★★★★ | 該 VMnet 沒開 NAT，也沒有 router VM 做轉送 | 開 NAT，或建一台雙網卡 router VM |

> [!danger] ★★★★★ 埠轉發等於在你的主機上開了一個對外的門
> 你轉發出去的是一台**沒有打補丁、密碼可能很簡單的實驗機**。
> 做完測試就**把規則刪掉**，不要一直留著。
> 實驗機上絕不放真實資料與憑證。

**原理詳見**：[[050-01-02-04-guide-Workstation-網路模式]] 的〈NAT 埠轉發：讓外面連進 VM 裡的服務〉
與〈安全性注意事項〉。

---

### ★★★★ 情境五：主機磁碟空間爆掉

**現象**：主機碟越來越小、VM 執行到一半跳「磁碟空間不足」並暫停、
`.vmdk` 明顯大於 Guest 裡 `df` 顯示的用量。

> [!danger] ★★★★★ 看到「磁碟空間不足，VM 已暫停」時：不要按 Abort
> Workstation 是**為了保護資料**才把 VM 暫停的。
> **正確順序是：先到主機上清出空間 → 再回來按 Retry。**
> 按 Abort 等同對執行中的 Guest 硬斷電，Guest 檔案系統可能損壞。

**判斷分流**：空間被吃掉只有兩個來源，**先分清楚是哪一個**。

```text
VM 資料夾裡有一堆 -000001.vmdk ～ -00000N.vmdk  → 快照鏈（走【1】）
只有一個大 .vmdk，但遠大於 Guest 的 df          → 動態磁碟只長不縮（走【2】）
兩者都有                                        → 先做【1】再做【2】，順序不能反
```

【1】★★★★★ 先看快照。`Ctrl+M` 打開快照管理員，或直接數檔案：

```powershell
Get-ChildItem 'D:\VMs\lab-ubuntu' -Filter '*-0000*.vmdk' | Measure-Object
```

```bash
ls -lh ~/vmware/lab-ubuntu/*-0000*.vmdk
```

★★★★ 看到 `-000001` 一路排到 `-000009`，代表累積了九個快照。

| 條件 | 該做什麼 |
| --- | --- |
| 變更驗證完成 ★★★★★ | **立刻刪掉變更前的那個快照** |
| 快照 ≥ 3 個 ★★★★ | 檢視並清理 |
| 快照存在超過兩週 ★★★★ | 檢討是否還需要 |
| ★★★★★ 主機剩餘空間 < 20% | **立刻清** |
| 要擴充虛擬磁碟 ★★★★ | 必須全刪（`Expand` 才不會是灰的） |
| 要做效能測試 ★★★★ | 必須全刪（否則數據忽高忽低不可信） |
| 要匯出 OVF ★★★★ | 必須全刪 |

> [!danger] ★★★★★ 刪除快照（尤其是 Delete All）是不可逆的
> 刪快照的動作是**把差異磁碟合併回基礎磁碟**，之前的還原點就此消失。
> 而且合併過程需要額外空間、可能跑很久。
>
> - **不要在主機空間快滿的時候刪大快照** —— 合併需要空間，中斷會很慘
> - ★★★★★ **刪除快照時 VM 看似當機是正常的**，delta 檔案很大就是要跑那麼久。
>   **不要強制關閉、不要斷電。**
> - 必要的還原點請改用**完整複製**保存，那才是能獨立存在的一份

【2】★★★★★ 動態磁碟只長不縮。**這是「主機磁碟莫名其妙被吃光」最常見的原因。**

```text
Guest 裡：df 顯示用了 8 GB
Host 上：.vmdk 已經 45 GB
         ↑ 這 37 GB 是「曾經寫過但已經刪掉」的空間
```

Guest 刪檔時只是把檔案系統的區塊標記成可用，**`.vmdk` 完全不知道**。
★★★★★ **只做 Host 端的 Compact 沒有用**，因為 Host 分不出哪些區塊是垃圾。
必須「**先歸零，再壓縮**」，兩步缺一不可：

```bash
# 步驟 1（Guest 端）：先清乾淨
sudo apt clean
sudo journalctl --vacuum-time=1d

# 步驟 2（Guest 端）：把可用空間歸零
sudo vmware-toolbox-cmd disk shrink /
```

```text
Please disregard any warnings about disk space for the duration of shrink process.
Progress: 100 [=======================>]
Disk shrinking complete.
```

```bash
# 步驟 3（Host 端，VM 完全關機後）
vmware-vdiskmanager -k /path/to/lab-ubuntu.vmdk
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 壓縮選單是灰色的／壓縮失敗 | **存在快照**，或 VM 不是完全關機 | 先刪除所有快照（**不可逆**）並完全關機 |
| 壓縮完 `.vmdk` 幾乎沒變小 ★★★★ | 沒做 Guest 端歸零，Host 認不出垃圾區塊 | 補做 `disk shrink`（Windows Guest 用 `sdelete64.exe -z C:`） |
| ★★★★ VM 資料夾在 OneDrive／Dropbox 裡 | 同步軟體不停鎖檔、還會把整包上傳 | **把 VM 資料夾搬出同步範圍**，並在同步軟體排除該路徑 |
| AutoProtect 把空間吃光 ★★★★ | 自動快照持續累積 | 快照管理員 → AutoProtect 分頁取消勾選，並手動刪掉已產生的自動快照 |

> [!danger] ★★★★★ 壓縮前先完整複製一份 VM 目錄
> 壓縮過程異常中斷可能損壞 `.vmdk`。
> 另外 `dd if=/dev/zero` 這種手動歸零法會**把磁碟寫滿**，
> 執行中的服務可能因此損壞資料 —— **絕不在正式機上做**。

**原理詳見**：
[[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈磁碟膨脹與壓縮〉與〈快照鏈：不是越多越好〉、
[[050-01-02-03-guide-Workstation-快照與複製]] 的〈快照鏈太長的後果與清理時機〉。

---

### ★★★★★ 情境六：效能突然變慢，之前都好好的

**現象**：同一台 VM，昨天還很順，今天開機要好幾分鐘、指令有延遲、
主機的滑鼠都會卡。

★★★★★ **「之前都好好的」這五個字是關鍵 —— 代表有東西變了。**
不要一開始就去調 CPU 與記憶體，先找出「變了什麼」。

**判斷分流**：★★★★★ **依序檢查這五件事，九成在裡面。**

```text
① 快照又長出來了嗎？          Ctrl+M 數一下
② 主機碟是不是快滿了？         df -h / Get-PSDrive
③ 防毒開始掃 VM 目錄了嗎？     最近更新過防毒或改過政策？
④ 筆電切到省電模式了嗎？       拔掉電源就變慢＝這一項
⑤ 別人也在用同一台主機嗎？     工作管理員看有幾個 vmware-vmx
```

【1】★★★★ 快照鏈。每多一層快照，讀取就要多走一層差異磁碟。

```text
base.vmdk ← -000001.vmdk ← -000002.vmdk ← -000003.vmdk（目前在寫這一層）
   ↑ 讀一個舊區塊，最壞情況要往回問四層
```

處置：快照管理員 → 確認哪些不需要 → Delete（合併回去）。
★★★★★ **效能測試前一定要 Delete All Snapshots**，不然數據忽高忽低不可信。

【2】★★★★ 主機碟快滿。剩不到 20% 時，動態磁碟擴檔會變得很慢，主機自己也會卡。

【3】★★★★ 防毒掃描虛擬磁碟。`.vmdk` 是一直在變動的大檔，防毒會一直重掃。

> [!warning] ★★★★ 排除防毒時，優先排除「程序」而不是「整個資料夾」
> 把整個 VM 目錄加進排除清單，代表**下載到那個目錄的東西也不會被掃**。
> 較安全的做法是只排除 `vmware-vmx.exe` 這個程序，
> 並且**不要把 VM 目錄當成下載資料夾**。

【4】★★★ 筆電電源計畫。省電模式會壓低 CPU 時脈，VM 特別有感。
在 Guest 裡可以間接看到實際時脈：

```bash
vmware-toolbox-cmd stat speed
```

【5】★★★★★ 資源被瓜分。**先確認總量，再談分配。**

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 配了 8 vCPU 反而比 2 vCPU 慢 | vCPU 超配造成 co-scheduling 等待 | 降回 2～4 vCPU；**所有執行中 VM 的 vCPU 總和 ≤ 主機實體核心數**（不算超執行緒） |
| Guest 的 load average 遠高於 vCPU 數 ★★★★ | vCPU 配太少，或主機 CPU 被超配 | 加 vCPU，或減少同時執行的 VM |
| ★★★★ Guest `top` 的 `%wa` 長期偏高 | 磁碟太慢（傳統硬碟），或多台 VM 搶同一顆碟 | 把 `.vmdk` 搬到 SSD；減少同時執行的 VM |
| ★★★★ Windows 主機上 VM 一開機整台就卡 | 記憶體超配導致主機開始 swap | 調降 VM 記憶體，確保主機 `Available MBytes` ≥ 4000 |
| 開機很慢，停在偵測裝置階段 ★★★ | 殘留的軟碟機、序列埠等虛擬裝置 | 移除 Floppy、Serial、Parallel、Sound、Printer |

> [!danger] ★★★★★ 主機開始 swap 就全滅
> 把記憶體配到主機只剩 1～2 GB，Windows 會開始把東西丟進 pagefile。
> 這時候**不是只有 VM 慢，是整台電腦（連滑鼠都會卡）一起慢**，
> 而且 VM 的記憶體檔案也在被換出換入，會惡性循環。
> **給主機留 4～6 GB 是硬底線。**

診斷指令一次列齊：

| 要看什麼 | 主機（Windows） | Guest（Linux） |
| --- | --- | --- |
| CPU 核心數 ★★★★ | `Get-CimInstance Win32_Processor \| Select NumberOfCores` | `nproc` |
| 可用記憶體 ★★★★★ | `Get-Counter '\Memory\Available MBytes'` | `free -h` |
| 負載 ★★★★ | 工作管理員 | `uptime`（比對 vCPU 數） |
| I/O 等待 ★★★★ | 資源監視器 | `top` 看 `%wa`；`iostat -x 2` |
| 氣球佔用 ★★★ | — | `vmware-toolbox-cmd stat balloon` |

**原理詳見**：[[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的
〈第一原則：資源是從主機挖走的〉、〈CPU 配置準則〉、〈記憶體配置準則〉，
以及那張 27 列的排錯總表（單一訊息對單一解法都在那裡）。

---

### ★★★★ 情境七：巢狀虛擬化跑不動（要在 VM 裡跑 PVE／KVM）

**現象**：想在 Workstation 的 VM 裡再裝 Proxmox VE 或 KVM，結果：
勾選框是灰的、開 VM 時報錯、或裝好了但 Guest 裡 `kvm-ok` 說不能用。

**判斷分流**：★★★★★ **巢狀虛擬化有三個前提，缺一不可。照順序驗，不要跳。**

```text
前提一：Host 上沒有其他 Hypervisor    HyperVisorPresent 必須是 False
前提二：Host CPU 支援 EPT（Intel）／RVI-NPT（AMD）
前提三：VM 的虛擬硬體版本夠新（太舊的沒有那個勾選框）
```

【1】★★★★★ 前提一。Windows 主機上這是最常見的失敗原因。

```powershell
Get-ComputerInfo -Property "HyperVisorPresent"
```

★★★★★ **必須是 `False`。** 是 `True` 就先回〈情境一〉把 Hyper-V 層關掉，
**不要繼續往下做**，後面每一步都會失敗。

> [!warning] ★★★★★ 「共存模式」不能做巢狀虛擬化
> 較新版 Workstation 可以在 Hyper-V 存在時以 Windows Hypervisor Platform 運作，
> VM **開得起來**，但效能明顯較差，而且**巢狀虛擬化通常不可用或極不穩**。
> 要做 PVE／KVM 章節，只有把 Hyper-V 層關掉這條路。

【2】★★★★ 前提二與前提三。開 VM 設定看那個勾選框：

**`VM → Settings → Processors → Virtualization engine`**，
勾 **`Virtualize Intel VT-x/EPT or AMD-V/RVI`**。

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `Processors` 頁上根本沒有那個勾選框 | 虛擬硬體版本太舊 | `VM → Manage → Change Hardware Compatibility…` 升級 |
| ★★★★★ 勾選框是灰的 | Hyper-V 層還在（共存模式），或 **VM 正在執行中** | 先完全關機再改；仍是灰的就回〈情境一〉 |
| ★★★★★ `Virtualized Intel VT-x/EPT is not supported on this platform.` | Host 缺 EPT／RVI，或仍有其他 Hypervisor | 先確認 `HyperVisorPresent` = `False`；再確認 CPU 支援 EPT／RVI |

> [!danger] ★★★★ 升級虛擬硬體相容性是不可逆的
> `Change Hardware Compatibility` 升上去之後**不能降回舊版本**，
> 舊版 Workstation 就打不開這台 VM 了。**升級前先完整複製整個 VM 目錄。**

【3】★★★★★ 也可以直接改 `.vmx`（**VM 必須完全關機，不是 Suspend**）：

```ini
vhv.enable = "TRUE"
```

| 參數 | 作用 |
| --- | --- |
| `vhv.enable = "TRUE"` ★★★★★ | 巢狀虛擬化本體 |
| `vpmc.enable = "TRUE"` ★★★ | 虛擬效能計數器 |
| `vvtd.enable = "TRUE"` ★★★ | IOMMU（裝置直通） |

> [!warning] ★★★★ 改了 `.vmx` 卻沒生效？
> 幾乎都是**改檔時 VM 不是完全關機**（在執行中或 Suspend 狀態）。
> Workstation 關閉時會把記憶體裡的設定寫回 `.vmx`，把你的修改蓋掉。
> **完全關機 → 改檔 → 存檔 → 才開機。**

【4】★★★★★ 進 Guest 裡驗證。**五個驗證只要有一個不過，就是沒生效。**

```bash
grep -c -E 'vmx|svm' /proc/cpuinfo
```

```text
4            ← 應等於你配的 vCPU 數；0 代表沒生效
```

```bash
lscpu | grep -i virtual
```

```text
Virtualization:                  VT-x        ← 有這一行才對
```

```bash
sudo kvm-ok
```

```text
INFO: /dev/kvm exists
KVM acceleration can be used                  ★★★★★ 這一句是最終驗收
```

```bash
ls -l /dev/kvm
lsmod | grep kvm            # 要有 kvm_intel 或 kvm_amd
```

RHEL 系可以改用 `virt-host-validate`，前三項要 `PASS`。

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `kvm-ok` 說 `KVM acceleration can NOT be used` | 勾選框沒勾，或改 `.vmx` 時 VM 沒完全關機 | 完全關機後勾選；確認 `.vmx` 裡確實有 `vhv.enable = "TRUE"` |
| `/proc/cpuinfo` 沒有 `vmx`／`svm` ★★★★★ | 同上 | 同上 |
| 巢狀的 PVE 裝得起來但慢到不能用 ★★★★ | 資源不夠 | **巢狀 PVE 建議 4 vCPU / 8 GB 以上**，並確保 `.vmdk` 在 SSD |

> [!danger] ★★★★★ 巢狀虛擬化擴大了攻擊面
> 開啟 `vhv.enable` 等於把 CPU 的特權指令暴露給 Guest。
> 歷史上出現過從 Guest 逃逸到 Host 的漏洞，巢狀環境讓這條路更複雜也更危險。
> **只在需要的那一台 VM 上開，不要當成預設值套用到所有機器。**

**原理詳見**：[[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的〈巢狀虛擬化〉整節
（含完整的 PVE 實戰步驟與十項驗收）。

---

### ★★★★ 情境八：`/mnt/hgfs` 看不到東西，以及 Tools 沒裝好的連鎖症狀

**現象**：在 Workstation 裡明明設好共享資料夾了，Guest 裡 `/mnt/hgfs` 卻是空的、
甚至根本不存在。或是一整串看似無關的小毛病同時出現。

> [!note] ★★★★★ 先記住這件事，可以省掉一半的排查
> open-vm-tools 的共享資料夾走的是**使用者空間的 `vmhgfs-fuse`**，
> **它不會自動幫你掛載**。舊版有 `vmhgfs` 核心模組會自動掛好 `/mnt/hgfs`，
> 現代 Linux 沒有。
> 「我設好共享資料夾了可是 Guest 裡看不到」這個經典問題，答案就是**你還沒掛**。

**判斷分流**：★★★★★ **先分清楚是「Host 沒給」還是「Guest 沒掛」。**

```text
vmware-hgfsclient 有輸出嗎？
   沒有輸出 → Host 端沒給（走【1】）
   有輸出   → Host 給了，Guest 沒掛（走【2】）
指令本身 command not found → open-vm-tools 沒裝（走【0】）
```

【0】★★★★ Tools 沒裝的連鎖症狀。★★★★★ **下面這些看起來毫不相干的毛病，
其實是同一個原因。** 一次對照，不要一項一項猜。

| 症狀 | 最可能的原因 | 先確認什麼 |
| --- | --- | --- |
| 滑鼠移出 VM 視窗要按 `Ctrl+Alt` ★★★ | Tools 完全沒裝 | `vmtoolsd` 有沒有在跑 |
| ★★★★ Workstation 主畫面看不到 VM 的 IP | `vmtoolsd` 沒在跑（Host 靠它回報） | `systemctl status open-vm-tools` |
| ★★★★ 選單的 `Shut Down Guest`／`Restart Guest` 是灰的 | 同上，電源事件要靠 Tools 傳達 | 同上 |
| 視窗放大後畫面沒跟著變大、四周黑邊 ★★★★ | 顯示元件沒裝（缺 `open-vm-tools-desktop`） | Guest 有沒有桌面環境 |
| 解析度選單只有幾個固定值 ★★★ | 同上 | 同上 |
| Host 與 Guest 無法複製貼上 ★★★ | 缺 `-desktop`，或 Guest Isolation 關掉了剪貼簿 | VM 設定 → Options → Guest Isolation |
| 拖放檔案沒反應 ★★★ | 同上 | 同上 |
| ★★★★★ 快照還原或主機睡醒後時間差好幾小時 | 時間同步沒設好 | 走〈情境九〉 |

安裝（★★★★★ **Linux Guest 一律裝發行版套件庫的 open-vm-tools**）：

```bash
sudo apt install -y open-vm-tools            # Ubuntu / Debian
sudo dnf install -y open-vm-tools            # Rocky / AlmaLinux
sudo apt install -y open-vm-tools-desktop    # 只有「有桌面」才裝
```

```bash
systemctl is-active open-vm-tools    # Ubuntu：open-vm-tools.service
                                     # RHEL 系：vmtoolsd.service
```

> [!danger] ★★★★★ 不要在現代 Linux 上裝原廠 VMware Tools
> 典型災難流程：照十年前的文章掛 ISO、解壓 `VMwareTools-*.tar.gz`、跑 `vmware-install.pl`。
> 結果它把自己的 `vmhgfs`、`vmxnet` 模組硬塞進系統，
> **下一次 `apt upgrade` 換了核心，模組編不過，開機後網路卡不見**。
>
> 已經誤裝的話：`sudo /usr/bin/vmware-uninstall-tools.pl` 移除乾淨，
> 再 `sudo apt install open-vm-tools`，重開機。
> ★★★★★ Windows Guest 則相反 —— **原廠 Tools 是唯一選擇**，open-vm-tools 沒有 Windows 版。

【1】★★★★★ Host 端沒給。先問 Guest「你看得到哪些共享」：

```bash
vmware-hgfsclient
```

```text
（沒有任何輸出）    ← ★★★★★ Host 端根本沒開共享，或沒 Add 任何一個
```

處置：**`VM → Settings → Options → Shared Folders`** →
設為 `Always enabled` → `Add…` 新增一個共享。

【2】★★★★★ Host 給了，Guest 沒掛。手動掛一次確認：

```bash
sudo mkdir -p /mnt/hgfs
sudo vmhgfs-fuse .host:/ /mnt/hgfs -o allow_other
ls /mnt/hgfs
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `/mnt/hgfs` 存在但完全是空的 | **只建了目錄，沒有掛載** | 上面那行 `vmhgfs-fuse`，再寫進 `/etc/fstab` |
| `/mnt/hgfs` 根本不存在 ★★★★ | 掛載點沒建 | `sudo mkdir -p /mnt/hgfs` |
| `fusermount: option allow_other only allowed if 'user_allow_other' is set in /etc/fuse.conf` ★★★★ | FUSE 未開放給其他使用者 | 取消註解 `/etc/fuse.conf` 裡的 `user_allow_other` |
| 一般使用者 `ls /mnt/hgfs` 得到 `Permission denied` ★★★★ | 用 root 掛載且沒加 `allow_other` | 重新掛載時加 `allow_other`，或加 `uid=`／`gid=` |
| ★★★★ `mount: unknown filesystem type 'vmhgfs'` | fstab 型別寫成舊的 `vmhgfs` | 改成 **`fuse.vmhgfs-fuse`** |
| Windows Guest 找不到 `\\vmware-host\Shared Folders` ★★★★ | 共享是 Disabled，或 VMTools 服務沒跑 | 設為 Always enabled；`Get-Service VMTools` 要 `Running` |

【3】★★★★★ 寫進 `/etc/fstab` 讓它開機自動掛。**`nofail` 不能省。**

```text
.host:/  /mnt/hgfs  fuse.vmhgfs-fuse  allow_other,defaults,nofail  0  0
```

```bash
sudo mount -a        # ★★★★★ 一定要在這裡驗一次，不要直接重開機
```

> [!danger] ★★★★★ fstab 少了 `nofail`，下次開機會掉進 emergency mode
> 這一行掛不起來時，systemd 會判定「本機檔案系統」失敗，整台停在
> `Give root password for maintenance:`。
>
> 救法：在 maintenance shell 裡 `mount -o remount,rw /` →
> 編輯 `/etc/fstab` 補上 `nofail`（或先註解掉該行）→ `reboot`。
> 詳細流程見 [[020-01-98-trouble-Linux-常見故障排除]]。

【4】★★★★ 掛起來了，但用起來怪怪的。**這些不是壞掉，是 HGFS 本來就不支援。**

```text
HGFS 不是 POSIX 完整的檔案系統：
  不支援硬連結
  不支援 UNIX 權限位元（所有檔案看起來同一個 uid/gid）
  chmod 大多無效
  inotify 不可靠
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ 在共享裡跑 `git clone`／`npm install` 大量權限與連結錯誤 | HGFS 不支援符號連結與完整 POSIX 權限 | ★★★★★ **不要在 `/mnt/hgfs` 裡開發**，複製到本機路徑再操作 |
| 看不到剛在 Host 建立的新檔 ★★★ | HGFS 目錄快取尚未更新 | `ls` 一次上層目錄通常就刷新；必要時 `umount` 重掛 |

> [!warning] ★★★★ 共享資料夾的正確定位是「搬檔案用的臨時通道」
> 拿它放 Web 根目錄或資料庫檔案，會遇到權限錯亂、`inotify` 失效、效能低落、
> 檔案鎖行為異常一連串問題。真正要跑的東西請複製進 Guest 的本機檔案系統。
>
> ★★★★ 另外 HGFS **不走 TCP/IP**，走的是 Host 與 Guest 之間的 VMCI 通道 ——
> 所以 VM 網路完全不通的時候，共享資料夾照樣能用，**這在進去救網路設定時很有用**。

**原理詳見**：[[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的
〈VMware Tools 與 open-vm-tools 的差別〉、〈HGFS：共享資料夾到底怎麼運作〉與〈常見錯誤與排錯〉。

---

### ★★★ 情境九：VM 時間跑掉

**現象**：主機睡眠喚醒後 Guest 慢了好幾小時、還原快照後時間跳回過去、
`journalctl` 一堆 `System clock was stepped by …`、`apt update` 說 `not valid yet`。

★★★★★ **不要覺得「差幾分鐘沒差」。** 會炸的東西非常多：

| 影響 | 症狀 |
| --- | --- |
| ★★★★★ TLS／HTTPS 憑證驗證 | `certificate is not yet valid` 或 `has expired`，所有 HTTPS 連線失敗 |
| ★★★★★ Kerberos／AD 網域登入 | 時間差超過 5 分鐘直接拒絕認證，加入網域失敗 |
| ★★★★ `apt update` | `Release file ... is not valid yet` |
| ★★★★ 日誌關聯分析 | 多台機器時間對不上，事件排不出先後 |
| ★★★ 排程工作 | cron／systemd timer 在錯誤的時間點爆發性執行 |
| ★★★★ TOTP 兩步驟驗證 | 驗證碼永遠是錯的 |

**判斷分流**：★★★★★ **先分清楚是「一次性跳掉」還是「一直在跳」。**

```text
主機睡醒／還原快照之後跳一次，之後穩定  → 走【1】（一次性事件）
journalctl 一直出現 System clock was stepped → 走【2】（兩套授時在打架）
時間慢慢漂移，一天差幾秒到幾分鐘        → 走【3】（沒有 NTP 或 NTP 不通）
```

【1】★★★★★ 一次性跳掉。**先救回來，再處理根因。**

```bash
timedatectl
sudo chronyc makestep       # 立即強制校正
```

原因是虛擬機沒有真正的 RTC 晶片，時間靠 Hypervisor 模擬的中斷推算。
**Host 進睡眠時 VM 收不到該收的中斷，醒來就慢了整整睡眠的那段時間。**

| 情境 | 時間會怎樣 | 嚴重度 |
| --- | --- | --- |
| ★★★★★ Host 睡眠／休眠再喚醒 | 醒來後**慢了整整睡眠的時間** | 筆電使用者天天遇到 |
| ★★★★★ 還原快照 | 時間跳回快照當時，可能倒退好幾天 | 極常見 |
| ★★★★ Suspend 後恢復 | 同睡眠情境 | 常見 |
| ★★★ Host CPU 長時間滿載 | 慢慢漂移 | 慢性 |

【2】★★★★★ **一直在跳 = 兩套授時機制在打架。這是本情境的核心。**

```text
  ┌─ VMware Tools 時間同步 ──→ 從 Host 的時鐘抄（Host 自己準不準？不一定）
  時鐘
  └─ chrony / systemd-timesyncd ─→ 從 NTP 伺服器抄（準，但需要網路）
```

> [!danger] ★★★★★ 最糟的組合：兩個都開著
> Tools 從 Host 抄一個時間、chrony 從 NTP 抄另一個，兩邊差一點點，時鐘就被來回 step。
> **這種機器的日誌時間戳完全不能信，排查故障時你會被自己的日誌騙。務必二選一。**

| 情境 | 該留哪一套 |
| --- | --- |
| ★★★★★ 伺服器類實驗機（Web／DB／AD／監控） | **關掉 Tools 同步，用 chrony 走 NTP** |
| ★★★★ 完全沒有網路的隔離實驗機 | 反過來：**開 Tools 同步，停掉 chrony** |
| ★★★★★ 要加入 AD 網域的 VM | 一律用 NTP，而且**授時來源要是網域控制站** |

【3】★★★★★ 關掉 Tools 授時的**正確做法（兩步，只做第一步沒有用）**：

```bash
sudo vmware-toolbox-cmd timesync disable
vmware-toolbox-cmd timesync status
```

```text
Disabled
```

★★★★★ **這一步幾乎所有教學都漏掉**：即使 `timesync disable`，
在「恢復暫停」「**還原快照**」「開機」這些事件發生時，Tools **仍然會做一次性校時**。
要完全關掉必須改 `.vmx`（VM 需**完全關機**）：

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
| `time.synchronize.restore` ★★★★★ | **還原快照後** —— 最容易被忽略的一項 |
| `time.synchronize.continue` ★★★★ | 從暫停恢復後 |
| `time.synchronize.tools.startup` ★★★★ | Tools 服務啟動時（＝每次開機） |
| `time.synchronize.resume.disk` ★★★ | 磁碟恢復後 |
| `time.synchronize.shrink` ★★★ | 磁碟壓縮後 |

排錯對照：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `timesync status` 顯示 `Disabled` 但時間還是被改 | **只關了週期性同步，事件觸發的還開著** | 在 `.vmx` 補上那六項 |
| ★★★★ 改了 `.vmx` 重開後設定不見了 | 改檔時 VM 不是完全關機 | 完全關機（不是 Suspend）後再改 |
| ★★★★ `chronyc sources` 全部顯示 `^?` | 網路不通或 UDP/123 被擋 | 確認網路模式與對外連線；隔離環境改用 Tools 授時 |
| ★★★★★ 加入 AD 網域失敗，提示時間差異過大 | Guest 與網域控制站差超過 5 分鐘 | chrony 的 `server` 指向網域控制站，`chronyc makestep` 後重試 |

> [!warning] ★★★★ 虛擬機的 chrony 設定要把 `rtcsync` 註解掉
> `rtcsync` 是叫核心定期把系統時間寫回硬體時鐘。虛擬機的「硬體時鐘」是模擬的，
> 這個動作意義不大，還可能與 Hypervisor 的時間處理互相干擾。

**原理詳見**：[[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈時間同步的坑〉，
Linux 端的 chrony 設定見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]]。

---

### ★★★ 情境十：複製 VM 之後兩台打架

**現象**：兩台複製出來的機器搶同一個 IP、SSH 指紋一模一樣、
`ssh` 報 `REMOTE HOST IDENTIFICATION HAS CHANGED`。

★★★★★ **複製 VM 只複製了「檔案」，沒有複製「身分」。**
複製出來的第二台，身上帶著第一台的所有識別碼。

**判斷分流**：

```text
兩台一起開機就網路不通       → IP 衝突（走【1】）
兩台的 SSH 指紋一樣          → host key 沒重新產生（走【2】）
DHCP 一直發同一個 IP 給兩台  → machine-id 相同（走【3】）
ssh 報 HOST IDENTIFICATION CHANGED → ★★★ 這通常是正常的（走【4】）
```

【1】★★★★★ 複製後**必改四項**。少改一項就會有一種奇怪症狀。

| 項目 | 指令 | 不改的症狀 |
| --- | --- | --- |
| hostname ★★★★ | `sudo hostnamectl set-hostname <新名>`（記得也改 `/etc/hosts`） | 日誌分不出是哪一台 |
| ★★★★★ machine-id | `sudo rm /etc/machine-id /var/lib/dbus/machine-id && sudo systemd-machine-id-setup` | **DHCP 發同一個 IP 給兩台** |
| ★★★★★ SSH host key | `sudo rm -f /etc/ssh/ssh_host_* && sudo ssh-keygen -A && sudo systemctl restart ssh` | 兩台指紋一樣，中間人攻擊分不出來 |
| 靜態 IP ★★★★ | 改 `/etc/netplan/*.yaml` → `sudo netplan try` | 兩台 IP 衝突 |

改完驗證，**每一台的值都要不一樣**：

```bash
hostnamectl
cat /etc/machine-id
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
ip -4 addr show ens33
```

【2】★★★★ 為什麼 `machine-id` 會造成 IP 衝突？
現代 Linux 的 DHCP 客戶端拿 `machine-id` 當作 DHCP client identifier。
兩台的識別碼一樣，DHCP 伺服器就認為它們是同一台機器，發同一個 IP。

【3】★★★★ 確認是不是真的 IP 衝突：

```bash
ip neigh
arping -I ens33 192.168.100.50
```

【4】★★★ `REMOTE HOST IDENTIFICATION HAS CHANGED` **通常是正常且正確的**：
那個 IP 之前是另一台機器，host key 當然不同。SSH 在保護你，不是在報錯。

```bash
ssh-keygen -R 192.168.100.50
```

> [!danger] ★★★★★ 範本裡不能有任何機密
> 範本被複製出去幾十份，裡面的東西也就複製了幾十份。
> **範本裡不要放憑證、私鑰、機關資料、正式環境的密碼。**
> 實驗機的密碼**不能和正式環境相同**。

【5】★★★★ 連結複製特有的問題：**它完全依賴來源 VM。**

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 連結複製開機報找不到磁碟 | **來源 VM 被刪除、改名或搬移** | 把來源還原到原路徑與原名稱；或手動編輯複本 `.vmdk` 描述檔的 `parentFileNameHint` |
| 快照管理員裡某個快照刪不掉，訊息提到 linked clones ★★★ | 該快照正被連結複製依賴 | 先刪掉依賴它的複本，或把那些複本轉成完整複製 |
| `Create a linked clone` 是灰的 ★★★ | 來源 VM 沒有任何快照，或選了 `The current state` | 先關機拍一個快照，複製時選 `An existing snapshot` |
| `Clone` 選單整個沒有 ★★★ | VM 開機中，或用的是 **Player**（沒有這個功能） | 先關機；Player 改用手動複製整個資料夾（等同完整複製） |
| 匯出 OVF 失敗或內容不符預期 ★★★★ | VM 有快照，或這是連結複製的 VM | 先 Delete All Snapshots；連結複製要先轉成完整複製 |

> [!warning] ★★★★ 連結複製不適合放機密資料，也不能搬走
> 它與來源共用基礎磁碟，**來源一動就全垮**，而且不能匯出。
> 要長期保存、要搬到別台、要做效能測試 → 一律用**完整複製**。

**原理詳見**：[[050-01-02-03-guide-Workstation-快照與複製]] 的
〈複製：連結複製 vs 完整複製〉與〈複製後一定要改的四樣東西〉。

---

### ★★★ 情境十一：升級 Workstation 之後，舊的 VM 出問題

**現象**：升級 Workstation 大版本之後，舊 VM 開不起來、一直提示 Tools 過期、
或勾選框位置變了找不到。

**判斷分流**：★★★★★ **分成「開不起來」與「開得起來但有毛病」兩條路，處理順序不能反。**

```text
完全開不起來 → 走【1】（模組／服務／硬體相容性）
開得起來但一直跳 Tools 過期 → 走【2】（Tools 版本）
開得起來但選項找不到 → 走【3】（虛擬硬體版本）
```

【1】★★★★ 開不起來。升級後最常見的三個原因：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ Linux 主機升級後打不開 | 新版程式配新核心模組，模組還沒編 | `sudo vmware-modconfig --console --install-all`，Secure Boot 環境要**重新簽章** |
| ★★★★ Windows 主機升級後 VM 打不開／權限錯誤 | `VMware Authorization Service` 沒起來 | `Start-Service VMAuthdService` |
| 安裝時卡在「正在移除舊版」很久 ★★ | 舊版仍有 VM 在跑或服務卡住 | 先關掉所有 VM 與 Workstation 視窗，必要時重開機再裝 |
| ★★★★ 升級後才發現 Hyper-V 又回來了 | 網域 GPO 強制啟用 VBS／Credential Guard | 這是政策層問題，**找資安單位處理，不要自行繞過** |

【2】★★★ 一直提示「VMware Tools 已過期」。

| Guest | 處理 |
| --- | --- |
| ★★★★★ Linux | 改用 `open-vm-tools`（發行版套件庫版本），**提示就會消失**，之後跟著 `apt upgrade` 一起更新 |
| ★★★★ Windows | 重跑 `VM → Install VMware Tools` → `D:\setup64.exe` |

★★★★★ 這正是本手冊堅持 Linux Guest 用 open-vm-tools 的理由：
原廠版每次 Workstation 升級都要手動追，開源版**跟著系統一起更新，不用管**。

【3】★★★★ 開得起來但選項找不到／是灰的。多半是**虛擬硬體版本停在舊版**。

```text
VM → Manage → Change Hardware Compatibility…
```

> [!danger] ★★★★★ 升級虛擬硬體相容性不可逆
> 升上去之後**不能降回舊版**，舊版 Workstation 就打不開這台 VM 了。
> **升級前先完整複製整個 VM 目錄。**
> 如果只是為了某一個勾選框而升級，先想清楚這台 VM 之後還要不要給別人用。

【4】★★★★ 升級前後的自保步驟（★★★★★ **升級大版本前先做這三件事**）：

```text
① 把重要 VM 的整個資料夾複製到另一顆碟（不是快照，是複製）
② 記下每台 VM 目前的韌體型別（UEFI / BIOS）與硬體相容性版本
③ 先關掉所有 VM 與 Workstation 視窗再升級
```

**原理詳見**：[[050-01-02-01-svc-Workstation-安裝與授權]] 的〈升級到新的大版本〉與〈乾淨移除〉、
[[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] 的〈VMware Tools 與 open-vm-tools 的差別〉。

---

### ★★★★ 情境十二：VM 檔案損毀與救援

**現象**：`Cannot open the disk ...`、`This virtual machine appears to be in use.`、
刪快照刪到一半失敗、VM 資料夾裡多了一堆看不懂的檔案。

> [!danger] ★★★★★ 這個情境的第一動作永遠是：不要動原檔
> 在做任何救援之前，**先把整個 VM 資料夾原封不動複製一份到另一顆碟**。
> 救援失敗還有退路；直接在原檔上動手，失敗就沒了。
> ★★★★★ **這一步沒做完，下面每一步都不要做。**

**先看懂 VM 資料夾裡有什麼**（不認識檔案就無法判斷少了什麼）：

| 副檔名 | 內容 | 弄丟的後果 |
| --- | --- | --- |
| `.vmx` ★★★★★ | 主設定檔（文字檔，可手改） | VM 不見了，但磁碟還在，可以重建設定 |
| `.vmdk` ★★★★★ | 虛擬磁碟**描述檔** | 描述檔壞掉時資料片段還在，有機會重建 |
| `-s00N.vmdk` ★★★★★ | 分割磁碟的**實際資料片段** | ★★★★★ **少一片，整顆磁碟就讀不回來** |
| `-00000N.vmdk` ★★★★★ | 快照的差異磁碟 | 快照鏈斷掉，VM 開不起來 |
| `.vmsd` ★★★★ | 快照樹的中繼資料 | 快照關係亂掉 |
| `.vmsn` ★★★ | 快照狀態檔（勾記憶體時很大） | 該快照不可用 |
| `.nvram` ★★ | 虛擬 BIOS／UEFI 的 NVRAM | 開機順序等設定重置，可重建 |
| `.vmem` ★★ | 執行中 VM 的記憶體對應檔 | 正常關機後應該消失 |
| `.lck` **目錄** ★★★★★ | 執行中的鎖定目錄 | **正常關機後應該自己消失** |
| `.log` ★★★★★ | `vmware.log`，排錯必看 | 沒有它就很難查 |

**判斷分流**：

```text
訊息是「appears to be in use」／「Failed to lock」  → 走【1】（鎖檔）
訊息是「Cannot open the disk ...」                 → 走【2】（磁碟鏈）
刪快照刪到一半失敗                                  → 走【3】
連結複製的複本開不起來                              → 走【4】
```

【1】★★★★★ `.lck` 鎖檔殘留。

```text
This virtual machine appears to be in use.
   Take Ownership   /   Cancel
```

★★★★★ **按 `Take Ownership` 之前，先確認真的沒有別人開著它。**
`.lck` 的用途就是防止兩個 Workstation 同時寫同一顆磁碟 ——
**兩邊同時寫，磁碟一定壞。**

```text
① 這台 VM 有沒有在另一個 Workstation 視窗裡開著？
② 有沒有別人透過共享資料夾／網路磁碟也開著同一份？
③ 主機上還有沒有殘留的 vmware-vmx 程序？
   Windows: Get-Process vmware-vmx
   Linux  : pgrep -a vmware-vmx
```

三項都確認沒有，再按 `Take Ownership`。

> [!danger] ★★★★★ 手動刪除 `.lck` 目錄是最後手段
> 只有在下列條件**全部成立**時才可以做：
> 1. 已經把整個 VM 資料夾備份到另一顆碟
> 2. 所有 Workstation 視窗都已關閉
> 3. `vmware-vmx` 程序確定不存在
> 4. 確定沒有第二台電腦開著同一份檔案
>
> 條件不全就刪，等於允許兩個程序同時寫同一顆虛擬磁碟，**資料一定壞**。
> 做法是刪掉 VM 目錄下所有 `*.lck` **資料夾**（不是 `.vmdk`）。

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| `Failed to lock the file` ★★★★ | `.lck` 殘留，或防毒／備份軟體正鎖著檔案 | 先排除防毒掃描、停掉備份工作，再考慮刪 `.lck` |
| ★★★★ VM 放在 OneDrive／Dropbox 裡，偶爾就鎖住 | 同步軟體不斷開檔上傳 | **把整個 VM 資料夾搬出同步範圍**，並在同步軟體排除該路徑 |

【2】★★★★★ 磁碟鏈斷掉。

```text
Cannot open the disk 'lab-ubuntu-000003.vmdk' or one of the snapshot disks
it depends on.
```

★★★★★ **這句話的重點是「it depends on」—— 鏈上少了一環。**

```text
lab-ubuntu.vmdk           ← base
  └ lab-ubuntu-000001.vmdk
      └ lab-ubuntu-000002.vmdk      ← 這一片如果不在，整條鏈就斷了
          └ lab-ubuntu-000003.vmdk  ← 現在要開的是這一層
```

排查步驟：

```bash
ls -l ~/vmware/lab-ubuntu/*.vmdk
```

```text
① 所有 -00000N.vmdk 是不是都在同一個目錄裡？
     被搬走／被清理軟體刪掉 → 找回來放回原位
② 有沒有被改過名字？
     .vmdk 描述檔裡記著上一層的檔名，改名就斷
③ 分割磁碟的 -s00N.vmdk 有沒有缺片？
     ★★★★★ 缺一片就是整顆讀不回來，只能從備份還原
```

```bash
vmware-vdiskmanager -R /path/to/lab-ubuntu.vmdk    # 檢查／嘗試修復磁碟鏈
```

> [!danger] ★★★★★ 絕對不要「隨手刪掉看起來沒用的 .vmdk」
> `-000001.vmdk`、`-s003.vmdk` 這些看起來像暫存檔的東西，
> **每一個都是磁碟的一部分**。刪掉任何一個，整顆虛擬磁碟就報廢，
> 而且**沒有還原的方法**。
> 空間不夠時的正確做法是〈情境五〉的刪快照與壓縮流程，不是手動刪檔。

【3】★★★★★ 刪快照刪到一半失敗。

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 刪快照時 VM 卡住很久甚至看似當機 | delta 檔案很大，正在合併回 base | **不要強制關閉、不要斷電**，讓它跑完 |
| ★★★★★ 刪到一半失敗，VM 開不起來 | 合併過程被中斷，或主機空間不足 | 先清出主機空間；讀 `vmware.log` 找錯誤；嚴重時只能從備份還原 |

★★★★ 預防勝於救援：**不要讓快照鏈長成那樣**。
主機空間 < 20% 就先清空間，再談刪快照。

【4】★★★★★ 連結複製的複本開不起來 —— 見〈情境十〉【5】。
根因永遠是**來源 VM 被刪除、改名或搬移**。

【5】★★★★ 真的救不回來時：**還原備份。** 這時候你會發現一件事 ——

> [!danger] ★★★★★ 快照不是備份
> 快照與基礎磁碟**放在同一顆碟、同一個資料夾**。
> 主機硬碟壞掉，base 與所有快照一起沒。
>
> | 問題 | 快照 | 備份 |
> | --- | --- | --- |
> | 和原始資料分開存放？ | **否** | 是 |
> | 可以獨立還原？ | **否**（依賴基礎磁碟） | 是 |
> | 磁碟壞了救得回來？ | **不行** | 可以 |
> | 有版本與保留策略？ | 沒有 | 有 |
> | 適合長期保存？ | 不適合 | 適合 |
>
> ★★★★★ 重要的 VM 一定要**完整複製到另一顆碟或外部儲存**，
> 或 `File → Export to OVF` 匯出成可攜的一份。

**原理詳見**：
[[050-01-02-03-guide-Workstation-快照與複製]] 的〈快照不是備份〉與〈常見錯誤與排錯〉、
[[050-01-02-06-guide-Workstation-效能調校與疑難排解]] 的排錯總表與〈排錯的第一站永遠是 `vmware.log`〉。

---

## 跨篇判斷樹：不知道從哪查起的時候

★★★★★ 上面十二個情境都對不上，或症狀橫跨好幾篇時，走這棵樹。

```text
                    ┌─ 所有 VM 都有問題 ─→ 主機層
                    │      ├ 開不了任何 VM       → 情境一（Hypervisor / 模組 / BIOS）
   問題影響範圍 ────┤      ├ 全部都慢             → 情境六（資源 / 防毒 / 空間）
                    │      └ 全部沒網路           → 情境三【1】（VMware 服務）
                    │
                    └─ 只有一台有問題 ─→ 那台 VM 的層次
                           ├ 連 Power On 都不行   → 情境二【1】→ 情境十二
                           ├ 停在韌體畫面         → 情境二【2】
                           ├ 進得去但沒網路       → 情境三
                           ├ 有網路但服務連不進   → 情境四
                           ├ 進得去但很慢         → 情境六
                           ├ 進得去但時間錯       → 情境九
                           └ 進得去但共享看不到   → 情境八
```

★★★★ **第二個好用的切法：問「最近改了什麼」。**

| 最近做了什麼 | 最可能踩到的情境 |
| --- | --- |
| 主機裝了 Docker Desktop／開了 WSL2 ★★★★★ | 情境一（Hyper-V 層被拉起來） |
| 主機更新了 BIOS ★★★★ | 情境一【5】（VT-x 被重設回停用） |
| 主機升級了核心（Linux）★★★★ | 情境一【4】（模組要重編＋重簽章） |
| 升級了 Workstation 大版本 ★★★★ | 情境十一 |
| 複製了一台 VM ★★★★★ | 情境十（四項識別碼） |
| 拍了幾個快照做實驗 ★★★★★ | 情境五、情境六（空間與效能） |
| 還原了快照 ★★★★★ | 情境九（時間跳回過去） |
| 改了網路模式 ★★★★★ | 情境三（閘道 `.2`、Bridged 三坑） |
| 在 VM 裡裝了 PVE／KVM ★★★★ | 情境七 |
| 把 VM 搬到別的資料夾 ★★★★★ | 情境十二（連結複製與磁碟鏈） |
| 主機睡眠又喚醒 ★★★★ | 情境九、情境三【1】（網路服務異常） |

---

## 什麼時候該停手：不可逆操作清單

★★★★★ **下面每一項都是「做了就回不去」。** 動手之前先確認你有備份。

| 操作 | 為什麼不可逆 | 動手前必須先做 |
| --- | --- | --- |
| ★★★★★ 刪除快照 / Delete All Snapshots | 差異磁碟合併回 base，還原點永久消失 | 確認不再需要；必要的還原點改用**完整複製**保存 |
| ★★★★★ 回復快照（Go To / Revert） | 丟掉快照之後的**所有改動** | **先對現在的狀態 Take Snapshot** |
| ★★★★★ 刪除 `.lck` 目錄 | 允許兩個程序同時寫同一顆磁碟 → 資料壞 | 備份整個資料夾；確認沒有任何 `vmware-vmx` 在跑 |
| ★★★★★ 手動刪除 `-00000N.vmdk` / `-s00N.vmdk` | 整顆虛擬磁碟報廢，**無法還原** | ★★★★★ **不要做。** 空間不夠走情境五 |
| ★★★★★ `VM → Manage → Delete from Disk` | 檔案真的被刪掉 | 確認選的是複本不是範本 |
| ★★★★ 升級虛擬硬體相容性 | 不能降回舊版，舊版 Workstation 打不開 | 完整複製整個 VM 目錄 |
| ★★★★ 磁碟壓縮 `vmware-vdiskmanager -k` | 異常中斷可能損壞 `.vmdk` | 壓縮前完整複製整個 VM 目錄 |
| ★★★★ 改韌體型別（UEFI ⇄ BIOS） | 開機載入器對不上，系統開不起來 | 記下原本是哪一個，改錯就改回去 |
| ★★★★★ 對執行中的 VM 按 Abort／強制關閉電源 | 等同硬斷電，Guest 檔案系統可能損壞 | 先清空間再 Retry；刪快照時讓它跑完 |
| ★★★★★ 關閉主機的 Device/Credential Guard | 降低主機的憑證保護 | ★★★★★ **機關電腦先問資安單位**，或改申請專用實驗主機 |
| ★★★ 關閉主機 Secure Boot | 降低主機開機鏈完整性 | 優先用 MOK 簽章而不是關掉它 |

> [!danger] ★★★★★ 三個「先停手，去問人」的時機
> 1. **這台 VM 裡有你不確定能不能重建的東西** → 先複製整個資料夾，再想下一步
> 2. **要關的是機關電腦的資安機制**（Credential Guard、Secure Boot、防毒排除）
>    → 找資安單位，不要自己繞過
> 3. **主機是共用的，上面還有別人的 VM** → 任何會重開機、關服務、關 Hyper-V 的動作，
>    先通知其他使用者

---

## 症狀 → 章節索引表

★★★★★ 這張表是反向查詢：**知道要學什麼原理，但不知道在哪一篇。**

| 主題 | 到哪一篇 | 看哪一節 |
| --- | --- | --- |
| Hyper-V／WSL2／VBS 衝突 ★★★★★ | [[050-01-02-01-svc-Workstation-安裝與授權]] | 〈與 Hyper-V／WSL2 共存〉 |
| Pro 與 Player 的差別（沒有快照與複製）★★★★ | [[050-01-02-01-svc-Workstation-安裝與授權]] | 〈Workstation 產品線〉 |
| Linux 主機核心模組與 Secure Boot ★★★★ | [[050-01-02-01-svc-Workstation-安裝與授權]] | 〈Linux 主機：安裝步驟〉 |
| VMware 服務名稱與重要檔案路徑 ★★★★ | [[050-01-02-01-svc-Workstation-安裝與授權]] | 〈速查表〉 |
| 升級大版本與乾淨移除 ★★★ | [[050-01-02-01-svc-Workstation-安裝與授權]] | 〈升級到新的大版本〉 |
| CPU／記憶體／磁碟該給多少 ★★★★ | [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] | 〈硬體配置：該給多少〉 |
| 動態成長 vs 預先配置、單檔 vs 分割 ★★★★ | [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] | 〈虛擬磁碟：兩組互相獨立的選擇〉 |
| UEFI／BIOS 選錯的後果 ★★★★★ | [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] | 〈UEFI 還是 BIOS〉 |
| 擴充磁碟的兩層流程 ★★★★ | [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] | 〈擴充磁碟的完整兩層流程〉 |
| VM 資料夾裡各種副檔名 ★★★★ | [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] | 〈虛擬機資料夾內的檔案〉 |
| `vmrun` 命令列操作 ★★★ | [[050-01-02-02-guide-Workstation-建立虛擬機與作業系統安裝]] | 〈從命令列操作 VM〉 |
| 快照的差異磁碟原理與效能代價 ★★★★ | [[050-01-02-03-guide-Workstation-快照與複製]] | 〈快照到底做了什麼〉 |
| ★★★★★ 快照不是備份 | [[050-01-02-03-guide-Workstation-快照與複製]] | 〈快照不是備份〉 |
| 快照鏈太長的後果與清理時機 ★★★★ | [[050-01-02-03-guide-Workstation-快照與複製]] | 〈快照鏈太長的後果與清理時機〉 |
| 連結複製 vs 完整複製 ★★★★★ | [[050-01-02-03-guide-Workstation-快照與複製]] | 〈複製：連結複製 vs 完整複製〉 |
| 複製後必改的四樣東西 ★★★★★ | [[050-01-02-03-guide-Workstation-快照與複製]] | 〈複製後一定要改的四樣東西〉 |
| AutoProtect 自動快照 ★★★ | [[050-01-02-03-guide-Workstation-快照與複製]] | 〈AutoProtect：自動快照〉 |
| 匯出 OVF ★★★ | [[050-01-02-03-guide-Workstation-快照與複製]] | 〈匯出成 OVF〉 |
| 四種網路模式與 VMnet 編號 ★★★★★ | [[050-01-02-04-guide-Workstation-網路模式]] | 〈一〜五〉 |
| ★★★★★ 可達性矩陣 | [[050-01-02-04-guide-Workstation-網路模式]] | 〈可達性矩陣〉 |
| 哪個實驗該用哪個模式 ★★★★★ | [[050-01-02-04-guide-Workstation-網路模式]] | 〈本手冊各章實驗環境該選哪一種〉 |
| NAT 網段三個固定位址（`.1` / `.2` / `.254`）★★★★★ | [[050-01-02-04-guide-Workstation-網路模式]] | 〈查出目前的 NAT 網段是什麼〉 |
| NAT 埠轉發 ★★★★★ | [[050-01-02-04-guide-Workstation-網路模式]] | 〈NAT 埠轉發〉 |
| 一台 VM 掛多張網卡做路由器 ★★★★ | [[050-01-02-04-guide-Workstation-網路模式]] | 〈一台 VM 掛多張網路卡〉 |
| 直接編輯 `.vmx` 的網路參數 ★★★ | [[050-01-02-04-guide-Workstation-網路模式]] | 〈直接編輯 `.vmx` 檔〉 |
| VMware Tools vs open-vm-tools ★★★★★ | [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] | 〈VMware Tools 與 open-vm-tools 的差別〉 |
| Tools 沒裝好的症狀對照表 ★★★★ | [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] | 〈Tools 沒裝好的症狀對照表〉 |
| HGFS 原理與 `/mnt/hgfs` ★★★★★ | [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] | 〈HGFS：共享資料夾到底怎麼運作〉 |
| `vmware-toolbox-cmd` 診斷 ★★★★ | [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] | 〈`vmware-toolbox-cmd`〉 |
| ★★★★★ 時間同步的坑（六個 `.vmx` 參數） | [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] | 〈時間同步的坑〉 |
| 剪貼簿、拖放、自動調整解析度 ★★★ | [[050-01-02-05-guide-Workstation-共享資料夾與VMwareTools]] | 〈進階應用〉 |
| ★★★★★ 資源是從主機挖走的 | [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] | 〈第一原則〉 |
| vCPU 超配與 CPU 配置準則 ★★★★★ | [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] | 〈CPU 配置準則〉 |
| 記憶體配置與主機保留 ★★★★★ | [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] | 〈記憶體配置準則〉 |
| ★★★★★ 巢狀虛擬化（開啟與五項驗證） | [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] | 〈巢狀虛擬化〉 |
| 磁碟膨脹與壓縮（先歸零再壓縮）★★★★★ | [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] | 〈磁碟膨脹與壓縮〉 |
| ★★★★★ 27 列排錯總表 | [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] | 〈常見錯誤與排錯〉 |
| 該拔掉哪些虛擬裝置 ★★★ | [[050-01-02-06-guide-Workstation-效能調校與疑難排解]] | 〈關掉不需要的虛擬裝置〉 |
| Linux Guest 本身的故障（開機、fstab、權限）★★★★ | [[020-01-98-trouble-Linux-常見故障排除]] | 全篇 |
| chrony／NTP 設定細節 ★★★★ | [[020-01-28-cmd-Linux-時間同步NTP與chrony]] | 全篇 |
| Guest 內的網路診斷指令 ★★★★ | [[020-01-16-cmd-Linux-網路基礎指令]] | 全篇 |
| Guest 內的分割區與掛載 ★★★★ | [[020-01-15-cmd-Linux-磁碟分割與掛載]] | 全篇 |

---

## 延伸閱讀

- 本章索引：[[050-01-02-00-idx-Workstation-VMware-Workstation]]
- 本章總複習（100 題）：[[050-01-02-99-exam-Workstation-總結小考]]
- 為什麼選 Workstation 而不是別的平台：[[050-01-01-01-guide-虛擬化-虛擬化概念與選型]]
- 巢狀環境的下一站（在 VM 裡跑 PVE）：[[050-01-03-07-svc-PVE-叢集與高可用]]
- Guest 是 Linux 時的完整排錯手冊：[[020-01-98-trouble-Linux-常見故障排除]]
- Guest 開機救援（GRUB / emergency mode）：[[020-01-25-guide-Linux-開機流程與GRUB救援]]
