---
title: "SSH 原理與第一次連線"
desc: "連線六階段、host key 指紋的帶外驗證、known_hosts 實務與 REMOTE HOST IDENTIFICATION HAS CHANGED 的分流處置"
aliases: [ssh, known_hosts, host key, 主機指紋, TOFU, ssh-keyscan, 第一次連線]
tags: [群組/Linux, 服務/ssh, 主題/遠端, 主題/信任模型]
category: SSH與遠端管理
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[16-網路基礎指令]]", "[[09-網概-TCP與UDP]]"]
updated: 2026-08-28
---

# SSH 原理與第一次連線

> [!abstract] 這篇你會學到
> - 把 SSH 連線拆成**六個階段**，看到錯誤訊息就知道**卡在第幾階段**，不用亂猜 ★★★★
> - **★★★★★ 用帶外管道取得主機指紋並逐字比對** —— 這是第一次連線唯一有意義的動作
> - 看到 `REMOTE HOST IDENTIFICATION HAS CHANGED` 時**先分流再處置**，不要反射性 `ssh-keygen -R` ★★★★★
> - 讀懂 `ssh -v` 的每一段 debug 行，**自己定位問題**而不是把設定檔亂改一輪 ★★★★
> - 處理 **OpenSSH 8.8+ 連老設備**的 `no matching host key type`，知道臨時旗標與它的風險 ★★★★
> - 用 `known_hosts` / `ssh_known_hosts` 建立一套**全機關可稽核**的主機信任登記流程
> - 每次動 SSH 設定前先**準備好第二條路**（console、第二個連線、第二個帳號），不把自己鎖在門外 ★★★★

## 前置知識

- [[16-網路基礎指令]] —— `ip`、`ss`、`ping`、`nc` 的基本用法，本篇直接引用不重講
- [[09-網概-TCP與UDP]] —— 三向交握與連線狀態，第 ① 階段的失敗都是 TCP 層的事
- [[10-網概-連接埠與應用層協定]] —— 為什麼 SSH 是 22/tcp，以及改埠的意義
- [[03-ss-netstat-與lsof]] —— 確認 sshd 有沒有在聽，本篇的前置檢查會用到
- [[17-systemd服務管理]] —— `systemctl status ssh`、socket activation 的概念

> [!tip] 這篇的定位
> 本篇**不是**教「怎麼打 `ssh` 指令」。打指令三分鐘就會了。
> 本篇教的是維運人員在**第一次連線那一刻**必須做的**信任決策**：
> 這台機器真的是我要連的那台嗎？我憑什麼相信？
> 這個決策做錯，後面所有的金鑰、加固、稽核**全部建立在錯的地基上**。★★★★

---

## 觀念說明

### ★★★★ SSH 連線的六個階段

排錯的第一件事永遠是**定位階段**。把下面這張圖背起來，看到任何 SSH 錯誤訊息，
第一個動作是問「這是第幾階段的訊息」：

```text
★★★★ SSH 連線六階段（每一階段有專屬的失敗訊息）

  客戶端 ssh                                      伺服器 sshd (22/tcp)
  ──────────                                      ────────────────────

  ①  TCP 三向交握（SYN → SYN-ACK → ACK）
      ────────────────────────────────────────────▶
      ★★★ 失敗訊息：
        · Connection refused          → 埠沒人聽（sshd 沒跑 / 埠不對）
        · Connection timed out        → 防火牆 DROP / 路由不通 / 機器沒開
        · No route to host            → 路由或 ARP 層面就不通

  ②  協定版本字串交換（明文，尚未加密）
      SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13
      ◀──────────────────────────────────────────▶
      ★★★ 失敗訊息：
        · kex_exchange_identification: read: Connection reset by peer
                                      → 被 fail2ban / TCP wrapper / IPS 中途踢掉
        · Bad protocol version identification
                                      → 這個埠上根本不是 SSH（連錯服務）

  ③  KEX 金鑰交換 + 演算法協商
      協商：KEX 演算法、host key 型別、對稱加密、MAC、壓縮
      ★★★★ 失敗訊息：
        · Unable to negotiate ... no matching host key type found.
              Their offer: ssh-rsa   → OpenSSH 8.8+ 對老設備的經典症頭
        · no matching key exchange method found
        · no matching cipher found / no matching MAC found

  ④  主機認證（伺服器用 host key 私鑰簽章，客戶端拿 known_hosts 驗）
      ★★★★★ 失敗訊息：
        · The authenticity of host ... can't be established.  ← 第一次連線（不是錯誤）
        · WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!    ← ★★★★★ 停手
        · Host key verification failed.

  ⑤  使用者認證（依序嘗試 publickey → keyboard-interactive → password）
      ★★★★ 失敗訊息：
        · Permission denied (publickey).
        · Permission denied (publickey,password).
        · Too many authentication failures

  ⑥  開 channel（互動 shell / exec 單一指令 / sftp subsystem / 埠轉發）
      ★★ 失敗訊息：
        · shell request failed on channel 0
        · subsystem request failed on channel 0   （sftp 沒開）
        · administratively prohibited: open failed（埠轉發被 sshd 禁止）
```

> [!note] ③ 和 ④ 在協定上其實是同一回合 ★★
> 嚴格說，伺服器是在 KEX 過程中用 host key 私鑰對「exchange hash」簽章，
> 主機認證是 KEX 的一部分，不是獨立的往返。
> 但**排錯時把它們分開看非常有用**：
> `no matching host key type` 是「連要用哪種 host key 都談不攏」（③），
> `Host key verification failed` 是「談攏了、簽章也對，但你的 known_hosts 不同意」（④）。
> 這兩個訊息的處置方式完全不同，混在一起就會亂改設定。

### ★★★★ 錯誤訊息 → 階段 → 第一動作

| 錯誤訊息 | 階段 | 真正的意思 | 第一個該下的指令 |
| --- | --- | --- | --- |
| `Connection refused` | ★★★ ① | 封包**有到**機器，那個埠**沒有程序在聽** | 主機上 `ss -ltnp \| grep :22` |
| `Connection timed out` | ★★★ ① | 封包**根本沒回來**，中間有東西靜默丟包 | `nc -zv host 22`、查防火牆與路由 |
| `no matching host key type` | ★★★★ ③ | 雙方**沒有共同支援的演算法** | `ssh -V`、`ssh -G host \| grep hostkey` |
| `Host key verification failed` | ★★★★★ ④ | 對方身分**和你記錄的不符** | **先停手**，用帶外管道取指紋 |
| `Permission denied (publickey)` | ★★★★ ⑤ | 網路、加密、主機身分**全部正常** | 伺服器 `journalctl -u ssh`（見 [[02-SSH-金鑰認證與ssh-agent]]） |

> [!warning] 這張表的價值在「排除」★★★
> 看到 `Permission denied (publickey)` 卻跑去查防火牆，是浪費半小時的典型。
> **能看到 `Permission denied` 就代表 ①～④ 全部成功了** ——
> TCP 通、版本相容、演算法談攏、主機身分驗證通過。問題**只**在使用者認證。

### 主機金鑰 host key：跟使用者金鑰完全是兩回事

初學者最大的混淆是把 host key 和使用者金鑰搞在一起。它們**方向相反**：

```text
★★★★ 兩種金鑰，兩個方向，不要搞混

  【host key 主機金鑰】  伺服器 → 證明給客戶端看「我是誰」
    私鑰：/etc/ssh/ssh_host_ed25519_key        （★★★★★ root 才能讀，600）
    公鑰：/etc/ssh/ssh_host_ed25519_key.pub    （★ 可公開）
    客戶端記錄在：~/.ssh/known_hosts
    ★★ 由 openssh-server 安裝時自動產生，你通常不會手動建
    ★★★★ 重灌系統 / 重建 VM / 從範本 clone → 這組會換掉

  【使用者金鑰】          客戶端 → 證明給伺服器看「我是誰」
    私鑰：~/.ssh/id_ed25519                    （★★★★★ 600，不可外流）
    公鑰：~/.ssh/id_ed25519.pub
    伺服器記錄在：~/.ssh/authorized_keys
    → 這部分完整寫在 [[02-SSH-金鑰認證與ssh-agent]]，本篇不重複
```

Ubuntu 24.04 安裝 `openssh-server` 後，`/etc/ssh/` 底下通常有這幾組：

| 檔案 | 演算法 | 現況 | 重要度 |
| --- | --- | --- | --- |
| `ssh_host_ed25519_key` | Ed25519 | ★★★★ **現代預設，客戶端優先選這個**，指紋最該登記的就是它 | ★★★★ |
| `ssh_host_rsa_key` | RSA 3072 | ★★★ 保留給老客戶端相容（用 rsa-sha2-256/512 簽章） | ★★★ |
| `ssh_host_ecdsa_key` | ECDSA nistp256 | ★★ 相容用，有些機關的資安基準要求停用 NIST 曲線 | ★★ |
| `ssh_host_dsa_key` | DSA | ★ **歷史遺留**，OpenSSH 9.8 起編譯預設關閉、10.0 完全移除，新系統不會有 | ★ |

```bash
sudo ls -l /etc/ssh/ssh_host_*
```

預期輸出：

```text
-rw------- 1 root root  505 Aug 12 09:41 /etc/ssh/ssh_host_ecdsa_key       # ★★★★★ 600 root
-rw-r--r-- 1 root root  176 Aug 12 09:41 /etc/ssh/ssh_host_ecdsa_key.pub   # ★ 644 公鑰
-rw------- 1 root root  411 Aug 12 09:41 /etc/ssh/ssh_host_ed25519_key
-rw-r--r-- 1 root root   96 Aug 12 09:41 /etc/ssh/ssh_host_ed25519_key.pub
-rw------- 1 root root 2590 Aug 12 09:41 /etc/ssh/ssh_host_rsa_key
-rw-r--r-- 1 root root  568 Aug 12 09:41 /etc/ssh/ssh_host_rsa_key.pub
```

> [!danger] host key 私鑰外洩 = 全機關的 SSH 信任崩塌 ★★★★★
> 拿到 `ssh_host_ed25519_key` 的人可以**完美冒充這台伺服器**，
> 而且所有客戶端的 `known_hosts` **不會發出任何警告**（指紋一模一樣）。
> 三個實務上真的會出事的情境：
> - **★★★★★ 從 VM 範本 clone 出十台機器沒重新產生 host key** ——
>   十台機器共用同一把私鑰，攻破任何一台就能冒充其餘九台
> - **★★★★ 備份整台 `/etc` 到沒加密的網芳或 git repo** —— 私鑰跟著出去
> - **★★★★ 交機前用同一份磁碟映像檔大量佈署** —— 同上
>
> clone 之後一定要重新產生：
> ```bash
> sudo rm -f /etc/ssh/ssh_host_*
> sudo ssh-keygen -A                      # ★★★★ 依系統設定重建所有型別
> sudo systemctl restart ssh
> ```
> 做完之後**所有客戶端都會跳 HOST KEY CHANGED**，這是預期行為，
> 但你必須事先通知並記錄新指紋，否則就是自己製造狼來了。

### ★★★★ TOFU：SSH 信任模型的先天弱點

SSH 沒有 CA、沒有憑證鏈（除非另外建 SSH CA），它用的是 **TOFU（Trust On First Use，首次使用即信任）**：

```text
★★★★ TOFU 的邏輯與它的破口

  第一次連線
    ┌─────────────────────────────────────────────┐
    │ ssh 問你：「這把 key 我沒看過，你要信嗎？」   │
    │  → 你打了 yes                                │
    │  → 寫進 ~/.ssh/known_hosts                   │
    └─────────────────────────────────────────────┘
              ▲
              │  ★★★★★ 整個模型的安全性【全部押在這一刻】
              │  你如果隨手打 yes，等於沒有任何驗證
              │
  第二次以後
    ┌─────────────────────────────────────────────┐
    │ ssh 自己比對 known_hosts，一致就靜靜連進去    │
    │ 不一致 → 大聲警告並【拒絕連線】               │
    └─────────────────────────────────────────────┘

  ★★★★★ 所以 SSH 能防的是「第一次之後的中間人」，
         防不了「第一次就被中間人接手」。
         第一次連線如果就在被劫持的網路上，
         你信的是攻擊者的 key，之後每次連線都不會有任何警告。
```

對照 HTTPS 的信任模型（見 [[01-PKI與憑證基礎]]）：

| | HTTPS | SSH |
| --- | --- | --- |
| 信任根 | ★★ 作業系統／瀏覽器內建 CA 清單 | ★★★★ **你自己的 `known_hosts`** |
| 第一次連線 | ★★ CA 已經幫你背書 | ★★★★★ **你必須自己驗證** |
| 主機換憑證／換金鑰 | ★ 只要 CA 簽了就無感 | ★★★★ 大聲警告並拒絕 |
| 被中間人時 | ★★★ 憑證不受信任 → 瀏覽器警告 | ★★★★ 指紋不符 → 警告 |

> [!tip] 機關環境的正解：把「取得指紋」寫進交機流程 ★★★★
> TOFU 的破口不是技術問題，是**流程問題**。
> 解法是：**主機指紋在交機時就從帶外管道抄下來、寫進交機表、跟資產編號一起管理**。
> 第一次連線時比對交機表，不是憑感覺按 yes。本篇的完整實戰範例就是在做這件事。

---

## 基礎操作

### ★★★ 步驟零：確認自己手上的 OpenSSH 版本

版本決定**預設支援哪些演算法**，也決定你會不會踩到 8.8 的 SHA-1 斷崖。
到新環境的第一個動作：

```bash
ssh -V
```

```text
OpenSSH_9.6p1 Ubuntu-3ubuntu13.5, OpenSSL 3.0.13 30 Jan 2024   # ★★★ 走 stderr，要存檔得 2>&1
```

| 系統 | OpenSSH | 影響 | 重要度 |
| --- | --- | --- | --- |
| Ubuntu 24.04 LTS | 9.6p1 | ★★★★ 已停用 ssh-rsa(SHA-1)，連老設備會失敗 | ★★★★ |
| Ubuntu 22.04 LTS | 8.9p1 | ★★★★ 同上（8.8 起就停用了） | ★★★★ |
| Ubuntu 20.04 LTS | 8.2p1 | ★★ 還接受 ssh-rsa，連老設備沒事 | ★★ |
| RHEL / Rocky 9 | 8.7p1 | ★★★ 未停用 ssh-rsa，但受 crypto-policies 影響更大 | ★★★ |
| RHEL / Rocky 8 | 8.0p1 | ★★ 老演算法多半還能用 | ★★ |
| 老交換器／NAS／IPMI | 5.x～7.x | ★★★★ 只會 ssh-rsa，甚至只會 dh-group1-sha1 | ★★★★ |

查這版**編譯有支援**哪些演算法：

```bash
ssh -Q key | head -n 5
```

```text
ssh-ed25519
ssh-ed25519-cert-v01@openssh.com
sk-ssh-ed25519@openssh.com
ecdsa-sha2-nistp256
ssh-rsa                       # ★★★ 有列出 ≠ 預設啟用（8.8+ 預設不用它簽章）
```

> [!warning] `ssh -Q` 是「編譯有支援」，`ssh -G` 才是「這次連線實際會用」★★★
> ```bash
> ssh -G srv-web01 | grep -iE '^(hostkeyalgorithms|pubkeyacceptedalgorithms|kexalgorithms)'
> ```
> `-G` 印的是所有設定檔套用完之後的**最終有效值**，
> 這是判斷「我的 `~/.ssh/config` 到底生效沒」最快的方法（見 [[03-SSH-客戶端設定檔]]）。

### ★★★★ 步驟一：連線前的三個前置檢查

**不要一上來就 `ssh`** —— 連不上時你會分不清是網路、是服務、還是認證。
花三十秒做完這三項，可以省掉半小時的瞎猜。

**（a）在伺服器端確認 sshd 真的在聽**（透過 console 或 IPMI）：

```bash
sudo ss -ltnp | grep -E ':22\b'
```

```text
LISTEN 0  4096   *:22   *:*   users:(("systemd",pid=1,fd=76))   # ★★★★ 是 systemd 不是 sshd
```

> [!warning] ★★★★ Ubuntu 22.10 起 sshd 走 systemd socket activation
> 這會讓很多老經驗失效，機關環境升級到 24.04 一定會撞到：
> - `systemctl status ssh` 顯示 **inactive (dead)** 但 SSH 明明連得進去 —— 這是**正常的**，
>   連線進來時 `ssh.socket` 才把 `ssh@.service` 叫起來
> - **★★★★ `sshd_config` 的 `Port` 與 `ListenAddress` 會被忽略** ——
>   聽哪個埠由 `ssh.socket` 的 `ListenStream=` 決定
>
> 改埠的正確位置（改埠本身的討論在 [[04-sshd-伺服器端設定]]，這裡只講「為什麼改了沒用」）：
> ```bash
> sudo systemctl edit ssh.socket
> ```
> ```ini
> [Socket]
> ListenStream=
> ListenStream=2222
> ```
> ★★★★ 第一行空的 `ListenStream=` 是必要的，用來**清掉預設的 22**，漏掉會兩個埠都聽。
> ```bash
> sudo systemctl daemon-reload && sudo systemctl restart ssh.socket
> ```
> 判斷自己是哪種模式：`systemctl is-enabled ssh.socket` 回 `enabled` 就是 socket activation。

**（b）從客戶端確認埠通不通**（把網路問題跟 SSH 問題分開）：

```bash
nc -zv 192.168.20.31 22
```

```text
Connection to 192.168.20.31 22 port [tcp/ssh] succeeded!    # ★ 網路 OK，問題在階段 ②～⑥
nc: connect ... failed: Connection refused                  # ★★★ 到得了機器，但沒人聽 22
（卡住十幾秒最後 timed out）                                 # ★★★ 防火牆 DROP 或路由不通
```

**（c）看對方吐出來的版本字串**（不用登入就知道對方是誰）：

```bash
nc -w 5 192.168.20.31 22 </dev/null
```

```text
SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.5    # ★★★ 階段 ② 是明文，任何人都看得到
```

> [!note] 這行明文有兩面 ★★★
> **好處**：不用帳密就能確認「這個埠上跑的是 SSH、是哪一版」，排錯很好用。
> **壞處**：★★★ 攻擊者掃埠時同樣看得到精確版本，可直接比對已知漏洞。
> 遮掉版本字串是低價值的隱匿式安全，真正該做的是及時更新與限制來源 —— 見 [[07-SSH-安全強化]]。

### 步驟二：第一次連線的畫面，逐行解讀

```bash
ssh sysadm@192.168.20.31
```

預期輸出：

```text
The authenticity of host '192.168.20.31 (192.168.20.31)' can't be established.
ED25519 key fingerprint is SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs.
This key is not known by any other names.
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

逐行拆：

| 這一行 | 意思 | 重要度 |
| --- | --- | --- |
| `can't be established` | 你的 `known_hosts` 裡沒有這台 —— **不是錯誤，是 TOFU 的提問** | ★★★ |
| `ED25519 key fingerprint is` | 對方**選中**的 host key 型別是 Ed25519 | ★★ |
| `SHA256:kV3m...` | ★★★★★ **這 43 個字元就是你要比對的東西** | ★★★★★ |
| `This key is not known by any other names` | 這把 key 沒有以別的主機名／IP 出現在 known_hosts | ★★★ |
| `(yes/no/[fingerprint])` | ★★★★ 第三個選項是 OpenSSH 8.4 加的 —— **可以直接貼指紋讓它自己比** | ★★★★ |

> [!danger] ★★★★★ 這一刻打 `yes` 而沒有比對，等於關掉 SSH 的全部主機驗證
> `yes` 的意思是「我已經用其他方式確認過這把 key 是對的」。
> 如果你沒確認過就打 `yes`，那你只是把**當下線路上的任何一台機器**寫進了信任清單。
> 在機關內網這通常沒事；**在跨機關專線、VPN 出口、廠商遠端維護、公用 Wi-Fi 上，這是真的風險**。

**★★★★ 正確做法：用第三個選項，把帶外取得的指紋整串貼進去。**

```text
Are you sure you want to continue connecting (yes/no/[fingerprint])? SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs
Warning: Permanently added '192.168.20.31' (ED25519) to the list of known hosts.
sysadm@192.168.20.31's password:
```

貼錯或不符時：

```text
Are you sure you want to continue connecting (yes/no/[fingerprint])? SHA256:7bQvL2xR9dK4mN8sT0uY3wZ6cA1eG5hJ2kP4nX7rV9M
Please type 'yes', 'no' or the fingerprint: 
```

> [!tip] 為什麼「貼指紋」比「用眼睛比」好 ★★★★
> SHA256 指紋是 43 個大小寫混雜的 base64 字元。
> 人眼比對時**只會看頭尾幾個字**，中間有一段不同根本看不出來 ——
> 這正是攻擊者會利用的（用算力磨出一把頭尾相似的 key 不困難）。
> 讓 `ssh` 自己做字串比對，是**唯一不會偷懶的比對方式**。
> 注意 OpenSSH 8.4 起這個比對是**區分大小寫**的。

### ★★★ 步驟三：在主機端取得正確的指紋

指紋要在**主機自己身上**算，透過 IPMI / iDRAC / iLO / PVE console / 實體 KVM 這種**帶外管道**：

```bash
for f in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf "$f"; done
```

```text
256 SHA256:Z1xW4vU7tS0rQ3pO6nM9lK2jI5hG8fE1dC4bA7zY0xQ root@srv-web01 (ECDSA)
256 SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs root@srv-web01 (ED25519)
3072 SHA256:M9pX2vC5nB8kL1jH4gF7dS0aQ3wE6rT9yU2iO5pA8sD root@srv-web01 (RSA)
│    │                                                   │             └ 型別
│    └ ★★★★ 指紋本體（交機表要抄的就是這一串）             └ comment
└ 位元數
```

主控台字太小時，加 `-v` 可以多印一張 randomart 圖形輔助辨識
（客戶端對應的是 `ssh -o VisualHostKey=yes`）：

```bash
ssh-keygen -lvf /etc/ssh/ssh_host_ed25519_key.pub | head -n 3
```

```text
256 SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs root@srv-web01 (ED25519)
+--[ED25519 256]--+
|      .o+.       |
```

★★ 圖形只適合「一眼看出**完全不同**」，真正的驗證永遠是那 43 個字元的逐字比對。

> [!danger] ★★★★ `ssh-keyscan` 取到的指紋不能拿來驗證自己
> 常見的自欺行為：
> ```bash
> ssh-keyscan -t ed25519 192.168.20.31 | ssh-keygen -lf -    # ★★★★ 這不是驗證
> ```
> 因為 `ssh-keyscan` **走的是跟 `ssh` 完全一樣的那條網路路徑**。
> 路徑上若有中間人，`ssh-keyscan` 拿到的就是**中間人的 key**，
> 然後你拿中間人的指紋去比對中間人的指紋 —— 當然相符。
> 這叫「用嫌犯的證詞證明嫌犯清白」。
>
> **`ssh-keyscan` 的正當用途只有兩個**：
> ① 把**已經由帶外管道確認過**的指紋，自動化寫進 `known_hosts`（本篇腳本就是這樣用）
> ② 盤點「這批主機現在的 host key 是什麼」，跟資產表**對帳**（★★★ 基準必須是資產表）

### ★★★ known_hosts 的實際長相

```bash
tail -n 2 ~/.ssh/known_hosts
```

未 hash 的樣子（RHEL 系預設）：

```text
192.168.20.31 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB7q...KcE
srv-web01,192.168.20.31 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB7q...KcE
```

Hash 過的樣子（**Debian / Ubuntu 預設 `HashKnownHosts yes`**）：

```text
|1|Xr8QpM3vK2sT9dW=|hN7bLyF4uJ6aE0oG5PnR= ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB7q...KcE
```

| 欄位 | 說明 | 重要度 |
| --- | --- | --- |
| `\|1\|salt\|hash` | ★★★ 主機名／IP 的 HMAC-SHA1 雜湊，**看不出是哪台** | ★★★ |
| `ssh-ed25519` | host key 型別 | ★★ |
| `AAAAC3...` | base64 公鑰本體 | ★★ |
| 行首 `@revoked` | ★★★★ 標記為撤銷，之後連到這把 key 會**直接拒絕** | ★★★★ |
| 行首 `@cert-authority` | ★★★ 這是 SSH CA 的公鑰，可簽發主機憑證 | ★★★ |

> [!note] 為什麼 Debian 系要 hash？★★★
> 防止「攻破一台跳板機 → 讀 `known_hosts` → 得到整個機房的主機清單」。
> 這是真實的橫向移動手法（蠕蟲時代就在用）。
> 代價是你**不能再用 `grep` 找主機**，必須改用 `ssh-keygen -F`。

查詢（hash 過也查得到，因為 `ssh-keygen` 會自己算 HMAC）：

```bash
ssh-keygen -F 192.168.20.31
```

預期輸出：

```text
# Host 192.168.20.31 found: line 14                       # ★★★ 行號，處置時要用
|1|Xr8QpM3vK2sT9dW=|hN7bLyF4uJ6aE0oG5PnR= ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB7q...KcE
```

順便算出**已登記那把 key 的指紋**（比對用，加 `-l`）：

```bash
ssh-keygen -lF 192.168.20.31
```

預期輸出：

```text
# Host 192.168.20.31 found: line 14
192.168.20.31 SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs   # ★★★★ 拿這個跟交機表比
```

查不到時（**exit code 是 1，腳本要判斷**）：

```bash
ssh-keygen -F 10.0.0.99; echo "exit=$?"
```

```text
exit=1        # ★★★ 沒有這台的記錄
```

刪除（**先看下一節的決策樹再決定要不要刪**）：

```bash
ssh-keygen -R 192.168.20.31
```

預期輸出：

```text
# Host 192.168.20.31 found: line 14
/home/sysadm/.ssh/known_hosts updated.
Original contents retained as /home/sysadm/.ssh/known_hosts.old   # ★★★ 自動備份，刪錯救得回來
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> **套件與服務名稱不同**：
> ```bash
> sudo dnf install -y openssh-server
> sudo systemctl enable --now sshd          # ★★★ 是 sshd 不是 ssh
> sudo systemctl status sshd
> ```
> ★★★ RHEL 系**沒有 socket activation**，`sshd_config` 的 `Port` / `ListenAddress` 正常生效。
>
> **★★★★ 最大的差異：system-wide crypto-policies**
> RHEL 8/9 的 SSH 演算法**不是只看 `sshd_config`**，還被全系統密碼原則覆蓋：
> ```bash
> update-crypto-policies --show
> ```
> ```text
> DEFAULT
> ```
> 連老設備談不攏演算法時，RHEL 上的正解是切策略而不是硬改 `sshd_config`：
> ```bash
> sudo update-crypto-policies --set LEGACY     # ★★★★ 全系統降級，含 TLS，影響很大
> ```
> ★★★★ `LEGACY` 會連 HTTPS、資料庫連線的加密強度一起降，
> **機關環境請優先用單一連線的 `-o` 旗標，不要動全系統策略**。
>
> **防火牆**：RHEL 系是 firewalld，不是 ufw：
> ```bash
> sudo firewall-cmd --permanent --add-service=ssh && sudo firewall-cmd --reload
> ```
>
> **SELinux ★★★★**：改了 SSH 埠一定要同時放行，否則 sshd 起不來：
> ```bash
> sudo semanage port -a -t ssh_port_t -p tcp 2222
> ```
> 細節見 [[07-SELinux與AppArmor]]。
>
> ★★ RHEL 系 `HashKnownHosts` 預設是 `no`，`known_hosts` 可以直接 `grep`。

---

## 進階應用

### ★★★★★ `REMOTE HOST IDENTIFICATION HAS CHANGED` 的四種成因與分流

先看訊息長什麼樣：

```text
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!
Someone could be eavesdropping on you right now (man-in-the-middle attack)!
It is also possible that a host key has just been changed.
The fingerprint for the ED25519 key sent by the remote host is
SHA256:7bQvL2xR9dK4mN8sT0uY3wZ6cA1eG5hJ2kP4nX7rV9M.        # ★★★★ 現在收到的
Please contact your system administrator.
Add correct host key in /home/sysadm/.ssh/known_hosts to get rid of this message.
Offending ED25519 key in /home/sysadm/.ssh/known_hosts:14   # ★★★ 舊的在第 14 行
Host key for 192.168.20.31 has changed and you have requested strict checking.
Host key verification failed.
```

> [!danger] ★★★★★ 反射性 `ssh-keygen -R` 是把入侵警報當噪音關掉
> 網路上大部分文章的答案是「跑 `ssh-keygen -R host` 就好了」。
> **那不是解法，那是把唯一一個能偵測到中間人攻擊的機制手動關掉。**
> SSH 花了整個信任模型才換來這一聲警報，你三秒鐘就把它消音了。
>
> 正確順序永遠是：**先確認 → 再處置**。確認的成本是三分鐘，猜錯的成本是一次資安事件。

**四種成因與辨別方法：**

```text
★★★★★ 看到 HOST KEY CHANGED，先停手，跑這棵決策樹

  ┌── 這台機器最近有沒有【變更紀錄】？（重灌／重建 VM／從快照還原／換硬體）
  │    ├─ 有 ───▶ 【成因①：主機重建】★★★
  │    │           → 到 IPMI/PVE console 上跑 ssh-keygen -lf 取新指紋
  │    │           → 跟畫面上收到的那串【逐字比對】
  │    │           → 相符才 ssh-keygen -R，然後重新登記
  │    └─ 沒有 ─┐
  │             │
  ├── 這個【IP 是不是 DHCP 或 NAT 後面】？
  │    ├─ 是 ───▶ 【成因②：IP 換人了】★★★
  │    │           → 同一個 IP 現在是另一台機器（DHCP 租約到期重派、NAT 對應改了）
  │    │           → 用 ip neigh / arp -n 看 MAC 有沒有變
  │    │           → 用 ssh -o HostKeyAlias 或改用主機名連，別再用 IP 當識別
  │    └─ 否 ───┐
  │             │
  ├── 這個位址後面是不是【負載平衡／VIP／多台後端】？
  │    ├─ 是 ───▶ 【成因③：連到不同後端】★★★
  │    │           → 每台後端有各自的 host key，輪詢時就會跳警告
  │    │           → 解法見下方「多台後端共用位址」
  │    └─ 否 ───┐
  │             │
  └────────────▶ 【成因④：可能是真的 MITM】★★★★★
                  → ✗ 不要重試、不要打密碼、不要 -R
                  → 立刻改用【帶外管道】（IPMI/實體 console）取指紋
                  → 指紋不符 → 【資安事件通報】，保留 ~/.ssh/known_hosts 與 ssh -vvv 輸出
                  → 檢查同網段有無 ARP 欺騙（見 [[03-入侵偵測與防禦IDS-IPS]]）
```

**成因①（主機重建）的完整處置**：

```bash
# ★★★ 【1】從 console 取得新指紋（在主機上做，不要透過 SSH）
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

```text
256 SHA256:7bQvL2xR9dK4mN8sT0uY3wZ6cA1eG5hJ2kP4nX7rV9M root@srv-web01 (ED25519)
```

```bash
# ★★★★ 【2】跟警告畫面上那串比對，一致才往下做
# ★★★ 【3】先看清楚舊的是哪一行（不要盲刪）
ssh-keygen -lF 192.168.20.31
```

```text
# Host 192.168.20.31 found: line 14
192.168.20.31 SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs
```

```bash
# ★★★ 【4】刪除舊記錄（會自動留 known_hosts.old）
ssh-keygen -R 192.168.20.31
# ★★★★ 【5】重新連線，用貼指紋的方式重新登記
ssh sysadm@192.168.20.31
```

**成因③（多台後端共用位址）的處置** ★★★：

三個選項，由好到差：

| 做法 | 說明 | 重要度 |
| --- | --- | --- |
| ★★★★ 讓所有後端共用同一組 host key | 把同一組 `/etc/ssh/ssh_host_*` 佈到每台後端 —— **前提是這組私鑰的保護等級要提高** | ★★★★ |
| ★★★ 把每台後端的 key 都登記進 known_hosts 同一行 | 同一個主機名可以有多行，任一符合就通過 | ★★★ |
| ★★★ 用 SSH CA 簽發主機憑證 | 最正規的解法，`@cert-authority` 一行搞定整個機房 | ★★★ |
| ★★★★★ 用 `StrictHostKeyChecking=no` 迴避 | **禁止** —— 等於整批主機都不驗證 | ★★★★★ |

### ★★★★ `ssh -v` 的三段式判讀

這是所有 SSH 問題的**第一動作**，比亂改設定有效一百倍。

```bash
ssh -v sysadm@192.168.20.31
```

輸出很長，但你只要盯**四個關鍵字**：

```text
OpenSSH_9.6p1 Ubuntu-3ubuntu13.5, OpenSSL 3.0.13 30 Jan 2024
debug1: Reading configuration data /home/sysadm/.ssh/config      # ★★★ 有沒有讀到你的設定
debug1: Reading configuration data /etc/ssh/ssh_config
debug1: Connecting to 192.168.20.31 [192.168.20.31] port 22.     # 【關鍵字 1】階段 ①
debug1: Connection established.                                   # ★★★ 有這行 = TCP 通了
debug1: Local version string SSH-2.0-OpenSSH_9.6p1
debug1: Remote protocol version 2.0, remote software version OpenSSH_9.6p1
debug1: Authenticating to 192.168.20.31:22 as 'sysadm'
debug1: SSH2_MSG_KEXINIT sent
debug1: SSH2_MSG_KEXINIT received                                 # ★★★ 階段 ③ 開始
debug1: kex: algorithm: sntrup761x25519-sha512@openssh.com
debug1: kex: host key algorithm: ssh-ed25519                      # ★★★ 談定用哪種 host key
debug1: Server host key: ssh-ed25519 SHA256:kV3mQ0Zc8p...RcIs     # 【關鍵字 2】階段 ④
debug1: Host '192.168.20.31' is known and matches the ED25519 host key.   # ★★★★ 驗證通過
debug1: Found key in /home/sysadm/.ssh/known_hosts:14
debug1: Will attempt key: /home/sysadm/.ssh/id_ed25519 ED25519 SHA256:...
debug1: Offering public key: /home/sysadm/.ssh/id_ed25519         # 【關鍵字 3】階段 ⑤
debug1: Authentications that can continue: publickey,password    # 【關鍵字 4】伺服器接受的方式
debug1: Next authentication method: password
sysadm@192.168.20.31's password:
```

**四個關鍵字的判讀規則**：

| 關鍵字 | 沒看到代表 | 看到但後面斷掉代表 | 重要度 |
| --- | --- | --- | --- |
| `Connecting to` | ★★★ **名稱解析失敗**（DNS / `/etc/hosts`），連 IP 都沒解出來 | TCP 建不起來 → 階段 ① | ★★★ |
| `Connection established` | ★★★★ TCP 沒通 → 查防火牆、路由、sshd 是否在聽 | — | ★★★★ |
| `Server host key:` | ★★★★ 卡在演算法協商 → 階段 ③（`no matching ...`） | — | ★★★★ |
| `Offering public key:` | ★★★ **根本沒有可用的金鑰**，或金鑰權限錯被略過 | 每把都被拒 → 階段 ⑤ | ★★★ |
| `Authentications that can continue:` | — | ★★★★ **這行列的就是伺服器願意接受的方式** | ★★★★ |

> [!tip] `Authentications that can continue:` 這行最有價值 ★★★★
> - 只列 `publickey` → 伺服器**已停用密碼登入**，你沒把公鑰放上去就是進不去
> - 列了 `password` 但你一直被拒 → 密碼真的錯，或帳號被鎖（看 `faillock` / `pam_tally2`）
> - 完全沒出現這行 → 問題**不在階段 ⑤**，往前面找

`-vv` 多顯示演算法協商細節，`-vvv` 連封包層都印。**排錯順序是 `-v` → `-vv`，不要一開始就 `-vvv`**（訊息太多反而看不到重點）。★★★

伺服器端對照看（需要另一條既有連線或 console）：

```bash
sudo journalctl -u ssh -f -n 50
```

預期輸出：

```text
Aug 28 10:22:31 srv-web01 sshd[2841]: Accepted publickey for sysadm from 192.168.20.10 port 51422 ssh2: ED25519 SHA256:...
Aug 28 10:23:04 srv-web01 sshd[2903]: Failed password for invalid user admin from 203.0.113.44 port 40122 ssh2
```

★★★ socket activation 的機器上，單一連線的日誌在 `ssh@<實例>.service`：

```bash
sudo journalctl -u 'ssh@*' -n 50 --no-pager
```

日誌的完整運用見 [[19-日誌系統]]。

### ★★★★ OpenSSH 8.8+ 連老設備：`no matching host key type`

機關環境**一定**會遇到 —— 用 Ubuntu 24.04 的管理工作站去連 2015 年的交換器或 NAS：

```bash
ssh admin@10.0.30.5
```

```text
Unable to negotiate with 10.0.30.5 port 22: no matching host key type found.
Their offer: ssh-rsa                            # ★★★★ 對方只會 SHA-1 簽章的 ssh-rsa
```

**成因**：OpenSSH 8.8（2021-09-26）起**預設停用 `ssh-rsa`**，因為那是 RSA + SHA-1 簽章，
SHA-1 已經可以做出選定前綴碰撞。**注意這停用的是「簽章演算法」不是「RSA 金鑰」** ——
同一把 RSA 金鑰改用 `rsa-sha2-256` / `rsa-sha2-512` 簽章就完全沒問題（OpenSSH 7.2 起就支援），
問題只出在**對方太舊、只會用 SHA-1 簽**。★★★★

**臨時解法（單次連線）**：

```bash
ssh -o HostKeyAlgorithms=+ssh-rsa \
    -o PubkeyAcceptedAlgorithms=+ssh-rsa \
    admin@10.0.30.5
```

| 選項 | 管什麼 | 什麼時候需要 |
| --- | --- | --- |
| `HostKeyAlgorithms=+ssh-rsa` | ★★★ **對方的 host key**（階段 ③／④） | `no matching host key type` |
| `PubkeyAcceptedAlgorithms=+ssh-rsa` | ★★★ **你的使用者金鑰簽章**（階段 ⑤） | `Permission denied (publickey)` 但金鑰確實在 `authorized_keys` |

★★★ `+` 是「加回清單」，`=`（不加號）是「整個換掉」。**寫錯成 `=ssh-rsa` 會把其他演算法全砍掉**，
變成連現代主機都連不上。

更老的設備連 KEX 都談不攏：

```text
Unable to negotiate with 10.0.30.5 port 22: no matching key exchange method found.
Their offer: diffie-hellman-group1-sha1,diffie-hellman-group14-sha1
```

```bash
ssh -o KexAlgorithms=+diffie-hellman-group14-sha1 \
    -o HostKeyAlgorithms=+ssh-rsa \
    admin@10.0.30.5
```

> [!danger] ★★★★ 這些旗標是「暫時的」，而且要有紀錄
> 加回 `ssh-rsa` / `dh-group1-sha1` 的實際後果：
> - **★★★★ 主機認證的簽章可被偽造** —— SHA-1 碰撞讓「證明我是這台機器」的保證變弱
> - **★★★★★ `diffie-hellman-group1-sha1` 是 1024-bit DH**，國家級對手已具備破解能力（Logjam）
> - ★★★ 一旦寫進 `~/.ssh/config` 就會被忘記，三年後還在用
>
> 機關的正確處理：
> ① ★★★★ 把這條設定**限定到那一台**（`Host` 區塊，見 [[03-SSH-客戶端設定檔]]），不要寫在 `Host *`
> ② ★★★★ 開一張**設備汰換／韌體升級**的追蹤單，把設備型號與到期日寫上去
> ③ ★★★ 這類老設備的管理介面**只允許從管理網段存取**，不要暴露在一般網段
> ④ ★★ 在設定檔加註解寫明「為什麼降級、誰核准、預計何時移除」，稽核時交代得出來

### 登入之後的環境雜訊：亂碼與畫面錯亂

**（a）★★★ 中文亂碼與 `setlocale` 警告**

```text
-bash: warning: setlocale: LC_ALL: cannot change locale (zh_TW.UTF-8)
```

成因：客戶端透過 `SendEnv LANG LC_*`（Debian/Ubuntu 的 `/etc/ssh/ssh_config` 預設就有這行）
把自己的 locale 帶過去，但**伺服器沒有安裝那個 locale**。

```bash
# ★ 在伺服器上看有哪些 locale
locale -a | grep -i zh
```

```text
（沒有輸出 → 伺服器根本沒有中文 locale）
```

三種解法：

```bash
# ★★★ 解法一（建議）：在伺服器補上 locale
sudo locale-gen zh_TW.UTF-8 en_US.UTF-8
sudo update-locale
# ★★ 解法二：這次連線不要帶過去
ssh -o SendEnv=  sysadm@srv-web01
# ★★ 解法三：連線後臨時指定
LANG=C.UTF-8 ssh sysadm@srv-web01
```

> [!warning] ★★★ 亂碼跟 locale 不一定有關
> `LC_*` 影響的是**排序、日期、訊息語言**。
> 中文變成 `????` 或 `\x??` 通常是**終端機模擬器的編碼**設錯（PuTTY 的 Window→Translation 要選 UTF-8），
> 跟伺服器 locale 無關。先判斷是哪一邊的問題再動手。

**（b）★★ `TERM` 不對造成畫面錯亂**

```bash
ssh sysadm@srv-web01 'echo $TERM'
```

```text
xterm-256color        # ★ 這是客戶端帶過去的
```

老系統（RHEL 6、某些嵌入式設備）沒有 `xterm-256color` 的 terminfo，
症狀是 `vim`／`top` 畫面破碎、方向鍵變亂碼。臨時解：

```bash
TERM=xterm ssh admin@10.0.30.5
```

**（c）★★★ 機關常見客戶端的行為差異**

| 客戶端 | known_hosts 位置 | 指紋顯示 | 要注意 |
| --- | --- | --- | --- |
| OpenSSH（Linux／macOS／Win10+） | `~/.ssh/known_hosts` | SHA256 base64 | ★ 本篇所有指令的基準 |
| PuTTY | ★★★ **Windows 登錄檔** `HKCU\Software\SimonTatham\PuTTY\SshHostKeys` | ★★★ 自己的格式，**不是 SHA256 base64** | ★★★★ 指紋比對要用 PuTTY 自己顯示的那串，或改用 `plink` |
| Windows Terminal + 內建 OpenSSH | `C:\Users\<user>\.ssh\known_hosts` | SHA256 | ★★ 與 Linux 一致 |
| MobaXterm | ★★ 自己的 session 資料夾 | SHA256 | ★★ 內建 X11／sftp 分頁，會**自動開額外連線**（連線數限制要留意） |
| WSL | ★★★ WSL 內的 `~/.ssh/`，**與 Windows 的不同份** | SHA256 | ★★★ 同一個人有兩份 known_hosts，警告只跳其中一邊 |

> [!tip] ★★★ 機關統一用 OpenSSH 客戶端，維運成本會低很多
> Windows 10 1809 起內建 OpenSSH 客戶端。統一之後：
> `~/.ssh/config` 可以共用、`known_hosts` 格式一致、教學文件只要寫一份、
> 指紋比對流程不用因人而異。PuTTY 留給「必須用序列埠 console」的場合就好。

### ★★★ 非互動執行：`ssh host '指令'` 與 exit code

維運腳本大量依賴這個模式，有兩個**一定要知道**的細節：

```bash
ssh sysadm@srv-web01 'systemctl is-active nginx'; echo "exit=$?"
```

```text
active
exit=0            # ★★★★ ssh 回傳的是【遠端指令】的 exit code
```

```bash
ssh sysadm@srv-web01 'systemctl is-active nosuch'; echo "exit=$?"
```

```text
inactive
exit=3            # ★★★ 遠端指令的 3 原封不動傳回來
```

```bash
ssh sysadm@10.0.0.99 'true'; echo "exit=$?"
```

```text
ssh: connect to host 10.0.0.99 port 22: Connection timed out
exit=255          # ★★★★ 255 = 【ssh 自己】失敗（連不上／認證失敗／host key 不符）
```

> [!warning] ★★★★ 255 是 ssh 的保留碼，腳本一定要分開處理
> `exit=255` 代表「**指令根本沒跑到**」，跟「指令跑了但失敗」是完全不同的意思。
> 批次維運腳本如果不分這兩者，就會把「連不上的機器」誤判成「檢查沒通過的機器」，
> 然後對一台根本沒連上的機器發出錯誤的告警或執行錯誤的補救動作。★★★★
> 唯一的例外：遠端指令自己剛好回傳 255（很少見），這時要用 wrapper 包一層改變回傳值。

**什麼時候需要 `-t`（強制配置 pty）**：

```bash
ssh sysadm@srv-web01 'sudo systemctl restart nginx'
```

```text
sudo: a terminal is required to read the password; either use the -S option to read from standard input, or configure an askpass helper
                                      # ★★★ 沒有 tty，sudo 問不了密碼
```

```bash
ssh -t sysadm@srv-web01 'sudo systemctl restart nginx'
```

```text
[sudo] password for sysadm:
Connection to srv-web01 closed.       # ★★ -t 之後 sudo 就問得到密碼了
```

| 情境 | 要不要 `-t` | 說明 |
| --- | --- | --- |
| `sudo` 需要輸入密碼 | ★★★★ 要 | 沒 tty 就問不了密碼 |
| 要跑 `top` / `vim` / `less` 這種全螢幕程式 | ★★★ 要 | 否則畫面全亂 |
| 要 `Ctrl-C` 能正確中斷遠端程式 | ★★★ 要 | 訊號要靠 tty 傳過去 |
| 把輸出接管線 `\| grep` | ★★★★ **不要** | ★★★★ `-t` 會混入控制字元與 `Connection to ... closed.`，把後續解析弄壞 |
| 在 cron／CI 裡跑 | ★★★★ **不要** | ★★★ 沒有 tty 可配置，會噴 `Pseudo-terminal will not be allocated` |

看到這行**不是錯誤**，只是提醒：

```text
Pseudo-terminal will not be allocated because stdin is not a terminal.
```

### ★★★★ 全機共用的 `/etc/ssh/ssh_known_hosts`

機關有二十台伺服器、十個維運人員時，讓每個人各自 TOFU 二十次是**流程上的漏洞** ——
只要有一個人隨手按 yes，那台跳板機的信任就破了。

正解是由管理者**集中維護一份**經過帶外驗證的 `/etc/ssh/ssh_known_hosts`，
發到每台管理工作站：

```bash
sudo install -m 0644 -o root -g root /srv/config/ssh_known_hosts /etc/ssh/ssh_known_hosts
```

驗證它有生效：

```bash
ssh -v sysadm@srv-web01 2>&1 | grep -i 'found key'
```

```text
debug1: Found key in /etc/ssh/ssh_known_hosts:7      # ★★★★ 讀的是全機那份，不是個人的
```

搭配這兩個設定，個人就**不能再自己 TOFU**：

```text
# /etc/ssh/ssh_config
Host *
    StrictHostKeyChecking yes          # ★★★★ 不在清單裡就直接拒絕，不問
    UserKnownHostsFile /etc/ssh/ssh_known_hosts ~/.ssh/known_hosts
```

| `StrictHostKeyChecking` 值 | 行為 | 適用 |
| --- | --- | --- |
| `ask`（預設） | 沒看過就問你 yes/no/fingerprint | ★★★ 一般人工操作 |
| `yes` | ★★★★ 沒看過**直接拒絕**，也不接受變更 | ★★★★ 集中管理、自動化 |
| `accept-new` | ★★★ 新主機自動接受，**但變更仍然拒絕** | ★★★ 大量佈署時的折衷 |
| `no` / `off` | ★★★★★ 新主機自動接受、**變更也自動接受** | ★★★★★ **正式環境禁用** |

> [!danger] ★★★★★ `StrictHostKeyChecking=no` 是最常見的自殺式設定
> 它常常跟 `-o UserKnownHostsFile=/dev/null` 一起出現在 CI/CD 腳本裡。
> 這組合的實際意義是：**永久關閉 SSH 的主機驗證，且不留任何記錄**。
> 對 CI 來說，任何能做 ARP 欺騙或 DNS 劫持的人都能攔下你的部署流程、
> 拿到部署金鑰、把惡意程式送進正式站。
> **CI/CD 的正解**：把驗證過的 host key **寫死在 pipeline 的祕密變數裡**，
> 部署前 `echo "$KNOWN_HOSTS" > ~/.ssh/known_hosts`，然後用 `StrictHostKeyChecking=yes`。
> 相關做法見 [[03-機密管理與金鑰保護]]。

### ★★★★ 鎖門預防：先準備好第二條路

這是貫穿整個 SSH 章節（尤其 [[04-sshd-伺服器端設定]] 與 [[07-SSH-安全強化]]）的基調。
**在你還連得進去的時候**，先把後路鋪好：

```text
★★★★ 動 SSH 設定之前的四道保險

  ① ★★★★★ 保留一條【既有的 SSH 連線不要關】
     → 改壞了、重啟 sshd 之後，這條舊連線【仍然活著】
     → 可以用它把設定改回來。關掉它 = 自斷退路

  ② ★★★★ 開【第二個終端機】測試新連線
     → 舊連線不動，用新視窗連連看
     → 連得上再收工，連不上就回舊視窗改回來

  ③ ★★★★ 改之前一定先做語法檢查（在【重啟之前】）
     $ sudo sshd -t                       # 沒輸出 = 語法正確
     $ sudo sshd -T | grep -i permitroot  # 印出【最終有效設定】

  ④ ★★★★ 確認【帶外管道】真的能用（不是「應該能用」）
     → IPMI / iDRAC / iLO 的密碼現在就試登入一次
     → PVE / VMware console 開得起來嗎？
     → 雲端主機的 serial console / VNC 有沒有啟用？
     ★★★★★ 很多人是在被鎖在外面之後，才發現 IPMI 密碼沒人知道
```

`sshd -t` 的兩種輸出：

```bash
sudo sshd -t
```

```text
（沒有任何輸出，exit code 0 → ★★★★ 語法正確，可以重啟）
```

```bash
sudo sshd -t
```

```text
/etc/ssh/sshd_config line 34: Bad configuration option: PermitRootLogins
/etc/ssh/sshd_config: terminating, 1 bad configuration options   # ★★★★ 千萬不要在這時候重啟
```

保險起見的自動回滾（改設定前先掛一個定時還原）：

```bash
# ★★★★ 十分鐘後自動還原備份並重啟，除非你先把它取消
sudo cp -a /etc/ssh/sshd_config /etc/ssh/sshd_config.bak
echo 'cp -a /etc/ssh/sshd_config.bak /etc/ssh/sshd_config && systemctl restart ssh' \
  | sudo at now + 10 minutes
# 確認新設定沒問題之後，把這個 at job 刪掉
sudo atq
sudo atrm <job號碼>
```

★★★ `at` 的用法與 systemd timer 的替代寫法見 [[18-排程工作]]。

---

## 完整實戰範例

### 情境

機關新到一台 **Ubuntu 24.04** 伺服器 `srv-web01`（`192.168.20.31`），要做交機驗收。
維運人員手上只有 iDRAC 的網址與帳密，管理工作站在 `192.168.20.10`。

驗收的三個步驟：

```text
【步驟一】從 iDRAC console 取得四種 host key 指紋，寫進交機表（帶外）
【步驟二】從管理工作站執行 ssh-first-connect，用交機表的指紋比對
【步驟三】比對通過才寫入 known_hosts，並登記到資產表
```

### 步驟一：帶外取得指紋（在 iDRAC / IPMI console 上做）

```bash
sudo bash -c 'for f in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf "$f"; done'
```

預期輸出：

```text
256 SHA256:Z1xW4vU7tS0rQ3pO6nM9lK2jI5hG8fE1dC4bA7zY0xQ root@srv-web01 (ECDSA)
256 SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs root@srv-web01 (ED25519)
3072 SHA256:M9pX2vC5nB8kL1jH4gF7dS0aQ3wE6rT9yU2iO5pA8sD root@srv-web01 (RSA)
```

抄進交機表（★★★★ 這張表要跟資產編號一起歸檔，不是抄在便條紙上）：

| 項目 | 內容 |
| --- | --- |
| 資產編號 | `MIS-SRV-2026-031` |
| 主機名 / IP | `srv-web01` / `192.168.20.31` |
| OS | Ubuntu 24.04.3 LTS |
| OpenSSH | 9.6p1 |
| ★★★★ ED25519 指紋 | `SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs` |
| ★★★ RSA 指紋 | `SHA256:M9pX2vC5nB8kL1jH4gF7dS0aQ3wE6rT9yU2iO5pA8sD` |
| ★★ ECDSA 指紋 | `SHA256:Z1xW4vU7tS0rQ3pO6nM9lK2jI5hG8fE1dC4bA7zY0xQ` |
| 取得方式 | ★★★★ iDRAC 虛擬主控台（帶外） |
| 取得人 / 日期 | 王小明 / 2026-08-28 |

### 步驟二：`/usr/local/bin/ssh-first-connect`

```bash
sudo install -m 0755 /dev/stdin /usr/local/bin/ssh-first-connect <<'SCRIPT'
#!/usr/bin/env bash
#
# ssh-first-connect —— 以「帶外取得的指紋」為準，安全完成第一次 SSH 連線並登記 known_hosts
#
# 用法：ssh-first-connect <主機> <埠> <SHA256:預期指紋> [known_hosts路徑]
# 例：  ssh-first-connect 192.168.20.31 22 SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs
#
# 設計原則：
#   ★★★★★ 指紋不符 → 立刻中止，絕不寫入 known_hosts
#   ★★★★  寫入前先備份，任何後續失敗都自動回滾
#   ★★★   只寫入「指紋相符的那一種 key」，不順便寫入未驗證的其他 key
#
set -euo pipefail

readonly PROG="${0##*/}"
HOST="${1:-}"; PORT="${2:-}"; EXPECT="${3:-}"
KNOWN_HOSTS="${4:-$HOME/.ssh/known_hosts}"
BACKUP=""
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/${PROG}.XXXXXX")"

# ---------- 共用函式 ----------
log()  { printf '[ %-4s ] %s\n' "$1" "$2"; }
step() { printf '\n=== %s ===\n' "$*"; }
die()  { printf '\n[FAIL] %s\n' "$*" >&2; exit 1; }

rollback() {
  if [ -n "$BACKUP" ] && [ -f "$BACKUP" ]; then
    cp -p -- "$BACKUP" "$KNOWN_HOSTS"
    log "RB" "已將 $KNOWN_HOSTS 還原為 $BACKUP"
  fi
}
cleanup() { rm -rf -- "$WORKDIR"; }
trap cleanup EXIT

usage() {
  cat >&2 <<EOF
用法：$PROG <主機> <埠> <SHA256:預期指紋> [known_hosts路徑]

預期指紋必須從【帶外管道】取得（IPMI/iDRAC/PVE console、交機文件），
在主機上執行：ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
EOF
  exit 2
}

# ---------- 【0】參數檢查 ----------
step "【0】參數檢查"
[ -n "$HOST" ] && [ -n "$PORT" ] && [ -n "$EXPECT" ] || usage
case "$PORT" in ""|*[!0-9]*) die "埠號不合法：$PORT";; esac
(( PORT >= 1 && PORT <= 65535 )) || die "埠號不合法：$PORT"
# ★★★★ 指紋格式驗證：SHA256: + 43 個 base64 字元（無 padding）
printf '%s' "$EXPECT" | grep -Eq '^SHA256:[A-Za-z0-9+/]{43}$' \
  || die "指紋格式不正確：$EXPECT
        正確格式範例：SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs
        ★★★ 不要包含結尾的句點，也不要用 MD5 格式"
for c in ssh ssh-keygen ssh-keyscan nc; do
  command -v "$c" >/dev/null || die "缺少必要指令：$c"
done
log "OK" "主機=$HOST 埠=$PORT known_hosts=$KNOWN_HOSTS"

# ★★★ 非 22 埠在 known_hosts 裡是 [host]:port 的格式
if (( PORT == 22 )); then HOSTSPEC="$HOST"; else HOSTSPEC="[$HOST]:$PORT"; fi

# ---------- 【1】既有記錄檢查 ----------
step "【1】檢查 known_hosts 既有記錄"
mkdir -p -- "$(dirname -- "$KNOWN_HOSTS")"
chmod 700 -- "$(dirname -- "$KNOWN_HOSTS")"
touch -- "$KNOWN_HOSTS"; chmod 600 -- "$KNOWN_HOSTS"

if ssh-keygen -f "$KNOWN_HOSTS" -F "$HOSTSPEC" >"$WORKDIR/existing.txt" 2>/dev/null \
   && [ -s "$WORKDIR/existing.txt" ]; then
  OLD_FP="$(ssh-keygen -f "$KNOWN_HOSTS" -lF "$HOSTSPEC" | awk '/SHA256:/ {print $2}' | head -n1)"
  if [ "$OLD_FP" = "$EXPECT" ]; then
    log "OK" "已經登記過且指紋相符（$OLD_FP），不需重複寫入"
    exit 0
  fi
  # ★★★★★ 已有記錄但指紋不同 —— 這正是 HOST KEY CHANGED 的情境，本腳本【不自動處理】
  die "known_hosts 已有 $HOSTSPEC 的記錄，但指紋與預期不符
        已登記：$OLD_FP
        預期值：$EXPECT
        ★★★★★ 這是 HOST KEY CHANGED 的情境，禁止本腳本自動覆蓋。
        請先確認主機是否重建過（查變更單），並用帶外管道重新取得指紋，
        確認無誤後手動執行：ssh-keygen -R '$HOSTSPEC'"
fi
log "OK" "known_hosts 尚無 $HOSTSPEC 的記錄"

# ---------- 【2】TCP 埠連通測試 ----------
step "【2】TCP 埠連通測試（階段①）"
if ! nc -z -w 5 "$HOST" "$PORT" 2>/dev/null; then
  die "無法連上 ${HOST}:${PORT}
        ★★★ Connection refused → sshd 沒跑或埠不對，到主機上跑 ss -ltnp
        ★★★ 逾時無回應       → 防火牆 DROP 或路由不通，檢查 ufw/firewalld 與網段"
fi
log "OK" "${HOST}:${PORT} 可連線"

# ---------- 【3】取得對方提供的 host key ----------
step "【3】取得對方提供的 host key（ssh-keyscan）"
if ! ssh-keyscan -T 10 -p "$PORT" -t rsa,ecdsa,ed25519 -- "$HOST" \
      >"$WORKDIR/scan.txt" 2>"$WORKDIR/scan.err"; then
  die "ssh-keyscan 執行失敗：$(tr '\n' ' ' <"$WORKDIR/scan.err")"
fi
grep -v '^#' "$WORKDIR/scan.txt" >"$WORKDIR/keys.txt" || true
[ -s "$WORKDIR/keys.txt" ] || die "ssh-keyscan 沒有取回任何 host key
        ★★★ 對方可能不是 SSH 服務，或版本過舊只支援本腳本未指定的型別"
log "OK" "取得 $(wc -l <"$WORKDIR/keys.txt") 把 host key"

# ---------- 【4】逐一比對指紋 ----------
step "【4】比對指紋（★★★★★ 這是整個流程的核心）"
MATCH_LINE=""; MATCH_TYPE=""
while IFS= read -r line; do
  [ -n "$line" ] || continue
  printf '%s\n' "$line" >"$WORKDIR/one.pub"
  fp="$(ssh-keygen -lf "$WORKDIR/one.pub" | awk '{print $2}')"
  typ="$(ssh-keygen -lf "$WORKDIR/one.pub" | awk '{print $NF}' | tr -d '()')"
  if [ "$fp" = "$EXPECT" ]; then
    log "MATCH" "$typ  $fp   ← ★★★★ 與交機表相符"
    MATCH_LINE="$line"; MATCH_TYPE="$typ"
  else
    log "----" "$typ  $fp"
  fi
done <"$WORKDIR/keys.txt"

if [ -z "$MATCH_LINE" ]; then
  cp -p "$WORKDIR/keys.txt" "/tmp/${PROG}-mismatch-$$.txt"
  die "★★★★★ 沒有任何一把 host key 的指紋與預期相符！
        預期：$EXPECT
        實收：見上方 ---- 各行
        對方提供的原始 key 已存到 /tmp/${PROG}-mismatch-$$.txt 供調查

        ★★★★★ 在確認原因之前【不要】重試、【不要】輸入密碼。三個查法：
          【1】查變更單：這台最近有沒有重灌／重建／從快照還原
          【2】用帶外管道（iDRAC/PVE console）重新取一次指紋，跟交機表核對
          【3】確認 IP 沒有被 DHCP 重新指派給別台：ip neigh show $HOST
        以上都排除，仍不符 → 依資安事件流程通報，保留本檔案作為證據"
fi

# ---------- 【5】備份並寫入 known_hosts ----------
step "【5】寫入 known_hosts（先備份）"
BACKUP="${KNOWN_HOSTS}.bak.$(date +%Y%m%d%H%M%S)"
cp -p -- "$KNOWN_HOSTS" "$BACKUP"
log "OK" "已備份到 $BACKUP"
printf '%s\n' "$MATCH_LINE" >>"$KNOWN_HOSTS"
log "OK" "已寫入 $MATCH_TYPE host key"

# ---------- 【6】實地驗證 ----------
step "【6】實地驗證（StrictHostKeyChecking=yes）"
set +e
ssh -p "$PORT" \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$KNOWN_HOSTS" \
    -o ConnectTimeout=10 \
    -o PreferredAuthentications=publickey \
    -- "$HOST" true 2>"$WORKDIR/verify.err"
set -e

if grep -qi 'Host key verification failed' "$WORKDIR/verify.err"; then
  rollback
  die "★★★★★ 寫入後主機驗證仍然失敗，已回滾 known_hosts
        $(cat "$WORKDIR/verify.err")"
fi
# ★★★★ 能走到「使用者認證被拒」代表階段①～④全部成功，這正是本腳本要驗證的範圍
if grep -qiE 'Permission denied|No supported authentication' "$WORKDIR/verify.err"; then
  log "OK" "主機驗證通過（使用者認證尚未設定，屬預期 —— 見 02-SSH-金鑰認證與ssh-agent）"
else
  log "OK" "主機驗證通過，且已可用金鑰登入"
fi

# ---------- 【7】結果 ----------
step "【7】完成"
ssh-keygen -f "$KNOWN_HOSTS" -lF "$HOSTSPEC"
cat <<EOF

★★★ 後續動作：
  · 把「已完成第一次連線驗證」與日期填回交機表
  · 回滾方式：cp -p '$BACKUP' '$KNOWN_HOSTS'
             或 ssh-keygen -f '$KNOWN_HOSTS' -R '$HOSTSPEC'
  · 下一步做金鑰認證與停用密碼登入
EOF
SCRIPT
```

### 步驟二執行結果

**（a）指紋相符（正常情況）**：

```bash
ssh-first-connect 192.168.20.31 22 SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs
```

預期輸出：

```text
=== 【0】參數檢查 ===
[ OK   ] 主機=192.168.20.31 埠=22 known_hosts=/home/sysadm/.ssh/known_hosts

=== 【1】檢查 known_hosts 既有記錄 ===
[ OK   ] known_hosts 尚無 192.168.20.31 的記錄

=== 【2】TCP 埠連通測試（階段①） ===
[ OK   ] 192.168.20.31:22 可連線

=== 【3】取得對方提供的 host key（ssh-keyscan） ===
[ OK   ] 取得 3 把 host key

=== 【4】比對指紋（★★★★★ 這是整個流程的核心） ===
[ ---- ] RSA      SHA256:M9pX2vC5nB8kL1jH4gF7dS0aQ3wE6rT9yU2iO5pA8sD
[ ---- ] ECDSA    SHA256:Z1xW4vU7tS0rQ3pO6nM9lK2jI5hG8fE1dC4bA7zY0xQ
[ MATCH] ED25519  SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs   ← ★★★★ 與交機表相符

=== 【5】寫入 known_hosts（先備份） ===
[ OK   ] 已備份到 /home/sysadm/.ssh/known_hosts.bak.20260828101533
[ OK   ] 已寫入 ED25519 host key

=== 【6】實地驗證（StrictHostKeyChecking=yes） ===
[ OK   ] 主機驗證通過（使用者認證尚未設定，屬預期 —— 見 02-SSH-金鑰認證與ssh-agent）

=== 【7】完成 ===
# Host 192.168.20.31 found: line 15
192.168.20.31 SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs
...
```

```bash
echo "exit=$?"
```

```text
exit=0
```

**（b）★★★★★ 指紋不符（要的就是這個行為）**：

```bash
ssh-first-connect 192.168.20.31 22 SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs
```

```text
=== 【4】比對指紋（★★★★★ 這是整個流程的核心） ===
[ ---- ] RSA      SHA256:M9pX2vC5nB8kL1jH4gF7dS0aQ3wE6rT9yU2iO5pA8sD
[ ---- ] ECDSA    SHA256:Z1xW4vU7tS0rQ3pO6nM9lK2jI5hG8fE1dC4bA7zY0xQ
[ ---- ] ED25519  SHA256:7bQvL2xR9dK4mN8sT0uY3wZ6cA1eG5hJ2kP4nX7rV9M

[FAIL] ★★★★★ 沒有任何一把 host key 的指紋與預期相符！
        預期：SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs
        實收：見上方 ---- 各行
        對方提供的原始 key 已存到 /tmp/ssh-first-connect-mismatch-31204.txt 供調查
        ...
```

★★★★ 注意此時 **`known_hosts` 完全沒有被動過** —— 沒有備份、沒有寫入、沒有殘留。

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 | 重要度 |
| --- | --- | --- | --- | --- |
| 1 | 交機表已記錄三種指紋 | 目視交機表 | 三欄都有值且註明取得管道 | ★★★★ |
| 2 | 指紋確實從帶外取得 | 目視交機表「取得方式」 | ★★★★ 寫的是 iDRAC／PVE console，**不是 ssh-keyscan** | ★★★★★ |
| 3 | sshd 在監聽 | `ss -ltnp \| grep :22` | `LISTEN ... users:(("systemd",...))` | ★★★ |
| 4 | 埠通 | `nc -zv 192.168.20.31 22` | `succeeded!` | ★★★ |
| 5 | 對方版本符合預期 | `ssh -V` 與遠端 banner | `OpenSSH_9.6p1` | ★★ |
| 6 | 第一次連線腳本通過 | `ssh-first-connect ...` | `exit=0`，出現 `[ MATCH]` | ★★★★★ |
| 7 | known_hosts 有正確記錄 | `ssh-keygen -lF 192.168.20.31` | 指紋等於交機表的 ED25519 值 | ★★★★ |
| 8 | 嚴格模式下連得上 | `ssh -o StrictHostKeyChecking=yes -o BatchMode=yes sysadm@192.168.20.31 true` | ★★★ 不出現 `Host key verification failed` | ★★★★ |
| 9 | 遠端指令的 exit code 正確傳回 | `ssh sysadm@srv-web01 'exit 7'; echo $?` | `7`（不是 255） | ★★★ |
| 10 | 帶外管道可用 | 實際登入一次 iDRAC | ★★★★ 能開虛擬主控台並看到登入畫面 | ★★★★★ |
| 11 | 主機時間正確 | `ssh sysadm@srv-web01 timedatectl` | `System clock synchronized: yes`（見 [[28-時間同步NTP與chrony]]） | ★★★ |
| 12 | 登入紀錄有進日誌 | `journalctl -u 'ssh@*' -n 5` | 看得到 `Accepted ...` | ★★★ |

### 回滾

```bash
# ★★★ 回到寫入前的狀態（腳本會印出實際的備份檔名）
cp -p ~/.ssh/known_hosts.bak.20260828101533 ~/.ssh/known_hosts
# ★★ 或只移除這一台
ssh-keygen -R 192.168.20.31
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!` | 主機重建／IP 換機器／LB 後端不同／**真的被 MITM** | **先跑決策樹分流**，用帶外管道取指紋比對；相符才 `ssh-keygen -R`。★★★★★ 禁止反射性刪除 |
| ★★★★ `no matching host key type found. Their offer: ssh-rsa` | OpenSSH 8.8+ 預設停用 SHA-1 簽章，對方設備太舊 | 單次加 `-o HostKeyAlgorithms=+ssh-rsa`；長期排設備汰換或韌體升級 |
| ★★★★ `Permission denied (publickey).` | ①～④ 全通，**問題純在使用者認證** | 看 `ssh -v` 的 `Authentications that can continue`；伺服器端看 `journalctl -u ssh`。詳見 [[02-SSH-金鑰認證與ssh-agent]] |
| ★★★★ 改完 `sshd_config` 重啟後所有人連不上 | 語法錯或設定把自己擋掉，且**沒有留既有連線** | ★★★★ 重啟前一定先 `sshd -t`；用 console 還原 `sshd_config.bak` |
| ★★★★ 改了 `sshd_config` 的 `Port` 完全沒生效 | Ubuntu 22.10+ 走 **socket activation**，`Port` 被忽略 | `systemctl edit ssh.socket` 改 `ListenStream=`（第一行要留空清預設） |
| ★★★ `Connection refused` | 埠上沒有程序在聽：sshd 沒跑、埠改過、連錯 IP | 到主機 `ss -ltnp \| grep :22`；`systemctl status ssh ssh.socket` |
| ★★★ `Connection timed out` | 封包被靜默丟棄：防火牆 DROP、路由不通、機器沒開 | `nc -zv`、`ping`、查 ufw/firewalld/資安設備；必要時 [[01-tcpdump-基礎抓包]] |
| ★★★ `kex_exchange_identification: read: Connection reset by peer` | TCP 通了但立刻被踢：fail2ban 封鎖、`MaxStartups` 滿、IPS 阻擋 | 伺服器 `sudo fail2ban-client status sshd`；看 `journalctl -u ssh` 有無 `Connection closed by ... [preauth]` |
| ★★★ `Host key verification failed.` 但沒有 CHANGED 警告 | `StrictHostKeyChecking=yes` 且 known_hosts 沒這台；或 `BatchMode=yes` 不能互動提問 | 先用本篇腳本完成帶外驗證再登記；★★★★★ 不要改成 `no` 繞過 |
| ★★★ 連線卡住五到十秒才出現密碼提示 | 伺服器對客戶端 IP 做**反向 DNS 查詢逾時**，或 GSSAPI 認證嘗試逾時 | 伺服器 `UseDNS no`；客戶端 `-o GSSAPIAuthentication=no`（設定值見 [[04-sshd-伺服器端設定]]） |
| ★★★ `Bad owner or permissions on /home/xxx/.ssh/config` | 設定檔權限太寬或擁有者不對 | `chmod 600 ~/.ssh/config; chown $USER ~/.ssh/config`；`~/.ssh` 要 700 |
| ★★★ `sudo: a terminal is required to read the password` | 非互動模式沒有 tty，`sudo` 問不了密碼 | 加 `-t`；或改用 NOPASSWD 的專用維運帳號（最小權限） |
| ★★★ 遠端指令失敗但腳本判斷成功／反之 | 沒有分辨 `255`（ssh 自己失敗）與其他碼（遠端指令失敗） | 腳本一律 `rc=$?; if (( rc == 255 )); then …連線問題…` |
| ★★★ `client_loop: send disconnect: Broken pipe` 閒置後斷線 | 中間 NAT／防火牆的連線表逾時清掉了閒置連線 | 客戶端 `ServerAliveInterval 60`／伺服器 `ClientAliveInterval`（見 [[03-SSH-客戶端設定檔]]） |
| ★★★ `Too many authentication failures` | ssh-agent 裡金鑰太多，還沒輪到對的就超過 `MaxAuthTries` | `-o IdentitiesOnly=yes -i ~/.ssh/指定金鑰`；`ssh-add -D` 清空 agent |
| ★★ `Warning: Permanently added 'x' to the list of known hosts.` | ★★★ 不是錯誤 —— 但代表**這次是無驗證接受**（`accept-new`／`no`） | 檢查是誰設的；正式環境改回 `ask` 或 `yes` |
| ★★ 中文變成 `?` 或 `\x` 亂碼 | 終端機模擬器編碼不是 UTF-8，或伺服器缺 locale | 客戶端改 UTF-8；伺服器 `locale-gen zh_TW.UTF-8` |
| ★★ `vim`／`top` 畫面破碎、方向鍵變亂碼 | 遠端沒有你 `TERM` 對應的 terminfo | `TERM=xterm ssh ...`；或在遠端裝 `ncurses-term` |

### 排查步驟

**★★★★ 【1】名稱解析與 TCP 連通**

```bash
getent hosts srv-web01 && nc -zv 192.168.20.31 22
```

```text
192.168.20.31   srv-web01.example.gov.tw srv-web01
Connection to 192.168.20.31 22 port [tcp/ssh] succeeded!
```

- `getent` 無輸出 → ★★★ DNS／`/etc/hosts` 的問題，**跟 SSH 無關**，先修名稱解析
- `succeeded!` → 階段 ① 過關，跳到【3】
- `Connection refused`（立刻回） → 到【2】的服務面
- 卡住到逾時 → 到【2】的防火牆面

**★★★ 【2】區分「服務沒跑」與「被擋掉」**（在主機端／console 上做）

```bash
systemctl status ssh ssh.socket --no-pager | grep -E 'Active|Listen'
```

```text
     Active: active (listening) since Thu 2026-08-28 08:01:12 CST; 2h 21min ago
     Listen: [::]:22 (Stream)        # ★★★★ 確認實際聽的是哪個埠
     Active: inactive (dead)         # ★★★ ssh.service 在 socket activation 下是正常的
```

- `active (listening)` 卻連不上 → **是防火牆**：`sudo ufw status verbose`，
  確認 `22/tcp ALLOW IN 192.168.20.0/24` 有涵蓋你的來源網段（見 [[02-防火牆-ufw基礎與實務]]）
- `ss -ltnp` 看不到 22 → ★★★ 服務真的沒跑，`sudo systemctl start ssh.socket`

**★★★★ 【3】用 `ssh -v` 定位卡在第幾階段**

```bash
ssh -v sysadm@srv-web01 2>&1 | grep -E 'Connecting to|Connection established|Server host key|is known|Authentications that can continue'
```

四種典型結果：

```text
(a) 只有 Connecting to                     → ★★★  階段 ①（TCP 建不起來）
(b) 停在 Connection established.           → ★★★★ 階段 ②／③，看完整輸出的 no matching
(c) 有 Server host key 但沒有 is known     → ★★★★★ 階段 ④，去跑決策樹
(d) 出現 Authentications that can continue → ★★★  ①～④ 全過，只剩階段 ⑤
```

**★★★★ 【4】卡在階段 ③：問清楚對方到底會什麼**

```bash
ssh -v admin@10.0.30.5 2>&1 | grep -iE 'their offer|no matching'
ssh -G 10.0.30.5 | grep -i hostkeyalgorithms
```

```text
Unable to negotiate with 10.0.30.5 port 22: no matching host key type found. Their offer: ssh-rsa
hostkeyalgorithms ssh-ed25519-cert-v01@openssh.com,...,rsa-sha2-512,rsa-sha2-256
                                          # ★★★★ 自己的清單裡沒有 ssh-rsa → 難怪談不攏
```

`Their offer:` 後面就是**對方支援的全部清單**。解法見「OpenSSH 8.8+ 連老設備」。

**★★★★★ 【5】卡在階段 ④：分流，不要直接刪**

```bash
# 【5-1】現在收到的指紋（★★★ 只讀不登入，不會污染 known_hosts）
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -v srv-web01 2>&1 | grep 'Server host key'
# 【5-2】known_hosts 目前記的指紋
ssh-keygen -lF srv-web01
# 【5-3】★★★★ 到 console 取「真值」—— 這是唯一的判準
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

```text
debug1: Server host key: ssh-ed25519 SHA256:7bQvL2xR9dK4mN8sT0uY3wZ6cA1eG5hJ2kP4nX7rV9M
# Host srv-web01 found: line 14
srv-web01 SHA256:kV3mQ0Zc8pQ2rT1sXhN9dW7bLyF4uJ6aE0oG5PnRcIs
256 SHA256:7bQvL2xR9dK4mN8sT0uY3wZ6cA1eG5hJ2kP4nX7rV9M root@srv-web01 (ED25519)
```

- console 值 **等於【5-1】** → 主機真的換過 key（成因①），`-R` 之後重新登記
- console 值 **等於【5-2】** → ★★★★★ 有人在中間，**立刻停止並依資安事件流程通報**
- console 連不上、IP 上是別台機器 → 成因②，查 DHCP 租約與 `ip neigh show`

★★★★★ 【5-1】那條指令**只用來讀指紋，絕對不可以真的登入或輸入密碼**。

**★★★ 【6】卡在階段 ⑤：從伺服器端看**

```bash
sudo journalctl -u 'ssh@*' -u ssh --since '5 min ago' --no-pager | tail -n 20
```

```text
Aug 28 10:41:07 srv-web01 sshd[3312]: Connection closed by authenticating user sysadm 192.168.20.10 port 52210 [preauth]
Aug 28 10:41:15 srv-web01 sshd[3320]: Failed password for sysadm from 192.168.20.10 port 52216 ssh2
```

★★★ 一行都看不到 → 請求根本沒到 sshd，回到【2】。

**★★ 【7】排除自己的設定檔，必要時抓包**

```bash
ssh -F /dev/null -o StrictHostKeyChecking=ask sysadm@srv-web01
```

★★★ 這樣**就成功** → 問題確定在 `~/.ssh/config`，用 `ssh -G host` 比對最終有效值；
這樣**仍失敗** → 問題不在設定檔，最後手段是兩邊同時抓包（見 [[01-tcpdump-基礎抓包]]）：

```bash
sudo tcpdump -i any -nn 'tcp port 22 and host 192.168.20.10'
```

```text
10:52:31.204 IP 192.168.20.10.52288 > 192.168.20.31.22: Flags [S], seq 1024...
10:52:31.204 IP 192.168.20.31.22 > 192.168.20.10.52288: Flags [R.], seq 1, ack 1025...
                                                        # ★★★ 立刻 RST = 沒人聽或被 REJECT
```

---

## 安全性注意事項

> [!danger] 絕對禁止的六件事 ★★★★★
> **① ★★★★★ 看到 `HOST KEY CHANGED` 就直接 `ssh-keygen -R`**
> 後果：如果那真的是中間人，你剛剛把警報關掉、把攻擊者寫進信任清單，
> 然後把**密碼或金鑰的認證過程**送給他。所有後續連線都不會再有警告。
>
> **② ★★★★★ 在正式環境用 `StrictHostKeyChecking=no` 或 `UserKnownHostsFile=/dev/null` 登入**
> 後果：等於永久關閉主機驗證。CI/CD 腳本裡的這一行是機關最常見的高風險設定，
> 攻擊者只要能做 ARP 欺騙就能攔下整條部署管線與部署金鑰。
>
> **③ ★★★★★ 從 VM 範本 clone 出多台機器而不重新產生 host key**
> 後果：多台機器共用同一把主機私鑰，攻破一台就能**無警告地冒充其他所有台**。
> Clone 後必做：`sudo rm -f /etc/ssh/ssh_host_* && sudo ssh-keygen -A && sudo systemctl restart ssh`。
>
> **④ ★★★★ 把 `HostKeyAlgorithms=+ssh-rsa` 寫在 `Host *` 底下**
> 後果：為了一台老交換器，把**所有主機**的驗證強度降到 SHA-1。
> 一定要限定在該設備的 `Host` 區塊，並留註解說明原因與預計移除時間。
>
> **⑤ ★★★★ 改 `sshd_config` 時關掉唯一的連線**
> 後果：語法錯或規則寫錯 → sshd 起不來或把自己擋在外面 →
> 只能派人到機房。★★★★ 動手前先確認 IPMI／console **現在**能用，不是「應該能用」。
>
> **⑥ ★★★★★ 用 `ssh-keyscan` 的結果當作「已驗證」寫進交機表**
> 後果：整套驗證流程變成形式主義。`ssh-keyscan` 跟 `ssh` 走同一條路，
> 有中間人時兩邊拿到的都是中間人的 key，比對必然相符。

**機關情境的四個要點**：

| 項目 | 做法 | 重要度 |
| --- | --- | --- |
| ★★★★ 稽核軌跡 | SSH 登入成功／失敗都要進集中日誌（`journalctl -u ssh` → syslog → SIEM），保存期限依機關規定。見 [[09-日誌集中與SIEM]] | ★★★★ |
| ★★★★ 最小權限 | 不用 `root` 直連（`PermitRootLogin no`），用個人帳號登入後 `sudo`，**才有「誰做了什麼」的軌跡** | ★★★★ |
| ★★★★ 個資風險 | ★★★★ `ssh -vvv` 的輸出、`tcpdump` 的 pcap 可能含內部主機名與帳號，**送給廠商前要遮蔽**，不要貼到公開論壇 | ★★★★ |
| ★★★ TWGCB 對應 | 政府組態基準對 SSH 有明確要求（停用 root 登入、限制認證方式、閒置逾時等），逐項見 [[03-TWGCB-Linux項目分類詳解]] | ★★★ |

> [!warning] ★★★★ 不用 root 直連，不只是資安要求，也是排錯需求
> 三個人都用 `root` 登入，日誌上全部是 `Accepted ... for root`，
> 出事時**你無法知道是誰改的**。用個人帳號 + `sudo`，
> `journalctl -u ssh` 加上 `/var/log/auth.log` 的 sudo 紀錄才拼得出完整軌跡。
> 這在機關的事故調查與稽核裡是硬需求。

> [!tip] ★★★ 第一次連線之後立刻要做的三件事
> ① 建立金鑰認證並停用密碼登入 → [[02-SSH-金鑰認證與ssh-agent]]、[[04-sshd-伺服器端設定]]
> ② 建立第二個具 sudo 權限的維運帳號（★★★★ 唯一帳號被鎖就沒救了）
> ③ 套用初始安全基線 → [[01-伺服器初始安全設定]]

---

## 速查表

### ★★★★ 六階段 → 錯誤訊息 → 第一動作

| 階段 | 典型訊息 | 第一動作 | 重要度 |
| --- | --- | --- | --- |
| ① TCP | `Connection refused` | 主機上 `ss -ltnp \| grep :22` | ★★★ |
| ① TCP | `Connection timed out` | `nc -zv host 22`、查防火牆 | ★★★ |
| ② 版本 | `kex_exchange_identification: ... reset` | 查 fail2ban／`MaxStartups`／IPS | ★★★ |
| ③ KEX | `no matching host key type` | `ssh -V`、`ssh -G host \| grep hostkey` | ★★★★ |
| ④ 主機 | `HOST KEY CHANGED` | ★★★★★ **停手，跑決策樹** | ★★★★★ |
| ⑤ 使用者 | `Permission denied (publickey)` | `ssh -v` 看 `Authentications that can continue` | ★★★★ |
| ⑥ channel | `subsystem request failed` | 伺服器 `Subsystem sftp` 有沒有開 | ★★ |

### ★★★★ 指紋相關指令

| 指令 | 用途 | 重要度 |
| --- | --- | --- |
| `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` | ★★★★★ **在主機上**取得真值（帶外） | ★★★★★ |
| `for f in /etc/ssh/ssh_host_*.pub; do ssh-keygen -lf "$f"; done` | 一次列出所有型別，填交機表 | ★★★★ |
| `ssh-keygen -lvf <pub>` | 加印 randomart 圖形（★★ 輔助用） | ★★ |
| `ssh-keygen -lF <host>` | 查 known_hosts **已登記**的指紋 | ★★★★ |
| `ssh -o VisualHostKey=yes <host>` | 連線時同時顯示圖形 | ★★ |
| `ssh-keyscan -t ed25519 <host>` | ★★★ 抓 key **供自動化寫入**（★★★★ 不能當驗證） | ★★★ |

### ★★★★ known_hosts 操作

| 指令 | 用途 | 重要度 |
| --- | --- | --- |
| `ssh-keygen -F <host>` | 查詢（hash 過也查得到），沒找到 exit=1 | ★★★★ |
| `ssh-keygen -R <host>` | 刪除，★★★ 自動留 `known_hosts.old` | ★★★★ |
| `ssh-keygen -R '[host]:2222'` | ★★★ **非 22 埠**要用中括號格式 | ★★★ |
| `ssh-keygen -H -f ~/.ssh/known_hosts` | 把既有內容 hash 化 | ★★ |
| `ssh -o UserKnownHostsFile=/dev/null -v host` | ★★★ 只為了「看指紋」，**不要真的登入** | ★★★ |

### ★★★★ 檔案路徑

| 路徑 | 內容 | 權限 | 重要度 |
| --- | --- | --- | --- |
| `/etc/ssh/ssh_host_*_key` | ★★★★★ 主機**私**鑰 | `600 root:root` | ★★★★★ |
| `/etc/ssh/ssh_host_*_key.pub` | 主機公鑰（指紋來源） | `644` | ★★★★ |
| `~/.ssh/known_hosts` | 個人已信任的主機 | `600` | ★★★★ |
| `/etc/ssh/ssh_known_hosts` | ★★★★ 全機共用的信任清單 | `644 root:root` | ★★★★ |
| `~/.ssh/` | 目錄本身 | ★★★ `700`，太寬 ssh 會拒絕使用 | ★★★ |
| `/etc/ssh/ssh_config`、`ssh_config.d/` | 客戶端全機設定 | `644` | ★★★ |
| `/etc/systemd/system/ssh.socket.d/override.conf` | ★★★★ Ubuntu 改埠的**真正位置** | `644` | ★★★★ |

### ★★★ 相容性旗標（老設備）

| 症狀 | 旗標 | 風險 | 重要度 |
| --- | --- | --- | --- |
| `no matching host key type` | `-o HostKeyAlgorithms=+ssh-rsa` | ★★★★ 主機簽章降到 SHA-1 | ★★★★ |
| `Permission denied (publickey)`（老 server） | `-o PubkeyAcceptedAlgorithms=+ssh-rsa` | ★★★ 使用者簽章降到 SHA-1 | ★★★ |
| `no matching key exchange method` | `-o KexAlgorithms=+diffie-hellman-group14-sha1` | ★★★★★ 1024/2048-bit DH + SHA-1 | ★★★★ |
| `no matching cipher found` | `-o Ciphers=+aes128-cbc` | ★★★★ CBC 模式有已知弱點 | ★★★ |
| ★★★★ 通用注意 | `+` 是**加回**，`=` 是**整個換掉** | ★★★★ 寫成 `=` 會連現代主機都連不上 | ★★★★ |

### ★★★ 判斷準則速記

| 看到 | 就知道 | 重要度 |
| --- | --- | --- |
| `Connection established` | ★★★ 階段 ① 已通，別再查防火牆 | ★★★ |
| `Server host key:` | ★★★ 階段 ③ 已通，演算法談攏了 | ★★★ |
| `is known and matches` | ★★★★ 階段 ④ 已通，主機身分驗證成功 | ★★★★ |
| `Authentications that can continue:` | ★★★★ ①～④ 全通，問題只在帳號 | ★★★★ |
| `exit code 255` | ★★★★ **ssh 自己**失敗，遠端指令根本沒跑 | ★★★★ |
| `Permanently added` | ★★★ 這次是**無驗證**接受的 | ★★★ |
| `systemctl status ssh` 顯示 inactive 但連得上 | ★★★ Ubuntu socket activation，正常 | ★★★ |

---

## 練習題

> [!question]- 練習 1：把「六階段判讀」變成肌肉記憶
> 在測試機上刻意製造三種失敗，並用 `ssh -v` 確認自己判斷的階段正確：
> 1. 停掉 sshd（`sudo systemctl stop ssh.socket ssh.service`），從別台連 → 記下訊息與階段
> 2. 恢復服務，用 ufw 擋掉來源 IP（`sudo ufw deny from <你的IP> to any port 22`）→ 記下訊息與階段
> 3. 恢復防火牆，故意在客戶端指定不存在的演算法
>    （`ssh -o KexAlgorithms=diffie-hellman-group1-sha1 host`）→ 記下訊息與階段
>
> **參考解答**
> 1. **`Connection refused`，階段 ①**。★★★ 因為 TCP RST 是核心直接回的 —— 有機器、沒程序在聽。
>    `ssh -v` 只會停在 `debug1: Connecting to ...`，連 `Connection established.` 都不會出現。
> 2. **`Connection timed out`（約 2 分鐘後），階段 ①**。★★★ ufw 預設是 DROP 不是 REJECT，
>    所以客戶端得不到任何回應，只能等 TCP 重傳耗盡。
>    ★★★★ 「refused 立刻回、timeout 要等很久」是現場最快的區分方式。
> 3. **`Unable to negotiate ... no matching key exchange method found.`，階段 ③**。
>    ★★★ 會先看到 `Connection established.`，證明階段 ① 是通的 ——
>    這正是「錯誤訊息告訴你哪些階段已經成功」的實例。
>    收尾：`sudo ufw delete deny from <你的IP> to any port 22`、`sudo systemctl start ssh.socket`。

> [!question]- 練習 2：完整走一次帶外驗證流程
> 用一台 VM（PVE 或 VirtualBox 都可以）模擬交機：
> 1. 從 **VM console**（不是 SSH）取得三種 host key 的指紋，抄進一張表
> 2. 從另一台機器用 `ssh-first-connect` 完成第一次連線
> 3. 把 VM 的 host key 重新產生（`sudo rm -f /etc/ssh/ssh_host_* && sudo ssh-keygen -A && sudo systemctl restart ssh`）
> 4. 再連一次，觀察警告；用決策樹完成處置
>
> **參考解答**
> 第 2 步應該看到 `[ MATCH]` 與 `exit=0`。★★★★
> 第 4 步會看到 `REMOTE HOST IDENTIFICATION HAS CHANGED!` 與 `Offending ED25519 key in ...:NN`。
> **正確處置順序**：
> ① 這是**成因①（主機重建）**，因為你自己剛做的、有「變更紀錄」；
> ② 從 console 跑 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` 取新指紋；
> ③ 跟警告畫面上的 `The fingerprint for the ED25519 key sent by the remote host is` 逐字比對；
> ④ 相符才 `ssh-keygen -R <host>`（★★★ 注意它會留 `known_hosts.old`）；
> ⑤ 用新指紋重跑 `ssh-first-connect`。
> ★★★★ 重點是**你在第 ④ 步之前做了確認**。順序反過來（先刪再說）就是本篇最反對的做法。

> [!question]- 練習 3：驗證腳本真的會擋下錯誤的指紋
> 拿練習 2 的環境，故意把交機表上的指紋改掉一個字元，重跑 `ssh-first-connect`。
> 檢查三件事：① 有沒有中止；② `known_hosts` 有沒有被動到；③ exit code 是多少。
>
> **參考解答**
> ① ★★★★★ 應該在 `【4】比對指紋` 就中止，印出 `沒有任何一把 host key 的指紋與預期相符！`
>    並把實收的 key 存到 `/tmp/ssh-first-connect-mismatch-<pid>.txt`。
> ② ★★★★ `known_hosts` **完全沒被動過** —— 因為備份與寫入都在【5】，
>    而【4】的 `die` 讓流程根本走不到【5】。可以用
>    `md5sum ~/.ssh/known_hosts` 在執行前後比對確認（兩次應相同）。
> ③ exit code 是 **1**（`die` 用的是 `exit 1`）。★★★
> **延伸思考**：如果把比對邏輯改成「相符就寫、不符就警告後繼續」，
> 這支腳本的安全價值就歸零了 —— ★★★★★ **驗證失敗必須是硬中止，不能是可略過的警告**。
> 另外注意腳本在【1】就處理了「已有記錄但指紋不同」的情況，
> 它同樣是硬中止，不會自動覆蓋 —— 因為那正是 HOST KEY CHANGED 的情境。

---

## 小測驗

Q1. `ssh` 回傳 `Permission denied (publickey).`，這代表連線的**哪幾個階段已經成功**？接下來**不該**查什麼？

Q2. 你用 `ssh-keyscan` 抓到的指紋，跟 `ssh` 連線時螢幕顯示的指紋一模一樣。這能證明沒有中間人嗎？為什麼？

Q3. 看到 `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!`，請寫出**四種成因**與各自的辨別方法。

Q4. 這兩行的差別是什麼？各自在什麼情況下要用？
```bash
ssh -o HostKeyAlgorithms=+ssh-rsa host
ssh -o HostKeyAlgorithms=ssh-rsa host
```

Q5. 在 Ubuntu 24.04 上，你把 `/etc/ssh/sshd_config` 的 `Port` 改成 2222 並 `systemctl restart ssh`，結果 2222 連不上、22 還通。為什麼？怎麼改才對？

Q6. 一支批次腳本跑 `ssh "$h" 'systemctl is-active nginx'`，只用 `if [ $? -ne 0 ]` 判斷「服務異常」。這個寫法有什麼**嚴重缺陷**？

Q7. 是非題：把 VM 範本 clone 成十台伺服器之後，因為每台的 IP 和主機名都不同，SSH 的安全性不受影響。

Q8. `ssh -v` 的輸出裡出現了 `debug1: Connection established.` 但**沒有** `debug1: Server host key:`。問題在第幾階段？下一個該下什麼指令？

Q9. 為什麼 Debian/Ubuntu 預設 `HashKnownHosts yes`？這造成什麼不便？要查某台主機的記錄該用什麼指令？

Q10. 你要在正式環境的伺服器上改 `sshd_config` 的認證設定。請列出**動手前**必須完成的四道保險。

> [!question]- 測驗答案
> **Q1.** **階段 ①～④ 全部成功了。** ★★★★
> 能看到 `Permission denied` 代表 TCP 通（①）、版本相容（②）、演算法談攏（③）、
> **主機身分驗證通過**（④）—— `known_hosts` 裡的 key 與對方送來的簽章相符。
> 問題**只在階段 ⑤ 使用者認證**。
> **不該再查**：防火牆、路由、`ss -ltnp`、`nc -zv`、host key 指紋、演算法相容性 ——
> 這些已經被這行訊息證明沒問題了。跑去查防火牆是浪費半小時的典型。
> **該做的**：`ssh -v` 看 `Authentications that can continue:` 知道伺服器接受哪些方式，
> 再到伺服器 `sudo journalctl -u ssh -n 30`（常見是
> `Authentication refused: bad ownership or modes for directory /home/xxx/.ssh`）。
> 見「`ssh -v` 的三段式判讀」與 [[02-SSH-金鑰認證與ssh-agent]]。
>
> **Q2.** **不能證明。** ★★★★★
> `ssh-keyscan` 和 `ssh` **走完全相同的一條網路路徑**。路徑上若有中間人，
> 兩者拿到的都是**中間人的 host key** —— 同一個假貨比對自己，當然相符。
> 這等於「用嫌犯的證詞證明嫌犯清白」。
> **唯一有效的是帶外（out-of-band）管道**：IPMI／iDRAC／iLO 虛擬主控台、
> PVE／VMware console、實體 KVM，或建置當下由可信人員簽章的交機文件。在主機上執行：
> ```bash
> ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
> ```
> `ssh-keyscan` 的正當用途只有兩個：把**已經**帶外驗證過的指紋自動化寫入 known_hosts，
> 以及盤點現況跟資產表對帳。見「觀念說明」的 TOFU 段。
>
> **Q3.** 四種成因與辨別方法：★★★★★
> ① **主機重建**（重灌、重建 VM、還原快照、重跑 `ssh-keygen -A`）——
>    查**變更單／建置紀錄**，並到 console 跑 `ssh-keygen -lf` 取新指紋比對。
> ② **同一個 IP 換成另一台機器**（DHCP 重派、NAT 對應改了）——
>    `ip neigh show <ip>` 看 MAC 有沒有變、查 DHCP 租約表。
>    ★★★ 長期解法是改用主機名或固定 IP，別拿 DHCP 位址當識別。
> ③ **負載平衡／VIP 後面多台機器** —— 連續連幾次，指紋在**固定幾個值之間輪替**就是這種。
>    解法：後端共用同一組 host key、全部登記、或改用 SSH CA。
> ④ **真的被中間人攻擊** —— 前三種都排除，且**帶外指紋與畫面顯示不符**。
>    ★★★★★ 不要重試、不要輸入密碼、不要 `-R`；保留 `known_hosts` 與 `ssh -vvv` 輸出並通報。
>
> **Q4.** ★★★★ 差在 `+` 這個字元，後果差很大。
> - `+ssh-rsa`：**把 `ssh-rsa` 加回預設清單的尾端**，其他現代演算法全部保留，
>   連現代主機一樣正常。
> - `=ssh-rsa`（沒有加號）：**整個清單換成只剩 `ssh-rsa`**。★★★★
>   之後連到只提供 Ed25519 的現代主機會直接 `no matching host key type found`，
>   而且錯誤訊息長得一模一樣，很容易誤以為是對方的問題，一路查錯方向。
> **使用時機**：連 OpenSSH 7.x 以前的老交換器／老 NAS 出現
> `no matching host key type found. Their offer: ssh-rsa` 時用 `+ssh-rsa`，
> ★★★★ 而且要寫在該設備專屬的 `Host` 區塊，**不可以寫在 `Host *`**。
> 另有 `-`（移除某項）與 `^`（插到最前面）兩種前綴。
>
> **Q5.** 因為 **Ubuntu 22.10 起 sshd 走 systemd socket activation**。★★★★
> 監聽 22 的是 `ssh.socket`（實際持有 socket 的是 pid 1 的 systemd），
> sshd 是連線進來才被叫起來的 —— 此時 **`sshd_config` 的 `Port` 與 `ListenAddress` 會被忽略**。
> 確認：`systemctl is-enabled ssh.socket` 回 `enabled`、`ss -ltnp | grep :22` 顯示 `systemd`。
> 正確改法：
> ```bash
> sudo systemctl edit ssh.socket        # [Socket] / ListenStream= / ListenStream=2222
> sudo systemctl daemon-reload && sudo systemctl restart ssh.socket
> ```
> ★★★★ 第一行**空的** `ListenStream=` 不能省 —— 它的作用是清掉預設的 22，
> 漏掉會變成 22 和 2222 同時聽。改埠前記得先開防火牆（RHEL 還要 `semanage port`），
> 並**保留既有連線**。
>
> **Q6.** 缺陷是**沒有區分 `255` 與其他 exit code**。★★★★
> `ssh` 的回傳規則：遠端指令有跑到 → 回傳**遠端指令自己的碼**；
> `ssh` 自己失敗（連不上／認證失敗／host key 不符）→ 一律回 **255**。
> 所以「機器連不上」與「nginx 真的掛了」在 `$? -ne 0` 底下**完全無法區分** ——
> 一台網路中斷的機器會被判成「nginx 異常」，觸發錯誤的重啟或告警，
> 而真正的問題（網路）沒人處理。正確寫法：
> ```bash
> out="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$h" 'systemctl is-active nginx' 2>&1)"; rc=$?
> if (( rc == 255 )); then echo "[連線問題] $h: $out"
> elif (( rc != 0 )); then echo "[服務異常] $h: $out"; fi
> ```
> ★★ `BatchMode=yes` 讓它不會卡在密碼提示。見「非互動執行」段。
>
> **Q7.** **錯。** ★★★★★
> Clone 出來的十台**共用同一組 `/etc/ssh/ssh_host_*_key` 私鑰**，
> IP 和主機名不同完全不影響 —— 身分證明靠的是私鑰，不是 IP。後果：
> ① 攻破**任何一台**（或一次備份外洩）就取得那把私鑰，
>    之後可**完美冒充其餘九台**，客戶端 `known_hosts` **不會有任何警告**；
> ② ★★★ 因為十台指紋一樣，你連到 A 機時 known_hosts 也會對 B 機的記錄「相符」，
>    整批機器在信任層面變成同一台，出事時連辨識都做不到。
> 正確做法（★★★★ 寫進 VM 範本的 first-boot 腳本）：
> ```bash
> sudo rm -f /etc/ssh/ssh_host_* && sudo ssh-keygen -A && sudo systemctl restart ssh
> ```
> 做完所有客戶端都會跳 HOST KEY CHANGED，這是預期行為，要事先公告並登記新指紋。
>
> **Q8.** 問題在**階段 ② 或 ③**。★★★★
> `Connection established.` 證明 TCP 通了（① 過關）；沒有 `Server host key:`
> 代表**還沒走到主機認證**，卡在協定版本交換或演算法協商。
> 下一步（看完整訊息，不要只 grep）：`ssh -v host 2>&1 | tail -n 20`。三種典型結果：
> - `no matching host key type found. Their offer: ssh-rsa`
>   → ★★★★ 階段 ③，OpenSSH 8.8+ 對老設備，用 `-o HostKeyAlgorithms=+ssh-rsa`
> - `kex_exchange_identification: read: Connection reset by peer`
>   → ★★★ 階段 ②，被 fail2ban／IPS／`MaxStartups` 中途踢掉，去伺服器查
> - `Bad protocol version identification '...'`
>   → ★★★ 這個埠上根本不是 SSH（連錯服務或埠被別的程式佔用）
> 對照「排查步驟【3】」。
>
> **Q9.** ★★★ 目的是**防止橫向移動**。
> 攻擊者拿下跳板機或個人電腦後，第一件事往往是讀 `~/.ssh/known_hosts` ——
> 它等於一份「這個人平常連哪些機器」的清單，直接畫出整個機房的地圖。
> Hash 後檔案裡只剩 `|1|<salt>|<HMAC-SHA1>`，**看不出是哪台**。
> **不便**：不能再 `grep` 找記錄，也不能用肉眼盤點連過哪些機器。查詢要改用：
> ```bash
> ssh-keygen -F 192.168.20.31        # 印出該行與行號
> ssh-keygen -lF 192.168.20.31       # 加 -l 直接印指紋，比對交機表用
> ssh-keygen -R 192.168.20.31        # 刪除（會留 known_hosts.old）
> ```
> ★★★ 非 22 埠的記錄格式是 `[host]:port`，要寫成 `ssh-keygen -R '[192.168.20.31]:2222'`，
> 不然會找不到。★★ RHEL 系預設 `HashKnownHosts no`，可以直接 grep。
>
> **Q10.** 四道保險，缺一不可：★★★★
> ① **★★★★★ 保留一條既有的 SSH 連線不要關。** 重啟 sshd **不會斷掉已建立的連線**，
>    萬一新設定把自己擋在外面，這條舊連線是唯一還能改回來的通道。關掉它 = 自斷退路。
> ② **★★★★ 開第二個終端機測試新連線。** 舊視窗完全不動，連得上才收工。
> ③ **★★★★ 重啟前先做語法檢查與有效值確認**：
>    ```bash
>    sudo sshd -t                                       # 沒輸出 = 語法正確
>    sudo sshd -T | grep -iE 'permitrootlogin|passwordauthentication|allowusers'
>    ```
>    `-T` 印的是**所有設定套用後的最終有效值**，★★★ 避免「改了 `sshd_config`
>    卻被 `sshd_config.d/` 的檔案蓋掉」這種鬼打牆。
> ④ **★★★★★ 現在就實測帶外管道能用** —— IPMI／iDRAC 密碼現在登入一次、
>    console 現在開一次。很多人是被鎖在門外之後，才發現密碼三年前換過沒人記得。
> ★★★ 加分：改設定前用 `at now + 10 minutes` 掛自動還原排程，確認沒問題再 `atrm`。


---

## 延伸閱讀

- [[02-SSH-金鑰認證與ssh-agent]] —— 本篇之後的**必做下一步**：把密碼登入換成金鑰，
  以及 `Permission denied (publickey)` 的完整排查
- [[03-SSH-客戶端設定檔]] —— 把本篇用到的 `-o` 旗標固化成 `~/.ssh/config`，
  包含老設備的相容設定要怎麼**限定在單一 Host** 而不污染全域
- [[04-sshd-伺服器端設定]] —— 伺服器端的 `sshd_config`：改埠、限制來源、
  停用 root 登入，以及每一次改動的鎖門預防
- [[07-SSH-安全強化]] —— 演算法清單的建議值、`fail2ban`、雙因素，
  本篇提到的「暫時降級旗標」在這裡有長期解法
- [[23-Linux常見疑難排解]] —— 連不上時「網路 vs. 服務 vs. 權限」的通用分層排查法
- [[01-PKI與憑證基礎]] —— 對照 HTTPS 的 CA 信任模型，理解 SSH 為什麼要 TOFU、
  以及 SSH CA 能解決什麼
- [[03-ss-netstat-與lsof]] —— 確認 sshd 監聽狀態的完整用法，本篇只引用不重講
- [[01-scp與sftp傳輸]] —— 第一次連線建立信任之後的檔案傳輸，
  它們共用同一份 `known_hosts`

**官方文件**

- OpenSSH `ssh(1)` 手冊：<https://man.openbsd.org/ssh>
- OpenSSH `ssh_config(5)`（`StrictHostKeyChecking`、`HostKeyAlgorithms` 等選項）：<https://man.openbsd.org/ssh_config>
- OpenSSH `ssh-keyscan(1)`：<https://man.openbsd.org/ssh-keyscan>
- OpenSSH 8.8 release notes（ssh-rsa 停用的原始說明）：<https://www.openssh.com/txt/release-8.8>
- OpenSSH 全部版本的 release notes：<https://www.openssh.com/releasenotes.html>
