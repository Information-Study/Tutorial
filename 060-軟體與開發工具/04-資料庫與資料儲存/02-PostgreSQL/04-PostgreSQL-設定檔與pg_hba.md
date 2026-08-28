---
title: "PostgreSQL 設定檔與 pg_hba"
desc: "四道關卡的錯誤訊息判讀、pg_hba 第一條命中即定案的比對順序、md5 轉 scram 遷移、reload 與 restart 的判準"
aliases: [postgresql.conf, pg_hba, pg_hba.conf, pg_ident.conf, postgresql.auto.conf, pg_reload_conf, scram-sha-256]
tags: [群組/軟體與開發工具, 服務/postgresql, 主題/設定, 主題/認證]
category: 資料庫與資料儲存
difficulty: 進階
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[01-PostgreSQL-安裝與初始化]]", "[[02-PostgreSQL-角色與權限]]", "[[03-psql-操作與常用指令]]"]
updated: 2026-08-28
---

# PostgreSQL 設定檔與 pg_hba

> [!abstract] 這篇你會學到
> - 看到 `psql: error:` 開頭的一行字，就能**在 10 秒內判斷卡在四道關卡的哪一關**（防火牆 / `listen_addresses` / `pg_hba.conf` / `GRANT`），而不是四個地方亂改
> - ★★★★ 說得出 `pg_hba.conf` 的比對規則：**第一條命中就定案、沒有 fall-through、沒命中就拒絕**，並解釋為什麼「我明明加了一行卻沒生效」幾乎都是被上面某一行先攔走
> - 分得清 `trust` / `peer` / `ident` / `md5` / `scram-sha-256` / `cert` 各自的信任來源與風險，並完成一次 **md5 → scram-sha-256 的全庫遷移**（含驅動相容性與回滾）
> - ★★★★ 判斷一個參數改完是 **reload 就好還是必須 restart**，用 `pg_settings.context` 查證而不是憑印象，並在改完後**確認新值真的生效**
> - 用 `pg_hba_file_rules` **在改壞之前抓出語法錯誤**，並寫出一支「改壞自動回滾」的套用腳本
> - 把 `log_connections` / `log_line_prefix` 調到「出事時查得到是誰、從哪裡、用哪一條規則被拒絕」的程度

## 前置知識

- [[01-PostgreSQL-安裝與初始化]] —— 叢集（cluster）概念、`postgres` OS 帳號、服務名稱與資料目錄
- [[02-PostgreSQL-角色與權限]] —— ★★★★ **`pg_hba.conf` 管「能不能連進來」，`GRANT` 管「連進來能做什麼」**，兩者是不同的關卡，本篇只講前者
- [[03-psql-操作與常用指令]] —— `psql` 的連線參數、反斜線指令；本篇的驗證步驟大量用到 `psql -c`
- [[04-MySQL-設定檔與調校]] —— 對照組。★★★ **同一件事在 MySQL 是寫在帳號的 host 欄位裡，在 PostgreSQL 是一個獨立檔案**，差異見下一節
- [[02-防火牆-ufw基礎與實務]] —— 第一道關卡在防火牆，不在資料庫
- [[17-systemd服務管理]] —— `reload` 與 `restart` 在 systemd 層怎麼下、失敗了去哪看

> [!tip] 這篇不講 SQL
> 建帳號、`GRANT`、`REVOKE` 的語法在 [[02-PostgreSQL-角色與權限]] 與 [[03-SQL基礎操作]]，
> 本篇一律**指過去、不重講**。這裡只處理「連線要能進到 SQL 那一層」之前的所有事。

---

## 觀念說明

### 一條連線要過四道關卡 ★★★★

新手在 PostgreSQL 上卡最久的地方，是把四個不同的問題當成同一個問題在改。

```
   應用主機 10.10.20.31                      資料庫主機 10.10.20.11
   (Laravel / Nuxt)                          (PostgreSQL 16)

   ┌──────────┐   TCP 5432    ┌───────┐   ┌──────────────┐   ┌─────────┐   ┌────────┐
   │  client  │ ────────────▶ │【1】  │──▶│【2】         │──▶│【3】    │──▶│【4】   │
   │  libpq   │               │防火牆 │   │listen_       │   │pg_hba   │   │GRANT   │
   └──────────┘               │ufw /  │   │addresses     │   │.conf    │   │角色權限│
                              │nft    │   │＋ port       │   │認證     │   │授權    │
                              └───────┘   └──────────────┘   └─────────┘   └────────┘
                                  │             │                 │             │
     卡在這關會看到 ──────────────┘             │                 │             │
       Connection timed out（等 15~130 秒才失敗）                  │             │
                                                │                 │             │
     卡在這關會看到 ────────────────────────────┘                 │             │
       Connection refused（【瞬間】失敗，不會等）                    │             │
                                                                  │             │
     卡在這關會看到 ─────────────────────────────────────────────┘             │
       FATAL: no pg_hba.conf entry for host "10.10.20.31", user "app", ...      │
       FATAL: password authentication failed for user "app"                     │
       FATAL: Peer authentication failed for user "app"                         │
                                                                                │
     卡在這關會看到 ───────────────────────────────────────────────────────────┘
       ERROR: permission denied for table orders
       FATAL: database "appdb" does not exist   ← 連得進來了，只是東西不在
```

> [!note] ★★★★ 這張圖是本篇最值錢的一段
> **錯誤訊息的「形狀」就標示了關卡編號**：
>
> | 你看到的字 | 卡在 | 去改哪裡 |
> | --- | --- | --- |
> | `Connection timed out` / 卡住很久 | 【1】防火牆 | `ufw` / `nftables` / 中間的實體防火牆 |
> | `Connection refused`（秒回） | 【2】沒在聽 | `listen_addresses`、`port`、服務沒起來 |
> | `no pg_hba.conf entry for ...` | 【3】沒有規則命中 | `pg_hba.conf` 加規則 |
> | `password authentication failed` | 【3】規則命中了但密碼錯 | 密碼或 `scram`/`md5` 不一致 |
> | `Peer authentication failed` | 【3】規則命中的是 `peer` | OS 帳號 ≠ DB 角色名，或該走 TCP |
> | `permission denied for ...` | 【4】授權 | `GRANT`（見 [[02-PostgreSQL-角色與權限]]） |
>
> ★★★★★ **`permission denied` 出現時代表你早就通過認證了**，
> 這時候再去改 `pg_hba.conf` 是完全白費力氣 —— 現場最常見的鬼打牆就是這一種。

### 和 MySQL 的對照：同一件事，兩套做法

從 MySQL 過來的人會被 `pg_hba.conf` 絆倒，因為 MySQL 沒有這個東西。

| 這件事 | MySQL 8.0 | PostgreSQL 16/17 |
| --- | --- | --- |
| 主設定檔 | `/etc/mysql/my.cnf` + `!includedir` | `/etc/postgresql/16/main/postgresql.conf` + `include_dir` |
| 線上改設定並持久化 | `SET PERSIST` → `mysqld-auto.cnf` | `ALTER SYSTEM SET` → `postgresql.auto.conf` |
| ★★★★ 誰贏 | `mysqld-auto.cnf` 最後讀，贏 | `postgresql.auto.conf` 最後讀，**贏** |
| 限制來源 IP | 寫在帳號裡：`'app'@'10.10.20.%'` | **獨立檔案** `pg_hba.conf` 的 ADDRESS 欄 |
| 多條規則怎麼選 | 挑**最明確**的一條（specificity） | ★★★★★ **由上而下，第一條命中即定案** |
| 認證外掛 | `caching_sha2_password` / `mysql_native_password` | `scram-sha-256` / `md5` / `peer` / `cert` … |
| 改完套用 | `FLUSH PRIVILEGES`（部分）／重啟 | `SELECT pg_reload_conf();`（`pg_hba` 一律夠用） |
| 監聽範圍 | `bind-address` | `listen_addresses` |

> [!warning] ★★★★ 兩個模型最大的差別
> MySQL 是「**先找最合適的帳號**」；PostgreSQL 是「**由上往下讀，讀到第一條符合的就用它，用失敗也不會往下找**」。
>
> ```
> MySQL 的直覺（錯的）：      PostgreSQL 的真實行為：
>   規則 A 不行 → 試 B         規則 A 命中 → 用 A 認證
>   規則 B 不行 → 試 C         A 認證失敗 → 【直接拒絕】，不會去試 B、C
> ```
>
> 這個差異造成了本篇後面幾乎所有的排錯情境。

### 設定檔家族：五個檔案，各管一件事

```
/etc/postgresql/16/main/                          ← Debian/Ubuntu 的設定目錄
├── postgresql.conf        主設定：監聽、記憶體、日誌、WAL…      【參數】
│    └── include_dir = 'conf.d'                                  （Debian 預設就有）
├── conf.d/
│    └── zz-local.conf     ★★★ 我們自己的覆寫檔，放這裡         【參數】
├── pg_hba.conf            誰可以從哪裡、用什麼方式連進來          【認證】
├── pg_ident.conf          外部身分（OS 帳號 / 憑證 CN）→ DB 角色  【對映】
├── pg_ctl.conf            pg_ctl 的額外參數（很少動）
├── start.conf             開機是否自動啟動這個 cluster
└── environment            伺服器行程的環境變數（如 PGDATA 之外的 locale）

/var/lib/postgresql/16/main/                      ← 資料目錄（PGDATA）
└── postgresql.auto.conf   ★★★★ ALTER SYSTEM 寫出來的，【最後讀、贏過上面全部】
```

> [!danger] ★★★★★ `postgresql.auto.conf` 是「設定明明改了卻沒生效」的頭號元兇
> 有人半年前在 `psql` 裡下了一句 `ALTER SYSTEM SET listen_addresses = 'localhost';`，
> 從此不管你怎麼改 `postgresql.conf` 都沒有用，而且**沒有任何警告**。
> 每次接手一台不熟的機器，第一件事就是：
>
> ```bash
> sudo cat /var/lib/postgresql/16/main/postgresql.auto.conf
> ```
>
> 這個檔案**永遠是最後讀的**，不受 `include_dir` 的字典序影響。

### `pg_hba.conf` 的比對流程 ★★★★★

`hba` = **H**ost-**B**ased **A**uthentication。一行就是一條規則，五（或四）個欄位：

```
TYPE   DATABASE   USER   ADDRESS        METHOD        [OPTIONS]
─────  ─────────  ─────  ─────────────  ────────────  ─────────
host   appdb      app    10.10.20.0/24  scram-sha-256
local  all        all                   peer           ← local 沒有 ADDRESS 欄
```

伺服器收到連線請求時的處理流程：

```
   新連線進來，帶著：連線型態(local/TCP/SSL) + 來源 IP + 要連的 DB + 宣稱的角色名
                                   │
                                   ▼
              ┌────────────────────────────────────────┐
              │ 從 pg_hba.conf 【第 1 行】開始往下讀    │
              └────────────────────────────────────────┘
                                   │
                     ┌─────────────┴─────────────┐
                     ▼                           ▼
        TYPE/DATABASE/USER/ADDRESS         有任何一欄不符
        【四欄全部符合】                          │
                     │                           ▼
                     │                   讀下一行 ──┐
                     │                              │
                     ▼                        （回到上面）
        ┌───────────────────────────┐              │
        │ 用【這一行】的 METHOD 認證 │              │
        └───────────────────────────┘              ▼
             │              │                 讀完最後一行還沒命中
        認證成功        認證失敗                    │
             │              │                       ▼
             ▼              ▼              FATAL: no pg_hba.conf entry
        進入【4】GRANT   FATAL: xxx        for host "..." , user "...",
                        authentication      database "...", no encryption
                        failed
                            ▲
                            │
        ★★★★★ 這裡【不會】回頭去試下面的規則。
              「沒有 fall-through、沒有 backup」是官方原文用詞。
```

> [!note] 兩種 FATAL 的意義完全不同 ★★★★
> ```
> FATAL: no pg_hba.conf entry for host "10.10.20.31", user "app", database "appdb", no encryption
>   → 【一條都沒命中】。要新增規則，或檢查 IP/DB/角色名是不是打錯。
>   → 訊息尾巴的 "no encryption" / "SSL encryption" 很關鍵：
>      它告訴你這條連線是不是 SSL，決定了 hostssl 的規則會不會被考慮。
>
> FATAL: password authentication failed for user "app"
>   → 【有命中】，只是密碼不對（或 md5/scram 不一致）。
>   → 這時候加規則是沒用的，要去找是【哪一行】命中的。
> ```

### `reload` 還是 `restart`：不要憑印象 ★★★★

PostgreSQL 每個參數都有一個 `context`，決定它能在什麼時機被改變。

| `context` | 意義 | 套用方式 | 代表參數 |
| --- | --- | --- | --- |
| `internal` | 編譯期決定 | ★ 改不了 | `block_size`、`segment_size` |
| `postmaster` | 只能啟動時設定 | ★★★★ **必須 restart** | `listen_addresses`、`port`、`max_connections`、`shared_buffers`、`wal_level`、`shared_preload_libraries` |
| `sighup` | 收到 SIGHUP 生效 | ★★ **reload 即可** | `ssl`、`password_encryption`、`log_connections`、`log_line_prefix`、`archive_command` |
| `superuser-backend` | 連線建立時、需超級使用者 | ★ 新連線生效 | `log_connections`（部分版本） |
| `backend` | 連線建立時決定 | ★ 新連線生效 | `post_auth_delay` |
| `superuser` | 執行期，超級使用者可改 | ★ `SET` 立即 | `log_min_duration_statement` |
| `user` | 執行期，任何人可改 | ★ `SET` 立即 | `work_mem`、`search_path` |

★★★★ **`pg_hba.conf` 與 `pg_ident.conf` 永遠只需要 reload**，不管你改了什麼。
需要 restart 的只有 `postgresql.conf` 裡那些 `postmaster` 參數。

不要背，直接查：

```bash
sudo -u postgres psql -c \
  "SELECT name, setting, context FROM pg_settings WHERE name IN ('listen_addresses','port','ssl','password_encryption','max_connections','log_connections');"
```

預期輸出：

```text
        name         |  setting  |  context
---------------------+-----------+------------
 listen_addresses    | localhost | postmaster   # ★★★★ 改了要 restart
 log_connections     | off       | superuser-backend
 max_connections     | 100       | postmaster   # ★★★★ 改了要 restart
 password_encryption | scram-sha-256 | user     # ★★ reload 即可，新設密碼才套用
 port                | 5432      | postmaster   # ★★★★ 改了要 restart
 ssl                 | on        | sighup       # ★★ 換憑證不必 restart
(6 rows)
```

> [!tip] ★★★ `context` 欄的值會隨版本微調
> 上表是 PostgreSQL 16/17 的常見結果，但**以你機器上這個查詢的輸出為準**。
> 手冊裡任何「這個要不要重啟」的說法，都比不上這一行查詢可靠。

---

## 基礎設定

### 先確認「這台機器到底在讀哪些檔案」★★★★

不要用 `find` 猜，讓伺服器自己說：

```bash
sudo -u postgres psql -c "SHOW config_file;" \
                     -c "SHOW hba_file;" \
                     -c "SHOW ident_file;" \
                     -c "SHOW data_directory;"
```

預期輸出：

```text
               config_file
------------------------------------------
 /etc/postgresql/16/main/postgresql.conf
(1 row)

                hba_file
------------------------------------------
 /etc/postgresql/16/main/pg_hba.conf       # ★★★★ 認得這條路徑
(1 row)

               ident_file
------------------------------------------
 /etc/postgresql/16/main/pg_ident.conf
(1 row)

      data_directory
--------------------------
 /var/lib/postgresql/16/main
(1 row)
```

★★★ 一台機器可能有**多個 cluster**（16/main、16/staging、17/main…），
每個 cluster 有自己的一整組設定檔與 port。Debian 系用這個看：

```bash
pg_lsclusters
```

預期輸出：

```text
Ver Cluster Port Status Owner    Data directory              Log file
16  main    5432 online postgres /var/lib/postgresql/16/main /var/log/postgresql/postgresql-16-main.log
17  staging 5433 online postgres /var/lib/postgresql/17/staging /var/log/postgresql/postgresql-17-staging.log
```

> [!danger] ★★★★ 改錯 cluster 是很常見的浪費一小時
> 兩個 cluster 的設定檔長得幾乎一樣，只差路徑裡的版本號與 cluster 名。
> **每次動手前先跑一次 `SHOW hba_file;`**，把輸出貼到你的工作紀錄裡。

看看整個設定目錄：

```bash
ls -l /etc/postgresql/16/main/
```

預期輸出：

```text
total 60
drwxr-xr-x 2 postgres postgres  4096 Aug 20 10:02 conf.d
-rw-r--r-- 1 postgres postgres   315 Aug 20 10:02 environment
-rw-r--r-- 1 postgres postgres   143 Aug 20 10:02 pg_ctl.conf
-rw-r----- 1 postgres postgres  5002 Aug 26 14:31 pg_hba.conf     # ★★★ 0640，只有 postgres 讀得到
-rw-r----- 1 postgres postgres  1636 Aug 20 10:02 pg_ident.conf
-rw-r--r-- 1 postgres postgres 29735 Aug 26 14:31 postgresql.conf
-rw-r--r-- 1 postgres postgres   317 Aug 20 10:02 start.conf
```

> [!info]- Rocky / AlmaLinux（RHEL 系）對照
> PGDG 的 RPM 套件**把設定檔放在資料目錄裡**，沒有 `/etc/postgresql/`：
>
> ```bash
> sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
> sudo dnf -qy module disable postgresql          # ★★★ 不擋掉會裝到 AppStream 的舊版
> sudo dnf install -y postgresql16-server
> sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
> sudo systemctl enable --now postgresql-16
> ```
>
> | 項目 | Ubuntu/Debian | RHEL 系（PGDG） |
> | --- | --- | --- |
> | 設定檔 | `/etc/postgresql/16/main/` | `/var/lib/pgsql/16/data/` |
> | 資料目錄 | `/var/lib/postgresql/16/main/` | `/var/lib/pgsql/16/data/`（同一個） |
> | 服務名 | `postgresql@16-main` | `postgresql-16` |
> | reload | `pg_ctlcluster 16 main reload` | `systemctl reload postgresql-16` |
> | 日誌 | `/var/log/postgresql/postgresql-16-main.log` | `/var/lib/pgsql/16/data/log/*.log` |
> | 多 cluster 工具 | `pg_lsclusters`、`pg_createcluster` | ★★★ **沒有**，要自己 `initdb` 到不同目錄 |
> | 執行檔 | 在 `PATH` 裡 | `/usr/pgsql-16/bin/`，★★ 要自己加 `PATH` |
>
> ★★★★ 最大的雷：**RHEL 系初始的 `pg_hba.conf` 內容與 Debian 不同**。
> Debian 的 `pg_createcluster` 會產生 `local ... peer` + `host ... scram-sha-256`；
> RHEL 的 `initdb` 依參數不同可能產生 `ident` 甚至 `trust`。
> **不要假設，一定自己看過：**
>
> ```bash
> sudo grep -vE '^\s*#|^\s*$' /var/lib/pgsql/16/data/pg_hba.conf
> ```
>
> 另外 RHEL 系預設 **SELinux enforcing**，改 `port` 之後要
> `semanage port -a -t postgresql_port_t -p tcp 5433`，否則服務起不來。

### 讀懂預設的 `pg_hba.conf`

只看有效行（去掉註解與空行）：

```bash
sudo grep -vE '^\s*#|^\s*$' /etc/postgresql/16/main/pg_hba.conf
```

預期輸出（Ubuntu 24.04 + PostgreSQL 16 全新安裝）：

```text
local   all             postgres                                peer
local   all             all                                     peer
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256
local   replication     all                                     peer
host    replication     all             127.0.0.1/32            scram-sha-256
host    replication     all             ::1/128                 scram-sha-256
```

逐行的意思：

```
local  all  postgres            peer   ← ★★★★ 這一行讓 `sudo -u postgres psql` 免密碼
                                          因為 OS 帳號 postgres == DB 角色 postgres
local  all  all                 peer   ← 其他人走 unix socket 也要 OS 帳號同名
host   all  all  127.0.0.1/32   scram  ← 本機走 TCP 要密碼
host   all  all  ::1/128        scram  ← 同上，IPv6
local  replication ...                 ← ★★★ `all` 【不包含】replication，要單獨寫
```

> [!warning] ★★★★ 預設值裡**沒有任何一行允許遠端連線**
> 這是刻意的。加上 `listen_addresses = 'localhost'`，
> 一台全新安裝的 PostgreSQL **從外面完全連不進來** —— 這是好事，不是壞掉。
> 開放遠端是本篇〈完整實戰範例〉要做的事，而且要一次做對。

### 確認「實際值」而不是「你以為的值」★★★★

和 MySQL 一樣，**寫進檔案的值 ≠ 生效的值**。PostgreSQL 的 `pg_settings` 比 MySQL 好用，
因為它會告訴你這個值**是從哪個檔案的第幾行來的**：

```bash
sudo -u postgres psql -x -c \
  "SELECT name, setting, unit, source, sourcefile, sourceline, pending_restart
     FROM pg_settings WHERE name = 'listen_addresses';"
```

預期輸出：

```text
-[ RECORD 1 ]---+----------------------------------------
name            | listen_addresses
setting         | localhost
unit            |
source          | configuration file        # ★★★★ 看這欄
sourcefile      | /etc/postgresql/16/main/postgresql.conf
sourceline      | 59                        # ★★★★ 直接告訴你第幾行
pending_restart | f
```

`source` 欄可能的值與意義：

| `source` | 意義 | 星級 |
| --- | --- | --- |
| `default` | 內建預設值，沒人改過 | ★ |
| `configuration file` | 來自某個 `.conf`，看 `sourcefile` | ★★ |
| `command line` | 啟動參數（systemd unit 或 `pg_ctl -o`） | ★★★ 藏得深，很容易漏 |
| `override` | 被伺服器內部強制覆蓋 | ★★ |
| `session` / `user` | 這條連線自己 `SET` 的 | ★★★ 只影響你這條連線 |
| `database` / `role` | `ALTER DATABASE/ROLE ... SET` 設的 | ★★★★ **最容易被忘記的一種** |

> [!danger] ★★★★ `ALTER ROLE ... SET` 是隱藏的第三份設定
> ```bash
> sudo -u postgres psql -c "\drds"
> ```
> 預期輸出：
> ```text
>  Role | Database |          Settings
> ------+----------+-----------------------------
>  app  |          | search_path=app, public     # ★★★ 只對 app 這個角色生效
>       | appdb    | timezone=Asia/Taipei
> (2 rows)
> ```
> 這些設定**不在任何 `.conf` 檔案裡**，`grep` 一輩子也找不到。
> 交接一台機器時 `\drds` 一定要跑一次。

### 我們自己的覆寫檔要放哪裡

★★★★ **不要直接改 `postgresql.conf`**，理由和 MySQL 的 `mysqld.cnf` 一樣：
套件升級時 `dpkg` 會問你要不要覆蓋，選錯就整份沒了。

Debian/Ubuntu 的 `postgresql.conf` 結尾已經有這一行（先確認它存在）：

```bash
grep -n "include_dir" /etc/postgresql/16/main/postgresql.conf
```

預期輸出：

```text
815:include_dir = 'conf.d'			#include files ending in '.conf' from
```

★★★ 如果沒有這行（自己 `initdb` 出來的 cluster 通常沒有），自己補上去。
然後建立我們的覆寫檔：

```bash
sudo install -o postgres -g postgres -m 0640 /dev/null \
  /etc/postgresql/16/main/conf.d/zz-local.conf
```

```
命名為什麼是 zz-：
  · include_dir 依 C locale 的字典序讀取 → zz- 最後讀 → 我們的值贏
  · 一眼看得出「這是人為調整」，不是發行版原檔
  · dpkg 不會碰不屬於任何套件的檔案，升級時不會有覆蓋詢問
```

> [!warning] ★★★★ 但 `conf.d` 仍然贏不了 `postgresql.auto.conf`
> 讀取順序（後面的贏）：
> ```
> postgresql.conf  →  include_dir 展開的 conf.d/*.conf（字典序）
>                  →  postgresql.auto.conf          ← ★★★★ 永遠最後
>                  →  command line（systemd 的 -c 參數）  ← ★★★★★ 比 auto.conf 還贏
> ```
> 所以「我明明寫在 `zz-local.conf` 裡了」不是保證。永遠用 `pg_settings.source` 驗證。

### 三種套用方式，選對那一種

```bash
# 方式 A：★★★ SQL 內下，最常用、不需要 sudo，回傳 t 代表訊號送出去了
sudo -u postgres psql -c "SELECT pg_reload_conf();"
```

預期輸出：

```text
 pg_reload_conf
----------------
 t
(1 row)
```

```bash
# 方式 B：★★ Debian 系的 cluster 工具，會處理多 cluster
sudo pg_ctlcluster 16 main reload
```

預期輸出：（成功時**完全沒有輸出**）

```text
```

```bash
# 方式 C：★★ systemd。注意 template unit 的寫法
sudo systemctl reload postgresql@16-main
```

> [!danger] ★★★★★ `pg_reload_conf()` 回傳 `t` **不代表設定是對的**
> 它只代表「SIGHUP 送出去了」。如果 `pg_hba.conf` 有語法錯誤，
> 伺服器會**保留舊的規則繼續跑**，只在日誌裡留一行警告，
> 而你的 `psql` 看到的是漂亮的 `t`。
>
> ```
> 你以為：改好了 → t → 收工
> 實際上：改好了 → t → 【新規則根本沒載入】→ 明天早上全站連不上
> ```
>
> **每一次 reload 之後都必須做兩件事**：
> ① 看日誌尾巴；② 查 `pg_hba_file_rules` 的 `error` 欄。做法見下一節。

### reload 之後的兩個必做驗證 ★★★★

```bash
sudo tail -n 20 /var/log/postgresql/postgresql-16-main.log
```

成功時的預期輸出：

```text
2026-08-28 14:32:10.114 CST [1284] LOG:  received SIGHUP, reloading configuration files
2026-08-28 14:32:10.118 CST [1284] LOG:  parameter "log_connections" changed to "on"
```

失敗時的預期輸出（★★★★ 認得這兩行）：

```text
2026-08-28 14:35:02.771 CST [1284] LOG:  received SIGHUP, reloading configuration files
2026-08-28 14:35:02.772 CST [1284] LOG:  invalid connection type "hosts"
2026-08-28 14:35:02.772 CST [1284] CONTEXT:  line 96 of configuration file "/etc/postgresql/16/main/pg_hba.conf"
2026-08-28 14:35:02.772 CST [1284] FATAL:  could not load pg_hba.conf   # ★★★★★ 舊規則繼續生效
```

第二個驗證是 `pg_hba_file_rules`（PostgreSQL 10 起提供）：

```bash
sudo -u postgres psql -x -c \
  "SELECT rule_number, file_name, line_number, type, database, user_name, address, auth_method, error
     FROM pg_hba_file_rules WHERE error IS NOT NULL;"
```

沒有問題時的預期輸出：

```text
(0 rows)                      # ★★★★ 這就是我們要的
```

有問題時：

```text
-[ RECORD 1 ]---------------------------------------------------
rule_number | 
file_name   | /etc/postgresql/16/main/pg_hba.conf
line_number | 96
type        | 
database    | 
user_name   | 
address     | 
auth_method | 
error       | invalid connection type "hosts"     # ★★★★ 錯在哪、第幾行，一目了然
```

> [!tip] ★★★ 這張 view 就是 PostgreSQL 版的 `nginx -t`
> 差別是它**必須在 reload 之後**才反映新檔案（它讀的是伺服器記憶體中的解析結果）。
> 所以正確順序是：**備份 → 改 → reload → 查 error → 有錯就用備份還原再 reload**。
> 這個流程在〈完整實戰範例〉會寫成腳本。

---

## 進階設定與調校

### 一、`pg_hba.conf` 五個欄位逐欄拆解

#### TYPE：這條規則管哪一種連線 ★★★★

| TYPE | 適用連線 | 說明 |
| --- | --- | --- |
| `local` | Unix domain socket | ★★★ **沒有 ADDRESS 欄**。`psql` 不加 `-h` 時走這個 |
| `host` | TCP/IP，**不管有沒有 SSL** | ★★★ 最常用，但也最寬鬆 |
| `hostssl` | TCP/IP，**只有 SSL 連線**符合 | ★★★★ 要求加密就用這個 |
| `hostnossl` | TCP/IP，**只有非 SSL**符合 | ★★★ 通常拿來搭配 `reject` |
| `hostgssenc` | 有 GSSAPI 加密的 TCP | ★ AD/Kerberos 環境才用得到 |
| `hostnogssenc` | 沒有 GSSAPI 加密的 TCP | ★ |

★★★★ 強制加密的標準寫法（**兩行，順序不能反**）：

```text
# /etc/postgresql/16/main/pg_hba.conf
hostnossl  all  all  0.0.0.0/0  reject                # ★★★★ 先把明文連線打掉
hostssl    appdb  app  10.10.20.0/24  scram-sha-256   # 再放行加密連線
```

寫反的話，`hostssl` 那行會先命中加密連線、放行，接著明文連線落到 `reject`。
結果是一樣的 —— **但如果你把 `host`（不分 SSL）寫在最上面，`reject` 那行永遠不會被讀到**。

#### DATABASE：哪些資料庫

| 寫法 | 意義 | 星級 |
| --- | --- | --- |
| `appdb` | 就這一個 | ★★ |
| `appdb,logdb` | 逗號分隔多個（**不要有空白**） | ★★★ 加了空白會被當成下一欄 |
| `all` | 所有資料庫 | ★★★ ★★★★ **不含 replication** |
| `replication` | 實體複寫連線（見 [[07-PostgreSQL-複寫與高可用]]） | ★★★★ 必須單獨一行 |
| `sameuser` | 資料庫名 == 角色名時才符合 | ★★ 多租戶好用 |
| `samerole` | 角色是「與資料庫同名的 role」的成員 | ★★ |
| `/^app_\d+$` | ★★★ 正規表示式（**PostgreSQL 16 起**），前面加 `/` | ★★★ |
| `@dblist` | 從檔案讀清單 | ★★ |

> [!warning] ★★★★ `all` 不包含 `replication`
> 這是官方明文規定的例外。你設了 `host all all 10.10.20.0/24 scram-sha-256`，
> 備援機仍然會拿到 `no pg_hba.conf entry for host "..." , database "replication"`。
> **複寫一定要單獨一行**：
> ```text
> host  replication  replicator  10.10.20.12/32  scram-sha-256
> ```
> 另外 ★★★ **邏輯複寫（logical replication）走的是一般資料庫連線**，
> 不吃 `replication` 這個關鍵字，要用實際的資料庫名。

#### USER：哪些角色

| 寫法 | 意義 | 星級 |
| --- | --- | --- |
| `app` | 這個角色 | ★★ |
| `app,report` | 多個 | ★★ |
| `all` | 所有角色 | ★★★ |
| `+devs` | ★★★★ **`devs` 這個 role 的所有成員（會遞迴展開）** | ★★★★ |
| `/^svc_` | 正規表示式（PostgreSQL 16 起） | ★★★ |
| `@userlist` | 從檔案讀 | ★★ |

★★★★ `+groupname` 是機關情境最實用的一個：把「可以從辦公室網段連進來的人」
做成一個 role，人員異動時只要 `GRANT devs TO 新人;`，**完全不用改 `pg_hba.conf`、不用 reload**。

```bash
sudo -u postgres psql -c "CREATE ROLE dba_group NOLOGIN;" \
                      -c "GRANT dba_group TO alice, bob;"
```

```text
# pg_hba.conf
hostssl  all  +dba_group  10.10.30.0/24  scram-sha-256
```

#### ADDRESS：來源位址（`local` 沒有這欄）

| 寫法 | 意義 | 星級 |
| --- | --- | --- |
| `10.10.20.31/32` | ★★★★ **單一主機，最安全的寫法** | ★★★★ |
| `10.10.20.0/24` | 一個網段 | ★★★ |
| `0.0.0.0/0` | ★★★★★ 全世界的 IPv4 | ★★★★★ |
| `::0/0` | 全世界的 IPv6 | ★★★★★ |
| `all` | ★★★★★ IPv4 + IPv6 全部 | ★★★★★ |
| `samehost` | 伺服器自己的任一個 IP | ★★ |
| `samenet` | 伺服器直連的任一個子網 | ★★★ 網卡換了範圍就跟著變 |
| `app01.example.gov.tw` | 主機名稱（★★★★ 需要反解 + 正解雙向驗證） | ★★★ |
| `.example.gov.tw` | 前面加點 = 尾綴比對，符合所有子網域 | ★★★ |

> [!danger] ★★★★ 用主機名稱當 ADDRESS 的代價
> PostgreSQL 會對來源 IP 做**反向解析**，再把結果**正向解析**回來確認一致。
> ```
> 後果一：每次新連線多兩次 DNS 查詢 → 高頻短連線時延遲明顯
> 後果二：★★★★★ DNS 掛掉 = 所有人連不進來，而且錯誤訊息是
>          「no pg_hba.conf entry」，會讓你完全往錯的方向查
> ```
> **正式環境一律寫 IP/CIDR。** 需要彈性就寫網段，不要寫主機名。

#### METHOD 與 OPTIONS：認證方式

見下一節的完整選型表。OPTIONS 是 `key=value` 形式，常見的：

```text
host  all  all  10.10.20.0/24  cert   map=svcmap clientcert=verify-full
host  all  all  10.10.20.0/24  ldap   ldapserver=ldap.example.gov.tw ldapprefix="cn=" ldapsuffix=", dc=example, dc=gov, dc=tw"
```

### 二、★★★★★ 比對順序：本篇最容易出事的一節

規則只有一句話：**由上而下，第一條四欄全中的規則決定一切，用它認證失敗也不會往下找。**

#### 陷阱 A：寬鬆規則放在上面，嚴格規則永遠讀不到

```text
# ✗ 錯誤示範
host  all    all   10.10.20.0/24   trust            ← 第 1 行就全中了
host  appdb  app   10.10.20.31/32  scram-sha-256    ← ★★★★★ 永遠不會被讀到
```

`10.10.20.31` 上的任何人、用任何角色名，都會在第 1 行拿到 `trust`（**免密碼直接進**）。
第 2 行寫得再嚴謹也沒有意義。

```text
# ✓ 正確：明確的放上面，寬鬆的放下面
host  appdb  app         10.10.20.31/32  scram-sha-256
host  all    +dba_group  10.10.30.0/24   scram-sha-256
host  all    all         0.0.0.0/0       reject            ← ★★★ 明確拒絕，收尾
```

> [!tip] ★★★★ 記憶法：像防火牆規則一樣讀
> `pg_hba.conf` 的語意和 `iptables` 的 chain 一模一樣：
> **specific first, general last, 最後一條明確 deny**。
> 見 [[03-防火牆-nftables與iptables]]。

#### 陷阱 B：以為「認證失敗會退回去試下一條」

```text
host  appdb  app  10.10.20.0/24   scram-sha-256    ← 命中，密碼錯 → 【直接 FATAL】
host  appdb  app  10.10.20.31/32  trust            ← ★★★★★ 不會被嘗試
```

工程師常常想「我在下面加一條 trust 當後路」，這是**完全無效**的，
而且會在稽核報告上留下一條「存在 trust 規則」的高風險發現。

#### 陷阱 C：`hostssl` 與連線是否加密

```text
hostssl  appdb  app  10.10.20.0/24  scram-sha-256
```

若應用端的連線字串是 `sslmode=disable`，這一行**不會命中**，
你拿到的錯誤是 `no pg_hba.conf entry for host "10.10.20.31", user "app", database "appdb", no encryption`。
★★★★ **訊息最後那句 `no encryption` 就是給你的線索** —— 問題在應用端的 `sslmode`，不在規則。

#### 找出「到底是哪一行命中」的方法 ★★★★

PostgreSQL 不會直接告訴你命中的行號，但有兩招：

**招數一**：把 `pg_hba_file_rules` 印出來，用眼睛從上往下模擬一次。

```bash
sudo -u postgres psql -c \
  "SELECT rule_number, line_number, type, database, user_name, address, auth_method
     FROM pg_hba_file_rules ORDER BY rule_number;"
```

預期輸出：

```text
 rule_number | line_number |  type   |   database    | user_name  |    address    |  auth_method
-------------+-------------+---------+---------------+------------+---------------+---------------
           1 |          89 | local   | {all}         | {postgres} |               | peer
           2 |          91 | local   | {all}         | {all}      |               | peer
           3 |          93 | host    | {all}         | {all}      | 127.0.0.1     | scram-sha-256
           4 |          95 | host    | {appdb}       | {app}      | 10.10.20.31   | scram-sha-256
           5 |          97 | host    | {replication} | {repl}     | 10.10.20.12   | scram-sha-256
           6 |          99 | host    | {all}         | {all}      | 0.0.0.0       | reject
(6 rows)
```

★★★ `rule_number` 就是實際的比對順序（`include` 進來的檔案也會被展開排進去）。

**招數二**：暫時把 `log_connections` 打開，從日誌反推。

```bash
sudo -u postgres psql -c "ALTER SYSTEM SET log_connections = 'on';" \
                      -c "SELECT pg_reload_conf();"
```

日誌會出現：

```text
2026-08-28 15:02:41.220 CST [4471] LOG:  connection received: host=10.10.20.31 port=51122
2026-08-28 15:02:41.226 CST [4471] LOG:  connection authenticated: identity="app" method=scram-sha-256 (/etc/postgresql/16/main/pg_hba.conf:95)
2026-08-28 15:02:41.227 CST [4471] LOG:  connection authorized: user=app database=appdb SSL enabled (protocol=TLSv1.3, cipher=TLS_AES_256_GCM_SHA384)
```

> [!note] ★★★★★ `connection authenticated` 那行會直接印出「檔案:行號」
> `(/etc/postgresql/16/main/pg_hba.conf:95)` —— 這是 PostgreSQL 15 起新增的欄位，
> **是找出「哪一行命中」最直接的證據**。排 pg_hba 問題時第一個該打開的就是它。
> 排完記得關掉（高流量下每條連線三行日誌很可觀），見〈安全性注意事項〉。

### 三、認證方式選型表 ★★★★

| METHOD | 信任來源 | 適用場景 | 風險 |
| --- | --- | --- | --- |
| `trust` | ★★★★★ **不驗證任何東西** | 只有全新初始化、要救回忘記的密碼時 | ★★★★★ 誰都能冒充 `postgres` |
| `reject` | —— | 明確拒絕，放在規則尾巴或擋明文 | ★ |
| `scram-sha-256` | 密碼（挑戰／回應，**密碼不上線**） | ★★★★ **所有密碼場景的唯一正解** | ★★ |
| `md5` | 密碼（舊式雜湊） | 只為了相容老驅動 | ★★★★ 雜湊可被離線破解，且**等同密碼**（拿到 hash 就能登入） |
| `password` | ★★★★★ **明文送密碼** | 幾乎沒有 | ★★★★★ 沒有 SSL 就是全網可讀 |
| `peer` | OS 使用者名稱（**只限 local**） | ★★★★ 主機上的維運腳本、`sudo -u postgres` | ★ 但要求 OS 帳號名 == 角色名 |
| `ident` | 遠端主機的 identd 服務 | ★ 幾乎不要用 | ★★★★ 信任的是**對方主機的自我宣告** |
| `cert` | ★★★★ 用戶端憑證（隱含 `clientcert=verify-full`） | 機關間、跨網段的高保證連線 | ★★ 憑證管理成本高 |
| `ldap` | 外部 LDAP / AD | 集中帳號管理 | ★★★ LDAP 掛掉全體登不入；密碼會經過 PG |
| `gss` | Kerberos / AD 票證 | Windows AD 整合 | ★★ 設定複雜 |
| `pam` / `radius` | 系統 PAM / RADIUS | 特殊需求 | ★★★ |

> [!danger] ★★★★★ `trust` 只有一種正當用途
> 就是**忘記 `postgres` 密碼**時的救援：
> ```bash
> # 1) 只把 local 那一行暫時改成 trust
> sudo cp /etc/postgresql/16/main/pg_hba.conf /root/pg_hba.rescue.bak
> sudo sed -i '/^local\s\+all\s\+postgres/s/\bpeer\b/trust/' /etc/postgresql/16/main/pg_hba.conf
> sudo pg_ctlcluster 16 main reload
>
> # 2) 立刻改密碼（★★★ 用 \password，不要用 ALTER ROLE ... PASSWORD '明文'，見安全性一節）
> sudo -u postgres psql -c "\password postgres"
>
> # 3) ★★★★★ 馬上還原，不要「等一下再說」
> sudo cp /root/pg_hba.rescue.bak /etc/postgresql/16/main/pg_hba.conf
> sudo pg_ctlcluster 16 main reload
> sudo -u postgres psql -c "SELECT count(*) FROM pg_hba_file_rules WHERE auth_method = 'trust';"
> ```
> 最後一行的預期輸出必須是：
> ```text
>  count
> -------
>      0
> (1 row)
> ```
> ★★★★★ 只要 `trust` 存在超過必要的那 30 秒，就是一個資安事件。

### 四、★★★★ 從 `md5` 遷移到 `scram-sha-256`

PostgreSQL 14 起 `password_encryption` 預設就是 `scram-sha-256`，
但**從舊版升級上來的資料庫，既有角色的密碼還是 md5 格式**，
而 `pg_hba.conf` 寫 `scram-sha-256` 時，**md5 密碼的角色一律登入失敗**。

#### 【1】先盤點：誰還是 md5

```bash
sudo -u postgres psql -c \
  "SELECT rolname,
          CASE WHEN rolpassword LIKE 'SCRAM-SHA-256\$%' THEN 'scram'
               WHEN rolpassword LIKE 'md5%'            THEN 'md5'
               WHEN rolpassword IS NULL                THEN '(無密碼)'
               ELSE '其他' END AS pwd_type
     FROM pg_authid WHERE rolcanlogin ORDER BY 2, 1;"
```

預期輸出：

```text
  rolname   | pwd_type
------------+----------
 legacy_app | md5        # ★★★★ 這個換規則之後會登不進來
 report     | md5        # ★★★★
 app        | scram
 postgres   | scram
 monitoring | (無密碼)   # ★★★ 靠 peer 或 .pgpass，換規則也不受影響
(5 rows)
```

#### 【2】確認 `password_encryption`

```bash
sudo -u postgres psql -c "SHOW password_encryption;"
```

預期輸出：

```text
 password_encryption
---------------------
 scram-sha-256          # ★★★ 不是這個就先改，否則重設密碼還是產生 md5
(1 row)
```

若不是，改在 `conf.d/zz-local.conf` 並 reload：

```ini
# /etc/postgresql/16/main/conf.d/zz-local.conf
password_encryption = 'scram-sha-256'
```

#### 【3】逐一重設密碼（★★★★ 這一步一定要使用者本人在場）

```bash
sudo -u postgres psql -c "\password legacy_app"
```

★★★★ `\password` 是 `psql` 的用戶端指令，它會**在本機算好雜湊再送出**，
所以**明文密碼不會出現在 SQL 日誌、不會出現在 `~/.psql_history`**。
這是它和 `ALTER ROLE ... PASSWORD '明文'` 最關鍵的差別（見〈安全性注意事項〉）。

#### 【4】驗證都轉完了

```bash
sudo -u postgres psql -tAc \
  "SELECT count(*) FROM pg_authid WHERE rolcanlogin AND rolpassword LIKE 'md5%';"
```

預期輸出：

```text
0
```

#### 【5】最後才改 `pg_hba.conf`

順序不能反 ★★★★★：**先全部轉成 scram，再改規則**。
反過來做，會在改規則的那一秒讓所有 md5 帳號斷線。

> [!warning] ★★★ 驅動相容性檢查表
> | 用戶端 | 支援 scram-sha-256 起始版本 |
> | --- | --- |
> | libpq / psql | 10 |
> | PHP PDO_pgsql（走 libpq） | 跟著系統的 libpq 走 ★★★ 通常沒問題 |
> | JDBC (pgjdbc) | 42.2.0 |
> | Node.js `pg` | 8.x ★★★ 7.x 會失敗 |
> | Python psycopg2 | 2.8（且需 libpq ≥ 10） |
> | 老舊 ODBC / Delphi / VB6 應用 | ★★★★ **很可能不支援，這是機關最常見的卡點** |
>
> 真的有無法升級的老應用，**唯一可接受的折衷**是：
> 讓那一個角色、那一個來源 IP 走 `md5`，其餘全部 `scram-sha-256`，並在稽核文件上列為已知風險：
> ```text
> hostssl  legacydb  legacy_app  10.10.40.7/32  md5             # ★★★★ 已知風險，2026-12 前汰換
> hostssl  all       all         10.10.20.0/24  scram-sha-256
> ```

### 五、`pg_ident.conf`：把外部身分對映成資料庫角色

問題情境：Nginx／PHP-FPM 以 OS 帳號 `www-data` 執行，
但資料庫角色叫 `app`。用 `peer` 會失敗（`www-data` ≠ `app`），
可是我們又不想在設定檔裡放密碼。

解法是 `map=`：

```text
# /etc/postgresql/16/main/pg_hba.conf
local  appdb  app  peer  map=svcmap
```

```text
# /etc/postgresql/16/main/pg_ident.conf
# MAPNAME   SYSTEM-USERNAME   PG-USERNAME
svcmap      www-data          app
svcmap      deploy            app
svcmap      /^dev_(.*)$       \1            # ★★★ 正規表示式 + 反向參照（PostgreSQL 16 起支援更多寫法）
```

驗證（PostgreSQL 16 起有專屬的 view）：

```bash
sudo -u postgres psql -c "SELECT * FROM pg_ident_file_mappings;"
```

預期輸出：

```text
 map_number |                file_name                | line_number | map_name | sys_name  | pg_username | error
------------+-----------------------------------------+-------------+----------+-----------+-------------+-------
          1 | /etc/postgresql/16/main/pg_ident.conf    |          45 | svcmap   | www-data  | app         |
          2 | /etc/postgresql/16/main/pg_ident.conf    |          46 | svcmap   | deploy    | app         |
(2 rows)
```

實測：

```bash
sudo -u www-data psql -d appdb -c "SELECT current_user, session_user;"
```

預期輸出：

```text
 current_user | session_user
--------------+--------------
 app          | app            # ★★★★ 成功了：OS 是 www-data，DB 身分是 app，全程免密碼
(1 row)
```

> [!tip] ★★★★ 這是「設定檔裡不放密碼」最乾淨的做法
> Laravel 的 `.env` 裡 `DB_PASSWORD` 留空、`DB_HOST` 留空（走 socket），
> 密碼就完全不存在於檔案系統上。代價是**應用與資料庫必須同一台機器**。
> 跨主機的做法見〈完整實戰範例〉與 [[08-用自建CA簽發伺服器憑證]]。

### 六、`hostssl` 與憑證認證

先確認伺服器端 SSL 有開：

```bash
sudo -u postgres psql -c "SHOW ssl;" -c "SHOW ssl_cert_file;" -c "SHOW ssl_key_file;"
```

預期輸出：

```text
 ssl
-----
 on
(1 row)

              ssl_cert_file
------------------------------------------
 /etc/ssl/certs/ssl-cert-snakeoil.pem      # ★★★ Debian 的自簽預設憑證，正式環境要換掉
(1 row)
```

★★★★ Ubuntu 套件預設就把 `ssl = on` 開著，用的是 `ssl-cert-snakeoil` 這組自簽憑證。
**它能加密，但無法驗證身分**（用戶端只能用 `sslmode=require`，不能用 `verify-full`）。
換成自建 CA 簽的憑證：見 [[08-用自建CA簽發伺服器憑證]] 與 [[05-自簽憑證快速產生]]。

```ini
# /etc/postgresql/16/main/conf.d/zz-local.conf
ssl = on
ssl_cert_file = '/etc/postgresql/16/main/server.crt'
ssl_key_file  = '/etc/postgresql/16/main/server.key'
ssl_ca_file   = '/etc/postgresql/16/main/root.crt'      # 驗證用戶端憑證用
ssl_min_protocol_version = 'TLSv1.2'                    # ★★★ 稽核常見要求
```

> [!danger] ★★★★ 私鑰權限錯了服務會直接起不來
> ```bash
> sudo chown postgres:postgres /etc/postgresql/16/main/server.key
> sudo chmod 0600 /etc/postgresql/16/main/server.key
> ```
> 權限太寬時日誌會寫：
> ```text
> FATAL:  private key file "/etc/postgresql/16/main/server.key" has group or world access
> DETAIL: File must have permissions u=rw (0600) or less if owned by the database user
> ```
> ★★★ `ssl` 是 `sighup` context，**換憑證只要 reload，不用 restart**，可以在上班時間做。

用戶端憑證認證（不用密碼）：

```text
# pg_hba.conf —— cert 隱含 clientcert=verify-full，會拿憑證的 CN 比對角色名
hostssl  appdb  app  10.10.20.31/32  cert  map=certmap
```

```text
# pg_ident.conf
certmap   app01.example.gov.tw   app        # 憑證 CN → DB 角色
```

從用戶端測試：

```bash
psql "host=10.10.20.11 dbname=appdb user=app sslmode=verify-full \
      sslrootcert=/etc/ssl/certs/org-root.crt \
      sslcert=/etc/ssl/app01.crt sslkey=/etc/ssl/private/app01.key" -c "SELECT 1;"
```

預期輸出：

```text
 ?column?
----------
        1
(1 row)
```

### 七、`include` 系列（PostgreSQL 16 起）與規則模組化

PostgreSQL 16 讓 `pg_hba.conf` 與 `pg_ident.conf` 也能用 `include` 系列指令：

```text
# /etc/postgresql/16/main/pg_hba.conf 尾端
include_dir  'hba.d'
include_if_exists  'pg_hba.local.conf'
```

```bash
sudo install -d -o postgres -g postgres -m 0750 /etc/postgresql/16/main/hba.d
sudo install -o postgres -g postgres -m 0640 /dev/null /etc/postgresql/16/main/hba.d/10-app.conf
```

★★★★ 但要注意兩件事：

```
① include 進來的規則【依然參與同一條由上而下的比對鏈】。
   rule_number 會把所有檔案展平後連號 —— 用 pg_hba_file_rules 確認實際順序。
② include_dir 依【C locale 字典序】讀取，所以檔名前面要加數字：
   10-app.conf → 20-repl.conf → 90-reject.conf
   跟 Nginx 的 conf.d 是同一套心法。
```

> [!warning] ★★★ 版本相依
> `include` / `include_if_exists` / `include_dir` 在 `pg_hba.conf` 裡**是 PostgreSQL 16 才有的**。
> 在 15 或更舊的版本上寫，reload 會噴 `invalid connection type "include_dir"` 並且
> **整個 pg_hba.conf 載入失敗、繼續沿用舊規則**。動筆前先 `psql -c "SELECT version();"`。

### 八、`postgresql.conf` 的連線相關關鍵參數

```ini
# /etc/postgresql/16/main/conf.d/zz-local.conf

# ── 監聽 ────────────────────────────────────────────────
listen_addresses = '10.10.20.11, localhost'   # ★★★★ postmaster：改了要 restart
                                              # ★★★★ 不要寫 '*'，見安全性一節
port = 5432                                   # ★★★★ postmaster：改了要 restart

# ── 連線數 ──────────────────────────────────────────────
max_connections = 200                         # ★★★★ postmaster：改了要 restart
superuser_reserved_connections = 5            # ★★★ 保留給 DBA，滿載時還進得去

# ── 逾時（都是 sighup，reload 即可）─────────────────────
authentication_timeout = 30s                  # ★★ 認證階段的上限
idle_in_transaction_session_timeout = 60s     # ★★★★ 防止「開了交易就跑去吃飯」鎖住整張表
statement_timeout = 0                         # ★★★ 全域設 0，要限制請對特定 role 設
tcp_keepalives_idle = 60                      # ★★★ 中間有 NAT/防火牆時，防連線被默默砍掉
tcp_keepalives_interval = 10
tcp_keepalives_count = 6
```

> [!danger] ★★★★★ `max_connections` 不是越大越好
> PostgreSQL **一條連線 = 一個作業系統行程**（不像 MySQL 是執行緒）。
> ```
> 200 連線 × 每行程約 5~10 MB 基本開銷 = 1~2 GB，還不含 work_mem
> 最壞情況 ≈ shared_buffers + max_connections × (行程開銷 + work_mem × 排序節點數)
> ```
> ★★★★ 應用端請用連線池（Laravel 的 persistent connection、PgBouncer），
> **不要靠調大 `max_connections` 解決問題** —— 這和 [[04-MySQL-設定檔與調校]]
> 講 `max_connections` 的道理完全一樣，記憶體預算要加得起來。
> 詳細算法見 [[06-PostgreSQL-效能調校與索引]]。

改完之後確認哪些在等重啟：

```bash
sudo -u postgres psql -c \
  "SELECT name, setting, pending_restart FROM pg_settings WHERE pending_restart;"
```

預期輸出：

```text
      name        | setting | pending_restart
------------------+---------+-----------------
 listen_addresses | 10.10.20.11, localhost | t   # ★★★★ 還沒生效，要排重啟
(1 row)
```

### 九、日誌設定：排 `pg_hba` 問題的唯一入口 ★★★★

```ini
# /etc/postgresql/16/main/conf.d/zz-local.conf
logging_collector = on                        # ★★★★ postmaster：改了要 restart
log_destination = 'stderr'
log_line_prefix = '%m [%p] %q%u@%d from %h app=%a '   # ★★★★ 這一行決定你查不查得到人
log_connections = on                          # ★★★ 排錯時開，平時視流量決定
log_disconnections = off
log_min_messages = warning
log_min_error_statement = error
log_hostname = off                            # ★★★★ 開了會對每條連線做反解，很慢
```

`log_line_prefix` 的佔位符（機關稽核最少要有這幾個）：

| 佔位符 | 內容 | 星級 |
| --- | --- | --- |
| `%m` | 毫秒級時間戳 | ★★★ |
| `%p` | 行程 PID（同一條連線的所有日誌用它串起來） | ★★★★ |
| `%u` | 資料庫使用者 | ★★★★ |
| `%d` | 資料庫名 | ★★★ |
| `%h` | ★★★★ **來源主機 IP** —— 沒有這個就查不出是誰 | ★★★★ |
| `%a` | 應用程式名稱（用戶端的 `application_name`） | ★★★ |
| `%q` | ★★★ 分隔符：非連線相關的日誌會在這裡截斷 | ★★★ |

套用（`log_line_prefix` 是 `sighup`，reload 即可）：

```bash
sudo -u postgres psql -c "SELECT pg_reload_conf();"
sudo tail -n 3 /var/log/postgresql/postgresql-16-main.log
```

預期輸出：

```text
2026-08-28 15:41:02.331 CST [1284] LOG:  received SIGHUP, reloading configuration files
2026-08-28 15:41:02.334 CST [1284] LOG:  parameter "log_line_prefix" changed to "%m [%p] %q%u@%d from %h app=%a "
```

失敗連線長這樣（★★★★ 一眼就知道是誰、從哪、要連什麼）：

```text
2026-08-28 15:42:18.902 CST [4712] FATAL:  no pg_hba.conf entry for host "10.10.99.8", user "app", database "appdb", no encryption
```

日誌輪替與集中見 [[02-日誌集中與輪替]]。

### 十、★★★★ 改設定的安全流程（六步，一步都不能跳）

```
【1】記錄現況    SHOW hba_file; + pg_settings 的 source/sourcefile
【2】備份        cp 到帶時間戳的檔名（★★★★ 不是 .bak，是 .20260828-1541）
【3】改          只改 conf.d/zz-local.conf 或 pg_hba.conf，一次只改一件事
【4】套用        reload（或安排 restart 視窗）
【5】驗證        ① 日誌沒有 FATAL  ② pg_hba_file_rules 的 error 為空
                 ③ pg_settings 顯示新值  ④ 【從真正的用戶端連一次】
【6】回滾條件    驗證任一項不過 → 立刻 cp 回備份 + reload，不要 debug 到一半就下班
```

> [!danger] ★★★★★ 絕對不要在沒有第二條登入途徑時改 `pg_hba.conf`
> 如果你是 SSH 進去改的，先確認：
> ```bash
> sudo -u postgres psql -c "SELECT 1;"     # ★★★★ 本機 peer 這條路要活著
> ```
> 預期輸出：
> ```text
>  ?column?
> ----------
>         1
> (1 row)
> ```
> **只要 `local all postgres peer` 這一行還在，你就永遠救得回來。**
> 把它刪掉、又把遠端規則改壞，就只剩下停機重來一途。

---

## 完整實戰範例

### 情境

```
機關內部 LXMP 架構，資料庫獨立一台：

  ┌────────────────────┐        ┌────────────────────┐        ┌───────────────┐
  │ app01 10.10.20.31  │        │  db01 10.10.20.11  │◀──WAL──│ db02          │
  │ Nginx + PHP-FPM    │──5432─▶│  PostgreSQL 16     │        │ 10.10.20.12   │
  │ Laravel + Nuxt     │  SSL   │  appdb / app       │        │ 待命備援       │
  └────────────────────┘        └────────────────────┘        └───────────────┘
                                          ▲
                          辦公室網段 10.10.30.0/24（DBA 手動維護，需 SSL）

稽核要求（機關資安查核常見項目）：
  ① 不得有 trust 規則                              ★★★★★
  ② 不得有 0.0.0.0/0 的放行規則                    ★★★★
  ③ 遠端連線一律加密（禁止明文）                    ★★★★
  ④ 密碼一律 scram-sha-256                          ★★★★
  ⑤ 日誌需記錄來源 IP 與帳號，可回溯               ★★★★
  ⑥ 每次設定變更需有備份與回滾程序                  ★★★
```

### 目標規則表

| # | TYPE | DATABASE | USER | ADDRESS | METHOD | 為什麼 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `local` | `all` | `postgres` | —— | `peer` | ★★★★★ 救命通道，永遠不能刪 |
| 2 | `local` | `appdb` | `app` | —— | `peer map=svcmap` | 本機維運腳本免密碼 |
| 3 | `hostnossl` | `all` | `all` | `0.0.0.0/0` | `reject` | ★★★★ 擋掉所有明文 |
| 4 | `hostssl` | `appdb` | `app` | `10.10.20.31/32` | `scram-sha-256` | 只放行 app01 這一台 |
| 5 | `hostssl` | `replication` | `replicator` | `10.10.20.12/32` | `scram-sha-256` | ★★★ `all` 不含 replication |
| 6 | `hostssl` | `all` | `+dba_group` | `10.10.30.0/24` | `scram-sha-256` | DBA 群組，人員異動免改檔 |
| 7 | `host` | `all` | `all` | `all` | `reject` | ★★★ 明確收尾，日誌清楚 |

### 前置：建立角色與群組

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE dba_group NOLOGIN;
GRANT dba_group TO alice, bob;
SQL
```

角色與權限的完整做法見 [[02-PostgreSQL-角色與權限]]，這裡只做本篇需要的部分。

### 主角：`/usr/local/bin/pg-hba-apply.sh`

★★★★ 這支腳本解決 PostgreSQL 一個真實的痛點：**`pg_hba.conf` 沒有離線語法檢查**
（不像 `nginx -t`）。所以我們用「備份 → 套用 → reload → 驗證 → 錯了自動回滾」補上這個缺口。

```bash
sudo install -o root -g root -m 0750 /dev/null /usr/local/bin/pg-hba-apply.sh
sudo nano /usr/local/bin/pg-hba-apply.sh
```

```bash
#!/usr/bin/env bash
# pg-hba-apply.sh —— 安全套用 pg_hba.conf：備份、套用、reload、驗證、失敗自動回滾
# 用法： sudo pg-hba-apply.sh <新檔路徑> [叢集版本] [叢集名稱]
# 例：   sudo pg-hba-apply.sh /root/pg_hba.new 16 main
set -euo pipefail

NEW_FILE="${1:?用法: pg-hba-apply.sh <新檔路徑> [版本] [叢集名]}"
PGVER="${2:-16}"
PGCLUSTER="${3:-main}"

PGUSER_OS="postgres"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/var/backups/pg_hba"
PSQL=(sudo -u "$PGUSER_OS" psql -tAX)

log()  { printf '\033[1;34m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
ok()   { printf '\033[1;32m  ✔ %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  ✘ %s\033[0m\n' "$*" >&2; exit 1; }

# ── 【0】前置檢查 ──────────────────────────────────────────────────────
preflight() {
  log "【0】前置檢查"
  [[ $EUID -eq 0 ]] || die "必須用 root 執行（sudo）"
  [[ -f "$NEW_FILE" ]] || die "找不到新檔：$NEW_FILE"

  command -v pg_ctlcluster >/dev/null 2>&1 \
    || die "找不到 pg_ctlcluster（本腳本為 Debian/Ubuntu 版；RHEL 請改用 systemctl reload postgresql-$PGVER）"

  # ★★★★ 讓伺服器自己說 hba_file 在哪，不要用猜的
  HBA_FILE="$("${PSQL[@]}" -c 'SHOW hba_file;' 2>/dev/null)" \
    || die "連不上資料庫，無法取得 hba_file（伺服器沒起來？）"
  [[ -n "$HBA_FILE" ]] || die "取得的 hba_file 是空的"
  ok "目標檔案：$HBA_FILE"

  # ★★★★★ 救命通道檢查：新檔必須保留 local/postgres/peer，否則改壞就沒得救
  if ! grep -qE '^\s*local\s+all\s+postgres\s+peer' "$NEW_FILE"; then
    die "新檔缺少救命通道 'local all postgres peer'，拒絕套用"
  fi
  ok "救命通道存在"

  # ★★★★★ 稽核紅線：不得有 trust
  if grep -vE '^\s*#' "$NEW_FILE" | grep -qE '\btrust\b'; then
    die "新檔含有 trust 規則，違反稽核要求，拒絕套用"
  fi
  ok "無 trust 規則"

  # ★★★★ 稽核紅線：0.0.0.0/0 只允許出現在 reject 那一行
  if grep -vE '^\s*#' "$NEW_FILE" | grep -E '0\.0\.0\.0/0' | grep -qvE '\breject\b'; then
    die "新檔含有非 reject 的 0.0.0.0/0 放行規則，拒絕套用"
  fi
  ok "無全網放行規則"
}

# ── 【1】備份 ──────────────────────────────────────────────────────────
backup() {
  log "【1】備份現行設定"
  install -d -m 0750 -o root -g root "$BACKUP_DIR"
  BACKUP_FILE="$BACKUP_DIR/pg_hba.conf.$STAMP"
  cp -a "$HBA_FILE" "$BACKUP_FILE"
  ok "已備份到 $BACKUP_FILE"
}

# ── 【2】套用 ──────────────────────────────────────────────────────────
apply() {
  log "【2】套用新檔"
  # ★★★ 保留原本的 owner 與 mode（0640 postgres:postgres），不要用 mv
  install -o "$PGUSER_OS" -g "$PGUSER_OS" -m 0640 "$NEW_FILE" "$HBA_FILE"
  ok "已寫入 $HBA_FILE"

  log "【3】reload（pg_hba.conf 永遠只需要 reload）"
  pg_ctlcluster "$PGVER" "$PGCLUSTER" reload
  sleep 1
  ok "SIGHUP 已送出"
}

# ── 【4】驗證 ──────────────────────────────────────────────────────────
verify() {
  log "【4】驗證"
  local failed=0

  # 4-1 語法錯誤（★★★★ pg_reload_conf 回 t 不代表沒錯，一定要查這張 view）
  local errs
  errs="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL;")"
  if [[ "$errs" != "0" ]]; then
    printf '\n'
    sudo -u "$PGUSER_OS" psql -x -c \
      "SELECT file_name, line_number, error FROM pg_hba_file_rules WHERE error IS NOT NULL;"
    printf '  ✘ pg_hba_file_rules 有 %s 筆錯誤\n' "$errs" >&2
    failed=1
  else
    ok "pg_hba_file_rules 無錯誤"
  fi

  # 4-2 日誌是否出現載入失敗
  local logfile="/var/log/postgresql/postgresql-$PGVER-$PGCLUSTER.log"
  if [[ -f "$logfile" ]] && tail -n 30 "$logfile" | grep -q "could not load pg_hba.conf"; then
    printf '  ✘ 日誌出現 could not load pg_hba.conf\n' >&2
    failed=1
  else
    ok "日誌無載入失敗訊息"
  fi

  # 4-3 救命通道實測
  if "${PSQL[@]}" -c "SELECT 1;" >/dev/null 2>&1; then
    ok "本機 peer 連線正常"
  else
    printf '  ✘ 本機 peer 連線失敗\n' >&2
    failed=1
  fi

  # 4-4 稽核紅線再確認一次（這次是查已載入的規則，不是查檔案）
  local trusts
  trusts="$("${PSQL[@]}" -c "SELECT count(*) FROM pg_hba_file_rules WHERE auth_method = 'trust';")"
  if [[ "$trusts" != "0" ]]; then
    printf '  ✘ 已載入的規則中有 %s 條 trust\n' "$trusts" >&2
    failed=1
  else
    ok "已載入規則無 trust"
  fi

  return "$failed"
}

# ── 【5】回滾 ──────────────────────────────────────────────────────────
rollback() {
  log "【5】驗證失敗，自動回滾"
  install -o "$PGUSER_OS" -g "$PGUSER_OS" -m 0640 "$BACKUP_FILE" "$HBA_FILE"
  pg_ctlcluster "$PGVER" "$PGCLUSTER" reload
  sleep 1
  if "${PSQL[@]}" -c "SELECT 1;" >/dev/null 2>&1; then
    ok "已回滾到 $BACKUP_FILE，服務正常"
  else
    printf '  ✘✘ 回滾後仍異常，請立即人工介入：%s\n' "$BACKUP_FILE" >&2
  fi
  exit 1
}

main() {
  preflight
  backup
  apply
  if verify; then
    log "完成 ✔ 新規則已生效"
    printf '\n目前生效的規則：\n'
    sudo -u "$PGUSER_OS" psql -c \
      "SELECT rule_number, type, database, user_name, address, auth_method
         FROM pg_hba_file_rules ORDER BY rule_number;"
    printf '\n★★★★ 別忘了從【真正的應用主機】連一次，腳本驗不到那一段。\n'
  else
    rollback
  fi
}

main "$@"
```

### 準備新的 `pg_hba.conf`

```bash
sudo tee /root/pg_hba.new >/dev/null <<'HBA'
# =====================================================================
#  pg_hba.conf —— db01 (10.10.20.11) / PostgreSQL 16
#  維護：資訊室   最後修改：2026-08-28
#  ★★★★★ 規則由上而下比對，第一條命中即定案，沒有 fall-through。
#         新增規則時務必想清楚它會不會被上面某一行先攔走。
# =====================================================================
# TYPE       DATABASE      USER          ADDRESS           METHOD

# --- 本機救命通道（★★★★★ 永遠不要刪這一行）-------------------------
local        all           postgres                        peer

# --- 本機服務帳號（www-data → app，見 pg_ident.conf 的 svcmap）-------
local        appdb         app                             peer  map=svcmap

# --- ★★★★ 先擋掉所有明文連線，這一行必須在任何 host 規則之前 -------
hostnossl    all           all           0.0.0.0/0         reject
hostnossl    all           all           ::0/0             reject

# --- 應用主機 app01，只此一台 ----------------------------------------
hostssl      appdb         app           10.10.20.31/32    scram-sha-256

# --- 備援機的實體複寫（★★★ all 不含 replication，必須單獨寫）--------
hostssl      replication   replicator    10.10.20.12/32    scram-sha-256

# --- DBA 群組，從辦公室網段 -------------------------------------------
hostssl      all           +dba_group    10.10.30.0/24     scram-sha-256

# --- ★★★ 明確拒絕收尾：日誌會清楚寫出被擋的來源 ---------------------
host         all           all           all               reject
HBA
```

### 執行

```bash
sudo pg-hba-apply.sh /root/pg_hba.new 16 main
```

預期輸出：

```text
[16:02:11] 【0】前置檢查
  ✔ 目標檔案：/etc/postgresql/16/main/pg_hba.conf
  ✔ 救命通道存在
  ✔ 無 trust 規則
  ✔ 無全網放行規則
[16:02:11] 【1】備份現行設定
  ✔ 已備份到 /var/backups/pg_hba/pg_hba.conf.20260828-160211
[16:02:11] 【2】套用新檔
  ✔ 已寫入 /etc/postgresql/16/main/pg_hba.conf
[16:02:11] 【3】reload（pg_hba.conf 永遠只需要 reload）
  ✔ SIGHUP 已送出
[16:02:12] 【4】驗證
  ✔ pg_hba_file_rules 無錯誤
  ✔ 日誌無載入失敗訊息
  ✔ 本機 peer 連線正常
  ✔ 已載入規則無 trust
[16:02:13] 完成 ✔ 新規則已生效

 rule_number |   type    |   database    | user_name     |   address   |  auth_method
-------------+-----------+---------------+---------------+-------------+---------------
           1 | local     | {all}         | {postgres}    |             | peer
           2 | local     | {appdb}       | {app}         |             | peer
           3 | hostnossl | {all}         | {all}         | 0.0.0.0     | reject
           4 | hostnossl | {all}         | {all}         | ::          | reject
           5 | hostssl   | {appdb}       | {app}         | 10.10.20.31 | scram-sha-256
           6 | hostssl   | {replication} | {replicator}  | 10.10.20.12 | scram-sha-256
           7 | hostssl   | {all}         | {+dba_group}  | 10.10.30.0  | scram-sha-256
           8 | host      | {all}         | {all}         | all         | reject
(8 rows)

★★★★ 別忘了從【真正的應用主機】連一次，腳本驗不到那一段。
```

刻意寫錯來驗證回滾機制（★★★★ **一定要演練過一次**）：

```bash
sudo sed -i 's/^hostssl      appdb/hostsl      appdb/' /root/pg_hba.new
sudo pg-hba-apply.sh /root/pg_hba.new 16 main
```

預期輸出（節錄）：

```text
[16:05:40] 【4】驗證
-[ RECORD 1 ]------------------------------------------
file_name   | /etc/postgresql/16/main/pg_hba.conf
line_number | 18
error       | invalid connection type "hostsl"
  ✘ pg_hba_file_rules 有 1 筆錯誤
[16:05:41] 【5】驗證失敗，自動回滾
  ✔ 已回滾到 /var/backups/pg_hba/pg_hba.conf.20260828-160540，服務正常
```

### 從應用主機做最終驗證

```bash
# 在 app01 (10.10.20.31) 上執行
PGPASSWORD='***' psql "host=10.10.20.11 dbname=appdb user=app sslmode=verify-full \
  sslrootcert=/etc/ssl/certs/org-root.crt" \
  -c "SELECT current_user, inet_server_addr(), ssl_is_used() FROM pg_stat_ssl WHERE pid = pg_backend_pid();"
```

預期輸出：

```text
 current_user | inet_server_addr | ssl_is_used
--------------+------------------+-------------
 app          | 10.10.20.11      | t             # ★★★★ 加密確實生效
(1 row)
```

明文連線應該被擋（★★★ 驗證 `hostnossl reject` 有作用）：

```bash
psql "host=10.10.20.11 dbname=appdb user=app sslmode=disable" -c "SELECT 1;"
```

預期輸出：

```text
psql: error: connection to server at "10.10.20.11", port 5432 failed:
FATAL:  pg_hba.conf rejects connection for host "10.10.20.31", user "app", database "appdb", no encryption
```

★★★★ 注意這句是 `rejects connection`（有規則明確拒絕），
不是 `no pg_hba.conf entry`（沒規則）—— **兩句話代表不同的原因**。

### 驗收檢查表

| # | 檢查項 | 指令 | 預期結果 |
| --- | --- | --- | --- |
| 1 | ★★★★★ 救命通道還在 | `sudo -u postgres psql -c "SELECT 1;"` | 回 `1` |
| 2 | ★★★★ 無語法錯誤 | `psql -tAc "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL;"` | `0` |
| 3 | ★★★★★ 無 trust | `psql -tAc "SELECT count(*) FROM pg_hba_file_rules WHERE auth_method='trust';"` | `0` |
| 4 | ★★★★ 無全網放行 | `psql -tAc "SELECT count(*) FROM pg_hba_file_rules WHERE address='0.0.0.0' AND auth_method<>'reject';"` | `0` |
| 5 | ★★★★ 密碼全為 scram | `psql -tAc "SELECT count(*) FROM pg_authid WHERE rolcanlogin AND rolpassword LIKE 'md5%';"` | `0` |
| 6 | ★★★★ 應用連得上 | 在 app01 執行上面的 `psql ... sslmode=verify-full` | 回 `t` |
| 7 | ★★★★ 明文被擋 | 在 app01 執行 `sslmode=disable` | `pg_hba.conf rejects connection` |
| 8 | ★★★ 複寫連得上 | 在 db02 執行 `psql "host=10.10.20.11 user=replicator replication=database" -c "IDENTIFY_SYSTEM;"` | 回傳 systemid |
| 9 | ★★★ 監聽正確 | `ss -lntp \| grep 5432` | 只在 `10.10.20.11` 與 `127.0.0.1` |
| 10 | ★★★ 日誌有來源 IP | `sudo grep 'from 10\.' /var/log/postgresql/postgresql-16-main.log \| tail -3` | 有 `from <IP>` |
| 11 | ★★★ 備份存在 | `ls -l /var/backups/pg_hba/` | 有帶時間戳的檔案 |
| 12 | ★★★★ 回滾演練過 | 故意寫錯後執行腳本 | 自動回滾且服務正常 |

### 回滾方式

```bash
# ★★★ 腳本自動回滾失效時的人工回滾（30 秒內完成）
sudo ls -t /var/backups/pg_hba/ | head -5
sudo install -o postgres -g postgres -m 0640 \
  /var/backups/pg_hba/pg_hba.conf.20260828-160211 \
  /etc/postgresql/16/main/pg_hba.conf
sudo pg_ctlcluster 16 main reload
sudo -u postgres psql -c "SELECT 1;"
```

`postgresql.conf` 那邊的回滾：

```bash
# 如果是 ALTER SYSTEM 改壞的
sudo -u postgres psql -c "ALTER SYSTEM RESET listen_addresses;" \
                      -c "SELECT pg_reload_conf();"
# ★★★★ 全部清掉（核彈級，會清掉所有 ALTER SYSTEM 設過的值）
sudo -u postgres psql -c "ALTER SYSTEM RESET ALL;"
```

---

## 常見錯誤與排錯

| 現象 | 原因 | 解法 |
| --- | --- | --- |
| ★★★★ `FATAL: no pg_hba.conf entry for host "x.x.x.x", user "app", database "appdb", no encryption` | 一條規則都沒命中；或連線是明文而規則寫 `hostssl` | 用 `pg_hba_file_rules` 逐條核對四個欄位；訊息尾巴的 `no encryption` 表示要調用戶端 `sslmode` |
| ★★★★ 改了 `pg_hba.conf` 又 reload 了，行為完全沒變 | reload 時語法錯誤，伺服器**沿用舊規則**；或改到別的 cluster 的檔案 | `SHOW hba_file;` 確認路徑；`SELECT * FROM pg_hba_file_rules WHERE error IS NOT NULL;`；看日誌 `could not load pg_hba.conf` |
| ★★★★★ 改了 `postgresql.conf` 的 `listen_addresses` 卻沒生效，`ss` 看不到新位址 | ① 需要 **restart** 不是 reload；② 被 `postgresql.auto.conf` 蓋過 | `SELECT name,setting,source,sourcefile FROM pg_settings WHERE name='listen_addresses';` 看 `source`；必要時 `ALTER SYSTEM RESET listen_addresses;` |
| ★★★★ `FATAL: password authentication failed for user "app"` 但密碼確定正確 | 角色密碼還是 md5 格式，規則卻寫 `scram-sha-256` | `SELECT rolname FROM pg_authid WHERE rolpassword LIKE 'md5%';`，用 `\password` 重設 |
| ★★★★ `FATAL: Peer authentication failed for user "app"` | 走了 unix socket，`peer` 要求 OS 帳號名 == 角色名 | 加 `-h 127.0.0.1` 改走 TCP，或在 `pg_ident.conf` 建 map 並在規則加 `map=` |
| ★★★★ 應用連得上，DBA 從辦公室連不上（同一份規則） | 上面某一條較寬鬆的規則先命中了 DBA 的連線 | `log_connections = on` 後看 `connection authenticated ... (pg_hba.conf:NN)` 的行號 |
| ★★★★ 備援機複寫失敗：`no pg_hba.conf entry ... database "replication"` | `DATABASE` 欄的 `all` **不包含 replication** | 單獨加一行 `hostssl replication replicator 10.10.20.12/32 scram-sha-256` |
| ★★★ 連線 timeout（等很久才失敗），日誌**完全沒有紀錄** | 封包沒到伺服器 —— 防火牆或路由 | `nc -vz 10.10.20.11 5432`；查 `ufw status`、雲端 SG、實體防火牆（見 [[02-防火牆-ufw基礎與實務]]） |
| ★★★ `Connection refused`（瞬間失敗），日誌沒紀錄 | 服務沒起來，或 `listen_addresses` 沒含這個位址 | `systemctl status postgresql@16-main`；`ss -lntp \| grep 5432` |
| ★★★★★ 重啟後服務起不來：`FATAL: could not create lock file` / `has group or world access` | 設定檔或私鑰的 owner/mode 被改壞（常見於用 `mv` 搬檔） | `chown postgres:postgres`、`chmod 0640`（設定檔）/ `0600`（私鑰）；用 `install` 而不是 `mv` |
| ★★★ `FATAL: sorry, too many clients already` | 連線數達 `max_connections` | `SELECT count(*) FROM pg_stat_activity;` 找出來源；先靠 `superuser_reserved_connections` 進去，再處理連線池 |
| ★★★ `pg_hba.conf` 裡的 `include_dir` 讓 reload 整份失敗 | PostgreSQL 15 或更舊版本不支援 `pg_hba.conf` 的 include 指令 | `SELECT version();` 確認；15 以下把規則寫回單一檔案 |
| ★★★ `psql` 從遠端連線變得很慢（每次三、五秒） | `log_hostname = on` 或 ADDRESS 欄寫了主機名稱，觸發 DNS 反解 | 關掉 `log_hostname`、規則改用 IP/CIDR |
| ★★★★ 明明設了 `search_path` / `timezone` 卻對某個帳號無效 | 被 `ALTER ROLE/DATABASE ... SET` 覆蓋 | `psql -c "\drds"` 查出來，用 `ALTER ROLE app RESET search_path;` 清掉 |

### 排查步驟

**【1】確認你在改的是正確的檔案** ★★★★

```bash
sudo -u postgres psql -c "SHOW hba_file;" -c "SHOW config_file;"
```

預期輸出：

```text
                hba_file
------------------------------------------
 /etc/postgresql/16/main/pg_hba.conf
(1 row)
```

> 看到 `/var/lib/pgsql/16/data/pg_hba.conf` → 這是 RHEL 系佈局，你剛剛改的
> `/etc/postgresql/` 底下那份**根本沒人在讀**。
> 看到的版本號或 cluster 名與你改的不同 → 你改到別的 cluster 了，`pg_lsclusters` 對一下。

**【2】先分清楚是四道關卡的哪一關** ★★★★

從**應用主機**（不是資料庫主機）執行：

```bash
nc -vz 10.10.20.11 5432
```

- 看到 `Connection to 10.10.20.11 5432 port [tcp/postgresql] succeeded!`
  → **關卡【1】【2】都過了**，問題在 `pg_hba.conf` 或 `GRANT`，跳到【3】。
- 看到 `nc: connect to 10.10.20.11 port 5432 (tcp) failed: Connection refused`
  → **問題在【2】**：服務沒起來，或 `listen_addresses` 沒含這個位址。跳到【6】。
- 卡住很久才 `Connection timed out`
  → **問題在【1】防火牆**。跳到【7】。

**【3】看伺服器日誌怎麼說** ★★★★

```bash
sudo tail -n 40 /var/log/postgresql/postgresql-16-main.log
```

三種可能的預期輸出，對應三種完全不同的方向：

```text
FATAL:  no pg_hba.conf entry for host "10.10.20.31", user "app", database "appdb", no encryption
  → 【一條都沒命中】。跳到【4】。

FATAL:  pg_hba.conf rejects connection for host "10.10.20.31", user "app", database "appdb", no encryption
  → 【命中了 reject 那一行】。你的用戶端是明文，規則要求 SSL。跳到【8】。

FATAL:  password authentication failed for user "app"
  → 【命中了、方法對了、密碼錯】。跳到【5】。
```

★★★★ 如果日誌**什麼都沒有**，代表封包根本沒到 PostgreSQL —— 回到【2】。

**【4】沒有規則命中：逐欄核對** ★★★

```bash
sudo -u postgres psql -c \
  "SELECT rule_number, line_number, type, database, user_name, address, netmask, auth_method
     FROM pg_hba_file_rules ORDER BY rule_number;"
```

拿日誌那行 FATAL 的四個資訊（host / user / database / 加密與否）逐條比對：

```
FATAL 說：host=10.10.20.31  user=app  database=appdb  no encryption
                │              │           │              │
規則第 5 條：hostssl  appdb  app  10.10.20.31/32  scram-sha-256
                │                                  ▲
                └── ★★★★ type 是 hostssl，但連線【沒有加密】→ 不符合 → 不命中
```

**最常見的四個原因**（按出現頻率）：
① 用戶端 `sslmode=disable` 但規則寫 `hostssl`；
② 來源 IP 不在 CIDR 裡（NAT／多網卡／容器 bridge 造成的意外來源 IP）；
③ 資料庫名或角色名大小寫、拼字不同；
④ 複寫連線但規則只寫了 `all`。

**【5】密碼認證失敗：先確認雜湊格式** ★★★★

```bash
sudo -u postgres psql -tAc \
  "SELECT rolname, left(rolpassword, 14) FROM pg_authid WHERE rolname = 'app';"
```

預期輸出：

```text
app|SCRAM-SHA-256$        # ★ 正常
```

```text
app|md5a3f5c9d1e2b       # ★★★★ 規則寫 scram-sha-256 時，這個帳號一定登不進來
```

解法是 `sudo -u postgres psql -c "\password app"` 重設。見〈進階設定與調校〉第四節。

★★★ 若格式是對的，再確認是不是**用戶端連到了別台機器**：

```bash
psql "host=10.10.20.11 dbname=appdb user=app" -c "SELECT inet_server_addr(), current_database();"
```

**【6】`Connection refused`：確認在聽什麼** ★★★

```bash
ss -lntp | grep 5432
```

預期輸出：

```text
LISTEN 0  244  10.10.20.11:5432  0.0.0.0:*  users:(("postgres",pid=1284,fd=6))
LISTEN 0  244    127.0.0.1:5432  0.0.0.0:*  users:(("postgres",pid=1284,fd=7))
```

- **完全沒有輸出** → 服務沒起來：`systemctl status postgresql@16-main` 與日誌。
- **只有 `127.0.0.1:5432`** → `listen_addresses` 沒含對外位址。改完 ★★★★ **要 restart 不是 reload**。
- **有對外位址但仍 refused** → 你連的 port 不對，或連到另一個 cluster（5433）。

**【7】timeout：確認防火牆** ★★★

在資料庫主機上：

```bash
sudo ufw status numbered
```

預期輸出：

```text
     To                         Action      From
     --                         ------      ----
[ 1] 5432/tcp                   ALLOW IN    10.10.20.31                # ★★★ 只放行 app01
[ 2] 5432/tcp                   ALLOW IN    10.10.30.0/24
```

★★★★ 沒有這些規則就是防火牆擋的。加規則的做法見 [[02-防火牆-ufw基礎與實務]]。
如果 `ufw` 是 inactive，就往上游查交換器 ACL 或雲端安全群組。

**【8】被 `reject` 擋掉：確認用戶端的 `sslmode`** ★★★

```bash
psql "host=10.10.20.11 dbname=appdb user=app sslmode=require" -c "SELECT ssl_is_used();"
```

預期輸出：

```text
 ssl_is_used
-------------
 t
(1 row)
```

換成 `sslmode=require` 就能連 → 確認是加密與否的問題，去改應用端的連線字串
（Laravel 在 `config/database.php` 的 `sslmode`，Node.js `pg` 在 `ssl: { rejectUnauthorized: true, ca: ... }`）。

**【9】改完都對，但只有某些連線失敗** ★★★★

打開行號日誌，讓伺服器直接告訴你命中哪一行：

```bash
sudo -u postgres psql -c "ALTER SYSTEM SET log_connections = 'on';" \
                      -c "SELECT pg_reload_conf();"
sudo tail -f /var/log/postgresql/postgresql-16-main.log
```

預期輸出：

```text
LOG:  connection authenticated: identity="alice" method=scram-sha-256 (/etc/postgresql/16/main/pg_hba.conf:26)
```

★★★★ 括號裡的 `:26` 就是命中的行號。如果它不是你以為的那一行，
代表**上面有一條規則先攔走了**，把那一行改窄或往下移。

查完記得關掉：

```bash
sudo -u postgres psql -c "ALTER SYSTEM RESET log_connections;" -c "SELECT pg_reload_conf();"
```

---

## 安全性注意事項

> [!danger] ★★★★★ 絕對禁止：`pg_hba.conf` 裡出現 `trust`
> ```text
> host  all  all  0.0.0.0/0  trust        # ★★★★★ 全世界都能以 postgres 身分登入
> ```
> 後果不是「密碼被猜到」，是**根本不需要密碼**。攻擊者拿到的是超級使用者，
> 可以 `COPY ... FROM PROGRAM` 執行任意 OS 指令、可以讀走整個資料庫。
> 這在機關資安查核是**立即列為重大缺失**的項目。
> 唯一例外是救援流程中的那 30 秒，而且必須立刻還原。

> [!danger] ★★★★★ 絕對禁止：`ALTER ROLE app PASSWORD '明文密碼';`
> ```
> 這一行明文密碼會出現在：
>   ① ~/.psql_history           ← 檔案權限 0600，但備份、rsync 一起帶走
>   ② PostgreSQL 的 SQL 日誌（若開了 log_statement = 'ddl' 或 'all'）
>   ③ pg_stat_activity 的 query 欄（其他 DBA 當下看得到）
>   ④ shell history（如果是 psql -c 下的）
> ```
> **一律用 `\password <角色>`** —— 它在用戶端算好雜湊才送出，
> 上面四個地方都只會看到 `ALTER ROLE app PASSWORD 'SCRAM-SHA-256$4096:...'`。

> [!danger] ★★★★ 絕對禁止：`listen_addresses = '*'`
> 這會綁到機器上**每一個**網卡，包含管理網段、DMZ、容器的 bridge。
> 你以為只開了內網，實際上連 IPv6 的 global address 都在聽。
> ```ini
> listen_addresses = '10.10.20.11, localhost'   # ★★★★ 明確列出來
> ```
> 用 `ss -lntp | grep 5432` 確認實際綁了什麼，**不要相信設定檔上寫什麼**。

> [!danger] ★★★★ 絕對禁止：讓 `postgres` 超級使用者能從網路登入
> ```text
> hostssl  all  postgres  10.10.0.0/16  scram-sha-256      # ★★★★ 不要
> ```
> `postgres` 只保留 `local ... peer`。需要遠端做 DBA 工作的人，
> 建立具名的個人角色並 `GRANT pg_read_all_data` 之類的預定義角色，
> 這樣**稽核軌跡才有「是誰做的」**。共用超級帳號在個資稽核上是不可接受的
> （見 [[07-台灣資安法規與個資法]]）。

> [!warning] ★★★★ 個資與稽核軌跡的最低要求
> 個人資料保護法要求「對個人資料檔案採行適當之安全維護措施」，
> 落到資料庫設定檔上至少是這四項（★★★ 不要編條號，寫措施就好）：
>
> | 要求 | 對應設定 |
> | --- | --- |
> | ★★★★ 存取來源可控 | `pg_hba.conf` 用 `/32` 或明確網段，禁止 `0.0.0.0/0` |
> | ★★★★ 傳輸加密 | `hostnossl ... reject` + `hostssl ...`，`ssl_min_protocol_version = 'TLSv1.2'` |
> | ★★★★ 可回溯到人 | `log_line_prefix` 含 `%u %h`；禁用共用帳號；`log_connections = on` |
> | ★★★ 設定變更留痕 | 設定檔納入版控或帶時間戳備份到 `/var/backups/pg_hba/` |
>
> 更完整的稽核設定（`pgaudit`、資料表層級的存取記錄）在 [[08-PostgreSQL-安全強化]]。

> [!warning] ★★★ 設定檔本身就是機敏資料
> `pg_hba.conf` 洩漏出去等於把「哪些 IP 進得來、用什麼認證」整張地圖交出去。
> ```bash
> sudo chown postgres:postgres /etc/postgresql/16/main/pg_hba.conf
> sudo chmod 0640 /etc/postgresql/16/main/pg_hba.conf
> ```
> ★★★ 納入 git 版控時記得：**設定檔可以進版控，`.pgpass` 與私鑰不可以**。

> [!warning] ★★★ `log_connections` 的兩面性
> 開著能查到誰連進來，但每條連線三行日誌。一台每秒 200 次短連線的機器，
> 一天會產生數 GB 的日誌，**把 `/var` 寫滿之後 PostgreSQL 會拒絕新連線**。
> 平時的折衷：`log_connections = on` + `log_disconnections = off` + 確實的
> `logrotate`（見 [[02-日誌集中與輪替]]），或改用 `pgaudit` 做選擇性記錄。

---

## 速查表

### 檔案路徑

| 項目 | Ubuntu/Debian | RHEL（PGDG） | 星級 |
| --- | --- | --- | --- |
| 主設定 | `/etc/postgresql/16/main/postgresql.conf` | `/var/lib/pgsql/16/data/postgresql.conf` | ★★★ |
| 認證 | `/etc/postgresql/16/main/pg_hba.conf` | `/var/lib/pgsql/16/data/pg_hba.conf` | ★★★★ |
| 身分對映 | `/etc/postgresql/16/main/pg_ident.conf` | `/var/lib/pgsql/16/data/pg_ident.conf` | ★★ |
| ALTER SYSTEM | `/var/lib/postgresql/16/main/postgresql.auto.conf` | `/var/lib/pgsql/16/data/postgresql.auto.conf` | ★★★★ |
| 我們的覆寫檔 | `/etc/postgresql/16/main/conf.d/zz-local.conf` | 自建 `conf.d/` 並加 `include_dir` | ★★★ |
| 日誌 | `/var/log/postgresql/postgresql-16-main.log` | `/var/lib/pgsql/16/data/log/*.log` | ★★★★ |

### 確認實際值（★★★★ 這四行值得背下來）

| 目的 | 指令 |
| --- | --- |
| ★★★★ 設定檔在哪 | `psql -c "SHOW config_file;" -c "SHOW hba_file;"` |
| ★★★★ 值從哪來 | `psql -x -c "SELECT name,setting,source,sourcefile,sourceline FROM pg_settings WHERE name='X';"` |
| ★★★★ 誰在等重啟 | `psql -c "SELECT name,setting FROM pg_settings WHERE pending_restart;"` |
| ★★★★ hba 有沒有錯 | `psql -c "SELECT * FROM pg_hba_file_rules WHERE error IS NOT NULL;"` |
| ★★★ 角色/DB 層級覆寫 | `psql -c "\drds"` |
| ★★★ ident 對映 | `psql -c "SELECT * FROM pg_ident_file_mappings;"` |

### 套用設定

| 動作 | 指令 | 適用 |
| --- | --- | --- |
| ★★★★ reload（SQL） | `SELECT pg_reload_conf();` | `pg_hba.conf`、所有 `sighup` 參數 |
| ★★★ reload（Debian） | `sudo pg_ctlcluster 16 main reload` | 同上 |
| ★★★ reload（systemd） | `sudo systemctl reload postgresql@16-main` | 同上 |
| ★★★★ restart | `sudo pg_ctlcluster 16 main restart` | `postmaster` 參數，**會斷線** |
| ★★★ 全部 cluster | `sudo systemctl restart postgresql` | ★★★★ 小心，會重啟這台所有 cluster |
| ★★★ 清掉 auto.conf 某項 | `ALTER SYSTEM RESET <參數>;` + reload | 修 `postgresql.auto.conf` |

### `pg_hba.conf` 欄位

| 欄 | 常用值 | 易錯點 |
| --- | --- | --- |
| TYPE | `local` `host` `hostssl` `hostnossl` | ★★★★ `local` 沒有 ADDRESS 欄 |
| DATABASE | `all` `appdb` `replication` `sameuser` | ★★★★ `all` **不含** `replication` |
| USER | `all` `app` `+group` `/regex` | ★★★ `+` 會遞迴展開 role 成員 |
| ADDRESS | `10.0.0.5/32` `10.0.0.0/24` `samenet` | ★★★★ 別用主機名（DNS 依賴） |
| METHOD | `scram-sha-256` `peer` `cert` `reject` | ★★★★★ 絕不用 `trust` |
| OPTIONS | `map=` `clientcert=` `ldap*=` | ★★★ `cert` 已隱含 `clientcert=verify-full` |

### 認證方式決策

| 情境 | 用這個 | 星級 |
| --- | --- | --- |
| 同一台機器上的維運腳本 | `peer` | ★★★★ |
| 同一台機器但 OS 帳號名不同（`www-data`） | `peer map=svcmap` | ★★★★ |
| 跨主機的應用連線 | `hostssl` + `scram-sha-256` | ★★★★ |
| 跨主機且要最高保證 | `hostssl` + `cert` + `map=` | ★★★ |
| 集中帳號（AD／LDAP） | `ldap` 或 `gss` | ★★★ |
| 無法升級的老舊應用 | `md5`（單一 IP、單一角色，列管風險） | ★★★★ |
| 任何情況 | ★★★★★ **不要用 `trust` 或 `password`** | ★★★★★ |

### 判斷準則

| 看到 | 代表 | 先查 |
| --- | --- | --- |
| ★★★★ `no pg_hba.conf entry` | 一條都沒命中 | `pg_hba_file_rules` 逐欄核對 |
| ★★★★ `rejects connection` | 命中了 `reject` | 用戶端 `sslmode` |
| ★★★★ `password authentication failed` | 命中了，密碼／雜湊格式不對 | `pg_authid.rolpassword` 前綴 |
| ★★★ `Peer authentication failed` | 走 socket 且 OS 帳號 ≠ 角色 | 加 `-h 127.0.0.1` 或設 `map=` |
| ★★★★ `permission denied for ...` | **已經連進來了** | `GRANT`，不是 `pg_hba.conf` |
| ★★★ `Connection refused`（秒回） | 沒在聽 | `ss -lntp \| grep 5432` |
| ★★★ `Connection timed out`（很慢） | 防火牆 | `nc -vz`、`ufw status` |
| ★★★★ 改了完全沒反應 | 語法錯／改錯檔／被 auto.conf 蓋 | 日誌 + `pg_settings.source` |

---

## 練習題

> [!question]- 練習 1：把一份危險的 `pg_hba.conf` 改安全（★★★★）
> 你接手一台機關的 PostgreSQL 16，`pg_hba.conf` 的有效行如下：
> ```text
> local  all  all                     trust
> host   all  all  0.0.0.0/0          md5
> host   appdb  app  10.10.20.31/32   scram-sha-256
> host   replication  all  0.0.0.0/0  trust
> ```
> 請：① 指出四個問題各自的風險等級；② 寫出改寫後的版本；
> ③ 說明為什麼原本第 3 行「其實從來沒有生效過」。
>
> **參考解答**
>
> ① 風險盤點：
> | 行 | 問題 | 等級 |
> | --- | --- | --- |
> | 1 | `local all all trust` —— 任何 OS 使用者都能以任何 DB 角色登入，包含 `postgres` | ★★★★★ |
> | 2 | `0.0.0.0/0` + `md5` —— 全網開放，且雜湊等同密碼 | ★★★★★ |
> | 3 | 本身沒問題，但**永遠讀不到**（第 2 行先命中） | ★★★★ |
> | 4 | 複寫全網 `trust` —— 任何人都能拉走整份資料 | ★★★★★ |
>
> ② 改寫：
> ```text
> local      all          postgres                       peer
> local      all          all                            peer
> hostnossl  all          all           0.0.0.0/0        reject
> hostssl    appdb        app           10.10.20.31/32   scram-sha-256
> hostssl    replication  replicator    10.10.20.12/32   scram-sha-256
> hostssl    all          +dba_group    10.10.30.0/24    scram-sha-256
> host       all          all           all              reject
> ```
> ③ 因為 `pg_hba.conf` 是**由上而下、第一條命中即定案**。
> 來自 `10.10.20.31` 的連線在第 2 行（`host all all 0.0.0.0/0 md5`）就四欄全中了，
> 伺服器直接用 `md5` 認證，**根本不會讀到第 3 行**。
> ★★★★ 這也解釋了為什麼「加了 scram 規則但使用者還是被要求 md5 密碼」。
> 改完後用 `SELECT rule_number, ... FROM pg_hba_file_rules ORDER BY rule_number;` 確認順序。

> [!question]- 練習 2：判斷 reload 還是 restart（★★★★）
> 下列六項變更，各自需要 reload 還是 restart？請寫出你**用什麼指令查證**，
> 而不是憑印象回答。
> ① 把 `listen_addresses` 從 `localhost` 改成 `10.10.20.11, localhost`
> ② 在 `pg_hba.conf` 新增一條 `hostssl` 規則
> ③ 換掉過期的伺服器憑證（`ssl_cert_file`）
> ④ 把 `max_connections` 從 100 調到 200
> ⑤ 把 `log_line_prefix` 加上 `%h`
> ⑥ 在 `pg_ident.conf` 新增一組 map
>
> **參考解答**
>
> 查證指令（★★★★ 這才是重點）：
> ```bash
> sudo -u postgres psql -c \
>   "SELECT name, context FROM pg_settings
>      WHERE name IN ('listen_addresses','ssl_cert_file','max_connections','log_line_prefix');"
> ```
> | 變更 | 需要 | 依據 |
> | --- | --- | --- |
> | ① `listen_addresses` | ★★★★ **restart** | `context = postmaster` |
> | ② `pg_hba.conf` | reload | ★★★★ 認證檔**永遠**只需 reload，不在 `pg_settings` 裡 |
> | ③ `ssl_cert_file` | reload | `context = sighup`，★★★ 換憑證可在上班時間做 |
> | ④ `max_connections` | ★★★★ **restart** | `context = postmaster` |
> | ⑤ `log_line_prefix` | reload | `context = sighup` |
> | ⑥ `pg_ident.conf` | reload | 同 ②，認證相關檔案 |
>
> 改完 ① ④ 之後，用這行確認它們確實在等重啟：
> ```bash
> sudo -u postgres psql -c "SELECT name, setting FROM pg_settings WHERE pending_restart;"
> ```
> 排到維護視窗再 `sudo pg_ctlcluster 16 main restart`。
> ★★★★ **restart 會斷掉所有現有連線**，Laravel 會噴一批 500，一定要排時間。

> [!question]- 練習 3：設計一次 md5 → scram 的遷移（★★★★）
> 一個機關有 12 個登入角色，其中 3 個是 2019 年建的老 VB6 報表程式在用（ODBC 驅動很舊）。
> 請寫出遷移的完整步驟順序，並說明「如果那 3 個角色的驅動不支援 scram，你怎麼收尾」。
>
> **參考解答**
>
> 步驟順序（★★★★★ **順序反了會直接造成服務中斷**）：
> ```
> 【1】盤點：SELECT rolname, rolpassword LIKE 'md5%' FROM pg_authid WHERE rolcanlogin;
> 【2】測試：先在測試機把一個角色轉 scram，讓老 ODBC 連連看 → 這一步決定後面的路
> 【3】確認 password_encryption = 'scram-sha-256'（reload 即可）
> 【4】通知：告知各系統窗口重設密碼的時間窗
> 【5】逐一 \password 重設 9 個能升級的角色（★★★ 不要用 ALTER ROLE ... PASSWORD '明文'）
> 【6】驗證 SELECT count(*) ... rolpassword LIKE 'md5%' 只剩下那 3 個
> 【7】最後才改 pg_hba.conf，reload
> 【8】從真正的用戶端逐一實測
> ```
> 收尾方式：**不要為了 3 個角色讓全庫留在 md5**。
> 把例外縮到最小 —— 單一角色、單一來源 IP、單一資料庫：
> ```text
> hostssl  reportdb  vb6_report  10.10.40.7/32  md5    # ★★★★ 已知風險，列管至 2026-12 汰換
> hostssl  all       all         10.10.20.0/24  scram-sha-256
> ```
> 並且要做三件事：① 在資安風險清單上列管並訂汰換期限；
> ② 該角色只給唯讀權限（`GRANT SELECT`，見 [[02-PostgreSQL-角色與權限]]）；
> ③ `hostssl` 至少保證傳輸加密，md5 雜湊不會在網路上被側錄。
> ★★★★ 稽核時「有列管、有期限、有補償控制」和「沒發現」是完全不同的結果。

---

## 小測驗

Q1. 用一句話說明 `pg_hba.conf` 的比對規則。接著解釋：為什麼「在檔案最下面加一條 `trust` 當備援」是完全無效的做法？

Q2. **是非題**：`pg_hba.conf` 的 `DATABASE` 欄寫 `all` 就涵蓋了所有連線，包含備援機的複寫連線。請說明理由。

Q3. 「這行指令會發生什麼」：
```bash
sudo -u postgres psql -c "SELECT pg_reload_conf();"
```
回傳 `t`。這代表你的 `pg_hba.conf` 修改成功了嗎？如果不是，你還要做哪兩件事？

Q4. **選擇題**：你在應用主機執行 `psql`，等了約 20 秒後看到 `Connection timed out`，而資料庫主機的日誌**一行相關紀錄都沒有**。問題最可能在哪？
(A) `pg_hba.conf` 沒有對應規則 (B) 密碼錯誤 (C) 防火牆／路由 (D) `GRANT` 沒給

Q5. 「看到這個錯誤該先查哪裡」：`ERROR: permission denied for table members`。請說明你的第一個動作，以及**為什麼去改 `pg_hba.conf` 是浪費時間**。

Q6. 你把 `listen_addresses` 從 `localhost` 改成 `10.10.20.11, localhost`，reload 之後 `ss -lntp | grep 5432` 仍然只看到 `127.0.0.1`。請列出**兩個**可能原因，以及各自的查證指令。

Q7. **簡答**：`peer` 與 `ident` 的信任來源分別是什麼？為什麼 `ident` 在正式環境幾乎不該被使用？

Q8. 一個角色的密碼確定沒打錯，但登入時一直是 `FATAL: password authentication failed`。請寫出你會下的**第一個 SQL**，並說明看到什麼輸出代表什麼。

Q9. 說明 `cert` 認證方式隱含的 `clientcert` 值是什麼，以及當憑證的 CN 和資料庫角色名不一樣時該怎麼處理。

Q10. 你接手一台機器，`postgresql.conf` 裡明明寫著 `log_connections = on`，但重啟後日誌完全沒有連線紀錄。請列出你的排查順序（至少三步），並寫出關鍵的那一行查詢。

> [!question]- 測驗答案
> **Q1.** 規則是：**由上而下逐行比對 TYPE / DATABASE / USER / ADDRESS 四個欄位，
> 第一條四欄全中的規則決定用哪種認證方式；用它認證失敗也不會往下找；
> 讀完全部都沒命中就拒絕連線。**
> 官方文件的原文是「沒有 fall-through 或 backup」。
> 所以「在最下面加一條 `trust` 當備援」無效的原因是：
> ```
> 上面那條規則一旦命中 → 認證失敗 → 【直接 FATAL】
> 下面的 trust 規則永遠不會被讀到
> ```
> ★★★★★ 而且這條 `trust` 對**沒被上面規則命中的連線**是有效的，
> 等於開了一個你不知道的後門，稽核時是重大缺失。
> 真正的備援是保留 `local all postgres peer` 這條本機通道。見〈觀念說明〉。
>
> **Q2.** **非（錯誤）**。
> `all` 在 `DATABASE` 欄是明文規定的例外：**它不匹配實體複寫連線**。
> 原因是實體複寫連線在協定層不指定任何資料庫（`replication=true` 的啟動封包），
> 所以必須用專屬關鍵字：
> ```text
> hostssl  replication  replicator  10.10.20.12/32  scram-sha-256
> ```
> ★★★★ 沒寫這一行時，備援機拿到的錯誤是
> `no pg_hba.conf entry for host "10.10.20.12", user "replicator", database "replication"`，
> 訊息裡的 `database "replication"` 就是線索。
> ★★★ 另外要分清楚：**邏輯複寫走的是一般資料庫連線**，
> 吃的是真正的資料庫名，不是 `replication` 關鍵字。見〈進階設定與調校〉第一節與 [[07-PostgreSQL-複寫與高可用]]。
>
> **Q3.** **不代表成功。** `pg_reload_conf()` 回傳 `t` 只表示 **SIGHUP 訊號送出去了**，
> 完全不代表新設定通過解析。
> ★★★★★ 如果 `pg_hba.conf` 有語法錯誤，伺服器會**保留舊規則繼續服務**，
> 只在日誌留一行 `FATAL: could not load pg_hba.conf`，
> 而你的 `psql` 看到的是漂亮的 `t` —— 這是最惡毒的一種假成功。
> 還要做的兩件事：
> ```bash
> # ① 看日誌尾巴
> sudo tail -n 20 /var/log/postgresql/postgresql-16-main.log
> # ② 查已載入規則的錯誤欄（★★★★ 這才是決定性證據）
> sudo -u postgres psql -c "SELECT file_name, line_number, error
>                             FROM pg_hba_file_rules WHERE error IS NOT NULL;"
> ```
> 第 ② 行回 `(0 rows)` 才算通過。見〈基礎設定：reload 之後的兩個必做驗證〉。
>
> **Q4.** **(C) 防火牆／路由。**
> 判斷依據是兩個特徵**同時成立**：
> ```
> 特徵一：等很久（TCP SYN 重送到逾時）才失敗 → 封包被【默默丟棄】(DROP)
>         如果是 REJECT 或服務沒起來，會【瞬間】回 Connection refused
> 特徵二：資料庫主機日誌【完全沒有紀錄】→ 封包根本沒到 PostgreSQL 行程
> ```
> ★★★★ 只要日誌沒有任何紀錄，`pg_hba.conf`（A）和 `GRANT`（D）就一定不是原因，
> 因為那兩關都在 PostgreSQL 行程內、都會留下日誌。(B) 密碼錯誤會秒回 FATAL。
> 查證：在應用主機 `nc -vz 10.10.20.11 5432`，在資料庫主機 `sudo ufw status numbered`。
> 見〈排查步驟【2】【7】〉與 [[02-防火牆-ufw基礎與實務]]。
>
> **Q5.** 第一個動作是 **確認目前的身分與該物件的權限**：
> ```bash
> psql -d appdb -c "SELECT current_user, session_user;" \
>                -c "\dp members"
> ```
> ★★★★★ 去改 `pg_hba.conf` 是浪費時間，因為 `permission denied for table` 這個錯誤
> **只有在你已經成功通過認證、已經在資料庫裡面的時候才會出現**。
> ```
> 【3】pg_hba 認證  ← 已經過了，不然你連 SQL 都送不出去
> 【4】GRANT 授權   ← 問題在這一關
> ```
> 正確方向是 `GRANT SELECT ON members TO app;` 或檢查 schema 的 `USAGE` 權限、
> 以及 `ALTER DEFAULT PRIVILEGES` 有沒有設對。
> ★★★ 這是本篇〈觀念說明〉那張四關卡圖最想避免的鬼打牆。詳見 [[02-PostgreSQL-角色與權限]]。
>
> **Q6.** 兩個原因與查證：
> **原因一：`listen_addresses` 是 `postmaster` context，reload 不夠，必須 restart。**
> ```bash
> sudo -u postgres psql -c "SELECT name, setting, pending_restart
>                             FROM pg_settings WHERE name='listen_addresses';"
> ```
> `pending_restart = t` 就是這個原因，排維護視窗 `sudo pg_ctlcluster 16 main restart`。
> **原因二：被 `postgresql.auto.conf` 蓋過（有人下過 `ALTER SYSTEM SET`）。**
> ```bash
> sudo -u postgres psql -x -c "SELECT name, setting, source, sourcefile
>                                FROM pg_settings WHERE name='listen_addresses';"
> ```
> `sourcefile` 指向 `postgresql.auto.conf` 就是這個原因，
> ★★★★ 用 `ALTER SYSTEM RESET listen_addresses;` 清掉再重啟。
> 見〈觀念說明：設定檔家族〉與〈排查步驟【6】〉。
>
> **Q7.** 信任來源：
> ```
> peer  → 【伺服器自己】透過 OS 核心（SO_PEERCRED）查出 unix socket 對端行程的 UID
>          ★★★★ 這個資訊【無法偽造】，因為是核心給的，只適用 local 連線
> ident → 去問【用戶端主機】上的 identd 服務「這條連線是誰開的」
>          ★★★★★ 信任的是【對方主機的自我宣告】
> ```
> `ident` 不該用於正式環境的理由：
> ① 攻擊者只要控制用戶端主機（或架一台假的 identd），就能宣稱自己是任何人；
> ② identd 是 RFC 1413 的老協定，現代 Linux 預設根本沒裝；
> ③ 每次連線多一次到用戶端的網路往返，慢且會受防火牆影響。
> ★★★★ 需要「免密碼但可信」的跨主機認證，正解是 `cert`（憑證）或 `gss`（Kerberos）。
> 見〈進階設定與調校〉第三節的選型表。
>
> **Q8.** 第一個 SQL 是**檢查密碼的雜湊格式**：
> ```bash
> sudo -u postgres psql -tAc \
>   "SELECT rolname, left(rolpassword, 14) FROM pg_authid WHERE rolname = 'app';"
> ```
> 兩種輸出、兩種意義：
> ```text
> app|SCRAM-SHA-256$   → ★★ 格式正確，問題在別處：密碼真的錯了、
>                          或用戶端連到了另一台機器／另一個 cluster（用 inet_server_addr() 確認）
> app|md5a3f5c9d1e2b   → ★★★★ 找到了：規則寫 scram-sha-256，但這個角色還是 md5 雜湊，
>                          兩者協定不相容，密碼再對也一定失敗
> ```
> 解法是 `sudo -u postgres psql -c "\password app"` 重設（★★★★ 用 `\password`，
> 不要用 `ALTER ROLE ... PASSWORD '明文'`，理由見〈安全性注意事項〉）。
> 這是從舊版升級上來的資料庫最常見的一個坑。見〈進階設定與調校〉第四節。
>
> **Q9.** `cert` 隱含 **`clientcert=verify-full`**，意思是：
> ```
> ① 必須是 SSL 連線（所以只能寫在 hostssl 規則上）
> ② 用戶端必須提供憑證，且該憑證要能被 ssl_ca_file 驗證通過
> ③ ★★★★ 憑證的 CN 必須【等於】連線宣稱的資料庫角色名
> ```
> 因為 ③ 的關係，明確寫 `clientcert=verify-full` 是多餘的。
> CN 和角色名不一樣時（很常見 —— 憑證 CN 通常是主機名 `app01.example.gov.tw`，
> 角色名是 `app`），用 `map=` 搭配 `pg_ident.conf`：
> ```text
> # pg_hba.conf
> hostssl  appdb  app  10.10.20.31/32  cert  map=certmap
> # pg_ident.conf     MAPNAME  SYSTEM-USERNAME(CN)     PG-USERNAME
> certmap   app01.example.gov.tw   app
> ```
> ★★★ 用 `SELECT * FROM pg_ident_file_mappings;` 確認 map 有被正確解析。
> 憑證怎麼簽發見 [[08-用自建CA簽發伺服器憑證]]。見〈進階設定與調校〉第六節。
>
> **Q10.** 排查順序（★★★★ 順序本身就是重點：先確認「檔案有沒有人讀」再看內容）：
> ```
> 【1】確認伺服器讀的是不是這個檔案 —— 可能有多個 cluster
>      sudo -u postgres psql -c "SHOW config_file;"
>      → 路徑和你改的不同 → 你改錯 cluster 了（pg_lsclusters 對一下）
>
> 【2】★★★★ 查實際生效值與來源 —— 這是關鍵的一行
>      sudo -u postgres psql -x -c "SELECT name, setting, source, sourcefile, sourceline
>                                     FROM pg_settings WHERE name='log_connections';"
>      → setting=off 且 sourcefile 指向 postgresql.auto.conf
>        代表有人下過 ALTER SYSTEM SET log_connections='off'，它贏過 postgresql.conf
>        解法：ALTER SYSTEM RESET log_connections; 再 reload
>      → setting=on 但你看不到日誌 → 跳【3】
>
> 【3】確認日誌到底寫到哪裡去了
>      sudo -u postgres psql -c "SHOW log_destination;" -c "SHOW logging_collector;"
>      → logging_collector=off 時日誌走 stderr，被 systemd 收走：
>        sudo journalctl -u postgresql@16-main --since '10 min ago'
>      → logging_collector=on 時看 SHOW log_directory / log_filename 指的位置
> ```
> ★★★ 還有一個常被忽略的可能：`log_min_messages` 被調到 `error` 以上，
> 把 `LOG` 等級的訊息全濾掉了。見〈進階設定與調校〉第九節與〈基礎設定：確認實際值〉。

---

## 延伸閱讀

- [[02-PostgreSQL-角色與權限]] —— ★★★★ 本篇管「連不連得進來」，那篇管「進來能做什麼」。看到 `permission denied` 就該去那一篇
- [[01-PostgreSQL-安裝與初始化]] —— cluster、`pg_createcluster`、資料目錄的來龍去脈，本篇的路徑都從那裡來
- [[03-psql-操作與常用指令]] —— `\password`、`\drds`、`\dp` 這些排錯必用的反斜線指令
- [[08-PostgreSQL-安全強化]] —— 本篇是「連線層」的安全，那篇涵蓋 `pgaudit`、資料列層級安全（RLS）與稽核落地
- [[07-PostgreSQL-複寫與高可用]] —— `replication` 這一行規則的完整脈絡，以及切換時 `pg_hba.conf` 要跟著改什麼
- [[04-MySQL-設定檔與調校]] —— 對照組：MySQL 把來源限制放在帳號裡，PostgreSQL 放在獨立檔案，兩套模型的差異
- [[08-用自建CA簽發伺服器憑證]] —— `hostssl` 與 `cert` 認證需要的憑證怎麼簽、怎麼派送
- [[02-防火牆-ufw基礎與實務]] —— 四道關卡的第一關，`Connection timed out` 的解法在那裡

官方文件：

- PostgreSQL 17 — The pg_hba.conf File：<https://www.postgresql.org/docs/17/auth-pg-hba-conf.html>
- PostgreSQL 17 — User Name Maps（`pg_ident.conf`）：<https://www.postgresql.org/docs/17/auth-username-maps.html>
- PostgreSQL 17 — Connections and Authentication（`postgresql.conf` 參數）：<https://www.postgresql.org/docs/17/runtime-config-connection.html>
- PostgreSQL 17 — `pg_hba_file_rules` view：<https://www.postgresql.org/docs/17/view-pg-hba-file-rules.html>
- PostgreSQL APT Repository（PGDG）：<https://wiki.postgresql.org/wiki/Apt>
