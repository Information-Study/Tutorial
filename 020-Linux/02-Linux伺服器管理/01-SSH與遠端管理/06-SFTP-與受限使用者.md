---
title: "SFTP 與受限使用者"
desc: "伺服器端的受限帳號體系：四種型態、chroot 目錄設計、生命週期治理與可交稽核的日誌"
aliases: [sftp, chroot, internal-sftp, rrsync, 受限帳號, 廠商帳號]
tags: [群組/Linux, 服務/ssh, 主題/權限, 主題/稽核]
category: SSH與遠端管理
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[04-sshd-伺服器端設定]]", "[[01-scp與sftp傳輸]]", "[[08-檔案權限與擁有者]]"]
updated: 2026-08-28
---

# SFTP 與受限使用者

> [!abstract] 這篇你會學到
> - 用**四種受限帳號型態**（chroot SFTP／rrsync／單一指令／git-shell）對應不同的委外情境，並說得出各自的**殘留風險**
> - 設計**上傳目錄結構**，讓 Web 服務讀得到廠商上傳的檔案、卻寫不進去也執行不了
> - **★★★★★ 封死受限帳號的三條提權路徑**：開隧道、改自己的 `authorized_keys`、寫進被 root 執行的路徑
> - 把廠商帳號納入**生命週期治理**：申請單 → 建立 → 到期日雙保險 → 停用 → 資料刪除紀錄
> - 把 `internal-sftp -l INFO` 的日誌**分流成獨立檔案**，產出「本月誰上傳了哪些檔案」的稽核月報
> - **★★★★ 改 `Match` 區塊時不要把管理員一起關進 chroot**：`sshd -t`、`sshd -T -C` 與自動回滾 SOP

## 前置知識

- [[04-sshd-伺服器端設定]] —— `sshd_config` 的通用指令、drop-in 載入順序、`Match` 的語意
- [[01-scp與sftp傳輸]] —— **客戶端**的 `sftp` 操作、批次傳輸、基本的 chroot 權限規則
- [[08-檔案權限與擁有者]] —— rwx、setgid、POSIX ACL
- [[09-使用者與群組管理]] —— `useradd` / `usermod` / `chage` 的一般用法
- [[02-SSH-金鑰認證與ssh-agent]] —— 公鑰認證與 `authorized_keys` 選項語法

> [!note] 這篇跟 [[01-scp與sftp傳輸]] 的分工 ★★★
> [[01-scp與sftp傳輸]] 站在**客戶端**：怎麼傳、怎麼保留權限、跳板機怎麼過，
> 末尾附了一支 `create-sftp-user` 讓你**先能動起來**，chroot 的權限硬規則那篇也寫過了。
>
> 這篇站在**伺服器端的治理層次**：不是「怎麼開一個 SFTP 帳號」，
> 而是「**機關怎麼管一整批廠商帳號十年不出事**」——
> 帳號有幾種型態、目錄怎麼跟 Web 服務共存、到期怎麼自動失效、
> 稽核來要「上個月誰上傳了什麼」時交不交得出報表。
> 重複的部分只做一句話複習並連結過去，不重寫。

## 觀念說明

### 受限帳號不是一個設定，是五層 ★★★★

```text
★★★★ 五層都成立才叫「可以交差的受限帳號」，缺一層就是一個後門：

 ① 認證層  只收公鑰、金鑰放【chroot 之外】由 root 擁有、★★★★ 綁到期日
 ② 授權層  Match Group → ForceCommand internal-sftp（拿不到 shell）
            + AllowTcpForwarding no / PermitTTY no / PermitTunnel no
 ③ 檔案層  ChrootDirectory、upload/ 與 download/ 分開、setgid + ACL、配額
            ★★★★★ 上傳目錄不可以被 Web 當程式執行
 ④ 稽核層  -l INFO → 獨立日誌 → 輪替（保存期限＝稽核要求）→ 月報 CSV
 ⑤ 生命週期 申請單 → 到期停用 → 資料保存 N 天 → 刪除紀錄；★★★★ 每季清查

★★★ 最常見的失敗：①②③ 做得很漂亮，④⑤ 完全沒有 ——
     三年後稽核問「vendor03 是誰申請的、還在用嗎」沒人知道，
     而它的金鑰還在某個離職員工的筆電裡。
```

### ★★★★ 四種受限帳號型態

不是所有「不給 shell」的需求都該用 chroot SFTP。先對號入座再動手：

| 型態 | 可做什麼 | 不能做什麼 | 典型情境 | 殘留風險 |
| --- | --- | --- | --- | --- |
| **★★★★ 純 SFTP + chroot**<br>`ForceCommand internal-sftp` | 在 chroot 內讀寫檔案、建目錄、改檔名 | 執行任何程式、看到 chroot 以外、轉發埠 | 委外廠商每月交報表、對外收件匣 | **★★★★★ 上傳的檔案被別的服務執行**（Web 解析 PHP）；佔滿磁碟；目錄權限設錯就完全連不上 |
| **★★★ rsync-only**<br>`command="rrsync -ro /path"` | 只對指定目錄做 rsync（可再限唯讀／唯寫） | 執行其他指令、跑到目錄外、用被封鎖的 rsync 選項 | 備份主機來拉檔、離線機房同步 | `--delete` 誤刪（用 `-no-del`）；覆寫既有備份（用 `-no-overwrite`）；rrsync 的選項白名單本身就是攻擊面 |
| **★★★★ 單一指令帳號**<br>`restrict,command="…"` | 只執行寫死的那一支程式 | 帶自己的指令、開 pty、轉發 | CI 觸發部署、遠端重載服務 | **★★★★★ 腳本若拼接 `$SSH_ORIGINAL_COMMAND` 就是命令注入**；那支腳本若用 sudo，等於把 sudo 借出去 |
| **★★★ git-shell 帳號**<br>`--shell /usr/bin/git-shell` | `git push` / `git pull`、跑 `~/git-shell-commands/` 裡的自訂指令 | 任意指令、互動 shell（沒有該目錄時） | 自建 git 中繼站、離線環境交付程式碼 | **★★★★★ repo 的 hook 就是可執行檔**，能 push 就可能能執行程式碼；`git-shell-commands` 目錄若使用者可寫＝拿到 shell |

> [!tip] 選型一句話 ★★★
> **只交檔** → chroot SFTP。**要增量同步** → rrsync。**要「按一下就做某件事」** → `command=`。
> **要交程式碼** → git-shell。需求「什麼都要一點」時**開四個帳號**，不要開一個萬能帳號。

### chroot 的硬規則（一句話複習）★★★

`ChrootDirectory` 指到的目錄**以及它往上的每一層**，都必須 root 擁有、group 與 other 不可寫。
細節見 [[01-scp與sftp傳輸]] 與 [[08-檔案權限與擁有者]]，這裡只留驗證方式：

```bash
$ namei -l /srv/sftp/vendor01/upload
f: /srv/sftp/vendor01/upload
 drwxr-xr-x root root     /
 drwxr-xr-x root root     srv
 drwxr-xr-x root root     sftp
 drwxr-xr-x root root     vendor01        # ★★★★ 這行以上全部 root、且沒有 group/other 的 w
 drwxrws--- vendor01 sftp-vendor01 upload # ★★★ 使用者只在這裡有寫入權
```

由這條規則直接推出本篇要解決的問題：**既然 chroot 根不可被使用者寫入，
帳號一定要有可寫的子目錄**，而子目錄要給誰讀、給誰寫、新檔案權限長什麼樣，
就是下面「目錄結構設計」的主題。

### ★★★★ 為什麼 chroot 下只能用 internal-sftp

```text
★★★★ 兩個獨立的理由，任何一個都足以讓外部 sftp-server 失敗：

 ① 【執行檔不在牢籠裡】chroot 後要 exec 的是
    /srv/sftp/vendor01/usr/lib/openssh/sftp-server（不存在）；就算複製進去，
    還缺 ld-linux、libc、libcrypto…，少一個 .so 就啟動失敗，
    而且從客戶端【看不出是缺哪一個】

 ② 【需要透過使用者的 login shell 啟動】ForceCommand 是「用 login shell 加 -c 執行」，
    而受限帳號的 shell 是 /usr/sbin/nologin，印一行字就結束，subsystem 起不來

★★★★ internal-sftp 是 sshd【行程內】實作：不 exec、不需要 shell、牢籠裡不需要任何檔案
      → chroot 場景【唯一可行的選項】

★★★ 客戶端看到的失敗（分不出是哪個原因，一定要看伺服器日誌）：
      $ sftp vendor01@srv01
      subsystem request failed on channel 0 / Connection closed
```

## 環境準備與基礎設定

### 【0】★★★★ 動工前的鎖門預防

> [!danger] 這一步不做，改壞了就要跑機房 ★★★★
> `Match` 條件寫錯人，或 `Match` 放在檔案中段導致**後面每一行都被吃進條件**，
> **管理員下次登入也會被 chroot 進 `/srv/sftp/`** 且拿不到 shell。
> 這種錯誤 `sshd -t` **抓不到** —— 語法完全合法，只是條件寫錯人。

```bash
# ① 開第二個終端機登進去，【整個過程都不要關】 ★★★★ 這是逃生梯
$ ssh admin@srv01

# ② 備份現有設定
$ sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.$(date +%F)

# ③ ★★★★ 排一個五分鐘後自動回滾的計時器
$ sudo systemd-run --on-active=5min --unit=sshd-rollback \
    /bin/sh -c 'rm -f /etc/ssh/sshd_config.d/60-sftp-restricted.conf; systemctl restart ssh'
Running timer as unit: sshd-rollback.timer

# ④ 改完、驗證完、確定【新連線】進得來之後，才取消回滾
$ sudo systemctl stop sshd-rollback.timer
```

> [!tip] Ubuntu 24.04 起 sshd 是 socket 啟動 ★★★
> `ssh.socket` 監聽 22 埠，**每條新連線都是新的 sshd 行程、重新讀設定**，
> 所以「新連線立刻套用、既有連線不受影響」—— 這正是逃生梯成立的原因。
> 只有**改埠**才需要 `sudo systemctl restart ssh.socket`。
> RHEL 系是常駐服務，改完要 `sudo systemctl reload sshd`。

### 【1】套件與版本

```bash
$ ssh -V
OpenSSH_9.6p1 Ubuntu-3ubuntu13.5, OpenSSL 3.0.13 30 Jan 2024   # ★★ 9.3 以上才有 sshd -G

$ sudo apt install -y acl rsync clamav clamav-daemon   # setfacl / rrsync / 掃毒
$ ls -l /usr/bin/rrsync
-rwxr-xr-x 1 root root 13005 Jun  8 21:58 /usr/bin/rrsync   # ★★★ Debian 12／Ubuntu 22.04 起在這裡
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照 ★★★★
> ```bash
> sudo dnf install -y acl rsync policycoreutils-python-utils clamav clamd
> ```
> - `rrsync` 在 RHEL 是 **`/usr/share/doc/rsync/support/rrsync`**，要自己 `install -m 0755` 到 `/usr/local/bin/`
> - 日誌在 **`/var/log/secure`**，不是 `/var/log/auth.log`；服務名是 **`sshd`**（Ubuntu 是 `ssh`）
> - RHEL 8 的 `sshd_config` **沒有** `Include`，要直接改主檔；RHEL 9 才有 drop-in
> - **★★★★★ SELinux 是 RHEL 上最常見的「設定都對卻連不上」**：
>   ```bash
>   sudo setsebool -P ssh_chroot_rw_homedirs on
>   sudo semanage fcontext -a -t ssh_home_t "/etc/ssh/authorized_keys(/.*)?"
>   sudo restorecon -Rv /etc/ssh/authorized_keys
>   sudo ausearch -m avc -ts recent      # ★★★★ 出事第一個看這個
>   ```

### 【2】群組、目錄與帳號

```bash
$ sudo groupadd -f sftpusers            # ★★★ sshd Match 條件用的共用群組
$ sudo groupadd -f sftp-vendor01        # ★★★ 每人一個專屬群組，之後掛 ACL 給 Web 讀
$ sudo install -d -o root -g root -m 0755 /srv/sftp /srv/sftp/vendor01
$ sudo install -d -o root -g root -m 0755 /etc/ssh/authorized_keys   # ★★★★★ 金鑰放牢籠外

$ sudo useradd --no-create-home --home-dir /srv/sftp/vendor01 \
      --shell /usr/sbin/nologin --gid sftp-vendor01 --groups sftpusers \
      --comment "某某資訊 王小明/SR-2026-0812" vendor01
$ sudo passwd -l vendor01               # ★★★ 不給密碼，只走公鑰
$ id vendor01
uid=1002(vendor01) gid=1002(sftp-vendor01) groups=1002(sftp-vendor01),1001(sftpusers)
#                                                                     ↑★★★★ 沒有這個 Match 不會命中
```

> [!warning] `--home-dir` 指到 chroot 根，但**不要**加 `--create-home` ★★★
> 加了會用 `/etc/skel` 建目錄並 `chown` 給使用者 → chroot 根變成使用者擁有 →
> **連上就斷**（`bad ownership or modes`）。目錄一律用 `install -d -o root` 自己建。

### 【3】★★★★ sshd 的 Match 區塊

```bash
$ sudo tee /etc/ssh/sshd_config.d/60-sftp-restricted.conf >/dev/null <<'EOF'
# ★★★★ 全域：chroot 下唯一可行的 subsystem
Subsystem sftp internal-sftp

# ★★★★★ Match 區塊放在【整個檔案的最後面】
#   Match 的效力延伸到「下一個 Match 或檔案結尾」，
#   在它後面多寫一行「以為是全域」的設定，那行就只對 sftpusers 生效
Match Group sftpusers
    ChrootDirectory /srv/sftp/%u
    ForceCommand internal-sftp -u 0027 -l INFO
    AuthorizedKeysFile /etc/ssh/authorized_keys/%u
    AuthenticationMethods publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PermitTTY no
    X11Forwarding no
    AllowTcpForwarding no
    AllowStreamLocalForwarding no
    GatewayPorts no
    PermitTunnel no
    PermitUserRC no
    MaxSessions 4
    ClientAliveInterval 300
    ClientAliveCountMax 2
EOF
```

| 設定 | 為什麼要有它 | 漏掉的後果 |
| --- | --- | --- |
| **★★★★ `ChrootDirectory /srv/sftp/%u`** | `%u` 展開成帳號名，一條規則管所有廠商（可用 `%%` `%h` `%U` `%u`） | 每個帳號一個 Match 區塊，遲早漏改 |
| **★★★★ `ForceCommand internal-sftp`** | 忽略客戶端要求的任何指令，只跑行程內 SFTP | 客戶端可要求 `exec /bin/sh` → 拿到 shell |
| **★★★ `-u 0027`** | SFTP 建檔 umask：新檔 `0640`、新目錄 `0750` | 預設 `0666`／`0777` → **全世界可讀寫的上傳檔** |
| **★★★★ `-l INFO`** | 記錄 open／close／檔名／bytes | **稽核要傳輸紀錄時交不出東西** |
| **★★★★★ `AuthorizedKeysFile /etc/ssh/authorized_keys/%u`** | 金鑰在 chroot 外、root 擁有 | 使用者能自己加金鑰、加 `command=` → **永久後門** |
| **★★★★ `AuthenticationMethods publickey`** | 只收公鑰 | 弱密碼被爆破；廠商把密碼貼在群組聊天室 |
| **★★★★ `AllowTcpForwarding no` + `AllowStreamLocalForwarding no` + `PermitTunnel no`** | 禁止 `-L`／`-R`／UNIX socket／tun 轉發 | **受限帳號變成內網跳板**（見 [[05-SSH-隧道與埠轉發]]），或轉發到 Docker socket＝root |
| **★★★ `PermitTTY no` + `PermitUserRC no`** | 不配 pty、不執行 `~/.ssh/rc` | 多出互動介面與「使用者可寫路徑被執行」的攻擊面 |
| **★★ `MaxSessions` / `ClientAlive*`** | 限制通道數、清掉殭屍連線 | 單一帳號吃光 I/O、檔案鎖卡住 |

> [!note] `DisableForwarding yes` 可以一行關掉所有轉發 ★★★
> 效果等於同時關掉 TCP、StreamLocal、X11、agent、tunnel。
> 本篇仍逐項列出，是因為**驗收要逐項證明給稽核看**，一行 `DisableForwarding` 講不清楚。

### 【4】★★★★ 套用前的三道檢查

```bash
# ① 語法檢查（沒有輸出 + 回傳 0 才算過）
$ sudo sshd -t; echo $?
0

# ② ★★★★★ 確認【管理員自己】沒有被 Match 吃進去
$ sudo sshd -T -C user=admin,host=localhost,addr=127.0.0.1 | grep -iE 'chroot|forcecommand|permittty'
permittty yes
forcecommand none        # ★★★★★ 管理員必須是 none；這裡若出現 chrootdirectory【現在就停手】

# ③ 確認【受限帳號】確實被命中
$ sudo sshd -T -C user=vendor01,host=localhost,addr=127.0.0.1 \
    | grep -iE 'chrootdirectory|forcecommand|allowtcp|permittty|authenticationmethods|authorizedkeysfile|permittunnel'
authorizedkeysfile /etc/ssh/authorized_keys/%u
authenticationmethods publickey
chrootdirectory /srv/sftp/vendor01        # ★★★★ %u 已經展開
forcecommand internal-sftp -u 0027 -l INFO
allowtcpforwarding no
permittty no
permittunnel no

# 套用
$ sudo systemctl restart ssh        # Ubuntu 24.04+：新連線立刻生效，既有連線不受影響
```

> [!tip] OpenSSH 9.3 起有 `sshd -G` ★★
> `sshd -G -C user=vendor01,host=localhost,addr=127.0.0.1` 做同樣的事，
> 但**不需要 root、也不讀私鑰**，適合寫進 CI。舊版（Ubuntu 22.04 的 8.9）只有 `-T`，要 `sudo`。
> **`-C` 的三個欄位建議都給**（`user`/`host`/`addr`），少給時涉及該欄位的條件會被跳過。

## 進階設定與調校

### ★★★★ 目錄結構設計：讓 Web 讀得到、廠商寫不壞

```text
/srv/sftp/vendor01/     root:root                0755  ← ChrootDirectory（使用者不可寫）
├── upload/             vendor01:sftp-vendor01   2770  ← 廠商往這裡丟（新檔 0640 + ACL www-data:r--）
├── download/           root:sftp-vendor01       0750  ← 我們放給廠商拿
└── dev/log             （選用）chroot 內的 syslog socket

★★★★ 三個設計理由：
 ① upload 與 download 分開 → 「誰能寫」一眼看得出來，稽核也好講
 ② upload 的 setgid（2770）→ 新檔案【繼承群組】sftp-vendor01；
    不然 umask 再對，群組也會變成使用者主群組，ACL 就掛不穩
 ③ ★★★★★ 整棵樹【不在 web root 底下】——
    要給 Web 用是讓 www-data 靠 ACL 讀，不是把目錄搬進 /var/www
```

```bash
$ sudo install -d -o vendor01 -g sftp-vendor01 -m 2770 /srv/sftp/vendor01/upload
$ sudo install -d -o root     -g sftp-vendor01 -m 0750 /srv/sftp/vendor01/download
$ sudo setfacl -m g:www-data:--x /srv/sftp/vendor01          # ★★★ 只給穿越，不給列目錄
$ sudo setfacl    -m g:www-data:r-x /srv/sftp/vendor01/upload   # 現有檔案
$ sudo setfacl -d -m g:www-data:r-x /srv/sftp/vendor01/upload   # ★★★★ -d ＝ default ACL，新檔案才會繼承

$ getfacl /srv/sftp/vendor01/upload
# owner: vendor01
# group: sftp-vendor01
# flags: -s-                        # ★★★ setgid 有掛上
group:www-data:r-x                  # ★★★★ Web 只有讀與穿越，沒有 w
default:group:www-data:r-x          # ★★★★ 新檔案自動套用
other::---
```

> [!warning] default ACL 與 umask 會互相影響 ★★★★
> 目錄有 default ACL 時，**新檔案權限不是單純由 `-u 0027` 決定**，
> 而是「default ACL 條目」與「建檔要求的模式」取交集。
> SFTP 建檔要求的是 `0666`（沒有 x），所以 `default:group:www-data:r-x`
> 落到**檔案**上會變成 `r--`（目錄才保留 `x`）—— 這正是我們要的。
> **不要用推的，實際上傳一個檔案再看**：
> ```bash
> getfacl /srv/sftp/vendor01/upload/t.xlsx | grep www-data
> # 預期：group:www-data:r--    ← ★★★★ 沒有 x 才對
> ```

### ★★★★★ authorized_keys 一定要放在 chroot 之外

chroot 根就是使用者的家目錄。把 `.ssh/` 放在裡面只有兩種結局：
**(a) 使用者擁有它** → 他可以自己新增金鑰、甚至寫 `command="/bin/bash"` 給自己開後門，
而你從外面完全看不出來；**(b) root 擁有它** → 可行，但很容易在某次「他說傳不上去」時被 `chown` 回去。
**★★★ sshd 讀 `authorized_keys` 是在 chroot 之前、用真實路徑**，所以直接放牢籠外最乾淨。

```bash
$ sudo tee /etc/ssh/authorized_keys/vendor01 >/dev/null <<'EOF'
restrict,expiry-time="20261126",from="203.0.113.0/24" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... vendor01@某某資訊
EOF
$ sudo chown root:root /etc/ssh/authorized_keys/vendor01 && sudo chmod 0644 $_
```

| 金鑰選項 | 作用 | 星級 |
| --- | --- | --- |
| `restrict` | 一次關掉所有轉發、pty 與 `~/.ssh/rc`，**未來新增的限制也自動包含** | ★★★★ |
| `expiry-time="20261126"` | 這天之後這把金鑰不再被接受（`YYYYMMDD` 或 `YYYYMMDDHHMM[SS]`，加 `Z` 表 UTC） | ★★★★ |
| `from="203.0.113.0/24"` | 限制來源網段，公鑰外洩也要從對的地方來 | ★★★ |
| `command="…"` | 強制指令（rrsync／單一指令帳號用） | ★★★★ |

> [!tip] 金鑰選項與 `Match` 兩邊都設**不是多餘** ★★★
> `Match` 是伺服器政策（管理員維護），金鑰選項跟著**那一把金鑰**走（換金鑰時一起換）。
> 任一邊被誤改，另一邊還擋著 —— 稽核也喜歡看到這種雙重控制。

### 另外三種型態怎麼做

```bash
# ═══ ★★★ rsync-only：備份主機來拉，只准讀不准刪 ═══
$ sudo tee /etc/ssh/authorized_keys/backup-puller >/dev/null <<'EOF'
restrict,expiry-time="20270101",command="/usr/bin/rrsync -ro /srv/backup/app01" ssh-ed25519 AAAA... backup@nas01
EOF

$ /usr/bin/rrsync -help
usage: rrsync [-ro | -wo] [-munge] [-no-del] [-no-lock] [-no-overwrite] [-help] DIR
  -ro            Allow only reading from the DIR. Implies -no-del and -no-lock.
  -wo            Allow only writing to the DIR.
  -no-del        Disable rsync's --delete* and --remove* options.   # ★★★★ 收檔一定加
  -no-overwrite  Prevent overwriting existing files by enforcing --ignore-existing
```

| 情境 | 建議選項 | 理由 |
| --- | --- | --- |
| **★★★★ 備份主機來拉** | `-ro` | 來源機不該被備份主機寫入；`-ro` 已隱含 `-no-del` |
| **★★★★ 廠商推檔進來** | `-wo -no-del -no-overwrite` | 只准新增，**不准覆寫或刪除既有檔案**（勒索軟體最愛覆寫） |
| **★★★ 雙向同步** | 不要用 rrsync | 沒辦法同時安全；拆成兩個帳號兩個目錄 |

> [!note] rrsync 自己的日誌 ★★★
> rrsync 只在 `~/rrsync.log` **這個檔案已經存在**時才會附加紀錄：
> `sudo -u backup-puller touch /home/backup-puller/rrsync.log`。
> 忘了建這個空檔就完全沒有操作紀錄 —— 稽核會問。同步策略見 [[02-rsync-同步與備份]]。

```bash
# ═══ ★★★★ 單一指令帳號 ═══
$ sudo tee /etc/ssh/authorized_keys/deploy-trigger >/dev/null <<'EOF'
restrict,expiry-time="20270101",from="10.20.0.5",command="/usr/local/bin/deploy-hook" ssh-ed25519 AAAA... ci@gitlab
EOF
```

```bash
# /usr/local/bin/deploy-hook
#!/usr/bin/env bash
set -euo pipefail
# ★★★★★ 絕對不要這樣寫：
#   eval "$SSH_ORIGINAL_COMMAND"                     ← 等於把 shell 送給對方
#   /usr/local/bin/deploy "$SSH_ORIGINAL_COMMAND"    ← 參數注入
# ★★★★ 正確做法：把使用者輸入當【選單索引】，不是當指令
case "${SSH_ORIGINAL_COMMAND:-}" in
  "deploy web") exec /usr/local/bin/deploy-web ;;
  "deploy api") exec /usr/local/bin/deploy-api ;;
  "status")     exec systemctl --no-pager status app.service ;;
  *) echo "不允許的指令：${SSH_ORIGINAL_COMMAND:-<空>}" >&2
     logger -t deploy-hook "rejected: ${SSH_ORIGINAL_COMMAND:-<空>} from ${SSH_CLIENT%% *}"
     exit 2 ;;
esac
```

```bash
$ ssh -i ~/.ssh/ci deploy-trigger@srv01 'rm -rf /'
不允許的指令：rm -rf /            # ★★★★ 白名單擋下，伺服器端還留了 logger 紀錄

# ═══ ★★★ git-shell 帳號 ═══
$ sudo useradd -m -d /srv/git -s /usr/bin/git-shell gituser
$ grep gituser /etc/passwd
gituser:x:1005:1005::/srv/git:/usr/bin/git-shell     # ★★★ shell 本身就是限制
```

> [!danger] git-shell 的兩個地雷 ★★★★★
> ① **能 push 就可能能執行程式碼** —— repo 的 `hooks/` 由**伺服器**執行，
> 一定要 root 擁有且使用者不可寫：
> `sudo chown -R root:root /srv/git/app.git/hooks`
> ② **`~/git-shell-commands/` 若使用者可寫，等於給了 shell** ——
> git-shell 會執行那個目錄裡的任何檔案。不需要自訂指令時**根本不要建這個目錄**。

### ★★★★ 帳號生命週期治理

| 申請單欄位 | 為什麼要問 | 星級 |
| --- | --- | --- |
| 用途（一句話） | 三年後才知道這帳號在幹嘛 | ★★★ |
| **資料類型：是否含個資／機敏** | 決定保存期限、能不能給 Web 讀、要不要加密 | ★★★★★ |
| 廠商名稱、窗口姓名、電話、Email | 出事找得到人；離職要換金鑰 | ★★★★ |
| 來源 IP 或網段、公鑰指紋（SHA256） | 寫進 `from=` 把攻擊面縮到一條線；指紋是交付憑據 | ★★★★ |
| 方向：上傳／下載／雙向 | 決定 `upload/` 與 `download/` 的權限 | ★★★ |
| **到期日** | **沒有到期日的廠商帳號＝永久後門** | ★★★★★ |
| 資料保存期限與刪除方式 | 個資法與檔案保存年限要求 | ★★★★ |
| 核准人 | 稽核要看誰批准的 | ★★★★ |

```bash
# ★★★★ 到期日雙保險：帳號層 + 金鑰層
$ sudo chage -E 2026-11-26 vendor01
$ sudo chage -l vendor01 | grep 'Account expires'
Account expires                         : Nov 26, 2026        # ★★★★ 第一道（shadow / PAM）
$ sudo grep -o 'expiry-time="[0-9]*"' /etc/ssh/authorized_keys/vendor01
expiry-time="20261126"                                        # ★★★★ 第二道（sshd 驗金鑰時自己檢查）
```

兩道走的是**完全不同的檢查路徑**：`chage -E` 是 shadow／PAM 的帳號到期檢查，
生效與否受 `UsePAM` 等設定影響；`expiry-time` 由 sshd 在驗金鑰時檢查，不經過 PAM。
實務價值是**防呆** —— 換金鑰時工程師常複製舊的一行卻忘了改日期，這時另一道還擋著。
★★★ 客戶端**兩種情況都是** `Permission denied (publickey).`，要靠伺服器日誌分辨（排查步驟【5】）。

```bash
# ★★★★ 每季到期清查：對照申請單，沒人認領的一律停用
$ for u in $(getent group sftpusers | cut -d: -f4 | tr ',' ' '); do
    exp=$(chage -l "$u" 2>/dev/null | awk -F': ' '/Account expires/{print $2}')
    key=$(grep -ho 'expiry-time="[0-9]*"' /etc/ssh/authorized_keys/"$u" 2>/dev/null)
    printf '%-14s 帳號到期:%-14s 金鑰:%s\n' "$u" "${exp:-未設定}" "${key:-未設定}"
  done
vendor01       帳號到期:Nov 26, 2026  金鑰:expiry-time="20261126"
vendor02       帳號到期:never         金鑰:未設定          # ★★★★★ 這種就是要處理的
backup-puller  帳號到期:Jan 01, 2027  金鑰:expiry-time="20270101"
```

> [!danger] ★★★★★ 停用不是 `usermod -L`
> `usermod -L` 只是在密碼雜湊前加一個 `!`。**受限帳號根本沒有密碼**，走的是公鑰 ——
> 鎖了等於沒鎖，廠商照樣連得進來。這是稽核最愛抓的假停用。
> **真正的停用四件事一起做**：
> ```bash
> sudo usermod --expiredate 1 vendor01          # 帳號立刻過期
> sudo gpasswd -d vendor01 sftpusers            # 移出群組，Match 不再命中
> sudo mv /etc/ssh/authorized_keys/vendor01 \
>         /etc/ssh/authorized_keys/vendor01.disabled-$(date +%F)
> sudo pkill -u vendor01 || true                # 踢掉還開著的連線
> ```
> **不要直接 `userdel`**：檔案會變成孤兒 UID，稽核對不回人；
> UID 被新帳號重用時舊檔案會「變成」新帳號的；保存期限也還沒到。

```bash
# ★★★ 刪除資料前一定要留下「誰、何時、刪了什麼、依據什麼、誰核准」
$ sudo tee -a /var/log/sftp-retention.log >/dev/null <<EOF
$(date '+%F %T') DELETE user=vendor01 path=/srv/intake/vendor01/2025-* \
 files=$(find /srv/intake/vendor01/2025-* -type f | wc -l) \
 reason="保存期限屆滿(2年)" approver="資訊室 李課長" operator="$(logname)"
EOF
$ sudo find /srv/intake/vendor01/2025-* -type f -delete   # ★★★ 先寫紀錄再刪
```

> [!warning] `shred` 在有快照／備份的環境是自我安慰 ★★★★
> `shred -u` 只覆寫**這個檔案系統上的區塊**。資料在 LVM 快照、ZFS/Btrfs snapshot、
> 每日備份或物件儲存裡各有一份時，**刪本地那份等於沒刪**。
> 含個資的資料要刪，**備份鏈也要一起走流程**並寫進紀錄
> （見 [[03-備份策略與還原演練]]、[[07-台灣資安法規與個資法]]）。

### ★★★★ 稽核：把 SFTP 日誌分流出來

**★★★★ 第一個坑：chroot 裡沒有 `/dev/log`。**
`internal-sftp` 的日誌是透過 syslog socket 送出去的，chroot 之後那個路徑變成
`/srv/sftp/vendor01/dev/log`，不存在 → **一行日誌都不會有，而且沒有任何錯誤提示**。
你會以為「`-l INFO` 沒作用」，其實是訊息掉在牢籠裡出不來。

```bash
$ sudo tee /etc/rsyslog.d/49-sftp.conf >/dev/null <<'EOF'
module(load="imuxsock")
# ★★★★ 在每個 chroot 內開一個 syslog socket
input(type="imuxsock" Socket="/srv/sftp/vendor01/dev/log" CreatePath="on")
# ★★★★ 分流到獨立檔案並 stop（不要再進 auth.log）
if $programname == 'internal-sftp' then {
    action(type="omfile" file="/var/log/sftp.log"
           fileCreateMode="0640" fileOwner="syslog" fileGroup="adm")
    stop
}
EOF
$ sudo systemctl restart rsyslog
$ sudo ls -l /srv/sftp/vendor01/dev/log
srw-rw-rw- 1 root root 0 Aug 28 09:02 /srv/sftp/vendor01/dev/log   # ★★★ s 開頭＝socket
```

> [!warning] 三個要記得的限制 ★★★
> ① 檔名數字要**小於** `50-default.conf`，否則 `auth.log` 也會收到一份（`stop` 來不及）。
> ② rsyslog 的 imuxsock **socket 數量有編譯期上限（預設 50）**，帳號多要改用共用 socket 的做法。
> ③ 每新增一個帳號就要多一行 `input(...)` **並重載 rsyslog** —— 這一步要寫進建立腳本，
> 不然新帳號永遠沒日誌。沒有 rsyslog、只有 journald 的機器，
> 則是把 `/run/systemd/journal/dev-log` **bind mount** 進 chroot（用 `.mount` unit）。
>
> > [!warning] 未實機驗證
> > bind mount syslog socket 的做法未在本手冊環境驗證，
> > 套用後務必實際上傳一個檔案並確認 `journalctl -t internal-sftp` 真的有紀錄。

```bash
$ sudo tail -4 /var/log/sftp.log
Aug 28 18:05:11 srv01 internal-sftp[12345]: session opened for local user vendor01 from [203.0.113.45]
Aug 28 18:05:20 srv01 internal-sftp[12345]: open "/upload/2026-08-statistics.xlsx" flags WRITE,CREATE,TRUNCATE mode 0666
Aug 28 18:05:21 srv01 internal-sftp[12345]: close "/upload/2026-08-statistics.xlsx" bytes read 0 written 482104
Aug 28 18:06:02 srv01 internal-sftp[12345]: session closed for local user vendor01 from [203.0.113.45]
```

| 欄位 | 意義 | 稽核用途 |
| --- | --- | --- |
| `internal-sftp[12345]` | **★★★★ PID 是同一 session 的關聯鍵** | 把 `open`／`close` 對回「哪個帳號、從哪個 IP」 |
| `session opened … from [IP]` | 誰、從哪連進來 | 存取紀錄的「人」與「來源」 |
| `open "路徑" flags WRITE,CREATE,TRUNCATE` | 開檔意圖 | **★★★ `TRUNCATE` 代表覆寫既有檔案** |
| `close "路徑" bytes read R written W` | **★★★★ 傳輸完成與大小** | `written>0` ＝上傳、`read>0` ＝下載 |
| 有 `open` 卻沒有 `close` | 傳到一半斷線 | 對帳差異的第一嫌疑 |

```bash
$ sudo tee /etc/logrotate.d/sftp >/dev/null <<'EOF'
/var/log/sftp.log {
    daily
    rotate 400            # ★★★★ 由稽核保存期限決定，不是預設的 4 週
    missingok
    notifempty
    compress
    create 0640 syslog adm
    sharedscripts
    postrotate
        /usr/lib/rsyslog/rsyslog-rotate     # ★★ Ubuntu 的 rsyslog 重載腳本
    endscript
}
EOF
$ sudo logrotate -d /etc/logrotate.d/sftp | grep rotating
rotating pattern: /var/log/sftp.log  after 1 days (400 rotations)   # ★★★ 確認保留天數
```

集中與長期保存見 [[02-日誌集中與輪替]]，稽核軌跡的要求見 [[09-資安稽核與符合性檢核]]。

### ★★★ 配額與濫用防護

```bash
# ★★★★ XFS project quota：算的是【目錄】，最適合 chroot（fstab 要有 prjquota）
$ echo '101:/srv/sftp/vendor01' | sudo tee -a /etc/projects
$ echo 'sftp-vendor01:101'      | sudo tee -a /etc/projid
$ sudo xfs_quota -x -c 'project -s sftp-vendor01' /srv
$ sudo xfs_quota -x -c 'limit -p bsoft=4g bhard=5g sftp-vendor01' /srv
$ sudo xfs_quota -x -c 'report -p -h' /srv
Project ID     Used   Soft   Hard Warn/Grace
sftp-vendor01  126M     4G     5G  00 [------]     # ★★★★ 換帳號也不用重設
```

> [!info]- ext4 的做法（依【使用者】計）★★★
> ```bash
> sudo apt install -y quota                             # fstab 加 usrquota,grpquota 後 remount
> sudo quotacheck -cum /srv && sudo quotaon -v /srv
> sudo setquota -u vendor01 4194304 5242880 0 0 /srv    # soft 4G / hard 5G（單位 KB）
> sudo repquota -s /srv
> ```
> ★★★ **配額是整個檔案系統的**，所以 `/srv` 最好是獨立分割區（見 [[04-檔案系統與目錄結構]]）；
> 超過 hard limit 時客戶端只會看到一個沒頭沒尾的 `Failure`。

| 手法 | 適用 | 星級 |
| --- | --- | --- |
| XFS project quota | chroot 目錄、共用 UID 的情境 | ★★★★ |
| ext4 user quota | 一人一帳號一目錄，且 `/srv` 獨立分割 | ★★★ |
| `du` 門檻告警 | 沒有配額時的最低限度（擋不住，但會知道） | ★★★ |
| **上傳後即搬走** | 交檔型情境的**根本解**：讓 `upload/` 永遠幾乎是空的 | ★★★★ |

### 不用 chroot 的替代方案

| 方案 | 怎麼做 | 取捨 |
| --- | --- | --- |
| **★★★ bind mount 每帳號目錄** | 資料放 `/data/vendor01`，`mount --bind` 到 `upload/` | 資料與牢籠分離、備份好做；但**忘了掛載時上傳會寫進空目錄**（★★★★ intake 腳本要先 `mountpoint -q` 檢查） |
| **★★★ 容器化 SFTP** | 每個廠商一個容器，資料走 volume | 影響面小、可拋棄；但同一套權限設計還是要做，日誌要另外收，**★★★ 容器 ≠ 沙箱** |
| **★★ 檔案交換平台** | 有帳號管理與稽核介面的既成產品 | 申請／到期／稽核有介面、非資訊人員能自助；但多一套系統與授權費，**★★★ 仍要確認儲存目錄不在 web root** |
| **★★ 只開 download** | 廠商只能拿，交檔改走別的管道 | 攻擊面最小，但業務流程要配合 |

## 完整實戰範例

> **情境**：機關委外廠商「某某資訊」每月 5 日前上傳統計報表（xlsx／csv），
> 由內部 Laravel 系統讀取後匯入。要求：公鑰認證、**有效期 90 天**、
> chroot 在 `/srv/sftp/vendor01`、upload 讓 `www-data` **讀得到但寫不進去**、
> Web 路徑**不解析**上傳檔、每日掃毒並搬到處理區、每月產出可交稽核的月報。

### 【1】建立腳本 `/usr/local/bin/create-restricted-user`

```bash
#!/usr/bin/env bash
# /usr/local/bin/create-restricted-user
# 建立三種受限帳號：sftp（chroot 交檔）／rsync（rrsync）／command（單一指令）
set -euo pipefail
umask 022

SFTP_ROOT=/srv/sftp                 # chroot 家族的根
KEY_DIR=/etc/ssh/authorized_keys    # ★★★★★ 金鑰放 chroot 外，使用者改不到
SFTP_GROUP=sftpusers                # sshd Match 條件用的群組
WEB_GROUP=www-data                  # 需要讀上傳檔的服務群組
DRY_RUN=0

die()  { printf '[FAIL] %s\n' "$*" >&2; exit 1; }
ok()   { printf '[ OK ] %s\n' "$*"; }
step() { printf '\n=== %s ===\n' "$*"; }
run()  { if [ "$DRY_RUN" = 1 ]; then printf '       (dry-run) %s\n' "$*"; else "$@"; fi; }
usage() { sed -n '2,4p' "$0"; cat <<'U'
用法： create-restricted-user --user <帳號> --type sftp|rsync|command --key <公鑰檔>
       --expire <YYYY-MM-DD> [--owner 窗口] [--ticket 單號] [--from IP/CIDR]
       [--dir 目錄] [--command 指令] [--dry-run]
U
}

USER_NAME=""; TYPE=""; KEY_FILE=""; EXPIRE=""; OWNER=""; TICKET=""
FROM=""; TARGET_DIR=""; FORCED_CMD=""
while [ $# -gt 0 ]; do
  case "$1" in
    --user)    USER_NAME="${2:?--user 要給值}"; shift 2 ;;
    --type)    TYPE="${2:?--type 要給值}";      shift 2 ;;
    --key)     KEY_FILE="${2:?--key 要給值}";   shift 2 ;;
    --expire)  EXPIRE="${2:?--expire 要給值}";  shift 2 ;;
    --owner)   OWNER="${2:-}";      shift 2 ;;
    --ticket)  TICKET="${2:-}";     shift 2 ;;
    --from)    FROM="${2:-}";       shift 2 ;;
    --dir)     TARGET_DIR="${2:-}"; shift 2 ;;
    --command) FORCED_CMD="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1;           shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage; die "未知參數：$1" ;;
  esac
done

step "【0】參數檢查"
[ -n "$USER_NAME" ] || { usage; die "缺少 --user"; }
[ -n "$TYPE" ]      || { usage; die "缺少 --type"; }
[ -n "$KEY_FILE" ]  || { usage; die "缺少 --key（受限帳號一律公鑰認證，不給密碼）"; }
[ -n "$EXPIRE" ]    || { usage; die "缺少 --expire（沒有到期日的廠商帳號＝永久後門）"; }
printf '%s' "$USER_NAME" | grep -qE '^[a-z][a-z0-9_-]{2,31}$' \
  || die "帳號名稱只能小寫字母開頭、3~32 字元：$USER_NAME"
case "$TYPE" in sftp|rsync|command) ;; *) die "--type 只能是 sftp / rsync / command" ;; esac
[ -r "$KEY_FILE" ] || die "讀不到公鑰檔：$KEY_FILE"
ssh-keygen -l -f "$KEY_FILE" >/dev/null 2>&1 || die "$KEY_FILE 不是合法的公鑰檔"
date -d "$EXPIRE" +%Y-%m-%d >/dev/null 2>&1 || die "--expire 格式要是 YYYY-MM-DD：$EXPIRE"
[ "$(date -d "$EXPIRE" +%s)" -gt "$(date +%s)" ] || die "--expire 不能是過去的日期"
[ "$TYPE" != command ] || [ -n "$FORCED_CMD" ] || die "--type command 必須給 --command"
[ "$DRY_RUN" = 1 ] || [ "$(id -u)" = 0 ] || die "請用 sudo 執行"
id "$USER_NAME" >/dev/null 2>&1 && die "帳號已存在：$USER_NAME（改設定請走變更流程，不要重建）"

KEY_FP="$(ssh-keygen -l -f "$KEY_FILE" | awk '{print $2}')"
EXPIRE_KEY="$(date -d "$EXPIRE" +%Y%m%d)"      # authorized_keys 的 expiry-time 格式
ok "帳號=$USER_NAME 型態=$TYPE 到期=$EXPIRE 指紋=$KEY_FP"

step "【1】建立群組與帳號"
getent group "$SFTP_GROUP" >/dev/null || run groupadd "$SFTP_GROUP"
run groupadd -f "sftp-$USER_NAME"              # ★★★ 專屬群組，給 Web 掛 ACL 用
case "$TYPE" in
  sftp)
    run useradd --no-create-home --home-dir "$SFTP_ROOT/$USER_NAME" \
        --shell /usr/sbin/nologin --gid "sftp-$USER_NAME" \
        --groups "$SFTP_GROUP" --comment "$OWNER/$TICKET" "$USER_NAME" ;;
  rsync|command)
    # ★★★ 這兩種靠 authorized_keys 的 command= 限制，需要能執行的 shell
    run useradd --create-home --home-dir "/home/$USER_NAME" \
        --shell /bin/bash --gid "sftp-$USER_NAME" \
        --comment "$OWNER/$TICKET" "$USER_NAME" ;;
esac
run passwd -l "$USER_NAME"                     # ★★★ 不設密碼
ok "帳號建立完成"

step "【2】有效期雙保險"
run chage -E "$EXPIRE" -I 0 -m 0 -M 99999 "$USER_NAME"    # ★★★★ 第一道：帳號層
ok "chage -E $EXPIRE"

step "【3】目錄骨架與權限"
if [ "$TYPE" = sftp ]; then
  run install -d -o root -g root -m 0755 "$SFTP_ROOT"
  run install -d -o root -g root -m 0755 "$SFTP_ROOT/$USER_NAME"   # ★★★★ chroot 根歸 root
  run install -d -o "$USER_NAME" -g "sftp-$USER_NAME" -m 2770 "$SFTP_ROOT/$USER_NAME/upload"
  run install -d -o root -g "sftp-$USER_NAME" -m 0750 "$SFTP_ROOT/$USER_NAME/download"
  if getent group "$WEB_GROUP" >/dev/null; then
    run setfacl -m    "g:$WEB_GROUP:r-x" "$SFTP_ROOT/$USER_NAME/upload"
    run setfacl -d -m "g:$WEB_GROUP:r-x" "$SFTP_ROOT/$USER_NAME/upload"  # ★★★★ 新檔案自動可讀
    run setfacl -m    "g:$WEB_GROUP:--x" "$SFTP_ROOT/$USER_NAME"         # 只給穿越
  fi
else
  TARGET_DIR="${TARGET_DIR:-/srv/backup/$USER_NAME}"
  run install -d -o "$USER_NAME" -g "sftp-$USER_NAME" -m 0750 "$TARGET_DIR"
fi
ok "目錄骨架完成"

step "【4】寫入 authorized_keys（chroot 之外）"
run install -d -o root -g root -m 0755 "$KEY_DIR"
KEY_BODY="$(grep -vE '^\s*(#|$)' "$KEY_FILE" | head -n1)"
[ -n "$KEY_BODY" ] || die "公鑰檔內容是空的"
OPTS="restrict,expiry-time=\"$EXPIRE_KEY\""                 # ★★★★ 第二道：金鑰層
[ -z "$FROM" ] || OPTS="$OPTS,from=\"$FROM\""               # ★★★ 綁來源網段
case "$TYPE" in
  rsync)   OPTS="$OPTS,command=\"/usr/bin/rrsync -wo -no-del $TARGET_DIR\"" ;;
  command) OPTS="$OPTS,command=\"$FORCED_CMD\"" ;;
esac
if [ "$DRY_RUN" = 1 ]; then
  printf '       (dry-run) 寫入 %s/%s：\n         %s %s\n' "$KEY_DIR" "$USER_NAME" "$OPTS" "${KEY_BODY:0:40}..."
else
  printf '%s %s\n' "$OPTS" "$KEY_BODY" > "$KEY_DIR/$USER_NAME"
  chown root:root "$KEY_DIR/$USER_NAME"; chmod 0644 "$KEY_DIR/$USER_NAME"
fi
ok "authorized_keys 由 root 擁有，使用者改不到"

step "【5】設定檢查"
if sshd -G -C "user=$USER_NAME,host=localhost,addr=127.0.0.1" >/dev/null 2>&1; then
  SSHD_DUMP="sshd -G -C"; else SSHD_DUMP="sshd -T -C"; fi
run sshd -t || die "sshd 設定語法錯誤，請先修好再繼續"
if [ "$DRY_RUN" = 0 ]; then
  $SSHD_DUMP "user=$USER_NAME,host=localhost,addr=127.0.0.1" \
    | grep -iE '^(chrootdirectory|forcecommand|allowtcpforwarding|permittty|authenticationmethods|authorizedkeysfile|permittunnel)' \
    || die "Match 區塊沒有套用到 $USER_NAME，請檢查群組與 sshd_config"
fi
ok "sshd 設定檢查通過"

cat <<EOF
 帳號 $USER_NAME ($TYPE)  到期 $EXPIRE  指紋 $KEY_FP
 申請單 ${TICKET:-未填}   窗口 ${OWNER:-未填}
 驗收：sudo $SSHD_DUMP user=$USER_NAME,... | grep -i chroot；namei -l $SFTP_ROOT/$USER_NAME
 回滾（停用不刪除）：usermod --expiredate 1 $USER_NAME；gpasswd -d $USER_NAME $SFTP_GROUP；
       mv $KEY_DIR/$USER_NAME $KEY_DIR/$USER_NAME.disabled-\$(date +%F)
EOF
logger -t create-restricted-user "created $USER_NAME type=$TYPE expire=$EXPIRE fp=$KEY_FP ticket=${TICKET:-none}" || true
```

```bash
$ sudo install -m 0750 create-restricted-user.sh /usr/local/bin/create-restricted-user
$ sudo create-restricted-user --user vendor01 --type sftp --key /tmp/vendor01.pub \
    --expire "$(date -d '+90 days' +%F)" --owner "某某資訊 王小明" \
    --ticket SR-2026-0812 --from 203.0.113.0/24 --dry-run
=== 【0】參數檢查 ===
[ OK ] 帳號=vendor01 型態=sftp 到期=2026-11-26 指紋=SHA256:ATETBhluls0SVFL6W66q9NHVvD8gDaTKPNGsTRwI9wE
=== 【3】目錄骨架與權限 ===
       (dry-run) install -d -o root -g root -m 0755 /srv/sftp/vendor01
       (dry-run) install -d -o vendor01 -g sftp-vendor01 -m 2770 /srv/sftp/vendor01/upload
       (dry-run) setfacl -d -m g:www-data:r-x /srv/sftp/vendor01/upload
[ OK ] sshd 設定檢查通過
```

**★★★★ `--dry-run` 看過一遍沒問題，再拿掉 `--dry-run` 真的執行。**

### 【2】★★★★★ Web 端：讓上傳的檔案絕對不會被執行

```nginx
server {
    root /var/www/app/public;      # ★★★★★ web root 與 /srv/sftp 完全不重疊

    # ★★★★ 要讓人下載廠商上傳的檔案時，用 ^~ 前綴 location：
    #   ^~ 會【阻止後面的正規表示式 location 被比對】
    #   → /files/evil.php 不會掉進 location ~ \.php$ 的 fastcgi_pass
    location ^~ /files/ {
        alias /srv/sftp/vendor01/upload/;
        autoindex off;
        add_header Content-Disposition "attachment" always;   # ★★★ 一律下載，不在瀏覽器裡跑
        add_header X-Content-Type-Options nosniff always;
        types { }                                             # ★★★ 不做 MIME 推測
        default_type application/octet-stream;
        location ~* \.(php|phtml|phar|cgi|pl|py|sh|html?|svg)$ { return 403; }   # ★★★★ 雙保險
    }

    location ~ \.php$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
    }
}
```

```bash
# ★★★★★ 驗證：上傳一個 .php 檔，確認它【不會被執行】
$ echo '<?php echo "PWNED"; ?>' > /tmp/t.php
$ sftp -i ~/.ssh/vendor01 vendor01@srv01 <<'EOF'
cd upload
put /tmp/t.php
EOF
$ curl -s -o /dev/null -w '%{http_code}\n' https://app.example.gov.tw/files/t.php
403      # ★★★★★ 403 或 404 才對。看到 200 且內容是 PWNED → 立刻停用帳號並當資安事件處理
```

> [!danger] 這是本篇最高等級的紅線 ★★★★★
> 「上傳目錄在 web root 底下」＋「該路徑會被 PHP／CGI 解析」
> ＝ **你發給廠商的不是傳檔帳號，是一個遠端程式碼執行入口**。
> 廠商筆電中毒、金鑰外流、委外人員離職沒交還金鑰，任一項成立就是完整入侵。
> Nginx 加固細節見 [[09-Nginx-安全設定]]。

### 【3】每日 intake：掃毒、搬檔、告警

```bash
#!/usr/bin/env bash
# /usr/local/bin/sftp-intake —— 掃毒、搬檔到處理區、容量告警、通報
set -euo pipefail
SFTP_ROOT="${SFTP_ROOT:-/srv/sftp}"
INTAKE="${INTAKE:-/srv/intake}"           # ★★★★ 處理區，不在 web root 底下
QUARANTINE="${QUARANTINE:-/srv/quarantine}"
LOG="${INTAKE_LOG:-/var/log/sftp-intake.log}"
QUOTA_WARN_MB="${QUOTA_WARN_MB:-4096}"
STABLE_MIN="${STABLE_MIN:-5}"             # ★★★★ N 分鐘內沒被改過才算「傳完」
MAIL_TO="${MAIL_TO:-ops@example.gov.tw}"
TODAY="$(date +%F)"
moved=0; infected=0; warned=0; scan_err=0

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG"; }
scan_one() {   # 回傳 0=乾淨 1=有毒 2=掃不動
  local f="$1"
  if command -v clamdscan >/dev/null; then
    clamdscan --fdpass --no-summary -- "$f" >/dev/null 2>&1; return $?
  elif command -v clamscan >/dev/null; then
    clamscan --no-summary -- "$f" >/dev/null 2>&1; return $?
  else return 2; fi
}
safe_name() { printf '%s' "${1##*/}" | tr -c 'A-Za-z0-9._-' '_'; }   # ★★★★ 檔名消毒

for updir in "$SFTP_ROOT"/*/upload; do
  [ -d "$updir" ] || continue
  user="$(basename "$(dirname "$updir")")"
  dest="$INTAKE/$user/$TODAY"
  install -d -m 0750 "$dest"; chgrp "sftp-$user" "$dest" 2>/dev/null || true

  while IFS= read -r -d '' f; do
    name="$(safe_name "$f")"
    # ★★★★★ 絕對不要對上傳的檔案做 source / bash / eval，這裡只搬移，不執行
    set +e; scan_one "$f"; rc=$?; set -e
    case "$rc" in
      0)  install -m 0640 -- "$f" "$dest/$name"
          chgrp "sftp-$user" "$dest/$name" 2>/dev/null || true
          rm -f -- "$f"; moved=$((moved + 1))
          log "MOVED user=$user file=$name size=$(stat -c%s "$dest/$name")" ;;
      1)  install -d -m 0700 "$QUARANTINE/$user"
          install -m 0600 -- "$f" "$QUARANTINE/$user/$TODAY-$name"
          rm -f -- "$f"; infected=$((infected + 1))
          log "QUARANTINE user=$user file=$name（clamav 判定為惡意）" ;;
      *)  scan_err=$((scan_err + 1))
          log "SCAN-ERROR user=$user file=$name rc=$rc（★★★ 檔案留在原地，不放行也不刪除）" ;;
    esac
  done < <(find "$updir" -type f -mmin +"$STABLE_MIN" -print0)

  used_mb=$(du -sm "$SFTP_ROOT/$user" | cut -f1)
  if [ "$used_mb" -ge "$QUOTA_WARN_MB" ]; then
    warned=$((warned+1)); log "QUOTA user=$user used=${used_mb}MB threshold=${QUOTA_WARN_MB}MB"
  fi
done

log "SUMMARY moved=$moved infected=$infected scan_err=$scan_err quota_warn=$warned"
if [ "$infected" -gt 0 ] || [ "$warned" -gt 0 ] || [ "$scan_err" -gt 0 ]; then
  command -v mail >/dev/null && tail -n 50 "$LOG" \
    | mail -s "[SFTP intake] 毒=$infected 掃描失敗=$scan_err 容量=$warned $(hostname -s)" "$MAIL_TO"
  exit 1      # ★★★ 非 0 讓 systemd 記成 failed，監控才抓得到
fi
```

| 設計 | 為什麼 | 星級 |
| --- | --- | --- |
| `find -mmin +5` | **傳到一半的檔案不能搬**，否則廠商會得到「檔案不見了」 | ★★★★ |
| `find -print0` + `read -r -d ''` | 檔名含空白、分號、換行時不會被拆開或被當成指令 | ★★★★ |
| `safe_name()` | 奇怪字元換成 `_`，下游匯入程式才不會炸 | ★★★★ |
| 掃不動就**留在原地** | 病毒碼過期、clamd 沒跑時**不放行也不刪除**，並告警 | ★★★★ |

```ini
# /etc/systemd/system/sftp-intake.service   （unit 寫法見 [[01-systemd-unit撰寫實戰]]）
[Unit]
Description=SFTP 上傳檔案掃毒與搬移
After=clamav-daemon.service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/sftp-intake
PrivateTmp=true                 # ★★★ 這支腳本會碰到外部上傳的檔案，能關的都關掉
ProtectSystem=strict
ReadWritePaths=/srv/sftp /srv/intake /srv/quarantine /var/log
NoNewPrivileges=true

# /etc/systemd/system/sftp-intake.timer     （選型見 [[02-systemd-timer與cron選型]]）
[Unit]
Description=每日執行 SFTP intake
[Timer]
OnCalendar=*-*-* 02:30:00
RandomizedDelaySec=300
Persistent=true
[Install]
WantedBy=timers.target
```

```bash
$ sudo systemctl daemon-reload && sudo systemctl enable --now sftp-intake.timer
$ systemctl list-timers sftp-intake.timer
NEXT                        LEFT     LAST PASSED UNIT              ACTIVATES
Sat 2026-08-29 02:30:00 CST 7h left  -    -      sftp-intake.timer sftp-intake.service
```

### 【4】稽核月報 `/usr/local/bin/sftp-audit-report`

```bash
#!/usr/bin/env bash
# /usr/local/bin/sftp-audit-report —— 產生可交稽核的 SFTP 傳輸月報（CSV）
set -euo pipefail
MONTH="${1:-$(date -d 'last month' +%Y-%m)}"     # 預設上個月
LOG_GLOB="${SFTP_LOG:-/var/log/sftp.log}"
OUT="${2:-/var/log/sftp-audit/sftp-$MONTH.csv}"
YEAR="${MONTH%-*}"; MON="${MONTH#*-}"
MON_ABBR="$(LC_ALL=C date -d "$YEAR-$MON-01" +%b)"
install -d -o root -g adm -m 0750 "$(dirname "$OUT")"

# shellcheck disable=SC2086
zcat -f $LOG_GLOB* 2>/dev/null | awk -v year="$YEAR" -v mon="$MON_ABBR" -v monnum="$MON" '
  BEGIN { print "日期時間,帳號,來源IP,方向,檔案,位元組" }
  {   i = index($0, "internal-sftp[")               # ★★★★ PID 是 session 的關聯鍵
      if (i > 0) { pid = substr($0, i + 14); sub(/\].*/, "", pid) }
  }
  /session opened for local user/ {
      for (i = 1; i <= NF; i++) if ($i == "user") { user[pid] = $(i+1) }
      ip = $NF; gsub(/[\[\]]/, "", ip); addr[pid] = ip
  }
  /: close "/ {
      if ($1 != mon) next
      ts = sprintf("%s-%s-%02d %s", year, monnum, $2, $3)
      p = $0; sub(/^.*close "/, "", p); sub(/" bytes read.*/, "", p)
      r = $0; sub(/^.*bytes read /, "", r); sub(/ written.*/, "", r)
      w = $0; sub(/^.*written /, "", w)
      dir = (w + 0 > 0) ? "上傳" : "下載"            # ★★★ written>0 就是上傳
      bytes = (w + 0 > 0) ? w : r
      printf "%s,%s,%s,%s,\"%s\",%s\n", ts, (pid in user ? user[pid] : "unknown"), \
             (pid in addr ? addr[pid] : "unknown"), dir, p, bytes
  }' > "$OUT.tmp"

mv "$OUT.tmp" "$OUT"; chmod 0640 "$OUT"; chgrp adm "$OUT" 2>/dev/null || true
echo "月報：$OUT（$(( $(wc -l < "$OUT") - 1 )) 筆傳輸紀錄）"
```

```bash
$ sudo sftp-audit-report 2026-08
月報：/var/log/sftp-audit/sftp-2026-08.csv（3 筆傳輸紀錄）
$ sudo cat /var/log/sftp-audit/sftp-2026-08.csv
日期時間,帳號,來源IP,方向,檔案,位元組
2026-08-28 18:05:21,vendor01,203.0.113.45,上傳,"/upload/2026-08-statistics.xlsx",482104
2026-08-28 18:05:41,vendor01,203.0.113.45,下載,"/download/spec.pdf",91234
2026-08-29 09:11:30,vendor02,198.51.100.7,上傳,"/upload/rpt.csv",1048576
```

> [!tip] 月報要跟「檔案還在不在」對帳 ★★★
> 月報說 8/28 上傳了 `2026-08-statistics.xlsx`，`/srv/intake/vendor01/2026-08-28/` 就該有同名檔案。
> **對不起來的那幾筆**才是要追的：掃毒隔離了？被人手動刪了？還是傳輸中斷沒有 `close`？

### 【5】回滾

```bash
# ★★★★ 帳號出問題：停用，不要刪除
$ sudo usermod --expiredate 1 vendor01
$ sudo gpasswd -d vendor01 sftpusers
$ sudo mv /etc/ssh/authorized_keys/vendor01 /etc/ssh/authorized_keys/vendor01.disabled-$(date +%F)
$ sudo pkill -u vendor01 || true
# 資料依申請單上的保存期限留存，期限到再走「刪除紀錄」流程
$ sudo mv /srv/sftp/vendor01 /srv/sftp/.retired/vendor01-$(date +%F)

# ★★★ sshd 設定整個退掉
$ sudo rm /etc/ssh/sshd_config.d/60-sftp-restricted.conf
$ sudo sshd -t && sudo systemctl restart ssh
```

### ★★★★ 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 |
| --- | --- | --- | --- |
| 1 | **★★★★★ 管理員沒被關進去** | `sudo sshd -T -C user=admin,host=localhost,addr=127.0.0.1 \| grep -i chroot` | **沒有任何輸出** |
| 2 | ★★★★ Match 命中受限帳號 | `sudo sshd -T -C user=vendor01,… \| grep -i chrootdirectory` | `chrootdirectory /srv/sftp/vendor01` |
| 3 | ★★★★ chroot 路徑權限 | `namei -l /srv/sftp/vendor01` | 每層都 `root root`、group/other 無 `w` |
| 4 | ★★★★ 拿不到 shell | `ssh -i k vendor01@srv01 id` | **看不到 `uid=`**（連線卡住或直接關閉） |
| 5 | ★★★★★ 不能開隧道 | `ssh -i k -N -L 9000:127.0.0.1:22 …` 後 `curl localhost:9000` | `administratively prohibited: open failed` |
| 6 | ★★★★ 跳不出 chroot | `sftp> cd /etc` | `Couldn't canonicalize: No such file or directory` |
| 7 | ★★★★ 根目錄不可寫 | `sftp> put x.txt /x.txt` | `remote open("/x.txt"): Permission denied` |
| 8 | ★★★ upload 可寫 | `sftp> put x.txt /upload/x.txt` | `Uploading … 100%` |
| 9 | ★★★★ 上傳檔案權限 | `stat -c '%a %U:%G' …/upload/x.txt` | `640 vendor01:sftp-vendor01` |
| 10 | ★★★★ Web 讀得到 | `sudo -u www-data cat …/upload/x.txt` | 印出內容 |
| 11 | **★★★★★ Web 寫不進去** | `sudo -u www-data touch …/upload/y.txt` | `Permission denied` |
| 12 | **★★★★★ 上傳的 .php 不會被執行** | `curl -o /dev/null -w '%{http_code}' https://…/files/t.php` | `403` 或 `404`（**絕不能是 200**） |
| 13 | ★★★★ 改不到 authorized_keys | `sftp> ls -l /.ssh` | `No such file or directory` |
| 14 | ★★★★ 到期日雙保險 | `chage -l vendor01`；`grep expiry-time …/vendor01` | 兩者都有值且**日期一致** |
| 15 | ★★★★ 日誌有出來 | `sudo tail -3 /var/log/sftp.log` | 有 `open`／`close` 與 bytes |
| 16 | ★★★ 月報與 timer | `sudo sftp-audit-report $(date +%Y-%m)`；`systemctl list-timers sftp-intake.timer` | CSV 筆數合理、`NEXT` 有值且沒 failed |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **★★★★★ 管理員登入後被關進 `/srv/sftp/admin`，拿不到 shell** | `Match` 條件寫錯人，或 Match 之後又寫了「以為是全域」的設定 | 用逃生梯連線或主控台 → 刪掉 drop-in → `sshd -t` → 重啟；之後一律先 `sshd -T -C user=admin` 驗證 |
| **★★★★★ 上傳的 `.php` 被瀏覽器執行了** | 上傳目錄落在 web root 且被 `location ~ \.php$` 比對到 | 目錄移出 web root；`location ^~` + `return 403`；**當資安事件處理**（[[09-Nginx-安全設定]]） |
| **★★★★ `sftp` 一連上就 `Connection closed`** | chroot 路徑某一層被使用者或群組可寫 | `namei -l` 逐層檢查；`chown root:root` + `chmod 755`；日誌會有 `bad ownership or modes` |
| **★★★★ `subsystem request failed on channel 0`** | `Subsystem` 指到外部 `sftp-server`，chroot 裡沒有那支執行檔 | 改成 `Subsystem sftp internal-sftp` |
| **★★★★ 連得上但 `put` 一律 Permission denied** | 只有 chroot 根，沒有可寫子目錄（根**必須**不可寫） | 建 `upload/` 並 `chown vendor01:sftp-vendor01`、`chmod 2770` |
| **★★★★ `-l INFO` 設了卻沒有任何日誌** | chroot 裡沒有 `/dev/log`，syslog 訊息出不來 | rsyslog `input(type="imuxsock" Socket="…/dev/log" CreatePath="on")` |
| **★★★★ 帳號「停用」了廠商還連得進來** | 只做了 `usermod -L`（僅鎖密碼），公鑰不受影響 | `usermod --expiredate 1` + 移出群組 + 搬走 `authorized_keys` + `pkill -u` |
| **★★★★ 到期日到了卻沒失效** | 只設了 `chage -E` 或只設了 `expiry-time`，而那一道剛好沒生效 | 兩道都設、每季清查核對；把日期調成昨天實測一次 |
| **★★★★ www-data 讀不到新上傳的檔案（舊的可以）** | 只下了 `setfacl -m`，沒下 `-d`（default ACL） | 補 `setfacl -d -m g:www-data:r-x upload/`，並上傳一個檔案 `getfacl` 驗證 |
| **★★★ 上傳的檔案變成 0666 全世界可讀寫** | `ForceCommand` 少了 `-u 0027` | 補上；既有檔案 `find … -type f -exec chmod 0640 {} +` |
| **★★★ 檔案上傳到一半就被 intake 搬走** | 沒有等檔案穩定 | `find -mmin +5`；或要求廠商先傳 `.part` 再改名 |
| **★★★ 磁碟被單一廠商塞爆；新帳號沒有日誌** | 沒配額沒告警；rsyslog 的 `input()` 是逐帳號寫的，新增時忘了加 | XFS project quota + intake 的 `du` 門檻；把「加 input + 重載 rsyslog」寫進建立腳本 |

### 排查步驟

**【1】** 先確認是不是 Match 沒命中

```bash
$ sudo sshd -T -C user=vendor01,host=localhost,addr=127.0.0.1 | grep -iE 'chroot|forcecommand'
chrootdirectory /srv/sftp/vendor01
forcecommand internal-sftp -u 0027 -l INFO
```

- 輸出**空的**或 `forcecommand none` → 問題在 **Match 條件**（多半是帳號不在 `sftpusers`，用 `id` 確認）
- 看到 `chrootdirectory %u` **沒展開** → 你少帶了 `-C`，重來
- **管理員身上也看到 chroot → 立刻停手**，這是最嚴重的情況

**【2】** 看伺服器日誌，不要猜

```bash
$ sudo journalctl -u ssh -n 50 --no-pager | grep -i vendor01     # RHEL：tail /var/log/secure
```

| 看到這行 | 代表 | 下一步 |
| --- | --- | --- |
| `fatal: bad ownership or modes for chroot directory "…"` | **★★★★ 目錄或上層目錄權限** | 跳【3】 |
| `subsystem request for sftp failed, subsystem not found` | **★★★★ subsystem 設定** | 改用 `internal-sftp` |
| `Authentication refused: bad ownership or modes for file /etc/ssh/authorized_keys/vendor01` | **★★★ 金鑰檔權限** | `chown root:root` + `chmod 0644` |
| `pam_unix(sshd:account): account vendor01 has expired` | **★★★★ `chage -E` 生效了** | 預期行為，確認是否該續期 |
| `Connection closed by authenticating user vendor01` | 認證階段被拒 | 跳【5】 |

**【3】** 逐層檢查 chroot 路徑

```bash
$ namei -l /srv/sftp/vendor01/upload
 drwxr-xr-x root root     /
 drwxr-xr-x root root     srv
 drwxr-xr-x root root     sftp
 drwxr-xr-x root root     vendor01        # ★★★★ 到這行為止都要 root root、且沒有 group/other 的 w
 drwxrws--- vendor01 sftp-vendor01 upload
```

- 任何一層出現**非 root 擁有者**或 `drwxrwx…` → 就是它，`chown root:root` + `chmod 755`
- `vendor01` 那層擁有者是 `vendor01` → 多半是 `useradd --create-home` 造成的
- **不要先 `chmod 777`** —— 權限太寬 sshd 一樣拒絕，只會讓你更難查

**【4】** 確認拿不到 shell、也出不去

```bash
$ ssh -i ~/.ssh/vendor01 vendor01@srv01 id
（沒有 uid= 輸出，連線停住或直接關閉）      # ★★★★ 印出 uid=1002(vendor01) 就是出大事

$ sftp -i ~/.ssh/vendor01 vendor01@srv01
sftp> pwd
Remote working directory: /                 # ★★★ 這個 / 是 chroot 的根
sftp> cd /etc
Couldn't canonicalize: No such file or directory      # ★★★★ 出不去
```

**【5】** 分辨是「帳號到期」還是「金鑰到期」

```bash
$ sudo chage -l vendor01 | grep 'Account expires'
Account expires                         : Nov 26, 2026
$ sudo grep -o 'expiry-time="[0-9]*"' /etc/ssh/authorized_keys/vendor01
expiry-time="20261126"
$ date +%F
2026-11-27
```

- 客戶端**兩種情況都是** `Permission denied (publickey).` → 只能從伺服器端分辨
- 日誌有 `account has expired` → `chage -E` 擋的
- 日誌只有 `Authentication refused` / 找不到相符金鑰 → `expiry-time` 或 `from=` 擋的

**【6】** 驗證轉發真的被封死

```bash
$ ssh -i ~/.ssh/vendor01 -N -L 9000:127.0.0.1:22 vendor01@srv01 &
$ curl -sv telnet://127.0.0.1:9000
channel 3: open failed: administratively prohibited: open failed    # ★★★★ 這才對
```

**★★★ `ssh -L` 這一步本身不會報錯**（本機埠是客戶端自己綁的），
**要實際去連那個埠**才看得到伺服器拒絕。沒連過就說「有擋」是不算數的。

**【7】** 日誌沒出來時，確認 socket 與 `-l INFO`

```bash
$ sudo ls -l /srv/sftp/vendor01/dev/log
srw-rw-rw- 1 root root 0 Aug 28 09:02 /srv/sftp/vendor01/dev/log
$ sudo grep -c internal-sftp /var/log/sftp.log
42
```

- 沒有那個 socket → rsyslog 的 `input()` 沒設或沒重載
- socket 在但 `sftp.log` 是 0 → 用 `sshd -T -C` 確認 `forcecommand` 真的帶了 `-l INFO`

**【8】** 確認 Web 端的紅線

```bash
$ sudo -u www-data touch /srv/sftp/vendor01/upload/probe.txt
touch: cannot touch '…/probe.txt': Permission denied      # ★★★★★ 要看到這行
$ curl -s -o /dev/null -w '%{http_code}\n' https://app.example.gov.tw/files/t.php
403                                                       # ★★★★★ 不能是 200
```

## 安全性注意事項

> [!danger] 絕對不要做的事 ★★★★★
> - **不要把上傳目錄放在 web root 底下**，也不要用 symlink 連過去。一旦該路徑會被 PHP／CGI 解析，
>   廠商帳號就是**遠端程式碼執行入口**，從「傳檔權限」瞬間升級成「整台機器」。
> - **不要把 `authorized_keys` 放在使用者可寫的地方**。他可以自己加金鑰（你永遠不知道），
>   或加 `command="/bin/bash"` 把限制拆掉。
> - **不要讓受限帳號能寫到任何被 root 讀取或執行的路徑** —— `/etc/cron.d/`、systemd unit 目錄、
>   或**任何 root 排程腳本會去 `source` 的設定檔**。寫得進去就等於拿到 root。
> - **不要在處理腳本裡對上傳內容做 `eval` / `source` / `bash`**，包括「只是看一下檔頭」。
> - **不要用 `usermod -L` 當停用**。受限帳號沒有密碼，鎖密碼等於什麼都沒做。
> - **不要發沒有到期日的廠商帳號**。專案結案三年後那把金鑰還在誰的電腦裡，沒人說得出來。
> - **不要為了「廠商說傳不上去」就 `chmod 777`**。99% 是子目錄擁有者設錯，不是權限不夠。

### ★★★★★ 提權自檢清單（交件前逐項實測）

```bash
#!/usr/bin/env bash
# 受限帳號提權自檢：每一項都要看到「預期的失敗」
U=vendor01; KEY=~/.ssh/vendor01; H=srv01

echo "── ① 能不能拿到 shell（預期：沒有 uid= 輸出）"
ssh -i "$KEY" -o BatchMode=yes "$U@$H" id 2>&1 | head -2

echo "── ② 能不能開隧道（預期：administratively prohibited）"
ssh -i "$KEY" -o BatchMode=yes -N -L 9000:127.0.0.1:22 "$U@$H" & sleep 2
curl -s -m 3 telnet://127.0.0.1:9000 2>&1 | tail -2; kill %1 2>/dev/null

echo "── ③④ 看得到自己的 authorized_keys 嗎、跳得出 chroot 嗎"
#      （預期：No such file / Couldn't canonicalize）
sftp -i "$KEY" -b - "$U@$H" <<'EOF' 2>&1 | tail -4
ls -l /.ssh
cd /etc
EOF

echo "── ⑤ 能不能寫到 root 會執行的路徑（在伺服器上跑）"
sudo -u "$U" test -w /etc/cron.d          && echo "★★★★★ 危險：cron.d 可寫"
sudo -u "$U" test -w /etc/systemd/system  && echo "★★★★★ 危險：unit 目錄可寫"
sudo find /srv/sftp/$U -xdev -type d -perm -o+w -printf '★★★★ 其他人可寫：%p\n'

echo "── ⑥ 有沒有 root 排程會去讀寫這個目錄（人工判讀）"
sudo grep -rl "/srv/sftp" /etc/cron.d /etc/cron.* /etc/systemd/system 2>/dev/null
```

> [!warning] 第 ⑥ 項最容易被忽略 ★★★★★
> 只要有一支 **root 執行的排程**會去讀廠商上傳的目錄，那支腳本的品質就是你的資安邊界：
> 它有沒有 `eval`？有沒有 `for f in $(ls)`？有沒有把檔名塞進另一個指令？
> 有沒有直接 `unzip` 到別的目錄（zip slip）？
> 本篇的 `sftp-intake` 之所以只用 `install` / `rm` / `find -print0`，就是這個原因。

| 機關情境的要求 | 對應做法 | 星級 |
| --- | --- | --- |
| 個資檔案的存取軌跡 | `-l INFO` 日誌 + 月報 CSV，保存期限決定 `logrotate rotate` | ★★★★★ |
| 共用帳號零容忍 | 兩家廠商**不可以**共用一個帳號，否則稽核無法歸責 | ★★★★★ |
| 最小權限 | 一帳號一用途一目錄；`upload` 與 `download` 分開 | ★★★★ |
| 委外人員管理 | 申請單留窗口與核准人；離職／換人**換金鑰，不共用金鑰** | ★★★★ |
| 資料保存與銷毀 | 保存期限寫進申請單；刪除要有紀錄（誰、何時、依據、核准） | ★★★★ |
| 帳號定期盤點 | 每季跑清查腳本，對照申請單，沒人認領一律停用 | ★★★★ |
| 傳輸加密 | SFTP 走 SSH 已加密；演算法加固見 [[07-SSH-安全強化]] | ★★★ |

密碼與帳號政策通則見 [[02-密碼與帳號管理實務]]，主機層加固見 [[08-系統強化與稽核]]。

## 速查表

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `sudo sshd -t` | 語法檢查（**改完必跑**） | ★★★★ |
| `sudo sshd -T -C user=U,host=H,addr=A` | 印出**對某使用者生效**的完整設定 | ★★★★★ |
| `sshd -G -C user=U,…` | 同上但不需 root（OpenSSH 9.3+） | ★★★ |
| `namei -l /srv/sftp/U` | 一次看整條路徑的擁有者與權限 | ★★★★ |
| `getfacl 檔案或目錄` | 檢查 ACL 與 default ACL | ★★★★ |
| `chage -l U` / `getent group sftpusers` | 看到期日 / 列群組成員（清查用） | ★★★★ |
| `ssh-keygen -l -f key.pub` | 算公鑰指紋（交付對帳） | ★★★ |
| `systemd-run --on-active=5min --unit=X …` | 排自動回滾（改設定的保命符） | ★★★★ |

| sshd 設定項 | 值 | 星級 |
| --- | --- | --- |
| `Subsystem sftp` | `internal-sftp`（**chroot 唯一解**） | ★★★★ |
| `ChrootDirectory` | `/srv/sftp/%u`（可用 `%%` `%h` `%U` `%u`） | ★★★★ |
| `ForceCommand` | `internal-sftp -u 0027 -l INFO` | ★★★★ |
| `AuthorizedKeysFile` | `/etc/ssh/authorized_keys/%u`（牢籠外） | ★★★★★ |
| `AuthenticationMethods` | `publickey` | ★★★★ |
| `AllowTcpForwarding`／`PermitTunnel`／`PermitTTY`／`PermitUserRC` | 全部 `no` | ★★★★ |

| authorized_keys 選項 ／ 檔案路徑 | 效果 ／ 內容 | 星級 |
| --- | --- | --- |
| `restrict` | 關掉所有轉發、pty、`~/.ssh/rc`，含未來新增的限制 | ★★★★ |
| `expiry-time="YYYYMMDD"` ／ `from="203.0.113.0/24"` | 金鑰到期（可加 `HHMM[SS]`、`Z` 表 UTC）／ 限制來源 | ★★★★ |
| `command="/usr/bin/rrsync -ro /path"` | 強制指令 | ★★★★ |
| `/etc/ssh/sshd_config.d/60-sftp-restricted.conf` | Match 區塊（**放檔案最後面**） | ★★★★ |
| `/etc/ssh/authorized_keys/<帳號>` | 集中的公鑰，root:root 0644 | ★★★★★ |
| `/srv/sftp/<帳號>/` ／ `…/upload/` | chroot 根 root:root 0755 ／ 可寫 2770 | ★★★★ |
| `/var/log/sftp.log` ／ `/srv/intake/<帳號>/<日期>/` | 分流後的日誌 ／ 掃毒後的處理區 | ★★★★ |

| 判斷準則 | 答案 |
| --- | --- |
| 只交檔？ | **chroot SFTP** ★★★★ |
| 要增量同步？ | **rrsync**（收檔 `-wo -no-del -no-overwrite`）★★★★ |
| 要觸發一件事？ | **`command=` + 白名單 case**，永不 `eval` ★★★★★ |
| 廠商說「傳不上去」？ | 先看 `namei -l` 與 `sshd -T -C`，**不要先 chmod** ★★★★ |
| 帳號要停用？ | `usermod --expiredate 1` + 移群組 + 搬金鑰 + `pkill -u` ★★★★★ |

## 練習題

> [!question]- 練習 1：把管理員關進 chroot（在測試機上故意做錯）★★★★
> 1. 在**測試機**上把 `Match Group sftpusers` 改成 `Match User *`，先**不要**重啟
> 2. 跑 `sudo sshd -t` → 有報錯嗎？
> 3. 跑 `sudo sshd -T -C user=admin,host=localhost,addr=127.0.0.1 | grep -i chroot` → 看到什麼？
> 4. 說明為什麼「語法檢查過了」不代表「設定是對的」
>
> **參考解答**：② `sshd -t` **不會報錯** —— `Match User *` 語法完全合法。
> ③ 會看到 `chrootdirectory /srv/sftp/admin`，代表**管理員也會被 chroot**；
> 這時若重啟 sshd，新登入就拿不到 shell。
> ④ `sshd -t` 只驗證**語法**、不驗證**語意**；「條件寫錯人」只能靠 `sshd -T -C` 模擬。
> ★★★★ 正式環境 SOP：`sshd -t` → `sshd -T -C user=<管理員>` → 保留逃生連線 → 排自動回滾 → 才重啟。

> [!question]- 練習 2：default ACL 與 Web 共存 ★★★★
> 1. 建立 `vendor-test`，做出 `upload/`（2770）與 `download/`（0750）
> 2. 對 `upload/` 只下 `setfacl -m`（**故意不下** `-d`），上傳一個檔案後 `getfacl` 看新檔案
> 3. 補上 `setfacl -d -m`，再上傳一個檔案，比較兩者
> 4. 用 `sudo -u www-data cat` 與 `sudo -u www-data touch` 驗證「可讀不可寫」
>
> **參考解答**：② 沒有 `-d` 時**只有既有檔案**有 ACL，新上傳的沒有 → Web 讀不到，
> 症狀是「昨天的檔案讀得到、今天的讀不到」，非常難查。
> ③ 補了 `-d` 之後新檔案會出現 `group:www-data:r--`
> （**檔案沒有 x**，因為建檔模式沒有執行位元，這是對的）。
> ④ `cat` 成功、`touch` 得到 `Permission denied` 才算對 ★★★★；
> 若 `touch` 成功表示 ACL 給了 `w`，等於 Web 被入侵後可以往交換區寫檔。

> [!question]- 練習 3：提權自檢與稽核 ★★★★★
> 1. 用本篇的自檢腳本跑完六項
> 2. 把 `AllowTcpForwarding` 暫時改成 `yes`，再跑第 ② 項 → 差別是什麼？
> 3. 在 chroot 內建 `.ssh/authorized_keys` 並 `chown` 給使用者，同時把 `AuthorizedKeysFile` 改回預設
>    → 使用者現在能做什麼？
> 4. 上傳三個檔案跑 `sftp-audit-report`，然後**手動刪掉其中一個檔案**再跑一次 → 月報還看得到嗎？
>
> **參考解答**：② 改成 `yes` 後 `curl 127.0.0.1:9000` 會**連得上 22 埠**（看到 SSH banner），
> 代表受限帳號可以拿你的伺服器當跳板掃內網 ★★★★。
> ③ 使用者可以自己寫入 `command="/bin/bash"` 或加一把新金鑰，下次登入**繞過所有限制**，
> 而且你從外面完全看不出來 ★★★★★。
> ④ **月報仍然看得到** —— 月報來自**日誌**，不是來自檔案系統。
> 這正是稽核軌跡的價值：檔案可以被刪，紀錄留著；
> 反過來說，**日誌保存期限**才是稽核真正在意的東西 ★★★★。

## 小測驗

Q1. 為什麼 chroot 環境下**只能**用 `internal-sftp`？請說出**兩個**互相獨立的理由。

Q2. `ChrootDirectory` 設好了，`vendor01` 卻連上就斷。你會依序做哪三個檢查？

Q3. 為什麼一定要建 `upload/` 子目錄，不能讓廠商直接寫在 chroot 根目錄？

Q4. `setfacl -m g:www-data:r-x upload/` 和 `setfacl -d -m g:www-data:r-x upload/` 差在哪？只下前者會出現什麼症狀？

Q5. 這行指令會發生什麼？`sudo usermod -L vendor01`

Q6. 到期日為什麼要 `chage -E` 與 `expiry-time` **兩道**？客戶端要怎麼分辨是哪一道擋的？

Q7. 你在 `60-sftp.conf` 的 `Match Group sftpusers` **後面**又加了一行 `PasswordAuthentication yes`。會發生什麼？

Q8. 受限帳號的**三條提權路徑**是什麼？各要怎麼實測封死？

Q9. `ForceCommand internal-sftp -l INFO` 設了，日誌卻一行 SFTP 紀錄都沒有。最可能的原因是什麼？

Q10. 廠商上傳目錄要讓 Web 讀取，以下哪個做法安全，為什麼？
(a) 把 `/srv/sftp/vendor01/upload` symlink 到 `/var/www/app/public/files`
(b) 把 chroot 根改成 `/var/www/app/public/vendor01`
(c) 目錄留在 `/srv` 底下，用 ACL 讓 `www-data` 可讀，Nginx 用 `location ^~` 提供下載且該路徑不解析程式

> [!question]- 測驗答案
> **Q1.** ①**執行檔與函式庫不在牢籠裡** —— chroot 之後 `sftp-server` 的路徑變成
> `/srv/sftp/vendor01/usr/lib/openssh/sftp-server`，不存在；就算複製進去還缺
> `ld-linux`、`libc`、`libcrypto`，少一個 `.so` 就啟動失敗，而客戶端看不出缺哪個。
> ②**它需要透過使用者的 login shell 啟動** —— `ForceCommand` 是「用 login shell 加 `-c` 執行」，
> 而受限帳號的 shell 是 `nologin`。
> `internal-sftp` 是 sshd **行程內**實作：不 exec、不需要 shell、牢籠裡不需要任何檔案，
> 所以是 chroot 場景的**唯一選項** ★★★★（見「為什麼 chroot 下只能用 internal-sftp」）。
> 客戶端症狀是 `subsystem request failed on channel 0`，要靠伺服器日誌確認真因。
>
> **Q2.** ①**看 Match 有沒有命中**：`sudo sshd -T -C user=vendor01,host=localhost,addr=127.0.0.1 | grep -i chroot`
> —— 沒輸出就是帳號不在 `sftpusers`，用 `id vendor01` 確認。
> ②**看伺服器日誌**：`journalctl -u ssh -n 50 | grep vendor01` ——
> `bad ownership or modes for chroot directory` 是權限問題，`subsystem not found` 是 subsystem 設錯。
> ③**逐層檢查**：`namei -l /srv/sftp/vendor01`，從 `/` 到 chroot 根**每一層**都要 root 擁有、
> group/other 不可寫 ★★★★。最常見的兇手是 `useradd --create-home` 把根 chown 給了使用者。
> **不要先 `chmod 777`** —— 權限太寬 sshd 一樣拒絕。
>
> **Q3.** 因為 **chroot 根必須 root 擁有且群組與其他人不可寫**，這是 sshd 的硬性檢查
> （防止使用者在牢籠根放 `etc/`、`lib/` 影響後續行為）。
> 根不可寫，廠商就沒有地方可以 `put` —— 症狀是「連得上、一上傳就 Permission denied」★★★★。
> 所以要建 `upload/`（`vendor01:sftp-vendor01`、`2770`）給他寫，
> 另建 `download/`（`root:sftp-vendor01`、`0750`）放我們要給他的東西。
> `2770` 的 **setgid 讓新檔案繼承 `sftp-vendor01` 群組**，
> 後面掛給 `www-data` 的 ACL 才有穩定的群組可依附 ★★★。
>
> **Q4.** `-m` 設的是**目前這個目錄的 access ACL**；`-d -m` 設的是 **default ACL**，
> 之後在裡面**新建的檔案與子目錄**才會繼承。
> 只下 `-m` 的症狀很有代表性：**設定當下就有的檔案 Web 讀得到，
> 廠商明天新上傳的讀不到**，變成「昨天好好的，今天又壞了」的鬼故事 ★★★★。
> 正確做法是兩個都下，然後**實際上傳一個檔案用 `getfacl` 驗證**，
> 預期看到 `group:www-data:r--`（檔案沒有 x 是對的）。
> 注意目錄有 default ACL 時，`-u 0027` 的 umask 不再單獨決定新檔案權限，
> 而是與 default ACL 取交集 —— **一定要看實際結果，不要用推的**。
>
> **Q5.** `usermod -L` 只是在 `/etc/shadow` 的密碼雜湊前加一個 `!`，**把密碼鎖起來**。
> 受限帳號**根本沒有密碼**，走的是 `AuthenticationMethods publickey`，
> 所以這行指令**完全沒有效果** —— 廠商照樣連得進來 ★★★★★，這是稽核最愛抓的假停用。
> 真正停用要四件事一起做：`usermod --expiredate 1`（帳號立刻過期）、
> `gpasswd -d vendor01 sftpusers`（Match 不再命中）、
> 把 `authorized_keys` 改名搬走、`pkill -u vendor01`（踢掉現有連線）。
> 而且**先停用不刪除**：`userdel` 會讓資料變孤兒 UID、UID 被重用時舊檔案會「變成」新帳號的，
> 保存期限通常也還沒到（見「停用不是 `usermod -L`」）。
>
> **Q6.** 兩道走**完全不同的檢查路徑**：`chage -E` 是 shadow／PAM 的帳號到期檢查，
> 生效與否受 `UsePAM` 等設定影響；`expiry-time` 由 **sshd 驗金鑰時自己檢查**，不經過 PAM。
> 實務價值是**防呆**：換金鑰時常複製舊的一行卻忘了改日期，這時 `chage -E` 還擋著；
> 反過來帳號被別的流程清掉到期日時，`expiry-time` 還擋著 ★★★★。
> **客戶端分辨不出來** —— 兩種都是 `Permission denied (publickey).`。
> 只能看伺服器端：有 `pam_unix(sshd:account): account vendor01 has expired` 是 `chage` 擋的；
> 沒有那行而是認證失敗，就是 `expiry-time` 或 `from=` 擋的（排查步驟【5】）。
>
> **Q7.** `Match` 的效力延伸到「**下一個 `Match` 行或檔案結尾**」，
> 所以那行**不是全域設定，而是只對 `sftpusers` 生效** ——
> 你等於**只替受限帳號打開了密碼登入**，而這正是最不該開的一群帳號 ★★★★★。
> 這種錯誤 `sshd -t` **抓不到**（語法合法），只能用
> `sudo sshd -T -C user=vendor01,… | grep -i passwordauthentication` 檢查實際值。
> 所以規矩是：**Match 區塊永遠放在該檔案最後面**，
> 而且「Match 之後不要再寫任何你以為是全域的設定」。
>
> **Q8.** ①**開隧道當跳板** → `AllowTcpForwarding no`、`AllowStreamLocalForwarding no`、`PermitTunnel no`；
> 實測 `ssh -N -L 9000:127.0.0.1:22 …` 之後**實際去 `curl 127.0.0.1:9000`**，
> 要看到 `administratively prohibited: open failed`（★★★ 只建立轉發不去連是測不出來的）。
> ②**改自己的 `authorized_keys`** → `AuthorizedKeysFile /etc/ssh/authorized_keys/%u`
> 把金鑰放 chroot 外、root:root 0644；實測在 sftp 裡 `ls -l /.ssh` 要找不到。
> ③**寫進被 root 讀取或執行的路徑** → 確認 `/etc/cron.d`、systemd unit 目錄不可寫，
> 並檢查**有沒有 root 排程會處理上傳目錄**；那支腳本不可以 `eval`／`source` 上傳內容，
> 檔名要用 `find -print0` 處理 ★★★★★（見「提權自檢清單」）。
>
> **Q9.** 最可能是 **chroot 裡沒有 `/dev/log`**。`internal-sftp` 的日誌透過 syslog socket 送出，
> chroot 之後路徑變成 `/srv/sftp/vendor01/dev/log`，不存在 →
> **訊息掉在牢籠裡，而且沒有任何錯誤提示** ★★★★，你會誤以為 `-l INFO` 沒作用。
> 解法是讓 rsyslog 在每個 chroot 內開 socket：
> `input(type="imuxsock" Socket="/srv/sftp/vendor01/dev/log" CreatePath="on")`，
> 再用 `if $programname == 'internal-sftp'` 分流到 `/var/log/sftp.log` 並 `stop`。
> 驗證：`ls -l …/dev/log` 要看到 `s` 開頭的 socket。
> 次要可能：`ForceCommand` 根本沒帶 `-l INFO`（用 `sshd -T -C` 確認），或你看錯日誌檔。
>
> **Q10.** **只有 (c) 安全** ★★★★★。
> (a) symlink 沒有改變「Nginx 的 `location ~ \.php$` 會比對到 `/files/x.php`」這件事，
> PHP-FPM 照樣解析並執行上傳的檔案 —— **這是完整的遠端程式碼執行**。
> (b) 更糟：整個 chroot 根都在 web root 裡，連 `download/` 都能被列舉與執行。
> (c) 的三個要素缺一不可：①**實體位置在 web root 之外**；
> ②用 **ACL** 讓 `www-data` 可讀不可寫（`sudo -u www-data touch` 必須失敗）；
> ③Nginx 用 **`location ^~ /files/`** —— `^~` 會**阻止後面的正規表示式 location 被比對** ——
> 再加 `Content-Disposition: attachment`、`X-Content-Type-Options: nosniff`
> 與對 `.php|.phtml|.phar|.svg|.html` 的 `return 403` 當雙保險。
> 驗收：上傳 `t.php` 後 `curl` 必須拿到 **403/404，絕不能是 200**（見 [[09-Nginx-安全設定]]）。

## 延伸閱讀

- [[04-sshd-伺服器端設定]] —— `Match`、drop-in 載入順序與 `sshd -T` 的完整說明，本篇的地基
- [[01-scp與sftp傳輸]] —— 客戶端怎麼傳、`sftp` 批次模式、chroot 權限規則的完整版
- [[07-SSH-安全強化]] —— 演算法加固、2FA、Fail2ban，受限帳號之外的整體防線
- [[05-SSH-隧道與埠轉發]] —— 先懂隧道能做什麼，才知道 `AllowTcpForwarding no` 擋掉了什麼
- [[08-檔案權限與擁有者]] —— setgid、POSIX ACL、`getfacl` 的細節
- [[09-Nginx-安全設定]] —— 上傳目錄與 Web 共存的紅線、`location ^~` 與關閉執行權
- [[02-rsync-同步與備份]] —— rrsync 帳號背後的同步策略與輪替設計
- [[02-日誌集中與輪替]] —— 稽核日誌的長期保存、集中與完整性保護
- [[09-資安稽核與符合性檢核]] —— 稽核會問什麼、要交出哪些證據
- OpenSSH `sshd_config(5)`：<https://man.openbsd.org/sshd_config.5>
- OpenSSH `sshd(8)` AUTHORIZED_KEYS 格式（`restrict`、`expiry-time`）：<https://man.openbsd.org/sshd.8>
- rsync `rrsync(1)`：<https://manpages.debian.org/rrsync.1>
