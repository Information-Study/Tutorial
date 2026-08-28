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
> - ★★★★ 用 `AllowGroups` 而不是列一堆帳號，用 `Match` 針對特定人／來源給不同設定，
>   並用 `sshd -T -C user=admin,addr=10.10.0.5` 驗證「這個人實際會拿到什麼設定」
> - 產出一組可直接部署的 `sshd-apply` / `sshd-confirm` / `sshd-rollback` 腳本與驗收檢查表

> [!warning] 未實機驗證
> 本篇的 **socket activation（`ssh.socket`）** 與 **自動回滾 timer** 兩段依 Ubuntu 官方公告與
> OpenSSH／systemd 手冊撰寫，撰稿環境沒有可長期保留的實體伺服器可完整驗證。
> 其餘 `sshd_config` 指令與預設值以 Ubuntu 24.04（OpenSSH 9.6p1）的
> `man 5 sshd_config` 為準。導入前請先在測試機跑一遍本篇的「驗收檢查表」。

## 前置知識

- [[02-SSH-金鑰認證與ssh-agent]] —— 本篇的所有建議設定都預設「你已經有一把能登入的金鑰」
- [[01-SSH-原理與第一次連線]] —— 認證流程、host key 的角色
- [[17-systemd服務管理]] —— `reload` 與 `restart` 的差別、`systemctl edit` 建 drop-in
- [[03-SSH-客戶端設定檔]] —— 客戶端 `~/.ssh/config` 怎麼配合伺服器端的埠與使用者設定

---

## 觀念說明

### 一句話：sshd 的設定不是「你寫了什麼」，是「sshd 讀完之後決定用什麼」

99% 的 sshd 事故都來自同一個誤解 —— **以為編輯器裡看到的就是生效的設定**。
在 Ubuntu 22.04 以後這個假設是錯的。真正的生效路徑長這樣：

```text
                     ┌──────────────────────────────────────────┐
  sshd 啟動 ────────▶ │ /etc/ssh/sshd_config                     │
                     │  第 1 行  Include /etc/ssh/sshd_config.d/*.conf  ★★★★★
                     └───────────────┬──────────────────────────┘
                                     │ 依「檔名字典序」展開
                     ┌───────────────▼──────────────────────────┐
                     │ 50-cloud-init.conf                       │  ← 安裝時自動產生
                     │ 60-cloudimg-settings.conf                │  ← 雲端映像帶的
                     │ 99-你以為最後才讀的檔.conf                 │
                     └───────────────┬──────────────────────────┘
                                     │
                     ┌───────────────▼──────────────────────────┐
                     │ 主檔剩下的內容（第 2 行以後）              │  ← 你手改的地方
                     └───────────────┬──────────────────────────┘
                                     │
                     ┌───────────────▼──────────────────────────┐
                     │ 規則：★★★★★ 同一個關鍵字，「第一個讀到的值勝出」│
                     │       後面再寫幾次都不會覆蓋               │
                     └───────────────┬──────────────────────────┘
                                     │
                     ┌───────────────▼──────────────────────────┐
                     │ Match 區塊：連線進來時才依 user/addr 套用   │
                     └───────────────┬──────────────────────────┘
                                     ▼
                          sudo sshd -T   ← 唯一可信的答案
```

`man 5 sshd_config` 的原文是：

> Unless noted otherwise, for each keyword, **the first obtained value will be used**.

Ubuntu 22.04 起把 `Include` 放在**主檔的第一行**，所以 `sshd_config.d/` 底下任何一個檔案裡的設定，
都比你在主檔裡寫的優先。**你在主檔末尾加的 `PasswordAuthentication no` 可能一點作用都沒有。**

### 這東西壞掉會怎樣

| 壞法 | 後果 | 星級 |
| --- | --- | --- |
| 設定寫錯語法就 `restart` | sshd 起不來，**所有人都連不進去**，只能靠 console／IPMI | ★★★★★ |
| 改了 `AllowGroups` 但自己不在群組裡 | 服務正常、但**你被擋在門外**，比起不來更難察覺 | ★★★★★ |
| 以為關掉密碼登入了，其實沒關 | 暴力破解持續有效，稽核記錄一堆 `Failed password` | ★★★★★ |
| 改了 `Port` 卻沒改 `ssh.socket` | 新埠沒開、舊埠還開著，防火牆已經按新埠設定 → 全斷 | ★★★★ |
| `Match` 區塊放在檔案中間 | **後面所有設定都變成該 Match 條件專屬**，全域設定憑空消失 | ★★★★ |
| 忘了 `UseDNS no` | 每次登入卡 20~30 秒才出現密碼提示，被當成「網路慢」查半天 | ★★★ |

### 三個你一定要先知道的工具

| 指令 | 回答什麼問題 | 星級 |
| --- | --- | --- |
| `sudo sshd -t` | **語法有沒有錯**（不看語意，只看能不能解析） | ★★★★★ |
| `sudo sshd -T` | **合併 Include 之後，全域實際生效的值是什麼** | ★★★★★ |
| `sudo sshd -T -C user=x,addr=y,host=z` | **某個人從某個來源連進來，實際會拿到什麼設定**（含 Match） | ★★★★ |

這三個指令是本篇的骨幹。**任何時候你想知道「現在到底是什麼設定」，答案永遠是 `sshd -T`，
不是 `cat sshd_config`。**

### reload 與 restart 的差別，在 sshd 上特別致命

| | `systemctl reload ssh` | `systemctl restart ssh` |
| --- | --- | --- |
| 做什麼 | 送 `SIGHUP`，sshd 主程序重讀設定 | 殺掉再重開 |
| **現有連線** | ★★★★★ **保留**（你那條救命的 session 還在） | 主程序重開；socket 啟動模式下可能連帶中斷 |
| 設定寫錯時 | Ubuntu 的 unit 有 `ExecReload=/usr/sbin/sshd -t`，**語法錯會拒絕 reload** | 直接掛掉，服務進 `failed` |
| 該用哪個 | **改設定一律用 reload** | 換了執行檔、改了 unit 才用 |

> [!danger] ★★★★★ 改 sshd 設定永遠先 `reload`，不要 `restart`
> `reload` 的價值不在「不中斷服務」，而在**設定改壞的時候，你那條已登入的 session 還活著**，
> 你還有機會把它改回來。`restart` 一下去，如果新設定把你擋掉，你就只剩 console 一條路。
>
> 更完整的 `reload` / `restart` 差異見 [[17-systemd服務管理]]。

### 主線環境

本篇主線是 **Ubuntu 24.04 LTS（openssh-server 9.6p1）**，RHEL 系差異集中在
「進階設定與調校」最後的摺疊對照區塊。

---

## 環境準備與安裝

### 步驟 0：先搞清楚你在哪一種環境 ★★★★

在動任何一個字之前，先跑完這四條指令。**不同版本的 sshd 行為差很多，猜錯就是事故。**

```bash
# ★★★★ 版本（決定有沒有 Include、有沒有 sshd-session 拆分）
sshd -V 2>&1 || ssh -V
lsb_release -ds
```

預期輸出：

```text
OpenSSH_9.6p1 Ubuntu-3ubuntu13.5, OpenSSL 3.0.13 30 Jan 2024
Ubuntu 24.04.2 LTS
```

```bash
# ★★★★★ 有沒有 Include？在第幾行？
grep -n '^Include' /etc/ssh/sshd_config
ls -1 /etc/ssh/sshd_config.d/ 2>/dev/null
```

預期輸出：

```text
1:Include /etc/ssh/sshd_config.d/*.conf     # ★★★★★ 在第 1 行 = 這裡面的設定全部贏過主檔
50-cloud-init.conf
60-cloudimg-settings.conf
```

```bash
# ★★★★ 是不是 socket 啟動？這決定你改 Port 該改哪裡
systemctl is-enabled ssh.socket 2>/dev/null; systemctl is-enabled ssh.service 2>/dev/null
systemctl list-units 'ssh*' --all --no-pager
```

Ubuntu 24.04 預設安裝的預期輸出：

```text
enabled          # ← ssh.socket 是 enabled
disabled         # ← ssh.service 不是 enabled，由 socket 觸發   ★★★★
UNIT          LOAD   ACTIVE   SUB       DESCRIPTION
ssh.service   loaded inactive dead      OpenBSD Secure Shell server
ssh.socket    loaded active   listening OpenBSD Secure Shell server socket
```

> [!warning] ★★★★ `ssh.service` 顯示 `inactive (dead)` **不代表 SSH 掛了**
> socket 啟動模式下，沒有人連線時 `ssh.service` 本來就是 dead，由 `ssh.socket` 在 listening。
> 很多人看到 `inactive` 就去 `systemctl start ssh`，反而搞出「兩個東西搶同一個埠」。
> **判斷 SSH 有沒有在服務，要看 `ssh.socket` 是不是 `listening`。**

```bash
# ★★★★★ 現在實際生效的關鍵值（不是檔案內容，是 sshd 自己算出來的）
sudo sshd -T | grep -Ei '^(port|listenaddress|permitrootlogin|pubkeyauthentication|passwordauthentication|kbdinteractiveauthentication|usepam|loglevel|allowgroups|allowusers)'
```

預期輸出（Ubuntu 24.04 全新安裝）：

```text
port 22
listenaddress [::]:22
listenaddress 0.0.0.0:22
permitrootlogin prohibit-password
pubkeyauthentication yes
passwordauthentication yes            # ★★★★ 預設是開的
kbdinteractiveauthentication yes      # ★★★★★ 這個也是開的，關鍵陷阱
usepam yes
loglevel INFO
```

`sshd -T` 會把所有關鍵字**印成小寫**、把預設值也一起印出來，
沒設定的項目也看得到。這是它比 `grep sshd_config` 可靠的原因。

### 步驟 1：★★★★★ 不鎖門 SOP —— 本篇的招牌

這七道保險是整篇最重要的內容。**做完再改設定，你永遠不會被鎖在外面。**

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

開兩個終端機。**第一個終端機登入後就不要動它、不要關它、不要 `exit`。**
所有的編輯與 `reload` 都在這條連線裡做。

`reload` 送出的 `SIGHUP` 只讓**主程序**重讀設定，**已建立的連線是獨立的子程序，不受影響**。
就算新設定把你的帳號完全擋掉，這條 session 仍然活著，你還可以把它改回來。

```bash
# 在第一條 session 裡確認自己是誰、從哪來 —— 待會 Match 驗證要用
who am i
echo "$SSH_CONNECTION"
```

預期輸出：

```text
admin    pts/0        2026-08-28 09:12 (10.10.0.5)
10.10.0.5 51234 10.10.0.20 22        # 來源IP 來源埠 本機IP 本機埠
```

> [!tip] ★★★ 用 `tmux` 或 `screen` 再加一層保險
> ```bash
> tmux new -s sshd-work
> ```
> 就算你的網路斷了，session 還在伺服器上跑，重連後 `tmux attach -t sshd-work` 就回到現場。
> 對於「改到一半網路閃斷」這種常見狀況，這是很划算的一步。

#### ② `sshd -t`：語法檢查 ★★★★★

```bash
sudo sshd -t && echo "語法 OK"
```

預期輸出（正確時）：

```text
語法 OK
```

有錯時（例：把 `AllowGroups` 打成 `AllowGroup`）：

```text
/etc/ssh/sshd_config.d/50-gov-baseline.conf line 12: Bad configuration option: AllowGroup
/etc/ssh/sshd_config.d/50-gov-baseline.conf: terminating, 1 bad configuration options
```

指定檔案測試（還沒放進正式路徑時）：

```bash
sudo sshd -t -f /tmp/sshd_config.candidate
```

> [!warning] ★★★★ `sshd -t` 只驗語法，不驗「你會不會被鎖在外面」
> `AllowGroups nobody-at-all` 語法完全正確，`sshd -t` 一句話都不會說。
> **語法檢查通過 ≠ 安全**，還要靠 ③ 與 ⑤。

#### ③ `sshd -T`：印出真正生效的值 ★★★★★

```bash
sudo sshd -T | grep -Ei 'passwordauthentication|kbdinteractive'
```

預期輸出：

```text
passwordauthentication no
kbdinteractiveauthentication no        # ★★★★★ 兩行都要是 no，密碼登入才是真的關了
```

驗證 Match 區塊 —— **模擬某個人從某個來源連進來**：

```bash
sudo sshd -T -C user=admin,host=mgmt01,addr=10.10.0.5,laddr=10.10.0.20,lport=22 \
  | grep -Ei 'passwordauthentication|allowtcpforwarding|permitrootlogin|forcecommand'
```

預期輸出：

```text
passwordauthentication no
allowtcpforwarding yes                 # ← Match 區塊放行了這個人的埠轉發
permitrootlogin no
```

`-C` 的關鍵字是 `user` / `host` / `addr` / `laddr` / `lport` / `rdomain`。
★★★ 舊版 OpenSSH 要求 `user`、`host`、`addr` **三個都要給**，少一個會報
`Must specify user/host/addr`，養成三個一起寫的習慣最省事。

> [!tip] ★★★★ 把 `sshd -T` 存成基準快照，日後比對用
> ```bash
> sudo sshd -T | sort > /var/backups/sshd/effective-$(date +%F).txt
> diff <(sudo sshd -T | sort) /var/backups/sshd/effective-2026-08-01.txt
> ```
> 「這台跟基準到底差在哪」一行 `diff` 就有答案，比翻設定檔快得多。
> 這也是 [[02-基準設定與範本化]] 的做法在 SSH 上的具體應用。

#### ④ `systemd-run` 自動回滾 timer ★★★★★

這是七道保險裡最強的一道：**先安排好「五分鐘後自動還原」，再去改設定。**
改完如果你連得進來，就把 timer 停掉；如果你被鎖在外面，五分鐘後系統自己救你。

```bash
sudo systemd-run --on-active=5m --unit=sshd-rollback \
  /usr/local/bin/sshd-rollback
```

預期輸出：

```text
Running timer as unit: sshd-rollback.timer
Will run service as unit: sshd-rollback.service
```

確認 timer 真的排上了：

```bash
systemctl list-timers sshd-rollback.timer --no-pager
```

預期輸出：

```text
NEXT                        LEFT     LAST PASSED UNIT                 ACTIVATES
Fri 2026-08-28 09:22:41 CST 4min 58s -    -      sshd-rollback.timer  sshd-rollback.service
```

驗證成功之後**一定要記得停掉**，否則五分鐘後你的新設定會被還原：

```bash
sudo systemctl stop sshd-rollback.timer
```

> [!danger] ★★★★★ 忘了停 timer 的後果比你想的糟
> 你改好設定、測試通過、關掉筆電去吃飯 —— 五分鐘後設定被還原，
> 但**防火牆、客戶端 `~/.ssh/config`、監控系統都還是照新設定在跑**。
> 下午回來會看到一堆「連不上」的告警，而設定檔看起來完全正常（因為它被還原了）。
> 這種案件極難查。**把 `sshd-confirm` 寫成腳本，養成「驗證完立刻執行」的肌肉記憶。**

> [!info]- 沒有 `systemd-run`（或不想用）的替代做法
> 用 `at` 或最原始的背景 subshell 也行，但精確度與可觀察性都比 timer 差：
> ```bash
> # 方法 A：at（需 apt install at）
> echo '/usr/local/bin/sshd-rollback' | sudo at now + 5 minutes
> sudo atq        # 查排程
> sudo atrm <id>  # 取消
>
> # 方法 B：nohup 背景 sleep（最陽春，機器重開就沒了）
> sudo nohup sh -c 'sleep 300; /usr/local/bin/sshd-rollback' >/dev/null 2>&1 &
> ```
> ★★★ 方法 B 的問題是你很難查到「那個 sleep 還在不在」，也不會留下日誌。
> 有 systemd 就用 `systemd-run`，它會把執行結果寫進 journal，事後查得到。
> timer 與 cron 的選型比較見 [[02-systemd-timer與cron選型]]。

#### ⑤ 在另一個埠前景試跑 ★★★★

這是唯一能在**完全不動正式服務**的前提下，真正驗證新設定的方法。

```bash
# 先放行測試埠（用完記得刪）
sudo ufw allow 2222/tcp comment 'sshd temp test'

# ★★★★ -D 前景執行、-e 日誌印到 stderr、-p 指定埠、-f 指定設定檔
sudo /usr/sbin/sshd -D -p 2222 -f /etc/ssh/sshd_config.candidate -e
```

預期輸出（前景不會返回，這是正常的）：

```text
Server listening on 0.0.0.0 port 2222.
Server listening on :: port 2222.
```

另開第三個終端機從**外部**測試：

```bash
ssh -p 2222 -o StrictHostKeyChecking=no admin@10.10.0.20 'id; echo LOGIN-OK'
```

預期輸出：

```text
uid=1000(admin) gid=1000(admin) groups=1000(admin),27(sudo),1002(ssh-users)
LOGIN-OK
```

同時前景那個視窗會即時印出認證過程：

```text
Accepted publickey for admin from 10.10.0.5 port 51240 ssh2: ED25519 SHA256:9Xk...
```

測完 `Ctrl+C` 停掉，並收回防火牆規則：

```bash
sudo ufw delete allow 2222/tcp
```

> [!warning] ★★★ 前景試跑的兩個坑
> 1. **OpenSSH 9.8 起 `sshd` 會再執行 `/usr/lib/openssh/sshd-session`**。
>    用絕對路徑 `/usr/sbin/sshd` 執行沒問題，但如果你把 sshd 複製到別的目錄再跑，
>    會出現 `sshd-session: No such file or directory`。**不要複製 binary，用絕對路徑。**
> 2. 測試設定檔裡如果寫死了 `Port 22`，`-p 2222` 會**覆蓋**它（命令列優先）；
>    但 `ListenAddress 10.10.0.20:22` 這種帶埠的寫法不會被 `-p` 覆蓋，會導致試跑仍綁 22 埠而衝突。
>    ★★★ 試跑用的候選檔建議先把 `ListenAddress` 註解掉。

#### ⑥ 確認頻外管理（out-of-band）可用 ★★★★★

在按下 `reload` 之前，**確認你有一條不經過 SSH 的路**：

| 環境 | 頻外管理 | 事前該做的驗證 |
| --- | --- | --- |
| 實體伺服器 | iDRAC / iLO / IPMI / BMC | ★★★★★ 先開瀏覽器登入一次，確認密碼沒過期 |
| Proxmox VE | PVE 網頁的 **Console**（noVNC / xterm.js） | ★★★★ 先開一次 console 看到 login prompt |
| VMware | vSphere Client 的 Web Console | ★★★★ 同上 |
| 公有雲 | Serial Console / VNC Console | ★★★ 有些雲要先在設定裡「啟用序列主控台」 |
| 都沒有 | **只剩實體鍵盤螢幕** | ★★★★★ 那你更應該做 ④ 的自動回滾 timer |

> [!danger] ★★★★★ 「反正我等一下再測」是最常見的事故起點
> 機關常見情境：機房在別的樓層、iDRAC 密碼是三年前的同事設的、
> PVE 帳號沒有這台 VM 的 console 權限 —— 這些都是「要用的時候才發現不能用」。
> **改 sshd 之前先驗證頻外管理，不是流程潔癖，是保命。**

#### ⑦ `reload`，不是 `restart` ★★★★★

```bash
sudo systemctl reload ssh
```

預期輸出：沒有輸出就是成功。確認一下：

```bash
systemctl status ssh --no-pager | head -5
sudo sshd -T | grep -i passwordauthentication
```

```text
● ssh.service - OpenBSD Secure Shell server
     Loaded: loaded (/usr/lib/systemd/system/ssh.service; disabled; preset: enabled)
     Active: active (running) since Fri 2026-08-28 09:12:03 CST; 3min ago
passwordauthentication no        # ★★★★ 新值生效了
```

**然後從第二個乾淨的終端機登入驗證**（不要重用舊 session）：

```bash
ssh -o ControlMaster=no -o ControlPath=none admin@10.10.0.20 'echo NEW-SESSION-OK'
```

```text
NEW-SESSION-OK
```

★★★★ `-o ControlPath=none` 很重要 —— 如果你的 `~/.ssh/config` 開了連線多工
（`ControlMaster`），「新連線」其實是走舊的通道，**根本沒有重新認證**，測了等於沒測。
見 [[03-SSH-客戶端設定檔]]。

驗證成功，立刻停掉回滾 timer：

```bash
sudo systemctl stop sshd-rollback.timer
```

---

## 基礎設定

### 設定檔治理：★★★★ 不要動主檔

```text
/etc/ssh/sshd_config              ← ★★★★ 套件的地盤，升級時會問你要不要覆蓋。不要動。
/etc/ssh/sshd_config.d/
    ├── 50-cloud-init.conf        ← 安裝程式產生的，你沒寫但它會贏
    ├── 50-gov-baseline.conf      ← ★★★★★ 你的機關基準寫在這裡
    ├── 60-cloudimg-settings.conf ← 雲端映像帶的
    └── 90-host-<主機名>.conf     ← 單機例外（少用）
```

三個理由：

1. **升級不會被覆蓋。** `dpkg` 升級 openssh-server 時若偵測到主檔被改過，會跳出
   `Configuration file '/etc/ssh/sshd_config' ... What would you like to do about it?`
   自動化派送時這一問會卡住整批機器。★★★★
2. **可以納入版控。** 只要把 `sshd_config.d/` 丟進 git 或組態管理工具就好，
   不用管主檔隨版本變動的雜訊。
3. **職責清楚。** 出事時「這台跟基準差在哪」只要看一個檔案。

> [!danger] ★★★★★ 檔名排序決定誰贏，不是你寫的位置
> `Include /etc/ssh/sshd_config.d/*.conf` 是用 **glob 展開後的字典序**讀檔，
> 而規則是**第一個讀到的值勝出**。所以：
>
> - `50-cloud-init.conf` 裡的 `PasswordAuthentication yes`
> - **贏過** `60-cloudimg-settings.conf` 裡的 `PasswordAuthentication no`
> - 也贏過你在主檔任何位置寫的設定
>
> ★★★★★ 數字**小**的贏。這跟 Nginx `conf.d`、logrotate、systemd drop-in 的
> 「後蓋前」直覺**完全相反**，是最容易踩的一顆雷。
>
> 機關基準要壓過 cloud-init，就得取一個**排在它前面**的檔名，例如
> `10-gov-baseline.conf`；或者更乾淨的做法：**直接刪掉／清空 `50-cloud-init.conf`**，
> 讓基準檔成為唯一來源。
>
> 不管你選哪一種，**驗證方式只有一個**：`sudo sshd -T | grep <關鍵字>`。

### 監聽類：Port / ListenAddress / AddressFamily

| 指令 | 預設值 | 建議值 | 改壞會怎樣 |
| --- | --- | --- | --- |
| `Port` | `22` | 維持 `22` 或改非標準埠 | ★★★★ Ubuntu 24.04 socket 模式下**改了不生效**，見下一節 |
| `ListenAddress` | 全部位址 | ★★★★ `10.10.0.20`（只綁管理網段） | 綁到開機時還沒起來的 IP → sshd 起不來 |
| `AddressFamily` | `any` | 沒用 IPv6 就 `inet` | 設 `inet` 後 IPv6 客戶端全部連不進來 |

```bash
# 只綁管理網段的寫法
sudo tee /etc/ssh/sshd_config.d/50-gov-baseline.conf >/dev/null <<'EOF'
ListenAddress 10.10.0.20
AddressFamily inet
EOF
sudo sshd -t && sudo systemctl reload ssh
```

驗證實際綁在哪：

```bash
sudo ss -lntp '( sport = :22 )'
```

預期輸出：

```text
State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process
LISTEN 0      4096      10.10.0.20:22        0.0.0.0:*     users:(("systemd",pid=1,fd=93))
```

★★★★ `Process` 欄顯示 **`systemd`** 而不是 `sshd`，就代表你在 **socket 啟動模式**，
`Port` / `ListenAddress` 這兩個指令**根本沒有被使用**。

> [!danger] ★★★★★ `ListenAddress` 綁到「開機時還不存在」的位址 = 開機後 SSH 全滅
> 常見於：綁 VLAN 子介面、綁 bond、綁 DHCP 才拿得到的 IP、綁 keepalived 的 VIP。
> sshd 在 `network-online.target` 之後啟動，但**介面拿到 IP 的時機不保證**。
>
> 兩個解法：
> ```bash
> # A. 保留一個保底位址（永遠綁得到）
> ListenAddress 10.10.0.20
> ListenAddress 127.0.0.1
> ```
> ```bash
> # B. socket 模式用 FreeBind（允許綁尚未存在的位址）
> sudo systemctl edit ssh.socket
> # [Socket]
> # FreeBind=yes
> ```
> ★★★★ VIP 的情況一律用 B，否則主備切換時 sshd 會啟動失敗。

### ★★★★ Ubuntu 24.04：`Port` 要改在 `ssh.socket`

Ubuntu 從 22.10 開始（openssh-server `1:9.0p1-1ubuntu1`）預設改用 **systemd socket activation**：
由 `ssh.socket` 監聽 22 埠，有連線進來才觸發 sshd。省下常駐記憶體，但代價是
**`sshd_config` 裡的 `Port` 與 `ListenAddress` 不再被使用**。

判斷方法：

```bash
systemctl is-enabled ssh.socket
```

```text
enabled        # ← socket 模式
```

```text
disabled       # 或 Failed to get unit file state: No such file... ← 傳統 service 模式
```

#### 做法 A（建議）：改 `ssh.socket` 的 `ListenStream=`

```bash
sudo systemctl edit ssh.socket
```

在編輯器中填入：

```ini
[Socket]
# ★★★★★ 空的那行是必要的！它清掉原本的 22，否則會變成同時聽 22 和 2222
ListenStream=
ListenStream=2222
```

存檔後：

```bash
sudo systemctl daemon-reload
sudo systemctl restart ssh.socket
sudo ss -lntp | grep 2222
```

預期輸出：

```text
LISTEN 0 4096 *:2222 *:* users:(("systemd",pid=1,fd=93))
```

> [!danger] ★★★★★ 少寫那行空的 `ListenStream=` 會怎樣
> systemd 的 `ListenStream=` 是**列表型**指令，直接寫新值是「**追加**」不是「取代」。
> 結果是 22 和 2222 **同時開著** —— 你以為改好埠了、防火牆也只放行 2222，
> 但 22 埠還在對外裸奔，暴力破解照樣打得進來。**這是資安稽核會直接開缺失的錯誤。**
> 同樣的規則也適用於 unit 檔的 `ExecStart=`，見 [[01-systemd-unit撰寫實戰]]。

#### 做法 B：關掉 socket，回到傳統 service 模式

如果你的組態管理工具、監控腳本、TWGCB 檢測腳本都假設「sshd 是常駐服務」，
回到傳統模式反而省事：

```bash
sudo systemctl disable --now ssh.socket
# ★★★★ 這兩個檔案是遷移時留下的，不刪掉會繼續強迫 socket 行為
sudo rm -f /etc/systemd/system/ssh.service.d/00-socket.conf
sudo rm -f /etc/systemd/system/ssh.socket.d/addresses.conf
sudo systemctl daemon-reload
sudo systemctl enable --now ssh.service
```

驗證：

```bash
systemctl is-active ssh.service; sudo ss -lntp '( sport = :22 )'
```

```text
active
LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=1421,fd=3))   # ★★★ Process 變回 sshd
```

回到 service 模式後，`sshd_config` 的 `Port` / `ListenAddress` 就恢復作用了。

> [!warning] ★★★★ socket 模式下 `journalctl -u ssh` 可能看不到連線日誌
> socket 觸發的 sshd 有機會跑在別的 unit 名稱底下，`-u ssh` 會漏掉。
> **最保險的查法是用 syslog identifier：**
> ```bash
> journalctl -t sshd -f          # ★★★★ 不管在哪個 unit 都抓得到
> journalctl -u 'ssh*' -f        # 萬用字元也可以
> ```
> 監控與告警規則（見 [[19-日誌系統]]、[[02-日誌集中與輪替]]）記得一起改，
> 否則會出現「登入失敗告警突然歸零」的假象。

### 認證類：★★★★★ 最容易自以為設好的一組

| 指令 | 預設值 | 建議值 | 改壞會怎樣 |
| --- | --- | --- | --- |
| `PermitRootLogin` | `prohibit-password` | ★★★★ `no` | 設 `yes` + 密碼認證 = 全網的 bot 都在打你的 root |
| `PubkeyAuthentication` | `yes` | `yes` | 設 `no` 而密碼也關 = **沒有任何人能登入** ★★★★★ |
| `PasswordAuthentication` | `yes` | ★★★★ `no` | 單獨設 `no` **擋不住密碼登入**，見下方 |
| `KbdInteractiveAuthentication` | **`yes`** | ★★★★★ `no` | 忘了關 = 密碼登入其實還開著 |
| `PermitEmptyPasswords` | `no` | `no` | 設 `yes` 等於門戶洞開 ★★★★★ |
| `AuthenticationMethods` | 未設（任一種通過即可） | `publickey`（進階） | 設成 `publickey,password` 是**兩種都要**，不是二選一 ★★★★ |
| `MaxAuthTries` | `6` | `3` | 設太小（1）會讓「agent 裡有多把金鑰」的人直接被踢 ★★★ |
| `MaxSessions` | `10` | `4~10` | 設 `1` 會讓 `ControlMaster` 多工與 `scp` 併發失敗 ★★★ |
| `MaxStartups` | `10:30:100` | `10:30:60` | 設太小，多人同時登入時會被隨機拒絕 ★★★ |
| `UsePAM` | 上游 `no`／Ubuntu 設 `yes` | ★★★★ `yes` | 設 `no` 會壞掉帳號鎖定、`pam_faillock`、密碼過期、motd |

#### ★★★★★ 頭號陷阱：關了密碼登入，卻還能用密碼登入

這是 Ubuntu 22.04 之後最常見的 sshd 誤解：

```bash
# 你以為這樣就關掉密碼登入了
echo 'PasswordAuthentication no' | sudo tee -a /etc/ssh/sshd_config
sudo systemctl reload ssh

# 結果從別台機器測試 ——
ssh -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no admin@10.10.0.20
```

```text
admin@10.10.0.20's password:        # ★★★★★ 還是問密碼！而且輸入正確就會登入
```

原因有兩層：

1. **`KbdInteractiveAuthentication` 預設是 `yes`**。它搭配 `UsePAM yes` 時，
   PAM 的 `pam_unix` 一樣會問密碼並驗證 —— 走的是 `keyboard-interactive` 而不是 `password`，
   所以 `PasswordAuthentication no` 管不到它。
2. **`Include` 在檔首、第一個值勝出**。你 `tee -a` 加在主檔末尾的那行，
   很可能被 `50-cloud-init.conf` 裡的 `PasswordAuthentication yes` 蓋掉，連第一層都沒過。

正確做法：

```bash
sudo tee /etc/ssh/sshd_config.d/50-gov-baseline.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no      # ★★★★★ 這行才是關鍵
PubkeyAuthentication yes
PermitEmptyPasswords no
EOF
sudo sshd -t && sudo systemctl reload ssh
```

驗證（★★★★★ 兩行都要是 `no` 才算數）：

```bash
sudo sshd -T | grep -Ei 'passwordauthentication|kbdinteractiveauthentication'
```

```text
passwordauthentication no
kbdinteractiveauthentication no
```

再從外部實測一次：

```bash
ssh -o PreferredAuthentications=password,keyboard-interactive -o PubkeyAuthentication=no \
    admin@10.10.0.20
```

```text
admin@10.10.0.20: Permission denied (publickey).     # ★★★★★ 這才是關對了
```

> [!tip] ★★★ `ChallengeResponseAuthentication` 是舊名字
> OpenSSH 8.7 起 `ChallengeResponseAuthentication` 改名為 `KbdInteractiveAuthentication`，
> 舊名仍可用（deprecated alias）。網路上很多舊教學寫的是舊名 —— 兩個是同一件事，
> **不要兩個都寫**，會互相覆蓋而且第一個勝出，徒增混亂。

#### `MaxStartups 10:30:100` 的三段語意 ★★★

很多人以為這是「最多 10 條連線」，錯了。三個數字是 `start:rate:full`：

```text
未認證連線數
  0 ─────────► 10        全部接受
 10 ─────────► 100       以 30% → 100% 線性上升的機率「隨機」拒絕      ★★★
100 ─────────►           全部拒絕
```

- **未認證**（unauthenticated）：連進來但還沒完成登入的那段時間，受 `LoginGraceTime` 限制。
- `30` 是**百分比**，不是秒數也不是連線數。
- ★★★ 症狀是「有時候連得上、有時候被拒絕」，日誌出現
  `Connection closed by ... [preauth]` 或 `beginning MaxStartups throttling`。
- 跳板機、CI/CD 大量併發 SSH 的環境要調大（例如 `30:30:200`）；
  一般伺服器維持預設或縮小到 `10:30:60`。

### 存取控制：★★★★ Allow / Deny 的評估順序

```text
連線進來
   │
   ├─ ① DenyUsers   命中 → ★ 直接拒絕（不再往下看）
   ├─ ② AllowUsers  有設定但沒命中 → 拒絕
   ├─ ③ DenyGroups  命中 → 拒絕
   └─ ④ AllowGroups 有設定但沒命中 → 拒絕
   ▼
 允許
```

**規則：Deny 永遠優先於 Allow；四個指令只要設了其中的 Allow 類，沒被列到的人一律進不來。**

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `DenyUsers` | 個別黑名單（離職但帳號還沒刪） | ★★★ |
| `AllowUsers` | 白名單帳號，可帶來源：`admin@10.10.0.0/24` | ★★★ |
| `DenyGroups` | 群組黑名單 | ★★ |
| `AllowGroups` | ★★★★ **機關環境的正解** | ★★★★ |

#### 為什麼機關該用 `AllowGroups`

```bash
# ✗ 難維護：每次人事異動都要改 sshd 設定 + reload + 走變更申請
AllowUsers admin ops01 ops02 vendor-a vendor-b

# ✓ ★★★★ 一次設定，之後只動群組成員
AllowGroups ssh-users
```

建立與維護：

```bash
sudo groupadd -f ssh-users
sudo usermod -aG ssh-users admin
sudo usermod -aG ssh-users ops01

# 確認自己真的在裡面 —— ★★★★★ reload 之前一定要跑這行
id admin | tr ',' '\n' | grep ssh-users
getent group ssh-users
```

預期輸出：

```text
1002(ssh-users)
ssh-users:x:1002:admin,ops01
```

好處：

1. **人事異動不用改 sshd 設定**，`usermod -aG` 即時生效（下次登入就套用），不必 reload。
2. **稽核好交代**：「誰可以 SSH 進來」等於 `getent group ssh-users`，一行指令交卷。
3. **可以跟 AD／LDAP 群組對接**，帳號治理集中在目錄服務。

> [!danger] ★★★★★ 設 `AllowGroups` 之前，先確認自己在群組裡
> 這是「服務正常但你進不去」的最經典寫法。順序永遠是：
> ```bash
> sudo groupadd -f ssh-users
> sudo usermod -aG ssh-users "$(logname)"
> id "$(logname)" | grep -q ssh-users || { echo "★ 你不在群組裡，停手"; exit 1; }
> # 確認過了才寫設定
> ```
> ★★★★ 補充一個細節：`usermod -aG` **不會影響你現在這條 session 的群組**
> （群組是登入時決定的），但 sshd 是在**新連線認證時**去查 `getent group`，
> 所以新連線會拿到新群組，不需要你先登出。

### 逾時與連線品質

| 指令 | 預設值 | 建議值 | 說明 |
| --- | --- | --- | --- |
| `LoginGraceTime` | `120` | ★★★ `30` | 連上但沒完成認證的最長時間；縮短可減輕 slowloris 型騷擾 |
| `ClientAliveInterval` | `0`（關閉） | ★★★★ `300` | 每隔幾秒送一次加密探測 |
| `ClientAliveCountMax` | `3` | ★★★★ `3` | 連續幾次沒回應就斷線 |
| `TCPKeepAlive` | `yes` | `yes` | TCP 層的存活偵測（可被偽造，不能取代上面兩個） |
| `UseDNS` | `no` | ★★★ `no` | 開著會對來源 IP 做反解 |

**閒置逾時的算法**：`ClientAliveInterval × ClientAliveCountMax` = 實際斷線時間。

機關稽核常見的「閒置 15 分鐘自動登出」= **900 秒**，兩種寫法：

```ini
# 寫法一（語意明確，各版本行為一致）★★★★ 推薦
ClientAliveInterval 300
ClientAliveCountMax 3          # 300 × 3 = 900 秒

# 寫法二（TWGCB／CIS 常見）
ClientAliveInterval 900
ClientAliveCountMax 0          # 第一次探測沒回應就斷
```

> [!warning] ★★★ `ClientAliveCountMax 0` 的行為在不同版本曾有差異
> 有些舊版本把 `0` 解讀為「停用」而不是「零次容忍」，結果**逾時根本沒生效**，
> 稽核抽查時才被抓到。導入前務必實測：
> ```bash
> # 開一條連線放著不動，記錄開始時間
> date; ssh admin@10.10.0.20
> # 什麼都不要打，等它自己斷，記錄結束時間
> ```
> 預期看到（約 900 秒後）：
> ```text
> Connection to 10.10.0.20 closed by remote host.
> Connection to 10.10.0.20 closed.
> ```
> 沒斷就是設定沒生效。★★★★ **寫法一比較保險**，因為 `3` 在任何版本都是明確的次數。

> [!warning] ★★★ 逾時設定會誤殺長時間工作
> `rsync` 大檔、`apt upgrade`、資料庫匯入這類「終端機看起來沒動靜」的工作，
> 其實通道上有資料在跑，**不會**被 ClientAlive 斷掉。
> 真正會被斷的是「開著一個 shell 去開會」。要跑長工作請一律用 `tmux` / `screen` / `nohup`，
> 不要依賴逾時設定寬鬆。

#### `UseDNS` 的 20~30 秒之謎 ★★★

```ini
UseDNS no
```

開著（`yes`）時，sshd 會對來源 IP 做反解（PTR），用來讓 `AllowUsers user@hostname` 這種
以主機名為條件的規則生效。問題是：

- 內網 IP 通常**沒有 PTR 紀錄**，DNS 伺服器要等到逾時才回 NXDOMAIN
- 兩台 DNS、各 5 秒逾時、retry 兩次 → **使用者要等 20~30 秒才看到密碼提示**
- 這種症狀 100% 會被回報成「網路很慢」，然後你去查交換器、查頻寬，查半天

驗證是不是這個問題：

```bash
# 客戶端加 -v，看卡在哪一步
ssh -v admin@10.10.0.20 2>&1 | ts '[%H:%M:%S]' | grep -E 'Authenticat|Offering|Server accepts'
```

★★★ 如果 `debug1: Connecting to ...` 之後停很久才有下一行，先去伺服器上看 `sshd -T | grep usedns`。

---

## 進階設定與調校

### 功能開關與最小化 ★★★★

**預設全部關掉，需要的人用 `Match` 個別放行** —— 這是最小權限原則在 sshd 上的具體寫法。

| 指令 | 預設值 | 基準建議 | 關掉會擋住什麼／不關的風險 |
| --- | --- | --- | --- |
| `AllowTcpForwarding` | `yes` | ★★★★ `no` | 關掉後 `ssh -L` / `-D` 全部失效；不關 = 任何能登入的人都能把內網服務轉出去 |
| `PermitOpen` | `any` | ★★★★ 白名單 | 搭配 `AllowTcpForwarding yes` 限制「只能轉到哪些目標」 |
| `GatewayPorts` | `no` | ★★★★ `no` | 設 `yes` 會讓 `-R` 轉發**綁到 0.0.0.0**，等於在防火牆上開洞 ★★★★★ |
| `AllowAgentForwarding` | `yes` | ★★★★ `no` | 不關的話，跳板機 root 可以**盜用你的 agent 去登入別台** ★★★★★ |
| `AllowStreamLocalForwarding` | `yes` | `no` | Unix socket 轉發，一般用不到 |
| `X11Forwarding` | `no` | `no` | Ubuntu 主檔常設成 `yes`，伺服器沒 GUI 就該關 ★★★ |
| `PermitTunnel` | `no` | `no` | 設 `yes` 等於允許在 SSH 上架 VPN（tun/tap） |
| `PermitUserEnvironment` | `no` | ★★★★★ **`no`** | 設 `yes` = 使用者可經 `~/.ssh/environment` 注入 `LD_PRELOAD` 等變數提權 |
| `DisableForwarding` | 未設 | ★★★★ 一次全關 | 比逐項關掉更保險，會蓋過所有 forwarding 相關設定 |
| `PermitTTY` | `yes` | 服務帳號 `no` | 只給自動化用的帳號不該拿到互動 shell |

```ini
# ★★★★ 一行全關（OpenSSH 8.x+）
DisableForwarding yes

# 或逐項控制 + 白名單
AllowTcpForwarding yes
PermitOpen 10.10.0.30:3306 10.10.0.31:5432    # ★★★★ 只准轉到這兩個目標
GatewayPorts no
AllowAgentForwarding no
X11Forwarding no
PermitTunnel no
PermitUserEnvironment no
```

驗證：

```bash
sudo sshd -T | grep -Ei 'forwarding|permitopen|gatewayports|permittunnel|permituserenvironment'
```

```text
allowagentforwarding no
allowtcpforwarding no
gatewayports no
x11forwarding no
permittunnel no
permituserenvironment no
permitopen any
```

> [!danger] ★★★★★ `AllowAgentForwarding yes` + 跳板機 = 你的金鑰等於交出去了
> agent forwarding 會在跳板機上建立一個 socket，**該機器的 root 可以直接拿它去簽認證挑戰**，
> 等於用你的身分登入你所有能登入的機器 —— 而且你的私鑰從頭到尾沒離開本機，**追不到**。
> 正解是用 `ProxyJump`（`ssh -J`）取代 agent forwarding，見 [[03-SSH-客戶端設定檔]]。

> [!note] 埠轉發的**客戶端**用法（`-L` / `-R` / `-D`）不在本篇
> 本篇只講伺服器端「准不准」。客戶端怎麼用、跳板機怎麼串，見 [[05-SSH-隧道與埠轉發]]。

### `Match` 區塊 ★★★★

`Match` 讓你對「特定使用者／群組／來源」套用不同設定 —— 例如全域關閉埠轉發，
但只放行維運群組。

#### 語法與可用條件

```ini
Match <條件> <值> [<條件2> <值2> ...]
    <只在條件命中時套用的指令>
```

| 條件 | 說明 | 範例 |
| --- | --- | --- |
| `User` | 使用者名稱，可用萬用字元與逗號列表 | `Match User admin,ops*` |
| `Group` | 使用者的**任一**群組 | `Match Group ssh-admins` |
| `Address` | 來源 IP，支援 CIDR 與否定 `!` | `Match Address 10.10.0.0/24` |
| `LocalAddress` | 連進來的**本機**位址（多網卡分流） | `Match LocalAddress 10.10.0.20` |
| `LocalPort` | 連進來的**本機**埠 | `Match LocalPort 2222` |
| `All` | 全部命中（用來收尾） | `Match All` |

多個條件寫在同一行是 **AND**；同一條件內用逗號分隔是 **OR**。

```ini
# ★★★★ 維運群組 + 來自管理網段 → 才准埠轉發
Match Group ssh-admins Address 10.10.0.0/24
    AllowTcpForwarding yes
    PermitOpen 10.10.0.30:3306
    AllowAgentForwarding no
```

#### ★★★★★ 三條鐵律

> [!danger] ★★★★★ 鐵律一：`Match` 一旦出現，**到檔案結尾或下一個 `Match` 為止都算它的**
> ```ini
> # ✗ 災難寫法
> Match User backup
>     ForceCommand /usr/local/bin/backup-only
>
> PasswordAuthentication no      # ★★★★★ 這行變成「只有 backup 這個使用者才關密碼」！
> AllowGroups ssh-users          # ★★★★★ 這行也一樣，全域完全沒有生效
> ```
> ```ini
> # ✓ 正確：全域設定寫在前面，所有 Match 區塊放在檔案最後
> PasswordAuthentication no
> AllowGroups ssh-users
>
> Match User backup
>     ForceCommand /usr/local/bin/backup-only
> ```
> ★★★★ 這個錯誤 `sshd -t` **檢查不出來**，因為語法完全合法。
> 唯一的偵測方法是 `sudo sshd -T`（不帶 `-C` 時只印全域設定）—— 
> 如果你發現 `passwordauthentication yes`，就是被 Match 吃掉了。

> [!danger] ★★★★ 鐵律二：`Match` 裡面只能用「允許的關鍵字」
> `Port`、`ListenAddress`、`UsePAM`、`MaxStartups`、`LogLevel` 之外的很多全域指令**不能**放在 Match 裡。
> 可用的包含：`AllowTcpForwarding`、`AllowAgentForwarding`、`AllowGroups`、`AllowUsers`、
> `AuthenticationMethods`、`AuthorizedKeysFile`、`Banner`、`ChrootDirectory`、
> `ClientAliveInterval`、`ClientAliveCountMax`、`DenyGroups`、`DenyUsers`、`ForceCommand`、
> `GatewayPorts`、`KbdInteractiveAuthentication`、`LogLevel`、`MaxAuthTries`、`MaxSessions`、
> `PasswordAuthentication`、`PermitOpen`、`PermitRootLogin`、`PermitTTY`、`PubkeyAuthentication`、
> `X11Forwarding` 等（完整清單見 `man 5 sshd_config` 的 Match 段）。
> 放錯會直接被 `sshd -t` 抓出來：
> ```text
> /etc/ssh/sshd_config.d/50-gov-baseline.conf line 30: Directive 'Port' is not allowed within a Match block
> ```

> [!danger] ★★★★ 鐵律三：`Match` 內的設定**不受**「第一個值勝出」保護
> Match 區塊是**連線時**才評估的第二層，會覆蓋全域值。
> 也就是說 `sshd -T`（不帶 `-C`）看到的乾淨結果，**不代表實際連線時是那樣**。
> 一定要用 `-C` 驗證每一種角色。

#### 驗證每一種角色實際拿到什麼 ★★★★★

```bash
# 一般使用者
sudo sshd -T -C user=ops01,host=pc01,addr=10.20.0.9 | grep -Ei 'allowtcpforwarding|forcecommand|permitrootlogin'
```

```text
allowtcpforwarding no
permitrootlogin no
```

```bash
# 維運人員從管理網段
sudo sshd -T -C user=admin,host=mgmt01,addr=10.10.0.5 | grep -Ei 'allowtcpforwarding|permitopen'
```

```text
allowtcpforwarding yes
permitopen 10.10.0.30:3306
```

```bash
# 備份服務帳號
sudo sshd -T -C user=backup,host=nas01,addr=10.10.0.40 | grep -Ei 'forcecommand|permittty|allowtcpforwarding'
```

```text
forcecommand /usr/local/bin/backup-only
permittty no
allowtcpforwarding no
```

把這三條指令寫進驗收腳本，每次改設定都跑一遍。

> [!note] `ChrootDirectory` + `ForceCommand internal-sftp` 的完整做法不在本篇
> 那是受限 SFTP 使用者的主題，包含目錄擁有者必須是 root、目錄不能可寫等一堆細節，
> 完整寫在 [[06-SFTP-與受限使用者]]。本篇只說明「這兩個指令可以放在 Match 裡」。

### Banner 與 UsePAM

#### 法定登入警語 ★★★★

機關資安規範（以及 TWGCB、CIS）都要求登入前顯示「未經授權存取之告示」，
理由是**法律上的「已明確告知」**，事後追訴時是必要證據。

```ini
Banner /etc/issue.net
```

```bash
sudo tee /etc/issue.net >/dev/null <<'EOF'
******************************************************************
  本系統為 XX 機關所有，僅供授權人員因公使用。
  使用者之所有操作將被記錄並定期稽核。
  未經授權之存取、使用或破壞行為，將依刑法第三十六章
  「妨害電腦使用罪」及相關法規追究法律責任。
  繼續連線即表示您已閱讀並同意上述條款。
******************************************************************
EOF
sudo chmod 644 /etc/issue.net
sudo sshd -t && sudo systemctl reload ssh
```

驗證（從外部）：

```bash
ssh admin@10.10.0.20
```

預期輸出（**在輸入密碼／認證之前**就顯示）：

```text
******************************************************************
  本系統為 XX 機關所有，僅供授權人員因公使用。
...
******************************************************************
admin@10.10.0.20:~$
```

| 檔案 | 何時顯示 | 誰讀它 |
| --- | --- | --- |
| `/etc/issue` | 本機 tty 登入**前** | `getty` / `agetty` |
| **`/etc/issue.net`** | ★★★★ **SSH 認證前** | sshd 的 `Banner` |
| `/etc/motd` | 登入**成功後** | PAM 的 `pam_motd` |

★★★★ 稽核要的是**認證前**的告示，所以是 `/etc/issue.net`，不是 `/etc/motd`。
放在 motd 等於「登入成功之後才告訴他不准登入」，形同虛設。

> [!warning] ★★★ Banner 不要放系統版本、主機名、機關內部代號
> ```text
> ✗ Ubuntu 24.04.2 LTS / DB-PROD-01 / 財政資訊處第三機房
> ```
> 這是免費送給攻擊者的偵察情報。Banner 只放法律警語，其他什麼都不要。
> Ubuntu 預設的 `/etc/issue.net` 內容就是版本號，**一定要覆蓋掉**。

#### `UsePAM yes` 為什麼不能關 ★★★★

| 功能 | `UsePAM yes` | `UsePAM no` |
| --- | --- | --- |
| 帳號鎖定（`pam_faillock`） | ✅ | ❌ 失效 |
| 密碼過期強制更換 | ✅ | ❌ |
| `/etc/security/limits.conf` | ✅ | ❌ |
| 動態 motd（`pam_motd`） | ✅ | ❌ |
| 登入時間限制（`pam_time`） | ✅ | ❌ |
| 2FA 模組（`pam_google_authenticator` 等） | ✅ | ❌ |

★★★★ Ubuntu 的主檔已經設 `UsePAM yes`，**不要關掉**。
即使你完全用金鑰登入，PAM 的 session 階段仍負責建立 cgroup、寫 `wtmp`（登入紀錄）、
套用資源限制 —— 關掉會讓 `last` 查不到人，**稽核軌跡直接斷掉**。

### 日誌 ★★★★

#### 兩個來源，內容不一樣

```bash
# ★★★★ journald（一定有，socket 模式下用 -t 最保險）
sudo journalctl -t sshd -f

# rsyslog 寫的檔案（Ubuntu Server 預設有，最小化映像／容器可能沒有）
sudo tail -f /var/log/auth.log
```

| 來源 | 內容 | 特性 |
| --- | --- | --- |
| `journalctl -t sshd` | 完整、有結構化欄位 | ★★★★ 可過濾 `_PID`、`PRIORITY`，二進位格式、有大小上限 |
| `/var/log/auth.log` | 純文字 | ★★★ 好 `grep`、好給第三方工具吃；**沒裝 rsyslog 就不存在** |

先確認 `auth.log` 到底在不在：

```bash
ls -l /var/log/auth.log 2>/dev/null || echo "★★★ 沒有 auth.log，這台沒裝 rsyslog，只能查 journal"
systemctl is-active rsyslog
```

#### `LogLevel VERBOSE`：稽核追人的唯一線索 ★★★★

```ini
LogLevel VERBOSE
```

預設 `INFO` 的登入紀錄：

```text
Aug 28 09:12:41 srv01 sshd[1421]: Accepted publickey for admin from 10.10.0.5 port 51240 ssh2: ED25519 SHA256:9Xk4mZ...
```

`VERBOSE` 額外會有：

```text
Aug 28 09:12:41 srv01 sshd[1421]: Postponed publickey for admin from 10.10.0.5 port 51240 ssh2 [preauth]
Aug 28 09:12:41 srv01 sshd[1421]: Found matching ED25519 key: SHA256:9Xk4mZ...
Aug 28 09:12:41 srv01 sshd[1421]: Accepted publickey for admin from 10.10.0.5 port 51240 ssh2: ED25519 SHA256:9Xk4mZ...
Aug 28 09:12:41 srv01 sshd[1421]: User child is on pid 1425
```

**為什麼機關一定要開**：多人共用一個 `ops` 帳號時（很常見，雖然不該），
INFO 只告訴你「有人用 ops 登入」，`VERBOSE` 的**金鑰指紋**才能告訴你**是誰**。
比對方式：

```bash
# 把指紋對回人
for f in /home/*/.ssh/authorized_keys /root/.ssh/authorized_keys; do
  [ -f "$f" ] && ssh-keygen -lf "$f" | sed "s|^|$f: |"
done
```

預期輸出：

```text
/home/ops/.ssh/authorized_keys: 256 SHA256:9Xk4mZ... admin@notebook (ED25519)
/home/ops/.ssh/authorized_keys: 256 SHA256:pQ7wLn... ops01@pc01 (ED25519)
```

> [!warning] ★★★ `VERBOSE` 會讓日誌量變大，一定要配輪替
> 高流量或被大量掃描的對外主機，日誌可能一天長好幾百 MB，塞爆 `/var`。
> 至少要做兩件事：
> ```bash
> # journald 上限
> sudo mkdir -p /etc/systemd/journald.conf.d
> printf '[Journal]\nSystemMaxUse=2G\nMaxRetentionSec=90day\n' \
>   | sudo tee /etc/systemd/journald.conf.d/50-limits.conf
> sudo systemctl restart systemd-journald
> ```
> ```bash
> # 確認 auth.log 有被輪替
> grep -A6 'auth.log' /etc/logrotate.d/rsyslog
> ```
> ★★★★ 稽核通常要求日誌保存 6 個月以上，本機留不住就要送到集中日誌 —— 
> 見 [[19-日誌系統]] 與 [[02-日誌集中與輪替]]。
>
> ★★★ 不要用 `LogLevel DEBUG`／`DEBUG3` 當常態設定：它會記錄大量內部細節，
> `man 5 sshd_config` 明確警告 **DEBUG 等級違反使用者隱私**，而且量大到沒法看。
> 只在排查特定問題時臨時開，查完立刻關。

#### 幾條常用的稽核查詢

```bash
# 今天成功登入的人
sudo journalctl -t sshd --since today | grep -E 'Accepted (publickey|password)'

# 失敗次數前十的來源 IP（暴力破解偵察）★★★★
sudo journalctl -t sshd --since '7 days ago' \
  | grep -oP 'Failed password for .* from \K[0-9.]+' | sort | uniq -c | sort -rn | head
```

預期輸出：

```text
   4812 45.148.10.7
   1903 193.32.162.44
     22 10.20.0.99          # ★★★ 內網也有？這台可能被打進來了，要查
```

自動封鎖的做法（fail2ban）留給 [[05-Fail2ban入侵防護]]，本篇不重複。

### 演算法設定只提一句 ★★

`KexAlgorithms` / `Ciphers` / `MACs` / `HostKeyAlgorithms` / `PubkeyAcceptedAlgorithms`
這幾個是密碼學強化的範疇，**建議清單、`ssh-audit` 掃描、2FA、SSH CA 全部在 [[07-SSH-安全強化]]**。
本篇只教你怎麼查目前用的是什麼：

```bash
sudo sshd -T | grep -Ei '^(kexalgorithms|ciphers|macs|hostkeyalgorithms|pubkeyacceptedalgorithms)'
```

```text
kexalgorithms sntrup761x25519-sha512@openssh.com,curve25519-sha256,...
ciphers chacha20-poly1305@openssh.com,aes128-ctr,aes192-ctr,aes256-ctr,...
macs umac-64-etm@openssh.com,umac-128-etm@openssh.com,hmac-sha2-256-etm@openssh.com,...
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照 ★★★★
> RHEL 系有五個地方跟 Ubuntu 不一樣，每一個都會咬人。
>
> **① 服務名是 `sshd`，不是 `ssh`**
> ```bash
> sudo systemctl reload sshd        # ★★★★ Ubuntu 是 ssh，RHEL 是 sshd
> sudo systemctl status sshd
> ```
> ★★★ RHEL 9 也有 `sshd.socket`，但**預設是 disabled**，走傳統常駐 service，
> 所以 `sshd_config` 的 `Port` / `ListenAddress` 是有效的。確認一下：
> ```bash
> systemctl is-enabled sshd.socket
> ```
> ```text
> disabled
> ```
>
> **② ★★★★★ `update-crypto-policies` 會蓋掉你在 sshd_config 寫的演算法設定**
> RHEL 8/9 的 `/etc/sysconfig/sshd` 有一行：
> ```bash
> grep -n CRYPTO_POLICY /etc/sysconfig/sshd
> ```
> ```text
> 8:CRYPTO_POLICY=
> ```
> 它會在啟動時把 `/etc/crypto-policies/back-ends/opensshserver.config` 的參數
> **以命令列選項的形式**塞給 sshd —— 命令列優先於設定檔，
> 所以**你在 `sshd_config` 寫的 `Ciphers` / `MACs` 完全不會生效**。
>
> 查目前的系統政策：
> ```bash
> update-crypto-policies --show
> ```
> ```text
> DEFAULT
> ```
> 兩種解法：
> ```bash
> # A（建議）用系統政策，全機一致，稽核好交代
> sudo update-crypto-policies --set FUTURE      # 或 DEFAULT:NO-SHA1
> sudo systemctl reload sshd
>
> # B 讓 sshd_config 說了算：把 CRYPTO_POLICY 那行註解掉
> sudo sed -i 's/^CRYPTO_POLICY=/#CRYPTO_POLICY=/' /etc/sysconfig/sshd
> sudo systemctl restart sshd
> ```
> ★★★★ 選 B 就等於這台脫離全機政策，要在變更紀錄裡寫清楚原因。
>
> **③ ★★★★ 改埠一定要先過 SELinux**
> ```bash
> sudo dnf install -y policycoreutils-python-utils
> sudo semanage port -a -t ssh_port_t -p tcp 2222
> sudo semanage port -l | grep ssh_port_t
> ```
> ```text
> ssh_port_t                     tcp      2222, 22
> ```
> 沒做這步，sshd 會啟動失敗並在 `/var/log/audit/audit.log` 留下 AVC denied：
> ```bash
> sudo ausearch -m avc -ts recent | grep sshd
> ```
> ```text
> type=AVC msg=audit(...): avc:  denied  { name_bind } for  pid=1421 comm="sshd" src=2222 ... tclass=tcp_socket
> ```
> ★★★ 症狀是「`sshd -t` 過了、設定也對，就是起不來」。SELinux 相關見 [[07-SELinux與AppArmor]]。
>
> **④ 防火牆是 firewalld，不是 ufw**
> ```bash
> sudo firewall-cmd --permanent --add-port=2222/tcp
> sudo firewall-cmd --reload
> sudo firewall-cmd --list-ports
> ```
> ```text
> 2222/tcp
> ```
> 詳見 [[04-防火牆-firewalld]]（Ubuntu 側是 [[02-防火牆-ufw基礎與實務]]）。
>
> **⑤ 日誌在 `/var/log/secure`，不是 `/var/log/auth.log`**
> ```bash
> sudo tail -f /var/log/secure
> sudo journalctl -u sshd -f
> ```
> ★★ RHEL 9 的 `sshd_config` 一樣有 `Include /etc/ssh/sshd_config.d/*.conf` 在檔首，
> 底下會有 `50-redhat.conf`（帶 crypto policy 相關設定），
> **「第一個值勝出」的規則跟 Ubuntu 完全一樣**，同樣要靠 `sshd -T` 驗證。

---

## 完整實戰範例

### 情境

一台剛用 Ubuntu 24.04 Server ISO 裝好的伺服器 `srv-app01`（管理 IP `10.10.0.20`），
現在是預設設定：密碼登入開著、root 可用金鑰登入、埠轉發全開、沒有 Banner、沒有逾時。

**目標**：套用機關基準，並且**全程不能把自己鎖在外面**。

我們要產出四樣東西：

| 檔案 | 作用 |
| --- | --- |
| `/etc/ssh/sshd_config.d/50-gov-baseline.conf` | 機關基準設定 |
| `/usr/local/bin/sshd-apply` | 備份 → 寫入 → 語法檢查 → 佈署回滾 timer → reload |
| `/usr/local/bin/sshd-confirm` | 驗證成功後取消回滾 |
| `/usr/local/bin/sshd-rollback` | 立即還原（timer 到期時也是呼叫它） |

### 第一步：前置檢查（★★★★★ 不可略過）

```bash
# ① 保留這條 session，另開一個終端機做以下事情
tmux new -s sshd-work

# ② 建群組並把自己加進去
sudo groupadd -f ssh-users
sudo usermod -aG ssh-users "$(logname)"
id "$(logname)" | grep -q '(ssh-users)' && echo "★ OK 你在群組裡" || echo "★★★★★ 停手！你不在群組裡"
```

預期輸出：

```text
★ OK 你在群組裡
```

```bash
# ③ 確認你有金鑰可以登入（不然關掉密碼你就完了）
sudo awk '{print FILENAME": "$3}' /home/*/.ssh/authorized_keys 2>/dev/null
```

```text
/home/admin/.ssh/authorized_keys: admin@notebook
```

```bash
# ④ 確認頻外管理可用（自行到 iDRAC / PVE console 登入一次），然後記錄現況
sudo sshd -T | sort | sudo tee /var/backups/sshd-effective-before.txt >/dev/null
wc -l /var/backups/sshd-effective-before.txt
```

```text
104 /var/backups/sshd-effective-before.txt
```

### 第二步：基準設定檔

```bash
sudo install -d -m 0755 /etc/ssh/sshd_config.d
sudo tee /etc/ssh/sshd_config.d/50-gov-baseline.conf >/dev/null <<'EOF'
# =====================================================================
#  機關 SSH 基準設定  /etc/ssh/sshd_config.d/50-gov-baseline.conf
#  ★★★★★ 由組態管理派送，請勿手動編輯本機副本
#  維護：資訊室  最後更新：2026-08-28
#  驗證：sudo sshd -T  |  sudo sshd -T -C user=admin,host=x,addr=10.10.0.5
# =====================================================================

# ---- 監聽 ------------------------------------------------------------
# ★★★★ 只綁管理網段。socket 啟動模式下這兩行無效，要改 ssh.socket
ListenAddress 10.10.0.20
AddressFamily inet

# ---- 認證 ------------------------------------------------------------
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

# ---- 存取控制 --------------------------------------------------------
# ★★★★ 用群組不用帳號；人事異動只動群組成員，不必改設定
AllowGroups ssh-users
DenyUsers root

# ---- 逾時（稽核要求：閒置 15 分鐘登出）★★★★ -------------------------
ClientAliveInterval 300
ClientAliveCountMax 3
TCPKeepAlive yes

# ---- 功能最小化 ------------------------------------------------------
AllowTcpForwarding no
AllowAgentForwarding no
AllowStreamLocalForwarding no
GatewayPorts no
X11Forwarding no
PermitTunnel no
PermitUserEnvironment no               # ★★★★★ yes 會讓使用者能注入 LD_PRELOAD
PrintLastLog yes

# ---- 效能與體感 ------------------------------------------------------
UseDNS no                              # ★★★ 開著會讓登入卡 20~30 秒

# ---- 日誌與告示 ------------------------------------------------------
LogLevel VERBOSE                       # ★★★★ 稽核要靠它記錄金鑰指紋
Banner /etc/issue.net

# =====================================================================
#  ★★★★★ Match 區塊一律放在檔案最後，否則會把後面所有設定都吃進條件
# =====================================================================

# 維運群組從管理網段連入，才准開埠轉發，且只能轉到指定目標
Match Group ssh-admins Address 10.10.0.0/24
    AllowTcpForwarding yes
    PermitOpen 10.10.0.30:3306 10.10.0.31:5432

# 備份服務帳號：只准跑固定指令，不給 shell、不給 TTY
Match User backup
    ForceCommand /usr/local/bin/backup-only
    PermitTTY no
    AllowTcpForwarding no
    ClientAliveInterval 0
EOF

sudo chmod 0644 /etc/ssh/sshd_config.d/50-gov-baseline.conf
```

同時準備 Banner：

```bash
sudo tee /etc/issue.net >/dev/null <<'EOF'
******************************************************************
  本系統為 XX 機關所有，僅供授權人員因公使用。
  使用者之所有操作將被記錄並定期稽核。
  未經授權之存取、使用或破壞行為，將依相關法規追究法律責任。
******************************************************************
EOF
sudo chmod 0644 /etc/issue.net
```

### 第三步：`sshd-rollback` —— 先寫回滾，再寫套用 ★★★★★

**順序很重要**：回滾腳本必須先存在且可執行，`sshd-apply` 才能安全地引用它。

```bash
sudo tee /usr/local/bin/sshd-rollback >/dev/null <<'EOF'
#!/usr/bin/env bash
# sshd-rollback —— 立即還原最近一次備份的 SSH 設定並 reload
# ★★★★★ 這支腳本也是自動回滾 timer 的執行目標，必須絕對可靠：
#        不依賴任何外部環境變數、不依賴 PATH、失敗時大聲留下日誌
set -euo pipefail

BACKUP_DIR=/var/backups/sshd
POINTER="${BACKUP_DIR}/LATEST"
TAG=sshd-rollback

log() { logger -t "$TAG" -p auth.warning -- "$*"; echo "[$TAG] $*" >&2; }
die() { log "★★★★★ 還原失敗：$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "必須以 root 執行"
[ -f "$POINTER" ]    || die "找不到備份指標 $POINTER"

SNAP="$(cat "$POINTER")"
[ -f "$SNAP" ] || die "備份檔不存在：$SNAP"

log "開始還原 $SNAP"

# ★★★★ 先把目前狀態也存一份，才有辦法事後追「當時到底改了什麼」
FAILED_SNAP="${BACKUP_DIR}/failed-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "$FAILED_SNAP" -C / etc/ssh/sshd_config etc/ssh/sshd_config.d 2>/dev/null || true
log "問題設定已保留於 $FAILED_SNAP"

# ★★★★★ 先清空 sshd_config.d 再解壓，否則新增的檔案不會被還原掉
rm -rf /etc/ssh/sshd_config.d
tar -xzf "$SNAP" -C / || die "解壓 $SNAP 失敗"

if ! sshd -t; then
    die "還原後語法仍有誤，未執行 reload —— 請立刻用 console 進入處理"
fi

# ★★★★ socket 模式與 service 模式的重載方式不同
if systemctl is-active --quiet ssh.socket; then
    systemctl restart ssh.socket || die "restart ssh.socket 失敗"
    log "已 restart ssh.socket"
else
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null \
        || die "reload 失敗"
    log "已 reload ssh"
fi

log "★ 還原完成，目前生效設定："
sshd -T | grep -Ei '^(port|permitrootlogin|passwordauthentication|kbdinteractiveauthentication|allowgroups)' \
    | while read -r line; do log "  $line"; done
EOF

sudo chmod 0755 /usr/local/bin/sshd-rollback
sudo bash -n /usr/local/bin/sshd-rollback && echo "★ rollback 腳本語法 OK"
```

預期輸出：

```text
★ rollback 腳本語法 OK
```

### 第四步：`sshd-apply`

```bash
sudo tee /usr/local/bin/sshd-apply >/dev/null <<'EOF'
#!/usr/bin/env bash
# sshd-apply —— 安全地套用 SSH 設定變更
#   備份 → 語法檢查 → 佈署自動回滾 timer → reload → 提示人工驗證
# 用法：sudo sshd-apply [回滾寬限時間，預設 5m]
set -euo pipefail

BACKUP_DIR=/var/backups/sshd
POINTER="${BACKUP_DIR}/LATEST"
ROLLBACK_UNIT=sshd-rollback
GRACE="${1:-5m}"
STAMP="$(date +%Y%m%d-%H%M%S)"

c_ok()   { printf '\033[32m✔ %s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m▲ %s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m�’ %s\033[0m\n' "$*" >&2; }
step()   { printf '\n\033[1m── %s ──\033[0m\n' "$*"; }
die()    { c_err "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "請用 sudo 執行"

# ---------------------------------------------------------------- 0 前置
step "0/6 前置檢查"
command -v systemd-run >/dev/null || die "找不到 systemd-run，改用 at 或手動守著"
[ -x /usr/local/bin/sshd-rollback ] || die "缺少 /usr/local/bin/sshd-rollback，先建立它"

# ★★★★★ 確認執行者自己不會被新設定擋掉
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo root)}"
if grep -rqs '^AllowGroups' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/; then
    GRP="$(grep -rhs '^AllowGroups' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ | awk '{print $2}' | head -1)"
    if ! id -nG "$REAL_USER" | tr ' ' '\n' | grep -qx "$GRP"; then
        die "★★★★★ 使用者 $REAL_USER 不在 AllowGroups 群組 $GRP 裡，套用後你會被鎖在外面"
    fi
    c_ok "$REAL_USER 在 $GRP 群組中"
fi

# ---------------------------------------------------------------- 1 備份
step "1/6 備份現有設定"
install -d -m 0700 "$BACKUP_DIR"
SNAP="${BACKUP_DIR}/sshd-${STAMP}.tar.gz"
tar -czf "$SNAP" -C / etc/ssh/sshd_config etc/ssh/sshd_config.d 2>/dev/null \
    || die "備份失敗，中止（沒有備份就不准改）"
echo "$SNAP" > "$POINTER"
sshd -T 2>/dev/null | sort > "${BACKUP_DIR}/effective-${STAMP}.txt" || true
c_ok "備份：$SNAP"
c_ok "生效值快照：${BACKUP_DIR}/effective-${STAMP}.txt"

# ------------------------------------------------------------ 2 語法檢查
step "2/6 語法檢查（sshd -t）"
if ! sshd -t; then
    c_err "★★★★★ 語法有誤，已中止，現行設定未變動"
    exit 1
fi
c_ok "語法正確"

# ------------------------------------------------------------ 3 語意檢查
step "3/6 語意檢查（sshd -T）"
EFF="$(sshd -T)"
check() {  # check <關鍵字> <期望值>
    local k="$1" want="$2" got
    got="$(printf '%s\n' "$EFF" | awk -v k="$k" '$1==k {print $2; exit}')"
    if [ "$got" = "$want" ]; then c_ok "$k = $got"
    else c_warn "$k = ${got:-<未設定>}（期望 $want）"; fi
}
check passwordauthentication      no
check kbdinteractiveauthentication no
check permitrootlogin             no
check permituserenvironment       no
check usepam                      yes
check loglevel                    VERBOSE

# ★★★★★ 沒有任何認證方式可用 = 誰都進不來，這是唯一必須硬擋的組合
PK="$(printf '%s\n' "$EFF" | awk '$1=="pubkeyauthentication"{print $2}')"
PW="$(printf '%s\n' "$EFF" | awk '$1=="passwordauthentication"{print $2}')"
KB="$(printf '%s\n' "$EFF" | awk '$1=="kbdinteractiveauthentication"{print $2}')"
if [ "$PK" = "no" ] && [ "$PW" = "no" ] && [ "$KB" = "no" ]; then
    die "★★★★★ 三種認證方式全部關閉，套用後沒有人能登入，已中止"
fi

# ------------------------------------------------------- 4 自動回滾 timer
step "4/6 佈署自動回滾 timer（${GRACE} 後自動還原）"
systemctl stop "${ROLLBACK_UNIT}.timer" 2>/dev/null || true
systemd-run --on-active="$GRACE" --unit="$ROLLBACK_UNIT" \
    /usr/local/bin/sshd-rollback >/dev/null
systemctl list-timers "${ROLLBACK_UNIT}.timer" --no-pager | sed -n '2p'
c_ok "回滾保險已上膛"

# ------------------------------------------------------------- 5 套用
step "5/6 套用設定"
if systemctl is-active --quiet ssh.socket; then
    c_warn "★★★★ 偵測到 socket 啟動模式：Port/ListenAddress 由 ssh.socket 決定"
    systemctl restart ssh.socket
    c_ok "已 restart ssh.socket"
else
    systemctl reload ssh 2>/dev/null || systemctl reload sshd
    c_ok "已 reload（現有連線未中斷）"
fi

# ------------------------------------------------------------- 6 提示
step "6/6 請人工驗證"
cat <<'MSG'

★★★★★ 這條 session 不要關！

請「另外開一個乾淨的終端機」執行：

    ssh -o ControlPath=none -o ControlMaster=no <你的帳號>@<本機IP> 'echo NEW-SESSION-OK'

看到 NEW-SESSION-OK 之後，立刻回到這裡執行：

    sudo sshd-confirm

若沒有執行 sshd-confirm，設定會在寬限時間到期後自動還原。

MSG
EOF

sudo chmod 0755 /usr/local/bin/sshd-apply
sudo bash -n /usr/local/bin/sshd-apply && echo "★ apply 腳本語法 OK"
```

### 第五步：`sshd-confirm`

```bash
sudo tee /usr/local/bin/sshd-confirm >/dev/null <<'EOF'
#!/usr/bin/env bash
# sshd-confirm —— 驗證成功後解除自動回滾
set -euo pipefail
ROLLBACK_UNIT=sshd-rollback

[ "$(id -u)" -eq 0 ] || { echo "請用 sudo 執行" >&2; exit 1; }

if systemctl is-active --quiet "${ROLLBACK_UNIT}.timer"; then
    systemctl stop "${ROLLBACK_UNIT}.timer"
    echo "✔ 回滾 timer 已取消，設定正式生效"
else
    echo "▲ 沒有進行中的回滾 timer（可能已到期執行、或本來就沒佈署）"
fi

logger -t sshd-confirm -p auth.notice -- "SSH 設定變更已由 $(logname 2>/dev/null || echo root) 確認"
echo
echo "目前生效設定摘要："
sshd -T | grep -Ei '^(port|listenaddress|permitrootlogin|passwordauthentication|kbdinteractiveauthentication|allowgroups|loglevel|clientaliveinterval|clientalivecountmax)'
EOF

sudo chmod 0755 /usr/local/bin/sshd-confirm
sudo bash -n /usr/local/bin/sshd-confirm && echo "★ confirm 腳本語法 OK"
```

### 第六步：實際執行

```bash
sudo sshd-apply 5m
```

預期輸出：

```text
── 0/6 前置檢查 ──
✔ admin 在 ssh-users 群組中

── 1/6 備份現有設定 ──
✔ 備份：/var/backups/sshd/sshd-20260828-091203.tar.gz
✔ 生效值快照：/var/backups/sshd/effective-20260828-091203.txt

── 2/6 語法檢查（sshd -t）──
✔ 語法正確

── 3/6 語意檢查（sshd -T）──
✔ passwordauthentication = no
✔ kbdinteractiveauthentication = no
✔ permitrootlogin = no
✔ permituserenvironment = no
✔ usepam = yes
✔ loglevel = VERBOSE

── 4/6 佈署自動回滾 timer（5m 後自動還原）──
Fri 2026-08-28 09:17:03 CST 4min 58s - - sshd-rollback.timer sshd-rollback.service
✔ 回滾保險已上膛

── 5/6 套用設定 ──
▲ ★★★★ 偵測到 socket 啟動模式：Port/ListenAddress 由 ssh.socket 決定
✔ 已 restart ssh.socket

── 6/6 請人工驗證 ──

★★★★★ 這條 session 不要關！
...
```

從另一台機器驗證：

```bash
ssh -o ControlPath=none -o ControlMaster=no admin@10.10.0.20 'echo NEW-SESSION-OK'
```

```text
******************************************************************
  本系統為 XX 機關所有，僅供授權人員因公使用。
...
NEW-SESSION-OK
```

回到原本的 session 確認：

```bash
sudo sshd-confirm
```

```text
✔ 回滾 timer 已取消，設定正式生效

目前生效設定摘要：
port 22
listenaddress 10.10.0.20
permitrootlogin no
passwordauthentication no
kbdinteractiveauthentication no
allowgroups ssh-users
loglevel VERBOSE
clientaliveinterval 300
clientalivecountmax 3
```

### 驗收檢查表 ★★★★★

| # | 檢查項 | 指令 | 預期結果 |
| --- | --- | --- | --- |
| 1 | ★★★★★ 語法正確 | `sudo sshd -t; echo $?` | `0` |
| 2 | ★★★★★ 密碼登入真的關了 | `sudo sshd -T \| grep -c '^\(passwordauthentication\|kbdinteractiveauthentication\) no'` | `2` |
| 3 | ★★★★★ 至少有一種認證可用 | `sudo sshd -T \| grep '^pubkeyauthentication'` | `pubkeyauthentication yes` |
| 4 | ★★★★ root 不能登入 | `sudo sshd -T \| grep '^permitrootlogin'` | `permitrootlogin no` |
| 5 | ★★★★ 白名單群組正確 | `sudo sshd -T \| grep '^allowgroups'` | `allowgroups ssh-users` |
| 6 | ★★★★ 自己在群組裡 | `id $USER \| grep -o 'ssh-users'` | `ssh-users` |
| 7 | ★★★★ Match 對維運人員生效 | `sudo sshd -T -C user=admin,host=m,addr=10.10.0.5 \| grep '^allowtcpforwarding'` | `allowtcpforwarding yes` |
| 8 | ★★★★ Match 對一般使用者不生效 | `sudo sshd -T -C user=ops01,host=p,addr=10.20.0.9 \| grep '^allowtcpforwarding'` | `allowtcpforwarding no` |
| 9 | ★★★★ 服務在監聽 | `sudo ss -lntp \| grep ':22 '` | 有 `LISTEN` 一列 |
| 10 | ★★★★★ 新連線可登入 | `ssh -o ControlPath=none admin@10.10.0.20 'echo OK'` | `OK` |
| 11 | ★★★★★ 舊連線沒被踢掉 | 在原 session 執行 `uptime` | 正常輸出 |
| 12 | ★★★★ Banner 有出現 | `ssh admin@10.10.0.20 exit 2>&1 \| head -2` | 顯示警語 |
| 13 | ★★★★ 密碼登入被拒 | `ssh -o PubkeyAuthentication=no admin@10.10.0.20` | `Permission denied (publickey).` |
| 14 | ★★★ 日誌有指紋 | `sudo journalctl -t sshd -n 20 \| grep 'Found matching'` | `Found matching ED25519 key: SHA256:...` |
| 15 | ★★★★★ 回滾 timer 已取消 | `systemctl is-active sshd-rollback.timer` | `inactive` |
| 16 | ★★★ 備份存在且可還原 | `tar -tzf $(cat /var/backups/sshd/LATEST) \| head -3` | 列出 `etc/ssh/...` |

**16 項全過才算完成。** 建議把這張表做成 `sshd-verify` 腳本納入 [[02-基準設定與範本化]] 的檢核流程，
以及 [[04-TWGCB-Linux本機導入]] 的檢測項目。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 改完設定 `restart` 後所有人都連不進去，`systemctl status ssh` 顯示 `failed` | 設定語法錯誤／`ListenAddress` 綁到不存在的位址／埠被佔用 | 用 console 進入 → `sudo sshd -t` 看錯在哪一行 → 修正 → `sudo systemctl restart ssh`。下次改用 `reload` 並先跑 `sshd -t` |
| ★★★★★ `PasswordAuthentication no` 設好了，還是能用密碼登入 | `KbdInteractiveAuthentication` 預設 `yes`，搭配 `UsePAM yes` 走 keyboard-interactive 一樣驗密碼 | 加 `KbdInteractiveAuthentication no`，用 `sudo sshd -T \| grep -E 'password\|kbdinter'` 確認**兩行都是 no** |
| ★★★★★ 在 `/etc/ssh/sshd_config` 末尾改的設定完全沒作用 | `Include sshd_config.d/*.conf` 在第 1 行，且「第一個值勝出」，被 `50-cloud-init.conf` 蓋掉 | 改寫到 `sshd_config.d/` 底下，並取一個**字典序在前**的檔名；一律以 `sshd -T` 驗證 |
| ★★★★★ 設了 `AllowGroups` 之後自己也進不去 | 執行者不在該群組，或群組建立後沒有 `usermod -aG` | console 進入 → `usermod -aG ssh-users <你>` → `getent group ssh-users` 確認 → 不必 reload，新連線即生效 |
| ★★★★ 改了 `sshd_config` 的 `Port 2222`，`ss` 顯示還在聽 22 | Ubuntu 24.04 是 socket 啟動，`Port` 不被使用 | `systemctl edit ssh.socket` 寫空的 `ListenStream=` 再寫 `ListenStream=2222` → `daemon-reload` → `restart ssh.socket` |
| ★★★★ 改了 `ssh.socket` 後，22 和 2222 **同時**在聽 | 少寫那行空的 `ListenStream=`，systemd 把新值**追加**上去 | 在 drop-in 的 `[Socket]` 底下第一行補 `ListenStream=`（等號後不接東西） |
| ★★★★ 全域寫了 `PasswordAuthentication no`，`sshd -T` 卻顯示 `yes` | 該行被寫在某個 `Match` 區塊**之後**，變成只對那個條件生效 | 把所有全域設定移到第一個 `Match` **之前**；用 `sudo sshd -T`（不帶 `-C`）確認全域值 |
| ★★★★ `sshd -t` 報 `Directive 'X' is not allowed within a Match block` | 把不允許的關鍵字（`Port`、`UsePAM`、`MaxStartups`…）放進 Match | 移到 Match 之前的全域區；可用清單見 `man 5 sshd_config` 的 Match 段 |
| ★★★ 登入時要等 20~30 秒才出現提示或 shell | `UseDNS yes` 且來源 IP 沒有 PTR，DNS 反解逾時 | 設 `UseDNS no`（預設值就是 no，通常是被某個 conf 打開的）；`sshd -T \| grep usedns` 確認 |
| ★★★ 偶爾連得上、偶爾被拒絕，日誌有 `beginning MaxStartups throttling` | 未認證連線數超過 `MaxStartups` 的第一段，開始隨機丟棄 | 調大成 `30:30:200`，或縮短 `LoginGraceTime` 讓未認證連線更快釋放 |
| ★★★ 明明開了 `LogLevel VERBOSE`，`journalctl -u ssh` 什麼都沒有 | socket 啟動模式下連線跑在別的 unit 名稱底下，`-u ssh` 抓不到 | 改用 `journalctl -t sshd -f` 或 `journalctl -u 'ssh*' -f`；監控規則一併更新 |
| ★★★ `/var/log/auth.log` 不存在 | 這台沒裝 rsyslog（最小化映像／容器常見） | `systemctl is-active rsyslog` 確認；用 journal 查，或 `apt install rsyslog` |
| ★★★★ RHEL 上 `sshd_config` 寫的 `Ciphers` 完全沒生效 | `/etc/sysconfig/sshd` 的 `CRYPTO_POLICY=` 把系統政策以命令列參數塞進去，優先於設定檔 | 用 `update-crypto-policies --set` 調整，或註解掉 `CRYPTO_POLICY=` 後 `restart sshd` |
| ★★★★ RHEL 上改埠後 sshd 起不來，`audit.log` 有 `avc: denied { name_bind }` | SELinux 沒有把新埠標成 `ssh_port_t` | `semanage port -a -t ssh_port_t -p tcp 2222` 後再啟動 |
| ★★★ `sudo systemctl reload ssh` 沒有報錯但設定沒變 | reload 前忘了存檔／改到別的檔案／被 `Match` 吃掉 | `sudo sshd -T \| grep <關鍵字>` 才是答案；再用 `grep -rn '<關鍵字>' /etc/ssh/` 找出所有出現位置 |
| ★★★ 前景試跑報 `sshd re-exec requires execution with an absolute path` | 用相對路徑執行 sshd | 一律用 `/usr/sbin/sshd` 絕對路徑；OpenSSH 9.8+ 還會需要找到 `/usr/lib/openssh/sshd-session`，不要複製 binary |

### 排查步驟

**【1】先確定「服務到底有沒有在聽」**

```bash
sudo ss -lntp | grep -E ':(22|2222)\s'
```

- 看到 `users:(("sshd",...))` → 傳統 service 模式，服務正常，問題在**設定或防火牆**，跳【4】
- 看到 `users:(("systemd",...))` → **socket 啟動模式**，`Port` 設定不會生效，跳【3】
- **什麼都沒有** → 服務沒起來，跳【2】

**【2】服務起不來 —— 看語法與啟動日誌**

```bash
sudo sshd -t
```

有輸出就是語法錯，會直接指出檔名與行號：

```text
/etc/ssh/sshd_config.d/50-gov-baseline.conf line 30: Directive 'Port' is not allowed within a Match block
```

語法沒問題但還是起不來：

```bash
sudo journalctl -u ssh -u ssh.socket -n 40 --no-pager
```

| 看到什麼 | 問題在哪 |
| --- | --- |
| `Cannot bind any address` / `Address already in use` | ★★★★ 埠被別的程序佔用，或 socket 與 service 同時在跑 |
| `Bind to port 22 on 10.10.0.20 failed: Cannot assign requested address` | ★★★★★ `ListenAddress` 綁到還不存在的 IP |
| `error: Could not load host key` | ★★★★ host key 檔案遺失或權限錯，跑 `ssh-keygen -A` |
| `Permission denied` 相關 | ★★★ 檔案權限（見【6】）或 SELinux（見【8】） |

**【3】socket 模式下確認實際監聽的埠**

```bash
systemctl cat ssh.socket | grep -A5 '\[Socket\]'
```

預期輸出：

```text
[Socket]
ListenStream=22
Accept=no
FreeBind=yes
# /etc/systemd/system/ssh.socket.d/override.conf
[Socket]
ListenStream=
ListenStream=2222       # ★★★★ 有空行才是對的
```

- 看到**兩個** `ListenStream=` 有值（22 和 2222）→ 少寫空行，埠沒有真的換掉
- 只看到 `ListenStream=22` → 你的 drop-in 沒被讀到，檢查有沒有跑 `systemctl daemon-reload`

**【4】確認「生效值」而不是「檔案內容」**

```bash
sudo sshd -T | grep -Ei '^(port|listenaddress|allowgroups|allowusers|passwordauthentication|kbdinteractiveauthentication|permitrootlogin)'
```

- 生效值跟你寫的**不一樣** → 被 `sshd_config.d/` 或 `Match` 蓋掉，跳【5】
- 生效值**跟你寫的一樣**，但特定人連不進來 → 跳【7】

**【5】找出這個關鍵字到底被誰設定了**

```bash
grep -rn -i 'passwordauthentication' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/
```

預期輸出：

```text
/etc/ssh/sshd_config:58:#PasswordAuthentication yes
/etc/ssh/sshd_config:120:PasswordAuthentication no          # ← 你加的，在主檔末尾
/etc/ssh/sshd_config.d/50-cloud-init.conf:1:PasswordAuthentication yes   # ★★★★★ 這個贏
```

★★★★★ 檔名數字**小的、且 Include 在第 1 行**的勝出。把你的設定搬到
`sshd_config.d/` 並取更前面的檔名，或直接清掉 `50-cloud-init.conf`。

再確認 Match 有沒有吃掉全域設定：

```bash
grep -n '^Match' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf
awk '/^Match/{m=1} m&&/^[A-Za-z]/{print FILENAME": "FNR": "$0}' /etc/ssh/sshd_config.d/*.conf | head -20
```

★★★★ 如果第一個 `Match` 之後還有沒縮排的全域設定，那些設定**已經變成條件專屬**。

**【6】權限問題（金鑰登入失敗但沒有明確錯誤）**

```bash
sudo ls -ld /home/admin /home/admin/.ssh; sudo ls -l /home/admin/.ssh/authorized_keys
```

預期輸出：

```text
drwxr-xr-x 5 admin admin 4096 Aug 28 09:00 /home/admin
drwx------ 2 admin admin 4096 Aug 28 09:00 /home/admin/.ssh
-rw------- 1 admin admin  742 Aug 28 09:00 /home/admin/.ssh/authorized_keys
```

★★★★ 只要 `.ssh` 或家目錄**對 group/other 可寫**，sshd 就會拒絕使用 authorized_keys
（`StrictModes yes` 的行為），而且客戶端只會看到 `Permission denied (publickey)`。
伺服器端日誌會寫得很清楚：

```bash
sudo journalctl -t sshd -n 30 | grep -i 'bad ownership\|StrictModes'
```

```text
Authentication refused: bad ownership or modes for directory /home/admin
```

修正：

```bash
sudo chmod 755 /home/admin; sudo chmod 700 /home/admin/.ssh
sudo chmod 600 /home/admin/.ssh/authorized_keys
sudo chown -R admin:admin /home/admin/.ssh
```

**【7】驗證「這個人實際會拿到什麼」**

```bash
sudo sshd -T -C user=ops01,host=pc01,addr=10.20.0.9 \
  | grep -Ei '^(passwordauthentication|pubkeyauthentication|allowtcpforwarding|forcecommand|permittty)'
```

同時開一個 debug 的 sshd 在別的埠，直接看拒絕原因：

```bash
# 伺服器端（前景，看得到完整判斷過程）
sudo /usr/sbin/sshd -D -d -p 2222 -e
```

```bash
# 客戶端
ssh -vvv -p 2222 ops01@10.10.0.20
```

伺服器端會逐行印出：

```text
debug1: user ops01 matched 'Group ssh-users' at line 25
debug1: trying public key file /home/ops01/.ssh/authorized_keys
Accepted publickey for ops01 from 10.20.0.9 port 51299 ssh2: ED25519 SHA256:pQ7wLn...
```

看到 `User ops01 not allowed because none of user's groups are listed in AllowGroups`
就知道是群組問題，不是金鑰問題。★★★★ 這比猜快一百倍。

**【8】防火牆與 SELinux／AppArmor**

```bash
# Ubuntu
sudo ufw status verbose | grep -E '22|2222'
```

```text
22/tcp                     ALLOW IN    10.10.0.0/24
```

```bash
# RHEL
sudo firewall-cmd --list-all | grep -E 'ports|services'
sudo ausearch -m avc -ts recent | grep sshd
```

★★★ 客戶端出現 `Connection timed out` 通常是防火牆／路由；
出現 `Connection refused` 表示封包有到、但沒人在聽（服務沒起來或埠不對）。
這兩個錯誤訊息的區別是排查方向的分水嶺。

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對禁止：`PermitRootLogin yes` 搭配密碼認證
> 對外主機開這組設定，通常**幾小時內**就會在日誌看到每秒數次的
> `Failed password for root from <各國 IP>`。root 帳號名稱是公開的，
> 攻擊者只要猜密碼；一旦猜中，**整台機器直接失守，且沒有任何操作留下「是誰做的」**。
> 一律 `PermitRootLogin no`，需要提權就用一般帳號 + `sudo`（有完整稽核軌跡）。

> [!danger] ★★★★★ 絕對禁止：只設 `PasswordAuthentication no` 就宣稱關閉密碼登入
> `KbdInteractiveAuthentication` 沒關的話，密碼登入的門根本沒關，
> 而你的稽核報告已經勾了「已停用密碼認證」。**這是實質的資安缺失加上不實陳報。**
> 驗證只認 `sudo sshd -T`，兩行都要是 `no`。

> [!danger] ★★★★★ 絕對禁止：`PermitUserEnvironment yes`
> 開啟後任何能寫 `~/.ssh/environment` 的使用者，可以在登入時注入
> `LD_PRELOAD=/tmp/evil.so`、`PATH=/tmp/bin:$PATH` 等變數。
> 若該使用者接著執行 setuid 程式或被管理者 `su` 過去，就是一條**本機提權路徑**。
> 保持預設 `no`，並且不要為了「方便設環境變數」而打開它 —— 用 `SetEnv` 或 `AcceptEnv` 白名單。

> [!danger] ★★★★★ 絕對禁止：`GatewayPorts yes` 出現在對外主機
> 它讓 `ssh -R 8080:內網DB:3306` 的遠端轉發**綁到 0.0.0.0**，
> 等於任何人只要連得到這台機器的 8080，就直達你的內網資料庫 —— 
> 繞過所有防火牆規則。這是資料外洩的直接管道，而且防火牆日誌上完全看不出異常。

> [!danger] ★★★★ 絕對禁止：在跳板機上允許 `AllowAgentForwarding yes`
> 跳板機的 root（或任何被入侵的程序）可以直接使用轉發過來的 agent socket，
> **以你的身分登入你所有能登入的機器**。私鑰沒外洩，但效果完全一樣，而且事後追不到。
> 用 `ProxyJump` 取代，見 [[03-SSH-客戶端設定檔]]。

> [!danger] ★★★★ 絕對禁止：關掉 `UsePAM`
> 會連帶失效：`pam_faillock` 帳號鎖定、密碼過期強制、`limits.conf` 資源限制、
> **以及 `wtmp` 登入紀錄**。最後一項意味著 `last`、`lastlog` 查不到人，
> **稽核軌跡直接斷掉** —— 這在機關是重大缺失。

> [!warning] ★★★★ 機關情境的四個必辦
> 1. **法定告示**：`Banner /etc/issue.net`，內容只放法律警語，不放版本與主機資訊。
> 2. **可稽核性**：`LogLevel VERBOSE` 記錄金鑰指紋；日誌保存期依規定（常見 6 個月以上），
>    本機留不住就送集中日誌（[[19-日誌系統]]、[[02-日誌集中與輪替]]）。
> 3. **最小權限**：`AllowGroups ssh-users` + `DisableForwarding yes`，
>    需要的人再用 `Match` 個別放行，並在變更紀錄寫明理由。
> 4. **組態基準**：TWGCB 對 SSH 有明確項目（禁止 root 登入、閒置逾時、
>    `PermitEmptyPasswords no`、`LogLevel` 等），導入與檢測見
>    [[04-TWGCB-Linux本機導入]] 與 [[07-TWGCB-Linux檢測與符合性報告]]。

> [!warning] ★★★★ 改埠不是安全措施，是降噪措施
> 把 22 改成 2222 可以讓自動掃描的雜訊少 95%，日誌乾淨很多 —— 這是它真正的價值。
> 但它**不能取代**金鑰認證、`AllowGroups`、fail2ban。
> 針對性攻擊 `nmap -p-` 一掃就找到，而且改埠會讓你的監控、備份、
> CI/CD、跳板機設定全部要跟著改，成本不低。**先做認證強化，再考慮改埠。**

> [!warning] ★★★ 備份與變更紀錄
> 每次改動前 `cp` 帶時間戳備份是最低標準（本篇的 `sshd-apply` 已經做成 tar 快照）。
> 更好的做法是把 `/etc/ssh/sshd_config.d/` 納入版控或組態管理工具，
> 讓「誰在什麼時候為什麼改了什麼」有紀錄可查 —— 見 [[02-基準設定與範本化]]
> 與 [[03-備份策略與還原演練]]。

---

## 速查表

### 三大驗證指令 ★★★★★

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `sudo sshd -t` | 語法檢查，沒輸出就是過 | ★★★★★ |
| `sudo sshd -t -f <檔>` | 檢查指定檔案（正式套用前） | ★★★★ |
| `sudo sshd -T` | 印出**全域實際生效**的所有設定 | ★★★★★ |
| `sudo sshd -T -C user=u,host=h,addr=a` | 模擬某人連線，驗證 Match 結果 | ★★★★ |
| `sudo /usr/sbin/sshd -D -d -p 2222 -e` | 前景 debug 模式，看完整認證判斷過程 | ★★★★ |
| `sudo systemctl reload ssh` | 重載設定，**不斷現有連線** | ★★★★★ |

### 不鎖門 SOP 七步 ★★★★★

| # | 動作 | 星級 |
| --- | --- | --- |
| ① | 保留一條已登入 session，全程不關 | ★★★★★ |
| ② | `sudo sshd -t` 語法檢查 | ★★★★★ |
| ③ | `sudo sshd -T` / `-T -C` 驗證生效值 | ★★★★★ |
| ④ | `systemd-run --on-active=5m --unit=sshd-rollback` 上保險 | ★★★★★ |
| ⑤ | `/usr/sbin/sshd -D -p 2222 -f <新檔>` 前景試跑 | ★★★★ |
| ⑥ | 確認 IPMI / iDRAC / PVE console 可用 | ★★★★★ |
| ⑦ | `reload`（不是 `restart`），再從乾淨終端登入驗證 | ★★★★★ |

### 關鍵設定項預設值 vs 建議值

| 設定項 | 預設 | 建議 | 星級 |
| --- | --- | --- | --- |
| `PermitRootLogin` | `prohibit-password` | `no` | ★★★★ |
| `PasswordAuthentication` | `yes` | `no` | ★★★★ |
| `KbdInteractiveAuthentication` | **`yes`** | **`no`** | ★★★★★ |
| `PubkeyAuthentication` | `yes` | `yes` | ★★★★ |
| `PermitEmptyPasswords` | `no` | `no` | ★★★★★ |
| `UsePAM` | Ubuntu 設 `yes` | `yes` | ★★★★ |
| `MaxAuthTries` | `6` | `3` | ★★★ |
| `MaxSessions` | `10` | `10` | ★★ |
| `MaxStartups` | `10:30:100` | `10:30:60` | ★★★ |
| `LoginGraceTime` | `120` | `30` | ★★★ |
| `ClientAliveInterval` | `0` | `300` | ★★★★ |
| `ClientAliveCountMax` | `3` | `3` | ★★★★ |
| `UseDNS` | `no` | `no` | ★★★ |
| `AllowTcpForwarding` | `yes` | `no` | ★★★★ |
| `AllowAgentForwarding` | `yes` | `no` | ★★★★ |
| `GatewayPorts` | `no` | `no` | ★★★★★ |
| `X11Forwarding` | `no`（Ubuntu 主檔常設 `yes`） | `no` | ★★★ |
| `PermitTunnel` | `no` | `no` | ★★★ |
| `PermitUserEnvironment` | `no` | `no` | ★★★★★ |
| `LogLevel` | `INFO` | `VERBOSE` | ★★★★ |
| `Banner` | 無 | `/etc/issue.net` | ★★★★ |
| `AllowGroups` | 無 | `ssh-users` | ★★★★ |

### 檔案路徑

| 路徑 | 內容 | 星級 |
| --- | --- | --- |
| `/etc/ssh/sshd_config` | 主檔，**不要改** | ★★★★ |
| `/etc/ssh/sshd_config.d/*.conf` | ★★★★★ 你的設定寫這裡，**檔名小的贏** | ★★★★★ |
| `/etc/ssh/ssh_host_*_key` | 伺服器 host key（權限 600，遺失要 `ssh-keygen -A`） | ★★★★ |
| `/etc/issue.net` | SSH 認證**前**顯示的 Banner | ★★★★ |
| `/etc/motd` | 登入**成功後**顯示（不能當法定告示） | ★★ |
| `/etc/default/ssh` | Ubuntu 的 `SSHD_OPTS` 額外參數 | ★★ |
| `/usr/lib/systemd/system/ssh.socket` | socket 監聽定義（改用 `systemctl edit`） | ★★★★ |
| `/var/log/auth.log` | Ubuntu 認證日誌（需 rsyslog） | ★★★ |
| `/var/log/secure` | RHEL 認證日誌 | ★★★ |
| `/etc/sysconfig/sshd` | ★★★★ RHEL 專有，`CRYPTO_POLICY=` 會蓋掉演算法設定 | ★★★★ |

### Ubuntu / RHEL 差異

| 項目 | Ubuntu 24.04 | Rocky / AlmaLinux 9 | 星級 |
| --- | --- | --- | --- |
| 服務名 | `ssh`（別名 `sshd`） | `sshd` | ★★★★ |
| 啟動方式 | ★★★★ `ssh.socket`（socket 啟動） | `sshd.service`（常駐） | ★★★★ |
| 改埠 | `systemctl edit ssh.socket` | `sshd_config` 的 `Port` + `semanage port` | ★★★★ |
| 演算法 | 直接寫在 `sshd_config` | ★★★★ 受 `update-crypto-policies` 控制 | ★★★★★ |
| 防火牆 | `ufw` | `firewalld` | ★★★ |
| MAC | AppArmor | ★★★★ SELinux（改埠必做 `semanage`） | ★★★★ |
| 日誌 | `/var/log/auth.log` | `/var/log/secure` | ★★★ |

### 判斷準則

| 症狀 | 先查哪裡 | 星級 |
| --- | --- | --- |
| 完全連不上、`Connection refused` | 服務有沒有起來：`ss -lntp` | ★★★★★ |
| 完全連不上、`Connection timed out` | 防火牆／路由，不是 sshd | ★★★★ |
| `Permission denied (publickey)` | `sshd -T -C` 看該使用者的設定 + 家目錄權限 | ★★★★ |
| 設定看起來對但沒生效 | ★★★★★ `sshd -T`，然後 `grep -rn` 找誰蓋掉的 | ★★★★★ |
| 登入慢 20~30 秒 | `sshd -T \| grep usedns` | ★★★ |
| 改了 `Port` 沒用 | `systemctl is-enabled ssh.socket` | ★★★★ |
| 密碼還能登入 | `sshd -T \| grep kbdinteractive` | ★★★★★ |
| 日誌查不到連線 | `journalctl -t sshd`（不要用 `-u ssh`） | ★★★ |

---

## 練習題

> [!question]- 練習 1：找出「被誰蓋掉」★★★★
> 在測試機上執行以下操作，然後回答問題：
> ```bash
> echo 'PasswordAuthentication no' | sudo tee -a /etc/ssh/sshd_config
> printf 'PasswordAuthentication yes\n' | sudo tee /etc/ssh/sshd_config.d/50-test.conf
> sudo sshd -t && sudo systemctl reload ssh
> sudo sshd -T | grep -i passwordauthentication
> ```
> **問**：輸出是 `yes` 還是 `no`？為什麼？要讓它變成 `no`，在**不刪除 `50-test.conf`** 的前提下，
> 你要怎麼做？
>
> ---
> **參考解答**
>
> 輸出是 **`passwordauthentication yes`**。
>
> 原因：`/etc/ssh/sshd_config` 第 1 行是 `Include /etc/ssh/sshd_config.d/*.conf`，
> 所以 `50-test.conf` 比主檔末尾那行**更早**被讀到；而 sshd 的規則是
> **「第一個取得的值勝出」**（`man 5 sshd_config`：*the first obtained value will be used*）。
>
> 不刪 `50-test.conf` 的解法是建立一個**字典序更前面**的檔案：
> ```bash
> printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\n' \
>   | sudo tee /etc/ssh/sshd_config.d/10-gov-baseline.conf
> sudo sshd -t && sudo systemctl reload ssh
> sudo sshd -T | grep -Ei 'passwordauthentication|kbdinteractive'
> ```
> ```text
> passwordauthentication no
> kbdinteractiveauthentication no
> ```
> ★★★★ 記得順手把 `KbdInteractiveAuthentication` 也關掉，否則密碼登入還是通的。
> 收尾：`sudo rm /etc/ssh/sshd_config.d/50-test.conf` 並把主檔末尾那行拿掉。

> [!question]- 練習 2：實測自動回滾 timer ★★★★★
> 在**測試機**上刻意寫一個會把自己鎖在外面的設定，驗證回滾機制真的有效。
>
> ---
> **參考解答**
>
> ```bash
> # ① 先確認 sshd-rollback 存在且可執行，並先做一次備份建立 LATEST 指標
> sudo install -d -m 0700 /var/backups/sshd
> sudo tar -czf /var/backups/sshd/sshd-good.tar.gz -C / etc/ssh/sshd_config etc/ssh/sshd_config.d
> echo /var/backups/sshd/sshd-good.tar.gz | sudo tee /var/backups/sshd/LATEST
>
> # ② 上保險（縮短成 2 分鐘方便觀察）
> sudo systemd-run --on-active=2m --unit=sshd-rollback /usr/local/bin/sshd-rollback
>
> # ③ 刻意寫一個沒有人在裡面的群組
> printf 'AllowGroups nobody-at-all\n' | sudo tee /etc/ssh/sshd_config.d/99-break.conf
> sudo sshd -t && sudo systemctl reload ssh     # ★★★ 語法完全正確，sshd -t 不會擋
> ```
>
> ④ 從**另一個乾淨終端機**嘗試登入：
> ```text
> admin@10.10.0.20: Permission denied (publickey).
> ```
> 伺服器端日誌：
> ```text
> User admin from 10.10.0.5 not allowed because none of user's groups are listed in AllowGroups
> ```
>
> ⑤ 等 2 分鐘不要動。到期後再登入一次，應該就通了。檢查回滾日誌：
> ```bash
> sudo journalctl -t sshd-rollback -n 20 --no-pager
> ```
> ```text
> sshd-rollback[2103]: 開始還原 /var/backups/sshd/sshd-good.tar.gz
> sshd-rollback[2103]: 問題設定已保留於 /var/backups/sshd/failed-20260828-093012.tar.gz
> sshd-rollback[2103]: 已 reload ssh
> sshd-rollback[2103]: ★ 還原完成，目前生效設定：
> ```
> ★★★★★ 重點觀察兩件事：(a) `99-break.conf` 已經不見了（腳本先 `rm -rf sshd_config.d` 再解壓），
> (b) 問題設定被保留在 `failed-*.tar.gz`，事後查得到當時到底改了什麼。
> ★★★★ 這一題一定要在測試機做，而且務必先確認 console 進得去。

> [!question]- 練習 3：設計並驗證一組 Match 規則 ★★★★
> 需求：
> - 全域關閉所有 forwarding，關閉密碼登入，白名單 `ssh-users`
> - `ssh-admins` 群組**且**來自 `10.10.0.0/24` → 可以做埠轉發，但只能轉到 `10.10.0.30:3306`
> - `deploy` 帳號 → 只能執行 `/usr/local/bin/deploy.sh`，不給 TTY
>
> 寫出設定並用 `sshd -T -C` 驗證三種角色。
>
> ---
> **參考解答**
>
> ```ini
> # /etc/ssh/sshd_config.d/50-gov-baseline.conf
> PasswordAuthentication no
> KbdInteractiveAuthentication no
> AllowGroups ssh-users
> DisableForwarding yes
>
> # ★★★★★ 所有 Match 一定放最後
> Match Group ssh-admins Address 10.10.0.0/24
>     DisableForwarding no
>     AllowTcpForwarding yes
>     PermitOpen 10.10.0.30:3306
>
> Match User deploy
>     ForceCommand /usr/local/bin/deploy.sh
>     PermitTTY no
>     AllowTcpForwarding no
> ```
> ```bash
> sudo sshd -t && sudo systemctl reload ssh
> ```
> 驗證三種角色：
> ```bash
> sudo sshd -T -C user=ops01,host=pc01,addr=10.20.0.9 | grep -E '^(allowtcpforwarding|forcecommand)'
> ```
> ```text
> allowtcpforwarding no
> ```
> ```bash
> sudo sshd -T -C user=admin,host=mgmt01,addr=10.10.0.5 | grep -E '^(allowtcpforwarding|permitopen)'
> ```
> ```text
> allowtcpforwarding yes
> permitopen 10.10.0.30:3306
> ```
> ```bash
> sudo sshd -T -C user=deploy,host=ci01,addr=10.10.0.60 | grep -E '^(forcecommand|permittty)'
> ```
> ```text
> forcecommand /usr/local/bin/deploy.sh
> permittty no
> ```
> ★★★★ 注意 `admin` 必須同時在 `ssh-users`（過全域白名單）**和** `ssh-admins`（過 Match），
> 兩個群組缺一不可 —— 這是最容易漏掉的地方。
> ★★★ 另外 `Address` 條件比對的是**來源 IP**，不是主機名，所以 NAT 之後的來源要看實際看到的位址。

---

## 小測驗

Q1. `/etc/ssh/sshd_config` 第 1 行是 `Include /etc/ssh/sshd_config.d/*.conf`。你在主檔**最後一行**寫了 `PermitRootLogin no`，而 `sshd_config.d/50-cloud-init.conf` 裡有 `PermitRootLogin yes`。reload 之後 root 能不能用金鑰登入？為什麼？

Q2. 你設好 `PasswordAuthentication no` 並確認 `sshd -T` 顯示 `no`，但同事回報他還是能用密碼登入。最可能的原因是什麼？用哪一條指令證實？

Q3. 這行指令會發生什麼事：`sudo systemctl restart ssh`（在設定檔有語法錯誤的情況下）？換成 `reload` 又會怎樣？

Q4. 在 Ubuntu 24.04 上改了 `sshd_config` 的 `Port 2222`、reload 之後 `ss -lntp` 顯示還在聽 22，`Process` 欄寫的是 `systemd`。診斷與正確解法是什麼？

Q5. 你在 `ssh.socket` 的 drop-in 裡只寫了 `ListenStream=2222`（沒有先寫空的那行）。`ss -lntp` 會看到什麼？為什麼這是資安問題？

Q6. `MaxStartups 10:30:100` 的三個數字各代表什麼？使用者回報「有時候連得上有時候被拒」，跟這個設定有什麼關係？

Q7. 下面這段設定有什麼問題？

```ini
Match User backup
    ForceCommand /usr/local/bin/backup-only
PasswordAuthentication no
AllowGroups ssh-users
```

Q8. `sudo sshd -t` 通過了，是不是就代表可以安全地 reload？舉一個「語法正確但會把自己鎖在外面」的例子。

Q9. 稽核要求「能追出共用帳號是誰登入的」。你要改哪一個設定？改完之後日誌會多出什麼？有什麼副作用要一起處理？

Q10. 在 Rocky Linux 9 上，你在 `sshd_config` 寫了 `Ciphers aes256-gcm@openssh.com`，reload 之後 `sshd -T | grep ciphers` 卻是一長串預設值。原因是什麼？兩種解法各是什麼？

> [!question]- 測驗答案
> **Q1.** ★★★★★ **root 可以用金鑰登入**，也就是 `50-cloud-init.conf` 的 `yes` 勝出。
> `man 5 sshd_config` 明文寫著：*Unless noted otherwise, for each keyword, the first obtained
> value will be used.* —— **第一個讀到的值勝出**，不是最後一個。
> `Include` 在主檔第 1 行，所以 `sshd_config.d/` 的所有內容都比主檔其他行更早被讀到。
> 這跟 Nginx `conf.d`、systemd drop-in 的「後蓋前」直覺完全相反，是本篇最重要的陷阱。
> 驗證方式只有一個：
> ```bash
> sudo sshd -T | grep -i permitrootlogin
> ```
> ```text
> permitrootlogin yes
> ```
> 正解是把設定寫成 `sshd_config.d/10-gov-baseline.conf`（字典序在 `50-` 之前），
> 或直接清掉 `50-cloud-init.conf`。見「設定檔治理」與「觀念說明」。
>
> **Q2.** ★★★★★ 元凶是 **`KbdInteractiveAuthentication`**（預設 `yes`）。
> 它搭配 `UsePAM yes` 時會走 PAM 的 `pam_unix`，一樣會問密碼並驗證，
> 但走的是 `keyboard-interactive` 而不是 `password` 認證方法，
> 所以完全不受 `PasswordAuthentication no` 管轄。
> ```bash
> sudo sshd -T | grep -Ei 'passwordauthentication|kbdinteractiveauthentication'
> ```
> ```text
> passwordauthentication no
> kbdinteractiveauthentication yes     # ★★★★★ 就是它
> ```
> 實測：`ssh -o PubkeyAuthentication=no -o PreferredAuthentications=keyboard-interactive user@host`
> 會看到密碼提示。修法是補上 `KbdInteractiveAuthentication no`，
> 修完再測一次應該得到 `Permission denied (publickey).`。見「認證類」。
>
> **Q3.** ★★★★★ `restart` 會**先殺掉再啟動**，而啟動時解析設定檔失敗，sshd 起不來，
> 服務進入 `failed` 狀態 —— **所有人（包含你）都連不進去**，只剩 console／IPMI 能救。
> ```text
> Job for ssh.service failed because the control process exited with error code.
> ```
> `reload` 則安全得多：Ubuntu 的 `ssh.service` unit 裡有
> `ExecReload=/usr/sbin/sshd -t`，**語法檢查沒過就不會送 SIGHUP**，
> 舊設定與所有現有連線都原封不動，你還在線上，可以從容修正。
> ★★★★★ 這就是「改 sshd 一律 reload」的理由 —— 不是為了不中斷服務，是為了留住你的退路。
> 見「觀念說明 → reload 與 restart」與 [[17-systemd服務管理]]。
>
> **Q4.** ★★★★ 這台是 **socket 啟動模式**。`Process` 欄顯示 `systemd` 而不是 `sshd`
> 就是決定性線索 —— 監聽埠的是 `ssh.socket`，`sshd_config` 的 `Port` / `ListenAddress`
> 根本沒被使用。確認：
> ```bash
> systemctl is-enabled ssh.socket
> ```
> ```text
> enabled
> ```
> 解法 A（建議）：
> ```bash
> sudo systemctl edit ssh.socket
> # [Socket]
> # ListenStream=
> # ListenStream=2222
> sudo systemctl daemon-reload && sudo systemctl restart ssh.socket
> ```
> 解法 B：`systemctl disable --now ssh.socket`，刪掉
> `/etc/systemd/system/ssh.service.d/00-socket.conf`，再 `enable --now ssh.service`
> 回到傳統模式，`Port` 就恢復作用。見「Ubuntu 24.04：Port 要改在 ssh.socket」。
>
> **Q5.** ★★★★★ 會看到 **22 和 2222 同時在 LISTEN**：
> ```text
> LISTEN 0 4096 *:22   *:* users:(("systemd",...))
> LISTEN 0 4096 *:2222 *:* users:(("systemd",...))
> ```
> 因為 systemd 的 `ListenStream=` 是**列表型**指令，直接賦值是「追加」而非「取代」，
> 必須先寫一行空的 `ListenStream=` 把原值清掉。
> 資安問題在於：你以為埠已經換掉，防火牆規則、監控、fail2ban 都照 2222 設定，
> **但 22 埠還在對外裸奔**，暴力破解照樣打得進來而且可能沒有被監控到。
> 稽核抽查「SSH 服務埠」時會直接開缺失。同樣的列表語意也適用於 unit 的 `ExecStart=`，
> 見 [[01-systemd-unit撰寫實戰]]。
>
> **Q6.** ★★★ 三個數字是 `start:rate:full`，管的是**未認證連線數**（連上但還沒登入完成的）：
> - `10`：未認證連線數在 10 以內全部接受
> - `30`：超過 10 之後，以 **30%** 的機率隨機拒絕新連線（`30` 是百分比，不是秒也不是數量）
> - `100`：達到 100 時 100% 拒絕；10 到 100 之間拒絕機率線性上升
>
> 「有時候連得上有時候被拒」正是**隨機拒絕**的典型症狀，日誌會出現
> `beginning MaxStartups throttling` 或 `Connection closed by ... [preauth]`。
> 常見於跳板機、CI/CD 大量併發、或正在被掃描的對外主機。
> 解法是調大（例如 `30:30:200`），並縮短 `LoginGraceTime` 讓未認證連線更快釋放。見「認證類」。
>
> **Q7.** ★★★★★ **`Match` 之後的所有內容都屬於該 Match 區塊**，直到檔案結尾或下一個 `Match`。
> 所以 `PasswordAuthentication no` 和 `AllowGroups ssh-users` 變成
> 「**只有 backup 這個使用者**才關密碼、才需要在 ssh-users 群組」，
> **全域完全沒有這兩項設定** —— 其他所有人的密碼登入都是開著的。
> 致命之處在於 `sudo sshd -t` **完全不會報錯**（語法合法），
> 偵測方法是 `sudo sshd -T`（不帶 `-C`）：會看到 `passwordauthentication yes`。
> 正確寫法是把全域設定移到第一個 `Match` **之前**，所有 `Match` 區塊放在檔案最後。
> 見「Match 區塊 → 鐵律一」。
>
> **Q8.** ★★★★★ **不代表**。`sshd -t` 只驗語法（能不能解析），完全不驗語意。
> 三個「語法正確但會鎖死自己」的經典例子：
> 1. `AllowGroups ssh-users` 但你不在該群組 → 服務正常，你進不去
> 2. `ListenAddress 10.10.0.99`（這台沒有這個 IP）→ 重開機後 sshd 起不來
> 3. `PubkeyAuthentication no` + `PasswordAuthentication no` + `KbdInteractiveAuthentication no`
>    → 沒有任何認證方式，誰都登不進來
>
> 所以語法檢查之後還要做：`sshd -T` 驗生效值、`sshd -T -C` 驗每種角色、
> `id` 確認自己在群組裡、另一個埠前景試跑、以及自動回滾 timer。
> 本篇的 `sshd-apply` 腳本把第 3 種情況做成硬性中止。見「不鎖門 SOP」。
>
> **Q9.** ★★★★ 改 `LogLevel INFO` 為 **`LogLevel VERBOSE`**。
> ```ini
> LogLevel VERBOSE
> ```
> 日誌會多出金鑰比對的細節，關鍵是這一行：
> ```text
> sshd[1421]: Found matching ED25519 key: SHA256:9Xk4mZ...
> ```
> 有了指紋，就能用 `ssh-keygen -lf ~/.ssh/authorized_keys` 把它對回**是哪個人的金鑰**，
> 這是共用帳號情境下**唯一**能追到人的線索。
>
> 副作用與配套：日誌量會明顯變大，尤其對外主機被掃描時。必須一起處理
> (a) journald 上限（`SystemMaxUse=`）、(b) `auth.log` 的 logrotate、
> (c) 稽核要求的保存期限（常見 6 個月）本機留不住就送集中日誌。
> ★★★ 另外**不要**用 `DEBUG` 當常態設定，`man 5 sshd_config` 明確警告它違反使用者隱私。
> 見「日誌」與 [[19-日誌系統]]。
>
> **Q10.** ★★★★ 原因是 RHEL 系的 `/etc/sysconfig/sshd` 有 `CRYPTO_POLICY=` 這行，
> 它會把 `/etc/crypto-policies/back-ends/opensshserver.config` 的內容
> **以命令列參數的形式**傳給 sshd，而**命令列優先於設定檔**，
> 所以你在 `sshd_config` 寫的 `Ciphers` / `MACs` / `KexAlgorithms` 全部被覆蓋。
> ```bash
> grep -n CRYPTO_POLICY /etc/sysconfig/sshd
> update-crypto-policies --show
> ```
> 兩種解法：
> ```bash
> # A（建議）改系統政策，全機一致、稽核好交代
> sudo update-crypto-policies --set FUTURE
> sudo systemctl reload sshd
>
> # B 讓 sshd_config 說了算（等於這台脫離全機政策，要寫進變更紀錄）
> sudo sed -i 's/^CRYPTO_POLICY=/#CRYPTO_POLICY=/' /etc/sysconfig/sshd
> sudo systemctl restart sshd
> ```
> 演算法清單本身怎麼選，見 [[07-SSH-安全強化]]。此題見「RHEL 系對照」摺疊區塊。

---

## 延伸閱讀

- [[07-SSH-安全強化]] —— 演算法清單、`ssh-audit` 掃描、2FA、SSH CA、fail2ban 整合，本篇刻意留給它的部分
- [[02-SSH-金鑰認證與ssh-agent]] —— 關掉密碼登入的前提，authorized_keys 的選項與 agent 的正確用法
- [[06-SFTP-與受限使用者]] —— `ChrootDirectory` + `ForceCommand internal-sftp` 的完整做法與權限地雷
- [[05-SSH-隧道與埠轉發]] —— 本篇只講伺服器端「准不准」，客戶端 `-L` / `-R` / `-D` 怎麼用看這篇
- [[03-SSH-客戶端設定檔]] —— `ProxyJump`、`ControlMaster`；驗證新設定時 `ControlPath=none` 為何重要
- [[17-systemd服務管理]] —— `reload` / `restart` / `systemctl edit` drop-in 的完整說明
- [[19-日誌系統]] —— journald 與 rsyslog 的分工、保存期限、`journalctl` 進階過濾
- [[04-TWGCB-Linux本機導入]] —— 政府組態基準對 SSH 的具體項目與導入方式
- [[02-防火牆-ufw基礎與實務]] —— SSH 埠的放行與來源限制
- [[02-基準設定與範本化]] —— 把 `sshd_config.d/` 納入組態管理與版控的做法
- OpenSSH `sshd_config` 官方手冊：<https://man.openbsd.org/sshd_config>
- OpenSSH `sshd` 官方手冊（`-t` / `-T` / `-C` 的完整說明）：<https://man.openbsd.org/sshd>
- Ubuntu 官方公告：SSHd now uses socket-based activation：<https://discourse.ubuntu.com/t/sshd-now-uses-socket-based-activation-ubuntu-22-10-and-later/30189>
- Ubuntu 24.04 `sshd_config` manpage：<https://manpages.ubuntu.com/manpages/noble/en/man5/sshd_config.5.html>
