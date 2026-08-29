---
title: "MyGuard 套件庫介紹"
desc: "強化版 NGINX 與 Angie 的第三方 APT 套件庫，以及它解決了什麼問題"
aliases: [MyGuard, deb.myguard.nl, myguard-labs, 第三方套件庫]
tags: [群組/軟體與開發工具, 服務/nginx, 服務/myguard]
category: MyGuard與Angie
difficulty: 入門
status: 完成
distro: [ubuntu]
prerequisites: ["[[060-02-02-01-guide-Nginx-安裝與目錄結構]]", "[[020-01-14-guide-Linux-套件管理]]"]
updated: 2026-08-28
---

# MyGuard 套件庫介紹

> [!abstract] 這篇你會學到
> - **★★★★ MyGuard 是什麼、不是什麼**（★ 名字容易誤解）
> - 它解決了官方套件庫的什麼問題
> - **★★★ 加入套件庫的正確流程**（含 GPG 金鑰驗證）
> - 支援的發行版與 codename
> - **★★★★ 第三方套件庫的風險評估**（★ 機關環境必讀）
> - APT pinning 與版本控制

> [!warning] 未實機驗證 ★★★
> ```
> ★★★ 本章的內容依據 2026 年 8 月的官方文件撰寫。
>
> ★★★★ 動筆前請務必到 https://deb.myguard.nl/how-to-use/
>       確認【當前的套件庫路徑、GPG 金鑰指紋、支援的 codename】
>
> ★★ 第三方套件庫的路徑與金鑰可能隨時變更。
> ```

## 前置知識

- [[060-02-02-01-guide-Nginx-安裝與目錄結構]] — NGINX 的基礎
- [[020-01-14-guide-Linux-套件管理]] — APT 與套件庫
- [[020-02-03-03-cmd-標準化-第三方APT套件庫實務]] — 第三方套件庫的通用做法

---

## ★★★★ MyGuard 不是什麼

```
★★★★ 【最重要的釐清】

  MyGuard 這個名字聽起來像端點防護軟體，
  ★★★★ 但它【不是】：
    ✗ 不是防毒軟體
    ✗ 不是 EDR / 端點防護代理程式
    ✗ 不是資安監控平台
    ✗ 和任何商業的「MyGuard」產品沒有關係

★★★ 它【是】：
  ✓ 一個【第三方的 Debian / Ubuntu APT 套件庫】
  ✓ 由 myguard-labs（GitHub 組織）維護
  ✓ 提供【強化版的 NGINX 與 Angie】
  ✓ 以及 100 多個動態模組

★★★ 網址：https://deb.myguard.nl
★★★ 原始碼：https://github.com/myguard-labs
★★★ 問題追蹤：https://github.com/eilandert/deb.myguard.nl
```

---

## ★★★ 它解決了什麼問題

```
★★★★ 核心問題：【官方套件庫的 NGINX 功能太少、太舊】

  ┌────────────────────┬──────────────┬──────────────┬──────────────┐
  │ 功能               │ Ubuntu 官方   │ nginx.org 官方│ ★★★ MyGuard  │
  ├────────────────────┼──────────────┼──────────────┼──────────────┤
  │ 版本               │ 落後 1~2 年   │ mainline 較新 │ ★★ mainline  │
  │ ★★★ HTTP/3 (QUIC)  │ ✗            │ ✓（新版）    │ ✓            │
  │ ★★★ kTLS           │ ✗            │ ✗            │ ✓            │
  │ Brotli 壓縮        │ ✗            │ ✗            │ ✓            │
  │ ★★ Zstandard 壓縮  │ ✗            │ ✗            │ ✓            │
  │ ★★★ ModSecurity v3 │ ✗            │ ✗            │ ✓            │
  │ Lua / NJS          │ 部分         │ NJS          │ ✓ 兩者       │
  │ ★★ 動態模組數量    │ ~10          │ ~15          │ ★★★ 100+     │
  │ ★★★★ 自製模組      │ ✗            │ ✗            │ ✓（見下）    │
  │ 更新頻率           │ 安全修補     │ 版本發布時   │ ★★ 每日重建  │
  └────────────────────┴──────────────┴──────────────┴──────────────┘

★★★ 典型的痛點：
  「我需要 HTTP/3 + ModSecurity + Brotli」
  → 官方套件庫：★★★★ 三個都沒有
  → 自己編譯：★★★ 要處理相依、每次更新都要重編、沒有安全更新
  → ★★★ MyGuard：apt install 就有
```

### ★★★★ 自製模組（本手冊的重點）

| 模組 | 作用 | 對應章節 |
| --- | --- | --- |
| **`autocert`** | **★★★★ NGINX 內建 ACME 客戶端**，`autocert on;` 就自動申請與續期，**不需要 certbot 與 cron** | [[060-02-05-03-guide-MyGuard-autocert自動憑證模組]] |
| **`http-shield`** | 攔截 SQLi、Log4Shell、Shellshock、RCE 鏈等已知攻擊 | [[060-02-05-04-guide-http-shield攻擊攔截]] |
| **`error-abuse`** | 對 4xx/5xx 濫用的來源限流與封鎖 | [[060-02-05-05-guide-error-abuse與sentinel]] |
| **`sentinel`** | **★★ 用戶端信譽評分與 AI 爬蟲 tarpit**（實驗中） | [[060-02-05-05-guide-error-abuse與sentinel]] |
| **`cache-turbo`** | 共享記憶體的邊緣快取、stale-while-revalidate | [[060-02-05-06-guide-cache-turbo與壓縮模組]] |
| **`strip-filter`** | HTML／CSS／JS／JSON 回應體精簡 | [[060-02-05-06-guide-cache-turbo與壓縮模組]] |
| **`zstd`** | Zstandard 壓縮 | [[060-02-05-06-guide-cache-turbo與壓縮模組]] |

> [!info] 本手冊的範圍界線 ★★★
> ```
> ★★★ myguard-labs 也提供【郵件相關】的套件：
>   · Mailstrix（郵件惡意程式掃描）
>   · rspamd 外掛
>   · ViMbAdmin（虛擬信箱管理）
>
> ★★★★ 這些【不寫入本手冊】—— 已確定不納入郵件伺服器主題。
> ```

---

## ★★★★ 第三方套件庫的風險評估

> [!danger] 機關環境必讀 ★★★★
> ```
> ★★★★ 加入第三方套件庫 = 【把 root 權限交給對方】
>
>   APT 套件庫中的套件可以：
>     · 安裝任意檔案到系統的任何位置
>     · ★★★★ 執行 maintainer script（preinst/postinst）→ 【以 root 執行任意程式碼】
>     · 取代系統既有的套件
>
>   → ★★★★ 這不是「多裝一個程式」，是【信任鏈的擴張】
>
> ★★★ 評估的六個問題：
>   ① 【維護者是誰？】可以追溯嗎？有公開的身分嗎？
>   ② ★★★ 【原始碼公開嗎？】能不能自己審查與重建？
>   ③ ★★★ 【更新頻率與安全回應？】有 CVE 時多久修補？
>   ④ ★★★★ 【如果套件庫消失了怎麼辦？】有退路嗎？
>   ⑤ ★★ 【機關的資安政策允許嗎？】需要簽核嗎？
>   ⑥ ★★★ 【值得嗎？】自己編譯或用官方版本的代價是什麼？
>
> ★★★★ MyGuard 的狀況：
>   ✓ 原始碼公開（github.com/myguard-labs）
>   ✓ GPG 簽章
>   ✓ 有問題追蹤（GitHub issues）
>   ✓ 每日重建（★ 更新快）
>   ★★ 但：單一維護者、非官方、不在任何發行版的支援範圍內
>
> ★★★★ 本手冊的建議：
>   · 【開發／測試環境】★★ 可以用，體驗新功能
>   · 【正式環境】★★★ 要有明確的理由（HTTP/3 / ModSecurity / autocert）
>     並且【經過資安簽核】、【有退場方案】
>   · ★★★★ 【關鍵基礎設施】建議用官方套件庫 + 自行編譯需要的模組
> ```

```bash
# ★★★ 退場方案：怎麼移除 MyGuard 回到官方版本
$ sudo apt remove --purge nginx angie 'libnginx-mod-*'
$ sudo rm -f /etc/apt/sources.list.d/myguard*.list \
             /etc/apt/sources.list.d/myguard*.sources \
             /etc/apt/keyrings/deb.myguard.nl.gpg \
             /etc/apt/preferences.d/myguard
$ sudo apt update
$ sudo apt install nginx                      # ★★ 回到官方版本
#   ★★★★ 但注意：設定檔中用到的自製模組指令（autocert 等）要先移除
#     → 否則 nginx -t 會失敗
```

---

## ★★★ 加入套件庫

> [!warning] 動筆前確認 ★★★★
> ```
> ★★★★ 以下的路徑與金鑰以【2026 年 8 月】的官方文件為準。
>       執行前請到 https://deb.myguard.nl/how-to-use/ 核對。
> ```

### 方法一：★★★ 手動加入（推薦，看得見每一步）

```bash
# ═══ ★★★【1】前置 ═══
$ sudo apt update
$ sudo apt install -y curl gnupg ca-certificates lsb-release
$ CODENAME=$(lsb_release -cs)
$ echo "$CODENAME"
noble                                     # ★ Ubuntu 24.04

# ═══ ★★★★【2】匯入 GPG 金鑰 ═══
$ sudo install -d -m 0755 /etc/apt/keyrings
$ curl -fsSL https://deb.myguard.nl/deb.myguard.nl.gpg \
    | sudo tee /etc/apt/keyrings/deb.myguard.nl.gpg >/dev/null
$ sudo chmod 644 /etc/apt/keyrings/deb.myguard.nl.gpg

# ★★★★ 驗證金鑰指紋（★ 這一步不能跳）
$ gpg --show-keys --with-fingerprint /etc/apt/keyrings/deb.myguard.nl.gpg
#   ★★★★ 把顯示的指紋和官網公布的比對
#   → 不一致 = 可能被中間人攻擊，立刻停止

# ═══ ★★★【3】加入套件庫 ═══
$ echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/deb.myguard.nl.gpg] \
https://deb.myguard.nl/apt/dists/$CODENAME $CODENAME main" \
  | sudo tee /etc/apt/sources.list.d/myguard.list

#   ★★★ 只要 NGINX（不要其他套件）
$ echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/deb.myguard.nl.gpg] \
https://deb.myguard.nl/apt/nginx/$CODENAME $CODENAME main" \
  | sudo tee /etc/apt/sources.list.d/myguard-nginx.list

#   ★★★ 只要 Angie
$ echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/deb.myguard.nl.gpg] \
https://deb.myguard.nl/apt/angie/$CODENAME $CODENAME main" \
  | sudo tee /etc/apt/sources.list.d/myguard-angie.list

# ═══ ★★★【4】更新並驗證 ═══
$ sudo apt update
Get:5 https://deb.myguard.nl/apt/dists/noble noble InRelease [2,458 B]
Get:6 https://deb.myguard.nl/apt/dists/noble noble/main amd64 Packages [128 kB]
#   ★★★ 沒有 GPG 錯誤 = 簽章驗證通過

#   ★★★★ 有錯誤的話：
# W: GPG error: ... NO_PUBKEY ...
#   → ★★★ 金鑰沒匯入成功，回到步驟 2
# E: The repository ... does not have a Release file
#   → ★★★ codename 不支援，見下方
```

### 方法二：bootstrap 套件（快但看不見細節）

```bash
# ★★ 官方提供的一鍵設定
$ curl -fsSLO https://deb.myguard.nl/myguard.deb

# ★★★★ 安裝前一定要檢查內容！
$ dpkg-deb --info myguard.deb                     # ★★★ 套件資訊
$ dpkg-deb --contents myguard.deb                 # ★★★ 會裝哪些檔案
$ dpkg-deb --control myguard.deb /tmp/ctl && ls /tmp/ctl/
$ cat /tmp/ctl/postinst                           # ★★★★ 看 postinst 做了什麼！
#   → ★★★★ maintainer script 是【以 root 執行】的，一定要看過

$ sudo dpkg -i myguard.deb
$ sudo apt update

# ★★ 它會自動設定：APT source、GPG 金鑰、pinning
$ ls /etc/apt/sources.list.d/ /etc/apt/preferences.d/ /etc/apt/keyrings/
```

> [!danger] `curl | sh` 與未經檢查的 `.deb` ★★★★
> ```
> ★★★★ 「下載一個 .deb 然後 dpkg -i」和「curl | sh」的風險是一樣的：
>   → maintainer script（preinst / postinst / prerm / postrm）
>     【以 root 執行任意程式碼】
>
> ★★★ 檢查的三個步驟：
>   $ dpkg-deb --contents myguard.deb          # 會裝什麼檔案
>   $ dpkg-deb --control myguard.deb /tmp/ctl  # 解出控制檔
>   $ cat /tmp/ctl/{preinst,postinst,prerm,postrm} 2>/dev/null
>
> ★★★★ 機關環境建議用【方法一手動設定】
>   → 每一步都看得見，也符合稽核要求
> ```

### 支援的發行版

```bash
# ★★★ 檢查你的 codename 是否有支援
$ CODENAME=$(lsb_release -cs)
$ curl -fsSI "https://deb.myguard.nl/apt/dists/$CODENAME/InRelease" | head -1
HTTP/2 200                                # ★★★ 有支援

$ curl -fsSI "https://deb.myguard.nl/apt/dists/focal/InRelease" | head -1
HTTP/2 404                                # ★★★ 不支援

# ★★ 列出所有支援的 codename
$ curl -fsSL https://deb.myguard.nl/apt/dists/ | grep -oP 'href="\K[a-z]+(?=/")'
```

```
★★★ 2026 年 8 月時支援的（★ 請自行確認當前狀況）：

  Ubuntu：  noble (24.04 LTS)、jammy (22.04 LTS)、resolute
  Debian：  trixie (13)、bookworm (12)、bullseye (11)

★★★★ 不支援時的處理：
  ① 升級系統到支援的版本
  ② ★★ 用官方套件庫 + 自行編譯需要的模組
  ③ ★★ 用官方提供的 Docker 映像（見 [[060-02-05-08-guide-MyGuard-MyGuard實戰組合]]）
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```
> ★★★★ MyGuard 【只提供 Debian / Ubuntu 的套件】，沒有 RPM。
>
> ★★★ RHEL 系的替代方案：
>   ① 官方的 nginx.org RPM 套件庫（★ 有 mainline 與 HTTP/3）
>      $ sudo dnf install -y https://nginx.org/packages/mainline/centos/9/x86_64/RPMS/...
>   ② ★★ Angie 官方的 RPM 套件庫
>      $ curl -o /etc/yum.repos.d/angie.repo https://angie.software/angie/rhel/9/angie.repo
>   ③ ★★★ 自行編譯（★ 完整可控，但要自己維護）
>   ④ ★★ 用 MyGuard 的 Docker 映像（★ 不管主機是什麼發行版）
> ```

---

## ★★★ APT pinning 與版本控制

```
★★★★ 為什麼需要 pinning：

  加入 MyGuard 之後，它的 nginx 版本比官方新
  → ★★★ apt 會【自動用 MyGuard 的版本】取代官方的
  → ★★ 可能不是你要的（★ 尤其是你只想要某幾個套件時）

★★★ 三種策略：
  ① ★★★ 只用 MyGuard 的 nginx，其他都用官方
  ② ★★ 完全優先 MyGuard
  ③ ★★★★ 鎖定特定版本（★ 正式環境建議）
```

```bash
# ═══ ★★★ 策略一：只讓 nginx 相關的套件用 MyGuard ═══
$ sudo tee /etc/apt/preferences.d/myguard >/dev/null <<'EOF'
# ★★★ MyGuard 的 nginx 與模組：高優先
Package: nginx nginx-* libnginx-mod-*
Pin: origin deb.myguard.nl
Pin-Priority: 700

# ★★★ 其他所有套件：低於官方（★ 避免意外取代系統套件）
Package: *
Pin: origin deb.myguard.nl
Pin-Priority: 100
EOF

# ═══ ★★ 策略二：完全優先 ═══
$ sudo tee /etc/apt/preferences.d/myguard >/dev/null <<'EOF'
Package: *
Pin: origin deb.myguard.nl
Pin-Priority: 700
EOF

# ═══ ★★★★ 策略三：鎖定特定版本（正式環境）═══
$ apt policy nginx
nginx:
  Installed: 1.29.1-1~noble
  Candidate: 1.29.2-1~noble
  Version table:
     1.29.2-1~noble 700
        700 https://deb.myguard.nl/apt/nginx/noble noble/main amd64 Packages
 *** 1.29.1-1~noble 700
        700 https://deb.myguard.nl/apt/nginx/noble noble/main amd64 Packages
        100 /var/lib/dpkg/status

$ sudo apt-mark hold nginx 'libnginx-mod-*'
$ apt-mark showhold
nginx
#   ★★★ 之後 apt upgrade 不會動它
#   ★★ 要更新時：sudo apt-mark unhold nginx && sudo apt install nginx

# ★★★ 或釘住確切的版本
$ sudo tee /etc/apt/preferences.d/myguard-version >/dev/null <<'EOF'
Package: nginx
Pin: version 1.29.1-1~noble
Pin-Priority: 1001
EOF
#   ★★★★ Priority > 1000 表示【即使是降版也要用這個版本】

# ═══ ★★★ 驗證 pinning 生效 ═══
$ apt-cache policy nginx
$ apt policy | grep -A2 myguard
```

```bash
# ★★★ 看某個套件會從哪裡安裝
$ apt-cache policy libnginx-mod-http-brotli
$ apt list -a nginx

# ★★★ 模擬安裝（★ 不實際執行）
$ sudo apt install -s nginx
$ sudo apt install --dry-run nginx | grep -E '^(Inst|Conf)'

# ★★★★ 檢查有沒有意外取代系統套件
$ sudo apt list --upgradable 2>/dev/null | grep myguard
$ apt-cache policy $(dpkg -l | awk '/^ii/{print $2}' | head -50) 2>/dev/null | \
    grep -B3 'deb.myguard.nl' | grep '^[a-z]' | head
```

---

## 完整實戰範例：從零到可用

```bash
#!/usr/bin/env bash
# ★★★ /usr/local/bin/setup-myguard —— 安全地加入 MyGuard 套件庫
set -euo pipefail

KEYRING=/etc/apt/keyrings/deb.myguard.nl.gpg
KEY_URL=https://deb.myguard.nl/deb.myguard.nl.gpg
BASE=https://deb.myguard.nl/apt
CODENAME=$(lsb_release -cs)
MODE="${1:-nginx}"          # nginx | angie | all

echo "═══ 加入 MyGuard 套件庫（$MODE / $CODENAME）═══"

# ═══ ★★★【1】檢查支援 ═══
echo -e "\n【1】檢查 codename 支援"
case "$MODE" in
    nginx) URL="$BASE/nginx/$CODENAME" ;;
    angie) URL="$BASE/angie/$CODENAME" ;;
    all)   URL="$BASE/dists/$CODENAME" ;;
    *)     echo "★★ 用法: setup-myguard [nginx|angie|all]"; exit 1 ;;
esac

if ! curl -fsSI "$URL/InRelease" >/dev/null 2>&1 && \
   ! curl -fsSI "$URL/Release" >/dev/null 2>&1; then
    echo "  ★★★★ $CODENAME 不在支援清單中"
    echo "  ★ 可用的："
    curl -fsSL "$BASE/dists/" 2>/dev/null | grep -oP 'href="\K[a-z]+(?=/")' | sed 's/^/    /'
    exit 1
fi
echo "  ★ $CODENAME 有支援"

# ═══ ★★★★【2】GPG 金鑰 ═══
echo -e "\n【2】★★★ 匯入並驗證 GPG 金鑰"
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL "$KEY_URL" | sudo tee "$KEYRING" >/dev/null
sudo chmod 644 "$KEYRING"

echo "  ★★★★ 金鑰指紋（請與 https://deb.myguard.nl/how-to-use/ 比對）："
gpg --show-keys --with-fingerprint "$KEYRING" 2>/dev/null | sed 's/^/    /'
read -rp "  指紋正確嗎？[y/N] " a
[ "$a" = y ] || { sudo rm -f "$KEYRING"; echo "  ★★ 已中止並移除金鑰"; exit 1; }

# ═══ ★★★【3】套件庫 ═══
echo -e "\n【3】加入套件庫"
sudo tee "/etc/apt/sources.list.d/myguard-$MODE.list" >/dev/null <<EOF
deb [arch=amd64 signed-by=$KEYRING] $URL $CODENAME main
EOF
echo "  ★ /etc/apt/sources.list.d/myguard-$MODE.list"

# ═══ ★★★★【4】pinning ═══
echo -e "\n【4】★★★ 設定 pinning（★ 只讓 nginx/angie 相關的套件用 MyGuard）"
sudo tee /etc/apt/preferences.d/myguard >/dev/null <<'EOF'
Package: nginx nginx-* angie angie-* libnginx-mod-* libangie-mod-*
Pin: origin deb.myguard.nl
Pin-Priority: 700

# ★★★★ 其他套件低優先，避免意外取代系統套件
Package: *
Pin: origin deb.myguard.nl
Pin-Priority: 100
EOF
echo "  ★ /etc/apt/preferences.d/myguard"

# ═══ ★★★【5】更新 ═══
echo -e "\n【5】更新套件索引"
sudo apt update 2>&1 | grep -E 'myguard|GPG|Err|W:' || true

# ═══ ★★★【6】驗證 ═══
echo -e "\n【6】★★★ 驗證"
echo "  ── 套件庫狀態 ──"
apt policy 2>/dev/null | grep -A2 'deb.myguard.nl' | sed 's/^/    /' || \
  echo "    ★★★★ 套件庫沒有生效"

echo "  ── nginx 可用版本 ──"
apt policy nginx 2>/dev/null | sed 's/^/    /'

echo "  ── 可用的模組數量 ──"
N=$(apt-cache search '^libnginx-mod-' 2>/dev/null | wc -l)
echo "    $N 個動態模組"

echo -e "\n★ 完成。安裝："
echo "  sudo apt install nginx        # 強化版 NGINX"
echo "  sudo apt install angie        # Angie"
echo ""
echo "★★★ 退場方案（記錄下來）："
echo "  sudo apt remove --purge nginx 'libnginx-mod-*'"
echo "  sudo rm -f /etc/apt/sources.list.d/myguard-*.list \\"
echo "             /etc/apt/preferences.d/myguard $KEYRING"
echo "  sudo apt update && sudo apt install nginx"
```

```bash
$ sudo install -m755 setup-myguard.sh /usr/local/bin/setup-myguard
$ sudo setup-myguard nginx

═══ 加入 MyGuard 套件庫（nginx / noble）═══

【1】檢查 codename 支援
  ★ noble 有支援

【2】★★★ 匯入並驗證 GPG 金鑰
  ★★★★ 金鑰指紋（請與 https://deb.myguard.nl/how-to-use/ 比對）：
    pub   rsa4096 2023-...
          XXXX XXXX XXXX XXXX XXXX  XXXX XXXX XXXX XXXX XXXX
  指紋正確嗎？[y/N] y

【4】★★★ 設定 pinning
  ★ /etc/apt/preferences.d/myguard

【6】★★★ 驗證
  ── nginx 可用版本 ──
    nginx:
      Installed: (none)
      Candidate: 1.29.2-1~noble
  ── 可用的模組數量 ──
    104 個動態模組
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`NO_PUBKEY`** ★★★ | 金鑰沒匯入或路徑錯 | 重做金鑰步驟；確認 `signed-by=` 路徑 |
| **`does not have a Release file`** ★★★ | **codename 不支援** | 確認 `lsb_release -cs`；升級系統 |
| **`apt update` 很慢或逾時** ★★ | 網路／防火牆 | 確認能連 `deb.myguard.nl:443`；proxy |
| **裝了但版本沒變** ★★★ | **pinning 優先權太低** | `apt policy nginx` 看優先權 |
| **意外取代系統套件** ★★★★ | pinning 設太寬 | **`Package: *` 設 100** |
| **`nginx -t` 說 unknown directive** ★★★★ | **模組沒載入** | `load_module`；見 [[060-02-05-07-guide-MyGuard-動態模組管理]] |
| **升級後設定壞掉** ★★★ | 新版本的指令改了 | `apt-mark hold`；先在測試環境驗證 |
| **移除後 nginx 起不來** ★★★★ | 設定檔還在用自製模組 | **先移除 `autocert` 等指令再換回官方版** |
| 找不到 `libnginx-mod-*` ★★ | 只加了 nginx 的子套件庫 | 用 `dists/$CODENAME` 完整套件庫 |

### 排查

```bash
# 【1】★★★ 套件庫狀態
$ apt policy | grep -B1 -A2 myguard
$ ls -l /etc/apt/sources.list.d/ /etc/apt/keyrings/ /etc/apt/preferences.d/
$ cat /etc/apt/sources.list.d/myguard*.list

# 【2】★★★★ 金鑰
$ gpg --show-keys --with-fingerprint /etc/apt/keyrings/deb.myguard.nl.gpg
$ apt-key list 2>/dev/null | grep -A2 -i myguard    # ★ 舊做法，已淘汰

# 【3】★★★ 連通性
$ curl -fsSI https://deb.myguard.nl/apt/dists/$(lsb_release -cs)/InRelease | head -3
$ curl -fsSL https://deb.myguard.nl/apt/dists/ | grep -oP 'href="\K[a-z]+(?=/")'

# 【4】★★★★ pinning 是否生效
$ apt-cache policy nginx
$ apt-cache policy | head -30
$ sudo apt install -s nginx | grep -E '^Inst'

# 【5】★★ 已安裝的 MyGuard 套件
$ dpkg -l | awk '/^ii/{print $2}' | while read -r p; do
    apt-cache policy "$p" 2>/dev/null | grep -q 'deb.myguard.nl' && echo "$p"
  done

# 【6】★★★ 模組清單
$ apt-cache search '^libnginx-mod-' | sort | head -30
$ apt-cache search '^libnginx-mod-' | wc -l
$ dpkg -L nginx | grep -E 'modules|\.so$' | head
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★★
> ```
> ① ★★★★ 加入第三方套件庫 = 擴張信任鏈
>      → ★★★ 機關環境要走簽核程序
>      → ★★ 記錄：為什麼加、誰核准、退場方案
>
> ② ★★★★ 一定要驗證 GPG 指紋
>      → 不驗證 = 中間人可以推送任意套件
>      → ★★★ 指紋要和官網公布的比對
>
> ③ ★★★★ 檢查 .deb 的 maintainer script
>      → postinst 以 root 執行任意程式碼
>      → ★★★ dpkg-deb --control 解出來看過再裝
>
> ④ ★★★ pinning 限制範圍
>      → ★★★★ 不要讓第三方套件庫取代系統套件
>      → Package: * 設 Pin-Priority: 100
>
> ⑤ ★★★ 有退場方案
>      → 套件庫可能停止維護、可能被入侵
>      → ★★★★ 寫下移除的完整步驟並演練過
> ```

```bash
# ★★★★ 稽核：目前系統上有哪些套件來自第三方
$ sudo tee /usr/local/bin/audit-repos >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★★ 列出所有非官方來源的套件
echo "═══ 第三方套件稽核 $(date '+%F') ═══"

echo -e "\n【設定的套件庫】"
grep -rhoP '^deb\s+(\[[^]]*\]\s+)?\K\S+' \
    /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null | sort -u
grep -rhoP '^URIs:\s*\K\S+' /etc/apt/sources.list.d/*.sources 2>/dev/null | sort -u

echo -e "\n【★★★ GPG 金鑰】"
for k in /etc/apt/keyrings/* /etc/apt/trusted.gpg.d/*; do
    [ -f "$k" ] || continue
    printf '  %-45s ' "$(basename "$k")"
    gpg --show-keys --with-colons "$k" 2>/dev/null | \
      awk -F: '/^fpr/{print $10; exit}' || echo "?"
done

echo -e "\n【★★★★ 來自第三方的已安裝套件】"
dpkg-query -W -f='${Package}\n' | while read -r p; do
    src=$(apt-cache policy "$p" 2>/dev/null | \
          awk '/\*\*\*/{f=1;next} f&&/http/{print $2; exit}')
    case "$src" in
        ''|*archive.ubuntu.com*|*security.ubuntu.com*|*ports.ubuntu.com*|*deb.debian.org*) ;;
        *) printf '  %-40s %s\n' "$p" "$src" ;;
    esac
done

echo -e "\n【★★ 被 hold 的套件】"
apt-mark showhold | sed 's/^/  /' || echo "  （無）"
EOF
$ sudo chmod +x /usr/local/bin/audit-repos
$ sudo audit-repos

# ★★★ 定期檢查金鑰是否變更（★ 套件庫被入侵的徵兆）
$ sudo tee /etc/cron.d/repo-key-check >/dev/null <<'EOF'
0 6 * * * root /usr/local/bin/check-repo-keys 2>&1 | logger -t repo-key
EOF

$ sudo tee /usr/local/bin/check-repo-keys >/dev/null <<'EOF'
#!/usr/bin/env bash
# ★★★ 監控套件庫金鑰的指紋是否變更
BASELINE=/etc/apt/keyrings/.fingerprints
CURRENT=$(mktemp)
trap 'rm -f "$CURRENT"' EXIT

for k in /etc/apt/keyrings/*.gpg; do
    [ -f "$k" ] || continue
    fp=$(gpg --show-keys --with-colons "$k" 2>/dev/null | awk -F: '/^fpr/{print $10; exit}')
    echo "$(basename "$k") $fp"
done | sort > "$CURRENT"

if [ ! -f "$BASELINE" ]; then
    cp "$CURRENT" "$BASELINE"
    chmod 600 "$BASELINE"
    echo "★ 已建立基準"
    exit 0
fi

if ! diff -q "$BASELINE" "$CURRENT" >/dev/null; then
    echo "★★★★ 套件庫金鑰有變更！"
    diff "$BASELINE" "$CURRENT"
    exit 1
fi
echo "★ 金鑰未變更"
EOF
$ sudo chmod +x /usr/local/bin/check-repo-keys
$ sudo check-repo-keys
```

---

## 速查表

### ★★★★ MyGuard 是什麼

```
★★★★ 不是防毒 / EDR / 資安產品
★★★ 是【第三方 Debian/Ubuntu APT 套件庫】
     提供強化版 NGINX 與 Angie + 100 多個動態模組
網址：deb.myguard.nl　原始碼：github.com/myguard-labs
```

### 加入套件庫

```bash
CODENAME=$(lsb_release -cs)
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://deb.myguard.nl/deb.myguard.nl.gpg \
  | sudo tee /etc/apt/keyrings/deb.myguard.nl.gpg >/dev/null
★★★★ gpg --show-keys --with-fingerprint /etc/apt/keyrings/deb.myguard.nl.gpg
      → 和官網比對指紋！

echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/deb.myguard.nl.gpg] \
https://deb.myguard.nl/apt/nginx/$CODENAME $CODENAME main" \
  | sudo tee /etc/apt/sources.list.d/myguard-nginx.list
sudo apt update
```

### 套件庫路徑

```
完整：  https://deb.myguard.nl/apt/dists/$CODENAME
NGINX： https://deb.myguard.nl/apt/nginx/$CODENAME
Angie： https://deb.myguard.nl/apt/angie/$CODENAME
```

### ★★★★ pinning

```
Package: nginx nginx-* libnginx-mod-*
Pin: origin deb.myguard.nl
Pin-Priority: 700

Package: *                    # ★★★★ 其他低優先，避免取代系統套件
Pin: origin deb.myguard.nl
Pin-Priority: 100

apt-mark hold nginx           # ★★★ 正式環境鎖版本
apt policy nginx              # ★★★ 驗證
```

### ★★★★ 自製模組

```
autocert     ★★★★ 內建 ACME（不用 certbot）
http-shield  攔截已知攻擊
error-abuse  4xx/5xx 濫用限流
sentinel     ★★ 信譽評分 + AI 爬蟲 tarpit（實驗）
cache-turbo  邊緣快取 + stale-while-revalidate
strip-filter HTML/CSS/JS/JSON 精簡
zstd         Zstandard 壓縮
```

### ★★★★ 風險與退場

```bash
★★★★ 第三方套件庫 = 把 root 交給對方（maintainer script 以 root 執行）
★★★★ 一定要驗證 GPG 指紋
★★★ 檢查 .deb：dpkg-deb --control x.deb /tmp/c && cat /tmp/c/postinst
★★★ 正式環境要簽核 + 有退場方案

# 退場
sudo apt remove --purge nginx 'libnginx-mod-*'
sudo rm -f /etc/apt/sources.list.d/myguard*.list \
           /etc/apt/preferences.d/myguard \
           /etc/apt/keyrings/deb.myguard.nl.gpg
sudo apt update && sudo apt install nginx
★★★★ 記得先移除設定檔中的 autocert 等自製指令
```

---

## 練習題

> [!question]- 練習 1：加入套件庫 ★★★
> 1. **確認你的 `lsb_release -cs` 有沒有支援**
> 2. **手動匯入 GPG 金鑰並驗證指紋**
> 3. **和官網公布的指紋比對** → 一致嗎？
> 4. 加入 nginx 的子套件庫並 `apt update`
> 5. **`apt policy nginx`** → 候選版本是哪一個？
> 6. **`apt-cache search '^libnginx-mod-' | wc -l`** → 有幾個模組？

> [!question]- 練習 2：檢查 .deb ★★★★
> 1. **下載 `myguard.deb` 但先不要安裝**
> 2. **`dpkg-deb --contents`** → 會裝哪些檔案？
> 3. **`dpkg-deb --control` 解出控制檔**
> 4. **`cat postinst`** → 它做了什麼？
> 5. **這些動作需要 root 嗎？如果 postinst 有惡意程式碼會怎樣？**
> 6. **比較手動設定和 bootstrap 的優缺點**

> [!question]- 練習 3：pinning ★★★★
> 1. **不設 pinning 直接 `apt update && apt list --upgradable`**
> 2. **有哪些系統套件會被 MyGuard 的版本取代？**
> 3. **加上 `Package: * Pin-Priority: 100`** → 呢？
> 4. **`apt policy nginx`** → 優先權是多少？
> 5. **用 `apt install -s` 模擬安裝**
> 6. **`apt-mark hold nginx` 後試著 upgrade** → 會動嗎？

> [!question]- 練習 4：風險評估 ★★★★
> 1. **對 MyGuard 回答那六個評估問題**
> 2. **你的環境該不該用？為什麼？**
> 3. **寫下退場方案並實際演練一次**
> 4. **執行 `audit-repos`** → 你的系統有幾個第三方套件庫？
> 5. **設定金鑰變更監控**
> 6. **寫一份簽核用的說明文件**

> [!question]- 練習 5：退場演練 ★★★
> 1. **裝好 MyGuard 的 nginx 並用 `autocert on;`**
> 2. **直接移除套件庫換回官方版** → `nginx -t` 成功嗎？
> 3. **錯誤訊息是什麼？**
> 4. **正確的順序應該是什麼？**
> 5. **完整走一次退場流程**
> 6. **把步驟寫進文件**

---

## 小測驗

Q1. **MyGuard 是什麼？最容易被誤解成什麼**？

Q2. **它解決了官方套件庫的什麼問題**？（至少三個）

Q3. **加入第三方 APT 套件庫的真正風險是什麼**？

Q4. **為什麼一定要驗證 GPG 金鑰指紋**？

Q5. **安裝來路不明的 `.deb` 前該檢查什麼**？怎麼檢查？

Q6. **`Package: * Pin-Priority: 100` 這條 pinning 規則的用意**？

Q7. **`does not have a Release file` 是什麼問題**？怎麼確認？

Q8. **MyGuard 的哪一個自製模組讓 certbot 變成不必要**？

Q9. **RHEL 系要用強化版 NGINX 有哪些選擇**？

Q10. **移除 MyGuard 換回官方 nginx 時，順序為什麼重要**？

> [!question]- 測驗答案
> **Q1.** **MyGuard 是一個第三方的 Debian / Ubuntu APT 套件庫**，
> 由 **myguard-labs** 維護，提供**強化版的 NGINX 與 Angie** 以及 100 多個動態模組。
> **★★★★ 最容易被誤解成「端點防護軟體 / 防毒 / EDR」** ——
> 因為名字裡有 "Guard"。
> **它不是**：不是防毒軟體、不是 EDR 代理程式、不是資安監控平台，
> 也和任何商業的「MyGuard」產品沒有關係。
> 網址是 `deb.myguard.nl`，原始碼在 `github.com/myguard-labs`，
> 問題追蹤在 `github.com/eilandert/deb.myguard.nl`。
> 這個釐清很重要 —— 在機關環境提到「要裝 MyGuard」時，
> 如果不說清楚，資安單位可能會以為你要裝一個防護軟體。
>
> **Q2.** **官方套件庫的 NGINX 缺少現代化的功能，而且版本落後**：
> ①**★★★ HTTP/3（QUIC）** —— Ubuntu 官方套件庫沒有；
> ②**★★★ ModSecurity v3 + OWASP CRS** —— 官方完全沒有，
> 要自己編譯（處理相依、每次更新重編、沒有安全更新）；
> ③**★★ Brotli 與 Zstandard 壓縮** —— 官方沒有；
> ④**★★★ kTLS**（核心層的 TLS 卸載，效能提升）；
> ⑤**★★ 動態模組數量** —— 官方約 10 個，MyGuard 有 100+；
> ⑥**★★★★ 自製模組**（`autocert`、`http-shield`、`cache-turbo` 等）
> —— 這些在別的地方拿不到。
> **典型痛點**：「我需要 HTTP/3 + ModSecurity + Brotli」，
> 官方套件庫三個都沒有，自己編譯又要長期維護。
>
> **Q3.** **★★★★ 加入第三方套件庫等於「把 root 權限交給對方」**。
> APT 套件庫中的套件可以：
> ①**安裝任意檔案到系統的任何位置**；
> ②**★★★★ 執行 maintainer script（preinst / postinst / prerm / postrm）
> —— 這些是以 root 執行的任意程式碼**；
> ③**取代系統既有的套件**。
> **這不是「多裝一個程式」，是信任鏈的擴張** ——
> 套件庫被入侵、維護者帳號被盜、或維護者本身有惡意，
> 都能在你所有裝了這個套件庫的機器上執行任意程式碼。
> **所以機關環境要走簽核程序**，
> 並且記錄「為什麼加、誰核准、退場方案是什麼」。
>
> **Q4.** 因為 **不驗證指紋的話，中間人可以推送任意套件**。
> 你用 `curl` 下載金鑰的過程如果被攔截
> （DNS 汙染、惡意的 proxy、被入侵的網路），
> 攻擊者可以給你**他自己的金鑰**，
> 之後 APT 就會**信任攻擊者簽署的套件庫**，
> 而且**完全不會有任何警告**（簽章驗證會通過，因為用的是攻擊者的金鑰）。
> **正確做法**：
> ```bash
> gpg --show-keys --with-fingerprint /etc/apt/keyrings/deb.myguard.nl.gpg
> ```
> **把顯示的指紋和官網公布的比對**，不一致就立刻停止。
> 理想上指紋應該從**不同的管道**取得（官網 + GitHub + 維護者的其他發布管道）。
> 之後也要**定期監控金鑰是否變更**（套件庫被入侵的徵兆）。
>
> **Q5.** **★★★★ 檢查 maintainer script** ——
> `.deb` 的 `preinst`、`postinst`、`prerm`、`postrm`
> **都是以 root 執行的任意程式碼**，
> 所以「下載一個 `.deb` 然後 `dpkg -i`」的風險和「`curl | sh`」是一樣的。
> **三個檢查步驟**：
> ```bash
> dpkg-deb --info myguard.deb              # ★★ 套件的基本資訊
> dpkg-deb --contents myguard.deb          # ★★★ 會安裝哪些檔案
> dpkg-deb --control myguard.deb /tmp/ctl  # ★★★★ 解出控制檔
> cat /tmp/ctl/{preinst,postinst,prerm,postrm} 2>/dev/null
> ```
> **機關環境建議用手動設定套件庫**，不要用 bootstrap 的 `.deb` ——
> 每一步都看得見，也符合稽核要求。
>
> **Q6.** **★★★★ 防止第三方套件庫意外取代系統套件**。
> 加入 MyGuard 之後，它裡面可能有一些**和系統套件同名但版本更新**的套件
> （共用函式庫、相依套件）。
> 如果不設 pinning，`apt upgrade` 時 **APT 會自動選擇版本較新的**，
> 於是**系統的核心套件被第三方版本取代了** ——
> 這會造成難以預期的相容性問題，而且日後排查時很難發現。
> **正確的 pinning 策略**：
> ```
> Package: nginx nginx-* libnginx-mod-*
> Pin: origin deb.myguard.nl
> Pin-Priority: 700              # ★★★ 只有這些用 MyGuard
>
> Package: *
> Pin: origin deb.myguard.nl
> Pin-Priority: 100              # ★★★★ 其他一律低於官方
> ```
> **驗證**：`apt policy <套件名>` 看優先權，`apt install -s` 模擬安裝。
>
> **Q7.** **★★★ 你的發行版 codename 不在套件庫的支援清單中**。
> 每個 APT 套件庫都是**按 codename 分開建置**的
> （`noble`、`jammy`、`bookworm`…），
> 套件庫沒有為你的版本建置就會缺少 `Release` / `InRelease` 檔案。
> **確認方式**：
> ```bash
> CODENAME=$(lsb_release -cs)
> curl -fsSI "https://deb.myguard.nl/apt/dists/$CODENAME/InRelease" | head -1
> # HTTP/2 200 = 有支援；404 = 沒有
> curl -fsSL https://deb.myguard.nl/apt/dists/ | grep -oP 'href="\K[a-z]+(?=/")'
> ```
> **三個處理方式**：
> ①**升級系統**到支援的版本；
> ②**用官方套件庫 + 自行編譯**需要的模組；
> ③**★★ 用官方提供的 Docker 映像**（不管主機是什麼發行版都能跑）。
>
> **Q8.** **★★★★ `autocert` 模組** ——
> 它是**內建在 NGINX 裡面的 ACME 客戶端**。
> 只要在 server 區塊加一行 **`autocert on;`**，
> NGINX 自己就會**向 Let's Encrypt（或任何 ACME CA）申請、提供、續期**
> 該 vhost 的 `server_name` 對應的憑證 ——
> **不需要 certbot、不需要 cron job、不需要 deploy hook、不需要 reload**。
> 這解決了傳統 certbot 流程的幾個痛點：
> 續期後要 reload nginx（可能失敗沒人發現）、
> `.well-known/acme-challenge` 的 location 要另外設定、
> cron 停掉就沒人知道憑證要過期了。
> 相關指令：`autocert_contact`（ACME 帳號 email）、
> `autocert_key_type`（預設 p384）、`autocert_challenge`（http-01 / tls-alpn-01 / dns-01）、
> `autocert_staging on;`（測試用）。詳見 [[060-02-05-03-guide-MyGuard-autocert自動憑證模組]]。
>
> **Q9.** **★★★★ MyGuard 只提供 Debian / Ubuntu 的套件，沒有 RPM**。
> **RHEL 系的四個替代方案**：
> ①**★★★ 官方的 nginx.org RPM 套件庫** ——
> 有 mainline 版本與 HTTP/3 支援，但沒有 ModSecurity 和自製模組；
> ②**★★ Angie 官方的 RPM 套件庫**（`angie.software`）——
> Angie 本身就內建 ACME 支援與更多功能；
> ③**★★★ 自行編譯** —— 完整可控，
> 但要自己處理相依、自己追安全更新、每次升級都要重編；
> ④**★★ 用 MyGuard 的 Docker 映像**（`hub.docker.com/r/eilandert/nginx`）——
> **不管主機是什麼發行版都能跑**，而且每日重建。
> 對機關的 RHEL 環境，方案②或④通常最實際。
>
> **Q10.** 因為 **設定檔中可能有只有 MyGuard 版本才認得的指令**
> （`autocert on;`、`http_shield on;`、`cache_turbo on;` 等）。
> **如果先換成官方 nginx 再處理設定**：
> ```
> nginx: [emerg] unknown directive "autocert" in /etc/nginx/sites-enabled/app:12
> ```
> **nginx 完全起不來，服務中斷**。
> **正確的順序**：
> ①**先把設定檔中的自製模組指令註解或移除**
> （`autocert on;` → 改回 `ssl_certificate` + certbot）；
> ②`nginx -t` 確認設定在**沒有那些模組**的情況下也是有效的；
> ③移除套件、套件庫、金鑰、pinning；
> ④`apt install nginx` 裝官方版；
> ⑤**再次 `nginx -t` 並 reload**。
> **這個退場流程應該事先演練過並寫進文件** ——
> 真正需要退場時通常是緊急狀況（套件庫掛掉、資安事件），
> 不會有時間慢慢試。

---

## 延伸閱讀

- [[060-02-05-02-guide-MyGuard-Angie伺服器入門]] — Angie 是什麼、和 NGINX 的差異
- [[060-02-05-03-guide-MyGuard-autocert自動憑證模組]] — **★★★★ 不用 certbot 的自動憑證**
- [[060-02-05-07-guide-MyGuard-動態模組管理]] — 模組的安裝與載入
- [[060-02-05-08-guide-MyGuard-MyGuard實戰組合]] — 完整的實戰配置
- [[020-02-03-03-cmd-標準化-第三方APT套件庫實務]] — 第三方套件庫的通用做法
- [[060-02-02-01-guide-Nginx-安裝與目錄結構]] — NGINX 基礎
