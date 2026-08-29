---
title: "動態模組管理"
desc: "load_module 的順序、模組相依、版本綁定與升級策略"
aliases: [動態模組, load_module, dynamic module, modules-enabled, ABI]
tags: [群組/軟體與開發工具, 服務/nginx, 服務/myguard]
category: MyGuard與Angie
difficulty: 進階
status: 完成
distro: [ubuntu]
prerequisites: ["[[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]]", "[[060-02-02-01-guide-Nginx-安裝與目錄結構]]"]
updated: 2026-08-28
---

# 動態模組管理

> [!abstract] 這篇你會學到
> - **★★★★ 動態模組 vs 靜態編譯**的差別與限制
> - **★★★★ `load_module` 的位置與順序**（★ 順序真的會影響行為）
> - 模組的探索、安裝、啟用與停用
> - **★★★★ 版本綁定**（★ 模組與 nginx 主程式的 ABI 相依）
> - **★★★ 升級策略**與升級後的驗證
> - 過濾模組的執行順序
> - **★★★ 只裝需要的模組**（記憶體與攻擊面）

> [!warning] 未實機驗證 ★★★
> ```
> ★★★ 套件名稱與模組檔名以 MyGuard 套件庫的實際狀況為準。
> ★★★★ 執行前請用 apt-cache search 與 ls /usr/lib/nginx/modules/ 確認。
> ```

## 前置知識

- [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]] — 套件庫的加入
- [[060-02-02-01-guide-Nginx-安裝與目錄結構]] — NGINX 的目錄結構

---

## ★★★ 動態模組 vs 靜態編譯

```
★★★★ 兩種把模組加進 NGINX 的方式：

┌────────────────────┬──────────────────────┬────────────────────────┐
│                    │ ★★ 靜態編譯 (--add-module) │ ★★★ 動態模組 (--add-dynamic-module) │
├────────────────────┼──────────────────────┼────────────────────────┤
│ 產出               │ 編進 nginx 執行檔     │ ★★★ 獨立的 .so 檔案     │
│ 啟用方式           │ 編譯時就決定          │ ★★★ load_module 指令    │
│ ★★★ 增減模組       │ ★★★★ 要重新編譯整個 nginx│ ★★★ apt install + 一行設定 │
│ ★★★ 記憶體         │ 全部載入              │ ★★★ 只載入需要的        │
│ 啟動速度           │ ★ 略快                │ ★ 略慢（要 dlopen）     │
│ ★★★★ 版本相依      │ —                    │ ★★★★ 必須與主程式版本相符│
│ 官方套件庫         │ ★★ 少數模組           │ ★★★ MyGuard 提供 100+   │
└────────────────────┴──────────────────────┴────────────────────────┘

★★★★ 動態模組的關鍵限制：
  · ★★★★ 【必須和 nginx 主程式用相同的版本與編譯參數建置】
  · ★★★ nginx 升級 → 所有模組都要跟著升級
  · ★★ 不是所有模組都支援動態載入（★ 要修改 core 的就不行）
```

```bash
# ★★★ 看目前的 nginx 是怎麼編譯的
$ nginx -V 2>&1 | tr ' ' '\n' | grep -E '^--' | sort | head -30
--add-dynamic-module=...
--with-compat                        # ★★★★ 這個很重要（見下）
--with-http_v3_module
--with-http_ssl_module
...

# ★★★★ --with-compat 的意義
#   → 啟用「動態模組的相容 ABI」
#   → ★★★ 有這個參數，模組才能在不同的（但相容的）nginx 建置間使用
#   → ★★★★ 沒有的話，模組必須用【完全相同】的編譯參數建置
```

---

## ★★★ 探索與安裝

```bash
# ═══ ★★★ 列出所有可用的模組 ═══
$ apt-cache search '^libnginx-mod-' | sort
libnginx-mod-http-auth-pam - PAM 認證
libnginx-mod-http-autocert - 自動憑證（ACME）
libnginx-mod-http-brotli-filter - Brotli 壓縮
libnginx-mod-http-brotli-static - Brotli 預壓縮
libnginx-mod-http-cache-turbo - 邊緣快取
libnginx-mod-http-error-abuse - 錯誤率限流
libnginx-mod-http-geoip2 - GeoIP2
libnginx-mod-http-headers-more-filter - 標頭操作
libnginx-mod-http-image-filter - 圖片處理
libnginx-mod-http-lua - Lua
libnginx-mod-http-modsecurity - ModSecurity WAF
libnginx-mod-http-njs - NJS (JavaScript)
libnginx-mod-http-shield - 攻擊攔截
libnginx-mod-http-ssl-fingerprint - JA3/JA4 指紋
libnginx-mod-http-strip-filter - 回應精簡
libnginx-mod-http-vts - 虛擬主機流量狀態
libnginx-mod-http-zstd-filter - Zstd 壓縮
libnginx-mod-stream-geoip2 - stream 的 GeoIP2
...
$ apt-cache search '^libnginx-mod-' | wc -l
104

# ═══ ★★★ 查詢單一模組 ═══
$ apt-cache show libnginx-mod-http-cache-turbo | head -20
Package: libnginx-mod-http-cache-turbo
Version: 1.29.2-1~noble
Depends: nginx (= 1.29.2-1~noble)         # ★★★★ 版本綁死主程式！
Description: NGINX cache-turbo module

# ★★★★ 注意 Depends 的版本：模組和 nginx 是【綁在一起】的

# ═══ ★★★ 安裝 ═══
$ sudo apt install -y libnginx-mod-http-cache-turbo

# ★★★ 看它裝了什麼
$ dpkg -L libnginx-mod-http-cache-turbo
/usr/lib/nginx/modules/ngx_http_cache_turbo_module.so
/usr/share/nginx/modules-available/mod-http-cache-turbo.conf
/etc/nginx/modules-enabled/50-mod-http-cache-turbo.conf     # ★★★ 符號連結

$ cat /etc/nginx/modules-enabled/50-mod-http-cache-turbo.conf
load_module modules/ngx_http_cache_turbo_module.so;
```

```
★★★ Debian/Ubuntu 的模組管理慣例：

  /usr/lib/nginx/modules/          ★★★ .so 檔案的實際位置
  /usr/share/nginx/modules-available/   ★★ 所有可用的載入設定
  /etc/nginx/modules-enabled/      ★★★ 啟用的（符號連結到 available）
                                    ★★★★ 檔名的數字前綴決定【載入順序】

  nginx.conf 中：
    include /etc/nginx/modules-enabled/*.conf;    ★★★ 通常在最上層
```

```bash
# ═══ ★★★ 啟用與停用 ═══
# ★★★ 停用（★ 不移除套件）
$ sudo rm /etc/nginx/modules-enabled/50-mod-http-cache-turbo.conf
$ sudo nginx -t && sudo systemctl reload nginx

# ★★★ 重新啟用
$ sudo ln -sf /usr/share/nginx/modules-available/mod-http-cache-turbo.conf \
              /etc/nginx/modules-enabled/50-mod-http-cache-turbo.conf

# ★★★ 列出目前啟用的
$ ls -l /etc/nginx/modules-enabled/
$ sudo nginx -T 2>/dev/null | grep '^load_module'

# ★★★ 對照已安裝但沒啟用的
$ comm -23 \
    <(ls /usr/share/nginx/modules-available/ | sort) \
    <(ls /etc/nginx/modules-enabled/ | sed 's/^[0-9]*-//' | sort)
```

---

## ★★★★ `load_module` 的位置與順序

```
★★★★ 兩個硬規則：

  ① 【★★★★ 必須在 main context】
     → nginx.conf 的最上層，【http 區塊之前】
     → ★★★ 不能放在 http / server / location 裡面

  ② 【★★★★ 順序會影響 filter 模組的執行順序】
     → 對 filter 類的模組（壓縮、精簡、標頭處理）
     → ★★★ 順序錯了行為會不一樣
```

```nginx
# ═══ ★★★★ 正確的位置 ═══
# /etc/nginx/nginx.conf
user www-data;
worker_processes auto;
pid /run/nginx.pid;

# ★★★★ load_module 在這裡（main context）
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 4096;
}

http {
    # ★★★★ 不能在這裡 load_module！
    ...
}
```

```bash
# ★★★★ 放錯位置的錯誤訊息
$ sudo nginx -t
nginx: [emerg] "load_module" directive is specified too late in /etc/nginx/nginx.conf:42
#   ★★★ 意思是「已經進入 http 區塊了，太晚」

nginx: [emerg] "load_module" directive is not allowed here in .../app.conf:1
#   ★★★ 放在 server 或 location 裡面
```

### ★★★★ 過濾模組的執行順序

```
★★★★ NGINX 的 filter 模組形成一個【鏈】，
      而【後載入的模組先執行】（★ 這是反直覺的地方）

  載入順序：A → B → C
  ★★★ 回應處理順序：C → B → A

★★★★ 為什麼重要（★ 三個實例）：

【① 壓縮 vs 精簡】
  ★★★★ 正確：strip 先執行（精簡）→ 然後才壓縮
  → ★★★ strip 要【後載入】才會先執行？
  → ★★★★ 實務上：MyGuard 的套件用數字前綴排好了順序
    不要自己亂改

【② SSI vs 壓縮】
  ★★★ SSI 要在壓縮【之前】處理（★ 否則處理的是壓縮後的位元組）

【③ 標頭處理】
  ★★ headers-more 的 more_set_headers 要在其他模組之後

★★★★ 實務建議：
  · ★★★ 用套件提供的預設順序（數字前綴）
  · ★★ 只有在確定要調整時才改，而且要完整測試
  · ★★★★ 改了順序之後【一定要驗證所有相關功能】
```

```bash
# ★★★ 看目前的載入順序
$ ls -1 /etc/nginx/modules-enabled/ | sort
10-mod-http-geoip2.conf
15-mod-http-ssl-fingerprint.conf
50-mod-http-autocert.conf
50-mod-http-cache-turbo.conf
50-mod-http-shield.conf
50-mod-http-error-abuse.conf
70-mod-http-brotli-filter.conf              # ★★★ filter 類通常較後面
70-mod-http-zstd-filter.conf
75-mod-http-strip-filter.conf
80-mod-http-headers-more-filter.conf

$ sudo nginx -T 2>/dev/null | grep '^load_module'
load_module modules/ngx_http_geoip2_module.so;
load_module modules/ngx_http_ssl_fingerprint_module.so;
load_module modules/ngx_http_autocert_module.so;
...

# ★★★ 調整順序：改檔名的數字前綴
$ cd /etc/nginx/modules-enabled/
$ sudo mv 70-mod-http-brotli-filter.conf 78-mod-http-brotli-filter.conf
$ sudo nginx -t && sudo systemctl reload nginx
#   ★★★★ 改完一定要完整測試（壓縮、精簡、標頭都要驗）
```

> [!danger] 模組相依 ★★★
> ```
> ★★★ 有些模組需要【其他模組先載入】：
>
>   ssl-fingerprint  → ★★★ 提供 $ssl_fingerprint_ja3_hash 等變數
>                       → sentinel 才能用
>   geoip2           → ★★★ 提供 $geoip2_asn
>                       → sentinel 的 ASN 訊號才能用
>   brotli-filter    → ★★ brotli-static 通常需要它
>
> ★★★★ 相依的模組要【先載入】（★ 數字前綴要更小）
>   10-mod-http-geoip2.conf              ← 先
>   15-mod-http-ssl-fingerprint.conf     ← 再
>   50-mod-http-sentinel.conf            ← ★★★ 後（用到前兩個的變數）
>
> ★★★ 順序錯了的症狀：
>   nginx: [emerg] unknown "geoip2_asn" variable
>   → ★★★ 變數在使用時還沒被定義
> ```

---

## ★★★★ 版本綁定與升級

```
★★★★ 動態模組和 nginx 主程式是【版本綁死】的：

  $ apt-cache show libnginx-mod-http-cache-turbo | grep Depends
  Depends: nginx (= 1.29.2-1~noble)
                 ↑ ★★★★ 精確相等，不是 >=

★★★ 意義：
  · nginx 升級到 1.29.3 → ★★★★ 所有模組都必須跟著升到 1.29.3
  · ★★★ apt 會【一起升級】（★ 因為相依關係）
  · ★★★★ 但如果某個模組還沒有新版本 → apt 會【阻擋整個升級】

★★★★ 版本不符的症狀：
  nginx: [emerg] module "ngx_http_xxx_module.so" version 1029002
         instead of 1029003 in /etc/nginx/nginx.conf:5
  → ★★★★ nginx 完全起不來！
```

```bash
# ═══ ★★★★ 安全的升級流程 ═══
$ sudo tee /usr/local/bin/nginx-upgrade >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★★★ 安全地升級 nginx 與所有動態模組
set -euo pipefail

echo "═══ NGINX 升級 ═══"

# ═══ ★★★【1】現況 ═══
echo -e "\n【1】現況"
CUR=$(nginx -v 2>&1 | grep -oP 'nginx/\K\S+')
echo "  目前版本: $CUR"
echo "  ── 已安裝的模組 ──"
MODS=$(dpkg-query -W -f='${Package} ${Version}\n' 'libnginx-mod-*' 2>/dev/null)
echo "$MODS" | sed 's/^/    /'
NMOD=$(echo "$MODS" | grep -c . || echo 0)
echo "  共 $NMOD 個模組"

# ═══ ★★★★【2】檢查可升級的版本是否一致 ═══
echo -e "\n【2】★★★★ 版本一致性檢查"
sudo apt update -qq
NEW_NGINX=$(apt-cache policy nginx | awk '/Candidate:/{print $2}')
echo "  nginx 候選版本: $NEW_NGINX"

MISMATCH=0
echo "$MODS" | awk '{print $1}' | while read -r p; do
    c=$(apt-cache policy "$p" 2>/dev/null | awk '/Candidate:/{print $2}')
    if [ "$c" != "$NEW_NGINX" ]; then
        printf "    ★★★★ %-46s %s (≠ %s)\n" "$p" "$c" "$NEW_NGINX"
        MISMATCH=1
    fi
done

# ★★★★ 用 apt 模擬檢查（★ 更可靠）
echo -e "\n  ── 模擬升級 ──"
if sudo apt-get -s upgrade nginx 2>&1 | grep -qE '^(E:|The following packages have been kept back)'; then
    echo "  ★★★★ apt 回報有問題："
    sudo apt-get -s upgrade nginx 2>&1 | grep -A5 -E '^(E:|kept back)' | sed 's/^/    /'
    echo "  ★★★ 可能是某個模組還沒有對應的新版本"
    echo "  ★★ 建議：等套件庫更新，或先移除該模組"
    exit 1
fi
echo "  ★ 版本一致，可以升級"

# ═══ ★★★【3】備份 ═══
echo -e "\n【3】備份"
TS=$(date +%Y%m%d-%H%M%S)
sudo tar -czf "/root/nginx-config-$TS.tar.gz" /etc/nginx/
sudo nginx -T > "/root/nginx-full-$TS.conf" 2>/dev/null
dpkg-query -W -f='${Package}=${Version}\n' 'nginx*' 'libnginx-mod-*' \
    > "/root/nginx-packages-$TS.txt"
echo "  ★ 設定: /root/nginx-config-$TS.tar.gz"
echo "  ★ 完整設定: /root/nginx-full-$TS.conf"
echo "  ★★★ 套件版本: /root/nginx-packages-$TS.txt（★ 回退用）"

# ═══ ★★★【4】升級 ═══
echo -e "\n【4】升級"
sudo apt install -y nginx $(echo "$MODS" | awk '{print $1}' | tr '\n' ' ')

# ═══ ★★★★【5】驗證 ═══
echo -e "\n【5】★★★★ 驗證"
NEW=$(nginx -v 2>&1 | grep -oP 'nginx/\K\S+')
echo "  新版本: $NEW"

echo "  ── 模組版本一致性 ──"
BAD=0
for so in /usr/lib/nginx/modules/*.so; do
    [ -f "$so" ] || continue
    p=$(dpkg -S "$so" 2>/dev/null | cut -d: -f1)
    v=$(dpkg-query -W -f='${Version}' "$p" 2>/dev/null)
    nv=$(dpkg-query -W -f='${Version}' nginx 2>/dev/null)
    if [ "$v" != "$nv" ]; then
        printf "    ★★★★ %-40s %s (nginx=%s)\n" "$(basename "$so")" "$v" "$nv"
        BAD=$((BAD+1))
    fi
done
[ "$BAD" -eq 0 ] && echo "    ★ 全部一致"

echo "  ── 設定語法 ──"
if sudo nginx -t; then
    echo "    ★ 通過"
else
    echo "    ★★★★ 語法錯誤！可能是模組載入失敗"
    echo "    ★★★ 回退方式："
    echo "      sudo apt install -y --allow-downgrades \$(cat /root/nginx-packages-$TS.txt | tr '\n' ' ')"
    exit 1
fi

# ═══ ★★★【6】重載並驗證服務 ═══
echo -e "\n【6】重載"
sudo systemctl reload nginx
sleep 2
systemctl is-active --quiet nginx && echo "  ★ 服務正常" || {
    echo "  ★★★★ 服務異常！"; sudo journalctl -u nginx -n 20 --no-pager; exit 1; }

echo "  ── 端點測試 ──"
for u in / /api/health; do
    printf "    %-16s " "$u"
    curl -sko /dev/null -w '%{http_code}\n' --max-time 10 "https://localhost$u" || echo "失敗"
done

echo -e "\n★ 升級完成 $CUR → $NEW"
echo "★★★ 建議接著執行完整的功能驗證（★ 見下方檢查清單）"
EOF
$ sudo chmod +x /usr/local/bin/nginx-upgrade
$ sudo nginx-upgrade
```

```bash
# ═══ ★★★★ 升級後的功能檢查清單 ═══
$ sudo tee /usr/local/bin/nginx-module-verify >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★★★ 驗證每個模組的功能是否正常
URL="${1:-https://localhost}"
FAIL=0
chk(){ printf '  %-42s ' "$1"; shift
       eval "$@" >/dev/null 2>&1 && echo "✓" || { echo "★★★★ 失敗"; FAIL=$((FAIL+1)); }; }

echo "═══ 模組功能驗證 ═══"
CONF=$(sudo nginx -T 2>/dev/null)
LOADED=$(echo "$CONF" | grep -oP '^load_module modules/\K\S+' | tr -d ';')

echo -e "\n【載入的模組】"
echo "$LOADED" | sed 's/^/  /'

echo -e "\n【★★★ 功能驗證】"

echo "$LOADED" | grep -q autocert && \
  chk "autocert：憑證有效" \
      "echo | openssl s_client -connect \${URL#https://}:443 2>/dev/null | grep -q 'Verify return code: 0'"

echo "$LOADED" | grep -q shield && {
  chk "shield：擋掉 SQLi" \
      "[ \"\$(curl -sko /dev/null -w '%{http_code}' \"$URL/?id=1'+union+select+1--\")\" != '200' ]"
  chk "shield：正常請求放行" \
      "[ \"\$(curl -sko /dev/null -w '%{http_code}' \"$URL/\")\" = '200' ]"
}

echo "$LOADED" | grep -q cache_turbo && \
  chk "cache-turbo：X-Cache 標頭存在" \
      "curl -skI \"$URL/\" | grep -qi 'x-cache'"

echo "$LOADED" | grep -q brotli && \
  chk "brotli：br 壓縮生效" \
      "curl -skI -H 'Accept-Encoding: br' \"$URL/\" | grep -qi 'content-encoding: br'"

echo "$LOADED" | grep -q zstd && \
  chk "zstd：zstd 壓縮生效" \
      "curl -skI -H 'Accept-Encoding: zstd' \"$URL/\" | grep -qi 'content-encoding: zstd'"

echo "$LOADED" | grep -q strip && \
  chk "strip：HTML 註解被移除" \
      "[ \"\$(curl -sk \"$URL/\" | grep -c '<!--')\" = '0' ]"

echo "$LOADED" | grep -q modsecurity && \
  chk "modsecurity：日誌存在" '[ -f /var/log/modsec_audit.log ]'

echo "$LOADED" | grep -q geoip2 && \
  chk "geoip2：資料庫存在" '[ -f /usr/share/GeoIP/GeoLite2-Country.mmdb ] || [ -f /usr/share/GeoIP/GeoLite2-ASN.mmdb ]'

echo -e "\n【★★★ 通用】"
chk "Vary: Accept-Encoding" "curl -skI \"$URL/\" | grep -qi 'vary.*accept-encoding'"
chk "沒有 500 錯誤"          "[ \"\$(curl -sko /dev/null -w '%{http_code}' \"$URL/\")\" -lt '500' ]"
chk "error.log 沒有新的 emerg" \
    "! sudo tail -50 /var/log/nginx/error.log | grep -q '\[emerg\]'"

echo ""
[ "$FAIL" -eq 0 ] && echo "★ 全部通過" || echo "★★★★ $FAIL 項失敗"
exit "$FAIL"
EOF
$ sudo chmod +x /usr/local/bin/nginx-module-verify
$ sudo nginx-module-verify https://app.example.gov.tw
```

> [!danger] 升級的三個風險 ★★★★
> ```
> ① ★★★★ 【某個模組還沒有新版本】
>      → apt 會 kept back，或強制升級會導致版本不符
>      → ★★★★ nginx 完全起不來
>      → ★★★ 解法：等套件庫更新，或先停用該模組
>
> ② ★★★ 【新版本的指令語法變了】
>      → nginx -t 失敗
>      → ★★★ 升級前先看 changelog
>      $ apt changelog nginx | head -50
>
> ③ ★★★★ 【模組的行為變了但語法沒變】
>      → ★★★★ 最危險，nginx -t 通過但功能不對
>      → ★★★ 升級後一定要跑完整的功能驗證
>
> ★★★★ 正式環境的做法：
>   ① 在【測試環境】先升級並完整驗證
>   ② ★★★ apt-mark hold 鎖住正式環境的版本
>   ③ 排定維護時間窗
>   ④ ★★★★ 準備好回退指令（套件版本清單）
> ```

```bash
# ★★★★ 正式環境鎖版本
$ sudo apt-mark hold nginx $(dpkg-query -W -f='${Package} ' 'libnginx-mod-*')
$ apt-mark showhold

# ★★★ 要升級時解鎖
$ sudo apt-mark unhold nginx $(dpkg-query -W -f='${Package} ' 'libnginx-mod-*')
$ sudo nginx-upgrade
$ sudo apt-mark hold nginx $(dpkg-query -W -f='${Package} ' 'libnginx-mod-*')

# ★★★★ 回退
$ sudo apt install -y --allow-downgrades \
    $(cat /root/nginx-packages-20260828-190011.txt | tr '\n' ' ')
$ sudo nginx -t && sudo systemctl reload nginx
```

---

## ★★★ 只裝需要的模組

```
★★★★ 為什麼不要「全部裝起來備用」：

  ① ★★★ 記憶體
     → 每個載入的模組都佔記憶體（★ 每個 worker 都要）
     → ★★ 100 個模組 × 8 個 worker → 明顯的浪費

  ② ★★★★ 攻擊面
     → ★★★ 每個模組都是額外的程式碼
     → 模組本身可能有漏洞（★ 而且第三方模組的審查通常較少）
     → ★★★★ 載入但沒用到的模組一樣有風險

  ③ ★★★ 升級的複雜度
     → ★★★★ 裝越多，升級時「某個模組沒有新版本」的機率越高
     → 一個模組卡住 → 整個 nginx 不能升級

  ④ ★★ 啟動速度
     → 每個模組都要 dlopen

★★★★ 原則：【現在用得到的才裝】
```

```bash
# ═══ ★★★★ 稽核：哪些模組載入了但沒用到 ═══
$ sudo tee /usr/local/bin/nginx-module-audit >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★★★ 找出載入但沒有使用的模組
CONF=$(sudo nginx -T 2>/dev/null)
echo "═══ 模組使用稽核 ═══"

# ★★★ 模組名稱 → 對應的關鍵指令
declare -A DIRECTIVES=(
    [autocert]="autocert"
    [shield]="shield"
    [cache_turbo]="cache_turbo"
    [error_abuse]="error_abuse"
    [sentinel]="sentinel"
    [strip_filter]="strip"
    [brotli_filter]="brotli"
    [brotli_static]="brotli_static"
    [zstd_filter]="zstd"
    [zstd_static]="zstd_static"
    [geoip2]="geoip2"
    [modsecurity]="modsecurity"
    [headers_more]="more_set_headers|more_clear_headers"
    [image_filter]="image_filter"
    [lua]="content_by_lua|access_by_lua|init_by_lua"
    [njs]="js_content|js_set|js_import"
    [ssl_fingerprint]="ssl_fingerprint"
    [vts]="vhost_traffic_status"
    [auth_pam]="auth_pam"
)

echo -e "\n【★★★★ 載入但未使用】"
UNUSED=0
echo "$CONF" | grep -oP '^load_module modules/ngx_(http_|stream_)?\K\w+(?=_module\.so)' | \
while read -r m; do
    pat="${DIRECTIVES[$m]:-$m}"
    #   ★★★ 排除 load_module 那一行本身
    n=$(echo "$CONF" | grep -v '^load_module' | grep -cE "^\s*($pat)" || echo 0)
    if [ "$n" -eq 0 ]; then
        pkg=$(dpkg -S "/usr/lib/nginx/modules/"*"$m"*.so 2>/dev/null | cut -d: -f1 | head -1)
        printf "  ★★★★ %-24s（套件: %s）\n" "$m" "${pkg:-?}"
    fi
done

echo -e "\n【已使用的模組】"
echo "$CONF" | grep -oP '^load_module modules/ngx_(http_|stream_)?\K\w+(?=_module\.so)' | \
while read -r m; do
    pat="${DIRECTIVES[$m]:-$m}"
    n=$(echo "$CONF" | grep -v '^load_module' | grep -cE "^\s*($pat)" || echo 0)
    [ "$n" -gt 0 ] && printf "  ✓ %-24s（%d 處）\n" "$m" "$n"
done

echo -e "\n【記憶體】"
ps -o rss= -C nginx 2>/dev/null | awk '{s+=$1} END {printf "  nginx 總計: %.1f MB\n", s/1024}'
N=$(echo "$CONF" | grep -c '^load_module')
echo "  載入的模組數: $N"

echo -e "\n★★★ 停用未使用的模組："
echo "  sudo rm /etc/nginx/modules-enabled/NN-mod-XXX.conf"
echo "  sudo nginx -t && sudo systemctl reload nginx"
echo "★★★ 確定不用的話再移除套件："
echo "  sudo apt remove libnginx-mod-XXX"
EOF
$ sudo chmod +x /usr/local/bin/nginx-module-audit
$ sudo nginx-module-audit

═══ 模組使用稽核 ═══

【★★★★ 載入但未使用】
  ★★★★ image_filter          （套件: libnginx-mod-http-image-filter）
  ★★★★ lua                   （套件: libnginx-mod-http-lua）
  ★★★★ vts                   （套件: libnginx-mod-http-vts）

【已使用的模組】
  ✓ autocert                （3 處）
  ✓ shield                  （8 處）
  ✓ cache_turbo             （12 處）
  ✓ brotli_filter           （4 處）
  ✓ strip_filter            （5 處）

【記憶體】
  nginx 總計: 284.2 MB
  載入的模組數: 8
```

---

## 完整實戰範例：一組精簡的模組配置

```bash
#!/usr/bin/env bash
# ★★★ /usr/local/bin/setup-nginx-modules —— 依用途安裝模組
set -euo pipefail

PROFILE="${1:-web}"      # web | api | secure | full

case "$PROFILE" in
    web)
        # ★★★ 一般網站：憑證 + 防護 + 快取 + 壓縮
        MODS="autocert shield cache-turbo brotli-filter brotli-static strip-filter"
        ;;
    api)
        # ★★★ API：憑證 + 防護 + 限流 + 壓縮（★ 不需要 HTML 快取與精簡）
        MODS="autocert shield error-abuse brotli-filter zstd-filter"
        ;;
    secure)
        # ★★★★ 高安全需求：加上 WAF 與指紋
        MODS="autocert shield error-abuse modsecurity geoip2 ssl-fingerprint brotli-filter"
        ;;
    full)
        MODS="autocert shield error-abuse cache-turbo strip-filter \
              brotli-filter brotli-static zstd-filter zstd-static \
              modsecurity geoip2 ssl-fingerprint headers-more-filter"
        ;;
    *)
        echo "★★ 用法: setup-nginx-modules [web|api|secure|full]"; exit 1 ;;
esac

echo "═══ 安裝 NGINX 模組（$PROFILE）═══"

# ═══ ★★★【1】檢查可用性 ═══
echo -e "\n【1】檢查套件"
AVAIL=""
for m in $MODS; do
    p="libnginx-mod-http-$m"
    if apt-cache show "$p" >/dev/null 2>&1; then
        printf "  ✓ %s\n" "$p"
        AVAIL="$AVAIL $p"
    else
        printf "  ★★★ 找不到 %s（★ 名稱可能不同）\n" "$p"
    fi
done
[ -n "$AVAIL" ] || { echo "★★ 沒有可安裝的模組"; exit 1; }

# ═══ ★★★★【2】版本一致性 ═══
echo -e "\n【2】★★★★ 版本一致性"
NGINX_V=$(apt-cache policy nginx | awk '/Candidate:/{print $2}')
echo "  nginx: $NGINX_V"
for p in $AVAIL; do
    v=$(apt-cache policy "$p" | awk '/Candidate:/{print $2}')
    [ "$v" = "$NGINX_V" ] || printf "  ★★★★ %s 版本不符: %s\n" "$p" "$v"
done

# ═══ ★★★【3】安裝 ═══
echo -e "\n【3】安裝"
# shellcheck disable=SC2086
sudo apt install -y nginx $AVAIL

# ═══ ★★★【4】載入順序 ═══
echo -e "\n【4】★★★ 載入順序"
ls -1 /etc/nginx/modules-enabled/ | sort | sed 's/^/  /'

# ═══ ★★★★【5】驗證 ═══
echo -e "\n【5】驗證"
sudo nginx -t && echo "  ★ 語法正確"
sudo nginx -T 2>/dev/null | grep -c '^load_module' | \
  awk '{print "  載入了 " $1 " 個模組"}'

echo -e "\n【6】★★★ 記憶體基準"
sudo systemctl reload nginx && sleep 2
ps -o rss= -C nginx | awk '{s+=$1} END {printf "  nginx 總計: %.1f MB\n", s/1024}'

echo -e "\n★ 完成。下一步："
echo "  · 在設定檔中啟用需要的功能"
echo "  · sudo nginx-module-verify https://your-domain"
echo "  · ★★★ sudo apt-mark hold nginx 'libnginx-mod-*'（正式環境鎖版本）"
```

```bash
$ sudo install -m755 setup-nginx-modules.sh /usr/local/bin/setup-nginx-modules
$ sudo setup-nginx-modules web
```

```nginx
# ═══ ★★★ 對應的 nginx.conf 骨架 ═══
# /etc/nginx/nginx.conf
user www-data;
worker_processes auto;
worker_rlimit_nofile 65536;
pid /run/nginx.pid;

# ★★★★ 模組載入（★ main context，http 之前）
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 8192;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # ═══ ★★★ 各模組的全域設定 ═══
    # autocert
    resolver 1.1.1.1 8.8.8.8 valid=300s ipv6=off;
    autocert_contact admin@example.gov.tw;
    autocert_key_type p384 rsa2048;

    # shield
    shield detect;
    shield_log /var/log/nginx/shield.json;
    shield_ban_zone shield:10m;

    # cache-turbo
    cache_turbo_zone name=ct 256m;

    # 壓縮
    gzip on; gzip_vary on; gzip_static on; gzip_comp_level 5;
    brotli on; brotli_static on; brotli_comp_level 5;

    # strip
    strip on; strip_css on; strip_json on;

    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`load_module directive is specified too late`** ★★★★ | **放在 http 之後** | 移到 nginx.conf 最上層 |
| **`module version 1029002 instead of 1029003`** ★★★★ | **版本不符** | 一起升級 nginx 與所有模組 |
| **`unknown directive "xxx"`** ★★★★ | 模組沒載入 | `nginx -T \| grep load_module` |
| **`unknown "geoip2_asn" variable`** ★★★ | **相依模組載入順序錯** | 調整數字前綴 |
| **`cannot load module ... undefined symbol`** ★★★★ | 編譯參數不相容 | 用同一個套件庫的版本；`--with-compat` |
| **`apt` 說 kept back** ★★★★ | **某模組沒有新版本** | 等套件庫更新；或先移除該模組 |
| **升級後功能怪怪的** ★★★★ | 行為變了但語法沒變 | **跑完整的功能驗證** |
| **記憶體用量高** ★★★ | 載入太多模組 | `nginx-module-audit` 找出沒用的 |
| **壓縮/精簡的順序不對** ★★★ | filter 載入順序 | 調整數字前綴並完整測試 |
| 停用模組後 nginx 起不來 ★★★★ | **設定檔還在用該模組的指令** | **先移除指令再停用模組** |

### 排查

```bash
# 【1】★★★★ 載入了哪些模組
$ sudo nginx -T 2>/dev/null | grep '^load_module'
$ ls -l /etc/nginx/modules-enabled/
$ ls -l /usr/lib/nginx/modules/

# 【2】★★★★ 版本一致性
$ dpkg-query -W -f='${Package} ${Version}\n' nginx 'libnginx-mod-*' | column -t
$ NV=$(dpkg-query -W -f='${Version}' nginx)
$ dpkg-query -W -f='${Package} ${Version}\n' 'libnginx-mod-*' | \
    awk -v v="$NV" '$2 != v {print "★★★★ 版本不符: " $0}'

# 【3】★★★ 模組的相依
$ apt-cache depends libnginx-mod-http-cache-turbo
$ ldd /usr/lib/nginx/modules/ngx_http_cache_turbo_module.so | grep 'not found'

# 【4】★★★ 編譯參數
$ nginx -V 2>&1 | tr ' ' '\n' | grep -E '^--with-compat|^--prefix|^--modules-path'

# 【5】★★★★ 找出載入但沒用的
$ sudo nginx-module-audit

# 【6】★★★ 功能驗證
$ sudo nginx-module-verify https://app.example.gov.tw

# 【7】★★ 記憶體
$ ps -o pid,rss,cmd -C nginx
$ sudo nginx -T | grep -c '^load_module'

# 【8】★★★★ 停用模組前先檢查設定有沒有用到
$ MOD=cache_turbo
$ sudo nginx -T 2>/dev/null | grep -v '^load_module' | grep -cE "^\s*$MOD"
#   ★★★★ 大於 0 = 還在用，不能直接停用
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★
> ```
> ① ★★★★ 每個模組都是額外的攻擊面
>      → ★★★ 只裝現在用得到的
>      → 定期執行 nginx-module-audit 清理
>
> ② ★★★ 第三方模組的審查較少
>      → ★★★★ 官方模組 vs 社群模組 vs 單一維護者的模組
>      → 風險等級不同，正式環境要評估
>
> ③ ★★★★ 模組升級不能落後
>      → 模組有漏洞時，nginx 主程式沒事也一樣危險
>      → ★★★ 訂閱套件庫的公告；定期 apt list --upgradable
>
> ④ ★★★ 模組檔案的權限
>      → ★★★★ .so 可寫 = 攻擊者可以植入程式碼
>      → root:root 644
>
> ⑤ ★★★ 停用未使用的模組（不只是不用它的指令）
>      → ★★★★ 載入了就會執行初始化，還是有風險
> ```

```bash
# ★★★★ 模組檔案的權限稽核
$ ls -l /usr/lib/nginx/modules/
-rw-r--r-- 1 root root 148K ... ngx_http_cache_turbo_module.so    # ★★★ 正確

$ find /usr/lib/nginx/modules/ -type f ! -user root -o ! -group root 2>/dev/null
$ find /usr/lib/nginx/modules/ -type f -perm /go+w 2>/dev/null
#   ★★★★ 有輸出 = 可被非 root 寫入，立刻修正
$ sudo chown root:root /usr/lib/nginx/modules/*.so
$ sudo chmod 644 /usr/lib/nginx/modules/*.so

# ★★★ 確認模組來自套件管理（★ 不是手動放的）
$ for so in /usr/lib/nginx/modules/*.so; do
    if ! dpkg -S "$so" >/dev/null 2>&1; then
        echo "★★★★ 非套件管理的模組: $so"
        ls -l "$so"
        sha256sum "$so"
    fi
  done

# ★★★ 完整性監控（AIDE）
$ sudo tee -a /etc/aide/aide.conf.d/99_nginx_modules >/dev/null <<'EOF'
/usr/lib/nginx/modules/.*\.so$ FIPSR
/etc/nginx/modules-enabled/ FIPSR
EOF
$ sudo aideinit && sudo aide --check | grep -A5 nginx

# ★★★★ 追蹤模組的安全更新
$ sudo tee /usr/local/bin/nginx-security-check >/dev/null <<'EOF'
#!/usr/bin/env bash
echo "═══ NGINX 模組安全檢查 $(date '+%F') ═══"

echo -e "\n【★★★ 可用的更新】"
apt list --upgradable 2>/dev/null | grep -E '^(nginx|libnginx-mod-)' | sed 's/^/  /' || \
  echo "  ★ 沒有可用的更新"

echo -e "\n【★★★★ 版本一致性】"
NV=$(dpkg-query -W -f='${Version}' nginx 2>/dev/null)
BAD=$(dpkg-query -W -f='${Package} ${Version}\n' 'libnginx-mod-*' 2>/dev/null | \
      awk -v v="$NV" '$2 != v' | wc -l)
[ "$BAD" -eq 0 ] && echo "  ★ 全部一致（$NV）" || {
    echo "  ★★★★ $BAD 個模組版本不符："
    dpkg-query -W -f='${Package} ${Version}\n' 'libnginx-mod-*' | \
      awk -v v="$NV" '$2 != v {print "    " $0}'
}

echo -e "\n【★★★ 檔案完整性】"
NONPKG=0
for so in /usr/lib/nginx/modules/*.so; do
    dpkg -S "$so" >/dev/null 2>&1 || { echo "  ★★★★ 非套件: $so"; NONPKG=$((NONPKG+1)); }
done
[ "$NONPKG" -eq 0 ] && echo "  ★ 全部來自套件管理"

W=$(find /usr/lib/nginx/modules/ -type f -perm /go+w 2>/dev/null | wc -l)
[ "$W" -eq 0 ] && echo "  ★ 權限正確" || echo "  ★★★★ $W 個模組可被非 root 寫入"

echo -e "\n【★★★ 載入但未使用】"
/usr/local/bin/nginx-module-audit 2>/dev/null | \
  sed -n '/載入但未使用/,/已使用/p' | grep '★★★★' | sed 's/^/  /' || \
  echo "  ★ 無"
EOF
$ sudo chmod +x /usr/local/bin/nginx-security-check

$ sudo tee /etc/cron.d/nginx-security >/dev/null <<'EOF'
0 8 * * 1 root /usr/local/bin/nginx-security-check 2>&1 | \
  mail -s "NGINX 模組安全檢查 $(hostname)" admin@example.gov.tw
EOF
```

---

## 速查表

### ★★★★ 載入位置與順序

```nginx
# /etc/nginx/nginx.conf —— ★★★★ main context（http 之前）
include /etc/nginx/modules-enabled/*.conf;
events { ... }
http { ... }
```

```
★★★★ 錯誤：load_module directive is specified too late
      → 放在 http 之後了

★★★ 檔名的數字前綴決定順序：
  10-mod-http-geoip2.conf              ← 先（提供變數）
  15-mod-http-ssl-fingerprint.conf
  50-mod-http-shield.conf
  70-mod-http-brotli-filter.conf       ← filter 類較後
★★★ 相依的模組要先載入
```

### 管理

```bash
apt-cache search '^libnginx-mod-'                      # ★★★ 列出可用的
sudo apt install libnginx-mod-http-cache-turbo
dpkg -L libnginx-mod-http-cache-turbo                  # 裝了什麼
sudo nginx -T | grep '^load_module'                    # ★★★ 目前載入的
ls -l /etc/nginx/modules-enabled/                      # ★★★ 啟用的

# ★★★ 停用（不移除套件）
sudo rm /etc/nginx/modules-enabled/50-mod-http-xxx.conf
★★★★ 先移除設定檔中該模組的指令！
```

### ★★★★ 版本綁定

```bash
apt-cache show libnginx-mod-http-xxx | grep Depends
# Depends: nginx (= 1.29.2-1~noble)     ★★★★ 精確相等

# ★★★★ 檢查一致性
NV=$(dpkg-query -W -f='${Version}' nginx)
dpkg-query -W -f='${Package} ${Version}\n' 'libnginx-mod-*' | awk -v v="$NV" '$2 != v'

# ★★★ 正式環境鎖版本
sudo apt-mark hold nginx 'libnginx-mod-*'
```

### ★★★ 升級流程

```
① 測試環境先升級並完整驗證
② 備份設定 + 記錄套件版本（回退用）
③ ★★★★ 檢查所有模組都有對應的新版本（apt -s upgrade）
④ 一起升級 nginx 與所有模組
⑤ nginx -t → reload
⑥ ★★★★ nginx-module-verify 完整功能驗證
```

### ★★★★ 只裝需要的

```
理由：記憶體 / ★★★★ 攻擊面 / 升級複雜度 / 啟動速度
sudo nginx-module-audit          # ★★★★ 找出載入但沒用的
```

### ★★★ 常見錯誤

```
too late              → load_module 放錯位置
version X instead Y   → ★★★★ 版本不符，一起升級
unknown directive     → 模組沒載入
unknown variable      → ★★★ 相依模組順序錯
undefined symbol      → 編譯參數不相容
kept back             → ★★★★ 某模組沒有新版本
```

### 安全

```bash
ls -l /usr/lib/nginx/modules/                 # ★★★ root:root 644
find /usr/lib/nginx/modules/ -perm /go+w      # ★★★★ 應該沒有輸出
for so in /usr/lib/nginx/modules/*.so; do dpkg -S "$so" >/dev/null || echo "非套件: $so"; done
sudo nginx-security-check
```

---

## 練習題

> [!question]- 練習 1：載入位置 ★★★★
> 1. **把 `load_module` 放進 `http` 區塊** → `nginx -t` 說什麼？
> 2. **放進 `server` 區塊** → 呢？
> 3. **移到最上層** → 通過了嗎？
> 4. **`nginx -T | grep load_module`** → 順序是什麼？
> 5. **改一個模組的數字前綴** → 順序變了嗎？
> 6. **為什麼 filter 模組的順序重要？**

> [!question]- 練習 2：版本綁定 ★★★★
> 1. **`apt-cache show libnginx-mod-http-xxx | grep Depends`** → 相依是什麼？
> 2. **`dpkg-query` 列出 nginx 與所有模組的版本** → 一致嗎？
> 3. **手動下載一個舊版的模組 .so 覆蓋** → `nginx -t` 說什麼？
> 4. **錯誤訊息中的數字代表什麼？**
> 5. **恢復並用 `apt --reinstall` 修復**
> 6. **`apt-mark hold` 鎖住版本並試著 upgrade**

> [!question]- 練習 3：模組稽核 ★★★
> 1. **安裝 5 個以上的模組但只在設定中用 2 個**
> 2. **執行 `nginx-module-audit`** → 找出幾個沒用的？
> 3. **記錄 nginx 的記憶體用量**
> 4. **停用沒用的模組並 reload** → 記憶體變化？
> 5. **`nginx -T | grep -c load_module`** → 剩幾個？
> 6. **停用一個【設定檔還在用】的模組** → 會怎樣？

> [!question]- 練習 4：相依順序 ★★★
> 1. **安裝 geoip2 與一個用到它變數的模組**
> 2. **把 geoip2 的前綴改成 90（最後載入）**
> 3. **`nginx -t`** → 錯誤訊息是什麼？
> 4. **改回 10** → 通過了嗎？
> 5. **列出你環境中所有的模組相依關係**
> 6. **畫出正確的載入順序**

> [!question]- 練習 5：升級演練 ★★★★
> 1. **記錄目前所有套件的版本**
> 2. **執行 `nginx-upgrade`**
> 3. **升級後 `nginx-module-verify`** → 全部通過嗎？
> 4. **故意讓一個模組版本不符**（降級單一模組）→ `nginx -t` 說什麼？
> 5. **用記錄的版本清單回退**
> 6. **寫一份正式環境的升級 SOP**

---

## 小測驗

Q1. **動態模組和靜態編譯的五個差異**？動態模組的關鍵限制是什麼？

Q2. **`load_module` 必須放在哪裡**？放錯的錯誤訊息是什麼？

Q3. **模組的載入順序為什麼重要**？舉兩個例子。

Q4. **`module version 1029002 instead of 1029003` 是什麼問題**？怎麼解決？

Q5. **升級 nginx 時 `apt` 說 kept back，最可能的原因**？

Q6. **升級的三個風險**？哪一個最危險？

Q7. **為什麼不該「把模組全部裝起來備用」**？（四個理由）

Q8. **停用一個模組前必須先做什麼**？不做會怎樣？

Q9. **`--with-compat` 這個編譯參數的意義**？

Q10. **模組相關的安全檢查有哪些**？

> [!question]- 測驗答案
> **Q1.** ①**產出** —— 靜態編進 nginx 執行檔，動態是獨立的 `.so`；
> ②**★★★ 增減模組** —— 靜態要**重新編譯整個 nginx**，
> 動態只要 `apt install` + 一行 `load_module`；
> ③**★★★ 記憶體** —— 靜態全部載入，動態**只載入需要的**；
> ④**啟動速度** —— 靜態略快（動態要 `dlopen`）；
> ⑤**★★★★ 版本相依** —— 動態模組**必須與主程式版本完全相符**。
> **★★★★ 關鍵限制**：
> 動態模組**必須和 nginx 主程式用相同的版本與相容的編譯參數建置** ——
> nginx 一升級，**所有模組都要跟著升級**，
> 否則 `nginx -t` 會報 `module version X instead of Y` 而**完全起不來**。
> 另外**不是所有模組都支援動態載入**（要修改 core 的就不行）。
>
> **Q2.** **★★★★ 必須放在 nginx.conf 的 main context（最上層，`http` 區塊之前）**。
> ```nginx
> user www-data;
> worker_processes auto;
> include /etc/nginx/modules-enabled/*.conf;   # ★★★★ 這裡
> events { ... }
> http { ... }
> ```
> **放錯的錯誤訊息**：
> ```
> nginx: [emerg] "load_module" directive is specified too late in nginx.conf:42
> # ★★★ 意思是已經進入 http 區塊了
>
> nginx: [emerg] "load_module" directive is not allowed here in app.conf:1
> # ★★★ 放在 server 或 location 裡面
> ```
> **原因**：模組必須在 nginx 解析其他設定**之前**就載入完成，
> 否則模組提供的指令（`autocert`、`shield`）在解析時還不存在，
> 會被當成 `unknown directive`。
> Debian/Ubuntu 的慣例是把載入設定放在 `/etc/nginx/modules-enabled/*.conf`，
> 由 nginx.conf 的 `include` 引入。
>
> **Q3.** **兩個原因**：
> ①**★★★ 過濾模組（filter）形成一個鏈，而「後載入的先執行」** ——
> 順序影響回應的處理流程。
> **例一：壓縮 vs 精簡** —— strip（精簡）應該在壓縮**之前**處理內容，
> 順序錯了就變成「壓縮後的位元組被拿去精簡」（無意義且可能損壞）。
> **例二：SSI vs 壓縮** —— SSI 必須在壓縮之前處理，否則處理的是壓縮後的資料。
> ②**★★★ 模組間的相依** ——
> 有些模組提供**變數**給其他模組用：
> `geoip2` 提供 `$geoip2_asn`、
> `ssl-fingerprint` 提供 `$ssl_fingerprint_ja4`，
> **sentinel 用到這些變數，所以必須在它們之後載入**。
> 順序錯了會報 `unknown "geoip2_asn" variable`。
> **控制方式**：`/etc/nginx/modules-enabled/` 中**檔名的數字前綴**。
>
> **Q4.** **★★★★ 模組的版本和 nginx 主程式不符**，nginx 完全無法啟動。
> 數字是 nginx 的內部版本編號：`1029002` = 1.29.2，`1029003` = 1.29.3 ——
> 訊息的意思是「這個模組是為 1.29.2 建置的，但你的 nginx 是 1.29.3」。
> **原因**：
> ①升級了 nginx 但某個模組沒跟著升級（手動裝的模組最常見）；
> ②從不同來源混用模組與主程式。
> **解決**：
> ```bash
> # ★★★ 一起升級
> sudo apt install -y nginx $(dpkg-query -W -f='${Package} ' 'libnginx-mod-*')
> # ★★★ 檢查一致性
> NV=$(dpkg-query -W -f='${Version}' nginx)
> dpkg-query -W -f='${Package} ${Version}\n' 'libnginx-mod-*' | awk -v v="$NV" '$2 != v'
> ```
> **緊急處理**：把有問題的模組的 `load_module` 註解掉先讓 nginx 起來
> （但設定檔中該模組的指令也要一起處理）。
>
> **Q5.** **★★★★ 某個動態模組還沒有對應的新版本**。
> 因為模組的相依是 `Depends: nginx (= 1.29.2-1~noble)`（**精確相等**），
> 如果 nginx 有 1.29.3 但某個模組只到 1.29.2，
> **apt 無法同時滿足兩邊的相依**，於是把 nginx 標成 `kept back`（保留不升級）。
> **這其實是保護機制** —— 強制升級會導致版本不符讓 nginx 起不來。
> **檢查**：
> ```bash
> sudo apt-get -s upgrade nginx 2>&1 | grep -A5 'kept back'
> apt-cache policy libnginx-mod-http-xxx   # 看候選版本
> ```
> **三個處理方式**：
> ①**等套件庫更新**（通常維護者會很快補上）；
> ②**先移除卡住的模組**（如果不是必要的）；
> ③**維持現狀**並訂閱套件庫的公告。
> 這也是「只裝需要的模組」的實際理由 —— 裝越多，卡住的機率越高。
>
> **Q6.** ①**★★★★ 某個模組還沒有新版本** —— apt kept back，
> 強制升級會讓 nginx 起不來；
> ②**★★★ 新版本的指令語法變了** —— `nginx -t` 失敗，
> 升級前應該先看 `apt changelog nginx`；
> ③**★★★★ 模組的行為變了但語法沒變** —— **這個最危險**。
> `nginx -t` 通過、服務正常啟動、看起來一切都好，
> **但功能的行為已經不同了** ——
> 例如快取的 key 計算方式改了（命中率暴跌）、
> shield 的某個分類預設從 detect 變成 block（開始擋正常使用者）、
> 壓縮的預設等級改了（CPU 飆高）。
> **這種問題可能過好幾天才被發現**。
> **對策**：**升級後一定要跑完整的功能驗證**（`nginx-module-verify`），
> 而且**先在測試環境驗證**，正式環境用 `apt-mark hold` 鎖版本並排定維護窗。
>
> **Q7.** ①**★★★ 記憶體** —— 每個載入的模組在**每個 worker** 都佔記憶體，
> 100 個模組 × 8 個 worker 是明顯的浪費；
> ②**★★★★ 攻擊面** —— 每個模組都是額外的程式碼，
> 模組本身可能有漏洞（**第三方模組的審查通常比 nginx core 少得多**），
> 而且**載入了但沒用到的模組一樣會執行初始化，一樣有風險**；
> ③**★★★ 升級的複雜度** —— 裝越多，
> 「某個模組還沒有新版本」導致**整個 nginx 卡住不能升級**的機率越高，
> 這會讓你無法及時套用安全修補；
> ④**★★ 啟動速度** —— 每個模組都要 `dlopen`。
> **★★★★ 原則：現在用得到的才裝**，
> 定期用 `nginx-module-audit` 找出「載入但設定中沒有使用」的模組並清掉。
>
> **Q8.** **★★★★ 必須先移除設定檔中該模組提供的所有指令**。
> 如果直接刪掉 `/etc/nginx/modules-enabled/50-mod-http-cache-turbo.conf` 就 reload：
> ```
> nginx: [emerg] unknown directive "cache_turbo" in /etc/nginx/sites-enabled/app:24
> ```
> **nginx 完全起不來，服務中斷**。
> **正確順序**：
> ①**先檢查設定中有沒有用到**：
> ```bash
> sudo nginx -T 2>/dev/null | grep -v '^load_module' | grep -cE '^\s*cache_turbo'
> # ★★★★ 大於 0 = 還在用，不能停用
> ```
> ②移除或註解掉那些指令 → `nginx -t` 確認；
> ③再刪掉 `modules-enabled` 的符號連結；
> ④`nginx -t` → `reload`；
> ⑤確定不用的話才 `apt remove` 移除套件。
> **同樣的道理適用於「從 MyGuard 退回官方 nginx」** ——
> 要先把 `autocert on;` 這類指令換回 certbot 的做法。
>
> **Q9.** **`--with-compat` 啟用「動態模組的相容 ABI」**。
> **沒有這個參數時**：動態模組必須用**完全相同的編譯參數**建置，
> 任何一個 `--with-xxx` 不同就會載入失敗
> （`undefined symbol` 或 module version 錯誤）。
> **有 `--with-compat` 時**：nginx 提供一個**穩定的模組介面**，
> 只要主版本相符，用不同編譯參數建置的模組也能載入 ——
> **這讓「第三方套件庫提供模組給官方 nginx 用」成為可能**。
> **檢查**：
> ```bash
> nginx -V 2>&1 | tr ' ' '\n' | grep -- --with-compat
> ```
> **注意**：`--with-compat` 只放寬了**編譯參數**的限制，
> **版本仍然必須相符**（模組還是為特定版本建置的）。
> 官方 nginx.org 的套件和 MyGuard 的套件都有這個參數。
>
> **Q10.** **五項**：
> ①**★★★★ 檔案權限** —— `.so` 必須是 `root:root 644`，
> **可被非 root 寫入 = 攻擊者可以植入程式碼並在 nginx 重啟時執行**：
> ```bash
> find /usr/lib/nginx/modules/ -type f -perm /go+w    # ★★★★ 應該沒有輸出
> ```
> ②**★★★ 確認模組來自套件管理** ——
> 手動放進去的 `.so` 沒有簽章驗證也沒有安全更新：
> ```bash
> for so in /usr/lib/nginx/modules/*.so; do dpkg -S "$so" >/dev/null || echo "非套件: $so"; done
> ```
> ③**★★★★ 版本一致性與安全更新** ——
> 模組有漏洞時，nginx 主程式沒事也一樣危險，
> 定期 `apt list --upgradable | grep nginx`；
> ④**★★★ 清掉未使用的模組**（`nginx-module-audit`）——
> 載入了就有風險；
> ⑤**★★ 檔案完整性監控**（AIDE/Wazuh FIM）——
> 監控 `/usr/lib/nginx/modules/` 與 `/etc/nginx/modules-enabled/` 的變更並告警。

---

## 延伸閱讀

- [[060-02-05-01-guide-MyGuard-MyGuard套件庫介紹]] — 套件庫與風險評估
- [[060-02-02-01-guide-Nginx-安裝與目錄結構]] — NGINX 的目錄結構
- [[060-02-05-08-guide-MyGuard-MyGuard實戰組合]] — 完整的實戰配置
- [[060-02-05-03-guide-MyGuard-autocert自動憑證模組]] — autocert 的載入
- [[060-02-05-04-guide-http-shield攻擊攔截]] — shield 的載入
- [[020-01-14-guide-Linux-套件管理]] — APT 的相依與 pinning
