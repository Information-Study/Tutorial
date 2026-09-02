---
title: "CN 與 SAN 設定與瀏覽器相容性"
desc: "為什麼現代瀏覽器只看 SAN，以及各平台的網域比對規則"
aliases: [SAN, CN, subjectAltName, ERR_CERT_COMMON_NAME_INVALID, 萬用憑證]
tags: [群組/資訊安全, 主題/PKI, 主題/憑證]
category: 憑證與PKI
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[090-01-02-guide-PKI-CSR產生與req設定檔]]"]
updated: 2026-09-03
---

# CN 與 SAN 設定與瀏覽器相容性

> [!abstract] 這篇你會學到
> - 為什麼 **CN 已被淘汰、SAN 才是唯一有效的**
> - **萬用憑證（`*.example.gov.tw`）的比對規則與限制**
> - **IP 位址憑證**的特殊要求
> - 各平台（瀏覽器、Java、Node、Python、行動裝置）的**比對差異**
> - 診斷 **`ERR_CERT_COMMON_NAME_INVALID`** 等常見錯誤
> - 為**內部系統**設計正確的 SAN 規劃

## 前置知識

- [[090-01-02-guide-PKI-CSR產生與req設定檔]] — 在 CSR 中設定 SAN
- [[090-01-01-guide-PKI-PKI與憑證基礎]] — X.509 欄位

---

## CN 的淘汰史

```
1999 年 RFC 2818（HTTP over TLS）：
  「若有 SAN，就【只用】 SAN；
    只有在【沒有 SAN】時才回頭用 CN（★ 且已標記為 deprecated）」

2000-2016：瀏覽器仍接受只有 CN 的憑證（相容舊系統）

2017 年 Chrome 58：★★ 【完全停止】檢查 CN
2018 年 Firefox 48+：同樣停止
2019 年 Safari：跟進
2020 年 RFC 8446（TLS 1.3）時代：SAN 成為唯一標準

★★★ 現在：沒有 SAN 的憑證 = 沒有用
```

> [!danger] 只有 CN 沒有 SAN 的憑證會被直接拒絕
> ```
> Chrome：
>   NET::ERR_CERT_COMMON_NAME_INVALID
>   「這個伺服器無法證明其為 app.example.gov.tw；
>     其安全性憑證沒有指定主體別名。」
>
> Firefox：
>   SSL_ERROR_BAD_CERT_DOMAIN
>
> curl：
>   curl: (60) SSL: certificate subject name 'app.example.gov.tw'
>   does not match target host name
> ```
>
> **★ 而且無法點「繼續前往」繞過**（在有 HSTS 的情況下）。

```bash
# ★★ 快速檢查一張憑證有沒有 SAN
$ openssl x509 -in cert.pem -noout -ext subjectAltName
X509v3 Subject Alternative Name:
    DNS:app.example.gov.tw, DNS:www.app.example.gov.tw

# ★ 沒有 SAN 時
$ openssl x509 -in old-cert.pem -noout -ext subjectAltName
No extensions in certificate                      # ★★ 這張憑證沒用了

# ★ 從線上檢查
$ echo | openssl s_client -connect app.example.gov.tw:443 \
    -servername app.example.gov.tw 2>/dev/null | \
    openssl x509 -noout -ext subjectAltName
```

---

## SAN 的正確寫法

```ini
# ═══ req.txt ═══
[ req ]
prompt              = no
distinguished_name  = req_distinguished_name
req_extensions      = req_ext            # ★★★ 沒有這行 SAN 不會被寫進 CSR

[ req_distinguished_name ]
C  = TW
ST = Taiwan
L  = Taipei
O  = Example Government Agency
OU = Information Department
CN = app.example.gov.tw                  # ★ 仍然要填（習慣、相容性）

[ req_ext ]
subjectAltName = @alt_names

[ alt_names ]
DNS.1 = app.example.gov.tw               # ★★★ CN 必須【也】列在這裡
DNS.2 = www.app.example.gov.tw
DNS.3 = api.example.gov.tw
DNS.4 = admin.example.gov.tw
```

> [!danger] 最常見的錯誤：CN 沒有列在 SAN 中 ★★★
> ```ini
> CN = app.example.gov.tw
>
> [ alt_names ]
> DNS.1 = www.app.example.gov.tw          # ★★ 只有 www，沒有 app！
> ```
>
> **結果**：
> ```
> https://www.app.example.gov.tw  → ✓ 正常
> https://app.example.gov.tw      → ✗✗ ERR_CERT_COMMON_NAME_INVALID
> ```
>
> **因為瀏覽器完全不看 CN。**
>
> ```bash
> # ★ 驗證腳本
> $ CN=$(openssl x509 -in cert.pem -noout -subject | grep -oP 'CN\s*=\s*\K[^,/]+' | xargs)
> $ SAN=$(openssl x509 -in cert.pem -noout -ext subjectAltName 2>/dev/null | tail -1)
> $ echo "$SAN" | grep -q "DNS:$CN" && echo "✓ CN 在 SAN 中" || echo "✗✗ CN 不在 SAN 中"
> ```

### 各種 SAN 類型

```ini
[ alt_names ]
# ═══ DNS 名稱（最常用）═══
DNS.1 = app.example.gov.tw
DNS.2 = *.example.gov.tw                 # 萬用（見下方規則）

# ═══ IP 位址（★ 公開 CA 通常不簽發）═══
IP.1  = 10.0.5.20
IP.2  = 192.168.1.100
IP.3  = 2001:db8::1                      # IPv6

# ═══ Email（S/MIME 憑證用）═══
email.1 = admin@example.gov.tw

# ═══ URI（少用）═══
URI.1 = https://example.gov.tw/

# ═══ ★ UPN（Windows 智慧卡登入用）═══
otherName.1 = 1.3.6.1.4.1.311.20.2.3;UTF8:user@example.gov.tw
```

> [!warning] IP 位址必須用 `IP.n` 而不是 `DNS.n`
> ```ini
> # ❌ 錯誤
> DNS.1 = 10.0.5.20
> #   → 憑證中會是 DNS:10.0.5.20
> #   → ★ 用 https://10.0.5.20/ 存取時【不會比對成功】
> #     （瀏覽器知道你輸入的是 IP，會去找 iPAddress 類型的 SAN）
>
> # ✅ 正確
> IP.1 = 10.0.5.20
> #   → 憑證中會是 IP Address:10.0.5.20
> ```
>
> ```bash
> # ★ 檢查
> $ openssl x509 -in cert.pem -noout -ext subjectAltName
> X509v3 Subject Alternative Name:
>     DNS:internal.example.local, IP Address:10.0.5.20     # ★ 兩種類型
> ```

---

## 萬用憑證的比對規則 ★★

```
*.example.gov.tw 涵蓋：
  ✅ www.example.gov.tw
  ✅ api.example.gov.tw
  ✅ anything.example.gov.tw

  ❌ example.gov.tw              ★★ 【不含根網域本身！】
  ❌ a.b.example.gov.tw          ★★ 【只涵蓋一層】
  ❌ *.a.example.gov.tw
```

> [!danger] 萬用憑證不涵蓋根網域 ★★★
> ```
> 憑證的 SAN 只有：*.example.gov.tw
>
>   https://www.example.gov.tw  → ✓ 正常
>   https://example.gov.tw      → ✗✗ 憑證錯誤！
>
> ★★ 這是極常見的設定失誤
> ```
>
> **正確做法：兩個都列**
> ```ini
> [ alt_names ]
> DNS.1 = example.gov.tw                  # ★★ 根網域
> DNS.2 = *.example.gov.tw                # ★★ 一層子網域
> ```

> [!warning] 萬用只涵蓋「一層」
> ```
> *.example.gov.tw
>   ✅ api.example.gov.tw
>   ❌ v1.api.example.gov.tw              ★ 兩層，不涵蓋
>
> 要涵蓋兩層必須明確列出：
>   DNS.1 = example.gov.tw
>   DNS.2 = *.example.gov.tw
>   DNS.3 = *.api.example.gov.tw          ★ 針對 api 這一層
>   DNS.4 = *.dev.example.gov.tw
> ```

```
其他規則：

  ❌ *.gov.tw              CA 不會簽發（公共後綴，Public Suffix List）
  ❌ *.tw                  同上
  ❌ www.*.example.gov.tw  萬用字元必須在【最左邊】
  ❌ w*.example.gov.tw     部分萬用（RFC 允許但瀏覽器多不支援）
  ❌ *                     不可能
```

```bash
# ★ 驗證萬用憑證的涵蓋範圍
#!/usr/bin/env bash
CERT="${1:?用法: $0 <憑證檔> [測試網域...]}"
shift
SAN=$(openssl x509 -in "$CERT" -noout -ext subjectAltName 2>/dev/null | tail -1)
echo "SAN: $SAN"
echo

for host in "$@"; do
    MATCHED=""
    # 逐一比對每個 SAN 項目
    echo "$SAN" | tr ',' '\n' | grep -oP 'DNS:\K\S+' | while read -r pattern; do
        if [ "$pattern" = "$host" ]; then
            echo "  ✓ $host  （精確比對 $pattern）"; exit 0
        elif [[ "$pattern" == \*.* ]]; then
            SUFFIX="${pattern#\*}"                        # .example.gov.tw
            PREFIX="${host%$SUFFIX}"                      # 去掉後綴
            # ★ 必須是「一層」且後綴相符
            if [ "$PREFIX" != "$host" ] && [ -n "$PREFIX" ] && [[ "$PREFIX" != *.* ]]; then
                echo "  ✓ $host  （萬用比對 $pattern）"; exit 0
            fi
        fi
    done | head -1 | grep -q '✓' || echo "  ✗ $host  【沒有相符的 SAN】"
done
```

```bash
$ ./check-wildcard.sh cert.pem example.gov.tw www.example.gov.tw v1.api.example.gov.tw
SAN: DNS:example.gov.tw, DNS:*.example.gov.tw

  ✓ example.gov.tw  （精確比對 example.gov.tw）
  ✓ www.example.gov.tw  （萬用比對 *.example.gov.tw）
  ✗ v1.api.example.gov.tw  【沒有相符的 SAN】
```

> [!tip] 萬用憑證 vs 多網域憑證（SAN 憑證）
> | | **萬用憑證** | **多網域憑證** |
> | --- | --- | --- |
> | SAN | `*.example.gov.tw` | 明確列出每一個 |
> | 新增子網域 | **✅ 不用重簽** | ❌ 要重新簽發 |
> | 涵蓋範圍 | 一層子網域 | 精確控制 |
> | **私鑰洩漏的影響** | **★★ 所有子網域** | 只有列出的那些 |
> | **CT 日誌洩漏** | **★ 只曝光一個萬用名稱** | 每個子網域都曝光 |
> | 申請方式 | **必須 DNS-01** | HTTP-01 或 DNS-01 |
> | 費用（商業 CA） | 較高 | 依網域數 |
>
> **建議**：
> ```
> ① 大量的低風險子網域（測試、文件、部落格）→ 萬用憑證
> ② 高價值服務（金流、後台、API）→ ★ 獨立的憑證
> ③ 內部系統（不想曝光主機名）→ 萬用憑證 或 內部 CA
> ```

---

## 各平台的比對差異 ★

| 平台 | 只看 SAN | 支援萬用 | IP 憑證 | 特殊行為 |
| --- | --- | --- | --- | --- |
| **Chrome / Edge** | ✅ | ✅ | ✅ | **★ 要求 CT（公開 CA）** |
| **Firefox** | ✅ | ✅ | ✅ | **★ 自己的信任清單** |
| **Safari / iOS** | ✅ | ✅ | ✅ | **★ 帶頭限制憑證效期（上限分階段縮短中）** |
| **Android** | ✅ | ✅ | ✅ | ★ 使用者安裝的 CA 有限制（見下方） |
| **curl / wget** | ✅ | ✅ | ✅ | — |
| **Java** | ✅ | ✅ | ✅ | **★★ 自己的 `cacerts`** |
| **Node.js** | ✅ | ✅ | ✅ | **★ 內建清單；`NODE_EXTRA_CA_CERTS`** |
| **Python requests** | ✅ | ✅ | ✅ | **★ certifi 的清單** |
| **Go** | ✅ | ✅ | ✅ | 用系統清單 |
| **.NET** | ✅ | ✅ | ✅ | Windows 憑證存放區 |
| **OpenSSL CLI** | ⚠ | ✅ | ✅ | **★ 預設不驗證主機名（見下方）** |

> [!danger] `openssl s_client` 預設「不驗證主機名」
> ```bash
> # ❌ 這個指令【不會】檢查憑證的 SAN 是否符合
> $ openssl s_client -connect example.gov.tw:443
> # → 即使憑證的 SAN 完全不符也不會報錯！
>
> # ✅ 要加 -verify_hostname
> $ openssl s_client -connect example.gov.tw:443 \
>     -servername example.gov.tw \
>     -verify_hostname example.gov.tw
> ...
> Verification: OK                    # ★ 或 Verification error: ...
> ```
>
> **這是很多人誤判「憑證沒問題」的原因** ——
> `openssl s_client` 說 OK 不代表瀏覽器會接受。
>
> **更可靠的測試**：
> ```bash
> $ curl -sI https://example.gov.tw/ | head -1      # ★ curl 會完整驗證
> ```

### 公開信任憑證的效期上限（分階段縮短中）★★

> [!warning] 不要把天數記死
> 憑證效期上限【正在分階段縮短】，方向只會往更短走。
> **實際上限以 CA/Browser Forum 現行 Baseline Requirements
> 與各 CA、各瀏覽器的公告為準**（本文撰寫日：2026-09）。

```
2020 年 9 月起，Apple 帶頭限制公開信任憑證的有效期
  → Chrome 與 Firefox 隨後跟進
  → ★ 當時的上限是【約一年】
  → 超過上限的憑證【直接被拒絕】（不是警告）

★★ 但一年不是終點：CA/Browser Forum 已決議【分階段再縮短】
   → 具體天數與生效日會隨階段改變，【以官方公告為準】
   → 【不要把固定天數寫進 SOP 與檢查腳本的硬編碼】

★ 影響：
  · 以前買 2-3 年的憑證早就不可行
  · ★★★ 連「一年人工換一次」也已經擐不住
    → 【自動化續期（ACME）從「方便」變成「必要能力」】
      見 [[090-01-12-guide-PKI-憑證生命週期管理]]
```

```bash
# ★ 檢查憑證的有效期長度
$ openssl x509 -in cert.pem -noout -dates
notBefore=Aug 28 00:00:00 2026 GMT
notAfter=Nov 26 23:59:59 2026 GMT

$ START=$(date -d "$(openssl x509 -in cert.pem -noout -startdate | cut -d= -f2)" +%s)
$ END=$(date -d "$(openssl x509 -in cert.pem -noout -enddate | cut -d= -f2)" +%s)
$ echo "有效期：$(( (END - START) / 86400 )) 天"
有效期：90 天
# ★ 超過現行效期上限的話 Safari/Chrome/Firefox 會拒絕（上限持續縮短中）
```

### Android 的使用者 CA 限制

```
Android 7（API 24）起：
  ★★ App 【預設不信任】使用者安裝的 CA
    → 只信任系統的 CA
      → 即使使用者手動安裝了你的內部根憑證
        → ★ App 仍然拒絕連線

  除非 App 明確在 network_security_config.xml 中宣告：
```

```xml
<!-- res/xml/network_security_config.xml -->
<network-security-config>
    <base-config cleartextTrafficPermitted="false">
        <trust-anchors>
            <certificates src="system" />
            <certificates src="user" />      <!-- ★ 明確信任使用者安裝的 CA -->
        </trust-anchors>
    </base-config>
</network-security-config>
```

> [!warning] 這對「內部 CA」的影響很大
> ```
> 情境：機關的行動 App 要連內部系統（用內部 CA 的憑證）
>
>   ① 使用者安裝了內部根憑證 → 【瀏覽器】可以連 ✓
>   ② 但機關自己開發的 App → ★★ 【仍然拒絕】
>
> 解法：
>   ① App 加上 network_security_config.xml（★ 要改 App）
>   ② ★ 把根憑證【打包進 App】（憑證釘選 certificate pinning）
>   ③ ★★ 內部系統改用【公開 CA】的憑證（最省事）
>      → 用 DNS-01 為內部主機申請（見 03 篇）
> ```

### Java 的 cacerts

```bash
# ★ Java 有自己的信任清單
$ keytool -list -cacerts | head -5
$ keytool -list -keystore "$JAVA_HOME/lib/security/cacerts" -storepass changeit | grep -c 'trustedCertEntry'
147

# ★ 匯入內部根憑證
$ sudo keytool -importcert -trustcacerts \
    -alias example-gov-root-ca \
    -file /etc/ssl/certs/example-root-ca.crt \
    -cacerts -storepass changeit -noprompt

# ★ 驗證
$ keytool -list -cacerts -storepass changeit | grep -i example
example-gov-root-ca, Aug 28, 2026, trustedCertEntry,

# ★★ 每次升級 JDK 都要重做（cacerts 會被覆蓋）
```

### Node.js / Python

```bash
# ═══ Node.js ═══
$ export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/example-root-ca.crt
$ node -e "require('https').get('https://internal.example.gov.tw', r => console.log(r.statusCode))"

# ★ systemd service 中
Environment="NODE_EXTRA_CA_CERTS=/etc/ssl/certs/example-root-ca.crt"

# ❌ 不要用這個（關閉所有憑證驗證）
# NODE_TLS_REJECT_UNAUTHORIZED=0

# ═══ Python requests ═══
$ export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
# 或
$ python3 -c "import requests; requests.get('https://x', verify='/path/ca.crt')"

# ★ 把內部 CA 加進 certifi
$ python3 -c "import certifi; print(certifi.where())"
/usr/lib/python3/dist-packages/certifi/cacert.pem
$ cat /etc/ssl/certs/example-root-ca.crt | sudo tee -a "$(python3 -c 'import certifi; print(certifi.where())')"

# ═══ Go ═══
$ export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
$ export SSL_CERT_DIR=/etc/ssl/certs
```

---

## 完整實戰範例

### SAN 相容性檢查腳本

```bash
#!/usr/bin/env bash
# /usr/local/bin/check-san —— 憑證的 SAN 與相容性檢查
TARGET="${1:?用法: $0 <網域> 或 <憑證檔>}"
FAIL=0; WARN=0
pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m⚠\033[0m %s\n' "$1"; WARN=$((WARN+1)); }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }

# ── 取得憑證 ──
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
if [ -f "$TARGET" ]; then
    cp "$TARGET" "$TMP"; SRC="檔案：$TARGET"; HOST=""
else
    echo | timeout 10 openssl s_client -connect "$TARGET:443" -servername "$TARGET" 2>/dev/null | \
      openssl x509 > "$TMP" 2>/dev/null
    [ -s "$TMP" ] || { echo "✗ 無法取得 $TARGET 的憑證"; exit 1; }
    SRC="線上：$TARGET"; HOST="$TARGET"
fi

echo "═══ SAN 與相容性檢查 ═══"
echo "  來源：$SRC"

# ── ① 基本資訊 ──
echo -e "\n【1】主體與簽發者"
openssl x509 -in "$TMP" -noout -subject -issuer | sed 's/^/  /'

CN=$(openssl x509 -in "$TMP" -noout -subject | grep -oP 'CN\s*=\s*\K[^,/]+' | xargs)

# ── ② ★★ SAN ──
echo -e "\n【2】★★ Subject Alternative Name"
SAN_RAW=$(openssl x509 -in "$TMP" -noout -ext subjectAltName 2>/dev/null | tail -n +2 | xargs)
if [ -z "$SAN_RAW" ]; then
    fail "★★★ 沒有 SAN —— 這張憑證【現代瀏覽器完全不接受】"
    echo "     → 重新產生 CSR 時要在 req.txt 加上 req_extensions = req_ext"
    exit 1
fi
echo "$SAN_RAW" | tr ',' '\n' | sed 's/^ */    /'

DNS_LIST=$(echo "$SAN_RAW" | tr ',' '\n' | grep -oP 'DNS:\K\S+')
IP_LIST=$(echo "$SAN_RAW" | tr ',' '\n' | grep -oP 'IP Address:\K\S+')
echo
echo "  DNS 名稱：$(echo "$DNS_LIST" | grep -c .) 個"
[ -n "$IP_LIST" ] && echo "  IP 位址：$(echo "$IP_LIST" | grep -c .) 個"

# ── ③ ★★ CN 是否在 SAN 中 ──
echo -e "\n【3】★★ CN 是否列在 SAN 中"
if [ -z "$CN" ]; then
    warn "憑證沒有 CN（可以接受，因為瀏覽器只看 SAN）"
elif echo "$DNS_LIST" | grep -qx "$CN"; then
    pass "CN（$CN）有列在 SAN 中"
elif echo "$DNS_LIST" | grep -q '^\*\.'; then
    # 檢查萬用是否涵蓋 CN
    COVERED=0
    for w in $(echo "$DNS_LIST" | grep '^\*\.'); do
        SUF="${w#\*}"
        PRE="${CN%$SUF}"
        [ "$PRE" != "$CN" ] && [ -n "$PRE" ] && [[ "$PRE" != *.* ]] && COVERED=1
    done
    [ "$COVERED" -eq 1 ] && pass "CN（$CN）被萬用 SAN 涵蓋" \
                         || fail "★★ CN（$CN）不在 SAN 中【瀏覽器會拒絕】"
else
    fail "★★ CN（$CN）不在 SAN 中【瀏覽器會拒絕存取 https://$CN】"
fi

# ── ④ 萬用憑證的檢查 ──
echo -e "\n【4】萬用憑證"
WILD=$(echo "$DNS_LIST" | grep '^\*\.' || true)
if [ -n "$WILD" ]; then
    echo "$WILD" | sed 's/^/    /'
    for w in $WILD; do
        BASE="${w#\*.}"
        # ★ 根網域是否也在 SAN 中
        if echo "$DNS_LIST" | grep -qx "$BASE"; then
            pass "根網域 $BASE 也在 SAN 中"
        else
            fail "★★ $w 【不涵蓋根網域 $BASE】—— 要另外列出"
        fi
        # ★ 檢查是否為公共後綴
        DOTS=$(echo "$BASE" | tr -cd '.' | wc -c)
        [ "$DOTS" -lt 1 ] && fail "★ $w 涵蓋範圍過大（可能是公共後綴）"
    done
    echo
    echo "  ★ 提醒：萬用只涵蓋【一層】子網域"
    echo "    $WILD 涵蓋 a.${WILD#\*.} 但【不涵蓋】 b.a.${WILD#\*.}"
else
    echo "    （沒有萬用憑證）"
fi

# ── ⑤ IP SAN ──
echo -e "\n【5】IP 位址 SAN"
if [ -n "$IP_LIST" ]; then
    echo "$IP_LIST" | sed 's/^/    /'
    for ip in $IP_LIST; do
        if [[ "$ip" =~ ^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|127\.) ]]; then
            pass "$ip（私有位址，應為內部 CA 簽發）"
        else
            warn "$ip（公開位址）"
        fi
    done
    # ★ 檢查是否誤用 DNS 類型
    echo "$DNS_LIST" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' && \
      fail "★★ 有 IP 被寫成 DNS 類型【用 https://IP/ 存取時不會比對成功】"
else
    echo "    （沒有 IP SAN）"
fi

# ── ⑥ 有效期（★ 公開信任憑證的效期上限，分階段縮短中）──
# ★★ MAX_DAYS 請依 CA/Browser Forum 現行 Baseline Requirements 調整
#    上限只會越來越短，這個值要跟著改（本文撰寫日：2026-09）
MAX_DAYS=${CERT_MAX_DAYS:-366}
echo -e "\n【6】★ 有效期長度（公開信任憑證上限 ${MAX_DAYS} 天，持續縮短中）"
S=$(date -d "$(openssl x509 -in "$TMP" -noout -startdate | cut -d= -f2)" +%s)
E=$(date -d "$(openssl x509 -in "$TMP" -noout -enddate | cut -d= -f2)" +%s)
LEN=$(( (E - S) / 86400 ))
REMAIN=$(( (E - $(date +%s)) / 86400 ))
echo "    總長度：$LEN 天    剩餘：$REMAIN 天"
[ "$LEN" -gt "$MAX_DAYS" ] && fail "★★ 有效期 $LEN 天超過 $MAX_DAYS 天【Safari/Chrome/Firefox 會拒絕】" \
                   || pass "有效期未超過 $MAX_DAYS 天"
[ "$REMAIN" -lt 30 ] && warn "剩餘 $REMAIN 天【該續期了】"

# ── ⑦ 演算法 ──
echo -e "\n【7】演算法"
ALG=$(openssl x509 -in "$TMP" -noout -text | grep -oP 'Public Key Algorithm: \K\S+')
BITS=$(openssl x509 -in "$TMP" -noout -text | grep -oP 'Public-Key: \(\K\d+')
SIG=$(openssl x509 -in "$TMP" -noout -text | grep -oP 'Signature Algorithm: \K\S+' | head -1)
echo "    公鑰：$ALG $BITS bit"
echo "    簽章：$SIG"
case "$ALG" in
    rsaEncryption) [ "$BITS" -ge 2048 ] && pass "RSA $BITS ≥ 2048" || fail "RSA $BITS 太弱" ;;
    id-ecPublicKey) [ "$BITS" -ge 256 ] && pass "ECDSA $BITS" || fail "ECDSA $BITS 太弱" ;;
esac
echo "$SIG" | grep -qiE 'sha1|md5' && fail "★ 使用不安全的雜湊（$SIG）" || pass "雜湊安全"

# ── ⑧ ★ 實際比對測試 ──
if [ -n "$HOST" ]; then
    echo -e "\n【8】★ 實際比對測試"
    for d in $DNS_LIST; do
        [[ "$d" == \** ]] && continue
        C=$(curl -sI -m 10 -o /dev/null -w '%{http_code}' "https://$d/" 2>&1)
        if [ "$C" != "000" ] && [ -n "$C" ]; then
            printf '    ✓ %-40s HTTP %s\n' "$d" "$C"
        else
            ERR=$(curl -sI -m 10 "https://$d/" 2>&1 | head -1)
            printf '    ⚠ %-40s %s\n' "$d" "${ERR:0:50}"
        fi
    done
fi

# ── ⑨ ★ openssl 的主機名驗證 ──
if [ -n "$HOST" ]; then
    echo -e "\n【9】★ openssl 主機名驗證"
    R=$(echo | timeout 10 openssl s_client -connect "$HOST:443" -servername "$HOST" \
        -verify_hostname "$HOST" 2>&1 | grep -E 'Verification|verify error' | head -3)
    echo "$R" | sed 's/^/    /'
    echo "$R" | grep -q 'Verification: OK' && pass "主機名驗證通過" \
                                           || fail "主機名驗證失敗"
    echo "    ★ 提醒：openssl s_client 【預設不驗證主機名】，要加 -verify_hostname"
fi

# ── ⑩ 各平台提醒 ──
echo -e "\n【10】各平台相容性提醒"
cat <<'EOF'
    · Chrome/Edge  ★ 公開 CA 的憑證需要 CT（Certificate Transparency）
    · Safari/iOS   ★ 有效期上限分階段縮短中（以現行 CA/B Forum BR 為準）
    · Android 7+   ★ App 預設不信任「使用者安裝」的 CA
    · Java         ★ 有自己的 cacerts（keytool -importcert -cacerts）
    · Node.js      ★ NODE_EXTRA_CA_CERTS=/path/ca.crt
    · Python       ★ REQUESTS_CA_BUNDLE 或 certifi
    · Firefox      ★ 自己的信任清單（不用系統的）
EOF

echo -e "\n═══ 結果 ═══"
printf '  失敗 \033[31m%d\033[0m 項，警告 \033[33m%d\033[0m 項\n' "$FAIL" "$WARN"
exit $FAIL
```

```bash
$ check-san app.example.gov.tw
$ check-san /etc/letsencrypt/live/app.example.gov.tw/fullchain.pem
```

### 內部系統的 SAN 規劃

```ini
# ═══ 情境：內部系統有多種存取方式 ═══
[ alt_names ]
# ① 內部 FQDN（★ 主要）
DNS.1 = crm.internal.example.gov.tw

# ② 短名稱（★ 內網 DNS 的 search domain 會補完，但憑證要明確列出）
DNS.2 = crm

# ③ 別名
DNS.3 = crm-prod.internal.example.gov.tw
DNS.4 = customer.internal.example.gov.tw

# ④ ★ IP（緊急時直接用 IP 存取）
IP.1  = 10.0.5.20

# ⑤ ★ 本機（伺服器上的健康檢查腳本）
DNS.5 = localhost
IP.2  = 127.0.0.1

# ⑥ ★ 負載平衡器的 VIP
IP.3  = 10.0.5.100
```

> [!tip] 為什麼要列「短名稱」與「IP」
> ```
> 實際會發生的存取方式：
>   · 使用者在瀏覽器輸入 https://crm/          ← 短名稱
>   · 監控腳本用 https://10.0.5.20/health      ← IP
>   · 本機的健康檢查用 https://localhost/       ← localhost
>   · 應用之間的呼叫用 https://crm-prod.../     ← 別名
>
> ★ 每一種都必須列在 SAN 中，否則會憑證錯誤
> ★★ 但【不要列太多】—— 每個都是攻擊面
> ```

---

## 常見錯誤與排錯

| 錯誤訊息 | 原因 | 解法 |
| --- | --- | --- |
| **`ERR_CERT_COMMON_NAME_INVALID`** ★★★ | **憑證沒有 SAN，或 SAN 不含該網域** | 重新申請並在 SAN 中加入 |
| `SSL_ERROR_BAD_CERT_DOMAIN`（Firefox） | 同上 | 同上 |
| **`certificate subject name does not match`**（curl） | 同上 | 同上 |
| **萬用憑證連根網域失敗** ★★ | **`*.example.gov.tw` 不涵蓋 `example.gov.tw`** | **SAN 中兩個都要列** |
| **兩層子網域失敗** | 萬用只涵蓋一層 | 加 `*.api.example.gov.tw` |
| **用 IP 存取憑證錯誤** | IP 寫成 `DNS.n` | **改用 `IP.n`** |
| **Safari 拒絕但 Chrome 正常** | 有效期超過現行上限（上限持續縮短） | 重新申請較短效期的，並改用自動續期 |
| **Java 應用說憑證無效** ★ | **Java 有自己的 cacerts** | `keytool -importcert -cacerts` |
| **Node.js 說憑證無效** | Node 內建清單 | `NODE_EXTRA_CA_CERTS=/path/ca.crt` |
| Python requests 憑證錯誤 | certifi 的清單 | `REQUESTS_CA_BUNDLE` |
| **Android App 拒絕但瀏覽器正常** ★ | **Android 7+ App 不信任使用者 CA** | `network_security_config.xml`；或改用公開 CA |
| **`openssl s_client` 說 OK 但瀏覽器拒絕** ★ | **openssl 預設不驗證主機名** | 加 `-verify_hostname` |
| CN 有但 SAN 沒有該網域 | 忘了把 CN 列進 SAN | **CN 必須也在 SAN 中** |
| `*.gov.tw` 申請被拒 | 公共後綴 | 只能申請自己網域的萬用 |
| 憑證更新後某個子網域壞掉 | 新憑證的 SAN 漏了它 | 比對新舊憑證的 SAN |

### 排查流程

```bash
# 【1】★★ 最重要：看 SAN
$ echo | openssl s_client -connect D:443 -servername D 2>/dev/null | \
    openssl x509 -noout -ext subjectAltName

# 【2】★ 主機名驗證（不要只用 s_client 的預設）
$ echo | openssl s_client -connect D:443 -servername D -verify_hostname D 2>&1 | \
    grep -E 'Verification|verify error'

# 【3】★ 用 curl 完整驗證
$ curl -sI https://D/ | head -1
$ curl -v https://D/ 2>&1 | grep -E 'subject|SAN|issuer|SSL cert'

# 【4】比對新舊憑證的 SAN（更新後某個網域壞掉時）
$ diff <(openssl x509 -in old.pem -noout -ext subjectAltName | tr ',' '\n' | sort) \
       <(openssl x509 -in new.pem -noout -ext subjectAltName | tr ',' '\n' | sort)

# 【5】從 CSR 檢查（申請前）
$ openssl req -in app.csr -noout -text | grep -A1 'Subject Alternative Name'

# 【6】各平台分別測試
$ curl -sI https://D/                                    # OpenSSL
$ node -e "require('https').get('https://D',r=>console.log(r.statusCode))"
$ python3 -c "import requests; print(requests.get('https://D').status_code)"
$ java -Djavax.net.debug=ssl:handshake YourTest 2>&1 | grep -i 'subject\|SAN'
```

---

## 安全性注意事項

> [!danger] SAN 中的網域會出現在公開的 CT 日誌
> ```bash
> $ curl -s "https://crt.sh/?q=%25.example.gov.tw&output=json" | \
>     jq -r '.[].name_value' | tr '\n' '\n' | sort -u
> app.example.gov.tw
> www.example.gov.tw
> jenkins.internal.example.gov.tw          # ★★ 內部 CI 系統曝光了
> backup-db-01.example.gov.tw              # ★★ 資料庫主機曝光了
> vpn-admin.example.gov.tw                 # ★★ VPN 管理介面曝光了
> ```
>
> **這是攻擊者踩點的第一步。**
>
> **三個原則**：
> ```
> ① ★ 內部系統用【內部 CA】（不會進 CT 日誌）
> ② ★ 若一定要用公開憑證，用【萬用憑證】
>    *.internal.example.gov.tw 不洩漏個別主機名
> ③ ★ 不要在同一張憑證中混合「對外」與「內部」的網域
> ```
>
> ```bash
> # ★ 定期檢查你洩漏了什麼
> $ curl -s "https://crt.sh/?q=%25.example.gov.tw&output=json" | \
>     jq -r '.[].name_value' | tr ',' '\n' | sed 's/^ *//' | sort -u | \
>     grep -iE 'internal|dev|test|staging|admin|backup|db|jenkins|gitlab'
> ```

> [!warning] 萬用憑證的私鑰洩漏影響範圍極大
> ```
> *.example.gov.tw 的私鑰洩漏
>   → 攻擊者可以冒充【所有】子網域
>     → www、api、admin、payment、vpn...
>       → ★★ 而且撤銷後【所有】子網域都要重新部署
> ```
>
> **建議的分層策略**：
> ```
> 高價值服務（payment、admin、vpn）→ ★ 各自獨立的憑證
> 一般服務（www、docs、blog）      → 萬用憑證
> 內部系統                          → 內部 CA
> ```

> [!tip] 不要在 SAN 中放不必要的名稱
> ```
> ❌ 「反正多列幾個也沒差」
>   → 每一個都是【可以被冒充的目標】
>   → 每一個都【曝光在 CT 日誌中】
>   → 憑證更新時要重新確認每一個
>
> ✅ 只列【實際會被存取的】名稱
> ```
> ```bash
> # ★ 檢查 SAN 中的每個名稱是否真的在用
> $ openssl x509 -in cert.pem -noout -ext subjectAltName | \
>     tr ',' '\n' | grep -oP 'DNS:\K\S+' | while read -r d; do
>       N=$(grep -c "Host: $d" /var/log/nginx/access.log 2>/dev/null || echo 0)
>       printf '  %-40s 近期存取 %s 次 %s\n' "$d" "$N" \
>         "$([ "$N" -eq 0 ] && echo '★ 考慮移除' || echo '')"
>   done
> ```

---

## 速查表

### ★★★ 核心規則

```
現代瀏覽器【完全不看 CN，只看 SAN】（Chrome 58+ / Firefox 48+ / Safari）

→ 沒有 SAN 的憑證 = 沒有用
→ ★★ CN 必須【也】列在 SAN 中
```

```bash
# 快速檢查
openssl x509 -in cert.pem -noout -ext subjectAltName
echo | openssl s_client -connect D:443 -servername D 2>/dev/null | \
  openssl x509 -noout -ext subjectAltName
```

### SAN 的類型

```ini
[ alt_names ]
DNS.1 = app.example.gov.tw        # ★ CN 也要列
DNS.2 = *.example.gov.tw          # 萬用
IP.1  = 10.0.5.20                 # ★★ IP 必須用 IP.n（不是 DNS.n）
IP.2  = 2001:db8::1               # IPv6
email.1 = admin@example.gov.tw    # S/MIME
```

### ★★ 萬用憑證的規則

```
*.example.gov.tw 涵蓋：
  ✅ www.example.gov.tw · api.example.gov.tw
  ❌ example.gov.tw          ★★ 【不含根網域】→ 要另外列
  ❌ v1.api.example.gov.tw   ★★ 【只涵蓋一層】
  ❌ *.gov.tw                公共後綴，CA 不簽發
  ❌ www.*.example.gov.tw    萬用必須在最左邊

✅ 正確寫法：
   DNS.1 = example.gov.tw
   DNS.2 = *.example.gov.tw
   DNS.3 = *.api.example.gov.tw    # 需要兩層時
```

### 平台差異 ★

| 平台 | 注意事項 |
| --- | --- |
| **Safari / iOS** | **★ 有效期上限分階段縮短中（以現行 BR 為準）** |
| **Chrome** | ★ 公開 CA 需要 CT |
| **Android 7+** | **★ App 預設不信任「使用者安裝」的 CA** |
| **Java** | **★★ 自己的 `cacerts`**（`keytool -importcert -cacerts`） |
| **Node.js** | **★ `NODE_EXTRA_CA_CERTS=/path/ca.crt`** |
| **Python** | **★ `REQUESTS_CA_BUNDLE` / certifi** |
| **Firefox** | ★ 自己的信任清單 |
| **`openssl s_client`** | **★★ 預設「不驗證主機名」→ 要加 `-verify_hostname`** |

```bash
# ★ openssl 的正確測試方式
echo | openssl s_client -connect D:443 -servername D -verify_hostname D 2>&1 | \
  grep Verification
# ★ 更可靠：用 curl（會完整驗證）
curl -sI https://D/ | head -1
```

### 有效期檢查（上限分階段縮短中）

```bash
S=$(date -d "$(openssl x509 -in c.pem -noout -startdate | cut -d= -f2)" +%s)
E=$(date -d "$(openssl x509 -in c.pem -noout -enddate   | cut -d= -f2)" +%s)
echo "有效期 $(( (E-S)/86400 )) 天"        # ★ 超過現行上限 → Safari/Chrome 拒絕
```

### 常見錯誤

| 錯誤 | 原因 |
| --- | --- |
| **`ERR_CERT_COMMON_NAME_INVALID`** | **沒有 SAN，或 SAN 不含該網域** |
| 萬用憑證連根網域失敗 | **`*.d.tw` 不涵蓋 `d.tw`** |
| 用 IP 存取失敗 | **IP 寫成 `DNS.n`** |
| Safari 拒絕但 Chrome 正常 | 有效期超過現行上限 |
| Java / Node / Python 說無效 | **各自有獨立的信任清單** |
| Android App 拒絕但瀏覽器正常 | **App 不信任使用者安裝的 CA** |
| `s_client` OK 但瀏覽器拒絕 | **s_client 預設不驗證主機名** |

### 安全

```
① ★ SAN 中的網域全部進入公開的 CT 日誌
   → 內部系統用【內部 CA】或【萬用憑證】
② ★ 萬用憑證私鑰洩漏 = 所有子網域受影響
   → 高價值服務（payment/admin/vpn）用獨立憑證
③ ★ 只列實際會被存取的名稱（每個都是攻擊面）
```

```bash
# 檢查你洩漏了什麼
curl -s "https://crt.sh/?q=%25.example.gov.tw&output=json" | \
  jq -r '.[].name_value' | tr ',' '\n' | sort -u | \
  grep -iE 'internal|dev|test|admin|backup|db|jenkins'
```

---

## 練習題

> [!question]- 練習 1：重現 CN 不在 SAN 的問題
> 1. 產生一份 `req.txt`：CN = `app.test.local`，
>    但 `[alt_names]` **只有** `www.app.test.local`
> 2. 自簽一張憑證並部署到 Nginx
> 3. 用瀏覽器存取 `https://app.test.local/` → **看到什麼錯誤？**
> 4. 存取 `https://www.app.test.local/` → 正常嗎？
> 5. `openssl s_client -connect app.test.local:443`（**不加 `-verify_hostname`**）
>    → **它說 OK 嗎？**
> 6. 加上 `-verify_hostname app.test.local` → 現在呢？
> 7. **這說明了什麼？**

> [!question]- 練習 2：萬用憑證的邊界
> 1. 產生一張 SAN **只有** `*.test.local` 的憑證
> 2. 建立多個測試網域並逐一存取：
>    - `test.local`
>    - `www.test.local`
>    - `a.b.test.local`
> 3. **哪些成功？哪些失敗？為什麼？**
> 4. 加上 `DNS.2 = test.local` 重做
> 5. 加上 `DNS.3 = *.b.test.local` 再測 `a.b.test.local`
> 6. **畫出萬用憑證的涵蓋範圍圖**

> [!question]- 練習 3：IP SAN
> 1. 產生一張憑證，**故意把 IP 寫成 `DNS.1 = 10.0.5.20`**
> 2. 用 `https://10.0.5.20/` 存取 → **成功嗎？**
> 3. 改成 `IP.1 = 10.0.5.20`，重新產生
> 4. **再測一次**
> 5. `openssl x509 -noout -ext subjectAltName` 比較兩者的輸出差異
> 6. **記錄「IP 必須用 IP.n」這個規則**

> [!question]- 練習 4：各平台的信任清單
> 1. 用內部 CA 簽發一張憑證並部署
> 2. 把根憑證加進**系統**信任清單
> 3. 逐一測試：
>    ```bash
>    curl -sI https://internal.test.local/
>    node -e "require('https').get('https://internal.test.local',r=>console.log(r.statusCode))"
>    python3 -c "import requests; print(requests.get('https://internal.test.local').status_code)"
>    ```
> 4. **哪些成功？哪些失敗？**
> 5. 逐一設定各平台的信任（`NODE_EXTRA_CA_CERTS`、`REQUESTS_CA_BUNDLE`…）
> 6. **寫一份「內部 CA 派送檢查清單」**

> [!question]- 練習 5：CT 日誌盤點
> 1. 查詢你的機關網域在 CT 日誌中的所有記錄
> 2. **列出所有曝光的子網域**
> 3. **標記出「不該曝光的內部系統」**
> 4. 評估：這些資訊對攻擊者的價值是什麼？
> 5. 設計一個改善方案（內部 CA / 萬用憑證 / 分離）
> 6. 設定 CT 監控告警

---

## 小測驗

Q1. **為什麼 CN 已經被淘汰？從什麼時候開始**？

Q2. **「CN 必須也列在 SAN 中」為什麼是最常見的錯誤**？

Q3. **`*.example.gov.tw` 涵蓋哪些網域？「不」涵蓋哪些**？

Q4. **IP 位址的 SAN 為什麼必須用 `IP.n` 而不是 `DNS.n`**？

Q5. **`openssl s_client` 的預設行為有什麼陷阱？怎麼正確測試**？

Q6. **公開信任憑證的效期上限現在是什麼狀況？對憑證管理有什麼影響**？

Q7. **Android 7+ 對「使用者安裝的 CA」有什麼限制？三種解法是什麼**？

Q8. **哪四個平台有「自己的信任清單」？各怎麼設定**？

Q9. **萬用憑證與多網域憑證的取捨是什麼**？

Q10. **SAN 中的網域會洩漏什麼？三個處理原則是什麼**？

> [!question]- 測驗答案
> **Q1.** 因為 **CN（Common Name）是一個自由格式的欄位，語意不明確、
> 無法表達多個網域，而且原本的設計目的不是用來表示網域**。
> **RFC 2818（1999 年）就已經規定「若有 SAN 就只用 SAN，
> CN 已標記為 deprecated」**。
> **時間點**：
> **Chrome 58（2017 年）完全停止檢查 CN**，
> Firefox 48+（2018）、Safari（2019）陸續跟進。
> **現在沒有 SAN 的憑證等於沒有用** ——
> 會直接報 `ERR_CERT_COMMON_NAME_INVALID`，
> 而且在有 HSTS 的情況下無法點「繼續前往」繞過。
>
> **Q2.** 因為**直覺上會認為「CN 已經寫了主網域，SAN 只要列『其他』網域」** ——
> 於是寫成：
> ```ini
> CN = app.example.gov.tw
> [ alt_names ]
> DNS.1 = www.app.example.gov.tw      # ★★ 只有 www，沒有 app！
> ```
> **結果**：`https://www.app.example.gov.tw` 正常，
> 但 **`https://app.example.gov.tw` 憑證錯誤** ——
> 因為**瀏覽器完全不看 CN**。
> 正確做法是 **`[alt_names]` 中必須把 CN 也列進去**：
> ```ini
> DNS.1 = app.example.gov.tw          # ★ 與 CN 相同
> DNS.2 = www.app.example.gov.tw
> ```
>
> **Q3.** **`*.example.gov.tw` 涵蓋**：
> `www.example.gov.tw`、`api.example.gov.tw`、
> 任何**恰好一層**的子網域。
> **不涵蓋**：
> ①**`example.gov.tw`（根網域本身）** ——
> ★★ 這是極常見的失誤，必須另外列 `DNS.n = example.gov.tw`；
> ②**`v1.api.example.gov.tw`（兩層）** ——
> 要涵蓋需另外列 `*.api.example.gov.tw`；
> ③`*.gov.tw`（公共後綴，CA 不會簽發）；
> ④`www.*.example.gov.tw`（萬用字元必須在最左邊）。
>
> **Q4.** 因為 **X.509 的 SAN 有不同的「類型」** ——
> `DNS` 類型（dNSName）與 `IP Address` 類型（iPAddress）是**不同的資料結構**。
> **當使用者輸入 `https://10.0.5.20/` 時，
> 用戶端知道這是一個 IP 位址，會去憑證中尋找「iPAddress 類型」的 SAN 來比對**，
> **完全不會去比對 dNSName 類型的項目**。
> 所以寫成 `DNS.1 = 10.0.5.20` 時，
> 憑證中會是 `DNS:10.0.5.20`，**用 IP 存取時比對失敗**。
> 正確寫法：`IP.1 = 10.0.5.20` → 憑證中是 `IP Address:10.0.5.20`。
>
> **Q5.** **`openssl s_client` 預設「不驗證主機名」** ——
> 它只驗證憑證鏈是否可信，**完全不檢查憑證的 SAN 是否符合你連線的主機名**。
> ```bash
> # ❌ 即使 SAN 完全不符也不會報錯
> openssl s_client -connect example.gov.tw:443
> ```
> **這是很多人誤判「憑證沒問題」的原因** ——
> `s_client` 說 `Verification: OK` 不代表瀏覽器會接受。
> **正確測試**：
> ```bash
> openssl s_client -connect D:443 -servername D -verify_hostname D
> # 或更可靠：
> curl -sI https://D/ | head -1        # ★ curl 會完整驗證（含主機名）
> ```
>
> **Q6.** **Apple 從 2020 年 9 月起帶頭把公開信任憑證的有效期壓到約一年**，
> 超過的憑證**直接被 Safari 拒絕（不是警告）**；Chrome 與 Firefox 隨後跟進。
> **★★ 重點是這個上限並沒有停在一年** ——
> CA/Browser Forum 已決議**分階段再縮短**，方向只會往更短走；
> 具體天數與生效日**以現行 Baseline Requirements 與各 CA 公告為準**
> （本文撰寫日：2026-09），**不要把天數寫死**。
> **對憑證管理的影響**：
> ①**以前可以買 2-3 年的憑證，現在不可行**；
> ②**連「一年手動換一次」的作業方式也已經擐不住**；
> ③**★★★ 「自動化續期（ACME）」從「方便」變成「必要能力」** ——
> 手動更新憑證的時代已經結束（見 [[090-01-12-guide-PKI-憑證生命週期管理]]）。
> 業界的趨勢還在持續縮短（規劃中的 200 天 → 100 天 → 47 天）。
>
> **Q7.** **Android 7（API 24）起，App 預設「只信任系統的 CA」，
> 不信任使用者手動安裝的 CA** ——
> 即使使用者已經安裝了你的內部根憑證，**瀏覽器可以連，但 App 仍然拒絕**。
> **三種解法**：
> ①**App 加上 `network_security_config.xml`** 明確宣告信任使用者 CA：
> ```xml
> <trust-anchors>
>     <certificates src="system" />
>     <certificates src="user" />
> </trust-anchors>
> ```
> （★ 需要修改 App 並重新發布）；
> ②**把根憑證打包進 App**（憑證釘選 certificate pinning）；
> ③**★★ 內部系統改用「公開 CA」的憑證**（最省事）——
> 用 DNS-01 為內部主機申請（見 [[090-01-03-guide-PKI-向CA申請憑證]]）。
>
> **Q8.** ①**Java** —— `$JAVA_HOME/lib/security/cacerts`：
> ```bash
> sudo keytool -importcert -trustcacerts -alias my-ca -file ca.crt -cacerts -storepass changeit
> ```
> **★ 每次升級 JDK 都要重做**（cacerts 會被覆蓋）。
> ②**Node.js** —— 內建一份清單：
> ```bash
> export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/my-root-ca.crt
> ```
> （★ 不要用 `NODE_TLS_REJECT_UNAUTHORIZED=0`，那是關閉所有驗證）。
> ③**Python requests** —— certifi 的清單：
> ```bash
> export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
> ```
> ④**Firefox** —— 自己的 NSS database（要在 Firefox 的設定中匯入，
> 或用 `certutil` 操作 profile）。
> 另外 **Go** 用 `SSL_CERT_FILE`、**.NET** 用 Windows 憑證存放區。
>
> **Q9.** **萬用憑證（`*.example.gov.tw`）**：
> **優點** —— 新增子網域不用重新簽發；**CT 日誌只曝光一個萬用名稱**（不洩漏個別主機名）；
> **缺點** —— **私鑰洩漏影響所有子網域**；只涵蓋一層；必須用 DNS-01 申請。
> **多網域憑證（SAN 憑證）**：
> **優點** —— 精確控制涵蓋範圍；影響範圍可控；可用 HTTP-01；
> **缺點** —— **新增子網域要重新簽發**；**每個子網域都曝光在 CT 日誌**。
> **建議的分層策略**：
> **高價值服務（payment、admin、vpn）用獨立憑證**；
> 大量的低風險子網域用萬用憑證；
> 內部系統用內部 CA。
>
> **Q10.** **SAN 中的所有網域都會出現在公開的 Certificate Transparency 日誌中**，
> 任何人都能用 `crt.sh` 查詢 —— **這是攻擊者踩點的第一步**：
> ```
> jenkins.internal.example.gov.tw     ← CI 系統
> backup-db-01.example.gov.tw         ← 資料庫主機
> vpn-admin.example.gov.tw            ← VPN 管理介面
> ```
> **三個處理原則**：
> ①**內部系統用「內部 CA」**（簽發的憑證不會進入 CT 日誌）；
> ②**若一定要用公開憑證，用萬用憑證**
> （`*.internal.example.gov.tw` 不洩漏個別主機名）；
> ③**不要在同一張憑證中混合「對外」與「內部」的網域**。
> 另外**只列實際會被存取的名稱** —— 每一個都是可以被冒充的目標。

---

## 延伸閱讀

- [[090-01-02-guide-PKI-CSR產生與req設定檔]] — 在 CSR 中設定 SAN
- [[090-01-05-guide-PKI-自簽憑證快速產生]] — 快速產生測試憑證
- [[090-01-09-guide-PKI-根憑證派送與信任]] — 各平台的信任清單設定
- [[090-01-13-guide-PKI-憑證常見問題排查]] — 完整的錯誤對照
- [[090-01-03-guide-PKI-向CA申請憑證]] — 萬用憑證的申請
- [[090-01-01-guide-PKI-PKI與憑證基礎]] — CT 與 CAA
