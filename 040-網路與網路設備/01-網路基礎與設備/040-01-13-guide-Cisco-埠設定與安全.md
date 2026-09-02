---
title: "Cisco 埠設定與安全"
desc: "speed/duplex 與 late collision、port-security 三種違規模式與 sticky、portfast＋bpduguard、未用埠處理與錯誤計數判讀"
aliases: [port-security, duplex mismatch, late collision, spanning-tree portfast, bpduguard, err-disabled, sticky mac]
tags: [群組/網路與設備, 網路/設備, 主題/網路]
category: 網路基礎與設備
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[040-01-10-cmd-Cisco-IOS-基礎操作]]", "[[040-01-11-guide-Cisco-VLAN與Trunk設定]]"]
updated: 2026-09-02
---

# Cisco 埠設定與安全

> [!note] 本手冊以 Juniper JunOS 為主線
> 網路設備章節**以 Juniper JunOS 為主線**，對應篇是 [[040-01-08-guide-Juniper-埠設定與安全]]。
> Cisco 這一篇是**輔助線**，給接手既有 Catalyst 設備的維運人員用，內容深度不打折。

> [!abstract] 這篇你會學到
> - ★★★★★ **雙工不一致（duplex mismatch）是機關現場最難查的效能問題**：
>   線是通的、ping 也通、但檔案傳輸慢到不能用。怎麼從 `late collision`
>   這個計數器一眼認出來，以及為什麼「兩邊都寫死」和「兩邊都自動」才是對的
> - ★★★★ `port-security` 的三種違規模式（`shutdown` / `restrict` / `protect`）
>   差在哪、機關該選哪一種，以及 `sticky` MAC **不 `write memory` 就會消失**
> - ★★★★ `portfast` ＋ `bpduguard` 為什麼一定要成對出現，
>   以及使用者私接小型交換器造成廣播風暴的完整處理流程
> - ★★★★ `err-disabled` 的六種常見成因與**自動恢復**（`errdisable recovery`）的設定
> - ★★★ 未用埠的**兩層處理**：`shutdown` ＋ 丟進黑洞 VLAN，為什麼兩件都要做
> - ★★★ `show interfaces counters errors` 每一欄的意義：
>   `Align-Err` 指向線材、`FCS-Err` 指向干擾、`Runts` 指向雙工
> - ★★★ `description` 命名規範：為什麼「這個埠接什麼」是最有價值的一行設定
> - 一份接入層交換器的完整埠安全設定範本與 30 列速查表

> [!warning] 未實機驗證
> ★★★★★ 本專案**沒有可供驗證的實體 Cisco 設備**。本篇依 Cisco IOS 15.2(7)E
> （Catalyst 2960-X）與 IOS-XE 17.x（Catalyst 9200／9300）的官方命令參考撰寫，
> 輸出為依實際格式重建的**示意輸出**，MAC、計數值為虛構。
> ★★★★ `errdisable recovery` 的可用 cause 清單、`storm-control` 的參數格式、
> `port-security` 在 trunk／voice VLAN 上的行為在不同機型差異明顯，
> 導入前請用 `?` 確認你的版本支援哪些選項，並在測試環境驗證。
> 批次套用到多個埠之前，**先對一個埠試**。

## 前置知識

- [[040-01-10-cmd-Cisco-IOS-基礎操作]] —— `interface range`、`show interfaces status`、
  ★★★★★ `reload in 5`
- [[040-01-11-guide-Cisco-VLAN與Trunk設定]] —— access 埠、黑洞 VLAN、DTP 的關閉
- [[010-02-04-guide-網概-線材與實體層]] —— 雙絞線、等級、長度限制
- [[010-02-05-guide-網概-MAC位址與交換器]] —— CAM table 與 MAC 學習
- [[040-01-16-guide-網路設備-鏈路聚合與STP]] —— STP 的埠狀態與收斂
- [[040-01-08-guide-Juniper-埠設定與安全]] —— 主線平台的做法

## 觀念說明

### 自動協商：預設就是對的，人工介入才會出事 ★★★★★

乙太網路的自動協商（auto-negotiation）會讓兩端交換能力清單，
談出雙方都支援的最高速率與雙工模式。**它幾乎總是對的。**

問題出在人工介入的三種情形：

```text
情形 A（★ 正確）：兩端都 auto
   本端 auto ◀──協商──▶ 對端 auto
   結果：1000/full  ✔ 正常

情形 B（★ 正確）：兩端都寫死且一致
   本端 100/full  ────────  對端 100/full
   結果：100/full  ✔ 正常（但沒有必要這樣做）

情形 C（★★★★★ 災難）：一端寫死、一端 auto
   本端 100/full  ────────  對端 auto
   對端聽不到協商訊號 ─▶ 退回 parallel detection
                      ─▶ 只能偵測到「速率」，偵測不到「雙工」
                      ─▶ ★★★★★ 對端自己決定用 half duplex
   結果：本端 100/full ／ 對端 100/half   ✘ 雙工不一致
```

> [!danger] ★★★★★ 雙工不一致的症狀，比斷線更難查
> **它不會斷線**。ping 通、網頁開得起來、`show interfaces status` 兩端看起來都 `connected`。
> 但只要開始傳大量資料：
>
> | 症狀 | 使用者說法 |
> | --- | --- |
> | 吞吐量掉到理論值的 1～5% | 「複製檔案要跑一整天」 |
> | 大檔案傳輸中斷 | 「檔案傳到一半就斷了」 |
> | 視訊會議卡頓 | 「網路很不穩」 |
> | ping 小封包正常、大封包掉 | 「明明 ping 得到啊」 |
>
> ★★★★★ **半雙工那一端會出現 `late collision` 計數持續上升**，
> 這是雙工不一致最明確的指紋（下一節詳述）。

### `late collision` 是唯一的鐵證 ★★★★★

| 計數器 | 正常的半雙工網路 | 雙工不一致 |
| --- | --- | --- |
| `collisions`（一般碰撞） | ★ **正常會有**（CSMA/CD 本來就會碰撞） | 也會有 |
| `late collisions` | ★★★★★ **應該是 0** | ★★★★★ **持續上升** |

★★★★ 原理：正常碰撞發生在訊框的前 64 bytes 內（碰撞窗口內），
發送端會偵測到並重傳。**late collision 是「已經送出 64 bytes 之後才發現碰撞」**，
這時訊框已經送不回來了，**直接丟棄且不重傳**，只能靠上層 TCP 逾時重送 ——
所以效能會掉到不能用的程度。

在正確設定的網路上，late collision 的成因只有兩個：

| 成因 | 說明 | 星級 |
| --- | --- | --- |
| ★★★★★ **雙工不一致** | 全雙工那端隨時發送，半雙工那端收到一半正在發送 → late collision | ★★★★★ |
| ★★★ **線路超長** | 超過標準的 100m，訊號來回時間超過碰撞窗口 | ★★★ |

```cisco
SW-3F-01#show interfaces GigabitEthernet1/0/5 | include duplex|collision|error
  Full-duplex, 100Mb/s, media type is 10/100/1000BaseTX
     0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored
     0 output errors, 0 collisions, 0 interface resets
```

★★★ 上面是健康的。下面是有問題的（假設是半雙工那端）：

```cisco
SW-3F-01#show interfaces GigabitEthernet1/0/9 | include duplex|collision|error|runts
  Half-duplex, 100Mb/s, media type is 10/100/1000BaseTX
     4213 input errors, 3891 CRC, 322 frame, 0 overrun, 0 ignored
     8104 runts, 0 giants, 0 throttles
     1247 output errors, 15332 collisions, 3 interface resets
     8891 late collision, 0 deferred
```

★★★★★ `8891 late collision` ＝ **雙工不一致，去查對端**。

> [!tip] ★★★★ 1000BASE-T 幾乎不可能人工寫死
> IEEE 802.3ab（1000BASE-T）**要求必須透過自動協商才能建立 full duplex 連線**。
> 在多數 Catalyst 上，把 gigabit 埠設成 `speed 1000` ＋ `duplex full` 會被拒絕，
> 或是設定了但實際上仍在協商。
>
> ★★★★★ 所以現代環境的正確答案是：**兩端都留 auto，不要碰。**
> 只有面對「不支援自動協商的老舊設備」（某些工控機、老印表機、
> 老舊的媒體轉換器）才需要兩端一起寫死，而且要寫死就**兩端都寫死**。

### `show interfaces status` 的速率欄位怎麼讀 ★★★

```cisco
SW-3F-01#show interfaces status
Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   USER-3F-01         connected    30         a-full a-1000 10/100/1000BaseTX
Gi1/0/9   PRINTER-3F-01      connected    30           full    100 10/100/1000BaseTX
Gi1/0/10  OLD-PLC-01         connected    30           half    100 10/100/1000BaseTX
```

| 顯示 | 意義 | 星級 |
| --- | --- | --- |
| `a-full` / `a-1000` | ★ 有 `a-` 前綴 ＝ **自動協商得到的結果** | 正常 |
| `full` / `100` | ★★★★ 沒有前綴 ＝ **人工寫死** | 要確認對端也寫死了 |
| `half` | ★★★★★ 半雙工 ＝ 幾乎一定有問題（除非真的接老設備） | 立刻查 |
| `auto` / `auto` | 埠是 down 的（還沒協商） | 正常（未接線） |

★★★★ **一台正常的接入層交換器，`show interfaces status` 上不應該有任何 `half`。**
這是巡檢時的一秒鐘檢查項。

### `err-disabled`：交換器保護了自己，也切斷了使用者 ★★★★

當交換器偵測到某些危險狀況，會把該埠強制關閉並標記為 `err-disabled`。

```cisco
SW-3F-01#show interfaces status err-disabled
Port      Name               Status       Reason               Err-disabled Vlans
Gi1/0/5   USER-3F-05         err-disabled psecure-violation
Gi1/0/12  USER-3F-12         err-disabled bpduguard
```

| Reason | 成因 | 處理 | 星級 |
| --- | --- | --- | --- |
| `psecure-violation` | ★★★★ port-security 偵測到未授權 MAC | 查是誰接了什麼機器 | ★★★★ |
| `bpduguard` | ★★★★ 該埠收到 BPDU（有人接了交換器／集線器） | 拔掉私接設備 | ★★★★ |
| `link-flap` | ★★★ 短時間內 up/down 太多次 | 換線、換 SFP、檢查對端 | ★★★ |
| `udld` | ★★★ 單向連線（光纖一芯壞掉） | 檢查光纖與模組 | ★★★ |
| `storm-control` | ★★★ 廣播／群播流量超過門檻 | 找出風暴來源 | ★★★ |
| `dtp-flap` | ★★ DTP 協商反覆變動 | 兩端明確設定模式 ＋ `nonegotiate` | ★★ |
| `loopback` | ★★★ 偵測到自己的封包繞回來 | 檢查配線（同一台機器兩個埠互接） | ★★★ |

★★★★★ **恢復的正確流程**：

```text
① 先查原因 ─▶ show interfaces status err-disabled
② ★★★★★ 排除肇因（拔掉私接設備、清掉未授權 MAC、換線）
③ 才恢復   ─▶ interface <埠> → shutdown → no shutdown
```

> [!danger] ★★★★★ 跳過第 ② 步只會讓你陷入無限循環
> 直接 `shutdown` / `no shutdown` 而不排除肇因，
> 埠會在幾秒內**再次進入 err-disabled**。
> 更糟的是有人為了「解決問題」而把 `port-security` 或 `bpduguard` 關掉 ——
> **那不是解決問題，是拆掉警報器。**

### `portfast` 與 `bpduguard`：一定要成對 ★★★★

**沒有 portfast 的埠**，插上線之後要經過 STP 的
`listening`（15 秒）→ `learning`（15 秒）→ `forwarding`，
**總共約 30 秒才能通訊**。使用者的體感是：

| 現象 | 真正原因 |
| --- | --- |
| 「開機後要等很久才能上網」 | ★★★ DHCP 在 30 秒的 STP 等待期間逾時了 |
| 「PXE 網路開機失敗」 | ★★★ PXE 的等待時間比 30 秒短 |
| 「筆電插上網路線沒反應」 | ★★★ 同上 |

```cisco
SW-3F-01(config-if)#spanning-tree portfast
%Warning: portfast should only be enabled on ports connected to a single
 host. Connecting hubs, concentrators, switches, bridges, etc... to this
 interface when portfast is enabled, can cause temporary bridging loops.
 Use with CAUTION
```

★★★★ **那段警告不是形式**：portfast 埠一插上就直接 forwarding，
如果有人在那個埠接了一台交換器並形成環路，**廣播風暴會在毫秒內爆發**，
而 STP 來不及阻止（因為它跳過了 listening/learning）。

★★★★★ 所以 **portfast 必須搭配 bpduguard**：

```cisco
SW-3F-01(config-if)#spanning-tree portfast
SW-3F-01(config-if)#spanning-tree bpduguard enable
```

```text
使用者在 Gi1/0/12 接了一台家用交換器
        │
        ▼
那台交換器發出 BPDU
        │
        ▼
★★★★ Gi1/0/12 有 bpduguard ─▶ 立刻 err-disable 該埠
        │
        ▼
%SPANTREE-2-BLOCK_BPDUGUARD: Received BPDU on port Gi1/0/12 with BPDU Guard enabled.
%PM-4-ERR_DISABLE: bpduguard error detected on Gi1/0/12, putting Gi1/0/12 in err-disable state
        │
        ▼
只有那一個埠斷，★ 其他人完全沒感覺
```

★★★★★ **沒有 bpduguard 的話**，那台家用交換器可能：
① 造成環路 → 全網廣播風暴 → 整棟樓斷網；
② 或搶成 root bridge → 全網流量繞路 → 效能崩潰。

| 全域寫法 | 逐埠寫法 | 差別 |
| --- | --- | --- |
| `spanning-tree portfast default` | `spanning-tree portfast` | ★★★ 全域版只對 **access 埠**生效，trunk 不受影響 |
| `spanning-tree bpduguard default` | `spanning-tree bpduguard enable` | ★★★ 全域版只對**已啟用 portfast 的埠**生效 |

★★★★ 機關環境建議：**全域開，特殊埠逐埠關**。這樣新加的埠自動受保護，
不會因為忘記設定而留下缺口。

```cisco
SW-3F-01(config)#spanning-tree portfast default
SW-3F-01(config)#spanning-tree bpduguard default
!-- 上行 trunk 埠要例外
SW-3F-01(config)#interface GigabitEthernet1/0/24
SW-3F-01(config-if)#spanning-tree bpduguard disable
```

> [!warning] ★★★★★ 絕對不要用 `spanning-tree bpdufilter` 來「解決」bpduguard 的告警
> `bpdufilter` 是**不收也不送 BPDU** —— 它把 STP 在那個埠上徹底關掉。
> 全域啟用 `spanning-tree bpdufilter default` 更危險：
> 那個埠變成 STP 的盲區，**環路一旦形成就沒有任何機制能阻止**。
> 有人接了交換器導致埠一直 err-disable，正確做法是**去找出那台設備並拔掉**，
> 不是把偵測機制關掉。

### `port-security`：三種違規模式差很多 ★★★★

port-security 限制一個埠上能學到幾個 MAC、以及哪些 MAC。

| 違規模式 | 違規流量 | 埠狀態 | 產生 log | 計數器 | 適用 |
| --- | --- | --- | --- | --- | --- |
| `protect` | ★★ 靜默丟棄 | 保持 up | ★★★★ **不產生** | 不增加 | ★★ 不建議（出事你不會知道） |
| `restrict` | 丟棄 | 保持 up | ★★★★ 產生 SNMP trap 與 syslog | ★ 增加 | ★★★★ 建議（其他人不受影響） |
| `shutdown`（預設） | — | ★★★★ **err-disabled** | 產生 | 增加 | ★★★ 高安全區域 |

> [!tip] ★★★★ 機關環境的選擇建議
> **一般辦公區用 `restrict`**：違規的那台機器上不了網（達到目的），
> 但埠不會關掉，**同一個埠上原本合法的機器不受影響**（例如 IP 電話後面接電腦的場景），
> 而且會產生 log 讓你知道發生了什麼。
>
> **機房、財會、人事等高安全區域用 `shutdown`**：任何異常都要立刻中斷並人工介入。
> 搭配 `errdisable recovery` 設定自動恢復時間，避免每次都要人跑一趟。
>
> ★★★★★ **不要用 `protect`** —— 它不產生任何記錄，
> 使用者報修「網路不通」時你完全查不到原因。

**`maximum` 該設多少？**

| 場景 | `maximum` | 說明 |
| --- | --- | --- |
| 一台桌機 | `1` | 最嚴格 |
| ★★★★ IP 電話 ＋ 後面串桌機 | `2` 或 `3` | 電話一個 MAC、電腦一個 MAC，部分電話型號會多一個 |
| 有虛擬機的工作站 | ★★★★ `5`～`10` | 每個橋接模式的 VM 都是一個 MAC |
| 會議室、共用區 | 視實際情況 | ★★★ 別設太小造成誤擋 |
| ★★★★★ 接交換器的埠 | **不要用 port-security** | 下游所有 MAC 都會學進來，必爆 |

**`sticky` 的陷阱**：

```cisco
SW-3F-01(config-if)#switchport port-security mac-address sticky
```

`sticky` 的意思是「把動態學到的 MAC **寫進 running-config**，成為固定名單」。

```cisco
SW-3F-01#show running-config interface GigabitEthernet1/0/1
Building configuration...

Current configuration : 312 bytes
!
interface GigabitEthernet1/0/1
 description USER-3F-01
 switchport access vlan 30
 switchport mode access
 switchport nonegotiate
 switchport port-security maximum 2
 switchport port-security violation restrict
 switchport port-security mac-address sticky
 switchport port-security mac-address sticky 0050.56a1.2b3c
 switchport port-security
 spanning-tree portfast
 spanning-tree bpduguard enable
end
```

> [!danger] ★★★★★ sticky MAC 沒 `write memory` 就會消失
> `sticky` 學到的 MAC 進的是 **running-config**。
> 沒有 `write memory` 的話，設備一重開，**所有 sticky MAC 全部消失**，
> 重新開始學習 —— 這時候插在那個埠上的**任何**機器都會被當成合法的。
>
> ★★★★ 而更麻煩的相反情況：**存了檔之後，換一台電腦就上不了網**。
> 使用者換新電腦、換網卡、筆電換人用，都會觸發違規。
> 處理方式：
>
> ```cisco
> SW-3F-01(config-if)#no switchport port-security mac-address sticky 0050.56a1.2b3c
> ```
>
> ★★★ 或整個埠清掉重學：
>
> ```cisco
> SW-3F-01#clear port-security sticky interface GigabitEthernet1/0/1
> ```
>
> ★★★★ **導入 sticky 之前，先想清楚「電腦汰換」的作業流程誰來做。**
> 很多機關導入 port-security 之後因為維護成本太高而默默關掉，
> 那比一開始就不導入更糟（因為設定還留在那裡，讓人以為有保護）。

### `port-security` 的前置條件 ★★★

```cisco
SW-3F-01(config-if)#switchport port-security
Command rejected: GigabitEthernet1/0/5 is a dynamic port.
```

★★★★ port-security **只能用在明確設定的 access 埠或 trunk 埠**，
不能用在 `dynamic auto`／`dynamic desirable` 的埠。
必須先：

```cisco
SW-3F-01(config-if)#switchport mode access
SW-3F-01(config-if)#switchport port-security
```

★★★ 這也是為什麼上一篇強調「每個埠都要明確設定模式」——
它不只是安全問題，也是後續設定的前提。

## 環境準備與安裝

### 本篇的環境

| 項目 | 值 |
| --- | --- |
| 設備 | SW-3F-01，Catalyst WS-C2960X-24TS-L，IOS 15.2(7)E3 |
| Gi1/0/1-16 | 辦公電腦（VLAN 30） |
| Gi1/0/17-18 | AP（trunk，VLAN 20/40） |
| Gi1/0/19-20 | IP 電話 ＋ 串接電腦（VLAN 30 ＋ voice VLAN 50） |
| Gi1/0/21-23 | ★★★ 未使用 |
| Gi1/0/24 | 上行 trunk |
| 管理連線 | SSH 從 10.10.99.50 |

### 動工前的盤點 ★★★★

```cisco
SW-3F-01#show interfaces status
Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   USER-3F-01         connected    30         a-full a-1000 10/100/1000BaseTX
Gi1/0/2                      connected    30         a-full a-1000 10/100/1000BaseTX
Gi1/0/3                      notconnect   30           auto   auto 10/100/1000BaseTX
Gi1/0/9   PRINTER-3F-01      connected    30           half    100 10/100/1000BaseTX
Gi1/0/17  AP-3F-01           connected    trunk      a-full a-1000 10/100/1000BaseTX
Gi1/0/21                     connected    1          a-full a-1000 10/100/1000BaseTX
Gi1/0/24  UPLINK-TO-DIST     connected    trunk      a-full a-1000 10/100/1000BaseTX
```

★★★★ 這份輸出有四個問題：

| 埠 | 問題 | 星級 |
| --- | --- | --- |
| Gi1/0/2 | 沒有 `description`，不知道接什麼 | ★★★ |
| Gi1/0/9 | ★★★★★ `half` 雙工 —— 效能問題的來源 | ★★★★★ |
| Gi1/0/21 | ★★★★ 應該是未用埠，但**在 VLAN 1 且是 connected** —— 有人偷接了東西 | ★★★★ |
| 全部 | 沒有任何 port-security | ★★★ |

```cisco
SW-3F-01#show interfaces counters errors
Port        Align-Err     FCS-Err    Xmit-Err     Rcv-Err  UnderSize  OutDiscards
Gi1/0/1             0           0           0           0          0          12
Gi1/0/2             0           0           0           0          0           0
Gi1/0/9           322        3891           0        4213          0           0
Gi1/0/17            0           0           0           0          0           3
Gi1/0/24            0           0           0           0          0         104

Port        Single-Col  Multi-Col   Late-Col  Excess-Col  Carri-Sen       Runts
Gi1/0/1              0          0          0           0          0           0
Gi1/0/9          12441       2891       8891         421          0        8104
Gi1/0/24             0          0          0           0          0           0
```

★★★★★ Gi1/0/9 的 `Late-Col 8891` 就是雙工不一致的鐵證。

| 欄位 | 意義 | 通常指向 | 星級 |
| --- | --- | --- | --- |
| `Align-Err` | 訊框位元數不是 8 的倍數 | ★★★★ 線材、接頭、干擾、雙工不一致 | ★★★★ |
| `FCS-Err` | 檢查碼錯誤（訊框內容被破壞） | ★★★★ 線材品質、電磁干擾、超長線路 | ★★★★ |
| `Xmit-Err` | 送出緩衝區溢位 | ★★★ 該埠速率跟不上流量 | ★★★ |
| `Rcv-Err` | 接收錯誤總計（含上面幾種） | 綜合指標 | ★★★ |
| `UnderSize` | 小於 64 bytes 且 FCS 正確 | ★★ 對端網卡問題 | ★★ |
| `OutDiscards` | ★★ 因擁塞丟棄的送出封包（**不是錯誤**） | 少量正常，持續大量代表頻寬不足 | ★★ |
| `Late-Col` | ★★★★★ 延遲碰撞 | **雙工不一致**或線路超長 | ★★★★★ |
| `Excess-Col` | 連續碰撞 16 次後放棄 | ★★★★ 嚴重壅塞或雙工不一致 | ★★★★ |
| `Runts` | 小於 64 bytes 且 FCS 錯誤 | ★★★★ 碰撞的殘骸，常伴隨雙工不一致 | ★★★★ |
| `Giants` | 大於 MTU 的訊框 | ★★★ MTU 設定不一致 | ★★★ |

★★★★ 排錯時**先歸零再觀察**，比看累積值有用得多：

```cisco
SW-3F-01#clear counters GigabitEthernet1/0/9
Clear "show interface" counters on this interface [confirm]
SW-3F-01#
*Sep  2 18:04:11.221: %CLEAR-5-COUNTERS: Clear counter on interface GigabitEthernet1/0/9
 by netadm on vty0 (10.10.99.50)
```

等 10～30 分鐘再看一次，**如果計數又漲上去，問題是現在進行式**。

> [!info]- Juniper JunOS 對照
> | 事情 | Cisco IOS | Juniper JunOS（ELS） |
> | --- | --- | --- |
> | 埠描述 | `description USER-3F-01` | `set interfaces ge-0/0/1 description USER-3F-01` |
> | 關閉埠 | `shutdown` | `set interfaces ge-0/0/1 disable` |
> | 速率／雙工 | `speed 100` ＋ `duplex full` | `set interfaces ge-0/0/1 speed 100m` ＋ `link-mode full-duplex` |
> | 免除 STP 等待 | ★★★ `spanning-tree portfast` | `set protocols rstp interface ge-0/0/1 edge` |
> | 防私接交換器 | ★★★★ `spanning-tree bpduguard enable` | `set protocols rstp bpdu-block-on-edge` |
> | MAC 數量限制 | `switchport port-security maximum 2` | `set switch-options interface ge-0/0/1 interface-mac-limit 2` |
> | 違規動作 | `violation restrict` / `shutdown` | `... packet-action drop` / `shutdown` |
> | sticky MAC | ★★★★ `mac-address sticky`（★ 記得 `write memory`） | `persistent-learning`（存進設定需 `commit`） |
> | 廣播風暴抑制 | `storm-control broadcast level 5.00` | `set forwarding-options storm-control-profiles ...` |
> | 錯誤埠恢復 | ★★★ `errdisable recovery cause <原因>` | `set protocols rstp interface ... disable-timeout 300` |
> | 看錯誤計數 | `show interfaces counters errors` | `show interfaces ge-0/0/1 extensive` |
> | 看埠狀態一覽 | `show interfaces status` | `show interfaces terse` |
>
> 詳見 [[040-01-08-guide-Juniper-埠設定與安全]]。

## 基礎設定

### 步驟 1：`description` —— 最有價值的一行設定 ★★★★

★★★★ 一台沒有 description 的交換器，等於一台沒有標籤的配線架。
排錯時你會浪費大量時間在「這條線到底通到哪裡」。

**建議的命名規範**：

```text
<用途>-<位置>-<編號>[-<備註>]

USER-3F-014            辦公電腦，三樓，014 號座位
PRINTER-3F-01          印表機
IPPHONE-3F-014         IP 電話
AP-3F-01               無線基地台
SRV-DB-01              伺服器
UPLINK-TO-SW-DIST-01-Gi1/0/8   ★★★★ 上行，含對端埠號
CCTV-3F-NVR            監視器
UNUSED-DO-NOT-PATCH    ★★★ 未使用，明示不要接
RESERVED-EXPANSION     保留給擴充
```

| 規則 | 理由 | 星級 |
| --- | --- | --- |
| ★★★★ 上行埠一定要寫**對端設備 ＋ 對端埠號** | 出事時省下翻線路圖的時間 | ★★★★ |
| 不要用中文 | ★★★ 部分 IOS 版本顯示會亂碼 | ★★★ |
| 不要有空格 | ★★★ 部分過濾器與腳本會斷開 | ★★★ |
| 長度控制在 30 字以內 | ★★ `show interfaces status` 只顯示前 18 字左右 | ★★ |
| 與配線架標籤一致 | ★★★★ 兩邊對不起來就等於沒有標籤 | ★★★★ |

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface GigabitEthernet1/0/2
SW-3F-01(config-if)#description USER-3F-002
SW-3F-01(config-if)#exit
SW-3F-01(config)#interface GigabitEthernet1/0/9
SW-3F-01(config-if)#description PRINTER-3F-01
SW-3F-01(config-if)#end
```

**驗證**：

```cisco
SW-3F-01#show interfaces description | exclude admin down
Interface                      Status         Protocol Description
Gi1/0/1                        up             up       USER-3F-001
Gi1/0/2                        up             up       USER-3F-002
Gi1/0/9                        up             up       PRINTER-3F-01
Gi1/0/17                       up             up       AP-3F-01
Gi1/0/24                       up             up       UPLINK-TO-SW-DIST-01-Gi1/0/8
```

★★★★ **檢查有沒有漏網之魚**：

```cisco
SW-3F-01#show interfaces description | include up             up
```

任何 `up up` 但描述欄空白的埠，都是待補的項目。

### 步驟 2：修掉那個半雙工的埠 ★★★★★

Gi1/0/9 接的是印表機，`show interfaces status` 顯示 `half / 100`：

```cisco
SW-3F-01#show interfaces GigabitEthernet1/0/9 | include duplex|Half|Full
  Half-duplex, 100Mb/s, media type is 10/100/1000BaseTX
SW-3F-01#show running-config interface GigabitEthernet1/0/9 | include speed|duplex
 speed 100
 duplex full
```

★★★★★ **問題找到了**：交換器這端寫死 `100/full`，
印表機那端是 auto → 印表機收不到協商訊號 → 退回 parallel detection →
只偵測到速率 100，雙工自己選 half → **雙工不一致**。

★★★★ 兩種正確的修法，**選一種，不要混**：

```cisco
!-- 修法 A（★★★★★ 建議）：兩端都改回自動協商
SW-3F-01#configure terminal
SW-3F-01(config)#interface GigabitEthernet1/0/9
SW-3F-01(config-if)#no speed
SW-3F-01(config-if)#no duplex
SW-3F-01(config-if)#end
```

```cisco
!-- 修法 B：確實不支援自動協商的老設備，兩端一起寫死
!-- ★★★★ 前提：你已經到印表機的網路設定頁把它也設成 100/full
SW-3F-01(config-if)#speed 100
SW-3F-01(config-if)#duplex full
```

**驗證**（改完等 10 秒讓它重新協商）：

```cisco
SW-3F-01#show interfaces status | include Gi1/0/9
Gi1/0/9   PRINTER-3F-01      connected    30         a-full  a-100 10/100/1000BaseTX
```

★★★★ `a-full` `a-100` —— 有 `a-` 前綴代表協商成功。

```cisco
SW-3F-01#clear counters GigabitEthernet1/0/9
Clear "show interface" counters on this interface [confirm]
```

等 30 分鐘後：

```cisco
SW-3F-01#show interfaces counters errors | include Port|Gi1/0/9
Port        Align-Err     FCS-Err    Xmit-Err     Rcv-Err  UnderSize  OutDiscards
Gi1/0/9             0           0           0           0          0           0
Port        Single-Col  Multi-Col   Late-Col  Excess-Col  Carri-Sen       Runts
Gi1/0/9              0          0          0           0          0           0
```

★★★★★ **全部歸零且不再上升 ＝ 問題解決。**

> [!warning] ★★★ 改速率／雙工會讓該埠短暫斷線
> 執行 `no speed` / `no duplex` 或 `speed`/`duplex` 都會觸發鏈路重新協商，
> 該埠會 down 再 up（約 2～5 秒）。
> ★★★★ 不要在上行 trunk 埠上隨便做這件事 —— 那是整棟樓的流量。

### 步驟 3：portfast ＋ bpduguard 全域套用 ★★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#spanning-tree portfast default
%Warning: this command enables portfast by default on all interfaces. You
 should now disable portfast explicitly on switched ports leading to hubs,
 switches and bridges as they may create temporary bridging loops.
SW-3F-01(config)#spanning-tree bpduguard default
SW-3F-01(config)#end
```

★★★ 上行 trunk 埠要例外（它本來就會收到 BPDU）：

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface GigabitEthernet1/0/24
SW-3F-01(config-if)#spanning-tree bpduguard disable
SW-3F-01(config-if)#end
```

★★★★ AP 的 trunk 埠比較特別：它接的是**單一裝置**（AP 不是交換器），
所以要 portfast 但**也要**保留 bpduguard：

```cisco
SW-3F-01(config)#interface range GigabitEthernet1/0/17 - 18
SW-3F-01(config-if-range)#spanning-tree portfast trunk
SW-3F-01(config-if-range)#spanning-tree bpduguard enable
SW-3F-01(config-if-range)#end
```

★★★ 注意是 `portfast trunk` 不是 `portfast` —— 全域的
`portfast default` 只對 access 埠生效，trunk 埠需要明確加 `trunk` 關鍵字。

**驗證**：

```cisco
SW-3F-01#show spanning-tree summary
Switch is in rapid-pvst mode
Root bridge for: none
Extended system ID           is enabled
Portfast Default             is enabled
PortFast BPDU Guard Default  is enabled
Portfast BPDU Filter Default is disabled
Loopguard Default            is disabled
EtherChannel misconfig guard is enabled
UplinkFast                   is disabled
BackboneFast                 is disabled

Name                   Blocking Listening Learning Forwarding STP Active
---------------------- -------- --------- -------- ---------- ----------
VLAN0030                      0         0        0          9          9
VLAN0099                      0         0        0          2          2
---------------------- -------- --------- -------- ---------- ----------
2 vlans                       0         0        0         11         11
```

★★★★★ **必看的兩行**：
`Portfast Default is enabled`、`PortFast BPDU Guard Default is enabled`，
以及 `Portfast BPDU Filter Default is disabled`（★★★★★ **這個必須是 disabled**）。

```cisco
SW-3F-01#show spanning-tree interface GigabitEthernet1/0/1 portfast
VLAN0030            enabled
```

### 步驟 4：未用埠的兩層處理 ★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface range GigabitEthernet1/0/21 - 23
SW-3F-01(config-if-range)#description UNUSED-DO-NOT-PATCH
SW-3F-01(config-if-range)#switchport mode access
SW-3F-01(config-if-range)#switchport access vlan 999
SW-3F-01(config-if-range)#switchport nonegotiate
SW-3F-01(config-if-range)#shutdown
SW-3F-01(config-if-range)#end
```

★★★★ **為什麼要做兩件事（丟 VLAN 999 ＋ shutdown）？**

| 只做 `shutdown` | 只丟 VLAN 999 | 兩者都做 |
| --- | --- | --- |
| ★★★ 有人為了急用 `no shutdown` → **埠落在 VLAN 1**，直通內網 | ★★★ 埠是 up 的，任何人接上就有連線（只是在死路 VLAN） | ★★★★ 有人 `no shutdown` 也只會落在死路 VLAN |

★★★★ VLAN 999 必須是**真正的死路**：沒有 SVI、沒有 IP、
不在任何 trunk 的 allowed list 裡。見 [[040-01-11-guide-Cisco-VLAN與Trunk設定]]。

**驗證**：

```cisco
SW-3F-01#show interfaces status | include disabled
Gi1/0/21  UNUSED-DO-NOT-PATC disabled     999          auto   auto 10/100/1000BaseTX
Gi1/0/22  UNUSED-DO-NOT-PATC disabled     999          auto   auto 10/100/1000BaseTX
Gi1/0/23  UNUSED-DO-NOT-PATC disabled     999          auto   auto 10/100/1000BaseTX
```

★★★★ **確認 VLAN 1 上沒有任何埠**：

```cisco
SW-3F-01#show vlan brief | include ^1  |^1$
1    default                          active
```

`Ports` 欄空白 ＝ 過關。

### 步驟 5：port-security ★★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface range GigabitEthernet1/0/1 - 16
SW-3F-01(config-if-range)#switchport port-security
SW-3F-01(config-if-range)#switchport port-security maximum 3
SW-3F-01(config-if-range)#switchport port-security violation restrict
SW-3F-01(config-if-range)#switchport port-security mac-address sticky
SW-3F-01(config-if-range)#switchport port-security aging time 480
SW-3F-01(config-if-range)#switchport port-security aging type inactivity
SW-3F-01(config-if-range)#end
```

| 指令 | 作用 | 星級 |
| --- | --- | --- |
| `switchport port-security` | ★★★★ 啟用（**這行不打，其他都不生效**） | ★★★★ |
| `maximum 3` | ★★★★ 最多學 3 個 MAC（電話＋電腦＋一個緩衝） | ★★★★ |
| `violation restrict` | ★★★★ 丟棄違規流量、產生 log、不關埠 | ★★★★ |
| `mac-address sticky` | ★★★★ 學到的 MAC 寫進 running-config | ★★★★ |
| `aging time 480` | ★★★ 480 分鐘（8 小時）後老化 | ★★★ |
| `aging type inactivity` | ★★★ **閒置**才計時（預設是 absolute 絕對計時） | ★★★ |

★★★★ `aging type inactivity` 很重要：預設的 `absolute` 是「學到之後固定 N 分鐘就忘記」，
即使那台電腦一直在用；`inactivity` 是「N 分鐘沒有流量才忘記」，
比較符合「這個座位換人了」的實際語意。

★★★★★ **設完立刻存檔，否則重開後 sticky MAC 全部消失**：

```cisco
SW-3F-01#write memory
Building configuration...
[OK]
```

**驗證**：

```cisco
SW-3F-01#show port-security
Secure Port  MaxSecureAddr  CurrentAddr  SecurityViolation  Security Action
                (Count)       (Count)          (Count)
---------------------------------------------------------------------------
      Gi1/0/1            3            1                  0         Restrict
      Gi1/0/2            3            1                  0         Restrict
      Gi1/0/3            3            0                  0         Restrict
      ...
---------------------------------------------------------------------------
Total Addresses in System (excluding one mac per port)     : 2
Max Addresses limit in System (excluding one mac per port) : 4096
```

```cisco
SW-3F-01#show port-security interface GigabitEthernet1/0/1
Port Security              : Enabled
Port Status                : Secure-up
Violation Mode             : Restrict
Aging Time                 : 480 mins
Aging Type                 : Inactivity
SecureStatic Address Aging : Disabled
Maximum MAC Addresses      : 3
Total MAC Addresses        : 1
Configured MAC Addresses   : 0
Sticky MAC Addresses       : 1
Last Source Address:Vlan   : 0050.56a1.2b3c:30
Security Violation Count   : 0
```

★★★★ 要看的三行：`Port Status : Secure-up`（正常）、
`Violation Mode : Restrict`（如預期）、`Security Violation Count : 0`（沒有違規）。
`Port Status : Secure-shutdown` 代表已經違規並被關閉了。

```cisco
SW-3F-01#show port-security address
          Secure Mac Address Table
--------------------------------------------------------------------------
Vlan    Mac Address       Type                     Ports   Remaining Age
                                                              (mins)
----    -----------       ----                     -----   -------------
  30    0050.56a1.2b3c    SecureSticky             Gi1/0/1        471
  30    b827.ebaa.1122    SecureSticky             Gi1/0/2        468
--------------------------------------------------------------------------
Total Addresses in System (excluding one mac per port)     : 2
```

### 步驟 6：IP 電話埠的特殊設定 ★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface range GigabitEthernet1/0/19 - 20
SW-3F-01(config-if-range)#description IPPHONE-3F-PC
SW-3F-01(config-if-range)#switchport mode access
SW-3F-01(config-if-range)#switchport access vlan 30
SW-3F-01(config-if-range)#switchport voice vlan 50
SW-3F-01(config-if-range)#switchport nonegotiate
SW-3F-01(config-if-range)#switchport port-security
SW-3F-01(config-if-range)#switchport port-security maximum 3
SW-3F-01(config-if-range)#switchport port-security violation restrict
SW-3F-01(config-if-range)#switchport port-security mac-address sticky
SW-3F-01(config-if-range)#spanning-tree portfast
SW-3F-01(config-if-range)#spanning-tree bpduguard enable
SW-3F-01(config-if-range)#end
```

★★★★ `maximum 3` 而不是 2 的理由：
IP 電話本身一個 MAC（在 voice VLAN 50）、後面串接的電腦一個 MAC（在 VLAN 30），
★★★ 部分電話型號的內建交換器晶片還會多出一個 MAC。設 2 會誤擋。

★★★ 若你的機型支援分別限制，可以更精準：

```cisco
SW-3F-01(config-if)#switchport port-security maximum 2 vlan access
SW-3F-01(config-if)#switchport port-security maximum 1 vlan voice
```

★★★★ 這個語法在部分機型／版本不存在，打之前用
`switchport port-security maximum 2 ?` 確認。

## 進階設定與調校

### `errdisable recovery`：讓埠自己恢復 ★★★★

每次 err-disable 都要人工 `shutdown`／`no shutdown` 很累。
可以設定自動恢復：

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#errdisable recovery cause psecure-violation
SW-3F-01(config)#errdisable recovery cause bpduguard
SW-3F-01(config)#errdisable recovery cause link-flap
SW-3F-01(config)#errdisable recovery cause storm-control
SW-3F-01(config)#errdisable recovery interval 300
SW-3F-01(config)#end
```

```cisco
SW-3F-01#show errdisable recovery
ErrDisable Reason            Timer Status
-----------------            --------------
arp-inspection               Disabled
bpduguard                    Enabled
channel-misconfig (STP)      Disabled
dhcp-rate-limit              Disabled
dtp-flap                     Disabled
gbic-invalid                 Disabled
inline-power                 Disabled
l2ptguard                    Disabled
link-flap                    Enabled
mac-limit                    Disabled
loopback                     Disabled
pagp-flap                    Disabled
port-mode-failure            Disabled
pppoe-ia-rate-limit          Disabled
psecure-violation            Enabled
security-violation           Disabled
sfp-config-mismatch          Disabled
small-frame                  Disabled
storm-control                Enabled
udld                         Disabled
vmps                         Disabled
psp                          Disabled

Timer interval: 300 seconds

Interfaces that will be enabled at the next timeout:

Interface     Errdisable reason       Time left(sec)
---------     -----------------       --------------
Gi1/0/12         bpduguard                  187
```

> [!warning] ★★★★ 自動恢復是雙面刃
> **好處**：使用者拔掉私接的交換器之後，5 分鐘內自己恢復，不用報修。
> ★★★★ **壞處**：如果肇因沒排除（那台交換器還接著），
> 埠會進入「恢復 → 再次違規 → err-disable → 恢復」的循環，
> 每一輪都可能造成短暫的廣播風暴。
>
> ★★★★★ **絕對不要對 `udld` 開自動恢復** ——
> UDLD 偵測到的是實體層的單向連線（光纖一芯壞了），
> 自動恢復只會讓一條半殘的鏈路反覆加入拓樸，造成 STP 反覆重算。
>
> ★★★ 折衷建議：`interval` 設長一點（600～900 秒），
> 並且**一定要把 err-disable 事件送到 syslog 並設告警**，
> 讓自動恢復不會掩蓋掉真正的問題。見 [[100-01-03-guide-日誌-系統監控與告警]]。

### `storm-control`：擋住廣播風暴 ★★★

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface range GigabitEthernet1/0/1 - 20
SW-3F-01(config-if-range)#storm-control broadcast level 5.00 3.00
SW-3F-01(config-if-range)#storm-control multicast level 5.00 3.00
SW-3F-01(config-if-range)#storm-control action trap
SW-3F-01(config-if-range)#end
```

| 參數 | 意義 |
| --- | --- |
| `level 5.00 3.00` | ★★★ 超過頻寬的 5% 開始抑制，降到 3% 以下才解除（遲滯） |
| `action trap` | ★★★ 只發 SNMP trap 與 syslog，不關埠 |
| `action shutdown` | ★★★★ 直接 err-disable 該埠（較激進） |
| `level pps 1000` | 用每秒封包數而非百分比（部分機型支援） |

```cisco
SW-3F-01#show storm-control broadcast
Interface  Filter State   Upper        Lower        Current
---------  -------------  -----------  -----------  ----------
Gi1/0/1    Forwarding       5.00%        3.00%        0.00%
Gi1/0/2    Forwarding       5.00%        3.00%        0.12%
Gi1/0/12   Blocking         5.00%        3.00%       47.83%
```

★★★★ `Blocking` 且 `Current 47.83%` ＝ **Gi1/0/12 正在製造廣播風暴**，
去看那個埠接了什麼。

> [!tip] ★★★ 門檻值怎麼定
> 5% 是常見的起點，但**每個環境不一樣**。設太低會誤擋
> （例如網路開機 PXE、大量 ARP 的環境），設太高等於沒設。
> 建議做法：先用 `action trap` 觀察一到兩週，
> 看 `show storm-control` 的 `Current` 值的正常波動範圍，再訂門檻。

### 使用者埠關閉 CDP ★★★★

```cisco
SW-3F-01(config)#interface range GigabitEthernet1/0/1 - 16
SW-3F-01(config-if-range)#no cdp enable
SW-3F-01(config-if-range)#end
```

★★★★ CDP 會廣播設備型號、IOS 版本、管理 IP、埠號 ——
接在使用者埠上的任何機器都收得到，這是攻擊者的偵察起點。
★★★ **設備之間的埠（trunk、上行）要保留 CDP**，那是排錯的重要工具。
★★★ IP 電話埠要保留 CDP（電話靠它取得 voice VLAN），或改用 LLDP-MED。

```cisco
SW-3F-01#show cdp interface GigabitEthernet1/0/1
（沒有輸出 → CDP 已在該埠關閉）

SW-3F-01#show cdp interface GigabitEthernet1/0/24
GigabitEthernet1/0/24 is up, line protocol is up
  Encapsulation ARPA
  Sending CDP packets every 60 seconds
  Holdtime is 180 seconds
```

### DHCP snooping 與動態 ARP 檢查 ★★★

★★★★ 這兩個功能防的是「使用者接了一台家用路由器，
它的 DHCP 伺服器開始發 192.168.1.x 給整層樓」的經典事故。

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#ip dhcp snooping
SW-3F-01(config)#ip dhcp snooping vlan 30,40
SW-3F-01(config)#no ip dhcp snooping information option
SW-3F-01(config)#interface GigabitEthernet1/0/24
SW-3F-01(config-if)#ip dhcp snooping trust
SW-3F-01(config-if)#exit
SW-3F-01(config)#interface range GigabitEthernet1/0/1 - 20
SW-3F-01(config-if-range)#ip dhcp snooping limit rate 15
SW-3F-01(config-if-range)#end
```

| 指令 | 作用 | 星級 |
| --- | --- | --- |
| `ip dhcp snooping` | 全域啟用 | ★★★★ |
| `ip dhcp snooping vlan 30,40` | ★★★★ 指定要保護的 VLAN（**不指定等於沒作用**） | ★★★★ |
| `ip dhcp snooping trust` | ★★★★★ **只有上行埠設 trust**（合法 DHCP 從那裡來） | ★★★★★ |
| `no ip dhcp snooping information option` | ★★★★ 關閉 Option 82（★ 不關的話多數 DHCP 伺服器會丟棄請求） | ★★★★ |
| `ip dhcp snooping limit rate 15` | ★★★ 限制每秒 DHCP 封包數，防洪水攻擊 | ★★★ |

```cisco
SW-3F-01#show ip dhcp snooping
Switch DHCP snooping is enabled
Switch DHCP gleaning is disabled
DHCP snooping is configured on following VLANs:
30,40
DHCP snooping is operational on following VLANs:
30,40
Insertion of option 82 is disabled
Interface                  Trusted    Allow option    Rate limit (pps)
------------------------   -------    ------------    ----------------
GigabitEthernet1/0/1       no         no              15
GigabitEthernet1/0/24      yes        yes             unlimited
```

> [!danger] ★★★★★ 導入 DHCP snooping 有兩個必踩的坑
> **坑 1：忘記把上行埠設成 `trust`。**
> 結果是**整層樓的 DHCP 全部失效**（合法的 DHCP OFFER 從不受信任的埠進來，被丟棄）。
> ★★★★★ **一定要先設 trust，再啟用 snooping。**
>
> **坑 2：Option 82。**
> IOS 預設會在 DHCP 請求中插入 Option 82，但**交換器自己不是 relay agent**，
> 多數 DHCP 伺服器收到來源是 0.0.0.0 卻帶著 Option 82 的請求會直接丟棄。
> 解法：`no ip dhcp snooping information option`。
>
> ★★★★ 這兩個坑都會造成大範圍斷網，**務必在維護時段導入，並先 `reload in 10`**。

動態 ARP 檢查（DAI）建立在 DHCP snooping 的綁定表上：

```cisco
SW-3F-01(config)#ip arp inspection vlan 30,40
SW-3F-01(config)#interface GigabitEthernet1/0/24
SW-3F-01(config-if)#ip arp inspection trust
SW-3F-01(config-if)#end
```

★★★★ DAI 會擋掉 ARP 欺騙（中間人攻擊）。
★★★★★ 但**靜態 IP 的機器（伺服器、印表機）不在 DHCP 綁定表裡，會被擋掉**，
必須額外建 ARP ACL：

```cisco
SW-3F-01(config)#arp access-list STATIC-HOSTS
SW-3F-01(config-arp-nacl)#permit ip host 10.10.30.200 mac host 0050.56a1.9999
SW-3F-01(config-arp-nacl)#exit
SW-3F-01(config)#ip arp inspection filter STATIC-HOSTS vlan 30
```

★★★ DAI 的維護成本不低，**建議先把 DHCP snooping 做好、穩定運行一段時間後再考慮 DAI**。

### 批次巡檢腳本 ★★★

```cisco
!-- ① 有沒有半雙工的埠（★★★★★ 一秒鐘檢查）
show interfaces status | include half

!-- ② 有沒有 err-disabled 的埠
show interfaces status err-disabled

!-- ③ 有沒有 port-security 違規
show port-security | exclude          0

!-- ④ 有沒有錯誤計數在增加（跑兩次比對）
show interfaces counters errors | exclude    0           0           0           0

!-- ⑤ 有沒有埠留在 VLAN 1
show vlan brief | begin ^1

!-- ⑥ 有沒有埠沒有描述
show interfaces description | include up             up

!-- ⑦ 廣播風暴狀況
show storm-control broadcast | exclude 0.00%

!-- ⑧ 全域保護機制的狀態
show spanning-tree summary | include Portfast|BPDU
```

★★★★ 這八行應該納入每月巡檢的固定項目，
見 [[040-02-10-guide-機房-機房巡檢與紀錄]]。

## 完整實戰範例

**情境**：週一早上，三樓整層樓的使用者陸續報修「網路很慢，開檔案要等很久」。
你 SSH 進 SW-3F-01 查看。過程中你會發現**兩個獨立的問題**：
一個雙工不一致，一個私接交換器造成的廣播風暴。

### 前置環境

| 項目 | 值 |
| --- | --- |
| 設備 | SW-3F-01，10.10.99.31，Catalyst 2960-X，IOS 15.2(7)E3 |
| 症狀 | 三樓部分使用者「網路很慢」，但 ping 通 |
| 你的位置 | 跳板機 10.10.99.50，SSH |
| 時間 | ★★★ 上班時間，不能隨便斷線 |

### 步驟 1：三分鐘快速分診 ★★★★

```cisco
SW-3F-01#terminal length 0
SW-3F-01#show interfaces status | include half
Gi1/0/9   PRINTER-3F-01      connected    30           half    100 10/100/1000BaseTX
```

★★★★★ **第一個問題找到了**：Gi1/0/9 是半雙工。

```cisco
SW-3F-01#show interfaces status err-disabled
Port      Name               Status       Reason               Err-disabled Vlans
```

沒有 err-disabled 的埠。

```cisco
SW-3F-01#show storm-control broadcast | exclude 0.00%
Interface  Filter State   Upper        Lower        Current
---------  -------------  -----------  -----------  ----------
Gi1/0/12   Forwarding       5.00%        3.00%       42.17%
Gi1/0/24   Forwarding       5.00%        3.00%       38.94%
```

★★★★★ **第二個問題找到了**：Gi1/0/12 的廣播佔了 42% 的頻寬，
而且上行 Gi1/0/24 也有 38% —— **廣播正在往整個網路擴散**。

```cisco
SW-3F-01#show processes cpu sorted | include CPU utilization|^ *[0-9]
CPU utilization for five seconds: 78%/61%; one minute: 71%; five minutes: 66%
 PID Runtime(ms)     Invoked      uSecs   5Sec   1Min   5Min TTY Process
 138    88214123    41221033        214  9.12%  8.44%  8.01%   0 Hulc LED Process
  91    12441022     8812441       1411  4.31%  4.02%  3.88%   0 IP Input
```

★★★★ `78%/61%` —— 斜線後面那個 61% 是**中斷處理時間**，
代表 CPU 正在被大量封包淹沒。這佐證了廣播風暴的判斷。

### 步驟 2：先處理廣播風暴（影響範圍最大）★★★★★

```cisco
SW-3F-01#show interfaces GigabitEthernet1/0/12 | include description|input rate|output rate
SW-3F-01#show running-config interface GigabitEthernet1/0/12
Building configuration...

Current configuration : 198 bytes
!
interface GigabitEthernet1/0/12
 description USER-3F-012
 switchport access vlan 30
 switchport mode access
 switchport nonegotiate
 storm-control broadcast level 5.00 3.00
 storm-control action trap
 spanning-tree portfast
end
```

★★★★★ **注意看：這個埠有 `portfast` 但沒有 `bpduguard`！**
（因為當初是逐埠設定的，漏了這一個。）

```cisco
SW-3F-01#show mac address-table interface GigabitEthernet1/0/12
          Mac Address Table
-------------------------------------------

Vlan    Mac Address       Type        Ports
----    -----------       --------    -----
  30    0050.56a1.2b3c    DYNAMIC     Gi1/0/12
  30    b827.eb11.2233    DYNAMIC     Gi1/0/12
  30    b827.eb11.2234    DYNAMIC     Gi1/0/12
  30    aabb.cc00.1100    DYNAMIC     Gi1/0/12
  30    aabb.cc00.1101    DYNAMIC     Gi1/0/12
  30    aabb.cc00.1102    DYNAMIC     Gi1/0/12
Total Mac Addresses for this criterion: 6
```

★★★★★ **一個座位的埠學到 6 個 MAC → 那裡接了一台交換器。**

```cisco
SW-3F-01#show cdp neighbors GigabitEthernet1/0/12
Capability Codes: R - Router, T - Trans Bridge, B - Source Route Bridge
                  S - Switch, H - Host, I - IGMP, r - Repeater, P - Phone,
                  D - Remote, C - CVTA, M - Two-port Mac Relay

Device ID        Local Intrfce     Holdtme    Capability  Platform  Port ID
```

★★★ CDP 看不到（家用交換器不發 CDP），但 MAC 數量已經足夠判斷。

**立即處置：先把那個埠關掉，止血**

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface GigabitEthernet1/0/12
SW-3F-01(config-if)#shutdown
SW-3F-01(config-if)#end
SW-3F-01#
*Sep  8 09:12:44.331: %LINK-5-CHANGED: Interface GigabitEthernet1/0/12, changed state
to administratively down
```

**驗證止血效果**（等 30 秒）：

```cisco
SW-3F-01#show storm-control broadcast | exclude 0.00%
Interface  Filter State   Upper        Lower        Current
---------  -------------  -----------  -----------  ----------
Gi1/0/24   Forwarding       5.00%        3.00%        0.31%

SW-3F-01#show processes cpu | include CPU utilization
CPU utilization for five seconds: 12%/4%; one minute: 38%; five minutes: 52%
```

★★★★★ 廣播降到 0.31%、CPU 從 78% 降到 12% → **風暴止住了**。
五分鐘平均值還高是因為它是移動平均，會慢慢降下來。

**補上遺漏的保護**：

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#spanning-tree bpduguard default
SW-3F-01(config)#interface GigabitEthernet1/0/24
SW-3F-01(config-if)#spanning-tree bpduguard disable
SW-3F-01(config-if)#end
SW-3F-01#show spanning-tree summary | include Portfast|BPDU
Portfast Default             is enabled
PortFast BPDU Guard Default  is enabled
Portfast BPDU Filter Default is disabled
```

★★★★ 現在**所有** portfast 埠都受保護了，不會再有漏網之魚。

**通知使用者並確認**：請三樓 012 座位的同仁拔掉私接的交換器，
確認之後再開埠：

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface GigabitEthernet1/0/12
SW-3F-01(config-if)#no shutdown
SW-3F-01(config-if)#end
```

**驗證**（等 1 分鐘）：

```cisco
SW-3F-01#show mac address-table interface GigabitEthernet1/0/12
          Mac Address Table
-------------------------------------------

Vlan    Mac Address       Type        Ports
----    -----------       --------    -----
  30    0050.56a1.2b3c    DYNAMIC     Gi1/0/12
Total Mac Addresses for this criterion: 1

SW-3F-01#show interfaces status | include Gi1/0/12
Gi1/0/12  USER-3F-012        connected    30         a-full a-1000 10/100/1000BaseTX
```

★★★★ 只剩 1 個 MAC ＝ 私接設備已移除。

★★★ 如果他真的需要多個網路孔，正確做法是**申請配線架增接**，
而不是自己買交換器。這件事要寫進事件紀錄並回報。

### 步驟 3：處理雙工不一致

```cisco
SW-3F-01#show interfaces GigabitEthernet1/0/9 | include duplex|late|Runts|CRC
  Half-duplex, 100Mb/s, media type is 10/100/1000BaseTX
     4213 input errors, 3891 CRC, 322 frame, 0 overrun, 0 ignored
     8104 runts, 0 giants, 0 throttles
     8891 late collision, 0 deferred

SW-3F-01#show running-config interface GigabitEthernet1/0/9 | include speed|duplex
 speed 100
 duplex full
```

★★★★★ 交換器端寫死 `100/full`、實際協商結果是 `half` →
**對端（印表機）是 auto，且只透過 parallel detection 偵測到速率。**

**先確認影響範圍**：這個埠是印表機，斷 5 秒可以接受。

```cisco
SW-3F-01#configure terminal
SW-3F-01(config)#interface GigabitEthernet1/0/9
SW-3F-01(config-if)#no speed
SW-3F-01(config-if)#no duplex
SW-3F-01(config-if)#end
SW-3F-01#
*Sep  8 09:24:11.442: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/9, changed state to down
*Sep  8 09:24:14.881: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/9, changed state to up
```

**驗證**：

```cisco
SW-3F-01#show interfaces status | include Gi1/0/9
Gi1/0/9   PRINTER-3F-01      connected    30         a-full  a-100 10/100/1000BaseTX
```

★★★★★ `a-full` `a-100` —— 協商成功，且是全雙工。

```cisco
SW-3F-01#clear counters GigabitEthernet1/0/9
Clear "show interface" counters on this interface [confirm]
SW-3F-01#
*Sep  8 09:25:02.114: %CLEAR-5-COUNTERS: Clear counter on interface
GigabitEthernet1/0/9 by netadm on vty0 (10.10.99.50)
```

★★★ 等 30 分鐘後複查（這是驗收的關鍵一步）：

```cisco
SW-3F-01#show interfaces counters errors | include Port|Gi1/0/9
Port        Align-Err     FCS-Err    Xmit-Err     Rcv-Err  UnderSize  OutDiscards
Gi1/0/9             0           0           0           0          0           0
Port        Single-Col  Multi-Col   Late-Col  Excess-Col  Carri-Sen       Runts
Gi1/0/9              0          0          0           0          0           0
```

★★★★★ **全零且不再增加 ＝ 真的修好了。**

### 步驟 4：全面盤查，找出同類問題

★★★★ 修好報修的那兩個之後，**主動找出還沒被報修的同類問題**：

```cisco
!-- 全交換器還有沒有寫死速率／雙工的埠
SW-3F-01#show running-config | include ^interface| speed | duplex
interface GigabitEthernet1/0/14
 speed 100
 duplex full
interface GigabitEthernet1/0/24
```

★★★★ 又找到一個：Gi1/0/14。

```cisco
SW-3F-01#show interfaces status | include Gi1/0/14
Gi1/0/14  USER-3F-014        connected    30           full    100 10/100/1000BaseTX
```

★★★ 這個是 `full` —— 目前沒有問題（對端也寫死了，或協商剛好對上），
但它是一顆**未爆彈**：只要那台電腦換網卡或換人用，就會變成半雙工。

```cisco
SW-3F-01#show interfaces counters errors | include Port|Gi1/0/14
Port        Single-Col  Multi-Col   Late-Col  Excess-Col  Carri-Sen       Runts
Gi1/0/14             0          0          0           0          0           0
```

★★★ 目前計數是零，**列入待辦，排到維護時段一起改回 auto**，
不要在上班時間動一個目前正常的埠。

### 步驟 5：補齊防護並存檔

```cisco
SW-3F-01#configure terminal
!-- 補上遺漏的 port-security（Gi1/0/12 當初漏了）
SW-3F-01(config)#interface GigabitEthernet1/0/12
SW-3F-01(config-if)#switchport port-security
SW-3F-01(config-if)#switchport port-security maximum 3
SW-3F-01(config-if)#switchport port-security violation restrict
SW-3F-01(config-if)#switchport port-security mac-address sticky
SW-3F-01(config-if)#switchport port-security aging time 480
SW-3F-01(config-if)#switchport port-security aging type inactivity
SW-3F-01(config-if)#exit
!-- 自動恢復（避免下次同樣狀況要人工介入）
SW-3F-01(config)#errdisable recovery cause bpduguard
SW-3F-01(config)#errdisable recovery cause psecure-violation
SW-3F-01(config)#errdisable recovery cause storm-control
SW-3F-01(config)#errdisable recovery interval 600
SW-3F-01(config)#end
SW-3F-01#write memory
Building configuration...
[OK]
```

★★★★★ **`write memory` 特別重要** —— sticky MAC 在 running-config 裡，
不存檔的話重開就全沒了。

```cisco
SW-3F-01#show archive config differences system:running-config nvram:startup-config
!Contextual Config Diffs:
!No changes were found
```

```cisco
SW-3F-01#copy running-config tftp://10.10.99.20/SW-3F-01-20260908.cfg
!!
5721 bytes copied in 1.402 secs (4081 bytes/sec)
```

### 驗收檢查表 ★★★★

| # | 檢查項 | 指令 | 通過條件 |
| --- | --- | --- | --- |
| 1 | 沒有半雙工的埠 | `show interfaces status \| include half` | ★★★★★ 無輸出 |
| 2 | 沒有 err-disabled | `show interfaces status err-disabled` | 無輸出 |
| 3 | 廣播流量正常 | `show storm-control broadcast \| exclude 0.00%` | 沒有超過門檻的埠 |
| 4 | CPU 正常 | `show processes cpu \| include utilization` | 五秒值 < 30% |
| 5 | 錯誤計數不再增加 | `clear counters` 後 30 分鐘複查 | ★★★★★ 全零 |
| 6 | 每個 access 埠一個 MAC | `show mac address-table` | 沒有單一埠學到大量 MAC |
| 7 | 全域保護已開 | `show spanning-tree summary \| include Portfast\|BPDU` | portfast 與 bpduguard 皆 enabled，bpdufilter **disabled** |
| 8 | port-security 全覆蓋 | `show port-security` | 所有使用者埠都在清單裡 |
| 9 | 無違規計數 | `show port-security \| exclude 0` | 違規計數為 0 |
| 10 | 未用埠已處理 | `show interfaces status \| include disabled` | 在 VLAN 999 且 `disabled` |
| 11 | VLAN 1 無埠 | `show vlan brief \| begin ^1` | Ports 欄空白 |
| 12 | 每個 up 的埠都有描述 | `show interfaces description` | 無空白描述 |
| 13 | ★★★★★ 已存檔 | `show archive config differences ...` | `No changes were found` |
| 14 | 已備份 | 備份主機 | 有今天日期的檔案 |

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| 網路「很慢」但 ping 通、`show interfaces status` 顯示 `connected` | ★★★★★ 雙工不一致（一端寫死、一端 auto） | `show interfaces <埠> \| include late collision`，有數字就是。兩端都改回 auto，或兩端都寫死 |
| `late collision` 持續上升 | ★★★★★ 雙工不一致，或線路超過 100m | 先查對端的速率／雙工設定；線長問題要重拉線 |
| `Runts` 與 `FCS-Err` 大量增加 | ★★★★ 線材品質差、接頭氧化、電磁干擾、雙工不一致 | 換一條測試線比對；檢查是否與電源線平行走線 |
| `Align-Err` 增加 | ★★★★ 線材、接頭、或雙工不一致 | 同上 |
| 埠變成 `err-disabled`，reason 是 `bpduguard` | ★★★★ 該埠收到 BPDU（有人接了交換器） | 拔掉私接設備 → `shutdown` → `no shutdown`。★★★★★ 不要用關掉 bpduguard 來「解決」 |
| 埠變成 `err-disabled`，reason 是 `psecure-violation` | ★★★★ port-security 偵測到未授權 MAC | `show port-security interface <埠>` 看 `Last Source Address`；確認是誰的機器後決定放行或處置 |
| 埠恢復後幾秒又進 err-disabled | ★★★★★ 肇因沒排除 | 先找出並移除肇因（私接設備、未授權機器），再恢復 |
| `Command rejected: GigabitEthernet1/0/5 is a dynamic port.` | ★★★★ port-security 不能用在 dynamic 模式的埠 | 先 `switchport mode access`，再 `switchport port-security` |
| 設了 sticky MAC，重開機後全部消失 | ★★★★★ sticky 存在 running-config，沒 `write memory` | 設定完立刻 `write memory` |
| 使用者換新電腦後上不了網 | ★★★★ sticky MAC 綁著舊網卡 | `clear port-security sticky interface <埠>`，或 `no switchport port-security mac-address sticky <舊 MAC>` |
| IP 電話後面接電腦，電腦連不上 | ★★★★ `port-security maximum` 設太小（設 1 或 2） | 改成 `maximum 3` |
| port-security 設了但完全沒作用 | ★★★★ 忘記打 `switchport port-security`（只設了子參數） | `show port-security` 看該埠在不在清單裡；補上主指令 |
| 使用者「開機後要等 30 秒才能上網」 | ★★★ 沒設 `spanning-tree portfast` | 對所有接單一終端的埠加 portfast（或用全域 `portfast default`） |
| 有人接了交換器，全網廣播暴增、CPU 飆高 | ★★★★★ 沒有 bpduguard，形成環路或搶 root | 立刻 `shutdown` 該埠止血；補上 `spanning-tree bpduguard default` |
| `show spanning-tree summary` 顯示 `Portfast BPDU Filter Default is enabled` | ★★★★★ 有人開了 bpdufilter，STP 在那些埠等於關閉 | `no spanning-tree bpdufilter default`。**環路將無法被偵測** |
| `portfast` 對 trunk 埠沒作用 | ★★★ 全域 `portfast default` 只對 access 埠生效 | trunk 埠要明確打 `spanning-tree portfast trunk` |
| 未用埠 `shutdown` 了，但有人 `no shutdown` 之後直接進內網 | ★★★★ 只做了 shutdown，沒丟黑洞 VLAN | 兩件都要做：`switchport access vlan 999` ＋ `shutdown` |
| 啟用 DHCP snooping 之後整層樓拿不到 IP | ★★★★★ 上行埠沒設 `ip dhcp snooping trust` | 上行埠加 `trust`；並確認 `no ip dhcp snooping information option` |
| DHCP snooping 開了但沒作用 | ★★★★ 只打了全域指令，沒指定 VLAN | 補 `ip dhcp snooping vlan 30,40` |
| 啟用 DAI 之後伺服器與印表機不通 | ★★★★★ 靜態 IP 的機器不在 DHCP 綁定表裡 | 建 `arp access-list` 明確放行，或改用 `ip source binding` 手動建綁定 |
| `storm-control` 一直誤觸發 | ★★★ 門檻設太低，或環境本來就有大量廣播 | 先用 `action trap` 觀察兩週的 `Current` 值再定門檻 |
| 光纖鏈路半通不通、STP 反覆重算 | ★★★★ 單向連線（一芯壞），UDLD 未啟用或已自動恢復 | 啟用 UDLD aggressive；★★★★★ **不要對 udld 開 errdisable recovery** |
| `show interfaces status` 上有埠是 `connected` 但你不知道接什麼 | ★★★ 沒有 description | 用 `show mac address-table` ＋ `show cdp neighbors` 反查，補上描述 |
| `clear counters` 之後計數又立刻歸零看不出問題 | ★★★ 觀察時間太短 | 清完至少等 30 分鐘（有流量的時段）再看 |

## 安全性注意事項

> [!warning] ★★★★★ 實體存取就是最高權限
> 一個沒有保護的網路孔 ＝ 任何人（訪客、清潔人員、外包廠商）
> 只要帶一台筆電就能接進內網。埠安全的每一項措施，
> 本質上都是在補「實體存取無法完全管制」這個現實。

| 項目 | 風險 | 做法 | 星級 |
| --- | --- | --- | --- |
| 未用埠是 up 的且在 VLAN 1 | ★★★★★ 任何人接上就進內網 | `shutdown` ＋ 丟黑洞 VLAN 999（兩件都做） | ★★★★★ |
| 沒有 port-security | ★★★★ 任何裝置接上就能通訊 | `maximum` ＋ `violation restrict` ＋ `sticky` | ★★★★ |
| 用 `violation protect` | ★★★★ 靜默丟棄，出事完全沒有記錄 | 改用 `restrict`（有 log）或 `shutdown` | ★★★★ |
| 有 portfast 沒 bpduguard | ★★★★★ 私接交換器可造成廣播風暴或搶 root | ★★★★★ 兩者必須成對，建議用全域 default | ★★★★★ |
| 啟用 `bpdufilter` | ★★★★★ STP 在該埠徹底失效，環路無法偵測 | ★★★★★ 絕對不要用它來消除 bpduguard 告警 | ★★★★★ |
| 沒有 DHCP snooping | ★★★★ 使用者接家用路由器發錯 IP，或惡意 DHCP 中間人 | `ip dhcp snooping` ＋ 上行 `trust` | ★★★★ |
| 沒有 storm-control | ★★★ 單一故障設備可癱瘓全網 | `storm-control broadcast level 5.00` ＋ `action trap` | ★★★ |
| 使用者埠開著 CDP | ★★★★ 洩漏型號、IOS 版本、管理 IP | 使用者埠 `no cdp enable` | ★★★★ |
| 沒有 `description` | ★★★ 出事時無法快速定位，也無法稽核 | 全部補上並與配線架標籤一致 | ★★★ |
| err-disable 事件沒有告警 | ★★★★ 資安事件靜靜發生，沒人知道 | log 送 syslog 並設告警規則 | ★★★★ |
| 對 `udld` 開自動恢復 | ★★★★ 半殘鏈路反覆加入拓樸 | 只對 bpduguard／psecure-violation 等開自動恢復 | ★★★★ |
| 用 802.1X 才是完整解 | port-security 只認 MAC，MAC 可以偽造 | ★★★ 高安全需求應導入 802.1X（超出本篇範圍） | ★★★ |

★★★ port-security 是「提高門檻」不是「絕對防護」——
MAC 位址可以偽造，攻擊者只要抄一台合法機器的 MAC 就能繞過。
★★★★ 真正的埠級認證是 **802.1X**（結合 RADIUS 與使用者身分），
但導入成本高、對舊設備相容性差，機關環境通常先做好本篇的基本功。

## 速查表

| 指令 / 設定項 | 說明 | 範例 |
| --- | --- | --- |
| `description <文字>` | ★★★★ 埠用途（最有價值的一行） | `description USER-3F-014` |
| `shutdown` / `no shutdown` | 關閉／啟用埠 ★★★★ | `SW(config-if)#shutdown` |
| `speed {10\|100\|1000\|auto}` | ★★★★ 速率（**建議留 auto**） | `SW(config-if)#speed 100` |
| `duplex {half\|full\|auto}` | ★★★★★ 雙工（**建議留 auto**） | `SW(config-if)#duplex full` |
| `no speed` / `no duplex` | ★★★★ 改回自動協商 | `SW(config-if)#no duplex` |
| `show interfaces status` | ★★★★ 一覽（`a-` 前綴＝協商而來） | `SW#show int status \| include half` |
| `show interfaces <埠> \| include duplex\|collision` | ★★★★★ 查雙工不一致 | `SW#show int gi1/0/9 \| in late` |
| `show interfaces counters errors` | ★★★★ 錯誤計數（Late-Col 是鐵證） | `SW#show int counters errors` |
| `clear counters <埠>` | ★★★★ 歸零後觀察增量 | `SW#clear counters gi1/0/9` |
| `show interfaces description` | 埠描述一覽 ★★★ | `SW#show int desc` |
| `switchport port-security` | ★★★★ **啟用主指令**（不打其他都不生效） | `SW(config-if)#switchport port-security` |
| `switchport port-security maximum <n>` | ★★★★ 最多幾個 MAC | `... maximum 3` |
| `switchport port-security violation restrict` | ★★★★ 丟棄＋log＋不關埠（建議） | `... violation restrict` |
| `switchport port-security violation shutdown` | ★★★ err-disable（高安全區） | `... violation shutdown` |
| `switchport port-security violation protect` | ★★★★ 靜默丟棄（**不建議**，無記錄） | `... violation protect` |
| `switchport port-security mac-address sticky` | ★★★★ 學到的 MAC 寫進 running-config | `... mac-address sticky` |
| `switchport port-security aging type inactivity` | ★★★ 閒置才老化（預設是 absolute） | `... aging type inactivity` |
| `show port-security` | ★★★★ 所有受保護埠的一覽 | `SW#show port-security` |
| `show port-security interface <埠>` | ★★★★ 單埠詳情與違規計數 | `SW#show port-security int gi1/0/1` |
| `show port-security address` | 已學到的安全 MAC ★★★ | `SW#show port-security address` |
| `clear port-security sticky interface <埠>` | ★★★★ 清掉 sticky 重新學（換電腦時用） | `SW#clear port-security sticky int gi1/0/1` |
| `spanning-tree portfast` | ★★★ access 埠免除 30 秒等待 | `SW(config-if)#spanning-tree portfast` |
| `spanning-tree portfast trunk` | ★★★ trunk 埠接單一裝置（AP） | `... portfast trunk` |
| `spanning-tree portfast default` | ★★★ 全域（只對 access 埠） | `SW(config)#spanning-tree portfast default` |
| `spanning-tree bpduguard enable` | ★★★★ 收到 BPDU 就 err-disable | `... bpduguard enable` |
| `spanning-tree bpduguard default` | ★★★★ 全域（對所有 portfast 埠） | `SW(config)#spanning-tree bpduguard default` |
| `spanning-tree bpduguard disable` | 個別埠例外（上行 trunk） ★★★ | `... bpduguard disable` |
| `spanning-tree guard root` | ★★★ 防下游搶 root bridge | `SW(config-if)#spanning-tree guard root` |
| `show spanning-tree summary` | ★★★★ 全域保護機制狀態 | `SW#show spanning-tree summary` |
| `show interfaces status err-disabled` | ★★★★ 哪些埠被關了、為什麼 | `SW#show int status err-disabled` |
| `errdisable recovery cause <原因>` | ★★★ 啟用自動恢復 | `SW(config)#errdisable recovery cause bpduguard` |
| `errdisable recovery interval 600` | 自動恢復等待秒數 ★★★ | `SW(config)#errdisable recovery interval 600` |
| `show errdisable recovery` | 自動恢復狀態與倒數 ★★★ | `SW#show errdisable recovery` |
| `storm-control broadcast level 5.00 3.00` | ★★★ 廣播抑制門檻 | `SW(config-if)#storm-control broadcast level 5.00 3.00` |
| `storm-control action trap` | ★★★ 只告警不關埠 | `... action trap` |
| `show storm-control broadcast` | ★★★★ 各埠廣播佔比 | `SW#show storm-control broadcast` |
| `no cdp enable`（介面下） | ★★★★ 使用者埠關 CDP | `SW(config-if)#no cdp enable` |
| `ip dhcp snooping` ＋ `vlan <list>` | ★★★★ 防惡意 DHCP | `SW(config)#ip dhcp snooping vlan 30,40` |
| `ip dhcp snooping trust` | ★★★★★ **只有上行埠設** | `SW(config-if)#ip dhcp snooping trust` |
| `no ip dhcp snooping information option` | ★★★★ 不關會導致 DHCP 全失效 | `SW(config)#no ip dhcp snooping information option` |
| `default interface <埠>` | ★★★★ 打回原廠（會斷網） | `SW(config)#default int gi1/0/8` |
| `write memory` | ★★★★★ sticky MAC 必須存檔 | `SW#wr` |

## 練習題

> [!question]- 練習 1：從錯誤計數判斷問題
> 以下是三個埠的錯誤計數，分別判斷各自最可能的問題與處理方向。
>
> ```cisco
> Port        Align-Err     FCS-Err    Xmit-Err     Rcv-Err  UnderSize  OutDiscards
> Gi1/0/3             0           0           0           0          0        8421
> Gi1/0/7          1204        4412           0        5616          0           0
> Gi1/0/11          322        3891           0        4213          0           0
>
> Port        Single-Col  Multi-Col   Late-Col  Excess-Col  Carri-Sen       Runts
> Gi1/0/3              0          0          0           0          0           0
> Gi1/0/7              0          0          0           0          0           0
> Gi1/0/11         12441       2891       8891         421          0        8104
> ```
>
> **參考解答**
>
> | 埠 | 判斷 | 處理 |
> | --- | --- | --- |
> | Gi1/0/3 | ★★ **只有 `OutDiscards`，沒有任何錯誤** —— 這不是錯誤，是**擁塞**（送出佇列滿了） | 看該埠的流量是否長期接近滿載；考慮升速或做 QoS。不是實體層問題 |
> | Gi1/0/7 | ★★★★ `Align-Err` ＋ `FCS-Err` 高，但**沒有碰撞、沒有 Runts** → 全雙工下的**訊框損毀**，指向**線材／接頭／干擾** | 換一條測試線；檢查線是否與電源線平行走線、是否超過 100m、接頭是否氧化 |
> | Gi1/0/11 | ★★★★★ `Late-Col 8891` ＋ 大量 `Runts` ＋ 各種碰撞 → **雙工不一致** | `show interfaces gi1/0/11` 確認是 `Half-duplex`；查兩端設定，統一為 auto 或統一寫死 |
>
> ★★★★ 關鍵區分：**有 `Late-Col` 就是雙工問題；只有 `Align`/`FCS` 就是實體層問題；
> 只有 `OutDiscards` 就是頻寬問題。**

> [!question]- 練習 2：port-security 的完整演練
> 在測試機上對一個埠設定 port-security（`maximum 1`、`violation restrict`、`sticky`），
> 接上一台機器讓它學到 MAC，然後換另一台機器接上去，記錄發生什麼。
> 最後說明要怎麼讓新機器能用。
>
> **參考解答**
>
> ```cisco
> SW(config)#interface gi1/0/5
> SW(config-if)#switchport mode access
> SW(config-if)#switchport access vlan 30
> SW(config-if)#switchport port-security
> SW(config-if)#switchport port-security maximum 1
> SW(config-if)#switchport port-security violation restrict
> SW(config-if)#switchport port-security mac-address sticky
> SW(config-if)#end
>
> !-- 接上第一台機器，等它送出流量
> SW#show port-security address
>   30    0050.56a1.2b3c    SecureSticky             Gi1/0/5           -
>
> !-- 換第二台機器
> SW#
> *Sep  2 ...: %PORT_SECURITY-2-PSECURE_VIOLATION: Security violation occurred,
> caused by MAC address b827.eb11.2233 on port GigabitEthernet1/0/5.
>
> SW#show port-security interface gi1/0/5 | include Violation|Last Source
> Violation Mode             : Restrict
> Last Source Address:Vlan   : b827.eb11.2233:30
> Security Violation Count   : 1
> ```
>
> ★★★ 埠仍是 `Secure-up`（restrict 模式不關埠），但第二台機器**無法通訊**。
>
> **讓新機器能用**（三種方式）：
>
> ```cisco
> !-- 方式 A：清掉舊的 sticky MAC，重新學（★★★★ 最常用）
> SW#clear port-security sticky interface GigabitEthernet1/0/5
>
> !-- 方式 B：只刪掉特定的舊 MAC
> SW(config-if)#no switchport port-security mac-address sticky 0050.56a1.2b3c
>
> !-- 方式 C：提高上限（★★★ 若真的要兩台共用）
> SW(config-if)#switchport port-security maximum 2
> ```
>
> ★★★★★ 處理完記得 `write memory`。

> [!question]- 練習 3：模擬私接交換器
> 在測試環境把一台交換器接到另一台的 access 埠上（該埠已設 portfast ＋ bpduguard），
> 觀察 log 與埠狀態，然後完成完整的恢復流程。
>
> **參考解答**
>
> ```cisco
> SW-3F-01#
> *Sep  2 10:14:22.331: %SPANTREE-2-BLOCK_BPDUGUARD: Received BPDU on port
> GigabitEthernet1/0/12 with BPDU Guard enabled. Disabling port.
> *Sep  2 10:14:22.339: %PM-4-ERR_DISABLE: bpduguard error detected on Gi1/0/12,
> putting Gi1/0/12 in err-disable state
> *Sep  2 10:14:23.345: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/12, changed
> state to down
>
> SW-3F-01#show interfaces status err-disabled
> Port      Name               Status       Reason               Err-disabled Vlans
> Gi1/0/12  USER-3F-012        err-disabled bpduguard
> ```
>
> **完整恢復流程**：
>
> ```cisco
> !-- ① 確認原因（已完成）
> !-- ② ★★★★★ 排除肇因：實際去把那台交換器拔掉
> !-- ③ 才恢復
> SW-3F-01#configure terminal
> SW-3F-01(config)#interface GigabitEthernet1/0/12
> SW-3F-01(config-if)#shutdown
> SW-3F-01(config-if)#no shutdown
> SW-3F-01(config-if)#end
>
> !-- ④ 驗證
> SW-3F-01#show interfaces status | include Gi1/0/12
> Gi1/0/12  USER-3F-012        connected    30         a-full a-1000 10/100/1000BaseTX
> SW-3F-01#show mac address-table interface gi1/0/12
>   30    0050.56a1.2b3c    DYNAMIC     Gi1/0/12
> Total Mac Addresses for this criterion: 1
> ```
>
> ★★★★★ 若跳過第 ② 步，埠會在 `no shutdown` 後幾秒內再次 err-disable。

> [!question]- 練習 4：設計未用埠的處理標準
> 為你的機關寫一份「未使用網路埠的處理標準」，說明每一項措施防的是什麼，
> 並寫出可以驗證是否落實的指令。
>
> **參考解答**
>
> | 措施 | 防什麼 | 星級 |
> | --- | --- | --- |
> | `description UNUSED-DO-NOT-PATCH` | ★★★ 讓下一個人知道這是刻意保留的，不要隨手接 | ★★★ |
> | `switchport mode access` ＋ `switchport nonegotiate` | ★★★★ 防被協商成 trunk | ★★★★ |
> | `switchport access vlan 999` | ★★★★ 就算被 `no shutdown` 也只落在死路 VLAN | ★★★★ |
> | `shutdown` | ★★★★ 接上線也不會 up | ★★★★ |
> | 配線架端也標「未使用」 | ★★★ 實體端的第一道防線 | ★★★ |
>
> **驗證指令**：
>
> ```cisco
> !-- ① 所有 disabled 的埠都在 VLAN 999
> SW#show interfaces status | include disabled
>
> !-- ② VLAN 1 上沒有任何埠
> SW#show vlan brief | begin ^1
>
> !-- ③ 沒有埠處於 dynamic 模式
> SW#show interfaces switchport | include Name:|Administrative Mode
>
> !-- ④ VLAN 999 沒有 SVI（確認它真的是死路）
> SW#show ip interface brief | include Vlan999
> ```
>
> ★★★★ 第 ④ 項最容易被忽略：如果有人給 VLAN 999 建了 SVI 或把它加進 trunk 的
> allowed list，它就不再是死路了。

> [!question]- 練習 5：接入層交換器的完整埠設定範本
> 寫出一份可以直接套用到新交換器的埠設定範本，涵蓋使用者埠、IP 電話埠、
> AP 埠、未用埠、上行埠五種，並附驗收指令。
>
> **參考解答**
>
> ```cisco
> ! ===== 全域保護 =====
> spanning-tree mode rapid-pvst
> spanning-tree portfast default
> spanning-tree bpduguard default
> errdisable recovery cause bpduguard
> errdisable recovery cause psecure-violation
> errdisable recovery cause storm-control
> errdisable recovery interval 600
> ip dhcp snooping
> ip dhcp snooping vlan 30,40
> no ip dhcp snooping information option
> !
> ! ===== 使用者埠（Gi1/0/1-16）=====
> interface range GigabitEthernet1/0/1 - 16
>  description USER-3F-PORT
>  switchport mode access
>  switchport access vlan 30
>  switchport nonegotiate
>  switchport port-security
>  switchport port-security maximum 3
>  switchport port-security violation restrict
>  switchport port-security mac-address sticky
>  switchport port-security aging time 480
>  switchport port-security aging type inactivity
>  storm-control broadcast level 5.00 3.00
>  storm-control action trap
>  ip dhcp snooping limit rate 15
>  no cdp enable
>  spanning-tree portfast
>  spanning-tree bpduguard enable
>  no shutdown
> !
> ! ===== IP 電話埠（Gi1/0/19-20）=====
> interface range GigabitEthernet1/0/19 - 20
>  description IPPHONE-3F-PC
>  switchport mode access
>  switchport access vlan 30
>  switchport voice vlan 50
>  switchport nonegotiate
>  switchport port-security
>  switchport port-security maximum 3
>  switchport port-security violation restrict
>  switchport port-security mac-address sticky
>  spanning-tree portfast
>  spanning-tree bpduguard enable
>  no shutdown
> !         ★★★ 注意：這裡【保留】CDP，電話靠它取得 voice VLAN
> !
> ! ===== AP 埠（Gi1/0/17-18）=====
> interface range GigabitEthernet1/0/17 - 18
>  description AP-3F-TRUNK
>  switchport trunk native vlan 20
>  switchport trunk allowed vlan 20,40
>  switchport mode trunk
>  switchport nonegotiate
>  spanning-tree portfast trunk
>  spanning-tree bpduguard enable
>  no shutdown
> !
> ! ===== 未用埠（Gi1/0/21-23）=====
> interface range GigabitEthernet1/0/21 - 23
>  description UNUSED-DO-NOT-PATCH
>  switchport mode access
>  switchport access vlan 999
>  switchport nonegotiate
>  shutdown
> !
> ! ===== 上行 trunk（Gi1/0/24）=====
> interface GigabitEthernet1/0/24
>  description UPLINK-TO-SW-DIST-01-Gi1/0/8
>  switchport trunk native vlan 999
>  switchport trunk allowed vlan 20,30,40,50,99
>  switchport mode trunk
>  switchport nonegotiate
>  ip dhcp snooping trust
>  spanning-tree bpduguard disable
>  spanning-tree guard root
>  no shutdown
> ```
>
> **驗收指令**：
>
> ```cisco
> show interfaces status | include half
> show interfaces status err-disabled
> show interfaces status | include disabled
> show vlan brief | begin ^1
> show port-security
> show spanning-tree summary | include Portfast|BPDU
> show ip dhcp snooping
> show interfaces description
> show interfaces counters errors
> ```
>
> ★★★★★ 最後別忘了 `write memory`（sticky MAC 靠它）。
> 這份範本應存進 `_設定檔範例/`，見 [[040-01-18-guide-網路設備-網路設備盤點與文件化]]。

## 小測驗

Q1. 使用者說「網路很慢」，但你 ping 得到、`show interfaces status` 顯示 `connected`。
你會先看哪一個計數器？看到什麼數字代表什麼問題？

Q2. （選擇）造成雙工不一致最常見的原因是？
(A) 兩端都設 auto
(B) 兩端都寫死 100/full
(C) 一端寫死 100/full、另一端 auto
(D) 線材品質太差

Q3. （是非）`spanning-tree portfast` 可以單獨使用，
`bpduguard` 只是額外的加強，可有可無。

Q4. 這行指令會發生什麼事？
`SW(config)#spanning-tree bpdufilter default`
為什麼絕對不該用它來消除 bpduguard 的告警？

Q5. （簡答）`port-security` 的三種違規模式差在哪？機關的一般辦公區該選哪一種？為什麼？

Q6. 你設了 `switchport port-security mac-address sticky` 並確認 MAC 學到了。
一週後跳電，設備重開，結果所有埠的 MAC 名單都不見了。原因是什麼？

Q7. IP 電話後面串接電腦的埠，`port-security maximum` 設 1 會發生什麼？該設多少？

Q8. 未用埠的處理，為什麼「只做 `shutdown`」和「只丟黑洞 VLAN」都不夠？

Q9. 啟用 `ip dhcp snooping` 之後整層樓拿不到 IP。兩個最可能的原因是什麼？

Q10. （是非）對 `udld` 設定 `errdisable recovery cause udld` 是好習慣，
可以省下人工恢復的時間。

> [!question]- 測驗答案
> **Q1.** ★★★★★ 先看 **`late collision`**：
> ```cisco
> SW#show interfaces gi1/0/9 | include late collision
> ```
> 有持續上升的數字 ＝ **雙工不一致**（或線路超過 100m）。
> 這是「通但很慢」最典型的成因，而且 `show interfaces status` 上看起來完全正常。
> 佐證指標：大量 `Runts`、`Align-Err`、`FCS-Err`，以及該埠顯示 `Half-duplex`。
> 見「觀念說明 → `late collision` 是唯一的鐵證」。
>
> **Q2.** ★★★★★ **(C)**。一端寫死之後**不再送出協商訊號**，
> 另一端只能退回 parallel detection —— 那只偵測得到速率、偵測不到雙工，
> 於是自己選了 half duplex，形成 full ↔ half 的不一致。
> (A) 與 (B) 都是正確的組合。(D) 會造成 `FCS-Err`／`Align-Err`，
> 但不會產生 `late collision`。
> 見「觀念說明 → 自動協商」。
>
> **Q3.** ★★★★★ **否，兩者必須成對。**
> portfast 讓埠一插上就直接進 forwarding，**跳過了 STP 的 listening／learning**。
> 這代表如果有人在那個埠接了交換器並形成環路，
> **廣播風暴會在毫秒內爆發，STP 來不及阻止**。
> bpduguard 是 portfast 的配套安全網：收到 BPDU 就立刻關閉該埠，
> 把災害限制在一個埠。
> 見「觀念說明 → `portfast` 與 `bpduguard`」。
>
> **Q4.** ★★★★★ 它會**全域啟用 BPDU filter**：那些埠既不送也不收 BPDU，
> 等於**在那些埠上把 STP 徹底關掉**。
> 絕對不該用它來消除告警，因為：bpduguard 的告警代表「有人接了交換器」，
> 那是真實存在的問題；把 bpdufilter 打開之後告警確實消失了，
> 但那台交換器仍然接著，而且**現在沒有任何機制能偵測或阻止環路** ——
> 下一次形成環路時就是整棟樓的廣播風暴。
> 正確做法是**去找出並移除那台私接的設備**。
> 見「觀念說明 → `portfast` 與 `bpduguard`」的 warning 區塊。
>
> **Q5.** ★★★★
> | 模式 | 違規流量 | 埠狀態 | 產生 log |
> | --- | --- | --- | --- |
> | `protect` | 靜默丟棄 | 保持 up | ★★★★ **不產生** |
> | `restrict` | 丟棄 | 保持 up | 產生 syslog ＋ SNMP trap |
> | `shutdown`（預設） | — | err-disabled | 產生 |
>
> **一般辦公區選 `restrict`**：違規機器上不了網（達到安全目的），
> 但埠不會關閉，**同一埠上原本合法的機器不受影響**
> （IP 電話 ＋ 電腦的場景很重要），而且有 log 可查。
> ★★★★★ **不要用 `protect`** —— 它不留任何記錄，
> 使用者報修時你完全查不到原因。
> 見「觀念說明 → `port-security`」。
>
> **Q6.** ★★★★★ 因為 **sticky 學到的 MAC 寫進的是 `running-config`（RAM）**，
> 沒有 `write memory` 就不會進 startup-config，掉電即消失。
> 更危險的是：重開後埠會重新開始學習，
> **這時插在那個埠上的任何機器都會被當成合法的**，等於保護完全失效。
> 設完 port-security 一定要立刻 `write memory`。
> 見「觀念說明 → `sticky` 的陷阱」。
>
> **Q7.** ★★★★ 電腦會被擋掉（或電話被擋掉，取決於誰先送出流量）。
> IP 電話本身佔一個 MAC（在 voice VLAN），
> 後面串接的電腦佔一個 MAC（在 data VLAN），
> ★★★ 部分電話型號的內建交換器晶片還會多出一個 MAC。
> **應設 `maximum 3`**（2 個必要 ＋ 1 個緩衝）。
> 見「基礎設定 → 步驟 6」。
>
> **Q8.** ★★★★
> - **只做 `shutdown`**：有人為了急用（「我只要接一下」）打了 `no shutdown`，
>   那個埠會落在 **VLAN 1** —— 直通內網。
> - **只丟黑洞 VLAN**：埠是 up 的，任何人接上就有連線
>   （雖然在死路 VLAN 裡，但至少能做 L2 層的探測，且哪天有人把 VLAN 999
>   加進 trunk allowed list 就破功了）。
> - **兩者都做**：就算有人 `no shutdown`，也只會落在死路 VLAN，兩層防護。
>
> ★★★ 另外要確認 VLAN 999 真的是死路：沒有 SVI、不在任何 trunk 的 allowed list。
> 見「基礎設定 → 步驟 4」。
>
> **Q9.** ★★★★★
> ① **上行埠沒設 `ip dhcp snooping trust`** ——
> 合法的 DHCP OFFER 從不受信任的埠進來，全部被丟棄。
> ② **Option 82 沒關** —— IOS 預設會插入 Option 82，
> 但交換器本身不是 relay agent，多數 DHCP 伺服器會丟棄這種請求。
> 解法：`ip dhcp snooping trust`（只在上行埠）＋
> `no ip dhcp snooping information option`。
> ★★★★ 這兩個坑都會造成大範圍斷網，導入時務必先 `reload in 10`。
> 見「進階設定與調校 → DHCP snooping」。
>
> **Q10.** ★★★★★ **否，這是危險的做法。**
> UDLD 偵測到的是**實體層的單向連線**（例如光纖有一芯斷了、
> SFP 的收發模組壞了一邊）。這種故障不會自己好。
> 自動恢復只會讓一條半殘的鏈路反覆加入拓樸 →
> STP 反覆重新計算 → 網路持續不穩，而且**掩蓋了真正需要換料件的事實**。
> UDLD 觸發的 err-disable 應該保持人工介入，去現場檢查光纖與模組。
> 自動恢復適合用在 `bpduguard`、`psecure-violation`、`storm-control`
> 這種「肇因移除後就會恢復正常」的情況。
> 見「進階設定與調校 → `errdisable recovery`」。

## 延伸閱讀

- [[040-01-14-svc-Cisco-設定備份與韌體升級]] —— 把這些設定備份起來、以及 IOS 升級
- [[040-01-11-guide-Cisco-VLAN與Trunk設定]] —— 黑洞 VLAN、DTP、trunk 設定
- [[040-01-12-guide-Cisco-管理IP與遠端存取]] —— 管理平面的安全基線
- [[040-01-08-guide-Juniper-埠設定與安全]] —— 主線平台的做法
- [[040-01-15-cmd-網路設備-Juniper與Cisco指令對照]] —— 兩邊指令一頁式對照
- [[040-01-16-guide-網路設備-鏈路聚合與STP]] —— STP 的埠狀態、root guard、loop guard
- [[040-01-17-guide-網路設備-交換器故障排除]] —— 系統化的排錯流程
- [[010-02-04-guide-網概-線材與實體層]] —— 線材等級、長度限制與干擾
- [[040-02-08-guide-機房-結構化佈線與標籤規範]] —— description 要與配線架標籤一致
- [[040-02-10-guide-機房-機房巡檢與紀錄]] —— 把本篇的八行巡檢納入月檢
- [[100-01-03-guide-日誌-系統監控與告警]] —— err-disable 事件的告警設定
