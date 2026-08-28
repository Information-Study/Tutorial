---
title: "nmap 埠掃描與盤點"
desc: "主機探測、埠掃描、服務辨識與資產盤點的合法使用"
aliases: [nmap, 埠掃描, port scan, 資產盤點, NSE]
tags: [群組/軟體與開發工具, 主題/網路診斷, 主題/nmap, 主題/資安]
category: 常用工具
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[03-ss-netstat-與lsof]]"]
updated: 2026-08-28
---

# nmap 埠掃描與盤點

> [!abstract] 這篇你會學到
> - **★★★★ 掃描的授權與法遵**（機關環境的必要程序）
> - 主機探測、埠掃描的**六種類型與差別**
> - **★★★ 服務與版本辨識**（`-sV`）
> - **★★ 作業系統偵測**與其限制
> - **★★★ NSE 腳本**（含 TLS 檢查、漏洞掃描）
> - **★★★ 資產盤點的實務流程**與輸出格式
> - **★★ 掃描對目標的影響**與如何降低

> [!danger] 使用前必讀 ★★★★
> ```
> ★★★★ 對【沒有授權】的網路或主機執行埠掃描，
>       在許多國家與地區可能構成違法行為。
>
> ★★★ 台灣相關法規：
>   · 刑法第 358 條「入侵電腦或其相關設備罪」
>   · 刑法第 360 條「干擾電腦或其相關設備罪」
>   · ★★ 個人資料保護法（若掃描過程接觸到個資）
>
> ★★★★ 本篇的內容僅用於：
>   ① 【你自己管理的】設備與網路
>   ② 【有書面授權】的滲透測試或資安檢測
>   ③ 機關內部的【資產盤點與弱點管理】（★ 需經核准）
>
> ★★★ 動手前的三件事：
>   ① 取得書面授權（★ 明確的 IP 範圍與時間窗）
>   ② 通知相關單位（★ 避免被誤判為攻擊）
>   ③ 記錄掃描的目的、範圍、時間、執行人
> ```

## 前置知識

- [[03-ss-netstat-與lsof]] — **★★ 自己的機器用 `ss` 更準確**
- [[16-網路基礎指令]] — 網路基礎

---

## ★★★ 什麼時候該用 nmap

```
★★★★ 重要觀念：【對自己的機器，ss 比 nmap 準確】

  ss -tulnp   → ★★★ 直接問核心，100% 準確
                 → 而且知道是【哪個程序】在監聽
  nmap        → ★★ 從外部探測，會被防火牆影響
                 → 只知道「外面看得到什麼」

★★★ nmap 的真正價值：
  ① ★★★★ 【驗證防火牆規則】
     → 「我設了規則，外面到底看不看得到？」
     → ★★ ss 說有在聽，nmap 說看不到 → ★★★ 防火牆有效

  ② ★★★ 【資產盤點】
     → 整個網段有哪些機器、開了什麼服務
     → ★★ 找出「沒人知道還活著」的老機器

  ③ ★★★ 【外部視角的資安檢查】
     → 攻擊者看到的是什麼

  ④ ★★ 【找出未經核准的服務】
     → 有人偷偷開了一個服務

★★★ 標準流程：
  ss（內部真相）+ nmap（外部視角）→ ★★★★ 比對兩者的差異
```

---

## 安裝

```bash
$ sudo apt install -y nmap
$ nmap --version
Nmap version 7.94 ( https://nmap.org )
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> $ sudo dnf install -y nmap
> ```

```bash
# ★★ 更新 NSE 腳本資料庫
$ sudo nmap --script-updatedb
$ ls /usr/share/nmap/scripts/ | wc -l
604
```

---

## 主機探測 ★★

```bash
# ═══ ★★★ ping scan（★ 只找活著的主機，不掃埠）═══
$ sudo nmap -sn 10.10.20.0/24
Starting Nmap 7.94
Nmap scan report for 10.10.20.1
Host is up (0.00042s latency).
MAC Address: 00:1A:2B:3C:4D:5E (Cisco Systems)
Nmap scan report for 10.10.20.31
Host is up (0.00031s latency).
MAC Address: BA:12:CD:34:EF:56 (Proxmox Server Solutions)
...
Nmap done: 256 IP addresses (18 hosts up) scanned in 3.24 seconds

#   -sn  ★★★ 只做主機探測（★ 舊版是 -sP）
#   ★★ 在同網段會用 ARP（★ 最可靠，防火牆擋不掉）
#   ★★ 跨網段會用 ICMP echo + TCP SYN 80/443 + ICMP timestamp

# ★★ 只列出 IP（給腳本用）
$ sudo nmap -sn 10.10.20.0/24 -oG - | awk '/Up$/{print $2}'
10.10.20.1
10.10.20.31
10.10.20.50

# ★★★ 不做主機探測，直接掃埠（★ 目標擋 ping 時必用）
$ sudo nmap -Pn 10.10.20.31
#   -Pn  ★★★ 假設主機是活的
#   → ★★ 很多機關的主機會擋 ICMP，不加 -Pn 會被判定為「主機不存在」

# ★★ 只列出目標不掃描（★ 確認範圍算對了）
$ nmap -sL 10.10.20.0/28
Nmap scan report for 10.10.20.0
Nmap scan report for 10.10.20.1
...
Nmap done: 16 IP addresses (0 hosts up)
```

```bash
# ★★★ 主機探測的細部控制
$ sudo nmap -sn -PE 10.10.20.0/24          # ICMP echo
$ sudo nmap -sn -PS22,80,443 10.10.20.0/24 # ★★ TCP SYN 探測特定埠
$ sudo nmap -sn -PA80 10.10.20.0/24        # TCP ACK
$ sudo nmap -sn -PU53 10.10.20.0/24        # UDP
$ sudo nmap -sn -PR 10.10.20.0/24          # ★★★ ARP（★ 同網段最準）

# ★★ 其他寫法的目標
$ nmap 10.10.20.31                          # 單一主機
$ nmap 10.10.20.0/24                        # CIDR
$ nmap 10.10.20.1-50                        # ★★ 範圍
$ nmap 10.10.20.1,5,10                      # 列舉
$ nmap -iL targets.txt                      # ★★★ 從檔案讀
$ nmap 10.10.20.0/24 --exclude 10.10.20.1,10.10.20.254   # ★★ 排除
$ nmap 10.10.20.0/24 --excludefile skip.txt
```

---

## ★★★ 埠掃描類型

| 掃描 | 選項 | 需要 root | 說明 |
| --- | --- | --- | --- |
| **TCP SYN** | **`-sS`** | **★ 是** | **★★★ 預設（root 時）；只送 SYN 不完成交握，快** |
| **TCP connect** | **`-sT`** | 否 | **★★ 完整交握；★★★ 會在目標留下完整的連線紀錄** |
| **UDP** | **`-sU`** | ★ 是 | **★★★ 很慢**（見下） |
| ACK | `-sA` | 是 | ★★ 判斷防火牆是有狀態還是無狀態 |
| Window | `-sW` | 是 | ★ ACK 的變形 |
| NULL/FIN/Xmas | `-sN`/`-sF`/`-sX` | 是 | **★★ 規避偵測**（★ 對 Windows 無效） |

```bash
# ═══ ★★★ 最常用的三種 ═══
$ sudo nmap -sS 10.10.20.31                  # ★★★ SYN 掃描（★ 預設）
$ nmap -sT 10.10.20.31                       # ★★ 不用 root
$ sudo nmap -sU --top-ports 20 10.10.20.31   # ★★ UDP（★ 限制範圍）

# ═══ ★★★ 埠的指定 ═══
$ sudo nmap -p 80,443 10.10.20.31
$ sudo nmap -p 1-1000 10.10.20.31
$ sudo nmap -p- 10.10.20.31                  # ★★★ 全部 65535 個（★ 慢）
$ sudo nmap -p U:53,161,T:22,80,443 10.10.20.31   # ★★ 混合
$ sudo nmap -F 10.10.20.31                   # ★★ 快速（前 100 個常用埠）
$ sudo nmap --top-ports 1000 10.10.20.31     # ★★★ 最常見的 1000 個（★ 預設）
```

```
★★★ 掃描結果的六種狀態：

  open              ★★★ 有服務在監聽並接受連線
  closed            ★★ 主機有回應，但沒有服務（★ 回 RST）
  ★★★★ filtered     被防火牆擋住 → 【沒有任何回應】
                    → ★★★ 這是防火牆用 DROP 的特徵
  unfiltered        能到達但無法判斷 open/closed（★ ACK 掃描才會出現）
  open|filtered     ★★★ 無法區分（★ UDP 掃描很常見）
  closed|filtered   ★ 罕見

★★★★ 判讀重點：
  · closed 多  → ★★ 主機活著，防火牆是 REJECT 或沒防火牆
  · ★★★★ filtered 多 → 防火牆在 DROP（★ 這是比較好的設定）
  · ★★★ 掃描很慢 → 通常就是因為 filtered（要等 timeout）
```

> [!warning] UDP 掃描為什麼那麼慢 ★★★
> ```
> ★★★★ UDP 沒有交握，判斷「有沒有服務」很困難：
>
>   送 UDP 封包 → 有三種結果：
>     ① 收到 UDP 回應        → ★★ open（★ 但很多服務不回應）
>     ② 收到 ICMP port unreachable → ★★ closed
>     ③ ★★★★ 什麼都沒收到    → open|filtered（★ 無法判斷）
>
>   → ★★★ 情況 ③ 要等 timeout，而且會重試
>   → ★★★★ 而且 Linux 對 ICMP unreachable 有【速率限制】
>     （★ 預設每秒最多 1 個）→ 掃 1000 個埠要 1000 秒！
>
> ★★★ 實務做法：
>   ① ★★★★ 只掃常用的 UDP 埠
>      $ sudo nmap -sU --top-ports 20 10.10.20.31
>   ② ★★ 搭配 -sV 讓 nmap 用協定探測（★ 更準）
>      $ sudo nmap -sU -sV -p 53,123,161,500 10.10.20.31
>   ③ ★★ 加上 --max-retries 1 減少重試
> ```

---

## ★★★ 服務與版本辨識

```bash
$ sudo nmap -sV 10.10.20.31
PORT     STATE SERVICE  VERSION
22/tcp   open  ssh      OpenSSH 9.6p1 Ubuntu 3ubuntu13.5 (Ubuntu Linux; protocol 2.0)
80/tcp   open  http     nginx 1.24.0 (Ubuntu)
443/tcp  open  ssl/http nginx 1.24.0 (Ubuntu)
3306/tcp open  mysql    MySQL 8.0.39-0ubuntu0.24.04.2
#                                ↑
#   ★★★★ 版本資訊【對攻擊者非常有價值】
#      → 可以直接查有沒有已知漏洞

# ★★ 調整探測強度
$ sudo nmap -sV --version-intensity 9 10.10.20.31    # ★ 0~9，預設 7
$ sudo nmap -sV --version-light 10.10.20.31          # ★★ = intensity 2（★ 快）
$ sudo nmap -sV --version-all 10.10.20.31            # = intensity 9

# ★★★ 作業系統偵測
$ sudo nmap -O 10.10.20.31
Running: Linux 5.X|6.X
OS CPE: cpe:/o:linux:linux_kernel:5 cpe:/o:linux:linux_kernel:6
OS details: Linux 5.0 - 6.5
Network Distance: 1 hop
#   ★★ 準確度有限，而且需要至少一個 open 和一個 closed 的埠

# ★★★ 常用組合
$ sudo nmap -sS -sV -O -T4 10.10.20.31
$ sudo nmap -A 10.10.20.31                # ★★★ -A = -sV -O --script=default --traceroute
#   ★★★★ -A 很吵！會觸發 IDS/IPS，不要對正式環境隨便用
```

> [!danger] 版本資訊外洩是資安問題 ★★★
> ```
> ★★★★ 攻擊者拿到版本號的第一件事：
>   $ searchsploit nginx 1.24.0
>   $ 到 CVE 資料庫查有沒有已知漏洞
>
> ★★★ 減少版本外洩：
>
>   【nginx】
>     server_tokens off;                 # ★★★ 隱藏版本號
>     more_clear_headers Server;         # ★★ 需要 headers-more 模組
>
>   【Apache】
>     ServerTokens Prod
>     ServerSignature Off
>
>   【SSH】★★ 無法完全隱藏（★ 協定要求）
>     → ★★★ 但可以確保是最新版
>     $ ssh -V
>
>   【MySQL】★★★★ 根本不該對外開放！
>     bind-address = 127.0.0.1
>
> ★★ 但要注意：
>   隱藏版本【只是延緩】，不是防護
>   → ★★★★ 真正的防護是【保持更新】+ 最小暴露面
> ```

```bash
# ★★ 驗證版本隱藏是否生效
$ curl -sI https://app.example.gov.tw | grep -i '^server:'
Server: nginx                            # ★★★ 沒有版本號（正確）
Server: nginx/1.24.0                     # ★★★★ 有版本號（要修正）

$ sudo nmap -sV -p 443 --script http-server-header app.example.gov.tw
```

---

## ★★★ NSE 腳本

```bash
# ★★ 腳本分類
$ ls /usr/share/nmap/scripts/ | head -10
$ nmap --script-help "default" 2>/dev/null | head -20

# ★★★ 分類：
#   auth        認證相關
#   broadcast   廣播探測
#   ★★ default  預設執行的（-sC 或 -A）
#   discovery   資訊蒐集
#   ★★★ safe    不會影響目標的
#   ★★★★ intrusive  ★ 可能影響目標（★ 慎用）
#   ★★★★ vuln   漏洞檢測（★ 需要授權）
#   ★★★★ exploit  ★★ 實際利用（★★★★ 絕對不要隨便用）
#   ★★ dos      阻斷服務測試（★★★★ 絕對不要對正式環境用）
#   malware     惡意軟體偵測
#   version     版本偵測輔助

# ═══ ★★★ 常用腳本 ═══
$ sudo nmap -sC 10.10.20.31                        # ★★ default 腳本
$ sudo nmap --script safe 10.10.20.31              # ★★★ 只跑安全的
$ sudo nmap --script "http-*" -p 80,443 10.10.20.31
$ sudo nmap --script "not intrusive" 10.10.20.31   # ★★★ 排除侵入性的

# ═══ ★★★★ TLS/SSL 檢查（★ 非常實用）═══
$ sudo nmap --script ssl-enum-ciphers -p 443 app.example.gov.tw
PORT    STATE SERVICE
443/tcp open  https
| ssl-enum-ciphers:
|   TLSv1.2:
|     ciphers:
|       TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384 (secp256r1) - A
|       TLS_RSA_WITH_AES_128_CBC_SHA (rsa 2048) - C      # ★★★ 弱！
|     compressors: NULL
|     cipher preference: server
|   TLSv1.3:
|     ciphers:
|       TLS_AKE_WITH_AES_256_GCM_SHA384 (ecdh_x25519) - A
|_  least strength: C                                     # ★★★★ 最弱是 C

$ sudo nmap --script ssl-cert -p 443 app.example.gov.tw
| ssl-cert: Subject: commonName=app.example.gov.tw
| Subject Alternative Name: DNS:app.example.gov.tw, DNS:www.app.example.gov.tw
| Issuer: commonName=R11/organizationName=Let's Encrypt/countryName=US
| Not valid before: 2026-07-01T00:00:00
| Not valid after:  2026-09-29T23:59:59              # ★★★ 檢查到期日
|_MD5: ...

# ★★★ 一次檢查憑證與密碼套件
$ sudo nmap --script "ssl-cert,ssl-enum-ciphers,ssl-date" -p 443 app.example.gov.tw

# ═══ ★★ HTTP 相關 ═══
$ sudo nmap --script http-headers -p 443 app.example.gov.tw
$ sudo nmap --script http-security-headers -p 443 app.example.gov.tw
$ sudo nmap --script http-methods -p 443 app.example.gov.tw
| http-methods:
|_  Supported Methods: GET HEAD POST OPTIONS TRACE     # ★★★ TRACE 應該關掉

$ sudo nmap --script http-title -p 80,443 10.10.20.0/24

# ═══ ★★★ SMB / Windows（★ AD 環境盤點）═══
$ sudo nmap --script smb-os-discovery -p 445 10.10.30.0/24
$ sudo nmap --script smb-security-mode -p 445 10.10.30.50
$ sudo nmap --script smb2-security-mode -p 445 10.10.30.50
| smb2-security-mode:
|   3.1.1:
|_    Message signing enabled and required           # ★★★ 正確

# ═══ ★★★★ 漏洞掃描（★ 需要授權）═══
$ sudo nmap --script vuln 10.10.20.31                # ★★★★ 侵入性，要授權
$ sudo nmap --script ssl-heartbleed -p 443 10.10.20.31
$ sudo nmap --script "http-vuln-*" -p 443 10.10.20.31

# ★★ 安裝 vulners（查 CVE）
$ sudo git clone https://github.com/vulnersCom/nmap-vulners.git \
    /usr/share/nmap/scripts/nmap-vulners
$ sudo nmap --script-updatedb
$ sudo nmap -sV --script nmap-vulners/vulners.nse -p 22,80,443 10.10.20.31
```

> [!danger] `--script vuln` 與 `exploit` 的差別 ★★★★
> ```
> ★★★ vuln 類別
>   → 【檢測】是否存在已知漏洞
>   → ★★ 部分腳本會實際發送 payload
>   → ★★★ 可能造成服務異常
>   → ★★★★ 需要書面授權
>
> ★★★★ exploit 類別
>   → 【實際利用】漏洞
>   → ★★★★ 這是攻擊行為
>   → ★★★★ 絕對不要對正式環境使用
>   → ★★★ 只在有明確授權的滲透測試中使用
>
> ★★★★ dos 類別
>   → 【測試阻斷服務】
>   → ★★★★ 會讓服務掛掉
>   → ★★★★ 絕對不要對正式環境使用
>
> ★★★ 安全的做法：
>   $ sudo nmap --script "safe and not intrusive" 目標
> ```

---

## ★★ 掃描速度與隱蔽性

```bash
# ═══ ★★★ 時間範本 ═══
$ sudo nmap -T0 10.10.20.31       # paranoid  ★ 極慢（★ 規避 IDS，5 分鐘一個埠）
$ sudo nmap -T1 10.10.20.31       # sneaky
$ sudo nmap -T2 10.10.20.31       # polite    ★★ 降低對目標的負擔
$ sudo nmap -T3 10.10.20.31       # ★★★ normal（預設）
$ sudo nmap -T4 10.10.20.31       # ★★★ aggressive（★ 內網掃描建議）
$ sudo nmap -T5 10.10.20.31       # insane    ★★★ 可能漏掉結果

# ═══ ★★ 細部控制 ═══
$ sudo nmap --min-rate 100 --max-rate 500 10.10.20.0/24   # ★★ 每秒封包數
$ sudo nmap --max-retries 1 10.10.20.31                    # ★★ 減少重試
$ sudo nmap --host-timeout 30s 10.10.20.0/24               # ★★ 單一主機上限
$ sudo nmap --scan-delay 100ms 10.10.20.31                 # ★★ 每個探測間隔
$ sudo nmap --min-parallelism 10 --max-parallelism 100 10.10.20.0/24

# ═══ ★★ 分片與偽裝（★ 規避偵測，多數情況不需要）═══
$ sudo nmap -f 10.10.20.31                       # ★ IP 分片
$ sudo nmap --mtu 16 10.10.20.31
$ sudo nmap -D RND:5 10.10.20.31                 # ★★ 誘餌 IP
$ sudo nmap -S 10.10.20.99 -e ens18 10.10.20.31  # ★★ 偽造來源（★ 收不到回應）
$ sudo nmap --source-port 53 10.10.20.31         # ★★ 偽裝成 DNS 回應
$ sudo nmap --data-length 25 10.10.20.31         # ★ 加隨機資料

#   ★★★★ 規避技術在【授權測試】以外的使用可能構成犯罪
#      → ★★ 本手冊的資產盤點用途【不需要】這些
```

> [!warning] 掃描對目標的影響 ★★★
> ```
> ★★★ 掃描不是「唯讀」的操作，它會：
>
>   ① ★★★ 消耗目標的資源
>      → 每個 SYN 都會建立半開連線（★ 佔用 backlog）
>      → -T5 掃 65535 個埠可能讓小型設備當機
>      → ★★★★ 網路印表機、IP 攝影機、老舊的嵌入式設備【特別脆弱】
>
>   ② ★★★ 觸發 IDS/IPS 告警
>      → ★★ 資安單位會收到通知
>      → ★★★★ 沒事先通知的話會被當成攻擊
>
>   ③ ★★ 觸發自動封鎖
>      → fail2ban、WAF、雲端的 DDoS 防護
>      → ★★★ 你的 IP 可能被封鎖
>
>   ④ ★★ 產生大量日誌
>      → ★ 目標的日誌被洗版
>
> ★★★ 對正式環境的建議：
>   · 用 -T2（polite）或 -T3
>   · ★★ 限制埠範圍（不要 -p-）
>   · ★★★ 離峰時段執行
>   · ★★★★ 事先通知並取得授權
> ```

---

## ★★★ 資產盤點實務

```bash
#!/usr/bin/env bash
# ★★★ /usr/local/bin/asset-scan —— 機關內網資產盤點
set -euo pipefail

RANGE="${1:?用法: asset-scan <網段> [輸出目錄]}"
OUT="${2:-/var/log/asset-scan}"
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"

echo "═══ 資產盤點  $RANGE  $(date '+%F %T') ═══"
echo "★★ 執行者: $(whoami)@$(hostname)"

# ═══ ★★★【1】主機探測 ═══
echo -e "\n【1】主機探測（ARP/ICMP）"
sudo nmap -sn -T4 "$RANGE" -oG "$OUT/hosts-$TS.gnmap" >/dev/null
UP=$(awk '/Up$/{print $2}' "$OUT/hosts-$TS.gnmap")
COUNT=$(echo "$UP" | grep -c . || echo 0)
echo "  ★ 發現 $COUNT 台主機"
echo "$UP" > "$OUT/hosts-$TS.txt"

# ═══ ★★★【2】埠掃描 + 服務辨識 ═══
echo -e "\n【2】埠掃描與服務辨識（★ 只掃常用埠，T3 保守）"
sudo nmap -sS -sV --version-light -T3 --top-ports 200 \
    -iL "$OUT/hosts-$TS.txt" \
    -oA "$OUT/scan-$TS" >/dev/null
echo "  ★ 完成，輸出：$OUT/scan-$TS.{nmap,gnmap,xml}"

# ═══ ★★★【3】產生 CSV 報表 ═══
echo -e "\n【3】產生報表"
{
  echo "IP,主機名,埠,協定,狀態,服務,版本"
  python3 - "$OUT/scan-$TS.xml" <<'PYEOF'
import sys, xml.etree.ElementTree as ET, csv
root = ET.parse(sys.argv[1]).getroot()
w = csv.writer(sys.stdout)
for h in root.findall('host'):
    if h.find('status').get('state') != 'up':
        continue
    ip = h.find("address[@addrtype='ipv4']").get('addr')
    hn = h.find('hostnames/hostname')
    name = hn.get('name') if hn is not None else ''
    ports = h.find('ports')
    if ports is None:
        continue
    for p in ports.findall('port'):
        st = p.find('state').get('state')
        if st != 'open':
            continue
        s = p.find('service')
        w.writerow([ip, name, p.get('portid'), p.get('protocol'), st,
                    s.get('name', '') if s is not None else '',
                    ((s.get('product', '') + ' ' + s.get('version', '')).strip()
                     if s is not None else '')])
PYEOF
} > "$OUT/assets-$TS.csv"
echo "  ★ CSV：$OUT/assets-$TS.csv（$(( $(wc -l < "$OUT/assets-$TS.csv") - 1 )) 筆）"

# ═══ ★★★★【4】風險檢查 ═══
echo -e "\n【4】★★★ 風險項目"
awk -F, 'NR>1' "$OUT/assets-$TS.csv" | while IFS=, read -r ip name port proto st svc ver; do
    case "$port" in
      3306|5432|6379|27017|11211|9200|2375|5984)
        echo "  ★★★★ 資料庫/快取對外: $ip:$port ($svc $ver)" ;;
      23)   echo "  ★★★★ Telnet（明文）: $ip:$port" ;;
      21)   echo "  ★★★ FTP（明文）: $ip:$port" ;;
      445|139) echo "  ★★ SMB: $ip:$port ($ver)" ;;
      3389) echo "  ★★★ RDP 對外: $ip:$port" ;;
      5900|5901) echo "  ★★★ VNC: $ip:$port" ;;
      161)  echo "  ★★ SNMP: $ip:$port（★ 檢查是否還在用 public）" ;;
    esac
done | sort -u

# ═══ ★★★【5】與上次比對 ═══
PREV=$(ls -1t "$OUT"/assets-*.csv 2>/dev/null | sed -n 2p || true)
if [ -n "$PREV" ]; then
    echo -e "\n【5】★★★ 與上次（$(basename "$PREV")）的差異"
    echo "  ── 新增 ──"
    comm -13 <(sort "$PREV") <(sort "$OUT/assets-$TS.csv") | sed 's/^/  ★★ + /' | head -20
    echo "  ── 消失 ──"
    comm -23 <(sort "$PREV") <(sort "$OUT/assets-$TS.csv") | sed 's/^/  ★ - /' | head -20
else
    echo -e "\n【5】★ 第一次掃描，無可比對的基準"
fi

# ═══ ★★ 稽核記錄 ═══
cat >> "$OUT/AUDIT.log" <<EOF
$(date -Is) | $(whoami)@$(hostname) | 範圍: $RANGE | 主機: $COUNT | 檔案: scan-$TS
EOF

echo -e "\n★★ 完成。稽核記錄：$OUT/AUDIT.log"
```

```bash
$ sudo install -m750 asset-scan.sh /usr/local/bin/asset-scan
$ sudo asset-scan 10.10.20.0/24

═══ 資產盤點  10.10.20.0/24  2026-08-28 16:20:11 ═══
★★ 執行者: admin@mgmt01

【1】主機探測（ARP/ICMP）
  ★ 發現 18 台主機

【2】埠掃描與服務辨識（★ 只掃常用埠，T3 保守）
  ★ 完成，輸出：/var/log/asset-scan/scan-20260828-162011.{nmap,gnmap,xml}

【3】產生報表
  ★ CSV：/var/log/asset-scan/assets-20260828-162011.csv（74 筆）

【4】★★★ 風險項目
  ★★★★ 資料庫/快取對外: 10.10.20.50:3306 (mysql 8.0.39)
  ★★★★ Telnet（明文）: 10.10.20.201:23
  ★★★ RDP 對外: 10.10.20.88:3389
  ★★ SNMP: 10.10.20.1:161（★ 檢查是否還在用 public）

【5】★★★ 與上次（assets-20260821-162011.csv）的差異
  ── 新增 ──
  ★★ + 10.10.20.99,,8080,tcp,open,http-proxy,Squid 5.7
  ── 消失 ──
  ★ - 10.10.20.77,,443,tcp,open,ssl/http,nginx 1.18.0
```

```bash
# ═══ ★★ 輸出格式 ═══
$ sudo nmap -sV -oN scan.txt 10.10.20.31        # ★ 一般文字
$ sudo nmap -sV -oX scan.xml 10.10.20.31        # ★★★ XML（★ 給程式解析）
$ sudo nmap -sV -oG scan.gnmap 10.10.20.31      # ★★ grep 友善
$ sudo nmap -sV -oA scan 10.10.20.31            # ★★★ 三種都輸出

# ★★ XML 轉 HTML 報表
$ sudo apt install -y xsltproc
$ xsltproc scan.xml -o scan.html

# ★★★ 用 grep 快速篩選
$ grep '/open/' scan.gnmap | awk '{print $2}' | sort -u        # ★ 有開埠的主機
$ grep -oP '\d+/open/tcp//\K[a-z-]+' scan.gnmap | sort | uniq -c | sort -rn
     18 http
     18 ssh
      4 mysql                                   # ★★★ 4 台 MySQL 對外？

# ★★ ndiff 比對兩次掃描
$ ndiff scan-old.xml scan-new.xml
```

---

## 完整實戰範例：驗證防火牆設定

```bash
# ═══ ★★★★ 情境：確認新設的防火牆規則是否正確 ═══

# ═══ ★★★【1】在伺服器上看「真相」 ═══
$ ssh app01 'sudo ss -tlnp' | awk 'NR>1 {print $4, $NF}'
0.0.0.0:22    users:(("sshd",pid=890,fd=3))
0.0.0.0:80    users:(("nginx",pid=1234,fd=6))
0.0.0.0:443   users:(("nginx",pid=1234,fd=8))
127.0.0.1:3306 users:(("mysqld",pid=5678,fd=25))
127.0.0.1:9000 users:(("php-fpm",pid=1200,fd=7))
#   ★★★ 內部真相：五個服務在監聽，其中兩個只綁本機

$ ssh app01 'sudo nft list ruleset' | grep -A10 'chain input'
        chain input {
                type filter hook input priority filter; policy drop;
                ct state established,related accept
                iif "lo" accept
                icmp type { destination-unreachable, time-exceeded, echo-request } accept
                tcp dport { 22, 80, 443 } accept
        }
#   ★★★ 規則：只放行 22/80/443

# ═══ ★★★★【2】從外部驗證 ═══
$ sudo nmap -Pn -sS -p 22,80,443,3306,9000,8080 10.10.20.31
PORT     STATE    SERVICE
22/tcp   open     ssh
80/tcp   open     http
443/tcp  open     https
3306/tcp filtered mysql                    # ★★★ 被防火牆擋住（正確）
8080/tcp filtered http-proxy
9000/tcp filtered cslistener               # ★★★ 正確
#   ★★★★ filtered = DROP 生效

# ═══ ★★★【3】全埠掃描確認沒有漏網之魚 ═══
$ sudo nmap -Pn -sS -p- -T4 --max-retries 1 10.10.20.31
Not shown: 65532 filtered tcp ports no-response
PORT    STATE SERVICE
22/tcp  open  ssh
80/tcp  open  http
443/tcp open  https
#   ★★★★ 只有三個 open → 防火牆設定正確

# ═══ ★★★【4】從不同來源測試（★ 驗證來源限制）═══
#   ★★ 從管理網段
$ sudo nmap -Pn -p 22 10.10.20.31
22/tcp open ssh                            # ★ 可以

#   ★★ 從一般使用者網段（★ 應該擋掉）
$ ssh user-vlan-host 'sudo nmap -Pn -p 22 10.10.20.31'
22/tcp filtered ssh                        # ★★★ 正確被擋

# ═══ ★★★【5】TLS 設定檢查 ═══
$ sudo nmap --script "ssl-cert,ssl-enum-ciphers" -p 443 10.10.20.31
| ssl-cert: Subject: commonName=app.example.gov.tw
| Not valid after:  2026-09-29T23:59:59
| ssl-enum-ciphers:
|   TLSv1.2:
|     ciphers:
|       TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384 - A
|   TLSv1.3:
|       TLS_AKE_WITH_AES_256_GCM_SHA384 - A
|_  least strength: A                      # ★★★★ 全 A，正確

#   ★★★ 如果看到這些就要修正：
#     SSLv3 / TLSv1.0 / TLSv1.1        → ★★★★ 停用舊協定
#     TLS_RSA_WITH_*                    → ★★★ 沒有前向保密
#     *_CBC_*                           → ★★ 建議改用 GCM
#     least strength: C 或 D            → ★★★★ 有弱密碼套件

# ═══ ★★【6】安全標頭 ═══
$ sudo nmap --script http-security-headers -p 443 10.10.20.31
| http-security-headers:
|   Strict_Transport_Security:
|     max-age=31536000; includeSubDomains
|   X_Frame_Options: SAMEORIGIN
|   X_Content_Type_Options: nosniff
|_  Content_Security_Policy: (not set)     # ★★★ 缺 CSP

# ═══ ★★★★【7】比對結果 ═══
#   ss 說有 5 個服務監聽
#   nmap 說外部只看得到 3 個
#   → ★★★★ 差異的 2 個（3306, 9000）本來就只綁 127.0.0.1
#   → ★★★ 加上防火牆的 DROP，形成雙重防護 → 正確
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| **`Host seems down`** ★★★ | 目標擋 ICMP | **`-Pn`** |
| **UDP 掃描超級慢** ★★★★ | ICMP 速率限制 | **`--top-ports 20`**；`--max-retries 1` |
| **全部 `filtered`** ★★★ | 防火牆 DROP／來源被擋 | 換來源測試；確認授權 |
| **`-sS` 說要 root** ★★ | SYN 掃描需要 raw socket | `sudo`；或用 `-sT` |
| **掃描被封鎖** ★★★ | IDS/fail2ban | 降速 `-T2`；**事先協調** |
| **結果不一致** ★★★ | 有負載平衡器／CDN | 直接掃後端 IP |
| **`-A` 掃很久** ★★ | 太多探測 | 拆開執行；只做需要的 |
| **`ss` 與 `nmap` 結果不同** ★★★★ | **這是正常的** | 差異就是防火牆的效果 |
| **掃到自己的 NAT IP** ★★ | 經過 NAT | 從內網掃；確認拓撲 |
| **版本辨識不準** ★★ | 服務改過 banner | 交叉比對；用 `-sV --version-all` |

### 排查

```bash
# 【1】★★★ 確認目標可達
$ ping -c 2 10.10.20.31
$ ip route get 10.10.20.31
$ traceroute -n 10.10.20.31

# 【2】★★ 看 nmap 做了什麼
$ sudo nmap -v -v -p 443 10.10.20.31          # ★ 詳細輸出
$ sudo nmap --packet-trace -p 443 10.10.20.31 # ★★★ 每個封包
$ sudo nmap --reason -p 443 10.10.20.31       # ★★★ 為什麼判定為這個狀態
PORT    STATE    SERVICE REASON
443/tcp open     https   syn-ack ttl 64
3306/tcp filtered mysql  no-response          # ★★★ 沒有回應 = DROP

# 【3】★★ 同時抓包驗證
$ sudo tcpdump -i any -nn 'host 10.10.20.31 and port 3306' &
$ sudo nmap -Pn -p 3306 10.10.20.31
#   ★★★ 只看到自己的 SYN，沒有任何回應 → 確認是 DROP

# 【4】★★ 對照內部真相
$ ssh 10.10.20.31 'sudo ss -tlnp'

# 【5】★ 除錯層級
$ sudo nmap -d 10.10.20.31                    # -d 到 -d9
```

---

## 安全性注意事項

> [!danger] 五個要點 ★★★★
> ```
> ① ★★★★ 未授權的掃描可能違法
>      → ★★★ 刑法 358、360 條
>      → ★★★★ 一定要有【書面授權】與明確的範圍
>
> ② ★★★★ exploit / dos 類腳本絕對不要對正式環境使用
>      → 會造成服務中斷
>      → ★★★ vuln 類也要謹慎（部分會送 payload）
>
> ③ ★★★ 掃描結果本身是【高度敏感】的資訊
>      → 完整的攻擊面地圖
>      → ★★★★ chmod 600；不要放在共享目錄
>      → ★★ 保存期限與銷毀程序
>
> ④ ★★★ 事先通知資安單位
>      → ★★★★ 沒通知的話會被當成攻擊事件處理
>      → ★★ 你的帳號可能被停權
>
> ⑤ ★★ 老舊設備可能被掃當機
>      → ★★★★ 網路印表機、IP 攝影機、PLC、醫療設備
>      → ★★★ 對這類設備用 -T2 且限制埠範圍
> ```

```bash
# ★★★ 掃描前的檢查清單
$ cat > /usr/local/share/scan-checklist.md <<'EOF'
# 掃描前檢查清單

- [ ] ★★★★ 已取得書面授權（授權文號：________）
- [ ] ★★★ 掃描範圍已明確定義（IP 範圍：________）
- [ ] ★★★ 時間窗已確認（________ 至 ________）
- [ ] ★★★ 已通知資安單位（通知時間：________）
- [ ] ★★ 已通知系統管理員
- [ ] ★★★ 已排除脆弱設備（印表機/攝影機/醫療/PLC）
- [ ] ★★ 已選定適當的時間範本（正式環境用 -T2/-T3）
- [ ] ★★★ 不使用 exploit / dos 類腳本
- [ ] ★★ 結果的保存位置與權限已規劃
- [ ] ★★ 結果的銷毀時程已定義
EOF

# ★★★ 掃描結果的保護
$ sudo chmod 700 /var/log/asset-scan
$ sudo find /var/log/asset-scan -type f -exec chmod 600 {} \;
$ sudo chown -R root:adm /var/log/asset-scan

# ★★ 定期銷毀
$ sudo tee /etc/cron.d/scan-cleanup >/dev/null <<'EOF'
0 3 * * 0 root find /var/log/asset-scan -name 'scan-*' -mtime +90 -exec shred -u {} \;
EOF

# ★★★ 排除脆弱設備
$ cat > /etc/nmap/fragile-hosts.txt <<'EOF'
10.10.20.201
10.10.20.202
10.10.40.0/24
EOF
$ sudo nmap -sn 10.10.0.0/16 --excludefile /etc/nmap/fragile-hosts.txt

# ★★★ 偵測是否有人在掃描你（★ 防守方）
$ sudo tcpdump -i any -nn 'tcp[tcpflags] == tcp-syn' -c 1000 2>/dev/null | \
    awk '{split($3,a,"."); print a[1]"."a[2]"."a[3]"."a[4]}' | \
    sort | uniq -c | sort -rn | awk '$1 > 50 {print "★★★ 疑似掃描: " $2 " ("$1" SYN)"}'

$ sudo nft add rule inet filter input tcp flags syn \
    limit rate over 20/second counter drop comment "port-scan-limit"

# ★★ fail2ban 的 portscan jail
$ sudo tee /etc/fail2ban/jail.d/portscan.conf >/dev/null <<'EOF'
[portscan]
enabled  = true
filter   = portscan
logpath  = /var/log/kern.log
maxretry = 5
findtime = 60
bantime  = 3600
EOF
```

---

## 速查表

### ★★★★ 使用前

```
① 書面授權（明確的 IP 範圍與時間窗）
② 通知資安單位與系統管理員
③ 排除脆弱設備（印表機/攝影機/PLC/醫療）
④ 正式環境用 -T2 或 -T3，不要 -p- 全掃
★★★★ 不使用 exploit / dos 類腳本
```

### 基本掃描

```bash
sudo nmap -sn 10.10.20.0/24              # ★★★ 只找活主機
sudo nmap -Pn 10.10.20.31                # ★★★ 目標擋 ICMP 時
sudo nmap -sS -T4 10.10.20.31            # ★★★ SYN 掃描
sudo nmap -F 10.10.20.31                 # ★★ 快速（前 100 埠）
sudo nmap -p- 10.10.20.31                # ★★ 全埠（慢）
sudo nmap -sU --top-ports 20 10.10.20.31 # ★★★ UDP（★ 一定要限制範圍）
sudo nmap -sV 10.10.20.31                # ★★★ 服務版本
sudo nmap --reason -p 443 10.10.20.31    # ★★★ 為什麼是這個狀態
```

### ★★★ 狀態判讀

```
open              有服務在監聽
closed            主機活著但沒服務（回 RST）
★★★★ filtered     防火牆 DROP（沒有任何回應）
open|filtered     ★★★ UDP 常見，無法判斷
```

### ★★★ 實用 NSE

```bash
sudo nmap --script "ssl-cert,ssl-enum-ciphers" -p 443 host   # ★★★★ TLS 檢查
sudo nmap --script http-security-headers -p 443 host
sudo nmap --script http-methods -p 443 host                  # ★★ TRACE 該關
sudo nmap --script smb2-security-mode -p 445 host
sudo nmap --script "safe and not intrusive" host             # ★★★ 安全的
★★★★ 不要用：--script "exploit" / "dos"
```

### ★★★ 輸出

```bash
sudo nmap -sV -oA scan host              # ★★★ 三種格式
xsltproc scan.xml -o scan.html           # ★★ HTML 報表
ndiff old.xml new.xml                    # ★★★ 比對兩次掃描
grep '/open/' scan.gnmap | awk '{print $2}'
```

### ★★★★ ss vs nmap

```
ss -tulnp   → ★★★★ 內部真相（100% 準確，知道是哪個程序）
nmap        → ★★★ 外部視角（受防火牆影響）
★★★★ 兩者的【差異】就是防火牆的效果 → 這才是驗證的重點
```

### ★★★ 資產盤點風險項目

```
★★★★ 3306/5432/6379/27017/11211/9200/2375 對外 = 資料庫暴露
★★★★ 23 (Telnet) = 明文
★★★ 21 (FTP)、3389 (RDP)、5900 (VNC) 對外
★★ 161 (SNMP) = 檢查 community string
```

---

## 練習題

> [!question]- 練習 1：ss vs nmap ★★★★
> 1. **在你自己的機器 `sudo ss -tulnp`** → 記下所有監聽的埠
> 2. **從另一台 `sudo nmap -Pn -p- <你的IP>`** → 看到幾個？
> 3. **兩者的差異是什麼？為什麼？**
> 4. 關掉防火牆再掃一次 → 呢？
> 5. **哪一個是「真相」？哪一個是「外部視角」？**
> 6. **兩者都要看的理由是什麼？**

> [!question]- 練習 2：狀態判讀 ★★★
> 1. 用 `nft`/`iptables` 對某個埠設 **DROP** → 掃描 → 狀態是？
> 2. 改成 **REJECT** → 呢？
> 3. **完全關掉防火牆但服務也停掉** → 呢？
> 4. **用 `--reason` 看每種情況的原因**
> 5. **同時用 tcpdump 抓包驗證**
> 6. **三種狀態各對應什麼封包行為？**

> [!question]- 練習 3：UDP 掃描 ★★★
> 1. **`time sudo nmap -sU -p 1-200 <目標>`** → 花多久？
> 2. **`time sudo nmap -sU --top-ports 20 <目標>`** → 呢？
> 3. **為什麼 UDP 這麼慢？**
> 4. 加 `--max-retries 1` → 快多少？
> 5. **加 `-sV` 結果更準嗎？**
> 6. 用 `sysctl net.ipv4.icmp_ratelimit` 看速率限制

> [!question]- 練習 4：TLS 檢查 ★★★★
> 1. **`sudo nmap --script ssl-enum-ciphers -p 443 <你的網站>`**
> 2. **`least strength` 是多少？**
> 3. 有 TLSv1.0 / 1.1 嗎？有 CBC 的密碼套件嗎？
> 4. **修改 nginx 的 `ssl_protocols` 和 `ssl_ciphers` 再測**
> 5. `--script ssl-cert` → **憑證還有幾天到期？**
> 6. **`--script http-security-headers`** → 缺哪些標頭？

> [!question]- 練習 5：資產盤點 ★★★
> 1. **把 `asset-scan` 腳本裝起來**（★ 只對自己的測試網段）
> 2. 執行一次，看產生的 CSV
> 3. **風險項目有哪些？**
> 4. **在某台機器多開一個服務，一週後再掃** → 差異比對抓到了嗎？
> 5. 用 `ndiff` 比對兩次的 XML
> 6. **寫一份包含授權檢查清單的盤點作業程序**

---

## 小測驗

Q1. **對自己管理的機器，為什麼 `ss` 比 `nmap` 準確**？nmap 的價值在哪？

Q2. **執行掃描前必須完成哪三件事**？

Q3. **`open`、`closed`、`filtered` 三種狀態分別代表什麼封包行為**？

Q4. **為什麼 UDP 掃描特別慢**？實務上怎麼做？

Q5. **`-Pn` 什麼時候必須加**？

Q6. **`-sS` 和 `-sT` 的差別**？各有什麼優缺點？

Q7. **`--script vuln`、`exploit`、`dos` 三類的差別**？哪些絕對不能對正式環境用？

Q8. **`server_tokens off` 能防止什麼？不能防止什麼**？

Q9. **掃描會對目標造成哪四種影響**？

Q10. **資產盤點時，哪些埠出現在對外介面應該立刻警覺**？

> [!question]- 測驗答案
> **Q1.** 因為 **`ss` 直接向核心查詢 socket 狀態，是 100% 準確的內部真相**，
> 而且**知道是哪一個程序在監聽**（`-p`）。
> `nmap` 是**從外部發封包探測**，結果會被防火牆、NAT、負載平衡器影響 ——
> 它只能告訴你「從這個位置看過去，看得到什麼」。
> **★★★ nmap 的真正價值有四個**：
> ①**驗證防火牆規則** —— 「我設了規則，外面到底看不看得到？」；
> ②**資產盤點** —— 整個網段有哪些機器、開了什麼服務，
> 特別是找出「沒人記得還活著」的老機器；
> ③**外部視角的資安檢查** —— 攻擊者看到的是什麼；
> ④**找出未經核准的服務**。
> **★★★★ 最有價值的做法是「兩者都跑，比對差異」** ——
> 差異的部分就是防火牆實際發揮的效果。
>
> **Q2.** ①**★★★★ 取得書面授權** —— 明確記載**IP 範圍與時間窗**。
> 未授權的埠掃描在台灣可能觸犯刑法第 358 條（入侵電腦罪）
> 或第 360 條（干擾電腦罪）；
> ②**★★★ 通知資安單位與系統管理員** ——
> 掃描會觸發 IDS/IPS 告警，沒通知的話**會被當成攻擊事件處理**，
> 你的帳號可能被停權，還要花時間解釋；
> ③**★★★ 記錄掃描的目的、範圍、時間、執行人** ——
> 這是稽核要求，也是保護你自己。
> **另外要做的準備**：**排除脆弱設備**
> （網路印表機、IP 攝影機、PLC、醫療設備 —— 這些可能被掃當機）、
> 選擇適當的時間範本（正式環境用 `-T2`/`-T3`）、
> 規劃結果的保存權限與銷毀時程。
>
> **Q3.** **`open`** = 送 SYN 後**收到 SYN-ACK** —— 有服務在監聽並接受連線。
> **`closed`** = 送 SYN 後**收到 RST** ——
> 主機是活的且可達，但那個埠沒有服務在監聽
> （表示中間沒有防火牆，或防火牆用 REJECT）。
> **★★★★ `filtered`** = **完全沒有任何回應**（或收到 ICMP unreachable）——
> 這是**防火牆用 DROP** 的特徵，封包被靜默丟棄。
> **判讀意義**：
> `closed` 多表示主機沒有防火牆或用 REJECT（會暴露主機存在）；
> **`filtered` 多表示防火牆在 DROP，這是比較好的設定**。
> 另外 **`filtered` 也是掃描慢的主因** —— nmap 必須等 timeout 並重試。
> 用 **`--reason`** 可以看到判定依據（`syn-ack` / `reset` / `no-response`）。
>
> **Q4.** 因為 **UDP 沒有交握，「沒有回應」無法區分是 open 還是被擋**。
> 送出 UDP 封包後三種結果：
> ①收到 UDP 回應 → `open`（但**大多數 UDP 服務不會回應無效的探測**）；
> ②收到 ICMP port unreachable → `closed`；
> ③**什麼都沒收到 → `open|filtered`，無法判斷**。
> **情況③要等 timeout 而且會重試**，
> 更糟的是 **Linux 對 ICMP unreachable 有速率限制**
> （`net.ipv4.icmp_ratelimit`，預設每秒約 1 個）——
> 掃 1000 個 closed 的 UDP 埠，**光是等 ICMP 回應就要 1000 秒**。
> **實務做法**：
> ```bash
> sudo nmap -sU --top-ports 20 目標          # ★★★★ 只掃常用埠
> sudo nmap -sU -sV -p 53,123,161,500 目標   # ★★ -sV 用協定探測更準
> sudo nmap -sU --max-retries 1 --top-ports 20 目標
> ```
>
> **Q5.** **當目標主機擋 ICMP（不回應 ping）時必須加**。
> nmap 預設會**先做主機探測**（ICMP echo + TCP SYN 80/443 等），
> 判定主機「活著」才進行埠掃描。
> **很多機關的主機基於資安政策會擋掉 ICMP** ——
> 這時 nmap 會直接回報 **`Host seems down`** 而**完全不掃描任何埠**，
> 你會誤以為主機不存在。
> **`-Pn` 的意思是「跳過主機探測，假設主機是活的，直接掃埠」**。
> ```bash
> sudo nmap -Pn -p 22,80,443 10.10.20.31
> ```
> 代價是**掃描不存在的主機時會很慢**（每個埠都要等 timeout），
> 所以掃大網段時要搭配 `--host-timeout`。
> 同網段的話可以改用 **`-PR`（ARP 探測）** ——
> ARP 是 L2 協定，**防火牆擋不掉**，最可靠。
>
> **Q6.** **`-sS`（SYN 掃描，又稱半開掃描）** ——
> 只送 SYN，收到 SYN-ACK 就判定為 open，**然後送 RST 中斷，不完成三次交握**。
> **優點**：快（少一次往返）、**不會在目標的應用程式留下完整的連線紀錄**、
> 消耗的資源少。**缺點**：**需要 root**（要建 raw socket）。
> **`-sT`（TCP connect 掃描）** ——
> 使用作業系統的 `connect()` 系統呼叫，**完成完整的三次交握**。
> **優點**：**不需要 root**、在某些受限環境（如透過 proxy）是唯一可行的方式。
> **缺點**：慢、**會在目標的應用程式日誌留下完整的連線紀錄**
> （nginx 的 access log 會出現一筆）、消耗較多資源。
> **實務**：有 root 就用 `-sS`（nmap 的預設），沒有才用 `-sT`。
>
> **Q7.** **`vuln`** = **檢測**是否存在已知漏洞。
> 部分腳本會**實際發送 payload** 來確認，**可能造成服務異常** ——
> **需要書面授權**才能使用。
> **`exploit`** = **實際利用**漏洞取得存取權。
> **★★★★ 這是攻擊行為**，只能在有明確授權的滲透測試中使用，
> **絕對不要對正式環境使用**。
> **`dos`** = **測試阻斷服務**。
> **★★★★ 會讓服務掛掉**，絕對不要對正式環境使用。
> **絕對不能對正式環境用的是 `exploit` 和 `dos`**，
> `vuln` 要有授權且謹慎。
> **安全的做法**：
> ```bash
> sudo nmap --script "safe and not intrusive" 目標
> ```
>
> **Q8.** **`server_tokens off` 能防止的**：
> 在 HTTP 回應標頭與錯誤頁面中**顯示 nginx 的版本號**，
> 讓 `Server: nginx/1.24.0` 變成 `Server: nginx`。
> 這**延緩了**攻擊者用 `searchsploit nginx 1.24.0` 直接查對應漏洞的速度。
> **★★★★ 不能防止的**：
> ①**`-sV` 仍可能透過行為特徵推測版本**（回應的細微差異、支援的功能）；
> ②**它完全不修補任何漏洞** —— 有漏洞的版本還是有漏洞，
> 攻擊者可以直接**盲打 payload** 試試看，不需要先知道版本；
> ③其他管道仍會洩漏（錯誤頁面的格式、特定的 header 順序、
> `X-Powered-By`、cookie 名稱）。
> **★★★★ 真正的防護是「保持更新」+「最小暴露面」** ——
> 隱藏版本只是降低雜訊，不是安全措施。
>
> **Q9.** ①**★★★ 消耗目標資源** ——
> 每個 SYN 都建立半開連線佔用 backlog，
> `-T5` 掃 65535 個埠**可能讓小型設備當機**
> （網路印表機、IP 攝影機、PLC、老舊嵌入式設備**特別脆弱**）；
> ②**★★★ 觸發 IDS/IPS 告警** ——
> 資安單位會收到通知，**沒事先協調就會被當成攻擊事件**；
> ③**★★ 觸發自動封鎖** ——
> fail2ban、WAF、雲端 DDoS 防護可能把你的 IP 封鎖；
> ④**★★ 產生大量日誌** —— 目標的 access log / kern.log 被洗版，
> 可能把真正重要的事件淹沒。
> **降低影響的做法**：正式環境用 **`-T2`（polite）或 `-T3`**、
> **限制埠範圍**（不要 `-p-`）、離峰時段執行、事先通知。
>
> **Q10.** **★★★★ 資料庫與快取服務**：
> **3306（MySQL）、5432（PostgreSQL）、6379（Redis）、
> 27017（MongoDB）、11211（Memcached）、9200（Elasticsearch）** ——
> 這些**只應該綁 `127.0.0.1` 或內網介面**。
> **Redis 對外且沒密碼是經典的入侵途徑**
> （攻擊者可直接寫入 SSH authorized_keys）。
> **★★★★ 明文協定**：**23（Telnet）**、21（FTP）——
> 帳號密碼完全明文傳輸，應該改用 SSH/SFTP。
> **★★★ 遠端桌面**：3389（RDP）、5900（VNC）——
> 對外開放是勒索軟體最常見的入口，應該走 VPN。
> **★★★ 管理介面**：**2375（Docker API 未加密）**——
> 等同於 root shell；9000（php-fpm）、5601（Kibana）。
> **★★ SNMP（161）** —— 檢查是否還在用預設的 `public` community string。

---

## 延伸閱讀

- [[03-ss-netstat-與lsof]] — **★★★ 自己的機器用 `ss` 更準確**
- [[01-tcpdump-基礎抓包]] — 驗證掃描結果
- [[02-防火牆-ufw基礎與實務]] — 防火牆規則的設定
- [[08-系統強化與稽核]] — Lynis、CIS 基準
- [[12-憑證生命週期管理]] — TLS 設定與憑證監控
- [[11-資訊設備盤點]] — 資產管理制度
