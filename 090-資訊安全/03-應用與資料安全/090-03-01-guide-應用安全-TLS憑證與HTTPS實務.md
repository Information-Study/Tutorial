---
title: "TLS 憑證與 HTTPS 實務"
desc: "憑證裝上去之後的事：協定版本取捨、加密套件怎麼選、HSTS 的不可逆風險、OCSP stapling 與憑證鏈完整性，並用 testssl.sh 把站台調到 A 級"
aliases: [tls, ssl, https, hsts, testssl, ocsp-stapling]
tags: [群組/資訊安全, 安全/tls, 主題/加密]
category: 應用與資料安全
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[060-02-02-06-guide-Nginx-HTTPS與Certbot]]", "[[090-01-01-guide-PKI-PKI與憑證基礎]]"]
updated: 2026-09-03
---

# TLS 憑證與 HTTPS 實務

## 這篇你會學到

> [!abstract] 學習目標
> - 看懂 TLS 交握的四個階段，能從錯誤訊息判斷是**哪一段**談不攏
> - ★★★★★ 正確處理**協定版本**：停用 TLS 1.0／1.1 之前，先從日誌證明沒有舊客戶端還在用
> - ★★★★ 用**產生器與檢測工具**決定加密套件，而不是從網路上抄一份三年前的清單
> - ★★★★★ 理解 HSTS 是**不可逆**的，知道 `includeSubDomains` 與 `preload` 開下去代表什麼
> - ★★★★ 診斷**憑證鏈不完整**：為什麼桌機瀏覽器正常、手機與舊 Java 客戶端卻連不上
> - 設定 OCSP stapling、session resumption，並知道 HTTP/2 與 HTTP/3 的前提條件
> - 跑一次完整流程：一台只有 HTTP 的 Nginx →設定 →`testssl.sh` 檢測 →逐項修正 →再檢測到 A 級

### 這篇與憑證專章的分工 ★★★★★

`090-01` 憑證與 PKI 專章（14 篇）已經把「**憑證怎麼來**」寫透了：CSR 怎麼產、
CN／SAN 怎麼填、向 CA 怎麼申請、自建 CA 怎麼簽、憑證怎麼續期與盤點。

**這篇完全不重寫那些。** 這篇的定位是：

> **憑證檔案已經放到伺服器上了，接下來 HTTPS 這條連線本身怎麼調對。**

| 問題 | 去哪一篇 |
| --- | --- |
| 憑證要怎麼申請、CSR 怎麼產 | [[090-01-02-guide-PKI-CSR產生與req設定檔]]、[[090-01-03-guide-PKI-向CA申請憑證]] |
| CN 與 SAN 要填什麼才被瀏覽器接受 | [[090-01-04-guide-PKI-CN與SAN設定與瀏覽器相容性]] |
| 自建 CA、中繼 CA、憑證鏈怎麼組出來 | [[090-01-07-guide-PKI-自建中繼CA與憑證鏈]] |
| 憑證檔要放哪、各服務怎麼掛上去 | [[090-01-10-guide-PKI-憑證部署到各服務]] |
| PEM／DER／PFX 轉換、怎麼看憑證內容 | [[090-01-11-guide-PKI-憑證格式轉換與檢視工具]] |
| 到期監控、續期自動化、憑證盤點 | [[090-01-12-guide-PKI-憑證生命週期管理]] |
| 機關要向 GCA／TWCA 申請 | [[090-01-14-guide-PKI-機關憑證來源GCA與TWCA]] |
| **憑證裝好了，但 SSL Labs 只給 B** | ← **這篇** |
| **要不要停用 TLS 1.0／1.1，怎麼確認可以停** | ← **這篇** |
| **HSTS 該不該開、preload 敢不敢送** | ← **這篇** |
| **手機連不上但電腦可以** | ← **這篇** |

> [!tip] 一句話記住分工
> PKI 專章管的是**憑證這張紙**；這篇管的是**握手這個動作**。
> 紙沒問題不代表握手沒問題 —— 機關站台九成的 HTTPS 客訴，問題出在握手不在紙上。

---

## 前置知識

動筆前你應該已經會下面這些，沒把握的先回去補：

| 需要的基礎 | 篇章 |
| --- | --- |
| Nginx 基本設定與 `server` 區塊 | [[060-02-02-02-guide-Nginx-設定語法與虛擬主機]] |
| Nginx 上 HTTPS 與 Certbot 的基本掛法 | [[060-02-02-06-guide-Nginx-HTTPS與Certbot]] |
| 憑證、私鑰、CA、憑證鏈這些名詞 | [[090-01-01-guide-PKI-PKI與憑證基礎]] |
| Apache 的 HTTPS 掛法（對照用） | [[060-02-03-05-guide-Apache-HTTPS設定]] |
| DNS 解析與 `dig` 排查 | [[060-01-04-06-guide-dig-與DNS排查]] |
| Nginx 日誌格式與除錯 | [[060-02-02-07-guide-Nginx-日誌與除錯]] |

環境假設（全篇以此為準）：

- Ubuntu 22.04 / 24.04 LTS，Nginx 由官方或發行版套件安裝
- OpenSSL 3.x（`openssl version` 確認）
- 站台網域 `www.example.gov.tw`，憑證已經放在 `/etc/ssl/example/`
- 你有 `sudo` 權限，且能重載 Nginx

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> - 設定檔位置：Nginx 為 `/etc/nginx/conf.d/*.conf`（沒有 `sites-available`／`sites-enabled` 慣例）
> - Apache 叫 `httpd`，設定在 `/etc/httpd/conf.d/ssl.conf`
> - RHEL 8／9 有**系統層的加密政策**：`update-crypto-policies --show`，
>   預設 `DEFAULT` 已經停用 TLS 1.0／1.1。這一層會**蓋過**應用程式設定，
>   排錯時務必先看它：`update-crypto-policies --show` 回 `DEFAULT` 或 `FUTURE`。
>   要放寬給舊系統用 `update-crypto-policies --set LEGACY`（★★★★ 全機生效，不是只有這個站台）。
> - SELinux 啟用時，憑證檔要有正確 context：`restorecon -Rv /etc/pki/tls/`

---

## 觀念說明

### TLS 交握在做什麼 ★★★

不需要懂密碼學細節，但要懂到**能判讀錯誤訊息落在哪一段**。把交握拆成四件事：

| 階段 | 在做什麼 | 談不攏會看到什麼 |
| --- | --- | --- |
| ① 協定版本協商 | 客戶端說「我支援到 TLS 1.3」，伺服器挑一個雙方都有的版本 | `no protocols available`、`unsupported protocol`、`TLSV1_ALERT_PROTOCOL_VERSION` |
| ② 加密套件協商 | 從雙方共同支援的 cipher suite 挑一個 | `no shared cipher`、`SSL_ERROR_NO_CYPHER_OVERLAP`、`handshake failure` |
| ③ 伺服器身分驗證 | 伺服器送出憑證鏈，客戶端往上驗到自己信任的根 | `unable to get local issuer certificate`、`self signed certificate in certificate chain`、`NET::ERR_CERT_AUTHORITY_INVALID` |
| ④ 金鑰交換與完成 | 算出這條連線的對稱金鑰，之後的資料用它加密 | 很少單獨失敗，通常是前三段的連帶結果 |

> [!note] ★★★ 判讀口訣
> - 錯誤訊息裡有 **protocol** ／ **version** → 第 ① 段，版本問題
> - 錯誤訊息裡有 **cipher** ／ **no shared** → 第 ② 段，加密套件問題
> - 錯誤訊息裡有 **certificate** ／ **issuer** ／ **verify** → 第 ③ 段，憑證或憑證鏈問題
> - 錯誤訊息裡有 **name** ／ **hostname mismatch** → 第 ③ 段的子問題，SAN 沒涵蓋這個名字

還有兩個貫穿全程的關鍵字：

- **SNI（Server Name Indication）** ★★★★：客戶端在交握**最一開始**、還沒加密之前，
  就告訴伺服器「我要連的是 `www.example.gov.tw`」，伺服器才知道要拿哪一張憑證出來。
  一台機器上多個 HTTPS 站台全靠這個。用 `openssl s_client` 測試時**一定要加 `-servername`**，
  忘了加就會拿到預設站台的憑證，然後你會誤判成「憑證裝錯了」。
- **ALPN（Application-Layer Protocol Negotiation）** ★★★：在交握時順便談好上層要用
  HTTP/1.1 還是 HTTP/2。HTTP/2 over TLS **只能**靠 ALPN 協商，這是後面講 HTTP/2 的前提。

### 協定版本：TLS 1.2 與 1.3 ★★★★★

這是整篇最重要的一段。現在的正確答案很簡單：

> **只開 TLS 1.2 與 TLS 1.3，其他全部關掉。**

| 版本 | 狀態 | 該怎麼辦 |
| --- | --- | --- |
| SSL 2.0 / 3.0 | 早已廢止（POODLE 等） | ★★★★★ 一定要關。現代 OpenSSL 通常連編譯都沒編進去 |
| TLS 1.0 | 已被 IETF 正式棄用（RFC 8996），PCI DSS 不接受 | ★★★★ 關掉。只有極舊的 Windows XP／IE、老舊嵌入式設備需要 |
| TLS 1.1 | 同上，已棄用 | ★★★★ 關掉。實務上沒有客戶端「只支援 1.1」 |
| **TLS 1.2** | 現行主力 | ★★★★★ **必開**。相容性的底線 |
| **TLS 1.3** | 現行最新（RFC 8446） | ★★★★★ **必開**。交握更快（1-RTT）、把不安全的選項直接從協定中拿掉 |

TLS 1.3 相對 1.2 的三個實務差異，是你設定時會踩到的：

1. **TLS 1.3 的 cipher suite 是另一組，`ssl_ciphers` 管不到它。**
   Nginx 要改 TLS 1.3 的套件必須用 `ssl_conf_command Ciphersuites ...`（Nginx 1.19.4+、OpenSSL 1.1.1+）。
   ★★★ 絕大多數情況**不需要改** —— TLS 1.3 只留下五個套件，全部都是安全的。
2. **TLS 1.3 全部都有前向保密（forward secrecy）**，也移除了 RSA 金鑰傳輸、靜態 DH、
   壓縮、重新協商等歷史包袱。所以「TLS 1.3 有沒有選對套件」基本上不是問題。
3. **TLS 1.3 支援 0-RTT（early data）**，第二次連線可以在交握完成前就送資料 ——
   ★★★★ 代價是**有重放（replay）風險**，不要對會改變狀態的請求（POST／PUT／DELETE）開啟。
   Nginx 的 `ssl_early_data on;` 預設是關的，沒有明確需求就別開。

> [!danger] ★★★★★ 停用 TLS 1.0／1.1 之前一定要先做的事
> 機關站台最常見的事故是：資安稽核要求關 TLS 1.0，管理員直接改設定重載，
> 隔天某個十年前的公文交換系統或某台事務機掃描上傳功能全部掛掉，而且**沒有人知道是誰在用**。
>
> **正確順序是：先量測 →再公告 →再停用 →留退路。** 下一節就教怎麼量測。

### 停用前怎麼確認沒有舊客戶端在用 ★★★★★

Nginx 有兩個內建變數可以寫進 access log：

| 變數 | 內容 |
| --- | --- |
| `$ssl_protocol` | 這條連線實際協商出來的協定版本，如 `TLSv1.2`、`TLSv1.3` |
| `$ssl_cipher` | 實際使用的加密套件名稱 |
| `$ssl_session_reused` | `r` 表示這次是重用 session、`.` 表示完整交握 |

在 `http` 區塊定義一個帶 TLS 資訊的日誌格式，掛到要觀察的站台上，跑一到四週再統計。

**做法會在「進階應用」給完整設定與統計指令**，這裡先講判準：

| 統計結果 | 決策 |
| --- | --- |
| TLS 1.0／1.1 佔比 0，連續觀察兩週 | ★★★ 可以直接停用 |
| 佔比極低（< 0.1%）且來源 IP 都是內部固定幾台 | ★★★★ 先找出那幾台是什麼設備，處理完再停 |
| 佔比低但來源 IP 分散在外網 | ★★★★ 很可能是舊手機或掃描器；先公告再停，並準備回滾程序 |
| 佔比 > 1% | ★★★★★ 不要直接停。先查清楚是什麼系統，排時程升級 |

> [!warning] ★★★ 只看 Nginx 日誌會漏掉一種情況
> 如果客戶端連 TLS 1.2 都不支援，它**根本走不到產生 access log 那一步** ——
> 交握在第 ① 段就失敗，只會出現在 `error.log`。所以量測期間也要看：
> `grep -i "no protocols available\|unsupported protocol" /var/log/nginx/error.log`

### 加密套件（cipher suite）怎麼選 ★★★★

> [!danger] ★★★★★ 不要從網路文章抄 cipher suite 清單
> 這是本篇最想阻止你做的事。網路上（包含很多政府與大廠的舊技術文件）的
> `ssl_ciphers ECDHE-RSA-AES256-...` 一長串，多半是好幾年前寫的。抄過來會發生三件事：
> 1. 裡面可能還留著**現在已經視為不安全**的套件（3DES、CBC 模式的舊組合）
> 2. 可能少了**新的、更好的**套件，導致相容性反而變差
> 3. 你**看不懂自己貼了什麼**，稽核問起來答不出來，出事也不知道怎麼改
>
> **正確做法：用產生器產生，用檢測工具驗證。** 這兩件事都不需要你背套件名稱。

一個 cipher suite 名稱其實是四件事拼起來的（以 TLS 1.2 為例）：

```text
ECDHE - RSA - AES128GCM - SHA256
  │      │       │          │
  │      │       │          └── MAC／PRF 雜湊
  │      │       └───────────── 對稱加密演算法與模式（AES-128-GCM）
  │      └───────────────────── 憑證的簽章演算法（伺服器憑證是 RSA 還是 ECDSA）
  └──────────────────────────── 金鑰交換（ECDHE = 橢圓曲線 Diffie-Hellman ephemeral）
```

你需要知道的判準只有四條 ★★★★：

| 判準 | 說明 |
| --- | --- |
| ★★★★★ 金鑰交換一定要是 **ECDHE** 或 **DHE** | 帶 `E`（ephemeral）才有前向保密：私鑰日後外洩，之前錄下的流量也解不開。`RSA` 開頭的靜態金鑰交換一律排除 |
| ★★★★ 對稱加密優先 **AEAD**：`GCM`、`CHACHA20-POLY1305`、`CCM` | AEAD 同時做加密與完整性驗證，避開一整類 padding oracle 攻擊 |
| ★★★★ 排除 **3DES、RC4、NULL、EXPORT、anon、MD5** | 這些是已知弱項（Sweet32、RC4 偏差等） |
| ★★★ **順序決定偏好** | TLS 1.2 時伺服器可以決定要不要照自己的順序挑（`ssl_prefer_server_ciphers`） |

**Mozilla SSL Configuration Generator**（<https://ssl-config.mozilla.org/>）是業界事實標準，
它提供三種相容等級 ★★★★★：

| 等級 | 支援的協定 | 相容範圍 | 什麼時候用 |
| --- | --- | --- | --- |
| **Modern** | 只有 TLS 1.3 | 只有近幾年的瀏覽器與客戶端 | 內部 API、只給新版瀏覽器用的後台。★★ 對外站台通常太激進 |
| **Intermediate** | TLS 1.2 + 1.3 | 絕大多數在用的瀏覽器與作業系統 | ★★★★★ **對外站台的預設答案，九成情況選這個** |
| **Old** | 往回相容到 TLS 1.0 | 含極舊的 XP／IE8 等 | ★★★★ 只在確認有舊客戶端、且已排入汰換時程時暫時使用 |

使用方式：在頁面選 Server（Nginx／Apache）、填入你的版本號、選相容等級，
它會生出**可直接貼上**的設定片段，而且會標示這份設定對應的 guideline 版本與日期。

> [!tip] ★★★ 三個實務要點
> 1. 填**正確的 Nginx／OpenSSL 版本**。填錯版本產生的設定可能用到你的版本沒有的指令，
>    `nginx -t` 會直接報 unknown directive。
> 2. 產生出來的設定**把 guideline 版本寫進註解**，例如
>    `# Mozilla intermediate, generated 2026-09-03`。日後稽核與比對才有依據。
> 3. ★★★★ **每年重新產生一次**並用檢測工具比對，這件事排進年度維運行事曆。
>    憑證會到期你會收到通知，但 cipher suite 過時**沒有人會通知你**。

### 憑證鏈完整性 ★★★★

這是「桌機正常、手機失敗」這類靈異事件的頭號原因。

一張伺服器憑證通常不是由根 CA 直接簽的，中間隔著一到兩層**中繼憑證（intermediate）**：

```text
根 CA 憑證（Root）        ← 內建在作業系統／瀏覽器的信任清單裡，伺服器不用送
    └── 中繼 CA 憑證      ← ★★★★ 伺服器必須送，客戶端通常沒有
            └── 你的伺服器憑證（leaf）  ← 伺服器一定會送
```

伺服器該送出的是 **leaf + 中繼**（不含根，送根只是浪費頻寬）。
少送中繼會發生什麼？

| 客戶端 | 少中繼時的行為 | 結果 |
| --- | --- | --- |
| 桌機 Chrome／Edge／Firefox | 會嘗試從憑證的 **AIA 欄位**自動去抓中繼，或用**快取**中曾經抓過的中繼 | ★★★ **看起來正常** —— 這就是陷阱 |
| Android 舊版、部分 iOS 情境 | AIA 抓取支援不完整 | ★★★★ 顯示憑證不受信任 |
| Java 客戶端（`HttpsURLConnection`、很多公文／繳費介接程式） | **不做 AIA 抓取** | ★★★★★ `PKIX path building failed: unable to find valid certification path` |
| `curl`、`wget`、Python `requests` | 不做 AIA 抓取 | ★★★★ `unable to get local issuer certificate` |
| 手機 App（OkHttp 等） | 多半不做 AIA 抓取 | ★★★★ 連線失敗 |

> [!warning] ★★★★★ 「我用瀏覽器測都正常」不是驗證
> 用你自己的桌機瀏覽器測 HTTPS，是**最沒有參考價值**的驗證方式，因為它會幫你補洞。
> 一定要用 `openssl s_client -showcerts` 或 `curl` 這種**不會自動補中繼**的工具驗證。

Certbot 的檔案命名常見誤用 ★★★★：

| 檔案 | 內容 | Nginx `ssl_certificate` 該指哪個 |
| --- | --- | --- |
| `cert.pem` | **只有** leaf 憑證 | ✗ 指這個就是憑證鏈不完整 |
| `chain.pem` | **只有**中繼憑證 | ✗ 這個是給 `ssl_trusted_certificate`（OCSP stapling）用的 |
| `fullchain.pem` | leaf + 中繼 | ✓ ★★★★★ **就是要指這個** |
| `privkey.pem` | 私鑰 | ✓ 給 `ssl_certificate_key` |

> [!info]- Apache 對照
> Apache 2.4.8 以後，`SSLCertificateFile` **可以**直接放 fullchain（leaf + 中繼），
> 不需要再用 `SSLCertificateChainFile`（該指令已標為過時）。
> ```apache
> SSLCertificateFile      /etc/letsencrypt/live/example/fullchain.pem
> SSLCertificateKeyFile   /etc/letsencrypt/live/example/privkey.pem
> ```
> 如果你看到舊設定還在用 `SSLCertificateChainFile`，它仍能運作但建議合併掉。

### HSTS：不可逆的那一個 ★★★★★

**HTTP Strict Transport Security**：伺服器回一個標頭，告訴瀏覽器
「以後 N 秒內，這個網域**只准用 HTTPS 連**，使用者按繼續也不准」。

```text
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
                           └──── 秒數 ────┘  └── 含所有子網域 ──┘ └ 送進預載清單 ┘
```

它解決的是一個真實問題：使用者在網址列打 `example.gov.tw`（沒有 `https://`），
第一個請求走明文 HTTP，這一下就可能被中間人劫持（SSL stripping）。
有 HSTS 之後，瀏覽器**在送出請求前**就自己改成 HTTPS。

> [!danger] ★★★★★ HSTS 是不可逆的 —— 這是本篇最危險的設定
> 標頭一旦送出去，**瀏覽器就記住了**，記在使用者的電腦裡，你**無法從伺服器端收回**。
>
> 你可以把 `max-age` 改成 `0` 讓「之後再來的人」清掉記錄，但：
> - 已經拿到舊標頭、且在 `max-age` 期間**沒有再回訪**的使用者，記錄仍然有效
> - 如果你的 HTTPS 壞了（憑證過期、憑證鏈斷），這些使用者**看到的是硬錯誤，沒有「繼續前往」按鈕**
> - 你不能請他們「先用 HTTP 將就一下」—— 瀏覽器根本不會送出 HTTP 請求
>
> **開 HSTS 等於承諾：這個網域從今天起永遠有可用的 HTTPS。** 承諾之前先看下面的檢查清單。

三個參數的風險等級不同：

| 參數 | 作用 | 風險 | 建議 |
| --- | --- | --- | --- |
| `max-age=<秒>` | 記憶有效期 | ★★★ 中。改小可讓新訪客的記錄提早失效 | ★★★★ 上線先用 `max-age=300`（5 分鐘）觀察一週，再逐步加到 `31536000`（1 年） |
| `includeSubDomains` | ★★★★★ **所有子網域**一併強制 HTTPS | ★★★★★ 高。包含你忘記的那些子網域 | 開之前必須盤點**所有**子網域 |
| `preload` | 送進瀏覽器**內建**的預載清單 | ★★★★★ 最高。連第一次造訪都不用送標頭，**移除要等好幾個月**，且要等瀏覽器改版才生效 | ★★★★★ 除非你確定整個網域樹永久 HTTPS，否則不要送 |

> [!danger] ★★★★★ `includeSubDomains` 的典型災難
> `example.gov.tw` 開了 `includeSubDomains`。結果機關內部還有：
> - `printer.example.gov.tw` —— 事務機的網頁管理介面，只有 HTTP
> - `old-erp.example.gov.tw` —— 十年前的系統，HTTPS 憑證早就過期
> - `test.example.gov.tw` —— 測試機，用自簽憑證
>
> 這三個**當天全部無法從瀏覽器存取**，而且清不掉（只能請每位使用者手動去
> `chrome://net-internals/#hsts` 刪除，這在機關裡不可行）。
>
> **開之前一定要做的盤點**：把 DNS 區域檔或 DNS 管理介面裡的**每一筆**子網域列出來，
> 逐一確認都有可用的 HTTPS。做不到就不要開 `includeSubDomains`。

**開 HSTS 前的檢查清單 ★★★★★**（全部打勾才可以開）：

- [ ] 憑證有自動續期，而且**續期失敗會告警**（見 [[090-01-12-guide-PKI-憑證生命週期管理]]）
- [ ] 憑證鏈完整，已用 `openssl s_client -showcerts` 驗證過
- [ ] 站台所有頁面都能用 HTTPS 正常運作（沒有 mixed content）
- [ ] HTTP 已經正確 301 導向 HTTPS，而且**沒有導向迴圈**
- [ ] 已用 `max-age=300` 觀察至少一週沒有災情
- [ ] 若要開 `includeSubDomains`：已盤點**全部**子網域且都有可用 HTTPS
- [ ] 若要送 `preload`：上面全部做到，且已取得單位主管同意（★★★★★ 這是長期承諾）

> [!note] ★★★ `preload` 的額外條件
> 送進 <https://hstspreload.org> 的網域必須同時滿足：
> 有效憑證、HTTP 導向到**同主機**的 HTTPS、所有子網域都提供 HTTPS、
> 標頭同時含 `max-age` 至少一年（31536000）、`includeSubDomains`、`preload` 三個指令。
> 送出後要等瀏覽器發新版才生效，**移除同樣要等新版**，通常以月計。

### OCSP stapling ★★★

客戶端要確認「這張憑證有沒有被撤銷」，傳統做法是自己去問 CA 的 OCSP responder。
問題是：慢（多一次網路往返）、而且**洩漏使用者在瀏覽哪個站**。

**OCSP stapling** 把這件事搬到伺服器：伺服器自己定期去問 CA，把**簽了名的回應**
在交握時「釘（staple）」在憑證後面一起送給客戶端。快、不洩漏隱私。

需要三個東西：
1. `ssl_stapling on;`
2. `ssl_stapling_verify on;` + `ssl_trusted_certificate`（指向含中繼與根的檔案，用來驗證 OCSP 回應）
3. `resolver`（Nginx 要能解析 CA 的 OCSP 網址）

> [!warning] ★★★ Stapling 沒生效不會有錯誤畫面
> 它只是**靜靜地沒作用**，`nginx -t` 不會抱怨。要主動驗證：
> `openssl s_client -connect host:443 -servername host -status < /dev/null | grep -A2 "OCSP Response Status"`
> 看到 `OCSP Response Status: successful` 才算成功；看到 `no response sent` 就是沒生效。
>
> 另外 ★★ Nginx 第一次啟動後的**第一個連線**通常還沒抓到 OCSP 回應，
> 要等幾秒或第二次請求才會 staple 成功 —— 測試時不要第一發就下結論。

### Session resumption ★★★

完整交握要做非對稱運算，成本高。同一個客戶端反覆連線時，可以「續用」上次的成果：

| 機制 | 怎麼運作 | Nginx 指令 | 注意 |
| --- | --- | --- | --- |
| **Session ID（cache）** | 伺服器把 session 存在自己的共享記憶體裡，客戶端只帶一個 ID | `ssl_session_cache shared:SSL:10m;`<br>`ssl_session_timeout 1d;` | ★★★ 多台伺服器要黏著同一台，或改用共享儲存 |
| **Session ticket** | 伺服器把 session 加密成票券交給客戶端保管，自己不存 | `ssl_session_tickets on/off;` | ★★★★ 票券金鑰若長期不換，會**破壞前向保密** |

Mozilla 的建議是 ★★★★：**開 session cache、關 session tickets**（`ssl_session_tickets off;`），
除非你有能力做票券金鑰的定期輪替。TLS 1.3 有自己的 resumption 機制，但同樣受這個開關影響。

`shared:SSL:10m` 的 `10m` 是**共享記憶體大小**（約可存 4 萬個 session），不是時間；
時間是 `ssl_session_timeout`。★★★ 這兩個很多人搞混。

### HTTP/2 與 HTTP/3 的前提 ★★★

| 協定 | 傳輸層 | 前提條件 |
| --- | --- | --- |
| HTTP/1.1 | TCP | 無 |
| **HTTP/2** | TCP + TLS | ★★★ 瀏覽器只在 HTTPS 上支援，且靠 **ALPN** 協商。所以**必須先有可用的 TLS**。Nginx 1.9.5+ |
| **HTTP/3** | **UDP** + QUIC（內含 TLS 1.3） | ★★★★ 需要 Nginx 1.25+ 且**編譯時帶 QUIC 支援**；★★★★★ 防火牆要放行 **UDP/443**；要回 `Alt-Svc` 標頭讓瀏覽器知道可以升級 |

Nginx 語法的版本差異 ★★★★（這個很常寫錯）：

```nginx
# Nginx < 1.25.1 的舊寫法（1.25.1 起會出 deprecation 警告）
listen 443 ssl http2;

# Nginx >= 1.25.1 的新寫法：http2 變成獨立指令
listen 443 ssl;
http2 on;
```

> [!note] ★★★ HTTP/3 不是「開了就一定變快」
> 它主要改善**高延遲、高丟包**的行動網路體驗。機關內網或有線環境的收益有限，
> 但 UDP/443 這個防火牆缺口與偵錯難度是實打實的成本。
> 沒有明確需求就先不要開；要開請一併讀 [[060-02-05-06-guide-cache-turbo與壓縮模組]] 與
> [[060-02-05-02-guide-MyGuard-Angie伺服器入門]]（MyGuard 的套件已內建 QUIC）。

---

## 安裝或基礎操作

### 檢測工具三件組 ★★★★

| 工具 | 定位 | 安裝 |
| --- | --- | --- |
| `openssl s_client` | ★★★★★ 最基本、一定有、拿來看**真相** | 系統內建 |
| `testssl.sh` | ★★★★★ 一次跑完協定、套件、憑證、漏洞、標頭的完整報告 | git clone 或套件 |
| `sslscan` | ★★★ 快速列出支援的協定與套件，輸出精簡 | `apt install sslscan` |
| `nmap` 的 ssl-enum-ciphers | ★★★ 附帶評分，適合掃一整段網段 | `apt install nmap` |

```bash
# 安裝 sslscan 與 nmap
sudo apt update
sudo apt install -y sslscan nmap

# 安裝 testssl.sh（建議用 git clone 取最新版；發行版套件常常落後）
sudo apt install -y git bsdmainutils
cd /opt
sudo git clone --depth 1 https://github.com/testssl/testssl.sh.git
sudo ln -s /opt/testssl.sh/testssl.sh /usr/local/bin/testssl.sh
testssl.sh --version
```

預期輸出（版本號會不同）：

```text
    testssl.sh       3.2rc3 from https://testssl.sh/dev/
    ...
```

> [!tip] ★★★ 從哪台機器跑檢測
> **不要只在伺服器本機跑。** 本機跑會繞過防火牆、負載平衡器、CDN、WAF ——
> 而使用者遇到的問題往往就出在那幾層。至少要從**外網的另一台機器**跑一次。

### 看清楚現況：`openssl s_client` ★★★★★

這是排錯時的第一個動作，把它練成反射。

```bash
openssl s_client -connect www.example.gov.tw:443 -servername www.example.gov.tw < /dev/null
```

★★★★★ `-servername` **一定要加**（SNI）。`< /dev/null` 是讓它送完就結束，不然會卡住等你輸入。

輸出中要看的四個地方：

```text
Certificate chain
 0 s:CN = www.example.gov.tw          ← leaf，s = subject
   i:C = US, O = Let's Encrypt, CN = R11   ← i = issuer，簽發者
 1 s:C = US, O = Let's Encrypt, CN = R11   ← 中繼憑證，有它才叫鏈完整
   i:C = US, O = Internet Security Research Group, CN = ISRG Root X1
...
SSL handshake has read 4523 bytes and written 396 bytes
---
New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384    ← ① 談成的版本與套件
Server public key is 2048 bit
...
Verify return code: 0 (ok)                         ← ② 驗證結果，0 才是好的
```

| 看什麼 | 好的樣子 | 壞的樣子代表什麼 |
| --- | --- | --- |
| `Certificate chain` 的層數 | 至少 `0` 和 `1` 兩層 | ★★★★ **只有 `0`** → 憑證鏈不完整，中繼沒送 |
| `New, TLSvX.X, Cipher is ...` | `TLSv1.3` 或 `TLSv1.2` | 出現 `TLSv1` / `TLSv1.1` → 版本沒關乾淨 |
| `Verify return code` | `0 (ok)` | ★★★★ `20 (unable to get local issuer certificate)` → 鏈斷了或根不受信任<br>`21 (unable to verify the first certificate)` → 同上<br>`10 (certificate has expired)` → 憑證過期 |
| `Server certificate` 的 `subject` | 含你要連的名字 | 不含 → SAN 沒涵蓋，見 [[090-01-04-guide-PKI-CN與SAN設定與瀏覽器相容性]] |

**只列憑證鏈的主體與簽發者**（比讀整包 PEM 好懂太多）★★★★：

```bash
openssl s_client -connect www.example.gov.tw:443 -servername www.example.gov.tw \
  -showcerts < /dev/null 2>/dev/null \
| openssl crl2pkcs7 -nocrl -certfile /dev/stdin \
| openssl pkcs7 -print_certs -noout
```

預期輸出：

```text
subject=CN = www.example.gov.tw
issuer=C = US, O = Let's Encrypt, CN = R11

subject=C = US, O = Let's Encrypt, CN = R11
issuer=C = US, O = Internet Security Research Group, CN = ISRG Root X1
```

★★★★ 判讀規則很簡單：**上一段的 `issuer` 必須等於下一段的 `subject`**，一路接下去。
接不上或只有一段，就是鏈有問題。

**測特定協定版本能不能連** ★★★★：

```bash
# 測 TLS 1.2 —— 應該要成功
openssl s_client -connect www.example.gov.tw:443 -servername www.example.gov.tw \
  -tls1_2 < /dev/null 2>&1 | grep -E "^New|Verify return"

# 測 TLS 1.0 —— 停用後應該要失敗
openssl s_client -connect www.example.gov.tw:443 -servername www.example.gov.tw \
  -tls1 < /dev/null 2>&1 | tail -5
```

TLS 1.0 被正確擋掉時的預期輸出：

```text
...:SSL alert number 70
```
或
```text
error:0A000102:SSL routines::unsupported protocol
```

> [!warning] ★★★★ OpenSSL 3.0 本身可能就不讓你測舊協定
> Ubuntu 22.04+ 的 OpenSSL 3.0 預設 `SECLEVEL=2`，`-tls1` 可能直接被**客戶端這邊**拒絕，
> 出現 `no protocols available`。這時你測到的是**自己的 OpenSSL**，不是伺服器。
> 要真的測伺服器，加上降級參數：
> ```bash
> openssl s_client -connect host:443 -servername host -tls1 \
>   -cipher 'DEFAULT@SECLEVEL=0' < /dev/null
> ```
> 或改用 `testssl.sh`／`nmap`，它們有自己的實作不受系統政策限制。

### 基礎 HTTPS 設定（Mozilla intermediate 骨架）★★★★

以下是**結構**，`ssl_ciphers` 那一行的實際內容請到
<https://ssl-config.mozilla.org/> 產生後貼上，**不要抄本文的示意**。

```nginx
# /etc/nginx/sites-available/example.conf
# TLS 設定來源：Mozilla SSL Configuration Generator, Intermediate
# 產生日期：2026-09-03（★★★ 每年重新產生一次並比對）

server {
    listen 80;
    listen [::]:80;
    server_name www.example.gov.tw example.gov.tw;

    # ACME 續期用的路徑要放行（不要一併導向）
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/acme;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;                       # Nginx >= 1.25.1；舊版請寫在 listen 後面
    server_name www.example.gov.tw;

    # ── 憑證 ───────────────────────────────────────────────
    ssl_certificate     /etc/letsencrypt/live/example/fullchain.pem;   # ★★★★★ 必須是 fullchain
    ssl_certificate_key /etc/letsencrypt/live/example/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/example/chain.pem;   # 給 stapling 驗證用

    # ── 協定版本 ───────────────────────────────────────────
    ssl_protocols TLSv1.2 TLSv1.3;                # ★★★★★ 這一行是重點

    # ── 加密套件（★ 請用產生器產生，勿抄舊文章）──────────────
    ssl_ciphers <貼上 Mozilla 產生器給的字串>;
    ssl_prefer_server_ciphers off;                # intermediate 等級建議 off

    # ── Session ────────────────────────────────────────────
    ssl_session_cache shared:MozSSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # ── OCSP stapling ─────────────────────────────────────
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 168.95.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;

    # ── HSTS（★★★★★ 先用短 max-age，確認無誤再拉長）────────
    add_header Strict-Transport-Security "max-age=300" always;

    root /var/www/example/public;
    index index.html index.php;

    access_log /var/log/nginx/example.access.log;
    error_log  /var/log/nginx/example.error.log warn;
}
```

套用與驗證：

```bash
sudo nginx -t
```

預期輸出：

```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

```bash
sudo systemctl reload nginx
```

> [!tip] ★★★★ 把 TLS 設定抽成共用檔
> 站台多的時候，把上面「協定版本／加密套件／session／stapling」四段抽出來放
> `/etc/nginx/snippets/tls-intermediate.conf`，各站台 `include snippets/tls-intermediate.conf;`。
> 這樣**明年更新設定只要改一個檔**，而不是逐站改二十個檔還漏掉三個。
> 憑證路徑因站而異，留在各站的 `server` 區塊裡。

> [!info]- Apache 對照
> 設定放在 `/etc/apache2/sites-available/example-le-ssl.conf`（Ubuntu）或
> `/etc/httpd/conf.d/ssl.conf`（RHEL）。同樣請用 Mozilla 產生器產生 `SSLCipherSuite`。
> ```apache
> <VirtualHost *:443>
>     ServerName www.example.gov.tw
>     Protocols h2 http/1.1                    # HTTP/2，需 mod_http2
>
>     SSLEngine on
>     SSLCertificateFile      /etc/letsencrypt/live/example/fullchain.pem
>     SSLCertificateKeyFile   /etc/letsencrypt/live/example/privkey.pem
>     SSLCACertificateFile    /etc/letsencrypt/live/example/chain.pem
>
>     # 協定版本 ★★★★★
>     SSLProtocol             -all +TLSv1.2 +TLSv1.3
>     SSLCipherSuite          <貼上 Mozilla 產生器給的字串>
>     SSLHonorCipherOrder     off
>
>     # OCSP stapling（SSLStaplingCache 必須放在 VirtualHost 之外的全域設定）
>     SSLUseStapling on
>
>     # HSTS，需要 mod_headers
>     Header always set Strict-Transport-Security "max-age=300"
>
>     DocumentRoot /var/www/example/public
> </VirtualHost>
> ```
> 全域（例如 `/etc/apache2/mods-available/ssl.conf`）加：
> ```apache
> SSLStaplingCache "shmcb:logs/ssl_stapling(32768)"
> SSLSessionCache  "shmcb:logs/ssl_scache(512000)"
> SSLSessionCacheTimeout 300
> ```
> 啟用模組與檢查：
> ```bash
> sudo a2enmod ssl http2 headers
> sudo apachectl configtest      # 預期：Syntax OK
> sudo systemctl reload apache2
> ```
> ★★★ Apache 的 `SSLProtocol -all +TLSv1.2 +TLSv1.3` 寫法比 Nginx 的列舉法容易漏，
> 一定要用 `testssl.sh` 回頭驗證，不要相信設定檔看起來對。

---

## 進階應用

### 量測 TLS 版本使用分布（停用舊協定的依據）★★★★★

**步驟 1：加上帶 TLS 資訊的日誌格式。**

```nginx
# /etc/nginx/conf.d/log-tls.conf（http 區塊層級）
log_format tlsinfo '$time_iso8601|$remote_addr|$ssl_protocol|$ssl_cipher|'
                   '$ssl_session_reused|$status|"$http_user_agent"|"$request"';
```

在要觀察的 `server` 區塊裡加一行（可以與原本的 access_log 並存）：

```nginx
    access_log /var/log/nginx/example.tls.log tlsinfo;
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

**步驟 2：跑一到四週後統計。** 觀察期至少要涵蓋一個完整的業務週期
（★★★ 含月底結算、季報這種只有特定時間才有人用的系統）。

```bash
# 各協定版本的請求數
awk -F'|' '{print $3}' /var/log/nginx/example.tls.log | sort | uniq -c | sort -rn
```

預期輸出：

```text
 184203 TLSv1.3
  41877 TLSv1.2
      6 TLSv1
```

```bash
# 有 TLSv1 / TLSv1.1 的來源 IP 與 User-Agent —— 這是要去追的名單
awk -F'|' '$3=="TLSv1" || $3=="TLSv1.1" {print $2, $7}' \
  /var/log/nginx/example.tls.log | sort | uniq -c | sort -rn | head -20
```

預期輸出（典型的機關現場）：

```text
      4 10.20.30.41 "Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 5.1)"
      2 10.20.30.55 "Java/1.6.0_45"
```

★★★★ 看到 `Java/1.6` 就知道是某個舊介接程式；看到 `MSIE 8.0` 就是某台沒汰換的 XP。
這兩個都是**內部 IP**，可以直接查是哪個單位、哪台機器，處理完再停用。

```bash
# 加權重的統計：各版本佔比
awk -F'|' '{c[$3]++; t++} END {for (k in c) printf "%-10s %8d  %6.3f%%\n", k, c[k], c[k]*100/t}' \
  /var/log/nginx/example.tls.log | sort -k2 -rn
```

**步驟 3：也要檢查連交握都失敗的。**

```bash
grep -icE "no protocols available|unsupported protocol|no shared cipher" \
  /var/log/nginx/example.error.log
```

回 `0` 才代表沒有客戶端被擋在門外。有數字就要去 `error.log` 裡看來源 IP。

> [!info]- Apache 對照
> mod_ssl 提供 `%{SSL_PROTOCOL}x` 與 `%{SSL_CIPHER}x`：
> ```apache
> LogFormat "%{%Y-%m-%dT%H:%M:%S}t|%a|%{SSL_PROTOCOL}x|%{SSL_CIPHER}x|%>s|\"%{User-Agent}i\"|\"%r\"" tlsinfo
> CustomLog ${APACHE_LOG_DIR}/example.tls.log tlsinfo
> ```
> 統計指令與 Nginx 相同（欄位位置注意調整 `awk -F'|'` 的欄號）。

**步驟 4：分階段停用，並留退路。**

| 階段 | 動作 | 觀察 |
| --- | --- | --- |
| 1 | 加日誌、觀察 2～4 週 | 得到使用分布 |
| 2 | 公告（含影響的單位、日期、替代方案） | ★★★★ 機關內部一定要走這步，出事才有依據 |
| 3 | 先在**測試站台**停用 | 讓有疑慮的單位去測 |
| 4 | 正式站台停用，`ssl_protocols TLSv1.2 TLSv1.3;` | ★★★★ 停用後**盯 `error.log` 至少 48 小時** |
| 5 | 一週無異常，移除觀察用的日誌格式 | 收尾 |

★★★★ 退路：把舊設定備份成 `example.conf.bak-20260903`，回滾就是
`sudo cp example.conf.bak-20260903 example.conf && nginx -t && systemctl reload nginx`，
30 秒可以復原。**不要靠記憶回滾。**

### 用 `testssl.sh` 做完整檢測 ★★★★★

```bash
# 全套檢測（會跑幾分鐘）
testssl.sh https://www.example.gov.tw
```

常用選項（跑 `testssl.sh --help` 看完整清單）：

| 選項 | 作用 | 什麼時候用 |
| --- | --- | --- |
| `-p` | 只測協定版本 | ★★★★ 停用舊協定後快速驗證 |
| `-S` | 只看伺服器預設（憑證、鏈、標頭） | ★★★★ 檢查憑證鏈完整性 |
| `-P` | 看伺服器的套件偏好順序 | 調 `ssl_prefer_server_ciphers` 時 |
| `-U` | 跑所有已知漏洞測試 | ★★★★ 稽核前跑一次 |
| `-h` | 檢查 HTTP 安全標頭 | 和 [[090-03-02-guide-應用安全-應用層安全]] 一起看 |
| `--fast` | 加快（每個協定只測一個套件） | 大量站台盤點時 |
| `--jsonfile <檔>` | 輸出 JSON | ★★★ 要進報表或做前後比對時 |
| `--htmlfile <檔>` | 輸出 HTML | 交給主管或稽核看 |

```bash
# 快速確認協定版本設定對不對
testssl.sh -p https://www.example.gov.tw
```

預期輸出（設定正確時）：

```text
 Testing protocols via sockets except NPN+ALPN

 SSLv2      not offered (OK)
 SSLv3      not offered (OK)
 TLS 1      not offered
 TLS 1.1    not offered
 TLS 1.2    offered (OK)
 TLS 1.3    offered (OK): final
 NPN/SPDY   not offered
 ALPN/HTTP2 h2, http/1.1 (offered)
```

```bash
# 憑證鏈與伺服器預設
testssl.sh -S https://www.example.gov.tw 2>&1 | grep -iE "chain|trust|expiration"
```

憑證鏈不完整時，`testssl.sh` 會明確講出來：

```text
 Chain of trust        NOT ok (chain incomplete)
```

★★★★ 這一行就是「桌機正常手機失敗」的根因，看到它就去修 `ssl_certificate` 指向的檔案。

```bash
# 產出可存檔的報告（稽核用）
testssl.sh --jsonfile /var/tmp/tls-$(date +%F).json \
           --htmlfile /var/tmp/tls-$(date +%F).html \
           https://www.example.gov.tw
```

> [!tip] ★★★ 檢測結果要留檔比對
> 每次改完 TLS 設定，前後各跑一次 `--jsonfile`，把兩個檔案 `diff` 一下。
> 這是最可靠的「我到底改了什麼」證據，也是資安稽核時最好用的佐證。

### `sslscan` 與 `nmap` 的快速用法 ★★★

```bash
sslscan --no-colour www.example.gov.tw:443 | head -40
```

輸出結構（節錄）：

```text
SSL/TLS Protocols:
SSLv2     disabled
SSLv3     disabled
TLSv1.0   disabled
TLSv1.1   disabled
TLSv1.2   enabled
TLSv1.3   enabled

TLS Fallback SCSV:
Server supports TLS Fallback SCSV

Supported Server Cipher(s):
Preferred TLSv1.3  128 bits  TLS_AES_128_GCM_SHA256   Curve 25519 DHE 253
...
```

```bash
# nmap 版本，會附一個 least strength 評分，適合掃網段盤點
nmap --script ssl-enum-ciphers -p 443 www.example.gov.tw
```

輸出結尾會有：

```text
|_  least strength: A
```

★★★ `nmap` 的評分只看套件強度，**不看憑證鏈與 HSTS**，不要拿它當最終驗收。

### OCSP stapling 的驗證與排錯 ★★★

```bash
openssl s_client -connect www.example.gov.tw:443 -servername www.example.gov.tw \
  -status < /dev/null 2>/dev/null | grep -A 3 "OCSP response"
```

成功的樣子：

```text
OCSP response:
======================================
OCSP Response Data:
    OCSP Response Status: successful (0x0)
```

沒生效的樣子：

```text
OCSP response: no response sent
```

| 沒生效的原因 | 怎麼確認 | 解法 |
| --- | --- | --- |
| ★★★★ 沒設 `resolver` | `nginx -T \| grep resolver` 沒東西 | 加上 `resolver`，並確認 Nginx 主機能對外做 DNS 查詢 |
| ★★★★ 伺服器出不去（機關常見） | `curl -sI http://<OCSP網址>` 逾時 | OCSP 走的是 **HTTP（80 埠）**，防火牆要放行對外 80 |
| ★★★ `ssl_trusted_certificate` 少了中繼 | `ssl_stapling_verify on` 時驗證失敗 | 指向 `chain.pem`，或含中繼＋根的檔 |
| ★★ 剛重載還沒抓到 | 第一次請求 | 等幾秒再測，不要第一發就下結論 |
| ★★ CA 的 OCSP responder 當機 | `error.log` 有 `ssl_stapling` 相關警告 | ★★ 這是 CA 端問題，stapling 會自動退回不釘 |

`error.log` 裡的典型訊息：

```text
[warn] 1234#1234: ignoring stapling response, no OCSP responder URL in the certificate
```
★★★ 這代表憑證本身沒有 OCSP 網址（部分新式 CA 已不再提供 OCSP），此時 stapling 開了也沒用，
不是設定錯誤。

### 憑證鏈修復 ★★★★

發現 `Chain of trust NOT ok` 之後：

```bash
# 1. 確認 Nginx 現在到底指到哪個檔
sudo nginx -T | grep -E "ssl_certificate |ssl_certificate_key"
```

```text
    ssl_certificate     /etc/letsencrypt/live/example/cert.pem;      ← ★★★★ 問題在這
    ssl_certificate_key /etc/letsencrypt/live/example/privkey.pem;
```

```bash
# 2. 看那個檔裡有幾張憑證
grep -c "BEGIN CERTIFICATE" /etc/letsencrypt/live/example/cert.pem
```

回 `1` 就是只有 leaf，鏈不完整。

```bash
# 3. 改指 fullchain.pem
sudo sed -i 's|live/example/cert.pem|live/example/fullchain.pem|' \
  /etc/nginx/sites-available/example.conf
sudo nginx -t && sudo systemctl reload nginx

# 4. 驗證
grep -c "BEGIN CERTIFICATE" /etc/letsencrypt/live/example/fullchain.pem   # 應該 >= 2
openssl s_client -connect www.example.gov.tw:443 -servername www.example.gov.tw \
  -showcerts < /dev/null 2>/dev/null | grep -c "BEGIN CERTIFICATE"        # 應該 >= 2
```

如果憑證不是 Certbot 發的（例如 GCA／TWCA 提供的檔案），CA 會另外給中繼憑證檔，
自己組出 fullchain ★★★★：

```bash
# 順序很重要：leaf 在前、中繼在後（由下往上）
cat server.crt intermediate.crt > fullchain.crt
openssl verify -CAfile root.crt -untrusted intermediate.crt server.crt
```

預期輸出：

```text
server.crt: OK
```

> [!warning] ★★★★ 順序反了不會報錯，但客戶端可能拒收
> `cat intermediate.crt server.crt` 這樣寫順序是錯的。Nginx 通常還是能啟動，
> 但部分嚴格的客戶端會驗證失敗。永遠是 **leaf → 中繼 → （不含根）**。
> 詳細說明見 [[090-01-07-guide-PKI-自建中繼CA與憑證鏈]]。

### HSTS 的分階段導入 ★★★★★

```nginx
# 第 1 週：5 分鐘，出事影響範圍極小
add_header Strict-Transport-Security "max-age=300" always;

# 第 2～3 週：1 天
add_header Strict-Transport-Security "max-age=86400" always;

# 第 4～6 週：30 天
add_header Strict-Transport-Security "max-age=2592000" always;

# 穩定後：1 年（SSL Labs A+ 需要至少 180 天）
add_header Strict-Transport-Security "max-age=31536000" always;

# 盤點完所有子網域、確認全部有 HTTPS 之後才加（★★★★★）
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

★★★★ `always` 參數不可省。沒有 `always` 時，Nginx **只在 2xx／3xx 回應加標頭**，
遇到 4xx／5xx 錯誤頁就不加 —— 這正是使用者最需要保護的時候。

驗證：

```bash
curl -sI https://www.example.gov.tw | grep -i strict-transport
```

預期輸出：

```text
strict-transport-security: max-age=31536000
```

> [!danger] ★★★★★ Nginx `add_header` 的繼承陷阱
> Nginx 的 `add_header` **不會累加**：只要子區塊（`location`）裡出現了**任何一個** `add_header`，
> **父區塊的所有 `add_header` 全部失效**。
>
> ```nginx
> server {
>     add_header Strict-Transport-Security "max-age=31536000" always;
>
>     location /api/ {
>         add_header X-Custom "v1" always;   # ★★★★★ 這一行讓 /api/ 沒有 HSTS 了
>     }
> }
> ```
> 修法：在子區塊裡把父層的標頭**重寫一遍**，或改用 `ngx_headers_more` 的 `more_set_headers`
> （行為是累加的）。★★★★ 改完一定用 `curl -sI https://host/api/` 逐路徑驗證，
> **不要只測首頁**。這個坑在 [[090-03-02-guide-應用安全-應用層安全]] 會再詳細展開。

要把 HSTS 記錄清掉（本機測試用）：

| 瀏覽器 | 位置 |
| --- | --- |
| Chrome／Edge | 網址列輸入 `chrome://net-internals/#hsts`（Edge 為 `edge://net-internals/#hsts`），在 **Delete domain security policies** 輸入網域後刪除 |
| Firefox | 「忘記此網站」（歷史記錄中右鍵）或清除網站資料 |

★★★★★ 這只能清**你自己這一台**。全機關幾百台電腦你清不完 —— 這就是為什麼要分階段。

### 從 HTTP 導向 HTTPS 而不製造迴圈 ★★★★

單機直連時很單純：

```nginx
server {
    listen 80;
    server_name www.example.gov.tw;
    return 301 https://$host$request_uri;
}
```

**但站台在負載平衡器／反向代理後面時**，這樣寫會造成無限迴圈 ★★★★★：
LB 把 HTTPS 卸載後用 HTTP 轉給後端 → 後端看到是 HTTP 就 301 到 HTTPS →
瀏覽器再連 LB → LB 又用 HTTP 轉給後端 → 無限循環，瀏覽器顯示
`ERR_TOO_MANY_REDIRECTS`。

正確做法：看 `X-Forwarded-Proto` 而不是看自己收到的是不是 HTTPS。

```nginx
server {
    listen 80;
    server_name www.example.gov.tw;

    # 只有當前端也是 HTTP 時才導向
    if ($http_x_forwarded_proto = "http") {
        return 301 https://$host$request_uri;
    }
    # X-Forwarded-Proto = https 時，正常提供內容
    root /var/www/example/public;
}
```

★★★★ 前提是**你信任這個標頭**。必須確保：
1. 後端只接受來自 LB 的連線（防火牆或 `allow`／`deny`）
2. LB 一定會**覆寫**（不是附加）`X-Forwarded-Proto`

搭配 `real_ip` 模組把真實來源 IP 取回來（限流與日誌都需要）：

```nginx
set_real_ip_from 10.0.0.0/24;      # ★★★★ 只列你的 LB／代理，不要寫 0.0.0.0/0
real_ip_header X-Forwarded-For;
real_ip_recursive on;
```

### 混合內容（mixed content）★★★★

頁面本身是 HTTPS，但裡面用 `http://` 載入圖片、JS、CSS。瀏覽器行為：

| 資源類型 | 現代瀏覽器行為 |
| --- | --- |
| 腳本、樣式、iframe（active content） | ★★★★ **直接封鎖**，功能壞掉 |
| 圖片、影音（passive content） | ★★★ 多數瀏覽器會自動升級成 HTTPS，失敗則封鎖 |

找出來的方法：

```bash
# 抓首頁 HTML 裡的 http:// 引用
curl -s https://www.example.gov.tw/ | grep -oE '(src|href)="http://[^"]+' | sort -u
```

治本是請開發方改成 `https://` 或協定相對路徑。維運端的緩衝手段 ★★★：

```nginx
add_header Content-Security-Policy "upgrade-insecure-requests" always;
```

這會讓瀏覽器把頁內的 `http://` 請求自動改成 `https://`。
★★★★ 前提是**那些資源真的有 HTTPS 版本**，否則只是換一種壞法。
CSP 的完整用法見 [[090-03-02-guide-應用安全-應用層安全]]。

### 用得到的話：mTLS（雙向認證）★★

某些機關介接（例如與上級機關的資料交換）會要求客戶端也出示憑證：

```nginx
    ssl_client_certificate /etc/ssl/example/client-ca.crt;   # 簽發客戶端憑證的 CA
    ssl_verify_client on;                                     # on / optional / off
    ssl_verify_depth 2;
```

驗證結果可在日誌或後端讀到：`$ssl_client_verify`（`SUCCESS`／`FAILED:...`／`NONE`）、
`$ssl_client_s_dn`（客戶端憑證的主體）。

★★★ 客戶端憑證的簽發與管理屬於 PKI 範疇，見 [[090-01-08-guide-PKI-用自建CA簽發伺服器憑證]]
與 [[090-01-09-guide-PKI-根憑證派送與信任]]。這裡只講伺服器端怎麼開。

---

## 完整實戰範例

**情境**：機關有一台 Ubuntu 22.04，跑著 `www.example.gov.tw`，
目前只有 HTTP。資安稽核要求「HTTPS 且 SSL Labs 達 A 級以上」。
我們要從零做到 A 級，全程可跑、每一步都有驗證。

### 步驟 0：確認起點

```bash
nginx -v
```
```text
nginx version: nginx/1.24.0 (Ubuntu)
```

```bash
openssl version
```
```text
OpenSSL 3.0.2 15 Mar 2022 (Library: OpenSSL 3.0.2 15 Mar 2022)
```

```bash
curl -sI http://www.example.gov.tw/ | head -3
```
```text
HTTP/1.1 200 OK
Server: nginx/1.24.0 (Ubuntu)
Content-Type: text/html
```

```bash
# 確認 443 目前沒開
sudo ss -tlnp | grep -E ':(80|443)'
```
```text
LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=812,fd=6),...)
```

★★★ Nginx 是 1.24，**不是** 1.25.1 以上，所以 HTTP/2 要用舊寫法 `listen 443 ssl http2;`。
這一點決定了後面的設定寫法 —— 先確認版本，不要憑印象。

### 步驟 1：備份現有設定（★★★★ 先做退路）

```bash
sudo cp -a /etc/nginx /etc/nginx.bak-$(date +%F)
ls -d /etc/nginx.bak-*
```
```text
/etc/nginx.bak-2026-09-03
```

### 步驟 2：取得憑證

假設用 Let's Encrypt（機關憑證請改看 [[090-01-14-guide-PKI-機關憑證來源GCA與TWCA]]）：

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot certonly --nginx -d www.example.gov.tw --agree-tos -m ops@example.gov.tw
```

```bash
sudo ls -l /etc/letsencrypt/live/www.example.gov.tw/
```
```text
lrwxrwxrwx 1 root root  ... cert.pem -> ../../archive/www.example.gov.tw/cert1.pem
lrwxrwxrwx 1 root root  ... chain.pem -> ../../archive/www.example.gov.tw/chain1.pem
lrwxrwxrwx 1 root root  ... fullchain.pem -> ../../archive/www.example.gov.tw/fullchain1.pem
lrwxrwxrwx 1 root root  ... privkey.pem -> ../../archive/www.example.gov.tw/privkey1.pem
```

★★★★ 記住：等一下要指的是 **`fullchain.pem`**。

### 步驟 3：到 Mozilla 產生器拿設定

到 <https://ssl-config.mozilla.org/>：

- Server Software：**nginx**
- Version：**1.24.0**
- OpenSSL Version：**3.0.2**
- Configuration：**Intermediate**

把它給的 `ssl_ciphers`、`ssl_protocols`、`ssl_prefer_server_ciphers`、
session 相關那幾行複製下來備用。

> [!warning] ★★★★★ 這一步不能跳過用抄的
> 本文刻意不列出具體的 cipher 字串，因為它**會過期**。
> 你在 2026 年抄本文的字串，到 2029 年就是一份過時設定。永遠去產生器拿當下的版本。

### 步驟 4：寫設定（第一版，先不開 HSTS）

```bash
sudo tee /etc/nginx/snippets/tls-intermediate.conf > /dev/null <<'EOF'
# Mozilla SSL Configuration Generator - Intermediate
# nginx 1.24.0 / OpenSSL 3.0.2
# 產生日期：2026-09-03　★★★ 每年重新產生並比對
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers <貼上產生器給的字串>;
ssl_prefer_server_ciphers off;

ssl_session_timeout 1d;
ssl_session_cache shared:MozSSL:10m;
ssl_session_tickets off;

ssl_stapling on;
ssl_stapling_verify on;
resolver 168.95.1.1 8.8.8.8 valid=300s;
resolver_timeout 5s;
EOF
```

```bash
sudo tee /etc/nginx/sites-available/example.conf > /dev/null <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name www.example.gov.tw;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/acme;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;              # nginx 1.24 用舊寫法
    listen [::]:443 ssl http2;
    server_name www.example.gov.tw;

    ssl_certificate         /etc/letsencrypt/live/www.example.gov.tw/fullchain.pem;
    ssl_certificate_key     /etc/letsencrypt/live/www.example.gov.tw/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/www.example.gov.tw/chain.pem;

    include snippets/tls-intermediate.conf;

    root  /var/www/example/public;
    index index.html;

    access_log /var/log/nginx/example.access.log;
    error_log  /var/log/nginx/example.error.log warn;
}
EOF
```

```bash
sudo mkdir -p /var/www/acme
sudo ln -sf /etc/nginx/sites-available/example.conf /etc/nginx/sites-enabled/example.conf
sudo nginx -t
```
```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```
```bash
sudo systemctl reload nginx
```

### 步驟 5：第一次檢測（找出還有什麼問題）

```bash
testssl.sh --jsonfile /var/tmp/tls-round1.json https://www.example.gov.tw
```

假設得到（節錄）：

```text
 Testing protocols

 SSLv2      not offered (OK)
 SSLv3      not offered (OK)
 TLS 1      not offered
 TLS 1.1    not offered
 TLS 1.2    offered (OK)
 TLS 1.3    offered (OK): final

 Testing server defaults (Server Hello)

 TLS extensions   ... "status request/#5" ...
 OCSP stapling    not offered                          ← ① 問題
 Chain of trust   Ok

 Testing HTTP header response @ "/"

 HSTS             not offered                          ← ② 問題
 Reverse Proxy banner  nginx/1.24.0 (Ubuntu)           ← ③ 洩漏版本
```

三個要修的項目找到了。

### 步驟 6：逐項修正

**① OCSP stapling 沒生效。** 先確認是不是 DNS 出不去：

```bash
dig +short r11.o.lencr.org @168.95.1.1
```

沒有回應就是 DNS 或防火牆問題。確認 Nginx 主機能對外做 DNS 與 HTTP(80)：

```bash
curl -sI -m 5 http://r11.o.lencr.org/ | head -1
```

★★★★ 機關防火牆常常只放行對外 443、擋掉對外 80，而 **OCSP 走的就是 80**。
請網管開通對外 80（目的地限 CA 的 OCSP 主機）。開通後：

```bash
sudo systemctl reload nginx
sleep 5
openssl s_client -connect www.example.gov.tw:443 -servername www.example.gov.tw \
  -status < /dev/null 2>/dev/null | grep "OCSP Response Status"
```
```text
    OCSP Response Status: successful (0x0)
```

**② 加上 HSTS（先用短的）。**

```bash
sudo sed -i '/include snippets\/tls-intermediate.conf;/a\
\    add_header Strict-Transport-Security "max-age=300" always;' \
  /etc/nginx/sites-available/example.conf
sudo nginx -t && sudo systemctl reload nginx
curl -sI https://www.example.gov.tw/ | grep -i strict
```
```text
strict-transport-security: max-age=300
```

**③ 關掉版本洩漏。**

```bash
grep -n "server_tokens" /etc/nginx/nginx.conf
```
沒有就加進 `http` 區塊：
```bash
sudo sed -i '/^http {/a\    server_tokens off;' /etc/nginx/nginx.conf
sudo nginx -t && sudo systemctl reload nginx
curl -sI https://www.example.gov.tw/ | grep -i '^server'
```
```text
server: nginx
```
★★★ `server_tokens off` 只拿掉版本號，`nginx` 這個字還在。要完全移除得用
`ngx_headers_more` 模組（`more_clear_headers Server;`），
詳見 [[090-03-02-guide-應用安全-應用層安全]]。

### 步驟 7：第二次檢測與比對

```bash
testssl.sh --jsonfile /var/tmp/tls-round2.json https://www.example.gov.tw
```

```text
 OCSP stapling    offered
 Chain of trust   Ok
 HSTS             300 seconds = 0 days (less than 15552000 seconds is not recommended)
 Reverse Proxy banner  nginx
```

三項都改善了。HSTS 的提示是預期中的 —— 我們刻意先用短的。

```bash
# 前後比對（要有 jq）
sudo apt install -y jq
diff <(jq -S '.scanResult' /var/tmp/tls-round1.json) \
     <(jq -S '.scanResult' /var/tmp/tls-round2.json) | head -40
```

### 步驟 8：觀察期與逐步拉長 HSTS

| 時間點 | `max-age` | 動作 |
| --- | --- | --- |
| D+0 | 300 | 上線，盯 `error.log` |
| D+7 | 86400 | 無災情才調整 |
| D+21 | 2592000 | 同上 |
| D+45 | 31536000 | 到這裡 SSL Labs 才會給 A+ |

每次調整後都要驗證：

```bash
curl -sI https://www.example.gov.tw/ | grep -i strict
```

### 步驟 9：驗收清單

```bash
#!/usr/bin/env bash
# /usr/local/sbin/tls-verify.sh —— TLS 上線驗收
set -u
HOST="${1:?用法: tls-verify.sh <hostname>}"
PORT="${2:-443}"
S="openssl s_client -connect ${HOST}:${PORT} -servername ${HOST}"
fail=0
ok()   { printf '  [ OK ] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=$((fail+1)); }

echo "== TLS 驗收：${HOST}:${PORT} =="

# 1. 憑證鏈至少兩張
n=$($S -showcerts </dev/null 2>/dev/null | grep -c "BEGIN CERTIFICATE")
[ "$n" -ge 2 ] && ok "憑證鏈完整（${n} 張）" || bad "憑證鏈只有 ${n} 張，中繼可能沒送"

# 2. 驗證結果為 0
v=$($S </dev/null 2>/dev/null | grep "Verify return code")
echo "$v" | grep -q "return code: 0" && ok "$v" || bad "$v"

# 3. TLS 1.2 可用
$S -tls1_2 </dev/null >/dev/null 2>&1 && ok "TLS 1.2 可用" || bad "TLS 1.2 不可用"

# 4. TLS 1.3 可用
$S -tls1_3 </dev/null >/dev/null 2>&1 && ok "TLS 1.3 可用" || bad "TLS 1.3 不可用"

# 5. TLS 1.0 應被拒絕
if $S -tls1 -cipher 'DEFAULT@SECLEVEL=0' </dev/null >/dev/null 2>&1; then
  bad "TLS 1.0 仍然可用（應停用）"
else
  ok "TLS 1.0 已停用"
fi

# 6. OCSP stapling
$S -status </dev/null 2>/dev/null | grep -q "OCSP Response Status: successful" \
  && ok "OCSP stapling 生效" || bad "OCSP stapling 未生效"

# 7. HSTS
h=$(curl -sI "https://${HOST}/" | grep -i '^strict-transport-security' | tr -d '\r')
[ -n "$h" ] && ok "${h}" || bad "沒有 HSTS 標頭"

# 8. HTTP 導向
loc=$(curl -sI "http://${HOST}/" | grep -i '^location' | tr -d '\r')
echo "$loc" | grep -qi "https://" && ok "${loc}" || bad "HTTP 未導向 HTTPS（${loc:-無 Location}）"

# 9. 憑證到期天數
end=$($S </dev/null 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -n "$end" ]; then
  days=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
  [ "$days" -gt 21 ] && ok "憑證剩 ${days} 天" || bad "憑證只剩 ${days} 天"
fi

echo "== 失敗項目：${fail} =="
exit "$fail"
```

```bash
sudo install -m 0755 /dev/stdin /usr/local/sbin/tls-verify.sh < tls-verify.sh
sudo /usr/local/sbin/tls-verify.sh www.example.gov.tw
```

預期輸出：

```text
== TLS 驗收：www.example.gov.tw:443 ==
  [ OK ] 憑證鏈完整（2 張）
  [ OK ] Verify return code: 0 (ok)
  [ OK ] TLS 1.2 可用
  [ OK ] TLS 1.3 可用
  [ OK ] TLS 1.0 已停用
  [ OK ] OCSP stapling 生效
  [ OK ] strict-transport-security: max-age=31536000
  [ OK ] location: https://www.example.gov.tw/
  [ OK ] 憑證剩 74 天
== 失敗項目：0 ==
```

★★★★ 把這個腳本排進每月的維運檢查，或接到監控系統（`exit` 非 0 就告警），
詳見 [[100-01-04-guide-日誌-健康檢查與可用性監控]]。

### 步驟 10：留檔

```bash
sudo mkdir -p /var/lib/tls-audit
sudo cp /var/tmp/tls-round2.json /var/lib/tls-audit/$(date +%F)-www.example.gov.tw.json
```

稽核要證據時，這個目錄就是答案。

---

## 常見錯誤與排錯

| # | 現象 | 原因 | 解法 |
| --- | --- | --- | --- |
| 1 | ★★★★ 桌機瀏覽器正常，手機 App／Java 程式回 `PKIX path building failed` 或 `unable to get local issuer certificate` | 憑證鏈不完整，`ssl_certificate` 指到 `cert.pem` 而不是 `fullchain.pem`。桌機瀏覽器靠 AIA 自動補中繼所以看不出來 | 改指 `fullchain.pem`，用 `openssl s_client -showcerts \| grep -c "BEGIN CERTIFICATE"` 確認 ≥ 2 |
| 2 | ★★★★ `curl` 回 `SSL certificate problem: unable to get local issuer certificate` | 同上；或用的是自建 CA 而客戶端沒安裝根憑證 | 前者修 fullchain；後者見 [[090-01-09-guide-PKI-根憑證派送與信任]] |
| 3 | ★★★★ 瀏覽器 `NET::ERR_CERT_COMMON_NAME_INVALID` / `certificate name mismatch` | 憑證的 SAN 沒有涵蓋使用者輸入的名字（常見：只簽了 `www.example.gov.tw`，使用者打 `example.gov.tw`） | 重簽含所有名字的憑證，見 [[090-01-04-guide-PKI-CN與SAN設定與瀏覽器相容性]] |
| 4 | ★★★★★ 開了 HSTS 後憑證過期，使用者完全進不去、也沒有「繼續前往」 | HSTS 讓瀏覽器拒絕接受任何憑證錯誤 | ★★★★★ 只能**趕快修好憑證**，沒有其他辦法。這就是為什麼開 HSTS 前必須先確保續期自動化＋到期告警 |
| 5 | ★★★★★ 開了 `includeSubDomains` 後，內部管理介面（事務機、UPS、舊系統）全部連不上 | 子網域被一併強制 HTTPS，但它們只有 HTTP | 移除 `includeSubDomains` 只對**新訪客**生效；已中招的機器要逐台去 `chrome://net-internals/#hsts` 刪除。★★★★★ 事前盤點才是解法 |
| 6 | ★★★★ `ERR_TOO_MANY_REDIRECTS`（重新導向迴圈） | 站台在 LB／CDN 後面，LB 卸載 TLS 後用 HTTP 轉給後端，後端又 301 到 HTTPS | 改判斷 `$http_x_forwarded_proto`；或在 LB 上就做導向。CDN 的話檢查「SSL 模式」是否設成 Flexible（★★★★ 這個設定會製造迴圈） |
| 7 | ★★★★ HTTPS 頁面上功能壞掉，Console 顯示 `Mixed Content: The page at 'https://...' was loaded over HTTPS, but requested an insecure ...` | 頁內以 `http://` 載入 JS／CSS／iframe，被瀏覽器封鎖 | 請開發方改成 `https://`；過渡期可加 `Content-Security-Policy: upgrade-insecure-requests` |
| 8 | ★★★ 網頁不再有掛鎖（顯示「不安全」），但沒有錯誤 | passive mixed content（圖片）被升級失敗或被標記 | `curl -s https://host/ \| grep -oE '(src\|href)="http://[^"]+'` 找出來修 |
| 9 | ★★★★ 某些舊系統改用 TLS 1.2 後仍連不上，錯誤是 `no shared cipher` | 舊客戶端只支援已被排除的套件（例如只有 3DES 或 CBC 系列） | ★★★★ 不要為了它放寬全站。改用 Mozilla **Old** 等級**只給那個站台**，或把該系統排入汰換 |
| 10 | ★★★ `nginx -t` 報 `unknown directive "http2"` | Nginx < 1.25.1，`http2` 還不是獨立指令 | 改回 `listen 443 ssl http2;` |
| 11 | ★★★ `nginx -t` 報 `the "ssl" parameter requires ngx_http_ssl_module` | Nginx 編譯時沒帶 SSL 模組（少見，多半是自編版本） | `nginx -V 2>&1 \| tr ' ' '\n' \| grep ssl` 確認；改用發行版或 MyGuard 的套件 |
| 12 | ★★★★ OCSP stapling 設了但 `testssl.sh` 顯示 `not offered` | 沒設 `resolver`；或 Nginx 主機**對外 80 埠被防火牆擋住**（OCSP 走 HTTP） | 加 `resolver`，並請網管放行對外 80 至 CA 的 OCSP 主機 |
| 13 | ★★★ `error.log` 出現 `ignoring stapling response, no OCSP responder URL in the certificate` | 憑證本身沒有 OCSP 網址（部分 CA 已停止提供 OCSP） | 不是錯誤，stapling 對這張憑證無效，可移除相關設定或忽略 |
| 14 | ★★★★ 某個 `location` 底下的 HSTS／安全標頭消失 | Nginx `add_header` 不繼承：子區塊有任何 `add_header` 就覆蓋掉父層全部 | 在該 `location` 重寫一次全部標頭，或用 `ngx_headers_more`。★★★★ 用 `curl -sI` **逐路徑**驗證 |
| 15 | ★★★ 錯誤頁（404／500）沒有安全標頭 | `add_header` 少了 `always` 參數 | 全部加上 `always` |
| 16 | ★★★ 本機 `openssl s_client -tls1` 回 `no protocols available`，不確定是伺服器擋的還是自己擋的 | OpenSSL 3.0 的 `SECLEVEL=2` 在客戶端就拒絕舊協定 | 加 `-cipher 'DEFAULT@SECLEVEL=0'`，或改用 `testssl.sh`／`nmap` 測 |
| 17 | ★★★ 一台機器多個 HTTPS 站台，測某個站拿到的是別站的憑證 | `openssl s_client` 忘了加 `-servername`（沒送 SNI），拿到預設站台 | 一定要加 `-servername <FQDN>` |
| 18 | ★★★ SSL Labs 給 A 但不給 A+ | HSTS 的 `max-age` 太短（需至少 180 天／15552000 秒） | 觀察期結束後拉到 `31536000` |
| 19 | ★★★ SSL Labs 分數被壓在 B | 仍支援 TLS 1.0／1.1 | 依「量測 → 公告 → 停用」流程關閉 |
| 20 | ★★★★ 憑證續期後網站還是用舊憑證 | Certbot 更新了檔案但沒有重載 Nginx | 設定 `--deploy-hook "systemctl reload nginx"`；見 [[090-01-12-guide-PKI-憑證生命週期管理]] |

---

## 安全性注意事項

> [!danger] ★★★★★ 三件不可逆或難以復原的事
> 1. **HSTS 標頭送出去就收不回來**。瀏覽器記在使用者電腦裡，你沒有遠端清除的能力。
>    分階段（300 → 86400 → 2592000 → 31536000）是唯一安全的做法。
> 2. **`preload` 送出去要等好幾個月才能移除**，而且移除生效要等瀏覽器改版。
>    這是對整個網域樹的長期承諾，送之前要有主管同意與書面記錄。
> 3. **私鑰外洩無法「撤銷後就沒事」**。沒有前向保密的連線，被錄下的舊流量會被回溯解密。
>    這就是為什麼 cipher suite 一定要 ECDHE／DHE。私鑰保護見
>    [[090-03-03-guide-應用安全-機密管理與金鑰保護]]。

> [!warning] ★★★★ 私鑰檔案權限
> ```bash
> sudo chown root:root /etc/letsencrypt/live/*/privkey.pem
> sudo chmod 600 /etc/letsencrypt/live/*/privkey.pem
> sudo chmod 700 /etc/letsencrypt/archive /etc/letsencrypt/live
> ```
> Nginx 的 master process 以 root 啟動才讀得到私鑰，worker 降權後不再持有 ——
> 所以私鑰**不需要**給 `www-data` 讀。看到 `chmod 644 privkey.pem` 一律視為缺失。

其他要點：

| 項目 | 說明 |
| --- | --- |
| ★★★★ 私鑰不進 git | `.pem`、`.key` 加入 `.gitignore`；已經進去的要**輪換金鑰**，不是刪 commit 就好 |
| ★★★★ 0-RTT（`ssl_early_data`）預設不要開 | 有重放風險。真要開，後端必須對重放的請求冪等 |
| ★★★ `ssl_session_tickets off` | 除非你有票券金鑰輪替機制，否則關掉以保全前向保密 |
| ★★★★ 不要用 `ssl_verify_client optional` 又不檢查 `$ssl_client_verify` | 等於沒驗；後端一定要判斷變數值是 `SUCCESS` |
| ★★★ TLS 壓縮一律關 | CRIME 攻擊。現代 OpenSSL 預設已關，`testssl.sh -U` 會確認 |
| ★★★★ 內部管理介面也要 HTTPS | 「反正是內網」不是理由；內網橫向移動是現在最常見的攻擊路徑 |
| ★★★ 憑證到期監控要獨立於發證流程 | 續期腳本壞掉時，監控是你最後一道防線 |
| ★★★★ 每年重新產生一次 TLS 設定 | 排進年度維運行事曆，和憑證續期分開排 |
| ★★★ 檢測要從外網跑 | 本機跑會繞過 LB／WAF／CDN，測不到使用者真正遇到的東西 |
| ★★ 把 `testssl.sh` 報告存檔 | 稽核佐證，也是變更前後的比對基準 |

> [!tip] ★★★ TLS 只是縱深防禦的一層
> HTTPS 保護的是**傳輸中**的資料，它不會擋 SQL injection、不會擋 XSS、
> 不會讓有漏洞的應用變安全。應用層的防護見 [[090-03-02-guide-應用安全-應用層安全]]，
> 外加一層 WAF 見 [[090-04-00-idx-ModSecurity]] 與
> [[090-05-04-guide-資安設備-Web應用防火牆WAF]]。

---

## 速查表

### 檢測指令

| 目的 | 指令 |
| --- | --- |
| 看憑證鏈與驗證結果 | `openssl s_client -connect H:443 -servername H < /dev/null` |
| 只列鏈上每張憑證的 subject／issuer | `openssl s_client -connect H:443 -servername H -showcerts </dev/null 2>/dev/null \| openssl crl2pkcs7 -nocrl -certfile /dev/stdin \| openssl pkcs7 -print_certs -noout` |
| 數鏈上有幾張憑證（★★★★ 應 ≥ 2） | `openssl s_client ... -showcerts </dev/null 2>/dev/null \| grep -c "BEGIN CERTIFICATE"` |
| 驗證 OCSP stapling | `openssl s_client -connect H:443 -servername H -status </dev/null \| grep "OCSP Response Status"` |
| 測特定協定版本 | `openssl s_client -connect H:443 -servername H -tls1_2`（`-tls1`／`-tls1_1`／`-tls1_3`） |
| 測舊協定但被本機 SECLEVEL 擋住時 | 加 `-cipher 'DEFAULT@SECLEVEL=0'` |
| 看憑證到期日 | `openssl s_client ... </dev/null 2>/dev/null \| openssl x509 -noout -dates` |
| 看本機憑證檔的內容 | `openssl x509 -in cert.pem -noout -text` |
| 完整檢測報告 | `testssl.sh https://H` |
| 只測協定版本 | `testssl.sh -p https://H` |
| 只測伺服器預設與憑證鏈 | `testssl.sh -S https://H` |
| 測已知漏洞 | `testssl.sh -U https://H` |
| 輸出 JSON／HTML 報告 | `testssl.sh --jsonfile a.json --htmlfile a.html https://H` |
| 快速列支援的協定與套件 | `sslscan --no-colour H:443` |
| nmap 版本（含評分） | `nmap --script ssl-enum-ciphers -p 443 H` |
| 看回應標頭 | `curl -sI https://H/` |
| 確認 HSTS | `curl -sI https://H/ \| grep -i strict-transport` |
| 確認 HTTP 導向 | `curl -sI http://H/ \| grep -i location` |
| 確認 HTTP/2 | `curl -sI --http2 https://H/ \| head -1`（顯示 `HTTP/2 200`） |
| 找 mixed content | `curl -s https://H/ \| grep -oE '(src\|href)="http://[^"]+' \| sort -u` |

### Nginx 指令

| 指令 | 作用 | 建議值 |
| --- | --- | --- |
| `ssl_certificate` | 憑證檔 | ★★★★★ 指 `fullchain.pem`（leaf + 中繼） |
| `ssl_certificate_key` | 私鑰 | `privkey.pem`，權限 600 |
| `ssl_trusted_certificate` | 驗證 OCSP 回應用 | `chain.pem` |
| `ssl_protocols` | 協定版本 | ★★★★★ `TLSv1.2 TLSv1.3` |
| `ssl_ciphers` | TLS 1.2 的套件（1.3 管不到） | ★★★★ 由 Mozilla 產生器產生 |
| `ssl_conf_command Ciphersuites` | TLS 1.3 的套件 | ★★ 通常不需要改 |
| `ssl_prefer_server_ciphers` | 用伺服器順序 | intermediate 建議 `off` |
| `ssl_session_cache` | session ID 快取 | `shared:MozSSL:10m`（10m 是**記憶體大小**） |
| `ssl_session_timeout` | session 有效時間 | `1d` |
| `ssl_session_tickets` | session ticket | ★★★★ `off`（除非能輪替票券金鑰） |
| `ssl_stapling` / `ssl_stapling_verify` | OCSP stapling | `on` / `on` |
| `resolver` | stapling 需要的 DNS | 填可用的 DNS，並加 `valid=300s` |
| `ssl_early_data` | TLS 1.3 0-RTT | ★★★★ 預設 `off`，有重放風險 |
| `ssl_client_certificate` / `ssl_verify_client` | mTLS | 需要雙向認證時 |
| `http2 on;` | HTTP/2（Nginx ≥ 1.25.1） | 舊版寫 `listen 443 ssl http2;` |
| `server_tokens off;` | 隱藏版本號 | ★★★ 放 `http` 區塊 |
| `add_header ... always` | 加回應標頭 | ★★★★ `always` 不可省；★★★★ 子區塊會覆蓋父層 |

### Nginx 日誌變數

| 變數 | 內容 |
| --- | --- |
| `$ssl_protocol` | 協商出的協定版本 |
| `$ssl_cipher` | 協商出的加密套件 |
| `$ssl_session_reused` | `r` = 重用、`.` = 完整交握 |
| `$ssl_server_name` | 客戶端送的 SNI |
| `$ssl_client_verify` | mTLS 驗證結果（`SUCCESS`／`FAILED:...`／`NONE`） |
| `$http_x_forwarded_proto` | 前端代理告知的原始協定（★★★★ 導向迴圈用它判斷） |

### `Verify return code` 對照

| 代碼 | 意義 | 通常是什麼問題 |
| --- | --- | --- |
| 0 | ok | 正常 |
| 10 | certificate has expired | 憑證過期 |
| 18 | self signed certificate | 自簽憑證且未信任 |
| 19 | self signed certificate in certificate chain | 自建 CA，客戶端沒裝根憑證 |
| 20 | unable to get local issuer certificate | ★★★★ 憑證鏈不完整或根不受信任 |
| 21 | unable to verify the first certificate | ★★★★ 同上 |

### HSTS 參數

| 寫法 | 意義 | 風險 |
| --- | --- | --- |
| `max-age=300` | 5 分鐘 | ★ 低，上線第一週用 |
| `max-age=86400` | 1 天 | ★★ |
| `max-age=2592000` | 30 天 | ★★★ |
| `max-age=31536000` | 1 年（A+ 需 ≥ 15552000） | ★★★★ |
| `; includeSubDomains` | 含所有子網域 | ★★★★★ 開前必須盤點全部子網域 |
| `; preload` | 送進瀏覽器內建清單 | ★★★★★ 移除要數個月 |
| `max-age=0` | 讓**新訪客**清除記錄 | 只對之後來的人有效 |

### 常用網址

| 用途 | 網址 |
| --- | --- |
| TLS 設定產生器 | <https://ssl-config.mozilla.org/> |
| 線上完整檢測與評分 | <https://www.ssllabs.com/ssltest/> |
| HSTS preload 送件與查詢 | <https://hstspreload.org> |
| 憑證透明度查詢（找出自家所有憑證） | <https://crt.sh> |

---

## 練習題

> [!question]- 練習 1：判讀憑證鏈（★★★★）
> 在一台測試機上，把 Nginx 的 `ssl_certificate` 從 `fullchain.pem` 改成 `cert.pem`，重載後：
> 1. 用桌機瀏覽器開站台，觀察是否有錯誤
> 2. 用 `curl -I https://<host>/` 觀察
> 3. 用 `openssl s_client -connect <host>:443 -servername <host> -showcerts </dev/null 2>/dev/null | grep -c "BEGIN CERTIFICATE"` 觀察
> 4. 用 `testssl.sh -S https://<host>` 觀察 `Chain of trust`
>
> **解答方向**
> - 瀏覽器多半**看起來正常**（靠 AIA 抓中繼或用快取），這正是本篇強調「不要用瀏覽器驗證」的原因
> - `curl` 會回 `curl: (60) SSL certificate problem: unable to get local issuer certificate`
> - `grep -c` 從 2 變成 **1**
> - `testssl.sh` 顯示 `Chain of trust NOT ok (chain incomplete)`
> - 改回 `fullchain.pem` 後三項都恢復
> 這個練習做完，你以後看到「電腦可以手機不行」就會直接想到這裡。

> [!question]- 練習 2：量測 TLS 版本分布（★★★★★）
> 在一台有實際流量的站台上：
> 1. 加上 `tlsinfo` 日誌格式並掛到站台
> 2. 蒐集至少三天
> 3. 統計各協定版本佔比
> 4. 把使用 TLS 1.0／1.1 的來源 IP 與 User-Agent 整理成一張表
> 5. 寫一段給主管的說明：可不可以停用、理由是什麼、若要停用需要先處理什麼
>
> **解答方向**
> - `awk -F'|' '{print $3}' ... | sort | uniq -c | sort -rn` 得到分布
> - 重點不在指令，在於**你能不能拿數字說話**。稽核問「為什麼還沒關 TLS 1.0」時，
>   「還有 0.03% 的流量來自兩台內部設備，已於某日發文請單位汰換」是專業回答；
>   「不知道會不會有人用所以不敢關」不是
> - 別忘了同時 `grep` `error.log` 找連交握都失敗的客戶端

> [!question]- 練習 3：HSTS 的分階段導入（★★★★★）
> 在**測試站台**上：
> 1. 設 `max-age=60`，用瀏覽器造訪一次
> 2. 把 Nginx 的 443 關掉（註解掉 HTTPS server 區塊、只留 80），重載
> 3. 用同一個瀏覽器造訪 `http://<host>/`，記錄看到什麼
> 4. 等 60 秒後再試一次
> 5. 把 443 恢復，再到 `chrome://net-internals/#hsts` 查詢與刪除該網域
>
> **解答方向**
> - 步驟 3 你會看到瀏覽器**直接拒絕連線**（它自己把 HTTP 改成 HTTPS，而 HTTPS 沒開），
>   而且**沒有任何「繼續前往」的選項**
> - 步驟 4 過了 `max-age` 之後才恢復
> - 親身體驗過這 60 秒，你就會理解為什麼 `max-age=31536000` 加 `includeSubDomains`
>   不能在沒盤點的情況下開下去

> [!question]- 練習 4：完成一次 A 級調校（★★★★）
> 對一台測試站台，完整走一次「完整實戰範例」的步驟 3～7：
> 1. 從 Mozilla 產生器取得 Intermediate 設定
> 2. 套用並 `nginx -t`
> 3. `testssl.sh --jsonfile round1.json`
> 4. 依報告逐項修正（至少修 OCSP stapling 與 HSTS）
> 5. `testssl.sh --jsonfile round2.json`
> 6. `diff` 兩份報告，寫出你改了什麼、分別解決什麼問題
>
> **解答方向**
> - 重點在**第 6 步**。能說出「這次改動讓 X 從 not offered 變成 offered，
>   解決的是 Y 問題」，才算真的懂，而不是把設定抄上去看到 A 就收工

> [!question]- 練習 5：導向迴圈重現與修復（★★★★）
> 用兩台機器（或兩個 Nginx server 區塊）模擬 LB + 後端：
> 1. 前端在 443 收 HTTPS，用 `proxy_pass http://backend;` 轉給後端的 80
> 2. 後端寫 `return 301 https://$host$request_uri;`
> 3. 用瀏覽器存取，記錄錯誤訊息
> 4. 在前端加 `proxy_set_header X-Forwarded-Proto $scheme;`
> 5. 把後端改成只有 `if ($http_x_forwarded_proto = "http")` 時才導向
> 6. 再測一次
>
> **解答方向**
> - 步驟 3 會看到 `ERR_TOO_MANY_REDIRECTS`
> - 步驟 6 恢復正常
> - 額外思考：如果 `X-Forwarded-Proto` 是由**外部使用者**送進來的（後端直接對外），
>   會發生什麼安全問題？（提示：使用者可以偽造這個標頭繞過強制 HTTPS）

---

## 小測驗

Q1. Nginx 的 `ssl_certificate` 該指向 Certbot 產出的哪一個檔案？指錯成 `cert.pem` 會有什麼具體症狀？

Q2.（是非）在桌機 Chrome 上開站台沒有出現憑證錯誤，就可以確定憑證鏈是完整的。

Q3. 這行指令少了什麼、會導致什麼誤判？
```bash
openssl s_client -connect www.example.gov.tw:443 < /dev/null
```

Q4.（選擇）要停用 TLS 1.0／1.1，最正確的第一步是：
(A) 直接改 `ssl_protocols TLSv1.2 TLSv1.3;` 並重載
(B) 先加上含 `$ssl_protocol` 的日誌格式，蒐集兩到四週的使用分布
(C) 發文請各單位回報有沒有在用
(D) 到 SSL Labs 掃一次看分數

Q5. `ssl_session_cache shared:MozSSL:10m;` 裡的 `10m` 指的是什麼？控制 session 存活時間的是哪個指令？

Q6.（是非）HSTS 設錯的話，把伺服器上的 `add_header Strict-Transport-Security` 那行刪掉，所有使用者就會立刻恢復正常。

Q7. 下面這段設定有一個嚴重問題，是什麼？
```nginx
server {
    add_header Strict-Transport-Security "max-age=31536000" always;
    location /api/ {
        add_header X-API-Version "2" always;
        proxy_pass http://backend;
    }
}
```

Q8. OCSP stapling 設定都寫了、`nginx -t` 也通過，但 `testssl.sh` 顯示 `OCSP stapling not offered`。在機關環境中，最常見的原因是什麼？

Q9.（簡答）為什麼本篇一再強調「不要從網路文章複製 `ssl_ciphers` 清單」？請說出至少兩個理由，以及正確的替代做法。

Q10.（選擇）站台在負載平衡器後面，使用者看到 `ERR_TOO_MANY_REDIRECTS`。最可能的原因是：
(A) 憑證鏈不完整
(B) LB 卸載 TLS 後用 HTTP 轉給後端，後端看到 HTTP 就 301 到 HTTPS
(C) HSTS 的 `max-age` 設太長
(D) TLS 1.3 沒有啟用

> [!question]- 測驗答案
> **Q1.** 應指 `fullchain.pem`（leaf + 中繼）。指成 `cert.pem`（只有 leaf）會造成憑證鏈不完整：
> 桌機瀏覽器多半正常（會用 AIA 或快取補中繼），但 `curl`、Java 客戶端、手機 App、
> 舊 Android 會失敗，訊息如 `unable to get local issuer certificate`、
> `PKIX path building failed`。★★★★ 見「憑證鏈完整性」與排錯表第 1 列。
>
> **Q2.** ✗ 錯。★★★★★ 這正是最大的陷阱 —— 桌機瀏覽器會自動從憑證的 AIA 欄位抓中繼，
> 或用之前快取的中繼，**幫你把洞補起來**。必須用 `openssl s_client -showcerts` 或
> `testssl.sh -S` 這種不會自動補的工具驗證。見「憑證鏈完整性」。
>
> **Q3.** 少了 **`-servername www.example.gov.tw`**（SNI）。一台機器上有多個 HTTPS 站台時，
> 沒送 SNI 伺服器會回**預設站台**的憑證，於是你會看到一張名字不符的憑證，
> 誤判成「憑證裝錯了」。★★★ 見「TLS 交握在做什麼」與排錯表第 17 列。
>
> **Q4.** **(B)**。★★★★★ 先量測才有決策依據。(A) 是最常造成事故的做法；
> (C) 靠回報通常收不到真實答案（沒人知道自己的事務機在用 TLS 1.0）；
> (D) 只告訴你分數，不告訴你**誰**會被影響。見「停用前怎麼確認沒有舊客戶端在用」。
>
> **Q5.** `10m` 是**共享記憶體的大小**（約 4 萬個 session），不是 10 分鐘。
> 存活時間由 `ssl_session_timeout` 控制（範例用 `1d`）。★★★ 這兩個很常被搞混，
> 見「Session resumption」。
>
> **Q6.** ✗ 錯。★★★★★ HSTS 記錄存在**使用者的瀏覽器裡**，伺服器端刪掉標頭只會讓
> **之後新來的訪客**不再拿到；已經記住的使用者要等 `max-age` 過期，或自己去
> `chrome://net-internals/#hsts` 手動刪除。這就是「HSTS 是不可逆的」的意思。
>
> **Q7.** ★★★★ `/api/` 這個 location 裡出現了 `add_header`，會讓**父層 `server` 的所有
> `add_header` 全部失效** —— 也就是 `/api/` 底下**沒有 HSTS 標頭**。
> Nginx 的 `add_header` 不繼承累加，只要子區塊有任何一個就整組覆蓋。
> 修法是在該 location 把 HSTS 重寫一次，或改用 `ngx_headers_more` 的 `more_set_headers`。
> 見「HSTS 的分階段導入」的 danger 區塊與排錯表第 14 列。
>
> **Q8.** ★★★★ 機關防火牆通常只放行對外 443、擋掉對外 80，而 **OCSP 查詢走的是 HTTP（80 埠）**，
> 導致 Nginx 拿不到 OCSP 回應。次常見原因是沒設 `resolver`，Nginx 解析不了 CA 的網址。
> 用 `curl -sI -m 5 http://<OCSP主機>/` 從伺服器上驗證。見「OCSP stapling 的驗證與排錯」。
>
> **Q9.** 至少兩個理由：(1) 舊清單可能包含**現在已視為不安全**的套件（3DES、舊 CBC 組合）；
> (2) 會**缺少新的、更好的**套件，反而傷害相容性與效能；(3) 你看不懂自己貼了什麼，
> 稽核問不出來、出事改不動。正確做法：用 <https://ssl-config.mozilla.org/> 依
> **Server 版本 + OpenSSL 版本 + 相容等級（多數選 Intermediate）** 產生，
> 把產生日期寫進註解，並用 `testssl.sh` 驗證、**每年重新產生一次**。★★★★★
>
> **Q10.** **(B)**。LB 卸載 TLS 之後用 HTTP 連後端，後端的「HTTP 一律 301 到 HTTPS」規則
> 就會無限循環。解法是改判斷 `$http_x_forwarded_proto`，或把導向做在 LB 上；
> CDN 環境另外要檢查 SSL 模式是不是設成 Flexible。★★★★ 見「從 HTTP 導向 HTTPS 而不製造迴圈」
> 與排錯表第 6 列。

---

## 延伸閱讀

### 本手冊內

**憑證本身（PKI 專章，本篇的上游）**

- [[090-01-00-idx-PKI-憑證與PKI]] —— 憑證專章總覽
- [[090-01-01-guide-PKI-PKI與憑證基礎]] —— 名詞與信任模型
- [[090-01-04-guide-PKI-CN與SAN設定與瀏覽器相容性]] —— 名稱不符問題的根源
- [[090-01-07-guide-PKI-自建中繼CA與憑證鏈]] —— 憑證鏈怎麼組出來
- [[090-01-11-guide-PKI-憑證格式轉換與檢視工具]] —— PEM／DER／PFX 與檢視指令
- [[090-01-12-guide-PKI-憑證生命週期管理]] —— 續期自動化與到期告警（★★★★ 開 HSTS 的前提）
- [[090-01-13-guide-PKI-憑證常見問題排查]] —— 憑證層面的排錯
- [[090-01-14-guide-PKI-機關憑證來源GCA與TWCA]] —— 機關怎麼申請

**伺服器設定**

- [[060-02-02-06-guide-Nginx-HTTPS與Certbot]] —— Nginx 掛 HTTPS 的基礎
- [[060-02-02-09-guide-Nginx-安全設定]] —— Nginx 的其他安全項目
- [[060-02-03-05-guide-Apache-HTTPS設定]] —— Apache 對照
- [[060-02-03-07-guide-Apache-安全與效能]] —— Apache 安全設定
- [[060-02-04-guide-Web-Nginx與Apache選型與共存]] —— 兩者取捨
- [[060-02-05-03-guide-MyGuard-autocert自動憑證模組]] —— Nginx 內建 ACME，不需 certbot
- [[060-02-05-02-guide-MyGuard-Angie伺服器入門]] —— 內建 QUIC／HTTP-3 的選擇

**往外一層**

- [[090-03-02-guide-應用安全-應用層安全]] —— 安全標頭、Cookie、資訊洩漏（★★★★ 建議接著讀）
- [[090-03-03-guide-應用安全-機密管理與金鑰保護]] —— 私鑰怎麼保管
- [[090-03-06-guide-應用安全-委外系統上線前資安檢測]] —— 驗收廠商系統
- [[090-04-00-idx-ModSecurity]] —— 外加一層 WAF
- [[090-05-04-guide-資安設備-Web應用防火牆WAF]] —— WAF 設備選型
- [[090-05-11-guide-資安設備-DDoS防護與CDN]] —— CDN 前面那一層的 TLS 怎麼算
- [[100-01-04-guide-日誌-健康檢查與可用性監控]] —— 把驗收腳本接上監控

### 外部資源

| 資源 | 網址 | 用途 |
| --- | --- | --- |
| Mozilla SSL Configuration Generator | <https://ssl-config.mozilla.org/> | ★★★★★ 產生設定的唯一推薦來源 |
| Mozilla Server Side TLS 指引 | <https://wiki.mozilla.org/Security/Server_Side_TLS> | 三個等級背後的判準 |
| Qualys SSL Labs Server Test | <https://www.ssllabs.com/ssltest/> | ★★★★ 外部評分，稽核常引用 |
| testssl.sh | <https://testssl.sh/> | ★★★★★ 可離線、可存檔的完整檢測 |
| HSTS Preload | <https://hstspreload.org> | preload 送件與條件說明 |
| crt.sh 憑證透明度查詢 | <https://crt.sh> | ★★★ 盤點「我們到底簽過哪些憑證」 |
| RFC 8446（TLS 1.3） | <https://www.rfc-editor.org/rfc/rfc8446> | 規格原文 |
| RFC 8996（棄用 TLS 1.0／1.1） | <https://www.rfc-editor.org/rfc/rfc8996> | ★★★ 停用舊協定時的正式依據，寫簽呈可引用 |
| RFC 6797（HSTS） | <https://www.rfc-editor.org/rfc/rfc6797> | HSTS 規格 |
| Nginx `ngx_http_ssl_module` 文件 | <https://nginx.org/en/docs/http/ngx_http_ssl_module.html> | 指令的權威說明 |
