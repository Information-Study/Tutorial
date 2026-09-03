---
title: "Fail2ban 入侵防護"
desc: "jail/filter/action 三層架構、jail.local 正確改法、banaction 選錯不生效、自訂 filter 與誤封解除"
aliases: [fail2ban, jail, jail.local, fail2ban-regex, banaction, bantime.increment]
tags: [群組/資訊安全, 安全/防護, 主題/防護]
category: 系統與網路防護
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-02-01-04-svc-sshd-伺服器端設定]]"]
updated: 2026-09-03
---

# Fail2ban 入侵防護

> [!abstract] 這篇你會學到
> - ★★★★ **防火牆擋不到的那一半**：firewall 擋的是「不該連的來源」，
>   Fail2ban 擋的是「**連得進來、但一直猜密碼**的來源」
> - jail／filter／action 三層架構，以及 Fail2ban 是怎麼把封鎖動作交給防火牆執行的
> - ★★★★★ **`banaction` 選錯，Fail2ban 會回報「已封鎖」但對方照樣連得進來** ——
>   `ufw`／`nftables`／`iptables` 三種後端怎麼挑
> - ★★★★★ **設定一律改 `jail.local`，不要動 `jail.conf`** —— 套件更新會直接覆蓋 `.conf`
> - `maxretry`／`findtime`／`bantime` 三個參數的關係，以及 `bantime.increment` 遞增封鎖
> - ★★★★★ **`ignoreip` 一定要先把機關網段與管理主機加進去**，否則自己人打錯兩次密碼就進不來
> - 用 `fail2ban-regex` 從一段真實日誌**完整走一遍**自訂 filter 的開發流程
> - ★★★★ 與 **nftables set** 的整合：封鎖數千個 IP 時，逐條規則會拖垮效能，set 才是正解
> - 完整實戰：從安裝到「故意打錯密碼觸發封鎖 → 確認被擋 → 解封」的全流程驗證

> [!warning] 未實機驗證
> 本篇主線為 **Ubuntu 24.04 LTS（fail2ban 1.0.2）**，內容依官方
> `jail.conf` 註解、`man jail.conf`、`man fail2ban-client` 與 `action.d/` 內建動作檔撰寫。
> 撰稿環境沒有長期保留的實體伺服器完整驗證每一段輸出，**尤其是
> nftables set 名稱與 `bantime.increment` 的實際遞增秒數會隨版本不同**。
> 導入前請在測試機上照「完整實戰範例」跑一次，並用該機器上的
> `fail2ban-client status <jail>` 與 `nft list ruleset` 對答案，不要照抄本篇輸出當事實。

## 前置知識

- [[020-02-01-04-svc-sshd-伺服器端設定]] —— Fail2ban 讀的就是 sshd 產生的日誌
- [[020-02-01-07-svc-SSH-安全強化]] —— ★★★★ **先關掉密碼登入**，Fail2ban 是第二道，不是第一道
- [[090-02-02-guide-防火牆-ufw基礎與實務]] —— Ubuntu 主線的防火牆，`banaction = ufw` 會用到
- [[090-02-03-guide-防火牆-nftables與iptables]] —— set 整合那一段的基礎
- [[020-01-19-guide-Linux-日誌系統]] —— journald 與 `/var/log/auth.log` 的關係，這是本篇最大的坑
- [[020-01-12-cmd-Linux-文字處理三劍客]] —— 寫 filter 的正則基礎

## 觀念說明

### 先看一段真實的日誌 ★★★★★

這是一台開在公網上、開機不到兩小時的機器，`/var/log/auth.log` 的片段：

```text
Sep  3 03:12:41 web01 sshd[24817]: Failed password for root from 203.0.113.66 port 51234 ssh2
Sep  3 03:12:43 web01 sshd[24817]: Failed password for root from 203.0.113.66 port 51234 ssh2
Sep  3 03:12:45 web01 sshd[24817]: Failed password for root from 203.0.113.66 port 51234 ssh2
Sep  3 03:12:45 web01 sshd[24817]: Connection closed by authenticating user root 203.0.113.66 port 51234 [preauth]
Sep  3 03:12:47 web01 sshd[24819]: Invalid user admin from 203.0.113.66 port 51290
Sep  3 03:12:47 web01 sshd[24819]: Failed password for invalid user admin from 203.0.113.66 port 51290 ssh2
Sep  3 03:12:49 web01 sshd[24821]: Invalid user oracle from 203.0.113.66 port 51344
Sep  3 03:12:49 web01 sshd[24821]: Failed password for invalid user oracle from 203.0.113.66 port 51344 ssh2
Sep  3 03:12:52 web01 sshd[24823]: Invalid user postgres from 198.51.100.14 port 44012
Sep  3 03:12:52 web01 sshd[24823]: Failed password for invalid user postgres from 198.51.100.14 port 44012 ssh2
```

數一下：**11 秒內 8 次登入失敗，來自 2 個來源，試了 root / admin / oracle / postgres 四個帳號。**
這不是打錯密碼，是自動化字典攻擊。這種東西一天可以打進來幾萬次。

現在問一個關鍵問題：

> **防火牆能擋這個嗎？**

不能。防火牆的規則是「允許來源 X 連 22 埠」。這個攻擊者**符合規則** ——
他就是從允許的來源（因為你的 ssh 對外開放）連了允許的埠。防火牆做完它的工作了。

### 兩者的分工 ★★★★★

```text
                     ┌──────────────────────────────────────────┐
   封包進來 ───────▶ │ 防火牆（ufw / firewalld / nftables）      │
                     │ 問題：「這個來源該不該連這個埠？」          │
                     │ 判斷依據：來源 IP、目的埠 —— 靜態規則       │
                     └────────────────┬─────────────────────────┘
                                      │ 通過（他是合法的連線請求）
                                      ▼
                     ┌──────────────────────────────────────────┐
                     │ 服務（sshd / nginx / postfix …）           │
                     │ 問題：「這個人的帳密對不對？」               │
                     │ 密碼錯 → 寫一行 log → 對方再試一次           │
                     └────────────────┬─────────────────────────┘
                                      │ 產生失敗日誌
                                      ▼
                     ┌──────────────────────────────────────────┐
   ★★★★★           │ Fail2ban                                  │
                     │ 問題：「這個來源在 X 秒內失敗了幾次？」        │
                     │ 超過門檻 → 回頭叫防火牆把他擋掉一段時間        │
                     └────────────────┬─────────────────────────┘
                                      │ 呼叫 ufw / nft / iptables
                                      └──▶ 動態新增一條封鎖規則
```

★★★★★ 一句話總結：
**Fail2ban 是「讀日誌 → 找出行為異常的 IP → 叫防火牆去擋」的自動化機器人。**
它自己**沒有任何封包處理能力**，全部靠防火牆執行。

這也直接推出本篇最重要的一個結論：
★★★★★ **如果 Fail2ban 呼叫的是「你這台機器上沒在用的那套防火牆」，
它會顯示封鎖成功，但實際上什麼都沒擋。** 這就是後面 `banaction` 那一段要解決的問題。

### 三層架構：jail / filter / action ★★★★

```text
┌── jail（監獄）────────────────────────────────────────────┐
│  「監看哪個日誌、用哪個 filter、超過幾次、用哪個 action 擋」    │
│                                                            │
│  [sshd]                                                    │
│  enabled  = true                                           │
│  logpath  = /var/log/auth.log   ← 監看什麼                  │
│  filter   = sshd                ─────┐                     │
│  maxretry = 5                        │                     │
│  findtime = 10m                      │                     │
│  bantime  = 1h                       │                     │
│  banaction = ufw                ─────┼──┐                  │
└──────────────────────────────────────┼──┼─────────────────┘
                                       │  │
        ┌──────────────────────────────┘  │
        ▼                                 ▼
┌── filter（篩選器）──────────┐   ┌── action（動作）─────────────┐
│ /etc/fail2ban/filter.d/     │   │ /etc/fail2ban/action.d/      │
│   sshd.conf                 │   │   ufw.conf                   │
│                             │   │   nftables-multiport.conf    │
│ 一組正則，把「失敗」那幾行   │   │   iptables-multiport.conf    │
│ 挑出來，並用 <HOST> 標出     │   │                              │
│ 犯人的 IP                   │   │ actionban   = 怎麼擋          │
│                             │   │ actionunban = 怎麼放          │
└─────────────────────────────┘   └──────────────────────────────┘
```

| 層 | 回答什麼問題 | 檔案位置 | 星級 |
| --- | --- | --- | --- |
| **jail** | 監看誰、門檻多少、擋多久 | `/etc/fail2ban/jail.local`（★★★★★ 你改這個） | ★★★★★ |
| **filter** | 日誌裡哪一行算「失敗」、犯人 IP 在哪 | `/etc/fail2ban/filter.d/*.conf` | ★★★★ |
| **action** | 用什麼手段擋、怎麼解 | `/etc/fail2ban/action.d/*.conf` | ★★★★★ |

★★★ 想像成法院：**filter 是警察（認出犯人）、jail 是法官（判幾次、關多久）、action 是獄卒（實際關人）。**
三個角色缺一不可，而且各自可能出錯 —— 排錯時要能分辨是哪一層壞了。

### `<HOST>` 是整個 filter 的核心 ★★★★★

filter 的正則裡，`<HOST>` 是 Fail2ban 定義的特殊標記，代表「**這裡是犯人的 IP，把它抓出來**」。
沒有 `<HOST>` 的正則，就算比對成功也**不會產生任何封鎖**（Fail2ban 不知道要擋誰）。

```ini
# /etc/fail2ban/filter.d/sshd.conf（節錄示意）
[Definition]
failregex = ^%(__prefix_line)sFailed \S+ for .* from <HOST>( port \d+)?( ssh\d*)?$
```

★★★★ Fail2ban 會把 `<HOST>` 展開成一段同時能配 IPv4／IPv6／主機名的正則。
你自己寫 filter 時**永遠用 `<HOST>`，不要自己寫 `(\d+\.\d+\.\d+\.\d+)`** ——
自己寫的會漏 IPv6，而現在的攻擊來源有相當比例是 IPv6。

## 環境準備與安裝

### 安裝

```bash
$ sudo apt update && sudo apt install -y fail2ban
...
Setting up fail2ban (1.0.2-3ubuntu0.1) ...
Created symlink /etc/systemd/system/multi-user.target.wants/fail2ban.service → /usr/lib/systemd/system/fail2ban.service.

$ fail2ban-server --version
Fail2Ban v1.0.2
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> Fail2ban 不在 RHEL 官方庫，要先開 EPEL：
> ```bash
> sudo dnf install -y epel-release
> sudo dnf install -y fail2ban fail2ban-firewalld
> sudo systemctl enable --now fail2ban
> ```
> ★★★★ 三個關鍵差異：
> 1. **日誌路徑不同** —— RHEL 是 `/var/log/secure`，不是 `/var/log/auth.log`。
>    但 `paths-fedora.conf` 已經處理好了，用 `%(sshd_log)s` 就會自動指對。
> 2. **`banaction` 要用 firewalld 的** —— 裝了 `fail2ban-firewalld` 之後，
>    `/etc/fail2ban/jail.d/00-firewalld.conf` 會把 `banaction` 設成 `firewallcmd-rich-rules`。
>    ★★★★★ **不要再自己設成 `ufw`**，RHEL 上根本沒有 ufw。
> 3. **建議改用 ipset 版本**：封鎖量大時 `banaction = firewallcmd-ipset` 效能遠優於逐條 rich rule。
>    詳見〈進階設定與調校〉的「與 nftables set 的整合」。
>
> firewalld 本身的操作見 [[090-02-04-guide-防火牆-firewalld]]。

### ★★★★★ 步驟 0：先確認日誌到底在哪

這是 Ubuntu 24.04 最大的坑，**不先處理的話後面全部白做**。

```bash
$ ls -l /var/log/auth.log
ls: cannot access '/var/log/auth.log': No such file or directory
```

★★★★★ **Ubuntu 24.04 預設不安裝 rsyslog，所以 `/var/log/auth.log` 根本不存在** ——
所有認證日誌只進 systemd-journald。而 `jail.conf` 裡的 sshd jail 預設指向 `/var/log/auth.log`。
結果就是：

```bash
$ sudo systemctl status fail2ban
● fail2ban.service - Fail2Ban Service
     Loaded: loaded (/usr/lib/systemd/system/fail2ban.service; enabled)
     Active: failed (Result: exit-code) since Wed 2026-09-03 09:41:02 CST
...
fail2ban-server[1832]: ERROR  Failed during configuration: Have not found any log file for sshd jail
fail2ban-server[1832]: ERROR  Async configuration of server failed
```

**兩種解法，選一個：**

| 解法 | 做法 | 建議 |
| --- | --- | --- |
| A. ★★★★★ 讓 Fail2ban 直接讀 journal | 在 jail 裡設 `backend = systemd` | **建議這個**。不用多裝套件，也不用煩惱日誌輪替 |
| B. 把 rsyslog 裝回來 | `sudo apt install -y rsyslog` → 重開 sshd 後 `/var/log/auth.log` 就會出現 | 已經有集中式 syslog 架構（[[100-01-02-guide-日誌-日誌集中與輪替]]）時才選 |

先確認 journal 裡真的有東西：

```bash
$ sudo journalctl -u ssh -n 5 --no-pager
Sep 03 09:38:12 web01 sshd[1502]: Failed password for root from 203.0.113.66 port 51234 ssh2
Sep 03 09:38:14 web01 sshd[1502]: Failed password for root from 203.0.113.66 port 51234 ssh2
...
```

★★★ Ubuntu 的 sshd unit 叫 `ssh.service`（不是 `sshd.service`），但 journal 裡的
`_COMM` 仍是 `sshd`，所以內建 filter 的 `journalmatch` 抓得到。RHEL 上 unit 就叫 `sshd.service`。

### 檢視預設狀態

```bash
$ sudo fail2ban-client status
Status
|- Number of jail:      1
`- Jail list:   sshd
```

★★★★ Ubuntu／Debian 只預設啟用 `sshd` 一個 jail，來自：

```bash
$ cat /etc/fail2ban/jail.d/defaults-debian.conf
[sshd]
enabled = true
```

其他 jail（nginx、postfix…）在 `jail.conf` 裡都是 `enabled = false`，要自己開。

## 基礎設定

### ★★★★★ 第一課：只改 `jail.local`，不要碰 `jail.conf`

```bash
$ head -25 /etc/fail2ban/jail.conf
#
# WARNING: heavily refactored in 0.9.0 release.  Please review and
#          customize settings for your setup.
#
# Changes:  in most of the cases you should not modify this
#           file, but provide customizations in jail.local file,
#           or separate .conf files under jail.d/ directory, e.g.:
#
# HOW TO ACTIVATE JAILS:
...
```

**官方檔案第一行就在叫你不要改它。** 理由很實際：

> [!danger] ★★★★★ 改 `jail.conf` = 下一次 `apt upgrade` 你的設定全部消失
> `jail.conf` 是套件檔案。`apt upgrade fail2ban` 時 dpkg 會問你要不要覆蓋，
> **無人值守更新（unattended-upgrades）則直接照套件維護者的設定處理**，
> 你辛苦調的 `bantime` 與 `ignoreip` 就這樣沒了 —— 而且不會有人通知你。
>
> 最惡劣的情況是 **`ignoreip` 被還原**：機關網段不再被豁免，
> 隔天早上全單位的人打錯一次密碼就被鎖在外面。
> **救援方法**：`sudo fail2ban-client unban --all` 立刻放光所有封鎖，再補回 `jail.local`。

**設定檔的讀取順序（後讀的蓋前讀的）** ★★★★★：

```text
① /etc/fail2ban/jail.conf              ← 套件提供，全部預設值。不要改
② /etc/fail2ban/jail.d/*.conf          ← 套件／發行版的客製（依檔名字典序）
③ /etc/fail2ban/jail.local             ← ★★★★★ 你改這裡
④ /etc/fail2ban/jail.d/*.local         ← 更細的分檔（大型環境用）
```

同樣的規則適用於整個 Fail2ban：

| 不要改 | 改這個 | 用途 |
| --- | --- | --- |
| `/etc/fail2ban/fail2ban.conf` | `/etc/fail2ban/fail2ban.local` | 守護程序本身（log level、資料庫） |
| `/etc/fail2ban/jail.conf` | ★★★★★ `/etc/fail2ban/jail.local` | jail 設定（**最常改的**） |
| `/etc/fail2ban/filter.d/sshd.conf` | `/etc/fail2ban/filter.d/sshd.local` | 微調內建 filter |
| `/etc/fail2ban/action.d/ufw.conf` | `/etc/fail2ban/action.d/ufw.local` | 微調內建 action |

★★★★ **`.local` 只需要寫「要覆蓋的那幾行」，不用整份複製。**
很多教學叫你 `cp jail.conf jail.local`，那是**壞習慣** ——
複製過來的 900 行會讓你看不出自己到底改了什麼，日後也吃不到套件更新的新預設值。

### 最小可用的 `jail.local` ★★★★★

```bash
$ sudo tee /etc/fail2ban/jail.local >/dev/null <<'EOF'
[DEFAULT]
# ── ★★★★★ 白名單：機關網段與管理主機，一定要先寫 ──
ignoreip = 127.0.0.1/8 ::1 10.10.0.0/24 10.20.5.0/24

# ── 判定門檻 ──
findtime = 10m
maxretry = 5
bantime  = 1h

# ── ★★★★★ 封鎖後端：Ubuntu 用 ufw ──
banaction = ufw

# ── Ubuntu 24.04 沒有 /var/log/auth.log，直接讀 journal ──
backend = systemd

[sshd]
enabled  = true
port     = ssh
maxretry = 4
bantime  = 2h
EOF
```

逐行解釋：

| 設定 | 意義 | 星級 |
| --- | --- | --- |
| `[DEFAULT]` | ★★★★ 這一段的值會被**所有 jail 繼承**，個別 jail 可以再覆寫 | ★★★★ |
| `ignoreip` | ★★★★★ **永遠不封鎖的來源**。空白分隔，可寫 IP、CIDR、DNS 名稱 | ★★★★★ |
| `findtime = 10m` | 「觀察窗」—— 在這段時間內累計失敗次數 | ★★★★ |
| `maxretry = 5` | 觀察窗內失敗超過這個數就封鎖 | ★★★★ |
| `bantime = 1h` | 封鎖多久。★★★ 設 `-1` 代表永久 | ★★★★ |
| `banaction = ufw` | ★★★★★ 用哪套防火牆執行封鎖。**選錯就不會生效** | ★★★★★ |
| `backend = systemd` | 從 journald 讀日誌，而不是讀檔案 | ★★★★★ |
| `port = ssh` | 要封鎖的目的埠。★★★ sshd 換過埠的話這裡要跟著改成 `2222` | ★★★★ |

套用：

```bash
$ sudo fail2ban-client -t
OK: configuration test is successful

$ sudo systemctl restart fail2ban
$ sudo fail2ban-client status sshd
Status for the jail: sshd
|- Filter
|  |- Currently failed: 0
|  |- Total failed:     18
|  `- Journal matches:  _SYSTEMD_UNIT=sshd.service + _COMM=sshd
`- Actions
   |- Currently banned: 0
   |- Total banned:     0
   `- Banned IP list:
```

★★★★★ **`fail2ban-client -t` 是每次改設定後的必跑指令。**
它會把所有 `.conf` + `.local` 合併起來檢查語法，**在重啟之前**告訴你有沒有寫錯。
語法錯了直接 restart 的話，服務會 failed，**你的機器就完全沒有暴力破解防護了**，
而且通常沒人會發現。

### ★★★★★ `banaction`：選錯不會有任何錯誤訊息

這是本篇第二重要的一段。Fail2ban 的 `actionban` 只是去執行一行 shell 指令，
**那行指令有沒有真的擋到人，Fail2ban 不會驗證。**

```bash
$ ls /etc/fail2ban/action.d/ | grep -E '^(ufw|nftables|iptables|firewallcmd)'
firewallcmd-allports.conf
firewallcmd-ipset.conf
firewallcmd-multiport.conf
firewallcmd-rich-rules.conf
iptables-allports.conf
iptables-multiport.conf
iptables.conf
nftables-allports.conf
nftables-multiport.conf
nftables.conf
ufw.conf
```

**怎麼挑：先看你這台機器實際在用哪套防火牆。**

```bash
$ sudo ufw status | head -1
Status: active                    # → banaction = ufw

$ systemctl is-active nftables    # 沒有 ufw、直接用 nftables 的話
active                            # → banaction = nftables-multiport

$ sudo firewall-cmd --state       # RHEL 系
running                           # → banaction = firewallcmd-rich-rules 或 firewallcmd-ipset
```

| 你的防火牆 | `banaction` 應該設 | 說明 | 星級 |
| --- | --- | --- | --- |
| ufw（Ubuntu 主線） | `ufw` | ★★★★★ 呼叫 `ufw insert 1 deny from <IP>`，規則插在最前面 | ★★★★★ |
| 純 nftables | `nftables-multiport` | ★★★★ 用 nftables **set** 存封鎖名單，效率最好 | ★★★★★ |
| 純 nftables、要擋所有埠 | `nftables-allports` | 不分埠全擋。recidive jail 常用 | ★★★★ |
| iptables（舊系統） | `iptables-multiport` | 傳統做法，逐條規則 | ★★★ |
| firewalld（RHEL） | `firewallcmd-rich-rules` | 每個封鎖產生一條 rich rule | ★★★★ |
| firewalld + 大量封鎖 | `firewallcmd-ipset` | ★★★★ 用 ipset，數千筆也不掉效能 | ★★★★ |

> [!danger] ★★★★★ 選錯 `banaction` 的症狀：一切看起來都正常，但完全沒擋
> 典型情境：Ubuntu 上開著 ufw，但 `banaction` 留在預設的 `iptables-multiport`。
>
> ```bash
> $ sudo fail2ban-client status sshd
>    |- Currently banned: 3
>    `- Banned IP list:   203.0.113.66 198.51.100.14 192.0.2.7
> ```
> **Fail2ban 說擋了三個。** 但 ufw 是用自己的一套 iptables chain 結構，
> Fail2ban 插進 `INPUT` 的規則可能排在 ufw 的規則後面而永遠比對不到 ——
> 對方照樣連得進來繼續猜密碼。
>
> **驗證方法（★★★★★ 每次設定完都要做一次）**：
> ```bash
> # ufw
> sudo ufw status numbered | head -5
> # nftables
> sudo nft list ruleset | grep -A5 'f2b'
> # iptables
> sudo iptables -L f2b-sshd -n --line-numbers
> ```
> **在防火牆那一側看得到封鎖規則，才叫真的擋住了。**

用 `ufw` 後端時，封鎖成功長這樣：

```bash
$ sudo ufw status numbered | head -5
Status: active

     To                         Action      From
     --                         ------      ----
[ 1] Anywhere                   DENY IN     203.0.113.66
[ 2] 22/tcp                     ALLOW IN    10.10.0.0/24
```

★★★★ 注意封鎖規則在 **`[1]`** —— `ufw` action 用的是 `ufw insert 1`，
**一定要插在所有 allow 規則前面**，否則 allow 先命中就擋不到了。

### ★★★★★ `ignoreip`：先寫白名單，再開 jail

> [!danger] ★★★★★ 沒設 `ignoreip` 的下場
> 情境：機關的 NAT 出口是單一 IP，全單位五百人共用。
> 早上有三個人各打錯兩次密碼 → 對 Fail2ban 來說就是「同一個 IP 在 10 分鐘內失敗 6 次」
> → **整個機關被封鎖一小時**，包含所有維運人員。
>
> 更糟的是：如果你也在那個 NAT 後面，**你自己也進不去了**。
>
> **救援方法（依可用性排序）**：
> 1. 從**不在** NAT 後面的來源（手機熱點、其他機房）ssh 進去 → `fail2ban-client unban --all`
> 2. 主機 console／IPMI／PVE noVNC → `systemctl stop fail2ban` 再慢慢修
> 3. ★★★ 兩者都沒有 → 只能請機房人員到現場。**所以第 1、2 條一定要事先準備好。**

必須放進 `ignoreip` 的東西：

| 項目 | 例 | 星級 |
| --- | --- | --- |
| localhost | `127.0.0.1/8 ::1` | ★★★★ |
| ★★★★★ 機關對外 NAT 出口 IP | `203.0.113.10/32` | ★★★★★ |
| ★★★★★ 管理／跳板主機網段 | `10.10.0.0/24` | ★★★★★ |
| 監控主機 | `10.10.0.80/32` | ★★★★ |
| VPN 配發網段 | `10.99.0.0/24` | ★★★★ |
| 備份主機、CI runner | `10.20.9.0/24` | ★★★ |

```ini
[DEFAULT]
ignoreip = 127.0.0.1/8 ::1 10.10.0.0/24 10.20.5.0/24 203.0.113.10/32
```

★★★ 也可以用 DNS 名稱（`ignoreip = jump.example.gov.tw`），但**不建議** ——
DNS 掛掉時解析不出來，白名單就失效了。**用 IP。**

驗證白名單有沒有生效：

```bash
$ sudo fail2ban-client get sshd ignoreip
These IP addresses/networks are ignored:
|- 127.0.0.1/8
|- ::1
|- 10.10.0.0/24
|- 10.20.5.0/24
`- 203.0.113.10/32
```

★★★ 另有一個預設開啟的 `ignoreself = true`，會自動忽略本機所有介面的 IP。
建議保持開啟，但**它不涵蓋你的管理網段**，`ignoreip` 還是要自己寫。

### 三個門檻參數的關係 ★★★★

```text
findtime = 10m  ┌───────── 觀察窗（滑動）──────────┐
                │ ✗   ✗      ✗    ✗       ✗       │
時間軸 ─────────┼──────────────────────────────────┼──────────────▶
                │ 1   2      3    4       5        │
                └──────────────────────────────────┘
                                                   ▲
                              maxretry = 5 達標 ────┘
                                                   │
                                    ┌──────────────┴──────────────┐
                                    │  bantime = 1h  封鎖一小時    │
                                    └─────────────────────────────┘
```

| 情境 | `findtime` | `maxretry` | `bantime` | 說明 |
| --- | --- | --- | --- | --- |
| ★★★★ 一般伺服器（建議起點） | `10m` | `5` | `1h` | 誤封風險低、對機器人夠煩 |
| ★★★★ 對外公網 ssh | `10m` | `3` | `24h` | 公網上不該有人打錯三次 |
| ★★★ 內部系統、使用者多 | `30m` | `10` | `15m` | 寬鬆，優先避免誤封 |
| ★★★★★ 已關密碼登入、純金鑰 | `10m` | `3` | `-1`（永久） | 反正正常人不會用密碼失敗 |
| ★★ Web 登入頁 | `5m` | `10` | `30m` | Web 使用者打錯機率高得多 |

★★★★ **時間單位可以寫 `600`（秒）、`10m`、`1h`、`1d`、`1w`。建議用有單位的寫法**，
`bantime = 600` 到底是 10 分鐘還是別的，半年後你自己也不確定。

### 常用 jail ★★★★

在 `jail.local` 加上要啟用的 jail。**只開你這台機器真的有跑的服務** ——
開了不存在的服務，jail 會因為找不到日誌而讓整個 fail2ban 起不來。

```ini
# ── SSH ──★★★★★ 每台都要開
[sshd]
enabled  = true
port     = ssh
maxretry = 4
bantime  = 2h

# ── Nginx HTTP Basic 認證失敗 ──★★★★
[nginx-http-auth]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/error.log
maxretry = 5

# ── Nginx 掃描器（找 /wp-admin、/.env、/phpmyadmin 之類）──★★★★
[nginx-botsearch]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/access.log
maxretry = 3
bantime  = 12h

# ── Nginx limit_req 被觸發（要先在 nginx 設 limit_req）──★★★
[nginx-limit-req]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/error.log
maxretry = 10

# ── ★★★★ 累犯：被同一個 jail 反覆封鎖的常客，直接關一週 ──
[recidive]
enabled   = true
logpath   = /var/log/fail2ban.log
banaction = %(banaction_allports)s
bantime   = 1w
findtime  = 1d
maxretry  = 5
```

| jail | 監看什麼 | 需要的前置條件 | 星級 |
| --- | --- | --- | --- |
| `sshd` | ssh 登入失敗 | 無 | ★★★★★ |
| `nginx-http-auth` | Nginx Basic Auth 失敗 | 有用 `auth_basic` | ★★★★ |
| `nginx-botsearch` | 掃描常見後台路徑 | Nginx access log | ★★★★ |
| `nginx-limit-req` | 觸發 Nginx 速率限制 | ★★★ 必須先在 Nginx 設 `limit_req_zone`，見 [[060-02-02-09-guide-Nginx-安全設定]] | ★★★ |
| `nginx-bad-request` | 大量畸形請求 | Nginx access log | ★★ |
| `recidive` | ★★★★ **Fail2ban 自己的日誌** —— 抓反覆被封的常客 | 需要 `/var/log/fail2ban.log` | ★★★★ |
| `postfix`、`dovecot`、`sasl` | 郵件服務暴力破解 | ★ **本手冊不涵蓋郵件伺服器**，此處僅列出供參考，不提供設定教學 | ★ |

> [!note] ★ 關於郵件相關 jail
> `jail.conf` 裡有 `postfix`、`postfix-sasl`、`dovecot`、`sieve` 等一整組郵件 jail。
> **本手冊已明確排除郵件伺服器主題**（Postfix／Dovecot／rspamd 不在範圍內），
> 所以這裡只說明它們存在、以及開啟方式與其他 jail 相同，不提供調校建議。
> 如果你的環境真的有郵件主機，`postfix-sasl` 通常是最值得開的一個 ——
> SMTP AUTH 是暴力破解的重災區。

> [!warning] ★★★★ `recidive` 的 `banaction_allports`
> `recidive` 抓的是「已經被別的 jail 關過很多次」的頑固份子，
> 這種來源**不該只擋單一埠**，所以用 `banaction_allports`（`nftables-allports` / `iptables-allports`）
> 把他所有埠都擋掉。★★★ 用 ufw 後端時 `ufw` action 本來就是全埠 deny，不用另外處理。

### 讓 `recidive` 有東西可讀 ★★★

`recidive` 讀的是 `/var/log/fail2ban.log`。Ubuntu 24.04 預設 fail2ban 只寫 journal：

```bash
$ ls -l /var/log/fail2ban.log
ls: cannot access '/var/log/fail2ban.log': No such file or directory
```

```bash
$ sudo tee /etc/fail2ban/fail2ban.local >/dev/null <<'EOF'
[Definition]
logtarget = /var/log/fail2ban.log
loglevel  = INFO
EOF
$ sudo systemctl restart fail2ban
$ sudo tail -3 /var/log/fail2ban.log
2026-09-03 10:15:02,331 fail2ban.jail  [2104]: INFO    Jail 'sshd' started
2026-09-03 10:15:02,412 fail2ban.jail  [2104]: INFO    Jail 'recidive' started
2026-09-03 10:15:02,489 fail2ban.server[2104]: INFO    Server ready
```

★★★ 記得配 logrotate，否則這個檔案會一直長。Ubuntu 套件已經附了
`/etc/logrotate.d/fail2ban`，裝了就有，不用自己寫。

## 進階設定與調校

### `bantime.increment`：遞增封鎖 ★★★★

固定 `bantime` 的問題：機器人被關一小時後回來繼續打，你等於每小時都要重新擋一次。
遞增封鎖讓**同一個 IP 每被抓一次，封鎖時間就翻倍**。

```ini
[DEFAULT]
bantime.increment = true
bantime           = 1h
bantime.factor    = 2
bantime.maxtime   = 4w
bantime.rndtime   = 10m
```

| 參數 | 意義 | 星級 |
| --- | --- | --- |
| `bantime.increment` | ★★★★ 總開關，預設 `false` | ★★★★ |
| `bantime` | 第一次封鎖的基準時間 | ★★★★ |
| `bantime.factor` | 倍率係數（預設 `1`，配合預設公式使用） | ★★★ |
| `bantime.maxtime` | ★★★★ **封鎖時間上限**。不設的話會一路成長到荒謬的數字 | ★★★★ |
| `bantime.rndtime` | ★★★ 隨機加上 0～這個數的時間，避免攻擊者算準解封時刻回來 | ★★★ |
| `bantime.multipliers` | 直接指定倍數序列，例如 `1 2 4 8 16 32 64` | ★★★ |

實際效果（`bantime = 1h`，預設公式）：

| 第幾次被抓 | 封鎖時間 |
| --- | --- |
| 1 | 1 小時 |
| 2 | 2 小時 |
| 3 | 4 小時 |
| 4 | 8 小時 |
| … | 持續加倍直到 `bantime.maxtime` |

> [!warning] ★★★★★ 遞增封鎖會放大誤封的傷害
> 開了 `bantime.increment` 之後，**誤封一個機關 NAT 出口的代價會從「1 小時」變成「幾週」**。
> 開這個功能之前，先確定 `ignoreip` 已經寫好寫滿並驗證過（`fail2ban-client get <jail> ignoreip`）。
>
> 另外它依賴資料庫記住「這個 IP 之前被抓過幾次」，所以**必須確認資料庫沒有被過早清掉**（見下一段）。

> [!warning] 未實機驗證
> `bantime.increment` 的預設遞增公式在 0.11 → 1.0 之間調整過，
> 上表的秒數是依 `jail.conf` 註解的說明推導。實際數字請在你的環境用
> `fail2ban-client get <jail> bantime` 與 `fail2ban.log` 的 `Ban` 記錄對照確認。

### 持久化：封鎖清單怎麼在重啟後保留 ★★★★

```bash
$ ls -lh /var/lib/fail2ban/fail2ban.sqlite3
-rw------- 1 root root 96K Sep  3 10:20 /var/lib/fail2ban/fail2ban.sqlite3
```

Fail2ban 把封鎖記錄與失敗次數存在這個 SQLite 檔裡，重啟後會**重新套用還沒到期的封鎖**。

```ini
# /etc/fail2ban/fail2ban.local
[Definition]
dbfile     = /var/lib/fail2ban/fail2ban.sqlite3
dbpurgeage = 7d
```

> [!danger] ★★★★★ `dbpurgeage` 小於 `bantime` = 封鎖記錄會提早被清掉
> `dbpurgeage` 預設是 `1d`。如果你把 `bantime` 設成 `1w` 或開了 `bantime.increment`，
> **超過 1 天的封鎖記錄會被資料庫清理程序刪掉**，重啟 fail2ban 之後那些人就自動放出來了，
> 而且 `bantime.increment` 的「累犯計數」也一併歸零。
>
> **規則：`dbpurgeage` 必須 ≥ 你用過的最大 `bantime`。**
> 用了 `bantime.maxtime = 4w` 就把 `dbpurgeage` 設成 `5w`。

### ★★★★ 與 nftables set 的整合：封鎖量大時的唯一解

`banaction = iptables-multiport` 的做法是**每封鎖一個 IP 就插一條規則**。
封鎖 2000 個 IP＝2000 條規則，每個進來的封包都要線性比對 2000 次 ——
在流量大的機器上這是實實在在的 CPU 成本。

**nftables set 是雜湊查表，2000 筆跟 2 筆的查詢成本幾乎一樣。**

```ini
[DEFAULT]
banaction            = nftables-multiport
banaction_allports   = nftables-allports
```

★★★ 前提是這台機器用純 nftables 管防火牆（見 [[090-02-03-guide-防火牆-nftables與iptables]]），
**不要跟 ufw 混用**。

套用後檢查 nftables 那一側：

```bash
$ sudo nft list ruleset | grep -B2 -A8 f2b
table inet f2b-table {
	set addr-set-sshd {
		type ipv4_addr
		elements = { 203.0.113.66, 198.51.100.14 }
	}

	chain f2b-chain {
		type filter hook input priority filter - 1; policy accept;
		tcp dport { 22 } ip saddr @addr-set-sshd drop
	}
}
```

★★★★★ 讀懂這段輸出就等於學會了驗證 Fail2ban：

| 看什麼 | 意義 |
| --- | --- |
| `table inet f2b-table` | ★★★★ Fail2ban 自己建的表，跟你的主要防火牆表分開，**互不干擾** |
| `set addr-set-sshd` | 每個 jail 一個 set，名稱是 `addr-set-<jail名>` |
| `elements = { ... }` | ★★★★★ **這裡有 IP 才是真的擋住了** |
| `priority filter - 1` | ★★★★ 優先權比一般 filter 早 1，確保**在你的 allow 規則之前**執行 |
| `tcp dport { 22 }` | 只擋這個 jail 宣告的 `port`。`allports` 版本則沒有這一段 |

驗證單一 IP 在不在 set 裡：

```bash
$ sudo nft get element inet f2b-table addr-set-sshd '{ 203.0.113.66 }'
table inet f2b-table {
	set addr-set-sshd {
		type ipv4_addr
		elements = { 203.0.113.66 }
	}
}
```

★★★ 不在的話會回 `Error: Could not process rule: No such file or directory`。

> [!warning] 未實機驗證
> 上面的 table／chain／set 名稱來自 `/etc/fail2ban/action.d/nftables.conf` 的預設變數
> （`nftables_family = inet`、`nftables_table = f2b-table`、`nftables_chain = f2b-chain`）。
> **不同版本可能不同**，請在你的機器上直接看：
> ```bash
> grep -E '^nftables_' /etc/fail2ban/action.d/nftables.conf
> ```

> [!info]- firewalld 環境：改用 `firewallcmd-ipset`
> RHEL 系上同樣的道理，逐條 rich rule 會拖垮效能，改用 ipset：
> ```ini
> [DEFAULT]
> banaction = firewallcmd-ipset
> ```
> 驗證：
> ```bash
> sudo firewall-cmd --get-ipsets
> sudo firewall-cmd --info-ipset=f2b-sshd
> ```
> ★★★ 注意 `firewallcmd-ipset` 產生的是 **runtime** 規則，重啟 firewalld 會消失 ——
> 但這沒關係，Fail2ban 重新套用時會重建。firewalld 本身的操作見 [[090-02-04-guide-防火牆-firewalld]]。

### ★★★★ 自訂 filter：完整走一遍

**情境**：機關的 Laravel 後台把登入失敗寫進 `/var/www/app/storage/logs/auth.log`，
格式如下。要做一個 jail 擋掉猜密碼的人。

```text
[2026-09-03 03:12:41] production.WARNING: login.failed ip=203.0.113.66 user=admin
[2026-09-03 03:12:44] production.WARNING: login.failed ip=203.0.113.66 user=administrator
[2026-09-03 03:12:47] production.WARNING: login.failed ip=203.0.113.66 user=root
[2026-09-03 03:12:50] production.INFO: login.success ip=10.10.0.51 user=ops
[2026-09-03 03:12:55] production.WARNING: login.failed ip=198.51.100.14 user=test
```

#### 步驟 1：先取一段真實日誌當樣本 ★★★★

```bash
$ sudo cp /var/www/app/storage/logs/auth.log /tmp/sample.log
$ wc -l /tmp/sample.log
842 /tmp/sample.log
```

★★★★ **一定要用真實日誌，不要自己編一段。** 真實日誌裡才有你想不到的變體
（欄位順序不同、多了 request id、IPv6 位址、跨月的日期格式…）。

#### 步驟 2：寫第一版 filter

```bash
$ sudo tee /etc/fail2ban/filter.d/laravel-auth.conf >/dev/null <<'EOF'
# Fail2Ban filter: Laravel 後台登入失敗
[Definition]
failregex = ^\[.*\] \S+\.WARNING: login\.failed ip=<HOST> user=\S+\s*$
ignoreregex =
datepattern = ^\[%%Y-%%m-%%d %%H:%%M:%%S\]
EOF
```

★★★★★ 三個容易踩的點：

| 點 | 說明 |
| --- | --- |
| `<HOST>` | ★★★★★ 犯人 IP 的位置。**只能有一個**，而且必須是**未被括號包住**的裸標記 |
| `%%` | ★★★★ 在 Fail2ban 的設定檔裡，`%` 是變數插值符號，**要寫日期格式必須用 `%%` 跳脫** |
| `datepattern` | ★★★ 告訴 Fail2ban 怎麼解析時間戳。不設的話它會猜，猜錯就會把舊日誌當成剛發生的 |

#### 步驟 3：★★★★★ 用 `fail2ban-regex` 測試

**這是自訂 filter 唯一正確的開發方式。不要寫完直接 restart 去賭。**

```bash
$ fail2ban-regex /tmp/sample.log /etc/fail2ban/filter.d/laravel-auth.conf

Running tests
=============

Use   failregex filter file : laravel-auth, basedir: /etc/fail2ban
Use         log file : /tmp/sample.log
Use         encoding : UTF-8

Results
=======

Failregex: 317 total
|-  #) [# of hits] regular expression
|   1) [317] ^\[.*\] \S+\.WARNING: login\.failed ip=<HOST> user=\S+\s*$
`-

Ignoreregex: 0 total

Date template hits:
|- [# of hits] date format
|  [842] ^\[Year-Month-Day 24hour:Minute:Second\]
`-

Lines: 842 lines, 0 ignored, 317 matched, 525 missed
[processed in 0.18 sec]
```

★★★★★ 看四個數字：

| 數字 | 意義 | 該長什麼樣 |
| --- | --- | --- |
| `Failregex: 317 total` | ★★★★★ 比對成功幾行 | **必須 > 0**。是 0 就是正則寫錯 |
| `Date template hits: [842]` | ★★★★ 時間戳解析成功幾行 | **應該接近總行數**。是 0 就是 `datepattern` 錯 |
| `matched` | 同 Failregex | — |
| `missed` | 沒比對到的行 | ★★★ 應該都是 `login.success` 之類**本來就不該抓**的行 |

★★★★★ **`Date template hits` 是 0 的話，就算 `Failregex` 有命中，jail 也完全不會封鎖任何人** ——
Fail2ban 無法判斷「這件事發生在 findtime 之內」。這是自訂 filter 最常見的沉默失敗。

檢查漏掉的是不是該抓的：

```bash
$ fail2ban-regex /tmp/sample.log /etc/fail2ban/filter.d/laravel-auth.conf --print-all-missed | head -5
[2026-09-03 03:12:50] production.INFO: login.success ip=10.10.0.51 user=ops
[2026-09-03 03:13:02] production.INFO: login.success ip=10.10.0.52 user=alice
...
```

★★★★ 全部都是 `login.success` → 正確，這些本來就不該抓。
如果 missed 裡面出現了 `login.failed` 的變體，回頭改正則再測一次。

也可以直接用單行字串快速測：

```bash
$ fail2ban-regex '[2026-09-03 03:12:41] production.WARNING: login.failed ip=203.0.113.66 user=admin' \
    '^\[.*\] \S+\.WARNING: login\.failed ip=<HOST> user=\S+\s*$'
...
Lines: 1 lines, 0 ignored, 1 matched, 0 missed
```

#### 步驟 4：建 jail

```ini
# 追加到 /etc/fail2ban/jail.local
[laravel-auth]
enabled  = true
filter   = laravel-auth
logpath  = /var/www/app/storage/logs/auth.log
port     = http,https
maxretry = 6
findtime = 10m
bantime  = 6h
backend  = polling
```

★★★ 這裡 `backend` 用 `polling` 而不是 `systemd`，因為這是**應用自己寫的檔案**，不在 journal 裡。
`auto` 通常也可以（會挑 `pyinotify`），但 Laravel 的日誌檔會依日期換檔名，
`polling` 對這種情況比較穩。

#### 步驟 5：套用並驗證

```bash
$ sudo fail2ban-client -t
OK: configuration test is successful
$ sudo systemctl reload fail2ban
$ sudo fail2ban-client status laravel-auth
Status for the jail: laravel-auth
|- Filter
|  |- Currently failed: 0
|  |- Total failed:     317
|  |- File list:        /var/www/app/storage/logs/auth.log
`- Actions
   |- Currently banned: 2
   |- Total banned:     2
   `- Banned IP list:   203.0.113.66 198.51.100.14
```

★★★★ `Total failed: 317` 對上了 `fail2ban-regex` 的數字 → filter 確實在運作。

> [!tip] ★★★ 讀取權限
> Fail2ban 以 root 執行，通常沒有權限問題。但**日誌檔的父目錄如果權限太緊**
> （例如 `storage/logs` 是 `0700 www-data:www-data`）仍可能讀不到。
> 症狀是 `fail2ban.log` 出現 `Failed to open ...: Permission denied`。

### 微調內建 filter ★★★

不要改 `filter.d/sshd.conf`，建一個 `.local` 加規則：

```bash
$ sudo tee /etc/fail2ban/filter.d/sshd.local >/dev/null <<'EOF'
[Definition]
# 把「連上就馬上斷線」的掃描行為也算成一次失敗
failregex = %(known/failregex)s
            ^%(__prefix_line)sConnection closed by authenticating user \S+ <HOST> port \d+ \[preauth\]$
EOF
```

★★★★★ `%(known/failregex)s` 是關鍵 —— 它代表「**原本 `.conf` 裡的所有規則**」。
不寫這一行的話，你的 `.local` 會**整組取代**原本的規則，
結果是只剩你新加的那一條在跑，原本抓 `Failed password` 的能力就沒了。

改完照樣要測：

```bash
$ fail2ban-regex /tmp/auth-sample.log sshd
...
Failregex: 89 total
|-  #) [# of hits] regular expression
|   1) [61] ^Failed \S+ for .* from <HOST>...
|   2) [28] ^Connection closed by authenticating user \S+ <HOST> port \d+ \[preauth\]$
`-
```

★★★ 兩條規則都有命中 → 正確。只有第 2 條有命中 → 你忘了 `%(known/failregex)s`。

### 常用管理指令 ★★★★

```bash
# 整體狀態
$ sudo fail2ban-client status
Status
|- Number of jail:      4
`- Jail list:   laravel-auth, nginx-botsearch, recidive, sshd

# 單一 jail
$ sudo fail2ban-client status sshd
Status for the jail: sshd
|- Filter
|  |- Currently failed: 2
|  |- Total failed:     1043
|  `- Journal matches:  _SYSTEMD_UNIT=sshd.service + _COMM=sshd
`- Actions
   |- Currently banned: 5
   |- Total banned:     87
   `- Banned IP list:   203.0.113.66 198.51.100.14 192.0.2.7 192.0.2.31 198.51.100.9

# 只要封鎖清單（適合腳本）
$ sudo fail2ban-client get sshd banned
['203.0.113.66', '198.51.100.14', '192.0.2.7', '192.0.2.31', '198.51.100.9']

# 查某個 IP 被哪些 jail 關著
$ sudo fail2ban-client banned 203.0.113.66
[{'sshd': 1}, {'recidive': 1}]
```

### 解封 ★★★★★

```bash
# 解單一 IP（單一 jail）
$ sudo fail2ban-client set sshd unbanip 203.0.113.66
1

# 解單一 IP（★★★★ 所有 jail，比較常用）
$ sudo fail2ban-client unban 203.0.113.66
1

# ★★★★★ 全部放光 —— 把自己鎖住時的急救指令
$ sudo fail2ban-client unban --all
2026-09-03 10:44:11,203 fail2ban.actions [2104]: NOTICE  [sshd] Unban 203.0.113.66
2026-09-03 10:44:11,215 fail2ban.actions [2104]: NOTICE  [sshd] Unban 198.51.100.14
5
```

★★★ 回傳的數字是「解封了幾個」。

**手動封鎖**（例如收到威脅情資）：

```bash
$ sudo fail2ban-client set sshd banip 203.0.113.200
1
```

> [!warning] ★★★★ 手動 ban 一樣受 `bantime` 限制
> `set <jail> banip` 加入的封鎖，時間到了照樣會自動解除。
> **要永久封鎖某個來源，請直接寫進防火牆規則**（ufw `deny from`、
> firewalld rich rule `drop`），不要靠 Fail2ban。
> Fail2ban 管的是「動態、暫時」的封鎖，永久黑名單屬於防火牆的職責。

## 完整實戰範例

### 情境

一台 **Ubuntu 24.04** 的對外 Web 主機，要從零裝好 Fail2ban 並**實際驗證它真的會擋人**。

| 項目 | 值 |
| --- | --- |
| 主機 | `web01`，`10.20.5.10`，ufw 已啟用 |
| 管理網段 | `10.10.0.0/24`（你的工作站 `10.10.0.51` 在這裡） |
| 測試機 | `10.30.7.99` —— ★★★★ **刻意不在管理網段**，用來扮演攻擊者 |
| 服務 | sshd（22）、Nginx（80/443） |

> [!danger] ★★★★★ 開始之前：準備好「第二條路」
> 本節第 5 步會**故意讓一台機器被封鎖**。萬一設定寫錯，被封的可能是你自己。
> 開工之前先確認至少有以下其中一項可用：
> - 主機 console／IPMI／iDRAC／PVE 的 noVNC
> - 一條來自不同網段的備援連線（手機熱點）
> - 一個已排定的自動解除任務：
>   ```bash
>   echo 'fail2ban-client unban --all' | sudo at now + 20 minutes
>   ```
> **沒有第二條路就不要開始。**

### 第 1 步：安裝與環境確認

```bash
$ sudo apt update && sudo apt install -y fail2ban
$ fail2ban-server --version
Fail2Ban v1.0.2

$ ls -l /var/log/auth.log
ls: cannot access '/var/log/auth.log': No such file or directory   # ★★★★★ 要用 systemd backend

$ sudo journalctl -u ssh -n 3 --no-pager
Sep 03 09:38:12 web01 sshd[1502]: Accepted publickey for ops from 10.10.0.51 port 49122 ssh2: ED25519 SHA256:xxxx
...

$ sudo ufw status | head -6
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80,443/tcp                 ALLOW       Anywhere
```

★★★★ ufw 是 active → `banaction` 要用 `ufw`。

### 第 2 步：確認自己的來源 IP（決定會不會鎖到自己）

```bash
$ who am i
ops      pts/0        2026-09-03 09:58 (10.10.0.51)
```

★★★★★ `10.10.0.51` 會被寫進 `ignoreip`，所以你不會被鎖。**這一步不能跳過。**

### 第 3 步：寫 `jail.local`

```bash
$ sudo tee /etc/fail2ban/jail.local >/dev/null <<'EOF'
[DEFAULT]
# ★★★★★ 白名單優先
ignoreip   = 127.0.0.1/8 ::1 10.10.0.0/24
ignoreself = true

# 判定門檻
findtime = 10m
maxretry = 5
bantime  = 1h

# ★★★★★ Ubuntu + ufw
banaction = ufw

# ★★★★★ Ubuntu 24.04 沒有 auth.log
backend = systemd

# 通知（可選）
destemail = ops@example.gov.tw
sender    = fail2ban@web01.example.gov.tw
action    = %(action_)s

[sshd]
enabled  = true
port     = ssh
maxretry = 3
bantime  = 30m

[nginx-botsearch]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/access.log
backend  = polling
maxretry = 3
bantime  = 12h
EOF
```

★★★ 這裡把 sshd 的 `maxretry` 設成 3、`bantime` 設成 30m —— **測試階段刻意設短**，
方便觀察解封。正式上線再調回 `maxretry = 4` / `bantime = 2h`。

### 第 4 步：語法檢查與啟動

```bash
$ sudo fail2ban-client -t
OK: configuration test is successful

$ sudo systemctl restart fail2ban
$ sudo systemctl is-active fail2ban
active

$ sudo fail2ban-client status
Status
|- Number of jail:      2
`- Jail list:   nginx-botsearch, sshd

$ sudo fail2ban-client get sshd ignoreip
These IP addresses/networks are ignored:
|- 127.0.0.1/8
|- ::1
`- 10.10.0.0/24
```

★★★★★ **白名單有生效** —— 這一行確認完才能進行下一步。

### 第 5 步：★★★★★ 觸發封鎖（從測試機故意打錯密碼）

在測試機 `10.30.7.99` 上：

```bash
[tester@lab ~]$ for i in 1 2 3 4; do
>   ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no \
>       -o ConnectTimeout=5 -o StrictHostKeyChecking=no nosuchuser@10.20.5.10 2>&1 | tail -1
> done
Permission denied, please try again.
Permission denied, please try again.
Permission denied, please try again.
ssh: connect to host 10.20.5.10 port 22: Connection refused
```

★★★★ 第 4 次變成 `Connection refused`（ufw 的 `deny` 是 reject 行為）或 `Connection timed out`
（用 nftables/iptables 後端則是 drop）—— **這就是被擋住的表現**。

★★★ `-o PreferredAuthentications=password -o PubkeyAuthentication=no` 是必要的，
否則 ssh 會先嘗試金鑰、產生的日誌行不是 `Failed password`。

### 第 6 步：在伺服器上確認（三層都要看）★★★★★

```bash
# ── ① Fail2ban 說擋了 ──
$ sudo fail2ban-client status sshd
Status for the jail: sshd
|- Filter
|  |- Currently failed: 0
|  |- Total failed:     3
|  `- Journal matches:  _SYSTEMD_UNIT=sshd.service + _COMM=sshd
`- Actions
   |- Currently banned: 1
   |- Total banned:     1
   `- Banned IP list:   10.30.7.99
```

```bash
# ── ② ★★★★★ 防火牆那一側真的有規則嗎？（決定性的一步）──
$ sudo ufw status numbered | head -6
Status: active

     To                         Action      From
     --                         ------      ----
[ 1] Anywhere                   DENY IN     10.30.7.99
[ 2] 22/tcp                     ALLOW IN    Anywhere
```

★★★★★ **看到 `[1] DENY IN 10.30.7.99` 排在 allow 規則前面，才算真的擋住。**
只有 ① 而沒有 ② 的話，就是 `banaction` 選錯了（見排錯表第 3 列）。

```bash
# ── ③ 日誌怎麼記的 ──
$ sudo journalctl -u fail2ban -n 5 --no-pager
Sep 03 10:31:44 web01 fail2ban.filter[2104]: INFO    [sshd] Found 10.30.7.99 - 2026-09-03 10:31:44
Sep 03 10:31:47 web01 fail2ban.filter[2104]: INFO    [sshd] Found 10.30.7.99 - 2026-09-03 10:31:47
Sep 03 10:31:50 web01 fail2ban.filter[2104]: INFO    [sshd] Found 10.30.7.99 - 2026-09-03 10:31:50
Sep 03 10:31:50 web01 fail2ban.actions[2104]: NOTICE  [sshd] Ban 10.30.7.99
```

★★★★ 讀日誌的關鍵字：
`Found` = filter 抓到一次失敗；`Ban` = 達到門檻、已執行封鎖動作；
`Already banned` = 已經在名單裡；`Unban` = 解封。

### 第 7 步：驗證白名單真的有效 ★★★★★

從**管理網段的機器**（`10.10.0.51`）做同樣的事：

```bash
[ops@jump ~]$ for i in 1 2 3 4 5 6; do
>   ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no \
>       -o ConnectTimeout=5 nosuchuser@10.20.5.10 2>&1 | tail -1
> done
Permission denied, please try again.
Permission denied, please try again.
Permission denied, please try again.
Permission denied, please try again.
Permission denied, please try again.
Permission denied, please try again.
```

```bash
$ sudo fail2ban-client status sshd | grep Banned
   `- Banned IP list:   10.30.7.99
```

★★★★★ **失敗 6 次仍然沒被封鎖 → `ignoreip` 正確運作。**
這一步比第 5 步更重要 —— 它證明你的同事不會被自己的防護鎖在外面。

### 第 8 步：解封

```bash
$ sudo fail2ban-client set sshd unbanip 10.30.7.99
1

$ sudo fail2ban-client status sshd | grep -E 'Currently banned|Banned IP'
   |- Currently banned: 0
   `- Banned IP list:

$ sudo ufw status numbered | head -5
Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp                     ALLOW IN    Anywhere
```

★★★★★ **ufw 那條 DENY 規則也一併消失了** —— 這才叫真的解封。
如果 Fail2ban 說解了但防火牆規則還在（`actionunban` 失敗），
你會遇到「Fail2ban 顯示沒封鎖、但對方就是連不進來」的鬼故事。

從測試機確認：

```bash
[tester@lab ~]$ nc -zv -w3 10.20.5.10 22
Connection to 10.20.5.10 22 port [tcp/ssh] succeeded!
```

### 第 9 步：落地 —— 調回正式參數並確認開機自動啟動

```bash
$ sudo sed -i 's/^maxretry = 3$/maxretry = 4/; s/^bantime  = 30m$/bantime  = 2h/' /etc/fail2ban/jail.local
$ sudo fail2ban-client -t
OK: configuration test is successful
$ sudo systemctl reload fail2ban
$ sudo systemctl is-enabled fail2ban
enabled
```

### 驗收檢查表 ★★★★★

| # | 檢查項 | 指令 | 期望 |
| --- | --- | --- | --- |
| 1 | 服務在跑 | `systemctl is-active fail2ban` | `active` |
| 2 | 開機自動啟動 | `systemctl is-enabled fail2ban` | `enabled` |
| 3 | 設定語法正確 | `fail2ban-client -t` | `OK` |
| 4 | jail 都起來了 | `fail2ban-client status` | 列出所有你啟用的 jail |
| 5 | ★★★★★ filter 真的在讀日誌 | `fail2ban-client status sshd` 的 `Total failed` | **> 0**（0 = filter 或 logpath 錯） |
| 6 | ★★★★★ 白名單有效 | `fail2ban-client get sshd ignoreip` | 含機關網段 |
| 7 | ★★★★★ 封鎖能觸發 | 從非白名單來源打錯密碼 | `Currently banned` 增加 |
| 8 | ★★★★★ **防火牆真的有規則** | `ufw status numbered` / `nft list ruleset \| grep f2b` | 看得到封鎖項 |
| 9 | 解封乾淨 | `fail2ban-client unban <IP>` 後看防火牆 | 規則消失 |
| 10 | 重啟後封鎖保留 | `systemctl restart fail2ban` 後 `status` | 未到期的封鎖還在 |
| 11 | `dbpurgeage` ≥ 最大 `bantime` | `grep dbpurgeage /etc/fail2ban/fail2ban.local` | 是 |
| 12 | ★★★★ **重開機後全部還在** | `reboot` 後重跑 1～8 項 | 全部一致 |

## 常見錯誤與排錯

| # | 現象 | 原因 | 解法 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | `systemctl start fail2ban` 失敗，log 有 `Have not found any log file for sshd jail` | ★★★★★ Ubuntu 24.04 沒裝 rsyslog，`/var/log/auth.log` 不存在 | `jail.local` 加 `backend = systemd`；或 `apt install rsyslog` | ★★★★★ |
| 2 | 服務有跑、`Total failed` 一直是 0 | filter 沒抓到任何行：`logpath` 錯、`backend` 錯、或正則不符 | `fail2ban-regex <日誌> <filter>` 測；確認 `Date template hits` 也 > 0 | ★★★★★ |
| 3 | ★★★★★ **`Currently banned` 有數字，但對方照樣連得進來** | `banaction` 選錯（例如 ufw 環境卻用 `iptables-multiport`） | 改成環境對應的：ufw→`ufw`、nftables→`nftables-multiport`、firewalld→`firewallcmd-ipset`。**改完一定要去防火牆那側驗證看得到規則** | ★★★★★ |
| 4 | 一改設定就整個服務起不來 | `.local` 語法錯（縮排、缺 `[section]`、`%` 沒跳脫成 `%%`） | ★★★★★ **改完永遠先 `fail2ban-client -t` 再 restart** | ★★★★★ |
| 5 | ★★★★★ **把自己／整個機關鎖在外面** | `ignoreip` 沒寫，或機關走同一個 NAT 出口 | 從其他網段登入 `fail2ban-client unban --all`；沒別的路就走 console `systemctl stop fail2ban`。事後把網段補進 `ignoreip` | ★★★★★ |
| 6 | 昨天調好的參數今天變回預設 | ★★★★★ 改在 `jail.conf`，被 `apt upgrade` 覆蓋 | 全部搬到 `jail.local`；`diff` 一下確認 `jail.conf` 已還原成原廠 | ★★★★★ |
| 7 | 自訂 filter：`Failregex` 有命中但從不封鎖 | ★★★★★ `Date template hits` 是 0，Fail2ban 判斷不出事件時間 | 在 filter 加正確的 `datepattern`；日期格式裡的 `%` 要寫成 `%%` | ★★★★★ |
| 8 | 自訂 filter：`fail2ban-regex` 回 `ERROR No failure-id group in ...` | 正則裡沒有 `<HOST>`，或 `<HOST>` 被寫成自己的括號群組 | 加上裸的 `<HOST>`，不要用 `(<HOST>)` 也不要自己寫 IP 正則 | ★★★★ |
| 9 | 改了 `filter.d/sshd.local` 之後，原本會抓的 `Failed password` 不抓了 | ★★★★★ `.local` 的 `failregex` **整組取代**了 `.conf` 的 | 第一行加 `%(known/failregex)s` 把原規則接回來 | ★★★★ |
| 10 | 重啟 fail2ban 後封鎖名單全空 | `dbpurgeage`（預設 `1d`）小於 `bantime`，記錄已被清掉 | `fail2ban.local` 設 `dbpurgeage` ≥ 最大 `bantime` | ★★★★ |
| 11 | `bantime.increment` 沒有遞增 | 同上（累犯計數存在資料庫，被清掉就歸零）；或忘了設 `bantime.increment = true` | 兩者一起檢查 | ★★★ |
| 12 | `recidive` jail 起不來：`Have not found any log file` | 它讀 `/var/log/fail2ban.log`，但 Ubuntu 預設只寫 journal | `fail2ban.local` 設 `logtarget = /var/log/fail2ban.log` 再 restart | ★★★★ |
| 13 | 日誌輪替（logrotate）之後就不再偵測 | `backend` 用了不會偵測換檔的模式 | 用 `backend = auto`／`polling`；systemd backend 不受影響 | ★★★ |
| 14 | Nginx 在反向代理後面，封鎖到的都是代理的 IP | ★★★★ 日誌記的是代理 IP，不是真實客戶端 | Nginx 設 `set_real_ip_from` + `real_ip_header X-Forwarded-For`，見 [[060-02-02-09-guide-Nginx-安全設定]] | ★★★★ |
| 15 | 封鎖清單幾千筆之後，主機吃 CPU、網路變慢 | `iptables-multiport` 每個 IP 一條規則，線性比對 | 改 `nftables-multiport`（set）或 `firewallcmd-ipset` | ★★★★ |
| 16 | `fail2ban-client status` 顯示 jail 存在，但 `Currently banned` 永遠 0，日誌只有 `Found` 沒有 `Ban` | 失敗次數沒在 `findtime` 內累積到 `maxretry`；或每次都被 `ignoreip` 吃掉 | 調低 `maxretry`／調長 `findtime`；用 `fail2ban-client get <jail> ignoreip` 確認來源不在白名單 | ★★★ |
| 17 | 攻擊者被封鎖後立刻換 IP 繼續打 | 分散式暴力破解，Fail2ban 天生擋不住 | ★★★★★ **關掉密碼登入**（[[020-02-01-07-svc-SSH-安全強化]]）才是根本解；Fail2ban 只是降噪 | ★★★★★ |
| 18 | 已建立的 ssh 連線在被封鎖後仍然活著 | ★★★ conntrack 的 `ESTABLISHED` 連線不受新規則影響 | 正常現象。要立刻斷掉可搭配 `conntrack -D -s <IP>` 或改用會處理既有連線的 action | ★★★ |

### 排查步驟（照順序，不要跳）★★★★★

```bash
# ① 服務活著嗎？設定語法對嗎？
sudo systemctl status fail2ban --no-pager
sudo fail2ban-client -t

# ② jail 起來了嗎？
sudo fail2ban-client status

# ③ ★★★★★ filter 有沒有讀到東西？（Total failed 是不是 0）
sudo fail2ban-client status sshd

# ④ 如果 ③ 是 0：filter 本身對不對？
fail2ban-regex /var/log/auth.log /etc/fail2ban/filter.d/sshd.conf
#   看 Failregex 與 Date template hits 兩個數字

# ⑤ 如果 ③ 有數字但沒 Ban：是不是被白名單吃掉了？
sudo fail2ban-client get sshd ignoreip

# ⑥ ★★★★★ 如果有 Ban 但沒擋到：防火牆那側有規則嗎？
sudo ufw status numbered | head
sudo nft list ruleset | grep -A8 f2b
sudo iptables -L -n --line-numbers | grep f2b

# ⑦ 看 Fail2ban 自己怎麼說
sudo journalctl -u fail2ban --since '15 min ago' --no-pager | grep -E 'Found|Ban|Unban|ERROR'
```

★★★★★ **③ 和 ⑥ 把問題切成兩半：**
`Total failed` 是 0 → 問題在 **filter／日誌來源**（前半段）；
有 Ban 但防火牆沒規則 → 問題在 **action／banaction**（後半段）。
不先做這個切分，你會在錯的地方查一整個下午。

## 安全性注意事項

> [!danger] ★★★★★ 三個一定要先做好的準備
> 1. **先寫 `ignoreip`，再開 jail。** 順序反了就有機會在寫完白名單之前先把自己關進去。
> 2. **準備好第二條路。** console／IPMI／不同網段的備援連線，三選一以上。
>    調 Fail2ban 而沒有第二條路，等於在沒有安全網的高空作業。
> 3. **改完設定先 `fail2ban-client -t` 再 restart。** 語法錯 → 服務起不來 →
>    **機器完全失去暴力破解防護，而且不會有任何人發現**，直到出事。

> [!danger] ★★★★★ 把自己鎖住的完整救援流程
> ```bash
> # 情境 A：還有另一條路能登入（不同網段、手機熱點）
> sudo fail2ban-client unban --all          # 立刻放光所有封鎖
> sudo fail2ban-client set sshd unbanip 10.10.0.51   # 或只放特定 IP
>
> # 情境 B：只剩 console / IPMI / PVE noVNC
> sudo systemctl stop fail2ban              # 先讓自己進得來
> sudo fail2ban-client unban --all          # （服務停了的話，直接改防火牆）
> sudo ufw status numbered                  # 找到 DENY 規則
> sudo ufw delete <編號>                     # 手動刪掉
> #   然後把來源網段補進 /etc/fail2ban/jail.local 的 ignoreip，再 start
>
> # 情境 C：事前預防（★★★★ 做高風險變更前先排好）
> echo 'fail2ban-client unban --all' | sudo at now + 20 minutes
> ```

> [!warning] ★★★★★ Fail2ban 不是第一道防線，是第二道
> **對 ssh 而言，關掉密碼登入的效果遠大於 Fail2ban。**
> 純金鑰認證下，攻擊者再怎麼猜也不可能成功；Fail2ban 的價值變成
> 「**減少日誌噪音、降低伺服器處理無效連線的負擔**」，而不是「防止入侵」。
>
> 正確的優先順序：
>
> | 順序 | 做什麼 | 參考 |
> | --- | --- | --- |
> | 1 | ★★★★★ 關掉 ssh 密碼登入、`PermitRootLogin no` | [[020-02-01-07-svc-SSH-安全強化]] |
> | 2 | ★★★★★ 用防火牆把管理埠限制到管理網段 | [[090-02-02-guide-防火牆-ufw基礎與實務]] |
> | 3 | ★★★★ Fail2ban 處理「不得不對外開放」的服務 | 本篇 |
> | 4 | ★★★ 集中日誌與告警，才知道有人在打你 | [[100-01-03-guide-日誌-系統監控與告警]] |

> [!warning] ★★★★ Fail2ban 本身能被拿來當攻擊工具
> 如果攻擊者能**偽造來源 IP** 出現在你的日誌裡（最典型：Web 應用直接把
> `X-Forwarded-For` 的內容寫進日誌，而那個標頭是使用者可控的），
> 他就能讓 Fail2ban 去封鎖**任意 IP**，包含你的合作機關、你的 CDN、甚至你自己。
> 這叫 **Fail2ban 反射式 DoS**。
>
> 防法：
> - ★★★★★ **只信任來自可信代理的 `X-Forwarded-For`** —— Nginx 用 `set_real_ip_from`
>   明確列出代理 IP，其他來源的標頭一律忽略（[[060-02-02-09-guide-Nginx-安全設定]]）
> - ★★★★ filter 的 `<HOST>` 一定要抓在**伺服器自己記錄的連線來源欄位**，
>   不要抓應用層可被使用者控制的欄位
> - ★★★★ 把自家所有對外 IP、CDN 回源 IP 都放進 `ignoreip`

> [!tip] ★★★ 稽核與交接
> 機關稽核會問「這台機器有沒有暴力破解防護、擋了多少」。準備這三份：
> ```bash
> fail2ban-client status                                   # 有哪些 jail
> for j in $(fail2ban-client status | sed -n 's/.*Jail list:\s*//p' | tr ',' ' '); do
>   echo "=== $j ==="; fail2ban-client status "$j"
> done                                                     # 各 jail 累計封鎖數
> grep -c ' Ban ' /var/log/fail2ban.log                    # 總封鎖次數
> ```
> ★★★★ 順便把 `jail.local` 納入版本控管 —— 誰在什麼時候把 `maxretry` 從 4 改成 20，
> 沒有版控就永遠查不出來。

## 速查表

### 管理指令 ★★★★★

| 指令 | 說明 |
| --- | --- |
| `fail2ban-client -t` | ★★★★★ **改完設定必跑**，檢查語法 |
| `fail2ban-client status` | 列出所有 jail |
| `fail2ban-client status sshd` | 單一 jail 的失敗數與封鎖清單 |
| `fail2ban-client get sshd banned` | 只回封鎖清單（Python list 格式，適合腳本） |
| `fail2ban-client banned <IP>` | 這個 IP 被哪些 jail 關著 |
| `fail2ban-client get sshd ignoreip` | ★★★★★ 確認白名單真的生效 |
| `fail2ban-client set sshd unbanip <IP>` | 解封（單一 jail） |
| `fail2ban-client unban <IP>` | ★★★★ 解封（所有 jail） |
| `fail2ban-client unban --all` | ★★★★★ **全部放光 —— 把自己鎖住時的急救指令** |
| `fail2ban-client set sshd banip <IP>` | 手動封鎖 |
| `fail2ban-client reload` | 重載設定（不重啟服務） |
| `fail2ban-client reload sshd` | 只重載單一 jail |
| `fail2ban-client get sshd bantime` | 查目前的封鎖時間設定 |
| `systemctl reload fail2ban` | 重載（比 restart 溫和） |

### filter 開發 ★★★★

| 指令 | 說明 |
| --- | --- |
| `fail2ban-regex <日誌檔> <filter名或路徑>` | ★★★★★ 測 filter，**看 `Failregex` 與 `Date template hits` 兩個數字** |
| `fail2ban-regex <日誌檔> <filter> --print-all-matched` | 印出所有比對成功的行 |
| `fail2ban-regex <日誌檔> <filter> --print-all-missed` | ★★★★ 印出漏掉的行，檢查是不是該抓的 |
| `fail2ban-regex '<單行字串>' '<正則>'` | 快速測一條正則 |
| `<HOST>` | ★★★★★ filter 裡代表犯人 IP 的標記，**必須有且只有一個** |
| `%%` | ★★★★ 設定檔裡 `%` 的跳脫寫法（寫 `datepattern` 一定用到） |
| `%(known/failregex)s` | ★★★★★ 在 `.local` 裡接回 `.conf` 原本的規則 |

### 關鍵參數 ★★★★★

| 參數 | 預設 | 說明 |
| --- | --- | --- |
| `enabled` | `false` | jail 開關 |
| `ignoreip` | `127.0.0.1/8 ::1` | ★★★★★ **白名單，最重要的一個** |
| `ignoreself` | `true` | 自動忽略本機介面 IP |
| `maxretry` | `5` | findtime 內失敗幾次就封 |
| `findtime` | `10m` | 觀察窗長度 |
| `bantime` | `10m` | 封鎖多久（`-1` = 永久） |
| `bantime.increment` | `false` | ★★★★ 遞增封鎖總開關 |
| `bantime.maxtime` | — | ★★★★ 遞增封鎖的上限，**一定要設** |
| `banaction` | 隨發行版 | ★★★★★ **選錯不會生效**：`ufw` / `nftables-multiport` / `iptables-multiport` / `firewallcmd-ipset` |
| `banaction_allports` | — | recidive 之類要全埠封鎖時用 |
| `backend` | `auto` | ★★★★★ `systemd`（讀 journal）/ `polling` / `pyinotify` |
| `logpath` | 隨 jail | 監看的日誌檔（`backend = systemd` 時不需要） |
| `port` | 隨 jail | 要封鎖的目的埠 |
| `filter` | 同 jail 名 | 用哪個 filter |
| `dbpurgeage` | `1d` | ★★★★ **必須 ≥ 最大 `bantime`**，否則封鎖記錄提早消失 |
| `logtarget` | 隨發行版 | ★★★ 設成 `/var/log/fail2ban.log` 才能用 `recidive` |

### 檔案路徑 ★★★★★

| 路徑 | 說明 |
| --- | --- |
| `/etc/fail2ban/jail.conf` | ★★★★★ 套件提供，**絕對不要改** |
| `/etc/fail2ban/jail.local` | ★★★★★ **你的設定寫這裡** |
| `/etc/fail2ban/jail.d/*.local` | 分檔的 jail 設定（大型環境） |
| `/etc/fail2ban/fail2ban.local` | 守護程序本身（`logtarget`、`dbpurgeage`） |
| `/etc/fail2ban/filter.d/*.conf` | 內建 filter（不要改） |
| `/etc/fail2ban/filter.d/*.local` | ★★★★ 你微調的 filter |
| `/etc/fail2ban/action.d/*.conf` | 內建 action（`ufw.conf`、`nftables-multiport.conf`…） |
| `/var/lib/fail2ban/fail2ban.sqlite3` | ★★★★ 封鎖記錄與累犯計數 |
| `/var/log/fail2ban.log` | Fail2ban 自己的日誌（`recidive` 讀這個） |
| `/var/log/auth.log`（Ubuntu ≤ 22.04） | ssh 日誌。★★★★★ **24.04 預設不存在** |
| `/var/log/secure`（RHEL） | RHEL 系的 ssh 日誌 |

### 判斷準則（背這五條）★★★★★

1. **服務起不來** → 先 `fail2ban-client -t`，八成是 `.local` 語法錯或找不到日誌
2. **`Total failed` 是 0** → 問題在 filter／logpath／backend，用 `fail2ban-regex` 查
3. **有 Ban 但沒擋到** → `banaction` 選錯，去防火牆那側看有沒有規則
4. **從不 Ban** → 看 `ignoreip`，或 `maxretry` 太高
5. **把自己鎖住** → `fail2ban-client unban --all`；沒路了就 console `systemctl stop fail2ban`

## 練習題

> [!question]- 練習 1：確認你的機器需要哪個 backend
> 在一台 Ubuntu 上判斷 sshd jail 該用 `systemd` 還是檔案 backend，並實際設定成功啟動。
>
> **解答**
> ```bash
> ls -l /var/log/auth.log 2>&1        # 不存在 → 必須用 systemd backend
> sudo journalctl -u ssh -n 5 --no-pager   # 確認 journal 裡有 sshd 的紀錄
> sudo tee /etc/fail2ban/jail.local >/dev/null <<'EOF'
> [DEFAULT]
> backend  = systemd
> ignoreip = 127.0.0.1/8 ::1
> [sshd]
> enabled = true
> EOF
> sudo fail2ban-client -t && sudo systemctl restart fail2ban
> sudo fail2ban-client status sshd     # 看 Journal matches 那一行
> ```
> ★★★★★ 成功的標誌是 `Journal matches: _SYSTEMD_UNIT=sshd.service + _COMM=sshd`，
> 而且過一陣子 `Total failed` 開始有數字。

> [!question]- 練習 2：證明 `banaction` 選錯會發生什麼
> **在測試機上**故意把 `banaction` 設成環境不符的值，觸發封鎖，觀察「Fail2ban 說擋了但實際沒擋」。
>
> **解答**
> ```bash
> # ① ufw 是 active，但故意設成 iptables-multiport
> sudo sed -i 's/^banaction = ufw/banaction = iptables-multiport/' /etc/fail2ban/jail.local
> sudo fail2ban-client -t && sudo systemctl restart fail2ban
> # ② 從另一台故意打錯密碼直到被封
> # ③ Fail2ban 說封了
> sudo fail2ban-client status sshd | grep Banned
> # ④ 但 ufw 沒有這條規則
> sudo ufw status numbered | grep DENY
> # ⑤ 從測試機再試，發現還連得進來
> ```
> ★★★★★ 這一題的價值在於**親眼看到「① 說擋了」與「④ 防火牆沒規則」可以同時成立**。
> 之後你就會養成「每次都去防火牆那側驗證」的習慣。做完記得改回 `ufw`。

> [!question]- 練習 3：從一段真實日誌寫出可用的 filter
> 假設應用把失敗記成：
> ```text
> 2026-09-03T03:12:41+08:00 api WARN auth_failed client=203.0.113.66 account=admin
> ```
> 寫出 filter 並用 `fail2ban-regex` 驗證。
>
> **解答**
> ```bash
> sudo tee /etc/fail2ban/filter.d/myapi.conf >/dev/null <<'EOF'
> [Definition]
> failregex = ^\S+ \S+ WARN auth_failed client=<HOST> account=\S+\s*$
> ignoreregex =
> datepattern = ^%%Y-%%m-%%dT%%H:%%M:%%S
> EOF
>
> fail2ban-regex \
>   '2026-09-03T03:12:41+08:00 api WARN auth_failed client=203.0.113.66 account=admin' \
>   '^\S+ \S+ WARN auth_failed client=<HOST> account=\S+\s*$'
> # 期望：Lines: 1 lines, 0 ignored, 1 matched, 0 missed
>
> fail2ban-regex /tmp/api-sample.log /etc/fail2ban/filter.d/myapi.conf
> # 期望：Failregex > 0 且 Date template hits ≈ 總行數
> ```
> ★★★★★ 兩個檢查點缺一不可：`Failregex` 有命中**且** `Date template hits` 不是 0。
> 只有前者的話，jail 會安靜地永遠不封鎖任何人。

> [!question]- 練習 4：安全地驗證「被封鎖」與「解封」
> 在測試環境完整跑一次：觸發封鎖 → 三層驗證 → 解封 → 確認防火牆規則也消失。
>
> **解答**
> ```bash
> # 事前保險（★★★★ 高風險操作前必做）
> echo 'fail2ban-client unban --all' | sudo at now + 15 minutes
>
> # 從非白名單來源觸發
> for i in $(seq 1 5); do
>   ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no \
>       -o ConnectTimeout=5 nosuchuser@<目標> 2>&1 | tail -1
> done
>
> # 三層驗證
> sudo fail2ban-client status sshd            # ① Currently banned 增加
> sudo ufw status numbered | head -5           # ② ★★★★★ 看到 DENY 規則
> sudo journalctl -u fail2ban -n 5 --no-pager  # ③ 看到 NOTICE ... Ban
>
> # 解封並確認乾淨
> sudo fail2ban-client set sshd unbanip <來源IP>
> sudo ufw status numbered | grep DENY          # 應該沒有輸出
> ```
> ★★★★★ 第 ② 步是整題的重點。只看 ① 就宣稱「防護正常」是最常見的自欺。

> [!question]- 練習 5：把 `dbpurgeage` 的坑重現一次
> 設 `bantime = 3d` 但 `dbpurgeage` 留在預設 `1d`，說明會發生什麼、怎麼修。
>
> **解答**
> 封鎖記錄超過 1 天就被資料庫清理程序刪除。之後只要 `systemctl restart fail2ban`，
> 那些「應該還要關兩天」的 IP 就全部被放出來了，`bantime.increment` 的累犯計數也歸零。
> ```bash
> sudo tee /etc/fail2ban/fail2ban.local >/dev/null <<'EOF'
> [Definition]
> dbpurgeage = 7d
> EOF
> sudo fail2ban-client -t && sudo systemctl restart fail2ban
> ```
> ★★★★ 規則：**`dbpurgeage` ≥ 你用過的最大 `bantime`**（含 `bantime.maxtime`）。

## 小測驗

Q1. 一句話說明：防火牆與 Fail2ban 在防禦暴力破解上，各自負責什麼？

Q2. （是非）Fail2ban 自己會處理封包，所以就算沒有安裝任何防火牆，它一樣能擋住攻擊者。

Q3. 為什麼所有教學都叫你改 `jail.local` 而不是 `jail.conf`？最糟的後果是什麼？

Q4. 這行指令會發生什麼？
```bash
sudo fail2ban-client unban --all
```

Q5. 在 Ubuntu 24.04 上安裝 Fail2ban 後，`systemctl status fail2ban` 顯示
`Have not found any log file for sshd jail`。原因與兩種解法各是什麼？

Q6. （選擇）`fail2ban-client status sshd` 顯示 `Currently banned: 3`，但攻擊者照樣連得進來。
最該先檢查的是？
　A. `maxretry` 是不是設太高
　B. `ignoreip` 是不是把攻擊者加進去了
　C. 防火牆那一側有沒有出現對應的封鎖規則
　D. `findtime` 是不是太短

Q7. 你寫了一個自訂 filter，`fail2ban-regex` 顯示 `Failregex: 240 total`，
但 `Date template hits` 是 0。這個 jail 會正常封鎖人嗎？為什麼？

Q8. 你在 `/etc/fail2ban/filter.d/sshd.local` 裡寫了一條新的 `failregex`，
結果原本抓 `Failed password` 的能力消失了。少寫了什麼？

Q9. 為什麼封鎖數千個 IP 時，`nftables-multiport` 比 `iptables-multiport` 好？

Q10. 一個 Web 應用直接把 HTTP 標頭 `X-Forwarded-For` 的值寫進日誌，
而你的 filter 從那個欄位抓 `<HOST>`。攻擊者能利用這一點做什麼？

> [!question]- 測驗答案
> **Q1.** ★★★★★ **防火牆決定「這個來源該不該連這個埠」（靜態、事前）；
> Fail2ban 決定「這個已經連進來的來源行為是不是異常」（動態、事後）。**
> Fail2ban 判定異常後，還是要回頭叫防火牆去執行封鎖 → 見〈觀念說明〉的分工圖。
>
> **Q2.** ★★★★★ **否（假）。** Fail2ban 完全沒有封包處理能力，
> 它只是讀日誌、然後執行一行 shell 指令去呼叫 ufw／nftables／iptables／firewalld。
> **沒有防火牆，Fail2ban 什麼都擋不了** → 見〈觀念說明〉。
>
> **Q3.** ★★★★★ `jail.conf` 是套件檔案，`apt upgrade` 會覆蓋它。
> 最糟的後果是 **`ignoreip` 被還原成預設值** —— 機關網段不再豁免，
> 隔天全單位打錯一次密碼就被鎖在外面，而且沒有任何人會收到通知 →
> 見〈基礎設定〉的「第一課」。
>
> **Q4.** ★★★★★ **立刻解除所有 jail 的所有封鎖**，並在防火牆那側移除對應規則，
> 最後回傳解封的筆數。這是「把自己或整個機關鎖在外面」時的**急救指令** →
> 見〈安全性注意事項〉的救援流程。
>
> **Q5.** ★★★★★ **原因**：Ubuntu 24.04 預設不安裝 rsyslog，`/var/log/auth.log` 不存在，
> 而 sshd jail 預設指向那個檔案。
> **解法 A（建議）**：`jail.local` 設 `backend = systemd`，直接讀 journald。
> **解法 B**：`apt install rsyslog` 把檔案日誌裝回來 → 見〈環境準備與安裝〉步驟 0 與排錯表第 1 列。
>
> **Q6.** ★★★★★ **C。** 這是 `banaction` 選錯的典型症狀 ——
> Fail2ban 自己的計數正常（所以 A、D 不是重點），攻擊者也沒被白名單豁免（B 不成立，
> 否則 `Currently banned` 不會有他），問題出在「執行封鎖的那一步做了但沒效果」。
> 去 `ufw status numbered` / `nft list ruleset | grep f2b` 看有沒有規則 →
> 見〈基礎設定〉的 banaction 段與排錯表第 3 列。
>
> **Q7.** ★★★★★ **不會封鎖任何人。** `Date template hits` 是 0 代表 Fail2ban
> 解析不出每一行的時間戳，因此**無法判斷「這些失敗是不是發生在 `findtime` 之內」**，
> 也就永遠累積不到 `maxretry`。要在 filter 裡補上正確的 `datepattern`
> （日期格式裡的 `%` 記得寫成 `%%`）→ 見〈進階設定與調校〉的自訂 filter 步驟 3。
>
> **Q8.** ★★★★★ 少了 **`%(known/failregex)s`**。
> `.local` 的 `failregex` 是**整組取代**而非追加，不把原規則接回來的話，
> 就只剩你新加的那一條在跑 → 見〈進階設定與調校〉的「微調內建 filter」與排錯表第 9 列。
>
> **Q9.** ★★★★ 因為 **nftables 用 set（雜湊表）存封鎖名單，查詢是常數時間**；
> `iptables-multiport` 則是每個 IP 插一條規則，封包要線性比對數千條，
> 在高流量機器上會實實在在吃掉 CPU → 見〈進階設定與調校〉的「與 nftables set 的整合」
> 與 [[090-02-03-guide-防火牆-nftables與iptables]]。
>
> **Q10.** ★★★★★ **他可以偽造 `X-Forwarded-For` 讓 Fail2ban 去封鎖任意 IP** ——
> 包含你的合作機關、CDN 回源位址，甚至你自己的管理網段。這叫 **Fail2ban 反射式 DoS**。
> 防法是在 Nginx 用 `set_real_ip_from` 明確列出可信代理、其他來源的標頭一律忽略，
> 並且 filter 的 `<HOST>` 要抓伺服器自己記錄的連線來源，不抓使用者可控欄位 →
> 見〈安全性注意事項〉。

## 延伸閱讀

- [[020-02-01-07-svc-SSH-安全強化]] —— ★★★★★ **比 Fail2ban 更根本的一步**：關掉密碼登入
- [[020-02-01-04-svc-sshd-伺服器端設定]] —— Fail2ban 讀的日誌是這裡產生的
- [[090-02-02-guide-防火牆-ufw基礎與實務]] —— `banaction = ufw` 的另一半
- [[090-02-03-guide-防火牆-nftables與iptables]] —— set 整合、以及 `nft list ruleset` 怎麼讀
- [[090-02-04-guide-防火牆-firewalld]] —— RHEL 環境的 `firewallcmd-ipset`
- [[090-02-01-guide-防護-伺服器初始安全設定]] —— 新機上線時 Fail2ban 排在第幾步
- [[090-02-06-guide-防護-遠端存取安全]] —— 跳板機與 VPN，把管理面完全移出公網
- [[090-02-08-guide-防護-系統強化與稽核]] —— 稽核時要交出來的封鎖統計
- [[060-02-02-09-guide-Nginx-安全設定]] —— `set_real_ip_from` 與 `limit_req`，兩者都跟本篇直接相關
- [[060-02-02-07-guide-Nginx-日誌與除錯]] —— nginx jail 讀的日誌格式
- [[020-01-19-guide-Linux-日誌系統]] —— journald 與 `backend = systemd` 的背景
- [[100-01-02-guide-日誌-日誌集中與輪替]] —— 日誌換檔時 Fail2ban 的行為
- [[100-01-03-guide-日誌-系統監控與告警]] —— 把封鎖事件接到告警上
- `man jail.conf`、`man fail2ban-client`、`man fail2ban-regex` —— ★★★★ 參數的權威來源
