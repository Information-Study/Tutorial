---
title: "SSH 安全強化"
desc: "威脅模型排序、加固基準八項、演算法加固與相容性評估、SSH CA 短效憑證、鎖門預防與稽核報表"
aliases: [加固, hardening, ssh-audit, SSH CA, sshd hardening, 憑證式認證]
tags: [群組/Linux, 服務/ssh, 安全/加固]
category: SSH與遠端管理
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[04-sshd-伺服器端設定]]", "[[02-SSH-金鑰認證與ssh-agent]]", "[[02-防火牆-ufw基礎與實務]]"]
updated: 2026-08-28
---

# SSH 安全強化

> [!abstract] 這篇你會學到
> - 用**威脅模型排序**決定加固順序，不再把力氣浪費在改埠上
> - 一份可打勾、**可交稽核**的加固基準八項，每項附 `sshd -T` 驗證指令
> - ★★★★★ 為什麼 `PasswordAuthentication no` **沒有真的關掉密碼登入**
> - 演算法加固（KEX / Cipher / MAC / HostKey）與**加固後誰會連不上**的相容性評估
> - ★★★★★ **SSH CA 短效憑證式認證** —— 人離職不必上每台機器刪金鑰
> - ★★★★★ 加固前的**自動回滾**與加固後的**乾淨環境重連驗證**（否則你驗到的是舊連線）
> - 產出 `ssh-harden` 與 `ssh-compliance-check` 兩支腳本與 CSV 稽核報表

## 前置知識

- [[04-sshd-伺服器端設定]] —— `sshd_config` 每個指令的意義、`Include` 順序、`ssh.socket` 陷阱
- [[02-SSH-金鑰認證與ssh-agent]] —— 金鑰產生、`authorized_keys` 選項
- [[02-防火牆-ufw基礎與實務]] —— 本篇的「第一層來源限制」靠它
- [[05-Fail2ban入侵防護]] —— 本篇只給最小 jail，調校與誤封解除看那篇
- [[17-systemd服務管理]] —— 自動回滾 timer 會用到 `systemd-run`

> [!warning] 版本差異會直接影響本篇每一段
> 實測環境：**Ubuntu 26.04.1 LTS / OpenSSH 10.2p1 / OpenSSL 3.5.5**。版本不同時預設清單與可用選項都不一樣：
>
> | 版本 | 你必須注意的差異 |
> | --- | --- |
> | **8.5** ★★ | `PubkeyAcceptedKeyTypes` 改名 `PubkeyAcceptedAlgorithms` |
> | **8.7** ★★★ | `ChallengeResponseAuthentication` 改名 `KbdInteractiveAuthentication` |
> | **8.8** ★★★★ | 預設**停用 `ssh-rsa`（SHA-1）簽章** —— 舊客戶端從這版開始大量連不上 |
> | **9.0** | 預設 KEX 加入 `sntrup761x25519-sha512@openssh.com`（後量子混合） |
> | **9.8** ★★★ | 拆出 privilege-separated listener；新增 `PerSourcePenalties`（預設開啟） |
> | **10.0** ★★★★ | 預設 KEX 改 `mlkem768x25519-sha256`；**sshd 預設移除所有 modp DH**；**移除 DSA** |
>
> ```bash
> $ ssh -V
> OpenSSH_10.2p1 Ubuntu-2ubuntu3.5, OpenSSL 3.5.5 27 Jan 2026   # ★★ 動筆前先確認自己的版本
> ```

---

## 觀念說明

### 先排序，再動手 ★★★★

加固最常見的失敗不是「做錯」，而是「**做了不重要的那幾項就交差**」。
機關資安檢核表上「SSH 已改埠、已裝 fail2ban」兩個勾打完，
但一把 2019 年離職同事的公鑰還躺在 `root` 的 `authorized_keys` 裡 —— 這就是典型。

**風險由高到低排序（這張表決定你有限的人力放哪）**：

| # | 風險項 | 星級 | 一旦發生的後果 | 對策在本篇哪一段 |
| --- | --- | --- | --- | --- |
| 1 | **私鑰外洩／殭屍金鑰** | ★★★★★ | 攻擊者**直接合法登入**，日誌看起來完全正常，沒有任何暴力破解痕跡 | 金鑰治理、**SSH CA 短效憑證** |
| 2 | **密碼登入「以為」關了但沒關** | ★★★★★ | 弱密碼帳號被撞開；`PasswordAuthentication no` 給了你**假安全感** | 加固基準第 2 項 |
| 3 | **舊演算法與協商降級** | ★★★ | 中間人可降級到 SHA-1／CBC；稽核不過；但實務上被實際利用的比例遠低於 1 與 2 | 演算法加固 |
| 4 | **管理埠對全網開放** | ★★★★ | 全球掃描器每天數千次嘗試；一旦 1 或 2 成立就直接被打穿 | 來源限制三層 |
| 5 | **埠號是 22** | ★ | **只影響日誌噪音量**，不影響是否被攻破 | 改埠效益評估 |

> [!danger] 改埠是降噪，不是安全 ★★★★
> ```text
> 把 22 改成 52222 之後：
>   ✓ 每天的失敗登入日誌從 3,000 筆掉到 5 筆     ← 真實效益，值得做
>   ✗ 只要對方掃過你的機器（nmap -p- 兩分鐘的事）
>     → 一樣找得到，一樣照打
>
> ★★★★ 所以：
>   · 改埠可以做，但【不可以】當成加固的主要成果去交差
>   · 改埠【不能】取代「關密碼登入」與「限制來源網段」
>   · 稽核報告上請寫「降低掃描噪音」，不要寫「提升安全性」
> ```

### SSH 的四層攻擊面

```text
① 網路層  誰連得到 TCP/22？  對策：防火牆只開管理網段 → VPN／跳板機 → SSH 不上公網
          失效：規則寫成 anywhere；★★★★ IPv6 那條忘了關
② 傳輸層  協商什麼演算法？    對策：KexAlgorithms / Ciphers / MACs / HostKeyAlgorithms
          失效：★★★★ RHEL 的 crypto-policies 蓋掉你的設定
③ 認證層  怎麼證明你是你？    對策：publickey only → +2FA → SSH CA 短效憑證
          失效：★★★★★ KbdInteractiveAuthentication 忘了關
④ 授權稽核 進來能做什麼？查得到嗎？ 對策：AllowGroups / ForceCommand / LogLevel VERBOSE / 集中日誌
          失效：★★★★ LogLevel INFO + 日誌只留本機 → 事後查不出是誰
```

**四層都要有東西**。只做 ② 的機器（ssh-audit 拿 A+）如果 ③ 沒做好，
一樣被一把外流的私鑰輕鬆登入 —— 而且日誌上看起來完全正常。

### 「加固」與「可用性」的張力

| 動作 | 安全收益 | 你會弄壞什麼 | 建議 |
| --- | --- | --- | --- |
| 關密碼登入 | ★★★★★ | 沒放公鑰的同事進不來 | **先確認每個人的公鑰都在**再關 |
| 限制來源網段 | ★★★★ | 在家連 VPN 忘了開的人 | 保留 console／iDRAC 當後路 |
| 演算法加固 | ★★★ | 老備份軟體、老交換器、Java 8 的 JSch | **先做相容性盤點**再套 |
| `AllowGroups` | ★★★★ | 不在群組裡的服務帳號（含監控） | 先 `lastlog`，別漏了自動化帳號 |
| SSH CA | ★★★★★ | 沒發憑證的人全部進不來 | **與 `authorized_keys` 並存過渡** |
| 改埠 | ★ | 監控探針、備份任務、文件、交接 | 兩埠並存 → 驗證 → 才收 22 |

> [!note] 本篇與其他篇的分工
> - fail2ban 的 `jail.local`、filter 撰寫、誤封解除 → [[05-Fail2ban入侵防護]]
> - 防火牆規則語法 → [[02-防火牆-ufw基礎與實務]]、[[03-防火牆-nftables與iptables]]
> - TOTP／FIDO2 的逐步操作 → [[07-身分存取管理IAM與MFA]]
> - VPN／跳板機架構選型 → [[06-遠端存取安全]]
> - `sshd_config` 每個指令的基礎意義、`Include` 與 `ssh.socket` → [[04-sshd-伺服器端設定]]
> - TWGCB 項目逐條解讀 → [[02-TWGCB-Linux基準文件解讀]]
>
> **本篇只寫別篇沒有的**：威脅排序、可交稽核的基準、演算法相容性評估、**SSH CA**、鎖門預防。

---

## 基礎設定：加固基準八項

這八項是**最低標**，做完才有資格談演算法與憑證。
所有設定**不要改 `/etc/ssh/sshd_config` 本體**，一律寫進 drop-in：

```bash
sudo install -d -m 755 /etc/ssh/sshd_config.d
sudo install -m 600 /dev/null /etc/ssh/sshd_config.d/60-hardening.conf
```

> [!warning] drop-in 的編號很重要 ★★★★
> `sshd_config` 的規則是「**先讀到的值贏**」（first obtained value wins），
> 與 Nginx／Apache 的「後蓋前」**完全相反**。
> - Ubuntu：主檔第一行就是 `Include /etc/ssh/sshd_config.d/*.conf`，
>   所以 drop-in 一定贏主檔；drop-in 之間**編號小的贏**。
> - RHEL 9／Rocky：系統已放了 `50-redhat.conf`（裡面 include crypto-policies），
>   **你的檔案要編號小於 50** 才蓋得過去 —— 詳見下方 RHEL 對照 callout。
>
> 順序細節見 [[04-sshd-伺服器端設定]]。

### 可打勾清單（每項附驗證指令）

| # | 項目 | 星級 | 設定值 | 驗證指令（`sudo sshd -T` 為準） |
| --- | --- | --- | --- | --- |
| 1 | `PermitRootLogin` | ★★★★ | `no` | `sudo sshd -T \| grep -i permitrootlogin` |
| 2 | `PasswordAuthentication` **+** `KbdInteractiveAuthentication` | ★★★★★ | 兩者皆 `no` | `sudo sshd -T \| grep -iE 'passwordauth\|kbdinteractive'` |
| 3 | `AllowGroups` | ★★★★ | `ssh-users` | `sudo sshd -T \| grep -i allowgroups` |
| 4 | `MaxAuthTries` | ★★★ | `3` | `sudo sshd -T \| grep -i maxauthtries` |
| 5 | `LoginGraceTime` | ★★★ | `30` | `sudo sshd -T \| grep -i logingracetime` |
| 6 | `AllowTcpForwarding` | ★★★ | 依角色（預設 `no`） | `sudo sshd -T \| grep -i allowtcpforwarding` |
| 7 | `PermitUserEnvironment` | ★★★ | `no` | `sudo sshd -T \| grep -i permituserenvironment` |
| 8 | `LogLevel` | ★★★★ | `VERBOSE` | `sudo sshd -T \| grep -i loglevel` |

> [!tip] `sshd -T` 才是唯一真相 ★★★★
> **不要用 `grep` 讀設定檔來驗收**。設定檔裡寫了什麼不代表生效：
> 可能被更前面的 drop-in 蓋掉、可能拼錯字被忽略、可能在 `Match` 區塊裡。
> `sshd -T`（extended test mode）印出的是 **sshd 實際採用的最終值**，全部小寫。
> 稽核報表請以 `sshd -T` 的輸出為證據。

### 第 1 項：`PermitRootLogin no` ★★★★

```bash
$ echo 'PermitRootLogin no' | sudo tee -a /etc/ssh/sshd_config.d/60-hardening.conf
$ sudo sshd -t && sudo systemctl reload ssh
$ sudo sshd -T | grep -i permitrootlogin
permitrootlogin no          # ★★★★ 只有這樣才算生效
```

| 值 | 意義 | 什麼時候只能用它 |
| --- | --- | --- |
| `no` ★★★★ | root 完全不能用 SSH 登入 | **預設就選這個** |
| `prohibit-password` ★★ | root 可用金鑰／憑證，不能用密碼 | 某些備份／儲存設備的複寫作業**只支援 root** 時 |
| `forced-commands-only` ★★★ | root 只能執行 `authorized_keys` 裡 `command=` 綁死的那條 | **比 `prohibit-password` 安全的替代** |
| `yes` ★★★★★ | **禁止使用** | 無 |

> [!danger] `prohibit-password` 不是免死金牌 ★★★
> 用它的機器，root 的 `authorized_keys` 就是**全機房最值錢的檔案** ——
> 那把私鑰在誰的筆電裡？有沒有 passphrase？離職時誰負責撤掉？
> ★★★★ 更好的做法是 `forced-commands-only` + 綁死指令：
> ```text
> restrict,command="/usr/local/bin/backup-pull",from="10.0.30.9" ssh-ed25519 AAAA...
> → 就算私鑰外洩，對方也只能觸發那支備份腳本，拿不到 shell
> ```

### 第 2 項：真正關掉密碼登入 ★★★★★

**這是本篇最重要的一段。** 絕大多數「加固完成」的機器都栽在這裡。

```ini
PasswordAuthentication no
KbdInteractiveAuthentication no      # ★★★★★ 少了這行，密碼登入其實還開著
PermitEmptyPasswords no
UsePAM yes                            # ★★ 不要關，關了 sudo 記帳、pam_faillock、session 都會壞
AuthenticationMethods publickey
```

> [!danger] 為什麼 `PasswordAuthentication no` 關不掉密碼 ★★★★★
> ```text
> SSH 有【兩條】會問密碼的路：
>   路 A: "password" 方法             ← PasswordAuthentication 管這條
>   路 B: "keyboard-interactive" 方法 ← KbdInteractiveAuthentication 管
>          └→ PAM → /etc/pam.d/sshd 的 @include common-auth → pam_unix.so
>             └→ 【它會問密碼，驗證的是同一組 /etc/shadow】
>
> ★★★★★ 只關 PasswordAuthentication，攻擊者用
>   ssh -o PreferredAuthentications=keyboard-interactive 一樣能撞密碼，
>   而且【你的稽核報表會誤報為「已停用」】。
> ★★★★ 8.7 以前這選項叫 ChallengeResponseAuthentication，抄舊文章 → 新版直接忽略。
> ```

**實測驗證（★★★★★ 一定要做，不然等於沒關）**：

```bash
# ★ 先測 password 方法
$ ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no ops@web01
ops@web01: Permission denied (publickey).

# ★★★★★ 再測 keyboard-interactive —— 這才是照妖鏡
$ ssh -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no ops@web01
ops@web01: Permission denied (publickey).      # ← 加固成功
```

**加固失敗**會長這樣 —— 看到密碼提示就代表你剛剛的加固是假的：

```text
(ops@web01) Password:                          # ★★★★★ 出現這行 = 密碼登入還開著
```

> [!tip] 之後要導入 2FA 的人請注意
> 導入 TOTP 時**必須把 `KbdInteractiveAuthentication` 開回 `yes`**，
> 那時要靠 `AuthenticationMethods publickey,keyboard-interactive` 與
> **改 `/etc/pam.d/sshd` 拿掉 `@include common-auth`** 才不會把密碼登入一起開回來。
> 見〈2FA 的取捨〉與 [[07-身分存取管理IAM與MFA]]。

### 第 3 項：`AllowGroups ssh-users` ★★★★

```bash
$ sudo groupadd -f ssh-users && sudo usermod -aG ssh-users ops
$ getent group ssh-users
ssh-users:x:1002:ops,deploy      # ★★★★ 確認每個要進來的人都在，包含監控與備份的服務帳號
```

```ini
AllowGroups ssh-users
```

| 指令 | 何時用 | 陷阱 |
| --- | --- | --- |
| `AllowGroups` ★★★★ | **預設選這個**：白名單、跟著人事異動走 | 加進群組後**要重新登入**才生效 |
| `AllowUsers` ★★ | 只有一兩個固定帳號 | 每加一個人都要改設定檔＋reload |
| `DenyGroups` / `DenyUsers` ★ | 臨時封鎖單一帳號 | 黑名單天生會漏，不要當主要手段 |

> [!danger] `AllowGroups` 最常見的翻車 ★★★★
> 套下去會**立刻**被鎖在外面的三種人：①你自己（忘了把自己加進去）；
> ②監控（Zabbix／Nagios 的檢查帳號、Ansible 帳號）；③備份與 CI 的服務帳號。
> ```bash
> # ★★★★ 套用前先跑：過去 90 天登入過的帳號，一個都不能漏
> $ sudo lastlog -t 90 | awk 'NR>1 {print $1}' | sort -u
> ansible
> deploy
> ops
> zabbix          # ★★★★ 這個很容易被忘記 → 套下去後監控全紅
> ```

### 第 4／5 項：`MaxAuthTries 3` 與 `LoginGraceTime 30` ★★★

```bash
# MaxAuthTries：單一連線最多試 3 次認證；LoginGraceTime：未完成認證最多佔 30 秒（預設 120 太長）
$ sudo sshd -T | grep -iE 'maxauthtries|logingracetime'
maxauthtries 3
logingracetime 30
```

> [!warning] `MaxAuthTries` 會誤傷「金鑰很多」的自己人 ★★★
> ```text
> ssh-agent 裡有 6 把金鑰時，客戶端會【一把一把送】給伺服器試 →
>   Received disconnect from 10.0.20.15 port 22:2: Too many authentication failures
> ★★★ 這【不是】伺服器設錯，是客戶端該修（~/.ssh/config）：
>   Host web01
>     IdentityFile ~/.ssh/id_ed25519_web
>     IdentitiesOnly yes      ← ★★★★ 只送指定的那一把（見 [[03-SSH-客戶端設定檔]]）
> ★★ LoginGraceTime 也別太短：要觸碰 FIDO2 金鑰或等 OTP 時 30 秒可能不夠
>    → 有 2FA 的機器在 Match 區塊裡放寬到 60。
> ```

### 第 6 項：`AllowTcpForwarding` 依角色 ★★★

```ini
# 主線：一律關掉
AllowTcpForwarding no
AllowAgentForwarding no
AllowStreamLocalForwarding no
GatewayPorts no
PermitTunnel no
X11Forwarding no
```

| 角色 | 建議 |
| --- | --- |
| **一般 Web／DB 伺服器** ★★★★ | 全關；沒有正當用途，帳號被盜時攻擊者會用 `-D` 把你的機器當跳板打內網 |
| **跳板機 bastion** ★★★ | `AllowTcpForwarding yes` + `PermitOpen 10.0.30.11:3306` 白名單 + `ForceCommand /usr/sbin/nologin`（只給隧道不給 shell） |
| **SFTP 專用帳號** ★★★★ | `Match Group sftp-only` 內 `DisableForwarding yes` → [[06-SFTP-與受限使用者]] |

> [!danger] `AllowTcpForwarding no` 擋不住有 shell 的人 ★★★★
> 它只關掉 **SSH 協定層**的 `-L` / `-R` / `-D`。使用者拿得到 shell 就能自己跑
> `socat` / `ncat`，或從機器**往外**再開一條隧道。
> ★★★★ 它是**縱深防禦的一層**，不是隔離手段；真要隔離請用
> `ForceCommand` + 無 shell 帳號，並在防火牆限制這台機器的**出向**連線。
> ★★★ `AllowAgentForwarding no` 特別重要：agent forwarding 會把你的 agent socket
> 暴露在遠端，遠端 root 可用它**冒充你去登入任何機器** → 串接請改用 `ProxyJump`
> （見 [[05-SSH-隧道與埠轉發]]）。

### 第 7 項：`PermitUserEnvironment no` ★★★

```bash
# 另外保留 AcceptEnv LANG LC_*（★★ 只影響語系）
$ sudo sshd -T | grep -i permituserenvironment
permituserenvironment no
```

> [!warning] 為什麼要明確寫死 ★★★
> 開啟時使用者可在 `~/.ssh/environment` 或 `authorized_keys` 的 `environment=`
> 設定**任意環境變數**。最典型的提權路徑是設 `LD_PRELOAD`：登入時載入自己的共享函式庫
> → **繞過 `ForceCommand` 與受限 shell**。預設就是 `no`，但很多從網路抄來的設定會打開它。

### 第 8 項：`LogLevel VERBOSE` ★★★★

```ini
LogLevel VERBOSE
```

| 等級 | 記到什麼 | 評價 |
| --- | --- | --- |
| `INFO`（預設） | 成功登入那行**已含**所用公鑰指紋 | 不夠：查不到「誰用哪把金鑰試過但失敗」 |
| `VERBOSE` ★★★★ | 加記**每一把被提供過的公鑰指紋**與失敗原因 | **CIS／TWGCB 要求的等級** |
| `DEBUG*` ★★★★★ | 極大量輸出，**可能記到敏感資訊** | **正式機禁用** |

```bash
$ sudo journalctl -u ssh -n 20 --no-pager | grep -E 'Accepted|Failed'
Aug 28 09:12:31 web01 sshd[2311]: Accepted publickey for ops from 10.0.20.5 port 51234 ssh2: ED25519 SHA256:N84r82PdXq72rYLIq+mwcAOqbb4BEmpnjN7u7rkSD5M
Aug 28 09:14:02 web01 sshd[2402]: Failed publickey for invalid user admin from 203.0.113.9 port 40122 ssh2: RSA SHA256:9Xf0k...   # ★★★★ VERBOSE 才有這行
```

> [!danger] 指紋是事後追人的**唯一線索** ★★★★
> ```text
> 事件調查時你唯一能問的是：「09:12 從 10.0.20.5 登入的 ops，用的是【哪一把金鑰】？」
>   有指紋 → 比對金鑰清冊 → 「李工程師 2025 年配發那把」→ 找得到人
>   沒指紋 → 只知道有人用 ops 登入 → 【全公司都有嫌疑】→ 結不了案
> ★★★ 代價：日誌量約為 INFO 的 2～3 倍 → 配合 [[02-日誌集中與輪替]]、[[09-日誌集中與SIEM]]
> ```

### 其餘應該一起寫進去的項目

```ini
# ═══ 逾時（★★★ 稽核基準常見要求：閒置 15 分鐘斷線）═══
ClientAliveInterval 300
ClientAliveCountMax 3               # 300 x 3 = 15 分鐘
TCPKeepAlive no                     # ★★ 避免偽造的 keepalive 維持殭屍 session

# ═══ 主機金鑰：只留 ed25519 與 rsa ★★★（ecdsa 建議註解掉）═══
HostKey /etc/ssh/ssh_host_ed25519_key
HostKey /etc/ssh/ssh_host_rsa_key

# ═══ 其他 ═══
StrictModes yes                     # ★★★ ~/.ssh 權限太寬就拒絕，別關
IgnoreRhosts yes
HostbasedAuthentication no
UseDNS no                           # ★★ 開著會讓 DNS 慢時登入卡 30 秒
Banner /etc/issue.net               # ★★★ 機關法遵：登入前的未授權使用警語
Subsystem sftp internal-sftp        # ★★ internal-sftp 才能配合 ChrootDirectory
```

`/etc/issue.net`（**機關稽核常被要求**）：

```text
 本系統為 XX 機關資訊設備，僅限授權人員使用。
 所有連線行為均予記錄與稽核，未經授權之存取將依法追訴。
 Unauthorised access to this system is prohibited and will be prosecuted.
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照 ★★★★
> **最大的坑：`crypto-policies` 是系統層決定的，會蓋掉你在 `sshd_config` 寫的演算法。**
>
> ```bash
> $ sudo update-crypto-policies --show
> DEFAULT
>
> # ★★★★ 關鍵：看清楚 sshd 到底 include 了什麼
> $ grep -rn 'Include' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/
> /etc/ssh/sshd_config:17:Include /etc/ssh/sshd_config.d/*.conf
> /etc/ssh/sshd_config.d/50-redhat.conf:1:Include /etc/crypto-policies/back-ends/opensshserver.config
> ```
>
> ```text
> ★★★★★ 因為 sshd 是「先讀到的值贏」：
>   50-redhat.conf 先被讀 → 它 include 的 opensshserver.config 裡的
>   Ciphers/MACs/KexAlgorithms 就【定案】
>     → 你放在 60-hardening.conf 的 Ciphers【完全不生效】
>       → 而且 sshd -t 不會報錯，你會以為成功了
> ```
>
> **做法 A（建議）：改系統政策或加自訂子政策**
>
> ```bash
> $ sudo update-crypto-policies --set DEFAULT:NO-SHA1
> $ sudo update-crypto-policies --show
> DEFAULT:NO-SHA1
> $ sudo systemctl reload sshd            # ★★★ RHEL 的服務名是 sshd，不是 ssh
> ```
>
> 自訂子政策（副檔名必須是 `.pmod`）：
>
> ```bash
> sudo tee /etc/crypto-policies/policies/modules/SSH-HARDEN.pmod >/dev/null <<'EOF'
> ssh_cipher = -AES-*-CBC -3DES-CBC
> mac        = -HMAC-SHA1
> EOF
> sudo update-crypto-policies --set DEFAULT:SSH-HARDEN
> ```
>
> **做法 B：用編號小於 50 的 drop-in 硬蓋過去**（例如 `40-hardening-crypto.conf`）。
> ★★★★ 代價：這台機器的 SSH 與系統政策**不一致**，下次有人跑
> `update-crypto-policies` 排錯時會非常困惑，OpenSCAP／TWGCB 掃描也可能判定
> 「未套用系統政策」→ 機關環境建議用做法 A。
>
> **其他差異**：服務名 `sshd`；防火牆用 `firewalld`；**SELinux 開著**，
> 改埠必須 `sudo semanage port -a -t ssh_port_t -p tcp 52222`；
> `/etc/sysconfig/sshd` 的 `CRYPTO_POLICY=` 在 RHEL 9 **已被忽略**，別再照 RHEL 8 的文章做。

---

## 進階設定與調校

### 演算法加固 ★★★★

#### 先查本機支援什麼，再決定要留什麼

**不要照抄網路上的清單**：抄來的若有本機不支援的，`sshd -t` 直接報錯；
更糟的是只留下客戶端不支援的，你就把自己鎖在外面了。

```bash
$ ssh -Q kex
diffie-hellman-group1-sha1              # ★★★★★ 1024-bit + SHA-1，必須排除
diffie-hellman-group14-sha1             # ★★★★ SHA-1，排除
diffie-hellman-group-exchange-sha1      # ★★★★★ 排除（Logjam）
diffie-hellman-group14-sha256 / group16-sha512 / group18-sha512
ecdh-sha2-nistp256 / p384 / p521        # ★★ NIST 曲線，可留作相容
curve25519-sha256                       # ★★★★ 主力
sntrup761x25519-sha512@openssh.com      # ★★★★ 後量子混合（9.0+）
mlkem768x25519-sha256                   # ★★★★ 後量子混合（10.0+，NIST 標準化）

$ ssh -Q cipher | tr '\n' ' '; echo; ssh -Q mac | grep etm | tr '\n' ' '
3des-cbc aes128-cbc aes192-cbc aes256-cbc      ← ★★★★★ CBC 與 3DES 全部排除
aes128-ctr aes192-ctr aes256-ctr               ← ★★ 非 AEAD，僅相容用
aes128-gcm@ aes256-gcm@ chacha20-poly1305@     ← ★★★★ 只留這三個
hmac-sha1-etm@ hmac-md5-etm@ umac-64-etm@      ← ★★★★ SHA-1／MD5／64-bit tag，排除
hmac-sha2-256-etm@ hmac-sha2-512-etm@          ← ★★★★ 只留這兩個
```

#### 建議值與理由

```ini
KexAlgorithms sntrup761x25519-sha512@openssh.com,curve25519-sha256,curve25519-sha256@libssh.org
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com
HostKeyAlgorithms ssh-ed25519-cert-v01@openssh.com,ssh-ed25519,rsa-sha2-512,rsa-sha2-256
PubkeyAcceptedAlgorithms ssh-ed25519-cert-v01@openssh.com,ssh-ed25519,rsa-sha2-512,rsa-sha2-256
CASignatureAlgorithms ssh-ed25519,rsa-sha2-512
```

| 設定項 | 理由 | 星級 |
| --- | --- | --- |
| `KexAlgorithms` | 混合式後量子抵抗「**現在竊錄、將來解密**」；curve25519 不依賴 NIST 曲線參數 | ★★★★ |
| `Ciphers` | 只留 **AEAD**：加密與完整性綁在一起，沒有 MAC 順序問題；CBC 有 padding oracle 與 Terrapin 歷史 | ★★★★ |
| `MACs` | 只留 `*-etm`＝Encrypt-then-MAC，**先驗 MAC 再解密**；非 ETM 要先解密才驗，攻擊面較大 | ★★★★ |
| `HostKeyAlgorithms` | 明確排除 `ssh-rsa`（SHA-1 簽章）與 `ecdsa-*` | ★★★ |
| `PubkeyAcceptedAlgorithms` | **控制使用者金鑰**：擋掉還在用 SHA-1 RSA 金鑰的老客戶端 | ★★★ |

★★ 只留 AEAD 時 `MACs` 其實用不到（協商會顯示 `<implicit>`），
但**兩個都要設**：`Ciphers` 是主防線，`MACs` 是相容性例外時的第二道。

#### 相容性評估 ★★★★（套下去之前一定要做）

演算法加固是本篇**唯一會把「別人」弄壞**的一項。先列出「誰會連進這台機器」。

| 客戶端／設備 | 會不會壞 | 症狀與處理 |
| --- | --- | --- |
| OpenSSH ≥ 8.0 的 Linux／macOS | 不會 | —— |
| **PuTTY < 0.75 / WinSCP < 5.19** ★★★ | **會** | `Couldn't agree a key exchange algorithm` → 升級客戶端 |
| **Java 8 的 JSch 0.1.5x** ★★★★ | **會** | `Algorithm negotiation fail`，**排程作業整批失敗** → 換 `com.github.mwiede:jsch` |
| Python `paramiko` < 2.9 ★★★ | 部分 | RSA SHA-1 被拒 → 升級到 ≥ 2.9 |
| **老備份軟體／NAS 的 rsync over SSH** ★★★★★ | **會** | **靜默失敗，數天後才發現** → 先在測試機驗證或做例外 |
| **UPS／IPMI／BMC 的 SSH 客戶端** ★★★★ | **會** | 通常無法升級 → 做例外或改走別的協定 |
| Windows 內建 OpenSSH（1809+） | 不會 | 版本較舊，先測 |

```bash
# ★★★★ 加固前先跑一週：實際連進來的客戶端版本
$ sudo journalctl -u ssh --since "7 days ago" --no-pager \
    | grep -oP 'remote software version \K.*' | sort | uniq -c | sort -rn
    412 OpenSSH_10.2p1 Ubuntu-2ubuntu3.5
     88 OpenSSH_8.9p1 Ubuntu-3ubuntu0.10
     31 PuTTY_Release_0.83
      7 JSCH-0.1.55                       # ★★★★★ 找到了：這個一加固就會死
```

> [!danger] 例外只能用「第二個實例」，不能用 `Match` ★★★★
> ```text
> ★★★★ Ciphers / MACs / KexAlgorithms 【不能】寫在 Match 區塊裡：
>   這些是「協商階段」的設定，發生在 sshd 知道對方 IP 之前，
>   Match 只影響「認證與 session 階段」。
>   → 硬寫會得到 "Directive 'Ciphers' is not allowed within a Match block"
>
> ★★★★ 正確做法：開第二個 sshd 實例，綁【內網 IP + 另一個埠】，
>   防火牆只放行那台老設備，並用 AllowUsers + ForceCommand 限制到只能做一件事。
> ```

```ini
# /etc/ssh/sshd_config_legacy   ★★★★ 隔離實例
Port 2202
ListenAddress 10.0.20.15
PidFile /run/sshd-legacy.pid
LogLevel VERBOSE
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
AllowUsers backupsvc
ForceCommand /usr/local/bin/backup-pull      # ★★★★ 只能做備份，拿不到 shell
KexAlgorithms +diffie-hellman-group14-sha256 # ★★★ 用 + 疊加，不要整串覆寫
Ciphers +aes256-ctr
MACs +hmac-sha2-256
```

```bash
# unit：ExecStart=/usr/sbin/sshd -D -f /etc/ssh/sshd_config_legacy（ExecStartPre 先 sshd -t）
$ sudo systemctl daemon-reload && sudo systemctl enable --now sshd-legacy
$ sudo ss -tlnp | grep -E ':22 |:2202 '
LISTEN 0 128   0.0.0.0:22    0.0.0.0:*  users:(("sshd",pid=1120,fd=3))
LISTEN 0 128 10.0.20.15:2202 0.0.0.0:*  users:(("sshd",pid=3311,fd=3))   # ★★★ 只綁內網
```

★★★★ 例外必須有**落日期限**：在工單寫明「2027-03-31 前汰換該備份軟體，屆時關閉 sshd-legacy」，
否則這個例外會永遠留著，變成下一次資安事件的入口。

> [!tip] `+` / `-` / `^` 三個前綴 ★★★
> 無前綴＝**整串取代**（加固建議用這個，明確可稽核）；`+` 尾端追加；
> `-` 從預設移除；`^` 插到最前面提高優先序。

#### 用 ssh-audit 與 nmap 驗算法 ★★★★

```bash
$ sudo apt install -y pipx && pipx install ssh-audit
$ ssh-audit -L | head -3                       # 列出內建政策（3.9.0 起含 Ubuntu 24.04 政策）
$ ssh-audit 10.0.20.15
(gen) software: OpenSSH 10.2p1
(gen) compatibility: OpenSSH 9.9+, Dropbear SSH 2020.79+     # ★★★ 這行就是相容性警告
(kex) sntrup761x25519-sha512@openssh.com  -- [info] available since OpenSSH 8.5
(enc) chacha20-poly1305@openssh.com       -- [info] available since OpenSSH 6.5
(rec) mlkem768x25519-sha256               -- kex algorithm to append   # ★★ 10.0+ 才有
```

```bash
# ★★★★ 政策稽核：Result 那一行可以直接當成交付給稽核的證據
$ ssh-audit -P "Hardened Ubuntu Server 24.04 LTS (version 1)" 10.0.20.15
Host:   10.0.20.15:22
Policy: Hardened Ubuntu Server 24.04 LTS (version 1)
Result: ✔ Passed
```

失敗時會逐項列出差異（`Expected` / `Actual`），直接指出多留了哪個演算法。

```bash
# ★★ 沒有 ssh-audit 時的替代，也適合掃網段
$ nmap -p 22 --script ssh2-enum-algos 10.0.20.15
|   encryption_algorithms: (3)
|       chacha20-poly1305@openssh.com
|       aes256-gcm@openssh.com
|       aes128-gcm@openssh.com          # ★★★ 只該看到 AEAD
|   mac_algorithms: (2)
|       hmac-sha2-512-etm@openssh.com
|       hmac-sha2-256-etm@openssh.com   # ★★★ 只該看到 -etm
```

---

### 來源限制的三層 ★★★★

**三層都要有**，因為每一層的失效模式不同：

```text
第一層  防火牆（ufw / nftables / firewalld / 雲端 Security Group）
        ↓ 失效：規則寫成 anywhere、IPv6 那條忘了設、雲端 SG 被別人改
第二層  authorized_keys 的 from=
        ↓ 失效：只綁在「那一把金鑰」，換一把金鑰就沒有限制了
第三層  sshd 的 Match Address（差異化策略）
        ↓ 失效：Match 只影響認證階段，不影響 TCP 是否連得上
```

#### 第一層：防火牆只開管理網段

```bash
# ★★★★ 先加新規則，確認能連，再刪舊規則 —— 順序不可顛倒
$ sudo ufw allow from 10.0.20.0/24 to any port 22 proto tcp comment 'SSH mgmt net'
$ sudo ufw allow from 203.0.113.64/28 to any port 22 proto tcp comment 'SSH VPN pool'
$ sudo ufw status numbered
[ 1] 22/tcp      ALLOW IN  Anywhere            # ★★★★★ 這條要刪
[ 2] 22/tcp (v6) ALLOW IN  Anywhere (v6)       # ★★★★★ 這條【最常被忘記】
[ 3] 22/tcp      ALLOW IN  10.0.20.0/24        # SSH mgmt net
[ 4] 22/tcp      ALLOW IN  203.0.113.64/28     # SSH VPN pool

# ★★★★ 確認新規則可用【之後】才刪；從高號碼往低刪，否則編號會位移
$ sudo ufw delete 2 && sudo ufw delete 1
```

規則語法與 nftables 寫法見 [[02-防火牆-ufw基礎與實務]]、[[03-防火牆-nftables與iptables]]。

#### 第二層：`authorized_keys` 的 `from=`

```text
# ~deploy/.ssh/authorized_keys
restrict,pty,from="10.0.30.20,10.0.30.21",command="/usr/local/bin/deploy.sh" ssh-ed25519 AAAAC3Nza... ci-runner
```

| 選項 | 作用 | 星級 |
| --- | --- | --- |
| `restrict` ★★★★ | **一次關掉**所有轉發、pty、agent、X11、user-rc；要什麼再加回來 | ★★★★ |
| `from="..."` ★★★★ | 只允許這些來源用**這把金鑰**；支援萬用字元與 `!` 否定 | ★★★★ |
| `command="..."` ★★★★ | 不論使用者下什麼指令，都只執行這一條 | ★★★★ |
| `expiry-time="20261231"` ★★★ | **金鑰自動到期**（OpenSSH 8.2+）—— 對抗殭屍金鑰的低成本手段 | ★★★ |
| `no-touch-required` ★★ | FIDO2 金鑰免觸碰（自動化用；**互動帳號不要加**） | ★★ |

> [!tip] `expiry-time=` 是最被低估的一招 ★★★
> 還沒導入 SSH CA 之前，**先給每把 `authorized_keys` 的金鑰加上到期日**：
> ```text
> restrict,pty,expiry-time="20270331" ssh-ed25519 AAAA... wangdm@laptop
> ```
> 成本只有一行，卻能保證「就算沒人來清，一年後也會自己失效」。
> 到期後登入會直接失敗，日誌顯示 `Authentication key ... expired`。

#### 第三層：`Match Address` 差異化策略 ★★★★

```ini
# ═══ 全域：最嚴 ═══
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthenticationMethods publickey
AllowTcpForwarding no
LoginGraceTime 30

# ═══ 內網管理網段：允許 2FA，寬限時間拉長 ★★★ ═══
Match Address 10.0.20.0/24
    KbdInteractiveAuthentication yes
    AuthenticationMethods publickey,keyboard-interactive
    LoginGraceTime 60

# ═══ 外網：只允許憑證，且只給特定群組 ★★★★ ═══
Match Address *,!10.0.20.0/24,!10.0.30.0/24
    AllowGroups ssh-remote
    AuthenticationMethods publickey
    MaxAuthTries 2

# ═══ CI 部署帳號：綁死指令、不給 pty ★★★★ ═══
Match User deploy Address 10.0.30.20/32
    PermitTTY no
    ForceCommand /usr/local/bin/deploy.sh
```

**驗證 `Match` 真的生效（★★★★ 很多人不知道可以這樣測）**：

```bash
# -C 帶入「假想的連線條件」，印出【在那個條件下】的最終設定
$ sudo sshd -T -C user=ops,host=web01,addr=10.0.20.5 | grep -iE 'kbdinteractive|logingracetime'
kbdinteractiveauthentication yes
logingracetime 60                       # ★★★★ 證明 Match Address 10.0.20.0/24 生效了

$ sudo sshd -T -C user=ops,host=web01,addr=203.0.113.9 | grep -iE 'kbdinteractive|allowgroups'
kbdinteractiveauthentication no
allowgroups ssh-remote                  # ★★★★ 外網走的是另一組規則
```

> [!danger] `Match` 區塊的四個致命細節 ★★★★
> ```text
> ① Match 之後的設定【都屬於那個區塊】直到下一個 Match 或檔尾
>    → 千萬不要在檔尾放 Match 後又補全域設定
> ② Ciphers / MACs / KexAlgorithms / HostKey 【不能】放在 Match 裡
> ③ Match Address 比對【TCP 來源 IP】→ ★★★★ 過了 NAT／負載平衡器就全變同一個 IP，策略失效
> ④ 用 Match 放寬時要想清楚：Match Address 10.0.0.0/8 → AuthenticationMethods any
>    等於【只要進到內網就繞過所有加固】，內網被打穿時你什麼都沒有
> ```

---

### 暴力破解與洪水防護

#### `MaxStartups` 與 `PerSourcePenalties` ★★★

```ini
MaxStartups 10:30:60
PerSourcePenalties authfail:10s noauth:5s grace-exceeded:30s max:1800s   # OpenSSH 9.8+
PerSourcePenaltyExemptList 10.0.20.0/24,10.0.30.0/24                     # ★★★ 避免自己人被誤鎖
PerSourceMaxStartups 3                                                    # ★★★ 單一來源最多 3 條未認證連線
```

```text
MaxStartups start:rate:full
   10 : 30 : 60
    │    │    └── 未認證連線達 60 條時【全部拒絕】
    │    └─────── 超過 start 後以 30% 起跳的機率隨機拒絕（線性內插到 100%）
    └──────────── 低於 10 條時全部接受

★★★ 預設 10:30:100。調小能更早丟棄洪水，
     但機器上跑 Ansible fork 50 這類大量並行時【會誤傷自己】，
     症狀是 kex_exchange_identification: Connection closed by remote host 隨機失敗。
```

```bash
$ sudo journalctl -u ssh --since today | grep -i maxstartups
Aug 28 03:14:07 web01 sshd[1120]: error: beginning MaxStartups throttling   # ★★★ 開始丟連線
Aug 28 03:19:41 web01 sshd[1120]: error: exited MaxStartups throttling after 05:34, 218 connections dropped

$ sudo sshd -T | grep -i persourcepenalties
persourcepenalties enabled:yes crash:90 authfail:5 noauth:1 grace-exceeded:20 max:600 min:15 ...
```

> [!tip] 有了 `PerSourcePenalties` 還需要 fail2ban 嗎？★★★
> 要，角色不同：前者作用在 **sshd 內部**、秒～分鐘等級、**重開機不保留**、無法通報；
> fail2ban 作用在**防火牆**（可擋所有埠）、小時～永久、可關聯 Nginx 等其他服務、
> 可 action 到 Wazuh／SIEM。**兩個都開**：前者擋瞬間洪水，後者做長期封鎖與通報。

#### fail2ban 最小可用 jail ★★★

```ini
# /etc/fail2ban/jail.d/sshd-minimal.local     ★★★ 最小可用，調校見專篇
[sshd]
enabled  = true
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
ignoreip = 127.0.0.1/8 ::1 10.0.20.0/24      # ★★★★ 一定要放自己的管理網段
```

```bash
$ sudo systemctl restart fail2ban && sudo fail2ban-client status sshd
Status for the jail: sshd
|- Filter:  Currently failed: 2  Total failed: 1483
`- Actions: Currently banned: 7  Total banned: 214
```

**jail 語法、filter 撰寫、誤封解除、遞增封鎖 → [[05-Fail2ban入侵防護]]，本篇不重複。**

#### 最有效的一招：把 SSH 從公網下架 ★★★★★

```text
上面所有防護加起來的效果，都比不上這一句：【外網根本連不到 TCP/22】

  維運人員 ══WireGuard/OpenVPN══> VPN 閘道／跳板機 ──SSH──> 伺服器群

★★★★★ 效果：
  · 暴力破解嘗試從每天 3000 次 →【0 次】
  · OpenSSH 爆出 pre-auth RCE 時（例如 CVE-2024-6387 regreSSHion），
    你的伺服器【不在攻擊面上】，可照正常維護窗口更新，不必半夜緊急處理
  · 稽核時「管理介面未對外開放」是實質加分項

架構選型（VPN / 跳板機 / 零信任代理）→ [[06-遠端存取安全]]
```

---

### SSH 憑證式認證（CA）★★★★★

**這是本章其他篇都沒有的深水區，也是 SSH 加固能走到的最遠處。**

#### `authorized_keys` 為什麼一定會爛掉

```text
機器 30 台 x 人員 12 人 x 每人 2 把金鑰 = 720 筆散落的授權
  新人報到 → 上 30 台加公鑰（漏一台 = 他抱怨；多一台 = 越權）
  換筆電   → 再來一次
  ★★★★★ 離職 → 上 30 台刪公鑰 → 漏一台，那把私鑰【永遠】能登入那台
           而且日誌看起來完全正常，沒有任何異常可偵測
★★★★ 更糟的是：你根本【不知道】漏了哪一台。
     authorized_keys 沒有到期日、沒有中央清單、沒有撤銷機制。
```

**SSH CA 把「授權」從「每台機器的檔案」改成「一張會過期的憑證」**：

```text
  ┌────────────────────────────────┐
  │ 離線 CA 工作站                  │  ★★★★★ CA 私鑰只在這裡
  │  ca_user_key / ca_host_key     │
  └──────────┬─────────────────────┘
             │ 簽發（有效期 8 小時）
  ┌─────────┐▼          ┌──────────────────────────┐
  │ 維運人員 │ ──憑證──> │ 30 台伺服器               │
  └─────────┘           │ TrustedUserCAKeys        │
                        │  = ca_user_key.pub（一行）│
                        └──────────────────────────┘

★★★★★ 離職怎麼辦？→【什麼都不用做】。憑證 8 小時後自己失效，之後再也簽不到新的。
```

#### 【1】建立內部 SSH CA

```bash
# ★★★★★ 這一步請在【離線工作站】或專用管理機上做，不要在伺服器上做
$ sudo install -d -m 700 /etc/ssh-ca && cd /etc/ssh-ca
$ ssh-keygen -t ed25519 -f ca_user_key -C "SSH User CA - example.gov.tw"   # ★★★★ 使用者 CA
$ ssh-keygen -t ed25519 -f ca_host_key -C "SSH Host CA - example.gov.tw"   # ★★★★ 主機 CA，必須分開
$ ssh-keygen -lf ca_user_key.pub
256 SHA256:TP9udeo7o9ZWUoujh7qlqcoxgbR+cXhSHLDHshublwg SSH User CA - example.gov.tw (ED25519)
```

> [!danger] CA 私鑰＝全機房萬能鑰匙 ★★★★★
> ```text
> ★★★★★ 拿到 ca_user_key 的人可以簽出 principals=root 的憑證
>   →【同時登入所有伺服器】，而且日誌上每一次都是合法的憑證登入
>   → 比任何一把使用者私鑰外洩嚴重數十倍
>
> 必要防護（缺一不可）：
>   ① CA 私鑰【不放在任何一台被 CA 信任的伺服器上】
>   ② 存放在離線工作站、HSM、YubiKey（ssh-keygen -t ed25519-sk）或 Vault
>   ③ 私鑰一定要有 passphrase
>   ④ 簽發要留紀錄（誰、何時、給誰、什麼 principals、多久）
>   ⑤ 定期演練 CA 換發：TrustedUserCAKeys 可放【多把】公鑰，新舊並存 → 換完 → 移除舊的
>
> ★★★★ 使用者 CA 與主機 CA 必須分開：否則撤銷 CA 時人與機器【必須同時停擺】，
>       無法分階段處理，而且兩種身分會混用同一個信任錨。
> ```

#### 【2】簽發短效使用者憑證

```bash
$ ssh-keygen -s ca_user_key -I "wangdm-20260828" -n wangdm,webadmin -V +8h -z 1001 wangdm.pub
Signed user key wangdm-cert.pub: id "wangdm-20260828" serial 1001 for wangdm,webadmin valid from 2026-08-28T18:44:00 to 2026-08-29T02:45:18
```

| 旗標 | 意義 | 星級 |
| --- | --- | --- |
| `-s ca_user_key` | 用哪把 CA **私鑰**簽 | ★★★★★ |
| `-I "wangdm-20260828"` | Key ID，**會完整寫進日誌**，事後追人的欄位 | ★★★★ |
| `-n wangdm,webadmin` | principals（角色），**使用者憑證必填** | ★★★★ |
| `-V +8h` | 有效期。**短效是整個機制的價值來源**，不要簽一年 | ★★★★★ |
| `-z 1001` | 序號，KRL 撤銷時用得到 | ★★★ |
| `-h` | **簽主機憑證時才加**，不加就是使用者憑證 | ★★★★ |

```bash
$ ssh-keygen -L -f wangdm-cert.pub
        Type: ssh-ed25519-cert-v01@openssh.com user certificate
        Signing CA: ED25519 SHA256:TP9udeo7o9ZWUoujh7qlqcoxgbR+cXhSHLDHshublwg (using ssh-ed25519)
        Key ID: "wangdm-20260828"
        Serial: 1001
        Valid: from 2026-08-28T18:44:00 to 2026-08-29T02:45:18       # ★★★★ 8 小時後自動失效
        Principals: wangdm, webadmin
        Critical Options: (none)
        Extensions: permit-X11-forwarding permit-agent-forwarding
                    permit-port-forwarding permit-pty permit-user-rc  # ★★★★ 沒 permit-pty 就沒終端機
```

**加限制的憑證（CI／自動化用）**：

```bash
$ ssh-keygen -s ca_user_key -I "deploy-ci-20260828" -n deploy -V +1h \
    -O clear -O permit-pty \
    -O force-command="/usr/local/bin/deploy.sh" \
    -O source-address=10.0.30.20/32 ci.pub
$ ssh-keygen -L -f ci-cert.pub | grep -A3 'Critical Options'
        Critical Options:
                force-command /usr/local/bin/deploy.sh    # ★★★★ 綁死指令
                source-address 10.0.30.20/32              # ★★★★ 綁死來源，比 from= 更難繞過
```

> [!danger] `-O clear` 的經典翻車 ★★★★
> `-O clear` 會**清掉所有 extensions**（含 `permit-pty`）。忘了補回去的結果是
> `PTY allocation request failed on channel 0` —— 登入「成功」但**沒有終端機**。
> ★★★ 自動化帳號本來就不該有 pty，所以不補是對的；**人要用的憑證一定要補**。

#### 【3】伺服器端信任 CA

```ini
TrustedUserCAKeys /etc/ssh/ca_user_key.pub
AuthorizedPrincipalsFile /etc/ssh/auth_principals/%u
RevokedKeys /etc/ssh/revoked_keys.krl
CASignatureAlgorithms ssh-ed25519,rsa-sha2-512
```

```bash
$ sudo install -m 644 ca_user_key.pub /etc/ssh/ca_user_key.pub
$ sudo install -d -m 755 /etc/ssh/auth_principals
$ printf 'webadmin\nsysadmin\n' | sudo tee /etc/ssh/auth_principals/ops
webadmin
sysadmin
$ sudo sshd -t && sudo systemctl reload ssh
```

```text
★★★★ 授權模型（兩層都要對才進得來）：
   憑證的 -n principals   ∩   /etc/ssh/auth_principals/<本機帳號>   ≠ 空集合

   憑證 principals = wangdm,webadmin；auth_principals/ops 內含 webadmin
     → ssh ops@web01   ✓
     → ssh root@web01  ✗（auth_principals/root 不存在）

★★★★ 沒設 AuthorizedPrincipalsFile 時，OpenSSH 退回「principal 必須等於本機帳號名」，
     這通常不是你要的（每個人的憑證都得為每台機器重簽）。
```

```bash
# ★★★ 客戶端只要把憑證放在私鑰旁邊（檔名 <key>-cert.pub），ssh 會自動送出
$ ssh -v ops@web01 2>&1 | grep -i 'Offering\|Authenticated'
debug1: Offering public key: /home/wangdm/.ssh/id_ed25519 ED25519-CERT SHA256:N84r... explicit
debug1: Authenticated to web01 ([10.0.20.15]:22) using "publickey".

# 伺服器端日誌 —— 這就是憑證式認證的稽核價值
$ sudo journalctl -u ssh -n 5 --no-pager | grep Accepted
Accepted publickey for ops from 10.0.20.5 port 51244 ssh2: ED25519-CERT SHA256:N84r... ID wangdm-20260828 (serial 1001) CA ED25519 SHA256:TP9u...
```

★★★★ 日誌同時有 **Key ID（誰）**、**serial（哪一張）**、**CA 指紋（誰簽的）**；
`authorized_keys` 只給得出一個公鑰指紋。

#### 【4】主機憑證：一次解決 known_hosts 地獄

```bash
$ ssh-keygen -s ca_host_key -I "web01.example.gov.tw" -h \
    -n web01.example.gov.tw,web01,10.0.20.15 -V +52w ssh_host_ed25519_key.pub
Signed host key ssh_host_ed25519_key-cert.pub: id "web01.example.gov.tw" serial 0 for web01.example.gov.tw,web01,10.0.20.15 valid from 2026-08-28T18:44:00 to 2027-08-27T18:45:26
```

```ini
HostCertificate /etc/ssh/ssh_host_ed25519_key-cert.pub      # 伺服器端
```

```text
# 客戶端 /etc/ssh/ssh_known_hosts —— ★★★★ 全公司只要這一行
@cert-authority *.example.gov.tw,10.0.20.* ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... SSH Host CA
```

> [!tip] 主機憑證解決的真實痛點 ★★★★
> ```text
> 沒有主機憑證：
>   · 每台新機器第一次連線都問 "Are you sure you want to continue connecting?"
>     → ★★★★ 大家【養成無腦按 yes 的習慣】→ 中間人攻擊時也照按
>   · 重灌一台 → 所有人的 known_hosts 都要手動清那一行
>     → REMOTE HOST IDENTIFICATION HAS CHANGED 變成日常噪音 → 沒人再認真看
> 有主機憑證：
>   · 新機器簽一張 → 所有客戶端第一次連就直接信任，不問任何問題
>   · 重灌 → 重簽 → 客戶端無感
>   · ★★★★ 而且那個警告【恢復意義】：再看到它，就是真的有問題
> ```

#### 【5】撤銷：KRL

憑證短效（8 小時）本身就是最好的撤銷機制，但**私鑰當場外洩**時需要立刻失效：

```bash
$ ssh-keygen -k -f revoked_keys.krl id_ed25519.pub          # 建立／更新 KRL
Revoking from id_ed25519.pub
$ ssh-keygen -Qf revoked_keys.krl id_ed25519.pub; echo "exit=$?"
id_ed25519.pub (wangdm@ops): REVOKED
exit=1                                    # ★★★ 已撤銷時 exit code 為 1

# 派送到所有伺服器（用 Ansible／組態管理），sshd 端以 RevokedKeys 指向它
$ sudo install -m 644 revoked_keys.krl /etc/ssh/revoked_keys.krl && sudo systemctl reload ssh
```

#### 【6】導入策略：不要一次切換 ★★★★

```text
階段 1（並存 2～4 週）authorized_keys 與 TrustedUserCAKeys 同時保留，少數人先用憑證
階段 2（憑證為主）  全員改用憑證；authorized_keys 只留 1～2 把緊急備援金鑰（放保險箱）
                    監控還有多少人在用舊方式：
                      journalctl -u ssh | grep 'Accepted publickey' | grep -v 'ID '
階段 3（收斂）      清空 authorized_keys；★★★★★ 這一步前務必確認 console／iDRAC 真的能用

★★★★ 全程要有「CA 掛掉怎麼辦」的答案：
     CA 工作站故障 → 沒人簽得到新憑證 → 8 小時後【全公司進不去】
     → 必須有離線備援金鑰 + console 存取 + CA 私鑰離線備份（見 [[03-備份策略與還原演練]]）
```

| | `authorized_keys` | **SSH CA 憑證** |
| --- | --- | --- |
| 新人上線 | 上 N 台機器加公鑰 | **簽一張憑證** ★★★★ |
| 離職 | 上 N 台刪公鑰（★★★★★ 一定會漏） | **什麼都不用做**（自然過期） |
| 稽核軌跡 | 只有公鑰指紋 | **Key ID + serial + CA 指紋** ★★★★ |
| 到期／撤銷 | 需手動加 `expiry-time=`／逐台刪檔 | **內建強制**／KRL 可集中派送 |
| 最大風險 | 單把私鑰外洩 → 一個人的權限 | **CA 私鑰外洩 → 全機房** ★★★★★ |

---

### 2FA 的取捨（決策與 sshd 端整合）

操作細節（`pam_google_authenticator` 安裝、FIDO2 註冊流程）在 [[07-身分存取管理IAM與MFA]]，
**本節只寫決策與 sshd 怎麼串**。

#### `AuthenticationMethods` 的語意 ★★★★

```text
publickey,keyboard-interactive   逗號 =【且】兩個都要過，而且依序 → 這才是真正的雙因素
publickey keyboard-interactive   空白 =【或】任一組通過即可
                                 → ★★★★★ 這【不是】雙因素，等於「金鑰或密碼」二選一
```

```bash
$ sudo sshd -T | grep -i authenticationmethods
authenticationmethods publickey,keyboard-interactive     # ★★★★ 逗號才對
```

> [!danger] 開 2FA 就等於把 `KbdInteractiveAuthentication` 開回 `yes` ★★★★★
> ```text
> 這時候「基準第 2 項」的防線就只剩 PAM。/etc/pam.d/sshd 若還留著
>     @include common-auth        ← 裡面是 pam_unix.so
> 攻擊者就能用 keyboard-interactive 走到 pam_unix →【又能撞密碼】
>
> ★★★★★ 正確做法：/etc/pam.d/sshd 開頭改成
>     auth required pam_google_authenticator.so nullok=no
>     # @include common-auth      ←【註解掉】
> ★★★★ 改完必須實測（保留另一條連線！）：
>   看到 "Verification code:" → 對；看到 "Password:" → 錯，密碼登入還開著
> ```

#### 自動化帳號的例外 ★★★★

```ini
# ★★★★ 用【群組 + 來源 IP + 綁死指令】三重限制開例外，不要只寫 Match User
Match Group svc-automation Address 10.0.30.0/24
    AuthenticationMethods publickey
    KbdInteractiveAuthentication no
    PermitTTY no
    ForceCommand /usr/local/bin/deploy.sh
    AllowTcpForwarding no
```

```text
★★★★★ 常見錯誤開法：Match User deploy → AuthenticationMethods publickey
   沒限來源、沒綁指令 → 攻擊者拿到 deploy 私鑰就【完全繞過全站 2FA】，還拿得到互動 shell。
★★★★ 正確思路：例外帳號要「失去的比得到的多」——
   免 2FA，但同時失去 pty、失去自由指令、失去來源自由度。
```

#### FIDO2 vs TOTP

| | **FIDO2（`ed25519-sk`）** | **TOTP（`pam_google_authenticator`）** |
| --- | --- | --- |
| 認證方法 | `publickey`（**不必開 keyboard-interactive**）★★★★ | `keyboard-interactive` |
| 防釣魚 | ✓ 綁定伺服器身分 | ✗ OTP 可被轉發 |
| 私鑰外洩風險 | 極低（私鑰在硬體裡出不來）★★★★★ | 種子檔在家目錄，**可被複製** |
| 需要 | OpenSSH ≥ 8.2 兩端 + 實體金鑰 | 只要手機 |
| 建議 | **外網存取、特權帳號**首選 | 內網、預算受限時的過渡方案 |

★★★★ **FIDO2 最大優勢**：走 `publickey` 路徑，所以可以**繼續維持
`KbdInteractiveAuthentication no`** —— 基準第 2 項不必打開，風險小得多。
操作細節見 [[07-身分存取管理IAM與MFA]]。

---

### 稽核與監控 ★★★★

```bash
# 【1】失敗登入 Top 來源
$ sudo journalctl -u ssh --since "7 days ago" --no-pager \
    | grep -oP 'Failed \S+ for (invalid user )?\S+ from \K[0-9a-f.:]+' | sort | uniq -c | sort -rn | head
   1842 203.0.113.9
    771 198.51.100.44
      3 10.0.20.5        # ★★★★ 內網 IP 出現在這 = 自己人打錯或【內網已被入侵】，優先查

# 【2】成功登入：誰、從哪、用哪把金鑰／哪張憑證
$ sudo journalctl -u ssh --since "7 days ago" --no-pager | grep Accepted \
    | awk '{for(i=1;i<=NF;i++){if($i=="for")u=$(i+1);if($i=="from")ip=$(i+1)};print u,ip,$NF}' \
    | sort | uniq -c | sort -rn
     42 ops 10.0.20.5 SHA256:N84r82PdXq72rYLIq+mwcAOqbb4BEmpnjN7u7rkSD5M
      9 deploy 10.0.30.20 SHA256:9Xf0kQ2r...
      1 ops 203.0.113.77 SHA256:aB3d...     # ★★★★★ 陌生來源 + 陌生指紋 = 立刻進事件處理

# 【3】盤點用
$ sudo lastlog -t 90
Username     Port  From          Latest
ops          pts/0 10.0.20.5     Fri Aug 28 09:12:31 +0800 2026
zabbix       pts/2 10.0.20.9     Fri Aug 28 08:00:01 +0800 2026
# last -F（成功／wtmp）、lastb -F（失敗／btmp，需 root）同樣常用 ★★★
```

> [!danger] 只留在本機的日誌，資安事件時等於沒有 ★★★★★
> ```text
> 攻擊者拿到 root 後的第一件事就是清日誌：
>   journalctl --rotate --vacuum-time=1s ; truncate -s0 /var/log/auth.log
>   → 你的所有稽核軌跡【三秒內消失】
> ★★★★★ 必須即時外送到攻擊者拿不到的地方：
>   Wazuh agent → [[01-Wazuh架構與安裝]]、[[05-Wazuh-日誌蒐集與解析]]
>   集中日誌／SIEM → [[09-日誌集中與SIEM]]；保存期限（機關常見 6 個月）→ [[02-日誌集中與輪替]]
> ```

**對照 TWGCB 的 SSH 相關要求**：

| 基準要求（描述） | 對應設定 | 星級 |
| --- | --- | --- |
| 禁止 root 直接遠端登入 | `PermitRootLogin no` | ★★★★ |
| 停用以密碼進行 SSH 認證 | `PasswordAuthentication no` **+** `KbdInteractiveAuthentication no` | ★★★★★ |
| 限制可登入之使用者／群組 | `AllowGroups` | ★★★★ |
| 登入嘗試次數上限／閒置逾時 | `MaxAuthTries`／`ClientAlive*` | ★★★ |
| 顯示登入前警告訊息 | `Banner /etc/issue.net` | ★★★ |
| 記錄層級須達 VERBOSE | `LogLevel VERBOSE` | ★★★★ |
| 禁用弱式加密與 MAC 演算法 | `Ciphers` / `MACs` / `KexAlgorithms` | ★★★★ |

> [!warning] 別直接抄項目編號 ★★★★
> TWGCB **不同 OS 版本有各自的基準文件**（TWGCB-01-014 Ubuntu 22.04、TWGCB-01-012 RHEL 9…），
> **項目編號不通用**。逐條解讀見 [[02-TWGCB-Linux基準文件解讀]]，本機導入見
> [[04-TWGCB-Linux本機導入]]，自動化檢測見 [[07-TWGCB-Linux檢測與符合性報告]] 與
> [[06-Wazuh-SCA安全組態評估]]。

---

### 金鑰治理：殭屍金鑰盤點 ★★★★

```bash
$ sudo find /home /root /var/www /opt -maxdepth 4 -name authorized_keys 2>/dev/null \
  | while read -r f; do
      age=$(( ( $(date +%s) - $(stat -c %Y "$f") ) / 86400 ))
      while read -r line; do
        [ -z "$line" ] && continue; case "$line" in '#'*) continue;; esac
        fp=$(echo "$line" | ssh-keygen -lf - 2>/dev/null | awk '{print $2, $NF}')
        printf '%-45s %5sd  %s\n' "$f" "$age" "$fp"
      done < "$f"
    done
/home/ops/.ssh/authorized_keys                   12d  SHA256:N84r82Pd... (ED25519)
/home/deploy/.ssh/authorized_keys               401d  SHA256:9Xf0kQ2r... (ED25519)  # ★★★★ 401 天沒動
/root/.ssh/authorized_keys                     1873d  SHA256:cW7pR4nZ... (RSA)      # ★★★★★ 五年前的 root 金鑰
```

| 判斷準則 | 星級 | 動作 |
| --- | --- | --- |
| 指紋**不在金鑰清冊**上 | ★★★★★ | **立即移除**並調查來源 |
| `root` 的 `authorized_keys` 非空 | ★★★★★ | 改 `forced-commands-only` 或移除 |
| 檔案 **> 365 天**未變更 | ★★★★ | 逐把確認擁有者是否還在職 |
| 金鑰是 RSA < 3072 bit 或 DSA | ★★★★ | 要求換 ed25519 |
| 服務帳號金鑰沒有 `restrict` / `from=` | ★★★★ | 補上限制 |
| 註解欄是空的（認不出是誰的） | ★★★ | 找不到人就移除 |

> [!tip] CI 部署金鑰的輪替 ★★★★
> 它存在 GitHub/GitLab 的 Secret 裡，任何有 repo 設定權限的人、
> 任何一個被投毒的 CI 步驟都碰得到 —— 是**最容易外洩**的一把。
> 最低要求：`restrict` + `command=` + `from="<CI runner IP>"`，每季輪替（新舊並存 → 切換 → 移除舊的），
> 用可設唯讀的 Deploy Key 而不是個人帳號金鑰。
> ★★★★★ 更好：改用 SSH CA 簽 1 小時短效憑證，CI 每次 build 現簽現用 → [[08-Git-伺服器端與自動部署]]。

---

### 改埠的效益評估 ★★★★

| 面向 | 改埠的影響 | 星級 |
| --- | --- | --- |
| **日誌噪音** | ✓ 失敗登入從每天數千筆掉到個位數，**真實事件不再被淹沒** | ★★★★ |
| 自動化掃描 | ✓ 大部分只掃 22 的殭屍網路會略過 | ★★★ |
| **實際安全性** | ✗ `nmap -p-` 兩分鐘就找到，**針對性攻擊完全不受影響** | ★ |
| **SELinux（RHEL）** | ✗ 忘了 `semanage port -a -t ssh_port_t -p tcp 52222` → **sshd 起不來** | ★★★★ |
| 防火牆／雲端 SG | ✗ 全部要同步改 | ★★★ |
| **監控探針** | ✗ Zabbix/Nagios 的 SSH 檢查、Ansible 的 `ansible_port` | ★★★★ |
| **fail2ban** | ✗ jail 的 `port = ssh` 要改成實際埠號，否則**封不到人** | ★★★★ |
| **Ubuntu socket 啟動** | ✗ 22.10+ 用 `ssh.socket`，只改 `sshd_config` 可能無效 → [[04-sshd-伺服器端設定]] | ★★★★ |
| 文件與交接 | ✗ runbook、新人文件、廠商聯絡單都要改 | ★★ |

> [!danger] 若決定要改：先加不刪、兩埠並存 ★★★★★
> ```bash
> # 【1】sshd_config 同時寫 Port 22 與 Port 52222
> # 【2】RHEL 先開 SELinux port label（★★★★ 少這步 sshd 直接起不來）
> sudo semanage port -a -t ssh_port_t -p tcp 52222
> # 【3】防火牆兩個都放行
> # 【4】★★★★★ 保留舊連線，驗證新埠：ssh -p 52222 ops@web01 'echo NEW PORT OK'
> # 【5】改監控、fail2ban、Ansible inventory、文件
> # 【6】觀察一週確認 22 埠沒有自己人還在連：
> sudo journalctl -u ssh --since "7 days ago" | grep -c 'port 22 '
> # 【7】才把 Port 22 拿掉
> ```

---

### 鎖門預防與回滾 ★★★★★

#### 加固前 checklist 與自動回滾 ★★★★★

```text
□ ★★★★★ console 可用：實體終端／iDRAC／iLO／雲端 VNC【現在就登入試一次】
□ ★★★★★ 保留一條【已經登入的 SSH session】不要關（reload 不會斷既有連線）
□ ★★★★  另開一條備用 session 測試新設定
□ ★★★★  備份 /etc/ssh/sshd_config、sshd_config.d/、authorized_keys
□ ★★★★  確認 AllowGroups 的帳號清單（lastlog -t 90 對照）
□ ★★★★  安排自動回滾 timer
□ ★★★   通知會受影響的人；不要在週五下午做
```

```bash
# ★★★★★ 套用設定「之前」就先掛好定時回滾：驗證成功再手動解除
$ sudo systemd-run --unit=ssh-rollback --on-active=10min /usr/local/sbin/ssh-rollback-exec
Running timer as unit: ssh-rollback.timer
Will run service as unit: ssh-rollback.service

# ★★★★ 驗證成功後記得【解除】，否則 10 分鐘後你的加固會被自己還原
$ sudo systemctl stop ssh-rollback.timer
$ sudo systemctl list-timers 'ssh-rollback*'
0 timers listed.        # ★★★★ 看到這行才算完成
```

#### ★★★★★ 加固後必須從「乾淨環境」重連驗證

```text
你以為在驗證、其實什麼都沒驗到的三種情況：
① ControlMaster 複用：~/.ssh/config 有 ControlPersist，你「重新連線」其實是
   【共用那條加固前就建立的 TCP 連線】→ 加固再爛都連得上
② ssh-agent 裡還載著金鑰：你以為在測憑證，其實是舊金鑰通過的
③ 用同一台跳板機測：跳板機 IP 落在 Match Address 的寬鬆分支 → 你驗的是內網策略
```

```bash
# ★★★★★ 乾淨環境驗證：不吃任何設定檔、不複用連線、不使用 agent
$ ssh -F /dev/null -o ControlPath=none -o ControlMaster=no \
      -o IdentityAgent=none -o IdentitiesOnly=yes \
      -o PreferredAuthentications=publickey -i ~/.ssh/id_ed25519 \
      -o StrictHostKeyChecking=accept-new ops@10.0.20.15 'echo CLEAN LOGIN OK; id'
CLEAN LOGIN OK
uid=1001(ops) gid=1001(ops) groups=1001(ops),1002(ssh-users),27(sudo)
```

★★★★ 最保險：**從另一台還沒連過這台機器的主機**測。

---

## 完整實戰範例

**情境**：`web01.example.gov.tw`（10.0.20.15）是機關對外網站伺服器，目前 SSH 對全網開放、
密碼登入還開著、`root` 的 `authorized_keys` 有一把 2021 年的金鑰。
目標：一次做完加固基準、演算法、來源限制、fail2ban 與 SSH CA，並產出可交稽核的報表。

### 【1】加固設定檔

```ini
# /etc/ssh/sshd_config.d/60-hardening.conf     權限 600，owner root
# ═══ 基準八項 ═══
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no          # ★★★★★ 少這行等於沒關密碼
PermitEmptyPasswords no
AuthenticationMethods publickey
AllowGroups ssh-users
MaxAuthTries 3
LoginGraceTime 30
AllowTcpForwarding no
AllowAgentForwarding no
AllowStreamLocalForwarding no
GatewayPorts no
PermitTunnel no
X11Forwarding no
PermitUserEnvironment no
LogLevel VERBOSE

# ═══ 演算法（★★★★ RHEL 系請改用 crypto-policies）═══
KexAlgorithms sntrup761x25519-sha512@openssh.com,curve25519-sha256,curve25519-sha256@libssh.org
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com
HostKeyAlgorithms ssh-ed25519-cert-v01@openssh.com,ssh-ed25519,rsa-sha2-512,rsa-sha2-256
PubkeyAcceptedAlgorithms ssh-ed25519-cert-v01@openssh.com,ssh-ed25519,rsa-sha2-512,rsa-sha2-256
CASignatureAlgorithms ssh-ed25519,rsa-sha2-512

# ═══ SSH CA ═══
TrustedUserCAKeys /etc/ssh/ca_user_key.pub
AuthorizedPrincipalsFile /etc/ssh/auth_principals/%u
RevokedKeys /etc/ssh/revoked_keys.krl
HostCertificate /etc/ssh/ssh_host_ed25519_key-cert.pub

# ═══ 洪水、逾時與其他 ═══
MaxStartups 10:30:60
PerSourceMaxStartups 3
PerSourcePenaltyExemptList 10.0.20.0/24,10.0.30.0/24
ClientAliveInterval 300
ClientAliveCountMax 3
TCPKeepAlive no
UseDNS no
StrictModes yes
Banner /etc/issue.net
Subsystem sftp internal-sftp

# ═══ Match：外網更嚴、CI 綁死 ★★★★（Match 必須放最後）═══
Match Address *,!10.0.20.0/24,!10.0.30.0/24
    AllowGroups ssh-remote
    MaxAuthTries 2

Match User deploy Address 10.0.30.20/32
    PermitTTY no
    ForceCommand /usr/local/bin/deploy.sh
```

### 【2】防火牆與 fail2ban

```bash
sudo ufw allow from 10.0.20.0/24 to any port 22 proto tcp comment 'SSH mgmt'
sudo ufw allow from 203.0.113.64/28 to any port 22 proto tcp comment 'SSH VPN'
sudo ufw status numbered | grep -n 'Anywhere.*22'   # ★★★★★ 找出全開的規則（含 v6）再刪
```

```ini
# /etc/fail2ban/jail.d/sshd-minimal.local
[sshd]
enabled = true
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
ignoreip = 127.0.0.1/8 ::1 10.0.20.0/24 10.0.30.0/24
```

### 【3】建立 CA 並簽發

```bash
# 在 CA 工作站（不是 web01）
cd /etc/ssh-ca
ssh-keygen -s ca_user_key -I "wangdm-20260828" -n webadmin -V +8h -z 1001 wangdm.pub
scp ssh_host_ed25519_key.pub web01:/tmp/ && \
  ssh-keygen -s ca_host_key -I "web01.example.gov.tw" -h \
    -n web01.example.gov.tw,web01,10.0.20.15 -V +52w /tmp/ssh_host_ed25519_key.pub

# 在 web01
sudo install -m 644 ca_user_key.pub /etc/ssh/ca_user_key.pub
sudo install -m 644 ssh_host_ed25519_key-cert.pub /etc/ssh/
sudo install -d -m 755 /etc/ssh/auth_principals
echo 'webadmin' | sudo tee /etc/ssh/auth_principals/ops
```

### 【4】`/usr/local/bin/ssh-harden` ★★★★★

```bash
#!/usr/bin/env bash
# ssh-harden —— 安全套用 SSH 加固設定，含備份、語法檢查與自動回滾
# 用法：sudo ssh-harden <新設定檔> [回滾等待時間，預設 10min]
set -euo pipefail
IFS=$'\n\t'

SRC="${1:?用法: ssh-harden <新設定檔> [回滾等待]}"
DELAY="${2:-10min}"
TARGET=/etc/ssh/sshd_config.d/60-hardening.conf
BKROOT=/var/backups/ssh-harden
BKDIR="$BKROOT/$(date +%Y%m%d-%H%M%S)"
UNIT=ssh-rollback
SVC=ssh                      # ★★★ RHEL 系請改成 sshd

log()  { printf '\033[1;34m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[FATAL]\033[0m %s\n' "$*" >&2; exit 1; }

# ─── 0. 前置檢查 ────────────────────────────────────────────
[ "$EUID" -eq 0 ] || die "請用 root 執行"
[ -r "$SRC" ]   || die "找不到來源設定檔：$SRC"
command -v sshd >/dev/null || die "找不到 sshd"

sessions=$(who | grep -c 'pts/' || true)
if (( sessions < 2 )); then
    warn "★★★★★ 目前只有 $sessions 條互動 session。"
    warn "請【另開一條 SSH 連線】再執行，否則設定改壞會把自己鎖在外面。"
    read -rp "仍要繼續？(輸入 yes 確認) " ans
    [ "$ans" = "yes" ] || die "已中止"
fi

# ─── 1. 備份 ────────────────────────────────────────────────
log "備份現有設定到 $BKDIR"
install -d -m 700 "$BKDIR/etc/ssh"
cp -a /etc/ssh/sshd_config "$BKDIR/etc/ssh/"
[ -d /etc/ssh/sshd_config.d ] && cp -a /etc/ssh/sshd_config.d "$BKDIR/etc/ssh/"
ln -sfn "$BKDIR" "$BKROOT/latest"
sshd -T > "$BKDIR/sshd-T.before.txt" 2>/dev/null || warn "備份前的 sshd -T 失敗"

# ─── 2. 掛上自動回滾（★★★★★ 必須在套用【之前】掛好）────────
log "掛上 $DELAY 後的自動回滾 timer"
systemctl stop "${UNIT}.timer" 2>/dev/null || true
cat > /usr/local/sbin/ssh-rollback-exec <<'ROLLBACK'
#!/usr/bin/env bash
set -euo pipefail
LATEST=/var/backups/ssh-harden/latest
rm -rf /etc/ssh/sshd_config.d
cp -a "$LATEST/etc/ssh/." /etc/ssh/
if sshd -t; then
    systemctl reload ssh 2>/dev/null || systemctl reload sshd
    logger -p auth.crit -t ssh-harden "AUTO ROLLBACK executed from $LATEST"
else
    logger -p auth.crit -t ssh-harden "AUTO ROLLBACK FAILED: sshd -t rejected the backup"
fi
ROLLBACK
chmod 700 /usr/local/sbin/ssh-rollback-exec
systemd-run --unit="$UNIT" --on-active="$DELAY" /usr/local/sbin/ssh-rollback-exec >/dev/null
log "回滾已武裝。驗證成功請執行：systemctl stop ${UNIT}.timer"

# ─── 3. 套用 + 4. 語法檢查（失敗立刻還原，不等 timer）★★★★★ ─
log "套用新設定到 $TARGET"
install -m 600 -o root -g root "$SRC" "$TARGET"
if ! sshd -t 2>/tmp/sshd-t.err; then
    warn "語法錯誤，立即還原："; cat /tmp/sshd-t.err >&2
    /usr/local/sbin/ssh-rollback-exec
    systemctl stop "${UNIT}.timer" 2>/dev/null || true
    die "設定未套用，已還原成加固前狀態"
fi

# ─── 5. 差異報告 + 6. reload（不用 restart，既有連線不會斷）★★★★ ─
sshd -T > "$BKDIR/sshd-T.after.txt"
log "生效值差異（before → after）："
diff <(sort "$BKDIR/sshd-T.before.txt") <(sort "$BKDIR/sshd-T.after.txt") || true
systemctl reload "$SVC"
systemctl is-active --quiet "$SVC" || die "$SVC 未在執行，請立刻從 console 檢查"

cat <<EOF

★★★★★ 現在【不要關閉這條 session】。請從一台乾淨的機器執行：
  ssh -F /dev/null -o ControlPath=none -o IdentityAgent=none \\
      -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 ops@$(hostname -I | awk '{print $1}') 'echo OK'
確認可以登入後，解除自動回滾：sudo systemctl stop ${UNIT}.timer
若無法登入 → 什麼都不用做，$DELAY 後會自動還原。備份位置：$BKDIR
EOF
```

```bash
$ sudo install -m 750 ssh-harden /usr/local/bin/ && sudo ssh-harden /root/60-hardening.conf 10min
[18:52:03] 備份現有設定到 /var/backups/ssh-harden/20260828-185203
[18:52:03] 掛上 10min 後的自動回滾 timer
[18:52:03] 套用新設定到 /etc/ssh/sshd_config.d/60-hardening.conf
[18:52:03] 生效值差異（before → after）：
< passwordauthentication yes
> passwordauthentication no                    # ★★★★★ 這行就是加固的核心成果
< kbdinteractiveauthentication yes
> kbdinteractiveauthentication no
< loglevel INFO
> loglevel VERBOSE
```

### 【5】`/usr/local/bin/ssh-compliance-check` ★★★★

```bash
#!/usr/bin/env bash
# ssh-compliance-check —— 比對 sshd 生效值與基準、掃殭屍金鑰，輸出可交稽核的 CSV
# 退出碼：0=完全符合  1=有 WARN  2=有 FAIL  3=執行錯誤
set -euo pipefail
IFS=$'\n\t'

BASELINE="${1:-/etc/ssh/hardening-baseline.txt}"
OUT="${2:-/var/log/ssh-compliance-$(date +%Y%m%d).csv}"
trap 'echo "[FATAL] 第 $LINENO 行失敗" >&2; exit 3' ERR

[ "$EUID" -eq 0 ]    || { echo "請用 root 執行" >&2; exit 3; }
[ -r "$BASELINE" ]   || { echo "找不到基準檔 $BASELINE" >&2; exit 3; }

fail=0; warn=0
printf '項目,類別,期望值,實際值,結果,星級\n' > "$OUT"
EFFECTIVE=$(sshd -T)
row() { printf '%s,%s,"%s","%s",%s,%s\n' "$1" "$2" "$3" "$4" "$5" "$6" >> "$OUT"; }

# ─── A. 基準檔逐項比對（格式：<設定項小寫> <期望值> <星級>）─────
while read -r key expect stars; do
    case "${key:-}" in ''|\#*) continue;; esac
    actual=$(echo "$EFFECTIVE" | awk -v k="$key" '$1==k {$1=""; sub(/^ /,""); print; exit}')
    actual="${actual:-<未設定>}"
    if [ "$actual" = "$expect" ]; then
        row "$key" 基準 "$expect" "$actual" PASS "$stars"
    else
        row "$key" 基準 "$expect" "$actual" FAIL "$stars"; fail=$((fail+1))
        echo "[FAIL] $stars $key: 期望 '$expect'，實際 '$actual'" >&2
    fi
done < "$BASELINE"

# ─── B. 殭屍金鑰掃描 ★★★★ ──────────────────────────────────
while read -r f; do
    [ -s "$f" ] || continue
    age=$(( ( $(date +%s) - $(stat -c %Y "$f") ) / 86400 ))
    n=$(grep -cvE '^\s*(#|$)' "$f" || true)
    if (( age > 365 )); then
        row "$f" 金鑰 "<365天內更新" "${age}天/${n}把" FAIL '★★★★'; fail=$((fail+1))
    elif [ "${f#/root/}" != "$f" ]; then
        row "$f" 金鑰 "root應為空" "${n}把" FAIL '★★★★★'; fail=$((fail+1))
    else
        row "$f" 金鑰 "-" "${age}天/${n}把" PASS '★★'
    fi
done < <(find /home /root /var/www /opt -maxdepth 4 -name authorized_keys 2>/dev/null)

# ─── C. 日誌等級與外送 ★★★★ ────────────────────────────────
lvl=$(echo "$EFFECTIVE" | awk '$1=="loglevel"{print $2}')
[ "$lvl" = "VERBOSE" ] \
  && row loglevel 稽核 VERBOSE "$lvl" PASS '★★★★' \
  || { row loglevel 稽核 VERBOSE "$lvl" FAIL '★★★★'; fail=$((fail+1)); }
if systemctl is-active --quiet wazuh-agent 2>/dev/null || systemctl is-active --quiet rsyslog; then
    row 日誌外送 稽核 "已啟用" "OK" PASS '★★★★'
else
    row 日誌外送 稽核 "已啟用" "未偵測到" WARN '★★★★'; warn=$((warn+1))
fi

# ─── D. 摘要 ────────────────────────────────────────────────
echo "報表：$OUT"; column -s, -t < "$OUT" | head -30
echo "FAIL=$fail  WARN=$warn"
(( fail > 0 )) && exit 2
(( warn > 0 )) && exit 1
exit 0
```

基準檔 `/etc/ssh/hardening-baseline.txt`（格式：`<項目> <期望值> <星級>`）：

```text
permitrootlogin no ★★★★
passwordauthentication no ★★★★★
kbdinteractiveauthentication no ★★★★★
permitemptypasswords no ★★★★
maxauthtries 3 ★★★
logingracetime 30 ★★★
permituserenvironment no ★★★
allowtcpforwarding no ★★★
x11forwarding no ★★★
usedns no ★★
```

```bash
$ sudo ssh-compliance-check; echo "exit=$?"
報表：/var/log/ssh-compliance-20260828.csv
項目                              類別  期望值     實際值    結果  星級
permitrootlogin                   基準  no         no        PASS  ★★★★
passwordauthentication            基準  no         no        PASS  ★★★★★
kbdinteractiveauthentication      基準  no         no        PASS  ★★★★★
/root/.ssh/authorized_keys        金鑰  root應為空  1把       FAIL  ★★★★★
loglevel                          稽核  VERBOSE    VERBOSE   PASS  ★★★★
FAIL=1  WARN=0
exit=2                                                # ★★★★ 非 0 可直接接進監控告警
```

排程每日檢查（見 [[02-systemd-timer與cron選型]]）：

```bash
sudo systemd-run --on-calendar='*-*-* 03:20:00' --unit=ssh-compliance \
     --timer-property=Persistent=true /usr/local/bin/ssh-compliance-check
```

### 【6】驗收檢查表 ★★★★★

| # | 檢查項 | 指令 | 預期結果 |
| --- | --- | --- | --- |
| 1 | 設定語法正確 | `sudo sshd -t` | 無輸出 |
| 2 | 密碼登入被拒 ★★★★★ | `ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no ops@web01` | `Permission denied (publickey)` |
| 3 | keyboard-interactive 被拒 ★★★★★ | `ssh -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no ops@web01` | `Permission denied (publickey)`，**不可出現 `Password:`** |
| 4 | root 不能登入 | `ssh root@web01` | `Permission denied (publickey)` |
| 5 | 憑證登入成功 ★★★★ | `ssh -F /dev/null -o IdentityAgent=none -i ~/.ssh/id_ed25519 ops@web01 id` | 印出 `uid=1001(ops)` |
| 6 | **憑證過期後被拒** ★★★★ | 等 `-V` 到期後再連 | `Permission denied`；日誌 `Certificate invalid: expired` |
| 7 | 演算法只剩 AEAD | `nmap -p22 --script ssh2-enum-algos web01` | `encryption_algorithms` 只有 gcm／chacha20 |
| 8 | ssh-audit 政策通過 ★★★★ | `ssh-audit -P "Hardened Ubuntu Server 24.04 LTS (version 1)" web01` | `Result: ✔ Passed` |
| 9 | 外網來源被防火牆擋 | 從外部 `nc -zv web01 22` | timeout |
| 10 | 日誌含公鑰指紋 ★★★★ | `journalctl -u ssh \| grep Accepted \| tail -1` | 含 `SHA256:` 與 `ID ...` |
| 11 | 基準符合性 | `sudo ssh-compliance-check` | `FAIL=0`，exit 0 |
| 12 | 回滾已解除 ★★★★ | `systemctl list-timers 'ssh-rollback*'` | `0 timers listed` |
| 13 | fail2ban 運作 | `sudo fail2ban-client status sshd` | jail 存在、有 banned 統計 |
| 14 | **從乾淨環境重連** ★★★★★ | 另一台沒連過的機器 `ssh ops@web01 'echo OK'` | `OK` |

### 【7】回滾

```bash
# ★★★★ 方法 A：自動回滾 —— 套用後不解除 timer，10 分鐘內自己執行，什麼都不用做
# ★★★★ 方法 B：手動立刻回滾
$ sudo /usr/local/sbin/ssh-rollback-exec && sudo systemctl stop ssh-rollback.timer
# ★★★ 方法 C：從備份還原指定版本
$ sudo rm -rf /etc/ssh/sshd_config.d
$ sudo cp -a /var/backups/ssh-harden/20260828-185203/etc/ssh/. /etc/ssh/
$ sudo sshd -t && sudo systemctl reload ssh
$ sudo sshd -T | grep -i passwordauthentication
passwordauthentication yes        # 已回到加固前
```

> [!danger] 已經被鎖在外面了怎麼辦 ★★★★★
> ① console／iDRAC／iLO／雲端 VNC 進去改 `/etc/ssh/sshd_config.d/`；
> ② 雲端沒有 console → 用救援模式掛載磁碟，或把磁碟掛到另一台機器上改；
> ③ 都沒有 → **只剩重建機器**。這就是為什麼加固前的 checklist 不能跳。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **加固後仍出現 `Password:` 提示** ★★★★★ | 只設了 `PasswordAuthentication no`，`KbdInteractiveAuthentication` 還是 `yes` | 兩個都設 `no`；有 2FA 時改用 PAM 拿掉 `@include common-auth` |
| **設定改完卻沒生效，`sshd -t` 也不報錯** ★★★★ | 被編號更小的 drop-in 蓋掉（RHEL 的 `50-redhat.conf`） | 用 `sshd -T` 驗證；RHEL 改用 crypto-policies 或編號 < 50 |
| **`sshd -t` 說 `Directive 'Ciphers' is not allowed within a Match block`** ★★★ | 演算法設定放進了 `Match` | 演算法只能全域；例外請開第二個 sshd 實例 |
| **自己被鎖在外面** ★★★★★ | 沒保留既有 session、沒掛回滾、`AllowGroups` 漏了自己 | console／iDRAC 進去還原；下次照加固前 checklist 做 |
| `Too many authentication failures` ★★★ | agent 裡金鑰太多，超過 `MaxAuthTries` | 客戶端加 `IdentitiesOnly yes` 與 `IdentityFile` |
| **監控／備份全紅** ★★★★ | `AllowGroups` 漏了服務帳號 | `lastlog -t 90` 盤點後補進群組 |
| `Couldn't agree a key exchange algorithm` ★★★★ | 演算法加固後老客戶端連不上 | 升級客戶端；或開隔離的 `sshd-legacy` 實例（要有落日期限） |
| **備份任務靜默失敗，數天後才發現** ★★★★★ | 老備份軟體用 SHA-1／CBC 被拒，但不會告警 | 加固前做客戶端版本盤點；備份任務要有成功回報監控 |
| **憑證登入失敗 `Certificate invalid: expired`** ★★★ | 憑證過期，或伺服器時間不對 | 重新簽發；`timedatectl` 檢查 NTP |
| 憑證登入失敗，日誌無 `ID` 欄位 ★★★ | 客戶端沒送出憑證（檔名不是 `<key>-cert.pub`） | 憑證放私鑰旁並命名正確，或 `CertificateFile` 明指 |
| **憑證通過但 `key_cert_check_authority: invalid certificate`** ★★★★ | `AuthorizedPrincipalsFile` 沒有對應本機帳號的檔案，或 principals 不交集 | 建 `/etc/ssh/auth_principals/<帳號>` 並填入 principal |
| `PTY allocation request failed on channel 0` ★★★ | 簽憑證時用了 `-O clear` 卻沒補 `-O permit-pty` | 重簽並加 `-O permit-pty` |
| **改埠後 sshd 起不來（RHEL）** ★★★★ | SELinux 沒有該埠的 `ssh_port_t` 標籤 | `semanage port -a -t ssh_port_t -p tcp 52222` |
| **改埠後 fail2ban 封不到人** ★★★★ | jail 的 `port = ssh` 仍指向 22 | jail 內改成實際埠號 |
| **`ssh-audit` 拿 A+ 但被人用外流私鑰登入** ★★★★★ | 只做了傳輸層，認證層與金鑰治理沒做 | 回頭做威脅排序表的第 1、2 項 |
| 日誌被清空，查不到入侵軌跡 ★★★★★ | 日誌只留本機 | 即時外送 Wazuh／SIEM |

### 排查步驟

**【1】設定到底生效了沒**

```bash
$ sudo sshd -T | grep -iE 'passwordauth|kbdinteractive|permitrootlogin|allowgroups|loglevel'
permitrootlogin no
passwordauthentication no
kbdinteractiveauthentication no
allowgroups ssh-users
loglevel VERBOSE
```

看到 `yes` → 設定被更前面的 drop-in 蓋掉或拼錯 → 進【2】。

**【2】是誰蓋掉的**

```bash
$ sudo grep -rn 'PasswordAuthentication\|Ciphers' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ | sort
/etc/ssh/sshd_config:57:#PasswordAuthentication yes
/etc/ssh/sshd_config.d/50-cloud-init.conf:1:PasswordAuthentication yes   # ★★★★ 兇手在這
/etc/ssh/sshd_config.d/60-hardening.conf:3:PasswordAuthentication no
```

**編號小的贏** → 停用 `50-cloud-init.conf`，或把你的檔案改成 `49-`。

**【3】`Match` 區塊有沒有按你想的分流**

```bash
$ sudo sshd -T -C user=ops,host=web01,addr=203.0.113.9 | grep -iE 'allowgroups|maxauthtries'
allowgroups ssh-remote
maxauthtries 2          # ★★★ 與全域不同 → 證明 Match Address 生效
```

輸出與全域相同 → `Match` 條件沒命中（多半是 NAT 後 IP 不是你想的那個）。

**【4】客戶端送了什麼、伺服器為什麼拒絕**

```bash
$ ssh -vvv ops@web01 2>&1 | grep -iE 'Offering|Authentications that can continue|kex: algorithm'
debug1: kex: algorithm: sntrup761x25519-sha512@openssh.com
debug1: Authentications that can continue: publickey        # ★★★★ 只有 publickey = 密碼真的關了
debug1: Offering public key: /home/wangdm/.ssh/id_ed25519 ED25519-CERT SHA256:N84r...
```

出現 `password` 或 `keyboard-interactive` → 回【1】。

**【5】伺服器端為什麼不接受這把金鑰／憑證**（`sudo journalctl -u ssh -f` 後再試登入）

| 日誌訊息 | 問題在哪 |
| --- | --- |
| `bad ownership or modes for directory /home/ops/.ssh` ★★★ | `StrictModes` 擋下權限太寬 → `chmod 700 ~/.ssh; chmod 600 authorized_keys` |
| `not allowed because none of user's groups are listed in AllowGroups` ★★★★ | 帳號不在 `ssh-users` |
| `Certificate invalid: expired` ★★★ | 憑證過期或時鐘不同步（`timedatectl`） |
| `Certificate invalid: name is not a listed principal` ★★★★ | `AuthorizedPrincipalsFile` 與憑證 principals 不交集 |
| `Public key SHA256:... blacklisted` ★★★ | 命中 `RevokedKeys` 的 KRL |
| `Connection closed by authenticating user ... [preauth]` ★★ | 客戶端主動放棄（金鑰試完了） |

**【6】演算法協商失敗**

```bash
$ ssh -vv -o KexAlgorithms=diffie-hellman-group14-sha1 ops@web01 2>&1 | tail -2
Unable to negotiate with 10.0.20.15 port 22: no matching key exchange method found.
Their offer: sntrup761x25519-sha512@openssh.com,curve25519-sha256,curve25519-sha256@libssh.org
```

看到這行代表舊演算法確實被擋掉了 —— 這正是你要的結果。

**【7】確認自己驗到的不是舊連線 ★★★★★**

```bash
$ ssh -O check ops@web01
Control socket connect(/home/wangdm/.ssh/cm-ops@web01:22): No such file or directory
```

若印出 `Master running (pid=xxxx)` → **你的「重新連線」是假的**，先 `ssh -O exit ops@web01`。

**【8】服務狀態與 socket 啟動**

```bash
$ systemctl status ssh --no-pager | head -3; sudo ss -tlnp | grep sshd
     Active: active (running) since Fri 2026-08-28 18:52:04 CST; 3min ago
LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=4210,fd=3))
```

Ubuntu 22.10+ 若看到 `ssh.socket` 在聽而 `ssh.service` inactive，那是 socket 啟動 → [[04-sshd-伺服器端設定]]。

---

## 安全性注意事項

> [!danger] 絕對禁止 ★★★★★
> ```text
> ✗ 把 SSH CA 私鑰放在【任何一台被該 CA 信任的伺服器】上
>     → 打穿任一台 = 拿到萬能鑰匙 = 全機房同時失守，且日誌看起來全部合法
> ✗ 只設 PasswordAuthentication no 就在報告上寫「已停用密碼登入」
>     → 這是【不實陳述】。稽核時請附上 keyboard-interactive 的實測輸出
> ✗ 在沒有 console／iDRAC 的機器上遠端加固，且沒掛自動回滾 → 改壞 = 機器報廢重建
> ✗ 用 restart 而不是 reload 套用設定
>     → restart 會【切斷所有現有連線】，設定改壞時你連補救的機會都沒有
> ✗ Match Address 10.0.0.0/8 → AuthenticationMethods any
>     → 等於宣告「只要進得了內網就免驗證」，橫向移動零阻力
> ✗ 為了讓一台 UPS 能連，把全域 Ciphers 加回 CBC／3DES → 請開隔離實例
> ✗ LogLevel DEBUG 留在正式機 → 可能寫入敏感資訊，且日誌量會塞爆磁碟
> ```

> [!warning] 機關情境特別注意 ★★★★
> - **個資法／資安法**：SSH 日誌屬稽核軌跡，保存期限與存取控制要符合機關規定；
>   日誌本身含帳號與來源 IP，**日誌伺服器的權限也要管**。
> - **最小權限**：`AllowGroups` + `AuthorizedPrincipalsFile` 讓「誰能登入哪台」變成可稽核的清單。
> - **離職程序**：把「撤銷 SSH 憑證／移除公鑰」寫進離職檢查表，
>   並用 `ssh-compliance-check` 的殭屍金鑰掃描做事後驗證。
> - **委外廠商**：一律用**短效憑證 + `force-command` + `source-address`**，
>   合約結束後憑證自然失效，不必依賴人工清理。
> - **變更管理**：備份、`sshd -T` 前後差異、驗收檢查表都要留檔。

---

## 速查表

### 驗證指令 ★★★★

| 指令 | 用途 | 星級 |
| --- | --- | --- |
| `sudo sshd -t` | 語法檢查（**套用前必跑**） | ★★★★★ |
| `sudo sshd -T` | 印出**實際生效**的所有設定 | ★★★★★ |
| `sudo sshd -T -C user=u,host=h,addr=1.2.3.4` | 驗證 `Match` 區塊分流 | ★★★★ |
| `ssh -vvv host` | 看協商與認證的完整過程 | ★★★★ |
| `ssh -Q kex\|cipher\|mac\|key` | 查本機支援哪些演算法 | ★★★ |
| `ssh-audit -P "<政策>" host` | 政策稽核，輸出可交差 | ★★★★ |
| `nmap -p22 --script ssh2-enum-algos host` | 從外部列舉演算法 | ★★★ |
| `ssh-keygen -L -f cert.pub` | 檢視憑證內容 | ★★★★ |
| `ssh-keygen -lf key.pub` | 取得公鑰指紋（比對日誌用） | ★★★★ |
| `ssh -O check host` | 檢查是否有 ControlMaster 複用 | ★★★★★ |

### 鎖門實測指令 ★★★★★

| 要驗證什麼 | 指令 | 通過的表現 |
| --- | --- | --- |
| 密碼登入真的關了 | `ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no u@h` | `Permission denied (publickey)` |
| **keyboard-interactive 也關了** | `ssh -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no u@h` | 不出現 `Password:` |
| 舊演算法被擋 | `ssh -o KexAlgorithms=diffie-hellman-group14-sha1 u@h` | `no matching key exchange method` |
| **乾淨環境登入** | `ssh -F /dev/null -o ControlPath=none -o IdentityAgent=none -i <key> u@h` | 正常登入 |

### 檔案路徑與 CA 旗標

| 路徑／旗標 | 內容 | 星級 |
| --- | --- | --- |
| `/etc/ssh/sshd_config.d/60-hardening.conf` | 加固設定（Ubuntu） | ★★★★ |
| `/etc/ssh/sshd_config.d/50-redhat.conf` | RHEL 的 crypto-policies include（**編號要比它小**） | ★★★★ |
| `/etc/crypto-policies/back-ends/opensshserver.config` | RHEL 實際生效的演算法 | ★★★★ |
| `/etc/ssh/ca_user_key.pub` | 被信任的使用者 CA 公鑰 | ★★★★★ |
| `/etc/ssh/auth_principals/<帳號>` | 該帳號接受哪些 principal | ★★★★ |
| `/etc/ssh/revoked_keys.krl` | 撤銷清單 | ★★★ |
| `ssh-keygen -s / -I / -n / -V / -h / -z` | 簽發：CA 私鑰／Key ID／principals／有效期／主機憑證／序號 | ★★★★★ |
| `-O clear` / `-O force-command=` / `-O source-address=` | 清除 extensions（★★★★ 記得補 `permit-pty`）／綁死指令／綁死來源 | ★★★★ |

---

## 練習題

> [!question]- 練習 1：找出「假加固」的機器
> 某台伺服器 `sshd_config` 裡寫著 `PasswordAuthentication no`，但資安掃描說它仍接受密碼登入。
> 寫出三個指令，依序證明「問題在哪」並「修好它」。
>
> **參考解答**
>
> ```bash
> # 【1】看實際生效值 —— 不要看設定檔
> $ sudo sshd -T | grep -iE 'passwordauth|kbdinteractive'
> passwordauthentication no
> kbdinteractiveauthentication yes      # ★★★★★ 兇手
>
> # 【2】實測確認（★★★★ 沒有這步就是紙上作業）
> $ ssh -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no ops@web01
> (ops@web01) Password:                 # 密碼登入確實還開著
>
> # 【3】修正並驗證
> $ echo 'KbdInteractiveAuthentication no' | sudo tee -a /etc/ssh/sshd_config.d/60-hardening.conf
> $ sudo sshd -t && sudo systemctl reload ssh
> $ ssh -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no ops@web01
> Permission denied (publickey).        # ★★★★★ 這才是通過
> ```
>
> **補充**：若這台是 RHEL，還要確認你的 drop-in 編號小於 `50-redhat.conf`。

> [!question]- 練習 2：為委外廠商簽一張安全的短效憑證
> 廠商工程師今天下午要修 `webadmin` 的東西，只能從跳板機 10.0.30.5 連進來，
> 只能操作 web01，只能維護 4 小時。寫出簽發指令與伺服器端設定。
>
> **參考解答**
>
> ```bash
> # ═══ CA 工作站 ═══
> ssh-keygen -s /etc/ssh-ca/ca_user_key \
>   -I "vendor-chen-20260828-ticket12345" \   # ★★★★ Key ID 帶工單號，日誌可追
>   -n vendor-web01 \                          # ★★★★ 專屬 principal，不要給 webadmin
>   -V +4h -z 2026082801 \                     # ★★★★ 只有 4 小時
>   -O source-address=10.0.30.5/32 \           # ★★★★ 綁死來源
>   -O no-agent-forwarding -O no-port-forwarding /tmp/vendor_chen.pub
> # ═══ web01 ═══
> echo 'vendor-web01' | sudo tee -a /etc/ssh/auth_principals/webadmin
> ```
>
> **為什麼這樣設計**：`-V +4h` ★★★★★ 合約時間結束後**不需要任何人記得去撤銷**；
> 專屬 principal ★★★★ 之後只要刪 `auth_principals` 那一行就能一次收回所有廠商憑證；
> `source-address` ★★★★ 憑證外流也只能從跳板機用；
> Key ID 帶工單號 ★★★★ 稽核時能把每次登入對應到一張工單。

> [!question]- 練習 3：規劃一次不會把自己鎖在外面的加固
> 你要對一台**雲端**（沒有實體 console，但有 VNC）的機器做演算法加固。
> 列出完整步驟並說明每一步在防範什麼。
>
> **參考解答**
>
> ```text
> 【1】確認 VNC 現在就能登入        → 防：改壞了完全沒有後路 ★★★★★
> 【2】保留一條已登入的 SSH session  → 防：reload 後新連線失敗時還能改回來 ★★★★★
> 【3】盤點客戶端版本（journalctl 抓 remote software version 一週）
>                                    → 防：老客戶端／備份軟體靜默失敗 ★★★★
> 【4】備份 /etc/ssh/ 全部          → 防：不知道原本長什麼樣
> 【5】掛 10 分鐘自動回滾 timer      → 防：驗證失敗時的最後保險 ★★★★★
> 【6】套用 → sshd -t → reload      → 用 reload 不用 restart ★★★★
> 【7】從【另一台沒連過的機器】測登入  → 防：驗到的是舊連線／複用 socket ★★★★★
>      ssh -F /dev/null -o ControlPath=none -o IdentityAgent=none ops@host
> 【8】ssh-audit + nmap 驗算法      → 產出稽核證據
> 【9】驗證成功 → systemctl stop ssh-rollback.timer  → ★★★★ 忘了做，10 分鐘後加固自己消失
> 【10】更新文件、通知使用者、記錄變更 → 防：交接時沒人知道做過什麼
> ```
>
> **最容易漏的兩步**：【7】乾淨環境（多數人用原本那條 session 測，等於沒測）
> 與【9】解除回滾（加固莫名其妙失效，查半天）。

---

## 小測驗

Q1. `PasswordAuthentication no` 已經設了，為什麼還可能被密碼登入？要怎麼實測確認？

Q2. `AuthenticationMethods publickey keyboard-interactive`（中間是空白）與
`publickey,keyboard-interactive`（中間是逗號）差在哪？哪一個才是雙因素？

Q3. 你在 RHEL 9 的 `/etc/ssh/sshd_config.d/60-hardening.conf` 寫了 `Ciphers`，
`sshd -t` 沒報錯，但 `nmap` 掃出來還是有 CBC。為什麼？

Q4. 為什麼「演算法例外」不能用 `Match Address` 做？正確做法是什麼？

Q5. 這行指令會發生什麼：
`ssh-keygen -s ca_user_key -I "ops" -n ops -V +8h -O clear id_ed25519.pub`

Q6. SSH CA 相對 `authorized_keys` 的最大維運價值是什麼？最大風險又是什麼？

Q7. 是非題：把 SSH 從 22 改到 52222 之後，可以在稽核報告上寫「已提升 SSH 安全性」。

Q8. 你加固完，用原本那條 SSH 視窗開新分頁連進去，一切正常。
為什麼這個驗證可能是假的？要怎麼做才算數？

Q9. `MaxStartups 10:30:60` 這三個數字分別代表什麼？調小之後可能誤傷誰？

Q10. 資安事件發生，你要查「昨天 14:00 從 10.0.20.5 登入 ops 的是誰」。
`LogLevel INFO` 與 `LogLevel VERBOSE` 分別能給你什麼？

> [!question]- 測驗答案
> **Q1.** 因為 SSH 有**兩條**會問密碼的路：`password` 方法（由 `PasswordAuthentication` 管）
> 與 `keyboard-interactive` 方法（由 `KbdInteractiveAuthentication` 管，背後接 PAM）。
> PAM 的 `/etc/pam.d/sshd` 通常 `@include common-auth` → `pam_unix.so`，
> **它驗的是同一組 `/etc/shadow` 密碼**。所以只關前者，攻擊者用
> `-o PreferredAuthentications=keyboard-interactive` 一樣能撞密碼。
> ★★★★★ 這是加固後**最常見的假安全**，而且你的稽核報表會誤報為「已停用」。
> 實測：
> ```bash
> ssh -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no ops@web01
> ```
> 出現 `Password:` → 沒關成功；出現 `Permission denied (publickey).` → 才算過。
> 修法是同時設 `KbdInteractiveAuthentication no`（OpenSSH 8.7 以前叫
> `ChallengeResponseAuthentication`，抄舊文章會抄錯）。見〈基準第 2 項〉。
>
> **Q2.** **逗號 = AND，空白 = OR**。
> - `publickey,keyboard-interactive`：**兩個都要依序通過** → 這才是雙因素 ★★★★
> - `publickey keyboard-interactive`：**任一組通過即可** → 等於「金鑰**或**密碼」，
>   ★★★★★ 完全不是雙因素，反而**放寬**了限制（多開了一條 OTP／密碼路徑）
>
> 驗證：`sudo sshd -T | grep -i authenticationmethods`，看清楚是逗號還是空白。
> ★★★★ 另外注意：開 2FA 就必須把 `KbdInteractiveAuthentication` 開回 `yes`，
> 這時要靠 PAM（拿掉 `@include common-auth`）才不會把密碼登入一起開回來。
> 見〈2FA 的取捨〉。
>
> **Q3.** 因為 **RHEL 的 crypto-policies 先被讀到**。
> `sshd_config` 的規則是「**先讀到的值贏**」，而 RHEL 9 出廠就有
> `/etc/ssh/sshd_config.d/50-redhat.conf`，裡面 `Include
> /etc/crypto-policies/back-ends/opensshserver.config`。
> `50-` 排在 `60-` 前面 → 系統政策的 `Ciphers` 先定案 → **你寫的完全不生效**，
> 而且 `sshd -t` 不會報任何錯，你會以為成功了。★★★★
> 兩種修法：
> ```bash
> # A（建議）：改系統政策／加子政策，全系統一致，OpenSCAP 也認
> sudo update-crypto-policies --set DEFAULT:NO-SHA1 && sudo systemctl reload sshd
> # B：把檔名改成編號小於 50
> sudo mv /etc/ssh/sshd_config.d/{60-hardening.conf,40-hardening.conf}
> ```
> 驗證一律用 `sudo sshd -T | grep -i ciphers`。見 RHEL 對照 callout。
>
> **Q4.** 因為 `Ciphers` / `MACs` / `KexAlgorithms` / `HostKey` 屬於**協商階段**的設定，
> 發生在 sshd **還不知道對方是誰、也還沒完成連線比對**之前；
> `Match` 只影響**認證與 session 階段**的設定。
> 硬寫進去 `sshd -t` 會直接報 `Directive 'Ciphers' is not allowed within a Match block`。★★★
> **正確做法：開第二個 sshd 實例**（`sshd -f /etc/ssh/sshd_config_legacy`），
> 綁在**內網 IP + 另一個埠**，防火牆只放行那台老設備，
> 並加上 `AllowUsers` + `ForceCommand` 把它限制到只能做一件事。★★★★
> ★★★★ 例外一定要寫**落日期限**進工單，否則會變成永久的後門。見〈相容性評估〉。
>
> **Q5.** 會簽出一張 8 小時、principal 為 `ops` 的使用者憑證，
> 但因為 `-O clear` **清掉了所有 extensions**（包含 `permit-pty`），
> 使用者拿它登入時會看到：
> ```text
> PTY allocation request failed on channel 0
> ```
> ★★★★ 也就是「認證成功但沒有終端機」—— 可以執行單一指令，但沒有互動 shell。
> 自動化帳號**本來就不該有 pty**，所以這樣簽是對的；
> 但**人要用的憑證必須補 `-O permit-pty`**。
> 順帶一提，`-O clear` 也清掉了 `permit-port-forwarding` 與 `permit-agent-forwarding`，
> 這對自動化帳號同樣是好事。見〈簽發短效使用者憑證〉。
>
> **Q6.** **最大價值：離職／換機時什麼都不用做。**
> `authorized_keys` 模式下，離職要上 N 台機器逐一刪公鑰，
> ★★★★★ **只要漏一台，那把私鑰就永遠能登入那台**，而且日誌看起來完全正常。
> 憑證模式下，人離職後就簽不到新憑證，手上那張 8 小時後自動失效。
> 附帶價值：日誌同時記錄 **Key ID + serial + CA 指紋**，稽核追人容易得多。
> **最大風險：CA 私鑰是全機房萬能鑰匙。** ★★★★★
> 拿到它的人可以簽出任意 principal 的憑證、同時登入所有伺服器，
> 而且**每一次登入在日誌上都是合法的憑證登入**。
> 所以 CA 私鑰必須離線／HSM／限用工作站、要有 passphrase、簽發要留紀錄，
> 且**絕不放在任何被該 CA 信任的伺服器上**。見〈SSH 憑證式認證〉。
>
> **Q7.** **否。** ★★★★
> 改埠的真實效益只有一個：**降低日誌噪音**（失敗登入從每天數千筆掉到個位數，
> 讓真正的異常不再被淹沒），以及避開只掃 22 的殭屍網路。
> 但 `nmap -p-` 兩分鐘就能找出實際埠號，**針對性攻擊完全不受影響**。
> 而且改埠有實際成本：RHEL 要 `semanage port -a -t ssh_port_t -p tcp <埠>`
> （漏了 sshd 直接起不來 ★★★★）、防火牆、監控探針、fail2ban 的 `port =`、
> Ansible inventory、所有文件與交接資料都要同步改。
> 稽核報告上正確的寫法是「**降低掃描噪音**」。
> 真正該寫進「提升安全性」的是：關密碼登入、限制來源、SSH 不上公網。
>
> **Q8.** 因為你很可能驗到的是**加固前就已經建立的連線**：
> ① `~/.ssh/config` 若有 `ControlMaster` / `ControlPersist`，
> 新分頁其實是**複用同一條 TCP 連線**，加固再爛都會通；
> ② `ssh-agent` 裡還載著舊金鑰，你以為在測憑證其實是舊金鑰過的；
> ③ 從同一台跳板機測，落在 `Match Address` 的寬鬆分支裡，驗的是內網策略。★★★★★
> 正確做法：
> ```bash
> ssh -O check ops@web01          # 印出 Master running → 先 ssh -O exit
> ssh -F /dev/null -o ControlPath=none -o ControlMaster=no \
>     -o IdentityAgent=none -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 ops@web01 'echo OK'
> ```
> 最保險是**從另一台沒連過這台機器的主機**測。見〈鎖門預防與回滾〉。
>
> **Q9.** `start:rate:full` 三段值，管的是**未完成認證的並行連線數**：
> - `10`：低於 10 條時全部接受
> - `30`：超過 10 之後，以 **30%** 起跳的機率隨機拒絕新連線（往上線性內插）
> - `60`：達到 60 條時 **100% 拒絕**
>
> 預設是 `10:30:100`。調小能更早丟棄連線洪水（含 pre-auth 資源耗盡型攻擊）。★★★
> **誤傷對象**：自己的自動化 —— Ansible `forks=50`、CI 大量並行部署、
> 監控系統同時對多台下 SSH 檢查，都會在同一瞬間開出大量未認證連線，
> 症狀是 `kex_exchange_identification: Connection closed by remote host` 隨機失敗。
> 日誌關鍵字：`error: beginning MaxStartups throttling`。
> 搭配 `PerSourceMaxStartups` 與 `PerSourcePenaltyExemptList` 可以只擋外部、放行內網。
>
> **Q10.** - `LogLevel INFO`：成功登入那一行**已經含所用公鑰的 SHA256 指紋**
> （`Accepted publickey for ops from 10.0.20.5 port 51234 ssh2: ED25519 SHA256:...`），
> 所以「成功登入用了哪把金鑰」查得到；但**失敗或被提供過卻沒用上的金鑰查不到**。
> - `LogLevel VERBOSE` ★★★★：額外記錄**每一把被提供過的公鑰指紋**與失敗原因
> （`Failed publickey for ... SHA256:...`），這才能回答
> 「有沒有人拿著離職同事那把金鑰在試」這種問題，也是 CIS／TWGCB 要求的等級。
>
> 拿到指紋後 `ssh-keygen -lf` 比對金鑰清冊即可對到人；用 SSH CA 時更直接 ——
> 日誌裡有 `ID wangdm-20260828 (serial 1001)`。★★★★
> ★★★★★ 但這一切的前提是**日誌還在**：攻擊者拿到 root 後三秒就能清空本機日誌，
> 所以必須即時外送到 Wazuh／SIEM。見〈稽核與監控〉。

---

## 延伸閱讀

- [[04-sshd-伺服器端設定]] —— 本篇每個設定項的基礎意義、`Include` 順序與 `ssh.socket` 陷阱
- [[02-SSH-金鑰認證與ssh-agent]] —— `authorized_keys` 選項與金鑰產生，SSH CA 的前一站
- [[05-Fail2ban入侵防護]] —— 本篇只給最小 jail，遞增封鎖、filter 與誤封解除看這篇
- [[06-遠端存取安全]] —— 「把 SSH 從公網下架」的架構選型（VPN／跳板機／零信任）
- [[07-身分存取管理IAM與MFA]] —— TOTP 與 FIDO2 的逐步操作，本篇只寫決策
- [[08-系統強化與稽核]] —— SSH 之外的系統層加固與稽核工具
- [[04-TWGCB-Linux本機導入]]、[[07-TWGCB-Linux檢測與符合性報告]] —— 把本篇成果對應到政府組態基準
- [[09-日誌集中與SIEM]]、[[05-Wazuh-日誌蒐集與解析]] —— 讓 SSH 日誌在被清掉之前就送出去
- OpenSSH `sshd_config(5)` 官方手冊：<https://man.openbsd.org/sshd_config>
- OpenSSH 憑證式認證（`ssh-keygen(1)` CERTIFICATES 章節）：<https://man.openbsd.org/ssh-keygen#CERTIFICATES>
- ssh-audit 官方加固指引：<https://www.ssh-audit.com/hardening_guides.html>
- Red Hat 系統層密碼學政策：<https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/security_hardening/using-the-system-wide-cryptographic-policies_security-hardening>
