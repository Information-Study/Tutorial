---
title: "Cisco 管理 IP 與遠端存取"
desc: "SVI 與預設閘道、RSA 金鑰啟用 SSHv2、line vty 與 transport input、enable secret 與 Type 7 的差別、ACL 限制管理來源"
aliases: [interface vlan, ip default-gateway, crypto key generate rsa, line vty, transport input ssh, enable secret, service password-encryption]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-10-cmd-Cisco-IOS-基礎操作]]", "[[040-01-11-guide-Cisco-VLAN與Trunk設定]]"]
updated: 2026-09-02
---

# Cisco 管理 IP 與遠端存取

> [!note] 本手冊以 Juniper JunOS 為主線
> 網路設備章節**以 Juniper JunOS 為主線**，對應篇是 [[040-01-07-guide-Juniper-管理IP與遠端存取]]。
> Cisco 這一篇是**輔助線**，給接手既有 Catalyst 設備的維運人員用，內容深度不打折。
> 遠端存取的通用安全原則（不限平台）見 [[090-02-06-guide-防護-遠端存取安全]]。

> [!abstract] 這篇你會學到
> - ★★★★★ `enable password` ＋ `service password-encryption` 產生的 **Type 7 是可逆編碼**，
>   線上工具三秒還原明文 —— 為什麼機關稽核一定會抓這一項，正確做法是什麼
> - ★★★★★ 遠端啟用 SSH 的**正確順序**：先建帳號、再開 SSH、**最後**才關 telnet。
>   順序錯一步就是把自己鎖在門外
> - ★★★★ L2 交換器用 `ip default-gateway`、L3 交換器用 `ip route`，
>   兩者**互斥**（開了 `ip routing` 之後 `ip default-gateway` 就失效了）
> - ★★★★ `crypto key generate rsa` 的前置條件：**沒設 hostname 與 domain name 就產不出金鑰**
> - ★★★★ `line vty 0 4` 為什麼不夠 —— 多數機型有 `0 15` 共 16 條線，
>   只鎖前五條等於留了 11 個後門
> - ★★★★ 用 `access-class` 把管理介面限制在管理網段，以及它與介面 ACL 的差別
> - ★★★ `no ip http server` / `no ip http secure-server`：關掉那個 CVE 重災區的 Web UI
> - 一份可直接套用的機關管理平面安全基線設定範本

> [!warning] 未實機驗證
> ★★★★★ 本專案**沒有可供驗證的實體 Cisco 設備**。本篇依 Cisco IOS 15.2(7)E
> （Catalyst 2960-X）與 IOS-XE 17.x（Catalyst 9200／9300）的官方命令參考撰寫，
> 輸出為依實際格式重建的**示意輸出**，金鑰指紋、雜湊值等為虛構。
> ★★★★ 密碼雜湊型別（Type 5／8／9）與 `algorithm-type` 選項在不同版本差異很大，
> 導入前請用 `username test secret ?` 與 `enable secret ?` 確認你的版本支援哪些。
> 所有遠端變更請照本篇的 `reload in` 保險做法。

## 前置知識

- [[040-01-10-cmd-Cisco-IOS-基礎操作]] —— 模式階層、`do`、★★★★★ `reload in 5`
- [[040-01-11-guide-Cisco-VLAN與Trunk設定]] —— 管理 VLAN 要先建好、
  trunk 的 allowed list 要含管理 VLAN，否則 SVI 起不來
- [[010-02-06-guide-網概-IP位址與子網路]] —— 網段與遮罩
- [[020-02-01-04-svc-sshd-伺服器端設定]] —— Linux 端的 sshd 觀念，
  ★★★ 兩邊對照看「不把自己鎖在外面」的共通思路
- [[040-01-07-guide-Juniper-管理IP與遠端存取]] —— 主線平台的做法

## 觀念說明

### 交換器的管理 IP 掛在哪裡 ★★★★

L2 交換器**沒有實體的管理埠 IP**（少數新機型有 `GigabitEthernet0/0` 這種
out-of-band 管理埠，但那是例外）。管理 IP 掛在一個叫 **SVI** 的邏輯介面上：

```text
                 ┌────────────── SW-3F-01 ──────────────┐
                 │                                       │
                 │   interface Vlan99                    │  ← SVI（Switch Virtual Interface）
                 │    ip address 10.10.99.31 255.255.255.0│
                 │           ▲                            │
                 │           │ 這個 IP 屬於 VLAN 99        │
                 │           │                            │
                 │   ┌───────┴────────┐                   │
                 │   │  VLAN 99 廣播域 │                   │
                 │   └───────┬────────┘                   │
                 │           │                            │
                 │       Gi1/0/24 trunk（allowed 必須含 99）│
                 └───────────┬────────────────────────────┘
                             ▼
                      SW-DIST-01 ──▶ 10.10.99.254（閘道）
```

★★★★★ **SVI 要 up，必須同時滿足三個條件**：

| 條件 | 檢查方式 | 沒滿足的症狀 |
| --- | --- | --- |
| 該 VLAN 存在於 VLAN 資料庫 | `show vlan brief` 有這個 VLAN 且 `active` | SVI 一直 down |
| ★★★★ 該 VLAN **至少有一個 up 的埠**（access 埠或 trunk 上被 allow） | `show vlan brief` 的 Ports 欄，或 `show interfaces trunk` | SVI down/down |
| SVI 本身沒有 `shutdown` | `show ip interface brief` 不是 `administratively down` | administratively down |

★★★★ 第二個條件最常被漏掉：**你建了 VLAN 99、設了 SVI，
但上行 trunk 的 `allowed vlan` 裡沒有 99**，SVI 就永遠是 down。

### `ip default-gateway` 與 `ip route` 的互斥關係 ★★★★

這是 Cisco 最常被搞混的一組指令：

| 情境 | 用什麼 | 為什麼 |
| --- | --- | --- |
| **純 L2 交換器**（沒開 `ip routing`） | ★★★★ `ip default-gateway 10.10.99.254` | 設備本身不做路由，只需要知道「要出去找誰」 |
| **L3 交換器 / 路由器**（`ip routing` 已開） | ★★★★ `ip route 0.0.0.0 0.0.0.0 10.10.99.254` | 設備有路由表，預設路由是路由表的一筆 |

> [!danger] ★★★★★ 開了 `ip routing` 之後，`ip default-gateway` 就完全失效
> 而且它**還會留在 `running-config` 裡**，看起來一切正常。
> 典型事故：某人為了做 inter-VLAN routing 打了 `ip routing`，
> 交換器的管理連線隨即中斷（因為 `ip default-gateway` 不再作用，
> 而 `ip route` 又還沒設）。
>
> ★★★★ 判斷方法：
>
> ```cisco
> SW-3F-01#show running-config | include ^ip routing
> ```
>
> 有輸出 → 你需要 `ip route 0.0.0.0 0.0.0.0 <閘道>`。
> 沒輸出 → 你需要 `ip default-gateway <閘道>`。

```cisco
!-- L2 交換器（2960-X）：確認沒開 routing
SW-3F-01#show ip route
Default gateway is 10.10.99.254

Host               Gateway           Last Use    Total Uses  Interface
ICMP redirect cache is empty
```

★★★ 這個輸出格式（`Default gateway is ...` 加一張 host 表）就是
「這台沒開 `ip routing`」的證明。開了之後 `show ip route` 會變成完整的路由表格式。

### SSH 與 Telnet：不是「多開一個」而是「取代」 ★★★★★

出廠的 Cisco 設備 **Telnet 是開的、SSH 是關的**。
Telnet 把帳號密碼以**明文**送過網路，同網段任何一台機器抓封包就能拿到管理員密碼。

```text
啟用 SSH 的正確順序（★★★★★ 順序錯就會把自己鎖在外面）：

 ① hostname + ip domain name        ← 沒有這兩個，金鑰產不出來
 ② crypto key generate rsa 2048     ← 產生金鑰（★ 這一步會自動啟用 SSH）
 ③ ip ssh version 2                 ← 強制只用 SSHv2
 ④ username <帳號> privilege 15 secret <密碼>   ← ★★★★★ 先有帳號
 ⑤ enable secret <密碼>
 ⑥ line vty 0 15
      login local                   ← 改用本機帳號驗證
      transport input ssh telnet    ← ★★★★ 暫時兩種都留著
 ⑦ ★★★★★ 開另一條 SSH 連線實測 → 成功登入、能 enable
 ⑧ line vty 0 15
      transport input ssh           ← 確認 SSH 可用之後才關 telnet
 ⑨ reload cancel → write memory
```

> [!danger] ★★★★★ 第 ⑦ 步不能跳過
> 「設完就直接關 telnet」是遠端把自己鎖在外面的第一名原因。
> 常見的失敗點：金鑰模數太小（512 bits）導致 SSHv2 起不來、
> 使用者帳號打錯、`login local` 忘記設、ACL 把自己擋掉。
> **一定要在舊連線還活著的時候，另開一條新連線驗證。**
> 這跟 Linux 改 sshd 的原則完全一樣，見 [[020-02-01-04-svc-sshd-伺服器端設定]]。

### 密碼型別：這一節決定你的稽核會不會被開缺失 ★★★★★

IOS 設定檔裡的密碼會標一個型別數字：

```cisco
enable secret 5 $1$mERr$9cTjUIEqNGurQiFU.ZeCi1
username netadm privilege 15 password 7 070C285F4D06
```

| 型別 | 演算法 | 可逆嗎 | 能用嗎 | 星級 |
| --- | --- | --- | --- | --- |
| **Type 0** | ★★★★★ **完全沒有加密，明文** | — | ★★★★★ **絕對不行** | ★★★★★ |
| **Type 7** | Cisco 私有 Vigenère 編碼 | ★★★★★ **可逆，三秒還原** | ★★★★★ **絕對不行** | ★★★★★ |
| **Type 5** | MD5 加鹽雜湊 | 不可逆 | ★★★ 可接受，但已可暴力破解 | ★★★ |
| **Type 8** | PBKDF2-SHA256 | 不可逆 | ★★★★ 建議 | ★★★★ |
| **Type 9** | scrypt | 不可逆 | ★★★★ **最佳選擇** | ★★★★ |

> [!danger] ★★★★★ `service password-encryption` 是這個手冊裡最大的假安全
> 很多人以為打了這行就「密碼加密了」。**它產生的是 Type 7。**
>
> ```cisco
> SW(config)#service password-encryption
> SW(config)#username test password Cisco123
> SW(config)#do show run | include username test
> username test password 7 08701E1D5D4C53
> ```
>
> 那串 `08701E1D5D4C53` 用網路上隨便一個 Cisco Type 7 decoder
> **不到三秒就還原成 `Cisco123`**。它的唯一用途是防止有人站在你身後看螢幕。
>
> ★★★★★ 正確做法：**永遠用 `secret` 而不是 `password`**。
>
> | 錯誤寫法 | 產生 | 正確寫法 | 產生 |
> | --- | --- | --- | --- |
> | `enable password Cisco123` | Type 0／7 | `enable secret Cisco123` | Type 5／9 |
> | `username x password Cisco123` | Type 0／7 | `username x secret Cisco123` | Type 5／9 |
> | `line vty` → `password Cisco123` | ★★★★ Type 0／7 | 改用 `login local` ＋ `username ... secret` | Type 5／9 |
>
> `service password-encryption` 還是要開（它能保護那些**只能**用 Type 7 的欄位，
> 例如某些 line password 與 TACACS+ key），但**不能當成安全措施**。

★★★ 較新的 IOS-XE 可以明確指定演算法：

```cisco
SW(config)#username netadm privilege 15 algorithm-type scrypt secret Str0ng-P@ssw0rd
SW(config)#enable algorithm-type scrypt secret Str0ng-Enable-P@ss
SW(config)#do show run | include ^username|^enable secret
enable secret 9 $9$Xw3jK1nQ2mLp8u$V0kZ7yTn2eR4sB6cD8fG0hJ2kL4mN6pQ8rS0tU2vW4x
username netadm privilege 15 secret 9 $9$Ab1cD2eF3gH4i5$J6kL7mN8oP9qR0sT1uV2wX3yZ4aB5cD6eF7gH8i
```

★★★ 如果你的版本沒有 `algorithm-type`（會回 `% Invalid input`），
直接用 `enable secret <密碼>` 得到 Type 5 即可 —— 那也遠好過 Type 7。

### `line vty` 的數量陷阱 ★★★★

```cisco
SW-3F-01#show running-config | section line vty
line vty 0 4
 login local
 transport input ssh
line vty 5 15
 login
 transport input all
```

★★★★★ 看出問題了嗎？只有前 5 條（0-4）設好了，**後面 11 條（5-15）是預設值**：
`transport input all`（telnet 也可以）、`login`（用 line password 而非本機帳號）。

★★★★ 攻擊者只要讓前 5 條被佔滿（開 5 個 SSH 連線放著），
第 6 個連線就會落到 vty 5，走的是沒設防的那組設定。

**正確做法：一律用 `line vty 0 15` 一次涵蓋全部。**

```cisco
SW-3F-01(config)#line vty 0 15
SW-3F-01(config-line)#login local
SW-3F-01(config-line)#transport input ssh
SW-3F-01(config-line)#exec-timeout 5 0
SW-3F-01(config-line)#access-class MGMT-IN in
SW-3F-01(config-line)#logging synchronous
```

★★★ 不同機型的 vty 數量不同（常見是 0-4、0-15，某些 IOS-XE 到 0-97）。
確認方法：

```cisco
SW-3F-01(config)#line vty 0 ?
  <1-15>  Last Line number
```

## 環境準備與安裝

### 本篇的環境

| 項目 | 值 |
| --- | --- |
| 設備 | SW-3F-01，Catalyst WS-C2960X-24TS-L，IOS 15.2(7)E3 |
| 管理 VLAN | 99（`MGMT`），已在上一篇建好 |
| 管理 IP | 10.10.99.31/24 |
| 管理閘道 | 10.10.99.254 |
| 管理網段（允許來源） | 10.10.99.0/24 |
| 網管跳板機 | 10.10.99.50 |
| 網域名稱 | `gov.local` |
| Syslog／NTP | 10.10.99.30 |
| 目前連線方式 | ★ Console（安全，改壞了也不會鎖住自己） |

> [!tip] ★★★★★ 第一次設定 SSH 請用 console
> 本篇的所有步驟在 console 上做**沒有任何風險**。
> 如果只能遠端做（例如設備在分處），全程照 `reload in 15` 的保險做法，
> 並且**在確認新的 SSH 連線可用之前，絕對不要 `write memory`**。

### 動工前的檢查

```cisco
SW-3F-01#show vlan brief | include 99
99   MGMT                             active

SW-3F-01#show interfaces trunk | begin Vlans allowed on trunk
Port        Vlans allowed on trunk
Gi1/0/24    20,30,40,99

SW-3F-01#show ip interface brief | include Vlan
Vlan1                  unassigned      YES manual administratively down down
```

★★★★ 三項都要確認：VLAN 99 存在、上行 trunk 允許 99、VLAN 1 已關。
缺第二項的話 SVI 起不來，見上一篇。

```cisco
SW-3F-01#show ip ssh
SSH Disabled - version 1.99
%Please create RSA keys to enable SSH (and of atleast 768 bits for SSH v2).
Authentication timeout: 120 secs; Authentication retries: 3
```

★★★ 這是「SSH 還沒啟用」的標準輸出。訊息中的 `768 bits` 是最低門檻，
**實務上一律用 2048 或更高**。

```cisco
SW-3F-01#show running-config | include ip http|transport input|^username|^enable
enable password cisco
ip http server
ip http secure-server
```

★★★★★ 這三行就是典型的出廠／未強化狀態：明文 enable 密碼、HTTP 與 HTTPS 管理介面全開、
沒有任何本機帳號。

> [!info]- Juniper JunOS 對照
> | 事情 | Cisco IOS | Juniper JunOS |
> | --- | --- | --- |
> | 管理 IP | `interface Vlan99` ＋ `ip address ...` | `set interfaces irb.99 family inet address 10.10.99.31/24`（或 `me0`／`vme`） |
> | 預設閘道（L2） | ★★★★ `ip default-gateway 10.10.99.254` | `set routing-options static route 0.0.0.0/0 next-hop 10.10.99.254` |
> | 預設路由（L3） | `ip route 0.0.0.0 0.0.0.0 10.10.99.254` | 同上（★ JunOS 兩者寫法相同，沒有互斥陷阱） |
> | 產生 SSH 金鑰 | ★★★★ `crypto key generate rsa modulus 2048`（需先設 hostname／domain） | ★ 啟用 `set system services ssh` 時自動產生 |
> | 啟用 SSH | `crypto key generate rsa` ＋ `ip ssh version 2` | `set system services ssh protocol-version v2` |
> | 關閉 telnet | `line vty 0 15` → `transport input ssh` | `delete system services telnet` |
> | 本機帳號 | `username netadm privilege 15 secret <pw>` | `set system login user netadm class super-user authentication plain-text-password` |
> | enable 密碼 | ★★★★ `enable secret <pw>` | ★ JunOS **沒有 enable 概念**，權限由 class 決定 |
> | 密碼雜湊 | Type 5／8／9（★★★★★ 不要用 Type 7） | ★ JunOS 預設 SHA-512，沒有 Type 7 這種東西 |
> | 限制管理來源 | `access-class <ACL> in`（掛在 line vty） | `set system services ssh connection-limit` ＋ firewall filter 掛 `lo0` |
> | 關閉 Web UI | `no ip http server` ＋ `no ip http secure-server` | `delete system services web-management` |
> | 改壞的保險 | `reload in 15` | `commit confirmed 15` |
>
> ★★★★ 最大的體感差異：**JunOS 沒有 Type 7 這種假加密**，
> 也沒有「vty 0-4 設了但 5-15 沒設」這種數量陷阱。
> 詳見 [[040-01-07-guide-Juniper-管理IP與遠端存取]]。

## 基礎設定

### 步驟 1：SVI 與預設閘道

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface Vlan99
SW-3F-01(config-if)#description MGMT-SVI
SW-3F-01(config-if)#ip address 10.10.99.31 255.255.255.0
SW-3F-01(config-if)#no shutdown
SW-3F-01(config-if)#exit
SW-3F-01(config)#ip default-gateway 10.10.99.254
SW-3F-01(config)#end
```

**驗證**：

```cisco
SW-3F-01#show ip interface brief | include Vlan99
Vlan99                 10.10.99.31     YES manual up                    up
```

★★★★ 必須是 `up  up`。若是 `down down`，回頭檢查：

```cisco
SW-3F-01#show vlan brief | include ^99
99   MGMT                             active

SW-3F-01#show interfaces trunk | include ^Gi1/0/24
Gi1/0/24    on               802.1q         trunking      999
```

```cisco
SW-3F-01#ping 10.10.99.254
Type escape sequence to abort.
Sending 5, 100-byte ICMP Echos to 10.10.99.254, timeout is 2 seconds:
!!!!!
Success rate is 100 percent (5/5), round-trip min/avg/max = 1/1/4 ms

SW-3F-01#ping 10.10.99.50
Type escape sequence to abort.
Sending 5, 100-byte ICMP Echos to 10.10.99.50, timeout is 2 seconds:
!!!!!
Success rate is 100 percent (5/5), round-trip min/avg/max = 1/2/4 ms
```

★★★ ping 得到跳板機才代表管理路徑是通的。只 ping 得到閘道還不夠。

### 步驟 2：主機名與網域名稱（金鑰的前置條件）★★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#hostname SW-3F-01
SW-3F-01(config)#ip domain-name gov.local
SW-3F-01(config)#end
```

> [!warning] ★★★ 這個指令有版本差異
> IOS 15.x：`ip domain-name gov.local`
> 部分 IOS-XE 16.x／17.x：`ip domain name gov.local`（**空格，不是連字號**）
> 打錯會回 `% Invalid input detected`。用 `ip domain ?` 確認。

沒設這兩項就產金鑰會被拒絕：

```cisco
SW-3F-01(config)#crypto key generate rsa
% Please define a domain-name first.
```

★★★★ 原因：RSA 金鑰的名稱是 `<hostname>.<domain-name>`，
沒有這兩個資訊就沒有名字可用。

### 步驟 3：產生 RSA 金鑰 ★★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#crypto key generate rsa modulus 2048
The name for the keys will be: SW-3F-01.gov.local

% The key modulus size is 2048 bits
% Generating 2048 bit RSA keys, keys will be non-exportable...
[OK] (elapsed time was 3 seconds)

SW-3F-01(config)#
*Sep  2 15:04:12.331: %SSH-5-ENABLED: SSH 1.99 has been enabled
```

★★★★ 看到 `%SSH-5-ENABLED` 就代表 SSH 服務已經起來了 ——
**產金鑰這個動作本身就會啟用 SSH**，不需要額外的「開啟 SSH」指令。

| 模數 | 評價 | 星級 |
| --- | --- | --- |
| 512 | ★★★★★ SSHv2 不支援，且極不安全 | 禁用 |
| 768 | SSHv2 的最低門檻，仍太弱 | 禁用 |
| 1024 | 舊機型的預設，★★★ 現代標準已不建議 | 不建議 |
| **2048** | ★★★★ **機關環境建議值**，相容性與安全性平衡 | 建議 |
| 4096 | 更安全，但★★★ 舊機型產生要數分鐘、且每次連線 CPU 負擔明顯 | 視需求 |

```cisco
SW-3F-01(config)#end
SW-3F-01#show crypto key mypubkey rsa
% Key pair was generated at: 15:04:09 CST Sep 2 2026
Key name: SW-3F-01.gov.local
Key type: RSA KEYS
 Storage Device: private-config
 Usage: General Purpose Key
 Key is not exportable. Redundancy enabled.
 Key Data:
  30820122 300D0609 2A864886 F70D0101 01050003 82010F00 3082010A 02820101
  ...
```

> [!warning] ★★★★ 重新產生金鑰會讓所有客戶端跳「主機金鑰已變更」警告
> ```cisco
> SW-3F-01(config)#crypto key zeroize rsa
> % All RSA keys will be removed.
> % All router certs issued using these keys will also be removed.
> Do you really want to remove these keys? [yes/no]: yes
> ```
> ★★★★★ `crypto key zeroize rsa` 會**立刻停用 SSH 並中斷所有 SSH 連線**。
> 遠端執行等於自斷退路。要換金鑰請在 console 上做，或先 `reload in 10`。
> 換完之後客戶端要清掉舊的 known_hosts 記錄，
> 見 [[020-02-01-01-cmd-SSH-原理與第一次連線]]。

### 步驟 4：強制 SSHv2 並調整參數

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#ip ssh version 2
SW-3F-01(config)#ip ssh time-out 60
SW-3F-01(config)#ip ssh authentication-retries 3
SW-3F-01(config)#end
SW-3F-01#show ip ssh
SSH Enabled - version 2.0
Authentication methods:publickey,keyboard-interactive,password
Authentication Publickey Algorithms:x509v3-ssh-rsa,ssh-rsa
Hostkey Algorithms:x509v3-ssh-rsa,ssh-rsa
Encryption Algorithms:aes128-ctr,aes192-ctr,aes256-ctr
MAC Algorithms:hmac-sha1,hmac-sha1-96
Authentication timeout: 60 secs; Authentication retries: 3
Minimum expected Diffie Hellman key size : 1024 bits
IOS Keys in SECSH format(ssh-rsa, base64 encoded): NONE
```

★★★★ `SSH Enabled - version 2.0` 才算過關。
如果顯示 `version 1.99` 代表 SSHv1 與 v2 都接受 —— **SSHv1 有已知的協定弱點**，
機關環境必須用 `ip ssh version 2` 強制關掉 v1。

★★★ 上面輸出的 `Encryption Algorithms` 與 `MAC Algorithms` 是這個版本支援的清單。
`hmac-sha1` 在部分稽核基準中已被標為過弱；較新的 IOS-XE 可以用
`ip ssh server algorithm mac hmac-sha2-256` 收斂演算法清單，
舊 IOS 15.x 則沒有這個選項，只能靠升級 IOS 解決。

### 步驟 5：建立本機帳號與 enable 密碼 ★★★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#enable secret Str0ng-Enable-P@ss-2026
SW-3F-01(config)#no enable password
SW-3F-01(config)#username netadm privilege 15 secret N3tAdm1n-P@ss-2026
SW-3F-01(config)#username monitor privilege 1 secret M0n1t0r-P@ss-2026
SW-3F-01(config)#service password-encryption
SW-3F-01(config)#end
```

★★★★★ 三個關鍵細節：

| 行 | 為什麼 |
| --- | --- |
| `enable secret` 而非 `enable password` | ★★★★★ 前者是雜湊，後者是明文／Type 7 |
| ★★★★★ `no enable password` | **兩者可以並存**，而且 `enable password` 會留在設定檔裡以 Type 7 呈現。必須明確刪掉 |
| `privilege 15` vs `privilege 1` | ★★★ 15 是完整管理權（登入即 `#`），1 是唯讀（登入是 `>`，要 `enable` 才能升權） |

**驗證**：

```cisco
SW-3F-01#show running-config | include ^enable|^username
enable secret 5 $1$Kp9x$8vNqL2mR4tY6uI0oP1aS2.
username netadm privilege 15 secret 5 $1$Zq3w$7bVcX1nM5kJ8hG2fD4sA3.
username monitor privilege 1 secret 5 $1$Yr4e$6cWdZ2oN9lK7jH3gF5tB4.
```

★★★★ **確認每一行都是 `secret 5`（或 `secret 9`），沒有任何一行是
`password 7` 或 `password 0`。** 這是稽核最常抓的一項。

### 步驟 6：line vty 與 line console ★★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#line console 0
SW-3F-01(config-line)#login local
SW-3F-01(config-line)#exec-timeout 10 0
SW-3F-01(config-line)#logging synchronous
SW-3F-01(config-line)#exit
SW-3F-01(config)#line vty 0 15
SW-3F-01(config-line)#login local
SW-3F-01(config-line)#transport input ssh telnet
SW-3F-01(config-line)#transport output none
SW-3F-01(config-line)#exec-timeout 5 0
SW-3F-01(config-line)#logging synchronous
SW-3F-01(config-line)#end
```

★★★★ 注意第 8 行 `transport input ssh telnet` —— **這一步刻意保留 telnet**，
等下一步驗證 SSH 真的可用之後才收掉。

| 指令 | 作用 | 星級 |
| --- | --- | --- |
| `login local` | ★★★★ 用 `username`／`secret` 驗證（而非 line password） | ★★★★ |
| `transport input ssh` | ★★★★★ 只接受 SSH 進來 | ★★★★★ |
| `transport output none` | ★★★ 禁止從這台設備往外開 telnet／ssh（防跳板） | ★★★ |
| `exec-timeout 5 0` | ★★★★ 閒置 5 分鐘自動登出（`0 0` 是永不逾時，禁用） | ★★★★ |
| `logging synchronous` | log 不會打斷你打字 | ★★★ |
| `access-class <ACL> in` | ★★★★ 限制可以連進來的來源 IP（步驟 8） | ★★★★ |

> [!danger] ★★★★★ `exec-timeout 0 0` 是稽核缺失也是實質風險
> 它代表 session 永不逾時。管理員忘記登出、離開座位，
> 那條 session 就一直保持在 `#` 權限。
> console 也一樣要設 —— **接在機櫃上的 console 伺服器等於一條永久的後門。**

### 步驟 7：實測 SSH，然後才關 telnet ★★★★★

**保持你現在的 console／telnet 連線不要關**，另開一個終端機：

```bash
$ ssh netadm@10.10.99.31
The authenticity of host '10.10.99.31 (10.10.99.31)' can't be established.
RSA key fingerprint is SHA256:xK3mP9qL2nR7tY4uI8oA1sD6fG0hJ5kZ3cV7bN2mQ4w.
Are you sure you want to continue connecting (yes/no/[fingerprint])? yes
Warning: Permanently added '10.10.99.31' (RSA) to the list of known hosts.
Password:
SW-3F-01#
```

★★★★★ 三件事都要確認：

| 檢查 | 通過條件 |
| --- | --- |
| 能連上並輸入密碼 | 出現 `Password:` 提示 |
| 登入成功 | 出現提示符號 |
| ★★★★ 提示符號是 `#` 不是 `>` | `privilege 15` 生效了 |

★★★ 若是 `>`，代表 `privilege 15` 沒設好，你需要再打 `enable`。
兩種都可以接受，但要知道差別在哪。

```cisco
SW-3F-01#show users
    Line       User       Host(s)              Idle       Location
   0 con 0     netadm     idle                 00:00:12
*  1 vty 0     netadm     idle                 00:00:00   10.10.99.50
```

★★★ `show users` 同時看到 console 與 vty 兩條，代表兩條路都活著。

**確認無誤後，才收掉 telnet**：

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#line vty 0 15
SW-3F-01(config-line)#transport input ssh
SW-3F-01(config-line)#end
SW-3F-01#show running-config | section line vty
line vty 0 15
 exec-timeout 5 0
 logging synchronous
 login local
 transport input ssh
 transport output none
```

★★★★ **確認輸出是 `line vty 0 15` 這一個區塊**，不是分成 `0 4` 與 `5 15` 兩塊。

**驗證 telnet 真的關了**：

```bash
$ telnet 10.10.99.31
Trying 10.10.99.31...
Connected to 10.10.99.31.
Escape character is '^]'.
Connection closed by foreign host.
```

★★★ 連上後立刻被關閉＝正確。若還能看到登入提示，代表設定沒生效
（多半是只改了 `line vty 0 4`）。

### 步驟 8：ACL 限制管理來源 ★★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#ip access-list standard MGMT-IN
SW-3F-01(config-std-nacl)#remark == 允許網管跳板機 ==
SW-3F-01(config-std-nacl)#permit host 10.10.99.50
SW-3F-01(config-std-nacl)#remark == 允許管理網段（含備援管理主機） ==
SW-3F-01(config-std-nacl)#permit 10.10.99.0 0.0.0.255
SW-3F-01(config-std-nacl)#remark == 其餘全部拒絕並記錄 ==
SW-3F-01(config-std-nacl)#deny any log
SW-3F-01(config-std-nacl)#exit
SW-3F-01(config)#line vty 0 15
SW-3F-01(config-line)#access-class MGMT-IN in
SW-3F-01(config-line)#end
```

> [!danger] ★★★★★ 這是本篇最容易把自己鎖在外面的一步
> 打下 `access-class MGMT-IN in` 的瞬間，**任何不在 ACL 裡的來源立刻斷線**。
> 遠端執行前務必：
> 1. ★★★★★ 先 `reload in 10`
> 2. ★★★★ 確認**你自己的來源 IP 真的在 ACL 裡**
>    （不是你以為的 IP —— 用 `show users` 看 Location 欄，那才是設備看到的來源）
> 3. ★★★ 確認經過 NAT／跳板時，設備看到的是**跳板機的 IP**，不是你筆電的 IP

★★★★ **Cisco ACL 有隱含的 `deny any` 結尾**，所以最後那行 `deny any log`
在功能上是多餘的 —— 但**加了才會產生 log**，這對稽核與入侵偵測很重要：

```cisco
SW-3F-01#show logging | include MGMT-IN
*Sep  2 16:11:23.442: %SEC-6-IPACCESSLOGS: list MGMT-IN denied 192.168.5.77 1 packet
```

**驗證**：

```cisco
SW-3F-01#show ip access-lists MGMT-IN
Standard IP access list MGMT-IN
    10 permit 10.10.99.50 (14 matches)
    20 permit 10.10.99.0, wildcard bits 0.0.0.255 (3 matches)
    30 deny   any log
```

★★★ `(14 matches)` 代表這條規則真的被套用到了。全部都是 0 matches
而你人還連著 → `access-class` 沒掛上去。

| 概念 | `access-class`（掛 line vty） | 介面 ACL（`ip access-group`） |
| --- | --- | --- |
| 保護什麼 | ★★★★ **設備自己的管理平面**（vty 連線） | 穿過設備的轉發流量 |
| 掛在哪 | `line vty` 底下 | `interface` 底下 |
| 誤設的後果 | ★★★★★ 你連不進去 | 使用者流量被擋 |
| 機關必做 | ★★★★★ 是 | 視需求 |

### 步驟 9：關閉不需要的服務 ★★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#no ip http server
SW-3F-01(config)#no ip http secure-server
SW-3F-01(config)#no cdp run
SW-3F-01(config)#no service pad
SW-3F-01(config)#no ip source-route
SW-3F-01(config)#no ip bootp server
SW-3F-01(config)#no ip domain-lookup
SW-3F-01(config)#end
```

| 指令 | 關掉什麼 | 為什麼 | 星級 |
| --- | --- | --- | --- |
| `no ip http server` | HTTP 管理介面（TCP 80） | ★★★★ 明文傳輸，且歷年多個 RCE 等級 CVE | ★★★★ |
| `no ip http secure-server` | HTTPS 管理介面（TCP 443） | ★★★★ 同上（加密不代表沒漏洞），CLI 已足夠 | ★★★★ |
| `no cdp run` | 全域關閉 CDP | ★★★ 洩漏型號／版本／管理 IP | ★★★ |
| `no service pad` | X.25 PAD 服務 | ★★ 遠古遺留，完全用不到 | ★★ |
| `no ip source-route` | 來源路由封包 | ★★★ 可被用來繞過路由與 ACL | ★★★ |
| `no ip bootp server` | BOOTP 服務 | ★★ 用不到的攻擊面 | ★★ |
| `no ip domain-lookup` | 打錯字時的 DNS 查詢 | ★★★★ 打錯指令會卡 30 秒 | ★★★★ |

> [!warning] ★★★★ `no cdp run` 要想清楚再打
> CDP 是**排錯與盤點的重要工具**（`show cdp neighbors detail` 一秒告訴你
> 對端是誰、IP 多少、什麼版本），而且 IP 電話依賴 CDP 取得 voice VLAN。
>
> ★★★★ 折衷做法：**保留全域 CDP，只在使用者埠關掉**：
>
> ```cisco
> SW-3F-01(config)#interface range GigabitEthernet1/0/1 - 20
> SW-3F-01(config-if-range)#no cdp enable
> ```
>
> 這樣設備之間仍能互相探索，但攻擊者從使用者埠接進來看不到任何資訊。
> ★★★ 如果現場有 IP 電話，那幾個埠要保留 CDP 或改用 LLDP-MED。

### 步驟 10：登入警告標語 ★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#banner motd ^
Enter TEXT message.  End with the character '^'.
********************************************************************
*  本設備屬 XX 機關所有，僅限授權人員使用。                        *
*  所有存取行為均予記錄，未經授權之存取將依法追究。                *
*  AUTHORIZED ACCESS ONLY. All activity is logged and monitored.   *
********************************************************************
^
SW-3F-01(config)#end
```

★★★★ **標語內容不要寫「Welcome」或任何歡迎字眼**，
也不要寫出設備型號、機關名稱以外的資訊。
歡迎字眼在部分法律見解中可能被解讀為「開放存取」的默示同意。

★★★ `banner motd` 的分隔字元可以是任何未出現在內文的字元，
常用 `^`、`#`、`$`。內文裡出現該字元會提早結束。

## 進階設定與調校

### 只允許金鑰登入（公鑰認證）★★★

較新的 IOS／IOS-XE 支援 SSH 公鑰認證：

```cisco
SW-3F-01(config)#ip ssh pubkey-chain
SW-3F-01(conf-ssh-pubkey)#username netadm
SW-3F-01(conf-ssh-pubkey-user)#key-string
SW-3F-01(conf-ssh-pubkey-data)#AAAAB3NzaC1yc2EAAAADAQABAAABgQDQm3Zv8xK2nP9qL4tR7yU0iO
SW-3F-01(conf-ssh-pubkey-data)#2aS5dF8gH1jK3lM6nB9vC2xZ4wQ7eR0tY5uI8oP1aS3dF6gH9jK
SW-3F-01(conf-ssh-pubkey-data)#exit
SW-3F-01(conf-ssh-pubkey-user)#exit
SW-3F-01(conf-ssh-pubkey)#exit
```

> [!warning] ★★★★ IOS 的公鑰匯入格式跟 OpenSSH 不一樣
> IOS 吃的是**去掉 `ssh-rsa ` 前綴與尾端註解、且每行不超過一定長度**的 base64 內容。
> 直接貼 `~/.ssh/id_rsa.pub` 整行**會失敗**。
> ★★★ 另有 `key-hash ssh-rsa <MD5>` 的寫法（只存指紋）。
> 這一段各版本行為差異大，**建議先在測試機驗證**，
> 且**不要在正式設備上把密碼認證關掉**，除非公鑰登入已經確實可用。
>
> 金鑰產生與管理見 [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]]。

### 登入失敗鎖定 ★★★

```cisco
SW-3F-01(config)#login block-for 300 attempts 5 within 60
SW-3F-01(config)#login quiet-mode access-class MGMT-IN
SW-3F-01(config)#login on-failure log
SW-3F-01(config)#login on-success log
SW-3F-01(config)#login delay 3
```

| 指令 | 作用 |
| --- | --- |
| `login block-for 300 attempts 5 within 60` | ★★★★ 60 秒內失敗 5 次 → 封鎖 300 秒（進入 quiet mode） |
| `login quiet-mode access-class MGMT-IN` | ★★★★★ **quiet mode 期間仍放行 ACL 內的來源** —— 沒有這行，封鎖期間連你自己都進不來 |
| `login on-failure log` / `on-success log` | ★★★★ 產生登入 log，稽核必備 |
| `login delay 3` | 每次登入嘗試之間強制間隔 3 秒 |

```cisco
SW-3F-01#show login
A default login delay of 3 seconds is applied.
Quiet-Mode access list MGMT-IN is applied.
All successful login is logged.
All failed login is logged.

Router enabled to watch for login Attacks.
If more than 5 login failures occur in 60 seconds or less,
logins will be disabled for 300 seconds.

Router presently in Normal-Mode.
Current Watch Window
    Time remaining: 42 seconds.
    Login failures: 0, Login failure limit: 5.
```

> [!danger] ★★★★★ 沒設 `login quiet-mode access-class` 的後果
> 攻擊者只要故意打錯 5 次密碼，就能讓設備進入 quiet mode 300 秒 ——
> **連合法管理員都連不進去**。這是一個現成的 DoS。
> 有了 `quiet-mode access-class`，封鎖只對 ACL 外的來源生效。

### 集中式帳號：TACACS+ 與 AAA ★★★

機關有數十台設備時，本機帳號的管理成本會失控（人員異動要一台一台改）。
標準做法是接 TACACS+（Cisco ISE、tac_plus）或 RADIUS：

```cisco
SW-3F-01(config)#aaa new-model
SW-3F-01(config)#tacacs server TAC-01
SW-3F-01(config-server-tacacs)#address ipv4 10.10.99.40
SW-3F-01(config-server-tacacs)#key Str0ng-TACACS-Key
SW-3F-01(config-server-tacacs)#exit
SW-3F-01(config)#aaa group server tacacs+ TACGRP
SW-3F-01(config-sg-tacacs+)#server name TAC-01
SW-3F-01(config-sg-tacacs+)#exit
SW-3F-01(config)#aaa authentication login default group TACGRP local
SW-3F-01(config)#aaa authentication enable default group TACGRP enable
SW-3F-01(config)#aaa authorization exec default group TACGRP local
SW-3F-01(config)#aaa accounting commands 15 default start-stop group TACGRP
SW-3F-01(config)#end
```

> [!danger] ★★★★★ `aaa new-model` 是一個會立刻改變登入行為的指令
> 打下去的瞬間，**所有 line 的認證方式都改由 AAA 決定**。
> 如果 TACACS+ 伺服器不通、key 打錯、或方法清單沒設 fallback，
> **你會立刻被鎖在外面**（包含 console）。
>
> ★★★★★ 三道保險，一個都不能少：
> 1. **每個 `aaa authentication` 都要有 `local` 當最後的 fallback**
>    （`group TACGRP local` —— TACACS+ 不通時退回本機帳號）
> 2. **本機帳號必須已經存在且測試過**（`username netadm ... secret ...`）
> 3. **一律在 console 上做，或先 `reload in 15`**
>
> ★★★★ `aaa accounting commands 15` 會把每一條管理員下的指令送到 TACACS+，
> 這是機關稽核「誰在什麼時候改了什麼」的標準做法。

★★★ AAA 的完整規劃超出本篇範圍。單台或少數幾台設備的環境，
**本機帳號 ＋ 嚴格的 ACL ＋ 集中 syslog** 已經足夠，不必為了導入而導入。

### SNMP：要用就用 v3 ★★★★

```cisco
!-- ★★★★★ 絕對不要這樣做（SNMPv2c community 等於明文密碼）
SW-3F-01(config)#snmp-server community public RO
SW-3F-01(config)#snmp-server community private RW

!-- ★★★★ 正確做法：SNMPv3，認證 + 加密，且限制來源
SW-3F-01(config)#snmp-server group NMS-GRP v3 priv read NMS-VIEW access MGMT-IN
SW-3F-01(config)#snmp-server view NMS-VIEW iso included
SW-3F-01(config)#snmp-server user nmsuser NMS-GRP v3 auth sha Auth-P@ss-2026 priv aes 128 Priv-P@ss-2026
SW-3F-01(config)#snmp-server host 10.10.99.30 version 3 priv nmsuser
SW-3F-01(config)#snmp-server enable traps
```

★★★★★ 如果環境裡的網管系統只支援 v2c，**至少要**：
使用非預設的 community 字串、設成唯讀（`RO`）、
用 ACL 限制來源（`snmp-server community <字串> RO MGMT-IN`），
並把這件事列入待改善事項。
★★★★ `public` / `private` 這兩個預設 community 是掃描工具的第一發子彈。

### 集中 log 與 NTP ★★★★

```cisco
SW-3F-01(config)#logging host 10.10.99.30
SW-3F-01(config)#logging trap informational
SW-3F-01(config)#logging source-interface Vlan99
SW-3F-01(config)#logging buffered 65536 informational
SW-3F-01(config)#archive
SW-3F-01(config-archive)#log config
SW-3F-01(config-archive-log-cfg)#logging enable
SW-3F-01(config-archive-log-cfg)#notify syslog contenttype plaintext
SW-3F-01(config-archive-log-cfg)#hidekeys
SW-3F-01(config-archive-log-cfg)#end
```

★★★★★ `archive` → `log config` → `logging enable` 這三行的價值極高：
**它會把每一條設定變更指令送到 syslog**，包含是誰、從哪裡、改了什麼。

```cisco
SW-3F-01#show archive log config all
 idx   sess           user@line      Logged command
    1     1        netadm@vty0       |interface GigabitEthernet1/0/8
    2     1        netadm@vty0       | description TEMP-TEST
    3     2        netadm@vty0       |line vty 0 15
    4     2        netadm@vty0       | transport input ssh
```

★★★★ `hidekeys` 確保密碼與金鑰不會被明文寫進 log。**一定要加。**

NTP（沒有正確時間，上面所有 log 都是廢紙）：

```cisco
SW-3F-01(config)#clock timezone CST 8
SW-3F-01(config)#ntp server 10.10.99.30
SW-3F-01(config)#ntp source Vlan99
SW-3F-01(config)#service timestamps log datetime msec localtime show-timezone
SW-3F-01(config)#service timestamps debug datetime msec localtime show-timezone
```

★★★ log 集中收容與保存見 [[100-01-02-guide-日誌-日誌集中與輪替]]。

## 完整實戰範例

**情境**：接手一台從未強化過的 Catalyst 2960-X（分處的接入層交換器）。
現況是 telnet 開著、`enable password cisco`、沒有本機帳號、HTTP 管理介面全開。
**你人在總部，只能遠端 telnet 進去**（分處沒有可以派的人）。
目標：完成安全基線，且全程不能中斷使用者服務。

### 前置環境

| 項目 | 值 |
| --- | --- |
| 設備 | SW-BR-05，10.10.99.75，Catalyst 2960-X，IOS 15.2(7)E3 |
| 你的來源 | 跳板機 10.10.99.50 |
| 現有連線 | ★★★★ telnet（明文，但這是唯一的路） |
| 管理 VLAN | 99，SVI 已設好且可達 |
| 網域名稱 | `gov.local` |
| 允許管理來源 | 10.10.99.0/24 |
| 維護視窗 | 無，不可中斷使用者流量 |

★★★★ 好消息：本篇的所有變更都只動**管理平面**，
不會影響使用者的轉發流量。就算你把自己鎖在外面，使用者也不會斷網。
壞消息：你會需要請分處同仁接 console，那可能要等一天。

### 步驟 0：備份與上保險 ★★★★★

```cisco
SW-BR-05#terminal length 0
SW-BR-05#show running-config
Building configuration...

Current configuration : 3874 bytes
...
（整份複製，存成 SW-BR-05-before-20260902.cfg）
```

```cisco
SW-BR-05#copy running-config tftp://10.10.99.20/SW-BR-05-before-20260902.cfg
Address or name of remote host [10.10.99.20]?
Destination filename [SW-BR-05-before-20260902.cfg]?
!!
3874 bytes copied in 1.104 secs (3509 bytes/sec)
```

```cisco
SW-BR-05#reload in 20
Reload scheduled in 20 minutes by netadm on vty0 (10.10.99.50)
Reload reason: Reload Command
Proceed with reload? [confirm]
SW-BR-05#show reload
Reload scheduled in 19 minutes and 52 seconds by netadm on vty0 (10.10.99.50)
```

★★★★★ **從現在到最後一步，絕對不能打 `write memory`。**

### 步驟 1：確認現況

```cisco
SW-BR-05#show running-config | include ^enable|^username|ip http|transport input|^line
enable password cisco
ip http server
ip http secure-server
line con 0
line vty 0 4
line vty 5 15

SW-BR-05#show ip ssh
SSH Disabled - version 1.99
%Please create RSA keys to enable SSH (and of atleast 768 bits for SSH v2).

SW-BR-05#show users
    Line       User       Host(s)              Idle       Location
*  1 vty 0                idle                 00:00:00   10.10.99.50
```

★★★★ `show users` 的 `Location` 欄告訴你**設備看到的來源 IP 是 10.10.99.50**。
這個值就是等下 ACL 一定要放行的 IP —— 不要憑印象。

### 步驟 2：主機名、網域、金鑰

```cisco
SW-BR-05#configure terminal
SW-BR-05(config)#hostname SW-BR-05
SW-BR-05(config)#ip domain-name gov.local
SW-BR-05(config)#crypto key generate rsa modulus 2048
The name for the keys will be: SW-BR-05.gov.local

% The key modulus size is 2048 bits
% Generating 2048 bit RSA keys, keys will be non-exportable...
[OK] (elapsed time was 4 seconds)

SW-BR-05(config)#
*Sep  2 16:32:08.114: %SSH-5-ENABLED: SSH 1.99 has been enabled
SW-BR-05(config)#ip ssh version 2
SW-BR-05(config)#ip ssh time-out 60
SW-BR-05(config)#ip ssh authentication-retries 3
SW-BR-05(config)#end
```

**驗證**：

```cisco
SW-BR-05#show ip ssh
SSH Enabled - version 2.0
Authentication timeout: 60 secs; Authentication retries: 3
```

★★★ 必須是 `version 2.0`。

### 步驟 3：帳號與 enable secret

```cisco
SW-BR-05#configure terminal
SW-BR-05(config)#enable secret Br05-Enable-P@ss-2026
SW-BR-05(config)#no enable password
SW-BR-05(config)#username netadm privilege 15 secret Br05-N3tAdm1n-2026
SW-BR-05(config)#username monitor privilege 1 secret Br05-M0n1t0r-2026
SW-BR-05(config)#service password-encryption
SW-BR-05(config)#end
```

**驗證**：

```cisco
SW-BR-05#show running-config | include ^enable|^username
enable secret 5 $1$Vb7n$3kL9mN2pQ5rS8tU1vW4xY.
username netadm privilege 15 secret 5 $1$Wc8o$4lM0nO3qR6sT9uV2wX5yZ.
username monitor privilege 1 secret 5 $1$Xd9p$5mN1oP4rS7tU0vW3xY6zA.
```

★★★★★ 三行都是 `secret 5`，`enable password` 已消失 → 過關。

### 步驟 4：line 設定（★ 先保留 telnet）

```cisco
SW-BR-05#configure terminal
SW-BR-05(config)#line console 0
SW-BR-05(config-line)#login local
SW-BR-05(config-line)#exec-timeout 10 0
SW-BR-05(config-line)#logging synchronous
SW-BR-05(config-line)#exit
SW-BR-05(config)#line vty 0 15
SW-BR-05(config-line)#login local
SW-BR-05(config-line)#transport input ssh telnet
SW-BR-05(config-line)#transport output none
SW-BR-05(config-line)#exec-timeout 5 0
SW-BR-05(config-line)#logging synchronous
SW-BR-05(config-line)#end
```

★★★★★ 注意：你現在這條 telnet session **還活著**（IOS 不會踢掉既有連線），
但**新的 telnet 連線現在需要 `username`／`secret` 才能登入了**。
這是好事 —— 代表 `login local` 生效了。

### 步驟 5：★★★★★ 實測 SSH

**不要關掉現在這條 telnet。** 另開一個終端機：

```bash
$ ssh netadm@10.10.99.75
The authenticity of host '10.10.99.75 (10.10.99.75)' can't be established.
RSA key fingerprint is SHA256:mR4tY7uI0oP3aS6dF9gH2jK5lZ8xC1vB4nM7qW0eR3t.
Are you sure you want to continue connecting (yes/no/[fingerprint])? yes
Warning: Permanently added '10.10.99.75' (RSA) to the list of known hosts.
Password:
SW-BR-05#
```

```cisco
SW-BR-05#show users
    Line       User       Host(s)              Idle       Location
   1 vty 0     netadm     idle                 00:03:41   10.10.99.50
*  2 vty 1     netadm     idle                 00:00:00   10.10.99.50
```

★★★★★ 兩條都在、SSH 那條是 `#` 提示符號 → **現在才可以關 telnet**。

### 步驟 6：關 telnet 與不需要的服務

```cisco
SW-BR-05#configure terminal
SW-BR-05(config)#line vty 0 15
SW-BR-05(config-line)#transport input ssh
SW-BR-05(config-line)#exit
SW-BR-05(config)#no ip http server
SW-BR-05(config)#no ip http secure-server
SW-BR-05(config)#no ip domain-lookup
SW-BR-05(config)#no service pad
SW-BR-05(config)#no ip source-route
SW-BR-05(config)#no ip bootp server
SW-BR-05(config)#end
```

★★★ 打完 `transport input ssh` 的瞬間，你那條 telnet session **會被切斷**。
這是預期行為 —— 你已經有 SSH 那條了。

**驗證**（在 SSH session 裡）：

```cisco
SW-BR-05#show running-config | section line vty
line vty 0 15
 exec-timeout 5 0
 logging synchronous
 login local
 transport input ssh
 transport output none

SW-BR-05#show running-config | include ip http
（沒有輸出 → HTTP／HTTPS 都關了）
```

```bash
$ telnet 10.10.99.75
Trying 10.10.99.75...
Connected to 10.10.99.75.
Escape character is '^]'.
Connection closed by foreign host.
```

### 步驟 7：ACL 與登入保護 ★★★★★

```cisco
SW-BR-05#configure terminal
SW-BR-05(config)#ip access-list standard MGMT-IN
SW-BR-05(config-std-nacl)#remark == 網管跳板機 ==
SW-BR-05(config-std-nacl)#permit host 10.10.99.50
SW-BR-05(config-std-nacl)#remark == 管理網段 ==
SW-BR-05(config-std-nacl)#permit 10.10.99.0 0.0.0.255
SW-BR-05(config-std-nacl)#deny any log
SW-BR-05(config-std-nacl)#exit
SW-BR-05(config)#do show ip access-lists MGMT-IN
Standard IP access list MGMT-IN
    10 permit 10.10.99.50
    20 permit 10.10.99.0, wildcard bits 0.0.0.255
    30 deny   any log
```

★★★★★ **掛上去之前，先確認 `show users` 的 Location（10.10.99.50）在清單裡。**
確認了才打下一行：

```cisco
SW-BR-05(config)#line vty 0 15
SW-BR-05(config-line)#access-class MGMT-IN in
SW-BR-05(config-line)#exit
SW-BR-05(config)#login block-for 300 attempts 5 within 60
SW-BR-05(config)#login quiet-mode access-class MGMT-IN
SW-BR-05(config)#login on-failure log
SW-BR-05(config)#login on-success log
SW-BR-05(config)#end
```

★★★★★ **立刻另開一條 SSH 驗證**（不要關現有的）：

```bash
$ ssh netadm@10.10.99.75
Password:
SW-BR-05#
```

連得上 → ACL 沒把自己擋掉。

```cisco
SW-BR-05#show ip access-lists MGMT-IN
Standard IP access list MGMT-IN
    10 permit 10.10.99.50 (3 matches)
    20 permit 10.10.99.0, wildcard bits 0.0.0.255
    30 deny   any log
```

★★★ `(3 matches)` 證明規則真的在作用。

### 步驟 8：log、NTP、標語

```cisco
SW-BR-05#configure terminal
SW-BR-05(config)#clock timezone CST 8
SW-BR-05(config)#ntp server 10.10.99.30
SW-BR-05(config)#ntp source Vlan99
SW-BR-05(config)#service timestamps log datetime msec localtime show-timezone
SW-BR-05(config)#service timestamps debug datetime msec localtime show-timezone
SW-BR-05(config)#logging buffered 65536 informational
SW-BR-05(config)#logging host 10.10.99.30
SW-BR-05(config)#logging trap informational
SW-BR-05(config)#logging source-interface Vlan99
SW-BR-05(config)#archive
SW-BR-05(config-archive)#log config
SW-BR-05(config-archive-log-cfg)#logging enable
SW-BR-05(config-archive-log-cfg)#notify syslog contenttype plaintext
SW-BR-05(config-archive-log-cfg)#hidekeys
SW-BR-05(config-archive-log-cfg)#exit
SW-BR-05(config-archive)#exit
SW-BR-05(config)#banner motd ^
Enter TEXT message.  End with the character '^'.
********************************************************************
*  本設備屬 XX 機關所有，僅限授權人員使用。                        *
*  所有存取行為均予記錄，未經授權之存取將依法追究。                *
*  AUTHORIZED ACCESS ONLY. All activity is logged and monitored.   *
********************************************************************
^
SW-BR-05(config)#end
```

**驗證**：

```cisco
SW-BR-05#show clock
16:58:22.443 CST Tue Sep 2 2026
SW-BR-05#show ntp status
Clock is synchronized, stratum 3, reference is 10.10.99.30
SW-BR-05#show logging | include Trap logging
    Trap logging: level informational, 87 message lines logged
        Logging to 10.10.99.30  (udp port 514, audit disabled, ...)
```

★★★ 到 syslog 主機上確認真的收到這台設備的訊息，才算通過。

### 步驟 9：解除保險並存檔 ★★★★★

**再一次確認所有管理路徑都通**：

```cisco
SW-BR-05#show ip ssh | include SSH Enabled
SSH Enabled - version 2.0
SW-BR-05#show users
    Line       User       Host(s)              Idle       Location
   2 vty 1     netadm     idle                 00:08:12   10.10.99.50
*  3 vty 2     netadm     idle                 00:00:00   10.10.99.50
```

**然後才解除保險**：

```cisco
SW-BR-05#reload cancel
SW-BR-05#
*Sep  2 17:01:44.221: %SYS-5-SCHEDULED_RELOAD_CANCELLED: Scheduled reload cancelled at
17:01:44 CST Tue Sep 2 2026
SW-BR-05#show reload
No reload is scheduled.
SW-BR-05#write memory
Building configuration...
[OK]
```

```cisco
SW-BR-05#show archive config differences system:running-config nvram:startup-config
!Contextual Config Diffs:
!No changes were found
```

```cisco
SW-BR-05#copy running-config tftp://10.10.99.20/SW-BR-05-after-20260902.cfg
!!
4612 bytes copied in 1.221 secs (3777 bytes/sec)
```

### 驗收檢查表 ★★★★

| # | 檢查項 | 指令 | 通過條件 |
| --- | --- | --- | --- |
| 1 | SVI 可達 | `show ip interface brief \| include Vlan99` | `up  up` |
| 2 | 閘道可達 | `ping <閘道>` | 100 percent |
| 3 | SSH 版本 | `show ip ssh` | `SSH Enabled - version 2.0` |
| 4 | 金鑰長度 | `show crypto key mypubkey rsa` | 2048 bits 以上 |
| 5 | ★★★★★ 無明文密碼 | `show run \| include password 7\|password 0` | **無輸出** |
| 6 | ★★★★★ enable 用 secret | `show run \| include ^enable` | 只有 `enable secret 5`（或 9） |
| 7 | ★★★★ vty 全涵蓋 | `show run \| section line vty` | 只有一個 `line vty 0 15` 區塊 |
| 8 | telnet 已關 | `telnet <IP>` | `Connection closed by foreign host.` |
| 9 | Web UI 已關 | `show run \| include ip http` | 無輸出 |
| 10 | ACL 已掛 | `show ip access-lists MGMT-IN` | 有 matches 計數 |
| 11 | 逾時已設 | `show run \| include exec-timeout` | 沒有 `0 0` |
| 12 | 登入保護 | `show login` | `Router enabled to watch for login Attacks.` |
| 13 | 時間正確 | `show ntp status` | `Clock is synchronized` |
| 14 | log 送出 | syslog 主機 | 收得到這台的訊息 |
| 15 | 設定變更稽核 | `show archive log config all` | 有記錄 |
| 16 | 已存檔 | `show archive config differences ...` | `No changes were found` |
| 17 | 排程已解除 | `show reload` | `No reload is scheduled.` |
| 18 | 備份完成 | 備份主機 | before／after 兩份都在 |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| `% Please define a domain-name first.` | ★★★★ 產金鑰前必須先設 hostname 與 domain name | `hostname SW-XX` ＋ `ip domain-name gov.local`（IOS-XE 部分版本是 `ip domain name`），再產金鑰 |
| SVI 一直是 `down down` | ★★★★ 該 VLAN 沒有任何 up 的埠，或上行 trunk 的 allowed list 沒包含它 | `show vlan brief` 確認 VLAN active；`show interfaces trunk` 確認 allowed 含管理 VLAN |
| SVI 是 `administratively down` | 有人下過 `shutdown` | `interface Vlan99` → `no shutdown` |
| SVI up 但 ping 不到閘道 | ★★★★ `ip default-gateway` 沒設，或設備開了 `ip routing` 導致它失效 | `show run \| include ^ip routing` 判斷；L2 用 `ip default-gateway`，L3 用 `ip route 0.0.0.0 0.0.0.0` |
| 打了 `ip routing` 之後管理連線立刻中斷 | ★★★★★ `ip default-gateway` 在 `ip routing` 開啟後完全失效 | 接 console 補上 `ip route 0.0.0.0 0.0.0.0 <閘道>`；遠端做這件事前務必 `reload in` |
| `show ip ssh` 顯示 `SSH Disabled` | 還沒產生 RSA 金鑰 | `crypto key generate rsa modulus 2048` |
| `show ip ssh` 顯示 `version 1.99` | ★★★★ 同時接受 SSHv1 與 v2 | `ip ssh version 2` 強制只用 v2 |
| SSH 客戶端報 `no matching key exchange method found` 或 `no matching cipher` | ★★★★ 舊 IOS 只支援已被現代 OpenSSH 停用的演算法 | 短期：客戶端加 `-o KexAlgorithms=+diffie-hellman-group14-sha1`；★★★★ 長期：升級 IOS，見 [[040-01-14-svc-Cisco-設定備份與韌體升級]] |
| SSH 連得上但登入一直失敗 | `login local` 沒設（走的是 line password），或帳號打錯 | `show run \| section line vty` 確認有 `login local`；`show run \| include ^username` 確認帳號存在 |
| SSH 登入後是 `>` 不是 `#` | ★★★ 帳號沒有 `privilege 15` | `username netadm privilege 15 secret ...`；或登入後手動 `enable` |
| 關了 telnet 之後完全連不進去 | ★★★★★ SSH 沒有先驗證就關 telnet | 若有 `reload in` 保險就等重開；否則接 console。**永遠先驗證再關舊路徑** |
| 打了 `access-class` 之後 SSH 立刻斷線 | ★★★★★ 自己的來源 IP 不在 ACL 裡（常見於經過 NAT／跳板） | `show users` 的 Location 欄才是設備看到的來源；等 `reload in` 生效或接 console |
| ACL 掛上了但 `show ip access-lists` 全部 0 matches | ★★★ `access-class` 沒掛到 line vty 上 | `show run \| section line vty` 確認有 `access-class MGMT-IN in` |
| 前 5 條 vty 設好了，但攻擊者仍能 telnet 進來 | ★★★★ 只設了 `line vty 0 4`，`5 15` 是預設值 | 一律用 `line vty 0 15`；`show run \| section line vty` 確認只有一個區塊 |
| `show run` 裡看到 `password 7 08701E1D5D4C53` | ★★★★★ 用了 `password` 而非 `secret`，Type 7 可逆 | 改用 `enable secret` / `username ... secret`，並 `no enable password` 刪掉舊的 |
| 攻擊者連續打錯密碼後，連管理員都進不去 | ★★★★★ `login block-for` 沒搭配 `login quiet-mode access-class` | 補上 `login quiet-mode access-class MGMT-IN` |
| 打了 `aaa new-model` 之後被鎖在外面 | ★★★★★ TACACS+ 不通且方法清單沒有 `local` fallback | 接 console；方法清單一律寫成 `group TACGRP local` |
| `crypto key zeroize rsa` 之後所有 SSH 斷線 | ★★★★★ 這個指令會立刻停用 SSH | 只能接 console 重新產生金鑰。遠端操作前先 `reload in` |
| SSH 客戶端警告 `REMOTE HOST IDENTIFICATION HAS CHANGED!` | ★★★ 設備重新產生過金鑰（或設備被換過） | 確認是計畫內的變更後，清掉客戶端的 known_hosts 該筆記錄 |
| log 時間全是 `*Mar 1 00:xx` | ★★★★ 沒有 NTP 也沒設 clock | 設 `clock timezone` ＋ `ntp server`；見 [[020-01-28-cmd-Linux-時間同步NTP與chrony]] |
| syslog 主機收不到訊息 | `logging host` 沒設，或 `logging trap` 等級太高，或 ACL 擋住 UDP 514 | `show logging` 看 `Trap logging` 那行；確認來源介面與路由可達 |

## 安全性注意事項

> [!danger] ★★★★★ 管理平面比使用者平面更值得保護
> 一台交換器的管理權限 ＝ 這台設備下面所有 VLAN 的流量都可能被鏡像、竄改或中斷。
> 使用者網段被入侵是一個事件；**管理網段被入侵是整個網路淪陷**。

| 項目 | 風險 | 做法 | 星級 |
| --- | --- | --- | --- |
| 使用 `enable password` 或 `password 7` | ★★★★★ 可逆編碼，等同明文 | 一律 `enable secret` / `username ... secret`，並 `no enable password` | ★★★★★ |
| Telnet 開著 | ★★★★★ 帳密明文過網路 | `transport input ssh` | ★★★★★ |
| SSHv1 未關閉 | ★★★★ 協定層弱點 | `ip ssh version 2` | ★★★★ |
| RSA 金鑰 1024 bits 以下 | ★★★★ 現代標準已不接受 | `crypto key generate rsa modulus 2048` 以上 | ★★★★ |
| 管理平面沒有來源限制 | ★★★★★ 全網任何主機都能嘗試登入 | `access-class MGMT-IN in` 掛 line vty | ★★★★★ |
| 只設 `line vty 0 4` | ★★★★ 5-15 是預設值，等於後門 | 一律 `line vty 0 15` | ★★★★ |
| `exec-timeout 0 0` | ★★★★ session 永不逾時 | vty `5 0`、console `10 0` | ★★★★ |
| HTTP／HTTPS 管理介面開著 | ★★★★ 歷年多個高風險 CVE | `no ip http server` ＋ `no ip http secure-server` | ★★★★ |
| 管理 VLAN 與使用者 VLAN 相同 | ★★★★★ 使用者可直接打到管理介面 | 專屬管理 VLAN，且不在使用者可達的路徑上 | ★★★★★ |
| SNMPv2c 用預設 community | ★★★★★ `public`/`private` 是掃描工具第一發子彈 | 改用 SNMPv3 認證加密；不得已時至少改字串 ＋ 唯讀 ＋ ACL | ★★★★★ |
| 沒有登入失敗記錄 | ★★★★ 暴力破解無從察覺 | `login on-failure log` ＋ `login on-success log` ＋ 集中 syslog | ★★★★ |
| 沒有設定變更稽核 | ★★★★ 出事時查不到是誰改的 | `archive` → `log config` → `logging enable` ＋ `hidekeys` | ★★★★ |
| 沒有登入標語 | ★★★ 部分法遵要求 | `banner motd`，內容不得有歡迎字眼 | ★★★ |
| 設定檔用 TFTP 傳輸／存放無管制 | ★★★★ 設定檔含密碼雜湊、SNMP 字串、ACL 全貌 | 改用 SCP；備份區限制存取；見 [[040-01-14-svc-Cisco-設定備份與韌體升級]] |
| CDP 開在使用者埠 | ★★★★ 洩漏型號、版本、管理 IP | 使用者埠 `no cdp enable`（保留設備間的 CDP） | ★★★★ |

## 速查表

| 指令 / 設定項 | 說明 | 範例 |
| --- | --- | --- |
| `interface Vlan99` | ★★★★ 進入 SVI 設定 | `SW(config)#interface Vlan99` |
| `ip address <ip> <mask>` | 設管理 IP | `... ip address 10.10.99.31 255.255.255.0` |
| `ip default-gateway <ip>` | ★★★★ L2 交換器的預設閘道 | `SW(config)#ip default-gateway 10.10.99.254` |
| `ip route 0.0.0.0 0.0.0.0 <ip>` | ★★★★ L3 設備的預設路由（與上者互斥） | `SW(config)#ip route 0.0.0.0 0.0.0.0 10.10.99.254` |
| `show ip route` | 判斷是 L2 還是 L3 模式 ★★★ | `SW#show ip route` |
| `hostname <名稱>` | ★★★★ 產金鑰的前置條件之一 | `SW(config)#hostname SW-3F-01` |
| `ip domain-name <網域>` | ★★★★ 前置條件之二（IOS-XE 可能是 `ip domain name`） | `SW(config)#ip domain-name gov.local` |
| `crypto key generate rsa modulus 2048` | ★★★★ 產生金鑰（★ 同時啟用 SSH） | `SW(config)#crypto key generate rsa modulus 2048` |
| `crypto key zeroize rsa` | ★★★★★ 刪除金鑰並停用 SSH（會斷線） | `SW(config)#crypto key zeroize rsa` |
| `ip ssh version 2` | ★★★★ 強制只用 SSHv2 | `SW(config)#ip ssh version 2` |
| `ip ssh time-out 60` | 認證逾時秒數 ★★★ | `SW(config)#ip ssh time-out 60` |
| `ip ssh authentication-retries 3` | 認證重試次數 ★★★ | `SW(config)#ip ssh authentication-retries 3` |
| `show ip ssh` | ★★★★ 確認 SSH 狀態與版本 | `SW#show ip ssh` |
| `show crypto key mypubkey rsa` | 看金鑰名稱與產生時間 ★★★ | `SW#show crypto key mypubkey rsa` |
| `enable secret <密碼>` | ★★★★★ 雜湊的特權密碼 | `SW(config)#enable secret Str0ng-P@ss` |
| `no enable password` | ★★★★★ 刪掉舊的明文／Type 7 密碼 | `SW(config)#no enable password` |
| `username <帳號> privilege 15 secret <密碼>` | ★★★★★ 本機管理帳號 | `SW(config)#username netadm privilege 15 secret P@ss` |
| `enable algorithm-type scrypt secret <密碼>` | ★★★ Type 9（版本支援才有） | `SW(config)#enable algorithm-type scrypt secret P@ss` |
| `service password-encryption` | ★★★ 只是 Type 7，**不能當安全措施** | `SW(config)#service password-encryption` |
| `line vty 0 15` | ★★★★ 一次涵蓋全部 vty（不要只設 0 4） | `SW(config)#line vty 0 15` |
| `login local` | ★★★★ 用本機帳號驗證 | `SW(config-line)#login local` |
| `transport input ssh` | ★★★★★ 只接受 SSH | `SW(config-line)#transport input ssh` |
| `transport output none` | ★★★ 禁止從本設備往外連（防跳板） | `SW(config-line)#transport output none` |
| `exec-timeout 5 0` | ★★★★ 閒置 5 分逾時（`0 0` 禁用） | `SW(config-line)#exec-timeout 5 0` |
| `access-class <ACL> in` | ★★★★★ 限制管理來源 IP | `SW(config-line)#access-class MGMT-IN in` |
| `ip access-list standard MGMT-IN` | 建立管理來源 ACL ★★★★ | `SW(config)#ip access-list standard MGMT-IN` |
| `permit host <ip>` / `permit <net> <wildcard>` | ACL 放行 ★★★★ | `permit 10.10.99.0 0.0.0.255` |
| `deny any log` | ★★★★ 產生阻擋 log（隱含 deny 不產 log） | `SW(config-std-nacl)#deny any log` |
| `show ip access-lists <名稱>` | ★★★★ 看規則與 matches 計數 | `SW#show ip access-lists MGMT-IN` |
| `show users` | ★★★★ 誰連著，以及**設備看到的來源 IP** | `SW#show users` |
| `login block-for 300 attempts 5 within 60` | ★★★★ 暴力破解防護 | `SW(config)#login block-for 300 attempts 5 within 60` |
| `login quiet-mode access-class MGMT-IN` | ★★★★★ 封鎖期間仍放行管理網段 | `SW(config)#login quiet-mode access-class MGMT-IN` |
| `show login` | 看登入保護狀態 ★★★ | `SW#show login` |
| `no ip http server` / `no ip http secure-server` | ★★★★ 關 Web 管理介面 | `SW(config)#no ip http server` |
| `no cdp enable`（介面下） | ★★★★ 使用者埠關 CDP | `SW(config-if)#no cdp enable` |
| `banner motd ^ ... ^` | ★★★ 登入警告標語 | `SW(config)#banner motd ^` |
| `archive` → `log config` → `logging enable` | ★★★★ 設定變更稽核 | `SW(config-archive-log-cfg)#logging enable` |
| `hidekeys` | ★★★★ 稽核 log 不含密碼 | `SW(config-archive-log-cfg)#hidekeys` |
| `show archive log config all` | ★★★★ 誰改了什麼 | `SW#show archive log config all` |
| `logging host <ip>` / `logging source-interface Vlan99` | ★★★★ 集中 log | `SW(config)#logging host 10.10.99.30` |
| `ntp server <ip>` / `clock timezone CST 8` | ★★★★ 時間同步 | `SW(config)#ntp server 10.10.99.30` |
| `reload in 15` / `reload cancel` | ★★★★★ 遠端變更保命符 | `SW#reload in 15` |

## 練習題

> [!question]- 練習 1：找出設定檔裡所有的不安全密碼
> 拿一份實際的 Cisco 設定檔（或本篇的範例），用一行指令找出所有
> Type 0 與 Type 7 的密碼欄位。列出你會怎麼逐一修正。
>
> **參考解答**
>
> ```cisco
> SW#show running-config | include password 7|password 0|secret 0
> enable password 7 08701E1D5D4C53
> username backup password 7 070C285F4D06
> line vty 5 15
>  password 7 060506324F41
> ```
>
> ★★★★★ 三處都要改：
>
> ```cisco
> SW(config)#no enable password
> SW(config)#enable secret Str0ng-Enable-P@ss
> SW(config)#no username backup
> SW(config)#username backup privilege 1 secret Str0ng-Backup-P@ss
> SW(config)#line vty 0 15
> SW(config-line)#no password
> SW(config-line)#login local
> ```
>
> 驗證：`show run | include password 7|password 0` 應該**完全沒有輸出**。
> ★★★ 這一行就是稽核人員會跑的那一行。

> [!question]- 練習 2：從零啟用 SSH
> 在一台測試交換器上（或模擬器）從完全未設定的狀態啟用 SSHv2，
> 記錄每一步的輸出，並找出「如果跳過某一步會發生什麼」。
>
> **參考解答**
>
> ```cisco
> Switch(config)#crypto key generate rsa
> % Please define a domain-name first.          ← ★★★★ 跳過 domain-name 的後果
>
> Switch(config)#hostname SW-TEST
> SW-TEST(config)#ip domain-name test.local
> SW-TEST(config)#crypto key generate rsa modulus 2048
> The name for the keys will be: SW-TEST.test.local
> % Generating 2048 bit RSA keys, keys will be non-exportable...
> [OK] (elapsed time was 3 seconds)
> *Sep  2 ...: %SSH-5-ENABLED: SSH 1.99 has been enabled
>
> SW-TEST(config)#ip ssh version 2
> SW-TEST(config)#username test privilege 15 secret Test-P@ss
> SW-TEST(config)#line vty 0 15
> SW-TEST(config-line)#login local
> SW-TEST(config-line)#transport input ssh
> SW-TEST(config-line)#end
> SW-TEST#show ip ssh
> SSH Enabled - version 2.0
> ```
>
> **跳過各步驟的後果**：
>
> | 跳過 | 後果 |
> | --- | --- |
> | `hostname` / `ip domain-name` | ★★★★ 金鑰產不出來 |
> | `ip ssh version 2` | ★★★★ 停在 1.99，SSHv1 也接受 |
> | `username ... secret` | ★★★★★ SSH 起來了但沒帳號可登入 |
> | `login local` | ★★★★ 走 line password，而 line password 沒設 → 拒絕登入 |

> [!question]- 練習 3：ACL 鎖住自己的模擬
> 在測試機上刻意設一個**不包含你自己來源 IP** 的 `access-class`，
> 觀察會發生什麼。然後說明在正式環境要怎麼避免這個結果。
>
> **參考解答**
>
> ```cisco
> SW-TEST#show users
>     Line       User       Host(s)              Idle       Location
> *  1 vty 0     test       idle                 00:00:00   10.10.99.50
>
> SW-TEST#configure terminal
> SW-TEST(config)#ip access-list standard WRONG-ACL
> SW-TEST(config-std-nacl)#permit host 192.168.1.1
> SW-TEST(config-std-nacl)#exit
> SW-TEST(config)#line vty 0 15
> SW-TEST(config-line)#access-class WRONG-ACL in
>                                       ← ★★★★★ 按下 Enter 後 session 立刻斷
> ```
>
> **避免方式**（三道，缺一不可）：
> 1. ★★★★★ 動手前 `reload in 10`
> 2. ★★★★ 用 `show users` 的 **Location 欄**確認設備看到的來源 IP，
>    不要憑印象（經過跳板／NAT 時會不一樣）
> 3. ★★★ 掛 ACL **之前**先 `do show ip access-lists <名稱>` 目視核對一遍

> [!question]- 練習 4：判斷該用 `ip default-gateway` 還是 `ip route`
> 給你三台設備的 `show running-config | include ^ip routing` 輸出，
> 分別判斷該用哪個指令，並寫出完整指令。
>
> 甲：（無輸出）
> 乙：`ip routing`
> 丙：`no ip routing`
>
> **參考解答**
>
> | 設備 | 判斷 | 指令 |
> | --- | --- | --- |
> | 甲 | ★★★★ 沒開 routing（2960 這類 L2 機型預設就沒有這行） | `ip default-gateway 10.10.99.254` |
> | 乙 | ★★★★ 已開 routing | `ip route 0.0.0.0 0.0.0.0 10.10.99.254` |
> | 丙 | 明確關閉 routing（3560／9300 這類 L3 機型的預設或人為設定） | `ip default-gateway 10.10.99.254` |
>
> ★★★★★ 陷阱在乙：如果乙上面**同時**留著 `ip default-gateway`，
> 它會出現在設定檔裡但完全不作用，容易誤導排錯。
> 打了 `ip route` 之後應該把 `no ip default-gateway` 一併清掉。

> [!question]- 練習 5：設計機關的管理平面基線
> 為你的機關寫一份「所有 Cisco 交換器上線前必套用」的設定範本，
> 至少涵蓋密碼、SSH、vty、ACL、log、時間六個面向，並附上驗收指令。
>
> **參考解答**
>
> ```cisco
> ! ===== 1. 身分與密碼 =====
> hostname SW-XX-NN
> ip domain-name gov.local
> enable secret <機關統一強密碼>
> no enable password
> username netadm privilege 15 secret <強密碼>
> username monitor privilege 1 secret <強密碼>
> service password-encryption
> !
> ! ===== 2. SSH =====
> crypto key generate rsa modulus 2048
> ip ssh version 2
> ip ssh time-out 60
> ip ssh authentication-retries 3
> !
> ! ===== 3. 管理來源 ACL =====
> ip access-list standard MGMT-IN
>  permit 10.10.99.0 0.0.0.255
>  deny any log
> !
> ! ===== 4. line =====
> line console 0
>  login local
>  exec-timeout 10 0
>  logging synchronous
> line vty 0 15
>  login local
>  transport input ssh
>  transport output none
>  exec-timeout 5 0
>  access-class MGMT-IN in
>  logging synchronous
> !
> ! ===== 5. 登入保護與稽核 =====
> login block-for 300 attempts 5 within 60
> login quiet-mode access-class MGMT-IN
> login on-failure log
> login on-success log
> archive
>  log config
>   logging enable
>   notify syslog contenttype plaintext
>   hidekeys
> !
> ! ===== 6. 時間與 log =====
> clock timezone CST 8
> ntp server 10.10.99.30
> ntp source Vlan99
> service timestamps log datetime msec localtime show-timezone
> service timestamps debug datetime msec localtime show-timezone
> logging buffered 65536 informational
> logging host 10.10.99.30
> logging trap informational
> logging source-interface Vlan99
> !
> ! ===== 7. 關閉不需要的服務 =====
> no ip http server
> no ip http secure-server
> no ip domain-lookup
> no service pad
> no ip source-route
> no ip bootp server
> ```
>
> **驗收指令**（一次跑完）：
>
> ```cisco
> show ip ssh
> show run | include password 7|password 0
> show run | section line vty
> show ip access-lists MGMT-IN
> show login
> show ntp status
> show run | include ip http
> show archive log config all
> ```
>
> ★★★★ 這份範本應該存進 `_設定檔範例/` 並納入版本控管，
> 見 [[040-01-18-guide-網路設備-網路設備盤點與文件化]]。

## 小測驗

Q1. （選擇）以下哪一個組合真正保護了設定檔裡的密碼？
(A) `enable password Cisco123` ＋ `service password-encryption`
(B) `enable secret Cisco123`
(C) `enable password 7 08701E1D5D4C53`
(D) A 和 C 都可以

Q2. （是非）`line vty 0 4` 底下設好 `transport input ssh` 之後，
這台設備就完全不接受 telnet 了。

Q3. 這行指令會發生什麼事？
`SW-BR-05(config-line)#access-class MGMT-IN in`
執行前你必須先確認什麼？用哪個指令確認？

Q4. `crypto key generate rsa` 回 `% Please define a domain-name first.`。
原因是什麼？RSA 金鑰的名稱是怎麼決定的？

Q5. （簡答）為什麼「先關 telnet 再測試 SSH」是錯的順序？
正確順序是什麼？

Q6. 一台 L2 交換器的 SVI 是 `up/up`，也 ping 得到同網段的主機，
但 ping 不到不同網段的網管系統。最可能的原因是什麼？

Q7. （是非）在一台已經打了 `ip routing` 的 L3 交換器上，
`ip default-gateway 10.10.99.254` 仍然有效。

Q8. 你設了 `login block-for 300 attempts 5 within 60` 之後，
某天發現自己也連不進去。原因與解法是什麼？

Q9. `show ip ssh` 顯示 `SSH Enabled - version 1.99`。
這是什麼意思？為什麼機關環境不能接受？

Q10. 打了 `aaa new-model` 之後，你的 console 登入也失敗了。
最可能的原因是什麼？設定 AAA 時哪一個關鍵字可以避免這個結果？

> [!question]- 測驗答案
> **Q1.** ★★★★★ **(B)**。`enable secret` 產生的是**不可逆的雜湊**（Type 5／9）。
> (A) 與 (C) 都是 **Type 7 —— 可逆的 Cisco 私有編碼**，線上工具三秒還原明文。
> `service password-encryption` 只是把明文變成 Type 7，**不是加密**。
> 見「觀念說明 → 密碼型別」。
>
> **Q2.** ★★★★ **否。** 多數 Catalyst 機型有 **16 條 vty（0-15）**。
> 只設 `line vty 0 4` 的話，`5 15` 仍是預設的 `transport input all`，
> 攻擊者只要讓前 5 條被佔滿，第 6 個連線就會走到沒設防的那組。
> 一律用 `line vty 0 15`。
> 見「觀念說明 → `line vty` 的數量陷阱」。
>
> **Q3.** ★★★★★ 立刻把管理連線限制在 `MGMT-IN` ACL 允許的來源，
> **任何不在清單裡的來源（可能包含你自己）在按下 Enter 的瞬間斷線**。
> 執行前必須確認**設備看到的你的來源 IP** 在 ACL 裡 ——
> 用 `show users` 看 `Location` 欄（★★★★ 不是你以為的 IP，
> 經過 NAT 或跳板時設備看到的是跳板機的 IP）。
> 並且遠端執行前一定要 `reload in 10`。
> 見「基礎設定 → 步驟 8」。
>
> **Q4.** ★★★★ RSA 金鑰的名稱是 `<hostname>.<domain-name>`，
> 沒有 domain name 就組不出名字，IOS 因此拒絕產生。
> 解法：先 `hostname SW-XX` 與 `ip domain-name gov.local`
> （部分 IOS-XE 版本是 `ip domain name`，空格），再產金鑰。
> 見「基礎設定 → 步驟 2、3」。
>
> **Q5.** ★★★★★ 因為關掉 telnet 的那一刻，如果 SSH 因為任何理由不能用
> （金鑰模數太小、帳號打錯、`login local` 沒設、ACL 擋住、
> 客戶端演算法不相容），**你就失去了所有遠端管理路徑**，
> 只能到現場接 console。
> 正確順序：① 設好 SSH 與帳號 → ② `transport input ssh telnet`（兩者並存）
> → ③ **在舊連線還活著時另開一條 SSH 實測登入成功**
> → ④ 才改成 `transport input ssh`。
> 見「觀念說明 → SSH 與 Telnet」與「完整實戰範例 → 步驟 5、6」。
>
> **Q6.** ★★★★ 最可能是**沒設 `ip default-gateway`**（或設錯）。
> 同網段能通代表 SVI 與 L2 路徑正常；跨網段不通代表設備不知道要把封包丟給誰。
> 檢查：`show ip route` 看有沒有 `Default gateway is ...`；
> 並用 `show run | include ^ip routing` 確認該用 `ip default-gateway`
> 還是 `ip route 0.0.0.0 0.0.0.0`。
> 見「觀念說明 → `ip default-gateway` 與 `ip route`」。
>
> **Q7.** ★★★★★ **否。** 一旦開啟 `ip routing`，`ip default-gateway` **完全失效**，
> 但它**還會留在設定檔裡**，看起來一切正常，這是排錯時最容易被誤導的地方。
> L3 模式下必須改用 `ip route 0.0.0.0 0.0.0.0 <閘道>`，
> 並把舊的 `ip default-gateway` 用 `no` 清掉。
> 見「觀念說明 → `ip default-gateway` 與 `ip route`」。
>
> **Q8.** ★★★★★ 因為沒有搭配 `login quiet-mode access-class MGMT-IN`。
> 只要有人（可能是攻擊者，也可能是打錯密碼的同事）在 60 秒內失敗 5 次，
> 設備就進入 quiet mode 300 秒，**拒絕所有登入嘗試，包括合法管理員** ——
> 這等於一個現成的 DoS。
> 解法：加上 `login quiet-mode access-class MGMT-IN`，
> 讓封鎖只對 ACL 之外的來源生效。
> 見「進階設定與調校 → 登入失敗鎖定」。
>
> **Q9.** ★★★★ `1.99` 是 SSH 協定的相容性標示，代表這台設備
> **同時接受 SSHv1 與 SSHv2**。SSHv1 有已知的協定層弱點
> （完整性檢查可被繞過），機關資安基準通常明文禁止。
> 解法：`ip ssh version 2`，之後 `show ip ssh` 應顯示 `version 2.0`。
> 見「基礎設定 → 步驟 4」。
>
> **Q10.** ★★★★★ `aaa new-model` 一打下去，**所有 line 的認證方式立刻改由 AAA 決定**。
> 如果 `aaa authentication login default` 指向的 TACACS+／RADIUS 伺服器不通、
> key 打錯，而方法清單又沒有 `local` 作為 fallback，
> 就連 console 都會被拒絕。
> 關鍵字是 **`local`**：一律寫成
> `aaa authentication login default group TACGRP local`，
> 並確保本機帳號已經存在且測試過。
> 另外務必在 console 上做這個變更，或先 `reload in 15`。
> 見「進階設定與調校 → 集中式帳號」。

## 延伸閱讀

- [[040-01-13-guide-Cisco-埠設定與安全]] —— 管理平面顧好了，接著是使用者埠
- [[040-01-14-svc-Cisco-設定備份與韌體升級]] —— SCP 備份、`archive`、IOS 升級與回退
- [[040-01-11-guide-Cisco-VLAN與Trunk設定]] —— 管理 VLAN 與 trunk allowed list 的前置條件
- [[040-01-07-guide-Juniper-管理IP與遠端存取]] —— 主線平台的做法
- [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]] —— 兩邊指令一頁式對照
- [[090-02-06-guide-防護-遠端存取安全]] —— 不限平台的遠端存取安全原則
- [[020-02-01-04-svc-sshd-伺服器端設定]] —— Linux sshd 的「不鎖門 SOP」，思路完全共通
- [[020-02-01-02-cmd-SSH-金鑰認證與ssh-agent]] —— 金鑰產生與管理
- [[100-01-02-guide-日誌-日誌集中與輪替]] —— 設備 log 送到哪裡、保存多久
- [[040-01-18-guide-網路設備-網路設備盤點與文件化]] —— 設定範本的版本控管
