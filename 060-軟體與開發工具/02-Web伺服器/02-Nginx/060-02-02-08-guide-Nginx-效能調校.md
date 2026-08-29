---
title: "Nginx 效能調校"
desc: "worker 與連線數、核心參數、HTTP/2 與 HTTP/3、限流與逾時的完整調校"
aliases: [worker_processes, worker_connections, HTTP/2, HTTP/3, QUIC, limit_req, 調校]
tags: [群組/軟體與開發工具, 服務/nginx, 主題/效能]
category: Nginx
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[060-02-02-07-guide-Nginx-日誌與除錯]]"]
updated: 2026-08-28
---

# Nginx 效能調校

> [!abstract] 這篇你會學到
> - **先量測再調校**：找出真正的瓶頸在哪一層
> - 正確設定 **worker、連線數、檔案描述元**
> - 調整**作業系統核心參數**（backlog、TIME_WAIT、fd 上限）
> - 啟用 **HTTP/2 與 HTTP/3 (QUIC)**
> - 用 **`limit_req` / `limit_conn`** 保護後端
> - 設定合理的**逾時**與**緩衝**
> - 建立一份**可重複的壓測與驗證流程**

## 前置知識

- [[060-02-02-07-guide-Nginx-日誌與除錯]] — 用日誌找出瓶頸
- [[060-02-02-05-guide-Nginx-靜態資源與快取]] — 壓縮與快取（**效果通常比調參數大**）

---

## 先量測，不要盲調

> [!danger] 最常見的錯誤：直接抄「效能調校懶人包」
> ```
> 從網路上抄一份 nginx.conf
>   → worker_connections 65535、各種 buffer 調到很大
>     → 記憶體用量暴增 → OOM → 服務中斷
>       → 而原本的瓶頸【根本不在 Nginx】
> ```
>
> **實務上 90% 的效能問題不在 Nginx，而在**：
> ```
> ① 資料庫（缺索引、N+1 查詢）           ← 最常見
> ② 應用程式（同步呼叫外部 API）
> ③ 沒有快取（每次都重算）
> ④ 沒有壓縮（傳輸量大 10 倍）
> ⑤ 才是 Nginx 的參數
> ```

### 三層量測法

```bash
#!/usr/bin/env bash
# 找出瓶頸在哪一層
D="${1:?用法: $0 <domain>}"

echo "═══ 【第一層】從日誌看整體分布 ═══"
tail -100000 /var/log/nginx/access.log 2>/dev/null | \
  awk '{
    rt=""; urt=""
    for(i=1;i<=NF;i++) {
      if($i ~ /^rt=/)  rt=substr($i,4)
      if($i ~ /^urt=/) urt=substr($i,5)
    }
    if (rt=="") next
    n++; sum+=rt; a[n]=rt
    if (urt != "" && urt != "-") { un++; usum+=urt }
  } END {
    if (n==0) {print "  ⚠ 日誌沒有 rt= 欄位，先照 07 篇設定 log_format"; exit}
    asort(a)
    printf "  請求數 %d\n", n
    printf "  平均 rt  %.3fs   平均 urt %.3fs\n", sum/n, (un?usum/un:0)
    printf "  P50 %.3f  P90 %.3f  P95 %.3f  P99 %.3f  Max %.3f\n",
           a[int(n*.5)], a[int(n*.9)], a[int(n*.95)], a[int(n*.99)], a[n]
    r = (un ? usum/un : 0) / (sum/n)
    printf "  後端佔比 %.0f%%  → %s\n", r*100,
      (r > 0.7 ? "★ 瓶頸在【後端】，調 Nginx 沒用" : "★ 瓶頸在【Nginx 或網路】")
  }'

echo -e "\n═══ 【第二層】直接打後端（跳過 Nginx）═══"
BACKEND=$(sudo nginx -T 2>/dev/null | grep -oP 'proxy_pass\s+http://\K127\.0\.0\.1:\d+' | head -1)
if [ -n "$BACKEND" ]; then
    echo "  後端：$BACKEND"
    for i in 1 2 3; do
        curl -s -o /dev/null -w "  直接打後端 #$i: %{time_total}s\n" "http://$BACKEND/" 2>/dev/null
    done
else
    echo "  （沒有 TCP 後端，可能是 unix socket 或純靜態）"
fi

echo -e "\n═══ 【第三層】透過 Nginx ═══"
for i in 1 2 3; do
    curl -sk -o /dev/null -w "  透過 Nginx #$i: connect=%{time_connect}s tls=%{time_appconnect}s ttfb=%{time_starttransfer}s total=%{time_total}s\n" \
        "https://$D/" 2>/dev/null
done

echo -e "\n═══ 【系統資源】═══"
echo "  CPU 核心：$(nproc)   記憶體：$(free -h | awk '/^Mem:/{print $3"/"$2}')"
echo "  負載：$(uptime | grep -oP 'load average: \K.*')"
echo "  Nginx worker：$(pgrep -c -f 'nginx: worker')"
echo "  Nginx 記憶體：$(ps -o rss= -C nginx 2>/dev/null | awk '{s+=$1} END {printf "%.0f MB\n", s/1024}')"
echo "  連線："; sudo ss -s 2>/dev/null | head -3 | sed 's/^/    /'
echo "  磁碟 I/O："; iostat -x 1 2 2>/dev/null | tail -n +7 | head -5 | sed 's/^/    /' \
    || echo "    （需要 sysstat 套件）"
```

> [!tip] 調校的優先順序（★ 按這個順序做）
> ```
> ① 開啟壓縮（gzip/brotli）           效益最大，成本最低
> ② 靜態資源長快取 + 預壓縮
> ③ ★ proxy_cache 快取動態內容        QPS 可以提升數十倍
> ④ upstream keepalive
> ⑤ 修正後端的慢查詢與 N+1            通常這才是真正的問題
> ⑥ HTTP/2
> ⑦ worker / 連線數 / 核心參數        只在真的碰到上限時才調
> ⑧ HTTP/3                            錦上添花
> ```

---

## worker 與連線數

```nginx
# ═══ main 區塊 ═══
user www-data;

worker_processes auto;                 # ★ = CPU 核心數（auto 會自動偵測）
worker_cpu_affinity auto;              # ★ 綁定 CPU，減少 context switch
worker_rlimit_nofile 65535;            # ★ 每個 worker 的檔案描述元上限

pid /run/nginx.pid;

events {
    worker_connections 10240;          # ★ 每個 worker 的最大連線數
    use epoll;                         # Linux 上的高效事件模型（auto 會選）
    multi_accept on;                   # 一次接受多個新連線
    accept_mutex off;                  # ★ 現代核心有 SO_REUSEPORT，關掉更好
}
```

### 怎麼算 `worker_connections`

```
理論最大並發連線 = worker_processes × worker_connections

但是【反向代理】時，每個請求要用【兩條】連線：
  一條給客戶端、一條給後端

  → 實際最大並發 ≈ worker_processes × worker_connections / 2
```

```bash
# 目前用了多少
$ sudo ss -tan state established | grep -cE ':(80|443)\b'
2847

# 上限是多少
$ WC=$(sudo nginx -T 2>/dev/null | grep -oP 'worker_connections\s+\K\d+' | head -1)
$ WP=$(pgrep -c -f 'nginx: worker')
$ echo "上限：$((WC * WP))  （反向代理實際約 $((WC * WP / 2))）"
上限：81920  （反向代理實際約 40960）
```

> [!danger] `worker_connections` 不能超過 `worker_rlimit_nofile`
> **每條連線至少要一個 fd，反向代理要兩個。**
> ```nginx
> worker_rlimit_nofile 65535;         # ★ 必須 ≥ worker_connections × 2
> events { worker_connections 10240; }
> ```
>
> **同時 systemd 也要放行**：
> ```bash
> $ sudo systemctl edit nginx
> ```
> ```ini
> [Service]
> LimitNOFILE=65535
> ```
> ```bash
> $ sudo systemctl daemon-reload && sudo systemctl restart nginx
>
> # ★ 驗證（reload 不夠，要 restart）
> $ for pid in $(pgrep -f 'nginx: worker'); do
>     echo "PID $pid: $(sudo grep 'Max open files' /proc/$pid/limits)"
>   done
> PID 1234: Max open files    65535    65535    files
> ```
>
> **沒設好的症狀**：
> ```
> error.log: worker_connections are not enough
> error.log: 24: Too many open files
> → 新的連線【直接被拒絕】
> ```

> [!warning] 記憶體估算
> ```
> 每條連線約需要：
>   基本結構            ~ 2-4 KB
>   + client_header_buffer_size (1k)
>   + client_body_buffer_size   (16k，只在有 body 時)
>   + proxy_buffers             (8×8k = 64k，反向代理時)
>   + ssl 相關                  (~ 20-40 KB，TLS 連線)
>
> 保守估計：HTTPS 反向代理 ≈ 每條連線 100 KB
>
> worker_connections 10240 × 4 workers × 100KB ≈ 4 GB
> ★ 這是【極限值】，實際遠低於此（大部分連線是 idle 的）
> ```
> **不要把 `worker_connections` 設成 65535 卻只有 2GB 記憶體。**

---

## 核心參數調整

```bash
$ sudo tee /etc/sysctl.d/99-nginx.conf >/dev/null <<'EOF'
# ══════════ 連線佇列 ══════════
# ★ 完成三次握手、等待 accept() 的佇列長度
net.core.somaxconn = 65535
# ★ 半開連線（SYN_RECV）佇列
net.ipv4.tcp_max_syn_backlog = 65535
# 網卡收到但還沒被處理的封包佇列
net.core.netdev_max_backlog = 65535

# ══════════ TIME_WAIT ══════════
# ★ 允許 TIME_WAIT 的 socket 被新連線重用（【安全】）
net.ipv4.tcp_tw_reuse = 1
# ★★ 【不要】開啟 tcp_tw_recycle —— 它在 NAT 環境下會【隨機丟棄連線】
#     Linux 4.12 之後已經移除這個參數
# net.ipv4.tcp_tw_recycle = 1        ← ❌❌ 絕對不要
net.ipv4.tcp_max_tw_buckets = 262144
net.ipv4.tcp_fin_timeout = 15

# ══════════ 連接埠範圍 ══════════
# ★ 反向代理需要大量的本機埠去連後端
net.ipv4.ip_local_port_range = 10240 65535

# ══════════ keepalive ══════════
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3

# ══════════ 緩衝區 ══════════
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# ══════════ 其他 ══════════
net.ipv4.tcp_slow_start_after_idle = 0    # ★ keepalive 連線不要重新慢啟動
net.ipv4.tcp_syncookies = 1               # SYN flood 防護
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_congestion_control = bbr     # ★ BBR 壅塞控制（需核心 4.9+）
net.core.default_qdisc = fq               # ★ BBR 需要搭配 fq

# ══════════ 檔案描述元 ══════════
fs.file-max = 2097152
fs.nr_open = 2097152

# ══════════ HTTP/3 (QUIC) 需要更大的 UDP 緩衝 ══════════
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
EOF

$ sudo sysctl --system

# 驗證
$ sysctl net.core.somaxconn net.ipv4.tcp_tw_reuse net.ipv4.tcp_congestion_control
net.core.somaxconn = 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_congestion_control = bbr
```

> [!danger] `net.ipv4.tcp_tw_recycle` 絕對不要開
> **這是網路上「效能調校懶人包」中最危險的一項。**
>
> ```
> tcp_tw_recycle 會拒絕「時間戳記倒退」的封包
>   → 在 NAT 環境下，同一個公網 IP 後面有多台不同時間的裝置
>     → 【後面的裝置連不上，而且是隨機的、間歇性的】
>       → 極難排查（有些人可以、有些人不行、時好時壞）
> ```
>
> **Linux 4.12 之後已經移除這個參數**，
> 但很多舊教學仍然在教。
> **`tcp_tw_reuse = 1` 是安全的，用它就夠了。**

> [!tip] `somaxconn` 與 Nginx 的 `backlog` 要一起改
> ```nginx
> listen 443 ssl backlog=65535;      # ★ 不能超過 net.core.somaxconn
> ```
> ```bash
> # 檢查 accept 佇列有沒有溢位（★ 溢位表示 backlog 不夠）
> $ nstat -az | grep -i listen
> TcpExtListenOverflows    1247      # ★ 不為 0 = 有連線被丟棄
> TcpExtListenDrops        1247
>
> # 即時觀察佇列
> $ ss -tlnp | grep nginx
> State  Recv-Q  Send-Q  Local Address:Port
> LISTEN 0       65535   0.0.0.0:443
> #      ^^^^^^  ^^^^^^^
> #      當前佇列 佇列上限     ★ Recv-Q 持續接近 Send-Q = backlog 不夠
> ```

---

## HTTP/2 與 HTTP/3

### HTTP/2

```nginx
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;                         # ★ Nginx 1.25.1+ 的寫法

    # ── HTTP/2 調校 ──
    http2_max_concurrent_streams 128;      # 單一連線的並行串流數
    keepalive_requests 1000;               # ★ HTTP/2 要設大一點
    keepalive_timeout  75s;
}
```

| HTTP/2 帶來的好處 | 說明 |
| --- | --- |
| **多工（multiplexing）** | **單一連線同時處理多個請求**，消除隊頭阻塞 |
| 標頭壓縮（HPACK） | 大幅減少重複標頭的傳輸量 |
| 二進位分幀 | 解析更快、更省 |
| 伺服器推送 | **已被主流瀏覽器廢棄，不要用** |

> [!warning] HTTP/2 之後不要再做「資源打包」與「domain sharding」
> HTTP/1.1 時代的最佳實務在 HTTP/2 下**反而有害**：
> ```
> ❌ 把所有 JS 打包成一個大檔案
>    → HTTP/2 可以並行載入多個小檔案
>    → 而且一個小檔案改動不會讓整包快取失效
>
> ❌ CSS Sprites（把小圖拼成大圖）
>    → 同上
>
> ❌ Domain sharding（把資源分散到 static1/static2 子網域）
>    → 【反而增加連線數與 TLS 握手】，完全是反效果
>
> ❌ 內聯小資源（inline base64）
>    → 無法被獨立快取
> ```

```bash
# 驗證 HTTP/2
$ curl -sI --http2 https://網站/ | head -1
HTTP/2 200

$ nghttp -nv https://網站/ 2>&1 | head -20      # 更詳細的資訊
```

### HTTP/3 (QUIC)

```nginx
server {
    # ★ 同時保留 HTTP/2（HTTP/3 需要先透過 HTTP/2 通告）
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    # ★ HTTP/3 走 UDP
    listen 443 quic reuseport;
    listen [::]:443 quic reuseport;

    ssl_protocols TLSv1.2 TLSv1.3;         # ★ QUIC 需要 TLS 1.3

    # ★★ 告訴瀏覽器「我支援 HTTP/3」（沒有這行瀏覽器不會用 HTTP/3）
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    quic_gso on;                            # Generic Segmentation Offload
    quic_retry on;                          # 防 amplification 攻擊
}
```

```bash
# ★ 防火牆要開 UDP 443
$ sudo ufw allow 443/udp
# RHEL: sudo firewall-cmd --permanent --add-port=443/udp && sudo firewall-cmd --reload

# 確認 Nginx 有 HTTP/3 支援
$ nginx -V 2>&1 | grep -o 'with-http_v3_module'
with-http_v3_module

# 驗證
$ curl --http3 -sI https://網站/ | head -1
HTTP/3 200

$ curl -sI https://網站/ | grep -i alt-svc
alt-svc: h3=":443"; ma=86400
```

| HTTP/3 適合 | HTTP/3 不適合 |
| --- | --- |
| **行動網路**（換基地台不斷線） | 內部網路（TCP 已經很好） |
| **高延遲、高丟包**的環境 | UDP 被封鎖的企業網路 |
| 首次連線（0-RTT / 1-RTT 握手） | CPU 較弱的伺服器（**加密在使用者空間，CPU 較高**） |

> [!warning] HTTP/3 的三個注意事項
> ① **必須同時保留 HTTP/2** —— 瀏覽器先用 HTTP/2 連上，
> 看到 `Alt-Svc` 標頭才知道可以升級到 HTTP/3
> ② **`reuseport` 是必要的** —— 讓每個 worker 有自己的 UDP socket
> ③ **CPU 用量會比 HTTP/2 高** —— QUIC 的加密在使用者空間做，
> 沒有 kTLS 的核心加速。**先壓測再決定是否啟用**

---

## 限流與連線限制

```nginx
http {
    # ═══ 定義限流區 ═══
    # ★ 一般請求：每秒 20 次
    limit_req_zone $binary_remote_addr zone=general:20m rate=20r/s;
    # ★ 登入端點：每分鐘 5 次（防暴力破解）
    limit_req_zone $binary_remote_addr zone=login:10m   rate=5r/m;
    # ★ API：每秒 50 次
    limit_req_zone $binary_remote_addr zone=api:20m     rate=50r/s;
    # ★ 依伺服器整體限流（保護後端）
    limit_req_zone $server_name        zone=perserver:10m rate=1000r/s;

    # ═══ 連線數限制 ═══
    limit_conn_zone $binary_remote_addr zone=perip:20m;
    limit_conn_zone $server_name        zone=perserver_conn:10m;

    # ═══ 被限流時回傳的狀態碼 ═══
    limit_req_status  429;             # ★ 429 Too Many Requests（不要用預設的 503）
    limit_conn_status 429;
    limit_req_log_level warn;

    server {
        # ── 全站基本限流 ──
        limit_req  zone=general burst=40 nodelay;
        limit_conn perip 20;

        # ── ★ 登入端點嚴格限流 ──
        location = /login {
            limit_req zone=login burst=3 nodelay;
            limit_req_status 429;
            proxy_pass http://backend;
        }

        location = /api/auth/token {
            limit_req zone=login burst=3 nodelay;
            proxy_pass http://backend;
        }

        # ── API ──
        location ^~ /api/ {
            limit_req zone=api burst=100 delay=50;
            proxy_pass http://backend;
        }

        # ── 下載限速 ──
        location ^~ /downloads/ {
            limit_rate_after 10m;      # 前 10MB 全速
            limit_rate 2m;             # 之後限 2MB/s
            limit_conn perip 2;        # 每個 IP 最多 2 個同時下載
        }

        # ── ★ 靜態資源不限流 ──
        location ~* \.(?:js|css|png|jpg|woff2)$ {
            limit_req off;
            limit_conn off;
            expires 1y;
        }
    }
}
```

### `burst` 與 `nodelay` 的差別 ★

```
rate=20r/s 表示「平均每 50ms 允許一個請求」

┌── burst=40（沒有 nodelay）──────────────────────┐
│ 超出速率的請求【排隊等待】，依 50ms 的間隔慢慢放行 │
│ 佇列滿了（40 個）才回 429                        │
│ → 使用者感覺【很慢但會成功】                      │
└──────────────────────────────────────────────┘

┌── burst=40 nodelay ★ 推薦 ────────────────────┐
│ 前 40 個突發請求【立刻處理，不等待】              │
│ 但仍佔用配額，配額用完就回 429                    │
│ → 使用者感覺【快，超過才被擋】                    │
└──────────────────────────────────────────────┘

┌── burst=100 delay=50 ─────────────────────────┐
│ 前 50 個【立刻處理】                             │
│ 第 51-100 個【排隊等待】                         │
│ 超過 100 個回 429                                │
│ → 折衷方案                                      │
└──────────────────────────────────────────────┘
```

> [!danger] 限流的三個常見錯誤
> **錯誤一：對靜態資源限流**
> ```
> 一個頁面可能載入 50 個資源
>   → rate=20r/s 會讓【正常使用者】被擋
>     → 頁面破圖、CSS 沒載入
> ```
> **解法**：靜態資源 `limit_req off;`
>
> **錯誤二：忘記 NAT 環境**
> ```
> 整個機關 200 人共用一個公網 IP
>   → $binary_remote_addr 看起來都是同一個
>     → rate=20r/s 對整個機關生效 → 全部被擋
> ```
> **解法**：內部網段排除，或用其他 key
> ```nginx
> geo $limit_exempt { default 0; 10.0.0.0/8 1; 172.16.0.0/12 1; }
> map $limit_exempt $limit_key {
>     0 $binary_remote_addr;
>     1 "";                       # ★ 空值 = 不限流
> }
> limit_req_zone $limit_key zone=general:20m rate=20r/s;
> ```
>
> **錯誤三：用 503 而非 429**
> ```
> 503 = 服務暫時無法使用（監控系統會誤判為「服務掛了」而告警）
> 429 = 請求太多（★ 正確的語意，而且客戶端知道要退避重試）
> ```
> ```nginx
> limit_req_status 429;
> ```

```nginx
# ★ 加上 Retry-After 標頭，讓客戶端知道何時可以重試
error_page 429 = @ratelimited;
location @ratelimited {
    add_header Retry-After 60 always;
    default_type application/json;
    return 429 '{"error":"too_many_requests","retry_after":60}';
}
```

```bash
# 測試限流
$ for i in $(seq 1 60); do
    printf '%3d %s\n' "$i" "$(curl -s -o /dev/null -w '%{http_code}' https://網站/api/test)"
  done | sort | uniq -c -f1
# 應該看到前面是 200，超過 burst 之後變 429

# 看被限流的紀錄
$ sudo grep 'limiting requests' /var/log/nginx/error.log | tail -20
2026/08/28 10:15:32 [warn] 1234#0: *5678 limiting requests, excess: 20.500 by zone "general",
client: 203.0.113.5, server: app.example.gov.tw, request: "GET /api/x HTTP/2.0"

# 統計被限流最多的 IP
$ sudo grep 'limiting requests' /var/log/nginx/error.log | \
    grep -oP 'client: \K[0-9.]+' | sort | uniq -c | sort -rn | head -10
```

---

## 逾時與緩衝

```nginx
http {
    # ═══ 客戶端逾時 ═══
    client_header_timeout 10s;         # ★ 短一點，防 Slowloris
    client_body_timeout   30s;         # ★ 短一點，防 Slow POST
    send_timeout          30s;
    keepalive_timeout     65s;
    keepalive_requests    1000;

    # ═══ 客戶端緩衝 ═══
    client_header_buffer_size     1k;
    large_client_header_buffers   4 16k;    # ★ 大 Cookie / 長 URL 時要調大
    client_body_buffer_size       128k;     # 超過就寫到暫存檔
    client_max_body_size          20m;      # ★ 與 PHP 的 upload_max_filesize 一致

    # ═══ 後端逾時 ═══
    proxy_connect_timeout 10s;         # ★ 連不上就快點失敗
    proxy_send_timeout    60s;
    proxy_read_timeout    60s;

    fastcgi_connect_timeout 10s;
    fastcgi_send_timeout    60s;
    fastcgi_read_timeout    60s;

    # ═══ 後端緩衝 ═══
    proxy_buffering         on;
    proxy_buffer_size       8k;        # 標頭用
    proxy_buffers           8 8k;      # 內容用
    proxy_busy_buffers_size 16k;
    proxy_max_temp_file_size 1024m;

    fastcgi_buffering       on;
    fastcgi_buffer_size     16k;       # ★ PHP 的標頭常常較大
    fastcgi_buffers         16 16k;
    fastcgi_busy_buffers_size 32k;

    # ═══ 其他 ═══
    reset_timedout_connection on;      # 逾時的連線直接 RST，快速釋放資源
    server_tokens off;
}
```

> [!tip] 逾時設定的三個原則
> ```
> ① client_header_timeout / client_body_timeout 要【短】
>    → 防止 Slowloris / Slow POST 慢速攻擊
>    → 10-30 秒就夠，正常使用者不會超過
>
> ② proxy_connect_timeout 要【短】（5-10 秒）
>    → 連不上後端就該快點失敗、切換節點
>    → 設 60 秒只會讓使用者等更久
>
> ③ proxy_read_timeout 依【業務】而定
>    → 一般 API：30-60 秒
>    → 報表產生：可能需要 300 秒（★ 但更好的做法是改成非同步佇列）
>    → WebSocket / SSE：3600 秒
> ```

> [!warning] `an upstream response is buffered to a temporary file`
> ```
> 後端回應超過 proxy_buffers 的總大小
>   → Nginx 把它寫到磁碟暫存檔
>     → 【每個大回應都是一次磁碟寫入】→ I/O 壓力
> ```
>
> **判斷是否需要調整**：
> ```bash
> $ sudo grep -c 'buffered to a temporary file' /var/log/nginx/error.log
> 8421                          # ★ 大量出現才需要調
> ```
>
> **兩種處理方式**：
> ```nginx
> # A. 調大緩衝（★ 注意：每條連線都會佔這麼多記憶體）
> proxy_buffers 16 32k;         # 16×32k = 512k
>
> # B. 這本來就是大檔案下載 → 關掉緩衝，直接串流
> location ^~ /downloads/ {
>     proxy_buffering off;
> }
> ```

---

## 完整實戰範例

### 一份完整的 nginx.conf

```nginx
# ═══════════════ /etc/nginx/nginx.conf ═══════════════
user  www-data;
worker_processes      auto;
worker_cpu_affinity   auto;
worker_rlimit_nofile  65535;
pid /run/nginx.pid;

# 動態模組
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 10240;
    use epoll;
    multi_accept on;
    accept_mutex off;
}

http {
    # ── MIME ──
    include      /etc/nginx/mime.types;
    default_type application/octet-stream;

    # ── 效能 ──
    sendfile           on;
    sendfile_max_chunk 2m;
    tcp_nopush         on;
    tcp_nodelay        on;
    aio                threads;
    directio           16m;

    open_file_cache          max=20000 inactive=60s;
    open_file_cache_valid    60s;
    open_file_cache_min_uses 2;
    open_file_cache_errors   on;

    # ── 逾時（★ 客戶端短、後端依業務）──
    client_header_timeout 10s;
    client_body_timeout   30s;
    send_timeout          30s;
    keepalive_timeout     65s;
    keepalive_requests    1000;
    reset_timedout_connection on;

    # ── 緩衝 ──
    client_header_buffer_size   1k;
    large_client_header_buffers 4 16k;
    client_body_buffer_size     128k;
    client_max_body_size        20m;

    proxy_buffering           on;
    proxy_buffer_size         8k;
    proxy_buffers             8 8k;
    proxy_busy_buffers_size   16k;
    proxy_connect_timeout     10s;
    proxy_send_timeout        60s;
    proxy_read_timeout        60s;

    fastcgi_buffering         on;
    fastcgi_buffer_size       16k;
    fastcgi_buffers           16 16k;
    fastcgi_busy_buffers_size 32k;
    fastcgi_connect_timeout   10s;
    fastcgi_read_timeout      60s;

    # ── 隱藏版本 ──
    server_tokens off;

    # ── 壓縮 ──
    gzip            on;
    gzip_vary       on;
    gzip_comp_level 5;
    gzip_min_length 1024;
    gzip_proxied    any;
    gzip_static     on;
    gzip_types text/plain text/css text/xml text/javascript
               application/javascript application/json application/xml
               application/ld+json application/manifest+json image/svg+xml;

    # ── 日誌（見 07 篇）──
    log_format main escape=default
        '$remote_addr - $remote_user [$time_local] "$request" '
        '$status $body_bytes_sent "$http_referer" "$http_user_agent" '
        'rt=$request_time uct=$upstream_connect_time uht=$upstream_header_time '
        'urt=$upstream_response_time ua=$upstream_addr us=$upstream_status '
        'cache=$upstream_cache_status host=$host xff="$http_x_forwarded_for" '
        'ssl=$ssl_protocol/$ssl_cipher';
    access_log /var/log/nginx/access.log main buffer=64k flush=5s;
    error_log  /var/log/nginx/error.log  warn;

    # ── 限流區 ──
    geo $limit_exempt {
        default 0;
        10.0.0.0/8     1;
        172.16.0.0/12  1;
        192.168.0.0/16 1;
        127.0.0.0/8    1;
    }
    map $limit_exempt $limit_key {
        0 $binary_remote_addr;
        1 "";
    }
    limit_req_zone  $limit_key zone=general:20m rate=20r/s;
    limit_req_zone  $limit_key zone=login:10m   rate=5r/m;
    limit_req_zone  $limit_key zone=api:20m     rate=50r/s;
    limit_conn_zone $limit_key zone=perip:20m;
    limit_req_status  429;
    limit_conn_status 429;
    limit_req_log_level warn;

    # ── 快取區（見 05 篇）──
    proxy_cache_path /var/cache/nginx/app
        levels=1:2 keys_zone=app_cache:100m
        max_size=10g inactive=60m use_temp_path=off;

    # ── TLS（見 06 篇）──
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache   shared:SSL:50m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 1.1.1.1 8.8.8.8 valid=300s ipv6=off;
    ssl_buffer_size 4k;

    # ── WebSocket map ──
    map $http_upgrade $connection_upgrade {
        default upgrade;
        ''      close;
    }

    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
```

### 壓測與驗證流程

```bash
#!/usr/bin/env bash
# /usr/local/bin/nginx-bench —— 壓測與比對
D="${1:?用法: $0 <domain> [path]}"
P="${2:-/}"
URL="https://$D$P"

command -v ab >/dev/null || { echo "請先安裝：sudo apt install -y apache2-utils"; exit 1; }

echo "═══ 壓測 $URL ═══"
echo "★ 壓測前先記錄基準值，改設定後用同樣的參數重測"
echo

# ── 暖機 ──
echo "暖機中..."
ab -n 200 -c 5 "$URL" >/dev/null 2>&1

run() {
    local n="$1" c="$2" extra="${3:-}"
    echo "── 並發 $c，總計 $n 次 $extra ──"
    # shellcheck disable=SC2086
    ab -n "$n" -c "$c" -k $extra "$URL" 2>/dev/null | \
      grep -E 'Requests per second|Time per request:.*mean\)|Failed requests|Transfer rate|^  50%|^  95%|^  99%' | \
      sed 's/^/  /'
    echo
}

run 2000 10
run 5000 50
run 10000 200

echo "── 帶壓縮 ──"
ab -n 2000 -c 50 -k -H 'Accept-Encoding: gzip,br' "$URL" 2>/dev/null | \
  grep -E 'Requests per second|Total transferred' | sed 's/^/  /'

echo
echo "═══ 壓測期間的系統狀態 ═══"
echo "  Nginx worker CPU："
top -bn1 -o %CPU 2>/dev/null | grep nginx | head -5 | \
  awk '{printf "    PID %s CPU %s%% MEM %s%%\n", $1, $9, $10}'
echo "  連線："
sudo ss -s 2>/dev/null | head -2 | sed 's/^/    /'
echo "  ★ accept 佇列溢位："
nstat -az 2>/dev/null | grep -iE 'ListenOverflows|ListenDrops' | sed 's/^/    /'
echo "  ★ Nginx 錯誤（壓測期間）："
sudo tail -20 /var/log/nginx/error.log | grep -cE 'worker_connections|too many open files' | \
  awk '{if($1>0) print "    ⚠ 有 "$1" 筆連線數/fd 相關錯誤 —— 需要調大"; else print "    ✓ 無"}'

echo
echo "═══ 檢查清單 ═══"
for item in \
  "gzip on:壓縮" \
  "sendfile on:零複製" \
  "tcp_nopush on:封包合併" \
  "open_file_cache max:檔案快取" \
  "keepalive :upstream keepalive" \
  "http2 on:HTTP/2" \
  "proxy_cache_path:反向代理快取" \
  "limit_req_zone:限流"
do
    key="${item%%:*}"; desc="${item##*:}"
    sudo nginx -T 2>/dev/null | grep -q "$key" \
      && printf '  ✓ %s\n' "$desc" || printf '  ○ %s（未啟用）\n' "$desc"
done

echo
echo "★ 提醒：ab 只能測單一 URL。真實負載請用 k6 / wrk / vegeta 模擬使用者行為。"
```

### 調校前後的比對表

```bash
#!/usr/bin/env bash
# 記錄目前的關鍵設定，方便調校前後比對
echo "═══ Nginx 關鍵設定快照 $(date '+%F %T') ═══"
for k in worker_processes worker_connections worker_rlimit_nofile \
         keepalive_timeout keepalive_requests client_max_body_size \
         gzip gzip_comp_level proxy_buffer_size proxy_read_timeout; do
    v=$(sudo nginx -T 2>/dev/null | grep -oP "^\s*$k\s+\K[^;]+" | head -1)
    printf '  %-24s %s\n' "$k" "${v:-（未設定，用預設值）}"
done
echo
echo "  ── 核心參數 ──"
for k in net.core.somaxconn net.ipv4.tcp_tw_reuse net.ipv4.ip_local_port_range \
         net.ipv4.tcp_congestion_control fs.file-max; do
    printf '  %-32s %s\n' "$k" "$(sysctl -n "$k" 2>/dev/null)"
done
echo
echo "  ── systemd 限制 ──"
systemctl show nginx -p LimitNOFILE 2>/dev/null | sed 's/^/  /'
```

---

## 常見錯誤與排錯

| 現象／錯誤 | 原因 | 解法 |
| --- | --- | --- |
| **`worker_connections are not enough`** | 連線數用完 | 調大 `worker_connections`；**同時調 `worker_rlimit_nofile`** |
| **`too many open files`** | fd 上限 | `worker_rlimit_nofile 65535;` + **systemd `LimitNOFILE`** + `restart` |
| **調了 LimitNOFILE 但沒生效** | **`reload` 不夠** | **必須 `systemctl restart nginx`** |
| **NAT 環境下部分使用者間歇性連不上** ★ | **開了 `tcp_tw_recycle`** | **關掉它**（4.12+ 已移除） |
| 大量 TIME_WAIT | 沒有 keepalive | upstream `keepalive` + `proxy_http_version 1.1` + `Connection ""` |
| `ListenOverflows` 不為 0 | accept 佇列溢位 | 調大 `net.core.somaxconn` 與 `listen ... backlog=` |
| **記憶體暴增 / OOM** | buffer 或 worker_connections 設太大 | **每條連線 ≈ 100KB，回頭算總量** |
| **正常使用者被限流擋住** ★ | 對靜態資源限流 / NAT | 靜態資源 `limit_req off;`；內網用 `geo` 排除 |
| 限流回 503 導致監控誤判 | 用了預設狀態碼 | **`limit_req_status 429;`** |
| `an upstream response is buffered to a temporary file` | 回應超過 buffer | 調大 `proxy_buffers` 或該路徑 `proxy_buffering off` |
| **`upstream sent too big header`** | 後端標頭大（大 Cookie、多 Set-Cookie） | `proxy_buffer_size 32k;` / `fastcgi_buffer_size 32k;` |
| `400 Request Header Or Cookie Too Large` | 客戶端標頭太大 | `large_client_header_buffers 4 32k;` |
| **HTTP/3 連不上** | 防火牆沒開 UDP 443 | `ufw allow 443/udp`；`listen 443 quic reuseport;` |
| HTTP/3 沒被使用 | 缺 `Alt-Svc` 標頭 | `add_header Alt-Svc 'h3=":443"; ma=86400' always;` |
| **HTTP/2 之後反而變慢** | 還在做資源打包 / domain sharding | **移除 HTTP/1.1 時代的最佳實務** |
| CPU 跑滿 | gzip_comp_level 太高 / 沒用預壓縮 | `gzip_comp_level 5;` + `gzip_static on` |
| **調了半天沒效果** ★ | **瓶頸根本不在 Nginx** | **先量測**：`rt` vs `urt` |

### 效能問題的排查順序

```bash
# 【1】★ 先確認瓶頸在哪一層（不要跳過這步）
$ tail -100000 /var/log/nginx/access.log | \
    awk '{for(i=1;i<=NF;i++){if($i~/^rt=/)r=substr($i,4);if($i~/^urt=/)u=substr($i,5)}
          if(r!=""){n++;sr+=r; if(u!=""&&u!="-"){m++;su+=u}}}
         END{printf "平均 rt=%.3f urt=%.3f 後端佔比 %.0f%%\n", sr/n, su/m, su/m/(sr/n)*100}'
# 後端佔比 > 70% → 【去調後端，不是 Nginx】

# 【2】系統資源
$ top -bn1 | head -15
$ free -h
$ iostat -x 1 3
$ sudo ss -s

# 【3】Nginx 的連線與 fd
$ sudo ss -tan state established | grep -cE ':(80|443)\b'
$ for p in $(pgrep -f 'nginx: worker'); do
    echo "PID $p: $(ls /proc/$p/fd 2>/dev/null | wc -l) fd"
  done

# 【4】佇列溢位
$ nstat -az | grep -iE 'ListenOverflows|ListenDrops|TCPBacklogDrop'

# 【5】error_log
$ sudo tail -100 /var/log/nginx/error.log | \
    grep -E 'worker_connections|too many open files|buffered to a temporary'

# 【6】後端狀態
$ sudo systemctl status php8.3-fpm
$ pm2 list
# PHP-FPM 的 worker 用完？
$ curl -s http://127.0.0.1/fpm-status | grep -E 'active processes|max children'
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> # ★ systemd 的 fd 限制
> $ sudo systemctl edit nginx
> [Service]
> LimitNOFILE=65535
> $ sudo systemctl daemon-reload && sudo systemctl restart nginx
>
> # ★ SELinux 可能擋住某些調校
> # 例如綁定非標準埠
> $ sudo semanage port -a -t http_port_t -p tcp 8443
> # 允許連 TCP 後端
> $ sudo setsebool -P httpd_can_network_connect 1
>
> # ★ tuned 的效能設定檔
> $ sudo dnf install -y tuned
> $ sudo tuned-adm profile throughput-performance
> $ tuned-adm active
>
> # firewalld 開 UDP 443（HTTP/3）
> $ sudo firewall-cmd --permanent --add-port=443/udp
> $ sudo firewall-cmd --reload
>
> # BBR（RHEL 8/9 核心支援）
> $ sudo modprobe tcp_bbr
> $ echo 'tcp_bbr' | sudo tee /etc/modules-load.d/bbr.conf
> ```

---

## 安全性注意事項

> [!danger] 調大 buffer 與連線數會擴大 DoS 的效果
> ```
> worker_connections 65535 + client_body_buffer_size 10m
>   → 攻擊者開 65535 條連線，每條送 10MB
>     → 【瞬間吃掉 650 GB 記憶體需求】→ OOM → 服務中斷
> ```
>
> **必須同時設定的三道防線**：
> ```nginx
> # ① 連線數限制
> limit_conn_zone $binary_remote_addr zone=perip:20m;
> limit_conn perip 20;
>
> # ② 請求速率限制
> limit_req_zone $binary_remote_addr zone=general:20m rate=20r/s;
> limit_req zone=general burst=40 nodelay;
>
> # ③ ★ 短逾時（防 Slowloris）
> client_header_timeout 10s;
> client_body_timeout   30s;
> reset_timedout_connection on;
> ```

> [!warning] Slowloris 與 Slow POST
> ```
> Slowloris：開很多連線，每個都只送【半個標頭】然後慢慢送
>   → 每條連線佔用一個 worker slot
>     → 連線數用完 → 【正常使用者連不進來】
>
> Slow POST：宣告 Content-Length: 10000000，然後【每秒送 1 byte】
>   → 連線被佔用數小時
> ```
>
> **Nginx 的事件驅動架構天生比 Apache prefork 抗這類攻擊**，
> 但仍需要設定：
> ```nginx
> client_header_timeout 10s;         # ★ 標頭必須在 10 秒內送完
> client_body_timeout   30s;         # ★ body 每次讀取間隔不能超過 30 秒
> limit_conn perip 20;               # ★ 每個 IP 最多 20 條連線
> reset_timedout_connection on;      # 逾時直接 RST
> ```
>
> **驗證**：
> ```bash
> # 用 slowhttptest 測試（★ 只在自己的測試環境）
> $ sudo apt install -y slowhttptest
> $ slowhttptest -c 1000 -H -i 10 -r 200 -t GET -u https://測試站台/ -x 24 -p 3
> # 觀察 "service available" 是否一直是 YES
> ```

> [!warning] `limit_req` 的 zone 大小與記憶體
> ```
> limit_req_zone $binary_remote_addr zone=general:20m rate=20r/s;
>                                          ^^^^ 20MB 共享記憶體
>
> 每個 IP 約佔 64 bytes（IPv4）
>   → 20MB ≈ 32 萬個 IP
>
> ★ zone 滿了會【淘汰最舊的記錄】，不會拒絕服務，但限流會不準
> ```
> **用 `$binary_remote_addr` 而不是 `$remote_addr`** ——
> 前者 IPv4 只佔 4 bytes，後者是字串形式佔 15 bytes 以上。

> [!tip] 效能與安全的平衡
> | 設定 | 效能 | 安全 | 建議 |
> | --- | --- | --- | --- |
> | `worker_connections` 大 | ↑ | ↓ DoS 影響大 | 依記憶體算，**搭配 limit_conn** |
> | `client_body_buffer_size` 大 | ↑ | ↓ 記憶體攻擊 | 128k 就夠，大檔案本來就該寫磁碟 |
> | `keepalive_timeout` 長 | ↑ | ↓ 連線佔用 | 65s 是合理值 |
> | **`server_tokens off`** | — | ↑ | **一定要關** |
> | `limit_req` 嚴格 | ↓ | ↑ | 依實際流量調，**靜態資源要排除** |
> | HTTP/3 | ↑ 行動網路 | ↓ CPU 較高、UDP 放大攻擊 | 先壓測，`quic_retry on` |

---

## 速查表

### 調校優先順序 ★

```
① gzip/brotli 壓縮              效益最大、成本最低
② 靜態資源長快取 + 預壓縮
③ ★ proxy_cache                 QPS 可提升數十倍
④ upstream keepalive
⑤ 修正後端慢查詢與 N+1          ★ 通常這才是真正的問題
⑥ HTTP/2
⑦ worker / 連線數 / 核心參數    只在真的碰到上限時
⑧ HTTP/3
```

### worker 與連線數

```nginx
worker_processes      auto;          # = CPU 核心數
worker_cpu_affinity   auto;
worker_rlimit_nofile  65535;         # ★ ≥ worker_connections × 2
events {
    worker_connections 10240;
    use epoll;  multi_accept on;  accept_mutex off;
}
```

```bash
# systemd 也要放行（★ 必須 restart，reload 不夠）
sudo systemctl edit nginx     # [Service] LimitNOFILE=65535
sudo systemctl daemon-reload && sudo systemctl restart nginx
grep 'Max open files' /proc/$(pgrep -f 'nginx: worker'|head -1)/limits
```

```
理論並發 = worker_processes × worker_connections
反向代理實際 ≈ 上述 / 2（客戶端 + 後端各一條）
記憶體估算：HTTPS 反向代理 ≈ 每條連線 100 KB
```

### 核心參數

```bash
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_tw_reuse = 1              # ★ 安全
# net.ipv4.tcp_tw_recycle              ← ❌❌ 絕對不要（NAT 下隨機斷線）
net.ipv4.ip_local_port_range = 10240 65535
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq
fs.file-max = 2097152
```

```bash
nstat -az | grep -i listen     # ★ ListenOverflows 不為 0 = backlog 不夠
ss -tlnp | grep nginx          # Recv-Q 接近 Send-Q = 佇列快滿
```

### HTTP/2 與 HTTP/3

```nginx
listen 443 ssl;
http2 on;                                       # ★ 1.25.1+ 寫法
listen 443 quic reuseport;                      # HTTP/3
add_header Alt-Svc 'h3=":443"; ma=86400' always; # ★ 沒這行瀏覽器不會用 h3
ssl_protocols TLSv1.2 TLSv1.3;                  # QUIC 需要 1.3
```

```bash
sudo ufw allow 443/udp                          # ★ HTTP/3 走 UDP
curl -sI --http2 https://D/ | head -1
curl --http3 -sI https://D/ | head -1
```

```
❌ HTTP/2 之後不要再做：資源打包、CSS Sprites、domain sharding、inline base64
```

### 限流

```nginx
geo $limit_exempt { default 0; 10.0.0.0/8 1; }        # ★ 內網排除
map $limit_exempt $limit_key { 0 $binary_remote_addr; 1 ""; }

limit_req_zone  $limit_key zone=general:20m rate=20r/s;
limit_req_zone  $limit_key zone=login:10m   rate=5r/m;
limit_conn_zone $limit_key zone=perip:20m;
limit_req_status  429;                                 # ★ 不要用預設 503

limit_req  zone=general burst=40 nodelay;
limit_conn perip 20;
location = /login { limit_req zone=login burst=3 nodelay; }
location ~* \.(js|css|png)$ { limit_req off; limit_conn off; }   # ★ 靜態排除
```

```
burst=N              超出的排隊等待（使用者感覺慢但會成功）
burst=N nodelay ★    前 N 個立刻處理，超過回 429（推薦）
burst=N delay=M      前 M 個立刻，M+1~N 排隊，超過 429
```

### 逾時

```nginx
client_header_timeout 10s;      # ★ 短 —— 防 Slowloris
client_body_timeout   30s;      # ★ 短 —— 防 Slow POST
keepalive_timeout     65s;
proxy_connect_timeout 10s;      # ★ 短 —— 連不上就快點失敗
proxy_read_timeout    60s;      # 依業務（WebSocket 3600s）
reset_timedout_connection on;
```

### 緩衝

```nginx
client_body_buffer_size     128k;
large_client_header_buffers 4 16k;      # 大 Cookie / 長 URL
proxy_buffer_size           8k;
proxy_buffers               8 8k;
fastcgi_buffer_size         16k;        # ★ PHP 標頭常較大
fastcgi_buffers             16 16k;
```

### 壓測

```bash
ab -n 5000 -c 50 -k https://D/
wrk -t4 -c100 -d30s https://D/
# ★ 壓測前記錄基準值；改設定後用同樣參數重測
# ★ ab 只能測單一 URL，真實負載用 k6 / vegeta
```

### 排查順序

```
① ★ rt vs urt → 瓶頸在後端還是 Nginx（不要跳過）
② top / free / iostat -x / ss -s
③ 連線數與 fd 用量
④ nstat -az | grep -i listen（佇列溢位）
⑤ error.log 的 worker_connections / too many open files
⑥ 後端狀態（php-fpm status、pm2 list）
```

---

## 練習題

> [!question]- 練習 1：建立效能基準
> 1. **先不要改任何設定**，記錄基準值：
>    - `ab -n 5000 -c 50 -k` 的 QPS 與 P95
>    - 日誌的 P50/P95/P99
>    - 記憶體與 CPU 用量
> 2. 依「調校優先順序」**一次只改一項**，每次重測
> 3. **記錄每一項帶來的提升**
> 4. **哪一項效益最大？與你的預期一致嗎？**

> [!question]- 練習 2：連線數上限實測
> 1. 故意把 `worker_connections` 設成 `128`
> 2. `ab -n 10000 -c 500 https://網站/`
> 3. 觀察 error_log 的 `worker_connections are not enough`
> 4. 調大到 10240，**同時故意不改** `worker_rlimit_nofile`
> 5. 重測 → 觀察 `too many open files`
> 6. 兩個都調好 + systemd `LimitNOFILE`
> 7. **`systemctl reload` 後檢查 `/proc/PID/limits` —— 生效了嗎？**
> 8. 改成 `restart`，再檢查一次

> [!question]- 練習 3：限流的副作用
> 1. 設定 `limit_req zone=general burst=10 nodelay;`（**不排除靜態資源**）
> 2. 用瀏覽器開啟一個載入 50 個資源的頁面
> 3. **觀察頁面是否破圖、console 是否有 429**
> 4. 加上靜態資源的 `limit_req off;`
> 5. **重測**
> 6. 用 `geo` + `map` 排除內網，從內網再測一次
> 7. 比較 `burst=10`、`burst=10 nodelay`、`burst=50 delay=10` 三種的體感差異

> [!question]- 練習 4：HTTP/2 與 HTTP/3
> 1. 確認 `nginx -V` 有 `http_v2_module` 與 `http_v3_module`
> 2. 啟用 HTTP/2，用 `curl -sI --http2` 驗證
> 3. **用瀏覽器 DevTools 的 Protocol 欄位確認**
> 4. 啟用 HTTP/3（含 `Alt-Svc` 與 UDP 防火牆）
> 5. `curl --http3 -sI` 驗證
> 6. **用 `--limit-rate` 與 `tc` 模擬高延遲高丟包，比較 h2 與 h3 的差異**
> 7. 壓測比較 CPU 用量

> [!question]- 練習 5：Slowloris 防護驗證
> **★ 只在自己的測試環境做**
> 1. 安裝 `slowhttptest`
> 2. **先把逾時設成很長**（`client_header_timeout 300s`）
> 3. `slowhttptest -c 1000 -H -i 10 -r 200 -u https://測試站台/`
> 4. **觀察服務是否變得無法回應**
> 5. 改成 `client_header_timeout 10s` + `limit_conn perip 20`
> 6. **重測，確認 "service available" 一直是 YES**

---

## 小測驗

Q1. **「先量測再調校」的三層量測法是什麼？怎麼判斷瓶頸在 Nginx 還是後端**？

Q2. **調校的優先順序前四項是什麼？為什麼參數調整排在後面**？

Q3. **`worker_connections` 與 `worker_rlimit_nofile` 的關係是什麼？反向代理時實際並發約是多少**？

Q4. **調了 `LimitNOFILE` 但沒生效，最可能的原因是什麼**？

Q5. **`net.ipv4.tcp_tw_recycle` 為什麼絕對不能開？該用什麼取代**？

Q6. **`burst=40` 與 `burst=40 nodelay` 的行為差別是什麼**？

Q7. **限流的三個常見錯誤是什麼**？

Q8. **為什麼 `limit_req_status` 要設成 429 而不是預設值**？

Q9. **HTTP/2 之後哪些 HTTP/1.1 時代的最佳實務反而有害**？

Q10. **啟用 HTTP/3 需要哪三個必要條件**？

> [!question]- 測驗答案
> **Q1.** **三層量測**：
> ①**從日誌看整體分布** —— 算 P50/P95/P99，並比較 `rt` 與 `urt` 的平均值；
> ②**直接打後端**（`curl http://127.0.0.1:3000/`，跳過 Nginx）；
> ③**透過 Nginx**（`curl -w 'connect/tls/ttfb/total'`）。
> **判斷方式**：**比較 `$request_time` 與 `$upstream_response_time`** ——
> **後端佔比（urt/rt）> 70% 就是後端慢**，調 Nginx 沒用，要去查應用與資料庫；
> `rt >> urt` 才是 Nginx 或網路的問題（壓縮 CPU、磁碟 I/O、客戶端頻寬）。
>
> **Q2.** **前四項**：①**開啟壓縮（gzip/brotli）**——效益最大成本最低；
> ②**靜態資源長快取 + 預壓縮**；
> ③**`proxy_cache` 快取動態內容**——QPS 可提升數十倍；
> ④**upstream keepalive**。
> **參數調整排在後面**是因為：
> **實務上 90% 的效能問題不在 Nginx**，而在資料庫（缺索引、N+1）、
> 應用程式（同步呼叫外部 API）、沒有快取、沒有壓縮。
> 盲目抄「調校懶人包」把 `worker_connections` 設成 65535、
> buffer 調到很大，只會**讓記憶體暴增導致 OOM**，
> 而原本的瓶頸根本沒解決。
>
> **Q3.** **`worker_rlimit_nofile` 必須 ≥ `worker_connections × 2`** ——
> 因為每條連線至少要一個檔案描述元，**反向代理時要兩個**
> （一條給客戶端、一條給後端）。
> **理論最大並發** = `worker_processes × worker_connections`；
> **反向代理的實際並發 ≈ 上述數值 ÷ 2**。
> 例如 4 個 worker × 10240 = 81920，反向代理實際約 40960。
> 沒設好的症狀是 error_log 出現
> `worker_connections are not enough` 或 `24: Too many open files`。
>
> **Q4.** **最可能的原因是只做了 `systemctl reload` 而沒有 `restart`** ——
> **`LimitNOFILE` 是 systemd 在啟動程序時設定的，reload 不會重新套用**。
> 正確流程：
> ```bash
> sudo systemctl edit nginx     # [Service] LimitNOFILE=65535
> sudo systemctl daemon-reload
> sudo systemctl restart nginx  # ★ 必須 restart
> ```
> 驗證：`grep 'Max open files' /proc/$(pgrep -f 'nginx: worker'|head -1)/limits`。
> 另一個可能是只改了 Nginx 的 `worker_rlimit_nofile`
> 而沒改 systemd 的限制（systemd 的限制是硬上限）。
>
> **Q5.** 因為 **`tcp_tw_recycle` 會拒絕「時間戳記倒退」的封包** ——
> 在 **NAT 環境下**，同一個公網 IP 後面有多台時間不完全同步的裝置，
> **後面連線的裝置會被隨機拒絕**，症狀是
> **間歇性、隨機的連線失敗**（有些人可以、有些人不行、時好時壞），**極難排查**。
> **Linux 4.12 之後已經移除這個參數**，但很多舊教學仍然在教。
> **該用 `net.ipv4.tcp_tw_reuse = 1` 取代** ——
> 它允許 TIME_WAIT 的 socket 被新的**對外**連線重用，是安全的。
>
> **Q6.** 以 `rate=20r/s`（平均每 50ms 一個請求）為例：
> **`burst=40`（沒有 nodelay）**：超出速率的請求**排隊等待**，
> 依 50ms 的間隔慢慢放行，佇列滿了（40 個）才回 429 ——
> **使用者感覺「很慢但會成功」**。
> **`burst=40 nodelay`**：**前 40 個突發請求立刻處理，不等待**，
> 但仍佔用配額，配額用完就回 429 ——
> **使用者感覺「快，超過才被擋」**。
> **推薦用 `nodelay`**，因為讓使用者等待反而佔用連線。
> 折衷是 `burst=100 delay=50`（前 50 個立刻、51-100 排隊、超過 429）。
>
> **Q7.** ①**對靜態資源限流** —— 一個頁面可能載入 50 個資源，
> `rate=20r/s` 會讓**正常使用者被擋**，導致頁面破圖、CSS 沒載入；
> 解法是靜態資源 `limit_req off;`。
> ②**忘記 NAT 環境** —— 整個機關 200 人共用一個公網 IP，
> `$binary_remote_addr` 看起來都是同一個，**限流對整個機關生效**；
> 解法是用 `geo` + `map` 把內部網段的 key 設成空字串（不限流）。
> ③**用 503 而非 429** —— 503 的語意是「服務暫時無法使用」，
> **監控系統會誤判為服務掛了而發出告警**。
>
> **Q8.** 因為 **429 Too Many Requests 才是正確的語意**：
> ①**503 = 服務暫時無法使用** ——
> 監控系統與健康檢查會把它判定為**「服務掛了」而發出誤告警**；
> ②**429 明確告訴客戶端「你請求太多了」**，
> 符合規範的 HTTP 客戶端（以及搜尋引擎爬蟲）**會自動退避重試**，
> 而看到 503 可能會直接放棄或判定服務不可用。
> 建議再搭配 `Retry-After` 標頭：
> ```nginx
> limit_req_status 429;
> error_page 429 = @ratelimited;
> location @ratelimited {
>     add_header Retry-After 60 always;
>     return 429 '{"error":"too_many_requests"}';
> }
> ```
>
> **Q9.** 因為 HTTP/2 有**多工（單一連線並行多個請求）**，
> 以下 HTTP/1.1 時代的技巧**反而有害**：
> ①**把所有 JS 打包成一個大檔案** ——
> HTTP/2 可以並行載入多個小檔案，而且**一個小檔案改動不會讓整包快取失效**；
> ②**CSS Sprites**（把小圖拼成大圖）—— 同理；
> ③**Domain sharding**（把資源分散到 static1/static2 子網域）——
> **反而增加連線數與 TLS 握手，完全是反效果**；
> ④**內聯小資源（inline base64）** —— 無法被獨立快取。
> 另外**伺服器推送（Server Push）已被主流瀏覽器廢棄，不要用**。
>
> **Q10.** ①**`listen 443 quic reuseport;`**（HTTP/3 走 UDP，
> `reuseport` 讓每個 worker 有自己的 UDP socket）；
> ②**`add_header Alt-Svc 'h3=":443"; ma=86400' always;`** ——
> **沒有這個標頭瀏覽器根本不知道你支援 HTTP/3**
> （瀏覽器先用 HTTP/2 連上，看到 Alt-Svc 才升級），
> 所以**必須同時保留 HTTP/2**；
> ③**防火牆開放 UDP 443**（`sudo ufw allow 443/udp`）。
> 另外還需要：Nginx 編譯時有 `--with-http_v3_module`
> （`nginx -V 2>&1 | grep http_v3`），以及 `ssl_protocols` 含 **TLSv1.3**
> （QUIC 強制要求）。
> 注意 **HTTP/3 的 CPU 用量比 HTTP/2 高**（加密在使用者空間，沒有 kTLS 加速），
> 建議先壓測再決定。

---

## 延伸閱讀

- [[060-02-02-09-guide-Nginx-安全設定]] — 安全加固（與效能的平衡）
- [[060-02-02-05-guide-Nginx-靜態資源與快取]] — 壓縮與快取（**效能提升最大的兩項**）
- [[060-02-02-07-guide-Nginx-日誌與除錯]] — 用日誌找出瓶頸
- [[060-02-02-04-guide-Nginx-反向代理與負載平衡]] — keepalive 與 upstream
- [[060-03-01-02-guide-PHP-FPM設定與Pool調校]] — 後端的 worker 調校
- [[060-02-03-07-guide-Apache-安全與效能]] — Apache 的對應調校
