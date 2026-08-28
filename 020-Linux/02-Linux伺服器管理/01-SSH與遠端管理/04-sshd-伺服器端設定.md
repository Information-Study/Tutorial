---
title: "sshd 伺服器端設定"
desc: "不鎖門 SOP、sshd_config.d 覆寫順序、KbdInteractive 與 ssh.socket 三大陷阱"
aliases: [sshd_config, sshd, sshd -T, sshd_config.d, ssh.socket]
tags: [群組/Linux, 服務/ssh, 主題/設定]
category: SSH與遠端管理
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[02-SSH-金鑰認證與ssh-agent]]", "[[17-systemd服務管理]]"]
updated: 2026-08-28
---

# sshd 伺服器端設定

> [!abstract] 這篇你會學到
> - ★★★★★ 一套「改 sshd 而**不會把自己鎖在外面**」的標準作業程序：保留舊連線、`sshd -t`、
>   `systemd-run` 自動回滾 timer、另一個埠前景試跑 —— 七道保險，缺一道就是在賭運氣
> - ★★★★★ 為什麼你在 `/etc/ssh/sshd_config` **末尾**改的設定會被 `sshd_config.d/` 悄悄蓋掉，
>   以及唯一可信的驗證方式 `sudo sshd -T`
> - ★★★★★ `PasswordAuthentication no` 設好了卻**還能用密碼登入** —— 元凶是 `KbdInteractiveAuthentication`
> - ★★★★ Ubuntu 24.04 起 sshd 由 `ssh.socket` 觸發，改 `Port` 不會生效，要改 `ListenStream=`
> - ★★★★ 用 `AllowGroups` 取代一長串帳號、用 `Match` 分角色，並用
>   `sshd -T -C user=admin,addr=10.10.0.5` 驗證「這個人實際會拿到什麼設定」
> - 產出可直接部署的 `sshd-apply` / `sshd-confirm` / `sshd-rollback` 三支腳本與驗收檢查表

> [!warning] 未實機驗證
> 本篇的 **socket activation（`ssh.socket`）** 與 **自動回滾 timer** 兩段依 Ubuntu 官方公告與
> OpenSSH／systemd 手冊撰寫，撰稿環境沒有可長期保留的實體伺服器完整驗證；其餘設定項與預設值
> 以 Ubuntu 24.04（OpenSSH 9.6p1）`man 5 sshd_config` 為準。導入前請先在測試機跑一遍
> 本篇的「驗收檢查表」。

## 前置知識

- [[02-SSH-金鑰認證與ssh-agent]] —— 本篇所有建議都預設「你已經有一把能登入的金鑰」
- [[01-SSH-原理與第一次連線]] —— 認證流程與 host key 的角色
- [[17-systemd服務管理]] —— `reload` 與 `restart` 的差別、`systemctl edit` 建 drop-in
- [[03-SSH-客戶端設定檔]] —— 客戶端怎麼配合伺服器端的埠與 `ControlMaster` 的陷阱

## 觀念說明

### sshd 的設定不是「你寫了什麼」，是「sshd 讀完之後決定用什麼」

99% 的 sshd 事故都來自同一個誤解 —— **以為編輯器裡看到的就是生效的設定**。
Ubuntu 22.04 以後這個假設是錯的：

```text
sshd 啟動
 ├─▶ /etc/ssh/sshd_config 第 1 行：Include /etc/ssh/sshd_config.d/*.conf   ★★★★★
 │      50-cloud-init.conf → 50-gov-baseline.conf → 60-cloudimg-settings.conf
 │      （依「檔名字典序」展開，數字小的先讀）
 ├─▶ 主檔第 2 行以後（你手改的地方，最後才讀到）
 ├─▶ 規則：★★★★★ 同一關鍵字「第一個讀到的值勝出」，後面寫幾次都沒用
 └─▶ Match 區塊：連線進來時依 user / addr 再套一層 ─▶ sudo sshd -T ← 唯一可信的答案
```

`man 5 sshd_config` 原文：*Unless noted otherwise, for each keyword,
**the first obtained value will be used**.*
★★★★★ 這跟 Nginx `conf.d`、systemd drop-in 的「後蓋前」直覺**完全相反**。

| 壞法 | 後果 | 星級 |
| --- | --- | --- |
| 語法寫錯就 `restart` | sshd 起不來，**所有人都連不進去**，只剩 console／IPMI | ★★★★★ |
| 改 `AllowGroups` 但自己不在群組裡 | 服務正常、**你被擋在門外**，比起不來更難察覺 | ★★★★★ |
| 以為關掉密碼登入、其實沒關 | 暴力破解持續有效，稽核報告還變成不實陳報 | ★★★★★ |
| 改了 `Port` 卻沒改 `ssh.socket` | 新埠沒開、舊埠還在，防火牆已按新埠設 → 全斷 | ★★★★ |
| `Match` 放在檔案中間 | **後面所有設定變成該條件專屬**，全域設定憑空消失 | ★★★★ |

### 三個一定要先會的工具

| 指令 | 回答什麼問題 | 星級 |
| --- | --- | --- |
| `sudo sshd -t` | **語法**有沒有錯（不看語意） | ★★★★★ |
| `sudo sshd -T` | 合併 Include 之後，**全域實際生效**的值 | ★★★★★ |
| `sudo sshd -T -C user=x,host=y,addr=z` | **某人從某來源連進來實際拿到什麼**（含 Match） | ★★★★ |

**任何時候想知道「現在到底是什麼設定」，答案永遠是 `sshd -T`，不是 `cat sshd_config`。**

> [!danger] ★★★★★ 改 sshd 設定永遠先 `reload`，不要 `restart`
> `reload` 送 `SIGHUP` 讓主程序重讀設定，**現有連線全部保留**；Ubuntu 的 unit 還帶
> `ExecReload=/usr/sbin/sshd -t`，**語法錯會直接拒絕 reload**。
> `restart` 則是殺掉再重開，設定寫錯就進 `failed`，**所有人（含你）都連不進去**。
> `reload` 的價值不在「不中斷服務」，而在**設定改壞時你那條已登入的 session 還活著**，
> 還有機會改回來。完整差異見 [[17-systemd服務管理]]。

本篇主線是 **Ubuntu 24.04 LTS（openssh-server 9.6p1）**，RHEL 差異集中在「進階設定與調校」末尾的摺疊區塊。

## 環境準備與安裝

### 步驟 0：先搞清楚你在哪一種環境 ★★★★

動任何一個字之前先跑完這三組指令。**不同版本行為差很多，猜錯就是事故。**

```bash
$ ssh -V; lsb_release -ds; grep -n '^Include' /etc/ssh/sshd_config; ls -1 /etc/ssh/sshd_config.d/
OpenSSH_9.6p1 Ubuntu-3ubuntu13.5, OpenSSL 3.0.13 30 Jan 2024
Ubuntu 24.04.2 LTS
1:Include /etc/ssh/sshd_config.d/*.conf    # ★★★★★ 在第 1 行 = 裡面的設定全贏過主檔
50-cloud-init.conf
60-cloudimg-settings.conf
```

```bash
$ systemctl is-enabled ssh.socket; systemctl list-units 'ssh*' --all --no-pager
enabled                       # ★★★★ socket 模式（disabled 或找不到 unit = 傳統 service 模式）
ssh.service   loaded inactive dead      OpenBSD Secure Shell server
ssh.socket    loaded active   listening OpenBSD Secure Shell server socket
```

★★★★ `ssh.service` 顯示 `inactive (dead)` **不代表 SSH 掛了** —— socket 模式下沒人連線時它本來就是
dead。很多人一看到 inactive 就去 `systemctl start ssh`，反而搞出「兩個東西搶同一個埠」。
**要看 `ssh.socket` 是不是 `listening`。**

```bash
$ sudo sshd -T | grep -Ei '^(port|permitrootlogin|pubkeyauth|passwordauth|kbdinteractive|usepam|loglevel)'
port 22
permitrootlogin prohibit-password
pubkeyauthentication yes
passwordauthentication yes            # ★★★★ 預設是開的
kbdinteractiveauthentication yes      # ★★★★★ 這個也開著，關鍵陷阱
usepam yes
loglevel INFO
```

`sshd -T` 把關鍵字印成**小寫**、連沒設定的預設值都印出來 —— 這是它比 `grep sshd_config` 可靠的原因。

### 步驟 1：★★★★★ 不鎖門 SOP —— 本篇的招牌

```text
 ①  保留一條已登入的 session，全程不要關      ← 最便宜、最有效
 ②  sudo sshd -t                              語法檢查
 ③  sudo sshd -T / -T -C                      驗證「真正生效的值」
 ④  systemd-run --on-active=5m 自動回滾 timer  ← 保險絲
 ⑤  /usr/sbin/sshd -D -p 2222 -f 新檔          另一個埠前景試跑
 ⑥  確認 IPMI / iDRAC / PVE console 可用       最後一條路
 ⑦  systemctl reload ssh（不是 restart）
```

#### ① 保留一條既有連線 ★★★★★

開兩個終端機，**第一個登入後就不要動它、不要關它、不要 `exit`**，所有編輯與 `reload` 都在它裡面做。
`reload` 的 `SIGHUP` 只讓**主程序**重讀設定，**已建立的連線是獨立子程序，不受影響** —— 
就算新設定把你的帳號完全擋掉，這條 session 仍然活著。
★★★ 再加一層：`tmux new -s sshd-work`，網路閃斷後 `tmux attach` 就回到現場。

```bash
$ who am i; echo "$SSH_CONNECTION"
admin    pts/0        2026-08-28 09:12 (10.10.0.5)
10.10.0.5 51234 10.10.0.20 22      # ★★★ 待會 Match 驗證要用這個來源 IP
```

#### ② `sshd -t`：語法檢查 ★★★★★

```bash
$ sudo sshd -t && echo "語法 OK"
語法 OK
$ sudo sshd -t          # 把 AllowGroups 打成 AllowGroup 時
/etc/ssh/sshd_config.d/50-gov-baseline.conf line 12: Bad configuration option: AllowGroup
/etc/ssh/sshd_config.d/50-gov-baseline.conf: terminating, 1 bad configuration options
```

候選檔還沒放進正式路徑時用 `-f` 測：`sudo sshd -t -f /tmp/sshd_config.candidate`。
★★★★ **`sshd -t` 只驗語法，不驗「你會不會被鎖在外面」** —— `AllowGroups nobody-at-all`
語法完全正確，它一句話都不會說。**語法通過 ≠ 安全**，還要靠 ③ 與 ⑤。

#### ③ `sshd -T`：印出真正生效的值 ★★★★★

```bash
$ sudo sshd -T | grep -Ei 'passwordauthentication|kbdinteractive'
passwordauthentication no
kbdinteractiveauthentication no     # ★★★★★ 兩行都是 no，密碼登入才是真的關了
$ sudo sshd -T -C user=admin,host=mgmt01,addr=10.10.0.5,laddr=10.10.0.20,lport=22 \
    | grep -Ei 'allowtcpforwarding|permitrootlogin'
allowtcpforwarding yes              # ← Match 區塊放行了這個人的埠轉發
permitrootlogin no
```

`-C` 的關鍵字有 `user` / `host` / `addr` / `laddr` / `lport` / `rdomain`；★★★ 舊版 OpenSSH 要求
`user`、`host`、`addr` **三個都要給**。★★★★ 另外把生效值存成基準快照，日後一行 `diff` 就知道
「這台跟基準差在哪」（[[02-基準設定與範本化]] 在 SSH 上的具體應用）：

```bash
$ sudo sshd -T | sort > /var/backups/sshd/effective-$(date +%F).txt
$ diff <(sudo sshd -T | sort) /var/backups/sshd/effective-2026-08-01.txt
```

#### ④ `systemd-run` 自動回滾 timer ★★★★★

七道保險裡最強的一道：**先安排好「五分鐘後自動還原」，再去改設定。**
沒有 `systemd-run` 時可退而求其次用 `echo ... | sudo at now + 5 minutes`（`atq` 查、`atrm` 取消），
但 `systemd-run` 的執行結果會寫進 journal，事後查得到（選型見 [[02-systemd-timer與cron選型]]）。

```bash
$ sudo systemd-run --on-active=5m --unit=sshd-rollback /usr/local/bin/sshd-rollback
Running timer as unit: sshd-rollback.timer
Will run service as unit: sshd-rollback.service
$ systemctl list-timers sshd-rollback.timer --no-pager | sed -n 2p
Fri 2026-08-28 09:22:41 CST 4min 58s  -  -  sshd-rollback.timer sshd-rollback.service
```

驗證成功後**一定要停掉**：`sudo systemctl stop sshd-rollback.timer`

> [!danger] ★★★★★ 忘了停 timer 的後果比你想的糟
> 你改好設定、測試通過、關掉筆電去吃飯 —— 五分鐘後設定被還原，
> 但**防火牆、客戶端 `~/.ssh/config`、監控系統都還是照新設定在跑**。
> 下午回來一堆「連不上」告警，而設定檔看起來完全正常（因為它被還原了）。這種案件極難查。
> **把 `sshd-confirm` 寫成腳本，養成「驗證完立刻執行」的肌肉記憶。**

#### ⑤ 在另一個埠前景試跑 ★★★★

唯一能在**完全不動正式服務**的前提下真正驗證新設定的方法。

```bash
$ sudo ufw allow 2222/tcp comment 'sshd temp test'
$ sudo /usr/sbin/sshd -D -p 2222 -f /etc/ssh/sshd_config.candidate -e
Server listening on 0.0.0.0 port 2222.        # 前景不返回是正常的
```

```bash
# 另開第三個終端機從外部測，測完 Ctrl+C 並 sudo ufw delete allow 2222/tcp
$ ssh -p 2222 -o StrictHostKeyChecking=no admin@10.10.0.20 'id; echo LOGIN-OK'
uid=1000(admin) gid=1000(admin) groups=1000(admin),27(sudo),1002(ssh-users)
LOGIN-OK
```

★★★ 兩個坑：(1) OpenSSH 9.8 起 `sshd` 會再執行 `/usr/lib/openssh/sshd-session`，用絕對路徑
`/usr/sbin/sshd` 沒問題，但**把 binary 複製到別的目錄再跑會失敗**；(2) 候選檔若有
`ListenAddress 10.10.0.20:22` 這種帶埠寫法，**不會**被 `-p 2222` 覆蓋，會導致試跑仍綁 22 埠
而衝突 —— 試跑用的候選檔先把 `ListenAddress` 註解掉。

#### ⑥ 確認頻外管理（out-of-band）可用 ★★★★★

實體機先登入一次 iDRAC / iLO / IPMI 確認密碼沒過期（★★★★★）；PVE / VMware 先開一次網頁
Console 看到 login prompt（★★★★）；公有雲有些要先在設定裡啟用序列主控台（★★★）；
什麼頻外管理都沒有的機器，★★★★★ 你更該做 ④ 的自動回滾 timer。

★★★★★ 「反正我等一下再測」是最常見的事故起點。機關常見情境：機房在別的樓層、
iDRAC 密碼是三年前同事設的、PVE 帳號沒有這台 VM 的 console 權限 ——
都是「要用的時候才發現不能用」。**改 sshd 前先驗證頻外管理，不是流程潔癖，是保命。**

#### ⑦ `reload`，不是 `restart` ★★★★★

```bash
$ sudo systemctl reload ssh          # 沒有輸出就是成功
$ systemctl status ssh --no-pager | sed -n 3p; sudo sshd -T | grep -i passwordauth
     Active: active (running) since Fri 2026-08-28 09:12:03 CST; 3min ago
passwordauthentication no            # ★★★★ 新值生效了
$ ssh -o ControlMaster=no -o ControlPath=none admin@10.10.0.20 'echo NEW-SESSION-OK'
NEW-SESSION-OK
```

★★★★ 最後一步一定要從**第二個乾淨終端機**做，而且 `-o ControlPath=none` 很重要 —— 
若 `~/.ssh/config` 開了連線多工，「新連線」其實走舊通道、**根本沒重新認證**，測了等於沒測
（見 [[03-SSH-客戶端設定檔]]）。驗證成功立刻 `sudo systemctl stop sshd-rollback.timer`。

## 基礎設定

### 設定檔治理：★★★★ 不要動主檔

```text
/etc/ssh/sshd_config              ← ★★★★ 套件地盤，升級會問你要不要覆蓋。不要動。
/etc/ssh/sshd_config.d/
    ├── 50-cloud-init.conf        ← 安裝程式產生的，你沒寫但它會贏
    ├── 50-gov-baseline.conf      ← ★★★★★ 機關基準寫這裡
    └── 60-cloudimg-settings.conf ← 雲端映像帶的
```

三個理由：**升級不會被覆蓋**（改過主檔時 `dpkg` 會跳出互動詢問，自動化派送會卡住整批機器 ★★★★）、**可以納入版控**、**職責清楚**（「這台跟基準差在哪」只看一個檔案）。

> [!danger] ★★★★★ 檔名排序決定誰贏，不是你寫的位置
> `Include` 用 **glob 展開後的字典序**讀檔，規則是**第一個讀到的值勝出**。所以
> `50-cloud-init.conf` 的 `PasswordAuthentication yes` **贏過** `60-cloudimg-settings.conf`
> 的 `no`，也贏過你在主檔任何位置寫的設定。**數字小的贏。**
> 機關基準要壓過 cloud-init 就取一個排在它前面的檔名（`10-gov-baseline.conf`），
> 或更乾淨：**直接清空 `50-cloud-init.conf`**。驗證永遠只有 `sudo sshd -T | grep <關鍵字>`。

### 監聽類：Port / ListenAddress / AddressFamily

| 指令 | 預設值 | 建議值 | 改壞會怎樣 |
| --- | --- | --- | --- |
| `Port` | `22` | 維持或改非標準埠 | ★★★★ Ubuntu 24.04 socket 模式下**改了不生效** |
| `ListenAddress` | 全部位址 | ★★★★ `10.10.0.20`（只綁管理網段） | 綁到開機時還沒起來的 IP → sshd 起不來 |
| `AddressFamily` | `any` | 沒用 IPv6 就 `inet` | 設 `inet` 後 IPv6 客戶端全部連不進來 |

```bash
$ sudo ss -lntp '( sport = :22 )'
State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process
LISTEN 0      4096      10.10.0.20:22        0.0.0.0:*     users:(("systemd",pid=1,fd=93))
```

★★★★ `Process` 欄顯示 **`systemd`** 而不是 `sshd`，就代表你在 **socket 啟動模式**，
`Port` / `ListenAddress` 這兩個指令**根本沒被使用**。

> [!danger] ★★★★★ `ListenAddress` 綁到「開機時還不存在」的位址 = 開機後 SSH 全滅
> 常見於 VLAN 子介面、bond、DHCP 才拿得到的 IP、keepalived 的 VIP。sshd 雖在
> `network-online.target` 之後啟動，但**介面拿到 IP 的時機不保證**。兩個解法：
> 多寫一行 `ListenAddress 127.0.0.1` 當保底位址，或在 socket 模式加 `[Socket]` `FreeBind=yes`
> （★★★★ VIP 情境一律用這個，否則主備切換時 sshd 會啟動失敗）。

### ★★★★ Ubuntu 24.04：`Port` 要改在 `ssh.socket`

Ubuntu 從 22.10（openssh-server `1:9.0p1-1ubuntu1`）起預設改用 **systemd socket activation**：
由 `ssh.socket` 監聽 22 埠、有連線才觸發 sshd，省下常駐記憶體，
代價是 **`sshd_config` 的 `Port` 與 `ListenAddress` 不再被使用**。

```bash
$ sudo systemctl edit ssh.socket      # 做法 A（建議）
```

```ini
[Socket]
# ★★★★★ 空的那行是必要的！它清掉原本的 22，否則會變成同時聽 22 和 2222
ListenStream=
ListenStream=2222
```

```bash
$ sudo systemctl daemon-reload && sudo systemctl restart ssh.socket && sudo ss -lntp | grep 2222
LISTEN 0 4096 *:2222 *:* users:(("systemd",pid=1,fd=93))
```

> [!danger] ★★★★★ 少寫那行空的 `ListenStream=` 會怎樣
> systemd 的 `ListenStream=` 是**列表型**指令，直接寫新值是「**追加**」不是「取代」，
> 結果 22 和 2222 **同時開著**。你以為改好埠了、防火牆只放行 2222，
> **但 22 埠還在對外裸奔**，暴力破解照樣打得進來 —— 資安稽核會直接開缺失。
> 同樣的列表語意也適用於 unit 的 `ExecStart=`，見 [[01-systemd-unit撰寫實戰]]。

做法 B 是關掉 socket 回到傳統 service 模式（組態管理／TWGCB 檢測腳本假設常駐服務時較省事），
之後 `Port` / `ListenAddress` 就恢復作用：

```bash
$ sudo systemctl disable --now ssh.socket
$ sudo rm -f /etc/systemd/system/ssh.service.d/00-socket.conf \
             /etc/systemd/system/ssh.socket.d/addresses.conf   # ★★★★ 不刪會繼續強迫 socket 行為
$ sudo systemctl daemon-reload && sudo systemctl enable --now ssh.service
$ sudo ss -lntp '( sport = :22 )' | tail -1
LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=1421,fd=3))    # ★★★ Process 變回 sshd
```

★★★★ 另外 socket 模式下 `journalctl -u ssh` 可能看不到連線日誌（sshd 有機會跑在別的 unit 名稱底下）。
最保險是用 syslog identifier `journalctl -t sshd -f`；監控與告警規則（[[19-日誌系統]]、
[[02-日誌集中與輪替]]）記得一起改，否則會出現「登入失敗告警突然歸零」的假象。

### 認證類：★★★★★ 最容易自以為設好的一組

| 指令 | 預設值 | 建議值 | 改壞會怎樣 |
| --- | --- | --- | --- |
| `PermitRootLogin` | `prohibit-password` | ★★★★ `no` | 設 `yes` + 密碼 = 全網 bot 都在打你的 root |
| `PubkeyAuthentication` | `yes` | `yes` | 設 `no` 而密碼也關 = **沒有任何人能登入** ★★★★★ |
| `PasswordAuthentication` | `yes` | ★★★★ `no` | 單獨設 `no` **擋不住密碼登入**，見下方 |
| `KbdInteractiveAuthentication` | **`yes`** | ★★★★★ `no` | 忘了關 = 密碼登入其實還開著 |
| `PermitEmptyPasswords` | `no` | `no` | 設 `yes` 等於門戶洞開 ★★★★★ |
| `AuthenticationMethods` | 未設 | `publickey` | ★★★★ `publickey,password` 是**兩種都要**，不是二選一 |
| `MaxAuthTries` | `6` | `3` | 設 `1` 會讓「agent 裡有多把金鑰」的人直接被踢 ★★★ |
| `MaxStartups` | `10:30:100` | `10:30:60` | 設太小，多人同時登入會被隨機拒絕 ★★★ |
| `UsePAM` | 上游 `no`／Ubuntu `yes` | ★★★★ `yes` | 設 `no` 會壞掉帳號鎖定、密碼過期、`wtmp` 紀錄 |

#### ★★★★★ 頭號陷阱：關了密碼登入，卻還能用密碼登入

```bash
$ echo 'PasswordAuthentication no' | sudo tee -a /etc/ssh/sshd_config && sudo systemctl reload ssh
$ ssh -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no admin@10.10.0.20
admin@10.10.0.20's password:        # ★★★★★ 還是問密碼，而且輸入正確就會登入
```

原因有兩層：(1) **`KbdInteractiveAuthentication` 預設 `yes`**，搭配 `UsePAM yes` 時 PAM 的
`pam_unix` 一樣會問密碼並驗證 —— 走的是 `keyboard-interactive` 而非 `password`，
`PasswordAuthentication no` 管不到它；(2) **`Include` 在檔首、第一個值勝出**，
你 `tee -a` 加在主檔末尾那行很可能被 `50-cloud-init.conf` 的 `yes` 蓋掉，連第一層都沒過。

```bash
$ sudo tee /etc/ssh/sshd_config.d/50-gov-baseline.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no      # ★★★★★ 這行才是關鍵
PubkeyAuthentication yes
PermitEmptyPasswords no
EOF
$ sudo sshd -t && sudo systemctl reload ssh
$ sudo sshd -T | grep -Ei 'passwordauthentication|kbdinteractiveauthentication'
passwordauthentication no
kbdinteractiveauthentication no
$ ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no admin@10.10.0.20
admin@10.10.0.20: Permission denied (publickey).      # ★★★★★ 這才是關對了
```

★★★ OpenSSH 8.7 起 `ChallengeResponseAuthentication` 已改名為 `KbdInteractiveAuthentication`，
舊名仍可用；兩者是同一件事，**不要兩個都寫**（會互相覆蓋而且第一個勝出）。

★★★ **`MaxStartups 10:30:100` 不是「最多 10 條連線」**。三個數字是 `start:rate:full`，
管的是**未認證連線數**：10 以內全接受；超過 10 之後以 **30%**（百分比，不是秒也不是數量）
機率隨機拒絕、機率線性上升；到 100 全部拒絕。症狀是「有時候連得上、有時候被拒絕」，
日誌出現 `beginning MaxStartups throttling`。跳板機／CI 大量併發要調大（`30:30:200`）。

### 存取控制：★★★★ Allow / Deny 的評估順序

```text
連線進來 ─▶ ① DenyUsers 命中 → 拒絕 ─▶ ② AllowUsers 有設但沒命中 → 拒絕
         ─▶ ③ DenyGroups 命中 → 拒絕 ─▶ ④ AllowGroups 有設但沒命中 → 拒絕 ─▶ 允許
```

**Deny 永遠優先於 Allow；只要設了 Allow 類，沒被列到的人一律進不來。** 機關環境不要用
`AllowUsers admin ops01 ops02 vendor-a`（人事異動都要改設定 + reload + 走變更申請），改用 ★★★★ `AllowGroups ssh-users`：

```bash
$ sudo groupadd -f ssh-users && sudo usermod -aG ssh-users admin
$ id admin | tr ',' '\n' | grep ssh-users; getent group ssh-users
1002(ssh-users)
ssh-users:x:1002:admin,ops01
```

好處是**人事異動不用改 sshd 設定**（`usermod -aG` 下次登入即生效，不必 reload）、
**稽核好交代**（`getent group ssh-users` 一行交卷）、**可對接 AD／LDAP 群組**。

> [!danger] ★★★★★ 設 `AllowGroups` 之前，先確認自己在群組裡
> 這是「服務正常但你進不去」最經典的寫法。順序永遠是：
> ```bash
> sudo groupadd -f ssh-users && sudo usermod -aG ssh-users "$(logname)"
> id "$(logname)" | grep -q ssh-users || { echo "★ 你不在群組裡，停手"; exit 1; }
> ```
> ★★★★ `usermod -aG` 不影響你現在這條 session 的群組，但 sshd 是在**新連線認證時**
> 才查 `getent group`，所以新連線會拿到新群組，不需要先登出。

### 逾時與連線品質

| 指令 | 預設值 | 建議值 | 說明 |
| --- | --- | --- | --- |
| `LoginGraceTime` | `120` | ★★★ `30` | 連上但沒完成認證的最長時間，縮短可減輕騷擾 |
| `ClientAliveInterval` | `0`（關閉） | ★★★★ `300` | 每隔幾秒送一次加密探測 |
| `ClientAliveCountMax` | `3` | ★★★★ `3` | 連續幾次沒回應就斷線 |
| `UseDNS` | `no` | ★★★ `no` | 開著會對來源 IP 做反解 |

**閒置逾時 = `ClientAliveInterval × ClientAliveCountMax`。** 機關稽核常見的「閒置 15 分鐘登出」
= 900 秒，寫成 `300 / 3`（推薦，語意明確）或 TWGCB／CIS 常見的 `900 / 0`。

> [!warning] ★★★ `ClientAliveCountMax 0` 的行為在不同版本曾有差異
> 有些舊版把 `0` 解讀為「停用」，結果**逾時根本沒生效**，稽核抽查才被抓到。
> 導入前實測：開一條連線放著不動，約 900 秒後應看到
> `Connection to 10.10.0.20 closed by remote host.`，沒斷就是沒生效。
> ★★★ 另外：`rsync` 大檔、`apt upgrade` 這類通道上有資料在跑的工作**不會**被斷，真正會被斷的是
> 「開著 shell 去開會」；長工作一律 `tmux` / `nohup`，不要靠放寬逾時。

**`UseDNS` 的 20~30 秒之謎 ★★★**：開著時 sshd 會對來源 IP 做 PTR 反解。內網 IP 通常沒有 PTR，
兩台 DNS 各 5 秒逾時再 retry → **使用者要等 20~30 秒才看到提示**，
而這 100% 會被回報成「網路很慢」，然後你去查交換器查半天。
症狀確認：`ssh -v` 卡在 `debug1: Connecting to ...` 很久，就去伺服器 `sshd -T | grep usedns`。

## 進階設定與調校

### 功能開關與最小化 ★★★★

**預設全部關掉，需要的人用 `Match` 個別放行** —— 最小權限原則在 sshd 上的具體寫法。

| 指令 | 預設 | 基準建議 | 不關的風險／關掉會擋住什麼 |
| --- | --- | --- | --- |
| `AllowTcpForwarding` | `yes` | ★★★★ `no` | 不關 = 任何能登入的人都能把內網服務轉出去 |
| `PermitOpen` | `any` | ★★★★ 白名單 | 搭配 forwarding 限制「只能轉到哪些目標」 |
| `GatewayPorts` | `no` | ★★★★★ `no` | 設 `yes` 會讓 `-R` 轉發**綁到 0.0.0.0**，等於在防火牆開洞 |
| `AllowAgentForwarding` | `yes` | ★★★★★ `no` | 跳板機 root 可**盜用你的 agent 去登入別台** |
| `X11Forwarding` | `no`（Ubuntu 主檔常設 `yes`） | ★★★ `no` | 伺服器沒 GUI 就該關 |
| `PermitUserEnvironment` | `no` | ★★★★★ **`no`** | `yes` = 使用者可經 `~/.ssh/environment` 注入 `LD_PRELOAD` 提權 |
| `DisableForwarding` | 未設 | ★★★★ 一次全關 | 比逐項關更保險，會蓋過所有 forwarding 設定 |
| `PermitTTY` | `yes` | 服務帳號 `no` | 自動化帳號不該拿到互動 shell |

```bash
$ sudo sshd -T | grep -Ei 'forwarding|gatewayports|permittunnel|permituserenvironment'
allowagentforwarding no
allowtcpforwarding no
gatewayports no ／ x11forwarding no ／ permittunnel no ／ permituserenvironment no
```

> [!danger] ★★★★★ `AllowAgentForwarding yes` + 跳板機 = 你的金鑰等於交出去了
> agent forwarding 會在跳板機上建立一個 socket，**該機器的 root 可以直接拿它去簽認證挑戰**，
> 等於用你的身分登入你所有能登入的機器 —— 私鑰從頭到尾沒離開本機，**事後追不到**。
> 正解是用 `ProxyJump`（`ssh -J`）取代，見 [[03-SSH-客戶端設定檔]]。
> 客戶端 `-L` / `-R` / `-D` 怎麼用見 [[05-SSH-隧道與埠轉發]]，本篇只講伺服器端「准不准」。

### `Match` 區塊 ★★★★

可用條件：`User`（可用萬用字元與逗號列表）、`Group`（使用者的**任一**群組）、
`Address`（來源 IP，支援 CIDR 與否定 `!`）、`LocalAddress` / `LocalPort`（多網卡分流）、`All`。
同一行寫多個條件是 **AND**，同一條件用逗號分隔是 **OR**：

```ini
Match Group ssh-admins Address 10.10.0.0/24
    AllowTcpForwarding yes
    PermitOpen 10.10.0.30:3306
```

> [!danger] ★★★★★ 鐵律一：`Match` 一旦出現，到檔案結尾或下一個 `Match` 為止都算它的
> ```ini
> Match User backup                  # ✗ 災難寫法
>     ForceCommand /usr/local/bin/backup-only
> PasswordAuthentication no          # ★★★★★ 變成「只有 backup 才關密碼」！
> AllowGroups ssh-users              # ★★★★★ 全域完全沒有生效
> ```
> 正確做法是**全域設定寫在前面，所有 `Match` 區塊放在檔案最後**。
> ★★★★ 這個錯誤 `sshd -t` **檢查不出來**（語法完全合法）。唯一偵測方法是
> `sudo sshd -T`（不帶 `-C`）—— 看到 `passwordauthentication yes` 就是被吃掉了。

> [!danger] ★★★★ 鐵律二：`Match` 裡只能用「允許的關鍵字」
> `Port`、`ListenAddress`、`UsePAM`、`MaxStartups` 等**不能**放進 Match；可用的包含
> `AllowTcpForwarding`、`AllowAgentForwarding`、`AllowGroups`、`AllowUsers`、
> `AuthenticationMethods`、`AuthorizedKeysFile`、`Banner`、`ChrootDirectory`、`ClientAlive*`、
> `DenyUsers`、`ForceCommand`、`GatewayPorts`、`KbdInteractiveAuthentication`、`LogLevel`、
> `MaxAuthTries`、`PasswordAuthentication`、`PermitOpen`、`PermitRootLogin`、`PermitTTY`、
> `PubkeyAuthentication`、`X11Forwarding`。放錯 `sshd -t` 會抓出來：
> `Directive 'Port' is not allowed within a Match block`。

★★★★ **鐵律三：`Match` 內的設定不受「第一個值勝出」保護** —— 它是連線時評估的第二層，會覆蓋全域值。
`sshd -T`（不帶 `-C`）看到的乾淨結果**不代表實際連線時是那樣**，一定要用 `-C` 逐一驗證每種角色：

```bash
$ sudo sshd -T -C user=ops01,host=pc01,addr=10.20.0.9 | grep -E '^(allowtcpforwarding|permitrootlogin)'
allowtcpforwarding no
permitrootlogin no
$ sudo sshd -T -C user=admin,host=mgmt01,addr=10.10.0.5 | grep -E '^(allowtcpforwarding|permitopen)'
allowtcpforwarding yes
permitopen 10.10.0.30:3306
$ sudo sshd -T -C user=backup,host=nas01,addr=10.10.0.40 | grep -E '^(forcecommand|permittty)'
forcecommand /usr/local/bin/backup-only
permittty no
```

★★★ `ChrootDirectory` + `ForceCommand internal-sftp` 的完整做法（目錄擁有者必須是 root、
目錄不能可寫等細節）在 [[06-SFTP-與受限使用者]]，本篇只說明這兩個指令可以放在 Match 裡。

### Banner 與 UsePAM ★★★★

機關資安規範（以及 TWGCB、CIS）要求登入前顯示「未經授權存取之告示」，
理由是**法律上的「已明確告知」**，事後追訴時是必要證據。

```bash
$ sudo tee /etc/issue.net >/dev/null <<'EOF'
******************************************************************
  本系統為 XX 機關所有，僅供授權人員因公使用。
  使用者之所有操作將被記錄並定期稽核。
  未經授權之存取、使用或破壞行為，將依相關法規追究法律責任。
******************************************************************
EOF
$ sudo chmod 644 /etc/issue.net && echo 'Banner /etc/issue.net' \
    | sudo tee -a /etc/ssh/sshd_config.d/50-gov-baseline.conf && sudo sshd -t && sudo systemctl reload ssh
```

`/etc/issue` 由 `getty` 在本機 tty 登入**前**顯示、**`/etc/issue.net`** 由 sshd 的 `Banner` 在
★★★★ **SSH 認證前**顯示、`/etc/motd` 由 `pam_motd` 在登入**成功後**顯示。
★★★★ 稽核要的是**認證前**的告示，所以是 `/etc/issue.net`；放在 motd 等於
「登入成功之後才告訴他不准登入」，形同虛設。
★★★ Banner 內**不要**放系統版本、主機名、機關內部代號 —— 那是免費送給攻擊者的偵察情報，
而 Ubuntu 預設 `/etc/issue.net` 的內容就是版本號，**一定要覆蓋掉**。

**`UsePAM yes` 不能關 ★★★★**：關掉會一併失效 `pam_faillock` 帳號鎖定、密碼過期強制、
`limits.conf`、`pam_time` 登入時段限制、2FA 模組，**以及 `wtmp` 登入紀錄** —— 
`last`、`lastlog` 查不到人，**稽核軌跡直接斷掉**。

### 日誌 ★★★★

journald 用 `sudo journalctl -t sshd -f`（★★★★ socket 模式下用 `-t` 才不會漏），
rsyslog 的 `/var/log/auth.log` 好 grep、好餵第三方工具但**沒裝 rsyslog 就不存在**。

**`LogLevel VERBOSE`：稽核追人的唯一線索 ★★★★** —— 預設 `INFO` 只有 `Accepted publickey ...` 一行，
`VERBOSE` 會額外記錄金鑰比對過程：

```text
sshd[1421]: Postponed publickey for admin from 10.10.0.5 port 51240 ssh2 [preauth]
sshd[1421]: Found matching ED25519 key: SHA256:9Xk4mZ...     # ★★★★ 稽核追人靠這行
sshd[1421]: Accepted publickey for admin from 10.10.0.5 port 51240 ssh2: ED25519 SHA256:9Xk4mZ...
```

多人共用一個 `ops` 帳號時（很常見，雖然不該），INFO 只告訴你「有人用 ops 登入」，**金鑰指紋才能
告訴你是誰**：

```bash
$ sudo ssh-keygen -lf /home/ops/.ssh/authorized_keys
256 SHA256:9Xk4mZ... admin@notebook (ED25519)
256 SHA256:pQ7wLn... ops01@pc01 (ED25519)
$ sudo journalctl -t sshd --since '7 days ago' \
    | grep -oP 'Failed password for .* from \K[0-9.]+' | sort | uniq -c | sort -rn | head -3
   4812 45.148.10.7
   1903 193.32.162.44
     22 10.20.0.99        # ★★★ 內網也有？這台可能已經被打進來了，要查
```

> [!warning] ★★★ `VERBOSE` 會讓日誌量變大，一定要配輪替
> 對外主機一天可能長好幾百 MB 塞爆 `/var`。至少設 journald 上限並確認 `auth.log` 有輪替：
> ```bash
> printf '[Journal]\nSystemMaxUse=2G\nMaxRetentionSec=90day\n' \
>   | sudo tee /etc/systemd/journald.conf.d/50-limits.conf && sudo systemctl restart systemd-journald
> ```
> ★★★★ 稽核通常要求保存 6 個月以上，本機留不住就送集中日誌（[[19-日誌系統]]、[[02-日誌集中與輪替]]）。
> ★★★ **不要**用 `LogLevel DEBUG` 當常態設定 —— 官方手冊明確警告它違反使用者隱私。
> 自動封鎖（fail2ban）見 [[05-Fail2ban入侵防護]]，本篇不重複。

★★ 演算法設定（`KexAlgorithms` / `Ciphers` / `MACs` / `PubkeyAcceptedAlgorithms`）的建議清單、
`ssh-audit` 掃描、2FA、SSH CA **全部在 [[07-SSH-安全強化]]**；本篇只教你怎麼查目前用的是什麼：
`sudo sshd -T | grep -Ei '^(kexalgorithms|ciphers|macs)'`。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照 ★★★★
> 五個地方跟 Ubuntu 不一樣，每一個都會咬人。
>
> **① 服務名是 `sshd` 不是 `ssh`**，而且 RHEL 9 雖有 `sshd.socket` 但**預設 disabled**，
> 走傳統常駐 service，所以 `sshd_config` 的 `Port` / `ListenAddress` **是有效的**。
> ```bash
> $ sudo systemctl reload sshd; systemctl is-enabled sshd.socket
> disabled
> ```
>
> **② ★★★★★ `update-crypto-policies` 會蓋掉你在 sshd_config 寫的演算法設定**
> ```bash
> $ grep -n CRYPTO_POLICY /etc/sysconfig/sshd; update-crypto-policies --show
> 8:CRYPTO_POLICY=
> DEFAULT
> ```
> 它把 `/etc/crypto-policies/back-ends/opensshserver.config` 的參數**以命令列選項形式**塞給 sshd，
> 而命令列優先於設定檔 —— **你寫的 `Ciphers` / `MACs` 完全不會生效**。兩種解法：
> ```bash
> sudo update-crypto-policies --set FUTURE && sudo systemctl reload sshd   # A 用系統政策（建議）
> sudo sed -i 's/^CRYPTO_POLICY=/#CRYPTO_POLICY=/' /etc/sysconfig/sshd     # B 讓 sshd_config 說了算
> sudo systemctl restart sshd
> ```
> ★★★★ 選 B 等於這台脫離全機政策，要在變更紀錄寫清楚原因。
>
> **③ ★★★★ 改埠一定要先過 SELinux**（沒做的症狀是「`sshd -t` 過了、設定也對，就是起不來」）
> ```bash
> $ sudo dnf install -y policycoreutils-python-utils
> $ sudo semanage port -a -t ssh_port_t -p tcp 2222; sudo semanage port -l | grep ssh_port_t
> ssh_port_t                     tcp      2222, 22
> ```
> `sudo ausearch -m avc -ts recent | grep sshd` 會看到 `avc: denied { name_bind } ... src=2222`，
> 見 [[07-SELinux與AppArmor]]。
>
> **④ 防火牆是 firewalld 不是 ufw**：`sudo firewall-cmd --permanent --add-port=2222/tcp` 後
> `--reload`，見 [[04-防火牆-firewalld]]（Ubuntu 側是 [[02-防火牆-ufw基礎與實務]]）。
>
> **⑤ 日誌在 `/var/log/secure`**，journal 用 `journalctl -u sshd -f`。
> ★★ RHEL 9 的 `sshd_config` 一樣有 `Include` 在檔首、底下有 `50-redhat.conf`，
> **「第一個值勝出」的規則跟 Ubuntu 完全一樣**，同樣要靠 `sshd -T` 驗證。

## 完整實戰範例

### 情境

一台剛用 Ubuntu 24.04 Server ISO 裝好的伺服器 `srv-app01`（管理 IP `10.10.0.20`）：
密碼登入開著、root 可用金鑰登入、埠轉發全開、沒有 Banner、沒有逾時。
**目標是套用機關基準，而且全程不能把自己鎖在外面。** 產出四樣東西：基準設定檔
`50-gov-baseline.conf`、`sshd-apply`（備份→檢查→佈署回滾 timer→reload）、
`sshd-confirm`（驗證成功後取消回滾）、`sshd-rollback`（立即還原，timer 到期也是呼叫它）。

### 第一步：前置檢查（★★★★★ 不可略過）

```bash
$ tmux new -s sshd-work                      # ① 保留這條 session
$ sudo groupadd -f ssh-users && sudo usermod -aG ssh-users "$(logname)"
$ id "$(logname)" | grep -q '(ssh-users)' && echo "★ OK 你在群組裡" || echo "★★★★★ 停手"
★ OK 你在群組裡
$ sudo awk '{print FILENAME": "$3}' /home/*/.ssh/authorized_keys 2>/dev/null
/home/admin/.ssh/authorized_keys: admin@notebook      # ③ 確認有金鑰可登入
$ sudo install -d -m 0700 /var/backups/sshd
```

④ 另外**自行到 iDRAC / PVE console 登入一次**，確認頻外管理真的能用。

### 第二步：基準設定檔

```bash
sudo tee /etc/ssh/sshd_config.d/50-gov-baseline.conf >/dev/null <<'EOF'
# 機關 SSH 基準  ★★★★★ 由組態管理派送，請勿手動編輯本機副本
# 驗證：sudo sshd -T  /  sudo sshd -T -C user=admin,host=x,addr=10.10.0.5
ListenAddress 10.10.0.20               # ★★★★ socket 啟動模式下這兩行無效，要改 ssh.socket
AddressFamily inet
PermitRootLogin no
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no        # ★★★★★ 少了這行，密碼登入其實沒關掉
PermitEmptyPasswords no
UsePAM yes                             # ★★★★ 關掉會壞掉帳號鎖定與 wtmp 紀錄
MaxAuthTries 3
MaxSessions 10
MaxStartups 10:30:60
LoginGraceTime 30
AllowGroups ssh-users                  # ★★★★ 用群組不用帳號
DenyUsers root
ClientAliveInterval 300                # ★★★★ 300 × 3 = 900 秒，符合「閒置 15 分鐘登出」
ClientAliveCountMax 3
TCPKeepAlive yes
AllowTcpForwarding no
AllowAgentForwarding no
AllowStreamLocalForwarding no
GatewayPorts no
X11Forwarding no
PermitTunnel no
PermitUserEnvironment no               # ★★★★★ yes 會讓使用者能注入 LD_PRELOAD
UseDNS no                              # ★★★ 開著會讓登入卡 20~30 秒
LogLevel VERBOSE                       # ★★★★ 稽核要靠它記錄金鑰指紋
Banner /etc/issue.net
PrintLastLog yes
# ★★★★★ Match 一律放檔案最後，否則會把後面所有設定都吃進條件
Match Group ssh-admins Address 10.10.0.0/24
    AllowTcpForwarding yes
    PermitOpen 10.10.0.30:3306 10.10.0.31:5432
Match User backup
    ForceCommand /usr/local/bin/backup-only
    PermitTTY no
    AllowTcpForwarding no
EOF
sudo chmod 0644 /etc/ssh/sshd_config.d/50-gov-baseline.conf
```

### 第三步：`sshd-rollback` —— 先寫回滾，再寫套用 ★★★★★

**順序很重要**：回滾腳本必須先存在且可執行，`sshd-apply` 才能安全地引用它。

```bash
sudo tee /usr/local/bin/sshd-rollback >/dev/null <<'EOF'
#!/usr/bin/env bash
# sshd-rollback —— 立即還原最近一次備份的 SSH 設定並 reload
# ★★★★★ 這支也是自動回滾 timer 的執行目標，必須絕對可靠：不依賴環境變數、失敗時大聲留日誌
set -euo pipefail
BACKUP_DIR=/var/backups/sshd; POINTER="${BACKUP_DIR}/LATEST"
log() { logger -t sshd-rollback -p auth.warning -- "$*"; echo "[sshd-rollback] $*" >&2; }
die() { log "★★★★★ 還原失敗：$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "必須以 root 執行"
[ -f "$POINTER" ]    || die "找不到備份指標 $POINTER"
SNAP="$(cat "$POINTER")"; [ -f "$SNAP" ] || die "備份檔不存在：$SNAP"

log "開始還原 $SNAP"
# ★★★★ 先把問題設定也存一份，事後才追得到「當時到底改了什麼」
FAILED="${BACKUP_DIR}/failed-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "$FAILED" -C / etc/ssh/sshd_config etc/ssh/sshd_config.d 2>/dev/null || true
log "問題設定已保留於 $FAILED"

rm -rf /etc/ssh/sshd_config.d    # ★★★★★ 先清空再解壓，否則新增的檔案不會被還原掉
tar -xzf "$SNAP" -C / || die "解壓 $SNAP 失敗"
sshd -t || die "還原後語法仍有誤，未 reload —— 請立刻用 console 進入處理"

if systemctl is-active --quiet ssh.socket; then     # ★★★★ 兩種模式重載方式不同
    systemctl restart ssh.socket || die "restart ssh.socket 失敗"; log "已 restart ssh.socket"
else
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || die "reload 失敗"
    log "已 reload ssh"
fi
sshd -T | grep -Ei '^(port|permitrootlogin|passwordauthentication|allowgroups)' \
    | while read -r l; do log "  $l"; done
log "★ 還原完成"
EOF
sudo chmod 0755 /usr/local/bin/sshd-rollback
```

```bash
$ sudo bash -n /usr/local/bin/sshd-rollback && echo "★ rollback 腳本語法 OK"
★ rollback 腳本語法 OK
```

### 第四步：`sshd-apply`

```bash
sudo tee /usr/local/bin/sshd-apply >/dev/null <<'EOF'
#!/usr/bin/env bash
# sshd-apply —— 安全套用 SSH 設定：備份 → 語法檢查 → 語意檢查 → 回滾 timer → reload
# 用法：sudo sshd-apply [回滾寬限時間，預設 5m]
set -euo pipefail
BACKUP_DIR=/var/backups/sshd; POINTER="${BACKUP_DIR}/LATEST"
ROLLBACK_UNIT=sshd-rollback; GRACE="${1:-5m}"; STAMP="$(date +%Y%m%d-%H%M%S)"
ok()   { printf '\033[32m✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m▲ %s\033[0m\n' "$*"; }
step() { printf '\n\033[1m── %s ──\033[0m\n' "$*"; }
die()  { printf '\033[31m✘ %s\033[0m\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "請用 sudo 執行"
step "0/6 前置檢查"
command -v systemd-run >/dev/null || die "找不到 systemd-run"
[ -x /usr/local/bin/sshd-rollback ] || die "缺少 /usr/local/bin/sshd-rollback，先建立它"
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo root)}"
if grep -rqs '^AllowGroups' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/; then
    GRP="$(grep -rhs '^AllowGroups' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ | awk '{print $2}' | head -1)"
    id -nG "$REAL_USER" | tr ' ' '\n' | grep -qx "$GRP" \
        || die "★★★★★ $REAL_USER 不在 AllowGroups 群組 $GRP 裡，套用後你會被鎖在外面"
    ok "$REAL_USER 在 $GRP 群組中"
fi
step "1/6 備份現有設定"
install -d -m 0700 "$BACKUP_DIR"; SNAP="${BACKUP_DIR}/sshd-${STAMP}.tar.gz"
tar -czf "$SNAP" -C / etc/ssh/sshd_config etc/ssh/sshd_config.d 2>/dev/null \
    || die "備份失敗，中止（沒有備份就不准改）"
echo "$SNAP" > "$POINTER"
sshd -T 2>/dev/null | sort > "${BACKUP_DIR}/effective-${STAMP}.txt" || true
ok "備份：$SNAP"
step "2/6 語法檢查（sshd -t）"
sshd -t || die "★★★★★ 語法有誤，已中止，現行設定未變動"
ok "語法正確"
step "3/6 語意檢查（sshd -T）"
EFF="$(sshd -T)"
val()   { printf '%s\n' "$EFF" | awk -v k="$1" '$1==k {print $2; exit}'; }
check() { local g; g="$(val "$1")"; [ "$g" = "$2" ] && ok "$1 = $g" || warn "$1 = ${g:-<未設定>}（期望 $2）"; }
check passwordauthentication no; check kbdinteractiveauthentication no
check permitrootlogin no;        check permituserenvironment no
check usepam yes;                check loglevel VERBOSE
# ★★★★★ 三種認證全關 = 誰都進不來，唯一必須硬擋的組合
if [ "$(val pubkeyauthentication)" = no ] && [ "$(val passwordauthentication)" = no ] \
   && [ "$(val kbdinteractiveauthentication)" = no ]; then
    die "★★★★★ 三種認證方式全部關閉，套用後沒有人能登入，已中止"
fi
step "4/6 佈署自動回滾 timer（${GRACE} 後自動還原）"
systemctl stop "${ROLLBACK_UNIT}.timer" 2>/dev/null || true
systemd-run --on-active="$GRACE" --unit="$ROLLBACK_UNIT" /usr/local/bin/sshd-rollback >/dev/null
systemctl list-timers "${ROLLBACK_UNIT}.timer" --no-pager | sed -n 2p
ok "回滾保險已上膛"
step "5/6 套用設定"
if systemctl is-active --quiet ssh.socket; then
    warn "★★★★ socket 啟動模式：Port/ListenAddress 由 ssh.socket 決定"
    systemctl restart ssh.socket; ok "已 restart ssh.socket"
else
    systemctl reload ssh 2>/dev/null || systemctl reload sshd; ok "已 reload（現有連線未中斷）"
fi
step "6/6 請人工驗證"
cat <<'MSG'
★★★★★ 這條 session 不要關！請「另外開一個乾淨終端機」執行：
    ssh -o ControlPath=none -o ControlMaster=no <帳號>@<本機IP> 'echo NEW-SESSION-OK'
看到 NEW-SESSION-OK 後立刻回到這裡執行： sudo sshd-confirm
若未執行 sshd-confirm，設定會在寬限時間到期後自動還原。
MSG
EOF
sudo chmod 0755 /usr/local/bin/sshd-apply
```

### 第五步：`sshd-confirm`

```bash
sudo tee /usr/local/bin/sshd-confirm >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "請用 sudo 執行" >&2; exit 1; }
if systemctl is-active --quiet sshd-rollback.timer; then
    systemctl stop sshd-rollback.timer; echo "✔ 回滾 timer 已取消，設定正式生效"
else
    echo "▲ 沒有進行中的回滾 timer（可能已到期執行、或本來就沒佈署）"
fi
logger -t sshd-confirm -p auth.notice -- "SSH 設定變更已由 $(logname 2>/dev/null || echo root) 確認"
sshd -T | grep -Ei '^(port|listenaddress|permitrootlogin|passwordauth|kbdinteractive|allowgroups|loglevel|clientalive)'
EOF
sudo chmod 0755 /usr/local/bin/sshd-confirm
```

### 第六步：實際執行

```bash
$ sudo sshd-apply 5m
── 0/6 前置檢查 ──       ✔ admin 在 ssh-users 群組中
── 1/6 備份現有設定 ──   ✔ 備份：/var/backups/sshd/sshd-20260828-091203.tar.gz
── 2/6 語法檢查 ──       ✔ 語法正確
── 3/6 語意檢查 ──       ✔ passwordauthentication = no ／ kbdinteractiveauthentication = no
                         ✔ permitrootlogin = no ／ permituserenvironment = no ／ loglevel = VERBOSE
── 4/6 佈署自動回滾 timer（5m 後自動還原）──
Fri 2026-08-28 09:17:03 CST 4min 58s - - sshd-rollback.timer sshd-rollback.service
✔ 回滾保險已上膛
── 5/6 套用設定 ──       ▲ ★★★★ socket 模式 → ✔ 已 restart ssh.socket
── 6/6 請人工驗證 ──     ★★★★★ 這條 session 不要關！...
```

```bash
$ ssh -o ControlPath=none admin@10.10.0.20 'echo NEW-SESSION-OK'    # 從另一台機器驗證
******************************************************************
  本系統為 XX 機關所有，僅供授權人員因公使用。
******************************************************************
NEW-SESSION-OK
$ sudo sshd-confirm                                                 # 回到原 session 確認
✔ 回滾 timer 已取消，設定正式生效
port 22 ／ listenaddress 10.10.0.20 ／ permitrootlogin no ／ allowgroups ssh-users
passwordauthentication no ／ kbdinteractiveauthentication no ／ loglevel VERBOSE
```

### 驗收檢查表 ★★★★★

| # | 檢查項 | 指令 | 預期結果 |
| --- | --- | --- | --- |
| 1 | ★★★★★ 語法正確 | `sudo sshd -t; echo $?` | `0` |
| 2 | ★★★★★ 密碼登入真的關了 | `sudo sshd -T \| grep -E 'password\|kbdinter'` | 兩行都是 `no` |
| 3 | ★★★★★ 至少一種認證可用 | `sudo sshd -T \| grep '^pubkeyauth'` | `pubkeyauthentication yes` |
| 4 | ★★★★ root 不能登入 | `sudo sshd -T \| grep '^permitrootlogin'` | `permitrootlogin no` |
| 5 | ★★★★ 白名單群組正確 | `sudo sshd -T \| grep '^allowgroups'` | `allowgroups ssh-users` |
| 7 | ★★★★ Match 對維運人員生效 | `sudo sshd -T -C user=admin,host=m,addr=10.10.0.5 \| grep '^allowtcp'` | `allowtcpforwarding yes` |
| 8 | ★★★★ Match 對一般使用者不生效 | `sudo sshd -T -C user=ops01,host=p,addr=10.20.0.9 \| grep '^allowtcp'` | `allowtcpforwarding no` |
| 9 | ★★★★ 服務在監聽 | `sudo ss -lntp \| grep ':22 '` | 有 `LISTEN` 一列 |
| 10 | ★★★★★ 新連線可登入 | `ssh -o ControlPath=none admin@10.10.0.20 'echo OK'` | `OK` |
| 11 | ★★★★★ 舊連線沒被踢掉 | 在原 session 執行 `uptime` | 正常輸出 |
| 12 | ★★★★ Banner 有出現、密碼登入被拒 | `ssh -o PubkeyAuthentication=no admin@10.10.0.20` | 顯示警語後 `Permission denied (publickey).` |
| 14 | ★★★★★ 回滾 timer 已取消 | `systemctl is-active sshd-rollback.timer` | `inactive` |

**12 項全過才算完成。** 建議把這張表做成 `sshd-verify` 腳本納入
[[02-基準設定與範本化]] 的檢核流程與 [[04-TWGCB-Linux本機導入]] 的檢測項目。

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 改完 `restart` 後所有人都連不進去，`status` 顯示 `failed` | 語法錯誤／`ListenAddress` 綁到不存在的位址／埠被佔用 | console 進入 → `sudo sshd -t` 看錯在哪一行 → 修正 → `restart`。下次改用 `reload` |
| ★★★★★ `PasswordAuthentication no` 設好了還是能用密碼登入 | `KbdInteractiveAuthentication` 預設 `yes`，搭 `UsePAM yes` 走 keyboard-interactive 一樣驗密碼 | 補 `KbdInteractiveAuthentication no`，`sshd -T` 確認**兩行都是 no** |
| ★★★★★ 在主檔末尾改的設定完全沒作用 | `Include` 在第 1 行且「第一個值勝出」，被 `50-cloud-init.conf` 蓋掉 | 改寫到 `sshd_config.d/` 並取**字典序在前**的檔名；一律以 `sshd -T` 驗證 |
| ★★★★★ 設了 `AllowGroups` 之後自己也進不去 | 執行者不在該群組，或建群組後忘了 `usermod -aG` | console 進入 → `usermod -aG ssh-users <你>` → `getent group` 確認；新連線即生效 |
| ★★★★ 改了 `Port 2222`，`ss` 顯示還在聽 22 且 Process 是 `systemd` | Ubuntu 24.04 socket 啟動，`Port` 不被使用 | `systemctl edit ssh.socket` 寫空的 `ListenStream=` 再寫新埠 → `daemon-reload` → `restart ssh.socket` |
| ★★★★ 改完 `ssh.socket` 後 22 和 2222 **同時**在聽 | 少寫空的 `ListenStream=`，systemd 把新值**追加**上去 | 在 drop-in `[Socket]` 底下第一行補 `ListenStream=`（等號後不接東西） |
| ★★★★ 全域寫了 `PasswordAuthentication no`，`sshd -T` 卻是 `yes` | 該行被寫在某個 `Match` **之後**，變成只對那個條件生效 | 全域設定移到第一個 `Match` **之前**；用 `sudo sshd -T`（不帶 `-C`）確認 |
| ★★★★ RHEL 上 `sshd_config` 寫的 `Ciphers` 完全沒生效 | `/etc/sysconfig/sshd` 的 `CRYPTO_POLICY=` 以命令列參數塞入，優先於設定檔 | `update-crypto-policies --set` 調整，或註解掉該行後 `restart sshd` |
| ★★★★ RHEL 上改埠後起不來，`audit.log` 有 `avc: denied { name_bind }` | SELinux 沒把新埠標成 `ssh_port_t` | `semanage port -a -t ssh_port_t -p tcp 2222` 後再啟動 |

### 排查步驟

**【1】先確定「服務到底有沒有在聽」**

```bash
$ sudo ss -lntp | grep -E ':(22|2222)\s'
LISTEN 0 4096 *:22 *:* users:(("systemd",pid=1,fd=93))
```

- `users:(("sshd",...))` → 傳統 service 模式，服務正常，問題在**設定或防火牆**，跳【4】
- `users:(("systemd",...))` → **socket 啟動模式**，`Port` 不會生效，跳【3】
- **什麼都沒有** → 服務沒起來，跳【2】

**【2】服務起不來 —— 看語法與啟動日誌**

```bash
$ sudo sshd -t
/etc/ssh/sshd_config.d/50-gov-baseline.conf line 30: Directive 'Port' is not allowed within a Match block
```

語法沒問題還是起不來就看 `sudo journalctl -u ssh -u ssh.socket -n 40 --no-pager`：

| 看到什麼 | 問題在哪 |
| --- | --- |
| `Address already in use` | ★★★★ 埠被佔用，或 socket 與 service 同時在跑 |
| `Bind to port 22 on 10.10.0.20 failed: Cannot assign requested address` | ★★★★★ `ListenAddress` 綁到還不存在的 IP |
| `error: Could not load host key` | ★★★★ host key 遺失或權限錯，跑 `ssh-keygen -A` |
| `Permission denied` 相關 | ★★★ 檔案權限（見【6】）或 SELinux（見【8】） |

**【3】socket 模式下確認實際監聽的埠**

```bash
$ systemctl cat ssh.socket | grep -A6 '\[Socket\]'
[Socket]
ListenStream=22
# /etc/systemd/system/ssh.socket.d/override.conf
[Socket]
ListenStream=
ListenStream=2222        # ★★★★ 前面有空的那行才是對的
```

看到**兩個**有值的 `ListenStream=` → 少寫空行，埠沒真的換掉；
只看到 `ListenStream=22` → drop-in 沒被讀到，檢查有沒有跑 `systemctl daemon-reload`。

**【4】確認「生效值」而不是「檔案內容」**

```bash
$ sudo sshd -T | grep -Ei '^(port|listenaddress|allowgroups|passwordauthentication|kbdinteractive)'
passwordauthentication yes      # ← 跟你寫的不一樣就跳【5】；一樣但特定人進不來就跳【7】
```

**【5】找出這個關鍵字到底被誰設定了**

```bash
$ grep -rn -i 'passwordauthentication' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/
/etc/ssh/sshd_config:120:PasswordAuthentication no                       # 你加的，主檔末尾
/etc/ssh/sshd_config.d/50-cloud-init.conf:1:PasswordAuthentication yes   # ★★★★★ 這個贏
$ awk '/^Match/{m=1} m && /^[A-Za-z]/ {print FILENAME": "FNR": "$0}' /etc/ssh/sshd_config.d/*.conf | head
50-gov-baseline.conf: 44: Match Group ssh-admins Address 10.10.0.0/24
```

★★★★ 若第一個 `Match` 之後還有**沒縮排的全域設定**，那些設定已經變成條件專屬。

**【6】權限問題（金鑰登入失敗但沒有明確錯誤）**

```bash
$ sudo ls -ld /home/admin /home/admin/.ssh; sudo journalctl -t sshd -n 30 | grep -i 'bad ownership'
drwxr-xr-x 5 admin admin 4096 Aug 28 09:00 /home/admin
drwx------ 2 admin admin 4096 Aug 28 09:00 /home/admin/.ssh
Authentication refused: bad ownership or modes for directory /home/admin
```

★★★★ 只要 `.ssh` 或家目錄**對 group/other 可寫**，sshd 就拒絕使用 authorized_keys（`StrictModes yes`），
而客戶端只看得到 `Permission denied (publickey)`。修正：
`sudo chmod 755 /home/admin; sudo chmod 700 /home/admin/.ssh; sudo chmod 600 /home/admin/.ssh/authorized_keys`

**【7】驗證「這個人實際會拿到什麼」**

```bash
# 伺服器端開一個 debug sshd 在別的埠，直接看拒絕原因（客戶端配 ssh -vvv -p 2222）
$ sudo /usr/sbin/sshd -D -d -p 2222 -e
debug1: user ops01 matched 'Group ssh-users' at line 25
Accepted publickey for ops01 from 10.20.0.9 port 51299 ssh2: ED25519 SHA256:pQ7wLn...
```

看到 `User ops01 not allowed because none of user's groups are listed in AllowGroups`
就知道是群組問題，不是金鑰問題。★★★★ 這比猜快一百倍。

**【8】防火牆與 SELinux／AppArmor**

```bash
$ sudo ufw status verbose | grep -E '22|2222'          # Ubuntu
22/tcp                     ALLOW IN    10.10.0.0/24
$ sudo firewall-cmd --list-all | grep ports            # RHEL
$ sudo ausearch -m avc -ts recent | grep sshd          # RHEL SELinux
```

★★★ 客戶端 `Connection timed out` 通常是**防火牆／路由**；`Connection refused` 表示封包有到
但**沒人在聽**（服務沒起來或埠不對）。這兩個訊息的區別就是排查方向的分水嶺。

## 安全性注意事項

> [!danger] ★★★★★ 絕對禁止：`PermitRootLogin yes` 搭配密碼認證
> 對外主機開這組設定，通常**幾小時內**就會看到每秒數次的 `Failed password for root`。
> root 帳號名稱是公開的，攻擊者只要猜密碼；一旦猜中**整台機器直接失守，
> 且沒有任何操作留下「是誰做的」**。一律 `PermitRootLogin no`，
> 需要提權用一般帳號 + `sudo`（有完整稽核軌跡）。

> [!danger] ★★★★★ 絕對禁止：只設 `PasswordAuthentication no` 就宣稱關閉密碼登入
> `KbdInteractiveAuthentication` 沒關的話門根本沒關，而你的稽核報告已經勾了
> 「已停用密碼認證」。**這是實質資安缺失加上不實陳報。** 驗證只認 `sudo sshd -T`，兩行都要 `no`。

> [!danger] ★★★★★ 絕對禁止：`PermitUserEnvironment yes` 與 `GatewayPorts yes`
> 前者讓任何能寫 `~/.ssh/environment` 的使用者在登入時注入 `LD_PRELOAD=/tmp/evil.so`、
> `PATH=/tmp/bin:$PATH` —— 該使用者接著執行 setuid 程式或被管理者 `su` 過去，
> 就是一條**本機提權路徑**（要設環境變數請用 `SetEnv` / `AcceptEnv` 白名單）。
> 後者讓 `ssh -R 8080:內網DB:3306` 綁到 **0.0.0.0**，任何人連得到這台的 8080
> 就直達你的內網資料庫，**繞過所有防火牆規則**，而且防火牆日誌完全看不出異常。

> [!danger] ★★★★ 絕對禁止：跳板機允許 `AllowAgentForwarding yes`、或關掉 `UsePAM`
> 前者讓跳板機的 root（或任何被入侵的程序）直接使用轉發過來的 agent socket，
> **以你的身分登入你所有能登入的機器**，私鑰沒外洩但效果一樣、事後追不到 ——
> 用 `ProxyJump` 取代（[[03-SSH-客戶端設定檔]]）。後者會連帶失效 `pam_faillock` 帳號鎖定、
> 密碼過期強制、`limits.conf`，**以及 `wtmp` 登入紀錄** —— `last`、`lastlog` 查不到人，
> **稽核軌跡直接斷掉**，機關屬重大缺失。

> [!warning] ★★★★ 機關情境的四個必辦
> 1. **法定告示**：`Banner /etc/issue.net`，只放法律警語，不放版本與主機資訊。
> 2. **可稽核性**：`LogLevel VERBOSE` 記錄金鑰指紋；保存期依規定（常見 6 個月以上），
>    本機留不住就送集中日誌（[[19-日誌系統]]、[[02-日誌集中與輪替]]）。
> 3. **最小權限**：`AllowGroups ssh-users` + `DisableForwarding yes`，需要的人用 `Match` 個別放行，
>    並在變更紀錄寫明理由（[[08-系統強化與稽核]]、[[09-資安稽核與符合性檢核]]）。
> 4. **組態基準**：TWGCB 對 SSH 有明確項目（禁止 root 登入、閒置逾時、`PermitEmptyPasswords no`、
>    `LogLevel` 等），導入與檢測見 [[04-TWGCB-Linux本機導入]] 與 [[07-TWGCB-Linux檢測與符合性報告]]。

> [!warning] ★★★★ 改埠不是安全措施，是降噪措施；備份與變更紀錄才是基本功
> 22 改 2222 能讓自動掃描的雜訊少 95%、日誌乾淨很多 —— 這才是它的價值。但它**不能取代**
> 金鑰認證、`AllowGroups`、fail2ban；針對性攻擊 `nmap -p-` 一掃就找到，
> 而且監控、備份、CI/CD、跳板機設定全部要跟著改。**先做認證強化，再考慮改埠。**
> ★★★ 另外每次改動前帶時間戳備份是最低標準（本篇 `sshd-apply` 已做成 tar 快照），
> 更好的是把 `/etc/ssh/sshd_config.d/` 納入版控或組態管理 —— 見 [[02-基準設定與範本化]]
> 與 [[03-備份策略與還原演練]]。

## 速查表

### 驗證指令與不鎖門 SOP ★★★★★

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `sudo sshd -t` ／ `sudo sshd -t -f <檔>` | 語法檢查（沒輸出就是過）／檢查候選檔 | ★★★★★ |
| `sudo sshd -T` | 印出**全域實際生效**的所有設定 | ★★★★★ |
| `sudo sshd -T -C user=u,host=h,addr=a` | 模擬某人連線，驗證 Match 結果 | ★★★★ |
| `sudo /usr/sbin/sshd -D -d -p 2222 -e` | 前景 debug，看完整認證判斷過程 | ★★★★ |
| `sudo systemctl reload ssh` | 重載設定，**不斷現有連線** | ★★★★★ |
| `sudo systemd-run --on-active=5m --unit=sshd-rollback <腳本>` | 自動回滾保險絲 | ★★★★★ |
| `systemctl stop sshd-rollback.timer` | 驗證成功後解除保險 | ★★★★★ |

### 關鍵設定項預設值 vs 建議值

| 設定項 | 預設 | 建議 | 星級 |
| --- | --- | --- | --- |
| `PermitRootLogin` | `prohibit-password` | `no` | ★★★★ |
| `PasswordAuthentication` | `yes` | `no` | ★★★★ |
| `KbdInteractiveAuthentication` | **`yes`** | **`no`** | ★★★★★ |
| `PubkeyAuthentication` ／ `PermitEmptyPasswords` | `yes` ／ `no` | `yes` ／ `no` | ★★★★★ |
| `UsePAM` | Ubuntu `yes` | `yes` | ★★★★ |
| `MaxAuthTries` ／ `MaxSessions` ／ `MaxStartups` | `6` ／ `10` ／ `10:30:100` | `3` ／ `10` ／ `10:30:60` | ★★★ |
| `LoginGraceTime` | `120` | `30` | ★★★ |
| `ClientAliveInterval` ／ `CountMax` | `0` ／ `3` | `300` ／ `3` | ★★★★ |
| `UseDNS` | `no` | `no` | ★★★ |
| `AllowTcpForwarding` ／ `AllowAgentForwarding` | `yes` ／ `yes` | `no` ／ `no` | ★★★★ |
| `GatewayPorts` ／ `PermitUserEnvironment` | `no` ／ `no` | `no` ／ `no` | ★★★★★ |
| `X11Forwarding` | `no`（Ubuntu 主檔常設 `yes`） | `no` | ★★★ |
| `LogLevel` ／ `Banner` ／ `AllowGroups` | `INFO` ／ 無 ／ 無 | `VERBOSE` ／ `/etc/issue.net` ／ `ssh-users` | ★★★★ |

### 檔案路徑與平台差異

| 路徑 | 內容 | 星級 |
| --- | --- | --- |
| `/etc/ssh/sshd_config` | 主檔，**不要改** | ★★★★ |
| `/etc/ssh/sshd_config.d/*.conf` | ★★★★★ 設定寫這裡，**檔名數字小的贏** | ★★★★★ |
| `/etc/issue.net` | SSH 認證**前**顯示的 Banner | ★★★★ |
| `/etc/sysconfig/sshd` | ★★★★ RHEL 專有，`CRYPTO_POLICY=` 會蓋掉演算法設定 | ★★★★ |

| 項目 | Ubuntu 24.04 | Rocky / AlmaLinux 9 | 星級 |
| --- | --- | --- | --- |
| 服務名／啟動方式 | `ssh` ／ ★★★★ `ssh.socket` | `sshd` ／ 常駐 service | ★★★★ |
| 改埠 | `systemctl edit ssh.socket` | `Port` + ★★★★ `semanage port` | ★★★★ |
| 演算法 | 寫在 `sshd_config` | ★★★★★ 受 `update-crypto-policies` 控制 | ★★★★★ |
| 防火牆／MAC | `ufw` ／ AppArmor | `firewalld` ／ ★★★★ SELinux | ★★★ |

### 判斷準則

| 症狀 | 先查哪裡 | 星級 |
| --- | --- | --- |
| `Connection refused` | 服務有沒有起來：`ss -lntp` | ★★★★★ |
| `Permission denied (publickey)` | `sshd -T -C` 看該使用者設定 + 家目錄權限 | ★★★★ |
| 設定看起來對但沒生效 | ★★★★★ `sshd -T`，再 `grep -rn` 找誰蓋掉的 | ★★★★★ |
| 密碼還能登入 | `sshd -T \| grep kbdinteractive` | ★★★★★ |

## 練習題

> [!question]- 練習 1：找出「被誰蓋掉」★★★★
> 在測試機執行下列操作，回答：輸出是 `yes` 還是 `no`？為什麼？
> 在**不刪除 `50-test.conf`** 的前提下要怎麼讓它變成 `no`？
> ```bash
> echo 'PasswordAuthentication no' | sudo tee -a /etc/ssh/sshd_config
> printf 'PasswordAuthentication yes\n' | sudo tee /etc/ssh/sshd_config.d/50-test.conf
> sudo sshd -t && sudo systemctl reload ssh && sudo sshd -T | grep -i passwordauth
> ```
>
> ---
> **參考解答**：輸出是 **`passwordauthentication yes`**。因為主檔第 1 行是
> `Include /etc/ssh/sshd_config.d/*.conf`，`50-test.conf` 比主檔末尾那行**更早**被讀到，
> 而規則是**「第一個取得的值勝出」**。不刪它的解法是建一個**字典序更前面**的檔案：
> ```bash
> printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\n' \
>   | sudo tee /etc/ssh/sshd_config.d/10-gov-baseline.conf
> sudo sshd -t && sudo systemctl reload ssh && sudo sshd -T | grep -Ei 'passwordauth|kbdinteractive'
> # → passwordauthentication no / kbdinteractiveauthentication no
> ```
> ★★★★ 順手把 `KbdInteractiveAuthentication` 也關掉，否則密碼登入還是通的。
> 收尾記得 `sudo rm /etc/ssh/sshd_config.d/50-test.conf` 並移除主檔末尾那行。

> [!question]- 練習 2：實測自動回滾 timer ★★★★★
> 在**測試機**上刻意寫一個會把自己鎖在外面的設定，驗證回滾機制真的有效。
>
> ---
> **參考解答**
> ```bash
> # ① 先做一次備份建立 LATEST 指標
> sudo install -d -m 0700 /var/backups/sshd
> sudo tar -czf /var/backups/sshd/sshd-good.tar.gz -C / etc/ssh/sshd_config etc/ssh/sshd_config.d
> echo /var/backups/sshd/sshd-good.tar.gz | sudo tee /var/backups/sshd/LATEST
> # ② 上保險（縮短成 2 分鐘方便觀察）
> sudo systemd-run --on-active=2m --unit=sshd-rollback /usr/local/bin/sshd-rollback
> # ③ 刻意寫一個沒有人在裡面的群組（★★★ 語法完全正確，sshd -t 不會擋）
> printf 'AllowGroups nobody-at-all\n' | sudo tee /etc/ssh/sshd_config.d/99-break.conf
> sudo sshd -t && sudo systemctl reload ssh
> ```
> ④ 從另一個乾淨終端機登入會得到 `Permission denied (publickey).`，伺服器端日誌是
> `User admin ... not allowed because none of user's groups are listed in AllowGroups`。
> ⑤ 等 2 分鐘不要動，到期後再登入應該就通了，`sudo journalctl -t sshd-rollback -n 20` 會看到
> 「開始還原 …／問題設定已保留於 failed-20260828-093012.tar.gz／已 reload ssh」。
> ★★★★★ 重點觀察兩件事：(a) `99-break.conf` 已經不見了（腳本先 `rm -rf` 再解壓），
> (b) 問題設定被保留在 `failed-*.tar.gz`，事後查得到當時到底改了什麼。
> ★★★★ 這題務必在測試機做，且事前確認 console 進得去。

> [!question]- 練習 3：設計並驗證一組 Match 規則 ★★★★
> 需求：全域關閉所有 forwarding 與密碼登入、白名單 `ssh-users`；
> `ssh-admins` 群組**且**來自 `10.10.0.0/24` 可做埠轉發但只能轉到 `10.10.0.30:3306`；
> `deploy` 帳號只能執行 `/usr/local/bin/deploy.sh`、不給 TTY。寫出設定並驗證三種角色。
>
> ---
> **參考解答**
> ```ini
> PasswordAuthentication no
> KbdInteractiveAuthentication no
> AllowGroups ssh-users
> DisableForwarding yes
> Match Group ssh-admins Address 10.10.0.0/24      # ★★★★★ 所有 Match 一定放最後
>     DisableForwarding no
>     AllowTcpForwarding yes
>     PermitOpen 10.10.0.30:3306
> Match User deploy
>     ForceCommand /usr/local/bin/deploy.sh
>     PermitTTY no
> ```
> ```bash
> sudo sshd -t && sudo systemctl reload ssh
> sudo sshd -T -C user=ops01,host=pc01,addr=10.20.0.9   | grep '^allowtcp'    # allowtcpforwarding no
> sudo sshd -T -C user=admin,host=mgmt01,addr=10.10.0.5 | grep '^permitopen'  # permitopen 10.10.0.30:3306
> sudo sshd -T -C user=deploy,host=ci01,addr=10.10.0.60 | grep '^permittty'   # permittty no
> ```
> ★★★★ `admin` 必須**同時**在 `ssh-users`（過全域白名單）**和** `ssh-admins`（過 Match），
> 兩個群組缺一不可 —— 這是最容易漏掉的地方。
> ★★★ `Address` 比對的是**來源 IP**，NAT 之後要用實際看到的位址。

## 小測驗

Q1. 主檔第 1 行是 `Include /etc/ssh/sshd_config.d/*.conf`。你在主檔**最後一行**寫了 `PermitRootLogin no`，而 `50-cloud-init.conf` 裡有 `PermitRootLogin yes`。reload 之後 root 能不能用金鑰登入？為什麼？

Q2. 你設好 `PasswordAuthentication no` 且 `sshd -T` 顯示 `no`，但同事回報他還是能用密碼登入。最可能的原因？用哪條指令證實？

Q3. 這行指令會發生什麼事：`sudo systemctl restart ssh`（設定檔有語法錯誤的情況）？換成 `reload` 又會怎樣？

Q4. Ubuntu 24.04 上改了 `Port 2222` 並 reload，`ss -lntp` 卻顯示還在聽 22 且 `Process` 欄是 `systemd`。診斷與正確解法？

Q5. 你在 `ssh.socket` 的 drop-in 裡只寫 `ListenStream=2222`（沒先寫空的那行）。`ss -lntp` 會看到什麼？為什麼這是資安問題？

Q6. `MaxStartups 10:30:100` 三個數字各代表什麼？使用者回報「有時連得上有時被拒」跟它有什麼關係？

Q7. 下面這段設定有什麼問題？
```ini
Match User backup
    ForceCommand /usr/local/bin/backup-only
PasswordAuthentication no
AllowGroups ssh-users
```

Q8. `sudo sshd -t` 通過了，是不是就代表可以安全 reload？舉一個「語法正確但會把自己鎖在外面」的例子。

Q9. 稽核要求「能追出共用帳號是誰登入的」。要改哪個設定？改完日誌會多出什麼？有什麼副作用要一起處理？

Q10. 在 Rocky Linux 9 上你在 `sshd_config` 寫了 `Ciphers aes256-gcm@openssh.com`，reload 之後 `sshd -T | grep ciphers` 卻是一長串預設值。原因？兩種解法？

> [!question]- 測驗答案
> **Q1.** ★★★★★ **root 可以用金鑰登入** —— `50-cloud-init.conf` 的 `yes` 勝出。
> `man 5 sshd_config` 明文寫著 *the first obtained value will be used* ——**第一個讀到的值勝出**，
> 不是最後一個；`Include` 在主檔第 1 行，所以 `sshd_config.d/` 的內容都比主檔其他行更早被讀到。
> 這跟 Nginx `conf.d`、systemd drop-in 的「後蓋前」直覺完全相反，是本篇最重要的陷阱。
> 驗證：`sudo sshd -T | grep -i permitrootlogin` → `permitrootlogin yes`。
> 正解是把設定寫成 `10-gov-baseline.conf`（字典序在 `50-` 之前），或清掉 `50-cloud-init.conf`。
> 見「觀念說明」與「設定檔治理」。
>
> **Q2.** ★★★★★ 元凶是 **`KbdInteractiveAuthentication`**（預設 `yes`）。它搭配 `UsePAM yes`
> 會走 PAM 的 `pam_unix`，一樣問密碼並驗證，但走的是 `keyboard-interactive` 而非 `password`
> 認證方法，不受 `PasswordAuthentication no` 管轄。證實：
> `sudo sshd -T | grep -Ei 'passwordauthentication|kbdinteractiveauthentication'`，
> 會看到 `kbdinteractiveauthentication yes`。實測
> `ssh -o PubkeyAuthentication=no -o PreferredAuthentications=keyboard-interactive user@host`
> 仍會看到密碼提示；補上 `KbdInteractiveAuthentication no` 後應得到
> `Permission denied (publickey).`。見「認證類」。
>
> **Q3.** ★★★★★ `restart` **先殺掉再啟動**，而啟動時解析設定失敗，sshd 起不來、進入 `failed`
> —— **所有人（包含你）都連不進去**，只剩 console／IPMI 能救。
> `reload` 安全得多：Ubuntu 的 `ssh.service` 有 `ExecReload=/usr/sbin/sshd -t`，**語法檢查沒過
> 就不會送 SIGHUP**，舊設定與現有連線原封不動，你還在線上可以從容修正。
> ★★★★★ 這就是「改 sshd 一律 reload」的理由 —— 不是為了不中斷服務，是為了留住退路。
> 見「觀念說明」與 [[17-systemd服務管理]]。
>
> **Q4.** ★★★★ 這台是 **socket 啟動模式**；`Process` 欄顯示 `systemd` 而非 `sshd` 就是決定性線索
> —— 監聽的是 `ssh.socket`，`sshd_config` 的 `Port` / `ListenAddress` 根本沒被使用
> （`systemctl is-enabled ssh.socket` → `enabled` 可再確認）。
> 解法 A（建議）`systemctl edit ssh.socket` 寫 `[Socket]` + 空的 `ListenStream=` + `ListenStream=2222`，
> 再 `daemon-reload` 與 `restart ssh.socket`；解法 B `disable --now ssh.socket`、刪掉
> `/etc/systemd/system/ssh.service.d/00-socket.conf`、`enable --now ssh.service` 回到傳統模式，
> `Port` 就恢復作用。見「Port 要改在 ssh.socket」。
>
> **Q5.** ★★★★★ 會看到 **22 和 2222 同時 LISTEN**。因為 systemd 的 `ListenStream=` 是**列表型**指令，
> 直接賦值是「追加」而非「取代」，必須先寫一行空的把原值清掉。
> 資安問題在於：你以為埠已換掉，防火牆、監控、fail2ban 都照 2222 設定，**但 22 埠還在對外裸奔**，
> 暴力破解照樣打得進來而且可能沒被監控到，稽核抽查「SSH 服務埠」會直接開缺失。
> 同樣的列表語意也適用 unit 的 `ExecStart=`，見 [[01-systemd-unit撰寫實戰]]。
>
> **Q6.** ★★★ 三個數字是 `start:rate:full`，管的是**未認證連線數**：`10` 以內全接受；
> 超過 10 之後以 **30%**（百分比，不是秒也不是數量）機率隨機拒絕、機率線性上升；
> 到 `100` 全部拒絕。「有時連得上有時被拒」正是**隨機拒絕**的典型症狀，日誌會出現
> `beginning MaxStartups throttling`；常見於跳板機、CI 大量併發、或正被掃描的對外主機。
> 解法是調大（`30:30:200`）並縮短 `LoginGraceTime` 讓未認證連線更快釋放。見「認證類」。
>
> **Q7.** ★★★★★ **`Match` 之後的所有內容都屬於該區塊**，直到檔案結尾或下一個 `Match`。
> 所以那兩行變成「**只有 backup 這個使用者**才關密碼、才需要在 ssh-users 群組」，
> **全域完全沒有這兩項設定** —— 其他所有人的密碼登入都是開著的。
> 致命之處在於 `sudo sshd -t` **完全不會報錯**（語法合法）；偵測方法是
> `sudo sshd -T`（不帶 `-C`），會看到 `passwordauthentication yes`。
> 正確寫法是全域設定移到第一個 `Match` **之前**，所有 `Match` 放在檔案最後。見「Match 鐵律一」。
>
> **Q8.** ★★★★★ **不代表**。`sshd -t` 只驗語法能不能解析，完全不驗語意。三個經典例子：
> (1) `AllowGroups ssh-users` 但你不在該群組 → 服務正常、你進不去；
> (2) `ListenAddress 10.10.0.99`（這台沒這個 IP）→ 重開機後 sshd 起不來；
> (3) `PubkeyAuthentication no` + `PasswordAuthentication no` + `KbdInteractiveAuthentication no`
> → 沒有任何認證方式，誰都登不進來。
> 所以語法檢查之後還要 `sshd -T` 驗生效值、`sshd -T -C` 驗每種角色、`id` 確認自己在群組裡、
> 另一個埠前景試跑、以及自動回滾 timer；本篇 `sshd-apply` 把第 3 種情況做成硬性中止。見「不鎖門 SOP」。
>
> **Q9.** ★★★★ 把 `LogLevel INFO` 改成 **`LogLevel VERBOSE`**。日誌會多出金鑰比對細節，
> 關鍵是 `Found matching ED25519 key: SHA256:9Xk4mZ...` 這行。
> 有了指紋就能用 `ssh-keygen -lf ~/.ssh/authorized_keys` 對回**是哪個人的金鑰**，
> 這是共用帳號情境下**唯一**能追到人的線索。副作用與配套：日誌量明顯變大
> （尤其對外主機被掃描時），必須一起處理 (a) journald 上限 `SystemMaxUse=`、
> (b) `auth.log` 的 logrotate、(c) 稽核要求的保存期限（常見 6 個月），
> 本機留不住就送集中日誌。★★★ 另外**不要**用 `DEBUG` 當常態設定，
> 官方手冊明確警告它違反使用者隱私。見「日誌」與 [[19-日誌系統]]。
>
> **Q10.** ★★★★ 原因是 RHEL 的 `/etc/sysconfig/sshd` 有 `CRYPTO_POLICY=` 這行，
> 它把 `/etc/crypto-policies/back-ends/opensshserver.config` 的內容**以命令列參數形式**
> 傳給 sshd，而**命令列優先於設定檔**，所以你寫的 `Ciphers` / `MACs` / `KexAlgorithms`
> 全部被覆蓋（查證：`grep -n CRYPTO_POLICY /etc/sysconfig/sshd`、`update-crypto-policies --show`）。
> 解法 A（建議）`sudo update-crypto-policies --set FUTURE` 再 `reload sshd`，全機一致、稽核好交代；
> 解法 B 把 `CRYPTO_POLICY=` 註解掉再 `restart sshd`，等於這台脫離全機政策，要寫進變更紀錄。
> 演算法清單怎麼選見 [[07-SSH-安全強化]]。此題見「RHEL 系對照」摺疊區塊。

## 延伸閱讀

- [[07-SSH-安全強化]] —— 演算法清單、`ssh-audit`、2FA、SSH CA、fail2ban 整合，本篇刻意留給它的部分
- [[02-SSH-金鑰認證與ssh-agent]] —— 關掉密碼登入的前提，authorized_keys 選項與 agent 的正確用法
- [[06-SFTP-與受限使用者]] —— `ChrootDirectory` + `ForceCommand internal-sftp` 的完整做法與權限地雷
- [[05-SSH-隧道與埠轉發]] —— 本篇只講伺服器端「准不准」，客戶端 `-L` / `-R` / `-D` 看這篇
- [[03-SSH-客戶端設定檔]] —— `ProxyJump`、`ControlMaster`；驗證新設定時 `ControlPath=none` 為何重要
- [[17-systemd服務管理]] —— `reload` / `restart` / `systemctl edit` drop-in 的完整說明
- [[19-日誌系統]] —— journald 與 rsyslog 的分工、保存期限、`journalctl` 進階過濾
- [[04-TWGCB-Linux本機導入]] —— 政府組態基準對 SSH 的具體項目與導入方式
- [[02-基準設定與範本化]] —— 把 `sshd_config.d/` 納入組態管理與版控的做法
- OpenSSH `sshd_config` 官方手冊：<https://man.openbsd.org/sshd_config>
- OpenSSH `sshd` 官方手冊（`-t` / `-T` / `-C` 完整說明）：<https://man.openbsd.org/sshd>
- Ubuntu 官方公告 SSHd now uses socket-based activation：<https://discourse.ubuntu.com/t/sshd-now-uses-socket-based-activation-ubuntu-22-10-and-later/30189>
