---
title: "資安情資研判與IoC比對"
desc: "收到情資單之後實際要做什麼：判斷適用性、逐類比對 IoC、判定影響三分法與回報"
aliases: [情資研判, IoC, Indicator of Compromise, 威脅情資, Threat Intelligence, 情資單, 影響評估]
tags: [群組/資訊安全, 安全/實踐規範, 主題/情資研判]
category: 資安實踐與規範
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[100-02-13-guide-維運-資產與授權管理]]", "[[090-05-09-guide-資安設備-日誌集中與SIEM]]"]
updated: 2026-09-03
---

# 資安情資研判與IoC比對

## 這篇你會學到

> [!abstract] 學習目標
> - 看懂一份情資單的**五個組成部分**，知道哪一部分決定你要不要動手
> - 用**四步流程**處理情資：判斷適用性 → 比對 IoC → 判定影響 → 處置與回報
> - 針對 **IP／網域／檔案雜湊／檔案路徑／程序連線／行為特徵** 六類 IoC，各給出可以直接跑的比對指令
> - 寫出一支**吃 IoC 清單、輸出比對結果**的整合腳本
> - 分清「無命中」與「**無法確認**」的差別，以及後者為什麼是最常見也最該修的結論
> - 知道平時要準備什麼，才不會在情資來的當天才發現自己什麼都查不到

## 前置知識

| 你需要先會 | 為什麼 | 對應篇章 |
| --- | --- | --- |
| 有一份可信的資產清冊 | 第一步「適不適用」完全靠它 | [[100-02-13-guide-維運-資產與授權管理]] |
| 知道自己的日誌收在哪、留多久 | 第二步比對 IoC 靠它 | [[090-05-09-guide-資安設備-日誌集中與SIEM]] |
| `grep`／`find`／`awk` 基本用法 | 比對就是大量的搜尋 | [[020-01-07-cmd-Linux-尋找檔案與內容]] |
| 看得懂 `ps` 與 `ss` 的輸出 | 即時比對程序與連線 | [[020-01-10-cmd-Linux-程序管理與訊號]] |
| 知道事件應變的六階段 | 命中之後就進入應變流程 | [[090-07-04-guide-資安實踐-資安事件應變流程]] |

> [!note] 這篇跟弱點管理是兩件事
> [[090-07-03-guide-資安實踐-弱點與修補管理流程]] 處理的是「**我可能會被打**，所以要修補」；
> 這篇處理的是「**我可能已經被打了**，所以要查」。
> 同一封來文常常兩件事都要做 —— 修補是給未來，比對 IoC 是查過去。

---

## 觀念說明

### 一份公文引發的三小時 ★★★

現場真實的情境長這樣：

> 星期三下午四點，收到主管機關轉發的資安情資，主旨大意是
> 「○○ 框架存在重大遠端程式碼執行漏洞，已有實際攻擊案例，
> 請各機關**自行檢視是否受影響並於期限內回報**」。
> 附件是一份 PDF，裡面有版本範圍、三個惡意 IP、兩個 C2 網域、
> 一個 webshell 的 SHA-256、以及一個檔案落地路徑。

這時候會發生的三件事：

1. 有人說「我們沒有用那個東西吧」—— 但沒有人拿得出證據。
2. 有人打開防火牆管理介面想查那三個 IP，發現日誌只留 7 天，而情資說攻擊從兩個月前開始。
3. 期限快到了，回報單上填「經查未受影響」—— 其實是**沒查出來**，不是**沒有**。

★★★★★ **這篇要解決的就是第 3 點。「查不到」和「沒有」是完全不同的兩個結論，
把前者寫成後者，是機關資安最常見、也最致命的一種自我欺騙。**

### 情資從哪裡來 ★★★

| 來源 | 典型形式 | 可信度 | 時效性 | 處理原則 |
| --- | --- | --- | --- | --- |
| **主管機關／上級機關來文** ★★★★★ | 公文＋PDF 附件 | 高 | 中（已經過篩選轉發，可能落後數天） | **一定要回**，有期限，流程照走 |
| **國家級 CERT／CSIRT 通告** ★★★★ | 網頁公告、訂閱電子報 | 高 | 快 | 主動訂閱，當作預警 |
| **產品廠商安全公告（PSIRT）** ★★★★ | 廠商官網、郵件清單 | 對自家產品最準 | 快 | 只看你有用的產品，訂閱清單要跟資產清冊對齊 |
| **上游套件／專案的 advisory** ★★★ | GitHub Security Advisory、發行說明 | 高 | 最快 | 開發團隊該訂，維運端從這裡拿到版本號 |
| **商業威脅情資（TI feed）** ★★★ | STIX/TAXII、CSV、API | 高但量大 | 快 | 要有 SIEM 才吃得下，人工處理不了 |
| **資安社群、部落格、社群媒體** ★★ | 貼文、技術分析 | **參差不齊** | 最快 | 當線索用，**不要當結論用**；一定要找到原始出處 |
| **廠商業務轉貼的「情報」** ★ | 簡報、行銷郵件 | 低（常混雜銷售目的） | 不定 | 資訊要自己回頭查證，不要直接引用進公文 |

> [!warning] 可信度與時效性通常互相衝突 ★★★
> 最快的消息（社群、推文）最不可靠；最可靠的消息（正式公文）通常最慢。
> 實務做法是：**用快的來源提早準備、用慢的來源作為正式依據**。
> 看到社群消息先去查資產清冊有沒有這個產品，等正式公告到就能立刻回報。

### 什麼是 IoC ★★★★

**IoC（Indicator of Compromise，入侵指標）** 是「如果在你的環境裡看到它，
就代表你可能已經被入侵」的具體特徵。它跟「弱點」的差別是：

- **弱點**（CVE、版本號）＝ 你**可能會**被打的條件
- **IoC**（IP、雜湊、路徑）＝ 你**已經**被打的痕跡

常見的 IoC 類型：

| 類型 | 範例 | 在哪裡比對 | 好不好用 |
| --- | --- | --- | --- |
| **IP 位址** | `203.0.113.45` | 防火牆／Proxy／Netflow／Web 日誌 | 容易比對，但攻擊者換 IP 很快 ★★ |
| **網域名稱** | `cdn-update.example.net` | DNS 查詢紀錄、Proxy 日誌 | 同上，稍微持久一點 ★★ |
| **URL／路徑** | `/wp-content/uploads/x.php` | Web access log | 對 Web 攻擊很有用 ★★★ |
| **檔案雜湊** | SHA-256／SHA-1／MD5 | 檔案系統掃描、EDR | **精準但脆弱**（改一個位元組就變了）★★★ |
| **檔案名稱／落地路徑** | `/tmp/.ICE-unix/sshd` | `find` | 比雜湊耐用 ★★★ |
| **Registry 鍵值** | `HKLM\...\Run\Updater` | Windows 登錄檔 | Windows 專用 ★★★ |
| **程序／服務名稱** | 偽裝成 `[kworker/0:2]` 的使用者行程 | `ps`／`ss` | 需要基線才判得出來 ★★★★ |
| **行為特徵（TTP）** | 「凌晨三點從境外 IP 用服務帳號登入成功」 | SIEM 關聯規則 | **最難仿冒、最耐用**，但也最難比對 ★★★★★ |

### IoC 金字塔：為什麼有些指標比較值錢 ★★★

由下而上，**對攻擊者來說越難改變**、對你來說越持久：

```text
              ┌─────────────────────┐
              │  TTP（行為手法）      │ ★★★★★ 攻擊者最難改，最耐用
              ├─────────────────────┤
              │  工具（Tools）        │ ★★★★
              ├─────────────────────┤
              │  網路／主機痕跡        │ ★★★
              ├─────────────────────┤
              │  網域名稱             │ ★★
              ├─────────────────────┤
              │  IP 位址              │ ★★
              ├─────────────────────┤
              │  檔案雜湊             │ ★  改一個位元組就失效
              └─────────────────────┘
```

★★★ **實務意義**：情資單上只給雜湊時，比對「沒命中」的參考價值很低 ——
攻擊者只要重新編譯一次，你的雜湊就對不上了。
所以**雜湊沒命中不等於乾淨**，還要往上比對路徑、程序、行為。

### 一份情資單通常有什麼 ★★★★★

不管是哪一種來源，形式再怎麼不同，內容大致就是這五塊。
**收到情資的第一件事，是把這五塊拆出來**：

| 區塊 | 內容 | 你要拿它做什麼 |
| --- | --- | --- |
| ① **受影響的產品與版本** ★★★★★ | 產品名稱、版本範圍、受影響的元件 | 拿去對**資產清冊**，決定適不適用 |
| ② **漏洞資訊** ★★★ | CVE 編號、CVSS 分數、攻擊條件（是否需認證、是否可遠端） | 決定嚴重程度與處理順序 |
| ③ **IoC 清單** ★★★★★ | IP、網域、URL、雜湊、路徑、registry 鍵、行為描述 | 拿去比對日誌與主機，決定有沒有中 |
| ④ **建議處置** ★★★★ | 升級到哪個版本、暫時緩解措施（關閉功能、加 WAF 規則） | 排修補計畫 |
| ⑤ **通報／回報要求** ★★★★★ | 回報對象、格式、期限、要附什麼佐證 | **照來文所載辦理**，不要自己猜 |

> [!danger] ★★★★★ 不要跳過 ① 直接做 ③
> 常見的錯誤是一看到 IoC 就開始 grep，花了一整天比對，
> 最後才發現這個產品機關根本沒有裝。
> **先確定適用性，能省下 90% 的工。**
> 反過來也一樣危險：確認「我們沒有裝這個產品」就結案，卻忽略情資裡的 C2 IP
> 可能同時被用在**別的攻擊活動**上 —— 這種情況下 IP／網域類 IoC 仍然值得掃一遍。

### 三種結論，不是兩種 ★★★★★

比對之後只能得到三種結論之一，**絕對不要把第三種寫成第二種**：

| 結論 | 意思 | 後續動作 |
| --- | --- | --- |
| **有命中** ★★★★★ | 找到明確的 IoC 痕跡 | 立刻進入事件應變（[[090-07-04-guide-資安實踐-資安事件應變流程]]），**先保全證據**再談其他 |
| **無命中** ★★★ | 涵蓋範圍內的資料都查過，沒有發現 | 回報「未發現受影響跡象」，**並註明查核範圍與資料涵蓋期間** |
| **無法確認** ★★★★★ | 沒有相關日誌、日誌已輪替刪除、資產清冊不全 | **誠實回報「無法確認」**，並把缺口列為改善事項 |

> [!tip] 回報時的一句話模板 ★★★★
> 「經比對防火牆與 Web 存取日誌（保存期間 2026-08-05 至 2026-09-03），
> **於該期間內**未發現與所列 IoC 相符之連線紀錄；
> 惟情資所述攻擊起始時間早於本機關日誌保存期間，**該期間之前無法確認**。」
>
> 這句話同時做到：說明查了什麼、查到什麼、以及**誠實揭露查核的邊界**。

---

## 安裝或基礎操作

### 四步標準流程 ★★★★★

```text
情資單進來
   │
   ├─ [第 0 步] 登記與分流（誰負責、期限幾號）
   │
   ├─ [第 1 步] 判斷適用性 ──── 不適用 ──┐
   │      （查資產清冊）                  │
   │            │ 適用                    │
   │            ▼                         │
   ├─ [第 2 步] 比對 IoC                  │
   │      （日誌 → 主機 → 即時狀態）      │
   │            │                         │
   │            ▼                         │
   ├─ [第 3 步] 判定影響                  │
   │      有命中 / 無命中 / 無法確認      │
   │            │                         │
   │            ├─ 有命中 → 事件應變流程  │
   │            │                         │
   │            ▼                         ▼
   └─ [第 4 步] 處置與回報 ◄──────────────┘
          （修補計畫 + 依來文格式回報）
```

**時序建議**（實務上抓得到的節奏，不是硬性規定）：

| 時間點 | 該完成 |
| --- | --- |
| 收到後 **當天** ★★★★ | 第 0、1 步 —— 至少知道「適不適用」，適用的話通知主管 |
| 收到後 **1～2 個工作天** ★★★★ | 第 2 步日誌比對（可自動化的部分） |
| 收到後 **2～3 個工作天** ★★★ | 第 2 步主機掃描（要排時段，避開尖峰） |
| **回報期限前一天** ★★★★★ | 第 3、4 步完成，回報內容給主管確認 |

> [!warning] 期限一律以來文所載為準 ★★★★★
> 不同來文、不同事件等級的回報期限都不一樣，**不要背一個固定天數**。
> 收到當天就把期限寫進行事曆或工單系統，這是第 0 步最重要的事。

### 第 0 步：登記與分流 ★★★

情資最容易死在「大家都看到了，但沒有人接」。所以第一件事是留紀錄：

| 欄位 | 範例 |
| --- | --- |
| 情資編號／來文文號 | （依實際來文填） |
| 收到日期 | 2026-09-03 |
| 來源 | 主管機關來文 |
| 主題 | ○○ 框架 RCE 漏洞 |
| 受影響產品／版本 | ○○ Framework < 6.4.2 |
| 回報期限 | （依來文所載） |
| 負責人 | 王○○ |
| 目前狀態 | 適用性評估中 |
| 結論 | （待填） |

★★★ 這張表就是日後稽核時的證據。[[090-07-16-guide-資安實踐-政府資安健診的準備與執行]]
會被問到「你們怎麼處理外部情資」，這張表就是答案。

### 第 1 步：判斷適用性 ★★★★★

**這一步靠的是資產清冊，沒有清冊就只能瞎猜。**

要回答三個問題：

1. **我們有沒有這個產品／元件？**
2. **有的話，版本落在受影響範圍內嗎？**
3. **就算版本符合，攻擊前提成立嗎？**（例如「需要該功能啟用」「需要對外開放」）

#### 從資產清冊查（最快，但清冊要準）★★★★

```bash
# 假設資產清冊是一份 CSV：主機名,IP,用途,作業系統,主要軟體,版本,對外開放
grep -i "framework" /srv/資產/資產清冊.csv
```

預期輸出：

```text
web01,10.10.1.11,對外官網,Ubuntu 24.04,OO-Framework,6.3.8,是
web02,10.10.1.12,內部表單,Ubuntu 24.04,OO-Framework,6.4.5,否
```

判讀：`web01` 版本 6.3.8 落在 `< 6.4.2` 範圍內 → **適用**；`web02` 6.4.5 → 不適用。

#### 直接到主機上驗證（最準，清冊不準時的救命方法）★★★★★

```bash
# Debian／Ubuntu：查套件版本
dpkg -l | grep -i nginx
apt list --installed 2>/dev/null | grep -i php

# 精確查單一套件
dpkg-query -W -f='${Package} ${Version} ${Status}\n' nginx
```

預期輸出：

```text
nginx 1.24.0-2ubuntu7.4 install ok installed
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> rpm -qa | grep -i nginx
> rpm -q --qf '%{NAME} %{VERSION}-%{RELEASE}\n' nginx
> dnf list installed | grep -i php
> ```
> RHEL 系常見的陷阱：套件版本號會被**回溯修補（backport）**，
> 例如 `nginx-1.20.1-14.el9_2.1` 的上游版本雖然是 1.20.1，
> 但發行商可能已經把修補打進 `-14` 這個 release 號裡。
> ★★★★ **不要只看上游版本號就判定受影響**，要查發行商的 errata 說明。

語言層套件（框架、函式庫）不在系統套件管理員裡，要另外查：

```bash
# PHP（Composer 專案）
composer show --format=json 2>/dev/null | head -40
composer show | grep -i laravel

# Node.js
npm ls --depth=0
npm ls <套件名>            # 查是否為間接相依

# Python
pip list 2>/dev/null | grep -i requests
pip3 freeze | grep -i django
```

★★★★ **間接相依是最容易漏掉的**。你沒有直接安裝那個套件，
但你安裝的某個套件相依它。`npm ls <套件名>` 和 `composer why <套件名>`
就是查這個用的。

#### 適用性判定表 ★★★★

| 有這個產品？ | 版本在範圍內？ | 攻擊前提成立？ | 結論 |
| --- | --- | --- | --- |
| 否 | — | — | **不適用**（但 IP／網域類 IoC 仍建議掃一遍）★★★ |
| 是 | 否 | — | 不適用，記錄版本作為佐證 ★★ |
| 是 | 是 | 否（例如該功能未啟用、未對外） | **降級但仍需比對**，並列入修補計畫 ★★★★ |
| 是 | 是 | 是 | **適用，最高優先**，立即進入第 2 步 ★★★★★ |
| **查不到** ★★★★★ | — | — | **這本身就是一個發現** —— 資產清冊有缺口，要列為改善事項 |

### 第 2 步：比對 IoC 的順序 ★★★★

比對有先後，**先做便宜的、涵蓋面廣的，再做昂貴的、單機的**：

| 順序 | 做什麼 | 成本 | 涵蓋範圍 |
| --- | --- | --- | --- |
| ① | 集中日誌／SIEM 全文搜尋 IP、網域、URL | 低 | 全機關 ★★★★★ |
| ② | 防火牆／Proxy／DNS 日誌 | 低 | 全機關網路層 ★★★★ |
| ③ | 受影響主機的 Web／應用日誌 | 中 | 單機 ★★★★ |
| ④ | 受影響主機的即時狀態（`ps`／`ss`） | 低 | 單機當下 ★★★ |
| ⑤ | 受影響主機的檔案系統掃描（雜湊、路徑） | **高**（I/O 重） | 單機歷史 ★★★★ |
| ⑥ | 全機關端點掃描（透過 EDR／Wazuh 派工） | 中 | 全機關 ★★★★★ |

> [!danger] ★★★★★ 如果 ① 到 ④ 任一步命中，立刻停手
> 命中就代表這台可能是**現場**。繼續在上面 `find /` 全機掃描會大量改動 atime、
> 覆寫證據、甚至觸發攻擊者留下的清除機制。
> 正確動作是：**隔離網路但保持開機**，然後照
> [[090-07-15-guide-資安實踐-被入侵主機的跡證檢查]] 的順序保全證據。

### 準備一個工作台 ★★★

比對之前先把 IoC 整理成機器讀得懂的格式，後面所有指令都吃這幾個檔：

```bash
sudo install -d -m 0750 /var/lib/ioc/2026-09-03-OO框架RCE
cd /var/lib/ioc/2026-09-03-OO框架RCE
```

```bash
# ip.txt —— 一行一個 IP
cat > ip.txt <<'EOF'
203.0.113.45
198.51.100.77
192.0.2.201
EOF

# domain.txt —— 一行一個網域
cat > domain.txt <<'EOF'
cdn-update.example.net
sync.badhost.example
EOF

# hash.txt —— 一行一個 SHA-256（小寫）
cat > hash.txt <<'EOF'
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
EOF

# path.txt —— 一行一個檔名或路徑片段
cat > path.txt <<'EOF'
/tmp/.ICE-unix/sshd
uploads/x.php
EOF
```

★★★ **統一小寫、去掉空白、去掉 BOM**。從 PDF 複製貼上的 IoC
常常帶著全形空白或不可見字元，會讓 `grep -F` 完全比不到：

```bash
# 清洗：去 BOM、去 CR、去前後空白、去空行、轉小寫
sed -i 's/\xEF\xBB\xBF//; s/\r$//; s/^[[:space:]]*//; s/[[:space:]]*$//' *.txt
sed -i '/^$/d' *.txt
tr 'A-Z' 'a-z' < hash.txt > hash.lower.txt && mv hash.lower.txt hash.txt
```

驗證清洗結果（★★★ 用 `cat -A` 看不可見字元）：

```bash
cat -A ip.txt | head -3
```

預期輸出（結尾只有 `$`，沒有 `^M` 或 `M-oM-;M-?`）：

```text
203.0.113.45$
198.51.100.77$
192.0.2.201$
```

---

## 進階應用

### IoC 比對法一：IP 與網域 ★★★★★

#### 集中日誌／SIEM（最理想）

有集中日誌時，這是**唯一一個一次涵蓋全機關**的做法：

```bash
# journald 集中收容時，用 grep -F -f 一次比對整份清單
sudo journalctl --since "2026-06-01" --no-pager \
  | grep -F -f /var/lib/ioc/2026-09-03-OO框架RCE/ip.txt
```

Wazuh／Elastic 之類的介面上則是一條查詢語句，把 IP 清單放進 `should` 條件。
詳見 [[090-05-09-guide-資安設備-日誌集中與SIEM]] 與 [[090-08-00-idx-Wazuh資安監控]]。

#### 防火牆日誌 ★★★★

```bash
# 如果防火牆把 syslog 送到 /var/log/fw/，含壓縮輪替檔一起查
sudo zgrep -F -f /var/lib/ioc/2026-09-03-OO框架RCE/ip.txt /var/log/fw/*.log*
```

預期輸出（有命中時）：

```text
/var/log/fw/2026-08-14.log.gz:Aug 14 03:12:44 fw01 filterlog: 
  pass,in,igb0,tcp,203.0.113.45,50122,10.10.1.11,443,SYN
```

★★★★ 命中一行就夠了 —— **停手，進入事件應變**。不要為了「多找幾筆」繼續翻。

> [!info]- Juniper SRX 上直接查 ★★★
> ```junos
> show log messages | match 203.0.113.45
> show security flow session destination-prefix 203.0.113.45
> ```
> 前者查歷史日誌，後者查**當下還存在的連線**。
> 若 SRX 未設定 syslog 外送，本機日誌容量有限，很快就輪替掉了。

> [!info]- Cisco IOS 對照
> ```cisco
> show logging | include 203.0.113.45
> show ip access-lists   ! 看 ACL 的命中計數
> ```

#### Web 伺服器存取日誌 ★★★★

```bash
# Nginx / Apache 存取日誌（含輪替）
sudo zgrep -F -f /var/lib/ioc/2026-09-03-OO框架RCE/ip.txt \
  /var/log/nginx/access.log* /var/log/apache2/access.log* 2>/dev/null
```

也可以反過來，看某個 IP 到底做了什麼：

```bash
sudo zgrep '203\.0\.113\.45' /var/log/nginx/access.log* \
  | awk '{print $7}' | sort | uniq -c | sort -rn | head -20
```

預期輸出：

```text
     87 /index.php
     41 /api/v1/render
      3 /wp-content/uploads/x.php     ← ★★★★★ 這一行就是命中
      1 /
```

★★★★★ **看到 IoC 路徑出現在自己的 access log 且回應碼為 200，
基本上就是命中了。** 加上 `$9`（狀態碼）確認：

```bash
sudo zgrep 'uploads/x\.php' /var/log/nginx/access.log* \
  | awk '{print $1, $4, $7, $9}'
```

#### DNS 查詢紀錄 ★★★★

網域類 IoC 最有價值的地方是：**就算連線被防火牆擋掉，DNS 查詢還是會留下**，
代表那台機器上有東西「想要」連出去。

```bash
# BIND：需先啟用 query log
sudo rndc querylog on            # 開啟（會大量寫入，查完記得關）
sudo grep -F -f /var/lib/ioc/2026-09-03-OO框架RCE/domain.txt /var/log/named/query.log
sudo rndc querylog off
```

```bash
# dnsmasq：需在設定檔加 log-queries 後重啟，查 journal
sudo journalctl -u dnsmasq --since "2026-08-01" --no-pager \
  | grep -F -f /var/lib/ioc/2026-09-03-OO框架RCE/domain.txt
```

```bash
# systemd-resolved（用戶端本機）
sudo resolvectl statistics
sudo journalctl -u systemd-resolved --since "-30d" --no-pager | grep -F -f domain.txt
```

> [!warning] ★★★★ DNS 查詢紀錄預設多半是關的
> 這是機關最常見的「無法確認」原因之一。DNS 查詢日誌量大，但價值極高 ——
> 建議至少在**對外 DNS forwarder** 上開啟並集中收容。

#### ★ 沒有集中日誌時的替代做法

| 情況 | 替代做法 | 限制 |
| --- | --- | --- |
| 防火牆沒送 syslog | 登入防火牆本機看日誌 | 保存期通常只有幾天到數週 ★★★ |
| 沒有 Proxy | 查各主機的 `access.log`、應用日誌 | 只涵蓋有日誌的服務 ★★ |
| 沒有 DNS 日誌 | 查主機上的 DNS 快取（若有）、`/etc/hosts` 被改的痕跡 | 涵蓋範圍極小 ★★ |
| 什麼都沒有 | **從現在開始抓** —— 部署封包擷取或臨時規則 | 只能涵蓋未來，不能回溯 ★★★★ |

★★★★★ 最後一列是重點：**現在開始抓，至少能證明「從今天起沒有」**。

```bash
# 臨時：在對外閘道上針對 IoC IP 建立一條記錄用規則（nftables）
sudo nft add rule inet filter forward ip daddr { 203.0.113.45, 198.51.100.77 } \
  log prefix "IOC-HIT " counter

# 查命中次數
sudo nft list ruleset | grep -A2 'IOC-HIT'
```

```bash
# 臨時：用 tcpdump 在對外介面守著（背景執行，輪替存檔）
sudo tcpdump -i eth0 -nn -w /var/log/ioc-%Y%m%d%H.pcap -G 3600 -W 48 \
  'host 203.0.113.45 or host 198.51.100.77'
```

★★★ `-G 3600 -W 48` ＝ 每小時一個檔、最多留 48 個，避免把磁碟塞爆。

### IoC 比對法二：檔案雜湊 ★★★★

#### 基本寫法

```bash
# 單檔驗證
sha256sum /var/www/html/wp-content/uploads/x.php
```

預期輸出：

```text
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  /var/www/html/wp-content/uploads/x.php
```

#### 全機掃描的正確寫法 ★★★★★

**天真的寫法（不要用）**：

```bash
# ★★★★★ 反例：會掃到 /proc /sys、會跨掛載點掃 NFS、會卡住數小時
find / -type f -exec sha256sum {} \;
```

**實務寫法**：

```bash
sudo find / -xdev -type f -size -30M \
     ! -path '/proc/*' ! -path '/sys/*' ! -path '/dev/*' ! -path '/run/*' \
     -print0 2>/dev/null \
  | xargs -0 -r -P 2 -n 200 sha256sum 2>/dev/null \
  | grep -F -f /var/lib/ioc/2026-09-03-OO框架RCE/hash.txt
```

逐項說明：

| 參數 | 作用 | 為什麼重要 |
| --- | --- | --- |
| `-xdev` ★★★★★ | 不跨檔案系統邊界 | 避免掃到 NFS／CIFS 掛載，那會拖垮網路又掃不完 |
| `-size -30M` ★★★★ | 只算 30MB 以下的檔 | webshell、後門執行檔都很小；大檔算雜湊最耗時 |
| `! -path '/proc/*'` ★★★★ | 排除虛擬檔案系統 | `/proc` 下的檔讀取會阻塞 |
| `-print0` ＋ `xargs -0` ★★★★ | 用 NUL 分隔 | 檔名含空白／換行時不會出錯 |
| `-P 2` ★★★ | 平行 2 個行程 | 加速但不打爆 I/O；正式機建議不超過 CPU 核心數的一半 |
| `-n 200` ★★★ | 每次帶 200 個檔 | 減少行程建立次數 |
| `2>/dev/null` ★★ | 吃掉「權限不足」訊息 | 輸出才看得清楚 |

★★★★ **加上 `ionice` 和 `nice`，正式機掃描時服務才不會被拖垮**：

```bash
sudo ionice -c3 nice -n 19 find / -xdev -type f -size -30M \
     ! -path '/proc/*' ! -path '/sys/*' -print0 2>/dev/null \
  | xargs -0 -r -P 2 -n 200 sha256sum 2>/dev/null > /var/lib/ioc/allhash.txt
```

`ionice -c3` ＝ idle 等級 I/O，只在系統空閒時才做；`nice -n 19` ＝ 最低 CPU 優先權。

先存全量再比對的好處 ★★★★：**這份 `allhash.txt` 之後拿到新情資可以重複使用，
不必再掃一次磁碟**，而且它同時是一份基線。

```bash
grep -F -f /var/lib/ioc/2026-09-03-OO框架RCE/hash.txt /var/lib/ioc/allhash.txt
```

#### 效能參考 ★★★

| 情況 | 大致耗時 |
| --- | --- |
| 20GB 系統碟、SSD、`-size -30M` | 數分鐘到十幾分鐘 |
| 同上但機械硬碟 | 半小時到數小時 |
| 沒加 `-xdev`、掛了 2TB NFS | **可能跑一整晚還跑不完** ★★★★★ |

> [!warning] ★★★★ 掃描會大量改動 atime
> 如果這台已經懷疑被入侵，**全機掃描本身就是破壞證據**。
> 正確順序是：先做映像／先收集揮發性證據，再在**副本**上掃描。
> 見 [[090-07-15-guide-資安實踐-被入侵主機的跡證檢查]]。
> 若必須在原機掃，可用 `find ... -noatime` 不可用的話改用掛載選項
> `mount -o remount,noatime`（★★ 這本身也是一次改動，要記錄下來）。

#### 情資只給 MD5／SHA-1 時 ★★★

```bash
md5sum /path/to/file
sha1sum /path/to/file
```

★★★ MD5 有碰撞風險，但**當作 IoC 比對仍然可用** —— 攻擊者不會費工去做碰撞
來騙你的比對。有 SHA-256 就優先用 SHA-256。

### IoC 比對法三：檔案路徑與檔名 ★★★★

比雜湊耐用，因為攻擊工具常常寫死落地路徑。

```bash
# 精確路徑
sudo ls -la /tmp/.ICE-unix/sshd 2>/dev/null

# 檔名比對（大小寫不敏感）
sudo find / -xdev -iname 'x.php' 2>/dev/null

# 路徑片段比對
sudo find /var/www -xdev -path '*uploads*' -name '*.php' -ls 2>/dev/null
```

★★★★★ 最後一條是**通用的 webshell 獵捕手法**：
「上傳目錄裡出現 `.php`」在絕大多數正常環境都不該發生。

預期輸出（有問題時）：

```text
262147  4 -rw-r--r--  1 www-data www-data  2841 Aug 14 03:15 /var/www/html/wp-content/uploads/x.php
```

★★★★ 注意 **擁有者是 `www-data`** —— 代表這個檔是**由 Web 服務本身寫出來的**，
而不是管理員部署的。這是強烈的入侵指標。

#### 隱藏目錄與檔案 ★★★★★

攻擊者最愛藏在這幾個地方，`find` 預設**會**找到它們，但人眼 `ls` 看不到：

```bash
# 找隱藏目錄（以 . 開頭）
sudo find /tmp /var/tmp /dev/shm -xdev -name '.*' -maxdepth 2 -ls 2>/dev/null

# 找名字看起來像空白或點的詭異目錄
sudo find /tmp /var/tmp -xdev \( -name '. ' -o -name '..' -o -name '...' \) -ls 2>/dev/null

# /dev/shm 裡不該有可執行檔 ★★★★★
sudo find /dev/shm -xdev -type f -ls 2>/dev/null
```

★★★★★ `/dev/shm`、`/tmp`、`/var/tmp` 是**記憶體或暫存區**，
正常情況下不該有長期存在的執行檔。有的話高度可疑。

```bash
# 找出所有 world-writable 目錄裡的執行檔
sudo find /tmp /var/tmp /dev/shm -xdev -type f -perm -u+x -ls 2>/dev/null

# 找 setuid 檔案（跟基線比對，多出來的就有問題）★★★★★
sudo find / -xdev -perm -4000 -type f -ls 2>/dev/null | sort -k11
```

### IoC 比對法四：程序與網路連線 ★★★★

這一類是**即時**比對 —— 只能看到「現在」，看不到過去。

```bash
# 目前所有連線（含程序名與 PID）
sudo ss -tunap
```

預期輸出（節錄）：

```text
Netid State  Recv-Q Send-Q  Local Address:Port   Peer Address:Port  Process
tcp   ESTAB  0      0       10.10.1.11:47122     203.0.113.45:443   users:(("nginx",pid=2841,fd=12))
tcp   LISTEN 0      511     0.0.0.0:80           0.0.0.0:*          users:(("nginx",pid=1102,fd=6))
```

★★★★★ 第一行就是命中：**本機主動連出到 IoC IP**。

直接用 IoC 清單比對：

```bash
sudo ss -tunap | grep -F -f /var/lib/ioc/2026-09-03-OO框架RCE/ip.txt
```

#### 從連線反查程序、再反查執行檔 ★★★★★

```bash
PID=2841
sudo ls -l /proc/$PID/exe        # 真正的執行檔路徑
sudo ls -l /proc/$PID/cwd        # 工作目錄
sudo tr '\0' ' ' < /proc/$PID/cmdline; echo   # 完整命令列
sudo ls -l /proc/$PID/fd | head -30            # 開了哪些檔
```

預期輸出：

```text
lrwxrwxrwx 1 root root 0 Sep  3 10:22 /proc/2841/exe -> /tmp/.ICE-unix/sshd (deleted)
```

★★★★★ 兩個紅旗同時出現：
1. 程序名稱是 `sshd`，但**執行檔在 `/tmp` 底下**；
2. 標記 `(deleted)` —— 執行檔已經從磁碟刪掉，只活在記憶體裡。
這是後門程式的教科書行為。

★★★★ **程序名稱可以造假，`/proc/<pid>/exe` 不能。** 永遠以後者為準。

```bash
# 一次列出所有程序的真實執行檔路徑，找出不在標準目錄的
sudo ls -l /proc/*/exe 2>/dev/null \
  | grep -vE '/(usr|bin|sbin|lib|opt|snap)/' 
```

```bash
# 程序樹，看誰生出誰 ★★★★
ps auxf | less
```

★★★★★ 看 `nginx` 或 `php-fpm` 底下掛著 `sh`、`bash`、`curl`、`wget`、`python`
—— Web 服務生出 shell 幾乎必然是 webshell 或 RCE 的結果。

```bash
# 直接找這個模式
ps -eo pid,ppid,user,comm,args --forest \
  | grep -E 'nginx|apache2|php-fpm' -A3 | grep -E '\b(sh|bash|curl|wget|python3?|perl|nc)\b'
```

### IoC 比對法五：行為特徵 ★★★★★

情資裡的行為描述通常長這樣：「攻擊者利用漏洞取得 shell 後，
於非上班時段以既有帳號登入，並嘗試存取 `/etc/shadow`」。
這種 IoC 沒有可比對的字串，要靠**條件查詢**。

```bash
# 非上班時段（00:00–06:00）的成功登入
sudo journalctl -u ssh --since "2026-08-01" --no-pager \
  | grep 'Accepted' \
  | awk '{ split($3,t,":"); if (t[1]+0 < 6) print }'
```

```bash
# Debian／Ubuntu 傳統 auth.log（含輪替）
sudo zgrep 'Accepted' /var/log/auth.log* \
  | awk '{ split($3,t,":"); if (t[1]+0 < 6) print $1,$2,$3,$9,$11 }'
```

預期輸出：

```text
Aug 14 03:07:51 deploy 203.0.113.45     ← ★★★★★ 凌晨三點、境外 IP、服務帳號
Aug 20 02:14:03 backup 10.10.1.50
```

```bash
# 服務帳號（不該互動登入的帳號）出現登入紀錄 ★★★★★
sudo zgrep -E 'Accepted .* for (www-data|deploy|backup|nobody|postgres|mysql) ' \
  /var/log/auth.log*
```

```bash
# 大量失敗後緊接著一次成功（暴力破解成功的特徵）★★★★
sudo lastb -F | head -30      # 失敗紀錄
sudo last -F | head -30       # 成功紀錄
```

```bash
# 日誌中的可疑字串（情資常給的行為關鍵字）
sudo zgrep -iE '(base64_decode|eval\(|/bin/sh|wget +http|curl +-o|chmod \+x)' \
  /var/log/nginx/access.log* /var/log/apache2/access.log* 2>/dev/null | head
```

★★★ Web 存取日誌裡出現 `base64_decode`、`eval(` 這類字串，
代表 payload 直接放在 URL 或 query string 裡 —— 這是相當可靠的攻擊指標。

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> 認證日誌路徑不同：
> ```bash
> sudo zgrep 'Accepted' /var/log/secure*
> sudo journalctl -u sshd --since "2026-08-01" --no-pager | grep Accepted
> ```
> RHEL 系預設啟用 `auditd`，可以查到更細的行為：
> ```bash
> sudo ausearch -m USER_LOGIN --start 08/01/2026 -i | head -40
> sudo ausearch -f /etc/shadow -i | head -20
> ```
> ★★★★ `ausearch -f /etc/shadow` 可以直接回答「誰動過 shadow」，
> Ubuntu 上要先 `apt install auditd` 並加規則才有同等能力。

### 整合 IoC 比對腳本 ★★★★★

吃一個 IoC 目錄，跑完所有比對，輸出一份報告。
**唯讀，不改任何東西**，可以安全地在正式機上跑（除了磁碟掃描那段要斟酌）。

```bash
sudo install -d -m 0750 /usr/local/sbin
sudo tee /usr/local/sbin/ioc-scan.sh >/dev/null <<'SCRIPT'
#!/usr/bin/env bash
# ioc-scan.sh —— IoC 比對工具（唯讀）
# 用法：ioc-scan.sh <IoC目錄> [輸出目錄]
# IoC 目錄需包含（可缺）：ip.txt domain.txt hash.txt path.txt keyword.txt
set -uo pipefail

IOCDIR="${1:?用法: $0 <IoC目錄> [輸出目錄]}"
OUTDIR="${2:-/var/lib/ioc/report-$(hostname -s)-$(date +%Y%m%d-%H%M%S)}"
SCAN_DISK="${SCAN_DISK:-1}"      # SCAN_DISK=0 可跳過磁碟雜湊掃描
MAXSIZE="${MAXSIZE:-30M}"

mkdir -p "$OUTDIR"
REPORT="$OUTDIR/report.txt"
HITS=0

log()  { printf '%s\n' "$*" | tee -a "$REPORT"; }
sect() { log ""; log "═══ $* ═══"; }
hit()  { HITS=$((HITS+1)); log "  [!! 命中] $*"; }

have() { [[ -s "$IOCDIR/$1" ]]; }

log "IoC 比對報告"
log "主機      : $(hostname -f 2>/dev/null || hostname)"
log "時間      : $(date -Is)"
log "IoC 來源  : $IOCDIR"
log "執行者    : $(id -un)"
log "核心      : $(uname -a)"

# ── 1. 即時網路連線 ──────────────────────────────────
sect "1. 目前網路連線比對 IP"
if have ip.txt; then
  ss -tunap 2>/dev/null > "$OUTDIR/ss.txt"
  if grep -F -f "$IOCDIR/ip.txt" "$OUTDIR/ss.txt" >> "$REPORT" 2>/dev/null; then
    hit "現行連線中出現 IoC IP（見上方輸出）"
  else
    log "  未命中"
  fi
else
  log "  (略過：無 ip.txt)"
fi

# ── 2. 網路層日誌 ────────────────────────────────────
sect "2. 網路／Web 日誌比對 IP 與網域"
LOGS=(/var/log/nginx/access.log* /var/log/apache2/access.log*
      /var/log/nginx/error.log*  /var/log/apache2/error.log*
      /var/log/fw/*.log*         /var/log/syslog*  /var/log/messages*)
for f in ip.txt domain.txt; do
  have "$f" || continue
  log "  -- 以 $f 比對 --"
  found=0
  for L in "${LOGS[@]}"; do
    [[ -f "$L" ]] || continue
    if [[ "$L" == *.gz ]]; then
      out=$(zgrep -F -f "$IOCDIR/$f" "$L" 2>/dev/null | head -20)
    else
      out=$(grep -F -f "$IOCDIR/$f" "$L" 2>/dev/null | head -20)
    fi
    if [[ -n "$out" ]]; then
      hit "$L"
      printf '%s\n' "$out" >> "$REPORT"
      found=1
    fi
  done
  [[ $found -eq 0 ]] && log "  未命中"
done

# ── 3. journald ──────────────────────────────────────
sect "3. journald 比對 IP 與網域"
if command -v journalctl >/dev/null 2>&1; then
  cat "$IOCDIR"/ip.txt "$IOCDIR"/domain.txt 2>/dev/null > "$OUTDIR/net-ioc.txt"
  if [[ -s "$OUTDIR/net-ioc.txt" ]]; then
    out=$(journalctl --since "-90d" --no-pager 2>/dev/null \
          | grep -F -f "$OUTDIR/net-ioc.txt" | head -30)
    if [[ -n "$out" ]]; then hit "journald"; printf '%s\n' "$out" >> "$REPORT"
    else log "  未命中（涵蓋期間：journald 目前保有的全部紀錄，上限 90 天）"; fi
  fi
fi

# ── 4. 檔案路徑 ──────────────────────────────────────
sect "4. 檔案路徑與檔名比對"
if have path.txt; then
  while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    if [[ "$p" == /* ]]; then
      if [[ -e "$p" ]]; then hit "路徑存在：$p"; ls -la --time-style=full-iso "$p" >> "$REPORT" 2>/dev/null; fi
    else
      out=$(find / -xdev -path "*${p}*" -print 2>/dev/null | head -10)
      if [[ -n "$out" ]]; then hit "比對到路徑片段 $p"; printf '%s\n' "$out" >> "$REPORT"; fi
    fi
  done < "$IOCDIR/path.txt"
  log "  路徑比對完成"
else
  log "  (略過：無 path.txt)"
fi

# ── 5. 檔案雜湊 ──────────────────────────────────────
sect "5. 檔案雜湊掃描（SHA-256，上限 $MAXSIZE）"
if have hash.txt && [[ "$SCAN_DISK" == "1" ]]; then
  log "  掃描中，這一步最耗時…"
  ionice -c3 nice -n 19 find / -xdev -type f -size "-$MAXSIZE" \
      ! -path '/proc/*' ! -path '/sys/*' ! -path '/dev/*' ! -path '/run/*' \
      -print0 2>/dev/null \
    | xargs -0 -r -P 2 -n 200 sha256sum 2>/dev/null > "$OUTDIR/allhash.txt"
  log "  已計算 $(wc -l < "$OUTDIR/allhash.txt") 個檔案的雜湊"
  out=$(grep -F -f "$IOCDIR/hash.txt" "$OUTDIR/allhash.txt")
  if [[ -n "$out" ]]; then hit "檔案雜湊"; printf '%s\n' "$out" >> "$REPORT"
  else log "  未命中"; fi
else
  log "  (略過：無 hash.txt 或 SCAN_DISK=0)"
fi

# ── 6. 行為關鍵字 ────────────────────────────────────
sect "6. 日誌行為關鍵字比對"
if have keyword.txt; then
  for L in /var/log/nginx/access.log* /var/log/apache2/access.log* /var/log/auth.log* /var/log/secure*; do
    [[ -f "$L" ]] || continue
    if [[ "$L" == *.gz ]]; then out=$(zgrep -iF -f "$IOCDIR/keyword.txt" "$L" 2>/dev/null | head -10)
    else out=$(grep -iF -f "$IOCDIR/keyword.txt" "$L" 2>/dev/null | head -10); fi
    if [[ -n "$out" ]]; then hit "$L（關鍵字）"; printf '%s\n' "$out" >> "$REPORT"; fi
  done
  log "  關鍵字比對完成"
else
  log "  (略過：無 keyword.txt)"
fi

# ── 7. 涵蓋範圍聲明（★ 最重要的一段）───────────────
sect "7. 查核涵蓋範圍（回報時必附）"
for L in /var/log/nginx/access.log /var/log/apache2/access.log /var/log/auth.log /var/log/secure; do
  [[ -f "$L" ]] || continue
  oldest=$(ls -1t "${L}"* 2>/dev/null | tail -1)
  log "  $L 系列最舊檔案：$oldest（$(stat -c '%y' "$oldest" 2>/dev/null | cut -d' ' -f1)）"
done
if command -v journalctl >/dev/null 2>&1; then
  log "  journald 最舊紀錄：$(journalctl --no-pager -n1 -o short-iso --reverse 2>/dev/null | tail -1 | cut -d' ' -f1)"
fi

# ── 結論 ─────────────────────────────────────────────
sect "結論"
if [[ $HITS -gt 0 ]]; then
  log "  ★★★★★ 共 $HITS 項命中 —— 請立即停止在本機操作，進入事件應變流程"
else
  log "  於上述涵蓋範圍內未發現命中。注意：這不等於「未受影響」，"
  log "  若涵蓋範圍未包含情資所述攻擊期間，結論應為「無法確認」。"
fi
log ""
log "報告位置：$REPORT"
exit $(( HITS > 0 ? 2 : 0 ))
SCRIPT
sudo chmod 0750 /usr/local/sbin/ioc-scan.sh
```

執行：

```bash
# 完整跑（含磁碟掃描）
sudo /usr/local/sbin/ioc-scan.sh /var/lib/ioc/2026-09-03-OO框架RCE

# 只跑日誌比對，跳過耗時的磁碟掃描
sudo SCAN_DISK=0 /usr/local/sbin/ioc-scan.sh /var/lib/ioc/2026-09-03-OO框架RCE
```

預期輸出（節錄）：

```text
IoC 比對報告
主機      : web01.example.gov.tw
時間      : 2026-09-03T14:21:07+08:00
IoC 來源  : /var/lib/ioc/2026-09-03-OO框架RCE

═══ 1. 目前網路連線比對 IP ═══
  未命中

═══ 2. 網路／Web 日誌比對 IP 與網域 ═══
  -- 以 ip.txt 比對 --
  [!! 命中] /var/log/nginx/access.log.3.gz
203.0.113.45 - - [14/Aug/2026:03:12:51 +0800] "POST /api/v1/render HTTP/1.1" 200 41 "-" "python-requests/2.31.0"
...
═══ 結論 ═══
  ★★★★★ 共 2 項命中 —— 請立即停止在本機操作，進入事件應變流程
```

★★★★ 離開碼設計成 `2 = 有命中`、`0 = 無命中`，方便用組態管理工具批次派工後彙整結果。

★★★★★ **這支腳本刻意只讀不寫**（除了寫報告到 `$OUTDIR`）。
它不刪檔、不殺程序、不改設定 —— 因為在還沒確認之前，任何寫入都可能是破壞證據。

#### 多台主機批次執行 ★★★★

```bash
# 用 Ansible ad-hoc 派工（假設已有 inventory）
ansible web -b -m copy -a "src=/var/lib/ioc/2026-09-03-OO框架RCE dest=/var/lib/ioc/ mode=0750"
ansible web -b -m script -a "/usr/local/sbin/ioc-scan.sh /var/lib/ioc/2026-09-03-OO框架RCE" \
  | tee /tmp/ioc-all.txt

# 挑出有命中的主機
grep -B5 '命中' /tmp/ioc-all.txt | grep -oE '^[a-z0-9.-]+ \|' | sort -u
```

有 Wazuh 的話更直接：把 IoC 做成 CDB list 或 rootcheck 規則，
由 agent 自己比對並回報，見 [[090-08-00-idx-Wazuh資安監控]]。

### 「無法確認」怎麼辦 ★★★★★

這是機關最常見的結論，也是最該正視的結論。

| 造成無法確認的原因 | 短期補救 | 長期修正 |
| --- | --- | --- |
| **日誌保存期不夠** ★★★★★ | 找備份裡有沒有舊日誌；找上游設備（防火牆、Proxy）是否留更久 | 拉長保存期，見 [[100-01-02-guide-日誌-日誌集中與輪替]] |
| **沒有集中日誌** ★★★★★ | 逐台登入查（很痛苦但做得到） | 建立集中日誌，見 [[090-05-09-guide-資安設備-日誌集中與SIEM]] |
| **DNS 查詢沒記錄** ★★★★ | 從現在開始開啟並觀察 | 對外 forwarder 開 query log 並集中 |
| **資產清冊不全** ★★★★★ | 用網段掃描 + 服務指紋暫時補 | [[100-02-13-guide-維運-資產與授權管理]] |
| **主機已重灌／已重開機** ★★★★★ | 幾乎救不回來 | **教育：不要急著重灌**，見 [[090-07-15-guide-資安實踐-被入侵主機的跡證檢查]] |
| **沒有檔案完整性基線** ★★★★ | 用套件驗證（`debsums`／`rpm -Va`）替代 | 部署 AIDE／Wazuh FIM |
| **委外系統看不到日誌** ★★★★ | 正式行文請廠商協助查核 | 契約納入日誌提供義務，見 [[090-07-11-guide-資安實踐-委外與供應鏈資安]] |

> [!danger] ★★★★★ 絕對不要把「無法確認」寫成「未受影響」
> 這是實務上最嚴重的錯誤。理由：
> 1. **對外**：如果之後真的爆出來，回報不實會比原本的事件更嚴重。
> 2. **對內**：寫「未受影響」就沒有人會去修日誌保存期的問題，同樣的洞會一再發生。
>
> 誠實寫「無法確認，因日誌保存期僅 30 天」反而是最有力的改善預算理由。

快速自我檢查：**你的日誌涵蓋期間夠嗎？**

```bash
# 各主要日誌最舊到什麼時候
for f in /var/log/auth.log /var/log/syslog /var/log/nginx/access.log; do
  oldest=$(ls -1t "$f"* 2>/dev/null | tail -1)
  [[ -n "$oldest" ]] && echo "$f -> $oldest ($(stat -c '%y' "$oldest" | cut -d' ' -f1))"
done
```

```bash
# journald 實際保有的最早時間與佔用空間
journalctl --no-pager | head -1
journalctl --disk-usage
```

預期輸出：

```text
-- Journal begins at Tue 2026-08-05 09:11:23 CST, ends at Wed 2026-09-03 14:20:55 CST. --
Archived and active journals take up 412.3M in the file system.
```

★★★★★ 這行 `Journal begins at` 就是你**能證明的最早日期**。
情資說攻擊從 6 月開始，而你的日誌從 8 月才有 —— 結論就只能是「無法確認」。

### 平時該準備什麼 ★★★★★

> [!danger] 情資來的時候才開始準備就來不及了
> 上面每一個「無法確認」的原因，都是**平時沒做**造成的。
> 情資單只給你幾天時間，而日誌保存期是無法回溯補救的。

| 準備項目 | 為什麼 | 檢驗方式 |
| --- | --- | --- |
| **資產清冊** ★★★★★ | 沒有它就答不出「我們有沒有」 | 隨機抽一台主機，看清冊上有沒有、資料對不對 |
| **軟體版本清單（含語言層套件）** ★★★★★ | 情資都是按版本範圍給的 | 能在 5 分鐘內產出「哪幾台裝了 X」 |
| **集中日誌 + 足夠的保存期** ★★★★★ | 唯一能回答「過去有沒有發生」的東西 | `journalctl --no-pager \| head -1` 看得到幾個月前 |
| **DNS 查詢日誌** ★★★★ | 連線被擋也留得下痕跡 | 隨便查一個網域，看日誌有沒有出現 |
| **檔案完整性基線** ★★★★ | 才知道什麼是「多出來的」 | 有 AIDE／Wazuh FIM 資料庫且有定期更新 |
| **全機雜湊基線** ★★★ | 新情資可直接比對，不必再掃磁碟 | `/var/lib/ioc/allhash.txt` 有在更新 |
| **情資訂閱清單** ★★★★ | 讓你比公文早幾天知道 | 訂閱來源跟資產清冊上的產品對得起來 |
| **一份寫好的比對腳本** ★★★★ | 情資來的當天就能跑 | 每季演練跑一次，見 [[090-07-17-guide-資安實踐-演練設計與演練紀錄]] |
| **上一次的處理紀錄** ★★★ | 下次照抄，不必從頭想 | 情資登記表有連續紀錄 |

### 回報 ★★★★

> [!warning] ★★★★★ 格式、期限、對象一律依來文所載
> 本手冊**不列**任何表單名稱、通報系統名稱或天數 —— 那些會隨規定改版，
> 寫死在手冊裡只會誤導。收到來文的第一件事就是把這三項抄進登記表。

回報內容不論用什麼表單，實質上要說清楚這六件事：

| # | 要說明的 | 範例寫法 |
| --- | --- | --- |
| ① | **是否適用** | 「本機關有 2 台主機使用該產品，版本 6.3.8，落在受影響範圍。」★★★★★ |
| ② | **查核了什麼** | 「比對防火牆日誌、Nginx 存取日誌、主機檔案雜湊。」★★★★ |
| ③ | **涵蓋期間** | 「防火牆日誌 2026-07-01 起、Web 日誌 2026-08-05 起。」★★★★★ |
| ④ | **結論** | 「於上述期間內未發現命中；該期間之前無法確認。」★★★★★ |
| ⑤ | **已採取的處置** | 「已於 9/4 升級至 6.4.6；已於邊界封鎖所列 3 個 IP。」★★★★ |
| ⑥ | **後續改善** | 「將日誌保存期由 30 天延長至 180 天，預計 10 月完成。」★★★ |

★★★★ ③ 是最多人漏掉、也最重要的一項 —— **沒有涵蓋期間的「未發現」等於沒有結論**。

---

## 完整實戰範例

> [!example] 情境
> 2026-09-03 下午，收到主管機關轉發之資安情資（以下**內容為教學虛構**，
> 產品名稱、CVE 與 IoC 均為範例，僅用於示範流程）。
> 機關環境：3 台對外 Web（web01～web03）、1 台 Juniper SRX 邊界防火牆、
> 已有 rsyslog 集中但只有防火牆送過去、Web 日誌留在各機本地。

### 收到的情資單（虛構範例）

```text
────────────────────────────────────────────────
主旨：OO-Framework 遠端程式碼執行漏洞（CVE-2026-XXXXX）情資通告

一、受影響產品與版本
    OO-Framework 6.0.0 ≦ 版本 < 6.4.2
    受影響元件：範本渲染模組（/api/v1/render 端點）

二、漏洞資訊
    CVE-2026-XXXXX，CVSS v3.1 9.8（Critical）
    無須認證、可遠端觸發，已有實際攻擊案例，
    觀測到之最早攻擊時間為 2026-06-18。

三、入侵指標（IoC）
    C2 IP：203.0.113.45 / 198.51.100.77 / 192.0.2.201
    C2 網域：cdn-update.example.net / sync.badhost.example
    Webshell SHA-256：
      a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90
    落地路徑：<網站根目錄>/uploads/x.php、/tmp/.ICE-unix/sshd
    行為特徵：Web 服務行程直接產生 /bin/sh 子行程；
              成功利用後以既有帳號於非上班時段登入。

四、建議處置
    升級至 6.4.6 以上；無法立即升級者，於 WAF 阻擋 /api/v1/render
    之 POST 請求，並封鎖上列 IP。

五、回報要求
    請於期限前依指定格式回報是否受影響及處置情形。
────────────────────────────────────────────────
```

### 步驟 0：登記（14:05，收到後 10 分鐘）

```bash
sudo install -d -m 0750 /var/lib/ioc/2026-09-03-OO框架RCE
cd /var/lib/ioc/2026-09-03-OO框架RCE
```

填好登記表，抄下期限與負責人。通知資訊主管：「有一則 Critical 情資，正在評估適用性。」

### 步驟 1：判斷適用性（14:10～14:35）

先查資產清冊：

```bash
grep -i "OO-Framework" /srv/資產/資產清冊.csv
```

```text
web01,10.10.1.11,對外官網,Ubuntu 24.04,OO-Framework,6.3.8,是
web02,10.10.1.12,線上表單,Ubuntu 24.04,OO-Framework,6.4.5,是
```

★★★★ 清冊上只有兩台，但機關有三台對外 Web —— **web03 沒有登記**。
不能假設它沒裝，直接上機驗：

```bash
for h in web01 web02 web03; do
  echo "=== $h ==="
  ssh "$h" 'grep -m1 VERSION /opt/ooframework/VERSION 2>/dev/null || echo "未安裝"'
done
```

預期輸出：

```text
=== web01 ===
VERSION=6.3.8
=== web02 ===
VERSION=6.4.5
=== web03 ===
VERSION=6.1.2
```

★★★★★ **web03 也裝了，而且版本 6.1.2 更舊。** 清冊漏了一台 ——
這件事本身就要列入改善事項。

適用性結論：

| 主機 | 版本 | 受影響 | 對外 | 優先序 |
| --- | --- | --- | --- | --- |
| web01 | 6.3.8 | **是** | 是 | ★★★★★ 最高 |
| web02 | 6.4.5 | 否 | 是 | 低（仍掃 IP 類 IoC） |
| web03 | 6.1.2 | **是** | 是 | ★★★★★ 最高 |

14:35 回報主管：**適用，兩台受影響，開始比對。**

### 步驟 2：整理 IoC（14:35～14:45）

```bash
cd /var/lib/ioc/2026-09-03-OO框架RCE

cat > ip.txt <<'EOF'
203.0.113.45
198.51.100.77
192.0.2.201
EOF

cat > domain.txt <<'EOF'
cdn-update.example.net
sync.badhost.example
EOF

cat > hash.txt <<'EOF'
a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90
EOF

cat > path.txt <<'EOF'
uploads/x.php
/tmp/.ICE-unix/sshd
EOF

cat > keyword.txt <<'EOF'
/api/v1/render
EOF

# 清洗
sed -i 's/\xEF\xBB\xBF//; s/\r$//; s/^[[:space:]]*//; s/[[:space:]]*$//' *.txt
sed -i '/^$/d' *.txt
wc -l *.txt
```

預期輸出：

```text
  2 domain.txt
  1 hash.txt
  3 ip.txt
  1 keyword.txt
  2 path.txt
  9 total
```

### 步驟 3：先查涵蓋面最大的 —— 防火牆日誌（14:45～15:10）

集中日誌上一次比對三台的所有對外連線：

```bash
sudo zgrep -F -f /var/lib/ioc/2026-09-03-OO框架RCE/ip.txt /var/log/fw/*.log*
```

預期輸出：

```text
/var/log/fw/2026-08-14.log.gz:Aug 14 03:12:44 fw01 filterlog: 
  pass,in,ge-0/0/0,tcp,203.0.113.45,50122,10.10.1.11,443,SYN
/var/log/fw/2026-08-14.log.gz:Aug 14 03:19:07 fw01 filterlog: 
  pass,out,ge-0/0/0,tcp,10.10.1.11,49233,198.51.100.77,443,SYN
```

★★★★★ **第二行是關鍵**：`10.10.1.11`（web01）**主動連出**到 C2 IP。
這不是被掃描，這是已經被控制了。

同時確認防火牆日誌涵蓋期間：

```bash
ls -1t /var/log/fw/ | tail -3
```

```text
2026-07-02.log.gz
2026-07-01.log.gz
2026-06-30.log.gz
```

★★★ 涵蓋到 6/30，但情資說攻擊自 6/18 起 —— **6/18～6/29 這段仍是無法確認**。

### 步驟 4：停手，隔離 web01（15:10）

> [!danger] ★★★★★ 這一刻起，web01 是現場，不是主機
> - **不要重開機**、**不要重灌**、**不要跑全機 `find`**
> - 先把它從網路上拿掉，但**保持開機**

```bash
# 在防火牆上阻斷 web01 的對外流量（保留管理網段可達）
# JunOS：
#   set security policies from-zone trust to-zone untrust policy block-web01 \
#       match source-address web01 destination-address any application any
#   set security policies ... then deny
#   commit
```

接著照 [[090-07-15-guide-資安實踐-被入侵主機的跡證檢查]] 的順序收集揮發性證據。
本篇只示範 IoC 比對的部分：

```bash
# 在 web01 上（唯讀）
sudo ss -tunap | grep -F -f /var/lib/ioc/2026-09-03-OO框架RCE/ip.txt
```

```text
tcp ESTAB 0 0 10.10.1.11:49233 198.51.100.77:443 users:(("sshd",pid=31882,fd=3))
```

```bash
sudo ls -l /proc/31882/exe
```

```text
lrwxrwxrwx 1 root root 0 Sep  3 15:12 /proc/31882/exe -> /tmp/.ICE-unix/sshd (deleted)
```

★★★★★ 兩個 IoC 同時命中：C2 IP + 落地路徑，而且執行檔已被刪除。**確認入侵。**

```bash
# webshell 是否還在
sudo ls -la /var/www/html/uploads/x.php
sudo sha256sum /var/www/html/uploads/x.php
```

```text
-rw-r--r-- 1 www-data www-data 2841 Jun 18 21:47 /var/www/html/uploads/x.php
a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90  /var/www/html/uploads/x.php
```

★★★★★ 雜湊完全吻合，且 mtime 是 **6/18 21:47** —— 跟情資所述最早攻擊時間吻合，
表示 web01 至少被控制了 **77 天**。

### 步驟 5：擴大比對 web02、web03（15:30～16:40）

web01 已隔離交由後續處理，現在要回答「**還有哪幾台中了**」。

```bash
# web02（版本不受影響，但仍掃 IP／路徑類 IoC）
ssh web02 'sudo SCAN_DISK=0 /usr/local/sbin/ioc-scan.sh /var/lib/ioc/2026-09-03-OO框架RCE'
```

```text
═══ 結論 ═══
  於上述涵蓋範圍內未發現命中。
```

```bash
# web03（版本受影響，完整掃描）
ssh web03 'sudo /usr/local/sbin/ioc-scan.sh /var/lib/ioc/2026-09-03-OO框架RCE'
```

```text
═══ 2. 網路／Web 日誌比對 IP 與網域 ═══
  -- 以 ip.txt 比對 --
  [!! 命中] /var/log/nginx/access.log.5.gz
203.0.113.45 - - [18/Jun/2026:21:44:02 +0800] "POST /api/v1/render HTTP/1.1" 500 178 "-" "python-requests/2.31.0"
203.0.113.45 - - [18/Jun/2026:21:44:19 +0800] "POST /api/v1/render HTTP/1.1" 500 178 "-" "python-requests/2.31.0"
  未命中（path.txt / hash.txt）
═══ 結論 ═══
  ★★★★★ 共 1 項命中
```

★★★★ 判讀關鍵：**web03 被嘗試攻擊，但回應碼是 `500` 不是 `200`**，
而且沒有落地檔案、沒有 C2 連線。合理推論是**攻擊失敗**（版本雖在範圍內，
但可能因設定不同而未成功）。

★★★★★ 但**不能就這樣結案** —— 500 也可能是攻擊過程中的中間狀態。
要再確認兩件事：

```bash
# ① web03 有沒有 Web 服務生出 shell 的痕跡
ssh web03 "sudo zgrep -iE '(sh|bash|curl|wget) ' /var/log/nginx/error.log* | head"
# ② web03 有沒有非上班時段的登入
ssh web03 "sudo zgrep 'Accepted' /var/log/auth.log* | awk '{split(\$3,t,\":\"); if(t[1]+0<6) print}'"
```

兩者皆無輸出 → 判定 web03 **遭嘗試攻擊但未成功**。

### 步驟 6：判定影響（16:40）

| 主機 | 適用 | 比對結果 | 涵蓋期間 | 結論 |
| --- | --- | --- | --- | --- |
| web01 | 是 | C2 連線 + webshell + 後門程序，全部命中 | 防火牆 6/30 起、Web 日誌 8/5 起 | ★★★★★ **確認遭入侵**，至少自 6/18 |
| web02 | 否（版本不符） | 無命中 | 同上 | ★★★ 未發現受影響 |
| web03 | 是 | 僅有攻擊嘗試（HTTP 500），無落地、無 C2 | 同上 | ★★★★ 遭嘗試攻擊但未成功；**6/18 前無法確認** |

### 步驟 7：處置與回報（16:40～）

處置：

```bash
# 1) web01：維持隔離、保持開機、等待證據保全（不做任何清除）
# 2) web02、web03：升級到 6.4.6
ssh web03 'sudo systemctl stop nginx && sudo /opt/ooframework/upgrade.sh 6.4.6'

# 3) 邊界封鎖三個 C2 IP（JunOS）
#    set security zones security-zone untrust address-book address ioc1 203.0.113.45
#    ...
#    set security policies from-zone trust to-zone untrust policy block-ioc then deny
#    commit confirmed 5

# 4) 全部主機的 sinkhole：避免 DNS 解析到 C2 網域
printf '0.0.0.0 cdn-update.example.net\n0.0.0.0 sync.badhost.example\n' \
  | sudo tee -a /etc/hosts
```

★★★ `commit confirmed 5` ＝ 5 分鐘內沒有再次 `commit` 就自動回退，
避免把自己的管理連線鎖在外面。

回報內容（實質六項，格式依來文）：

> ① **適用性**：本機關 3 台對外 Web 主機中，2 台（web01、web03）之
>    OO-Framework 版本落在受影響範圍。
> ② **查核範圍**：邊界防火牆日誌、各主機 Nginx 存取／錯誤日誌、
>    系統認證日誌、全機檔案 SHA-256 掃描、即時程序與網路連線。
> ③ **涵蓋期間**：防火牆日誌 2026-06-30 起，Web 與系統日誌 2026-08-05 起。
> ④ **結論**：web01 **確認遭入侵**，於 2026-06-18 落地 webshell（雜湊與情資相符），
>    並持續與 C2 通聯；web03 遭嘗試攻擊但未發現成功跡象，
>    惟 2026-06-18 前之日誌已逾保存期，**該期間無法確認**；web02 未受影響。
> ⑤ **已採處置**：web01 已於 15:10 網路隔離並保持開機以保全證據，
>    另案依事件應變流程辦理；web02、web03 已升級至 6.4.6；
>    邊界已封鎖情資所列 3 個 IP 與 2 個網域。
> ⑥ **後續改善**：(a) 資產清冊漏登 web03，已補正並訂每季盤點；
>    (b) Web 與系統日誌保存期由 30 天延長至 180 天並納入集中日誌；
>    (c) 開啟 DNS 查詢日誌。

★★★★★ 注意 ④ 同時包含「確認」「未發現」「無法確認」三種結論 ——
**這才是一份誠實的回報**。

### 步驟 8：歸檔（隔日）

```bash
cd /var/lib/ioc
sudo tar -czf 2026-09-03-OO框架RCE.tar.gz 2026-09-03-OO框架RCE/
sudo sha256sum 2026-09-03-OO框架RCE.tar.gz | sudo tee 2026-09-03-OO框架RCE.tar.gz.sha256
```

★★★★ 連同回報公文一起歸檔，下次稽核或健診時就是現成的佐證。

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| `grep -F -f ip.txt` 完全比不到，但肉眼看得到 IP ★★★★★ | IoC 檔從 PDF 貼過來，含 BOM／CR／全形空白 | 用 `cat -A` 檢查；`sed -i 's/\xEF\xBB\xBF//; s/\r$//'` 清洗 |
| `grep: ip.txt: No such file or directory` | 相對路徑，但已經 `cd` 到別處 | 一律用絕對路徑，或先 `cd "$IOCDIR"` |
| 雜湊比對永遠不中，檔案明明在 ★★★★ | 情資給的是大寫雜湊，`sha256sum` 輸出小寫 | `tr 'A-Z' 'a-z' < hash.txt` 統一小寫，或改用 `grep -iF` |
| `find /` 跑了三小時還沒結束 ★★★★★ | 沒加 `-xdev`，掃到 NFS／CIFS 掛載 | 加 `-xdev`；`findmnt -t nfs4,cifs` 先確認有哪些網路掛載 |
| 掃描期間網站變超慢、負載飆高 ★★★★ | `sha256sum` 吃滿 I/O | 前置 `ionice -c3 nice -n 19`；`-P` 降到 1；改在離峰執行 |
| `xargs: argument line too long` | 檔案數太多，一次帶太多參數 | 加 `-n 200` 限制每批數量 |
| `sha256sum: '...': No such file or directory`（檔名含空白） | 用了 `find ... \| xargs` 而沒用 NUL 分隔 | 改成 `find -print0 \| xargs -0` |
| `zgrep` 對 `.log.1`（未壓縮）檔沒反應 ★★★ | 輪替後第一個檔通常未壓縮，`zgrep` 仍可處理但萬用字元展開順序可能漏 | 用 `for L in /var/log/x*; do ...` 逐檔判斷副檔名 |
| `journalctl --since` 查不到兩個月前的紀錄 ★★★★★ | journald 已依 `SystemMaxUse` 輪替刪除 | 這就是「無法確認」；長期解：調高保存並集中收容 |
| `ss -tunap` 沒顯示 Process 欄 ★★★ | 沒有用 `sudo`，看不到別的使用者的行程 | 一律 `sudo ss -tunap` |
| `/proc/<pid>/exe` 顯示 `Permission denied` | 非 root 且非該行程擁有者 | `sudo ls -l /proc/<pid>/exe` |
| `nft add rule` 回 `Error: Could not process rule: No such file or directory` ★★★ | `inet filter` 這個 table／chain 不存在 | 先 `sudo nft list tables` 確認實際的 table 名稱 |
| `rndc querylog on` 回 `connection refused` | BIND 的 `rndc` 金鑰或 controls 未設定 | 檢查 `/etc/bind/rndc.key` 與 `named.conf` 的 `controls` 區段 |
| `debsums` 大量回報 `MISSING`／`FAILED` 但機器沒事 ★★★ | 設定檔本來就會被改；有些套件沒附 md5sums | 用 `debsums -c -e` 排除設定檔；`debsums -l` 看哪些套件沒有校驗資料 |
| 比對腳本在某台主機上直接結束、沒有輸出 | `set -e` 遇到 `grep` 無命中（離開碼 1）就中止 | 腳本用 `set -uo pipefail`（**不加 `-e`**），或在 grep 後加 `|| true` |
| Ansible 派工回報 `non-zero return code` ★★★ | 腳本刻意用離開碼 2 表示「有命中」 | 加 `ignore_errors: true` 或 `failed_when: rc not in [0,2]` |
| 明明封鎖了 C2 IP，連線還是出得去 ★★★★ | 規則加在錯的 chain／zone，或已建立的 session 未被清掉 | 確認規則方向（out/forward）；JunOS 上 `clear security flow session destination-prefix <ip>` |
| 回報後被追問「你怎麼知道沒有」答不出來 ★★★★★ | 沒有保留比對過程與涵蓋期間 | 用腳本產出 report.txt 並歸檔，回報時附上涵蓋期間 |

---

## 安全性注意事項

> [!danger] ★★★★★ 命中之後不要「順手清掉」
> 看到 webshell 就 `rm`、看到可疑程序就 `kill` —— 這是最自然的反應，也是最糟的處置。
> 後果：
> 1. 你**再也查不出**攻擊者進來多久、拿了什麼、還去了哪幾台。
> 2. 攻擊者通常留有多個後門，刪掉一個他會從另一個回來，而你已經沒有線索了。
> 3. 若涉及個資外洩，你毀掉的是**法律責任認定的依據**。
>
> 正確動作：**隔離網路、保持開機、保全證據**，
> 然後照 [[090-07-04-guide-資安實踐-資安事件應變流程]] 走。

> [!warning] ★★★★ IoC 清單本身是敏感資料
> 情資單常標有分發限制。不要把 IoC 貼到公開的線上分析平台、
> 不要上傳可疑檔案到公開的多引擎掃描服務 —— 那等同於公開揭露
> 「某機關正在調查這個攻擊」，可能讓攻擊者知道自己被發現了。
> 需要外部分析時，走正式管道請求協助。

| 注意事項 | 說明 |
| --- | --- |
| **比對腳本必須唯讀** ★★★★★ | 任何寫入、刪除、重啟都可能破壞證據或觸發攻擊者的清除機制 |
| **不要在可疑主機上安裝新套件** ★★★★★ | `apt install` 會改動大量檔案時間戳，也可能需要對外連線 |
| **收集用的工具從外部帶進去** ★★★★ | 被入侵主機上的 `ls`、`ps`、`netstat` 可能已被替換（rootkit） |
| **IoC 檔案權限** ★★★ | `/var/lib/ioc` 設 `0750` 且屬 root，避免一般使用者看到情資內容 |
| **封鎖 IoC IP 前先確認不是共用基礎設施** ★★★★ | C2 有時架在大型雲端或 CDN 上，整段封鎖會誤傷正常服務 |
| **sinkhole 網域要小心** ★★★ | 改 `/etc/hosts` 只影響單機；DNS 層 sinkhole 才有全機關效果，但要留意內部服務誤中 |
| **報告與截圖不要外流** ★★★★ | 報告內含內部 IP、主機名、路徑，屬機關敏感資訊 |
| **不要用正式帳號登入可疑主機** ★★★★ | 主機上可能有鍵盤側錄或憑證竊取；用專用的調查帳號，事後停用 |
| **調查結束後撤掉臨時規則** ★★★ | 臨時的 tcpdump、querylog、log 規則會持續吃磁碟，要有收尾清單 |
| **不要在事件未明時對外說明細節** ★★★★ | 對外說明由指定窗口統一處理，見 [[090-07-04-guide-資安實踐-資安事件應變流程]] |

---

## 速查表

### 四步流程

| 步驟 | 做什麼 | 靠什麼 |
| --- | --- | --- |
| 0 | 登記、抄下期限與負責人 | 情資登記表 |
| 1 | 判斷適用性 | ★★★★★ 資產清冊 |
| 2 | 比對 IoC | 集中日誌 → 主機日誌 → 即時狀態 → 磁碟 |
| 3 | 判定影響（有命中／無命中／**無法確認**） | 涵蓋期間 |
| 4 | 處置與回報 | 依來文格式，實質六項 |

### 情資單五塊

| ① 受影響產品與版本 | ② 漏洞資訊 | ③ IoC 清單 | ④ 建議處置 | ⑤ 回報要求 |
| --- | --- | --- | --- | --- |
| 對資產清冊 | 決定優先序 | 拿去比對 | 排修補 | 照來文辦 |

### 適用性查詢

| 目的 | 指令 |
| --- | --- |
| Debian 套件版本 | `dpkg-query -W -f='${Package} ${Version}\n' <pkg>` |
| RHEL 套件版本 | `rpm -q --qf '%{NAME} %{VERSION}-%{RELEASE}\n' <pkg>` |
| PHP 套件 | `composer show \| grep -i <pkg>` |
| 為什麼裝了某套件 | `composer why <pkg>` |
| Node 套件（含間接） | `npm ls <pkg>` |
| Python 套件 | `pip list \| grep -i <pkg>` |

### IoC 比對指令

| IoC 類型 | 指令 |
| --- | --- |
| IP（日誌，含壓縮） | `sudo zgrep -F -f ip.txt /var/log/nginx/access.log*` |
| IP（journald） | `sudo journalctl --since -90d --no-pager \| grep -F -f ip.txt` |
| IP（即時連線） ★★★★★ | `sudo ss -tunap \| grep -F -f ip.txt` |
| 網域（BIND） | `sudo rndc querylog on` 後查 `/var/log/named/query.log` |
| 雜湊（單檔） | `sha256sum <file>` |
| 雜湊（全機） ★★★★★ | `find / -xdev -type f -size -30M -print0 \| xargs -0 -P2 -n200 sha256sum` |
| 路徑片段 | `sudo find / -xdev -path '*uploads*' -name '*.php' -ls` |
| 隱藏檔 | `sudo find /tmp /var/tmp /dev/shm -xdev -name '.*' -ls` |
| setuid 檔 | `sudo find / -xdev -perm -4000 -type f -ls` |
| 程序真實路徑 ★★★★★ | `sudo ls -l /proc/<pid>/exe` |
| 程序樹 | `ps auxf` |
| 非上班時段登入 | `sudo zgrep Accepted /var/log/auth.log* \| awk '{split($3,t,":"); if(t[1]+0<6) print}'` |
| 登入失敗紀錄 | `sudo lastb -F \| head -30` |

### `find` 全機掃描必加的參數

| 參數 | 作用 |
| --- | --- |
| `-xdev` ★★★★★ | 不跨掛載點（避開 NFS） |
| `-size -30M` ★★★★ | 只算小檔 |
| `! -path '/proc/*'` ★★★★ | 排除虛擬檔案系統 |
| `-print0` + `xargs -0` ★★★★ | 處理含空白的檔名 |
| `ionice -c3 nice -n 19` ★★★★ | 不拖垮正式服務 |

### 涵蓋期間怎麼查

| 目標 | 指令 |
| --- | --- |
| journald 最早紀錄 ★★★★★ | `journalctl --no-pager \| head -1` |
| journald 佔用空間 | `journalctl --disk-usage` |
| 某日誌最舊的輪替檔 | `ls -1t /var/log/auth.log* \| tail -1` |
| 該檔日期 | `stat -c '%y' <file>` |

### 三種結論

| 結論 | 條件 | 動作 |
| --- | --- | --- |
| 有命中 ★★★★★ | 找到明確痕跡 | 停手 → 隔離但不關機 → 事件應變 |
| 無命中 ★★★ | 涵蓋範圍內查過 | 回報並**註明涵蓋期間** |
| 無法確認 ★★★★★ | 日誌不足／清冊不全 | **誠實回報** + 列改善事項 |

### 回報實質六項

① 是否適用 ② 查核了什麼 ③ **涵蓋期間** ④ 結論 ⑤ 已採處置 ⑥ 後續改善

### 平時準備（缺一項就多一個「無法確認」）

資產清冊 ★★★★★ ／ 軟體版本清單 ★★★★★ ／ 集中日誌與足夠保存期 ★★★★★
／ DNS 查詢日誌 ★★★★ ／ 檔案完整性基線 ★★★★ ／ 全機雜湊基線 ★★★
／ 情資訂閱清單 ★★★★ ／ 寫好的比對腳本 ★★★★

### 一句話

> ★★★★★ **「查不到」不是「沒有」。回報時一定要寫出涵蓋期間。**

---

## 練習題

1. **（適用性）** 在你手上任一台伺服器，用三種方式列出「所有已安裝的 Web 相關套件與版本」
   （系統套件、語言層套件、自行部署的應用），並判斷若情資說
   「Nginx < 1.24.0 受影響」，你能在幾分鐘內回答？

2. **（IoC 清洗）** 從任一份 PDF 或網頁複製 5 個 IP 貼進 `ip.txt`，
   先用 `grep -F -f ip.txt` 對一份自製的測試日誌比對（故意讓其中兩個會命中），
   若比不到，用 `cat -A` 找出原因並修正。

3. **（涵蓋期間）** 在你負責的三台主機上，分別查出
   `auth.log`、`nginx/access.log`、`journald` 的**最早紀錄日期**，
   做成一張表。若今天收到一份情資說「攻擊自 90 天前開始」，
   這三台各自能給出什麼結論？

4. **（磁碟掃描）** 對一台測試機執行全機 SHA-256 掃描，
   分別測「有 `-xdev`」與「沒有 `-xdev`」、「有 `ionice`」與「沒有」的耗時與負載差異，
   記錄下來。

5. **（腳本）** 部署本篇的 `ioc-scan.sh`，自己在 `/tmp/.ICE-unix/` 下放一個空檔案
   當作假的 IoC，確認腳本抓得到並回傳離開碼 2。**測完記得刪除測試檔。**

6. **（回報）** 針對第 3 題的結果，用「回報實質六項」寫出一段 200 字以內的回報文字，
   要包含「無法確認」的正確表述。

> [!question]- 練習題參考答案
>
> **1.** 三種方式：`dpkg -l \| grep -i nginx`（系統套件）、
> `composer show`／`npm ls --depth=0`（語言層）、
> 應用自己的 `VERSION` 檔或管理介面。
> ★★★★ 如果超過 5 分鐘才答得出來，代表需要一份預先產好的軟體清單 ——
> 這正是 [[100-02-13-guide-維運-資產與授權管理]] 要解決的問題。
>
> **2.** 最常見原因：從 PDF 複製帶了不可見字元。`cat -A ip.txt` 會看到
> `203.0.113.45M-BM- $` 之類的痕跡（`M-BM-` 是全形空白 U+00A0）。
> 修法：`sed -i 's/\xC2\xA0//g; s/\r$//; s/[[:space:]]*$//' ip.txt`。
>
> **3.** 用 `journalctl --no-pager | head -1` 與 `ls -1t <log>* | tail -1` +
> `stat -c '%y'`。若最早紀錄晚於 90 天前，結論只能是「**該期間無法確認**」，
> **不能**寫「未受影響」。
>
> **4.** 典型結果：沒有 `-xdev` 且掛了網路儲存時，耗時可能相差 10 倍以上；
> 加 `ionice -c3` 後掃描時間變長，但 `uptime` 的 load average 明顯較低、
> 服務回應時間不受影響。★★★★ 正式機一律加。
>
> **5.** 預期看到 `[!! 命中] 路徑存在：/tmp/.ICE-unix/sshd`，
> `echo $?` 回傳 `2`。★★★ 這個測試同時驗證了腳本可用與你的
> `path.txt` 格式正確。
>
> **6.** 範例：「本機關經查有 3 台主機使用該產品，其中 2 台版本落在受影響範圍。
> 已比對邊界防火牆日誌（2026-06-30 起）、Web 存取日誌（2026-08-05 起）
> 及主機檔案雜湊。於上述期間內未發現與所列 IoC 相符之跡象；
> 惟情資所述攻擊起始時間早於本機關日誌保存期間，該期間之前無法確認。
> 已完成版本升級並於邊界封鎖所列 IP，另將日誌保存期延長至 180 天。」
> ★★★★★ 關鍵在同時寫出「查了什麼」「涵蓋到哪」「哪一段確認不了」。

---

## 小測驗

**Q1.** 收到情資單後的第一步應該是下列何者？
　(A) 立刻用 IoC 掃描所有主機
　(B) 判斷這個產品與版本我們有沒有
　(C) 先升級所有軟體
　(D) 先回報「經查未受影響」

**Q2.** （是非）檔案雜湊比對沒有命中，就可以確定這台主機沒有被植入該惡意程式。

**Q3.** 下面這行指令有什麼嚴重問題？
```bash
find / -type f -exec sha256sum {} \;
```

**Q4.** 「無命中」與「無法確認」的差別是什麼？為什麼把後者寫成前者很危險？

**Q5.** `ss -tunap` 顯示某程序名稱為 `sshd`，但 `ls -l /proc/<pid>/exe` 顯示
`-> /tmp/.ICE-unix/sshd (deleted)`。請說明這兩個資訊各代表什麼，該相信哪一個。

**Q6.** （選擇）在 IoC 金字塔中，下列何者對攻擊者而言最難改變、對防守方最耐用？
　(A) IP 位址　(B) 檔案 MD5　(C) 網域名稱　(D) TTP（行為手法）

**Q7.** 為什麼即使連線已被防火牆阻擋，**DNS 查詢紀錄**仍然是有價值的 IoC 來源？

**Q8.** 全機檔案雜湊掃描時，`-xdev` 這個參數解決了什麼問題？不加會怎樣？

**Q9.** （是非）發現 webshell 之後，應該立刻 `rm` 掉並重啟服務，以免繼續被利用。

**Q10.** 回報「未發現受影響」時，一定要一併寫出哪一項資訊？為什麼？

> [!question]- 測驗答案
>
> **Q1 — (B)。** 先判斷適用性能省下大量無謂的比對工作；
> 而且沒有資產清冊就無法回答這一題。
> → 見「第 1 步：判斷適用性」。
> ★★★ (D) 是最糟的答案 —— 那不是結論，那是猜測。
>
> **Q2 — 否。** 檔案雜湊是 IoC 金字塔最底層，攻擊者重新編譯一次就完全不同。
> 雜湊沒命中只能說「這個特定樣本不在」，還要往上比對路徑、程序與行為。
> → 見「IoC 金字塔」與「IoC 比對法二：檔案雜湊」。
>
> **Q3 — 三個問題。**
> ① 沒有 `-xdev`，會跨掛載點掃到 NFS／CIFS，可能永遠跑不完；
> ② 沒有排除 `/proc`、`/sys`，讀取虛擬檔案可能阻塞；
> ③ `-exec ... \;` 對每個檔案各起一個行程，效能極差，
> 且沒有 `-size` 限制會對超大檔案算雜湊。
> 正確寫法見「全機掃描的正確寫法」。★★★★★
>
> **Q4 —** 「無命中」＝**在確定的涵蓋範圍內查過且沒有發現**；
> 「無法確認」＝**根本沒有資料可查**（日誌已刪、清冊不全）。
> 把後者寫成前者的危險：對外是回報不實，日後爆發責任更重；
> 對內則讓日誌保存期不足的根本問題永遠不會被修。
> → 見「三種結論，不是兩種」與「無法確認怎麼辦」。★★★★★
>
> **Q5 —** 程序名稱（`comm`／`argv[0]`）是**程式自己可以任意設定的**，可以偽裝；
> `/proc/<pid>/exe` 是核心維護的**真實執行檔連結**，不能偽裝。
> 應相信後者。`(deleted)` 表示執行檔已從磁碟移除、只存在於記憶體，
> 這是後門程式的典型行為。
> → 見「從連線反查程序、再反查執行檔」。★★★★★
>
> **Q6 — (D) TTP。** 攻擊者換 IP、換網域、重編譯改雜湊都很容易，
> 但改變整套作業手法（怎麼進來、怎麼持久化、怎麼外傳）成本極高。
> → 見「IoC 金字塔」。
>
> **Q7 —** DNS 查詢發生在連線建立**之前**。就算後續 TCP 連線被防火牆擋掉，
> 查詢紀錄仍證明**主機內部有東西試圖連向 C2**，
> 也就是說這台機器上很可能已經有惡意程式在跑。
> → 見「DNS 查詢紀錄」。★★★★
>
> **Q8 —** `-xdev` 讓 `find` 不跨越檔案系統邊界。不加的話會掃進
> NFS／CIFS 等網路掛載點，造成掃描時間暴增、網路壅塞，
> 甚至掃到別台主機的資料而得到誤導性的結果。
> → 見「全機掃描的正確寫法」參數表。★★★★★
>
> **Q9 — 否，而且是嚴重錯誤。** 刪掉 webshell 會毀掉判斷
> 「入侵多久、拿走什麼、還有哪幾台中了」的關鍵證據，
> 而攻擊者通常留有多個後門，刪一個沒有用。
> 正確做法是隔離網路但保持開機，先保全證據。
> → 見「安全性注意事項」與 [[090-07-15-guide-資安實踐-被入侵主機的跡證檢查]]。★★★★★
>
> **Q10 — 必須寫出「查核的涵蓋期間」**（各類日誌各自涵蓋到哪一天）。
> 沒有涵蓋期間的「未發現」是一個無法驗證、也無法承擔責任的結論；
> 有了涵蓋期間，讀的人才知道這個結論的效力邊界在哪裡。
> → 見「回報」與「三種結論，不是兩種」。★★★★★

---

## 延伸閱讀

| 主題 | 篇章 |
| --- | --- |
| 命中之後怎麼保全證據 ★★★★★ | [[090-07-15-guide-資安實踐-被入侵主機的跡證檢查]] |
| 完整的事件應變六階段與通報 | [[090-07-04-guide-資安實踐-資安事件應變流程]] |
| 資產清冊怎麼建、怎麼維持準確 ★★★★★ | [[100-02-13-guide-維運-資產與授權管理]] |
| 集中日誌與 SIEM ★★★★★ | [[090-05-09-guide-資安設備-日誌集中與SIEM]] |
| 日誌保存期與輪替設定 | [[100-01-02-guide-日誌-日誌集中與輪替]] |
| 修補計畫怎麼排 | [[090-07-03-guide-資安實踐-弱點與修補管理流程]] |
| 用 ATT&CK 描述行為型 IoC ★★★★ | [[090-07-18-guide-資安實踐-MITRE-ATTCK與告警判讀]] |
| Wazuh 上做 IoC 比對與 FIM | [[090-08-00-idx-Wazuh資安監控]] |
| 系統強化與基線 | [[090-02-08-guide-防護-系統強化與稽核]] |
| 委外系統的日誌與查核義務 | [[090-07-11-guide-資安實踐-委外與供應鏈資安]] |
| 健診時會被問到的情資處理程序 | [[090-07-16-guide-資安實踐-政府資安健診的準備與執行]] |
| 演練：拿舊情資重跑一次流程 | [[090-07-17-guide-資安實踐-演練設計與演練紀錄]] |
| 找檔案與內容的完整用法 | [[020-01-07-cmd-Linux-尋找檔案與內容]] |
| 程序管理與 `/proc` | [[020-01-10-cmd-Linux-程序管理與訊號]] |
| Linux 日誌系統 | [[020-01-19-guide-Linux-日誌系統]] |
