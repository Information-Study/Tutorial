---
title: "Proxmox VE 常見故障排除"
desc: "依症狀查的 PVE 故障排除總索引：分流表、急救卡與 12 篇未涵蓋情境的完整排查"
aliases: [PVE故障排除, PVE排錯手冊]
tags: [群組/虛擬機與容器, 主題/故障排除]
category: Proxmox VE
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: []
updated: 2026-09-02
---

# Proxmox VE 常見故障排除

> [!warning] 未實機驗證
> 本篇以 **PVE 8**（Debian 12 bookworm 基底）為例撰寫。指令、路徑、套件名稱與
> 錯誤訊息在不同小版本之間可能有差異，正式環境動手前請先以 `pveversion -v`
> 確認自己的版本，並對照官方文件。所有**不可逆操作**都請先做備份與快照。

> [!abstract] 這份手冊在整章的位置 ★★★★★
> 本章一共 13 篇教學文，故障排除拆成**兩層**，不要搞混：
>
> | | [[050-01-03-12-guide-PVE-故障排除]] | 本篇（98-trouble） |
> | --- | --- | --- |
> | 定位 | **服務與叢集層的深度排查** | **全章的上層總索引** |
> | 內容 | 六層分層模型、`pve-triage.sh` 檢傷腳本、症狀 A～I 的完整分支 | 分流表＋12 篇**沒涵蓋**的十個情境 |
> | 什麼時候看 | 已經知道是「主機／後台／儲存／叢集／遷移／VM／LXC／備份／憑證」出事 | **還不知道問題屬於哪一類**，或問題出在規劃、安裝、設定當下 |
>
> ★★★★★ 用法：**先看本篇的「總分流表」對症狀**。表格會告訴你
> 「去 12 篇的症狀 X」或「留在本篇的情境 N」，不要兩邊亂翻。
>
> ★★★★★ 本手冊**不重講原理**。每個情境結尾的「原理詳見」就是原文入口。

## 黃金 60 秒急救卡

> [!danger] ★★★★★ 出事的前 60 秒，只做三件事：**看、記、不要動**
> ① 先跑下面三個指令，把輸出**貼進工單或存成檔案**；
> ② 確認「服務還活著嗎」而不是「為什麼壞掉」；
> ③ 在還沒看懂之前，**不要 restart、不要 reboot、不要刪東西**。
> 重開機會把記憶體狀態、執行中的任務、以及一半的錯誤日誌一起帶走。

★★★★★ 三個指令，順序不要換：

```bash
# ① 這台機器的服務層還在嗎（PVE 的六個核心服務）
$ systemctl is-active pve-cluster corosync pveproxy pvedaemon pvestatd pvescheduler
active
active
active
active
active
active
#   任何一項不是 active → 直接去 [[050-01-03-12-guide-PVE-故障排除]] 症狀 B

# ② 設定檔系統寫得進去嗎（/etc/pve 唯讀 = 幾乎什麼都做不了）
$ pvecm status 2>/dev/null | grep -E 'Quorate|Expected|Total votes' ; touch /etc/pve/.rwtest && rm -f /etc/pve/.rwtest && echo "/etc/pve 可寫"
Expected votes:   3
Total votes:      3
Quorate:          Yes
/etc/pve 可寫
#   Quorate: No 或 touch 失敗 → 12 篇症狀 D（★★★★★ 不要自己下 pvecm expected）
#   單機沒有叢集時 pvecm status 會沒有輸出，只要 touch 成功就正常

# ③ 空間與磁碟還有沒有餘裕（PVE 最常見的死因）
$ df -h / /var/lib/vz 2>/dev/null | grep -v tmpfs ; lvs -o lv_name,data_percent,metadata_percent 2>/dev/null ; zpool list 2>/dev/null
Filesystem            Size  Used Avail Use% Mounted on
/dev/mapper/pve-root   94G   88G  1.2G  99% /             # ★★★★★ 就是它
  LV   Data%  Meta%
  data 97.42  81.05                                        # ★★★★★ thin pool 快滿
#   / 超過 90%、Data% 或 Meta% 超過 85% → 12 篇症狀 C
```

★★★★ 這三步跑完，你會落在三種狀況之一：

```text
三項都正常，但使用者說某台 VM／CT 有問題
  → 問題在來賓層，不是主機層。看本篇情境三（效能）／情境四（cloud-init）／情境五（LXC）

有一項不正常，而且症狀在 12 篇的 A～I 清單裡
  → 去 [[050-01-03-12-guide-PVE-故障排除]]，本篇不重複

問題發生在「我剛剛做了某件事之後」
  → 幾乎一定在本篇。往下看「總分流表」的第二段（依你剛做的事查）
```

> [!tip] ★★★★★ 一句話判斷「該不該現在動手」
> 問自己：**「服務還在跑嗎？」**
> 跑得動 → 你有時間慢慢查，先蒐證再處置。
> 跑不動 → 先恢復服務（可以是繞道、可以是還原備份），根因**事後**再查。
> ★★★★★ 恢復優先於查根因，但**蒐證優先於恢復** —— 先把現況存成檔案再動手。

★★★★ 蒐證一行版（花 10 秒，救你事後半天）：

```bash
$ { date; pveversion -v; systemctl --failed --no-pager; pvecm status; pvesm status; \
    qm list; pct list; df -h; lvs -a; zpool status 2>/dev/null; \
    journalctl -p err -b --no-pager | tail -100; } > /root/pve-incident-$(date +%F-%H%M).txt 2>&1
$ ls -lh /root/pve-incident-*.txt
-rw-r--r-- 1 root root 18K Sep  2 09:14 /root/pve-incident-2026-09-02-0914.txt
```

★★★★ 更完整的檢傷請用 12 篇的 `pve-triage.sh`（[[050-01-03-12-guide-PVE-故障排除]]
「通用第一輪檢查」一節），那份把六層都掃過一遍。

## 總分流表

### 第一段：依「你看到的症狀」查 ★★★★★

★★★★★ 這張表涵蓋全章 13 篇。**代號 A～I 是 12 篇的症狀編號**，指過去就對了，
本篇不重複那些內容；寫「情境 N」的才留在本篇往下展開。

| 症狀（你會看到的） | 最可能的原因 | 先下這個指令 | 去哪裡 |
| --- | --- | --- | --- |
| ★★★★★ 主機開不了機、停在 GRUB／emergency mode | 開機鏈斷在某一階段 | IPMI 主控台看畫面 | 12 篇 **症狀 A** |
| ★★★★★ 8006 後台連不上，但 VM 都還在跑 | pveproxy 或防火牆 | `systemctl status pveproxy` | 12 篇 **症狀 B** |
| ★★★★★ 儲存滿了、VM 集體變唯讀 | 根分割、thin pool、ZFS pool | `df -h /; lvs` | 12 篇 **症狀 C** |
| ★★★★★ `/etc/pve` 唯讀，什麼設定都改不了 | 失去 Quorum 或 pmxcfs 掛了 | `pvecm status` | 12 篇 **症狀 D** |
| ★★★★ 遷移失敗、卡住不動 | SSH、儲存不同名、CPU 不相容 | 看遷移任務的原文錯誤 | 12 篇 **症狀 E** |
| ★★★★ VM 按 Start 起不來 | 磁碟不見、參數不支援 | `qm start <id>` | 12 篇 **症狀 F** |
| ★★★★ LXC 起不來、`job failed with error -1` | mount／idmap／features | `pct start <id> --debug` | 12 篇 **症狀 G** |
| ★★★★ 排程備份失敗或卡住 | 空間、鎖、fsfreeze | `tail /var/log/vzdump/*.log` | 12 篇 **症狀 H** |
| ★★★★ 憑證過期、瀏覽器擋住、節點間 API 憑證錯 | pveproxy-ssl／叢集 CA | `pvenode cert info` | 12 篇 **症狀 I** |
| ★★★★★ **ISO 開不起來、安裝程式黑屏或找不到磁碟** | 開機媒體、顯示驅動、控制器 | `dmesg \| tail`（安裝環境按 `Ctrl+Alt+F3`） | **情境一** |
| ★★★★★ **安裝完 `apt update` 全部 401，什麼都更新不了** | 企業版套件庫沒切成 no-subscription | `grep -r . /etc/apt/sources.list.d/` | **情境一【6】** |
| ★★★★★ **巢狀環境裡 VM 一開就 `failed to initialize kvm`** | VT-x／AMD-V 沒往下傳 | `grep -cE 'vmx\|svm' /proc/cpuinfo` | **情境一【3】** |
| ★★★★ **`local` 一直爆滿、ISO 與備份塞在根分割** | 儲存規劃時沒收 `content` | `du -sh /var/lib/vz/*` | **情境二【1】** |
| ★★★★★ **thin pool 的 `Meta%` 先滿（Data% 還很低）** | 中繼資料區太小，快照太多 | `lvs -o +metadata_percent` | **情境二【2】** |
| ★★★★ **NFS 加不進來，或加進來就整個後台變慢** | export／防火牆／hard mount 卡死 | `pvesm scan nfs <ip>` | **情境二【3】** |
| ★★★★ **iSCSI 時斷時續，VM 偶發 I/O error** | session 斷線與 timeout 設定 | `iscsiadm -m session` | **情境二【4】** |
| ★★★★ **裝了 ZFS 之後記憶體幾乎被吃光** | ARC 沒設上限 | `arc_summary \| head -20` | **情境二【5】** |
| ★★★★ **VM 磁碟／網路慢到不像話** | 沒用 VirtIO、cache／aio 選錯 | `qm config <id>` | **情境三** |
| ★★★★ **VM 遷過去就當、或加密效能很差** | CPU type 選錯 | `qm config <id> \| grep cpu` | **情境三【2】** |
| ★★★★ **主機斷電後 guest 檔案系統毀損** | `cache=unsafe` | `grep -rn 'cache=unsafe' /etc/pve/` | **情境三【3】** |
| ★★★★ **資料庫 VM 週期性卡頓、guest 內狂 swap** | balloon 抽走記憶體 | `qm config <id> \| grep balloon` | **情境三【5】** |
| ★★★★ **cloud-init 設定完全沒生效** | ci 磁碟沒加、只跑第一次開機 | `qm cloudinit dump <id> user` | **情境四** |
| ★★★★ **複製出來的機器 IP 互搶、SSH 指紋一樣** | 範本沒清 machine-id 與 host key | `cat /etc/machine-id` | **情境四【4】** |
| ★★★★ **`--cicustom` 之後 `--ciuser` 失效** | 自訂 user-data 是整份取代 | `qm config <id> \| grep cicustom` | **情境四【3】** |
| ★★★★ **非特權容器裡檔案全是 `nobody:nogroup`** | UID 位移 100000 | `pct config <id> \| grep unprivileged` | **情境五【1】** |
| ★★★★ **bind mount 掛進去卻寫不了** | 主機端擁有者不在對應範圍 | `ls -ln <主機來源目錄>` | **情境五【2】** |
| ★★★★ **LXC 裡的 Docker 起不來** | `nesting` 沒開／overlay2 不支援 | `pct config <id> \| grep features` | **情境五【3】** |
| ★★★★ **`pveam download` 抓不到範本** | 清單過舊或對外不通 | `pveam update` | **情境五【4】** |
| ★★★★★ **改完網路 `ifreload -a` 就斷線，SSH 進不去** | bridge／VLAN／bond 打錯 | 從 IPMI 主控台進去 | **情境六** |
| ★★★★ **VM 設了 `tag=` 完全不通** | `bridge-vlan-aware` 沒開 | `bridge vlan show` | **情境六【3】** |
| ★★★★ **bond 起來了但時通時不通** | 兩端模式不一致 | `cat /proc/net/bonding/bond0` | **情境六【4】** |
| ★★★★★ **IOMMU 群組是空的、直通參數沒生效** | BIOS 沒開或改錯開機設定檔 | `ls /sys/kernel/iommu_groups/` | **情境七【1】** |
| ★★★★★ **`group N is not viable`** | 同群組還有裝置沒綁 vfio | `lspci -nnk` | **情境七【3】** |
| ★★★★★ **直通完 VM 起不來、或主機主控台變黑** | driver 沒換、framebuffer 佔用 | `dmesg \| grep -i vfio` | **情境七【4】** |
| ★★★★★ **直通後才發現不能遷移、HA 切不過去** | 有 `hostpci` 就綁死在該節點 | `qm config <id> \| grep hostpci` | **情境七【6】** |
| ★★★★★ **升級完主機失聯／進不了系統／服務起不來** | 設定檔被覆蓋、核心不合 | 從 IPMI 進去 | **情境八** |
| ★★★★★ **`pveversion -v` 版本混雜、一半新一半舊** | 升級中斷或套件庫只改一半 | `pveversion -v` | **情境八【3】** |
| ★★★★ **想退回舊版卻退不了** | Debian 系不支援降級 | `proxmox-boot-tool kernel list` | **情境八【5】** |
| ★★★★ **備份空間不足／被鎖住／還原到錯的 VMID** | 保留策略、殘留鎖、VMID 撞號 | `qm unlock`／`pvesm status` | **情境九** |
| ★★★★★ **要救援時才發現備份根本還原不了** | 從來沒做過還原演練 | 現在就排一次演練 | **情境九【5】** |
| ★★★ **練習機把實體機資源吃光、快照鏈爆掉** | 沒設 `--onboot 0`、快照沒清 | `qm listsnapshot <id>` | **情境十** |
| ★★★ **實驗做完沒清乾淨，下次一開機全部自動啟動** | 沒有清理腳本與命名規則 | `qm list \| wc -l` | **情境十【3】** |

### 第二段：依「你剛剛做了什麼」查 ★★★★★

★★★★★ 這一段的命中率往往比症狀表更高 —— **九成的 PVE 故障，發生在「有人剛改過什麼」之後**。

| 我剛剛做了…… | 最容易踩到的坑 | 去哪裡 |
| --- | --- | --- |
| ★★★★★ 剛裝好 PVE、第一次 `apt update` | 企業版套件庫 401 | **情境一【6】** |
| ★★★★★ 剛在 VMware Workstation／巢狀環境裡裝 PVE | VT-x 沒往下傳、`pveperf` 極慢 | **情境一【3】** |
| ★★★★ 剛加了一個新儲存 | content 類型沒勾、shared 設錯 | **情境二【3】** |
| ★★★★ 剛匯入一批 ISO 或第一次跑備份 | `local` 在根分割，很快就滿 | **情境二【1】** |
| ★★★★ 剛建好一台 VM，覺得很慢 | 沒用 VirtIO、cache 預設值 | **情境三【1】** |
| ★★★★ 剛做完範本、開始大量複製 | machine-id／host key／cloud-init | **情境四** |
| ★★★★ 剛把 LXC 掛上主機目錄 | UID 對應與權限 | **情境五【1】【2】** |
| ★★★★★ 剛改過 `/etc/network/interfaces` | 一按下去就把自己鎖在外面 | **情境六** |
| ★★★★★ 剛開了 IOMMU、插了顯示卡 | 群組、vfio 綁定、主控台變黑 | **情境七** |
| ★★★★★ 剛跑完 `apt dist-upgrade` 並重開機 | 設定檔覆蓋、核心不合、憑證 | **情境八** |
| ★★★★ 剛改了備份保留策略或換了備份目標 | 空間、鎖、通知沒設 | **情境九** |
| ★★★★★ 剛把節點加進叢集 | `/etc/pve` 被取代，儲存與使用者不見了 | 12 篇 **症狀 D**、[[050-01-03-07-svc-PVE-叢集與高可用]] |
| ★★★★ 剛改了使用者權限或建了 API Token | `privsep` 沒授權、Token 格式 | [[050-01-03-08-guide-PVE-使用者權限與API]] |
| ★★★ 剛清理完實驗環境 | 刪錯機器、快照沒清 | **情境十【3】** |

## 依情境展開

★★★★★ 以下十個情境，都是 [[050-01-03-12-guide-PVE-故障排除]] **沒有涵蓋**的部分 ——
它處理的是「跑起來之後壞掉」，本篇處理的是「還沒跑起來」與「規劃當下就錯了」。

### ★★★★★ 情境一：安裝階段就過不去

**現象**：五種都算「還沒裝好就卡住」，處理方向完全不同。

```text
（A）從 USB 開機顯示 No bootable device / Missing operating system
（B）安裝精靈跑到 Detecting hardware 之後黑屏、花屏或整個凍住
（C）安裝精靈的 Target Harddisk 下拉是空的，一顆磁碟都沒有
（D）安裝完拔掉 USB 重開機，又跑回安裝精靈，或停在 GRUB 找不到系統
（E）裝好了、後台也進得去，但 apt update 全部 401 Unauthorized
```

**判斷分流**：

```text
連 GRUB 選單都沒出現              →【1】開機媒體或韌體設定
出現選單、選了之後畫面壞掉        →【2】改用 Terminal UI 或 nomodeset
選單正常但看不到磁碟              →【4】控制器模式或 RAID 卡
在巢狀環境（Workstation/PVE-in-PVE）→【3】先確認 VT-x 有沒有往下傳
裝完開機又跑回安裝程式            →【5】開機順序與開機項目
裝完 apt 全紅                     →【6】套件庫切換（★★★★★ 最常見）
```

**可能原因**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `No bootable device` / USB 開不起來 | ISO 用「檔案複製」方式寫入，不是 raw/DD 模式 | Rufus 選 **DD Image mode**、或用 balenaEtcher、或 Linux 下 `dd` 重寫 |
| ★★★★ 開機選單有，但選 UEFI 開不了、Legacy 才行 | ISO 寫入方式或韌體的 Secure Boot | 韌體關掉 Secure Boot 再試（PVE 8 支援 Secure Boot，但寫入方式錯一樣開不了） |
| ★★★★ `Detecting hardware` 後黑屏／花屏 | 圖形安裝程式與顯示卡驅動不合 | 回選單改用 **`Install Proxmox VE (Terminal UI)`**，選項完全相同 |
| ★★★★ Terminal UI 也黑屏 | KMS 驅動問題 | 在該選單項按 `e`，於 `linux` 那行尾端加 `nomodeset`，按 `Ctrl+X` 開機 |
| ★★★★★ 巢狀環境按 Start 就 `failed to initialize kvm: Operation not permitted` | 上層沒把 VT-x／AMD-V 傳給這台 VM | Workstation：關機 → `Processors` → 勾 `Virtualize Intel VT-x/EPT`；PVE-in-PVE：外層 VM 的 `cpu` 設 `host` |
| ★★★★★ 實體機 `/proc/cpuinfo` 沒有 `vmx`／`svm` | BIOS 沒開虛擬化 | 進 BIOS 開 `Intel VT-x` / `SVM Mode`，**存檔後完整斷電再開**（有些機種熱重開不生效） |
| ★★★★ Target Harddisk 是空的 | 控制器在 RAID 模式、或需要廠商驅動 | BIOS 把 SATA/NVMe 控制器改成 **AHCI**；硬體 RAID 卡要先在卡的 BIOS 建好邏輯磁碟 |
| ★★★★ 只看得到 USB 碟，看不到內建 SSD | NVMe 被 RAID/VMD 模式藏起來（部分 Intel 平台） | BIOS 關閉 **Intel VMD / RST**（★★★★ 這會讓已安裝的 Windows 開不了機，先確認機器要不要保留） |
| ★★★★ 安裝完重開又進安裝精靈 | 安裝媒體還掛著且開機順序在硬碟前面 | 拔 USB／取消勾選虛擬光碟的 `Connected`；BIOS 調開機順序 |
| ★★★★ 拔了 USB 卻停在 `no such device` / GRUB rescue | UEFI 開機項目沒建好，或裝到了錯的磁碟 | 進 BIOS 手動加開機項目指向 `\EFI\proxmox\grubx64.efi`；不確定就重裝並只接目標磁碟 |
| ★★★★★ `apt update` 全部 `401 Unauthorized` | 預設啟用企業版套件庫但沒有訂閱 | 停用 enterprise、加上 no-subscription，見【6】 |
| ★★★ Hostname 欄位一直被拒絕 | PVE 要求 FQDN | 填 `pve01.lab.local` 這種**至少有一個點**的完整名稱 |
| ★★★ 安裝時設的 IP 打錯，裝完連不上 | 網路設定寫進 `/etc/network/interfaces` 與 `/etc/hosts` 兩個地方 | 從主控台**兩個檔案一起改**，見情境六【5】 |

**處置步驟**：

【1】★★★★ 開機媒體：先分辨「韌體沒認到 USB」還是「認到了但開不起來」。

```text
BIOS 開機選單（F11／F12／Esc，視廠牌）裡：
  完全看不到 USB 裝置        → 換一個 USB 埠（優先用主機板後方的 USB 2.0）、換一支碟
  看得到但選了跳回 BIOS      → ★★★★★ 九成是寫入方式錯，重寫一次 ISO
  看得到、選了顯示 No bootable device → 同上
```

★★★★ 在 Linux 下重寫（★★★★★ `of=` 一定要指向**整顆碟**而不是分割區）：

```bash
$ lsblk -o NAME,SIZE,MODEL,TRAN | grep -i usb
sdc    28.9G SanDisk Ultra   usb                 # ★★★★★ 確認到型號這一層再往下
$ sudo dd if=proxmox-ve_8.x.iso of=/dev/sdc bs=4M status=progress oflag=direct
1476395008 bytes (1.5 GB, 1.4 GiB) copied, 42 s, 35.2 MB/s
$ sync
```

> [!danger] ★★★★★ `dd` 打錯目標就是整顆磁碟消失
> `of=/dev/sda` 而不是 `/dev/sdc`，你會在三秒內毀掉一顆有資料的硬碟，而且**沒有復原路徑**。
> 動手前一律 `lsblk -o NAME,SIZE,MODEL,SERIAL,TRAN` 對到型號與序號，
> 並且**只在確認 `TRAN` 是 `usb` 的裝置上動手**。

【2】★★★★ 安裝精靈畫面壞掉：不要硬拚圖形介面。

```text
GRUB 選單（安裝媒體開機後的第一個畫面）：
  Install Proxmox VE (Graphical)     ← 預設，畫面壞掉就別用
  Install Proxmox VE (Terminal UI)   ← ★★★★★ 選這個，選項一模一樣
  Advanced Options                   ← 裡面有 debug 模式，可在各階段掉進 shell
```

還是黑屏就手動加核心參數：在該選單項按 `e`，找到 `linux ...` 開頭那一行，
在**行尾**加上 `nomodeset`，按 `Ctrl+X` 開機。

★★★ 安裝過程中要看底層訊息，按 `Ctrl+Alt+F3` 切到第三個虛擬終端：

```bash
# 在安裝環境的 tty3
$ dmesg | tail -30
$ lsblk
$ lspci -nnk | grep -A3 -i 'sata\|raid\|nvme'
```

【3】★★★★★ 巢狀環境：**先證明 KVM 真的可用**，再談別的。

```bash
# 在 PVE 主機上
$ grep -cE 'vmx|svm' /proc/cpuinfo
16                                    # ★★★★★ 大於 0 才代表 CPU 虛擬化旗標有傳進來
$ ls -l /dev/kvm
crw-rw---- 1 root kvm 10, 232 Sep  2 08:10 /dev/kvm
$ systemctl status kvm 2>/dev/null; lsmod | grep -E '^kvm'
kvm_intel             380928  0
kvm                  1146880  1 kvm_intel
```

分支判定：

```text
grep -c 結果是 0
  → 上層沒把虛擬化旗標傳下來。回到上層平台處理：
      VMware Workstation：VM 關機 → 設定 → Processors → 勾 Virtualize Intel VT-x/EPT
      外層是 PVE：qm set <外層VMID> --cpu host（★★★★ 要完全關機再開，reboot 沒用）
      實體機：進 BIOS 開 VT-x / SVM，存檔後完整斷電再上電
/dev/kvm 不存在但 grep 有數字
  → 模組沒載：modprobe kvm_intel（或 kvm_amd），看 dmesg 有沒有拒絕原因
kvm_intel 載不起來，dmesg 說 disabled by bios
  → ★★★★★ BIOS 真的沒開，不是作業系統的問題
```

★★★★ 巢狀環境**慢是正常的**，不要拿它跟實體機比。三層巢狀（實體 → Workstation → PVE → VM）
的磁碟同步寫入會被層層放大，`pveperf` 的 `FSYNCS/SECOND` 掉到兩位數屬預期，
只能拿來「跟自己昨天比」。詳見 [[050-01-03-13-guide-PVE-建立練習環境]]。

【4】★★★★ 看不到磁碟：分成「核心沒認到」與「認到了但安裝程式不給選」。

```bash
# 安裝環境 tty3
$ lsblk
NAME   MAJ:MIN RM   SIZE RO TYPE MOUNTPOINTS
sda      8:0    0 447.1G  0 disk                # 認到了 → 是安裝程式的問題
$ lspci -nnk | grep -iA3 'raid\|sata\|non-volatile'
00:17.0 SATA controller [0106]: Intel Corporation ... [8086:a352]
        Kernel driver in use: ahci                # ★★★★ 有 driver in use 才算認到
```

```text
lsblk 什麼都沒有，lspci 有控制器但沒有 Kernel driver in use
  → ★★★★★ 缺驅動。BIOS 把控制器改成 AHCI；硬體 RAID 卡先在卡的 BIOS 建好邏輯磁碟
lsblk 看得到，但安裝程式的下拉還是空的
  → ★★★ 該磁碟太小（PVE 需要數十 GB 以上），或上面有安裝程式無法處理的殘留簽章
     tty3 下 wipefs -a /dev/sdX 清掉簽章再回安裝程式（★★★★★ 確認這顆沒有要保留的資料）
只看得到 USB、看不到 NVMe
  → BIOS 的 Intel VMD / RST 打開了，改成 AHCI/NVMe 直通模式
```

> [!danger] ★★★★★ `wipefs -a`、`sgdisk --zap-all` 都是不可逆的
> 這兩個指令會清掉分割表與檔案系統簽章，上面的資料**不會有任何提示就消失**。
> 在安裝環境裡 `/dev/sda` 的編號跟你平常看到的**不一定一樣**，
> 一律用 `lsblk -o NAME,SIZE,MODEL,SERIAL` 對到序號那一層再動手。

【5】★★★★ 裝完開不了機：先確認「裝到哪一顆」。

```bash
# 用安裝媒體開機 → Advanced Options → 進 rescue/debug shell
$ lsblk -f
NAME        FSTYPE      LABEL FSVER    UUID                                 MOUNTPOINTS
sda
├─sda1                                                                       # BIOS boot
├─sda2      vfat              FAT32    1234-5678                             # EFI
└─sda3      LVM2_member       LVM2 001 xxxx-xxxx-xxxx
  ├─pve-root ext4                      9f3c2b41-...
  └─pve-data lvm2
$ efibootmgr -v
BootCurrent: 0002
BootOrder: 0002,0000
Boot0000* proxmox   HD(2,GPT,...)/File(\EFI\proxmox\grubx64.efi)
```

```text
efibootmgr 完全沒有 proxmox 項目
  → 開機項目沒建起來。進 BIOS 手動新增，指向 \EFI\proxmox\grubx64.efi
有項目但 BootOrder 排在 USB／網路開機之後
  → 進 BIOS 調順序即可
連 LVM2_member 都沒看到
  → ★★★★★ 根本沒裝到這顆碟。確認當初選的 Target Harddisk 是哪一顆，重裝
```

★★★★ PVE 用 `proxmox-boot-tool` 管理開機分割（ZFS root 走 systemd-boot，
LVM root 走 GRUB）。裝好之後在系統內確認：

```bash
$ proxmox-boot-tool status
Re-executing '/usr/sbin/proxmox-boot-tool' in new private mount namespace..
System currently booted with uefi
1234-5678 is configured with: uefi (versions: 6.8.12-4-pve)
```

★★★★★ 這個輸出很重要 —— 它決定了**你之後要改哪個檔案加核心參數**（情境七會用到）：

| `proxmox-boot-tool status` 說 | 開機方式 | 核心參數改哪裡 | 套用指令 |
| --- | --- | --- | --- |
| ★★★★★ `is configured with: uefi` | systemd-boot（多半是 ZFS root） | `/etc/kernel/cmdline` | `proxmox-boot-tool refresh` |
| ★★★★★ `is configured with: grub` 或沒有 `proxmox-boot-tool` 管理 | GRUB | `/etc/default/grub` 的 `GRUB_CMDLINE_LINUX_DEFAULT` | `update-grub` |

★★★★★ 改錯檔案 = 參數永遠不生效，而你會以為 BIOS 沒開。改完一定要驗證：

```bash
$ cat /proc/cmdline
BOOT_IMAGE=/boot/vmlinuz-6.8.12-4-pve root=/dev/mapper/pve-root ro quiet intel_iommu=on
#                                                                    ^^^^^^^^^^^^^^^^ 有出現才算數
```

【6】★★★★★ 套件庫切換：**沒有訂閱就一定要做這件事**，否則所有更新與安全性修補都失效。

```bash
$ sudo apt update
Err:1 https://enterprise.proxmox.com/debian/pve bookworm InRelease
  401  Unauthorized [IP: 144.217.225.162 443]
E: The repository 'https://enterprise.proxmox.com/debian/pve bookworm InRelease' is not signed.
```

★★★★ 先看清楚目前有哪些來源（PVE 8 可能同時有 `.list` 與 `.sources` 兩種格式）：

```bash
$ grep -rvE '^\s*#|^\s*$' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null
/etc/apt/sources.list:deb http://ftp.tw.debian.org/debian bookworm main contrib
/etc/apt/sources.list:deb http://security.debian.org bookworm-security main contrib
/etc/apt/sources.list.d/pve-enterprise.list:deb https://enterprise.proxmox.com/debian/pve bookworm pve-enterprise
/etc/apt/sources.list.d/ceph.list:deb https://enterprise.proxmox.com/debian/ceph-quincy bookworm enterprise
```

處理三步（★★★★ 註解掉而不是刪除，日後買了訂閱可以直接還原）：

```bash
$ sudo sed -i 's/^deb/# deb/' /etc/apt/sources.list.d/pve-enterprise.list
$ sudo sed -i 's/^deb/# deb/' /etc/apt/sources.list.d/ceph.list
$ echo 'deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription' \
    | sudo tee /etc/apt/sources.list.d/pve-no-subscription.list
$ sudo apt update
Get:1 http://download.proxmox.com/debian/pve bookworm InRelease [2,768 B]
...
All packages are up to date.                     # ★★★★★ 看到這句才算成功
```

> [!warning] ★★★★ `pve-no-subscription` 不是「免費的企業版」
> 它是**測試較少**的套件庫，官方明確標示不建議用於正式環境。機關內部使用時，
> 至少要做到：升級前一定跑升級檢查工具、一定有可還原的備份、
> 不要在正式與測試機同時升級。授權與成本的判斷見
> [[050-01-01-04-guide-虛擬化-機關選型與授權成本]]。

★★★ 後台每次登入跳的「No valid subscription」提示是**正常的**，不影響功能。
不要為了拿掉它去 `sed` 改 `proxmoxlib.js` —— 改壞會讓後台整個變白畫面，
而且每次 `proxmox-widget-toolkit` 更新都會被蓋回去。

**原理詳見** [[050-01-03-01-svc-PVE-安裝與初始設定]]（安裝流程、套件庫、初始檢查）、
[[050-01-01-02-guide-虛擬化-虛擬化底層技術]]（VT-x／EPT 與巢狀虛擬化為什麼會慢）。

**預防**：
- ★★★★★ 裝完的第一件事就是切套件庫 + `apt update && apt full-upgrade`，不要等到要裝東西才發現
- ★★★★★ 安裝前把**不相干的磁碟先拔掉或在 BIOS 停用**，這是防止裝錯碟最有效的一招
- ★★★★ BIOS 設定（VT-x、IOMMU、AHCI、開機順序、Secure Boot）在上架時就一次設好並記錄，
  見 [[040-02-09-guide-機房-伺服器上架與初始設定]]
- ★★★★ 安裝後把 `proxmox-boot-tool status` 的輸出記進機器資產表，之後改核心參數會用到

### ★★★★ 情境二：儲存規劃錯了，上線之後才發現

**現象**：這一類的共通點是 —— **當初沒錯，是後來才變成問題**。
安裝時按預設值一路 Next，跑三個月之後開始出事。

```text
（A）local 只有幾十 GB，放了幾個 ISO 加一次備份就滿了
（B）lvs 顯示 Data% 只有 40%，但 Meta% 已經 95%，VM 開始出現 I/O error
（C）NFS 加不進來；或加進來之後整個後台變超慢、一直轉圈
（D）iSCSI 上的 VM 偶爾 I/O error，dmesg 有 session 相關訊息
（E）free -h 顯示記憶體幾乎用光，但 VM 加起來根本沒配那麼多
```

**判斷分流**：★★★★★ 先分清楚**滿的是哪一層**，四層各自的處理方式完全不同。

```bash
$ df -h / /var/lib/vz | grep -v tmpfs      # ① 主機根檔案系統（LVM 的 pve-root）
$ lvs -a -o lv_name,lv_size,data_percent,metadata_percent   # ② LVM-thin pool
$ zpool list; zfs list -o space            # ③ ZFS pool
$ pvesm status                             # ④ PVE 看到的每個儲存
```

```text
df 的 / 快滿              →【1】ISO／備份／日誌塞在根分割
lvs 的 Meta% 先滿          →【2】★★★★★ 中繼資料用盡，最容易被忽略的一種
lvs 的 Data% 滿            → 12 篇症狀 C（本篇不重複）
zpool 的 CAP 超過 80%      →【5】順便看 ARC
pvesm status 有 inactive   →【3】（NFS）或【4】（iSCSI）
記憶體被吃光但 VM 沒配那麼多 →【5】ZFS ARC
```

**可能原因**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 根分割滿，設定改不動、VM 起不來 | ISO 與備份預設放 `local`，而 `local` 的路徑 `/var/lib/vz` 就在根分割上 | `du -sh /var/lib/vz/*` 找兇手，搬走並收緊 `local` 的 `content` |
| ★★★★★ `Meta%` 到 100 但 `Data%` 還很低 | thin pool 的中繼資料區是**獨立且很小**的一塊，快照與大量小型精簡磁碟會先吃光它 | `lvextend --poolmetadatasize +1G pve/data`（★★★★ 中繼資料區只能加不能減） |
| ★★★★★ VM 集體變唯讀、日誌全是 I/O error | thin pool 的 Data 或 Meta 任一到 100% | 立刻停止寫入 → 刪快照 → 擴充 pool；救回後在 guest 內做檔案系統檢查 |
| ★★★★ VM 裡刪了 50 GB，`Data%` 完全沒降 | discard/TRIM 鏈路沒打通 | 磁碟加 `discard=on`、控制器用 VirtIO SCSI、guest 內 `fstrim -av` |
| ★★★★ 加 NFS 時 `create storage failed: mount error` | export 沒放行這台的 IP、防火牆擋、或路徑打錯 | 先 `pvesm scan nfs <ip>` 確認 export 看得到；NFS 端 `exportfs -ra` |
| ★★★★★ NFS 主機掛掉後整個後台變超慢、一直轉圈 | `pvestatd` 卡在 hard mount 上收不到狀態 | `pvesm set <id> --disable 1` → `umount -f -l /mnt/pve/<id>` → `systemctl restart pvestatd` |
| ★★★★ NFS 儲存 `active` 但備份寫入失敗 | export 是 `ro`，或 `root_squash` 把 root 降權 | NFS 端改成 `rw`（必要時 `no_root_squash`）後 `exportfs -ra` |
| ★★★★ iSCSI 的 VM 偶發 I/O error、`dmesg` 出現 `connection ... error` | 網路抖動或 `replacement_timeout` 太短 | 修網路是根本解；調 `/etc/iscsi/iscsid.conf` 只是緩解 |
| ★★★★ iSCSI LUN 掛得上但沒有快照功能 | `iscsi` 與 thick `lvm` 後端本來就不支援快照 | 要快照就把磁碟 `qm move-disk` 到 `lvmthin`／`zfspool`／qcow2 目錄儲存 |
| ★★★★ 多節點同時掛同一個 iSCSI LUN 後資料毀損 | ★★★★★ 沒有叢集檔案系統卻當共享用 | LUN 上建 LVM，由 PVE 以 `lvm` 儲存管理；**不要**多節點直接掛同一個檔案系統 |
| ★★★★ ZFS 節點記憶體幾乎被吃光 | ARC 預設會吃掉相當比例的實體記憶體 | 設 `zfs_arc_max` 後 `update-initramfs -u -k all` 並**重開機** |
| ★★★★ ZFS pool 超過 85% 之後寫入變超慢 | 高使用率下配置策略改變 | 刪快照／搬資料／加 vdev；★★★★★ 規劃時就把 20% 當成「不能用」 |
| ★★★ `pvesm remove` 之後空間沒變多 | `remove` 只刪儲存**定義**，不刪磁碟上的資料 | 到該路徑手動刪檔案 |
| ★★★★ 遷移後 VM 在目標節點找不到磁碟 | 本機儲存被誤設 `--shared 1` | `pvesm set <id> --shared 0` 後重做遷移 |

**處置步驟**：

【1】★★★★ 根分割滿：PVE 的 `local` 預設就在 `/var/lib/vz`，而它在根分割上。

```bash
$ df -h /
Filesystem            Size  Used Avail Use% Mounted on
/dev/mapper/pve-root   94G   91G  0.5G  99% /
$ du -sh /var/lib/vz/* 2>/dev/null | sort -h
12M     /var/lib/vz/snippets
1.4G    /var/lib/vz/template
38G     /var/lib/vz/template/iso        # ★★★★ ISO 堆積
44G     /var/lib/vz/dump                # ★★★★ 備份直接寫進根分割
```

★★★★ 三步處理，順序不要換：

```bash
# ① 先確認哪些 ISO 真的還要用，其餘刪掉（★★★ 刪之前先看檔名與日期）
$ ls -lht /var/lib/vz/template/iso/ | head
$ rm -f /var/lib/vz/template/iso/<確定不要的>.iso

# ② 把備份挪到別的儲存，之後才收緊 content
$ pvesm status
Name             Type     Status           Total            Used       Available        %
local             dir     active        96633312        94088520          352184   97.37%
backup-nas        nfs     active      4194304000       891289600      3303014400   21.25%
$ mv /var/lib/vz/dump/*.vma.zst /mnt/pve/backup-nas/dump/    # ★★★★ 先搬完再改設定

# ③ 收緊 local，讓它再也放不進備份與 ISO
$ pvesm set local --content vztmpl,snippets
$ pvesm status | grep local
local             dir     active        96633312        11298304        80311800   11.69%
```

> [!tip] ★★★★ 正確的長期設計
> `local`（根分割）**只放範本與 snippets**；ISO 放獨立目錄儲存或 NFS；
> 備份一律放外部儲存。根分割留給系統，不要跟資料搶。詳細規劃見
> [[050-01-03-02-guide-PVE-儲存設定]]。

【2】★★★★★ thin pool 的 **Meta 用盡** —— 這是最容易被漏看的一種。

```bash
$ lvs -a -o lv_name,lv_size,data_percent,metadata_percent,lv_attr
  LV              LSize    Data%  Meta%  Attr
  data            <320.00g 41.85  96.72  twi-aotz--     # ★★★★★ Data 才 41%，Meta 已 96%
  [data_tdata]    <320.00g                 Twi-ao----
  [data_tmeta]      3.25g                  ewi-ao----   # ★★★★ 中繼資料區只有 3.25 GB
  vm-101-disk-0    50.00g  62.10           Vwi-aotz--
```

★★★★★ Meta 一旦到 100%，thin pool 會被核心設成**唯讀甚至失效**，
上面所有 VM 同時變唯讀 —— 症狀跟「空間滿了」一模一樣，但 `Data%` 看起來很健康，
所以第一次遇到的人常常查錯方向。

```text
Meta% > 80%   → 現在就處理，還來得及線上擴充
Meta% > 95%   → ★★★★★ 立刻停止建立新快照與新磁碟
Meta% = 100%  → pool 已經受損，見下方 danger
```

處理（★★★★ 兩件事都要做：擴中繼資料 + 減少快照）：

```bash
# ① 先確認 VG 還有沒有空間可以撥
$ vgs
  VG  #PV #LV #SN Attr   VSize    VFree
  pve   1  12   0 wz--n- <446.13g 18.75g          # ★★★★ VFree 要夠才擴得動

# ② 擴充中繼資料區（★★★★ 只能加不能減，一次加夠但不要浮誇）
$ lvextend --poolmetadatasize +2G pve/data
  Size of logical volume pve/data_tmeta changed from 3.25 GiB to 5.25 GiB.
  Logical volume pve/data successfully resized.
$ lvs -o lv_name,data_percent,metadata_percent pve/data
  LV   Data%  Meta%
  data 41.85  59.83                                # ★★★★ 降下來了

# ③ 找出誰在製造快照
$ for id in $(qm list | awk 'NR>1{print $1}'); do
    n=$(qm listsnapshot $id | grep -vc '^\s*$'); echo "$id: $n"
  done
101: 1
102: 14                                            # ★★★★★ 這台的快照沒人清
$ qm listsnapshot 102
 `-> preupdate-2026-05-11    2026-05-11 02:00:03
 `-> preupdate-2026-05-18    2026-05-18 02:00:04
 ...
$ qm delsnapshot 102 preupdate-2026-05-11          # ★★★★ 一個一個刪，每刪一個看一次 lvs
```

> [!danger] ★★★★★ 不要用 `lvremove` 直接刪 VM 的磁碟或快照
> 那會繞過 PVE，`/etc/pve/qemu-server/<id>.conf` 仍然記著這顆磁碟，
> 之後 VM 開不起來、備份也會失敗，而且**沒有乾淨的還原路徑**。
> 一律用 `qm delsnapshot` / `qm disk unlink` / `pct` 對應指令。
>
> ★★★★★ 若 `Meta%` 已經到 100%，pool 可能已經是 `dm-thin` 的 error 狀態。
> 這時**先不要重開機**，先把還讀得到的 VM 磁碟複製出去，
> 再依 LVM 文件的 `thin_check` / `thin_repair` 流程處理 —— 那是有資料遺失風險的操作。

【3】★★★★ NFS：分成「加不進來」與「加進來但拖垮主機」兩種，後者更麻煩。

加不進來時，★★★★★ **先在指令列證明掛得起來**，不要在後台反覆按：

```bash
$ pvesm scan nfs 192.168.10.20
192.168.10.20:/export/pve-backup    192.168.10.0/24
192.168.10.20:/export/iso           *
#   完全沒有輸出 → NFS 端沒 export、或防火牆擋（TCP/UDP 2049、111）

$ showmount -e 192.168.10.20
Export list for 192.168.10.20:
/export/pve-backup 192.168.10.0/24

# ★★★★ 手動掛一次，錯誤訊息比後台清楚得多
$ mkdir -p /mnt/test && mount -t nfs 192.168.10.20:/export/pve-backup /mnt/test
mount.nfs: access denied by server while mounting 192.168.10.20:/export/pve-backup
#   access denied  → export 的來源 IP 網段不含這台
#   No route to host → 網路或防火牆
#   Connection timed out → 對方沒開 NFS 或被擋
$ touch /mnt/test/x && echo "可寫" || echo "唯讀 → export 是 ro 或 root_squash"
可寫
$ umount /mnt/test
```

確認可掛可寫之後才加進 PVE：

```bash
$ pvesm add nfs backup-nas --server 192.168.10.20 --export /export/pve-backup \
    --content backup --options vers=4.2
$ pvesm status | grep backup-nas
backup-nas        nfs     active      4194304000       891289600      3303014400   21.25%
```

★★★★★ 加進來之後拖垮主機（後台一直轉圈、`pvesm status` 卡住）：

```bash
$ pvesm status                       # 卡住不回來 → 幾乎確定是某個網路儲存失聯
^C
$ findmnt -t nfs,nfs4
TARGET             SOURCE                              FSTYPE OPTIONS
/mnt/pve/backup-nas 192.168.10.20:/export/pve-backup   nfs4   rw,relatime,hard,...
$ ping -c2 -W2 192.168.10.20
--- 192.168.10.20 ping statistics ---
2 packets transmitted, 0 received, 100% packet loss     # ★★★★★ 儲存主機真的不見了
```

★★★★ 止血三步（先讓主機恢復正常，再去修 NAS）：

```bash
$ pvesm set backup-nas --disable 1        # ① 先讓 PVE 不要再去碰它
$ umount -f -l /mnt/pve/backup-nas        # ② -l（lazy）才卸得掉 hard mount
$ systemctl restart pvestatd              # ③ 狀態收集重新開始
$ pvesm status                            # 立刻回來了
```

> [!warning] ★★★★★ NFS 儲存**不要**寫進 `/etc/fstab`
> 寫進 fstab 而且沒加 `nofail`，NAS 一掛掉主機就會停在 emergency mode 開不了機。
> PVE 的 NFS 儲存由 `pvestatd` 自己掛載與管理，交給它就好。

【4】★★★★ iSCSI：斷線是**網路問題**，不是儲存問題。

```bash
$ iscsiadm -m session
tcp: [1] 192.168.20.30:3260,1 iqn.2026-01.local.nas:pve-lun0 (non-flash)
$ iscsiadm -m session -P 3 | grep -E 'iSCSI Session State|Internal iscsid Session State'
                iSCSI Session State: LOGGED_IN
                Internal iscsid Session State: NO CHANGE
$ dmesg -T | grep -i iscsi | tail -5
[Tue Sep  2 03:12:41 2026] connection1:0: detected conn error (1020)
[Tue Sep  2 03:12:56 2026] connection1:0: detected conn error (1020)   # ★★★★ 反覆斷線
```

```text
LOGGED_IN 且沒有 conn error   → iSCSI 本身正常，問題在別的地方
反覆 conn error               → ★★★★★ 網路：查交換器埠錯誤計數、MTU 是否一致、
                                有沒有跟備份流量搶頻寬
完全沒有 session              → iscsid 沒跑或目標端拒絕：systemctl status iscsid、
                                iscsiadm -m discovery -t st -p <ip>
```

★★★★ 短暫斷線就讓 VM 出現 I/O error，是因為預設的 `replacement_timeout` 比 guest
的 SCSI 逾時短。調整（★★★ 這是**緩解**不是根治）：

```bash
$ grep replacement_timeout /etc/iscsi/iscsid.conf
node.session.timeo.replacement_timeout = 120
$ systemctl restart iscsid open-iscsi
```

★★★★★ 多節點共用 iSCSI 的正確做法：LUN 上建 LVM，PVE 以 `lvm` 型別管理，
由 PVE 保證同一顆磁碟只被一個節點使用。**不要**在多個節點上直接掛同一個 ext4/xfs
—— 那會在沒有任何警告的情況下毀掉資料。

【5】★★★★ ZFS ARC 吃光記憶體：先確認「是不是真的 ARC」。

```bash
$ free -h
               total        used        free      shared  buff/cache   available
Mem:            125Gi       118Gi       2.1Gi       0.0Ki       5.2Gi       6.4Gi
$ qm list | awk 'NR>1{s+=$4} END{print "VM 配置合計:", s, "MB"}'
VM 配置合計: 49152 MB                     # ★★★★★ VM 只配了 48 GB，卻用掉 118 GB
$ arc_summary | head -20
ARC size (current):                                    58.4 %   36.5 GiB
        Target size (adaptive):                       100.0 %   62.5 GiB
        Min size (hard limit):                          6.2 %    3.9 GiB
        Max size (high water):                           16:1   62.5 GiB   # ★★★★ 上限沒設
```

★★★★ 設上限（單位是 byte）：

```bash
$ echo "options zfs zfs_arc_max=17179869184" | sudo tee /etc/modprobe.d/zfs.conf
options zfs zfs_arc_max=17179869184           # 16 GiB
$ sudo update-initramfs -u -k all
update-initramfs: Generating /boot/initrd.img-6.8.12-4-pve
$ sudo proxmox-boot-tool refresh               # ★★★★ systemd-boot 的機器要多這一步
$ sudo reboot
```

★★★★★ 三個常見錯誤，每一個都會讓你以為「設了沒用」：

| 做了什麼 | 為什麼沒生效 |
| --- | --- |
| ★★★★★ 只寫了 `/etc/modprobe.d/zfs.conf` 就重開機 | 沒跑 `update-initramfs`，ZFS 在 initramfs 階段就載入了，讀不到新設定 |
| ★★★★★ 跑了 `update-initramfs` 但沒重開機 | 模組參數只有在載入時讀一次 |
| ★★★★ ZFS root 的機器只跑 `update-initramfs` | systemd-boot 需要 `proxmox-boot-tool refresh` 把 initrd 同步到 ESP |

★★★ 臨時調整（不重開機，重開就失效，只適合救急）：

```bash
$ echo 17179869184 | sudo tee /sys/module/zfs/parameters/zfs_arc_max
$ arc_summary | grep -A1 'Max size'
```

**原理詳見** [[050-01-03-02-guide-PVE-儲存設定]]（各儲存型別的能力矩陣、thin pool 機制、
容量規劃）、[[020-01-24-guide-進階儲存-ZFS與Btrfs]]（ARC、快照與 pool 健康）、
[[020-01-15-cmd-Linux-磁碟分割與掛載]]（`df`／`du`／掛載選項）。

**預防**：
- ★★★★★ 建置當天就把 `local` 的 `content` 收成 `vztmpl,snippets`，ISO 與備份都放外部
- ★★★★★ thin pool 的 **`Data%` 與 `Meta%` 都要監控**，75% 提醒、85% 告警
  （設定見 [[100-01-03-guide-日誌-系統監控與告警]]）
- ★★★★ 快照要有保留政策，「開機前先拍一張」很好，但要有人負責刪
- ★★★★ ZFS pool 規劃時就把使用率上限訂在 **80%**，超過就是要加碟不是要清檔案
- ★★★★ 網路儲存一律加監控，NAS 掉線要在 PVE 卡住之前就有人知道

### ★★★★ 情境三：VM 效能不如預期

**現象**：VM 「跑得動但很慢」，而主機的 CPU、記憶體、磁碟看起來都沒滿。

```text
（A）磁碟讀寫只有實體機的十分之一，guest 內 iowait 很高
（B）網路只有幾十 Mbps，明明是 10G 網卡
（C）VM 遷到另一個節點就 kernel panic，或 HTTPS/VPN 效能特別差
（D）多顆磁碟的 VM，一顆在忙其他幾顆全部跟著卡
（E）資料庫 VM 週期性卡頓，guest 內看到大量 swap
```

> [!warning] ★★★★★ 先分清楚「慢」是誰的問題
> 這個情境處理的是**設定選錯**造成的慢。如果是**主機資源真的不夠**
> （超配、IO delay 持續偏高、steal time 高），那是容量規劃問題，
> 請走 [[050-01-03-09-svc-PVE-監控與資源調校]]，不要在這裡調參數。
> ★★★★★ 判斷方法：主機 `IO delay` 長期 < 5%、`free -h` 沒吃 swap，
> 那就是設定問題；反過來就是資源問題。

**判斷分流**：★★★★★ 一個指令就能看出九成的問題 —— **把設定攤開來看**。

```bash
$ qm config 101
agent: 1
boot: order=scsi0;net0
cores: 4
cpu: kvm64                                    # ★★★★★ 問題 1：沒有 AES-NI
ide0: local-lvm:vm-101-cloudinit,media=cdrom
memory: 8192
balloon: 2048                                 # ★★★★ 問題 2：最小值遠低於 memory
name: db-prod
net0: e1000=BC:24:11:xx:xx:xx,bridge=vmbr0    # ★★★★★ 問題 3：模擬網卡
numa: 0
ostype: l26
sata0: local-lvm:vm-101-disk-0,size=200G      # ★★★★★ 問題 4：SATA 模擬控制器
scsihw: lsi                                   # ★★★★★ 問題 5：不是 virtio-scsi
smbios1: uuid=...
sockets: 1
```

```text
net0 是 e1000 / rtl8139        →【1】換 virtio
scsihw 是 lsi / megasas        →【1】換 virtio-scsi-single
磁碟掛在 ide / sata            →【1】換 scsi
cpu 是 kvm64 / qemu64          →【2】換 x86-64-v2-AES
磁碟參數有 cache=unsafe        →【3】★★★★★ 立刻改掉
多磁碟但沒有 iothread=1        →【4】
balloon 小於 memory 且是資料庫 →【5】
以上都對，但還是慢             → 資源不夠，去 09 篇
```

**可能原因**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 磁碟慢、guest iowait 高 | 用了 `ide`／`sata` 模擬控制器，每個 I/O 都要模擬硬體暫存器 | 改掛 `scsi` + `scsihw: virtio-scsi-single`（★★★★ Windows 要先裝 VirtIO 驅動） |
| ★★★★★ 網路只有幾十 Mbps | 網卡型號是 `e1000`／`rtl8139` 模擬卡 | `qm set <id> --net0 virtio,bridge=vmbr0`（★★★★ **要完全關機**才生效） |
| ★★★★★ Windows 安裝時看不到磁碟 | 安裝程式沒有 VirtIO SCSI 驅動 | 加掛 `virtio-win.iso`，在「選擇磁碟」頁按「載入驅動程式」選 `vioscsi` |
| ★★★★★ VM 遷過去就 panic | `cpu: host` 但兩台 CPU 指令集不同 | 改成 `x86-64-v2-AES` 之類的相容等級（★★★★ 要完全關機） |
| ★★★★ HTTPS／VPN 效能特別差 | `cpu: kvm64` 這個舊 model **沒有 AES-NI** | 改 `x86-64-v2-AES`，guest 內用 `grep -m1 aes /proc/cpuinfo` 驗證 |
| ★★★★★ 主機斷電後 guest 檔案系統毀損 | `cache=unsafe` 會把 flush 指令直接忽略 | 全叢集清查並改成 `cache=none` |
| ★★★★ 多顆磁碟互相拖累 | 沒開 `iothread=1`，所有磁碟共用同一條 I/O 執行緒 | 控制器改 `virtio-scsi-single` **且**每顆磁碟加 `iothread=1`，兩者缺一不可 |
| ★★★★ 資料庫 VM 週期性卡頓、guest 狂 swap | balloon 在主機記憶體吃緊時把 guest 的記憶體抽走 | 關鍵 VM 設 `--balloon 0`（等於固定配置） |
| ★★★★ 主機記憶體在 80% 附近震盪、所有 VM 一起抖 | ★★★★★ balloon 抖動，根因是**超配** | 減載或加記憶體；調 balloon 參數治不好 |
| ★★★★ 後台的 VM 記憶體圖表永遠 100% | 沒裝 QEMU Guest Agent，PVE 讀不到 guest 真實用量 | guest 裝 `qemu-guest-agent`，PVE 端 `qm set <id> --agent enabled=1` |
| ★★★★ thin pool 用量只增不減 | 磁碟沒開 `discard=on`，或 guest 沒跑 TRIM | 加 `discard=on,ssd=1`，guest 內啟用 `fstrim.timer` |
| ★★★ 改了設定「完全沒有變化」 | ★★★★★ 只按了 Reboot，沒有完全關機 | 硬體層面的變更（CPU type、網卡型號、控制器）**一定要 `qm shutdown` 再 `qm start`** |

**處置步驟**：

【1】★★★★★ VirtIO 三件套：**控制器、磁碟、網卡**，三個都要換才有效果。

先看現況與可用選項：

```bash
$ qm config 101 | grep -E '^(scsihw|sata|ide|scsi|virtio|net)'
scsihw: lsi
sata0: local-lvm:vm-101-disk-0,size=200G
net0: e1000=BC:24:11:xx:xx:xx,bridge=vmbr0
```

★★★★★ 換法（Linux guest 通常換完就能開；**Windows guest 要先裝驅動**，見下方警告）：

```bash
# ① 先關機（★★★★★ 不是 reboot）
$ qm shutdown 101 && sleep 20 && qm status 101
status: stopped

# ② 快照或備份（★★★★★ 這一步不要省，換控制器有開不起來的風險）
$ qm snapshot 101 pre-virtio --description "換 VirtIO 前"

# ③ 把 SATA 磁碟卸下來，改掛成 SCSI
$ qm set 101 --delete sata0
update VM 101: -delete sata0
$ qm config 101 | grep unused
unused0: local-lvm:vm-101-disk-0                 # ★★★★ 磁碟還在，只是沒掛上
$ qm set 101 --scsihw virtio-scsi-single --scsi0 local-lvm:vm-101-disk-0,discard=on,ssd=1,iothread=1
$ qm set 101 --boot order=scsi0

# ④ 網卡換 virtio（★★★★ 沿用原本的 MAC，避免 guest 內網路設定失效）
$ qm set 101 --net0 virtio=BC:24:11:xx:xx:xx,bridge=vmbr0

# ⑤ 開機驗證
$ qm start 101
$ qm config 101 | grep -E '^(scsihw|scsi0|net0|boot)'
boot: order=scsi0
net0: virtio=BC:24:11:xx:xx:xx,bridge=vmbr0
scsi0: local-lvm:vm-101-disk-0,discard=on,iothread=1,size=200G,ssd=1
scsihw: virtio-scsi-single
```

> [!danger] ★★★★★ Windows guest 換控制器之前，一定要先在 guest 裡裝好 VirtIO 驅動
> 直接把系統碟從 `sata` 改成 `scsi` + `virtio-scsi`，Windows 開機會直接藍屏
> `INACCESSIBLE_BOOT_DEVICE`，而且**不是改回去就一定會好**。
> 安全做法：先掛一顆很小的 `scsi1` 暫時磁碟讓 Windows 認得 VirtIO 控制器並裝好驅動，
> 確認裝置管理員裡有 `Red Hat VirtIO SCSI controller` 之後，再關機換系統碟。
> ★★★★★ 動手前先 `qm snapshot`，出事才有回頭路。

★★★★ guest 內驗證真的換過來了：

```bash
# Linux guest
$ lsblk -o NAME,SIZE,TRAN
NAME   SIZE TRAN
sda    200G                       # 換之前是 sata
$ lspci | grep -i virtio
00:05.0 SCSI storage controller: Red Hat, Inc. Virtio SCSI
00:12.0 Ethernet controller: Red Hat, Inc. Virtio network device
$ ethtool eth0 | grep Speed
        Speed: Unknown!           # ★★★ virtio 沒有實體速率，顯示 Unknown 是正常的
```

【2】★★★★ CPU type：這是**遷移相容性**與**效能**的取捨，不是越高越好。

```bash
$ qm config 101 | grep ^cpu
cpu: kvm64
$ qm cpu 2>/dev/null || echo "可用清單見 qm set --help 的 --cpu 說明"
```

★★★★★ 選擇原則：

| 情境 | 選什麼 | 為什麼 |
| --- | --- | --- |
| ★★★★★ 叢集內 CPU 型號不一致 | `x86-64-v2-AES` 之類的通用等級 | 保證能在任一節點開機與遷移，且有 AES-NI |
| ★★★★ 單機、不需要遷移、要壓榨效能 | `host` | 把實體 CPU 的指令集全部傳給 guest |
| ★★★★★ 千萬不要留著的 | `kvm64`／`qemu64` | 這是很舊的相容 model，**沒有 AES-NI**，加解密效能差很多 |

```bash
$ qm shutdown 101 && sleep 20
$ qm set 101 --cpu x86-64-v2-AES
$ qm start 101
# guest 內驗證
$ ssh root@<guest> "grep -m1 -o aes /proc/cpuinfo"
aes                                          # ★★★★ 有這行才代表 AES-NI 傳進去了
```

> [!warning] ★★★★★ 改 CPU type 只按 Reboot 是沒用的
> `qm reboot` 是在 guest 裡重開作業系統，QEMU 行程沒有重建，硬體設定當然不變。
> **一定要 `qm shutdown` 之後再 `qm start`**。
> 這一條同樣適用於：網卡型號、SCSI 控制器、machine type、`pve-qemu-kvm` 更新後的安全性修補。

【3】★★★★★ 快取模式：`cache=unsafe` 是效能陷阱，代價是**斷電就毀資料**。

```bash
# 全叢集清查（★★★★ 每一台都要查，包括 LXC 的設定目錄）
$ grep -rn 'cache=unsafe' /etc/pve/qemu-server/ /etc/pve/nodes/*/qemu-server/ 2>/dev/null
/etc/pve/nodes/pve01/qemu-server/108.conf:scsi0: local-lvm:vm-108-disk-0,cache=unsafe,size=100G
```

★★★★ 各模式的取捨（★★★★★ 沒有把握就用 `none`）：

| `cache=` | 行為 | 什麼時候用 |
| --- | --- | --- |
| ★★★★★ `none` | 繞過主機 page cache，尊重 guest 的 flush | **預設就用這個**；ZFS、LVM-thin、Ceph 都適合 |
| ★★★★ `writeback` | 用主機 page cache，flush 才落地 | 目錄型儲存 + qcow2 且有 UPS 保護時可考慮 |
| ★★★ `writethrough` | 每次寫入都同步落地 | 最安全但最慢，通常不需要 |
| ★★★★★ `unsafe` | **忽略 guest 的 flush 指令** | ★★★★★ 只在「掉了也無所謂」的臨時測試機上用，正式環境絕對不可 |

```bash
$ qm shutdown 108 && sleep 20
$ qm set 108 --scsi0 local-lvm:vm-108-disk-0,cache=none,discard=on,iothread=1,size=100G
$ qm start 108
```

【4】★★★★ IO thread：**兩個條件缺一不可**。

```text
條件一：scsihw 必須是 virtio-scsi-single（不是 virtio-scsi）
條件二：每一顆磁碟都要各自加 iothread=1
```

★★★★★ 只做其中一項是完全沒有效果的 —— `virtio-scsi`（不帶 single）所有磁碟共用一個
控制器，開了 `iothread` 也擠在同一條路上。

```bash
$ qm shutdown 105 && sleep 20
$ qm set 105 --scsihw virtio-scsi-single
$ qm set 105 --scsi0 local-lvm:vm-105-disk-0,iothread=1,discard=on,size=60G
$ qm set 105 --scsi1 local-lvm:vm-105-disk-1,iothread=1,discard=on,size=500G
$ qm start 105
# 驗證：QEMU 真的起了獨立的 iothread
$ qm showcmd 105 --pretty | grep -c iothread
2
```

【5】★★★★ balloon：關鍵服務**不要**讓它動。

```bash
$ qm config 101 | grep -E '^(memory|balloon)'
memory: 8192
balloon: 2048            # ★★★★★ 主機吃緊時，guest 可能被壓到只剩 2 GB
```

```text
資料庫、快取、Java 應用（有固定 heap）  → ★★★★★ balloon 設 0，固定配置
一般 Web／應用伺服器、測試機            → 可以用 balloon 提高整體密度
Windows guest                           → 要裝 virtio Balloon 驅動與服務才有作用
```

```bash
$ qm set 101 --balloon 0
$ qm config 101 | grep -E '^(memory|balloon)'
balloon: 0
memory: 8192             # ★★★★ balloon 0 = 固定給滿 8 GB，不會被抽走
```

★★★★★ 但要記得：**balloon 抖動的根因是主機記憶體超配**。把單一 VM 設成
`balloon 0` 只是保護這一台，其他 VM 會更早受壓。真正的解法是減載或加記憶體，
詳見 [[050-01-03-09-svc-PVE-監控與資源調校]]。

【6】★★★ 改完之後**要量測**，不要只憑感覺。

```bash
# 在 guest 內建立一個可重複的基準（★★★★ 改設定前先跑一次留底）
$ fio --name=randrw --ioengine=libaio --direct=1 --rw=randrw --rwmixread=70 \
      --bs=4k --numjobs=4 --iodepth=32 --size=2G --runtime=60 --group_reporting
   read: IOPS=18.2k, BW=71.1MiB/s
  write: IOPS=7802,  BW=30.5MiB/s
```

> [!tip] ★★★★★ 一次只改一項
> 一口氣把控制器、cache、iothread、CPU type 全部改掉，之後就永遠不知道
> 是哪一項有效、哪一項造成新問題。**改一項 → 量測 → 記錄 → 再改下一項**。

**原理詳見** [[050-01-03-03-guide-PVE-虛擬機管理]]（VirtIO 裝置、磁碟參數、
Windows 驅動安裝）、[[050-01-03-09-svc-PVE-監控與資源調校]]（cache／aio／CPU type／
balloon 的完整取捨與量測方法）、[[050-01-01-02-guide-虛擬化-虛擬化底層技術]]
（半虛擬化為什麼比模擬快）。

**預防**：
- ★★★★★ 做一份**標準 VM 範本**，把 VirtIO 三件套、`cache=none`、`discard=on`、
  `iothread=1`、正確的 CPU type 全部設好，以後一律從範本複製
- ★★★★★ 叢集內 CPU 型號不一致時，**建置當天就統一訂一個 CPU model**，
  不要等到要遷移才發現
- ★★★★ guest 一律裝 `qemu-guest-agent`，否則記憶體圖表、關機、備份 fsfreeze 都不準
- ★★★ 上線前跑一次 `fio` 基準並存檔，日後說「變慢了」才有比較的依據

### ★★★★ 情境四：cloud-init 沒生效

**現象**：範本做好了、複製也成功了，但**設定就是沒進去**。

```text
（A）開機後 IP 還是 DHCP、使用者也不是設定的那一個
（B）第一次開機有生效，改了 --ipconfig0 之後重開機卻沒變
（C）用了 --cicustom 之後，--ciuser 與 --sshkeys 全部失效
（D）複製出來的十台機器 SSH 指紋一樣、DHCP 拿到同一個 IP
（E）Console 一片黑，什麼都看不到（但機器其實有在跑）
```

**判斷分流**：★★★★★ 四個問題各自獨立，用三個指令分開。

```bash
$ qm config 9000 | grep -E 'ide|scsi|cloudinit|ci|ipconfig|sshkeys'   # ① ci 磁碟在不在
$ qm cloudinit dump 101 user                                          # ② PVE 產生了什麼
$ qm cloudinit dump 101 network                                       # ③ 網路那份呢
```

```text
qm config 完全沒有 cloudinit 那一行     →【1】★★★★★ 根本沒加 ci 磁碟
有 ci 磁碟，dump 出來的內容是對的        →【2】只在第一次開機執行的問題
dump 出來看不到 user / ssh_authorized_keys →【3】cicustom 覆蓋
每台機器的 machine-id 都一樣            →【4】範本沒清乾淨
Console 黑畫面但 SSH 進得去              →【5】cloud image 輸出在序列埠
```

**可能原因**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 完全沒套用任何 cloud-init 設定 | 忘了加 cloud-init 磁碟 | `qm set <id> --ide2 local-lvm:cloudinit` 後重開機 |
| ★★★★★ 改了 `--ipconfig0` 但 IP 沒變 | cloud-init 的網路與使用者設定**只在第一次開機**完整執行 | guest 內 `cloud-init clean --logs` 後重開；或**複製後、首次開機前**就設好 |
| ★★★★ `--cicustom` 之後 `--ciuser`／`--sshkeys` 失效 | ★★★★★ 自訂 user-data 是**整份取代**不是合併 | 在自己的 yaml 裡自己寫 `users:` 與 `ssh_authorized_keys:` |
| ★★★★ `--cicustom` 設了但 PVE 說找不到檔案 | snippets 路徑寫錯，或該儲存沒開 `snippets` 內容類型 | `pvesm set <id> --content snippets,...`；路徑格式是 `user=<儲存>:snippets/<檔名>` |
| ★★★★★ 多台機器 DHCP 拿到同一個 IP | 範本沒清 `/etc/machine-id`，DHCP client identifier 重複 | 重做範本並在轉範本前清空；已複製的逐台清掉再重開 |
| ★★★★★ 多台機器 SSH 指紋一樣 | 範本沒清 `/etc/ssh/ssh_host_*` | guest 內刪掉並重新產生；範本要重做 |
| ★★★★ SSH 連不進去，密碼不對 | cloud image 預設**不開密碼登入** | 用 `--sshkeys` 給金鑰；一定要密碼就 `--cipassword` 並在 yaml 開 `ssh_pwauth: true` |
| ★★★★ Console 一片黑 | cloud image 把 console 輸出導到序列埠 | `qm set <id> --serial0 socket --vga serial0`，用 `qm terminal <id>` |
| ★★★ 磁碟擴大了但 guest 沒變大 | cloud image 通常會自動長大，一般安裝的不會 | guest 內 `growpart /dev/sda 2` 再 `resize2fs /dev/sda2` |
| ★★★ 設了 DNS 但 guest 內沒生效 | 只設了 `--nameserver` 沒設 `--searchdomain`，或 guest 用 systemd-resolved 另有來源 | 兩個都設；guest 內 `resolvectl status` 確認 |

**處置步驟**：

【1】★★★★★ 先證明「PVE 這一端有沒有把設定交出去」。

```bash
$ qm config 101 | grep -E 'cloudinit|ciuser|sshkeys|ipconfig|nameserver'
ide2: local-lvm:vm-101-cloudinit,media=cdrom     # ★★★★★ 沒有這一行就什麼都不會發生
ciuser: sysadm
ipconfig0: ip=192.168.10.101/24,gw=192.168.10.254
nameserver: 192.168.10.1
sshkeys: ssh-ed25519%20AAAAC3Nza...
```

★★★★ 看 PVE 實際產生的內容（這是 guest 會拿到的東西）：

```bash
$ qm cloudinit dump 101 user
#cloud-config
hostname: web01
manage_etc_hosts: true
user: sysadm
ssh_authorized_keys:
  - ssh-ed25519 AAAAC3Nza... admin@mgmt
chpasswd:
  expire: False
users:
  - default
package_upgrade: true

$ qm cloudinit dump 101 network
version: 1
config:
    - type: physical
      name: eth0
      mac_address: 'bc:24:11:xx:xx:xx'
      subnets:
      - type: static
        address: '192.168.10.101'
        netmask: '255.255.255.0'
        gateway: '192.168.10.254'
```

```text
dump 出來的內容是對的  → 問題在 guest 端，走【2】
dump 說 no cloudinit drive → 補 ci 磁碟：qm set 101 --ide2 local-lvm:cloudinit
dump 出來缺了 user 或 ssh → 走【3】
```

【2】★★★★★ cloud-init **只在第一次開機**跑完整流程 —— 這是最常被誤解的一點。

```bash
# 在 guest 內
$ cloud-init status --long
status: done
time: Mon, 01 Sep 2026 08:12:44 +0000
detail:
DataSourceNoCloud [seed=/dev/sr0][dsmode=net]
#   status: done 且時間是「第一次開機那天」→ ★★★★★ 之後改的設定當然不會生效
```

要讓它重跑（★★★★ 這會清掉 cloud-init 的狀態，等於「當作第一次開機」）：

```bash
# ① PVE 端先把新設定寫進 ci 磁碟
$ qm set 101 --ipconfig0 ip=192.168.10.111/24,gw=192.168.10.254
$ qm cloudinit update 101

# ② guest 內清狀態再重開
$ cloud-init clean --logs
$ reboot

# ③ 重開後驗證
$ cloud-init status --long
status: done
time: Tue, 02 Sep 2026 09:31:07 +0000        # ★★★★ 時間變成剛剛，代表真的重跑了
$ ip -br a show eth0
eth0  UP  192.168.10.111/24
```

★★★★★ 但正確的做法是**不要走到這一步**：複製之後、**第一次開機之前**就把
`--ipconfig0`、`--ciuser`、`--sshkeys` 全部設好。

```bash
$ qm clone 9000 111 --name web11 --full
$ qm set 111 --ipconfig0 ip=192.168.10.111/24,gw=192.168.10.254 \
             --ciuser sysadm --sshkeys /root/.ssh/authorized_keys \
             --nameserver 192.168.10.1 --searchdomain lab.local
$ qm start 111                                # ★★★★★ 到這一步才第一次開機
```

★★★★ 查 guest 端的日誌（cloud-init 有跑但結果不對時）：

```bash
$ sudo cloud-init status --long
$ sudo tail -40 /var/log/cloud-init.log
$ sudo cat /var/log/cloud-init-output.log | tail -30
$ sudo ls -l /run/cloud-init/
```

【3】★★★★ `--cicustom`：**整份取代**，不是在預設值上疊加。

```bash
$ qm config 101 | grep cicustom
cicustom: user=local:snippets/web-user.yaml,network=local:snippets/web-net.yaml
```

★★★★★ 一旦指定了 `user=`，PVE 就**完全不再產生**它自己的那份 user-data ——
`--ciuser`、`--cipassword`、`--sshkeys` 全部失效，你必須在 yaml 裡自己寫：

```yaml
#cloud-config
hostname: web01
manage_etc_hosts: true
users:
  - name: sysadm
    groups: [sudo]
    shell: /bin/bash
    sudo: ["ALL=(ALL) NOPASSWD:ALL"]
    ssh_authorized_keys:
      - ssh-ed25519 AAAAC3Nza... admin@mgmt
ssh_pwauth: false
package_update: true
packages:
  - qemu-guest-agent
runcmd:
  - systemctl enable --now qemu-guest-agent
```

★★★★ snippets 檔案要放對地方，而且該儲存必須開 `snippets` 內容類型：

```bash
$ pvesm status | grep local
local             dir     active        96633312        11298304        80311800   11.69%
$ pvesm set local --content vztmpl,snippets,iso
$ mkdir -p /var/lib/vz/snippets
$ vi /var/lib/vz/snippets/web-user.yaml
$ qm set 101 --cicustom "user=local:snippets/web-user.yaml"
$ qm cloudinit dump 101 user | head -5        # ★★★★★ dump 出來要跟你寫的一樣
#cloud-config
hostname: web01
```

> [!warning] ★★★★ 叢集環境裡的 snippets 路徑陷阱
> `local` 是**每個節點各自的**目錄。把 snippets 放在 `local` 上，VM 遷到別的節點
> 就找不到那個檔案了。叢集環境請把 snippets 放在**共享儲存**上，
> 或是每個節點都放一份同樣的檔案。

【4】★★★★★ 範本沒清乾淨：**三樣東西**一定要處理。

```text
① /etc/machine-id 與 /var/lib/dbus/machine-id  → 不清會讓 DHCP 發同一個 IP
② /etc/ssh/ssh_host_*                          → 不清會讓所有機器 SSH 指紋一樣
③ cloud-init 狀態                              → 不清會讓 cloud-init 以為已經跑過
```

★★★★ 轉範本之前，在 guest 內跑這一段（★★★★★ 跑完**不要再開機**，直接關機轉範本）：

```bash
# 在準備轉成範本的那台 guest 裡
$ sudo cloud-init clean --logs --seed
$ sudo truncate -s 0 /etc/machine-id
$ sudo rm -f /var/lib/dbus/machine-id
$ sudo ln -s /etc/machine-id /var/lib/dbus/machine-id
$ sudo rm -f /etc/ssh/ssh_host_*
$ sudo rm -rf /var/lib/cloud/instances/* /var/lib/cloud/instance
$ sudo apt clean && sudo rm -rf /tmp/* /var/tmp/*
$ history -c && sudo shutdown -h now          # ★★★★★ 關機，之後不要再開起來
```

回到 PVE 轉範本：

```bash
$ qm template 9000
$ qm config 9000 | grep template
template: 1
```

★★★ 已經複製出去的機器怎麼補救（逐台做，做完重開）：

```bash
$ ssh root@<guest> 'truncate -s 0 /etc/machine-id; rm -f /var/lib/dbus/machine-id; \
    ln -s /etc/machine-id /var/lib/dbus/machine-id; \
    rm -f /etc/ssh/ssh_host_*; dpkg-reconfigure -f noninteractive openssh-server; reboot'
```

> [!danger] ★★★★★ `qm template` 是不可逆的
> 轉成範本之後**不能開機、不能修改、也沒有 untemplate 指令**。
> 要改範本只能：從範本 full clone 一台 → 修改 → 再 `qm template` 成新範本。
> ★★★★★ 而且範本底下若還有 linked clone，就**刪不掉**這個範本。
> 轉範本前請先確認：該裝的套件裝了、該清的清了、該關的服務關了。

【5】★★★ Console 黑畫面：cloud image 預設把輸出送到序列埠。

```bash
$ qm set 101 --serial0 socket --vga serial0
$ qm stop 101 && qm start 101
$ qm terminal 101
starting serial terminal on interface serial0 (press Ctrl+O to exit)

Debian GNU/Linux 12 web01 ttyS0
web01 login:
```

**原理詳見** [[050-01-03-13-guide-PVE-建立練習環境]]（範本製作、cloud image、
批次複製的完整流程）、[[050-01-03-03-guide-PVE-虛擬機管理]]（複製、範本、
machine-id 與 host key 的處理）。

**預防**：
- ★★★★★ 範本製作寫成**檢查清單**（清 machine-id、清 host key、清 cloud-init、
  裝 guest agent、關掉 onboot），每次做範本都照著跑一遍
- ★★★★★ 複製之後、**第一次開機之前**就把 cloud-init 參數設完，不要事後補
- ★★★★ 範本命名帶日期與用途（`tpl-debian12-2026-09`），舊範本保留一版以便回退
- ★★★ 叢集環境的 snippets 放共享儲存，不要放 `local`

### ★★★★ 情境五：LXC 特有的坑

**現象**：這些問題**只會在 LXC 發生，VM 不會有** —— 因為 LXC 與主機共用核心。

```text
（A）容器裡看主機掛進來的目錄，全部是 nobody:nogroup，寫不進去
（B）bind mount 的檔案在主機是 1000:1000，容器裡卻變成別的數字
（C）容器裡裝 Docker，daemon 起不來或 overlay2 不支援
（D）pveam download 抓不到範本
（E）容器裡 modprobe / systemctl 某些服務起不來
```

> [!note] ★★★★★ 先建立正確的心智模型
> 非特權容器（unprivileged）裡的 root（UID 0），在**主機上其實是 UID 100000**。
> 位移量是 100000，範圍 65536。所以：
> 容器 UID 0 → 主機 100000；容器 UID 1000 → 主機 101000。
> 「權限看起來很怪」的問題，九成都是這個位移造成的。

**判斷分流**：

```bash
$ pct config 201 | grep -E 'unprivileged|features|mp[0-9]|rootfs'
unprivileged: 1                                # ★★★★★ 先確認是不是非特權
features: nesting=1
mp0: /srv/data,mp=/data
rootfs: local-lvm:vm-201-disk-0,size=8G
```

```text
unprivileged: 1 + 檔案顯示 nobody   →【1】UID 位移
unprivileged: 1 + bind mount 寫不了 →【2】主機端擁有者不在對應範圍
Docker 起不來                       →【3】
pveam 抓不到範本                    →【4】
modprobe / 某些服務起不來           →【5】★★★★ 這是設計限制，不是故障
容器完全起不來（error -1）           → 12 篇 症狀 G（本篇不重複）
```

**可能原因**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 容器內看到 `nobody:nogroup` | 主機端檔案的 UID 不在 `100000-165535` 這個對應範圍內 | 主機端 `chown $((100000+容器UID)):$((100000+容器GID))`，或用共用 GID |
| ★★★★★ `lxc_map_ids: newuidmap failed to write mapping` | `lxc.idmap` 三段加總不等於 65536，或 `/etc/subuid`／`/etc/subgid` 沒同步加 | 重算三段並**兩個檔案都要加**，見【2】 |
| ★★★★ bind mount 的容器**不能做快照** | `snapshot feature is not available for bind mounts` 是設計限制 | 移除 bind mount，或改用儲存型掛載點（`mp0: <儲存>:8,mp=/data`） |
| ★★★★★ 備份日誌寫 `excluding bind mount point mp0` | ★★★★★ bind mount **永遠不進 vzdump** | 對主機來源目錄另做備份（`tar --numeric-owner` 或檔案級備份） |
| ★★★★ Docker daemon 起不來 | 沒開 `nesting=1` | `pct set <id> --features nesting=1,keyctl=1` 後重開容器 |
| ★★★★ `driver not supported: overlay2` | rootfs 在 ZFS subvol 上，overlay2 不支援 | rootfs 換到 LVM-thin／dir，或改用 `fuse-overlayfs`（需 `fuse=1`）；★★★★★ **Docker 建議直接用 VM** |
| ★★★ `pveam download` 找不到範本 | 清單過舊，或對外連不到 | 先 `pveam update`；檢查 DNS 與對外連線 |
| ★★★ `pveam` 下載到一半失敗 | 儲存空間不足或該儲存沒開 `vztmpl` | `pvesm set local --content vztmpl,...`；`df -h /var/lib/vz` |
| ★★★ 容器內 `modprobe: Module xxx not found` | ★★★★ 容器**不能載核心模組**，這是設計 | 在**主機**上 `modprobe`；真的需要就改用 VM |
| ★★★ 容器內 `mount: permission denied`（掛 NFS） | 非特權容器預設不能掛網路檔案系統 | ★★★★ 在**主機**掛好再 bind mount 進去 |
| ★★★ `pct enter` 後 `apt update` 一直解析失敗 | `--nameserver` 沒設，或沿用主機 DNS 但主機 DNS 不通 | `pct set <id> --nameserver <IP>` 後重開容器 |
| ★★★★ 克隆的兩台容器 SSH 指紋一樣、DHCP 撞 IP | 沒重生 host key 與 machine-id | 與情境四【4】同樣的三件事，容器內也要做 |

**處置步驟**：

【1】★★★★★ UID 對應：先把「同一個檔案，兩邊各自看到什麼」攤開來比。

```bash
# 主機上
$ ls -ln /srv/data
total 4
-rw-r--r-- 1 1000 1000 42 Sep  2 09:10 report.txt      # ★★★★ 主機看到 UID 1000

# 容器內
$ pct exec 201 -- ls -ln /data
-rw-r--r-- 1 65534 65534 42 Sep  2 09:10 report.txt     # ★★★★★ 變成 nobody(65534)
```

★★★★★ 為什麼？主機 UID 1000 **不在** `100000-165535` 這個範圍內，
容器無法把它映射成任何一個容器內的 UID，只好顯示成 `nobody`。

★★★★ 最簡單的解法：把主機端檔案的擁有者改成「容器內想要的 UID + 100000」。

```bash
# 想讓容器內的 UID 1000 擁有它 → 主機端要是 101000
$ sudo chown -R 101000:101000 /srv/data
$ ls -ln /srv/data
-rw-r--r-- 1 101000 101000 42 Sep  2 09:10 report.txt
$ pct exec 201 -- ls -ln /data
-rw-r--r-- 1 1000 1000 42 Sep  2 09:10 report.txt        # ★★★★★ 對上了
```

★★★★ 另一種做法：**共用 GID**（適合主機與容器都要存取的目錄）。

```bash
# 主機建一個群組，GID 用容器映射範圍外的值也可以，只要兩邊都設定
$ sudo groupadd -g 101000 ctshare
$ sudo chgrp -R 101000 /srv/data && sudo chmod -R g+rwX,g+s /srv/data
$ pct exec 201 -- usermod -aG 1000 www-data   # 容器內把服務帳號加進對應的 GID
```

【2】★★★★★ 真的需要「容器內 UID = 主機 UID」時，才動 `lxc.idmap`。

★★★★★ 三個規則，違反任何一個容器都起不來：

```text
① 三段（或更多段）的 count 加總，一定要正好等於 65536
② /etc/subuid 與 /etc/subgid **兩個檔案都要加**，只加一個一定失敗
③ 改完要重開容器（pct stop 再 pct start），不是 reboot
```

範例：讓容器內的 UID 1000 直接對應主機的 UID 1000。

```bash
$ vi /etc/pve/lxc/201.conf
# 加在檔案最後
lxc.idmap: u 0 100000 1000
lxc.idmap: g 0 100000 1000
lxc.idmap: u 1000 1000 1
lxc.idmap: g 1000 1000 1
lxc.idmap: u 1001 101001 64535
lxc.idmap: g 1001 101001 64535
#   驗算：1000 + 1 + 64535 = 65536  ★★★★★ 一定要自己算一次

$ grep root /etc/subuid /etc/subgid
/etc/subuid:root:100000:65536
/etc/subgid:root:100000:65536
$ echo 'root:1000:1' | sudo tee -a /etc/subuid
$ echo 'root:1000:1' | sudo tee -a /etc/subgid     # ★★★★★ 兩個都要加

$ pct stop 201 && pct start 201
$ pct exec 201 -- ls -ln /data
-rw-r--r-- 1 1000 1000 42 Sep  2 09:10 report.txt
```

失敗時的錯誤長這樣，看到就回去檢查上面三個規則：

```text
lxc_map_ids: 245 newuidmap failed to write mapping "newuidmap: uid range [1000-1001) -> [1000-1001) not allowed"
```

> [!danger] ★★★★★ 不要手動把 `unprivileged: 1` 改成 `0`
> 「權限有問題就改成特權容器」是最糟的解法 —— 特權容器裡的 root **就是主機的 root**，
> 容器逃逸的後果是整台主機失守。而且直接改設定檔並不會重新對應既有檔案的擁有者，
> 容器多半會直接起不來。
> ★★★★★ 正確做法：非特權容器 + 正確的 UID 對應；真的需要特權才做得到的事，**改用 VM**。

【3】★★★★ LXC 裡跑 Docker：★★★★★ **能用 VM 就用 VM**。

```bash
$ pct config 201 | grep features
features: nesting=1,keyctl=1                   # ★★★★ 兩個都要
$ pct exec 201 -- docker info 2>&1 | head -5
Client: Docker Engine - Community
ERROR: Cannot connect to the Docker daemon at unix:///var/run/docker.sock.
$ pct exec 201 -- journalctl -u docker --no-pager | tail -5
failed to start daemon: error initializing graphdriver: driver not supported: overlay2
```

```text
沒有 nesting=1        → pct set 201 --features nesting=1,keyctl=1 後 pct stop/start
有 nesting 但 overlay2 不支援 → rootfs 在 ZFS subvol 上
    解法 A（★★★★★ 建議）：改用 VM 跑 Docker
    解法 B：rootfs 移到 LVM-thin 或 dir 型儲存
    解法 C：features 加 fuse=1，Docker 改用 fuse-overlayfs（★★★ 效能較差）
```

★★★★★ 為什麼建議用 VM：LXC 跑 Docker 是「容器裡再開容器」，
cgroup、AppArmor、seccomp、儲存驅動每一層都有例外要處理，
而且升級 PVE 之後常常又壞一次。教學環境更是如此，見
[[050-01-03-13-guide-PVE-建立練習環境]]。

【4】★★★ 範本下載：三步就能定位。

```bash
$ pveam update
update successful
$ pveam available --section system | head -5
system          debian-12-standard_12.7-1_amd64.tar.zst
system          ubuntu-24.04-standard_24.04-2_amd64.tar.zst
$ pveam download local debian-12-standard_12.7-1_amd64.tar.zst
downloading http://download.proxmox.com/images/system/debian-12-standard_12.7-1_amd64.tar.zst
calculating checksum...OK, checksum verified
$ pveam list local
NAME                                                         SIZE
local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst        128.15MB
```

```text
pveam update 就失敗        → 對外連線或 DNS：ping download.proxmox.com、cat /etc/resolv.conf
available 有但 download 失敗 → 空間不足（df -h /var/lib/vz）或 local 沒開 vztmpl 內容類型
下載成功但建容器說 no such volume → ★★★★ 檔名版本號抄錯，用 pveam list 複製實際檔名
```

【5】★★★★ 「這不是故障，是設計」的清單 —— 遇到這些不要修，改用 VM。

| 你想做的事 | LXC 能不能 | 怎麼辦 |
| --- | --- | --- |
| ★★★★ 載入自己的核心模組 | ★★★★★ 不能 | 在主機 `modprobe`；需要自己核心的服務改用 VM |
| ★★★★ 改核心參數（`sysctl` 大部分） | ★★★★ 多數不能 | 在主機改；容器只有少數 namespace 化的參數可改 |
| ★★★★ 掛 NFS／CIFS | ★★★★ 非特權預設不能 | ★★★★★ 主機掛好再 bind mount 進去 |
| ★★★★ 跑自己的防火牆規則（iptables/nft） | ★★★ 受限 | 用 PVE 的容器層防火牆 |
| ★★★★ 跑 Docker／Kubernetes | ★★★ 勉強可以但問題多 | ★★★★★ 用 VM |
| ★★★ 用 systemd 管理全部服務 | ★★★★ 可以（用 standard 範本） | 用 `pct enter` 不要用 `pct exec` 進去操作 |

**原理詳見** [[050-01-03-04-guide-PVE-LXC容器管理]]（特權與非特權、idmap、
掛載點型別、features 的完整說明）。

**預防**：
- ★★★★★ 一律用**非特權容器**；需要特權才能做的事，那件事就該用 VM 做
- ★★★★★ 需要主機與容器共用資料時，建置當下就決定 UID 對應方式並**寫進文件**
- ★★★★★ 有 bind mount 的容器，**備份策略要另外規劃** —— vzdump 不會備到它
- ★★★★ 容器範本下載後記下確切檔名，建置腳本用變數帶入，不要每次手打

### ★★★★ 情境六：改壞網路，把自己鎖在外面

**現象**：★★★★★ 這是 PVE 最常見、也最容易造成「要跑一趟機房」的故障。

```text
按下 Apply Configuration（或 ifreload -a）之後：
  SSH 斷線、8006 打不開、ping 不到 —— 而且 VM 可能還在跑
```

> [!danger] ★★★★★ 動網路設定之前，先確認你有第二條路
> 沒有 IPMI／iDRAC／iLO／實體螢幕鍵盤、也沒有第二張管理網卡，
> **就不要改網路設定** —— 你只會有一次機會。
> 最低限度的保險：改之前 `cp -a /etc/network/interfaces /root/interfaces.$(date +%F-%H%M).bak`，
> 並且在另一個終端開一個 `sleep 600 && cp -a /root/interfaces.<備份> /etc/network/interfaces && ifreload -a`
> 的定時還原（★★★★ 確認新設定沒問題後記得把它殺掉）。

**判斷分流**：★★★★★ 已經斷線時，唯一的路是從主控台進去。

```text
還連得上（改之前）    →【1】先用 dry-run 驗語法，再套用
已經斷線               →【2】從 IPMI／實體主控台進去還原
主機通但 VM 不通       →【3】VLAN 與 bridge
時通時不通             →【4】bond 兩端不一致
改了 IP 之後後台進不去 →【5】/etc/hosts 沒同步改
```

**可能原因**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ Web 介面改完網路「完全沒反應」 | PVE 把變更寫進 `interfaces.new`，要按 **Apply Configuration** 才生效 | 按 Apply；或 shell 下 `ifreload -a` |
| ★★★★★ `ifreload -a` 之後整台失聯 | 管理 IP 掛錯介面、bridge port 打錯、native VLAN 對不上 | 從主控台還原備份再 `ifreload -a` |
| ★★★★ `ifreload` 報 `unsupported ... mode` 之類語法錯 | `/etc/network/interfaces` 拼字或縮排錯 | ★★★★★ `ifreload -a -n` 先做 dry-run |
| ★★★★★ VM 設了 `tag=` 完全不通 | `bridge-vlan-aware` 沒開、或交換器 trunk 沒放行該 VLAN | `bridge vlan show` 確認；交換器端確認 trunk 清單 |
| ★★★★★ 節點管理 IP 不通但 VM 的 VLAN 都正常 | ★★★★★ 交換器 trunk 的 **native VLAN 設錯** | 把 native VLAN 改成管理 VLAN |
| ★★★★★ bond 設 `802.3ad` 但交換器沒設 LAG | ★★★★★ MAC 在兩個埠之間跳動，時通時不通 | 立刻改回 `active-backup`，或把交換器 LAG 設好 |
| ★★★★ `/proc/net/bonding/bond0` 的 Partner MAC 全是 0 | 交換器沒回 LACPDU（沒設 LAG 或設成靜態 on） | 交換器改成 LACP active |
| ★★★★ `ifreload` 報 `RTNETLINK answers: File exists` | 設定了兩個 `gateway` | 只留一個 `gateway`，其餘用 `post-up ip route add` |
| ★★★★ 節點重開機後網路沒起來 | 介面少了 `auto` 那一行，或網卡名稱因硬體變動而改變 | 每個要開機啟用的介面都要有 `auto`；用 `ip -br link` 對名稱 |
| ★★★★ 改了 IP 之後後台連不上（SSH 卻通） | 只改了 `interfaces`，`/etc/hosts` 還是舊 IP | ★★★★★ 兩個檔案要一起改，見【5】 |
| ★★★★ 開了防火牆之後 8006／22 連不上 | 規則寫在 enable 之後，或 `local_network` 判定錯 | 主控台把 `enable` 改回 `0`；**先寫規則再啟用** |
| ★★★★ 遷移 VM 到別節點後網路不通 | 目標節點沒有同名 bridge，或該 bridge 不是 VLAN aware | 所有節點的 bridge 命名與 VLAN aware 設定要一致 |
| ★★★ 大檔案傳輸卡死、小封包正常 | MTU 不一致（單邊開了 Jumbo Frame） | `ping -M do -s 8972 <對端>` 測；全鏈路統一 MTU |

**處置步驟**：

【1】★★★★★ 改之前的三道保命符（做完這三件事再按 Enter）。

```bash
# ① 備份（★★★★★ 這一步不能省）
$ cp -a /etc/network/interfaces /root/interfaces.$(date +%F-%H%M).bak
$ ls -l /root/interfaces.*.bak
-rw-r--r-- 1 root root 812 Sep  2 09:40 /root/interfaces.2026-09-02-0940.bak

# ② dry-run 驗語法（★★★★★ ifupdown2 可以只驗不套用）
$ ifreload -a -n
warning: vmbr1: bridge-ports enp2s0f1: interface does not exist   # ★★★★ 抓到打錯的介面名
#   完全沒有輸出 = 語法沒問題

# ③ 定時自動還原（★★★★ 給自己一個 10 分鐘的後悔期）
$ ( sleep 600; cp -a /root/interfaces.2026-09-02-0940.bak /etc/network/interfaces; ifreload -a ) &
[1] 24817
#   確認新設定沒問題之後，記得殺掉：kill %1
```

★★★★ 確認之後才套用：

```bash
$ ifreload -a
$ ip -br a
lo               UNKNOWN  127.0.0.1/8
enp1s0           UP
vmbr0            UP       192.168.10.10/24
vmbr1            UP
$ ip route get 1.1.1.1
1.1.1.1 via 192.168.10.254 dev vmbr0 src 192.168.10.10
```

【2】★★★★★ 已經斷線：從 IPMI／實體主控台進去，**先還原再查原因**。

```bash
# 在主控台（tty）以 root 登入
# ① 先看現在長什麼樣
$ ip -br a
lo      UNKNOWN  127.0.0.1/8
enp1s0  DOWN
vmbr0   DOWN                       # ★★★★★ 管理介面根本沒起來

# ② 直接還原備份（★★★★★ 不要在斷線狀態下慢慢除錯，先恢復連線）
$ ls -t /root/interfaces.*.bak | head -1
/root/interfaces.2026-09-02-0940.bak
$ cp -a /root/interfaces.2026-09-02-0940.bak /etc/network/interfaces
$ ifreload -a
$ ip -br a show vmbr0
vmbr0   UP   192.168.10.10/24       # ★★★★ 回來了

# ③ 沒有備份時的緊急手動恢復（★★★ 只是暫時，重開機會失效）
$ ip addr add 192.168.10.10/24 dev vmbr0
$ ip link set vmbr0 up
$ ip route add default via 192.168.10.254
$ ping -c2 192.168.10.254
```

★★★★ 恢復連線之後，才從 SSH 慢慢找原因：

```bash
$ journalctl -u networking -b --no-pager | tail -30
$ diff /root/interfaces.2026-09-02-0940.bak /etc/network/interfaces.new 2>/dev/null
```

★★★ Web 介面改的東西還沒 Apply 時，會留在 `interfaces.new`：

```bash
$ ls -l /etc/network/interfaces*
-rw-r--r-- 1 root root 812 Sep  2 09:40 /etc/network/interfaces
-rw-r--r-- 1 root root 904 Sep  2 09:52 /etc/network/interfaces.new    # ★★★★ 還沒套用
$ rm -f /etc/network/interfaces.new      # ★★★ 確定不要那份變更時才刪
```

【3】★★★★★ VLAN 不通：由下往上三層各查一次，不要跳著猜。

```bash
# ① PVE 的 bridge 是不是 VLAN aware
$ grep -A5 'iface vmbr0' /etc/network/interfaces
iface vmbr0 inet static
        address 192.168.10.10/24
        gateway 192.168.10.254
        bridge-ports enp1s0
        bridge-stp off
        bridge-fd 0
        bridge-vlan-aware yes            # ★★★★★ 沒有這行，tag= 就完全不會生效
        bridge-vids 2-4094

# ② bridge 上實際放行了哪些 VLAN
$ bridge vlan show
port              vlan-id
enp1s0            1 PVID Egress Untagged
                  2-4094
tap101i0          10 PVID Egress Untagged      # ★★★★ VM 101 的 tag=10 有掛上
vmbr0             1 PVID Egress Untagged

# ③ VM 那一側
$ qm config 101 | grep net0
net0: virtio=BC:24:11:xx:xx:xx,bridge=vmbr0,tag=10
```

```text
沒有 bridge-vlan-aware yes  → 加上去，ifreload -a（★★★★ 這會短暫斷網）
bridge vlan show 沒有 tap   → VM 沒開機，或 net0 沒指到這個 bridge
以上都對還是不通            → ★★★★★ 問題在交換器：trunk 有沒有放行 VLAN 10、
                              VLAN 10 在交換器上存不存在
```

★★★★ 交換器端（Juniper JunOS 為主線）：

```text
user@sw> show vlans
Routing instance   VLAN name    Tag    Interfaces
default-switch     mgmt         100    ge-0/0/10.0*
default-switch     app          10     ge-0/0/10.0*

user@sw> show ethernet-switching interface ge-0/0/10
Interface  State  VLAN members  Tag  Blocking
ge-0/0/10  up     mgmt          100  unblocked      # ★★★★★ native VLAN
                  app            10  unblocked
```

> [!info]- Cisco IOS 對照
> ```cisco
> Switch# show interfaces gi0/10 switchport
> Name: Gi0/10
> Administrative Mode: trunk
> Trunking Native Mode VLAN: 100 (mgmt)
> Trunking VLANs Enabled: 10,20,100
> ```
> ★★★★★ 陷阱：`switchport trunk allowed vlan 30` 是**取代**不是附加，
> 打下去會把原本的 10,20,100 全部清掉，整台主機瞬間斷線。
> 要新增一律用 `switchport trunk allowed vlan add 30`。

【4】★★★★ bond：★★★★★ **兩端一定要一致**，這是唯一的規則。

```bash
$ cat /proc/net/bonding/bond0
Bonding Mode: IEEE 802.3ad Dynamic link aggregation
Transmit Hash Policy: layer2+3 (2)
802.3ad info
LACP active: on
Partner Mac Address: 00:00:00:00:00:00          # ★★★★★ 全 0 = 交換器沒回 LACPDU

Slave Interface: enp1s0
MII Status: up
Slave Interface: enp1s1
MII Status: up
```

```text
Partner Mac 全 0                → 交換器沒設 LAG，或設成靜態 mode on
一邊 802.3ad、一邊沒 LAG        → ★★★★★ MAC 在兩個埠之間跳動，時通時不通
不確定交換器那端怎麼設          → ★★★★★ 先用 active-backup（不需要交換器配合）
```

★★★★ 緊急止血：改回 `active-backup`，這個模式**不需要交換器做任何設定**。

```bash
$ vi /etc/network/interfaces
auto bond0
iface bond0 inet manual
        bond-slaves enp1s0 enp1s1
        bond-miimon 100
        bond-mode active-backup            # 原本是 802.3ad
$ ifreload -a -n && ifreload -a
$ grep 'Bonding Mode' /proc/net/bonding/bond0
Bonding Mode: fault-tolerance (active-backup)
```

【5】★★★★ 改管理 IP：★★★★★ **兩個檔案一起改**，只改一個一定出事。

```bash
$ grep -n 'address\|gateway' /etc/network/interfaces
12:        address 192.168.10.10/24
13:        gateway 192.168.10.254
$ grep -n pve01 /etc/hosts
2:192.168.10.10 pve01.lab.local pve01      # ★★★★★ 這一行也要改
```

★★★★★ `/etc/hosts` 沒同步改的後果：`pve-cluster` 起不來 → `/etc/pve` 是空的 →
後台完全打不開（SSH 卻正常）。這正是 12 篇症狀 B 的一個常見成因。

```bash
$ sed -i 's/192\.168\.10\.10 pve01/192.168.10.20 pve01/' /etc/hosts
$ sed -i 's#address 192.168.10.10/24#address 192.168.10.20/24#' /etc/network/interfaces
$ ifreload -a
$ systemctl restart pve-cluster pveproxy pvedaemon
$ ls /etc/pve/ | head -3
authkey.pub
ceph.conf
corosync.conf                                # ★★★★ 有內容 = pmxcfs 掛起來了
```

> [!danger] ★★★★★ 叢集節點不要隨便改 IP 或主機名
> 叢集的 corosync 設定、憑證、`/etc/pve/nodes/<name>/` 全都綁著節點名與 IP。
> 隨手改會造成節點失聯、憑證錯誤、甚至整個叢集散掉，而且**沒有簡單的還原路徑**。
> 一定要改的話，請照 [[050-01-03-07-svc-PVE-叢集與高可用]] 的正式流程走，
> 並先確認每個節點都有備份。

**原理詳見** [[050-01-03-05-guide-PVE-網路設定]]（bridge、VLAN aware、bond 模式、
SDN、PVE 防火牆的完整說明）、[[020-01-16-cmd-Linux-網路基礎指令]]（六層分層排查）。

**預防**：
- ★★★★★ **IPMI 先設好並測過**，再談改網路。這是唯一真正有效的預防
- ★★★★★ 改之前一定 `cp -a` 備份 + `ifreload -a -n` dry-run，兩件事都不能省
- ★★★★ 遠端操作時用「定時自動還原」給自己一個後悔期
- ★★★★ 叢集內**所有節點的 bridge 命名與 VLAN aware 設定要完全一致**，
  否則遷移過去網路就不通
- ★★★ 每次改動後把 `/etc/network/interfaces` 存進版本控制或組態管理，
  見 [[100-02-08-guide-維運-變更管理流程]]

### ★★★★★ 情境七：硬體直通失敗

**現象**：直通是 PVE 最容易「照著網路教學做卻不會動」的功能，
因為它牽涉**韌體 → 核心參數 → 驅動綁定 → VM 設定**四層，任何一層漏掉都無聲失敗。

```text
（A）ls /sys/kernel/iommu_groups/ 是空的
（B）參數加了、重開了，/proc/cmdline 裡卻沒有
（C）VM 啟動報 vfio: group N is not viable
（D）VM 開不起來，或開起來但 guest 內看不到卡
（E）直通成功了，主機的實體螢幕變黑
（F）要遷移／HA 切換時才發現這台搬不走
```

**判斷分流**：★★★★★ 由下往上四層，**每一層都要看到預期輸出才往上走**。

```bash
# 第一層：韌體有沒有開 IOMMU
$ dmesg | grep -e DMAR -e IOMMU | head -5
[    0.024289] DMAR: IOMMU enabled                     # ★★★★★ Intel 看這行
[    0.412771] DMAR-IR: Enabled IRQ remapping in x2apic mode

# 第二層：核心參數有沒有真的傳進去
$ cat /proc/cmdline
BOOT_IMAGE=/boot/vmlinuz-6.8.12-4-pve root=/dev/mapper/pve-root ro quiet intel_iommu=on iommu=pt

# 第三層：群組分得出來嗎
$ ls /sys/kernel/iommu_groups/ | wc -l
28

# 第四層：目標裝置被誰佔著
$ lspci -nnk -s 01:00
01:00.0 VGA compatible controller [0300]: NVIDIA Corporation ... [10de:1b80] (rev a1)
        Subsystem: ...
        Kernel driver in use: vfio-pci                # ★★★★★ 要是 vfio-pci 才對
        Kernel modules: nvidiafb, nouveau
01:00.1 Audio device [0403]: NVIDIA Corporation ... [10de:10f0] (rev a1)
        Kernel driver in use: vfio-pci                # ★★★★★ 同群組的音效也要綁
```

```text
第一層沒有 IOMMU enabled → BIOS 沒開 VT-d / AMD-V + IOMMU →【1】
第二層 /proc/cmdline 沒有 → ★★★★★ 改錯設定檔了 →【2】
第三層群組是空的          → 前兩層其實沒過，回去看
第四層 driver 不是 vfio-pci → 驅動沒綁 →【3】
全部都對但 VM 起不來      →【4】
主機主控台變黑            →【5】★★★★ 這是預期行為
要遷移才發現搬不走        →【6】★★★★★ 這是設計限制
```

**可能原因**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `/sys/kernel/iommu_groups/` 是空的 | BIOS 沒開 VT-d／IOMMU，或核心參數沒生效 | 進 BIOS 開；用 `proxmox-boot-tool status` 確認要改哪個檔 |
| ★★★★★ 參數加了但 `/proc/cmdline` 沒有 | ★★★★★ 改了 `/etc/default/grub` 卻沒 `update-grub`；或改了 `/etc/kernel/cmdline` 卻沒 `proxmox-boot-tool refresh` | 跑對應的套用指令再重開機，見【2】 |
| ★★★★★ `Kernel driver in use: nouveau`（或 `nvidia`、`amdgpu`） | 黑名單或 `vfio.conf` 沒進 initramfs | `update-initramfs -u -k all` 後重開機 |
| ★★★★★ `vfio ...: group 14 is not viable` | ★★★★★ **同 IOMMU 群組裡還有裝置沒綁 vfio-pci** | 把整組成員都綁上，或把卡換到別的插槽 |
| ★★★★ `failed to open /dev/vfio/14: Device or resource busy` | 該裝置已被另一台執行中的 VM 佔用 | 一張卡只能給一台；`qm list` 找出誰在用 |
| ★★★★ `dmesg`：`BAR 3: can't reserve [mem 0x...]` | 韌體 framebuffer（efifb/simplefb）佔住顯示卡記憶體區段 | BIOS 主顯改成內顯或 BMC；仍不行再考慮 `initcall_blacklist=sysfb_init` |
| ★★★★ guest 內 `lspci` 看不到卡 | `machine` 不是 q35，或沒加 `pcie=1` | `qm set <id> --machine q35 --hostpci0 <addr>,pcie=1` |
| ★★★★ VM 卡在 UEFI 畫面 | 沒加 EFI Disk，或 boot order 沒設對 | 加 `--efidisk0`，檢查 `qm config` 的 `boot:` |
| ★★★★ Windows 裝置管理員 **Code 43** | 舊版 NVIDIA 驅動拒絕在 VM 內運作 | ★★★★ 先把驅動更新到新版；必要時 `--cpu host,hidden=1` |
| ★★★ 兩張同型號的卡都被綁走 | `ids=` 是比對**型號**不是插槽 | 改用 `driver_override` 依 PCI 位址綁定 |
| ★★★ 換插槽後 VM 起不來 | PCI 位址變了 | `lspci` 重查位址，`qm set` 改 `hostpci0` |
| ★★★★★ 遷移報 `can't migrate VM with local resources` | ★★★★★ 有 `hostpci` 就**不能線上遷移** | 關機做離線遷移，且目標節點要有同款卡；★★★★★ 直通 VM 不要放進 HA |

**處置步驟**：

【1】★★★★ BIOS：兩個項目都要開，名稱因廠牌而異。

```text
Intel 平台：VT-d（有時叫 Intel Virtualization Technology for Directed I/O）
AMD 平台：  IOMMU（有時在 NBIO 或 AMD CBS 選單底下）+ SVM Mode
另外常見的兩個：ACS Enable（影響群組拆分）、Above 4G Decoding（大顯存的卡需要）
★★★★ 存檔後「完整斷電再上電」，有些機種熱重開不會重新初始化 IOMMU
```

【2】★★★★★ 核心參數：**先確認自己是哪一種開機方式**，改錯檔案是最常見的失敗。

```bash
$ proxmox-boot-tool status
System currently booted with uefi
1234-5678 is configured with: uefi (versions: 6.8.12-4-pve)
```

| 上面顯示 | 改這個檔 | 套用指令 |
| --- | --- | --- |
| ★★★★★ `configured with: uefi`（systemd-boot，多為 ZFS root） | `/etc/kernel/cmdline` | `proxmox-boot-tool refresh` |
| ★★★★★ `configured with: grub` 或指令不存在 | `/etc/default/grub` 的 `GRUB_CMDLINE_LINUX_DEFAULT` | `update-grub` |

```bash
# systemd-boot 的機器
$ cat /etc/kernel/cmdline
root=ZFS=rpool/ROOT/pve-1 boot=zfs intel_iommu=on iommu=pt
$ proxmox-boot-tool refresh

# GRUB 的機器
$ grep GRUB_CMDLINE_LINUX_DEFAULT /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="quiet intel_iommu=on iommu=pt"
$ update-grub

$ reboot
# 重開後一定要驗
$ cat /proc/cmdline | tr ' ' '\n' | grep -E 'iommu'
intel_iommu=on
iommu=pt                                    # ★★★★★ 沒看到就是沒生效，不要往下做
```

★★★ AMD 平台參數是 `amd_iommu=on`；新核心多數情況下 Intel 已預設啟用 IOMMU，
但**明確寫上去比較不會有版本差異的困擾**。

【3】★★★★★ 綁定 vfio-pci：先看群組成員，**整組一起綁**。

```bash
# 列出每個群組有哪些裝置
$ for g in /sys/kernel/iommu_groups/*/devices/*; do
    n=${g#*/iommu_groups/}; n=${n%%/*}
    printf 'group %s: %s\n' "$n" "$(lspci -nns ${g##*/} | cut -c1-90)"
  done | sort -V | grep -E '^group (14|15):'
group 14: 01:00.0 VGA compatible controller [0300]: NVIDIA Corporation [10de:1b80]
group 14: 01:00.1 Audio device [0403]: NVIDIA Corporation [10de:10f0]
#   ★★★★★ 群組 14 有兩個裝置 → 兩個都要綁，否則 group is not viable
```

```bash
# ① 黑名單原生驅動
$ cat >> /etc/modprobe.d/blacklist-gpu.conf <<'EOT'
blacklist nouveau
blacklist nvidia
blacklist nvidiafb
blacklist snd_hda_intel
EOT

# ② 指定 vfio-pci 接管（ids 用上面 lspci 顯示的 [廠商:裝置] 碼）
$ echo 'options vfio-pci ids=10de:1b80,10de:10f0 disable_vga=1' > /etc/modprobe.d/vfio.conf

# ③ ★★★★★ 一定要重建 initramfs，否則上面兩個檔案根本不會被讀到
$ update-initramfs -u -k all
$ proxmox-boot-tool refresh          # ★★★★ systemd-boot 的機器多這一步
$ reboot

# ④ 驗證
$ lspci -nnk -s 01:00
        Kernel driver in use: vfio-pci
        Kernel driver in use: vfio-pci
```

★★★ 兩張同型號的卡只想綁其中一張時，`ids=` 沒辦法分辨（它比對型號），
改用 `driver_override` 依 PCI 位址綁：

```bash
$ echo vfio-pci > /sys/bus/pci/devices/0000:01:00.0/driver_override
$ echo 0000:01:00.0 > /sys/bus/pci/drivers/nouveau/unbind 2>/dev/null
$ echo 0000:01:00.0 > /sys/bus/pci/drivers_probe
#   ★★★ 這是暫時的，要持久化請寫成 systemd unit 在開機時執行
```

> [!warning] ★★★★★ `pcie_acs_override` 不是萬用解
> 網路上很多教學會叫你加 `pcie_acs_override=downstream,multifunction` 來強制拆群組。
> 這個參數是**繞過硬體的隔離保證**，等於告訴核心「假裝這些裝置彼此隔離」。
> 在實驗環境可以，但**正式環境不建議** —— 它會讓 VM 有機會存取到不該存取的記憶體。
> 正解是：把卡換到獨立群組的插槽，或換一張主機板／CPU。

【4】★★★★ VM 設定：三個參數缺一不可。

```bash
$ qm stop 120
$ qm set 120 --machine q35 --bios ovmf
$ qm set 120 --efidisk0 local-lvm:1,efitype=4m,pre-enrolled-keys=0
$ qm set 120 --hostpci0 0000:01:00,pcie=1        # ★★★★ 不寫功能號 = 整張卡的所有功能
$ qm start 120
$ qm config 120 | grep -E 'machine|bios|hostpci|efidisk'
bios: ovmf
efidisk0: local-lvm:vm-120-disk-1,efitype=4m,pre-enrolled-keys=0,size=528K
hostpci0: 0000:01:00,pcie=1
machine: q35
```

開不起來時，★★★★★ **去看任務日誌的原文**，摘要會被截斷：

```bash
$ qm start 120
TASK ERROR: start failed: QEMU exited with code 1
$ ls -t /var/log/pve/tasks/*/ | head
$ grep -rl "vfio" /var/log/pve/tasks/ | head -1 | xargs tail -20
vfio 0000:01:00.0: group 14 is not viable
Please ensure all devices within the iommu_group are bound to their vfio bus driver.
#   → 回到【3】，把群組成員全部綁上
```

【5】★★★★ 主機主控台變黑：★★★★★ **這是預期行為，不是故障**。

顯示卡被 vfio-pci 接管之後，主機就不再往那張卡輸出畫面了。
之後管理這台機器一律走 **SSH 或 BMC/IPMI 的遠端主控台**。

★★★★★ 所以：**沒有 IPMI 的機器不要直通唯一一張顯示卡** ——
出事的時候你會連畫面都看不到。

【6】★★★★★ 直通的代價：**這台 VM 從此綁死在這個節點上**。

```bash
$ qm migrate 120 pve02 --online
2026-09-02 10:12:03 ERROR: migration aborted: can't migrate VM with local resources: hostpci0
```

| 你失去了什麼 | 說明 |
| --- | --- |
| ★★★★★ 線上遷移 | 有 `hostpci` 就不能 live migrate，沒有例外 |
| ★★★★ 離線遷移 | 可以，但目標節點必須有**同款卡且 PCI 位址對得上** |
| ★★★★★ HA | 切過去的節點沒有那張卡就開不起來 → **直通 VM 不要放進 HA 群組** |
| ★★★★ 記憶體超配 | 直通會 pin 住整份記憶體，balloon 形同無效 → `--balloon 0` 並如實規劃容量 |
| ★★★ 主機維護 | 要重開主機就一定得停這台 VM，沒有繞道 |

★★★★★ 因此**在決定直通之前**就要回答：這個服務可以接受「單點、不能遷移、
維護要停機」嗎？不能的話，改用 SR-IOV（把一張卡切成多個 VF）或乾脆別虛擬化。
選型的取捨見 [[050-01-01-03-ref-虛擬化-五平台橫向對照]]。

**原理詳見** [[050-01-03-10-guide-PVE-硬體直通與GPU]]（IOMMU、群組、vfio、
GPU 與 SR-IOV 的完整流程）。

**預防**：
- ★★★★★ 直通規劃階段就確認：**這台機器有 IPMI 嗎？** 沒有就不要直通唯一的顯示卡
- ★★★★★ 買硬體之前先確認 IOMMU 群組能不能拆得開（同一張主機板不同插槽差很多）
- ★★★★ 直通的 VM 在資產表上標註「不可遷移、不進 HA」，交接時一定要講
- ★★★★ 每次核心升級後重新驗證 `/proc/cmdline` 與 `lspci -nnk`，
  升級可能讓 initramfs 或參數失效

### ★★★★★ 情境八：升級之後回不去

**現象**：升級本身「看起來成功了」，問題出在重開機之後。

```text
（A）重開機後主機完全失聯，ping 不到
（B）開機停在核心 panic 或進不了系統
（C）pveversion -v 顯示版本混雜，一半新一半舊
（D）Web 後台連不上，或憑證錯誤
（E）VM 開不起來，說某個 QEMU 參數不支援
（F）想退回舊版，發現退不了
```

> [!danger] ★★★★★ 升級前沒有做到這四件事，就不要按 Enter
> ① **有可還原的備份**（不是快照，是備份），而且**驗證過還原得回來**；
> ② 有 IPMI 或實體主控台可以進去；
> ③ 用 `screen` 或 `tmux` 跑升級 —— SSH 一斷，套件停在半途；
> ④ 跑過官方的升級檢查工具並清掉所有 `FAIL`。
> ★★★★★ Debian 系**不支援降級**。升級是單行道，你唯一的退路是「還原備份」。

**判斷分流**：

```text
主機完全失聯               →【1】從主控台看是網路還是系統沒起來
停在 panic / 進不了系統    →【2】選舊核心開機
版本混雜、套件半舊半新     →【3】把升級跑完
後台連不上、憑證錯         →【4】
VM 開不起來                →【5】舊設定用了新版移除的選項
真的救不回來               →【6】還原備份（★★★★★ 這才是主要退路）
```

**可能原因**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 升級後主機失聯 | 設定檔衝突時誤按 `Y` 覆蓋了 `/etc/network/interfaces` | 從主控台用 `/etc/network/interfaces.dpkg-old` 還原後 `ifreload -a` |
| ★★★★★ 重開機進不了系統 | 新核心與硬體或驅動不合 | 開機選單選舊核心；進系統後 `proxmox-boot-tool kernel pin <舊版本>` |
| ★★★★★ 升級中途 SSH 斷線，套件停半路 | 沒用 screen／tmux | `dpkg --configure -a` → `apt -f install` → `apt dist-upgrade` 續做 |
| ★★★★★ `apt dist-upgrade` 一堆套件 `held back` | 用了 `apt upgrade`（不會裝新相依），或套件庫 codename 只改了一半 | 逐行檢查所有 `.list`／`.sources`；`apt-mark showhold` |
| ★★★★ `pveversion -v` 版本混雜 | 升級不完整 | `apt update && apt dist-upgrade` 再跑一次；仍不行看 `apt -f install` |
| ★★★★ 後台連不上（8006） | pveproxy 沒起來，或憑證檔壞了 | `journalctl -u pveproxy -n 50`；必要時 `pvenode cert delete` 退回自簽 |
| ★★★★ VM 開不起來，QEMU 說參數不支援 | 舊設定用了新版移除的選項 | 看 `qm start <id>` 的原文錯誤，對照官方升級指引的「移除的功能」 |
| ★★★★ 安全性修補上了但 VM 仍受影響 | `pve-qemu-kvm` 更新後 VM 沒重建行程 | ★★★★★ 關機再開機（不是 Reboot），或遷移到已更新的節點 |
| ★★★★★ 兩節點叢集升級時 `/etc/pve` 變唯讀 | 停掉一台後 Quorum 不成立 | ★★★★★ 事前加 QDevice；緊急處置見 12 篇症狀 D |
| ★★★ 磁碟空間不足導致升級中斷 | `/` 或 `/boot` 滿了 | `apt clean`、清舊核心；升級前確認 `/boot` 至少有 1 GB |

**處置步驟**：

【1】★★★★★ 升級後失聯：九成是設定檔被覆蓋。

```bash
# 從 IPMI 主控台
$ ip -br a
vmbr0   DOWN                                   # ★★★★ 管理介面沒起來
$ ls -l /etc/network/interfaces*
-rw-r--r-- 1 root root  412 Sep  2 03:22 /etc/network/interfaces        # ★★★★★ 變成套件的預設版
-rw-r--r-- 1 root root  812 Aug 15 10:04 /etc/network/interfaces.dpkg-old   # ★★★★★ 你原本的
$ cp -a /etc/network/interfaces.dpkg-old /etc/network/interfaces
$ ifreload -a && ip -br a show vmbr0
vmbr0   UP   192.168.10.10/24
```

★★★★ 順手檢查其他常被覆蓋的檔案：

```bash
$ find /etc -name '*.dpkg-old' -o -name '*.dpkg-dist' -o -name '*.ucf-old' 2>/dev/null
/etc/network/interfaces.dpkg-old
/etc/ssh/sshd_config.dpkg-dist
/etc/chrony/chrony.conf.dpkg-dist
```

> [!warning] ★★★★★ 升級時看到「設定檔衝突」的提示，預設值是「保留現有的」
> 提示會問 `install the package maintainer's version` / `keep the local version`。
> ★★★★★ **一律選保留現有版本（預設的 N）**，升級完再自己 diff 決定要不要合。
> 手滑按 `Y` 就是本情境【1】。

【2】★★★★★ 核心不相容：選舊核心開機，然後**釘住**它。

```bash
# 開機時在 GRUB 選 Advanced options → 選上一個核心版本
# 或 systemd-boot 按向下鍵選舊版本

# 進系統後
$ proxmox-boot-tool kernel list
Manually selected kernels:
None.
Automatically selected kernels:
6.8.12-4-pve
6.8.12-2-pve
$ uname -r
6.8.12-2-pve                                   # 現在跑的是舊的
$ proxmox-boot-tool kernel pin 6.8.12-2-pve
Setting '6.8.12-2-pve' as grub default entry and running update-grub.
$ proxmox-boot-tool kernel list
Manually selected kernels:
6.8.12-2-pve                                   # ★★★★ 釘住了，下次開機還是它
```

★★★★★ 釘住只是**止血**，不是解法。接下來要：查 `journalctl -k -b -1` 找新核心失敗的原因、
回報硬體廠商或 Proxmox 論壇、等修正版出來之後 `proxmox-boot-tool kernel unpin` 解除。

★★★★ 兩件事不要做：

```text
★★★★★ 不要手動 rm /boot/vmlinuz-* 刪核心
    → 套件資料庫不會更新、開機選單會指向不存在的核心
    → 一律 apt autoremove --purge 或 apt purge proxmox-kernel-<版本>
★★★★★ 絕對不要刪掉 uname -r 顯示的那一版
```

【3】★★★★ 版本混雜：把升級**跑完**，不要停在中間。

```bash
$ pveversion -v | head -8
proxmox-ve: 8.2.0 (running kernel: 6.8.12-2-pve)
pve-manager: 8.2.4 (running version: 8.2.4/xxxxxxx)
proxmox-kernel-6.8: 6.8.12-4
pve-qemu-kvm: 8.1.5-6                          # ★★★★ 明顯比其他套件舊
$ apt-mark showhold
$ apt update && apt dist-upgrade
The following packages have been kept back:
  pve-qemu-kvm libpve-storage-perl              # ★★★★★ 有 kept back 就是還沒升完
```

```text
出現 kept back
  → ★★★★★ 一定要用 dist-upgrade（會安裝新的相依套件），apt upgrade 不會
  → 還是不動：apt -f install，看它抱怨什麼
出現套件庫的 codename 不一致（bookworm 混 bullseye）
  → grep -rE 'bullseye|bookworm' /etc/apt/sources.list /etc/apt/sources.list.d/
  → 全部統一成同一個 codename
中斷過的痕跡：dpkg was interrupted
  → dpkg --configure -a 之後再 dist-upgrade
```

【4】★★★★ 後台或憑證：先分清楚是**哪一組憑證**。

```bash
$ systemctl status pveproxy --no-pager | head -5
$ ls -l /etc/pve/nodes/$(hostname)/
-rw-r----- 1 root www-data 1704 Aug 15 10:04 pve-ssl.key       # 叢集內部用
-rw-r----- 1 root www-data 1899 Aug 15 10:04 pve-ssl.pem       # 叢集內部用
-rw-r----- 1 root www-data 3247 Jul 01 09:11 pveproxy-ssl.pem  # ★★★★ 瀏覽器看到的是這個
$ openssl x509 -in /etc/pve/nodes/$(hostname)/pveproxy-ssl.pem -noout -enddate
notAfter=Aug 30 23:59:59 2026 GMT              # ★★★★★ 過期了
```

★★★★ 最快讓後台先能用：退回自簽憑證。

```bash
$ pvenode cert delete                          # 刪掉自訂憑證，退回 PVE 自簽
$ systemctl restart pveproxy
#   瀏覽器會跳「憑證不受信任」，這是預期的，先進得去再說
```

★★★ 節點之間的 API 憑證錯誤（叢集內部那一組）走另一條路：

```bash
$ pvecm updatecerts --force
$ systemctl restart pveproxy pvedaemon
```

詳細分辨方式見 12 篇的症狀 I 與 [[050-01-03-11-svc-PVE-升級與維護]]。

【5】★★★★ VM 開不起來：看原文錯誤，不要猜。

```bash
$ qm start 130
TASK ERROR: start failed: QEMU exited with code 1
$ qm showcmd 130 --pretty | head -20            # ★★★★ 看 PVE 實際組出來的 QEMU 指令
$ grep -rl "130" /var/log/pve/tasks/ | head -1 | xargs tail -15
qemu-system-x86_64: -device ...: Parameter 'xxx' is not supported
```

★★★★ 對照官方升級指引的「已移除的功能」章節，把 `qm set` 改掉那個選項。

【6】★★★★★ 真的救不回來：**還原備份，這才是升級的正式退路**。

```bash
# 從備份還原到一個新的 VMID（★★★★★ 不要覆蓋，先開起來確認）
$ ls /mnt/pve/backup-nas/dump/ | grep vzdump-qemu-130
vzdump-qemu-130-2026_09_01-02_00_03.vma.zst
$ qmrestore /mnt/pve/backup-nas/dump/vzdump-qemu-130-2026_09_01-02_00_03.vma.zst 930 --unique
restore vma archive: ...
progress 100% (read 214748364800 bytes, duration 812 sec)
$ qm start 930
```

> [!danger] ★★★★★ 主機層級的「降級」在 Debian 系是行不通的
> `apt install <套件>=<舊版本>` 對零星套件或許可行，但整套 PVE 有數十個互相依賴的套件，
> 強行降級會做出一個**沒有人測過、也沒有人能支援**的狀態，而且很可能讓 `/etc/pve` 起不來。
> ★★★★★ 主機層真正的退路只有兩條：**重灌 + 還原設定與 VM 備份**，
> 或**先在另一台機器驗證新版本再升級**（有備援節點就一台一台來）。

**原理詳見** [[050-01-03-11-svc-PVE-升級與維護]]（升級前檢查、套件庫切換、
核心管理、憑證與 ACME 的完整流程）、[[020-01-14-guide-Linux-套件管理]]（apt 的行為）。

**預防**：
- ★★★★★ 升級前**驗證過**的備份，而不是「應該有備份」——見情境九【5】
- ★★★★★ 一律用 `screen`／`tmux` 跑升級；設定檔衝突一律選「保留現有版本」
- ★★★★★ 叢集**一次升一台**，升完驗證再升下一台；兩節點叢集先加 QDevice
- ★★★★ 升級前跑官方檢查工具（PVE 7→8 是 `pve7to8 --full`），把所有 `FAIL` 清掉
- ★★★★ 先在測試環境升一次，把踩到的坑寫進自己的升級 SOP
  （[[100-02-08-guide-維運-變更管理流程]]）

### ★★★★ 情境九：備份與還原失敗

> [!note] ★★★★ 這一段跟 12 篇的分工
> [[050-01-03-12-guide-PVE-故障排除]] 的**症狀 H** 處理「排程備份跑失敗」的即時排錯
> （日誌怎麼看、鎖怎麼解、fsfreeze 逾時）。本情境處理的是**還原這一側**與
> **規劃層面的失敗**：還原到錯的 VMID、還原後撞 IP、以及最致命的「從來沒測過還原」。

**現象**：

```text
（A）備份目的地滿了，保留策略設了卻沒生效
（B）備份留下的鎖沒解開，之後每次備份都失敗
（C）還原時說 VM already exists，或還原到了正在用的 VMID
（D）還原成功、開機之後跟正式機撞 IP，把正式服務也弄掛
（E）★★★★★ 要救援時才發現，這三年的備份一份都還原不了
```

**可能原因**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `no space left on device` | 備份目的地滿、或保留策略沒設 | `--prune-backups keep-last=N,keep-daily=N`；★★★★ 空間要監控告警 |
| ★★★★ 保留策略設了但檔案沒被刪 | 策略設在 job 上，手動備份不吃它；或 PBS 需要跑 GC 才回收空間 | 手動 `vzdump --prune-backups`；PBS 設定定期 garbage collection |
| ★★★★ `VM is locked (backup)` / `CT is locked (backup)` | 上次備份異常中斷留下鎖 | ★★★★★ **先確認真的沒有備份在跑**，再 `qm unlock <id>` / `pct unlock <id>` |
| ★★★★★ `unable to restore - VM 101 already exists` | 還原目標 VMID 已存在 | ★★★★★ **換一個空的 VMID**；`--force` 會直接刪掉現有那台 |
| ★★★★★ 還原後兩台 VM 撞 IP、正式服務跟著掛 | 還原出來的機器 MAC 與 IP 跟正式機一樣，開機就上線 | ★★★★★ 還原加 `--unique`，**開機前**先改 `bridge=` 或 `tag=` 到隔離網段 |
| ★★★★ 還原後開機停在 `Waiting for network configuration` | guest 內綁的網卡名稱／MAC 變了 | 進 console 改 guest 的網路設定 |
| ★★★★ LVM-thin 上備份到一半失敗，之後儲存變唯讀 | ★★★★★ 臨時快照撐爆 thin pool | 擴 pool 或減少同時備份的數量，見情境二【2】 |
| ★★★★ `vma extract` 失敗，說開不了檔 | ★★★ `.vma.zst` 要**先解壓縮**才能 extract | `zstd -d file.vma.zst -o file.vma` 之後再 `vma extract` |
| ★★★★★ 備份靜靜失敗好幾週沒人發現 | 沒設通知，或通知信被擋 | 設定通知並**實際測過收得到**；另外接監控 |
| ★★★★★ 備份都在，但還原不回來 | ★★★★★ **從來沒做過還原演練** | 見【5】，這是本情境最重要的一段 |

**處置步驟**：

【1】★★★★ 空間與保留策略：先看清楚「誰在佔空間」。

```bash
$ pvesm status | grep -E 'Name|backup'
Name             Type     Status           Total            Used       Available        %
backup-nas        nfs     active      4194304000      4102291456        92012544   97.81%
$ ls -lhS /mnt/pve/backup-nas/dump/ | head -5
$ ls /mnt/pve/backup-nas/dump/ | sed 's/.*qemu-\([0-9]*\)-.*/\1/' | sort | uniq -c | sort -rn
     42 130                                     # ★★★★ 這台留了 42 份
      7 101
$ vzdump 130 --prune-backups keep-last=3,keep-daily=7,keep-monthly=3 --dumpdir /mnt/pve/backup-nas/dump --stdexcludes 1 --node $(hostname) 2>&1 | head
```

★★★★★ 刪之前一定先 dry-run 看它會刪什麼：

```bash
$ pvesm prune-backups backup-nas --dry-run 1 --keep-last 3 --keep-daily 7 --keep-monthly 3 --vmid 130
VMID  TYPE  BACKUP-TIME          MARK
130   qemu  2026-09-01 02:00:03  keep
130   qemu  2026-08-31 02:00:04  keep
130   qemu  2026-06-14 02:00:02  remove       # ★★★★ 確認這些真的可以刪再實際執行
```

【2】★★★★★ 解鎖：**順序不能顛倒**。

```bash
# ① 先確認真的沒有備份在跑
$ pgrep -a vzdump
$ ls -l /var/log/vzdump/ | tail -3
$ pvesh get /nodes/$(hostname)/tasks --limit 5 --typefilter vzdump

# ② 確認沒有之後才解鎖
$ qm unlock 130
$ qm config 130 | grep -c '^lock:'
0
```

> [!danger] ★★★★★ 備份還在跑的時候 `qm unlock`，會毀掉備份檔與 VM 磁碟的一致性
> 解鎖只是把 `lock:` 那一行拿掉，它**不會**停止正在跑的備份。
> 兩個程序同時操作同一顆磁碟，結果是備份檔不可用、而且 VM 的磁碟可能不一致。
> ★★★★★ `pgrep -a vzdump` 沒有輸出，才可以解鎖。

【3】★★★★★ 還原：**永遠先還原到一個空的 VMID**。

```bash
# ① 先確認目標 VMID 是空的
$ qm status 930 2>&1
Configuration file 'nodes/pve01/qemu-server/930.conf' does not exist    # ★★★★ 空的，可以用

# ② 還原（--unique 會重新產生 MAC，避免撞網路）
$ qmrestore /mnt/pve/backup-nas/dump/vzdump-qemu-130-2026_09_01-02_00_03.vma.zst 930 \
    --storage local-lvm --unique
restore vma archive: zstd -q -d -c ... | vma extract -v -r /var/tmp/vzdumptmp... 
progress 100% (read 107374182400 bytes, duration 412 sec)
successfully imported 'local-lvm:vm-930-disk-0'

# ③ ★★★★★ 開機之前先把網路切到隔離網段
$ qm set 930 --net0 virtio,bridge=vmbr9          # vmbr9 = 沒有上聯的隔離橋接
$ qm set 930 --onboot 0 --name restore-test-130
$ qm start 930
```

> [!danger] ★★★★★ `qmrestore --force` 會直接刪掉目標 VMID 上現有的那台
> 沒有二次確認、沒有回收桶。打錯一個數字，被覆蓋的是**正在提供服務的正式機**。
> ★★★★★ 規則：還原一律用新的、確定沒人用的 VMID（例如統一用 9xx 當還原測試區），
> 確認新機器沒問題之後，才用正常流程把服務切過去。
> `pct restore` 與 `pct destroy`、`qm destroy` 同樣沒有回頭路。

【4】★★★★ 還原後撞 IP：這是「還原成功卻造成更大事故」的典型。

```text
★★★★★ 還原出來的機器，開機的那一刻就會：
  ① 用跟正式機一樣的 IP 上線 → 正式服務開始時通時不通
  ② 用跟正式機一樣的 MAC     → 交換器的 MAC 表開始跳動
  ③ 連上正式的資料庫、佇列、AD → 可能寫入正式資料

所以還原的正確順序永遠是：
  還原到新 VMID → 改網路到隔離網段 → 關掉 onboot → 才開機
```

【5】★★★★★ **從來沒測過還原** —— 本篇最重要的一段。

★★★★★ 「有備份」和「還原得回來」是兩件事。備份任務顯示綠色，不代表：
檔案沒有損壞、你有權限讀它、目標儲存放得下、還原出來開得了機、資料是完整的。

★★★★ 每季一次的還原演練，照這五步跑（★★★★ 花不到一小時，但救的是整個機關）：

```bash
# 第 1 步：隨機挑一份「不是最新的」備份（最新的最可能沒問題）
$ ls /mnt/pve/backup-nas/dump/ | shuf -n 1
vzdump-qemu-101-2026_07_18-02_00_05.vma.zst

# 第 2 步：確認檔案本身沒壞（★★★★ 光是這一步就會抓出不少問題）
$ zstd -t /mnt/pve/backup-nas/dump/vzdump-qemu-101-2026_07_18-02_00_05.vma.zst
vzdump-qemu-101-2026_07_18-02_00_05.vma.zst: 107374182400 bytes  OK

# 第 3 步：看得到設定嗎
$ zstd -d -c /mnt/pve/backup-nas/dump/vzdump-qemu-101-2026_07_18-02_00_05.vma.zst | vma config - | head
#qmdump#map:scsi0:drive-scsi0:local-lvm:raw:
boot: order=scsi0
cores: 4
memory: 8192

# 第 4 步：實際還原到測試 VMID 並開機（★★★★★ 這一步不能省，前三步都不算演練）
$ qmrestore <備份檔> 901 --unique --storage local-lvm
$ qm set 901 --net0 virtio,bridge=vmbr9 --onboot 0 --name drill-$(date +%Y%m%d)
$ qm start 901 && sleep 60 && qm status 901
status: running

# 第 5 步：進去驗資料，然後清乾淨
$ qm terminal 901        # 或用 console 登入，檢查應用資料到不到得了「可用」的程度
$ qm stop 901 && qm destroy 901 --purge --destroy-unreferenced-disks 1
```

★★★★★ 演練要**留紀錄**：日期、挑到哪一份、花多久、遇到什麼問題、誰做的。
沒有紀錄的演練，在稽核與事故檢討時等於沒做。表單與流程見
[[100-02-09-svc-維運-事件處理與升級流程]]。

**原理詳見** [[050-01-03-06-svc-PVE-備份與還原]]（備份模式、保留策略、PBS、
還原流程的完整說明）。

**預防**：
- ★★★★★ **每季一次還原演練**並留紀錄 —— 這一項的投資報酬率高於其他所有備份設定
- ★★★★★ 備份通知一定要設，而且**實際測過收得到**；再加一層監控盯備份任務
- ★★★★★ 還原專用的 VMID 區段（例如 900-999）寫進規範，永遠不還原到既有 VMID
- ★★★★ 準備一個沒有上聯的隔離 bridge（`vmbr9`），還原測試一律接它
- ★★★★ 有 bind mount 的 LXC，**另外規劃備份** —— vzdump 不會備到它

### ★★★ 情境十：練習環境把自己搞垮

**現象**：實驗機不會造成資料損失，但**會把實體機的資源吃光，連帶影響正式服務**。

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ 主機重開後一堆練習機自動啟動，資源爆掉 | 建立時沒設 `--onboot 0` | 全部關掉自動啟動，見【1】 |
| ★★★★★ thin pool 用量暴增，正式 VM 跟著變唯讀 | ★★★★★ 練習用的快照沒人清 | `qm listsnapshot` 逐台清，見【2】 |
| ★★★★ 巢狀環境慢到不能用 | ★★★★ 三層巢狀是預期的慢 | 這不是故障；降低期待或改用實體練習機 |
| ★★★ 實驗做完沒清乾淨，下次找不到哪台是哪台 | 沒有命名規則 | 用 `lab-` 前綴與固定 VMID 區段，見【3】 |
| ★★★ 練習機跟正式機在同一個 bridge，撞 IP | 沒有隔離網段 | 練習一律接沒有上聯的 `vmbr9` |
| ★★★ 清理腳本刪不掉某一台 | 有鎖或有快照 | `qm unlock <id>`；`--purge` 已含刪快照 |

**處置步驟**：

【1】★★★★ 一次把練習機的自動啟動全關掉。

```bash
$ qm list | awk 'NR>1 && $2 ~ /^lab-/ {print $1}' | while read id; do
    qm set $id --onboot 0 && echo "$id onboot=0"
  done
101 onboot=0
$ grep -l '^onboot: 1' /etc/pve/qemu-server/*.conf /etc/pve/lxc/*.conf 2>/dev/null
/etc/pve/qemu-server/101.conf                 # ★★★★ 剩下的都應該是正式機
```

【2】★★★★★ 快照鏈：**練習環境最容易爆的就是這個**。

```bash
$ for id in $(qm list | awk 'NR>1{print $1}'); do
    c=$(qm listsnapshot $id 2>/dev/null | grep -c '`->')
    [ "$c" -gt 0 ] && echo "VM $id: $c 個快照"
  done
VM 101: 2 個快照
VM 902: 17 個快照                              # ★★★★★ 練習機忘了清
$ qm listsnapshot 902
 `-> before-net-lab       2026-08-02 10:14:21
 `-> before-firewall-lab  2026-08-09 09:02:10
 ...
$ qm delsnapshot 902 before-net-lab            # ★★★★ 一個一個刪，每刪一個看 lvs
$ lvs -o lv_name,data_percent,metadata_percent pve/data
```

> [!danger] ★★★★ 快照不是備份
> 快照跟原始磁碟在**同一個 pool**上。pool 壞了、pool 滿了，快照一起沒。
> ★★★★★ 快照的用途是「改壞了馬上回去」，時效以**小時到天**計；
> 需要留一個月以上的，那是備份的工作。

【3】★★★ 清理實驗環境：★★★★★ **先確認 VMID 區段**再動手。

```bash
# ① 先看要刪什麼（★★★★★ 這一步不能跳）
$ qm list | awk '$1 >= 900 && $1 <= 999'
       900 lab-web01            stopped     2048    32.00 0
       902 lab-db01             stopped     4096    64.00 0
$ pct list | awk '$1 >= 900 && $1 <= 999'

# ② 確認清單無誤，才實際刪
$ for id in 900 902; do
    qm stop $id 2>/dev/null
    qm destroy $id --purge --destroy-unreferenced-disks 1
  done
```

> [!danger] ★★★★★ `qm destroy` 與 `pct destroy` 是不可逆的
> `--purge` 會連同備份任務設定、HA 資源、防火牆規則一起清掉；
> `--destroy-unreferenced-disks 1` 會刪掉該儲存上所有名稱屬於這個 VMID 的磁碟。
> **沒有回收桶、沒有二次確認。**
> ★★★★★ 動手前一律先用 `qm list` 把要刪的清單印出來看過，
> 而且**練習機與正式機的 VMID 區段一定要分開**（例如正式 100-499、練習 900-999）。

**原理詳見** [[050-01-03-13-guide-PVE-建立練習環境]]（練習環境的建置、範本、
巢狀虛擬化與資源規劃）。

**預防**：
- ★★★★★ 練習機與正式機**VMID 區段分開**、**命名前綴分開**、**網段分開**
- ★★★★ 建立練習機的指令一律帶 `--onboot 0`，寫進建置腳本
- ★★★★ 快照建立時就在描述欄寫「什麼時候可以刪」，並排一個每月的清理提醒
- ★★★ 練習環境跟正式環境**不要共用同一個 thin pool**，避免互相拖累

## 什麼時候該停手求援

> [!danger] ★★★★★ 以下情況請立刻停止操作 —— 繼續動手會讓災情擴大或證據消失

**【1】★★★★★ 共享儲存上還有其他節點在跑，而你打算下 `pvecm expected 1`**：
這是 PVE 最危險的單一指令。若其他節點其實還活著，兩邊會同時寫同一份資料 →
**split-brain**，共享儲存上的 VM 磁碟直接損毀，而且**還原備份是唯一的路**。
★★★★★ 一定要先用 IPMI／實體確認其他節點**真的關機了**，才可以考慮。
處置流程見 12 篇症狀 D。

**【2】★★★★★ thin pool 的 `Data%` 或 `Meta%` 已經 100%**：pool 可能已進入
error 狀態。★★★★★ **先不要重開機、不要 fsck、不要 `lvremove`** ——
先把還讀得到的 VM 磁碟複製出去，再談修復。修復工具在滿載的 pool 上跑，
很可能把「大部分還讀得到」變成「什麼都讀不到」。

**【3】★★★★★ 下一步是不可逆操作，而你手上沒有驗證過的備份**：
`qm destroy`、`pct destroy`、`zpool destroy`、`lvremove`、`pvecm delnode`、
`rm` 掉 `/etc/pve` 底下的檔案、`wipefs`、`dd`。
★★★★★ 沒有還原得回來的備份，就沒有回頭路 —— 停下來，先想辦法把資料複製出去。

**【4】★★★★★ 你想直接編輯 `/var/lib/pve-cluster/config.db`**：這是 pmxcfs 的資料庫。
直接改它會毀掉整個叢集設定，而且**沒有還原路徑**。
需要在無 Quorum 的情況下改設定，正確做法是 `pmxcfs -l`（local mode），見 12 篇症狀 D-6。

**【5】★★★★★ 判斷不出這是「故障」還是「入侵」**：出現不認識的 VM、
`/etc/pve/user.cfg` 多了沒人承認的帳號或 Token、後台有大量 `authentication failure`、
節點上有不明程序在跑。★★★★★ **不要重開機、不要刪東西、不要「順便清一清」** ——
保存現場並依 [[090-07-04-guide-資安實踐-資安事件應變流程]] 通報。

**【6】★★★★ 災情不只一台**：多個節點同時異常、共享儲存整個不見、
整個機櫃失聯。這時面對的是網路、儲存或電力層級的事件，
繼續在單一節點上找答案只是浪費時間 —— 往上升級成事件處理流程
（[[100-02-09-svc-維運-事件處理與升級流程]]、[[040-02-14-guide-機房-機房異常應變]]）。

**【7】★★★ 同一個問題試超過三十分鐘，而且開始「隨便改改看」**：
★★★★★ 隨機修改會製造新問題，把單一故障變成多重故障，而且沒人知道你動過什麼。
停下來，把做過的每一個動作寫下來，找第二個人一起看。

**【8】★★★ 要在正式環境做不可逆變更，卻沒走變更流程**：即使技術上做得到，
制度上也應該先取得核准與備援計畫（[[100-02-08-guide-維運-變更管理流程]]）。

## 症狀 → 章節 快速索引

★★★★★ 找不到自己的症狀時，用這張表反查該讀哪一篇原文。**本章 13 篇全部涵蓋**。

| 你遇到的事 | 本手冊位置 | 原理篇章 |
| --- | --- | --- |
| ISO 開不起來、安裝黑屏、看不到磁碟、裝完開不了機 | 情境一【1】～【5】 | [[050-01-03-01-svc-PVE-安裝與初始設定]] |
| `apt update` 401、套件庫切換、訂閱提示 | 情境一【6】 | [[050-01-03-01-svc-PVE-安裝與初始設定]] |
| 巢狀環境 KVM 起不來、`pveperf` 極慢 | 情境一【3】 | [[050-01-01-02-guide-虛擬化-虛擬化底層技術]] |
| `local` 爆滿、ISO 與備份塞在根分割 | 情境二【1】 | [[050-01-03-02-guide-PVE-儲存設定]] |
| thin pool `Meta%` 用盡、快照堆積 | 情境二【2】 | [[050-01-03-02-guide-PVE-儲存設定]] |
| thin pool `Data%` 滿、VM 集體變唯讀 | 12 篇 症狀 C | [[050-01-03-02-guide-PVE-儲存設定]] |
| NFS 加不進來、NAS 掉線拖垮後台 | 情境二【3】 | [[050-01-03-02-guide-PVE-儲存設定]] |
| iSCSI 斷線、多節點共用 LUN | 情境二【4】 | [[050-01-03-02-guide-PVE-儲存設定]] |
| ZFS ARC 吃光記憶體、pool 超過 80% 變慢 | 情境二【5】 | [[020-01-24-guide-進階儲存-ZFS與Btrfs]] |
| VirtIO 沒裝、控制器與網卡選錯、磁碟很慢 | 情境三【1】 | [[050-01-03-03-guide-PVE-虛擬機管理]] |
| CPU type 選錯、遷移就當、AES-NI 不見 | 情境三【2】 | [[050-01-03-09-svc-PVE-監控與資源調校]] |
| `cache=unsafe`、快取模式取捨 | 情境三【3】 | [[050-01-03-09-svc-PVE-監控與資源調校]] |
| IO thread、多磁碟互相拖累 | 情境三【4】 | [[050-01-03-09-svc-PVE-監控與資源調校]] |
| balloon 抖動、guest 狂 swap、記憶體超配 | 情境三【5】 | [[050-01-03-09-svc-PVE-監控與資源調校]] |
| cloud-init 沒生效、ci 磁碟沒加、只跑第一次開機 | 情境四【1】【2】 | [[050-01-03-13-guide-PVE-建立練習環境]] |
| `cicustom` 覆蓋、snippets 路徑 | 情境四【3】 | [[050-01-03-13-guide-PVE-建立練習環境]] |
| 範本沒清 machine-id／ssh host key、複製後撞 IP | 情境四【4】 | [[050-01-03-03-guide-PVE-虛擬機管理]] |
| Console 黑畫面（cloud image 序列埠） | 情境四【5】 | [[050-01-03-13-guide-PVE-建立練習環境]] |
| 非特權容器 UID 位移、`nobody:nogroup` | 情境五【1】【2】 | [[050-01-03-04-guide-PVE-LXC容器管理]] |
| LXC 跑 Docker、nesting、overlay2 | 情境五【3】 | [[050-01-03-04-guide-PVE-LXC容器管理]] |
| `pveam` 範本下載失敗 | 情境五【4】 | [[050-01-03-04-guide-PVE-LXC容器管理]] |
| LXC 起不來（error -1）、bind mount 失敗 | 12 篇 症狀 G | [[050-01-03-04-guide-PVE-LXC容器管理]] |
| 改網路把自己鎖在外面、從主控台救回 | 情境六【1】【2】 | [[050-01-03-05-guide-PVE-網路設定]] |
| VLAN aware 沒開、trunk 與 native VLAN | 情境六【3】 | [[050-01-03-05-guide-PVE-網路設定]] |
| bond 兩端不一致、LACP 沒起來 | 情境六【4】 | [[050-01-03-05-guide-PVE-網路設定]] |
| 改管理 IP 之後後台進不去（`/etc/hosts`） | 情境六【5】 | [[050-01-03-05-guide-PVE-網路設定]] |
| IOMMU 沒開、核心參數改錯檔案 | 情境七【1】【2】 | [[050-01-03-10-guide-PVE-硬體直通與GPU]] |
| `group is not viable`、vfio 綁定、initramfs | 情境七【3】 | [[050-01-03-10-guide-PVE-硬體直通與GPU]] |
| 直通後 VM 起不來、主控台變黑 | 情境七【4】【5】 | [[050-01-03-10-guide-PVE-硬體直通與GPU]] |
| 直通後不能遷移、不能進 HA | 情境七【6】 | [[050-01-03-10-guide-PVE-硬體直通與GPU]] |
| 升級後失聯、設定檔被覆蓋 | 情境八【1】 | [[050-01-03-11-svc-PVE-升級與維護]] |
| 核心不相容、`kernel pin`、不要手動刪核心 | 情境八【2】 | [[050-01-03-11-svc-PVE-升級與維護]] |
| 版本混雜、`held back`、升級中斷 | 情境八【3】 | [[050-01-03-11-svc-PVE-升級與維護]] |
| 升級後憑證錯誤、後台連不上 | 情境八【4】、12 篇 症狀 I | [[050-01-03-11-svc-PVE-升級與維護]] |
| 降級回不去、還原備份是唯一退路 | 情境八【6】 | [[050-01-03-06-svc-PVE-備份與還原]] |
| 備份空間、保留策略、prune | 情境九【1】 | [[050-01-03-06-svc-PVE-備份與還原]] |
| 備份鎖沒解、`qm unlock` 的前提 | 情境九【2】、12 篇 症狀 H | [[050-01-03-06-svc-PVE-備份與還原]] |
| 還原到錯的 VMID、`--force` 的風險 | 情境九【3】 | [[050-01-03-06-svc-PVE-備份與還原]] |
| 還原後撞 IP、隔離網段 | 情境九【4】 | [[050-01-03-06-svc-PVE-備份與還原]] |
| ★★★★★ 從來沒測過還原、還原演練五步 | 情境九【5】 | [[050-01-03-06-svc-PVE-備份與還原]] |
| 練習機吃光資源、`onboot`、快照鏈 | 情境十【1】【2】 | [[050-01-03-13-guide-PVE-建立練習環境]] |
| 清理實驗環境、`qm destroy` 的風險 | 情境十【3】 | [[050-01-03-13-guide-PVE-建立練習環境]] |
| 主機開不了機、GRUB、emergency mode | 12 篇 症狀 A | [[020-01-25-guide-Linux-開機流程與GRUB救援]] |
| 後台連不上、pveproxy、狀態全灰 | 12 篇 症狀 B | [[050-01-03-12-guide-PVE-故障排除]] |
| Quorum、pmxcfs、`/etc/pve` 唯讀、節點被 fence | 12 篇 症狀 D | [[050-01-03-07-svc-PVE-叢集與高可用]] |
| 遷移失敗、SSH 金鑰、儲存不同名 | 12 篇 症狀 E | [[050-01-03-07-svc-PVE-叢集與高可用]] |
| VM 開不起來、`no such volume`、`qm rescan` | 12 篇 症狀 F | [[050-01-03-12-guide-PVE-故障排除]] |
| API 403／401、Token `privsep`、AD 登入沒權限 | 本篇未展開 | [[050-01-03-08-guide-PVE-使用者權限與API]] |
| 2FA 被鎖在門外、暴力破解日誌 | 本篇未展開 | [[050-01-03-08-guide-PVE-使用者權限與API]] |
| 本章有哪些篇、建議閱讀順序 | — | [[050-01-03-00-idx-PVE-ProxmoxVE]] |

## 延伸閱讀

**本章各篇（原理都在這裡，本手冊只做索引）**

- [[050-01-03-00-idx-PVE-ProxmoxVE]] —— 本章索引與建議閱讀順序
- [[050-01-03-12-guide-PVE-故障排除]] —— ★★★★★ **服務與叢集層的深度排查**：
  六層分層模型、`pve-triage.sh`、症狀 A～I。本篇是它的上層索引，兩篇配合看
- [[050-01-03-01-svc-PVE-安裝與初始設定]] —— 安裝、套件庫、初始檢查（情境一）
- [[050-01-03-02-guide-PVE-儲存設定]] —— 儲存型別能力矩陣、thin pool、容量規劃（情境二）
- [[050-01-03-03-guide-PVE-虛擬機管理]] —— VirtIO、磁碟參數、複製與範本（情境三、四）
- [[050-01-03-04-guide-PVE-LXC容器管理]] —— 特權與非特權、idmap、features（情境五）
- [[050-01-03-05-guide-PVE-網路設定]] —— bridge、VLAN、bond、PVE 防火牆（情境六）
- [[050-01-03-06-svc-PVE-備份與還原]] —— ★★★★★ 備份模式、保留策略、還原演練（情境九）
- [[050-01-03-07-svc-PVE-叢集與高可用]] —— Quorum、QDevice、HA、遷移
- [[050-01-03-08-guide-PVE-使用者權限與API]] —— ACL、Token、AD 整合、2FA
- [[050-01-03-09-svc-PVE-監控與資源調校]] —— ★★★★★ cache／CPU type／balloon 的取捨（情境三）
- [[050-01-03-10-guide-PVE-硬體直通與GPU]] —— IOMMU、vfio、SR-IOV（情境七）
- [[050-01-03-11-svc-PVE-升級與維護]] —— 升級流程、核心管理、憑證（情境八）
- [[050-01-03-13-guide-PVE-建立練習環境]] —— 範本、cloud-init、巢狀虛擬化（情境四、十）

**排錯時常一起用到的其他章節**

- [[050-01-01-98-trouble-虛擬化-常見故障排除]] —— ★★★★ 平台無關的虛擬化故障
  （選型、授權、資源競爭），跨平台問題先看那份
- [[050-01-01-03-ref-虛擬化-五平台橫向對照]] —— 這件事在別的平台怎麼做
- [[020-01-98-trouble-Linux-常見故障排除]] —— ★★★★★ 主機是 Debian，Linux 層的問題都在那份
- [[020-01-23-guide-Linux-Linux常見疑難排解]] —— 排錯方法論本身
- [[020-01-25-guide-Linux-開機流程與GRUB救援]] —— 主機開不起來（12 篇症狀 A 的原理）
- [[020-01-15-cmd-Linux-磁碟分割與掛載]] —— `df`／`du`／fstab／掛載選項
- [[020-01-24-guide-進階儲存-ZFS與Btrfs]] —— ZFS pool 健康、ARC、快照
- [[020-01-16-cmd-Linux-網路基礎指令]] —— 網路不通的六層分層排查
- [[020-01-19-guide-Linux-日誌系統]] —— `journalctl` 進階與日誌保存
- [[020-01-14-guide-Linux-套件管理]] —— apt 的行為、鎖檔、中斷後的收拾
- [[100-01-03-guide-日誌-系統監控與告警]] —— ★★★★★ 讓 thin pool 與備份在爆炸前就告警
- [[100-01-04-guide-日誌-健康檢查與可用性監控]] —— 節點與儲存的健康檢查
- [[100-02-10-guide-維運-故障排除方法論]] —— 制度層面的排錯流程與記錄要求
- [[100-02-09-svc-維運-事件處理與升級流程]] —— 什麼時候該升級、要通知誰、怎麼記錄
- [[100-02-08-guide-維運-變更管理流程]] —— 改網路、改儲存、升級前的核准與備援計畫
- [[040-02-09-guide-機房-伺服器上架與初始設定]] —— ★★★★★ IPMI 一定要在上架時就設好
- [[040-02-14-guide-機房-機房異常應變]] —— 機房層級的事件（電力、空調、網路）
- [[040-02-04-guide-機房-電力系統與配電]] —— 斷電與冗餘電源
- [[090-07-04-guide-資安實踐-資安事件應變流程]] —— 判斷是「故障」還是「入侵」之後的正式流程

**外部資源**

- Proxmox VE 官方文件（`pve-docs`）：Installation、Storage、Qemu/KVM、
  Linux Container、Network Configuration、PCI(e) Passthrough 各章
- Proxmox VE 官方 wiki：**Upgrade from 7.x to 8.0**、**PCI Passthrough**、
  **Unprivileged LXC containers**、**Cloud-Init Support**
- Debian 官方文件：`apt`、`dpkg`、`ifupdown2` 的行為說明
- LVM 文件：`lvmthin(7)`（★★★★ thin pool 的資料區與中繼資料區）
- OpenZFS 文件：`zpool(8)`、`zfs(8)`、ARC 調校說明
- cloud-init 官方文件：`cloud-config` 模組清單與 NoCloud 資料來源
- Proxmox 官方論壇 —— ★★★★ 搜尋你看到的**錯誤訊息原文**，多數坑有人踩過
