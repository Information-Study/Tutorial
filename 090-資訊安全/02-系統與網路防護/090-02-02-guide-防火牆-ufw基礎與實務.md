---
title: "ufw 基礎與實務"
desc: "Ubuntu 內建主機防火牆 ufw：預設政策、allow/deny/reject/limit、來源與介面限制、規則順序與 insert、應用設定檔、日誌判讀，以及 Docker 繞過 ufw 的坑與解法"
aliases: [ufw, firewall, ufw allow, ufw status numbered, ufw-docker]
tags: [群組/資訊安全, 安全/防火牆, 主題/網路]
category: 系統與網路防護
difficulty: 入門
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-01-16-cmd-Linux-網路基礎指令]]", "[[090-02-01-guide-防護-伺服器初始安全設定]]"]
updated: 2026-09-03
---

# ufw 基礎與實務

> [!abstract] 這篇你會學到
> - ★★★★★ **`ufw enable` 會立刻切斷你現在這條 SSH 連線** —— 除非你已經先放行 SSH。
>   本篇第一件事就是教你「先放行、再開牆、留第二條連線」的標準順序
> - ★★★★★ 從 `default deny incoming` 開始，一台 Nginx + MySQL 主機的**完整規則集**怎麼建、
>   建完怎麼從外部實測驗證
> - ★★★★ **規則是由上而下、第一個匹配勝出** —— 這是「規則明明加了卻沒作用」的頭號原因，
>   解法是 `ufw status numbered` 看順序、用 `ufw insert N` 插到正確位置
> - ★★★★ **Docker 會直接改 iptables，繞過 ufw** —— `-p 8080:80` 發布的埠
>   對全世界開放，`ufw status` 卻什麼都看不出來。這是機關最常踩的坑
> - ★★★ `allow` / `deny` / `reject` / `limit` 四個動作的差別，以及什麼時候該用哪個
> - ★★★ 來源限制（`from 192.168.10.0/24`）、介面限制（`in on ens192`）、
>   方向（`in` / `out`）、`ufw route` 轉發規則
> - ★★★ 應用設定檔 `/etc/ufw/applications.d/`：怎麼用現成的、怎麼寫自己的
> - ★★★ `ufw logging` 的四個等級、`/var/log/ufw.log` 每個欄位的意思，
>   以及怎麼從日誌反推「是誰被擋了」
> - 一份 20 列的速查表、15 列排錯表，以及把自己鎖在外面時的三種救援手段

> [!danger] ★★★★★ 動手前先讀這一段
> **在遠端主機上操作防火牆，隨時可能把自己鎖在門外。**
> 開始之前務必做到三件事：
> 1. 另外開一條 SSH 連線（第二個終端機視窗）並**保持不要關掉**，
>    它會維持在 established 狀態，通常不會被新規則切斷，是你的救命索。
> 2. 確認你有 **out-of-band 存取管道**：iDRAC／iLO／IPMI、
>    PVE 或 VMware 的主控台、雲端供應商的 Serial Console。
> 3. 先排好自動還原：`echo "ufw disable" | at now + 5 minutes`
>    （細節見本篇〈把自己鎖在外面時的三種救援〉）。
> 沒有以上任何一項就只有一條 SSH 的機器，**請排維護時段、到機房前面做**。

## 前置知識

- [[020-01-16-cmd-Linux-網路基礎指令]] —— `ss`、`ip`、`ping`、埠與協定的基本觀念
- [[090-02-01-guide-防護-伺服器初始安全設定]] —— 這篇是伺服器上線前 checklist 的一環
- [[020-02-01-04-svc-sshd-伺服器端設定]] —— SSH 埠若不是 22，本篇所有範例都要跟著改
- [[020-01-17-cmd-Linux-systemd服務管理]] —— `systemctl status ufw`、開機自啟
- [[020-01-19-guide-Linux-日誌系統]] —— journald 與 rsyslog，ufw 日誌會同時進這兩邊

搭配閱讀：

- [[090-02-03-guide-防火牆-nftables與iptables]] —— ufw 底下那一層。
  ufw 表達不出來的需求（複雜 NAT、大量 IP 集合、細緻速率限制）要跳下去寫
- [[090-02-04-guide-防火牆-firewalld]] —— RHEL／Rocky／AlmaLinux 系的對應工具，另有專篇
- [[090-02-05-guide-防護-Fail2ban入侵防護]] —— 動態封鎖暴力破解來源，ufw 是它的執行後端之一
- [[090-05-02-guide-資安設備-防火牆與次世代防火牆]] —— 邊界防火牆（設備）與主機防火牆的分工

## 觀念說明

### 為什麼主機防火牆不能省 ★★★★★

很多機關的說法是「我們外面有防火牆設備了，主機上不用再開一層」。這句話有三個漏洞：

```text
  網際網路
     │
  ┌──▼──────────────┐
  │ 邊界防火牆       │  ← 只管「進出機關」的流量
  │ (次世代 FW)      │
  └──┬──────────────┘
     │
  ┌──▼──────────────────────────────────────────┐
  │  內部網段 192.168.10.0/24                     │
  │                                              │
  │  ┌────────┐   ┌────────┐   ┌──────────────┐  │
  │  │ 員工 PC │──▶│ 印表機  │   │  你的伺服器   │  │
  │  │ 中毒了  │   └────────┘   │  ← 誰擋這條？ │  │
  │  └────────┘ ─────────────────▶              │  │
  │                              └──────────────┘  │
  └──────────────────────────────────────────────┘
```

| 漏洞 | 說明 | 主機防火牆怎麼補 |
| --- | --- | --- |
| ★★★★★ **橫向移動** | 邊界防火牆看不到內網東西向流量。一台中毒的 PC 打你的 MySQL 3306，邊界完全無感 | 主機上只放行必要來源網段 |
| ★★★★ **管理埠外洩** | 有人在邊界開了一條 NAT 給廠商，忘了收 | 主機層再擋一次，多一道保險 |
| ★★★★ **服務誤綁** | 開發人員把測試服務綁在 `0.0.0.0:9000`，自己不知道 | 預設拒絕，沒明確放行就進不來 |
| ★★★ **稽核要求** | TWGCB 與 ISMS 稽核都會查主機層防火牆狀態 | `ufw status verbose` 直接當佐證 |

> [!note] ★★★★ 縱深防禦（defense in depth）
> 主機防火牆不是要取代邊界設備，是要在邊界失守之後**限制災情範圍**。
> 假設攻擊者已經拿到內網一台機器，你的伺服器還能撐多久，就看主機防火牆設得多嚴。

### 為什麼先學 ufw ★★★★★

Linux 主機防火牆的工具堆疊長這樣：

```text
  ┌────────────────────────────────────────────────────────┐
  │  管理者輸入的指令                                        │
  │     ufw allow 80/tcp        ← 你在這一層（本篇）          │
  └────────────────────┬───────────────────────────────────┘
                       │ ufw 幫你翻譯
  ┌────────────────────▼───────────────────────────────────┐
  │  iptables 指令介面（Ubuntu 上其實是 iptables-nft 相容層） │
  │     iptables -A ufw-user-input -p tcp --dport 80 -j ACCEPT │
  └────────────────────┬───────────────────────────────────┘
                       │ 相容層再翻譯
  ┌────────────────────▼───────────────────────────────────┐
  │  nftables 規則集（現行後端，第 03 篇）                    │
  │     table ip filter { chain ufw-user-input { ... } }    │
  └────────────────────┬───────────────────────────────────┘
                       │
  ┌────────────────────▼───────────────────────────────────┐
  │  Linux kernel netfilter —— 真正在封包路徑上執行的地方     │
  └────────────────────────────────────────────────────────┘
```

選 ufw 當主線的四個理由：

| 理由 | 說明 |
| --- | --- |
| ★★★★★ **Ubuntu 內建** | `ufw` 套件在 Ubuntu Server 預設就裝好（只是沒啟用），不用另外找套件庫 |
| ★★★★★ **語法直觀** | `ufw allow from 192.168.10.0/24 to any port 3306 proto tcp` 唸出來就是規則本身，交接給下一個同事不用重新訓練 |
| ★★★★ **涵蓋九成需求** | 「開哪幾個埠、只給哪些來源」—— 機關伺服器的防火牆需求九成就是這一句 |
| ★★★ **不會寫壞** | ufw 自動處理 loopback、established/related、ICMP 這些**新手最容易漏掉的基礎規則**（放在 `before.rules`），你只要管業務埠 |

> [!tip] ★★★★ 什麼時候該放棄 ufw 跳到 nftables
> 當你的需求開始出現這些字眼，就代表 ufw 已經表達不出來了，請看
> [[090-02-03-guide-防火牆-nftables與iptables]]：
> - 「封鎖這 8 萬個惡意 IP」（要用 set，一條一條 `ufw deny` 會讓規則集爆掉）
> - 「這個埠每秒只准 20 個新連線」（細緻速率限制）
> - 「來自 A 網段走 NAT 到 B、來自 C 網段直接丟掉」（複雜 NAT／policy routing）
> - 「依連線狀態與封包標記分流」

### ufw 的四個動作 ★★★★

| 動作 | 行為 | 對方看到什麼 | 什麼時候用 |
| --- | --- | --- | --- |
| `allow` | 放行 | 正常連上 | ★★★★★ 正常業務埠 |
| `deny` | 靜默丟棄（DROP） | 連線逾時（timeout），大約 30～120 秒才失敗 | ★★★★ **對外網一律用這個**，讓掃描者浪費時間、也不確認主機是否存在 |
| `reject` | 明確拒絕（REJECT），回 ICMP port-unreachable 或 TCP RST | 立刻「Connection refused」 | ★★★ **對內網用**，讓自己人的程式立刻失敗而不是卡住逾時 |
| `limit` | 放行但限速：同一來源 IP **30 秒內超過 6 次新連線就丟棄** | 前幾次正常，之後逾時 | ★★★★ SSH、SMTP 等會被暴力破解的埠 |

> [!warning] ★★★ `limit` 的細節與限制
> `ufw limit` 底層用的是 iptables 的 `recent` 模組，硬編碼是 **6 次 / 30 秒**，
> **ufw 沒有提供指令去改這個數字**。要改就得手動編 `/etc/ufw/before.rules`，
> 或改用 [[090-02-05-guide-防護-Fail2ban入侵防護]] 做動態封鎖。
> 另外 `limit` **只支援 IPv4 的 recent 追蹤在部分舊版有差異**，
> 而且 `limit` 對已建立的連線無效 —— 它只算「新連線」。

### 預設政策：一切從拒絕開始 ★★★★★

```text
  封包進來
     │
     ▼
  ┌──────────────────────────────────────┐
  │ before.rules（ufw 內建，你通常不用改） │
  │  · loopback (lo) 一律放行              │
  │  · ESTABLISHED,RELATED 一律放行 ★★★★★  │
  │  · 無效封包（INVALID）丟棄             │
  │  · 部分 ICMP 放行（echo-request 等）   │
  │  · DHCP client 回應放行                │
  └──────────────┬───────────────────────┘
                 │ 沒被上面處理掉的
                 ▼
  ┌──────────────────────────────────────┐
  │ user.rules —— 你用 ufw allow 加的規則   │
  │  由上而下，★★★★ 第一個匹配就決定命運    │
  └──────────────┬───────────────────────┘
                 │ 全部都沒匹配到
                 ▼
  ┌──────────────────────────────────────┐
  │ after.rules ＋ 預設政策                │
  │  default deny incoming → 丟掉          │
  └──────────────────────────────────────┘
```

★★★★★ **`ESTABLISHED,RELATED` 放行是整件事能運作的關鍵。**
因為有這條，你的伺服器可以 `apt update`（對外發出的連線，回應算 established 而被放行），
你的 SSH 連線也不會因為你新增規則就斷掉。
初學者自己手寫 iptables 最常見的災難就是漏了這一條，結果連 DNS 查詢都回不來。

### 規則順序：第一個匹配勝出 ★★★★

這是本篇最重要的觀念之一，也是「規則加了卻沒作用」的頭號原因。

```text
  ufw 規則清單（由上而下掃描）

  [1] 3306/tcp        DENY IN    Anywhere        ← 先擋所有人
  [2] 3306/tcp        ALLOW IN   192.168.10.50   ← 這條永遠不會被執行！

                              封包 SRC=192.168.10.50 DPT=3306
                                       │
                                       ▼
                              [1] 匹配 → DENY，結束
                              [2] 根本沒機會看
```

`ufw allow` / `ufw deny` **一律把新規則加在清單最後面**。
所以「先加了寬鬆的拒絕、後來才想開特例」就必然踩坑。
解法是 `ufw insert N`，把特例插到拒絕規則的前面：

```bash
sudo ufw insert 1 allow from 192.168.10.50 to any port 3306 proto tcp
```

> [!tip] ★★★★ 實務上的規則排序原則
> 1. 最上面放**最具體的例外**（單一 IP 的管理存取）
> 2. 中間放**一般業務規則**（80／443 對全世界）
> 3. 最下面放**廣泛的拒絕**（整個網段封鎖）
> 4. 真正的 catch-all 交給預設政策 `default deny incoming`，不要自己寫

## 環境準備與安裝

### 檢查 ufw 是否已安裝 ★★★

```bash
dpkg -l ufw | tail -n 3
```

```text
Desired=Unknown/Install/Remove/Purge/Hold
| Status=Not/Inst/Conf-files/Unpacked/halF-conf/Half-inst/trig-aWait/Trig-pend
|/ Err?=(none)/Reinst-required/Uppercase=bad)
||/ Name           Version      Architecture Description
+++-==============-============-============-=================================
ii  ufw            0.36.2-6     all          program for managing a Netfilter firewall
```

沒有的話（極精簡的容器映像或 netinst 安裝可能沒有）：

```bash
sudo apt update
sudo apt install -y ufw
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> RHEL 系預設是 **firewalld**，不是 ufw。EPEL 雖然有 ufw 套件，
> **但不建議在 RHEL 系硬裝 ufw** —— 會跟 firewalld 搶同一組 netfilter 規則，
> 而且 RHEL 的支援與稽核工具（openscap、TWGCB 基準）都是針對 firewalld 寫的。
> RHEL 系請直接看 [[090-02-04-guide-防火牆-firewalld]]。
>
> 對照速查（本篇 ufw 指令 → firewalld）：
> | ufw | firewalld |
> | --- | --- |
> | `ufw enable` | `systemctl enable --now firewalld` |
> | `ufw status verbose` | `firewall-cmd --list-all` |
> | `ufw allow 80/tcp` | `firewall-cmd --permanent --add-port=80/tcp && firewall-cmd --reload` |
> | `ufw allow from 192.168.10.0/24` | `firewall-cmd --permanent --add-source=192.168.10.0/24 --zone=trusted` |
> | `ufw reload` | `firewall-cmd --reload` |

### 確認當前狀態（還沒啟用時） ★★★

```bash
sudo ufw status verbose
```

```text
Status: inactive
```

★★★ **`Status: inactive` 代表 ufw 完全沒在管事**，不代表主機沒有防火牆規則 ——
Docker 或別的工具可能已經寫了 iptables 規則。用第 03 篇的方法確認：

```bash
sudo iptables -S | head -n 20
```

### ★★★★★ 啟用前的四步準備

> [!danger] ★★★★★ `ufw enable` 會立刻切斷現有 SSH 連線
> `ufw` 的預設政策是 `deny incoming`。如果你在 **還沒放行 SSH** 的情況下執行
> `ufw enable`，防火牆立刻生效、22 埠被擋，**你這條 SSH 連線當場斷掉，而且連不回來**。
> 更麻煩的是：ufw 是開機自啟的，重開機也救不了你。
>
> **正確順序永遠是：先 allow，再 enable。**

**步驟 1：確認 SSH 服務實際監聽的埠** ★★★★★

不要憑印象，直接查：

```bash
sudo ss -tlnp | grep -i ssh
```

```text
LISTEN 0      128          0.0.0.0:22        0.0.0.0:*    users:(("sshd",pid=812,fd=3))
LISTEN 0      128             [::]:22           [::]:*    users:(("sshd",pid=812,fd=4))
```

如果 sshd 被改到非標準埠（例如 2222），下面所有 `OpenSSH` 都要換成 `2222/tcp`。

**步驟 2：放行 SSH** ★★★★★

```bash
sudo ufw allow OpenSSH
```

```text
Rules updated
Rules updated (v6)
```

★★★★ 如果 SSH 不是 22 埠：

```bash
sudo ufw allow 2222/tcp comment 'SSH (custom port)'
```

**步驟 3：確認規則真的加進去了（enable 之前！）** ★★★★★

```bash
sudo ufw show added
```

```text
Added user rules (see 'ufw status' for running firewall):
ufw allow OpenSSH
```

★★★★★ **這一步不能跳過。** `ufw show added` 顯示的是「已加入但可能尚未生效」的規則，
是 enable 之前唯一能確認自己不會被鎖在外面的方法。

**步驟 4：排好自動救援，再開另一條連線** ★★★★★

```bash
# 5 分鐘後自動關閉防火牆（沒有 at 的話先 apt install -y at）
echo "/usr/sbin/ufw --force disable" | sudo at now + 5 minutes
```

```text
warning: commands will be executed using /bin/sh
job 3 at Wed Sep  3 10:35:00 2026
```

然後**另外開一個終端機視窗**連進同一台主機，保持不要關。

### 啟用 ufw ★★★★★

```bash
sudo ufw enable
```

```text
Command may disrupt existing ssh connections. Proceed with operation (y|n)? y
Firewall is active and enabled on system startup
```

★★★★ 那句 `Command may disrupt existing ssh connections` **是真的會發生**，
不是罐頭警語。看到它請先深呼吸，回頭確認步驟 3 的輸出裡有 SSH。

驗證：

```bash
sudo ufw status verbose
```

```text
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp (OpenSSH)           ALLOW IN    Anywhere
22/tcp (OpenSSH (v6))      ALLOW IN    Anywhere (v6)
```

確認沒事之後，**記得把自動救援的 at job 取消**，否則 5 分鐘後防火牆會自己關掉：

```bash
atq
```

```text
3	Wed Sep  3 10:35:00 2026 a root
```

```bash
sudo atrm 3
```

### 開機自啟與服務狀態 ★★★

```bash
systemctl is-enabled ufw
```

```text
enabled
```

★★★ **`ufw enable` 已經包含了 `systemctl enable ufw`**，不用再手動做一次。
反過來說，`ufw disable` 也會把開機自啟關掉。

> [!warning] ★★★ `systemctl stop ufw` 不等於 `ufw disable`
> `ufw.service` 只是開機時把規則載入 netfilter 的 oneshot 單元。
> `systemctl stop ufw` 會清掉規則，但 `/etc/ufw/ufw.conf` 裡的 `ENABLED=yes` 還在，
> 下次開機規則又回來，而 `ufw status` 中間這段時間顯示的東西可能誤導人。
> **要關防火牆一律用 `ufw disable`。**

## 基礎設定

### 設定預設政策 ★★★★★

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw default deny routed
```

```text
Default incoming policy changed to 'deny'
(be sure to update your rules accordingly)
Default outgoing policy changed to 'allow'
(be sure to update your rules accordingly)
Default routed policy changed to 'deny'
(be sure to update your rules accordingly)
```

| 方向 | 建議值 | 理由 |
| --- | --- | --- |
| `incoming` | ★★★★★ `deny` | 沒明確放行就進不來，這是整套設計的基礎 |
| `outgoing` | ★★★★ `allow` | 對外全開。改成 `deny` 會擋掉 DNS、apt、NTP、監控回報，除非你有明確的出向管制政策，否則不要動 |
| `routed` | ★★★★ `deny` | 這台不是路由器就該關。是 Docker 主機或 NAT 閘道才需要 `allow` |

> [!danger] ★★★★★ `ufw default deny outgoing` 是遠端管理的第二大殺手
> 出向全擋之後，DNS（53）、NTP（123）、apt（80/443）全部斷。
> 你的 SSH 連線因為是 established 不會馬上斷，但主機會慢慢「壞掉」：
> 解析不到網域、憑證驗不了、監控回報不出去。
> **真的要做出向管制，請先把 DNS、NTP、apt mirror、監控伺服器逐條 `ufw allow out` 放行，
> 並且全程在第二條連線與 at 自動還原的保護下操作。**

### 最常用的六種規則寫法 ★★★★★

```bash
# ① 依埠號與協定（最常用）
sudo ufw allow 80/tcp

# ② 依應用設定檔名稱
sudo ufw allow 'Nginx Full'

# ③ 限制來源網段（★★★★★ 管理埠與資料庫埠必用）
sudo ufw allow from 192.168.10.0/24 to any port 3306 proto tcp

# ④ 限制單一來源 IP
sudo ufw allow from 203.0.113.4 to any port 22 proto tcp comment 'admin jump host'

# ⑤ 限制網路介面
sudo ufw allow in on ens192 to any port 9100 proto tcp comment 'node_exporter on mgmt nic'

# ⑥ 埠範圍（★★★ 冒號不是連字號）
sudo ufw allow 30000:30100/udp
```

每一條成功都會回：

```text
Rule added
Rule added (v6)
```

★★★ 只有 IPv4 時（例如指定了 IPv4 來源），就只會出現一行 `Rule added`。

> [!warning] ★★★★ 埠範圍一定要指定協定
> ```bash
> sudo ufw allow 30000:30100
> ```
> ```text
> ERROR: Must specify 'tcp' or 'udp' with multiple ports
> ```
> 單一埠可以省略協定（tcp 與 udp 都開），**埠範圍不行**。

### 完整語法結構 ★★★★

```text
ufw [--dry-run] [insert N] {allow|deny|reject|limit} [in|out] [on 介面]
    [log|log-all]
    [proto 協定] [from 來源[ port 來源埠]] [to 目的[ port 目的埠]]
    [comment '註解']
```

實際組合範例：

```bash
# 只允許管理網段透過管理網卡連 SSH，並記錄
sudo ufw allow in on ens224 log proto tcp from 192.168.99.0/24 to any port 22 \
     comment 'SSH from mgmt vlan only'

# 拒絕整個網段存取所有埠（記得放在特例規則的下面）
sudo ufw deny from 198.51.100.0/24 comment 'blocked branch office'

# 出向：禁止這台主機主動連 SMB，避免中毒後往內網掃
sudo ufw deny out proto tcp to any port 445 comment 'no outbound SMB'
```

### ★★★★★ `--dry-run`：先看會產生什麼再套用

```bash
sudo ufw --dry-run allow from 192.168.10.0/24 to any port 3306 proto tcp
```

```text
*filter
:ufw-user-input - [0:0]
:ufw-user-output - [0:0]
:ufw-user-forward - [0:0]
### RULES ###

### tuple ### allow tcp 3306 0.0.0.0/0 any 192.168.10.0/24 in
-A ufw-user-input -p tcp --dport 3306 -s 192.168.10.0/24 -j ACCEPT

### END RULES ###
COMMIT
```

★★★★ 這是**在正式環境改規則前最有價值的一個旗標**。
它讓你在動手之前看到 ufw 會產生什麼 iptables 規則，
尤其是當規則寫得比較複雜、你不確定 ufw 有沒有理解對你的意思的時候。

### 查看規則：三個 status ★★★★★

```bash
sudo ufw status
```

```text
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80,443/tcp (Nginx Full)    ALLOW       Anywhere
3306/tcp                   ALLOW       192.168.10.0/24
22/tcp (v6)                ALLOW       Anywhere (v6)
80,443/tcp (Nginx Full (v6)) ALLOW     Anywhere (v6)
```

```bash
sudo ufw status verbose
```

```text
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
80,443/tcp (Nginx Full)    ALLOW IN    Anywhere
3306/tcp                   ALLOW IN    192.168.10.0/24
```

★★★★★ **`verbose` 才會顯示預設政策與 logging 狀態**，稽核截圖請截這一個。

```bash
sudo ufw status numbered
```

```text
Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp                     ALLOW IN    Anywhere
[ 2] 80,443/tcp (Nginx Full)    ALLOW IN    Anywhere
[ 3] 3306/tcp                   ALLOW IN    192.168.10.0/24
[ 4] 22/tcp (v6)                ALLOW IN    Anywhere (v6)
[ 5] 80,443/tcp (Nginx Full (v6)) ALLOW IN  Anywhere (v6)
```

★★★★★ **`numbered` 是排查「規則沒作用」的第一個指令** —— 它顯示真正的執行順序。

### 插入規則到指定位置 ★★★★

```bash
sudo ufw insert 1 allow from 203.0.113.4 to any port 22 proto tcp comment 'jump host'
```

```text
Rule inserted
```

> [!warning] ★★★★ insert 的位置號碼是**當下**的號碼
> `ufw status numbered` 看到的號碼，會在你每次新增／刪除之後改變。
> 標準做法是：**每次 insert 或 delete 之前都重跑一次 `ufw status numbered`**，
> 不要用五分鐘前記下來的號碼。

### 刪除規則：兩種方法 ★★★★

**方法 A：依號碼刪（推薦）**

```bash
sudo ufw status numbered
sudo ufw delete 3
```

```text
Deleting:
 allow from 192.168.10.0/24 to any port 3306 proto tcp
Proceed with operation (y|n)? y
Rule deleted
```

> [!danger] ★★★★★ 一次刪多條時，一定要**從大號碼往小號碼刪**
> 刪掉第 3 條之後，原本的第 4 條會變成第 3 條、第 5 條變第 4 條。
> 如果你照著舊清單「刪 3、刪 4、刪 5」，實際刪掉的是舊的 3、5、7 ——
> **可能把 SSH 那條刪掉**。
> 正確做法：`sudo ufw delete 5` → `sudo ufw delete 4` → `sudo ufw delete 3`，
> 而且每刪一條就重看一次 `ufw status numbered`。

**方法 B：把新增指令原封不動加上 `delete`**

```bash
sudo ufw delete allow 80/tcp
```

```text
Rule deleted
Rule deleted (v6)
```

★★★ 這個方法的字串必須**跟當初新增時完全一致**（含 `proto`、`from`、`to` 的寫法），
少一個字就會得到：

```text
ERROR: Could not delete non-existent rule
ERROR: Could not delete non-existent rule (v6)
```

### 重載與重置 ★★★★

```bash
# 重新套用規則（改了 before.rules / after.rules 之後必跑）
sudo ufw reload
```

```text
Firewall reloaded
```

> [!danger] ★★★★★ `ufw reset` 會刪光所有規則並停用防火牆
> ```bash
> sudo ufw reset
> ```
> ```text
> Resetting all rules to installed defaults. This may disrupt existing ssh
> connections. Proceed with operation (y|n)? y
> Backing up 'user.rules' to '/etc/ufw/user.rules.20260903_103012'
> Backing up 'before.rules' to '/etc/ufw/before.rules.20260903_103012'
> ...
> ```
> ★★★★ 好消息是它**會自動備份**到 `/etc/ufw/*.rules.<時間戳>`，救得回來。
> 壞消息是 reset 之後 ufw 變成 inactive、規則全空，
> **在遠端做這件事前一定要先排 at 自動還原**。

## 進階設定與調校

### 應用設定檔（application profiles） ★★★

套件安裝時會把「這個服務用哪些埠」寫進 `/etc/ufw/applications.d/`，
讓你可以用名字而不是埠號來開牆。

```bash
sudo ufw app list
```

```text
Available applications:
  Nginx Full
  Nginx HTTP
  Nginx HTTPS
  OpenSSH
```

```bash
sudo ufw app info 'Nginx Full'
```

```text
Profile: Nginx Full
Title: Web Server (Nginx, HTTP + HTTPS)
Description: Small, but very powerful and efficient web server

Ports:
  80,443/tcp
```

**自己寫一個** ★★★

```bash
sudo tee /etc/ufw/applications.d/myapp <<'EOF'
[MyApp API]
title=MyApp REST API
description=Internal REST API served by PHP-FPM behind Nginx
ports=8443/tcp

[MyApp Metrics]
title=MyApp Prometheus metrics
description=node_exporter and app metrics endpoints
ports=9100,9101/tcp
EOF
```

★★★ 格式重點：

| 欄位 | 說明 |
| --- | --- |
| `[名稱]` | 顯示在 `ufw app list`。含空白時使用要加引號 |
| `title` | 一行標題 |
| `description` | 描述 |
| `ports` | ★★★ 逗號分隔的埠、冒號表示範圍、`/tcp` 或 `/udp` 指定協定，多組用 `|` 分隔，例如 `80,443/tcp|53/udp` |

讓 ufw 重讀：

```bash
sudo ufw app update 'MyApp API'
```

```text
Rules updated for profile 'MyApp API'
Skipped reloading firewall
```

```bash
sudo ufw app list
```

```text
Available applications:
  MyApp API
  MyApp Metrics
  Nginx Full
  Nginx HTTP
  Nginx HTTPS
  OpenSSH
```

> [!warning] ★★★★ 應用設定檔會被套件升級覆寫
> `/etc/ufw/applications.d/nginx` 這種**由套件提供的檔案**，
> 在 `apt upgrade` 時可能被換掉。你自己新增的檔案（不同檔名）不受影響。
> 另外一個更大的坑：如果套件把 `ports` 改了（例如新版把 443 拿掉），
> 你的 `ufw allow 'Nginx Full'` 規則**不會自動跟著變**，
> 因為 ufw 是在下規則的當下把設定檔展開成埠號存起來的。
> **升級 Nginx 之後請重跑 `ufw status` 確認埠號還是你要的。**

### 日誌 ★★★★

```bash
sudo ufw logging medium
```

```text
Logging enabled
```

| 等級 | 記錄什麼 | 建議 |
| --- | --- | --- |
| `off` | 不記 | ★★★★ 正式環境不要用，出事沒證據 |
| `low` | 被預設政策擋掉的封包 ＋ 明確 `log` 的規則 | ★★★★★ **預設值，多數機關用這個就夠** |
| `medium` | low ＋ 所有被 INVALID／新連線但未匹配的封包 | ★★★ 排查期間用 |
| `high` | medium ＋ 所有封包（含 established），有速率限制 | ★★ 只在短時間排查用 |
| `full` | 所有封包，**不做速率限制** | ★★★★★ **會把磁碟寫爆**，只在幾分鐘的抓包排查用，用完立刻改回 low |

> [!danger] ★★★★★ `ufw logging full` 在正式環境會塞爆 `/var`
> 一台有正常流量的 Web 主機開 `full`，`/var/log/ufw.log` 可以在幾十分鐘內長到數 GB，
> `/var` 滿了會連帶讓 MySQL、journald、Nginx 一起寫入失敗。
> 要開就在 tmux 裡開，並且同時排好：
> ```bash
> echo "/usr/sbin/ufw logging low" | sudo at now + 10 minutes
> ```

**讀日誌** ★★★★

```bash
sudo tail -n 2 /var/log/ufw.log
```

```text
Sep  3 10:41:07 web01 kernel: [ 8123.554122] [UFW BLOCK] IN=ens192 OUT= MAC=00:50:56:9a:1b:2c:00:50:56:9a:aa:bb:08:00 SRC=203.0.113.77 DST=192.168.10.20 LEN=60 TOS=0x00 PREC=0x00 TTL=52 ID=54321 DF PROTO=TCP SPT=41234 DPT=3306 WINDOW=29200 RES=0x00 SYN URGP=0
Sep  3 10:41:09 web01 kernel: [ 8125.101987] [UFW BLOCK] IN=ens192 OUT= MAC=00:50:56:9a:1b:2c:00:50:56:9a:aa:bb:08:00 SRC=198.51.100.9 DST=192.168.10.20 LEN=44 TOS=0x00 PREC=0x00 TTL=245 ID=0 PROTO=TCP SPT=51000 DPT=23 WINDOW=1024 RES=0x00 SYN URGP=0
```

| 欄位 | 意思 | 重要度 |
| --- | --- | --- |
| `[UFW BLOCK]` | 被擋掉。其他可能是 `[UFW ALLOW]`、`[UFW LIMIT BLOCK]`、`[UFW AUDIT]` | ★★★★★ |
| `IN=ens192` | 從哪張網卡進來。空的代表是本機發出的 | ★★★★ |
| `OUT=` | 從哪張網卡出去。入向封包這欄是空的 | ★★★ |
| `MAC=` | 目的 MAC ＋ 來源 MAC ＋ 乙太類型（`08:00` = IPv4），共 14 bytes | ★★ |
| `SRC=` / `DST=` | ★★★★★ **來源／目的 IP，排查第一個要看的** | ★★★★★ |
| `PROTO=` | TCP／UDP／ICMP | ★★★★ |
| `SPT=` / `DPT=` | ★★★★★ **來源埠／目的埠。`DPT` 就是「他想連你哪個埠」** | ★★★★★ |
| `SYN` | TCP 旗標。只有 `SYN` 代表是新連線嘗試 | ★★★ |
| `TTL=` | ★★ 可粗略推測跳數；`TTL=245` 這種接近 255 的通常是網路設備或掃描工具 | ★★ |

**只看某個 IP 被擋了什麼**：

```bash
sudo grep 'SRC=203.0.113.77' /var/log/ufw.log | tail -n 5
```

**統計哪些埠被打最多**（★★★★ 每週巡檢很好用）：

```bash
sudo grep 'UFW BLOCK' /var/log/ufw.log | grep -o 'DPT=[0-9]*' | sort | uniq -c | sort -rn | head
```

```text
   1842 DPT=23
    967 DPT=3306
    511 DPT=445
    338 DPT=22
     94 DPT=6379
```

**統計來源 IP**：

```bash
sudo grep 'UFW BLOCK' /var/log/ufw.log | grep -o 'SRC=[0-9.]*' | sort | uniq -c | sort -rn | head
```

> [!tip] ★★★ ufw 日誌也在 journald 裡
> ```bash
> sudo journalctl -k --grep 'UFW' -n 20 --no-pager
> ```
> 如果 `/var/log/ufw.log` 是空的（某些精簡安裝沒有對應的 rsyslog 規則），
> 就用 journalctl 這條。日誌輪替與集中請看 [[100-01-02-guide-日誌-日誌集中與輪替]]。

### 單條規則加日誌 ★★★

```bash
sudo ufw allow log 22/tcp
sudo ufw deny log-all from 198.51.100.0/24
```

| 關鍵字 | 行為 |
| --- | --- |
| `log` | ★★★ 只記錄**新連線**（第一個封包） |
| `log-all` | ★★ 記錄**所有匹配的封包**，量很大，慎用 |

### IPv6 ★★★★

```bash
grep IPV6 /etc/default/ufw
```

```text
IPV6=yes
```

★★★★★ **`IPV6=yes` 是預設值，而且應該保持開啟。**
關掉之後 ufw 完全不管 IPv6 流量 —— 但你的主機**還是有 IPv6 位址、
服務還是綁在 IPv6 上**，等於開了一個沒人看守的後門。

驗證你的服務有沒有在聽 IPv6：

```bash
sudo ss -tlnp | grep ':::'
```

```text
LISTEN 0      511             [::]:80          [::]:*    users:(("nginx",pid=1123,fd=7))
LISTEN 0      128             [::]:22          [::]:*    users:(("sshd",pid=812,fd=4))
```

> [!warning] ★★★★ 來源限制不會自動涵蓋 IPv6
> ```bash
> sudo ufw allow from 192.168.10.0/24 to any port 3306 proto tcp
> ```
> 這條只產生 IPv4 規則（輸出只有一行 `Rule added`）。
> 如果 MySQL 也綁在 `::`，IPv6 那邊就靠預設政策 `deny incoming` 擋 —— 這是安全的。
> 但如果你哪天寫了 `ufw allow 3306/tcp`（不指定來源），
> **IPv4 與 IPv6 會同時全開**。★★★★ 資料庫埠永遠要指定來源。

### 轉發規則 `ufw route` ★★★

只有這台機器要當路由器／NAT 閘道時才需要。

```bash
sudo ufw default allow routed
sudo ufw route allow in on ens192 out on ens224 to 192.168.20.0/24 port 443 proto tcp
```

```text
Rule added
Rule added (v6)
```

> [!warning] ★★★ ufw 的 NAT 能力很有限
> `ufw route` 只能做**過濾**，不能做 SNAT／DNAT。
> 要做位址轉換得手動編 `/etc/ufw/before.rules` 的 `*nat` 區段，
> 那時候你其實已經在寫 iptables 了 —— 建議直接看
> [[090-02-03-guide-防火牆-nftables與iptables]] 用原生語法寫，比較好維護。

### ★★★★ Docker 會繞過 ufw

這是機關導入容器之後**最常踩、也最危險**的一個坑。

**現象**：

```bash
# 主機上 ufw 只放行 22 與 80
sudo ufw status
```

```text
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
```

```bash
# 但這台機器上跑了一個容器，發布了 8080
sudo docker run -d --name test -p 8080:80 nginx:alpine
```

```text
a3f1c9e2b7d4...
```

```bash
# 從另一台機器測 8080
curl -sS -m 5 -o /dev/null -w '%{http_code}\n' http://192.168.10.20:8080/
```

```text
200
```

★★★★★ **8080 通了。ufw 完全沒擋，`ufw status` 也看不出任何異常。**

**原因**：

```text
  封包進來 → netfilter nat 表 PREROUTING
                    │
                    ▼
            ┌───────────────────┐
            │ DOCKER chain      │  ← Docker 在這裡做 DNAT
            │ 8080 → 容器:80    │     把目的地改成容器 IP
            └────────┬──────────┘
                     │ 目的地已經不是本機了
                     ▼
            這個封包走的是 FORWARD 路徑，不是 INPUT
                     │
                     ▼
            ┌───────────────────┐   ┌──────────────────┐
            │ DOCKER-USER chain │   │ ufw-user-input   │
            │ Docker 建立，優先  │   │ 你的 ufw 規則     │
            │ 於 Docker 的規則   │   │ ★ 根本不在路徑上  │
            └───────────────────┘   └──────────────────┘
```

★★★★★ 兩個關鍵：
1. Docker 發布的埠走的是 **FORWARD 鏈**，而 ufw 的使用者規則掛在 **INPUT 鏈**。
2. Docker 啟動時會自己寫 iptables 規則，而且插在很前面。

**解法（依推薦程度排序）**：

**解法 A ★★★★★：把發布埠綁在 loopback，前面擺反向代理**

```bash
sudo docker run -d --name app -p 127.0.0.1:8080:80 nginx:alpine
```

```yaml
# docker-compose.yml
services:
  app:
    image: nginx:alpine
    ports:
      - "127.0.0.1:8080:80"
```

★★★★★ 這是**最乾淨、最不需要維護的做法**：
容器只對本機開放，外部一律走主機上的 Nginx 反向代理，
而那個 Nginx 的 80／443 是走 INPUT 鏈的，ufw 管得到。
機關的標準架構應該直接把這條寫進部署規範。

**解法 B ★★★★：用 `DOCKER-USER` 鏈補規則**

Docker 保證 `DOCKER-USER` 鏈**永遠在 Docker 自己的規則之前**被執行，
而且 Docker 不會去清空它。把它接到 ufw 的 forward 鏈：

編輯 `/etc/ufw/after.rules`，在檔案**最後面**（`COMMIT` 之後）加入：

```text
# BEGIN UFW AND DOCKER
*filter
:ufw-user-forward - [0:0]
:ufw-docker-logging-deny - [0:0]
:DOCKER-USER - [0:0]
-A DOCKER-USER -j ufw-user-forward

-A DOCKER-USER -j RETURN -s 10.0.0.0/8
-A DOCKER-USER -j RETURN -s 172.16.0.0/12
-A DOCKER-USER -j RETURN -s 192.168.0.0/16

-A ufw-docker-logging-deny -m limit --limit 3/min --limit-burst 10 -j LOG --log-prefix "[UFW DOCKER BLOCK] "
-A ufw-docker-logging-deny -j DROP

-A DOCKER-USER -p udp -m udp --sport 53 --dport 1024:65535 -j RETURN

-A DOCKER-USER -j ufw-docker-logging-deny -p tcp -m tcp --tcp-flags FIN,SYN,RST,ACK SYN -d 192.168.0.0/16
-A DOCKER-USER -j ufw-docker-logging-deny -p tcp -m tcp --tcp-flags FIN,SYN,RST,ACK SYN -d 10.0.0.0/8
-A DOCKER-USER -j ufw-docker-logging-deny -p tcp -m tcp --tcp-flags FIN,SYN,RST,ACK SYN -d 172.16.0.0/12
-A DOCKER-USER -j ufw-docker-logging-deny -p udp -m udp --dport 0:32767 -d 192.168.0.0/16
-A DOCKER-USER -j ufw-docker-logging-deny -p udp -m udp --dport 0:32767 -d 10.0.0.0/8
-A DOCKER-USER -j ufw-docker-logging-deny -p udp -m udp --dport 0:32767 -d 172.16.0.0/12

-A DOCKER-USER -j RETURN
COMMIT
# END UFW AND DOCKER
```

```bash
sudo ufw reload
```

之後就可以用 `ufw route` 控制容器的存取：

```bash
sudo ufw route allow proto tcp from 192.168.10.0/24 to any port 80
```

> [!warning] ★★★ 未實機驗證
> 上面這段 `after.rules` 內容源自社群廣泛使用的 **ufw-docker** 專案作法。
> **本專案未在實機驗證過每一行的行為**，而且它假設你的容器網段落在
> RFC1918 三個私有網段內。套用之前請：
> 1. 先在測試機做，用 `sudo ufw reload` 後跑 `sudo iptables -S DOCKER-USER` 確認鏈有生效
> 2. 從外部實測「該通的通、該擋的擋」
> 3. 重開機一次再測一遍（確認 after.rules 有在開機時載入）

**解法 C ★★（不建議）：關掉 Docker 的 iptables 管理**

```json
{
  "iptables": false
}
```

> [!danger] ★★★★★ `"iptables": false` 會直接打斷容器網路
> 寫進 `/etc/docker/daemon.json` 之後，Docker 不再建立 NAT 與 MASQUERADE 規則，
> **容器將連不出去（無法 apt、無法拉取外部 API）**，容器之間的通訊也可能中斷。
> 你必須自己補完所有 NAT 規則。
> 除非你很清楚自己在做什麼，否則**不要用這個解法**。

延伸閱讀：[[050-02-01-05-guide-Docker-網路]]、[[050-02-01-08-guide-Docker-安全實務]]。

### ★★★★★ 把自己鎖在外面時的三種救援

**救援 1：at 排定自動還原（事前預防，最有效）**

```bash
# 動手改規則之前先排好
echo "/usr/sbin/ufw --force disable" | sudo at now + 10 minutes
atq
```

改完、確認連得上之後：

```bash
sudo atrm <job號碼>
```

★★★★★ **`--force` 不可省略**，否則 `ufw disable` 在非互動環境會停在確認提示、什麼也不做。

**救援 2：主控台（console）進去**

| 環境 | 進入方式 |
| --- | --- |
| 實體機 | ★★★★ iDRAC / iLO / IPMI 的 Virtual Console，或直接接螢幕鍵盤 |
| Proxmox VE | ★★★★★ Web UI → 該 VM → Console（noVNC） |
| VMware | vSphere Client → 開啟主控台 |
| 雲端（Azure/GCP/AWS） | ★★★★ Serial Console，需事先啟用 |

進去之後：

```bash
sudo ufw disable
```

**救援 3：從救援模式改設定檔（最後手段）**

用 Live USB 或雲端的 rescue mode 掛載根分割區，然後：

```bash
sudo sed -i 's/^ENABLED=yes/ENABLED=no/' /mnt/etc/ufw/ufw.conf
```

★★★ 重開機之後 ufw 就不會載入規則。

> [!tip] ★★★★ 永遠在 tmux 裡改防火牆
> ```bash
> tmux new -s fw
> ```
> 如果 SSH 斷了，你的指令還在 tmux 裡跑完（例如 `ufw reload` 的後半段），
> 不會停在一半留下半套規則。重連之後 `tmux attach -t fw` 就回到現場。

## 完整實戰範例

**情境**：新建一台 Ubuntu 24.04 LTS 伺服器 `web01`，要跑 Nginx（對全世界提供 80／443）
與 MySQL（只給同網段的 app 伺服器連），並且要被監控系統抓 node_exporter 指標。

| 項目 | 值 |
| --- | --- |
| 主機 | `web01`，IP `192.168.10.20/24`，網卡 `ens192` |
| 管理網段 | `192.168.99.0/24`（MIS 的跳板機在 `192.168.99.10`） |
| 應用伺服器 | `192.168.10.31`、`192.168.10.32` |
| 監控主機 | `192.168.10.50`（Prometheus） |
| 服務 | Nginx 80/443、MySQL 3306、node_exporter 9100、SSH 22 |

目標規則集：

| 埠 | 對誰開 | 動作 |
| --- | --- | --- |
| 22 | 只有管理網段 `192.168.99.0/24` | ★★★★★ `limit` |
| 80, 443 | 全世界 | `allow` |
| 3306 | 只有 `.31` 與 `.32` | ★★★★★ `allow` |
| 9100 | 只有 `192.168.10.50` | `allow` |
| 其他 | —— | ★★★★★ `deny`（預設政策） |

### 步驟 0：★★★★★ 先架好安全網

```bash
# 開 tmux
tmux new -s fw

# 確認 sshd 的埠
sudo ss -tlnp | grep sshd
```

```text
LISTEN 0      128          0.0.0.0:22        0.0.0.0:*    users:(("sshd",pid=812,fd=3))
LISTEN 0      128             [::]:22           [::]:*    users:(("sshd",pid=812,fd=4))
```

```bash
# 排定 15 分鐘後自動關閉防火牆
sudo apt install -y at
sudo systemctl enable --now atd
echo "/usr/sbin/ufw --force disable" | sudo at now + 15 minutes
```

```text
warning: commands will be executed using /bin/sh
job 1 at Wed Sep  3 11:02:00 2026
```

★★★★★ 另外開一個終端機視窗 SSH 進 `web01`，**放著不要關**。

### 步驟 1：記錄動手前的基準線 ★★★★

```bash
sudo ufw status verbose | sudo tee /root/fw-before.txt
sudo iptables -S | sudo tee -a /root/fw-before.txt
sudo ss -tlnp | sudo tee -a /root/fw-before.txt
```

```text
Status: inactive
-P INPUT ACCEPT
-P FORWARD ACCEPT
-P OUTPUT ACCEPT
...
LISTEN 0  128    0.0.0.0:22    0.0.0.0:*  users:(("sshd",pid=812,fd=3))
LISTEN 0  511    0.0.0.0:80    0.0.0.0:*  users:(("nginx",pid=1123,fd=6))
LISTEN 0  511    0.0.0.0:443   0.0.0.0:*  users:(("nginx",pid=1123,fd=8))
LISTEN 0  151    0.0.0.0:3306  0.0.0.0:*  users:(("mysqld",pid=1401,fd=23))
LISTEN 0  4096      *:9100        *:*     users:(("node_exporter",pid=1520,fd=3))
```

★★★★ **這份 `ss -tlnp` 是規劃規則的依據** —— 有幾個埠在聽，就要決定幾條規則。
看到不認得的埠先查清楚是誰在聽，不要直接開牆。

### 步驟 2：設定預設政策 ★★★★★

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw default deny routed
```

```text
Default incoming policy changed to 'deny'
(be sure to update your rules accordingly)
Default outgoing policy changed to 'allow'
(be sure to update your rules accordingly)
Default routed policy changed to 'deny'
(be sure to update your rules accordingly)
```

★★★ 這時候 ufw 還沒 enable，所以什麼都還沒生效。

### 步驟 3：先放行 SSH ★★★★★

```bash
sudo ufw limit in on ens192 proto tcp from 192.168.99.0/24 to any port 22 \
     comment 'SSH from mgmt vlan (rate limited)'
```

```text
Rules updated
```

> [!danger] ★★★★★ 這條規則只放行管理網段
> 如果你**現在這條 SSH 不是從 `192.168.99.0/24` 連進來的**，
> enable 之後你就會被鎖在外面（現有連線因為 established 暫時不斷，但一斷就回不來）。
> 先確認你自己的來源 IP：
> ```bash
> who am i
> ```
> ```text
> mis      pts/0        2026-09-03 10:55 (192.168.99.10)
> ```
> 括號裡的 `192.168.99.10` 必須落在你放行的網段內。不在的話，
> **先多加一條你自己 IP 的規則**，等改用跳板機之後再刪掉。

### 步驟 4：確認規則清單（enable 之前的最後檢查） ★★★★★

```bash
sudo ufw show added
```

```text
Added user rules (see 'ufw status' for running firewall):
ufw limit in on ens192 proto tcp from 192.168.99.0/24 to any port 22 comment 'SSH from mgmt vlan (rate limited)'
```

★★★★★ **有看到 SSH 那一條才可以往下走。**

### 步驟 5：啟用 ufw ★★★★★

```bash
sudo ufw enable
```

```text
Command may disrupt existing ssh connections. Proceed with operation (y|n)? y
Firewall is active and enabled on system startup
```

立刻到第二個終端機視窗測試「重新 SSH 進來」：

```bash
ssh mis@192.168.10.20
```

```text
mis@192.168.10.20's password:
Welcome to Ubuntu 24.04.3 LTS (GNU/Linux 6.8.0-45-generic x86_64)
```

★★★★★ **連得上才繼續。連不上就立刻等 at job 生效（或走主控台）。**

### 步驟 6：加業務規則 ★★★★

```bash
# Web：對全世界開放
sudo ufw allow 80/tcp comment 'nginx http'
sudo ufw allow 443/tcp comment 'nginx https'

# MySQL：只給兩台 app server
sudo ufw allow proto tcp from 192.168.10.31 to any port 3306 comment 'app01 -> mysql'
sudo ufw allow proto tcp from 192.168.10.32 to any port 3306 comment 'app02 -> mysql'

# node_exporter：只給 Prometheus
sudo ufw allow proto tcp from 192.168.10.50 to any port 9100 comment 'prometheus scrape'
```

```text
Rule added
Rule added (v6)
Rule added
Rule added (v6)
Rule added
Rule added
Rule added
```

★★★ 注意 80／443 有 `(v6)`（沒指定來源，IPv4＋IPv6 都加），
3306 與 9100 只有一行（來源是 IPv4 位址，只加 IPv4 規則）。

### 步驟 7：檢查規則順序 ★★★★★

```bash
sudo ufw status numbered
```

```text
Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp on ens192           LIMIT IN    192.168.99.0/24            # SSH from mgmt vlan (rate limited)
[ 2] 80/tcp                     ALLOW IN    Anywhere                   # nginx http
[ 3] 443/tcp                    ALLOW IN    Anywhere                   # nginx https
[ 4] 3306/tcp                   ALLOW IN    192.168.10.31              # app01 -> mysql
[ 5] 3306/tcp                   ALLOW IN    192.168.10.32              # app02 -> mysql
[ 6] 9100/tcp                   ALLOW IN    192.168.10.50              # prometheus scrape
[ 7] 80/tcp (v6)                ALLOW IN    Anywhere (v6)              # nginx http
[ 8] 443/tcp (v6)               ALLOW IN    Anywhere (v6)              # nginx https
```

★★★★ 這個順序沒有問題：清單裡沒有任何 `DENY`，所有規則彼此不重疊，
不匹配的一律交給預設政策。

### 步驟 8：打開日誌 ★★★

```bash
sudo ufw logging low
sudo ufw status verbose
```

```text
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp on ens192           LIMIT IN    192.168.99.0/24            # SSH from mgmt vlan (rate limited)
80/tcp                     ALLOW IN    Anywhere                   # nginx http
443/tcp                    ALLOW IN    Anywhere                   # nginx https
3306/tcp                   ALLOW IN    192.168.10.31              # app01 -> mysql
3306/tcp                   ALLOW IN    192.168.10.32              # app02 -> mysql
9100/tcp                   ALLOW IN    192.168.10.50              # prometheus scrape
```

### 步驟 9：★★★★★ 從外部實測（最關鍵的一步）

**規則設好不等於做對了。一定要從外部真的打一次。**

在**管理跳板機 `192.168.99.10`** 上：

```bash
# 應該通：SSH
nc -zv -w 3 192.168.10.20 22
```

```text
Connection to 192.168.10.20 22 port [tcp/ssh] succeeded!
```

```bash
# 應該通：HTTP / HTTPS
nc -zv -w 3 192.168.10.20 80 443
```

```text
Connection to 192.168.10.20 80 port [tcp/http] succeeded!
Connection to 192.168.10.20 443 port [tcp/https] succeeded!
```

```bash
# ★★★★★ 應該不通：MySQL（跳板機不在放行清單裡）
nc -zv -w 3 192.168.10.20 3306
```

```text
nc: connect to 192.168.10.20 port 3306 (tcp) timed out: Operation now in progress
```

★★★★★ **看到 `timed out` 就對了。** `deny` 是靜默丟棄，所以是逾時不是 refused。
如果看到 `Connection refused`，代表封包有到主機但沒有服務在聽 —— 表示防火牆沒擋到，要回頭查。

```bash
# ★★★★ 應該不通：node_exporter
nc -zv -w 3 192.168.10.20 9100
```

```text
nc: connect to 192.168.10.20 port 9100 (tcp) timed out: Operation now in progress
```

在 **app01 `192.168.10.31`** 上：

```bash
nc -zv -w 3 192.168.10.20 3306
```

```text
Connection to 192.168.10.20 3306 port [tcp/mysql] succeeded!
```

```bash
# ★★★ app01 不該連得上 SSH（來源不在管理網段）
nc -zv -w 3 192.168.10.20 22
```

```text
nc: connect to 192.168.10.20 22 port (tcp) timed out: Operation now in progress
```

在 **Prometheus `192.168.10.50`** 上：

```bash
curl -sS -m 5 -o /dev/null -w '%{http_code}\n' http://192.168.10.20:9100/metrics
```

```text
200
```

### 步驟 10：對照日誌確認擋對了人 ★★★★

回到 `web01`：

```bash
sudo tail -n 5 /var/log/ufw.log
```

```text
Sep  3 11:12:44 web01 kernel: [ 9421.331002] [UFW BLOCK] IN=ens192 OUT= MAC=00:50:56:9a:1b:2c:00:50:56:9a:cc:dd:08:00 SRC=192.168.99.10 DST=192.168.10.20 LEN=60 TOS=0x00 PREC=0x00 TTL=64 ID=41207 DF PROTO=TCP SPT=45120 DPT=3306 WINDOW=64240 RES=0x00 SYN URGP=0
Sep  3 11:12:48 web01 kernel: [ 9425.442119] [UFW BLOCK] IN=ens192 OUT= MAC=00:50:56:9a:1b:2c:00:50:56:9a:cc:dd:08:00 SRC=192.168.99.10 DST=192.168.10.20 LEN=60 TOS=0x00 PREC=0x00 TTL=64 ID=41290 DF PROTO=TCP SPT=39882 DPT=9100 WINDOW=64240 RES=0x00 SYN URGP=0
Sep  3 11:13:05 web01 kernel: [ 9442.108771] [UFW BLOCK] IN=ens192 OUT= MAC=00:50:56:9a:1b:2c:00:50:56:9a:ee:ff:08:00 SRC=192.168.10.31 DST=192.168.10.20 LEN=60 TOS=0x00 PREC=0x00 TTL=64 ID=8811 DF PROTO=TCP SPT=54338 DPT=22 WINDOW=64240 RES=0x00 SYN URGP=0
```

★★★★★ 三筆 BLOCK 對應到剛剛三次「應該不通」的測試，來源與埠都對得上。
**日誌對得上，才算真的驗證完成。**

### 步驟 11：收尾 ★★★★★

```bash
# 取消自動還原
atq
```

```text
1	Wed Sep  3 11:02:00 2026 a root
```

```bash
sudo atrm 1

# 備份規則檔（★★★★ 一定要做，這是唯一能快速還原的東西）
sudo tar czf /root/ufw-backup-$(date +%F).tar.gz /etc/ufw /etc/default/ufw
sudo ls -lh /root/ufw-backup-*.tar.gz
```

```text
-rw-r--r-- 1 root root 8.1K Sep  3 11:20 /root/ufw-backup-2026-09-03.tar.gz
```

```bash
# 產出交接文件
sudo ufw status verbose | sudo tee /root/fw-after.txt
```

### 步驟 12：重開機驗證 ★★★★★

★★★★★ **沒有重開機驗證過的防火牆設定不算完成。**
很多「上線三個月後某次維護重開機就全掛」的事故，就是因為當初沒測這一步。

```bash
sudo reboot
```

重連之後：

```bash
sudo ufw status verbose
```

```text
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp on ens192           LIMIT IN    192.168.99.0/24            # SSH from mgmt vlan (rate limited)
80/tcp                     ALLOW IN    Anywhere                   # nginx http
...
```

再從外部重跑一次步驟 9 的 `nc` 測試。

### 驗收檢查表 ★★★★★

| # | 檢查項 | 通過條件 |
| --- | --- | --- |
| 1 | `ufw status verbose` | `Status: active`、`Default: deny (incoming)` |
| 2 | SSH 從管理網段 | 連得上 |
| 3 | SSH 從非管理網段 | ★★★★★ timed out |
| 4 | 80／443 從外部 | 連得上 |
| 5 | 3306 從 app01／app02 | 連得上 |
| 6 | 3306 從其他來源 | ★★★★★ timed out |
| 7 | 9100 從 Prometheus 以外 | timed out |
| 8 | `/var/log/ufw.log` | ★★★★ 有對應的 BLOCK 紀錄 |
| 9 | 重開機後 | ★★★★★ 規則完整存在 |
| 10 | 有無 Docker | ★★★★ 有的話，`docker ps` 檢查有沒有 `0.0.0.0:` 開頭的發布埠 |
| 11 | 規則備份 | `/root/ufw-backup-*.tar.gz` 存在 |
| 12 | at job | ★★★ 已 `atrm` 清掉 |

## 常見錯誤與排錯

| # | 現象 | 原因 | 解法 |
| --- | --- | --- | --- |
| 1 | ★★★★★ `ufw enable` 之後 SSH 立刻斷、連不回來 | 沒先 `ufw allow OpenSSH` 就啟用，或 sshd 在非 22 埠而規則寫 22 | 走主控台（iDRAC／PVE Console／Serial Console）下 `sudo ufw disable`；沒有主控台就只能救援模式改 `/etc/ufw/ufw.conf` 的 `ENABLED=no`。事前預防：`echo "/usr/sbin/ufw --force disable" \| sudo at now + 5 minutes` |
| 2 | ★★★★ 規則加了卻沒作用 | 前面有更早匹配的規則（多半是廣泛的 `deny`）先命中了 | `sudo ufw status numbered` 看順序，用 `sudo ufw insert 1 <規則>` 把特例插到前面 |
| 3 | ★★★★★ `ufw status` 只有 22／80，但容器的 8080 從外部通得到 | Docker 走 FORWARD 鏈，ufw 使用者規則在 INPUT 鏈，管不到 | 首選改成 `-p 127.0.0.1:8080:80` 綁 loopback；或按本篇解法 B 在 `/etc/ufw/after.rules` 加 `DOCKER-USER` 區塊後 `ufw reload` |
| 4 | `ERROR: Could not delete non-existent rule` | `ufw delete <規則>` 的字串跟新增時不完全一致 | 改用 `sudo ufw status numbered` 後 `sudo ufw delete <號碼>` |
| 5 | ★★★★ 刪規則時不小心把 SSH 刪掉 | 依號碼連續刪多條時號碼會位移 | 從**大號碼往小號碼**刪，每刪一條重看一次 `numbered`。已經刪掉就走主控台補回 |
| 6 | `ERROR: Must specify 'tcp' or 'udp' with multiple ports` | 埠範圍或多埠沒指定協定 | 寫成 `sudo ufw allow 30000:30100/udp` |
| 7 | ★★★ 從外部連是 `Connection refused` 而不是逾時 | 封包根本沒被防火牆擋 —— 通過了但沒服務在聽，或是被上游設備 reject | `sudo ss -tlnp \| grep <埠>` 確認服務有在聽；`sudo ufw status numbered` 確認規則真的存在 |
| 8 | ★★★★ 服務只從本機連得上，外部一律不通，規則看起來也對 | 服務綁在 `127.0.0.1` 而不是 `0.0.0.0` —— 這不是防火牆問題 | `sudo ss -tlnp \| grep <埠>`，看到 `127.0.0.1:3306` 就去改應用程式的 `bind-address` |
| 9 | ★★★ IPv4 通、IPv6 不通（或反過來） | 只加了一邊的規則；或 `/etc/default/ufw` 的 `IPV6=no` | `grep IPV6 /etc/default/ufw` 確認是 `yes`；IPv6 規則要用 IPv6 來源另寫一條 |
| 10 | ★★★ 改了 `/etc/ufw/before.rules` 沒生效 | 沒重載 | `sudo ufw reload`。語法錯的話 reload 會噴 `iptables-restore` 錯誤，照訊息的行號改 |
| 11 | ★★★★ 重開機後規則全沒了 | `ufw.service` 沒 enable，或 `/etc/ufw/ufw.conf` 的 `ENABLED=no` | `systemctl is-enabled ufw` 應為 `enabled`；`grep ENABLED /etc/ufw/ufw.conf` 應為 `yes`。最保險是重跑一次 `sudo ufw enable` |
| 12 | ★★★★ `/var` 被寫爆 | `ufw logging full` 忘了關 | `sudo ufw logging low`；`sudo truncate -s 0 /var/log/ufw.log`；檢查 `/etc/logrotate.d/ufw` |
| 13 | ★★★ 連上 SSH 幾次之後就連不上，等一下又好了 | `ufw limit` 觸發（30 秒 6 次新連線） | 正常行為。頻繁自動化連線的來源（備份腳本、Ansible）改用 `allow from <該IP>` 排除，或整段改用 [[090-02-05-guide-防護-Fail2ban入侵防護]] |
| 14 | ★★★ `ufw app list` 看不到剛裝的服務 | 套件沒提供 profile，或檔案剛新增還沒被讀取 | `ls /etc/ufw/applications.d/` 確認檔案在；`sudo ufw app update <名稱>`。真的沒有就自己寫一個 |
| 15 | ★★★★ Nginx 升級後 HTTPS 突然不通 | 當初用 `ufw allow 'Nginx Full'`，profile 內容改了但既有規則不會跟著變 | `sudo ufw status` 確認實際埠號；★★★ 建議正式環境**直接寫埠號**（`allow 80/tcp`、`allow 443/tcp`）不要依賴 profile |
| 16 | ★★★ `ufw status` 顯示 active，但 `iptables -S` 幾乎是空的 | 有別的工具（firewalld、自訂 nft script）把規則清掉了 | 用第 03 篇的方法查有沒有第二套防火牆在跑：`systemctl status firewalld nftables`。同一台機器只能有一個負責人 |
| 17 | ★★ `ufw` 指令沒反應／很慢 | 反解 DNS 卡住（規則裡寫了主機名稱） | 規則一律寫 IP 或 CIDR，不要寫主機名稱 |

### 排查順序 ★★★★★

遇到「連不上」的時候，照這個順序一步一步排除，不要跳：

```text
  1. 服務真的在聽嗎？          sudo ss -tlnp | grep <埠>
        │ 沒在聽 → 不是防火牆問題，去修服務
        ▼ 有在聽
  2. 綁在哪個位址？            0.0.0.0 / :: 才對外，127.0.0.1 只有本機
        │ 綁 127.0.0.1 → 改應用程式設定
        ▼
  3. 本機連得到嗎？            curl -v http://127.0.0.1:<埠>/
        │ 本機也不通 → 服務問題
        ▼
  4. ufw 規則有嗎、順序對嗎？   sudo ufw status numbered
        │
        ▼
  5. 有被 ufw 擋掉的紀錄嗎？    sudo tail -f /var/log/ufw.log
        │ 有 BLOCK 且 SRC/DPT 對得上 → 就是規則問題，回 4
        │ 完全沒紀錄 → 封包根本沒到這台機器
        ▼
  6. 封包有到嗎？              sudo tcpdump -ni any port <埠>
        │ 沒看到封包 → 上游（交換器 ACL、邊界防火牆、路由）問題
        ▼
  7. 是不是 Docker？           sudo docker ps --format '{{.Names}}\t{{.Ports}}'
        │ 有 0.0.0.0: 開頭的發布埠 → 見本篇 Docker 章節
        ▼
  8. 有第二套防火牆嗎？         systemctl status firewalld nftables
                              sudo iptables -S | head -n 40
```

## 安全性注意事項

| # | 事項 | 重要度 |
| --- | --- | --- |
| 1 | **預設 `deny incoming`，每開一個埠都要能說出理由**。開牆申請要有紀錄（誰申請、為了什麼、什麼時候可以關） | ★★★★★ |
| 2 | **管理埠（SSH、資料庫、監控 exporter）一律限制來源網段**，不可以 `allow 22/tcp` 對全世界 | ★★★★★ |
| 3 | **不要用 `ufw default allow incoming` 當臨時解法**。「先全開讓它先動、之後再收」的規則永遠不會被收回來 | ★★★★★ |
| 4 | 對外網用 `deny`（靜默丟棄）不要用 `reject` —— `reject` 等於告訴掃描者「這台主機存在」 | ★★★★ |
| 5 | **`allow out` 全開是有代價的**。中毒的主機可以自由往外連 C2。有能力的話對出向做白名單，至少擋掉 445、3389、23 這些不該從伺服器主動發出的埠 | ★★★★ |
| 6 | **IPv6 不能忘**。`IPV6=yes` 要保持開啟，並確認你的來源限制在 IPv6 那邊也有等效規則（或該服務根本不綁 IPv6） | ★★★★ |
| 7 | **Docker 主機必須額外檢查**：`docker ps` 看有沒有 `0.0.0.0:` 開頭的發布埠。有就是對全世界開放 | ★★★★★ |
| 8 | `ufw limit` 不是 IPS。真正的暴力破解防護要靠 [[090-02-05-guide-防護-Fail2ban入侵防護]]，並搭配 SSH 金鑰認證、停用密碼登入 | ★★★★ |
| 9 | **日誌要留、要集中**。`/var/log/ufw.log` 只留在本機的話，攻擊者拿到 root 就能刪掉。送到集中式 log server（見 [[100-01-02-guide-日誌-日誌集中與輪替]]） | ★★★★ |
| 10 | **規則變更要納入變更管理**。`/etc/ufw/` 整個目錄建議納入設定管理（Ansible／git），至少每次改完 `tar` 一份備份 | ★★★★ |
| 11 | **不要把 ufw 當唯一防線**。它擋不了應用層攻擊（SQL injection、上傳惡意檔案），那是 WAF 的工作 | ★★★★ |
| 12 | 定期（每季）重看一次規則，把「已經沒在用的服務」對應的規則刪掉 —— 這是稽核最常開的缺失 | ★★★ |
| 13 | ★★★ 別在規則裡用主機名稱。DNS 被投毒或解析失敗時，你的防火牆行為會變得不可預測 | ★★★ |
| 14 | **臨時開的埠要設到期日**。真的必須臨時開，就同時排 `at`：`echo "ufw delete allow 8080/tcp" \| at now + 2 hours` | ★★★ |

## 速查表

### 指令 ★★★★★

| 指令 | 作用 |
| --- | --- |
| `sudo ufw status` | 看規則清單 |
| `sudo ufw status verbose` | ★★★★★ 含預設政策與 logging（稽核截這個） |
| `sudo ufw status numbered` | ★★★★★ 含順序號碼，排查與刪除必用 |
| `sudo ufw show added` | ★★★★★ 看「已加入但可能未生效」的規則，enable 前必看 |
| `sudo ufw show listening` | 看有哪些埠在聽、對應到哪條規則 |
| `sudo ufw enable` | ★★★★★ 啟用（會斷 SSH，先 allow） |
| `sudo ufw disable` | 停用（含關閉開機自啟） |
| `sudo ufw reload` | 重載規則（改 before/after.rules 後必跑） |
| `sudo ufw reset` | ★★★★★ 清空所有規則並停用，會自動備份 |
| `sudo ufw default deny incoming` | 設預設入向政策 |
| `sudo ufw allow 80/tcp` | 開埠 |
| `sudo ufw allow 'Nginx Full'` | 用應用設定檔開埠 |
| `sudo ufw allow from 192.168.10.0/24 to any port 3306 proto tcp` | ★★★★★ 限來源 |
| `sudo ufw allow in on ens192 to any port 9100 proto tcp` | 限介面 |
| `sudo ufw limit 22/tcp` | ★★★★ 限速（30 秒 6 次新連線） |
| `sudo ufw deny out to any port 445` | 出向封鎖 |
| `sudo ufw insert 1 allow ...` | ★★★★ 插到第 1 條 |
| `sudo ufw delete 3` | 依號碼刪（★★★ 多條時由大到小） |
| `sudo ufw delete allow 80/tcp` | 依規則字串刪（要完全一致） |
| `sudo ufw --dry-run allow ...` | ★★★★★ 只顯示會產生的規則，不套用 |
| `sudo ufw logging low` | 設日誌等級 |
| `sudo ufw app list` / `app info '名稱'` / `app update '名稱'` | 應用設定檔 |
| `sudo ufw route allow in on A out on B` | 轉發規則（僅過濾） |

### 檔案路徑 ★★★★

| 路徑 | 內容 |
| --- | --- |
| `/etc/ufw/ufw.conf` | ★★★★ `ENABLED=yes/no`、`LOGLEVEL` |
| `/etc/default/ufw` | ★★★★ `IPV6=yes`、`DEFAULT_INPUT_POLICY`、`DEFAULT_FORWARD_POLICY` |
| `/etc/ufw/user.rules` | ★★★ 你用 `ufw allow` 加的 IPv4 規則（別手動編） |
| `/etc/ufw/user6.rules` | 同上，IPv6 |
| `/etc/ufw/before.rules` | ★★★★ 使用者規則**之前**執行；loopback、established、ICMP 在這 |
| `/etc/ufw/after.rules` | ★★★★ 使用者規則**之後**執行；Docker 整合區塊加在這 |
| `/etc/ufw/before6.rules` / `after6.rules` | IPv6 對應版本 |
| `/etc/ufw/sysctl.conf` | ufw 專屬的 sysctl 設定 |
| `/etc/ufw/applications.d/` | ★★★ 應用設定檔目錄 |
| `/var/log/ufw.log` | ★★★★★ 防火牆日誌 |
| `/lib/systemd/system/ufw.service` | systemd 單元 |

### 動作與方向 ★★★★

| 關鍵字 | 意思 |
| --- | --- |
| `allow` / `deny` / `reject` / `limit` | 放行／靜默丟棄／明確拒絕／限速 |
| `in` / `out` | 入向／出向（省略時預設 `in`） |
| `on <介面>` | 限定網路介面 |
| `proto tcp` / `proto udp` | 協定 |
| `from <IP或CIDR>` / `to <IP或CIDR>` | 來源／目的位址，`any` 代表全部 |
| `port <埠>` | 埠號，`30000:30100` 是範圍 |
| `log` / `log-all` | 記新連線／記所有封包 |
| `comment '文字'` | ★★★★ 註解，強烈建議每條都寫 |

### 日誌欄位 ★★★★

| 欄位 | 意思 |
| --- | --- |
| `[UFW BLOCK]` / `[UFW ALLOW]` / `[UFW LIMIT BLOCK]` | 動作結果 |
| `IN=` / `OUT=` | 進出的網卡 |
| `SRC=` / `DST=` | 來源／目的 IP |
| `PROTO=` | 協定 |
| `SPT=` / `DPT=` | 來源埠／目的埠 |
| `SYN` | 新連線嘗試 |

### 緊急救援 ★★★★★

| 情況 | 動作 |
| --- | --- |
| 事前預防 | `echo "/usr/sbin/ufw --force disable" \| sudo at now + 10 minutes` |
| 已被鎖在外 | 走 iDRAC／PVE Console／Serial Console，下 `sudo ufw disable` |
| 完全進不去 | 救援模式掛載後 `sed -i 's/^ENABLED=yes/ENABLED=no/' /mnt/etc/ufw/ufw.conf` |
| 改壞了想還原 | `sudo tar xzf /root/ufw-backup-<日期>.tar.gz -C /` 後 `sudo ufw reload` |
| reset 之後想回復 | `/etc/ufw/*.rules.<時間戳>` 是自動備份，複製回去再 `ufw reload` |

## 練習題

1. 在測試機（★★★★★ **不要在正式機**）上，從 `ufw` 尚未啟用的狀態開始，
   完成以下流程並把每一步的輸出貼進交接文件：
   排 at 自動還原 → 確認 sshd 埠 → 放行 SSH → `ufw show added` 確認 → `ufw enable`
   → 開第二條連線驗證 → `atrm` 取消。

2. 建立以下規則集，然後用 `ufw status numbered` 檢查順序，
   說明為什麼「允許 `10.0.0.5` 連 8080」那條**不會生效**，並用一行指令修好它：
   ```bash
   sudo ufw deny 8080/tcp
   sudo ufw allow from 10.0.0.5 to any port 8080 proto tcp
   ```

3. 在 `/etc/ufw/applications.d/` 裡自訂一個名為 `Corp Backup` 的應用設定檔，
   包含 TCP 10050 與 UDP 10051 兩個埠，讓它出現在 `ufw app list`，
   並用 `ufw allow 'Corp Backup'` 套用，最後用 `ufw --dry-run` 驗證產生的規則。

4. 在測試機裝 Docker，跑 `docker run -d -p 8080:80 nginx:alpine`，
   在 ufw 只放行 22 的情況下，從另一台機器測試 8080。
   記錄結果，然後改成 `-p 127.0.0.1:8080:80` 再測一次，比較兩者差異。

5. 把 `ufw logging` 開到 `medium`，從外部對一個未放行的埠打三次，
   然後寫一行指令從 `/var/log/ufw.log` 統計出「被擋最多次的前 5 個目的埠」。

6. ★★★★ 設計一份「web01 防火牆規則交接文件」，
   內容包含：每條規則的用途、申請人、預期存取來源、可以刪除的條件。
   用 `ufw status numbered` 的輸出當骨架。

> [!question]- 練習解答
>
> **1.** 標準流程（★★★★★ 順序不可調換）：
> ```bash
> sudo apt install -y at && sudo systemctl enable --now atd
> echo "/usr/sbin/ufw --force disable" | sudo at now + 10 minutes
> sudo ss -tlnp | grep sshd          # 確認實際埠
> sudo ufw allow OpenSSH             # 或 allow <實際埠>/tcp
> sudo ufw show added                # ★★★★★ 必須看到 SSH 那條
> sudo ufw enable
> # 另開視窗 ssh 進來確認
> atq && sudo atrm <job號碼>
> ```
> 關鍵在於 `ufw show added` 這一步 —— 它是 enable 之前唯一能確認自己不會被鎖的方法。
>
> **2.** `ufw deny 8080/tcp` 是先加的，所以排在第 1 條。
> 由上而下第一個匹配勝出，來自 `10.0.0.5` 的封包在第 1 條就被 DENY 掉，
> 第 2 條永遠沒機會執行。修法：
> ```bash
> sudo ufw insert 1 allow from 10.0.0.5 to any port 8080 proto tcp
> ```
> 然後 `sudo ufw status numbered` 確認 allow 在 deny 之上；
> 原本那條排在後面的 allow 可以刪掉。
>
> **3.**
> ```bash
> sudo tee /etc/ufw/applications.d/corp-backup <<'EOF'
> [Corp Backup]
> title=Corporate backup agent
> description=Zabbix-style agent ports for the backup system
> ports=10050/tcp|10051/udp
> EOF
> sudo ufw app update 'Corp Backup'
> sudo ufw app info 'Corp Backup'
> sudo ufw --dry-run allow 'Corp Backup'
> ```
> ★★★ 重點在 `ports` 用 `|` 分隔不同協定的群組，用 `,` 分隔同協定的多個埠。
>
> **4.** 第一次測試 8080 **會通**（回 200 或 nc succeeded），
> 即使 `ufw status` 只有 22 —— 因為 Docker 的 DNAT 讓封包走 FORWARD 鏈，
> 完全繞過 ufw 掛在 INPUT 鏈的使用者規則。
> 改成 `-p 127.0.0.1:8080:80` 之後，Docker 只在 loopback 上發布，
> 從外部測會 timed out（或 refused，視上游而定），本機 `curl 127.0.0.1:8080` 仍然通。
> ★★★★★ 這就是為什麼機關的容器部署規範應該一律要求綁 `127.0.0.1`，
> 對外一律走主機上的反向代理。
>
> **5.**
> ```bash
> sudo ufw logging medium
> # 外部打三次未放行的埠之後
> sudo grep 'UFW BLOCK' /var/log/ufw.log | grep -o 'DPT=[0-9]*' | sort | uniq -c | sort -rn | head -n 5
> ```
> ★★★ 記得測完把 logging 改回 `low`。
>
> **6.** 交接文件至少要有這幾欄（★★★★ 第 4、5 欄是稽核最看重的）：
> | 號 | 規則 | 用途 | 申請人／日期 | 可刪除條件 |
> | --- | --- | --- | --- | --- |
> | 1 | `limit 22/tcp from 192.168.99.0/24` | MIS 遠端管理 | 系統組 / 2026-09-03 | 改用堡壘機集中管理後 |
> | 4 | `allow 3306/tcp from 192.168.10.31` | app01 連資料庫 | 應用組王 / 2026-09-03 | app01 汰除時 |
>
> 「可刪除條件」這一欄是重點 —— 沒有它，規則只會越積越多。

## 小測驗

Q1. 在只有一條 SSH 連線的遠端主機上，下列哪個操作順序是安全的？
（A）`ufw enable` → `ufw allow OpenSSH`
（B）`ufw allow OpenSSH` → `ufw show added` → `ufw enable`
（C）`ufw default deny incoming` → `ufw enable` → `ufw allow OpenSSH`
（D）`ufw reset` → `ufw enable`

Q2. 是非題：`ufw deny` 與 `ufw reject` 對連線方的差別，只在於日誌記法不同。

Q3. 下面這兩條指令依序執行後，來自 `10.0.0.5` 的 8080 連線會發生什麼事？為什麼？
```bash
sudo ufw deny 8080/tcp
sudo ufw allow from 10.0.0.5 to any port 8080 proto tcp
```

Q4. 一台主機 `ufw status` 顯示只放行 22 與 80，但外部可以連上 8080 且該埠是某個
Docker 容器發布的。請說明原因，並給出**兩種**解法。

Q5. 選擇題：想確認「新加的規則有沒有真的進到清單、順序在哪」，最該用哪個指令？
（A）`ufw status`（B）`ufw status verbose`（C）`ufw status numbered`（D）`iptables -L`

Q6. 這行指令會發生什麼事？在什麼情況下會出事？
```bash
sudo ufw default deny outgoing
```

Q7. 簡答：要一次刪除 `ufw status numbered` 裡的第 3、4、5 條規則，
正確的刪除順序是什麼？為什麼？

Q8. 是非題：`ufw allow from 192.168.10.0/24 to any port 3306 proto tcp`
會同時建立 IPv4 與 IPv6 兩條規則。

Q9. 從外部 `nc -zv` 測試某個埠，得到 `Connection refused` 而不是 `timed out`。
這代表防火牆有沒有擋住？下一步該查什麼？

Q10. `ufw logging full` 有什麼風險？如果排查時真的必須開，該怎麼保護自己？

> [!question]- 測驗答案
>
> **Q1 → (B)** ★★★★★
> 必須「先放行、確認、再啟用」。(A) 與 (C) 都是先 enable，那一瞬間 22 埠就被預設政策擋住，
> SSH 當場斷線，而且 ufw 是開機自啟的，重開機也救不回來。
> `ufw show added` 那一步是 enable 前唯一的確認機會。
> → 詳見〈★★★★★ 啟用前的四步準備〉
>
> **Q2 → 錯** ★★★★
> 差別在**封包處理方式**：`deny` 是 DROP（靜默丟棄），對方會卡到逾時（30～120 秒）；
> `reject` 是 REJECT，回 ICMP port-unreachable 或 TCP RST，對方立刻收到「Connection refused」。
> 實務上對外網用 `deny`（讓掃描者浪費時間、不確認主機存在），
> 對內網用 `reject`（讓自己人的程式快速失敗而不是卡住）。
> → 詳見〈ufw 的四個動作〉
>
> **Q3** ★★★★★
> **會被擋掉（timed out）**。ufw 規則由上而下掃描、第一個匹配勝出，
> `deny 8080/tcp` 先加所以排在第 1 條，來自 `10.0.0.5` 的封包在第 1 條就命中 DENY，
> 第 2 條的 allow 永遠沒機會執行。
> 修法是 `sudo ufw insert 1 allow from 10.0.0.5 to any port 8080 proto tcp`。
> 這是「規則加了卻沒作用」的頭號原因。
> → 詳見〈規則順序：第一個匹配勝出〉
>
> **Q4** ★★★★★
> 原因：Docker 發布埠時在 nat 表做 DNAT，把目的地改成容器 IP，
> 該封包因此走 **FORWARD 鏈**，而 ufw 的使用者規則掛在 **INPUT 鏈**，根本不在路徑上。
> Docker 還會自己寫 iptables 規則且插在很前面。
> 解法（任兩種）：
> ①（最推薦）發布埠綁 loopback：`-p 127.0.0.1:8080:80`，外部一律走主機上的反向代理；
> ② 在 `/etc/ufw/after.rules` 加 `DOCKER-USER` 區塊接到 `ufw-user-forward`，
> 之後用 `ufw route allow ...` 控制；
> ③（不建議）`/etc/docker/daemon.json` 設 `"iptables": false` —— 會打斷容器對外網路。
> → 詳見〈★★★★ Docker 會繞過 ufw〉
>
> **Q5 → (C)** ★★★★★
> 只有 `numbered` 會顯示執行順序的號碼，而順序正是排查「規則沒作用」的關鍵。
> `verbose` 顯示預設政策與 logging（適合稽核截圖），但沒有號碼。
> → 詳見〈查看規則：三個 status〉
>
> **Q6** ★★★★★
> 把出向流量全部改成預設拒絕。你現在的 SSH 因為是 established 不會立刻斷，
> 但主機會慢慢「壞掉」：DNS（53）解析不到、NTP（123）對不了時、
> `apt update`（80/443）失敗、監控回報不出去、憑證吊銷檢查失敗。
> 真的要做出向管制，必須先逐條 `ufw allow out` 放行 DNS、NTP、apt mirror、監控伺服器，
> 並全程在第二條連線與 at 自動還原的保護下操作。
> → 詳見〈設定預設政策〉
>
> **Q7** ★★★★★
> **從大到小：先 `delete 5`，再 `delete 4`，最後 `delete 3`**，而且每刪一條重看一次
> `ufw status numbered`。因為刪掉第 3 條之後，原本的 4 會變 3、5 會變 4 ——
> 照舊清單順序刪「3、4、5」實際刪到的是舊的 3、5、7，很可能把 SSH 那條刪掉。
> → 詳見〈刪除規則：兩種方法〉
>
> **Q8 → 錯** ★★★
> 來源指定的是 IPv4 網段，所以 ufw **只建立 IPv4 規則**，輸出只有一行 `Rule added`
> （沒有 `Rule added (v6)`）。IPv6 那邊靠預設政策 `deny incoming` 擋住，這是安全的；
> 但如果哪天改寫成不指定來源的 `ufw allow 3306/tcp`，IPv4 與 IPv6 就會同時全開。
> → 詳見〈IPv6〉
>
> **Q9** ★★★★
> **代表防火牆沒擋住這個封包** —— refused 表示封包確實抵達了主機（或上游設備明確 reject），
> 只是沒有服務在那個埠上聽。ufw 的 `deny` 是 DROP，症狀會是 timed out 而不是 refused。
> 下一步查：`sudo ss -tlnp | grep <埠>` 確認服務有沒有在聽、綁在哪個位址
> （綁 `127.0.0.1` 的話外部本來就連不到，那是應用程式設定問題不是防火牆問題）。
> → 詳見〈排查順序〉與排錯表第 7、8 列
>
> **Q10** ★★★★★
> `full` 記錄所有封包且**不做速率限制**，一台有正常流量的 Web 主機可以在幾十分鐘內
> 把 `/var/log/ufw.log` 寫到數 GB，`/var` 滿了會連帶讓 MySQL、journald、Nginx 一起寫入失敗。
> 保護方式：在 tmux 裡開，並同時排定自動還原
> `echo "/usr/sbin/ufw logging low" | sudo at now + 10 minutes`，
> 事後 `sudo truncate -s 0 /var/log/ufw.log` 並確認 logrotate 設定正常。
> → 詳見〈日誌〉

## 延伸閱讀

### 本手冊

- [[090-02-03-guide-防火牆-nftables與iptables]] —— ufw 底下那一層。
  ★★★★ 大量 IP 封鎖（set）、細緻速率限制、複雜 NAT，以及看懂舊機器上的 iptables 語法
- [[090-02-04-guide-防火牆-firewalld]] —— RHEL／Rocky／AlmaLinux 系的對應工具
- [[090-02-01-guide-防護-伺服器初始安全設定]] —— 防火牆在伺服器上線 checklist 中的位置
- [[090-02-05-guide-防護-Fail2ban入侵防護]] —— ★★★★ 動態封鎖暴力破解來源，補 `ufw limit` 的不足
- [[090-02-06-guide-防護-遠端存取安全]] —— 跳板機、VPN、堡壘機
- [[020-02-01-04-svc-sshd-伺服器端設定]] —— 改 SSH 埠之後別忘了同步改防火牆規則
- [[020-02-01-07-svc-SSH-安全強化]] —— 金鑰認證、停用密碼登入
- [[050-02-01-05-guide-Docker-網路]] —— 為什麼容器發布埠會繞過主機防火牆
- [[050-02-01-08-guide-Docker-安全實務]] —— 容器部署的安全基準
- [[100-01-02-guide-日誌-日誌集中與輪替]] —— 把 ufw 日誌送到集中式 log server
- [[090-05-02-guide-資安設備-防火牆與次世代防火牆]] —— 邊界防火牆設備與主機防火牆的分工
- [[040-01-08-guide-Juniper-埠設定與安全]] —— 交換器層的存取控制，跟主機防火牆是不同層次的防線

### 外部資源

- `man ufw` 與 `man ufw-framework` —— ★★★★ 後者說明 before/after rules 的執行順序，
  要改 `after.rules` 之前一定要讀
- Ubuntu Server Guide — Firewall 章節：<https://documentation.ubuntu.com/server/how-to/security/firewalls/>
- ufw 上游專案：<https://launchpad.net/ufw>
- ufw-docker（解決 Docker 繞過問題的社群工具）：<https://github.com/chaifeng/ufw-docker>
- Docker 官方文件 — Packet filtering and firewalls：
  <https://docs.docker.com/engine/network/packet-filtering-firewalls/>
