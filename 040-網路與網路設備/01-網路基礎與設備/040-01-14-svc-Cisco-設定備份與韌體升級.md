---
title: "Cisco 設定備份與韌體升級"
desc: "TFTP／SCP 備份、archive 與 configure replace 回滾、kron 排程、IOS 升級與 boot system 回退、reload in 與 configure revert timer"
aliases: [copy running-config tftp, archive, configure replace, configure revert timer, kron, boot system, verify md5, reload in, install add activate commit]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-10-cmd-Cisco-IOS-基礎操作]]", "[[040-01-12-guide-Cisco-管理IP與遠端存取]]"]
updated: 2026-09-02
---

# Cisco 設定備份與韌體升級

> [!note] 本手冊以 Juniper JunOS 為主線
> 網路設備章節**以 Juniper JunOS 為主線**，對應篇是 [[040-01-09-svc-Juniper-設定備份與韌體升級]]。
> Cisco 這一篇是**輔助線**，給接手既有 Catalyst 設備的維運人員用，內容深度不打折。

> [!abstract] 這篇你會學到
> - ★★★★★ **`reload in 5` 是 Cisco 世界的 `commit confirmed`**：
>   為什麼它有效、三個絕對不能搞錯的細節、以及 IOS 12.4(20)T 之後
>   更精準的 `configure terminal revert timer` ＋ `configure confirm`
> - ★★★★★ **升級前後的完整檢查清單與回退流程** —— 舊映像檔留在 flash、
>   兩行 `boot system` 的順序就是你的退路
> - ★★★★ `archive` ＋ `configure replace` ：IOS 內建的設定版本管理與**逐行回滾**，
>   比重開機溫和得多
> - ★★★★ 用 SCP 取代 TFTP：TFTP 是明文 UDP、無認證，而設定檔裡有密碼雜湊與 SNMP 字串
> - ★★★★ `kron` 排程自動備份，以及那個一定會踩的坑：**`file prompt quiet`**
> - ★★★★ `verify /md5` 為什麼是升級流程裡不能省的一步
> - ★★★ IOS-XE 16.x 之後的 install 模式（`install add file ... activate commit`）
>   與傳統 bundle 模式的差別，以及 `auto-abort-timer` 這個內建的 commit confirmed
> - 一份可以直接照做的升級 SOP 與 20 列驗收檢查表

> [!warning] 未實機驗證
> ★★★★★ 本專案**沒有可供驗證的實體 Cisco 設備**。本篇依 Cisco IOS 15.2(7)E
> （Catalyst 2960-X）與 IOS-XE 17.x（Catalyst 9200／9300）的官方命令參考撰寫，
> 輸出為依實際格式重建的**示意輸出**，MD5、檔名、版本號為虛構。
> ★★★★★ **韌體升級是本手冊中風險最高的操作之一**：
> 不同機型、不同版本的升級路徑差異極大（bundle 模式 vs install 模式、
> 堆疊升級、授權變更、必要的中繼版本），
> **動手前必須到 Cisco 官網查該機型該版本的 Release Notes 與 Upgrade Guide**，
> 並確認你手上有 console 存取與可開機的舊映像檔。
> 本篇提供的是**流程與檢查清單**，具體指令請以官方文件為準。

## 前置知識

- [[040-01-10-cmd-Cisco-IOS-基礎操作]] —— running/startup 的差別、
  ★★★★★ `reload in`、`show version`、`show flash:`
- [[040-01-12-guide-Cisco-管理IP與遠端存取]] —— SSH／SCP 的前置設定、AAA
- [[040-01-11-guide-Cisco-VLAN與Trunk設定]] —— ★★★★ `vlan.dat` 不在設定檔裡，
  備份時要另外考慮
- [[020-01-28-cmd-Linux-時間同步NTP與chrony]] —— 備份檔名帶日期的前提
- [[060-01-01-01-guide-Git-觀念與初次設定]] —— ★★★ 設定檔備份納入版本控管
- [[040-01-09-svc-Juniper-設定備份與韌體升級]] —— 主線平台的做法

## 觀念說明

### 要備份的其實有三樣東西 ★★★★

大多數人只備份 `running-config`，那是不夠的：

| 項目 | 存在哪 | `copy run tftp:` 有備份到嗎 | 怎麼備份 | 星級 |
| --- | --- | --- | --- | --- |
| **設定檔** | RAM／NVRAM | ★ 有 | `copy running-config <目的>` | ★★★★★ |
| ★★★★ **VLAN 資料庫** | `flash:vlan.dat` | ★★★★★ **沒有**（VTP server／client 模式下） | `copy flash:vlan.dat tftp:` 或改用 `vtp mode transparent` | ★★★★ |
| ★★★ **IOS 映像檔** | `flash:` | 沒有 | 保留原始下載檔 ＋ 記錄 MD5 | ★★★ |

> [!danger] ★★★★★ `vlan.dat` 是最常被漏掉的一塊
> 在 VTP `server` 或 `client` 模式下，VLAN 的編號與名稱**不會出現在 `running-config`**。
> 你的設定檔備份看起來很完整，但**設備換新之後 VLAN 全部要重建**。
>
> ★★★★★ 最佳解不是「記得備份 vlan.dat」，而是
> **把所有交換器切成 `vtp mode transparent`** ——
> 這樣 VLAN 定義會進 `running-config`，設定檔備份就自然涵蓋了它，
> 而且順便免除了 VTP 誤覆蓋全網 VLAN 的風險。
> 見 [[040-01-11-guide-Cisco-VLAN與Trunk設定]]。

### 傳輸協定怎麼選 ★★★★

| 協定 | 傳輸層 | 認證 | 加密 | 設備端角色 | 評價 |
| --- | --- | --- | --- | --- | --- |
| **TFTP** | UDP/69 | ★★★★★ **無** | ★★★★★ **無（明文）** | client | ★★★ 只能在封閉管理網段用 |
| **FTP** | TCP/21 | 帳密（★★★★ 明文） | 無 | client | ★★ 不建議 |
| **SCP** | TCP/22 | ★ SSH 認證 | ★ SSH 加密 | client ／ server | ★★★★ **建議** |
| **HTTP／HTTPS** | TCP/80,443 | 視設定 | HTTPS 有 | client | ★★ 少用 |

> [!danger] ★★★★★ 設定檔不是普通檔案
> 一份 `running-config` 裡有：
> - `enable secret 5 $1$...` 與 `username ... secret 5 $1$...`（★★★★ 密碼雜湊，可離線暴力破解）
> - `snmp-server community ...`（★★★★★ 若是 v2c 就是明文密碼）
> - 完整的 ACL、VLAN 規劃、管理網段（★★★★ 攻擊者的地圖）
> - TACACS+／RADIUS 的 key
>
> **用 TFTP 傳輸等於把這些東西明文丟在網路上。**
> 而且備份主機上那個目錄如果權限沒設好，任何人都能下載全機關的網路設定。
>
> ★★★★ 機關環境的最低要求：
> ① 管理網段與使用者網段實體或邏輯隔離；
> ② 備份主機的備份目錄限制存取（只有網管群組可讀）；
> ③ 有條件就改用 SCP。

### 三層防護：這篇的核心觀念 ★★★★★

```text
第一層：變更當下的保險   ─▶ reload in 5  ／  configure terminal revert timer 5
                            改壞了自動復原，你不用做任何事

第二層：設備內的版本歷史 ─▶ archive ＋ configure replace
                            不用重開機就能逐行回滾到任一個歷史版本

第三層：設備外的備份     ─▶ copy running-config scp: ＋ kron 排程
                            設備整台壞掉、被偷、被清空時的最後退路
```

★★★★★ **三層缺一不可**，而且它們解決的是**不同**的問題：

| 情境 | 第一層 | 第二層 | 第三層 |
| --- | --- | --- | --- |
| 遠端改設定改壞、斷線 | ★ 有效 | ✘ 你連不進去 | ✘ 你連不進去 |
| 改了三天發現某個設定不對 | ✘ 早就過期 | ★ 有效 | ★ 有效 |
| 設備硬體故障要換新機 | ✘ | ✘ 隨設備一起壞了 | ★ 有效 |
| 設備被 `write erase` | ✘ | ★★★ 可能有效（archive 在 flash） | ★ 有效 |
| 機房火災、設備被偷 | ✘ | ✘ | ★ 有效（★★★★ 前提是異地存放） |

### `reload in` 為什麼有效 ★★★★★

原理就是 IOS 那個「running-config 只在 RAM」的特性：

```text
① reload in 5            排程 5 分鐘後重開
② 改設定                  ★ 立刻生效，但只在 RAM
③-A 一切正常、你還連得上   ─▶ reload cancel ─▶ write memory ─▶ 完成
③-B ★ 你斷線了            ─▶ 什麼都不做
                          ─▶ 5 分鐘後設備重開
                          ─▶ 載入 startup-config（＝變更前的狀態）
                          ─▶ 你又連得上了
```

> [!danger] ★★★★★ 三個絕對不能搞錯的細節
> **① `reload in` 之前絕對不能先 `write memory`。**
> 存了檔就等於把壞設定寫進 startup-config，重開後照樣是壞的，保險完全失效。
> 這是最常見的誤用。
>
> **② 確認成功後，先 `reload cancel`，再 `write memory`。**
> 忘了 `reload cancel` 的話，五分鐘後正在服務的設備會突然重開，
> 造成計畫外中斷（雖然設定是對的，但服務中斷了）。
>
> **③ 保險生效＝設備真的會重開，中斷 1～3 分鐘。**
> 這是代價。所以變更請排在維護時段，並事先告知。

| 指令 | 作用 | 星級 |
| --- | --- | --- |
| `reload in 5` | 5 分鐘後重開 | ★★★★★ |
| `reload in 1 30` | 1 小時 30 分後重開 | ★★★ |
| `reload at 03:00` | 指定時間重開（★★ 需先設好 clock） | ★★★ |
| `reload cancel` | ★★★★★ 取消排程 | ★★★★★ |
| `show reload` | 還剩多久 | ★★★★ |

### `configure revert timer`：更精準的 commit confirmed ★★★★

IOS 12.4(20)T 與多數 IOS-XE 提供一個**只回滾設定、不重開機**的機制：

```cisco
SW-3F-01#configure terminal revert timer 5
Enter configuration commands, one per line.  End with CNTL/Z.
Rollback Confirmed Change: Backing up current running config to
 flash:/rollback_1.cfg
SW-3F-01(config)#
```

```cisco
!-- 改完設定，確認一切正常
SW-3F-01#configure confirm
```

```cisco
!-- 或是主動立刻回滾
SW-3F-01#configure revert now
```

```cisco
SW-3F-01#show archive
The maximum archive configurations allowed is 14.
The next archive file will be named flash:/archive/SW-3F-01-config-8
 Archive #  Name
   1        flash:/archive/SW-3F-01-config-1
   2        flash:/archive/SW-3F-01-config-2 <- Most Recent
...
```

| | `reload in 5` | `configure terminal revert timer 5` |
| --- | --- | --- |
| 逾時的動作 | ★★★★ **重新開機**（服務中斷 1～3 分鐘） | ★ **只回滾設定**（服務不中斷） |
| 回到什麼狀態 | startup-config | 進入設定模式前的 running-config |
| 確認的指令 | `reload cancel` | `configure confirm` |
| 支援版本 | ★ 所有版本 | ★★★★ IOS 12.4(20)T＋／多數 IOS-XE（**要確認**） |
| 適合什麼 | ★★★★ 任何情況，尤其是不確定版本支援時 | ★★★★ 已確認支援的環境，日常變更 |

> [!warning] ★★★★ 兩個都有陷阱，但方向不同
> `configure terminal revert timer` 的陷阱：
> **它只保護「在那個 configure session 裡做的變更」**。
> 如果你 `end` 離開後又用另一個 `configure terminal` 改東西，
> 那些變更不在保護範圍內。
> ★★★ 而且部分平台在 `revert timer` 生效期間**不允許 `write memory`**，
> 這其實是好事（防止你不小心把壞設定存檔）。
>
> ★★★★★ **不確定你的版本支不支援時，用 `reload in`。**
> `reload in` 在所有版本都存在，行為完全可預測。

### IOS 映像檔與開機順序 ★★★★

```cisco
SW-3F-01#show boot
BOOT path-list      : flash:/c2960x-universalk9-mz.152-7.E3.bin
Config file         : flash:/config.text
Private Config file : flash:/private-config.text
Enable Break        : yes
Manual Boot         : no
Allow Dev Key       : yes
HELPER path-list    :
NVRAM/Config file
      buffer size:   524288
Timeout for Config
          Download:    0 seconds
Config Download
       via DHCP:       disabled (next boot: disabled)
```

```cisco
SW-3F-01#show running-config | include ^boot system
boot system flash:/c2960x-universalk9-mz.152-7.E10.bin
boot system flash:/c2960x-universalk9-mz.152-7.E3.bin
```

★★★★★ **`boot system` 的順序就是開機嘗試的順序**：
第一行的映像檔開不起來（檔案損毀、不存在），會自動嘗試第二行。
**這兩行就是你的升級退路** —— 新版在前、舊版在後。

★★★ 沒有任何 `boot system` 時，設備會嘗試 flash 裡找到的第一個
可開機映像檔（順序不保證），**這是不可預測的，不要依賴它**。

| 檔案 | 是什麼 | 星級 |
| --- | --- | --- |
| `flash:/xxx.bin` | ★★★★ IOS 映像檔（bundle 模式） | ★★★★ |
| `flash:/config.text` | ★★★ startup-config 在 flash 上的實體檔案（2960 系列） | ★★★ |
| `flash:/vlan.dat` | ★★★★ VLAN 資料庫 | ★★★★ |
| `flash:/private-config.text` | 私密設定（RSA 金鑰等） | ★★★ |
| `flash:/archive/` | ★★★★ `archive` 功能存放歷史版本的目錄 | ★★★★ |

## 環境準備與安裝

### 本篇的環境

| 項目 | 值 |
| --- | --- |
| 設備 | SW-3F-01，10.10.99.31，Catalyst WS-C2960X-24TS-L |
| 目前版本 | IOS 15.2(7)E3 |
| 目標版本 | IOS 15.2(7)E10（★★★ 假設值，實際版本請查官網） |
| 備份主機 | 10.10.99.20（Ubuntu，跑 SSH／SCP，另有 TFTP 供舊設備用） |
| 管理帳號 | `netadm`（privilege 15） |
| Console | ★★★★ 分處有人可以協助接線（升級的必要條件） |

### 準備一台 Linux 備份主機 ★★★

SCP 的伺服器端就是一台普通的 Linux SSH 伺服器：

```bash
# 在 10.10.99.20 上
$ sudo useradd -m -s /bin/bash netbackup
$ sudo passwd netbackup
$ sudo mkdir -p /srv/netbackup/configs /srv/netbackup/images
$ sudo chown -R netbackup:netbackup /srv/netbackup
$ sudo chmod 750 /srv/netbackup
$ ls -ld /srv/netbackup
drwxr-x--- 4 netbackup netbackup 4096 Sep  2 10:14 /srv/netbackup
```

★★★★ `chmod 750` 很重要 —— 設定檔含密碼雜湊，不能讓所有使用者讀取。
sshd 的安全設定見 [[020-02-01-04-svc-sshd-伺服器端設定]]。

若還需要 TFTP（給不支援 SCP 的舊設備）：

```bash
$ sudo apt install tftpd-hpa
$ sudo mkdir -p /srv/tftp
$ sudo chown tftp:tftp /srv/tftp
$ sudo chmod 755 /srv/tftp
$ grep -v '^#' /etc/default/tftpd-hpa
TFTP_USERNAME="tftp"
TFTP_DIRECTORY="/srv/tftp"
TFTP_ADDRESS=":69"
TFTP_OPTIONS="--secure --create"
$ sudo systemctl restart tftpd-hpa
$ systemctl is-active tftpd-hpa
active
```

> [!warning] ★★★★ `--create` 這個選項有風險
> 沒有它的話，設備無法建立新檔案（只能覆蓋已存在的檔案），
> 你得先在伺服器上 `touch` 出檔名並 `chmod 666`，非常麻煩。
> 有了它，**任何能連到 UDP/69 的人都能在你的 TFTP 目錄裡寫檔案**。
> ★★★★★ 所以 TFTP 服務**只能綁在管理網段的介面上**，
> 並用防火牆限制來源。見 [[090-02-02-guide-防火牆-ufw基礎與實務]]。

### 動工前的檢查 ★★★★

```cisco
SW-3F-01#show version | include Version 15|Model number|System serial|System image|register
Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E3, RELEASE SOFTWARE (fc2)
Model number                    : WS-C2960X-24TS-L
System serial number            : FOC2148XXXX
System image file is "flash:/c2960x-universalk9-mz.152-7.E3.bin"
Configuration register is 0xF
```

```cisco
SW-3F-01#dir flash:
Directory of flash:/

    2  -rwx    26674176   Nov 18 2025 08:10:22 +08:00  c2960x-universalk9-mz.152-7.E3.bin
    3  -rwx        5127   Sep  2 2026 10:14:22 +08:00  config.text
    4  -rwx         856   Sep  2 2026 10:14:22 +08:00  private-config.text
    5  -rwx        3072   Aug 15 2026 09:22:11 +08:00  vlan.dat
    6  drwx         512   Sep  2 2026 10:20:00 +08:00  archive

122185728 bytes total (94831104 bytes free)
```

★★★★★ **`94831104 bytes free`（約 90 MB）** —— 這是升級的關鍵數字。
新映像檔約 27 MB，空間充足，**可以同時保留新舊兩個映像檔**。

★★★★ 空間不足時的處理順序：
① 先刪其他無用檔案（舊的 crashinfo、log）；
② 再考慮刪**更舊**的映像檔（保留現在正在跑的那個）；
③ ★★★★★ **絕對不要刪掉現在正在跑的映像檔**。

```cisco
SW-3F-01#show file systems
File Systems:

     Size(b)      Free(b)      Type  Flags  Prefixes
*  122185728     94831104     flash     rw   flash:
           -            -    opaque     rw   bs:
           -            -    opaque     rw   vb:
      524288       520229     nvram     rw   nvram:
           -            -   network     rw   tftp:
           -            -    opaque     ro   cns:
           -            -   network     rw   scp:
           -            -   network     rw   http:
           -            -   network     rw   https:
```

★★★ `scp:` 出現在清單裡 → 這台支援 SCP 客戶端。

> [!info]- Juniper JunOS 對照
> | 事情 | Cisco IOS | Juniper JunOS |
> | --- | --- | --- |
> | 變更保險 | ★★★★★ `reload in 5` ＋ `reload cancel` | ★ `commit confirmed 5` ＋ `commit` |
> | 精準回滾保險 | `configure terminal revert timer 5` ＋ `configure confirm` | 同上（★ JunOS 只有一種，行為一致） |
> | 設定版本歷史 | ★★★★ `archive` ＋ `show archive` | ★ 自動保留 `rollback 0`～`rollback 49` |
> | 回滾到前一版 | `configure replace flash:/archive/xxx-config-5` | ★ `rollback 1` ＋ `commit` |
> | 比較差異 | `show archive config differences <A> <B>` | `show \| compare rollback 1` |
> | 備份設定 | `copy running-config scp://user@host/file` | `file copy /config/juniper.conf.gz scp://user@host/` |
> | 排程備份 | ★★★ `kron`（★★★★ 要 `file prompt quiet`） | `set system archival configuration transfer-interval` |
> | 上傳韌體 | `copy scp: flash:` | `file copy scp://... /var/tmp/` |
> | 驗證映像檔 | ★★★★ `verify /md5 flash:xxx.bin` | `request system software validate` |
> | 安裝韌體 | `boot system flash:/xxx.bin` ＋ `reload` | `request system software add /var/tmp/jinstall.tgz` |
> | 帶保險的升級 | ★★★ 保留兩行 `boot system`（新在前舊在後） | ★ `request system software add ... reboot` ＋ snapshot |
> | 升級後回退 | 改 `boot system` 順序 ＋ `reload` | `request system software rollback` ＋ reboot |
>
> ★★★★ 最大差異：JunOS 的 rollback 是**內建且自動的**（每次 commit 自動存檔 50 版），
> Cisco 要自己啟用 `archive` 才有。詳見 [[040-01-09-svc-Juniper-設定備份與韌體升級]]。

## 基礎設定

### 步驟 1：手動備份設定 ★★★★

**用 TFTP（舊設備、封閉網段）**：

```cisco
SW-3F-01#copy running-config tftp://10.10.99.20/SW-3F-01-20260902.cfg
Address or name of remote host [10.10.99.20]?
Destination filename [SW-3F-01-20260902.cfg]?
!!
5127 bytes copied in 1.284 secs (3993 bytes/sec)
```

**用 SCP（建議）**：

```cisco
SW-3F-01#copy running-config scp://netbackup@10.10.99.20/srv/netbackup/configs/SW-3F-01-20260902.cfg
Address or name of remote host [10.10.99.20]?
Destination username [netbackup]?
Destination filename [/srv/netbackup/configs/SW-3F-01-20260902.cfg]?
Writing /srv/netbackup/configs/SW-3F-01-20260902.cfg
Password:
!
5127 bytes copied in 2.114 secs (2425 bytes/sec)
```

**驗證**（★★★★ 這一步不能省）：

```bash
$ ls -l /srv/netbackup/configs/SW-3F-01-20260902.cfg
-rw-r--r-- 1 netbackup netbackup 5127 Sep  2 10:32 SW-3F-01-20260902.cfg
$ head -5 /srv/netbackup/configs/SW-3F-01-20260902.cfg
Building configuration...

Current configuration : 5127 bytes
!
! Last configuration change at 10:14:22 CST Tue Sep 2 2026 by netadm
$ grep -c . /srv/netbackup/configs/SW-3F-01-20260902.cfg
187
```

★★★★★ **檢查三件事**：檔案存在、大小不是 0、內容看起來像設定檔。
0 bytes 或只有錯誤訊息的檔案是最危險的 —— 你以為有備份，其實沒有。

**同時備份 `vlan.dat`**（若不是 transparent 模式）：

```cisco
SW-3F-01#copy flash:vlan.dat tftp://10.10.99.20/SW-3F-01-vlan-20260902.dat
Address or name of remote host [10.10.99.20]?
Source filename [vlan.dat]?
Destination filename [SW-3F-01-vlan-20260902.dat]?
!!
3072 bytes copied in 0.412 secs (7456 bytes/sec)
```

### 步驟 2：讓設備當 SCP 伺服器（拉取式備份）★★★

上面是**設備主動推送**。反過來也可以讓網管主機**主動拉取**，
這在集中管理數十台設備時比較好維護。

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#aaa new-model
SW-3F-01(config)#aaa authentication login default local
SW-3F-01(config)#aaa authorization exec default local
SW-3F-01(config)#ip scp server enable
SW-3F-01(config)#end
```

```bash
# 在網管主機上
$ scp netadm@10.10.99.31:running-config ./SW-3F-01-$(date +%Y%m%d).cfg
Password:
running-config                              100% 5127     1.2MB/s   00:00
```

> [!danger] ★★★★★ `ip scp server enable` 需要 `aaa new-model`，而那會改變登入行為
> `ip scp server enable` **必須**搭配 `aaa authorization exec` 才能運作。
> 而 `aaa new-model` 一打下去，**所有 line 的認證方式立刻改由 AAA 決定** ——
> 方法清單沒設好就會把自己鎖在外面（連 console 都是）。
>
> ★★★★★ 保命做法：
> 1. **一律在 console 上做這個變更**，或先 `reload in 15`
> 2. 確保 `aaa authentication login default local` 的 `local` 存在
>    （不然沒有任何認證來源）
> 3. 確保本機帳號已經存在且測試過
>
> 詳見 [[040-01-12-guide-Cisco-管理IP與遠端存取]]。

★★★ 如果你的環境只有幾台設備，**推送式（`copy run scp:`）比較單純**，
不需要動 AAA，建議優先採用。

### 步驟 3：啟用 `archive` —— 設備內的版本歷史 ★★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#archive
SW-3F-01(config-archive)#path flash:/archive/$h-config
SW-3F-01(config-archive)#maximum 14
SW-3F-01(config-archive)#time-period 1440
SW-3F-01(config-archive)#write-memory
SW-3F-01(config-archive)#exit
SW-3F-01(config)#end
```

| 參數 | 作用 | 星級 |
| --- | --- | --- |
| `path flash:/archive/$h-config` | ★★★ 存放位置與檔名（`$h` 展開成 hostname） | ★★★ |
| `maximum 14` | ★★★ 最多保留 14 份（超過就覆蓋最舊的） | ★★★ |
| `time-period 1440` | ★★★ 每 1440 分鐘（24 小時）自動存一份 | ★★★ |
| `write-memory` | ★★★★ **每次 `write memory` 時自動存一份** | ★★★★ |

★★★★ `write-memory` 這一項最有價值：它讓「每一次設定變更存檔」
都自動產生一個可回滾的版本點，完全不需要人記得做。

★★★ `path` 也可以指向遠端：

```cisco
SW-3F-01(config-archive)#path scp://netbackup@10.10.99.20/srv/netbackup/configs/$h-config
```

★★★★ 但遠端路徑在網路不通時會失敗（且可能拖慢 `write memory`），
**建議主路徑用 flash、另外用 kron 排程推送到遠端**。

**驗證**：

```cisco
SW-3F-01#write memory
Building configuration...
[OK]
SW-3F-01#show archive
The maximum archive configurations allowed is 14.
The next archive file will be named flash:/archive/SW-3F-01-config-3
 Archive #  Name
   0
   1        flash:/archive/SW-3F-01-config-1
   2        flash:/archive/SW-3F-01-config-2 <- Most Recent
   3
   ...
   14
```

```cisco
SW-3F-01#dir flash:/archive/
Directory of flash:/archive/

    7  -rwx        5127   Sep  2 2026 10:41:03 +08:00  SW-3F-01-config-1
    8  -rwx        5189   Sep  2 2026 11:02:44 +08:00  SW-3F-01-config-2

122185728 bytes total (94820864 bytes free)
```

### 步驟 4：`configure replace` —— 不重開機的回滾 ★★★★★

這是 `archive` 真正的價值所在。

```cisco
!-- ① 先看看差異（★★★★ 回滾前一定要先看）
SW-3F-01#show archive config differences flash:/archive/SW-3F-01-config-1 system:running-config
!Contextual Config Diffs:
+interface GigabitEthernet1/0/8
+ description TEMP-TEST
+ shutdown
-interface GigabitEthernet1/0/8
- description USER-3F-008
```

★★★ 讀法：`+` 是 running-config 有而歷史版本沒有的（新增的），
`-` 是歷史版本有而 running-config 沒有的（被刪掉的）。

```cisco
!-- ② 先做「假執行」看看會下哪些指令
SW-3F-01#configure replace flash:/archive/SW-3F-01-config-1 list
This will apply all necessary additions and deletions
to replace the current running configuration with the
contents of the specified configuration file, which is
assumed to be a complete configuration, not a partial
configuration. Enter Y if you are sure you want to proceed. ? [no]: y
!Pass 1
!List of Commands:
interface GigabitEthernet1/0/8
 no shutdown
 description USER-3F-008
end

Total number of passes: 1
Rollback Done
```

```cisco
!-- ③ 帶保險的執行（★★★★★ 建議寫法）
SW-3F-01#configure replace flash:/archive/SW-3F-01-config-1 time 5
This will apply all necessary additions and deletions
to replace the current running configuration with the
contents of the specified configuration file, which is
assumed to be a complete configuration, not a partial
configuration. Enter Y if you are sure you want to proceed. ? [no]: y
Total number of passes: 1
Rollback Done

SW-3F-01#configure confirm
```

★★★★★ `time 5` 的意思是「5 分鐘內沒有 `configure confirm` 就自動回滾回來」——
**這是回滾動作本身的保險**（回滾也可能回滾錯版本）。

| 選項 | 作用 | 星級 |
| --- | --- | --- |
| `list` | ★★★★ 只列出會執行的指令，不實際套用（假執行） | ★★★★ |
| `time <分鐘>` | ★★★★★ 套用後 N 分鐘內未確認就自動回滾 | ★★★★★ |
| `force` | ★★★ 不詢問直接執行（腳本用，人工操作不要用） | ★★★ |
| `revert now` | 立刻取消剛剛的 replace | ★★★★ |

> [!warning] ★★★★ `configure replace` 不是萬能的
> 它是**逐行計算差異並下指令**，不是「把檔案倒回去」。有些東西它處理不了：
> - ★★★★ **無法回滾 `vlan.dat`**（VLAN 資料庫不在設定檔裡）
> - ★★★ 某些需要重啟才生效的設定（如 `sdm prefer`）
> - ★★★ 密碼類設定回滾後可能需要重新輸入
> - ★★★★ 若目標檔案不完整（例如是 `show run | section` 的輸出），
>   **它會把「檔案裡沒有的東西」全部刪掉** —— 後果災難性
>
> ★★★★★ **`configure replace` 的目標檔案必須是完整的設定檔。**
> 拿一份片段去 replace 等於把設備清空。

### 步驟 5：`kron` 排程自動備份 ★★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#file prompt quiet
SW-3F-01(config)#kron policy-list BACKUP-CONFIG
SW-3F-01(config-kron-policy)#cli show running-config | redirect tftp://10.10.99.20/$h-daily.cfg
SW-3F-01(config-kron-policy)#exit
SW-3F-01(config)#kron occurrence DAILY-BACKUP at 2:30 recurring
SW-3F-01(config-kron-occurrence)#policy-list BACKUP-CONFIG
SW-3F-01(config-kron-occurrence)#end
```

> [!danger] ★★★★★ `file prompt quiet` 是 kron 備份最大的坑
> `copy` 指令預設會**互動式詢問**（`Destination filename [xxx]?`）。
> kron 執行的是非互動的 CLI，**遇到提示就永遠卡在那裡，備份靜默失敗**。
> 你會以為排程備份在跑，其實一份都沒產生。
>
> `file prompt quiet` 讓所有 `copy` 類指令不再詢問，直接用預設值。
>
> ★★★★ **副作用要知道**：這個設定是全域的，
> 之後你**人工**打 `copy` 指令時也不會再有確認提示 ——
> 包括 `copy tftp: flash:` 這種會覆蓋檔案的操作。
> 打錯目的地就直接覆蓋掉了，沒有機會後悔。
>
> ★★★ 替代寫法：用 `show running-config | redirect <目的>`
> 而不是 `copy running-config <目的>` —— `redirect` 不會產生互動提示，
> 就不需要 `file prompt quiet`。上面的範例就是用這個寫法。

**驗證**：

```cisco
SW-3F-01#show kron schedule
Kron Occurrence Schedule
DAILY-BACKUP inactive, will run again in 15 hours 27 minutes 12 seconds

SW-3F-01#show running-config | section kron
kron occurrence DAILY-BACKUP at 2:30 recurring
 policy-list BACKUP-CONFIG
kron policy-list BACKUP-CONFIG
 cli show running-config | redirect tftp://10.10.99.20/$h-daily.cfg
```

★★★★★ **手動觸發一次驗證它真的會動**（不要等到明天才發現沒作用）：

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#kron occurrence TEST-NOW in 1 oneshot
SW-3F-01(config-kron-occurrence)#policy-list BACKUP-CONFIG
SW-3F-01(config-kron-occurrence)#end
SW-3F-01#
!-- 等一分鐘
SW-3F-01#show kron schedule
Kron Occurrence Schedule
DAILY-BACKUP inactive, will run again in 15 hours 25 minutes 03 seconds
```

```bash
# 在備份主機上確認
$ ls -l /srv/tftp/SW-3F-01-daily.cfg
-rw-rw-rw- 1 tftp tftp 5189 Sep  2 11:31 SW-3F-01-daily.cfg
```

★★★★ 確認之後把測試用的 occurrence 刪掉：

```cisco
SW-3F-01(config)#no kron occurrence TEST-NOW
```

> [!tip] ★★★★ 更好的做法：從外部拉取，而不是靠設備推送
> 設備端的 kron 有幾個弱點：時間不準就會錯過、備份失敗沒人知道、
> 每台設備都要設定一次、檔名固定會被覆蓋（沒有歷史）。
>
> ★★★★ 機關環境的建議：**在網管主機上跑一支腳本或用 Oxidized／RANCID
> 之類的工具，定時 SSH 進每一台設備抓設定，存進 git**。
> 好處：集中管理、失敗會有錯誤訊息、天然有版本歷史與 diff、
> 一個地方就能看到全機關所有設備的變更。
> git 的使用見 [[060-01-01-01-guide-Git-觀念與初次設定]]。

## 進階設定與調校

### IOS 升級的完整流程 ★★★★★

```text
【準備階段】—— 可以提前幾天做，不影響服務
 ① 查官方 Release Notes：目標版本、已知問題、是否需要中繼版本
 ② 確認授權（部分機型升級後功能會受限）
 ③ 下載映像檔 ＋ ★★★★★ 記下官網公布的 MD5
 ④ 檢查 flash 空間（新舊映像檔要能並存）
 ⑤ ★★★★★ 完整備份設定 ＋ vlan.dat ＋ show tech-support
 ⑥ ★★★★ 確認有 console 存取（現場有人或有 console 伺服器）
 ⑦ 排維護時段、通知使用者

【上傳階段】—— 不影響服務，可以在上班時間做
 ⑧ copy scp: flash: 上傳新映像檔
 ⑨ ★★★★★ verify /md5 比對，不一致就重傳

【切換階段】—— ★ 需要維護時段
 ⑩ boot system 設定（新版在前、舊版在後）
 ⑪ write memory
 ⑫ ★★★★ show boot 確認
 ⑬ reload
 ⑭ 等待 3～8 分鐘

【驗收階段】
 ⑮ show version 確認版本
 ⑯ 逐項跑驗收檢查表
 ⑰ 觀察 24～48 小時

【回退（如果需要）】
 ⑱ 改 boot system 順序（舊版在前）→ write memory → reload
```

### 步驟 1：檢查空間並上傳映像檔 ★★★★

```cisco
SW-3F-01#dir flash: | include bytes free
122185728 bytes total (94831104 bytes free)
```

```cisco
SW-3F-01#copy scp://netbackup@10.10.99.20/srv/netbackup/images/c2960x-universalk9-mz.152-7.E10.bin flash:
Destination filename [c2960x-universalk9-mz.152-7.E10.bin]?
Password:
 Accessing scp://netbackup@10.10.99.20/srv/netbackup/images/c2960x-universalk9-mz.152-7.E10.bin...
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
26742784 bytes copied in 184.221 secs (145166 bytes/sec)
```

★★★ 上傳過程完全不影響服務，可以在上班時間做。
27 MB 在 100 Mbps 管理網段上大約 3 分鐘，1 Gbps 更快。

```cisco
SW-3F-01#dir flash: | include \.bin|bytes free
    2  -rwx    26674176   Nov 18 2025 08:10:22 +08:00  c2960x-universalk9-mz.152-7.E3.bin
    9  -rwx    26742784   Sep  2 2026 13:44:18 +08:00  c2960x-universalk9-mz.152-7.E10.bin
122185728 bytes total (68088320 bytes free)
```

★★★★ 新舊兩個映像檔並存，剩餘 65 MB —— 這就是你的退路。

### 步驟 2：`verify /md5` —— 不能省的一步 ★★★★★

```cisco
SW-3F-01#verify /md5 flash:c2960x-universalk9-mz.152-7.E10.bin
.....................................................................
.....................................................................Done!
verify /md5 (flash:c2960x-universalk9-mz.152-7.E10.bin) = a3f81c2e94d7b0562f8e13c47a9d0b6e
```

★★★★★ 跟 Cisco 官網下載頁公布的 MD5 逐字比對。

★★★ 也可以讓 IOS 直接幫你比對：

```cisco
SW-3F-01#verify /md5 flash:c2960x-universalk9-mz.152-7.E10.bin a3f81c2e94d7b0562f8e13c47a9d0b6e
.....................................................................Done!
Verified (flash:c2960x-universalk9-mz.152-7.E10.bin) = a3f81c2e94d7b0562f8e13c47a9d0b6e
```

不一致時：

```cisco
SW-3F-01#verify /md5 flash:c2960x-universalk9-mz.152-7.E10.bin a3f81c2e94d7b0562f8e13c47a9d0b6e
.....................................................................Done!
%Error verifying flash:c2960x-universalk9-mz.152-7.E10.bin
Computed signature = 7b2c94f81a3e0d562f8e13c47a9d0b6e
Submitted signature = a3f81c2e94d7b0562f8e13c47a9d0b6e
```

> [!danger] ★★★★★ MD5 不一致就是不能用，沒有例外
> 一個損毀的映像檔會讓設備**開機失敗、卡在 ROMMON**。
> 那時候你需要：現場、console 線、xmodem 傳輸（27 MB 用 xmodem 要**好幾個小時**）
> 或一台 TFTP 伺服器接在同一個網段。
>
> ★★★★ 不一致的處理：`delete flash:<檔案>` 之後重新上傳。
> 傳三次都不一致就換一台備份主機或換傳輸協定（TFTP 的 UDP 特性比較容易出錯）。

### 步驟 3：`boot system` 與退路 ★★★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#no boot system
SW-3F-01(config)#boot system flash:/c2960x-universalk9-mz.152-7.E10.bin
SW-3F-01(config)#boot system flash:/c2960x-universalk9-mz.152-7.E3.bin
SW-3F-01(config)#end
SW-3F-01#write memory
Building configuration...
[OK]
```

★★★★★ 順序就是一切：**新版在第一行，舊版在第二行**。
新版開不起來時，設備會自動嘗試舊版 —— **這就是你的自動退路**。

```cisco
SW-3F-01#show boot
BOOT path-list      : flash:/c2960x-universalk9-mz.152-7.E10.bin;flash:/c2960x-universalk9-mz.152-7.E3.bin
Config file         : flash:/config.text
Private Config file : flash:/private-config.text
Enable Break        : yes
Manual Boot         : no
```

★★★★ `BOOT path-list` 顯示兩個路徑、分號分隔 → 設定正確。

```cisco
SW-3F-01#show running-config | include ^boot system
boot system flash:/c2960x-universalk9-mz.152-7.E10.bin
boot system flash:/c2960x-universalk9-mz.152-7.E3.bin
```

★★★★ `Enable Break : yes` 也很重要 —— 它代表開機時可以用
Ctrl+Break 進 ROMMON。**這是最後的救援手段，不要把它關掉。**

### 步驟 4：重開機與觀察

```cisco
SW-3F-01#reload
System configuration has been modified. Save? [yes/no]: no
Proceed with reload? [confirm]

*Sep  2 21:03:11.442: %SYS-5-RELOAD: Reload requested by netadm on vty0
 (10.10.99.50). Reload Reason: Reload Command.
```

★★★★ 回 `no` 是因為你剛剛已經 `write memory` 了，這裡不需要再存。
★★★ 如果它問這句話而你**不記得自己改了什麼**，先 `end` 取消，
用 `show archive config differences system:running-config nvram:startup-config` 查清楚。

> [!danger] ★★★★★ 這一刻起，你只能靠 console
> 重開機期間設備完全離線。如果新版開不起來，
> **SSH 是連不上的**，你只能透過 console 看到 ROMMON 或開機失敗訊息。
> 這就是為什麼「現場有人可以接 console」是升級的前置條件。
>
> ★★★ 從 console 上你會看到完整的開機過程：
>
> ```text
> Loading "flash:/c2960x-universalk9-mz.152-7.E10.bin"...
> @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
> File "flash:/c2960x-universalk9-mz.152-7.E10.bin" uncompressed and installed,
>  entry point: 0x3000
> executing...
> ```
>
> 如果第一個映像檔壞了，你會看到它自動嘗試第二個 —— 那就是退路生效了。

### 步驟 5：升級後驗收 ★★★★★

```cisco
SW-3F-01#show version | include Version 15|System image|uptime|Last reload
Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E10, RELEASE SOFTWARE (fc1)
SW-3F-01 uptime is 4 minutes
System image file is "flash:/c2960x-universalk9-mz.152-7.E10.bin"
Last reload reason: Reload Command
```

★★★★★ 三件事都對：版本是 E10、映像檔路徑是新的、重開原因是 `Reload Command`
（★★★★ 如果是 `Watchdog`、`Software failure` 之類，代表出過問題，要查 crashinfo）。

```cisco
SW-3F-01#show interfaces status | exclude notconnect|disabled
Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   USER-3F-001        connected    30         a-full a-1000 10/100/1000BaseTX
Gi1/0/17  AP-3F-01           connected    trunk      a-full a-1000 10/100/1000BaseTX
Gi1/0/24  UPLINK-TO-SW-DIST- connected    trunk      a-full a-1000 10/100/1000BaseTX

SW-3F-01#show interfaces trunk | begin Vlans in spanning tree
Port        Vlans in spanning tree forwarding state and not pruned
Gi1/0/24    20,30,40,50,99

SW-3F-01#show vlan brief | exclude 100[0-9]
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active
20   WIFI-AP-MGMT                     active    Gi1/0/17
30   OFFICE                           active    Gi1/0/1, Gi1/0/2, ...
99   MGMT                             active
999  NATIVE-UNUSED                    active    Gi1/0/21, Gi1/0/22, Gi1/0/23

SW-3F-01#show spanning-tree summary | include Portfast|BPDU|Root
Root bridge for: none
Portfast Default             is enabled
PortFast BPDU Guard Default  is enabled
Portfast BPDU Filter Default is disabled

SW-3F-01#show port-security | include Restrict|Shutdown
      Gi1/0/1            3            1                  0         Restrict

SW-3F-01#show logging | include ERR|CRIT|ALERT|EMERG|Traceback
（★★★★★ 應該沒有輸出）
```

★★★★★ **`show logging` 出現 `Traceback` 是嚴重警訊** ——
那代表 IOS 內部發生例外。記下完整內容，考慮回退並向原廠回報。

```cisco
SW-3F-01#ping 10.10.99.254
Type escape sequence to abort.
Sending 5, 100-byte ICMP Echos to 10.10.99.254, timeout is 2 seconds:
!!!!!
Success rate is 100 percent (5/5), round-trip min/avg/max = 1/1/4 ms
```

### 步驟 6：回退流程 ★★★★★

如果驗收發現問題：

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#no boot system
SW-3F-01(config)#boot system flash:/c2960x-universalk9-mz.152-7.E3.bin
SW-3F-01(config)#boot system flash:/c2960x-universalk9-mz.152-7.E10.bin
SW-3F-01(config)#end
SW-3F-01#write memory
Building configuration...
[OK]
SW-3F-01#show boot | include BOOT path-list
BOOT path-list      : flash:/c2960x-universalk9-mz.152-7.E3.bin;flash:/c2960x-universalk9-mz.152-7.E10.bin
SW-3F-01#reload
Proceed with reload? [confirm]
```

★★★★ **只是把兩行的順序對調** —— 這就是為什麼一定要保留舊映像檔。

> [!warning] ★★★★ 設定檔的向下相容性問題
> 新版 IOS 可能引入新的設定語法。升級後你改了設定、存了檔，
> 回退到舊版時，**舊版可能不認得那些新語法**，那些行會被靜默丟棄。
>
> ★★★★★ 保命做法：
> **升級後到確認穩定（通常 48 小時）之前，不要做任何設定變更。**
> 這樣回退時 startup-config 還是升級前那一份，完全相容。
> 真的要改，先把升級前的設定檔留一份完整備份。

### IOS-XE 的 install 模式 ★★★★

Catalyst 9000 系列（IOS-XE 16.x 以後）預設用 **install 模式**，
跟傳統的 bundle 模式（`boot system` ＋ `.bin`）不同。

```cisco
SW-9300-01#show version | include INSTALL|BUNDLE|Version
Cisco IOS XE Software, Version 17.09.04a
Installation mode is INSTALL
```

| 模式 | 開機檔案 | 升級方式 | 星級 |
| --- | --- | --- | --- |
| **BUNDLE** | 整個 `.bin` | `boot system` ＋ `reload`（同傳統 IOS） | ★★★ |
| **INSTALL** | ★★★★ 解開成多個 `.pkg` ＋ `packages.conf` | `install add file ... activate commit` | ★★★★ |

```cisco
!-- ① 上傳
SW-9300-01#copy scp://netbackup@10.10.99.20/srv/netbackup/images/cat9k_iosxe.17.12.04.SPA.bin flash:

!-- ② 一步到位（★★★ 會自動重開機）
SW-9300-01#install add file flash:cat9k_iosxe.17.12.04.SPA.bin activate commit
```

★★★★★ **更安全的三段式**（分開執行，每一步都可以停下來檢查）：

```cisco
!-- ② add：解開套件，不影響現行運作
SW-9300-01#install add file flash:cat9k_iosxe.17.12.04.SPA.bin
install_add: START Tue Sep 02 21:14:33 CST 2026
install_add: Adding PACKAGE
...
SUCCESS: install_add  Tue Sep 02 21:22:11 CST 2026

SW-9300-01#show install summary
[ R0 ] Installed Package(s) Information:
State (St): I - Inactive, U - Activated & Uncommitted,
            C - Activated & Committed, D - Deactivated & Uncommitted
--------------------------------------------------------------------------------
Type  St   Filename/Version
--------------------------------------------------------------------------------
IMG   C    17.09.04a.0.6
IMG   I    17.12.04.0.4

!-- ③ activate：★★★★★ 帶自動中止計時器（等同 commit confirmed）
SW-9300-01#install activate auto-abort-timer 60
install_activate: START ...
This operation may require a reload of the system. Do you want to proceed? [y/n]y
```

設備重開後，你有 **60 分鐘**驗證：

```cisco
SW-9300-01#show install summary
Type  St   Filename/Version
--------------------------------------------------------------------------------
IMG   U    17.12.04.0.4          ← ★★★★ U = Activated & Uncommitted（未確認）

SW-9300-01#show install log | include auto-abort
Auto abort timer will expire in 54 minutes
```

```cisco
!-- ④-A 驗收通過 → commit（★★★★★ 沒做這一步，60 分鐘後會自動回退）
SW-9300-01#install commit
SUCCESS: install_commit ...

!-- ④-B 驗收失敗 → 主動回退
SW-9300-01#install abort
```

★★★★★ `auto-abort-timer` 是 IOS-XE 內建的 commit confirmed：
**你不做 `install commit`，60 分鐘後設備自己重開回舊版**。
這比傳統 IOS 的 `boot system` 兩行退路更自動化。

```cisco
!-- 事後要回到已 commit 的版本
SW-9300-01#install rollback to committed
```

> [!warning] ★★★★ 堆疊（stack）升級的額外注意事項
> ```cisco
> SW-9300-01#show switch
> Switch/Stack Mac Address : 00c8.8b1a.2233 - Local Mac Address
>                                              H/W   Current
> Switch#  Role    Mac Address     Priority Version  State
> --------------------------------------------------------------------------------
> *1       Active  00c8.8b1a.2233     15     V02     Ready
>  2       Standby 00c8.8b1a.3344     14     V02     Ready
>  3       Member  00c8.8b1a.4455     13     V02     Ready
> ```
>
> ★★★★★ **所有成員必須跑相同版本**，否則版本不符的成員會進入
> `Version Mismatch` 狀態而無法加入堆疊。
> `install` 模式會自動同步到所有成員，但：
> - ★★★★ 升級時間會拉長（每個成員都要處理）
> - ★★★★ 中途不能斷電（部分成員升級完、部分沒完的狀態最麻煩）
> - ★★★ 升級後要確認 `show switch` 所有成員都是 `Ready`
>
> ★★★ 部分平台支援 ISSU（In-Service Software Upgrade）做到接近零中斷，
> 但支援條件嚴格（版本相容性、硬體型號），**務必查該機型的官方文件**。

## 完整實戰範例

**情境**：資安通報指出目前的 IOS 15.2(7)E3 有一個高風險漏洞，
必須在本月底前升級到 15.2(7)E10。你要升級三樓的 SW-3F-01。
分處同仁週六可以到現場協助接 console。

### 前置環境

| 項目 | 值 |
| --- | --- |
| 設備 | SW-3F-01，10.10.99.31，Catalyst WS-C2960X-24TS-L |
| 現行版本 | 15.2(7)E3 |
| 目標版本 | 15.2(7)E10 |
| 維護時段 | 週六 09:00-12:00 |
| 現場人員 | 有（可接 console） |
| 備份主機 | 10.10.99.20（SCP） |
| 影響範圍 | 三樓約 40 位使用者、2 台 AP、1 台印表機 |

### 【準備階段】週三～週五（不影響服務）

#### 步驟 1：查官方文件並下載

```bash
# 在管理主機上（★★★ 實際網址與檔名請以 Cisco 官網為準）
$ ls -l ~/downloads/c2960x-universalk9-mz.152-7.E10.bin
-rw-r--r-- 1 admin admin 26742784 Aug 30 14:22 c2960x-universalk9-mz.152-7.E10.bin
$ md5sum ~/downloads/c2960x-universalk9-mz.152-7.E10.bin
a3f81c2e94d7b0562f8e13c47a9d0b6e  c2960x-universalk9-mz.152-7.E10.bin
```

★★★★★ **把官網頁面上的 MD5 抄下來，跟本機算出來的比對。**
不一致代表下載過程出錯（或更糟的情況），重新下載。

★★★★ 同時要看的 Release Notes 項目：

| 項目 | 為什麼 |
| --- | --- |
| ★★★★ Open Caveats（已知問題） | 你要升級去修的漏洞，別換來另一個問題 |
| ★★★★ Upgrade Path | 有些版本必須先升到中繼版本 |
| ★★★★ Minimum ROMMON version | ROMMON 太舊可能開不起來新映像檔 |
| ★★★ Memory Requirements | 舊機型可能記憶體不足 |
| ★★★ Deprecated Commands | 你現有設定裡的某些指令可能被移除了 |
| ★★★★ License Changes | 升級後功能可能受限 |

```bash
$ scp ~/downloads/c2960x-universalk9-mz.152-7.E10.bin netbackup@10.10.99.20:/srv/netbackup/images/
c2960x-universalk9-mz.152-7.E10.bin       100%   25MB  48.2MB/s   00:00
```

#### 步驟 2：完整備份 ★★★★★

```cisco
SW-3F-01#terminal length 0
SW-3F-01#copy running-config scp://netbackup@10.10.99.20/srv/netbackup/configs/SW-3F-01-preupgrade-20260902.cfg
Destination username [netbackup]?
Destination filename [/srv/netbackup/configs/SW-3F-01-preupgrade-20260902.cfg]?
Password:
!
5721 bytes copied in 2.114 secs (2706 bytes/sec)

SW-3F-01#copy flash:vlan.dat scp://netbackup@10.10.99.20/srv/netbackup/configs/SW-3F-01-vlan-20260902.dat
Password:
!
3072 bytes copied in 1.221 secs (2516 bytes/sec)
```

★★★★ 再加一份 `show tech-support`（★★★ 出問題時原廠會要這個）：

```cisco
SW-3F-01#show tech-support | redirect scp://netbackup@10.10.99.20/srv/netbackup/configs/SW-3F-01-tech-20260902.txt
```

**驗證備份**：

```bash
$ ls -lh /srv/netbackup/configs/SW-3F-01-*20260902*
-rw-r--r-- 1 netbackup netbackup 5.6K Sep  2 15:02 SW-3F-01-preupgrade-20260902.cfg
-rw-r--r-- 1 netbackup netbackup 3.0K Sep  2 15:03 SW-3F-01-vlan-20260902.dat
-rw-r--r-- 1 netbackup netbackup 412K Sep  2 15:05 SW-3F-01-tech-20260902.txt
$ grep -c 'interface GigabitEthernet' /srv/netbackup/configs/SW-3F-01-preupgrade-20260902.cfg
24
```

★★★★★ `grep -c` 得到 24（跟埠數一致）→ 備份是完整的，不是被截斷的。

#### 步驟 3：記錄「升級前的正常狀態」★★★★

★★★★★ 這是驗收的基準線。沒有它，你升級後看到任何異常都無法判斷
「是升級造成的還是本來就這樣」。

```cisco
SW-3F-01#show version | redirect flash:/preupgrade-version.txt
SW-3F-01#show interfaces status | redirect flash:/preupgrade-intstatus.txt
SW-3F-01#show vlan brief | redirect flash:/preupgrade-vlan.txt
SW-3F-01#show interfaces trunk | redirect flash:/preupgrade-trunk.txt
SW-3F-01#show spanning-tree summary | redirect flash:/preupgrade-stp.txt
SW-3F-01#show port-security | redirect flash:/preupgrade-portsec.txt
SW-3F-01#show mac address-table count | redirect flash:/preupgrade-maccount.txt
```

★★★ 把這幾份也複製到備份主機。

#### 步驟 4：上傳映像檔並驗證（可在上班時間做）

```cisco
SW-3F-01#dir flash: | include bytes free
122185728 bytes total (94831104 bytes free)

SW-3F-01#copy scp://netbackup@10.10.99.20/srv/netbackup/images/c2960x-universalk9-mz.152-7.E10.bin flash:
Destination filename [c2960x-universalk9-mz.152-7.E10.bin]?
Password:
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
26742784 bytes copied in 184.221 secs (145166 bytes/sec)
```

```cisco
SW-3F-01#verify /md5 flash:c2960x-universalk9-mz.152-7.E10.bin a3f81c2e94d7b0562f8e13c47a9d0b6e
....................................................................Done!
Verified (flash:c2960x-universalk9-mz.152-7.E10.bin) = a3f81c2e94d7b0562f8e13c47a9d0b6e
```

★★★★★ **`Verified` 才能進到下一階段。**

```cisco
SW-3F-01#dir flash: | include \.bin|bytes free
    2  -rwx    26674176   Nov 18 2025 08:10:22 +08:00  c2960x-universalk9-mz.152-7.E3.bin
    9  -rwx    26742784   Sep  2 2026 15:44:18 +08:00  c2960x-universalk9-mz.152-7.E10.bin
122185728 bytes total (68088320 bytes free)
```

★★★★ 新舊並存、剩 65 MB → 退路已就位。

**到這裡為止，服務完全沒有中斷。** 剩下的留到維護時段。

### 【切換階段】週六 09:00（維護時段）

#### 步驟 5：確認現場人員就位

★★★★★ 打電話確認：
① 現場同仁已到，console 線已接上筆電；
② 終端機軟體參數正確（9600 8N1）；
③ 他能看到 `SW-3F-01#` 提示符號。

★★★★ **這一步不能省。** 沒有 console 就等於沒有退路 ——
新版開不起來時你完全沒有辦法。

#### 步驟 6：設定 `boot system`

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#no boot system
SW-3F-01(config)#boot system flash:/c2960x-universalk9-mz.152-7.E10.bin
SW-3F-01(config)#boot system flash:/c2960x-universalk9-mz.152-7.E3.bin
SW-3F-01(config)#end
SW-3F-01#write memory
Building configuration...
[OK]
```

**驗證**（★★★★★ reload 之前的最後一道檢查）：

```cisco
SW-3F-01#show boot | include BOOT path-list|Enable Break
BOOT path-list      : flash:/c2960x-universalk9-mz.152-7.E10.bin;flash:/c2960x-universalk9-mz.152-7.E3.bin
Enable Break        : yes

SW-3F-01#show archive config differences system:running-config nvram:startup-config
!Contextual Config Diffs:
!No changes were found
```

★★★★★ 三件事都對：兩個 boot path、Enable Break 是 yes、設定已存檔。

#### 步驟 7：重開機

★★★ 通知使用者（如果還有人在用）：

```cisco
SW-3F-01#send *
Enter message, end with CTRL/Z; abort with CTRL/C:
[維護通知] SW-3F-01 將於 1 分鐘後重開機進行 IOS 升級，預計中斷 5 分鐘。^Z
Send message? [confirm]
```

```cisco
SW-3F-01#reload
System configuration has been modified. Save? [yes/no]: no
Proceed with reload? [confirm]

*Sep  6 09:14:22.331: %SYS-5-RELOAD: Reload requested by netadm on vty0
 (10.10.99.50). Reload Reason: Reload Command.
Connection to 10.10.99.31 closed by remote host.
```

★★★ 從這一刻起你只能看 console（請現場同仁回報畫面）。
2960-X 的開機時間約 3～5 分鐘。

現場同仁在 console 上會看到：

```text
Loading "flash:/c2960x-universalk9-mz.152-7.E10.bin"...
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
File "flash:/c2960x-universalk9-mz.152-7.E10.bin" uncompressed and installed,
 entry point: 0x3000
executing...

              Restricted Rights Legend
...
Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E10

Press RETURN to get started!

SW-3F-01>
```

#### 步驟 8：驗收 ★★★★★

等 SSH 恢復（約 4 分鐘後）：

```bash
$ ssh netadm@10.10.99.31
Password:
SW-3F-01#
```

```cisco
SW-3F-01#terminal length 0
SW-3F-01#show version | include Version 15|System image|uptime|Last reload reason
Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E10, RELEASE SOFTWARE (fc1)
SW-3F-01 uptime is 4 minutes
System image file is "flash:/c2960x-universalk9-mz.152-7.E10.bin"
Last reload reason: Reload Command
```

★★★★★ 版本正確、映像檔正確、重開原因正常。

**逐項比對升級前的基準線**：

```cisco
SW-3F-01#show interfaces status | exclude notconnect
Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   USER-3F-001        connected    30         a-full a-1000 10/100/1000BaseTX
Gi1/0/9   PRINTER-3F-01      connected    30         a-full  a-100 10/100/1000BaseTX
Gi1/0/17  AP-3F-01           connected    trunk      a-full a-1000 10/100/1000BaseTX
Gi1/0/21  UNUSED-DO-NOT-PATC disabled     999          auto   auto 10/100/1000BaseTX
Gi1/0/24  UPLINK-TO-SW-DIST- connected    trunk      a-full a-1000 10/100/1000BaseTX
```

★★★★ 跟 `preupgrade-intstatus.txt` 比對，應該完全一致。

```cisco
SW-3F-01#show vlan brief | exclude 100[0-9]
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active
20   WIFI-AP-MGMT                     active    Gi1/0/17
30   OFFICE                           active    Gi1/0/1, Gi1/0/2, Gi1/0/9
50   VOICE                            active    Gi1/0/19, Gi1/0/20
99   MGMT                             active
999  NATIVE-UNUSED                    active    Gi1/0/21, Gi1/0/22, Gi1/0/23
```

★★★★★ **VLAN 完整** —— 這是升級後最需要確認的一項
（尤其如果不是 transparent 模式）。

```cisco
SW-3F-01#show interfaces trunk | begin Vlans in spanning tree
Port        Vlans in spanning tree forwarding state and not pruned
Gi1/0/17    20,40
Gi1/0/24    20,30,40,50,99

SW-3F-01#show spanning-tree summary | include Portfast|BPDU
Portfast Default             is enabled
PortFast BPDU Guard Default  is enabled
Portfast BPDU Filter Default is disabled

SW-3F-01#show port-security | include Restrict
      Gi1/0/1            3            1                  0         Restrict
      Gi1/0/2            3            1                  0         Restrict

SW-3F-01#show ip ssh | include SSH Enabled
SSH Enabled - version 2.0

SW-3F-01#show ip interface brief | include Vlan99
Vlan99                 10.10.99.31     YES NVRAM  up                    up

SW-3F-01#ping 10.10.99.254
Type escape sequence to abort.
Sending 5, 100-byte ICMP Echos to 10.10.99.254, timeout is 2 seconds:
!!!!!
Success rate is 100 percent (5/5), round-trip min/avg/max = 1/1/2 ms

SW-3F-01#show logging | include ERR|CRIT|Traceback|%.*-3-
（★★★★★ 應該沒有輸出）
```

★★★ 最後請一位使用者實測：能上網、能開共用資料夾、印表機能印。

#### 步驟 9：收尾

```cisco
SW-3F-01#copy running-config scp://netbackup@10.10.99.20/srv/netbackup/configs/SW-3F-01-postupgrade-20260906.cfg
Password:
!
5721 bytes copied in 2.014 secs (2841 bytes/sec)
```

```bash
$ diff /srv/netbackup/configs/SW-3F-01-preupgrade-20260902.cfg \
       /srv/netbackup/configs/SW-3F-01-postupgrade-20260906.cfg
3c3
< Current configuration : 5721 bytes
---
> Current configuration : 5721 bytes
7,8c7,8
< boot system flash:/c2960x-universalk9-mz.152-7.E3.bin
---
> boot system flash:/c2960x-universalk9-mz.152-7.E10.bin
> boot system flash:/c2960x-universalk9-mz.152-7.E3.bin
```

★★★★★ **只有 `boot system` 那幾行不同 —— 這是升級成功最好的證據**：
設定完整保留，沒有任何東西在升級過程中遺失。

★★★★ 更新資產清單（型號、序號、**現行版本**、升級日期），
見 [[040-01-18-guide-網路設備-網路設備盤點與文件化]]。

#### 步驟 10：觀察期 ★★★★

★★★★★ **48 小時內不要做任何設定變更**（確保回退時 startup-config 完全相容）。

觀察項目：

```cisco
!-- 每天早上跑一次
SW-3F-01#show logging | include ERR|CRIT|Traceback|%.*-3-
SW-3F-01#show interfaces counters errors | exclude    0           0           0
SW-3F-01#show processes cpu | include utilization
SW-3F-01#show version | include uptime
```

★★★★ 48 小時無異常後，才可以：
① 恢復正常的設定變更作業；
② 考慮清掉舊映像檔（★★★ 但空間夠的話**建議一直留著**）。

### 驗收檢查表 ★★★★

| # | 階段 | 檢查項 | 通過條件 |
| --- | --- | --- | --- |
| 1 | 準備 | Release Notes 已閱讀 | 確認無阻擋性的已知問題與升級路徑限制 |
| 2 | 準備 | 映像檔 MD5（本機） | 與官網公布值一致 |
| 3 | 準備 | flash 空間 | 新舊映像檔可並存 |
| 4 | 準備 | 設定檔備份 | ★★★★★ 檔案存在、大小合理、內容完整 |
| 5 | 準備 | `vlan.dat` 備份 | 存在（或已確認是 transparent 模式） |
| 6 | 準備 | `show tech-support` | 已存一份 |
| 7 | 準備 | 升級前基準線 | 六份 `show` 輸出已存檔 |
| 8 | 準備 | console 存取 | ★★★★★ 現場有人且能看到提示符號 |
| 9 | 上傳 | `verify /md5`（設備上） | ★★★★★ `Verified` |
| 10 | 切換 | `show boot` | 兩個 boot path，新版在前 |
| 11 | 切換 | `Enable Break` | `yes` |
| 12 | 切換 | 設定已存檔 | `No changes were found` |
| 13 | 驗收 | `show version` | 版本是目標版本 |
| 14 | 驗收 | `Last reload reason` | `Reload Command`（不是 crash） |
| 15 | 驗收 | `show interfaces status` | 與升級前基準線一致 |
| 16 | 驗收 | `show vlan brief` | ★★★★★ VLAN 完整 |
| 17 | 驗收 | `show interfaces trunk` | trunk 的 allowed／forwarding 一致 |
| 18 | 驗收 | `show spanning-tree summary` | portfast／bpduguard 設定保留 |
| 19 | 驗收 | `show port-security` | 受保護埠與 sticky MAC 保留 |
| 20 | 驗收 | `show logging` | ★★★★★ 無 Traceback、無 level-3 以上錯誤 |
| 21 | 驗收 | `ping <閘道>` | 100 percent |
| 22 | 驗收 | 使用者實測 | 上網、共用資料夾、列印皆正常 |
| 23 | 收尾 | 升級後備份 ＋ diff | 只有 `boot system` 行不同 |
| 24 | 收尾 | 資產清單已更新 | 版本欄位已改 |
| 25 | 觀察 | 48 小時 | 無異常 log、無 CPU 異常、未意外重開 |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| 升級後設備卡在 ROMMON（`rommon 1 >`） | ★★★★★ 映像檔損毀，且沒有第二個 `boot system` 可用 | ROMMON 下 `dir flash:` 找舊映像檔，`boot flash:<舊映像檔>` 開機；沒有可用映像檔就要用 xmodem 或 ROMMON 的 TFTP 傳輸（需現場 console） |
| `verify /md5` 與官網值不一致 | ★★★★★ 傳輸過程損毀 | `delete flash:<檔案>` 重傳；三次都失敗換傳輸協定（TFTP → SCP）或換來源主機 |
| `%Error copying ... (Not enough space on device)` | ★★★★ flash 空間不足 | `dir flash:` 找出可刪的（舊 crashinfo、更舊的映像檔）；★★★★★ 絕不刪正在跑的映像檔 |
| 重開機後版本沒變 | ★★★★ `boot system` 沒設或沒 `write memory` | `show boot` 確認 `BOOT path-list`；`show run \| include ^boot system` |
| 重開機後設定全部不見 | ★★★★★ `config-register` 是 `0x2142`（開機忽略 startup-config） | `show version` 最後一行確認；`config-register 0x2102`（交換器 `0xF`）＋ `write memory` |
| 升級後 VLAN 全部消失 | ★★★★★ `vlan.dat` 損毀或 VTP 被覆蓋 | 從備份還原 `vlan.dat`（`copy tftp: flash:vlan.dat` ＋ `reload`）；★★★★ 長期解是切 `vtp mode transparent` |
| 升級後某些設定不見了 | ★★★★ 新版移除了那些指令（deprecated） | 比對 `diff` 找出消失的行；查 Release Notes 的替代語法 |
| 回退到舊版後設定有問題 | ★★★★ 升級後改過設定，舊版不認得新語法 | ★★★★★ 從升級前的備份 `configure replace` 還原；預防方式是升級後 48 小時內不改設定 |
| `copy running-config tftp:` 沒有反應、最後逾時 | ★★★★ TFTP 伺服器未啟動、防火牆擋 UDP/69、或目錄權限不足 | 伺服器端 `systemctl status tftpd-hpa`；`tcpdump -i any port 69`；確認 `--create` 選項與目錄權限 |
| TFTP 備份出來是 0 bytes | ★★★★★ 伺服器端無寫入權限，或沒有 `--create` | `chmod 777 /srv/tftp` 測試（★★★ 測完改回合理權限）；改用 SCP |
| `copy running-config scp:` 回 `%Error opening scp://...` | ★★★★ SSH 認證失敗、路徑不存在、或目的目錄無寫入權限 | 先在 Linux 上手動 `scp` 測試同一組帳密與路徑 |
| `ip scp server enable` 之後被鎖在外面 | ★★★★★ `aaa new-model` 改變了登入行為 | 接 console；方法清單一律加 `local` fallback |
| kron 排程備份一份都沒產生 | ★★★★★ `copy` 指令的互動提示卡住了 | 加 `file prompt quiet`，或改用 `show running-config \| redirect <目的>` |
| `show kron schedule` 顯示的時間永遠不到 | ★★★ 設備時間不對 | `show clock`；設 `ntp server` |
| `configure replace` 之後設備狀態更糟 | ★★★★★ 目標檔案不是完整設定檔（是片段） | 先用 `list` 假執行檢查會下哪些指令；★★★★★ 目標檔案必須是完整的 `show running-config` 輸出 |
| `configure replace` 之後 VLAN 沒回來 | ★★★★ `configure replace` 不處理 `vlan.dat` | VLAN 要另外從備份還原，或改用 transparent 模式讓 VLAN 進設定檔 |
| `reload in 5` 之後改設定改對了，卻在五分鐘後突然重開 | ★★★★★ 忘記 `reload cancel` | 養成「驗證成功 → `reload cancel` → `write memory`」的固定順序 |
| `reload in 5` 保險完全沒作用，重開後壞設定還在 | ★★★★★ 在 `reload in` 之前或期間打了 `write memory` | ★★★★★ 確認成功之前絕對不要存檔 |
| 堆疊中某台成員狀態是 `Version Mismatch` | ★★★★ 該成員的版本與 Active 不同 | `show switch`；install 模式下用 `install add file ... activate` 同步，或設定 `software auto-upgrade enable` |
| IOS-XE 升級後 60 分鐘自己回退了 | ★★★★ `install activate auto-abort-timer` 到期而沒有 `install commit` | 這是設計如此；重新 activate 後記得在時限內 `install commit` |
| `install add` 卡很久沒反應 | ★★★ 解開套件需要時間（大型平台可能 5～10 分鐘） | `show install log` 看進度；不要中途取消 |
| `archive` 沒有產生任何版本 | ★★★ `path` 指向的目錄不存在，或沒有觸發條件 | `dir flash:/archive/` 確認；手動 `archive config` 觸發一次測試 |

## 安全性注意事項

> [!danger] ★★★★★ 備份檔就是完整的攻擊地圖
> 一份設定檔包含：密碼雜湊（可離線暴力破解）、SNMP community、
> TACACS+／RADIUS 的 key、完整的 ACL 與 VLAN 規劃、管理網段位置。
> **備份主機的安全等級必須跟網路設備本身一樣高。**

| 項目 | 風險 | 做法 | 星級 |
| --- | --- | --- | --- |
| 用 TFTP 傳設定檔 | ★★★★★ 明文 UDP、無認證，任何人可攔截或竄改 | 改用 SCP；不得已時 TFTP 只綁管理網段介面 ＋ 防火牆限制來源 | ★★★★★ |
| 備份目錄權限過寬 | ★★★★★ 全機關網路設定外洩 | `chmod 750`，只有網管群組可讀；定期稽核 | ★★★★★ |
| 備份未異地存放 | ★★★★ 機房事故時備份與設備一起沒了 | 至少一份異地或離線副本 | ★★★★ |
| 備份從未驗證可用 | ★★★★★ 要用的時候才發現是 0 bytes 或截斷的 | 每次備份後檢查大小與內容；定期做**還原演練** | ★★★★★ |
| 設定檔進 git 但含明文密碼 | ★★★★ 版本庫外洩等於密碼外洩 | 存入前遮蔽 `secret`／`key`／`community` 行；或用私有 repo ＋ 存取控制 | ★★★★ |
| `file prompt quiet` 全域啟用 | ★★★ 人工操作也不再確認，`copy` 打錯就覆蓋 | 優先用 `show ... \| redirect` 取代 `copy`；真的要開就在文件中註明 | ★★★ |
| `ip scp server enable` ＋ `aaa new-model` 設錯 | ★★★★★ 把自己鎖在外面 | 在 console 上做；方法清單一律加 `local` fallback | ★★★★★ |
| 從非官方來源取得映像檔 | ★★★★★ 可能被植入後門 | 只從 Cisco 官網下載；★★★★★ 一律 `verify /md5` 比對官網公布值 | ★★★★★ |
| 升級後未確認 CVE 已修補 | ★★★★ 白升級一場 | 對照資安通報的修補版本，確認 `show version` 的版本號達標 | ★★★★ |
| 舊映像檔留在 flash 但已知有漏洞 | ★★★ 開機退路指向一個有漏洞的版本 | ★★★ 這是必要的取捨（可開機 > 完美無漏洞）；穩定後可換成次新版當退路 | ★★★ |
| `Enable Break` 被關閉 | ★★★★ 失去 ROMMON 救援途徑 | 保持 `Enable Break : yes`（★★ 但機房實體安全要做好） | ★★★★ |
| 升級沒有變更紀錄 | ★★★★ 事後無法追溯、稽核無法交代 | 每次升級留變更單：版本、時間、執行人、驗收結果 | ★★★★ |

## 速查表

| 指令 / 設定項 | 說明 | 範例 |
| --- | --- | --- |
| `copy running-config tftp://<ip>/<file>` | ★★★ TFTP 備份（明文，僅封閉網段） | `copy run tftp://10.10.99.20/sw01.cfg` |
| `copy running-config scp://<user>@<ip>/<path>` | ★★★★ SCP 備份（建議） | `copy run scp://netbackup@10.10.99.20/srv/x.cfg` |
| `copy flash:vlan.dat tftp://<ip>/<file>` | ★★★★ 備份 VLAN 資料庫 | `copy flash:vlan.dat tftp://10.10.99.20/vlan.dat` |
| `copy tftp: flash:` | 從遠端下載檔案到 flash ★★★ | `copy tftp://10.10.99.20/ios.bin flash:` |
| `show running-config \| redirect <目的>` | ★★★★ 不會有互動提示（kron 用這個） | `sh run \| redirect tftp://10.10.99.20/x.cfg` |
| `ip scp server enable` | ★★★ 讓設備當 SCP 伺服器（★★★★★ 需 `aaa new-model`） | `SW(config)#ip scp server enable` |
| `file prompt quiet` | ★★★★ 關閉 copy 的互動提示（kron 必要） | `SW(config)#file prompt quiet` |
| `archive` → `path flash:/archive/$h-config` | ★★★★ 設定版本歷史存放位置 | `SW(config-archive)#path flash:/archive/$h-config` |
| `archive` → `maximum 14` | 保留幾份 ★★★ | `SW(config-archive)#maximum 14` |
| `archive` → `write-memory` | ★★★★ 每次 `write memory` 自動存一版 | `SW(config-archive)#write-memory` |
| `archive` → `time-period 1440` | 每 N 分鐘自動存一版 ★★★ | `SW(config-archive)#time-period 1440` |
| `show archive` | ★★★★ 列出所有歷史版本 | `SW#show archive` |
| `archive config` | 手動觸發存一版 ★★★ | `SW#archive config` |
| `show archive config differences <A> <B>` | ★★★★ 比較兩份設定的差異 | `sh archive config diff sys:running nvram:startup` |
| `configure replace <檔案> list` | ★★★★ 假執行，只列出會下的指令 | `configure replace flash:/archive/x-config-1 list` |
| `configure replace <檔案> time 5` | ★★★★★ 帶回滾保險的套用 | `configure replace flash:/archive/x-config-1 time 5` |
| `configure confirm` | ★★★★★ 確認保留（不做就自動回滾） | `SW#configure confirm` |
| `configure revert now` | 立刻回滾 ★★★★ | `SW#configure revert now` |
| `configure terminal revert timer 5` | ★★★★ 只回滾設定不重開（IOS 12.4(20)T＋） | `SW#configure terminal revert timer 5` |
| `reload in 5` | ★★★★★ 遠端變更保命符（所有版本都有） | `SW#reload in 5` |
| `reload cancel` | ★★★★★ 確認成功後第一件事 | `SW#reload cancel` |
| `show reload` | 排程還剩多久 ★★★★ | `SW#show reload` |
| `kron policy-list <名稱>` ＋ `cli <指令>` | ★★★ 定義排程要跑的指令 | `SW(config-kron-policy)#cli sh run \| redirect tftp://...` |
| `kron occurrence <名稱> at 2:30 recurring` | ★★★ 排程時間 | `SW(config)#kron occurrence DAILY at 2:30 recurring` |
| `show kron schedule` | ★★★ 排程狀態與下次執行時間 | `SW#show kron schedule` |
| `dir flash:` | ★★★★ flash 內容與剩餘空間 | `SW#dir flash:` |
| `show file systems` | 各檔案系統的容量與可用協定 ★★★ | `SW#show file systems` |
| `verify /md5 <檔案>` | ★★★★★ 計算 MD5 | `SW#verify /md5 flash:ios.bin` |
| `verify /md5 <檔案> <期望值>` | ★★★★★ 直接比對 | `SW#verify /md5 flash:ios.bin a3f8...` |
| `boot system flash:/<檔案>` | ★★★★★ 開機順序（可多行，順序即優先序） | `SW(config)#boot system flash:/ios-new.bin` |
| `no boot system` | ★★★★ 清掉所有 boot system 設定 | `SW(config)#no boot system` |
| `show boot` | ★★★★ 確認 BOOT path-list 與 Enable Break | `SW#show boot` |
| `config-register 0x2102` | ★★★★★ 路由器正常值（交換器 `0xF`；`0x2142` 會忽略設定） | `SW(config)#config-register 0x2102` |
| `show version \| include register` | ★★★★ 確認沒留在 `0x2142` | `SW#sh ver \| in register` |
| `install add file flash:<檔案>` | ★★★★ IOS-XE：解開套件（不影響運作） | `SW#install add file flash:cat9k.bin` |
| `install activate auto-abort-timer 60` | ★★★★★ IOS-XE：啟用並設自動回退計時 | `SW#install activate auto-abort-timer 60` |
| `install commit` | ★★★★★ IOS-XE：確認（不做會自動回退） | `SW#install commit` |
| `install abort` | IOS-XE：主動放棄並回退 ★★★★ | `SW#install abort` |
| `install rollback to committed` | IOS-XE：回到已確認的版本 ★★★★ | `SW#install rollback to committed` |
| `show install summary` | ★★★★ IOS-XE：各版本的狀態（I/U/C/D） | `SW#show install summary` |
| `show switch` | ★★★★ 堆疊成員狀態與版本 | `SW#show switch` |
| `show tech-support \| redirect <目的>` | ★★★ 原廠報修時要的完整資訊 | `SW#sh tech \| redirect tftp://...` |
| `write erase` ＋ `delete flash:vlan.dat` | ★★★★★ 徹底清空（不可逆） | `SW#write erase` |

## 練習題

> [!question]- 練習 1：驗證你的備份真的能用
> 在測試機上做一次完整的「備份 → 破壞 → 還原」演練，
> 證明你的備份流程真的可以救回設備。
>
> **參考解答**
>
> ```cisco
> !-- ① 備份
> SW-TEST#copy running-config tftp://10.10.99.20/SW-TEST-backup.cfg
> !!
> 4213 bytes copied in 1.114 secs (3781 bytes/sec)
>
> !-- ② 驗證備份檔（★★★★★ 這一步最重要）
> ```
>
> ```bash
> $ ls -l /srv/tftp/SW-TEST-backup.cfg
> -rw-rw-rw- 1 tftp tftp 4213 Sep  2 16:02 SW-TEST-backup.cfg
> $ grep -c 'interface' /srv/tftp/SW-TEST-backup.cfg
> 26
> ```
>
> ```cisco
> !-- ③ 破壞（★★★★★ 只能在測試機做）
> SW-TEST#configure terminal
> SW-TEST(config)#interface range gi1/0/1 - 10
> SW-TEST(config-if-range)#default interface range gi1/0/1 - 10
> SW-TEST(config)#end
>
> !-- ④ 還原
> SW-TEST#copy tftp://10.10.99.20/SW-TEST-backup.cfg running-config
> Destination filename [running-config]?
> Accessing tftp://10.10.99.20/SW-TEST-backup.cfg...
> Loading SW-TEST-backup.cfg from 10.10.99.20 (via Vlan99): !
> [OK - 4213 bytes]
>
> 4213 bytes copied in 1.221 secs (3450 bytes/sec)
> ```
>
> > ★★★★★ **注意 `copy tftp: running-config` 是「合併」不是「取代」** ——
> > 它只會執行檔案裡的指令，**不會刪掉檔案裡沒有的設定**。
> > 要真正「取代」必須用 `configure replace`。
>
> ```cisco
> !-- ⑤ 更正確的還原方式
> SW-TEST#copy tftp://10.10.99.20/SW-TEST-backup.cfg flash:restore.cfg
> SW-TEST#configure replace flash:restore.cfg list
> SW-TEST#configure replace flash:restore.cfg time 5
> SW-TEST#configure confirm
>
> !-- ⑥ 驗證
> SW-TEST#show archive config differences flash:restore.cfg system:running-config
> !Contextual Config Diffs:
> !No changes were found
> ```
>
> ★★★★★ **這個演練每半年做一次。** 沒演練過的備份不算備份。

> [!question]- 練習 2：`reload in` 的正確與錯誤用法
> 寫出「用 `reload in` 保護一次遠端 trunk 變更」的完整指令序列（含驗證），
> 然後寫出兩種會讓保險失效的錯誤做法。
>
> **參考解答**
>
> **正確序列**：
>
> ```cisco
> SW#show interfaces trunk | begin Vlans allowed on trunk     ← ① 抄現況
> Port        Vlans allowed on trunk
> Gi1/0/24    20,30,99
>
> SW#reload in 5                                              ← ② 上保險
> Reload scheduled in 5 minutes by netadm on vty0 (10.10.99.50)
> Proceed with reload? [confirm]
>
> SW#configure terminal                                       ← ③ 改設定
> SW(config)#interface gi1/0/24
> SW(config-if)#switchport trunk allowed vlan add 40
> SW(config-if)#end
>
> SW#show interfaces trunk | begin Vlans allowed on trunk     ← ④ 驗證
> Port        Vlans allowed on trunk
> Gi1/0/24    20,30,40,99
>
> SW#reload cancel                                            ← ⑤ 解除保險
> SW#write memory                                             ← ⑥ 才存檔
> Building configuration...
> [OK]
> ```
>
> **錯誤做法 1（★★★★★ 最常見）**：
>
> ```cisco
> SW#configure terminal
> SW(config-if)#switchport trunk allowed vlan add 40
> SW(config-if)#end
> SW#write memory              ← ★★★★★ 先存檔了
> SW#reload in 5               ← 保險完全沒用（重開後壞設定還在）
> ```
>
> **錯誤做法 2**：
>
> ```cisco
> SW#reload in 5
> SW#configure terminal
> SW(config-if)#switchport trunk allowed vlan add 40
> SW(config-if)#end
> SW#write memory              ← ★★★★★ 在保險期間存檔，保險失效
> ```
>
> ★★★★★ 兩者的共同錯誤：**在確認成功之前就 `write memory`**。

> [!question]- 練習 3：設計 kron 備份並驗證它真的在跑
> 在測試機上設定每日 02:30 自動備份，並用一個立即執行的 oneshot
> 驗證它真的會產生檔案。
>
> **參考解答**
>
> ```cisco
> SW-TEST(config)#kron policy-list BACKUP-CONFIG
> SW-TEST(config-kron-policy)#cli show running-config | redirect tftp://10.10.99.20/$h-daily.cfg
> SW-TEST(config-kron-policy)#exit
> SW-TEST(config)#kron occurrence DAILY-BACKUP at 2:30 recurring
> SW-TEST(config-kron-occurrence)#policy-list BACKUP-CONFIG
> SW-TEST(config-kron-occurrence)#exit
>
> !-- ★★★★★ 立即驗證，不要等到明天
> SW-TEST(config)#kron occurrence TEST-NOW in 1 oneshot
> SW-TEST(config-kron-occurrence)#policy-list BACKUP-CONFIG
> SW-TEST(config-kron-occurrence)#end
> ```
>
> 等一分鐘後：
>
> ```bash
> $ ls -l /srv/tftp/SW-TEST-daily.cfg
> -rw-rw-rw- 1 tftp tftp 4213 Sep  2 16:34 SW-TEST-daily.cfg
> ```
>
> ```cisco
> SW-TEST#show kron schedule
> Kron Occurrence Schedule
> DAILY-BACKUP inactive, will run again in 9 hours 55 minutes 22 seconds
>
> SW-TEST#configure terminal
> SW-TEST(config)#no kron occurrence TEST-NOW      ← ★★★ 清掉測試用的
> SW-TEST(config)#end
> ```
>
> ★★★★★ 如果沒有產生檔案，最可能的原因是 `copy` 的互動提示卡住 ——
> 這也是為什麼上面用 `show ... | redirect` 而不是 `copy`。
> 若堅持用 `copy`，就要加 `file prompt quiet`。

> [!question]- 練習 4：寫一份升級變更單
> 為一次 IOS 升級寫出完整的變更單，包含變更內容、風險、回退方案、
> 驗收標準、以及中止條件（什麼情況下要立刻停止並回退）。
>
> **參考解答**
>
> ```text
> ═══════════════════════════════════════════════════════
> 網路設備韌體升級變更單
> ═══════════════════════════════════════════════════════
> 變更編號：CHG-2026-0906-001
> 執行人  ：網管組 王XX
> 覆核人  ：網管組長 李XX
> 執行時間：2026-09-06（六）09:00-12:00
> 現場支援：三樓 陳XX（console）
>
> 【變更內容】
>  設備    ：SW-3F-01（WS-C2960X-24TS-L，S/N FOC2148XXXX，10.10.99.31）
>  現行版本：IOS 15.2(7)E3
>  目標版本：IOS 15.2(7)E10
>  變更原因：修補資安通報 XXX 所列高風險漏洞
>  MD5     ：a3f81c2e94d7b0562f8e13c47a9d0b6e（已與官網比對）
>
> 【影響範圍】
>  三樓 40 位使用者、2 台 AP、1 台印表機、2 台 IP 電話
>  預計中斷：5-8 分鐘（重開機）
>
> 【前置條件】★★★★★ 全部滿足才可執行
>  □ Release Notes 已閱讀，無阻擋性已知問題
>  □ 設定檔 ＋ vlan.dat ＋ show tech-support 已備份並驗證
>  □ 升級前基準線（6 份 show 輸出）已存檔
>  □ 映像檔已上傳並 verify /md5 通過
>  □ flash 剩餘空間 > 30 MB（新舊映像檔並存）
>  □ 現場人員就位，console 可用
>  □ 使用者已通知
>
> 【執行步驟】
>  1. 確認現場 console 可用
>  2. no boot system → boot system <新> → boot system <舊> → write memory
>  3. show boot 確認兩個 path，新版在前
>  4. reload（不存檔）
>  5. 等待 5-8 分鐘
>  6. 執行驗收檢查表
>
> 【回退方案】★★★★★
>  觸發條件（任一即中止並回退）：
>   - 開機失敗、卡在 ROMMON
>   - show version 版本不符預期
>   - VLAN 或 trunk 設定遺失
>   - show logging 出現 Traceback 或 level-3 以上錯誤
>   - 使用者實測無法上網
>   - 15 分鐘內未恢復服務
>  回退步驟：
>   a. 對調 boot system 兩行順序（舊版在前）
>   b. write memory
>   c. show boot 確認
>   d. reload
>   e. 確認 show version 回到 15.2(7)E3
>   f. 若設定有異常，configure replace 從 preupgrade 備份還原
>  回退時間估計：8-10 分鐘
>
> 【驗收標準】
>  □ show version = 15.2(7)E10，Last reload reason = Reload Command
>  □ show interfaces status 與升級前基準線一致
>  □ show vlan brief VLAN 完整
>  □ show interfaces trunk allowed/forwarding 一致
>  □ show spanning-tree summary portfast/bpduguard 保留
>  □ show port-security sticky MAC 保留
>  □ show logging 無 Traceback、無 level-3 以上錯誤
>  □ ping 閘道 100%
>  □ 使用者實測：上網、共用資料夾、列印皆正常
>
> 【後續】
>  □ 升級後備份並與 preupgrade 做 diff（應只有 boot system 行不同）
>  □ 更新資產清單版本欄位
>  □ ★★★★ 48 小時觀察期內不做任何設定變更
>  □ 48 小時後回報結果
> ═══════════════════════════════════════════════════════
> ```
>
> ★★★★ 這份格式可以存進 `_表單範本/`，見
> [[040-01-18-guide-網路設備-網路設備盤點與文件化]]。

> [!question]- 練習 5：用 `configure replace` 做逐行回滾
> 在測試機上刻意改壞幾個設定，然後用 `archive` 的歷史版本回滾，
> 全程不重開機。記錄每一步的輸出。
>
> **參考解答**
>
> ```cisco
> !-- ① 確認 archive 已啟用且有版本
> SW-TEST#show archive
> The maximum archive configurations allowed is 14.
> The next archive file will be named flash:/archive/SW-TEST-config-4
>  Archive #  Name
>    1        flash:/archive/SW-TEST-config-1
>    2        flash:/archive/SW-TEST-config-2
>    3        flash:/archive/SW-TEST-config-3 <- Most Recent
>
> !-- ② 手動存一版當基準
> SW-TEST#archive config
> SW-TEST#show archive | include Most Recent
>    4        flash:/archive/SW-TEST-config-4 <- Most Recent
>
> !-- ③ 改壞設定
> SW-TEST#configure terminal
> SW-TEST(config)#interface gi1/0/8
> SW-TEST(config-if)#description BROKEN
> SW-TEST(config-if)#shutdown
> SW-TEST(config-if)#switchport access vlan 1
> SW-TEST(config-if)#end
>
> !-- ④ 看差異
> SW-TEST#show archive config differences flash:/archive/SW-TEST-config-4 system:running-config
> !Contextual Config Diffs:
> +interface GigabitEthernet1/0/8
> + description BROKEN
> + switchport access vlan 1
> + shutdown
> -interface GigabitEthernet1/0/8
> - description USER-TEST-008
> - switchport access vlan 30
>
> !-- ⑤ 假執行，看它會下哪些指令
> SW-TEST#configure replace flash:/archive/SW-TEST-config-4 list
> ...Enter Y if you are sure you want to proceed. ? [no]: y
> !Pass 1
> !List of Commands:
> interface GigabitEthernet1/0/8
>  no shutdown
>  switchport access vlan 30
>  description USER-TEST-008
> end
>
> Total number of passes: 1
> Rollback Done
>
> !-- ⑥ 帶保險執行
> SW-TEST#configure replace flash:/archive/SW-TEST-config-4 time 5
> ...? [no]: y
> Total number of passes: 1
> Rollback Done
>
> !-- ⑦ 驗證
> SW-TEST#show running-config interface gi1/0/8
> interface GigabitEthernet1/0/8
>  description USER-TEST-008
>  switchport access vlan 30
>  switchport mode access
> end
>
> !-- ⑧ 確認保留
> SW-TEST#configure confirm
>
> !-- ⑨ 最終驗證
> SW-TEST#show archive config differences flash:/archive/SW-TEST-config-4 system:running-config
> !Contextual Config Diffs:
> !No changes were found
> ```
>
> ★★★★★ 全程**沒有重開機**，服務完全沒有中斷 ——
> 這是 `configure replace` 相對於 `reload in` 的最大優勢。
> ★★★★ 但注意它**不會回滾 `vlan.dat`**：如果你在步驟 ③ 刪掉了一個 VLAN，
> `configure replace` 救不回來（除非是 transparent 模式）。

## 小測驗

Q1. （選擇）以下哪一個操作會讓 `reload in 5` 的保險完全失效？
(A) 執行 `reload cancel`
(B) 在 `reload in` 之後、確認成功之前執行 `write memory`
(C) 執行 `show reload`
(D) 改了 trunk 的 allowed vlan

Q2. （是非）`copy running-config tftp:` 已經備份了設備上的所有東西，
換一台新設備時把它倒回去就完全一樣了。

Q3. 這行指令會發生什麼事？
`SW#configure replace flash:/archive/SW-config-3 time 5`
接下來你必須做什麼？不做會怎樣？

Q4. 你設了 kron 每日備份，一週後發現一份檔案都沒產生。
最可能的原因是什麼？有哪兩種解法？

Q5. （簡答）升級 IOS 時為什麼要保留舊映像檔？兩行 `boot system` 的順序代表什麼？

Q6. `verify /md5` 算出來的值與官網公布值不一致。你會怎麼處理？
可以「反正只差幾個字元，應該沒關係」就繼續嗎？

Q7. （是非）升級成功後應該立刻把設定調整到最佳狀態，趁維護時段一次做完。

Q8. IOS-XE 上執行 `install activate auto-abort-timer 60` 之後，
設備重開了，你確認一切正常。接下來要做什麼？不做會怎樣？

Q9. 一台 VTP server 模式的交換器要換新機。你把 `running-config` 倒進新機後，
發現 VLAN 全部不見了。原因是什麼？怎麼避免？

Q10. `configure replace` 與 `copy tftp: running-config` 的關鍵差別是什麼？
哪一個才是真正的「還原」？

> [!question]- 測驗答案
> **Q1.** ★★★★★ **(B)**。`reload in` 的保險原理是
> 「未存檔的變更只在 RAM，重開就消失」。
> 一旦 `write memory`，壞設定就寫進 startup-config，
> 重開後照樣載入，保險完全失效。
> 正確順序是：`reload in` → 改設定 → 驗證 → **`reload cancel`** → **`write memory`**。
> 見「觀念說明 → `reload in` 為什麼有效」。
>
> **Q2.** ★★★★★ **否。** 至少漏了兩樣：
> ① **`vlan.dat`（VLAN 資料庫）** —— 在 VTP server／client 模式下
> VLAN 的編號與名稱不在 `running-config` 裡；
> ② **IOS 映像檔** —— 新設備的版本可能不同，某些設定語法可能不相容。
> ★★★★ 另外 `copy tftp: running-config` 是**合併**不是取代，
> 新機上原有的設定不會被清掉。
> 見「觀念說明 → 要備份的其實有三樣東西」。
>
> **Q3.** ★★★★★ 它會把目前的 running-config **逐行調整**成
> `SW-config-3` 那個歷史版本的樣子（不重開機、服務不中斷），
> 並啟動一個 **5 分鐘的回滾計時器**。
> 接下來必須執行 **`configure confirm`**。
> 不做的話，5 分鐘後設定會**自動回滾**回 replace 之前的狀態 ——
> 這是 replace 動作本身的保險（防止你回滾到錯誤的版本）。
> 見「基礎設定 → 步驟 4」。
>
> **Q4.** ★★★★★ 最可能是 **`copy` 指令的互動提示卡住了** ——
> kron 執行的是非互動 CLI，遇到 `Destination filename [xxx]?` 就永遠等下去，
> 備份靜默失敗。
> 兩種解法：
> ① 加 `file prompt quiet`（★★★ 副作用：人工 `copy` 也不再確認）；
> ② ★★★★ 改用 `show running-config | redirect <目的>` 取代 `copy`
> —— `redirect` 不產生互動提示，是比較乾淨的做法。
> ★★★★★ 另外務必用 `kron occurrence ... in 1 oneshot` **立即驗證一次**，
> 不要等一週後才發現。
> 見「基礎設定 → 步驟 5」。
>
> **Q5.** ★★★★★ 保留舊映像檔是**唯一的自動回退機制**。
> `boot system` 可以寫多行，**順序就是開機嘗試的順序**：
> 第一行的映像檔開不起來（損毀、不存在），設備會自動嘗試第二行。
> 所以標準寫法是「**新版在第一行、舊版在第二行**」——
> 新版有問題時設備自己會退回舊版開機。
> 要主動回退時，只要把兩行順序對調 ＋ `write memory` ＋ `reload`。
> ★★★★ 沒有舊映像檔的話，新版開不起來就只能靠 ROMMON ＋
> xmodem（27 MB 要傳好幾小時）或現場 TFTP。
> 見「進階設定與調校 → 步驟 3、6」。
>
> **Q6.** ★★★★★ **刪掉重傳，絕對不能繼續。**
> ```cisco
> SW#delete flash:c2960x-universalk9-mz.152-7.E10.bin
> SW#copy scp://... flash:
> SW#verify /md5 flash:... <官網值>
> ```
> 「只差幾個字元」在雜湊值上沒有意義 —— MD5 有雪崩效應，
> 檔案差一個 bit 雜湊值就完全不同。不一致代表檔案損毀
> （或更糟：被竄改）。
> ★★★★★ 用損毀的映像檔開機的結果是**設備卡在 ROMMON**，
> 需要現場 console ＋ 數小時的 xmodem 傳輸才能救回來。
> 傳三次都不一致就換傳輸協定或換來源主機。
> 見「進階設定與調校 → 步驟 2」。
>
> **Q7.** ★★★★★ **否，恰恰相反。**
> 升級後應該**至少 48 小時不做任何設定變更**。
> 理由：新版 IOS 可能引入新的設定語法，
> 你改了設定並 `write memory` 之後，
> **回退到舊版時舊版可能不認得那些語法，那些行會被靜默丟棄**，
> 造成回退後設定不完整。
> 保持 startup-config 與升級前一致，回退才是乾淨的。
> 見「進階設定與調校 → 步驟 6」的 warning 區塊。
>
> **Q8.** ★★★★★ 必須執行 **`install commit`**。
> `auto-abort-timer 60` 的意思是「60 分鐘內沒有 commit 就自動回退到舊版」——
> 這是 IOS-XE 內建的 commit confirmed 機制。
> 不做 `install commit` 的話，**60 分鐘後設備會自己重開回舊版本**，
> 你的升級白做了（而且會在非預期的時間再中斷一次服務）。
> 可以用 `show install summary` 確認狀態：
> `U` = Activated & Uncommitted（還沒確認）、
> `C` = Activated & Committed（已確認）。
> 見「進階設定與調校 → IOS-XE 的 install 模式」。
>
> **Q9.** ★★★★★ 因為在 **VTP server／client 模式下，
> VLAN 的編號與名稱存在 `flash:vlan.dat`，不在 `running-config` 裡**。
> 你倒進去的設定檔只有「哪個埠屬於哪個 VLAN」，
> 沒有「有哪些 VLAN」的定義。
> **避免方式（兩種，建議第二種）**：
> ① 備份時一併 `copy flash:vlan.dat tftp://...`，換機時倒回去並 reload；
> ② ★★★★★ **把所有交換器切成 `vtp mode transparent`** ——
> 這樣 VLAN 定義會進 `running-config`，設定檔備份自然涵蓋它，
> 而且順便免除了 VTP 誤覆蓋全網 VLAN 的風險。
> 見「觀念說明 → 要備份的其實有三樣東西」與
> [[040-01-11-guide-Cisco-VLAN與Trunk設定]]。
>
> **Q10.** ★★★★★
> - `copy tftp: running-config` 是 **「合併」**：
>   它把檔案裡的每一行當成指令逐行執行，
>   **不會刪掉檔案裡沒有的設定**。所以設備上多出來的東西會留著。
> - `configure replace <檔案>` 是 **「取代」**：
>   它計算目前設定與目標檔案的差異，
>   **同時執行「新增缺少的」與「刪除多餘的」**，
>   讓 running-config 真正等於目標檔案。
>
> **`configure replace` 才是真正的還原。**
> ★★★★★ 但它有一個致命前提：**目標檔案必須是完整的設定檔**。
> 拿一份片段（例如 `show run | section` 的輸出）去 replace，
> 它會把「檔案裡沒有的東西全部刪掉」—— 等於清空設備。
> 執行前務必先用 `list` 選項假執行檢查。
> 見「基礎設定 → 步驟 4」與「練習 1」。

## 延伸閱讀

- [[040-01-10-cmd-Cisco-IOS-基礎操作]] —— `reload in`、running/startup、`show flash:`
- [[040-01-11-guide-Cisco-VLAN與Trunk設定]] —— ★★★★ `vlan.dat` 與 VTP transparent
- [[040-01-12-guide-Cisco-管理IP與遠端存取]] —— SSH／SCP 的前置設定、AAA 的陷阱
- [[040-01-13-guide-Cisco-埠設定與安全]] —— sticky MAC 為什麼一定要 `write memory`
- [[040-01-09-svc-Juniper-設定備份與韌體升級]] —— 主線平台的做法（★ rollback 是內建的）
- [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]] —— 兩邊指令一頁式對照
- [[040-01-18-guide-網路設備-網路設備盤點與文件化]] —— 變更單與資產清單格式
- [[040-01-19-guide-網路設備-交換器汰換與遷移實務]] —— 換機時的完整流程
- [[060-01-01-01-guide-Git-觀念與初次設定]] —— 設定檔備份納入版本控管
- [[020-02-01-04-svc-sshd-伺服器端設定]] —— 備份主機的 SSH 安全設定
- [[090-02-02-guide-防火牆-ufw基礎與實務]] —— 限制 TFTP／SCP 的來源
- [[040-02-12-guide-機房-設備生命週期管理]] —— 韌體版本管理與汰換規劃
