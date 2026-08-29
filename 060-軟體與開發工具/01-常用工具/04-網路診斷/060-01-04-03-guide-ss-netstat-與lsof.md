---
title: "ss、netstat 與 lsof"
desc: "連線狀態、監聽埠、檔案描述符的查詢與判讀"
aliases: [ss, netstat, lsof, TIME_WAIT, CLOSE_WAIT, 連線數, 埠佔用]
tags: [群組/軟體與開發工具, 主題/網路診斷, 主題/連線]
category: 常用工具
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-01-16-cmd-Linux-網路基礎指令]]"]
updated: 2026-08-28
---

# ss、netstat 與 lsof

> [!abstract] 這篇你會學到
> - **★★★ `ss` 取代 `netstat`** 的理由與對照表
> - **★★★★ TCP 狀態機**與每個狀態代表的問題
> - **★★★★ `TIME_WAIT` 和 `CLOSE_WAIT` 的差別**（最常被誤解）
> - `-Send-Q` / `Recv-Q` 的判讀
> - **★★★ `lsof`** —— 誰開著這個檔案／誰佔用這個埠
> - **★★★ 檔案描述符用盡**的排查與調整
> - **★★ 連線數上限**的三層設定

## 前置知識

- [[020-01-16-cmd-Linux-網路基礎指令]] — `ip`、基本網路概念
- [[020-01-10-cmd-Linux-程序管理與訊號]] — 程序與 PID

---

## ★★★ ss 取代 netstat

```
★★★ netstat 已經被淘汰（★ net-tools 套件多年沒維護）

  netstat  → ★★ 讀 /proc/net/tcp 這種【文字檔】
             → ★★★ 幾萬條連線時要 parse 幾 MB 的文字 → 很慢
             → ★ 有些新發行版預設沒裝

  ss       → ★★★★ 直接用 netlink socket 跟核心要資料
             → ★★★ 快 10 倍以上
             → ★★ 能顯示 netstat 看不到的資訊（★ TCP 內部狀態）
```

| netstat | **★★★ ss** | 說明 |
| --- | --- | --- |
| `netstat -tulnp` | **`ss -tulnp`** | **★★★ 監聽中的 TCP/UDP** |
| `netstat -tanp` | **`ss -tanp`** | 所有 TCP 連線 |
| `netstat -s` | `ss -s` | 統計摘要 |
| `netstat -r` | `ip route` | 路由表 |
| `netstat -i` | `ip -s link` | 介面統計 |
| `netstat -tan \| grep :80` | **`ss -tan 'sport = :80'`** | **★★★ 用內建過濾更快** |

```bash
# ★★★ 安裝（★ ss 在 iproute2，幾乎一定有）
$ ss --version
ss utility, iproute2-6.1.0

$ sudo apt install -y net-tools     # ★ 如果真的需要 netstat
$ sudo apt install -y lsof
```

---

## ★★★ ss 常用選項

| 選項 | 作用 |
| --- | --- |
| **`-t`** | TCP |
| **`-u`** | UDP |
| **`-x`** | **★★ Unix domain socket** |
| **`-l`** | **★★★ 只看監聽中的** |
| **`-a`** | 全部（含監聽與非監聽） |
| **`-n`** | **★★★ 不解析名稱**（★ 快很多） |
| **`-p`** | **★★★ 顯示程序**（需要 root） |
| **`-s`** | **★★ 統計摘要** |
| **`-i`** | **★★★ TCP 內部資訊**（RTT、cwnd、重傳） |
| `-e` | 詳細（含 inode、uid） |
| `-m` | ★★ 記憶體用量 |
| `-o` | ★★ 計時器資訊 |
| `-4` / `-6` | 只看 IPv4 / IPv6 |
| **`-K`** | **★★★ 強制關閉 socket**（需要 root） |

```bash
# ═══ ★★★★ 最常用的三個 ═══
$ sudo ss -tulnp                # ★★★★ 有哪些服務在監聽（★ 最常用）
$ sudo ss -tanp                 # ★★ 所有 TCP 連線
$ ss -s                         # ★★ 快速統計
```

```bash
$ sudo ss -tulnp
Netid State  Recv-Q Send-Q  Local Address:Port   Peer Address:Port  Process
udp   UNCONN 0      0             0.0.0.0:68          0.0.0.0:*    users:(("dhclient",pid=890,fd=6))
tcp   LISTEN 0      511           0.0.0.0:80          0.0.0.0:*    users:(("nginx",pid=1234,fd=6))
tcp   LISTEN 0      511           0.0.0.0:443         0.0.0.0:*    users:(("nginx",pid=1234,fd=8))
tcp   LISTEN 0      511         127.0.0.1:9000        0.0.0.0:*    users:(("php-fpm",pid=1200,fd=7))
tcp   LISTEN 0      80          127.0.0.1:3306        0.0.0.0:*    users:(("mysqld",pid=5678,fd=25))
tcp   LISTEN 0      128           0.0.0.0:22          0.0.0.0:*    users:(("sshd",pid=890,fd=3))
```

```
★★★★ 這一份輸出的三個檢查重點：

【① Local Address —— 綁在哪】
  0.0.0.0:443    ★★ 所有介面（★ 對外服務應該是這個）
  127.0.0.1:9000 ★★★ 只有本機（★ php-fpm、資料庫應該是這個）
  127.0.0.1:3306 ★★★★ 資料庫【正確】只綁本機
  ★★★★ 如果看到 0.0.0.0:3306 → 資料庫對外開放！立刻處理

【② Send-Q（LISTEN 狀態時）—— ★★★ backlog 上限】
  511  ← nginx 的 listen backlog
  80   ← ★★ mysqld 的（比較小）
  → ★★★ 這是「還沒被 accept 的連線」能排隊的最大數量

【③ Recv-Q（LISTEN 狀態時）—— ★★★★ 目前排隊中的連線】
  0    ★ 正常
  >0   ★★★★ 有連線在等待被接受 → 應用程式忙不過來！
```

```bash
# ★★★★ 檢查對外開放的服務（★ 資安稽核必做）
$ sudo ss -tulnp | awk '$5 ~ /^(0\.0\.0\.0|\[::\]|\*)/ {print}'
tcp LISTEN 0 511 0.0.0.0:80   0.0.0.0:* users:(("nginx",pid=1234,fd=6))
tcp LISTEN 0 511 0.0.0.0:443  0.0.0.0:* users:(("nginx",pid=1234,fd=8))
tcp LISTEN 0 128 0.0.0.0:22   0.0.0.0:* users:(("sshd",pid=890,fd=3))
#   ★★★ 只有這三個對外 → 正確
#   ★★★★ 出現 3306 / 6379 / 9000 / 5432 就是設定錯誤

# ★★ 一行檢查腳本
$ sudo ss -tlnp | awk 'NR>1 && $4 !~ /^127\.|^\[::1\]/ {
    split($4,a,":"); printf "★ %-6s %s\n", a[length(a)], $NF}'
```

---

## ★★★★ TCP 狀態機

```
★★★★ 完整的 TCP 狀態轉換：

  【建立連線】
    CLOSED
      │ 主動連線                          │ 被動監聽
      ▼                                   ▼
    SYN_SENT ──────────────────────────► LISTEN
      │  ◄──── SYN-ACK ──────────────  SYN_RECV
      ▼                                   │
    ESTABLISHED ◄──────────────────────► ESTABLISHED
                    ★★★ 正常傳輸中

  【關閉連線】★★★★ 這裡是重點
    主動關閉方                      被動關閉方
      │ 送 FIN                          │
      ▼                                 ▼
    FIN_WAIT_1  ─── FIN ──────────►  ★★★★ CLOSE_WAIT
      │ ◄──── ACK ─────────────────      │
      ▼                                  │ ★★★ 應用程式要呼叫 close()
    FIN_WAIT_2                           ▼
      │ ◄──── FIN ─────────────────  LAST_ACK
      ▼ 送 ACK ────────────────────►     │
    ★★★★ TIME_WAIT                       ▼
      │ 等 2×MSL（★ Linux 是 60 秒）    CLOSED
      ▼
    CLOSED
```

| 狀態 | 意義 | **★ 大量出現代表什麼** |
| --- | --- | --- |
| `LISTEN` | 監聽中 | 正常 |
| `SYN_SENT` | 送了 SYN 等回應 | **★★ 大量 = 連不到對方**（防火牆/服務掛了） |
| `SYN_RECV` | 收到 SYN 回了 SYN-ACK | **★★★★ 大量 = SYN flood 攻擊** |
| **`ESTABLISHED`** | **正常連線中** | ★ 看數量是否合理 |
| `FIN_WAIT_1` | 送了 FIN 等 ACK | ★ 少量正常 |
| `FIN_WAIT_2` | 收到 ACK 等對方 FIN | **★★ 大量 = 對方不關閉** |
| **`TIME_WAIT`** | **★★★★ 主動關閉方等待** | **★★ 通常不是問題**（見下） |
| **`CLOSE_WAIT`** | **★★★★ 被動關閉方沒呼叫 close()** | **★★★★ 一定是程式 bug！** |
| `LAST_ACK` | 送了 FIN 等最後的 ACK | ★ 少量正常 |
| `CLOSING` | 雙方同時關閉 | ★ 罕見 |

```bash
# ★★★ 統計各狀態的數量
$ ss -tan | awk 'NR>1 {c[$1]++} END {for(s in c) printf "%-14s %d\n", s, c[s]}' | sort -k2 -rn
ESTAB          842
TIME-WAIT      12840                # ★★ 很多，但通常正常
LISTEN         12
CLOSE-WAIT     284                  # ★★★★ 這個才是問題！
SYN-RECV       2
FIN-WAIT-2     18

# ★ netstat 版本
$ netstat -ant | awk 'NR>2 {c[$6]++} END {for(s in c) print s, c[s]}' | sort -k2 -rn
```

### ★★★★ TIME_WAIT vs CLOSE_WAIT

```
★★★★ 這是最常被搞混、也最重要的一組差別：

┌─────────────────────────────────────────────────────────────┐
│ ★★★ TIME_WAIT —— 【主動關閉的一方】                          │
│                                                              │
│  · 出現在【先送 FIN 的那一端】                                │
│  · ★★ 這是 TCP 協定【設計上必要】的狀態                       │
│    → 等 2×MSL（Linux 預設 60 秒）確保：                       │
│      ① 對方的最後 ACK 有收到（★ 否則要重送 FIN）              │
│      ② ★★ 舊連線的延遲封包不會污染新連線                       │
│  · ★★★ 大量 TIME_WAIT 【通常不是問題】                        │
│    → 每個只佔幾十 bytes，60 秒後自動消失                      │
│  · ★★★★ 只有在【本機埠用盡】時才是問題                        │
│    → 症狀：Cannot assign requested address                   │
│                                                              │
│  ★★★ 解法（★ 有優先順序）：                                   │
│    ① ★★★★ 用【連線池 / keepalive】（★ 治本）                  │
│    ② 調 net.ipv4.ip_local_port_range                         │
│    ③ ★★ net.ipv4.tcp_tw_reuse = 1（★ 客戶端安全）             │
│    ④ ★★★★ 絕對不要用 tcp_tw_recycle（★ 已從核心移除）         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ ★★★★ CLOSE_WAIT —— 【被動關閉的一方】                        │
│                                                              │
│  · 出現在【收到 FIN 的那一端】                                │
│  · ★★★★ 意思是：對方說「我關了」，                            │
│    但【你的應用程式沒有呼叫 close()】                         │
│  · ★★★★ 這【一定是應用程式的 bug】！                          │
│    → 忘記 close()、例外處理沒關連線、連線池洩漏               │
│  · ★★★ 不會自動消失！會一直累積                               │
│    → ★★★★ 最後【檔案描述符用盡】→ 服務完全掛掉               │
│      Too many open files                                     │
│                                                              │
│  ★★★★ 解法：                                                 │
│    ① 找出是哪個程序（ss -tanp）                              │
│    ② ★★★ 修正程式碼（★ 用 try-finally / with / defer）        │
│    ③ ★★ 臨時：重啟該服務                                      │
│    ④ ★★★★ 調 sysctl 完全沒用！（★ 這不是核心的問題）          │
└─────────────────────────────────────────────────────────────┘
```

```bash
# ★★★★ 找出 CLOSE_WAIT 是哪個程序
$ sudo ss -tanp state close-wait
State      Recv-Q Send-Q  Local Address:Port  Peer Address:Port  Process
CLOSE-WAIT 1      0       10.10.20.31:44210   10.10.20.50:3306   users:(("php-fpm",pid=1234,fd=18))
CLOSE-WAIT 1      0       10.10.20.31:44212   10.10.20.50:3306   users:(("php-fpm",pid=1235,fd=19))
#                                                    ↑                        ↑
#   ★★★★ 連到資料庫的連線沒關                  ★★★ 就是 php-fpm

# ★★★ 統計哪個程序累積最多
$ sudo ss -tanp state close-wait | \
    grep -oP 'users:\(\("\K[^"]+' | sort | uniq -c | sort -rn
    284 php-fpm
     12 node

# ★★★ 對哪個目的地
$ sudo ss -tanp state close-wait | awk 'NR>1 {print $4}' | \
    awk -F: '{print $1":"$2}' | sort | uniq -c | sort -rn | head
    284 10.10.20.50:3306              # ★★★★ 都是資料庫連線

# ★★ 觀察是否持續增加（★ 確認是洩漏）
$ for i in $(seq 1 6); do
    printf "%s  CLOSE_WAIT=%s\n" "$(date +%H:%M:%S)" \
      "$(ss -tan state close-wait | wc -l)"
    sleep 30
  done
14:20:01  CLOSE_WAIT=284
14:20:31  CLOSE_WAIT=291
14:21:01  CLOSE_WAIT=298              # ★★★★ 一直增加 = 洩漏確認
```

```bash
# ★★★ TIME_WAIT 的正確處置
$ sysctl net.ipv4.ip_local_port_range
net.ipv4.ip_local_port_range = 32768	60999          # ★ 約 28000 個埠

$ ss -tan state time-wait | wc -l
28104                                                # ★★★★ 快用完了！

# ★★ 症狀
$ curl http://10.10.20.50/api
curl: (7) Failed to connect: Cannot assign requested address    # ★★★★ 埠用盡

# ═══ ★★★★ 解法一（治本）：連線池 / keepalive ═══
# nginx 對上游用 keepalive
upstream backend {
    server 10.10.20.50:8080;
    keepalive 64;                    # ★★★★ 保持 64 條長連線
    keepalive_timeout 60s;
    keepalive_requests 1000;
}
server {
    location / {
        proxy_pass http://backend;
        proxy_http_version 1.1;      # ★★★★ 必須！HTTP/1.0 不支援 keepalive
        proxy_set_header Connection ""; # ★★★★ 必須！清掉 Connection: close
    }
}

# ★★ PHP 的資料庫持久連線
#   PDO::ATTR_PERSISTENT => true
#   ★★★ 或用 Laravel 的 DB 連線池

# ═══ ★★ 解法二：擴大埠範圍 ═══
$ sudo sysctl -w net.ipv4.ip_local_port_range="10240 65535"
$ echo 'net.ipv4.ip_local_port_range = 10240 65535' | \
    sudo tee /etc/sysctl.d/60-net.conf

# ═══ ★★ 解法三：tcp_tw_reuse ═══
$ sudo sysctl -w net.ipv4.tcp_tw_reuse=1
#   ★★★ 允許重用 TIME_WAIT 的埠給【新的出向連線】
#   ★★ 只影響客戶端（主動連線方），伺服器端不受影響
#   ★ 需要 tcp_timestamps=1（預設開啟）

# ═══ ★★★★ 絕對不要做的 ═══
$ sudo sysctl -w net.ipv4.tcp_tw_recycle=1    # ★★★★ 危險！
#   → ★★★★ Linux 4.12 已經【移除這個參數】
#   → ★★★ 在 NAT 環境下會【隨機丟棄連線】
#     （★ 同一個 NAT 後面的不同客戶端時間戳不一致）
#   → ★★ 網路上很多舊文章還在教這個，不要照做
```

> [!danger] `tcp_tw_recycle` 是有害的建議 ★★★★
> ```
> ★★★★ 很多中文的「TCP 調優」文章會教你：
>   net.ipv4.tcp_tw_recycle = 1
>
> ★★★★ 這是【錯誤且有害】的：
>   · 它會依 TCP timestamp 判斷是否重用
>   · ★★★ NAT 後面的多個客戶端，時間戳彼此不同
>   · → ★★★★ 伺服器會【隨機拒絕】部分客戶端的連線
>   · 症狀：「有些人連得上，有些人連不上，而且會變」
>   · ★★★ 極難排查
>
> ★★★★ Linux 4.12（2017）已經【完全移除這個參數】
>   → 新系統設了也不會有效果
>   → ★ 但舊系統（CentOS 7）還有 → 一定要確認是 0
>
> $ sysctl net.ipv4.tcp_tw_recycle 2>/dev/null || echo "★ 已移除，安全"
> ```

### ★★★ Recv-Q 與 Send-Q

```
★★★★ 這兩欄的意義【依狀態不同】：

【LISTEN 狀態】
  Recv-Q = ★★★★ 目前【已完成交握但還沒被 accept()】的連線數
           → ★★★ > 0 就是應用程式忙不過來
  Send-Q = ★★★ backlog 的【上限】
           → min(應用程式的 listen() 參數, net.core.somaxconn)

【ESTABLISHED 狀態】
  Recv-Q = ★★★ 已收到但應用程式還沒讀取的資料量（bytes）
           → ★★★★ 持續 > 0 = 應用程式處理不過來
  Send-Q = ★★★ 已送出但對方還沒 ACK 的資料量
           → ★★★ 持續很大 = 網路慢或對方接收慢
```

```bash
# ★★★★ 檢查 accept 佇列是否積壓
$ ss -lnt
State  Recv-Q Send-Q Local Address:Port
LISTEN 0      511          0.0.0.0:443
LISTEN 48     511          0.0.0.0:80        # ★★★★ 48 個連線在等被 accept！
#      ↑
#   ★★★ nginx worker 忙不過來

# ★★★ 對照 overflow 統計
$ netstat -s | grep -iE 'listen'
    284 times the listen queue of a socket overflowed    # ★★★★ 有連線被丟棄
    284 SYNs to LISTEN sockets dropped
$ nstat -az | grep -iE 'ListenOverflows|ListenDrops'
TcpExtListenOverflows           284
TcpExtListenDrops               284

# ★★ 三層 backlog 設定（★ 三個都要調）
$ sysctl net.core.somaxconn                    # ★★★ 系統上限
net.core.somaxconn = 4096
$ sysctl net.ipv4.tcp_max_syn_backlog          # ★★ SYN 佇列
net.ipv4.tcp_max_syn_backlog = 2048

$ sudo tee /etc/sysctl.d/60-backlog.conf >/dev/null <<'EOF'
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.core.netdev_max_backlog = 16384
EOF
$ sudo sysctl --system

# ★★★ 應用層也要調（★ 三個都要，取最小值）
#   nginx:
#     listen 443 ssl backlog=8192;
#   php-fpm (pool.d/www.conf):
#     listen.backlog = 8192
#   ★★★★ 只調 sysctl 沒用，應用程式的 listen() 參數也要跟著改
$ ss -lnt 'sport = :443'         # ★★ 驗證 Send-Q 變大了

# ★★★ ESTABLISHED 的積壓
$ ss -tan state established | awk '$2>0 || $3>0'
ESTAB 65536  0      10.10.20.31:443  203.0.113.45:52134
#     ↑
#   ★★★★ 接收緩衝滿了，應用程式沒讀 → 應用層瓶頸
```

---

## ★★★ ss 的過濾語法

```bash
# ═══ ★★★ 依狀態 ═══
$ ss -tan state established
$ ss -tan state time-wait
$ ss -tan state close-wait               # ★★★★ 查程式 bug
$ ss -tan state syn-recv                 # ★★★ 查 SYN flood
$ ss -tan state connected                # ★★ 所有已連線的
$ ss -tan state bucket                   # time-wait + syn-recv
$ ss -tan state big                      # ★ 除了 listen/syn-recv/time-wait

# ═══ ★★★ 依埠 ═══
$ ss -tan 'sport = :443'                 # ★★ 來源埠
$ ss -tan 'dport = :3306'                # ★★★ 目的埠
$ ss -tan 'sport >= :8000 and sport <= :8100'
$ ss -tan '( dport = :80 or dport = :443 )'

# ═══ ★★ 依位址 ═══
$ ss -tan 'dst 10.10.20.50'
$ ss -tan 'dst 10.10.20.0/24'
$ ss -tan 'not dst 127.0.0.0/8'
$ ss -tan 'dst 10.10.20.50:3306'         # ★★ 位址 + 埠

# ═══ ★★★★ 組合 ═══
$ ss -tanp 'state close-wait and dst 10.10.20.50'
$ ss -tan 'state established and dport = :3306' | wc -l

# ═══ ★★★ 統計 ═══
$ ss -s
Total: 1284
TCP:   13842 (estab 842, closed 12840, orphaned 0, timewait 12840)
#                ↑                                    ↑
#         ★★ 正常連線                        ★★ TIME_WAIT（通常 OK）
Transport Total  IP  IPv6
TCP        1002  890  112
UDP        12    10   2

# ★★★ 每個對端的連線數（★ 找出誰連最多）
$ ss -tan state established | awk 'NR>1 {split($5,a,":"); print a[1]}' | \
    sort | uniq -c | sort -rn | head -10
    284 203.0.113.45                     # ★★★ 單一 IP 284 條連線！
     42 198.51.100.22

# ★★ 每個服務的連線數
$ sudo ss -tanp state established | grep -oP 'users:\(\("\K[^"]+' | \
    sort | uniq -c | sort -rn
    620 nginx
    142 php-fpm
     80 mysqld
```

### ★★★ `-i` 看 TCP 內部狀態

```bash
$ sudo ss -tani state established 'dst 203.0.113.45' | head -6
ESTAB 0 0  10.10.20.31:443  203.0.113.45:52134
     cubic wscale:7,7 rto:236 rtt:35.2/8.1 ato:40 mss:1448 pmtu:1500
     rcvmss:536 advmss:1448 cwnd:24 bytes_sent:482104 bytes_acked:482104
     bytes_received:12840 segs_out:842 segs_in:412 send 7.9Mbps
     lastsnd:24 lastrcv:1240 lastack:24 pacing_rate 15.8Mbps
     delivery_rate 6.2Mbps busy:4820ms retrans:0/12 rcv_space:14480

★★★ 關鍵欄位：
  rtt:35.2/8.1     ★★★ 往返時間 35.2ms（變異 8.1ms）
                   → ★★ 突然變大 = 網路品質變差
  retrans:0/12     ★★★★ 目前 0 / 累計 12 次重傳
                   → ★★★ 累計數大 = 遺失多
  cwnd:24          ★★ 擁塞視窗（★ 小 = 剛開始或遇到遺失）
  mss:1448         ★★ 協商的 MSS
  pmtu:1500        ★★★ 路徑 MTU
  send 7.9Mbps     ★★ 目前的傳送速率
  ★★ busy:4820ms  這條連線忙碌的時間
  ★★★ lastsnd/lastrcv  距離上次收送的毫秒數
                   → ★★★ 很大 = 連線閒置（★ 可能該關了）
```

```bash
# ★★★★ 找出高重傳的連線
$ sudo ss -tani state established | \
    grep -B1 -E 'retrans:[0-9]+/[1-9][0-9]{2,}' | head -20

# ★★★ 找出 RTT 異常的
$ sudo ss -tani state established | grep -oP 'rtt:\K[0-9.]+' | \
    sort -rn | head -5
420.8                                    # ★★★ 420ms！網路很差

# ★★★ 找出長時間閒置的連線
$ sudo ss -tanpi state established | grep -B2 -oP 'lastrcv:\K[0-9]{6,}' | head
```

---

## ★★★ lsof

```bash
# ═══ ★★★★ 誰佔用了這個埠（★ 最常用）═══
$ sudo lsof -i :8080
COMMAND   PID  USER  FD  TYPE DEVICE SIZE/OFF NODE NAME
node    12345 deploy  22u IPv4 892374      0t0  TCP *:8080 (LISTEN)

$ sudo ss -tlnp 'sport = :8080'          # ★★★ ss 更快
$ sudo fuser -n tcp 8080                 # ★ 另一個方法
8080/tcp:            12345

# ═══ ★★★ 一個程序開了哪些檔案 ═══
$ sudo lsof -p 1234 | head -20
$ sudo lsof -p 1234 | awk '{print $5}' | sort | uniq -c | sort -rn
    284 REG      # 一般檔案
    142 IPv4     # ★★ 網路連線
     18 DIR
      8 CHR

# ═══ ★★★ 誰開著這個檔案 ═══
$ sudo lsof /var/log/nginx/access.log
COMMAND  PID     USER  FD  TYPE DEVICE SIZE/OFF NODE NAME
nginx   1234 www-data  5w  REG  253,2  8240192  456 /var/log/nginx/access.log

# ★★★ 誰在用這個掛載點（★ 卸載前必查）
$ sudo lsof +D /mnt/data | head
$ sudo fuser -vm /mnt/data               # ★★ 更快

# ═══ ★★★★ 已刪除但還佔空間的檔案 ═══
$ sudo lsof +L1
COMMAND   PID  USER  FD  TYPE DEVICE  SIZE/OFF NLINK NODE NAME
mysqld   5678 mysql  12u REG  253,2  4294967296     0  123 /var/lib/mysql/ibtmp1 (deleted)
rsyslogd 8901  root   7w REG  253,2 98784247808     0  456 /var/log/huge.log (deleted)
#                                                    ↑
#   ★★★★ NLINK=0 = 已刪除，但檔案描述符還開著 → 空間沒釋放

# ★★ 依使用者 / 程序
$ sudo lsof -u www-data | wc -l
$ sudo lsof -c nginx | wc -l
$ sudo lsof -c nginx -a -i                # ★★ nginx 的網路連線（-a = AND）

# ═══ ★★ 網路連線 ═══
$ sudo lsof -i                            # 所有
$ sudo lsof -i TCP:443
$ sudo lsof -i @10.10.20.50               # ★★ 連到這個 IP 的
$ sudo lsof -i -sTCP:LISTEN               # ★★★ 只看監聽
$ sudo lsof -i -sTCP:ESTABLISHED -n -P    # ★★ -n -P 不解析（★ 快很多）
```

> [!tip] `lsof` 很慢時的替代方案 ★★★
> ```
> ★★★ lsof 會掃描 /proc 下【每一個程序的每一個 fd】
>   → 程序多時要好幾秒
>
> ★★★ 更快的替代：
>   查埠佔用：  ★★★★ sudo ss -tlnp 'sport = :8080'
>   查程序的 fd：ls -l /proc/PID/fd | head
>   查已刪除的： ★★ ls -l /proc/*/fd 2>/dev/null | grep deleted
>   查掛載點：  ★★ sudo fuser -vm /mnt/data
>
> ★★ lsof 一定要加 -n -P：
>   -n  不解析主機名
>   -P  不解析 port 名稱
>   → ★★★ 快 10 倍以上
> ```

---

## ★★★ 檔案描述符用盡

```
★★★★ 症狀：
  · nginx error.log:  accept4() failed (24: Too many open files)
  · PHP:              failed to open stream: Too many open files
  · ★★★ 服務突然完全無法接受新連線
  · ★★ 但既有連線還正常 → 很容易誤判成「網路問題」
```

```bash
# ═══ ★★★★ 三層限制（★ 三個都要看）═══

# ① ★★★ 系統總上限
$ cat /proc/sys/fs/file-nr
12840	0	9223372036854775807
#  ↑     ↑           ↑
# 已用  未使用    ★★ 上限（★ 現代核心通常很大）
$ sysctl fs.file-max

# ② ★★★★ 每個程序的上限（ulimit）
$ ulimit -n                              # ★ 目前 shell 的
1024
$ ulimit -Hn                             # 硬上限
524288

# ★★★★ 服務的實際限制（★ 不是你的 shell 的！）
$ cat /proc/1234/limits | grep -i 'open files'
Max open files            1024                 1024      files
#                          ↑ ★★★★ 這才是重點

# ③ ★★ 該程序目前用了多少
$ ls /proc/1234/fd | wc -l
1018                                     # ★★★★ 快到 1024 了！

# ═══ ★★★★ 一次檢查所有服務 ═══
$ for p in $(pgrep -d' ' -x 'nginx|php-fpm|mysqld|node'); do
    cmd=$(cat /proc/$p/comm 2>/dev/null) || continue
    cur=$(ls /proc/$p/fd 2>/dev/null | wc -l)
    max=$(awk '/Max open files/{print $4}' /proc/$p/limits 2>/dev/null)
    pct=$(awk -v c="$cur" -v m="$max" 'BEGIN{printf "%.0f", c/m*100}')
    printf "%-12s pid=%-7s %6s / %-8s (%s%%)" "$cmd" "$p" "$cur" "$max" "$pct"
    [ "$pct" -gt 80 ] && echo "  ★★★★ 危險" || echo ""
  done
nginx        pid=1234    1018 / 1024     (99%)  ★★★★ 危險
php-fpm      pid=1200     124 / 65536    (0%)
mysqld       pid=5678    2840 / 65536    (4%)
```

```bash
# ═══ ★★★★ 正確的調整方式（★ systemd 服務）═══

# ★★★★ 錯誤做法：改 /etc/security/limits.conf
#   → ★★★ 那只影響【透過 PAM 登入的 session】
#   → ★★★★ systemd 啟動的服務【完全不受影響】！

# ★★★ 正確做法一：systemd override
$ sudo systemctl edit nginx
[Service]
LimitNOFILE=65536

$ sudo systemctl daemon-reload && sudo systemctl restart nginx
$ cat /proc/$(pgrep -o nginx)/limits | grep -i 'open files'
Max open files            65536                65536     files    # ★★★ 生效

# ★★★ 正確做法二：全域預設
$ sudo tee /etc/systemd/system.conf.d/limits.conf >/dev/null <<'EOF'
[Manager]
DefaultLimitNOFILE=65536:524288
EOF
$ sudo systemctl daemon-reexec           # ★★ 需要重新執行 systemd

# ★★★ nginx 還要另外設（★ 它有自己的參數）
$ sudo tee /etc/nginx/conf.d/limits.conf >/dev/null <<'EOF'
# ★ 這個要放在 main context，實際上要寫在 nginx.conf 最上層
EOF
$ sudo sed -i '/^worker_processes/a worker_rlimit_nofile 65536;' /etc/nginx/nginx.conf
$ grep -E 'worker_processes|worker_rlimit_nofile|worker_connections' /etc/nginx/nginx.conf
worker_processes auto;
worker_rlimit_nofile 65536;              # ★★★★ 一定要設
events { worker_connections 4096; }      # ★★ 每個 worker 的連線上限

#   ★★★ 計算：最大連線數 = worker_processes × worker_connections
#      而 worker_rlimit_nofile 要 >= worker_connections × 2
#      （★ 每個連線可能用兩個 fd：客戶端 + 上游）

# ★★ php-fpm
$ sudo systemctl edit php8.3-fpm
[Service]
LimitNOFILE=65536
$ grep rlimit_files /etc/php/8.3/fpm/pool.d/www.conf
rlimit_files = 65536

# ★★ MySQL
$ sudo systemctl edit mysql
[Service]
LimitNOFILE=65536
$ sudo mysql -e "SHOW VARIABLES LIKE 'open_files_limit'"
```

---

## 完整實戰範例：連線數異常

```bash
# ═══ 情境：nginx error.log 出現 Too many open files ═══
$ sudo tail -5 /var/log/nginx/error.log
2026/08/28 15:42:11 [crit] 1234#0: *48210 accept4() failed (24: Too many open files)

# ═══ ★★★【1】確認限制與用量 ═══
$ cat /proc/$(pgrep -o nginx)/limits | grep -i 'open files'
Max open files            1024                 1024      files    # ★★★★ 只有 1024！
$ ls /proc/$(pgrep -o nginx)/fd | wc -l
1024                                                              # ★★★★ 滿了

# ═══ ★★★★【2】看 fd 用在哪 ═══
$ sudo ls -l /proc/$(pgrep -o nginx)/fd | awk '{print $NF}' | \
    sed 's/[0-9]*$//' | sort | uniq -c | sort -rn | head
    892 socket:[
     84 /var/log/nginx/access.log
     42 /var/log/nginx/error.log
      6 /dev/null
#   ★★★ 892 個是 socket → 是連線太多，不是檔案洩漏

# ═══ ★★★【3】連線狀態分布 ═══
$ ss -tan | awk 'NR>1 {c[$1]++} END {for(s in c) printf "%-14s %d\n",s,c[s]}' | sort -k2 -rn
TIME-WAIT      24810
ESTAB           842
CLOSE-WAIT      284                  # ★★★★ 有洩漏
SYN-RECV         12

# ═══ ★★★★【4】CLOSE_WAIT 是誰的 ═══
$ sudo ss -tanp state close-wait | grep -oP 'users:\(\("\K[^"]+' | \
    sort | uniq -c | sort -rn
    284 php-fpm

$ sudo ss -tanp state close-wait | awk 'NR>1{print $5}' | \
    awk -F: '{print $1":"$2}' | sort | uniq -c | sort -rn | head -3
    284 10.10.20.50:3306              # ★★★★ 資料庫連線沒關

# ★★ 確認是持續增加
$ for i in 1 2 3; do
    echo "$(date +%T) $(ss -tan state close-wait|wc -l)"; sleep 20
  done
15:45:01 284
15:45:21 291
15:45:41 299                          # ★★★★ 確認洩漏

# ═══ ★★★【5】TIME_WAIT 是不是問題 ═══
$ sysctl -n net.ipv4.ip_local_port_range
32768	60999                          # 28231 個
$ ss -tan state time-wait | wc -l
24810                                 # ★★★ 88% → 快用完
$ ss -tan state time-wait | awk 'NR>1{print $5}' | \
    awk -F: '{print $1":"$2}' | sort | uniq -c | sort -rn | head -3
  24102 10.10.20.50:8080              # ★★★★ 都是連到上游
#   → ★★★★ nginx 對上游【沒有用 keepalive】

# ═══ ★★★【6】accept 佇列 ═══
$ ss -lnt 'sport = :443'
State  Recv-Q Send-Q Local Address:Port
LISTEN 128    511          0.0.0.0:443       # ★★★★ 128 個在排隊
$ nstat -az | grep -i ListenOverflow
TcpExtListenOverflows           4820          # ★★★★ 已經丟了 4820 個連線

# ═══ ★★★★【7】處置（★ 一次一個）═══

# ★★★★ 處置 1：提高 nginx 的 fd 上限（★ 立即止血）
$ sudo systemctl edit nginx
[Service]
LimitNOFILE=65536
$ sudo sed -i '/^worker_processes/a worker_rlimit_nofile 65536;' /etc/nginx/nginx.conf
$ sudo sed -i 's/worker_connections .*/worker_connections 8192;/' /etc/nginx/nginx.conf
$ sudo nginx -t && sudo systemctl daemon-reload && sudo systemctl restart nginx
$ cat /proc/$(pgrep -o nginx)/limits | grep -i 'open files'
Max open files            65536                65536     files    # ★★★ 生效

# ★★★★ 處置 2：上游 keepalive（★ 消除 TIME_WAIT 的根因）
$ sudo tee /etc/nginx/conf.d/upstream.conf >/dev/null <<'EOF'
upstream backend {
    server 10.10.20.50:8080;
    keepalive 128;                    # ★★★★
    keepalive_timeout 60s;
    keepalive_requests 1000;
}
EOF
#   ★★★★ location 裡一定要加這兩行：
#     proxy_http_version 1.1;
#     proxy_set_header Connection "";
$ sudo nginx -t && sudo systemctl reload nginx

$ sleep 120 && ss -tan state time-wait | wc -l
1842                                  # ★★★★ 24810 → 1842

# ★★★ 處置 3：backlog
$ sudo tee /etc/sysctl.d/60-backlog.conf >/dev/null <<'EOF'
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.core.netdev_max_backlog = 16384
EOF
$ sudo sysctl --system
$ sudo sed -i 's/listen 443 ssl;/listen 443 ssl backlog=8192;/' \
    /etc/nginx/sites-enabled/app
$ sudo nginx -t && sudo systemctl restart nginx
$ ss -lnt 'sport = :443'
LISTEN 0      8192         0.0.0.0:443       # ★★★ Recv-Q 0，Send-Q 8192

# ★★★★ 處置 4：修正 CLOSE_WAIT 的程式 bug（★ 這個要改程式碼）
#   → ★★★ 找出沒有關閉資料庫連線的程式碼
$ grep -rn 'new PDO\|DB::connection' /var/www/app/current/app/ | head
#   → ★★ 用 try-finally 確保關閉，或改用框架的連線管理
#   → ★★★ 臨時處置：定期重啟 php-fpm worker
$ grep pm.max_requests /etc/php/8.3/fpm/pool.d/www.conf
pm.max_requests = 500                 # ★★★ 每個 worker 處理 500 個請求後重生
#   → ★★ 這能【緩解】fd 洩漏，但不是根治

# ═══ ★★★【8】驗證 ═══
$ ls /proc/$(pgrep -o nginx)/fd | wc -l
842                                   # ★★★ 遠低於 65536
$ ss -tan | awk 'NR>1{c[$1]++} END {for(s in c) printf "%-12s %d\n",s,c[s]}'
ESTAB          892
TIME-WAIT      1842                   # ★★★ 大幅下降
CLOSE-WAIT     12                     # ★★ 還有一點，等程式修正
$ nstat -az | grep -i ListenOverflow
TcpExtListenOverflows           0     # ★★★ 不再丟連線
$ sudo grep -c 'Too many open files' /var/log/nginx/error.log
0
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **大量 `CLOSE_WAIT`** ★★★★ | **應用程式沒呼叫 `close()`** | **修程式**；臨時重啟；調 sysctl **完全無效** |
| **大量 `TIME_WAIT`** ★★★ | 主動關閉方的正常狀態 | **通常不用管**；埠用盡才處理（**keepalive**） |
| **`Cannot assign requested address`** ★★★★ | 本機埠用盡 | keepalive；擴大 `ip_local_port_range`；`tcp_tw_reuse` |
| **`Too many open files`** ★★★★ | fd 上限 | **`systemctl edit` 加 `LimitNOFILE`** |
| **改了 `limits.conf` 沒效** ★★★★ | **systemd 服務不讀它** | **用 `systemctl edit`** |
| **`ss -lnt` 的 `Recv-Q` > 0** ★★★★ | accept 佇列積壓 | 調 `somaxconn` + 應用的 `backlog` |
| **調了 `somaxconn` 沒效** ★★★ | 應用的 `listen()` 參數沒改 | nginx `backlog=`；fpm `listen.backlog` |
| **`0.0.0.0:3306`** ★★★★ | **資料庫對外開放** | `bind-address = 127.0.0.1`；防火牆 |
| **大量 `SYN_RECV`** ★★★★ | **SYN flood** | `tcp_syncookies=1`；限流；上游防護 |
| **`lsof` 很慢** ★★★ | 掃描所有 `/proc` | `lsof -n -P`；改用 `ss` |
| **`netstat: command not found`** ★★ | net-tools 沒裝 | **用 `ss`** |
| `df` 滿但 `du` 找不到 ★★★★ | 已刪除但 fd 開著 | **`lsof +L1`** |

### 排查

```bash
# 【1】★★★★ 監聽與對外開放
$ sudo ss -tulnp
$ sudo ss -tlnp | awk 'NR>1 && $4 !~ /^127\.|^\[::1\]/'    # ★★★ 對外的

# 【2】★★★★ 狀態分布
$ ss -tan | awk 'NR>1{c[$1]++} END {for(s in c) printf "%-14s %d\n",s,c[s]}' | sort -k2 -rn

# 【3】★★★★ CLOSE_WAIT 的元凶
$ sudo ss -tanp state close-wait | grep -oP 'users:\(\("\K[^"]+' | sort | uniq -c | sort -rn

# 【4】★★★ 佇列積壓
$ ss -lnt
$ nstat -az | grep -iE 'ListenOverflows|ListenDrops|TcpExtSyncookies'
$ netstat -s | grep -iE 'listen|overflow'

# 【5】★★★★ fd 用量
$ for p in $(pgrep -d' ' -x 'nginx|php-fpm|mysqld'); do
    printf "%-10s %5s/%s\n" "$(cat /proc/$p/comm)" \
      "$(ls /proc/$p/fd 2>/dev/null|wc -l)" \
      "$(awk '/Max open files/{print $4}' /proc/$p/limits)"
  done

# 【6】★★★ TCP 內部狀態
$ sudo ss -tani state established | grep -oP 'rtt:\K[0-9.]+' | sort -rn | head -3
$ sudo ss -tani state established | grep -oP 'retrans:[0-9]+/\K[0-9]+' | sort -rn | head -3

# 【7】★★ 誰連最多
$ ss -tan state established | awk 'NR>1{split($5,a,":");print a[1]}' | \
    sort | uniq -c | sort -rn | head

# 【8】★★★ 已刪除的檔案
$ sudo lsof +L1 2>/dev/null | head
$ ls -l /proc/*/fd 2>/dev/null | grep -c deleted
```

---

## 安全性注意事項

> [!danger] 四個要點 ★★★
> ```
> ① ★★★★ ss -tulnp 是資安稽核的第一個指令
>      → 找出【不該對外開放】的服務
>      → ★★★★ 3306 / 6379 / 5432 / 9000 / 27017 綁 0.0.0.0 = 高風險
>      → ★★★ Redis 沒密碼 + 對外 = 直接被入侵
>
> ② ★★★ 大量 SYN_RECV = SYN flood 攻擊
>      → ★★ 開啟 tcp_syncookies
>      → ★★ 上游做限流
>
> ③ ★★★ 單一 IP 大量連線 = 可能是攻擊或爬蟲
>      → ★★ nginx limit_conn / limit_req
>      → ★ fail2ban
>
> ④ ★★ 連線資訊會暴露內部拓撲
>      → ★★★ ss 的輸出顯示內部 IP、服務、版本
>      → ★ 分享前清理
> ```

```bash
# ★★★★ 資安稽核：檢查對外開放的服務
$ sudo ss -tulnp | awk '
  NR>1 && $5 ~ /^(0\.0\.0\.0|\[::\]|\*)/ {
    split($5,a,":"); port=a[length(a)]
    danger="3306 5432 6379 27017 11211 9200 5601 8086 2375 9000"
    if (index(danger, port)) printf "★★★★ 危險: %-6s %s\n", port, $NF
    else printf "★ 對外: %-6s %s\n", port, $NF
  }'
★ 對外: 80     users:(("nginx",pid=1234,fd=6))
★ 對外: 443    users:(("nginx",pid=1234,fd=8))
★ 對外: 22     users:(("sshd",pid=890,fd=3))
★★★★ 危險: 6379   users:(("redis-server",pid=3210,fd=6))    # ★ 立刻處理！

# ★★★ 修正
$ sudo sed -i 's/^bind .*/bind 127.0.0.1 ::1/' /etc/redis/redis.conf
$ grep -E '^(bind|requirepass|protected-mode)' /etc/redis/redis.conf
bind 127.0.0.1 ::1
requirepass <強密碼>
protected-mode yes
$ sudo systemctl restart redis-server
$ sudo ss -tlnp 'sport = :6379'
LISTEN 0 511 127.0.0.1:6379    users:(("redis-server",pid=3290,fd=6))   # ★★★ 只綁本機

# ★★★ SYN flood 防護
$ sudo tee /etc/sysctl.d/60-syn.conf >/dev/null <<'EOF'
net.ipv4.tcp_syncookies = 1               # ★★★ 必開
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.tcp_synack_retries = 2           # ★★ 減少半開連線的存活時間
net.ipv4.tcp_abort_on_overflow = 0        # ★ 0 = 靜默丟棄（不要設 1）
EOF
$ sudo sysctl --system
$ nstat -az | grep -i syncookie
TcpExtSyncookiesSent            0         # ★★ >0 = 正在被攻擊或 backlog 不足

# ★★★ 找出連線異常多的來源
$ ss -tan state established | awk 'NR>1{split($5,a,":");print a[1]}' | \
    sort | uniq -c | sort -rn | awk '$1 > 50 {print "★★★ " $2 " → " $1 " 條連線"}'
★★★ 203.0.113.45 → 284 條連線

# ★★ nginx 限流
$ sudo tee /etc/nginx/conf.d/limits.conf >/dev/null <<'EOF'
limit_conn_zone $binary_remote_addr zone=perip:10m;
limit_req_zone  $binary_remote_addr zone=reqs:10m rate=20r/s;
EOF
#   ★★ 在 server / location 加：
#     limit_conn perip 20;
#     limit_req zone=reqs burst=40 nodelay;

# ★★ 清理輸出後再分享
$ sudo ss -tulnp | sed -E 's/([0-9]{1,3}\.){3}[0-9]{1,3}/x.x.x.x/g'
```

---

## 速查表

### ★★★★ 三個必背

```bash
sudo ss -tulnp        # ★★★★ 誰在監聽（資安稽核第一個指令）
sudo ss -tanp         # 所有連線 + 程序
ss -s                 # 統計摘要
```

### ★★★★ 狀態判讀

```
LISTEN         正常
SYN_RECV 大量  → ★★★★ SYN flood（tcp_syncookies=1）
ESTABLISHED    看數量是否合理
★★★ TIME_WAIT  主動關閉方，【通常正常】
               → 只有埠用盡才處理 → ★★★★ keepalive 治本
★★★★ CLOSE_WAIT 被動關閉方沒 close()
               → 【一定是程式 bug】，調 sysctl 無效
```

### ★★★★ Recv-Q / Send-Q

```
LISTEN 時：  Recv-Q = ★★★★ 排隊等 accept 的連線數（>0 就有問題）
            Send-Q = backlog 上限
ESTAB 時：   Recv-Q = ★★★ 應用程式還沒讀的資料（>0 = 處理不過來）
            Send-Q = 對方還沒 ACK 的資料
```

### ss 過濾

```bash
ss -tan state close-wait                    # ★★★★
ss -tan state time-wait | wc -l
ss -tanp 'dport = :3306'
ss -tan 'dst 10.10.20.0/24'
ss -tanp 'state established and dport = :3306'
sudo ss -tani state established             # ★★★ RTT / 重傳 / cwnd
sudo ss -K 'dst 203.0.113.45'               # ★★ 強制關閉
```

### ★★★★ 檔案描述符

```bash
cat /proc/PID/limits | grep -i 'open files'  # ★★★★ 服務的實際上限
ls /proc/PID/fd | wc -l                      # ★★★ 目前用量
sudo systemctl edit nginx                    # ★★★★ [Service] LimitNOFILE=65536
#  ★★★★ /etc/security/limits.conf 對 systemd 服務【無效】！
worker_rlimit_nofile 65536;                  # ★★★ nginx 還要另外設
```

### ★★★ backlog 三層

```bash
net.core.somaxconn = 8192                    # ① 系統上限
net.ipv4.tcp_max_syn_backlog = 8192          # ② SYN 佇列
listen 443 ssl backlog=8192;                 # ③ ★★★★ 應用層（缺這個前兩個沒用）
nstat -az | grep -i ListenOverflow           # ★★★ 驗證
```

### lsof

```bash
sudo lsof -i :8080 -n -P     # ★★★ 誰佔用埠（★ ss 更快）
sudo lsof +L1                # ★★★★ 已刪除但佔空間
sudo lsof -p PID             # 程序開的檔案
sudo fuser -vm /mnt/data     # ★★ 誰在用掛載點
★★★ lsof 一定加 -n -P（快 10 倍）
```

### ★★★★ 資安檢查

```bash
sudo ss -tlnp | awk 'NR>1 && $4 !~ /^127\.|^\[::1\]/'
# ★★★★ 3306/6379/5432/9000/27017 綁 0.0.0.0 = 立刻處理
```

---

## 練習題

> [!question]- 練習 1：監聽與資安 ★★★
> 1. **`sudo ss -tulnp`** → 列出所有監聽的服務
> 2. **哪些綁 `0.0.0.0`？哪些綁 `127.0.0.1`？**
> 3. **有沒有不該對外的？**（3306 / 6379 / 9000）
> 4. 用 `nmap` 從另一台掃描 → 掃到什麼？
> 5. **修正一個不該對外的服務**
> 6. **寫一個稽核腳本，發現危險埠就報警**

> [!question]- 練習 2：TIME_WAIT vs CLOSE_WAIT ★★★★
> 1. **寫一個小程式：連上伺服器、收到 FIN 後不呼叫 `close()`**
> 2. **`ss -tan state close-wait`** → 看得到嗎？會消失嗎？
> 3. 用 `ab -n 5000 -c 100` 對 nginx 壓測
> 4. **`ss -tan state time-wait | wc -l`** → 多少？60 秒後呢？
> 5. **兩者的差別是什麼？各該怎麼處理？**
> 6. **調 sysctl 對 CLOSE_WAIT 有用嗎？為什麼？**

> [!question]- 練習 3：backlog ★★★★
> 1. `ss -lnt 'sport = :443'` → **Send-Q 是多少？**
> 2. **設 `net.core.somaxconn = 8192`** → Send-Q 變了嗎？
> 3. **在 nginx 加 `backlog=8192` 並重啟** → 呢？
> 4. **為什麼只調 sysctl 沒用？**
> 5. `ab -n 50000 -c 500` 壓測，**觀察 `Recv-Q`**
> 6. **`nstat -az | grep ListenOverflow`** → 有丟連線嗎？

> [!question]- 練習 4：檔案描述符 ★★★★
> 1. **`cat /proc/$(pgrep -o nginx)/limits | grep -i 'open files'`** → 多少？
> 2. **改 `/etc/security/limits.conf` 設 65536，重啟 nginx** → 生效嗎？
> 3. **改用 `systemctl edit nginx` 加 `LimitNOFILE`** → 呢？
> 4. **為什麼第 2 步沒用？**
> 5. 加 `worker_rlimit_nofile` 到 nginx.conf
> 6. **寫一個監控腳本，fd 用量 > 80% 就告警**

> [!question]- 練習 5：lsof ★★★
> 1. `sudo dd if=/dev/zero of=/tmp/big bs=1M count=1000`
> 2. `tail -f /tmp/big > /dev/null &` 然後 `rm /tmp/big`
> 3. **`df -h /tmp` 和 `du -sh /tmp` 差多少？**
> 4. **`sudo lsof +L1 | grep big`** → 看到什麼？`NLINK` 是多少？
> 5. `kill %1` → 空間回來了嗎？
> 6. **比較 `lsof -i :80` 和 `ss -tlnp 'sport = :80'` 的速度**（`time`）

---

## 小測驗

Q1. **為什麼 `ss` 比 `netstat` 快**？

Q2. **`TIME_WAIT` 和 `CLOSE_WAIT` 分別出現在哪一端**？哪一個是程式 bug？

Q3. **大量 `TIME_WAIT` 需要處理嗎**？什麼情況下才需要？怎麼治本？

Q4. **為什麼 `net.ipv4.tcp_tw_recycle` 是有害的建議**？

Q5. **`ss -lnt` 的 `Recv-Q` 和 `Send-Q` 在 LISTEN 狀態下各代表什麼**？

Q6. **調了 `net.core.somaxconn` 但 backlog 沒變大，為什麼**？

Q7. **改 `/etc/security/limits.conf` 為什麼對 systemd 服務無效**？正確做法？

Q8. **`Too many open files` 的三層限制各是什麼**？怎麼查？

Q9. **`ss -tulnp` 在資安稽核上為什麼是第一個該跑的指令**？

Q10. **`df` 顯示滿了但 `du` 找不到，用哪個 `lsof` 參數查**？

> [!question]- 測驗答案
> **Q1.** 因為 **`ss` 直接透過 netlink socket 向核心查詢，而 `netstat` 是解析 `/proc/net/tcp` 這種文字檔**。
> `/proc/net/tcp` 是核心動態產生的**文字**，
> 每次讀取核心都要把所有 socket 的資訊**格式化成字串**，
> netstat 再把字串 **parse 回結構**。
> 幾萬條連線時這是好幾 MB 的文字，兩邊都在做無謂的轉換。
> **netlink 傳的是二進位結構**，而且**支援核心層的過濾**
> （`ss -tan state close-wait` 是核心幫你篩，不是抓全部回來再 grep）。
> 實測差距**10 倍以上**。
> 另外 `ss` 還能顯示 netstat 看不到的資訊：
> `-i` 的 RTT、cwnd、重傳次數、pacing rate 等 TCP 內部狀態。
> `net-tools`（netstat/ifconfig/route）已多年未維護，新發行版預設不裝。
>
> **Q2.** **`TIME_WAIT` 出現在「主動關閉的一方」**（先送 FIN 的那端）；
> **`CLOSE_WAIT` 出現在「被動關閉的一方」**（收到 FIN 的那端）。
> **★★★★ `CLOSE_WAIT` 是程式 bug**。
> 它的意思是：**對方已經說「我關了」，但你的應用程式沒有呼叫 `close()`** ——
> TCP 協定已經完成它該做的，剩下的是應用程式的責任。
> 常見原因：忘記 `close()`、例外處理路徑沒關連線、連線池洩漏。
> **它不會自動消失，會一直累積**，最後**檔案描述符用盡，服務完全掛掉**。
> **`TIME_WAIT` 則是協定設計上必要的狀態** ——
> 等 2×MSL（Linux 60 秒）確保對方收到最後的 ACK、
> 且舊連線的延遲封包不會污染新連線。**它會自動消失**。
>
> **Q3.** **★★★ 通常不需要處理**。
> 每個 TIME_WAIT socket 只佔幾十 bytes，60 秒後自動消失，
> 有幾萬個是完全正常的（尤其是反向代理）。
> **★★★★ 只有在「本機埠用盡」時才是問題**，症狀是：
> ```
> curl: (7) Failed to connect: Cannot assign requested address
> ```
> 判斷方式：`ss -tan state time-wait | wc -l` 對照
> `sysctl net.ipv4.ip_local_port_range`（預設約 28000 個）。
> **★★★★ 治本的方法是連線池 / keepalive** ——
> 不要每個請求都開新連線：
> ```nginx
> upstream backend {
>     server 10.10.20.50:8080;
>     keepalive 128;
> }
> location / {
>     proxy_pass http://backend;
>     proxy_http_version 1.1;         # ★★★★ 必須
>     proxy_set_header Connection ""; # ★★★★ 必須
> }
> ```
> 治標的方法：擴大 `ip_local_port_range`、`net.ipv4.tcp_tw_reuse=1`。
>
> **Q4.** 因為它**在 NAT 環境下會隨機拒絕連線**。
> `tcp_tw_recycle` 的機制是依 **TCP timestamp** 判斷是否可以重用 TIME_WAIT 的埠 ——
> 它假設「同一個來源 IP 的 timestamp 是遞增的」。
> **但 NAT 後面有很多台機器，它們的 timestamp 彼此不同** ——
> 伺服器看到「同一個 IP」送來比上次小的 timestamp，就判定為過期封包並丟棄。
> **症狀極難排查**：「有些人連得上，有些人連不上，而且時好時壞」。
> 現在絕大多數行動網路和企業網路都在 NAT 後面，這幾乎必然出事。
> **Linux 4.12（2017）已經完全移除這個參數**，新系統設了也沒效果。
> **但網路上大量的中文「TCP 調優」文章還在教這個** ——
> 遇到舊系統（CentOS 7）一定要確認它是 0。
> 安全的替代是 **`tcp_tw_reuse=1`**（只影響出向連線，伺服器端不受影響）。
>
> **Q5.** **在 LISTEN 狀態下**：
> **`Recv-Q` = 目前已完成三次交握、但應用程式還沒 `accept()` 的連線數**；
> **`Send-Q` = backlog 的上限**（= `min(應用程式 listen() 的參數, net.core.somaxconn)`）。
> **★★★★ `Recv-Q > 0` 就代表應用程式忙不過來** ——
> 連線已經建立好在排隊等人來接，使用者正在等待。
> ```
> LISTEN 48  511  0.0.0.0:80      ★★★★ 48 個在排隊
> ```
> 對照 `nstat -az | grep ListenOverflow` ——
> 有數字表示**佇列滿了，連線被直接丟棄**（客戶端會逾時）。
> **注意在 ESTABLISHED 狀態下意義完全不同**：
> `Recv-Q` 是已收到但應用還沒讀的**資料量（bytes）**，
> `Send-Q` 是已送出但對方還沒 ACK 的資料量。
>
> **Q6.** 因為 **實際的 backlog 是 `min(應用程式 listen() 的參數, net.core.somaxconn)`** ——
> **兩個都要調，取小的那個**。
> `somaxconn` 只是**系統允許的天花板**，
> 如果 nginx 呼叫 `listen(fd, 511)`，那實際 backlog 就是 511，
> 把 `somaxconn` 調到 8192 完全不會改變它。
> **三層都要設**：
> ```bash
> # ① 系統
> net.core.somaxconn = 8192
> net.ipv4.tcp_max_syn_backlog = 8192
> # ② ★★★★ 應用層（缺這個前面白調）
> #   nginx:    listen 443 ssl backlog=8192;
> #   php-fpm:  listen.backlog = 8192
> ```
> **驗證**：`ss -lnt 'sport = :443'` 看 **Send-Q 是否真的變大**。
> 注意應用程式要**重啟**（不是 reload）才會重新 `listen()`。
>
> **Q7.** 因為 **`/etc/security/limits.conf` 是 PAM 模組（`pam_limits.so`）讀取的**，
> **只在「使用者透過 PAM 登入建立 session」時套用** ——
> SSH 登入、`su`、`login` 這些。
> **systemd 啟動的服務完全不經過 PAM**，
> 它們是 systemd 直接 fork 出來的，繼承的是 systemd 的限制。
> **正確做法**：
> ```bash
> sudo systemctl edit nginx
> # [Service]
> # LimitNOFILE=65536
> sudo systemctl daemon-reload && sudo systemctl restart nginx
> ```
> **驗證**（一定要驗證，不要假設）：
> ```bash
> cat /proc/$(pgrep -o nginx)/limits | grep -i 'open files'
> ```
> 全域預設可以設在 `/etc/systemd/system.conf.d/limits.conf` 的
> `DefaultLimitNOFILE`（需要 `systemctl daemon-reexec`）。
> **nginx 還要額外設 `worker_rlimit_nofile`**（它自己會再降低限制）。
>
> **Q8.** **三層限制**：
> **① 系統總上限** `fs.file-max`：
> ```bash
> cat /proc/sys/fs/file-nr     # 已用  未使用  上限
> ```
> 現代核心這個值通常非常大，很少是瓶頸。
> **② 每個程序的上限（`RLIMIT_NOFILE`）** ——
> **這才是最常見的瓶頸**：
> ```bash
> cat /proc/<PID>/limits | grep -i 'open files'    # ★★★★ 看服務的實際值
> ulimit -n                                        # ★ 只是你這個 shell 的
> ```
> **③ 應用程式自己的設定** ——
> nginx 的 `worker_rlimit_nofile`、php-fpm 的 `rlimit_files`、
> MySQL 的 `open_files_limit`，這些會**在系統限制之內再設一層**。
> **目前用量**：`ls /proc/<PID>/fd | wc -l`。
> 三個都要對，任何一層卡住都會出現 `Too many open files`。
>
> **Q9.** 因為它**一次回答「這台機器對外暴露了什麼」** ——
> 這是攻擊面評估最直接的資訊。
> ```bash
> sudo ss -tulnp | awk 'NR>1 && $5 ~ /^(0\.0\.0\.0|\[::\]|\*)/'
> ```
> **要找的是「不該綁 0.0.0.0 的服務」**：
> **3306（MySQL）、5432（PostgreSQL）、6379（Redis）、
> 27017（MongoDB）、11211（Memcached）、9200（Elasticsearch）、
> 9000（php-fpm）、2375（Docker API）**。
> 這些**只應該綁 `127.0.0.1` 或內網介面**。
> **Redis 綁 0.0.0.0 且沒設密碼是經典的入侵途徑** ——
> 攻擊者可以直接寫入 SSH authorized_keys 或 cron。
> 比 `nmap` 從外部掃描更可靠（不受防火牆遮蔽影響），
> 而且**同時告訴你是哪個程序在監聽**（`-p`），可以直接去改設定。
>
> **Q10.** **`sudo lsof +L1`** ——
> `+L1` 的意思是「列出 link count 小於 1 的檔案」，
> 也就是**目錄項已經被刪除（`NLINK=0`）但仍有程序開著檔案描述符**的檔案。
> ```
> COMMAND   PID  USER FD  TYPE DEVICE   SIZE/OFF NLINK NODE NAME
> rsyslogd 8901  root  7w REG  253,2  98784247808     0  456 /var/log/huge.log (deleted)
> #                                                      ↑
> #                                      ★★★★ NLINK=0，但還佔 98GB
> ```
> `du` 是走目錄樹統計，這種檔案**沒有目錄項所以掃不到**，
> 但 inode 和資料區塊還在，**空間要等程序關閉 fd 才釋放**。
> **解法**：
> ```bash
> sudo systemctl restart rsyslog       # ★★ 重啟持有的服務（最乾淨）
> sudo truncate -s 0 /proc/8901/fd/7   # ★ 不重啟服務，但要確定 fd 正確
> ```
> 更快的替代查法：`ls -l /proc/*/fd 2>/dev/null | grep deleted`。
> 其他造成 `df`/`du` 不一致的原因還有：**掛載點蓋住底下的檔案**、
> **inode 用完**（`df -i`）、**ext4 保留給 root 的 5%**。

---

## 延伸閱讀

- [[060-01-04-01-guide-tcpdump-基礎抓包]] — 看不出問題時再抓包
- [[060-01-04-02-guide-tcpdump-進階過濾與實戰]] — 零視窗與重傳分析
- [[020-01-16-cmd-Linux-網路基礎指令]] — `ip` / `ping` / `traceroute`
- [[060-01-03-03-guide-監控-資源診斷工具集]] — `lsof +L1` 與磁碟空間
- [[060-01-03-04-guide-監控-效能瓶頸排查方法論]] — Saturation 的量測
- [[020-01-26-guide-Linux-核心模組與sysctl調校]] — TCP 參數
