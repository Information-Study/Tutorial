---
title: "curl 與 HTTP 除錯"
desc: "時間拆解、標頭檢查、TLS 驗證與 API 測試的完整用法"
aliases: [curl, wget, HTTP 除錯, TTFB, httpie]
tags: [群組/軟體與開發工具, 主題/網路診斷, 主題/curl, 主題/http]
category: 常用工具
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[16-網路基礎指令]]"]
updated: 2026-08-28
---

# curl 與 HTTP 除錯

> [!abstract] 這篇你會學到
> - **★★★★ `-w` 時間拆解** —— 一眼看出瓶頸在哪一層
> - 標頭檢查、重導向追蹤、Cookie 處理
> - **★★★ TLS 與憑證的驗證**（含自簽憑證與 mTLS）
> - **★★★ `--resolve`** —— 繞過 DNS 測特定伺服器
> - API 測試：POST / JSON / 認證 / 檔案上傳
> - **★★ curl vs wget vs httpie** 的取捨
> - **★★★ 常見錯誤碼的對照與處置**

## 前置知識

- [[16-網路基礎指令]] — 網路基礎
- [[03-ss-netstat-與lsof]] — 連線狀態

---

## ★★★★ 時間拆解（最重要的功能）

```bash
$ cat > ~/.curl-format <<'EOF'
     DNS 解析:   %{time_namelookup}s
     TCP 連線:   %{time_connect}s
   TLS 交握:     %{time_appconnect}s
   請求送出:     %{time_pretransfer}s
   重導向:       %{time_redirect}s
   ★★★ TTFB:    %{time_starttransfer}s
   ★★ 總時間:    %{time_total}s
   ─────────────────────────────────
   HTTP 狀態:    %{http_code}
   下載大小:     %{size_download} bytes
   下載速度:     %{speed_download} B/s
   重導向次數:   %{num_redirects}
   最終 URL:     %{url_effective}
   遠端 IP:      %{remote_ip}:%{remote_port}
   本機 IP:      %{local_ip}:%{local_port}
EOF

$ curl -w "@$HOME/.curl-format" -o /dev/null -s https://app.example.gov.tw/api/dashboard
     DNS 解析:   0.004123s
     TCP 連線:   0.012456s
   TLS 交握:     0.089234s
   請求送出:     0.089301s
   重導向:       0.000000s
   ★★★ TTFB:    2.104882s
   ★★ 總時間:    2.118445s
   ─────────────────────────────────
   HTTP 狀態:    200
   下載大小:     4820 bytes
   遠端 IP:      10.10.20.31:443
```

```
★★★★ 判讀規則（★ 這張表是排查的核心）：

  ┌─────────────────┬──────────┬────────────────────────────────┐
  │ 哪一段慢        │ 門檻     │ ★ 往哪查                       │
  ├─────────────────┼──────────┼────────────────────────────────┤
  │ DNS 解析        │ > 0.1s   │ ★★ DNS 伺服器、/etc/resolv.conf │
  │                 │          │    快取、多個 nameserver 逾時   │
  ├─────────────────┼──────────┼────────────────────────────────┤
  │ TCP 連線        │ > 0.1s   │ ★★ 網路延遲、防火牆、路由       │
  │ (= connect      │          │    ★★★ 減去 DNS 才是真正的連線 │
  │    - namelookup)│          │       時間（RTT）              │
  ├─────────────────┼──────────┼────────────────────────────────┤
  │ TLS 交握        │ > 0.3s   │ ★★ 憑證鏈太長、OCSP 沒 stapling │
  │ (= appconnect   │          │    ★ RSA 金鑰太大、CPU 不足     │
  │    - connect)   │          │                                │
  ├─────────────────┼──────────┼────────────────────────────────┤
  │ ★★★★ TTFB      │ > 0.5s   │ 【伺服器端處理】               │
  │ (= starttransfer│          │ ★★★ nginx → PHP → 資料庫       │
  │    - pretransfer│          │ ★★ 這是最常見的瓶頸            │
  ├─────────────────┼──────────┼────────────────────────────────┤
  │ 傳輸            │          │ ★★ 內容太大、頻寬不足、         │
  │ (= total        │          │    未壓縮、客戶端網路慢         │
  │    - starttransfer)│       │                                │
  └─────────────────┴──────────┴────────────────────────────────┘
```

```bash
# ★★★ 一行版本（不用建設定檔）
$ curl -sko /dev/null -w 'dns=%{time_namelookup} conn=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total} code=%{http_code}\n' https://app.example.gov.tw

# ★★★★ 從三個位置測，區分是網路還是伺服器
$ for t in 127.0.0.1 10.10.20.31 app.example.gov.tw; do
    printf "%-25s " "$t"
    curl -sko /dev/null --max-time 10 \
      -w 'ttfb=%{time_starttransfer}s total=%{time_total}s code=%{http_code}\n' \
      --resolve "app.example.gov.tw:443:$t" \
      "https://app.example.gov.tw/api/health" 2>/dev/null || echo "失敗"
  done
127.0.0.1                 ttfb=0.084s total=0.089s code=200      # ★ 本機快
10.10.20.31               ttfb=0.091s total=0.098s code=200      # ★ 內網快
app.example.gov.tw        ttfb=2.104s total=2.118s code=200      # ★★★ 外網慢

# ★★★ 連續測 10 次看穩定度
$ for i in $(seq 1 10); do
    curl -sko /dev/null -w '%{time_starttransfer}\n' https://app.example.gov.tw/api/health
  done | sort -n | awk '{a[NR]=$1} END {
    printf "min=%.3f  P50=%.3f  ★★ P90=%.3f  max=%.3f\n", a[1], a[int(NR*0.5)], a[int(NR*0.9)], a[NR]}'
min=0.082  P50=0.091  ★★ P90=2.104  max=2.881
#   ★★★★ P50 快但 P90 慢 → 【間歇性問題】
```

---

## 常用選項 ★★★

| 選項 | 作用 |
| --- | --- |
| **`-I`** | **★★★ 只要標頭**（送 HEAD） |
| **`-i`** | **★★★ 顯示標頭 + 內容** |
| **`-s`** | 安靜（不顯示進度條） |
| **`-S`** | 配合 `-s` 仍顯示錯誤 |
| **`-o file`** / `-O` | 輸出到檔案 |
| **`-L`** | **★★★ 跟隨重導向** |
| **`-v`** | **★★★ 詳細**（含 TLS 交握） |
| `--trace-ascii -` | ★★ 完整的傳輸內容 |
| **`-k`** | **★★★ 不驗證憑證**（★ 只在測試用） |
| **`-w`** | **★★★★ 格式化輸出** |
| **`-H`** | 加標頭 |
| **`-X`** | HTTP 方法 |
| **`-d`** | POST 資料 |
| **`--resolve`** | **★★★★ 覆寫 DNS** |
| **`--max-time`** | **★★★ 總逾時**（★ 一定要設） |
| `--connect-timeout` | 連線逾時 |
| **`-c` / `-b`** | Cookie 存 / 讀 |
| `--compressed` | ★★ 要求壓縮 |
| `-4` / `-6` | 強制 IPv4 / IPv6 |

```bash
# ═══ ★★★ 標頭檢查 ═══
$ curl -sI https://app.example.gov.tw
HTTP/2 200
server: nginx
date: Thu, 28 Aug 2026 16:30:11 GMT
content-type: text/html; charset=UTF-8
strict-transport-security: max-age=31536000; includeSubDomains
x-frame-options: SAMEORIGIN
x-content-type-options: nosniff
cache-control: no-cache, private

# ★★★ 檢查安全標頭
$ curl -sI https://app.example.gov.tw | grep -iE \
    'strict-transport|x-frame|x-content-type|content-security|referrer-policy|permissions-policy'

# ★★ 一次檢查所有該有的
$ for h in strict-transport-security x-frame-options x-content-type-options \
           content-security-policy referrer-policy permissions-policy; do
    v=$(curl -sI https://app.example.gov.tw | grep -i "^$h:" | cut -d' ' -f2-)
    if [ -n "$v" ]; then printf "✓ %-32s %s" "$h" "$v"
    else printf "★★★ 缺少: %s\n" "$h"; fi
  done

# ★★★★ 檢查不該出現的標頭
$ curl -sI https://app.example.gov.tw | grep -iE '^(server|x-powered-by|x-aspnet)'
server: nginx                             # ★ 沒版本號，正確
x-powered-by: PHP/8.3.6                   # ★★★★ 洩漏！要關掉
#   → php.ini: expose_php = Off
```

```bash
# ═══ ★★★ 重導向追蹤 ═══
$ curl -sIL https://example.gov.tw | grep -E '^(HTTP|location)'
HTTP/1.1 301 Moved Permanently
location: https://www.example.gov.tw/
HTTP/2 302
location: https://www.example.gov.tw/zh-tw/
HTTP/2 200

# ★★★ 顯示每一跳的細節
$ curl -sL -w '%{num_redirects} 次重導向，最終 %{url_effective} (%{http_code})\n' \
    -o /dev/null https://example.gov.tw
3 次重導向，最終 https://www.example.gov.tw/zh-tw/ (200)

# ★★ 限制重導向次數（★ 避免無窮迴圈）
$ curl -sL --max-redirs 5 https://example.gov.tw

# ★★★★ 檢查 HTTP → HTTPS 的重導向
$ curl -sI http://app.example.gov.tw | grep -iE '^(HTTP|location)'
HTTP/1.1 301 Moved Permanently
location: https://app.example.gov.tw/     # ★★★ 正確（301 + https）
#   ★★★ 要是 302 → 瀏覽器不會永久記住
#   ★★★★ 要是沒有重導向 → HTTP 明文可存取
```

---

## ★★★ `--resolve` 繞過 DNS

```
★★★★ 這是排查時最有用的選項之一：

  情境：
    · ★★★ DNS 還沒改，要先測新伺服器
    · ★★★ 有多台後端，要分別測
    · ★★ CDN 後面，要測源站
    · ★★ 負載平衡器後面的個別節點
    · ★★★ 測試灰度發布的新版本
```

```bash
# ★★★★ 用法：--resolve 主機名:埠:IP
$ curl -sI --resolve app.example.gov.tw:443:10.10.20.31 https://app.example.gov.tw
#   ★★ 這樣 SNI 和 Host 標頭都是正確的網域，但連到指定的 IP
#   ★★★ 憑證驗證也會正常運作

# ★★★ 對照：用 -H 'Host:' 的差別
$ curl -sI -H 'Host: app.example.gov.tw' https://10.10.20.31
#   ★★★★ 這樣 SNI 是 IP，不是網域
#   → 伺服器可能回錯的 server 區塊，憑證也對不上
#   → ★★★ 所以【一律用 --resolve】

# ★★★★ 分別測試多台後端
$ for ip in 10.10.20.31 10.10.20.32 10.10.20.33; do
    printf "%-15s " "$ip"
    curl -sko /dev/null --max-time 5 \
      -w 'code=%{http_code} ttfb=%{time_starttransfer}s\n' \
      --resolve "app.example.gov.tw:443:$ip" \
      https://app.example.gov.tw/api/health
  done
10.10.20.31     code=200 ttfb=0.084s
10.10.20.32     code=200 ttfb=0.091s
10.10.20.33     code=502 ttfb=0.042s        # ★★★★ 這台有問題！

# ★★★ 測試 CDN 的源站
$ curl -sI --resolve www.example.gov.tw:443:203.0.113.10 \
    https://www.example.gov.tw | grep -iE 'server|x-cache|age'

# ★★ 同時覆寫多個
$ curl -s --resolve 'a.example.tw:443:10.0.0.1' \
       --resolve 'b.example.tw:443:10.0.0.2' https://a.example.tw
```

---

## ★★★ TLS 與憑證

```bash
# ═══ ★★★ 看完整的 TLS 交握 ═══
$ curl -v https://app.example.gov.tw 2>&1 | grep -E '^\*' | head -25
* Connected to app.example.gov.tw (10.10.20.31) port 443
* ALPN: curl offers h2,http/1.1
* TLSv1.3 (OUT), TLS handshake, Client hello (1):
* TLSv1.3 (IN), TLS handshake, Server hello (2):
* TLSv1.3 (IN), TLS handshake, Certificate (11):
* TLSv1.3 (IN), TLS handshake, CERT verify (15):
* SSL connection using TLSv1.3 / TLS_AES_256_GCM_SHA384     # ★★★ 協定與套件
* Server certificate:
*  subject: CN=app.example.gov.tw
*  start date: Jul  1 00:00:00 2026 GMT
*  expire date: Sep 29 23:59:59 2026 GMT                     # ★★★ 到期日
*  subjectAltName: host "app.example.gov.tw" matched cert's "app.example.gov.tw"
*  issuer: C=US; O=Let's Encrypt; CN=R11
*  SSL certificate verify ok.                                # ★★★ 驗證通過

# ★★★ 只看關鍵資訊
$ curl -v https://app.example.gov.tw 2>&1 | \
    grep -E 'SSL connection|subject:|expire date:|issuer:|verify'

# ★★ 指定 TLS 版本測試
$ curl -sI --tlsv1.2 --tls-max 1.2 https://app.example.gov.tw >/dev/null && echo "TLS1.2 ✓"
$ curl -sI --tlsv1.3 https://app.example.gov.tw >/dev/null && echo "TLS1.3 ✓"
$ curl -sI --tlsv1.0 --tls-max 1.0 https://app.example.gov.tw >/dev/null 2>&1 \
    && echo "★★★★ TLS1.0 還開著！要關掉" || echo "TLS1.0 已停用 ✓"

# ★★★ 檢查憑證鏈是否完整
$ curl -sI https://app.example.gov.tw
curl: (60) SSL certificate problem: unable to get local issuer certificate
#   ★★★★ 通常是【伺服器沒送中繼憑證】
#   ★★ 驗證：
$ openssl s_client -connect app.example.gov.tw:443 \
    -servername app.example.gov.tw </dev/null 2>/dev/null | grep -c 'BEGIN CERTIFICATE'
1                                    # ★★★★ 只有 1 張 = 缺中繼！
2                                    # ★★★ 正常（伺服器 + 中繼）
```

```bash
# ═══ ★★★ 自簽憑證的處理 ═══
$ curl -sI https://internal.example.gov.tw
curl: (60) SSL certificate problem: self-signed certificate in certificate chain

# ★★★★ 錯誤做法：-k（忽略驗證）
$ curl -kI https://internal.example.gov.tw
#   → ★★★★ 這等於關掉所有 TLS 保護，會被中間人攻擊
#   → ★★ 只能用在【明知是測試環境】的臨時排查

# ★★★ 正確做法：指定 CA
$ curl --cacert /usr/local/share/ca-certificates/internal-root-ca.crt \
    -sI https://internal.example.gov.tw
$ curl --capath /etc/ssl/certs -sI https://internal.example.gov.tw

# ★★★ 或把 CA 加進系統信任存放區（★ 一勞永逸）
$ sudo cp internal-root-ca.crt /usr/local/share/ca-certificates/
$ sudo update-ca-certificates
$ curl -sI https://internal.example.gov.tw     # ★★ 不用任何參數了

# ★★ 只驗證憑證但不驗證主機名（★ 很少用）
$ curl --cacert ca.crt --insecure-no-hostname-verify ...   # ★ 不同版本語法不同

# ═══ ★★★ mTLS（雙向認證）═══
$ curl --cert client.crt --key client.key \
       --cacert ca-chain.crt \
       https://mtls.example.gov.tw/api/data

# ★★ 用 PKCS#12
$ curl --cert-type P12 --cert client.p12:密碼 \
       --cacert ca-chain.crt https://mtls.example.gov.tw/api/data

# ★★ 驗證伺服器有要求客戶端憑證
$ curl -v https://mtls.example.gov.tw 2>&1 | grep -i 'certificate request'
* TLSv1.3 (IN), TLS handshake, Request CERT (13):      # ★★★ 有要求
```

---

## API 測試 ★★★

```bash
# ═══ ★★★ GET ═══
$ curl -s 'https://api.example.gov.tw/users?page=1&per_page=20' \
    -H 'Accept: application/json' | jq .

# ═══ ★★★ POST JSON ═══
$ curl -s -X POST https://api.example.gov.tw/users \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json' \
    -d '{"name":"測試","email":"test@example.gov.tw"}' | jq .

# ★★ 從檔案讀 body
$ curl -s -X POST https://api.example.gov.tw/users \
    -H 'Content-Type: application/json' \
    -d @payload.json | jq .

# ★★★ 表單
$ curl -s -X POST https://app.example.gov.tw/login \
    -d 'email=user@example.gov.tw' -d 'password=secret' \
    -d '_token=abc123'

# ═══ ★★★ 檔案上傳 ═══
$ curl -s -X POST https://api.example.gov.tw/upload \
    -H 'Authorization: Bearer TOKEN' \
    -F 'file=@/path/to/report.pdf' \
    -F 'category=reports' | jq .

# ★★ 指定 MIME type
$ curl -F 'file=@a.csv;type=text/csv' ...

# ═══ ★★★ 認證 ═══
$ curl -s -u 'user:password' https://api.example.gov.tw/data      # Basic
$ curl -s -H 'Authorization: Bearer eyJhbGci...' https://api.example.gov.tw/data
$ curl -s -H 'X-API-Key: abc123' https://api.example.gov.tw/data

# ★★★★ 密碼不要寫在指令列（★ 會進 history 和 ps）
$ curl -s -u 'user' https://api.example.gov.tw/data       # ★★ 互動輸入密碼
$ curl -s -H "Authorization: Bearer $(cat ~/.api-token)" ...
$ curl -s --netrc-file ~/.netrc https://api.example.gov.tw/data
$ cat ~/.netrc                                             # ★★ chmod 600
machine api.example.gov.tw
login myuser
password mypassword
```

```bash
# ═══ ★★★ Cookie 與 session ═══
$ curl -s -c /tmp/cookies.txt https://app.example.gov.tw/login       # ★★ 存 cookie
$ curl -s -b /tmp/cookies.txt https://app.example.gov.tw/dashboard   # ★★ 帶 cookie
$ curl -s -b /tmp/cookies.txt -c /tmp/cookies.txt ...                # ★★★ 讀+更新

# ★★★★ Laravel Sanctum SPA 登入的完整流程
$ COOKIE=/tmp/sanctum.txt
$ rm -f "$COOKIE"

#   ① ★★★ 先拿 CSRF cookie
$ curl -s -c "$COOKIE" https://api.example.gov.tw/sanctum/csrf-cookie

#   ② ★★★ 從 cookie 取出 token 並 URL decode
$ XSRF=$(awk '/XSRF-TOKEN/{print $7}' "$COOKIE" | \
    python3 -c 'import sys,urllib.parse; print(urllib.parse.unquote(sys.stdin.read().strip()))')

#   ③ ★★★ 登入
$ curl -s -b "$COOKIE" -c "$COOKIE" \
    -X POST https://api.example.gov.tw/login \
    -H "X-XSRF-TOKEN: $XSRF" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json' \
    -H 'Referer: https://app.example.gov.tw' \
    -d '{"email":"user@example.gov.tw","password":"secret"}' | jq .

#   ④ ★★ 用 session 存取
$ curl -s -b "$COOKIE" https://api.example.gov.tw/api/user \
    -H 'Accept: application/json' | jq .
```

```bash
# ═══ ★★ 其他實用技巧 ═══
$ curl -s --compressed https://app.example.gov.tw | wc -c     # ★★ 要求壓縮
$ curl -sI --compressed https://app.example.gov.tw | grep -i content-encoding
content-encoding: br                     # ★★ Brotli

$ curl -s -r 0-1023 https://example.gov.tw/big.zip -o part1   # ★★ 範圍請求
$ curl -s -C - -O https://example.gov.tw/big.zip              # ★★ 續傳

$ curl -s --limit-rate 100k -O https://example.gov.tw/big.zip # ★ 限速

$ curl -s --retry 3 --retry-delay 2 --retry-max-time 30 URL   # ★★ 重試

$ curl -s -x http://proxy.example.gov.tw:3128 https://example.com   # ★★ proxy
$ curl -s --noproxy '*' https://internal.example.gov.tw             # ★★ 繞過 proxy

$ curl -s --http1.1 https://app.example.gov.tw                # ★★ 強制 HTTP/1.1
$ curl -sI --http2 https://app.example.gov.tw | head -1
HTTP/2 200
$ curl -sI --http3 https://app.example.gov.tw | head -1       # ★ 需要 curl 支援
```

---

## ★★ curl vs wget vs httpie

| | **curl** | **wget** | **httpie** |
| --- | --- | --- | --- |
| 主要用途 | **★★★ API 測試、除錯** | **★★★ 下載檔案** | ★★ 人類友善的 API 測試 |
| 預設輸出 | **stdout** | **檔案** | stdout（★ 有顏色） |
| **遞迴下載** | ✗ | **★★★ 有**（`-r`） | ✗ |
| **續傳** | `-C -` | **★★ `-c`**（更好用） | ✗ |
| **時間拆解** | **★★★★ `-w`** | ✗ | ✗ |
| JSON 處理 | ★ 要配 `jq` | ✗ | **★★ 內建** |
| 協定支援 | **★★★ 很多** | HTTP/FTP | HTTP |
| **幾乎都有裝** | **★★★ 是** | ★★ 是 | ✗ 要裝 |
| **除錯資訊** | **★★★★ `-v` 最詳細** | ★★ `-d` | ★ |

```bash
# ★★★ 下載大檔案 → wget 比較好
$ wget -c https://example.gov.tw/big.iso              # ★★ 續傳
$ wget -c --tries=5 --timeout=30 URL
$ wget -r -np -k -p https://docs.example.gov.tw/      # ★★ 遞迴抓整站
$ wget -q --spider https://app.example.gov.tw && echo "存活"   # ★★ 只檢查

# ★★★ API 測試與除錯 → curl
$ curl -sv https://api.example.gov.tw/health 2>&1 | grep -E '^[<>*]'

# ★★ httpie（★ 語法比較好記）
$ sudo apt install -y httpie
$ http GET https://api.example.gov.tw/users page==1 Accept:application/json
$ http POST https://api.example.gov.tw/users name=測試 email=t@example.tw
$ http --verify=no https://internal.example.gov.tw
$ http --print=HhBb GET https://app.example.gov.tw     # ★★ 顯示請求+回應
```

---

## 完整實戰範例：API 健康檢查腳本

```bash
#!/usr/bin/env bash
# ★★★ /usr/local/bin/api-check —— API 端點健康檢查
set -uo pipefail

BASE="${1:-https://app.example.gov.tw}"
TIMEOUT=15
FAIL=0

# ★★ 顏色（★ 非 tty 時停用）
if [ -t 1 ]; then G='\033[32m'; R='\033[31m'; Y='\033[33m'; N='\033[0m'
else G=''; R=''; Y=''; N=''; fi

echo "═══ API 健康檢查  $BASE  $(date '+%F %T') ═══"

# ═══ ★★★★ 通用檢查函式 ═══
chk() {
    local name="$1" path="$2" want="$3"; shift 3
    local out code ttfb
    out=$(curl -sko /dev/null --max-time "$TIMEOUT" \
          -w '%{http_code} %{time_starttransfer}' "$@" "$BASE$path" 2>/dev/null) || out="000 0"
    code=${out%% *}; ttfb=${out##* }
    printf '  %-38s ' "$name"
    if [ "$code" = "$want" ]; then
        printf "${G}✓${N} %s  (%.3fs)" "$code" "$ttfb"
        awk -v t="$ttfb" 'BEGIN{if(t>1) printf "  '"$Y"'★★ 慢'"$N"'"}'
        echo ""
    else
        printf "${R}✗ %s (預期 %s)${N}\n" "$code" "$want"
        FAIL=$((FAIL+1))
    fi
}

# ═══【1】基本連通與時間拆解 ═══
echo -e "\n【1】★★★ 時間拆解"
curl -sko /dev/null --max-time "$TIMEOUT" \
  -w '  DNS=%{time_namelookup}s  TCP=%{time_connect}s  TLS=%{time_appconnect}s
  ★★★ TTFB=%{time_starttransfer}s  總計=%{time_total}s  IP=%{remote_ip}\n' \
  "$BASE/" || { echo "  ★★★★ 完全連不上"; exit 1; }

# ═══ ★★★【2】TLS ═══
echo -e "\n【2】★★★ TLS 與憑證"
TLSINFO=$(curl -v --max-time "$TIMEOUT" "$BASE/" 2>&1 | \
          grep -E 'SSL connection using|expire date:|issuer:|verify')
echo "$TLSINFO" | sed 's/^\*/ /'
EXP=$(echo "$TLSINFO" | grep -oP 'expire date: \K.*' || true)
if [ -n "$EXP" ]; then
    DAYS=$(( ( $(date -d "$EXP" +%s) - $(date +%s) ) / 86400 ))
    printf '  剩餘天數: %s  ' "$DAYS"
    if [ "$DAYS" -lt 14 ]; then printf "${R}★★★★ 緊急！${N}\n"; FAIL=$((FAIL+1))
    elif [ "$DAYS" -lt 30 ]; then printf "${Y}★★★ 該續期了${N}\n"
    else printf "${G}✓${N}\n"; fi
fi

# ★★ 舊協定
for v in tlsv1.0 tlsv1.1; do
    if curl -sIk --"$v" --tls-max "${v#tlsv}" --max-time 5 "$BASE/" >/dev/null 2>&1; then
        printf "  ${R}★★★★ %s 還開著${N}\n" "$v"; FAIL=$((FAIL+1))
    fi
done

# ═══ ★★★【3】端點 ═══
echo -e "\n【3】★★★ 端點"
chk "首頁"                    "/"                     200
chk "★★ API 健康檢查"          "/api/health/live"      200
chk "★★ API readiness"        "/api/health/ready"     200
chk "★★ 未認證應回 401"        "/api/user"             401 -H 'Accept: application/json'
chk "★★★ .env 應擋住"          "/.env"                 404
chk "★★★ .git/config 應擋住"   "/.git/config"          404
chk "★★★★ PathInfo RCE 防護"   "/storage/x.jpg/y.php"  404
chk "★★ 不存在的頁面"          "/__nope__"             404

# ═══ ★★★【4】安全標頭 ═══
echo -e "\n【4】★★★ 安全標頭"
HDRS=$(curl -sI --max-time "$TIMEOUT" "$BASE/" 2>/dev/null)
for h in strict-transport-security x-frame-options x-content-type-options \
         referrer-policy content-security-policy; do
    v=$(echo "$HDRS" | grep -i "^$h:" | cut -d' ' -f2- | tr -d '\r')
    if [ -n "$v" ]; then printf "  ${G}✓${N} %-32s %s\n" "$h" "${v:0:45}"
    else printf "  ${Y}★★★ 缺少${N} %s\n" "$h"; fi
done

# ★★★ 不該出現的
echo "$HDRS" | grep -iE '^(x-powered-by|server: .*/[0-9])' | \
    sed "s/^/  ${R}★★★★ 洩漏版本: ${N}/" && FAIL=$((FAIL+1)) || true

# ═══ ★★【5】HTTP → HTTPS ═══
echo -e "\n【5】★★★ HTTP 重導向"
HTTP_URL="${BASE/https:/http:}"
RED=$(curl -sI --max-time 10 "$HTTP_URL" 2>/dev/null | tr -d '\r')
CODE=$(echo "$RED" | head -1 | awk '{print $2}')
LOC=$(echo "$RED" | grep -i '^location:' | cut -d' ' -f2-)
if [ "$CODE" = "301" ] && [[ "$LOC" == https://* ]]; then
    printf "  ${G}✓${N} 301 → %s\n" "$LOC"
elif [ "$CODE" = "302" ]; then
    printf "  ${Y}★★ 用 302（建議改 301）${N} → %s\n" "$LOC"
else
    printf "  ${R}★★★★ HTTP 沒有重導向到 HTTPS（code=%s）${N}\n" "$CODE"
    FAIL=$((FAIL+1))
fi

# ═══ ★★【6】壓縮 ═══
echo -e "\n【6】★★ 壓縮"
RAW=$(curl -s --max-time "$TIMEOUT" -o /dev/null -w '%{size_download}' "$BASE/")
GZ=$(curl -s --compressed --max-time "$TIMEOUT" -o /dev/null -w '%{size_download}' "$BASE/")
ENC=$(curl -sI --compressed --max-time "$TIMEOUT" "$BASE/" | \
      grep -i content-encoding | cut -d' ' -f2- | tr -d '\r')
if [ -n "$ENC" ]; then
    printf "  ${G}✓${N} %s  %s → %s bytes\n" "$ENC" "$RAW" "$GZ"
else
    printf "  ${Y}★★ 沒有啟用壓縮${N}（%s bytes）\n" "$RAW"
fi

# ═══ 總結 ═══
echo ""
if [ "$FAIL" -eq 0 ]; then
    printf "${G}★ 全部通過${N}\n"
else
    printf "${R}★★★★ %d 項失敗${N}\n" "$FAIL"
fi
exit "$FAIL"
```

```bash
$ sudo install -m755 api-check.sh /usr/local/bin/api-check
$ api-check https://app.example.gov.tw

# ★★ 加進監控
$ sudo tee /etc/cron.d/api-check >/dev/null <<'EOF'
*/15 * * * * root /usr/local/bin/api-check https://app.example.gov.tw >/var/log/api-check.log 2>&1 || logger -t api-check -p daemon.err "健康檢查失敗"
EOF
```

---

## 常見錯誤與排錯

| 錯誤 | 意義 | **★ 處置** |
| --- | --- | --- |
| **`(6) Could not resolve host`** ★★★ | DNS 解析失敗 | `dig`；`/etc/resolv.conf`；**`--resolve` 繞過** |
| **`(7) Failed to connect`** ★★★ | 連不上 | **服務沒起來／防火牆**；`ss -tlnp` |
| **`(7) Cannot assign requested address`** ★★★★ | **本機埠用盡** | TIME_WAIT；keepalive |
| **`(28) Operation timed out`** ★★★ | 逾時 | 加 `--max-time`；查伺服器端 |
| **`(35) SSL connect error`** ★★★ | TLS 交握失敗 | 協定/密碼套件不合；`--tlsv1.2` |
| **`(51) certificate subject name does not match`** ★★★ | **主機名對不上** | 檢查 SAN；`--resolve` |
| **`(56) Recv failure: Connection reset`** ★★★ | 對方 RST | 應用崩潰；WAF 阻擋 |
| **`(60) unable to get local issuer certificate`** ★★★★ | **缺中繼憑證** | 用 `fullchain.pem`；`--cacert` |
| **`(60) self-signed certificate`** ★★★ | 自簽 | **`--cacert`**（不要用 `-k`） |
| **`(52) Empty reply from server`** ★★★ | 沒有回應 | 應用崩潰；`error.log` |
| **`(92) HTTP/2 stream was not closed`** ★★ | HTTP/2 問題 | `--http1.1` 測試 |
| **`(18) transfer closed with N bytes remaining`** ★★ | 傳輸中斷 | Content-Length 不符；上游斷線 |

### 排查

```bash
# 【1】★★★★ 完整的 verbose
$ curl -v https://app.example.gov.tw 2>&1 | head -40
#   ★ * 開頭 = curl 的訊息
#   ★ > 開頭 = 送出的請求
#   ★ < 開頭 = 收到的回應

# 【2】★★★ 只看請求與回應
$ curl -v https://app.example.gov.tw 2>&1 | grep -E '^[<>]'

# 【3】★★ 完整的傳輸內容（含 body）
$ curl --trace-ascii /tmp/trace.txt https://app.example.gov.tw
$ head -60 /tmp/trace.txt

# 【4】★★★ 時間拆解定位
$ curl -sko /dev/null -w 'dns=%{time_namelookup} conn=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' URL

# 【5】★★★ 逐層測試
$ curl -sko /dev/null -w '%{http_code}\n' http://127.0.0.1/          # 本機
$ curl -sko /dev/null -w '%{http_code}\n' --resolve 'h:443:10.0.0.1' https://h/   # 內網
$ curl -sko /dev/null -w '%{http_code}\n' https://h/                 # 外網

# 【6】★★ 退化測試
$ curl -sI --http1.1 URL              # 是不是 HTTP/2 的問題
$ curl -sI --tlsv1.2 --tls-max 1.2 URL # 是不是 TLS 1.3 的問題
$ curl -sI -4 URL                      # 是不是 IPv6 的問題
$ curl -sI --noproxy '*' URL           # 是不是 proxy 的問題

# 【7】★★ 環境變數影響
$ env | grep -i proxy
http_proxy=http://proxy:3128           # ★★★ 這會影響 curl！
$ curl --noproxy '*' URL
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★
> ```
> ① ★★★★ 不要在指令列放密碼或 token
>      $ curl -u user:pass URL              ← ★★★★ ps 看得到
>      $ curl -H "Authorization: Bearer xxx" ← ★★★★ 同樣
>      → ★★★ 用 --netrc-file、環境變數、或互動輸入
>
> ② ★★★★ -k / --insecure 等於關掉 TLS 保護
>      → ★★★ 會被中間人攻擊
>      → ★★ 只在【明知是測試環境】的臨時排查用
>      → ★★★★ 絕對不要寫進腳本或 cron
>
> ③ ★★★ curl 會跟隨重導向到任意位置（-L）
>      → ★★ 可能被導到內網（SSRF）
>      → ★★★ 腳本中限制 --max-redirs 與 --proto
>
> ④ ★★ 存下來的 cookie 檔含 session token
>      → ★★★ chmod 600；用完刪除
>
> ⑤ ★★ curl 的 URL 會進 shell history
>      → ★★★ 含 token 的指令前面加空格（HISTCONTROL=ignorespace）
> ```

```bash
# ★★★ 安全的認證方式
$ chmod 600 ~/.netrc
$ curl --netrc-file ~/.netrc https://api.example.gov.tw/data

$ chmod 600 ~/.api-token
$ curl -H "Authorization: Bearer $(cat ~/.api-token)" https://api.example.gov.tw/data
#   ★★ 這樣 token 不會出現在 ps（★ 但仍會在 /proc/PID/environ）

# ★★★ 最安全：從 stdin
$ curl -H @- https://api.example.gov.tw/data <<< "Authorization: Bearer $TOKEN"

# ★★★ 限制 curl 的行為（腳本中）
$ curl --proto '=https' --proto-redir '=https' \
       --max-redirs 3 --max-time 30 \
       --retry 2 --retry-delay 1 \
       -sS "$URL"
#   ★★★ --proto '=https'       只允許 https
#   ★★★★ --proto-redir '=https' 重導向也只能到 https（★ 防 SSRF）

# ★★★ 防止 SSRF（★ 應用程式中呼叫外部 URL 時）
$ curl --proto '=https' --proto-redir '=https' \
       --max-redirs 0 \
       --noproxy '*' \
       --connect-timeout 5 --max-time 15 \
       "$USER_PROVIDED_URL"
#   ★★★★ 更好的做法：先解析 URL，檢查 IP 不在內網範圍

# ★★ history 保護
$ export HISTCONTROL=ignorespace
$  curl -H "Authorization: Bearer secret" URL     # ★★ 前面有空格 → 不進 history

# ★★ cookie 檔的保護
$ COOKIE=$(mktemp) && chmod 600 "$COOKIE"
$ trap 'rm -f "$COOKIE"' EXIT
$ curl -c "$COOKIE" -b "$COOKIE" ...

# ★★★ 檢查腳本中有沒有 -k
$ grep -rn 'curl.*\(-k\|--insecure\)' /usr/local/bin/ /etc/cron.d/ 2>/dev/null
#   ★★★★ 有的話要修正
```

---

## 速查表

### ★★★★ 時間拆解（最重要）

```bash
curl -sko /dev/null -w 'dns=%{time_namelookup} conn=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total} code=%{http_code}\n' URL

DNS > 0.1s        → ★★ DNS 伺服器
conn-dns > 0.1s   → ★★ 網路延遲 / 防火牆
tls-conn > 0.3s   → ★★ 憑證鏈 / OCSP
★★★★ TTFB 慢      → 【伺服器端處理】← 往 nginx/PHP/DB 查
total-ttfb 大     → ★★ 內容太大 / 頻寬
```

### 常用

```bash
curl -sI URL                      # ★★★ 只看標頭
curl -sIL URL                     # ★★ 跟隨重導向
curl -v URL 2>&1 | grep -E '^[<>*]'   # ★★★ 完整交握
curl -s URL | jq .                # ★★ JSON
curl --max-time 15 URL            # ★★★ 一定要設逾時
```

### ★★★★ `--resolve`

```bash
curl -sI --resolve app.example.tw:443:10.10.20.31 https://app.example.tw
# ★★★★ 比 -H 'Host:' 好：SNI 和憑證驗證都正確
# ★★★ 用途：DNS 沒改、測特定後端、測 CDN 源站
```

### TLS

```bash
curl -v URL 2>&1 | grep -E 'SSL connection|expire date|verify'
curl --cacert ca.crt URL              # ★★★ 自簽（不要用 -k）
curl --cert c.crt --key c.key URL     # ★★ mTLS
curl -sI --tlsv1.0 --tls-max 1.0 URL  # ★★★ 測舊協定是否還開
# ★★★★ (60) unable to get local issuer = 缺中繼憑證
```

### API

```bash
curl -X POST -H 'Content-Type: application/json' -d '{"a":1}' URL
curl -F 'file=@a.pdf' -H 'Authorization: Bearer T' URL
curl -c ck.txt -b ck.txt URL          # ★★ session
curl --netrc-file ~/.netrc URL        # ★★★ 安全的認證
```

### ★★★ 常見錯誤

```
(6)  DNS 解析失敗          (7)  連不上
(28) 逾時                  (35) TLS 交握失敗
(51) 主機名對不上          (52) 空回應（應用崩潰）
★★★★ (60) 缺中繼憑證 / 自簽   (56) 被 RST
```

### ★★★ 安全

```bash
--proto '=https' --proto-redir '=https' --max-redirs 3   # ★★★★ 防 SSRF
--netrc-file ~/.netrc                                    # ★★★ 不用指令列放密碼
export HISTCONTROL=ignorespace                           # ★★ 前面加空格
★★★★ 絕對不要把 -k 寫進腳本或 cron
```

---

## 練習題

> [!question]- 練習 1：時間拆解 ★★★★
> 1. **建立 `~/.curl-format` 並對三個網站測試**
> 2. **哪一段最長？**
> 3. **從本機、內網、外網三個位置測同一個服務**
> 4. **差異在哪一段？說明什麼？**
> 5. 連測 20 次算 P50 / P90
> 6. **P50 快但 P90 慢代表什麼？**

> [!question]- 練習 2：`--resolve` ★★★
> 1. **用 `--resolve` 測一個網域指到不同的 IP**
> 2. **對照 `-H 'Host:'` 的做法** → 憑證驗證有差嗎？
> 3. **用 `-v` 看兩者的 SNI 有什麼不同**
> 4. 對多台後端逐一測健康檢查端點
> 5. **找出哪一台有問題**
> 6. **為什麼 `--resolve` 是正確的做法？**

> [!question]- 練習 3：TLS ★★★★
> 1. **`curl -v` 看你的網站的 TLS 版本與密碼套件**
> 2. **憑證還有幾天到期？**（寫成一行指令）
> 3. **測 TLS 1.0 / 1.1 是否還開著**
> 4. 建一個自簽憑證的服務 → `curl` 報什麼錯？
> 5. **用 `--cacert` 正確驗證**（不要用 `-k`）
> 6. **把 CA 加進系統信任存放區再測**

> [!question]- 練習 4：API 測試 ★★★
> 1. **用 curl 完成一次 Sanctum SPA 登入流程**
> 2. **不帶 CSRF token 會怎樣？**（狀態碼）
> 3. 用 session 存取受保護的端點
> 4. **上傳一個檔案（`-F`）**
> 5. **把 token 寫進 `~/.netrc` 並用 `--netrc-file`**
> 6. **`ps aux | grep curl` 看得到 token 嗎？**（兩種寫法各測一次）

> [!question]- 練習 5：安全 ★★★★
> 1. **`curl -u user:password URL` 執行時，另一個視窗跑 `ps aux | grep curl`**
> 2. **看得到密碼嗎？**
> 3. 改用 `--netrc-file` → 呢？
> 4. **寫一個會跟隨重導向到內網的測試**（SSRF 模擬）
> 5. **加上 `--proto-redir '=https'` 和 `--max-redirs 0`** → 擋住了嗎？
> 6. **`grep -rn 'curl.*-k' /etc/cron.d/ /usr/local/bin/`** → 有嗎？

---

## 小測驗

Q1. **`-w` 的時間拆解中，TTFB 慢代表什麼**？往哪查？

Q2. **`time_connect` 減去 `time_namelookup` 是什麼**？

Q3. **`--resolve` 和 `-H 'Host: xxx'` 的差別**？為什麼前者比較正確？

Q4. **`curl: (60) unable to get local issuer certificate` 最常見的原因**？怎麼修？

Q5. **為什麼不該把 `-k` 寫進腳本**？正確做法？

Q6. **`curl -u user:pass URL` 有什麼資安問題**？三個替代方案？

Q7. **`--proto-redir '=https'` 防的是什麼攻擊**？

Q8. **curl 和 wget 各適合什麼場景**？

Q9. **HTTP → HTTPS 的重導向應該用 301 還是 302**？為什麼？

Q10. **從本機、內網、外網三個位置測同一個服務，TTFB 分別是 0.08s / 0.09s / 2.1s，說明什麼**？

> [!question]- 測驗答案
> **Q1.** **★★★★ TTFB（Time To First Byte）慢代表「伺服器端的處理慢」**。
> TTFB 涵蓋的是「連線與 TLS 都建立完成之後，到收到第一個位元組」——
> DNS、TCP、TLS 都已經排除了，**剩下的就是伺服器在思考**。
> **往下查的順序**：
> ①**nginx** —— `error.log` 有沒有 `upstream timed out`；
> 比對 access log 的 **`$request_time` 與 `$upstream_response_time`**
> （差值就是 nginx 自己花的時間）；
> ②**PHP-FPM** —— `/status?full` 看 `listen queue` 和 `max children reached`，
> `php-fpm-slow.log` 看卡在哪一行；
> ③**資料庫** —— 慢查詢日誌、`EXPLAIN`、缺索引；
> ④**系統資源** —— `first60` + USE method。
> 反之如果是 **`time_total - TTFB` 很大**，那是傳輸階段慢（內容太大或頻寬不足）。
>
> **Q2.** **★★★ 那是真正的「TCP 三次交握時間」，約等於一個 RTT**。
> `time_namelookup` 是「DNS 解析完成」的時間點，
> `time_connect` 是「TCP 連線建立完成」的時間點，
> **兩者都是從 curl 開始算起的累計值**，
> 所以要相減才是那一段真正花的時間。
> **同樣的道理**：
> `time_appconnect - time_connect` = **TLS 交握時間**；
> `time_starttransfer - time_pretransfer` = **伺服器處理時間**；
> `time_total - time_starttransfer` = **內容傳輸時間**。
> **這是判讀 `-w` 輸出最容易犯的錯** ——
> 看到 `time_appconnect: 0.089` 就以為 TLS 花了 89ms，
> 其實扣掉前面的 DNS 和 TCP 之後可能只有 40ms。
>
> **Q3.** **`--resolve 主機名:埠:IP`** 是**在 DNS 層面覆寫解析結果** ——
> curl 內部把該網域解析成指定的 IP，
> 但**SNI、Host 標頭、憑證驗證的主機名全部維持原本的網域**。
> **`-H 'Host: app.example.tw' https://10.10.20.31`** 則是
> **連到 IP，只改 Host 標頭** ——
> **TLS 的 SNI 送出去的是 IP（或空的）**，
> 伺服器可能回錯的 server 區塊，
> 而且**憑證的主機名驗證會失敗**（憑證是簽給網域，不是 IP），
> 所以通常還得加 `-k`，等於同時關掉了 TLS 驗證。
> **★★★ 所以一律用 `--resolve`** ——
> 它讓你測特定後端的同時，**SNI 路由和憑證驗證都保持正確**。
> 用途：DNS 還沒改就先測新伺服器、逐一測負載平衡後的節點、測 CDN 源站。
>
> **Q4.** **★★★★ 伺服器沒有送出中繼憑證（intermediate certificate）**。
> 憑證鏈是「伺服器憑證 → 中繼 CA → 根 CA」，
> 客戶端的信任存放區只有**根 CA**，
> 伺服器必須主動送出**中繼憑證**才能讓客戶端串起這條鏈。
> **確認方式**：
> ```bash
> openssl s_client -connect host:443 -servername host </dev/null 2>/dev/null | \
>   grep -c 'BEGIN CERTIFICATE'
> # 1 → ★★★★ 只送了自己的憑證，缺中繼
> # 2 → ★★★ 正常
> ```
> **修正**：nginx 的 `ssl_certificate` 要指向 **`fullchain.pem`**
> （伺服器憑證 + 中繼憑證串接），**不是** `cert.pem`。
> **另一個常見原因是自簽憑證** —— 那要用 `--cacert` 指定你的根 CA，
> 或把根 CA 加進系統信任存放區（`/usr/local/share/ca-certificates/` + `update-ca-certificates`）。
> **瀏覽器常常看起來正常是因為它會快取中繼憑證**，別被誤導。
>
> **Q5.** 因為 **`-k` / `--insecure` 等於完全關閉 TLS 的驗證** ——
> 憑證是誰簽的、有沒有過期、主機名對不對，**全部不檢查**。
> 這讓連線**完全暴露在中間人攻擊之下**：
> 攻擊者只要能攔截流量（ARP spoofing、DNS 汙染、惡意的 proxy），
> 就能用自己的憑證解密並竄改內容，而 curl 不會有任何抱怨。
> **寫進腳本或 cron 特別危險** ——
> 那是**長期、無人看管、可能帶著認證憑據**的請求。
> **正確做法**：
> ```bash
> curl --cacert /path/to/ca.crt https://internal.example.tw   # ★★★ 指定 CA
> # 或一勞永逸：
> sudo cp ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates
> ```
> `-k` 只能用在「明知是測試環境、當下的臨時排查」。
> 定期稽核：`grep -rn 'curl.*\(-k\|--insecure\)' /usr/local/bin/ /etc/cron.d/`。
>
> **Q6.** **★★★★ 完整的指令列（含密碼）是所有使用者都讀得到的** ——
> `/proc/<PID>/cmdline` 預設權限 `r--r--r--`，
> 任何人跑 `ps aux` 或 htop 都看得到；
> 而且密碼還會進入 **shell history**、**auditd 日誌**、**監控系統的程序快照**。
> **三個替代方案**（安全性由高到低）：
> ①**`--netrc-file ~/.netrc`**（`chmod 600`）——
> curl 從檔案讀認證，指令列完全不出現；
> ②**從檔案讀進標頭**：
> `curl -H "Authorization: Bearer $(cat ~/.api-token)"` ——
> 展開後仍在 cmdline，但至少不會進 history 明文；
> 更好的是 `curl -H @- URL <<< "Authorization: Bearer $TOKEN"`（從 stdin 讀）；
> ③**`curl -u 'user' URL`**（只給帳號）——
> curl 會**互動式提示輸入密碼**，最安全但不能自動化。
> 另外 `export HISTCONTROL=ignorespace` 後，
> 指令**前面加一個空格**就不會進 history。
>
> **Q7.** **★★★ SSRF（Server-Side Request Forgery，伺服器端請求偽造）**。
> 攻擊情境：應用程式接受使用者提供的 URL 並用 curl 去抓
> （例如「輸入圖片網址」「webhook 回呼」）——
> 攻擊者提供一個外部 URL，該 URL **回應 302 重導向到內網位址**，
> 例如 `http://169.254.169.254/latest/meta-data/`（雲端的 metadata 服務，
> 可以拿到 IAM 憑證）或 `http://127.0.0.1:6379/`（內網的 Redis）。
> **`--proto-redir '=https'` 限制「重導向只能到 https」**，
> 搭配 **`--proto '=https'`**（初始請求也只能 https）
> 和 **`--max-redirs 0`**（完全不跟隨重導向），
> 可以擋掉大部分的重導向型 SSRF。
> **但這只是縱深防禦的一層** ——
> **更根本的做法是先解析 URL，檢查目標 IP 不在內網範圍**
> （127.0.0.0/8、10.0.0.0/8、172.16.0.0/12、192.168.0.0/16、169.254.0.0/16）。
>
> **Q8.** **curl 適合：API 測試與 HTTP 除錯**。
> 它的**`-w` 時間拆解是獨一無二的**，
> `-v` 的除錯資訊最詳細（完整的 TLS 交握過程），
> 支援的協定最多，預設輸出到 stdout 方便接 `jq`，
> 而且**幾乎所有系統都預裝**。
> **wget 適合：下載檔案**。
> **`-c` 續傳比 curl 的 `-C -` 好用**，
> **`-r` 遞迴下載整個網站**（curl 完全沒有這個功能），
> `--tries` 重試機制成熟，
> `-q --spider` 適合單純的存活檢查，
> 預設輸出到檔案符合下載的使用習慣。
> **簡單記法**：**「要看發生了什麼」用 curl，「要把東西抓下來」用 wget**。
> httpie 語法友善、內建 JSON 處理，適合手動測 API，但要額外安裝。
>
> **Q9.** **★★★ 應該用 301（Moved Permanently）**。
> **301 是永久重導向** —— 瀏覽器會**快取這個結果**，
> 之後使用者輸入 `http://` 時，**瀏覽器直接在本機轉成 https，不會發出明文請求**。
> **302 是暫時重導向** —— 瀏覽器**不快取**，
> 每一次都要**先送出一個明文的 HTTP 請求**才會被導向，
> 那次請求中的 Cookie、URL 路徑、查詢參數**全部是明文**，
> 可能被中間人攔截（尤其在公共 Wi-Fi）。
> **更進一步應該加上 HSTS**：
> ```nginx
> add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
> ```
> HSTS 讓瀏覽器**在指定期間內完全拒絕用 http 連線**，
> 連第一次的明文請求都不會發生（配合 HSTS preload 更徹底）。
> **驗證**：`curl -sI http://app.example.tw | grep -iE '^(HTTP|location)'`。
>
> **Q10.** **★★★★ 伺服器本身沒問題，問題出在「外網到伺服器」這段路徑上**。
> 本機（0.08s）和內網（0.09s）幾乎一樣快，
> 證明**應用程式、PHP、資料庫都是健康的** ——
> 如果是伺服器端的處理慢，三個位置都會慢。
> **外網慢了 2 秒，往這幾個方向查**：
> ①**中間的網路設備** —— 防火牆、WAF、負載平衡器、IPS 的深度檢測；
> ②**CDN 或反向代理** —— 回源慢、快取未命中、節點問題；
> ③**網路路徑** —— 用 `mtr` 看哪一跳延遲高、有沒有丟包；
> ④**外部 DNS** —— 用時間拆解看是不是 `time_namelookup` 佔掉的
> （這題的 TTFB 已經排除了 DNS，所以不是）；
> ⑤**頻寬飽和** —— `sar -n DEV` 看對外介面是否接近上限。
> **這個三點測試法是分層定位最有效的第一步** ——
> 它一次就把「伺服器問題」和「網路問題」切開了。

---

## 延伸閱讀

- [[04-效能瓶頸排查方法論]] — 時間拆解在分層定位中的位置
- [[06-dig-與DNS排查]] — DNS 解析慢的排查
- [[01-tcpdump-基礎抓包]] — curl 看不出問題時抓包
- [[13-憑證常見問題排查]] — TLS 錯誤的完整對照
- [[09-前後端分離常見問題排查]] — API 與 CORS 問題
- [[02-Laravel-API後端部署]] — 健康檢查端點的設計
