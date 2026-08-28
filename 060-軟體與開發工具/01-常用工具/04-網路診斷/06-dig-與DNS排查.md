---
title: "dig 與 DNS 排查"
desc: "解析流程、記錄類型、快取與 TTL、常見 DNS 故障的定位"
aliases: [dig, nslookup, host, DNS, resolv.conf, systemd-resolved, TTL]
tags: [群組/軟體與開發工具, 主題/網路診斷, 主題/dns]
category: 常用工具
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[16-網路基礎指令]]"]
updated: 2026-08-28
---

# dig 與 DNS 排查

> [!abstract] 這篇你會學到
> - **★★★ DNS 解析的完整流程**（遞迴 vs 疊代）
> - `dig` 的輸出逐段判讀
> - **★★★★ `+trace`** —— 從根開始追整條解析鏈
> - 常用記錄類型與**★★★ CNAME 的三個陷阱**
> - **★★★★ TTL 與快取** —— 為什麼「改了 DNS 還是舊的」
> - **★★★ Linux 上的解析路徑**（`/etc/hosts` → nsswitch → systemd-resolved）
> - 換 IP、發憑證、郵件相關記錄的實務
> - **★★ DNS 的資安**（DNSSEC、開放遞迴、DoT/DoH）

## 前置知識

- [[16-網路基礎指令]] — 網路基礎
- [[05-curl-與HTTP除錯]] — `time_namelookup` 慢時往這裡查

---

## ★★★ DNS 解析流程

```
★★★★ 使用者查 www.example.gov.tw 時發生什麼：

  【1】★★★ 應用程式（curl / 瀏覽器）
        │ 呼叫 getaddrinfo()
        ▼
  【2】★★★★ /etc/nsswitch.conf 決定查詢順序
        hosts: files mdns4_minimal [NOTFOUND=return] dns
                 ↑                                    ↑
          ★★★ 先查 /etc/hosts                   最後才查 DNS
        │
        ▼
  【3】★★★ /etc/resolv.conf 指定的 DNS 伺服器
        （★★ Ubuntu 上通常是 127.0.0.53 = systemd-resolved）
        │
        ▼
  【4】★★ 遞迴解析器（ISP 的 DNS / 8.8.8.8 / 內部 DNS）
        │ ★★★ 有快取就直接回答（★ 這就是 TTL 的作用）
        │ 沒有的話 → 疊代查詢：
        ▼
  ┌──────────────────────────────────────────────┐
  │ ★★★ 根伺服器 (.)                              │
  │   → 「我不知道，但 tw. 的 NS 是這些」          │
  │        │                                      │
  │        ▼                                      │
  │ ★★ tw. 的權威伺服器                            │
  │   → 「gov.tw. 的 NS 是這些」                   │
  │        │                                      │
  │        ▼                                      │
  │ ★★ gov.tw. 的權威伺服器                        │
  │   → 「example.gov.tw. 的 NS 是這些」           │
  │        │                                      │
  │        ▼                                      │
  │ ★★★★ example.gov.tw. 的權威伺服器              │
  │   → 「www.example.gov.tw = 203.0.113.10」      │
  └──────────────────────────────────────────────┘
        │
        ▼
  【5】遞迴解析器【快取】結果（依 TTL）並回覆
        │
        ▼
  【6】★★ 應用程式拿到 IP
        （★★★ 有些程式自己也會快取！見下）

★★★ 兩個名詞：
  遞迴查詢（recursive）★★ 「你幫我查到底」→ 客戶端對遞迴解析器
  疊代查詢（iterative）★★ 「你知道多少就說多少」→ 解析器對權威伺服器
```

---

## 安裝

```bash
$ sudo apt install -y dnsutils          # ★★ dig / nslookup / host
$ dig -v
DiG 9.18.28-0ubuntu0.24.04.1-Ubuntu
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> $ sudo dnf install -y bind-utils       # ★★ 套件名不同
> ```

```bash
# ★★ 三個工具的比較
$ dig example.gov.tw          # ★★★ 最完整，排查首選
$ host example.gov.tw         # ★★ 簡潔
$ nslookup example.gov.tw     # ★ 舊工具，輸出格式不友善
$ resolvectl query example.gov.tw   # ★★ systemd 系統
$ getent hosts example.gov.tw       # ★★★ 走完整的 nsswitch 流程
```

---

## ★★★ dig 輸出判讀

```bash
$ dig www.example.gov.tw

; <<>> DiG 9.18.28 <<>> www.example.gov.tw
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 24810
;; flags: qr rd ra; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 1

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 1232
;; QUESTION SECTION:
;www.example.gov.tw.		IN	A

;; ANSWER SECTION:
www.example.gov.tw.	300	IN	CNAME	app.example.gov.tw.
app.example.gov.tw.	300	IN	A	203.0.113.10

;; Query time: 24 msec
;; SERVER: 127.0.0.53#53(127.0.0.53) (UDP)
;; WHEN: Thu Aug 28 16:45:11 CST 2026
;; MSG SIZE  rcvd: 92
```

```
★★★★ 逐段判讀：

【HEADER】
  ★★★★ status: NOERROR      查詢成功
        status: NXDOMAIN     ★★★ 網域不存在
        status: SERVFAIL     ★★★★ 伺服器錯誤（見下方常見原因）
        status: REFUSED      ★★★ 伺服器拒絕（★ 非授權的查詢）
        status: NOTIMP       不支援該查詢類型

  ★★★ flags:
    qr  = query response（★ 這是回應）
    ★★★ aa = authoritative answer（★ 來自權威伺服器）
         → ★★ 沒有 aa = 來自快取
    rd  = recursion desired（★ 客戶端要求遞迴）
    ★★★ ra = recursion available（★ 伺服器提供遞迴）
    ★★★★ tc = truncated（★ 回應太大，會轉 TCP）
    ★★ ad = authenticated data（★ DNSSEC 驗證通過）
    cd  = checking disabled

【ANSWER SECTION】★★★★ 最重要
  www.example.gov.tw.  300  IN  CNAME  app.example.gov.tw.
                       ↑    ↑    ↑
                  ★★★ TTL 類別  記錄類型
  → ★★★ TTL 300 = 這筆記錄可以被快取 300 秒

【AUTHORITY SECTION】
  ★★ 負責這個網域的 NS 伺服器

【ADDITIONAL SECTION】
  ★ 附帶的資訊（★ 通常是 NS 的 A 記錄，稱為 glue record）

【底部】
  ★★★ Query time: 24 msec   → 慢的話（> 100ms）要注意
  ★★★★ SERVER: 127.0.0.53   → 【實際回答你的是誰】
                              → ★★ Ubuntu 上是 systemd-resolved
```

```bash
# ═══ ★★★ 精簡輸出 ═══
$ dig +short www.example.gov.tw
app.example.gov.tw.
203.0.113.10

$ dig +short www.example.gov.tw A | tail -1     # ★★ 只要最終的 IP
203.0.113.10

$ dig +noall +answer www.example.gov.tw         # ★★★ 只要 ANSWER 區段
www.example.gov.tw.	300	IN	CNAME	app.example.gov.tw.
app.example.gov.tw.	300	IN	A	203.0.113.10

# ★★ 其他常用選項
$ dig +nocmd +noall +answer +stats example.gov.tw
$ dig +multiline example.gov.tw SOA        # ★★ 多行顯示（★ SOA 好讀）
$ dig +tcp example.gov.tw                  # ★★ 強制用 TCP
$ dig +dnssec example.gov.tw               # ★★ 要求 DNSSEC
$ dig +nssearch example.gov.tw             # ★★★ 問所有 NS（★ 檢查一致性）
```

---

## ★★★ 記錄類型

| 類型 | 用途 | 說明 |
| --- | --- | --- |
| **`A`** | IPv4 位址 | **★★★ 最常用** |
| **`AAAA`** | IPv6 位址 | ★★ |
| **`CNAME`** | 別名 | **★★★ 有三個陷阱**（見下） |
| **`MX`** | 郵件伺服器 | ★★ 有優先權數值 |
| **`TXT`** | 文字 | **★★★ SPF / DKIM / DMARC / 網域驗證** |
| **`NS`** | 名稱伺服器 | **★★★ 誰是權威** |
| **`SOA`** | 起始授權 | **★★ 序號、TTL 預設值** |
| **`PTR`** | 反解 | **★★★ IP → 網域**（★ 郵件伺服器必備） |
| **`SRV`** | 服務位置 | ★★ AD、SIP、XMPP |
| **`CAA`** | 憑證頒發授權 | **★★★ 限制誰能簽發憑證** |
| `DS` / `DNSKEY` | DNSSEC | ★★ |

```bash
# ═══ ★★★ 查特定類型 ═══
$ dig +short example.gov.tw A
$ dig +short example.gov.tw AAAA
$ dig +short example.gov.tw MX
10 mail1.example.gov.tw.
20 mail2.example.gov.tw.
#  ↑ ★★ 數字越小優先權越高

$ dig +short example.gov.tw NS
ns1.example.gov.tw.
ns2.example.gov.tw.

$ dig +short example.gov.tw TXT
"v=spf1 ip4:203.0.113.0/24 include:_spf.example.tw ~all"
"google-site-verification=abc123..."

$ dig +multiline example.gov.tw SOA
example.gov.tw.		3600 IN	SOA ns1.example.gov.tw. admin.example.gov.tw. (
				2026082801 ; ★★★ serial（★ 改設定要遞增）
				7200       ; refresh
				3600       ; retry
				1209600    ; expire
				3600       ; ★★ minimum（negative caching TTL）
				)

# ★★★ 反解（PTR）
$ dig +short -x 203.0.113.10
app.example.gov.tw.
#   ★★★★ 郵件伺服器【一定要有】正確的 PTR，否則會被判定為垃圾郵件

# ★★★ CAA（限制誰能簽發憑證）
$ dig +short example.gov.tw CAA
0 issue "letsencrypt.org"
0 issuewild ";"
0 iodef "mailto:security@example.gov.tw"
#   ★★★ 只有 Let's Encrypt 能簽發，禁止萬用憑證

# ★★ 查所有類型（★ 多數伺服器已不支援）
$ dig example.gov.tw ANY
#   ★★★ RFC 8482 之後多數伺服器回 HINFO 而不是全部記錄
```

> [!danger] CNAME 的三個陷阱 ★★★
> ```
> ★★★★ ① 【根網域不能用 CNAME】
>   example.gov.tw.  IN  CNAME  app.example.gov.tw.   ← ★★★★ 違反 RFC！
>   → 因為根網域一定要有 SOA 和 NS 記錄，
>     而 CNAME 規定【不能與其他記錄共存】
>   → ★★★ 症狀：MX 查不到、郵件收不到、DNS 伺服器拒絕載入 zone
>   → ★★ 解法：用 A 記錄；或用 DNS 商的 ALIAS / ANAME / CNAME flattening
>
> ★★★ ② 【CNAME 不能與其他記錄共存】
>   www  IN  CNAME  app.example.gov.tw.
>   www  IN  TXT    "..."                 ← ★★★ 不合法
>   → ★★ 常見的踩雷：想在有 CNAME 的名稱上加 TXT 做網域驗證
>
> ★★★ ③ 【CNAME 鏈會增加延遲】
>   www → cdn.provider.com → edge.provider.com → 203.0.113.10
>   → ★★ 每一跳都可能是一次額外的查詢
>   → ★★★ 鏈太長（> 3）會被某些解析器拒絕
>   → ★ 用 dig +trace 或 +short 看完整的鏈
> ```

---

## ★★★★ `+trace` 追整條解析鏈

```bash
$ dig +trace www.example.gov.tw

; <<>> DiG 9.18.28 <<>> +trace www.example.gov.tw
.			518400	IN	NS	a.root-servers.net.
.			518400	IN	NS	b.root-servers.net.
...
;; Received 811 bytes from 127.0.0.53#53(127.0.0.53) in 4 ms

tw.			172800	IN	NS	a.dns.tw.
tw.			172800	IN	NS	b.dns.tw.
;; Received 682 bytes from 198.41.0.4#53(a.root-servers.net) in 142 ms
#                              ↑ ★★★ 從根伺服器問到 tw. 的 NS

gov.tw.			86400	IN	NS	ns1.gov.tw.
;; Received 320 bytes from 203.73.24.24#53(a.dns.tw) in 12 ms

example.gov.tw.		86400	IN	NS	ns1.example.gov.tw.
example.gov.tw.		86400	IN	NS	ns2.example.gov.tw.
;; Received 128 bytes from 168.95.1.1#53(ns1.gov.tw) in 8 ms

www.example.gov.tw.	300	IN	CNAME	app.example.gov.tw.
app.example.gov.tw.	300	IN	A	203.0.113.10
;; Received 92 bytes from 203.0.113.53#53(ns1.example.gov.tw) in 4 ms
#                                          ↑ ★★★★ 最終由權威伺服器回答
```

```
★★★★ +trace 的價值：

  ① ★★★ 【繞過所有快取】
     → 每一步都直接問權威伺服器
     → ★★★★ 這是確認「DNS 真的改好了嗎」的可靠方法

  ② ★★★ 【看出是哪一層有問題】
     · 卡在根 → 網路問題
     · 卡在 tw. → 註冊商的問題
     · ★★★ 卡在 example.gov.tw. → 你自己的 NS 有問題

  ③ ★★ 【看出 NS 委派是否正確】
     → 上層說的 NS 和你實際設的 NS 一致嗎？

★★★ 注意：+trace 用的是【本機的解析路徑】找根伺服器
  → 如果本機的 DNS 完全壞掉，+trace 也會失敗
```

```bash
# ═══ ★★★ 檢查 NS 委派的一致性 ═══
#   ① 上層（gov.tw）說的 NS
$ dig +short example.gov.tw NS @ns1.gov.tw
ns1.example.gov.tw.
ns2.example.gov.tw.

#   ② ★★★ 你自己的 NS 說的
$ dig +short example.gov.tw NS @ns1.example.gov.tw
ns1.example.gov.tw.
ns2.example.gov.tw.
ns3.example.gov.tw.                       # ★★★★ 不一致！

#   → ★★★ 這叫「lame delegation」，會造成間歇性的解析失敗

# ═══ ★★★ 檢查所有 NS 的資料一致性 ═══
$ for ns in $(dig +short example.gov.tw NS); do
    printf "%-30s " "$ns"
    dig +short www.example.gov.tw A "@$ns" | tail -1
  done
ns1.example.gov.tw.            203.0.113.10
ns2.example.gov.tw.            203.0.113.10
ns3.example.gov.tw.            203.0.113.99      # ★★★★ 不同步！

# ★★★ 檢查 SOA 序號是否一致（★ 判斷 zone transfer 是否成功）
$ for ns in $(dig +short example.gov.tw NS); do
    printf "%-30s serial=" "$ns"
    dig +short example.gov.tw SOA "@$ns" | awk '{print $3}'
  done
ns1.example.gov.tw.            serial=2026082801
ns2.example.gov.tw.            serial=2026082801
ns3.example.gov.tw.            serial=2026082501   # ★★★★ 落後三天！

# ★★ nssearch（一次做完）
$ dig +nssearch example.gov.tw
```

---

## ★★★★ TTL 與快取

```
★★★★ 「我改了 DNS 但還是連到舊的 IP」—— 這是最常見的問題

★★★ 快取存在於【五個地方】：

  ① ★★★ 權威伺服器          → 改了就生效（★ 這一層沒有快取）
  ② ★★★★ 遞迴解析器（ISP）  → 依 TTL 快取（★ 最主要的一層）
  ③ ★★★ 本機的 stub resolver → systemd-resolved / dnsmasq / nscd
  ④ ★★★ 應用程式本身        → ★★★★ 見下方（最容易被忽略）
  ⑤ ★★ 瀏覽器               → Chrome 有自己的 DNS 快取

★★★★ 所以換 IP 的正確流程：
  ① 【提前】把 TTL 調低（例如 300 秒）
  ② ★★★ 等【舊的 TTL 完全過期】（★ 例如原本 86400 就要等一天）
  ③ 改 A 記錄
  ④ ★★★ 等新的 TTL（300 秒）
  ⑤ 驗證
  ⑥ ★★ 觀察無誤後把 TTL 調回正常值
```

```bash
# ═══ ★★★ 看目前的 TTL ═══
$ dig +noall +answer www.example.gov.tw
www.example.gov.tw.	86400	IN	A	203.0.113.10
#                        ↑ ★★★★ 一天！換 IP 前要先調低

# ★★★ 連續查看 TTL 遞減（★ 證明是快取的答案）
$ for i in 1 2 3; do dig +noall +answer example.gov.tw | awk '{print $2}'; sleep 5; done
287
282
277                                # ★★★ 遞減 = 來自快取

# ★★★★ 問權威伺服器（★ 繞過所有快取）
$ dig +noall +answer example.gov.tw @ns1.example.gov.tw
example.gov.tw.		300	IN	A	203.0.113.20      # ★★★ 新的！
#   → ★★★★ 權威已經改了，只是快取還沒過期

# ★★★ 從多個公開 DNS 檢查傳播狀況
$ for dns in 8.8.8.8 1.1.1.1 9.9.9.9 168.95.1.1 208.67.222.222; do
    printf "%-16s " "$dns"
    dig +short +time=3 +tries=1 www.example.gov.tw A "@$dns" | tail -1 || echo "逾時"
  done
8.8.8.8          203.0.113.20      # ★★ 已更新
1.1.1.1          203.0.113.20
9.9.9.9          203.0.113.10      # ★★★ 還是舊的
168.95.1.1       203.0.113.20
208.67.222.222   203.0.113.10      # ★★★ 還是舊的
```

```bash
# ═══ ★★★ 清除各層快取 ═══

# ★★★ systemd-resolved（Ubuntu 預設）
$ sudo resolvectl flush-caches
$ resolvectl statistics | grep -A3 Cache
Cache
  Current Cache Size: 0                # ★★ 清空了

# ★★ nscd
$ sudo nscd -i hosts

# ★★ dnsmasq
$ sudo systemctl restart dnsmasq

# ★ macOS
$ sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder

# ★ Windows
$ ipconfig /flushdns

# ★★ Chrome（★ 有自己的快取）
#   → chrome://net-internals/#dns → Clear host cache
```

> [!danger] 應用程式的 DNS 快取 ★★★★
> ```
> ★★★★ 這是最容易被忽略的一層：
>
> 【Java / JVM】★★★★ 最惡名昭彰
>   → 預設 networkaddress.cache.ttl = -1（★ 永久快取！）
>   → ★★★ 換 IP 後【必須重啟 JVM】
>   → 解法：$JAVA_HOME/conf/security/java.security
>     networkaddress.cache.ttl=30
>     networkaddress.cache.negative.ttl=10
>
> 【PHP-FPM】★★
>   → 一般不快取，但 curl 的連線重用可能持有舊連線
>   → ★ 重啟 php-fpm 保險
>
> 【Node.js】★★
>   → 預設不快取，但 keep-alive 的連線會持續使用舊 IP
>   → ★★ 用 agent 的 maxSockets / 定期重建連線
>
> 【★★★★ nginx upstream】← 這個最常踩
>   upstream backend { server api.internal.tw:8080; }
>   → ★★★★ nginx【只在啟動時解析一次】，之後永遠用那個 IP！
>   → ★★★ 解法：
>     ① 商業版的 resolver + server ... resolve;
>     ② ★★ 開源版用變數強制動態解析：
>        resolver 10.10.20.53 valid=30s ipv6=off;
>        set $backend "api.internal.tw";
>        proxy_pass http://$backend:8080;
>        ★★★ 注意：用變數後 proxy_pass 的 URI 處理規則會改變
>     ③ ★★ 或改用 IP + 定期 reload
>
> 【Docker / Kubernetes】★★
>   → 容器內的 /etc/resolv.conf 指向內建 DNS
>   → ★★ ndots:5 會讓查詢變多（★ K8s 常見的效能問題）
> ```

---

## ★★★ Linux 的解析路徑

```bash
# ═══ ★★★★【1】/etc/nsswitch.conf —— 查詢順序 ═══
$ grep '^hosts:' /etc/nsswitch.conf
hosts: files mdns4_minimal [NOTFOUND=return] dns
#      ↑                                      ↑
#  ★★★ 先查 /etc/hosts                   最後才 DNS
#   ★★★★ 所以 /etc/hosts 會【蓋過】DNS！

# ═══ ★★★【2】/etc/hosts ═══
$ cat /etc/hosts
127.0.0.1	localhost
10.10.20.31	app.example.gov.tw        # ★★★★ 這一行會蓋過 DNS！
#   ★★★ 排查時第一個要檢查的地方

# ═══ ★★★★【3】/etc/resolv.conf ═══
$ cat /etc/resolv.conf
nameserver 127.0.0.53                   # ★★★ Ubuntu = systemd-resolved
options edns0 trust-ad
search example.gov.tw

$ ls -l /etc/resolv.conf
lrwxrwxrwx 1 root root 39 ... /etc/resolv.conf -> ../run/systemd/resolve/stub-resolv.conf
#   ★★★★ 是符號連結 → 直接編輯【會被覆蓋】！

# ★★★ 看真正的上游 DNS
$ resolvectl status
Global
       Protocols: -LLMNR -mDNS -DNSOverTLS DNSSEC=no/unsupported
resolv.conf mode: stub

Link 2 (ens18)
    Current Scopes: DNS
         Protocols: +DefaultRoute -LLMNR -mDNS -DNSOverTLS DNSSEC=no/unsupported
Current DNS Server: 10.10.20.53
       DNS Servers: 10.10.20.53 10.10.20.54      # ★★★ 真正的上游
        DNS Domain: example.gov.tw

$ resolvectl dns                     # ★★ 只看 DNS 伺服器
$ resolvectl domain                  # ★★ 搜尋網域
$ resolvectl statistics              # ★★ 快取統計
```

```bash
# ═══ ★★★ 正確設定 DNS（Ubuntu / netplan）═══
$ sudo tee /etc/netplan/50-dns.yaml >/dev/null <<'EOF'
network:
  version: 2
  ethernets:
    ens18:
      nameservers:
        addresses: [10.10.20.53, 10.10.20.54]
        search: [example.gov.tw, internal.example.gov.tw]
EOF
$ sudo chmod 600 /etc/netplan/50-dns.yaml
$ sudo netplan apply
$ resolvectl status | grep -A2 'DNS Servers'

# ★★ 或用 resolvectl 臨時設定
$ sudo resolvectl dns ens18 10.10.20.53 10.10.20.54
$ sudo resolvectl domain ens18 example.gov.tw
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> # ★★ RHEL 用 NetworkManager，且 /etc/resolv.conf 不是符號連結
> $ sudo nmcli con mod ens18 ipv4.dns "10.10.20.53 10.10.20.54"
> $ sudo nmcli con mod ens18 ipv4.dns-search "example.gov.tw"
> $ sudo nmcli con up ens18
> $ cat /etc/resolv.conf
>
> # ★★ 阻止 NetworkManager 覆寫（★ 手動管理時）
> $ sudo nmcli con mod ens18 ipv4.ignore-auto-dns yes
> # ★ 或 /etc/NetworkManager/conf.d/90-dns-none.conf:
> #   [main]
> #   dns=none
> ```

```
★★★★ /etc/resolv.conf 的 options（★ 影響很大）：

  ★★★ options timeout:2      每個 nameserver 的逾時（★ 預設 5 秒！）
  ★★★ options attempts:2     重試次數（★ 預設 2）
  ★★★★ options ndots:5       名稱中的點數 < 5 時，先套用 search 網域
                              → ★★★ K8s 預設 ndots:5 → 查外部網域要多查 4 次！
  ★★ options rotate          輪替使用 nameserver
  ★★ options single-request-reopen  修正某些 A/AAAA 並行查詢的問題

★★★★ 最常見的效能陷阱：
  第一個 nameserver 掛了 → ★★★ 每次查詢都要等 5 秒逾時才換第二個
  → ★★★ 一定要設 options timeout:2 attempts:2
```

```bash
# ★★★ 逐層測試解析路徑
$ getent hosts app.example.gov.tw       # ★★★★ 走完整的 nsswitch（含 /etc/hosts）
10.10.20.31     app.example.gov.tw

$ dig +short app.example.gov.tw         # ★★★ 只走 DNS（不看 /etc/hosts）
203.0.113.10
#   ★★★★ 兩者不同 → 一定是 /etc/hosts 有東西！

$ grep app.example /etc/hosts
10.10.20.31	app.example.gov.tw          # ★★★ 找到了
```

---

## 完整實戰範例

### 情境一：★★★★ 換 IP 的完整流程

```bash
# ═══ ★★★【T-2 天】提前降低 TTL ═══
$ dig +noall +answer app.example.gov.tw
app.example.gov.tw.	86400	IN	A	203.0.113.10
#                        ↑ ★★★★ 一天，太長

#   ★★ 在 DNS 管理介面把 TTL 改成 300
#   ★★★★ 然後【等 86400 秒（一天）】讓舊的快取全部過期
$ dig +noall +answer app.example.gov.tw @ns1.example.gov.tw
app.example.gov.tw.	300	IN	A	203.0.113.10       # ★★ 權威已是 300

# ═══ ★★【T-1 天】確認傳播 ═══
$ for dns in 8.8.8.8 1.1.1.1 9.9.9.9 168.95.1.1; do
    printf "%-14s " "$dns"
    dig +noall +answer app.example.gov.tw "@$dns" | awk '{print "TTL="$2, $5}'
  done
8.8.8.8        TTL=287 203.0.113.10       # ★★★ TTL 已降到 300 以內
1.1.1.1        TTL=142 203.0.113.10
9.9.9.9        TTL=298 203.0.113.10
168.95.1.1     TTL=201 203.0.113.10
#   ★★★★ 全部 < 300 → 可以切換了

# ═══ ★★★【T 日】準備新伺服器 ═══
#   ★★★★ 切換前先用 --resolve 驗證新伺服器完全正常
$ curl -sI --resolve app.example.gov.tw:443:203.0.113.20 \
    https://app.example.gov.tw | head -3
HTTP/2 200
server: nginx

$ curl -s --resolve app.example.gov.tw:443:203.0.113.20 \
    https://app.example.gov.tw/api/health | jq .
{"status":"ok","db":"ok","cache":"ok"}    # ★★★ 新伺服器正常

# ═══ ★★★★【切換】改 A 記錄 ═══
#   （在 DNS 管理介面把 A 改成 203.0.113.20）

$ dig +short app.example.gov.tw @ns1.example.gov.tw
203.0.113.20                              # ★★★ 權威已更新

# ═══ ★★★【驗證】監控傳播 ═══
$ watch -n 10 'for d in 8.8.8.8 1.1.1.1 9.9.9.9 168.95.1.1; do
    printf "%-14s " "$d"; dig +short app.example.gov.tw "@$d" | tail -1
  done'
8.8.8.8        203.0.113.20
1.1.1.1        203.0.113.20
9.9.9.9        203.0.113.20
168.95.1.1     203.0.113.20               # ★★★★ 五分鐘內全部更新

# ★★★ 兩台都要監控（★ 舊的還會有流量）
$ ssh old-server 'tail -f /var/log/nginx/access.log | wc -l'
$ ssh new-server 'tail -f /var/log/nginx/access.log'

# ═══ ★★【T+1 天】舊機器可以下線 ═══
$ ssh old-server 'grep -c . /var/log/nginx/access.log'
0                                         # ★★★ 沒有流量了

# ═══ ★★【T+2 天】TTL 調回 3600 ═══
```

### 情境二：★★★ 憑證申請失敗

```bash
# ═══ 情境：Let's Encrypt 說 DNS 驗證失敗 ═══
$ sudo certbot certonly --dns-cloudflare -d api.example.gov.tw
Challenge failed for domain api.example.gov.tw
DNS problem: NXDOMAIN looking up TXT for _acme-challenge.api.example.gov.tw

# ═══ ★★★【1】檢查 TXT 記錄 ═══
$ dig +short _acme-challenge.api.example.gov.tw TXT
#   ★★★★ 空的 → 記錄沒建立，或還沒傳播

# ═══ ★★★★【2】直接問權威伺服器 ═══
$ dig +short _acme-challenge.api.example.gov.tw TXT @ns1.example.gov.tw
"abc123def456..."
#   ★★★ 權威有，但快取還沒過期 → 等一下再試

# ═══ ★★★【3】用 +trace 確認完整鏈路 ═══
$ dig +trace _acme-challenge.api.example.gov.tw TXT | tail -8

# ═══ ★★★【4】檢查 CAA 記錄 ═══
$ dig +short example.gov.tw CAA
0 issue "digicert.com"
#   ★★★★ 只允許 DigiCert！Let's Encrypt 被 CAA 擋住了
#   → ★★★ 解法：加上 0 issue "letsencrypt.org"

$ dig +short api.example.gov.tw CAA        # ★★ CAA 會往上找
$ dig +short gov.tw CAA

# ═══ ★★★【5】HTTP-01 驗證的檢查 ═══
$ curl -sI http://api.example.gov.tw/.well-known/acme-challenge/test
HTTP/1.1 301 Moved Permanently
location: https://api.example.gov.tw/...
#   ★★★★ 被重導向到 HTTPS，但 Let's Encrypt 的 HTTP-01 需要 http 可達
#   → ★★★ nginx 要為 .well-known 開例外：
#     location ^~ /.well-known/acme-challenge/ {
#         root /var/www/certbot;
#         try_files $uri =404;
#     }
```

### 情境三：★★★ DNS 解析很慢

```bash
# ═══ ★★★【1】curl 的時間拆解顯示 DNS 慢 ═══
$ curl -sko /dev/null -w 'dns=%{time_namelookup}s total=%{time_total}s\n' \
    https://api.partner.example.com
dns=5.012s total=5.234s                   # ★★★★ DNS 花了 5 秒！

# ═══ ★★★【2】直接測 dig ═══
$ dig api.partner.example.com | grep 'Query time'
;; Query time: 5001 msec                  # ★★★★ 確認

# ═══ ★★★★【3】測試每一個 nameserver ═══
$ resolvectl dns
Link 2 (ens18): 10.10.20.53 10.10.20.54

$ for ns in 10.10.20.53 10.10.20.54; do
    printf "%-14s " "$ns"
    dig +time=3 +tries=1 api.partner.example.com "@$ns" 2>&1 | \
      grep -E 'Query time|connection timed out' || echo "無回應"
  done
10.10.20.53    ;; connection timed out; no servers could be reached   # ★★★★ 掛了！
10.10.20.54    ;; Query time: 12 msec                                  # ★★ 正常

#   ★★★★ 第一個 nameserver 掛了 →
#     每次查詢都要等【5 秒逾時】才換第二個

# ═══ ★★★【4】兩個處置 ═══
#   ★★★ 短期：調整逾時
$ sudo tee /etc/systemd/resolved.conf.d/timeout.conf >/dev/null <<'EOF'
[Resolve]
DNS=10.10.20.54 10.10.20.53
FallbackDNS=1.1.1.1 8.8.8.8
Cache=yes
DNSStubListener=yes
EOF
$ sudo systemctl restart systemd-resolved

#   ★★ 傳統 resolv.conf 的話
$ grep options /etc/resolv.conf
options timeout:2 attempts:2 rotate       # ★★★ 逾時 2 秒而不是 5 秒

#   ★★★★ 長期：修好 10.10.20.53
$ ssh 10.10.20.53 'systemctl status named bind9 unbound 2>/dev/null'

# ═══ ★★【5】驗證 ═══
$ curl -sko /dev/null -w 'dns=%{time_namelookup}s\n' https://api.partner.example.com
dns=0.014s                                # ★★★★ 5s → 14ms
```

---

## 常見錯誤與排錯

| 現象 | 原因 | **★ 解法** |
| --- | --- | --- |
| **`NXDOMAIN`** ★★★ | 網域不存在 | 檢查拼字；**問權威伺服器** |
| **`SERVFAIL`** ★★★★ | 伺服器錯誤／**DNSSEC 驗證失敗** | `+cd` 跳過驗證測試；查權威 |
| **`REFUSED`** ★★★ | 非授權查詢／ACL | 確認查對伺服器 |
| **改了 DNS 還是舊 IP** ★★★★ | **快取** | `dig @權威`；**`+trace`**；清快取 |
| **`dig` 對但程式錯** ★★★★ | **`/etc/hosts`** | **`getent hosts`** 比對 |
| **DNS 解析要 5 秒** ★★★★ | **第一個 NS 掛了** | 逐一測 NS；`options timeout:2` |
| **改 `/etc/resolv.conf` 沒效** ★★★★ | **是符號連結，被覆寫** | netplan / `resolvectl` / NM |
| **nginx 上游一直連舊 IP** ★★★★ | **只在啟動時解析** | `resolver` + 變數；或定期 reload |
| **Java 一直用舊 IP** ★★★★ | **JVM 永久快取** | `networkaddress.cache.ttl=30`；重啟 |
| **K8s 內查外部網域很慢** ★★★ | **`ndots:5`** | Pod 加 `dnsConfig` 調 ndots |
| **根網域的 MX 查不到** ★★★ | **根網域用了 CNAME** | 改用 A / ALIAS |
| **憑證申請失敗** ★★★ | TXT 沒傳播／**CAA 擋住** | `dig TXT @權威`；檢查 CAA |
| **回應被截斷（`tc` flag）** ★★ | UDP 512 bytes 限制 | `+tcp`；確認 EDNS 可用 |

### 排查

```bash
# 【1】★★★★ 逐層測試
$ getent hosts HOST                 # ★★★ 完整流程（含 /etc/hosts）
$ dig +short HOST                   # ★★ 只走 DNS
$ dig +short HOST @10.10.20.53      # ★★ 指定伺服器
$ dig +short HOST @ns1.example.tw   # ★★★ 權威（繞過快取）
$ dig +trace HOST                   # ★★★★ 完整鏈路

# 【2】★★★ 本機設定
$ grep '^hosts:' /etc/nsswitch.conf
$ grep -v '^#' /etc/hosts | grep -v '^$'
$ cat /etc/resolv.conf
$ resolvectl status
$ resolvectl statistics

# 【3】★★★ 測試每一個 nameserver
$ for ns in $(resolvectl dns | grep -oP '(\d+\.){3}\d+'); do
    printf "%-16s " "$ns"
    dig +time=2 +tries=1 example.com "@$ns" 2>&1 | grep -oP 'Query time: \K.*' || echo "★★★ 無回應"
  done

# 【4】★★★ 一致性檢查
$ for ns in $(dig +short example.gov.tw NS); do
    printf "%-30s " "$ns"; dig +short www.example.gov.tw "@$ns" | tail -1
  done
$ dig +nssearch example.gov.tw          # ★★ SOA 序號比對

# 【5】★★ 傳播狀況
$ for d in 8.8.8.8 1.1.1.1 9.9.9.9 168.95.1.1; do
    printf "%-14s " "$d"; dig +short HOST "@$d" | tail -1
  done

# 【6】★★ DNSSEC
$ dig +dnssec example.gov.tw | grep -E 'flags:|RRSIG'
$ dig +cd example.gov.tw                 # ★★★ 跳過驗證（★ 判斷是不是 DNSSEC 問題）
$ delv example.gov.tw                    # ★★ 完整的 DNSSEC 驗證

# 【7】★ 清快取
$ sudo resolvectl flush-caches
$ resolvectl statistics | grep -A3 Cache
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★
> ```
> ① ★★★★ 開放遞迴的 DNS 伺服器 = DDoS 放大器
>      → 攻擊者偽造來源 IP 查詢，回應放大 50~100 倍
>      → ★★★ 內部 DNS 一定要限制 allow-recursion
>
> ② ★★★ 不要對外提供 zone transfer（AXFR）
>      → ★★★★ 會洩漏【整個網域的所有記錄】= 完整的內部拓撲
>      → ★★ 測試：dig AXFR example.gov.tw @ns1.example.gov.tw
>
> ③ ★★★ DNS 查詢預設是明文
>      → 中間人看得到你在查什麼、可以竄改
>      → ★★ 考慮 DoT（853）或 DoH（443）
>
> ④ ★★★ CAA 記錄限制誰能簽發憑證
>      → ★★★★ 沒設 CAA = 任何 CA 都能為你的網域簽憑證
>
> ⑤ ★★ DNSSEC 防止快取污染
>      → ★★★ 但設錯會造成 SERVFAIL（全網無法解析）
>      → ★ 要有監控
> ```

```bash
# ═══ ★★★★ 檢查 zone transfer 是否開放（★ 對自己的網域）═══
$ for ns in $(dig +short example.gov.tw NS); do
    printf "%-30s " "$ns"
    if dig +short AXFR example.gov.tw "@$ns" 2>/dev/null | grep -q SOA; then
        echo "★★★★ AXFR 開放！立刻修正"
    else
        echo "✓ 已限制"
    fi
  done

# ★★★ BIND 的正確設定
$ sudo tee -a /etc/bind/named.conf.options >/dev/null <<'EOF'
acl internal { 10.10.0.0/16; 127.0.0.1; };

options {
    # ★★★★ 不要開放遞迴給外部
    recursion yes;
    allow-recursion { internal; };
    allow-query { any; };            # ★ 權威查詢可以開放

    # ★★★★ 限制 zone transfer
    allow-transfer { 10.10.20.54; };  # ★ 只允許次要 NS

    # ★★★ 隱藏版本
    version "not disclosed";

    # ★★ 速率限制（★ 防止被當放大器）
    rate-limit {
        responses-per-second 20;
        window 5;
    };

    # ★★ DNSSEC 驗證
    dnssec-validation auto;
};
EOF
$ sudo named-checkconf && sudo systemctl reload named

# ═══ ★★★ CAA 記錄 ═══
$ dig +short example.gov.tw CAA
#   ★★★★ 空的 = 任何 CA 都能簽發

#   ★★★ 建議設定（在 DNS 管理介面）：
#     example.gov.tw. CAA 0 issue "letsencrypt.org"
#     example.gov.tw. CAA 0 issuewild ";"                # ★★ 禁止萬用憑證
#     example.gov.tw. CAA 0 iodef "mailto:security@example.gov.tw"

# ═══ ★★ DNSSEC 檢查 ═══
$ dig +dnssec example.gov.tw | grep -E '^;; flags:.*ad|RRSIG'
;; flags: qr rd ra ad;                    # ★★★ ad = 驗證通過
$ delv example.gov.tw
; fully validated                          # ★★★ 完整驗證

# ★★★ SERVFAIL 時判斷是不是 DNSSEC 問題
$ dig example.gov.tw
;; ->>HEADER<<- opcode: QUERY, status: SERVFAIL
$ dig +cd example.gov.tw                   # ★★★★ +cd = 跳過 DNSSEC 驗證
;; ->>HEADER<<- opcode: QUERY, status: NOERROR    # ★★★ 有答案 → 是 DNSSEC 壞了

# ═══ ★★ DoT / DoH ═══
$ sudo tee /etc/systemd/resolved.conf.d/dot.conf >/dev/null <<'EOF'
[Resolve]
DNS=1.1.1.1#cloudflare-dns.com 9.9.9.9#dns.quad9.net
DNSOverTLS=yes
DNSSEC=allow-downgrade
EOF
$ sudo systemctl restart systemd-resolved
$ resolvectl status | grep -i 'DNSOverTLS'
         Protocols: +DNSOverTLS

# ★ 測試 DoH
$ curl -sH 'accept: application/dns-json' \
    'https://cloudflare-dns.com/dns-query?name=example.gov.tw&type=A' | jq .

# ═══ ★★ 檢查是否被 DNS 劫持 ═══
$ dig +short example.gov.tw @8.8.8.8
$ dig +short example.gov.tw @1.1.1.1
$ dig +short example.gov.tw @ns1.example.gov.tw
#   ★★★ 三者不一致 → 可能有劫持或污染

# ★★ SPF / DKIM / DMARC（★ 郵件相關，本手冊不涵蓋郵件伺服器但 DNS 要會查）
$ dig +short example.gov.tw TXT | grep spf1
$ dig +short _dmarc.example.gov.tw TXT
$ dig +short default._domainkey.example.gov.tw TXT
```

---

## 速查表

### ★★★★ 排查三連

```bash
getent hosts HOST              # ★★★★ 完整流程（會看 /etc/hosts）
dig +short HOST                # ★★★ 只走 DNS
dig +short HOST @ns1.xxx       # ★★★★ 問權威（繞過所有快取）
dig +trace HOST                # ★★★★ 完整鏈路，確認真的改好了
```

### dig 常用

```bash
dig +short HOST A|AAAA|MX|NS|TXT|SOA|CAA
dig +noall +answer HOST        # ★★★ 只要答案（含 TTL）
dig +short -x 203.0.113.10     # ★★★ 反解
dig +multiline HOST SOA        # ★★ 好讀
dig +nssearch HOST             # ★★★ 問所有 NS
dig +dnssec HOST               # DNSSEC
dig +cd HOST                   # ★★★ 跳過 DNSSEC 驗證（判斷是不是它壞了）
dig +tcp HOST                  # 強制 TCP
```

### ★★★ status 判讀

```
NOERROR   成功
NXDOMAIN  ★★★ 網域不存在
SERVFAIL  ★★★★ 伺服器錯誤（★ 常常是 DNSSEC）→ 用 +cd 測
REFUSED   ★★★ 拒絕（★ ACL / 非授權）
flags: aa = 權威回答（★ 沒有 aa 就是快取）
flags: ad = ★★ DNSSEC 驗證通過
flags: tc = ★★ 被截斷，會轉 TCP
```

### ★★★★ 換 IP 流程

```
① 提前把 TTL 調低（300）
② ★★★★ 等舊的 TTL 完全過期（原本 86400 就等一天）
③ 用 --resolve 驗證新伺服器正常
④ 改 A 記錄
⑤ ★★★ 從多個公開 DNS 監控傳播
⑥ 觀察兩台的 access log
⑦ TTL 調回
```

### ★★★★ 快取的五層

```
① 權威伺服器      → 沒有快取
② ★★★★ 遞迴解析器 → 依 TTL（主要）
③ 本機 stub       → resolvectl flush-caches
④ ★★★★ 應用程式   → JVM 永久快取！nginx upstream 只解析一次！
⑤ 瀏覽器          → chrome://net-internals/#dns
```

### ★★★ CNAME 陷阱

```
★★★★ 根網域不能用 CNAME（會壞掉 MX/NS）→ 用 A 或 ALIAS
★★★ CNAME 不能與其他記錄共存（★ 不能同時有 TXT）
★★ CNAME 鏈太長會增加延遲
```

### ★★★ Linux 解析路徑

```bash
/etc/nsswitch.conf   # ★★★★ hosts: files ... dns（files 優先！）
/etc/hosts           # ★★★★ 會蓋過 DNS
/etc/resolv.conf     # ★★★ Ubuntu 是符號連結，改了會被覆寫
resolvectl status    # ★★★ 看真正的上游 DNS
netplan / nmcli      # ★★★ 正確的設定位置
options timeout:2 attempts:2   # ★★★ 避免 NS 掛掉時等 5 秒
```

### ★★★ 安全

```bash
dig AXFR example.tw @ns1.example.tw     # ★★★★ 應該要失敗
dig +short example.tw CAA               # ★★★ 限制誰能簽憑證
allow-recursion { internal; };          # ★★★★ 不要開放遞迴
allow-transfer { 次要NS; };              # ★★★★ 不要開放 AXFR
DNSOverTLS=yes                          # ★★ 加密 DNS
```

---

## 練習題

> [!question]- 練習 1：解析流程 ★★★
> 1. **`dig +trace www.google.com`** → 經過幾層？
> 2. **每一層是誰回答的？**
> 3. `dig www.google.com` 和 `+trace` 的結果一樣嗎？為什麼？
> 4. **連續三次 `dig` 看 TTL** → 遞減嗎？說明什麼？
> 5. `resolvectl flush-caches` 後再查 → TTL 呢？
> 6. **`dig +noall +stats` 看 Query time 的變化**

> [!question]- 練習 2：`/etc/hosts` 陷阱 ★★★★
> 1. **在 `/etc/hosts` 加一行把 `example.com` 指到 `127.0.0.1`**
> 2. **`dig +short example.com`** → 回什麼？
> 3. **`getent hosts example.com`** → 呢？
> 4. **`curl -sI http://example.com`** → 連到哪裡？
> 5. **為什麼 `dig` 和實際行為不一致？**
> 6. **排查時該用哪個指令？**

> [!question]- 練習 3：TTL 與快取 ★★★★
> 1. **找一個你能改 DNS 的網域**
> 2. 查目前的 TTL
> 3. **改 A 記錄，然後從 5 個公開 DNS 監控傳播**
> 4. **多久全部更新？**
> 5. **`dig @權威` 和 `dig @8.8.8.8` 什麼時候開始不同？**
> 6. **寫一個監控傳播的腳本**

> [!question]- 練習 4：nameserver 逾時 ★★★★
> 1. **把 `/etc/resolv.conf` 的第一個 nameserver 改成不存在的 IP**
> 2. **`time dig example.com`** → 花多久？
> 3. **`curl -w 'dns=%{time_namelookup}s\n'`** → 呢？
> 4. **加 `options timeout:1 attempts:1`** → 快多少？
> 5. **這個問題在正式環境會造成什麼影響？**
> 6. 恢復設定並驗證

> [!question]- 練習 5：安全檢查 ★★★
> 1. **對你管理的網域測試 `dig AXFR`** → 開放嗎？
> 2. **`dig +short 你的網域 CAA`** → 有設嗎？
> 3. **`dig +dnssec`** → 有 `ad` flag 嗎？
> 4. 從三個不同的 DNS 查同一個網域 → **結果一致嗎？**
> 5. **啟用 DoT 並驗證**
> 6. **檢查你的內部 DNS 有沒有開放遞迴給外部**

---

## 小測驗

Q1. **「改了 DNS 但還是連到舊 IP」，快取存在於哪五個地方**？

Q2. **`dig +trace` 和一般 `dig` 的差別**？什麼時候一定要用它？

Q3. **`dig` 查到的是新 IP 但程式還是連舊的，第一個該檢查什麼**？

Q4. **`flags` 中的 `aa` 代表什麼**？沒有 `aa` 說明什麼？

Q5. **換 IP 的正確流程**？為什麼要提前調 TTL？

Q6. **根網域為什麼不能用 CNAME**？會造成什麼問題？

Q7. **DNS 解析要 5 秒，最可能的原因**？怎麼確認與處置？

Q8. **`/etc/resolv.conf` 改了為什麼會被覆寫**？正確的設定位置在哪？

Q9. **nginx 的 upstream 用網域名稱，換 IP 後為什麼還連舊的**？

Q10. **`dig AXFR` 成功回應為什麼是嚴重的資安問題**？

> [!question]- 測驗答案
> **Q1.** **五層快取**：
> ①**權威伺服器** —— 這一層沒有快取，改了就生效；
> ②**★★★★ 遞迴解析器（ISP / 8.8.8.8 / 內部 DNS）** ——
> 依 TTL 快取，這是**最主要的一層**；
> ③**本機的 stub resolver** —— Ubuntu 的 systemd-resolved、dnsmasq、nscd，
> 用 `resolvectl flush-caches` 清；
> ④**★★★★ 應用程式本身** —— **最容易被忽略的一層**：
> **JVM 預設永久快取 DNS**（`networkaddress.cache.ttl=-1`）、
> **nginx 的 upstream 只在啟動時解析一次**、
> Node/Go 的 keep-alive 連線持續使用舊 IP；
> ⑤**瀏覽器** —— Chrome 有自己的 DNS 快取（`chrome://net-internals/#dns`）。
> **排查順序**：先 `dig @權威` 確認權威是新的，
> 再 `dig @8.8.8.8` 看遞迴層，再 `getent hosts` 看本機，
> 最後檢查應用程式。
>
> **Q2.** **一般 `dig` 是向你設定的遞迴解析器問一次，拿到的可能是快取的答案**；
> **`+trace` 是自己從根伺服器開始，逐層疊代查詢到權威伺服器** ——
> **★★★★ 完全繞過所有快取**。
> **兩個必用的情境**：
> ①**確認「DNS 真的改好了嗎」** ——
> 一般 dig 可能拿到舊的快取，`+trace` 直接問權威，答案是最新的；
> ②**定位是哪一層有問題** ——
> 卡在根 = 網路問題；卡在 `tw.` = 註冊商問題；
> **卡在 `example.gov.tw.` = 你自己的 NS 有問題**。
> 它也能看出 **NS 委派是否正確**（上層說的 NS 和你實際設的是否一致）。
> **注意**：`+trace` 仍需要用本機的解析路徑找到根伺服器，
> 本機 DNS 完全壞掉時它也會失敗。
>
> **Q3.** **★★★★ `/etc/hosts`**。
> `/etc/nsswitch.conf` 的 `hosts:` 行決定查詢順序，預設是：
> ```
> hosts: files mdns4_minimal [NOTFOUND=return] dns
> #      ↑ ★★★★ files（/etc/hosts）優先於 dns
> ```
> **`dig` 只走 DNS，完全不看 `/etc/hosts`** ——
> 所以 `dig` 說是新 IP，但程式（走 `getaddrinfo()`）拿到的是 hosts 裡的舊 IP。
> **正確的比對方式**：
> ```bash
> getent hosts app.example.gov.tw    # ★★★★ 走完整的 nsswitch 流程
> dig +short app.example.gov.tw      # ★★★ 只走 DNS
> # 兩者不同 → 一定是 /etc/hosts 或 nsswitch 的問題
> grep app.example /etc/hosts
> ```
> 這是排查 DNS 問題時**第一個該檢查的地方** ——
> 常常是某人為了測試加了一行然後忘記刪。
>
> **Q4.** **`aa` = Authoritative Answer，表示這個回應來自「該網域的權威伺服器」**。
> **沒有 `aa` 表示答案來自快取**（遞迴解析器的快取，或中間某層的快取）。
> **判讀價值**：
> 你 `dig example.com` 沒有 `aa` 是正常的（問的是遞迴解析器）；
> 但你 `dig example.com @ns1.example.com`（直接問權威）**卻沒有 `aa`**，
> 那就有問題 —— 可能是**這台 NS 其實沒有這個 zone 的資料**
> （lame delegation），或是你問錯了伺服器。
> **其他重要的 flag**：
> `ra` = 該伺服器提供遞迴服務（**權威伺服器不應該對外提供**）；
> `ad` = DNSSEC 驗證通過；
> **`tc` = 回應被截斷**（超過 UDP 限制，客戶端會改用 TCP 重試）。
>
> **Q5.** **★★★★ 正確流程（六步）**：
> ①**提前把 TTL 調低**（例如從 86400 改成 300）；
> ②**★★★★ 等舊的 TTL 完全過期** ——
> 原本是 86400 就要**等一整天**，讓全世界的快取都換成 300；
> ③改 A 記錄之前，**用 `--resolve` 驗證新伺服器完全正常**：
> ```bash
> curl -sI --resolve app.example.tw:443:新IP https://app.example.tw
> ```
> ④改 A 記錄；
> ⑤**從多個公開 DNS 監控傳播**（8.8.8.8 / 1.1.1.1 / 9.9.9.9 / 168.95.1.1），
> 同時**觀察新舊兩台的 access log**；
> ⑥確認舊機沒流量後才下線，過幾天再把 TTL 調回。
> **★★★ 為什麼要提前調 TTL**：
> TTL 是「快取可以保留多久」——
> 如果切換當下 TTL 還是 86400，
> **已經快取了舊 IP 的解析器最長會用舊 IP 一整天**，
> 你完全無法控制。提前調低才能把切換的影響窗口縮短到 5 分鐘。
>
> **Q6.** 因為 **CNAME 記錄規定「不能與任何其他記錄共存」**，
> 而**根網域（zone apex）一定要有 SOA 和 NS 記錄**（這是 DNS 的基本要求）。
> ```
> example.gov.tw.  IN  CNAME  app.example.gov.tw.   ← ★★★★ 違反 RFC 1034
> example.gov.tw.  IN  SOA    ...                    ← 但這個一定要有
> example.gov.tw.  IN  NS     ...                    ← 這個也是
> ```
> **造成的問題**：
> **MX 記錄查不到 → 郵件收不到**；
> NS 查不到 → 委派失效；
> 嚴格的 DNS 伺服器（BIND）會**直接拒絕載入這個 zone**；
> 或者行為變得不可預測（有些解析器忽略 CNAME，有些回 SERVFAIL）。
> **解法**：
> ①用 **A 記錄**（缺點是後端 IP 改變時要手動更新）；
> ②用 DNS 商提供的 **ALIAS / ANAME / CNAME flattening** ——
> 這些在 DNS 伺服器端把 CNAME 展開成 A 記錄回應，對客戶端來說是合法的。
>
> **Q7.** **★★★★ 第一個 nameserver 掛了**。
> `/etc/resolv.conf` 的 nameserver 是**依序嘗試**的，
> **預設逾時是 5 秒**（`options timeout:5`）——
> 第一個沒回應就要**等滿 5 秒**才換第二個。
> **確認方式**：
> ```bash
> resolvectl dns                      # 看有哪些 nameserver
> for ns in 10.10.20.53 10.10.20.54; do
>   printf "%-14s " "$ns"
>   dig +time=2 +tries=1 example.com "@$ns" 2>&1 | \
>     grep -oP 'Query time: \K.*' || echo "★★★★ 無回應"
> done
> ```
> **處置**：
> **短期** —— 調整順序（把正常的放前面）並縮短逾時：
> ```
> options timeout:2 attempts:2 rotate
> ```
> 或在 systemd-resolved 的設定調整 `DNS=` 順序。
> **長期** —— 修好壞掉的那台 DNS 伺服器。
> 這個問題在正式環境影響很大 ——
> **每一個對外的 HTTP 請求都多 5 秒**。
>
> **Q8.** 因為 **Ubuntu 的 `/etc/resolv.conf` 是符號連結**：
> ```bash
> ls -l /etc/resolv.conf
> # → ../run/systemd/resolve/stub-resolv.conf
> ```
> 這個檔案由 **systemd-resolved 動態產生**，
> 每次網路變更或服務重啟都會**重新寫入**，你的手動修改會消失。
> **正確的設定位置**：
> **Ubuntu（netplan）**：
> ```yaml
> # /etc/netplan/50-dns.yaml
> network:
>   ethernets:
>     ens18:
>       nameservers:
>         addresses: [10.10.20.53, 10.10.20.54]
>         search: [example.gov.tw]
> ```
> 然後 `sudo netplan apply`。
> 或用 `/etc/systemd/resolved.conf.d/*.conf` 設全域的 `DNS=`。
> 臨時測試可用 `sudo resolvectl dns ens18 10.10.20.53`。
> **RHEL 系**用 NetworkManager：`nmcli con mod ens18 ipv4.dns "..."`。
> **驗證真正生效的上游**：`resolvectl status`（**不是** `cat /etc/resolv.conf`，
> 那只會看到 `127.0.0.53` 這個 stub）。
>
> **Q9.** 因為 **nginx 開源版對 `upstream` 區塊中的網域名稱，只在「啟動時解析一次」**，
> 之後**永遠使用那個 IP**，即使 DNS 改了、即使 TTL 早就過期。
> ```nginx
> upstream backend {
>     server api.internal.tw:8080;    # ★★★★ 只解析一次
> }
> ```
> **三個解法**：
> ①**商業版 NGINX Plus** —— `server api.internal.tw:8080 resolve;` + `resolver`；
> ②**★★ 開源版用變數強制動態解析**：
> ```nginx
> resolver 10.10.20.53 valid=30s ipv6=off;
> set $backend "api.internal.tw";
> proxy_pass http://$backend:8080;
> ```
> **注意**：`proxy_pass` 使用變數後，**URI 的處理規則會改變**
> （不再自動帶上 location 匹配後的路徑），通常要自己補 `$request_uri`；
> ③**用固定 IP + 換 IP 時 reload nginx**（最簡單可靠，適合內部服務）。
> **同類問題**：`fastcgi_pass`、`proxy_pass` 在 location 中用網域也一樣。
>
> **Q10.** 因為 **AXFR（zone transfer）會回傳「整個網域的所有 DNS 記錄」** ——
> 這等於把**完整的內部網路拓撲**送給任何人：
> 所有主機名與對應 IP（包含**內部管理介面、測試環境、備援站台**）、
> 子網域結構、郵件伺服器、VPN 端點、
> 甚至從命名可以推測出用途（`backup-db-01`、`jenkins`、`vpn-gw`）。
> **這是滲透測試偵察階段的第一步**，一次就拿到完整的攻擊面地圖。
> **測試**：
> ```bash
> dig AXFR example.gov.tw @ns1.example.gov.tw
> # ★★★★ 有完整輸出 = 開放了，要立刻修正
> # ✓ 應該回 "Transfer failed."
> ```
> **修正（BIND）**：
> ```
> allow-transfer { 10.10.20.54; };   # ★★ 只允許次要 NS
> ```
> **同時要檢查的還有**：`allow-recursion`（開放遞迴 = **DDoS 放大器**，
> 回應可放大 50~100 倍）、`version` 是否洩漏、有沒有設 rate-limit。

---

## 延伸閱讀

- [[05-curl-與HTTP除錯]] — `time_namelookup` 慢時從這裡開始
- [[16-網路基礎指令]] — 網路基礎
- [[03-ss-netstat-與lsof]] — 連線狀態
- [[01-tcpdump-基礎抓包]] — 抓 DNS 封包（port 53）
- [[12-憑證生命週期管理]] — DNS-01 驗證與 CAA
- [[20-環境變數與設定檔]] — `/etc/hosts` 與 `resolv.conf`
