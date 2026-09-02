---
title: "Linux 基礎 常見故障排除"
desc: "依症狀查的故障排除索引：判斷分流、處置步驟與一頁式急救卡，原理連回原文"
aliases: [Linux 基礎故障排除, Linux 基礎排錯, Linux 故障排除手冊]
tags: [群組/Linux, 主題/故障排除]
category: Linux基礎
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: []
updated: 2026-09-02
---

# Linux 基礎 常見故障排除

> [!abstract] 怎麼用這份手冊
> - 依「你看到什麼症狀」查，不是依「這屬於什麼技術」查
> - 找到症狀 → 看判斷分流 → 照處置步驟做 → 想懂原理再點進原文
> - ★★★★ 緊急時直接跳到最下面的「一頁式急救卡」
> - ★★★★★ 本手冊**不重講原理**。每個情境結尾的「原理詳見」就是原文入口，
>   照著點進去看，不要在這裡找教學。
> - ★★★★★ 動手之前先問自己一句：**這台機器現在是「壞了」還是「正在被入侵」？**
>   兩者的第一動作完全相反 —— 前者要修，後者要先保存現場。判斷不了就看
>   「什麼時候該停手求援」。

## 快速索引（依症狀）

| 症狀（你會看到的） | 最可能的原因 | 先下這個指令 | 原理詳見 |
| --- | --- | --- | --- |
| ★★★★★ 開機停在 `You are in emergency mode` | `/etc/fstab` 有一行掛不起來，通常是剛加的那行 | `journalctl -xb -p err` | [[020-01-25-guide-Linux-開機流程與GRUB救援]] |
| ★★★★★ 畫面只剩 `grub rescue>` | GRUB 找不到 `/boot`：分割改過、磁碟順序變了、MBR 被蓋 | `ls`（在 grub rescue 提示下） | [[020-01-25-guide-Linux-開機流程與GRUB救援]] |
| ★★★★★ `No space left on device`，但 `df -h` 還有空間 | inode 用盡，或檔案已刪除卻仍被程序持有 | `df -i` | [[020-01-15-cmd-Linux-磁碟分割與掛載]] |
| ★★★★★ `mdadm` 陣列 `[U_]`、`zpool status` 出現 `DEGRADED` | 一顆磁碟掉了，**目前還活著但沒有冗餘** | `cat /proc/mdstat; zpool status -x` | [[020-01-29-guide-Linux-網路儲存與軟體RAID]] |
| ★★★★★ `systemctl start` 失敗，`status` 顯示 `status=203/EXEC` | 執行檔路徑錯、沒有 `+x`、或 shebang 指向不存在的直譯器 | `systemctl status <服務> -l --no-pager` | [[020-01-17-cmd-Linux-systemd服務管理]] |
| ★★★★ 服務半夜自己消失，日誌沒有任何錯誤 | OOM Killer 把它殺了 | `journalctl -k \| grep -i 'killed process'` | [[020-01-10-cmd-Linux-程序管理與訊號]] |
| ★★★★ `Permission denied`，但檔案明明是 `777` | 上層目錄少 `x`、ACL mask、SELinux、唯讀掛載、`+i` 屬性 | `namei -l <完整路徑>` | [[020-01-08-cmd-Linux-檔案權限與擁有者]] |
| ★★★★ 手動跑好好的腳本，放進 cron 就失敗 | cron 的 `PATH` 只有 `/usr/bin:/bin`，也不讀 `.bashrc` | `crontab -l; grep CRON /var/log/syslog` | [[020-01-18-guide-Linux-排程工作]] |
| ★★★★ `command not found`，但 `ls` 看得到那個執行檔 | `PATH` 沒有它、`sudo` 的 `secure_path`、shell 的路徑快取 | `type -a <指令>; echo "$PATH"` | [[020-01-20-guide-Linux-環境變數與設定檔]] |
| ★★★★ `kill -9` 也殺不掉的程序 | `D` 狀態（不可中斷 I/O）或 `Z` 殭屍 —— 兩者都不是 kill 能解決的 | `ps -eo pid,stat,wchan:20,comm \| awk '$2~/^[DZ]/'` | [[020-01-10-cmd-Linux-程序管理與訊號]] |
| ★★★★ `Could not get lock /var/lib/dpkg/lock-frontend` | 另一個 apt／`unattended-upgrades` 正在跑 | `sudo fuser -v /var/lib/dpkg/lock-frontend` | [[020-01-14-guide-Linux-套件管理]] |
| ★★★★ `dpkg was interrupted, you must manually run …` | 上一次安裝被中斷（多半是磁碟滿或斷電） | `sudo dpkg --configure -a` | [[020-01-14-guide-Linux-套件管理]] |
| ★★★★ `NO_PUBKEY`／`Release file is not valid yet` | 金鑰沒裝，或**本機時間比套件庫還早** | `timedatectl; apt update` | [[020-01-28-cmd-Linux-時間同步NTP與chrony]] |
| ★★★★ 網路不通，但不知道斷在哪一層 | 介面、IP、路由、DNS、防火牆、服務，六層任一層 | `ip -br a; ip route get 1.1.1.1` | [[020-01-16-cmd-Linux-網路基礎指令]] |
| ★★★★ `journalctl -b -1` 說 `Specifying boot ID has no effect` | journald 沒持久化，重開機日誌就沒了 | `journalctl --disk-usage; ls /var/log/journal` | [[020-01-19-guide-Linux-日誌系統]] |
| ★★★★ 憑證突然全部失效、AD 登入失敗、日誌時間亂跳 | 系統時間跑掉了 | `timedatectl; chronyc tracking` | [[020-01-28-cmd-Linux-時間同步NTP與chrony]] |
| ★★★★ `apt upgrade` 失敗說 `/boot` 沒空間 | 舊核心堆積，`/boot` 是獨立且很小的分割 | `df -h /boot; dpkg -l 'linux-image-*'` | [[020-01-25-guide-Linux-開機流程與GRUB救援]] |
| ★★★★ 重開機後裝置名稱換了、掛載點跑掉 | `/dev/sdb` 這種名稱**不保證順序**，fstab 應該寫 UUID | `lsblk -f; blkid` | [[020-01-15-cmd-Linux-磁碟分割與掛載]] |
| ★★★ 新硬碟插上去 `lsblk` 看不到 | 熱插拔後核心沒重掃，或線材／背板／RAID 卡沒認到 | `dmesg -T \| tail -20; lsblk` | [[020-01-27-cmd-Linux-硬體資訊與裝置管理]] |
| ★★★ 腳本 `bad interpreter: /bin/bash^M` | 檔案是 CRLF 行尾（從 Windows 帶過來的） | `file <腳本>` | [[020-01-21-cmd-Linux-Shell腳本入門]] |
| ★★★ 腳本中間出錯卻照樣往下跑，最後刪錯東西 | `set -e` 有六種不觸發的情況，而且變數沒引號會展開成空 | `bash -n <腳本>; shellcheck <腳本>` | [[020-01-22-guide-Linux-Shell腳本進階]] |
| ★★★ 改了設定檔卻完全沒生效 | 沒 reload、被 drop-in 蓋掉、改到不是實際讀的那個檔 | `systemctl cat <服務>` | [[020-01-17-cmd-Linux-systemd服務管理]] |
| ★★★ `sudo` 突然全部不能用 | `/etc/sudoers` 語法錯或權限被改寬 | 主控台以 root 登入 `visudo -c` | [[020-01-09-cmd-Linux-使用者與群組管理]] |
| ★★★ 自己編譯裝好了，跑起來卻還是舊版本 | `PATH` 順序、shell 路徑快取、`ldconfig` 沒跑 | `type -a <指令>; ldd $(which <指令>)` | [[020-01-30-guide-Linux-原始碼安裝與系統升級]] |
| ★★★ NFS 掛載點一 `ls` 就整個終端卡死 | `hard` 掛載遇到伺服器不通，程序會停在 `D` 狀態等下去 | `findmnt -t nfs4,nfs; ping <NFS 主機>` | [[020-01-29-guide-Linux-網路儲存與軟體RAID]] |

## 依情境展開

### ★★★★★ 情境一：開機掉進 emergency mode，或只剩 `grub rescue>`

**現象**：三種畫面，代表**卡在開機鏈的不同階段**，處理方向完全不同。

```text
（A）error: no such partition.
     Entering rescue mode...
     grub rescue>                      ★★★★★ 卡在 GRUB，核心還沒被載入

（B）VFS: Unable to mount root fs on unknown-block(0,0)
     Kernel panic - not syncing         ★★★★★ 核心載入了，但 initramfs／根裝置有問題

（C）You are in emergency mode. After logging in, type "journalctl -xb" to view
     system logs, "systemctl reboot" to reboot, "systemctl default" or "exit"
     to boot into default mode.
     Give root password for maintenance:  ★★★★ systemd 已經在跑，是掛載或某個 unit 失敗
```

**判斷分流**：看得到 `Give root password` 就是（C），這是**最好處理**的一種 ——
系統活著，你有一個能用的 shell。

```text
畫面有 grub rescue>／grub>        → 走【1】
Kernel panic + unknown-block(0,0) → 走【2】
emergency / maintenance mode      → 走【3】（九成是 fstab）
畫面卡在廠商 logo，什麼都沒有      → 這是韌體階段，不是 Linux 問題，查 BIOS/RAID 卡
```

**處置步驟**：

【1】★★★★ `grub rescue>` 底下只有極少數指令可用。先找出 `/boot` 在哪一個分割。

```text
grub rescue> ls
(hd0) (hd0,gpt1) (hd0,gpt2) (hd0,gpt3)
grub rescue> ls (hd0,gpt2)/
lost+found/ grub/ vmlinuz-6.8.0-45-generic initrd.img-6.8.0-45-generic
```

找到有 `grub/` 的那個分割，接著把 GRUB 的核心模組載回來：

```text
grub rescue> set prefix=(hd0,gpt2)/grub
grub rescue> set root=(hd0,gpt2)
grub rescue> insmod normal
grub rescue> normal
```

★★★★ 這樣只是**這一次**開得起來，不是修好。進系統後一定要補：

```bash
sudo grub-install /dev/sda && sudo update-grub    # RHEL 系：grub2-mkconfig -o /boot/grub2/grub.cfg
```

【2】★★★★ Kernel panic 找不到根檔案系統：先在 GRUB 選單挑**上一版核心**開機。
開機選單看不到就在 GRUB 畫面按住 `Shift`（BIOS）或 `Esc`（UEFI），進 `Advanced options`。

- 舊核心開得起來 → ★★★★ 是**新核心的 initramfs 壞了或沒產生完整**（常見於 `/boot` 滿了），
  進系統後 `sudo update-initramfs -u -k all`（RHEL：`sudo dracut -f --regenerate-all`）
- 舊核心也開不起來 → 是根裝置本身的問題（RAID 沒組起來、LVM 沒啟用、UUID 變了），走【4】

【3】★★★★★ emergency mode 九成是 `/etc/fstab`。先問系統是哪一行卡住：

```bash
# 在 maintenance shell 裡（輸入 root 密碼後）
$ journalctl -xb -p err --no-pager | tail -20
Sep 02 03:12:41 srv-app01 systemd[1]: Failed to mount /data.
Sep 02 03:12:41 srv-app01 systemd[1]: Dependency failed for Local File Systems.
$ systemctl --failed
  UNIT           LOAD   ACTIVE SUB    DESCRIPTION
● data.mount     loaded failed failed /data
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `Failed to mount /xxx` | fstab 那行的 UUID／裝置／選項錯 | 走下面的三步驟 |
| ★★★★ `Dependency failed for Local File Systems` | 只是上一條的連鎖反應 | 修好真正失敗的那個 `.mount` |
| ★★★ `Timed out waiting for device /dev/…` | 裝置根本不存在（拔掉的隨身碟、還沒接的 SAN） | 該行加 `nofail`，或註解掉 |
| ★★★★ 根檔案系統是唯讀，改不了 fstab | 尚未進入 `sysinit` 完成階段 | 先 `mount -o remount,rw /` |

```bash
$ mount -o remount,rw /                       # ★★★★ 沒這行你連 fstab 都存不了
$ blkid | grep -i data                        # 對照 fstab 裡的 UUID 是不是同一串
/dev/sdb1: UUID="9f3c2b41-1c7a-4d0e-b2a1-77c9e0f512aa" TYPE="ext4"
$ vi /etc/fstab                               # 修正或先在該行最前面加 # 註解掉
$ mount -a && echo '全部掛載成功'             # ★★★★★ 一定要跑到看見這句才敢重開
$ systemctl daemon-reload && systemctl default
```

【4】以上都救不回來時，用安裝媒體開 Live 環境做 chroot 修復。

```bash
$ sudo mount /dev/sda3 /mnt                            # 根分割
$ sudo mount /dev/sda2 /mnt/boot                       # 有獨立 /boot 才要
$ sudo mount /dev/sda1 /mnt/boot/efi                   # UEFI 才要
$ for d in dev proc sys run; do sudo mount --bind /$d /mnt/$d; done
$ sudo chroot /mnt /bin/bash
# grub-install /dev/sda && update-grub && update-initramfs -u -k all
```

> [!danger] ★★★★★ 在 Live 環境裡千萬不要對「還沒確認是哪一顆」的磁碟下手
> `mkfs`、`dd`、`sgdisk --zap-all`、`parted mklabel` 都是**一秒鐘毀掉整顆磁碟**的指令，
> 而且 Live 環境裡的 `/dev/sda` 很可能不是你平常看到的那一顆。
> 動手前一律先 `lsblk -f` 加 `blkid` 對照序號與 UUID，確認到磁碟序號那一層。

**原理**：開機分五個階段（韌體 → GRUB → 核心 → initramfs → systemd target），
你看到的畫面就決定了卡在哪一階段，也就決定了能用什麼工具救。
　→ 原理詳見 [[020-01-25-guide-Linux-開機流程與GRUB救援]]

**預防**：
- ★★★★★ 改完 `/etc/fstab` **一定要先 `mount -a` 驗證**再重開機，這一步省不得
- ★★★★ 非必要的掛載一律加 `nofail`（外接、NFS、備援磁碟），不要讓它有權阻擋開機
- ★★★★ 核心升級後**不要立刻刪舊核心**，至少留兩個版本當退路
- ★★★ 虛擬機在動開機相關設定前先拍快照（[[050-01-03-06-svc-PVE-備份與還原]]）

### ★★★★★ 情境二：`No space left on device`，可是 `df -h` 明明還有空間

**現象**：服務寫不進去、日誌停止、資料庫報錯，但容量看起來很正常。

```text
sh: cannot create /var/www/app/storage/logs/laravel.log: No space left on device
OSError: [Errno 28] No space left on device
```

**判斷分流**：★★★★★ 三個可能，**用兩個指令就能分開**。

```bash
$ df -h /var; df -i /var
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda3        50G   28G   20G  59% /var          # ★ 容量還有
Filesystem      Inodes  IUsed IFree IUse% Mounted on
/dev/sda3       3276800 3276800    0  100% /var     # ★★★★★ inode 用光了
```

```text
IUse% 100%              → inode 用盡          →【1】
兩個都沒滿，卻寫不進去  → 已刪除但被持有的檔案 →【2】
Use% 100% 真的滿了      → 找出誰吃掉空間      →【3】
滿的是 /boot            → 舊核心堆積          →【4】
```

**處置步驟**：

【1】★★★★ inode 用盡＝**小檔案太多**，跟總容量無關。先找出檔案數最多的目錄。

```bash
$ sudo find /var -xdev -printf '%h\n' | sort | uniq -c | sort -rn | head -5
 2841903 /var/spool/postfix/maildrop
   18422 /var/lib/php/sessions
```

★★★ `-xdev` 很重要，不加會跨到別的檔案系統去，數字會失真。
常見元凶：PHP session、失敗的郵件佇列、沒清的暫存檔、爆量的小日誌。
清理時**不要**直接 `rm -rf` 整個目錄（服務可能需要那個目錄存在），用條件刪：

```bash
$ sudo find /var/lib/php/sessions -type f -mtime +7 -delete
$ df -i /var | tail -1
/dev/sda3       3276800 412883 2863917   13% /var
```

【2】★★★★★ 這是最容易卡住新手的一種：**檔案已經 `rm` 掉了，但還有程序開著它**，
所以空間不會還回來，直到那個程序關閉描述符或結束。

```bash
$ sudo lsof +L1 | head
COMMAND   PID USER   FD   TYPE DEVICE   SIZE/OFF NLINK  NODE NAME
nginx    1842 www-data 5w  REG    8,3 21474836480     0 26214 /var/log/nginx/access.log (deleted)
```

★★★★ `NLINK` 是 `0`、名稱後面帶 `(deleted)` 就是它。**正確解法是讓程序重開檔案**：

```bash
$ sudo systemctl reload nginx        # 或該服務自己的 reopen 機制
$ df -h /var | tail -1               # 空間立刻回來
```

實在無法 reload 又急著救命時，可以把描述符截斷（★★★ 資料會沒，但服務不會斷）：

```bash
$ sudo truncate -s 0 /proc/1842/fd/5
```

【3】★★★★ 真的滿了：由上而下逐層縮小範圍，不要一開始就 `du -sh /*`（太慢又會跨檔案系統）。

```bash
$ sudo du -xh --max-depth=1 /var 2>/dev/null | sort -h | tail -5
1.2G    /var/lib
3.4G    /var/cache
22G     /var/log            # ★★★★ 就是它
$ sudo du -xh --max-depth=1 /var/log | sort -h | tail -3
21G     /var/log/journal
```

- 元凶是 `/var/log/journal` → 跳**情境十一**（journald 沒設上限）
- 元凶是某支應用的日誌 → logrotate 沒生效，跳**情境十一**【3】
- 元凶是 `/var/cache/apt` → `sudo apt clean`（RHEL：`sudo dnf clean all`）
- ★★★ 別忘了看看有沒有人把備份檔丟在 `/`：`sudo find / -xdev -type f -size +1G`

【4】★★★★ `/boot` 滿了通常在升級時才爆出來，訊息長這樣：

```text
gzip: stdout: No space left on device
E: mkinitramfs failure cpio 141 gzip 1
update-initramfs: failed for /boot/initrd.img-6.8.0-45-generic with 1.
dpkg: error processing package linux-image-6.8.0-45-generic (--configure):
```

```bash
$ df -h /boot; dpkg -l 'linux-image-*' | grep ^ii | awk '{print $2}'
$ uname -r                                   # ★★★★★ 這個版本絕對不能刪
$ sudo apt autoremove --purge                # 先用這個，它會保留現用與前一版
$ sudo dpkg --configure -a && sudo apt -f install   # 補完被中斷的安裝
```

> [!danger] ★★★★★ 不要手動 `rm /boot/vmlinuz-*`
> 直接刪檔案不會更新套件資料庫，也不會重建 GRUB 選單，下次開機可能會選到一個
> 已經不存在的核心。一律走 `apt autoremove --purge` 或
> `apt purge linux-image-<版本>`，而且**絕不刪除 `uname -r` 顯示的那一版**。

**原理**：檔案系統同時管理「資料區塊」與「inode」兩種資源，任一種用盡都會回報
`ENOSPC`；而 `unlink` 只是移除目錄項目，真正釋放空間要等最後一個開啟中的
描述符關閉，這就是 `df` 與 `du` 對不起來的原因。
　→ 原理詳見 [[020-01-15-cmd-Linux-磁碟分割與掛載]]、[[020-01-10-cmd-Linux-程序管理與訊號]]

**預防**：
- ★★★★★ 磁碟使用率**在 80% 就要告警**，不要等 95%（[[100-01-03-guide-日誌-系統監控與告警]]）
- ★★★★ 每個會寫日誌的應用都要有對應的 logrotate 設定，新服務上線就一併做
- ★★★★ journald 一定要設 `SystemMaxUse=`，預設是「用到磁碟的 10%」，很容易失控
- ★★★ 每月維護時看一次 `df -i`，inode 的問題都是慢慢累積的（[[100-02-04-guide-維運-每月維護作業]]）

### ★★★★★ 情境三：`systemctl start` 起不來，`status` 看不出所以然

**現象**：`Job for xxx.service failed because the control process exited with error code.`

★★★★★ 第一件事：**不要只看 `systemctl status` 的前幾行**，那通常只是結論不是原因。

**判斷分流**：一次把三份資訊看齊 —— 狀態、實際生效的 unit、完整日誌。

```bash
$ systemctl status myapp -l --no-pager
● myapp.service - My Application
     Loaded: loaded (/etc/systemd/system/myapp.service; enabled)
     Active: failed (Result: exit-code) since Tue 2026-09-02 03:40:12 CST
    Process: 4821 ExecStart=/opt/myapp/bin/start.sh (code=exited, status=203/EXEC)
$ journalctl -xeu myapp --no-pager | tail -30
```

★★★★★ 關鍵在 `status=` 後面那個數字，systemd 的專屬退出碼直接指出問題：

| `status=` | 意思 | 檢查什麼 |
| --- | --- | --- |
| ★★★★★ `203/EXEC` | 執行檔跑不起來 | 路徑打錯／沒有 `+x`／shebang 指向不存在的直譯器／CRLF 行尾 |
| ★★★★ `200/CHDIR` | `WorkingDirectory=` 不存在 | `ls -ld <該目錄>` |
| ★★★★ `217/USER` | `User=` 這個帳號不存在 | `getent passwd <帳號>` |
| ★★★★ `226/NAMESPACE` | `ProtectSystem`／`ReadWritePaths` 擋住了 | 暫時註解掉那幾行測試 |
| ★★★ `208/STDOUT`、`209/STDERR` | 指定的日誌檔或 socket 開不了 | 目錄權限 |
| ★★★★ `1/FAILURE` 或程式自己的碼 | **程式本身**啟動失敗 | 這時要看程式的日誌，不是 systemd 的 |
| ★★★ `signal=KILL` / `killed` | 被 OOM 或 `TimeoutStartSec` 砍掉 | 跳**情境七**與**情境八** |

**處置步驟**：

【1】★★★★★ `203/EXEC` 是最常見的一種，三步驟一定能找到：

```bash
$ systemctl cat myapp | grep -E 'ExecStart|User|WorkingDirectory'
ExecStart=/opt/myapp/bin/start.sh
$ ls -l /opt/myapp/bin/start.sh
-rw-r--r-- 1 root root 412 Sep  2 03:38 /opt/myapp/bin/start.sh   # ★★★★ 沒有 x
$ head -1 /opt/myapp/bin/start.sh | cat -A
#!/bin/bash^M$                                                     # ★★★★ CRLF 行尾
```

```bash
$ sudo chmod +x /opt/myapp/bin/start.sh
$ sudo sed -i 's/\r$//' /opt/myapp/bin/start.sh
$ sudo -u myapp /opt/myapp/bin/start.sh          # ★★★★★ 先用「服務要用的身分」手動跑一次
```

★★★★★ 「用 `sudo -u <服務帳號>` 手動跑一次」是整個排錯裡投報率最高的一步 ——
它會直接印出真正的錯誤訊息，而 systemd 只會給你一個數字。

【2】★★★★ 程式自己的退出碼（`status=1`）：systemd 幫不了你，要去看程式的輸出。

```bash
$ journalctl -u myapp --since '10 min ago' --no-pager -o cat | tail -20
Error: bind EADDRINUSE 0.0.0.0:3000
$ sudo ss -lntp | grep :3000
LISTEN 0 511 0.0.0.0:3000 0.0.0.0:* users:(("node",pid=3312,fd=20))
```

- `EADDRINUSE` → 埠被占用（多半是舊的程序沒收乾淨，或 `Restart=` 打架）
- `Permission denied` 開檔 → 走【3】
- `unknown option` 之類 → 設定檔或環境變數傳錯，看 `systemctl show -p Environment myapp`

【3】★★★★ 手動跑得起來、systemd 起不來 —— 兩者的**環境不一樣**，這是本質差異：

```bash
$ systemctl show myapp -p Environment -p User -p WorkingDirectory -p LimitNOFILE
Environment=NODE_ENV=production
User=myapp
WorkingDirectory=/opt/myapp
LimitNOFILE=1024
```

| 差異 | 為什麼 | 解法 |
| --- | --- | --- |
| ★★★★★ `PATH` 不同 | systemd 不讀 `.bashrc`／`.profile`，`PATH` 是最小集合 | `ExecStart` 一律寫**絕對路徑** |
| ★★★★ 找不到環境變數 | 同上，`export` 在互動 shell 才有效 | 用 `EnvironmentFile=` |
| ★★★★ 開檔數不足 | `ulimit` 只影響登入 shell，服務走 unit 的 `LimitNOFILE=` | 在 unit 裡設定，見 [[020-01-26-guide-Linux-核心模組與sysctl調校]] |
| ★★★ SELinux 擋住 | 手動跑是你的 context，服務是另一個 | `sudo ausearch -m avc -ts recent` |

【4】★★★ `Unit xxx.service is masked.` 是完全不同的一回事 ——
有人（或某個套件）刻意把它禁掉了：

```bash
$ systemctl is-enabled myapp
masked
$ sudo systemctl unmask myapp && sudo systemctl enable --now myapp
```

【5】★★★ 相依順序問題：服務起來了但連不到資料庫、或開機時順序不對。

```bash
$ systemctl list-dependencies myapp
$ systemd-analyze verify /etc/systemd/system/myapp.service    # 語法與相依檢查
```

★★★★ `After=` 只保證**啟動順序**，不保證對方「已經可以服務」。
資料庫需要暖機時，正解是在應用端做重試，不是一直加 `After=`。

**原理**：`systemctl status` 給的是結果，`journalctl -xeu` 給的是過程，
而 `systemctl cat` 給的是**實際生效的 unit 內容**（含 drop-in 覆寫）——
三個一起看才拼得出全貌。
　→ 原理詳見 [[020-01-17-cmd-Linux-systemd服務管理]]

**預防**：
- ★★★★★ 新服務第一次部署，先用 `sudo -u <服務帳號>` 手動跑通再寫成 unit
- ★★★★ `ExecStart` 只寫絕對路徑，環境變數放 `EnvironmentFile=`，不要依賴 shell 設定檔
- ★★★ 改完 unit 記得 `systemctl daemon-reload`，忘了它會讓你以為「改了沒用」
- ★★★ 服務要有自動復原與看門狗設定（[[020-02-02-04-svc-systemd-服務自動復原與看門狗]]）

### ★★★★ 情境四：`Permission denied`，但權限明明是 777

**現象**：`chmod 777` 都下了，程式還是說沒權限；或 `ls` 得到但 `cat` 不行。

```text
-bash: /srv/data/report.csv: Permission denied
PHP Warning: file_put_contents(/srv/data/out.txt): Failed to open stream: Permission denied
```

**判斷分流**：★★★★★ 一個指令看完整條路徑上的每一層 —— **權限是逐層檢查的**。

```bash
$ namei -l /srv/data/report.csv
f: /srv/data/report.csv
 drwxr-xr-x root root /
 drwxr-x--- root ops  srv          # ★★★★ 你不在 ops 群組就到此為止
 drwxrwxrwx root root data
 -rwxrwxrwx root root report.csv   # 檔案本身 777 一點用都沒有
```

```text
中間某層少了 x（對你而言）→【1】 —— 最常見，占一半以上
每層都通過卻仍被拒        →【2】 ACL／SELinux／掛載選項／檔案屬性
只有寫入被拒，讀取正常    →【3】
```

**處置步驟**：

【1】★★★★★ 目錄的 `x` 是「能不能穿過去」的權限，跟 `r`（能不能列出內容）是兩回事。
路徑上**任何一層**缺 `x`，後面全部到不了。

```bash
$ id www-data
uid=33(www-data) gid=33(www-data) groups=33(www-data)
$ sudo -u www-data namei -l /srv/data/report.csv     # ★★★★ 用真正的身分去測
$ sudo chmod o+x /srv                                # 只補 x，不要補 r
```

★★★★ 只補 `x` 不補 `r`：這樣別人可以「穿過」但無法「列出」目錄內容，是最小權限的正解。

【2】★★★★ 每層都通過還是被拒，依序查這四個：

```bash
$ getfacl /srv/data/report.csv | grep -E '^(user|group|mask)'
user::rwx
group::rwx
mask::r--                       # ★★★★ mask 把 group 與具名項全部壓成 r
$ ls -Z /srv/data/report.csv    # RHEL：SELinux context
unconfined_u:object_r:default_t:s0 /srv/data/report.csv    # ★★★★ 不是 httpd_sys_rw_content_t
$ findmnt -no OPTIONS /srv
rw,relatime,noexec,nosuid       # ★★★ noexec：這裡的檔案不能執行
$ lsattr /srv/data/report.csv
----i--------e------- /srv/data/report.csv                 # ★★★★ i = immutable，root 也不能改
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `getfacl` 出現 `mask::r--` | ACL mask 壓住了實際權限 | `setfacl -m m::rwx <檔案>` |
| ★★★★ RHEL 上權限全對仍被拒 | SELinux context 不對（`cp` 或手動建目錄造成） | `sudo restorecon -Rv /srv/data` |
| ★★★★ `lsattr` 有 `i` | 檔案被設成 immutable | `sudo chattr -i <檔案>`（先想清楚為什麼有人設它） |
| ★★★ 掛載選項有 `ro` | 檔案系統唯讀（常見於磁碟出錯後自我保護） | ★★★★★ **先查 `dmesg`，不要急著 remount** |
| ★★★ 掛載選項有 `noexec` | 這個分割禁止執行 | 把程式搬到別的分割，不要拿掉 `noexec` |
| ★★★ `/tmp` 裡刪不掉別人的檔 | sticky bit（`drwxrwxrwt`）本來就這樣設計 | 這是正常的，用 root 或請檔案擁有者刪 |

> [!warning] ★★★★★ 檔案系統突然變唯讀＝硬體警訊，不是權限問題
> `dmesg -T | grep -iE 'I/O error|remount.*read-only|EXT4-fs error'` 一有輸出，
> 就代表磁碟或控制器出事，系統為了保護資料主動改成唯讀。
> 這時 `mount -o remount,rw` 只是把警報關掉、繼續往壞掉的磁碟寫，
> 正確做法是**先備份資料再換磁碟**。

【3】★★★ 讀得到寫不進去，多半是磁碟滿（回**情境二**）、配額用盡、或唯讀掛載：

```bash
$ quota -s -u appuser 2>/dev/null      # 有設磁碟配額時
$ df -h /srv; df -i /srv
```

**原理**：`rwx` 對檔案與對目錄意義完全不同 —— 目錄的 `x` 是「進入／穿越」，
`r` 是「列出檔名」。而 POSIX ACL 的 `mask` 是所有具名項與群組項的上限，
SELinux 則是在 DAC 通過之後**再檢查一次**的獨立機制。
　→ 原理詳見 [[020-01-08-cmd-Linux-檔案權限與擁有者]]、[[090-02-07-guide-防護-SELinux與AppArmor]]

**預防**：
- ★★★★★ 永遠不要用 `chmod -R 777` 當解法 —— 它幾乎不會真的修好問題，卻一定會製造資安缺口
- ★★★★ 用 `sudo -u <服務帳號> <指令>` 來重現問題，不要用 root 測（root 幾乎測不出權限問題）
- ★★★★ 團隊共用目錄用「目錄 setgid + ACL 預設值」，不要靠事後 `chmod -R`
- ★★★ RHEL 上部署完檔案養成 `restorecon -Rv` 的習慣

### ★★★★ 情境五：手動跑得好好的腳本，放進 cron 就是不動

**現象**：`crontab -l` 明明有那行，時間也到了，但什麼都沒發生 —— 而且**通常連錯誤都看不到**。

**判斷分流**：★★★★★ 先確認「cron 到底有沒有觸發」，這決定了往哪邊查。

```bash
$ grep CRON /var/log/syslog | tail -5                  # RHEL：/var/log/cron
Sep  2 04:00:01 srv-app01 CRON[7712]: (deploy) CMD (/opt/scripts/backup.sh)
$ journalctl -u cron --since today --no-pager | tail   # RHEL：-u crond
```

```text
日誌有 CMD 這行           → cron 有跑，是腳本自己失敗 →【2】
日誌完全沒有那一行        → cron 沒觸發              →【1】
有 CMD 也有 (CRON) info   → 看看是不是 MAIL 相關訊息  →【3】
```

**處置步驟**：

【1】★★★★ cron 沒觸發，依序查這五項：

```bash
$ systemctl is-active cron                    # RHEL：crond
active
$ crontab -l -u deploy                        # ★★★★ 注意「是誰的 crontab」
$ sudo cat /etc/cron.d/backup                 # 系統 crontab 多一個「使用者」欄位
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ 寫在 `/etc/cron.d/` 卻沒跑 | 系統 crontab 的第 6 欄是**使用者**，少寫這欄整行無效 | `0 4 * * * root /opt/scripts/backup.sh` |
| ★★★★ 時間欄位看起來對卻不觸發 | `*/5` 與 `0-59/5` 的誤用、星期與日期同時指定是 OR 不是 AND | 用 [crontab.guru](https://crontab.guru) 之類工具核對，或改用 timer |
| ★★★★ 指令裡有 `%` 完全不執行 | ★★★★★ crontab 裡的 `%` 是換行符，必須寫成 `\%` | `date +\%F` |
| ★★★ 檔案最後一行沒有換行 | 部分 cron 實作會忽略最後一行 | 檔案結尾補一個空行 |
| ★★★ 檔名有 `.` 或非法字元（`/etc/cron.d/`） | run-parts 規則會跳過含 `.` 的檔名 | 檔名只用英數、底線、減號 |
| ★★★ 機器那個時間根本沒開機 | cron 不補跑 | 改用 systemd timer + `Persistent=true` |

【2】★★★★★ cron 有跑但腳本失敗 —— 九成是**環境不同**，不是腳本有問題。

```bash
$ crontab -l | head -3
PATH=/usr/bin:/bin                 # ★★★★★ cron 的預設 PATH 就這麼短
$ sudo -u deploy env -i /bin/sh -c 'echo $PATH'    # 模擬 cron 的空環境
/usr/bin:/bin
```

四大失敗原因，按出現頻率排：

```text
① ★★★★★ PATH 太短 → docker、node、composer、aws 這些都在 /usr/local/bin，cron 找不到
② ★★★★★ 不讀 ~/.bashrc → 你在 .bashrc 裡 export 的變數，cron 裡一個都沒有
③ ★★★★  相對路徑 → cron 的工作目錄是家目錄，不是你以為的專案目錄
④ ★★★★  沒有 TTY → 需要互動、需要 ssh-agent、需要 tty 的指令全部會失敗
```

★★★★★ 最有效的驗證方法：**用 cron 的環境重現一次**，不要在自己的 shell 裡測。

```bash
$ sudo -u deploy env -i /bin/sh -c '/opt/scripts/backup.sh'
/opt/scripts/backup.sh: 12: docker: not found          # ★★★★ 真相出現
```

修法（三選一，優先序由上而下）：

```bash
# ① 最好：腳本裡一律用絕對路徑
/usr/bin/docker compose -f /srv/app/compose.yml up -d

# ② 次好：在 crontab 最上面自己宣告
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SHELL=/bin/bash

# ③ 需要完整環境時：明確地載入
0 4 * * * deploy . /home/deploy/.profile; /opt/scripts/backup.sh
```

【3】★★★★★ 讓失敗**被看見** —— 排程最危險的不是失敗，是**靜默失敗**。

```bash
# crontab 開頭
MAILTO=ops@example.gov.tw

# 或把輸出導向檔案與 journal（沒有 MTA 時的做法）
0 4 * * * deploy /opt/scripts/backup.sh >> /var/log/backup.log 2>&1
0 4 * * * deploy /usr/bin/systemd-cat -t backup /opt/scripts/backup.sh
```

★★★★ `>/dev/null 2>&1` 是排程界最貴的六個字元 —— 它會讓你**永遠不知道備份壞了**。

【4】★★★ systemd timer 的對應查法（timer 比 cron 好查，因為有完整狀態）：

```bash
$ systemctl list-timers --all | grep backup
NEXT                        LEFT     LAST                        PASSED  UNIT
Wed 2026-09-03 04:00:00 CST 23h left Tue 2026-09-02 04:00:00 CST 1h ago  backup.timer
$ systemctl status backup.service --no-pager     # ★★★★ 失敗原因在 .service，不在 .timer
$ systemd-analyze calendar 'Mon *-*-* 04:00:00'  # 驗證 OnCalendar 寫法對不對
```

★★★★ timer 沒跑的頭號原因：**只 `enable` 了 `.service` 沒 `enable` `.timer`**，
或反過來把 `.service` 也設成 `enabled`（那會變成開機就跑一次）。

**原理**：cron 用的是一個刻意做得極簡的環境（短 `PATH`、非登入 shell、無 TTY、
工作目錄是家目錄），這是設計而非缺陷 —— 目的是讓排程行為**可預測**、不受個人設定影響。
　→ 原理詳見 [[020-01-18-guide-Linux-排程工作]]、[[020-01-20-guide-Linux-環境變數與設定檔]]

**預防**：
- ★★★★★ 排程腳本第一行寫 `set -euo pipefail`，並在腳本內部自己宣告 `PATH`
- ★★★★★ **成功也要回報**（心跳監控），不能只靠「失敗會寄信」——
  信箱壞掉的那一天你不會知道（[[100-01-04-guide-日誌-健康檢查與可用性監控]]）
- ★★★★ 新排程上線後**手動觸發一次**驗證：`systemctl start backup.service`
- ★★★ 會跑很久的排程要加鎖檔（`flock`），避免重疊執行

### ★★★★ 情境六：`command not found`，但那個檔案明明在

**現象**：`ls -l /usr/local/bin/tool` 看得到，`tool` 卻說找不到；
或者一般使用者能跑、`sudo` 就不行。

```text
-bash: tool: command not found
sudo: tool: command not found
```

**判斷分流**：

```bash
$ type -a tool; echo "$PATH"; ls -l /usr/local/bin/tool
-bash: type: tool: not found
/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
-rw-r--r-- 1 root root 8123456 Sep  2 01:20 /usr/local/bin/tool   # ★★★★ 沒有 x
```

```text
PATH 裡沒有那個目錄        →【1】
PATH 有、檔案在、還是找不到 →【2】 權限或 shell 快取
只有 sudo 時找不到          →【3】 secure_path
檔案存在卻說 No such file   →【4】 直譯器或函式庫缺失（訊息會騙人）
```

**處置步驟**：

【1】★★★★ 正確地加 `PATH`，並且加在**對的檔案**裡：

```bash
# ~/.profile（登入 shell 才讀）或 ~/.bashrc（每個互動 shell 都讀）
export PATH="/opt/tool/bin:$PATH"
```

| 我要它在哪裡生效 | 寫在哪 |
| --- | --- |
| ★★★ 只有我、互動使用 | `~/.bashrc` |
| ★★★ 只有我、登入時（含 `ssh host cmd`） | `~/.profile` |
| ★★★★ 全機所有使用者 | `/etc/profile.d/tool.sh`（不要改 `/etc/profile` 本身） |
| ★★★★★ systemd 服務 | unit 的 `Environment=` 或 `EnvironmentFile=` ——**設定檔完全不影響服務** |
| ★★★★★ cron | crontab 開頭自己宣告，見情境五 |

★★★ 改完要 `source ~/.bashrc` 或重開終端機；`echo $PATH` 確認有進去。

【2】★★★★ `PATH` 對、檔案在，兩個常見原因：

```bash
$ sudo chmod +x /usr/local/bin/tool     # ① 沒有執行權限
$ hash -r                               # ② bash 記住了舊路徑，清掉快取
$ type -a tool
tool is /usr/local/bin/tool
```

★★★★ `hash -r` 專治「我明明剛把它裝到新位置，怎麼跑的還是舊的」——
bash 會快取指令路徑，換位置後不清快取就會一直用舊的（詳見**情境十六**）。

【3】★★★★★ `sudo` 有自己的一套 `PATH`，叫 `secure_path`，這是刻意的資安設計：

```bash
$ sudo grep secure_path /etc/sudoers
Defaults secure_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
```

三種處置，優先序由上而下：

```text
① ★★★★★ 直接用絕對路徑：sudo /opt/tool/bin/tool
② ★★★★  用 visudo 把該目錄加進 secure_path（要有正當理由，且該目錄不可被一般使用者寫入）
③ ★★     sudo env "PATH=$PATH" tool  —— ★★★★ 這等於繞過保護，只在臨時排錯用
```

> [!warning] ★★★★ 不要把使用者可寫的目錄加進 `secure_path`
> `secure_path` 存在的目的就是防止「有人在你的 `PATH` 前面放一支假的 `ls`」。
> 把 `~/bin` 或 `/tmp` 之類加進去，等於把 root 權限交給任何能寫那個目錄的人。

【4】★★★ 訊息說 `No such file or directory`，但檔案就在眼前 —— 缺的是**別的東西**：

```bash
$ ./tool
-bash: ./tool: /lib/ld-musl-x86_64.so.1: bad ELF interpreter: No such file or directory
$ ldd ./tool | grep 'not found'
libssl.so.1.1 => not found                    # ★★★★ 缺共享函式庫
$ file ./script.sh
./script.sh: Bourne-Again shell script, ASCII text executable, with CRLF line terminators
```

- `bad ELF interpreter` → 執行檔是為別的發行版／架構編的，裝對應套件或換版本
- `libxxx.so => not found` → 缺函式庫，跳**情境十六**【2】
- `with CRLF line terminators` → 行尾問題，跳**情境十七**【1】

**原理**：shell 找指令的順序是「別名 → 函式 → 內建 → `hash` 快取 → 逐一走 `PATH`」，
而 `sudo`、cron、systemd 各自有**獨立的環境**，你在互動 shell 裡設的東西
它們一概不知道。
　→ 原理詳見 [[020-01-20-guide-Linux-環境變數與設定檔]]

**預防**：
- ★★★★★ 腳本、unit、crontab 一律用絕對路徑，不要賭 `PATH`
- ★★★★ 系統層級的 `PATH` 放 `/etc/profile.d/*.sh`，不要動 `/etc/profile` 與 `/etc/environment`
- ★★★ 自編軟體裝到 `/usr/local`，並記錄在維運文件裡（[[020-01-30-guide-Linux-原始碼安裝與系統升級]]）

### ★★★★ 情境七：程序砍不掉 —— `kill -9` 也沒用

**現象**：`kill -9 <PID>` 下了好幾次，`ps` 裡那個 PID 還在。

**判斷分流**：★★★★★ 先看**狀態碼**，這決定了它是「殺不掉」還是「不需要殺」。

```bash
$ ps -eo pid,ppid,stat,wchan:20,etime,comm | awk '$3 ~ /^[DZT]/'
  PID  PPID STAT WCHAN                ELAPSED COMMAND
 4412  4402 D    nfs_wait_bit_killable 02:14:31 rsync
 5108  5100 Z    -                     00:41:02 php-fpm <defunct>
```

| 狀態 | 意思 | 能不能 kill |
| --- | --- | --- |
| ★★★★★ `D` | 不可中斷睡眠（等 I/O 完成） | ★★★★★ **不能**。訊號會排隊，等 I/O 回來才處理 |
| ★★★★ `Z` | 殭屍：已結束，父程序還沒收屍 | ★★★★★ **不需要**。它已經死了，只剩一筆記錄 |
| ★★★ `T` | 被 `SIGSTOP` 停住 | 先 `kill -CONT`，再送 `TERM` |
| ★★ `S`/`R` 卻殺不掉 | 你不是擁有者，或它是核心執行緒（`[]` 包起來的） | 用 `sudo`；核心執行緒不要動 |

**處置步驟**：

【1】★★★★★ `D` 狀態：**問題不在程序，在它等的那個 I/O**。先找出它在等什麼。

```bash
$ cat /proc/4412/wchan; echo
nfs_wait_bit_killable                     # ★★★★ 在等 NFS
$ sudo cat /proc/4412/stack 2>/dev/null | head -5
$ findmnt -t nfs4,nfs
TARGET     SOURCE                 FSTYPE OPTIONS
/mnt/nas   10.10.30.9:/vol/share  nfs4   rw,hard,proto=tcp,timeo=600
```

| `wchan` 關鍵字 | 在等什麼 | 往哪查 |
| --- | --- | --- |
| ★★★★ `nfs_*`、`rpc_*` | NFS 伺服器沒回應 | `ping` NFS 主機、查對方服務，跳**情境十四** |
| ★★★★ `io_schedule`、`wait_on_page_bit` | 本機磁碟很慢或壞了 | ★★★★★ `dmesg -T \| grep -i 'I/O error'` |
| ★★★ `blk_*`、`md_*` | 底層 RAID 正在重建或有壞碟 | `cat /proc/mdstat`，跳**情境十三** |

★★★★★ **不要為了「清掉」D 狀態程序而重開機**，先確認底層 I/O 恢復；
若是 NFS，伺服器一回來程序通常自己就走完了。真的必須斷開時：

```bash
$ sudo umount -f /mnt/nas       # 強制卸載（可能造成程序拿到 I/O error）
$ sudo umount -l /mnt/nas       # 延遲卸載：先從命名空間移除，等用完再真的卸載
```

【2】★★★★★ 殭屍程序：**殺它沒有意義**，要處理的是**父程序**。

```bash
$ ps -o pid,ppid,stat,comm -p 5108
  PID  PPID STAT COMMAND
 5108  5100 Z    php-fpm <defunct>
$ ps -o pid,comm -p 5100
  PID COMMAND
 5100 php-fpm
$ sudo systemctl reload php8.3-fpm      # 讓父程序收屍；不行才 restart
```

★★★ 少數幾個殭屍不影響系統（只占一個 PID 表項目）。
★★★★ 但**數量持續增加**就是程式 bug（沒有 `wait()`），要回報開發；
PID 用盡會導致「無法 fork」，那時整台機器都會出事：

```bash
$ ps -eo stat | grep -c '^Z'; cat /proc/sys/kernel/pid_max
```

【3】★★★ 送訊號的正確順序：**先禮後兵**，不要一開始就 `-9`。

```bash
$ kill -TERM 3312          # ① 請它自己收拾（存檔、關連線、寫日誌）
$ sleep 5; kill -0 3312 && echo '還在'
$ kill -KILL 3312          # ② 真的不理你才用，程式沒機會清理
```

★★★★ `SIGKILL` 對資料庫、佇列服務可能造成資料不一致或需要長時間復原；
服務類一律用 `systemctl stop`（它會照 unit 定義的 `KillSignal` 與逾時處理）。

【4】★★★ 找出「是誰占住這個檔案／這個埠」再決定殺誰：

```bash
$ sudo lsof /var/lib/mysql/ibdata1
$ sudo fuser -v /mnt/nas          # 誰卡在這個掛載點
$ sudo ss -lntp | grep :8080
```

**原理**：訊號是「送給程序、由程序在返回使用者態時處理」的機制。
`D` 狀態的程序停在核心態等硬體，根本沒有機會去處理訊號 —— 所以 `SIGKILL` 也無效；
殭屍則是已經結束、只剩一筆等待父程序 `wait()` 回收的記錄。
　→ 原理詳見 [[020-01-10-cmd-Linux-程序管理與訊號]]

**預防**：
- ★★★★ NFS 掛載點加上 `soft,timeo=,retrans=` 或 `x-systemd.automount`，
  不要讓一台 NAS 拖垮整台主機（[[020-01-29-guide-Linux-網路儲存與軟體RAID]]）
- ★★★★ 磁碟健康要納入定期檢查（`smartctl -a`），`D` 狀態常常是壞碟的第一個症狀
- ★★★ 監控加上「`D` 狀態程序數」與「殭屍數」兩個指標

### ★★★★ 情境八：記憶體不足、服務半夜自己消失

**現象**：服務莫名其妙不見了，`systemctl status` 顯示
`Main process exited, code=killed, status=9/KILL`，而應用日誌**什麼錯誤都沒留**。

★★★★★ 「應用日誌乾乾淨淨地斷在中間」是 OOM Killer 的典型指紋 ——
程序是被瞬間 `SIGKILL`，沒有機會寫任何東西。

**判斷分流**：

```bash
$ journalctl -k --since '1 day ago' --no-pager | grep -i 'killed process'
Sep 02 03:14:07 srv-app01 kernel: Out of memory: Killed process 3312 (node) \
  total-vm:4821064kB, anon-rss:3914208kB, file-rss:0kB, shmem-rss:0kB, UID:1001
$ dmesg -T | grep -iE 'oom|killed process' | tail
```

```text
有 Killed process       → OOM，走【1】
沒有，但 free 很吃緊    → 還沒 OOM 但快了 →【2】
記憶體很多卻仍 OOM      → cgroup／unit 的記憶體上限 →【3】
系統整個卡住不是 OOM    → 可能是 swap 抖動或 I/O，跳情境九
```

**處置步驟**：

【1】★★★★ 先看清楚真實用量。`free` 要看的是 **`available`**，不是 `free`。

```bash
$ free -h
               total        used        free      shared  buff/cache   available
Mem:            7.7Gi       6.9Gi       120Mi        64Mi       700Mi       380Mi
Swap:           2.0Gi       1.9Gi        90Mi
```

★★★★★ `buff/cache` 很大**不是問題**，那是可回收的快取；
真正該看的是 `available` —— 它已經把可回收的部分算進去了。

```bash
$ ps -eo pid,user,%mem,rss,comm --sort=-rss | head -6
  PID USER     %MEM   RSS COMMAND
 3312 appuser  49.6 3914208 node
 2201 mysql    22.1 1748112 mysqld
```

【2】★★★★ 決定處置方向 —— 三選一，**不要只是加記憶體了事**：

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ 單一程序 RSS 持續成長不回落 | 記憶體洩漏 | 回報開發；短期用 `Restart=` + `MemoryMax=` 圍堵 |
| ★★★★ 尖峰時多個 worker 一起爆 | 併發設定超過機器能力 | 調降 `pm.max_children`、`worker_processes`、連線池 |
| ★★★ 資料庫吃掉大半 | `innodb_buffer_pool_size` 之類設太大 | 依實體記憶體重新計算 |
| ★★★ 沒有 swap，尖峰一到就 OOM | 完全沒有緩衝空間 | 加適量 swap（不是拿 swap 當記憶體用） |
| ★★★★★ 被殺的是資料庫而不是元凶 | OOM 分數是看「用最多」，常常誤傷 | 用 `OOMScoreAdjust=` 保護關鍵服務 |

```bash
# 保護資料庫、讓非關鍵服務先被犧牲（systemd drop-in）
$ sudo systemctl edit mysql
[Service]
OOMScoreAdjust=-500

$ sudo systemctl edit myapp
[Service]
MemoryMax=2G          # ★★★★ 超過就在 cgroup 內被殺，不會拖垮整台機器
Restart=always
```

【3】★★★★ 整機記憶體還很多卻 OOM —— 是 **cgroup 層級**的限制：

```bash
$ systemctl show myapp -p MemoryMax -p MemoryCurrent
MemoryMax=2147483648
MemoryCurrent=2147221504                 # ★★★★ 已經頂到天花板
$ journalctl -u myapp | grep -i 'memory limit'
```

容器內的服務同理，要看容器自己的限制，不是宿主機的 `free`。

【4】★★★ 系統很慢但沒 OOM：多半是 swap 抖動（thrashing）。

```bash
$ vmstat 1 5
procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
 2  8 1998848  84320  12044 612880 4820 5100 12400  8800 9210 18400  8  9  4 79 0
```

★★★★ `si`／`so` 持續有大量數字＝正在瘋狂換頁，這比純粹的 OOM 更折磨 ——
系統看起來活著但什麼都跑不動。此時降低併發或重啟吃記憶體的服務比較快。

**原理**：核心的 OOM Killer 在記憶體真的配不出來時，依 `oom_score`（主要看用量）
挑一個程序 `SIGKILL`。它是**保護整台機器不當機**的最後手段，
不是錯誤 —— 出現 OOM 代表容量規劃本身有問題。
　→ 原理詳見 [[020-01-10-cmd-Linux-程序管理與訊號]]、[[020-01-26-guide-Linux-核心模組與sysctl調校]]

**預防**：
- ★★★★★ 每個服務都設 `MemoryMax=`，把爆炸範圍限制在單一服務內
- ★★★★ 關鍵服務設 `OOMScoreAdjust=` 負值，讓 OOM 先挑非關鍵的下手
- ★★★★ 監控要抓 `available` 與 swap 使用率，不要只看 `used`
- ★★★ 上線前做壓力測試，量出真正的尖峰用量再決定機器規格

### ★★★★ 情境九：負載飆高、系統很卡，但看不出誰的錯

**現象**：`uptime` 的 load average 三個數字都很大，SSH 反應遲鈍，但 CPU 使用率不高。

**判斷分流**：★★★★★ **load 不等於 CPU** —— Linux 的 load 把 `D` 狀態也算進去，
所以「load 很高但 CPU 很閒」幾乎一定是 I/O。

```bash
$ uptime; nproc
 04:22:10 up 41 days,  3:02,  2 users,  load average: 28.41, 24.90, 18.02
8
$ vmstat 1 5
 r  b   swpd   free   buff  cache   si  so   bi   bo   in   cs us sy id wa st
 1 27      0 512000  22000 3100000    0   0 4200  980 3100 6200  6  4  8 82 0
```

```text
r 欄很大、us 很高    → CPU 真的忙        →【1】
b 欄很大、wa 很高    → 卡在 I/O          →【2】
si/so 有數字         → 記憶體不足，回情境八
三者都不明顯卻很卡   → 網路或外部相依    →【3】
st 欄有數字          → ★★★★ 虛擬機被宿主機搶 CPU，去查宿主機
```

**處置步驟**：

【1】★★★★ CPU 忙：找出是誰，以及是使用者態還是核心態。

```bash
$ ps -eo pid,user,%cpu,etime,comm --sort=-%cpu | head -6
$ top -b -n1 -o %CPU | head -15
$ pidstat -u 1 3                      # sysstat 套件
```

- 單一程序長期 100%（單核）→ 程式邏輯問題或無窮迴圈，抓 stack 給開發
- `sy`（核心態）特別高 → 常見於大量 context switch、網路中斷、檔案系統壓力
- 突然出現不認識的高 CPU 程序 → ★★★★★ **先確認不是挖礦程式**，見「什麼時候該停手求援」

【2】★★★★★ I/O 是最常見的元凶。先確認是哪個裝置、再確認是哪個程序。

```bash
$ iostat -xz 1 3                      # sysstat
Device  r/s   w/s  rkB/s  wkB/s  %util  await
sdb    412  1180  16480  47200   99.8   142.6      # ★★★★ %util 貼近 100、await 很大
$ sudo iotop -oPa                     # 只顯示有 I/O 的程序，累計模式
$ ps -eo stat,comm | grep -c '^D'     # D 狀態的數量
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ 單一裝置 `%util` 近 100% | 磁碟到極限，或磁碟開始壞 | ★★★★★ 先 `dmesg -T \| grep -i error`，再 `smartctl -a` |
| ★★★★ RAID 正在 resync | 重建期間效能本來就會掉 | `cat /proc/mdstat` 看進度，跳**情境十三** |
| ★★★ 備份／掃描排程在跑 | 排程撞在一起 | 錯開時段，加 `IOSchedulingClass=idle` |
| ★★★★ `await` 高但 `%util` 不高 | 後端是共享儲存（SAN／NFS） | 問題在儲存或網路那頭，不在本機 |

【3】★★★ 系統很卡但四個指標都正常 —— 往外看：DNS 逾時、外部 API 卡住、
NFS 沒回應。這時 `strace -c -p <PID>` 或直接看應用日誌的「回應時間」比較快。

**原理**：Linux 的 load average 是「可執行 + 不可中斷」的程序數平均，
所以 I/O 塞住會讓 load 沖高卻不消耗 CPU。判讀時一定要配合
`vmstat` 的 `r`／`b` 兩欄才有意義。
　→ 原理詳見 [[060-01-03-04-guide-監控-效能瓶頸排查方法論]]、[[020-01-10-cmd-Linux-程序管理與訊號]]

**預防**：
- ★★★★ 監控同時記錄 load、`%iowait`、`D` 狀態數，三者一起看才判讀得出來
- ★★★ 大型排程（備份、掃描、重建索引）錯開時段，並降低 I/O 優先權
- ★★★ 磁碟 SMART 納入每週檢查（[[100-02-03-guide-維運-每週維護作業]]）

### ★★★★ 情境十：套件裝不起來 —— 鎖檔、相依、金鑰、來源

**現象**：`apt install` 或 `dnf install` 直接失敗，訊息有好幾種。

```text
（A）E: Could not get lock /var/lib/dpkg/lock-frontend. It is held by process 2841 (unattended-upgr)
（B）E: dpkg was interrupted, you must manually run 'sudo dpkg --configure -a'
（C）W: GPG error: https://deb.example.com stable InRelease: The following signatures
     couldn't be verified because the public key is not available: NO_PUBKEY 8A1B2C3D4E5F6789
（D）E: Release file for https://.../InRelease is not valid yet (invalid for another 4h 12min)
（E）The following packages have unmet dependencies:
（F）Err:1 http://archive.ubuntu.com/ubuntu noble InRelease  Could not connect to ...
```

**判斷分流**：訊息就是分流，對照上面的字母直接跳。

```text
（A）鎖檔    →【1】     （B）dpkg 中斷 →【2】
（C）金鑰    →【3】     （D）時間不對  → ★★★★★ 跳情境十二，這是時間問題不是套件問題
（E）相依    →【4】     （F）連不到    →【5】
```

**處置步驟**：

【1】★★★★★ 鎖檔：**先確認是誰拿著，不要急著刪鎖檔**。

```bash
$ sudo fuser -v /var/lib/dpkg/lock-frontend
                     USER    PID ACCESS COMMAND
/var/lib/dpkg/lock-frontend:
                     root   2841 F.... unattended-upgr
$ ps -o pid,etime,cmd -p 2841
```

- 是 `unattended-upgrades`（自動安全更新）→ ★★★★ **等它跑完**，通常幾分鐘
- 是你自己開的另一個視窗 → 關掉那個
- 程序已經不存在、鎖檔卻還在 → 才輪到清鎖檔

> [!danger] ★★★★★ `rm /var/lib/dpkg/lock*` 是最後手段，不是第一步
> 在 apt 真的還在跑的時候刪鎖檔，會讓兩個 dpkg 同時改套件資料庫，
> 造成**資料庫損毀**，那比原本的問題嚴重十倍。
> 一定要先用 `fuser` 或 `ps` 確認「沒有任何 apt/dpkg 程序在跑」，再刪。

```bash
$ pgrep -a 'apt|dpkg|unattended' || echo '確認沒有任何套件程序在跑'
$ sudo rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/lib/apt/lists/lock
$ sudo dpkg --configure -a
```

【2】★★★★ dpkg 被中斷：先修復再做別的，順序不能亂。

```bash
$ sudo dpkg --configure -a
$ sudo apt -f install                      # 補齊未滿足的相依
$ sudo apt update && sudo apt upgrade
```

★★★★ 中斷的常見成因是**磁碟滿**（尤其 `/boot`）—— 修復前先 `df -h /` 與 `df -h /boot`，
沒清出空間就修不完，回**情境二**。

【3】★★★★ GPG 金鑰：現代做法是**每個來源一把金鑰、放在自己的檔案裡**，
不要再用已經被淘汰的 `apt-key add`。

```bash
$ curl -fsSL https://deb.example.com/gpg.key \
    | sudo gpg --dearmor -o /etc/apt/keyrings/example.gpg
$ cat /etc/apt/sources.list.d/example.sources
Types: deb
URIs: https://deb.example.com
Suites: stable
Components: main
Signed-By: /etc/apt/keyrings/example.gpg
$ sudo apt update
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `NO_PUBKEY` | 金鑰沒裝或路徑不對 | 依上面重新匯入，確認 `Signed-By` 指到實際檔案 |
| ★★★★ `is not signed` | 來源沒簽章，或簽章檔沒下載到 | 確認來源網址與 suite 名稱拼對 |
| ★★★★ 金鑰過期 | 上游輪替了金鑰 | 重新下載金鑰，不要用 `[trusted=yes]` 繞過 |
| ★★★★★ 有人建議加 `[trusted=yes]` | 這等於**關掉來源驗證** | ★★★★★ 正式環境絕對不要，這是供應鏈攻擊的入口 |

【4】★★★ 相依衝突：先看清楚它在抱怨什麼，再決定退讓哪一邊。

```bash
$ sudo apt install nginx 2>&1 | tail -20
$ apt-cache policy nginx                 # 看有哪些版本、來自哪個來源、目前裝哪個
$ sudo apt-mark showhold                 # ★★★★ 有沒有被 hold 住的套件卡著
$ sudo apt install -s nginx              # -s 模擬執行，先看它想做什麼
```

> [!danger] ★★★★★ 看到 `apt` 說「要移除 87 個套件」就立刻停手
> 相依衝突時 apt 的建議常常是「把半個系統拆掉」。
> `-s` 模擬跑一次，看清楚移除清單裡有沒有 `linux-image-*`、`systemd`、`openssh-server`，
> 有的話**絕對不要按 Y**。寧可先解掉 hold、移除有問題的第三方來源，再重來。

★★★ RHEL 系有一個殺手級的退路 —— `dnf history`：

```bash
$ sudo dnf history list | head -5
$ sudo dnf history undo 42               # ★★★★ 把某一次交易整個回退
```

【5】★★★ 連不到來源：這其實是網路問題，回**情境十一（網路分層）**先確認基本連線。

```bash
$ curl -sI https://archive.ubuntu.com/ubuntu/dists/noble/InRelease | head -1
HTTP/1.1 200 OK
$ getent hosts archive.ubuntu.com
```

- DNS 解不出來 → 網路情境的第四層
- 解得出但連不到 → 防火牆／Proxy。企業環境常需要在 `/etc/apt/apt.conf.d/95proxy` 設 Proxy
- 只有這一個第三方來源連不到 → 去對方網站確認套件庫路徑與支援的 codename 有沒有改

**原理**：套件系統是「**單一寫入者**」設計 —— 鎖檔保證同時只有一個程序能改套件資料庫；
簽章驗證則保證你裝的東西真的來自那個來源。這兩層都是安全機制，繞過它們的代價
遠大於當下省下的時間。
　→ 原理詳見 [[020-01-14-guide-Linux-套件管理]]

**預防**：
- ★★★★ 正式機的自動更新只開**安全性更新**，並固定在維護時段
- ★★★★ 第三方來源用 `Signed-By` 綁定金鑰，並記錄在資產文件中
- ★★★ 大版本升級前先做完整備份與快照（[[020-01-30-guide-Linux-原始碼安裝與系統升級]]）

### ★★★★ 情境十一：網路不通 —— 六層分層排查

**現象**：ping 不到、連不上服務、DNS 解不出來。★★★★★ 症狀都叫「網路不通」，
但原因分布在六個不同的層次，**一定要照順序往上查**，跳著查只會浪費時間。

**判斷分流**：六個指令，由下往上，每一層都有明確的「過」或「不過」。

```bash
$ ip -br link                     # ① 介面在不在、有沒有 UP
lo    UNKNOWN  00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP>
ens18 UP       bc:24:11:3a:9f:02 <BROADCAST,MULTICAST,UP,LOWER_UP>
$ ip -br addr                     # ② 有沒有 IP
ens18 UP  10.10.20.31/24
$ ip route get 1.1.1.1            # ③ 路由走得出去嗎
1.1.1.1 via 10.10.20.1 dev ens18 src 10.10.20.31
$ ping -c2 10.10.20.1             # ④ 到閘道通不通
$ getent hosts www.example.gov.tw # ⑤ DNS 解得出來嗎
$ curl -sS -o /dev/null -w '%{http_code}\n' https://www.example.gov.tw   # ⑥ 服務通不通
```

```text
①介面 DOWN / NO-CARRIER  →【1】 實體層或介面沒啟用
②沒有 IP                 →【2】 DHCP 或靜態設定
③沒有預設路由            →【3】
④閘道不通                →【3】
⑤DNS 解不出              →【4】
⑥前面全過、服務不通      →【5】 防火牆或對方服務
```

**處置步驟**：

【1】★★★★ 介面層：

```bash
$ ip -br link
ens18 DOWN  bc:24:11:3a:9f:02 <NO-CARRIER,BROADCAST,MULTICAST,UP>
$ sudo ethtool ens18 | grep -E 'Link detected|Speed|Duplex'
Link detected: no                       # ★★★★ 實體沒接上：線、交換器埠、VLAN
$ dmesg -T | grep -i ens18 | tail -5
```

- `NO-CARRIER` → 網路線、交換器埠、光模組。★★★ 這是實體問題，在 OS 上找不到答案
- 介面名稱整個不見 → 驅動沒載入或網卡換了（PCI 位置變動會改名），
  查 `lspci -k | grep -A3 Ethernet`，見 [[020-01-27-cmd-Linux-硬體資訊與裝置管理]]

【2】★★★ IP 層：確認是誰在管這台機器的網路設定。

```bash
$ ls /etc/netplan/ 2>/dev/null; nmcli device status 2>/dev/null
$ sudo netplan get                     # Ubuntu Server
$ nmcli connection show                # RHEL 系／Ubuntu 桌面
```

> [!warning] ★★★★★ 遠端改網路設定 = 有機會把自己鎖在外面
> Ubuntu 用 `sudo netplan try`（設定套用後 120 秒內沒確認就自動回滾），
> 不要直接 `netplan apply`。沒有 `try` 的環境就先掛一個回滾排程：
> `sudo systemd-run --on-active=5m /bin/sh -c 'cp /etc/netplan/50.yaml.bak /etc/netplan/50.yaml && netplan apply'`，
> 確認連得上之後再把它停掉。

【3】★★★ 路由與閘道：

```bash
$ ip route
default via 10.10.20.1 dev ens18 proto static metric 100
10.10.20.0/24 dev ens18 proto kernel scope link src 10.10.20.31
$ ip neigh show 10.10.20.1
10.10.20.1 dev ens18 lladdr 00:1b:17:00:01:01 REACHABLE
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ 沒有 `default via` | 沒設預設閘道，或 DHCP 沒給 | 補上 gateway 設定 |
| ★★★★ `ip neigh` 顯示 `FAILED`／`INCOMPLETE` | ARP 拿不到閘道 MAC：VLAN 錯、遮罩錯 | 核對子網路遮罩與交換器 VLAN |
| ★★★ 有兩條 default | 多網卡時 metric 沒規劃好 | 用 metric 明確排序 |
| ★★★★ 閘道 ping 得到、外面不通 | 上游或 NAT 的問題 | `traceroute -n 1.1.1.1` 看斷在第幾跳 |

【4】★★★★ DNS：★★★★★ 先分清楚「解析不了」和「解析錯了」。

```bash
$ getent hosts srv-db01
$ resolvectl status | grep -A3 'Link 2'          # systemd-resolved 實際用哪個 DNS
$ dig @10.10.10.5 srv-db01.example.gov.tw +short  # 指定伺服器繞過本機設定
$ cat /etc/resolv.conf; grep '^hosts:' /etc/nsswitch.conf
```

- 指定 DNS 伺服器查得到、本機查不到 → 本機 `resolv.conf`／`resolved` 設定錯
- `/etc/resolv.conf` 是指向 `stub-resolv.conf` 的符號連結 → ★★★ **不要直接編輯它**，
  它會被覆寫；要改就改 netplan 或 `resolved.conf`
- 解出來的 IP 不對 → `/etc/hosts` 有殘留、或 DNS 有舊記錄，`resolvectl flush-caches`

【5】★★★★ 前五層都過、就是連不到服務 —— 分清楚「這台的防火牆」與「對方的問題」。

```bash
$ nc -zv 10.10.30.20 3306
nc: connect to 10.10.30.20 port 3306 (tcp) failed: Connection refused
$ sudo ss -lntp | grep 3306                   # 在對方機器上：服務有沒有在聽
$ sudo ufw status verbose                     # 本機防火牆（RHEL：firewall-cmd --list-all）
```

```text
Connection refused → ★★★ 封包有到、沒人聽：服務沒起來、或只綁 127.0.0.1
連線逾時（卡住）    → ★★★★ 被防火牆 DROP 或路由不通
立刻 reset         → 中間有 IPS／資安設備，或對方主動拒絕
```

★★★★ 服務只綁 `127.0.0.1` 是非常常見的一種：

```bash
$ sudo ss -lntp | grep 3306
LISTEN 0 151 127.0.0.1:3306 0.0.0.0:*  users:(("mysqld",pid=2201,fd=22))
                ^^^^^^^^^ 只聽本機，外面永遠連不進來
```

**原理**：網路是分層的，每一層都建立在下一層之上 —— 沒有 carrier 就不會有 ARP，
沒有 ARP 就沒有 IP 連通，沒有 IP 連通 DNS 也不會通。
**照順序往上查**，就不會出現「在 DNS 上找了兩小時，其實是網路線鬆了」這種事。
　→ 原理詳見 [[020-01-16-cmd-Linux-網路基礎指令]]

**預防**：
- ★★★★★ 遠端改網路設定一律用 `netplan try` 或先掛自動回滾
- ★★★★ 重要主機用固定 IP 或 DHCP 保留，並記錄在資產表
- ★★★ 每台機器的網路設定（IP／VLAN／閘道／DNS）要有文件，排錯時省一半時間

### ★★★★ 情境十二：時間不對，然後所有東西一起壞

**現象**：時間偏差往往不是自己被發現的，而是**以別的症狀出現**：

```text
curl: (60) SSL certificate problem: certificate is not yet valid
apt: Release file for ... is not valid yet (invalid for another 4h 12min)
kinit: KRB5KDC_ERR_PREAUTH_FAILED / Clock skew too great while getting initial credentials
日誌時間跳來跳去、排程在奇怪的時間跑、資料庫複寫報時間戳記錯誤
```

★★★★★ 只要同時出現「憑證錯誤 + 套件庫錯誤 + 登入失敗」三種毫不相干的症狀，
**第一個要查的就是時間**。

**判斷分流**：

```bash
$ timedatectl
               Local time: Tue 2026-09-02 04:31:07 CST
           Universal time: Mon 2026-09-01 20:31:07 UTC
                Time zone: Asia/Taipei (CST, +0800)
System clock synchronized: no                     # ★★★★★ 就是這裡
              NTP service: active
```

```text
synchronized: no        →【1】 同步機制沒生效
synchronized: yes 但時間仍錯 →【2】 時區問題，不是時間問題
偏差大到 NTP 追不上     →【3】
重開機就跑掉            →【4】 RTC 或硬體電池
```

**處置步驟**：

【1】★★★★ 先確認是哪一套客戶端在管時間 —— ★★★★★ **`timesyncd` 與 `chrony` 只能擇一**，
兩個同時跑會互搶。

```bash
$ systemctl is-active systemd-timesyncd chronyd ntpd 2>/dev/null
active
inactive
inactive
```

用 chrony 的機器（伺服器建議用它）：

```bash
$ chronyc tracking
Reference ID    : 0A0A0A05 (ntp.example.gov.tw)
Stratum         : 4
System time     : 0.000241 seconds slow of NTP time
Leap status     : Normal                          # ★★★★ Normal 才算真的同步
$ chronyc sources -v
MS Name/IP address     Stratum Poll Reach LastRx Last sample
^* ntp.example.gov.tw        3    6   377     41   +102us[ +112us] +/-  9ms
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ 所有來源 `Reach 0`、標記 `^?` | UDP 123 被擋，或位址打錯 | 分層確認：`ping` 得到 NTP 主機嗎？防火牆放行 UDP 123 了嗎？ |
| ★★★★ `Leap status: Not synchronised` | 還在收斂，或來源全部不可用 | 等幾分鐘；仍不行就查來源 |
| ★★★ 只有一個來源 | 沒有備援，一掛就全機沒時間 | 至少設三個來源 |
| ★★★★★ VM 時間亂跳 | 宿主機同步與 guest 同步打架 | 二選一：關掉 guest 的 NTP 或關掉宿主機同步工具 |
| ★★★ 容器裡時間不對 | 容器與宿主機共用核心時鐘，但時區不同 | 掛載 `/etc/localtime` 或設 `TZ` |

【2】★★★ 時間對但顯示錯 —— 是時區，不是時間。`Universal time` 才是判斷基準：

```bash
$ sudo timedatectl set-timezone Asia/Taipei
$ timedatectl | grep -E 'Local time|Universal time|Time zone'
```

★★★ 伺服器統一用 UTC 或統一用本地時區都可以，但**全機房必須一致**，
否則交叉比對日誌會非常痛苦。

【3】★★★★ 偏差太大，NTP 用「微調」追不上（預設只會慢慢調，一天調不了幾秒）：

```bash
$ chronyc tracking | grep 'System time'
System time     : 1842.331245 seconds slow of NTP time     # ★★★★ 差半小時
$ sudo chronyc makestep                                    # 立刻跳到正確時間
```

> [!warning] ★★★★★ 在正式服務上「跳時間」要挑時機
> 時間往回跳會讓資料庫、憑證、日誌、排程全部困惑 ——
> 有應用正在跑交易時尤其危險。正確做法是**先停掉受影響的服務**、
> 調時間、再啟動；或安排維護時段處理。
> chrony 的 `makestep 1.0 3` 設定（開機後前三次允許跳）就是為了避開這個問題。

【4】★★★ 重開機就跑掉：硬體時鐘（RTC）本身不準或主機板電池沒電。

```bash
$ sudo hwclock --show                    # 硬體時鐘
$ sudo hwclock --systohc                 # 把系統時間寫回硬體時鐘
```

★★★ 每次重開都差好幾分鐘、越差越多 → 換主機板電池（實體機才有這問題）。

**原理**：TLS 憑證、Kerberos 票證、套件庫的 `Valid-Until` 全都**內建時間視窗**，
機器時間落在視窗外就一律判定無效 —— 所以時間偏差會同時擊中一堆看起來不相干的系統。
　→ 原理詳見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]]

**預防**：
- ★★★★★ 機房內建一組內部 NTP 伺服器，所有機器指向它，只有它對外
- ★★★★ 監控「時間偏差」這個指標本身，不要等出事才發現
- ★★★★ AD 網域環境的容許偏差預設只有 5 分鐘，超過就無法登入 —— 這是硬底線

### ★★★★★ 情境十三：RAID 降級、ZFS/Btrfs 池出現異常

**現象**：★★★★★ 這一類的共同特徵是「**現在還能用**」—— 所以最容易被拖延，
而拖延期間**再壞一顆就是全毀**。

```text
mdadm: /proc/mdstat 出現 [U_] 或 [_U]
zpool status: state: DEGRADED / one or more devices has experienced an error
btrfs: BTRFS warning: lost page write due to IO error on /dev/sdc1
郵件：A DegradedArray event had been detected on md device /dev/md0
```

**判斷分流**：

```bash
$ cat /proc/mdstat
Personalities : [raid1]
md0 : active raid1 sdb1[1](F) sda1[0]
      1953382464 blocks super 1.2 [2/1] [U_]        # ★★★★★ [U_] = 兩顆只剩一顆
$ zpool status -x
  pool: tank
 state: DEGRADED
status: One or more devices could not be used because the label is missing
```

```text
mdadm [U_]／(F)         →【1】
zpool DEGRADED/FAULTED  →【2】
zpool 有 permanent errors →【3】 ★★★★★ 資料真的有損壞
btrfs 沒空間但 df 有空間 →【4】 metadata 用盡
btrfs 掛不起來           →【5】
```

**處置步驟**：

【1】★★★★★ mdadm 降級：**先確認是哪一顆、確認另一顆是好的**，再換。

```bash
$ sudo mdadm --detail /dev/md0
    State : clean, degraded
   Number Major Minor RaidDevice State
      0    8     1      0        active sync   /dev/sda1
      -    0     0      1        removed
      1    8    17      -        faulty        /dev/sdb1
$ sudo smartctl -H /dev/sdb                      # 確認它真的壞了
SMART overall-health self-assessment test result: FAILED!
$ sudo smartctl -H /dev/sda                      # ★★★★★ 也要確認活著那顆是好的
SMART overall-health self-assessment test result: PASSED
```

★★★★★ 換碟前**先備份**。重建（resync）期間對僅存的那顆磁碟是滿載讀取，
這正是「第二顆磁碟也跟著掛掉」最常發生的時刻。

```bash
$ sudo mdadm --manage /dev/md0 --fail /dev/sdb1 --remove /dev/sdb1
# —— 實體換碟 ——
$ lsblk -o NAME,SERIAL,SIZE                      # ★★★★★ 用序號確認你換的是對的那顆
$ sudo sfdisk -d /dev/sda | sudo sfdisk /dev/sdb # 複製分割表到新碟
$ sudo mdadm --manage /dev/md0 --add /dev/sdb1
$ cat /proc/mdstat                               # 看重建進度
      [====>................]  recovery = 21.4% (418/1953)M finish=48.2min
```

★★★★★ 重建完成後**兩件事一定要做**，否則下次開機陣列可能組不起來：

```bash
$ sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf
$ sudo update-initramfs -u                       # RHEL：dracut -f
```

> [!danger] ★★★★★ `mdadm --zero-superblock` 用錯就是全毀
> 這個指令會清掉磁碟上的 RAID 中繼資料。對**還在陣列裡的**磁碟下這個指令，
> 陣列就再也組不回來了。只能用在「已經確認要重用、且不在任何陣列中」的磁碟上，
> 而且下之前一定要 `lsblk -o NAME,SERIAL` 對照序號。

【2】★★★★★ ZFS 降級：先看它建議什麼（`action:` 欄位就是官方建議）。

```bash
$ zpool status -v tank
 state: DEGRADED
action: Replace the device using 'zpool replace'.
  scan: scrub repaired 0B in 02:41:18 with 0 errors on Sun Sep  1 03:41:19 2026
config:
        NAME                      STATE     READ WRITE CKSUM
        tank                      DEGRADED     0     0     0
          mirror-0                DEGRADED     0     0     0
            ata-WDC_WD40-XXXX     ONLINE       0     0     0
            ata-WDC_WD40-YYYY     FAULTED     12     0     0  too many errors
```

```bash
$ sudo zpool replace tank ata-WDC_WD40-YYYY ata-WDC_WD40-ZZZZ   # 新碟的 by-id 名稱
$ zpool status tank                       # resilver 進度
$ sudo zpool clear tank                   # 確認是暫時性錯誤（線鬆了）才用這個
```

★★★★★ ZFS 一律用 `/dev/disk/by-id/` 的名稱建 pool 與換碟，
**不要用 `/dev/sdb`** —— 那個名稱重開機就可能變。

【3】★★★★★ `errors: Permanent errors have been detected in the following files:` ——
這代表**資料真的損壞了**，而且 ZFS 已經修不回來（沒有足夠冗餘）。

```bash
$ zpool status -v tank | tail -5
errors: Permanent errors have been detected in the following files:
        tank/data:/backups/2026-08/db.dump
```

★★★★★ 處置順序：① 記下受損檔案清單 → ② 從備份還原這些檔案 →
③ `zpool scrub` 重跑一次 → ④ `zpool clear` 清掉計數 → ⑤ **檢討為什麼冗餘不夠**。

> [!danger] ★★★★★ `zpool destroy` 沒有確認提示
> 打下去就沒了，而且 `zpool import -D` 不保證救得回來。
> 任何 `destroy`／`mkfs`／`dd of=/dev/...` 之前，
> 一律先把指令貼到記事本、逐字核對 pool 名稱與裝置名稱，再貼回終端機執行。

【4】★★★★ Btrfs 說沒空間但 `df` 有空間 —— 是 **metadata 用盡**，這是 Btrfs 特有的坑：

```bash
$ sudo btrfs filesystem usage /
Data,single: Size:180.00GiB, Used:96.00GiB
Metadata,DUP: Size:4.00GiB, Used:3.98GiB          # ★★★★ metadata 滿了
$ sudo btrfs balance start -dusage=20 /           # 從使用率低的區塊開始整理
$ sudo btrfs filesystem usage /                   # 再確認一次
```

★★★ `balance` 會吃 I/O，正式環境挑離峰時段跑；★★★★ 先確認有快照可以退。

【5】★★★★ Btrfs 掛不起來（`open_ctree failed`）：先唯讀掛起來搶救資料，不要急著修。

```bash
$ sudo mount -o ro,rescue=all /dev/sdc1 /mnt      # 先搶資料
$ sudo btrfs device stats /mnt                    # 看錯誤計數
$ sudo btrfs scrub start -B /mnt                  # 校驗與修復（有冗餘才修得回來）
```

> [!danger] ★★★★★ `btrfs check --repair` 是最後手段
> 官方文件明確警告它可能讓情況更糟。順序永遠是：
> **先唯讀掛載搶救資料 → 有備份 → 才考慮 repair**。
> 沒有備份就跑 `--repair`，等於拿唯一的資料去賭。

**原理**：RAID 與 ZFS/Btrfs 的冗餘設計是「容許 N 顆故障」，一顆掉了之後
**你就用完了所有額度**。而重建期間的高負載讀取，正是第二顆磁碟最容易跟著故障的時刻 ——
所以「降級」是要當天處理的事件，不是可以排到下週的維護項目。
　→ 原理詳見 [[020-01-29-guide-Linux-網路儲存與軟體RAID]]、[[020-01-24-guide-進階儲存-ZFS與Btrfs]]

**預防**：
- ★★★★★ `mdadm.conf` 一定要設 `MAILADDR`，並**實測寄得出信**
  （`mdadm --monitor --test --oneshot /dev/md0`）
- ★★★★★ ZFS 每月 `scrub`、mdadm 每月一致性檢查，排成 timer 並監控結果
- ★★★★★ RAID **不是備份** —— 它防的是磁碟故障，不防誤刪、勒索軟體、檔案損毀
- ★★★★ 同批採購的磁碟壽命接近，混用不同批次可降低同時故障的機率

### ★★★ 情境十四：新硬碟看不到、裝置名稱重開機就變、NFS 掛載卡死

**現象**：三個看似不同、其實都是「裝置與掛載」的問題。

```text
（A）插了新硬碟，lsblk 完全看不到
（B）重開機後 /data 掛到別顆磁碟去了，或開機掉進 emergency mode
（C）ls /mnt/nas 整個終端機卡住，Ctrl+C 也沒反應
```

**處置步驟**：

【1】★★★ 新硬碟看不到：先確認核心有沒有看到它。

```bash
$ dmesg -T | tail -20
[Tue Sep  2 05:10:22 2026] scsi 2:0:1:0: Direct-Access  ATA  WDC WD40EFRX
[Tue Sep  2 05:10:22 2026] sd 2:0:1:0: [sdc] 7814037168 512-byte logical blocks
$ lsblk -o NAME,SERIAL,SIZE,TYPE
```

- `dmesg` 有、`lsblk` 沒有 → 重新讀取分割表：`sudo partprobe` 或 `sudo blockdev --rereadpt /dev/sdc`
- `dmesg` 完全沒反應（熱插拔）→ 請核心重掃匯流排：

```bash
$ for h in /sys/class/scsi_host/host*; do echo '- - -' | sudo tee $h/scan >/dev/null; done
$ lsblk
```

- 還是沒有 → ★★★ 問題在硬體層：線材、背板、RAID 卡（要先在 RAID 卡裡設成 JBOD 或建 VD）、
  電源。用 `lspci -k | grep -iA3 raid` 確認控制器與驅動，
  詳見 [[020-01-27-cmd-Linux-硬體資訊與裝置管理]]

【2】★★★★★ 裝置名稱漂移：`/dev/sda`、`/dev/sdb` 是**依偵測順序**給的，
換一張卡、插一顆碟、甚至改一次 BIOS 設定都可能對調。

```bash
$ lsblk -f
NAME   FSTYPE LABEL  UUID                                 MOUNTPOINTS
sdb1   ext4   data   9f3c2b41-1c7a-4d0e-b2a1-77c9e0f512aa /data
$ grep data /etc/fstab
/dev/sdb1  /data  ext4  defaults  0 2        # ★★★★★ 這樣寫遲早出事
```

★★★★★ 正確寫法一律用 UUID（或 `LABEL=`、ZFS 用 `by-id`）：

```bash
$ sudo blkid /dev/sdb1
/dev/sdb1: LABEL="data" UUID="9f3c2b41-1c7a-4d0e-b2a1-77c9e0f512aa" TYPE="ext4"
# /etc/fstab
UUID=9f3c2b41-1c7a-4d0e-b2a1-77c9e0f512aa  /data  ext4  defaults,nofail  0 2
$ sudo mount -a && findmnt /data      # ★★★★★ 改完必驗，不要直接重開機
```

★★★ 網卡也有同樣的問題（`enp3s0` 是依 PCI 位置命名的），換卡或換插槽就會改名 ——
所以網路設定也不要寫死在「介面名稱一定不變」的假設上。

【3】★★★★ NFS 卡死：★★★★★ `hard` 掛載（預設值）遇到伺服器不通時，
**程序會無限期等下去**，而且處在 `D` 狀態、`Ctrl+C` 無效。

```bash
$ findmnt -t nfs4,nfs
TARGET   SOURCE                FSTYPE OPTIONS
/mnt/nas 10.10.30.9:/vol/share nfs4   rw,relatime,hard,proto=tcp,timeo=600,retrans=2
$ ping -c2 10.10.30.9
$ rpcinfo -p 10.10.30.9 | head        # 對方 NFS 服務還在嗎
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `ls` 卡死、程序 `D` 狀態 | `hard` 掛載 + 伺服器不通 | 修好伺服器；急救用 `umount -f` 或 `umount -l` |
| ★★★★ `Stale file handle` | 伺服器端的匯出被重建或檔案被刪 | `sudo umount -l /mnt/nas && sudo mount /mnt/nas` |
| ★★★ 讀得到但寫入 `Permission denied` | UID/GID 對不起來，或匯出是 `ro`／有 `root_squash` | 對齊兩端 UID，或改匯出選項 |
| ★★★★ 開機時卡很久 | fstab 裡的 NFS 沒加 `_netdev` | 加 `_netdev,nofail`，或改用 autofs |

★★★★ 長期解法：改用 autofs 或 `x-systemd.automount` —— 用到才掛、不用就放開，
NAS 掛掉時不會拖垮整台主機。

**原理**：`/dev/sdX` 是核心依偵測順序動態指派的，不具穩定性；
UUID 存在檔案系統本身的超級區塊裡，跟著資料走，所以才是持久設定的唯一正解。
NFS 的 `hard` 則是為了資料一致性而刻意設計成「一直等」。
　→ 原理詳見 [[020-01-15-cmd-Linux-磁碟分割與掛載]]、[[020-01-29-guide-Linux-網路儲存與軟體RAID]]

**預防**：
- ★★★★★ fstab 一律用 UUID，非必要掛載一律加 `nofail`
- ★★★★ NFS／iSCSI 這類網路儲存加 `_netdev`，並考慮 automount
- ★★★ 上架時就把磁碟槽位、序號、用途對照表記錄下來（[[040-02-09-guide-機房-伺服器上架與初始設定]]）

### ★★★★ 情境十五：日誌爆量、或者找不到日誌

**現象**：兩個相反的問題，但成因都在同一套機制。

```text
（A）/var/log 把磁碟塞爆了
（B）要查上禮拜的事，journalctl -b -1 卻說：Specifying boot ID has no effect,
     no persistent journal was found
```

**判斷分流**：

```bash
$ journalctl --disk-usage
Archived and active journals take up 18.4G in the file system.
$ ls -d /var/log/journal 2>/dev/null || echo '沒有持久化目錄'
$ sudo du -xh --max-depth=1 /var/log | sort -h | tail -5
```

```text
journal 很大        →【1】
沒有 /var/log/journal →【2】 ★★★★ Ubuntu 預設只留在記憶體，重開就沒了
某個應用日誌很大    →【3】 logrotate 沒生效
日誌完全沒有新內容  →【4】
```

**處置步驟**：

【1】★★★★ journald 爆量：先急救清出空間，再設上限避免重演。

```bash
$ sudo journalctl --vacuum-size=2G          # 保留 2G，其餘刪除
$ sudo journalctl --vacuum-time=30d         # 或只保留 30 天
```

```ini
# /etc/systemd/journald.conf.d/99-limits.conf
[Journal]
Storage=persistent
SystemMaxUse=2G
SystemMaxFileSize=200M
MaxRetentionSec=30day
```

```bash
$ sudo systemctl restart systemd-journald && journalctl --disk-usage
```

★★★★ 順便找出「是誰在狂寫日誌」—— 通常是某個服務一直在報同一個錯：

```bash
$ sudo journalctl --since '1 hour ago' -o json 2>/dev/null \
    | jq -r '._SYSTEMD_UNIT // "none"' | sort | uniq -c | sort -rn | head -5
   84213 myapp.service
```

【2】★★★★★ Ubuntu 預設 `Storage=auto` 而 `/var/log/journal` 不存在，
等於**日誌只活在記憶體裡，重開機全部消失** —— 這對事後追查是致命的。

```bash
$ sudo mkdir -p /var/log/journal
$ sudo systemd-tmpfiles --create --prefix /var/log/journal
$ sudo systemctl restart systemd-journald
$ journalctl --list-boots | head -3        # ★★★★ 有多筆就成功了
 0 8f2a... Tue 2026-09-02 05:20:11 CST—Tue 2026-09-02 05:41:02 CST
```

★★★★★ 這一步請當成新機建置的**必做項目**，不要等到要查事故時才發現沒日誌。

【3】★★★★ 某支應用的日誌一直長大 = logrotate 沒生效。先用除錯模式看它怎麼想：

```bash
$ sudo logrotate -d /etc/logrotate.d/myapp     # -d 只模擬不執行
rotating pattern: /var/log/myapp/*.log  after 1 days (14 rotations)
error: skipping "/var/log/myapp/app.log" because parent directory has insecure
       permissions (It's world writable or writable by group which is not "root")
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `insecure permissions` | 日誌目錄可被 group/other 寫 | 收緊權限，或在設定裡加 `su <user> <group>` |
| ★★★★★ 輪替了但檔案還在長大 | 應用還握著舊的描述符（同**情境二**【2】） | 用 `postrotate` 送訊號讓它重開檔 |
| ★★★ 完全沒輪替 | `logrotate.timer` 沒跑 | `systemctl list-timers \| grep logrotate` |
| ★★★ 設定寫了但沒被讀到 | 檔名含 `.` 或副檔名（如 `myapp.conf`）被跳過 | 檔名不要有點與副檔名 |

```ini
# /etc/logrotate.d/myapp
/var/log/myapp/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 myapp adm
    sharedscripts
    postrotate
        systemctl reload myapp >/dev/null 2>&1 || true
    endscript
}
```

★★★ 應用不支援重開日誌檔時才用 `copytruncate`（★★★ 有極小機率遺失輪替瞬間的幾行）。

【4】★★★ 日誌完全沒有新內容：

```bash
$ systemctl is-active systemd-journald rsyslog
$ sudo journalctl -f                          # 有沒有東西進來
$ ls -l /dev/log                              # rsyslog 的 socket 在不在
```

- journald 活著、rsyslog 掛了 → `/var/log/syslog` 之類會停更新，但 `journalctl` 仍有
- 兩個都活著卻沒東西 → 檢查該服務的 `StandardOutput=`／應用自己是不是寫到別的檔

**原理**：現代 Linux 有兩套日誌並存 —— journald（二進位、結構化、可查詢）
與傳統 syslog 檔案（純文字、靠 logrotate 管理）。
兩套的容量控制機制**完全不同**，所以要分別設定，漏掉任一邊都會出事。
　→ 原理詳見 [[020-01-19-guide-Linux-日誌系統]]

**預防**：
- ★★★★★ 新機建置必做：開啟 journald 持久化 + 設 `SystemMaxUse=`
- ★★★★ 新服務上線必做：寫一份對應的 logrotate 設定並用 `-d` 驗過
- ★★★★ 重要日誌外送到集中式日誌平台，才不會「機器掛了日誌也跟著沒了」
  （[[100-01-02-guide-日誌-日誌集中與輪替]]）

### ★★★ 情境十六：改了設定完全沒生效，或裝好了跑的還是舊版

**現象**：你確定改對了、也存檔了，但行為完全沒變。

**判斷分流**：★★★★★ 核心問題永遠是同一句話 ——
**「你改的那個檔案，跟系統實際讀的那個檔案，是不是同一個？」**

```text
改 systemd unit 沒反應      →【1】
改設定檔沒反應              →【2】
自己編譯裝了新版，跑的還是舊 →【3】
改 sysctl 沒反應            →【4】
```

**處置步驟**：

【1】★★★★ systemd：三個常見原因，一次全查。

```bash
$ systemctl cat myapp                    # ★★★★★ 這才是「實際生效」的完整內容
# /etc/systemd/system/myapp.service
...
# /etc/systemd/system/myapp.service.d/override.conf     ← drop-in 蓋在後面
[Service]
Environment=NODE_ENV=staging             # ★★★★ 你在主檔改的被這裡蓋掉了
$ systemd-delta --type=extended | head    # 全機被覆寫的 unit 一覽
```

```bash
$ sudo systemctl daemon-reload            # ★★★★★ 改完 unit 沒跑這行 = 白改
$ sudo systemctl restart myapp            # reload 不一定會重讀 unit，restart 才保險
```

【2】★★★★ 一般設定檔：先確認程式**實際打開的是哪個檔**。

```bash
$ sudo lsof -p $(pgrep -f myapp | head -1) | grep -E '\.(conf|yml|yaml|ini|env)$'
myapp 3312 myapp 8r REG 8,3 2140 /opt/myapp/config/production.yml
$ sudo strace -f -e trace=openat -p 3312 2>&1 | grep -i conf | head    # 更確定的做法
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ 改了主設定檔沒用 | 有 `include` 目錄，編號更後面的檔蓋過去 | 找出實際生效的那個檔改 |
| ★★★★ 沒有 reload | 多數服務要 reload／restart 才重讀 | `systemctl reload <服務>` |
| ★★★ 改到範例檔 | 改了 `xxx.conf.default`／`xxx.conf.sample` | 對照 `lsof` 的結果 |
| ★★★ 改到另一台機器 | 有負載平衡或多台後端 | `hostname` 確認你在哪台 |
| ★★★ 有語法錯誤被忽略 | 程式跳過壞掉的區段 | 用該服務的設定檢查指令驗證 |

【3】★★★★ 自己編譯裝了新版，跑的卻是舊版 —— 三個原因，依序排除：

```bash
$ type -a tool
tool is /usr/local/bin/tool
tool is /usr/bin/tool                    # ★★★★ 系統版也在，看 PATH 誰在前面
$ echo "$PATH"
$ hash -r; type tool                     # ② 清掉 shell 的路徑快取
$ ldd /usr/local/bin/tool | grep -i local
libfoo.so.2 => not found                 # ③ 找不到自編的函式庫
$ echo '/usr/local/lib' | sudo tee /etc/ld.so.conf.d/local.conf && sudo ldconfig
$ tool --version
```

★★★★ `/usr/local/bin` 在多數發行版的 `PATH` 中排在 `/usr/bin` 前面 —— 但
**cron、systemd、sudo 的 `PATH` 不一定如此**，服務跑到舊版常常就是這個原因。

【4】★★★ sysctl：改了檔案要載入，而且要注意誰蓋誰。

```bash
$ sudo sysctl -p /etc/sysctl.d/99-tuning.conf     # 載入單一檔
$ sudo sysctl --system                            # 依序載入所有目錄
$ sysctl net.core.somaxconn                       # ★★★★ 驗證實際生效的值
net.core.somaxconn = 4096
```

★★★★ 有些參數只在服務啟動時被讀取（如 `somaxconn` 之於已經在聽的 socket），
改完要重啟服務才會真的套用；容器內的服務則受宿主機的核心參數影響。

**原理**：Linux 的設定普遍採「主檔 + drop-in 目錄」的疊加模型，
而執行檔的解析又受 `PATH` 順序與 shell 快取影響 ——
所以「改了沒效」幾乎都不是改錯內容，而是**改錯地方**或**沒讓它重讀**。
　→ 原理詳見 [[020-01-17-cmd-Linux-systemd服務管理]]、[[020-01-30-guide-Linux-原始碼安裝與系統升級]]

**預防**：
- ★★★★ 改完一律用「印出實際生效值」的指令驗證，不要看檔案內容就當作改好了
- ★★★★ 自訂設定放 drop-in（`*.d/` 加編號），不要改套件提供的主檔 —— 升級才不會衝突
- ★★★ 設定檔納入版本控制，`git diff` 一看就知道誰動了什麼

### ★★★ 情境十七：Shell 腳本的三個經典陷阱

**現象**：腳本在你的終端機跑得好好的，換個環境就出事；或者出事了卻沒有人發現。

```text
（A）./deploy.sh: /bin/bash^M: bad interpreter: No such file or directory
（B）rm -rf /opt/app/ 本來要刪子目錄，結果刪掉整個 /opt/app
（C）中間某一步失敗了，腳本照樣往下跑到最後，還印出「部署成功」
```

**處置步驟**：

【1】★★★★ CRLF：從 Windows 編輯器帶過來的檔案，行尾多一個 `\r`。

```bash
$ file deploy.sh
deploy.sh: Bourne-Again shell script, ASCII text executable, with CRLF line terminators
$ head -1 deploy.sh | cat -A
#!/bin/bash^M$
$ sed -i 's/\r$//' deploy.sh          # 或 dos2unix deploy.sh
$ file deploy.sh
deploy.sh: Bourne-Again shell script, ASCII text executable
```

★★★★ CRLF 造成的錯誤訊息**非常會騙人** ——「找不到 `/bin/bash`」是假象，
真正找不到的是 `/bin/bash\r` 這個不存在的檔案。同樣的問題也會出現在
`.env` 檔（變數值尾端多一個 `\r`）與 systemd unit。
★★★ 治本：在 repo 加 `.gitattributes` 寫 `*.sh text eol=lf`。

【2】★★★★★ 未加引號的變數 —— 這是 Shell 最危險的預設行為。

```bash
# ★★★★★ 危險寫法：DIR 是空的時候，這行變成 rm -rf /
rm -rf $DIR/

# ★★★★★ 正確寫法：加引號 + 防呆展開
: "${DIR:?DIR 未設定，中止}"          # 沒設就直接中止並報錯
rm -rf "${DIR:?}"/
```

| 陷阱 | 出事的樣子 | 正確寫法 |
| --- | --- | --- |
| ★★★★★ 變數沒引號 | 空值展開成什麼都沒有；有空白就被拆成多個參數 | 一律 `"$VAR"` |
| ★★★★ 路徑含空白 | `for f in $(ls)` 把 `my file.txt` 拆成兩個 | `for f in *; do` |
| ★★★★ 未定義變數當空字串 | 打錯字的變數名靜默變成空值 | `set -u` 或 `${VAR:?}` |
| ★★★ `cd` 失敗仍往下跑 | 在錯誤的目錄執行破壞性指令 | `cd "$DIR" \|\| exit 1` |
| ★★★★ 用 `rm -rf` 組路徑 | 任何一段是空的就掃到上層 | 先 `[ -d "$DIR" ]` 再刪，並用絕對路徑 |

【3】★★★★★ `set -e` 不是萬靈丹 —— 它有好幾種**不會觸發**的情況：

```bash
#!/usr/bin/env bash
set -euo pipefail          # ★★★★★ 每支維運腳本的第一行

# ★★★★ 但這些情況 -e 仍然不會中止：
if failing_command; then :; fi        # 在 if 條件裡
failing_command || true               # 在 || 左邊
failing_command && next               # 在 && 左邊
failing_command | grep x              # 管線中間（要靠 pipefail）
local x=$(failing_command)            # local/declare 會吃掉退出碼
failing_command; echo "done"          # 函式內未 return 的情況
```

★★★★★ 結論：`set -e` 是**安全網不是錯誤處理**。關鍵步驟一定要自己檢查：

```bash
if ! systemctl reload nginx; then
    echo "reload 失敗，回滾" >&2
    cp -a "$BACKUP" "$TARGET" && systemctl reload nginx
    exit 1
fi
```

【4】★★★ 上線前的三道檢查，成本很低卻能擋掉八成問題：

```bash
$ bash -n deploy.sh              # 語法檢查，不執行
$ shellcheck deploy.sh           # ★★★★ 靜態分析，會抓出未加引號等問題
In deploy.sh line 12:
rm -rf $DIR/
       ^--^ SC2086: Double quote to prevent globbing and word splitting.
$ bash -x deploy.sh              # 逐行印出實際執行的指令（含變數展開後的值）
```

★★★★ `bash -x` 是排錯神器 —— 它印出的是**變數展開後**的真實指令，
一眼就看得出「這個變數其實是空的」。

**原理**：Shell 是「文字展開後再執行」的語言，變數展開發生在指令組合**之前**，
所以空變數會讓指令的形狀整個改變。`set -e` 只在特定情境檢查退出碼，
不是把 Shell 變成會拋例外的語言。
　→ 原理詳見 [[020-01-21-cmd-Linux-Shell腳本入門]]、[[020-01-22-guide-Linux-Shell腳本進階]]

**預防**：
- ★★★★★ 每支腳本開頭 `set -euo pipefail`，破壞性變數用 `${VAR:?}`
- ★★★★★ 危險指令先做「乾跑」模式（印出要執行什麼但不執行），驗過再加上真的執行
- ★★★★ `shellcheck` 納入 CI 或提交前檢查
- ★★★ 用 `trap` 做清理與回滾，讓腳本不管怎麼結束都收拾乾淨

### ★★★ 情境十八：使用者登不進去、`sudo` 突然全掛

**現象**：帳號好好的卻登不進去；或者更糟 —— `sudo` 整個不能用了。

```text
（A）su: Authentication failure
（B）This account is currently not available.
（C）Your account has expired; please contact your system administrator
（D）sudo: /etc/sudoers is world writable
（E）>>> /etc/sudoers: syntax error near line 42 <<<
```

**判斷分流**：

```bash
$ getent passwd deploy
deploy:x:1002:1002::/home/deploy:/usr/sbin/nologin      # ★★★★（B）的原因
$ sudo passwd -S deploy
deploy L 2026-06-01 0 99999 7 -1                        # ★★★ L = 密碼被鎖
$ sudo chage -l deploy | head -4
Account expires : Aug 31, 2026                          # ★★★（C）的原因
```

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★ `not available` | shell 是 `/usr/sbin/nologin` | 服務帳號本來就該這樣；真要登入才 `usermod -s /bin/bash` |
| ★★★ `passwd -S` 顯示 `L` | 密碼被鎖 | `sudo usermod -U <帳號>`；注意 `!` 與 `!!` 的差別 |
| ★★★ `Account expires` 已過 | `chage -E` 到期 | `sudo chage -E -1 <帳號>` 取消到期 |
| ★★★ 家目錄不存在 | 建帳號時沒有 `-m` | `sudo mkhomedir_helper <帳號>` 或手動建並設好擁有者 |
| ★★★★ 新加的群組沒生效 | 群組成員資格在**登入時**決定 | 重新登入；`id` 確認；服務要 restart |
| ★★★★★ `/etc/passwd` 或 `/etc/shadow` 權限被改 | 手動編輯造成 | `/etc/shadow` 應為 `640 root:shadow`（RHEL 為 `000 root:root`） |

**處置步驟**：

【1】★★★★★ `sudo` 壞掉是最緊急的一種 —— 因為**你可能連修它的權限都沒有了**。

```text
先確認你手上還有什麼：
① 這台機器上還有另一個開著的 root shell 嗎？（沒關掉就還有救）
② 能用 pkexec 嗎？        pkexec visudo
③ 有實體／IPMI／VM console 可以用 root 密碼登入嗎？
④ 都沒有 → 只能重開機進 GRUB，加 init=/bin/bash 或 rd.break 救援
```

```bash
# 有 root shell 的情況
# visudo -c                                  # 檢查語法
/etc/sudoers: parsed OK
/etc/sudoers.d/90-deploy: syntax error near line 3
# chmod 0440 /etc/sudoers && chown root:root /etc/sudoers
# visudo -f /etc/sudoers.d/90-deploy         # 修正那個檔
```

沒有任何 root 途徑時，走單一使用者模式（實體或 console 前操作）：

```text
GRUB 選單按 e → 找到 linux 那一行 → 行尾加：init=/bin/bash
按 Ctrl-X 開機 → 進到 shell 後：
  mount -o remount,rw /
  chmod 0440 /etc/sudoers
  visudo -c
  exec /sbin/init      （或 mount -o remount,ro / 後重開機）
```

★★★★ RHEL 系用 `rd.break`，進去後要 `chroot /sysroot`，
且若啟用 SELinux 還要 `touch /.autorelabel`，詳見
[[020-01-25-guide-Linux-開機流程與GRUB救援]]。

> [!danger] ★★★★★ 能從 GRUB 拿到 root，就等於「實體接觸 = 完全控制」
> 這條救援路徑同時也是攻擊路徑。正式環境必須設 GRUB 密碼、機櫃上鎖、
> BIOS 設定加密碼，並把伺服器機房的實體門禁納入資安控制。

【2】★★★★★ 預防勝於救援 —— 改 sudoers **只有一種正確做法**：

```bash
$ sudo visudo                            # ★★★★★ 它會在存檔前檢查語法，錯了不讓你存
$ sudo visudo -f /etc/sudoers.d/90-ops   # 自訂授權放這裡，不要改主檔
$ sudo cat /etc/sudoers.d/90-ops
%ops-team ALL=(ALL:ALL) ALL
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart myapp
```

★★★ `/etc/sudoers.d/` 裡的檔名**不要有點與副檔名**（`90-ops.conf` 會被忽略），
權限要 `0440`。

【3】★★★ 離職／權限盤點時的常用查法：

```bash
$ sudo lastlog -b 90                        # 90 天沒登入過的帳號
$ getent group sudo ops-team                # 誰在特權群組裡
$ sudo awk -F: '$3>=1000 && $3<65534 {print $1,$3,$7}' /etc/passwd
$ sudo grep -rE '^[^#]' /etc/sudoers.d/     # 所有自訂的 sudo 授權
```

**原理**：帳號是否能登入，由「shell 是不是 nologin」「密碼欄是不是被鎖」
「帳號有沒有到期」「PAM 有沒有放行」四道關卡共同決定，四者互相獨立。
而 `sudo` 為了防止設定被竄改，會在發現 sudoers 權限過寬或語法錯時**直接拒絕運作** ——
這是安全設計，不是 bug。
　→ 原理詳見 [[020-01-09-cmd-Linux-使用者與群組管理]]

**預防**：
- ★★★★★ 改 sudoers **永遠用 `visudo`**，改完在**另一個終端機**測試一次再關掉原本的
- ★★★★ 授權放 `/etc/sudoers.d/`，用群組而非個別帳號，並納入季度盤點
- ★★★★ 每台機器都要有可用的頻外管理（IPMI／console），這是所有救援的前提
- ★★★ 帳號生命週期（開通、調職、離職）走固定流程（[[090-07-02-guide-資安實踐-密碼與帳號管理實務]]）

## 一頁式急救卡

出事時來不及讀長文，先跑這幾個。★★★★★ **由上而下、看到異常就停下來往對應情境走**。

```bash
# ─── 黃金 60 秒：一分鐘掌握整機狀況 ──────────────────────────────
# 【1】我在哪台機器、開多久了、load 多高
hostname; uptime; who
#   load 遠大於 nproc → 情境九（先分辨是 CPU 還是 I/O）

# 【2】磁碟：容量與 inode 都要看
df -h | awk 'NR==1 || $5+0>=80'; df -i | awk 'NR==1 || $5+0>=80'
#   Use% 或 IUse% 逼近 100 → 情境二
#   輸出裡有 /boot → 核心升級會失敗，先清

# 【3】記憶體：看 available，不是 free
free -h; journalctl -k --since '1 day ago' | grep -ci 'killed process'
#   available 很低 / 有 killed process → 情境八

# 【4】有沒有服務掛了
systemctl --failed --no-pager
#   有紅字 → 情境三（先 systemctl status -l 再 journalctl -xeu）

# 【5】有沒有卡住或死掉的程序
ps -eo pid,stat,wchan:20,etime,comm | awk '$2 ~ /^[DZ]/'
#   D 狀態 → I/O 或 NFS，情境七與情境十四
#   大量 Z → 父程序沒收屍，情境七

# 【6】儲存冗餘有沒有掉
cat /proc/mdstat 2>/dev/null | grep -E '^\s*\[' ; zpool status -x 2>/dev/null
#   出現 [U_] 或 DEGRADED → ★★★★★ 情境十三，當天就要處理

# 【7】最近有沒有硬體或檔案系統錯誤
sudo dmesg -T --level=err,crit,alert,emerg | tail -20
#   I/O error / remount read-only → ★★★★★ 硬體問題，先備份再說

# 【8】時間對不對（一堆怪症狀的共同根源）
timedatectl | grep -E 'Local time|synchronized|NTP service'
#   synchronized: no → 情境十二

# ─── 網路不通時：由下往上六層，不要跳著查 ───────────────────────
ip -br link                        # ① 介面 UP 嗎（NO-CARRIER = 實體問題）
ip -br addr                        # ② 有 IP 嗎
ip route get 1.1.1.1               # ③ 有預設路由嗎
ping -c2 <閘道>                     # ④ 到閘道通嗎
getent hosts <目標主機名>           # ⑤ DNS 解得出來嗎
nc -zv <目標IP> <埠>                # ⑥ 服務通嗎
#   refused = 沒人聽（服務或綁定位址）；卡住逾時 = 防火牆或路由

# ─── 服務起不來時：三個指令拼出全貌 ─────────────────────────────
systemctl status <服務> -l --no-pager        # 結論（看 status=NNN 那個數字）
systemctl cat <服務>                          # 實際生效的 unit（含 drop-in 覆寫）
journalctl -xeu <服務> --no-pager | tail -30  # 過程（真正的錯誤訊息在這）
sudo -u <服務帳號> <ExecStart 那行指令>        # ★★★★★ 投報率最高的一步

# ─── 改設定沒生效時：先問「實際生效的值是什麼」─────────────────
systemctl cat <服務>                 # systemd
sudo sysctl <參數名>                 # 核心參數
sudo lsof -p <PID> | grep -E '\.(conf|ya?ml|ini|env)$'   # 程式真的讀了哪個檔
type -a <指令>; hash -r              # 執行檔解析與 shell 快取

# ─── 動手改之前的三道保命符 ────────────────────────────────────
cp -a <設定檔> <設定檔>.$(date +%F-%H%M).bak     # ① 一定要留可回退的副本
<該服務的設定檢查指令>                             # ② 先驗語法（nginx -t / sshd -t / visudo -c）
# ③ 遠端操作前先確認：我還有第二條路進來嗎？（另一個終端／console／IPMI）
```

> [!tip] ★★★★★ 三句話版本
> ① 先跑黃金 60 秒 —— **磁碟、記憶體、服務、儲存冗餘**，四項裡多半就有答案。
> ② 找不到原因時，去看**日誌的原文**（`journalctl -xeu`、`dmesg -T`），不要憑猜的改設定。
> ③ 動任何設定之前，**先備份、先驗語法、先確認還有第二條路進得來**。

## 什麼時候該停手求援

> [!danger] ★★★★★ 以下情況請立刻停止操作 —— 繼續動手會讓證據消失或災情擴大

**【1】★★★★★ 懷疑不是故障而是入侵**：出現不認識的高 CPU 程序、`/tmp` 或 `/dev/shm`
裡有奇怪的執行檔、`crontab` 多了沒人承認的排程、`authorized_keys` 多了不明公鑰、
日誌出現無法解釋的斷層。★★★★★ **不要重開機、不要刪檔案、不要「順便清一清」** ——
記憶體內容與時間戳記都是證據。保存現場並依
[[090-07-04-guide-資安實踐-資安事件應變流程]] 通報。

**【2】★★★★★ 磁碟出現 I/O error，或檔案系統被自動改成唯讀**：

```bash
$ sudo dmesg -T | grep -iE 'I/O error|remount.*read-only|EXT4-fs error|Medium Error'
```

有輸出就代表硬體已經在出錯。★★★★★ **第一件事是把資料備份出去**，
不是 `fsck`、不是 `mount -o remount,rw`。在壞掉的磁碟上跑修復工具，
很可能把「大部分還讀得到」變成「什麼都讀不到」。

**【3】★★★★★ RAID 已經降級，而你不確定該拔哪一顆**：拔錯一顆就是整組陣列全毀。
先用 `lsblk -o NAME,SERIAL`、`mdadm --detail`、機櫃上的指示燈（`ledctl locate=`）
三方交叉確認到磁碟序號那一層，確認不了就不要拔。

**【4】★★★★★ 手上沒有備份，而下一步是不可逆操作**：`mkfs`、`dd`、`parted`、
`zpool destroy`、`btrfs check --repair`、`mdadm --zero-superblock`、`rm -rf`。
★★★★★ 沒有可還原的備份就沒有回頭路 —— 停下來，先想辦法把資料複製出去。

**【5】★★★★ 系統還開著但你已經改壞了關鍵設定**（fstab、sudoers、網路、GRUB）：
★★★★★ **先不要重開機**。系統還活著的時候你有 shell 可以修，重開之後可能就進不去了。
把當下的 shell 保留住，開第二個終端做驗證，確認新設定能用再考慮重開。

**【6】★★★★ 災情比你以為的大**：不只一個服務有問題、多台機器同時異常、
或者連 SSH 都進不去。這時你面對的可能是網路、儲存、電力層級的事件，
繼續在單機上找答案只會浪費時間 —— 往上升級成事件處理流程
（[[100-02-09-svc-維運-事件處理與升級流程]]）。

**【7】★★★ 同一個問題試了超過三十分鐘，而且開始「隨便改改看」**：★★★★★ 隨機修改
會製造新問題，讓單一故障變成多重故障，而且沒人知道你動過什麼。
停下來，把做過的每一個動作寫下來，找第二個人一起看。

**【8】★★★ 要在正式環境做不可逆的變更，而且沒有走變更流程**：即使技術上你做得到，
制度上也應該先取得核准與備援計畫（[[100-02-08-guide-維運-變更管理流程]]）。
半夜自己判斷「這個改一下應該沒差」是事故報告裡出現頻率最高的一句話。

## 症狀 → 章節 快速對照

★★★★ 找不到自己的症狀時，用這張表反查該讀哪一篇原文。

| 你遇到的事 | 本手冊情境 | 原理篇章 |
| --- | --- | --- |
| 開不了機、emergency mode、GRUB rescue、核心 panic | 情境一 | [[020-01-25-guide-Linux-開機流程與GRUB救援]] |
| `/boot` 滿了、核心升級失敗、initramfs 產不出來 | 情境二【4】、情境一【2】 | [[020-01-25-guide-Linux-開機流程與GRUB救援]] |
| 磁碟滿、inode 用盡、`df` 與 `du` 對不起來 | 情境二 | [[020-01-15-cmd-Linux-磁碟分割與掛載]] |
| 已刪除的檔案不還空間 | 情境二【2】 | [[020-01-10-cmd-Linux-程序管理與訊號]] |
| 服務起不來、`status=203/EXEC`、masked、相依順序 | 情境三 | [[020-01-17-cmd-Linux-systemd服務管理]] |
| `Permission denied`、777 沒用、ACL、SELinux、immutable | 情境四 | [[020-01-08-cmd-Linux-檔案權限與擁有者]] |
| 唯讀掛載、`noexec`、sticky bit | 情境四【2】 | [[020-01-15-cmd-Linux-磁碟分割與掛載]] |
| cron 沒跑、cron 裡找不到指令、`%` 的陷阱 | 情境五 | [[020-01-18-guide-Linux-排程工作]] |
| systemd timer 沒觸發、`OnCalendar` 寫錯 | 情境五【4】 | [[020-01-18-guide-Linux-排程工作]] |
| `command not found`、`PATH`、`sudo` 的 secure_path | 情境六 | [[020-01-20-guide-Linux-環境變數與設定檔]] |
| 程序砍不掉、`D` 狀態、殭屍、訊號沒反應 | 情境七 | [[020-01-10-cmd-Linux-程序管理與訊號]] |
| OOM Killer、記憶體不足、swap 抖動、`MemoryMax` | 情境八 | [[020-01-10-cmd-Linux-程序管理與訊號]]、[[020-01-26-guide-Linux-核心模組與sysctl調校]] |
| load 很高、`%iowait`、磁碟很慢、CPU 飆高 | 情境九 | [[060-01-03-04-guide-監控-效能瓶頸排查方法論]] |
| apt/dnf 鎖檔、dpkg 中斷、GPG 金鑰、相依衝突 | 情境十 | [[020-01-14-guide-Linux-套件管理]] |
| 網路不通的六層分層排查、DNS、路由、綁定位址 | 情境十一 | [[020-01-16-cmd-Linux-網路基礎指令]] |
| 憑證「尚未生效」、套件庫時間錯、AD 登入失敗 | 情境十二 | [[020-01-28-cmd-Linux-時間同步NTP與chrony]] |
| RAID 降級、換磁碟、resync、mdadm 開機組不起來 | 情境十三【1】 | [[020-01-29-guide-Linux-網路儲存與軟體RAID]] |
| ZFS DEGRADED、permanent errors、Btrfs metadata 滿 | 情境十三【2】～【5】 | [[020-01-24-guide-進階儲存-ZFS與Btrfs]] |
| 新硬碟看不到、裝置名稱漂移、該用 UUID | 情境十四【1】【2】 | [[020-01-27-cmd-Linux-硬體資訊與裝置管理]]、[[020-01-15-cmd-Linux-磁碟分割與掛載]] |
| NFS 卡死、`Stale file handle`、開機卡在掛載 | 情境十四【3】 | [[020-01-29-guide-Linux-網路儲存與軟體RAID]] |
| 日誌爆量、journald 沒持久化、logrotate 沒生效 | 情境十五 | [[020-01-19-guide-Linux-日誌系統]] |
| 改設定沒生效、drop-in 覆寫、`hash -r`、`ldconfig` | 情境十六 | [[020-01-17-cmd-Linux-systemd服務管理]]、[[020-01-30-guide-Linux-原始碼安裝與系統升級]] |
| CRLF、變數沒引號、`set -e` 的例外 | 情境十七 | [[020-01-21-cmd-Linux-Shell腳本入門]]、[[020-01-22-guide-Linux-Shell腳本進階]] |
| 帳號登不進去、`sudo` 壞掉、單一使用者模式救援 | 情境十八 | [[020-01-09-cmd-Linux-使用者與群組管理]] |
| 找檔案、找內容、找誰吃了空間 | 全篇工具 | [[020-01-07-cmd-Linux-尋找檔案與內容]] |
| 看日誌、`tail -f` 與 `tail -F` 的差別 | 全篇工具 | [[020-01-06-cmd-Linux-檢視檔案內容]] |
| 管線吞掉錯誤、`2>&1` 的順序 | 情境五、十七 | [[020-01-11-cmd-Linux-輸入輸出重導向與管線]] |
| 從日誌裡撈出統計、批次修改設定 | 全篇工具 | [[020-01-12-cmd-Linux-文字處理三劍客]] |
| 備份打包、解開來路不明的封存 | 情境二、十三 | [[020-01-13-cmd-Linux-壓縮與封存]] |
| 自編軟體跑的是舊版、大版本升級卡一半 | 情境十六【3】、情境十 | [[020-01-30-guide-Linux-原始碼安裝與系統升級]] |

## 延伸閱讀

**本章各篇（原理都在這裡，本手冊只做索引）**

- [[020-01-00-idx-Linux基礎]] —— 本章索引與建議閱讀順序
- [[020-01-23-guide-Linux-Linux常見疑難排解]] —— ★★★★★ **排錯方法論本身**：四個原則、
  黃金 60 秒、十大故障類型、重開機前清單。本手冊是它的「依症狀展開版」，兩篇配合看
- [[020-01-08-cmd-Linux-檔案權限與擁有者]] —— rwx 對目錄的意義、umask、特殊權限、ACL（情境四）
- [[020-01-09-cmd-Linux-使用者與群組管理]] —— 帳號生命週期、`visudo`、sudoers.d（情境十八）
- [[020-01-10-cmd-Linux-程序管理與訊號]] —— 訊號、程序狀態碼、OOM Killer（情境七、八、九）
- [[020-01-14-guide-Linux-套件管理]] —— apt/dnf、套件庫、`dnf history` 回退（情境十）
- [[020-01-15-cmd-Linux-磁碟分割與掛載]] —— `df`/`du`、fstab、掛載選項、LVM（情境二、四、十四）
- [[020-01-16-cmd-Linux-網路基礎指令]] —— 分層排查、`ip`、`ss`、DNS、netplan（情境十一）
- [[020-01-17-cmd-Linux-systemd服務管理]] —— unit 結構、drop-in、`systemctl cat`（情境三、十六）
- [[020-01-18-guide-Linux-排程工作]] —— cron 四大失敗原因、systemd timer（情境五）
- [[020-01-19-guide-Linux-日誌系統]] —— journald 持久化、logrotate、`postrotate`（情境十五）
- [[020-01-20-guide-Linux-環境變數與設定檔]] —— `PATH`、設定檔載入順序、作用域（情境六）
- [[020-01-21-cmd-Linux-Shell腳本入門]] —— shebang、`set -euo pipefail`（情境十七）
- [[020-01-22-guide-Linux-Shell腳本進階]] —— `set -e` 的六個例外、`trap`、鎖檔（情境十七）
- [[020-01-24-guide-進階儲存-ZFS與Btrfs]] —— pool 狀態、scrub、快照與回滾（情境十三）
- [[020-01-25-guide-Linux-開機流程與GRUB救援]] —— 五階段、GRUB、initramfs、chroot（情境一、十八）
- [[020-01-26-guide-Linux-核心模組與sysctl調校]] —— sysctl、`ulimit` 三層、cgroup（情境三、八、十六）
- [[020-01-27-cmd-Linux-硬體資訊與裝置管理]] —— `smartctl`、`lspci`、udev 命名（情境九、十四）
- [[020-01-28-cmd-Linux-時間同步NTP與chrony]] —— chrony 判讀、AD 時間要求（情境十二）
- [[020-01-29-guide-Linux-網路儲存與軟體RAID]] —— NFS/CIFS、mdadm 換碟與監控（情境七、十三、十四）
- [[020-01-30-guide-Linux-原始碼安裝與系統升級]] —— `ldconfig`、大版本升級與回退（情境十、十六）

**排錯時常一起用到的其他章節**

- [[020-02-01-98-trouble-SSH-常見故障排除]] —— 連不上機器時先看這份，它是進到本手冊的前提
- [[020-02-02-98-trouble-systemd-常見故障排除]] —— systemd 與排程的深入排錯
- [[100-02-10-guide-維運-故障排除方法論]] —— 制度層面的排錯流程與記錄要求
- [[100-02-09-svc-維運-事件處理與升級流程]] —— 什麼時候該升級、要通知誰、怎麼記錄
- [[100-01-03-guide-日誌-系統監控與告警]] —— 讓問題在爆炸前就被發現
- [[100-01-02-guide-日誌-日誌集中與輪替]] —— 機器掛了日誌還在，事後才查得到
- [[060-01-03-04-guide-監控-效能瓶頸排查方法論]] —— CPU／記憶體／I／O／網路的系統化判讀
- [[060-01-03-03-guide-監控-資源診斷工具集]] —— `iostat`、`vmstat`、`pidstat` 等工具的完整用法
- [[060-01-04-03-guide-ss-netstat-與lsof]] —— 誰在聽哪個埠、誰開著哪個檔
- [[060-01-04-01-guide-tcpdump-基礎抓包]] —— 最後手段：直接看封包走到哪裡
- [[090-02-02-guide-防火牆-ufw基礎與實務]] —— 連線逾時的答案多半在這裡
- [[090-02-07-guide-防護-SELinux與AppArmor]] —— 權限全對卻仍被拒時的下一站
- [[090-07-04-guide-資安實踐-資安事件應變流程]] —— 判斷是「故障」還是「入侵」之後的正式流程
- [[090-07-02-guide-資安實踐-密碼與帳號管理實務]] —— 帳號生命週期與特權管理
- [[050-01-03-06-svc-PVE-備份與還原]] —— 救不回來時的快照還原
- [[040-02-09-guide-機房-伺服器上架與初始設定]] —— IPMI／iDRAC 與磁碟槽位對照表，
  ★★★★ 上架時就做好，不要等被鎖在外面才找
