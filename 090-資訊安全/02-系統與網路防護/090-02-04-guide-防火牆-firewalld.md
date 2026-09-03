---
title: "firewalld RHEL 防火牆"
desc: "zone 信任模型、runtime/permanent 雙軌、rich rule 與自訂 service，附 15 列 ufw 對照"
aliases: [firewalld, firewall-cmd, zone, rich rule, runtime-to-permanent]
tags: [群組/資訊安全, 安全/防火牆, 主題/網路]
category: 系統與網路防護
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[090-02-02-guide-防火牆-ufw基礎與實務]]"]
updated: 2026-09-03
---

# firewalld RHEL 防火牆

> [!note] 本篇是「對照線」，不是主線
> 本手冊的 Linux 主機防火牆**主線是 Ubuntu 的 ufw**，見 [[090-02-02-guide-防火牆-ufw基礎與實務]]。
> 但機關環境裡有大量 RHEL／Rocky／AlmaLinux 主機（PVE 上的 VM、資料庫主機、
> 舊系統移轉過來的 CentOS），這些機器出廠就帶 firewalld，**深度不能打折**。
> 兩者底層都可以是 nftables（見 [[090-02-03-guide-防火牆-nftables與iptables]]），
> 但**操作模型完全不同** —— ufw 是「一條一條規則」，firewalld 是「介面／來源綁到 zone，規則掛在 zone 上」。
> 用 ufw 的直覺去操作 firewalld，八成會踩到本篇「常見錯誤與排錯」的前三列。

> [!abstract] 這篇你會學到
> - ★★★★ **zone 信任模型** —— firewalld 與 ufw 最大的差異：規則不是掛在主機上，是掛在 zone 上；
>   介面綁 zone、來源網段也綁 zone，而且**來源綁定優先於介面綁定**
> - ★★★★★ **runtime 與 permanent 雙軌** —— 「重開機規則就不見了」與「改了沒生效」這兩個
>   最常見的事故，根源都是同一件事：`--permanent` 與 `--reload` 沒配對用
> - ★★★★ 用 `--runtime-to-permanent` 安全地「先試跑再落地」，以及 `--timeout` 自動撤銷規則
> - service 定義檔（`/usr/lib/firewalld/services/`）怎麼讀、怎麼自己寫一個
> - rich rule：來源限制、記錄、速率限制、時效規則，四種寫法一次講完
> - port forwarding 與 masquerade：什麼時候需要、為什麼少了 masquerade 回不來
> - ★★★★ **firewalld ↔ ufw 對照表（18 列）**：同一件事兩邊各怎麼寫
> - 完整實戰：一台 Rocky Linux 9 跑 Nginx + MySQL，從預設 zone 開始建出完整規則並驗證

> [!warning] 未實機驗證
> 本篇以 **Rocky Linux 9.4（firewalld 1.2.x，backend = nftables）** 的官方文件與
> `man firewalld.zone` / `man firewalld.richlanguage` / `man firewall-cmd` 為準撰寫。
> 撰稿環境沒有長期保留的 RHEL 實體機做完整驗證，**各版本預設 zone 允許的 service 清單會變動**
> （例如 `mdns` 是否預設開在 `home`／`work`）。導入前務必先在該台機器上用
> `firewall-cmd --list-all-zones` 確認實際預設，不要照抄本篇表格當成事實。

## 前置知識

- [[090-02-02-guide-防火牆-ufw基礎與實務]] —— 主線寫法。本篇很多段落是拿它來對照的
- [[090-02-03-guide-防火牆-nftables與iptables]] —— firewalld 只是前端，真正執行的是 nftables
- [[090-02-01-guide-防護-伺服器初始安全設定]] —— 一台新機器上線的整體順序，防火牆是其中一步
- [[020-01-17-cmd-Linux-systemd服務管理]] —— `systemctl enable --now`、`reload` 與 `restart` 的差別
- [[020-01-16-cmd-Linux-網路基礎指令]] —— `ss -tlnp`、`ip addr`，驗證規則時一定會用到

## 觀念說明

### firewalld 在整個防火牆生態裡的位置 ★★★

```text
   你打的指令        firewall-cmd  /  firewall-config(GUI)  /  firewall-offline-cmd
        │
        ▼
   常駐服務          firewalld.service（D-Bus 服務，維護「zone → 規則」的狀態）
        │
        ▼
   後端（backend）    nftables（預設，firewalld 0.6 起）   ← FirewallBackend= 決定
                     iptables（舊版或手動切回）
        │
        ▼
   核心              netfilter
```

★★★★ 這張圖說明兩件事：

1. **firewalld 的規則最後還是變成 nftables 規則。** 你可以用 `nft list ruleset` 看到它產生的東西，
   但**不要用 `nft` 直接去改** —— 下一次 `firewall-cmd --reload` 會把你的手改全部沖掉。
2. **firewalld 沒跑，規則就不存在。** 它不像 `nftables.service` 那樣把規則寫進去就留著；
   `systemctl stop firewalld` 之後，主機是**完全沒有防火牆**的裸奔狀態。

### 核心差異：zone 是什麼 ★★★★

ufw 的模型很單純：一台主機，一組規則，由上往下比對。
firewalld 的模型多了一層 —— **zone（區域）**：

```text
封包進來
   │
   ├─① 這個封包的「來源位址」有沒有被綁到某個 zone？   ← ★★★★ 優先權最高
   │      有 → 用那個 zone 的規則，結束判斷
   │
   ├─② 封包進來的「網路介面」綁在哪個 zone？
   │      有 → 用那個 zone 的規則，結束判斷
   │
   └─③ 都沒有 → 用 default zone（出廠是 public）
```

★★★★★ **「來源綁定優先於介面綁定」是 firewalld 最反直覺、也最常被用來設計規則的一點。**
它讓你可以這樣做：

> 這台機器的 `ens192` 綁在 `public`（只開 80／443），
> 但只要來源是 `10.10.0.0/24`（機房管理網段），就改用 `internal` zone（額外開 ssh 與 3306）。
> **同一張網卡、同一個埠，來源不同就走不同規則。**

用 ufw 要做同樣的事，得寫一堆帶 `from` 的規則並小心排序；firewalld 是把「信任等級」抽象出來，
規則寫在信任等級上，機器只要決定「誰屬於哪一級」。

### 九個預設 zone 的信任程度與適用場合 ★★★★

由**最不信任**排到**最信任**：

| zone | 預設 target | 出廠預設允許 | 信任度 | 什麼時候用 | 星級 |
| --- | --- | --- | --- | --- | --- |
| `drop` | `DROP` | 無 | 最低 | 進來的封包**直接丟棄、不回應**；掃描者連「有沒有這台機器」都測不出來。對外蜜罐、被攻擊時的緊急檔板 | ★★★ |
| `block` | `%%REJECT%%` | 無 | 極低 | 拒絕但**回 icmp-host-prohibited**；對方會立刻知道被拒。內網要讓人快速失敗而不是 timeout 時用 | ★★★ |
| `public` | `default` | `ssh`、`dhcpv6-client` | 低 | ★★★★★ **出廠的 default zone**，也是絕大多數對外伺服器該待的地方。假設「網路上的其他機器都不可信」 | ★★★★★ |
| `external` | `default` | `ssh` | 低 | 給**做 NAT 的對外介面**用，這個 zone **預設就開了 masquerade**。軟路由／閘道器的 WAN 側 | ★★★★ |
| `dmz` | `default` | `ssh` | 低 | 隔離區主機：對外提供有限服務、且**不信任內網**。DMZ 內的 Web 主機 | ★★★ |
| `work` | `default` | `ssh`、`dhcpv6-client` | 中 | 辦公網段。信任度比 public 高一點，但仍需明確開服務 | ★★ |
| `home` | `default` | `ssh`、`mdns`、`samba-client`、`dhcpv6-client` | 中高 | 家用／小型網段，預設多開了檔案分享與服務探索。★★★ **伺服器不要用這個** | ★★★ |
| `internal` | `default` | 同 `home` | 中高 | ★★★★ 內部管理網段。實務上最常拿來當「管理網段專用 zone」，把 ssh／3306／9100 開在這裡 | ★★★★ |
| `trusted` | `ACCEPT` | 全部 | 最高 | ★★★★★ **這個 zone 的一切都放行**。只能綁極少數來源（例如叢集心跳網段），**絕對不要綁到對外介面** | ★★★★★ |

> [!info]- `nm-shared` —— 第十個 zone
> firewalld 0.9 起多了 `nm-shared`，是 NetworkManager 做「連線共享」（把這台機器當簡易 NAT 分享出去）
> 時自動使用的 zone。伺服器環境用不到，看到它不用緊張，也不要拿它來放自己的規則。

> [!warning] ★★★ 上表的「出廠預設允許」會隨版本變
> RHEL 8 / RHEL 9 / Rocky 9 的預設清單不完全一樣，某些雲端映像檔還會再客製。
> **唯一可信的答案是在那台機器上跑**：
> ```bash
> firewall-cmd --list-all-zones | less
> ```

### zone 的 target：四個值決定「沒被規則命中時怎麼辦」 ★★★★

| target | 意義 |
| --- | --- |
| `default` | ★★★★ 沒命中就**拒絕**（實際上是走到最後的 reject 鏈）。絕大多數 zone 用這個 |
| `ACCEPT` | 沒命中就**放行**。`trusted` 用這個，等於沒有防火牆 |
| `DROP` | 沒命中就**丟棄不回應**。`drop` 用這個 |
| `%%REJECT%%` | 沒命中就**明確拒絕**。`block` 用這個 |

```bash
$ sudo firewall-cmd --zone=internal --set-target=default --permanent
success
```

★★★★ 自建 zone 時如果忘了設 target，預設是 `default`（拒絕），這通常是你要的。
**唯一要警覺的是把某個 zone 設成 `ACCEPT`** —— 那個 zone 底下的規則就全部形同虛設了。

## 環境準備與安裝

### 步驟 0：先確認現況 ★★★★

動任何一條規則之前，先把這四件事問清楚。

```bash
$ cat /etc/rocky-release; rpm -q firewalld
Rocky Linux release 9.4 (Blue Onyx)
firewalld-1.2.5-2.el9.noarch
```

```bash
$ sudo systemctl is-enabled firewalld; sudo firewall-cmd --state
enabled
running
```

★★★ `--state` 只有兩種答案：`running`，或 `not running`（此時 exit code 非 0）。
如果是 `not running`，**這台機器現在沒有任何防火牆**。

```bash
$ sudo firewall-cmd --get-default-zone
public

$ sudo firewall-cmd --get-active-zones
public
  interfaces: ens192
```

★★★★ `--get-active-zones` 是最重要的一條 —— 它只列出**真的有介面或來源綁上去**的 zone。
沒出現在這裡的 zone，就算你在裡面加了一百條規則也不會有任何作用。這是新手第一名的錯誤。

```bash
$ sudo firewall-cmd --list-all
public (active)
  target: default
  icmp-block-inversion: no
  interfaces: ens192
  sources:
  services: cockpit dhcpv6-client ssh
  ports:
  protocols:
  forward: yes
  masquerade: no
  forward-ports:
  source-ports:
  icmp-blocks:
  rich rules:
```

★★★ 讀這段輸出的順序：先看 `interfaces` / `sources`（誰進得來這個 zone），
再看 `services` / `ports`（進來之後能碰什麼），最後看 `rich rules`（有沒有例外）。

> [!info]- `forward: yes` 是 firewalld 1.0 的行為改變 ★★★
> firewalld **1.0 起同 zone 內的封包轉發（intra-zone forwarding）預設開啟**。
> 在 0.9 以前，同一個 zone 裡的兩個介面之間預設是不能互轉的。
> 從 RHEL 8（firewalld 0.9）升到 RHEL 9（1.x）時如果發現「轉發突然通了」，原因在這裡。
> 要關掉：`firewall-cmd --zone=public --remove-forward --permanent`

### 安裝與啟用

Rocky／RHEL 最小安裝通常已經有了；若沒有：

```bash
$ sudo dnf install -y firewalld
...
Installed:
  firewalld-1.2.5-2.el9.noarch  firewalld-filesystem-1.2.5-2.el9.noarch
  python3-firewall-1.2.5-2.el9.noarch
Complete!

$ sudo systemctl enable --now firewalld
Created symlink /etc/systemd/system/dbus-org.fedoraproject.FirewallD1.service → /usr/lib/systemd/system/firewalld.service.
Created symlink /etc/systemd/system/multi-user.target.wants/firewalld.service → /usr/lib/systemd/system/firewalld.service.
```

> [!danger] ★★★★★ 在遠端主機上第一次 `systemctl start firewalld` 之前，先確認 ssh 有開
> firewalld 一啟動就套用 default zone（`public`）的規則。`public` **出廠有含 `ssh` service**，
> 所以標準 22 埠是安全的。**但如果你已經照 [[020-02-01-07-svc-SSH-安全強化]] 把 sshd 改成非標準埠
> （例如 2222），啟動 firewalld 的瞬間你就會斷線。**
>
> 正確順序 —— 先用 offline 指令把埠寫進設定，再啟動：
> ```bash
> sudo firewall-offline-cmd --zone=public --add-port=2222/tcp
> sudo systemctl enable --now firewalld
> ```
> **救援方法**：真的鎖住了，唯一的路是主機 console／IPMI／iDRAC／PVE 的 noVNC，
> 進去之後 `systemctl stop firewalld` 就恢復裸奔狀態，再慢慢修。

### 兩個容易搞混的相近工具 ★★★

| 工具 | 什麼時候用 |
| --- | --- |
| `firewall-cmd` | firewalld **正在跑**的時候。透過 D-Bus 跟服務溝通 |
| `firewall-offline-cmd` | firewalld **沒在跑**的時候（例如尚未啟動、或在 chroot／映像檔裡）。直接改 `/etc/firewalld/` 的 XML。★★★★ 它的所有改動天生就是 permanent |
| `firewall-config` | GUI，需要桌面環境。伺服器上通常不裝 |

## 基礎設定

### ★★★★★ 第一課：runtime 與 permanent 是兩份獨立的設定

這是本篇最重要的一段。**沒搞懂這段，你寫的規則不是「重開機就不見」，就是「改了沒生效」。**

```text
┌─────────────────────────┐        ┌──────────────────────────────┐
│  runtime（記憶體）        │        │  permanent（磁碟 XML）         │
│  現在正在生效的規則        │        │  /etc/firewalld/zones/*.xml   │
│  重開機 / --reload 就沒了 │        │  重開機後從這裡載入             │
└─────────────────────────┘        └──────────────────────────────┘
        ▲                                        │
        │  ① firewall-cmd --add-service=http     │
        │     （不加 --permanent → 只改 runtime） │
        │                                        │
        │  ③ firewall-cmd --reload  ─────────────┘
        │     permanent 覆蓋 runtime（runtime 的暫時規則全部消失）
        │
        └─ ② firewall-cmd --runtime-to-permanent
              把 runtime 現況整包存成 permanent
```

四種操作，結果完全不同：

| 你打的指令 | 現在生效？ | 重開機還在？ | 星級 |
| --- | --- | --- | --- |
| `firewall-cmd --add-service=http` | ✅ 立刻 | ❌ **不在** | ★★★★★ |
| `firewall-cmd --permanent --add-service=http` | ❌ **沒生效** | ✅ 在 | ★★★★★ |
| `firewall-cmd --permanent --add-service=http` 之後 `firewall-cmd --reload` | ✅ | ✅ | ★★★★★ |
| `firewall-cmd --add-service=http` 之後 `firewall-cmd --runtime-to-permanent` | ✅ | ✅ | ★★★★ |

> [!warning] ★★★★★ 這是「重開機規則就不見了」的唯一原因
> 忘了 `--permanent`。firewalld 不會警告你，指令一樣回 `success`。
> 反過來，「我明明加了規則但 curl 還是連不上」則幾乎都是**加了 `--permanent` 卻忘了 `--reload`**。
>
> 記法：**`--permanent` 是「寫進檔案」，`--reload` 是「把檔案吃進去」。兩個都要做。**

★★★★ 隨時可以檢查兩份設定差在哪：

```bash
# runtime 現況
$ sudo firewall-cmd --zone=public --list-services
cockpit dhcpv6-client ssh http

# permanent 檔案內容
$ sudo firewall-cmd --permanent --zone=public --list-services
cockpit dhcpv6-client ssh
```

★★★★ 兩行不一樣 → 表示有人加了規則沒存檔，**下次 reload 或重開就會消失**。
把這兩行做成巡檢腳本的一條，可以擋掉一大票半夜的事故。

### 標準工作流（本篇之後全部照這個做）★★★★★

```bash
# ① 先在 runtime 試（可能會斷線的規則用這個試，反正重開就恢復）
sudo firewall-cmd --zone=public --add-service=http

# ② 驗證服務真的通了
curl -I http://<主機IP>/

# ③ 確認沒問題，才落地
sudo firewall-cmd --runtime-to-permanent

# ④ 再確認一次兩份一致
sudo firewall-cmd --permanent --zone=public --list-services
```

★★★★ 這個順序有一個很大的好處：**萬一 ① 的規則把自己鎖住了，重開機就自動恢復。**
反之，先 `--permanent` 再 `--reload` 的話，鎖住就是永久鎖住，只能去 console。

### 開放服務：用 service 名稱，不要用埠號 ★★★★

```bash
$ sudo firewall-cmd --permanent --zone=public --add-service=http
success
$ sudo firewall-cmd --permanent --zone=public --add-service=https
success
$ sudo firewall-cmd --reload
success
$ sudo firewall-cmd --zone=public --list-services
cockpit dhcpv6-client http https ssh
```

有哪些 service 可用：

```bash
$ sudo firewall-cmd --get-services | tr ' ' '\n' | grep -E '^(http|https|mysql|postgresql|ssh|dns|ntp)$'
dns
http
https
mysql
ntp
postgresql
ssh
```

```bash
$ sudo firewall-cmd --info-service=mysql
mysql
  ports: 3306/tcp
  protocols:
  source-ports:
  modules:
  destination:
  includes:
  helpers:
```

★★★★ **優先用 service 名稱而不是埠號**，理由有三個：

1. **可讀性** —— 半年後看 `--list-services` 是 `mysql`，比看到 `3306/tcp` 好懂
2. **多埠服務一次搞定** —— 例如 `samba` 涵蓋四個埠，你不用一個個記
3. **套件升級時 service 定義會跟著更新**（例如某服務新增了一個埠）

只有在**服務跑在非標準埠**時才用 `--add-port`：

```bash
$ sudo firewall-cmd --permanent --zone=public --add-port=8080/tcp
success
$ sudo firewall-cmd --permanent --zone=public --add-port=30000-30100/udp
success
```

★★ 埠範圍用 `-` 連接，注意是 `30000-30100/udp`，**不是 `30000:30100`**（那是 iptables 的寫法）。

### 移除規則

```bash
$ sudo firewall-cmd --permanent --zone=public --remove-service=cockpit
success
$ sudo firewall-cmd --reload
success
```

★★★ 移除**不存在**的規則會得到警告而不是錯誤，這對寫成冪等腳本很方便：

```bash
$ sudo firewall-cmd --permanent --zone=public --remove-service=telnet
Warning: NOT_ENABLED: telnet
success
```

### 介面綁 zone ★★★★

```bash
# 查現在綁在哪
$ sudo firewall-cmd --get-zone-of-interface=ens192
public

# 改綁到 internal（--change-interface 會先解除舊綁定，比 --add-interface 安全）
$ sudo firewall-cmd --permanent --zone=internal --change-interface=ens224
The interface is under control of NetworkManager, setting zone to 'internal'.
success
```

> [!warning] ★★★★ NetworkManager 會蓋掉你的介面綁定
> RHEL 系的介面幾乎都由 NetworkManager 管。連線設定檔裡的 `connection.zone` 才是最終權威 ——
> 網路重啟或 `nmcli con up` 之後，firewalld 的綁定會被 NM 的值覆蓋。
> **要讓綁定真正持久，改 NM 那一邊**：
> ```bash
> sudo nmcli connection modify ens224 connection.zone internal
> sudo nmcli connection up ens224
> ```
> 驗證：`nmcli -f connection.zone connection show ens224`

### ★★★★ 來源網段綁 zone —— firewalld 最好用的一招

這是 ufw 做起來很囉嗦、firewalld 做起來很優雅的場景。

```bash
# 把機房管理網段整段丟進 internal zone
$ sudo firewall-cmd --permanent --zone=internal --add-source=10.10.0.0/24
success

# internal 裡面只開管理用的服務
$ sudo firewall-cmd --permanent --zone=internal --add-service=ssh
success
$ sudo firewall-cmd --permanent --zone=internal --add-service=mysql
success
$ sudo firewall-cmd --reload
success

$ sudo firewall-cmd --get-active-zones
internal
  sources: 10.10.0.0/24
public
  interfaces: ens192
```

結果：**來自 10.10.0.0/24 的封包走 `internal`（有 ssh、mysql），其他所有來源走 `public`（只有 http/https）。**
一張網卡，兩套規則，靠的就是「來源綁定優先」。

> [!danger] ★★★★★ 把 ssh 從 public 拿掉之前，先確認你的管理網段真的綁對了
> 承上例，如果你接著跑 `firewall-cmd --permanent --zone=public --remove-service=ssh --reload`，
> 而你的跳板機其實在 `10.20.0.0/24`（不在 internal 的 source 裡），**你會立刻斷線且無法再連回來**。
>
> **安全做法**：先開一條有時效的保險再動手 ——
> ```bash
> sudo firewall-cmd --zone=public --add-service=ssh --timeout=600
> ```
> 這條 runtime 規則 10 分鐘後自動消失。在這 10 分鐘內確認新規則下你還連得進來；
> 確認 OK 就讓它自然過期，不 OK 就把 permanent 改回來。
> **救援方法**：已經鎖住了 → console 進去 `firewall-cmd --zone=public --add-service=ssh`（runtime 即時生效）。

### ★★★ 快速判斷「某個埠現在開不開」

```bash
$ sudo firewall-cmd --zone=public --query-service=http
yes
$ sudo firewall-cmd --zone=public --query-port=3306/tcp
no
```

★★★ `--query-*` 系列**不印訊息、只用 exit code**（0 = yes），適合寫進監控腳本：

```bash
if firewall-cmd --zone=public --query-service=https >/dev/null 2>&1; then
  echo "https 已開放"
fi
```

## 進階設定與調校

### service 定義檔：讀懂它，然後自己寫一個 ★★★★

```bash
$ cat /usr/lib/firewalld/services/https.xml
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>WWW (HTTPS)</short>
  <description>HTTPS is a modified HTTP used to serve Web pages when security is important. Examples are sites that require logins like stores or web mail. This option is not required for viewing pages locally or developing Web pages. You need the httpd package installed for this option to be useful.</description>
  <port protocol="tcp" port="443"/>
</service>
```

| 路徑 | 用途 | 星級 |
| --- | --- | --- |
| `/usr/lib/firewalld/services/` | ★★★★ **套件提供的定義，不要改**。`dnf update` 會覆蓋 | ★★★★ |
| `/etc/firewalld/services/` | ★★★★★ **你自己的定義放這裡**。同名檔案會蓋過 `/usr/lib` 的版本 | ★★★★★ |

這個「`/usr/lib` 是原廠、`/etc` 是你的」規則在 firewalld 裡是**一致的**，
`zones/`、`policies/`、`ipsets/`、`helpers/` 都一樣。

#### 自訂 service：以「機關內部的 Laravel Nova 後台」為例

有兩種做法，**建議用指令而不是手寫檔案**（指令會幫你驗證格式）。

```bash
$ sudo firewall-cmd --permanent --new-service=nova-admin
success
$ sudo firewall-cmd --permanent --service=nova-admin --set-short="Nova Admin Backend"
success
$ sudo firewall-cmd --permanent --service=nova-admin --set-description="機關內部管理後台，僅開放管理網段"
success
$ sudo firewall-cmd --permanent --service=nova-admin --add-port=8443/tcp
success
$ sudo firewall-cmd --reload
success
```

產生的檔案：

```bash
$ cat /etc/firewalld/services/nova-admin.xml
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>Nova Admin Backend</short>
  <description>機關內部管理後台，僅開放管理網段</description>
  <port port="8443" protocol="tcp"/>
</service>
```

之後就可以像內建服務一樣用：

```bash
$ sudo firewall-cmd --permanent --zone=internal --add-service=nova-admin
success
$ sudo firewall-cmd --reload
success
```

★★★ 也可以**基於現成的 service 改一份自己的**（最常見的需求：sshd 換埠）：

```bash
$ sudo cp /usr/lib/firewalld/services/ssh.xml /etc/firewalld/services/ssh.xml
$ sudo sed -i 's/port="22"/port="2222"/' /etc/firewalld/services/ssh.xml
$ sudo firewall-cmd --reload
success
$ sudo firewall-cmd --info-service=ssh
ssh
  ports: 2222/tcp
  ...
```

> [!tip] ★★★ 這一招比 `--add-port=2222/tcp` 好
> 因為所有 zone 裡寫的還是 `ssh`，語意清楚；而且以後再換埠只要改這一個檔案，
> 不用去每個 zone 找 `2222/tcp` 換掉。缺點是**要記得這台機器的 `ssh` 已經被你重新定義過**，
> 寫進交接文件裡。

### rich rule：四種你真的會用到的寫法 ★★★★

rich rule 是 firewalld 用來表達「service／port 表達不了的條件」的語法。
基本骨架（`man firewalld.richlanguage`）：

```text
rule [family="ipv4|ipv6"]
     [source address="..."] [destination address="..."]
     ( service name="..." | port port="..." protocol="..." | protocol value="..." | icmp-type name="..." | masquerade | forward-port ... )
     [log [prefix="..."] [level="..."] [limit value="rate/duration"]]
     [audit]
     ( accept | reject [type="..."] | drop | mark set="..." )
     [limit value="rate/duration"]
```

★★★ 順序是固定的：**條件 → 動作對象 → log → 最終動作 → limit**。順序寫錯會被拒絕。

#### ① 來源限制：只讓某個 IP 連 MySQL ★★★★

```bash
$ sudo firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4"
  source address="10.10.0.51/32"
  service name="mysql"
  accept'
success
$ sudo firewall-cmd --reload
success
$ sudo firewall-cmd --zone=public --list-rich-rules
rule family="ipv4" source address="10.10.0.51/32" service name="mysql" accept
```

★★★★ 注意：這條**只允許 10.10.0.51**，其他來源連 3306 會被 zone 的 target 拒絕。
你**不需要**再寫一條「拒絕其他人」—— firewalld 是預設拒絕的白名單模型。

#### ② 明確封鎖某個來源 ★★★

```bash
$ sudo firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4" source address="203.0.113.66/32" drop'
success
```

★★★★ **rich rule 的優先權高於一般的 service／port 規則**，所以這條 drop 會贏過 `--add-service=http`。
firewalld 內部的排序是：`deny` 類的 rich rule → `allow` 類的 rich rule → service/port → zone target。
這也是為什麼**臨時封鎖攻擊來源要用 rich rule**，而不是想辦法把它從某個 service 排除。

#### ③ 記錄 + 速率限制：抓 ssh 掃描 ★★★★

```bash
$ sudo firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4"
  service name="ssh"
  log prefix="SSH-ACCESS " level="info" limit value="6/m"
  accept'
success
$ sudo firewall-cmd --reload
success
```

驗證（另一台機器連進來後）：

```bash
$ sudo journalctl -k -g 'SSH-ACCESS' -n 3
Sep 03 10:22:14 web01 kernel: SSH-ACCESS IN=ens192 OUT= MAC=00:50:56:aa:bb:cc:... SRC=10.10.0.51 DST=10.20.5.10 LEN=60 TOS=0x00 PREC=0x00 TTL=63 ID=54321 DF PROTO=TCP SPT=53412 DPT=22 WINDOW=64240 RES=0x00 SYN URGP=0
```

★★★★★ `log ... limit value="6/m"` 的 limit **限制的是「寫幾行 log」，不是「擋幾個連線」**。
這個 limit 非常重要 —— 沒有它，被掃描時 journal 會在幾分鐘內被塞爆，
真正的錯誤訊息就淹沒了（見 [[020-01-19-guide-Linux-日誌系統]]）。

要限制**連線速率**，limit 要放在最後（動作之後）：

```bash
$ sudo firewall-cmd --permanent --zone=public --add-rich-rule='
  rule family="ipv4"
  service name="ssh"
  accept
  limit value="10/m"'
success
```

★★★★ 這條的意思是「每分鐘最多接受 10 個新的 ssh 連線，超過的丟掉」。
可用單位：`s`（秒）、`m`（分）、`h`（時）、`d`（天）。

> [!tip] ★★★ rate limit 只是止血，不是解方
> 針對暴力破解，firewalld 的 limit 只能拖慢對方；真正該做的是
> **關掉密碼登入**（[[020-02-01-07-svc-SSH-安全強化]]）＋ **Fail2ban 自動封鎖**
> （[[090-02-05-guide-防護-Fail2ban入侵防護]]）。三者是互補，不是取代。

#### ④ 時效規則：`--timeout` ★★★★

```bash
$ sudo firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4" source address="10.10.0.90/32" service name="ssh" accept' --timeout=1800
success
```

★★★★★ **`--timeout` 只能用在 runtime（不能跟 `--permanent` 併用）**，
30 分鐘後規則自動消失。這是「臨時讓廠商進來維護」的標準做法 ——
不用擔心事後忘記關，時間到自己就沒了。

```bash
$ sudo firewall-cmd --permanent --add-rich-rule='...' --timeout=1800
Error: INVALID_OPTION: can't use --timeout with --permanent
```

### 埠轉發與 masquerade ★★★★

#### 同機轉發：外部 80 → 本機 8080

```bash
$ sudo firewall-cmd --permanent --zone=public \
    --add-forward-port=port=80:proto=tcp:toport=8080
success
$ sudo firewall-cmd --reload
success
$ sudo firewall-cmd --zone=public --list-forward-ports
port=80:proto=tcp:toport=8080:toaddr=
```

★★★ 這種情況**不需要 masquerade**，因為封包沒有離開這台機器。

#### 轉到另一台機器：外部 80 → 10.10.0.60:8080

```bash
$ sudo firewall-cmd --permanent --zone=public \
    --add-forward-port=port=80:proto=tcp:toport=8080:toaddr=10.10.0.60
success
$ sudo firewall-cmd --permanent --zone=public --add-masquerade
success
$ sudo firewall-cmd --reload
success
```

> [!warning] ★★★★★ 少了 `--add-masquerade`，封包出得去回不來
> 沒有 masquerade 的話，後端 10.10.0.60 看到的來源 IP 是**原始客戶端**，
> 它的回應會直接送給客戶端而不是繞回這台轉發機 —— 客戶端收到一個來源 IP 不對的封包，直接丟棄。
> 現象就是「**連線 hang 住直到 timeout**」，而且 tcpdump 在轉發機上看得到去、看不到回。
>
> 加了 masquerade 之後後端看到的來源會變成轉發機的 IP，**後端的存取日誌就失去真實客戶端 IP**。
> 這是為什麼 Web 服務通常寧可用 Nginx 反向代理（可以帶 `X-Forwarded-For`）
> 而不是用防火牆做埠轉發，見 [[060-02-02-04-guide-Nginx-反向代理與負載平衡]]。

★★★★ 別忘了核心的 IP 轉發開關：

```bash
$ cat /proc/sys/net/ipv4/ip_forward
0
$ echo 'net.ipv4.ip_forward = 1' | sudo tee /etc/sysctl.d/90-ipforward.conf
net.ipv4.ip_forward = 1
$ sudo sysctl --system
...
* Applying /etc/sysctl.d/90-ipforward.conf ...
net.ipv4.ip_forward = 1
```

★★★ `--add-masquerade` 本身會處理 SNAT，但**跨介面轉發仍需要 `ip_forward=1`**。
`external` zone 預設就開了 masquerade，這也是它設計來給 NAT 閘道用的原因。

### ICMP 控制 ★★

```bash
# 不回應 ping
$ sudo firewall-cmd --permanent --zone=public --add-icmp-block=echo-request
success
```

> [!tip] ★★★ 不建議擋 ping
> 擋掉 `echo-request` 對安全幾乎沒有幫助（掃描器根本不靠 ping 判斷主機存活），
> 卻會讓你自己的監控（[[100-01-04-guide-日誌-健康檢查與可用性監控]]）與同事的第一線排查失去最基本的工具。
> ★★★★★ **絕對不要擋 `fragmentation-needed`／IPv6 的 `packet-too-big`** —— 那會直接打壞 Path MTU Discovery，
> 症狀是「小檔案正常、大檔案傳到一半卡死」，這種問題可以查一整天。

### 全域記錄被拒封包 ★★★

```bash
$ sudo firewall-cmd --set-log-denied=unicast
success
$ sudo firewall-cmd --get-log-denied
unicast
```

可選值：`all`／`unicast`／`broadcast`／`multicast`／`off`（預設 `off`）。
★★★★ 生產環境**選 `unicast` 不要選 `all`** —— `all` 會把大量廣播／多播噪音寫進 journal。
這個設定會直接改 `/etc/firewalld/firewalld.conf`，是永久的。

### panic mode：緊急全斷 ★★★

```bash
$ sudo firewall-cmd --panic-on
success
```

> [!danger] ★★★★★ panic mode 會切斷「包含你自己 ssh」在內的所有連線
> `--panic-on` 丟棄**所有**進出封包，等同於把網路線拔掉。遠端下這道指令 = 立刻失聯，
> 而且**你沒辦法再連進去把它關掉**。
>
> 只有在「已經在 console 前面」或「確定要把這台機器從網路上隔離、之後會親自去現場」時才用。
> **救援方法**：console 登入後 `firewall-cmd --panic-off`。
> 遠端要用的話，一定配 `--timeout` 的替代方案或事先排好 `at` 任務自動解除。

```bash
$ sudo firewall-cmd --query-panic
yes
$ sudo firewall-cmd --panic-off
success
```

### ★★★★ firewalld ↔ ufw 對照表（18 列）

| 要做的事 | firewalld | ufw | 星級 |
| --- | --- | --- | --- |
| 啟用／開機自動啟動 | `systemctl enable --now firewalld` | `ufw enable` | ★★★ |
| 停用 | `systemctl disable --now firewalld` | `ufw disable` | ★★★ |
| 看目前狀態 | `firewall-cmd --state` | `ufw status` | ★★★ |
| 看完整規則 | `firewall-cmd --list-all` | `ufw status verbose` | ★★★★ |
| 看帶編號的規則 | （無編號概念，靠 zone 分類） | `ufw status numbered` | ★★★★ |
| 開放服務 | `firewall-cmd --permanent --add-service=http` | `ufw allow http` | ★★★★ |
| 開放埠 | `firewall-cmd --permanent --add-port=8080/tcp` | `ufw allow 8080/tcp` | ★★★★ |
| 開放埠範圍 | `--add-port=30000-30100/udp` | `ufw allow 30000:30100/udp` | ★★★ |
| 限制來源 | `--add-rich-rule='rule family="ipv4" source address="10.10.0.0/24" service name="ssh" accept'` | `ufw allow from 10.10.0.0/24 to any port 22` | ★★★★★ |
| 封鎖某來源 | `--add-rich-rule='rule family="ipv4" source address="1.2.3.4" drop'` | `ufw deny from 1.2.3.4` | ★★★★ |
| 刪規則 | `--permanent --remove-service=http` | `ufw delete allow http` 或 `ufw delete 3` | ★★★★ |
| ★★★★★ 讓規則永久生效 | 加 `--permanent` **再** `--reload` | ufw **沒這回事**，寫下去就是永久 | ★★★★★ |
| 只暫時生效、重開就沒 | 不加 `--permanent`（預設就是 runtime） | ufw **做不到**（要自己記得刪） | ★★★★ |
| 規則帶有效期 | `--add-rich-rule='...' --timeout=1800` | ufw **沒有**，要自己配 `at`／cron | ★★★★ |
| 記錄被拒封包 | `firewall-cmd --set-log-denied=unicast` | `ufw logging on` | ★★★ |
| 埠轉發 | `--add-forward-port=port=80:proto=tcp:toport=8080` | `ufw route allow ...` ＋ 手改 `before.rules` 的 NAT 段 | ★★★★ |
| NAT / masquerade | `--add-masquerade` | 手改 `/etc/ufw/before.rules` 加 `MASQUERADE` | ★★★★ |
| 依信任等級分組規則 | ★★★★★ **zone**（firewalld 的招牌） | ufw **沒有對應概念** | ★★★★★ |
| 緊急全斷 | `firewall-cmd --panic-on` | `ufw default deny incoming` ＋ 刪規則 | ★★★ |
| 一次清空重來 | `firewall-cmd --permanent --zone=X --remove-service=...`（逐項）或刪 `/etc/firewalld/zones/X.xml` 後 reload | `ufw reset` | ★★★ |

★★★★ **最重要的兩列**是「讓規則永久生效」與「zone」。
從 ufw 轉過來的人幾乎 100% 會在第一列翻車；而如果不用 zone，你等於是在拿 firewalld 當難用的 ufw。

> [!info]- 為什麼 firewalld 沒有「規則編號」？
> ufw 的規則是**有序列表**，順序決定結果，所以要編號來刪。
> firewalld 的規則是**集合**（一個 zone 裡的 service 是無序的），內部排序由 firewalld 依
> 「deny rich rule → allow rich rule → service/port → target」的固定優先權自動決定，
> 所以你不需要、也不能指定順序。★★★ 這是設計哲學的差異，不是功能缺失。

### policy object：zone 之間的流量 ★★

firewalld 0.9 起新增 **policy**，用來描述「從 A zone 到 B zone」的流量（zone 只描述「進入本機」）。
做軟路由／閘道時會用到：

```bash
$ sudo firewall-cmd --permanent --new-policy=dmz-to-internal
success
$ sudo firewall-cmd --permanent --policy=dmz-to-internal --add-ingress-zone=dmz
success
$ sudo firewall-cmd --permanent --policy=dmz-to-internal --add-egress-zone=internal
success
$ sudo firewall-cmd --permanent --policy=dmz-to-internal --set-target=REJECT
success
$ sudo firewall-cmd --reload
success
```

★★ 一般的單機伺服器用不到 policy。**如果你在做的是閘道器，比較建議直接用
OPNsense 或 nftables**（[[090-02-03-guide-防火牆-nftables與iptables]]），
firewalld 的 policy 表達能力有限、除錯也比較麻煩。

### 備份與還原 ★★★★

firewalld 的全部設定就是 `/etc/firewalld/` 底下的一堆 XML，備份很單純：

```bash
$ sudo tar czf /root/firewalld-$(date +%F).tar.gz /etc/firewalld/
tar: Removing leading `/' from member names
$ ls -lh /root/firewalld-2026-09-03.tar.gz
-rw-r--r--. 1 root root 4.2K Sep  3 10:40 /root/firewalld-2026-09-03.tar.gz
```

還原：解開覆蓋回去，然後 `firewall-cmd --reload`。

★★★★ 落地前先驗證 XML 語法，避免 reload 失敗導致規則全空：

```bash
$ sudo firewall-cmd --check-config
success
```

## 完整實戰範例

### 情境

一台新交付的 **Rocky Linux 9.4** 要當機關的內部網站伺服器：

| 項目 | 值 |
| --- | --- |
| 主機名 | `web01` |
| 對外介面 | `ens192`，IP `10.20.5.10/24` |
| 服務 | Nginx（80 → 全部導向 443）、MySQL 8（3306，**只給應用伺服器**） |
| 管理網段 | `10.10.0.0/24`（機房跳板機＋維運人員 VPN 都在這段） |
| 應用伺服器 | `10.20.5.20`（Laravel，需要連 MySQL） |
| 監控主機 | `10.10.0.80`（Prometheus，需要抓 node_exporter 9100） |
| sshd | 標準 22 埠，**只允許管理網段** |

目標規則：

```text
來源 10.10.0.0/24（管理網段）    → internal zone → ssh(22) + node_exporter(9100)
來源 10.20.5.20（應用伺服器）    → 走 public，但用 rich rule 單獨開 mysql
其他所有來源                     → public zone   → http(80) + https(443)
```

### 第 0 步：前置檢查（不可略過）★★★★★

```bash
$ hostnamectl --static; ip -4 -br addr show ens192
web01
ens192           UP             10.20.5.10/24

$ sudo ss -tlnp | grep -E ':(22|80|443|3306|9100)\b'
LISTEN 0  511      0.0.0.0:80    0.0.0.0:*  users:(("nginx",pid=1183,fd=6))
LISTEN 0  511      0.0.0.0:443   0.0.0.0:*  users:(("nginx",pid=1183,fd=8))
LISTEN 0  128      0.0.0.0:22    0.0.0.0:*  users:(("sshd",pid=982,fd=3))
LISTEN 0  151    127.0.0.1:3306  0.0.0.0:*  users:(("mysqld",pid=1402,fd=23))
LISTEN 0  4096     0.0.0.0:9100  0.0.0.0:*  users:(("node_exporter",pid=1520,fd=3))
```

★★★★★ **這一步發現了一個問題：MySQL 綁在 `127.0.0.1`，應用伺服器根本連不到。**
防火牆開了也沒用 —— 這是最經典的「開了防火牆還是不通」誤判。先去改 `bind-address` 再繼續。

```bash
$ sudo sed -i 's/^bind-address.*/bind-address = 10.20.5.10/' /etc/my.cnf.d/mysql-server.cnf
$ sudo systemctl restart mysqld
$ sudo ss -tlnp | grep 3306
LISTEN 0  151   10.20.5.10:3306  0.0.0.0:*  users:(("mysqld",pid=2211,fd=23))
```

再確認你現在的來源 IP（決定會不會把自己鎖住）：

```bash
$ who am i
ops      pts/0        2026-09-03 09:58 (10.10.0.51)
```

★★★★ `10.10.0.51` 在 `10.10.0.0/24` 裡 → 待會綁 internal 之後你還連得進來。**這一步一定要確認。**

### 第 1 步：確認 firewalld 在跑、記下原始狀態

```bash
$ sudo systemctl enable --now firewalld
$ sudo firewall-cmd --state
running
$ sudo tar czf /root/firewalld-before-$(date +%F).tar.gz /etc/firewalld/ 2>/dev/null
$ sudo firewall-cmd --list-all
public (active)
  target: default
  interfaces: ens192
  sources:
  services: cockpit dhcpv6-client ssh
  ports:
  forward: yes
  masquerade: no
  forward-ports:
  icmp-blocks:
  rich rules:
```

### 第 2 步：先在 runtime 試（鎖住也能重開機救回來）★★★★★

```bash
# ── internal zone：管理網段 ──
$ sudo firewall-cmd --zone=internal --add-source=10.10.0.0/24
success
$ sudo firewall-cmd --zone=internal --add-service=ssh
success
$ sudo firewall-cmd --zone=internal --add-port=9100/tcp
success

# ── public zone：對外只留 http/https ──
$ sudo firewall-cmd --zone=public --add-service=http
success
$ sudo firewall-cmd --zone=public --add-service=https
success

# ── MySQL：只給應用伺服器那一台 ──
$ sudo firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4" source address="10.20.5.20/32" service name="mysql" accept'
success

# ── 記錄 ssh 存取（帶 log rate limit）──
$ sudo firewall-cmd --zone=internal --add-rich-rule='
  rule family="ipv4" service name="ssh"
  log prefix="SSH-INTERNAL " level="info" limit value="6/m" accept'
success
```

★★★★ 注意：**還沒有把 ssh 從 public 拿掉**。這是刻意的 —— 先確認 internal 那條路走得通再拆保險。

### 第 3 步：驗證（在做任何 permanent 之前）

```bash
$ sudo firewall-cmd --get-active-zones
internal
  sources: 10.10.0.0/24
public
  interfaces: ens192

$ sudo firewall-cmd --zone=internal --list-all
internal (active)
  target: default
  sources: 10.10.0.0/24
  services: dhcpv6-client mdns samba-client ssh
  ports: 9100/tcp
  ...
  rich rules:
	rule family="ipv4" service name="ssh" log prefix="SSH-INTERNAL " level="info" limit value="6/m" accept
```

★★★★ 這裡看到 `internal` 帶著出廠的 `mdns` 與 `samba-client` —— **伺服器不需要，拿掉**：

```bash
$ sudo firewall-cmd --zone=internal --remove-service=mdns
success
$ sudo firewall-cmd --zone=internal --remove-service=samba-client
success
$ sudo firewall-cmd --zone=internal --remove-service=dhcpv6-client
success
```

從外部驗證（另開一個 shell，從管理機 `10.10.0.51`）：

```bash
[ops@jump ~]$ nc -zv 10.20.5.10 22
Ncat: Connected to 10.20.5.10:22.
[ops@jump ~]$ nc -zv 10.20.5.10 9100
Ncat: Connected to 10.20.5.10:9100.
[ops@jump ~]$ nc -zv -w3 10.20.5.10 3306
Ncat: Connection timed out.        # ★★★★ 正確：管理網段不該連得到 MySQL
```

從應用伺服器 `10.20.5.20`：

```bash
[app@app01 ~]$ nc -zv 10.20.5.10 3306
Ncat: Connected to 10.20.5.10:3306.
[app@app01 ~]$ nc -zv -w3 10.20.5.10 22
Ncat: Connection timed out.        # ★★★★ 正確：應用伺服器不該能 ssh 進資料庫主機
```

從外部任意來源：

```bash
$ curl -sI -o /dev/null -w '%{http_code}\n' https://10.20.5.10/ -k
200
$ nc -zv -w3 10.20.5.10 22
nc: connect to 10.20.5.10 port 22 (tcp) failed: Connection timed out
```

★★★ 等等 —— 這裡 22 應該還是通的（public 還有 ssh）。若你看到 timeout，
表示這個「外部來源」其實也在 `10.10.0.0/24` 裡…… 但那樣應該會通。
★★★★ 真正的排查方式永遠是：**回頭跑 `firewall-cmd --get-active-zones` 確認這個來源歸哪個 zone**，
不要猜。

### 第 4 步：拆掉 public 的 ssh（帶保險）★★★★★

> [!danger] ★★★★★ 這是本例唯一會鎖死自己的一步
> 先開一條 10 分鐘的臨時保險再動手。

```bash
$ sudo firewall-cmd --zone=public --add-rich-rule='
  rule family="ipv4" source address="10.10.0.51/32" service name="ssh" accept' --timeout=600
success
$ sudo firewall-cmd --zone=public --remove-service=ssh
success
$ sudo firewall-cmd --zone=public --remove-service=cockpit
success
```

**現在開一個全新的 ssh 連線測試（不要用手上這條已建立的連線判斷 —— 已建立的連線靠 conntrack 不受新規則影響）：**

```bash
[ops@jump ~]$ ssh -o ConnectTimeout=5 ops@10.20.5.10 'echo OK'
OK
```

★★★★★ **「舊連線還活著不代表新連線進得來」** 是防火牆事故的頭號盲點。永遠開新視窗測。

### 第 5 步：確認無誤，落地成 permanent

```bash
$ sudo firewall-cmd --runtime-to-permanent
success
```

★★★★ 但注意 —— **第 4 步那條 `--timeout=600` 的臨時規則也會被一起存進去！**
檢查並刪掉：

```bash
$ sudo firewall-cmd --permanent --zone=public --list-rich-rules
rule family="ipv4" source address="10.20.5.20/32" service name="mysql" accept
rule family="ipv4" source address="10.10.0.51/32" service name="ssh" accept

$ sudo firewall-cmd --permanent --zone=public --remove-rich-rule='
  rule family="ipv4" source address="10.10.0.51/32" service name="ssh" accept'
success
$ sudo firewall-cmd --reload
success
```

★★★★★ **這是 `--runtime-to-permanent` 唯一的陷阱**：它是「整包快照」，
包含你本來只想暫時存在的東西。落地後一定要 `--list-all` 對過一遍。

### 第 6 步：驗收檢查表 ★★★★★

```bash
$ sudo firewall-cmd --list-all-zones | grep -A20 '^\(public\|internal\) '
internal (active)
  target: default
  sources: 10.10.0.0/24
  services: ssh
  ports: 9100/tcp
  protocols:
  forward: yes
  masquerade: no
  forward-ports:
  source-ports:
  icmp-blocks:
  rich rules:
	rule family="ipv4" service name="ssh" log prefix="SSH-INTERNAL " level="info" limit value="6/m" accept

public (active)
  target: default
  interfaces: ens192
  sources:
  services: http https
  ports:
  protocols:
  forward: yes
  masquerade: no
  forward-ports:
  source-ports:
  icmp-blocks:
  rich rules:
	rule family="ipv4" source address="10.20.5.20/32" service name="mysql" accept
```

| # | 檢查項 | 指令 | 期望 |
| --- | --- | --- | --- |
| 1 | runtime 與 permanent 一致 | `diff <(firewall-cmd --list-all-zones) <(firewall-cmd --permanent --list-all-zones)` | 只有 `(active)` 標記的差異 |
| 2 | 開機自動啟動 | `systemctl is-enabled firewalld` | `enabled` |
| 3 | 管理網段能 ssh | 從 10.10.0.51 開新連線 | 成功 |
| 4 | 其他來源不能 ssh | 從外部 `nc -zv -w3 host 22` | timeout |
| 5 | 應用機能連 MySQL | 從 10.20.5.20 `nc -zv host 3306` | connected |
| 6 | 管理網段不能連 MySQL | 從 10.10.0.51 `nc -zv -w3 host 3306` | timeout |
| 7 | 任意來源能連 https | `curl -kI https://host/` | 200 |
| 8 | ★★★★★ **重開機後還在** | `reboot` 後重跑第 1～7 項 | 全部一致 |

★★★★★ **第 8 項是唯一能證明 permanent 真的寫進去的方法。**
機關的機器很少重開，很多「重開就不見」的問題是三個月後停電才爆出來 ——
交付前一定要重開一次驗。

### 完整重建腳本

把上面整套寫成冪等腳本，方便部署到第二台、第三台：

```bash
#!/usr/bin/env bash
# fw-web01.sh —— Rocky 9 Nginx+MySQL 主機防火牆基準
set -euo pipefail

MGMT_NET="10.10.0.0/24"
APP_HOST="10.20.5.20/32"
IFACE="ens192"

echo "==> 檢查 firewalld"
systemctl is-active --quiet firewalld || { echo "firewalld 沒在跑"; exit 1; }

echo "==> 備份現況"
tar czf "/root/firewalld-before-$(date +%F-%H%M).tar.gz" /etc/firewalld/ 2>/dev/null

echo "==> internal zone：管理網段"
firewall-cmd --permanent --zone=internal --add-source="$MGMT_NET"
firewall-cmd --permanent --zone=internal --add-service=ssh
firewall-cmd --permanent --zone=internal --add-port=9100/tcp
for s in mdns samba-client dhcpv6-client; do
  firewall-cmd --permanent --zone=internal --remove-service="$s" || true
done

echo "==> public zone：對外服務"
firewall-cmd --permanent --zone=public --change-interface="$IFACE"
firewall-cmd --permanent --zone=public --add-service=http
firewall-cmd --permanent --zone=public --add-service=https
for s in ssh cockpit dhcpv6-client; do
  firewall-cmd --permanent --zone=public --remove-service="$s" || true
done
firewall-cmd --permanent --zone=public --add-rich-rule="rule family=\"ipv4\" source address=\"$APP_HOST\" service name=\"mysql\" accept"

echo "==> 語法檢查"
firewall-cmd --check-config

echo "==> 套用"
firewall-cmd --reload

echo "==> 結果"
firewall-cmd --get-active-zones
firewall-cmd --zone=internal --list-all
firewall-cmd --zone=public --list-all
echo "★★★★★ 請立刻從管理網段開一條新的 ssh 連線驗證，再離開現有 session。"
```

> [!danger] ★★★★★ 這支腳本會把 ssh 從 public 移除
> **只能在「你的來源 IP 確實落在 `$MGMT_NET` 裡」時執行。**
> 執行前先跑 `who am i` 確認來源，執行後**開新視窗**驗證，
> 確認之前不要關掉手上這條連線。
> **救援方法**：console 進去 `firewall-cmd --zone=public --add-service=ssh`（runtime 立即生效，不用 reload）。

## 常見錯誤與排錯

| # | 現象 | 原因 | 解法 | 星級 |
| --- | --- | --- | --- | --- |
| 1 | 加了規則，`--list-all` 也看得到，**但重開機就不見** | 忘了 `--permanent`，規則只寫進 runtime | 重下一次帶 `--permanent` 再 `--reload`；或當下用 `firewall-cmd --runtime-to-permanent` 補存 | ★★★★★ |
| 2 | `--permanent --add-service=http` 回 `success`，**但服務還是連不上** | 只寫進磁碟、沒載入記憶體 | `sudo firewall-cmd --reload` | ★★★★★ |
| 3 | 規則加在 `internal`，但完全沒作用 | ★★★★ 那個 zone **沒有綁任何介面或來源**，不在 active 清單裡 | `firewall-cmd --get-active-zones` 確認；用 `--add-source=` 或 `--change-interface=` 綁上去 | ★★★★★ |
| 4 | 明明綁了介面到 `internal`，重開機／`nmcli con up` 後又跳回 `public` | NetworkManager 的 `connection.zone` 才是權威，會覆蓋 firewalld | `nmcli connection modify <con> connection.zone internal && nmcli connection up <con>` | ★★★★ |
| 5 | 開了 `--add-service=mysql`，**外部仍連不到 3306** | 不是防火牆問題 —— 服務綁在 `127.0.0.1` | `ss -tlnp \| grep 3306` 確認；改 `bind-address` | ★★★★★ |
| 6 | 改完規則，用**現有的 ssh session** 測試發現「還是通的」，關掉後才發現連不進去 | ★★★★★ 已建立的連線走 conntrack 的 `ESTABLISHED`，不受新規則影響 | **永遠開一個新視窗／新連線測**，不要用手上這條判斷 | ★★★★★ |
| 7 | `firewall-cmd` 回 `Error: COMMAND_FAILED: ... Resource temporarily unavailable` | 底層 nftables／iptables 執行失敗，常見於同時跑了 iptables 直寫或 backend 不一致 | `journalctl -u firewalld -n 50` 看真正錯誤；確認 `/etc/firewalld/firewalld.conf` 的 `FirewallBackend=` | ★★★★ |
| 8 | `firewall-cmd` 回 `FirewallD is not running` | 服務沒起來 | `systemctl status firewalld`；常見是 XML 語法錯導致啟動失敗，先 `firewall-offline-cmd --check-config` | ★★★★ |
| 9 | `firewall-cmd --reload` 之後**所有規則都不見了** | permanent XML 檔壞掉／被誤刪，reload 讀到空設定 | 從 `/root/firewalld-*.tar.gz` 還原 `/etc/firewalld/`；下次改之前先 `--check-config` | ★★★★★ |
| 10 | rich rule 加不進去，回 `INVALID_RULE: unknown element` | rich rule 語法元素順序錯（例如把 `log` 寫在 `accept` 後面） | 順序固定為：條件 → service/port → log → audit → 動作 → limit；對照 `man firewalld.richlanguage` | ★★★★ |
| 11 | `--permanent ... --timeout=1800` 回 `INVALID_OPTION` | ★★★★★ `--timeout` **只能用於 runtime** | 拿掉 `--permanent`；要長期規則就別用 timeout | ★★★★ |
| 12 | 埠轉發設好了，客戶端**連線 hang 到 timeout** | 少了 `--add-masquerade`，回程封包來源 IP 不對被丟棄 | `firewall-cmd --permanent --zone=X --add-masquerade --reload`；同時確認 `net.ipv4.ip_forward=1` | ★★★★★ |
| 13 | 大檔案傳一半卡死、小檔案正常 | 擋掉了 ICMP `fragmentation-needed`，打壞 PMTU Discovery | `firewall-cmd --permanent --zone=X --remove-icmp-block=fragmentation-needed --reload` | ★★★★ |
| 14 | 用 `nft` 手動加的規則，`firewall-cmd --reload` 之後消失 | firewalld reload 會重建整個 ruleset | 不要混用。要額外規則就寫成 rich rule，或改用純 nftables 管理（見 [[090-02-03-guide-防火牆-nftables與iptables]]） | ★★★★ |
| 15 | `--runtime-to-permanent` 之後多出奇怪的規則 | 它是**整包快照**，把 `--timeout` 的臨時規則也存進去了 | 存完立刻 `--permanent --list-all-zones` 對一遍，刪掉不該存在的 | ★★★★ |
| 16 | 兩個 zone 都符合，不知道走哪個 | ★★★★ 判斷順序是「來源綁定 → 介面綁定 → default zone」 | `firewall-cmd --get-active-zones` 看歸屬；來源綁定永遠優先 | ★★★★ |
| 17 | 從 RHEL 8 升到 RHEL 9 後，同 zone 兩張網卡之間**突然可以互轉了** | firewalld 1.0 起 intra-zone forwarding 預設開啟 | 不要就 `firewall-cmd --permanent --zone=X --remove-forward --reload` | ★★★ |
| 18 | journal 被防火牆 log 塞爆，看不到別的訊息 | `--set-log-denied=all` 或 rich rule 的 `log` 沒加 `limit` | 改 `unicast`；rich rule 的 log 一律加 `limit value="6/m"` | ★★★ |

### 排查步驟（照順序做，不要跳）★★★★

```bash
# ① 服務有沒有在跑？規則存不存在？
sudo firewall-cmd --state
sudo firewall-cmd --get-active-zones

# ② 這個來源歸哪個 zone？該 zone 開了什麼？
sudo firewall-cmd --zone=<那個zone> --list-all

# ③ runtime 跟 permanent 是不是不一致？
diff <(sudo firewall-cmd --list-all-zones) <(sudo firewall-cmd --permanent --list-all-zones)

# ④ 服務本身有沒有在聽？聽在哪個位址？   ★★★★★ 最常被跳過的一步
sudo ss -tlnp | grep <埠>

# ⑤ 封包真的到得了這台機器嗎？
sudo tcpdump -ni ens192 "tcp port <埠>" -c 20

# ⑥ 底層 nftables 長什麼樣（確認 firewalld 真的產生了規則）
sudo nft list ruleset | grep -A5 'chain filter_IN_public_allow'

# ⑦ firewalld 自己的錯誤訊息
sudo journalctl -u firewalld --since '10 min ago' --no-pager
```

★★★★★ **④ 和 ⑤ 決定了問題到底在不在防火牆。**
`tcpdump` 看得到封包進來、但服務沒回應 → 防火牆擋的；
`tcpdump` 完全看不到封包 → 問題在上游（路由、交換器 ACL、雲端安全群組），
再怎麼調 firewalld 都沒用。

## 安全性注意事項

> [!danger] ★★★★★ 三個絕對不要做的操作
> 1. **不要把 `trusted` zone 綁到對外介面。** `trusted` 的 target 是 `ACCEPT`，
>    綁上去等於防火牆不存在，而且 `--list-all` 看起來還是「有設定」的樣子，非常難察覺。
> 2. **不要在遠端主機上 `firewall-cmd --panic-on`。** 那會切斷所有連線包含你自己，
>    而且無法遠端解除。救援只能靠 console。
> 3. **不要 `systemctl stop firewalld` 來「暫時測試」。** 停掉的瞬間主機完全裸奔，
>    如果測試中途你被別的事打斷，這台機器可能就這樣裸奔一整天。
>    要測就用 `--timeout` 開一條有時效的規則。

> [!warning] ★★★★ zone 設計的四條原則
> 1. **default zone 保持 `public`，而且把它當成「網際網路」看待。** 不要把 default 改成 `trusted` 或 `internal`
>    來「省事」—— 那會讓所有你忘記歸類的來源自動獲得高信任。
> 2. **管理服務（ssh、cockpit、node_exporter、IPMI）一律綁在來源受限的 zone，不要放在 default zone。**
> 3. **一個 zone 只代表一種信任等級。** 不要在 `public` 裡塞十條 rich rule 來模擬分級 ——
>    那就失去用 firewalld 的意義了，也很難稽核。
> 4. **rich rule 用來處理「例外」，不要用來當主要規則。** 主要規則用 zone + service 表達，
>    看 `--list-all` 一眼就懂；rich rule 多了之後可讀性會急速下降。

> [!warning] ★★★★ 防火牆不是唯一一層
> firewalld 只管「連得進來嗎」。以下四件事它管不到，必須另外做：
>
> | 威脅 | firewalld 做得到？ | 該用什麼 |
> | --- | --- | --- |
> | 允許的來源一直猜 ssh 密碼 | ❌ | [[090-02-05-guide-防護-Fail2ban入侵防護]] |
> | 允許的來源打 SQL Injection | ❌ | ModSecurity WAF（[[090-04-04-guide-ModSecurity-日誌分析與監控]]） |
> | 服務本身被入侵後往外連 | ❌（預設不管 outbound） | SELinux（[[090-02-07-guide-防護-SELinux與AppArmor]]）、出向規則 |
> | 弱密碼、沒關的預設帳號 | ❌ | [[090-02-08-guide-防護-系統強化與稽核]] |

> [!tip] ★★★ 稽核與交接必備
> 機關稽核常問「你怎麼證明這台機器的防火牆規則是對的」。答案是：
> ```bash
> firewall-cmd --list-all-zones > /var/log/fw-baseline-$(date +%F).txt
> ```
> 把這份輸出連同「每一條規則為什麼存在」的說明放進交接文件。
> ★★★★ **沒有人記得住原因的規則，三年後沒人敢刪，最後累積成一堆沒人懂的洞。**

## 速查表

### 狀態與查詢 ★★★★

| 指令 | 說明 |
| --- | --- |
| `firewall-cmd --state` | firewalld 有沒有在跑（`running` / `not running`） |
| `firewall-cmd --get-default-zone` | 預設 zone |
| `firewall-cmd --set-default-zone=public` | ★★★ 改預設 zone（**立即且永久，不用 reload**） |
| `firewall-cmd --get-active-zones` | ★★★★★ 真正生效的 zone 與其介面／來源 |
| `firewall-cmd --get-zones` | 所有可用 zone 名稱 |
| `firewall-cmd --list-all` | default zone 的完整設定 |
| `firewall-cmd --zone=X --list-all` | 指定 zone 的完整設定 |
| `firewall-cmd --list-all-zones` | ★★★★ 全部 zone 一次列出（稽核用） |
| `firewall-cmd --get-zone-of-interface=ens192` | 某介面綁在哪個 zone |
| `firewall-cmd --zone=X --query-service=http` | ★★★ 只回 exit code，適合腳本 |
| `firewall-cmd --get-services` | 所有內建 service 名稱 |
| `firewall-cmd --info-service=mysql` | 某 service 涵蓋哪些埠 |

### 規則異動 ★★★★★

| 指令 | 說明 |
| --- | --- |
| `firewall-cmd --permanent --zone=X --add-service=http` | 加服務（**寫檔，未生效**） |
| `firewall-cmd --reload` | ★★★★★ 把 permanent 載入 runtime（**跟上一條配對用**） |
| `firewall-cmd --zone=X --add-service=http` | 加服務（**立即生效，重開就沒**） |
| `firewall-cmd --runtime-to-permanent` | ★★★★ 把 runtime 整包存成 permanent |
| `firewall-cmd --permanent --zone=X --add-port=8080/tcp` | 加埠（範圍用 `30000-30100/udp`） |
| `firewall-cmd --permanent --zone=X --remove-service=http` | 移除服務 |
| `firewall-cmd --zone=X --add-service=ssh --timeout=600` | ★★★★ 有時效的臨時規則（**不能配 `--permanent`**） |
| `firewall-cmd --permanent --zone=X --add-source=10.10.0.0/24` | ★★★★ 綁來源網段（優先於介面） |
| `firewall-cmd --permanent --zone=X --change-interface=ens224` | 綁介面（NM 管的還要改 `nmcli`） |
| `firewall-cmd --permanent --zone=X --set-target=default` | 設 zone target |
| `firewall-cmd --complete-reload` | ★★★ 完整重載（**會斷掉現有連線的 conntrack**，非必要不用） |
| `firewall-cmd --check-config` | 驗證 permanent XML 語法 |

### rich rule 範本 ★★★★

| 需求 | 寫法 |
| --- | --- |
| 只讓某網段連某服務 | `rule family="ipv4" source address="10.10.0.0/24" service name="ssh" accept` |
| 封鎖某 IP | `rule family="ipv4" source address="1.2.3.4/32" drop` |
| 明確拒絕（會回應） | `rule family="ipv4" source address="1.2.3.4/32" reject` |
| 開非標準埠給特定來源 | `rule family="ipv4" source address="10.20.5.20/32" port port="8443" protocol="tcp" accept` |
| 記錄並限制 log 量 | `rule family="ipv4" service name="ssh" log prefix="SSH " level="info" limit value="6/m" accept` |
| 限制連線速率 | `rule family="ipv4" service name="ssh" accept limit value="10/m"` |
| IPv6 | 把 `family="ipv4"` 換成 `family="ipv6"`，位址用 `2001:db8::/64` |

### 檔案路徑 ★★★★

| 路徑 | 內容 |
| --- | --- |
| `/etc/firewalld/firewalld.conf` | 主設定：`DefaultZone=`、`FirewallBackend=`、`LogDenied=` |
| `/etc/firewalld/zones/*.xml` | ★★★★★ **你的** zone 設定（permanent 就存在這裡） |
| `/etc/firewalld/services/*.xml` | ★★★★ **你的** 自訂 service |
| `/etc/firewalld/policies/*.xml` | 你的 policy object |
| `/usr/lib/firewalld/zones/*.xml` | 原廠 zone 範本（**不要改**） |
| `/usr/lib/firewalld/services/*.xml` | 原廠 service 定義（**不要改**） |

### 判斷準則（背這五條）★★★★★

1. **改了沒生效** → 你少了 `--reload`
2. **重開就不見** → 你少了 `--permanent`
3. **規則沒作用** → `--get-active-zones` 看那個 zone 有沒有綁上去
4. **開了還是不通** → `ss -tlnp` 看服務綁在哪個位址
5. **舊連線通、新連線不通** → 這才是規則真正的效果，永遠開新視窗測

## 練習題

> [!question]- 練習 1：從零建一個「只給管理網段」的 zone
> 在測試機上：
> 1. 建立來源綁定：把 `192.168.56.0/24` 綁到 `internal`
> 2. 在 `internal` 裡只留 `ssh`，把出廠的 `mdns`、`samba-client`、`dhcpv6-client` 全部移除
> 3. **先只做 runtime**，用 `--get-active-zones` 與 `--zone=internal --list-all` 驗證
> 4. 確認無誤後 `--runtime-to-permanent`，再 `reboot` 驗證還在
>
> **解答**
> ```bash
> firewall-cmd --zone=internal --add-source=192.168.56.0/24
> for s in mdns samba-client dhcpv6-client; do
>   firewall-cmd --zone=internal --remove-service="$s"
> done
> firewall-cmd --get-active-zones
> firewall-cmd --zone=internal --list-all
> firewall-cmd --runtime-to-permanent
> reboot
> # 重開後
> firewall-cmd --zone=internal --list-all   # services 應只剩 ssh
> ```
> ★★★★ 重點在最後的 `reboot` —— **不重開就無法證明 permanent 真的寫進去了**。

> [!question]- 練習 2：驗證「來源綁定優先於介面綁定」
> 1. `ens192` 綁在 `public`，`public` 只開 `http`
> 2. 把你的測試機來源 IP 綁到 `trusted`
> 3. 從測試機 `nc -zv <目標> 22`，觀察結果
> 4. 把來源從 `trusted` 移除，再測一次
>
> **解答**
> ```bash
> firewall-cmd --zone=trusted --add-source=192.168.56.101/32
> # 從測試機：nc -zv target 22  → Connected（trusted 全開）
> firewall-cmd --zone=trusted --remove-source=192.168.56.101/32
> # 再測：nc -zv -w3 target 22  → timeout（回到 public，沒開 ssh）
> ```
> ★★★★★ 這個實驗直接證明了：**同一張網卡、同一個埠，來源不同結果完全不同**，
> 而且來源綁定會蓋過介面綁定。同時它也示範了為什麼 `trusted` 這麼危險。

> [!question]- 練習 3：自訂 service 並用在 zone 上
> 為一個跑在 `9443/tcp` 的內部管理後台建立名為 `myadmin` 的 service，只開放給 `10.10.0.0/24`。
>
> **解答**
> ```bash
> firewall-cmd --permanent --new-service=myadmin
> firewall-cmd --permanent --service=myadmin --set-short="Internal Admin"
> firewall-cmd --permanent --service=myadmin --add-port=9443/tcp
> firewall-cmd --permanent --zone=internal --add-source=10.10.0.0/24
> firewall-cmd --permanent --zone=internal --add-service=myadmin
> firewall-cmd --reload
> firewall-cmd --info-service=myadmin
> cat /etc/firewalld/services/myadmin.xml
> ```
> ★★★ 注意 `--new-service` **必須**配 `--permanent`（service 定義沒有 runtime 概念），
> 而且建立後一定要 `--reload` 才能在 zone 裡引用它。

> [!question]- 練習 4：用 `--timeout` 做一次安全的高風險變更
> 模擬「把 ssh 從 public 移除」，但確保萬一鎖住自己也能救回來。
>
> **解答**
> ```bash
> # ① 開 5 分鐘保險（只允許你自己的 IP）
> firewall-cmd --zone=public --add-rich-rule='rule family="ipv4" source address="<你的IP>/32" service name="ssh" accept' --timeout=300
> # ② 執行高風險變更（runtime，不落地）
> firewall-cmd --zone=public --remove-service=ssh
> # ③ 開新視窗測試新連線
> ssh -o ConnectTimeout=5 user@target 'echo OK'
> # ④-A 通了 → 落地，然後刪掉保險
> firewall-cmd --runtime-to-permanent
> firewall-cmd --permanent --zone=public --remove-rich-rule='rule family="ipv4" source address="<你的IP>/32" service name="ssh" accept'
> firewall-cmd --reload
> # ④-B 不通 → 什麼都不做，5 分鐘後保險過期，或直接 firewall-cmd --reload 回到 permanent 狀態
> ```
> ★★★★★ 這一題就是本篇的核心方法論：**runtime 試 → 開新視窗驗 → 才落地**。

> [!question]- 練習 5：讀懂 `nft` 底下的東西
> 加一條 `--add-service=http` 之後，在 nftables ruleset 裡找到對應的規則。
>
> **解答**
> ```bash
> firewall-cmd --zone=public --add-service=http
> nft list ruleset | grep -n 'tcp dport'
> # 會看到類似：
> #   tcp dport 80 ct state new,untracked accept
> ```
> ★★★ 用途是**除錯時確認 firewalld 真的產生了規則**。
> 但記住：看歸看，**不要用 `nft` 去改**，下次 reload 就沒了（排錯表第 14 列）。

## 小測驗

Q1. `firewall-cmd --permanent --zone=public --add-service=http` 執行後回 `success`，此時外部能連上 80 埠嗎？為什麼？

Q2. 一個封包同時符合「來源在 `internal` 的 source 清單裡」與「進入的介面綁在 `public`」，firewalld 會用哪個 zone？

Q3. （是非）`trusted` zone 的 target 是 `ACCEPT`，所以在 `trusted` 裡再加 `--add-service=http` 沒有任何額外效果。

Q4. 這行指令會發生什麼？
```bash
sudo firewall-cmd --permanent --zone=public --add-rich-rule='rule family="ipv4" source address="10.10.0.5/32" service name="ssh" accept' --timeout=600
```

Q5. 你在 `internal` zone 加了 `ssh` 與 `9100/tcp` 並 `--reload`，但監控主機還是抓不到 9100。第一個該跑的診斷指令是什麼？

Q6. （選擇）想在遠端主機上「暫時測試沒有防火牆的情況」，下列哪個做法最安全？
　A. `systemctl stop firewalld`
　B. `firewall-cmd --panic-on`
　C. `firewall-cmd --zone=public --set-target=ACCEPT`
　D. `firewall-cmd --zone=public --add-rich-rule='rule family="ipv4" source address="<自己IP>/32" accept' --timeout=300`

Q7. `--runtime-to-permanent` 有一個容易被忽略的副作用，是什麼？

Q8. 你設了 `--add-forward-port=port=80:proto=tcp:toport=8080:toaddr=10.10.0.60`，客戶端連線卻一直 hang 到 timeout。最可能少了哪一步？

Q9. `firewall-cmd --get-active-zones` 的輸出裡沒有 `dmz`，但你在 `dmz` 裡加了五條規則。這五條規則有作用嗎？

Q10. 用 ufw 的 `ufw allow from 10.10.0.0/24 to any port 22`，換成 firewalld 有哪兩種寫法？各自的適用情境是什麼？

> [!question]- 測驗答案
> **Q1.** ★★★★★ **不能。** `--permanent` 只把規則寫進 `/etc/firewalld/zones/public.xml`，
> 沒有載入到 runtime。必須再跑 `firewall-cmd --reload`。
> 這是「改了沒生效」的頭號原因 → 見〈基礎設定〉的「runtime 與 permanent 是兩份獨立的設定」。
>
> **Q2.** ★★★★★ **用 `internal`。** firewalld 的判斷順序是
> **① 來源綁定 → ② 介面綁定 → ③ default zone**，來源綁定優先權最高。
> 這正是「一張網卡、兩套規則」能成立的原理 → 見〈觀念說明〉的「核心差異：zone 是什麼」。
>
> **Q3.** ★★★★ **是（真）。** `trusted` 的 target 是 `ACCEPT`，代表任何沒被明確拒絕的封包都放行，
> 再加 service 只是讓 `--list-all` 好看一點，實際上沒有任何額外限制效果。
> 這也是為什麼 `trusted` 綁到對外介面極度危險 —— 它「看起來有設定」→ 見〈安全性注意事項〉。
>
> **Q4.** ★★★★ **會失敗**，回 `Error: INVALID_OPTION: can't use --timeout with --permanent`。
> `--timeout` 是 runtime 專屬的「規則自動過期」機制，永久規則沒有過期的概念 →
> 見〈進階設定與調校〉的「時效規則」與排錯表第 11 列。
>
> **Q5.** ★★★★★ **`sudo ss -tlnp | grep 9100`** —— 先確認 node_exporter 到底有沒有在聽、
> 綁在 `0.0.0.0` 還是 `127.0.0.1`。防火牆開了但服務綁在 loopback 是最常見的誤判。
> 第二步才是 `firewall-cmd --get-active-zones` 確認監控主機的來源真的歸在 `internal` →
> 見〈常見錯誤與排錯〉的排查步驟第 ④ 項。
>
> **Q6.** ★★★★★ **D。**
> A 會讓主機完全裸奔且沒有自動恢復機制；B 會立刻切斷你自己的連線且無法遠端解除；
> C 改 target 是永久的、而且對所有來源生效；
> 只有 D 是「範圍最小（只有你自己）＋ 自動過期（5 分鐘）」→ 見〈安全性注意事項〉。
>
> **Q7.** ★★★★ 它是**整包快照**，會把你原本只想暫時存在的東西（特別是 `--timeout` 加的臨時規則）
> 一起寫進 permanent。存完必須 `--permanent --list-all-zones` 對一遍並刪掉多餘的 →
> 見〈完整實戰範例〉第 5 步與排錯表第 15 列。
>
> **Q8.** ★★★★★ **少了 `--add-masquerade`。** 沒有 SNAT 的話，後端 10.10.0.60 會把回應直接送給
> 原始客戶端，客戶端收到來源 IP 不符的封包就丟棄，表現就是連線 hang 住。
> 順帶也要確認 `net.ipv4.ip_forward=1` → 見〈進階設定與調校〉的「埠轉發與 masquerade」。
>
> **Q9.** ★★★★★ **完全沒有作用。** 一個 zone 只有在綁了介面或來源、出現在 `--get-active-zones`
> 之後才會被套用。這是新手第一名的錯誤 → 見〈環境準備與安裝〉步驟 0 與排錯表第 3 列。
>
> **Q10.** ★★★★ 兩種寫法：
> 1. **rich rule**：`firewall-cmd --permanent --zone=public --add-rich-rule='rule family="ipv4" source address="10.10.0.0/24" service name="ssh" accept'`
>    —— 適合**單一例外**，規則少的時候一目了然。
> 2. **來源綁 zone**：`firewall-cmd --permanent --zone=internal --add-source=10.10.0.0/24`
>    ＋ `--zone=internal --add-service=ssh`
>    —— 適合**這個網段會有一整組管理服務**（ssh + 監控 + 資料庫…）的情境，可讀性與可稽核性都好很多。
>
> ★★★★★ 實務準則：**一條例外用 rich rule，一組服務用 zone。**
> 在 `public` 裡塞十條 rich rule 就失去用 firewalld 的意義了 → 見〈進階設定與調校〉的對照表。

## 延伸閱讀

- [[090-02-02-guide-防火牆-ufw基礎與實務]] —— 本手冊的主線防火牆，兩篇一起讀才完整
- [[090-02-03-guide-防火牆-nftables與iptables]] —— firewalld 底下真正在跑的東西
- [[090-02-05-guide-防護-Fail2ban入侵防護]] —— 防火牆擋不了「猜密碼」，這篇補上
- [[090-02-01-guide-防護-伺服器初始安全設定]] —— 新機上線的完整順序
- [[090-02-07-guide-防護-SELinux與AppArmor]] —— RHEL 系的另一半防護，跟 firewalld 一起才叫縱深
- [[090-02-08-guide-防護-系統強化與稽核]] —— 稽核時要交出來的東西
- [[020-02-01-07-svc-SSH-安全強化]] —— ssh 換埠時 firewalld 要跟著調整
- [[020-01-17-cmd-Linux-systemd服務管理]] —— `systemctl enable --now` 與服務狀態判讀
- [[020-01-19-guide-Linux-日誌系統]] —— rich rule 的 log 會進 journal，怎麼查
- [[980-01-ref-附錄-Ubuntu與RHEL差異總表]] —— ufw / firewalld 之外的其他差異
- `man firewalld.zone`、`man firewalld.richlanguage`、`man firewall-cmd` —— ★★★★ 遇到語法問題的權威來源
