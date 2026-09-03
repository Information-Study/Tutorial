---
title: "nftables 與 iptables"
desc: "ufw／iptables／nftables 三層關係、nft 語法與 table/chain/hook/priority、set 與 map 做大量 IP 封鎖與速率限制、iptables-translate 對照、原子套用與鎖門救援"
aliases: [nftables, iptables, nft, iptables-nft, iptables-translate, DOCKER-USER, nftables.conf]
tags: [群組/資訊安全, 安全/防火牆, 主題/網路]
category: 系統與網路防護
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[090-02-02-guide-防火牆-ufw基礎與實務]]", "[[020-01-16-cmd-Linux-網路基礎指令]]"]
updated: 2026-09-03
---

# nftables 與 iptables

> [!abstract] 這篇你會學到
> - ★ 一張圖看懂 **ufw ／ iptables ／ nftables ／ netfilter** 四層誰在誰上面，
>   以及「Ubuntu 上的 `iptables` 其實是 `iptables-nft` 相容層」是什麼意思
> - ★★★★ **什麼時候該放棄 ufw 跳下來寫 nftables**：大量 IP 集合、細緻速率限制、
>   複雜 NAT、依連線狀態分流 —— 這四種需求 ufw 都表達不出來
> - ★★★★★ **`nft flush ruleset` 會在 0.01 秒內把你鎖在門外**，
>   以及 `nft -c`（check）、`at` 自動還原、tmux 這三道保險怎麼架
> - ★★★★ **set 與 map**：封鎖 8 萬個惡意 IP 用一條規則 ＋ 一個 set 就搞定，
>   而不是 8 萬條規則；Fail2ban 的 nftables 後端也是這樣做的
> - ★★★★ **多個 base chain 掛在同一個 hook 上會全部執行**，任何一個 drop 就結束 ——
>   這是「ufw 說 allow、封包還是不通」的真正原因
> - ★★★ nftables 語法全貌：family／table／chain／hook／priority／rule／handle／counter
> - ★★★ **`/etc/nftables.conf` 持久化**與 `nft -f` 的**原子套用**特性
> - ★★★ 既有機器上的 iptables 語法怎麼讀、`iptables-translate` 怎麼轉
> - 用 nftables 重寫第 02 篇那台 web01 的完整規則集，兩相對照；
>   再加兩條 ufw 做不到的（IP 集合封鎖、per-IP 速率限制）

> [!warning] ★★★★★ 未實機驗證
> 本專案目前**沒有專屬的 nftables 實驗機**可以逐條驗證。
> 本篇語法以 **Ubuntu 24.04 LTS ／ nftables 1.0.9** 為基準撰寫，
> 大原則（table／chain／hook／priority／set 的結構）是穩定的，
> 但**特定寫法在不同 nftables 版本之間有差異**，尤其是：
> - dynamic set ＋ `limit rate over` 的 per-IP 限流語法
> - `meta l4proto` 與 `ip protocol` 在 `inet` family 下的行為差異
> - `ct state` 在不同版本對 `untracked` 的處理
>
> **每一段套用到正式環境之前，請在測試機用 `sudo nft -c -f <檔案>` 檢查語法、
> 用 `sudo nft list ruleset` 確認展開結果，並實際打流量測試。**
> 本篇每一節都會標出哪些是「安全的基本語法」、哪些是「請先驗證」。

> [!danger] ★★★★★ 這篇的每個指令都可能把你鎖在門外
> nftables 沒有 ufw 那層保護 —— 沒有「你確定嗎」的提示，
> 也不會自動幫你放行 loopback 與 established。
> **開始之前，本篇〈把自己鎖在外面〉那一節的三道保險請先架好：**
> 1. tmux
> 2. `echo "/usr/sbin/nft flush ruleset" | sudo at now + 5 minutes`（或還原腳本）
> 3. 第二條 SSH 連線 ＋ 可用的主控台

## 前置知識

- [[090-02-02-guide-防火牆-ufw基礎與實務]] —— ★★★★★ **先讀完那篇再讀這篇**。
  九成的機關需求 ufw 就夠了，這篇是處理剩下那一成
- [[020-01-16-cmd-Linux-網路基礎指令]] —— `ss`、`ip`、`tcpdump`
- [[020-01-17-cmd-Linux-systemd服務管理]] —— `nftables.service` 的啟用與載入時機
- [[010-02-03-guide-網概-網路分層模型]] —— 三層／四層、封包路徑的基本觀念

搭配閱讀：

- [[090-02-04-guide-防火牆-firewalld]] —— RHEL 系的前端，底層同樣是 nftables
- [[090-02-05-guide-防護-Fail2ban入侵防護]] —— ★★★★ Fail2ban 的 nftables 後端就是用 set
- [[050-02-01-05-guide-Docker-網路]] —— Docker 直接寫 iptables 規則的行為

## 觀念說明

### 四層堆疊：誰在誰上面 ★

這是本篇最重要的一張圖。搞清楚它，後面所有「為什麼規則沒作用」的問題都會變簡單。

```text
  ┌───────────────────────────────────────────────────────────────────┐
  │  第 1 層：管理前端（人用的）                                        │
  │                                                                   │
  │    ufw              firewalld           你自己寫的 nft script      │
  │    (Ubuntu 主線)     (RHEL 主線)          (本篇)                    │
  │    ufw allow 80/tcp  firewall-cmd ...    nft add rule ...          │
  └──────────┬─────────────────┬───────────────────────┬──────────────┘
             │                 │                       │
             │ 翻譯成          │ 直接產生               │ 直接產生
             ▼                 │                       │
  ┌────────────────────────┐   │                       │
  │  第 2 層：iptables 介面 │   │                       │
  │                        │   │                       │
  │  iptables -A INPUT ... │   │                       │
  │                        │   │                       │
  │  ★ Ubuntu 20.04+／     │   │                       │
  │    Debian 10+ 上，這個 │   │                       │
  │    指令其實是          │   │                       │
  │    iptables-nft，      │   │                       │
  │    一個「相容層」       │   │                       │
  └──────────┬─────────────┘   │                       │
             │ 再翻譯          │                       │
             ▼                 ▼                       ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │  第 3 層：nftables 規則集（現行後端）                                │
  │                                                                   │
  │    table ip filter { chain INPUT { ... } }     ← iptables 轉來的    │
  │    table inet myfw { chain input { ... } }     ← 你直接寫的         │
  │                                                                   │
  │    ★★★★ 兩者共存於同一個 nftables 引擎，但是**不同的 table**        │
  └──────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │  第 4 層：Linux kernel netfilter —— 封包真正經過的地方              │
  │                                                                   │
  │    prerouting → input → (本機) → output → postrouting              │
  │                    ↘ forward ↗                                    │
  └───────────────────────────────────────────────────────────────────┘
```

驗證你的機器走的是哪一條路：

```bash
sudo iptables -V
```

```text
iptables v1.8.10 (nf_tables)
```

★★★★ **括號裡的 `(nf_tables)` 就是關鍵**。它代表你打的 `iptables` 指令，
實際上是把規則翻譯成 nftables 規則存進 nftables 引擎。
如果看到 `(legacy)`，代表這台機器用的是舊的 xtables 後端，兩者的規則是**分開的兩套**。

```bash
ls -l /usr/sbin/iptables
```

```text
lrwxrwxrwx 1 root root 26 Aug 14 09:12 /usr/sbin/iptables -> /etc/alternatives/iptables
```

```bash
sudo update-alternatives --display iptables
```

```text
iptables - auto mode
  link best version is /usr/sbin/iptables-nft
  link currently points to /usr/sbin/iptables-nft
  link iptables is /usr/sbin/iptables
/usr/sbin/iptables-legacy - priority 10
/usr/sbin/iptables-nft - priority 20
```

> [!danger] ★★★★★ legacy 與 nft 兩套後端同時有規則，是災難的開始
> 如果一台機器上同時有 legacy 與 nft 兩套規則（例如舊系統升級上來、
> 或有人用 `iptables-legacy` 手動加過規則），**兩套都會生效**，
> 而你用 `iptables -S` 只會看到其中一套 —— 另一套變成看不見的幽靈規則。
> 檢查方法：
> ```bash
> sudo iptables-legacy -S 2>/dev/null | head
> sudo iptables-nft -S | head
> ```
> ★★★★ 如果 legacy 那邊有東西（不只 `-P INPUT ACCEPT` 三行），
> 請排維護時段把它清乾淨，並確認沒有服務依賴它。

### ★★★★ 多個 base chain 掛同一個 hook：全部執行

這是初學者最容易誤解、也最常造成「規則明明 allow 了卻不通」的地方。

```text
  一個封包進入 input hook：

  ┌─────────────────────────────────────────────────────────────┐
  │  input hook                                                 │
  │                                                             │
  │  priority -150  chain A (mangle)      ← 依 priority 由小到大 │
  │        ↓                                                    │
  │  priority    0  chain B (ufw 的 filter)                     │
  │        ↓                                                    │
  │  priority    0  chain C (你寫的 inet myfw input)             │
  │        ↓                                                    │
  │  priority   50  chain D (某個安全工具)                       │
  └─────────────────────────────────────────────────────────────┘

  ★★★★★ 規則：
  · 封包會依序經過所有掛在同一個 hook 的 base chain
  · 任何一個 chain 裡的規則說 drop / reject → 立刻結束，封包死掉
  · 某個 chain 說 accept → 只代表「這個 chain 放行」，
    後面的 chain 還是會看，還是可能把它 drop 掉
  · 全部走完都沒被 drop，才真的通過
```

實務含意（★★★★★ 記住這三句）：

1. **accept 不是最終判決，drop 才是。**
2. **你自己寫的 table 不會取代 ufw 的 table，兩個都在跑。**
3. **同一台機器只該有一個防火牆負責人。** 要嘛全用 ufw、要嘛全用手寫 nftables，
   混用的結果是三個月後沒人搞得清楚為什麼某個埠不通。

> [!tip] ★★★★ 混用時的正確做法
> 如果你已經在用 ufw、只是想補一個 ufw 做不到的功能（例如封鎖一個大 IP 清單），
> **不要另外建一個新的 base chain 去 accept**，那沒有意義（accept 不覆蓋別人的 drop）。
> 正確做法是：**另建一個只負責 drop 的 chain**，priority 設得比 ufw 更早（例如 `-10`），
> 讓惡意 IP 在還沒進 ufw 之前就被丟掉。本篇實戰範例會示範。

### 什麼時候該跳下來寫 nftables ★★★★

| 需求 | ufw 做得到嗎 | nftables 怎麼做 |
| --- | --- | --- |
| 開／關幾個埠、限制來源網段 | ★★★★★ 做得到，**請用 ufw** | 不必 |
| ★★★★ 封鎖數千～數十萬個惡意 IP | ✗ 一條一條加會讓規則集爆炸、效能崩潰 | **named set**，一條規則 ＋ 一個集合，O(1) 查找 |
| ★★★★ 「這個埠每秒最多 20 個新連線」 | ✗ 只有硬編碼的 `limit`（30 秒 6 次） | `limit rate 20/second` |
| ★★★★ 「每個來源 IP 分別限流」 | ✗ | dynamic set ＋ `limit rate over` |
| ★★★★ DNAT／SNAT（埠轉發、NAT 閘道） | ✗ `ufw route` 只能過濾 | `type nat hook prerouting` ＋ `dnat to` |
| ★★★ 「A 網段走這條路、B 網段走那條」 | ✗ | verdict map（`vmap`） |
| ★★★ 依封包標記／TOS／連線標記分流 | ✗ | `meta mark`、`ct mark` |
| ★★★ 一次原子套用整份規則（不留半套） | △ `ufw reload` 是逐條的 | ★★★★ `nft -f` 是**單一交易**，全成功或全失敗 |
| ★★★ 同一份規則同時涵蓋 IPv4 與 IPv6 | △ 要寫兩次 | ★★★★ `inet` family 一次搞定 |

> [!note] ★★★★★ 一句話判斷
> **「我需要的東西，`ufw` 的語法有對應的關鍵字嗎？」**
> 有 → 用 ufw。沒有 → 才考慮 nftables。
> 不要因為「nftables 比較高級」就把一台只需要開 80／443／22 的機器改成手寫規則集 ——
> 那只會增加交接成本與出錯機率。

### nftables 的結構：五個層級 ★★★

```text
  ruleset（整台機器的規則集，nft list ruleset 看到的全部）
    │
    ├── table  <family> <名稱>          ← 容器，family 決定管哪種流量
    │     │
    │     ├── chain <名稱> { type ... hook ... priority ... ; policy ... ; }
    │     │     │                        ↑ base chain：掛在 netfilter hook 上
    │     │     ├── rule                 ↑ regular chain：沒有 hook，靠 jump 進來
    │     │     ├── rule
    │     │     └── rule
    │     │
    │     ├── set <名稱> { type ... }    ← 位址／埠的集合
    │     └── map <名稱> { type ... : ... }  ← 查表對應
    │
    └── table ...
```

**family（家族）** ★★★

| family | 管什麼 | 建議 |
| --- | --- | --- |
| `inet` | ★★★★★ IPv4 ＋ IPv6 一起 | **新寫的規則一律用這個**，一份規則兩種協定都涵蓋 |
| `ip` | 只有 IPv4 | 只在需要 IPv4 專屬功能（例如 IPv4 NAT）時用 |
| `ip6` | 只有 IPv6 | 同上 |
| `arp` | ARP 封包 | 很少用 |
| `bridge` | 橋接流量 | ★★ 虛擬化主機的橋接網路過濾會用到 |
| `netdev` | 網卡 ingress，最早的攔截點 | ★★★ 做 DDoS 前置過濾用 |

**chain type 與 hook** ★★★

| type | 可用的 hook | 用途 |
| --- | --- | --- |
| `filter` | prerouting, input, forward, output, postrouting | ★★★★★ 過濾，九成規則都在這 |
| `nat` | prerouting, input, output, postrouting | ★★★★ 位址轉換 |
| `route` | output | ★★ 改路由決策 |

**priority（優先序）** ★★★

數字**越小越先執行**。nftables 提供了名稱常數：

| 名稱 | 數值 | 對應 iptables 的表 |
| --- | --- | --- |
| `raw` | -300 | raw |
| `mangle` | -150 | mangle |
| `dstnat` | -100 | nat (PREROUTING) |
| ★★★★★ `filter` | 0 | filter |
| `security` | 50 | security |
| `srcnat` | 100 | nat (POSTROUTING) |

★★★ 寫 `priority 0;` 跟 `priority filter;` 是一樣的。
要讓自己的 chain 比 ufw 更早執行就寫負數，例如 `priority -10;`。

**policy（預設判決）** ★★★★★

```text
  policy accept   ← chain 裡沒有規則命中時放行（預設值）
  policy drop     ← chain 裡沒有規則命中時丟棄
```

> [!danger] ★★★★★ `policy drop` 是最常見的自鎖原因
> 一個 `type filter hook input priority 0; policy drop;` 的 chain，
> **一建立就立刻開始丟棄所有還沒被規則放行的封包，包含你這條 SSH**。
> 標準做法是：**先建 `policy accept` 的 chain、把規則寫完、測試通過，
> 最後才把 policy 改成 drop**。或者更安全 —— 整份規則寫成檔案，
> 用 `nft -c -f` 檢查後一次 `nft -f` 原子套用（見〈持久化與原子套用〉）。

### 封包路徑：hook 的順序 ★★★

```text
                        ┌────────────────┐
                 ┌─────▶│  本機程序       │─────┐
                 │      │ (nginx/sshd 等) │     │
                 │      └────────────────┘     │
             ┌───┴────┐                   ┌────▼─────┐
             │ input  │                   │  output  │
             └───▲────┘                   └────┬─────┘
                 │                             │
  網卡 ──▶ ┌─────┴──────┐              ┌────────▼───────┐ ──▶ 網卡
  ingress  │ prerouting │──▶ 路由決策 ──│  postrouting   │
           │ (含 dstnat)│      │        │  (含 srcnat)   │
           └────────────┘      │        └────────▲───────┘
                               │                 │
                          ┌────▼─────┐           │
                          │ forward  │───────────┘
                          └──────────┘
```

★★★★★ **關鍵：目的地是本機的封包走 `input`，要轉給別人的走 `forward`。**
這正是第 02 篇「Docker 繞過 ufw」的原理 —— Docker 在 prerouting 做了 dnat，
把目的地改成容器 IP，封包因此走 forward 而不是 input，
而 ufw 的使用者規則掛在 input。

## 環境準備與安裝

### 檢查 nftables ★★★

```bash
sudo nft --version
```

```text
nftables v1.0.9 (Old Doc Yak #3)
```

沒有的話：

```bash
sudo apt update
sudo apt install -y nftables
```

```bash
systemctl status nftables --no-pager
```

```text
○ nftables.service - nftables
     Loaded: loaded (/usr/lib/systemd/system/nftables.service; disabled; preset: enabled)
     Active: inactive (dead)
       Docs: man:nft(8)
             http://wiki.nftables.org
```

★★★★ **`nftables.service` 只做一件事：開機時把 `/etc/nftables.conf` 載入。**
它不是一個常駐服務（`Active: inactive (dead)` 在載入完成後是正常的）。

### ★★★★★ 看清楚現在有什麼規則

**動任何東西之前，先完整記錄現況。**

```bash
sudo nft list ruleset | sudo tee /root/nft-before-$(date +%F-%H%M).nft
```

一台已經在跑 ufw 的機器，你會看到：

```text
table ip filter {
	chain INPUT {
		type filter hook input priority filter; policy drop;
		counter packets 1204 bytes 98432 jump ufw-before-logging-input
		counter packets 1204 bytes 98432 jump ufw-before-input
		counter packets 42 bytes 2520 jump ufw-after-input
		counter packets 42 bytes 2520 jump ufw-after-logging-input
		counter packets 42 bytes 2520 jump ufw-reject-input
		counter packets 42 bytes 2520 jump ufw-track-input
	}

	chain FORWARD {
		type filter hook forward priority filter; policy drop;
		...
	}
	...
	chain ufw-user-input {
		tcp dport 22 counter packets 18 bytes 1080 accept
		tcp dport 80 counter packets 340 bytes 20400 accept
		...
	}
}
```

★★★★ 幾個要注意的地方：

| 觀察 | 意思 |
| --- | --- |
| `table ip filter` | ufw 用的是 **iptables 相容層**產生的 table，名稱是大寫的 `INPUT`／`FORWARD`／`OUTPUT` |
| `counter packets ... bytes ...` | ★★★★ iptables 相容層會自動加 counter，**這是判斷「這條規則有沒有被命中過」的關鍵** |
| `jump ufw-before-input` | ufw 的分層結構被完整翻譯過來了 |
| ★★★ 沒有 `table inet` | 代表沒有人手寫過原生 nftables 規則 |

看某一個 table：

```bash
sudo nft list table ip filter
```

看規則的 handle（刪除規則會用到）：

```bash
sudo nft -a list chain ip filter ufw-user-input
```

```text
table ip filter {
	chain ufw-user-input { # handle 14
		tcp dport 22 counter packets 18 bytes 1080 accept # handle 21
		tcp dport 80 counter packets 340 bytes 20400 accept # handle 22
	}
}
```

★★★★ `# handle 21` 就是刪除這條規則要用的號碼。

### 其他常用檢視指令 ★★★

```bash
# 只列出所有 table 的名字
sudo nft list tables
```

```text
table ip filter
table ip6 filter
table ip nat
```

```bash
# 只列出 set 的內容
sudo nft list sets
```

```bash
# ★★★★ 即時監看規則變動（另一個視窗開著，看誰在改規則）
sudo nft monitor
```

```text
add rule ip filter ufw-user-input tcp dport 8080 counter accept
```

★★★★ `nft monitor` 在排查「規則一直被別人改掉」（Docker、Fail2ban、某個腳本）時非常好用。

## 基礎設定

> [!danger] ★★★★★ 從這裡開始，每個指令都會立刻改變封包行為
> 請先確認：
> - 你在 tmux 裡（`tmux new -s nft`）
> - 已排好自動還原（見下方）
> - 有第二條 SSH 連線與可用的主控台
>
> **本節的示範一律用一個獨立的測試 table `inet lab`，
> 而且 chain 的 policy 一律先設 `accept`**，這樣就算寫錯也不會鎖死自己。

### 先架好安全網 ★★★★★

```bash
sudo apt install -y at
sudo systemctl enable --now atd

# 先把現況存成還原腳本
sudo sh -c 'echo "#!/usr/sbin/nft -f" > /root/nft-restore.nft'
sudo sh -c 'echo "flush ruleset" >> /root/nft-restore.nft'
sudo sh -c 'nft list ruleset >> /root/nft-restore.nft'
sudo chmod 700 /root/nft-restore.nft

# 排 10 分鐘後自動還原
echo "/usr/sbin/nft -f /root/nft-restore.nft" | sudo at now + 10 minutes
```

```text
warning: commands will be executed using /bin/sh
job 4 at Wed Sep  3 14:15:00 2026
```

> [!warning] ★★★ 這個還原腳本有個前提
> `nft list ruleset` 的輸出**不保證可以原封不動餵回 `nft -f`** ——
> 少數情況（例如某些含有特殊 set 定義的規則）會有語法差異。
> ★★★★ **存好之後立刻在測試機用 `sudo nft -c -f /root/nft-restore.nft` 驗一次**：
> ```bash
> sudo nft -c -f /root/nft-restore.nft && echo "還原腳本語法 OK"
> ```
> ```text
> 還原腳本語法 OK
> ```
> 如果報錯，改用「ufw 主線的機器就備份 `/etc/ufw/` 並用 `ufw reload` 還原」這條路。

### 建立 table 與 chain ★★★★

```bash
sudo nft add table inet lab
sudo nft list tables
```

```text
table ip filter
table ip6 filter
table inet lab
```

```bash
# ★★★ policy 先用 accept，寫完測完再改 drop
sudo nft add chain inet lab input '{ type filter hook input priority 0 ; policy accept ; }'
sudo nft list table inet lab
```

```text
table inet lab {
	chain input {
		type filter hook input priority filter; policy accept;
	}
}
```

★★★ 大括號要用單引號包起來，否則 shell 會把 `{` `}` 當成自己的語法。

### 加規則 ★★★★★

**最重要的三條基礎規則**（★★★★★ 順序不能反）：

```bash
# ① loopback 一律放行 —— 少了這條，本機服務之間會斷（MySQL socket、DNS 快取、監控）
sudo nft add rule inet lab input iif lo accept

# ② 已建立與相關連線一律放行 —— 少了這條，你連 DNS 查詢都收不到回應
sudo nft add rule inet lab input ct state established,related accept

# ③ 無效封包丟掉
sudo nft add rule inet lab input ct state invalid drop
```

> [!danger] ★★★★★ 漏掉 `ct state established,related accept` 是新手第一大災難
> 沒有這條，你的主機**發得出去、收不回來**：
> `apt update` 卡住、DNS 解析失敗、你現在這條 SSH 在下一個封包就斷。
> 而且症狀會讓人誤判成「網路壞了」而不是「防火牆設錯了」。
> **這條永遠要放在規則集最前面。**

**業務規則**：

```bash
# 單一埠
sudo nft add rule inet lab input tcp dport 22 accept

# ★★★★ 多個埠用集合（anonymous set），比寫三條規則有效率
sudo nft add rule inet lab input tcp dport { 80, 443 } accept

# 限制來源
sudo nft add rule inet lab input ip saddr 192.168.10.0/24 tcp dport 3306 accept

# 限制來源 ＋ 介面
sudo nft add rule inet lab input iifname "ens192" ip saddr 192.168.99.0/24 tcp dport 22 accept

# 埠範圍（★★★ nftables 用連字號，跟 ufw 的冒號不一樣！）
sudo nft add rule inet lab input udp dport 30000-30100 accept

# ICMP（★★★ inet family 要同時處理 v4 與 v6）
sudo nft add rule inet lab input meta l4proto { icmp, ipv6-icmp } accept
```

檢視結果：

```bash
sudo nft list table inet lab
```

```text
table inet lab {
	chain input {
		type filter hook input priority filter; policy accept;
		iif "lo" accept
		ct state established,related accept
		ct state invalid drop
		tcp dport 22 accept
		tcp dport { 80, 443 } accept
		ip saddr 192.168.10.0/24 tcp dport 3306 accept
		iifname "ens192" ip saddr 192.168.99.0/24 tcp dport 22 accept
		udp dport 30000-30100 accept
		meta l4proto { icmp, ipv6-icmp } accept
	}
}
```

> [!warning] ★★★★ `iif` 與 `iifname` 不一樣
> - `iif "lo"` —— 比對**介面索引（index）**，在規則載入時就解析成數字，比較快，
>   但**介面必須存在**，而且介面重建（例如 VLAN 介面重新建立）後索引會變。
> - `iifname "ens192"` —— 比對**介面名稱字串**，每個封包都比一次字串，稍慢，
>   但介面不存在時也能載入規則。
>
> ★★★ 實務建議：**`lo` 用 `iif`（它永遠存在），其他介面用 `iifname`**
> （尤其是虛擬介面、Docker 介面、開機時可能還沒 up 的介面）。

### 插入、刪除、清空 ★★★★

```bash
# 插到 chain 最前面
sudo nft insert rule inet lab input tcp dport 8443 accept

# 插到指定位置（position 用的是 handle 號碼）
sudo nft -a list chain inet lab input
```

```text
table inet lab {
	chain input { # handle 2
		tcp dport 8443 accept # handle 12
		iif "lo" accept # handle 3
		ct state established,related accept # handle 4
		...
	}
}
```

```bash
sudo nft insert rule inet lab input position 4 tcp dport 8080 accept
```

★★★ `insert ... position N` 是插在 handle N 的規則**之前**，
`add ... position N` 是插在它**之後**。

```bash
# 刪除單一規則（一定要用 handle，nftables 沒有「依號碼刪」）
sudo nft delete rule inet lab input handle 12
```

```bash
# 清空一個 chain 裡的所有規則（chain 本身還在）
sudo nft flush chain inet lab input

# 刪掉整個 chain（必須先 flush，否則會 Device or resource busy）
sudo nft delete chain inet lab input

# 刪掉整個 table（★★★ 會連同裡面的 chain、set、rule 一起消失）
sudo nft delete table inet lab
```

> [!danger] ★★★★★ `nft flush ruleset` —— 一行把整台機器的防火牆清空
> ```bash
> sudo nft flush ruleset
> ```
> **沒有確認提示、沒有備份、瞬間完成。**
> 執行之後：
> - ufw 的規則全部消失（`ufw status` 還是會說 active，但實際上什麼都沒擋）
> - Docker 的 NAT 規則全部消失（容器對外網路立刻斷）
> - Fail2ban 的封鎖 set 全部消失
> - 如果你的 chain policy 原本是 drop，flush 之後變成「沒有 chain」＝ 全放行，
>   **不會把你鎖在外面，但會把整台機器裸奔**
>
> ★★★★★ 唯一安全的用法是**放在 `nft -f` 的規則檔第一行**，
> 讓它跟後面的規則一起在同一個交易裡執行（見下一節）。
> 單獨在指令列打這行，只有在「已經被鎖在外面、要緊急解鎖」時才做。
>
> 清完之後記得復原：`sudo ufw reload`（ufw 主線）或
> `sudo systemctl restart docker`（恢復 Docker 的 NAT 規則）。

### 持久化與原子套用 ★★★★★

**手動加的規則重開機就沒了。** 要持久化就寫進 `/etc/nftables.conf`。

```bash
sudo cat /etc/nftables.conf
```

```text
#!/usr/sbin/nft -f
# This file is autogenerated by nftables. Do not edit.

flush ruleset

table inet filter {
	chain input {
		type filter hook input priority 0;
	}
	chain forward {
		type filter hook forward priority 0;
	}
	chain output {
		type filter hook output priority 0;
	}
}
```

★★★★★ 這個檔案的三個關鍵：

| 元素 | 為什麼重要 |
| --- | --- |
| `#!/usr/sbin/nft -f` | ★★★ shebang，讓檔案可以直接執行 |
| `flush ruleset` | ★★★★★ **先清空再載入**，確保每次載入的結果都一樣（冪等）。少了它，重複載入會產生重複規則 |
| ★★★★★ **整份檔案是一個交易** | `nft -f` 的語意是「全部成功才套用，任何一行有錯就完全不套用」 |

**★★★★★ 原子套用是 nftables 相對 iptables 最大的優勢之一。**
iptables 是一條一條下的，中途出錯會留下半套規則（可能剛好把 SSH 那條漏掉）；
nftables 的 `nft -f` 要嘛全部生效、要嘛完全不動，**不會有中間狀態**。

**標準工作流程** ★★★★★：

```bash
# 1. 編輯
sudo vim /etc/nftables.conf

# 2. ★★★★★ 檢查語法（-c = check，只解析不套用）
sudo nft -c -f /etc/nftables.conf
```

語法沒問題時**完全沒有輸出**。有問題時：

```text
/etc/nftables.conf:14:20-24: Error: syntax error, unexpected string
		tcp dport 22 acept
		             ^^^^^
```

```bash
# 3. 排好自動還原
echo "/usr/sbin/nft -f /root/nft-restore.nft" | sudo at now + 5 minutes

# 4. 套用
sudo nft -f /etc/nftables.conf

# 5. 驗證（★★★★★ 從第二個視窗與外部主機測）
sudo nft list ruleset

# 6. 確認沒事就取消還原
atq && sudo atrm <job號碼>

# 7. 開機自啟
sudo systemctl enable nftables
```

```text
Created symlink /etc/systemd/system/multi-user.target.wants/nftables.service → /usr/lib/systemd/system/nftables.service.
```

> [!danger] ★★★★★ ufw 與 `/etc/nftables.conf` 不可以同時啟用
> 兩個都 enable 的話，開機時的載入順序不保證，而且 `/etc/nftables.conf` 裡的
> `flush ruleset` **會把 ufw 剛載入的規則清掉**（或反過來）。
> 結果是「開機後防火牆狀態每次都不一樣」—— 最難查的那種故障。
>
> **二選一**：
> ```bash
> # 選 ufw
> sudo systemctl disable nftables
> sudo ufw enable
>
> # 選手寫 nftables
> sudo ufw disable
> sudo systemctl enable nftables
> ```

## 進階設定與調校

### ★★★★ set：大量 IP 封鎖的正確做法

**問題**：你拿到一份威脅情資，裡面有 4 萬個惡意 IP 要封鎖。

**錯誤做法**：4 萬條 `ufw deny from <IP>` 規則。
規則集會變成 4 萬條線性掃描，每個封包都要比對到底，CPU 直接爆掉，
而且 `ufw status` 會噴出 4 萬行沒人看得懂。

**正確做法**：一個 set ＋ 一條規則。nftables 的 set 底層用 hash 或 red-black tree，
查找是 O(1) 或 O(log n)。

**宣告 set** ★★★★：

```bash
sudo nft add set inet lab blacklist4 '{ type ipv4_addr ; flags interval ; }'
sudo nft add set inet lab blacklist6 '{ type ipv6_addr ; flags interval ; }'
```

| 選項 | 意思 |
| --- | --- |
| `type ipv4_addr` | ★★★★ 元素型別。其他常見：`ipv6_addr`、`inet_service`（埠）、`ether_addr`（MAC）、`ifname` |
| `flags interval` | ★★★★★ **允許放 CIDR 網段而不只是單一 IP**。要塞 `203.0.113.0/24` 這種就必須加 |
| `flags timeout` | ★★★★ 允許元素有存活時間，過期自動移除（Fail2ban 的封鎖就靠這個） |
| `flags dynamic` | ★★★ 允許規則在執行期間動態新增元素 |
| `size N` | ★★★ 上限元素數。★★★★ **大清單一定要設**，否則預設上限可能塞不下 |
| `auto-merge` | ★★★ 自動合併重疊的網段 |
| `counter` | ★★ 每個元素各自計數，好用但耗記憶體 |

**加元素**：

```bash
sudo nft add element inet lab blacklist4 '{ 203.0.113.5, 198.51.100.0/24, 192.0.2.77 }'
sudo nft list set inet lab blacklist4
```

```text
table inet lab {
	set blacklist4 {
		type ipv4_addr
		flags interval
		elements = { 192.0.2.77, 198.51.100.0/24,
			     203.0.113.5 }
	}
}
```

**用 set 寫規則** ★★★★★：

```bash
sudo nft insert rule inet lab input ip saddr @blacklist4 counter drop
sudo nft insert rule inet lab input ip6 saddr @blacklist6 counter drop
```

★★★★ `@` 前綴代表「引用具名 set」。`counter` 讓你之後能看到擋了幾個封包。

**移除元素**：

```bash
sudo nft delete element inet lab blacklist4 '{ 203.0.113.5 }'
```

**清空 set**：

```bash
sudo nft flush set inet lab blacklist4
```

**從檔案批次匯入 4 萬個 IP** ★★★★★：

一條一條 `nft add element` 會很慢（每次都是一個 syscall 交易）。
正確做法是產生一個 nft 檔一次載入：

```bash
# 假設 /root/threat-ips.txt 一行一個 IP 或 CIDR
{
  echo "#!/usr/sbin/nft -f"
  echo "flush set inet lab blacklist4"
  echo -n "add element inet lab blacklist4 { "
  paste -sd, /root/threat-ips.txt
  echo " }"
} | sudo tee /root/blacklist-load.nft > /dev/null

sudo nft -c -f /root/blacklist-load.nft && sudo nft -f /root/blacklist-load.nft
```

驗證：

```bash
sudo nft list set inet lab blacklist4 | grep -c ','
```

> [!warning] ★★★ 未實機驗證
> 上面的 `paste -sd,` 產生的清單，在元素數量非常大（數十萬）時可能超過
> 單一 nft 指令的解析上限。★★★★ **本專案未驗證過 4 萬筆以上的實際載入時間與記憶體用量**。
> 大清單請分批（例如每批 5000 筆）測試，並用 `sudo nft list set ... | wc -l` 確認實際載入數量。
> 另外記得設 `size`：
> ```bash
> sudo nft add set inet lab blacklist4 '{ type ipv4_addr ; flags interval ; size 200000 ; }'
> ```

**帶 timeout 的自動過期 set** ★★★★（Fail2ban 的做法）：

```bash
sudo nft add set inet lab banned '{ type ipv4_addr ; flags timeout ; timeout 1h ; }'
sudo nft add element inet lab banned '{ 203.0.113.99 }'
sudo nft list set inet lab banned
```

```text
table inet lab {
	set banned {
		type ipv4_addr
		flags timeout
		timeout 1h
		elements = { 203.0.113.99 expires 59m54s }
	}
}
```

★★★★ `expires 59m54s` 就是剩餘時間。時間到會自動移除，不需要任何清理腳本 ——
這正是 [[090-02-05-guide-防護-Fail2ban入侵防護]] 用 nftables 後端時的運作方式。

### ★★★★ map 與 verdict map

**map** 是「查表得到一個值」，**verdict map（`vmap`）** 是「查表得到一個判決」。

```bash
# verdict map：依目的埠決定判決，取代一長串 if-else
sudo nft add rule inet lab input tcp dport vmap \
  '{ 22 : accept, 80 : accept, 443 : accept, 3306 : drop }'
```

```bash
sudo nft list table inet lab | grep vmap
```

```text
		tcp dport vmap { 22 : accept, 80 : accept, 443 : accept, 3306 : drop }
```

★★★ vmap 的好處是**查找而不是逐條比對**，埠數量多的時候差別明顯。

**具名 map**（★★★ 適合「不同來源網段對應不同處理」）：

```bash
sudo nft add map inet lab srcpolicy '{ type ipv4_addr : verdict ; flags interval ; }'
sudo nft add element inet lab srcpolicy \
  '{ 192.168.99.0/24 : accept, 198.51.100.0/24 : drop }'
sudo nft add rule inet lab input ip saddr vmap @srcpolicy
```

> [!warning] ★★★ 未實機驗證
> 具名 verdict map 搭配 `flags interval` 的行為（尤其是網段重疊時的優先順序）
> 在不同版本有差異。**請先在測試機用實際流量驗證每個網段的判決結果**，
> 不要直接套到正式環境。

### ★★★★ 速率限制

**全域限流**（整條規則共用一個計數器）：

```bash
# 每秒最多 20 個新的 HTTP 連線，burst 允許瞬間 50 個
sudo nft add rule inet lab input tcp dport 80 ct state new \
  limit rate 20/second burst 50 packets counter accept
```

★★★ 支援的單位：`/second`、`/minute`、`/hour`、`/day`；
也可以限流量：`limit rate 10 mbytes/second`。

**★★★★ per-IP 限流**（每個來源 IP 各自算，這是 ufw 完全做不到的）：

```bash
# 1. 建一個 dynamic set 存追蹤狀態
sudo nft add set inet lab sshmeter \
  '{ type ipv4_addr ; flags dynamic,timeout ; timeout 1m ; size 65535 ; }'

# 2. 超過速率的來源丟棄
sudo nft add rule inet lab input tcp dport 22 ct state new \
  add @sshmeter '{ ip saddr limit rate over 6/minute }' counter drop

# 3. 沒超過的放行
sudo nft add rule inet lab input tcp dport 22 ct state new counter accept
```

> [!warning] ★★★★★ 未實機驗證
> **這是本篇最需要實測的一段。** dynamic set ＋ `limit rate over` 的語法
> 在 nftables 0.9.x 與 1.0.x 之間有過調整，而且 `add @set { ... }` 這種
> 「在規則裡動態新增元素」的寫法對引號與大括號的處理很敏感。
>
> 套用前務必：
> 1. `sudo nft -c -f <檔案>` 確認語法能解析
> 2. 在測試機用 `for i in $(seq 1 10); do nc -zv -w1 <IP> 22; done` 實測第 7 次以後有沒有被擋
> 3. `sudo nft list set inet lab sshmeter` 看有沒有元素被加進去
>
> ★★★★ 如果你只是要防 SSH 暴力破解，**[[090-02-05-guide-防護-Fail2ban入侵防護]]
> 是更成熟、更好維護的選擇** —— 它有日誌分析、白名單、通知、解封等完整功能。
> 這段語法適合的場景是「純封包層級的限流」（例如擋 SYN flood）。

**★★★ 連線數限制**（同一個 IP 最多幾條並行連線）：

```bash
sudo nft add rule inet lab input tcp dport 443 ct state new \
  meter connlimit '{ ip saddr ct count over 50 }' counter drop
```

> [!warning] ★★★ 未實機驗證
> `ct count over N` 需要 conntrack 支援，且 `meter` 語法在新版建議改用
> 具名 dynamic set。請在測試機驗證。

### ★★★ NAT

ufw 完全做不到的部分。

**埠轉發（DNAT）**：

```bash
sudo nft add table ip natlab
sudo nft add chain ip natlab prerouting \
  '{ type nat hook prerouting priority dstnat ; policy accept ; }'
sudo nft add chain ip natlab postrouting \
  '{ type nat hook postrouting priority srcnat ; policy accept ; }'

# 外部連 :8443 → 轉給內部 192.168.20.10:443
sudo nft add rule ip natlab prerouting iifname "ens192" tcp dport 8443 \
  dnat to 192.168.20.10:443
```

**NAT 上網（masquerade）**：

```bash
sudo nft add rule ip natlab postrouting oifname "ens192" \
  ip saddr 192.168.20.0/24 masquerade
```

★★★★ NAT 還需要開啟 IP 轉發，否則封包根本不會進 forward：

```bash
echo 'net.ipv4.ip_forward=1' | sudo tee /etc/sysctl.d/99-forward.conf
sudo sysctl --system | grep ip_forward
```

```text
net.ipv4.ip_forward = 1
```

> [!danger] ★★★★ 開啟 IP 轉發等於把這台機器變成路由器
> 一台不該當路由器的伺服器開了 `ip_forward=1`，就可能被拿來當跳板繞過網段隔離。
> **只在真的要做 NAT／VPN 閘道的機器上開**，並且同時把 forward chain 的
> policy 設成 drop、只放行必要流量。

### ★★★ counter 與除錯

```bash
# 幫規則加 counter
sudo nft add rule inet lab input tcp dport 3306 counter drop

# 看命中次數
sudo nft list table inet lab
```

```text
		tcp dport 3306 counter packets 27 bytes 1620 drop
```

★★★★★ **counter 是判斷「這條規則到底有沒有被執行到」的唯一可靠方法。**
`packets 0` 就代表封包根本沒走到這條規則（可能被前面的規則攔截了，
也可能封包根本沒到這台機器）。

```bash
# 歸零所有 counter，方便觀察某段時間的變化
sudo nft reset counters
```

**加日誌**：

```bash
sudo nft add rule inet lab input tcp dport 3306 log prefix '"MYSQL-DROP: " ' counter drop
sudo journalctl -k --grep 'MYSQL-DROP' -n 5 --no-pager
```

```text
Sep 03 14:32:11 web01 kernel: MYSQL-DROP: IN=ens192 OUT= MAC=00:50:56:9a:1b:2c:... SRC=192.168.99.10 DST=192.168.10.20 LEN=60 ... PROTO=TCP SPT=45120 DPT=3306 WINDOW=64240 RES=0x00 SYN URGP=0
```

★★★ 格式跟 ufw 日誌一樣（都是 kernel 的 nf_log 輸出），欄位意義見
[[090-02-02-guide-防火牆-ufw基礎與實務]] 的日誌章節。

> [!warning] ★★★★ `log` 沒有速率限制會寫爆磁碟
> 一定要搭配 `limit`：
> ```bash
> sudo nft add rule inet lab input tcp dport 3306 \
>   limit rate 5/minute log prefix '"MYSQL-DROP: " ' counter drop
> ```
> ★★★ 注意這樣寫的語意是「每分鐘最多記 5 筆，**超過的封包不會被 drop**」——
> 因為 limit 不匹配時整條規則就不匹配了。
> 正確寫法是拆成兩條：一條只負責 log（帶 limit），一條負責 drop。

### iptables 對照 ★★★

既有機器上一定還會看到 iptables 語法，你至少要看得懂。

| iptables | nftables |
| --- | --- |
| `-A INPUT` | `add rule inet filter input` |
| `-I INPUT 1` | `insert rule inet filter input` |
| `-p tcp --dport 22` | `tcp dport 22` |
| `-s 192.168.10.0/24` | `ip saddr 192.168.10.0/24` |
| `-d 10.0.0.1` | `ip daddr 10.0.0.1` |
| `-i eth0` | `iifname "eth0"` |
| `-o eth0` | `oifname "eth0"` |
| `-m state --state ESTABLISHED,RELATED` | ★★★★ `ct state established,related` |
| `-m multiport --dports 80,443` | ★★★★ `tcp dport { 80, 443 }` |
| `-j ACCEPT` / `-j DROP` / `-j REJECT` | `accept` / `drop` / `reject` |
| `-j LOG --log-prefix "X: "` | `log prefix "X: "` |
| `-j MASQUERADE` | `masquerade` |
| `-j DNAT --to-destination 10.0.0.5:443` | `dnat to 10.0.0.5:443` |
| `-m limit --limit 5/min` | `limit rate 5/minute` |
| `-P INPUT DROP` | ★★★ chain 定義裡的 `policy drop` |
| `iptables -S` | `nft list ruleset` |
| `iptables -L -n -v` | `nft list ruleset`（counter 要規則自己帶） |
| `iptables-save > f` | `nft list ruleset > f` |
| `iptables-restore < f` | `nft -f f` |

**★★★★ `iptables-translate`：自動轉換工具**

```bash
iptables-translate -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -j ACCEPT
```

```text
nft 'add rule ip filter INPUT tcp dport 22 ct state new counter accept'
```

```bash
iptables-translate -t nat -A POSTROUTING -s 192.168.20.0/24 -o eth0 -j MASQUERADE
```

```text
nft 'add rule ip nat POSTROUTING oifname "eth0" ip saddr 192.168.20.0/24 counter masquerade'
```

**整份規則檔轉換**：

```bash
sudo iptables-save > /root/rules.v4
iptables-restore-translate -f /root/rules.v4 > /root/rules.nft
head -n 20 /root/rules.nft
```

```text
# Translated by iptables-restore-translate v1.8.10 on Wed Sep  3 14:40:12 2026
add table ip filter
add chain ip filter INPUT { type filter hook input priority 0; policy accept; }
add chain ip filter FORWARD { type filter hook forward priority 0; policy accept; }
add chain ip filter OUTPUT { type filter hook output priority 0; policy accept; }
add rule ip filter INPUT iif "lo" counter accept
add rule ip filter INPUT ct state established,related counter accept
add rule ip filter INPUT tcp dport 22 counter accept
```

> [!warning] ★★★★ 轉換結果不能直接上線
> `iptables-translate` 只做**語法轉換**，不做**語意最佳化**：
> - 它產生的是 `ip` family（只有 IPv4），不會幫你改成 `inet`
> - 它保留 iptables 的大寫 chain 名稱與扁平結構，不會重新設計
> - 少數 xtables 模組（例如某些 `-m` 模組）**沒有 nftables 對應，會轉不出來**
>
> ★★★ 正確用法是「拿它當草稿與對照表」，然後自己重新設計一份 `inet` family 的規則。

## 完整實戰範例

**情境**：把第 02 篇那台 `web01` 從 ufw 改成手寫 nftables，
規則邏輯完全一樣，**再加上兩條 ufw 做不到的**：
① 用 set 封鎖威脅情資 IP 清單；② HTTP 埠的新連線速率限制。

| 項目 | 值 |
| --- | --- |
| 主機 | `web01`，`192.168.10.20/24`，網卡 `ens192` |
| 管理網段 | `192.168.99.0/24` |
| 應用伺服器 | `192.168.10.31`、`192.168.10.32` |
| 監控主機 | `192.168.10.50` |
| 服務 | Nginx 80/443、MySQL 3306、node_exporter 9100、SSH 22 |

### 步驟 0：★★★★★ 架好三道保險

```bash
tmux new -s nft

sudo apt install -y at nftables
sudo systemctl enable --now atd

# ① 備份現況
sudo mkdir -p /root/fw-backup
sudo tar czf /root/fw-backup/ufw-$(date +%F).tar.gz /etc/ufw /etc/default/ufw
sudo nft list ruleset | sudo tee /root/fw-backup/nft-before-$(date +%F).txt > /dev/null

# ② 準備「緊急全開」還原腳本
sudo tee /root/fw-backup/panic-open.nft > /dev/null <<'EOF'
#!/usr/sbin/nft -f
flush ruleset
EOF
sudo chmod 700 /root/fw-backup/panic-open.nft
sudo nft -c -f /root/fw-backup/panic-open.nft && echo "panic 腳本語法 OK"
```

```text
panic 腳本語法 OK
```

```bash
# ③ 排 15 分鐘自動還原
echo "/usr/sbin/nft -f /root/fw-backup/panic-open.nft" | sudo at now + 15 minutes
atq
```

```text
7	Wed Sep  3 15:05:00 2026 a root
```

★★★★★ **另外開一個終端機視窗 SSH 進 web01，放著不要關。**

> [!danger] ★★★★★ `panic-open.nft` 只有 `flush ruleset`
> 執行它之後這台機器**完全沒有防火牆**，是裸奔狀態。
> 它是「解鎖用的緊急出口」，不是「還原到原本設定」。
> 解鎖之後請立刻修好規則再套用一次，不要放著不管。

### 步驟 1：確認要放行哪些埠 ★★★★

```bash
sudo ss -tlnp
```

```text
State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process
LISTEN 0      128        0.0.0.0:22          0.0.0.0:*     users:(("sshd",pid=812,fd=3))
LISTEN 0      511        0.0.0.0:80          0.0.0.0:*     users:(("nginx",pid=1123,fd=6))
LISTEN 0      511        0.0.0.0:443         0.0.0.0:*     users:(("nginx",pid=1123,fd=8))
LISTEN 0      151        0.0.0.0:3306        0.0.0.0:*     users:(("mysqld",pid=1401,fd=23))
LISTEN 0      4096             *:9100              *:*     users:(("node_exporter",pid=1520,fd=3))
LISTEN 0      128           [::]:22             [::]:*     users:(("sshd",pid=812,fd=4))
LISTEN 0      511           [::]:80             [::]:*     users:(("nginx",pid=1123,fd=7))
```

★★★★ 注意 22、80 同時綁在 IPv4 與 IPv6 —— 這就是為什麼要用 `inet` family。

```bash
# 確認自己的來源 IP，避免寫錯管理網段
who am i
```

```text
mis      pts/0        2026-09-03 14:50 (192.168.99.10)
```

### 步驟 2：停用 ufw（★★★★★ 二選一，不可並存）

```bash
sudo ufw disable
```

```text
Firewall stopped and disabled on system startup
```

```bash
sudo nft list ruleset
```

★★★ 這時應該幾乎是空的（可能還有 Docker 留下的 table）。
如果這台有 Docker，**下面的規則要額外處理 forward 鏈**（見步驟 7 的注意事項）。

### 步驟 3：寫規則檔 ★★★★★

```bash
sudo tee /etc/nftables.conf > /dev/null <<'EOF'
#!/usr/sbin/nft -f
#
# web01 主機防火牆
# 維護：資訊室系統組    最後修改：2026-09-03
# 對應文件：/root/fw-backup/README.md
#
# ★ 修改前務必：
#   1. tmux new -s nft
#   2. echo "/usr/sbin/nft -f /root/fw-backup/panic-open.nft" | at now + 10 minutes
#   3. nft -c -f /etc/nftables.conf   （語法檢查，無輸出代表 OK）
#   4. nft -f /etc/nftables.conf
#   5. 從外部實測後 atrm 取消還原

flush ruleset

# ── 定義 ────────────────────────────────────────────────
define MGMT_NET   = 192.168.10.0/24
define MGMT_VLAN  = 192.168.99.0/24
define APP_HOSTS  = { 192.168.10.31, 192.168.10.32 }
define MON_HOST   = 192.168.10.50
define WAN_IF     = "ens192"

table inet fw {

    # ── 威脅情資封鎖清單（★ 由 /root/fw-backup/threat-load.nft 載入）──
    set blacklist4 {
        type ipv4_addr
        flags interval
        size 200000
    }

    set blacklist6 {
        type ipv6_addr
        flags interval
        size 65536
    }

    chain input {
        type filter hook input priority 0; policy drop;

        # ① 基礎放行（★ 順序不可調換）
        iif lo accept comment "loopback"
        ct state established,related accept comment "已建立連線"
        ct state invalid counter drop comment "無效封包"

        # ② 威脅情資封鎖（放在業務規則之前）
        ip  saddr @blacklist4 counter drop comment "threat intel v4"
        ip6 saddr @blacklist6 counter drop comment "threat intel v6"

        # ③ ICMP（保留 ping 與 PMTU discovery，限速避免被當放大器）
        meta l4proto { icmp, ipv6-icmp } limit rate 10/second counter accept comment "icmp"

        # ④ SSH：只給管理網段，並限制每個來源的新連線速率
        iifname $WAN_IF ip saddr $MGMT_VLAN tcp dport 22 ct state new \
            limit rate 10/minute burst 5 packets counter accept comment "ssh mgmt"

        # ⑤ Web：對全世界開放，新連線速率限制（★ ufw 做不到的部分）
        tcp dport { 80, 443 } ct state new \
            limit rate 200/second burst 500 packets counter accept comment "web"

        # ⑥ MySQL：只給兩台 app server
        ip saddr $APP_HOSTS tcp dport 3306 counter accept comment "app -> mysql"

        # ⑦ node_exporter：只給 Prometheus
        ip saddr $MON_HOST tcp dport 9100 counter accept comment "prometheus scrape"

        # ⑧ 記錄被丟棄的封包（限速，避免寫爆 /var）
        limit rate 5/minute burst 10 packets \
            log prefix "NFT-DROP-IN: " level info comment "log drops"

        # ⑨ 其他一律 drop（由 policy drop 處理）
        counter comment "dropped by policy"
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
        counter comment "no forwarding on this host"
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }
}
EOF
```

★★★★ 這份檔案的設計重點：

| 設計 | 理由 |
| --- | --- |
| ★★★★★ `inet` family | 一份規則同時涵蓋 IPv4 與 IPv6，不用寫兩套 |
| ★★★★ `define` 變數 | 網段改了只要改一個地方，減少漏改 |
| ★★★★ 每條規則都有 `comment` | 半年後接手的人看得懂為什麼要開這個埠 |
| ★★★★ 每條規則都有 `counter` | 排查時能立刻知道哪條被命中 |
| ★★★★ 威脅情資規則放在最前面 | 惡意 IP 越早丟掉，後面的規則越省 CPU |
| ★★★★ 檔頭寫了改規則的 SOP | 這是實務上最有價值的一段註解 |
| ★★★ `output` policy accept | 出向不管制（跟第 02 篇的 ufw 設定一致） |

### 步驟 4：★★★★★ 語法檢查（絕對不能跳過）

```bash
sudo nft -c -f /etc/nftables.conf
```

沒有輸出 = 語法正確。故意打錯試試看：

```bash
sudo sed -i 's/tcp dport 22 ct state new/tcp dport 22 ct staet new/' /tmp/bad.nft 2>/dev/null
sudo nft -c -f /etc/nftables.conf
```

有錯時的樣子：

```text
/etc/nftables.conf:53:34-38: Error: syntax error, unexpected string, expecting comma or newline
            ... tcp dport 22 ct staet new \
                               ^^^^^
```

★★★★★ **`-c` 只解析不套用**，是 nftables 相對 ufw 的一大優勢 ——
你可以在完全不影響現行流量的情況下驗證整份規則。

### 步驟 5：套用 ★★★★★

```bash
sudo nft -f /etc/nftables.conf
```

★★★★★ 沒有輸出就是成功，而且是**原子套用** —— 整份規則同時生效，
不會出現「SSH 那條還沒下、policy drop 已經生效」的空窗期。

立刻在**第二個視窗**測試重新登入：

```bash
ssh mis@192.168.10.20
```

```text
mis@192.168.10.20's password:
Welcome to Ubuntu 24.04.3 LTS (GNU/Linux 6.8.0-45-generic x86_64)
```

★★★★★ **連得上才繼續。**

### 步驟 6：檢視結果 ★★★★

```bash
sudo nft list ruleset
```

```text
table inet fw {
	set blacklist4 {
		type ipv4_addr
		size 200000
		flags interval
	}

	set blacklist6 {
		type ipv6_addr
		size 65536
		flags interval
	}

	chain input {
		type filter hook input priority filter; policy drop;
		iif "lo" accept comment "loopback"
		ct state established,related accept comment "已建立連線"
		ct state invalid counter packets 0 bytes 0 drop comment "無效封包"
		ip saddr @blacklist4 counter packets 0 bytes 0 drop comment "threat intel v4"
		ip6 saddr @blacklist6 counter packets 0 bytes 0 drop comment "threat intel v6"
		meta l4proto { icmp, ipv6-icmp } limit rate 10/second counter packets 3 bytes 252 accept comment "icmp"
		iifname "ens192" ip saddr 192.168.99.0/24 tcp dport 22 ct state new limit rate 10/minute burst 5 packets counter packets 2 bytes 120 accept comment "ssh mgmt"
		tcp dport { 80, 443 } ct state new limit rate 200/second burst 500 packets counter packets 14 bytes 840 accept comment "web"
		ip saddr { 192.168.10.31, 192.168.10.32 } tcp dport 3306 counter packets 0 bytes 0 accept comment "app -> mysql"
		ip saddr 192.168.10.50 tcp dport 9100 counter packets 0 bytes 0 accept comment "prometheus scrape"
		limit rate 5/minute burst 10 packets log prefix "NFT-DROP-IN: " comment "log drops"
		counter packets 0 bytes 0 comment "dropped by policy"
	}

	chain forward {
		type filter hook forward priority filter; policy drop;
		counter packets 0 bytes 0 comment "no forwarding on this host"
	}

	chain output {
		type filter hook output priority filter; policy accept;
	}
}
```

★★★★ 注意 `define` 的變數已經被展開成實際的值（`$APP_HOSTS` 變成
`{ 192.168.10.31, 192.168.10.32 }`）—— 變數只存在於檔案裡，不存在於核心。

### 步驟 7：載入威脅情資清單 ★★★★

```bash
# 假設情資清單已放好（一行一個 IP 或 CIDR）
sudo head -n 3 /root/fw-backup/threat-ips.txt
```

```text
198.51.100.0/24
203.0.113.5
192.0.2.0/25
```

```bash
{
  echo "#!/usr/sbin/nft -f"
  echo "flush set inet fw blacklist4"
  echo -n "add element inet fw blacklist4 { "
  paste -sd, /root/fw-backup/threat-ips.txt
  echo " }"
} | sudo tee /root/fw-backup/threat-load.nft > /dev/null

sudo nft -c -f /root/fw-backup/threat-load.nft && sudo nft -f /root/fw-backup/threat-load.nft
sudo nft list set inet fw blacklist4
```

```text
table inet fw {
	set blacklist4 {
		type ipv4_addr
		size 200000
		flags interval
		elements = { 192.0.2.0/25, 198.51.100.0/24,
			     203.0.113.5 }
	}
}
```

★★★★ 之後每天更新情資只要重跑一次這個腳本（可以放進 cron），
**規則本身完全不用動** —— 這就是 set 的價值。

> [!warning] ★★★ 這台機器如果有 Docker
> 步驟 3 的 `forward` chain 是 `policy drop`，**Docker 的容器對外網路會直接斷掉**。
> 有 Docker 的機器有兩個選擇：
> 1. ★★★★ 把 `forward` 的 policy 改成 `accept`，並在 `input` 之外
>    另外處理容器流量（見 [[090-02-02-guide-防火牆-ufw基礎與實務]] 的 Docker 章節）
> 2. ★★★★★ 更好的做法：**容器主機不要手寫 nftables**，
>    改用 ufw ＋ 容器發布埠一律綁 `127.0.0.1`
>
> Docker 會在自己的 iptables table 裡建立 FORWARD 規則，
> 你的 `inet fw forward` chain 是**另一個 base chain**，兩者都會執行，
> 你的 `policy drop` 會覆蓋掉 Docker 的 accept（回顧本篇〈多個 base chain 掛同一個 hook〉）。

### 步驟 8：★★★★★ 從外部實測

在**管理跳板機 `192.168.99.10`**：

```bash
nc -zv -w 3 192.168.10.20 22
```

```text
Connection to 192.168.10.20 22 port [tcp/ssh] succeeded!
```

```bash
nc -zv -w 3 192.168.10.20 80 443
```

```text
Connection to 192.168.10.20 80 port [tcp/http] succeeded!
Connection to 192.168.10.20 443 port [tcp/https] succeeded!
```

```bash
# ★★★★★ 應該不通
nc -zv -w 3 192.168.10.20 3306
```

```text
nc: connect to 192.168.10.20 port 3306 (tcp) timed out: Operation now in progress
```

在 **app01 `192.168.10.31`**：

```bash
nc -zv -w 3 192.168.10.20 3306
```

```text
Connection to 192.168.10.20 3306 port [tcp/mysql] succeeded!
```

```bash
nc -zv -w 3 192.168.10.20 22
```

```text
nc: connect to 192.168.10.20 port 22 (tcp) timed out: Operation now in progress
```

**測試 SSH 速率限制**（★★★ 規則是 10/minute burst 5）：

```bash
for i in $(seq 1 12); do
  nc -zv -w 1 192.168.10.20 22 2>&1 | tail -n 1
done
```

```text
Connection to 192.168.10.20 22 port [tcp/ssh] succeeded!
Connection to 192.168.10.20 22 port [tcp/ssh] succeeded!
Connection to 192.168.10.20 22 port [tcp/ssh] succeeded!
Connection to 192.168.10.20 22 port [tcp/ssh] succeeded!
Connection to 192.168.10.20 22 port [tcp/ssh] succeeded!
nc: connect to 192.168.10.20 port 22 (tcp) timed out: Operation now in progress
nc: connect to 192.168.10.20 port 22 (tcp) timed out: Operation now in progress
...
```

★★★★ 前 5～6 次成功（burst），之後被限速丟棄，這就是預期行為。

> [!warning] ★★★★ 這條速率限制是**全域**的，不是 per-IP
> 意思是：所有管理網段的來源**共用**這個每分鐘 10 次的額度。
> 如果有多位 MIS 同時操作，會互相排擠。
> 要改成 per-IP 需要用本篇〈速率限制〉那節的 dynamic set 寫法（★★★★★ 未實機驗證）。
> 實務上更穩的做法是**這條不限速，改用
> [[090-02-05-guide-防護-Fail2ban入侵防護]] 做認證失敗封鎖**。

### 步驟 9：驗證 counter 與日誌 ★★★★

```bash
sudo nft list chain inet fw input | grep -E 'counter packets [1-9]'
```

```text
		meta l4proto { icmp, ipv6-icmp } limit rate 10/second counter packets 12 bytes 1008 accept comment "icmp"
		iifname "ens192" ip saddr 192.168.99.0/24 tcp dport 22 ct state new limit rate 10/minute burst 5 packets counter packets 7 bytes 420 accept comment "ssh mgmt"
		tcp dport { 80, 443 } ct state new limit rate 200/second burst 500 packets counter packets 22 bytes 1320 accept comment "web"
		ip saddr { 192.168.10.31, 192.168.10.32 } tcp dport 3306 counter packets 3 bytes 180 accept comment "app -> mysql"
		counter packets 9 bytes 540 comment "dropped by policy"
```

★★★★★ `dropped by policy` 的 counter 是 9 —— 對應到剛剛那幾次「應該不通」的測試。
**counter 對得上，才算驗證完成。**

```bash
sudo journalctl -k --grep 'NFT-DROP-IN' -n 3 --no-pager
```

```text
Sep 03 15:12:44 web01 kernel: NFT-DROP-IN: IN=ens192 OUT= MAC=00:50:56:9a:1b:2c:00:50:56:9a:cc:dd:08:00 SRC=192.168.99.10 DST=192.168.10.20 LEN=60 TOS=0x00 PREC=0x00 TTL=64 ID=41207 DF PROTO=TCP SPT=45120 DPT=3306 WINDOW=64240 RES=0x00 SYN URGP=0
Sep 03 15:13:05 web01 kernel: NFT-DROP-IN: IN=ens192 OUT= MAC=00:50:56:9a:1b:2c:00:50:56:9a:ee:ff:08:00 SRC=192.168.10.31 DST=192.168.10.20 LEN=60 TOS=0x00 PREC=0x00 TTL=64 ID=8811 DF PROTO=TCP SPT=54338 DPT=22 WINDOW=64240 RES=0x00 SYN URGP=0
```

### 步驟 10：開機自啟與收尾 ★★★★★

```bash
sudo systemctl enable nftables
sudo systemctl status nftables --no-pager | head -n 4
```

```text
○ nftables.service - nftables
     Loaded: loaded (/usr/lib/systemd/system/nftables.service; enabled; preset: enabled)
     Active: inactive (dead)
```

```bash
# ★★★★★ 確認 ufw 沒有同時啟用
systemctl is-enabled ufw
```

```text
disabled
```

```bash
# 取消自動還原
atq && sudo atrm 7

# 備份
sudo cp /etc/nftables.conf /root/fw-backup/nftables.conf.$(date +%F)
```

### 步驟 11：★★★★★ 重開機驗證

**沒有重開機驗證過的防火牆設定不算完成。**

```bash
sudo reboot
```

重連之後：

```bash
sudo nft list ruleset | head -n 5
```

```text
table inet fw {
	set blacklist4 {
		type ipv4_addr
		size 200000
		flags interval
	}
```

> [!warning] ★★★★ 重開機後 blacklist set 是空的
> `/etc/nftables.conf` 只宣告了 set 的**結構**，沒有元素。
> 情資清單要另外在開機時載入。做法是加一個 systemd unit 或 cron：
> ```bash
> sudo tee /etc/systemd/system/nft-threatlist.service > /dev/null <<'EOF'
> [Unit]
> Description=Load threat intel IPs into nftables set
> After=nftables.service
> Requires=nftables.service
>
> [Service]
> Type=oneshot
> ExecStart=/usr/sbin/nft -f /root/fw-backup/threat-load.nft
>
> [Install]
> WantedBy=multi-user.target
> EOF
> sudo systemctl daemon-reload
> sudo systemctl enable --now nft-threatlist.service
> ```
> ★★★ 用 `sudo nft list set inet fw blacklist4 | head` 確認元素回來了。

再從外部重跑一次步驟 8 的測試。

### 驗收檢查表 ★★★★★

| # | 檢查項 | 通過條件 |
| --- | --- | --- |
| 1 | `sudo nft -c -f /etc/nftables.conf` | 無輸出 |
| 2 | `sudo nft list ruleset` | ★★★★ 只有一個 `table inet fw`（沒有殘留的 ufw table） |
| 3 | `systemctl is-enabled ufw` | ★★★★★ `disabled`（不可與 nftables 並存） |
| 4 | `systemctl is-enabled nftables` | `enabled` |
| 5 | SSH 從管理網段 | 連得上 |
| 6 | SSH 從其他來源 | ★★★★★ timed out |
| 7 | 80／443 從外部 | 連得上 |
| 8 | 3306 從 app01／app02 | 連得上；★★★★★ 其他來源 timed out |
| 9 | `dropped by policy` counter | ★★★★ 數字對得上測試次數 |
| 10 | `journalctl -k --grep NFT-DROP-IN` | 有紀錄且 SRC／DPT 對得上 |
| 11 | blacklist set | 有元素，且重開機後仍在 |
| 12 | 重開機後完整規則 | ★★★★★ 存在且行為一致 |
| 13 | `/root/fw-backup/` | 備份與 panic 腳本齊全 |
| 14 | at job | 已 `atrm` 清掉 |

## 常見錯誤與排錯

| # | 現象 | 原因 | 解法 |
| --- | --- | --- | --- |
| 1 | ★★★★★ 套用規則後 SSH 立刻斷、連不回來 | chain `policy drop` 但沒放行 SSH，或漏了 `ct state established,related accept` | 等 at job 觸發 `nft -f panic-open.nft`；沒排 at 就走主控台（iDRAC／PVE Console／Serial Console）下 `sudo nft flush ruleset`。事後把規則寫成檔案，用 `nft -c -f` 檢查後再 `nft -f` 原子套用 |
| 2 | ★★★★★ 主機「網路壞了」：DNS 不通、`apt` 卡住、監控斷線 | 漏了 `ct state established,related accept` —— 出得去回不來 | 在 input chain 最前面補上這條，並確認它排在所有 drop 之前 |
| 3 | ★★★★ 規則寫了 `accept`，封包還是不通 | 另一個 base chain 掛在同一個 hook 上把它 drop 了（ufw、Docker、其他工具）。★★★★★ accept 不覆蓋別人的 drop | `sudo nft list ruleset` 看有幾個 `type filter hook input` 的 chain；同一台機器只留一個防火牆負責人 |
| 4 | ★★★★ `Error: Could not process rule: Device or resource busy` | 想刪的 chain 裡還有規則，或還被別的 chain jump 到 | 先 `sudo nft flush chain <family> <table> <chain>` 再 `delete chain` |
| 5 | `Error: Could not process rule: No such file or directory` | table 或 chain 不存在（打錯名字、family 寫錯） | `sudo nft list tables` 確認名稱與 family。`inet fw` 跟 `ip fw` 是兩個不同的 table |
| 6 | ★★★★ 重開機後規則全沒了 | `nftables.service` 沒 enable，或規則只是用 `nft add` 手動下的 | `sudo systemctl enable nftables`；規則一定要寫進 `/etc/nftables.conf` |
| 7 | ★★★★★ 開機後防火牆狀態每次不一樣 | ufw 與 nftables 兩個服務同時 enable，`flush ruleset` 互相清掉對方 | 二選一：`sudo systemctl disable nftables` 或 `sudo ufw disable` |
| 8 | ★★★★ `nft list ruleset` 看不到規則，但封包確實被擋 | 有 `iptables-legacy` 的規則存在（另一套後端） | `sudo iptables-legacy -S` 檢查；有東西就排維護時段清掉 |
| 9 | ★★★ 規則的 counter 一直是 0 | 封包沒走到這條（前面規則先攔截了），或封包根本沒到這台機器 | `sudo nft reset counters` 歸零後重測；用 `sudo tcpdump -ni any port <埠>` 確認封包有到 |
| 10 | ★★★★ 容器全部連不出去 | 手寫的 `forward` chain `policy drop` 蓋掉 Docker 的 accept | forward 改成 `policy accept` 並另外設計容器流量規則；或這台改回用 ufw |
| 11 | ★★★ set 裡的 CIDR 加不進去：`Error: Could not process rule: Invalid argument` | set 沒宣告 `flags interval` | 重建 set 時加上 `flags interval` |
| 12 | ★★★ `nft -f` 說語法錯，但那行看起來沒問題 | 大括號／貨幣符號被 shell 展開了 | 指令列一律用單引號包住 `'{ ... }'`；規則檔用 heredoc 時要寫 `<<'EOF'`（引號版，不展開變數） |
| 13 | ★★★★ `/var` 被日誌寫爆 | `log` 規則沒搭配 `limit rate` | 補 `limit rate 5/minute burst 10 packets`；`sudo journalctl --vacuum-size=200M` 清理 |
| 14 | ★★★ `iptables -S` 顯示的規則跟 `nft list ruleset` 對不起來 | 正常現象 —— iptables 相容層只看得到「iptables 建立的 table」，看不到原生 `inet` table | ★★★★ 以 `nft list ruleset` 為準，那才是完整的真相 |
| 15 | ★★★ `iptables-translate` 轉出來的規則跑不動 | 某些 xtables 模組沒有 nftables 對應 | 拿它當草稿，手動重寫。查 `man nft` 找對應的 expression |
| 16 | ★★★ dynamic set 的 per-IP 限流沒作用 | 語法在該版本不支援，或 set 沒有 `flags dynamic` | `sudo nft list set <family> <table> <set>` 看有沒有元素被加進去；★★★★ 這類需求建議改用 [[090-02-05-guide-防護-Fail2ban入侵防護]] |
| 17 | ★★★ `nft` 指令要 root 才能跑 | 正常 | 一律 `sudo`。不要為了方便給 `nft` 設 setuid |

### 排查順序 ★★★★★

```text
  1. 規則檔語法對嗎？        sudo nft -c -f /etc/nftables.conf
        │ 有錯 → 照行號改
        ▼
  2. 規則真的在核心裡嗎？     sudo nft list ruleset
        │ 沒有 → nft -f 沒套用成功，或被別人 flush 掉了
        ▼
  3. 有幾個 base chain 掛在同一個 hook？
        sudo nft list ruleset | grep -n 'type filter hook input'
        │ 超過一個 → ★★★★★ 這就是「accept 了還是不通」的原因
        ▼
  4. 規則被命中了嗎？        sudo nft reset counters
                            （重打流量）
                            sudo nft list ruleset | grep -E 'counter packets [1-9]'
        │ 目標規則 packets=0 → 前面有規則先攔截，往上找
        ▼
  5. 有 drop 的日誌嗎？      sudo journalctl -k --grep 'NFT-DROP' -n 20
        │ 有且 SRC/DPT 對得上 → 規則邏輯問題，回 4
        │ 完全沒有 → 封包沒到這台機器
        ▼
  6. 封包真的到了嗎？        sudo tcpdump -ni any port <埠>
        │ 沒看到 → 上游（交換器 ACL、邊界防火牆、路由）
        ▼
  7. 有第二套規則引擎嗎？     sudo iptables-legacy -S | head
                            systemctl is-enabled ufw firewalld nftables
                            sudo nft monitor    ← 看誰在即時改規則
        ▼
  8. 服務真的在聽嗎？        sudo ss -tlnp | grep <埠>
        （★ 這一步其實該最先做，見第 02 篇的排查順序）
```

## 安全性注意事項

| # | 事項 | 重要度 |
| --- | --- | --- |
| 1 | **一台機器只能有一個防火牆負責人**。ufw、firewalld、手寫 nftables 三選一，混用一定出事 | ★★★★★ |
| 2 | **規則永遠寫成檔案，用 `nft -c -f` 檢查後 `nft -f` 原子套用**，不要在指令列一條一條下 —— 中途出錯會留下半套規則 | ★★★★★ |
| 3 | **`policy drop` 的 chain 一建立就開始丟包**。先寫完整份規則、`-c` 檢查、再一次套用 | ★★★★★ |
| 4 | **`ct state established,related accept` 永遠放第一（loopback 之後）**。漏了它主機會「發得出去收不回來」 | ★★★★★ |
| 5 | `nft flush ruleset` **沒有確認提示、沒有備份**。只在緊急解鎖時用，用完立刻補回規則 —— 期間主機是裸奔的 | ★★★★★ |
| 6 | **改規則前必架三道保險**：tmux、`at` 自動還原、第二條連線 ＋ 可用主控台 | ★★★★★ |
| 7 | **`log` 一定要搭 `limit rate`**，否則 `/var` 會被寫爆，連帶讓資料庫與日誌服務寫入失敗 | ★★★★ |
| 8 | **`ip_forward=1` 只在真的要當路由器的機器上開**，並同時把 forward chain 設成 `policy drop` 白名單放行 | ★★★★ |
| 9 | **用 `inet` family**，不要只寫 IPv4。主機有 IPv6 位址、服務綁在 IPv6 上，只管 IPv4 等於開後門 | ★★★★ |
| 10 | **檢查有沒有 `iptables-legacy` 的幽靈規則**。兩套後端同時有規則，你只會看到其中一套 | ★★★★ |
| 11 | **`/etc/nftables.conf` 權限應為 `root:root 0644` 或更嚴**，且納入設定管理（Ansible／git），每次改動留版本 | ★★★★ |
| 12 | **每條規則都寫 `comment` 與 `counter`**。前者是給接手的人看的，後者是給排查的人用的 | ★★★★ |
| 13 | 威脅情資 set 的來源要可信、要有更新機制。★★★ 過期的黑名單會誤擋正常使用者（IP 被回收再分配） | ★★★ |
| 14 | **不要因為「比較高級」就把單純的機器改成手寫 nftables**。ufw 能表達的需求就用 ufw，交接成本低很多 | ★★★★ |
| 15 | 定期（每季）用 `nft list ruleset` 產出報告，把 counter 長期為 0 的規則抓出來檢討是否還需要 | ★★★ |

## 速查表

### nft 檢視 ★★★★★

| 指令 | 作用 |
| --- | --- |
| `sudo nft list ruleset` | ★★★★★ 看全部規則（唯一可信的完整真相） |
| `sudo nft -a list ruleset` | 帶 handle（刪規則要用） |
| `sudo nft list tables` | 只列 table 名稱 |
| `sudo nft list table inet fw` | 看單一 table |
| `sudo nft list chain inet fw input` | 看單一 chain |
| `sudo nft list sets` | 看所有 set |
| `sudo nft list set inet fw blacklist4` | 看單一 set 的元素 |
| `sudo nft monitor` | ★★★★ 即時監看規則變動（抓誰在改規則） |
| `sudo nft reset counters` | 歸零所有 counter |

### nft 修改 ★★★★

| 指令 | 作用 |
| --- | --- |
| `sudo nft add table inet fw` | 建 table |
| `sudo nft add chain inet fw input '{ type filter hook input priority 0 ; policy accept ; }'` | 建 base chain |
| `sudo nft add rule inet fw input tcp dport 22 accept` | 加規則到最後 |
| `sudo nft insert rule inet fw input <規則>` | 插到最前面 |
| `sudo nft insert rule inet fw input position N <規則>` | 插到 handle N 之前 |
| `sudo nft delete rule inet fw input handle N` | ★★★ 依 handle 刪 |
| `sudo nft flush chain inet fw input` | 清空 chain 的規則 |
| `sudo nft delete chain inet fw input` | 刪 chain（要先 flush） |
| `sudo nft delete table inet fw` | 刪整個 table |
| `sudo nft flush ruleset` | ★★★★★ 清空全部（危險） |

### 檔案與套用 ★★★★★

| 指令 | 作用 |
| --- | --- |
| `sudo nft -c -f /etc/nftables.conf` | ★★★★★ **只檢查語法不套用**（無輸出＝OK） |
| `sudo nft -f /etc/nftables.conf` | ★★★★★ 原子套用整份規則 |
| `sudo nft list ruleset > /root/backup.nft` | 匯出（★★★ 要自己補 shebang 與 `flush ruleset`） |
| `sudo systemctl enable nftables` | 開機自啟載入 `/etc/nftables.conf` |
| `/etc/nftables.conf` | ★★★★★ 主設定檔 |

### 常用 expression ★★★★

| 寫法 | 意思 |
| --- | --- |
| `iif lo` / `iifname "ens192"` | 入向介面（索引／名稱） |
| `oifname "ens192"` | 出向介面 |
| `ip saddr` / `ip daddr` | IPv4 來源／目的位址 |
| `ip6 saddr` / `ip6 daddr` | IPv6 來源／目的位址 |
| `tcp dport 22` / `udp dport 53` | 目的埠 |
| `tcp dport { 80, 443 }` | ★★★★ 多個埠（anonymous set） |
| `udp dport 30000-30100` | ★★★ 埠範圍（連字號，不是冒號） |
| `ct state established,related` | ★★★★★ 連線狀態 |
| `ct state new` / `ct state invalid` | 新連線／無效封包 |
| `meta l4proto { icmp, ipv6-icmp }` | ★★★ inet family 下同時比對 v4/v6 ICMP |
| `ip saddr @blacklist4` | ★★★★ 引用具名 set |
| `limit rate 20/second burst 50 packets` | 速率限制 |
| `counter` | ★★★★ 計數（排查必備） |
| `log prefix "X: "` | 記錄（★★★ 必須搭 limit） |
| `comment "說明"` | ★★★★ 註解 |
| `accept` / `drop` / `reject` | 判決 |
| `dnat to 10.0.0.5:443` / `masquerade` | NAT |
| `vmap { 22 : accept, 80 : accept }` | verdict map |

### family、hook、priority ★★★

| 項目 | 值 |
| --- | --- |
| family | `inet`（★★★★★ 首選）、`ip`、`ip6`、`arp`、`bridge`、`netdev` |
| chain type | `filter`、`nat`、`route` |
| hook | `prerouting`、`input`、`forward`、`output`、`postrouting`、`ingress` |
| priority | `raw`(-300)、`mangle`(-150)、`dstnat`(-100)、`filter`(0)、`security`(50)、`srcnat`(100) |
| policy | `accept`（預設）、`drop`（★★★★★ 會鎖人） |

### set 選項 ★★★★

| 選項 | 用途 |
| --- | --- |
| `type ipv4_addr` / `ipv6_addr` / `inet_service` / `ether_addr` | 元素型別 |
| `flags interval` | ★★★★★ 允許放 CIDR 網段 |
| `flags timeout` ＋ `timeout 1h` | ★★★★ 元素自動過期 |
| `flags dynamic` | 允許規則動態新增元素 |
| `size 200000` | ★★★★ 上限（大清單必設） |
| `auto-merge` | 自動合併重疊網段 |
| `counter` | 每個元素各自計數 |

### iptables 對照 ★★★

| iptables | nftables |
| --- | --- |
| `iptables -S` | `nft list ruleset` |
| `-A INPUT` / `-I INPUT 1` | `add rule ... input` / `insert rule ... input` |
| `-p tcp --dport 22` | `tcp dport 22` |
| `-s 10.0.0.0/8` / `-d 10.0.0.1` | `ip saddr 10.0.0.0/8` / `ip daddr 10.0.0.1` |
| `-i eth0` / `-o eth0` | `iifname "eth0"` / `oifname "eth0"` |
| `-m state --state ESTABLISHED,RELATED` | `ct state established,related` |
| `-m multiport --dports 80,443` | `tcp dport { 80, 443 }` |
| `-j ACCEPT/DROP/REJECT` | `accept`／`drop`／`reject` |
| `-j MASQUERADE` | `masquerade` |
| `-P INPUT DROP` | chain 定義的 `policy drop` |
| `iptables-save` / `iptables-restore` | `nft list ruleset` / `nft -f` |
| ★★★★ `iptables-translate <規則>` | 自動轉換單條 |
| ★★★ `iptables-restore-translate -f rules.v4` | 自動轉換整份 |

### 緊急救援 ★★★★★

| 情況 | 動作 |
| --- | --- |
| 事前預防 | `echo "/usr/sbin/nft flush ruleset" \| sudo at now + 10 minutes` |
| 只想檢查不想套用 | `sudo nft -c -f /etc/nftables.conf` |
| 已被鎖在外 | 主控台（iDRAC／PVE Console／Serial Console）下 `sudo nft flush ruleset` |
| 想還原到某份設定 | `sudo nft -f /root/fw-backup/nftables.conf.<日期>` |
| 完全進不去 | 救援模式掛載後 `mv /mnt/etc/nftables.conf /mnt/etc/nftables.conf.bak` 再重開機 |
| 想確認誰在改規則 | `sudo nft monitor` |

## 練習題

1. 在測試機上執行 `sudo iptables -V` 與 `sudo update-alternatives --display iptables`，
   判斷這台機器用的是 nft 後端還是 legacy 後端。
   再用 `sudo iptables-legacy -S` 確認有沒有幽靈規則，把結果寫成一份現況報告。

2. 建立一個測試 table `inet lab`，chain policy 先設 `accept`，
   依序加入 loopback、established/related、SSH 三條規則，
   然後**才**把 policy 改成 drop。
   ★★★★★ 全程在 tmux 裡、並先排好 `at` 自動 `nft flush ruleset`。
   說明為什麼「先寫規則、最後改 policy」比「先設 policy drop 再補規則」安全。

3. 建立一個帶 `flags interval` 的 set，塞進 `198.51.100.0/24` 與 `203.0.113.5`，
   寫一條規則引用它。然後故意建一個**沒有** `flags interval` 的 set，
   試著塞 CIDR 進去，記錄你看到的錯誤訊息。

4. 建立一個 `flags timeout` ＋ `timeout 2m` 的 set，加入一個 IP，
   每 30 秒跑一次 `nft list set ...`，觀察 `expires` 欄位的變化直到元素消失。
   說明這個機制跟 Fail2ban 的關係。

5. 把第 02 篇你在 ufw 上建的規則集，用 `sudo iptables-save > /root/rules.v4` 匯出，
   再用 `iptables-restore-translate -f /root/rules.v4` 轉成 nft 語法。
   對照本篇實戰範例的手寫版本，列出**三個轉換版本比手寫版本差的地方**。

6. ★★★★ 在測試機上刻意製造「兩個 base chain 掛在同一個 input hook」的情況
   （一個 accept 22、一個 drop 22），實測 22 埠通不通，
   並用 counter 證明兩個 chain 都被執行了。

> [!question]- 練習解答
>
> **1.** `iptables v1.8.10 (nf_tables)` 代表 nft 後端；`(legacy)` 代表舊後端。
> `update-alternatives --display iptables` 會顯示 `link currently points to`。
> ★★★★ 幽靈規則檢查：
> ```bash
> sudo iptables-legacy -S 2>/dev/null
> ```
> 只有三行 `-P INPUT ACCEPT` / `-P FORWARD ACCEPT` / `-P OUTPUT ACCEPT` 就是乾淨的。
> 有其他規則就代表有兩套規則同時生效，而 `iptables -S`（nft 版）看不到它們。
>
> **2.**
> ```bash
> tmux new -s lab
> echo "/usr/sbin/nft flush ruleset" | sudo at now + 10 minutes
> sudo nft add table inet lab
> sudo nft add chain inet lab input '{ type filter hook input priority 0 ; policy accept ; }'
> sudo nft add rule inet lab input iif lo accept
> sudo nft add rule inet lab input ct state established,related accept
> sudo nft add rule inet lab input tcp dport 22 accept
> # 測試沒問題後才改 policy
> sudo nft chain inet lab input '{ policy drop ; }'
> ```
> ★★★★★ 「先設 policy drop 再補規則」的問題在於：
> policy drop 的 chain **一建立就立刻開始丟棄所有封包**，
> 你在下第二條指令之前 SSH 就斷了，後面的規則永遠補不上去。
> 更安全的做法是整份寫成檔案，`nft -c -f` 檢查後一次 `nft -f` 原子套用。
>
> **3.**
> ```bash
> sudo nft add set inet lab s_ok '{ type ipv4_addr ; flags interval ; }'
> sudo nft add element inet lab s_ok '{ 198.51.100.0/24, 203.0.113.5 }'   # OK
> sudo nft add rule inet lab input ip saddr @s_ok counter drop
>
> sudo nft add set inet lab s_bad '{ type ipv4_addr ; }'
> sudo nft add element inet lab s_bad '{ 198.51.100.0/24 }'
> ```
> ```text
> Error: Could not process rule: Invalid argument
> add element inet lab s_bad { 198.51.100.0/24 }
>                              ^^^^^^^^^^^^^^^^
> ```
> ★★★★ 結論：**要放網段就必須宣告 `flags interval`**，這是 set 最常見的坑。
>
> **4.**
> ```bash
> sudo nft add set inet lab tmpban '{ type ipv4_addr ; flags timeout ; timeout 2m ; }'
> sudo nft add element inet lab tmpban '{ 203.0.113.99 }'
> sudo nft list set inet lab tmpban
> ```
> ```text
> 		elements = { 203.0.113.99 expires 1m52s }
> ```
> 30 秒後再看會變成 `expires 1m22s`，兩分鐘後元素自動消失。
> ★★★★ 這正是 Fail2ban 的 nftables 後端運作方式 —— 它把封鎖的 IP 加進帶 timeout 的 set，
> **不需要任何解封腳本或 cron**，核心會自己清掉過期元素。
> 見 [[090-02-05-guide-防護-Fail2ban入侵防護]]。
>
> **5.** 轉換版本比手寫版本差的地方（任三個）：
> - ★★★★ **是 `ip` family（只有 IPv4）**，IPv6 要另外轉一份 `ip6` table，
>   不像手寫版本用 `inet` 一次涵蓋
> - ★★★★ **保留 ufw 的多層 jump 結構**（`ufw-before-input`、`ufw-user-input`…），
>   規則數量多、可讀性差
> - ★★★★ **沒有 `comment`**，接手的人看不出每條規則的用途
> - ★★★ **沒有用 set**，多個 IP 是多條規則而不是一個集合
> - ★★★ **chain 名稱是大寫的 `INPUT`／`FORWARD`**，不符合 nftables 慣例
> - ★★★ 沒有 `define` 變數，網段改了要逐條改
>
> **6.**
> ```bash
> sudo nft add table inet a
> sudo nft add chain inet a input '{ type filter hook input priority 0 ; policy accept ; }'
> sudo nft add rule inet a input tcp dport 22 counter accept
>
> sudo nft add table inet b
> sudo nft add chain inet b input '{ type filter hook input priority 10 ; policy accept ; }'
> sudo nft add rule inet b input tcp dport 22 counter drop
> ```
> 實測結果：**22 埠不通**。
> ```bash
> sudo nft list ruleset | grep -E 'counter packets'
> ```
> ```text
> 		tcp dport 22 counter packets 4 bytes 240 accept
> 		tcp dport 22 counter packets 4 bytes 240 drop
> ```
> ★★★★★ 兩個 counter 都在動，證明**兩個 chain 都被執行了**。
> `inet a` 的 accept 只代表「這個 chain 放行」，
> priority 較大的 `inet b` 還是把封包 drop 掉了。
> 這就是「ufw 說 allow、封包還是不通」的真正機制。
> 測完記得清掉：`sudo nft delete table inet a; sudo nft delete table inet b`

## 小測驗

Q1. 選擇題：`sudo iptables -V` 輸出 `iptables v1.8.10 (nf_tables)`，這代表什麼？
（A）這台機器沒裝 nftables
（B）iptables 指令是相容層，規則實際存在 nftables 引擎裡
（C）iptables 與 nftables 的規則是完全分開的兩套
（D）必須改用 `nft` 指令才能看到規則

Q2. 是非題：如果 A chain 的規則對某個封包 `accept`，
那麼掛在同一個 hook 上的 B chain 就不會再看這個封包了。

Q3. 這行指令會發生什麼事？在什麼情況下你會被鎖在門外、什麼情況下不會？
```bash
sudo nft flush ruleset
```

Q4. 簡答：一個 nftables 規則集，開頭三條規則應該是什麼？為什麼順序不能改？

Q5. 你要封鎖一份含 4 萬個惡意 IP 的清單。
說明為什麼不能用「4 萬條 `ufw deny from <IP>`」，正確做法是什麼，
以及 set 宣告時哪一個 flag 絕對不能漏。

Q6. 選擇題：想在完全不影響現行流量的情況下驗證 `/etc/nftables.conf` 的語法，
應該用哪個指令？
（A）`nft -f /etc/nftables.conf`
（B）`nft -c -f /etc/nftables.conf`
（C）`nft list ruleset`
（D）`systemctl restart nftables`

Q7. 是非題：`ufw` 與 `nftables.service` 可以同時 enable，
因為它們用的是不同的 table，不會互相影響。

Q8. 這兩條規則有什麼差別？各自適合什麼情境？
```text
iif "lo" accept
iifname "lo" accept
```

Q9. 簡答：`nft -f` 相對於「一條一條下 `nft add rule`」最重要的優勢是什麼？
為什麼這個優勢在遠端操作時特別關鍵？

Q10. 一台機器 `nft list ruleset` 裡有一條 `tcp dport 8080 counter accept`，
counter 顯示 `packets 0`，但同事說「這個埠明明有人在連」。
列出**三個**你要依序檢查的方向。

> [!question]- 測驗答案
>
> **Q1 → (B)** ★★★★
> `(nf_tables)` 代表 `iptables` 是 `iptables-nft` 相容層：你打 iptables 語法，
> 它翻譯成 nftables 規則存進同一個引擎。
> 所以 `nft list ruleset` **看得到** iptables 建立的 table（名稱是大寫的 `INPUT` 等）。
> 反過來不成立 —— `iptables -S` 看不到原生的 `inet` table，這是排錯表第 14 列的重點。
> → 詳見〈四層堆疊：誰在誰上面〉
>
> **Q2 → 錯** ★★★★★
> 掛在同一個 hook 上的所有 base chain **都會依 priority 由小到大依序執行**。
> A chain 的 accept 只代表「A 這個 chain 放行」，B chain 還是會看，
> 而且 B 如果 drop，封包就死了。
> **accept 不是最終判決，drop 才是。**
> 這是「ufw 說 allow、封包還是不通」的真正原因。
> → 詳見〈★★★★ 多個 base chain 掛同一個 hook：全部執行〉
>
> **Q3** ★★★★★
> 瞬間清空整台機器的所有 nftables 規則，**沒有確認提示、沒有備份**。
> ufw 規則、Docker 的 NAT 規則、Fail2ban 的封鎖 set 全部消失。
> **不會把你鎖在外面** —— 因為 chain 都沒了，等於全放行；
> 但機器會處於**完全裸奔**狀態，而且容器對外網路會斷。
> 它是「已經被鎖在外面時的緊急解鎖手段」，不是日常操作。
> 唯一安全的日常用法是放在 `nft -f` 規則檔的第一行，讓它跟後面的規則同屬一個交易。
> → 詳見〈插入、刪除、清空〉
>
> **Q4** ★★★★★
> ```text
> iif lo accept
> ct state established,related accept
> ct state invalid drop
> ```
> 順序不能改的理由：
> ① loopback 放行必須最早，否則本機服務之間（MySQL socket、DNS 快取、監控）會斷；
> ② ★★★★★ `established,related` 少了它主機會「發得出去、收不回來」——
> DNS 解析失敗、`apt` 卡住、你現在這條 SSH 在下一個封包就斷，
> 而且症狀會被誤判成「網路壞了」；
> ③ invalid 要在業務規則之前丟掉，避免奇怪的封包進到後面的判斷。
> → 詳見〈加規則〉
>
> **Q5** ★★★★
> 4 萬條規則會變成 4 萬次線性比對，每個封包都要走完，CPU 直接爆掉，
> 而且規則清單完全不可讀、不可維護。
> 正確做法：**一個 named set ＋ 一條規則**，nftables 的 set 底層是 hash／紅黑樹，
> 查找是 O(1) 或 O(log n)：
> ```bash
> sudo nft add set inet fw blacklist4 '{ type ipv4_addr ; flags interval ; size 200000 ; }'
> sudo nft add rule inet fw input ip saddr @blacklist4 counter drop
> ```
> ★★★★★ **絕對不能漏的是 `flags interval`** —— 沒有它就塞不進 CIDR 網段，
> 只會得到 `Error: Could not process rule: Invalid argument`。
> 大清單另外要記得設 `size`。
> → 詳見〈★★★★ set：大量 IP 封鎖的正確做法〉
>
> **Q6 → (B)** ★★★★★
> `-c` 是 check：只解析語法、完全不套用，**沒有輸出就代表正確**。
> (A) 會真的套用；(C) 只看現況；(D) 會重載服務（等於套用）。
> `-c` 是 nftables 相對 ufw 的重要優勢之一，改正式環境前一定要跑。
> → 詳見〈持久化與原子套用〉
>
> **Q7 → 錯** ★★★★★
> 兩者都 enable 的話，開機時的載入順序不保證，
> 而 `/etc/nftables.conf` 開頭的 `flush ruleset` **會把 ufw 剛載入的規則整個清掉**
> （或反過來）。症狀是「每次開機防火牆狀態都不一樣」，是最難查的那種故障。
> 而且就算兩者的 table 不同，多個 base chain 掛同一個 hook 時 drop 會互相覆蓋。
> **一台機器只能有一個防火牆負責人，二選一。**
> → 詳見〈持久化與原子套用〉的 danger callout
>
> **Q8** ★★★
> `iif` 比對**介面索引（index）**，在規則載入時就解析成數字，比對快，
> 但介面必須存在，介面重建後索引會變。
> `iifname` 比對**介面名稱字串**，每個封包比一次字串、稍慢，
> 但介面不存在時規則也載入得起來。
> 實務建議：**`lo` 用 `iif`（永遠存在），其他介面（尤其虛擬介面、Docker 介面、
> 開機時可能還沒 up 的介面）用 `iifname`。**
> → 詳見〈加規則〉的 warning callout
>
> **Q9** ★★★★★
> **原子性（atomicity）**：`nft -f` 把整份檔案當成**一個交易**，
> 全部成功才套用、任何一行有錯就完全不動，**不會產生中間狀態**。
> 一條一條下的話，中途出錯會留下半套規則 ——
> 最糟的情況是「`policy drop` 已經生效、放行 SSH 那條還沒下」，
> 你當場被鎖在門外，而且遠端已經無法補救。
> → 詳見〈持久化與原子套用〉
>
> **Q10** ★★★★
> 依序檢查：
> ① **前面有沒有規則先攔截了**——`sudo nft reset counters` 歸零後重打流量，
> 看是哪一條的 counter 在動（很可能是更前面的 drop 或更寬的 accept）。
> ② **有沒有第二個 base chain 掛在同一個 hook**——
> `sudo nft list ruleset | grep -n 'type filter hook input'`；
> 也要檢查 `sudo iptables-legacy -S` 有沒有幽靈規則。
> ③ **封包到底有沒有到這台機器**——`sudo tcpdump -ni any port 8080`；
> 沒看到封包就是上游（交換器 ACL、邊界防火牆、路由）或
> 服務綁在 `127.0.0.1`（`sudo ss -tlnp | grep 8080`）的問題，不是這條規則。
> → 詳見〈排查順序〉與〈counter 與除錯〉

## 延伸閱讀

### 本手冊

- [[090-02-02-guide-防火牆-ufw基礎與實務]] —— ★★★★★ **主線**。
  九成的機關需求用 ufw 就夠了，本篇是處理剩下那一成
- [[090-02-04-guide-防火牆-firewalld]] —— RHEL／Rocky／AlmaLinux 系的前端，底層同樣是 nftables
- [[090-02-05-guide-防護-Fail2ban入侵防護]] —— ★★★★ 用帶 timeout 的 nft set 做動態封鎖，
  比自己寫 dynamic set 限流成熟得多
- [[090-02-01-guide-防護-伺服器初始安全設定]] —— 防火牆在伺服器上線 checklist 中的位置
- [[090-02-06-guide-防護-遠端存取安全]] —— 跳板機與 out-of-band 管理，鎖門時的救命管道
- [[050-02-01-05-guide-Docker-網路]] —— Docker 在 prerouting 做 dnat、封包走 forward 的原理
- [[050-02-01-08-guide-Docker-安全實務]] —— 容器主機的防火牆設計
- [[100-01-02-guide-日誌-日誌集中與輪替]] —— 把 `NFT-DROP` 日誌送到集中式 log server
- [[090-05-02-guide-資安設備-防火牆與次世代防火牆]] —— 邊界防火牆設備與主機防火牆的分工
- [[020-01-16-cmd-Linux-網路基礎指令]] —— `ss`、`tcpdump`、`ip`，排查防火牆問題的基本工具

### 外部資源

- `man nft` —— ★★★★★ **最權威的語法參考**。不確定某個 expression 怎麼寫就查這裡
- `man nft` 的 EXAMPLES 章節與 `/usr/share/doc/nftables/examples/`
- nftables wiki：<https://wiki.nftables.org/>
  （★★★★ 特別是 "Quick reference-nftables in 10 minutes" 與 "Moving from iptables to nftables"）
- netfilter 專案首頁：<https://www.netfilter.org/>
- Debian wiki — nftables：<https://wiki.debian.org/nftables>
- `iptables-translate` 與 `iptables-restore-translate` 的 man page
