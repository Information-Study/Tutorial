---
title: "tcpdump 基礎抓包"
desc: "封包擷取的第一課：介面、過濾、輸出判讀與存檔"
aliases: [tcpdump, 抓包, packet capture, pcap]
tags: [群組/軟體與開發工具, 主題/網路診斷, 主題/tcpdump]
category: 常用工具
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[020-01-16-cmd-Linux-網路基礎指令]]"]
updated: 2026-08-28
---

# tcpdump 基礎抓包

> [!abstract] 這篇你會學到
> - **★★★ 什麼時候該抓包**（以及什麼時候不用）
> - 介面選擇、**★★★ `-n` 為什麼一定要加**
> - 基本過濾：host / port / net / proto
> - **★★★★ 看懂輸出的每一個欄位**（含 TCP flags）
> - **★★★ 存成 pcap 給 Wireshark 分析**
> - **★★ 環形緩衝與長時間抓包**（不會塞爆磁碟）
> - **★★★ 抓包的資安與法遵注意事項**

## 前置知識

- [[020-01-16-cmd-Linux-網路基礎指令]] — `ip`、`ss`、`ping`
- [[060-01-04-03-guide-ss-netstat-與lsof]] — 先確認連線狀態再抓包

---

## ★★★ 什麼時候該抓包

```
★★★ 抓包是【最後手段】，不是第一步

  ✗ 「網站慢」→ 直接抓包        ← ★★ 太早了
  ✓ 先看 log → 看 ss → 看監控 → ★ 還是不知道 → 抓包

★★★★ 該抓包的五個情境：

  ① ★★★ 【看不到任何日誌】
     → 「連線根本沒到我的伺服器」
     → ★★ 抓包是唯一能證明「封包有沒有來」的方法

  ② ★★★ 【兩邊說法不一致】
     → 對方說「我有送」，你說「我沒收到」
     → ★★★★ 抓包 = 客觀證據

  ③ ★★★ 【協定層的問題】
     → TLS 交握失敗、TCP 重傳、MTU/分片
     → ★★ 應用層的日誌看不到這些

  ④ ★★ 【間歇性、無法重現】
     → 環形緩衝長時間抓，等問題發生

  ⑤ ★★ 【第三方系統整合】
     → 對方的 API 到底送了什麼

★★★ 不需要抓包的情況：
  · 應用層的錯誤（★ 看 log 更快）
  · 效能問題（★ 用 [[060-01-03-04-guide-監控-效能瓶頸排查方法論]]）
  · ★★ 已經有明確的錯誤訊息
```

---

## 安裝與權限

```bash
$ sudo apt install -y tcpdump
$ tcpdump --version
tcpdump version 4.99.4
libpcap version 1.10.4 (with TPACKET_V3)
OpenSSL 3.0.13
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> $ sudo dnf install -y tcpdump
> ```

```bash
# ★★★ 一般使用者也能抓包（★ 不用給完整 sudo）
$ sudo setcap cap_net_raw,cap_net_admin=eip "$(command -v tcpdump)"
$ getcap "$(command -v tcpdump)"
/usr/bin/tcpdump cap_net_raw,cap_net_admin=eip

$ tcpdump -i any -c 1        # ★ 不用 sudo 了
#   → ★★ 但 Ubuntu 的 AppArmor 可能仍會擋，見排錯

# ★★ 或用 sudoers 限制（★ 更可控）
$ sudo visudo -f /etc/sudoers.d/tcpdump
%netadmin ALL=(root) NOPASSWD: /usr/bin/tcpdump -i * -n -c * *
#   ★★★ 注意：不要允許 -w（寫檔）到任意路徑
#      → ★★★★ 攻擊者可以用 tcpdump -w /etc/cron.d/x 寫任意檔案
```

> [!danger] tcpdump 在 sudoers 裡是提權漏洞 ★★★★
> ```
> ★★★★ 給了 tcpdump 的完整 sudo = 給了 root
>
> 攻擊方式一：-z（postrotate 指令）
>   $ sudo tcpdump -i lo -w /tmp/x -W 1 -G 1 -z /bin/bash
>   → ★★★★ -z 指定的指令會【以 root 執行】
>
> 攻擊方式二：-w 寫任意檔案
>   $ sudo tcpdump -i lo -w /etc/cron.d/pwn
>   → ★★★ 寫入 cron 目錄（★ 內容雖然是二進位，但可以構造）
>
> ★★★ 正確做法：
>   ① 用 setcap（★ 不需要 sudo）
>   ② sudoers 精確限制參數，★★ 絕對不允許 -z 和 -w
>   ③ ★★ 或包一層腳本，腳本只做固定的事
> ```

---

## 基本用法 ★★★

### 選介面

```bash
# ★★ 列出可用的介面
$ sudo tcpdump -D
1.eth0 [Up, Running, Connected]
2.any (Pseudo-device that captures on all interfaces) [Up, Running]
3.lo [Up, Running, Loopback]
4.docker0 [Up, Running]
5.br-1a2b3c4d [Up, Running]

$ ip -br link                          # ★ 另一個查法
lo     UNKNOWN  00:00:00:00:00:00
ens18  UP       ba:12:cd:34:ef:56
docker0 DOWN    02:42:8a:...
```

```bash
# ★★★ 最常用的三種
$ sudo tcpdump -i ens18 -n            # ★★ 指定實體介面
$ sudo tcpdump -i any -n              # ★★★ 所有介面（★ 不確定走哪個時）
$ sudo tcpdump -i lo -n               # ★★★ 本機通訊（★ nginx→php-fpm 一定用這個）
```

> [!tip] `-i any` 與 `-i lo` 的重要差異 ★★★
> ```
> ★★★ 三個常見的「抓不到」：
>
> ① 【本機的服務之間】
>    nginx(127.0.0.1) → php-fpm(127.0.0.1:9000)
>    → ★★★★ 走的是 lo，不是 eth0
>    → ★ 要用 -i lo 或 -i any
>
> ② 【Unix socket 完全抓不到】
>    fastcgi_pass unix:/run/php/php8.3-fpm.sock;
>    → ★★★★ 這【不是網路】，tcpdump 抓不到任何東西
>    → ★★ 要改用 strace 或 socat 中繼
>
> ③ 【容器內的流量】
>    → 走 docker0 或 br-xxx
>    → ★★ 用 -i docker0；或進容器的 netns 抓
>    $ sudo nsenter -t $(docker inspect -f '{{.State.Pid}}' app) -n \
>        tcpdump -i eth0 -n
> ```

### ★★★ `-n` 為什麼一定要加

```bash
# ★★★★ 不加 -n 的災難
$ sudo tcpdump -i ens18 port 80
#   → tcpdump 對【每一個 IP】做反向 DNS 查詢
#   → ★★★ 每次查詢又產生新的 DNS 封包
#   → ★★★★ 而且 DNS 查詢很慢 → 【封包來不及處理 → 大量遺失】
#   → ★★ 高流量時甚至會拖垮機器

# ★★★ 正確
$ sudo tcpdump -i ens18 -nn port 80
#   -n   ★★★ 不解析主機名（★ 一定要加）
#   -nn  ★★★★ 連 port 名稱也不解析（★ 顯示 443 而不是 https）
```

```
★★ 三個必加的選項：

  -n / -nn    ★★★★ 不做 DNS 解析（★ 效能 + 避免干擾）
  -i <介面>   ★★★ 明確指定（★ 不指定會抓第一個介面）
  -c <數量>   ★★★ 限制封包數（★ 避免無限輸出洗版）

★★★ 標準的第一個指令：
  $ sudo tcpdump -i any -nn -c 20 port 443
```

### 常用選項

| 選項 | 作用 | 說明 |
| --- | --- | --- |
| **`-i`** | 介面 | **★★★ `any` / `lo` / `ens18`** |
| **`-nn`** | 不解析名稱 | **★★★★ 一定要加** |
| **`-c N`** | 抓 N 個就停 | **★★★ 避免洗版** |
| **`-w file.pcap`** | **★★★ 存檔** | 給 Wireshark 分析 |
| **`-r file.pcap`** | 讀檔 | |
| **`-s N`** | 每個封包抓幾 bytes | **★★ 預設 262144（全抓）** |
| **`-v` `-vv` `-vvv`** | 詳細程度 | ★★ `-v` 顯示 TTL、IP ID |
| **`-A`** | **★★ 以 ASCII 顯示內容** | ★ 看 HTTP 明文 |
| **`-X` / `-XX`** | hex + ASCII | ★★ `-XX` 含乙太網標頭 |
| **`-e`** | 顯示乙太網標頭 | **★★★ 看 MAC / VLAN** |
| **`-t` `-tt` `-ttt`** | 時間格式 | **★★ `-tttt` 完整日期時間** |
| `-q` | 精簡輸出 | ★ 快速掃視 |
| **`-S`** | 顯示絕對序號 | ★★ 分析重傳時有用 |
| `-p` | 不進入混雜模式 | ★★ 見下 |
| **`-Z user`** | 降權執行 | **★★★ 安全** |

---

## ★★★★ 看懂輸出

```bash
$ sudo tcpdump -i any -nn -c 5 port 443
14:23:11.482910 IP 203.0.113.45.52134 > 10.10.20.31.443: Flags [S], seq 1820394857, win 64240, options [mss 1460,sackOK,TS val 892374 ecr 0,nop,wscale 7], length 0
14:23:11.482998 IP 10.10.20.31.443 > 203.0.113.45.52134: Flags [S.], seq 3948572910, ack 1820394858, win 65160, options [mss 1460,sackOK,TS val 12093 ecr 892374,nop,wscale 7], length 0
14:23:11.494201 IP 203.0.113.45.52134 > 10.10.20.31.443: Flags [.], ack 1, win 502, length 0
14:23:11.494812 IP 203.0.113.45.52134 > 10.10.20.31.443: Flags [P.], seq 1:518, ack 1, win 502, length 517
14:23:11.494901 IP 10.10.20.31.443 > 203.0.113.45.52134: Flags [.], ack 518, win 507, length 0
```

```
★★★★ 逐欄拆解：

14:23:11.482910   IP   203.0.113.45.52134  >  10.10.20.31.443:  Flags [S], ...
      ↑            ↑          ↑                     ↑              ↑
   ① 時間戳    ② 協定    ③ 來源 IP.port      ④ 目的 IP.port   ⑤ TCP flags

  ★★ 注意 port 是用【點】接在 IP 後面，不是冒號
     203.0.113.45.52134 = IP 203.0.113.45，port 52134

  seq 1820394857    序號
  ack 1820394858    ★★ 確認號（= 對方的 seq + 1）
  win 64240         ★★★ 接收視窗（★ 一直是 0 = 對方處理不過來）
  options [...]     ★★ TCP 選項（MSS、SACK、時間戳、視窗縮放）
  length 517        ★★★ 【應用層資料】的長度（★ 不含標頭）
```

### ★★★★ TCP Flags

| 符號 | Flag | 意義 |
| --- | --- | --- |
| **`S`** | SYN | **★★★ 要建立連線** |
| **`S.`** | SYN-ACK | **★★★ 同意建立**（`.` 代表 ACK） |
| **`.`** | ACK | 確認 |
| **`P`** | PSH | **★★ 有資料要立刻交給應用層** |
| **`F`** | FIN | **★★★ 正常關閉** |
| **`R`** | RST | **★★★★ 強制中斷**（見下） |
| `U` | URG | 緊急 |
| `W` `E` | CWR / ECE | 壅塞通知 |

```
★★★★ 完整的 TCP 三次交握：

  客戶端 → 伺服器   Flags [S]     seq=x            ★ 我要連線
  伺服器 → 客戶端   Flags [S.]    seq=y ack=x+1    ★ 好，我也要連
  客戶端 → 伺服器   Flags [.]     ack=y+1          ★★ 確認 → 連線建立

★★★★ 四次揮手（正常關閉）：
  A → B   Flags [F.]   ★ 我沒資料了
  B → A   Flags [.]    ★ 收到
  B → A   Flags [F.]   ★ 我也沒了
  A → B   Flags [.]    ★★ 關閉完成

★★★★ RST 的三種常見情境（★ 最重要的排錯訊號）：
  ① 【port 沒有服務在聽】
     A → B  Flags [S]  → B 沒有人聽 443
     B → A  Flags [R.] ← ★★★ 立刻拒絕
     → ★★ 對應 curl 的 "Connection refused"

  ② 【防火牆用 reject 而不是 drop】
     → ★★ 也會回 RST（★ 但可能是中間設備發的）

  ③ ★★★ 【應用程式異常關閉】
     → 程式 crash、逾時、或呼叫了 SO_LINGER=0
     → ★★★ 連線已建立後突然的 RST = 應用層問題
```

```bash
# ★★★★ 只看 SYN 和 RST（★ 排查連線問題的關鍵）
$ sudo tcpdump -i any -nn 'tcp[tcpflags] & (tcp-syn|tcp-rst) != 0'

# ★★★ 只看 RST
$ sudo tcpdump -i any -nn 'tcp[tcpflags] & tcp-rst != 0'
14:25:03.128374 IP 10.10.20.31.443 > 203.0.113.45.52890: Flags [R.], seq 1, ack 1, win 0, length 0
#                    ↑ ★★★★ 伺服器主動 RST

# ★★ 只看 SYN（★ 找出誰在嘗試連線）
$ sudo tcpdump -i any -nn 'tcp[tcpflags] & tcp-syn != 0 and tcp[tcpflags] & tcp-ack = 0'
```

> [!tip] `length 0` vs `length 517` ★★★
> ```
> ★★★ length 是【應用層資料】的長度，不含 TCP/IP 標頭
>
>   Flags [S]  length 0      ★ 交握封包沒有資料
>   Flags [.]  length 0      ★★ 純 ACK
>   Flags [P.] length 517    ★★★ 有 517 bytes 的資料
>
> ★★★ 排錯用途：
>   · 只看到交握（length 0）沒有資料 → ★★★ 應用層沒送東西
>   · ★★ 一直有 length 0 的 ACK → 可能在等對方
>   · ★★★ 只過濾有資料的封包：
>     $ sudo tcpdump -i any -nn 'tcp and (ip[2:2] - ((ip[0]&0xf)<<2) - ((tcp[12]&0xf0)>>2)) != 0'
> ```

---

## 過濾語法 ★★★

```bash
# ═══ ★★★ 主機 ═══
$ sudo tcpdump -i any -nn host 203.0.113.45           # 來源或目的
$ sudo tcpdump -i any -nn src host 203.0.113.45       # ★★ 只看來源
$ sudo tcpdump -i any -nn dst host 10.10.20.31        # ★★ 只看目的

# ═══ ★★★ 埠 ═══
$ sudo tcpdump -i any -nn port 443
$ sudo tcpdump -i any -nn src port 443
$ sudo tcpdump -i any -nn portrange 8000-8100         # ★★ 範圍
$ sudo tcpdump -i any -nn 'port 80 or port 443'       # ★★★ 多個

# ═══ ★★ 網段 ═══
$ sudo tcpdump -i any -nn net 10.10.20.0/24
$ sudo tcpdump -i any -nn 'not net 10.10.0.0/16'      # ★★ 排除內網

# ═══ ★★ 協定 ═══
$ sudo tcpdump -i any -nn tcp
$ sudo tcpdump -i any -nn udp
$ sudo tcpdump -i any -nn icmp                        # ★★ ping
$ sudo tcpdump -i any -nn arp                         # ★★ ARP
$ sudo tcpdump -i any -nn 'ip6'                       # IPv6

# ═══ ★★★★ 組合（and / or / not）═══
$ sudo tcpdump -i any -nn 'host 203.0.113.45 and port 443'
$ sudo tcpdump -i any -nn 'src 10.10.20.31 and dst port 3306'
$ sudo tcpdump -i any -nn 'port 443 and not host 10.10.20.99'
$ sudo tcpdump -i any -nn '(src 10.0.0.1 or src 10.0.0.2) and dst port 80'
```

> [!warning] 過濾條件要用引號括起來 ★★★
> ```bash
> # ★★★ 錯誤（shell 會解讀括號和管線）
> $ sudo tcpdump -i any -nn (host a or host b) and port 80
> bash: syntax error near unexpected token `('
>
> # ★★★ 正確
> $ sudo tcpdump -i any -nn '(host a or host b) and port 80'
>
> # ★★ 含 ! 的也要單引號（★ 雙引號中 ! 會被 history expansion 處理）
> $ sudo tcpdump -i any -nn 'not port 22'
> $ sudo tcpdump -i any -nn '! port 22'
> ```

```
★★★★ 排除自己的 SSH 連線（★ 最常用的技巧）

  你 SSH 進伺服器抓包 → ★★★ 抓到的全是你自己的 SSH 流量
  → 而且【抓包的輸出又產生新的 SSH 流量】→ ★★ 無窮迴圈

  ★★★ 解法：
  $ sudo tcpdump -i any -nn 'not port 22'
  $ sudo tcpdump -i any -nn "not host $(echo $SSH_CLIENT | awk '{print $1}')"
  $ sudo tcpdump -i any -nn "not (host ${SSH_CLIENT%% *} and port ${SSH_CLIENT##* })"
```

---

## ★★★ 存檔與 Wireshark

```bash
# ★★★ 存成 pcap
$ sudo tcpdump -i any -nn -w /tmp/capture.pcap port 443
#   ★ Ctrl+C 停止
#   ★★ 存檔時【不會顯示在畫面上】（★ 加 -v 看計數）

$ sudo tcpdump -i any -nn -w /tmp/capture.pcap -c 1000 port 443
1000 packets captured
1024 packets received by filter
0 packets dropped by kernel          # ★★★ 這個數字很重要！

# ★★ 讀檔
$ tcpdump -nn -r /tmp/capture.pcap | head -20
$ tcpdump -nn -r /tmp/capture.pcap 'host 203.0.113.45'   # ★★ 讀檔時再過濾

# ★★ 檔案資訊
$ capinfos /tmp/capture.pcap          # ★ 需要 wireshark-common
$ ls -lh /tmp/capture.pcap
```

> [!danger] `packets dropped by kernel` ★★★★
> ```
> ★★★★ 這個數字不是 0 = 你的抓包【不完整】
>       → 分析結果可能是錯的
>
> 1000 packets captured
> 1024 packets received by filter
> ★★★★ 128 packets dropped by kernel     ← ★ 漏了 128 個
>
> ★★★ 原因與解法：
>   ① 沒加 -n → ★★★ DNS 查詢拖慢 → 【一定要加】
>   ② 寫入磁碟太慢 → ★★ 寫到 tmpfs 或更快的磁碟
>   ③ ★★ 緩衝區太小 → -B 4096（單位 KB）
>   ④ ★★★ 過濾條件太寬 → 縮小範圍（★ 最有效）
>   ⑤ 輸出到終端機太慢 → ★★ 用 -w 存檔而不是印出來
>
> ★★★ 高流量環境的標準寫法：
>   $ sudo tcpdump -i ens18 -nn -B 8192 -s 128 \
>       -w /dev/shm/cap.pcap 'port 443 and host 203.0.113.45'
> ```

```bash
# ═══ ★★★ 只抓標頭（★ 大幅減少檔案大小）═══
$ sudo tcpdump -i any -nn -s 96 -w /tmp/headers.pcap port 443
#   -s 96  ★★ 只抓前 96 bytes（★ 夠看 IP + TCP + 一點應用層）
#   ★★★ 檔案小 10 倍以上，也避免抓到敏感內容

# ★ 各層需要的大小：
#   14 (Ethernet) + 20 (IP) + 20 (TCP) = 54 → ★ -s 64 夠看標頭
#   ★★ -s 96  含少量應用層（看得到 HTTP 的第一行）
#   ★★ -s 128 看得到 TLS 的 SNI
#   -s 0 / 262144  全抓（★ 預設）

# ═══ ★★★ 傳回本機用 Wireshark 分析 ═══
$ scp server:/tmp/capture.pcap .
$ wireshark capture.pcap

# ★★★★ 直接串流到本機的 Wireshark（★ 不用存檔）
$ ssh server 'sudo tcpdump -i any -nn -U -s0 -w - not port 22' | wireshark -k -i -
#   -U  ★★ 不緩衝，即時輸出
#   -w -  寫到 stdout
#   -k -i -  ★★ Wireshark 從 stdin 讀

# ★★ 只要文字分析的話用 tshark
$ tshark -r capture.pcap -Y 'http.request' -T fields \
    -e frame.time -e ip.src -e http.request.full_uri | head
```

### ★★ 長時間抓包（環形緩衝）

```bash
# ★★★ 環形緩衝：抓 10 個檔案，每個 100MB，滿了就覆蓋最舊的
$ sudo tcpdump -i ens18 -nn -s 128 \
    -w /var/log/capture/cap-%Y%m%d-%H%M%S.pcap \
    -C 100 -W 10 -Z tcpdump \
    'port 443 and not host 10.10.20.99'
#   -C 100  ★★ 每個檔案 100 MB
#   -W 10   ★★★ 最多 10 個檔案（★ 循環覆蓋 → 磁碟不會爆）
#   -Z tcpdump  ★★★ 開檔後降權到 tcpdump 使用者
#   ★★★ 總共最多佔 1GB

# ★★ 依時間切檔（每小時一個，保留 24 個）
$ sudo tcpdump -i ens18 -nn -s 128 \
    -w /var/log/capture/cap-%Y%m%d-%H.pcap \
    -G 3600 -W 24 -Z tcpdump 'not port 22'
#   -G 3600  ★★ 每 3600 秒換檔

# ★★★ 做成 systemd 服務（★ 長期蒐證）
$ sudo tee /etc/systemd/system/packet-capture.service >/dev/null <<'EOF'
[Unit]
Description=Rolling packet capture
After=network-online.target

[Service]
Type=simple
ExecStartPre=/bin/mkdir -p /var/log/capture
ExecStart=/usr/bin/tcpdump -i ens18 -nn -s 128 \
  -w /var/log/capture/cap-%%Y%%m%%d-%%H%%M%%S.pcap \
  -C 100 -W 10 -Z tcpdump 'not port 22'
Restart=always
Nice=19
IOSchedulingClass=idle
# ★★ 安全加固
NoNewPrivileges=false
ProtectSystem=strict
ReadWritePaths=/var/log/capture
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
$ sudo useradd -r -s /usr/sbin/nologin tcpdump 2>/dev/null || true
$ sudo mkdir -p /var/log/capture && sudo chown tcpdump:adm /var/log/capture
$ sudo chmod 750 /var/log/capture
$ sudo systemctl daemon-reload && sudo systemctl enable --now packet-capture
```

---

## 完整實戰範例

### 情境一：★★★ 使用者說連不上

```bash
# ═══【1】先確認服務有在聽 ═══
$ sudo ss -lntp | grep :443
LISTEN 0  511  0.0.0.0:443  0.0.0.0:*  users:(("nginx",pid=1234,fd=8))
#   ★★ 有在聽，而且是 0.0.0.0（★ 不是只綁 127.0.0.1）

# ═══ ★★★【2】抓包看封包有沒有到 ═══
$ sudo tcpdump -i any -nn -c 20 'port 443 and host 203.0.113.45'

# ── 情況 A：★★★ 完全沒有輸出 ──
#   → ★★★★ 封包【根本沒到這台機器】
#   → 往上游查：防火牆、NAT、路由、DNS、負載平衡器
$ sudo tcpdump -i any -nn -c 20 'host 203.0.113.45'    # ★★ 拿掉 port 再試
$ dig +short app.example.gov.tw                         # ★★ DNS 指對了嗎？
$ sudo nft list ruleset | grep -A5 443                  # ★ 防火牆

# ── 情況 B：★★★ 只有 SYN，沒有 SYN-ACK ──
14:30:11.123 IP 203.0.113.45.52134 > 10.10.20.31.443: Flags [S], ...
14:30:12.145 IP 203.0.113.45.52134 > 10.10.20.31.443: Flags [S], ...   # ★★ 重傳
14:30:14.189 IP 203.0.113.45.52134 > 10.10.20.31.443: Flags [S], ...   # ★★ 又重傳
#   → ★★★★ 封包有到，但伺服器【沒有回應】
#   → 本機防火牆 DROP、服務沒綁對介面、SYN backlog 滿
$ sudo iptables -L INPUT -n -v | head
$ sudo nft list ruleset
$ ss -lnt 'sport = :443'              # ★★ Send-Q = backlog 上限
$ netstat -s | grep -iE 'listen.*overflow|SYNs to LISTEN'
#   ★★★ overflow 有數字 = backlog 滿了

# ── 情況 C：★★★★ SYN 之後立刻 RST ──
14:30:11.123 IP 203.0.113.45.52134 > 10.10.20.31.443: Flags [S], ...
14:30:11.124 IP 10.10.20.31.443 > 203.0.113.45.52134: Flags [R.], ...
#   → ★★★ 沒有服務在聽這個 port，或防火牆用 reject
$ sudo ss -lntp | grep :443           # ★★ 真的有在聽嗎？
$ sudo nft list ruleset | grep reject

# ── 情況 D：★★ 交握完成但沒有資料 ──
#   Flags [S] → [S.] → [.] → 然後就沒了
#   → ★★★ TCP 沒問題，是【應用層】的問題
#   → ★★ TLS 交握失敗？看 nginx error.log
$ sudo tail -50 /var/log/nginx/error.log
$ openssl s_client -connect 10.10.20.31:443 -servername app.example.gov.tw </dev/null
```

### 情境二：★★★ 上游超時（502）

```bash
# ═══ ★★★★ nginx → php-fpm 走 lo，一定要用 -i lo ═══
$ grep fastcgi_pass /etc/nginx/sites-enabled/app
        fastcgi_pass 127.0.0.1:9000;      # ★★ TCP → 抓得到

$ sudo tcpdump -i lo -nn -A -c 40 port 9000
14:35:11.482 IP 127.0.0.1.44210 > 127.0.0.1.9000: Flags [P.], seq 1:1240, length 1239
...
14:36:11.482 IP 127.0.0.1.44210 > 127.0.0.1.9000: Flags [F.], seq 1240, length 0
#                                                              ↑
#   ★★★★ 60 秒後 nginx 主動關閉 = fastcgi_read_timeout 到了
#   → ★★★ 是 PHP 處理太久，不是網路問題

# ═══ ★★★★ 如果是 Unix socket 就抓不到 ═══
$ grep fastcgi_pass /etc/nginx/sites-enabled/app
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
#   → ★★★★ tcpdump【完全抓不到】（不是網路）
#   → ★★ 替代方案：
$ sudo strace -f -p $(pgrep -f 'php-fpm: pool www' | head -1) -e trace=network -s 200
#   → ★ 或改成 TCP 暫時抓包
#   → ★★★ 或直接看 php-fpm-slow.log（更快）
$ sudo tail -30 /var/log/php8.3-fpm-slow.log
```

### 情境三：★★ 確認第三方 API 送了什麼

```bash
# ★★★ 對方說「我有送 webhook 過來」
$ sudo tcpdump -i any -nn -A -s 0 -c 50 \
    'dst port 443 and src host 198.51.100.77' -w /tmp/webhook.pcap

# ★★ 同時看 nginx 的 access log
$ sudo tail -f /var/log/nginx/access.log | grep webhook

# ★★★ HTTPS 的話看不到內容（加密）→ 三個做法：
#   ① ★★ 在 nginx 層記錄（★ 最簡單）
$ sudo tee /etc/nginx/conf.d/webhook-debug.conf >/dev/null <<'EOF'
log_format webhook escape=json '{"time":"$time_iso8601","ip":"$remote_addr",'
                                '"uri":"$request_uri","status":$status,'
                                '"body":"$request_body"}';
EOF
#   ★★ 在 location 加：
#      client_body_buffer_size 64k;
#      access_log /var/log/nginx/webhook.log webhook;
#   ★★★★ 注意：$request_body 可能含敏感資料，用完要關掉

#   ② ★ 用 mitmproxy 中繼（測試環境）
#   ③ ★★ Wireshark + TLS 金鑰（★ 需要 SSLKEYLOGFILE，只適用自己發起的連線）
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **抓不到任何封包** ★★★ | 介面選錯 | `-i any`；本機用 **`-i lo`** |
| **Unix socket 抓不到** ★★★★ | **那不是網路** | 改用 `strace`；或改成 TCP |
| **輸出全是自己的 SSH** ★★★ | 沒排除 | **`not port 22`** |
| **`dropped by kernel` 不是 0** ★★★★ | 處理不及 | **加 `-n`**；`-s 128`；`-B 8192`；縮小過濾 |
| **很慢、大量遺失** ★★★★ | **沒加 `-n`**（DNS 查詢） | **`-nn`** |
| **`syntax error near '('`** ★★★ | shell 解讀了括號 | **過濾條件用單引號括起來** |
| **`Permission denied`** ★★ | 需要 CAP_NET_RAW | `sudo`；或 `setcap` |
| **`setcap` 後仍不能跑** ★★★ | **AppArmor** | 見下方 |
| **只看到單向流量** ★★★ | 非對稱路由 / 只抓一個介面 | `-i any`；檢查路由 |
| **看不到 HTTPS 內容** ★★★ | **加密** | 在應用層記錄；或用 mitmproxy |
| **磁碟被抓包塞爆** ★★★ | 沒限制 | **`-C` + `-W` 環形緩衝** |
| **抓到的封包很短** ★★ | `-s` 設太小 | `-s 0`（全抓） |
| 容器內抓不到 ★★ | netns 不同 | `nsenter -t PID -n tcpdump` |

### 排查

```bash
# 【1】★★★ 介面確認
$ sudo tcpdump -D
$ ip -br addr
$ ip route get 203.0.113.45           # ★★ 這個目的地走哪個介面

# 【2】★★★ AppArmor（Ubuntu 的常見坑）
$ sudo aa-status | grep -i tcpdump
   /usr/bin/tcpdump
$ sudo dmesg | grep -i 'apparmor.*tcpdump'
[12345.678] audit: apparmor="DENIED" operation="open" profile="/usr/bin/tcpdump" name="/tmp/x.pcap"
#   ★★★ 解法一：寫到 AppArmor 允許的路徑
$ sudo tcpdump -w /var/log/capture/x.pcap ...
#   ★★ 解法二：改成 complain 模式（★ 臨時）
$ sudo aa-complain /usr/bin/tcpdump
#   ★ 解法三：停用該 profile
$ sudo aa-disable /usr/bin/tcpdump

# 【3】★★ 確認過濾條件正確
$ sudo tcpdump -i any -nn -d 'port 443 and host 10.0.0.1'    # ★★ 編譯後的 BPF
$ sudo tcpdump -i any -nn -c 5                                # ★ 先不過濾看有沒有東西

# 【4】★★★ 遺失率
$ sudo tcpdump -i ens18 -nn -c 10000 port 443 2>&1 | tail -3
10000 packets captured
10240 packets received by filter
★★★ 240 packets dropped by kernel

# 【5】★ 混雜模式
$ ip link show ens18 | grep -o PROMISC
#   ★★ tcpdump 預設會開混雜模式（★ 抓不是給自己的封包）
#   ★ -p 停用（★ 在 VM 或雲端環境可能反而抓不到東西）

# 【6】★★ 容器
$ docker inspect -f '{{.State.Pid}}' app
12345
$ sudo nsenter -t 12345 -n tcpdump -i eth0 -nn -c 10
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★★
> ```
> ① ★★★★ 抓包會攔截【所有明文內容】
>      → HTTP 的密碼、Cookie、API token
>      → ★★★ 資料庫查詢（MySQL 3306 預設不加密！）
>      → ★★ 內部 API 的完整內容
>      → ★★★★ 這在法律上可能構成【通訊監察】
>
> ② ★★★★ tcpdump 在 sudoers = 提權
>      → -z 參數可以【以 root 執行任意指令】
>      → ★★★ 用 setcap，或精確限制參數
>
> ③ ★★★ pcap 檔案要當成機密處理
>      → chmod 600、限制存放位置
>      → ★★ 用完要刪
>      → ★★★★ 絕對不要放在 web 可存取的路徑
>
> ④ ★★★ 用 -s 限制擷取長度
>      → -s 96 只抓標頭 → ★★ 排錯夠用，不會抓到內容
>      → ★★★ 這同時是【效能】和【隱私】的最佳做法
>
> ⑤ ★★★ 機關環境要有授權
>      → ★★★★ 抓包 = 可能攔截到他人的通訊
>      → ★ 事前簽核、記錄目的與時間範圍、事後銷毀
> ```

```bash
# ★★★ 安全的抓包（★ 標準寫法）
$ sudo tcpdump -i ens18 -nn -s 96 -Z tcpdump \
    -c 1000 -w /var/log/capture/debug-$(date +%F-%H%M).pcap \
    'host 203.0.113.45 and port 443'
#   -s 96      ★★★ 只抓標頭（不含內容）
#   -Z tcpdump ★★★ 開檔後降權
#   -c 1000    ★★ 限制數量
#   ★★ 精確的過濾條件（★ 不是全抓）

$ sudo chmod 600 /var/log/capture/*.pcap
$ sudo chown root:adm /var/log/capture/*.pcap

# ★★★ 檢查 pcap 有沒有敏感內容（★ 分享前一定要做）
$ tcpdump -r /tmp/capture.pcap -A 2>/dev/null | \
    grep -iE 'password|passwd|token|authorization|cookie|secret|api[_-]?key' | head
#   ★★★★ 有東西的話不要分享

# ★★ 去識別化（★ 需要 tcprewrite / tcpdump-anon）
$ tcprewrite --infile=capture.pcap --outfile=anon.pcap \
    --pnat=203.0.113.0/24:198.51.100.0/24

# ★★★ 用完銷毀
$ sudo shred -u /var/log/capture/*.pcap
$ sudo find /var/log/capture -name '*.pcap' -mtime +7 -exec shred -u {} \;

# ★★ 稽核記錄
$ sudo tee -a /var/log/capture/AUDIT.md >/dev/null <<EOF
$(date -Is) | $(whoami) | 目的: 排查 203.0.113.45 連線問題 |
  過濾: host 203.0.113.45 and port 443 | -s 96 (僅標頭) |
  檔案: debug-$(date +%F-%H%M).pcap | 預計刪除: $(date -d '+7 days' +%F)
EOF
```

```bash
# ★★★★ 提醒：MySQL / Redis / 內部 API 的流量通常沒加密
$ sudo tcpdump -i lo -nn -A -c 20 port 3306 | grep -iE 'select|insert|password'
#   → ★★★★ 看得到完整的 SQL 語句
#   → ★★★ 這也是為什麼【內部通訊也該加密】（見 [[090-01-10-guide-PKI-憑證部署到各服務]]）
```

---

## 速查表

### ★★★★ 標準起手式

```bash
sudo tcpdump -i any -nn -c 20 'port 443 and not port 22'
#            ↑      ↑    ↑     ↑
#         介面   ★★★★不解析  限量   ★★★ 排除自己的 SSH
```

### 必加選項

```
-i any / lo / ens18   ★★★ 本機服務間用 lo
-nn                   ★★★★ 一定要加（★ 否則大量遺失）
-c N                  ★★★ 限制數量
-s 96                 ★★★ 只抓標頭（效能 + 隱私）
-w file.pcap          ★★★ 存檔
-Z tcpdump            ★★★ 降權
```

### 過濾

```bash
host / src host / dst host 10.0.0.1
port / src port / dst port 443    portrange 8000-8100
net 10.10.20.0/24                 not net 10.0.0.0/8
tcp / udp / icmp / arp
'(host a or host b) and port 80'  # ★★★ 單引號！
'not port 22'                     # ★★★ 排除 SSH
```

### ★★★★ TCP Flags

```
S   SYN      要連線
S.  SYN-ACK  同意
.   ACK      確認
P.  PSH+ACK  ★★ 有資料
F.  FIN      正常關閉
★★★★ R.  RST  強制中斷 ← 最重要的排錯訊號

只看 SYN/RST：
sudo tcpdump -i any -nn 'tcp[tcpflags] & (tcp-syn|tcp-rst) != 0'
```

### ★★★ 四種連線失敗的指紋

```
完全沒封包        → ★★★★ 沒到這台（防火牆/NAT/路由/DNS）
SYN 重傳無回應    → ★★★ 本機防火牆 DROP / backlog 滿
SYN → RST        → ★★★ 沒服務在聽 / reject
交握完成無資料    → ★★★ 應用層問題（TLS / 程式）
```

### ★★★ 存檔與分析

```bash
sudo tcpdump -i any -nn -s 128 -w /tmp/c.pcap -c 1000 port 443
tcpdump -nn -r /tmp/c.pcap 'host 10.0.0.1'     # ★★ 讀檔再過濾
ssh srv 'sudo tcpdump -i any -U -s0 -w - not port 22' | wireshark -k -i -
tshark -r c.pcap -Y 'http.request' -T fields -e ip.src -e http.host
★★★★ 一定要看 "packets dropped by kernel" 是不是 0
```

### 環形緩衝

```bash
sudo tcpdump -i ens18 -nn -s 128 -w /var/log/capture/cap-%Y%m%d-%H%M%S.pcap \
     -C 100 -W 10 -Z tcpdump 'not port 22'
#    ★★ 每檔 100MB，最多 10 檔（★ 磁碟不會爆）
#    -G 3600 -W 24  依時間切檔
```

### ★★★★ 安全

```
-s 96          只抓標頭（不含內容）
-Z tcpdump     降權
chmod 600      pcap 當機密處理
shred -u       用完銷毀
★★★★ sudoers 絕對不要允許 -z 和 -w（提權漏洞）
★★★ 用 setcap cap_net_raw,cap_net_admin=eip /usr/bin/tcpdump
```

---

## 練習題

> [!question]- 練習 1：基本抓包 ★★
> 1. `sudo tcpdump -D` 列出介面
> 2. **`sudo tcpdump -i any -nn -c 10 port 443`** 然後開一個網頁
> 3. **找出三次交握的三個封包**（`[S]` `[S.]` `[.]`）
> 4. **不加 `-n` 再抓一次** → 輸出有什麼不同？慢嗎？
> 5. 抓 10000 個封包，**看 `dropped by kernel` 是多少**
> 6. **加 `-s 96` 再測** → 有差嗎？

> [!question]- 練習 2：四種失敗指紋 ★★★★
> 1. **抓一個正常的連線**存成 `ok.pcap`
> 2. `sudo systemctl stop nginx` → 抓連線 → **看到什麼 flag？**
> 3. 啟動 nginx，用 `nft`/`iptables` DROP 443 → 抓 → **呢？**
> 4. 改成 REJECT → **呢？**
> 5. **四種情況的封包長什麼樣？各對應什麼問題？**
> 6. `curl` 的錯誤訊息分別是什麼？

> [!question]- 練習 3：本機服務 ★★★
> 1. **`sudo tcpdump -i ens18 -nn port 9000`** 然後訪問網頁 → 抓到嗎？
> 2. **改成 `-i lo`** → 呢？**為什麼？**
> 3. 把 `fastcgi_pass` 改成 Unix socket，reload
> 4. **再用 `-i lo` 抓** → 抓得到嗎？
> 5. **為什麼？該怎麼查？**
> 6. 用 `strace -e trace=network` 試試看

> [!question]- 練習 4：存檔與 Wireshark ★★★
> 1. `sudo tcpdump -i any -nn -s 0 -w /tmp/c.pcap -c 500 port 443`
> 2. **`ls -lh` 看檔案大小**
> 3. **改成 `-s 96` 再抓一次** → 大小差多少？
> 4. `tcpdump -r /tmp/c.pcap 'host <某IP>'` 二次過濾
> 5. **傳回本機用 Wireshark 開啟，用 Follow TCP Stream**
> 6. **`tcpdump -r c.pcap -A | grep -i cookie`** → 找得到什麼？

> [!question]- 練習 5：安全 ★★★★
> 1. **抓 MySQL 的流量：`sudo tcpdump -i lo -nn -A -c 30 port 3306`**
> 2. 同時跑 `mysql -e "SELECT * FROM users LIMIT 1"`
> 3. **看得到 SQL 語句嗎？看得到資料嗎？**
> 4. **這說明什麼？**（內部通訊要不要加密）
> 5. `sudo setcap cap_net_raw,cap_net_admin=eip $(which tcpdump)` → 不用 sudo 能跑嗎？
> 6. **試試 `sudo tcpdump -i lo -w /tmp/x -W 1 -G 1 -z id`** → `-z` 做了什麼？**這代表什麼風險？**

---

## 小測驗

Q1. **`-n` 為什麼是必加的選項**？不加會怎樣？

Q2. **nginx 連 php-fpm 抓不到封包，兩個可能原因**？分別怎麼處理？

Q3. **`Flags [S]` `[S.]` `[.]` `[P.]` `[F.]` `[R.]` 各代表什麼**？

Q4. **只看到 SYN 一直重傳但沒有 SYN-ACK，代表什麼**？往哪查？

Q5. **SYN 之後立刻收到 RST，三種可能原因**？

Q6. **`packets dropped by kernel` 不是 0 為什麼嚴重**？五個解法？

Q7. **`length 517` 和 `length 0` 的差別**？排錯上有什麼意義？

Q8. **為什麼過濾條件要用單引號括起來**？

Q9. **長時間抓包怎麼避免塞爆磁碟**？

Q10. **為什麼 `tcpdump` 寫進 sudoers 是提權漏洞**？正確做法？

> [!question]- 測驗答案
> **Q1.** **`-n` 停用反向 DNS 解析**（`-nn` 連 port 名稱也不解析）。
> **不加的三個後果**：
> ①**★★★ 大量封包遺失** —— tcpdump 對**每一個看到的 IP** 發一次反向 DNS 查詢，
> 查詢是同步且慢的（幾十到幾百毫秒），這段時間封包來不及處理就被核心丟掉，
> `dropped by kernel` 會很高，**分析結果因此不可靠**；
> ②**★★★ 產生新的封包干擾抓包** —— DNS 查詢本身是網路流量，
> 如果你的過濾條件包含 port 53 或該 DNS 伺服器，會看到自己造成的封包；
> ③**★★ 高流量時可能拖垮機器**。
> **所以標準寫法一律是 `-nn`**，這是效能問題而不是顯示偏好。
> 需要看主機名的話，事後用 `dig -x` 查就好。
>
> **Q2.** ①**★★★ 走的是 lo 而不是實體介面** ——
> `fastcgi_pass 127.0.0.1:9000` 的流量走 loopback，
> `-i ens18` 完全抓不到。**解法：`-i lo` 或 `-i any`**；
> ②**★★★★ 用的是 Unix socket** ——
> `fastcgi_pass unix:/run/php/php8.3-fpm.sock`
> **根本不是網路通訊，tcpdump 抓不到任何東西**（它抓的是網路介面上的封包）。
> **解法**：
> `strace -f -p <pid> -e trace=network -s 200` 看 socket 的讀寫；
> 或臨時改成 TCP（`127.0.0.1:9000`）抓包；
> **或直接看 `php-fpm-slow.log`**（通常這個更快找到答案）。
> 這是很常見的困惑 —— 「明明有流量卻抓不到」。
>
> **Q3.** **`[S]` = SYN**，要建立連線（三次交握的第一步）；
> **`[S.]` = SYN-ACK**，同意建立（`.` 就是 ACK 旗標）；
> **`[.]` = 純 ACK**，確認收到；
> **`[P.]` = PSH+ACK**，**有應用層資料**且要求立刻交給應用程式；
> **`[F.]` = FIN+ACK**，正常關閉連線（四次揮手的一部分）；
> **`[R.]` = RST**，**強制中斷連線** —— 這是排錯時**最重要的訊號**。
> 完整的交握：`[S]` → `[S.]` → `[.]`，之後才開始 `[P.]` 傳資料。
> 只過濾 SYN 和 RST：
> ```bash
> sudo tcpdump -i any -nn 'tcp[tcpflags] & (tcp-syn|tcp-rst) != 0'
> ```
>
> **Q4.** **★★★★ 封包有到達這台機器，但伺服器完全沒有回應** ——
> 客戶端沒收到 SYN-ACK 所以不斷重傳（通常 1s、2s、4s、8s 指數退避）。
> **三個往下查的方向**：
> ①**★★★ 本機防火牆 DROP**（不是 REJECT，REJECT 會回 RST）：
> ```bash
> sudo nft list ruleset
> sudo iptables -L INPUT -n -v
> ```
> ②**★★ 服務沒綁對介面** —— 只綁 `127.0.0.1` 但從外部連：
> ```bash
> sudo ss -lntp | grep :443     # ★ 看 Local Address 是 0.0.0.0 還是 127.0.0.1
> ```
> ③**★★★ SYN backlog 滿了** —— 連線太多，核心直接丟棄：
> ```bash
> netstat -s | grep -iE 'listen.*overflow|SYNs to LISTEN'
> ss -lnt 'sport = :443'        # Send-Q 就是 backlog 上限
> ```
> 對照 `curl` 的錯誤是 **`Connection timed out`**（不是 refused）。
>
> **Q5.** ①**★★★ 那個 port 沒有服務在聽** ——
> 核心收到 SYN 但沒有程序在監聽，直接回 RST。
> 對應 `curl` 的 **`Connection refused`**。用 `ss -lntp` 確認；
> ②**★★ 防火牆用 REJECT 而不是 DROP** ——
> REJECT 會主動回應（RST 或 ICMP unreachable），DROP 則是靜默丟棄。
> 注意這個 RST **可能是中間的防火牆設備發的，不是伺服器**；
> ③**★★★ 服務在聽但立刻拒絕** ——
> 例如 backlog 滿了、`tcp_abort_on_overflow=1`、
> 或應用程式有 IP 白名單/連線數限制。
> **判斷技巧**：看 RST 的**來源 IP 和 TTL** ——
> 如果 TTL 跟正常回應的封包差很多，那個 RST 很可能是中間設備偽造的。
>
> **Q6.** 因為**你的抓包是不完整的，基於它做的任何分析都可能是錯的** ——
> 你可能因為「沒看到 SYN-ACK」而斷定伺服器沒回應，
> 但其實 SYN-ACK 有回，只是被丟掉了。
> **五個解法**：
> ①**★★★★ 加 `-n`/`-nn`** —— DNS 查詢是最常見的原因；
> ②**★★★ 縮小過濾條件** —— 最有效，只抓真正需要的
> （`host X and port Y` 而不是全抓）；
> ③**★★ 用 `-s 96` 限制擷取長度** —— 每個封包只存標頭，處理和寫入都快很多；
> ④**★★ 加大緩衝區 `-B 8192`**（單位 KB）；
> ⑤**★★ 用 `-w` 存檔而不是印到終端機**，
> 而且**寫到 `/dev/shm`（tmpfs）** 而不是慢速磁碟。
> 高流量環境的標準寫法把這些全部組合起來。
>
> **Q7.** **`length` 是「應用層資料」的長度，不含 TCP/IP 標頭**。
> `[S]`、`[S.]`、純 `[.]` ACK 的 length 都是 0（交握和確認不帶資料）；
> **`[P.] length 517` 表示這個封包帶了 517 bytes 的實際內容**。
> **排錯上的意義**：
> ①**只看到交握（全是 length 0）沒有任何資料** →
> **TCP 層沒問題，是應用層沒送東西** ——
> 可能是 TLS 交握失敗、程式卡住、或在等對方先說話；
> ②**一直有 length 0 的 ACK 往返** → 可能在互相等待（協定實作問題）；
> ③配合 `win`（接收視窗）看 —— **`win 0` 表示對方的接收緩衝滿了，處理不過來**。
> 只過濾有資料的封包：
> ```bash
> sudo tcpdump -i any -nn 'tcp and (ip[2:2] - ((ip[0]&0xf)<<2) - ((tcp[12]&0xf0)>>2)) != 0'
> ```
>
> **Q8.** 因為 **BPF 過濾語法用的字元和 shell 的特殊字元重疊**：
> **`(` `)`** 是 shell 的子 shell 語法 → `syntax error near unexpected token '('`；
> **`|`** 是管線；**`!`** 在互動式 bash 會觸發 history expansion；
> **`<` `>`** 是重導向；空白會被拆成多個參數。
> **單引號讓 shell 完全不解讀內容，原樣傳給 tcpdump**：
> ```bash
> sudo tcpdump -i any -nn '(host a or host b) and port 80'    # ★★★ 正確
> sudo tcpdump -i any -nn 'not port 22'
> sudo tcpdump -i any -nn 'tcp[tcpflags] & tcp-rst != 0'
> ```
> **要用單引號不是雙引號** —— 雙引號中 `!` 和 `$` 仍會被展開。
> 驗證過濾條件是否正確編譯：`tcpdump -d '<條件>'` 會印出 BPF 組合語言。
>
> **Q9.** **★★★ 用環形緩衝（`-C` + `-W`）**：
> ```bash
> sudo tcpdump -i ens18 -nn -s 128 \
>   -w /var/log/capture/cap-%Y%m%d-%H%M%S.pcap \
>   -C 100 -W 10 -Z tcpdump 'not port 22'
> ```
> **`-C 100`** = 每個檔案最大 100 MB；
> **`-W 10`** = **最多保留 10 個檔案，滿了就從第一個開始覆蓋** ——
> 總佔用**固定在 1 GB**，永遠不會爆。
> **依時間切檔**：`-G 3600 -W 24`（每小時一檔，保留 24 小時）。
> **另外三個要點**：
> ①**`-s 128` 只抓標頭** —— 檔案小 10 倍以上；
> ②**精確的過濾條件** —— 不要全抓；
> ③**`-Z tcpdump` 降權** —— 開檔後放棄 root 權限。
> 做成 systemd 服務（`Nice=19`、`IOSchedulingClass=idle`）就能長期蒐證，
> 等間歇性問題發生時再回頭撈。
>
> **Q10.** 因為 **tcpdump 有兩個參數可以達成任意程式碼執行或任意檔案寫入**：
> ①**★★★★ `-z` 參數指定的指令會以 root 執行**
> （原意是給檔案輪替後做壓縮用）：
> ```bash
> sudo tcpdump -i lo -w /tmp/x -W 1 -G 1 -z /bin/bash
> # ★★★★ 換檔時執行 /bin/bash → root shell
> ```
> ②**★★★ `-w` 可以寫入任意路徑**（例如 `/etc/cron.d/`）。
> **正確做法**（優先順序）：
> ①**★★★ 用 `setcap`，完全不需要 sudo**：
> ```bash
> sudo setcap cap_net_raw,cap_net_admin=eip $(which tcpdump)
> ```
> ②sudoers 精確限制參數，**絕對不允許 `-z` 和 `-w`**；
> ③包一層專用腳本，腳本只做固定的事（固定的介面、過濾、輸出路徑）。
> 同類問題的還有 `find -exec`、`awk system()`、`tar --checkpoint-action`、
> `less`/`vim` 的 shell 逃逸 —— 可以在 **GTFOBins** 查到完整清單。

---

## 延伸閱讀

- [[060-01-04-02-guide-tcpdump-進階過濾與實戰]] — BPF 語法、重傳分析、TLS 排查
- [[060-01-04-03-guide-ss-netstat-與lsof]] — 抓包前先看連線狀態
- [[020-01-16-cmd-Linux-網路基礎指令]] — `ip` / `ping` / `traceroute`
- [[060-01-04-05-guide-curl-與HTTP除錯]] — 應用層的排查
- [[020-02-01-07-svc-SSH-安全強化]] — 內部通訊加密
- [[090-01-10-guide-PKI-憑證部署到各服務]] — 為什麼內部服務也要 TLS
