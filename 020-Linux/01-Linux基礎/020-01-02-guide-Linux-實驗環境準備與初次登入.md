---
title: "實驗環境準備與初次登入"
desc: "用 WSL2、虛擬機或 VPS 建出可以安心亂玩的練習環境"
aliases: [WSL, VM, VPS, 練習機]
tags: [群組/Linux, linux/基礎, 主題/環境]
category: Linux基礎
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-01-01-guide-Linux-Linux是什麼與發行版選擇]]"]
updated: 2026-08-29
---

# 實驗環境準備與初次登入

> [!abstract] 這篇你會學到
> - 選出適合自己的練習環境：WSL2、本機虛擬機、還是雲端 VPS ★★★
> - 建好一台**壞掉可以三分鐘還原**的練習機——這是能大膽學習的前提 ★★★★
> - 完成第一次登入後該做的六件事，養成正確的開機習慣 ★★★
> - 避開「把自己鎖在門外」這個新手最容易犯、代價最大的錯 ★★★★★

## 前置知識

- [[020-01-01-guide-Linux-Linux是什麼與發行版選擇]]

---

## 觀念說明

### ★★★★ 為什麼一定要「可拋棄」的環境

學 Linux 一定會弄壞東西——改壞 `sshd_config` 連不進去、`chmod` 打錯權限、
`rm -rf` 少打一個字。這些都是**必經之路**，重點不是避免弄壞，
而是**弄壞之後能三分鐘還原**。★★★

只要還原成本夠低，你就敢做這些事：

- 敢直接改 `/etc/ssh/sshd_config` 而不是只讀教學 ★★★
- 敢真的把磁碟塞爆看看會發生什麼 ★★
- 敢執行那個「看起來很危險」的指令，親眼看到後果 ★★

如果你只有一台正式伺服器可以練，你會什麼都不敢動，學習效率會非常差。★★★

### ★★★ 三種環境的取捨

| | WSL2 | 本機虛擬機 | 雲端 VPS |
| --- | --- | --- | --- |
| 建置速度 | 最快（5 分鐘） | 中（20 分鐘） | 快（3 分鐘） |
| 成本 | 免費 | 免費 | 每月數美元起 |
| 快照還原 ★★★ | `wsl --export/--import` | 內建快照，最方便 | 廠商快照，可能收費 |
| 擬真度 ★★★ | **較低**（見下方警告） | 高 | **最高** |
| 對外服務測試 ★★★ | 不行（無公網 IP） | 不行 | **可以** |
| 多機練習 ★★ | 麻煩 | 容易 | 容易但要付多份錢 |
| 適合 | 日常指令練習、開發 | 服務架設、多機實驗 | HTTPS、憑證、真實部署 |

> [!warning] WSL2 不是完整的 Linux，有幾個地方會騙你 ★★★★
> - **systemd 預設可能沒啟用**（新版 WSL 需在 `/etc/wsl.conf` 開啟），★★★
>   `systemctl` 會直接報錯，第 [[020-01-17-cmd-Linux-systemd服務管理]] 篇會受影響
> - **核心是微軟客製的**，`uname -r` 會看到 `microsoft-standard-WSL2` ★★
> - **沒有公網 IP**，`localhost` 雖然和 Windows 互通，但外面連不進來 ★★★
> - `/mnt/c` 底下的 Windows 檔案**權限模型是模擬的**，練 `chmod` 會看到奇怪結果 ★★★
> - 開機流程與 init 系統跟真實機器不同 ★★
>
> 練指令沒問題，練「架伺服器」建議至少用虛擬機。★★★

> [!tip] 最務實的組合 ★★★
> **WSL2（日常打指令）+ 一台便宜 VPS（練 HTTPS、憑證、對外服務）**。
> 虛擬機留給需要多台機器互連的實驗（例如主從複寫、叢集）。

---

## 逐步說明

### ★★★ 方案 A：WSL2（Windows 使用者最快的起點）

在 **PowerShell（系統管理員）** 執行：

```powershell
wsl --install
```

這一行會裝好 WSL2 元件並安裝預設的 Ubuntu。想選發行版：

```powershell
wsl --list --online          # 看有哪些可裝
wsl --install -d Ubuntu-24.04
```

裝完重開機，第一次啟動會要你設定使用者名稱與密碼。

> [!tip] WSL 常用管理指令
> ```powershell
> wsl -l -v                        # ★★ 列出已安裝的發行版與版本
> wsl --set-default Ubuntu-24.04   # ★ 設定預設發行版
> wsl --shutdown                   # ★★★ 關閉所有 WSL（設定改完要這樣重啟）
> wsl --unregister Ubuntu-24.04    # ★★★★★ 砍掉整個發行版（不可逆！）
> ```
> ★★★★ `--unregister` 沒有任何確認提示，家目錄裡的東西**一併消失**，
> 打之前先確認你要砍的是哪一個名稱。

**啟用 systemd**（強烈建議，否則後面很多章節做不了）：★★★

```bash
sudo nano /etc/wsl.conf
```

```ini
[boot]
systemd=true
```

存檔後在 PowerShell 執行 `wsl --shutdown`，重新開啟即可。★★ 驗證：

```bash
systemctl is-system-running
```

```
running
```

**WSL 的快照就是匯出匯入**：★★★

```powershell
# 備份（先關掉再匯出比較保險）★★
wsl --shutdown
wsl --export Ubuntu-24.04 D:\wsl-backup\ubuntu-clean.tar

# 還原成一個新的實例 ★★
wsl --import Ubuntu-lab D:\wsl\Ubuntu-lab D:\wsl-backup\ubuntu-clean.tar
wsl -d Ubuntu-lab
```

> [!tip] 建一個「乾淨基準」再開始練 ★★★★
> 裝好、更新完、設定好使用者之後**立刻匯出一份**命名為 `clean`。
> 之後每次玩壞了，`wsl --unregister` 再 `wsl --import` 就回到乾淨狀態，
> 比重裝快得多。

### ★★★ 方案 B：本機虛擬機（Multipass 最省事）

Multipass 是 Canonical 出的輕量 Ubuntu VM 工具，一行指令開一台機器：

```bash
# Windows: winget install Canonical.Multipass
# macOS:   brew install multipass
# Linux:   snap install multipass

multipass launch --name lab01 --cpus 2 --memory 2G --disk 20G 24.04   # ★★★ 磁碟開太小之後很難救
multipass shell lab01
```

```
Launched: lab01
```

快照與還原：★★

```bash
multipass stop lab01                          # ★★★ 一定要先停機才拍得了快照
multipass snapshot lab01 --name clean
# ……弄壞之後……
multipass restore lab01.clean                 # ★★★★ 還原會覆蓋現況，未存的東西沒了
```

> [!tip] 需要多台機器互連時 ★★
> `multipass launch --name lab02` 再開一台，兩台預設在同一個網段可以互通。
> 用 `multipass list` 看各自的 IP，就能練 SSH 互連、主從複寫、負載平衡。

用 VirtualBox 或 Hyper-V 也可以，重點都一樣：**裝完先拍一張快照**。★★★

### ★★★★ 方案 C：雲端 VPS（唯一能練真實對外服務的方式）

任何一家 VPS 都可以。開機後你會拿到 **IP、root 密碼或金鑰**。

```bash
ssh root@203.0.113.10
```

第一次連線會看到指紋確認：

```
The authenticity of host '203.0.113.10' can't be established.
ED25519 key fingerprint is SHA256:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.   # ★★★ 這串要拿去比對
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

> [!warning] 不要無腦打 yes ★★★★
> 這個指紋應該和 VPS 主控台顯示的主機金鑰指紋一致。
> 在不受信任的網路上，這一步是唯一能擋下中間人攻擊的機會。★★★★
> 詳見 [[020-02-01-01-cmd-SSH-原理與第一次連線]]。

> [!danger] VPS 最重要的一件事：先確認你有 Console 存取 ★★★★★
> 動任何 SSH、防火牆設定**之前**，先到 VPS 主控台找到
> 「VNC Console」「Serial Console」「Recovery Mode」之類的功能，
> **確認你會用**。★★★★ 這是你把自己鎖在門外時唯一的救命通道。
> 沒確認過就改 sshd 設定，等於在沒有備用鑰匙的情況下換門鎖。

---

## 完整實戰範例：新機第一次登入的六件事

不管哪種環境，登入後這六件事請養成習慣。★★

### ★★★ 1. 確認你是誰、在哪裡

```bash
whoami
id
hostname
pwd
```

```
ubuntu
uid=1000(ubuntu) gid=1000(ubuntu) groups=1000(ubuntu),27(sudo)   # ★★★ 看有沒有 sudo
lab01                                                            # ★★★★ 確認是不是你要的那台
/home/ubuntu
```

`groups` 裡有 `sudo`（RHEL 系是 `wheel`）代表你可以提權。★★★

> [!tip] 養成「先確認再動手」的習慣 ★★★★
> 維運事故有很大一部分來自「在 A 機器上執行了要給 B 機器的指令」。★★★
> 每次登入先看一眼 `hostname`，成本一秒，能省下一場災難。
> 更好的做法是把主機名稱放進提示字元，見 [[060-01-05-03-guide-終端機-Bash與Zsh效率設定]]。

### ★★★ 2. 更新套件

```bash
sudo apt update && sudo apt upgrade -y
```

```
Get:1 http://archive.ubuntu.com/ubuntu noble InRelease [256 kB]
...
Reading package lists... Done
Building dependency tree... Done
42 packages can be upgraded. Run 'apt list --upgradable' to see them.   # ★★ 新機通常一堆待更新
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> sudo dnf upgrade -y
> ```
> ★★ `dnf` 沒有「先 update 再 upgrade」兩步驟，`upgrade` 一次做完。
> `dnf update` 是 `dnf upgrade` 的別名，兩者等價。

### ★★★ 3. 設定主機名稱與時區

```bash
sudo hostnamectl set-hostname lab01
timedatectl set-timezone Asia/Taipei     # 需要 sudo
timedatectl
```

```
               Local time: 三 2026-08-27 09:14:22 CST
           Universal time: 三 2026-08-27 01:14:22 UTC
                 RTC time: 三 2026-08-27 01:14:22
                Time zone: Asia/Taipei (CST, +0800)
System clock synchronized: yes                          # ★★★★ 這行是 no 要立刻處理
              NTP service: active                       # ★★ 沒有 active 就沒人在校時
```

> [!warning] `System clock synchronized: no` 要立刻處理 ★★★★
> 時間不對會造成一連串詭異問題：TLS 憑證驗證失敗、Kerberos 認證失敗、★★★★
> 日誌時間錯亂到無法追查、cron 排程在錯的時間跑。
> 先確認 NTP 服務有在跑：`systemctl status systemd-timesyncd`（或 `chronyd`）。
> 細節見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]]。

> [!tip] 伺服器時區該設 UTC 還是本地時區？★★
> 兩派都有道理。**單一機房、團隊都在同一時區** → 設本地時區，看日誌比較直覺。
> **跨區域、多機房** → 全部設 UTC，避免日光節約時間與時差造成的比對困難。
> ★★★ 重點是**整個環境要一致**，最怕的是有些機器 UTC 有些台北時間。

### ★★★★ 4. 建立自己的使用者，不要用 root 過日子

VPS 通常給你 root。**第一件事就是建立一般使用者**：★★★

```bash
sudo adduser mike                    # ★★★ 互動式，會問密碼與基本資料
sudo usermod -aG sudo mike           # ★★★★★ 一定是 -aG，少了 a 會清掉原有群組
```

驗證：

```bash
su - mike
sudo whoami
```

```
root      # ★★★★ 有這行才代表提權真的成立，不要跳過這步驗證
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ★★★ RHEL 系的提權群組是 **`wheel`** 不是 `sudo`，而且沒有 `adduser` 互動式指令：
>
> ```bash
> sudo useradd -m -s /bin/bash mike      # ★★★ 漏了 -m 不會有家目錄，漏了 -s 會拿到 nologin
> sudo passwd mike
> sudo usermod -aG wheel mike            # ★★★ 這裡是 wheel，照抄 sudo 會建出一個空群組
> ```
>
> `-m` 建家目錄、`-s` 指定 shell。Debian 系的 `adduser` 是包裝過的友善版本，
> 底層的 `useradd` 兩系都有。詳見 [[020-01-09-cmd-Linux-使用者與群組管理]]。

> [!danger] 為什麼不要用 root 日常操作 ★★★★★
> - ★★★★★ 打錯字沒有安全網。`rm -rf /var/log /` 中間多一個空格，root 會真的執行
> - ★★★ 沒有稽核軌跡。所有人都用 root，出事查不出是誰做的
> - ★★★ 服務不需要 root 權限也能跑，用 root 跑等於把整台機器賭進去
>
> 用一般使用者 + `sudo`，等於在每個危險操作前多一道確認。★★★

### ★★★ 5. 檢查資源狀況

```bash
df -h /          # 磁碟
free -h          # 記憶體
nproc            # CPU 核心數
```

```
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda1        20G  2.1G   17G  11% /            # ★★★ Use% 超過 80% 就該處理

               total        used        free      shared  buff/cache   available
Mem:           1.9Gi       241Mi       1.4Gi       1.0Mi       342Mi       1.6Gi   # ★★★ 看 available 不是 free
Swap:             0B          0B          0B                                       # ★★★ 小機器沒 swap 很危險

2
```

> [!tip] `Swap: 0B` 在小記憶體機器上要注意 ★★★★
> 很多 VPS 預設沒有 swap。1GB 記憶體的機器跑 MySQL + Nginx + PHP，
> ★★★ 很容易被 OOM Killer 砍掉服務。小機器建議加 1～2GB swap，見 [[020-01-15-cmd-Linux-磁碟分割與掛載]]。

### ★★★★ 6. 拍快照

**做完上面五件事之後、開始亂玩之前**，拍一張快照：★★★

```bash
# Multipass
multipass stop lab01 && multipass snapshot lab01 --name baseline

# WSL
wsl --shutdown
wsl --export Ubuntu-24.04 D:\wsl-backup\baseline.tar

# VPS：到廠商主控台建立 snapshot        # ★★★ 有些廠商只在關機狀態下才拍得到一致的快照
```

命名建議用 `baseline`、`before-nginx`、`before-twgcb` 這種**說明「這是做什麼之前」**的名字，★★★
不要用 `snapshot1`、`test`。

### ★★★★ 收尾驗收：一次確認六件事都真的做完了

「以為做了」和「真的做了」差很多。把下面這段貼進去跑一次，
每一行的 `OK` / `NG` 就是你的驗收結果：★★★

```bash
#!/usr/bin/env bash
# lab-check.sh —— 新機基準驗收，任何一項 NG 就回頭補做
chk(){ [ "$2" = "0" ] && printf 'OK   %s\n' "$1" || printf 'NG   %s\n' "$1"; }

id -nG | grep -qwE 'sudo|wheel'; chk "① 目前帳號在 sudo/wheel 群組" $?      # ★★★★ 沒過就別關掉這條連線
[ "$(id -u)" -ne 0 ];            chk "② 不是用 root 在操作" $?             # ★★★
[ "$(hostname)" != "localhost" ]; chk "③ 主機名稱已設定" $?                 # ★★
timedatectl show -p NTPSynchronized --value | grep -q yes
                                 chk "④ 系統時間已與 NTP 同步" $?           # ★★★
[ "$(df --output=pcent / | tail -1 | tr -dc 0-9)" -lt 80 ]
                                 chk "⑤ 根目錄使用率 < 80%" $?              # ★★★
[ "$(free -b | awk '/^Swap:/{print $2}')" -gt 0 ]
                                 chk "⑥ 有 swap 可用" $?                    # ★★★ 小記憶體機器才在意
```

預期輸出（一台做完六件事的 lab01）：

```text
OK   ① 目前帳號在 sudo/wheel 群組
OK   ② 不是用 root 在操作
OK   ③ 主機名稱已設定
OK   ④ 系統時間已與 NTP 同步
OK   ⑤ 根目錄使用率 < 80%
NG   ⑥ 有 swap 可用           # ★★★ VPS 常見，1GB 機器請補上 swap 再繼續
```

> [!warning] 這支腳本要在**拍快照之前**跑 ★★★★
> 驗收沒過就拍快照，等於把一台半成品的機器當成基準；
> 之後每次還原都回到同一個半成品，錯誤會一路跟著你。★★★

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| `wsl --install` 說虛擬化未啟用 ★★★ | BIOS 沒開 VT-x / AMD-V | 進 BIOS 開啟虛擬化，Windows 功能勾選「虛擬機器平台」 |
| WSL 裡 `systemctl` 報 `System has not been booted with systemd` ★★★★ | 未啟用 systemd | 寫 `/etc/wsl.conf` 的 `[boot] systemd=true` 後 `wsl --shutdown` |
| `sudo: command not found`（RHEL 最小安裝） ★★★ | 沒裝 `sudo` 套件 | `su -` 後 `dnf install -y sudo` |
| `mike is not in the sudoers file` ★★★★ | 使用者不在 sudo / wheel 群組 | `usermod -aG sudo mike`（RHEL 用 `wheel`），**要重新登入才生效** |
| 加了群組但 `sudo` 還是不行 ★★★ | 群組變更不會套用到現有 session | 完全登出再登入，或 `newgrp sudo` |
| SSH 連 VPS 顯示 `Connection refused` ★★★ | sshd 沒跑、埠不對、防火牆擋住 | 用主控台登入檢查 `systemctl status sshd`、`ss -tlnp \| grep ssh` |
| `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED` ★★★★★ | 主機重灌或 IP 被回收給別台 | 確認是預期的變動後 `ssh-keygen -R <IP>` 移除舊記錄 |
| 時間差好幾小時，日誌對不上 ★★★★ | 時區沒設或 NTP 沒同步 | `timedatectl set-timezone Asia/Taipei`、確認 NTP active |
| `df` 顯示磁碟滿但找不到大檔 ★★★ | 檔案被刪但程序還開著，或 inode 用光 | `lsof \| grep deleted`、`df -i`，見 [[020-01-15-cmd-Linux-磁碟分割與掛載]] |
| Multipass / VirtualBox 開不起來，說 VT-x 被占用 ★★★ | Windows 開了 Hyper-V，與 VirtualBox 的硬體虛擬化互斥 | 二選一：留 Hyper-V（用 WSL2／Multipass 的 Hyper-V 後端），或 `bcdedit /set hypervisorlaunchtype off` 後重開機 |
| `wsl --import` 進來的實例，一開機就是 `root@` ★★★ | 匯入的 tar 不帶預設使用者設定 | 在該實例的 `/etc/wsl.conf` 補上 `[user]` 段落與 `default=mike`，再 `wsl --shutdown` |
| VPS 用金鑰登入被拒 `Permission denied (publickey)` ★★★★ | 家目錄或 `~/.ssh` 權限太寬，sshd 直接忽略 `authorized_keys` | `chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys`、家目錄不可 group/other 可寫；見 [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] |
| `apt upgrade` 跑到一半說 `No space left on device` ★★★★ | 磁碟開太小（8G 以下），核心與快取塞爆 `/` | `sudo apt clean`、`sudo journalctl --vacuum-size=100M`；長期解是重開一台磁碟給足的機器 |
| 從快照複製出的第二台機器，SSH 指紋和第一台一模一樣 ★★★★ | host key 隨快照一起被複製 | 新機上 `sudo rm -f /etc/ssh/ssh_host_*` 後 `sudo ssh-keygen -A` 重新產生，再重啟 sshd |
| `multipass restore` 說 `snapshot ... does not exist` ★★★ | 快照名稱要寫成 `<實例>.<快照>`，且實例要先 stop | `multipass list --snapshots` 查正確名稱，`multipass stop lab01` 後再 restore |

### 排查步驟

**【1】** ★★★★ **先分流：是「連不上」還是「連上了但不對勁」**

```bash
$ ssh -o ConnectTimeout=5 mike@203.0.113.10 'hostname -s; id -un'
lab01
mike
#   ★★★ 判讀：有回應 → 走【5】查環境本身；
#        Connection refused / timed out → 走【2】【3】；
#        Permission denied → 走【4】。先分流才不會亂改設定。
```

**【2】** ★★★ **確認那台機器真的活著（先用不經過 SSH 的管道）**

```bash
$ multipass list
Name     State      IPv4            Image
lab01    Running    10.83.164.22    Ubuntu 24.04 LTS     # ★★★ State 不是 Running 就先開機
$ wsl -l -v
  NAME            STATE           VERSION
* Ubuntu-24.04    Stopped         2                      # ★★ WSL 停著很正常，wsl -d 就會起來
#   ★★★ VPS 沒有這兩個指令，改到廠商主控台看電源狀態與 VNC Console；
#        機器根本沒開卻在查 SSH 設定，是最常見的浪費時間。
```

**【3】** ★★★★ **網路層：分辨「沒人聽」與「被擋住」**

```bash
$ nc -zv 203.0.113.10 22
Connection to 203.0.113.10 22 port [tcp/ssh] succeeded!      # ★★★ 網路 OK，問題在認證，跳【4】
nc: connect to 203.0.113.10 port 22 (tcp) failed: Connection refused
#   ★★★ refused = 封包到得了機器但沒有程序在聽 → 從 Console 登入跑
#        `systemctl status ssh` 與 `ss -ltnp | grep :22`
（卡十幾秒最後 timed out）
#   ★★★ timeout = 封包被靜默丟掉 → 防火牆或安全群組（見 [[090-02-02-guide-防火牆-ufw基礎與實務]]）
```

**【4】** ★★★★ **認證層：看 ssh 到底走到哪一步**

```bash
$ ssh -v mike@203.0.113.10 2>&1 | grep -E 'Offering|Authentications that can continue'
debug1: Authentications that can continue: publickey        # ★★★ 伺服器只收金鑰，密碼登入已關
debug1: Offering public key: /home/mike/.ssh/id_ed25519 ED25519 SHA256:aaaa...
#   ★★★ 判讀：完全沒有 Offering → 你手上沒有對應的私鑰；
#        有 Offering 卻被拒 → 多半是伺服器端家目錄／~/.ssh 權限太寬（見錯誤表倒數第四列）。
#        ★★★★ 這一步不要用「乾脆把密碼登入打開」來繞過，那是把機器丟回爆破池。
```

**【5】** ★★★ **連上了：先確認自己是誰、在哪一台**

```bash
$ whoami; hostname; ip -brief addr show scope global
mike
lab01                                                       # ★★★ 不是你要的那台就立刻登出
eth0   UP   10.83.164.22/24
#   ★★★ 判讀：hostname 還是 ubuntu/localhost → 第 3 件事沒做完；
#        IP 和你連的位址對不上 → 你可能連到 NAT 後面另一台，回【1】確認目標。
```

**【6】** ★★★★ **`sudo` 不能用：分辨「沒加到群組」與「群組還沒生效」**

```bash
$ id -nG; getent group sudo
mike                                                        # ★★★ 目前 session 看到的群組
sudo:x:27:ubuntu,mike                                       # ★★★ 系統檔案裡其實已經有 mike
#   ★★★ 判讀：getent 有、id 沒有 → 只是【現有 session 沒重讀群組】，登出再登入即可；
#        兩邊都沒有 mike → 真的沒加成功，回去跑 usermod -aG sudo mike（RHEL 用 wheel）。
#        ★★★★ 這時候不要關掉手邊還有 sudo 的那條連線，否則沒人能改回來。
```

**【7】** ★★★ **WSL 專屬：systemd 沒起來**

```bash
$ systemctl is-system-running
System has not been booted with systemd as init system (PID 1). Can't operate.
$ cat /etc/wsl.conf
[boot]
systemd=true                                                # ★★★ 設定明明有寫
#   ★★★ 判讀：設定寫了卻沒生效 = 沒有真的重啟 → 回 PowerShell 執行 `wsl --shutdown`
#        （關掉視窗不算重啟）。★★★ 再確認 Windows 上的 WSL 版本夠新：`wsl --version`。
```

**【8】** ★★★★ **都救不回來：還原快照，並順手驗證快照真的可用**

```bash
$ multipass list --snapshots
Instance   Snapshot   Parent   Comment
lab01      baseline   --       --                           # ★★★ 沒有這行代表你根本沒快照
$ multipass stop lab01 && multipass restore lab01.baseline && multipass shell lab01
$ hostname; ls ~/                                            # ★★★ 還原後確認真的回到基準狀態
lab01
#   ★★★★ 還原完請立刻再拍一張新的 baseline —— 快照用掉一次之後，
#        下一次出事你需要的還是「一張已知可用的快照」。
```

---

## 安全性注意事項

> [!danger] VPS 開機後的黃金一小時 ★★★★★
> 一台剛開好、有公網 IP 的機器，**幾分鐘內就會開始被掃描與嘗試登入**。★★★★
> 這不是誇飾，去看 `journalctl -u ssh | grep "Failed password"` 就知道。
> 開機後第一小時內至少要完成：
>
> 1. 建立一般使用者並設強密碼 ★★★
> 2. 部署 SSH 金鑰、**停用密碼登入**（見 [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]]）★★★★
> 3. 停用 root 直接登入 ★★★
> 4. 開防火牆，只放行必要的埠（見 [[090-02-02-guide-防火牆-ufw基礎與實務]]）★★★
> 5. 裝上 Fail2ban（見 [[090-02-05-guide-防護-Fail2ban入侵防護]]）★★★
>
> 完整清單見 [[090-02-01-guide-防護-伺服器初始安全設定]]。

> [!warning] 改 SSH 設定的鐵則：保留一條退路 ★★★★★
> 修改 `sshd_config` 或防火牆規則時，**永遠保持一個已連線的 session 不要關掉**。★★★★★
> 用另一個終端機開新連線測試，確認新設定沒問題，才關掉舊的。
>
> ```bash
> # session 1：改設定並 reload（★★★★ 這條連線不要關）
> sudo systemctl reload ssh
>
> # session 2：測試新連線是否正常 ★★★
> ssh -p 2222 mike@203.0.113.10
> ```
>
> 如果新連線失敗，你還有 session 1 可以改回來。★★★

> [!tip] 練習機也要有基本防護 ★★★★
> 「反正是練習機」不是不設防的理由。有公網 IP 的機器被入侵後，
> 會被拿去當跳板攻擊別人、挖礦、發垃圾郵件，**責任在你**。★★★

> [!danger] 快照與匯出檔＝一整台機器的私鑰與密碼雜湊 ★★★★★
> `wsl --export` 出來的 `.tar`、Multipass 的快照、VPS 下載的映像檔，
> 裡面**完整包含**這些東西：★★★★
>
> | 檔案 | 洩漏後的後果 |
> | --- | --- |
> | `/etc/shadow` ★★★★★ | 所有帳號的密碼雜湊，可離線爆破 |
> | `~/.ssh/id_*` ★★★★★ | 你的使用者私鑰，等於別人可以用你的身分登入所有主機 |
> | `/etc/ssh/ssh_host_*_key` ★★★★ | 主機私鑰，別人可以冒充這台機器做中間人 |
> | `.env`、`~/.aws/credentials`、`.git-credentials` ★★★ | 資料庫密碼、雲端金鑰、Git token |
>
> ★★★★ 所以**不要把匯出檔丟進 OneDrive／Google Drive／公司網芳的共用資料夾**，
> 也不要為了方便 commit 進 git repo。要放遠端就先加密：
>
> ```bash
> gpg -c ubuntu-clean.tar        # ★★★ 產生 .tar.gpg，原始 tar 記得刪掉
> ```

> [!danger] 不要為了「先做完實驗」而把管理埠開上網際網路 ★★★★★
> 練習時最容易出現的臨時決定，就是「先把它綁 0.0.0.0 再說」。
> 這些埠一旦有公網 IP，被掃到的時間通常以**分鐘**計：★★★
>
> | 埠 | 服務 | 開上公網的實際後果 |
> | --- | --- | --- |
> | 3306 / 5432 ★★★★★ | MySQL / PostgreSQL | 弱密碼直接被登入，資料被拖走或加密勒索 |
> | 6379 ★★★★★ | Redis（預設無密碼） | 經典的寫入 `authorized_keys` 提權手法 |
> | 8006 / 5900 ★★★★ | Proxmox Web / VNC | 拿到的是**整台宿主機**，比拿到一個 VM 嚴重得多 |
> | 2375 ★★★★★ | Docker daemon（未加密） | 等同 root shell，可直接掛載宿主機根目錄 |
>
> ★★★ 正確做法是綁 `127.0.0.1`，需要遠端存取就走 SSH 埠轉發
> （見 [[020-02-01-05-cmd-SSH-隧道與埠轉發]]），不要為了省事開一個永久的洞。

> [!warning] 練習機不要放真實資料 ★★★★
> 練習機的防護等級低、快照到處複製、密碼常常是 `lab1234`。
> ★★★ 把機關的真實名冊、備份檔、正式站的 `.env` 放上去測試，
> 一旦被入侵就從「練習機被打」升級成**個資外洩通報事件**，
> 要走的是通報流程而不是重灌流程。測試資料請自己造假。

---

## 速查表

### 環境管理

| 指令 | 說明 |
| --- | --- |
| `wsl -l -v` ★★ | 列出 WSL 發行版與狀態 |
| `wsl --shutdown` ★★★ | 關閉所有 WSL（改設定後重啟用） |
| `wsl --export <名稱> <檔案>` ★★★ | 匯出快照 |
| `wsl --import <新名稱> <目錄> <檔案>` ★★★ | 從快照還原 |
| `wsl --unregister <名稱>` ★★★★★ | 刪除整個發行版，**不可逆、無確認** |
| `multipass launch --name X 24.04` ★★★ | 開一台 VM |
| `multipass snapshot X --name clean` ★★★ | 拍快照（需先 stop） |
| `multipass restore X.clean` ★★★ | 還原快照（會覆蓋現況） |
| `multipass list` ★★ | 列出所有 VM 與 IP |
| `multipass list --snapshots` ★★★ | 列出快照，還原前先確認名稱 |

### 初次登入檢查

| 指令 | 說明 |
| --- | --- |
| `whoami` / `id` ★★★ | 我是誰、屬於哪些群組 |
| `hostname` ★★★★ | 我在哪台機器 |
| `sudo apt update && sudo apt upgrade -y` ★★★ | 更新套件（RHEL：`dnf upgrade -y`） |
| `hostnamectl set-hostname X` ★★★ | 設定主機名稱 |
| `timedatectl set-timezone Asia/Taipei` ★★★ | 設定時區 |
| `timedatectl` ★★★ | 確認時間與 NTP 同步狀態 |
| `adduser X` + `usermod -aG sudo X` ★★★★ | 建立使用者並給予提權（RHEL：`wheel`；`-a` 不可省） |
| `df -h` / `free -h` / `nproc` ★★★ | 磁碟 / 記憶體 / CPU |

### 卡住時的第一動作

| 情況 | 第一動作 |
| --- | --- |
| SSH `Connection refused` ★★★ | `nc -zv <IP> 22` 分辨沒人聽還是被擋 |
| SSH `timed out` ★★★ | 查防火牆／安全群組，機器多半是活的 |
| `Permission denied (publickey)` ★★★ | `ssh -v` 看有沒有 Offering，再查 `~/.ssh` 權限 |
| `sudo` 說不在 sudoers ★★★ | `getent group sudo` 對照 `id -nG`，多半只是要重新登入 |
| WSL `systemctl` 報錯 ★★★ | `/etc/wsl.conf` 設好後**在 PowerShell** 跑 `wsl --shutdown` |
| 完全登不進去 ★★★★ | 用 Console（VNC / Serial / Recovery），不要再試 SSH |

---

## 練習題

> [!question]- 練習 1：建立你的基準環境
> 用任一方式建一台練習機，完成「六件事」，並拍下名為 `baseline` 的快照。
> 接著故意破壞它（例如 `sudo rm -rf /etc/ssh`），確認你**真的能還原**。
>
> **解答**
>
> 重點不在指令，而在最後一步：**沒有實際還原過的快照不算備份**。★★★★★
> 很多人拍了快照卻從沒試過還原，真的出事才發現快照設定錯誤或還原流程不會用。
>
> 這個習慣之後會延伸到 [[060-01-06-03-guide-傳輸-備份策略與還原演練]] —— 備份的價值不在備份本身，
> 而在於還原成功。

> [!question]- 練習 2：模擬把自己鎖在門外
> 在**虛擬機或 VPS**（不要用 WSL）上，故意把 `sshd_config` 的
> `Port` 改成 `2222` 但防火牆只開 22，然後 reload sshd。
> 開新連線會失敗。在不用快照的前提下，你要怎麼救回來？
>
> **解答**
>
> 三種救法，由好到壞：
>
> 1. **舊 session 還在** → 直接在舊 session 改回設定並 reload。這就是「保留退路」的價值。★★★★
> 2. **用 Console** → 從 VPS 主控台的 VNC / Serial Console 登入，改設定。★★★
>    這就是為什麼開機第一件事要先確認 Console 會用。
> 3. **都沒有** → 只能重灌，或掛載救援模式改檔案。代價很高。★★★
>
> 這題的目的是讓你在**練習機**上經歷一次，
> 這樣你在正式機上就不會犯同樣的錯。

> [!question]- 練習 3：為什麼 `usermod -aG` 的 `-a` 不能省？
> 查一下 `man usermod`，說明 `usermod -G sudo mike` 和
> `usermod -aG sudo mike` 的差別，以及省略 `-a` 會造成什麼後果。
>
> **解答**
>
> `-G` 是「**設定**這個使用者的附加群組清單」，會用你給的清單**取代**原本的。★★★★★
> `-a` 是 append，「**追加**到現有清單」。
>
> ```bash
> # mike 原本在 docker, adm 群組
> usermod -G sudo mike      # ★★★★★ mike 現在只在 sudo，被踢出 docker 和 adm！
> usermod -aG sudo mike     # ★★★ mike 現在在 docker, adm, sudo
> ```
>
> 少打一個 `-a`，可能讓使用者失去存取 Docker、讀日誌等權限，
> 而且不會有任何警告。★★★★ **加群組永遠用 `-aG`**。
> 更多細節見 [[020-01-09-cmd-Linux-使用者與群組管理]]。

---

## 小測驗

Q1. 為什麼練習環境必須「可拋棄」？這對學習方式有什麼影響？
Q2. WSL2 有哪三個地方會「騙你」，讓它不適合練架伺服器？
Q3. 在 VPS 動 SSH 或防火牆設定之前，第一件該確認的事是什麼？
Q4. 修改 `sshd_config` 時的「保留退路」具體做法是什麼？
Q5. `usermod -G sudo mike` 與 `usermod -aG sudo mike` 的差別？後果？
Q6. RHEL 系的提權群組叫什麼？建立使用者的指令與 Debian 的 `adduser` 有何不同？
Q7. `timedatectl` 顯示 `System clock synchronized: no` 會引發哪些看似無關的問題？
Q8. 伺服器時區該設 UTC 還是本地？判斷準則是什麼？
Q9. 是非：拍了快照就等於有了備份，不需要實際測試還原。
Q10. VPS 開機後的第一小時至少要完成哪五件事？

> [!question]- 測驗答案
> **Q1.** ★★★ 因為學習過程一定會弄壞東西；還原成本低才敢真的做危險操作，只能看不敢做的學習效率極差（見「為什麼一定要可拋棄的環境」）。
> **Q2.** ★★★ systemd 預設可能未啟用、核心是微軟客製、沒有公網 IP（另有 `/mnt/c` 權限模型是模擬的）。
> **Q3.** ★★★★★ 確認主控台（VNC/Serial Console）存取會用——那是把自己鎖在門外時唯一的救命通道。
> **Q4.** ★★★★ 保留一條已連線的 session 不關，用另一個終端機測試新連線，成功才關舊的。
> **Q5.** ★★★★★ `-G` 是「取代」附加群組清單，`-aG` 是「追加」。少了 `-a` 會把使用者踢出原本所有群組，包含 sudo。
> **Q6.** ★★★ `wheel`；RHEL 沒有互動式 `adduser`，要 `useradd -m -s /bin/bash` 加 `passwd`。
> **Q7.** ★★★ TLS 憑證驗證失敗、Kerberos/AD 認證失敗、日誌時間錯亂、cron 在錯的時間跑。
> **Q8.** ★★★ 單一機房同時區用本地時區；跨區域用 UTC。重點是整個環境一致。
> **Q9.** ★★★★ 否。沒有實際還原過的快照不算備份，還原流程或設定可能是錯的。
> **Q10.** ★★★ 建一般使用者並設強密碼、部署金鑰並停用密碼登入、停用 root 直接登入、開防火牆只放行必要埠、裝 Fail2ban。

---

## 延伸閱讀

- [[020-01-03-cmd-Linux-終端機與Shell入門]] — 環境建好了，開始學怎麼打指令
- [[980-03-guide-附錄-實驗環境搭建]] — 四種練習環境的完整建置細節
- [[090-02-01-guide-防護-伺服器初始安全設定]] — 新機上線的完整安全檢查清單
- [[020-02-01-01-cmd-SSH-原理與第一次連線]] — SSH 指紋驗證與 known_hosts
- [[020-01-09-cmd-Linux-使用者與群組管理]] — 使用者、群組與 sudo 的完整說明
