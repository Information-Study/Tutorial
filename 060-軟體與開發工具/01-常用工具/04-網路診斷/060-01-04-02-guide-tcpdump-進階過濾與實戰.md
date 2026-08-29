---
title: "tcpdump 進階過濾與實戰"
desc: "BPF 位元運算、重傳與 MTU 分析、TLS 交握排查與 tshark"
aliases: [BPF, tcpdump 進階, TCP 重傳, MTU, MSS, TLS 排查, tshark]
tags: [群組/軟體與開發工具, 主題/網路診斷, 主題/tcpdump]
category: 常用工具
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[060-01-04-01-guide-tcpdump-基礎抓包]]"]
updated: 2026-08-28
---

# tcpdump 進階過濾與實戰

> [!abstract] 這篇你會學到
> - **★★★ BPF 的位元運算語法**（`proto[offset:size]`）
> - **★★★★ 只抓 HTTP GET / TLS Client Hello** 的過濾式
> - **★★★ TCP 重傳、亂序、零視窗**的判讀
> - **★★★★ MTU / MSS 與黑洞問題**（最難查的網路故障之一）
> - **★★★ TLS 交握失敗**的完整排查
> - `tshark` 的統計與欄位擷取
> - **★★ 非對稱路由與 VLAN**

## 前置知識

- [[060-01-04-01-guide-tcpdump-基礎抓包]] — 介面、基本過濾、輸出判讀

---

## ★★★ BPF 位元運算

```
★★★★ 語法：proto[offset:size] 運算子 值

  proto   ether / ip / ip6 / tcp / udp / icmp
  offset  ★★ 從該協定【標頭開頭】算起的位元組偏移
  size    1 / 2 / 4（★ 預設 1）

★★★ 常用的偏移量：

  ip[0]      版本(4bit) + IHL(4bit)     → ★★ ip[0] & 0x0f = 標頭長度(4字組)
  ip[1]      TOS / DSCP
  ip[2:2]    ★★★ 總長度
  ip[6:2]    ★★★ flags(3bit) + 分片偏移(13bit)
  ip[8]      TTL
  ip[9]      ★★ 協定（6=TCP, 17=UDP, 1=ICMP）
  ip[12:4]   來源 IP
  ip[16:4]   目的 IP

  tcp[0:2]   來源 port
  tcp[2:2]   目的 port
  tcp[4:4]   序號
  tcp[8:4]   確認號
  tcp[12]    ★★★ 資料偏移(4bit) + 保留 → tcp[12] & 0xf0 >> 2 = 標頭長度
  tcp[13]    ★★★★ flags（★ 也可以寫成 tcp[tcpflags]）
  tcp[14:2]  ★★ 視窗大小
  tcp[20:...] ★★★ 應用層資料的開始（★ 標頭 20 bytes 無選項時）
```

```bash
# ═══ ★★★★ TCP flags 的位元 ═══
#   bit:  7    6    5    4    3    2    1    0
#         CWR  ECE  URG  ACK  PSH  RST  SYN  FIN
#   值:   128  64   32   16   8    4    2    1

# ★★★ 用具名常數（★ 比數字好讀）
$ sudo tcpdump -i any -nn 'tcp[tcpflags] & tcp-syn != 0'          # 有 SYN
$ sudo tcpdump -i any -nn 'tcp[tcpflags] & tcp-rst != 0'          # ★★★ 有 RST
$ sudo tcpdump -i any -nn 'tcp[tcpflags] == tcp-syn'              # ★★★ 只有 SYN（新連線）
$ sudo tcpdump -i any -nn 'tcp[tcpflags] == (tcp-syn|tcp-ack)'    # ★★ SYN-ACK
$ sudo tcpdump -i any -nn 'tcp[tcpflags] & (tcp-fin|tcp-rst) != 0'  # ★★★ 任何關閉

# ★ 等價的數字寫法
$ sudo tcpdump -i any -nn 'tcp[13] & 2 != 0'                      # SYN
$ sudo tcpdump -i any -nn 'tcp[13] == 2'                          # 只有 SYN
$ sudo tcpdump -i any -nn 'tcp[13] & 4 != 0'                      # RST
```

### ★★★★ 常用的實戰過濾式

```bash
# ═══ ★★★★ 只抓 HTTP GET 請求 ═══
$ sudo tcpdump -i any -nn -A 'tcp port 80 and tcp[((tcp[12:1] & 0xf0) >> 2):4] = 0x47455420'
#   ★★ 0x47455420 = "GET " 的 ASCII
#   ★★★ ((tcp[12:1] & 0xf0) >> 2) = TCP 標頭長度（★ 動態計算，含選項）

# ★★ POST
$ sudo tcpdump -i any -nn -A 'tcp port 80 and tcp[((tcp[12:1] & 0xf0) >> 2):4] = 0x504f5354'
#   0x504f5354 = "POST"

# ★★ 任何 HTTP 方法（GET/POST/PUT/HEAD/DELE）
$ sudo tcpdump -i any -nn -A 'tcp port 80 and (
    tcp[((tcp[12:1] & 0xf0) >> 2):4] = 0x47455420 or
    tcp[((tcp[12:1] & 0xf0) >> 2):4] = 0x504f5354 or
    tcp[((tcp[12:1] & 0xf0) >> 2):4] = 0x50555420 or
    tcp[((tcp[12:1] & 0xf0) >> 2):4] = 0x48454144)'

# ═══ ★★★★ TLS Client Hello（★ 排查 SNI 與版本問題）═══
$ sudo tcpdump -i any -nn 'tcp port 443 and
    tcp[((tcp[12:1] & 0xf0) >> 2)] = 0x16 and
    tcp[((tcp[12:1] & 0xf0) >> 2)+5] = 0x01'
#   0x16 = TLS Handshake record type
#   0x01 = Client Hello（在 record 後第 5 個 byte）

# ★★★ TLS Alert（★ 交握失敗）
$ sudo tcpdump -i any -nn -X 'tcp port 443 and tcp[((tcp[12:1] & 0xf0) >> 2)] = 0x15'
#   0x15 = Alert record

# ═══ ★★★ 只抓有應用層資料的封包（排除純 ACK）═══
$ sudo tcpdump -i any -nn 'tcp and (ip[2:2] - ((ip[0]&0x0f)<<2) - ((tcp[12]&0xf0)>>2)) != 0'
#   ★★ IP 總長度 - IP 標頭 - TCP 標頭 = 應用層資料長度

# ═══ ★★★ IP 分片 ═══
$ sudo tcpdump -i any -nn 'ip[6] & 0x20 != 0 or ip[6:2] & 0x1fff != 0'
#   0x20 = MF (More Fragments) 旗標
#   ★★★ 0x1fff = 分片偏移不為 0 → 這是後續的分片

# ★★★★ DF（Don't Fragment）旗標
$ sudo tcpdump -i any -nn 'ip[6] & 0x40 != 0'

# ═══ ★★★ ICMP 類型 ═══
$ sudo tcpdump -i any -nn 'icmp[icmptype] = icmp-echo'              # ping 請求
$ sudo tcpdump -i any -nn 'icmp[icmptype] = icmp-unreach'           # ★★★ 不可達
$ sudo tcpdump -i any -nn 'icmp[icmptype] = 3 and icmp[icmpcode] = 4'
#   ★★★★ type 3 code 4 = "需要分片但設了 DF" → MTU 問題！
$ sudo tcpdump -i any -nn 'icmp[icmptype] = icmp-timxceed'          # TTL 超時

# ═══ ★★ VLAN ═══
$ sudo tcpdump -i any -nn 'vlan'                     # 有 VLAN tag 的
$ sudo tcpdump -i any -nn 'vlan 100'                 # ★★ 特定 VLAN
$ sudo tcpdump -i any -nn -e 'vlan and port 443'     # ★★ -e 顯示 tag

# ═══ ★★ 封包大小 ═══
$ sudo tcpdump -i any -nn 'greater 1400'             # ★★ 大於 1400 bytes
$ sudo tcpdump -i any -nn 'less 100'
$ sudo tcpdump -i any -nn 'ip[2:2] > 1400'           # ★ 用 IP 總長度

# ═══ ★★ 特定 MAC ═══
$ sudo tcpdump -i any -nn -e 'ether host ba:12:cd:34:ef:56'
$ sudo tcpdump -i any -nn -e 'ether broadcast'
$ sudo tcpdump -i any -nn -e 'ether multicast'
```

> [!tip] `((tcp[12:1] & 0xf0) >> 2)` 為什麼這樣寫 ★★★
> ```
> ★★★ 這是【動態計算 TCP 標頭長度】的標準寫法
>
>   tcp[12]        = Data Offset(4bit) + Reserved(4bit)
>   & 0xf0         = ★★ 取高 4 bit（Data Offset）
>   >> 2           = ★★★ 右移 2 = 除以 4 再乘以 4
>                    → Data Offset 的單位是「32 位元字組」
>                    → 值 5 = 5×4 = 20 bytes（★ 無選項）
>                    → 值 8 = 8×4 = 32 bytes（★ 有 12 bytes 選項）
>
> ★★★★ 為什麼不直接寫 tcp[20]？
>   → ★★ 因為 TCP 標頭【長度是變動的】（有 MSS、SACK、時間戳等選項）
>   → 現代的 TCP 幾乎都有選項 → 標頭通常是 32 bytes 不是 20
>   → ★★★ 寫死 tcp[20] 會抓錯位置
> ```

---

## ★★★ TCP 重傳與亂序

```bash
# ★★★★ 用 -S 顯示絕對序號（★ 分析重傳必備）
$ sudo tcpdump -i any -nn -S -c 50 'host 203.0.113.45 and port 443'
14:23:11.100 IP 10.10.20.31.443 > 203.0.113.45.52134: Flags [P.], seq 1000:2448, ack 518, length 1448
14:23:11.320 IP 10.10.20.31.443 > 203.0.113.45.52134: Flags [P.], seq 1000:2448, ack 518, length 1448
#                                                              ↑ ★★★★ 同樣的 seq = 重傳！
14:23:11.740 IP 10.10.20.31.443 > 203.0.113.45.52134: Flags [P.], seq 1000:2448, ack 518, length 1448
#   ★★★ 間隔 220ms → 440ms → 指數退避

# ★★★ 用 tshark 直接標出重傳（★ 比 tcpdump 好用太多）
$ sudo tshark -i any -f 'port 443' -Y 'tcp.analysis.retransmission' \
    -T fields -e frame.time_relative -e ip.src -e ip.dst -e tcp.seq -e tcp.len

# ★★★★ 統計重傳率
$ sudo tshark -r capture.pcap -q -z io,stat,0,\
"COUNT(tcp)tcp",\
"COUNT(tcp.analysis.retransmission)tcp.analysis.retransmission",\
"COUNT(tcp.analysis.duplicate_ack)tcp.analysis.duplicate_ack"

# ★★ 系統層的重傳統計
$ netstat -s | grep -iE 'retransmit|segments retransmited'
    2840 segments retransmited              # ★★★ 對照總傳送數算比率
$ nstat -az | grep -iE 'TcpRetransSegs|TcpOutSegs'
$ sar -n ETCP 1 5
```

```
★★★★ 三種常見的 TCP 異常：

【① 重傳（retransmission）】
   同一個 seq 出現多次
   → ★★★ 封包遺失（★ 網路品質差、擁塞、中間設備丟包）
   → ★★ 判斷門檻：重傳率 > 1% 就要處理
   → ★★★ 對照 sar -n ETCP 的 retrans/s

【② 重複 ACK（duplicate ACK）】
   連續多個相同的 ack 號
   14:23:11.400 IP B > A: Flags [.], ack 2448    ← 第 1 個
   14:23:11.402 IP B > A: Flags [.], ack 2448    ← ★★ dup ACK
   14:23:11.404 IP B > A: Flags [.], ack 2448    ← ★★★ 3 個 → 觸發快速重傳
   → ★★★ 表示【中間有封包遺失】，接收端在提示

【③ 零視窗（zero window）】★★★★
   14:23:11.500 IP B > A: Flags [.], ack 5000, win 0
                                                   ↑ ★★★★
   → ★★★★ 接收端的緩衝區滿了，【叫對方停止傳送】
   → ★★★ 原因：接收端的應用程式處理不過來
     · PHP-FPM worker 全忙
     · 應用程式卡在資料庫
     · ★★ 磁碟寫入太慢
   → ★★★★ 這是【應用層問題】不是網路問題！
```

```bash
# ★★★★ 抓零視窗（★ 很有價值的訊號）
$ sudo tcpdump -i any -nn 'tcp[14:2] = 0 and tcp[tcpflags] & tcp-rst = 0'
$ sudo tshark -i any -Y 'tcp.analysis.zero_window' \
    -T fields -e ip.src -e ip.dst -e tcp.srcport -e tcp.dstport

# ★★★ 完整的 TCP 問題統計
$ sudo tshark -r capture.pcap -Y 'tcp.analysis.flags' \
    -T fields -e tcp.analysis.flags 2>/dev/null | sort | uniq -c | sort -rn
    142 tcp.analysis.retransmission
     89 tcp.analysis.duplicate_ack
     12 tcp.analysis.zero_window          # ★★★★ 應用層瓶頸
      8 tcp.analysis.out_of_order
```

---

## ★★★★ MTU / MSS 與黑洞問題

```
★★★★ 這是最難查的網路故障之一：
     「小的請求正常，大的請求就卡住」
     「SSH 能連但 scp 大檔案會斷」
     「網頁能開但圖片載不出來」

★★★ 名詞：
  MTU  = 一個乙太網框能承載的最大 IP 封包（★ 通常 1500）
  MSS  = TCP 能放的最大資料量 = MTU - IP標頭(20) - TCP標頭(20) = 1460

★★★★ 問題的成因：
  ① 路徑上有一段 MTU 比較小（★ VPN、PPPoE、GRE 隧道、雲端 overlay）
  ② 大封包設了 DF（Don't Fragment）旗標
  ③ ★★★★ 中間設備該回「ICMP type 3 code 4（需要分片）」
     → 但【防火牆把 ICMP 全擋了】
  ④ → 發送端不知道要縮小封包 → 一直重傳 → ★★★ 連線卡死
  → ★★★★ 這叫【PMTU 黑洞】（Path MTU Discovery blackhole）
```

```bash
# ═══ ★★★★【診斷 1】看 SYN 交握中協商的 MSS ═══
$ sudo tcpdump -i any -nn -v 'tcp[tcpflags] & tcp-syn != 0' -c 4
14:23:11.482 IP (tos 0x0, ttl 64, id 0, offset 0, flags [DF], proto TCP (6), length 60)
    10.10.20.31.443 > 203.0.113.45.52134: Flags [S.], seq ..., options [mss 1460,...]
#                                                                        ↑
#   ★★★ 雙方宣告的 MSS（★ 取兩邊較小者）

# ═══ ★★★★【診斷 2】用 ping 測實際的 PMTU ═══
$ ping -M do -s 1472 -c 3 203.0.113.45
#   ★★ -M do = 設定 DF 旗標（不允許分片）
#   ★★★ -s 1472 = ICMP 資料 1472 + ICMP標頭 8 + IP標頭 20 = 1500

PING 203.0.113.45 56(84) bytes of data.
ping: local error: message too long, mtu=1500
#   ★★ 或
From 10.10.20.1 icmp_seq=1 Frag needed and DF set (mtu = 1400)
#                                                        ↑ ★★★★ 找到了！路徑 MTU 是 1400

# ★★★ 二分法找出實際的 MTU
$ for s in 1472 1440 1400 1372 1300; do
    printf "%-6s " "$((s+28))"
    ping -M do -s "$s" -c 1 -W 2 203.0.113.45 >/dev/null 2>&1 \
      && echo "✓ 通過" || echo "✗ 失敗"
  done
1500   ✗ 失敗
1468   ✗ 失敗
1428   ✓ 通過                          # ★★★★ 實際 MTU 約 1428
1400   ✓ 通過
1328   ✓ 通過

# ★★ 用 tracepath 自動偵測
$ tracepath -n 203.0.113.45
 1?: [LOCALHOST]        pmtu 1500
 1:  10.10.20.1         0.412ms
 2:  10.10.20.1         0.389ms  pmtu 1400      # ★★★★ 這一跳降到 1400
 3:  203.0.113.45       12.104ms reached
     Resume: pmtu 1400 hops 3 back 3

# ═══ ★★★★【診斷 3】抓包看有沒有 ICMP 訊息 ═══
$ sudo tcpdump -i any -nn 'icmp[icmptype] = 3 and icmp[icmpcode] = 4'
14:23:12.104 IP 10.10.20.1 > 10.10.20.31: ICMP 203.0.113.45 unreachable -
    need to frag (mtu 1400), length 556
#   ★★★ 有這個訊息 = PMTU discovery 正常運作

#   ★★★★ 【完全沒有這個訊息，但大封包一直重傳】= PMTU 黑洞！
$ sudo tcpdump -i any -nn -S 'host 203.0.113.45' | grep -E 'length 1[0-9]{3}'
#   ★★ 看到同一個大封包一直重傳，卻沒有任何 ICMP → 確認是黑洞
```

```bash
# ═══ ★★★ 處置方案 ═══

# ★★ 方案一：調整介面 MTU（★ 治本，但要確定路徑）
$ ip link show ens18 | grep -o 'mtu [0-9]*'
mtu 1500
$ sudo ip link set dev ens18 mtu 1400        # ★ 臨時
# ★★ 永久（netplan）
$ sudo tee /etc/netplan/60-mtu.yaml >/dev/null <<'EOF'
network:
  version: 2
  ethernets:
    ens18:
      mtu: 1400
EOF
$ sudo netplan apply

# ★★★ 方案二：MSS clamping（★ 只影響 TCP，最常用）
#   在 nftables
$ sudo nft add table inet mangle 2>/dev/null
$ sudo nft add chain inet mangle forward '{ type filter hook forward priority -150; }' 2>/dev/null
$ sudo nft add rule inet mangle forward tcp flags syn tcp option maxseg size set rt mtu
#   ★★★ "set rt mtu" = 自動依路由的 MTU 調整

#   ★ iptables 版本
$ sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu

# ★★★ 方案三：nginx / 應用層（★ 只在特定路由）
$ sudo ip route change 203.0.113.0/24 via 10.10.20.1 dev ens18 advmss 1360

# ★★ 方案四：允許 ICMP type 3（★ 治本！）
$ sudo nft add rule inet filter input icmp type destination-unreachable accept
$ sudo iptables -A INPUT -p icmp --icmp-type fragmentation-needed -j ACCEPT
#   ★★★★ 很多資安設定「擋掉所有 ICMP」是錯的
#      → ★★★ type 3 code 4 是 TCP 正常運作【必要】的

# ★★ 啟用 PMTU 黑洞偵測（★ 核心層的補救）
$ sudo sysctl -w net.ipv4.tcp_mtu_probing=1
$ echo 'net.ipv4.tcp_mtu_probing = 1' | sudo tee /etc/sysctl.d/60-mtu.conf
#   0 = 停用  1 = ★★ 偵測到黑洞時啟用  2 = 一律啟用
```

> [!danger] 「擋掉所有 ICMP」是常見的錯誤資安設定 ★★★★
> ```
> ★★★★ 很多防火牆設定會寫「DROP all ICMP」
>       理由是「避免被 ping 掃描」
>
> ★★★★ 但這會【破壞 TCP 的正常運作】：
>   · ICMP type 3 code 4（需要分片）→ ★★★ PMTU discovery 依賴它
>   · 擋掉 → PMTU 黑洞 → 大封包永遠送不出去
>   · ★★ 症狀非常詭異：小請求正常、大請求卡死
>
> ★★★ 正確的做法：
>   · 擋 ICMP echo request（★ 避免被 ping 掃描）—— 可以
>   · ★★★★ 但一定要放行 type 3（destination unreachable）
>   · ★★ 建議也放行 type 11（time exceeded，traceroute 需要）
>
> $ sudo nft add rule inet filter input icmp type { destination-unreachable, time-exceeded } accept
> $ sudo nft add rule inet filter input icmp type echo-request drop
> ```

---

## ★★★ TLS 交握排查

```bash
# ═══ ★★★ 先用 openssl 測（★ 比抓包快）═══
$ openssl s_client -connect app.example.gov.tw:443 \
    -servername app.example.gov.tw -showcerts </dev/null 2>&1 | head -40
CONNECTED(00000003)
depth=2 C=US, O=Internet Security Research Group, CN=ISRG Root X1
verify return:1
...
SSL handshake has read 4820 bytes and written 391 bytes
New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
Verify return code: 0 (ok)                      # ★★★ 0 = 成功

# ★★ 常見的失敗
Verify return code: 21 (unable to verify the first certificate)
#   ★★★★ 伺服器沒送中繼憑證！（見 [[090-01-13-guide-PKI-憑證常見問題排查]]）

# ★★ 指定 TLS 版本測試
$ openssl s_client -connect host:443 -tls1_2 </dev/null 2>&1 | grep -E 'Protocol|Cipher'
$ openssl s_client -connect host:443 -tls1_3 </dev/null 2>&1 | grep -E 'Protocol|Cipher'

# ═══ ★★★★ 抓包看交握 ═══
$ sudo tcpdump -i any -nn -c 20 -X 'host app.example.gov.tw and port 443'

# ★★★ 用 tshark 直接解析 TLS（★ 好用太多）
$ sudo tshark -i any -f 'port 443' -Y 'tls.handshake' -V 2>/dev/null | \
    grep -E 'Handshake Type|Version|Server Name|Cipher Suite:|Alert'

# ★★★★ 只看關鍵欄位
$ sudo tshark -i any -f 'port 443' \
    -Y 'tls.handshake.type == 1 or tls.handshake.type == 2 or tls.alert_message' \
    -T fields \
    -e frame.time_relative -e ip.src -e ip.dst \
    -e tls.handshake.type \
    -e tls.handshake.extensions_server_name \
    -e tls.handshake.version \
    -e tls.alert_message.desc
0.000   203.0.113.45  10.10.20.31  1  app.example.gov.tw  0x0303
0.002   10.10.20.31   203.0.113.45 2                      0x0303
0.045   10.10.20.31   203.0.113.45                              48
#                                                               ↑
#   ★★★★ alert 48 = unknown_ca（★ 客戶端不信任你的 CA）
```

```
★★★★ 常見的 TLS Alert 代碼：

  40  handshake_failure       ★★★ 沒有共同的密碼套件或協定版本
  42  bad_certificate         ★★ 憑證格式有問題
  43  unsupported_certificate
  44  certificate_revoked     ★★ 憑證被撤銷
  45  certificate_expired     ★★★★ 憑證過期
  46  certificate_unknown
  47  illegal_parameter
  48  ★★★★ unknown_ca         客戶端不信任簽發的 CA
  49  access_denied
  50  decode_error
  51  decrypt_error
  70  protocol_version        ★★★ TLS 版本不相容
  80  internal_error
  112 ★★★ unrecognized_name   SNI 對不上任何 server_name
  116 certificate_required    ★★ 需要客戶端憑證（mTLS）
```

```bash
# ★★★★ SNI 對不上（alert 112）的排查
$ sudo tshark -i any -f 'port 443' -Y 'tls.handshake.type == 1' \
    -T fields -e tls.handshake.extensions_server_name
api.example.gov.tw                    # ★★ 客戶端送的 SNI

$ sudo nginx -T 2>/dev/null | grep -E 'server_name|listen.*443'
    listen 443 ssl;
    server_name app.example.gov.tw;   # ★★★★ 沒有 api.example.gov.tw！
#   → ★★★ 會用 default_server 或第一個 server 區塊
#   → ★ 憑證對不上 → 客戶端拒絕

# ★★★ 檢查 default_server
$ sudo nginx -T 2>/dev/null | grep -B2 -A8 'default_server'

# ★★ 測試不同 SNI
$ for sni in app.example.gov.tw api.example.gov.tw wrong.example.com; do
    printf "%-25s " "$sni"
    openssl s_client -connect 10.10.20.31:443 -servername "$sni" </dev/null 2>/dev/null | \
      openssl x509 -noout -subject 2>/dev/null || echo "失敗"
  done
app.example.gov.tw        subject=CN = app.example.gov.tw
api.example.gov.tw        subject=CN = app.example.gov.tw     # ★★★ 對不上！
wrong.example.com         subject=CN = app.example.gov.tw
```

---

## tshark ★★★

```bash
$ sudo apt install -y tshark          # ★ 安裝時問「非 root 可否抓包」選 Yes
$ sudo usermod -aG wireshark "$USER"  # ★★ 重新登入後生效
```

```bash
# ═══ ★★★ 統計 ═══
$ tshark -r capture.pcap -q -z conv,tcp | head -15        # ★★★ TCP 對話
$ tshark -r capture.pcap -q -z endpoints,ip | head -10    # ★★ 端點統計
$ tshark -r capture.pcap -q -z io,stat,10                 # ★★ 每 10 秒的流量
$ tshark -r capture.pcap -q -z http,tree                  # ★★★ HTTP 統計
$ tshark -r capture.pcap -q -z expert                     # ★★★★ 專家診斷（★ 直接列出問題）

# ★★★★ expert 的輸出範例
Errors (12)
  Frequency  Group       Protocol  Summary
         12  Malformed   TCP       [Malformed Packet]
Warnings (284)
        142  Sequence    TCP       This frame is a (suspected) retransmission
         89  Sequence    TCP       Duplicate ACK
         12  Sequence    TCP       ★★★★ Zero window
         41  Sequence    TCP       Previous segment not captured

# ═══ ★★★ 欄位擷取 ═══
$ tshark -r capture.pcap -Y 'http.request' -T fields \
    -e frame.time -e ip.src -e http.request.method -e http.host -e http.request.uri
$ tshark -r capture.pcap -Y 'dns' -T fields -e dns.qry.name -e dns.a | sort -u
$ tshark -r capture.pcap -Y 'tcp.flags.reset == 1' -T fields \
    -e frame.time_relative -e ip.src -e ip.dst -e tcp.srcport -e tcp.dstport

# ═══ ★★★ 顯示過濾器（★ 比 BPF 強大很多）═══
$ tshark -r capture.pcap -Y 'http.response.code >= 500'
$ tshark -r capture.pcap -Y 'tcp.analysis.retransmission'
$ tshark -r capture.pcap -Y 'tcp.time_delta > 1'          # ★★★ 延遲超過 1 秒
$ tshark -r capture.pcap -Y 'tls.alert_message'
$ tshark -r capture.pcap -Y 'ip.addr == 10.0.0.1 && tcp.port == 443'

# ═══ ★★★★ 跟蹤一個 TCP stream ═══
$ tshark -r capture.pcap -q -z follow,tcp,ascii,0
#   ★ 最後的 0 是 stream 編號
$ tshark -r capture.pcap -T fields -e tcp.stream | sort -un | head    # ★ 有哪些 stream

# ═══ ★★ 即時擷取 + 過濾 ═══
$ sudo tshark -i any -f 'port 443' -Y 'tls.handshake.type == 1' \
    -T fields -e tls.handshake.extensions_server_name
```

> [!tip] BPF（`-f`）與顯示過濾器（`-Y`）的差別 ★★★
> ```
> ★★★ -f  【擷取過濾器】（BPF，同 tcpdump）
>      → ★★★★ 在【核心層】過濾 → 不符合的封包【根本不會被複製】
>      → ★ 效能好，但語法簡單（只能看標頭欄位）
>      → ★★ 高流量時【一定要用】
>
> ★★★ -Y  【顯示過濾器】（Wireshark 語法）
>      → ★★ 封包已經擷取後再過濾
>      → ★★★★ 功能強大：能看應用層、能用 tcp.analysis.*、能算延遲
>      → ★ 但所有封包都要先處理 → 高流量時會遺失
>
> ★★★★ 最佳實務：
>   $ sudo tshark -i any -f 'port 443 and host 10.0.0.1' \
>                        -Y 'tls.handshake.type == 1'
>   → ★★ 用 -f 縮小範圍（核心層），用 -Y 精確篩選（應用層）
> ```

---

## 完整實戰範例：間歇性的連線中斷

```bash
# ═══ 情境 ═══
#   使用者：「每隔十幾分鐘，系統就會卡一下，然後自己恢復」
#   ★★ 應用層的 log 只有零星的 "connection reset by peer"

# ═══ ★★★【1】長時間抓包（環形緩衝）═══
$ sudo mkdir -p /var/log/capture && sudo chown tcpdump:adm /var/log/capture
$ sudo tcpdump -i ens18 -nn -s 128 -Z tcpdump \
    -w /var/log/capture/cap-%Y%m%d-%H%M%S.pcap -C 50 -W 20 \
    'host 10.10.20.50 and not port 22' &
#   ★★ 每檔 50MB × 20 = 1GB 上限

# ═══ ★★★【2】同時記錄系統指標 ═══
$ vmstat -tw 5 720 > /tmp/vmstat.log &
$ while true; do
    echo "$(date -Is) $(ss -s | grep -oP 'estab \K[0-9]+') $(cat /proc/net/netstat | \
      awk '/TcpExt:/{if(++n==2) print $NF}')"
    sleep 5
  done > /tmp/conn.log &

# ═══ 【3】等問題發生（★ 使用者回報 15:42 卡住）═══

# ═══ ★★★★【4】分析對應時段 ═══
$ ls -lt /var/log/capture/ | head -3
-rw-r----- 1 tcpdump adm 50M Aug 28 15:44 cap-20260828-154012.pcap
-rw-r----- 1 tcpdump adm 50M Aug 28 15:41 cap-20260828-153822.pcap

# ★★★★ 先用 expert 快速掃一遍
$ tshark -r /var/log/capture/cap-20260828-154012.pcap -q -z expert 2>/dev/null
Warnings (1284)
   Frequency  Group     Protocol  Summary
         842  Sequence  TCP       ★★★★ This frame is a (suspected) retransmission
         312  Sequence  TCP       Duplicate ACK
          89  Sequence  TCP       ★★★★ Zero window
          41  Sequence  TCP       Previous segment not captured

# ★★★ 找出零視窗發生的時間
$ tshark -r /var/log/capture/cap-20260828-154012.pcap \
    -Y 'tcp.analysis.zero_window' \
    -T fields -e frame.time -e ip.src -e ip.dst -e tcp.srcport 2>/dev/null | head
Aug 28, 2026 15:42:03  10.10.20.50  10.10.20.31  3306
Aug 28, 2026 15:42:04  10.10.20.50  10.10.20.31  3306
#                        ↑ ★★★★ 資料庫伺服器叫我們停止傳送！

# ★★★ 找出重傳集中的時段
$ tshark -r /var/log/capture/cap-20260828-154012.pcap \
    -Y 'tcp.analysis.retransmission' -T fields -e frame.time 2>/dev/null | \
    awk '{print $1,$2,$3,substr($4,1,5)}' | uniq -c | sort -rn | head -5
    284 Aug 28, 2026 15:42                # ★★★★ 15:42 集中爆發
     42 Aug 28, 2026 15:43
      8 Aug 28, 2026 15:38

# ═══ ★★★【5】對照系統指標 ═══
$ awk '$18 ~ /15:42/' /tmp/vmstat.log
 r  b   swpd   free  cache   si  so   bi    bo   in    cs us sy id wa st  時間
 2 12 131072 204800 716800   0   0  8400  62000 12400 24800 18 22  8 52 0  15:42:03
#     ↑                                          ↑     ↑              ↑
#  ★★★★ 12 個等 I/O                 ★★★ 中斷/切換暴增      ★★★★ wa 52%

# ═══ ★★★★【6】到資料庫伺服器查 ═══
$ ssh 10.10.20.50 'sar -u -s 15:40:00 -e 15:45:00'
03:42:01 PM  CPU  %user %nice %system %iowait %steal %idle
03:42:01 PM  all  12.24  0.00   8.42   68.31   0.00  11.03    # ★★★★ iowait 68%

$ ssh 10.10.20.50 'sudo mysql -e "SHOW GLOBAL STATUS LIKE \"Innodb_buffer_pool_wait_free\""'
Innodb_buffer_pool_wait_free    1284           # ★★★★ buffer pool 不夠，一直等 flush

$ ssh 10.10.20.50 'sudo grep -c "15:4[0-5]" /var/log/mysql/mysql-slow.log'
284

# ★★★ 是不是有排程作業
$ ssh 10.10.20.50 'crontab -l -u mysql; ls /etc/cron.d/'
*/15 * * * * /usr/local/bin/generate-report.sh      # ★★★★ 每 15 分鐘！
#   → ★★★★ 對上了「每隔十幾分鐘卡一下」

# ═══ ★★★★【7】根因 ═══
#   每 15 分鐘的報表排程 → 大量查詢 → InnoDB buffer pool 不夠 →
#   → 狂 flush 到磁碟 → I/O 飽和 → 資料庫回應變慢 →
#   → ★★★ TCP 接收緩衝滿 → 送出 zero window →
#   → 應用端無法傳送 → 逾時 → connection reset

# ═══ 【8】處置 ═══
#   ① ★★★ 報表改成離峰執行（凌晨）+ 讀取複本
#   ② ★★ 調大 innodb_buffer_pool_size
#   ③ ★★ 報表查詢加索引
#   ④ ★ 加 innodb_io_capacity 讓 flush 更平順

# ═══ 【9】驗證 ═══
$ tshark -r /var/log/capture/cap-新的.pcap -q -z expert 2>/dev/null | grep -i zero
#   ★★★ 沒有零視窗了
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **BPF 過濾寫 `tcp[20]` 抓不到** ★★★ | TCP 標頭長度是變動的 | **`((tcp[12:1] & 0xf0) >> 2)`** |
| **小請求正常、大請求卡死** ★★★★ | **PMTU 黑洞** | `ping -M do -s`；MSS clamping；放行 ICMP type 3 |
| **看到大量 zero window** ★★★★ | **接收端應用處理不過來** | **查應用層，不是網路** |
| **重傳很多** ★★★ | 封包遺失 | `sar -n ETCP`；查中間設備 |
| **`tshark -Y` 遺失封包** ★★★ | 顯示過濾器在使用者空間 | **先用 `-f` 縮小範圍** |
| **TLS alert 48** ★★★★ | 客戶端不信任 CA | 派送根憑證；檢查憑證鏈 |
| **TLS alert 112** ★★★ | **SNI 對不上** | 檢查 `server_name`、`default_server` |
| **TLS alert 40** ★★★ | 沒有共同密碼套件 | 檢查 `ssl_protocols`/`ssl_ciphers` |
| **只看到單向流量** ★★★ | 非對稱路由 | `ip route get`；兩端同時抓 |
| **VLAN 環境抓不到** ★★ | 沒處理 tag | `-e`；`vlan and ...` |
| `tshark` 要 root ★★ | 群組沒設 | `usermod -aG wireshark`；重新登入 |

### 排查

```bash
# 【1】★★ 驗證 BPF 過濾式
$ sudo tcpdump -d 'tcp port 80 and tcp[((tcp[12:1] & 0xf0) >> 2):4] = 0x47455420'
#   ★ 印出編譯後的 BPF 組合語言，語法錯會直接報錯

# 【2】★★★ MTU 測試
$ tracepath -n <目的地>
$ ping -M do -s 1472 -c 2 <目的地>
$ ip route get <目的地>                    # ★★ 看走哪個介面、advmss
$ ip link show <介面> | grep -o 'mtu [0-9]*'

# 【3】★★★ TCP 異常統計
$ tshark -r cap.pcap -q -z expert 2>/dev/null | head -20
$ netstat -s | grep -iE 'retrans|reset|overflow|prune'
$ nstat -az | grep -iE 'Tcp(Ext)?(Retrans|Abort|Loss|Timeout)'

# 【4】★★ TLS
$ openssl s_client -connect host:443 -servername sni </dev/null 2>&1 | \
    grep -E 'Verify return code|Protocol|Cipher'
$ sudo tshark -i any -f 'port 443' -Y 'tls.alert_message' \
    -T fields -e ip.src -e tls.alert_message.desc

# 【5】★★ 非對稱路由（兩端同時抓）
#   在 A：
$ sudo tcpdump -i any -nn -w /tmp/a.pcap 'host B'
#   在 B：
$ sudo tcpdump -i any -nn -w /tmp/b.pcap 'host A'
#   ★★★ 比對兩邊看到的封包數
$ tcpdump -r /tmp/a.pcap 2>/dev/null | wc -l
$ tcpdump -r /tmp/b.pcap 2>/dev/null | wc -l
#   ★★★★ 差很多 = 有封包在中間被丟掉

# 【6】★ VLAN
$ sudo tcpdump -i ens18 -nn -e -c 10 vlan
$ ip -d link show ens18.100
```

---

## 安全性注意事項

> [!danger] 四個要點 ★★★
> ```
> ① ★★★★ 進階過濾常常需要抓完整封包（-s 0）
>      → ★★★ 會擷取到完整的應用層內容
>      → ★★ 只在必要時用，用完立刻刪除
>
> ② ★★★ tshark 的 -Y 會【解析應用層協定】
>      → HTTP 的完整內容、DNS 查詢、SMTP 內容
>      → ★★★★ follow,tcp,ascii 會印出完整的對話
>      → ★★ 這比 tcpdump 更容易洩漏資料
>
> ③ ★★★ TLS 排查不需要解密
>      → ★★ SNI、憑證、alert 都在【明文的交握階段】
>      → ★★★★ 不要為了排查而配置 TLS 解密（★ 那會破壞前向保密）
>
> ④ ★★ pcap 分析結果也是敏感資訊
>      → conv/endpoints 統計會暴露內部拓撲
>      → ★ 分享前清理
> ```

```bash
# ★★★ 排查 TLS 只需要交握階段（★ 不需要 -s 0）
$ sudo tcpdump -i any -nn -s 256 -c 100 -w /tmp/tls.pcap \
    'tcp port 443 and (tcp[((tcp[12:1] & 0xf0) >> 2)] = 0x16 or
                       tcp[((tcp[12:1] & 0xf0) >> 2)] = 0x15)'
#   ★★ 只抓 Handshake(0x16) 和 Alert(0x15) 的 record
#   ★★★ -s 256 夠看 SNI 和憑證的開頭，不會抓到應用資料

# ★★★ 檢查 pcap 是否含敏感內容
$ tshark -r /tmp/capture.pcap -T fields -e http.authorization \
    -e http.cookie -e http.file_data 2>/dev/null | grep -v '^$' | head
$ tcpdump -r /tmp/capture.pcap -A 2>/dev/null | \
    grep -iE 'authorization:|cookie:|password=|token=|api[_-]?key' | head
#   ★★★★ 有東西的話絕對不能外流

# ★★ 只留標頭的去識別化版本
$ editcap -s 96 capture.pcap capture-headers.pcap     # ★ 截斷每個封包
$ tcprewrite --infile=capture.pcap --outfile=anon.pcap \
    --pnat=10.10.20.0/24:192.0.2.0/24

# ★★★ 銷毀
$ shred -u /tmp/*.pcap /var/log/capture/*.pcap
```

---

## 速查表

### ★★★★ BPF 位元運算

```bash
tcp[tcpflags] & tcp-rst != 0          # ★★★ RST
tcp[tcpflags] == tcp-syn              # ★★★ 只有 SYN（新連線）
tcp[14:2] = 0                         # ★★★★ 零視窗
ip[6] & 0x40 != 0                     # DF 旗標
icmp[icmptype]=3 and icmp[icmpcode]=4 # ★★★★ 需要分片（MTU）

# ★★★ TCP 標頭長度是變動的，用這個算應用層起點：
((tcp[12:1] & 0xf0) >> 2)
tcp[((tcp[12:1] & 0xf0) >> 2):4] = 0x47455420      # "GET "
tcp[((tcp[12:1] & 0xf0) >> 2)] = 0x16              # ★★★ TLS Handshake
tcp[((tcp[12:1] & 0xf0) >> 2)] = 0x15              # ★★★ TLS Alert
```

### ★★★★ 三種 TCP 異常

```
重傳          同一 seq 多次      → ★★★ 封包遺失（網路）
重複 ACK      連續相同 ack       → ★★★ 中間有遺失
★★★★ 零視窗   win 0             → 【接收端應用處理不過來】← 不是網路問題

tshark -r c.pcap -q -z expert          # ★★★★ 一次列出所有問題
tshark -Y 'tcp.analysis.zero_window'
netstat -s | grep -i retrans
```

### ★★★★ MTU 黑洞

```bash
tracepath -n <目的地>                       # ★★★ 自動偵測 PMTU
ping -M do -s 1472 -c 3 <目的地>            # ★★★ 1472+28=1500
sudo tcpdump -i any -nn 'icmp[icmptype]=3 and icmp[icmpcode]=4'
#   ★★★★ 大封包一直重傳 + 沒有這個 ICMP = 黑洞

# 處置
sudo nft add rule inet mangle forward tcp flags syn tcp option maxseg size set rt mtu
sudo sysctl -w net.ipv4.tcp_mtu_probing=1
★★★★ 防火牆一定要放行 icmp type 3（不要 DROP all ICMP）
```

### ★★★ TLS Alert

```
40 handshake_failure   密碼套件/版本不合
45 certificate_expired ★★★★ 憑證過期
48 unknown_ca          ★★★★ 不信任 CA（★ 缺中繼憑證或未派送根憑證）
70 protocol_version    TLS 版本不合
112 unrecognized_name  ★★★ SNI 對不上 server_name

openssl s_client -connect host:443 -servername sni </dev/null
tshark -Y 'tls.alert_message' -T fields -e tls.alert_message.desc
```

### tshark

```bash
-f 'BPF'      ★★★★ 核心層過濾（高流量必用）
-Y '顯示過濾'  ★★★ 功能強（tcp.analysis.* / http.response.code）
-q -z expert           ★★★★ 專家診斷
-q -z conv,tcp         對話統計
-q -z follow,tcp,ascii,0   ★★ 跟蹤 stream
-T fields -e ip.src -e http.host    欄位擷取
```

### ★★★ 安全

```bash
-s 256 只抓 TLS 交握（不含應用資料）
tshark -r c.pcap -e http.authorization -e http.cookie   # ★★ 分享前檢查
editcap -s 96 in.pcap out.pcap                          # ★ 截斷
shred -u *.pcap                                         # ★★ 銷毀
```

---

## 練習題

> [!question]- 練習 1：BPF 位元運算 ★★★
> 1. **用 `tcpdump -d` 驗證幾個過濾式的語法**
> 2. 寫一個只抓 HTTP GET 的過濾式並測試
> 3. **改成抓 POST**（`0x504f5354`）
> 4. **寫一個只抓 TLS Client Hello 的**
> 5. `tcp[20]` 和 `((tcp[12:1] & 0xf0) >> 2)` 差在哪？**實測看看**
> 6. **寫一個「排除純 ACK」的過濾式**

> [!question]- 練習 2：MTU 黑洞 ★★★★
> 1. `tracepath -n 8.8.8.8` → PMTU 是多少？
> 2. **`ping -M do -s 1472` 通過嗎？**
> 3. **把介面 MTU 改成 1400，再從另一台送 1500 的封包**
> 4. 抓 `icmp[icmptype]=3 and icmp[icmpcode]=4` → **有嗎？**
> 5. **用防火牆擋掉所有 ICMP，再測一次** → 症狀變成什麼？
> 6. **設 MSS clamping 再測** → 解決了嗎？

> [!question]- 練習 3：TCP 異常 ★★★★
> 1. 用 `tc` 製造封包遺失：`sudo tc qdisc add dev lo root netem loss 5%`
> 2. **抓包並用 `tshark -q -z expert` 分析**
> 3. 重傳率是多少？
> 4. **改成 `netem delay 200ms 50ms`** → expert 說什麼？
> 5. **移除：`sudo tc qdisc del dev lo root`**
> 6. **怎麼製造零視窗？**（提示：接收端不讀取 socket）

> [!question]- 練習 4：TLS 排查 ★★★
> 1. **用 `openssl s_client` 測自己的網站** → `Verify return code` 是多少？
> 2. **用一個不存在的 SNI 測** → 拿到哪張憑證？
> 3. 抓 `tls.alert_message` → 有 alert 嗎？代碼是？
> 4. **故意只放伺服器憑證（不含中繼）** → 客戶端看到什麼 alert？
> 5. **用 `-tls1_1` 測** → 呢？
> 6. **只抓交握不抓內容的過濾式怎麼寫？**

> [!question]- 練習 5：完整實戰 ★★★★
> 1. **設定環形緩衝的長時間抓包（systemd 服務）**
> 2. 同時記錄 `vmstat`
> 3. 用 `ab -n 50000 -c 200` 製造壓力
> 4. **分析對應時段的 pcap，用 `-z expert`**
> 5. **有零視窗嗎？對照 `vmstat` 的哪一欄？**
> 6. **寫一份包含 pcap 證據的排查報告**（★ 記得清理敏感資料）

---

## 小測驗

Q1. **為什麼過濾應用層資料要寫 `((tcp[12:1] & 0xf0) >> 2)` 而不是直接寫 `tcp[20]`**？

Q2. **看到大量「零視窗（zero window）」代表什麼**？該往哪個方向查？

Q3. **「小請求正常、大檔案傳輸卡死」最可能是什麼問題**？三步驟診斷？

Q4. **為什麼「DROP all ICMP」是錯誤的防火牆設定**？至少要放行哪兩種？

Q5. **TLS alert 48 和 112 分別代表什麼**？各自怎麼處理？

Q6. **`tshark` 的 `-f` 和 `-Y` 差在哪**？高流量時該怎麼組合？

Q7. **`tshark -q -z expert` 為什麼是分析 pcap 的第一個指令**？

Q8. **重傳、重複 ACK、零視窗三者中，哪一個「不是網路問題」**？

Q9. **排查 TLS 交握問題需要解密流量嗎**？為什麼？

Q10. **兩端同時抓包，A 看到 1000 個封包但 B 只看到 400 個，說明什麼**？

> [!question]- 測驗答案
> **Q1.** 因為 **TCP 標頭的長度是變動的** ——
> 基本標頭是 20 bytes，但**現代的 TCP 幾乎都帶選項**
> （MSS、SACK permitted、Window Scale、Timestamps），
> 實際標頭通常是 **32 bytes 甚至更長**。
> 寫死 `tcp[20]` 會指到**選項欄位的中間**，抓錯位置。
> **`((tcp[12:1] & 0xf0) >> 2)` 的拆解**：
> `tcp[12]` 的高 4 bit 是 **Data Offset**（標頭長度，單位是 32 位元字組）；
> `& 0xf0` 取出高 4 bit；
> **`>> 2` 等於「除以 16 再乘以 4」** ——
> 把 4 bit 的值移到低位（`>>4`）再乘以 4（`<<2`），合併就是 `>>2`。
> 值 5 → 20 bytes（無選項）；值 8 → 32 bytes（12 bytes 選項）。
> 這是動態計算應用層資料起點的標準寫法。
>
> **Q2.** **★★★★ 接收端的 TCP 接收緩衝區滿了，主動叫對方停止傳送** ——
> `win 0` 是接收端明確告訴發送端「我現在一個 byte 都收不下」。
> **關鍵洞見：這是應用層問題，不是網路問題** ——
> 緩衝區滿的原因是**接收端的應用程式沒有及時把資料從 socket 讀走**：
> ①**PHP-FPM worker 全忙**，沒有人來讀；
> ②**應用程式卡在資料庫或外部 API**；
> ③**磁碟寫入太慢**（應用程式在寫檔案）；
> ④應用程式有 bug（單執行緒被某個操作阻塞）。
> **往哪查**：接收端那台機器的
> `first60`、應用的 status 頁（`listen queue`）、慢日誌、`iostat`。
> **不要去調網路參數** —— 那治不了根因。
> ```bash
> tshark -Y 'tcp.analysis.zero_window' -T fields -e ip.src -e tcp.srcport
> ```
>
> **Q3.** **★★★★ PMTU 黑洞（Path MTU Discovery blackhole）**。
> 路徑上某一段的 MTU 比較小（VPN、PPPoE、GRE 隧道、雲端 overlay 網路），
> 大封包帶著 DF 旗標過不去，中間設備**應該回 ICMP type 3 code 4**
> 告訴發送端「需要分片，MTU 是 1400」——
> 但**防火牆把 ICMP 全擋了**，發送端永遠不知道要縮小封包，
> 於是一直重傳同一個大封包，連線就卡死了。
> **三步驟診斷**：
> ```bash
> # ① 自動偵測路徑 MTU
> tracepath -n <目的地>
> # ② 手動二分法確認
> ping -M do -s 1472 -c 3 <目的地>     # 1472+8+20=1500
> # ③ ★★★★ 看有沒有 ICMP（沒有就是黑洞）
> sudo tcpdump -i any -nn 'icmp[icmptype]=3 and icmp[icmpcode]=4'
> ```
> **處置**：MSS clamping（最常用）、調整介面 MTU、
> **放行 ICMP type 3**、`net.ipv4.tcp_mtu_probing=1`。
>
> **Q4.** 因為 **ICMP 不只是 ping，它是 IP 協定正常運作的一部分**。
> 「擋掉所有 ICMP 避免被掃描」聽起來合理，但會**破壞 TCP**。
> **至少要放行兩種**：
> ①**★★★★ type 3（Destination Unreachable）** ——
> 特別是 **code 4（Fragmentation Needed）**，
> **Path MTU Discovery 完全依賴它**。擋掉就造成 PMTU 黑洞，
> 症狀是「小請求正常、大請求卡死」，極難排查；
> ②**★★ type 11（Time Exceeded）** ——
> `traceroute`/`tracepath` 需要它，而且 TTL 過期的診斷也靠它。
> **可以擋的是 type 8（Echo Request）** —— 那才是 ping 掃描。
> ```bash
> sudo nft add rule inet filter input icmp type { destination-unreachable, time-exceeded } accept
> sudo nft add rule inet filter input icmp type echo-request drop
> ```
>
> **Q5.** **alert 48 = `unknown_ca`** ——
> **客戶端不信任簽發這張憑證的 CA**。兩個常見原因：
> ①**伺服器沒送中繼憑證**（只送了自己的憑證），
> 客戶端無法建立到根憑證的信任鏈 ——
> 解法是用 `fullchain.pem`（伺服器憑證 + 中繼憑證）而不是單獨的憑證；
> ②**用的是自建 CA，但客戶端沒有安裝根憑證** ——
> 解法是派送根憑證到客戶端的信任存放區。
> **alert 112 = `unrecognized_name`** ——
> **客戶端送的 SNI 對不上任何 `server_name`**。
> nginx 會 fallback 到 `default_server` 或第一個 server 區塊，
> 拿到的憑證跟請求的網域對不上，客戶端就拒絕。
> ```bash
> sudo nginx -T | grep -E 'server_name|default_server'
> openssl s_client -connect IP:443 -servername <要測的網域> </dev/null | \
>   openssl x509 -noout -subject
> ```
>
> **Q6.** **`-f` 是擷取過濾器（BPF 語法，和 tcpdump 相同）** ——
> **在核心層過濾，不符合的封包根本不會被複製到使用者空間**，
> 效能非常好，但語法只能操作標頭欄位。
> **`-Y` 是顯示過濾器（Wireshark 語法）** ——
> **封包已經被擷取並完整解析之後**才過濾，
> 功能強大得多：可以用 `tcp.analysis.retransmission`、
> `http.response.code >= 500`、`tcp.time_delta > 1`、`tls.alert_message`，
> 但**所有封包都要先處理**，高流量時會大量遺失。
> **★★★ 高流量時要組合使用**：
> ```bash
> sudo tshark -i any -f 'port 443 and host 10.0.0.1' \
>                    -Y 'tls.handshake.type == 1'
> ```
> **用 `-f` 在核心層把量降下來，用 `-Y` 做精確的應用層篩選**。
>
> **Q7.** 因為 **它會一次列出 pcap 裡「所有 Wireshark 認得的問題」**，
> 不用你自己一條一條想要查什麼：
> ```
> Warnings (1284)
>    842  Sequence  TCP  This frame is a (suspected) retransmission
>    312  Sequence  TCP  Duplicate ACK
>     12  Sequence  TCP  ★★★★ Zero window
>     41  Sequence  TCP  Previous segment not captured
> ```
> 這一份輸出立刻告訴你**問題的類型和量級**：
> 大量重傳 → 網路遺失；
> 有零視窗 → 應用層瓶頸；
> `Previous segment not captured` → 抓包本身可能有遺失（要檢討抓包方式）；
> `Malformed Packet` → 協定實作問題或抓包截斷。
> **有了方向再用 `-Y` 深入**特定類型。
> 這比從第一個封包開始一行一行看快幾十倍。
>
> **Q8.** **★★★★ 零視窗（zero window）不是網路問題**。
> **重傳**和**重複 ACK** 都指向**封包在網路上遺失了** ——
> 中間設備丟包、線路品質差、緩衝區溢位、擁塞控制作用。
> 這些要往**網路層**查：交換器的介面錯誤計數、中間防火牆、
> 頻寬是否飽和、`sar -n ETCP` 的 retrans/s。
> **零視窗則是接收端明確說「我的緩衝滿了，別再送」** ——
> 封包**完全沒有遺失，網路很健康**，
> 問題出在**接收端的應用程式沒有及時把資料讀走**。
> 這要往**應用層**查：worker 數量、慢查詢、磁碟 I/O、程式阻塞。
> **搞錯方向會浪費大量時間** ——
> 看到零視窗卻去調 TCP 參數或換網路設備，完全不會有幫助。
>
> **Q9.** **★★★ 不需要**。
> TLS 排查最需要的資訊**全部都在明文的交握階段**：
> **SNI**（Client Hello 的擴充欄位，明文）、
> **協定版本與密碼套件**（Client/Server Hello，明文）、
> **伺服器憑證鏈**（TLS 1.2 明文；TLS 1.3 加密但可用 `openssl s_client` 取得）、
> **Alert 代碼**（明確指出失敗原因）。
> 只有**應用層資料**是加密的，而那通常不是 TLS 問題的所在。
> **不該為了排查而配置解密**：
> ①TLS 1.3 的**前向保密（PFS）** 讓伺服器私鑰無法解密歷史流量，
> 要解密就得停用 PFS 或改用弱密碼套件 —— **等於降低安全性**；
> ②`SSLKEYLOGFILE` 只能用於你自己發起的連線，且會留下金鑰檔案。
> **正確做法**：`-s 256` 只抓交握 record（0x16/0x15），
> 加上 `openssl s_client` 和 nginx 的 error log。
>
> **Q10.** **★★★★ 有大約 600 個封包在中間被丟掉了**，
> 或是 **B 的抓包本身有遺失**。要先區分是哪一種：
> **① 先排除抓包問題** —— 檢查 B 的 `dropped by kernel` 是不是 0，
> 兩邊的過濾條件是否一致（一邊有加 `not port 22` 就會差很多）。
> **② 確認是真的遺失後，往中間設備查**：
> 防火牆的 drop 規則與計數器、
> 交換器介面的 error/discard 計數（`show interface`）、
> 頻寬是否飽和、中間的 IDS/IPS 是否在阻擋、
> **限流規則**（`nft` 的 `limit`、fail2ban）。
> **③ 也可能是非對稱路由** ——
> 去程和回程走不同路徑，其中一條路徑上的設備在丟包，
> 用 `ip route get` 和 `traceroute` 雙向比對。
> **兩端同時抓包比對，是證明「封包到底走到哪裡消失」最有力的方法**。

---

## 延伸閱讀

- [[060-01-04-01-guide-tcpdump-基礎抓包]] — 基礎過濾與輸出判讀
- [[060-01-04-03-guide-ss-netstat-與lsof]] — 連線狀態與 TCP 統計
- [[060-01-04-05-guide-curl-與HTTP除錯]] — 應用層排查
- [[090-01-13-guide-PKI-憑證常見問題排查]] — TLS 錯誤的完整對照
- [[060-01-03-04-guide-監控-效能瓶頸排查方法論]] — 零視窗要往應用層查
- [[020-01-26-guide-Linux-核心模組與sysctl調校]] — TCP 參數調校
